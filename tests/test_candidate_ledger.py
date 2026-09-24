"""core/candidate_ledger.py (RES-01: 모든 후보 shadow 원장) 테스트.

원칙: 예상값은 구현이 아니라 요구사항과 종이 계산으로 정했다.
- 합성 가격은 손으로 따라갈 수 있게 대부분 상수이고, 진입/청산 봉만 다른 값이다.
  Close 는 일부러 Open 과 크게 다르게 두었다(Close 로 계산하면 테스트가 실패하도록).
- 비용 예상값은 core.trade_ledger 문서에 적힌 체결 모델(매수 시가*(1+슬리피지)*(1+수수료),
  매도 시가*(1-슬리피지)*(1-수수료))에서 종이로 유도한 식이며, trade_ledger 의 독립 구현
  (run_cost_scenarios)과도 대조한다.
- 이 테스트는 성과·승률 개선을 주장하지 않는다. 관측 인프라의 계산 규칙만 검증한다.
"""

import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from core import candidate_ledger as cl
from core.models import CandidateBatch, CandidateDecision, CandidateOutcome
from core.trade_ledger import COST_SCENARIOS_BPS, run_cost_scenarios

# ---------------------------------------------------------------------------
# 합성 가격
# ---------------------------------------------------------------------------
N = 70
IDX = pd.bdate_range("2026-06-01", periods=N)  # 0=6/1(월) 1=6/2(화) ... 5=6/8(월) 6=6/9(화)
AS_OF = IDX[-1].date()

# 종이 계산용 (수수료bp, 슬리피지bp) — trade_ledger.COST_SCENARIOS_BPS 문서 값
FEE_SLIP = {"5bp": (2.0, 3.0), "10bp": (4.0, 6.0), "25bp": (10.0, 15.0)}


def paper_net(ratio, name):
    """왕복 1단위 명목: 매수 1/(1+s)(1+f) 주, 매도 (1-s)(1-f) -> ratio*(1-s)(1-f)/((1+s)(1+f)) - 1."""
    f, s = (x / 1e4 for x in FEE_SLIP[name])
    return ratio * (1 - s) * (1 - f) / ((1 + s) * (1 + f)) - 1


def _vals(default, overrides=None):
    v = [float(default)] * N
    for i, x in (overrides or {}).items():
        v[i] = float(x)
    return v


def px(vals, index=None):
    index = IDX if index is None else index
    o = pd.Series(vals, index=index, dtype=float)
    return pd.DataFrame(
        {"Open": o, "High": o + 20, "Low": o - 5, "Close": o + 7, "Adj Close": o + 7, "Volume": 1000.0},
        index=index,
    )


SPY = px(_vals(400, {1: 400, 6: 404, 21: 408, 61: 420}))  # 5d +1%, 20d +2%, 60d +5%
XLK = px(_vals(50, {6: 51, 21: 52.5, 61: 45}))  # 5d +2%, 20d +5%, 60d -10%
# 종목 A: idx0 시가 90 은 미끼(진입은 idx1=100). 5d +10%, 20d +20%, 60d -10%
STOCK_A = px(_vals(100, {0: 90, 6: 110, 21: 120, 61: 90}))
STOCK_B = px(_vals(100, {21: 105}))  # 20d +5%
STOCK_C = px(_vals(100, {21: 96}))  # 20d -4%


def provider_for(frames, raises=()):
    def _p(ticker, start, end):
        if ticker in raises:
            raise RuntimeError("provider boom")
        f = frames.get(ticker)
        return pd.DataFrame() if f is None else f

    return _p


# ---------------------------------------------------------------------------
# 사전 고정 상수
# ---------------------------------------------------------------------------
def test_preregistered_constants():
    assert cl.PRIMARY_HORIZON_DAYS == 20
    assert set(cl.DIAGNOSTIC_HORIZONS) == {5, 60}
    assert set(cl.ALL_HORIZONS) == {5, 20, 60}
    assert cl.PRIMARY_COST_SCENARIO in COST_SCENARIOS_BPS
    assert cl.BENCHMARK_TICKER == "SPY"
    assert cl.PRIMARY_TARGET == "net_excess_spy"
    assert set(cl.DECISIONS) == {"selected", "held", "rejected", "missing_data"}


# ---------------------------------------------------------------------------
# 시간 계약: 진입 세션 결정
# ---------------------------------------------------------------------------
def test_resolve_entry_position_date_only_is_next_session():
    assert cl.resolve_entry_position(IDX, "2026-06-01") == 1  # 월요일 종가 후 결정 -> 화요일 시가
    assert cl.resolve_entry_position(IDX, date(2026, 6, 1)) == 1
    assert cl.resolve_entry_position(IDX, "2026-06-05") == 5  # 금요일 -> 월요일(6/8)


def test_resolve_entry_position_intraday_cutoff_vs_open():
    # 6월은 EDT(UTC-4): 개장 09:30 EDT = 13:30 UTC. 6/2(idx1)
    assert cl.resolve_entry_position(IDX, datetime(2026, 6, 2, 13, 0)) == 1  # 09:00 EDT, 개장 전 -> 당일 시가
    assert cl.resolve_entry_position(IDX, datetime(2026, 6, 2, 14, 0)) == 2  # 10:00 EDT, 개장 후 -> 다음날
    assert cl.resolve_entry_position(IDX, datetime(2026, 6, 2, 13, 30)) == 2  # 정확히 개장 시각은 체결 불가(엄격)
    assert cl.resolve_entry_position(IDX, datetime(2026, 6, 6, 12, 0)) == 5  # 토요일 -> 월요일
    ny = pd.Timestamp("2026-06-02 16:00", tz="America/New_York")
    assert cl.resolve_entry_position(IDX, ny) == 2  # tz-aware 도 동일 규칙


def test_resolve_entry_position_handles_dst_winter():
    winter = pd.bdate_range("2026-01-05", periods=5)  # EST(UTC-5): 개장 14:30 UTC
    assert cl.resolve_entry_position(winter, datetime(2026, 1, 5, 14, 0)) == 0  # 09:00 EST
    assert cl.resolve_entry_position(winter, datetime(2026, 1, 5, 15, 0)) == 1  # 10:00 EST


def test_resolve_entry_position_none_when_no_session_after_cutoff():
    assert cl.resolve_entry_position(IDX, IDX[-1].date()) is None  # 마지막 봉 이후 세션 없음


# ---------------------------------------------------------------------------
# 진입=다음 시가, 청산=진입+N거래일 시가, 비용, 초과수익
# ---------------------------------------------------------------------------
def test_entry_is_next_session_open_not_cutoff_day_bar():
    out = cl.compute_outcome("2026-06-01", 5, STOCK_A, SPY, XLK, as_of=AS_OF)
    assert out["status"] == "final"
    assert out["entry_date"] == date(2026, 6, 2)
    assert out["entry_open"] == 100.0  # idx0 의 90 이 아니다
    assert out["exit_date"] == IDX[6].date()  # 진입 idx1 + 5거래일 = idx6
    assert out["exit_open"] == 110.0  # 종가(117)가 아니라 시가
    assert out["gross_return"] == pytest.approx(0.10)
    assert out["benchmark_return"] == pytest.approx(0.01)  # SPY 400 -> 404, 같은 진입/청산 시가
    assert out["sector_etf_return"] == pytest.approx(0.02)  # XLK 50 -> 51


