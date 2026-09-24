"""Satellite sleeve hold flag: independent of the core flag, fail-closed, enforced at the POST point.

Expected values follow the requirement (not the implementation):
- core hold and satellite hold are separate; one being on hold must not stop or start the other;
- a sleeve whose flag is missing / not exactly True never buys (same fail-closed rule as core);
- a held sleeve keeps its holdings (no liquidation from a missing recommendation), except explicit
  reasoned sells; "no trend candidates" with healthy data is NOT a hold (satellite goes to cash).
"""
import importlib.util
import pathlib

import pandas as pd
import pytest

from core import champion_strategy
from core.paper_execution import (
    AlpacaPaperBroker, RunStore, build_order_plan, enforce_order_gate, plan_targets,
)
from tests.test_paper_execution import FakeServer
from tests.test_champion_strategy import _fake_get_price_history_calendar, _make_satellite_mocks

_spec = importlib.util.spec_from_file_location(
    "champion_paper_trade", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "champion_paper_trade.py")
cpt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cpt)

EQUITY = 10_000.0
CORE_OK = {"top4": ["XLK", "XLF"], "new_orders_allowed": True, "per_ticker_weight": 0.2,
           "per_ticker_weights": {"XLK": 0.2, "XLF": 0.2}}
CORE_HOLD = {"top4": ["XLK", "XLF"], "new_orders_allowed": False, "per_ticker_weight": 0.0,
             "per_ticker_weights": {}, "allocation_reason": "SPY missing"}
SAT_OK = {"selected": ["AAPL"], "new_orders_allowed": True, "per_ticker_weights": {"AAPL": 0.1}}
SAT_HOLD = {"selected": [], "new_orders_allowed": False, "per_ticker_weights": {}, "allocation_reason": "no satellite data"}
# satellite dict as produced before the flag existed / by the legacy scan: no flag at all
SAT_NO_FLAG = {"selected": ["AAPL"], "per_ticker_weights": {"AAPL": 0.1}}

# XLE is a core ETF no longer targeted; AAPL is an individual stock => satellite sleeve
HELD = {"XLE": {"qty": 20, "market_value": 2000.0, "current_price": 100.0},
        "AAPL": {"qty": 10, "market_value": 1000.0, "current_price": 100.0}}


def _sides(plan):
    return {(o["symbol"], o["side"]) for o in plan["orders"]}


# ---- targets -----------------------------------------------------------------------------------

def test_plan_targets_each_sleeve_gated_by_its_own_flag_fail_closed():
    assert plan_targets(CORE_OK, SAT_OK) == {"XLK": 0.2, "XLF": 0.2, "AAPL": 0.1}
    assert plan_targets(CORE_OK, SAT_HOLD) == {"XLK": 0.2, "XLF": 0.2}
    assert plan_targets(CORE_HOLD, SAT_OK) == {"AAPL": 0.1}
    assert plan_targets(CORE_OK, SAT_NO_FLAG) == {"XLK": 0.2, "XLF": 0.2}          # missing flag = hold
    assert plan_targets({**CORE_OK, "new_orders_allowed": "yes"}, SAT_OK) == {"AAPL": 0.1}   # not exactly True
    assert plan_targets({k: v for k, v in CORE_OK.items() if k != "new_orders_allowed"}, SAT_OK) == {"AAPL": 0.1}


def test_plan_targets_uses_actual_weights_not_top4_times_weight():
    rec = {"new_orders_allowed": True, "top4": ["XLK", "XLF", "XLE", "XLV"], "per_ticker_weight": 0.2,
           "per_ticker_weights": {"XLK": 0.3}}
    assert plan_targets(rec, {"new_orders_allowed": True, "selected": ["AAPL"], "per_ticker_weight": 0.05,
                              "per_ticker_weights": {}}) == {"XLK": 0.3}


# ---- plan building (script) --------------------------------------------------------------------

def test_satellite_hold_keeps_satellite_holdings_and_core_still_trades():
    plan = cpt.build_plan(CORE_OK, SAT_HOLD, HELD, EQUITY)
    assert plan["new_orders_allowed"] is True and plan["satellite_new_orders_allowed"] is False
    assert "no satellite data" in plan["satellite_hold_reason"]
    assert _sides(plan) == {("XLE", "sell"), ("XLK", "buy"), ("XLF", "buy")}       # AAPL untouched
    assert plan["sleeve_of"]["XLK"] == "core" and "AAPL" not in plan["sleeve_of"]


def test_satellite_missing_flag_is_a_hold_not_a_liquidation():
    plan = cpt.build_plan(CORE_OK, SAT_NO_FLAG, HELD, EQUITY)
    assert plan["satellite_new_orders_allowed"] is False
    assert ("AAPL", "buy") not in _sides(plan) and ("AAPL", "sell") not in _sides(plan)
    assert plan["satellite_hold_reason"]                                           # says why


