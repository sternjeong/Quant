"""시작일 고정·공식 선정 재사용·누락 방지·독립 손익 검산. 외부 네트워크 없음."""
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from core import champion_follow as cf
from core import champion_performance as cp
from core import champion_strategy as cs


def inputs(end="2026-10-13", picks=True, missing=None):
    full = pd.bdate_range("2024-01-01", pd.Timestamp(end) - pd.Timedelta(days=1))
    idx = full[full >= cf.FOLLOW_START]
    hist = {t: pd.DataFrame({"Close": 100.0, "Adj Close": 100.0}, index=full)
            for t in [*cs.CORE_UNIVERSE, cs.CORE_CASH_ETF, "SPY", "SATA"]}
    # 시작일 이후 +10% 한 번. 기대값 = 코어85%*10% + 위성15%*10% - 편도 가중 비용.
    for t in [cs.CORE_UNIVERSE[0], "SATA"]:
        hist[t].loc[idx[1]:, ["Close", "Adj Close"]] = 110.0
    cw = pd.DataFrame({cs.CORE_UNIVERSE[0]: 1.0}, index=idx)
    core = {"weights": cw, **cs._compute_portfolio_returns(hist[cs.CORE_UNIVERSE[0]].loc[idx, ["Close"]].rename(columns={"Close": cs.CORE_UNIVERSE[0]}), cw, cs.CORE_COST_BPS_PER_SIDE)}
    if missing:
        hist[missing].loc[idx[1], "Close"] = np.nan
        hist[missing].loc[idx[1], "Adj Close"] = np.nan
    calls = []
    def price(tickers, **kwargs):
        return {t: hist[t] for t in tickers if t in hist}
    def pick(dt):
        calls.append(dt)
        return {"date": str(dt.date()), "picks": ["SATA"] if picks else [],
                "weights": {"SATA": 1.0} if picks else {}, "pool_size": 40, "n_with_history": 40,
                "n_active_trend": int(picks)}
    return {"price_fn": price, "core_fn": lambda *a: core, "pick_fn": pick}, calls


def test_start_is_october_first_and_selection_matches_date(tmp_path):
    kwargs, calls = inputs()
    result = cf.compute_follow_performance("2026-10-13", cache_dir=tmp_path, **kwargs)
    assert calls == [pd.Timestamp("2026-10-01")]
    assert result["summary"]["start"] == "2026-10-01"
    assert result["summary"]["end"] == "2026-10-12"
    fee = .85 * 3 / 10000 + .15 * 8 / 10000
    assert result["summary"]["total_return_pct"] == pytest.approx((.1-fee)*100)
    assert result["reconciliation"]["ok"]
    assert [r["ticker"] for r in result["initial_allocation"]] == [cs.CORE_UNIVERSE[0], "SATA"]
    assert result["next_satellite_reselection"] == "2027-04-01"
    assert all(e["date"] == "2026-10-01" for e in result["events"])
    cached = cf.compute_follow_performance("2026-10-13", cache_dir=tmp_path,
                price_fn=lambda *a, **k: pytest.fail("cached result should not fetch"))
    assert cached == result


def test_ticker_attribution_matches_champion_curve_for_selected_period():
    kwargs, _ = inputs()
    result = cf.compute_follow_performance("2026-10-13", use_cache=False, **kwargs)
    rows = cf.ticker_attribution_for_period(result, "2026-10-01", 10_000)
    assert {row["ticker"] for row in rows if row["pnl_usd"] > 0} == {cs.CORE_UNIVERSE[0], "SATA"}
    assert sum(row["pnl_usd"] for row in rows) == pytest.approx(
        (result["summary"]["final_x"] - 1.0) * 10_000, abs=1e-5)
    later = cf.ticker_attribution_for_period(result, "2026-10-06", 10_000)
    assert sum(row["pnl_usd"] for row in later) == pytest.approx(0, abs=1e-5)


