"""core/champion_recommendation.py + app/pages/11_챔피언_전략.py '지금 기준 재추천' 테스트.

네트워크 없음: 가격·유니버스·백테스트 캐시를 합성 데이터로 바꿔 끼운다. 분위·초과수익·최대낙폭은
손으로 계산한 값과 대조한다(겹치는 창을 쓰는 champion_tracking 의 계산을 그대로 재사용하는지 확인).
"""

import json
import pathlib
import socket
from datetime import date, timedelta

import pandas as pd
import pytest

import core.champion_strategy as cs
from core import champion_recommendation as cr
from core import champion_tracking as ct

PAGE = pathlib.Path(__file__).resolve().parents[1] / "app" / "pages" / "11_챔피언_전략.py"
MODULE = pathlib.Path(__file__).resolve().parents[1] / "core" / "champion_recommendation.py"


# ============================================================================================
# 합성 입력
# ============================================================================================

def _core_result(top4=("XLK", "GLD", "XLE", "TLT"), status="above"):
    tickers = list(cs.CORE_UNIVERSE)
    rows = []
    for i, t in enumerate(tickers):
        rows.append({"ticker": t, "momentum_pct": 30.0 - i, "last_close": 100.0 + i,
                     "passes_absolute_momentum": True, "in_top4": t in top4})
    ranked = pd.DataFrame(rows)
    # top4 가 표 맨 앞에 오도록(compute_core_recommendation 은 모멘텀 내림차순으로 정렬해 돌려준다)
    ranked["_o"] = ranked["ticker"].apply(lambda t: 0 if t in top4 else 1)
    ranked = ranked.sort_values(["_o", "momentum_pct"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)
    exposure = 1.0 if status == "above" else (0.5 if status == "below" else 0.0)
    weights = {t: cs.CORE_WEIGHT * exposure / len(top4) for t in top4} if status != "unknown" else {}
    return {
        "as_of": "2026-09-28", "last_trading_date": "2026-09-25", "ranked": ranked, "top4": list(top4),
        "above_200dma": True if status == "above" else (False if status == "below" else None),
        "market_filter_status": status, "new_orders_allowed": status != "unknown",
        "exposure_multiplier": exposure, "per_ticker_weight": (cs.CORE_WEIGHT * exposure / len(top4)) if top4 else 0.0,
        "per_ticker_weights": weights, "cash_weight_from_filter": cs.CORE_WEIGHT * (1 - exposure),
        "spy_price": 600.0, "spy_sma200": 550.0, "sizing_method": "equal",
        "allocation_reason": "SPY 200일선 위 — 코어 비중 x1", "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
        "data_coverage": {}, "ranked_cols": None,
    }


def _rule_result(picks=("AAA", "BBB"), rebal_date="2026-07-01"):
    picks = list(picks)
    return {
        "as_of": "2026-09-28", "rebal_date": rebal_date, "trading_days_to_next_rebal": 67,
        "pool_size": 38, "n_active_trend": 6, "new_orders_allowed": True,
        "allocation_reason": f"위성 {len(picks)}종목 equal 배분.",
        "selected": picks, "sizing_method": "equal",
        "per_ticker_weight": cs.SATELLITE_WEIGHT / len(picks) if picks else 0.0,
        "per_ticker_weights": {t: cs.SATELLITE_WEIGHT / len(picks) for t in picks} if picks else {},
        "picks": pd.DataFrame([{"ticker": t, "price_at_rebal": 100.0, "current_price": 110.0,
                                "return_since_rebal_pct": 10.0} for t in picks]),
        "unallocated_weight": 0.0,
        "candidates": pd.DataFrame([{"ticker": t, "momentum_12m": 0.4 - 0.1 * i, "rank": i + 1,
                                     "donchian_breakout": True, "selected": True}
                                    for i, t in enumerate(picks)]),
        "rejected_tickers": [], "missing_tickers": [], "data_coverage": {},
    }


def _today_pick(picks=("CCC", "DDD")):
    picks = list(picks)
    return {"date": "2026-09-28", "pool_size": 40, "n_active_trend": 5, "n_with_history": 40,
            "picks": picks, "weights": {t: 1.0 / len(picks) for t in picks} if picks else {},
            "ranked_active": [(t, 0.5 - 0.1 * i) for i, t in enumerate(picks)],
            "rejected_tickers": [], "missing_tickers": []}


def _backtest(strategy, spy, tlt=None, start_day=date(2020, 1, 1)):
    dates = [(start_day + timedelta(days=i)).isoformat() for i in range(len(strategy))]
    return {"generated_on": "2026-09-28", "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
            "start": dates[0], "end": dates[-1], "dates": dates, "strategy": list(strategy),
            "spy": list(spy), "tlt": list(tlt) if tlt else None, "core_holdings": [],
            "satellite_weight_applied": 0.15}


def _compute(tmp_path, **kw):
    calls = kw.pop("calls", [])

    def _rule(as_of_date=None, sizing_method="equal"):
        calls.append(("rule", as_of_date))
        return kw.pop("rule_value", None) or _rule_result()

    def _today(ts, sizing_method="equal", **_):
        calls.append(("today", ts))
        return _today_pick()

    defaults = dict(
        as_of=date(2026, 9, 28), cache_dir=tmp_path,
        core_fn=lambda sizing_method="equal": _core_result(),
        satellite_rule_fn=_rule, satellite_today_fn=_today,
        backtest_loader=lambda as_of: _backtest([0.01] * 300, [0.005] * 300),
        perf_loader=lambda: None,
        holdings_fn=lambda: None,
        ledger_loader=lambda: [],
        price_fn=lambda tickers, start=None, end=None, interval="1d": {},
        sector_map={},
        confidence_table=cs.load_confidence_table(),
    )
    defaults.update(kw)
    return cr.compute_recommendation(**defaults)


# ============================================================================================
# 주 추천(오늘자 재선정) vs 참고(직전 반기일에 매수했다면) — 같은 함수, 날짜 인자만 다르다
# ============================================================================================

def test_primary_recommendation_uses_today_and_reference_uses_last_rebal(tmp_path):
    calls = []
    res = _compute(tmp_path, calls=calls)

    kinds = [c[0] for c in calls]
    assert sorted(kinds) == ["rule", "today"], "오늘자(주)와 직전 반기일(참고)을 각각 한 번씩 계산한다"
    rule_arg = dict(calls)["rule"]
    today_arg = dict(calls)["today"]
    assert today_arg == pd.Timestamp("2026-09-28")  # 주 추천: 같은 선정 함수에 날짜만 오늘로
    assert rule_arg == "2026-09-28"  # 참고: '지금' 을 주면 함수가 직전 반기 리밸런싱일을 찾아 쓴다
    assert rule_arg != today_arg

    sat = res["satellite"]
    # 주 추천은 오늘자이고 참고용 딱지가 붙지 않는다
    assert sat["today"]["picks"] == ["CCC", "DDD"]
    assert sat["today"]["is_primary"] is True
    assert "is_reference_only" not in sat["today"]
    # 참고 목록은 직전 반기일 기준
    assert sat["if_bought_at_last_rebal"]["picks"] == ["AAA", "BBB"]
    assert sat["if_bought_at_last_rebal"]["rebal_date"] == "2026-07-01"
    assert sat["same_picks"] is False
    note = sat["diff_note"]
    assert "오늘 다시 뽑으면 CCC·DDD" in note and "AAA·BBB" in note
    assert "참고용" not in note, "오늘자 재선정은 참고용이 아니라 주 추천이다"
    # 근거 표는 주 추천(오늘자) 종목 기준이어야 한다
    assert [r["ticker"] for r in sat["evidence"]] == ["CCC", "DDD"]


def test_next_reselection_is_six_months_after_purchase_not_the_calendar_january():
    # 1·7월은 반기 주기의 위상일 뿐이므로, 오늘 매수하면 다음 재선정은 매수일 + 6개월이다.
    got = cr.next_reselection_after_purchase(date(2026, 9, 28))
    assert got["raw_date"] == "2027-03-28"
    assert got["months"] == 6
    assert not got["date"].startswith("2027-01"), "달력상 1월이 아니라 매수일 기준이어야 한다"


@pytest.mark.parametrize("bought,raw", [
    (date(2026, 8, 31), "2027-02-28"),  # 6개월 뒤 달에 31일이 없으면 말일로 클램프
    (date(2027, 8, 31), "2028-02-29"),  # 윤년
    (date(2026, 1, 15), "2026-07-15"),
])
def test_next_reselection_month_end_clamping(bought, raw):
    assert cr.next_reselection_after_purchase(bought)["raw_date"] == raw


def test_timing_note_states_both_sides_and_recommends_neither():
    note = cr.TIMING_NOTE
    assert "측정되지 않았습니다" in note  # 시작 날짜 민감도는 미측정
    assert "1월까지 기다려라" in note and "현금" in note  # 기다리는 쪽의 비용도 밝힌다
    assert "어느 쪽도 권하지 않습니다" in note


def test_diff_note_when_rule_and_today_agree():
    nxt = cr.next_satellite_rebalance(date(2026, 9, 28))
    note = cr.satellite_diff_note(["AAA"], ["AAA"], nxt)
    assert "같습니다" in note and "2026-07-01" in note  # 직전 반기일을 가리킨다
    assert "참고용" not in note


# ============================================================================================
# 다음 반기 리밸런싱일 — 1월/7월 첫 거래일, 휴장일 경계
# ============================================================================================

@pytest.mark.parametrize("year,month,expected", [
    (2026, 1, "2026-01-02"),  # 1월 1일(목) 신년 휴장 -> 2일
    (2027, 1, "2027-01-04"),  # 1월 1일(금) 휴장, 2·3일 주말 -> 4일(월)
    (2021, 1, "2021-01-04"),  # 1월 1일(금) 휴장, 2·3일 주말 -> 4일(월)
    (2026, 7, "2026-07-01"),  # 7월 1일(수) 정상 거래일
    (2021, 7, "2021-07-01"),
])
def test_first_trading_day_of_rebalance_month(year, month, expected):
    assert cr.first_trading_day_of_month(year, month).isoformat() == expected


def test_next_rebalance_boundaries():
    # 리밸런싱 당일: '오늘이 리밸런싱일'이라고 표시하고 next 는 그 다음 반기를 가리킨다
    on_day = cr.next_satellite_rebalance(date(2026, 7, 1))
    assert on_day["is_rebalance_today"] is True
    assert on_day["next_date"] == "2027-01-04"
    assert on_day["previous_date"] == "2026-07-01"

    # 1월 1일(휴장)은 리밸런싱일이 아니고, 다음 리밸런싱일은 바로 다음 거래일(1월 2일)
    holiday = cr.next_satellite_rebalance(date(2026, 1, 1))
    assert holiday["is_rebalance_today"] is False
    assert holiday["next_date"] == "2026-01-02"
    assert holiday["calendar_days_left"] == 1 and holiday["trading_days_left"] == 1

    mid = cr.next_satellite_rebalance(date(2026, 9, 28))
    assert mid["next_date"] == "2027-01-04"
    assert mid["previous_date"] == "2026-07-01"
    assert mid["calendar_days_left"] == 98
    # 2026-09-29 ~ 2027-01-04 사이 거래일 수(휴장일 제외)를 직접 세어 대조
    expected_trading = sum(
        1 for i in range(98)
        if cr._is_trading(date(2026, 9, 28) + timedelta(days=i + 1))
    )
    assert mid["trading_days_left"] == expected_trading == 67


# ============================================================================================
# 분포 — 손계산 대조 (champion_tracking 의 겹치는 창 계산 재사용)
# ============================================================================================

STRAT = [0.10, -0.10, 0.0, 0.20]
SPY = [0.0, 0.0, 0.10, 0.0]


def test_horizon_distribution_matches_hand_calculation():
    bt = _backtest(STRAT, SPY)
    live_start = date(2099, 1, 1)  # 라이브 시작 전 = 전 구간
    d = cr.horizon_distribution(bt, live_start, 2, min_windows=3)

    # 겹치는 2일 창의 복리 수익: 1.1*0.9-1, 0.9*1.0-1, 1.0*1.2-1
    assert d["n_windows"] == 3 and d["enough_windows"] is True
    assert d["strategy"]["p50"] == pytest.approx(-0.01)
    assert d["strategy"]["worst"] == pytest.approx(-0.10)
    assert d["strategy"]["p5"] == pytest.approx(-0.091)   # 선형보간: -0.1 + 0.09*0.1
    assert d["strategy"]["p95"] == pytest.approx(0.179)   # -0.01 + 0.21*0.9
    # SPY 창: 0.0, 0.10, 0.10 -> 초과수익 -0.01, -0.20, +0.10
    assert d["spy"]["p50"] == pytest.approx(0.10)
    assert d["excess_spy_values"] == pytest.approx([-0.01, -0.20, 0.10])
    assert d["excess_spy"]["p50"] == pytest.approx(-0.01)
    assert d["beat_spy_share"] == pytest.approx(1 / 3)
    # 창 안 최대낙폭: -0.1, -0.1, 0.0
    assert d["max_drawdown"]["worst"] == pytest.approx(-0.10)
    assert d["max_drawdown"]["p50"] == pytest.approx(-0.10)
    assert d["worst_window"]["return"] == pytest.approx(-0.10)
    assert d["worst_window"]["start"] == "2020-01-02" and d["worst_window"]["end"] == "2020-01-03"
    # 같은 창 길이라면 기존 추적 판정(expected_range)과 완전히 같은 창이 나와야 한다
    er = ct.expected_range(bt, live_start, 2)
    assert er["windows"] == pytest.approx([-0.01, -0.10, 0.20])
    assert er["excess_spy"] == pytest.approx(d["excess_spy_values"])


def test_distribution_respects_live_start_cutoff():
    bt = _backtest(STRAT, SPY)  # 2020-01-01 ~ 2020-01-04
    d = cr.horizon_distribution(bt, date(2020, 1, 3), 2, min_windows=1)
    assert d["n_windows"] == 1  # 1·2일차만 라이브 이전
    assert d["strategy"]["p50"] == pytest.approx(-0.01)
    assert d["backtest_end"] == "2020-01-02"


def test_window_max_drawdowns_hand_calc():
    assert cr.window_max_drawdowns([0.1, -0.1, 0.0, 0.2], 2) == pytest.approx([-0.1, -0.1, 0.0])
    assert cr.window_max_drawdowns([0.1], 2) == []
    # 창 전체가 하락이면 그 창의 낙폭은 누적 하락폭
    assert cr.window_max_drawdowns([-0.1, -0.1], 2) == pytest.approx([0.9 * 0.9 - 1])


def test_dist_stats_counts_share_positive():
    s = cr.dist_stats([-0.2, -0.1, 0.1])
    assert s["n"] == 3 and s["share_positive"] == pytest.approx(1 / 3)
    assert cr.dist_stats([])["n"] == 0 and cr.dist_stats([])["p50"] is None


def test_not_enough_windows_is_flagged(tmp_path):
    res = _compute(tmp_path, backtest_loader=lambda as_of: _backtest([0.01] * 70, [0.0] * 70))
    h3 = res["distributions"]["by_horizon"]["63"]
    h6 = res["distributions"]["by_horizon"]["126"]
    assert h3["n_windows"] == 8 and h3["enough_windows"] is False
    assert h6["n_windows"] == 0 and h6["strategy"]["p50"] is None


def test_sleeve_excess_distribution_from_performance_cache():
    idx = pd.bdate_range("2024-01-01", periods=5)
    perf = {"params": {"start": "2024-01-01"}, "computed_at": "2026-09-28T00:00:00+00:00", "curves": {
        "satellite": {"dates": [d.date().isoformat() for d in idx], "values": [1.0, 1.1, 1.21, 1.21, 1.21]},
        "spy": {"dates": [d.date().isoformat() for d in idx], "values": [1.0, 1.0, 1.0, 1.0, 1.0]},
        "strategy": {"dates": [d.date().isoformat() for d in idx], "values": [1.0, 1.05, 1.1, 1.1, 1.1]},
    }}
    out = cr.sleeve_excess_distributions(perf, horizons=(2,))
    row = out["by_horizon"]["2"]
    # 새틀라이트 일별 수익 0.1, 0.1, 0, 0 -> 2일 창 0.21, 0.1, 0 / SPY 0 -> 초과수익 그대로
    assert row["values"] == pytest.approx([0.21, 0.10, 0.0])
    assert row["beat_spy_share"] == pytest.approx(2 / 3)
    assert cr.sleeve_excess_distributions(None) is None
    assert cr.sleeve_excess_distributions({"curves": {}}) is None


def test_equity_curves_fall_back_to_tracking_cache():
    bt = _backtest([0.1, -0.1], [0.0, 0.0])
    curves = cr.equity_curves(bt, None)
    assert curves["source"].startswith("champion_tracking")
    assert curves["strategy"] == pytest.approx([1.1, 0.99])
    assert curves["spy"] == pytest.approx([1.0, 1.0])
    assert curves["dates"] == ["2020-01-01", "2020-01-02"]


# ============================================================================================
# 근거
# ============================================================================================

def test_satellite_evidence_stop_headroom_and_breakout_date():
    idx = pd.bdate_range("2026-01-01", periods=23)
    closes = [100.0] * 20 + [105.0, 110.0, 100.0]
    df = pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 1}, index=idx)

    rows = cr.satellite_evidence(
        ["AAA"], "2026-01-01", date(2026, 2, 2),
        candidates=[{"ticker": "AAA", "momentum_12m": 0.25, "rank": 1}],
        price_fn=lambda tickers, start=None, end=None, interval="1d": {"AAA": df},
        sector_map={"AAA": "Information Technology"},
    )
    r = rows[0]
    assert r["trend_active"] is True
    assert r["breakout_date"] == idx[20].date().isoformat()  # 20일 고가 100 을 105 로 돌파한 날
    assert r["momentum_12m_pct"] == pytest.approx(25.0)
    assert r["rank_among_breakouts"] == 1
    assert r["sector"] == "Information Technology"
    # 고점 110 -> 스탑 110*(1-0.15)=93.5, 현재가 100 -> 여유 (100/93.5-1)*100
    assert r["trailing_stop"] == pytest.approx(93.5)
    assert r["stop_headroom_pct"] == pytest.approx((100 / 93.5 - 1) * 100, abs=0.01)