def test_core_hold_does_not_block_a_healthy_satellite_and_keeps_core_holdings():
    sat = {"selected": ["AAPL"], "new_orders_allowed": True, "per_ticker_weights": {"AAPL": 0.15}}
    plan = cpt.build_plan(CORE_HOLD, sat, HELD, EQUITY)
    assert plan["new_orders_allowed"] is False and plan["satellite_new_orders_allowed"] is True
    # satellite buys 0.15*10000 - 1000 held; the held core ETF (XLE) is neither sold nor topped up
    assert _sides(plan) == {("AAPL", "buy")}


def test_both_sleeves_on_hold_produce_no_orders():
    plan = cpt.build_plan(CORE_HOLD, SAT_HOLD, HELD, EQUITY)
    assert plan["orders"] == [] and not plan["new_orders_allowed"] and not plan["satellite_new_orders_allowed"]


def test_healthy_satellite_with_no_picks_goes_to_cash():
    """No trend candidates with healthy data is a decision (sell), not a data hold."""
    empty_ok = {"selected": [], "new_orders_allowed": True, "per_ticker_weights": {}}
    plan = cpt.build_plan(CORE_OK, empty_ok, HELD, EQUITY)
    assert ("AAPL", "sell") in _sides(plan)


def test_explicit_sell_reason_still_exits_a_held_satellite_position():
    targets = plan_targets(CORE_OK, SAT_HOLD)
    plan = build_order_plan(targets, HELD, EQUITY, satellite_new_orders_allowed=False,
                            sleeve_of={"AAPL": "satellite", "XLK": "core", "XLF": "core"},
                            sell_reasons={"AAPL": "delisted"})
    assert ("AAPL", "sell") in _sides(plan)


def test_fingerprint_covers_the_satellite_flag():
    a = build_order_plan({"XLK": .2}, {}, EQUITY, satellite_new_orders_allowed=True)
    b = build_order_plan({"XLK": .2}, {}, EQUITY, satellite_new_orders_allowed=False)
    assert a["fingerprint"] != b["fingerprint"]


# ---- gate at the POST point ---------------------------------------------------------------------

class Broker(AlpacaPaperBroker):
    def __init__(self, server):
        super().__init__("k", "s")
        self._request = server.request

    def account(self):
        return {"id": "acct-1", "equity": str(EQUITY)}


def _mixed_plan(**flags):
    """One core buy (XLK) and one satellite buy (AAPL) built directly, then flags overridden."""
    plan = build_order_plan({"XLK": .2, "AAPL": .1}, {}, EQUITY, sleeve_of={"XLK": "core", "AAPL": "satellite"})
    plan.update(flags)
    return plan


def _post_symbols(server):
    return sorted(cid.split("-")[-1] for cid in server.posts)


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs.db")


def test_gate_blocks_satellite_buy_when_satellite_flag_false_but_core_buy_goes_through(store):
    server, plan = FakeServer(), _mixed_plan(satellite_new_orders_allowed=False)
    res = Broker(server).submit_plan(plan, plan["fingerprint"], run_store=store)
    assert _post_symbols(server) == ["XLK"]
    blocked = [r for r in res if r["reconcile_state"] == "blocked_hold"]
    assert [(r["symbol"], r["hold_sleeve"]) for r in blocked] == [("AAPL", "satellite")]


def test_gate_fails_closed_when_satellite_flag_missing(store):
    server, plan = FakeServer(), _mixed_plan()
    del plan["satellite_new_orders_allowed"]
    Broker(server).submit_plan(plan, plan["fingerprint"], run_store=store)
    assert _post_symbols(server) == ["XLK"]


def test_gate_flags_are_independent_core_false_satellite_true(store):
    server, plan = FakeServer(), _mixed_plan(new_orders_allowed=False)
    Broker(server).submit_plan(plan, plan["fingerprint"], run_store=store)
    assert _post_symbols(server) == ["AAPL"]


def test_gate_both_true_places_both_and_both_false_places_none(store, tmp_path):
    server, plan = FakeServer(), _mixed_plan()
    Broker(server).submit_plan(plan, plan["fingerprint"], run_store=store)
    assert _post_symbols(server) == ["AAPL", "XLK"]
    server2, plan2 = FakeServer(), _mixed_plan(new_orders_allowed=False, satellite_new_orders_allowed=False)
    Broker(server2).submit_plan(plan2, plan2["fingerprint"], run_store=RunStore(tmp_path / "other.db"))
    assert server2.posts == []


def test_unknown_sleeve_label_is_never_permitted():
    plan = _mixed_plan()
    plan["sleeve_of"]["AAPL"] = "moonshot"
    allowed, blocked = enforce_order_gate(plan)
    assert [o["symbol"] for o in allowed] == ["XLK"] and [o["symbol"] for o in blocked] == ["AAPL"]


