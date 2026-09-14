"""H4 — 퀄리티(PEG/성장률/ROE) 사전필터를 얹은 모멘텀 로테이션이 순수 모멘텀 로테이션보다 나은가.

작업19~23(트랙 B)의 챔피언은 GICS 섹터/자산 ETF를 순수 트레일링 모멘텀으로만 랭킹했다. 작업26(트랙 C
1번째 리포트)은 별도로 PEG<=1.5·이익성장률>=15%·ROE프록시>=15% 품질/밸류에이션 필터를
`core.screener.screen()` + `core.valuation`으로 구축했지만 1회성 정적 스크리닝으로만 썼고 모멘텀
랭킹/로테이션과 결합한 적은 없다. Asness/Frazzini/Pedersen의 "Quality Minus Junk"(퀄리티 팩터가
모멘텀과 상대적으로 낮은 상관관계를 갖고 결합 시 개선된다는 실증)를 근거로, 이 결합을 개별주
S&P500 유니버스에서 실제로 백테스트한다.

정확한 필터 정의(작업26과 다른 점을 명시):
  - core.valuation 기반 2단계 그대로 재사용: PEG<=1.5(양수), 이익성장률>=15%, ROE프록시(EPS/BVPS)>=15%.
  - 작업26의 1단계(`screen()`의 `market_cap_max=$300억` + 핫섹터 제한)는 "텐베거"(소형·특정 테마)
    발굴에 특화된 제약이라 일반 로테이션 비교에는 그대로 가져오지 않는다 — 대신 메인 비교는
    market_cap 상한 없이 순수 품질/밸류에이션 필터만 적용한다. 다만 작업26이 예고한 "품질 필터가
    후보 폭을 구조적으로 줄인다"는 긴장을 그대로 확인하기 위해, 별도 강건성 런에서 $300억 시총
    상한을 다시 걸어 그 효과를 명시적으로 재현한다(§로버스트니스).

방법론상 한계(정직하게 명시): core.valuation의 펀더멘털은 "현재 시점" 스냅샷뿐이라(작업25가 만든
point-in-time 인프라는 시가총액에만 적용됨, PEG/성장률/ROE의 과거 시점 값은 이 저장소에 없음) —
"오늘 기준 퀄리티를 통과하는 종목 집합"을 고정한 뒤 그 집합으로 과거 전체 구간을 모멘텀 로테이션
하는 방식이다. 이는 생존자 성격의 전향편향(hindsight)을 내포한다 — 결론에서 반드시 짚는다.
"""
import json
import sys

PROJECT_ROOT = "/workspaces/Quant/.claude/worktrees/agent-ad691d1b13ff1f0a9"
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pandas as pd

from core import screener
from core.strategy_tuning import sample_universe
from core.valuation import fetch_valuation_inputs, peg_ratio
from core.market_data import get_multiple_price_history
from core.backtest_engine import calculate_metrics, run_buy_and_hold, _first_trading_day_of_month_mask

OUT_DIR = f"{PROJECT_ROOT}/analysis/2026-08-19_permutation_and_quality_momentum_research"

START, END = "2019-08-12", "2026-08-12"  # 트랙 B No.06/07과 동일 기간(직접 비교 가능하도록)
WARMUP_DAYS = 400
MOMENTUM_WINDOW = 252  # 12개월
TOP_N = 4  # 트랙 B 챔피언과 동일
ROUND_TRIP_COST = 0.001  # 왕복 0.1%
SAMPLE_N = 100
RANDOM_SEED = 42

PEG_MAX = 1.5
GROWTH_MIN_PCT = 15.0
ROE_MIN_PCT = 15.0
CAP_CEILING_ROBUSTNESS = 30_000_000_000  # 작업26과 동일한 $300억 상한(로버스트니스 런 전용)


def log(msg):
    print(f"[h4] {msg}", flush=True)


