"""H10 - 새틀라이트 선정 로직을 모멘텀 랭킹 -> 돈치안 브레이크아웃+트레일링스탑(추세추종)으로 교체.

배경: H5(작업31)의 point-in-time 새틀라이트는 반기 리밸런싱마다 후보 풀(sample_universe)에서 단순
12개월 모멘텀 상위 3종목을 고른다. H9(작업32)가 이를 무작위 선택 200회와 비교하는 플라시보 검정을
했더니 88번째 백분위 - "무작위보다는 낫지만 결정적이지 않다"는 애매한 결과였다. 반면 작업27/H3은
IREN류 변동성 종목에 20일 돈치안 브레이크아웃+15% 트레일링스탑을 적용한 추세추종 전략이 순열검정에서
100번째 백분위(p=0.005)로 이 저장소 전체 연구 중 가장 강한 통계적 근거를 보였다.

이 스크립트는 그 강한 신호를 새틀라이트 선정 로직에 그대로 이식한다:
  - 코어/새틀라이트 인프라, 반기 리밸런싱 일정, point-in-time 후보 풀(SATELLITE_POOL_N=40),
    top_k=3, 15% 블렌드 비중은 H1/H5/H9와 동일 (직접 비교 가능하도록).
  - 선정 로직만 교체: 리밸런싱일 전일 기준으로 각 후보에 20일 돈치안 브레이크아웃+15% 트레일링스탑
    포지션 신호(donchian_trailing_stop_positions, IREN 리서치 backtest.py와 동일 함수 - 의존성
    꼬임을 피하려 이 파일에 그대로 복사)를 계산해 "현재 추세 신호가 켜져 있는(활성 브레이크아웃)"
    종목만 후보로 남기고, 그 안에서 12개월 모멘텀으로 순위를 매겨 상위 3개를 고른다. 활성 신호가
    3개 미만이면 남는 슬롯은 현금(모멘텀 새틀라이트와 동일 관례).
  - 보유방식은 모멘텀 새틀라이트와 동일하게 "반기 동안 정적 보유"로 유지한다(장중 트레일링스탑
    청산까지 재현하지 않음 - H9의 무작위선택 널분포와 정확히 같은 보유 메커니즘을 유지해야 선정
    로직만 격리해서 비교할 수 있기 때문. 04 한계에 명시).

core/ 참고: 이 워크트리는 point-in-time 인프라(작업25)가 main에 올라오기 전 시점에서 분기되어
core/point_in_time_market_cap.py가 없다 - 작업30이 경고한 실수(구버전 core/를 워크트리에 복사)를
반복하지 않기 위해, H5/H9와 동일하게 main 체크아웃의 core/를 sys.path 최상단에 꽂아 항상 "지금
main의" 코드를 그대로 참조한다.
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

from champion_strategy import (
    CHAMPION_UNIVERSE, MARKET_FILTER_TICKER, run_champion, _closes_from_histories, compute_portfolio_returns,
)
from h1_core_satellite import (
    semiannual_rebal_dates, blend_returns, build_satellite_returns,
    SATELLITE_POOL_N, SATELLITE_TOP_K, SATELLITE_MOMENTUM_WINDOW, SATELLITE_WARMUP_DAYS,
    SATELLITE_COST_BPS_PER_SIDE,
)
from core.backtest_engine import calculate_metrics
from core.market_data import get_multiple_price_history
from core.strategy_tuning import sample_universe

OUT_DIR = Path(__file__).resolve().parent
H9_RESULTS = Path(MAIN_CHECKOUT) / "analysis/2026-08-20_quality_filter_and_satellite_placebo_research/h9_results.json"

START, END = "2019-08-12", "2026-08-19"  # H1/H5/H9와 동일 구간(직접 비교)
SATELLITE_WEIGHTS = [0.10, 0.15, 0.20]  # H5가 찾은 정점 인근
DONCHIAN_ENTRY_WINDOW = 20
DONCHIAN_STOP_PCT = 0.15
TREND_FETCH_LOOKBACK_DAYS = 730  # 돈치안 신호가 안정되도록 넉넉히(2년) 과거 이력 확보


def log(msg):
    print(f"[h10] {msg}", flush=True)


def donchian_trailing_stop_positions(close: pd.Series, entry_window: int, stop_pct: float) -> pd.Series:
    """작업27 analysis/2026-08-16_iren_volatile_momentum_stocks/backtest.py의 동일 함수를 그대로
    복사(교차 워크트리 임포트 취약성을 피하기 위함). 20일 돈치안 브레이크아웃 진입 + %트레일링스탑
    청산 신호(0/1) 생성."""
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


def pick_satellite_trend_following_at_date(rebal_date: pd.Timestamp, top_k: int = SATELLITE_TOP_K) -> dict:
    """rebal_date 시점 point-in-time 유니버스에서, '지금 돈치안 브레이크아웃이 살아있는(활성 추세)'
    종목만 후보로 남기고 그 안에서 12개월 모멘텀 상위 top_k를 고른다."""
    as_of_str = rebal_date.date().isoformat()
    pool = sample_universe(n=SATELLITE_POOL_N, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
    candidates = [t for t in pool["ticker"].tolist() if t not in CHAMPION_UNIVERSE and t != MARKET_FILTER_TICKER]

    fetch_start = (rebal_date - pd.DateOffset(days=TREND_FETCH_LOOKBACK_DAYS)).date().isoformat()
    fetch_end = rebal_date.date().isoformat()
    histories = get_multiple_price_history(candidates, start=fetch_start, end=fetch_end, interval="1d")

    active_scores = {}
    for t in candidates:
        df = histories.get(t)
        if df is None or df.empty:
            continue
        close = df["Close"]
        close = close[close.index < rebal_date]  # 전일까지만 사용(당일 미포함, 룩어헤드 방지)
        if len(close) < DONCHIAN_ENTRY_WINDOW + 60:
            continue
        pos = donchian_trailing_stop_positions(close, DONCHIAN_ENTRY_WINDOW, DONCHIAN_STOP_PCT)
        if pos.iloc[-1] != 1:
            continue  # 활성 추세 신호 없음 -> 후보 제외
        if len(close) >= SATELLITE_MOMENTUM_WINDOW + 5:
            mom = close.iloc[-1] / close.iloc[-1 - SATELLITE_MOMENTUM_WINDOW] - 1.0
        else:
            mom = close.iloc[-1] / close.iloc[0] - 1.0  # 짧은 이력은 확보된 전체 구간 수익률로 대체
        if pd.notna(mom):
            active_scores[t] = float(mom)

    ranked = sorted(active_scores.items(), key=lambda kv: kv[1], reverse=True)
    picks = [t for t, m in ranked[:top_k]]

    return {
        "date": as_of_str,
        "pool_size": len(candidates),
        "n_active_trend": len(active_scores),
        "picks": picks,
        "pick_scores": {t: round(m, 4) for t, m in ranked[:top_k]},
    }


def build_satellite_returns_trend_following(start: str, end: str, trading_index: pd.DatetimeIndex, top_k: int = SATELLITE_TOP_K) -> dict:
    rebal_dates = semiannual_rebal_dates(trading_index, start, end)
    log(f"{len(rebal_dates)}개 반기 리밸런싱일(추세추종 선정): {[str(d.date()) for d in rebal_dates]}")

    all_picks_log = []
    all_tickers: set[str] = set()
    per_period_picks: list[tuple[pd.Timestamp, list[str]]] = []
    for i, d in enumerate(rebal_dates):
        t0 = time.time()
        info = pick_satellite_trend_following_at_date(d, top_k=top_k)
        log(f"  [{i+1}/{len(rebal_dates)}] {info['date']}: picks={info['picks']} "
            f"(pool={info['pool_size']}, 활성추세={info['n_active_trend']}, {time.time()-t0:.1f}s)")
        all_picks_log.append(info)
        per_period_picks.append((d, info["picks"]))
        all_tickers.update(info["picks"])

    all_tickers = sorted(all_tickers)
    if not all_tickers:
        raise RuntimeError("추세추종 새틀라이트 후보가 한 번도 뽑히지 않음")

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
                w[picks] = 1.0 / top_k
            last_w = w
        weights.loc[dt] = last_w.values

    result = compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)
    metrics = calculate_metrics(result["equity_net"], [], full_idx[0], full_idx[-1])

    return {
        "start": str(full_idx[0].date()),
        "end": str(full_idx[-1].date()),
        "rebal_log": all_picks_log,
        "tickers_ever_held": all_tickers,
        "metrics": metrics,
        "ret_net": result["ret_net"],
        "equity_net": result["equity_net"],
    }


def main():
    t0 = time.time()
    log(f"코어(17자산 챔피언) 실행: {START} ~ {END}")
    core = run_champion(START, END)
    trading_index = core["ret_net"].index
    log(f"코어 지표: {core['metrics']}")

    log("모멘텀 새틀라이트(H5/H9와 동일 로직) 구축...")
    sat_momentum = build_satellite_returns(START, END, trading_index)
    log(f"모멘텀 새틀라이트 지표: {sat_momentum['metrics']}")

    log("추세추종 새틀라이트(신규, 돈치안+트레일링스탑 게이트) 구축...")
    sat_trend = build_satellite_returns_trend_following(START, END, trading_index)
    log(f"추세추종 새틀라이트 지표: {sat_trend['metrics']}")

    def blend_table(sat_ret):
        rows = []
        for sw in SATELLITE_WEIGHTS:
            br = blend_returns(core["ret_net"], sat_ret, sw)
            eq = (1 + br).cumprod() * 100.0
            eq.iloc[0] = 100.0
            m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
            rows.append({"satellite_weight": sw, "metrics": m})
        return rows

    momentum_blends = blend_table(sat_momentum["ret_net"])
    trend_blends = blend_table(sat_trend["ret_net"])

    for row in momentum_blends:
        log(f"  [momentum] sw={row['satellite_weight']:.2f}: sharpe={row['metrics']['sharpe']:.3f} "
            f"cagr={row['metrics']['cagr']:.2f}% mdd={row['metrics']['mdd']:.2f}% calmar={row['metrics']['calmar']:.3f}")
    for row in trend_blends:
        log(f"  [trend]    sw={row['satellite_weight']:.2f}: sharpe={row['metrics']['sharpe']:.3f} "
            f"cagr={row['metrics']['cagr']:.2f}% mdd={row['metrics']['mdd']:.2f}% calmar={row['metrics']['calmar']:.3f}")

    # ------------------------------------------------------------------
    # 플라시보 재검정: H9의 무작위선택 널분포(200회, 정적보유, 15% 비중)를 그대로 로드해
    # 추세추종 새틀라이트(15%)의 백분위를 계산한다. 보유방식(반기 정적보유)이 H9 널분포와
    # 정확히 동일하므로 "선정 로직만" 격리해서 비교 가능.
    # ------------------------------------------------------------------
    log("H9 널분포 로드 및 추세추종 새틀라이트 백분위 계산...")
    h9 = json.loads(H9_RESULTS.read_text(encoding="utf-8"))
    null_sharpes = np.array(h9["null_distribution"]["sharpes"])
    real_momentum_sharpe_at_15 = next(r["metrics"]["sharpe"] for r in momentum_blends if r["satellite_weight"] == 0.15)
    real_trend_sharpe_at_15 = next(r["metrics"]["sharpe"] for r in trend_blends if r["satellite_weight"] == 0.15)

    momentum_percentile = float((null_sharpes < real_momentum_sharpe_at_15).mean() * 100.0)
    trend_percentile = float((null_sharpes < real_trend_sharpe_at_15).mean() * 100.0)
    log(f"H9 널분포(n={len(null_sharpes)}, mean={null_sharpes.mean():.3f}, std={null_sharpes.std(ddof=1):.3f}): "
        f"모멘텀(재확인)={momentum_percentile:.1f}%ile(H9 원 보고 88.0%ile), 추세추종={trend_percentile:.1f}%ile")

    result = {
        "meta": {
            "start": START, "end": END, "satellite_weights_tested": list(SATELLITE_WEIGHTS),
            "donchian_entry_window": DONCHIAN_ENTRY_WINDOW, "donchian_stop_pct": DONCHIAN_STOP_PCT,
            "satellite_pool_n": SATELLITE_POOL_N, "satellite_top_k": SATELLITE_TOP_K,
        },
        "core_metrics": core["metrics"],
        "satellite_momentum": {
            "standalone_metrics": sat_momentum["metrics"],
            "rebal_log": sat_momentum["rebal_log"],
            "tickers_ever_held": sat_momentum["tickers_ever_held"],
            "blends": momentum_blends,
        },
        "satellite_trend_following": {
            "standalone_metrics": sat_trend["metrics"],
            "rebal_log": sat_trend["rebal_log"],
            "tickers_ever_held": sat_trend["tickers_ever_held"],
            "blends": trend_blends,
        },
        "placebo_retest_vs_h9_null": {
            "h9_null_source": str(H9_RESULTS),
            "null_n_draws": len(null_sharpes),
            "null_mean": round(float(null_sharpes.mean()), 4),
            "null_median": round(float(np.median(null_sharpes)), 4),
            "null_std": round(float(null_sharpes.std(ddof=1)), 4),
            "satellite_weight_compared": 0.15,
            "momentum_real_sharpe": round(real_momentum_sharpe_at_15, 4),
            "momentum_percentile_recomputed": round(momentum_percentile, 1),
            "momentum_percentile_h9_original_report": 88.0,
            "trend_following_real_sharpe": round(real_trend_sharpe_at_15, 4),
            "trend_following_percentile": round(trend_percentile, 1),
        },
    }

    with open(OUT_DIR / "h10_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h10_results.json'} (총 {time.time()-t0:.0f}s)")

    # 새틀라이트 일간 순수익률 시계열도 저장(H11에서 2022 구간만 잘라 쓰기 위함)
    core["ret_net"].to_frame("core_ret_net").to_csv(OUT_DIR / "core_ret_net.csv")
    sat_momentum["ret_net"].to_frame("sat_momentum_ret_net").to_csv(OUT_DIR / "sat_momentum_ret_net.csv")
    sat_trend["ret_net"].to_frame("sat_trend_ret_net").to_csv(OUT_DIR / "sat_trend_ret_net.csv")
    log("일간 수익률 CSV 저장 완료 (H11 재사용용)")


if __name__ == "__main__":
    main()
