"""core/champion_performance.py + app/pages/14_챔피언_성과.py 테스트.

네트워크 없음: 가격 공급자·유니버스 표본을 합성 데이터로 바꿔 끼운다. 기대값은 손으로 계산했다
(체결 관례: 신호일 종가 매수, weights.shift(1) 로 다음 날 수익부터 반영, 비중 변화분 × 편도 비용).
"""

import json
import pathlib
import socket
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import core.champion_strategy as cs
from core import champion_performance as cp

PAGE = pathlib.Path(__file__).resolve().parents[1] / "app" / "pages" / "14_챔피언_성과.py"


# ----------------------------------------------------------------------------
# 손계산 합성 가중치/가격
# ----------------------------------------------------------------------------

IDX = pd.bdate_range("2024-01-01", periods=6)


def _closes(values):
    return pd.DataFrame({"AAA": values}, index=IDX, dtype=float)


def _weights(values):
    return pd.DataFrame({"AAA": values}, index=IDX, dtype=float)


SPY = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=IDX)
ONES = pd.Series(1.0, index=IDX)


def test_holding_interval_recovered_with_cost_and_spy_comparison():
    closes = _closes([100, 110, 121, 110, 110, 110])
    weights = _weights([0, 1, 1, 0, 0, 0])  # 1일차 신호 → 2·3일차 수익 반영 → 3일차 신호로 0
    trades, events = cp.extract_trades("코어", closes, weights, 10.0, 1.0, ONES, SPY)

    assert len(trades) == 1
    t = trades[0]
    assert (t["buy_date"], t["sell_date"]) == (IDX[1].date().isoformat(), IDX[3].date().isoformat())
    assert (t["buy_price"], t["sell_price"]) == (110.0, 110.0)
    assert t["is_open"] is False
    assert t["holding_days"] == (IDX[3] - IDX[1]).days
    assert t["price_return_pct"] == pytest.approx(0.0)
    # 편도 10bp 두 번: 0.999^2 - 1
    assert t["net_return_pct"] == pytest.approx((0.999 ** 2 - 1) * 100, abs=1e-4)
    assert t["spy_return_pct"] == pytest.approx((103 / 101 - 1) * 100, abs=1e-4)
    assert t["excess_vs_spy_pct"] == pytest.approx(t["net_return_pct"] - t["spy_return_pct"], abs=1e-3)
    # 손익(초기=1): 2일차 +10% - 매수비용 0.001, 3일차 110/121-1, 4일차 매도비용 0.001
    expected = (0.10 - 0.001) + (110 / 121 - 1) - 0.001
    assert t["pnl_x"] == pytest.approx(expected, abs=1e-12)
    assert [e["action"] for e in events] == ["매수", "매도"]


def test_partial_reweight_is_one_holding_with_adjustment_events():
    closes = _closes([100, 100, 100, 100, 100, 100])
    weights = _weights([0, 0.5, 1.0, 1.0, 0, 0])
    trades, events = cp.extract_trades("코어", closes, weights, 0.0, 0.85, ONES, SPY)
    assert len(trades) == 1
    assert trades[0]["n_adjustments"] == 1
    assert [e["action"] for e in events] == ["매수", "추가매수", "매도"]
    assert events[1]["weight_before_pct"] == pytest.approx(42.5)
    assert events[1]["weight_after_pct"] == pytest.approx(85.0)
    # 초기 1당 수량 = 비중 변화 × 슬리브 비중 / 가격
    assert events[0]["shares_per_capital"] == pytest.approx(0.5 * 0.85 / 100)


def test_position_held_to_end_is_open_with_single_side_cost():
    closes = _closes([100, 100, 100, 100, 100, 120])
    weights = _weights([0, 0, 0, 1, 1, 1])
    trades, _ = cp.extract_trades("새틀라이트", closes, weights, 8.0, 0.15, ONES, SPY)
    t = trades[0]
    assert t["is_open"] is True and t["sell_date"] == IDX[-1].date().isoformat()
    assert t["net_return_pct"] == pytest.approx((1.2 * (1 - 0.0008) - 1) * 100, abs=1e-4)


