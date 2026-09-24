"""core/filing_veto_shadow.py (RES-05 위성 shadow veto) 테스트.

원칙(test_filing_changes.py, test_candidate_recorder.py 와 동일):
- 예상값은 구현이 아니라 요구사항(스펙 §8 veto 규칙, candidate_ledger 의 최소 표본 게이트)에서 손으로 정했다.
- 네트워크를 쓰지 않는다. compute_satellite_recommendation_point_in_time 은 satellite_result 인자로,
  filing_veto 의 입력 이벤트는 event_provider 인자로 직접 주입한다(core.filing_changes.filing_veto 자체의
  섹션 추출·태깅 정확도는 test_filing_changes.py 의 몫이라 여기서 다시 검증하지 않는다).
- 이 테스트는 성과·승률 개선을 주장하지 않는다. "기록·비교 배관이 요구사항대로 동작하는가"만 검증한다.
"""

import ast
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import candidate_ledger as cl
from core import filing_veto_shadow as fvs
from core.filing_changes import (
    CATEGORY_LIQUIDITY,
    FilingChangeEvent,
    RiskTag,
    SECTION_LIQUIDITY,
    SECTION_RISK,
    SectionDiff,
)
from core.models import CandidateDecision

AS_OF = date(2026, 9, 22)


# ---------------------------------------------------------------------------
# 합성 이벤트 (core.filing_changes 의 추출·diff 를 다시 시험하지 않고, filing_veto 가 바로 쓸 수 있는
# FilingChangeEvent 를 직접 조립한다 — test_filing_changes.py 의 build_filing_change_event 종단 검증과
# 상호보완적이다)
# ---------------------------------------------------------------------------
def _hold_worthy_event(ticker: str, accession: str, available_at_iso: str) -> FilingChangeEvent:
    """신규(going concern) 유동성 위험 태그가 있는 이벤트 — filing_veto 규칙 R1 을 건드려야 한다."""
    tag = RiskTag(
        category=CATEGORY_LIQUIDITY, severity="strong", modality="asserted", specific=True,
        anchor="Our auditors have expressed substantial doubt about our ability to continue as a going concern.",
        section=SECTION_RISK, novelty="new_category", is_new=True,
    )
    risk_sd = SectionDiff(section=SECTION_RISK, status="ok", current_status="ok", prior_status="ok", tags=[tag])
    liq_sd = SectionDiff(section=SECTION_LIQUIDITY, status="not_comparable",
                         current_status="section_not_found", prior_status="section_not_found")
    return FilingChangeEvent(
        ticker=ticker, cik="0000000123", form="10-K", accession=accession, filing_date="2026-09-01",
        report_date="2026-06-30", prior_accession=f"{accession}-PRIOR", prior_form="10-K",
        prior_filing_date="2025-09-01", comparison_status="ok", available_at=available_at_iso,
        sections={SECTION_RISK: risk_sd, SECTION_LIQUIDITY: liq_sd},
    )


def _clean_event(ticker: str, accession: str, available_at_iso: str) -> FilingChangeEvent:
    """비교는 가능했지만(노출됨) veto 사유가 없는 이벤트 — pass 이되 exposed=True 여야 한다."""
    risk_sd = SectionDiff(section=SECTION_RISK, status="ok", current_status="ok", prior_status="ok", tags=[])
    liq_sd = SectionDiff(section=SECTION_LIQUIDITY, status="not_comparable",
                         current_status="section_not_found", prior_status="section_not_found")
    return FilingChangeEvent(
        ticker=ticker, cik="0000000456", form="10-K", accession=accession, filing_date="2026-09-01",
        report_date="2026-06-30", prior_accession=f"{accession}-PRIOR", prior_form="10-K",
        prior_filing_date="2025-09-01", comparison_status="ok", available_at=available_at_iso,
        sections={SECTION_RISK: risk_sd, SECTION_LIQUIDITY: liq_sd},
    )