def test_satellite_evidence_flags_stopped_out_trend():
    idx = pd.bdate_range("2026-01-01", periods=24)
    closes = [100.0] * 20 + [105.0, 110.0, 80.0, 80.0]  # 110 대비 -27% -> 스탑 이탈
    df = pd.DataFrame({"Close": closes}, index=idx)
    rows = cr.satellite_evidence(["AAA"], "2026-01-01", date(2026, 2, 3),
                                 price_fn=lambda tickers, **kw: {"AAA": df}, sector_map={})
    assert rows[0]["trend_active"] is False
    assert rows[0]["trailing_stop"] is None  # 이미 이탈했으면 스탑 여유를 표시하지 않는다


def test_core_evidence_carries_rank_and_weights():
    rows = cr.core_evidence(_core_result())
    assert rows[0]["rank"] == 1 and rows[0]["in_top4"] is True
    top4_rows = [r for r in rows if r["in_top4"]]
    assert len(top4_rows) == 4
    assert sum(r["weight_pct"] for r in top4_rows) == pytest.approx(cs.CORE_WEIGHT * 100, abs=0.05)
    assert len(rows) == len(cs.CORE_UNIVERSE)


def test_confidence_rows_attached_to_each_section(tmp_path):
    res = _compute(tmp_path)
    refs = res["references"]
    core_components = [r["component"] for r in refs["core_confidence"]]
    sat_components = [r["component"] for r in refs["satellite_confidence"]]
    assert any("코어 자산군" in c for c in core_components)
    assert any("시장필터" in c for c in core_components)
    assert any("새틀라이트 선정" in c for c in sat_components)
    # 약한 등급을 숨기지 않는다
    grades = {r["grade"] for r in refs["core_confidence"] + refs["satellite_confidence"]}
    assert "weak" in grades
    assert refs["synthesis_report"] == "docs/reports/research_program_synthesis.html"
    assert refs["rejected_ideas"]


