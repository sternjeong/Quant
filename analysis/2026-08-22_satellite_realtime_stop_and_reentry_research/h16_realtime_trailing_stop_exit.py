"""H16 - 새틀라이트 보유종목에 트레일링스탑 실시간 청산 적용.

배경(작업35/H15): point-in-time 추세추종 새틀라이트(H10)는 선정 시점엔 돈치안20일+15%
트레일링스탑 신호가 켜져 있어야만 후보가 되지만, 일단 선정되면 반기 리밸런싱 때까지 그 신호가
어떻게 되든 상관없이 "정적 보유"한다(H10 스크립트 docstring에 명시된 의도된 범위 제한). H15는
2021-07~2022-01 보유한 TSLA/NVDA/UPS가 2021-11-19 정점 이후 실제로 -13.2%(2021-12-20 기준)
빠지는 동안 이 정적 보유 메커니즘이 아무 것도 하지 않았음을 실측으로 확인했다.

이 스크립트는 H10이 이미 계산해 저장한 '선정 결과(rebal_log)'는 그대로 재사용하고(선정 로직은
바꾸지 않음 - 이번 라운드의 변경 대상이 아님), '보유 방식'만 바꾼다: 보유 기간 중 매일 각 보유
종목의 donchian_trailing_stop_positions 신호를 갱신해서, 신호가 1->0으로 꺼지는 순간 그 슬롯을
그 반기 잔여기간 동안 현금(0 비중)으로 전환한다(재진입 없음 - H17에서 재진입 정책을 별도로 다룸).
룩어헤드 방지를 위해 신호는 1일 지연(t-1일 확정 신호를 t일 비중에 적용)해서 쓴다 - 이 저장소의
다른 국면필터(H12의 SPY 200일선 스위치 등)와 동일한 관례.

3개 구간(2019-2026 전체/2022 약세장/2008 GFC)에서 (a) 코어단독, (b) 코어+정적보유 새틀라이트
(H10 베이스라인), (c) 코어+실시간청산 새틀라이트(이번 라운드), (d) 코어+실시간청산 새틀라이트+
SPY 200일선 포트폴리오 레벨 스위치(H12) 를 비교한다. 그리고 H15의 2021-2022 사례를 실시간청산
적용 시 그대로 재현해 실제 회피된 손실을 계산한다.
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

import numpy as np
import pandas as pd

from champion_strategy import compute_portfolio_returns, _closes_from_histories
from h1_core_satellite import blend_returns, SATELLITE_TOP_K, SATELLITE_COST_BPS_PER_SIDE, SATELLITE_WARMUP_DAYS
from h10_trend_following_satellite import donchian_trailing_stop_positions, DONCHIAN_ENTRY_WINDOW, DONCHIAN_STOP_PCT, TREND_FETCH_LOOKBACK_DAYS
from h11_crisis_robustness_test import run_three_asset_champion, THREE_ASSET_UNIVERSE, GFC_FULL_START, GFC_FULL_END, GFC_CRISIS_START, GFC_CRISIS_END
from h12_regime_switch import fetch_spy_regime_signal, build_regime_switched_weight_series, blend_returns_time_varying, SATELLITE_WEIGHT_ON
from core.backtest_engine import calculate_metrics
from core.market_data import get_multiple_price_history

PRIOR_H10_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test"
PRIOR_H12_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch"
OUT_DIR = Path(__file__).resolve().parent

FULL_START, FULL_END = "2019-08-12", "2026-08-19"
BEAR2022_START, BEAR2022_END = "2022-01-01", "2022-12-31"
SATELLITE_WEIGHT = 0.15


def log(msg):
    print(f"[h16] {msg}", flush=True)


def build_realtime_exit_weights(rebal_log: list[dict], start: str, end: str, trading_index: pd.DatetimeIndex,
                                 top_k: int = SATELLITE_TOP_K) -> dict:
    """H10/H11의 rebal_log(선정 결과)를 그대로 받아, 보유기간 중 트레일링스탑 실시간 청산을
    적용한 일별 비중 시계열과 청산 이벤트 로그를 만든다."""
    all_tickers = sorted({t for r in rebal_log for t in r["picks"]})
    if not all_tickers:
        raise RuntimeError("보유 종목이 없음")

    fetch_start = (pd.Timestamp(rebal_log[0]["date"]) - pd.DateOffset(days=TREND_FETCH_LOOKBACK_DAYS)).date().isoformat()
    histories = get_multiple_price_history(all_tickers, start=fetch_start, end=end, interval="1d")
    closes = _closes_from_histories(histories, all_tickers)

    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    closes = closes.reindex(full_idx).ffill()

    # 종목별 트레일링스탑 신호(전체 이력 기준 1회 계산 후 정렬) - 1일 지연해서 사용
    signals = {}
    for t in all_tickers:
        raw = histories.get(t)
        if raw is None or raw.empty:
            signals[t] = pd.Series(0, index=full_idx)
            continue
        c = raw["Close"]
        pos = donchian_trailing_stop_positions(c, DONCHIAN_ENTRY_WINDOW, DONCHIAN_STOP_PCT)
        pos = pos.reindex(full_idx).ffill().fillna(0).astype(int)
        signals[t] = pos.shift(1).fillna(1)  # 리밸런싱 첫날엔 전일 신호가 곧 선정 근거 신호(활성)였으므로 1

    rebal_dates_sorted = sorted(pd.Timestamp(r["date"]) for r in rebal_log)
    rebal_map = {pd.Timestamp(r["date"]): r["picks"] for r in rebal_log}

    weights = pd.DataFrame(0.0, index=full_idx, columns=all_tickers)
    exit_events = []
    for period_i, rebal_date in enumerate(rebal_dates_sorted):
        picks = rebal_map[rebal_date]
        if not picks:
            continue
        period_end = rebal_dates_sorted[period_i + 1] if period_i + 1 < len(rebal_dates_sorted) else full_idx[-1] + pd.Timedelta(days=1)
        period_mask = (full_idx >= rebal_date) & (full_idx < period_end)
        period_dates = full_idx[period_mask]
        for t in picks:
            sig = signals[t].reindex(period_dates).fillna(0)
            still_active = sig.cumprod().astype(bool)  # 한 번 0이 되면 그 뒤로 영구 0(재진입 없음)
            w = still_active.astype(float) * (1.0 / top_k)
            weights.loc[period_dates, t] = w.values
            exit_idx = still_active[~still_active]
            if len(exit_idx) > 0:
                exit_date = exit_idx.index[0]
                days_held = int((exit_idx.index[0] - rebal_date).days)
                exit_events.append({
                    "ticker": t, "rebal_date": str(rebal_date.date()), "exit_date": str(exit_date.date()),
                    "period_end": str(period_dates[-1].date()) if len(period_dates) else None,
                    "calendar_days_held_before_exit": days_held,
                    "exited_early": True,
                })
            else:
                exit_events.append({"ticker": t, "rebal_date": str(rebal_date.date()), "exit_date": None,
                                     "period_end": str(period_dates[-1].date()) if len(period_dates) else None,
                                     "exited_early": False})

    result = compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)
    metrics = calculate_metrics(result["equity_net"], [], full_idx[0], full_idx[-1])
    return {
        "metrics": metrics, "ret_net": result["ret_net"], "equity_net": result["equity_net"],
        "weights": weights, "exit_events": exit_events, "tickers_ever_held": all_tickers,
    }


def perf_metrics_slice(ret: pd.Series, start: str, end: str) -> dict:
    sliced = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if len(sliced) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "calmar": None, "n_days": len(sliced)}
    eq = (1 + sliced.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
    m["n_days"] = int(len(sliced))
    return m


def part_full_and_2022() -> dict:
    log("전체기간/2022: H10 코어/정적새틀라이트 CSV 재사용 + 실시간청산 새틀라이트 신규 구축")
    core_ret = pd.read_csv(PRIOR_H10_DIR / "core_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_static_ret = pd.read_csv(PRIOR_H10_DIR / "sat_trend_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]

    h10 = json.loads((PRIOR_H10_DIR / "h10_results.json").read_text(encoding="utf-8"))
    rebal_log = h10["satellite_trend_following"]["rebal_log"]

    rt = build_realtime_exit_weights(rebal_log, FULL_START, FULL_END, core_ret.index)
    log(f"실시간청산 새틀라이트 지표(단독): {rt['metrics']}")
    n_exits = sum(1 for e in rt["exit_events"] if e["exited_early"])
    log(f"청산 이벤트: {n_exits}/{len(rt['exit_events'])} 슬롯이 반기 도중 조기 청산됨")

    static_blend = blend_returns(core_ret, sat_static_ret, SATELLITE_WEIGHT)
    rt_blend = blend_returns(core_ret, rt["ret_net"], SATELLITE_WEIGHT)

    # SPY 스위치와 결합(4번째 구성)
    regime_raw = fetch_spy_regime_signal(FULL_START, FULL_END)
    weight_series = build_regime_switched_weight_series(core_ret.index, regime_raw, SATELLITE_WEIGHT)
    rt_switch_blend = blend_returns_time_varying(core_ret, rt["ret_net"], weight_series)

    windows = {"full_2019_2026": (FULL_START, FULL_END), "bear_2022": (BEAR2022_START, BEAR2022_END)}
    table = {}
    for wname, (ws, we) in windows.items():
        table[wname] = {
            "core_alone": perf_metrics_slice(core_ret, ws, we),
            "core_plus_static_satellite": perf_metrics_slice(static_blend, ws, we),
            "core_plus_realtime_exit_satellite": perf_metrics_slice(rt_blend, ws, we),
            "core_plus_realtime_exit_satellite_plus_spy_switch": perf_metrics_slice(rt_switch_blend, ws, we),
        }
    return {
        "windows": table, "exit_events": rt["exit_events"], "n_early_exits": n_exits, "n_slots": len(rt["exit_events"]),
        "realtime_sat_ret": rt["ret_net"], "core_ret": core_ret, "static_sat_ret": sat_static_ret,
        "rt_blend": rt_blend, "static_blend": static_blend, "rt_switch_blend": rt_switch_blend,
        "weights_realtime": rt["weights"],
    }


def part_gfc_2008() -> dict:
    log("2008 GFC: 3자산 코어 재구축 + H12 저장 픽 재사용 + 실시간청산 새틀라이트")
    h12 = json.loads((PRIOR_H12_DIR / "h12_results.json").read_text(encoding="utf-8"))
    rebal_log = h12["gfc_2008"]["satellite_rebal_log"]

    core = run_three_asset_champion(GFC_FULL_START, GFC_FULL_END)
    trading_index = core["ret_net"].index
    log(f"3자산 코어 지표: {core['metrics']}")

    core_ret_gfc = pd.read_csv(PRIOR_H12_DIR / "gfc_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_static_ret_gfc = pd.read_csv(PRIOR_H12_DIR / "gfc_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]

    rt = build_realtime_exit_weights(rebal_log, GFC_FULL_START, GFC_FULL_END, trading_index)
    log(f"실시간청산 새틀라이트 지표(GFC, 단독): {rt['metrics']}")
    n_exits = sum(1 for e in rt["exit_events"] if e["exited_early"])
    log(f"GFC 청산 이벤트: {n_exits}/{len(rt['exit_events'])}")

    static_blend = blend_returns(core_ret_gfc, sat_static_ret_gfc, SATELLITE_WEIGHT)
    rt_blend = blend_returns(core_ret_gfc, rt["ret_net"], SATELLITE_WEIGHT)

    regime_raw = fetch_spy_regime_signal(GFC_FULL_START, GFC_FULL_END)
    weight_series = build_regime_switched_weight_series(trading_index, regime_raw, SATELLITE_WEIGHT)
    rt_switch_blend = blend_returns_time_varying(core_ret_gfc, rt["ret_net"], weight_series)

    windows = {"full_2007_2009": (GFC_FULL_START, GFC_FULL_END), "crisis_2007_10_2009_06": (GFC_CRISIS_START, GFC_CRISIS_END)}
    table = {}
    for wname, (ws, we) in windows.items():
        table[wname] = {
            "core_alone": perf_metrics_slice(core_ret_gfc, ws, we),
            "core_plus_static_satellite": perf_metrics_slice(static_blend, ws, we),
            "core_plus_realtime_exit_satellite": perf_metrics_slice(rt_blend, ws, we),
            "core_plus_realtime_exit_satellite_plus_spy_switch": perf_metrics_slice(rt_switch_blend, ws, we),
        }
    return {"windows": table, "exit_events": rt["exit_events"], "n_early_exits": n_exits, "n_slots": len(rt["exit_events"])}


def part_2021_case_study(full_result: dict) -> dict:
    """H15의 2021-2022 사례를 실시간청산 적용 결과로 재현: 2021-07-01 리밸런싱 TSLA/NVDA/UPS가
    실제로 언제 청산됐는지, 그 청산이 H15가 발견한 -13.2%(2021-12-20 기준) 낙폭을 얼마나 피했는지."""
    events = [e for e in full_result["exit_events"] if e["rebal_date"] == "2021-07-01"]
    log(f"2021-07-01 리밸런싱(TSLA/NVDA/UPS) 청산 이벤트: {events}")

    rt_sat_ret = full_result["realtime_sat_ret"]
    static_sat_ret = full_result["static_sat_ret"]
    WIN_START, WIN_END = "2021-09-01", "2022-03-31"
    rt_win = rt_sat_ret[(rt_sat_ret.index >= WIN_START) & (rt_sat_ret.index <= WIN_END)]
    static_win = static_sat_ret[(static_sat_ret.index >= WIN_START) & (static_sat_ret.index <= WIN_END)]

    def dd_series(ret):
        eq = (1 + ret.fillna(0.0)).cumprod()
        peak = eq.cummax()
        return eq, peak, eq / peak - 1.0

    rt_eq, rt_peak, rt_dd = dd_series(rt_win)
    static_eq, static_peak, static_dd = dd_series(static_win)

    rt_trough_date = rt_dd.idxmin()
    static_trough_date = static_dd.idxmin()

    # H15가 보고한 기준일(2021-12-20)에서의 낙폭 비교
    ref_date = pd.Timestamp("2021-12-20")
    rt_dd_at_ref = float(rt_dd.reindex([ref_date], method="ffill").iloc[0])
    static_dd_at_ref = float(static_dd.reindex([ref_date], method="ffill").iloc[0])

    result = {
        "exit_events_2021h2": events,
        "static_hold_window_trough": {"date": str(static_trough_date.date()), "dd_pct": round(float(static_dd.min()) * 100, 2)},
        "realtime_exit_window_trough": {"date": str(rt_trough_date.date()), "dd_pct": round(float(rt_dd.min()) * 100, 2)},
        "static_hold_dd_at_2021_12_20_pct": round(static_dd_at_ref * 100, 2),
        "realtime_exit_dd_at_2021_12_20_pct": round(rt_dd_at_ref * 100, 2),
        "avoided_drawdown_pct_points_at_2021_12_20": round((static_dd_at_ref - rt_dd_at_ref) * 100, 2),
        "static_hold_dd_series": {str(k.date()): round(float(v), 4) for k, v in static_dd.items()},
        "realtime_exit_dd_series": {str(k.date()): round(float(v), 4) for k, v in rt_dd.items()},
    }
    log(f"H15 사례 재검증: 정적보유 저점 {result['static_hold_window_trough']}, "
        f"실시간청산 저점 {result['realtime_exit_window_trough']}, "
        f"2021-12-20 시점 낙폭: 정적 {result['static_hold_dd_at_2021_12_20_pct']}% vs 실시간청산 {result['realtime_exit_dd_at_2021_12_20_pct']}% "
        f"(회피 {result['avoided_drawdown_pct_points_at_2021_12_20']}%p)")
    return result


def main():
    t0 = time.time()
    p1 = part_full_and_2022()
    p2 = part_gfc_2008()
    case_2021 = part_2021_case_study(p1)

    def strip(d, extra_drop=()):
        drop = {"realtime_sat_ret", "core_ret", "static_sat_ret", "rt_blend", "static_blend", "rt_switch_blend", "weights_realtime", *extra_drop}
        return {k: v for k, v in d.items() if k not in drop}

    result = {
        "meta": {"satellite_weight": SATELLITE_WEIGHT, "donchian_entry_window": DONCHIAN_ENTRY_WINDOW, "donchian_stop_pct": DONCHIAN_STOP_PCT},
        "full_and_2022": strip(p1),
        "gfc_2008": p2,
        "case_study_2021_growth_unwind": case_2021,
    }
    with open(OUT_DIR / "h16_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h16_results.json'}")

    # H17 재사용용 CSV 저장
    p1["core_ret"].to_frame("core_ret").to_csv(OUT_DIR / "full_core_ret.csv")
    p1["realtime_sat_ret"].to_frame("realtime_sat_ret").to_csv(OUT_DIR / "full_realtime_sat_ret.csv")
    p1["static_sat_ret"].to_frame("static_sat_ret").to_csv(OUT_DIR / "full_static_sat_ret.csv")
    p1["weights_realtime"].to_csv(OUT_DIR / "full_realtime_weights.csv")
    log(f"CSV 저장 완료 (H17 재사용용, 총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