def test_sleeve_contributions_sum_to_backtest_returns():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-01", periods=60)
    closes = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0, 0.01, (60, 3)), axis=0), index=idx, columns=list("ABC"))
    raw = rng.integers(0, 3, (60, 3)) / 4.0
    weights = pd.DataFrame(raw, index=idx, columns=list("ABC"))
    ours = cp.sleeve_contributions(closes, weights, 3.0)["ret_net"]
    theirs = cs._compute_portfolio_returns(closes, weights, cost_bps_per_side=3.0)["ret_net"]
    assert (ours - theirs).abs().max() < 1e-15


def test_drawdown_info_finds_peak_trough_and_recovery():
    s = pd.Series([1.0, 1.2, 0.9, 1.0, 1.25], index=pd.bdate_range("2024-01-01", periods=5))
    info = cp.drawdown_info(s)
    assert info["mdd_pct"] == pytest.approx(-25.0)
    assert info["peak_date"] == s.index[1].date().isoformat()
    assert info["trough_date"] == s.index[2].date().isoformat()
    assert info["recovery_date"] == s.index[4].date().isoformat()


# ----------------------------------------------------------------------------
# 회귀: 실제 run_champion_backtest 와 자산곡선이 일치
# ----------------------------------------------------------------------------

BT_START, BT_END = "2022-01-01", "2023-12-29"
SAT_POOL = ["SATA", "SATB", "SATC", "SATD"]


def _series(start, end, annual_pct, seed, noise=0.01, warmup_days=900):
    idx = pd.bdate_range(pd.Timestamp(start) - pd.DateOffset(days=warmup_days), pd.Timestamp(end))
    rng = np.random.default_rng(seed)
    drift = (1 + annual_pct / 100) ** (1 / 252) - 1
    close = 100 * np.cumprod(1 + drift + rng.normal(0, noise, len(idx)))
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1}, index=idx)


_ANNUAL = {t: (35.0 - 5 * i) for i, t in enumerate(cs.CORE_UNIVERSE)}
_ANNUAL.update({"SPY": 10.0, "SATA": 60.0, "SATB": 45.0, "SATC": 30.0, "SATD": -20.0})
_SEEDS = {t: i + 1 for i, t in enumerate(list(_ANNUAL))}


def _fake_prices(tickers, start=None, end=None, interval="1d", use_cache=True):
    out = {}
    for t in tickers:
        df = _series(BT_START, BT_END, _ANNUAL.get(t, 5.0), _SEEDS.get(t, 99))
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            df = df[df.index <= pd.Timestamp(end)]
        out[t] = df
    return out


@pytest.fixture()
def synthetic_market(monkeypatch):
    monkeypatch.setattr(cs, "get_multiple_price_history", _fake_prices)
    monkeypatch.setattr(cs, "sample_universe",
                        lambda n, as_of_date=None, use_point_in_time_market_cap=False, use_cache=True:
                        pd.DataFrame({"ticker": SAT_POOL}))


def test_equity_curves_match_existing_champion_backtest(synthetic_market):
    bt = cs.run_champion_backtest(BT_START, BT_END)
    assert bt["satellite_weight_applied"] > 0, "새틀라이트가 한 번은 종목을 골라야 회귀 검증이 의미 있다"
    res = cp.analyze_backtest(bt)

    rec = res["reconciliation"]
    assert rec["ok"], rec
    assert rec["max_abs_return_diff_core"] < 1e-12
    assert rec["max_abs_return_diff_satellite"] < 1e-12
    assert rec["trade_pnl_sum_x"] == pytest.approx(rec["equity_pnl_x"], abs=1e-9)

    strategy = cp.series_from_json(res["curves"]["strategy"])
    expected = bt["equity_net"] / 100.0
    assert np.allclose(strategy.values, expected.values, atol=1e-7)
    core = cp.series_from_json(res["curves"]["core"])
    assert np.allclose(core.values, (bt["core"]["equity_net"] / 100.0).values, atol=1e-7)
    sat = cp.series_from_json(res["curves"]["satellite"])
    assert np.allclose(sat.values, (bt["satellite"]["equity_net"] / 100.0).values, atol=1e-7)

    assert {t["sleeve"] for t in res["trades"]} == {cp.SLEEVE_CORE, cp.SLEEVE_SATELLITE}
    assert sum(r["pnl_x"] for r in res["ticker_contributions"]) == pytest.approx(rec["equity_pnl_x"], abs=1e-9)
    assert res["summary"]["total_return_pct"] == pytest.approx(bt["metrics"]["cumulative_return"], abs=0.01)
    years = [r["year"] for r in res["yearly"]]
    assert years == [2022, 2023]