def _sat_result(tickers, **extra) -> dict:
    out = {"as_of": AS_OF.isoformat(), "rebal_date": "2026-07-01", "selected": list(tickers),
           "sizing_method": "equal", "per_ticker_weights": {t: 1 / len(tickers) for t in tickers} if tickers else {}}
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# (a) 신규 유동성 위험 공시가 있는 종목에 veto 가 걸리는가
# ---------------------------------------------------------------------------
def test_new_liquidity_risk_filing_triggers_hold(db_session):
    sat_result = _sat_result(["ZETA", "OMEGA"])

    def provider(ticker, decision_cutoff):
        if ticker == "ZETA":
            # decision_cutoff(2026-09-22 -> 23:59:59 ET -> 2026-09-23T03:59:59Z) 로부터 7일 전 -> W=10거래일(약
            # 14일) 이내 -> exposed=True 여야 한다.
            return [_hold_worthy_event("ZETA", "ACC-ZETA-1", "2026-09-15T21:00:00Z")]
        return []  # OMEGA: 최근 공시 없음 -> 노출되지 않은 후보

    out = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat_result,
                                        event_provider=provider)
    assert out["strategy_version"] == fvs.SHADOW_STRATEGY_VERSION
    assert out["source"] == fvs.SHADOW_SOURCE
    assert out["n_candidates"] == 2
    assert out["n_held_by_veto"] == 1
    assert out["n_exposed"] == 1
    assert out["shadow_only"] is True and out["order_path_connected"] is False

    zeta = db_session.query(CandidateDecision).filter_by(
        strategy_version=fvs.SHADOW_STRATEGY_VERSION, ticker="ZETA").one()
    assert zeta.decision == "held"
    assert "hold" in zeta.decision_reason
    import json
    scores = json.loads(zeta.scores)
    assert scores["veto_decision"] == "hold"
    assert "new_going_concern_language" in scores["veto_reason_codes"]
    assert scores["exposed"] is True
    assert scores["original_decision"] == "selected"  # 원전략은 이미 이 종목을 채택했다

    omega = db_session.query(CandidateDecision).filter_by(
        strategy_version=fvs.SHADOW_STRATEGY_VERSION, ticker="OMEGA").one()
    assert omega.decision == "selected"
    scores_o = json.loads(omega.scores)
    assert scores_o["veto_decision"] == "pass"
    assert scores_o["exposed"] is False
    assert scores_o["veto_reason_codes"] == ["no_usable_event"]

    # shadow 기록도 candidate_ledger 규칙 그대로 pit_certified=False 여야 한다(시간 계약을 지어내지 않는다).
    assert zeta.pit_certified is False and omega.pit_certified is False


def test_event_too_old_is_not_exposed_even_if_it_still_qualifies_for_veto(db_session):
    """filing_veto 자체의 max_event_age_days(기본 45일)는 exposed 판정(W~14일)보다 느슨하다 — 30일 전
    이벤트는 veto 규칙상 여전히 hold 를 유발할 수 있지만 주 분석 표본(exposed)에서는 빠져야 한다."""
    sat_result = _sat_result(["OLDCO"])

    def provider(ticker, decision_cutoff):
        return [_hold_worthy_event("OLDCO", "ACC-OLD-1", "2026-08-23T21:00:00Z")]  # cutoff 로부터 약 30일 전

    out = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat_result,
                                        event_provider=provider)
    assert out["n_held_by_veto"] == 1  # 여전히 hold
    assert out["n_exposed"] == 0  # 그러나 노출 표본에는 포함되지 않는다
    d = db_session.query(CandidateDecision).filter_by(
        strategy_version=fvs.SHADOW_STRATEGY_VERSION, ticker="OLDCO").one()
    assert d.decision == "held"
    import json
    assert json.loads(d.scores)["exposed"] is False


# ---------------------------------------------------------------------------
# (b) 원전략(위성)의 실제 채택/보류 결정은 절대 바뀌지 않는가
# ---------------------------------------------------------------------------
REAL_SATELLITE_STRATEGY_VERSION = "champion_satellite/equal"


