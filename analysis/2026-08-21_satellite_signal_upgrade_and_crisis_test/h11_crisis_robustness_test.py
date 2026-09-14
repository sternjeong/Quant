"""H11 - 코어-새틀라이트 구조의 위기 구간 아웃오브샘플 검증.

H1/H5/H9/H10이 검증한 코어-새틀라이트 블렌드는 전부 2019-08~2026-08(대체로 강세장 성격) 구간에서만
백테스트됐다. 17자산 코어 "챔피언" 자체는 작업22/23이 이미 2008 금융위기(SPY+TLT+GLD 3자산 근사)와
2022년 약세장(17자산 전체, 위기에도 정상 상장돼 있었으므로)에서 아웃오브샘플 검증을 통과했지만,
새틀라이트(개별주, 코어보다 변동성이 큼)를 얹었을 때도 같은 강건성이 유지되는지는 한 번도 검증되지
않았다 - "위기 때 하필 변동성 큰 개별주 슬리브가 꼬리위험을 더할 수 있다"는 우려를 직접 테스트한다.

두 구간을 검증한다:
  (A) 2022년 약세장 - 17자산 챔피언은 이미 이 구간에 상장돼 있어 H10이 만든 2019-08~2026-08 전체
      구간 코어/새틀라이트 일간수익률(core_ret_net.csv 등)을 그대로 재사용해 2022-01-01~2022-12-31만
      잘라낸다(재실행 불필요, 동일 정책).
  (B) 2007-2009 금융위기 - 섹터ETF가 2018년 상장이라 17자산 챔피언 자체를 쓸 수 없으므로, 작업22
      H20/작업28 H2가 쓴 SPY+TLT+GLD 3자산·top2 근사 챔피언을 그대로 재구현해 코어로 쓰고, 그 위에
      2007~2009 구간의 point-in-time 새틀라이트(H10에서 채택된 선정방식)를 반기 리밸런싱으로 얹는다.
      위기 구간 자체는 작업22와 동일하게 2007-10~2009-06으로 분리해서 본다.

새틀라이트 선정 방식은 H10 결과(h10_results.json의 placebo_retest_vs_h9_null)를 이 스크립트 실행
시점에 직접 로드해 자동으로 정한다 - 두 방식 중 H9 널분포 대비 백분위가 더 높은 쪽을 "현재 최선"으로
채택한다(둘 다 근사적으로 동률이면 모멘텀 쪽을 기본값으로 - 계산량이 적고 이미 3라운드 검증됨).

core/ 참고: H1/H5/H9/H10과 동일하게 main 체크아웃의 core/를 sys.path 최상단에 꽂아 참조한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))

import numpy as np
import pandas as pd

from champion_strategy import compute_portfolio_returns, _closes_from_histories
from h1_core_satellite import semiannual_rebal_dates, blend_returns
from core.backtest_engine import calculate_metrics, _first_trading_day_of_month_mask
from core.market_data import get_multiple_price_history
from core.strategy_tuning import sample_universe

OUT_DIR = Path(__file__).resolve().parent
H10_RESULTS = OUT_DIR / "h10_results.json"

SATELLITE_POOL_N = 40
SATELLITE_TOP_K = 3
SATELLITE_MOMENTUM_WINDOW = 252
SATELLITE_WARMUP_DAYS = 400
SATELLITE_COST_BPS_PER_SIDE = 5.0
DONCHIAN_ENTRY_WINDOW = 20
DONCHIAN_STOP_PCT = 0.15
TREND_FETCH_LOOKBACK_DAYS = 730

THREE_ASSET_UNIVERSE = ["SPY", "TLT", "GLD"]
THREE_ASSET_TOP_N = 2
THREE_ASSET_MOMENTUM_WINDOW = 252

GFC_FULL_START, GFC_FULL_END = "2007-01-01", "2009-12-31"
GFC_CRISIS_START, GFC_CRISIS_END = "2007-10-01", "2009-06-30"
BEAR2022_START, BEAR2022_END = "2022-01-01", "2022-12-31"


def log(msg):
    print(f"[h11] {msg}", flush=True)


def donchian_trailing_stop_positions(close: pd.Series, entry_window: int, stop_pct: float) -> pd.Series:
    rolling_max = close.shift(1).rolling(entry_window, min_periods=entry_window).max()
    breakout = close > rolling_max
    position = pd.Series(0, index=close.index, dtype=int)
    in_pos = False
    peak = None
    for i in range(len(close)):
        c = close.iloc[i]
        if in_pos:
            peak = max(peak, c)
            if c <= peak * (1 - stop_pct):
                in_pos = False
                peak = None
        else:
            if breakout.iloc[i]:
                in_pos = True
                peak = c
        position.iloc[i] = 1 if in_pos else 0
    return position


def perf_metrics_slice(ret: pd.Series, start: str, end: str) -> dict:
    sliced = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if len(sliced) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "calmar": None, "cumulative_return": None, "n_days": len(sliced)}
    eq = (1 + sliced.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
    m["n_days"] = int(len(sliced))
    return m


# ---------------------------------------------------------------------------
# (A) 2022 약세장 - H10이 저장한 전체기간 일간수익률 CSV를 그대로 재사용
# ---------------------------------------------------------------------------
def part_a_2022_bear(satellite_weight: float, chosen_method: str) -> dict:
    log(f"(A) 2022 약세장 - H10 저장 CSV 재사용 (chosen_method={chosen_method})")
    core_ret = pd.read_csv(OUT_DIR / "core_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_file = "sat_trend_ret_net.csv" if chosen_method == "trend_following" else "sat_momentum_ret_net.csv"
    sat_ret = pd.read_csv(OUT_DIR / sat_file, index_col=0, parse_dates=True).iloc[:, 0]
    blended = blend_returns(core_ret, sat_ret, satellite_weight)

    full_core = perf_metrics_slice(core_ret, "2019-08-12", "2026-08-19")
    full_blend = perf_metrics_slice(blended, "2019-08-12", "2026-08-19")
    crisis_core = perf_metrics_slice(core_ret, BEAR2022_START, BEAR2022_END)
    crisis_blend = perf_metrics_slice(blended, BEAR2022_START, BEAR2022_END)
    crisis_sat_alone = perf_metrics_slice(sat_ret, BEAR2022_START, BEAR2022_END)

    return {
        "satellite_weight": satellite_weight, "chosen_method": chosen_method,
        "full_period_2019_2026": {"core_alone": full_core, "core_plus_satellite": full_blend},
        "crisis_2022_full_year": {
            "core_alone": crisis_core, "core_plus_satellite": crisis_blend, "satellite_alone": crisis_sat_alone,
        },
    }


# ---------------------------------------------------------------------------
# (B) 2007-2009 금융위기 - 3자산(SPY/TLT/GLD) 근사 코어 + point-in-time 새틀라이트
# ---------------------------------------------------------------------------
def three_asset_champion_weights(closes: pd.DataFrame) -> pd.DataFrame:
    momentum = closes.pct_change(THREE_ASSET_MOMENTUM_WINDOW)
    is_rebal = _first_trading_day_of_month_mask(closes.index)
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_w = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            cand = mom[mom > 0].sort_values(ascending=False)
            picks = cand.index[:THREE_ASSET_TOP_N]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / THREE_ASSET_TOP_N
            last_w = w
        weights.iloc[i] = last_w.values
    return weights


def run_three_asset_champion(start: str, end: str) -> dict:
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=400)).date().isoformat()
    histories = get_multiple_price_history(THREE_ASSET_UNIVERSE, start=fetch_start, end=end, interval="1d")
    closes = pd.DataFrame({t: histories[t]["Close"] for t in THREE_ASSET_UNIVERSE if t in histories}).ffill()

    weights_full = three_asset_champion_weights(closes)
    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    closes_s = closes.loc[sliced_idx]
    weights_s = weights_full.loc[sliced_idx]

    result = compute_portfolio_returns(closes_s, weights_s, cost_bps_per_side=5.0)
    metrics = calculate_metrics(result["equity_net"], [], sliced_idx[0], sliced_idx[-1])
    return {"start": str(sliced_idx[0].date()), "end": str(sliced_idx[-1].date()), "metrics": metrics,
            "ret_net": result["ret_net"], "equity_net": result["equity_net"]}


def pick_satellite_momentum(rebal_date: pd.Timestamp, exclude: set, top_k: int = SATELLITE_TOP_K) -> dict:
    as_of_str = rebal_date.date().isoformat()
    pool = sample_universe(n=SATELLITE_POOL_N, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
    candidates = [t for t in pool["ticker"].tolist() if t not in exclude]
    fetch_start = (rebal_date - pd.DateOffset(days=SATELLITE_WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(candidates, start=fetch_start, end=as_of_str, interval="1d")
    scores = {}
    for t in candidates:
        df = histories.get(t)
        if df is None or df.empty:
            continue
        close = df["Close"]
        close = close[close.index < rebal_date]
        if len(close) < SATELLITE_MOMENTUM_WINDOW + 5:
            continue
        mom = close.iloc[-1] / close.iloc[-1 - SATELLITE_MOMENTUM_WINDOW] - 1.0
        if pd.notna(mom):
            scores[t] = float(mom)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    positive = [(t, m) for t, m in ranked if m > 0]
    picks = [t for t, m in positive[:top_k]]
    return {"date": as_of_str, "pool_size": len(candidates), "n_eligible": len(positive), "picks": picks}


def pick_satellite_trend_following(rebal_date: pd.Timestamp, exclude: set, top_k: int = SATELLITE_TOP_K) -> dict:
    as_of_str = rebal_date.date().isoformat()
    pool = sample_universe(n=SATELLITE_POOL_N, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
    candidates = [t for t in pool["ticker"].tolist() if t not in exclude]
    fetch_start = (rebal_date - pd.DateOffset(days=TREND_FETCH_LOOKBACK_DAYS)).date().isoformat()
    histories = get_multiple_price_history(candidates, start=fetch_start, end=as_of_str, interval="1d")
    active_scores = {}
    for t in candidates:
        df = histories.get(t)
        if df is None or df.empty:
            continue
        close = df["Close"]
        close = close[close.index < rebal_date]
        if len(close) < DONCHIAN_ENTRY_WINDOW + 60:
            continue
        pos = donchian_trailing_stop_positions(close, DONCHIAN_ENTRY_WINDOW, DONCHIAN_STOP_PCT)
        if pos.iloc[-1] != 1:
            continue
        if len(close) >= SATELLITE_MOMENTUM_WINDOW + 5:
            mom = close.iloc[-1] / close.iloc[-1 - SATELLITE_MOMENTUM_WINDOW] - 1.0
        else:
            mom = close.iloc[-1] / close.iloc[0] - 1.0
        if pd.notna(mom):
            active_scores[t] = float(mom)
    ranked = sorted(active_scores.items(), key=lambda kv: kv[1], reverse=True)
    picks = [t for t, m in ranked[:top_k]]
    return {"date": as_of_str, "pool_size": len(candidates), "n_eligible": len(active_scores), "picks": picks}


def build_satellite_returns_period(start: str, end: str, trading_index: pd.DatetimeIndex, exclude: set, method: str) -> dict:
    rebal_dates = semiannual_rebal_dates(trading_index, start, end)
    log(f"  반기 리밸런싱 {len(rebal_dates)}회({method}): {[str(d.date()) for d in rebal_dates]}")
    picker = pick_satellite_trend_following if method == "trend_following" else pick_satellite_momentum

    all_picks_log = []
    per_period_picks = []
    all_tickers: set[str] = set()
    for i, d in enumerate(rebal_dates):
        t0 = time.time()
        info = picker(d, exclude)
        log(f"    [{i+1}/{len(rebal_dates)}] {info['date']}: picks={info['picks']} (pool={info['pool_size']}, 후보={info['n_eligible']}, {time.time()-t0:.1f}s)")
        all_picks_log.append(info)
        per_period_picks.append((d, info["picks"]))
        all_tickers.update(info["picks"])

    if not all_tickers:
        log("  경고: 이 구간에서 새틀라이트 후보가 한 번도 뽑히지 않음 - 새틀라이트 수익률 0으로 처리")
        empty_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
        ret0 = pd.Series(0.0, index=empty_idx)
        eq0 = pd.Series(100.0, index=empty_idx)
        return {"rebal_log": all_picks_log, "tickers_ever_held": [], "metrics": calculate_metrics(eq0, [], empty_idx[0], empty_idx[-1]),
                "ret_net": ret0, "equity_net": eq0}

    all_tickers = sorted(all_tickers)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=SATELLITE_WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(all_tickers, start=fetch_start, end=end, interval="1d")
    closes = _closes_from_histories(histories, all_tickers)
    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    closes = closes.reindex(full_idx).ffill()

    weights = pd.DataFrame(0.0, index=full_idx, columns=closes.columns)
    last_w = pd.Series(0.0, index=closes.columns)
    rebal_set = {d: picks for d, picks in per_period_picks}
    for dt in full_idx:
        if dt in rebal_set:
            picks = rebal_set[dt]
            w = pd.Series(0.0, index=closes.columns)
            if picks:
                w[picks] = 1.0 / SATELLITE_TOP_K
            last_w = w
        weights.loc[dt] = last_w.values

    result = compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)
    metrics = calculate_metrics(result["equity_net"], [], full_idx[0], full_idx[-1])
    return {"rebal_log": all_picks_log, "tickers_ever_held": all_tickers, "metrics": metrics,
            "ret_net": result["ret_net"], "equity_net": result["equity_net"]}


def part_b_2008_gfc(satellite_weight: float, chosen_method: str) -> dict:
    log(f"(B) 2008 금융위기 - SPY+TLT+GLD 3자산 근사 코어 + point-in-time 새틀라이트({chosen_method})")
    core = run_three_asset_champion(GFC_FULL_START, GFC_FULL_END)
    trading_index = core["ret_net"].index
    log(f"  3자산 코어 지표(전체 {GFC_FULL_START}~{GFC_FULL_END}): {core['metrics']}")

    sat = build_satellite_returns_period(GFC_FULL_START, GFC_FULL_END, trading_index,
                                          exclude=set(THREE_ASSET_UNIVERSE), method=chosen_method)
    log(f"  새틀라이트 지표(전체구간): {sat['metrics']}")

    blended = blend_returns(core["ret_net"], sat["ret_net"], satellite_weight)

    full_core = perf_metrics_slice(core["ret_net"], GFC_FULL_START, GFC_FULL_END)
    full_blend = perf_metrics_slice(blended, GFC_FULL_START, GFC_FULL_END)
    crisis_core = perf_metrics_slice(core["ret_net"], GFC_CRISIS_START, GFC_CRISIS_END)
    crisis_blend = perf_metrics_slice(blended, GFC_CRISIS_START, GFC_CRISIS_END)
    crisis_sat_alone = perf_metrics_slice(sat["ret_net"], GFC_CRISIS_START, GFC_CRISIS_END)

    return {
        "satellite_weight": satellite_weight, "chosen_method": chosen_method,
        "satellite_rebal_log": sat["rebal_log"], "satellite_tickers_ever_held": sat["tickers_ever_held"],
        "full_period_2007_2009": {"core_alone": full_core, "core_plus_satellite": full_blend},
        "crisis_2007_10_2009_06": {
            "core_alone": crisis_core, "core_plus_satellite": crisis_blend, "satellite_alone": crisis_sat_alone,
        },
    }


def main():
    t0 = time.time()
    # H10 결과에서 "현재 최선" 새틀라이트 선정방식을 자동으로 읽어온다
    chosen_method = "momentum"
    chosen_weight = 0.15
    h10_summary = None
    if H10_RESULTS.exists():
        h10 = json.loads(H10_RESULTS.read_text(encoding="utf-8"))
        pc = h10["placebo_retest_vs_h9_null"]
        h10_summary = pc
        if pc["trend_following_percentile"] > pc["momentum_percentile_recomputed"]:
            chosen_method = "trend_following"
        log(f"H10 결과 로드: 모멘텀={pc['momentum_percentile_recomputed']}%ile, "
            f"추세추종={pc['trend_following_percentile']}%ile -> 채택: {chosen_method}")
    else:
        log("h10_results.json 없음 - 기본값(모멘텀) 사용")

    a = part_a_2022_bear(chosen_weight, chosen_method)
    b = part_b_2008_gfc(chosen_weight, chosen_method)

    result = {
        "meta": {
            "chosen_method": chosen_method, "chosen_satellite_weight": chosen_weight,
            "h10_reference": h10_summary,
        },
        "part_a_2022_bear_market": a,
        "part_b_2008_gfc": b,
    }
    with open(OUT_DIR / "h11_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h11_results.json'} (총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