def test_research_status_reads_verdicts_or_marks_in_progress(tmp_path):
    jobs = tmp_path / "jobs"
    results = tmp_path / "results"
    (jobs / "done-job").mkdir(parents=True)
    (jobs / "running-job").mkdir(parents=True)
    (jobs / "done-job" / "job.json").write_text(json.dumps({"id": "done-job", "title": "끝난 연구"}), encoding="utf-8")
    (jobs / "running-job" / "job.json").write_text(json.dumps({"id": "running-job", "title": "도는 연구"}), encoding="utf-8")
    (results / "done-job").mkdir(parents=True)
    (results / "done-job" / "results.json").write_text(
        json.dumps({"verdicts": {"H1": "FAIL"}, "generated_at": "2026-09-27T00:00:00+00:00"}), encoding="utf-8")

    rows = {r["id"]: r for r in cr.research_status(jobs, results)}
    assert rows["done-job"]["verdicts"] == {"H1": "FAIL"}
    assert rows["done-job"]["status"] == "결과 있음"
    assert rows["running-job"]["status"] == "진행 중" and rows["running-job"]["verdicts"] is None


def test_research_status_reads_repository_jobs():
    rows = cr.research_status()
    assert rows, "research/jobs 에 등록된 연구가 있어야 한다"
    assert all(r["status"] in ("진행 중", "결과 있음", "결과 파일 있음(판정 없음)", "결과 파일을 읽지 못함") for r in rows)


