"""H30 - 기저확률 가정의 몬테카를로 민감도 검증.

작업39(H22)는 6개 레짐 아키타입(평시/2008형/COVID형/2022형/2018형/2015-16형)의 연간 발생빈도를
"점추정치"로 고정한 뒤, 3개의 손으로 고른 대안 시나리오(기본/평온중시/위기중시)만으로 순위
안정성을 확인했다. 이번 라운드는 그 기저확률 자체를 진짜 불확실한 확률벡터로 취급하고, 디리클레
분포에서 대량으로 무작위 표본을 뽑아(5000~10000회) 각 표본마다 6개 창의 기존 Sharpe/CAGR 원자료를
재가중해 기댓값 순위가 얼마나 자주 뒤집히는지를 정직하게 측정한다.

새 백테스트는 전혀 하지 않는다 - 이미 존재하는 h22/h26/h27/h28/h29의 raw_lookup_table(창 x 구성 x
{sharpe,cagr,mdd})만 재사용하는 순수 통계/시뮬레이션 스크립트다.

불확실성 분포 설계
-------------------
6개 아키타입 발생확률을 하나의 확률벡터(합=1)로 보고, 디리클레(Dirichlet) 분포
    p ~ Dirichlet(alpha),  alpha_i = K * base_rate_i
를 사용한다. K(총 집중도, "가상 관측표본 크기"로 해석 가능)가 클수록 분포가 H22의 점추정치 주변에
좁게 몰리고, 작을수록 넓게 퍼진다. 디리클레 성분의 분산은 해석적으로
    Var(p_i) = alpha_i (K - alpha_i) / (K^2 (K+1))
이다. 예컨대 gfc_2008의 점추정치 3%에서 K=30이면 alpha_i=0.9, std(p_i) ≈ 3.06%p - 즉 표준편차가
점추정치와 같은 크기(변동계수 ~100%)여서 "실제 발생확률이 점추정치의 절반일 수도, 두 배일 수도
있다"는 정도의 폭넓은(하지만 극단적이지 않은) 불확실성을 반영한다. 위기형 아키타입(연 3~4회 정도만
"관측"되는 드문 사건)은 원래 통계적으로 추정이 어렵다는 점(bear-market frequency 연구들도 표본기간·
정의에 따라 8~20% 사이로 크게 갈린다 - 예: Ned Davis Research/Yardeni 계열 집계에서 S&P500 -20%
이상 약세장은 1928년 이후 약 5.5년에 한 번, 두 자릿수 조정(-10%~-20%)은 훨씬 더 빈번하다는 서로
다른 정의가 혼재)을 고려하면 이 정도 폭은 과도한 것이 아니라 오히려 최소한의 정직한 표현이다.

중심(K=30) 시나리오 외에, 더 좁은 확신(K=60, "점추정치를 상당히 신뢰")과 더 넓은 불확실성
(K=15, "거의 무지에 가까운 사전지식")도 함께 돌려 결론이 K 선택 자체에 얼마나 민감한지도 함께
보고한다 - 이것이 "3개 시나리오"를 "진짜 분포"로 대체하는 이번 라운드의 핵심이다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

MAIN_CHECKOUT = "/workspaces/Quant"
OUT_DIR = Path(__file__).resolve().parent

H22_PATH = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/h22_results.json"
H26_PATH = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_system_vs_buyhold_and_lookback_robustness/h26_results.json"
H27_PATH = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_system_vs_buyhold_and_lookback_robustness/h27_results.json"
H28_PATH = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_vol_targeting_and_rebalance_frequency_expected_value/h28_results.json"
H29_PATH = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_vol_targeting_and_rebalance_frequency_expected_value/h29_results.json"

EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]

# H22 base rates (== 작업39 point estimates), used as the Dirichlet prior mean for ALL hypotheses
# (H22/H26/H27/H28/H29 all share the same 6 episode windows / regime archetypes).
BASE_RATES = {
    "full_2019_2026": 0.50,
    "gfc_2008": 0.03,
    "covid_2020": 0.04,
    "bear_2022": 0.10,
    "selloff_2018": 0.16,
    "correction_2015_2016": 0.17,
}

N_DRAWS = 10000
SEED = 20260823
K_SCENARIOS = {"tight_K60": 60.0, "central_K30": 30.0, "wide_K15": 15.0}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dirichlet_draws(base_rates: dict, k: float, n: int, rng: np.random.Generator) -> np.ndarray:
    """Return (n, 6) array of probability vectors in EPISODE_ORDER, drawn from Dirichlet(K*base_rate)."""
    alpha = np.array([base_rates[ep] * k for ep in EPISODE_ORDER])
    return rng.dirichlet(alpha, size=n)


def build_ev_matrix(raw_lookup: dict, configs: list, metric: str) -> dict:
    """cfg -> np.array of length 6 (in EPISODE_ORDER) with the metric value per episode."""
    out = {}
    for cfg in configs:
        vals = []
        for ep in EPISODE_ORDER:
            m = raw_lookup.get(ep, {}).get(cfg)
            vals.append(m[metric] if m is not None else np.nan)
        out[cfg] = np.array(vals, dtype=float)
    return out


def monte_carlo_hypothesis(raw_lookup: dict, configs: list, draws: np.ndarray, metric: str = "sharpe") -> dict:
    """draws: (n,6) prob vectors. Returns per-draw expected metric per config + rank stats."""
    ev_matrix = build_ev_matrix(raw_lookup, configs, metric)
    n = draws.shape[0]
    ev_per_draw = {cfg: draws @ ev_matrix[cfg] for cfg in configs}
    stacked = np.column_stack([ev_per_draw[cfg] for cfg in configs])  # (n, n_configs)
    ranks = np.argsort(-stacked, axis=1)
    winner_idx = ranks[:, 0]
    win_counts = {cfg: int(np.sum(winner_idx == i)) for i, cfg in enumerate(configs)}
    win_rate = {cfg: win_counts[cfg] / n for cfg in configs}

    rank_position = np.argsort(np.argsort(-stacked, axis=1), axis=1)  # 0 = best
    rank_dist = {}
    for i, cfg in enumerate(configs):
        counts = np.bincount(rank_position[:, i], minlength=len(configs))
        rank_dist[cfg] = (counts / n).tolist()

    mean_ev = {cfg: float(np.mean(ev_per_draw[cfg])) for cfg in configs}
    std_ev = {cfg: float(np.std(ev_per_draw[cfg])) for cfg in configs}
    ci90 = {cfg: [float(np.percentile(ev_per_draw[cfg], 5)), float(np.percentile(ev_per_draw[cfg], 95))]
            for cfg in configs}

    overall_winner = max(configs, key=lambda c: mean_ev[c])
    rival = max((c for c in configs if c != overall_winner), key=lambda c: mean_ev[c])
    gap = ev_per_draw[overall_winner] - ev_per_draw[rival]
    gap_stats = {
        "winner": overall_winner, "rival": rival,
        "mean_gap": float(np.mean(gap)),
        "ci90_gap": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
        "pct_draws_winner_still_ahead": float(np.mean(gap > 0)),
    }

    return {
        "configs": configs,
        "win_count": win_counts,
        "win_rate": win_rate,
        "rank_distribution": rank_dist,
        "mean_expected_value": mean_ev,
        "std_expected_value": std_ev,
        "ci90_expected_value": ci90,
        "gap_winner_vs_rival": gap_stats,
    }


def run_all_k(raw_lookup: dict, configs: list, metric: str, rng: np.random.Generator) -> dict:
    out = {}
    for k_name, k_val in K_SCENARIOS.items():
        draws = dirichlet_draws(BASE_RATES, k_val, N_DRAWS, rng)
        out[k_name] = {"K": k_val, **monte_carlo_hypothesis(raw_lookup, configs, draws, metric)}
    return out


def main():
    rng = np.random.default_rng(SEED)

    h22 = load_json(H22_PATH)
    h26 = load_json(H26_PATH)
    h27 = load_json(H27_PATH)
    h28 = load_json(H28_PATH)
    h29 = load_json(H29_PATH)

    result = {
        "meta": {
            "n_draws": N_DRAWS, "seed": SEED, "base_rates": BASE_RATES,
            "k_scenarios": K_SCENARIOS,
            "episode_order": EPISODE_ORDER,
        },
        "h22_config_comparison": run_all_k(
            h22["raw_lookup_table"], h22["config_order"], "sharpe", rng),
        "h26_system_vs_spy": run_all_k(
            h26["raw_lookup_table"], ["spy_buyhold", "core_alone", "core_plus_satellite"], "sharpe", rng),
        "h27_lookback": run_all_k(
            h27["raw_lookup_table"], ["3", "6", "9", "12", "15", "18"], "sharpe", rng),
        "h28_vol_targeting": run_all_k(
            h28["raw_lookup_table"], ["no_overlay", "vol_targeted"], "sharpe", rng),
        "h29_rebalance_freq": run_all_k(
            h29["raw_lookup_table"], list(h29["frequencies"].keys()), "sharpe", rng),
    }

    (OUT_DIR / "h30_results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[h30] saved h30_results.json")

    for hyp_name in ["h22_config_comparison", "h26_system_vs_spy", "h27_lookback", "h28_vol_targeting", "h29_rebalance_freq"]:
        print(f"\n=== {hyp_name} ===")
        for k_name in K_SCENARIOS:
            r = result[hyp_name][k_name]
            top = max(r["win_rate"].items(), key=lambda kv: kv[1])
            gap = r["gap_winner_vs_rival"]
            print(f"  {k_name}: top-win-rate cfg={top[0]} ({top[1]*100:.1f}%) | "
                  f"gap {gap['winner']} vs {gap['rival']}: mean={gap['mean_gap']:.4f} "
                  f"90%CI=[{gap['ci90_gap'][0]:.4f},{gap['ci90_gap'][1]:.4f}] "
                  f"P(winner ahead)={gap['pct_draws_winner_still_ahead']*100:.1f}%")


if __name__ == "__main__":
    main()
