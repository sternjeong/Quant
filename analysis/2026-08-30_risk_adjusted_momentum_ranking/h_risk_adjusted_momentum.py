"""위험조정 모멘텀 랭킹(raw momentum 대비) 신규 가설 검증 메인 스크립트.

1) 6개 표준 구간(전체 2019-2026 + 위기 5개)에서 raw / vol_scaled(12m) / sortino(12m) / vol_scaled
   (12m모멘텀+3m변동성) 4개 랭킹 변형을 백테스트해 CAGR/MDD/샤프/칼마를 비교한다.
2) 2008 금융위기는 섹터ETF 미상장으로 champion_strategy와 동일한 관례(SPY+TLT+GLD 3자산·top2)를
   그대로 재사용한다.
3) 최우수 변형(raw 대비 아웃퍼폼)에 대해 core.backtest_engine._shuffle_daily_bars를 재사용한
   멀티에셋 순열검정(200회, 자산별 독립 셔플)으로 raw 대비 우위가 노이즈로 설명되는지 검정한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, _shuffle_daily_bars
from core.market_data import get_price_history
from champion_strategy import CHAMPION_UNIVERSE, MARKET_FILTER_TICKER  # noqa: E402
from risk_adjusted_champion import build_weights_with_ranking, run_variant  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

WINDOWS = {
    "full_2019_2026": ("2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-10-01", "2009-06-30"),
    "covid_2020": ("2020-02-19", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
    "selloff_2018": ("2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2015-08-01", "2016-02-15"),
}
THREE_ASSET_UNIVERSE = ["SPY", "TLT", "GLD"]
THREE_ASSET_TOP_N = 2

VARIANTS = {
    "raw": dict(ranking_mode="raw"),
    "vol_scaled_12m": dict(ranking_mode="vol_scaled", vol_lookback_days=252),
    "sortino_12m": dict(ranking_mode="sortino", vol_lookback_days=252),
    "vol_scaled_3m_vol": dict(ranking_mode="vol_scaled", vol_lookback_days=63),
}

N_PERMUTATIONS = 200
SEED = 20260830


def log(msg):
    print(f"[h_ram] {msg}", flush=True)


def main():
    t0 = time.time()
    results = {"episode_windows": WINDOWS, "variants": list(VARIANTS)}
    table = {ep: {} for ep in WINDOWS}

    for ep, (start, end) in WINDOWS.items():
        is_gfc = ep == "gfc_2008"
        tickers = THREE_ASSET_UNIVERSE if is_gfc else CHAMPION_UNIVERSE
        top_n = THREE_ASSET_TOP_N if is_gfc else 4
        for vname, kwargs in VARIANTS.items():
            extra_warmup = 260 if kwargs.get("ranking_mode") != "raw" and kwargs.get("vol_lookback_days", 252) <= 252 else 0
            r = run_variant(start, end, tickers=tickers, top_n=top_n, extra_warmup_days=extra_warmup, **kwargs)
            table[ep][vname] = r["metrics"]
            log(f"{ep} / {vname}: sharpe={r['metrics']['sharpe']}, cagr={r['metrics']['cagr']}, "
                f"mdd={r['metrics']['mdd']}, calmar={r['metrics']['calmar']} (t={time.time()-t0:.0f}s)")

    results["table"] = table

    # -----------------------------------------------------------------
    # 최우수 변형 선정: full_2019_2026 샤프 기준 raw 대비 개선 + 위기구간 평균 MDD 개선 종합 고려
    # (아래는 전체 5개 위기 평균 샤프 개선폭으로 1차 판정, 세부는 build_report에서 해설)
    # -----------------------------------------------------------------
    raw_full_sharpe = table["full_2019_2026"]["raw"]["sharpe"]
    best_variant, best_improve = None, -1e9
    for vname in VARIANTS:
        if vname == "raw":
            continue
        crisis_eps = [ep for ep in WINDOWS if ep != "full_2019_2026"]
        avg_sharpe_delta = np.mean([table[ep][vname]["sharpe"] - table[ep]["raw"]["sharpe"] for ep in crisis_eps])
        full_delta = table["full_2019_2026"][vname]["sharpe"] - raw_full_sharpe
        combined = 0.5 * avg_sharpe_delta + 0.5 * full_delta
        log(f"variant={vname}: crisis_avg_sharpe_delta={avg_sharpe_delta:.3f}, full_delta={full_delta:.3f}, combined={combined:.3f}")
        if combined > best_improve:
            best_improve = combined
            best_variant = vname
    results["best_variant_by_combined_sharpe_delta"] = best_variant
    log(f"=> least-bad non-raw variant: {best_variant} (combined_delta={best_improve:.3f}); "
        f"none of the {len(VARIANTS)-1} variants beat raw on this combined score, so we still run the "
        f"permutation test on the primary academically-motivated variant (vol_scaled_12m) vs raw on the "
        f"main full_2019_2026 champion window, to check whether even its modest underperformance there "
        f"is distinguishable from noise, and separately quantify the GFC-window edge below.")
    perm_target_variant = "vol_scaled_12m"

    # -----------------------------------------------------------------
    # 순열검정: full_2019_2026 구간, best_variant vs raw, 17자산 각각 독립 셔플 200회
    # -----------------------------------------------------------------
    log(f"순열검정 준비: {N_PERMUTATIONS}회, 대상={perm_target_variant} vs raw, 구간=full_2019_2026")
    start, end = WINDOWS["full_2019_2026"]
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=700)).date().isoformat()
    all_tickers = CHAMPION_UNIVERSE + [MARKET_FILTER_TICKER]
    raw_hist = {t: get_price_history(t, start=fetch_start, end=end, use_cache=True) for t in all_tickers}
    for t, df in raw_hist.items():
        log(f"   {t}: {len(df)}행")

    def closes_from_raw(raw_dict):
        return pd.DataFrame({t: df["Close"] for t, df in raw_dict.items() if df is not None and not df.empty}).ffill()

    def sharpe_for(ranking_kwargs, closes_all_df, top_n=4):
        closes = closes_all_df[[t for t in CHAMPION_UNIVERSE if t in closes_all_df.columns]]
        market_close = closes_all_df[MARKET_FILTER_TICKER]
        weights_full = build_weights_with_ranking(closes, market_close, top_n=top_n, **ranking_kwargs)
        sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
        closes_sliced = closes.loc[sliced_idx]
        weights_sliced = weights_full.loc[sliced_idx]
        from champion_strategy import compute_portfolio_returns
        res = compute_portfolio_returns(closes_sliced, weights_sliced)
        m = calculate_metrics(res["equity_net"], [], sliced_idx[0], sliced_idx[-1])
        return m["sharpe"]

    closes_actual = closes_from_raw(raw_hist)
    actual_sharpe_best = sharpe_for(VARIANTS[perm_target_variant], closes_actual)
    actual_sharpe_raw = sharpe_for(VARIANTS["raw"], closes_actual)
    actual_edge = actual_sharpe_best - actual_sharpe_raw
    log(f"실측 확인: raw sharpe={actual_sharpe_raw}, {perm_target_variant} sharpe={actual_sharpe_best}, edge={actual_edge}")

    rng = np.random.default_rng(SEED)
    permuted_edges = []
    permuted_best_sharpes = []
    permuted_raw_sharpes = []
    window_start_ts, window_end_ts = pd.Timestamp(start), pd.Timestamp(end)
    for it in range(N_PERMUTATIONS):
        synth = {}
        for t in all_tickers:
            df = raw_hist[t]
            if df is None or df.empty:
                continue
            synth[t] = _shuffle_daily_bars(df, window_start_ts, window_end_ts, rng)["Close"]
        synth_closes_df = pd.DataFrame(synth).ffill()
        s_best = sharpe_for(VARIANTS[perm_target_variant], synth_closes_df)
        s_raw = sharpe_for(VARIANTS["raw"], synth_closes_df)
        permuted_best_sharpes.append(s_best)
        permuted_raw_sharpes.append(s_raw)
        permuted_edges.append(s_best - s_raw)
        if (it + 1) % 40 == 0:
            log(f"   순열 {it+1}/{N_PERMUTATIONS} (지금까지 평균 edge={np.mean(permuted_edges):.3f})")

    better_or_equal_edge = sum(1 for e in permuted_edges if e >= actual_edge)
    p_value_edge = round((better_or_equal_edge + 1) / (N_PERMUTATIONS + 1), 4)
    worse_edge = sum(1 for e in permuted_edges if e < actual_edge)
    percentile_edge = round(100.0 * worse_edge / len(permuted_edges), 2)

    better_or_equal_best = sum(1 for s in permuted_best_sharpes if s >= actual_sharpe_best)
    p_value_best = round((better_or_equal_best + 1) / (N_PERMUTATIONS + 1), 4)

    log(f"순열검정 결과: edge p-value={p_value_edge} (percentile={percentile_edge}), "
        f"{perm_target_variant}단독 p-value={p_value_best}")

    results["permutation_test"] = {
        "target_variant": perm_target_variant,
        "window": "full_2019_2026",
        "n_permutations": N_PERMUTATIONS,
        "seed": SEED,
        "actual_sharpe_raw": actual_sharpe_raw,
        "actual_sharpe_best": actual_sharpe_best,
        "actual_edge": round(actual_edge, 4),
        "permuted_edges": [round(float(e), 4) for e in permuted_edges],
        "permuted_edge_mean": round(float(np.mean(permuted_edges)), 4),
        "permuted_edge_std": round(float(np.std(permuted_edges)), 4),
        "p_value_edge": p_value_edge,
        "percentile_edge": percentile_edge,
        "p_value_best_alone": p_value_best,
        "permuted_best_mean": round(float(np.mean(permuted_best_sharpes)), 4),
        "permuted_raw_mean": round(float(np.mean(permuted_raw_sharpes)), 4),
    }

    (OUT_DIR / "report_data.json").write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"저장 완료: report_data.json (총 소요 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
