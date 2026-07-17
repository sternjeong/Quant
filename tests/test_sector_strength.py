"""core/sector_strength.py 단위 테스트 (모듈 G 확장: 섹터/테마 강도 RS 점수).

네트워크(yfinance)를 타지 않도록 core.market_data.get_multiple_price_history 를 monkeypatch 로
대체한다.
"""

import pandas as pd
import pytest

import core.sector_strength as sector_strength


def _close_df(values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="B")
    return pd.DataFrame({"Close": values}, index=idx)


def _trend_df(n: int = 300, start: float = 100.0, daily_pct: float = 0.0) -> pd.DataFrame:
    values = [start * (1 + daily_pct / 100) ** i for i in range(n)]
    return _close_df(values)


def test_compute_theme_strength_ranks_stronger_theme_higher(monkeypatch):
    fake_prices = {
        "STRONG": _trend_df(daily_pct=0.30),
        "WEAK": _trend_df(daily_pct=-0.10),
    }
    theme_universe = {"강한테마": ["STRONG"], "약한테마": ["WEAK"]}

    def _fake_multi(tickers, start=None, end=None, interval="1d", use_cache=True):
        return {t: fake_prices[t] for t in tickers}

    monkeypatch.setattr(sector_strength, "get_multiple_price_history", _fake_multi)

    df = sector_strength.compute_theme_strength(theme_universe)
    assert list(df["theme"]) == ["강한테마", "약한테마"]
    assert df.iloc[0]["rs_score"] > df.iloc[1]["rs_score"]
    assert df.iloc[0]["strength_factor"] > df.iloc[1]["strength_factor"]


def test_compute_theme_strength_averages_multiple_proxies(monkeypatch):
    # 두 프록시(하나는 강세, 하나는 정체)를 평균하면 단일 강세 프록시보다는 약해야 한다.
    fake_prices = {
        "P1": _trend_df(daily_pct=0.30),
        "P2": _trend_df(daily_pct=0.0),
        "SOLO": _trend_df(daily_pct=0.30),
    }
    theme_universe = {"평균테마": ["P1", "P2"], "단독테마": ["SOLO"]}

    def _fake_multi(tickers, start=None, end=None, interval="1d", use_cache=True):
        return {t: fake_prices[t] for t in tickers}

    monkeypatch.setattr(sector_strength, "get_multiple_price_history", _fake_multi)

    df = sector_strength.compute_theme_strength(theme_universe)
    avg_row = df[df["theme"] == "평균테마"].iloc[0]
    solo_row = df[df["theme"] == "단독테마"].iloc[0]
    assert avg_row["strength_factor"] < solo_row["strength_factor"]


def test_compute_theme_strength_skips_theme_with_no_data(monkeypatch):
    theme_universe = {"데이터없음": ["NODATA"], "정상": ["OK"]}
    fake_prices = {"NODATA": pd.DataFrame(), "OK": _trend_df(daily_pct=0.1)}

    def _fake_multi(tickers, start=None, end=None, interval="1d", use_cache=True):
        return {t: fake_prices[t] for t in tickers}

    monkeypatch.setattr(sector_strength, "get_multiple_price_history", _fake_multi)

    df = sector_strength.compute_theme_strength(theme_universe)
    assert list(df["theme"]) == ["정상"]


def test_compute_theme_strength_trend_direction(monkeypatch):
    # 최근 20거래일 동안 급등한 시리즈: 뒤로 갈수록 강도가 높아져야 "상승" 추세로 판정
    n = 300
    values = [100.0] * (n - 20) + [100.0 * (1.02**i) for i in range(1, 21)]
    accelerating = _close_df(values)
    theme_universe = {"가속테마": ["ACCEL"]}

    monkeypatch.setattr(
        sector_strength, "get_multiple_price_history", lambda tickers, **k: {"ACCEL": accelerating}
    )

    df = sector_strength.compute_theme_strength(theme_universe)
    assert df.iloc[0]["trend"] == "상승"
    assert df.iloc[0]["trend_change"] > 0


def test_compute_theme_strength_empty_universe_returns_empty_df(monkeypatch):
    # {}는 "테마 없음"을 명시한 것이지 "기본값 써라"가 아니다 — falsy라고 프리셋으로 폴백하면
    # 네트워크를 타게 되므로, 호출 자체가 없어야 함을 함께 확인한다.
    def _fail_if_called(*a, **k):
        raise AssertionError("빈 테마 집합인데 get_multiple_price_history가 호출됨")

    monkeypatch.setattr(sector_strength, "get_multiple_price_history", _fail_if_called)

    df = sector_strength.compute_theme_strength({})
    assert df.empty
    assert list(df.columns) == [
        "theme", "proxies", "strength_factor", "rs_score", "return_3m", "return_6m", "return_12m",
        "trend", "trend_change",
    ]