def test_costs_match_paper_formula_for_all_scenarios():
    out = cl.compute_outcome("2026-06-01", 5, STOCK_A, SPY, XLK, as_of=AS_OF)
    assert set(out["net_returns"]) == set(COST_SCENARIOS_BPS)
    for name in COST_SCENARIOS_BPS:
        assert out["net_returns"][name] == pytest.approx(paper_net(1.10, name), abs=1e-12)
    # 종이 감각 점검: 편도 10bp 왕복 약 20bp 이므로 10% 총수익이 약 9.78% 로 줄어든다
    assert out["net_returns"]["10bp"] == pytest.approx(0.0978, abs=2e-4)
    assert out["net_returns"]["5bp"] > out["net_returns"]["10bp"] > out["net_returns"]["25bp"]


def test_costs_match_independent_trade_ledger_round_trip():
    """trade_ledger.run_cost_scenarios(독립 구현)의 왕복 순수익과 같아야 한다."""
    out = cl.compute_outcome("2026-06-01", 5, STOCK_A, SPY, XLK, as_of=AS_OF)
    df = STOCK_A.iloc[:7]
    pos = pd.Series([1, 1, 1, 1, 1, 0, 0], index=df.index, dtype=float)  # idx1 시가 매수, idx6 시가 매도
    res = run_cost_scenarios(df, pos, initial_cash=100.0)
    for name in COST_SCENARIOS_BPS:
        assert res[name].ledger["fill_time"].tolist() == [IDX[1], IDX[6]]
        led_net = res[name].nav.iloc[-1] / 100.0 - 1.0
        assert out["net_returns"][name] == pytest.approx(led_net, abs=1e-9)


def test_exit_horizons_20_and_60_use_open_n_sessions_after_entry():
    o20 = cl.compute_outcome("2026-06-01", 20, STOCK_A, SPY, XLK, as_of=AS_OF)
    assert o20["exit_date"] == IDX[21].date() and o20["exit_open"] == 120.0
    assert o20["gross_return"] == pytest.approx(0.20)
    assert o20["benchmark_return"] == pytest.approx(0.02)
    o60 = cl.compute_outcome("2026-06-01", 60, STOCK_A, SPY, XLK, as_of=AS_OF)
    assert o60["exit_date"] == IDX[61].date() and o60["exit_open"] == 90.0
    assert o60["gross_return"] == pytest.approx(-0.10)
    assert o60["sector_etf_return"] == pytest.approx(-0.10)  # XLK 50 -> 45


def test_intraday_cutoff_before_open_enters_same_day_open():
    # 13:00 UTC = 09:00 EDT 6/2 -> 진입은 6/2(idx1) 시가. 종이: 100 -> 110(idx6)이 아니라 5거래일 뒤 idx6
    out = cl.compute_outcome(datetime(2026, 6, 2, 13, 0), 5, STOCK_A, SPY, XLK, as_of=AS_OF)
    assert out["entry_date"] == date(2026, 6, 2)
    later = cl.compute_outcome(datetime(2026, 6, 2, 14, 0), 5, STOCK_A, SPY, XLK, as_of=AS_OF)
    assert later["entry_date"] == date(2026, 6, 3)


def test_bars_after_as_of_are_never_used():
    as_of = IDX[10].date()  # 6/15. 20일 청산(idx21)은 아직 도래하지 않음
    out = cl.compute_outcome("2026-06-01", 20, STOCK_A, SPY, XLK, as_of=as_of)
    assert out["status"] == "pending" and out["reason"] == "horizon_not_reached"
    assert out["gross_return"] is None and out["exit_open"] is None
    assert all(v is None for v in out["net_returns"].values())
    # 5일은 이미 도래(idx6 <= idx10)
    assert cl.compute_outcome("2026-06-01", 5, STOCK_A, SPY, XLK, as_of=as_of)["status"] == "final"


def test_sector_etf_missing_is_null_not_zero():
    out = cl.compute_outcome("2026-06-01", 5, STOCK_A, SPY, None, as_of=AS_OF)
    assert out["status"] == "final"
    assert out["sector_etf_return"] is None
    assert out["detail"]["sector_note"] == "sector_etf_unavailable"


# ---------------------------------------------------------------------------
# 결측 사유 (조용한 0 처리 금지)
# ---------------------------------------------------------------------------
def test_delisted_stock_is_missing_with_reason_after_grace():
    delisted = STOCK_A.iloc[:25]  # idx24 까지만 존재. 60일 청산(idx61)은 데이터 없음. 벤치마크는 idx69 까지
    out = cl.compute_outcome("2026-06-01", 60, delisted, SPY, XLK, as_of=AS_OF)
    assert out["status"] == "missing" and out["reason"] == "data_ended_before_exit"
    assert out["gross_return"] is None and out["net_returns"]["10bp"] is None
    assert out["detail"]["ticker_last_bar"] == IDX[24].date().isoformat()
    # 20일(idx21)은 존재 -> 정상 확정
    assert cl.compute_outcome("2026-06-01", 20, delisted, SPY, XLK, as_of=AS_OF)["status"] == "final"


def test_lagging_ticker_data_is_pending_not_missing_within_grace():
    lagging = STOCK_A.iloc[:61]  # idx60 까지. 청산 idx61
    out = cl.compute_outcome("2026-06-01", 60, lagging, SPY, XLK, as_of=IDX[62].date())
    assert out["status"] == "pending" and out["reason"] == "ticker_data_lagging"


def test_empty_price_data_pending_then_missing():
    early = cl.compute_outcome("2026-06-01", 20, pd.DataFrame(), SPY, XLK, as_of=IDX[22].date())
    assert early["status"] == "pending" and early["reason"] == "price_data_unavailable"
    late = cl.compute_outcome("2026-06-01", 20, pd.DataFrame(), SPY, XLK, as_of=AS_OF)
    assert late["status"] == "missing" and late["reason"] == "no_price_data"
    assert late["gross_return"] is None


def test_gap_at_exit_and_entry_bars_are_missing():
    no_exit = STOCK_A.drop(IDX[21])
    out = cl.compute_outcome("2026-06-01", 20, no_exit, SPY, XLK, as_of=AS_OF)
    assert out["status"] == "missing" and out["reason"] == "no_exit_bar"
    no_entry = STOCK_A.drop(IDX[1])
    out = cl.compute_outcome("2026-06-01", 20, no_entry, SPY, XLK, as_of=AS_OF)
    assert out["status"] == "missing" and out["reason"] == "no_entry_bar"


def test_stock_listed_after_entry_and_invalid_open():
    late_listing = STOCK_A.iloc[3:]
    out = cl.compute_outcome("2026-06-01", 20, late_listing, SPY, XLK, as_of=AS_OF)
    assert out["status"] == "missing" and out["reason"] == "not_listed_at_entry"
    bad = STOCK_A.copy()
    bad.loc[IDX[21], "Open"] = float("nan")
    out = cl.compute_outcome("2026-06-01", 20, bad, SPY, XLK, as_of=AS_OF)
    assert out["status"] == "missing" and out["reason"] == "invalid_exit_open"
    zero = STOCK_A.copy()
    zero.loc[IDX[1], "Open"] = 0.0
    out = cl.compute_outcome("2026-06-01", 20, zero, SPY, XLK, as_of=AS_OF)
    assert out["status"] == "missing" and out["reason"] == "invalid_entry_open"


