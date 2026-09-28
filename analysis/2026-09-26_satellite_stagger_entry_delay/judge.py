"""사전 등록 판정 규칙(PREREGISTRATION.md)을 코드로 고정한 심판 — 결과를 보기 전에 정한 것이며 바꾸지 않는다.

여기에는 **판정 규칙만** 있다(부트스트랩·백테스트 숫자는 run.py 가 만든다). 규칙을 숫자 계산과
분리해 둔 이유: 사전 등록 문장과 1:1로 대조할 수 있고, 합성 입력으로 경계(채택/기각/중립/미입증)를
손계산과 맞춰 볼 수 있어서다(tests/test_satellite_stagger_job.py).

사전 등록 원문 대응:
- H1 "5개 **전부**에서 CI 하한 > 0 이면 '1·7월 특이성 있음(계절성)' → 시차 분할 기각. 아니면 '시작월 강건'."
- H2 "H1이 '시작월 강건' 그리고 샤프 차이(분할−기준) CI 하한 ≥ −0.20 그리고 |MDD(분할)| ≤ |MDD(기준)| + 5%p 이면 채택"
- H3 "'진입 가능 기간' = [excess(d) − excess(0) 반기 부트스트랩 CI가 0을 포함] 그리고 [excess(d) 반기 평균 점추정 > 0]
      을 만족하는 최대 d. 다중비교(지연 7개)라 '탐색 결과'로 라벨."
- H4 "CI 하한 ≥ 0 → 채택. CI 상한 < 0(해로움) → 기각. CI가 0 포함 → '중립 — 위험 관리 목적이면 채택 가능'."
- H5 "불일치 비율 > 10% 이면 화면에서 '이번 달 보유(검증 기준)'를 주 표시로 바꿀 근거로 기록."

판정 기준을 계산할 수 없으면(표본 부족·자료 결측) 억지 결론 대신 UNPROVEN(미입증)을 낸다.
"""

from __future__ import annotations

UNPROVEN = "UNPROVEN"

# H1
H1_N_COMPARISONS = 5  # 기준(1,7) 대비 나머지 변형 5개
H1_ROBUST, H1_SEASONAL = "ROBUST", "SEASONAL"

# H2
H2_SHARPE_CI_LOWER_FLOOR = -0.20  # 샤프 차이(분할−기준) CI 하한이 이보다 낮으면 기각
H2_MDD_TOLERANCE_PP = 5.0  # |MDD(분할)| 이 |MDD(기준)| + 5%p 를 넘으면 기각
H2_ADOPT, H2_REJECT = "ADOPT", "REJECT"

# H3 (사전 등록에 고정된 지연 집합 — 바꾸면 다른 연구다)
H3_DELAYS = (0, 5, 21, 42, 63, 84, 105)
H3_LABEL = "탐색 결과(지연 7개 다중비교, 보정 없음)"

# H4
H4_DELAYS = (21, 42, 63, 84, 105)
H4_ADOPT, H4_REJECT, H4_NEUTRAL = "ADOPT", "REJECT", "NEUTRAL"
H4_NEUTRAL_NOTE = "중립 — 위험 관리 목적이면 채택 가능"

# H5
H5_MISMATCH_THRESHOLD = 0.10
H5_FREQUENT, H5_RARE = "MISMATCH_FREQUENT", "MISMATCH_RARE"


def ci_contains_zero(ci95) -> bool:
    """95% 백분위 CI 가 0을 포함하는가(경계 포함)."""
    if ci95 is None or len(ci95) != 2:
        return False
    lo, hi = float(ci95[0]), float(ci95[1])
    return lo <= 0.0 <= hi


# ---------------------------------------------------------------- H1
def h1_verdict(ci_lowers, n_expected: int = H1_N_COMPARISONS) -> str:
    """ci_lowers: 기준−변형 샤프 차이 CI 하한 목록(변형 5개). 전부 > 0 이면 계절성."""
    lowers = [x for x in (ci_lowers or []) if x is not None]
    if len(lowers) != n_expected:
        return UNPROVEN  # 변형 하나라도 계산하지 못했으면 판정하지 않는다
    return H1_SEASONAL if all(float(x) > 0.0 for x in lowers) else H1_ROBUST


