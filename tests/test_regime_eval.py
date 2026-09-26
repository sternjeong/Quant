"""core.regime_eval: 결정 시점 국면 라벨(미래 정보 차단), 국면별 원장 판정, 실측 비용 진단 칸.

네트워크를 쓰지 않는다. 예상값은 요구사항과 손계산으로 정했다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import candidate_ledger as cl
from core import cost_calibration as cc
from core import regime_eval as re_
from core import strategy_variants as sv
from core.models import CandidateOutcome, MarketRegimeSnapshot


def snap(ts: str, regime: str = "강세장", partial: bool = False, sid: int = 1) -> dict:
    return {"id": sid, "computed_at": datetime.fromisoformat(ts), "regime": regime, "partial": partial,
            "coverage": 1.0, "missing_signals": [], "regime_reason": None}


# 결정 시각: 2026-06-10(수) 날짜만 -> 미 동부 23:59:59 = 2026-06-11 03:59:59 UTC
CUTOFF = "2026-06-10"


# ---------------------------------------------------------------------------
# 라벨: 미래 정보 차단 · 오래된 스냅샷 · partial
# ---------------------------------------------------------------------------
def test_only_future_snapshot_gives_unknown():
    future = snap("2026-06-11T15:00:00", "강세장")  # 결정 다음 날 계산된 스냅샷
    lab = re_.label_decision_regime(CUTOFF, [future], benchmark=None)
    assert lab["regime"] == "unknown"
    assert "no_snapshot_before_cutoff" in lab["regime_reason"]


def test_prior_snapshot_is_used_and_later_snapshot_ignored():
    prior = snap("2026-06-09T15:00:00", "약세장", sid=1)
    later = snap("2026-06-12T15:00:00", "강세장", sid=2)
    lab = re_.label_decision_regime(CUTOFF, [later, prior])
    assert lab["regime"] == "약세장" and lab["regime_snapshot_id"] == 1
    assert lab["regime_source"] == re_.SOURCE_SNAPSHOT and lab["regime_age_trading_days"] == 1


def test_stale_snapshot_gives_unknown_and_boundary_is_five_trading_days():
    # 2026-06-03(수) -> 06-10(수): 평일 5일(목,금,월,화,수) -> 허용
    ok = re_.label_decision_regime(CUTOFF, [snap("2026-06-03T15:00:00")])
    assert ok["regime"] == "강세장" and ok["regime_age_trading_days"] == 5
    # 2026-06-02(화) -> 6일 -> unknown
    old = re_.label_decision_regime(CUTOFF, [snap("2026-06-02T15:00:00")])
    assert old["regime"] == "unknown" and old["regime_reason"].startswith("snapshot_stale")


def test_unknown_snapshot_and_partial_flag():
    u = re_.label_decision_regime(CUTOFF, [snap("2026-06-09T15:00:00", "unknown")])
    assert u["regime"] == "unknown" and u["regime_reason"].startswith("snapshot_regime_unknown")
    p = re_.label_decision_regime(CUTOFF, [snap("2026-06-09T15:00:00", "중립/혼조", partial=True)])
    assert p["regime"] == "중립/혼조" and p["regime_partial"] is True


def _trend_bench(n=320, end="2026-06-10", crash_after=None):
    idx = pd.bdate_range(end=end, periods=n)
    close = pd.Series(100 * np.exp(np.arange(n) * 0.004), index=idx)
    df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close})
    if crash_after:
        extra = pd.bdate_range(pd.Timestamp(end) + timedelta(days=1), periods=crash_after)
        c = pd.Series(close.iloc[-1] * np.linspace(0.9, 0.5, crash_after), index=extra)
        df = pd.concat([df, pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c})])
    return df


def test_fallback_recomputes_without_future_bars():
    bench_future = _trend_bench(crash_after=40)  # 결정 이후 폭락 봉 포함
    cut = pd.DataFrame({"decision_id": [1], "decision_cutoff": [CUTOFF]})
    lab = re_.label_decisions(cut, snapshots=[], price_provider=lambda t, s, e: bench_future)
    row = lab.iloc[0]
    assert row["regime"] == "강세장"  # 꾸준한 상승 추세(200일선 위·강한 ADX)
    assert row["regime_source"] == re_.SOURCE_FALLBACK and row["regime_asof"] == "2026-06-10"


def test_fallback_excludes_same_day_bar_before_close():
    # 2026-06-10 10:00 미 동부 = 14:00 UTC -> 당일 종가 미확정, 전일(06-09) 봉까지만
    cut = pd.DataFrame({"decision_id": [1], "decision_cutoff": [datetime(2026, 6, 10, 14, 0)]})
    lab = re_.label_decisions(cut, snapshots=[], price_provider=lambda t, s, e: _trend_bench())
    assert lab.iloc[0]["regime_asof"] == "2026-06-09"


def test_fallback_insufficient_history_is_unknown():
    cut = pd.DataFrame({"decision_id": [1], "decision_cutoff": [CUTOFF]})
    lab = re_.label_decisions(cut, snapshots=[], price_provider=lambda t, s, e: _trend_bench(n=150))
    assert lab.iloc[0]["regime"] == "unknown" and "insufficient_history" in lab.iloc[0]["regime_reason"]


# ---------------------------------------------------------------------------
# 국면별 판정
# ---------------------------------------------------------------------------
def _synthetic(n_per=40):
    """강세장에선 채택이 +5% 전후/보류 0, 약세장에선 채택 -5% 전후/보류 0 (배치당 채택1·보류1)."""
    rows, labels, did = [], [], 0
    for regime, start, sign in (("강세장", "2018-01-01", 1.0), ("약세장", "2022-01-01", -1.0)):
        for i in range(n_per):
            d = pd.Timestamp(start) + pd.Timedelta(days=30 * i)
            bid = f"{regime}-{i}"
            for dec, val in (("selected", sign * (0.05 + 0.001 * (i % 5))), ("held", 0.0)):
                did += 1
                rows.append({"decision_id": did, "candidate_set_id": bid, "ticker": f"{bid}-{dec}",
                             "decision": dec, "decision_date": d, "pit_certified": True, "net_excess_spy": val})
                labels.append({"decision_id": did, "regime": regime, "regime_source": re_.SOURCE_SNAPSHOT,
                               "regime_partial": False})
    f = pd.DataFrame(rows)
    f.attrs["cost_scenario"] = cl.PRIMARY_COST_SCENARIO
    return f, pd.DataFrame(labels)


KW = dict(n_boot=300, n_random_draws=100)


def test_regime_split_verdict_differs_from_pooled_verdict():
    frame, labels = _synthetic()
    out = re_.evaluate_by_regime(frame, labels, **KW)
    # 섞으면 채택 평균 0 ≈ 무작위 기준선 0 -> 신뢰구간이 0 포함 -> 미입증
    assert out["pooled_reference"]["verdict"] == cl.VERDICT_UNPROVEN
    assert "ci_includes_zero" in out["pooled_reference"]["verdict_reasons"]
    bull = out["regimes"]["강세장"]
    # 강세장만: 채택 ~0.052 vs 기준선 ~0.026 -> 증분 ~0.026 > 0, 게이트(40/80/40) 통과
    assert bull["verdict"] == cl.VERDICT_POSITIVE_REVIEW
    assert bull["incremental"]["selected_minus_random"]["estimate"] == pytest.approx(0.052 - 0.026, abs=1e-9)
    assert out["regimes"]["약세장"]["verdict"] == cl.VERDICT_UNPROVEN  # 기각 검토는 채택 >=100 필요
    # 원장 함수를 그대로 쓴다: 강세장만 잘라 직접 돌린 결과와 같아야 한다
    direct = cl.evaluate_selection(frame[labels["regime"].values == "강세장"], **KW)
    assert direct["verdict"] == bull["verdict"] and direct["incremental"] == bull["incremental"]


def test_multiple_comparison_label_and_small_sample_note():
    frame, labels = _synthetic(n_per=10)
    out = re_.evaluate_by_regime(frame, labels, **KW)
    assert out["n_comparisons"] == 2
    for res in out["regimes"].values():
        assert res["multiple_comparisons"]["n_comparisons"] == 2
        assert res["multiple_comparisons"]["correction"] == "none"
        assert res["verdict"] == cl.VERDICT_UNPROVEN and res["sample_gate_note"] == re_.SAMPLE_NOTE


def test_unknown_is_separate_and_never_mixed():
    frame, labels = _synthetic()
    extra = pd.DataFrame([{"decision_id": 9000 + i, "candidate_set_id": f"u{i}", "ticker": f"U{i}",
                           "decision": "selected", "decision_date": pd.Timestamp("2020-01-01"),
                           "pit_certified": True, "net_excess_spy": 9.9} for i in range(5)])
    big = pd.concat([frame, extra], ignore_index=True)
    big.attrs = dict(frame.attrs)
    lab = pd.concat([labels, pd.DataFrame([{"decision_id": 9000 + i, "regime": "unknown",
                                           "regime_source": re_.SOURCE_NONE, "regime_partial": None,
                                           "regime_reason": "snapshot_stale(age=9>5)"} for i in range(5)])],
                    ignore_index=True)
    out = re_.evaluate_by_regime(big, lab, **KW)
    assert set(out["regimes"]) == {"강세장", "약세장"}
    assert out["unknown"]["groups"]["selected"]["n"] == 5
    assert out["unknown"]["unknown_reasons"] == {"snapshot_stale": 5}
    assert out["regimes"]["강세장"]["groups"]["selected"]["n"] == 40  # 9.9 값이 섞이지 않음
    assert out["label_counts"]["unknown"] == 5


# ---------------------------------------------------------------------------
# 실측 비용
# ---------------------------------------------------------------------------
def test_measured_round_trip_matches_ledger_convention():
    # 대칭(수수료 4, 슬리피지 6)이면 원장 10bp 시나리오와 같아야 한다
    sc = {"fee_bps": 4.0, "buy_slippage_bps": 6.0, "sell_slippage_bps": 6.0}
    assert re_.measured_round_trip(0.10, sc) == pytest.approx(cl.round_trip_return(100.0, 110.0, "10bp"), abs=1e-15)
    # 손계산: 매수 슬리피지 10bp, 매도 20bp, 수수료 0, 총수익 0 -> 0.998/1.001 - 1
    asym = {"fee_bps": 0.0, "buy_slippage_bps": 10.0, "sell_slippage_bps": 20.0}
    assert re_.measured_round_trip(0.0, asym) == pytest.approx(0.998 / 1.001 - 1, abs=1e-15)


def _ok_cal(**kw):
    base = {"status": "ok", "n": 42, "generated_at": "2026-09-20T00:00:00+00:00", "stale": False,
            "scenario": {"fee_bps": 0.0, "slippage_bps": 7.0, "buy_slippage_bps": 5.0, "sell_slippage_bps": 9.0,
                         "side_split": True, "fee_note": "fee 미측정"}}
    base.update(kw)
    return base


def test_measured_status_ok_insufficient_and_missing():
    ok = re_.measured_cost_status(_ok_cal())
    assert ok["used"] and ok["stale"] is False and ok["scenario"]["buy_slippage_bps"] == 5.0
    short = re_.measured_cost_status({"status": "insufficient_sample", "reason": "insufficient_sample", "n": 12,
                                      "scenario": None})
    assert short["used"] is False and short["reason"] == "insufficient_sample" and short["n"] == 12
    assert re_.measured_cost_status(None) == {"used": False, "reason": "no_calibration_file", "stale": None}


def test_measured_stale_is_flagged_via_real_loader(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(_ok_cal(generated_at="2026-08-01T00:00:00+00:00", stale=None)), encoding="utf-8")
    cal = cc.load_cost_calibration(p, now=datetime(2026, 9, 25, tzinfo=timezone.utc))
    st = re_.measured_cost_status(cal)
    assert st["used"] and st["stale"] is True


def test_cost_scenarios_side_by_side_and_measured_is_never_verdict_bearing():
    frame, _ = _synthetic()
    frame["gross_return"] = 0.02
    frame["benchmark_return"] = 0.01
    frame["sector_etf_return"] = np.nan
    frames = {"10bp": frame}
    out = re_.evaluate_cost_scenarios(frames, re_.measured_cost_status(_ok_cal(stale=True)), **KW)
    assert set(out) == {"10bp", "measured"}
    assert out["10bp"]["primary"] and out["measured"]["kind"] == "measured" and out["measured"]["stale"] is True
    assert out["measured"]["verdict"] == cl.VERDICT_UNPROVEN
    assert "non_primary_cost_scenario" in out["measured"]["verdict_reasons"]
    # 손계산: 모든 행 총수익 2% -> 1.02*(1-0.0009)/(1.0005) - 1 - 0.01
    exp = 1.02 * (1 - 0.0009) / 1.0005 - 1 - 0.01
    assert out["measured"]["selected_mean"] == pytest.approx(exp, abs=1e-12)
    # 표본 부족이면 measured 칸 자체가 없다
    none = re_.evaluate_cost_scenarios(frames, re_.measured_cost_status({"status": "insufficient_sample",
                                                                         "n": 3, "scenario": None}), **KW)
    assert set(none) == {"10bp"}


# ---------------------------------------------------------------------------
# DB 통합: 가정 비용 결과 불변 + 보고서 절
# ---------------------------------------------------------------------------
def _record_and_track(db_session, cutoff="2026-06-01"):
    recs = [cl.CandidateRecord(t, "selected" if t in "AB" else "held") for t in "ABCD"]
    cl.record_candidate_set(cl.FrozenCandidateSet("test_src", "test/v1", cutoff, recs), session=db_session)
    idx = pd.bdate_range("2026-06-01", periods=70)

    def frame(slope):
        o = pd.Series(100.0 * (1 + slope * np.arange(70)), index=idx)
        return pd.DataFrame({"Open": o, "Close": o, "High": o, "Low": o, "Volume": 1.0}, index=idx)

    frames = {"A": frame(0.002), "B": frame(0.001), "C": frame(0.0), "D": frame(-0.001), "SPY": frame(0.0005)}
    cl.update_forward_outcomes(idx[-1].date(), price_provider=lambda t, s, e: frames.get(t, pd.DataFrame()),
                               session=db_session)


def test_assumed_cost_results_unchanged_and_labels_from_db(db_session):
    _record_and_track(db_session)
    db_session.add(MarketRegimeSnapshot(regime="강세장", total_score=50.0, detail=json.dumps({"partial": True}),
                                        computed_at=datetime(2026, 6, 1, 15, 0)))
    db_session.add(MarketRegimeSnapshot(regime="약세장", total_score=-50.0, detail="{}",
                                        computed_at=datetime(2026, 6, 2, 15, 0)))  # 결정 이후 -> 무시
    db_session.commit()
    before = sorted((o.decision_id, o.horizon_days, o.net_return_5bp, o.net_return_10bp, o.net_return_25bp)
                    for o in db_session.query(CandidateOutcome).all())
    ref10 = cl.evaluate_selection(cl.load_outcome_frame(db_session, cost_scenario="10bp"), **KW)
    ev = re_.build_regime_cost_evaluation(db_session, strategy_version="test/v1", calibration=_ok_cal(), **KW)
    after = sorted((o.decision_id, o.horizon_days, o.net_return_5bp, o.net_return_10bp, o.net_return_25bp)
                   for o in db_session.query(CandidateOutcome).all())
    assert before == after
    assert ev["cost_scenarios"]["10bp"]["selected_mean"] == ref10["groups"]["selected"]["mean"]
    assert ev["cost_scenarios"]["10bp"]["verdict"] == ref10["verdict"]
    assert set(ev["cost_scenarios"]) == {"5bp", "10bp", "25bp", "measured"}
    br = ev["by_regime"]
    assert br["label_counts"] == {"강세장": 4} and br["regimes"]["강세장"]["n_partial_labels"] == 4
    assert br["unknown"] is None


def test_research_report_has_new_sections(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "STATE_CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(cc, "load_cost_calibration", lambda *a, **k: {"status": "insufficient_sample",
                                                                       "reason": "insufficient_sample", "n": 7,
                                                                       "scenario": None})
    monkeypatch.setattr(re_, "cache_only_price_provider", lambda t, s, e: pd.DataFrame())
    ranked = pd.DataFrame({"ticker": list("ABCDEF"), "momentum_pct": [30, 29, 28, 27, 26, 25.0],
                           "last_close": 100.0})
    ranked["passes_absolute_momentum"] = True
    rec = {"last_trading_date": "2026-06-01", "ranked": ranked, "top4": list("ABCD"), "new_orders_allowed": True,
           "cash_weight_from_filter": 0.0, "allocation_reason": "t"}
    monkeypatch.setattr(sv, "_get_core_recommendation", lambda: rec)
    sv.record_variant_shadow(session=db_session)
    rep = sv.write_research_report(out_dir=tmp_path, session=db_session, as_of="2026-06-30")
    md = Path(rep["md_path"]).read_text(encoding="utf-8")
    assert "## 국면별 판정" in md and "## 실측 비용 반영 결과" in md
    assert "## 변형별 기록·표본·판정" in md and "## 회전율" in md  # 기존 절 유지
    assert "실측 비용 미사용: insufficient_sample (n=7)" in md
    payload = json.loads(Path(rep["json_path"]).read_text(encoding="utf-8"))
    rc = payload["regime_cost"]["hold_band_v1"]
    assert "error" not in rc
    assert rc["by_regime"]["label_counts"] == {"unknown": 6}  # 스냅샷·캐시 없음 -> 전부 unknown
    assert "개선했다" not in md and "우수" not in md