def determine_quality_pass(tickers: list[str]) -> pd.DataFrame:
    """작업26의 2단계 필터(PEG/성장률/ROE프록시)를 그대로 재사용해 오늘 시점 품질 통과 여부를 판정."""
    rows = []
    for t in tickers:
        try:
            vinputs = fetch_valuation_inputs(t)
        except Exception as e:
            log(f"   {t}: valuation 조회 실패 ({e})")
            continue
        per = vinputs.get("trailingPE")
        eps = vinputs.get("trailingEps")
        bvps = vinputs.get("bookValue")
        earnings_growth = vinputs.get("earningsGrowth")
        earnings_growth_pct = earnings_growth * 100 if earnings_growth is not None else None
        peg = peg_ratio(per, earnings_growth_pct)
        roe_proxy_pct = (eps / bvps * 100) if (eps and bvps and bvps > 0) else None
        passes = (
            peg is not None and 0 < peg <= PEG_MAX
            and earnings_growth_pct is not None and earnings_growth_pct >= GROWTH_MIN_PCT
            and roe_proxy_pct is not None and roe_proxy_pct >= ROE_MIN_PCT
        )
        rows.append({
            "ticker": t, "per": per, "peg": peg, "earnings_growth_pct": earnings_growth_pct,
            "roe_proxy_pct": roe_proxy_pct, "quality_pass": passes,
        })
    return pd.DataFrame(rows)


def build_momentum_weights_with_regime(closes: pd.DataFrame, spy_close: pd.Series,
                                        momentum_window: int, top_n: int) -> pd.DataFrame:
    """트랙 B 챔피언과 동일 로직: 12개월 절대+상대 모멘텀 top_n 동일비중, 후보부족은 현금,
    SPY<200일선이면 전체 비중 50% 축소(이진 시장필터, No.06~07과 동일)."""
    momentum = closes.pct_change(momentum_window)
    sma200 = spy_close.rolling(200, min_periods=200).mean()
    below_200 = (spy_close < sma200)

    is_rebal = _first_trading_day_of_month_mask(closes.index)
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            candidates = mom[mom > 0].sort_values(ascending=False)
            picks = candidates.index[:top_n]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / top_n
            regime_scale = 0.5 if (signal_date in below_200.index and bool(below_200.loc[signal_date])) else 1.0
            last_weights = w * regime_scale
        weights.iloc[i] = last_weights.values
    return weights


def run_rotation(closes: pd.DataFrame, spy_close: pd.Series, start: str, end: str) -> tuple[dict, pd.Series, int]:
    closes = closes.ffill()
    weights_full = build_momentum_weights_with_regime(closes, spy_close, MOMENTUM_WINDOW, TOP_N)
    sliced = closes[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    weights = weights_full.loc[sliced.index]
    daily_ret = sliced.pct_change().fillna(0.0)
    executed = weights.shift(1).fillna(0.0)
    port_ret = (daily_ret * executed).sum(axis=1)
    turnover = executed.diff().abs().sum(axis=1).fillna(0.0)
    port_ret_after_cost = port_ret - turnover * ROUND_TRIP_COST
    equity = (1.0 + port_ret_after_cost).cumprod() * 100.0
    equity.iloc[0] = 100.0
    m = calculate_metrics(equity, [], equity.index[0], equity.index[-1])
    # 현금비율(=평균 미투자 비중) — 후보부족으로 얼마나 자주 현금화됐는지 감 잡기 위한 참고 지표
    invested_frac = float(weights_full.loc[sliced.index].sum(axis=1).clip(upper=1.0).mean())
    n_rebalance_months = int(is_rebal_count(sliced.index))
    return m, equity, invested_frac, n_rebalance_months


def is_rebal_count(idx) -> int:
    return int(_first_trading_day_of_month_mask(idx).sum())


def cash_month_stats(closes: pd.DataFrame, start: str, end: str) -> dict:
    """리밸런싱 월별로 몇 개 종목이 절대모멘텀(>0) 후보였는지 분포 — '현금화가 얼마나 잦았는가'."""
    closes = closes.ffill()
    momentum = closes.pct_change(MOMENTUM_WINDOW)
    is_rebal = _first_trading_day_of_month_mask(closes.index)
    sliced_idx = closes[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))].index
    counts = []
    for i, dt in enumerate(closes.index):
        if dt not in sliced_idx or not is_rebal.iloc[i] or i == 0:
            continue
        signal_date = closes.index[i - 1]
        mom = momentum.loc[signal_date]
        n_candidates = int((mom > 0).sum())
        counts.append(n_candidates)
    counts = np.array(counts)
    return {
        "n_months": int(len(counts)),
        "mean_candidates": round(float(counts.mean()), 2) if len(counts) else None,
        "pct_months_full_topn": round(100.0 * float((counts >= TOP_N).mean()), 1) if len(counts) else None,
        "pct_months_zero_candidates": round(100.0 * float((counts == 0).mean()), 1) if len(counts) else None,
        "pct_months_below_topn": round(100.0 * float((counts < TOP_N).mean()), 1) if len(counts) else None,
    }


