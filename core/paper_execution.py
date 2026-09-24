"""Champion strategy paper-trading execution primitives.

This module deliberately has no live-broker URL.  It converts a reviewed target
allocation into bounded paper orders and only talks to Alpaca's paper endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Any

import requests

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
DEFAULT_RUN_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "paper_runs.db"


@dataclass(frozen=True)
class RiskLimits:
    max_position_weight: float = 0.25
    max_gross_weight: float = 1.0
    min_trade_notional: float = 25.0
    max_order_notional: float = 25_000.0


def validate_targets(targets: dict[str, float], limits: RiskLimits = RiskLimits()) -> None:
    if not targets or any(not symbol.isupper() or weight < 0 for symbol, weight in targets.items()):
        raise ValueError("target symbols and weights must be valid long-only values")
    if sum(targets.values()) > limits.max_gross_weight + 1e-9:
        raise ValueError("target gross exposure exceeds limit")
    if any(weight > limits.max_position_weight + 1e-9 for weight in targets.values()):
        raise ValueError("target position exceeds limit")


SLEEVE_CORE = "core"
SLEEVE_SATELLITE = "satellite"


def plan_targets(core: dict[str, Any], satellite: dict[str, Any]) -> dict[str, float]:
    """Merge core + satellite target weights.  Uses the actual allocation (per_ticker_weights),
    never top4 x per_ticker_weight, so an unknown/held recommendation yields no targets.

    Each sleeve is gated by its OWN ``new_orders_allowed`` flag and fails closed: a recommendation
    whose flag is missing or not exactly True (e.g. the satellite dict has no flag yet) contributes
    no targets.  Core hold and satellite hold are independent of each other."""
    result: dict[str, float] = {}
    for source in (core, satellite):
        if source.get("new_orders_allowed") is not True:
            continue
        for ticker, weight in (source.get("per_ticker_weights") or {}).items():
            result[ticker] = result.get(ticker, 0.0) + float(weight)
    return result


def _sleeve_flag_name(plan: dict[str, Any], symbol: str) -> str | None:
    """Plan flag governing ``symbol``: core (default for unlabelled symbols) or satellite.
    An unknown sleeve label has no flag -> never permitted."""
    sleeve = (plan.get("sleeve_of") or {}).get(symbol, SLEEVE_CORE)
    return {SLEEVE_CORE: "new_orders_allowed", SLEEVE_SATELLITE: "satellite_new_orders_allowed"}.get(sleeve)


def _sleeve_permitted(plan: dict[str, Any], symbol: str) -> bool:
    """True only when the sleeve owning ``symbol`` carries an explicit ``True`` flag (fail-closed)."""
    flag = _sleeve_flag_name(plan, symbol)
    return flag is not None and plan.get(flag) is True


def build_order_plan(
    targets: dict[str, float], positions: dict[str, dict[str, float]], equity: float,
    limits: RiskLimits = RiskLimits(), *, new_orders_allowed: bool = True,
    sell_reasons: dict[str, str] | None = None, hold_reason: str = "",
    satellite_new_orders_allowed: bool = True, satellite_hold_reason: str = "",
    sleeve_of: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return market/day paper orders (sells first); never submits them.

    new_orders_allowed=False is a HOLD of the core sleeve: its targets are ignored, no buy is ever
    produced and existing holdings are kept.  ``satellite_new_orders_allowed=False`` is the same
    for the satellite sleeve and is independent of the core flag.  ``sleeve_of`` maps a symbol to
    ``"core"`` or ``"satellite"`` (unlabelled symbols are core).  Only symbols listed in
    ``sell_reasons`` (explicit, reasoned exits) may be sold from a sleeve that is on hold.  The
    flags and labels are stored in the plan so submit_plan enforces them again.
    """
    if equity <= 0:
        raise ValueError("equity must be positive")
    sell_reasons = dict(sell_reasons or {})
    sleeve_of = dict(sleeve_of or {})
    sleeve_open = {SLEEVE_CORE: bool(new_orders_allowed), SLEEVE_SATELLITE: bool(satellite_new_orders_allowed)}

    def _open(symbol: str) -> bool:
        return sleeve_open.get(sleeve_of.get(symbol, SLEEVE_CORE), False)

    orders = []
    open_targets = {s: w for s, w in targets.items() if _open(s)}
    if new_orders_allowed or open_targets:
        validate_targets(open_targets, limits)
    symbols = sorted(s for s in (set(targets) | set(positions)) if _open(s) or (s in sell_reasons and s in positions))
    for symbol in symbols:
        current = positions.get(symbol, {})
        current_value = float(current.get("market_value", 0.0))
        target_weight = targets.get(symbol, 0.0) if _open(symbol) else 0.0
        delta = target_weight * equity - current_value
        if abs(delta) < limits.min_trade_notional:
            continue
        if abs(delta) > limits.max_order_notional:
            raise ValueError(f"{symbol} order exceeds max_order_notional")
        order = {"symbol": symbol, "side": "buy" if delta > 0 else "sell", "type": "market", "time_in_force": "day"}
        if delta > 0:
            order["notional"] = f"{abs(delta):.2f}"
        else:
            price = float(current.get("current_price", 0.0))
            if price <= 0:
                raise ValueError(f"{symbol} sell requires current_price")
            order["qty"] = f"{min(abs(delta) / price, float(current.get('qty', 0.0))):.6f}"
        orders.append(order)
    orders.sort(key=lambda o: (o["side"] != "sell", o["symbol"]))  # sells first (frees cash)
    order_sleeves = {o["symbol"]: sleeve_of.get(o["symbol"], SLEEVE_CORE) for o in orders}
    payload = {"orders": orders, "new_orders_allowed": bool(new_orders_allowed), "sell_reasons": sell_reasons,
               "satellite_new_orders_allowed": bool(satellite_new_orders_allowed), "sleeve_of": order_sleeves}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return {"mode": "paper", "equity": equity, "orders": orders, "fingerprint": fingerprint,
            "new_orders_allowed": bool(new_orders_allowed), "sell_reasons": sell_reasons, "hold_reason": hold_reason,
            "satellite_new_orders_allowed": bool(satellite_new_orders_allowed),
            "satellite_hold_reason": satellite_hold_reason, "sleeve_of": order_sleeves}


