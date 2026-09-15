"""2단계: 코어(17자산 로테이션) 순열검정 + 코어/새틀라이트/통합 블록부트스트랩을
현재 비용가정(0.1% 왕복) vs 보수적 비용가정(0.5% 왕복)에서 각각 수행 — 비용을 현실화해도 통계적
결론(순열검정 p-value, 부트스트랩 신뢰구간)이 바뀌는지 확인.

방법론은 이 저장소 기존 관례를 코드 그대로 재사용한다:
  - 순열검정: core.backtest_engine._shuffle_daily_bars (2026-08-19 h3_permutation_test.py와 동일 원리
    — 각 티커의 캔들모양은 보존, 날짜 순서만 무작위로 섞어 추세/자기상관 제거). N=200, SEED=20260914.
    새틀라이트는 매 반기 point-in-time 유니버스 재추출이 필요해 순열마다 재실행하면 계산비용이
    지나치게 크므로(반기당 40종목 풀 스캔 x 200회) 이번 감사에서는 제외한다 — 코어만 순열검정.
  - 블록부트스트랩: analysis/2026-08-23_block_bootstrap_sample_error_quantification (H33) /
    2026-08-24 (H34)와 동일한 순환 이동블록부트스트랩(block_len 10/20/40, 창당 2000회). 이건 이미
    계산된 일별 순수익률 시계열에 대해서만 재표본하므로 코어/새틀라이트/통합 시스템 전부에 저비용으로
    적용 가능하다(step1이 저장한 *_ret_*.csv를 그대로 사용).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))

import numpy as np
import pandas as pd

from core.backtest_engine import _shuffle_daily_bars, calculate_metrics
from core.champion_strategy import (
    CORE_UNIVERSE, MARKET_FILTER_TICKER, BACKTEST_WARMUP_DAYS,
    _build_core_weights, _compute_portfolio_returns,
)
from core.market_data import get_multiple_price_history

OUT_DIR = Path(__file__).resolve().parent
FULL_START = "2019-08-12"
FULL_END = "2026-09-14"
N_PERMUTATIONS = 200
SEED = 20260914
N_BOOT = 2000
BLOCK_LENGTHS = [10, 20, 40]
TRADING_DAYS = 252

PERMUTATION_COST_SCENARIOS = {"current_0.1pct_rt": 5.0, "conservative_0.5pct_rt": 25.0}


def log(msg):
    print(f"[step2] {msg}", flush=True)


def annualized_sharpe(ret: np.ndarray) -> float:
    if len(ret) < 2:
        return float("nan")
    mu, sd = np.mean(ret), np.std(ret, ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(mu / sd * np.sqrt(TRADING_DAYS))


def moving_block_bootstrap_sharpe(ret: np.ndarray, block_len: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    n = len(ret)
    if n == 0:
        return np.full(n_boot, np.nan)
    block_len = min(block_len, n)
    n_blocks_needed = int(np.ceil(n / block_len))
    sharpes = np.empty(n_boot)
    ext = np.concatenate([ret, ret])
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks_needed)
        pieces = [ext[s:s + block_len] for s in starts]
        synth = np.concatenate(pieces)[:n]
        sharpes[b] = annualized_sharpe(synth)
    return sharpes


def run_core_permutation():
    tickers = list(CORE_UNIVERSE) + [MARKET_FILTER_TICKER]
    log("코어+SPY 원본 OHLCV(전 이력) 로딩...")
    raw = get_multiple_price_history(tickers, start="2008-01-01", end=FULL_END, interval="1d")
    for t in tickers:
        if raw.get(t) is None or raw[t].empty:
            raise RuntimeError(f"{t} 원본 데이터 없음 — 순열검정 불가")

    window_start = pd.Timestamp(FULL_START)
    window_end = pd.Timestamp(FULL_END)

    results = {}
    for scen_name, bps in PERMUTATION_COST_SCENARIOS.items():
        log(f"순열검정 시작 [{scen_name}] cost_bps/side={bps}, N={N_PERMUTATIONS}")
        rng = np.random.default_rng(SEED if scen_name == "current_0.1pct_rt" else SEED + 1)
        permuted_sharpes = []
        permuted_cagrs = []
        for it in range(N_PERMUTATIONS):
            synth_closes = {}
            for t in tickers:
                synth_df = _shuffle_daily_bars(raw[t], window_start, window_end, rng)
                synth_closes[t] = synth_df["Close"]
            closes_all = pd.DataFrame(synth_closes).sort_index().ffill().dropna()
            closes = closes_all[[t for t in CORE_UNIVERSE if t in closes_all.columns]]
            market_close = closes_all[MARKET_FILTER_TICKER]
            weights_full = _build_core_weights(closes, market_close, apply_market_filter=True)

            sliced_idx = closes.index[(closes.index >= window_start) & (closes.index <= window_end)]
            if len(sliced_idx) < 100:
                continue
            closes_sliced = closes.loc[sliced_idx]
            weights_sliced = weights_full.loc[sliced_idx]
            res = _compute_portfolio_returns(closes_sliced, weights_sliced, cost_bps_per_side=bps)
            m = calculate_metrics(res["equity_net"], [], sliced_idx[0], sliced_idx[-1])
            permuted_sharpes.append(m["sharpe"])
            permuted_cagrs.append(m["cagr"])
            if (it + 1) % 40 == 0:
                log(f"   [{scen_name}] {it + 1}/{N_PERMUTATIONS} 완료 (평균 샤프 {np.mean(permuted_sharpes):.3f})")

        # 실제(비셔플) 지표는 step1_results.json에서 로드
        step1 = json.load(open(OUT_DIR / "step1_results.json", encoding="utf-8"))
        actual_sharpe = step1["core_results"][scen_name]["metrics"]["sharpe"]
        actual_cagr = step1["core_results"][scen_name]["metrics"]["cagr"]

        worse = sum(1 for s in permuted_sharpes if s < actual_sharpe)
        better_eq = sum(1 for s in permuted_sharpes if s >= actual_sharpe)
        percentile = round(100.0 * worse / len(permuted_sharpes), 2)
        p_value = round((better_eq + 1) / (N_PERMUTATIONS + 1), 4)
        log(f"[{scen_name}] 실제 샤프={actual_sharpe} -> 백분위={percentile}, p={p_value}, "
            f"순열평균={np.mean(permuted_sharpes):.3f}(sd={np.std(permuted_sharpes):.3f})")

        results[scen_name] = {
            "cost_bps_per_side": bps,
            "actual_sharpe": actual_sharpe,
            "actual_cagr": actual_cagr,
            "permuted_sharpes": [round(float(s), 4) for s in permuted_sharpes],
            "permuted_mean": round(float(np.mean(permuted_sharpes)), 4),
            "permuted_std": round(float(np.std(permuted_sharpes)), 4),
            "percentile": percentile,
            "p_value": p_value,
            "n_permutations": len(permuted_sharpes),
        }
    return results


def run_block_bootstrap():
    log("블록부트스트랩 시작 (코어/새틀라이트, 비용시나리오별 저장된 ret CSV 재사용)...")
    step1 = json.load(open(OUT_DIR / "step1_results.json", encoding="utf-8"))
    results = {}
    seed_counter = 0
    for sleeve, cost_keys in [("core", step1["core_results"].keys()), ("satellite", step1["satellite_results"].keys())]:
        results[sleeve] = {}
        for cost_name in cost_keys:
            csv_path = OUT_DIR / f"{sleeve}_ret_{cost_name}.csv"
            if not csv_path.exists():
                continue
            ret = pd.read_csv(csv_path, index_col=0, parse_dates=True).iloc[:, 0].dropna().to_numpy()
            actual_sharpe = annualized_sharpe(ret)
            block_results = {}
            for bl in BLOCK_LENGTHS:
                seed_counter += 1
                rng = np.random.default_rng(SEED + seed_counter)
                boot = moving_block_bootstrap_sharpe(ret, bl, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                if len(boot) == 0:
                    continue
                ci_low, ci_high = np.percentile(boot, [2.5, 97.5])
                pct_positive = float(np.mean(boot > 0) * 100)
                block_results[f"block_{bl}"] = {
                    "ci_2.5": round(float(ci_low), 3), "ci_97.5": round(float(ci_high), 3),
                    "pct_bootstrap_sharpe_positive": round(pct_positive, 2),
                    "boot_mean": round(float(np.mean(boot)), 3), "boot_std": round(float(np.std(boot)), 3),
                }
                log(f"   {sleeve}/{cost_name}/L={bl}: 실제샤프={actual_sharpe:.3f}, "
                    f"95%CI=[{ci_low:.3f},{ci_high:.3f}], 부트스트랩샤프>0 비율={pct_positive:.1f}%")
            results[sleeve][cost_name] = {"actual_sharpe": round(float(actual_sharpe), 4), "n_days": len(ret), **block_results}
    return results


def main():
    perm_results = run_core_permutation()
    boot_results = run_block_bootstrap()
    json.dump(
        {"permutation_core": perm_results, "block_bootstrap": boot_results,
         "meta": {"n_permutations": N_PERMUTATIONS, "seed": SEED, "n_boot": N_BOOT, "block_lengths": BLOCK_LENGTHS}},
        open(OUT_DIR / "step2_results.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str,
    )
    log("step2_results.json 저장 완료")


if __name__ == "__main__":
    main()
