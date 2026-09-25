"""가설 자동 심판 (설계 S2, docs/AGENTIC_QUANT_SYSTEM_DESIGN.md 3.2절) — LLM 없음, 판정은 pass/fail 두 가지뿐.

통과 조건(전부 만족):
1. Deflated Sharpe Ratio ≥ DSR_THRESHOLD(0.95). N = 레지스트리 누적 시도 수(이 가설 포함, 줄지 않음).
   V(시도 간 일별 샤프 분산) = 지금까지 기록된 모든 시도 샤프의 분산. 기록이 2개 미만이면 연 샤프 표준편차 0.5 가정.
   (Bailey & López de Prado 2014: SR0 = √V·((1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne))),
    DSR = Φ((SR−SR0)√(T−1) / √(1 − skew·SR + (kurt−1)/4·SR²)))
2. 레짐(강세/약세/횡보, core.market_regime.classify_daily_regime on SPY) 중 60거래일 이상인 레짐의 과반에서
   SPY 보다 연율 수익이 높다 — 같은 레짐끼리만 비교한다(프로젝트 결정).
3. SPY 일수익과의 상관 < 0.9 (시장 베타 복제 차단). 챔피언 라이브 원장과 60일 이상 겹치면 상관 < 0.7.
4. kill_criteria: 리밸런싱 횟수 ≥ min_rebalances, 최대낙폭 ≤ max_drawdown.

파라미터 조합(params_grid)마다 백테스트하고 샤프가 가장 높은 조합을 대표로 쓴다 — 그래서 조합 수가 시도 수다.
비용은 실측 교정(core.cost_calibration, status ok) 편도 bp, 없으면 25bp 보수 가정.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from statistics import NormalDist, pvariance
from typing import Any, Optional

import pandas as pd

from core import hypothesis_engine as he

DSR_THRESHOLD = 0.95
DEFAULT_SR_ANNUAL_SD = 0.5
EULER_GAMMA = 0.5772156649
MIN_REGIME_DAYS = 60
MAX_CORR_SPY = 0.9
MAX_CORR_CHAMPION = 0.7
BENCHMARK = "SPY"
_N = NormalDist()


def expected_max_sr(n_trials: int, variance: float) -> float:
    """N 번 시도했을 때 우연만으로 기대되는 최대 샤프(일별 단위)."""
    if n_trials <= 1 or variance <= 0:
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(variance) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


def deflated_sharpe(sr: float, n_days: int, skew: float, kurt: float, n_trials: int, variance: float) -> dict[str, float]:
    sr0 = expected_max_sr(n_trials, variance)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if n_days < 2 or denom <= 0:
        return {"dsr": 0.0, "sr0_daily": sr0}
    return {"dsr": _N.cdf((sr - sr0) * math.sqrt(n_days - 1) / math.sqrt(denom)), "sr0_daily": sr0}


def cost_bps() -> tuple[float, str]:
    try:
        from core.cost_calibration import load_cost_calibration

        cal = load_cost_calibration()
        if cal and cal.get("status") == "ok" and cal.get("scenario"):
            sc = cal["scenario"]
            return float(sc.get("fee_bps", 0.0)) + float(sc["slippage_bps"]), f"measured(n={cal.get('n')})"
    except Exception:  # noqa: BLE001
        pass
    return he.DEFAULT_ONE_WAY_BPS, "assumed_25bp"


def regime_table(strat: pd.Series, bench: pd.DataFrame) -> list[dict[str, Any]]:
    from core.market_regime import classify_daily_regime

    labels = classify_daily_regime(bench["Close"], bench.get("High", bench["Close"]), bench.get("Low", bench["Close"]))
    b_ret = bench["Close"].pct_change(fill_method=None)
    df = pd.DataFrame({"s": strat, "b": b_ret, "reg": labels}).dropna()
    out = []
    for reg, g in df.groupby("reg"):
        n = len(g)
        ann = lambda x: float((1 + x).prod() ** (he.TRADING_DAYS / n) - 1)  # noqa: E731
        out.append({"regime": reg, "days": n, "strategy_ann": ann(g["s"]), "benchmark_ann": ann(g["b"]),
                    "excess_ann": ann(g["s"]) - ann(g["b"]), "qualifies": n >= MIN_REGIME_DAYS})
    return out


def champion_correlation(strat: pd.Series) -> Optional[dict]:
    try:
        from core.db import get_session
        from core.models import ChampionLedgerEntry

        with get_session() as db:
            rows = db.query(ChampionLedgerEntry.entry_date, ChampionLedgerEntry.realized_return_pct).all()
    except Exception:  # noqa: BLE001
        return None
    champ = pd.Series({pd.Timestamp(d): r / 100 for d, r in rows})
    both = pd.DataFrame({"s": strat, "c": champ}).dropna()
    if len(both) < 60:
        return {"n": len(both), "corr": None}
    return {"n": len(both), "corr": float(both["s"].corr(both["c"]))}


def prior_trial_srs(session=None) -> list[float]:
    from core import hypothesis_registry as reg

    out: list[float] = []
    for h in reg.list_by_status(*reg.FROZEN_STATES, session=session):
        out.extend((h.get("judge") or {}).get("trial_srs") or [])
    return out


def judge(hyp: dict, *, cumulative_trials: int, prior_srs: list[float], price_provider=None,
          champion_corr_fn=champion_correlation, cost: Optional[tuple[float, str]] = None) -> dict[str, Any]:
    spec = hyp["spec"]
    signal = he.load_signal(hyp["signal_code"])
    tickers, members_at = he.resolve_universe(spec)
    start = date.fromisoformat(spec["period"]["start"])
    end = date.fromisoformat(spec["period"]["end"]) if spec["period"].get("end") else date.today()
    prices = he.load_prices(sorted(set(tickers) | {BENCHMARK}), start, end, price_provider)
    bench = prices.get(BENCHMARK)
    universe_prices = {t: df for t, df in prices.items() if t in set(tickers)}
    bps, bps_source = cost or cost_bps()

    trials = []
    for params in spec["signal"]["params_grid"]:
        bt = he.backtest(spec, params, signal, universe_prices, members_at, bps)
        trials.append((he.stats(bt["returns"]), params, bt))
    trial_srs = [t[0].get("sharpe_daily", 0.0) for t in trials]
    best_stats, best_params, best_bt = max(trials, key=lambda t: t[0].get("sharpe_daily", -1e9))
    r = best_bt["returns"]

    pool = prior_srs + trial_srs
    if len(pool) >= 2:
        variance, v_source = pvariance(pool), f"observed(n={len(pool)})"
    else:
        variance, v_source = (DEFAULT_SR_ANNUAL_SD / math.sqrt(he.TRADING_DAYS)) ** 2, "assumed(annual_sd=0.5)"
    n_total = max(cumulative_trials, len(trial_srs))
    dsr = deflated_sharpe(best_stats.get("sharpe_daily", 0.0), best_stats.get("n_days", 0), best_stats.get("skew", 0.0),
                          best_stats.get("kurtosis", 3.0), n_total, variance)

    reasons: list[str] = []
    if dsr["dsr"] < DSR_THRESHOLD:
        reasons.append(f"DSR {dsr['dsr']:.3f} < {DSR_THRESHOLD} (누적 시도 {n_total})")
    regimes, corr_spy = [], None
    if bench is None:
        reasons.append("벤치마크(SPY) 가격 없음 — 레짐·상관 검사 불가")
    else:
        regimes = regime_table(r, bench)
        q = [x for x in regimes if x["qualifies"]]
        wins = sum(1 for x in q if x["excess_ann"] > 0)
        if not q or wins * 2 <= len(q):
            reasons.append(f"레짐별 SPY 초과: {wins}/{len(q)} (과반 필요)")
        both = pd.DataFrame({"s": r, "b": bench["Close"].pct_change(fill_method=None)}).dropna()
        corr_spy = float(both["s"].corr(both["b"])) if len(both) > 30 else None
        if corr_spy is not None and corr_spy >= MAX_CORR_SPY:
            reasons.append(f"SPY 상관 {corr_spy:.2f} ≥ {MAX_CORR_SPY}")
    champ = champion_corr_fn(r) if champion_corr_fn else None
    if champ and champ.get("corr") is not None and champ["corr"] >= MAX_CORR_CHAMPION:
        reasons.append(f"챔피언 상관 {champ['corr']:.2f} ≥ {MAX_CORR_CHAMPION}")
    kill = spec["kill_criteria"]
    if best_bt["n_rebalances"] < kill["min_rebalances"]:
        reasons.append(f"리밸런싱 {best_bt['n_rebalances']}회 < {kill['min_rebalances']}")
    if abs(best_stats.get("max_drawdown", 0.0)) > kill["max_drawdown"]:
        reasons.append(f"최대낙폭 {best_stats['max_drawdown']:.1%} > {kill['max_drawdown']:.0%}")

    warnings = []
    cov = best_bt["price_coverage"]
    if cov is not None and cov < 0.8:
        warnings.append(f"가격 커버리지 {cov:.0%} — 폐지 종목 누락으로 생존편향 가능")
    return {
        "verdict": "fail" if reasons else "pass", "reasons": reasons, "warnings": warnings,
        "best_params": best_params, "stats": best_stats, "trial_srs": trial_srs,
        "dsr": dsr["dsr"], "sr0_annual": dsr["sr0_daily"] * math.sqrt(he.TRADING_DAYS), "n_trials_total": n_total,
        "sr_variance_source": v_source, "regimes": regimes, "corr_spy": corr_spy, "champion_corr": champ,
        "n_rebalances": best_bt["n_rebalances"], "avg_turnover": best_bt["avg_turnover"],
        "price_coverage": cov, "missing_price_days": best_bt["missing_price_days"],
        "cost_one_way_bps": bps, "cost_source": bps_source,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def judge_frozen(hyp_id: str, *, session=None, price_provider=None, champion_corr_fn=champion_correlation) -> dict:
    """frozen 가설을 심판하고 pass/fail 로 전이한다. 데이터·코드 오류는 전이하지 않고 status=error 로 돌려준다."""
    from core import hypothesis_registry as reg
    from core.models import Hypothesis

    hyp = reg.get(hyp_id, session=session)
    if hyp is None or hyp["status"] != reg.FROZEN:
        return {"status": "skipped", "reason": "not frozen"}
    with reg._session(session) as db:
        n_total = reg.cumulative_trials(db)
    try:
        res = judge(hyp, cumulative_trials=n_total, prior_srs=prior_trial_srs(session), price_provider=price_provider,
                    champion_corr_fn=champion_corr_fn)
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"[:500]
        with reg._session(session) as db:
            row = db.get(Hypothesis, hyp_id)
            note = row.note or ""
            n = int(note.split("=", 1)[1]) + 1 if note.startswith("judge_errors=") else 1
            row.note = f"judge_errors={n}"
        if n >= 3:
            reg.transition(hyp_id, reg.FAIL, f"심판 3회 연속 오류: {err}", session=session,
                           judge={"verdict": "fail", "reasons": [f"error: {err}"], "trial_srs": []})
            return {"status": "failed_after_errors", "error": err}
        return {"status": "error", "error": err, "attempt": n}
    reg.transition(hyp_id, reg.PASS if res["verdict"] == "pass" else reg.FAIL,
                   "; ".join(res["reasons"]) or "all checks passed", session=session, judge=res)
    return {"status": res["verdict"], "judge": res}