def test_benchmark_unavailable_is_pending_with_reason():
    out = cl.compute_outcome("2026-06-01", 20, STOCK_A, pd.DataFrame(), XLK, as_of=AS_OF)
    assert out["status"] == "pending" and out["reason"] == "benchmark_unavailable"


def test_missing_decision_cutoff_is_terminal_missing():
    out = cl.compute_outcome(None, 20, STOCK_A, SPY, XLK, as_of=AS_OF)
    assert out["status"] == "missing" and out["reason"] == "decision_cutoff_missing"


# ---------------------------------------------------------------------------
# 시간 계약 / PIT
# ---------------------------------------------------------------------------
T = [datetime(2026, 6, 1, 12, 0), datetime(2026, 6, 1, 12, 5), datetime(2026, 6, 1, 12, 20),
     datetime(2026, 6, 1, 21, 0), datetime(2026, 6, 2, 13, 30)]


def test_pit_status_requires_all_five_fields_in_order():
    ok, issues = cl.compute_pit_status(*T)
    assert ok is True and issues == []
    ok, issues = cl.compute_pit_status(None, None, None, T[3], None)
    assert ok is False
    assert "missing:source_publication" in issues and "missing:next_executable_fill" in issues
    # system_first_seen 이 decision_cutoff 뒤 -> 누수 위반
    bad = list(T)
    bad[1] = datetime(2026, 6, 1, 22, 0)
    bad[2] = datetime(2026, 6, 1, 22, 5)
    ok, issues = cl.compute_pit_status(*bad)
    assert ok is False and any(i.startswith("order_violation:") for i in issues)


def test_normalize_time_conventions():
    assert cl.normalize_time(None) is None
    assert cl.normalize_time(datetime(2026, 6, 1, 12, 0)) == datetime(2026, 6, 1, 12, 0)  # naive = UTC
    ny = pd.Timestamp("2026-06-01 17:00", tz="America/New_York")
    assert cl.normalize_time(ny) == datetime(2026, 6, 1, 21, 0)
    # 날짜만 -> 그 날 미 동부 23:59:59 (보수적: 가장 늦은 시각) = 다음날 03:59:59 UTC (EDT)
    assert cl.normalize_time("2026-06-01") == datetime(2026, 6, 2, 3, 59, 59)
    assert cl.normalize_time(date(2026, 6, 1)) == datetime(2026, 6, 2, 3, 59, 59)


# ---------------------------------------------------------------------------
# 후보 집합 해시
# ---------------------------------------------------------------------------
def test_candidate_set_id_is_deterministic_and_order_independent():
    a = cl.compute_candidate_set_id(["AAA", "BBB"], "v1", "src", "2026-06-01")
    b = cl.compute_candidate_set_id(["bbb", " AAA"], "v1", "src", "2026-06-01")
    assert a == b and len(a) > 10
    assert a != cl.compute_candidate_set_id(["AAA", "BBB", "CCC"], "v1", "src", "2026-06-01")
    assert a != cl.compute_candidate_set_id(["AAA", "BBB"], "v2", "src", "2026-06-01")
    assert a != cl.compute_candidate_set_id(["AAA", "BBB"], "v1", "src", "2026-06-02")


def test_candidate_record_validation():
    with pytest.raises(ValueError):
        cl.CandidateRecord("AAA", "maybe")
    with pytest.raises(ValueError):
        cl.CandidateRecord("", "selected")
    with pytest.raises(ValueError):
        cl.FrozenCandidateSet("s", "v", "2026-06-01",
                              [cl.CandidateRecord("AAA", "selected"), cl.CandidateRecord("aaa", "held")])


# ---------------------------------------------------------------------------
# DB 왕복 (임시 SQLite) + update_forward_outcomes
# ---------------------------------------------------------------------------
def _make_set(cutoff="2026-06-01"):
    recs = [
        cl.CandidateRecord("AAA", "selected", "top1", scores={"composite_score": 90.0, "flags": ["x"]},
                           order_proposal={"target_weight": 0.03}, sector="Technology", rank=1),
        cl.CandidateRecord("BBB", "held", "below_cutoff", scores={"composite_score": 70.0}, rank=3,
                           sector="Technology"),
        cl.CandidateRecord("CCC", "rejected", "no_breakout"),
        cl.CandidateRecord("DDD", "missing_data", "history_missing"),
    ]
    return cl.FrozenCandidateSet(source="unit_test", strategy_version="v-test", decision_cutoff=cutoff,
                                 records=recs, meta={"note": "synthetic"})


FRAMES = {
    "SPY": SPY, "XLK": XLK, "AAA": STOCK_A, "BBB": STOCK_B, "CCC": STOCK_C,
    "DDD": px(_vals(100)).iloc[:31],  # idx30 에서 데이터 종료(상장폐지 가정)
}


def test_record_candidate_set_roundtrip_and_idempotent(db_session):
    cset = _make_set()
    res = cl.record_candidate_set(cset, session=db_session)
    assert res["inserted"] is True and res["n_decisions"] == 4 and res["conflict"] is False
    res2 = cl.record_candidate_set(_make_set(), session=db_session)
    assert res2["inserted"] is False and res2["candidate_set_id"] == res["candidate_set_id"]
    assert db_session.query(CandidateBatch).count() == 1
    assert db_session.query(CandidateDecision).count() == 4  # 중복 행 없음

    aaa = db_session.query(CandidateDecision).filter_by(ticker="AAA").one()
    assert aaa.decision == "selected" and aaa.rank == 1 and aaa.strategy_version == "v-test"
    assert aaa.candidate_set_id == res["candidate_set_id"]
    assert json.loads(aaa.scores) == {"composite_score": 90.0, "flags": ["x"]}
    assert json.loads(aaa.order_proposal) == {"target_weight": 0.03}
    assert aaa.decision_cutoff == datetime(2026, 6, 2, 3, 59, 59)  # 날짜만 -> 미 동부 종료 시각(UTC)
    assert aaa.pit_certified is False  # 시간 계약 없음 -> PIT 인증 아님
    assert aaa.source_publication is None and aaa.system_first_seen is None
    assert aaa.sector_etf == "XLK"  # Technology -> XLK 자동 매핑


def test_conflicting_rerecord_does_not_overwrite(db_session):
    cl.record_candidate_set(_make_set(), session=db_session)
    changed = _make_set()
    changed.records[0] = cl.CandidateRecord("AAA", "held", "changed my mind", sector="Technology", rank=1)
    res = cl.record_candidate_set(changed, session=db_session)
    assert res["inserted"] is False and res["conflict"] is True
    assert db_session.query(CandidateDecision).filter_by(ticker="AAA").one().decision == "selected"


