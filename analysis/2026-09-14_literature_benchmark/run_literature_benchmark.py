"""리서치 에이전트 H(문헌대조) - 오늘의 주제: "12개월 트레일링 원시가격모멘텀 랭킹"에 대한
외부 학술 문헌 대조 + 미시도 확립 기법(Jegadeesh-Titman 1993 / Novy-Marx 2012의 "12-2" 최근월
제외 관행) 재현.

confidence_table의 두 항목을 함께 다룬다:
  - "모멘텀 랭킹 방식(12개월 트레일링, 원시가격모멘텀)" (moderate)
  - "위험조정(변동성조정) 모멘텀 랭킹" (reversed - raw가 vol_scaled/sortino를 이김)
둘 다 analysis/2026-08-30_risk_adjusted_momentum_ranking/ 한 스크립트에서 같이 나온 결론이다.

이번 실행은:
  1) 기존 raw vs vol_scaled/sortino 결과(report_data.json, 이미 계산됨)를 그대로 인용한다
     (재탕 검증이 아니라 "외부 문헌과 대조하기 위해 재인용" - 새 계산은 아래 2)/3)).
  2) 문헌이 실제로 권장하는, 이 저장소가 아직 안 해본 정제: 최근 1개월을 제외한 "12-2" 모멘텀
     신호(raw_skip1m)를 skip_month_momentum.py로 구현해 동일 6개 구간에서 raw(스킵없음)과
     비교한다.
  3) full_2019_2026 구간에서 raw_skip1m vs raw 우위가 노이즈로 설명되는지 core.backtest_engine.
     _shuffle_daily_bars 재사용 멀티에셋 순열검정(200회)으로 검정한다 - 2026-08-30 스크립트와
     동일한 방법론.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WORKTREE_ROOT = "/workspaces/Quant/.claude/worktrees/agent-ab5b3cdcd18a01aae"
sys.path.insert(0, WORKTREE_ROOT)
sys.path.insert(0, str(Path(WORKTREE_ROOT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, _shuffle_daily_bars
from core.market_data import get_price_history
from champion_strategy import CHAMPION_UNIVERSE, MARKET_FILTER_TICKER, compute_portfolio_returns  # noqa: E402
from skip_month_momentum import build_weights_with_ranking, run_variant, SKIP_DAYS  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
PRIOR_STUDY_DIR = Path(WORKTREE_ROOT) / "analysis" / "2026-08-30_risk_adjusted_momentum_ranking"

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

N_PERMUTATIONS = 200
SEED = 20260914


def log(msg):
    print(f"[lit_bench] {msg}", flush=True)


def main():
    t0 = time.time()

    prior = json.loads((PRIOR_STUDY_DIR / "report_data.json").read_text(encoding="utf-8"))
    prior_table = prior["table"]

    results = {
        "episode_windows": WINDOWS,
        "variants": ["raw", "raw_skip1m", "vol_scaled_12m", "sortino_12m", "vol_scaled_3m_vol"],
        "cited_prior_study": "analysis/2026-08-30_risk_adjusted_momentum_ranking/report_data.json",
    }
    table = {ep: {} for ep in WINDOWS}

    for ep, (start, end) in WINDOWS.items():
        is_gfc = ep == "gfc_2008"
        tickers = THREE_ASSET_UNIVERSE if is_gfc else CHAMPION_UNIVERSE
        top_n = THREE_ASSET_TOP_N if is_gfc else 4

        # (1) 기존 raw / vol_scaled_12m / sortino_12m / vol_scaled_3m_vol - 08-30 결과 그대로 인용
        for vname in ("raw", "vol_scaled_12m", "sortino_12m", "vol_scaled_3m_vol"):
            table[ep][vname] = prior_table[ep][vname]

        # (2) 신규: raw_skip1m (Jegadeesh-Titman 1993 / Novy-Marx 2012 "12-2" 관행)
        extra_warmup = 40  # SKIP_DAYS(21거래일) 만큼 여유
        r = run_variant(start, end, tickers=tickers, top_n=top_n, ranking_mode="raw_skip1m",
                         extra_warmup_days=extra_warmup)
        table[ep]["raw_skip1m"] = r["metrics"]
        log(f"{ep} / raw_skip1m: sharpe={r['metrics']['sharpe']}, cagr={r['metrics']['cagr']}, "
            f"mdd={r['metrics']['mdd']}, calmar={r['metrics']['calmar']} (t={time.time()-t0:.0f}s) "
            f"[참고 raw: sharpe={table[ep]['raw']['sharpe']}, cagr={table[ep]['raw']['cagr']}]")

    results["table"] = table

    full_raw = table["full_2019_2026"]["raw"]
    full_skip = table["full_2019_2026"]["raw_skip1m"]
    log(f"=> full_2019_2026: raw sharpe={full_raw['sharpe']} vs raw_skip1m sharpe={full_skip['sharpe']} "
        f"(delta={full_skip['sharpe']-full_raw['sharpe']:.3f})")

    # -----------------------------------------------------------------
    # 순열검정: full_2019_2026 구간, raw_skip1m vs raw, 17자산+SPY 각각 독립 셔플 200회
    # (2026-08-30 스크립트와 동일 방법론 재사용)
    # -----------------------------------------------------------------
    start, end = WINDOWS["full_2019_2026"]
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=700)).date().isoformat()
    all_tickers = CHAMPION_UNIVERSE + [MARKET_FILTER_TICKER]
    raw_hist = {t: get_price_history(t, start=fetch_start, end=end, use_cache=True) for t in all_tickers}
    for t, df in raw_hist.items():
        log(f"   {t}: {len(df)}행")

    def closes_from_raw(raw_dict):
        return pd.DataFrame({t: df["Close"] for t, df in raw_dict.items() if df is not None and not df.empty}).ffill()

    def sharpe_for(ranking_mode, closes_all_df, top_n=4):
        closes = closes_all_df[[t for t in CHAMPION_UNIVERSE if t in closes_all_df.columns]]
        market_close = closes_all_df[MARKET_FILTER_TICKER]
        weights_full = build_weights_with_ranking(closes, market_close, ranking_mode=ranking_mode, top_n=top_n)
        sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
        closes_sliced = closes.loc[sliced_idx]
        weights_sliced = weights_full.loc[sliced_idx]
        res = compute_portfolio_returns(closes_sliced, weights_sliced)
        m = calculate_metrics(res["equity_net"], [], sliced_idx[0], sliced_idx[-1])
        return m["sharpe"]

    closes_actual = closes_from_raw(raw_hist)
    actual_sharpe_raw = sharpe_for("raw", closes_actual)
    actual_sharpe_skip = sharpe_for("raw_skip1m", closes_actual)
    actual_edge = actual_sharpe_skip - actual_sharpe_raw
    log(f"실측 확인: raw sharpe={actual_sharpe_raw}, raw_skip1m sharpe={actual_sharpe_skip}, edge={actual_edge}")

    rng = np.random.default_rng(SEED)
    permuted_edges, permuted_skip_sharpes, permuted_raw_sharpes = [], [], []
    window_start_ts, window_end_ts = pd.Timestamp(start), pd.Timestamp(end)
    for it in range(N_PERMUTATIONS):
        synth = {}
        for t in all_tickers:
            df = raw_hist[t]
            if df is None or df.empty:
                continue
            synth[t] = _shuffle_daily_bars(df, window_start_ts, window_end_ts, rng)["Close"]
        synth_closes_df = pd.DataFrame(synth).ffill()
        s_skip = sharpe_for("raw_skip1m", synth_closes_df)
        s_raw = sharpe_for("raw", synth_closes_df)
        permuted_skip_sharpes.append(s_skip)
        permuted_raw_sharpes.append(s_raw)
        permuted_edges.append(s_skip - s_raw)
        if (it + 1) % 40 == 0:
            log(f"   순열 {it+1}/{N_PERMUTATIONS} (지금까지 평균 edge={np.mean(permuted_edges):.3f})")

    better_or_equal_edge = sum(1 for e in permuted_edges if e >= actual_edge)
    p_value_edge = round((better_or_equal_edge + 1) / (N_PERMUTATIONS + 1), 4)
    worse_edge = sum(1 for e in permuted_edges if e < actual_edge)
    percentile_edge = round(100.0 * worse_edge / len(permuted_edges), 2)

    log(f"순열검정 결과: edge p-value={p_value_edge} (percentile={percentile_edge})")

    results["permutation_test"] = {
        "target_variant": "raw_skip1m",
        "baseline_variant": "raw",
        "window": "full_2019_2026",
        "n_permutations": N_PERMUTATIONS,
        "seed": SEED,
        "actual_sharpe_raw": actual_sharpe_raw,
        "actual_sharpe_skip1m": actual_sharpe_skip,
        "actual_edge": round(actual_edge, 4),
        "permuted_edge_mean": round(float(np.mean(permuted_edges)), 4),
        "permuted_edge_std": round(float(np.std(permuted_edges)), 4),
        "p_value_edge": p_value_edge,
        "percentile_edge": percentile_edge,
    }

    (OUT_DIR / "report_data.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    log(f"저장 완료: report_data.json (총 소요 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
