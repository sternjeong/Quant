"""core/guidance_shadow.py (RES-04 개별주 위성 shadow) 테스트.

원칙: 실제 SEC 네트워크 호출이나 실제 compute_satellite_recommendation_point_in_time 전체 스캔은
하지 않는다. 위성 원전략 결과는 satellite_result 인자로 직접 주입하고, 가이던스 관측은 합성
GuidanceChange/GuidanceItem으로 만든다. 예상값은 이 테스트 파일 안에서 독립적으로 정한다.
"""

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from core import guidance_shadow as gs
from core.candidate_ledger import (
    MIN_SELECTED_FOR_VERDICT,
    VERDICT_UNPROVEN,
    champion_satellite_to_candidate_set,
)
from core.earnings_events import GuidanceChange, GuidanceItem
from core.models import CandidateDecision

AS_OF = date(2026, 6, 10)
CUTOFF = "2026-06-10"


def _item(metric="revenue", acceptance=None, low="1000", high="1100", accession="0000000001-26-000001"):
    return GuidanceItem(
        cik="0000000001",
        accession=accession,
        acceptance_utc=acceptance,
        source_url="https://example.test/doc",
        metric=metric,
        basis="gaap",
        period_key="FY2026",
        period_raw="fiscal 2026",
        shape="range",
        low=Decimal(low),
        high=Decimal(high),
        unit="currency" if metric != "eps" else "per_share",
        currency="USD" if metric != "eps" else None,
        anchor="We now expect revenue of $1.0 billion to $1.1 billion.",
    )


def _change(label, *, metric="revenue", acceptance=None, mid_change_pct="5.0", accession="0000000001-26-000001"):
    current = _item(metric=metric, acceptance=acceptance, accession=accession)
    return GuidanceChange(
        change=label, reason="midpoint_comparison" if label != "unknown" else "no_previous_in_retrieved_history",
        current=current, mid_change_pct=Decimal(mid_change_pct) if mid_change_pct is not None else None,
    )


RECENT = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)  # cutoff(6/10)로부터 약 9일 전 -> 20거래일 창 안
TOO_OLD = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)  # 20거래일 창 밖


# ---------------------------------------------------------------------------
# (a) feature 계산: raised/lowered가 올바르게 반영되는가
# ---------------------------------------------------------------------------
def test_raised_guidance_reflected_in_feature():
    obs = gs.GuidanceObservation("AAA", _change("raised", acceptance=RECENT, mid_change_pct="5.0"), RECENT)
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [obs])
    assert feature.basis_status == gs.BASIS_CLEAR
    assert feature.veto_flag is False
    assert feature.latest_change == "raised"
    assert feature.change_magnitude_pct == 5.0
    assert feature.matched_metrics == ("revenue",)
    assert feature.n_observations_in_window == 1


def test_lowered_guidance_sets_veto_flag():
    obs = gs.GuidanceObservation("AAA", _change("lowered", acceptance=RECENT, mid_change_pct="-8.0"), RECENT)
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [obs])
    assert feature.veto_flag is True
    assert feature.basis_status == gs.BASIS_CLEAR
    assert feature.latest_change == "lowered"
    assert feature.change_magnitude_pct == -8.0


def test_withdrawn_without_raise_sets_veto_flag_even_if_older_raise_exists_outside_window():
    # 창 밖의 raised는 쓰지 않는다 -> 창 안에 withdrawn만 있으면 veto.
    old_raise = gs.GuidanceObservation("AAA", _change("raised", acceptance=TOO_OLD), TOO_OLD)
    recent_withdrawn = gs.GuidanceObservation(
        "AAA", _change("withdrawn", acceptance=RECENT, mid_change_pct=None), RECENT)
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [old_raise, recent_withdrawn])
    assert feature.veto_flag is True
    assert feature.n_observations_in_window == 1  # old_raise는 창 밖이라 제외


def test_no_release_when_only_observation_is_outside_lookback_window():
    obs = gs.GuidanceObservation("AAA", _change("lowered", acceptance=TOO_OLD), TOO_OLD)
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [obs])
    assert feature.basis_status == gs.BASIS_NO_RELEASE
    assert feature.veto_flag is False
    assert feature.n_observations_in_window == 0


def test_no_release_when_no_observations_given():
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [])
    assert feature.basis_status == gs.BASIS_NO_RELEASE
    assert feature.latest_change is None


