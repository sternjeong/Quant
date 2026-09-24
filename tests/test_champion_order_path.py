"""Integration: recommendation -> plan -> submit_plan gate, run ids, reconcile (mock only, no network)."""
import importlib.util
import pathlib
import sys
from datetime import datetime

import pytest
import requests

from core import paper_execution
from core.paper_execution import AlpacaPaperBroker, RunStore, build_order_plan, client_order_id
from tests.test_paper_execution import FakeServer

_spec = importlib.util.spec_from_file_location(
    "champion_paper_trade", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "champion_paper_trade.py")
cpt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cpt)

HELD = {"XLK": {"qty": 10, "market_value": 2000.0, "current_price": 200.0},
        "XLE": {"qty": 20, "market_value": 2000.0, "current_price": 100.0}}
EQUITY = 10_000.0


def _core(status="above"):
    if status == "unknown":  # what compute_core_recommendation returns when SPY data is missing
        return {"top4": ["XLK", "XLE"], "market_filter_status": "unknown", "new_orders_allowed": False,
                "per_ticker_weight": 0.0, "per_ticker_weights": {}, "allocation_reason": "SPY missing"}
    return {"top4": ["XLK", "XLF"], "market_filter_status": "above", "new_orders_allowed": True,
            "per_ticker_weight": 0.2, "per_ticker_weights": {"XLK": 0.2, "XLF": 0.2}}


class Broker(AlpacaPaperBroker):
    def __init__(self, server, positions):
        super().__init__("k", "s")
        self._request = server.request
        self._positions = positions

    def account(self):
        return {"id": "acct-1", "equity": str(EQUITY)}

    def positions(self):
        return self._positions


def _run(server, core, positions=HELD, submit=True, confirm=None, store_path=None):
    b = Broker(server, positions)
    plan = cpt.build_plan(core, {}, positions, EQUITY)
    return cpt.run(b, core, {}, submit=submit, confirm=confirm or plan["fingerprint"], run_store=RunStore(store_path))


@pytest.fixture
def store(tmp_path):
    return tmp_path / "runs.db"


def test_spy_missing_blocks_all_orders_and_keeps_holdings(store):
    server = FakeServer()
    out = _run(server, _core("unknown"), store_path=store)
    assert server.posts == []                      # nothing reached the broker
    assert out["plan"]["orders"] == []             # no liquidation plan either
    assert out["plan"]["new_orders_allowed"] is False


def test_submit_plan_itself_refuses_buys_when_gate_closed(store):
    """Gate lives at the POST point: a hand-built plan with a buy and no allow flag is blocked."""
    server = FakeServer()
    plan = build_order_plan({"XLK": .2}, {}, EQUITY)
    plan["new_orders_allowed"] = False
    res = Broker(server, {}).submit_plan(plan, plan["fingerprint"], run_store=RunStore(store))
    assert server.posts == [] and res[0]["reconcile_state"] == "blocked_hold"
    forged = {k: v for k, v in plan.items() if k != "new_orders_allowed"}  # missing flag -> fail closed
    Broker(server, {}).submit_plan(forged, forged["fingerprint"], run_store=RunStore(store))
    assert server.posts == []


def test_explicit_sell_reason_allowed_on_hold_but_other_holdings_kept(store):
    server = FakeServer()
    plan = build_order_plan({}, HELD, EQUITY, new_orders_allowed=False, sell_reasons={"XLE": "delisted"})
    assert [(o["symbol"], o["side"]) for o in plan["orders"]] == [("XLE", "sell")]
    Broker(server, HELD).submit_plan(plan, plan["fingerprint"], run_store=RunStore(store))
    assert [c.split("-")[-1] for c in server.posts] == ["XLE"]


def test_open_market_sells_come_first():
    plan = build_order_plan({"AAA": .2, "BBB": .2}, {"ZZZ": {"qty": 5, "market_value": 1000, "current_price": 200}}, EQUITY)
    assert [o["side"] for o in plan["orders"]] == ["sell", "buy", "buy"]


def test_lost_response_retry_no_duplicate_and_reconcile_state_reported(store, capsys):
    server = FakeServer()
    server.lose_response_for = {"XLF"}
    out = _run(server, _core(), store_path=store)
    assert set(out["reconcile_state"].values()) == {"open"}
    _run(server, _core(), store_path=store)   # retry with fresh objects
    assert len(server.orders) == len(server.posts) == 2   # sell XLE, buy XLF (XLK already at 20% target)


def test_partial_fill_reported_and_not_resubmitted(store):
    server = FakeServer()
    _run(server, _core(), store_path=store)
    n = len(server.posts)
    for o in server.orders.values():
        o.update(status="partially_filled", filled_qty="1")
    out = _run(server, _core(), store_path=store)
    assert set(out["reconcile_state"].values()) == {"partial"} and len(server.posts) == n


