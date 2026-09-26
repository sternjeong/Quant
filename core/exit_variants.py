"""후보 원장 청산 규칙 변형 비교 — 관측·연구 전용 (2026-09-26 사전 등록).

후보 shadow 원장(core.candidate_ledger)은 모든 후보를 "다음 시가 진입 -> 20거래일 뒤 시가 청산" 하나로만
평가한다. 이 모듈은 이미 원장에 기록된 후보(CandidateDecision)에 대해 **같은 진입**에서 여러 청산 규칙을
적용한 결과를 계산하고, 원장과 같은 판정 틀(candidate_ledger.evaluate_selection / decide_verdict)로 비교한다.
새 통계 규칙은 만들지 않는다. 주문 경로·스케줄러와 연결하지 않는다. 설계·사전 등록: docs/EXIT_VARIANTS_SPEC.md.

## 사전 고정 (결과를 보기 전에 고정. 바꾸면 탐색 결과로만 취급)
- baseline_20d: 원장과 동일(진입 + 20거래일 뒤 세션 시가). 원장 결과와 숫자가 정확히 같다(회귀).
- fixed_stop_8: 종가 <= 진입가*(1-0.08) 이면 다음 거래일 시가 청산, 20거래일 상한.
- trailing_10: 종가 <= 진입 이후 최고 종가*(1-0.10) 이면 다음 거래일 시가 청산, 20거래일 상한.
- satellite_trailing_15: core.champion_strategy.SATELLITE_DONCHIAN_STOP_PCT(0.15) 트레일링 규칙 그대로 + 20거래일 상한.

## 체결 가정 (미래 정보 없음)
손절 판단은 일봉 종가로만, 체결은 판단 다음 거래일 시가(장중 가격 체결 가정 금지). 갭 하락이면 그 시가 그대로.
비용은 원장과 같은 편도 5/10/25bp(주 검정 10bp). 결측·대기는 기준선과 같은 상태·사유를 그대로 따른다.

결과는 과거 관측이며 미래 성과를 보장하지 않는다. 성과·승률 개선을 주장하지 않는다.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

from core import candidate_ledger as cl
from core.trade_ledger import COST_SCENARIOS_BPS

# ---------------------------------------------------------------------------
# 사전 고정 상수 (docs/EXIT_VARIANTS_SPEC.md 와 같다)
# ---------------------------------------------------------------------------
EXIT_VARIANTS_VERSION = "exit-variants/2026-09-26"
HORIZON_CAP_DAYS = cl.PRIMARY_HORIZON_DAYS  # 20 거래일 상한 = 원장 주 horizon
FIXED_STOP_PCT = 0.08
TRAILING_STOP_PCT = 0.10
SATELLITE_TRAILING_STOP_PCT = 0.15  # = champion_strategy.SATELLITE_DONCHIAN_STOP_PCT (테스트로 동기화 확인)
FAMILY_ALPHA = 0.05  # 원장과 같은 유의수준. 기준선이 아닌 변형은 Bonferroni 로 나눈다.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "data" / "reports"

DISCLAIMER = (
    "청산 규칙 변형 비교는 관측·연구용이다. 수치는 과거 관측이며 미래 성과를 보장하지 않고, 성과·승률 개선의 증거가 아니다. "
    "기준선이 아닌 변형은 여러 규칙을 동시에 본 탐색 결과(다중비교)이며, 판정은 사람이 검토할 후보일 뿐 자동 채택이 아니다."
)
FILL_RULE = ("stop decided on daily Close only; filled at the NEXT session Open (no intraday fill); "
             "gap-downs fill at that Open; cap = entry session + 20 sessions Open (same as ledger)")


@dataclass(frozen=True)
class ExitVariant:
    name: str
    kind: str  # "time" | "fixed" | "trailing"
    stop_pct: Optional[float]
    description: str


BASELINE = "baseline_20d"
VARIANTS: tuple[ExitVariant, ...] = (
    ExitVariant(BASELINE, "time", None, "원장과 동일: 진입 + 20거래일 뒤 세션 시가 청산"),
    ExitVariant("fixed_stop_8", "fixed", FIXED_STOP_PCT, "종가가 진입가 -8% 이하면 다음 거래일 시가 청산, 20거래일 상한"),
    ExitVariant("trailing_10", "trailing", TRAILING_STOP_PCT,
                "종가가 진입 이후 최고 종가 -10% 이하면 다음 거래일 시가 청산, 20거래일 상한"),
    ExitVariant("satellite_trailing_15", "trailing", SATELLITE_TRAILING_STOP_PCT,
                "위성 전략 트레일링 스탑(최고 종가 -15%) 그대로, 다음 거래일 시가 청산, 20거래일 상한"),
)
VARIANT_BY_NAME = {v.name: v for v in VARIANTS}
N_EXPLORATORY = sum(1 for v in VARIANTS if v.name != BASELINE)
EXPLORATORY_ALPHA = FAMILY_ALPHA / max(N_EXPLORATORY, 1)
EXPLORATORY_LABEL = (f"탐색 결과(다중비교: 기준선 외 변형 {N_EXPLORATORY}개 동시 비교, "
                     f"Bonferroni α={EXPLORATORY_ALPHA:.4f})")
PAIRED_TARGET = "variant_minus_baseline"


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def _as_date(x: Any = None) -> date:
    if x is None:
        return date.today()
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return pd.Timestamp(x).date()


def _ny_date(dt_utc_naive: Optional[datetime]) -> Optional[date]:
    if dt_utc_naive is None:
        return None
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(cl.MARKET_TZ).date()


def _prep_ohlc(df: Optional[pd.DataFrame], as_of_date: date) -> pd.DataFrame:
    """Open·Close 만 남기고 날짜 인덱스를 정규화한다(원장 _clean_prices 와 같은 방식 + Close). as_of 이후 봉 제거."""
    cols = ["Open", "Close"]
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or "Open" not in df.columns:
        return pd.DataFrame({c: pd.Series(dtype=float) for c in cols}, index=pd.DatetimeIndex([]))
    out = pd.DataFrame({c: pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan for c in cols})
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out.index = idx.normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out[out.index <= pd.Timestamp(as_of_date)]


def _valid(x: Any) -> bool:
    return x is not None and pd.notna(x) and float(x) > 0


# ---------------------------------------------------------------------------
# 한 후보 x 한 변형 (순수 함수, 네트워크 없음)
# ---------------------------------------------------------------------------
def compute_variant_outcome(
    cutoff: Any, variant: Any, stock_df: Optional[pd.DataFrame], bench_df: Optional[pd.DataFrame], *,
    as_of: Any = None, grace_sessions: int = cl.MISSING_GRACE_SESSIONS,
) -> dict:
    """후보 1건에 청산 규칙 1개를 적용한 결과. 반환 형식은 candidate_ledger.compute_outcome 과 같고 필드를 더한다
    (variant, exit_reason: time|stop, holding_sessions, stop_signal_date).

    진입·결측·대기 판정은 원장 compute_outcome(20거래일) 결과를 그대로 쓴다 → 모든 변형이 기준선과 같은 모집단.
    """
    v = VARIANT_BY_NAME[variant] if isinstance(variant, str) else variant
    as_of_date = _as_date(as_of)
    base = cl.compute_outcome(cutoff, HORIZON_CAP_DAYS, stock_df, bench_df, None, as_of=as_of_date,
                              grace_sessions=grace_sessions)
    base.update({"variant": v.name, "exit_reason": None, "holding_sessions": None, "stop_signal_date": None})
    if base["status"] != "final":
        return base

    bench = _prep_ohlc(bench_df, as_of_date)
    cal = bench[(bench["Open"].notna()) & (bench["Open"] > 0)].index
    e = int(cal.get_loc(pd.Timestamp(base["entry_date"])))
    x = int(cal.get_loc(pd.Timestamp(base["exit_date"])))
    if v.kind == "time":
        base.update({"exit_reason": "time", "holding_sessions": x - e})
        return base

    stock = _prep_ohlc(stock_df, as_of_date)
    if stock["Close"].notna().sum() == 0:
        out = cl.compute_outcome(None, HORIZON_CAP_DAYS, None, None)  # 빈 결과 틀(수익 None)
        out.update({"status": "missing", "reason": "close_unavailable_for_stop", "variant": v.name,
                    "exit_reason": None, "holding_sessions": None, "stop_signal_date": None,
                    "entry_date": base["entry_date"], "entry_open": base["entry_open"], "detail": {}})
        return out

    entry_open = float(base["entry_open"])
    peak = None
    signal_pos = None
    for i in range(e, x):  # 진입일 종가 ~ 상한 전날 종가
        d = cal[i]
        c = stock.at[d, "Close"] if d in stock.index else np.nan
        if not _valid(c):
            continue  # 종가 없는 날은 판단하지 않는다
        c = float(c)
        if v.kind == "trailing":
            peak = c if peak is None else max(peak, c)
            line = peak * (1 - v.stop_pct)
        else:
            line = entry_open * (1 - v.stop_pct)
        if c <= line:
            signal_pos = i
            break
    if signal_pos is None:
        base.update({"exit_reason": "time", "holding_sessions": x - e})
        return base

    # 다음 거래일 시가 체결. 그날 종목 시가가 없으면 그 뒤 첫 유효 시가(늦어도 상한 세션 — 기준선 final 이라 존재).
    fill_pos = None
    for j in range(signal_pos + 1, x + 1):
        d = cal[j]
        if d in stock.index and _valid(stock.at[d, "Open"]):
            fill_pos = j
            break
    exit_d = cal[fill_pos]
    exit_open = float(stock.at[exit_d, "Open"])
    bench_open = bench["Open"]
    base["exit_date"], base["exit_open"] = exit_d.date(), exit_open
    base["gross_return"] = cl.round_trip_return(entry_open, exit_open)
    base["net_returns"] = {n: cl.round_trip_return(entry_open, exit_open, n) for n in COST_SCENARIOS_BPS}
    base["benchmark_return"] = cl.round_trip_return(bench_open.at[cal[e]], bench_open.at[exit_d])
    base["sector_etf_return"] = None
    base["detail"] = {"stop_pct": v.stop_pct, "peak_close": peak}
    if fill_pos != signal_pos + 1:
        base["detail"]["stop_fill_delayed"] = int(fill_pos - signal_pos - 1)
    base.update({"exit_reason": "stop", "holding_sessions": fill_pos - e,
                 "stop_signal_date": cal[signal_pos].date()})
    return base


# ---------------------------------------------------------------------------
# 원장 후보 전체 -> 변형별 프레임
# ---------------------------------------------------------------------------
@contextmanager
def _read_scope(session=None):
    if session is not None:
        yield session
        return
    from core.db import get_session, init_db

    init_db()
    with get_session() as s:
        yield s


def compute_variant_frames(
    session=None, *, as_of: Any = None, price_provider=None, strategy_version: Optional[str] = None,
    source: Optional[str] = None, cost_scenario: str = cl.PRIMARY_COST_SCENARIO,
    benchmark: str = cl.BENCHMARK_TICKER, variants: Sequence[ExitVariant] = VARIANTS,
) -> dict:
    """원장에 기록된 후보마다 모든 변형을 계산해 load_outcome_frame 과 같은 컬럼의 프레임을 변형별로 만든다.

    DB 에 쓰지 않는다(읽기 전용). 가격은 price_provider(ticker, start, end)(기본: 원장 기본 공급자 = 가격 캐시).
    Returns {"frames": {name: DataFrame}, "stats": {...}, "ledger_consistency": {...}}.
    """
    from core.models import CandidateDecision

    if cost_scenario not in COST_SCENARIOS_BPS:
        raise ValueError(f"알 수 없는 cost_scenario: {cost_scenario}")
    as_of_date = _as_date(as_of)
    provider = price_provider or cl.default_price_provider
    with _read_scope(session) as s:
        ledger = cl.load_outcome_frame(s, HORIZON_CAP_DAYS, strategy_version=strategy_version, source=source,
                                       cost_scenario=cost_scenario)
        q = s.query(CandidateDecision.id, CandidateDecision.ticker, CandidateDecision.decision_cutoff)
        if strategy_version:
            q = q.filter(CandidateDecision.strategy_version == strategy_version)
        if source:
            q = q.filter(CandidateDecision.source == source)
        cutoffs = {i: (t, c) for i, t, c in q.all()}

    dates = [_ny_date(c) for _, c in cutoffs.values() if c is not None]
    frames_px: dict[str, Any] = {}
    errors: dict[str, str] = {}
    if dates:
        start = (min(dates) - timedelta(days=10)).isoformat()
        end = (as_of_date + timedelta(days=1)).isoformat()
        for t in sorted({benchmark} | {t for t, c in cutoffs.values() if c is not None}):
            try:
                frames_px[t] = provider(t, start, end)
            except Exception as exc:  # noqa: BLE001 - 티커 하나의 실패가 전체를 멈추지 않게
                errors[t] = f"{type(exc).__name__}: {exc}"
    bench_raw = frames_px.get(benchmark)

    rows: dict[str, list] = {v.name: [] for v in variants}
    stop_counts = {v.name: {"final": 0, "stop": 0, "holding_sessions": []} for v in variants}
    for _, lrow in ledger.iterrows():
        ticker, cutoff = cutoffs.get(int(lrow["decision_id"]), (lrow["ticker"], None))
        for v in variants:
            if ticker in errors:
                out = {"status": "pending", "reason": f"provider_error: {errors[ticker]}", "entry_date": None,
                       "exit_date": None, "gross_return": None, "net_returns": {}, "benchmark_return": None,
                       "exit_reason": None, "holding_sessions": None}
            else:
                out = compute_variant_outcome(cutoff, v, frames_px.get(ticker), bench_raw, as_of=as_of_date)
            final = out["status"] == "final"
            net = out["net_returns"].get(cost_scenario) if final else None
            bret = out["benchmark_return"] if final else None
            r = {c: lrow[c] for c in ("decision_id", "candidate_set_id", "ticker", "strategy_version", "source",
                                       "decision", "decision_date", "sector", "pit_certified")}
            r.update({
                "horizon_days": HORIZON_CAP_DAYS, "status": out["status"], "status_reason": out["reason"],
                "entry_date": out["entry_date"], "exit_date": out["exit_date"],
                "gross_return": np.nan if not final else out["gross_return"],
                "net_return": np.nan if net is None else net,
                "benchmark_return": np.nan if bret is None else bret, "sector_etf_return": np.nan,
                "net_excess_spy": np.nan if (net is None or bret is None) else net - bret,
                "net_excess_sector": np.nan, "exit_reason": out.get("exit_reason"),
                "holding_sessions": out.get("holding_sessions"),
            })
            rows[v.name].append(r)
            if final:
                stop_counts[v.name]["final"] += 1
                stop_counts[v.name]["stop"] += int(out.get("exit_reason") == "stop")
                stop_counts[v.name]["holding_sessions"].append(out.get("holding_sessions"))

    cols = list(cl.FRAME_COLUMNS) + ["exit_reason", "holding_sessions"]
    frames = {}
    for name, rs in rows.items():
        df = pd.DataFrame(rs, columns=cols)
        df["decision_date"] = pd.to_datetime(df["decision_date"])
        df.attrs["cost_scenario"] = cost_scenario
        df.attrs["horizon_days"] = HORIZON_CAP_DAYS
        df.attrs["variant"] = name
        frames[name] = df

    stats = {}
    for name, sc in stop_counts.items():
        hs = [h for h in sc["holding_sessions"] if h is not None]
        stats[name] = {"n_final": sc["final"], "n_stop_exits": sc["stop"],
                       "stop_exit_rate": (sc["stop"] / sc["final"]) if sc["final"] else None,
                       "avg_holding_sessions": float(np.mean(hs)) if hs else None}
    return {"frames": frames, "stats": stats, "provider_errors": errors,
            "ledger_consistency": ledger_consistency(ledger, frames.get(BASELINE))}


def ledger_consistency(ledger: pd.DataFrame, baseline: Optional[pd.DataFrame], tol: float = 1e-12) -> dict:
    """원장에 저장된 final 결과와 기준선 재계산이 같은지(회귀 점검). 원장이 아직 pending 인 행은 비교하지 않는다."""
    if baseline is None or ledger.empty:
        return {"compared": 0, "mismatches": 0, "mismatch_ids": []}
    m = ledger[["decision_id", "status", "net_excess_spy"]].merge(
        baseline[["decision_id", "status", "net_excess_spy"]], on="decision_id", suffixes=("_ledger", "_base"))
    m = m[m["status_ledger"] == "final"]
    bad = m[(m["status_base"] != "final") | ~np.isclose(m["net_excess_spy_ledger"], m["net_excess_spy_base"],
                                                        rtol=0, atol=tol, equal_nan=False)]
    return {"compared": int(len(m)), "mismatches": int(len(bad)),
            "mismatch_ids": [int(i) for i in bad["decision_id"].tolist()[:20]]}


# ---------------------------------------------------------------------------
# 평가 (원장 evaluate_selection 재사용)
# ---------------------------------------------------------------------------
def paired_difference_frame(variant_frame: pd.DataFrame, baseline_frame: pd.DataFrame) -> pd.DataFrame:
    """같은 후보의 (변형 − 기준선) 주 대상 값. 둘 중 하나라도 없으면 NaN(결측으로 셈)."""
    b = baseline_frame.set_index("decision_id")[cl.PRIMARY_TARGET]
    df = variant_frame.copy()
    df[PAIRED_TARGET] = df[cl.PRIMARY_TARGET].to_numpy() - df["decision_id"].map(b).to_numpy(dtype=float)
    df.attrs.update(variant_frame.attrs)
    return df


def _key_stats(ev: dict) -> dict:
    sel = ev["groups"]["selected"]
    return {
        "n_selected": sel["n"], "mean": sel["mean"], "win_rate": sel["win_rate"],
        "profit_factor": sel["profit_factor"], "profit_factor_infinite": sel["profit_factor_infinite"],
        "max_loss": sel["max_loss"], "p05": sel["p05"], "p50": sel["p50"], "p95": sel["p95"],
        "missed_opportunity_mean": ev["missed_opportunity"]["mean_excess"],
        "missing_outcome_rate": ev["missing_outcome_rate"],
    }


def evaluate_variants(frames: dict, *, n_boot: int = cl.DEFAULT_N_BOOT,
                      n_random_draws: int = cl.DEFAULT_N_RANDOM_DRAWS, seed: int = cl.BOOTSTRAP_SEED,
                      require_pit: bool = True) -> dict:
    """변형별 evaluate_selection + 기준선 대비 차이. 기준선 외 변형은 Bonferroni α 와 '탐색 결과' 라벨."""
    base_frame = frames[BASELINE]
    out: dict = {}
    base_stats = None
    for v in VARIANTS:
        if v.name not in frames:
            continue
        exploratory = v.name != BASELINE
        alpha = EXPLORATORY_ALPHA if exploratory else FAMILY_ALPHA
        ev = cl.evaluate_selection(frames[v.name], horizon=HORIZON_CAP_DAYS, alpha=alpha, n_boot=n_boot,
                                   n_random_draws=n_random_draws, seed=seed, require_pit=require_pit)
        ks = _key_stats(ev)
        entry = {
            "variant": v.name, "kind": v.kind, "stop_pct": v.stop_pct, "description": v.description,
            "alpha": alpha, "exploratory": exploratory,
            "label": EXPLORATORY_LABEL if exploratory else "사전 등록 기준선(원장과 동일 계약)",
            "verdict": ev["verdict"], "verdict_reasons": ev["verdict_reasons"], "stats": ks, "evaluation": ev,
        }
        if not exploratory:
            base_stats = ks
        else:
            pf = paired_difference_frame(frames[v.name], base_frame)
            pev = cl.evaluate_selection(pf, horizon=HORIZON_CAP_DAYS, value_col=PAIRED_TARGET, alpha=alpha,
                                        n_boot=n_boot, n_random_draws=n_random_draws, seed=seed,
                                        require_pit=require_pit)
            sel_ev = pev["incremental"]["selected_ev"]
            entry["paired_vs_baseline"] = {
                "selected_mean_diff": pev["groups"]["selected"]["mean"],
                "selected_n": pev["groups"]["selected"]["n"],
                "ci_low": sel_ev["ci_low"] if sel_ev else None, "ci_high": sel_ev["ci_high"] if sel_ev else None,
                "rest_mean_diff": pev["groups"]["rest"]["mean"],
                "verdict": pev["verdict"], "verdict_reasons": pev["verdict_reasons"],
                "note": "짝지은 차이는 주 대상이 아니므로 원장 규칙상 항상 '미입증' — 설명용 수치.",
            }
        out[v.name] = entry
    for name, entry in out.items():
        if base_stats is None or name == BASELINE:
            entry["delta_vs_baseline"] = None
            continue
        entry["delta_vs_baseline"] = {
            k: (None if entry["stats"][k] is None or base_stats[k] is None else entry["stats"][k] - base_stats[k])
            for k in ("mean", "win_rate", "profit_factor", "max_loss", "p05", "p50", "missed_opportunity_mean")
        }
    return {
        "variants": out,
        "multiple_comparison": {
            "n_exploratory_variants": N_EXPLORATORY, "family_alpha": FAMILY_ALPHA,
            "exploratory_alpha": EXPLORATORY_ALPHA, "method": "Bonferroni",
            "note": ("기준선이 아닌 변형 여러 개를 같은 데이터로 동시에 비교하므로 우연히 좋아 보이는 변형이 나올 수 있다. "
                     "신뢰구간을 변형 수만큼 넓히고(Bonferroni) '탐색 결과'로만 표시한다. 채택하려면 새 기간에서 사전 등록 재검증이 필요하다."),
        },
    }


# ---------------------------------------------------------------------------
# 보고서
# ---------------------------------------------------------------------------
def _fmt(x: Any, pct: bool = True) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x * 100:+.2f}%" if pct else f"{x:.2f}"


def _render_md(report: dict) -> str:
    L = [f"# 청산 규칙 변형 비교 ({report['as_of']})", "", f"> {report['disclaimer']}", "",
         f"- 버전: {report['version']} / 원장 {report['ledger_version']}",
         f"- 대상: {report['rules']['primary_target']}, 비용 {report['rules']['primary_cost_scenario']}(편도), "
         f"상한 {report['rules']['horizon_cap_days']}거래일",
         f"- 체결 가정: 손절은 일봉 종가로 판단, **다음 거래일 시가** 체결(장중 가격 체결 가정 없음), 갭 하락은 그 시가 그대로.",
         f"- 원장 회귀 점검: 저장된 final {report['ledger_consistency']['compared']}건 중 불일치 "
         f"{report['ledger_consistency']['mismatches']}건", "",
         "## 변형별 결과 (채택 그룹, 비용 후 SPY 초과수익)", "",
         "| 변형 | 라벨 | n | 기대값 | 승률 | 손익비 | 최대 손실 | 5% | 중앙값 | 놓친 기회(보류·거절 평균) | 손절 청산률 | 평균 보유 | 판정 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    ev = report["evaluation"]["variants"]
    for name, e in ev.items():
        s, st = e["stats"], report["stats"][name]
        pf = "∞" if s["profit_factor_infinite"] else _fmt(s["profit_factor"], pct=False)
        L.append(f"| {name} | {'탐색' if e['exploratory'] else '기준선'} | {s['n_selected']} | {_fmt(s['mean'])} | "
                 f"{_fmt(s['win_rate'], pct=False) if s['win_rate'] is not None else 'n/a'} | {pf} | "
                 f"{_fmt(s['max_loss'])} | {_fmt(s['p05'])} | {_fmt(s['p50'])} | {_fmt(s['missed_opportunity_mean'])} | "
                 f"{_fmt(st['stop_exit_rate'], pct=False)} | {_fmt(st['avg_holding_sessions'], pct=False)} | "
                 f"{e['verdict']} ({', '.join(e['verdict_reasons']) or '-'}) |")
    L += ["", "## 기준선 대비 차이 (탐색 결과)", "",
          "| 변형 | Δ기대값 | Δ승률 | Δ손익비 | Δ최대 손실 | Δ5% | 짝지은 차이 평균 | 보정 CI | 짝지은 판정 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, e in ev.items():
        if not e["exploratory"]:
            continue
        d, p = e["delta_vs_baseline"] or {}, e["paired_vs_baseline"]
        ci = "n/a" if p["ci_low"] is None else f"[{_fmt(p['ci_low'])}, {_fmt(p['ci_high'])}]"
        L.append(f"| {name} | {_fmt(d.get('mean'))} | {_fmt(d.get('win_rate'), pct=False)} | "
                 f"{_fmt(d.get('profit_factor'), pct=False)} | {_fmt(d.get('max_loss'))} | {_fmt(d.get('p05'))} | "
                 f"{_fmt(p['selected_mean_diff'])} | {ci} | {p['verdict']} |")
    mc = report["evaluation"]["multiple_comparison"]
    L += ["", "## 다중비교", "", f"- {mc['note']}",
          f"- 기준선 외 변형 {mc['n_exploratory_variants']}개, 보정 α = {mc['exploratory_alpha']:.4f} ({mc['method']}).",
          "", "## 사전 고정 변형", ""]
    for v in report["variants_registered"]:
        L.append(f"- `{v['name']}` — {v['description']}")
    L += ["", "## 배선 방법 (미배선)", "",
          "스케줄러에는 연결하지 않았다. 주간 연구 보고서 잡에서 `update_forward_outcomes` 이후에 "
          "`from core.exit_variants import write_exit_variants_report; write_exit_variants_report()` 를 try/except 로 "
          "한 번 부르면 된다(실패가 다른 잡을 막지 않게).",
          "", "## 한계", "",
          "- 기준선이 결측·대기인 후보는 모든 변형에서 같은 사유로 제외된다(손절이 상장폐지 손실을 막은 경우 미반영).",
          "- 일봉 종가 판단 + 다음 시가 체결이라 실제 손절 주문과 체결이 다르다. 배당 미반영, SPY 거래일력.",
          "- 표본 부족·PIT 미인증이면 원장 규칙대로 '미입증'이다. 결과는 과거 관측이며 미래 성과를 보장하지 않는다."]
    return "\n".join(L) + "\n"


def build_exit_variants_report(session=None, *, as_of: Any = None, price_provider=None,
                               strategy_version: Optional[str] = None, source: Optional[str] = None,
                               **eval_kwargs) -> dict:
    as_of_date = _as_date(as_of)
    comp = compute_variant_frames(session, as_of=as_of_date, price_provider=price_provider,
                                  strategy_version=strategy_version, source=source)
    evaluation = evaluate_variants(comp["frames"], **eval_kwargs)
    return {
        "as_of": as_of_date.isoformat(), "version": EXIT_VARIANTS_VERSION, "ledger_version": cl.LEDGER_VERSION,
        "disclaimer": DISCLAIMER, "strategy_version": strategy_version, "source": source,
        "rules": {"primary_target": cl.PRIMARY_TARGET, "primary_cost_scenario": cl.PRIMARY_COST_SCENARIO,
                  "horizon_cap_days": HORIZON_CAP_DAYS, "fill_rule": FILL_RULE, "entry_rule": cl.ENTRY_RULE,
                  "price_basis": cl.PRICE_BASIS},
        "variants_registered": [{"name": v.name, "kind": v.kind, "stop_pct": v.stop_pct,
                                 "description": v.description} for v in VARIANTS],
        "stats": comp["stats"], "ledger_consistency": comp["ledger_consistency"],
        "provider_errors": comp["provider_errors"], "evaluation": evaluation,
    }


def write_exit_variants_report(out_dir: Any = None, session=None, as_of: Any = None, price_provider=None,
                               **kwargs) -> dict:
    """data/reports/exit_variants_YYYY-MM-DD.md + .json 을 만든다(같은 날 재실행은 덮어씀, 시드 고정 → 멱등).

    Returns 보고서 dict + md_path/json_path. 성과 개선을 주장하지 않는다.
    """
    report = build_exit_variants_report(session, as_of=as_of, price_provider=price_provider, **kwargs)
    out = Path(out_dir) if out_dir else REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    stem = f"exit_variants_{report['as_of']}"
    md_path, json_path = out / f"{stem}.md", out / f"{stem}.json"
    md_path.write_text(_render_md(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {**report, "md_path": str(md_path), "json_path": str(json_path)}
