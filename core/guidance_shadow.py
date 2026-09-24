"""RES-04 개별주 위성 shadow 실험: 발행사 가이던스 변화 feature를 champion 위성 후보에 병행 기록 (2026-09-22).

사전 등록 스펙: docs/EARNINGS_GUIDANCE_EXPERIMENT_SPEC.md — 특히 5절(주 지표·기준선·horizon), 6절
(최소 독립 사건 수), 7절(채택/기각/미입증 규칙). 이 모듈은 core.champion_strategy(위성 전략)와
core.earnings_events(가이던스 추출)를 "관측 전용"으로 잇는다.

핵심 불변식(반드시 지킨다):
    1. 원전략(위성)의 채택/보류 결정 자체는 절대 바꾸지 않는다. build_guidance_shadow_candidate_set()은
       core.candidate_ledger.champion_satellite_to_candidate_set()(수정하지 않음)이 이미 계산한 decision/
       decision_reason을 그대로 재사용하고, 가이던스 feature는 CandidateRecord.scores에 관측값으로만
       추가한다. 별도 strategy_version("champion_satellite/guidance_shadow_v1")으로 원전략 기록
       (core/candidate_recorder.py)과 분리해 동결 기록하므로 섞이지 않는다.
    2. 주문 경로(core.paper_execution, scripts/champion_paper_trade.py)는 이 모듈이 import도 호출도
       하지 않는다. record_candidate_set()이 쓰는 원장은 어떤 주문 로직도 읽지 않는다(RES-01과 동일 원칙).
    3. 판정 통계는 새로 만들지 않는다. evaluate_guidance_comparisons()는 후보 프레임의 decision 컬럼만
       비교군별로 다시 라벨링하고, 실제 판정은 core.candidate_ledger.evaluate_selection/decide_verdict를
       그대로 호출한다 — 표본이 6절 최소 조건에 못 미치면 그 게이트가 모든 비교군에 대해 자동으로
       VERDICT_UNPROVEN("미입증")을 강제한다(우회 불가).

알려진 한계(정직하게 남김, 다음 세션이 봐야 할 것):
    - compute_satellite_recommendation_point_in_time()은 top-K 채택 종목(picks/selected)만 반환하고,
      스펙 2절이 말하는 "후보 집합 C"(그날 돈치안 20일 돌파가 활성인 S&P500 종목 전체)는 반환하지
      않는다. 그 전체 후보 풀은 비공개 함수 _pick_satellite_at_date 내부의 active_scores에만 있고,
      이번 작업은 core/champion_strategy.py를 수정하지 않으므로 꺼낼 수 없다. 따라서 이 shadow는
      스펙 2절의 "채택 집합 A"(원전략이 실제로 고른 종목)만 관측한다 — held/rejected 반사실은 아직
      기록할 수 없다. 후보 풀 전체를 관측하려면 champion_strategy.py에 반환값을 추가하는 별도 작업이
      필요하다(주문 로직 미변경, 반환값 확장만이면 안전할 수 있음 — 사람 결정 필요).
    - 가이던스 발표의 완전한 시간 계약(source_publication/system_first_seen/extraction_completed)은
      실제 수집 파이프라인이 없으면 채울 수 없다. 이 모듈은 아는 값(acceptance_utc)만 source_publication에
      채우고 나머지는 비워 둔다 — core/candidate_recorder.py와 같은 관례이며, 그 결과
      core.candidate_ledger.compute_pit_status가 pit_certified=False를 매기고 decide_verdict가 그
      사실만으로 항상 '미입증'을 반환한다(원장 규칙을 우회하지 않는다).
    - 실제 SEC 조회(티커->CIK 매핑, 8-K 수집)는 이 모듈이 직접 하지 않는다(느린 전체 스캔 금지 지시).
      record_guidance_shadow()는 호출부가 미리 모은 core.earnings_events 결과(오프라인 fixture나 캐시)를
      GuidanceObservation 목록으로 주입해야 한다. 주입하지 않으면 모든 후보가 basis_status='no_release'로
      기록되고 실제 표본은 쌓이지 않는다 — 이번 세션이 확인한 현재 상태 그대로다.
    - 스케줄 배선(scheduler/run_scheduler.py 등록)은 이번 작업 범위 밖이다. record_guidance_shadow(as_of,
      session=None)만 호출 가능한 형태로 제공한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from core.candidate_ledger import (
    BOOTSTRAP_SEED,
    ELIGIBLE_DECISIONS,
    PRIMARY_COST_SCENARIO,
    PRIMARY_HORIZON_DAYS,
    CandidateRecord,
    FrozenCandidateSet,
    champion_satellite_to_candidate_set,
    evaluate_selection,
    load_outcome_frame,
    normalize_time,
    record_candidate_set,
)
from core.earnings_events import GuidanceChange

# ---------------------------------------------------------------------------
# 사전 고정 상수 (스펙 3·5절과 같은 값. 결과를 본 뒤 바꾸면 탐색 결과로만 취급한다)
# ---------------------------------------------------------------------------
GUIDANCE_SHADOW_STRATEGY_VERSION = "champion_satellite/guidance_shadow_v1"
GUIDANCE_SHADOW_SOURCE = "champion_satellite_guidance_shadow"

# 스펙 3절: 주 가설의 veto 규칙은 revenue·eps item만 쓴다(나머지 metric은 진단·기록용).
GUIDANCE_FEATURE_METRICS = ("revenue", "eps")
# 스펙 3절: 룩백은 주 horizon(20거래일)과 같은 값으로 미리 고정하며 튜닝하지 않는다.
PRIMARY_LOOKBACK_TRADING_DAYS = 20
# 실제 거래일력이 없을 때만 쓰는 근사(core.candidate_ledger._date_blocks와 같은 7/5 관례).
_CALENDAR_DAYS_PER_TRADING_DAY = 7.0 / 5.0

BASIS_CLEAR = "clear"
BASIS_UNKNOWN = "unknown"
BASIS_NO_RELEASE = "no_release"
BASIS_STATUSES = (BASIS_CLEAR, BASIS_UNKNOWN, BASIS_NO_RELEASE)

COMPARISON_ORIGINAL = "원전략"
COMPARISON_RAISED_ONLY = "raised_선호_단순규칙"
COMPARISON_RANDOM_SAME_COUNT = "동일_채택수_무작위"
COMPARISON_NAMES = (COMPARISON_ORIGINAL, COMPARISON_RAISED_ONLY, COMPARISON_RANDOM_SAME_COUNT)


# ---------------------------------------------------------------------------
# 입력/출력 데이터 구조
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GuidanceObservation:
    """revenue/eps 가이던스 변화 관측 1건 = core.earnings_events.GuidanceChange + 그 발표를 시스템이
    알 수 있었던 시각.

    available_at은 스펙 4절의 decision_cutoff 개념(그 발표 자체의 source_publication/system_first_seen/
    extraction_completed 중 가장 늦은 시각)이다. 실제 system_first_seen·extraction_completed를 모르면
    acceptance 시각(change.current.acceptance_utc)으로 근사하고 approximate=True로 남긴다 — 이 모듈은
    그 근사를 감춰서 확정 PIT 시각처럼 쓰지 않는다(호출부가 CandidateRecord의 다른 시간 필드를 비워
    두면 candidate_ledger.compute_pit_status가 자동으로 pit_certified=False를 매긴다).
    """

    ticker: str
    change: GuidanceChange
    available_at: Optional[datetime]
    approximate: bool = True


@dataclass(frozen=True)
class GuidanceFeature:
    """스펙 3절 V 플래그 + 진단 필드(순수 계산 결과). 이 자체로는 어떤 결정도 바꾸지 않는다."""

    ticker: str
    decision_cutoff: Optional[datetime]
    lookback_start: Optional[datetime]
    basis_status: str  # clear / unknown / no_release (스펙 3절 그대로)
    veto_flag: bool  # V: lowered/withdrawn이 하나 이상이고 raised가 없음
    latest_change: Optional[str]  # raised/lowered/maintained/initiated/withdrawn/unknown, 없으면 None
    change_magnitude_pct: Optional[float]  # 창 안에서 가장 최근 유효 관측의 mid_change_pct
    latest_available_at: Optional[datetime]  # 그 관측의 available_at(없으면 None)
    matched_metrics: tuple  # 창 안에서 비교 가능했던 metric들(revenue/eps 중)
    n_observations_in_window: int
    n_observations_total: int
    reason: str


def _lookback_start(
    decision_cutoff: datetime, lookback_trading_days: int, trading_days: Optional[Sequence[date]]
) -> datetime:
    """decision_cutoff으로부터 lookback_trading_days 거래일 전의 시작 시각. trading_days가 있으면 실제
    거래일력으로 정확히 계산하고, 없으면 7/5 근사(주말만 제외)를 쓴다 — candidate_ledger의 기존 관례와
    같은 근사이며 새로 발명하지 않는다."""
    if trading_days:
        idx = pd.DatetimeIndex(sorted(set(pd.Timestamp(d) for d in trading_days)))
        cutoff_date = pd.Timestamp(decision_cutoff).normalize()
        pos = int(idx.searchsorted(cutoff_date, side="left"))
        start_pos = max(0, pos - lookback_trading_days)
        if len(idx) > 0:
            start_pos = min(start_pos, len(idx) - 1)
            return idx[start_pos].to_pydatetime()
    calendar_days = int(np.ceil(lookback_trading_days * _CALENDAR_DAYS_PER_TRADING_DAY))
    return decision_cutoff - timedelta(days=calendar_days)


def compute_guidance_feature(
    ticker: str,
    decision_cutoff: Any,
    observations: Sequence[GuidanceObservation],
    *,
    lookback_trading_days: int = PRIMARY_LOOKBACK_TRADING_DAYS,
    trading_days: Optional[Sequence[date]] = None,
) -> GuidanceFeature:
    """스펙 3절의 veto 플래그 V와 진단 필드를 계산한다(순수 함수, 네트워크 없음, 결정에 아직 연결하지
    않음). observations는 이 ticker의 것만 넘겨도 되고(권장), 여러 ticker가 섞여 있으면 내부에서
    ticker가 일치하는 것만 쓴다.

    규칙(스펙 3절 그대로):
        - metric이 revenue/eps가 아니면 진단용이라 제외한다.
        - available_at이 없거나 decision_cutoff 이후(미래 정보)이면 그 관측은 쓰지 않는다.
        - available_at이 lookback 창(기본 20거래일, 근사 가능) 밖이면 쓰지 않는다.
        - 창 안에 유효 관측이 하나도 없으면 basis_status='no_release'.
        - 창 안 관측이 있지만 전부 change='unknown'이면 basis_status='unknown'(방향을 추측하지 않는다).
        - 창 안에 lowered/withdrawn이 하나 이상이고 raised가 하나도 없으면 veto_flag=True, basis_status='clear'.
        - 그 외(raised 있음, 또는 maintained/initiated뿐)는 veto_flag=False, basis_status='clear'.
        - latest_change/change_magnitude_pct는 창 안에서 available_at이 가장 늦은(가장 최근) 관측 기준.
    """
    tick = str(ticker).strip().upper()
    cutoff = normalize_time(decision_cutoff)
    n_total = len(observations)
    if cutoff is None:
        return GuidanceFeature(tick, None, None, BASIS_NO_RELEASE, False, None, None, None, (), 0, n_total,
                               "decision_cutoff_missing")

    start = _lookback_start(cutoff, lookback_trading_days, trading_days)
    in_window: list[tuple[datetime, GuidanceChange]] = []
    for obs in observations:
        if str(obs.ticker).strip().upper() != tick:
            continue
        change = obs.change
        current = change.current
        if current.metric not in GUIDANCE_FEATURE_METRICS:
            continue
        avail = normalize_time(obs.available_at)
        if avail is None or avail > cutoff or avail < start:
            continue
        in_window.append((avail, change))
    in_window.sort(key=lambda t: t[0])

    if not in_window:
        return GuidanceFeature(tick, cutoff, start, BASIS_NO_RELEASE, False, None, None, None, (), 0, n_total,
                               "no_guidance_release_in_window")

    labels = [chg.change for _, chg in in_window]
    metrics_seen = tuple(sorted({chg.current.metric for _, chg in in_window}))
    has_lower = any(lbl in ("lowered", "withdrawn") for lbl in labels)
    has_raise = any(lbl == "raised" for lbl in labels)
    all_unknown = all(lbl == "unknown" for lbl in labels)

    latest_avail, latest_change_obj = in_window[-1]
    latest_label = latest_change_obj.change
    mag = latest_change_obj.mid_change_pct
    latest_mag = None if mag is None else float(mag)

    if all_unknown:
        return GuidanceFeature(tick, cutoff, start, BASIS_UNKNOWN, False, latest_label, latest_mag, latest_avail,
                               metrics_seen, len(in_window), n_total, "all_observations_unknown_in_window")

    veto = bool(has_lower and not has_raise)
    reason = "lowered_or_withdrawn_without_raise" if veto else "no_veto_condition"
    return GuidanceFeature(tick, cutoff, start, BASIS_CLEAR, veto, latest_label, latest_mag, latest_avail,
                           metrics_seen, len(in_window), n_total, reason)


def guidance_feature_to_scores(feature: GuidanceFeature) -> dict:
    """GuidanceFeature -> CandidateRecord.scores에 얹을 JSON 안전 dict. 접두사 'guidance_'로 원전략
    점수 필드와 절대 겹치지 않게 한다."""
    return {
        "guidance_basis_status": feature.basis_status,
        "guidance_veto_flag": feature.veto_flag,
        "guidance_latest_change": feature.latest_change,
        "guidance_change_magnitude_pct": feature.change_magnitude_pct,
        "guidance_matched_metrics": list(feature.matched_metrics),
        "guidance_n_observations_in_window": feature.n_observations_in_window,
        "guidance_n_observations_total": feature.n_observations_total,
        "guidance_lookback_trading_days": PRIMARY_LOOKBACK_TRADING_DAYS,
        "guidance_feature_reason": feature.reason,
    }


# ---------------------------------------------------------------------------
# 어댑터: 위성 원전략 결과 -> 가이던스 shadow 후보 집합 (원전략 decision을 바꾸지 않는다)
# ---------------------------------------------------------------------------
def _normalize_event_keys(events_by_ticker: Optional[Mapping[str, Sequence[GuidanceObservation]]]) -> dict:
    if not events_by_ticker:
        return {}
    return {str(k).strip().upper(): v for k, v in events_by_ticker.items()}


def build_guidance_shadow_candidate_set(
    satellite_result: dict,
    *,
    base_strategy_version: str,
    decision_cutoff: Any,
    events_by_ticker: Optional[Mapping[str, Sequence[GuidanceObservation]]] = None,
    shadow_strategy_version: str = GUIDANCE_SHADOW_STRATEGY_VERSION,
    source: str = GUIDANCE_SHADOW_SOURCE,
    lookback_trading_days: int = PRIMARY_LOOKBACK_TRADING_DAYS,
    trading_days: Optional[Sequence[date]] = None,
) -> FrozenCandidateSet:
    """champion_satellite_to_candidate_set()(core.candidate_ledger, 수정하지 않음)이 계산한 원전략
    decision/decision_reason을 한 글자도 바꾸지 않고 재사용하며, 각 후보에 가이던스 feature만 scores에
    추가해 별도 strategy_version으로 동결 기록할 후보 집합을 만든다.

    order_proposal은 shadow 행에 담지 않는다 — 이 원장은 주문을 제안하지 않는 관측 전용 병행 기록이며,
    스코어에 order_proposal이 있으면 이 shadow가 원전략에 영향을 주는 것처럼 오해될 수 있어 비워 둔다.

    한계: compute_satellite_recommendation_point_in_time() 결과에는 후보 풀(candidates)이 없으므로
    (모듈 docstring 참고) champion_satellite_to_candidate_set()도 selected/held(신규 주문 보류 시)만
    반환한다 — 이 함수가 관측하는 것은 스펙 2절의 "채택 집합 A"이며 "후보 집합 C" 전체가 아니다.
    """
    base_set = champion_satellite_to_candidate_set(
        satellite_result, strategy_version=base_strategy_version, decision_cutoff=decision_cutoff)
    cutoff = base_set.decision_cutoff
    events = _normalize_event_keys(events_by_ticker)

    records: list[CandidateRecord] = []
    n_with_release = 0
    n_veto = 0
    for r in base_set.records:
        obs = events.get(r.ticker, ())
        feature = compute_guidance_feature(
            r.ticker, cutoff, obs, lookback_trading_days=lookback_trading_days, trading_days=trading_days)
        if feature.basis_status != BASIS_NO_RELEASE:
            n_with_release += 1
        if feature.veto_flag:
            n_veto += 1
        scores = {**(r.scores or {}), **guidance_feature_to_scores(feature)}
        records.append(CandidateRecord(
            ticker=r.ticker,
            decision=r.decision,  # 원전략 결정 그대로 — 이 함수는 절대 바꾸지 않는다
            decision_reason=r.decision_reason,
            scores=scores,
            rank=r.rank,
            sector=r.sector,
            sector_etf=r.sector_etf,
            source_publication=feature.latest_available_at,  # 아는 값만(system_first_seen 등은 비움)
            decision_cutoff=cutoff,
        ))

    meta = {
        "adapter": "guidance_shadow",
        "base_strategy_version": base_strategy_version,
        "lookback_trading_days": lookback_trading_days,
        "guidance_feature_metrics": list(GUIDANCE_FEATURE_METRICS),
        "n_candidates": len(records),
        "n_candidates_with_release_in_window": n_with_release,
        "n_candidates_veto_flagged": n_veto,
        "base_meta": base_set.meta,
        "note": (
            "관측 전용 병행 기록. 원전략(위성) 채택/보류 결정을 바꾸지 않는다. 주문 경로와 연결되지 "
            "않는다. compute_satellite_recommendation_point_in_time 은 채택 종목만 반환하므로 이 집합은 "
            "스펙 2절의 채택 집합 A만 관측한다(후보 집합 C 전체 아님)."
        ),
    }
    return FrozenCandidateSet(source, shadow_strategy_version, cutoff, records, meta)


def _cutoff_for(as_of: date) -> datetime:
    """가격·재무 기반 시각 관례(core/candidate_recorder.py와 동일): 날짜만 주면 그 날 장 마감 이후로
    해석한다(normalize_time이 날짜만 받으면 그 날 23:59:59 미 동부로 처리하는 관례를 그대로 따른다).
    시각을 지어내지 않기 위해 여기서 시:분:초를 직접 만들지 않고 날짜만 넘긴다."""
    return datetime.combine(as_of, datetime.min.time())


def record_guidance_shadow(
    as_of: Optional[date] = None,
    *,
    session=None,
    satellite_result: Optional[dict] = None,
    events_by_ticker: Optional[Mapping[str, Sequence[GuidanceObservation]]] = None,
    base_strategy_version: Optional[str] = None,
    lookback_trading_days: int = PRIMARY_LOOKBACK_TRADING_DAYS,
    trading_days: Optional[Sequence[date]] = None,
) -> dict:
    """RES-04 개별주 위성 shadow 기록의 단일 진입점.

    - satellite_result를 주지 않으면 core.champion_strategy.compute_satellite_recommendation_point_in_time을
      직접 호출한다(느림 — point-in-time 유니버스 표본추출+가격조회가 필요하므로 실제 배선 시 job_manager로
      감싸야 한다. core/candidate_recorder.py의 champion_satellite 잡과 같은 주의사항).
    - events_by_ticker를 주지 않으면 빈 dict로 취급한다 — 이 경우 모든 후보가 basis_status='no_release'로
      기록된다. 실제 SEC 조회·티커->CIK 매핑은 이번 작업 범위 밖이며 이 함수는 느린 전체 스캔을 하지
      않는다(지시 사항). 호출부가 core.earnings_events로 미리 모은 관측을 GuidanceObservation 목록으로
      주입해야 실제 신호가 쌓인다.
    - 스케줄러(scheduler/run_scheduler.py) 등록은 이 함수의 책임이 아니다 — 다음 세션이 별도로 배선한다.
    - 주문 경로(core.paper_execution, scripts/champion_paper_trade.py)는 import도 호출도 하지 않는다.
    - 같은 날 재실행은 멱등이다(candidate_set_id가 이미 있으면 record_candidate_set이 아무것도 바꾸지 않는다).

    Returns: {"as_of", "ok", "n_pool", "n_with_events_provided", ...} 또는 위성 원전략 자체가 실패하면
    {"as_of", "ok": False, "error": ...}(예외를 삼키지 않고 사유를 남긴다).
    """
    as_of_date = as_of or date.today()
    events = events_by_ticker or {}
    try:
        if satellite_result is None:
            from core.champion_strategy import compute_satellite_recommendation_point_in_time

            satellite_result = compute_satellite_recommendation_point_in_time(as_of_date=as_of_date.isoformat())
        sizing = satellite_result.get("sizing_method", "equal")
        base_version = base_strategy_version or f"champion_satellite/{sizing}"
        cset = build_guidance_shadow_candidate_set(
            satellite_result, base_strategy_version=base_version, decision_cutoff=_cutoff_for(as_of_date),
            events_by_ticker=events, lookback_trading_days=lookback_trading_days, trading_days=trading_days)
    except Exception as exc:  # noqa: BLE001 - 위성 원전략 실패 사유를 삼키지 않고 보고한다
        return {"as_of": as_of_date.isoformat(), "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    result = record_candidate_set(cset, session=session)
    result["as_of"] = as_of_date.isoformat()
    result["n_pool"] = len(cset.records)
    result["n_with_events_provided"] = len(_normalize_event_keys(events))
    result["ok"] = True
    return result


# ---------------------------------------------------------------------------
# 3개 비교군 판정 (새 통계 규칙 없음 — candidate_ledger.evaluate_selection/decide_verdict 재사용)
# ---------------------------------------------------------------------------
def _fetch_scores_by_id(decision_ids: Iterable[int], session=None) -> dict:
    """CandidateDecision.scores(JSON 문자열)를 decision_id -> dict로 읽는다. 읽기 전용 쿼리."""
    from core.models import CandidateDecision

    ids = list(decision_ids)
    if not ids:
        return {}
    if session is not None:
        rows = session.query(CandidateDecision.id, CandidateDecision.scores).filter(
            CandidateDecision.id.in_(ids)).all()
    else:
        from core.db import get_session, init_db

        init_db()
        with get_session() as s:
            rows = s.query(CandidateDecision.id, CandidateDecision.scores).filter(
                CandidateDecision.id.in_(ids)).all()
    out = {}
    for did, raw in rows:
        try:
            out[did] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            out[did] = {}
    return out


GUIDANCE_SCORE_COLUMNS = (
    "guidance_basis_status", "guidance_veto_flag", "guidance_latest_change", "guidance_change_magnitude_pct",
)


def load_guidance_feature_frame(
    session=None, *, horizon: int = PRIMARY_HORIZON_DAYS, strategy_version: str = GUIDANCE_SHADOW_STRATEGY_VERSION,
    cost_scenario: str = PRIMARY_COST_SCENARIO,
) -> pd.DataFrame:
    """가이던스 shadow 원장(기본 strategy_version=guidance_shadow_v1)에서 candidate_ledger.load_outcome_frame과
    같은 결과 프레임에 guidance_* feature 컬럼을 얹어 반환한다. 통계 로직은 추가하지 않는다 — 이 함수는
    scores(JSON)에 저장된 이미 계산된 feature를 컬럼으로 풀어내기만 한다."""
    base = load_outcome_frame(
        session, horizon, strategy_version=strategy_version, source=GUIDANCE_SHADOW_SOURCE,
        cost_scenario=cost_scenario)
    if base.empty:
        for col in GUIDANCE_SCORE_COLUMNS:
            base[col] = pd.Series(dtype=object)
        return base
    scores_by_id = _fetch_scores_by_id(base["decision_id"].tolist(), session=session)
    for col in GUIDANCE_SCORE_COLUMNS:
        base[col] = base["decision_id"].map(lambda i: scores_by_id.get(i, {}).get(col))
    return base


def _relabel_raised_only(frame: pd.DataFrame) -> pd.DataFrame:
    """비교군 2: '가이던스 feature=raised인 후보만 선호하는 단순 규칙'. 원전략이 채택할 수 있었던 풀
    (ELIGIBLE_DECISIONS = selected/held/rejected) 안에서만 다시 라벨링한다 —
    guidance_latest_change=='raised'인 후보는 selected, 나머지는 held. missing_data는 그대로 둔다
    (결측을 채택/보류로 지어내지 않는다, candidate_ledger 원칙과 동일). 통계 판정은 이 함수가 하지 않고
    호출부가 candidate_ledger.evaluate_selection에 넘긴다."""
    out = frame.copy()
    if out.empty:
        return out
    eligible = out["decision"].isin(ELIGIBLE_DECISIONS)
    is_raised = out.get("guidance_latest_change") == "raised"
    out.loc[eligible & is_raised, "decision"] = "selected"
    out.loc[eligible & ~is_raised, "decision"] = "held"
    return out


def _relabel_random_same_count(frame: pd.DataFrame, *, seed: int = BOOTSTRAP_SEED) -> pd.DataFrame:
    """비교군 3: 원전략과 같은 채택 수(n_selected)를 유지한 채 무작위로 채택을 다시 뽑는다(고정 시드,
    재현 가능). 후보 풀(ELIGIBLE_DECISIONS)이 채택 수보다 작으면 전원 채택한다. missing_data는 그대로
    둔다. 통계 판정은 하지 않는다(evaluate_selection에 넘길 프레임만 만든다)."""
    out = frame.copy()
    if out.empty:
        return out
    eligible_mask = out["decision"].isin(ELIGIBLE_DECISIONS)
    n_selected = int((out["decision"] == "selected").sum())
    eligible_idx = out.index[eligible_mask].to_numpy()
    rng = np.random.default_rng(seed)
    if len(eligible_idx) and n_selected > 0:
        k = min(n_selected, len(eligible_idx))
        chosen = rng.choice(eligible_idx, size=k, replace=False)
    else:
        chosen = np.array([], dtype=eligible_idx.dtype if len(eligible_idx) else int)
    out.loc[eligible_mask, "decision"] = "held"
    if len(chosen):
        out.loc[chosen, "decision"] = "selected"
    return out


def evaluate_guidance_comparisons(
    session=None, *, horizon: int = PRIMARY_HORIZON_DAYS, strategy_version: str = GUIDANCE_SHADOW_STRATEGY_VERSION,
    cost_scenario: str = PRIMARY_COST_SCENARIO, seed: int = BOOTSTRAP_SEED, **eval_kwargs,
) -> dict:
    """스펙이 정한 3개 비교군(원전략 / feature=raised 선호 단순 규칙 / 동일 채택수 무작위)을 같은
    가이던스 shadow 프레임에서 계산한다.

    새 통계 규칙은 만들지 않는다 — 세 프레임 모두 candidate_ledger.evaluate_selection(내부에서
    decide_verdict를 호출)에 그대로 넘긴다. 표본이 6절 최소 조건(MIN_SELECTED_FOR_VERDICT 등)에 못
    미치면 evaluate_selection의 기존 게이트가 세 비교군 모두에 대해 VERDICT_UNPROVEN('미입증')을
    강제한다(우회하지 않는다).

    Returns: {COMPARISON_ORIGINAL: {...evaluate_selection 결과...}, COMPARISON_RAISED_ONLY: {...},
              COMPARISON_RANDOM_SAME_COUNT: {...}}
    """
    frame = load_guidance_feature_frame(
        session, horizon=horizon, strategy_version=strategy_version, cost_scenario=cost_scenario)
    frames = {
        COMPARISON_ORIGINAL: frame,
        COMPARISON_RAISED_ONLY: _relabel_raised_only(frame),
        COMPARISON_RANDOM_SAME_COUNT: _relabel_random_same_count(frame, seed=seed),
    }
    return {
        name: evaluate_selection(f, horizon=horizon, cost_scenario=cost_scenario, seed=seed, **eval_kwargs)
        for name, f in frames.items()
    }
