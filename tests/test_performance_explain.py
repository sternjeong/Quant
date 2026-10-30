"""상승·하락 기여와 상관을 구분하고 가격 결측을 보간하지 않는다."""

import pandas as pd
import pytest

from core import champion_performance as cp
from core import performance_explain as explain


def test_down_days_identify_losses_and_offsets_without_confusing_deposits():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"])
    c = {"nav": pd.Series([100, 210, 200, 205], index=dates),
         "flows": pd.Series([0, 100, 0, 0], index=dates),
         "pnl": pd.DataFrame({"AAA": [0, 15, -12, 8], "BBB": [0, -5, 2, -3]}, index=dates),
         "active": pd.DataFrame(True, index=dates, columns=["AAA", "BBB"])}
    down = explain.movement_summary(c, "하락일")
    assert down["n_days"] == 1
    assert down["net_move_usd"] == -10
    assert [(r["ticker"], r["pnl_usd"]) for r in down["rows"]] == [("AAA", -12), ("BBB", 2)]
    assert down["rows"][0]["impact_share_pct"] == pytest.approx(12 / 14 * 100)
    assert down["rows"][0]["correlation_r"] is None  # 3일은 과도한 상관 표시 금지
    up = explain.movement_summary(c, "상승일")
    assert up["n_days"] == 2 and up["net_move_usd"] == 15
    assert up["rows"][0]["pnl_usd"] == 23


def test_correlation_is_available_only_with_five_nonconstant_held_days():
    dates = pd.bdate_range("2026-10-01", periods=7)
    contribution = pd.Series([0, 1, -2, 3, -1, 2, -3], index=dates)
    nav = pd.Series([100, 101, 99, 102, 101, 103, 100], index=dates)
    c = {"nav": nav, "flows": pd.Series(0.0, index=dates),
         "pnl": pd.DataFrame({"AAA": contribution}, index=dates),
         "active": pd.DataFrame(True, index=dates, columns=["AAA"])}
    ticker_returns = pd.DataFrame({"AAA": nav.pct_change(fill_method=None)}, index=dates)
    row = explain.movement_summary(c, "전체", ticker_returns=ticker_returns)["rows"][0]
    assert row["n_observed"] == 6
    assert row["correlation_r"] == pytest.approx(1)


def test_champion_daily_components_reconcile_to_curve():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05"])
    result = {"curves": {"strategy": cp._series_to_json(pd.Series([1, 1.1, 1.05], index=dates))},
              "ticker_pnl_daily": [{"sleeve": "코어", "ticker": "AAA",
                                    "pnl_x": cp._series_to_json(pd.Series([0, .1, -.05], index=dates))}],
              "daily_allocation": [{"date": day.date().isoformat(), "allocation": [
                  {"sleeve": "코어", "ticker": "AAA", "weight": 1.0}]} for day in dates]}
    c = explain.champion_components(result, "2026-10-01", 1000)
    assert c["pnl"].sum().sum() == pytest.approx(50)
    assert explain.movement_summary(c, "하락일")["rows"][0]["pnl_usd"] == pytest.approx(-50)


def test_ticker_trend_breaks_at_missing_close_instead_of_flatlining():
    dates = pd.to_datetime(["2026-10-01", "2026-10-02", "2026-10-05"])
    prices = {"AAA": pd.DataFrame({"Close": [100, None, 110]}, index=dates)}
    result = explain.ticker_price_trends(["AAA", "ZZZ"], dates,
                                        price_fn=lambda tickers, **kwargs: prices)
    assert result["curves"]["AAA"].iloc[0] == 0
    assert pd.isna(result["curves"]["AAA"].iloc[1])
    assert result["curves"]["AAA"].iloc[2] == pytest.approx(10)
    assert result["missing"] == ["ZZZ"]
    assert pd.isna(result["daily_returns"].loc[dates[2], "AAA"])  # 결측 다음 날도 보간 수익을 만들지 않는다.


def test_spy_price_correlation_does_not_claim_constituent_impact():
    dates = pd.bdate_range("2026-10-01", periods=7)
    spy = pd.Series([None, .01, -.02, .03, -.01, .02, -.03], index=dates)
    prices = pd.DataFrame({"AAA": spy, "BBB": -spy}, index=dates)
    rows = explain.price_correlation_rows(prices, spy)
    assert rows[0]["correlation_r"] == pytest.approx(1)
    assert rows[1]["correlation_r"] == pytest.approx(-1)
    assert all("pnl_usd" not in row for row in rows)