# ============================================================================================
# 행동 결론 문구
# ============================================================================================

def _next():
    return cr.next_reselection_after_purchase(date(2026, 9, 28))


def test_action_no_change_wording():
    prev = {"as_of": "2026-09-27", "core_top4": ["XLK", "GLD", "XLE", "TLT"], "satellite_selected": ["AAA", "BBB"]}
    act = cr.action_summary(core=_core_result(), picks=["AAA", "BBB"], next_reselection=_next(), previous=prev)
    assert act["has_changes"] is False
    assert act["headline"].startswith(cr.ACTION_NO_CHANGE)
    assert "2027-03-29" in act["headline"]  # 매수일 + 6개월(달력상 1월이 아니다)
    assert act["places_orders"] is False


def test_action_core_swap_wording():
    prev = {"as_of": "2026-09-27", "core_top4": ["XLK", "GLD", "XLE", "XLV"], "satellite_selected": ["AAA", "BBB"]}
    act = cr.action_summary(core=_core_result(), picks=["AAA", "BBB"], next_reselection=_next(), previous=prev)
    assert act["has_changes"] is True
    assert "코어 1개 교체 필요(XLV→TLT)" in act["headline"]


def test_action_does_not_compare_satellite_with_quick_scan_baseline_and_keeps_stop_note():
    prev = {"as_of": "2026-09-27", "core_top4": ["XLK", "GLD", "XLE", "TLT"], "satellite_selected": ["AAA"]}
    stop_rows = [{"ticker": "AAA", "trend_active": False}]
    act = cr.action_summary(core=_core_result(), picks=["AAA", "BBB"], next_reselection=_next(),
                            previous=prev, stop_rows=stop_rows)
    # 어제 밤 저장 새틀라이트는 다른 방법론(빠른 근사 스캔)이라 교체 필요로 단정하지 않는다
    assert "교체 필요" not in act["headline"]
    assert act["has_changes"] is False
    note = " ".join(i["text"] for i in act["items"])
    assert "빠른 근사 스캔" in note
    assert "트레일링스탑" in note and "매도 신호가 아니라" in note