def test_original_strategy_decision_is_never_changed(db_session):
    """실제(RES-01 식) 위성 원장과 shadow 원장을 나란히 기록하고, shadow 가 hold 로 판정한 종목도
    실제 원장에서는 여전히 selected 로 남아 있는지 확인한다 — 이 모듈은 별도 strategy_version/source
    로만 쓰기 때문에 구조적으로 실제 결정을 건드릴 수 없다."""
    sat_result = _sat_result(["ZETA"])
    sat_result_copy_before = dict(sat_result, selected=list(sat_result["selected"]))

    # 1) 실제 RES-01 스타일 원장(원전략의 진짜 채택 결정)을 먼저 기록한다.
    real_cset = cl.champion_satellite_to_candidate_set(
        sat_result, strategy_version=REAL_SATELLITE_STRATEGY_VERSION, decision_cutoff=AS_OF)
    cl.record_candidate_set(real_cset, session=db_session)
    real_before = db_session.query(CandidateDecision).filter_by(
        strategy_version=REAL_SATELLITE_STRATEGY_VERSION, ticker="ZETA").one()
    assert real_before.decision == "selected"

    # 2) shadow veto 는 같은 종목을 hold 로 판정한다.
    def provider(ticker, decision_cutoff):
        return [_hold_worthy_event("ZETA", "ACC-ZETA-2", "2026-09-16T12:00:00Z")]

    fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat_result, event_provider=provider)

    # 3) 실제 원장은 전혀 바뀌지 않았어야 한다.
    real_after = db_session.query(CandidateDecision).filter_by(
        strategy_version=REAL_SATELLITE_STRATEGY_VERSION, ticker="ZETA").one()
    assert real_after.decision == "selected"
    assert real_after.id == real_before.id  # 같은 행, 새 행이 생기거나 덮어써지지 않았다
    assert db_session.query(CandidateDecision).filter_by(
        strategy_version=REAL_SATELLITE_STRATEGY_VERSION).count() == 1

    # 4) shadow 원장에서는(다른 strategy_version) held 로 남는다 — 두 원장이 공존하되 서로 침범하지 않는다.
    shadow = db_session.query(CandidateDecision).filter_by(
        strategy_version=fvs.SHADOW_STRATEGY_VERSION, ticker="ZETA").one()
    assert shadow.decision == "held"

    # 5) 원전략에 넘긴 satellite_result 입력 자체도 변형되지 않았다.
    assert sat_result == sat_result_copy_before


