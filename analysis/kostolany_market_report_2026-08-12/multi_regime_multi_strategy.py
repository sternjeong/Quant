"""사용자 가설(매우 구체적): 전 기간에 하나의 전략을 쓰지 말고, N개의 전략을 미리 만들어두고
(약세장용 방어형, 횡보장/광범위강세용 베타형, 쏠림강세장용 알파추구형) 매일 그 시점까지의 데이터로
국면을 인과적으로 판정해 자금을 그 전략들 사이에 동적으로 재배분하자 — 베타는 챙기면서 알파를
쫓는다. 알파추구형은 (a) 쏠림 섹터의 ETF, (b) 그 시점 모멘텀 상위 개별 종목("대장주"), (c) 둘의
혼합을 각각 테스트한다.

설계 원칙(이 리포트가 이미 여러 번 스스로 잡아낸 함정들을 처음부터 피함):
  1. 모든 국면 판정·모멘텀 랭킹은 "그 날짜까지의" 데이터만 사용(룩어헤드 없음), 신호는 다음
     거래일부터 체결(1일 지연).
  2. 국면 판정 임계값은 사후에 스윕해서 고르지 않는다 — 시장추세 임계값(연 ±5%)과 쏠림 임계값
     (횡단면 z-점수 ≥ 1)은 사전에 정한 상식적/통계적 기준.
  3. 종목 유니버스는 생존편향 없는(그 시점 실제 S&P500 구성종목에서 무작위 추출) 표본만 사용.
  4. 리스크패리티 가중은 분기마다 트레일링 1년 데이터로만 재계산(정적 전체구간 계산 금지 —
     이전에 룩어헤드로 확인된 실수).

국면 정의(3개 거시국면 + 강세장 세분화):
  - 약세장: 섹터 평균 트레일링 12개월 수익률 < -5%  -> 전략 A(방어형): 리스크패리티 + 강한
    변동성타게팅(목표 12%)
  - 횡보장: -5% ~ +5% 사이                          -> 전략 B(베타형): 리스크패리티 + 중간
    변동성타게팅(목표 18%)
  - 강세장(> +5%), 세분화:
      - 광범위(쏠림 없음, 최대 z < 1)                -> 전략 B(베타형)과 동일
      - 쏠림(최대 z >= 1)                            -> 전략 C(알파추구형): 베타형 위에 알파
        슬리브(쏠림 섹터 ETF 및/또는 그 시점 모멘텀 상위 개별종목)를 얹음, 3개 변형 비교
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pickle
import numpy as np
import pandas as pd

from core.backtest_engine import run_buy_and_hold, calculate_metrics
from core.market_data import get_multiple_price_history
from rolling_risk_parity import rolling_risk_parity_weights
from portfolio_vol_targeting import vol_target_scale, metrics_from_returns

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"
WARMUP_DAYS = 400
MOMENTUM_WINDOW = 252
Z_THRESHOLD = 1.0            # 쏠림 판정(사후 스윕 아님, 표준 이상치 기준)
BULL_TREND_PCT = 5.0         # 강세장 임계값(연 +5%, 사전 정의)
BEAR_TREND_PCT = -5.0        # 약세장 임계값(연 -5%, 사전 정의)
ALPHA_TILT = 0.5             # 알파 슬리브에 배정하는 비중(전체의 50%)
STOCK_TOP_K = 3              # 알파-주식 슬리브: 모멘텀 상위 K종목 동일비중

SECTOR_ETFS_MODERN = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
SECTOR_ETFS_LEGACY = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU"]


def classify_regimes(sector_returns: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """섹터 ETF 일별수익률로부터 (국면 레이블, 리더 섹터, 시장추세) 시리즈를 만든다.
    전부 트레일링 데이터만 사용(룩어헤드 없음)."""
    trailing_mom = sector_returns.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(
        lambda x: (1 + x).prod() - 1, raw=True
    )
    market_trend = trailing_mom.mean(axis=1) * 100  # %
    cross_mean = trailing_mom.mean(axis=1)
    cross_std = trailing_mom.std(axis=1)
    z_scores = trailing_mom.sub(cross_mean, axis=0).div(cross_std.replace(0, np.nan), axis=0)
    max_z = z_scores.max(axis=1)
    leader = z_scores.idxmax(axis=1)

    regime = pd.Series("데이터부족", index=sector_returns.index)
    regime[market_trend < BEAR_TREND_PCT] = "약세장"
    mid = (market_trend >= BEAR_TREND_PCT) & (market_trend <= BULL_TREND_PCT)
    regime[mid] = "횡보장"
    bull = market_trend > BULL_TREND_PCT
    regime[bull & (max_z < Z_THRESHOLD)] = "광범위강세"
    regime[bull & (max_z >= Z_THRESHOLD)] = "쏠림강세"
    regime[market_trend.isna()] = "데이터부족"

    return regime, leader, market_trend


def stock_momentum_leaders(stock_returns: pd.DataFrame, top_k: int = STOCK_TOP_K) -> pd.DataFrame:
    """매일, 그날까지의 트레일링 12개월 수익률 상위 top_k 종목(절대모멘텀>0 필터)에 동일비중을
    배정한 일별 비중 DataFrame을 반환(룩어헤드 없음)."""
    trailing_mom = stock_returns.rolling(MOMENTUM_WINDOW, min_periods=MOMENTUM_WINDOW).apply(
        lambda x: (1 + x).prod() - 1, raw=True
    )
    weights = pd.DataFrame(0.0, index=stock_returns.index, columns=stock_returns.columns)
    for dt in stock_returns.index:
        row = trailing_mom.loc[dt].dropna()
        candidates = row[row > 0].sort_values(ascending=False)
        picks = candidates.index[:top_k]
        if len(picks) > 0:
            weights.loc[dt, picks] = 1.0 / len(picks)
    return weights


def run_period(label, start, end, sector_etfs, unbiased_pkl):
    print(f"\n{'='*24} {label} ({start}~{end}) {'='*24}", flush=True)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=WARMUP_DAYS + MOMENTUM_WINDOW)).date().isoformat()

    # 1) 섹터 ETF
    etf_hist = get_multiple_price_history(sector_etfs, start=fetch_start, end=end, interval="1d")
    etf_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in etf_hist.items() if df is not None and not df.empty}
    etf_df = pd.DataFrame(etf_rets).dropna(how="all", axis=0)

    # 2) 생존편향 없는 개별종목 유니버스(이미 계산해둔 pkl 재사용)
    with open(unbiased_pkl, "rb") as f:
        meta = pickle.load(f)
    ok_tickers = meta["ok_tickers"]
    stock_hist = get_multiple_price_history(ok_tickers, start=fetch_start, end=end, interval="1d")
    stock_rets = {t: df["Close"].pct_change().fillna(0.0) for t, df in stock_hist.items() if df is not None and not df.empty and len(df) > WARMUP_DAYS}
    stock_df = pd.DataFrame(stock_rets)

    common_idx = etf_df.index
    stock_df = stock_df.reindex(common_idx)

    sliced_idx = common_idx[(common_idx >= pd.Timestamp(start)) & (common_idx <= pd.Timestamp(end))]

    # --- 국면 판정 ---
    regime, leader, market_trend = classify_regimes(etf_df)
    print("국면 분포:", regime.loc[sliced_idx].value_counts().to_dict(), flush=True)

    # --- 기본 베타 슬리브: 롤링 리스크패리티(섹터 ETF) ---
    rp_weights = rolling_risk_parity_weights(etf_df, lookback_days=252, rebal_freq="QS")

    # --- 알파 슬리브 후보 ---
    stock_leader_weights = stock_momentum_leaders(stock_df.fillna(0.0), top_k=STOCK_TOP_K)
    # 트레일링 데이터가 아예 없는(warmup 부족) 종목의 0 수익률이 섞이지 않도록, 실제 데이터 있는 곳만 후보로
    valid_stock_mask = stock_df.notna()

    def etf_alpha_weight_row(dt):
        base = rp_weights.loc[dt].copy()
        if regime.loc[dt] == "쏠림강세":
            lead = leader.loc[dt]
            base[lead] = base[lead] + ALPHA_TILT
            base = base / base.sum()
        return base

    # --- 3개 알파 변형 조합 ---
    all_assets = list(etf_df.columns) + list(stock_df.columns)
    variants = ["baseline", "etf_tilt", "stock_tilt", "combined_tilt"]
    weights_by_variant = {v: pd.DataFrame(0.0, index=common_idx, columns=all_assets) for v in variants}

    for dt in common_idx:
        r = regime.loc[dt]
        base_etf_w = rp_weights.loc[dt]

        # baseline: 국면 무관, 항상 베타형(리스크패리티)만
        weights_by_variant["baseline"].loc[dt, etf_df.columns] = base_etf_w.values

        if r == "쏠림강세":
            lead = leader.loc[dt]
            # etf_tilt: 쏠림 섹터 ETF에 추가 비중
            w = base_etf_w.copy()
            w[lead] = w[lead] + ALPHA_TILT
            w = w / w.sum()
            weights_by_variant["etf_tilt"].loc[dt, etf_df.columns] = w.values

            # stock_tilt: 베타(1-ALPHA_TILT) + 개별종목 모멘텀 리더(ALPHA_TILT)
            w_etf = base_etf_w * (1 - ALPHA_TILT)
            weights_by_variant["stock_tilt"].loc[dt, etf_df.columns] = w_etf.values
            stock_w = stock_leader_weights.loc[dt]
            if stock_w.sum() > 0:
                weights_by_variant["stock_tilt"].loc[dt, stock_df.columns] = (stock_w * ALPHA_TILT).values
            else:
                weights_by_variant["stock_tilt"].loc[dt, etf_df.columns] += (base_etf_w * ALPHA_TILT).values

            # combined_tilt: 베타(1-ALPHA_TILT) + ETF쏠림(ALPHA_TILT/2) + 개별주 모멘텀(ALPHA_TILT/2).
            # 매 분기(day)마다 etf/stock 두 조각을 "처음부터 다시" 계산해 합이 정확히 1이 되도록 한다
            # (이전 버전은 fallback에서 이미 정규화된 벡터에 값을 덧붙여 합이 1을 넘는 버그가 있었다).
            half = ALPHA_TILT / 2
            if stock_w.sum() > 0:
                # 베타(1-ALPHA_TILT, 전체 ETF에 리스크패리티로 분산) + 리더ETF에 half 추가 + 개별주에 half
                # 합계 검증: (1-ALPHA_TILT) + half + half = (1-ALPHA_TILT) + ALPHA_TILT = 1
                w_etf2 = base_etf_w * (1 - ALPHA_TILT)
                w_etf2[lead] = w_etf2[lead] + half
                weights_by_variant["combined_tilt"].loc[dt, etf_df.columns] = w_etf2.values
                weights_by_variant["combined_tilt"].loc[dt, stock_df.columns] = (stock_w * half).values
            else:
                # 그날 모멘텀>0인 개별종목 후보가 없으면 그 몫(half)도 통째로 리더 ETF에 배정
                w_etf2 = base_etf_w * (1 - ALPHA_TILT)
                w_etf2[lead] = w_etf2[lead] + ALPHA_TILT
                weights_by_variant["combined_tilt"].loc[dt, etf_df.columns] = w_etf2.values
        else:
            for v in ["etf_tilt", "stock_tilt", "combined_tilt"]:
                weights_by_variant[v].loc[dt, etf_df.columns] = base_etf_w.values

    full_rets = pd.concat([etf_df, stock_df], axis=1).fillna(0.0)

    for v in variants:
        wsum = weights_by_variant[v].loc[sliced_idx].sum(axis=1)
        max_dev = (wsum - 1.0).abs().max()
        print(f"[검증] {v} 비중 합계 1.0으로부터 최대 이탈: {max_dev:.6f}", flush=True)
        if max_dev > 1e-6:
            raise ValueError(f"{v} 비중 정규화 버그: 최대 이탈 {max_dev}")

    # 국면별 변동성타게팅 목표(약세장=12%, 그 외=18%) — 사전 정의, 스윕 아님
    vol_target_by_regime = regime.map({"약세장": 12.0, "횡보장": 18.0, "광범위강세": 18.0, "쏠림강세": 18.0}).fillna(18.0)

    results = {}
    curves = {}
    for v in variants:
        w = weights_by_variant[v].loc[sliced_idx]
        executed = w.shift(1).fillna(0.0)
        port_ret = (full_rets.loc[sliced_idx] * executed).sum(axis=1)

        # 국면별 다른 목표변동성 -> 국면이 바뀔 때마다 다른 target을 쓰는 변동성타게팅
        realized_vol = port_ret.rolling(5, min_periods=5).std() * np.sqrt(252) * 100
        tv = vol_target_by_regime.loc[sliced_idx]
        scale = (tv / realized_vol).clip(upper=1.0).fillna(1.0)
        scaled_ret = port_ret * scale.shift(1).fillna(1.0)

        m_no_overlay, _ = metrics_from_returns(port_ret)
        m_final, eq_final = metrics_from_returns(scaled_ret)
        results[v] = {"no_overlay": m_no_overlay, "final": m_final}
        curves[v] = eq_final
        print(f"[{v}] 오버레이 없음:", m_no_overlay, flush=True)
        print(f"[{v}] 국면별 변동성타게팅 적용:", m_final, flush=True)

    bench = run_buy_and_hold("^GSPC", sliced_idx[0].date().isoformat(), sliced_idx[-1].date().isoformat())
    print("S&P500:", bench.metrics, flush=True)

    # 국면별 성과 분해(전략이 실제로 각 국면에서 뭘 하고 있는지 확인)
    regime_breakdown = {}
    for r_label in ["약세장", "횡보장", "광범위강세", "쏠림강세"]:
        mask = regime.loc[sliced_idx] == r_label
        if mask.sum() < 20:
            continue
        base_ret_masked = (full_rets.loc[sliced_idx][mask] * weights_by_variant["baseline"].loc[sliced_idx][mask].shift(1).fillna(0.0)).sum(axis=1)
        etf_tilt_ret_masked = (full_rets.loc[sliced_idx][mask] * weights_by_variant["etf_tilt"].loc[sliced_idx][mask].shift(1).fillna(0.0)).sum(axis=1)
        regime_breakdown[r_label] = {
            "days": int(mask.sum()),
            "baseline_mean_daily_pct": round(float(base_ret_masked.mean() * 100), 4),
            "etf_tilt_mean_daily_pct": round(float(etf_tilt_ret_masked.mean() * 100), 4),
        }
    print("국면별 일평균 수익률 분해:", regime_breakdown, flush=True)

    return {
        "regime_distribution": {str(k): int(v) for k, v in regime.loc[sliced_idx].value_counts().items()},
        "results": results, "sp500_bh": bench.metrics, "regime_breakdown": regime_breakdown,
    }, curves


def main():
    out = {}
    all_curves = {}
    out["2015_2026"], all_curves["2015_2026"] = run_period(
        "강세장", "2015-01-01", "2026-08-12", SECTOR_ETFS_MODERN,
        f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl",
    )
    out["2000_2012"], all_curves["2000_2012"] = run_period(
        "약세장포함", "2000-01-03", "2012-12-31", SECTOR_ETFS_LEGACY,
        f"{OUT_DIR}/bear_market_robustness_curves.pkl",
    )

    with open(f"{OUT_DIR}/multi_regime_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(f"{OUT_DIR}/multi_regime_curves.pkl", "wb") as f:
        pickle.dump(all_curves, f)
    print("\nDONE")


if __name__ == "__main__":
    main()