def enforce_order_gate(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split plan orders into (allowed, blocked).  Fails closed: an order is allowed only when the
    sleeve that owns its symbol (plan["sleeve_of"], default core) carries an explicit True flag --
    ``new_orders_allowed`` for core, ``satellite_new_orders_allowed`` for satellite.  A sleeve on
    hold (flag False/missing) blocks every buy; a sell from it needs an explicit sell_reason."""
    allowed, blocked = [], []
    reasons = plan.get("sell_reasons") or {}
    for order in plan["orders"]:
        if _sleeve_permitted(plan, order["symbol"]) or (order["side"] == "sell" and order["symbol"] in reasons):
            allowed.append(order)
        else:
            blocked.append(order)
    return allowed, blocked


class RunCloseError(Exception):
    """A manual run close could not be carried out (unknown / already closed / no reason)."""


class RunCloseRefused(RunCloseError):
    """The broker still shows non-terminal (or unverifiable) orders for the run; needs force=True."""
    def __init__(self, message: str, check: dict[str, Any]):
        super().__init__(message)
        self.check = check


_RUN_ID_RE = re.compile(r"^r(\d{5,})$")


def _parse_run_id(run_id: str) -> int:
    match = _RUN_ID_RE.match(str(run_id))
    if not match:
        raise ValueError(f"invalid run id {run_id!r} (expected e.g. r00012)")
    return int(match.group(1))


def inspect_run_orders(run: dict[str, Any], broker: Any) -> dict[str, Any]:
    """Ask the broker about every order of a run's stored plan, by its deterministic client_order_id.

    Per-order ``state``: ``settled`` (terminal), ``not_placed`` (broker has no such order),
    ``unsettled`` (found but still open / partially working / unknown status) or ``unverifiable``
    (lookup failed or no broker connection).  ``blocking`` lists the unsettled + unverifiable ones.
    """
    rows: list[dict[str, Any]] = []
    for index, order in enumerate(run["plan"].get("orders", [])):
        cid = client_order_id(run["account"], run["strategy_version"], run["run_id"], index, order["symbol"])
        row: dict[str, Any] = {"client_order_id": cid, "symbol": order["symbol"], "side": order["side"]}
        if broker is None:
            row.update(state="unverifiable", detail="no broker connection (API credentials not available)")
        else:
            try:
                found = broker.order_by_client_id(cid)
            except (requests.RequestException, ValueError) as exc:
                row.update(state="unverifiable", detail=f"lookup failed: {type(exc).__name__}")
            else:
                if found is None:
                    row.update(state="not_placed", detail="broker has no order with this client_order_id")
                else:
                    reconcile = classify_order_state(found)
                    terminal = _is_terminal({**found, "reconcile_state": reconcile})
                    row.update(state="settled" if terminal else "unsettled", broker_status=str(found.get("status", "")),
                               reconcile_state=reconcile, filled_qty=str(found.get("filled_qty", "")))
        rows.append(row)
    blocking = [r for r in rows if r["state"] in ("unsettled", "unverifiable")]
    return {"orders": rows, "blocking": blocking}


class RunStore:
    """Persistent execution-run identifiers (SQLite file, stdlib only).

    A run is one scheduled execution round for (account, strategy version).  It stays 'open'
    -- across restarts and past midnight -- until close_run() is called, and it remembers the
    plan it started with so retries resume the same orders.  The next round gets a new run id.

    Operations: list_runs() to inspect, manual_close() to end a stuck run with a recorded reason
    (refused while the broker still shows unsettled orders unless force=True).  Every close and
    every refused close is written to the ``paper_run_audit`` table (list via audit_log()).
    """
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = str(path or os.getenv("QUANT_PAPER_RUN_DB") or DEFAULT_RUN_DB_PATH)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS paper_runs (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                      "account TEXT, strategy_version TEXT, status TEXT, plan TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            # separate table (not new columns) so databases created by earlier versions keep working
            c.execute("CREATE TABLE IF NOT EXISTS paper_run_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, run_seq INTEGER, "
                      "action TEXT, reason TEXT, actor TEXT, forced INTEGER DEFAULT 0, detail TEXT, "
                      "created_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def _audit(c: sqlite3.Connection, seq: int, action: str, reason: str, actor: str, forced: bool,
               detail: dict[str, Any] | None = None) -> None:
        c.execute("INSERT INTO paper_run_audit (run_seq, action, reason, actor, forced, detail) VALUES (?,?,?,?,?,?)",
                  (seq, action, reason, actor, int(forced), json.dumps(detail or {}, ensure_ascii=False, default=str)))

    def get_or_open_run(self, account: str, strategy_version: str, plan: dict[str, Any]) -> dict[str, Any]:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT seq, plan FROM paper_runs WHERE account=? AND strategy_version=? AND status='open' "
                            "ORDER BY seq DESC LIMIT 1", (account, strategy_version)).fetchone()
            if row:
                return {"run_id": f"r{row[0]:05d}", "plan": json.loads(row[1]), "resumed": True}
            cur = c.execute("INSERT INTO paper_runs (account, strategy_version, status, plan) VALUES (?,?,'open',?)",
                            (account, strategy_version, json.dumps(plan)))
            return {"run_id": f"r{cur.lastrowid:05d}", "plan": plan, "resumed": False}

    def close_run(self, run_id: str, *, reason: str = "round settled", actor: str = "system") -> bool:
        """Close an open run (used by submit_plan when every order is terminal).  Returns whether
        this call closed it; the close is audited.  Operators use manual_close() instead."""
        seq = _parse_run_id(run_id)
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            changed = c.execute("UPDATE paper_runs SET status='closed' WHERE seq=? AND status='open'", (seq,)).rowcount
            if changed:
                self._audit(c, seq, "auto_close", reason, actor, False)
            return bool(changed)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        seq = _parse_run_id(run_id)
        with self._conn() as c:
            row = c.execute("SELECT seq, account, strategy_version, status, plan, created_at FROM paper_runs WHERE seq=?",
                            (seq,)).fetchone()
        if row is None:
            return None
        return {"run_id": f"r{row[0]:05d}", "seq": row[0], "account": row[1], "strategy_version": row[2],
                "status": row[3], "plan": json.loads(row[4] or "{}"), "created_at": row[5]}

    def list_runs(self, status: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        """Runs newest first.  ``status`` filters to 'open' / 'closed' (None = all).  Each row has the
        order count, plan fingerprint and, for closed runs, when/why/by whom it was closed (from the audit log)."""
        if status not in (None, "open", "closed"):
            raise ValueError("status must be 'open', 'closed' or None")
        query = "SELECT seq, account, strategy_version, status, plan, created_at FROM paper_runs"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY seq DESC"
        if limit:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._conn() as c:
            rows = c.execute(query, params).fetchall()
            closes = {r[0]: r for r in c.execute(
                "SELECT run_seq, action, reason, actor, forced, created_at FROM paper_run_audit "
                "WHERE action IN ('manual_close','auto_close') ORDER BY id")}
        out = []
        for seq, account, version, st, plan_json, created in rows:
            plan = json.loads(plan_json or "{}")
            row = {"run_id": f"r{seq:05d}", "account": account, "strategy_version": version, "status": st,
                   "created_at": created, "n_orders": len(plan.get("orders", [])), "fingerprint": plan.get("fingerprint"),
                   "closed_at": None, "close_action": None, "close_reason": None, "closed_by": None, "forced": False}
            if st == "closed" and seq in closes:
                _, action, reason, actor, forced, closed_at = closes[seq]
                row.update(closed_at=closed_at, close_action=action, close_reason=reason, closed_by=actor, forced=bool(forced))
            out.append(row)
        return out

    def audit_log(self, run_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id, run_seq, action, reason, actor, forced, detail, created_at FROM paper_run_audit"
        params: list[Any] = []
        if run_id is not None:
            query += " WHERE run_seq=?"
            params.append(_parse_run_id(run_id))
        with self._conn() as c:
            rows = c.execute(query + " ORDER BY id", params).fetchall()
        return [{"id": r[0], "run_id": f"r{r[1]:05d}", "action": r[2], "reason": r[3], "actor": r[4],
                 "forced": bool(r[5]), "detail": json.loads(r[6] or "{}"), "created_at": r[7]} for r in rows]

    def manual_close(self, run_id: str, reason: str, *, broker: Any = None, force: bool = False,
                     actor: str = "cli") -> dict[str, Any]:
        """Operator close of a stuck open run, with a mandatory reason and an audit record.

        The broker is asked about every order of the run's stored plan.  If any order is still
        unsettled (open / partly working / unknown status) or cannot be verified (lookup failed, or
        ``broker`` is None) the close is REFUSED (RunCloseRefused, also audited) unless force=True --
        closing while an order is still working lets the next round trade on top of it.  With
        force=True the close goes through and the audit row records ``forced`` plus the warnings.
        After a close the next submit_plan opens a NEW run id, so all its client_order_ids change.
        """
        reason = (reason or "").strip()
        if not reason:
            raise RunCloseError("a close reason is required")
        run = self.get_run(run_id)
        if run is None:
            raise RunCloseError(f"unknown run {run_id}")
        if run["status"] != "open":
            raise RunCloseError(f"{run['run_id']} is already {run['status']}")
        check = inspect_run_orders(run, broker)
        blocking = check["blocking"]
        summary = {"blocking": [{k: r.get(k) for k in ("client_order_id", "symbol", "state", "broker_status", "detail")}
                                for r in blocking], "n_orders": len(check["orders"])}
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            if blocking and not force:
                self._audit(c, run["seq"], "close_refused", reason, actor, False, summary)
                refused = True
            else:
                changed = c.execute("UPDATE paper_runs SET status='closed' WHERE seq=? AND status='open'", (run["seq"],)).rowcount
                if not changed:
                    raise RunCloseError(f"{run['run_id']} was closed by someone else")
                self._audit(c, run["seq"], "manual_close", reason, actor, bool(blocking), summary)
                refused = False
        if refused:
            raise RunCloseRefused(
                f"{run['run_id']} has {len(blocking)} order(s) not confirmed settled at the broker; "
                "resolve them or pass force=True (--force) to close anyway", check)
        return {"run_id": run["run_id"], "status": "closed", "forced": bool(blocking), "warnings": summary["blocking"],
                "reason": reason, "actor": actor}


class AlpacaPaperBroker:
    """Minimal authenticated paper-only client; credentials are read only at runtime."""
    def __init__(self, key: str, secret: str):
        if not key or not secret:
            raise ValueError("ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET are required")
        self.headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    @classmethod
    def from_env(cls) -> "AlpacaPaperBroker":
        return cls(os.getenv("ALPACA_PAPER_API_KEY", ""), os.getenv("ALPACA_PAPER_API_SECRET", ""))

    def _request(self, method: str, path: str, **kwargs):
        response = requests.request(method, PAPER_BASE_URL + path, headers=self.headers, timeout=20, **kwargs)
        response.raise_for_status()
        return response.json()

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/v2/account")

    def positions(self) -> dict[str, dict[str, float]]:
        rows = self._request("GET", "/v2/positions")
        return {r["symbol"]: {"qty": float(r["qty"]), "market_value": float(r["market_value"]), "current_price": float(r["current_price"])} for r in rows}

    def order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        """Look up an order by client order ID; None when the broker has no such order (404)."""
        try:
            return self._request("GET", "/v2/orders:by_client_order_id", params={"client_order_id": client_order_id})
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise

    def submit_plan(self, plan: dict[str, Any], expected_fingerprint: str, run_store: RunStore | None = None,
                    strategy_version: str = "unversioned") -> list[dict[str, Any]]:
        """Submit idempotently.  This is the single place that POSTs orders, so the hold gate is
        enforced here (not only in recommendation/plan building).

        Each order carries a client_order_id built from account / strategy version / persisted run
        id / sequence / symbol.  The run id is created once per execution round and stored, so a
        retry (restart, after midnight) reuses the same ids; the next round gets a new run id.
        Before/after an ambiguous failure the broker is queried by client_order_id, so a retry
        never creates a second order.  Each result has ``reconcile_state``.  If an outcome cannot
        be determined the run stays open (state ``unresolved``) and later retries reconcile it.
        """
        if plan.get("mode") != "paper" or plan.get("fingerprint") != expected_fingerprint:
            raise ValueError("paper plan fingerprint confirmation required")
        account = self.account()
        if account.get("trading_blocked") or account.get("account_blocked"):
            raise RuntimeError("paper account is blocked")
        store = run_store or RunStore()
        account_id = str(account.get("id") or account.get("account_number") or "paper")
        run = store.get_or_open_run(account_id, strategy_version, plan)
        if run["resumed"] and self._run_finished(account_id, strategy_version, run):
            store.close_run(run["run_id"], reason="previous round fully settled; new round")
            run = store.get_or_open_run(account_id, strategy_version, plan)
        # Resume the stored plan (positions change after partial fills; ids must stay aligned).
        # The current plan's gate still applies: a hold now blocks buys of a stored plan too.
        effective = {
            **run["plan"],
            "new_orders_allowed": plan.get("new_orders_allowed") is True and run["plan"].get("new_orders_allowed") is True,
            "satellite_new_orders_allowed": (plan.get("satellite_new_orders_allowed") is True
                                             and run["plan"].get("satellite_new_orders_allowed") is True),
            "sell_reasons": {**(run["plan"].get("sell_reasons") or {}), **(plan.get("sell_reasons") or {})},
        }
        # index in the ORIGINAL stored order list, so ids do not shift when orders are gated out
        indexed = list(enumerate(run["plan"]["orders"]))
        allowed_ids = {id(o) for o in enforce_order_gate(effective)[0]}
        results: list[dict[str, Any]] = []
        for index, order in indexed:
            if id(order) not in allowed_ids:
                results.append({"symbol": order["symbol"], "side": order["side"], "reconcile_state": "blocked_hold",
                                "hold_sleeve": (effective.get("sleeve_of") or {}).get(order["symbol"], SLEEVE_CORE)})
                continue
            cid = client_order_id(account_id, strategy_version, run["run_id"], index, order["symbol"])
            body = {**order, "client_order_id": cid}
            try:
                existing = self.order_by_client_id(cid)
            except (requests.RequestException, ValueError):
                results.append({"client_order_id": cid, "symbol": order["symbol"], "reconcile_state": "unresolved"})
                break
            if existing is not None:
                results.append({**existing, "reconcile_state": classify_order_state(existing), "resubmitted": False})
                continue
            try:
                placed = self._request("POST", "/v2/orders", json=body)
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else 0
                if 400 <= code < 500 and code != 422:
                    results.append({"client_order_id": cid, "symbol": order["symbol"], "reconcile_state": "rejected",
                                    "error_status": code})
                    continue
                placed = self._reconcile_after_error(cid)
            except (requests.RequestException, ValueError):  # response lost / timeout / bad body
                placed = self._reconcile_after_error(cid)
            if placed is None:
                results.append({"client_order_id": cid, "symbol": order["symbol"], "reconcile_state": "unresolved"})
                break
            state = "not_placed" if placed.get("not_found_after_error") else classify_order_state(placed)
            results.append({**placed, "reconcile_state": state})
        pending = len(results) < len(indexed) or not all(
            r["reconcile_state"] == "blocked_hold" or _is_terminal(r) for r in results)
        if not pending:
            store.close_run(run["run_id"], reason="round settled (all orders terminal)")
        for r in results:
            r["run_id"] = run["run_id"]
        return results

    def _run_finished(self, account_id: str, strategy_version: str, run: dict[str, Any]) -> bool:
        """True when every order of the stored plan is on record at the broker in a terminal state."""
        for index, order in enumerate(run["plan"]["orders"]):
            if order["side"] == "buy" and not _sleeve_permitted(run["plan"], order["symbol"]):
                continue
            try:
                found = self.order_by_client_id(client_order_id(account_id, strategy_version, run["run_id"], index, order["symbol"]))
            except (requests.RequestException, ValueError):
                return False
            if found is None or not _is_terminal({**found, "reconcile_state": classify_order_state(found)}):
                return False
        return True

    def _reconcile_after_error(self, cid: str) -> dict[str, Any] | None:
        """After an ambiguous POST failure: found -> it went through; 404 -> rejected marker; error -> None."""
        try:
            found = self.order_by_client_id(cid)
        except (requests.RequestException, ValueError):
            return None
        return found if found is not None else {"client_order_id": cid, "not_found_after_error": True}


def _is_terminal(result: dict[str, Any]) -> bool:
    """filled / rejected / partial-but-no-longer-working.  Open or unknown orders keep the run open."""
    state = result.get("reconcile_state")
    if state in {"filled", "rejected"}:
        return True
    return state == "partial" and str(result.get("status", "")).lower() in {"canceled", "expired", "done_for_day"}


def _short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def client_order_id(account_id: str, strategy_version: str, run_id: str, index: int, symbol: str) -> str:
    """Deterministic per (account, strategy version, run, sequence, symbol); no wall-clock date.

    Same run retried -> same ids; a new run -> different ids (Alpaca max 128 chars)."""
    safe = re.sub(r"[^A-Za-z0-9.-]", "", symbol)
    return f"q-{_short(account_id)}-{_short(strategy_version)}-{run_id}-{index:02d}-{safe}"[:128]


def classify_order_state(order: dict[str, Any]) -> str:
    """filled / partial / open / rejected (rejected, canceled, expired) / unknown."""
    status = str(order.get("status", "")).lower()
    if status == "filled":
        return "filled"
    if status == "partially_filled" or (status in {"canceled", "expired", "done_for_day"} and float(order.get("filled_qty") or 0) > 0):
        return "partial"
    if status in {"new", "accepted", "pending_new", "accepted_for_bidding", "pending_cancel", "pending_replace", "replaced", "held"}:
        return "open"
    if status in {"rejected", "canceled", "expired", "suspended", "stopped"}:
        return "rejected"
    return "unknown"
