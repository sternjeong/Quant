import pytest
from core.paper_execution import RiskLimits, build_order_plan, validate_targets


def test_plan_sells_before_buys_and_has_confirmation_fingerprint():
    plan = build_order_plan({"XLK": .2125, "XLE": .2125}, {"OLD": {"qty": 10, "market_value": 2000, "current_price": 200}}, 10_000)
    assert plan["mode"] == "paper" and len(plan["fingerprint"]) == 16
    assert {o["symbol"] for o in plan["orders"]} == {"OLD", "XLK", "XLE"}


def test_rejects_concentration():
    with pytest.raises(ValueError):
        validate_targets({"SPY": .30}, RiskLimits(max_position_weight=.25))