def test_unknown_only_does_not_set_veto_and_does_not_guess_direction():
    obs = gs.GuidanceObservation("AAA", _change("unknown", acceptance=RECENT, mid_change_pct=None), RECENT)
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [obs])
    assert feature.basis_status == gs.BASIS_UNKNOWN
    assert feature.veto_flag is False


def test_non_primary_metric_is_excluded_from_feature():
    # gross_margin은 스펙 3절 주 가설의 revenue/eps가 아니므로 제외된다.
    obs = gs.GuidanceObservation(
        "AAA", _change("lowered", metric="gross_margin", acceptance=RECENT, mid_change_pct="-3.0"), RECENT)
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [obs])
    assert feature.basis_status == gs.BASIS_NO_RELEASE
    assert feature.veto_flag is False


def test_future_available_at_is_never_used():
    future = datetime(2026, 6, 20, tzinfo=timezone.utc)  # decision_cutoff(6/10) 이후
    obs = gs.GuidanceObservation("AAA", _change("lowered", acceptance=future, mid_change_pct="-8.0"), future)
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [obs])
    assert feature.basis_status == gs.BASIS_NO_RELEASE


def test_guidance_feature_to_scores_is_json_roundtrippable():
    obs = gs.GuidanceObservation("AAA", _change("raised", acceptance=RECENT, mid_change_pct="5.0"), RECENT)
    feature = gs.compute_guidance_feature("AAA", CUTOFF, [obs])
    scores = gs.guidance_feature_to_scores(feature)
    dumped = json.dumps(scores)  # 예외 없이 직렬화돼야 한다(원장 저장 전제)
    back = json.loads(dumped)
    assert back["guidance_latest_change"] == "raised"
    assert back["guidance_veto_flag"] is False


# ---------------------------------------------------------------------------
# (b) 원전략 결정이 shadow 기록으로 절대 바뀌지 않는다
# ---------------------------------------------------------------------------
def _satellite_result(new_orders_allowed=True):
    return {
        "as_of": CUTOFF, "rebal_date": "2026-01-02", "selected": ["AAA", "BBB"],
        "per_ticker_weights": {"AAA": 0.05, "BBB": 0.05} if new_orders_allowed else {},
        "sizing_method": "equal", "new_orders_allowed": new_orders_allowed,
        "allocation_reason": "ok" if new_orders_allowed else "spy_data_unknown",
    }


def test_same_satellite_result_produces_identical_original_decisions_regardless_of_guidance():
    """같은 satellite 결과를 원전략 어댑터와 shadow 어댑터에 각각 넣었을 때, decision/decision_reason이
    가이던스 feature(raised든 lowered든)와 무관하게 완전히 같아야 한다 — 이것이 '원전략을 바꾸지
    않는다'는 요구사항의 직접 증거다."""
    result = _satellite_result(new_orders_allowed=True)
    base_set = champion_satellite_to_candidate_set(
        result, strategy_version="champion_satellite/equal", decision_cutoff=CUTOFF)

    events = {
        "AAA": [gs.GuidanceObservation("AAA", _change("raised", acceptance=RECENT, mid_change_pct="9.0"), RECENT)],
        "BBB": [gs.GuidanceObservation("BBB", _change("lowered", acceptance=RECENT, mid_change_pct="-9.0"), RECENT)],
    }
    shadow_set = gs.build_guidance_shadow_candidate_set(
        result, base_strategy_version="champion_satellite/equal", decision_cutoff=CUTOFF, events_by_ticker=events)

    base_by_ticker = {r.ticker: (r.decision, r.decision_reason) for r in base_set.records}
    shadow_by_ticker = {r.ticker: (r.decision, r.decision_reason) for r in shadow_set.records}
    assert base_by_ticker == shadow_by_ticker
    assert base_by_ticker["AAA"][0] == "selected"

    # feature는 scores에만 얹힌다 — decision과 무관.
    shadow_scores = {r.ticker: r.scores for r in shadow_set.records}
    assert shadow_scores["AAA"]["guidance_latest_change"] == "raised"
    assert shadow_scores["BBB"]["guidance_latest_change"] == "lowered"
    assert shadow_scores["BBB"]["guidance_veto_flag"] is True
    # 그런데도 BBB의 decision은 AAA와 마찬가지로 원전략이 정한 'selected' 그대로다.
    assert shadow_by_ticker["BBB"][0] == "selected"

    # shadow 행에는 order_proposal을 싣지 않는다(주문 제안이 아님을 구조적으로 보장).
    assert all(r.order_proposal is None for r in shadow_set.records)


