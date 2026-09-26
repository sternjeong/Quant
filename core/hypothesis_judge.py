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
5. 강건성(재현 연구에서 흔한 실패 유형 세 가지를 막는다):
   a. 손익분기 비용: 순수익 합이 0 이 되는 편도 bp ≥ 가정 비용 × BREAKEVEN_MARGIN(2). 비용은 회전율에 선형이라
      총수익 = 순수익 합 + 총회전율×bp 로 역산한다(복리 무시한 산술 근사).
   b. 최고의 달 제거: 월수익 상위 TOP_MONTHS_DROPPED(3)개월을 뺀 연샤프 ≥ 원래의 ROBUST_KEEP(50%).
      몇 달이 성과 전부를 만들면 운과 구별할 수 없다. 24개월 미만이면 검사하지 않는다.
   c. 파라미터 이웃: 대표 조합의 양수 숫자 파라미터(최대 3개)를 ×0.5·×1.5 로 바꿔 다시 백테스트한다.
      이웃 중 하나라도 연샤프 ≤ 0 이거나 이웃 중앙값 < 대표의 50% 면 탈락(한 점에서만 되는 절벽).
      이웃은 선택 후보가 아니라 검사이므로 시도 수(N)에 넣지 않는다. 대표 샤프가 0 이하면 돌리지 않는다.

6. 표본 밖(OOS) 구간: 백테스트 마지막 HOLDOUT_YEARS(2)년을 떼어 둔다. 파라미터 선택·DSR 은 그 앞 구간(IS)만으로
   하고, 고른 조합의 OOS 연샤프가 0 이하면 탈락. IS 가 MIN_IS_DAYS 나 OOS 가 MIN_OOS_DAYS 보다 짧으면 분리하지 않고
   전체 기간으로 판정한다(경고). 레짐·상관·kill_criteria·강건성 검사는 고른 조합의 전체 기간 수익으로 본다.
   한계: 에이전트는 과거 가설의 탈락 사유(context.md)를 읽으므로 OOS 구간이 가설 사이에서 완전히 봉인된 것은 아니다.

보고만 하는 항목(판정에 쓰지 않음): Ken French FF5+모멘텀 팩터 회귀(core.french_factors.factor_exposure).
알파 t < 2 이면 "알려진 팩터로 대부분 설명됨" 경고. 롱온리라 시장 베타가 큰 것은 정상이다.

파라미터 조합(params_grid)마다 백테스트하고 샤프가 가장 높은 조합을 대표로 쓴다 — 그래서 조합 수가 시도 수다.
비용은 실측 교정(core.cost_calibration, status ok) 편도 bp, 없으면 25bp 보수 가정.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from statistics import NormalDist, median, pvariance
from typing import Any, Callable, Optional

import pandas as pd

from core import hypothesis_engine as he

DSR_THRESHOLD = 0.95
DEFAULT_SR_ANNUAL_SD = 0.5
EULER_GAMMA = 0.5772156649
MIN_REGIME_DAYS = 60
MAX_CORR_SPY = 0.9
MAX_CORR_CHAMPION = 0.7
BENCHMARK = "SPY"
BREAKEVEN_MARGIN = 2.0
TOP_MONTHS_DROPPED = 3
MIN_MONTHS_FOR_TOP_DROP = 24
ROBUST_KEEP = 0.5
PARAM_SCALES = (0.5, 1.5)
MAX_NEIGHBOR_KEYS = 3
HOLDOUT_YEARS = 2
MIN_IS_DAYS = 756   # 약 3년
MIN_OOS_DAYS = 252  # 약 1년
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


def breakeven_bps(net: pd.Series, total_turnover: float, one_way_bps: float) -> Optional[float]:
    """순수익 합이 0 이 되는 편도 비용(bp). 회전이 없으면 None."""
    if total_turnover <= 0:
        return None
    gross = float(net.sum()) + total_turnover * one_way_bps / 1e4
    return gross / total_turnover * 1e4


