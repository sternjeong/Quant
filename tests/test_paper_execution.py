import pytest
from core.paper_execution import RiskLimits, build_order_plan, validate_targets


def test_plan_sells_before_buys_and_has_confirmation_fingerprint():
    plan = build_order_plan({"XLK": .2125, "XLE": .2125}, {"OLD": {"qty": 10, "market_value": 2000, "current_price": 200}}, 10_000)
    assert plan["mode"] == "paper" and len(plan["fingerprint"]) == 16
    assert {o["symbol"] for o in plan["orders"]} == {"OLD", "XLK", "XLE"}


def test_rejects_concentration():
    with pytest.raises(ValueError):
        validate_targets({"SPY": .30}, RiskLimits(max_position_weight=.25))


# ---- ENG-05: client order ID idempotency (fake broker, no network) ----
import requests
from core.paper_execution import AlpacaPaperBroker, classify_order_state, client_order_id


class FakeServer:
    """Simulates Alpaca: stores orders by client_order_id; can lose responses / fail lookups."""
    def __init__(self):
        self.orders, self.posts, self.lose_response_for, self.reject_for = {}, [], set(), set()
        self.lookup_fails, self.status = False, {}

    def request(self, method, path, **kw):
        if path == "/v2/account":
            return {}
        if path == "/v2/orders:by_client_order_id":
            if self.lookup_fails:
                raise requests.ConnectionError("down")
            cid = kw["params"]["client_order_id"]
            if cid not in self.orders:
                err = requests.HTTPError("404"); err.response = type("R", (), {"status_code": 404})(); raise err
            return self.orders[cid]
        assert method == "POST"
        body = kw["json"]; cid = body["client_order_id"]; self.posts.append(cid)
        if body["symbol"] in self.reject_for:
            err = requests.HTTPError("403"); err.response = type("R", (), {"status_code": 403})(); raise err
        if cid in self.orders:
            err = requests.HTTPError("422"); err.response = type("R", (), {"status_code": 422})(); raise err
        self.orders[cid] = {"id": "x" + cid, "client_order_id": cid, "symbol": body["symbol"],
                            "status": self.status.get(body["symbol"], "accepted"), "filled_qty": "0"}
        if body["symbol"] in self.lose_response_for:
            self.lose_response_for.discard(body["symbol"])
            raise requests.ReadTimeout("response lost")
        return self.orders[cid]


def _broker(server):
    b = AlpacaPaperBroker("k", "s")
    b._request = server.request
    return b


def _plan():
    return build_order_plan({"XLK": .2, "XLE": .2}, {}, 10_000)


@pytest.fixture(autouse=True)
def _isolated_run_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_PAPER_RUN_DB", str(tmp_path / "runs.db"))


def test_client_order_id_deterministic():
    a = ("acct", "v1", "r00001")
    assert client_order_id(*a, 0, "XLE") == client_order_id(*a, 0, "XLE")
    assert client_order_id(*a, 0, "XLE") != client_order_id(*a, 1, "XLE")
    assert client_order_id(*a, 0, "XLE") != client_order_id("acct", "v1", "r00002", 0, "XLE")


def test_lost_response_then_retry_creates_no_duplicate():
    server, plan = FakeServer(), _plan()
    server.lose_response_for = {"XLE"}
    first = _broker(server).submit_plan(plan, plan["fingerprint"])
    assert len(server.orders) == 2 and all(r["reconcile_state"] == "open" for r in first)
    _broker(server).submit_plan(plan, plan["fingerprint"])  # process restart / retry
    assert len(server.orders) == 2 and len(server.posts) == 2


def test_lost_response_and_lookup_down_stops_unresolved_then_recovers():
    server, plan = FakeServer(), _plan()
    server.lose_response_for = {"XLE"}
    b = _broker(server)
    orig = server.request
    def flaky(method, path, **kw):  # lookup works before POST, fails after the lost response
        if path.endswith("by_client_order_id") and server.orders:
            raise requests.ConnectionError("down")
        return orig(method, path, **kw)
    b._request = flaky
    res = b.submit_plan(plan, plan["fingerprint"])
    assert res[-1]["reconcile_state"] == "unresolved" and len(res) == 1 and len(server.orders) == 1
    _broker(server).submit_plan(plan, plan["fingerprint"])
    assert len(server.orders) == 2 and len(server.posts) == 2


def test_rejection_recorded_and_not_retried_as_duplicate():
    server, plan = FakeServer(), _plan()
    server.reject_for = {"XLK"}
    res = _broker(server).submit_plan(plan, plan["fingerprint"])
    states = {r["symbol"]: r["reconcile_state"] for r in res}
    assert states["XLK"] == "rejected" and states["XLE"] == "open"


def test_partial_fill_and_states_reported_on_restart():
    server, plan = FakeServer(), _plan()
    _broker(server).submit_plan(plan, plan["fingerprint"])
    for o in server.orders.values():
        if o["symbol"] == "XLK":
            o.update(status="partially_filled", filled_qty="3")
        else:
            o.update(status="filled", filled_qty="5")
    res = _broker(server).submit_plan(plan, plan["fingerprint"])
    assert {r["symbol"]: r["reconcile_state"] for r in res} == {"XLE": "filled", "XLK": "partial"}
    assert len(server.posts) == 2 and all(r["resubmitted"] is False for r in res)


def test_fingerprint_still_required_and_classify():
    with pytest.raises(ValueError):
        _broker(FakeServer()).submit_plan(_plan(), "wrong")
    assert classify_order_state({"status": "canceled", "filled_qty": "2"}) == "partial"
    assert classify_order_state({"status": "canceled", "filled_qty": "0"}) == "rejected"
