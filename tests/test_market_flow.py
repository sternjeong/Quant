"""core/market_flow.py — 합성 가격으로 강도·로테이션·상관·조건부 검정·주도주를 검증한다(네트워크 없음)."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from core import market_flow as mf


def _bdays(n: int, end: str = "2026-10-29") -> pd.DatetimeIndex:
    return pd.bdate_range(end=end, periods=n)


def _prices(n: int = 800, seed: int = 1, tickers=("SPY", "AAA", "BBB", "CCC")) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = _bdays(n)
    data = {t: 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, n)) for t in tickers}
    return pd.DataFrame(data, index=idx)


# ----------------------------------------------------------------- 강도
def test_strength_factor_orders_by_trend_and_handles_short_history():
    idx = _bdays(300)
    up = pd.Series(np.linspace(100, 200, 300), index=idx)
    down = pd.Series(np.linspace(100, 60, 300), index=idx)
    assert mf.strength_factor(up) > 0 > mf.strength_factor(down)
    assert mf.strength_factor(up.iloc[:50]) is None  # 63거래일 미만이면 점수 없음
    short = mf.strength_factor(up.iloc[:130])  # 가능한 구간(63·126)만 가중치를 100% 로 다시 맞춘다
    assert short is not None and short > 0


def test_quadrant_labels():
    assert mf.quadrant(105, 103) == mf.QUADRANT_LEADING
    assert mf.quadrant(105, 97) == mf.QUADRANT_WEAKENING
    assert mf.quadrant(95, 97) == mf.QUADRANT_LAGGING
    assert mf.quadrant(95, 103) == mf.QUADRANT_IMPROVING


def test_rs_ratio_momentum_needs_enough_history():
    px = _prices(40)
    assert mf.rs_ratio_momentum(px["AAA"], px["SPY"]) is None
    px = _prices(300)
    out = mf.rs_ratio_momentum(px["AAA"], px["SPY"])
    assert out is not None and {"rs_ratio", "rs_momentum"} <= set(out.columns)


# ----------------------------------------------------------------- 시장 표
def test_market_table_ranks_leader_above_laggard_and_flow_sign():
    idx = _bdays(400)
    spy = pd.Series(np.linspace(100, 110, 400), index=idx)
    strong = pd.Series(np.linspace(100, 160, 400), index=idx)
    weak = pd.Series(np.linspace(100, 70, 400), index=idx)
    close = pd.DataFrame({"SPY": spy, "XLE": strong, "XLK": weak})
    volume = pd.DataFrame({
        "SPY": 1e6, "XLE": np.r_[np.full(280, 1e6), np.full(120, 3e6)], "XLK": np.r_[np.full(280, 1e6), np.full(120, 0.4e6)],
    }, index=idx)
    t = mf.compute_market_table(close, volume).set_index("ticker")
    assert t.loc["XLE", "rs_score"] > t.loc["SPY", "rs_score"] > t.loc["XLK", "rs_score"]
    assert t.loc["XLE", "flow_score"] > 0 > t.loc["XLK", "flow_score"]
    # 선형 상승은 비율의 증가율이 줄어 모멘텀이 100 아래일 수 있으므로 수준(RS-Ratio)만 확인한다.
    assert t.loc["XLE", "rs_ratio"] > 100 > t.loc["XLK", "rs_ratio"]
    assert t.loc["XLE", "quadrant"] in (mf.QUADRANT_LEADING, mf.QUADRANT_WEAKENING)
    assert t.loc["XLK", "quadrant"] in (mf.QUADRANT_LAGGING, mf.QUADRANT_IMPROVING)
    assert t.loc["XLK", "drawdown_52w"] < 0


def test_market_table_without_volume_and_without_benchmark():
    close = _prices(400)
    t = mf.compute_market_table(close, None)
    assert t["dollar_vol_change"].isna().all() and np.isfinite(t["flow_score"]).all()
    assert mf.compute_market_table(close.drop(columns="SPY"), None).empty


# ----------------------------------------------------------------- 상관
def test_correlation_matrix_and_shift_detect_decoupling():
    rng = np.random.default_rng(3)
    n = 600
    idx = _bdays(n)
    common = rng.normal(0, 0.01, n)
    a = common + rng.normal(0, 0.002, n)
    b_noise = rng.normal(0, 0.01, n)
    b = np.where(np.arange(n) < n - 60, common, b_noise)  # 마지막 60일은 따로 움직임
    close = pd.DataFrame({"A": 100 * np.exp(np.cumsum(a)), "B": 100 * np.exp(np.cumsum(b))}, index=idx)
    assert mf.correlation_matrix(close, 252).loc["A", "B"] > 0.6  # 마지막 60일이 섞여 있어 0.7 에는 못 미친다
    assert mf.correlation_matrix(close, 60).loc["A", "B"] < 0.5
    assert mf.correlation_shift(close, 60, 252).loc["A", "B"] < -0.3
    moves = mf.top_correlation_moves(close, 60, 252, n=3)
    assert len(moves) == 1 and moves.loc[0, "change"] < -0.3
    pair = mf.rolling_pair_correlation(close, "A", "B", 60)
    assert pair.iloc[0] > 0.9 and pair.iloc[-1] < 0.5


def test_correlation_matrix_drops_assets_with_too_few_observations():
    close = _prices(400)
    close.loc[close.index[:-30], "CCC"] = np.nan  # 최근 30일만 있는 자산
    corr = mf.correlation_matrix(close, 120)
    assert "CCC" not in corr.columns and "AAA" in corr.columns


def test_diversifier_candidates_prefers_strong_and_uncorrelated():
    rng = np.random.default_rng(7)
    n = 500
    idx = _bdays(n)
    base = rng.normal(0, 0.01, n)
    close = pd.DataFrame({
        "SPY": 100 * np.exp(np.cumsum(base * 0.5 + rng.normal(0, 0.005, n))),
        "WEAK": 100 * np.exp(np.cumsum(base - 0.0008)),
        "CORR": 100 * np.exp(np.cumsum(base + 0.0006)),
        "DIV": 100 * np.exp(np.cumsum(-base + 0.0006)),
    }, index=idx)
    table = mf.compute_market_table(close, None)
    cands = mf.diversifier_candidates(table, close, "WEAK", window=120)
    assert "WEAK" not in set(cands["ticker"])
    assert cands.iloc[0]["ticker"] == "DIV"  # 같은 상승 강도라도 약한 자산과 반대로 움직이는 쪽이 먼저


# ----------------------------------------------------------------- 조건부 검정
def _regime_world(effect: float, n: int = 3000, seed: int = 11) -> pd.DataFrame:
    """SRC 가 20일 하위 구간으로 빠진 뒤 20일 동안 TARGET 만 `effect` 만큼 더 오르게 심은 세계."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-10-29", periods=n)
    spy_r = rng.normal(0.0003, 0.008, n)
    src_r = rng.normal(0.0003, 0.012, n)
    tgt_r = rng.normal(0.0003, 0.008, n)
    other_r = rng.normal(0.0003, 0.008, n)
    src = 100 * np.cumprod(1 + src_r)
    s = pd.Series(src, index=idx)
    ret20 = (s / s.shift(20) - 1)
    thr = ret20.expanding(min_periods=252).quantile(0.10)
    trigger = ((ret20 <= thr) & thr.notna()).to_numpy()
    last = -10**9
    for i in np.flatnonzero(trigger):
        if i - last >= 20 and i + 20 < n:
            tgt_r[i + 1:i + 21] += effect / 20
            last = i
    return pd.DataFrame({
        "SPY": 100 * np.cumprod(1 + spy_r), "SRC": src,
        "TARGET": 100 * np.cumprod(1 + tgt_r), "OTHER": 100 * np.cumprod(1 + other_r),
    }, index=idx)


