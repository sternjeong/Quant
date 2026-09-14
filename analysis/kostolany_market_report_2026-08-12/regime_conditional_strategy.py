"""사용자 가설: 시장을 N개 국면으로 나누고(예: "광범위 강세/약세" vs "쏠림장 - 특정 섹터가
이례적으로 앞서감") 국면별로 다른 전략을 쓰면 더 낫지 않은가? (반도체 랠리가 최근의 실제 사례)

핵심 원칙(이 리포트가 이미 여러 번 부딪힌 함정 회피): "반도체가 좋았다"는 사후 관찰이다. 이 국면을
그 시점에 이미 알 수 있었던 정보로 인과적으로(미래 데이터 없이) 판정해야 진짜 검증이다. 임계값도
사후에 스윕해서 고르지 않고(과적합), 횡단면 z-점수라는 원칙적인 통계 기준을 그대로 쓴다.

국면 분류(매 리밸런싱 시점, 트레일링 데이터만 사용):
  - 시장추세: 섹터 평균 트레일링 12개월 수익률 > 0 이면 상승, 아니면 하락
  - 쏠림 여부: 섹터별 트레일링 12개월 수익률의 횡단면 z-점수 중 최댓값이 임계값(1.0, 사전에 정한
    표준적인 "1-시그마 이상 이상치" 기준일 뿐 스윕해서 고른 값이 아님)을 넘으면 "쏠림장"

전략:
  - 상승 + 쏠림장: 그 이상치 섹터에 추가 비중(리스크패리티 기본 비중 + 모멘텀 틸트)
  - 그 외 전부: 08장에서 이미 검증된 리스크패리티 + 변동성타게팅(무레버리지) 그대로
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd
import numpy as np

from core.backtest_engine import run_buy_and_hold, calculate_metrics
from core.market_data import get_multiple_price_history
from core.position_sizing import portfolio_volatility_target_weights
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
WARMUP_DAYS = 400
MOMENTUM_WINDOW = 252
Z_THRESHOLD = 1.0  # 사전에 정한 "1-시그마 이상 이상치" 기준(사후 스윕 아님)
TILT_EXTRA_WEIGHT = 0.5  # 이상치 섹터에 리스크패리티 기본비중 대비 추가로 더하는 비중(전체의 50%p)

SECTOR_ETFS_MODERN = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
SECTOR_ETFS_LEGACY = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU"]


def build_regime_tilted_weights(daily_returns: pd.DataFrame, rp_weights_daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """매 거래일, 트레일링 12개월 수익률의 횡단면 z-점수로 국면을 판정해 리스크패리티 기본비중에
    쏠림장이면 이상치 섹터로 모멘텀 틸트를 더한다. 룩어헤드 없음(그 날짜까지의 데이터만 사용).

    Returns: (틸트 적용된 일별 비중 DataFrame, 국면 레이블 시리즈("상승-쏠림"/"상승-분산"/"하락"))
    """
    trailing_mom = daily_returns.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(
        lambda x: (1 + x).prod() - 1, raw=True
    )
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    market_trend = trailing_mom.mean(axis=1)  # 섹터 평균 = 시장 전체 추세 근사

    tilted = rp_weights_daily.copy()
    regime_labels = pd.Series("데이터부족", index=daily_returns.index)

    for dt in daily_returns.index:
        z_row = z_scores.loc[dt]
        if z_row.isna().all():
            continue
        max_z = z_row.max()
        leader = z_row.idxmax()
        is_bull = market_trend.loc[dt] > 0
        is_narrow = max_z >= Z_THRESHOLD

        if is_bull and is_narrow:
            regime_labels.loc[dt] = "상승-쏠림"
            base = rp_weights_daily.loc[dt].copy()
            base[leader] = base[leader] + TILT_EXTRA_WEIGHT
            base = base / base.sum()
            tilted.loc[dt] = base
        elif is_bull:
            regime_labels.loc[dt] = "상승-분산"
        else:
            regime_labels.loc[dt] = "하락"

    return tilted, regime_labels


def run_period(label, start, end, sector_etfs):
    print(f"\n{'='*20} {label} ({start}~{end}) {'='*20}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")

    daily_rets_full = {}
    for t in sector_etfs:
        df = etf_hist.get(t)
        if df is None or df.empty:
            continue
        daily_rets_full[t] = df["Close"].pct_change().fillna(0.0)
    full_df = pd.DataFrame(daily_rets_full).dropna(how="all", axis=0)
    sliced_df = full_df[full_df.index >= pd.Timestamp(start)]
    if end:
        sliced_df = sliced_df[sliced_df.index <= pd.Timestamp(end)]

    # 기본: 롤링 리스크패리티(08장 검증된 방식)
    rp_weights_full = rolling_risk_parity_weights(full_df, lookback_days=252, rebal_freq="QS")

    # 국면 틸트 오버레이
    tilted_weights, regime_labels = build_regime_tilted_weights(full_df, rp_weights_full)

    def compute_return(weights_full):
        w = weights_full.loc[sliced_df.index]
        executed = w.shift(1).fillna(1.0 / w.shape[1])
        return (sliced_df * executed).sum(axis=1)

    rp_ret = compute_return(rp_weights_full)
    tilt_ret = compute_return(tilted_weights)

    m_rp, _ = metrics_from_returns(rp_ret)
    m_tilt, _ = metrics_from_returns(tilt_ret)
    print("[기본: 롤링 리스크패리티]:", m_rp, flush=True)
    print("[국면틸트: 쏠림장에 모멘텀 추가]:", m_tilt, flush=True)

    regime_counts = regime_labels.loc[sliced_df.index].value_counts()
    print("국면 분포(거래일 수):", regime_counts.to_dict(), flush=True)

    results = {}
    for tag, ret in [("rp", rp_ret), ("tilt", tilt_ret)]:
        for window, tv in [(5, 20.0)]:
            scale = vol_target_scale(ret, tv, 1.0, window=window)
            scaled = ret * scale.shift(1).fillna(1.0)
            m, _ = metrics_from_returns(scaled)
            results[f"{tag}_vt"] = m
            print(f"  [{tag}+vol(window={window},target={tv})]:", m, flush=True)

    bench = run_buy_and_hold("^GSPC", sliced_df.index[0].date().isoformat(), sliced_df.index[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    return {
        "rp_no_overlay": m_rp, "tilt_no_overlay": m_tilt,
        "vol_target": results, "sp500_bh": bench.metrics,
        "regime_distribution": {str(k): int(v) for k, v in regime_counts.items()},
    }


def main():
    out = {}
    out["2015_2026"] = run_period("강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN)
    out["2000_2012"] = run_period("약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY)

    with open(f"{OUT_DIR}/regime_conditional_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