def test_amounts_scale_linearly_with_initial_capital(synthetic_market):
    res = cp.analyze_backtest(cs.run_champion_backtest(BT_START, BT_END))
    a, b = cp.to_dollars(res, 10_000), cp.to_dollars(res, 25_000)
    assert b["pnl_usd"] == pytest.approx(a["pnl_usd"] * 2.5)
    assert b["curves"]["strategy"].iloc[0] == pytest.approx(25_000)
    assert a["trades"]["pnl_usd"].sum() == pytest.approx(a["pnl_usd"], abs=1e-4)
    assert b["events"]["shares"].iloc[0] == pytest.approx(a["events"]["shares"].iloc[0] * 2.5)


# ----------------------------------------------------------------------------
# 캐시
# ----------------------------------------------------------------------------

def test_cache_key_depends_on_inputs_and_version(monkeypatch):
    p1 = cp.cache_params("2021-01-01", "2026-09-26", 0.15)
    assert cp.cache_key(p1) == cp.cache_key(dict(p1))
    assert cp.cache_key(p1) != cp.cache_key(cp.cache_params("2021-01-01", "2026-09-25", 0.15))
    assert cp.cache_key(p1) != cp.cache_key(cp.cache_params("2021-01-01", "2026-09-26", 0.10))
    monkeypatch.setattr(cs, "CHAMPION_STRATEGY_VERSION", "other-version")
    assert cp.cache_key(cp.cache_params("2021-01-01", "2026-09-26", 0.15)) != cp.cache_key(p1)


def test_compute_uses_cache_and_latest_lookup(tmp_path, synthetic_market):
    calls = []

    def _bt(start, end, satellite_weight=0.15):
        calls.append((start, end))
        return cs.run_champion_backtest(start, end, satellite_weight=satellite_weight)

    first = cp.compute_backtest_performance(BT_START, BT_END, cache_dir=tmp_path, backtest_fn=_bt)
    second = cp.compute_backtest_performance(BT_START, BT_END, cache_dir=tmp_path, backtest_fn=_bt)
    assert len(calls) == 1 and first["from_cache"] is False and second["from_cache"] is True
    assert list(tmp_path.glob("champion_performance_*.json"))
    latest = cp.load_latest_cached(start=BT_START, satellite_weight=0.15, cache_dir=tmp_path)
    assert latest["params"]["end"] == BT_END
    assert cp.load_latest_cached(start="1999-01-01", cache_dir=tmp_path) is None
    assert cp.latest_snapshot_meta(tmp_path)["computed_at"] == first["computed_at"]
    # 파라미터가 다른 파일은 같은 경로여도 쓰지 않는다
    path = cp.cache_path(first["params"], tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["params"]["start"] = "tampered"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert cp.load_cached(first["params"], tmp_path) is None


# ----------------------------------------------------------------------------
# 실시간 기록 — 백테스트와 분리
# ----------------------------------------------------------------------------

def _entries(n, start=date(2026, 9, 19)):
    out, eq = [], 100.0
    for i in range(n):
        r = 0.0 if i == 0 else 0.5
        eq *= 1 + r / 100
        core = {"XLK": 0.2125, "GLD": 0.2125} if i < 3 else {"XLK": 0.2125, "XLU": 0.2125}
        out.append({"entry_date": (start + timedelta(days=i)).isoformat(), "core_weights": core,
                    "satellite_weights": {"NVDA": 0.05}, "realized_return_pct": r, "cumulative_equity": eq})
    return out


def _live_prices(tickers, start=None, end=None, interval="1d", use_cache=True):
    idx = pd.date_range("2026-09-19", periods=10, freq="D")
    base = {"SPY": np.linspace(100, 102, 10), "TLT": np.linspace(100, 99, 10)}
    return {t: pd.DataFrame({"Close": base[t]}, index=idx) for t in tickers}


def test_live_record_empty_ledger_is_reported_not_faked():
    live = cp.build_live_record(entries=[], paper_snapshots=[], price_fn=_live_prices)
    assert live["kind"] == "live"
    assert live["available"] is False and live["enough"] is False
    assert "원장 기록이 아직 없습니다" in live["reason"]
    assert live["paper"]["available"] is False
    assert "trades" not in live and "curves" not in live


def test_live_record_short_ledger_flags_insufficient_and_compares_benchmarks():
    entries = _entries(5)
    live = cp.build_live_record(entries=entries, paper_snapshots=[(date(2026, 9, 24), 100_000.0),
                                                                  (date(2026, 9, 25), 101_000.0)],
                                price_fn=_live_prices)
    assert live["available"] is True
    assert live["enough"] is False  # 5일 < 20일
    assert live["ledger_total_return_pct"] == pytest.approx((1.005 ** 4 - 1) * 100, abs=1e-3)
    spy_end = np.linspace(100, 102, 10)[4]
    assert live["spy_total_return_pct"] == pytest.approx((spy_end / 100 - 1) * 100, abs=1e-3)
    assert live["sixty_forty_total_return_pct"] is not None
    actions = {(c["ticker"], c["action"]) for c in live["weight_changes"]}
    assert ("GLD", "제외") in actions and ("XLU", "편입") in actions
    assert live["paper"]["available"] is True and live["paper"]["last_equity"] == 101_000.0


def test_backtest_does_not_read_live_ledger(tmp_path, synthetic_market, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("백테스트 계산이 실시간 원장을 읽으면 안 된다")

    monkeypatch.setattr(cs, "list_ledger_entries", _boom)
    res = cp.compute_backtest_performance(BT_START, BT_END, cache_dir=tmp_path)
    assert res["kind"] == "backtest" and "ledger_curve" not in res


# ----------------------------------------------------------------------------
# 화면 (AppTest)
# ----------------------------------------------------------------------------

@pytest.fixture()
def page_env(tmp_path, monkeypatch, synthetic_market):
    import streamlit as st
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import core.db as db

    engine = create_engine(f"sqlite:///{tmp_path / 'page.db'}", connect_args={"check_same_thread": False}, future=True)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))
    db.init_db()
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(cp, "CACHE_DIR", cache_dir)
    st.cache_data.clear()
    yield cache_dir
    st.cache_data.clear()