def test_update_forward_outcomes_fills_all_horizons_and_is_idempotent(db_session):
    cl.record_candidate_set(_make_set(), session=db_session)
    summary = cl.update_forward_outcomes(AS_OF, price_provider=provider_for(FRAMES), session=db_session)
    assert db_session.query(CandidateOutcome).count() == 4 * 3  # 결정 4 x horizon 3
    assert summary["finalized"] + summary["missing"] + summary["pending"] == 12

    aaa = db_session.query(CandidateDecision).filter_by(ticker="AAA").one()
    outs = {o.horizon_days: o for o in db_session.query(CandidateOutcome).filter_by(decision_id=aaa.id)}
    assert outs[20].role == "primary" and outs[5].role == "diagnostic" and outs[60].role == "diagnostic"
    assert outs[20].status == "final"
    assert outs[20].entry_date == date(2026, 6, 2) and outs[20].entry_open == 100.0
    assert outs[20].exit_date == IDX[21].date() and outs[20].exit_open == 120.0
    assert outs[20].gross_return == pytest.approx(0.20)
    assert outs[20].net_return_10bp == pytest.approx(paper_net(1.20, "10bp"))
    assert outs[20].net_return_5bp == pytest.approx(paper_net(1.20, "5bp"))
    assert outs[20].net_return_25bp == pytest.approx(paper_net(1.20, "25bp"))
    assert outs[20].benchmark_ticker == "SPY" and outs[20].benchmark_return == pytest.approx(0.02)
    assert outs[20].sector_etf_ticker == "XLK" and outs[20].sector_etf_return == pytest.approx(0.05)
    assert outs[60].gross_return == pytest.approx(-0.10)
    # 진입 세션 시가 시각이 next_executable_fill 로 기록된다 (6/2 09:30 EDT = 13:30 UTC)
    assert aaa.next_executable_fill == datetime(2026, 6, 2, 13, 30)

    # 상장폐지 가정 종목: 60일은 결측 사유가 남고 수익은 NULL (0 아님)
    ddd = db_session.query(CandidateDecision).filter_by(ticker="DDD").one()
    d60 = db_session.query(CandidateOutcome).filter_by(decision_id=ddd.id, horizon_days=60).one()
    assert d60.status == "missing" and d60.status_reason == "data_ended_before_exit"
    assert d60.gross_return is None and d60.net_return_10bp is None
    d20 = db_session.query(CandidateOutcome).filter_by(decision_id=ddd.id, horizon_days=20).one()
    assert d20.status == "final" and d20.gross_return == pytest.approx(0.0)

    # 재실행: 행 수·값 불변, 새로 확정되는 것 없음
    snap = sorted((o.decision_id, o.horizon_days, o.status, o.gross_return) for o in db_session.query(CandidateOutcome))
    again = cl.update_forward_outcomes(AS_OF, price_provider=provider_for(FRAMES), session=db_session)
    assert again["finalized"] == 0 and again["missing"] == 0
    assert db_session.query(CandidateOutcome).count() == 12
    snap2 = sorted((o.decision_id, o.horizon_days, o.status, o.gross_return) for o in db_session.query(CandidateOutcome))
    assert snap == snap2


def test_pending_rows_become_final_later_without_duplicates(db_session):
    cl.record_candidate_set(_make_set(), session=db_session)
    s1 = cl.update_forward_outcomes(IDX[10].date(), price_provider=provider_for(FRAMES), session=db_session)
    assert s1["pending"] > 0
    aaa = db_session.query(CandidateDecision).filter_by(ticker="AAA").one()
    o20 = db_session.query(CandidateOutcome).filter_by(decision_id=aaa.id, horizon_days=20).one()
    assert o20.status == "pending" and o20.status_reason == "horizon_not_reached"
    assert o20.gross_return is None
    o5 = db_session.query(CandidateOutcome).filter_by(decision_id=aaa.id, horizon_days=5).one()
    assert o5.status == "final"
    n_rows = db_session.query(CandidateOutcome).count()

    cl.update_forward_outcomes(AS_OF, price_provider=provider_for(FRAMES), session=db_session)
    db_session.expire_all()
    o20 = db_session.query(CandidateOutcome).filter_by(decision_id=aaa.id, horizon_days=20).one()
    assert o20.status == "final" and o20.gross_return == pytest.approx(0.20)
    assert db_session.query(CandidateOutcome).count() == n_rows  # 같은 행을 갱신


def test_provider_error_keeps_pending_and_others_continue(db_session):
    cl.record_candidate_set(_make_set(), session=db_session)
    summary = cl.update_forward_outcomes(
        AS_OF, price_provider=provider_for(FRAMES, raises=("BBB",)), session=db_session)
    bbb = db_session.query(CandidateDecision).filter_by(ticker="BBB").one()
    for o in db_session.query(CandidateOutcome).filter_by(decision_id=bbb.id):
        assert o.status == "pending" and o.status_reason.startswith("provider_error")
        assert o.gross_return is None
    aaa = db_session.query(CandidateDecision).filter_by(ticker="AAA").one()
    assert db_session.query(CandidateOutcome).filter_by(decision_id=aaa.id, status="final").count() == 3
    assert summary["errors"] and "BBB" in summary["errors"][0]


def test_missing_cutoff_decision_is_recorded_missing(db_session):
    cset = cl.FrozenCandidateSet("unit_test", "v-nocut", None, [cl.CandidateRecord("AAA", "selected")])
    cl.record_candidate_set(cset, session=db_session)
    cl.update_forward_outcomes(AS_OF, price_provider=provider_for(FRAMES), session=db_session)
    rows = db_session.query(CandidateOutcome).all()
    assert len(rows) == 3
    assert {(o.status, o.status_reason) for o in rows} == {("missing", "decision_cutoff_missing")}


def test_time_contract_certifies_pit_only_after_fill_is_known(db_session):
    rec = cl.CandidateRecord(
        "AAA", "selected", "guidance_raise",
        source_publication=T[0], system_first_seen=T[1], extraction_completed=T[2], decision_cutoff=T[3],
        info_url="https://example.invalid/pr/1", info_doc_id="doc-1", info_hash="abc123", info_revision="r1",
        event_id="evt-1", info_cost={"llm_usd": 0.01, "license": "public"},
    )
    cset = cl.FrozenCandidateSet("unit_test", "v-pit", T[3], [rec])
    cl.record_candidate_set(cset, session=db_session)
    d = db_session.query(CandidateDecision).one()
    assert d.pit_certified is False  # 체결 시각(next_executable_fill)이 아직 없음
    assert d.info_url == "https://example.invalid/pr/1" and d.info_content_hash == "abc123"
    assert d.event_id == "evt-1"
    cl.update_forward_outcomes(AS_OF, price_provider=provider_for(FRAMES), session=db_session)
    db_session.expire_all()
    d = db_session.query(CandidateDecision).one()
    assert d.next_executable_fill == datetime(2026, 6, 2, 13, 30)  # T[3]=17:00 EDT 장 마감 후 -> 다음날 시가
    assert d.pit_certified is True