def drop_top_months(r: pd.Series, k: int = TOP_MONTHS_DROPPED) -> dict[str, Any]:
    """월수익 상위 k 개월의 거래일을 뺀 연샤프."""
    r = r.dropna()
    month = r.index.to_period("M")
    monthly = (1 + r).groupby(month).prod() - 1
    if len(monthly) < MIN_MONTHS_FOR_TOP_DROP:
        return {"applicable": False, "n_months": len(monthly)}
    top = monthly.nlargest(k)
    rest = r[~month.isin(top.index)]
    return {"applicable": True, "n_months": len(monthly),
            "dropped": [{"month": str(p), "return": float(v)} for p, v in top.items()],
            "sharpe_annual": he.stats(rest).get("sharpe_annual", 0.0)}


def neighbor_params(params: dict) -> list[dict]:
    """양수 숫자 파라미터를 하나씩 ×0.5·×1.5 로 바꾼 조합. 정수는 반올림(최소 1)해 정수로 둔다."""
    keys = [k for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0]
    out: list[dict] = []
    for k in keys[:MAX_NEIGHBOR_KEYS]:
        for scale in PARAM_SCALES:
            v = params[k] * scale
            if isinstance(params[k], int):
                v = max(1, int(math.floor(v + 0.5)))
            if v == params[k]:
                continue
            n = {**params, k: v}
            if n not in out:
                out.append(n)
    return out


