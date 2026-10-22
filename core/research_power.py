"""연구 판정 설계 도구 (2026-10-10 사용자 승인 — 판정 체계 변경).

왜: 앞 구간 약 17년 일별 데이터로 DSR ≥ 0.95 를 요구하면, 시도 13개일 때 연 정보비율(IR) 약 0.8 이 넘어야 통과한다.
현실적인 개선(IR 0.2~0.4)은 거의 언제나 FAIL 이 되므로, FAIL 이 '효과 없음'인지 '판별 불가'인지 구분해야 한다.
또 같은 떼어 둔 2년(2024-10~)을 20개 넘는 연구가 들여다봐서 그 구간은 더 이상 정직한 시험대가 아니다.

새 규칙(docs/RESEARCH_JOBS.md '판정 설계 규칙'):
1. 새 연구는 결과를 보기 전에 power_report() 로 관측 통과 문턱(50% 통과 확률)과
   80% 검정력에서 검출 가능한 연 IR을 따로 계산한다. 관측 효과 하나만으로 검정력 부족을 확정하지 않는다.
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
    """기존 호환 이름: 통과 확률이 50%인 연 IR. 80% 검정력 MDE는 detectable_ir()."""
    if years <= 0:
        return float("inf")
    return (expected_max_z(n_trials) + _N.inv_cdf(confidence)) / math.sqrt(years)


def power(true_ir: float, years: float, n_trials: int = 1, confidence: float = 0.95) -> float:
    """참 연 IR 이 true_ir 일 때 이 관문을 통과할 확률(근사)."""
    if years <= 0:
        return 0.0
    return 1 - _N.cdf((mde_ir(years, n_trials, confidence) - true_ir) * math.sqrt(years))


def detectable_ir(years: float, n_trials: int = 1, *, confidence: float = 0.95,
                  target_power: float = 0.8) -> float:
    """정해진 검정력으로 관문을 통과할 수 있는 최소 참 연 IR(근사)."""
    if not 0 < target_power < 1:
        raise ValueError("target_power는 0과 1 사이여야 합니다")
    if years <= 0:
        return float("inf")
    return mde_ir(years, n_trials, confidence) + _N.inv_cdf(target_power) / math.sqrt(years)


def power_report(years: float, n_trials: int, *, confidence: float = 0.95,
                 plausible_irs: Sequence[float] = (0.2, 0.3, 0.5)) -> dict:
    """results.json 의 "power" 에 그대로 넣을 사전 계산."""
    return {
        "years": round(float(years), 2),
        "n_trials": int(n_trials),
        "confidence": confidence,
        "mde_ir": round(mde_ir(years, n_trials, confidence), 3),
        "pass_threshold_ir_50pct_power": round(mde_ir(years, n_trials, confidence), 3),
        "detectable_ir_80pct_power": round(detectable_ir(years, n_trials, confidence=confidence), 3),
        "power_at": {f"{ir:.2f}": round(power(ir, years, n_trials, confidence), 3) for ir in plausible_irs},
        "method": "expected-max-z(Bailey-LdP) + null SE, simplified",
    }


def power_line(rep: dict) -> str:
    """REPORT.md 용 한 줄."""
    pw = ", ".join(f"IR {k}→{v:.0%}" for k, v in rep["power_at"].items())
    return (f"검정력(사전 계산): {rep['years']}년·시도 {rep['n_trials']}개에서 통과에 필요한 연 IR ≈ {rep['mde_ir']:.2f} "
            f"(통과 확률 50%; 검정력 80%의 최소 참 IR ≈ {rep.get('detectable_ir_80pct_power', float('nan')):.2f}; "
            f"참 효과별 통과 확률 {pw}). 관측 IR만으로 효과 부재나 검정력 부족을 확정하지 않는다.")


def classify_fail(observed_ir: Optional[float], rep: dict) -> str:
    """같은 단위의 관측 연 활성 IR로 붙이는 휴리스틱 해석. 확정 검정력 판정은 아니다."""
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


# ---------------------------------------------------------------------------------------------
# 에이전트 아이디어 심판 3종(hypothesis_judge · satellite_lab · core_lab) 적용 도구 (2026-10-11 사용자 승인)
# 통과/탈락 기준·관문·판정 버전은 그대로 두고, 판정 결과에 검정력 정보와 해석 문구만 덧붙인다.
# ---------------------------------------------------------------------------------------------
TRADING_DAYS = 252
PASS_MEANING = "통과 = 전진 원장에 올릴 후보·사람 검토 대기. 채택이 아니며 챔피언에 자동 반영되지 않는다"
HOLDOUT_NOTE = ("떼어 둔 마지막 2년(2024-10~)은 20개 넘는 연구가 이미 들여다봐서 더 이상 독립 시험이 아니다 — "
                "채택 판단은 전진 원장(앞으로 쌓이는 데이터)으로 한다")


def power_fields(n_is_days: Optional[float], n_trials: Optional[int], observed_ir: Optional[float], failed: bool) -> dict:
    """판정 결과(dict)에 그대로 덧붙일 추가 키: {"power": power_report, "fail_kind": ...}.

    입력이 없거나 NaN·0 이하면 {} (판정을 막지 않는다). fail_kind 는 failed 일 때만.
    """
    try:
        days = float(n_is_days)
        trials = int(n_trials)
        if not math.isfinite(days) or days < 2 or trials < 1:
            return {}
        rep = power_report(days / TRADING_DAYS, trials)
        if not math.isfinite(rep["mde_ir"]):
            return {}
    except (TypeError, ValueError, OverflowError):
        return {}
    out: dict = {"power": rep}
    if failed:
        try:
            ir = float(observed_ir) if observed_ir is not None else None
        except (TypeError, ValueError):
            ir = None
        out["fail_kind"] = classify_fail(ir, rep)
    return out


def power_suffix(res: Optional[dict]) -> str:
    """텔레그램·화면용 짧은 덧붙임. 정보가 없으면 빈 문자열(옛 저장 결과도 안전)."""
    res = res or {}
    rep = res.get("power")
    if not isinstance(rep, dict) or "mde_ir" not in rep:
        return ""
    if res.get("fail_kind") == "FAIL_UNDERPOWERED":
        return f"검정력 부족(필요 연 IR≈{rep['mde_ir']:.2f}) — 효과 없음이 아니라 판별 불가에 가까움"
    return f"필요 연 IR≈{rep['mde_ir']:.2f}"


def briefing_block(years: float, n_trials: int) -> str:
    """에이전트 컨텍스트(Writer·위성 설계자·코어 설계자가 읽는 '이미 시도한 것 / 판정 방법')에 붙이는 검정력 사실 블록."""
    years = max(float(years), 1.0)
    n = max(int(n_trials), 1)
    mde = mde_ir(years, n)
    mde_one = mde_ir(years, 1)
    return "\n".join([
        "", "## 판정 해석 (자동 생성 — research_power 계산)",
        f"- 앞 구간 약 {years:.0f}년, 누적 시도 {n}개에서 DSR 0.95 를 넘으려면 연 정보비율(IR) 약 {mde:.2f} 이상이 필요하다"
        f"(시도 1개여도 {mde_one:.2f}). 현실적인 개선(IR 0.2~0.4)은 대개 이 문턱에 못 미친다.",
        "- 그러므로 크고 메커니즘(왜 작동하는지)이 분명한 효과를 노린다. 작은 개선을 숫자만 바꿔 다시 내지 않는다.",
        "- 이미 탈락한 방향 목록은 대부분 '효과 없음이 증명됐다'가 아니라 '검정력 부족(판별 불가)'이다 "
        "(판정 결과의 fail_kind 가 FAIL_UNDERPOWERED 면 그렇다). 같은 방향을 조금 바꿔 재시도하기보다 근거가 다른 새 메커니즘을 고른다.",
        f"- {PASS_MEANING}.",
        f"- {HOLDOUT_NOTE}.",
        "- 후보 수익이 기준선과 매일 같으면(설정이 계산에 반영되지 않음) 탈락이 아니라 NOT_EVALUABLE 이다 — 시도로 세지 않는다.",
        ""])
