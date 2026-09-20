"""H37 - H32(17라운드) 정밀 그리드 우승 후보(14~16개월 룩백 + 분기 리밸런싱)의 첫 블록부트스트랩 감사.

배경: H32(작업44, `analysis/2026-08-23_champion_parameter_fine_resolution_and_satellite_joint/`)는
룩백 9~18개월 x 리밸런싱 4주기 = 40칸 정밀 그리드에서 14~16개월+분기가 샤프 격차 0.01~0.014
안에 들어오는 "완만한 고원"이라고 보고했다(정밀 정점은 시나리오별로 14개월 또는 16개월로 흔들림).
H34(작업45, `analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/`)는 H32의 권고
중 "리밸런싱만 분기로 바꾼다"(룩백은 12개월 고정)는 부분만 블록부트스트랩으로 감사해 분기vs월간
승률이 49.6%(사실상 동전던지기)로 무너진다는 걸 보였다. 하지만 **H32 그리드 자체가 찾은 결합
우승점(룩백도 같이 14~16개월로 바꾸는 조합)은 지금까지 한 번도 표본오차 감사를 받지 않았다** —
리서치 에이전트 B 페르소나가 명시한 "아직 안 풀린 문제" 2번이 정확히 이것이다.

이 스크립트는 H33/H34와 동일한 방법론(순환 이동블록부트스트랩, 블록길이 10/20/40일, 창당 2,000회
재표본, 디리클레(K=30) 가중치 결합전파)을 다음 4개 가설에 적용한다:

  H1 (재현성 확인): 14/15/16개월+분기 조합을 이번 세션이 직접 재실행한 점추정치가 H32가 저장한
     `h32_stage1_results.json`의 값과 정확히 일치하는지 확인(코드 무변경, 순수 재현성 검증).
  H2 (블록부트스트랩 vs 현재 기본값): 12개월/월간(현재 `core/champion_strategy.py` 라이브 기본값과
     동일) 대비 14/15/16개월+분기 각각의 승률을 가중치만 반영 vs 표본오차만 반영 vs 결합전파로
     3단계 비교.
  H3 (분기전환 단독효과와 분리): H34가 이미 감사한 "12개월+분기"(리밸런싱만 바꾼 경우, 그 자체로는
     반전/미지지 판정)를 두 번째 기준선으로 놓고, "룩백까지 같이 바꾸는 것"이 분기전환 단독보다
     추가 가치를 내는지 검정.
  H4 (그리드 전수 백분위 — 플라시보 대용): H32가 이미 계산해 둔 40칸 전수 그리드(무작위 표집이
     아니라 그 자체가 전체 모집단)에서, 14/15/16개월+분기가 3개 기저확률 시나리오 각각에서 실제로
     몇 위인지 재확인 — "완만한 고원"이라는 서술이 숫자로도 얼마나 완만한지 정량화.

데이터 재구성 방식(재계산 최소화):
  - 12개월/월간, 12개월/분기 일별수익률: H34가 이미 저장해 둔
    `analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/{ep}_{monthly_21d,quarterly_63d}_ret.csv`
    를 그대로 재사용(재백테스트 없음).
  - 14/15/16개월/분기 일별수익률: H32의 `run_champion_joint()`를 그대로 재사용해 6개 창 x 3개
    룩백 = 18회 신규 백테스트(코드 재작성 없음, 파라미터만 대입).
  - 40칸 전수 그리드 순위: H32의 `h32_stage1_results.json`을 그대로 로드(재계산 없음).

블록부트스트랩 설계는 H33/H34와 완전히 동일(같은 코드를 이 스크립트 안에 그대로 복제 — 새
알고리즘 발명 없음), SEED만 이번 세션 시작일(20260917)로 갱신.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
H32_DIR = WORKTREE_ROOT / "analysis" / "2026-08-23_champion_parameter_fine_resolution_and_satellite_joint"
H34_DIR = WORKTREE_ROOT / "analysis" / "2026-08-24_bootstrap_confidence_audit_remaining_verdicts"
CHAMPION_DIR = WORKTREE_ROOT / "analysis" / "2026-08-19_champion_beta_and_satellite_research"

sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, str(CHAMPION_DIR))
sys.path.insert(0, str(H32_DIR))

import numpy as np
import pandas as pd

from h32_fine_grid_and_satellite_joint import run_champion_joint  # noqa: E402
from h32_fine_grid_and_satellite_joint import SCENARIOS as H32_SCENARIOS  # noqa: E402
from h32_fine_grid_and_satellite_joint import normalize as h32_normalize  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent

WINDOWS = {
    "full_2019_2026": ("2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-10-01", "2009-06-30"),
    "covid_2020": ("2020-02-19", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
    "selloff_2018": ("2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2015-08-01", "2016-02-15"),
}
EPISODE_ORDER = list(WINDOWS.keys())
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
SEED = 20260917
TRADING_DAYS = 252

BASELINE = "m12_monthly"          # 현재 core/champion_strategy.py 라이브 기본값(12개월, 월간)
FREQ_ONLY = "m12_quarterly"       # H34가 이미 감사한 "분기전환 단독" 기준선(12개월, 분기)
JOINT_CANDIDATES = {
    "m14_quarterly": (14 * 21, 63),
    "m15_quarterly": (15 * 21, 63),
    "m16_quarterly": (16 * 21, 63),
}
ALL_CONFIGS = [BASELINE, FREQ_ONLY] + list(JOINT_CANDIDATES.keys())


def log(msg):
    print(f"[h37] {msg}", flush=True)


def annualized_sharpe(ret: np.ndarray) -> float:
    if len(ret) < 2:
        return float("nan")
    mu, sd = np.mean(ret), np.std(ret, ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(mu / sd * np.sqrt(TRADING_DAYS))


def moving_block_bootstrap_sharpe(ret: np.ndarray, block_len: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """H33/H34와 완전히 동일한 순환 이동블록부트스트랩(재구현 아님, 같은 알고리즘 그대로 복제)."""
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


# ---------------------------------------------------------------------------
# H1 + 데이터 준비: 14/15/16개월/분기 신규 백테스트 + 기존 12개월 기준선 재사용
# ---------------------------------------------------------------------------
def load_h34_baseline_returns() -> dict:
    out = {ep: {} for ep in EPISODE_ORDER}
    for ep in EPISODE_ORDER:
        for cfg, fname in [(BASELINE, "monthly_21d"), (FREQ_ONLY, "quarterly_63d")]:
            s = pd.read_csv(H34_DIR / f"{ep}_{fname}_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
            out[ep][cfg] = s
    return out


def build_joint_candidate_returns() -> tuple[dict, dict]:
    """반환: (window_series, point_metrics). point_metrics[ep][cfg] = {sharpe, cagr, mdd, turnover}."""
    out_series = {ep: {} for ep in EPISODE_ORDER}
    point_metrics = {ep: {} for ep in EPISODE_ORDER}
    t0 = time.time()
    for ep, (start, end) in WINDOWS.items():
        for cfg, (lookback_days, rebal_days) in JOINT_CANDIDATES.items():
            metrics, result = run_champion_joint(start, end, lookback_days, rebal_days, return_weights_idx=True)
            out_series[ep][cfg] = result["ret_net"]
            point_metrics[ep][cfg] = metrics
            log(f"  {ep}/{cfg}: sharpe={metrics['sharpe']:.3f} cagr={metrics['cagr']:.2f}% "
                f"mdd={metrics['mdd']:.2f}% t={time.time()-t0:.1f}s")
    return out_series, point_metrics


def h1_reproducibility_check(point_metrics: dict) -> dict:
    """이번 세션 재실행 결과가 h32_stage1_results.json의 저장값과 일치하는지 확인."""
    h32_raw = json.loads((H32_DIR / "h32_stage1_results.json").read_text())["raw_lookup_table"]
    lookback_by_cfg = {"m14_quarterly": "14", "m15_quarterly": "15", "m16_quarterly": "16"}
    rows = []
    max_abs_diff = 0.0
    for ep in EPISODE_ORDER:
        for cfg, mk in lookback_by_cfg.items():
            stored = h32_raw[ep][mk]["quarterly_63d"]
            fresh = point_metrics[ep][cfg]
            diff = abs(fresh["sharpe"] - stored["sharpe"])
            max_abs_diff = max(max_abs_diff, diff)
            rows.append({
                "episode": ep, "config": cfg,
                "sharpe_h32_stored": stored["sharpe"], "sharpe_this_session": fresh["sharpe"],
                "abs_diff": round(diff, 6),
            })
    return {"rows": rows, "max_abs_diff": round(max_abs_diff, 6),
            "verdict": "exact_match" if max_abs_diff < 1e-6 else "mismatch"}


# ---------------------------------------------------------------------------
# H2/H3: 블록부트스트랩 + 결합전파 (H33/H34 방법론 그대로)
# ---------------------------------------------------------------------------
def bootstrap_all(window_series: dict, rng: np.random.Generator) -> tuple[dict, dict]:
    summary = {ep: {"n_obs": {}, "by_config": {}} for ep in EPISODE_ORDER}
    boot_l20 = {ep: {} for ep in EPISODE_ORDER}
    for ep in EPISODE_ORDER:
        for cfg in ALL_CONFIGS:
            ret = window_series[ep][cfg].values.astype(float)
            summary[ep]["n_obs"][cfg] = int(len(ret))
            point_sharpe = annualized_sharpe(ret)
            per_block = {}
            for L in BLOCK_LENGTHS:
                boot = moving_block_bootstrap_sharpe(ret, L, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                if L == 20:
                    boot_l20[ep][cfg] = boot.tolist()
                if len(boot) == 0:
                    per_block[str(L)] = None
                    continue
                per_block[str(L)] = {
                    "block_len": L, "n_boot_valid": int(len(boot)),
                    "mean": float(np.mean(boot)), "std": float(np.std(boot)),
                    "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
                }
            summary[ep]["by_config"][cfg] = {
                "point_estimate_sharpe": point_sharpe, "bootstrap_by_block_len": per_block,
            }
            log(f"  bootstrap {ep}/{cfg}: point={point_sharpe:.3f} L20_CI90={per_block.get('20', {}).get('ci90')}")
    return summary, boot_l20


K_CENTRAL = 30.0
N_DRAWS = 10000


def dirichlet_draws_for_scenario(scenario_weights: dict, n: int, rng: np.random.Generator) -> np.ndarray:
    w = h32_normalize(scenario_weights)
    alpha = np.array([w[ep] * K_CENTRAL for ep in EPISODE_ORDER])
    return rng.dirichlet(alpha, size=n)


def combined_propagation(boot_l20: dict, point_sharpe: dict, cfg_a: str, cfg_b: str,
                          scenario_weights: dict, rng: np.random.Generator) -> dict:
    dir_draws = dirichlet_draws_for_scenario(scenario_weights, N_DRAWS, rng)

    def draw_ev(cfg):
        per_ep_samples = []
        for ep in EPISODE_ORDER:
            samples = np.array(boot_l20[ep][cfg])
            idx = rng.integers(0, len(samples), size=N_DRAWS)
            per_ep_samples.append(samples[idx])
        stacked = np.column_stack(per_ep_samples)
        return np.sum(stacked * dir_draws, axis=1)

    ev_a, ev_b = draw_ev(cfg_a), draw_ev(cfg_b)
    gap = ev_b - ev_a
    combined_win_rate_b = float(np.mean(ev_b > ev_a))

    w_norm = h32_normalize(scenario_weights)
    ev_matrix_a = np.array([point_sharpe[ep][cfg_a] for ep in EPISODE_ORDER])
    ev_matrix_b = np.array([point_sharpe[ep][cfg_b] for ep in EPISODE_ORDER])
    weighting_only_win_rate_b = float(np.mean((dir_draws @ ev_matrix_b) > (dir_draws @ ev_matrix_a)))

    fixed_w = np.array([w_norm[ep] for ep in EPISODE_ORDER])

    def draw_ev_fixed(cfg):
        per_ep_samples = []
        for ep in EPISODE_ORDER:
            samples = np.array(boot_l20[ep][cfg])
            idx = rng.integers(0, len(samples), size=N_DRAWS)
            per_ep_samples.append(samples[idx])
        return np.column_stack(per_ep_samples) @ fixed_w

    sampling_only_win_rate_b = float(np.mean(draw_ev_fixed(cfg_b) > draw_ev_fixed(cfg_a)))

    return {
        "cfg_baseline": cfg_a, "cfg_challenger": cfg_b,
        "weighting_only_win_rate_challenger": weighting_only_win_rate_b,
        "sampling_only_win_rate_challenger": sampling_only_win_rate_b,
        "combined_win_rate_challenger": combined_win_rate_b,
        "combined_gap_challenger_minus_baseline": {
            "mean": float(np.mean(gap)),
            "ci90": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
        },
        "combined_mean_expected_sharpe": {cfg_a: float(np.mean(ev_a)), cfg_b: float(np.mean(ev_b))},
    }


# ---------------------------------------------------------------------------
# H4: 40칸 전수 그리드 백분위 (재계산 없음, h32_stage1_results.json 재사용)
# ---------------------------------------------------------------------------
def h4_grid_percentile() -> dict:
    h32_report = json.loads((H32_DIR / "report_data.json").read_text())
    out = {}
    for scen_name, scen in h32_report["stage1"]["scenarios"].items():
        ranking = scen["ranking_by_expected_sharpe"]  # list of [key, {..}]
        n_total = len(ranking)
        ranked_keys = [k for k, _ in ranking]
        cand_rows = []
        for months in (14, 15, 16):
            key = f"{months}|quarterly_63d"
            rank = ranked_keys.index(key) + 1
            val = dict(ranking[ranked_keys.index(key)][1])
            cand_rows.append({"lookback_months": months, "rank_out_of_40": rank,
                               "percentile": round(100 * (n_total - rank + 1) / n_total, 1),
                               "expected_sharpe": val["expected_sharpe"]})
        best_key, best_val = ranking[0]
        seq_key = "12|monthly_21d"
        seq_rank = ranked_keys.index(seq_key) + 1
        seq_val = dict(ranking[seq_rank - 1][1])
        out[scen_name] = {
            "grid_best": {"key": best_key, **best_val},
            "sequential_12m_monthly": {"rank_out_of_40": seq_rank, **seq_val},
            "candidates_14_15_16_quarterly": cand_rows,
            "sharpe_spread_top5": round(ranking[0][1]["expected_sharpe"] - ranking[4][1]["expected_sharpe"], 4),
        }
    return out


def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)

    log("=== 데이터 준비: H34 기준선(12mo/monthly, 12mo/quarterly) 재사용 ===")
    baseline_series = load_h34_baseline_returns()

    log("=== 신규 백테스트: 14/15/16개월 + 분기 (18회) ===")
    joint_series, point_metrics = build_joint_candidate_returns()

    window_series = {ep: {**baseline_series[ep], **joint_series[ep]} for ep in EPISODE_ORDER}
    for ep in EPISODE_ORDER:
        for cfg in JOINT_CANDIDATES:
            window_series[ep][cfg].to_csv(OUT_DIR / f"{ep}_{cfg}_ret.csv", header=["ret"])

    log("=== H1: 재현성 확인 (h32_stage1_results.json과 대조) ===")
    h1 = h1_reproducibility_check(point_metrics)
    log(f"  H1 verdict={h1['verdict']} max_abs_diff={h1['max_abs_diff']}")

    log("=== H2/H3: 블록부트스트랩 (전체 5개 config x 6개 창 x 3개 블록길이) ===")
    boot_summary, boot_l20 = bootstrap_all(window_series, rng)

    point_sharpe_lookup = {ep: {cfg: boot_summary[ep]["by_config"][cfg]["point_estimate_sharpe"]
                                 for cfg in ALL_CONFIGS} for ep in EPISODE_ORDER}

    log("=== H2/H3: 결합전파 (3개 시나리오 x [baseline, freq_only] x 3개 joint 후보) ===")
    combined_results = {}
    for scen_name, scen_weights in H32_SCENARIOS.items():
        combined_results[scen_name] = {}
        for base_cfg in (BASELINE, FREQ_ONLY):
            combined_results[scen_name][base_cfg] = {}
            for cand_cfg in JOINT_CANDIDATES:
                res = combined_propagation(boot_l20, point_sharpe_lookup, base_cfg, cand_cfg, scen_weights, rng)
                combined_results[scen_name][base_cfg][cand_cfg] = res
                log(f"  [{scen_name}] {cand_cfg} vs {base_cfg}: "
                    f"weighting_only={res['weighting_only_win_rate_challenger']:.3f} "
                    f"sampling_only={res['sampling_only_win_rate_challenger']:.3f} "
                    f"combined={res['combined_win_rate_challenger']:.3f}")

    log("=== H4: 40칸 전수 그리드 백분위 (재계산 없음) ===")
    h4 = h4_grid_percentile()

    out = {
        "seed": SEED, "n_boot": N_BOOT, "block_lengths": BLOCK_LENGTHS,
        "episode_windows": WINDOWS,
        "configs": {"baseline": BASELINE, "freq_only_baseline": FREQ_ONLY,
                    "joint_candidates": {k: {"lookback_months": v[0] // 21, "rebal_days": v[1]}
                                          for k, v in JOINT_CANDIDATES.items()}},
        "h1_reproducibility": h1,
        "h2_h3_bootstrap_summary": boot_summary,
        "h2_h3_combined_propagation": combined_results,
        "h4_grid_percentile": h4,
        "total_runtime_sec": round(time.time() - t0, 1),
    }
    (OUT_DIR / "h37_results.json").write_text(json.dumps(out, indent=1, default=str))
    log(f"전체 완료, h37_results.json 저장. 총 소요 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