# ---------------------------------------------------------------------------
# 기본 가격 공급자 (core.market_data 캐시 정책 사용)
# ---------------------------------------------------------------------------
def test_default_price_provider_uses_market_data_cache_with_explicit_end(monkeypatch):
    calls = []

    def fake_get_price_history(ticker, start=None, end=None, interval="1d", use_cache=True, **kw):
        calls.append((ticker, start, end, interval, use_cache))
        return STOCK_A

    import core.market_data as md
    monkeypatch.setattr(md, "get_price_history", fake_get_price_history)
    out = cl.default_price_provider("AAA", "2026-05-25", "2026-09-08")
    assert out is STOCK_A
    assert calls == [("AAA", "2026-05-25", "2026-09-08", "1d", True)]


# ---------------------------------------------------------------------------
# 지표: 그룹 요약
# ---------------------------------------------------------------------------
def test_summarize_values_hand_calc():
    s = cl.summarize_values([0.02, -0.01, 0.03])
    assert s["n"] == 3
    assert s["mean"] == pytest.approx(0.04 / 3)
    assert s["win_rate"] == pytest.approx(2 / 3)
    assert s["max_loss"] == pytest.approx(-0.01)
    assert s["p50"] == pytest.approx(0.02)
    assert s["profit_factor"] == pytest.approx(0.05 / 0.01)  # 이익합 0.05 / 손실합 0.01
    empty = cl.summarize_values([])
    assert empty["n"] == 0 and empty["mean"] is None and empty["win_rate"] is None
    no_loss = cl.summarize_values([0.01, 0.02])
    assert no_loss["profit_factor"] is None and no_loss["profit_factor_infinite"] is True


def _frame(rows, pit=True):
    df = pd.DataFrame(rows, columns=["candidate_set_id", "ticker", "decision", "decision_date", cl.PRIMARY_TARGET])
    df["decision_date"] = pd.to_datetime(df["decision_date"])
    df["pit_certified"] = pit
    df["status"] = np.where(df[cl.PRIMARY_TARGET].isna(), "missing", "final")
    return df


def _win_rate_only_frame():
    d = "2026-06-01"
    rows = [("cs1", "A", "selected", d, 0.01), ("cs1", "B", "selected", d, 0.01), ("cs1", "C", "selected", d, 0.01),
            ("cs1", "D", "held", d, 0.10), ("cs1", "E", "rejected", d, -0.01), ("cs1", "F", "held", d, -0.01)]
    return _frame(rows)


def test_selection_metrics_hand_calc():
    rep = cl.evaluate_selection(_win_rate_only_frame(), n_boot=300, n_random_draws=2000, seed=11)
    sel, rest, base = rep["groups"]["selected"], rep["groups"]["rest"], rep["groups"]["random_baseline_expected"]
    assert rep["coverage"] == pytest.approx(3 / 6)  # 선택률 = 채택 / (채택+보류+거절)
    assert sel["n"] == 3 and sel["mean"] == pytest.approx(0.01) and sel["win_rate"] == pytest.approx(1.0)
    assert rest["n"] == 3 and rest["mean"] == pytest.approx(0.08 / 3) and rest["win_rate"] == pytest.approx(1 / 3)
    assert rest["max_loss"] == pytest.approx(-0.01)
    # 동일 선택률(3/6) 무작위 보류의 기대: 전체 평균 0.11/6, 승률 4/6
    assert base["mean"] == pytest.approx(0.11 / 6) and base["win_rate"] == pytest.approx(4 / 6)
    # 놓친 기회 비용 = 보류·거절 후보의 평균 초과수익
    assert rep["missed_opportunity"]["mean_excess"] == pytest.approx(0.08 / 3)
    assert rep["missed_opportunity"]["n"] == 3
    assert rep["missed_opportunity"]["by_decision"]["held"] == pytest.approx(0.09 / 2)  # (0.10-0.01)/2
    assert rep["missed_opportunity"]["by_decision"]["rejected"] == pytest.approx(-0.01)
    inc = rep["incremental"]["selected_minus_random"]
    assert inc["estimate"] == pytest.approx(0.01 - 0.11 / 6)
    assert rep["incremental"]["selected_minus_rest"]["estimate"] == pytest.approx(0.01 - 0.08 / 3)
    # 몬테카를로(시드 고정)의 무작위 보류 평균은 해석적 기대값에 근접
    assert rep["random_baseline_mc"]["mean"] == pytest.approx(0.11 / 6, abs=3e-3)


def test_win_rate_up_explained_by_selectivity_raises_warning():
    rep = cl.evaluate_selection(_win_rate_only_frame(), n_boot=300, n_random_draws=200, seed=3)
    # 승률(100% vs 무작위 67%)은 올랐지만 기대값은 더 낮다(1.0% < 1.83%) -> 경고
    assert rep["groups"]["selected"]["win_rate"] > rep["groups"]["random_baseline_expected"]["win_rate"]
    assert rep["warning_flags"]["win_rate_selectivity"] is True
    assert any("승률" in w for w in rep["warnings"])
    assert rep["verdict"] == cl.VERDICT_UNPROVEN


def _big_frame(effect, pit=True, seed=123, n_blocks=12):
    rng = np.random.default_rng(seed)
    tickers = [f"T{i:02d}" for i in range(60)]
    dates = pd.date_range("2025-01-06", periods=n_blocks, freq="42D")  # 블록(28일) 하나당 날짜 하나
    rows = []
    for bi, d in enumerate(dates):
        cands = rng.choice(tickers, size=30, replace=False)
        for j, t in enumerate(cands):
            sel = j < 10
            v = (effect if sel else 0.0) + rng.normal(0.0, 0.02)
            rows.append((f"cs{bi}", t, "selected" if sel else ("held" if j < 20 else "rejected"), d, v))
    return _frame(rows, pit=pit)


def test_ci_excluding_zero_is_only_a_review_candidate_never_auto_adopt():
    rep = cl.evaluate_selection(_big_frame(0.05), n_boot=400, n_random_draws=100, seed=5)
    inc = rep["incremental"]["selected_minus_random"]
    assert inc["ci_low"] > 0
    assert rep["verdict"] == cl.VERDICT_POSITIVE_REVIEW
    assert rep["auto_decision"] is False and rep["requires_human_approval"] is True
    assert rep["warning_flags"]["win_rate_selectivity"] is False  # 실제 개선이면 경고 없음


def test_ci_excluding_zero_negative_is_reject_review_with_enough_sample():
    rep = cl.evaluate_selection(_big_frame(-0.05), n_boot=400, n_random_draws=100, seed=5)
    assert rep["incremental"]["selected_minus_random"]["ci_high"] < 0
    assert rep["verdict"] == cl.VERDICT_REJECT_REVIEW
    assert rep["requires_human_approval"] is True


def test_ci_including_zero_is_unproven():
    rep = cl.evaluate_selection(_big_frame(0.0), n_boot=400, n_random_draws=100, seed=5)
    inc = rep["incremental"]["selected_minus_random"]
    assert inc["ci_low"] <= 0 <= inc["ci_high"]
    assert rep["verdict"] == cl.VERDICT_UNPROVEN
    assert "ci_includes_zero" in rep["verdict_reasons"]


