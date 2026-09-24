"""core/strategy_variants.py — 챔피언 코어 변형 shadow book 테스트 (네트워크 없음, 임시 SQLite·임시 상태 파일).

예상값은 요구사항(hold-band: top4 신규, 기존 보유는 6위 밖일 때만 청산)과 종이 계산에서 정했다.
회전율 예: 슬롯 4, 코어 비중 0.85 -> 종목당 0.2125. 종목 1개 교체 = 2종목 x 0.2125 = 0.425 거래.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import candidate_ledger as cl
from core import strategy_variants as sv
from core.models import CandidateBatch, CandidateDecision, CandidateOutcome

W = 0.85 / 4  # 종목당 비중


# ---------------------------------------------------------------------------
# 순수 함수: 목표 집합
# ---------------------------------------------------------------------------
def test_baseline_is_top4_and_ignores_previous_holdings():
    r = sv.select_targets(list("BCDEAFG"), ["A", "B", "C", "D"], hold_rank=None)
    assert r["targets"] == ["B", "C", "D", "E"]
    assert r["entered"] == ["E"] and r["exited"] == ["A"]


def test_hold_band_keeps_holding_pushed_to_rank5_but_exits_at_rank7():
    prev = ["A", "B", "C", "D"]
    # A 가 5위로 밀림 -> 유지(슬롯이 꽉 차 신규 진입 없음)
    r5 = sv.select_targets(list("BCDEAFG"), prev, hold_rank=6)
    assert sorted(r5["targets"]) == ["A", "B", "C", "D"] and r5["entered"] == [] and r5["exited"] == []
    # 6위도 유지
    r6 = sv.select_targets(list("BCDEFAG"), prev, hold_rank=6)
    assert "A" in r6["targets"] and r6["exited"] == []
    # 7위로 밀리면 청산, 빈 슬롯은 top4 신규 종목이 채움
    r7 = sv.select_targets(list("BCDEFGA"), prev, hold_rank=6)
    assert r7["exited"] == ["A"] and r7["entered"] == ["E"] and sorted(r7["targets"]) == ["B", "C", "D", "E"]


def test_hold_band_new_entries_only_from_top4_and_only_into_vacant_slots():
    # 처음(보유 없음): top4 만
    assert sv.select_targets(list("ABCDEFG"), [], hold_rank=6)["targets"] == ["A", "B", "C", "D"]
    # A,B 보유(현재 5,6위). 빈 슬롯 2개는 top4 안의 C,D 가 채우고, 3~4위 E,F(top4 밖 아님) 는 슬롯 부족으로 못 들어옴
    r = sv.select_targets(list("CDEFAB G".replace(" ", "")), ["A", "B"], hold_rank=6)
    assert sorted(r["targets"]) == ["A", "B", "C", "D"]
    assert "E" not in r["targets"] and "F" not in r["targets"]
    # 5위 종목(신규)은 슬롯이 비어 있어도 top4 가 아니면 진입 불가
    r2 = sv.select_targets(list("CDEFGAB"), ["X"], hold_rank=6)  # X 는 순위 밖(절대모멘텀 탈락) -> 청산
    assert r2["exited"] == ["X"] and r2["targets"] == ["C", "D", "E", "F"]


def test_hold_band_exits_holding_that_fails_absolute_momentum():
    # 보유 A 가 적격 목록에 없음(절대모멘텀 탈락/결측) -> 순위와 무관하게 청산
    r = sv.select_targets(list("BCDEF"), ["A", "B"], hold_rank=6)
    assert r["exited"] == ["A"] and "A" not in r["targets"] and "B" in r["retained"]


# ---------------------------------------------------------------------------
# 기록 흐름 (원전략 추천 mock, 임시 상태 파일, 임시 SQLite)
# ---------------------------------------------------------------------------
def make_rec(order, last_date, fail=(), nan=(), allowed=True):
    rows, mom = [], 30.0
    for t in order:
        rows.append({"ticker": t, "momentum_pct": mom, "last_close": 100.0})
        mom -= 1.0
    for t in fail:
        rows.append({"ticker": t, "momentum_pct": -5.0, "last_close": 100.0})
    for t in nan:
        rows.append({"ticker": t, "momentum_pct": None, "last_close": None})
    ranked = pd.DataFrame(rows)
    ranked["passes_absolute_momentum"] = ranked["momentum_pct"].apply(lambda v: pd.notna(v) and v > 0)
    top4 = list(order[:4])
    return {
        "as_of": last_date, "last_trading_date": last_date, "ranked": ranked, "top4": top4,
        "new_orders_allowed": allowed, "market_filter_status": "above" if allowed else "unknown",
        "cash_weight_from_filter": 0.0, "per_ticker_weights": {t: W for t in top4},
        "allocation_reason": "test", "strategy_version": "test",
    }


@pytest.fixture()
def book(tmp_path, monkeypatch, db_session):
    monkeypatch.setattr(sv, "STATE_CACHE_PATH", tmp_path / "state.json")
    box = {"rec": None}
    monkeypatch.setattr(sv, "_get_core_recommendation", lambda: box["rec"])

    def run(rec):
        box["rec"] = rec
        return sv.record_variant_shadow(session=db_session)

    run.tmp = tmp_path
    return run


def _targets(res, name):
    return sorted(res["variants"][name]["targets"])


def test_hold_band_state_transitions_across_days_persist_in_state_file(book, db_session):
    d1 = book(make_rec(list("ABCDEFGH"), "2026-06-01"))
    assert _targets(d1, "baseline_v1") == list("ABCD") and _targets(d1, "hold_band_v1") == list("ABCD")
    d2 = book(make_rec(list("BCDEAFGH"), "2026-06-02"))  # A 는 5위로 밀림
    assert _targets(d2, "baseline_v1") == list("BCDE")
    assert _targets(d2, "hold_band_v1") == list("ABCD")  # 유지
    d3 = book(make_rec(list("BCDEFGAH"), "2026-06-03"))  # A 는 7위
    assert _targets(d3, "hold_band_v1") == list("BCDE") and d3["variants"]["hold_band_v1"]["exited"] == ["A"]
    # 상태 파일이 실제로 저장돼 다음 프로세스(다음 호출)가 그대로 이어받는다
    saved = json.loads((book.tmp / "state.json").read_text(encoding="utf-8"))
    assert sorted(saved["variants"]["hold_band_v1"]["holdings"]) == list("BCDE")
    assert saved["variants"]["hold_band_v1"]["as_of"] == "2026-06-03"


def test_variants_recorded_in_ledger_under_separate_strategy_versions(book, db_session):
    book(make_rec(list("ABCDEFGH"), "2026-06-01", fail=["I"], nan=["J"]))
    book(make_rec(list("BCDEAFGH"), "2026-06-02", fail=["I"], nan=["J"]))
    versions = {b.strategy_version for b in db_session.query(CandidateBatch)}
    assert versions == {"champion_core/baseline_v1", "champion_core/hold_band_v1"}
    assert db_session.query(CandidateBatch).count() == 4  # 변형 2 x 2일
    hb2 = (db_session.query(CandidateDecision)
           .filter_by(strategy_version="champion_core/hold_band_v1")
           .filter(CandidateDecision.decision_cutoff > pd.Timestamp("2026-06-03").to_pydatetime())
           .all())
    by = {d.ticker: d for d in hb2}
    assert by["A"].decision == "selected" and by["A"].decision_reason.startswith("retained(rank=5)")
    assert by["E"].decision == "held"  # 적격 5위 아래는 아니지만 목표 밖 -> 보류
    assert by["I"].decision == "rejected" and by["J"].decision == "missing_data"
    base2 = (db_session.query(CandidateDecision).filter_by(strategy_version="champion_core/baseline_v1")
             .filter(CandidateDecision.decision_cutoff > pd.Timestamp("2026-06-03").to_pydatetime()).all())
    assert {d.ticker: d.decision for d in base2}["A"] == "held"  # baseline 은 A 를 뺐다
    # 후보 집합은 17자산 코어 전체가 아니라 이번 유니버스 전체(10종목) 를 기록
    assert len(hb2) == 10


def test_original_champion_decision_is_never_changed(book):
    rec = make_rec(list("BCDEAFGH"), "2026-06-02")
    import copy
    snapshot = copy.deepcopy({k: v for k, v in rec.items() if k != "ranked"})
    ranked_before = rec["ranked"].copy()
    book(make_rec(list("ABCDEFGH"), "2026-06-01"))
    res = book(rec)
    assert res["champion_decision_unchanged"] is True
    assert {k: v for k, v in rec.items() if k != "ranked"} == snapshot
    pd.testing.assert_frame_equal(rec["ranked"], ranked_before)
    assert res["champion_top4"] == list("BCDE")
    assert _targets(res, "baseline_v1") == list("BCDE")  # baseline = 원전략 top4 그대로


def test_same_day_rerun_is_idempotent_and_does_not_advance_state_twice(book, db_session):
    book(make_rec(list("ABCDEFGH"), "2026-06-01"))
    first = book(make_rec(list("BCDEFGAH"), "2026-06-02"))  # A 청산
    again = book(make_rec(list("BCDEFGAH"), "2026-06-02"))
    assert _targets(first, "hold_band_v1") == _targets(again, "hold_band_v1") == list("BCDE")
    assert again["variants"]["hold_band_v1"]["ledger"]["inserted"] is False
    assert db_session.query(CandidateBatch).count() == 4  # 2일 x 2변형, 재실행은 늘리지 않음
    # 재실행이 '직전 보유 = 오늘 보유'로 오인하면 결과가 달라질 수 있는 시나리오: 여전히 같은 진입/청산 목록
    assert again["variants"]["hold_band_v1"]["exited"] == ["A"] and again["variants"]["hold_band_v1"]["entered"] == ["E"]


def test_market_filter_unknown_records_nothing_and_keeps_state(book, db_session):
    book(make_rec(list("ABCDEFGH"), "2026-06-01"))
    before = (book.tmp / "state.json").read_text(encoding="utf-8")
    res = book(make_rec(list("BCDEFGAH"), "2026-06-02", allowed=False))
    assert res["status"] == "skipped_new_orders_blocked" and res["variants"] == {}
    assert (book.tmp / "state.json").read_text(encoding="utf-8") == before
    assert db_session.query(CandidateBatch).count() == 2


def test_stale_as_of_is_not_applied(book):
    book(make_rec(list("ABCDEFGH"), "2026-06-05"))
    res = book(make_rec(list("BCDEFGAH"), "2026-06-02"))  # 과거 날짜로 되돌아온 실행
    assert res["variants"]["hold_band_v1"]["status"] == "stale_as_of"


def test_corrupt_state_is_preserved_and_reported_not_silently_reset(book):
    p = book.tmp / "state.json"
    p.write_text("{not json", encoding="utf-8")
    res = book(make_rec(list("ABCDEFGH"), "2026-06-01"))
    assert res["state_reset"] and "preserved" in res["state_reset"]
    assert any(x.name.startswith("state.json.corrupt-") for x in book.tmp.iterdir())
    assert _targets(res, "hold_band_v1") == list("ABCD")


# ---------------------------------------------------------------------------
# 회전율 · 비용
# ---------------------------------------------------------------------------
def test_turnover_and_cost_hand_calc_hold_band_avoids_flapping_swaps(book):
    book(make_rec(list("ABCDEFGH"), "2026-06-01"))
    book(make_rec(list("BCDEAFGH"), "2026-06-02"))  # A 5위: baseline 은 A<->E 교체
    book(make_rec(list("ABCDEFGH"), "2026-06-03"))  # A 복귀: baseline 은 E<->A 재교체
    t = sv.compare_turnover()
    b, h = t["variants"]["baseline_v1"], t["variants"]["hold_band_v1"]
    assert b["n_transitions"] == h["n_transitions"] == 2
    # baseline: 교체 2회 x (2종목 x 0.2125) = 0.85, 거래 종목 수 4
    assert b["traded_notional_sum"] == pytest.approx(0.85) and b["trades"] == 4
    assert b["entries"] == 2 and b["exits"] == 2
    assert h["traded_notional_sum"] == pytest.approx(0.0) and h["trades"] == 0
    assert b["avg_one_way_turnover_per_transition"] == pytest.approx(0.85 / 2 / 2)
    # 비용(편도 bp = 수수료+슬리피지: 5/10/25) : 거래 비중 x bp
    assert b["cost_drag_bp_of_nav"]["5bp"] == pytest.approx(0.85 * 5)
    assert b["cost_drag_bp_of_nav"]["10bp"] == pytest.approx(0.85 * 10)
    assert b["cost_drag_bp_of_nav"]["25bp"] == pytest.approx(0.85 * 25)
    d = t["difference"]
    assert d["trades"] == -4 and d["cost_drag_bp_of_nav"]["10bp"] == pytest.approx(-8.5)
    assert "assumed" in t["cost_source"]  # core.cost_calibration 이 없으면 가정값
    assert "수익" in t["note"]  # 수익 비교가 아님을 명시


def test_cost_calibration_is_optional_and_used_when_present(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("core.cost_calibration")
    fake.calibrated_one_way_bps = lambda: 7.5
    monkeypatch.setitem(sys.modules, "core.cost_calibration", fake)
    import core
    monkeypatch.setattr(core, "cost_calibration", fake, raising=False)
    a = sv._cost_assumptions()
    assert a["scenarios_one_way_bps"]["calibrated"] == 7.5 and "measured" in a["source"]
    # 잘못된 값이면 가정값으로 복귀
    fake.calibrated_one_way_bps = lambda: float("nan")
    assert "calibrated" not in sv._cost_assumptions()["scenarios_one_way_bps"]


# ---------------------------------------------------------------------------
# 리포트: 미입증, 정직한 문구, 파일 생성
# ---------------------------------------------------------------------------
def test_report_is_unproven_with_small_sample_and_writes_files(book, db_session, tmp_path):
    book(make_rec(list("ABCDEFGH"), "2026-06-01"))
    book(make_rec(list("BCDEAFGH"), "2026-06-02"))
    rep = sv.write_research_report(out_dir=tmp_path / "reports", session=db_session, as_of="2026-06-30")
    assert Path(rep["md_path"]).name == "strategy_research_2026-06-30.md"
    assert Path(rep["json_path"]).name == "strategy_research_2026-06-30.json"
    payload = json.loads(Path(rep["json_path"]).read_text(encoding="utf-8"))
    for name in ("baseline_v1", "hold_band_v1"):
        v = payload["variants"][name]
        assert v["batches_recorded"] == 2 and v["decisions_recorded"] == 16  # 2일 x 8종목
        assert v["verdict"] == cl.VERDICT_UNPROVEN and v["verdict_reasons"]
        assert v["final_samples_primary"]["selected"] == 0  # 아직 확정 결과 없음
    md = Path(rep["md_path"]).read_text(encoding="utf-8")
    assert "관측 전용" in md and "미입증" in md and "회전율" in md and "비용 영향" in md
    assert "개선했다" not in md and "우수" not in md


def test_report_counts_final_samples_after_outcomes_but_stays_unproven(book, db_session, tmp_path):
    book(make_rec(list("ABCDEFGH"), "2026-06-01"))
    idx = pd.bdate_range("2026-06-01", periods=70)

    def frame():
        o = pd.Series(100.0, index=idx)
        return pd.DataFrame({"Open": o, "Close": o, "High": o, "Low": o, "Volume": 1.0}, index=idx)

    frames = {t: frame() for t in list("ABCDEFGH") + ["SPY"]}
    cl.update_forward_outcomes(idx[-1].date(), price_provider=lambda t, s, e: frames.get(t, pd.DataFrame()),
                               session=db_session)
    assert db_session.query(CandidateOutcome).filter_by(status="final", horizon_days=20).count() > 0
    rep = sv.write_research_report(out_dir=tmp_path, session=db_session, as_of="2026-09-30")
    v = rep["variants"]["hold_band_v1"]
    assert v["final_samples_primary"]["selected"] == 4 and v["final_samples_primary"]["rest"] == 4
    assert v["verdict"] == cl.VERDICT_UNPROVEN  # 표본 1일 + PIT 미인증
    assert any(r.startswith("insufficient_sample") for r in v["verdict_reasons"])
    assert "not_pit_certified" in v["verdict_reasons"]


def test_module_has_no_order_path_or_intraday_dependency():
    src = Path(sv.__file__).read_text(encoding="utf-8")
    assert "paper_execution" not in src.replace("core.paper_execution, scripts", "")  # docstring 언급만 허용
    assert "import paper_execution" not in src and "from core.paper_execution" not in src
    assert "1m" not in src and "intraday" not in src.lower().replace("일봉 전용", "")