def test_conditional_study_finds_planted_effect():
    res = mf.conditional_forward_excess(_regime_world(effect=0.05), "SRC").set_index("ticker")
    assert res.loc["TARGET", "mean_excess"] > 2.0  # %p
    assert bool(res.loc["TARGET", "significant_raw"])
    assert not bool(res.loc["OTHER", "significant_bonferroni"])
    assert res.loc["TARGET", "episodes"] >= mf.MIN_EPISODES_FOR_STAT


def test_conditional_study_null_world_has_no_bonferroni_hits():
    hits = 0
    for seed in range(5):
        res = mf.conditional_forward_excess(_regime_world(effect=0.0, seed=seed), "SRC")
        hits += int(res["significant_bonferroni"].sum())
    assert hits == 0


def test_conditional_study_episodes_do_not_overlap_and_use_no_future_information():
    world = _regime_world(effect=0.0)
    res = mf.conditional_forward_excess(world, "SRC", horizon=20)
    dates = res.attrs["episode_dates"]
    pos = [world.index.get_loc(d) for d in dates]
    assert all(b - a >= 20 for a, b in zip(pos, pos[1:]))
    # 미래 가격을 바꿔도 이미 지난 트리거 날짜는 달라지지 않는다(확장 분포만 사용).
    cut = pos[len(pos) // 2]
    altered = world.copy()
    altered.iloc[cut + 1:, altered.columns.get_loc("SRC")] *= 5.0
    res2 = mf.conditional_forward_excess(altered, "SRC", horizon=20)
    kept = [d for d in res2.attrs["episode_dates"] if d <= world.index[cut]]
    assert kept == [d for d in dates if d <= world.index[cut]]


def test_conditional_study_edge_cases():
    world = _regime_world(effect=0.0)
    assert mf.conditional_forward_excess(world, "MISSING").empty
    assert mf.conditional_forward_excess(world.iloc[:300], "SRC").empty  # 이력 부족


def test_conditional_study_hides_stats_when_too_few_episodes():
    world = _regime_world(effect=0.0, n=1200)
    res = mf.conditional_forward_excess(world, "SRC", quantile=0.001, min_history=504)
    if not res.empty:
        few = res[res["episodes"] < mf.MIN_EPISODES_FOR_STAT]
        assert few["mean_excess"].isna().all() and not few["significant_raw"].any()


# ----------------------------------------------------------------- 로더
def test_last_complete_date_excludes_unfinished_us_session():
    et = mf.ET
    assert mf.last_complete_date(datetime(2026, 10, 30, 11, 0, tzinfo=et)).isoformat() == "2026-10-29"
    assert mf.last_complete_date(datetime(2026, 10, 30, 16, 14, tzinfo=et)).isoformat() == "2026-10-29"
    assert mf.last_complete_date(datetime(2026, 10, 30, 16, 15, tzinfo=et)).isoformat() == "2026-10-30"
    assert mf.last_complete_date(datetime(2026, 10, 31, 11, 0, tzinfo=et)).isoformat() == "2026-10-31"  # 토요일


def _fake_loader(frames):
    return lambda tickers, start=None, end=None, interval="1d": {t: frames.get(t, pd.DataFrame()) for t in tickers}


def test_load_universe_drops_incomplete_bar_missing_tickers_and_aligns_weekends():
    idx_us = pd.bdate_range(end="2026-10-30", periods=10)
    idx_all = pd.date_range(end="2026-10-30", periods=14, freq="D")  # 암호화폐는 주말에도
    frames = {
        "SPY": pd.DataFrame({"Close": np.linspace(100, 110, 10), "Volume": 1e6}, index=idx_us),
        "BTC-USD": pd.DataFrame({"Close": np.linspace(50, 60, 14), "Volume": 5e5}, index=idx_all),
    }
    close, volume, missing = mf.load_universe(
        ["SPY", "BTC-USD", "QQQ"], loader=_fake_loader(frames), now_et=datetime(2026, 10, 30, 11, 0, tzinfo=mf.ET))
    assert missing == ["QQQ"]
    assert close.index.max() == pd.Timestamp("2026-10-29")  # 오늘(미완성) 봉 제외
    assert set(close.index) <= set(idx_us)  # SPY 거래일에 정렬
    assert not close["BTC-USD"].isna().all()


# ----------------------------------------------------------------- 주도주
def test_price_leaders_rank_and_skip_bad_inputs():
    idx = _bdays(300)
    hist = {
        "UP": pd.DataFrame({"Close": np.linspace(100, 250, 300)}, index=idx),
        "FLAT": pd.DataFrame({"Close": np.full(300, 100.0)}, index=idx),
        "DOWN": pd.DataFrame({"Close": np.linspace(100, 50, 300)}, index=idx),
        "EMPTY": pd.DataFrame(),
        "SHORT": pd.DataFrame({"Close": np.linspace(1, 2, 20)}, index=idx[:20]),
    }
    out = mf.price_leaders(["UP", "FLAT", "DOWN", "EMPTY", "SHORT", "NOPE"], hist, top_n=2)
    assert out["ticker"].tolist() == ["UP", "FLAT"]
    assert mf.price_leaders(["EMPTY"], hist).empty


def test_leader_candidates_rules():
    assert mf.leader_candidates("TLT")[0] == []  # 채권은 개별 종목 주도주 없음
    cands, source = mf.leader_candidates("EWY")
    assert "005930.KS" in cands and "프리셋" in source
    assert mf.leader_candidates("SMH")[0]  # 반도체 테마 후보
    assert mf.leader_candidates("ZZZZ")[0] == []


def test_normalized_returns_starts_at_zero():
    close = _prices(300)
    out = mf.normalized_returns(close, ["AAA", "SPY", "MISSING"], 60)
    assert list(out.columns) == ["AAA", "SPY"] and (out.iloc[0] == 0).all() and len(out) == 61


def test_universe_has_benchmark_and_unique_tickers():
    tickers = mf.all_tickers()
    assert mf.BENCHMARK in tickers and len(tickers) == len(set(tickers)) == 34
    assert set(mf.ticker_names()) == set(tickers) == set(mf.ticker_groups())


# ----------------------------------------------------------------- 화면
def test_view_renders_every_section_with_synthetic_data(monkeypatch, tmp_path):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    rng = np.random.default_rng(5)
    tickers = mf.all_tickers()
    idx = pd.bdate_range(end="2026-10-29", periods=900)
    close = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0004, 0.01, 900)) for t in tickers}, index=idx)
    volume = pd.DataFrame({t: rng.uniform(1e6, 2e6, 900) for t in tickers}, index=idx)
    monkeypatch.setattr(mf, "load_universe", lambda *a, **k: (close, volume, []))
    hist = {t: pd.DataFrame({"Close": 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, 400))}, index=idx[-400:])
            for t in ("XOM", "CVX", "COP", "OXY", "EOG", "DVN", "FANG", "APA", "MRO", "HES")}
    import core.market_data as md

    monkeypatch.setattr(md, "get_multiple_price_history", lambda tickers, **k: {t: hist.get(t, pd.DataFrame()) for t in tickers})
    monkeypatch.setattr("core.db.init_db", lambda: None)

    view = Path(__file__).resolve().parents[1] / "app/views/17_시장_자금흐름.py"
    at = AppTest.from_file(str(view), default_timeout=120).run()
    assert not at.exception
    for section in ("📍 한눈에", "🔄 로테이션 맵", "🔗 상관 지도", "🏆 주도주·수익률", "🧪 가설 검증"):
        at.session_state["market_flow_section"] = section
        at.run()
        assert not at.exception, (section, at.exception[0].value if at.exception else None)
    assert any("보정 후 유의" in m.label for m in at.metric)
