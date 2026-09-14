"""H8 — 퀄리티 필터의 진짜 정체: 플라시보 검정.

작업30 H4는 100종목 표본(작업19 sample_universe(n=100, seed=42))에 PEG<=1.5·성장률>=15%·
ROE프록시>=15% 하드 필터를 걸어 26종목으로 좁힌 뒤, 동일한 모멘텀 로테이션(top4·12개월·월간
리밸런싱·SPY 200일선 이진 시장필터·왕복0.1%비용)을 돌려 샤프 0.82를 얻었다(순수 모멘텀 0.68 대비
개선). 작업31 H6은 이 개선이 "퀄리티 신호의 일반적 예측력"이 아니라 "그 시기 실제 승자가 몰려
있던 좁은 부분집합으로 우연히 좁혀졌기 때문"일 수 있다고 의심했지만, 이 의심을 formal하게 검증한
적은 없다.

이 스크립트는 그 의심을 직접 검정한다: 같은 100종목 표본에서 (품질 기준 없이) 무작위로 26종목을
뽑아 h4와 동일한 로테이션 백테스트를 반복 실행하고, 그 결과 샤프비율 분포(플라시보/귀무분포)를
만든다. 실제 품질필터 샤프(0.82)가 이 분포에서 어느 백분위에 위치하는지를 보면 "퀄리티 필터가 정말
일하는지, 단순 부분집합 축소 효과인지"를 구분할 수 있다.

방법론 노트:
  - h4_quality_momentum_hybrid.py의 run_rotation/build_momentum_weights_with_regime 로직을
    그대로 재사용(동일 top_n/모멘텀윈도우/시장필터/비용).
  - 무작위 추출은 "고정 시드로 26종목을 한 번 뽑아 전체 백테스트 기간에 고정"한다(매월 재추첨하지
    않음 — 그러면 플라시보의 의미가 사라짐).
  - 표본 크기와 추출 개수는 h4의 quality_pass_tickers 개수(26)를 h4_results.json에서 그대로
    읽어와 맞춘다(하드코딩 방지).

core/ 참고: main 체크아웃(/workspaces/Quant)의 core/를 sys.path 최상단에 꽂아 참조한다(이 워크트리의
core/는 다른 세션이 동시 진행 중인 변경으로 오래됐을 수 있음 — 작업30/31이 명시한 관례를 따름).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)

import numpy as np
import pandas as pd

from core.market_data import get_multiple_price_history
from core.backtest_engine import calculate_metrics, _first_trading_day_of_month_mask

OUT_DIR = Path(__file__).resolve().parent
H4_RESULTS = Path(MAIN_CHECKOUT) / "analysis/2026-08-19_permutation_and_quality_momentum_research/h4_results.json"

START, END = "2019-08-12", "2026-08-12"  # h4와 동일 기간
WARMUP_DAYS = 400
MOMENTUM_WINDOW = 252
TOP_N = 4
ROUND_TRIP_COST = 0.001
N_DRAWS = 200
BASE_SEED = 20260820


def log(msg):
    print(f"[h8] {msg}", flush=True)


def build_momentum_weights_with_regime(closes: pd.DataFrame, spy_close: pd.Series,
                                        momentum_window: int, top_n: int) -> pd.DataFrame:
    """h4_quality_momentum_hybrid.py와 완전히 동일한 로직(복붙 재사용, 의존성 최소화 목적)."""
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


def run_rotation(closes: pd.DataFrame, spy_close: pd.Series, start: str, end: str) -> dict:
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
    return m


def main():
    t_start = time.time()
    log("h4_results.json 로드 (표본 100종목 + 품질통과 26종목 확인)...")
    h4 = json.loads(H4_RESULTS.read_text(encoding="utf-8"))
    sample_tickers = h4["sample_tickers"]
    quality_pass_tickers = h4["quality_pass_tickers"]
    n_sample = len(sample_tickers)
    n_quality = len(quality_pass_tickers)
    real_sharpe_from_h4 = h4["quality_momentum"]["metrics"]["sharpe"]
    log(f"   표본 {n_sample}종목, 품질통과 {n_quality}종목, h4 기록 샤프={real_sharpe_from_h4}")

    log("가격 데이터 로딩 (표본 100 + SPY, 로컬 파케이 캐시 활용)...")
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=WARMUP_DAYS)).date().isoformat()
    hist = get_multiple_price_history(sample_tickers + ["SPY"], start=fetch_start, end=END, interval="1d")
    closes_all = pd.DataFrame({t: df["Close"] for t, df in hist.items() if not df.empty}).sort_index()
    spy_close = closes_all["SPY"]
    valid_tickers = [t for t in sample_tickers if t in closes_all.columns]
    valid_quality_tickers = [t for t in quality_pass_tickers if t in closes_all.columns]
    log(f"   가격데이터 확보: 표본 {len(valid_tickers)}/{n_sample}, 품질통과 {len(valid_quality_tickers)}/{n_quality}")

    # ------------------------------------------------------------------
    # 1) 실제 품질필터 결과 재확인 (h4와 동일 로직으로 직접 재실행 — h4_results.json 인용이 아니라
    #    이 스크립트의 run_rotation으로 직접 재현해 두 결과가 일치하는지 확인)
    # ------------------------------------------------------------------
    log("1) 실제 품질필터+모멘텀 로테이션 재현...")
    closes_q = closes_all[valid_quality_tickers]
    m_real = run_rotation(closes_q, spy_close, START, END)
    log(f"   재현 결과: {m_real}")

    # ------------------------------------------------------------------
    # 2) 순수 모멘텀(표본 100 전체) 참고용 재확인
    # ------------------------------------------------------------------
    closes_pure = closes_all[valid_tickers]
    m_pure = run_rotation(closes_pure, spy_close, START, END)
    log(f"   참고: 순수 모멘텀(표본 100) 샤프={m_pure['sharpe']}")

    # ------------------------------------------------------------------
    # 3) 플라시보 널분포 — 표본 100에서 무작위로 n_quality종목 추출 x N_DRAWS
    # ------------------------------------------------------------------
    log(f"3) 무작위 {n_quality}종목 추출 x {N_DRAWS}회 널분포 생성 (base_seed={BASE_SEED})...")
    null_sharpes = []
    null_draws_detail = []
    for i in range(N_DRAWS):
        rng = np.random.default_rng(BASE_SEED + i)
        draw = rng.choice(valid_tickers, size=n_quality, replace=False).tolist()
        closes_draw = closes_all[draw]
        m = run_rotation(closes_draw, spy_close, START, END)
        null_sharpes.append(m["sharpe"])
        null_draws_detail.append({"draw_idx": i, "tickers": draw, "sharpe": m["sharpe"], "cagr": m["cagr"], "mdd": m["mdd"]})
        if (i + 1) % 40 == 0:
            log(f"   {i+1}/{N_DRAWS} 완료 (경과 {time.time()-t_start:.0f}s)")

    null_sharpes = np.array(null_sharpes)
    real_sharpe = m_real["sharpe"]
    percentile = float((null_sharpes < real_sharpe).mean() * 100.0)
    # 동률 처리(<=)도 함께 기록
    percentile_le = float((null_sharpes <= real_sharpe).mean() * 100.0)

    result = {
        "meta": {
            "start": START, "end": END, "n_sample": len(valid_tickers), "n_quality": n_quality,
            "n_draws": N_DRAWS, "base_seed": BASE_SEED,
            "momentum_window_days": MOMENTUM_WINDOW, "top_n": TOP_N, "round_trip_cost": ROUND_TRIP_COST,
        },
        "real_quality_filter": {
            "tickers": valid_quality_tickers,
            "metrics": m_real,
            "h4_original_sharpe_for_reference": real_sharpe_from_h4,
        },
        "pure_momentum_reference": {"metrics": m_pure, "universe_size": len(valid_tickers)},
        "null_distribution": {
            "sharpes": [round(float(s), 4) for s in null_sharpes],
            "mean": round(float(null_sharpes.mean()), 4),
            "median": round(float(np.median(null_sharpes)), 4),
            "std": round(float(null_sharpes.std(ddof=1)), 4),
            "min": round(float(null_sharpes.min()), 4),
            "max": round(float(null_sharpes.max()), 4),
            "p10": round(float(np.percentile(null_sharpes, 10)), 4),
            "p25": round(float(np.percentile(null_sharpes, 25)), 4),
            "p75": round(float(np.percentile(null_sharpes, 75)), 4),
            "p90": round(float(np.percentile(null_sharpes, 90)), 4),
            "p95": round(float(np.percentile(null_sharpes, 95)), 4),
        },
        "real_sharpe_percentile_strict_less": round(percentile, 1),
        "real_sharpe_percentile_le": round(percentile_le, 1),
        "implied_p_value_two_sided_upper_tail": round(1.0 - percentile / 100.0, 4),
        "draws_detail": null_draws_detail,
    }

    with open(OUT_DIR / "h8_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h8_results.json'}")
    log(f"실제 품질필터 샤프={real_sharpe:.3f}, 널분포 mean={null_sharpes.mean():.3f} median={np.median(null_sharpes):.3f} "
        f"std={null_sharpes.std(ddof=1):.3f}, 백분위={percentile:.1f}% (총 {time.time()-t_start:.0f}s)")


if __name__ == "__main__":
    main()