def test_salary_flow_scales_existing_champion_positions_and_ticker_profit():
    from core import portfolio_account_history as pah
    from core import performance_explain as explain
    kwargs, _ = inputs()
    result = cf.compute_follow_performance("2026-10-13", use_cache=False, **kwargs)
    strategy = cp.series_from_json(result["curves"]["strategy"])
    spy = cp.series_from_json(result["curves"]["spy"])
    dates = strategy.index
    flow = pd.Series(0.0, index=dates)
    flow.loc[pd.Timestamp("2026-10-02")] = 1000
    actual = {"nav": pd.Series(1000.0, index=dates), "flows": flow, "start_value": 1000}
    comparison = pah.matched_benchmarks(strategy, spy, actual,
                                        daily_allocation=result["daily_allocation"],
                                        ticker_pnl_daily=result["ticker_pnl_daily"])
    assert comparison["champion"].loc[pd.Timestamp("2026-10-02")] > 2000
    assert comparison["spy"].loc[pd.Timestamp("2026-10-02")] == pytest.approx(2000)
    assert sum(comparison["champion_ticker_pnl"].values()) == pytest.approx(
        comparison["profit_usd"]["champion"], abs=.02)
    assert comparison["champion_daily_ticker_pnl"].sum().sum() == pytest.approx(
        comparison["profit_usd"]["champion"], abs=.02)
    daily = comparison["champion_daily_ticker_pnl"].copy()
    daily.iloc[0] = 0.0
    component = {"nav": comparison["champion"], "flows": actual["flows"], "pnl": daily,
                 "active": explain.champion_active(result, dates, daily.columns)}
    assert explain.movement_summary(component, "전체")["n_days"] == len(dates) - 1


def test_no_picks_keeps_satellite_cash_not_core_100_percent():
    kwargs, _ = inputs(picks=False)
    result = cf.compute_follow_performance("2026-10-13", use_cache=False, **kwargs)
    assert result["summary"]["total_return_pct"] == pytest.approx((.85*.1-.85*.0003)*100)
    assert result["initial_allocation"][-1] == {"sleeve": "현금", "ticker": "CASH", "weight": pytest.approx(.15)}
    assert result["reconciliation"]["ok"]


@pytest.mark.parametrize("ticker", ["SATA", cs.CORE_UNIVERSE[0]])
def test_missing_held_price_is_not_flat_return(ticker):
    kwargs, _ = inputs(missing=ticker)
    with pytest.raises(ValueError, match="보유 종목 가격 누락"):
        cf.compute_follow_performance("2026-10-13", use_cache=False, **kwargs)


def test_missing_satellite_data_fails_instead_of_cash():
    kwargs, _ = inputs()
    kwargs["pick_fn"] = lambda dt: {"pool_size": 40, "n_with_history": 0, "weights": {}}
    with pytest.raises(ValueError, match="후보 가격 부족"):
        cf.compute_follow_performance("2026-10-13", use_cache=False, **kwargs)


def test_wbd_cash_merger_pays_out_and_then_stays_cash():
    kwargs, _ = inputs()
    original_price = kwargs["price_fn"]
    def price(tickers, **options):
        histories = original_price(tickers, **options)
        if "WBD" in tickers:
            days = pd.bdate_range("2024-01-01", "2026-10-06")
            histories["WBD"] = pd.DataFrame({"Close": 30.95, "Adj Close": 30.95}, index=days)
        return histories
    kwargs["price_fn"] = price
    kwargs["pick_fn"] = lambda dt: {"picks": ["WBD"], "weights": {"WBD": 1.0},
                                    "pool_size": 40, "n_with_history": 40}
    result = cf.compute_follow_performance("2026-10-13", use_cache=False, **kwargs)
    assert result["reconciliation"]["ok"]
    assert result["cash_mergers"][0]["cash_per_share"] == 31.01666668
    assert result["summary"]["total_return_pct"] == pytest.approx(
        ((1 + 0.85 * 0.1 - 0.85 * .0003 - 0.15 * .0008)
         * (1 + 0.15 * (31.01666668 / 30.95 - 1)) - 1) * 100,
        abs=1e-4)
    assert {r["ticker"] for r in result["initial_allocation"]} == {cs.CORE_UNIVERSE[0], "WBD"}
    assert {r["ticker"] for r in result["latest_allocation"]} == {cs.CORE_UNIVERSE[0], "CASH"}
    assert next(r for r in result["latest_allocation"] if r["ticker"] == "CASH")["weight"] == pytest.approx(.15)
    assert any(e["ticker"] == "WBD" and e["action"] == "현금인수" and e["date"] == "2026-10-06"
               for e in result["events"])
    assert next(t for t in result["trades"] if t["ticker"] == "WBD")["is_open"] is False


