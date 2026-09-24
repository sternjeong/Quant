"""scripts/verify_alpaca_paper_idempotency.py -- logic tested against an in-process Alpaca simulator.

`requests.request` is replaced by the simulator and sockets are blocked, so nothing here can reach the
network.  The simulator answers like the real paper API is ASSUMED to (404 unknown, 422 duplicate,
204 cancel) and can be told to misbehave; the tool must then say FAIL / UNEXPECTED instead of PASS.
"""
import importlib.util
import json
import pathlib
import socket

import pytest
import requests

from core.paper_execution import PAPER_BASE_URL

_spec = importlib.util.spec_from_file_location(
    "verify_alpaca_paper_idempotency",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "verify_alpaca_paper_idempotency.py")
vp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vp)

KEY, SECRET = "PKTESTKEY1234567890", "TESTSECRET1234567890abcdefghijklmnop"
ENV = {"ALPACA_PAPER_API_KEY": KEY, "ALPACA_PAPER_API_SECRET": SECRET}


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(str(self.status_code))
            err.response = self
            raise err


class AlpacaSim:
    """Minimal Alpaca paper simulator.  Knobs default to 'behaves as the code assumes'."""
    def __init__(self, **knobs):
        self.calls, self.orders, self.seq = [], {}, 0
        self.unknown_status = 404          # answer to lookup of an unknown client_order_id
        self.duplicate = "422"             # "422" | "accept" (creates a 2nd order) | "replay" | "409" | "403"
        self.auth_fail = False
        self.account = {"id": "acct-uuid-1", "account_number": "PA123", "equity": "100000", "status": "ACTIVE",
                        "trading_blocked": False, "account_blocked": False, "currency": "USD"}
        self.initial_status = "accepted"   # status of a freshly placed order ("filled" simulates a bad price)
        self.cancel_status = 204
        self.pending_cancel_polls = 0      # lookups that still say pending_cancel after a cancel
        self.never_cancels = False
        self.raise_on_list = False
        self.lookup_500 = False
        for k, v in knobs.items():
            setattr(self, k, v)
        self._pending_left = {}

    # ---- helpers
    def _new_order(self, body):
        self.seq += 1
        order = {"id": f"oid-{self.seq}", "client_order_id": body["client_order_id"], "symbol": body["symbol"],
                 "side": body["side"], "type": body["type"], "qty": body["qty"], "filled_qty": "0",
                 "limit_price": body["limit_price"], "status": self.initial_status, "time_in_force": body["time_in_force"]}
        if self.initial_status == "filled":
            order["filled_qty"] = body["qty"]
        self.orders[order["id"]] = order
        return order

    def __call__(self, method, url, headers=None, timeout=None, **kw):
        assert url.startswith(PAPER_BASE_URL), f"request left the paper endpoint: {url}"
        assert headers["APCA-API-KEY-ID"] == KEY
        path = url[len(PAPER_BASE_URL):]
        self.calls.append((method, path, kw))
        if self.auth_fail:
            return Resp(401, {"message": "forbidden"})
        if method == "GET" and path == "/v2/clock":
            return Resp(200, {"is_open": False, "timestamp": "2026-09-21T12:00:00Z"})
        if method == "GET" and path == "/v2/account":
            return Resp(200, self.account)
        if method == "GET" and path == "/v2/orders:by_client_order_id":
            if self.lookup_500:
                return Resp(500, {"message": "boom"})
            cid = kw["params"]["client_order_id"]
            found = [o for o in self.orders.values() if o["client_order_id"] == cid]
            if not found:
                return Resp(self.unknown_status, {"code": 40410000, "message": "order not found"})
            order = found[0]
            if order.get("_cancel_requested") and not self.never_cancels:
                left = self._pending_left.setdefault(order["id"], self.pending_cancel_polls)
                if left > 0:
                    self._pending_left[order["id"]] = left - 1
                    return Resp(200, {**order, "status": "pending_cancel"})
                order["status"] = "canceled"
            elif order.get("_cancel_requested"):
                return Resp(200, {**order, "status": "pending_cancel"})
            return Resp(200, {k: v for k, v in order.items() if not k.startswith("_")})
        if method == "GET" and path == "/v2/orders":
            if self.raise_on_list:
                raise RuntimeError("simulated crash mid-run")
            return Resp(200, [{k: v for k, v in o.items() if not k.startswith("_")} for o in self.orders.values()])
        if method == "POST" and path == "/v2/orders":
            body = kw["json"]
            if any(o["client_order_id"] == body["client_order_id"] for o in self.orders.values()):
                if self.duplicate == "422":
                    return Resp(422, {"code": 40010001, "message": "client_order_id must be unique"})
                if self.duplicate == "409":
                    return Resp(409, {"message": "conflict"})
                if self.duplicate == "403":
                    return Resp(403, {"message": "forbidden"})
                if self.duplicate == "replay":
                    return Resp(200, next(o for o in self.orders.values() if o["client_order_id"] == body["client_order_id"]))
                return Resp(200, self._new_order(body))   # "accept": a second real order
            return Resp(200, self._new_order(body))
        if method == "DELETE" and path.startswith("/v2/orders/"):
            oid = path.rsplit("/", 1)[1]
            if oid in self.orders and self.cancel_status < 300:
                self.orders[oid]["_cancel_requested"] = True
            return Resp(self.cancel_status, None)
        raise AssertionError(f"unexpected call {method} {path}")

    def methods(self):
        return [m for m, _, _ in self.calls]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("real network access attempted")
    monkeypatch.setattr(socket.socket, "connect", _blocked)


