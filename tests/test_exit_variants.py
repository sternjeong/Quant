"""core/exit_variants.py (후보 원장 청산 규칙 변형 비교) 테스트.

원칙: 예상값은 구현이 아니라 사전 등록 문서(docs/EXIT_VARIANTS_SPEC.md)와 종이 계산으로 정했다.
- 합성 가격은 대부분 상수(시가 100, 종가 100)이고 손절 판단일·체결일만 다르다.
- 비용 식은 trade_ledger 체결 모델(매수 시가*(1+s)(1+f), 매도 시가*(1-s)(1-f))에서 종이로 유도했다.
- 네트워크 없음. 성과·승률 개선을 주장하지 않는다.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from core import candidate_ledger as cl
from core import exit_variants as ev

N = 40
IDX = pd.bdate_range("2026-06-01", periods=N)  # 0=6/1(월). cutoff 6/1 -> 진입 idx1, 상한 청산 idx21
AS_OF = IDX[-1].date()  # idx39: 상한(idx21) 이후 18세션 -> 결측 유예(5) 통과
CUT = "2026-06-01"
FEE_SLIP = {"5bp": (2.0, 3.0), "10bp": (4.0, 6.0), "25bp": (10.0, 15.0)}


def paper_net(ratio, name):
    f, s = (x / 1e4 for x in FEE_SLIP[name])
    return ratio * (1 - s) * (1 - f) / ((1 + s) * (1 + f)) - 1


def ohlc(opens=None, closes=None, default=100.0, low=None):
    o = [default] * N
    c = [default] * N
    for i, x in (opens or {}).items():
        o[i] = float(x)
    for i, x in (closes or {}).items():
        c[i] = float(x)
    lo = [min(a, b) - 1 for a, b in zip(o, c)]
    for i, x in (low or {}).items():
        lo[i] = float(x)
    return pd.DataFrame({"Open": o, "High": [max(a, b) + 1 for a, b in zip(o, c)], "Low": lo, "Close": c,
                         "Volume": 1000.0}, index=IDX)


# SPY: 진입 idx1 시가 400, idx6 404(+1%), idx7 408(+2%), idx21 420(+5%)
SPY = ohlc({6: 404, 7: 408, 21: 420}, default=400.0)


def run(stock, variant, as_of=AS_OF, bench=SPY):
    return ev.compute_variant_outcome(CUT, variant, stock, bench, as_of=as_of)


# ---------------------------------------------------------------------------
# 사전 고정 상수
# ---------------------------------------------------------------------------
def test_preregistered_variants_and_satellite_sync():
    from core.champion_strategy import SATELLITE_DONCHIAN_STOP_PCT

    assert [v.name for v in ev.VARIANTS] == ["baseline_20d", "fixed_stop_8", "trailing_10", "satellite_trailing_15"]
    assert ev.HORIZON_CAP_DAYS == cl.PRIMARY_HORIZON_DAYS == 20
    assert ev.FIXED_STOP_PCT == 0.08 and ev.TRAILING_STOP_PCT == 0.10
    assert ev.SATELLITE_TRAILING_STOP_PCT == SATELLITE_DONCHIAN_STOP_PCT == 0.15


# ---------------------------------------------------------------------------
# 손절 체결: 다음 날 시가, 장중 가격 미사용, 갭 하락
# ---------------------------------------------------------------------------
def test_fixed_stop_fills_next_day_open_not_intraday():
    # idx5 종가 91 <= 92(=100*0.92) -> idx6 시가 95 체결. idx5 저가 60 은 쓰면 안 된다(장중 체결 가정 금지).
    stock = ohlc(opens={6: 95}, closes={5: 91}, low={5: 60, 3: 50})
    out = run(stock, "fixed_stop_8")
    assert out["status"] == "final" and out["exit_reason"] == "stop"
    assert out["stop_signal_date"] == IDX[5].date()
    assert out["exit_date"] == IDX[6].date() and out["exit_open"] == 95.0
    assert out["gross_return"] == pytest.approx(-0.05, abs=1e-12)
    assert out["benchmark_return"] == pytest.approx(0.01, abs=1e-12)  # SPY 400 -> 404 (같은 진입·청산 세션)
    assert out["holding_sessions"] == 5
    for name in FEE_SLIP:
        assert out["net_returns"][name] == pytest.approx(paper_net(0.95, name), abs=1e-12)


def test_fixed_stop_boundary_close_equal_to_line_triggers_and_above_does_not():
    at = run(ohlc(closes={4: 92.0}), "fixed_stop_8")  # 92 <= 92 -> 발동, idx5 시가 100
    assert at["exit_reason"] == "stop" and at["exit_date"] == IDX[5].date()
    above = run(ohlc(closes={4: 92.01}), "fixed_stop_8")
    assert above["exit_reason"] == "time" and above["exit_date"] == IDX[21].date()


def test_gap_down_fills_at_that_open():
    stock = ohlc(opens={6: 70}, closes={5: 91})  # 손절선 92 보다 훨씬 낮은 갭 시가 70 그대로
    out = run(stock, "fixed_stop_8")
    assert out["exit_open"] == 70.0 and out["gross_return"] == pytest.approx(-0.30, abs=1e-12)
    assert out["net_returns"]["10bp"] == pytest.approx(paper_net(0.70, "10bp"), abs=1e-12)


def test_stop_fill_delayed_when_next_open_missing():
    stock = ohlc(opens={7: 90}, closes={5: 91}).drop(IDX[6])  # idx6 봉 없음 -> idx7 시가
    out = run(stock, "fixed_stop_8")
    assert out["exit_date"] == IDX[7].date() and out["exit_open"] == 90.0
    assert out["detail"]["stop_fill_delayed"] == 1
    assert out["benchmark_return"] == pytest.approx(0.02, abs=1e-12)  # SPY 400 -> 408


# ---------------------------------------------------------------------------
# 추적 손절: 최고 종가 갱신
# ---------------------------------------------------------------------------
TRAIL = ohlc(opens={6: 106}, closes={1: 100, 2: 110, 3: 120, 4: 113, **{i: 107 for i in range(5, N)}})


def test_trailing_stop_uses_updated_peak_close():
    # 최고 종가 120(idx3) -> 선 108. idx4 113 통과, idx5 107 <= 108 발동 -> idx6 시가 106.
    out = run(TRAIL, "trailing_10")
    assert out["exit_reason"] == "stop" and out["stop_signal_date"] == IDX[5].date()
    assert out["detail"]["peak_close"] == 120.0
    assert out["exit_open"] == 106.0 and out["gross_return"] == pytest.approx(0.06, abs=1e-12)
    # 진입가 기준 고정 손절(92)과 15% 추적(102)은 발동하지 않고 상한 청산(idx21 시가 100)
    for name in ("fixed_stop_8", "satellite_trailing_15"):
        o = run(TRAIL, name)
        assert o["exit_reason"] == "time" and o["exit_date"] == IDX[21].date() and o["gross_return"] == 0.0


def test_trailing_peak_starts_at_entry_day_close():
    # 진입일 종가 90(시가 100)부터 고점 시작: 진입가 대비 -10% 지만 고점(90) 대비 0% -> 발동 안 함(위성 규칙과 동일)
    out = run(ohlc(closes={1: 90, **{i: 90 for i in range(2, N)}}), "trailing_10")
    assert out["exit_reason"] == "time"


# ---------------------------------------------------------------------------
# 20일 상한
# ---------------------------------------------------------------------------
def test_cap_exit_at_20_sessions_and_last_check_day_signal():
    none = run(ohlc(opens={21: 103}), "trailing_10")
    assert none["exit_reason"] == "time" and none["exit_date"] == IDX[21].date() and none["holding_sessions"] == 20
    assert none["gross_return"] == pytest.approx(0.03, abs=1e-12)
    # 상한 전날(idx20) 종가 발동 -> idx21 시가(상한 세션)에 체결, 사유는 stop
    last = run(ohlc(opens={21: 80}, closes={20: 85}), "fixed_stop_8")
    assert last["exit_reason"] == "stop" and last["exit_date"] == IDX[21].date() and last["exit_open"] == 80.0
    # 상한 세션(idx21) 종가는 판단하지 않는다(그 뒤 체결은 20일 초과)
    after = run(ohlc(closes={21: 50}), "fixed_stop_8")
    assert after["exit_reason"] == "time" and after["exit_open"] == 100.0


# ---------------------------------------------------------------------------
# 결측·상장폐지·대기: 원장과 같은 사유
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("stock,as_of,status,reason", [
    (ohlc(closes={5: 80}).iloc[:11], AS_OF, "missing", "data_ended_before_exit"),  # 손절이 났더라도 모집단 동일
    (ohlc().iloc[5:], AS_OF, "missing", "not_listed_at_entry"),
    (ohlc().drop(IDX[1]), AS_OF, "missing", "no_entry_bar"),
    (ohlc(closes={5: 80}), IDX[15].date(), "pending", "horizon_not_reached"),
    (pd.DataFrame(), AS_OF, "missing", "no_price_data"),
])
def test_missing_and_pending_follow_ledger_reason(stock, as_of, status, reason):
    ledger = cl.compute_outcome(CUT, 20, stock, SPY, as_of=as_of)
    assert (ledger["status"], ledger["reason"]) == (status, reason)
    for v in ev.VARIANTS:
        out = run(stock, v, as_of=as_of)
        assert (out["status"], out["reason"]) == (status, reason)
        assert out["net_returns"]["10bp"] is None and out["gross_return"] is None


def test_no_close_column_marks_stop_variants_missing_not_silent_baseline():
    stock = ohlc().drop(columns=["Close"])
    assert run(stock, "baseline_20d")["status"] == "final"
    out = run(stock, "fixed_stop_8")
    assert out["status"] == "missing" and out["reason"] == "close_unavailable_for_stop"


# ---------------------------------------------------------------------------
# DB 통합: 기준선 = 원장(회귀), 평가·다중비교 라벨·미입증, 보고서
# ---------------------------------------------------------------------------
FRAMES = {
    "SPY": SPY,
    "AAA": ohlc(opens={6: 95, 21: 120}, closes={5: 91}),  # 고정 손절 발동, 기준선 +20%
    "BBB": TRAIL,  # 추적 10% 발동
    "CCC": ohlc(opens={21: 96}),  # 손절 없음, 기준선 -4%
    "DDD": ohlc().iloc[:11],  # 상장폐지 가정 -> 결측
}


def provider(ticker, start, end):
    return FRAMES.get(ticker, pd.DataFrame())


def _record(db_session):
    recs = [cl.CandidateRecord("AAA", "selected", "t"), cl.CandidateRecord("BBB", "selected", "t"),
            cl.CandidateRecord("CCC", "held", "t"), cl.CandidateRecord("DDD", "rejected", "t")]
    cl.record_candidate_set(cl.FrozenCandidateSet("unit_test", "v-test", CUT, recs), session=db_session)
    cl.update_forward_outcomes(AS_OF, price_provider=provider, session=db_session, horizons=(20,))


def test_baseline_equals_ledger_exactly(db_session):
    _record(db_session)
    comp = ev.compute_variant_frames(db_session, as_of=AS_OF, price_provider=provider)
    ledger = cl.load_outcome_frame(db_session, 20).set_index("decision_id")
    base = comp["frames"]["baseline_20d"].set_index("decision_id")
    for col in ("status", "status_reason", "net_return", "benchmark_return", "net_excess_spy", "gross_return"):
        pd.testing.assert_series_equal(base[col], ledger[col], check_names=False, check_dtype=False)
    assert comp["ledger_consistency"] == {"compared": 3, "mismatches": 0, "mismatch_ids": []}
    # 종이 계산: AAA 기준선 120/100, SPY 420/400
    aaa = base[base["ticker"] == "AAA"].iloc[0]
    assert aaa["net_excess_spy"] == pytest.approx(paper_net(1.2, "10bp") - 0.05, abs=1e-12)
    # 변형: AAA 고정 손절 -> 95/100, SPY 404/400
    fx = comp["frames"]["fixed_stop_8"].set_index("ticker")
    assert fx.at["AAA", "net_excess_spy"] == pytest.approx(paper_net(0.95, "10bp") - 0.01, abs=1e-12)
    assert fx.at["DDD", "status_reason"] == "data_ended_before_exit"
    assert comp["stats"]["fixed_stop_8"]["n_stop_exits"] == 1  # AAA 만(BBB 종가 107 > 92)
    assert comp["stats"]["trailing_10"]["n_stop_exits"] == 1  # BBB 만(AAA 고점 100 -> 선 90, 종가 91 은 선 위)


def test_evaluation_reuses_ledger_rules_with_multiple_comparison_label(db_session):
    _record(db_session)
    comp = ev.compute_variant_frames(db_session, as_of=AS_OF, price_provider=provider)
    res = ev.evaluate_variants(comp["frames"], n_boot=200, n_random_draws=50)
    mc = res["multiple_comparison"]
    assert mc["n_exploratory_variants"] == 3 and mc["exploratory_alpha"] == pytest.approx(0.05 / 3)
    base = res["variants"]["baseline_20d"]
    assert base["exploratory"] is False and base["alpha"] == 0.05
    # 기준선 평가 = 원장 evaluate_selection 과 동일
    direct = cl.evaluate_selection(cl.load_outcome_frame(db_session, 20), n_boot=200, n_random_draws=50)
    assert base["evaluation"]["groups"]["selected"] == direct["groups"]["selected"]
    assert base["verdict"] == direct["verdict"]
    for name in ("fixed_stop_8", "trailing_10", "satellite_trailing_15"):
        v = res["variants"][name]
        assert v["exploratory"] is True and "탐색 결과" in v["label"] and "Bonferroni" in v["label"]
        assert v["alpha"] == pytest.approx(0.05 / 3)
        # 표본 부족·PIT 미인증 -> 원장 규칙대로 미입증
        assert v["verdict"] == cl.VERDICT_UNPROVEN
        assert any(r.startswith("insufficient_sample") for r in v["verdict_reasons"])
        assert "not_pit_certified" in v["verdict_reasons"]
        assert v["paired_vs_baseline"]["verdict"] == cl.VERDICT_UNPROVEN
        assert "non_primary_target" in v["paired_vs_baseline"]["verdict_reasons"]
    # 기준선 대비 차이(종이 계산): 채택 = AAA, BBB
    b_aaa = paper_net(1.2, "10bp") - 0.05
    b_bbb = paper_net(1.0, "10bp") - 0.05  # BBB 기준선: idx21 시가 100
    f_aaa = paper_net(0.95, "10bp") - 0.01
    fx = res["variants"]["fixed_stop_8"]
    assert fx["stats"]["mean"] == pytest.approx((f_aaa + b_bbb) / 2, abs=1e-12)
    assert fx["delta_vs_baseline"]["mean"] == pytest.approx((f_aaa - b_aaa) / 2, abs=1e-12)
    assert fx["paired_vs_baseline"]["selected_mean_diff"] == pytest.approx((f_aaa - b_aaa) / 2, abs=1e-12)
    assert fx["stats"]["max_loss"] == pytest.approx(min(f_aaa, b_bbb), abs=1e-12)
    # 놓친 기회 = 보류·거절 평균(CCC 만, DDD 결측 제외): 96/100, SPY +5%
    assert fx["stats"]["missed_opportunity_mean"] == pytest.approx(paper_net(0.96, "10bp") - 0.05, abs=1e-12)


def test_write_report_idempotent_with_disclaimer(db_session, tmp_path):
    _record(db_session)
    tmp_path = tmp_path / "reports"
    r1 = ev.write_exit_variants_report(tmp_path, session=db_session, as_of=AS_OF, price_provider=provider,
                                       n_boot=100, n_random_draws=20)
    md = open(r1["md_path"], encoding="utf-8").read()
    assert r1["md_path"].endswith(f"exit_variants_{AS_OF.isoformat()}.md")
    assert "탐색" in md and "미래 성과를 보장하지 않" in md and "다음 거래일 시가" in md and "배선" in md
    j1 = open(r1["json_path"], encoding="utf-8").read()
    r2 = ev.write_exit_variants_report(tmp_path, session=db_session, as_of=AS_OF, price_provider=provider,
                                       n_boot=100, n_random_draws=20)
    assert open(r2["json_path"], encoding="utf-8").read() == j1  # 같은 입력 -> 같은 결과(시드 고정)
    assert len(list(tmp_path.iterdir())) == 2


def test_provider_error_leaves_pending(db_session):
    _record(db_session)

    def bad(ticker, start, end):
        if ticker == "AAA":
            raise RuntimeError("boom")
        return provider(ticker, start, end)

    comp = ev.compute_variant_frames(db_session, as_of=AS_OF, price_provider=bad)
    row = comp["frames"]["trailing_10"].set_index("ticker").loc["AAA"]
    assert row["status"] == "pending" and row["status_reason"].startswith("provider_error")
    assert np.isnan(row["net_excess_spy"])