def test_module_never_imports_order_path():
    """소스 검사: 주문 경로(core.paper_execution, scripts/champion_paper_trade)를 import 하지 않는다
    (tests/test_candidate_recorder.py 의 같은 검사와 같은 목적)."""
    src = Path(fvs.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    bad = [n for n in names if n.startswith("core.paper_execution") or n.startswith("scripts.champion_paper_trade")]
    assert bad == [], f"주문 경로를 import 하면 안 된다: {bad}"
    # core.champion_strategy 의 기존 함수를 고치지 않고 읽기만 한다는 것도 소스에서 확인한다(수정 금지 범위).
    assert "def compute_satellite_recommendation" not in src


# ---------------------------------------------------------------------------
# (c) 표본 미달 시 항상 '미입증'
# ---------------------------------------------------------------------------
def _shadow_frame(rows):
    """core.candidate_ledger.FRAME_COLUMNS 와 같은 모양의 프레임(evaluate_filing_veto_shadow_arms 가
    DB 없이 바로 받을 수 있게). rows: (decision_id, ticker, decision, decision_date, value)."""
    df = pd.DataFrame(rows, columns=["decision_id", "ticker", "decision", "decision_date", cl.PRIMARY_TARGET])
    df["candidate_set_id"] = "shadow_cs1"
    df["decision_date"] = pd.to_datetime(df["decision_date"])
    df["pit_certified"] = False  # 이 모듈의 실제 산출물과 같은 정직한 기본값(항상 False)
    df["status"] = np.where(df[cl.PRIMARY_TARGET].isna(), "missing", "final")
    return df[cl.FRAME_COLUMNS.__iter__.__self__ if False else
              ["decision_id", "candidate_set_id", "ticker", "decision", "decision_date", "pit_certified",
               "status", cl.PRIMARY_TARGET]]


def test_small_sample_is_always_unproven_even_with_strong_effect():
    # 5개 후보(보류 5, 채택 0)만으로는 candidate_ledger 의 최소 표본 게이트(MIN_SELECTED_FOR_VERDICT=30 등)를
    # 채울 수 없다 — 효과 크기를 아주 크게(veto 로 보류한 쪽이 -50%) 줘도 '미입증'이어야 한다.
    rows = [
        (1, "A", "selected", "2026-06-01", 0.01),
        (2, "B", "held", "2026-06-01", -0.50),
        (3, "C", "held", "2026-06-02", -0.55),
        (4, "D", "held", "2026-06-03", -0.60),
        (5, "E", "held", "2026-06-04", -0.45),
    ]
    frame = _shadow_frame(rows)
    exposed_ids = {r[0] for r in rows}
    # require_pit=False 로 PIT 게이트를 분리해도(항상 False 인 pit_certified 때문에 단독으로도 미입증이 되는
    # 것과 별개로) 최소 표본 게이트 자체가 미입증을 강제하는지 확인한다 — 우회하지 않는다.
    out = fvs.evaluate_filing_veto_shadow_arms(
        frame=frame, exposed_decision_ids=exposed_ids, exposed_only=True,
        n_boot=200, n_random_draws=50, seed=1, require_pit=False)
    assert out["verdict"] == cl.VERDICT_UNPROVEN
    assert any(r.startswith("insufficient_sample") for r in out["verdict_reasons"])
    assert out["requires_human_approval"] is False


def test_default_require_pit_true_is_always_unproven_because_shadow_never_certifies_pit():
    """production 기본값(require_pit=True)에서는, 표본이 충분해도 이 모듈이 시간 계약을 지어내지 않아
    pit_certified 가 항상 False 이므로 verdict 는 항상 '미입증'이어야 한다(우회 금지)."""
    rng = np.random.default_rng(7)
    tickers = [f"T{i:02d}" for i in range(60)]
    dates = pd.date_range("2025-01-06", periods=12, freq="42D")
    rows = []
    did = 0
    for d in dates:
        cands = rng.choice(tickers, size=20, replace=False)
        for j, t in enumerate(cands):
            did += 1
            held = j < 10
            v = (-0.05 if held else 0.0) + rng.normal(0.0, 0.02)
            rows.append((did, t, "held" if held else "selected", d, v))
    frame = _shadow_frame(rows)
    exposed_ids = {r[0] for r in rows}
    out = fvs.evaluate_filing_veto_shadow_arms(
        frame=frame, exposed_decision_ids=exposed_ids, exposed_only=True,
        n_boot=300, n_random_draws=100, seed=5)  # require_pit 기본값(True)
    assert out["verdict"] == cl.VERDICT_UNPROVEN
    assert "not_pit_certified" in out["verdict_reasons"]


# ---------------------------------------------------------------------------
# (d) DB 왕복
# ---------------------------------------------------------------------------
def test_record_then_evaluate_round_trips_through_db(db_session):
    sat_result = _sat_result(["ZETA", "OMEGA"])

    def provider(ticker, decision_cutoff):
        if ticker == "ZETA":
            return [_hold_worthy_event("ZETA", "ACC-ZETA-3", "2026-09-14T21:00:00Z")]
        return [_clean_event("OMEGA", "ACC-OMEGA-1", "2026-09-14T21:00:00Z")]

    rec1 = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat_result,
                                         event_provider=provider)
    assert rec1["inserted"] is True

    # 재실행은 멱등(같은 candidate_set_id 는 다시 쓰지 않는다) — record_candidate_set 규칙을 그대로 물려받는다.
    rec2 = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat_result,
                                         event_provider=provider)
    assert rec2["inserted"] is False
    assert db_session.query(CandidateDecision).filter_by(strategy_version=fvs.SHADOW_STRATEGY_VERSION).count() == 2

    # DB 를 거쳐 다시 읽는 경로(evaluate_filing_veto_shadow_arms 가 frame 없이 session 만 받는 경우)도
    # 에러 없이 동작하고, 아직 outcome 이 채워지지 않았으므로(update_forward_outcomes 를 돌리지 않았다)
    # 적격 표본이 0으로 남아 '미입증'이어야 한다 — 조용히 0으로 치환하지 않는다.
    out = fvs.evaluate_filing_veto_shadow_arms(session=db_session, n_boot=50, n_random_draws=20, seed=1)
    assert out["verdict"] == cl.VERDICT_UNPROVEN
    assert out["n_candidates_recorded"] == 2
    assert out["n_exposed_eligible"] == 2  # ZETA(hold)+OMEGA(pass) 모두 노출됨(둘 다 최근 공시가 있었다)
    assert out["n_held_by_veto"] == 1
    assert out["arm_b_simple_rule_veto"]["groups"]["selected"]["n"] == 0  # outcome 미확정이라 값이 없다
    assert out["arm_a_original_no_veto"]["groups"]["selected"]["n"] == 0


