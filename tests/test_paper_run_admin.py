"""Run list / manual close (RunStore) and scripts/paper_run_admin.py.  Fake broker only, no network.

Expected values come from the operating requirement, not from the implementation:
- a close needs a reason and is audited (refusals too);
- if the broker shows an order that is not terminal (or cannot be checked) the close is refused
  unless forced -- closing under a live order would let the next round trade on top of it;
- after a close the next submission gets a NEW run id and therefore new client order ids.
"""
import importlib.util
import json
import pathlib
import socket
import sqlite3

import pytest
import requests

from core.paper_execution import (
    AlpacaPaperBroker, RunCloseError, RunCloseRefused, RunStore, build_order_plan, client_order_id,
)
from tests.test_paper_execution import FakeServer

_spec = importlib.util.spec_from_file_location(
    "paper_run_admin", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "paper_run_admin.py")
admin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(admin)

ACCOUNT = "acct-secret-123"
VERSION = "ver-1"


class Broker(AlpacaPaperBroker):
    def __init__(self, server):
        super().__init__("test-key-DO-NOT-PRINT", "test-secret-DO-NOT-PRINT")
        self._request = server.request

    def account(self):
        return {"id": ACCOUNT, "equity": "10000"}


@pytest.fixture(autouse=True)
def _no_network_no_env_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)

    def _blocked(*a, **k):
        raise AssertionError("network access attempted in a unit test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "runs.db"


def _plan():
    return build_order_plan({"XLK": .2, "XLE": .2}, {}, 10_000)


def _submit(server, store, plan=None):
    plan = plan or _plan()
    return Broker(server).submit_plan(plan, plan["fingerprint"], run_store=store, strategy_version=VERSION)


def _stuck_open_run(server, store):
    """Round whose orders are accepted but not settled -> run stays open."""
    res = _submit(server, store)
    assert {r["reconcile_state"] for r in res} == {"open"}
    return res[0]["run_id"]


def _settle_all(server, status="filled"):
    for o in server.orders.values():
        o.update(status=status, filled_qty="1" if status == "filled" else "0")


# ---- list -----------------------------------------------------------------------------------

def test_list_runs_shows_open_then_closed_with_reason_newest_first(db):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    rows = store.list_runs()
    assert [(r["run_id"], r["status"], r["n_orders"]) for r in rows] == [(run1, "open", 2)]
    assert rows[0]["fingerprint"] == _plan()["fingerprint"] and rows[0]["closed_at"] is None

    _settle_all(server)
    store.manual_close(run1, "settled by hand", broker=Broker(server), actor="tester")
    run2 = _submit(server, store)[0]["run_id"]                      # a second round, still open
    rows = store.list_runs()
    assert [r["run_id"] for r in rows] == [run2, run1]              # newest first
    closed = [r for r in store.list_runs(status="closed")]
    assert [r["run_id"] for r in closed] == [run1]
    assert closed[0]["close_reason"] == "settled by hand" and closed[0]["closed_by"] == "tester"
    assert closed[0]["close_action"] == "manual_close" and closed[0]["forced"] is False
    assert [r["run_id"] for r in store.list_runs(status="open")] == [run2]
    assert len(store.list_runs(limit=1)) == 1
    with pytest.raises(ValueError):
        store.list_runs(status="bogus")


def test_automatic_close_is_audited_and_listed(db):
    server, store = FakeServer(), RunStore(db)
    _stuck_open_run(server, store)
    _settle_all(server)
    _submit(server, store)                       # round finished -> closed by submit_plan, new round opened
    first = store.list_runs(status="closed")[0]
    assert first["close_action"] == "auto_close" and first["closed_by"] == "system" and first["close_reason"]


def test_old_database_without_audit_table_still_works(db):
    """A paper_runs.db written by an earlier version has no audit table: opening must not break it."""
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE paper_runs (seq INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT, strategy_version TEXT, "
                "status TEXT, plan TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    con.execute("INSERT INTO paper_runs (account, strategy_version, status, plan) VALUES (?,?,'open',?)",
                (ACCOUNT, VERSION, json.dumps(_plan())))
    con.execute("INSERT INTO paper_runs (account, strategy_version, status, plan) VALUES (?,?,'closed',?)",
                (ACCOUNT, VERSION, json.dumps(_plan())))
    con.commit(); con.close()
    store = RunStore(db)
    rows = {r["run_id"]: r for r in store.list_runs()}
    assert rows["r00001"]["status"] == "open" and rows["r00002"]["status"] == "closed"
    assert rows["r00002"]["close_action"] is None                    # legacy close: no audit row
    store.manual_close("r00001", "legacy cleanup", broker=Broker(FakeServer()))   # nothing placed -> no force needed
    assert store.get_run("r00001")["status"] == "closed"


# ---- manual close: refusals ------------------------------------------------------------------

def test_close_refused_while_broker_order_is_unsettled_and_run_stays_open(db):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    with pytest.raises(RunCloseRefused) as exc:
        store.manual_close(run1, "stuck", broker=Broker(server))
    assert {r["state"] for r in exc.value.check["blocking"]} == {"unsettled"}
    assert store.get_run(run1)["status"] == "open"
    log = store.audit_log(run1)
    assert [e["action"] for e in log] == ["close_refused"] and log[0]["reason"] == "stuck"
    assert log[0]["detail"]["blocking"]
    # the run was left untouched: the next submission still resumes it (same ids, no new POSTs)
    posts = len(server.posts)
    assert {r["run_id"] for r in _submit(server, store)} == {run1} and len(server.posts) == posts


def test_close_refused_for_partially_working_order(db):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    for o in server.orders.values():
        o.update(status="partially_filled", filled_qty="2")
    with pytest.raises(RunCloseRefused):
        store.manual_close(run1, "stuck", broker=Broker(server))


def test_close_refused_when_broker_lookup_fails(db):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    server.lookup_fails = True
    with pytest.raises(RunCloseRefused) as exc:
        store.manual_close(run1, "broker down", broker=Broker(server))
    assert {r["state"] for r in exc.value.check["blocking"]} == {"unverifiable"}
    assert store.get_run(run1)["status"] == "open"


def test_close_refused_without_broker_connection(db):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    with pytest.raises(RunCloseRefused) as exc:
        store.manual_close(run1, "no creds", broker=None)
    assert "no broker connection" in exc.value.check["blocking"][0]["detail"]
    assert store.get_run(run1)["status"] == "open"


def test_close_input_validation(db):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    for bad_reason in ("", "   ", None):
        with pytest.raises(RunCloseError, match="reason"):
            store.manual_close(run1, bad_reason, broker=Broker(server), force=True)
    assert store.get_run(run1)["status"] == "open" and store.audit_log(run1) == []
    with pytest.raises(RunCloseError, match="unknown run"):
        store.manual_close("r09999", "x", broker=Broker(server), force=True)
    with pytest.raises(ValueError):
        store.manual_close("12", "x", broker=Broker(server))
    _settle_all(server)
    store.manual_close(run1, "done", broker=Broker(server))
    with pytest.raises(RunCloseError, match="already closed"):
        store.manual_close(run1, "again", broker=Broker(server), force=True)


# ---- manual close: success paths and the next round -------------------------------------------

def test_force_close_records_warnings_and_next_round_gets_new_run_and_ids(db):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    ids_round1 = set(server.orders)
    result = store.manual_close(run1, "operator abandoned round", broker=Broker(server), force=True, actor="ops")
    assert result["forced"] is True and len(result["warnings"]) == 2
    entry = store.audit_log(run1)[-1]
    assert entry["action"] == "manual_close" and entry["forced"] is True and entry["actor"] == "ops"
    assert entry["reason"] == "operator abandoned round" and len(entry["detail"]["blocking"]) == 2

    res2 = _submit(server, store)
    run2 = res2[0]["run_id"]
    assert run2 != run1 and store.get_run(run2)["status"] == "open"
    ids_round2 = {r["client_order_id"] for r in res2}
    assert ids_round2 and not ids_round2 & ids_round1             # new run -> new client order ids
    assert len(server.orders) == 4                                # round 2 placed its own orders


def test_close_without_force_when_everything_settled_then_new_run(db):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    _settle_all(server, "filled")
    result = store.manual_close(run1, "verified filled", broker=Broker(server))
    assert result["forced"] is False and result["warnings"] == []
    assert store.audit_log(run1)[-1]["forced"] is False
    res2 = _submit(server, store)
    assert res2[0]["run_id"] != run1


def test_close_allowed_when_orders_never_reached_broker(db):
    """Run opened but nothing was placed (404 for every id): nothing to wait for."""
    server, store = FakeServer(), RunStore(db)
    run = store.get_or_open_run(ACCOUNT, VERSION, _plan())
    result = store.manual_close(run["run_id"], "process died before POST", broker=Broker(server))
    assert result["forced"] is False
    next_run = store.get_or_open_run(ACCOUNT, VERSION, _plan())
    assert next_run["resumed"] is False and next_run["run_id"] != run["run_id"]


def test_client_ids_of_next_run_differ_from_closed_run(db):
    server, store = FakeServer(), RunStore(db)
    run1 = store.get_or_open_run(ACCOUNT, VERSION, _plan())["run_id"]
    store.manual_close(run1, "r", broker=Broker(server))
    run2 = store.get_or_open_run(ACCOUNT, VERSION, _plan())["run_id"]
    assert run2 != run1
    assert client_order_id(ACCOUNT, VERSION, run1, 0, "XLE") != client_order_id(ACCOUNT, VERSION, run2, 0, "XLE")


# ---- CLI ----------------------------------------------------------------------------------------

def test_cli_list_json_hides_raw_account_id(db, capsys):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    assert admin.main(["--db", str(db), "list", "--status", "open", "--json"]) == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert [r["run_id"] for r in rows] == [run1] and "account" not in rows[0] and len(rows[0]["account_hash"]) == 8
    assert ACCOUNT not in out
    assert admin.main(["--db", str(db), "list"]) == 0
    text = capsys.readouterr().out
    assert run1 in text and ACCOUNT not in text


def test_cli_close_refuses_then_force_closes_and_never_prints_keys(db, capsys):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    base = ["--db", str(db), "close", "--run-id", run1, "--reason", "manual test"]
    assert admin.main(base, broker=Broker(server)) == admin.EXIT_REFUSED
    captured = capsys.readouterr()
    assert "REFUSED" in captured.err and store.get_run(run1)["status"] == "open"
    assert admin.main(base + ["--force", "--actor", "ops"], broker=Broker(server)) == admin.EXIT_OK
    captured = capsys.readouterr()
    assert "closed " + run1 in captured.out and "WARNING" in captured.out
    assert store.get_run(run1)["status"] == "closed"
    for text in (captured.out, captured.err):
        assert "DO-NOT-PRINT" not in text
    assert admin.main(["--db", str(db), "audit", "--run-id", run1]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert [e["action"] for e in audit] == ["close_refused", "manual_close"]


def test_cli_without_credentials_is_unverifiable_and_needs_force(db, capsys):
    server, store = FakeServer(), RunStore(db)
    run1 = _stuck_open_run(server, store)
    base = ["--db", str(db), "close", "--run-id", run1, "--reason", "no keys here"]
    assert admin.main(base) == admin.EXIT_REFUSED                    # env has no keys (autouse fixture)
    assert "credentials" in capsys.readouterr().err and store.get_run(run1)["status"] == "open"
    assert admin.main(base + ["--force"]) == admin.EXIT_OK
    assert store.get_run(run1)["status"] == "closed"


def test_cli_errors_use_exit_code_1(db, capsys):
    store = RunStore(db)
    assert admin.main(["--db", str(db), "close", "--run-id", "r00042", "--reason", "x"], broker=Broker(FakeServer())) == admin.EXIT_ERROR
    assert admin.main(["--db", str(db), "close", "--run-id", "bad", "--reason", "x"], broker=Broker(FakeServer())) == admin.EXIT_ERROR
    assert admin.main(["--db", str(db), "close", "--run-id", "r00001", "--reason", "  "], broker=Broker(FakeServer())) == admin.EXIT_ERROR
    with pytest.raises(SystemExit):                                  # --reason is mandatory at the CLI level
        admin.main(["--db", str(db), "close", "--run-id", "r00001"])
    assert store.list_runs() == []
