"""H17 - 청산 후 재진입 정책: 즉시 재탐색 vs 다음 리밸런싱까지 현금 대기(H16 기본값).

H16이 실시간 트레일링스탑 청산을 새틀라이트 보유 슬롯에 적용했더니, 청산된 슬롯은 반기 잔여기간
내내 현금으로 남았다(기본 정책, 이 스크립트에서 "현금대기"로 재확인). 이 스크립트는 그 대안으로
"즉시 재탐색"을 구현한다: 슬롯이 청산되는 그 날, 그 반기 리밸런싱 시점에 이미 뽑아둔 point-in-time
후보 풀(같은 자격조건, 네트워크 재호출 없이 재사용 - 같은 반기 안이라 시가총액 랭킹이 크게
바뀌지 않는다는 전제) 안에서 "그 날 기준 돈치안 신호가 활성인" 종목 중 (이미 이 반기 동안 보유
중이거나 이미 청산된 종목 제외) 12개월 모멘텀 최고 종목으로 즉시 교체한다. 교체 종목도 똑같이
실시간 트레일링스탑을 적용받아, 반기가 끝나기 전에 또 청산될 수 있고 그러면 다시 재탐색한다
(슬롯당 재탐색 최대 5회로 제한 - 무한루프 방지, 실제로는 거의 도달하지 않음).

3개 정책 비교: (a) H16 그대로(청산 후 현금대기, baseline=control), (b) 즉시 재탐색(신규).
회전율 증가에 따른 거래비용은 compute_portfolio_returns의 비중변화 기반 왕복0.1% 비용 모델이
자동으로 반영한다(재진입도 신규 매수와 동일하게 비용 부과).
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

from champion_strategy import compute_portfolio_returns, _closes_from_histories
from h1_core_satellite import blend_returns, SATELLITE_TOP_K, SATELLITE_COST_BPS_PER_SIDE, SATELLITE_MOMENTUM_WINDOW
from h10_trend_following_satellite import donchian_trailing_stop_positions, DONCHIAN_ENTRY_WINDOW, DONCHIAN_STOP_PCT, TREND_FETCH_LOOKBACK_DAYS
from h11_crisis_robustness_test import run_three_asset_champion, THREE_ASSET_UNIVERSE, GFC_FULL_START, GFC_FULL_END, GFC_CRISIS_START, GFC_CRISIS_END
from core.backtest_engine import calculate_metrics
from core.market_data import get_multiple_price_history
from core.strategy_tuning import sample_universe

PRIOR_H10_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test"
PRIOR_H12_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch"
OUT_DIR = Path(__file__).resolve().parent

FULL_START, FULL_END = "2019-08-12", "2026-08-19"
BEAR2022_START, BEAR2022_END = "2022-01-01", "2022-12-31"
SATELLITE_WEIGHT = 0.15
MAX_RESEARCH_PER_SLOT = 5


def log(msg):
    print(f"[h17] {msg}", flush=True)


def perf_metrics_slice(ret: pd.Series, start: str, end: str) -> dict:
    sliced = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if len(sliced) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "calmar": None, "n_days": len(sliced)}
    eq = (1 + sliced.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
    m["n_days"] = int(len(sliced))
    return m


def fetch_period_pool_and_signals(rebal_date: pd.Timestamp, period_end: pd.Timestamp, exclude: set,
                                   initial_picks: list[str], pool_n: int = 40) -> dict:
    """rebal_date 시점 point-in-time 후보 풀을 뽑고, period_end까지의 가격이력/돈치안신호/모멘텀을
    한 번에 계산해둔다 (재탐색마다 네트워크 호출을 반복하지 않기 위함).

    주의(버그 수정): 초기 보유 종목(initial_picks)은 exclude 대상이라도 신호 계산 자체는 반드시
    포함해야 한다 - exclude는 "재탐색 후보로 재선정하지 않을 종목"일 뿐, "보유 중인 종목의 청산
    신호를 추적하지 않는다"는 뜻이 아니다. 처음 구현에서 exclude에 picks를 섞어 넘겨 candidates
    리스트 자체에서 picks가 빠지는 바람에 보유종목의 청산신호가 전혀 계산되지 않아 재탐색이
    한 번도 발생하지 않는 버그가 있었다."""
    as_of_str = rebal_date.date().isoformat()
    pool = sample_universe(n=pool_n, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
    candidates = [t for t in pool["ticker"].tolist() if t not in exclude]
    candidates = sorted(set(candidates) | set(initial_picks))  # 보유종목은 반드시 신호추적 대상에 포함

    fetch_start = (rebal_date - pd.DateOffset(days=TREND_FETCH_LOOKBACK_DAYS)).date().isoformat()
    fetch_end = period_end.date().isoformat()
    histories = get_multiple_price_history(candidates, start=fetch_start, end=fetch_end, interval="1d")

    signals, moms, closes = {}, {}, {}
    for t in candidates:
        df = histories.get(t)
        if df is None or df.empty:
            continue
        close = df["Close"]
        pos = donchian_trailing_stop_positions(close, DONCHIAN_ENTRY_WINDOW, DONCHIAN_STOP_PCT)
        signals[t] = pos
        closes[t] = close
        moms[t] = close.pct_change(SATELLITE_MOMENTUM_WINDOW)
    return {"candidates": list(signals.keys()), "signals": signals, "momentum": moms, "closes": closes}


def simulate_period_with_reentry(rebal_date: pd.Timestamp, period_dates: pd.DatetimeIndex, initial_picks: list[str],
                                  pool_info: dict, top_k: int) -> tuple[dict, list]:
    """한 반기 구간을 시뮬레이션: 슬롯별로 활성 종목/청산일/재탐색 종목을 순서대로 기록해
    {ticker: {date: weight}} 형태의 슬롯별 비중 시계열을 만든다."""
    n_slots = top_k
    slot_holdings = []  # 각 슬롯: [(ticker, start_date, end_date_or_None), ...]
    events = []
    held_globally_this_period: set[str] = set()

    for slot_i in range(n_slots):
        if slot_i >= len(initial_picks):
            slot_holdings.append([])
            continue
        ticker = initial_picks[slot_i]
        held_globally_this_period.add(ticker)
        segments = []
        cur_ticker = ticker
        cur_start = rebal_date
        research_count = 0
        while True:
            sig = pool_info["signals"].get(cur_ticker)
            if sig is None:
                # 데이터 없음 -> 그냥 기간 끝까지 보유(예외 상황)
                segments.append((cur_ticker, cur_start, period_dates[-1]))
                break
            sig_in_period = sig.reindex(period_dates).ffill()
            sig_in_period = sig_in_period[sig_in_period.index >= cur_start]
            zero_days = sig_in_period[sig_in_period == 0]
            if len(zero_days) == 0:
                segments.append((cur_ticker, cur_start, period_dates[-1]))
                break
            exit_date = zero_days.index[0]
            segments.append((cur_ticker, cur_start, exit_date - pd.Timedelta(days=1)))
            events.append({"slot": slot_i, "ticker": cur_ticker, "exit_date": str(exit_date.date())})
            research_count += 1
            if research_count > MAX_RESEARCH_PER_SLOT:
                break
            # 재탐색: exit_date 기준 활성신호+미보유 종목 중 모멘텀 최고
            best_t, best_m = None, -1e9
            for t in pool_info["candidates"]:
                if t in held_globally_this_period:
                    continue
                s = pool_info["signals"].get(t)
                m_series = pool_info["momentum"].get(t)
                if s is None or m_series is None or exit_date not in s.index:
                    continue
                if s.loc[exit_date] != 1:
                    continue
                mval = m_series.get(exit_date)
                if pd.isna(mval):
                    continue
                if mval > best_m:
                    best_m, best_t = mval, t
            if best_t is None:
                break  # 대체 후보 없음 -> 그 슬롯은 남은 기간 현금
            held_globally_this_period.discard(cur_ticker)
            held_globally_this_period.add(best_t)
            events.append({"slot": slot_i, "replaced_by": best_t, "entry_date": str(exit_date.date())})
            cur_ticker = best_t
            cur_start = exit_date
        slot_holdings.append(segments)
    return slot_holdings, events


def build_reentry_satellite(start: str, end: str, trading_index: pd.DatetimeIndex, rebal_log: list[dict],
                             exclude: set, top_k: int = SATELLITE_TOP_K) -> dict:
    rebal_dates_sorted = sorted(pd.Timestamp(r["date"]) for r in rebal_log)
    rebal_map = {pd.Timestamp(r["date"]): r["picks"] for r in rebal_log}
    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]

    all_events = []
    all_segments = []  # (ticker, start_date, end_date)
    for period_i, rebal_date in enumerate(rebal_dates_sorted):
        picks = rebal_map[rebal_date]
        if not picks:
            continue
        period_end = rebal_dates_sorted[period_i + 1] - pd.Timedelta(days=1) if period_i + 1 < len(rebal_dates_sorted) else full_idx[-1]
        period_mask = (full_idx >= rebal_date) & (full_idx <= period_end)
        period_dates = full_idx[period_mask]
        if len(period_dates) == 0:
            continue
        t0 = time.time()
        pool_info = fetch_period_pool_and_signals(rebal_date, period_dates[-1], exclude, initial_picks=picks)
        slot_holdings, events = simulate_period_with_reentry(rebal_date, period_dates, picks, pool_info, top_k)
        for seg_list in slot_holdings:
            all_segments.extend(seg_list)
        all_events.extend([{**e, "period_rebal_date": str(rebal_date.date())} for e in events])
        log(f"  [{period_i+1}/{len(rebal_dates_sorted)}] {rebal_date.date()}: 초기={picks}, "
            f"재탐색이벤트={len(events)}, {time.time()-t0:.1f}s")

    all_tickers = sorted({t for t, s, e in all_segments})
    if not all_tickers:
        raise RuntimeError("재진입 새틀라이트에 보유 종목이 없음")

    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=TREND_FETCH_LOOKBACK_DAYS)).date().isoformat()
    histories = get_multiple_price_history(all_tickers, start=fetch_start, end=end, interval="1d")
    closes = _closes_from_histories(histories, all_tickers)
    closes = closes.reindex(full_idx).ffill()

    weights = pd.DataFrame(0.0, index=full_idx, columns=all_tickers)
    for ticker, seg_start, seg_end in all_segments:
        mask = (full_idx >= seg_start) & (full_idx <= seg_end)
        weights.loc[mask, ticker] += 1.0 / top_k

    result = compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)
    metrics = calculate_metrics(result["equity_net"], [], full_idx[0], full_idx[-1])
    return {"metrics": metrics, "ret_net": result["ret_net"], "equity_net": result["equity_net"],
            "events": all_events, "n_reentries": sum(1 for e in all_events if "replaced_by" in e)}


def part_full_and_2022(exclude_champion: set) -> dict:
    log("전체기간/2022: 즉시재탐색 새틀라이트 구축")
    core_ret = pd.read_csv(PRIOR_H10_DIR / "core_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    h16 = json.loads((OUT_DIR / "h16_results.json").read_text(encoding="utf-8"))
    h10 = json.loads((PRIOR_H10_DIR / "h10_results.json").read_text(encoding="utf-8"))
    rebal_log = h10["satellite_trend_following"]["rebal_log"]

    reentry = build_reentry_satellite(FULL_START, FULL_END, core_ret.index, rebal_log, exclude_champion)
    log(f"즉시재탐색 새틀라이트 지표(단독): {reentry['metrics']}, 재진입 {reentry['n_reentries']}회")

    cash_wait_ret = pd.read_csv(OUT_DIR / "full_realtime_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    static_ret = pd.read_csv(OUT_DIR / "full_static_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]

    baseline_blend = blend_returns(core_ret, static_ret, SATELLITE_WEIGHT)
    cash_wait_blend = blend_returns(core_ret, cash_wait_ret, SATELLITE_WEIGHT)
    reentry_blend = blend_returns(core_ret, reentry["ret_net"], SATELLITE_WEIGHT)

    windows = {"full_2019_2026": (FULL_START, FULL_END), "bear_2022": (BEAR2022_START, BEAR2022_END)}
    table = {}
    for wname, (ws, we) in windows.items():
        table[wname] = {
            "static_hold_baseline_H10": perf_metrics_slice(baseline_blend, ws, we),
            "realtime_exit_cash_until_rebal_H16": perf_metrics_slice(cash_wait_blend, ws, we),
            "realtime_exit_immediate_reentry_H17": perf_metrics_slice(reentry_blend, ws, we),
        }
    return {"windows": table, "n_reentries": reentry["n_reentries"], "events": reentry["events"],
            "reentry_ret": reentry["ret_net"]}


def part_gfc_2008(exclude_3asset: set) -> dict:
    log("2008 GFC: 즉시재탐색 새틀라이트 구축")
    h12 = json.loads((PRIOR_H12_DIR / "h12_results.json").read_text(encoding="utf-8"))
    rebal_log = h12["gfc_2008"]["satellite_rebal_log"]

    core = run_three_asset_champion(GFC_FULL_START, GFC_FULL_END)
    trading_index = core["ret_net"].index
    core_ret_gfc = pd.read_csv(PRIOR_H12_DIR / "gfc_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    static_ret_gfc = pd.read_csv(PRIOR_H12_DIR / "gfc_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]

    h16 = json.loads((OUT_DIR / "h16_results.json").read_text(encoding="utf-8"))
    # H16의 GFC 실시간청산 새틀라이트 수익률은 CSV로 저장돼 있지 않으므로 h16 스크립트의 함수를 재사용해 재계산
    sys.path.insert(0, str(OUT_DIR))
    from h16_realtime_trailing_stop_exit import build_realtime_exit_weights
    rt = build_realtime_exit_weights(rebal_log, GFC_FULL_START, GFC_FULL_END, trading_index)
    cash_wait_ret_gfc = rt["ret_net"]

    reentry = build_reentry_satellite(GFC_FULL_START, GFC_FULL_END, trading_index, rebal_log, exclude_3asset)
    log(f"즉시재탐색 새틀라이트 지표(GFC): {reentry['metrics']}, 재진입 {reentry['n_reentries']}회")

    baseline_blend = blend_returns(core_ret_gfc, static_ret_gfc, SATELLITE_WEIGHT)
    cash_wait_blend = blend_returns(core_ret_gfc, cash_wait_ret_gfc, SATELLITE_WEIGHT)
    reentry_blend = blend_returns(core_ret_gfc, reentry["ret_net"], SATELLITE_WEIGHT)

    windows = {"full_2007_2009": (GFC_FULL_START, GFC_FULL_END), "crisis_2007_10_2009_06": (GFC_CRISIS_START, GFC_CRISIS_END)}
    table = {}
    for wname, (ws, we) in windows.items():
        table[wname] = {
            "static_hold_baseline_H10": perf_metrics_slice(baseline_blend, ws, we),
            "realtime_exit_cash_until_rebal_H16": perf_metrics_slice(cash_wait_blend, ws, we),
            "realtime_exit_immediate_reentry_H17": perf_metrics_slice(reentry_blend, ws, we),
        }
    return {"windows": table, "n_reentries": reentry["n_reentries"], "events": reentry["events"]}


def main():
    t0 = time.time()
    from champion_strategy import CHAMPION_UNIVERSE, MARKET_FILTER_TICKER
    exclude_champion = set(CHAMPION_UNIVERSE) | {MARKET_FILTER_TICKER}

    p1 = part_full_and_2022(exclude_champion)
    p2 = part_gfc_2008(set(THREE_ASSET_UNIVERSE))

    result = {
        "meta": {"satellite_weight": SATELLITE_WEIGHT, "max_research_per_slot": MAX_RESEARCH_PER_SLOT},
        "full_and_2022": {k: v for k, v in p1.items() if k != "reentry_ret"},
        "gfc_2008": p2,
    }
    with open(OUT_DIR / "h17_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h17_results.json'} (총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
