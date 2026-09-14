"""새 가설: E4(튜닝+추세게이트+비중조절 50%) 위에 두 종류의 오버레이를 더 얹으면 샤프비율이
더 오르는가?

H1. 변동성 타게팅(vol targeting): 종목별 20일 realized vol을 목표 vol로 나눈 비율만큼 포지션
    크기를 조절(고변동성 구간엔 비중을 줄이고 저변동성 구간엔 늘림, cap으로 상한). 퀀트 업계에서
    가장 잘 알려진 "샤프비율을 높이는" 기법 — 변동성 군집(vol clustering) 때문에 위험을 동일하게
    유지하면 급락 국면의 손실 크기를 구조적으로 줄일 수 있다.
H2. 시장 레짐 오버레이: core.market_regime의 4개 서브스코어 중 breadth(전체 유니버스 필요, 비용
    큼)를 뺀 3개(200일선 위치/골든·데드크로스/52주 낙폭)만으로 S&P500 자체의 "룰 기반 시장 국면
    점수"를 롤링(룩어헤드 없이) 재계산해, 시장 전체가 약세일 때 모든 종목의 포지션을 동시에
    축소한다(레짐 스코어가 낮을수록 더 많이 축소, 선형 매핑).

두 오버레이 모두 기존 포지션(0~1 스칼라)에 곱하는 스케일 팩터일 뿐이라, E4의 매매 로직 자체는
전혀 바꾸지 않고 "포지션 크기"만 조절한다 — core.backtest_engine.compute_equity_curve가 0~1
사이 비중을 그대로 지원하므로 별도 구현 없이 그대로 재사용 가능.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, compute_equity_curve, run_buy_and_hold
from core.indicators import sma
from core.market_data import get_multiple_price_history, get_price_history
from hyperparam_grid_search import classify_cycle_phase_series_param
from trend_gate_search import STYLE, START, END, WARMUP_DAYS, TUNED, build_position_trend_gated

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
BEST_UP, BEST_DOWN = 15.0, -25.0
FINAL_SELL_WEIGHT = 0.5
TRADING_DAYS = 252

BEAR_MARKET_DRAWDOWN_PCT = -20.0


def e4_position(df: pd.DataFrame) -> pd.Series:
    """E4(권장 최종안) 원본 포지션(0~1) — 이후 오버레이들이 여기에 스케일을 곱한다."""
    phase_full = classify_cycle_phase_series_param(df["Close"], df["Volume"], **TUNED)
    return build_position_trend_gated(phase_full, df["Close"], STYLE, BEST_UP, BEST_DOWN, FINAL_SELL_WEIGHT)


def vol_target_scale(close: pd.Series, target_vol_annual: float, cap: float, window: int = 20) -> pd.Series:
    """realized vol(20일, 연율화) 대비 목표 vol 비율 -> 포지션 배율(0~cap)."""
    daily_ret = close.pct_change()
    realized_vol = daily_ret.rolling(window, min_periods=window).std() * np.sqrt(TRADING_DAYS)
    scale = (target_vol_annual / 100.0) / realized_vol
    return scale.clip(lower=0.0, upper=cap).fillna(0.0)


def market_regime_scale_series(spx_close: pd.Series, bear_scale: float = 0.3) -> pd.Series:
    """core.market_regime의 3개 서브스코어(breadth 제외, 비용 문제로)를 롤링 재계산한 시장 레짐
    점수(-75~+25)를 [-35,+35] 구간에서 [bear_scale,1.0]으로 선형 매핑한 시장 전체 스케일 팩터.
    breadth를 빼서 만점(+75 대신 +25)이 달라지므로 원래 classify_regime의 문턱(±35)을 그대로 쓰되
    "이 축소판 점수 기준"이라는 점에 유의(원래도 강세/약세 판정 핵심은 이 3개 신호가 담당).
    """
    s = spx_close.dropna()
    sma50 = sma(s, 50)
    sma200 = sma(s, 200)
    trend_score = pd.Series(np.where(s > sma200, 25.0, -25.0), index=s.index)
    cross_score = pd.Series(np.where(sma50 > sma200, 25.0, -25.0), index=s.index)
    roll_max = s.rolling(252, min_periods=1).max()
    drawdown_pct = (s / roll_max - 1) * 100
    dd_score = (drawdown_pct / abs(BEAR_MARKET_DRAWDOWN_PCT) * 25).clip(-25.0, 0.0)

    total = trend_score + cross_score + dd_score
    total[sma200.isna()] = np.nan  # 200일선 계산 안 되는 초반 warmup은 무효

    lo, hi = -35.0, 35.0
    frac = ((total - lo) / (hi - lo)).clip(0.0, 1.0)
    scale = bear_scale + frac * (1.0 - bear_scale)
    return scale.fillna(1.0)


def run_metrics(sliced: pd.DataFrame, position: pd.Series) -> dict:
    from core.strategy_engine import extract_trades
    equity_curve = compute_equity_curve(sliced, position)
    trades = extract_trades(sliced, position)
    return calculate_metrics(equity_curve, trades, sliced.index[0], sliced.index[-1])


def main():
    baseline_df = pd.read_csv(f"{OUT_DIR}/summary_장기.csv").set_index("theme")
    sector_tickers = [t for t in baseline_df.index if t != "S&P500"]
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(sector_tickers, start=fetch_start, end=END, interval="1d")
    histories["S&P500"] = get_price_history("^GSPC", start=fetch_start, end=END, interval="1d")

    spx_full = histories["S&P500"]["Close"]
    regime_scale_full = market_regime_scale_series(spx_full, bear_scale=0.3)
    print("regime scale stats (전체 구간):", regime_scale_full.describe(), flush=True)

    def eval_positions(label, position_builder):
        rows = []
        for ticker, df in histories.items():
            pos_full = position_builder(df)
            sliced = df[df.index >= pd.Timestamp(START)]
            pos = pos_full.reindex(sliced.index).fillna(0.0)
            m = run_metrics(sliced, pos)
            base = baseline_df.loc[ticker]
            rows.append({
                "ticker": ticker, "sector": base["sector"], "cagr": m["cagr"], "mdd": m["mdd"], "sharpe": m["sharpe"],
                "excess_vs_bench": m["cagr"] - base["bench_cagr"],
                "beats_bh": m["cumulative_return"] > base["bh_cumulative_return"],
                "beats_bench": m["cumulative_return"] > base["bench_cumulative_return"],
            })
        pt = pd.DataFrame(rows)
        sector_only = pt[pt["ticker"] != "S&P500"]
        idx_row = pt[pt["ticker"] == "S&P500"].iloc[0]
        summary = {
            "label": label,
            "mean_sharpe": round(sector_only["sharpe"].mean(), 3),
            "median_sharpe": round(sector_only["sharpe"].median(), 3),
            "mean_cagr": round(sector_only["cagr"].mean(), 2),
            "mean_excess_vs_bench": round(sector_only["excess_vs_bench"].mean(), 2),
            "win_rate_vs_bench_pct": round(100 * sector_only["beats_bench"].mean(), 1),
            "index_cagr": idx_row["cagr"], "index_sharpe": idx_row["sharpe"], "index_mdd": idx_row["mdd"],
        }
        print(label, summary, flush=True)
        return summary, pt

    results = {}

    # baseline E4 (오버레이 없음) - 이미 알고 있지만 같은 파이프라인으로 재확인
    results["E4_base"], _ = eval_positions("E4 (오버레이 없음)", lambda df: e4_position(df))

    # H1: 변동성 타게팅 스윕
    for target_vol in [12.0, 18.0, 25.0]:
        for cap in [1.0, 1.3]:
            def builder(df, target_vol=target_vol, cap=cap):
                pos = e4_position(df)
                scale = vol_target_scale(df["Close"], target_vol, cap)
                return (pos * scale.reindex(pos.index).fillna(0.0)).clip(upper=cap)
            key = f"H1_vt{target_vol}_cap{cap}"
            results[key], _ = eval_positions(key, builder)

    # H2: 시장 레짐 오버레이 (여러 bear_scale)
    for bear_scale in [0.0, 0.3, 0.5]:
        rscale = market_regime_scale_series(spx_full, bear_scale=bear_scale)
        def builder(df, rscale=rscale):
            pos = e4_position(df)
            return pos * rscale.reindex(pos.index).fillna(1.0)
        key = f"H2_bearscale{bear_scale}"
        results[key], _ = eval_positions(key, builder)

    # H3: 최선의 H1 + 최선의 H2 결합 (아래서 최선 조합 찾은 뒤 별도 실행 — 우선 대표 조합 하나 테스트)
    best_vt, best_cap = 18.0, 1.3
    best_bear = 0.3
    rscale2 = market_regime_scale_series(spx_full, bear_scale=best_bear)
    def combo_builder(df):
        pos = e4_position(df)
        vscale = vol_target_scale(df["Close"], best_vt, best_cap)
        rs = rscale2.reindex(pos.index).fillna(1.0)
        return (pos * vscale.reindex(pos.index).fillna(0.0) * rs).clip(upper=best_cap)
    results["H3_combo"], h3_pt = eval_positions("H3 (vol target + regime)", combo_builder)
    h3_pt.to_csv(f"{OUT_DIR}/h3_combo_per_ticker.csv", index=False, encoding="utf-8-sig")

    import json
    summary_only = {k: v for k, v in results.items()}
    with open(f"{OUT_DIR}/vol_regime_overlay_results.json", "w", encoding="utf-8") as f:
        json.dump(summary_only, f, ensure_ascii=False, indent=2)

    print("\n=== 전체 요약 (mean_sharpe 내림차순) ===")
    df_summary = pd.DataFrame(list(results.values()))
    print(df_summary.sort_values("mean_sharpe", ascending=False).to_string())
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
