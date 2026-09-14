"""가설: core.position_sizing.kelly_fraction(켈리 기준)으로 섹터별 비중을 정하면 리스크패리티
(inverse-vol)보다 나은가? 분기마다 트레일링 3년 일별수익률의 "상승일 승률/평균상승/평균하락"으로
켈리 비율을 구해(하프켈리, 이 저장소 함수의 기본 안전계수) 섹터 비중으로 쓴다 — 룩어헤드 없음.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.backtest_engine import run_buy_and_hold
from core.market_data import get_multiple_price_history
from core.position_sizing import kelly_fraction
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns
from multi_regime_multi_strategy import SECTOR_ETFS_MODERN, SECTOR_ETFS_LEGACY, WARMUP_DAYS
from rolling_risk_parity import rolling_risk_parity_weights

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
LOOKBACK_DAYS = 756  # 트레일링 3년


def rolling_kelly_weights(daily_returns: pd.DataFrame, lookback_days: int = LOOKBACK_DAYS, rebal_freq: str = "QS") -> pd.DataFrame:
    idx = daily_returns.index
    rebal_dates = pd.date_range(idx[0], idx[-1], freq=rebal_freq)
    weights_daily = pd.DataFrame(0.0, index=idx, columns=daily_returns.columns)
    current = pd.Series(1.0 / daily_returns.shape[1], index=daily_returns.columns)
    ptr = 0
    for i, dt in enumerate(idx):
        while ptr < len(rebal_dates) and rebal_dates[ptr] <= dt:
            hist = daily_returns.loc[:dt].iloc[-lookback_days:]
            if len(hist) >= 252:
                fracs = {}
                for col in daily_returns.columns:
                    r = hist[col].dropna()
                    wins = r[r > 0]
                    losses = r[r < 0]
                    if len(wins) == 0 or len(losses) == 0:
                        fracs[col] = 0.0
                        continue
                    win_rate = len(wins) / len(r)
                    avg_win = float(wins.mean())
                    avg_loss = float(abs(losses.mean()))
                    kf = kelly_fraction(win_rate, avg_win, avg_loss, safety_fraction=0.5)
                    fracs[col] = kf["recommended_fraction"]
                fracs_s = pd.Series(fracs)
                if fracs_s.sum() > 0:
                    current = fracs_s / fracs_s.sum()
                else:
                    current = pd.Series(1.0 / daily_returns.shape[1], index=daily_returns.columns)
            ptr += 1
        weights_daily.iloc[i] = current.values
    return weights_daily


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*15} {label} {'='*15}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + LOOKBACK_DAYS)).date().isoformat()
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)
    sliced_idx = etf_df.index[(etf_df.index >= pd.Timestamp(start)) & (etf_df.index <= pd.Timestamp(end))]

    kelly_w = rolling_kelly_weights(etf_df)
    rp_w = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")

    def compute_ret(w_full):
        w = w_full.loc[sliced_idx]
        executed = w.shift(1).fillna(1.0 / w.shape[1])
        return (etf_df.loc[sliced_idx] * executed).sum(axis=1)

    kelly_ret = compute_ret(kelly_w)
    rp_ret = compute_ret(rp_w)

    m_kelly_raw, _ = metrics_from_returns(kelly_ret)
    m_rp_raw, _ = metrics_from_returns(rp_ret)
    print("[켈리, 오버레이 없음]:", m_kelly_raw, flush=True)
    print("[리스크패리티, 오버레이 없음]:", m_rp_raw, flush=True)

    scale_k = vol_target_scale(kelly_ret, 18.0, 1.0, window=5)
    m_kelly, _ = metrics_from_returns(kelly_ret * scale_k.shift(1).fillna(1.0))
    scale_r = vol_target_scale(rp_ret, 18.0, 1.0, window=5)
    m_rp, _ = metrics_from_returns(rp_ret * scale_r.shift(1).fillna(1.0))
    print("[켈리+변동성타게팅]:", m_kelly, flush=True)
    print("[리스크패리티+변동성타게팅]:", m_rp, flush=True)

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)
    return {"kelly_raw": m_kelly_raw, "rp_raw": m_rp_raw, "kelly_final": m_kelly, "rp_final": m_rp, "sp500_bh": bench.metrics}


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)
    with open(f"{OUT_DIR}/hypothesis_kelly_sizing.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