def test_restart_same_run_id_and_next_round_new_ids(store):
    server = FakeServer()
    server.lose_response_for = {"XLF"}
    first = _run(server, _core(), store_path=store)
    run1 = {r["run_id"] for r in first["results"]}
    assert len(run1) == 1
    # process re-created (new RunStore + broker objects): same run id, no new POSTs
    posts = len(server.posts)
    again = _run(server, _core(), store_path=store)
    assert {r["run_id"] for r in again["results"]} == run1 and len(server.posts) == posts
    # round completed (all ids resolved) -> next scheduled round gets a different run id and ids
    ids_round1 = set(server.orders)
    for o in server.orders.values():
        o.update(status="filled", filled_qty="1")
    third = _run(server, _core(), store_path=store)
    assert {r["run_id"] for r in third["results"]} != run1
    assert len(server.orders) == 4 and not (set(server.orders) - ids_round1) & ids_round1


def test_incomplete_round_survives_midnight_with_same_ids(store, monkeypatch):
    server = FakeServer()
    server.lose_response_for = {"XLF"}
    orig = server.request

    def down_after_post(method, path, **kw):   # lookup fails after the lost response -> unresolved
        if path.endswith("by_client_order_id") and server.orders and "XLF" in {o["symbol"] for o in server.orders.values()}:
            raise requests.ConnectionError("down")
        return orig(method, path, **kw)
    b = Broker(server, HELD); b._request = down_after_post
    plan = cpt.build_plan(_core(), {}, HELD, EQUITY)

    class Day1(datetime):
        @classmethod
        def now(cls, tz=None): return cls(2026, 9, 21, 23, 59)
    class Day2(datetime):
        @classmethod
        def now(cls, tz=None): return cls(2026, 9, 22, 0, 5)
    monkeypatch.setattr(paper_execution, "datetime", Day1, raising=False)
    r1 = b.submit_plan(plan, plan["fingerprint"], run_store=RunStore(store), strategy_version="v")
    assert r1[-1]["reconcile_state"] == "unresolved"
    ids_before = set(server.orders)
    monkeypatch.setattr(paper_execution, "datetime", Day2, raising=False)
    r2 = Broker(server, HELD).submit_plan(plan, plan["fingerprint"], run_store=RunStore(store), strategy_version="v")
    assert {r["run_id"] for r in r1 + r2} == {r1[0]["run_id"]}
    assert ids_before <= set(server.orders)
    assert len(server.posts) == len(set(server.posts)) == len(server.orders)  # no duplicate POST of one id


def test_client_order_id_is_wall_clock_independent(monkeypatch):
    """같은 (account, strategy_version, run_id, index, symbol)이면 계산 시점의 벽시계 날짜와 무관하게
    항상 같은 id여야 한다 — run_id 대신 오늘 날짜가 섞여 드는 회귀를 직접 잡는다.

    2026-09-22 게이트 변이 재검증에서, 이 파일의 test_incomplete_round_survives_midnight_with_same_ids가
    이름과 달리 이 회귀를 실제로는 못 잡는다는 것이 드러났다(그 테스트의 down_after_post 목이 어떤
    client_order_id를 조회하든 무조건 ConnectionError를 내서, 날짜가 바뀌어 다른 id가 조회되는 증상이
    드러나기 전에 루프가 끊긴다). 이 테스트와 아래 테스트가 그 사각지대를 메운다."""
    class Day1(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 21, 23, 59)

    class Day2(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 22, 0, 5)

    args = ("acct", "v1", "r00001", 0, "XLE")
    monkeypatch.setattr(paper_execution, "datetime", Day1, raising=False)
    id_day1 = client_order_id(*args)
    monkeypatch.setattr(paper_execution, "datetime", Day2, raising=False)
    id_day2 = client_order_id(*args)
    assert id_day1 == id_day2, (
        "client_order_id changed across a wall-clock day boundary with identical run_id/index/symbol "
        "— today's date leaked into the id (it must depend only on run_id, not the calendar date)"
    )


def test_resume_across_midnight_with_healthy_lookup_reuses_same_id_no_duplicate_post(store, monkeypatch):
    """자정 전에 낸 주문이 아직 열려 있고 브로커 조회가 정상 성공하는 상황(모호한 실패 목 없음)에서
    자정 후 재시도하면 같은 client_order_id로 인식되어야 하며 중복 POST가 없어야 한다.

    test_incomplete_round_survives_midnight_with_same_ids와 달리 조회 실패를 유도하지 않는다 —
    날짜가 섞인 id는 스스로 lookup miss → 중복 POST로 드러나야 하고, 이 테스트는 그 경로를 가리지 않는다."""
    class Day1(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 21, 23, 59)

    class Day2(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 22, 0, 5)

    server = FakeServer()
    plan = cpt.build_plan(_core(), {}, HELD, EQUITY)

    monkeypatch.setattr(paper_execution, "datetime", Day1, raising=False)
    r1 = Broker(server, HELD).submit_plan(plan, plan["fingerprint"], run_store=RunStore(store), strategy_version="v")
    assert len(server.posts) == len(server.orders) > 0
    ids_after_day1 = set(server.orders)

    monkeypatch.setattr(paper_execution, "datetime", Day2, raising=False)
    r2 = Broker(server, HELD).submit_plan(plan, plan["fingerprint"], run_store=RunStore(store), strategy_version="v")

    assert set(server.orders) == ids_after_day1, "a new client_order_id was looked up after midnight"
    assert len(server.posts) == len(ids_after_day1), "the order was resubmitted (duplicated) after crossing midnight"
    assert {o["client_order_id"] for o in r1} == {o["client_order_id"] for o in r2}
