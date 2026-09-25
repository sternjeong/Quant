"""RES-05: 위성 모멘텀 후보에 대한 공시 변화 veto shadow 실험 — 관측 전용 어댑터.

스펙: docs/FILING_CHANGE_VETO_SPEC.md (사전 등록 초안, 미동결). 이 모듈은 그 스펙의 §8(비교 대상 3종·veto
규칙 v0)을 core.filing_changes.filing_veto(정책 변경 없이 그대로) 와 core.candidate_ledger(RES-01 원장)에
연결하는 얇은 어댑터다. 새 통계 규칙이나 새 veto 규칙을 만들지 않는다 — 두 기존 모듈을 그대로 호출할 뿐이다.

RES-02 연결(2026-09-25): 각 후보 행에 대표 공시(쓸 수 있는 이벤트 중 가장 최근, 없으면 받은 이벤트 중 가장
최근)의 event_id(core.info_dedup.compute_event_id — sec_edgar/accession/ticker/form)·content_hash(원문 sha256,
core.filing_changes 가 계산한 current_doc_sha256)·info_doc_id(accession)를 populate_info_fields 로 채우고,
평가한 모든 공시의 event_id 는 scores["filing_event_ids"] 에 남긴다. 같은 10-K/10-Q 가 여러 날의 후보 행에
반복 등장해도 같은 event_id 라서 독립 근거로 중복 집계되지 않게 할 수 있다. veto 판정 자체는 바뀌지 않는다.

이 모듈이 하는 일 (그리고 하지 않는 일):
    1. record_filing_veto_shadow(): core.champion_strategy.compute_satellite_recommendation_point_in_time
       (읽기 전용 호출, 수정하지 않는다)이 오늘 채택한 위성 후보 각각에 core.filing_changes.filing_veto 를
       적용한 hold/pass 판정을, 원전략과 **다른** strategy_version/source(SHADOW_STRATEGY_VERSION/
       SHADOW_SOURCE)로 core.candidate_ledger 에 병행 기록한다. 원전략이 실제로 채택한 종목·주문·보유는
       이 함수가 절대 읽거나 바꾸지 않는다 — champion_strategy 의 반환값을 그대로 읽기만 하고, 기록은
       완전히 별개의 후보 집합(candidate_set_id 가 strategy_version 을 포함한 해시라 원장에서도 물리적으로
       분리된다)으로 남는다. core.paper_execution, scripts/champion_paper_trade.py 는 import 하지 않는다.
    2. evaluate_filing_veto_shadow_arms(): 스펙 §8 의 3개 비교군(A 원전략/B 단순 규칙 veto/C 동일 거래수
       무작위 보류)을 core.candidate_ledger.evaluate_selection 을 그대로(반복 호출만) 써서 계산한다.
       - Arm B(단순 규칙 veto)는 기록된 그대로(veto pass=selected, veto hold=held)에 evaluate_selection
         을 호출한 결과다. groups.rest(=missed_opportunity)가 스펙이 요구하는 "veto 로 보류한 종목의
         기회비용"이고, incremental 이 그 군집 부트스트랩 비교다 — candidate_ledger 의 기존 지표를 그대로
         쓴다(새로 만들지 않는다).
       - Arm C(동일 거래수 무작위 보류)는 evaluate_selection 이 이미 계산하는
         groups.random_baseline_expected / incremental.selected_minus_random / random_baseline_mc 를
         그대로 쓴다(같은 배치·같은 선택률의 무작위 보류 몬테카를로 — 스펙 Arm C 와 같은 목적의 기존 지표).
       - Arm A(원전략, veto 없음)는 같은 프레임을 전량 selected 로 재표시만 해 evaluate_selection 을
         두 번째로 호출한 결과다(모두 채택했을 때의 비용 후 평균 — 알고리즘이 아니라 라벨만 바꾼 재호출).
       - verdict/verdict_reasons 는 Arm B 호출이 내부에서 이미 실행한 decide_verdict 출력을 그대로
         반환한다. 표본이 candidate_ledger 의 최소 표본 게이트(MIN_SELECTED_FOR_VERDICT 등)를 못 채우면
         자동으로 '미입증'이 되며, 이 모듈은 그 판정을 우회하거나 덮어쓰지 않는다.
    3. filing_veto 규칙 자체(§8 v0)는 core.filing_changes.FilingVetoPolicy 기본값을 그대로 쓴다. 이
       모듈은 그 정책 파라미터를 바꾸지 않는다(호출자가 policy 인자로 바꿀 수는 있으나 기본값은 스펙 그대로).

시간 계약: 위성 후보의 decision_cutoff 는 그 날짜(date)를 그대로 CandidateRecord 에 넘긴다 —
core.candidate_ledger.normalize_time 이 날짜만 받으면 그 날 23:59:59 America/New_York(장 마감 후) ->
다음 거래일 시가 체결로 해석하는 관례를 그대로 따른다(시각을 지어내지 않는다). source_publication 등
나머지 4개 시간 계약 필드는 채우지 않으므로 pit_certified 는 core.candidate_ledger.compute_pit_status 규칙
그대로 항상 False 다 — core.filing_changes 자체도 아직 독립적인 PIT 인증 절차가 없다(파일 자체 문서 참고).
이는 이 모듈의 한계이자 정직한 기본값이며 우회하지 않는다.

"노출된 후보"(스펙 §3) 판정: filing_veto 가 실제로 사용한("usable") 이벤트 중 available_at 이
decision_cutoff 로부터 EXPOSURE_WINDOW_CALENDAR_DAYS(스펙 §3 의 W=10 거래일을, candidate_ledger.py 의
"거래일*7/5=달력일" 관례와 같은 방식으로 근사한 값) 이내인 것이 하나라도 있으면 exposed=True 로 표시해
scores 에 남긴다. 이 값은 evaluate_filing_veto_shadow_arms(exposed_only=True, 기본값)가 주 분석 표본을
스펙 §3 정의에 맞게 거르는 데 쓰인다 — veto 규칙 자체(§8)의 max_event_age_days(기본 45일, 더 느슨한
정책값)와는 별개 개념이다(둘을 하나로 합치지 않는다).

알려진 한계(정직하게 남긴다):
    - compute_satellite_recommendation_point_in_time 은 top_k 로 이미 선정된 종목(선정 시점의 사실상 유일한
      외부 공개 후보 목록)만 돌려주고, 돈치안 브레이크아웃이 활성인 전체 풀(active_scores)은 반환하지 않는다.
      champion_strategy.py 를 수정하지 않는 제약 때문에 이 모듈이 볼 수 있는 "후보"는 top_k 선정 종목뿐이다.
      진짜 "선정 전 브레이크아웃 풀"에 대한 veto 실험은 champion_strategy 쪽에 pool 반환 기능이 추가되어야
      가능하다(다음 연결 지점).
    - 기본 이벤트 공급자(_default_event_provider)는 core.filing_changes.EdgarClient 로 "현재" 기준 최신
      10-K/10-Q를 가져온다. EDGAR 에는 "특정 과거 시점 기준 최신 공시" 조회가 없으므로 이 기본 공급자는
      forward(오늘 as_of) shadow 에만 적절하고, as_of 를 과거로 주면 point-in-time 이 아니다(어차피
      pit_certified 는 항상 False 이므로 성과를 주장하는 데 쓰이지 않는다). 과거 재구성이 필요하면
      event_provider 를 별도로 주입해야 한다.
"""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, Optional