def test_action_without_baseline_does_not_claim_no_change():
    act = cr.action_summary(core=_core_result(), picks=["AAA"], next_reselection=_next(), previous=None)
    assert act["has_changes"] is None
    assert act["headline"].startswith(cr.ACTION_NO_BASELINE)
    assert cr.ACTION_NO_CHANGE not in act["headline"]


def test_action_holds_new_orders_when_market_filter_unknown():
    act = cr.action_summary(core=_core_result(status="unknown"), picks=[], next_reselection=_next(),
                            previous={"as_of": "2026-09-27", "core_top4": [], "satellite_selected": []})
    assert any(cr.ACTION_HOLD_ORDERS in i["text"] for i in act["items"])


# ============================================================================================
# 캐시
# ============================================================================================

def test_cache_key_depends_on_inputs_and_strategy_version(monkeypatch):
    p1 = cr.cache_params(date(2026, 9, 28), "equal", 0.15)
    assert cr.cache_key(p1) == cr.cache_key(dict(p1))
    assert cr.cache_key(p1) != cr.cache_key(cr.cache_params(date(2026, 9, 27), "equal", 0.15))
    assert cr.cache_key(p1) != cr.cache_key(cr.cache_params(date(2026, 9, 28), "inverse_vol", 0.15))
    assert cr.cache_key(p1) != cr.cache_key(cr.cache_params(date(2026, 9, 28), "equal", 0.10))
    monkeypatch.setattr(cs, "CHAMPION_STRATEGY_VERSION", "other-version")
    assert cr.cache_key(cr.cache_params(date(2026, 9, 28), "equal", 0.15)) != cr.cache_key(p1)


def test_second_call_uses_cache_and_date_change_recomputes(tmp_path):
    calls = []
    first = _compute(tmp_path, calls=calls)
    assert first["from_cache"] is False
    second = _compute(tmp_path, calls=calls)
    assert second["from_cache"] is True
    assert sorted(c[0] for c in calls) == ["rule", "today"], "캐시가 있으면 다시 계산하지 않는다"
    _compute(tmp_path, calls=calls, as_of=date(2026, 9, 29))
    assert sorted(c[0] for c in calls) == ["rule", "rule", "today", "today"]


def test_old_cache_is_ignored_when_strategy_version_changes(tmp_path, monkeypatch):
    _compute(tmp_path)
    assert cr.load_latest_cached(tmp_path) is not None
    monkeypatch.setattr(cs, "CHAMPION_STRATEGY_VERSION", "champion/other")
    assert cr.load_latest_cached(tmp_path) is None, "전략 버전이 바뀌면 옛 캐시를 쓰지 않는다"
    assert cr.load_cached(cr.cache_params(date(2026, 9, 28)), tmp_path) is None


def test_result_is_json_serialisable_and_amount_free(tmp_path):
    res = _compute(tmp_path)
    raw = json.dumps(res, ensure_ascii=False)  # 캐시에 그대로 들어가야 한다
    assert "NaN" not in raw
    curves = res["distributions"]["curves"]
    assert curves["strategy"][0] == pytest.approx(1.01)  # 금액이 아니라 배수(시작=1.0)로 저장
    assert cr.days_ago(res, date(2026, 9, 30)) == 2
    assert cr.days_ago(res, date(2026, 9, 28)) == 0


# ============================================================================================
# 화면 (AppTest)
# ============================================================================================

@pytest.fixture()
def page_env(tmp_path, monkeypatch):
    import streamlit as st
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import core.db as db

    engine = create_engine(f"sqlite:///{tmp_path / 'page.db'}", connect_args={"check_same_thread": False}, future=True)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))
    db.init_db()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(cr, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(cs, "compute_live_collar_state", lambda *a, **k: None)
    # VM 에는 매일 밤 저장되는 신호 상태(data/cache/champion_signal_state.json)가 있어 상관관계·실적 칸이 가격을 받는다 —
    # 화면 테스트가 그 환경에 흔들리지 않게 격리한다(2026-10-02 배포 관문 실패에서 발견).
    monkeypatch.setattr(cs, "get_current_holdings", lambda: None)
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked")))
    st.cache_data.clear()
    yield cache_dir
    st.cache_data.clear()


def _run_page(cache_dir, *, seed_core=True):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGE), default_timeout=120)
    if seed_core:
        # 코어 절의 자동 계산(job_manager.ensure)을 건너뛰게 만들어, 이 테스트가 새 절만 보게 한다.
        at.session_state["champion_core_asof"] = date.today().isoformat()
        at.session_state["champion_core_result"] = _core_result()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [w.value for w in at.warning] + [i.value for i in at.info] + [s.value for s in at.success]
    return " ".join(str(p) for p in parts)


def test_page_shows_button_without_starting_any_job(page_env):
    from core import job_manager

    at = _run_page(page_env)
    txt = _text(at)
    assert "✅ 지금 할 일" in txt
    assert "아직 추천을 계산하지 않았습니다" in txt
    assert at.button(key="champion_rec_button").label == "🔄 지금 기준으로 다시 추천"
    # 버튼을 누르지 않았으면 백그라운드 작업도, 슬롯 추적도 없다(다른 위젯 클릭을 먹지 않는 조건)
    assert not job_manager.list_running_jobs()
    assert "champion_rec_pending" not in at.session_state
    assert "_job_slot::champion_recommendation" not in at.session_state


