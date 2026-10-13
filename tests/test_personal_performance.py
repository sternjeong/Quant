"""현재 보유분 참고선은 보유 시작일·추가 매입·가격 결측을 정직하게 처리한다."""

import pandas as pd
import pytest

from core.personal_performance import current_holdings_curve, normalized_return_curves


def test_current_lots_start_after_october_first_and_new_money_is_not_profit():
    days = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-06", "2026-10-07", "2026-10-08"])
    holdings = [
        {"ticker": "AAA", "quantity": 1, "purchase_price": 100, "purchase_date": "2026-10-06"},
        {"ticker": "BBB", "quantity": 1, "purchase_price": 50, "purchase_date": "2026-10-07"},
    ]
    prices = {
        "AAA": pd.DataFrame({"Close": [100, 105, 110]}, index=days[-3:]),
        "BBB": pd.DataFrame({"Close": [50, 55]}, index=days[-2:]),
    }
    result = current_holdings_curve(holdings, days, price_fn=lambda tickers, **kwargs: prices)
    assert result["first_date"] == "2026-10-06"
    assert list(result["curve"].index) == list(days[-3:])
    assert result["curve"].iloc[0] == pytest.approx(1)
    assert result["curve"].iloc[1] == pytest.approx(1.05)  # 새로 투입한 $50는 수익이 아니다.
    assert result["curve"].iloc[2] == pytest.approx(1.05 * 165 / 155)
    assert result["cost_usd"] == 150
    assert result["unrealized_pnl_usd"] == 15


def test_missing_held_price_cannot_be_treated_as_zero_return():
    days = pd.to_datetime(["2026-10-06", "2026-10-07"])
    holdings = [{"ticker": "AAA", "quantity": 1, "purchase_price": 100, "purchase_date": "2026-10-06"}]
    prices = {"AAA": pd.DataFrame({"Close": [100, float("nan")]}, index=days)}
    with pytest.raises(ValueError, match="AAA 2026-10-07 종가"):
        current_holdings_curve(holdings, days, price_fn=lambda tickers, **kwargs: prices)


def test_empty_holdings_return_explanation_without_fetch():
    result = current_holdings_curve([], pd.to_datetime(["2026-10-01"]),
                                    price_fn=lambda *a, **kw: pytest.fail("no fetch"))
    assert not result["available"]


def test_normalized_chart_keeps_october_one_and_can_align_all_three_to_first_purchase():
    dates = pd.to_datetime(["2026-10-01", "2026-10-06", "2026-10-07"])
    champion = pd.Series([100, 110, 121], index=dates)
    spy = pd.Series([100, 90, 99], index=dates)
    mine = pd.Series([1, 1.05], index=dates[1:])
    whole = normalized_return_curves(champion, spy, mine)
    assert whole["strategy"].tolist() == pytest.approx([0, 10, 21])
    assert whole["spy"].tolist() == pytest.approx([0, -10, -1])
    assert whole["personal"].tolist() == pytest.approx([0, 5])
    aligned = normalized_return_curves(champion, spy, mine, same_period=True)
    assert aligned["strategy"].tolist() == pytest.approx([0, 10])
    assert aligned["spy"].tolist() == pytest.approx([0, 10])
    assert aligned["personal"].tolist() == pytest.approx([0, 5])