from core.candidate_ledger import (
    CandidateRecord,
    DISCLAIMER,
    FrozenCandidateSet,
    PRIMARY_COST_SCENARIO,
    PRIMARY_HORIZON_DAYS,
    PRIMARY_TARGET,
    evaluate_selection,
    load_outcome_frame,
    normalize_time,
    record_candidate_set,
)
from core.filing_changes import FilingVetoPolicy, filing_veto
from core.info_dedup import compute_event_id, populate_info_fields

SHADOW_SOURCE = "champion_satellite_filing_veto_shadow"
SHADOW_STRATEGY_VERSION = "champion_satellite/filing_veto_shadow_v1"

# 스펙 §3 의 W=10 거래일을 달력일로 근사(candidate_ledger.py 의 block_days = horizon*7/5 관례와 동일 방식).
EXPOSURE_WINDOW_TRADING_DAYS = 10
EXPOSURE_WINDOW_CALENDAR_DAYS = int(math.ceil(EXPOSURE_WINDOW_TRADING_DAYS * 7 / 5))  # 14


# ---------------------------------------------------------------------------
# 공용 유틸
# ---------------------------------------------------------------------------
@contextmanager
def _local_session_scope(session=None):
    """읽기 전용 조회용 세션 스코프(record_candidate_set 과 별개 — 이 모듈은 쓰기 시 candidate_ledger 의
    record_candidate_set 에 세션 관리를 위임하고, 읽기 시에만 이 헬퍼를 쓴다)."""
    if session is not None:
        yield session
        return
    from core.db import get_session, init_db

    init_db()
    with get_session() as s:
        yield s


