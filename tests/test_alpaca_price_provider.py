"""core/alpaca_price_provider.py — 실제 네트워크 없음(주입한 mock 만). 키 값은 센티널로 유출 여부를 검사한다."""

import pandas as pd
import pytest

from core import alpaca_price_provider as app
from core import candidate_ledger as cl
from core import price_crosscheck as pcc
from core.models import CandidateOutcome

KEY, SECRET = "SENTINEL-KEY-0001", "SENTINEL-SECRET-0002"
ENV = {"ALPACA_PAPER_API_KEY": KEY, "ALPACA_PAPER_API_SECRET": SECRET}
IDX = pd.bdate_range("2026-06-01", periods=8)


def yf_frame(opens=None, closes=None):
    o = pd.Series(opens or [100.0 + i for i in range(8)], index=IDX, dtype=float)
    c = pd.Series(closes or list(o + 0.5), index=IDX, dtype=float)
    return pd.DataFrame({"Open": o, "High": o + 1, "Low": o - 1, "Close": c, "Adj Close": c, "Volume": 1000.0}, index=IDX)


def bars_like(df, close_scale=1.0, open_offset=0.25, drop=()):
    out = []
    for ts, r in df.iterrows():
        if ts in drop:
            continue
        out.append({"t": ts.strftime("%Y-%m-%dT04:00:00Z"), "o": r["Open"] + open_offset, "h": r["High"], "l": r["Low"],
                    "c": r["Close"] * close_scale, "v": 500})
    return out


def make(env, yf_df, bars=None, fetch=None):
    calls = {"alpaca": 0}

    def _fetch(sym, a, b):
        calls["alpaca"] += 1
        if fetch:
            return fetch(sym, a, b)
        return bars

    prov = app.make_alpaca_price_provider(
        default_provider=lambda t, s, e: yf_df.copy(), env=env,
        alpaca_fetch_fn=_fetch if (bars is not None or fetch) else None)
    return prov, calls


def test_no_key_uses_default_provider_and_never_touches_alpaca(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("키가 없으면 Alpaca 를 호출하면 안 된다")

    monkeypatch.setattr(pcc, "fetch_alpaca_daily_bars", boom)
    yf = yf_frame()
    prov, calls = make({}, yf)
    out = prov("XLK", "2026-06-01", "2026-06-12")
    pd.testing.assert_frame_equal(out, yf, check_freq=False, check_names=False)
    rep = prov.report()
    assert rep["alpaca_enabled"] is False
    assert rep["per_ticker"]["XLK"]["source"] == app.SOURCE_DEFAULT
    assert rep["per_ticker"]["XLK"]["reason"] == "no_alpaca_credentials"
    assert calls["alpaca"] == 0 and out.attrs["price_source"] == app.SOURCE_DEFAULT


def test_clean_crosscheck_uses_alpaca_bars_and_reports_source():
    yf = yf_frame()
    prov, calls = make(ENV, yf, bars=bars_like(yf))
    out = prov("XLK", "2026-06-01", "2026-06-12")
    assert calls["alpaca"] == 1
    assert out.attrs["price_source"] == app.SOURCE_ALPACA
    assert out["Open"].iloc[0] == pytest.approx(100.25)  # Alpaca 시가(yfinance 와 다른 값) 사용
    m = prov.report()["per_ticker"]["XLK"]
    assert m["source"] == app.SOURCE_ALPACA and m["reason"] == "crosscheck_clean"
    assert m["crosscheck"].get("match") == 8 and m["overlap_days"] == 8
    assert "판정하지 않는다" in m["note"]  # 어느 소스가 옳은지 판정하지 않음


def test_crosscheck_mismatch_falls_back_to_default_with_meta():
    yf = yf_frame()
    prov, _ = make(ENV, yf, bars=bars_like(yf, close_scale=1.10))  # 종가 +10% = 1000bp -> major_diff
    out = prov("XLK", "2026-06-01", "2026-06-12")
    pd.testing.assert_frame_equal(out, yf, check_freq=False, check_names=False)
    m = prov.report()["per_ticker"]["XLK"]
    assert m["source"] == app.SOURCE_DEFAULT
    assert m["reason"].startswith("fallback:") and "major_diff_days=8" in m["reason"]
    assert m["crosscheck"].get("major_diff") == 8


def test_missing_alpaca_days_fall_back():
    yf = yf_frame()
    prov, _ = make(ENV, yf, bars=bars_like(yf, drop=(IDX[3],)))
    out = prov("XLK", "2026-06-01", "2026-06-12")
    assert out.attrs["price_source"] == app.SOURCE_DEFAULT
    assert "missing_in_alpaca_days=1" in prov.report()["per_ticker"]["XLK"]["reason"]


@pytest.mark.parametrize("exc", [pcc.AlpacaDataUnavailable("http 429"), RuntimeError("boom")])
def test_alpaca_fetch_failure_falls_back(exc):
    yf = yf_frame()

    def fetch(*a):
        raise exc

    prov, _ = make(ENV, yf, fetch=fetch)
    out = prov("XLK", "2026-06-01", "2026-06-12")
    assert out.attrs["price_source"] == app.SOURCE_DEFAULT
    assert "crosscheck_unavailable" in prov.report()["per_ticker"]["XLK"]["reason"]


def test_env_key_path_calls_fetcher_with_credentials_and_leaks_nothing(monkeypatch):
    yf = yf_frame()
    seen = {}

    def fake_fetch(symbol, start, end, *, credentials=None, feed=None, **kw):
        seen["has_credentials"] = credentials is not None
        seen["feed"] = feed
        return bars_like(yf)

    monkeypatch.setattr(pcc, "fetch_alpaca_daily_bars", fake_fetch)
    prov = app.make_alpaca_price_provider(default_provider=lambda t, s, e: yf.copy(), env=ENV)
    out = prov("XLK", "2026-06-01", "2026-06-12")
    assert seen == {"has_credentials": True, "feed": "iex"} and out.attrs["price_source"] == app.SOURCE_ALPACA
    blob = repr(prov.report()) + repr(out.attrs) + repr(prov.report()["per_ticker"])
    assert KEY not in blob and SECRET not in blob


def test_provider_plugs_into_update_forward_outcomes(db_session):
    idx = pd.bdate_range("2026-06-01", periods=30)
    o = pd.Series(100.0, index=idx)
    stock = pd.DataFrame({"Open": o, "High": o, "Low": o, "Close": o, "Adj Close": o, "Volume": 1.0}, index=idx)
    spy = stock.copy()

    def bars(df):
        return [{"t": t.strftime("%Y-%m-%dT04:00:00Z"), "o": r.Open, "h": r.High, "l": r.Low, "c": r.Close, "v": 5}
                for t, r in df.iterrows()]

    frames = {"AAA": stock, "SPY": spy}
    prov = app.make_alpaca_price_provider(
        default_provider=lambda t, s, e: frames.get(t, pd.DataFrame()).copy(), env=ENV,
        alpaca_fetch_fn=lambda t, s, e: bars(frames[t]))
    cset = cl.FrozenCandidateSet("t", "v", "2026-06-01", [cl.CandidateRecord("AAA", "selected")])
    cl.record_candidate_set(cset, session=db_session)
    res = app.update_outcomes_with_sources(idx[-1].date(), session=db_session, provider=prov, horizons=(5,))
    assert res["update"]["finalized"] == 1
    assert res["price_sources"]["source_counts"] == {app.SOURCE_ALPACA: 2}  # AAA, SPY
    o5 = db_session.query(CandidateOutcome).one()
    assert o5.status == "final" and o5.gross_return == pytest.approx(0.0)