def test_gate_sell_from_held_satellite_needs_explicit_reason():
    plan = build_order_plan({"XLK": .2}, HELD, EQUITY, new_orders_allowed=True, satellite_new_orders_allowed=True,
                            sleeve_of={"AAPL": "satellite"})
    assert ("AAPL", "sell") in _sides(plan)
    plan["satellite_new_orders_allowed"] = False            # flag flips to hold after the plan was built
    assert [o["symbol"] for o in enforce_order_gate(plan)[1]] == ["AAPL"]
    plan["sell_reasons"] = {"AAPL": "stop-loss"}
    assert [o["symbol"] for o in enforce_order_gate(plan)[0] if o["symbol"] == "AAPL"] == ["AAPL"]


def test_hold_in_current_plan_blocks_orders_of_a_resumed_stored_plan(store):
    """Round started while the satellite was fine (stored plan allows it) but nothing was placed yet;
    a retry made while the satellite is on hold must not place the satellite order."""
    server = FakeServer()
    stored = _mixed_plan()
    server.lookup_fails = True                              # 1st attempt: cannot even look up -> nothing posted
    Broker(server).submit_plan(stored, stored["fingerprint"], run_store=store)
    assert server.posts == []
    server.lookup_fails = False
    retry = _mixed_plan(satellite_new_orders_allowed=False)
    res = Broker(server).submit_plan(retry, retry["fingerprint"], run_store=store)
    assert _post_symbols(server) == ["XLK"]
    assert {r["symbol"]: r["reconcile_state"] for r in res}["AAPL"] == "blocked_hold"


# ---- recommendation flag ------------------------------------------------------------------------

def _pit(monkeypatch, pool, breakout, **kw):
    _make_satellite_mocks(monkeypatch, pool, breakout)
    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history_calendar)
    return champion_strategy.compute_satellite_recommendation_point_in_time(as_of_date="2022-03-15", top_k=3, **kw)


def test_recommendation_allowed_with_data_and_picks(monkeypatch):
    rec = _pit(monkeypatch, ["AAA", "BBB", "CCC"], {"AAA", "BBB"})
    assert rec["new_orders_allowed"] is True and rec["per_ticker_weights"]
    assert rec["data_coverage"]["n_with_history"] == 3 and rec["data_coverage"]["pool_size"] == 3


def test_recommendation_no_trend_candidates_with_healthy_data_is_cash_not_hold(monkeypatch):
    rec = _pit(monkeypatch, ["CCC", "DDD"], set())
    assert rec["selected"] == [] and rec["new_orders_allowed"] is True
    assert rec["unallocated_weight"] == pytest.approx(champion_strategy.SATELLITE_WEIGHT)


def test_recommendation_empty_pool_is_a_hold(monkeypatch):
    rec = _pit(monkeypatch, [], set())
    assert rec["new_orders_allowed"] is False and rec["per_ticker_weights"] == {}
    assert "후보 풀" in rec["allocation_reason"]


def test_recommendation_no_price_history_for_any_candidate_is_a_hold(monkeypatch):
    _make_satellite_mocks(monkeypatch, ["AAA", "BBB"], {"AAA"})
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", lambda *a, **k: {})
    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history_calendar)
    rec = champion_strategy.compute_satellite_recommendation_point_in_time(as_of_date="2022-03-15", top_k=3)
    assert rec["new_orders_allowed"] is False and rec["per_ticker_weights"] == {}
    assert rec["data_coverage"]["n_with_history"] == 0


def test_recommendation_pick_without_current_price_is_a_hold(monkeypatch):
    _make_satellite_mocks(monkeypatch, ["AAA", "BBB"], {"AAA", "BBB"})
    real = champion_strategy.get_multiple_price_history
    calls = {"n": 0}

    def flaky(tickers, **kw):
        calls["n"] += 1
        return real(tickers, **kw) if calls["n"] == 1 else {}      # 2nd call = price refresh of the picks
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", flaky)
    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history_calendar)
    rec = champion_strategy.compute_satellite_recommendation_point_in_time(as_of_date="2022-03-15", top_k=3)
    assert rec["selected"] and rec["new_orders_allowed"] is False and rec["per_ticker_weights"] == {}
    assert rec["data_coverage"]["picks_missing_price"]


def test_recommendation_flag_flows_into_paper_plan(monkeypatch):
    """End to end: unavailable satellite data -> plan holds the satellite sleeve, core still trades."""
    rec = _pit(monkeypatch, [], set())
    plan = cpt.build_plan(CORE_OK, rec, HELD, EQUITY)
    assert plan["satellite_new_orders_allowed"] is False and ("AAPL", "sell") not in _sides(plan)