@pytest.fixture
def sim(monkeypatch):
    s = AlpacaSim()
    monkeypatch.setattr(requests, "request", s)
    return s


def _configure(monkeypatch, **knobs):
    s = AlpacaSim(**knobs)
    monkeypatch.setattr(requests, "request", s)
    return s


def _verify(write=False, **kw):
    return vp.verify(vp.PaperApi(KEY, SECRET), KEY, SECRET, write=write, sleep=lambda s: None, **kw)


def _verdicts(report):
    return {s["id"]: s["verdict"] for s in report["steps"]}


# ---- read-only --------------------------------------------------------------------------------------

def test_read_only_pass_sends_no_write_calls_and_says_idempotency_not_verified(sim):
    report = _verify(write=False)
    assert _verdicts(report) == {"R1_clock": "PASS", "R2_account": "PASS", "R3_lookup_unknown_raw": "PASS",
                                 "R4_lookup_unknown_code_path": "PASS"}
    assert report["overall"] == "PASS" and report["mode"] == "read_only"
    assert set(sim.methods()) == {"GET"}                       # nothing that could place or cancel an order
    assert report["idempotency_verified"] is False
    assert "NOT verified" in report["verified_scope"]
    r3 = next(s for s in report["steps"] if s["id"] == "R3_lookup_unknown_raw")
    assert r3["actual_status"] == 404 and r3["expected"] == "404"
    acct = next(s for s in report["steps"] if s["id"] == "R2_account")["observed"]
    assert "acct-uuid-1" not in json.dumps(report) and "PA123" not in json.dumps(report)   # ids/equity not recorded
    assert acct["has_id_or_account_number"] is True


def test_every_request_targets_the_paper_endpoint_only(sim):
    _verify(write=True)
    assert sim.calls                                            # (the simulator asserts the URL prefix on every call)


def test_unknown_id_answering_200_is_a_fail(monkeypatch):
    _configure(monkeypatch, unknown_status=200)
    report = _verify()
    v = _verdicts(report)
    assert v["R3_lookup_unknown_raw"] == "FAIL" and v["R4_lookup_unknown_code_path"] == "FAIL" and report["overall"] == "FAIL"


def test_unknown_id_answering_422_is_a_fail_not_a_pass(monkeypatch):
    _configure(monkeypatch, unknown_status=422)
    assert _verdicts(_verify())["R3_lookup_unknown_raw"] == "FAIL"


def test_server_error_on_lookup_is_unexpected(monkeypatch):
    _configure(monkeypatch, lookup_500=True)
    report = _verify()
    assert _verdicts(report)["R3_lookup_unknown_raw"] == "UNEXPECTED" and report["overall"] == "UNEXPECTED"


def test_auth_failure_is_unexpected_and_blocks_the_write_phase(monkeypatch):
    s = _configure(monkeypatch, auth_fail=True)
    report = _verify(write=True)
    assert report["overall"] == "UNEXPECTED"
    assert "POST" not in s.methods() and "DELETE" not in s.methods()
    assert _verdicts(report)["W*"] == "SKIPPED"


def test_blocked_account_is_unexpected_and_nothing_is_submitted(monkeypatch):
    s = _configure(monkeypatch, account={**AlpacaSim().account, "trading_blocked": True})
    report = _verify(write=True)
    assert _verdicts(report)["R2_account"] == "UNEXPECTED" and "POST" not in s.methods()


def test_account_missing_fields_the_code_reads_is_a_fail(monkeypatch):
    _configure(monkeypatch, account={"status": "ACTIVE"})
    assert _verdicts(_verify())["R2_account"] == "FAIL"


# ---- write phase -------------------------------------------------------------------------------------