def test_small_sample_is_unproven_even_if_estimate_positive():
    rep = cl.evaluate_selection(_win_rate_only_frame(), n_boot=200, n_random_draws=50, seed=1)
    assert rep["verdict"] == cl.VERDICT_UNPROVEN
    assert any(r.startswith("insufficient_sample") for r in rep["verdict_reasons"])


def test_diagnostic_horizon_and_non_primary_target_never_bear_a_verdict():
    big = _big_frame(0.05)
    rep5 = cl.evaluate_selection(big, horizon=5, n_boot=200, n_random_draws=50, seed=5)
    assert rep5["incremental"]["selected_minus_random"]["ci_low"] > 0  # 통계는 계산하되
    assert rep5["verdict"] == cl.VERDICT_UNPROVEN  # 판정은 주 horizon 에만 허용
    assert rep5["role"] == "diagnostic" and rep5["multiple_testing"] is True
    assert "diagnostic_horizon_not_verdict_bearing" in rep5["verdict_reasons"]
    rep20 = cl.evaluate_selection(big, horizon=20, n_boot=200, n_random_draws=50, seed=5)
    assert rep20["role"] == "primary" and rep20["multiple_testing"] is False
    big2 = big.rename(columns={cl.PRIMARY_TARGET: "gross_return"})
    rep_t = cl.evaluate_selection(big2, value_col="gross_return", n_boot=200, n_random_draws=50, seed=5)
    assert rep_t["verdict"] == cl.VERDICT_UNPROVEN and "non_primary_target" in rep_t["verdict_reasons"]


def test_non_pit_certified_rows_cap_verdict_at_unproven():
    rep = cl.evaluate_selection(_big_frame(0.05, pit=False), n_boot=200, n_random_draws=50, seed=5)
    assert rep["incremental"]["selected_minus_random"]["ci_low"] > 0
    assert rep["verdict"] == cl.VERDICT_UNPROVEN and "not_pit_certified" in rep["verdict_reasons"]
    assert rep["pit_certified_fraction"] == 0.0
    # 탐색용으로 명시적으로 PIT 요구를 끌 수 있지만, 그 사실이 보고서에 남는다
    rep2 = cl.evaluate_selection(_big_frame(0.05, pit=False), n_boot=200, n_random_draws=50, seed=5,
                                 require_pit=False)
    assert rep2["verdict"] == cl.VERDICT_POSITIVE_REVIEW and rep2["require_pit"] is False


def test_decide_verdict_truth_table():
    kw = dict(horizon=20, target=cl.PRIMARY_TARGET, cost_scenario=cl.PRIMARY_COST_SCENARIO,
              n_selected=150, n_ticker_clusters=60, n_date_blocks=15, pit_fraction=1.0, missing_rate=0.0)
    assert cl.decide_verdict(-0.01, 0.02, **kw)[0] == cl.VERDICT_UNPROVEN  # 0 포함
    assert cl.decide_verdict(0.0, 0.02, **kw)[0] == cl.VERDICT_UNPROVEN  # 경계 0 도 포함으로 취급
    assert cl.decide_verdict(0.001, 0.02, **kw)[0] == cl.VERDICT_POSITIVE_REVIEW
    assert cl.decide_verdict(-0.02, -0.001, **kw)[0] == cl.VERDICT_REJECT_REVIEW
    assert cl.decide_verdict(None, None, **kw)[0] == cl.VERDICT_UNPROVEN
    small = dict(kw, n_selected=40)  # 검증 최소치(30)는 넘지만 기각 검정력 근사치(100) 미달
    assert cl.decide_verdict(0.001, 0.02, **small)[0] == cl.VERDICT_POSITIVE_REVIEW
    assert cl.decide_verdict(-0.02, -0.001, **small)[0] == cl.VERDICT_UNPROVEN  # 기각은 더 큰 표본 필요
    assert cl.decide_verdict(0.001, 0.02, **dict(kw, n_selected=10))[0] == cl.VERDICT_UNPROVEN
    assert cl.decide_verdict(0.001, 0.02, **dict(kw, n_ticker_clusters=5))[0] == cl.VERDICT_UNPROVEN
    assert cl.decide_verdict(0.001, 0.02, **dict(kw, n_date_blocks=2))[0] == cl.VERDICT_UNPROVEN
    assert cl.decide_verdict(0.001, 0.02, **dict(kw, pit_fraction=0.9))[0] == cl.VERDICT_UNPROVEN
    assert cl.decide_verdict(0.001, 0.02, **dict(kw, missing_rate=0.5))[0] == cl.VERDICT_UNPROVEN
    assert cl.decide_verdict(0.001, 0.02, **dict(kw, horizon=60))[0] == cl.VERDICT_UNPROVEN
    assert cl.decide_verdict(0.001, 0.02, **dict(kw, cost_scenario="25bp"))[0] == cl.VERDICT_UNPROVEN


def test_evaluation_is_deterministic_with_fixed_seed():
    f = _big_frame(0.02)
    a = cl.evaluate_selection(f, n_boot=300, n_random_draws=300, seed=42)
    b = cl.evaluate_selection(f, n_boot=300, n_random_draws=300, seed=42)
    assert a["incremental"] == b["incremental"] and a["random_baseline_mc"] == b["random_baseline_mc"]
    c = cl.evaluate_selection(f, n_boot=300, n_random_draws=300, seed=43)
    assert c["incremental"]["selected_minus_random"]["ci_low"] != a["incremental"]["selected_minus_random"]["ci_low"]
    # 점추정은 시드와 무관
    assert c["incremental"]["selected_minus_random"]["estimate"] == pytest.approx(
        a["incremental"]["selected_minus_random"]["estimate"])


def test_missing_outcomes_are_counted_not_averaged_as_zero():
    rows = [("cs1", "A", "selected", "2026-06-01", 0.02), ("cs1", "B", "selected", "2026-06-01", np.nan),
            ("cs1", "C", "held", "2026-06-01", 0.0), ("cs1", "D", "rejected", "2026-06-01", np.nan),
            ("cs1", "E", "missing_data", "2026-06-01", 0.5)]
    rep = cl.evaluate_selection(_frame(rows), n_boot=100, n_random_draws=50, seed=1)
    assert rep["groups"]["selected"]["n"] == 1 and rep["groups"]["selected"]["mean"] == pytest.approx(0.02)
    assert rep["n_missing_outcome"]["selected"] == 1 and rep["n_missing_outcome"]["rejected"] == 1
    assert rep["missing_outcome_rate"] == pytest.approx(2 / 5)
    assert rep["warning_flags"]["high_missing_rate"] is True
    assert rep["groups"]["missing_data"]["n"] == 1  # 데이터 결측 판정 후보도 별도로 추적
    # 결측 판정 후보는 채택/보류 비교 풀(기본)에 섞이지 않는다
    assert rep["groups"]["rest"]["n"] == 1
    assert rep["coverage"] == pytest.approx(1 / 2)  # 채택 1 / 결과 있는 적격 후보 2(A, C)


def test_evaluate_empty_frame_is_unproven():
    rep = cl.evaluate_selection(_frame([]), n_boot=50, n_random_draws=10, seed=1)
    assert rep["verdict"] == cl.VERDICT_UNPROVEN and rep["coverage"] is None
    assert "no_selected_outcomes" in rep["verdict_reasons"]


