"""Champion strategy paper-trading execution primitives.

This module deliberately has no live-broker URL.  It converts a reviewed target
allocation into bounded paper orders and only talks to Alpaca's paper endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

import requests

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


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


def build_order_plan(
    targets: dict[str, float], positions: dict[str, dict[str, float]], equity: float,
    limits: RiskLimits = RiskLimits(),
) -> dict[str, Any]:
    """Return market/day paper orders; never submits them."""
    if equity <= 0:
        raise ValueError("equity must be positive")
    validate_targets(targets, limits)
    orders = []
    for symbol in sorted(set(targets) | set(positions)):
        current = positions.get(symbol, {})
        current_value = float(current.get("market_value", 0.0))
        delta = targets.get(symbol, 0.0) * equity - current_value
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
    fingerprint = hashlib.sha256(json.dumps(orders, sort_keys=True).encode()).hexdigest()[:16]
    return {"mode": "paper", "equity": equity, "orders": orders, "fingerprint": fingerprint}


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

    def submit_plan(self, plan: dict[str, Any], expected_fingerprint: str) -> list[dict[str, Any]]:
        if plan.get("mode") != "paper" or plan.get("fingerprint") != expected_fingerprint:
            raise ValueError("paper plan fingerprint confirmation required")
        account = self.account()
        if account.get("trading_blocked") or account.get("account_blocked"):
            raise RuntimeError("paper account is blocked")
        return [self._request("POST", "/v2/orders", json=order) for order in plan["orders"]]
