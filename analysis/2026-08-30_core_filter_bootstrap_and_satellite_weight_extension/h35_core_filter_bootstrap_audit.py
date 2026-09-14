"""H35 - H25(코어 이진 시장필터 with/without) 판정에 H33/H34식 블록부트스트랩 신뢰도 감사를 적용.

H25(작업39-46 라운드, analysis/2026-08-23_satellite_weight_and_core_filter_expected_value/
h25_core_filter_expected_value.py)는 챔피언의 SPY<200SMA 이진 시장필터를 제거한 without_filter가
6개 창 기저확률가중 기댓값에서 base/calm_heavy/crisis_heavy 세 시나리오 모두 with_filter(현재
챔피언 기본값)를 이겼다고 결론지었다. 하지만 H25는 점추정(point estimate)만 사용했고, H33/H34가
H22/H26/H28/H32에 적용한 표본오차(sampling uncertainty) 감사를 받은 적이 없다.

이 스크립트는 H34(analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/
h34_bootstrap_audit_remaining_verdicts.py)의 방법론을 그대로 재사용한다:
  - 순환 이동블록부트스트랩(circular moving block bootstrap), 블록길이 L=10/20/40일(중심 20일),
    창x설정당 2000회 재표본, SEED=20260823(H33/H34와 동일 시드 계열 이어감).
  - H22/H30식 디리클레 기저확률 가중치 재표본(K=30, base 시나리오, 10000 draws)과 결합 전파해
    "combined win rate"를 산출.
  - H34의 unified table에 6번째 행으로 추가할 수 있는 동일 스키마의 출력을 만든다.

일별수익률 시계열: h25_core_filter_expected_value.py는 요약지표만 저장했으므로(daily return
series를 저장하지 않음), champion_strategy.run_champion을 6개 창 x 필터ON/OFF 각 1회씩 재실행해
ret_net을 새로 확보한다(h25와 완전히 동일한 코드/유니버스/날짜 재사용 -- run_champion은 결정적
백테스트라 h25가 낸 요약지표와 여기서 재계산한 요약지표가 일치하는지 검증용으로도 대조한다).

부트스트랩에 사용하는 슬라이스는 H22/expected_value_weighting.py의 관례와 동일: full_2019_2026은
전체기간 시계열, 나머지 5개 창은 각자의 위기 서브윈도우 시계열(H34가 WINDOWS에서 쓴 것과 동일한
슬라이스 정의).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))

import numpy as np
import pandas as pd

from champion_strategy import run_champion, CHAMPION_UNIVERSE  # noqa: E402
from core.backtest_engine import calculate_metrics  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
THREE_ASSET_UNIVERSE = ["SPY", "TLT", "GLD"]

# H25와 완전히 동일 (label -> full_start, full_end, crisis_start, crisis_end, universe)
WINDOWS_FULL = {
    "full_2019_2026": ("2019-08-12", "2026-08-19", None, None, CHAMPION_UNIVERSE),
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30", THREE_ASSET_UNIVERSE),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30", CHAMPION_UNIVERSE),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31", CHAMPION_UNIVERSE),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15", CHAMPION_UNIVERSE),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15", CHAMPION_UNIVERSE),
}
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
SEED = 20260823
TRADING_DAYS = 252

BASE_RATES = {
    "full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04,
    "bear_2022": 0.10, "selloff_2018": 0.16, "correction_2015_2016": 0.17,
}
K_CENTRAL = 30.0
N_DRAWS = 10000


def log(msg):
    print(f"[h35] {msg}", flush=True)


def perf_metrics_slice(ret: pd.Series, start: str, end: str) -> dict:
    sliced = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if len(sliced) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "calmar": None, "n_days": len(sliced)}
    eq = (1 + sliced.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
    m["n_days"] = int(len(sliced))
    return m


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
    max_start = n
    sharpes = np.empty(n_boot)
    ext = np.concatenate([ret, ret])
    for b in range(n_boot):
        starts = rng.integers(0, max_start, size=n_blocks_needed)
        pieces = [ext[s:s + block_len] for s in starts]
        synth = np.concatenate(pieces)[:n]
        sharpes[b] = annualized_sharpe(synth)
    return sharpes


def build_filter_returns() -> tuple[dict, dict]:
    """(daily_ret_series, summary_metrics) 반환. daily_ret_series[ep][cfg] = pd.Series (평가 슬라이스).
    summary_metrics[ep][cfg] = h25와 동일 스키마의 지표 dict (검증용 대조)."""
    daily = {}
    summary = {}
    shared = {}
    t0 = time.time()
    for label, (fs, fe, cs, ce, universe) in WINDOWS_FULL.items():
        cache_key = (tuple(universe), fs, fe)
        if cache_key in shared:
            log(f"{label}: 원시데이터 재사용 ({fs}~{fe})")
            with_f, without_f = shared[cache_key]
        else:
            log(f"{label}: 코어 실행 {fs}~{fe} ({len(universe)}자산, 필터 ON/OFF)")
            with_f = run_champion(fs, fe, tickers=universe, apply_market_filter=True)
            without_f = run_champion(fs, fe, tickers=universe, apply_market_filter=False)
            shared[cache_key] = (with_f, without_f)

        use_crisis = cs is not None
        eval_start, eval_end = (cs, ce) if use_crisis else (fs, fe)
        daily[label] = {
            "with_filter": with_f["ret_net"][(with_f["ret_net"].index >= pd.Timestamp(eval_start)) &
                                              (with_f["ret_net"].index <= pd.Timestamp(eval_end))],
            "without_filter": without_f["ret_net"][(without_f["ret_net"].index >= pd.Timestamp(eval_start)) &
                                                    (without_f["ret_net"].index <= pd.Timestamp(eval_end))],
        }
        summary[label] = {
            "with_filter": perf_metrics_slice(with_f["ret_net"], eval_start, eval_end),
            "without_filter": perf_metrics_slice(without_f["ret_net"], eval_start, eval_end),
        }
        daily[label]["with_filter"].to_frame("ret").to_csv(OUT_DIR / f"{label}_with_filter_ret.csv")
        daily[label]["without_filter"].to_frame("ret").to_csv(OUT_DIR / f"{label}_without_filter_ret.csv")
        log(f"  {label} eval=[{eval_start},{eval_end}] sharpe with={summary[label]['with_filter']['sharpe']} "
            f"without={summary[label]['without_filter']['sharpe']} t={time.time()-t0:.1f}s")
    return daily, summary


def bootstrap_comparison(window_series: dict, configs: list[str], rng: np.random.Generator) -> tuple[dict, dict]:
    out = {}
    boot_samples_l20 = {ep: {} for ep in window_series}
    for ep, d in window_series.items():
        out[ep] = {"n_obs": {}, "by_config": {}}
        for cfg in configs:
            ret = d[cfg].values.astype(float)
            out[ep]["n_obs"][cfg] = int(len(ret))
            point_sharpe = annualized_sharpe(ret)
            per_block = {}
            for L in BLOCK_LENGTHS:
                boot = moving_block_bootstrap_sharpe(ret, L, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                if L == 20:
                    boot_samples_l20[ep][cfg] = boot.tolist()
                if len(boot) == 0:
                    per_block[str(L)] = None
                    continue
                per_block[str(L)] = {
                    "block_len": L, "n_boot_valid": int(len(boot)),
                    "n_nonoverlapping_blocks_approx": round(len(ret) / L, 1),
                    "mean": float(np.mean(boot)), "std": float(np.std(boot)),
                    "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
                    "ci50": [float(np.percentile(boot, 25)), float(np.percentile(boot, 75))],
                }
            out[ep]["by_config"][cfg] = {
                "point_estimate_sharpe": point_sharpe,
                "bootstrap_by_block_len": per_block,
            }
            log(f"  bootstrap {ep}/{cfg}: point={point_sharpe:.3f}, n_obs={len(ret)}, "
                f"L=20 CI90={per_block.get('20', {}).get('ci90')}")
    return out, boot_samples_l20


def dirichlet_draws(n: int, rng: np.random.Generator) -> np.ndarray:
    alpha = np.array([BASE_RATES[ep] * K_CENTRAL for ep in EPISODE_ORDER])
    return rng.dirichlet(alpha, size=n)


def combined_propagation(boot_l20: dict, point_sharpe: dict, cfg_a: str, cfg_b: str, rng: np.random.Generator) -> dict:
    """cfg_b(챌린저) vs cfg_a(베이스라인)."""
    dir_draws = dirichlet_draws(N_DRAWS, rng)

    def draw_ev(cfg):
        per_ep_samples = []
        for ep in EPISODE_ORDER:
            samples = np.array(boot_l20[ep][cfg])
            idx = rng.integers(0, len(samples), size=N_DRAWS)
            per_ep_samples.append(samples[idx])
        stacked = np.column_stack(per_ep_samples)
        return np.sum(stacked * dir_draws, axis=1)

    ev_a = draw_ev(cfg_a)
    ev_b = draw_ev(cfg_b)
    gap = ev_b - ev_a
    win_rate_b = float(np.mean(ev_b > ev_a))

    ev_matrix_a = np.array([point_sharpe[ep][cfg_a] for ep in EPISODE_ORDER])
    ev_matrix_b = np.array([point_sharpe[ep][cfg_b] for ep in EPISODE_ORDER])
    weighting_only_a = dir_draws @ ev_matrix_a
    weighting_only_b = dir_draws @ ev_matrix_b
    weighting_only_win_rate_b = float(np.mean(weighting_only_b > weighting_only_a))

    fixed_w = np.array([BASE_RATES[ep] for ep in EPISODE_ORDER])
    fixed_w = fixed_w / fixed_w.sum()

    def draw_ev_fixed(cfg):
        per_ep_samples = []
        for ep in EPISODE_ORDER:
            samples = np.array(boot_l20[ep][cfg])
            idx = rng.integers(0, len(samples), size=N_DRAWS)
            per_ep_samples.append(samples[idx])
        stacked = np.column_stack(per_ep_samples)
        return stacked @ fixed_w

    sampling_only_a = draw_ev_fixed(cfg_a)
    sampling_only_b = draw_ev_fixed(cfg_b)
    sampling_only_win_rate_b = float(np.mean(sampling_only_b > sampling_only_a))

    return {
        "cfg_baseline": cfg_a, "cfg_challenger": cfg_b,
        "weighting_only_win_rate_challenger": weighting_only_win_rate_b,
        "sampling_only_win_rate_challenger": sampling_only_win_rate_b,
        "combined_win_rate_challenger": win_rate_b,
        "combined_gap_challenger_minus_baseline": {
            "mean": float(np.mean(gap)),
            "ci90": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
        },
        "combined_mean_expected_sharpe": {cfg_a: float(np.mean(ev_a)), cfg_b: float(np.mean(ev_b))},
    }


def main():
    t0 = time.time()
    log("=== 필터 ON/OFF 일별수익률 재구성 (h25와 동일 코드, 재검증용) ===")
    daily, summary = build_filter_returns()

    rng = np.random.default_rng(SEED)
    boot, samples_l20 = bootstrap_comparison(daily, ["with_filter", "without_filter"], rng)

    point = {ep: {cfg: boot[ep]["by_config"][cfg]["point_estimate_sharpe"] for cfg in ["with_filter", "without_filter"]}
             for ep in EPISODE_ORDER}

    rng2 = np.random.default_rng(SEED + 1)
    # H25 결론이 without_filter가 이긴다는 것이므로, without_filter를 챌린저로 둔다
    combined = combined_propagation(samples_l20, point, "with_filter", "without_filter", rng2)

    log(f"H35 without_filter vs with_filter combined win_rate(without_filter)="
        f"{combined['combined_win_rate_challenger']:.3f}")
    log(f"  weighting_only={combined['weighting_only_win_rate_challenger']:.3f} "
        f"sampling_only={combined['sampling_only_win_rate_challenger']:.3f}")

    out = {
        "meta": {
            "n_boot": N_BOOT, "n_draws": N_DRAWS, "seed": SEED, "block_lengths": BLOCK_LENGTHS,
            "trading_days": TRADING_DAYS, "episode_order": EPISODE_ORDER, "k_central": K_CENTRAL,
            "base_rates": BASE_RATES,
        },
        "h25_recomputed_summary_metrics": summary,
        "bootstrap_h25_core_filter": boot,
        "combined_h25_without_filter_vs_with_filter": combined,
        "total_runtime_sec": round(time.time() - t0, 1),
    }
    (OUT_DIR / "h35_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"저장 완료: h35_results.json, 총 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