# ---------------------------------------------------------------------------
# (e) 독립 검증 보강 — 요구사항별 재확인 (2026-09-24)
# ---------------------------------------------------------------------------
def test_original_decision_is_copied_not_recomputed(db_session, monkeypatch):
    """요구사항: 원전략 decision 을 재계산하지 않고 그대로 복사한다.

    - satellite_result 를 주면 compute_satellite_recommendation_point_in_time 을 호출조차 하지 않는다
      (호출하면 아래 스텁이 AssertionError 를 던진다 = 재계산 시도 탐지).
    - 원전략이 채택한 종목 집합은 shadow 원장에 그대로 전부 남는다(veto hold 여도 빠지지 않는다).
    - 모든 레코드의 scores.original_decision 은 원전략 결정('selected')이다.
    """
    import core.champion_strategy as cs

    def _boom(*a, **k):  # pragma: no cover - 호출되면 실패해야 한다
        raise AssertionError("원전략 결정을 재계산하면 안 된다")

    monkeypatch.setattr(cs, "compute_satellite_recommendation_point_in_time", _boom, raising=True)

    sat_result = _sat_result(["ZETA", "OMEGA", "GAMMA"])

    def provider(ticker, decision_cutoff):
        if ticker == "GAMMA":
            return [_hold_worthy_event("GAMMA", "ACC-G-1", "2026-09-17T13:00:00Z")]
        return [_clean_event(ticker, f"ACC-{ticker}-1", "2026-09-17T13:00:00Z")]

    fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat_result, event_provider=provider)

    rows = db_session.query(CandidateDecision).filter_by(strategy_version=fvs.SHADOW_STRATEGY_VERSION).all()
    assert {r.ticker for r in rows} == {"ZETA", "OMEGA", "GAMMA"}  # hold 된 종목도 빠지지 않는다
    import json
    for r in rows:
        assert json.loads(r.scores)["original_decision"] == "selected"
    assert {r.ticker for r in rows if r.decision == "held"} == {"GAMMA"}


def test_statistics_are_delegated_to_candidate_ledger(monkeypatch):
    """요구사항: 통계 판정을 자체 구현하지 않고 candidate_ledger.evaluate_selection/decide_verdict 에 위임한다.

    evaluate_selection 을 센티넬로 갈아끼우면 3개 arm 의 판정 필드가 모두 그 반환값을 그대로 통과시켜야
    한다(모듈이 자체 신뢰구간·p 값·판정을 계산하지 않는다는 증거).
    """
    sentinel = {
        "n_decisions": {"selected": 7, "held": 3},
        "groups": {"rest": {"mean": -0.10, "n": 3}, "random_baseline_expected": {"mean": 0.02}},
        "incremental": {"selected_minus_random": {"estimate": 0.5, "ci_low": 0.4, "ci_high": 0.6}},
        "random_baseline_mc": {"p_random_ge_selected": 0.01},
        "verdict": "SENTINEL_VERDICT",
        "verdict_reasons": ["SENTINEL_REASON"],
        "requires_human_approval": True,
    }
    calls = []

    def fake_eval(frame, **kwargs):
        calls.append(frame["decision"].tolist())
        return dict(sentinel)

    monkeypatch.setattr(fvs, "evaluate_selection", fake_eval, raising=True)

    rows = [(1, "A", "selected", "2026-06-01", 0.01), (2, "B", "held", "2026-06-01", -0.2)]
    frame = _shadow_frame(rows)
    out = fvs.evaluate_filing_veto_shadow_arms(frame=frame, exposed_decision_ids={1, 2}, exposed_only=True)

    assert out["verdict"] == "SENTINEL_VERDICT"
    assert out["verdict_reasons"] == ["SENTINEL_REASON"]
    assert out["requires_human_approval"] is True
    assert out["arm_c_random_hold_same_count"]["monte_carlo"] == sentinel["random_baseline_mc"]
    assert out["arm_c_random_hold_same_count"]["incremental_vs_random"]["ci_low"] == 0.4
    # Arm B 는 기록된 라벨 그대로, Arm A 는 전량 selected 로 재표시한 같은 프레임이어야 한다(라벨만 다름).
    assert calls[0] == ["selected", "held"]
    assert calls[1] == ["selected", "selected"]
    # 호출자의 프레임은 변형되지 않는다.
    assert frame["decision"].tolist() == ["selected", "held"]


def test_no_local_statistics_implementation_in_source():
    """소스 검사: 자체 통계 구현(부트스트랩·백분위수·p 값·검정 라이브러리)이 없어야 한다."""
    src = Path(fvs.__file__).read_text(encoding="utf-8")
    for bad in ("scipy", "statsmodels", "percentile", "bootstrap", "ttest", "p_value", "def decide_verdict"):
        assert bad not in src, f"자체 통계 구현 흔적: {bad}"


