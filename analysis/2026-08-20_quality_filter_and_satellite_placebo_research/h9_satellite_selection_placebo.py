"""H9 — 새틀라이트의 진짜 가치: 플라시보 검정.

작업30 H1 / 작업31 H5는 17자산 코어 챔피언에 point-in-time 개별주 새틀라이트(반기 리밸런싱,
sample_universe(as_of_date=t, use_point_in_time_market_cap=True)로 뽑은 후보 풀 중 12개월 모멘텀
상위 3종목 동일가중)를 15~20% 비중으로 얹어 샤프를 1.03 -> 1.09까지 개선했다. 이 개선이 "모멘텀
랭킹이라는 선택 로직 자체"가 만든 것인지, 아니면 "그 point-in-time 후보 풀에서 아무거나 3종목을
집어도 나오는 일반적 분산효과"인지는 formal하게 검정된 적이 없다.

이 스크립트는 h1_core_satellite.py/h5_satellite_weight_sweep.py와 정확히 같은 코어·새틀라이트
구축 인프라(같은 반기 리밸런싱 일정, 같은 point-in-time 후보 풀, 같은 top_k=3, 같은 15% 블렌드
비중, 같은 비용)를 재사용하되, 각 리밸런싱 시점마다 모멘텀 랭킹 대신 그 시점 후보 풀에서 무작위로
3종목을 뽑는 "무작위 새틀라이트"를 반복 구성해(~200회) 귀무분포를 만든다. 실제(모멘텀랭킹) 블렌드
샤프(H5의 15% 정점, 1.09)가 이 분포에서 어디에 위치하는지를 본다.

core/ 참고: main 체크아웃(/workspaces/Quant)의 core/를 sys.path 최상단에 꽂아 참조(이 워크트리의
core/는 point-in-time 인프라가 없는 구버전 — H5/H1과 동일한 관례).
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
from h1_core_satellite import semiannual_rebal_dates, SATELLITE_POOL_N, SATELLITE_TOP_K, SATELLITE_WARMUP_DAYS
from core.backtest_engine import calculate_metrics
from core.market_data import get_multiple_price_history
from core.strategy_tuning import sample_universe

OUT_DIR = Path(__file__).resolve().parent
H5_RESULTS = Path(MAIN_CHECKOUT) / "analysis/2026-08-20_satellite_frontier_and_quality_blend_research/h5_results.json"

START, END = "2019-08-12", "2026-08-19"  # H5와 동일 기간
SATELLITE_WEIGHT = 0.15  # H5 정점 비중(실측)
N_DRAWS = 200
BASE_SEED = 20260820
SATELLITE_COST_BPS_PER_SIDE = 5.0


def log(msg):
    print(f"[h9] {msg}", flush=True)


def blend_returns(core_ret: pd.Series, sat_ret: pd.Series, sw: float) -> pd.Series:
    a, b = core_ret.align(sat_ret, join="inner")
    return (1 - sw) * a + sw * b


def main():
    t0 = time.time()
    log(f"코어(17자산 챔피언) 실행: {START} ~ {END}")
    core = run_champion(START, END)
    trading_index = core["ret_net"].index
    log(f"코어 지표: {core['metrics']}")

    rebal_dates = semiannual_rebal_dates(trading_index, START, END)
    log(f"반기 리밸런싱 {len(rebal_dates)}회: {[str(d.date()) for d in rebal_dates]}")

    # ------------------------------------------------------------------
    # 1) 각 리밸런싱 시점의 point-in-time 후보 풀(모멘텀 계산 없이 풀 자체만) 확보
    # ------------------------------------------------------------------
    log("1) 시점별 point-in-time 후보 풀 조회 (H1/H5와 동일 캐시 재사용)...")
    pool_by_date: dict[pd.Timestamp, list[str]] = {}
    for d in rebal_dates:
        as_of_str = d.date().isoformat()
        pool = sample_universe(n=SATELLITE_POOL_N, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
        candidates = [t for t in pool["ticker"].tolist() if t not in CHAMPION_UNIVERSE and t != MARKET_FILTER_TICKER]
        pool_by_date[d] = candidates
        log(f"   {as_of_str}: 후보 {len(candidates)}종목")

    union_tickers = sorted(set(t for cands in pool_by_date.values() for t in cands))
    log(f"   전체 기간 통합 후보 유니버스: {len(union_tickers)}종목")

    # ------------------------------------------------------------------
    # 2) 가격 데이터 로딩 (통합 후보 전체, 로컬 캐시 활용 — h1/h5가 이미 모멘텀 계산 시 이 풀들의
    #    가격이력을 조회해둬서 캐시 적중률이 높을 것으로 기대)
    # ------------------------------------------------------------------
    log("2) 가격 데이터 로딩...")
    fetch_start = (pd.Timestamp(START) - pd.DateOffset(days=SATELLITE_WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(union_tickers, start=fetch_start, end=END, interval="1d")
    closes = _closes_from_histories(histories, union_tickers)
    full_idx = trading_index[(trading_index >= pd.Timestamp(START)) & (trading_index <= pd.Timestamp(END))]
    closes = closes.reindex(full_idx).ffill()
    log(f"   가격 데이터 확보: {len(closes.columns)}/{len(union_tickers)}종목")

    # 시점별 "가격데이터 확보된" 유효 후보만 남김(모멘텀 계산 없이도 최소 데이터 존재는 요구)
    valid_pool_by_date: dict[pd.Timestamp, list[str]] = {}
    for d, cands in pool_by_date.items():
        valid = [t for t in cands if t in closes.columns and pd.notna(closes.loc[d, t])]
        valid_pool_by_date[d] = valid

    # ------------------------------------------------------------------
    # 3) 실제(모멘텀랭킹) 새틀라이트 결과 — H5 실측치 인용(재실행 대신, 동일 인프라·동일 기간이므로
    #    직접 인용해도 공정 비교. draws_detail에 재현 가능하도록 h5_results.json 경로 명시)
    # ------------------------------------------------------------------
    h5 = json.loads(H5_RESULTS.read_text(encoding="utf-8"))
    real_peak = h5["peak_sharpe_metrics"]
    real_peak_weight = h5["peak_sharpe_weight"]
    real_sat_standalone = h5["satellite_standalone_metrics"]
    log(f"   H5 실측(인용): 정점비중={real_peak_weight}, 샤프={real_peak['sharpe']}, 새틀라이트단독샤프={real_sat_standalone['sharpe']}")

    # 15% 지점의 실측 샤프도 h5 frontier에서 직접 뽑아 SATELLITE_WEIGHT와 정확히 일치시킨다
    real_frontier = {f["satellite_weight"]: f["metrics"] for f in h5["frontier"]}
    real_metrics_at_sw = real_frontier.get(SATELLITE_WEIGHT, real_peak)
    real_sharpe = real_metrics_at_sw["sharpe"]
    log(f"   비교 기준(비중={SATELLITE_WEIGHT}): 실제 모멘텀랭킹 새틀라이트 블렌드 샤프={real_sharpe}")

    # ------------------------------------------------------------------
    # 4) 무작위 선택 새틀라이트 널분포 — N_DRAWS회
    # ------------------------------------------------------------------
    log(f"4) 무작위 새틀라이트(반기당 무작위 {SATELLITE_TOP_K}종목) x {N_DRAWS}회 널분포 생성...")
    null_sharpes = []
    null_draws_detail = []
    core_ret = core["ret_net"]
    for i in range(N_DRAWS):
        rng = np.random.default_rng(BASE_SEED + i)
        weights = pd.DataFrame(0.0, index=full_idx, columns=closes.columns)
        last_w = pd.Series(0.0, index=closes.columns)
        picks_log = {}
        for dt in full_idx:
            if dt in valid_pool_by_date:
                valid = valid_pool_by_date[dt]
                k = min(SATELLITE_TOP_K, len(valid))
                picks = rng.choice(valid, size=k, replace=False).tolist() if k > 0 else []
                w = pd.Series(0.0, index=closes.columns)
                if picks:
                    w[picks] = 1.0 / SATELLITE_TOP_K
                last_w = w
                picks_log[str(dt.date())] = picks
            weights.loc[dt] = last_w.values

        result = compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)
        sat_ret = result["ret_net"]
        br = blend_returns(core_ret, sat_ret, SATELLITE_WEIGHT)
        eq = (1 + br).cumprod() * 100.0
        eq.iloc[0] = 100.0
        m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
        null_sharpes.append(m["sharpe"])
        null_draws_detail.append({"draw_idx": i, "picks_by_date": picks_log, "sharpe": m["sharpe"], "cagr": m["cagr"], "mdd": m["mdd"]})
        if (i + 1) % 40 == 0:
            log(f"   {i+1}/{N_DRAWS} 완료 (경과 {time.time()-t0:.0f}s)")

    null_sharpes = np.array(null_sharpes)
    percentile = float((null_sharpes < real_sharpe).mean() * 100.0)
    percentile_le = float((null_sharpes <= real_sharpe).mean() * 100.0)

    result = {
        "meta": {
            "start": START, "end": END, "satellite_weight": SATELLITE_WEIGHT,
            "n_rebal_dates": len(rebal_dates), "satellite_top_k": SATELLITE_TOP_K,
            "satellite_pool_n": SATELLITE_POOL_N, "n_draws": N_DRAWS, "base_seed": BASE_SEED,
            "cost_bps_per_side": SATELLITE_COST_BPS_PER_SIDE,
        },
        "core_metrics": core["metrics"],
        "real_momentum_ranked_satellite": {
            "source": "h5_results.json (동일 인프라·기간 실측 인용, 재실행 아님)",
            "satellite_weight_compared": SATELLITE_WEIGHT,
            "metrics_at_this_weight": real_metrics_at_sw,
            "peak_weight_reference": real_peak_weight,
            "peak_metrics_reference": real_peak,
            "satellite_standalone_metrics_reference": real_sat_standalone,
        },
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
        "pool_by_date_sizes": {str(d.date()): len(v) for d, v in valid_pool_by_date.items()},
        "draws_detail": null_draws_detail,
    }

    with open(OUT_DIR / "h9_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h9_results.json'}")
    log(f"실제(모멘텀랭킹) 샤프={real_sharpe:.3f}, 널분포(무작위선택) mean={null_sharpes.mean():.3f} "
        f"median={np.median(null_sharpes):.3f} std={null_sharpes.std(ddof=1):.3f}, 백분위={percentile:.1f}% "
        f"(총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
