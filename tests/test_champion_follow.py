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
    kwargs, _ = inputs()
    result = cf.compute_follow_performance("2026-10-13", use_cache=False, **kwargs)
    monkeypatch.setattr(cf, "load_cached", lambda *a: result)
    monkeypatch.setattr(cp, "load_latest_cached", lambda **kw: None)
    monkeypatch.setattr(cp, "load_cached", lambda *a: None)
    monkeypatch.setattr(cp, "build_live_record", lambda *a: pytest.fail("legacy ledger must not be displayed"))
    monkeypatch.setattr(job_manager, "render", lambda *a, **kw: None)
    monkeypatch.setattr(job_manager, "render_active_jobs_sidebar", lambda: None)
    monkeypatch.setattr(cs, "get_current_holdings", lambda: None)
    page = Path(__file__).resolve().parents[1] / "app/views/14_챔피언_성과.py"
    at = AppTest.from_file(page).run(timeout=20)
    assert not at.exception
    assert any("10월 1일부터 챔피언 전략을 따랐다면" in m.value for m in at.markdown)
    assert any("현재 가상 자산" in m.value for m in at.markdown)
    assert any("SATA" in df.value.to_string() for df in at.dataframe)
    assert not any("따랐다면(원장)" in m.value for m in at.markdown)