def test_compute_theme_strength_handles_recently_listed_etf_with_short_history(monkeypatch):
    # 최근 상장된 ETF(예: 실제 DRAM 메모리 ETF, 2025년 상장)는 252거래일치 이력이 없을 수 있다.
    # 63거래일(3개월)치만 있어도 그 구간만으로 점수를 매겨야 한다(전체를 None으로 버리지 않음).
    short_history = _trend_df(n=70, daily_pct=0.5)  # 63거래일 ROC는 계산 가능, 126/189/252는 불가
    long_history = _trend_df(n=300, daily_pct=0.1)
    theme_universe = {"신규상장테마": ["NEWCO"], "기존테마": ["OLD"]}

    def _fake_multi(tickers, start=None, end=None, interval="1d", use_cache=True):
        return {t: (short_history if t == "NEWCO" else long_history) for t in tickers}

    monkeypatch.setattr(sector_strength, "get_multiple_price_history", _fake_multi)

    df = sector_strength.compute_theme_strength(theme_universe)
    assert set(df["theme"]) == {"신규상장테마", "기존테마"}
    new_row = df[df["theme"] == "신규상장테마"].iloc[0]
    assert new_row["strength_factor"] == pytest.approx(sector_strength.roc(short_history["Close"], 63).iloc[-1])
    assert pd.isna(new_row["return_6m"])
    assert pd.isna(new_row["return_12m"])


def test_strength_factor_returns_none_when_even_shortest_window_unavailable():
    too_short = pd.Series([100.0, 101.0, 102.0])
    assert sector_strength._strength_factor(too_short) is None


def _patch_session(monkeypatch, db_session):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(sector_strength, "get_session", _fake_get_session)


def test_get_latest_theme_strength_snapshot_returns_none_when_empty(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    assert sector_strength.get_latest_theme_strength_snapshot() is None


def test_save_and_get_latest_theme_strength_snapshot_roundtrip(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    df = pd.DataFrame(
        [
            {"theme": "반도체", "proxies": "SOXX, SMH", "strength_factor": 12.3, "rs_score": 90.0,
             "return_3m": 10.0, "return_6m": 20.0, "return_12m": 30.0, "trend": "상승"},
            {"theme": "유틸리티", "proxies": "XLU", "strength_factor": -1.0, "rs_score": 10.0,
             "return_3m": -2.0, "return_6m": None, "return_12m": None, "trend": "하락"},
        ]
    )

    row_id = sector_strength.save_theme_strength_snapshot(df)
    assert row_id is not None

    latest = sector_strength.get_latest_theme_strength_snapshot()
    assert "computed_at" in latest
    loaded = latest["theme_scores"]
    assert list(loaded["theme"]) == ["반도체", "유틸리티"]
    assert loaded.iloc[0]["rs_score"] == pytest.approx(90.0)
    assert pd.isna(loaded.iloc[1]["return_6m"])


def test_save_and_get_latest_theme_strength_snapshot_handles_empty_df(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    empty_df = pd.DataFrame(columns=sector_strength._THEME_STRENGTH_COLUMNS)

    sector_strength.save_theme_strength_snapshot(empty_df)

    latest = sector_strength.get_latest_theme_strength_snapshot()
    assert latest["theme_scores"].empty
    assert list(latest["theme_scores"].columns) == sector_strength._THEME_STRENGTH_COLUMNS


def test_get_latest_theme_strength_snapshot_returns_most_recent(db_session, monkeypatch):
    _patch_session(monkeypatch, db_session)
    sector_strength.save_theme_strength_snapshot(
        pd.DataFrame([{"theme": "OLD", "proxies": "X", "strength_factor": 1.0, "rs_score": 50.0,
                        "return_3m": 1.0, "return_6m": 1.0, "return_12m": 1.0, "trend": "횡보"}])
    )
    sector_strength.save_theme_strength_snapshot(
        pd.DataFrame([{"theme": "NEW", "proxies": "Y", "strength_factor": 2.0, "rs_score": 60.0,
                        "return_3m": 2.0, "return_6m": 2.0, "return_12m": 2.0, "trend": "상승"}])
    )

    latest = sector_strength.get_latest_theme_strength_snapshot()
    assert list(latest["theme_scores"]["theme"]) == ["NEW"]


def test_theme_universe_preset_has_expected_themes():
    assert sector_strength.THEME_UNIVERSE["메모리/DRAM"] == ["DRAM"]
    assert sector_strength.THEME_UNIVERSE["반도체"] == ["SOXX", "SMH"]
    assert set(sector_strength.THEME_UNIVERSE["우주"]) == {"UFO", "ARKX", "ROKT"}
    assert sector_strength.THEME_UNIVERSE["방산"] == ["ITA"]
    assert sector_strength.THEME_UNIVERSE["냉각"] == ["DTCR"]
    assert sector_strength.THEME_UNIVERSE["사이버보안"] == ["CIBR"]
    assert set(sector_strength.THEME_UNIVERSE["클라우드"]) == {"SKYY", "WCLD"}
    assert sector_strength.THEME_UNIVERSE["로보틱스"] == ["BOTZ"]
    # GICS 11개 + 반도체/DRAM/우주 + 방산/냉각/사이버보안/클라우드/로보틱스(2026-07-15 추가)
    assert len(sector_strength.THEME_UNIVERSE) == 19