def test_write_happy_path_passes_every_step_in_order(sim):
    report = _verify(write=True)
    assert _verdicts(report) == {
        "R1_clock": "PASS", "R2_account": "PASS", "R3_lookup_unknown_raw": "PASS", "R4_lookup_unknown_code_path": "PASS",
        "W1_submit": "PASS", "W2_duplicate_submit": "PASS", "W2b_count_orders_with_id": "PASS",
        "W3_lookup_placed": "PASS", "W4_cancel": "PASS", "W5_confirm_cancel": "PASS"}
    assert report["overall"] == "PASS" and report["idempotency_verified"] is True
    posts = [kw["json"] for m, p, kw in sim.calls if m == "POST"]
    assert len(posts) == 2 and posts[0] == posts[1]                                # the SAME body, same client_order_id
    body = posts[0]
    assert (body["qty"], body["side"], body["type"], body["limit_price"]) == ("1", "buy", "limit", "1.00")
    assert body["client_order_id"].startswith("qverify-")
    assert sim.methods().count("DELETE") == 1
    dup = next(s for s in report["steps"] if s["id"] == "W2_duplicate_submit")
    assert dup["actual_status"] == 422 and dup["expected"] == "422" and "unique" in dup["observed"]["message"]
    assert next(s for s in report["steps"] if s["id"] == "W4_cancel")["actual_status"] == 204
    assert report["status_mapping"]["canceled"] == "rejected" and report["status_mapping"]["accepted"] == "open"
    # known gaps of classify_order_state, reported (not judged): these keep a run open until an operator closes it
    assert report["unmapped_statuses"] == ["calculated", "done_for_day"]


def test_duplicate_accepted_by_broker_is_a_fail_and_both_orders_get_canceled(monkeypatch):
    s = _configure(monkeypatch, duplicate="accept")
    report = _verify(write=True)
    v = _verdicts(report)
    assert v["W2_duplicate_submit"] == "FAIL" and v["W2b_count_orders_with_id"] == "FAIL"
    assert report["overall"] == "FAIL"
    assert s.methods().count("DELETE") == 2                                        # nothing left behind


@pytest.mark.parametrize("dup, expected", [("409", "FAIL"), ("403", "UNEXPECTED"), ("replay", "UNEXPECTED")])
def test_other_duplicate_answers_are_not_pass(monkeypatch, dup, expected):
    _configure(monkeypatch, duplicate=dup)
    report = _verify(write=True)
    assert _verdicts(report)["W2_duplicate_submit"] == expected and report["overall"] != "PASS"


def test_lookup_404_right_after_placing_is_a_fail(monkeypatch):
    s = _configure(monkeypatch, unknown_status=404)
    orig = s.__call__

    def hide_order(method, url, headers=None, timeout=None, **kw):
        if method == "GET" and url.endswith("orders:by_client_order_id") and s.orders and s.methods().count("POST") == 2 \
                and "DELETE" not in s.methods():
            s.calls.append((method, "/v2/orders:by_client_order_id", kw))
            return Resp(404, {"message": "order not found"})
        return orig(method, url, headers=headers, timeout=timeout, **kw)
    monkeypatch.setattr(requests, "request", hide_order)
    report = _verify(write=True)
    assert _verdicts(report)["W3_lookup_placed"] == "FAIL"


def test_order_that_fills_is_unexpected_skips_the_rest_and_flags_manual_action(monkeypatch):
    s = _configure(monkeypatch, initial_status="filled")
    report = _verify(write=True)
    v = _verdicts(report)
    assert v["W1_submit"] == "UNEXPECTED" and v["W2_duplicate_submit"] == "SKIPPED"
    assert s.methods().count("POST") == 1                                          # no duplicate submitted on top of a fill
    assert report["manual_action_required"] is True and report["cleanup"]["attempted"] is True
    assert report["overall"] == "UNEXPECTED"


def test_first_submission_rejected_is_unexpected_and_nothing_to_cancel(monkeypatch):
    s = _configure(monkeypatch, duplicate="422")
    orig = s.__call__

    def reject(method, url, headers=None, timeout=None, **kw):
        if method == "POST":
            s.calls.append((method, "/v2/orders", kw))
            return Resp(403, {"message": "insufficient buying power"})
        return orig(method, url, headers=headers, timeout=timeout, **kw)
    monkeypatch.setattr(requests, "request", reject)
    report = _verify(write=True)
    assert _verdicts(report)["W1_submit"] == "UNEXPECTED" and "DELETE" not in s.methods()
    assert "cleanup" not in report


