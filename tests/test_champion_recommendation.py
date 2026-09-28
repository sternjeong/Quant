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
# ① 규칙 보유 vs ② 오늘 리밸런싱이라면 — 서로 다른 날짜를 쓴다
# ============================================================================================

def test_rule_and_today_pick_use_different_as_of(tmp_path):
    calls = []
    res = _compute(tmp_path, calls=calls)

    kinds = [c[0] for c in calls]
    assert kinds == ["rule", "today"], "① 규칙 보유와 ② 오늘 기준을 각각 한 번씩 계산해야 한다"
    rule_arg = dict(calls)["rule"]
    today_arg = dict(calls)["today"]
    assert rule_arg == "2026-09-28"  # ①: '지금' 을 주면 함수가 직전 반기 리밸런싱일을 찾아 쓴다
    assert today_arg == pd.Timestamp("2026-09-28")  # ②: 같은 선정 함수에 날짜만 오늘로
    assert rule_arg != today_arg

    sat = res["satellite"]
    assert sat["rule"]["picks"] == ["AAA", "BBB"]
    assert sat["rule"]["rebal_date"] == "2026-07-01"
    assert sat["today_if_rebalance"]["picks"] == ["CCC", "DDD"]
    assert sat["today_if_rebalance"]["is_reference_only"] is True
    assert sat["same_picks"] is False
    note = sat["diff_note"]
    assert "규칙은 AAA·BBB 보유" in note and "오늘 새로 뽑으면 CCC·DDD" in note
    assert "참고용" in note and sat["next_rebalance"]["next_date"] in note


def test_diff_note_when_rule_and_today_agree():
    nxt = cr.next_satellite_rebalance(date(2026, 9, 28))
    note = cr.satellite_diff_note(["AAA"], ["AAA"], nxt)
    assert "같습니다" in note and "2027-01-04" in note


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
    return cr.next_satellite_rebalance(date(2026, 9, 28))


def test_action_no_change_wording():
    prev = {"as_of": "2026-09-27", "core_top4": ["XLK", "GLD", "XLE", "TLT"], "satellite_selected": ["AAA", "BBB"]}
    act = cr.action_summary(core=_core_result(), rule_picks=["AAA", "BBB"], next_rebal=_next(), previous=prev)
    assert act["has_changes"] is False
    assert act["headline"].startswith(cr.ACTION_NO_CHANGE)
    assert "2027-01-04" in act["headline"]
    assert act["places_orders"] is False


def test_action_core_swap_wording():
    prev = {"as_of": "2026-09-27", "core_top4": ["XLK", "GLD", "XLE", "XLV"], "satellite_selected": ["AAA", "BBB"]}
    act = cr.action_summary(core=_core_result(), rule_picks=["AAA", "BBB"], next_rebal=_next(), previous=prev)
    assert act["has_changes"] is True
    assert "코어 1개 교체 필요(XLV→TLT)" in act["headline"]


def test_action_satellite_change_and_stop_note():
    prev = {"as_of": "2026-09-27", "core_top4": ["XLK", "GLD", "XLE", "TLT"], "satellite_selected": ["AAA"]}
    stop_rows = [{"ticker": "AAA", "trend_active": False}]
    act = cr.action_summary(core=_core_result(), rule_picks=["AAA", "BBB"], next_rebal=_next(),
                            previous=prev, stop_rows=stop_rows)
    assert "새틀라이트 1개 교체 필요(BBB 매수)" in act["headline"]
    note = " ".join(i["text"] for i in act["items"])
    assert "트레일링스탑" in note and "매도 신호가 아니라" in note


def test_action_without_baseline_does_not_claim_no_change():
    act = cr.action_summary(core=_core_result(), rule_picks=["AAA"], next_rebal=_next(), previous=None)
    assert act["has_changes"] is None
    assert act["headline"].startswith(cr.ACTION_NO_BASELINE)
    assert cr.ACTION_NO_CHANGE not in act["headline"]


def test_action_holds_new_orders_when_market_filter_unknown():
    act = cr.action_summary(core=_core_result(status="unknown"), rule_picks=[], next_rebal=_next(),
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
    assert [c[0] for c in calls] == ["rule", "today"], "캐시가 있으면 다시 계산하지 않는다"
    _compute(tmp_path, calls=calls, as_of=date(2026, 9, 29))
    assert [c[0] for c in calls] == ["rule", "today", "rule", "today"]


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
    assert "0. 지금 기준 재추천" in txt
    assert "아직 재추천을 계산하지 않았습니다" in txt
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
    assert "① 지금 무엇을 들고 있어야 하나" in txt
    assert "② 과거 같은 길이 구간에서 나온 범위" in txt
    assert "③ 왜 이걸 믿어야 하나" in txt
    assert "④ 지금 해야 할 행동" in txt
    assert "SPY 를 이긴 구간 비율" in txt
    assert "규칙은 AAA·BBB 보유" in txt and "참고용" in txt
    assert at.session_state["champion_rec_pending"] is False
    assert at.session_state["champion_rec_result"]["satellite"]["rule"]["picks"] == ["AAA", "BBB"]
    # 결과를 꺼낸 뒤에는 슬롯 추적이 남아 있지 않아야 한다(다음 rerun 에서 폴링 rerun 을 걸지 않음)
    assert "_job_slot::champion_recommendation" not in at.session_state


def test_cached_result_is_shown_on_revisit_with_age(page_env, tmp_path):
    res = _compute(tmp_path / "rec-cache")
    res["params"]["as_of"] = (date.today() - timedelta(days=3)).isoformat()
    (page_env / f"{cr.CACHE_PREFIX}{cr.cache_key(res['params'])}.json").write_text(
        json.dumps(res, ensure_ascii=False), encoding="utf-8")

    at = _run_page(page_env)
    txt = _text(at)
    assert "3일 전 결과입니다" in txt
    assert "① 지금 무엇을 들고 있어야 하나" in txt


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