def _run_page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [w.value for w in at.warning] + [i.value for i in at.info]
    return " ".join(str(p) for p in parts)


def test_page_renders_without_cache_and_does_not_start_job(page_env, monkeypatch):
    from core import job_manager

    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked")))
    at = _run_page()
    txt = _text(at)
    assert "A. 백테스트" in txt and "B. 실제 시장 기록(2026-09-19~)" in txt
    assert "아직 이 기간의 계산 결과가 없습니다" in txt
    assert "기록 없음" in txt
    assert not job_manager.list_running_jobs()


def test_page_renders_cached_backtest_and_live_ledger(page_env, monkeypatch):
    import core.db as db
    from core.models import ChampionLedgerEntry

    bt = cs.run_champion_backtest(BT_START, BT_END)
    res = cp.analyze_backtest(bt)
    params = cp.cache_params(cp.default_start(), (date.today() - timedelta(days=1)).isoformat(), cs.SATELLITE_WEIGHT)
    res["params"], res["computed_at"] = params, "2026-09-26T00:00:00+00:00"
    page_env.mkdir(parents=True, exist_ok=True)
    cp.cache_path(params, page_env).write_text(json.dumps(res), encoding="utf-8")

    with db.get_session() as s:
        for e in _entries(4):
            s.add(ChampionLedgerEntry(entry_date=date.fromisoformat(e["entry_date"]),
                                      core_weights=json.dumps(e["core_weights"]),
                                      satellite_weights=json.dumps(e["satellite_weights"]),
                                      realized_return_pct=e["realized_return_pct"],
                                      cumulative_equity=e["cumulative_equity"]))
    monkeypatch.setattr(cs, "get_multiple_price_history", _live_prices)

    at = _run_page()
    txt = _text(at)
    assert "최종 금액(가상)" in txt
    assert "✅ 검산" in txt
    assert "아직 기간이 짧아 판단 불가" in txt
    assert len(at.dataframe) >= 2