def test_button_click_fills_four_blocks(page_env, monkeypatch, tmp_path):
    result = _compute(tmp_path / "rec-cache")
    monkeypatch.setattr(cr, "compute_recommendation", lambda *a, **k: result)

    at = _run_page(page_env)
    at.button(key="champion_rec_button").click().run()
    assert not at.exception, [e.value for e in at.exception]
    txt = _text(at)
    # 맨 위 카드: 목표 포트폴리오 → 주문 목록(보유 미등록이면 처음 매수) → 다음에 볼 날
    assert "2단계 — 목표 포트폴리오" in txt
    assert "3단계 — 주문 목록" in txt and "처음부터 매수" in txt
    assert "4단계 — 다음에 다시 볼 날" in txt
    # 근거·분포·확신도는 카드 아래 탭으로 내려가 있다
    assert "추천 상세" in txt
    assert "코어를 만든 결정" in txt
    assert "SPY 를 이긴 구간 비율" in txt
    # 주 추천은 오늘자 재선정이고, 직전 반기일 목록은 접힌 참고로 내려간다
    assert "오늘 기준 재선정" in txt and "지금 매수한다면" in txt
    assert "오늘 다시 뽑으면 CCC·DDD" in txt
    # 직전 반기일 목록은 접힌 expander 안의 설명으로만 보인다(라벨은 AppTest 텍스트에 안 잡힌다)
    assert "그때 실제로 매수한 경우에만 의미가 있습니다" in txt
    assert "어느 쪽도 권하지 않습니다" in txt  # 시작 날짜에 대한 정직한 문구
    assert at.session_state["champion_rec_pending"] is False
    _sat_state = at.session_state["champion_rec_result"]["satellite"]
    assert _sat_state["today"]["picks"] == ["CCC", "DDD"]
    assert _sat_state["if_bought_at_last_rebal"]["picks"] == ["AAA", "BBB"]
    # 결과를 꺼낸 뒤에는 슬롯 추적이 남아 있지 않아야 한다(다음 rerun 에서 폴링 rerun 을 걸지 않음)
    assert "_job_slot::champion_recommendation" not in at.session_state


def test_cached_result_is_shown_on_revisit_with_age(page_env, tmp_path):
    res = _compute(tmp_path / "rec-cache")
    res["params"]["as_of"] = (date.today() - timedelta(days=3)).isoformat()
    (page_env / f"{cr.CACHE_PREFIX}{cr.cache_key(res['params'])}.json").write_text(
        json.dumps(res, ensure_ascii=False), encoding="utf-8")

    at = _run_page(page_env)
    txt = _text(at)
    # 같은 달이면 'N일 전', 달이 바뀌었으면 '다시 계산하세요' — 둘 다 기준일을 밝힌다
    assert res["params"]["as_of"] in txt
    assert ("3일 전" in txt) or ("다시 계산하세요" in txt)
    assert "2단계 — 목표 포트폴리오" in txt


def test_other_button_click_still_works_without_rec_job(page_env, monkeypatch):
    """새 절이 매 rerun 마다 render()를 부르지 않는지 — 다른 버튼 클릭이 살아 있어야 한다."""
    monkeypatch.setattr(cs, "compute_satellite_recommendation_point_in_time",
                        lambda **kw: _rule_result(picks=("ZZZ",)))
    at = _run_page(page_env)
    pit_button = [b for b in at.button if "point-in-time" in b.label][0]
    pit_button.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["champion_satellite_pit_result"]["selected"] == ["ZZZ"]


# ============================================================================================
# 표현 규칙 — 성과 보장·승률 개선 주장 없음, 민감값 없음
# ============================================================================================

def test_no_performance_promises_or_secrets_in_new_code():
    sources = MODULE.read_text(encoding="utf-8") + PAGE.read_text(encoding="utf-8")
    for banned in ("보장합니다", "승률이 개선", "성과가 개선", "수익을 보장합니다", "반드시 이깁니다",
                   "무조건", "TELEGRAM_BOT_TOKEN=", "ALPACA_API_KEY", "Bearer ", "sk-", "@gmail.com"):
        assert banned not in sources, banned
    module_text = MODULE.read_text(encoding="utf-8")
    assert "미래 수익을 보장하지 않습니다" in module_text
    assert "독립 표본이 아니고 p-값처럼 읽으면 안 됩니다" in module_text
    assert "생존편향" in module_text


def test_limitations_and_unverified_notes_are_surfaced(tmp_path):
    res = _compute(tmp_path)
    assert any("생존편향" in line for line in res["limitations"])
    assert any("세금" in line for line in res["limitations"])
    assert any("중도 청산" in line for line in res["unverified_notes"])
    assert res["distributions"]["warning"] == cr.DISTRIBUTION_WARNING
    assert "예상 수익" in cr.DISTRIBUTION_WARNING  # '예상 수익이 아니라'로 못박는 문구


def test_module_does_not_import_order_path():
    text = MODULE.read_text(encoding="utf-8")
    assert "champion_paper_trade" in text  # 주문은 별도 스크립트라는 설명은 남긴다
    assert "import" not in text.split("champion_paper_trade")[0].split("\n")[-1]
    assert "alpaca" not in text.lower()


# ============================================================================================
# '지금 할 일' 카드
# ============================================================================================

def _rec_for_todo(as_of="2026-10-02", top4=("XLK", "GLD", "XLE", "TLT"), status="above", picks=("AAA", "BBB", "CCC")):
    core = _core_result(top4=top4, status=status)
    return {
        "params": cr.cache_params(as_of),
        "as_of": as_of,
        "core": {"top4": list(top4), "per_ticker_weights": core["per_ticker_weights"],
                 "market_filter_status": status},
        "satellite": {"today": {"picks": list(picks), "sleeve_weights": {t: 1 / len(picks) for t in picks}}},
    }


def test_target_allocation_sums_to_one_with_satellite_scaled():
    rows = cr.target_allocation(_rec_for_todo())
    w = {r["ticker"]: r["weight"] for r in rows}
    assert w["XLK"] == pytest.approx(cs.CORE_WEIGHT / 4)
    assert w["AAA"] == pytest.approx(cs.SATELLITE_WEIGHT / 3)
    assert cr.CASH_TICKER not in w
    assert sum(w.values()) == pytest.approx(1.0)
    assert [r["sleeve"] for r in rows][:4] == ["코어"] * 4


def test_target_allocation_puts_filter_cut_into_cash():
    rows = cr.target_allocation(_rec_for_todo(status="below"))
    cash = [r for r in rows if r["ticker"] == cr.CASH_TICKER]
    assert cash and cash[0]["weight"] == pytest.approx(cs.CORE_WEIGHT * 0.5)