def test_blocked_new_orders_still_mirrors_original_held_decision_with_veto_feature():
    """new_orders_allowed=False(데이터 부족 보류)일 때도 shadow는 원전략과 똑같이 held로 기록해야
    하며, 이때도 가이던스가 lowered여도 decision을 바꾸지 않는다."""
    result = _satellite_result(new_orders_allowed=False)
    base_set = champion_satellite_to_candidate_set(
        result, strategy_version="champion_satellite/equal", decision_cutoff=CUTOFF)
    events = {
        "AAA": [gs.GuidanceObservation("AAA", _change("lowered", acceptance=RECENT, mid_change_pct="-9.0"), RECENT)],
    }
    shadow_set = gs.build_guidance_shadow_candidate_set(
        result, base_strategy_version="champion_satellite/equal", decision_cutoff=CUTOFF, events_by_ticker=events)

    base_by_ticker = {r.ticker: (r.decision, r.decision_reason) for r in base_set.records}
    shadow_by_ticker = {r.ticker: (r.decision, r.decision_reason) for r in shadow_set.records}
    assert base_by_ticker == shadow_by_ticker
    assert shadow_by_ticker["AAA"][0] == "held"
    aaa_scores = {r.ticker: r.scores for r in shadow_set.records}["AAA"]
    assert aaa_scores["guidance_veto_flag"] is True  # feature는 계산됐지만 decision은 그대로 held


# ---------------------------------------------------------------------------
# (c) 3개 비교군: 표본 미달이면 항상 '미입증'
# ---------------------------------------------------------------------------
def _small_synthetic_frame(n=10, n_selected=3):
    rng = np.random.default_rng(7)
    decisions = ["selected"] * n_selected + ["held"] * (n - n_selected)
    changes = (["raised"] * 2 + ["lowered"] * 2 + ["maintained"] * (n - 4))[:n]
    return pd.DataFrame({
        "decision_id": range(1, n + 1),
        "candidate_set_id": ["cs1"] * n,
        "ticker": [f"T{i}" for i in range(n)],
        "strategy_version": [gs.GUIDANCE_SHADOW_STRATEGY_VERSION] * n,
        "source": [gs.GUIDANCE_SHADOW_SOURCE] * n,
        "decision": decisions,
        "decision_date": pd.to_datetime([f"2026-01-{(i % 28) + 1:02d}" for i in range(n)]),
        "sector": [None] * n,
        "pit_certified": [False] * n,
        "horizon_days": [20] * n,
        "status": ["final"] * n,
        "status_reason": [None] * n,
        "entry_date": [None] * n,
        "exit_date": [None] * n,
        "gross_return": rng.normal(0, 0.05, n),
        "net_return": rng.normal(0, 0.05, n),
        "benchmark_return": rng.normal(0, 0.02, n),
        "sector_etf_return": [np.nan] * n,
        "net_excess_spy": rng.normal(0, 0.05, n),
        "net_excess_sector": [np.nan] * n,
        "guidance_basis_status": ["clear"] * n,
        "guidance_veto_flag": [False] * n,
        "guidance_latest_change": changes,
        "guidance_change_magnitude_pct": [1.0] * n,
    })


def test_all_three_comparisons_are_unproven_when_sample_below_minimum(monkeypatch):
    assert 10 < MIN_SELECTED_FOR_VERDICT  # 이 테스트의 전제(스펙 6절 게이트 미달)를 명시한다
    frame = _small_synthetic_frame(n=10, n_selected=3)
    monkeypatch.setattr(gs, "load_guidance_feature_frame", lambda *a, **k: frame)

    results = gs.evaluate_guidance_comparisons(session=None)

    assert set(results.keys()) == set(gs.COMPARISON_NAMES)
    for name, report in results.items():
        assert report["verdict"] == VERDICT_UNPROVEN, f"{name} 는 표본 미달이면 항상 미입증이어야 한다"
        assert report["auto_decision"] is False


def test_raised_only_relabel_keeps_missing_data_untouched():
    frame = _small_synthetic_frame(n=6, n_selected=2)
    frame.loc[0, "decision"] = "missing_data"
    frame.loc[0, "guidance_latest_change"] = "raised"  # missing_data는 raised여도 selected로 바뀌면 안 된다
    relabeled = gs._relabel_raised_only(frame)
    assert relabeled.loc[0, "decision"] == "missing_data"
    # raised인 나머지 eligible 행은 selected가 된다.
    raised_eligible = frame[(frame["decision"] != "missing_data") & (frame["guidance_latest_change"] == "raised")]
    for idx in raised_eligible.index:
        assert relabeled.loc[idx, "decision"] == "selected"


