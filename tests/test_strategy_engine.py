"""core/strategy_engine.py, core/indicators.py 단위 테스트 (합성 데이터 사용, 네트워크 불필요)."""

import numpy as np
import pandas as pd

import core.strategy_engine as strategy_engine
from core.indicators import (
    compute_bbw,
    compute_bbw_squeeze_release,
    compute_bollinger,
    compute_double_pattern,
    compute_engulfing,
    compute_highest_high,
    compute_ichimoku,
    compute_lowest_low,
    compute_ma_cross,
    compute_macd,
    compute_mfi,
    compute_percent_b,
    compute_rsi,
    compute_rsi_divergence,
)
from core.strategy_engine import (
    combine_conditions,
    extract_staged_trades,
    extract_trades,
    generate_positions,
    is_expression_config,
    is_staged_config,
    simulate_staged_positions,
)


def _make_engulfing_df():
    """상승 인걸(1번 인덱스)과 하락 인걸(2번 인덱스) 패턴이 확실히 나오는 합성 OHLC."""
    idx = pd.bdate_range("2022-01-03", periods=5)
    opens = [10, 7, 12, 6.5, 6.2]
    closes = [8, 11, 6, 6.2, 6.5]
    highs = [max(o, c) + 0.5 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 0.5 for o, c in zip(opens, closes)]
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Adj Close": closes, "Volume": 1_000_000},
        index=idx,
    )


