"""H6 — 경성 필터를 연성 블렌드로: 퀄리티 Z-점수 + 모멘텀 Z-점수 가중결합이 H4의 경성 필터(PEG<=1.5,
성장률>=15%, ROE프록시>=15%를 모두 통과해야만 후보)를 대체할 수 있는가.

작업30 H4의 발견: 경성 필터를 걸면 후보 폭이 100종목 -> 26종목(순수 필터)/8종목(+시총 상한)으로
붕괴해 8종목 버전은 31%의 달에 top4를 못 채워 현금화됐다. 이 스크립트는 같은 표본·같은 기간·같은
품질 지표(PEG/성장률/ROE프록시)를 쓰되, "통과/탈락"이 아니라 "표준화 점수로 얼마나 밀어주는가"로
바꾼다 — 후보를 아무도 하드 탈락시키지 않는다(절대모멘텀>0 게이트는 H4/순수모멘텀과 동일하게
유지 — 이건 퀄리티 필터가 아니라 로테이션 전략 자체의 리스크 관리 규칙이므로 그대로 둬야 "퀄리티
처리방식"만 바뀐 효과를 격리할 수 있다).

이 저장소의 문서화된 앙상블 방법론(docs/reports/study_notes_fin_engineering.html "F. 앙상블과
신호결합", core/strategy_engine.py의 compute_ensemble_score() 공식 "Σ(wi*스코어i)/Σwi")을 그대로
차용한다 — 다만 strategy_engine의 앙상블은 "한 종목의 여러 시계열 지표"를 표준화해 합치는
용도(z-점수 롤링윈도우 + tanh 압착)라 "여러 종목을 한 시점에서 횡단면으로 랭킹"하는 이 용도에는
그대로 재사용할 함수가 없다(작업 지시사항에 따라 그런 코드가 없으면 공식만 재구현) — 그래서
가중평균 공식(Σwi*scorei/Σwi)만 그대로 가져오고, 표준화는 tanh 압착 없이 순수 횡단면 z-점수만
쓴다(랭킹 목적이라 -1~1로 눌러 순서를 왜곡할 필요가 없음).

한계(H4와 동일하게 명시): 품질 지표(PEG/성장률/ROE프록시)는 "오늘 시점" 스냅샷 하나만 쓴다 —
이 저장소에 과거 시점 펀더멘털 point-in-time 인프라가 없어(시가총액만 point-in-time 지원) 품질
점수는 전체 백테스트 기간에 고정값으로 적용된다(생존자 성격의 전향편향, H4와 동일한 한계). 이
스크립트가 새로 검증하는 것은 "품질 정보를 하드필터 대신 연성 블렌드로 쓰면 폭 붕괴를 피하면서도
퀄리티의 이득을 일부라도 얻는가"이지, 품질 데이터 자체의 point-in-time 정확성이 아니다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"  # 항상 최신 core/를 참조(이 워크트리의 core/는 구버전, H5 참고)
sys.path.insert(0, MAIN_CHECKOUT)

OUT_DIR = Path(__file__).resolve().parent

import numpy as np
import pandas as pd

from core.strategy_tuning import sample_universe
from core.valuation import fetch_valuation_inputs, peg_ratio
from core.market_data import get_multiple_price_history
from core.backtest_engine import calculate_metrics, run_buy_and_hold, _first_trading_day_of_month_mask

START, END = "2019-08-12", "2026-08-12"  # H4와 동일 기간(직접 비교 가능하도록)
WARMUP_DAYS = 400
MOMENTUM_WINDOW = 252
TOP_N = 4
ROUND_TRIP_COST = 0.001
SAMPLE_N = 100
RANDOM_SEED = 42  # H4와 동일 표본이 나오도록 동일 시드

PEG_MAX = 1.5
GROWTH_MIN_PCT = 15.0
ROE_MIN_PCT = 15.0

BLEND_WEIGHTS = [
    {"label": "equal_50_50", "quality_w": 0.5, "momentum_w": 0.5},
    {"label": "momentum_tilted_30_70", "quality_w": 0.3, "momentum_w": 0.7},
]


def log(msg):
    print(f"[h6] {msg}", flush=True)


def determine_quality_metrics(tickers: list[str]) -> pd.DataFrame:
    """H4와 동일한 3개 지표(PEG/성장률/ROE프록시)를 조회하되, 통과여부가 아니라 원값 자체를 반환."""
    rows = []
    for t in tickers:
        try:
            vinputs = fetch_valuation_inputs(t)
        except Exception as e:
            log(f"   {t}: valuation 조회 실패 ({e})")
            rows.append({"ticker": t, "peg": None, "earnings_growth_pct": None, "roe_proxy_pct": None})
            continue
        per = vinputs.get("trailingPE")
        eps = vinputs.get("trailingEps")
        bvps = vinputs.get("bookValue")
        earnings_growth = vinputs.get("earningsGrowth")
        earnings_growth_pct = earnings_growth * 100 if earnings_growth is not None else None
        peg = peg_ratio(per, earnings_growth_pct)
        roe_proxy_pct = (eps / bvps * 100) if (eps and bvps and bvps > 0) else None
        rows.append({
            "ticker": t, "peg": peg, "earnings_growth_pct": earnings_growth_pct, "roe_proxy_pct": roe_proxy_pct,
            "quality_pass_hard_filter": bool(
                peg is not None and 0 < peg <= PEG_MAX
                and earnings_growth_pct is not None and earnings_growth_pct >= GROWTH_MIN_PCT
                and roe_proxy_pct is not None and roe_proxy_pct >= ROE_MIN_PCT
            ),
        })
    return pd.DataFrame(rows)


def zscore(s: pd.Series) -> pd.Series:
    valid = s.dropna()
    if len(valid) < 2 or valid.std(ddof=0) == 0:
        return pd.Series(0.0, index=s.index)
    z = (s - valid.mean()) / valid.std(ddof=0)
    return z.fillna(0.0)  # 결측치는 "정보 없음 -> 중립(0)" 처리, 하드 탈락시키지 않음(H6 핵심 설계)


def build_quality_zscore(qdf: pd.DataFrame) -> pd.Series:
    """PEG(낮을수록 좋음 -> 부호 반전)/성장률/ROE프록시 3개를 각각 횡단면 z-점수화한 뒤 단순평균.
    앙상블 공식 Σ(wi*scorei)/Σwi 을 균등가중(wi=1/3)으로 적용한 것과 동일."""
    peg_z = zscore(-qdf.set_index("ticker")["peg"])  # PEG는 낮을수록 좋으므로 부호 반전
    growth_z = zscore(qdf.set_index("ticker")["earnings_growth_pct"])
    roe_z = zscore(qdf.set_index("ticker")["roe_proxy_pct"])
    quality_z = (peg_z + growth_z + roe_z) / 3.0
    return quality_z


def build_blended_weights(closes: pd.DataFrame, spy_close: pd.Series, quality_z: pd.Series,
                           quality_w: float, momentum_w: float) -> tuple[pd.DataFrame, list]:
    """매월 첫 거래일: 절대모멘텀>0인 종목(H4/순수모멘텀과 동일 게이트) 중에서 모멘텀 횡단면 z-점수와
    퀄리티 z-점수를 가중결합한 점수로 top_n을 뽑는다(경성 퀄리티 필터 없음). 이진 시장필터(SPY<200일선
    -> 50% 축소)도 H4와 동일하게 유지."""
    momentum = closes.pct_change(MOMENTUM_WINDOW)
    sma200 = spy_close.rolling(200, min_periods=200).mean()
    below_200 = (spy_close < sma200)
    is_rebal = _first_trading_day_of_month_mask(closes.index)

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    monthly_log = []
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            eligible = mom[mom > 0]  # 절대모멘텀 게이트(퀄리티와 무관, H4/순수모멘텀과 동일)
            w = pd.Series(0.0, index=closes.columns)
            picks = []
            if len(eligible) > 0:
                mom_z = zscore(eligible.reindex(eligible.index))
                q_z = quality_z.reindex(eligible.index).fillna(0.0)
                blended = (momentum_w * mom_z + quality_w * q_z) / (momentum_w + quality_w)
                ranked = blended.sort_values(ascending=False)
                picks = ranked.index[:TOP_N].tolist()
                if picks:
                    w[picks] = 1.0 / TOP_N
            regime_scale = 0.5 if (signal_date in below_200.index and bool(below_200.loc[signal_date])) else 1.0
            last_weights = w * regime_scale
            monthly_log.append({"date": str(signal_date.date()), "n_eligible": int(len(eligible)), "picks": picks})
        weights.iloc[i] = last_weights.values
    return weights, monthly_log


def run_backtest(closes: pd.DataFrame, weights_full: pd.DataFrame, start: str, end: str) -> tuple[dict, float]:
    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    closes_s = closes.loc[sliced_idx]
    weights = weights_full.loc[sliced_idx]
    daily_ret = closes_s.pct_change().fillna(0.0)
    executed = weights.shift(1).fillna(0.0)
    port_ret = (daily_ret * executed).sum(axis=1)
    turnover = executed.diff().abs().sum(axis=1).fillna(0.0)
    port_ret_after_cost = port_ret - turnover * ROUND_TRIP_COST
    equity = (1.0 + port_ret_after_cost).cumprod() * 100.0
    equity.iloc[0] = 100.0
    m = calculate_metrics(equity, [], equity.index[0], equity.index[-1])
    invested_frac = float(weights.sum(axis=1).clip(upper=1.0).mean())
    return m, invested_frac


def cash_stats_from_log(monthly_log: list) -> dict:
    counts = np.array([e["n_eligible"] for e in monthly_log])
    picks_filled = np.array([len(e["picks"]) for e in monthly_log])
    return {
        "n_months": int(len(counts)),
        "mean_eligible_pool": round(float(counts.mean()), 2) if len(counts) else None,
        "pct_months_filled_topn": round(100.0 * float((picks_filled >= TOP_N).mean()), 1) if len(picks_filled) else None,
        "pct_months_zero_eligible": round(100.0 * float((counts == 0).mean()), 1) if len(counts) else None,
    }


def main():
    result = {"meta": {
        "start": START, "end": END, "sample_n": SAMPLE_N, "random_seed": RANDOM_SEED,
        "quality_filter_reference": {"peg_max": PEG_MAX, "growth_min_pct": GROWTH_MIN_PCT, "roe_min_pct": ROE_MIN_PCT},
        "blend_weights_tested": BLEND_WEIGHTS,
        "limitation": "품질 지표는 현재 시점 스냅샷만 사용(H4와 동일 한계, point-in-time 아님)",
    }}

    log(f"S&P500 섹터균등 표본 {SAMPLE_N}종목 추출 (seed={RANDOM_SEED}, H4와 동일)...")
    uni = sample_universe(n=SAMPLE_N, random_seed=RANDOM_SEED)
    tickers = uni["ticker"].tolist()
    result["sample_tickers"] = tickers

    log("품질 지표(PEG/성장률/ROE프록시) 조회...")
    qdf = determine_quality_metrics(tickers)
    result["quality_metrics_detail"] = qdf.to_dict(orient="records")
    hard_pass_count = int(qdf["quality_pass_hard_filter"].sum())
    log(f"   (참고) 동일 지표로 H4식 경성 필터 적용 시 통과: {hard_pass_count}/{len(tickers)}")
    result["hard_filter_pass_count_reference"] = hard_pass_count

    quality_z = build_quality_zscore(qdf)
    result["quality_zscore"] = quality_z.round(4).to_dict()

    log("가격 데이터 로딩...")
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    hist = get_multiple_price_history(tickers + ["SPY"], start=fetch_start, end=END, interval="1d")
    closes_all = pd.DataFrame({t: df["Close"] for t, df in hist.items() if not df.empty}).sort_index().ffill()
    spy_close = closes_all["SPY"]
    valid_tickers = [t for t in tickers if t in closes_all.columns]
    closes = closes_all[valid_tickers]
    log(f"   로딩 완료: {len(valid_tickers)}/{len(tickers)}종목")

    # 1) 순수 모멘텀 베이스라인(H4와 동일 로직 재구현 — quality_w=0으로 블렌드 함수 재사용)
    log("1) 순수 모멘텀 베이스라인...")
    w_pure, log_pure = build_blended_weights(closes, spy_close, quality_z, quality_w=0.0, momentum_w=1.0)
    m_pure, inv_pure = run_backtest(closes, w_pure, START, END)
    cash_pure = cash_stats_from_log(log_pure)
    log(f"   순수 모멘텀: {m_pure}")
    result["pure_momentum"] = {"metrics": m_pure, "avg_invested_frac": round(inv_pure, 3), "cash_stats": cash_pure}

    # 2) 소프트 블렌드 (equal 50/50, momentum-tilted 30/70)
    result["soft_blends"] = {}
    for bw in BLEND_WEIGHTS:
        log(f"2) 소프트 블렌드 {bw['label']} (quality_w={bw['quality_w']}, momentum_w={bw['momentum_w']})...")
        w_blend, log_blend = build_blended_weights(closes, spy_close, quality_z, bw["quality_w"], bw["momentum_w"])
        m_blend, inv_blend = run_backtest(closes, w_blend, START, END)
        cash_blend = cash_stats_from_log(log_blend)
        log(f"   {bw['label']}: {m_blend}")
        log(f"   현금화/폭 통계: {cash_blend}")
        result["soft_blends"][bw["label"]] = {
            "quality_w": bw["quality_w"], "momentum_w": bw["momentum_w"],
            "metrics": m_blend, "avg_invested_frac": round(inv_blend, 3), "cash_stats": cash_blend,
            "sample_monthly_log": log_blend[:6] + log_blend[-3:],
        }

    # 3) 참고 — H4의 경성 필터 결과(같은 표본/기간, 원본 값 그대로 인용 — 재실행 아님)
    log("3) H4 경성 필터 결과 인용(원본 h4_results.json)...")
    h4_path = Path(MAIN_CHECKOUT) / "analysis/2026-08-19_permutation_and_quality_momentum_research/h4_results.json"
    with open(h4_path) as f:
        h4 = json.load(f)
    result["h4_hard_filter_reference"] = {
        "source": "analysis/2026-08-19_permutation_and_quality_momentum_research/h4_results.json (원본 재실행 아님, 동일 표본/기간 인용)",
        "pure_momentum": h4["pure_momentum"],
        "quality_momentum_hard_filter": h4["quality_momentum"],
        "quality_cap_momentum_hard_filter_robustness": h4["quality_cap_momentum"],
    }

    # 4) 벤치마크
    log("4) 벤치마크...")
    spy_bh = run_buy_and_hold("SPY", START, END)
    result["spy_buy_hold"] = spy_bh.metrics

    with open(OUT_DIR / "h6_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h6_results.json'}")


if __name__ == "__main__":
    main()
