"""연구 판정 설계 도구 (2026-10-10 사용자 승인 — 판정 체계 변경).

왜: 앞 구간 약 17년 일별 데이터로 DSR ≥ 0.95 를 요구하면, 시도 13개일 때 연 정보비율(IR) 약 0.8 이 넘어야 통과한다.
현실적인 개선(IR 0.2~0.4)은 거의 언제나 FAIL 이 되므로, FAIL 이 '효과 없음'인지 '판별 불가'인지 구분해야 한다.
또 같은 떼어 둔 2년(2024-10~)을 20개 넘는 연구가 들여다봐서 그 구간은 더 이상 정직한 시험대가 아니다.

새 규칙(docs/RESEARCH_JOBS.md '판정 설계 규칙'):
1. 새 연구는 결과를 보기 전에 power_report() 로 최소 검출 효과(MDE)를 계산해 results.json 의 "power" 에 넣고
   REPORT.md 에 한 줄로 적는다. 판정이 FAIL 이고 관측 효과가 MDE 보다 작으면 "판별 불가(검정력 부족)"로 함께 적는다.
2. 후보 수익이 기준선과 전부 같으면(활성 수익이 0) FAIL 이 아니라 NOT_EVALUABLE — noop_guard() 로 막는다
   (core-universe-expansion-v1 이 이 경우였다: 추가 자산이 순위 후보에 들어가지 않았다).
3. 2024-10 이후 구간은 새 연구의 최종 판정 근거로 쓰지 않는다(보고만). 채택 판단은 전진 원장(앞으로 쌓이는 데이터)으로 한다.

계산은 Bailey·López de Prado 의 기대 최대 샤프 근사를 쓰되, 시도 간 샤프 분산을 귀무가설의 표본오차로 둔 단순화다
(실제 시도끼리 상관이 높으면 문턱이 조금 낮아진다 — 보수적인 쪽).
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Optional, Sequence

_N = NormalDist()
_EULER = 0.5772156649015329


def expected_max_z(n_trials: int) -> float:
    """독립 표준정규 n 개의 기대 최댓값 근사(n ≤ 1 이면 0)."""
    n = int(n_trials)
    if n <= 1:
        return 0.0
    return (1 - _EULER) * _N.inv_cdf(1 - 1 / n) + _EULER * _N.inv_cdf(1 - 1 / (n * math.e))


def mde_ir(years: float, n_trials: int = 1, confidence: float = 0.95) -> float:
    """이 기간·시도 수에서 DSR ≥ confidence 를 넘으려면 필요한 연 정보비율(최소 검출 효과)."""
    if years <= 0:
        return float("inf")
    return (expected_max_z(n_trials) + _N.inv_cdf(confidence)) / math.sqrt(years)


def power(true_ir: float, years: float, n_trials: int = 1, confidence: float = 0.95) -> float:
    """참 연 IR 이 true_ir 일 때 이 관문을 통과할 확률(근사)."""
    if years <= 0:
        return 0.0
    return 1 - _N.cdf((mde_ir(years, n_trials, confidence) - true_ir) * math.sqrt(years))


def power_report(years: float, n_trials: int, *, confidence: float = 0.95,
                 plausible_irs: Sequence[float] = (0.2, 0.3, 0.5)) -> dict:
    """results.json 의 "power" 에 그대로 넣을 사전 계산."""
    return {
        "years": round(float(years), 2),
        "n_trials": int(n_trials),
        "confidence": confidence,
        "mde_ir": round(mde_ir(years, n_trials, confidence), 3),
        "power_at": {f"{ir:.2f}": round(power(ir, years, n_trials, confidence), 3) for ir in plausible_irs},
        "method": "expected-max-z(Bailey-LdP) + null SE, simplified",
    }


def power_line(rep: dict) -> str:
    """REPORT.md 용 한 줄."""
    pw = ", ".join(f"IR {k}→{v:.0%}" for k, v in rep["power_at"].items())
    return (f"검정력(사전 계산): {rep['years']}년·시도 {rep['n_trials']}개에서 통과에 필요한 연 IR ≈ {rep['mde_ir']:.2f} "
            f"(참 효과별 통과 확률 {pw}). FAIL 이어도 관측 IR 이 이보다 작으면 '판별 불가'에 가깝다.")


def classify_fail(observed_ir: Optional[float], rep: dict) -> str:
    """FAIL 의 성격: 관측 IR 이 MDE 이상인데 다른 관문에서 떨어졌으면 'FAIL', 아니면 'FAIL_UNDERPOWERED'."""
    if observed_ir is None or not math.isfinite(observed_ir):
        return "FAIL"
    return "FAIL" if observed_ir >= rep["mde_ir"] or observed_ir <= 0 else "FAIL_UNDERPOWERED"


def noop_guard(active_returns: Sequence[float], *, tol: float = 1e-12) -> Optional[str]:
    """활성 수익(후보 − 기준선)이 전부 0 이면 사유 문자열(→ NOT_EVALUABLE), 아니면 None."""
    vals = [float(x) for x in active_returns if x is not None and math.isfinite(float(x))]
    if not vals:
        return "활성 수익 없음(데이터 없음)"
    if max(abs(x) for x in vals) <= tol:
        return "후보가 기준선과 매일 같음 — 후보 설정이 계산에 반영되지 않았을 가능성(NOT_EVALUABLE)"
    return None