def _age_calendar_days(available_at_iso: Optional[str], cutoff_aware_utc: Optional[datetime]) -> Optional[float]:
    if not available_at_iso or cutoff_aware_utc is None:
        return None
    try:
        dt = datetime.strptime(available_at_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (cutoff_aware_utc - dt).total_seconds() / 86400.0


def _extract_selected_tickers(satellite_result: dict) -> list:
    """compute_satellite_recommendation_point_in_time 결과의 'selected'(list[str]) 만 쓴다.

    breakout 풀(active_scores) 은 그 함수가 외부로 반환하지 않아(모듈 docstring의 "알려진 한계" 참고)
    top_k 선정 종목만 후보로 다룬다. 중복은 제거하되 순서는 보존한다.
    """
    out: list = []
    seen: set = set()
    for t in satellite_result.get("selected") or []:
        tu = str(t).strip().upper()
        if tu and tu not in seen:
            seen.add(tu)
            out.append(tu)
    return out


INFO_EVENT_SOURCE = "sec_edgar"


def _event_info_id(ticker: str, event: Any) -> Optional[str]:
    accession = getattr(event, "accession", None)
    if not accession:
        return None
    return compute_event_id(INFO_EVENT_SOURCE, accession, getattr(event, "ticker", None) or ticker,
                            getattr(event, "form", None) or "")


def filing_info_kwargs(record_kwargs: dict, ticker: str, events: list, usable_events: list) -> dict:
    """대표 공시의 info_* 필드를 CandidateRecord kwargs 에 채운다(순수 함수). 대표 = 쓸 수 있는 이벤트 중
    available_at 이 가장 늦은 것, 없으면 받은 이벤트 중 filing_date 가 가장 늦은 것. 이벤트가 없으면 그대로."""
    pool = [e for e in usable_events if getattr(e, "accession", None)]
    key = lambda e: (getattr(e, "available_at", None) or "", getattr(e, "filing_date", None) or "")  # noqa: E731
    if not pool:
        pool = [e for e in events if getattr(e, "accession", None)]
        key = lambda e: (getattr(e, "filing_date", None) or "", getattr(e, "available_at", None) or "")  # noqa: E731
    if not pool:
        return dict(record_kwargs)
    primary = max(pool, key=key)
    return populate_info_fields(
        record_kwargs,
        event_id=_event_info_id(ticker, primary),
        content_hash=getattr(primary, "current_doc_sha256", None) or None,
        info_doc_id=primary.accession,
    )


def _default_event_provider(ticker: str, decision_cutoff: Any) -> list:
    """운영 기본 공급자: core.filing_changes.EdgarClient(파일 캐시 재사용)로 10-K/10-Q 각각 최신 원본과
    직전 원본을 내려받아 FilingChangeEvent 를 만든다. decision_cutoff 는 이 기본 공급자에서는 쓰이지
    않는다(모듈 docstring의 한계 참고 — forward shadow 전용). 공시가 없거나 조회에 실패하면 그 form 은
    건너뛴다(느린 재시도로 전체 스캔을 막지 않는다 — max_retries 는 EdgarClient 기본값을 그대로 쓴다).
    """
    from core.filing_changes import EdgarClient, EdgarFetchError, build_latest_filing_change_event

    client = EdgarClient()
    events = []
    for form in ("10-K", "10-Q"):
        try:
            events.append(build_latest_filing_change_event(client, ticker=ticker, form=form, mode="retrospective"))
        except EdgarFetchError:
            continue
    return events


# ---------------------------------------------------------------------------
# 기록: record_filing_veto_shadow
# ---------------------------------------------------------------------------
def record_filing_veto_shadow(
    as_of: Optional[date] = None,
    *,
    session=None,
    satellite_result: Optional[dict] = None,
    event_provider: Optional[Callable[[str, Any], Iterable]] = None,
    policy: Optional[FilingVetoPolicy] = None,
    sizing_method: str = "equal",
    pool_n: Optional[int] = None,
    top_k: Optional[int] = None,
) -> dict:
    """오늘 위성 후보(compute_satellite_recommendation_point_in_time)에 filing_veto 판정을 병행 기록한다.

    원전략 함수는 읽기만 한다(수정하지 않는다). 기록은 SHADOW_STRATEGY_VERSION/SHADOW_SOURCE 로만 남아
    원전략의 실제 채택/보류 결정(다른 strategy_version 으로 기록되는 RES-01 원장, core.paper_execution 의
    실제 주문)에 전혀 영향을 주지 않는다. 같은 날 재실행은 record_candidate_set 의 멱등성을 그대로 물려받는다
    (같은 candidate_set_id 가 이미 있으면 아무것도 바꾸지 않는다).

    satellite_result 를 주면(테스트) compute_satellite_recommendation_point_in_time 을 호출하지 않는다.
    event_provider(ticker, decision_cutoff) -> Iterable[FilingChangeEvent] 를 주면(테스트/백필)
    _default_event_provider(실제 EDGAR 조회) 대신 쓴다. 한 종목의 조회 실패는 그 종목만 pass 로 기본
    처리하고 나머지는 계속 진행한다(veto 판정 불가를 hold 로 잘못 해석하지 않는다).
    """
    as_of_date = as_of if isinstance(as_of, date) and not isinstance(as_of, datetime) else (
        as_of.date() if isinstance(as_of, datetime) else (as_of or date.today())
    )

    if satellite_result is None:
        from core.champion_strategy import compute_satellite_recommendation_point_in_time  # 읽기 전용 호출

        kwargs: dict = {"as_of_date": as_of_date.isoformat(), "sizing_method": sizing_method}
        if pool_n is not None:
            kwargs["pool_n"] = pool_n
        if top_k is not None:
            kwargs["top_k"] = top_k
        satellite_result = compute_satellite_recommendation_point_in_time(**kwargs)

    pol = policy or FilingVetoPolicy()
    provider = event_provider or _default_event_provider
    cutoff_naive_utc = normalize_time(as_of_date)
    cutoff_aware_utc = cutoff_naive_utc.replace(tzinfo=timezone.utc) if cutoff_naive_utc is not None else None

    tickers = _extract_selected_tickers(satellite_result)
    records: list = []
    per_ticker: dict = {}
    # 스펙 §3.3: 추출·비교 실패 건은 "pass" 로 묻지 않고 사유별로 센다(주 분석 분모에서 조용히 빼지 않는다).
    unusable_reason_counts: dict = {}

    for t in tickers:
        try:
            events = list(provider(t, as_of_date))
        except Exception as exc:  # noqa: BLE001 - 한 종목의 조회 실패가 나머지 기록을 막지 않는다
            err = f"{type(exc).__name__}: {exc}"
            unusable_reason_counts["event_fetch_error"] = unusable_reason_counts.get("event_fetch_error", 0) + 1
            per_ticker[t] = {"error": err, "veto_decision": "pass", "exposed": False, "reason_codes": ["event_fetch_error"]}
            records.append(CandidateRecord(
                ticker=t, decision="selected", decision_reason="filing_event_fetch_error_defaulted_to_pass",
                scores={"veto_decision": "pass", "exposed": False, "error": err, "original_decision": "selected"},
                decision_cutoff=as_of_date,
            ))
            continue

        veto = filing_veto(events, pol, as_of=cutoff_aware_utc)
        for u in veto.unusable_events:
            rc = str(u.get("reason") or "unknown")
            unusable_reason_counts[rc] = unusable_reason_counts.get(rc, 0) + 1
        if not events:
            unusable_reason_counts["no_filing_found"] = unusable_reason_counts.get("no_filing_found", 0) + 1
        unusable_acc = {u.get("accession") for u in veto.unusable_events}
        usable_events = [e for e in events if e.accession not in unusable_acc]
        ages = [a for a in (_age_calendar_days(e.available_at, cutoff_aware_utc) for e in usable_events) if a is not None]
        min_age = min(ages) if ages else None
        exposed = bool(usable_events) and min_age is not None and min_age <= EXPOSURE_WINDOW_CALENDAR_DAYS

        decision = "held" if veto.decision == "hold" else "selected"
        reason = f"filing_veto_{pol.version}:{veto.decision}:{','.join(veto.reason_codes) or 'none'}"
        scores = {
            "veto_decision": veto.decision,
            "veto_reason_codes": list(veto.reason_codes),
            "veto_policy_version": veto.policy_version,
            "veto_reasons": [asdict(r) for r in veto.reasons],
            "veto_suppressed": [asdict(r) for r in veto.suppressed],
            "exposed": exposed,
            "n_events_evaluated": len(veto.evaluated_accessions),
            "n_usable_events": len(usable_events),
            "min_event_age_calendar_days": min_age,
            "unusable_events": veto.unusable_events,
            "original_decision": "selected",  # 이 후보는 이미 원전략(위성)이 채택한 종목이다
            # RES-02: 평가한 모든 공시의 결정적 event_id(같은 공시는 날짜·후보와 무관하게 같은 값).
            "filing_event_ids": sorted({i for i in (_event_info_id(t, e) for e in events) if i}),
        }
        record_kwargs = dict(ticker=t, decision=decision, decision_reason=reason, scores=scores,
                             decision_cutoff=as_of_date)
        records.append(CandidateRecord(**filing_info_kwargs(record_kwargs, t, events, usable_events)))
        per_ticker[t] = {"veto_decision": veto.decision, "exposed": exposed, "reason_codes": list(veto.reason_codes)}

    cset = FrozenCandidateSet(
        source=SHADOW_SOURCE, strategy_version=SHADOW_STRATEGY_VERSION, decision_cutoff=as_of_date, records=records,
        meta={
            "adapter": "filing_veto_shadow", "policy_version": pol.version,
            "base_satellite_as_of": satellite_result.get("as_of"),
            "base_satellite_rebal_date": satellite_result.get("rebal_date"),
            "base_satellite_sizing_method": satellite_result.get("sizing_method"),
            "note": ("관측 전용 shadow 기록이다. 원전략(champion_satellite)의 실제 채택/보류 결정과 주문 "
                     "경로에 영향을 주지 않는다. docs/FILING_CHANGE_VETO_SPEC.md 미동결, 성과 미검증."),
        },
    )
    result = record_candidate_set(cset, session=session)
    result.update({
        "as_of": as_of_date.isoformat(),
        "strategy_version": SHADOW_STRATEGY_VERSION,
        "source": SHADOW_SOURCE,
        "n_candidates": len(records),
        "n_exposed": sum(1 for v in per_ticker.values() if v.get("exposed")),
        "n_held_by_veto": sum(1 for r in records if r.decision == "held"),
        "n_not_exposed": sum(1 for v in per_ticker.values() if not v.get("exposed")),
        "unusable_reason_counts": dict(unusable_reason_counts),
        "exposure_window_calendar_days": EXPOSURE_WINDOW_CALENDAR_DAYS,
        "per_ticker": per_ticker,
        "shadow_only": True,
        "order_path_connected": False,
    })
    return result


# ---------------------------------------------------------------------------
# 평가: evaluate_filing_veto_shadow_arms
# ---------------------------------------------------------------------------
def _load_exposed_decision_ids(session=None, *, strategy_version: str = SHADOW_STRATEGY_VERSION,
                               source: str = SHADOW_SOURCE) -> set:
    from core.models import CandidateDecision

    with _local_session_scope(session) as s:
        rows = s.query(CandidateDecision.id, CandidateDecision.scores).filter(
            CandidateDecision.strategy_version == strategy_version, CandidateDecision.source == source,
        ).all()
    out: set = set()
    for decision_id, scores_json in rows:
        try:
            scores = json.loads(scores_json) if scores_json else {}
        except (TypeError, ValueError):
            scores = {}
        if scores.get("exposed"):
            out.add(int(decision_id))
    return out


def evaluate_filing_veto_shadow_arms(
    frame=None,
    *,
    session=None,
    horizon: int = PRIMARY_HORIZON_DAYS,
    value_col: str = PRIMARY_TARGET,
    cost_scenario: str = PRIMARY_COST_SCENARIO,
    exposed_only: bool = True,
    exposed_decision_ids: Optional[set] = None,
    **eval_kwargs,
) -> dict:
    """스펙 §8 의 3개 비교군(A 원전략/B 단순 규칙 veto/C 동일 거래수 무작위 보류)을
    core.candidate_ledger.evaluate_selection/decide_verdict 로만 계산한다(새 통계 규칙 없음).

    frame 을 안 주면 record_filing_veto_shadow 가 기록한 shadow 원장을 DB 에서 읽는다
    (load_outcome_frame(strategy_version=SHADOW_STRATEGY_VERSION, source=SHADOW_SOURCE, ...)).
    frame 을 직접 주면(테스트) DB 를 건드리지 않는다 — candidate_ledger.load_outcome_frame 과 같은
    컬럼(FRAME_COLUMNS)을 가진 프레임이면 된다.

    exposed_only=True(기본, 스펙 §3): 최근 공시가 없어 veto 유무와 무관하게 결과가 같은(노출되지 않은)
    후보는 주 분석에서 뺀다. exposed_decision_ids 를 안 주면(그리고 frame 도 안 줬으면) DB 에서
    scores.exposed 를 읽어 판정한다. frame 을 직접 줬는데 exposed_decision_ids 도 없으면
    exposed_only=True 여도 거를 것이 없어 빈 프레임이 된다(호출자가 실수로 필터를 빠뜨리지 않도록
    exposed_decision_ids 를 명시적으로 주거나 exposed_only=False 를 쓰라는 의도).

    반환:
        arm_a_original_no_veto: 같은 프레임을 전량 selected 로 재표시한 evaluate_selection 결과
            (원전략 = veto 없이 전량 채택했을 때의 비용 후 평균).
        arm_b_simple_rule_veto: 기록된 그대로(veto pass=selected, veto hold=held) evaluate_selection
            결과. groups.rest/missed_opportunity 가 veto 로 보류한 종목의 사후 성과(기회비용)다.
        arm_c_random_hold_same_count: evaluate_selection 이 이미 계산한 무작위 보류 기준선
            (random_baseline_expected/incremental.selected_minus_random/random_baseline_mc)을 그대로
            가리킨다.
        verdict/verdict_reasons: Arm B 호출의 decide_verdict 출력을 그대로 반환한다(우회하지 않는다).
    """
    if frame is None:
        with _local_session_scope(session) as s:
            frame = load_outcome_frame(
                s, horizon=horizon, strategy_version=SHADOW_STRATEGY_VERSION, source=SHADOW_SOURCE,
                cost_scenario=cost_scenario)
            if exposed_only and exposed_decision_ids is None:
                exposed_decision_ids = _load_exposed_decision_ids(s)

    frame = frame.copy()
    n_recorded = len(frame)
    if exposed_only:
        ids = exposed_decision_ids if exposed_decision_ids is not None else set()
        frame = frame[frame["decision_id"].isin(ids)].reset_index(drop=True)

    arm_b = evaluate_selection(frame, horizon=horizon, value_col=value_col, cost_scenario=cost_scenario, **eval_kwargs)

    frame_a = frame.copy()
    frame_a["decision"] = "selected"
    arm_a = evaluate_selection(frame_a, horizon=horizon, value_col=value_col, cost_scenario=cost_scenario, **eval_kwargs)

    n_sel = arm_b["n_decisions"].get("selected", 0)
    n_held = arm_b["n_decisions"].get("held", 0)
    n_exposed_pop = n_sel + n_held
    held_mean = arm_b["groups"]["rest"]["mean"]
    delta_ev_point_estimate = (
        -(n_held / n_exposed_pop) * held_mean if (n_exposed_pop and held_mean is not None) else None
    )

    return {
        "shadow_strategy_version": SHADOW_STRATEGY_VERSION, "shadow_source": SHADOW_SOURCE,
        "exposed_only": exposed_only, "n_candidates_recorded": n_recorded, "n_exposed_eligible": n_exposed_pop,
        "n_held_by_veto": n_held,
        "arm_a_original_no_veto": arm_a,
        "arm_b_simple_rule_veto": arm_b,
        "arm_c_random_hold_same_count": {
            "note": ("동일 선택률 무작위 보류 기준(스펙 §8 Arm C). candidate_ledger.evaluate_selection 이 "
                     "이미 계산하는 배치별(같은 결정일) 무작위 보류 몬테카를로를 그대로 쓴다."),
            "random_baseline_expected": arm_b["groups"]["random_baseline_expected"],
            "incremental_vs_random": arm_b["incremental"]["selected_minus_random"],
            "monte_carlo": arm_b["random_baseline_mc"],
        },
        "delta_ev_point_estimate_arm_b_minus_a": delta_ev_point_estimate,
        "delta_ev_formula": (
            "-(n_held/n_exposed) * mean(held, 현금 대안) — 스펙 §9 의 점 추정치 공식. 유의성·채택 판단은 "
            "verdict(=Arm B 의 decide_verdict)만 따른다. 이 점 추정치 자체에 별도 신뢰구간을 새로 계산하지 않는다."
        ),
        "verdict": arm_b["verdict"], "verdict_reasons": arm_b["verdict_reasons"],
        "requires_human_approval": arm_b["requires_human_approval"],
        "disclaimer": DISCLAIMER,
    }