def main():
    result = {"meta": {
        "start": START, "end": END, "momentum_window_days": MOMENTUM_WINDOW, "top_n": TOP_N,
        "sample_n": SAMPLE_N, "random_seed": RANDOM_SEED, "round_trip_cost": ROUND_TRIP_COST,
        "quality_filter": {"peg_max": PEG_MAX, "growth_min_pct": GROWTH_MIN_PCT, "roe_min_pct": ROE_MIN_PCT},
        "cap_ceiling_robustness": CAP_CEILING_ROBUSTNESS,
        "limitation": "펀더멘털(PEG/성장률/ROE)은 현재 시점 스냅샷만 사용 — point-in-time 아님(전향편향 내포, 결론에 명시)",
    }}

    # ------------------------------------------------------------------
    # 1) S&P500 표본 100종목 (섹터 균등, 결정론적 시드)
    # ------------------------------------------------------------------
    log(f"S&P500 섹터균등 표본 {SAMPLE_N}종목 추출 (seed={RANDOM_SEED})...")
    uni = sample_universe(n=SAMPLE_N, random_seed=RANDOM_SEED)
    tickers = uni["ticker"].tolist()
    log(f"   표본 {len(tickers)}종목, 섹터 {uni['sector'].nunique()}개")
    result["sample_tickers"] = tickers
    result["sample_by_sector"] = uni.groupby("sector")["ticker"].apply(list).to_dict()

    # ------------------------------------------------------------------
    # 2) 오늘 시점 품질 필터 통과 여부 판정
    # ------------------------------------------------------------------
    log("품질/밸류에이션 필터(PEG<=1.5, 성장률>=15%, ROE프록시>=15%) 판정...")
    qdf = determine_quality_pass(tickers)
    qdf = qdf.merge(uni[["ticker", "sector", "market_cap"]], on="ticker", how="left")
    quality_pass_tickers = qdf[qdf["quality_pass"]]["ticker"].tolist()
    log(f"   품질필터 통과: {len(quality_pass_tickers)}/{len(tickers)} — {quality_pass_tickers}")
    result["quality_screen_detail"] = qdf.to_dict(orient="records")
    result["quality_pass_tickers"] = quality_pass_tickers
    result["quality_pass_count"] = len(quality_pass_tickers)
    result["quality_pass_pct_of_sample"] = round(100.0 * len(quality_pass_tickers) / len(tickers), 1)

    # 로버스트니스: $300억 시총 상한까지 추가로 걸면 몇 개나 남는가(작업26 긴장 재현)
    quality_and_cap = qdf[qdf["quality_pass"] & (qdf["market_cap"] <= CAP_CEILING_ROBUSTNESS)]["ticker"].tolist()
    log(f"   +시총 $300억 상한까지 적용 시: {len(quality_and_cap)}종목 — {quality_and_cap}")
    result["quality_and_cap_ceiling_tickers"] = quality_and_cap

    if len(quality_pass_tickers) < TOP_N:
        log(f"   경고: 품질통과 종목이 top_n({TOP_N})보다 적음 — 로테이션이 사실상 '전원 동일비중'에 가까워짐")

    # ------------------------------------------------------------------
    # 3) 가격 데이터 로딩 (표본 100 + SPY)
    # ------------------------------------------------------------------
    log("가격 데이터 로딩...")
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    hist = get_multiple_price_history(tickers + ["SPY"], start=fetch_start, end=END, interval="1d")
    closes_all = pd.DataFrame({t: df["Close"] for t, df in hist.items() if not df.empty}).sort_index()
    spy_close = closes_all["SPY"]
    log(f"   로딩 완료: {len(closes_all.columns)}종목 (요청 {len(tickers) + 1}개 중 결측 {len(tickers) + 1 - len(closes_all.columns)}개)")
    missing = set(tickers + ["SPY"]) - set(closes_all.columns)
    if missing:
        log(f"   결측 종목: {missing}")
    result["missing_price_data_tickers"] = sorted(missing)

    valid_tickers = [t for t in tickers if t in closes_all.columns]
    valid_quality_tickers = [t for t in quality_pass_tickers if t in closes_all.columns]

    # ------------------------------------------------------------------
    # 4) 순수 모멘텀 로테이션 (표본 100 전체, 품질필터 없음)
    # ------------------------------------------------------------------
    log(f"4) 순수 모멘텀 로테이션 (표본 {len(valid_tickers)}종목)...")
    closes_pure = closes_all[valid_tickers]
    m_pure, eq_pure, invested_pure, n_months = run_rotation(closes_pure, spy_close, START, END)
    cash_pure = cash_month_stats(closes_pure, START, END)
    log(f"   순수 모멘텀: {m_pure}")
    log(f"   현금화 통계: {cash_pure}")
    result["pure_momentum"] = {"metrics": m_pure, "avg_invested_frac": round(invested_pure, 3), "cash_stats": cash_pure, "universe_size": len(valid_tickers)}

    # ------------------------------------------------------------------
    # 5) 품질필터 + 모멘텀 로테이션 (품질통과 종목만)
    # ------------------------------------------------------------------
    log(f"5) 품질필터+모멘텀 로테이션 (품질통과 {len(valid_quality_tickers)}종목)...")
    if len(valid_quality_tickers) >= 1:
        closes_q = closes_all[valid_quality_tickers]
        m_q, eq_q, invested_q, _ = run_rotation(closes_q, spy_close, START, END)
        cash_q = cash_month_stats(closes_q, START, END)
        log(f"   품질+모멘텀: {m_q}")
        log(f"   현금화 통계: {cash_q}")
        result["quality_momentum"] = {"metrics": m_q, "avg_invested_frac": round(invested_q, 3), "cash_stats": cash_q, "universe_size": len(valid_quality_tickers)}
    else:
        log("   품질통과 종목이 0개라 로테이션 자체가 불가능")
        result["quality_momentum"] = None

    # ------------------------------------------------------------------
    # 6) 로버스트니스 — 품질 + $300억 시총 상한(작업26 원 필터 재현)
    # ------------------------------------------------------------------
    valid_qc_tickers = [t for t in quality_and_cap if t in closes_all.columns]
    log(f"6) 로버스트니스: 품질+시총상한 ({len(valid_qc_tickers)}종목)...")
    if len(valid_qc_tickers) >= 1:
        closes_qc = closes_all[valid_qc_tickers]
        m_qc, eq_qc, invested_qc, _ = run_rotation(closes_qc, spy_close, START, END)
        cash_qc = cash_month_stats(closes_qc, START, END)
        log(f"   품질+시총상한: {m_qc}")
        result["quality_cap_momentum"] = {"metrics": m_qc, "avg_invested_frac": round(invested_qc, 3), "cash_stats": cash_qc, "universe_size": len(valid_qc_tickers)}
    else:
        log("   품질+시총상한 통과 종목 0개 — 로테이션 불가 (작업26의 긴장을 그대로 재현)")
        result["quality_cap_momentum"] = None

    # ------------------------------------------------------------------
    # 7) 벤치마크 — SPY 매수보유, 표본 100 균등가중 매수보유
    # ------------------------------------------------------------------
    log("7) 벤치마크...")
    spy_bh = run_buy_and_hold("SPY", START, END)
    result["spy_buy_hold"] = spy_bh.metrics
    log(f"   SPY 매수보유: {spy_bh.metrics}")

    sliced_pure = closes_pure[(closes_pure.index >= pd.Timestamp(START)) & (closes_pure.index <= pd.Timestamp(END))].ffill()
    norm = sliced_pure / sliced_pure.iloc[0]
    eq_ew = norm.mean(axis=1) * 100.0
    m_ew = calculate_metrics(eq_ew, [], eq_ew.index[0], eq_ew.index[-1])
    result["sample_equal_weight_buy_hold"] = m_ew
    log(f"   표본 100 균등가중 매수보유: {m_ew}")

    # ------------------------------------------------------------------
    # 8) 참고 — 트랙 B 17자산 ETF 챔피언 (No.07, 실측 기존 검증 결과 인용, 동일 기간)
    # ------------------------------------------------------------------
    result["track_b_17asset_champion_reference"] = {
        "source": "docs/reports/momentum_rotation_gfc_validation.html (No.07, 작업22)",
        "period": {"start": START, "end": END},
        "universe": "11 GICS 섹터 ETF + TLT/IEF/GLD/EFA/HYG/DBC (17자산)",
        "metrics": {"cumulative_return": 152.57, "cagr": 14.16, "mdd": -14.63, "sharpe": 1.10},
        "note": "코드 재실행이 아니라 기존 검증된 리포트 수치를 그대로 인용 (동일 기간, 다른 유니버스)",
    }

    with open(f"{OUT_DIR}/h4_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/h4_results.json")


if __name__ == "__main__":
    main()