def test_cash_merger_has_no_second_sale_fee_at_next_reselection():
    kwargs, _ = inputs(end="2027-04-07")
    original_price = kwargs["price_fn"]
    def price(tickers, **options):
        histories = original_price(tickers, **options)
        if "WBD" in tickers:
            days = pd.bdate_range("2024-01-01", "2026-10-06")
            histories["WBD"] = pd.DataFrame({"Close": 30.95}, index=days)
        return histories
    kwargs["price_fn"] = price
    kwargs["pick_fn"] = lambda dt: {"picks": ["WBD" if dt.month == 10 else "SATA"],
                                    "weights": {"WBD" if dt.month == 10 else "SATA": 1.0},
                                    "pool_size": 40, "n_with_history": 40}
    result = cf.compute_follow_performance("2027-04-07", use_cache=False, **kwargs)
    assert result["reconciliation"]["ok"]
    assert not any(e["ticker"] == "WBD" and e["action"] == "매도" for e in result["events"])
    assert next(t for t in result["trades"] if t["ticker"] == "WBD")["sell_date"] == "2026-10-06"
    # 4/02에는 새 SATA 매수 8bp만 든다. 이미 10/06 현금화된 WBD를 다시 매도하지 않는다.
    curve = cp.series_from_json(result["curves"]["satellite"])
    april = pd.Timestamp("2027-04-02")
    assert curve.loc[april] / curve.loc["2027-04-01"] - 1 == pytest.approx(-.0008, abs=1e-7)


def test_reselection_holds_six_months_and_uses_actual_sessions():
    idx = pd.bdate_range("2026-10-01", "2027-10-05").difference(pd.DatetimeIndex(["2027-04-01"]))
    assert cf.reselection_dates(idx, cf.FOLLOW_START) == list(pd.to_datetime(["2026-10-01", "2027-04-02", "2027-10-01"]))


def test_cache_does_not_reuse_other_strategy_version(tmp_path, monkeypatch):
    kwargs, _ = inputs()
    cf.compute_follow_performance("2026-10-13", cache_dir=tmp_path, **kwargs)
    monkeypatch.setattr(cs, "CHAMPION_STRATEGY_VERSION", "next-version")
    assert cf.load_cached("2026-10-13", cache_dir=tmp_path) is None