# ---------------------------------------------------------------------------
# DB -> 프레임 -> 리포트 (전체 경로)
# ---------------------------------------------------------------------------
def test_load_outcome_frame_and_report_end_to_end(db_session):
    cl.record_candidate_set(_make_set(), session=db_session)
    cl.update_forward_outcomes(AS_OF, price_provider=provider_for(FRAMES), session=db_session)
    f = cl.load_outcome_frame(db_session, horizon=20)
    assert len(f) == 4 and set(f["decision"]) == set(cl.DECISIONS)
    aaa = f[f["ticker"] == "AAA"].iloc[0]
    assert aaa["net_return"] == pytest.approx(paper_net(1.20, "10bp"))
    assert aaa[cl.PRIMARY_TARGET] == pytest.approx(paper_net(1.20, "10bp") - 0.02)  # SPY 초과
    assert aaa["net_excess_sector"] == pytest.approx(paper_net(1.20, "10bp") - 0.05)  # XLK 잔차
    assert f.attrs["cost_scenario"] == cl.PRIMARY_COST_SCENARIO
    f60 = cl.load_outcome_frame(db_session, horizon=60)
    ddd = f60[f60["ticker"] == "DDD"].iloc[0]
    assert ddd["status"] == "missing" and np.isnan(ddd[cl.PRIMARY_TARGET])

    report = cl.build_ledger_report(session=db_session, n_boot=100, n_random_draws=50, seed=1)
    assert report["primary"]["horizon_days"] == 20 and report["primary"]["role"] == "primary"
    assert {r["horizon_days"] for r in report["diagnostics"]} == {5, 60}
    assert all(r["multiple_testing"] is True for r in report["diagnostics"])
    assert report["primary"]["verdict"] == cl.VERDICT_UNPROVEN  # 표본 4개 + PIT 미인증
    assert "관측 인프라" in report["disclaimer"]


# ---------------------------------------------------------------------------
# 어댑터 (순수 함수)
# ---------------------------------------------------------------------------
def _discovery_df():
    rows = [
        # ticker, sector, composite, n_missing, missing_factors, data_errors
        ("T1", "Technology", 90.0, 0, [], []),
        ("T2", "Financial Services", 80.0, 1, ["value"], []),
        ("T3", "Technology", 70.0, 0, [], []),
        ("T4", "Energy", 60.0, 0, [], ["price_history"]),
        ("T5", "Utilities", 50.0, 3, ["momentum", "growth", "quality"], []),
        ("T6", "Energy", 10.0, 0, [], []),
    ]
    df = pd.DataFrame(rows, columns=["ticker", "sector", "composite_score", "n_missing_factors",
                                     "missing_factors", "data_errors"])
    df["name"] = df["ticker"]
    df["momentum_score"] = df["composite_score"]
    df["fallback_flags"] = [[] for _ in range(len(df))]
    df.attrs["meta"] = {"pit_verified": False, "pit_note": "현재 스냅샷", "score_method": "sector_percentile"}
    return df


def test_stock_discovery_adapter_top_n_missing_and_pit():
    base = _discovery_df()
    shuffled = base.sample(frac=1.0, random_state=0)  # 입력 순서가 뒤섞여도 점수순 rank
    shuffled.attrs = dict(base.attrs)
    cset = cl.stock_discovery_to_candidate_set(
        shuffled,
        strategy_version="stock_discovery/v2", decision_cutoff="2026-06-01", selected_n=2,
        min_composite_score=20.0, max_missing_factors=2)
    d = {r.ticker: r for r in cset.records}
    assert [d[t].decision for t in ("T1", "T2")] == ["selected", "selected"]  # 결측 1개인 T2 도 원전략은 채택
    assert d["T1"].rank == 1 and d["T2"].rank == 2 and d["T3"].rank == 3
    assert d["T3"].decision == "held" and "top_n" in d["T3"].decision_reason
    assert d["T4"].decision == "missing_data" and "price_history" in d["T4"].decision_reason
    assert d["T5"].decision == "missing_data"  # 결측 팩터 3개 >= 2
    assert d["T6"].decision == "rejected" and "min_composite" in d["T6"].decision_reason  # 결측 아님, 점수 미달
    assert d["T1"].scores["composite_score"] == 90.0
    assert d["T1"].sector_etf == "XLK" and d["T2"].sector_etf == "XLF"
    assert cset.source == "stock_discovery" and cset.strategy_version == "stock_discovery/v2"
    assert cset.meta["pit_verified"] is False
    assert all(r.source_publication is None for r in cset.records)  # 시간 계약을 지어내지 않는다
    assert cset.candidate_set_id == cl.compute_candidate_set_id(
        [r.ticker for r in cset.records], "stock_discovery/v2", "stock_discovery", "2026-06-01")


def test_stock_discovery_adapter_default_all_selected_and_empty():
    cset = cl.stock_discovery_to_candidate_set(_discovery_df().head(3), strategy_version="v", decision_cutoff="2026-06-01")
    assert {r.decision for r in cset.records} == {"selected"}
    empty = cl.stock_discovery_to_candidate_set(pd.DataFrame(), strategy_version="v", decision_cutoff="2026-06-01")
    assert empty.records == []


def test_sector_leaders_adapter_leader_growth_and_pool():
    result = {
        "theme": "기술", "proxies": ["XLK"], "candidates_count": 5,
        "leader": {"ticker": "AAPL", "name": "Apple", "market_cap": 3e12},
        "growth_stocks": [
            {"ticker": "MSFT", "growth_score": 90.0, "growth_data_missing": False, "earnings_growth": 0.2},
            {"ticker": "XYZ", "growth_score": 50.0, "growth_data_missing": True, "earnings_growth": None},
        ],
    }
    pool = [{"ticker": "AAPL"}, {"ticker": "MSFT"}, {"ticker": "XYZ"},
            {"ticker": "ABC", "growth_data_missing": False}, {"ticker": "DEF", "growth_data_missing": True}]
    cset = cl.sector_leaders_to_candidate_set(result, strategy_version="sector_leaders/v2",
                                              decision_cutoff="2026-06-01", pool=pool)
    d = {r.ticker: r for r in cset.records}
    assert len(cset.records) == 5
    assert d["AAPL"].decision == "selected" and "leader" in d["AAPL"].decision_reason
    assert d["MSFT"].decision == "selected" and d["XYZ"].decision == "selected"
    assert d["XYZ"].scores["growth_data_missing"] is True  # 결측인데 채택된 사실이 점수에 남는다
    assert d["ABC"].decision == "held"
    assert d["DEF"].decision == "missing_data"  # 미채택 + 성장 데이터 결측
    assert all(r.sector_etf == "XLK" for r in cset.records)
    assert cset.source == "sector_leaders" and cset.meta["theme"] == "기술"


def test_sector_leaders_adapter_without_pool_records_selected_only():
    result = {"theme": "기술", "leader": {"ticker": "AAPL"}, "growth_stocks": [{"ticker": "AAPL"}, {"ticker": "MSFT"}]}
    cset = cl.sector_leaders_to_candidate_set(result, strategy_version="v", decision_cutoff="2026-06-01")
    assert [r.ticker for r in cset.records] == ["AAPL", "MSFT"]  # 대장주와 중복된 티커는 한 번만
    assert cset.meta["pool_recorded"] is False  # 미채택 후보를 받지 못했음을 명시


