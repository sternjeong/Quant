"""사용자 제약: 채권은 거의 안 사고 현금 또는 주식/ETF만 산다. 지금까지 찾은 최선의 기법
(리스크패리티 가중 + 변동성타게팅)은 애초에 "노출을 줄일 때 현금으로 이동"하는 구조라 채권이
전혀 필요 없다 — 이 제약과 이미 잘 맞는다. 다만 55~68개 개별 종목에 리스크패리티로 나눠 담는
건 개인 투자자가 실전에서 관리하기 어렵다. 실제로 살 수 있는 소수의 유동적인 ETF만으로도
같은 효과가 나는지 검증한다.

두 가지 실전 버전을 테스트:
A) SPY 단독 + 변동성타게팅(현금 vs SPY 비중 조절) — 가장 단순, ETF 1개 + 현금만 관리.
B) GICS 섹터 ETF들(9~11개, 시대별로 존재하는 것만) 리스크패리티 가중 + 변동성타게팅 — 매매는
   ETF 9~11종목뿐이라 개인이 충분히 관리 가능한 수준.

두 기간(2015~2026 강세장, 2000~2012 약세장 포함) 모두에서 검증한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from core.position_sizing import portfolio_volatility_target_weights
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
WARMUP_DAYS = 400

SECTOR_ETFS_MODERN = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
SECTOR_ETFS_LEGACY = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU"]  # 2000년대 존재했던 것만


def run_period(label, start, end, sector_etfs, spy_ticker="SPY"):
    print(f"\n{'='*20} {label} ({start}~{end}) {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()

    # A) SPY 단독 + 변동성타게팅
    spy_hist = get_multiple_price_history([spy_ticker], start=fetch_start, end=end, interval="1d")
    spy_df = spy_hist[spy_ticker]
    spy_sliced = spy_df[spy_df.index >= pd.Timestamp(start)]
    spy_ret = spy_sliced["Close"].pct_change().fillna(0.0)

    m_spy_bh, _ = metrics_from_returns(spy_ret)
    print(f"[A] {spy_ticker} 매수보유(오버레이 없음):", m_spy_bh, flush=True)

    spy_results = {}
    for window, tv in [(20, 15.0), (5, 15.0), (5, 20.0)]:
        scale = vol_target_scale(spy_ret, tv, 1.0, window=window)
        scaled = spy_ret * scale.shift(1).fillna(1.0)
        m, _ = metrics_from_returns(scaled)
        spy_results[f"w{window}_tv{tv}"] = m
        print(f"  [A] {spy_ticker}+vol(window={window},target={tv}):", m, flush=True)

    # B) 섹터 ETF 리스크패리티 + 변동성타게팅
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    daily_rets = {}
    for t in sector_etfs:
        df = etf_hist.get(t)
        if df is None or df.empty or len(df) < WARMUP_DAYS:
            print(f"  ({t} 데이터 부족 - 제외)", flush=True)
            continue
        sliced = df[df.index >= pd.Timestamp(start)]
        if sliced.empty:
            continue
        daily_rets[t] = sliced["Close"].pct_change().fillna(0.0)
    etf_df = pd.DataFrame(daily_rets)
    print(f"[B] 사용 가능한 섹터 ETF: {list(etf_df.columns)}", flush=True)

    equal_ret = etf_df.mean(axis=1, skipna=True)
    m_equal, _ = metrics_from_returns(equal_ret)
    print("[B] 섹터 동일가중(오버레이 없음):", m_equal, flush=True)

    rp_w = pd.Series(portfolio_volatility_target_weights(etf_df.dropna(how="all", axis=0)))
    rp_ret = (etf_df[rp_w.index] * rp_w).sum(axis=1)
    m_rp, _ = metrics_from_returns(rp_ret)
    print("[B] 섹터 리스크패리티(오버레이 없음):", m_rp, flush=True)

    etf_results = {}
    for window, tv in [(20, 15.0), (5, 15.0), (5, 20.0)]:
        scale = vol_target_scale(rp_ret, tv, 1.0, window=window)
        scaled = rp_ret * scale.shift(1).fillna(1.0)
        m, _ = metrics_from_returns(scaled)
        etf_results[f"w{window}_tv{tv}"] = m
        print(f"  [B] 섹터리스크패리티+vol(window={window},target={tv}):", m, flush=True)

    bench = run_buy_and_hold("^GSPC", start, end)
    print("S&P500 매수보유:", bench.metrics, flush=True)

    return {
        "spy_bh": m_spy_bh, "spy_vol_target": spy_results,
        "sector_equal": m_equal, "sector_riskparity": m_rp, "sector_vol_target": etf_results,
        "sp500_bh": bench.metrics, "etf_columns": list(etf_df.columns),
    }


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)

    with open(f"{OUT_DIR}/practical_etf_strategy_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