def test_page_displays_follow_result_without_using_legacy_ledger(monkeypatch, tmp_path):
    from pathlib import Path
    from core import job_manager
    from core import personal_performance
    from core import portfolio_account_history
    from core import performance_explain
    kwargs, _ = inputs()
    result = cf.compute_follow_performance("2026-10-13", use_cache=False, **kwargs)
    result["cash_mergers"] = [dict(cf.WBD_CASH_MERGER)]
    monkeypatch.setattr(cf, "load_cached", lambda *a: result)
    monkeypatch.setattr(cp, "load_latest_cached", lambda **kw: None)
    monkeypatch.setattr(cp, "load_cached", lambda *a: None)
    monkeypatch.setattr(cp, "build_live_record", lambda *a: pytest.fail("legacy ledger must not be displayed"))
    monkeypatch.setattr(job_manager, "render", lambda *a, **kw: None)
    monkeypatch.setattr(job_manager, "render_active_jobs_sidebar", lambda: None)
    monkeypatch.setattr(cs, "get_current_holdings", lambda: None)
    monkeypatch.setattr("core.portfolio.list_holdings", lambda: [{"ticker": "SATA", "quantity": 1}])
    monkeypatch.setattr(personal_performance, "current_holdings_curve", lambda *a, **kw: {
        "available": True, "curve": pd.Series([1.0, 1.02], index=pd.to_datetime(["2026-10-09", "2026-10-12"])),
        "first_date": "2026-10-09", "last_date": "2026-10-12", "n_holdings": 1,
        "cost_usd": 100, "last_value_usd": 102, "unrealized_pnl_usd": 2, "twr_pct": 2,
        "daily_values": pd.Series([100.0, 102.0], index=pd.to_datetime(["2026-10-09", "2026-10-12"])),
        "daily_flows": pd.Series([0.0, 0.0], index=pd.to_datetime(["2026-10-09", "2026-10-12"])),
        "daily_ticker_pnl": pd.DataFrame({"SATA": [0.0, 2.0]}, index=pd.to_datetime(["2026-10-09", "2026-10-12"])),
        "daily_active": pd.DataFrame({"SATA": [True, True]}, index=pd.to_datetime(["2026-10-09", "2026-10-12"])),
    })
    monkeypatch.setattr(performance_explain, "ticker_price_trends", lambda tickers, sessions: {
        "curves": {ticker: pd.Series(0.0, index=sessions) for ticker in tickers},
        "daily_returns": pd.DataFrame({ticker: pd.Series(0.0, index=sessions) for ticker in tickers}, index=sessions),
        "missing": [],
    })
    monkeypatch.setattr(portfolio_account_history, "load_ledger", lambda: {
        "as_of": "2026-10-01", "cash_usd": 1000, "positions": {},
        "events": [{"as_of": "2026-10-02", "kind": "DEPOSIT", "amount_usd": 1000}],
    })
    page = Path(__file__).resolve().parents[1] / "app/views/14_챔피언_성과.py"
    at = AppTest.from_file(page).run(timeout=20)
    assert not at.exception
    next(r for r in at.radio if r.key == "follow_movement_direction").set_value("상승일").run(timeout=20)
    assert not at.exception
    assert any("10월 1일부터 챔피언 전략을 따랐다면" in m.value for m in at.markdown)
    assert any("현재 가상 자산" in m.value for m in at.markdown)
    assert any("WBD" in m.value and "현금 인수" in m.value for m in at.info)
    assert any("10월 1일부터의 수익률 변화" in m.value for m in at.markdown)
    assert any("선 위에 겹쳐 볼 종목" in m.label for m in at.multiselect)
    assert any("상승·하락을 움직인 종목" in m.value for m in at.markdown)
    assert any("가격 동행 r" in df.value.columns for df in at.dataframe)
    assert any("같은 입출금으로 비교한 실제 계좌" in m.value for m in at.markdown)
    assert any("이 달러 그래프의 상승·하락을 만든 종목" in e.label for e in at.expander)
    assert any("외부 입출금 1건" in m.value for m in at.markdown)
    assert any("가상 손익($)" in df.value.columns and "수익률 기여(%p)" in df.value.columns
               for df in at.dataframe)
    assert any("실제 계좌 전체 수익률은 아닙니다" in m.value for m in at.caption)
    assert any("같은 기간 2026-10-09~2026-10-12" in m.value for m in at.caption)
    at.radio[0].set_value("내 첫 매입일부터 같은 기간").run(timeout=20)
    assert not at.exception
    assert any("2026-10-09부터의 수익률 변화" in m.value for m in at.markdown)
    assert any("SATA" in df.value.to_string() for df in at.dataframe)
    assert not any("따랐다면(원장)" in m.value for m in at.markdown)