def _make_trending_df(n=200, start_price=100.0, seed=0):
    """상승 후 하락하는 합성 OHLCV DataFrame (지표 계산 검증용)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    # 앞부분은 상승 추세, 뒷부분은 하락 추세로 만들어 골든/데드 크로스가 확실히 발생하게 함
    trend = np.concatenate([np.linspace(0, 40, n // 2), np.linspace(40, -20, n - n // 2)])
    noise = rng.normal(0, 0.5, n)
    close = start_price + trend + noise
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )
    return df


def test_compute_ma_cross_produces_golden_and_dead_signals():
    df = _make_trending_df()
    cross = compute_ma_cross(df, short=10, long=30)
    assert cross["cross_up"].sum() >= 1  # 상승 추세 구간에서 골든크로스가 최소 1번 발생
    assert cross["cross_down"].sum() >= 1  # 하락 추세 구간에서 데드크로스가 최소 1번 발생


def test_compute_rsi_range():
    df = _make_trending_df()
    rsi = compute_rsi(df, period=14)
    valid = rsi.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_compute_bollinger_bands_order():
    df = _make_trending_df()
    bb = compute_bollinger(df, period=20, std_dev=2.0)
    valid = bb.dropna()
    assert (valid["upper"] >= valid["mid"]).all()
    assert (valid["mid"] >= valid["lower"]).all()


def test_compute_bbw_and_percent_b_consistent_with_bands():
    df = _make_trending_df()
    bb = compute_bollinger(df, period=20, std_dev=2.0)
    bbw = compute_bbw(df, period=20, std_dev=2.0)
    pb = compute_percent_b(df, period=20, std_dev=2.0)
    valid_idx = bb.dropna().index
    expected_bbw = (bb.loc[valid_idx, "upper"] - bb.loc[valid_idx, "lower"]) / bb.loc[valid_idx, "mid"]
    expected_pb = (df.loc[valid_idx, "Close"] - bb.loc[valid_idx, "lower"]) / (
        bb.loc[valid_idx, "upper"] - bb.loc[valid_idx, "lower"]
    )
    assert np.allclose(bbw.loc[valid_idx], expected_bbw)
    assert np.allclose(pb.loc[valid_idx], expected_pb)


def test_compute_mfi_range():
    df = _make_trending_df()
    mfi = compute_mfi(df, period=14)
    valid = mfi.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_compute_lowest_low_and_highest_high():
    df = _make_trending_df(n=40)
    lowest = compute_lowest_low(df, period=5)
    highest = compute_highest_high(df, period=5)
    valid_idx = lowest.dropna().index
    for i in range(5, len(df)):
        day = df.index[i]
        if day not in valid_idx:
            continue
        window = df["Low"].iloc[i - 4 : i + 1]
        assert lowest.loc[day] == window.min()
        window_h = df["High"].iloc[i - 4 : i + 1]
        assert highest.loc[day] == window_h.max()


def _make_squeeze_release_df():
    """변동성이 좁아졌다가(스퀴즈) 급격히 확대되는 합성 OHLCV (밴드폭 스퀴즈 해제 검증용)."""
    n = 80
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(7)
    close = np.concatenate(
        [
            100 + rng.normal(0, 2.0, 30),  # 변동성 높은 구간
            100 + rng.normal(0, 0.05, 30),  # 스퀴즈 구간(변동성 극도로 축소)
            np.linspace(100, 130, 20),  # 스퀴즈 해제 후 강한 추세 시작(밴드폭 급확대)
        ]
    )
    return pd.DataFrame(
        {"Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close, "Adj Close": close, "Volume": 1_000_000},
        index=idx,
    )


def test_compute_bbw_squeeze_release_fires_after_squeeze():
    df = _make_squeeze_release_df()
    release = compute_bbw_squeeze_release(df, period=10, std_dev=2.0, threshold=0.05, lookback=15, hold_bars=3)
    assert release.sum() >= 1
    # 스퀴즈 구간(변동성 극도로 낮은 초반 구간) 자체에서는 아직 "해제"가 아니므로 뜨지 않아야 한다
    assert not release.iloc[35:50].any()


def _make_double_bottom_df():
    """쌍바닥(bullish) 반전 패턴이 나오도록 설계한 합성 OHLCV."""
    n = 95
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(1)
    close = np.concatenate(
        [
            np.linspace(100, 100, 20),
            np.linspace(100, 70, 15),  # 첫 저점(밴드 밖으로 크게 이탈)
            np.linspace(70, 90, 10),  # 반등
            np.linspace(90, 80, 10),  # 두 번째 저점(밴드 안쪽, 더 얕음)
            np.linspace(80, 80, 5),
            np.linspace(80, 110, 15),  # 강한 반등(중심선 상향 돌파)
            np.linspace(110, 110, 20),
        ]
    )
    close = close[:n] + rng.normal(0, 0.3, n)
    volume = np.full(n, 1_000_000.0)
    volume[60:65] = 5_000_000.0  # 확인 돌파 시 거래량 급증
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Adj Close": close, "Volume": volume},
        index=idx,
    )


def _make_double_top_df():
    """쌍봉(bearish) 반전 패턴이 나오도록 설계한 합성 OHLCV (쌍바닥과 대칭)."""
    n = 95
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(3)
    close = np.concatenate(
        [
            np.linspace(100, 100, 20),
            np.linspace(100, 130, 15),  # 첫 고점(밴드 밖)
            np.linspace(130, 110, 10),  # 되돌림
            np.linspace(110, 122, 10),  # 두 번째 고점(밴드 안, 더 낮음)
            np.linspace(122, 122, 5),
            np.linspace(122, 90, 15),  # 강한 하락(중심선 하향 돌파)
            np.linspace(90, 90, 20),
        ]
    )
    close = close[:n] + rng.normal(0, 0.3, n)
    volume = np.full(n, 1_000_000.0)
    volume[60:65] = 5_000_000.0
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Adj Close": close, "Volume": volume},
        index=idx,
    )


def test_compute_double_pattern_detects_bullish_and_bearish():
    bullish_df = _make_double_bottom_df()
    pat = compute_double_pattern(bullish_df, band_period=10, band_std=2.0, pivot_lookback=3, pattern_window=40, volume_mult=1.5)
    assert pat["bullish"].sum() >= 1
    assert pat["bearish"].sum() == 0

    bearish_df = _make_double_top_df()
    pat2 = compute_double_pattern(bearish_df, band_period=10, band_std=2.0, pivot_lookback=3, pattern_window=40, volume_mult=1.5)
    assert pat2["bearish"].sum() >= 1
    assert pat2["bullish"].sum() == 0


def _make_divergence_df():
    """가격은 저점을 낮추지만 RSI는 저점을 높이는(상승 다이버전스) 합성 OHLCV."""
    n = 95
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(2)
    close = np.concatenate(
        [
            np.linspace(100, 100, 15),
            np.linspace(100, 60, 20),  # 첫 급락(가파름 -> RSI 크게 하락)
            np.linspace(60, 75, 10),  # 반등
            np.linspace(75, 55, 20),  # 두 번째 하락(가격은 더 낮지만 완만함 -> RSI는 덜 하락)
            np.linspace(55, 55, 5),  # 저점 확정 시간을 벌어주는 바닥 다지기
            np.linspace(55, 90, 15),  # 강한 반등(중심선 상향 돌파)
            np.linspace(90, 90, 10),
        ]
    )
    close = close[:n] + rng.normal(0, 0.2, n)
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Adj Close": close, "Volume": 1_000_000},
        index=idx,
    )


def test_compute_rsi_divergence_detects_bullish_divergence():
    df = _make_divergence_df()
    div = compute_rsi_divergence(df, rsi_period=7, band_period=10, pivot_lookback=3, pattern_window=50)
    assert div["bullish"].sum() >= 1


def test_compute_engulfing_detects_bullish_and_bearish_patterns():
    df = _make_engulfing_df()
    eng = compute_engulfing(df)
    assert bool(eng["bullish"].iloc[1]) is True
    assert bool(eng["bearish"].iloc[2]) is True
    # 패턴이 아닌 자리에서는 False여야 한다
    assert bool(eng["bullish"].iloc[0]) is False
    assert bool(eng["bearish"].iloc[1]) is False


def test_engulfing_condition_via_combine_conditions():
    df = _make_engulfing_df()
    bullish_signal = combine_conditions(
        df, {"logic": "AND", "conditions": [{"indicator": "engulfing", "direction": "bullish"}]}
    )
    bearish_signal = combine_conditions(
        df, {"logic": "AND", "conditions": [{"indicator": "engulfing", "direction": "bearish"}]}
    )
    assert bool(bullish_signal.iloc[1]) is True
    assert bool(bearish_signal.iloc[2]) is True


def test_bollinger_mid_band_condition_via_combine_conditions():
    df = _make_trending_df()
    up = combine_conditions(
        df, {"logic": "AND", "conditions": [{"indicator": "bollinger", "band": "mid", "op": "break_above"}]}
    )
    down = combine_conditions(
        df, {"logic": "AND", "conditions": [{"indicator": "bollinger", "band": "mid", "op": "break_below"}]}
    )
    bb = compute_bollinger(df, period=20, std_dev=2.0)
    assert (up == (df["Close"] > bb["mid"]).fillna(False)).all()
    assert (down == (df["Close"] < bb["mid"]).fillna(False)).all()


def test_percent_b_and_mfi_conditions_via_combine_conditions():
    df = _make_trending_df()
    pb_signal = combine_conditions(
        df, {"logic": "AND", "conditions": [{"indicator": "percent_b", "op": ">=", "value": 0.8}]}
    )
    mfi_signal = combine_conditions(
        df, {"logic": "AND", "conditions": [{"indicator": "mfi", "op": ">=", "value": 80}]}
    )
    pb = compute_percent_b(df, period=20, std_dev=2.0)
    mfi = compute_mfi(df, period=14)
    assert (pb_signal == (pb >= 0.8).fillna(False)).all()
    assert (mfi_signal == (mfi >= 80).fillna(False)).all()


def test_bbw_squeeze_release_condition_via_combine_conditions():
    df = _make_squeeze_release_df()
    signal = combine_conditions(
        df,
        {
            "logic": "AND",
            "conditions": [
                {"indicator": "bbw_squeeze_release", "period": 10, "std_dev": 2.0, "threshold": 0.05, "lookback": 15, "hold_bars": 3}
            ],
        },
    )
    expected = compute_bbw_squeeze_release(df, period=10, std_dev=2.0, threshold=0.05, lookback=15, hold_bars=3)
    assert (signal == expected).all()


def test_double_pattern_and_rsi_divergence_conditions_via_combine_conditions():
    bullish_df = _make_double_bottom_df()
    signal = combine_conditions(
        df=bullish_df,
        indicator_config={
            "logic": "AND",
            "conditions": [
                {"indicator": "double_pattern", "direction": "bullish", "band_period": 10, "pivot_lookback": 3, "pattern_window": 40}
            ],
        },
    )
    assert signal.sum() >= 1

    div_df = _make_divergence_df()
    div_signal = combine_conditions(
        df=div_df,
        indicator_config={
            "logic": "AND",
            "conditions": [
                {"indicator": "rsi_divergence", "direction": "bullish", "rsi_period": 7, "band_period": 10, "pivot_lookback": 3, "pattern_window": 50}
            ],
        },
    )
    assert div_signal.sum() >= 1


def test_combine_conditions_and_logic():
    df = _make_trending_df()
    config = {
        "logic": "AND",
        "conditions": [
            {"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"},
            {"indicator": "rsi", "period": 14, "op": ">", "value": 40},
        ],
    }
    combined = combine_conditions(df, config)
    assert combined.dtype == bool
    # AND 결합이므로 개별 조건보다 True 인 날의 수가 같거나 적어야 한다
    golden_only = combine_conditions(df, {"logic": "AND", "conditions": [config["conditions"][0]]})
    assert combined.sum() <= golden_only.sum()


def test_combine_conditions_empty_returns_all_false():
    df = _make_trending_df()
    combined = combine_conditions(df, {"logic": "AND", "conditions": []})
    assert not combined.any()


def test_is_expression_config_detects_expression_key():
    assert is_expression_config({"expression": "close > 0"}) is True
    assert is_expression_config({"logic": "AND", "conditions": []}) is False
    assert is_expression_config({"entry_stages": []}) is False


def test_generate_positions_dispatches_to_expression_engine():
    df = _make_trending_df()
    config = {"expression": "close > sma(close, 20)"}
    position = generate_positions(df, config)
    from core.indicators import sma

    expected = (df["Close"] > sma(df["Close"], 20)).fillna(False).astype(int)
    assert (position == expected).all()


def test_generate_positions_and_extract_trades_roundtrip():
    df = _make_trending_df()
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 10, "long": 30, "type": "golden"}]}
    position = generate_positions(df, config)
    assert set(position.unique()).issubset({0, 1})

    trades = extract_trades(df, position)
    # 매매가 있었다면 각 트레이드의 청산일이 진입일보다 이후여야 한다
    for t in trades:
        if t.exit_date is not None:
            assert t.exit_date >= t.entry_date
        assert t.return_pct is not None


def _make_flat_df(n=6):
    """모든 조건 신호를 combine_conditions 몫으로 완전히 통제하기 위한, 값 자체는 의미 없는 합성 DF."""
    idx = pd.bdate_range("2022-01-03", periods=n)
    close = [100.0] * n
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Adj Close": close, "Volume": 1},
        index=idx,
    )


def _patch_combine_conditions_sequence(monkeypatch, series_list):
    """simulate_staged_positions 내부의 combine_conditions 호출을 호출 순서대로 지정한 Series로 대체한다.

    entry_stages 조건들이 먼저(순서대로), 그다음 exit_stages 조건들이(순서대로), emergency_exit이
    있으면 마지막에 딱 한 번씩만 호출되는 구현 순서에 의존한다(함수 최상단에서 리스트 컴프리헨션으로
    한 번씩만 호출됨).
    """
    call_order = iter(series_list)
    monkeypatch.setattr(strategy_engine, "combine_conditions", lambda df_arg, cfg: next(call_order))


def test_simulate_staged_positions_last_exit_stage_closes_tag_beyond_exit_stage_count(monkeypatch):
    """entry_stages(3개) > exit_stages(2개)이고 마지막 진입 단계로 직행해 태그 인덱스(3)가 exit_stages
    범위를 벗어나도, 마지막 청산 단계 신호가 뜨면 emergency_exit 없이도 잔량이 정리돼야 한다.

    수정 전에는 exit 루프가 range(1, n_exit+1)=range(1,3)까지만 태그를 확인해 태그 3은 절대
    매칭되지 않았고, "마지막 단계면 잔량 전부 정리" 로직도 그 태그 자신이 열려있을 때만 도달 가능해
    이 케이스에서 포지션이 emergency_exit 없이는 백테스트 끝까지 안 닫히는 버그가 있었다.
    """
    df = _make_flat_df(6)
    idx = df.index
    all_false = pd.Series([False] * 6, index=idx)
    entry3_direct = pd.Series([True, False, False, False, False, False], index=idx)  # day0에 3단계 직행
    exit2_fires = pd.Series([False, False, False, True, False, False], index=idx)  # day3에 마지막 청산 신호

    _patch_combine_conditions_sequence(
        monkeypatch,
        [all_false, all_false, entry3_direct, all_false, exit2_fires],  # entry1,entry2,entry3,exit1,exit2
    )

    config = {
        "entry_stages": [
            {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "x1"}]},
            {"weight": 0.2, "logic": "AND", "conditions": [{"indicator": "x2"}]},
            {"weight": 0.6, "logic": "AND", "conditions": [{"indicator": "x3"}]},
        ],
        "exit_stages": [
            {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "y1"}]},
            {"weight": 0.2, "logic": "AND", "conditions": [{"indicator": "y2"}]},
        ],
    }

    weight_signal, events = simulate_staged_positions(df, config)

    assert weight_signal.iloc[0] == 0.6  # 3단계 직행 진입 직후 비중
    assert weight_signal.iloc[3] == 0.0  # 마지막 청산 단계 신호로 잔량(태그3)까지 정리됨
    exit_events = [e for e in events if e.kind == "exit"]
    assert len(exit_events) == 1
    assert exit_events[0].stage == 3
    assert exit_events[0].weight == 0.6


def test_simulate_staged_positions_partial_exit_only_closes_matching_tag(monkeypatch):
    """마지막이 아닌 청산 단계는 자신과 인덱스가 같은 진입 태그만 개별적으로 정리해야 한다."""
    df = _make_flat_df(6)
    idx = df.index
    all_false = pd.Series([False] * 6, index=idx)
    entry1_day0 = pd.Series([True, False, False, False, False, False], index=idx)
    entry2_day1 = pd.Series([False, True, False, False, False, False], index=idx)
    exit1_day3 = pd.Series([False, False, False, True, False, False], index=idx)

    _patch_combine_conditions_sequence(
        monkeypatch,
        [entry1_day0, entry2_day1, all_false, exit1_day3, all_false],  # entry1,entry2,entry3,exit1,exit2
    )

    config = {
        "entry_stages": [
            {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "x1"}]},
            {"weight": 0.2, "logic": "AND", "conditions": [{"indicator": "x2"}]},
            {"weight": 0.6, "logic": "AND", "conditions": [{"indicator": "x3"}]},
        ],
        "exit_stages": [
            {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "y1"}]},
            {"weight": 0.2, "logic": "AND", "conditions": [{"indicator": "y2"}]},
        ],
    }

    weight_signal, events = simulate_staged_positions(df, config)

    assert round(weight_signal.iloc[2], 9) == 0.3  # 1+2단계 진입 완료 후(청산 전) 비중
    assert round(weight_signal.iloc[3], 9) == 0.2  # 1단계 태그만 청산되고 2단계는 유지
    exit_events = [e for e in events if e.kind == "exit"]
    assert len(exit_events) == 1
    assert exit_events[0].stage == 1
    assert exit_events[0].weight == 0.1


def test_simulate_staged_positions_emergency_exit_clears_all_tags_regardless_of_stage(monkeypatch):
    df = _make_flat_df(6)
    idx = df.index
    all_false = pd.Series([False] * 6, index=idx)
    entry1_day0 = pd.Series([True, False, False, False, False, False], index=idx)
    entry2_day1 = pd.Series([False, True, False, False, False, False], index=idx)
    emergency_day2 = pd.Series([False, False, True, False, False, False], index=idx)

    _patch_combine_conditions_sequence(
        monkeypatch,
        # entry1,entry2,entry3,exit1,exit2,emergency
        [entry1_day0, entry2_day1, all_false, all_false, all_false, emergency_day2],
    )

    config = {
        "entry_stages": [
            {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "x1"}]},
            {"weight": 0.2, "logic": "AND", "conditions": [{"indicator": "x2"}]},
            {"weight": 0.6, "logic": "AND", "conditions": [{"indicator": "x3"}]},
        ],
        "exit_stages": [
            {"weight": 0.1, "logic": "AND", "conditions": [{"indicator": "y1"}]},
            {"weight": 0.2, "logic": "AND", "conditions": [{"indicator": "y2"}]},
        ],
        "emergency_exit": {"logic": "AND", "conditions": [{"indicator": "z"}]},
    }

    weight_signal, events = simulate_staged_positions(df, config)

    assert round(weight_signal.iloc[2], 9) == 0.0
    emergency_events = [e for e in events if e.kind == "emergency_exit"]
    assert {e.stage for e in emergency_events} == {1, 2}
    assert round(sum(e.weight for e in emergency_events), 9) == 0.3


def test_simulate_staged_positions_stop_loss_snapshots_level_at_entry_and_liquidates(monkeypatch):
    """stop_loss는 진입 사이클 시작 바에서 레벨을 스냅샷하고, 이후 종가가 그 아래로 내려오면
    (exit_stages 신호와 무관하게) 즉시 전량 청산해야 한다."""
    idx = pd.bdate_range("2022-01-03", periods=6)
    df = pd.DataFrame(
        {
            "Open": [100.0, 100.0, 100.0, 95.0, 96.0, 97.0],
            "High": [100.0, 100.0, 100.0, 95.0, 96.0, 97.0],
            "Low": [100.0, 100.0, 90.0, 90.0, 90.0, 90.0],
            "Close": [100.0, 100.0, 100.0, 95.0, 96.0, 97.0],
            "Adj Close": [100.0, 100.0, 100.0, 95.0, 96.0, 97.0],
            "Volume": 1,
        },
        index=idx,
    )
    entry1_day1 = pd.Series([False, True, False, False, False, False], index=idx)
    _patch_combine_conditions_sequence(monkeypatch, [entry1_day1])  # entry_stages 1개, exit_stages 없음

    config = {
        "entry_stages": [{"weight": 1.0, "logic": "AND", "conditions": [{"indicator": "x1"}]}],
        "stop_loss": {"source": "lowest_low", "period": 2},
    }

    weight_signal, events = simulate_staged_positions(df, config)

    # day1 진입 시점의 lowest_low(period=2, [Low0,Low1]=[100,100]의 최소) = 100.0 이 손절 레벨로 고정됨
    assert weight_signal.iloc[1] == 1.0
    assert weight_signal.iloc[2] == 1.0  # day2 종가(100)는 손절 레벨(100) 아래가 아니므로 유지
    assert weight_signal.iloc[3] == 0.0  # day3 종가(95) < 손절 레벨(100) -> 즉시 전량 청산

    stop_events = [e for e in events if e.kind == "stop_loss"]
    assert len(stop_events) == 1
    assert stop_events[0].stage == 1
    assert stop_events[0].weight == 1.0
    assert stop_events[0].date == idx[3]


def test_simulate_staged_positions_without_stop_loss_key_is_unaffected(monkeypatch):
    """stop_loss 키가 없으면 기존 동작 그대로(무기한 보유, exit_stages/emergency_exit만으로 청산)여야 한다."""
    idx = pd.bdate_range("2022-01-03", periods=6)
    df = pd.DataFrame(
        {
            "Open": [100.0] * 6,
            "High": [100.0] * 6,
            "Low": [100.0, 100.0, 90.0, 90.0, 90.0, 90.0],
            "Close": [100.0, 100.0, 100.0, 95.0, 96.0, 97.0],
            "Adj Close": [100.0, 100.0, 100.0, 95.0, 96.0, 97.0],
            "Volume": 1,
        },
        index=idx,
    )
    entry1_day1 = pd.Series([False, True, False, False, False, False], index=idx)
    _patch_combine_conditions_sequence(monkeypatch, [entry1_day1])

    config = {"entry_stages": [{"weight": 1.0, "logic": "AND", "conditions": [{"indicator": "x1"}]}]}
    weight_signal, events = simulate_staged_positions(df, config)

    assert weight_signal.iloc[3] == 1.0  # stop_loss가 없으니 종가가 내려가도 계속 보유
    assert not any(e.kind == "stop_loss" for e in events)


def test_extract_staged_trades_matches_average_weighted_prices():
    df = _make_flat_df(6)
    df = df.copy()
    df["Close"] = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    events = [
        strategy_engine.StageEvent(df.index[0], "entry", 1, 0.4, 100.0),
        strategy_engine.StageEvent(df.index[1], "entry", 2, 0.6, 101.0),
        strategy_engine.StageEvent(df.index[4], "exit", 2, 1.0, 104.0),
    ]
    trades = extract_staged_trades(df, events)
    assert len(trades) == 1
    trade = trades[0]
    # 체결가는 이벤트 다음 거래일 종가(lookahead 방지) — day0 다음날(101)/day1 다음날(102) 가중평균
    expected_entry = (0.4 * 101.0 + 0.6 * 102.0) / 1.0
    assert round(trade.entry_price, 6) == round(expected_entry, 6)
    assert trade.exit_price == 105.0  # day4 다음날(=마지막 인덱스) 종가