def holdout_split(index: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    """OOS 시작일(마지막 거래일 − HOLDOUT_YEARS). IS·OOS 가 최소 길이를 못 채우면 None."""
    if len(index) == 0:
        return None
    split = index[-1] - pd.DateOffset(years=HOLDOUT_YEARS)
    n_is, n_oos = int((index < split).sum()), int((index >= split).sum())
    return split if n_is >= MIN_IS_DAYS and n_oos >= MIN_OOS_DAYS else None


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
          champion_corr_fn=champion_correlation, cost: Optional[tuple[float, str]] = None,
          factors_fn: Optional[Callable[[], Optional[pd.DataFrame]]] = None) -> dict[str, Any]:
    spec = hyp["spec"]
    signal = he.load_signal(hyp["signal_code"])
    tickers, members_at = he.resolve_universe(spec)
    start = date.fromisoformat(spec["period"]["start"])
    end = date.fromisoformat(spec["period"]["end"]) if spec["period"].get("end") else date.today()
    prices = he.load_prices(sorted(set(tickers) | {BENCHMARK}), start, end, price_provider)
    bench = prices.get(BENCHMARK)
    universe_prices = {t: df for t, df in prices.items() if t in set(tickers)}
    bps, bps_source = cost or cost_bps()

    bts = [(params, he.backtest(spec, params, signal, universe_prices, members_at, bps))
           for params in spec["signal"]["params_grid"]]
    split = holdout_split(bts[0][1]["returns"].index)
    # 선택 통계: OOS 분리가 되면 IS 구간만, 아니면 전체 기간.
    trials = [(he.stats(bt["returns"][bt["returns"].index < split] if split is not None else bt["returns"]), params, bt)
              for params, bt in bts]
    trial_srs = [t[0].get("sharpe_daily", 0.0) for t in trials]
    sel_stats, best_params, best_bt = max(trials, key=lambda t: t[0].get("sharpe_daily", -1e9))
    r = best_bt["returns"]
    best_stats = he.stats(r)
    oos_stats = he.stats(r[r.index >= split]) if split is not None else None

    pool = prior_srs + trial_srs
    if len(pool) >= 2:
        variance, v_source = pvariance(pool), f"observed(n={len(pool)})"
    else:
        variance, v_source = (DEFAULT_SR_ANNUAL_SD / math.sqrt(he.TRADING_DAYS)) ** 2, "assumed(annual_sd=0.5)"
    n_total = max(cumulative_trials, len(trial_srs))
    dsr = deflated_sharpe(sel_stats.get("sharpe_daily", 0.0), sel_stats.get("n_days", 0), sel_stats.get("skew", 0.0),
                          sel_stats.get("kurtosis", 3.0), n_total, variance)

    reasons: list[str] = []
    if dsr["dsr"] < DSR_THRESHOLD:
        reasons.append(f"DSR {dsr['dsr']:.3f} < {DSR_THRESHOLD} (누적 시도 {n_total}{', IS 구간' if split is not None else ''})")
    if oos_stats is not None and oos_stats.get("sharpe_annual", 0.0) <= 0:
        reasons.append(f"OOS({split.date()}~) 연샤프 {oos_stats.get('sharpe_annual', 0.0):.2f} ≤ 0 "
                       f"(IS {sel_stats.get('sharpe_annual', 0.0):.2f})")
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
    if split is None:
        warnings.append(f"OOS 분리 없음 — 기간이 짧아(IS {MIN_IS_DAYS}·OOS {MIN_OOS_DAYS}거래일 미만) 전체 기간으로 선택·판정")
    be = breakeven_bps(r, best_bt.get("total_turnover", 0.0), bps)
    if be is not None and be < BREAKEVEN_MARGIN * bps:
        reasons.append(f"손익분기 비용 편도 {be:.1f}bp < 가정 {bps:.1f}bp×{BREAKEVEN_MARGIN:g}")
    full_sr = best_stats.get("sharpe_annual", 0.0)
    top = drop_top_months(r)
    if top["applicable"] and full_sr > 0 and top["sharpe_annual"] < ROBUST_KEEP * full_sr:
        reasons.append(f"상위 {TOP_MONTHS_DROPPED}개월 제외 연샤프 {top['sharpe_annual']:.2f} < 원래 {full_sr:.2f}의 "
                       f"{ROBUST_KEEP:.0%}")
    neighbors: list[dict] = []
    if full_sr > 0:
        for p in neighbor_params(best_params):
            try:
                nbt = he.backtest(spec, p, signal, universe_prices, members_at, bps)
                neighbors.append({"params": p, "sharpe_annual": he.stats(nbt["returns"]).get("sharpe_annual", 0.0)})
            except he.SignalError as exc:
                neighbors.append({"params": p, "error": str(exc)[:200]})
    n_srs = [x["sharpe_annual"] for x in neighbors if "error" not in x]
    if n_srs and (min(n_srs) <= 0 or median(n_srs) < ROBUST_KEEP * full_sr):
        reasons.append(f"파라미터 이웃 연샤프 최소 {min(n_srs):.2f}·중앙 {median(n_srs):.2f} (대표 {full_sr:.2f}) — 한 점에서만 됨")
    if len(n_srs) < len(neighbors):
        warnings.append(f"파라미터 이웃 {len(neighbors) - len(n_srs)}개 백테스트 실패")
    exposure = None
    if factors_fn is not None:
        from core.french_factors import factor_exposure

        try:
            exposure = factor_exposure(r, factors_fn())
        except Exception as exc:  # noqa: BLE001 — 보고 전용이라 판정을 막지 않는다
            warnings.append(f"팩터 회귀 실패: {type(exc).__name__}")
        if exposure and exposure["alpha_t"] < 2:
            warnings.append(f"FF5+모멘텀 회귀 알파 t={exposure['alpha_t']:.2f} < 2 — 알려진 팩터로 대부분 설명됨")
    cov = best_bt["price_coverage"]
    if cov is not None and cov < 0.8:
        warnings.append(f"가격 커버리지 {cov:.0%} — 폐지 종목 누락으로 생존편향 가능")
    return {
        "verdict": "fail" if reasons else "pass", "reasons": reasons, "warnings": warnings,
        "best_params": best_params, "stats": best_stats, "trial_srs": trial_srs,
        "holdout": {"split": split.date().isoformat() if split is not None else None,
                    "is_stats": sel_stats if split is not None else None, "oos_stats": oos_stats},
        "dsr": dsr["dsr"], "sr0_annual": dsr["sr0_daily"] * math.sqrt(he.TRADING_DAYS), "n_trials_total": n_total,
        "sr_variance_source": v_source, "regimes": regimes, "corr_spy": corr_spy, "champion_corr": champ,
        "n_rebalances": best_bt["n_rebalances"], "avg_turnover": best_bt["avg_turnover"],
        "price_coverage": cov, "missing_price_days": best_bt["missing_price_days"],
        "cost_one_way_bps": bps, "cost_source": bps_source, "breakeven_one_way_bps": be,
        "top_months_drop": top, "param_neighbors": neighbors, "factor_exposure": exposure,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _french_daily() -> Optional[pd.DataFrame]:
    from core.french_factors import daily_factors

    return daily_factors()


def judge_frozen(hyp_id: str, *, session=None, price_provider=None, champion_corr_fn=champion_correlation,
                 factors_fn=_french_daily) -> dict:
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
                    champion_corr_fn=champion_corr_fn, factors_fn=factors_fn)
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