def test_pending_cancel_is_polled_until_canceled(monkeypatch):
    slept = []
    _configure(monkeypatch, pending_cancel_polls=2)
    report = vp.verify(vp.PaperApi(KEY, SECRET), KEY, SECRET, write=True, sleep=slept.append, poll_interval=0.5)
    assert _verdicts(report)["W5_confirm_cancel"] == "PASS" and slept == [0.5, 0.5]


def test_never_confirmed_cancellation_is_unexpected_with_manual_action(monkeypatch):
    s = _configure(monkeypatch, never_cancels=True)
    report = _verify(write=True, poll_tries=3)
    assert _verdicts(report)["W5_confirm_cancel"] == "UNEXPECTED"
    assert report["manual_action_required"] is True and report["cleanup"]["attempted"] is True
    assert s.methods().count("DELETE") >= 2                                        # W4 + cleanup retry


def test_cancel_refused_is_unexpected(monkeypatch):
    _configure(monkeypatch, cancel_status=422)
    report = _verify(write=True, poll_tries=1)
    assert _verdicts(report)["W4_cancel"] == "UNEXPECTED" and report["overall"] == "UNEXPECTED"


def test_crash_mid_run_still_attempts_to_cancel_the_test_order(monkeypatch):
    s = _configure(monkeypatch, raise_on_list=True)
    with pytest.raises(RuntimeError):
        _verify(write=True)
    assert s.methods().count("DELETE") == 1                                        # finally-cleanup ran


# ---- CLI / secrets ------------------------------------------------------------------------------------

def test_cli_missing_credentials_exit_3_names_only(monkeypatch, capsys):
    s = _configure(monkeypatch)
    assert vp.main([], env={"ALPACA_PAPER_API_KEY": KEY}) == vp.EXIT_SETUP
    err = capsys.readouterr().err
    assert "ALPACA_PAPER_API_SECRET" in err and KEY not in err and s.calls == []


def test_cli_never_prints_or_stores_credentials_even_if_the_server_echoes_them(monkeypatch, capsys, tmp_path):
    s = _configure(monkeypatch)
    orig = s.__call__

    def echo(method, url, headers=None, timeout=None, **kw):
        r = orig(method, url, headers=headers, timeout=timeout, **kw)
        if url.endswith("by_client_order_id") and r.status_code == 404:
            r = Resp(404, {"message": f"order not found for key {KEY} secret {SECRET}"})
        return r
    monkeypatch.setattr(requests, "request", echo)
    out_file = tmp_path / "report.json"
    assert vp.main(["--write", "--output", str(out_file)], env=ENV, sleep=lambda s: None) == vp.EXIT_PASS
    captured = capsys.readouterr()
    written = out_file.read_text(encoding="utf-8")
    for text in (captured.out, captured.err, written):
        assert KEY not in text and SECRET not in text
    assert "[REDACTED]" in written
    report = json.loads(written)
    assert report["credential_hygiene"] == {"key_length": len(KEY), "secret_length": len(SECRET),
                                            "key_has_whitespace_or_quote": False, "secret_has_whitespace_or_quote": False}


def test_cli_read_only_default_prints_json_to_stdout_and_exit_codes(monkeypatch, capsys):
    _configure(monkeypatch)
    assert vp.main([], env=ENV) == vp.EXIT_PASS
    assert json.loads(capsys.readouterr().out)["mode"] == "read_only"
    _configure(monkeypatch, unknown_status=200)
    assert vp.main([], env=ENV) == vp.EXIT_FAIL
    _configure(monkeypatch, auth_fail=True)
    assert vp.main([], env=ENV) == vp.EXIT_UNEXPECTED


def test_cli_flags_credentials_with_quotes_or_whitespace_without_printing_them():
    hygiene = vp.credential_hygiene('"PKQUOTED"', "SEC RET\r")
    assert hygiene["key_has_whitespace_or_quote"] and hygiene["secret_has_whitespace_or_quote"]


def test_cli_refuses_output_under_data_dir_and_unsafe_parameters(monkeypatch):
    s = _configure(monkeypatch)
    data_out = pathlib.Path(vp.PROJECT_ROOT) / "data" / "verify.json"
    assert vp.main(["--output", str(data_out)], env=ENV) == vp.EXIT_SETUP
    assert vp.main(["--write", "--limit-price", "900"], env=ENV) == vp.EXIT_SETUP     # could fill: refused
    assert vp.main(["--symbol", "spy;rm"], env=ENV) == vp.EXIT_SETUP
    assert s.calls == [] and not data_out.exists()


def test_redact_helper_ignores_empty_and_tiny_values():
    assert vp.redact("abc KEYVALUE def", ["KEYVALUE", "", "ab"]) == "abc [REDACTED] def"
