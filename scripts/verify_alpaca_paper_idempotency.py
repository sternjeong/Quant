#!/usr/bin/env python3
"""Verify against the REAL Alpaca *paper* API the behaviours core/paper_execution.py assumes.

Until this has been run by a human with paper keys, the idempotency design (client_order_id, lookup by
client_order_id, 404 on unknown id, 422 on duplicate, order-status mapping) is only verified against a
mock.  This tool records what the paper API really answers and judges each step:

  PASS        the response matches what the code assumes
  FAIL        a definite response contradicts an assumption the code depends on
  UNEXPECTED  the step could not be judged (auth/network/rate limit/unusable state) or something
              dangerous showed up (an order that filled) -- read the note

Default mode is READ-ONLY (clock, account, lookup of a client_order_id that does not exist -> 404).
Only with --write does it place ONE far-from-market limit BUY of 1 share, resubmit the same
client_order_id, look it up, cancel it and confirm the cancellation.  Cancellation is attempted again
in a cleanup step if anything goes wrong.  Nothing is ever sent to the live endpoint: the base URL is
core.paper_execution.PAPER_BASE_URL and cannot be changed from the command line.

Credentials come ONLY from the environment (same names the rest of the code uses):
  ALPACA_PAPER_API_KEY, ALPACA_PAPER_API_SECRET
Their values are never printed or stored; any occurrence in the report is redacted as a safety net.

Usage:
  python scripts/verify_alpaca_paper_idempotency.py                       # read-only, JSON to stdout
  python scripts/verify_alpaca_paper_idempotency.py --write --output /tmp/paper_verify.json
  (--output must not be under the repository's data/ directory)

Exit codes: 0 PASS, 1 FAIL, 2 UNEXPECTED, 3 setup error (missing credentials / refused parameters).
See docs/PAPER_API_VERIFICATION_RUNBOOK.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.paper_execution import (  # noqa: E402
    PAPER_BASE_URL, AlpacaPaperBroker, _is_terminal, classify_order_state,
)

KEY_ENV, SECRET_ENV = "ALPACA_PAPER_API_KEY", "ALPACA_PAPER_API_SECRET"
EXIT_PASS, EXIT_FAIL, EXIT_UNEXPECTED, EXIT_SETUP = 0, 1, 2, 3
MAX_TEST_NOTIONAL = 25.0        # refuse a test order whose qty * limit price exceeds this (it must never fill anyway)
TRANSIENT = {401, 403, 429}     # cannot judge an assumption from these (auth / permissions / rate limit)
ORDER_FIELDS = ("id", "client_order_id", "symbol", "side", "type", "qty", "filled_qty", "limit_price", "status",
                "time_in_force", "created_at", "canceled_at")

# What the code assumes (shown in the report so a reader can compare with the observed answers).
CODE_ASSUMPTIONS = {
    "lookup_unknown_client_order_id": "GET /v2/orders:by_client_order_id for an unknown id -> 404 "
                                      "(AlpacaPaperBroker.order_by_client_id returns None only on 404)",
    "duplicate_client_order_id": "POST /v2/orders with an already used client_order_id -> 422 "
                                 "(submit_plan then reconciles by lookup; any other 4xx is recorded as 'rejected')",
    "lookup_finds_placed_order": "the order just placed is found by client_order_id (this is what stops duplicates)",
    "status_mapping": "classify_order_state maps broker statuses to filled/partial/open/rejected/unknown; "
                      "a canceled order with filled_qty 0 -> 'rejected' which is terminal (run can close)",
    "account_fields": "GET /v2/account has id (or account_number), equity, trading_blocked, account_blocked",
}
# Documented Alpaca order statuses and what classify_order_state makes of them (offline, informational).
DOCUMENTED_STATUSES = ("new", "partially_filled", "filled", "done_for_day", "canceled", "expired", "replaced",
                       "pending_cancel", "pending_replace", "accepted", "pending_new", "accepted_for_bidding",
                       "stopped", "rejected", "suspended", "calculated", "held")


class Reply:
    """One HTTP answer (or transport failure).  ``body`` is parsed JSON when possible."""
    def __init__(self, status: int | None, body: Any = None, text: str = "", error: str | None = None):
        self.status, self.body, self.text, self.error = status, body, text, error

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


class PaperApi:
    """Raw paper-endpoint client: returns status + body instead of raising, so every code can be recorded."""
    def __init__(self, key: str, secret: str, timeout: float = 20):
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self._timeout = timeout

    def call(self, method: str, path: str, **kwargs: Any) -> Reply:
        try:
            response = requests.request(method, PAPER_BASE_URL + path, headers=self._headers,
                                        timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            return Reply(None, error=type(exc).__name__)
        try:
            body = response.json()
        except ValueError:
            body = None
        return Reply(response.status_code, body, (getattr(response, "text", "") or "")[:300])


# ---------------------------------------------------------------------------------------------------
# report helpers

def _order_summary(body: Any) -> Any:
    if isinstance(body, dict):
        return {k: body[k] for k in ORDER_FIELDS if k in body}
    if isinstance(body, list):
        return [_order_summary(b) for b in body[:5]]
    return body


def _error_summary(reply: Reply) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if reply.error:
        out["transport_error"] = reply.error
    if isinstance(reply.body, dict):
        for k in ("code", "message"):
            if k in reply.body:
                out[k] = str(reply.body[k])[:300]
    elif reply.text:
        out["text"] = reply.text[:300]
    return out


class Report:
    def __init__(self, mode: str):
        self.data: dict[str, Any] = {
            "tool": "verify_alpaca_paper_idempotency", "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "base_url": PAPER_BASE_URL, "mode": mode, "code_assumptions": CODE_ASSUMPTIONS, "steps": [],
        }

    def step(self, step_id: str, description: str, request: dict[str, Any], expected: str, reply: Reply | None,
             verdict: str, note: str = "", observed: Any = None) -> str:
        self.data["steps"].append({
            "id": step_id, "description": description, "request": request, "expected": expected,
            "actual_status": None if reply is None else reply.status,
            "observed": observed if observed is not None else (None if reply is None else _error_summary(reply)),
            "verdict": verdict, "note": note,
        })
        return verdict

    def skip(self, step_id: str, description: str, why: str) -> None:
        self.data["steps"].append({"id": step_id, "description": description, "request": None, "expected": None,
                                   "actual_status": None, "observed": None, "verdict": "SKIPPED", "note": why})

    def finish(self) -> dict[str, Any]:
        verdicts = [s["verdict"] for s in self.data["steps"]]
        counts = {v: verdicts.count(v) for v in ("PASS", "FAIL", "UNEXPECTED", "SKIPPED")}
        overall = "FAIL" if counts["FAIL"] else "UNEXPECTED" if counts["UNEXPECTED"] else "PASS"
        self.data["summary"] = counts
        self.data["overall"] = overall
        # offline, informational: how classify_order_state reads every documented Alpaca order status
        mapping = {s: classify_order_state({"status": s, "filled_qty": "0"}) for s in DOCUMENTED_STATUSES}
        self.data["status_mapping"] = mapping
        self.data["unmapped_statuses"] = sorted(s for s, c in mapping.items() if c == "unknown")
        write = self.data["mode"] == "write"
        self.data["idempotency_verified"] = bool(write and overall == "PASS" and not counts["SKIPPED"])
        self.data["verified_scope"] = (
            "read-only + write: duplicate-POST answer, lookup-after-place, cancel and status mapping were exercised"
            if write else
            "read-only: connectivity, account fields and 404-on-unknown-id only. The duplicate-POST answer (422), "
            "lookup-after-place and cancel semantics are NOT verified -- rerun with --write")
        self.data["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return self.data


def _classify_transient(reply: Reply) -> str:
    return "auth/permission rejected -- check the key pair belongs to a PAPER account and is not truncated" \
        if reply.status in (401, 403) else "rate limited / transport / server problem -- retry later"


# ---------------------------------------------------------------------------------------------------
# read-only phase

def run_read_only(api: PaperApi, report: Report, key: str, secret: str) -> bool:
    """Returns True when the account is usable for the write phase."""
    usable = True
    r = api.call("GET", "/v2/clock")
    if r.status == 200 and isinstance(r.body, dict):
        report.step("R1_clock", "GET /v2/clock (connectivity + auth)", {"method": "GET", "path": "/v2/clock"}, "200", r,
                    "PASS", observed={"is_open": r.body.get("is_open")})
    else:
        usable = False
        report.step("R1_clock", "GET /v2/clock (connectivity + auth)", {"method": "GET", "path": "/v2/clock"}, "200", r,
                    "UNEXPECTED", _classify_transient(r) if r.status in (None, 401, 403, 429) or (r.status or 0) >= 500
                    else "unexpected answer from clock endpoint")

    r = api.call("GET", "/v2/account")
    req = {"method": "GET", "path": "/v2/account"}
    if r.status == 200 and isinstance(r.body, dict):
        b = r.body
        has_id = bool(b.get("id") or b.get("account_number"))
        observed = {"status": b.get("status"), "has_id_or_account_number": has_id, "has_equity": "equity" in b,
                    "trading_blocked": b.get("trading_blocked"), "account_blocked": b.get("account_blocked"),
                    "currency": b.get("currency")}
        if not (has_id and "equity" in b and "trading_blocked" in b and "account_blocked" in b):
            usable = False
            report.step("R2_account", "GET /v2/account (fields the code reads)", req, "200 + id/equity/blocked flags", r,
                        "FAIL", "account payload lacks a field submit_plan/champion_paper_trade reads", observed)
        elif b.get("trading_blocked") or b.get("account_blocked"):
            usable = False
            report.step("R2_account", "GET /v2/account (fields the code reads)", req, "200, account not blocked", r,
                        "UNEXPECTED", "account is blocked -- the write phase would be refused", observed)
        else:
            report.step("R2_account", "GET /v2/account (fields the code reads)", req, "200 + id/equity/blocked flags", r,
                        "PASS", observed=observed)
    else:
        usable = False
        report.step("R2_account", "GET /v2/account (fields the code reads)", req, "200", r, "UNEXPECTED",
                    _classify_transient(r) if r.status in (None, 401, 403, 429) or (r.status or 0) >= 500
                    else "unexpected answer from account endpoint")

    missing = f"qverify-nonexistent-{secrets.token_hex(6)}"
    r = api.call("GET", "/v2/orders:by_client_order_id", params={"client_order_id": missing})
    req = {"method": "GET", "path": "/v2/orders:by_client_order_id", "client_order_id": missing}
    if r.status == 404:
        verdict, note = "PASS", "unknown id -> 404 as assumed"
    elif r.status in TRANSIENT or r.status is None or r.status >= 500:
        verdict, note = "UNEXPECTED", _classify_transient(r)
    else:
        verdict, note = "FAIL", (f"unknown id answered {r.status}, not 404 -- order_by_client_id would raise or return a "
                                  "bogus order instead of None (duplicate protection breaks)")
    report.step("R3_lookup_unknown_raw", "lookup of a client_order_id that does not exist (raw status)", req, "404", r,
                verdict, note)

    # same question through the real code path
    broker = AlpacaPaperBroker(key, secret)
    req = {"method": "AlpacaPaperBroker.order_by_client_id", "client_order_id": missing}
    try:
        found = broker.order_by_client_id(missing)
    except (requests.RequestException, ValueError) as exc:
        report.step("R4_lookup_unknown_code_path", "AlpacaPaperBroker.order_by_client_id(unknown) -> None", req, "None", None,
                    "UNEXPECTED", f"code path raised {type(exc).__name__}", {"raised": type(exc).__name__})
    else:
        report.step("R4_lookup_unknown_code_path", "AlpacaPaperBroker.order_by_client_id(unknown) -> None", req, "None", None,
                    "PASS" if found is None else "FAIL",
                    "" if found is None else "code path returned an order for an unknown id",
                    {"returned_none": found is None})
    return usable


# ---------------------------------------------------------------------------------------------------
# write phase

def _find_by_cid(api: PaperApi, cid: str) -> Reply:
    return api.call("GET", "/v2/orders:by_client_order_id", params={"client_order_id": cid})


def run_write(api: PaperApi, report: Report, *, symbol: str, limit_price: float, qty: int,
              poll_tries: int, poll_interval: float, sleep: Callable[[float], None]) -> None:
    cid = f"qverify-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{secrets.token_hex(4)}"
    body = {"symbol": symbol, "qty": str(qty), "side": "buy", "type": "limit", "time_in_force": "day",
            "limit_price": f"{limit_price:.2f}", "client_order_id": cid}
    report.data["test_order"] = {k: v for k, v in body.items()}
    created_ids: set[str] = set()
    cancel_confirmed = False
    try:
        # W1 first submission ---------------------------------------------------------------------
        r1 = api.call("POST", "/v2/orders", json=body)
        req = {"method": "POST", "path": "/v2/orders", "client_order_id": cid}
        if r1.ok and isinstance(r1.body, dict) and r1.body.get("id"):
            created_ids.add(str(r1.body["id"]))
            state = classify_order_state(r1.body)
            if r1.body.get("client_order_id") != cid:
                verdict, note = "FAIL", "response client_order_id differs from the one sent"
            elif state == "open":
                verdict, note = "PASS", "accepted and open"
            elif state in ("filled", "partial"):
                verdict, note = "UNEXPECTED", ("the far limit order FILLED (partly) -- check the paper positions and close "
                                              "it by hand; choose a lower --limit-price next time")
            else:
                verdict, note = "FAIL", f"status {r1.body.get('status')!r} is classified 'unknown' by classify_order_state"
            report.step("W1_submit", "POST far-from-market limit buy, 1 share, with client_order_id", req,
                        "2xx (Alpaca documents 200) + status open", r1, verdict, note,
                        _order_summary(r1.body))
            if verdict != "PASS":
                return _after_w1_failure(report)
        else:
            report.step("W1_submit", "POST far-from-market limit buy, 1 share, with client_order_id", req, "2xx", r1,
                        "UNEXPECTED", (_classify_transient(r1) if r1.status in (None, 401, 403, 429) or (r1.status or 0) >= 500
                                       else "first submission rejected (parameters/price/symbol?) -- cannot judge duplicates"))
            return _after_w1_failure(report)

        # W2 duplicate submission ----------------------------------------------------------------
        r2 = api.call("POST", "/v2/orders", json=body)
        req = {"method": "POST", "path": "/v2/orders", "client_order_id": cid, "note": "same client_order_id resubmitted"}
        if r2.status == 422:
            verdict, note = "PASS", "duplicate client_order_id -> 422 as assumed"
        elif r2.ok and isinstance(r2.body, dict) and str(r2.body.get("id")) in created_ids:
            verdict, note = "UNEXPECTED", ("broker replayed the SAME order (2xx, same id) instead of answering 422 -- harmless "
                                           "for the code (it would treat it as placed) but differs from the 422 assumption")
        elif r2.ok:
            verdict, note = "FAIL", ("broker ACCEPTED a duplicate client_order_id -- lookup-before-POST is the only protection; "
                                     "see W2b for how many orders exist")
            if isinstance(r2.body, dict) and r2.body.get("id"):
                created_ids.add(str(r2.body["id"]))
        elif r2.status in TRANSIENT or r2.status is None or r2.status >= 500:
            verdict, note = "UNEXPECTED", _classify_transient(r2)
        else:
            verdict, note = "FAIL", (f"duplicate answered {r2.status}, not 422 -- submit_plan would record such an answer as "
                                     "'rejected' instead of reconciling through lookup")
        observed = _order_summary(r2.body) if r2.ok else _error_summary(r2)
        report.step("W2_duplicate_submit", "POST the SAME client_order_id again", req, "422", r2, verdict, note, observed)

        # W2b how many orders exist for this id ------------------------------------------------------
        r = api.call("GET", "/v2/orders", params={"status": "all", "symbols": symbol, "limit": 100, "direction": "desc"})
        req = {"method": "GET", "path": "/v2/orders", "params": {"status": "all", "symbols": symbol}}
        if r.status == 200 and isinstance(r.body, list):
            matching = [o for o in r.body if isinstance(o, dict) and o.get("client_order_id") == cid]
            for o in matching:
                if o.get("id"):
                    created_ids.add(str(o["id"]))
            verdict = "PASS" if len(matching) == 1 else "FAIL" if len(matching) > 1 else "UNEXPECTED"
            note = {"PASS": "exactly one order carries the client_order_id",
                    "FAIL": f"{len(matching)} orders carry the same client_order_id -- duplicates CAN be created",
                    "UNEXPECTED": "list did not show the order (page limit / propagation delay)"}[verdict]
            report.step("W2b_count_orders_with_id", "count orders carrying the client_order_id (GET /v2/orders)", req,
                        "exactly 1", r, verdict, note, {"count": len(matching)})
        else:
            report.step("W2b_count_orders_with_id", "count orders carrying the client_order_id (GET /v2/orders)", req,
                        "200 list", r, "UNEXPECTED", _classify_transient(r))

        # W3 lookup by client_order_id ---------------------------------------------------------------
        r3 = _find_by_cid(api, cid)
        req = {"method": "GET", "path": "/v2/orders:by_client_order_id", "client_order_id": cid}
        first_id = next(iter(sorted(created_ids)), None)
        if r3.status == 200 and isinstance(r3.body, dict):
            state = classify_order_state(r3.body)
            if r3.body.get("client_order_id") != cid or (first_id and r3.body.get("id") not in created_ids):
                verdict, note = "FAIL", "lookup returned a different order than the one placed"
            elif state == "open":
                verdict, note = "PASS", "placed order found by client_order_id and classified open"
            elif state in ("filled", "partial"):
                verdict, note = "UNEXPECTED", "order is filled/partly filled -- check positions"
            else:
                verdict, note = "FAIL", f"status {r3.body.get('status')!r} classified 'unknown'"
            report.step("W3_lookup_placed", "GET by client_order_id after placing", req, "200 + same order, state open", r3,
                        verdict, note, _order_summary(r3.body))
        elif r3.status == 404:
            report.step("W3_lookup_placed", "GET by client_order_id after placing", req, "200", r3, "FAIL",
                        "the order that was just placed is NOT found by client_order_id -- the duplicate guard cannot work",
                        _error_summary(r3))
        else:
            report.step("W3_lookup_placed", "GET by client_order_id after placing", req, "200", r3, "UNEXPECTED",
                        _classify_transient(r3))

        # W4 cancel ----------------------------------------------------------------------------------
        cancel_ok = True
        for oid in sorted(created_ids):
            rc = api.call("DELETE", f"/v2/orders/{oid}")
            req = {"method": "DELETE", "path": "/v2/orders/{id}", "id": oid}
            if rc.status == 204:
                verdict, note = "PASS", "cancel accepted (204)"
            elif rc.ok:
                verdict, note = "PASS", f"cancel accepted with {rc.status} (docs say 204)"
            else:
                cancel_ok = False
                verdict, note = "UNEXPECTED", ("cancel refused -- the order may be filled/already terminal; "
                                               "the cleanup step will retry and list what is left")
            report.step("W4_cancel", "DELETE /v2/orders/{id}", req, "204", rc, verdict, note)
        # W5 confirm cancellation --------------------------------------------------------------------
        r5 = Reply(None)
        for attempt in range(max(1, poll_tries)):
            r5 = _find_by_cid(api, cid)
            if r5.status == 200 and isinstance(r5.body, dict) and str(r5.body.get("status", "")).lower() not in (
                    "pending_cancel", "new", "accepted", "pending_new", "accepted_for_bidding"):
                break
            if attempt + 1 < max(1, poll_tries):
                sleep(poll_interval)
        req = {"method": "GET", "path": "/v2/orders:by_client_order_id", "client_order_id": cid, "polled": True}
        if r5.status == 200 and isinstance(r5.body, dict):
            status = str(r5.body.get("status", "")).lower()
            state = classify_order_state(r5.body)
            terminal = _is_terminal({**r5.body, "reconcile_state": state})
            if status == "canceled" and state == "rejected" and terminal:
                cancel_confirmed = True
                verdict, note = "PASS", "canceled; code maps it to 'rejected' (terminal) so a run could close"
            elif status == "canceled":
                verdict, note = "FAIL", (f"canceled with filled_qty={r5.body.get('filled_qty')!r} is classified {state!r} "
                                         f"(terminal={terminal}) -- expected 'rejected' + terminal")
            elif status in ("filled", "partially_filled"):
                verdict, note = "UNEXPECTED", "order filled instead of being canceled -- close the position by hand"
            elif status == "pending_cancel" or status in ("new", "accepted", "pending_new", "accepted_for_bidding"):
                verdict, note = "UNEXPECTED", (f"still {status} after {poll_tries} polls -- confirm in the Alpaca paper "
                                               "dashboard that it ends up canceled")
            else:
                verdict, note = "FAIL", f"unexpected terminal status {status!r} (classified {state!r})"
            report.step("W5_confirm_cancel", "poll by client_order_id until the order is canceled", req,
                        "status canceled -> classify 'rejected' -> terminal", r5, verdict, note, _order_summary(r5.body))
        else:
            report.step("W5_confirm_cancel", "poll by client_order_id until the order is canceled", req, "200", r5,
                        "UNEXPECTED", _classify_transient(r5))
        if not cancel_ok:
            report.data["manual_action_required"] = True
    finally:
        if not cancel_confirmed and created_ids:
            left = []
            for oid in sorted(created_ids):
                rc = api.call("DELETE", f"/v2/orders/{oid}")
                left.append({"id": oid, "cleanup_delete_status": rc.status})
            report.data["cleanup"] = {"attempted": True, "orders": left,
                                      "note": "verify in the Alpaca paper dashboard that no test order is left open"}
            report.data["manual_action_required"] = True


def _after_w1_failure(report: Report) -> None:
    for sid, desc in (("W2_duplicate_submit", "POST the same client_order_id again"),
                      ("W3_lookup_placed", "GET by client_order_id after placing"),
                      ("W4_cancel", "DELETE the test order"), ("W5_confirm_cancel", "confirm cancellation")):
        report.skip(sid, desc, "first submission did not produce a usable order")


# ---------------------------------------------------------------------------------------------------
# entry points

def verify(api: PaperApi, key: str, secret: str, *, write: bool = False, symbol: str = "SPY", limit_price: float = 1.0,
           qty: int = 1, poll_tries: int = 6, poll_interval: float = 1.0,
           sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    report = Report("write" if write else "read_only")
    usable = run_read_only(api, report, key, secret)
    if write:
        if usable:
            run_write(api, report, symbol=symbol, limit_price=limit_price, qty=qty, poll_tries=poll_tries,
                      poll_interval=poll_interval, sleep=sleep)
        else:
            report.skip("W*", "write phase", "read-only preflight did not pass (connectivity/account) -- nothing was submitted")
    return report.finish()


def redact(text: str, secrets_to_hide: list[str]) -> str:
    for value in secrets_to_hide:
        if value and len(value) >= 4:
            text = text.replace(value, "[REDACTED]")
    return text


def credential_hygiene(key: str, secret: str) -> dict[str, Any]:
    """Lengths and formatting hints only -- never the values."""
    odd = re.compile(r"[\s'\"]")
    return {"key_length": len(key), "secret_length": len(secret),
            "key_has_whitespace_or_quote": bool(odd.search(key)), "secret_has_whitespace_or_quote": bool(odd.search(secret))}


def _setup_error(message: str) -> int:
    print(f"SETUP ERROR: {message}", file=sys.stderr)
    return EXIT_SETUP


def main(argv: list[str] | None = None, *, env: dict[str, str] | None = None,
         sleep: Callable[[float], None] = time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true",
                        help="ALSO place, duplicate, look up and cancel one far-from-market test order (paper account)")
    parser.add_argument("--symbol", default="SPY", help="symbol for the test order (default SPY)")
    parser.add_argument("--limit-price", type=float, default=1.00,
                        help="limit price of the 1-share test buy; must be FAR below the market so it cannot fill (default 1.00)")
    parser.add_argument("--output", help="write the JSON report here instead of stdout (not under the repo's data/)")
    parser.add_argument("--poll-tries", type=int, default=6)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    environment = os.environ if env is None else env
    key, secret = environment.get(KEY_ENV, ""), environment.get(SECRET_ENV, "")
    missing = [name for name, value in ((KEY_ENV, key), (SECRET_ENV, secret)) if not value]
    if missing:
        return _setup_error("missing environment variable(s): " + ", ".join(missing) + " (values are never printed)")
    if not re.fullmatch(r"[A-Z][A-Z.]{0,9}", args.symbol):
        return _setup_error("--symbol must be an upper-case ticker")
    if not (0 < args.limit_price * 1 <= MAX_TEST_NOTIONAL):
        return _setup_error(f"--limit-price must be > 0 and qty*price <= {MAX_TEST_NOTIONAL:g} (the order must never fill)")
    if args.output:
        out_path = Path(args.output).resolve()
        if (PROJECT_ROOT / "data").resolve() in (out_path, *out_path.parents):
            return _setup_error("--output must not be under the repository's data/ directory")

    report = verify(PaperApi(key, secret), key, secret, write=args.write, symbol=args.symbol, limit_price=args.limit_price,
                    poll_tries=args.poll_tries, poll_interval=args.poll_interval, sleep=sleep)
    report["credential_hygiene"] = credential_hygiene(key, secret)
    rendered = redact(json.dumps(report, ensure_ascii=False, indent=2, default=str), [key, secret])

    for step in report["steps"]:
        print(f"{step['verdict']:<10} {step['id']:<28} status={step['actual_status']}  {step['note']}", file=sys.stderr)
    print(f"OVERALL {report['overall']}  ({report['verified_scope']})", file=sys.stderr)
    if report.get("manual_action_required"):
        print("MANUAL ACTION: confirm in the Alpaca PAPER dashboard that no test order (client_order_id starting with "
              "'qverify-') is still open.", file=sys.stderr)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(f"report written to {args.output}", file=sys.stderr)
    else:
        print(rendered)
    return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "UNEXPECTED": EXIT_UNEXPECTED}[report["overall"]]


if __name__ == "__main__":
    sys.exit(main())
