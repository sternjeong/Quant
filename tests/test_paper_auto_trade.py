"""core/paper_auto_trade.py — 모든 조건이 fail-closed 인지, 통과 시 1번만 제출하는지 검증(네트워크 없음)."""

from datetime import datetime, timezone

import pytest

from core import paper_auto_trade as pat

NOW = datetime(2026, 10, 6, 21, 10, tzinfo=timezone.utc)  # = 2026-10-06 17:10 ET (화, 장 마감 뒤)
CORE = {"top4": ["SPY"], "per_ticker_weights": {"SPY": 0.2}, "new_orders_allowed": True, "allocation_reason": ""}
SAT = {"selected": [], "per_ticker_weights": {}, "new_orders_allowed": True}


class FakeBroker:
    def __init__(self, blocked=False):
        self.blocked, self.submitted = blocked, []

    def account(self):
        return {"equity": "10000", "trading_blocked": self.blocked}

    def positions(self):
        return {}

    def submit_plan(self, plan, fp, run_store=None, strategy_version=""):
        assert fp == plan["fingerprint"]
        self.submitted.append(plan)
        return [{"symbol": o["symbol"], "reconcile_state": "accepted", "run_id": "r00001"} for o in plan["orders"]]


def _kw(tmp_path, **over):
    kw = dict(now=NOW, broker=FakeBroker(), core=CORE, satellite=SAT, run_store=object(),
              state_path=tmp_path / "s.json", credentials_fn=lambda: True, recent_pass_fn=lambda: {"overall": "PASS"},
              trading_day_fn=lambda d: True, tradability_fn=lambda syms: {s: {"verdict": "tradable"} for s in syms})
    kw.update(over)
    return kw


def test_submits_once_per_et_day(tmp_path):
    kw = _kw(tmp_path)
    r = pat.run_auto_round(**kw)
    assert r["status"] == "submitted" and r["et_day"] == "2026-10-06" and r["n_orders"] == 1
    assert r["order_value"] == pytest.approx(2000.0)
    assert pat.run_auto_round(**kw)["reason"] == "already submitted today"
    assert len(kw["broker"].submitted) == 1
    assert "주문 1건 제출" in pat.format_summary(r)


@pytest.mark.parametrize("over, reason", [
    ({"credentials_fn": lambda: False}, "no_credentials"),
    ({"recent_pass_fn": lambda: None}, "no recent Alpaca verification PASS (P0)"),
    ({"trading_day_fn": lambda d: None}, "calendar lookup failed (unknown trading day)"),
    ({"trading_day_fn": lambda d: False}, "market closed today"),
    ({"broker": FakeBroker(blocked=True)}, "paper account is blocked"),
    ({"tradability_fn": lambda s: {"SPY": {"verdict": "lookup_failed"}}}, "buy symbols not confirmed tradable"),
])
def test_every_precondition_fails_closed(tmp_path, over, reason):
    kw = _kw(tmp_path, **over)
    r = pat.run_auto_round(**kw)
    assert r["status"] == "skipped" and r["reason"] == reason
    assert not kw["broker"].submitted


def test_order_value_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(pat, "MAX_ORDER_VALUE_FRACTION", 0.1)
    kw = _kw(tmp_path)
    assert pat.run_auto_round(**kw)["reason"] == "order value exceeds cap"
    assert not kw["broker"].submitted


def test_hold_sleeve_produces_no_orders(tmp_path):
    kw = _kw(tmp_path, core={**CORE, "new_orders_allowed": False})
    assert pat.run_auto_round(**kw)["status"] == "no_orders"
    assert not kw["broker"].submitted


def test_disabled_by_default():
    from core.process_registry import PROCESS_REGISTRY

    assert PROCESS_REGISTRY["paper_auto_trade"]["default_enabled"] is False
