"""H19 - 연속 스펙트럼 프론티어: 트레일링스탑 타이트니스를 실제로 스윕.

배경: Case A(정적보유)/Case B(실시간청산 15%스탑+SPY스위치)는 이산적인 두 극단일 뿐이다. 이
스크립트는 "선정"은 H10 기준(돈치안20일+15%스탑 활성 종목 중 모멘텀 상위3, 반기 리밸런싱)을
고정한 채로, "청산" 트리거로 쓰는 트레일링스탑 폭만 {10%, 15%, 20%, 25%, 30%}로 스윕한다 -
선정 로직까지 같이 바꾸면 후보 자체가 달라져 순수하게 "청산 타이트니스"만의 효과를 분리해낼 수
없기 때문에, H16과 동일하게 이미 저장된 rebal_log(선정 결과)를 그대로 재사용하고 실시간청산
신호만 재계산한다(재선정 없음, 큰 재계산 비용 절감).

각 스탑 레벨에서: (1) 전체기간(2019-2026) core+15%새틀라이트 블렌드, (2) H18이 계산한 5개 위기
에피소드 각각의 위기서브윈도우 블렌드를 계산해 Sharpe/MDD/CAGR을 뽑고, 강세장CAGR-위기샤프 평면과
Sharpe-MDD 평면에서 파레토 효율점을 가려낸다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-21_satellite_signal_upgrade_and_crisis_test"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))

import pandas as pd

from champion_strategy import compute_portfolio_returns, _closes_from_histories, run_champion
from h1_core_satellite import blend_returns
from h10_trend_following_satellite import donchian_trailing_stop_positions, DONCHIAN_ENTRY_WINDOW, TREND_FETCH_LOOKBACK_DAYS
from h11_crisis_robustness_test import SATELLITE_TOP_K, SATELLITE_COST_BPS_PER_SIDE, run_three_asset_champion
from h12_regime_switch import fetch_spy_regime_signal, build_regime_switched_weight_series, blend_returns_time_varying, SATELLITE_WEIGHT_ON
from core.backtest_engine import calculate_metrics
from core.market_data import get_multiple_price_history

OUT_DIR = Path(__file__).resolve().parent
PRIOR_H10_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test"
H18_RESULTS = OUT_DIR / "h18_results.json"

SATELLITE_WEIGHT = 0.15
STOP_LEVELS = [0.10, 0.15, 0.20, 0.25, 0.30]

FULL_START, FULL_END = "2019-08-12", "2026-08-19"


def log(msg):
    print(f"[h19] {msg}", flush=True)


def build_exit_weights_at_stop(rebal_log: list[dict], start: str, end: str, trading_index: pd.DatetimeIndex,
                                stop_pct: float, top_k: int = SATELLITE_TOP_K) -> dict:
    """H16의 build_realtime_exit_weights와 동일 로직이나 stop_pct를 파라미터화."""
    all_tickers = sorted({t for r in rebal_log for t in r["picks"]})
    if not all_tickers:
        raise RuntimeError("보유 종목이 없음")

    fetch_start = (pd.Timestamp(rebal_log[0]["date"]) - pd.DateOffset(days=TREND_FETCH_LOOKBACK_DAYS)).date().isoformat()
    histories = get_multiple_price_history(all_tickers, start=fetch_start, end=end, interval="1d")
    closes = _closes_from_histories(histories, all_tickers)

    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    closes = closes.reindex(full_idx).ffill()

    signals = {}
    for t in all_tickers:
        raw = histories.get(t)
        if raw is None or raw.empty:
            signals[t] = pd.Series(0, index=full_idx)
            continue
        c = raw["Close"]
        pos = donchian_trailing_stop_positions(c, DONCHIAN_ENTRY_WINDOW, stop_pct)
        pos = pos.reindex(full_idx).ffill().fillna(0).astype(int)
        signals[t] = pos.shift(1).fillna(1)

    rebal_dates_sorted = sorted(pd.Timestamp(r["date"]) for r in rebal_log)
    rebal_map = {pd.Timestamp(r["date"]): r["picks"] for r in rebal_log}

    weights = pd.DataFrame(0.0, index=full_idx, columns=all_tickers)
    n_exits = 0
    n_slots = 0
    for period_i, rebal_date in enumerate(rebal_dates_sorted):
        picks = rebal_map[rebal_date]
        if not picks:
            continue
        period_end = rebal_dates_sorted[period_i + 1] if period_i + 1 < len(rebal_dates_sorted) else full_idx[-1] + pd.Timedelta(days=1)
        period_mask = (full_idx >= rebal_date) & (full_idx < period_end)
        period_dates = full_idx[period_mask]
        for t in picks:
            n_slots += 1
            sig = signals[t].reindex(period_dates).fillna(0)
            still_active = sig.cumprod().astype(bool)
            w = still_active.astype(float) * (1.0 / top_k)
            weights.loc[period_dates, t] = w.values
            if (~still_active).any():
                n_exits += 1

    result = compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)
    metrics = calculate_metrics(result["equity_net"], [], full_idx[0], full_idx[-1])
    return {"metrics": metrics, "ret_net": result["ret_net"], "n_exits": n_exits, "n_slots": n_slots}


def perf_metrics_slice(ret: pd.Series, start: str, end: str) -> dict:
    sliced = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if len(sliced) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "calmar": None, "n_days": len(sliced)}
    eq = (1 + sliced.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
    m["n_days"] = int(len(sliced))
    return m


def sweep_full_period() -> dict:
    log("전체기간(2019-2026) 스윕 시작 - H10 rebal_log 재사용")
    core_ret = pd.read_csv(PRIOR_H10_DIR / "core_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    h10 = json.loads((PRIOR_H10_DIR / "h10_results.json").read_text(encoding="utf-8"))
    rebal_log = h10["satellite_trend_following"]["rebal_log"]

    regime_raw = fetch_spy_regime_signal(FULL_START, FULL_END)
    weight_series = build_regime_switched_weight_series(core_ret.index, regime_raw, SATELLITE_WEIGHT_ON)

    out = {}
    for sp in STOP_LEVELS:
        t0 = time.time()
        rt = build_exit_weights_at_stop(rebal_log, FULL_START, FULL_END, core_ret.index, sp)
        blend = blend_returns(core_ret, rt["ret_net"], SATELLITE_WEIGHT)
        blend_switch = blend_returns_time_varying(core_ret, rt["ret_net"], weight_series)
        m_full = perf_metrics_slice(blend, FULL_START, FULL_END)
        m_full_switch = perf_metrics_slice(blend_switch, FULL_START, FULL_END)
        out[str(sp)] = {
            "stop_pct": sp, "n_exits": rt["n_exits"], "n_slots": rt["n_slots"],
            "full_period_no_switch": m_full, "full_period_with_switch": m_full_switch,
            "sat_ret": rt["ret_net"],
        }
        log(f"  stop={sp}: exits={rt['n_exits']}/{rt['n_slots']} full_sharpe(noswitch)={m_full['sharpe']} full_sharpe(switch)={m_full_switch['sharpe']} ({time.time()-t0:.0f}s)")
    return out


def sweep_crisis_episodes(full_period_result: dict) -> dict:
    """H18 결과의 5개 위기 에피소드 rebal_log를 재사용해 각 스탑 레벨의 위기 서브윈도우 성과를 계산."""
    if not H18_RESULTS.exists():
        log("h18_results.json 없음 - 위기 에피소드 스윕 건너뜀")
        return {}
    h18 = json.loads(H18_RESULTS.read_text(encoding="utf-8"))
    episodes = h18["episodes"]

    out = {}
    for label, ep in episodes.items():
        if "satellite_rebal_log" not in ep:
            # 2008/2022는 h16 결과 재사용이라 rebal_log를 h18에 저장 안 함 -> 별도 소스 필요
            continue
        rebal_log = ep["satellite_rebal_log"]
        full_start, full_end = ep["full_period"]
        crisis_start, crisis_end = ep["crisis_window"]
        log(f"위기 에피소드 스윕: {label} ({crisis_start}~{crisis_end})")

        core = run_champion(full_start, full_end)
        trading_index = core["ret_net"].index
        regime_raw = fetch_spy_regime_signal(full_start, full_end)
        weight_series = build_regime_switched_weight_series(trading_index, regime_raw, SATELLITE_WEIGHT_ON)

        ep_out = {}
        for sp in STOP_LEVELS:
            t0 = time.time()
            rt = build_exit_weights_at_stop(rebal_log, full_start, full_end, trading_index, sp)
            blend_switch = blend_returns_time_varying(core["ret_net"], rt["ret_net"], weight_series)
            m_crisis = perf_metrics_slice(blend_switch, crisis_start, crisis_end)
            ep_out[str(sp)] = {"stop_pct": sp, "n_exits": rt["n_exits"], "n_slots": rt["n_slots"], "crisis_window_with_switch": m_crisis}
            log(f"  [{label}] stop={sp}: crisis_sharpe={m_crisis['sharpe']} crisis_mdd={m_crisis['mdd']} ({time.time()-t0:.0f}s)")
        out[label] = ep_out
    return out


def gfc_2008_sweep() -> dict:
    """2008 GFC는 3자산 근사 코어를 써야 하므로 별도 처리(h16 rebal_log 재사용)."""
    h16_dir = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_satellite_realtime_stop_and_reentry_research"
    h16 = json.loads((h16_dir / "h16_results.json").read_text(encoding="utf-8"))
    h12 = json.loads((Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch/h12_results.json").read_text(encoding="utf-8"))
    rebal_log = h12["gfc_2008"]["satellite_rebal_log"]
    GFC_FULL_START, GFC_FULL_END = "2007-01-01", "2009-12-31"
    GFC_CRISIS_START, GFC_CRISIS_END = "2007-10-01", "2009-06-30"

    core = run_three_asset_champion(GFC_FULL_START, GFC_FULL_END)
    trading_index = core["ret_net"].index
    regime_raw = fetch_spy_regime_signal(GFC_FULL_START, GFC_FULL_END)
    weight_series = build_regime_switched_weight_series(trading_index, regime_raw, SATELLITE_WEIGHT_ON)

    out = {}
    for sp in STOP_LEVELS:
        t0 = time.time()
        rt = build_exit_weights_at_stop(rebal_log, GFC_FULL_START, GFC_FULL_END, trading_index, sp)
        blend_switch = blend_returns_time_varying(core["ret_net"], rt["ret_net"], weight_series)
        m_crisis = perf_metrics_slice(blend_switch, GFC_CRISIS_START, GFC_CRISIS_END)
        out[str(sp)] = {"stop_pct": sp, "n_exits": rt["n_exits"], "n_slots": rt["n_slots"], "crisis_window_with_switch": m_crisis}
        log(f"  [gfc_2008] stop={sp}: crisis_sharpe={m_crisis['sharpe']} crisis_mdd={m_crisis['mdd']} ({time.time()-t0:.0f}s)")
    return out


def bear2022_sweep() -> dict:
    """2022는 코어/전체구간이 H10 rebal_log와 동일하므로 sweep_full_period 결과에서 2022 서브윈도우만 잘라내면 됨."""
    core_ret = pd.read_csv(PRIOR_H10_DIR / "core_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    h10 = json.loads((PRIOR_H10_DIR / "h10_results.json").read_text(encoding="utf-8"))
    rebal_log = h10["satellite_trend_following"]["rebal_log"]
    regime_raw = fetch_spy_regime_signal(FULL_START, FULL_END)
    weight_series = build_regime_switched_weight_series(core_ret.index, regime_raw, SATELLITE_WEIGHT_ON)

    out = {}
    for sp in STOP_LEVELS:
        rt = build_exit_weights_at_stop(rebal_log, FULL_START, FULL_END, core_ret.index, sp)
        blend_switch = blend_returns_time_varying(core_ret, rt["ret_net"], weight_series)
        m_crisis = perf_metrics_slice(blend_switch, "2022-01-01", "2022-12-31")
        out[str(sp)] = {"stop_pct": sp, "n_exits": rt["n_exits"], "n_slots": rt["n_slots"], "crisis_window_with_switch": m_crisis}
        log(f"  [bear_2022] stop={sp}: crisis_sharpe={m_crisis['sharpe']} crisis_mdd={m_crisis['mdd']}")
    return out


def is_pareto_efficient(points: list[tuple], maximize: tuple[bool, bool]) -> list[bool]:
    """2차원 포인트 리스트에서 파레토효율 여부 계산. maximize=(True,True)면 둘 다 클수록 좋음."""
    n = len(points)
    eff = [True] * n
    for i in range(n):
        xi, yi = points[i]
        if xi is None or yi is None:
            eff[i] = False
            continue
        for j in range(n):
            if i == j:
                continue
            xj, yj = points[j]
            if xj is None or yj is None:
                continue
            better_x = (xj >= xi) if maximize[0] else (xj <= xi)
            better_y = (yj >= yi) if maximize[1] else (yj <= yi)
            strictly_better = (xj > xi if maximize[0] else xj < xi) or (yj > yi if maximize[1] else yj < yi)
            if better_x and better_y and strictly_better:
                eff[i] = False
                break
    return eff


def main():
    t0 = time.time()
    full = sweep_full_period()

    gfc = gfc_2008_sweep()
    bear2022 = bear2022_sweep()
    others = sweep_crisis_episodes(full)
    crisis_sweep = {"gfc_2008": gfc, "bear_2022": bear2022, **others}

    # 프론티어 좌표 구성: x=full-period Sharpe(스위치 적용), y=평균 위기 Sharpe(5개 에피소드, 스위치 적용)
    frontier_points = []
    for sp in STOP_LEVELS:
        sp_key = str(sp)
        full_sharpe = full[sp_key]["full_period_with_switch"]["sharpe"]
        full_cagr = full[sp_key]["full_period_with_switch"]["cagr"]
        full_mdd = full[sp_key]["full_period_with_switch"]["mdd"]
        crisis_sharpes = []
        crisis_cagrs = []
        for label, ep_sweep in crisis_sweep.items():
            if sp_key in ep_sweep:
                s = ep_sweep[sp_key]["crisis_window_with_switch"]["sharpe"]
                c = ep_sweep[sp_key]["crisis_window_with_switch"]["cagr"]
                if s is not None:
                    crisis_sharpes.append(s)
                if c is not None:
                    crisis_cagrs.append(c)
        avg_crisis_sharpe = sum(crisis_sharpes) / len(crisis_sharpes) if crisis_sharpes else None
        avg_crisis_cagr = sum(crisis_cagrs) / len(crisis_cagrs) if crisis_cagrs else None
        frontier_points.append({
            "stop_pct": sp, "full_period_sharpe": full_sharpe, "full_period_cagr": full_cagr, "full_period_mdd": full_mdd,
            "avg_crisis_sharpe_5ep": avg_crisis_sharpe, "avg_crisis_cagr_5ep": avg_crisis_cagr,
            "n_crisis_episodes_used": len(crisis_sharpes),
        })

    xs_sharpe_mdd = [(p["full_period_sharpe"], p["full_period_mdd"]) for p in frontier_points]
    pareto_sharpe_mdd = is_pareto_efficient(xs_sharpe_mdd, maximize=(True, True))  # mdd는 음수이므로 클수록(=0에 가까울수록) 좋음
    xs_bull_crisis = [(p["full_period_cagr"], p["avg_crisis_sharpe_5ep"]) for p in frontier_points]
    pareto_bull_crisis = is_pareto_efficient(xs_bull_crisis, maximize=(True, True))
    for i, p in enumerate(frontier_points):
        p["pareto_efficient_sharpe_vs_mdd"] = bool(pareto_sharpe_mdd[i])
        p["pareto_efficient_bull_cagr_vs_crisis_sharpe"] = bool(pareto_bull_crisis[i])

    def strip_full(d):
        return {k: {kk: vv for kk, vv in v.items() if kk != "sat_ret"} for k, v in d.items()}

    result = {
        "meta": {"stop_levels": STOP_LEVELS, "satellite_weight": SATELLITE_WEIGHT},
        "full_period_sweep": strip_full(full),
        "crisis_episode_sweep": crisis_sweep,
        "frontier_points": frontier_points,
    }
    with open(OUT_DIR / "h19_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h19_results.json'} (총 {time.time()-t0:.0f}s)")
    for p in frontier_points:
        log(f"  stop={p['stop_pct']}: full_sharpe={p['full_period_sharpe']} avg_crisis_sharpe={p['avg_crisis_sharpe_5ep']} "
            f"pareto(sharpe/mdd)={p['pareto_efficient_sharpe_vs_mdd']} pareto(bull/crisis)={p['pareto_efficient_bull_cagr_vs_crisis_sharpe']}")


if __name__ == "__main__":
    main()
