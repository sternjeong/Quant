"""후보 shadow 원장의 국면별 판정 + 실측 비용 진단 칸 (관측·진단 전용).

방법론 원칙: 전략은 **같은 국면(regime) 안에서만** 검증한다(전체 기간을 섞지 않는다). 후보 원장
(core.candidate_ledger)의 기본 판정은 모든 기간을 섞으므로, 이 모듈은 결정마다 **결정 시점에 알 수
있었던** 국면 라벨을 붙이고 국면별로 원장의 evaluate_selection/decide_verdict 를 그대로 다시 돌린다.
새 통계 규칙을 만들지 않는다.

## 국면 라벨 (미래 정보 차단)
결정(decision_cutoff, naive UTC)마다 다음 순서로 라벨을 정한다.
1. 저장된 MarketRegimeSnapshot 중 computed_at <= decision_cutoff 인 **가장 최근** 행. 이후에 계산된 스냅샷은
   절대 쓰지 않는다. 그 스냅샷이 결정일보다 MAX_SNAPSHOT_AGE_TRADING_DAYS(5) 거래일(평일 기준) 넘게 오래됐으면
   'unknown'(snapshot_stale). 스냅샷 자체가 unknown 이면 'unknown'. partial(일부 신호 결측으로 재정규화된 판정)은
   라벨은 유지하되 regime_partial=True 로 따로 표시한다.
2. 결정 이전 스냅샷이 하나도 없을 때만 core.market_regime.classify_daily_regime 로 재계산한다. 입력은 벤치마크
   일봉 중 결정 시점에 이미 확정된 봉만(결정 시각이 그 날 16:00 미 동부 이후면 당일 봉 포함, 아니면 전일까지)
   잘라서 넣는다. 200봉 미만이거나 마지막 봉이 5거래일 넘게 오래됐으면 'unknown'. source 를 따로 표시한다
   (시장폭이 빠진 다른 정의라 라벨 값도 '횡보장'이 나올 수 있으며, 스냅샷의 '중립/혼조'와 합치지 않는다).
   기본 가격 공급자는 로컬 캐시만 읽는다(네트워크 없음).
- 'unknown' 은 어느 국면에도 섞지 않고 별도 칸으로 평가한다.
- 한 후보 집합(candidate_set)의 결정들은 같은 decision_cutoff 를 공유하므로 같은 라벨을 받는다. 그래서 원장의
  '동일 선택률 무작위 기준선'(집합 단위)이 국면 분할로 깨지지 않는다.

## 다중비교
국면 수만큼 비교가 늘어난다. 각 국면 결과에 multiple_comparisons 라벨(비교 수, 보정 없음)을 붙인다. 표본이
국면별로 쪼개지므로 원장 게이트(채택 30·종목 20·날짜 블록 6)에 따라 대부분 '미입증'이 되는 것이 정상이다.

## 실측 비용 (진단용 추가 칸)
core.cost_calibration.load_cost_calibration() 이 status 'ok' 이면 'measured' 시나리오를 가정 5/10/25bp 와 나란히
추가해 비용 후 결과를 다시 계산한다. 체결 관례는 원장과 같다: 매수 시가*(1+매수 슬리피지)*(1+수수료),
매도 시가*(1-매도 슬리피지)*(1-수수료)를 체결가로 두고 수익률은 candidate_ledger.round_trip_return 으로 계산한다
(방향별 슬리피지가 같으면 원장의 명명 시나리오 식과 정확히 같다 — 테스트로 대조). 주 검정 비용 시나리오
(PRIMARY_COST_SCENARIO)는 바꾸지 않으므로 measured 판정은 원장 규칙상 항상 '미입증'(non_primary_cost_scenario)이다.
원장 DB 에 저장된 가정 비용 결과는 읽기만 하고 바꾸지 않는다. stale 이면 표시하고, 표본 부족이면 쓰지 않고 사유를 남긴다.

원장 결과의 pit_certified_fraction 은 원장 버전에 따라 의미가 다를 수 있어(5필드 시간 계약 인증 비율 또는
인정된 근거 비율) 이 모듈은 해석·표시하지 않는다. PIT 관련 판정은 원장의 verdict_reasons 를 그대로 옮긴다.

성과·승률 개선을 주장하지 않는다. 주문 경로와 무관하다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Optional, Sequence

import numpy as np
import pandas as pd

from core import candidate_ledger as cl

MAX_SNAPSHOT_AGE_TRADING_DAYS = 5
MIN_FALLBACK_BARS = 200  # classify_daily_regime 의 200일선이 계산되는 최소 이력
MARKET_CLOSE = time(16, 0)
UNKNOWN = "unknown"
SNAPSHOT_REGIMES = ("강세장", "약세장", "중립/혼조")  # core.market_regime.classify_regime 값
FALLBACK_REGIMES = ("강세장", "약세장", "횡보장")  # core.market_regime.classify_daily_regime 값
REGIME_ORDER = ("강세장", "약세장", "중립/혼조", "횡보장")

SOURCE_SNAPSHOT = "stored_snapshot"
SOURCE_FALLBACK = "daily_classifier_recomputed"
SOURCE_NONE = "none"

MEASURED = "measured"
_LOAD = object()  # calibration 인자 기본값: load_cost_calibration() 을 부른다

SAMPLE_NOTE = ("국면별로 표본이 쪼개지므로 원장 게이트(채택 >=30, 종목 군집 >=20, 날짜 블록 >=6)에 따라 "
               "'미입증'이 되는 것이 정상이다. 미입증은 '효과 없음'이 아니라 '판단할 근거 부족'이다.")
DISCLAIMER = ("국면별 판정·실측 비용 칸은 진단용이다. 판정은 core.candidate_ledger 규칙을 그대로 쓰며, "
              "국면 분할은 비교 수를 늘리므로(다중비교, 보정 없음) 한 국면의 '검토대상'도 우연일 수 있다. "
              "성과 개선의 증거가 아니다.")


# ---------------------------------------------------------------------------
# 가격 공급자 (기본: 로컬 캐시만, 네트워크 없음)
# ---------------------------------------------------------------------------
def cache_only_price_provider(ticker: str, start: str, end: str) -> pd.DataFrame:
    """core.market_data 의 로컬 저장소만 읽는다. 다운로드하지 않는다. end 는 배타적."""
    from core import market_data

    df = market_data._load_store(market_data._store_path(ticker, "1d"))
    if df is None or df.empty:
        return pd.DataFrame()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df = df.copy()
    df.index = idx
    return df[(df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))]


# ---------------------------------------------------------------------------
# 스냅샷 로딩
# ---------------------------------------------------------------------------
def load_regime_snapshots(session=None, until: Optional[datetime] = None) -> list[dict]:
    """저장된 MarketRegimeSnapshot 을 computed_at 오름차순 dict 목록으로. until 이후 행은 읽지 않는다.

    각 dict: {"id","computed_at"(naive UTC),"regime","partial","coverage","missing_signals","regime_reason"}.
    detail JSON 이 깨졌으면 partial=None(모름)으로 둔다.
    """
    from core.models import MarketRegimeSnapshot

    out: list[dict] = []
    with cl._session_scope(session) as s:
        q = s.query(MarketRegimeSnapshot)
        if until is not None:
            q = q.filter(MarketRegimeSnapshot.computed_at <= until)
        for row in q.order_by(MarketRegimeSnapshot.computed_at, MarketRegimeSnapshot.id).all():
            try:
                detail = json.loads(row.detail) if row.detail else {}
                parsed = isinstance(detail, dict)
                if not parsed:
                    detail = {}
            except (TypeError, ValueError):
                detail, parsed = {}, False
            out.append({
                "id": row.id, "computed_at": row.computed_at, "regime": row.regime,
                "partial": bool(detail.get("partial", False)) if parsed else None,
                "coverage": detail.get("coverage"), "missing_signals": detail.get("missing_signals"),
                "regime_reason": detail.get("regime_reason"),
            })
    return out


# ---------------------------------------------------------------------------
# 라벨 부여
# ---------------------------------------------------------------------------
def _trading_days_between(d0: date, d1: date) -> int:
    """d0 다음 평일부터 d1 까지의 평일 수(d0==d1 이면 0). 미국 휴장일은 반영하지 않는다(보수적으로 더 많이 셈)."""
    if d1 < d0:
        return -1
    return int(np.busday_count(d0 + timedelta(days=1), d1 + timedelta(days=1)))


def _label(regime: str, source: str, *, partial: Optional[bool] = False, reason: Optional[str] = None,
           as_of: Any = None, age: Optional[int] = None, snapshot_id: Optional[int] = None) -> dict:
    return {"regime": regime, "regime_source": source, "regime_partial": partial, "regime_reason": reason,
            "regime_asof": as_of, "regime_age_trading_days": age, "regime_snapshot_id": snapshot_id}


def _last_known_bar_date(cutoff_utc: datetime) -> date:
    """결정 시각에 이미 종가가 확정된 마지막 날짜. 16:00 미 동부 이후면 당일, 아니면 전일."""
    local = cl._ny_local(cutoff_utc)
    return local.date() if local.time() >= MARKET_CLOSE else local.date() - timedelta(days=1)


def _fallback_label(cutoff_utc: datetime, bench: Optional[pd.DataFrame], max_age: int, prefix: str) -> dict:
    from core.market_regime import classify_daily_regime

    if bench is None or bench.empty or not {"Close", "High", "Low"}.issubset(bench.columns):
        return _label(UNKNOWN, SOURCE_NONE, partial=None, reason=f"{prefix}; benchmark_unavailable")
    last_ok = _last_known_bar_date(cutoff_utc)
    past = bench[bench.index <= pd.Timestamp(last_ok)]  # 결정 시점 이후 봉은 입력에서 제거
    past = past.dropna(subset=["Close"])
    if len(past) < MIN_FALLBACK_BARS:
        return _label(UNKNOWN, SOURCE_FALLBACK, partial=None,
                      reason=f"{prefix}; benchmark_insufficient_history({len(past)}<{MIN_FALLBACK_BARS})")
    last_bar = past.index[-1].date()
    age = _trading_days_between(last_bar, cl._ny_local(cutoff_utc).date())
    if age > max_age:
        return _label(UNKNOWN, SOURCE_FALLBACK, partial=None, as_of=last_bar.isoformat(), age=age,
                      reason=f"{prefix}; benchmark_data_stale(age={age}>{max_age})")
    lab = classify_daily_regime(past["Close"], past["High"], past["Low"])
    value = str(lab.iloc[-1]) if len(lab) else UNKNOWN
    if value not in FALLBACK_REGIMES:
        return _label(UNKNOWN, SOURCE_FALLBACK, partial=None, as_of=last_bar.isoformat(), age=age,
                      reason=f"{prefix}; classifier_returned({value})")
    return _label(value, SOURCE_FALLBACK, partial=False, as_of=last_bar.isoformat(), age=age,
                  reason=f"{prefix}; recomputed_without_breadth")


def label_decision_regime(
    cutoff: Any, snapshots: Sequence[dict], *, benchmark: Optional[pd.DataFrame] = None,
    max_age_trading_days: int = MAX_SNAPSHOT_AGE_TRADING_DAYS,
) -> dict:
    """결정 1건의 국면 라벨. snapshots 는 load_regime_snapshots 형식(순서 무관). 미래 스냅샷은 걸러 낸다."""
    c = cl.normalize_time(cutoff)
    if c is None:
        return _label(UNKNOWN, SOURCE_NONE, partial=None, reason="decision_cutoff_missing")
    prior = [s for s in snapshots if s.get("computed_at") is not None and s["computed_at"] <= c]
    if prior:
        snap = max(prior, key=lambda s: (s["computed_at"], s.get("id") or 0))
        snap_date = cl._ny_local(snap["computed_at"]).date()
        age = _trading_days_between(snap_date, cl._ny_local(c).date())
        as_of = snap["computed_at"].isoformat()
        common = dict(partial=snap.get("partial"), as_of=as_of, age=age, snapshot_id=snap.get("id"))
        if age > max_age_trading_days:
            return _label(UNKNOWN, SOURCE_SNAPSHOT, reason=f"snapshot_stale(age={age}>{max_age_trading_days})",
                          **common)
        if snap.get("regime") not in SNAPSHOT_REGIMES:
            return _label(UNKNOWN, SOURCE_SNAPSHOT,
                          reason=f"snapshot_regime_unknown({snap.get('regime_reason') or snap.get('regime')})",
                          **common)
        return _label(str(snap["regime"]), SOURCE_SNAPSHOT, **common)
    return _fallback_label(c, benchmark, max_age_trading_days, "no_snapshot_before_cutoff")


LABEL_COLUMNS = ["decision_id", "regime", "regime_source", "regime_partial", "regime_reason", "regime_asof",
                 "regime_age_trading_days", "regime_snapshot_id"]


def label_decisions(
    cutoffs: pd.DataFrame, *, snapshots: Optional[Sequence[dict]] = None, session=None,
    price_provider: Optional[Callable] = None, benchmark_ticker: Optional[str] = None,
    max_age_trading_days: int = MAX_SNAPSHOT_AGE_TRADING_DAYS,
) -> pd.DataFrame:
    """cutoffs(decision_id, decision_cutoff) -> decision_id 별 라벨 프레임.

    snapshots=None 이면 DB 에서 (가장 늦은 결정 시각까지만) 읽는다. 폴백 벤치마크는 결정 이전 스냅샷이 없는
    결정이 있을 때만, 가장 늦은 결정일까지의 구간만 요청한다. price_provider 기본값은 로컬 캐시 전용.
    """
    if cutoffs is None or len(cutoffs) == 0:
        return pd.DataFrame(columns=LABEL_COLUMNS)
    norm = [cl.normalize_time(v) for v in cutoffs["decision_cutoff"]]
    valid = [c for c in norm if c is not None]
    if snapshots is None:
        snapshots = load_regime_snapshots(session, until=max(valid)) if valid else []
    snap_times = sorted(s["computed_at"] for s in snapshots if s.get("computed_at") is not None)
    need_fallback = [c for c in valid if not snap_times or snap_times[0] > c]
    bench = None
    if need_fallback:
        from core.market_regime import DEFAULT_BENCHMARK_TICKER

        ticker = benchmark_ticker or DEFAULT_BENCHMARK_TICKER
        provider = price_provider or cache_only_price_provider
        last = max(cl._ny_local(c).date() for c in need_fallback)
        first = min(cl._ny_local(c).date() for c in need_fallback)
        try:
            bench = provider(ticker, (first - timedelta(days=800)).isoformat(),
                             (last + timedelta(days=1)).isoformat())
            if bench is not None and len(bench):
                idx = pd.DatetimeIndex(bench.index)
                bench = bench.copy()
                bench.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
                bench = bench.sort_index()
                bench = bench[bench.index <= pd.Timestamp(last)]  # 공급자가 더 줘도 미래 봉 제거
        except Exception:  # noqa: BLE001 - 가격 조회 실패는 unknown 으로 남긴다
            bench = None
    rows = []
    for did, c in zip(cutoffs["decision_id"], norm):
        lab = label_decision_regime(c, snapshots, benchmark=bench, max_age_trading_days=max_age_trading_days)
        rows.append({"decision_id": did, **lab})
    return pd.DataFrame(rows, columns=LABEL_COLUMNS)


def load_decision_cutoffs(session=None, decision_ids: Optional[Sequence[int]] = None) -> pd.DataFrame:
    from core.models import CandidateDecision

    with cl._session_scope(session) as s:
        q = s.query(CandidateDecision.id, CandidateDecision.decision_cutoff)
        if decision_ids is not None:
            ids = [int(i) for i in decision_ids]
            if not ids:
                return pd.DataFrame(columns=["decision_id", "decision_cutoff"])
            q = q.filter(CandidateDecision.id.in_(ids))
        rows = q.all()
    return pd.DataFrame([{"decision_id": i, "decision_cutoff": c} for i, c in rows],
                        columns=["decision_id", "decision_cutoff"])


# ---------------------------------------------------------------------------
# 국면별 평가 (원장 evaluate_selection 을 그대로 재사용)
# ---------------------------------------------------------------------------
def _brief(res: dict) -> dict:
    inc = (res.get("incremental") or {}).get("selected_minus_random") or {}
    g = res["groups"]
    return {
        "n_selected": g["selected"]["n"], "n_rest": g["rest"]["n"],
        "selected_mean": g["selected"]["mean"], "rest_mean": g["rest"]["mean"],
        "selected_minus_random": inc.get("estimate"), "ci_low": inc.get("ci_low"), "ci_high": inc.get("ci_high"),
        "verdict": res["verdict"], "verdict_reasons": list(res["verdict_reasons"]),
    }


def evaluate_by_regime(frame: pd.DataFrame, labels: pd.DataFrame, **eval_kwargs) -> dict:
    """국면별로 cl.evaluate_selection 을 그대로 돌린다. unknown 은 별도 칸, 전체(섞은) 결과는 참고용으로만.

    Returns {"regimes": {라벨: {...evaluate_selection 결과, "label_sources", "n_partial_labels",
             "multiple_comparisons", "sample_gate_note"}}, "unknown": {...}|None, "pooled_reference": {...},
             "n_comparisons", "multiple_comparisons", "sample_note", "label_counts"}.
    """
    lab = labels.set_index("decision_id")
    extra_cols = ["regime", "regime_source", "regime_partial"]
    df = frame.copy()
    df["regime"] = df["decision_id"].map(lab["regime"]).fillna(UNKNOWN)
    df["regime_source"] = df["decision_id"].map(lab["regime_source"]).fillna(SOURCE_NONE)
    df["regime_partial"] = df["decision_id"].map(lab["regime_partial"])
    present = [r for r in REGIME_ORDER if (df["regime"] == r).any()]
    present += sorted(set(df["regime"]) - set(REGIME_ORDER) - {UNKNOWN})
    k = len(present)
    mc = {"family": "regime_split", "n_comparisons": k, "correction": "none",
          "label": f"국면별 분할 {k}개 비교(다중비교, 보정 없음) — 한 국면의 검토대상 판정도 우연일 수 있다"}

    def _eval(sub: pd.DataFrame) -> dict:
        sub = sub.drop(columns=extra_cols)
        sub.attrs = dict(frame.attrs)
        return cl.evaluate_selection(sub, **eval_kwargs)

    regimes: dict[str, dict] = {}
    for r in present:
        sub = df[df["regime"] == r]
        res = _eval(sub)
        res["label_sources"] = {str(a): int(b) for a, b in sub["regime_source"].value_counts().items()}
        res["n_partial_labels"] = int(sum(1 for x in sub["regime_partial"] if x is not None and x == True))  # noqa: E712
        res["multiple_comparisons"] = dict(mc)
        small = any(x.startswith("insufficient_sample") or x == "no_selected_outcomes"
                    for x in res["verdict_reasons"])
        res["sample_gate_note"] = SAMPLE_NOTE if small else None
        regimes[r] = res
    unk = df[df["regime"] == UNKNOWN]
    unknown = None
    if len(unk):
        unknown = _eval(unk)
        unknown["note"] = "국면을 알 수 없는 결정. 어느 국면에도 섞지 않았다(판정은 참고용)."
        reasons = lab.loc[lab.index.intersection(unk["decision_id"]), "regime_reason"].fillna("unlabeled")
        missing_lab = int((~unk["decision_id"].isin(lab.index)).sum())
        counts = reasons.astype(str).str.split("(").str[0].value_counts()
        unknown["unknown_reasons"] = {str(a): int(b) for a, b in counts.items()}
        if missing_lab:
            unknown["unknown_reasons"]["unlabeled"] = unknown["unknown_reasons"].get("unlabeled", 0) + missing_lab
    pooled = cl.evaluate_selection(frame, **eval_kwargs)
    pooled["note"] = "전체 기간을 섞은 원장 기본 판정(방법론상 참고용). 국면별 판정과 다를 수 있다."
    return {
        "regimes": regimes, "unknown": unknown, "pooled_reference": pooled, "n_comparisons": k,
        "multiple_comparisons": mc, "sample_note": SAMPLE_NOTE,
        "label_counts": {str(a): int(b) for a, b in df["regime"].value_counts().items()},
    }


# ---------------------------------------------------------------------------
# 실측 비용
# ---------------------------------------------------------------------------
def measured_cost_status(calibration: Any = _LOAD) -> dict:
    """실측 비용 시나리오 사용 여부. {"used", "reason", "stale", "n", "scenario", ...}. 예외를 던지지 않는다."""
    if calibration is _LOAD:
        try:
            from core import cost_calibration as cc

            calibration = cc.load_cost_calibration()
        except Exception as exc:  # noqa: BLE001
            return {"used": False, "reason": f"calibration_unavailable:{type(exc).__name__}", "stale": None}
    if calibration is None:
        return {"used": False, "reason": "no_calibration_file", "stale": None}
    if calibration.get("status") != "ok" or not calibration.get("scenario"):
        return {"used": False, "reason": calibration.get("reason") or calibration.get("status") or "not_ok",
                "n": calibration.get("n"), "min_sample": calibration.get("min_sample"), "stale": None}
    sc = calibration["scenario"]
    fee = float(sc.get("fee_bps", 0.0))
    slip = float(sc["slippage_bps"])
    buy, sell = sc.get("buy_slippage_bps"), sc.get("sell_slippage_bps")
    return {
        "used": True, "reason": None, "stale": bool(calibration.get("stale", False)),
        "age_days": calibration.get("age_days"), "n": calibration.get("n"),
        "generated_at": calibration.get("generated_at"),
        "scenario": {"fee_bps": fee, "buy_slippage_bps": slip if buy is None else float(buy),
                     "sell_slippage_bps": slip if sell is None else float(sell),
                     "side_split": bool(sc.get("side_split", False)), "fee_note": sc.get("fee_note")},
        "role": "diagnostic(주 검정 비용 시나리오 아님)",
    }


def measured_round_trip(gross_return: float, scenario: dict) -> float:
    """원장 체결 관례로 실측 비용 후 왕복 수익률. 체결가를 만든 뒤 cl.round_trip_return(비용 없음)을 재사용한다."""
    f = scenario["fee_bps"] / 1e4
    entry_fill = 1.0 * (1 + scenario["buy_slippage_bps"] / 1e4) * (1 + f)
    exit_fill = (1.0 + float(gross_return)) * (1 - scenario["sell_slippage_bps"] / 1e4) * (1 - f)
    return cl.round_trip_return(entry_fill, exit_fill, None)


def measured_frame(frame: pd.DataFrame, scenario: dict) -> pd.DataFrame:
    """load_outcome_frame 결과를 복사해 net_* 컬럼을 실측 비용으로 다시 계산한다(원본·DB 불변)."""
    df = frame.copy()
    g = pd.to_numeric(df["gross_return"], errors="coerce")
    df["net_return"] = [measured_round_trip(v, scenario) if pd.notna(v) else float("nan") for v in g]
    df["net_excess_spy"] = df["net_return"] - pd.to_numeric(df["benchmark_return"], errors="coerce")
    df["net_excess_sector"] = df["net_return"] - pd.to_numeric(df["sector_etf_return"], errors="coerce")
    df.attrs = {**frame.attrs, "cost_scenario": MEASURED}
    return df


def evaluate_cost_scenarios(frames: dict[str, pd.DataFrame], status: dict, **eval_kwargs) -> dict:
    """가정 시나리오별 프레임({이름: load_outcome_frame}) + (쓸 수 있으면) measured 를 나란히 평가한다."""
    out: dict[str, dict] = {}
    for name, fr in frames.items():
        out[name] = _brief(cl.evaluate_selection(fr, cost_scenario=name, **eval_kwargs))
        out[name].update({"kind": "assumed", "primary": name == cl.PRIMARY_COST_SCENARIO})
    if status.get("used"):
        base = frames.get(cl.PRIMARY_COST_SCENARIO)
        if base is None:
            base = next(iter(frames.values()))
        res = cl.evaluate_selection(measured_frame(base, status["scenario"]), cost_scenario=MEASURED, **eval_kwargs)
        out[MEASURED] = _brief(res)
        out[MEASURED].update({"kind": "measured", "primary": False, "stale": status.get("stale")})
    return out


# ---------------------------------------------------------------------------
# 묶음 진입점
# ---------------------------------------------------------------------------
def build_regime_cost_evaluation(
    session=None, *, strategy_version: Optional[str] = None, source: Optional[str] = None,
    horizon: int = cl.PRIMARY_HORIZON_DAYS, snapshots: Optional[Sequence[dict]] = None,
    price_provider: Optional[Callable] = None, calibration: Any = _LOAD, **eval_kwargs,
) -> dict:
    """원장에서 결과를 읽어 (1) 국면별 판정 (2) 가정 vs 실측 비용 판정을 만든다. DB 는 읽기만 한다."""
    from core.trade_ledger import COST_SCENARIOS_BPS

    with cl._session_scope(session) as s:
        frames = {sc: cl.load_outcome_frame(s, horizon, strategy_version=strategy_version, source=source,
                                            cost_scenario=sc) for sc in COST_SCENARIOS_BPS}
        primary = frames[cl.PRIMARY_COST_SCENARIO]
        cutoffs = load_decision_cutoffs(s, list(primary["decision_id"]))
        labels = label_decisions(cutoffs, snapshots=snapshots, session=s, price_provider=price_provider)
    by_regime = evaluate_by_regime(primary, labels, horizon=horizon, cost_scenario=cl.PRIMARY_COST_SCENARIO,
                                   **eval_kwargs)
    status = measured_cost_status(calibration)
    costs = evaluate_cost_scenarios(frames, status, horizon=horizon, **eval_kwargs)
    return {
        "strategy_version": strategy_version, "source": source, "horizon_days": horizon,
        "primary_cost_scenario": cl.PRIMARY_COST_SCENARIO, "by_regime": by_regime,
        "measured_cost": status, "cost_scenarios": costs, "disclaimer": DISCLAIMER,
        "label_rule": (f"결정 시각 이전 가장 최근 스냅샷({MAX_SNAPSHOT_AGE_TRADING_DAYS}거래일 초과 경과 시 unknown), "
                       "없으면 결정 시점에 확정된 벤치마크 일봉으로 classify_daily_regime 재계산"),
    }


# ---------------------------------------------------------------------------
# 보고서 절 (strategy_variants 가 사용)
# ---------------------------------------------------------------------------
def _pct(v: Optional[float]) -> str:
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v * 100:.2f}%"


def _ci_text(b: dict) -> str:
    if b.get("ci_low") is None or b.get("ci_high") is None:
        return "n/a"
    return f"[{_pct(b['ci_low'])}, {_pct(b['ci_high'])}]"


def render_regime_section(evals: dict[str, dict]) -> list[str]:
    """{변형: build_regime_cost_evaluation 결과 또는 {"error"}} -> '국면별 판정' 절 markdown 줄."""
    L = ["## 국면별 판정", "", DISCLAIMER, ""]
    for name, ev in evals.items():
        if ev.get("error"):
            L += [f"- {name}: 계산 실패({ev['error']})", ""]
            continue
        br = ev["by_regime"]
        L += [f"### {name}", "", f"라벨 규칙: {ev['label_rule']}. {br['multiple_comparisons']['label']}.", "",
              "| 국면 | 라벨 출처 | partial 라벨 | 채택/비교군 | 채택−무작위 | 95% CI | verdict | 사유 |",
              "|---|---|---|---|---|---|---|---|"]
        rows = list(br["regimes"].items())
        if br["unknown"] is not None:
            rows.append(("unknown(별도)", br["unknown"]))
        rows.append(("전체 섞음(참고)", br["pooled_reference"]))
        for r, res in rows:
            b = _brief(res)
            src = ", ".join(f"{a}:{c}" for a, c in (res.get("label_sources") or {}).items()) or "-"
            part = res.get("n_partial_labels", "-")
            L.append(f"| {r} | {src} | {part} | {b['n_selected']}/{b['n_rest']} | {_pct(b['selected_minus_random'])} | "
                     f"{_ci_text(b)} | {b['verdict']} | {', '.join(b['verdict_reasons']) or '-'} |")
        if not rows[:-1]:
            L.append("")
            L.append("기록된 결정이 없다.")
        if br["unknown"] is not None and br["unknown"].get("unknown_reasons"):
            L += ["", "unknown 사유: " + ", ".join(f"{a} {c}건" for a, c in br["unknown"]["unknown_reasons"].items())]
        L += ["", br["sample_note"], ""]
    return L


def render_cost_section(evals: dict[str, dict]) -> list[str]:
    """{변형: build_regime_cost_evaluation 결과} -> '실측 비용 반영 결과' 절 markdown 줄."""
    L = ["## 실측 비용 반영 결과", "",
         f"주 검정 비용 시나리오는 사전 고정값 {cl.PRIMARY_COST_SCENARIO} 그대로다. measured 는 진단용 추가 칸이라 원장 "
         "규칙상 항상 '미입증'(non_primary_cost_scenario)이며, 원장에 저장된 가정 비용 결과는 바꾸지 않는다.", ""]
    first = next((ev for ev in evals.values() if not ev.get("error")), None)
    if first is not None:
        st = first["measured_cost"]
        if st.get("used"):
            sc = st["scenario"]
            stale = " — **오래된 실측(stale)**" if st.get("stale") else ""
            L += [f"실측 비용: 표본 {st.get('n')}건, 매수 슬리피지 {sc['buy_slippage_bps']:g}bp, 매도 "
                  f"{sc['sell_slippage_bps']:g}bp, 수수료 {sc['fee_bps']:g}bp(측정 안 됨){stale}. "
                  f"산출 {st.get('generated_at')}.", ""]
        else:
            L += [f"실측 비용 미사용: {st.get('reason')}"
                  + (f" (n={st.get('n')})" if st.get("n") is not None else "") + ". 가정 시나리오만 표시한다.", ""]
    for name, ev in evals.items():
        if ev.get("error"):
            L += [f"- {name}: 계산 실패({ev['error']})", ""]
            continue
        L += [f"### {name}", "", "| 비용 시나리오 | 종류 | 채택 평균 | 채택−무작위 | 95% CI | verdict |",
              "|---|---|---|---|---|---|"]
        for sc_name, b in ev["cost_scenarios"].items():
            kind = b["kind"] + (" (주 검정)" if b.get("primary") else "") + (" stale" if b.get("stale") else "")
            L.append(f"| {sc_name} | {kind} | {_pct(b['selected_mean'])} | {_pct(b['selected_minus_random'])} | "
                     f"{_ci_text(b)} | {b['verdict']} |")
        L.append("")
    return L