def test_order_plan_fresh_buys_everything_with_capital():
    plan = cr.order_plan(cr.target_allocation(_rec_for_todo()), {}, 0.0, capital=10_000)
    assert plan["basis"] == "fresh"
    assert {r["action"] for r in plan["rows"]} == {"매수"}
    assert sum(r["delta_value"] for r in plan["rows"]) == pytest.approx(10_000, abs=1)
    assert plan["n_trades"] == 7


def test_order_plan_with_holdings_sells_first_and_keeps_within_band():
    targets = cr.target_allocation(_rec_for_todo())
    total = 10_000.0
    held = {"XLK": total * cs.CORE_WEIGHT / 4,  # 이미 목표 그대로
            "ZZZ": 1_000.0}                    # 추천 밖 보유
    cash = total - sum(held.values())
    plan = cr.order_plan(targets, held, cash)
    assert plan["basis"] == "holdings" and plan["total"] == pytest.approx(total)
    acts = {r["ticker"]: r["action"] for r in plan["rows"]}
    assert acts["XLK"] == "유지" and acts["ZZZ"] == "전량 매도" and acts["AAA"] == "매수"
    assert plan["rows"][0]["ticker"] == "ZZZ"  # 매도가 먼저
    assert plan["rows"][-1]["action"] == "유지"


def test_freshness_flags_previous_month_and_core_mismatch():
    rec = _rec_for_todo(as_of="2026-09-29")
    f = cr.freshness(rec, today=date(2026, 10, 2))
    assert f["ok"] is False and "이번 달" in f["reason"]
    rec = _rec_for_todo(as_of="2026-10-01")
    f = cr.freshness(rec, today=date(2026, 10, 2), live_core_top4=["XLK", "GLD", "XLE", "XLV"])
    assert f["ok"] is False and "다릅니다" in f["reason"]
    f = cr.freshness(rec, today=date(2026, 10, 2), live_core_top4=["TLT", "XLE", "GLD", "XLK"])
    assert f["ok"] is True and f["level"] == "aging"
    assert cr.freshness(None)["level"] == "missing"
    assert cr.freshness(_rec_for_todo(as_of="2026-10-02"), today=date(2026, 10, 2))["level"] == "fresh"


def test_next_checkpoints_dates():
    cp = cr.next_checkpoints(date(2026, 10, 2))
    assert cp["core_next"] == "2026-11-02"  # 11/1 은 일요일
    assert cp["core_rebalance_this_month"] == "2026-10-01"
    assert cp["core_rebalanced_recently"] is True
    assert cp["satellite_next"] == "2027-04-02"
    assert cr.next_checkpoints(date(2026, 12, 15))["core_next"] == "2027-01-04"


# ============================================================================================
# 종목 차트 — 누른 종목만 가격을 받아 그리고, '몇 주'는 금액 ÷ 현재가 내림
# ============================================================================================

def _ohlc(n=300, start=50.0, step=0.4, end_day=None):
    idx = pd.bdate_range(end=pd.Timestamp(end_day or date.today()), periods=n)
    close = pd.Series([start + step * i for i in range(n)], index=idx)
    return pd.DataFrame({"Open": close - 0.2, "High": close + 0.5, "Low": close - 0.5,
                         "Close": close, "Adj Close": close, "Volume": 1_000}, index=idx)


def test_estimate_shares_rounds_down():
    est = cr.estimate_shares(500, 271.95)
    assert est == {"shares": 1, "cost": 271.95, "leftover": 228.05}
    assert cr.estimate_shares(543.90, 271.95)["shares"] == 2  # 딱 나누어떨어지면 그 수 그대로
    assert cr.estimate_shares(100, 271.95)["shares"] == 0
    assert cr.estimate_shares(-750, 100.0)["shares"] == 7  # 매도 금액(음수 delta)도 절댓값으로
    assert cr.estimate_shares(500, None)["shares"] is None
    assert cr.estimate_shares(500, 0)["shares"] is None


def test_chart_tickers_excludes_cash():
    targets = cr.target_allocation(_rec_for_todo(status="below"))
    tickers = cr.chart_tickers(targets)
    assert cr.CASH_TICKER not in tickers
    assert tickers == [r["ticker"] for r in targets if r["ticker"] != cr.CASH_TICKER]  # 표 순서 그대로
    assert set(tickers) == {"XLK", "GLD", "XLE", "TLT", "AAA", "BBB", "CCC"}


def test_entry_levels_satellite_uses_evidence_stop_and_raises_peak_after_as_of():
    close = _ohlc(n=60, end_day=date(2026, 10, 1))["Close"]
    last = float(close.iloc[-1])
    ev = {"ticker": "CCC", "trailing_stop": 70.0}  # 추천 계산 시점 고점 70/0.85
    lv = cr.entry_chart_levels(close, "새틀라이트", evidence_row=ev, evidence_as_of="2026-09-01")
    assert lv["last_close"] == round(last, 2) and lv["last_date"] == "2026-10-01"
    # 20일 돌파선 = 직전 20거래일(오늘 제외) 최고 종가
    assert lv["breakout_level"] == round(float(close.iloc[-21:-1].max()), 2)
    # 9/1 이후 종가가 더 올랐으므로 고점을 올려 스탑도 올라간다
    expected_stop = max(70.0 / (1 - cs.SATELLITE_DONCHIAN_STOP_PCT), last) * (1 - cs.SATELLITE_DONCHIAN_STOP_PCT)
    assert lv["trailing_stop"] == pytest.approx(round(expected_stop, 2))
    assert lv["stop_headroom_pct"] == pytest.approx(round((last / expected_stop - 1) * 100, 2))
    assert {l["key"] for l in lv["levels"]} == {"last", "breakout", "stop"}
    assert lv["momentum_ref"] is None  # 새틀라이트 전용 종목엔 코어 기준선을 긋지 않는다