# ---------------------------------------------------------------- H2
def h2_verdict(h1: str, sharpe_diff_ci_lower, mdd_stagger, mdd_base) -> tuple[str, dict]:
    """반환: (판정, 조건별 통과 여부). 조건 하나라도 계산 불가면 미입증."""
    if h1 == UNPROVEN or sharpe_diff_ci_lower is None or mdd_stagger is None or mdd_base is None:
        return UNPROVEN, {}
    conditions = {
        "h1_start_month_robust": h1 == H1_ROBUST,
        "sharpe_diff_ci_lower_ge_floor": float(sharpe_diff_ci_lower) >= H2_SHARPE_CI_LOWER_FLOOR,
        "mdd_within_tolerance_pp": abs(float(mdd_stagger)) <= abs(float(mdd_base)) + H2_MDD_TOLERANCE_PP,
    }
    return (H2_ADOPT if all(conditions.values()) else H2_REJECT), conditions


# ---------------------------------------------------------------- H3
def h3_delay_qualifies(mean_excess, diff_ci95) -> bool:
    """지연 d 가 '진입 가능'한가: 차이 CI 가 0을 포함하고, 그 지연의 반기 평균 초과수익이 > 0."""
    if mean_excess is None:
        return False
    return ci_contains_zero(diff_ci95) and float(mean_excess) > 0.0


def h3_scan(per_delay: dict) -> dict:
    """per_delay: {지연 d: {"mean_excess": float|None, "diff_ci95": [lo,hi]|None, ...}}.

    반환: 최대 d(없으면 None), 통과한 지연 목록, 연속성 여부. 사전 등록 지연 집합이 다 없으면 미입증.
    """
    delays = sorted(int(d) for d in per_delay)
    if tuple(delays) != H3_DELAYS:
        return {"verdict": UNPROVEN, "max_entry_delay_days": None, "qualifying_delays": [],
                "contiguous": None, "label": H3_LABEL,
                "reason": f"사전 등록 지연 집합과 다르다: {delays} != {list(H3_DELAYS)}"}
    qualifying = [d for d in delays
                  if h3_delay_qualifies(per_delay[d].get("mean_excess"), per_delay[d].get("diff_ci95"))]
    if not qualifying:
        return {"verdict": UNPROVEN, "max_entry_delay_days": None, "qualifying_delays": [],
                "contiguous": None, "label": H3_LABEL,
                "reason": "조건을 만족하는 지연이 하나도 없다(d=0 포함) — 진입 가능 기간 미입증"}
    max_d = max(qualifying)
    contiguous = qualifying == [d for d in delays if d <= max_d]
    return {"verdict": "FOUND", "max_entry_delay_days": max_d, "qualifying_delays": qualifying,
            "contiguous": contiguous, "label": H3_LABEL}


# ---------------------------------------------------------------- H4
def h4_verdict(ci95) -> tuple[str, str]:
    """반환: (판정, 사전 등록이 붙인 설명). CI 를 계산하지 못했으면 미입증."""
    if ci95 is None or len(ci95) != 2:
        return UNPROVEN, "반기 부트스트랩 CI 를 계산할 표본이 없다"
    lo, hi = float(ci95[0]), float(ci95[1])
    if lo >= 0.0:
        return H4_ADOPT, "CI 하한 ≥ 0 — 추세 확인 필터 채택"
    if hi < 0.0:
        return H4_REJECT, "CI 상한 < 0 — 해로움, 기각"
    return H4_NEUTRAL, H4_NEUTRAL_NOTE


# ---------------------------------------------------------------- H5
def h5_verdict(mismatch_day_fraction) -> str:
    if mismatch_day_fraction is None:
        return UNPROVEN
    return H5_FREQUENT if float(mismatch_day_fraction) > H5_MISMATCH_THRESHOLD else H5_RARE


# ---------------------------------------------------------------- 묶음
def build_verdicts(h1: str, h2: str, h3_max_delay, h4: str, h5: str) -> dict:
    """텔레그램·관제 센터가 읽는 기계 판정(job.json 의 summary_from=verdicts)."""
    return {
        "H1_start_month_robustness": h1,
        "H2_staggered": h2,
        "H3_entry_window_days": h3_max_delay,
        "H4_trend_filter": h4,
        "H5_core_drift": h5,
    }
