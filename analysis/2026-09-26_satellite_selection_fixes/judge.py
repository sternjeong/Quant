"""사전 등록 판정 규칙을 그대로 구현한 심판 — PREREGISTRATION.md '판정 규칙' 절.

이 모듈은 수치만 받아 판정을 낸다(가격·네트워크를 쓰지 않는다). 그래서 합성 입력으로 경계를 검증할 수 있다
(`tests/test_satellite_selection_fixes_job.py`). 결과를 본 뒤 이 규칙을 바꾸지 않는다.
"""
from __future__ import annotations

import numpy as np

# ------------------------------------------------------------------ 사전 등록 문턱(결과 전 고정)
FAMILY_ALPHA = 0.05          # 가족 단위 유의수준
N_HYPOTHESES = 3             # 주검정 가설 수(H6·H7·H8) -> 본페로니 보정
N_BOOT = 2000                # 반기 복원추출 횟수
SEED = 20260928              # 시드 고정
N_HALVES_MIN = 30            # 사용 가능한 반기 최소 수(계획 36개 중)
N_EFFECTIVE_MIN = 8          # 규칙이 실제로 문 반기 최소 수
MAX_UNUSABLE_HALVES = 3      # 데이터 문제로 못 쓴 반기 허용 상한

ADOPT, REJECT, NEUTRAL, UNPROVEN = "ADOPT", "REJECT", "NEUTRAL", "UNPROVEN"


def bonferroni_percentiles(n_hypotheses: int = N_HYPOTHESES, family_alpha: float = FAMILY_ALPHA) -> tuple[float, float]:
    """본페로니 보정 양측 백분위. 가설 3개·가족 5% -> (0.8333, 99.1667) = 98.33% CI."""
    alpha = float(family_alpha) / int(n_hypotheses)
    return 100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)


def ci_level_pct(n_hypotheses: int = N_HYPOTHESES, family_alpha: float = FAMILY_ALPHA) -> float:
    lo, hi = bonferroni_percentiles(n_hypotheses, family_alpha)
    return round(hi - lo, 4)


def boot_means(values: list[float], seed: int = SEED, n_boot: int = N_BOOT) -> np.ndarray:
    """반기를 복원추출하는 부트스트랩 — 평균의 분포. 같은 시드면 항상 같은 색인을 쓴다."""
    arr = np.asarray([float(v) for v in values], dtype=float)
    if arr.size == 0:
        return np.zeros(1)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(int(n_boot), arr.size))
    return arr[idx].mean(axis=1)


def percentile_ci(boot: np.ndarray, lo_pct: float, hi_pct: float) -> list[float]:
    return [round(float(np.percentile(boot, lo_pct)), 4), round(float(np.percentile(boot, hi_pct)), 4)]


def sample_requirement_failures(n_halves: int, n_effective: int, n_unusable: int) -> list[str]:
    """표본 요건 미충족 사유 목록(비어 있으면 충족)."""
    out = []
    if int(n_halves) < N_HALVES_MIN:
        out.append(f"사용 가능한 반기 {n_halves}개 < 최소 {N_HALVES_MIN}개")
    if int(n_effective) < N_EFFECTIVE_MIN:
        out.append(f"규칙이 실제로 문 반기 {n_effective}개 < 최소 {N_EFFECTIVE_MIN}개")
    if int(n_unusable) > MAX_UNUSABLE_HALVES:
        out.append(f"데이터 문제로 못 쓴 반기 {n_unusable}개 > 허용 {MAX_UNUSABLE_HALVES}개")
    return out


def verdict_from_ci(lo: float, hi: float) -> str:
    """CI 하한 > 0 채택 · 상한 < 0 기각 · 0 을 포함하면 중립."""
    if lo > 0:
        return ADOPT
    if hi < 0:
        return REJECT
    return NEUTRAL


def judge_hypothesis(
    name: str,
    diffs: list[float | None],
    n_effective: int,
    gate_ok: bool,
    seed: int = SEED,
    n_boot: int = N_BOOT,
    n_hypotheses: int = N_HYPOTHESES,
) -> dict:
    """가설 하나의 판정. `diffs` 는 계획된 반기 순서대로의 짝지은 차이(못 쓴 반기는 None)."""
    usable = [float(v) for v in diffs if v is not None]
    n_halves = len(usable)
    n_unusable = len(diffs) - n_halves
    lo_pct, hi_pct = bonferroni_percentiles(n_hypotheses)

    boot = boot_means(usable, seed=seed, n_boot=n_boot) if n_halves else np.zeros(1)
    ci_b = percentile_ci(boot, lo_pct, hi_pct) if n_halves else [0.0, 0.0]
    ci_95 = percentile_ci(boot, 2.5, 97.5) if n_halves else [0.0, 0.0]

    failures = sample_requirement_failures(n_halves, n_effective, n_unusable)
    if not gate_ok:
        verdict = UNPROVEN
        basis = ["기준 재현 관문 실패 — 자체 스캔의 기준 선정이 라이브 엔진과 다르다"]
    elif failures:
        verdict = UNPROVEN
        basis = failures
    else:
        verdict = verdict_from_ci(ci_b[0], ci_b[1])
        basis = [f"본페로니 {ci_level_pct(n_hypotheses):.2f}% CI = [{ci_b[0]}, {ci_b[1]}]"]

    return {
        "hypothesis": name,
        "verdict": verdict,
        "verdict_basis": basis,
        "mean_diff_pp_per_year": round(float(np.mean(usable)), 4) if n_halves else None,
        "median_diff_pp_per_year": round(float(np.median(usable)), 4) if n_halves else None,
        "ci_bonferroni": ci_b,
        "ci_level_pct": ci_level_pct(n_hypotheses),
        "ci_percentiles": [round(lo_pct, 4), round(hi_pct, 4)],
        "ci_95_unadjusted_secondary": ci_95,
        "n_halves": n_halves,
        "n_unusable_halves": n_unusable,
        "n_effective_halves": int(n_effective),
        "n_boot": int(n_boot),
        "seed": int(seed),
        "sample_requirements_met": (not failures),
        "gate_ok": bool(gate_ok),
        "win_rate_halves": round(float(np.mean([1.0 if v >= 0 else 0.0 for v in usable])), 4) if n_halves else None,
        "worst_half_diff": round(float(np.min(usable)), 4) if n_halves else None,
        "best_half_diff": round(float(np.max(usable)), 4) if n_halves else None,
    }
