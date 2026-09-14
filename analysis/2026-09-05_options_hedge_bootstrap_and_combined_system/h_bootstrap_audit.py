"""H_bootstrap - 옵션 헤지(작업48) 결론에 H33 블록부트스트랩 감사를 적용.

작업48의 옵션 테일헤지 리포트(synthetic_options_tail_hedge_research.html)는 COVID 2020 구간에서
칼라가 무헤지 새틀라이트/코어단독/최선 트렌드 하이브리드를 모두 이겼다고 결론냈지만, 이 결론은
이 연구 프로그램의 다른 모든 주요 결론과 달리 H33 블록부트스트랩 표본오차 감사를 거친 적이 없다.
이 스크립트는 H33의 정확한 방법론(순환 이동블록부트스트랩, L=10/20/40 블록길이 중심 20, 창당/구성당
2000회 리샘플)을 옵션 헤지의 3개 구성(무헤지 새틀라이트, 풋헤지, 칼라헤지) x 6개 창에 그대로
적용한다. h_options_hedge.py의 run_episode()를 그대로 재사용해 일별수익률 시계열을 재계산한다
(재구현하지 않음).

이어서 H33b의 결합전파(디리클레 가중치불확실성 x 블록부트스트랩 표본오차, 10,000 draw)를
"칼라 vs 무헤지", "풋 vs 무헤지" 갭에 적용해 승률 및 신뢰구간을 산출한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-30_synthetic_options_tail_hedge"))

import numpy as np
import pandas as pd

import h_options_hedge as hh

OUT_DIR = Path(__file__).resolve().parent

EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
CONFIGS = ["core_alone", "unhedged_satellite", "protective_put", "collar"]
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
TRADING_DAYS = 252
SEED = 20260905

BASE_RATES = {
    "base": {"full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04, "bear_2022": 0.10,
             "selloff_2018": 0.16, "correction_2015_2016": 0.17},
    "calm_heavy": {"full_2019_2026": 0.65, "gfc_2008": 0.015, "covid_2020": 0.02, "bear_2022": 0.065,
                   "selloff_2018": 0.12, "correction_2015_2016": 0.13},
    "crisis_heavy": {"full_2019_2026": 0.35, "gfc_2008": 0.06, "covid_2020": 0.07, "bear_2022": 0.14,
                     "selloff_2018": 0.19, "correction_2015_2016": 0.19},
}
K_CENTRAL = 30.0
N_DRAWS = 10000


def log(msg):
    print(f"[boot] {msg}", flush=True)


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
    ext = np.concatenate([ret, ret])
    sharpes = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks_needed)
        pieces = [ext[s:s + block_len] for s in starts]
        synth = np.concatenate(pieces)[:n]
        sharpes[b] = annualized_sharpe(synth)
    return sharpes


def slice_window(s: pd.Series, start: str, end: str) -> pd.Series:
    return s[(s.index >= start) & (s.index <= end)]


def gather_window_returns() -> dict:
    """h_options_hedge의 h20 캐시된 시리즈를 재사용해 6개 창 x 4구성의 일별수익률(윈도우 슬라이스)을 만든다."""
    series = hh.load_h20_series()
    h20 = hh.load_h20_results()
    out = {}
    for label in EPISODE_ORDER:
        log(f"  {label}: 옵션 오버레이 재계산")
        ep_returns = hh.run_episode(label, series, put_moneyness=1.00, call_moneyness=1.05)
        h20_ep = h20["episodes"][label]
        crisis_start, crisis_end = h20_ep["crisis_window"]
        full_start, full_end = h20_ep["full_period"]
        wkey = "full_period" if label == "full_2019_2026" else "crisis_window"
        w_start, w_end = (full_start, full_end) if wkey == "full_period" else (crisis_start, crisis_end)

        cfg_series = {
            "core_alone": ep_returns["core_ret"],
            "unhedged_satellite": ep_returns["unhedged_blend"],
            "protective_put": ep_returns["put_hedged_blend"],
            "collar": ep_returns["collar_hedged_blend"],
        }
        windowed = {cfg: slice_window(s, w_start, w_end) for cfg, s in cfg_series.items()}
        out[label] = {"window_used": [w_start, w_end], "wkey": wkey,
                       "n_obs": int(len(windowed["core_alone"])), "series": windowed}
        log(f"  {label}: window={w_start}~{w_end} ({wkey}), n_obs={out[label]['n_obs']}")
    return out


def bootstrap_all(window_returns: dict) -> tuple[dict, dict]:
    """returns (summary_json, raw_boot_samples[ep][cfg] -> np.array for L=20)"""
    rng = np.random.default_rng(SEED)
    summary = {}
    raw20 = {}
    for label, d in window_returns.items():
        summary[label] = {"window_used": d["window_used"], "n_obs": d["n_obs"], "by_config": {}}
        raw20[label] = {}
        for cfg in CONFIGS:
            ret = d["series"][cfg].values.astype(float)
            point_sharpe = annualized_sharpe(ret)
            per_block = {}
            for L in BLOCK_LENGTHS:
                boot = moving_block_bootstrap_sharpe(ret, L, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                if len(boot) == 0:
                    per_block[str(L)] = None
                    continue
                per_block[str(L)] = {
                    "block_len": L, "n_boot_valid": int(len(boot)),
                    "n_nonoverlapping_blocks_approx": round(d["n_obs"] / L, 1),
                    "mean": float(np.mean(boot)), "std": float(np.std(boot)),
                    "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
                    "ci50": [float(np.percentile(boot, 25)), float(np.percentile(boot, 75))],
                }
                if L == 20:
                    raw20[label][cfg] = boot
            summary[label]["by_config"][cfg] = {
                "point_estimate_sharpe": point_sharpe, "n_obs": d["n_obs"],
                "bootstrap_by_block_len": per_block,
            }
            log(f"  {label}/{cfg}: point={point_sharpe:.3f} L20_CI90={per_block.get('20', {}).get('ci90')}")
    return summary, raw20


def dirichlet_draws(scenario: str, n: int, rng: np.random.Generator) -> np.ndarray:
    rates = BASE_RATES[scenario]
    alpha = np.array([rates[ep] * K_CENTRAL for ep in EPISODE_ORDER])
    return rng.dirichlet(alpha, size=n)


def combined_gap_analysis(boot_summary: dict, raw20: dict) -> dict:
    """디리클레 가중치(3개 시나리오) x 블록부트스트랩(L=20) 결합전파 - 칼라 vs 무헤지, 풋 vs 무헤지."""
    rng = np.random.default_rng(SEED + 1)
    out = {}
    pairs = [("collar", "unhedged_satellite"), ("protective_put", "unhedged_satellite")]
    for scenario in BASE_RATES:
        dir_draws = dirichlet_draws(scenario, N_DRAWS, rng)
        out[scenario] = {}
        for cfg_a, cfg_b in pairs:
            ev_a = np.zeros(N_DRAWS)
            ev_b = np.zeros(N_DRAWS)
            for i, ep in enumerate(EPISODE_ORDER):
                samples_a = raw20[ep][cfg_a]
                samples_b = raw20[ep][cfg_b]
                idx_a = rng.integers(0, len(samples_a), size=N_DRAWS)
                idx_b = rng.integers(0, len(samples_b), size=N_DRAWS)
                ev_a += dir_draws[:, i] * samples_a[idx_a]
                ev_b += dir_draws[:, i] * samples_b[idx_b]
            gap = ev_a - ev_b
            out[scenario][f"{cfg_a}_vs_{cfg_b}"] = {
                "mean_gap": float(np.mean(gap)),
                "ci90_gap": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
                "pct_draws_a_ahead": float(np.mean(gap > 0)),
                "mean_ev_a": float(np.mean(ev_a)), "mean_ev_b": float(np.mean(ev_b)),
            }
            log(f"  combined[{scenario}] {cfg_a} vs {cfg_b}: win_rate(a)={out[scenario][f'{cfg_a}_vs_{cfg_b}']['pct_draws_a_ahead']:.3f} "
                f"CI90_gap={out[scenario][f'{cfg_a}_vs_{cfg_b}']['ci90_gap']}")
    return out


def covid_specific_note(boot_summary: dict) -> dict:
    covid = boot_summary["covid_2020"]
    return {
        "n_obs": covid["n_obs"],
        "by_config": {cfg: {
            "point_sharpe": covid["by_config"][cfg]["point_estimate_sharpe"],
            "L20_ci90": covid["by_config"][cfg]["bootstrap_by_block_len"]["20"]["ci90"] if covid["by_config"][cfg]["bootstrap_by_block_len"]["20"] else None,
            "L40_ci90": covid["by_config"][cfg]["bootstrap_by_block_len"]["40"]["ci90"] if covid["by_config"][cfg]["bootstrap_by_block_len"]["40"] else None,
        } for cfg in CONFIGS},
    }


def main():
    t0 = time.time()
    window_returns = gather_window_returns()

    for label, d in window_returns.items():
        for cfg, s in d["series"].items():
            s.to_csv(OUT_DIR / f"{label}_{cfg}_ret.csv", header=["ret"])

    boot_summary, raw20 = bootstrap_all(window_returns)
    combined = combined_gap_analysis(boot_summary, raw20)
    covid_note = covid_specific_note(boot_summary)

    out = {
        "meta": {"n_boot": N_BOOT, "seed": SEED, "block_lengths": BLOCK_LENGTHS,
                 "trading_days": TRADING_DAYS, "episode_order": EPISODE_ORDER,
                 "configs": CONFIGS, "n_draws_combined": N_DRAWS, "base_rate_scenarios": BASE_RATES},
        "bootstrap": boot_summary,
        "combined_dirichlet_x_bootstrap": combined,
        "covid_specific_note": covid_note,
    }
    (OUT_DIR / "h_bootstrap_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"저장 완료: h_bootstrap_results.json ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