def test_champion_satellite_adapter_selected_held_missing_rejected():
    cands = pd.DataFrame({"ticker": [f"S{i}" for i in range(1, 8)],
                          "last_close": np.linspace(100, 50, 7),
                          "momentum_3m_pct": [30, 25, 20, 15, 10, 8, 5]})
    result = {"as_of": "2026-06-01", "scanned_count": 500, "candidates": cands,
              "selected": [f"S{i}" for i in range(1, 6)], "sizing_method": "equal",
              "per_ticker_weights": {f"S{i}": 0.03 for i in range(1, 6)}}
    cset = cl.champion_satellite_to_candidate_set(
        result, strategy_version="champion-satellite/2026-09", missing_tickers=["ZZZ"], rejected_tickers=["NOBRK"])
    d = {r.ticker: r for r in cset.records}
    assert [d[f"S{i}"].decision for i in range(1, 6)] == ["selected"] * 5
    assert d["S1"].order_proposal == {"target_weight": 0.03, "sleeve": "satellite", "sizing_method": "equal"}
    assert d["S6"].decision == "held" and d["S7"].decision == "held" and d["S6"].order_proposal is None
    assert d["S6"].rank == 6 and d["S6"].scores["momentum_3m_pct"] == 8
    assert d["ZZZ"].decision == "missing_data" and d["NOBRK"].decision == "rejected"
    # 결정 시각은 result["as_of"] 날짜(종가 이후)에서 유도 -> 다음 세션 시가 진입
    assert cset.decision_cutoff == cl.normalize_time("2026-06-01")
    assert cset.source == "champion_satellite"


def test_champion_satellite_adapter_requires_cutoff_or_as_of():
    with pytest.raises(ValueError):
        cl.champion_satellite_to_candidate_set({"candidates": pd.DataFrame(), "selected": []},
                                               strategy_version="v")
    pit = {"date": "2026-06-01", "picks": ["AAA", "BBB"], "weights": {"AAA": 0.5, "BBB": 0.5}}
    cset = cl.champion_satellite_to_candidate_set(pit, strategy_version="v")  # point-in-time 픽 형식
    assert [r.decision for r in cset.records] == ["selected", "selected"]
    assert cset.meta["pool_recorded"] is False


def test_champion_satellite_adapter_point_in_time_result_and_blocked_orders():
    """champion_paper_trade 가 실제로 쓰는 compute_satellite_recommendation_point_in_time 결과 형식."""
    picks_df = pd.DataFrame({"ticker": ["AAA", "BBB"], "price_at_rebal": [10.0, 20.0],
                             "current_price": [11.0, 19.0], "return_since_rebal_pct": [10.0, -5.0]})
    ok = {"as_of": "2026-06-01", "rebal_date": "2026-01-02", "selected": ["AAA", "BBB"], "sizing_method": "equal",
          "per_ticker_weights": {"AAA": 0.075, "BBB": 0.075}, "picks": picks_df, "new_orders_allowed": True,
          "allocation_reason": "위성 2종목 equal 배분.", "pool_size": 40, "n_active_trend": 6}
    cset = cl.champion_satellite_to_candidate_set(ok, strategy_version="champion-satellite-pit/2026-09")
    assert [(r.ticker, r.decision) for r in cset.records] == [("AAA", "selected"), ("BBB", "selected")]
    assert cset.records[0].order_proposal == {"target_weight": 0.075, "sleeve": "satellite", "sizing_method": "equal"}
    assert cset.meta["pool_recorded"] is False  # picks DataFrame 은 채택 종목이지 후보 풀이 아니다
    blocked = dict(ok, new_orders_allowed=False, per_ticker_weights={}, allocation_reason="위성 신규 주문 보류")
    held = cl.champion_satellite_to_candidate_set(blocked, strategy_version="champion-satellite-pit/2026-09")
    # 원전략은 골랐지만 주문이 보류됐다 -> 채택이 아니라 보류로 기록(반사실 추적 대상)
    assert [r.decision for r in held.records] == ["held", "held"]
    assert all(r.decision_reason.startswith("new_orders_blocked") for r in held.records)
    assert all(r.order_proposal is None for r in held.records)


def test_sector_leaders_adapter_accepts_dataframe_and_string_pool():
    result = {"theme": "기술", "proxies": ["XLK"], "leader": {"ticker": "AAPL"}, "growth_stocks": []}
    pool_df = pd.DataFrame({"ticker": ["AAPL", "ABC", "DEF"], "earnings_growth": [0.1, 0.2, None]})
    cset = cl.sector_leaders_to_candidate_set(result, strategy_version="v", decision_cutoff="2026-06-01", pool=pool_df)
    assert {r.ticker: r.decision for r in cset.records} == {"AAPL": "selected", "ABC": "held", "DEF": "missing_data"}
    cset2 = cl.sector_leaders_to_candidate_set(result, strategy_version="v", decision_cutoff="2026-06-01",
                                               pool=["AAPL", "ZZZ"])
    assert {r.ticker: r.decision for r in cset2.records} == {"AAPL": "selected", "ZZZ": "held"}


def test_adapter_sets_flow_into_the_ledger(db_session):
    cset = cl.stock_discovery_to_candidate_set(
        _discovery_df(), strategy_version="stock_discovery/v2", decision_cutoff="2026-06-01", selected_n=2)
    res = cl.record_candidate_set(cset, session=db_session)
    assert res["inserted"] and res["n_decisions"] == 6
    d = db_session.query(CandidateDecision).filter_by(ticker="T1").one()
    assert d.pit_certified is False and d.decision == "selected"


# ---------------------------------------------------------------------------
# CLI (scripts/candidate_ledger_update.py) — 주입한 공급자·세션으로 스모크
# ---------------------------------------------------------------------------
def _load_cli():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "candidate_ledger_update.py"
    spec = importlib.util.spec_from_file_location("candidate_ledger_update", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_updates_and_prints_summary_without_claiming_performance(db_session, capsys):
    cli = _load_cli()
    cl.record_candidate_set(_make_set(), session=db_session)
    rc = cli.main(["--as-of", AS_OF.isoformat(), "--n-boot", "50"],
                  price_provider=provider_for(FRAMES), session=db_session)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[갱신]" in out and "확정 11" in out and "결측 확정 1" in out
    assert "20거래일 · 주 검정" in out and "진단 전용" in out
    assert "미입증" in out and "자동 채택/폐기 아님" in out
    assert "data_ended_before_exit" in out
    n = db_session.query(CandidateOutcome).count()
    assert n == 12
    rc = cli.main(["--as-of", AS_OF.isoformat(), "--no-report", "--json"],
                  price_provider=provider_for(FRAMES), session=db_session)
    import json as _json
    payload = _json.loads(capsys.readouterr().out)
    assert rc == 0 and payload["report"] is None and payload["update"]["finalized"] == 0  # 재실행: 새 확정 없음
    assert db_session.query(CandidateOutcome).count() == n
