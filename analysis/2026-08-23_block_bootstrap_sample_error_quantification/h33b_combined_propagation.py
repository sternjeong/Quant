"""H33b - 가중치 불확실성(H30 디리클레) x 표본오차(H33 블록부트스트랩) 결합 전파.

H30은 6개 창의 Sharpe 점추정치를 고정한 채 "그 6개를 어떻게 가중하느냐"만 흔들었다(디리클레
10,000회). H33(이 스크립트의 자매 스크립트)은 반대로 가중치를 고정한 채 "그 6개 숫자 자체가
표본오차로 얼마나 흔들리는가"만 봤다(창별 블록부트스트랩 2000회).

이 스크립트는 두 불확실성을 동시에 표본추출한다: 매 draw마다
  1. H30과 동일한 시드/방식으로 디리클레 가중치 벡터 하나를 뽑고
  2. 6개 창 각각에서 부트스트랩 Sharpe 분포(L=20 블록길이)에서 하나씩 무작위로 뽑아
  3. 그 조합으로 core_alone / case_a_static_satellite의 기댓값 Sharpe를 계산한다.
10,000 draw를 반복해 "정적보유가 이긴다"는 결론이 두 불확실성을 다 더해도 여전히 강건한지 검증하고,
H30의 가중치-단독 결과와 직접 비교한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parent
H33_RESULTS = OUT_DIR / "h33_results.json"

EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
BASE_RATES = {
    "full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04,
    "bear_2022": 0.10, "selloff_2018": 0.16, "correction_2015_2016": 0.17,
}
K_CENTRAL = 30.0
N_DRAWS = 10000
SEED = 20260823
CONFIGS = ["core_alone", "case_a_static_satellite"]
BLOCK_LEN_FOR_PROPAGATION = "20"  # 중심 블록길이(H30의 K=30과 같은 역할의 "중심" 선택)


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def dirichlet_draws(n: int, rng: np.random.Generator) -> np.ndarray:
    alpha = np.array([BASE_RATES[ep] * K_CENTRAL for ep in EPISODE_ORDER])
    return rng.dirichlet(alpha, size=n)


def weighting_only_ev(draws: np.ndarray, point_sharpe: dict) -> dict:
    """H30과 동일 방식: 점추정치(부트스트랩 평균이 아니라 원 point_estimate_sharpe)만 가중."""
    ev_matrix = {cfg: np.array([point_sharpe[ep][cfg] for ep in EPISODE_ORDER]) for cfg in CONFIGS}
    ev_per_draw = {cfg: draws @ ev_matrix[cfg] for cfg in CONFIGS}
    return ev_per_draw


def sampling_only_ev(boot_by_window: dict, weights_fixed: np.ndarray, n: int, rng: np.random.Generator) -> dict:
    """가중치는 고정(H22 점추정치), 각 창의 Sharpe는 그 창의 부트스트랩 경험분포에서 매 draw 재추출."""
    ev_per_draw = {cfg: np.zeros(n) for cfg in CONFIGS}
    for cfg in CONFIGS:
        # 창별로 부트스트랩 표본(2000개)에서 n개를 복원추출한 뒤, 고정가중치로 합산
        per_ep_samples = []
        for ep in EPISODE_ORDER:
            samples = np.array(boot_by_window[ep]["by_config"][cfg]["_boot_samples"])
            idx = rng.integers(0, len(samples), size=n)
            per_ep_samples.append(samples[idx])
        stacked = np.column_stack(per_ep_samples)  # (n, 6)
        ev_per_draw[cfg] = stacked @ weights_fixed
    return ev_per_draw


def combined_ev(boot_by_window: dict, dir_draws: np.ndarray, n: int, rng: np.random.Generator) -> dict:
    """매 draw: 디리클레 가중치 1개 + 창별 부트스트랩표본 1개씩 동시 추출."""
    ev_per_draw = {cfg: np.zeros(n) for cfg in CONFIGS}
    for cfg in CONFIGS:
        per_ep_samples = []
        for ep in EPISODE_ORDER:
            samples = np.array(boot_by_window[ep]["by_config"][cfg]["_boot_samples"])
            idx = rng.integers(0, len(samples), size=n)
            per_ep_samples.append(samples[idx])
        stacked = np.column_stack(per_ep_samples)  # (n, 6)
        ev_per_draw[cfg] = np.sum(stacked * dir_draws, axis=1)
    return ev_per_draw


def summarize(ev_per_draw: dict) -> dict:
    n = len(next(iter(ev_per_draw.values())))
    stacked = np.column_stack([ev_per_draw[c] for c in CONFIGS])
    winner_idx = np.argmax(stacked, axis=1)
    win_rate = {c: float(np.mean(winner_idx == i)) for i, c in enumerate(CONFIGS)}
    mean_ev = {c: float(np.mean(ev_per_draw[c])) for c in CONFIGS}
    std_ev = {c: float(np.std(ev_per_draw[c])) for c in CONFIGS}
    ci90 = {c: [float(np.percentile(ev_per_draw[c], 5)), float(np.percentile(ev_per_draw[c], 95))] for c in CONFIGS}
    gap = ev_per_draw["case_a_static_satellite"] - ev_per_draw["core_alone"]
    return {
        "win_rate": win_rate, "mean_expected_sharpe": mean_ev, "std_expected_sharpe": std_ev,
        "ci90_expected_sharpe": ci90,
        "gap_static_minus_core": {
            "mean": float(np.mean(gap)),
            "ci90": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
            "pct_draws_static_ahead": float(np.mean(gap > 0)),
        },
    }


def main():
    h33 = load_json(H33_RESULTS)
    boot = h33["bootstrap"]

    # attach raw synthetic bootstrap-sharpe arrays is not saved in h33_results.json (only summary stats
    # were saved to keep the JSON small) - regenerate them deterministically using the same seed/method
    # as h33 so results are reproducible without re-running the expensive backtests.
    import sys
    sys.path.insert(0, str(OUT_DIR))
    from h33_block_bootstrap_sample_error import moving_block_bootstrap_sharpe, N_BOOT, SEED as H33_SEED
    import pandas as pd

    rng_boot = np.random.default_rng(H33_SEED)
    point_sharpe = {}
    boot_samples = {}
    for ep in EPISODE_ORDER:
        point_sharpe[ep] = {}
        boot_samples[ep] = {"by_config": {}}
        for cfg in CONFIGS:
            fname = "core_alone_ret.csv" if cfg == "core_alone" else "case_a_ret.csv"
            s = pd.read_csv(OUT_DIR / f"{ep}_{fname}", index_col=0, parse_dates=True).iloc[:, 0].values.astype(float)
            point_sharpe[ep][cfg] = boot["bootstrap" if False else ep]["by_config"][cfg]["point_estimate_sharpe"] if False else None
            samples = moving_block_bootstrap_sharpe(s, 20, N_BOOT, rng_boot)
            samples = samples[~np.isnan(samples)]
            boot_samples[ep]["by_config"][cfg] = {"_boot_samples": samples.tolist()}
            point_sharpe[ep][cfg] = boot[ep]["by_config"][cfg]["point_estimate_sharpe"]

    rng = np.random.default_rng(SEED)
    dir_draws = dirichlet_draws(N_DRAWS, rng)

    weighting_only = weighting_only_ev(dir_draws, point_sharpe)
    weighting_only_summary = summarize(weighting_only)

    fixed_weights = np.array([BASE_RATES[ep] for ep in EPISODE_ORDER])
    fixed_weights = fixed_weights / fixed_weights.sum()
    sampling_only = sampling_only_ev(boot_samples, fixed_weights, N_DRAWS, rng)
    sampling_only_summary = summarize(sampling_only)

    combined = combined_ev(boot_samples, dir_draws, N_DRAWS, rng)
    combined_summary = summarize(combined)

    out = {
        "meta": {"n_draws": N_DRAWS, "seed": SEED, "block_len_used": BLOCK_LEN_FOR_PROPAGATION,
                 "episode_order": EPISODE_ORDER, "configs": CONFIGS},
        "weighting_only_H30_style": weighting_only_summary,
        "sampling_only_bootstrap": sampling_only_summary,
        "combined_weighting_x_sampling": combined_summary,
        "per_window_point_sharpe": point_sharpe,
    }
    (OUT_DIR / "h33b_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[h33b] saved h33b_results.json")
    print("weighting-only win_rate(static):", weighting_only_summary["win_rate"]["case_a_static_satellite"])
    print("sampling-only  win_rate(static):", sampling_only_summary["win_rate"]["case_a_static_satellite"])
    print("combined       win_rate(static):", combined_summary["win_rate"]["case_a_static_satellite"])
    print("weighting-only CI90 gap:", weighting_only_summary["gap_static_minus_core"]["ci90"])
    print("sampling-only  CI90 gap:", sampling_only_summary["gap_static_minus_core"]["ci90"])
    print("combined       CI90 gap:", combined_summary["gap_static_minus_core"]["ci90"])


if __name__ == "__main__":
    main()