def test_entry_levels_satellite_without_evidence_recomputes_with_rule_function():
    close = _ohlc(n=60)["Close"]
    lv = cr.entry_chart_levels(close, "새틀라이트")
    # 계속 오르는 종가라 21번째 봉에서 돌파 → 진입 후 최고 종가는 마지막 종가
    assert lv["trailing_stop"] == pytest.approx(round(float(close.iloc[-1]) * (1 - cs.SATELLITE_DONCHIAN_STOP_PCT), 2))


def test_entry_levels_core_uses_12m_reference_price():
    close = _ohlc(n=300)["Close"]
    lv = cr.entry_chart_levels(close, "코어")
    ref = float(close.iloc[-1 - cs.CORE_MOMENTUM_LOOKBACK_DAYS])
    assert lv["momentum_ref"] == round(ref, 2)
    assert lv["momentum_12m_pct"] == pytest.approx(round((float(close.iloc[-1]) / ref - 1) * 100, 2))
    assert lv["breakout_level"] is None and lv["trailing_stop"] is None
    assert cr.entry_chart_levels(close.iloc[:100], "코어")["momentum_ref"] is None  # 1년이 안 되면 긋지 않음


def test_fetch_chart_history_returns_none_on_failure():
    def boom(*a, **k):
        raise OSError("offline")

    assert cr.fetch_chart_history("XLK", price_fn=boom) is None
    assert cr.fetch_chart_history("XLK", price_fn=lambda *a, **k: pd.DataFrame()) is None
    df = cr.fetch_chart_history("XLK", today=date(2026, 10, 2), price_fn=lambda t, start=None: _ohlc())
    assert df is not None and not df.empty


def _run_page_with_rec(cache_dir, rec):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGE), default_timeout=120)
    at.session_state["champion_core_asof"] = date.today().isoformat()
    at.session_state["champion_core_result"] = _core_result()
    at.session_state["champion_rec_result"] = rec
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_page_ticker_chart_loads_only_on_click(page_env, monkeypatch, tmp_path):
    import core.market_data as md

    calls = []

    def fake_history(ticker, start=None, end=None, interval="1d", **_):
        calls.append(ticker)
        return _ohlc()

    monkeypatch.setattr(md, "get_price_history", fake_history)
    rec = _compute(tmp_path / "rec-cache")
    at = _run_page_with_rec(page_env, rec)
    pills = at.pills(key="champion_todo_chart_ticker")
    assert "CCC" in pills.options and "XLK" in pills.options and "현금" not in pills.options
    assert calls == [], "종목을 누르기 전에는 가격을 받지 않는다"
    assert not at.get("plotly_chart") or all("champion_todo_chart" not in str(c.proto.id) for c in at.get("plotly_chart"))

    pills.set_value("CCC").run()
    assert not at.exception, [e.value for e in at.exception]
    assert calls == ["CCC"]
    txt = _text(at)
    last = float(_ohlc()["Close"].iloc[-1])
    shares = int((10_000 * cs.SATELLITE_WEIGHT * 0.5) / last)
    assert f"약 {shares}주" in txt
    assert f"현재가 ${last:,.2f}" in txt
    assert "지정가·목표 매수가가 없습니다" in txt and "종가" in txt
    assert "트레일링스탑 기준" in txt and "20일 돌파선" in txt
    assert at.get("plotly_chart"), "차트가 그려져야 한다"

    pills.set_value("XLK").run()
    assert not at.exception, [e.value for e in at.exception]
    assert "12개월 전 가격" in _text(at)


def test_page_ticker_chart_offline_shows_message(page_env, monkeypatch, tmp_path):
    import core.market_data as md

    def offline(*a, **k):
        raise OSError("network blocked")

    monkeypatch.setattr(md, "get_price_history", offline)
    at = _run_page_with_rec(page_env, _compute(tmp_path / "rec-cache"))
    at.pills(key="champion_todo_chart_ticker").set_value("XLK").run()
    assert not at.exception, [e.value for e in at.exception]
    assert "가격 데이터를 불러오지 못했습니다" in _text(at)


def test_page_shows_dawn_backtest_with_ranked_active_lists(page_env):
    """2026-10-06 배포 관문 실패 재현: 새벽 미리 계산(JSON)으로 읽은 새틀라이트 리밸런싱 로그의 ranked_active([종목, 점수] 목록)가
    표 변환(Arrow)을 깨뜨려 화면 전체가 예외로 멈췄다."""
    import numpy as np
    import pandas as pd

    from core import dawn_precompute as dp
    from core.backtest_engine import calculate_metrics

    idx = pd.bdate_range(date.today() - timedelta(days=400), periods=250)
    eq = pd.Series(np.linspace(1.0, 1.2, len(idx)), index=idx)
    ret = eq.pct_change().fillna(0.0)
    m = calculate_metrics(eq, [], idx[0], idx[-1])
    sleeve = {"start": str(idx[0].date()), "end": str(idx[-1].date()), "metrics": m, "ret_net": ret, "equity_net": eq}
    bt = {"start": str(idx[0].date()), "end": str(idx[-1].date()), "satellite_weight_applied": 0.15, "metrics": m,
          "equity_net": eq, "ret_net": ret, "core": dict(sleeve),
          "satellite": {**sleeve, "tickers_ever_held": ["NVDA"],
                        "rebal_log": [{"date": str(idx[10].date()), "picks": ["NVDA"], "weights": {"NVDA": 1.0},
                                       "ranked_active": [["NVDA", 0.52], ["META", 0.31]], "rejected_tickers": []}]}}
    as_of = dp.kst_today()
    dp.save_result(dp.KIND_CHAMPION_BACKTEST, dp.result_params(dp.KIND_CHAMPION_BACKTEST, as_of, satellite_weight=0.15, collar=False), bt)
    assert dp.load_latest(dp.KIND_CHAMPION_BACKTEST) is not None
    at = _run_page(page_env)  # 예외가 없어야 한다
    assert any("새벽 자동 계산" in c.value for c in at.caption)