def test_random_same_count_relabel_preserves_selected_count_and_is_deterministic():
    frame = _small_synthetic_frame(n=10, n_selected=3)
    r1 = gs._relabel_random_same_count(frame, seed=123)
    r2 = gs._relabel_random_same_count(frame, seed=123)
    assert (r1["decision"] == r2["decision"]).all()  # 같은 시드 -> 같은 결과(재현 가능)
    assert int((r1["decision"] == "selected").sum()) == 3


def test_empty_frame_yields_unproven_without_crashing(monkeypatch):
    empty = _small_synthetic_frame(n=0, n_selected=0)
    monkeypatch.setattr(gs, "load_guidance_feature_frame", lambda *a, **k: empty)
    results = gs.evaluate_guidance_comparisons(session=None)
    for report in results.values():
        assert report["verdict"] == VERDICT_UNPROVEN


# ---------------------------------------------------------------------------
# (d) DB 왕복 (임시 SQLite, tests/conftest.py의 db_session fixture)
# ---------------------------------------------------------------------------
def test_record_guidance_shadow_round_trips_through_db(db_session):
    result = _satellite_result(new_orders_allowed=True)
    events = {
        "AAA": [gs.GuidanceObservation("AAA", _change("raised", acceptance=RECENT, mid_change_pct="6.0"), RECENT)],
    }
    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=result, events_by_ticker=events)

    assert out["ok"] is True
    assert out["n_pool"] == 2  # AAA, BBB
    assert out["n_with_events_provided"] == 1
    assert out["inserted"] is True

    rows = db_session.query(CandidateDecision).filter_by(source=gs.GUIDANCE_SHADOW_SOURCE).all()
    assert len(rows) == 2
    by_ticker = {r.ticker: r for r in rows}
    assert by_ticker["AAA"].strategy_version == gs.GUIDANCE_SHADOW_STRATEGY_VERSION
    assert by_ticker["AAA"].decision == "selected"  # 원전략 결정 그대로
    aaa_scores = json.loads(by_ticker["AAA"].scores)
    assert aaa_scores["guidance_latest_change"] == "raised"
    assert aaa_scores["guidance_veto_flag"] is False
    bbb_scores = json.loads(by_ticker["BBB"].scores)
    assert bbb_scores["guidance_basis_status"] == "no_release"  # 이벤트를 주지 않은 티커

    frame = gs.load_guidance_feature_frame(db_session, strategy_version=gs.GUIDANCE_SHADOW_STRATEGY_VERSION)
    assert len(frame) == 2
    frame_by_ticker = frame.set_index("ticker")
    assert frame_by_ticker.loc["AAA", "guidance_latest_change"] == "raised"
    assert frame_by_ticker.loc["BBB", "guidance_basis_status"] == "no_release"


def test_record_guidance_shadow_rerun_same_day_is_idempotent(db_session):
    result = _satellite_result(new_orders_allowed=True)
    r1 = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=result, events_by_ticker={})
    r2 = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=result, events_by_ticker={})
    assert r1["inserted"] is True
    assert r2["inserted"] is False
    assert r2["conflict"] is False
    rows = db_session.query(CandidateDecision).filter_by(source=gs.GUIDANCE_SHADOW_SOURCE).count()
    assert rows == 2  # 중복 없음


def test_record_guidance_shadow_reports_satellite_failure_without_raising(db_session, monkeypatch):
    def boom(**kw):
        raise RuntimeError("satellite unavailable")

    monkeypatch.setattr("core.champion_strategy.compute_satellite_recommendation_point_in_time", boom)
    out = gs.record_guidance_shadow(AS_OF, session=db_session, satellite_result=None, events_by_ticker={})
    assert out["ok"] is False
    assert "satellite unavailable" in out["error"]
    rows = db_session.query(CandidateDecision).filter_by(source=gs.GUIDANCE_SHADOW_SOURCE).count()
    assert rows == 0  # 실패했으므로 아무것도 기록되지 않는다


def test_module_never_imports_order_path():
    import ast
    from pathlib import Path

    src = Path(gs.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    bad = [n for n in names if n.startswith("core.paper_execution") or n.startswith("scripts.champion_paper_trade")]
    assert bad == [], f"주문 경로를 import 하면 안 된다: {bad}"