def test_held_candidates_opportunity_cost_is_included():
    """요구사항: veto 로 보류된 종목의 기회비용이 포함된다.

    candidate_ledger 의 groups.rest / missed_opportunity 가 보류 종목의 사후 수익률이고, ΔEV 점추정치가
    스펙 §9 공식 −(보류수/노출수)×(보류 평균)과 일치해야 한다. 여기서는 보류군이 **플러스**(기회비용이
    실재하는 경우)라 ΔEV 가 음수로 나와야 한다 — 보류를 공짜로 계산하지 않는다는 증거.
    """
    rows = [
        (1, "A", "selected", "2026-06-01", 0.02),
        (2, "B", "selected", "2026-06-01", 0.04),
        (3, "C", "held", "2026-06-01", 0.10),
        (4, "D", "held", "2026-06-02", 0.20),
    ]
    frame = _shadow_frame(rows)
    out = fvs.evaluate_filing_veto_shadow_arms(
        frame=frame, exposed_decision_ids={1, 2, 3, 4}, exposed_only=True,
        n_boot=100, n_random_draws=50, seed=3, require_pit=False)
    arm_b = out["arm_b_simple_rule_veto"]
    assert arm_b["groups"]["rest"]["n"] == 2
    assert arm_b["groups"]["rest"]["mean"] == pytest.approx(0.15)
    assert arm_b["missed_opportunity"]["mean_excess"] == pytest.approx(0.15)
    assert arm_b["warning_flags"]["rest_outperformed_selected"] is True
    assert out["n_held_by_veto"] == 2 and out["n_exposed_eligible"] == 4
    assert out["delta_ev_point_estimate_arm_b_minus_a"] == pytest.approx(-(2 / 4) * 0.15)
    # Arm A(원전략, veto 없음)는 보류 종목까지 포함한 전량 채택 평균이다.
    assert out["arm_a_original_no_veto"]["groups"]["selected"]["mean"] == pytest.approx(0.09)
    assert out["arm_a_original_no_veto"]["groups"]["rest"]["n"] == 0
    # 기회비용을 포함해도 verdict 는 여전히 candidate_ledger 게이트에 따라 '미입증'이다.
    assert out["verdict"] == cl.VERDICT_UNPROVEN


def test_module_never_imports_order_or_scheduler_paths():
    """(d) 확장: 주문 경로·브로커·스케줄러 계열을 어느 것도 import 하지 않는다."""
    tree = ast.parse(Path(fvs.__file__).read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    forbidden = ("core.paper_execution", "scripts.champion_paper_trade", "alpaca", "scheduler",
                 "core.job_schedule", "core.process_registry", "core.trade_ledger")
    bad = [n for n in names for f in forbidden if n == f or n.startswith(f + ".")]
    assert bad == [], f"관측 전용 모듈이 import 하면 안 되는 경로: {bad}"


def test_exposed_only_without_ids_is_empty_and_unproven():
    """exposed_only=True 인데 exposed_decision_ids 가 없으면 조용히 전량 통과시키지 않고 빈 표본 ->
    '미입증' 이어야 한다(게이트 우회 금지)."""
    rows = [(1, "A", "selected", "2026-06-01", 0.01), (2, "B", "held", "2026-06-01", -0.5)]
    out = fvs.evaluate_filing_veto_shadow_arms(
        frame=_shadow_frame(rows), exposed_only=True, n_boot=50, n_random_draws=20, seed=1, require_pit=False)
    assert out["n_candidates_recorded"] == 2 and out["n_exposed_eligible"] == 0
    assert out["verdict"] == cl.VERDICT_UNPROVEN
    assert "no_selected_outcomes" in out["verdict_reasons"]
    assert out["delta_ev_point_estimate_arm_b_minus_a"] is None


def test_fetch_failure_is_counted_as_missing_sample_not_silent_pass(db_session):
    """스펙 §3.3: 조회·비교 실패는 pass 로 묻지 않고 사유별로 센다(그리고 노출 표본에서 빠진다)."""
    sat_result = _sat_result(["BOOM", "NOFILE"])

    def provider(ticker, decision_cutoff):
        if ticker == "BOOM":
            raise RuntimeError("edgar down")
        return []

    out = fvs.record_filing_veto_shadow(AS_OF, session=db_session, satellite_result=sat_result,
                                        event_provider=provider)
    assert out["n_candidates"] == 2 and out["n_exposed"] == 0 and out["n_not_exposed"] == 2
    assert out["n_held_by_veto"] == 0  # veto 판정 불가를 hold 로 잘못 읽지 않는다
    counts = out["unusable_reason_counts"]
    assert counts.get("event_fetch_error") == 1
    assert counts.get("no_filing_found") == 1
    assert out["per_ticker"]["BOOM"]["reason_codes"] == ["event_fetch_error"]
