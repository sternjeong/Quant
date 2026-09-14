"""core/champion_strategy.py 단위 테스트.

네트워크(yfinance) 호출을 피하기 위해 get_price_history/get_universe 를 monkeypatch 해서
합성 OHLCV 데이터를 반환하도록 한다 (tests/test_backtest_engine.py와 동일한 관례).
"""

import json
import math

import numpy as np
import pandas as pd
import pytest

import core.champion_strategy as champion_strategy


def _flat_then_return_df(n: int, total_return_pct: float) -> pd.DataFrame:
    """n개 영업일짜리 합성 OHLCV. 첫 값(100)에서 마지막 값까지 선형으로 total_return_pct%만큼
    이동한다 — len(df) == lookback_days + 1로 맞추면 iloc[-1-lookback_days] == iloc[0] == 100이
    되어 모멘텀(%) 계산값을 정확히 통제할 수 있다."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = np.linspace(100.0, 100.0 * (1 + total_return_pct / 100), n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.001, "Low": close * 0.999, "Close": close, "Volume": 1_000_000},
        index=idx,
    )


def _breakout_df(n: int, breakout: bool) -> pd.DataFrame:
    """돈치안 20일 브레이크아웃 테스트용: 앞부분은 100 근처 평탄, 마지막 날만 breakout=True면
    직전 20일 고가를 확실히 돌파하는 값으로, False면 그 아래로 유지."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    if breakout:
        close[-1] = 110.0
        high[-1] = 110.5
    else:
        close[-1] = 100.5
        high[-1] = 100.6
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": close * 0.99, "Close": close, "Volume": 1_000_000}, index=idx
    )


CORE_N = champion_strategy.CORE_MOMENTUM_LOOKBACK_DAYS + 1
SPY_N = champion_strategy.MARKET_FILTER_SMA_WINDOW + 5
SATELLITE_N = max(champion_strategy.SATELLITE_DONCHIAN_WINDOW, champion_strategy.SATELLITE_MOMENTUM_LOOKBACK_DAYS) + 1


def test_compute_core_recommendation_ranks_by_momentum_and_excludes_negative(monkeypatch):
    # SPY는 200일선 위(필터 미발동)로 고정
    spy_df = _flat_then_return_df(SPY_N, total_return_pct=5.0)

    returns = {
        "XLK": 30.0, "XLY": 20.0, "XLC": 15.0, "XLV": 10.0,  # 상위 4개 후보(양의 모멘텀)
        "XLU": -5.0, "XLP": -1.0,  # 음의 모멘텀 -> 조건 미충족(절대모멘텀 필터)
    }

    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True, **kwargs):
        if ticker == "SPY":
            return spy_df.copy()
        pct = returns.get(ticker, 1.0)  # 나머지 티커는 소폭 양의 모멘텀
        return _flat_then_return_df(CORE_N, pct)

    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history)

    result = champion_strategy.compute_core_recommendation()

    assert result["above_200dma"] is True
    assert result["exposure_multiplier"] == 1.0
    assert result["cash_weight_from_filter"] == pytest.approx(0.0)
    assert set(result["top4"]) == {"XLK", "XLY", "XLC", "XLV"}
    assert "XLU" not in result["top4"]  # 음의 모멘텀은 top4 후보에서 제외

    ranked = result["ranked"]
    xlu_row = ranked[ranked["ticker"] == "XLU"].iloc[0]
    assert not xlu_row["passes_absolute_momentum"]
    assert not xlu_row["in_top4"]

    expected_weight = champion_strategy.CORE_WEIGHT / champion_strategy.CORE_TOP_N
    assert result["per_ticker_weight"] == pytest.approx(expected_weight)


def test_compute_core_recommendation_applies_market_filter_when_spy_below_200dma(monkeypatch):
    # SPY 종가가 200일 평균보다 낮아지도록(하락 추세) 구성
    spy_df = _flat_then_return_df(SPY_N, total_return_pct=-15.0)

    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True, **kwargs):
        if ticker == "SPY":
            return spy_df.copy()
        return _flat_then_return_df(CORE_N, 8.0)

    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history)

    result = champion_strategy.compute_core_recommendation()

    assert result["above_200dma"] is False
    assert result["exposure_multiplier"] == pytest.approx(champion_strategy.MARKET_FILTER_EXPOSURE_CUT)
    expected_invested = champion_strategy.CORE_WEIGHT * champion_strategy.MARKET_FILTER_EXPOSURE_CUT
    assert result["cash_weight_from_filter"] == pytest.approx(champion_strategy.CORE_WEIGHT - expected_invested)
    expected_weight = expected_invested / champion_strategy.CORE_TOP_N
    assert result["per_ticker_weight"] == pytest.approx(expected_weight)


def test_compute_core_recommendation_handles_missing_data_gracefully(monkeypatch):
    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True, **kwargs):
        if ticker == "XLK":
            return pd.DataFrame()  # 데이터 조회 실패 상황 재현
        if ticker == "SPY":
            return _flat_then_return_df(SPY_N, 3.0)
        return _flat_then_return_df(CORE_N, 2.0)

    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history)

    result = champion_strategy.compute_core_recommendation()
    xlk_row = result["ranked"][result["ranked"]["ticker"] == "XLK"].iloc[0]
    assert pd.isna(xlk_row["momentum_pct"])
    assert not xlk_row["passes_absolute_momentum"]
    assert "XLK" not in result["top4"]


def test_compute_satellite_recommendation_selects_breakouts_ranked_by_momentum(monkeypatch):
    breakout_tickers = {"AAA": 40.0, "BBB": 20.0, "CCC": 5.0}  # momentum_3m 다르게
    non_breakout_tickers = ["DDD", "EEE"]

    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True, **kwargs):
        if ticker in breakout_tickers:
            df = _breakout_df(SATELLITE_N, breakout=True)
            # 모멘텀(3개월) 차등을 주기 위해 첫 구간 가격을 낮춰 상대적 3개월 수익률을 다르게 만듦
            lookback = champion_strategy.SATELLITE_MOMENTUM_LOOKBACK_DAYS
            base_price = df["Close"].iloc[-1] / (1 + breakout_tickers[ticker] / 100)
            df.loc[df.index[-1 - lookback], "Close"] = base_price
            return df
        return _breakout_df(SATELLITE_N, breakout=False)

    universe = list(breakout_tickers.keys()) + non_breakout_tickers
    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history)

    result = champion_strategy.compute_satellite_recommendation(universe=universe)

    assert result["scanned_count"] == len(universe)
    assert set(result["selected"]) <= set(breakout_tickers.keys())
    assert "DDD" not in result["selected"]
    assert "EEE" not in result["selected"]
    # 모멘텀 내림차순 정렬 확인
    assert result["candidates"]["ticker"].tolist()[0] == "AAA"
    assert result["per_ticker_weight"] == pytest.approx(
        champion_strategy.SATELLITE_WEIGHT / len(result["selected"])
    )
    assert result["unallocated_weight"] == pytest.approx(0.0)


def test_compute_satellite_recommendation_empty_when_no_breakouts(monkeypatch):
    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True, **kwargs):
        return _breakout_df(SATELLITE_N, breakout=False)

    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history)

    result = champion_strategy.compute_satellite_recommendation(universe=["AAA", "BBB"])

    assert result["selected"] == []
    assert result["candidates"].empty
    assert result["per_ticker_weight"] == 0.0
    assert result["unallocated_weight"] == pytest.approx(champion_strategy.SATELLITE_WEIGHT)


def test_compute_satellite_recommendation_uses_get_universe_when_not_provided(monkeypatch):
    monkeypatch.setattr(champion_strategy, "get_universe", lambda: pd.DataFrame({"Symbol": ["ZZZ"]}))
    monkeypatch.setattr(
        champion_strategy, "get_price_history",
        lambda ticker, start=None, end=None, use_cache=True, **kwargs: _breakout_df(SATELLITE_N, breakout=False),
    )
    result = champion_strategy.compute_satellite_recommendation()
    assert result["scanned_count"] == 1


def test_compute_satellite_recommendation_rejects_unknown_sizing_method():
    with pytest.raises(ValueError):
        champion_strategy.compute_satellite_recommendation(universe=["AAA"], sizing_method="bogus")


# ----------------------------------------------------------------------------
# 새틀라이트 사이징(변동성 역가중) — 작업 2026-09-14 추가
# ----------------------------------------------------------------------------


def _noisy_breakout_df(n: int, daily_noise_std: float, seed: int) -> pd.DataFrame:
    """평탄한 흐름 + 마지막 날 브레이크아웃 + 지정한 일별 변동성 노이즈를 가진 합성 OHLCV.
    _breakout_df와 달리 lookback 구간에 진짜 변동성 차이를 줘서 inverse_vol 가중이 실제로
    갈라지는지 검증할 수 있게 한다."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, daily_noise_std, n)
    close = 100 * np.cumprod(1 + noise)
    close[-1] = close[-2] * 1.10  # 마지막 날 확실한 브레이크아웃
    high = close * 1.001
    high[-1] = close[-1] * 1.005
    return pd.DataFrame({"Open": close, "High": high, "Low": close * 0.999, "Close": close, "Volume": 1_000_000}, index=idx)


def test_inverse_vol_weights_favor_lower_volatility_ticker():
    histories = {
        "LOWVOL": _noisy_breakout_df(SATELLITE_N, daily_noise_std=0.002, seed=1),
        "HIGHVOL": _noisy_breakout_df(SATELLITE_N, daily_noise_std=0.05, seed=2),
    }
    weights = champion_strategy._inverse_vol_weights(histories, ["LOWVOL", "HIGHVOL"], lookback_days=60)

    assert weights["LOWVOL"] > weights["HIGHVOL"]
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)


def test_inverse_vol_weights_empty_with_fewer_than_two_tickers():
    histories = {"AAA": _noisy_breakout_df(SATELLITE_N, daily_noise_std=0.01, seed=1)}
    assert champion_strategy._inverse_vol_weights(histories, ["AAA"]) == {}


def test_compute_satellite_recommendation_inverse_vol_sums_to_satellite_weight(monkeypatch):
    histories = {
        "LOWVOL": _noisy_breakout_df(SATELLITE_N, daily_noise_std=0.002, seed=1),
        "HIGHVOL": _noisy_breakout_df(SATELLITE_N, daily_noise_std=0.05, seed=2),
    }

    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True, **kwargs):
        return histories[ticker]

    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history)

    result = champion_strategy.compute_satellite_recommendation(
        universe=["LOWVOL", "HIGHVOL"], sizing_method="inverse_vol"
    )

    assert result["sizing_method"] == "inverse_vol"
    assert set(result["selected"]) == {"LOWVOL", "HIGHVOL"}
    weights = result["per_ticker_weights"]
    assert sum(weights.values()) == pytest.approx(champion_strategy.SATELLITE_WEIGHT, abs=1e-6)
    assert weights["LOWVOL"] > weights["HIGHVOL"]
    # 균등가중 하위호환 필드는 그대로 유지
    assert result["per_ticker_weight"] == pytest.approx(champion_strategy.SATELLITE_WEIGHT / 2)


def test_compute_satellite_recommendation_inverse_vol_falls_back_to_equal_for_single_pick(monkeypatch):
    monkeypatch.setattr(
        champion_strategy, "get_price_history",
        lambda ticker, start=None, end=None, use_cache=True, **kwargs: _breakout_df(SATELLITE_N, breakout=True),
    )
    result = champion_strategy.compute_satellite_recommendation(universe=["ONLY"], sizing_method="inverse_vol")
    assert result["selected"] == ["ONLY"]
    assert result["per_ticker_weights"]["ONLY"] == pytest.approx(champion_strategy.SATELLITE_WEIGHT)


def test_run_satellite_backtest_inverse_vol_weights_sum_to_one_per_rebalance(monkeypatch):
    pool = ["LOWVOL", "HIGHVOL", "AAA"]
    breakout = {"LOWVOL", "HIGHVOL"}

    def _fake_sample_universe(n, as_of_date=None, use_point_in_time_market_cap=False, use_cache=True):
        return pd.DataFrame({"ticker": pool})

    def _fake_get_multiple_price_history(tickers, start=None, end=None, interval="1d", use_cache=True):
        out = {}
        for t in tickers:
            if t == "LOWVOL":
                out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=30.0, seed=1, noise_std=0.002, warmup_days=800)
            elif t == "HIGHVOL":
                out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=30.0, seed=2, noise_std=0.05, warmup_days=800)
            else:
                out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=-30.0, seed=3, warmup_days=800)
        return out

    monkeypatch.setattr(champion_strategy, "sample_universe", _fake_sample_universe)
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", _fake_get_multiple_price_history)

    core_idx = pd.bdate_range(BT_START, BT_END)
    result = champion_strategy.run_satellite_backtest(BT_START, BT_END, core_idx, top_k=3, sizing_method="inverse_vol")

    rebal_with_picks = [r for r in result["rebal_log"] if r["picks"]]
    assert rebal_with_picks, "적어도 한 번은 브레이크아웃 종목이 선정되어야 검증 가능"
    for r in rebal_with_picks:
        assert sum(r["weights"].values()) == pytest.approx(1.0, abs=1e-6)
    # 변동성이 다른 두 종목이 함께 뽑힌 리밸런싱에서는 저변동성 쪽이 더 큰 비중을 받아야 한다
    both_picked = [r for r in rebal_with_picks if set(r["picks"]) >= {"LOWVOL", "HIGHVOL"}]
    for r in both_picked:
        assert r["weights"]["LOWVOL"] > r["weights"]["HIGHVOL"]


def test_champion_tunable_params_metadata_shape():
    for name, meta in champion_strategy.CHAMPION_TUNABLE_PARAMS.items():
        assert set(meta.keys()) >= {"label", "default_values", "current", "note"}
        assert len(meta["default_values"]) >= 2


def test_run_core_param_sensitivity_core_top_n_detects_robust_and_peak_agreement(monkeypatch):
    """core_top_n=2에서 train/test 둘 다 최고 sharpe가 나오는 완만한(견고한) 곡선을 합성해,
    is_train_robust=True와 peaks_agree=True가 함께 나오는지 확인."""
    # top_n(정수)별로 train/test sharpe를 결정론적으로 반환하는 가짜 run_core_backtest.
    # 이웃 값끼리 변화폭이 완만하도록(전체 범위의 절반 이하) 설계.
    train_sharpe_by_top_n = {2: 1.5, 3: 1.3, 4: 1.1, 5: 1.0}
    test_sharpe_by_top_n = {2: 1.2, 3: 1.0, 4: 0.9, 5: 0.8}

    def _fake_run_core_backtest(start, end, top_n=champion_strategy.CORE_TOP_N, exposure_cut=champion_strategy.MARKET_FILTER_EXPOSURE_CUT):
        table = train_sharpe_by_top_n if end == "2020-06-30" else test_sharpe_by_top_n
        return {"metrics": {"sharpe": table[top_n]}}

    monkeypatch.setattr(champion_strategy, "run_core_backtest", _fake_run_core_backtest)
    monkeypatch.setattr(
        champion_strategy, "train_test_split_dates",
        lambda start, end, train_ratio: ("2020-01-01", "2020-06-30", "2020-07-01", "2020-12-31"),
    )

    result = champion_strategy.run_core_param_sensitivity(
        "core_top_n", [5, 3, 2, 4], "2020-01-01", "2020-12-31", metric="sharpe"
    )

    assert [p["value"] for p in result["points"]] == [2, 3, 4, 5]  # 오름차순 정렬
    assert result["is_train_robust"] is True
    assert result["best_train_value"] == 2
    assert result["best_test_value"] == 2
    assert result["peaks_agree"] is True
    assert result["n_valid_train"] == 4 and result["n_valid_test"] == 4
    assert result["train_period"] == ("2020-01-01", "2020-06-30")
    assert result["test_period"] == ("2020-07-01", "2020-12-31")


def test_run_core_param_sensitivity_detects_overfit_peak_divergence(monkeypatch):
    """train에서는 exposure_cut=1.0이 (뾰족하게) 제일 좋지만 test에서는 오히려 최악인 경우 —
    peaks_agree=False로 과최적화 의심 신호가 드러나야 한다."""
    train_sharpe = {0.0: 0.5, 0.5: 0.5, 1.0: 3.0}  # 1.0에서만 크게 튐 -> 견고하지 않음
    test_sharpe = {0.0: 1.0, 0.5: 0.9, 1.0: 0.1}  # train의 1등이 test에서는 꼴찌

    def _fake_run_core_backtest(start, end, top_n=champion_strategy.CORE_TOP_N, exposure_cut=champion_strategy.MARKET_FILTER_EXPOSURE_CUT):
        table = train_sharpe if end == "train_end" else test_sharpe
        return {"metrics": {"sharpe": table[exposure_cut]}}

    monkeypatch.setattr(champion_strategy, "run_core_backtest", _fake_run_core_backtest)
    monkeypatch.setattr(
        champion_strategy, "train_test_split_dates",
        lambda start, end, train_ratio: ("s", "train_end", "test_start", "e"),
    )

    result = champion_strategy.run_core_param_sensitivity(
        "market_filter_exposure_cut", [0.0, 0.5, 1.0], "s", "e", metric="sharpe"
    )

    assert result["is_train_robust"] is False  # 이웃 점프가 전체 범위의 절반을 넘음
    assert result["best_train_value"] == 1.0
    assert result["best_test_value"] == 0.0
    assert result["peaks_agree"] is False


def test_run_core_param_sensitivity_rejects_unknown_param():
    with pytest.raises(ValueError):
        champion_strategy.run_core_param_sensitivity("not_a_real_param", [1, 2], "2020-01-01", "2020-12-31")


def test_run_satellite_weight_sensitivity_runs_core_and_satellite_exactly_once(monkeypatch):
    """satellite_weight를 여러 값으로 스윕해도, 가장 느린 계산(코어/새틀라이트 백테스트 자체)은
    딱 한 번씩만 실행되고 값마다는 재블렌드만 해야 한다(핵심 설계 의도)."""
    idx = pd.bdate_range("2020-01-01", "2020-12-31")
    call_counts = {"core": 0, "satellite": 0}

    def _fake_run_core_backtest(start, end, **kwargs):
        call_counts["core"] += 1
        ret = pd.Series(0.001, index=idx)  # 코어는 매일 +0.1%
        return {"ret_net": ret}

    def _fake_run_satellite_backtest(start, end, trading_index, **kwargs):
        call_counts["satellite"] += 1
        ret = pd.Series(0.01, index=idx)  # 새틀라이트는 매일 +1% (코어보다 훨씬 좋음)
        return {"ret_net": ret, "metrics": {}}

    monkeypatch.setattr(champion_strategy, "run_core_backtest", _fake_run_core_backtest)
    monkeypatch.setattr(champion_strategy, "run_satellite_backtest", _fake_run_satellite_backtest)
    monkeypatch.setattr(
        champion_strategy, "train_test_split_dates",
        lambda start, end, train_ratio: ("2020-01-01", "2020-06-30", "2020-07-01", "2020-12-31"),
    )

    result = champion_strategy.run_satellite_weight_sensitivity(
        [0.0, 0.15, 0.30], "2020-01-01", "2020-12-31", metric="cumulative_return"
    )

    assert call_counts["core"] == 1
    assert call_counts["satellite"] == 1
    # 새틀라이트 비중이 클수록 누적수익률이 더 좋아야 함(새틀라이트가 코어보다 항상 나은 가짜 데이터)
    train_by_value = {p["value"]: p["train_metric"] for p in result["points"]}
    assert train_by_value[0.30] > train_by_value[0.15] > train_by_value[0.0]
    assert result["best_train_value"] == 0.30
    assert result["best_test_value"] == 0.30


def test_run_satellite_param_sensitivity_handles_value_error_as_missing(monkeypatch):
    """구간이 짧아 반기 리밸런싱일이 없으면 run_satellite_backtest가 ValueError를 던지는데,
    민감도 함수는 이를 예외 전파 없이 그 포인트의 metric=None으로 정직하게 표시해야 한다."""
    idx = pd.bdate_range("2020-01-01", "2020-12-31")

    def _fake_run_core_backtest(start, end, **kwargs):
        return {"ret_net": pd.Series(0.0005, index=idx)}

    def _fake_run_satellite_backtest(start, end, trading_index, **kwargs):
        if end == "test_end":
            raise ValueError("반기 리밸런싱일 없음")
        return {"ret_net": pd.Series(0.002, index=idx), "metrics": {"sharpe": 1.0 + kwargs.get("top_k", 0) * 0.1}}

    monkeypatch.setattr(champion_strategy, "run_core_backtest", _fake_run_core_backtest)
    monkeypatch.setattr(champion_strategy, "run_satellite_backtest", _fake_run_satellite_backtest)
    monkeypatch.setattr(
        champion_strategy, "train_test_split_dates",
        lambda start, end, train_ratio: ("s", "train_end", "test_start", "test_end"),
    )

    result = champion_strategy.run_satellite_param_sensitivity(
        "satellite_top_k", [1, 2, 3], "s", "e", metric="sharpe"
    )

    assert all(p["test_metric"] is None for p in result["points"])
    assert result["n_valid_test"] == 0
    assert result["n_valid_train"] == 3
    assert result["best_test_value"] is None
    assert result["peaks_agree"] is None  # 비교 불가 -> 판단 근거 없음


def test_run_satellite_param_sensitivity_rejects_unknown_param():
    with pytest.raises(ValueError):
        champion_strategy.run_satellite_param_sensitivity("satellite_weight", [1, 2], "s", "e")


def test_run_champion_param_sweep_dispatches_to_correct_function(monkeypatch):
    calls = []
    monkeypatch.setattr(
        champion_strategy, "run_satellite_weight_sensitivity",
        lambda values, start, end, train_ratio=0.75, metric="sharpe": calls.append(("satellite_weight", values)) or {},
    )
    monkeypatch.setattr(
        champion_strategy, "run_core_param_sensitivity",
        lambda param_name, values, start, end, train_ratio=0.75, metric="sharpe": calls.append((param_name, values)) or {},
    )
    monkeypatch.setattr(
        champion_strategy, "run_satellite_param_sensitivity",
        lambda param_name, values, start, end, train_ratio=0.75, metric="sharpe": calls.append((param_name, values)) or {},
    )

    champion_strategy.run_champion_param_sweep("satellite_weight", [0.1], "s", "e")
    champion_strategy.run_champion_param_sweep("core_top_n", [3], "s", "e")
    champion_strategy.run_champion_param_sweep("market_filter_exposure_cut", [0.5], "s", "e")
    champion_strategy.run_champion_param_sweep("satellite_top_k", [2], "s", "e")
    champion_strategy.run_champion_param_sweep("satellite_pool_n", [40], "s", "e")

    assert calls == [
        ("satellite_weight", [0.1]),
        ("core_top_n", [3]),
        ("market_filter_exposure_cut", [0.5]),
        ("satellite_top_k", [2]),
        ("satellite_pool_n", [40]),
    ]

    with pytest.raises(ValueError):
        champion_strategy.run_champion_param_sweep("nonexistent", [1], "s", "e")


def test_run_core_backtest_top_n_and_exposure_cut_change_weight_construction(monkeypatch):
    """run_core_backtest(top_n=..., exposure_cut=...)가 실제로 _build_core_weights에 반영되는지
    (모듈 내부 데이터 조회를 합성 데이터로 치환한) 가벼운 통합 테스트로 확인."""
    idx = pd.bdate_range("2018-01-01", "2021-06-30")
    n = len(idx)

    def _fake_get_multiple_price_history(tickers, start=None, end=None, interval="1d"):
        histories = {}
        for i, t in enumerate(tickers):
            # 종목마다 다른 기울기로 우상향(모두 양의 모멘텀 -> top_n만큼 항상 선택됨)
            close = np.linspace(100.0, 100.0 * (1 + 0.02 * (i + 1)), n)
            histories[t] = pd.DataFrame(
                {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1_000_000}, index=idx
            )
        return histories

    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", _fake_get_multiple_price_history)

    result_top2 = champion_strategy.run_core_backtest("2020-01-01", "2020-12-31", top_n=2)
    result_top4 = champion_strategy.run_core_backtest("2020-01-01", "2020-12-31", top_n=4)

    # top_n이 다르면 리밸런싱일의 비중 개수(0이 아닌 종목 수)도 달라야 함
    nonzero_top2 = (result_top2["weights"] > 0).sum(axis=1)
    nonzero_top4 = (result_top4["weights"] > 0).sum(axis=1)
    assert nonzero_top2[nonzero_top2 > 0].max() <= 2
    assert nonzero_top4[nonzero_top4 > 0].max() <= 4
    assert nonzero_top4.max() > nonzero_top2.max()


def test_load_confidence_table_and_rejected_ideas_from_real_research_json():
    """실제 리서치 종합 JSON(analysis/2026-09-05_research_program_synthesis/report_data.json)이
    이 엔진이 기대하는 구조를 그대로 갖고 있는지 확인 (파일 이동/스키마 변경 시 회귀 감지)."""
    confidence_table = champion_strategy.load_confidence_table()
    assert len(confidence_table) > 0
    for row in confidence_table:
        assert set(row.keys()) >= {"component", "grade", "note", "source"}
        assert row["grade"] in ("robust", "moderate", "weak", "reversed")

    rejected = champion_strategy.load_rejected_ideas()
    assert len(rejected) > 0
    assert all(row["grade"] in ("reversed", "unsupported") for row in rejected)

    meta = champion_strategy.load_research_meta()
    assert meta.get("n_reports", 0) > 0


# ----------------------------------------------------------------------------
# 과거 백테스트 함수 (run_core_backtest / run_satellite_backtest / run_champion_backtest)
# ----------------------------------------------------------------------------


def _price_series_over_range(
    start: str, end: str, annual_return_pct: float, warmup_days: int = 450, seed: int = 0, noise_std: float = 0.003
) -> pd.DataFrame:
    """start보다 warmup_days만큼 이전부터 end까지, 연율 annual_return_pct%로 성장하는(약간의 잡음
    포함) 합성 OHLCV. 실제 달력 날짜를 쓰므로 run_core_backtest(start, end)처럼 명시적 구간을
    받는 함수 테스트에 쓴다(라이브 신호 테스트용 _flat_then_return_df와 달리 '오늘' 기준이 아님).

    noise_std=0으로 주면 완전히 매끄러운(잡음 없는) 추세만 남는다 — 시장필터가 노이즈 때문에
    우연히 발동하면 안 되는 테스트(예: "필터가 항상 꺼져있어야 한다")에 씀."""
    idx = pd.bdate_range(start=pd.Timestamp(start) - pd.Timedelta(warmup_days, unit="D"), end=pd.Timestamp(end))
    rng = np.random.default_rng(seed)
    daily_drift = (1 + annual_return_pct / 100) ** (1 / 252) - 1
    noise = rng.normal(0, noise_std, len(idx)) if noise_std > 0 else 0.0
    close = 100 * np.cumprod(1 + daily_drift + noise)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995, "Close": close, "Volume": 1_000_000},
        index=idx,
    )


BT_START, BT_END = "2022-01-03", "2023-12-29"
# 코어 유니버스 중 절반은 강한 양의 모멘텀(리더), 절반은 하락(제외 대상)으로 나눠 top4 선정을 검증
_STRONG_LEADERS = champion_strategy.CORE_UNIVERSE[:4]
_WEAK_LAGGARDS = champion_strategy.CORE_UNIVERSE[4:]


def _fake_get_multiple_price_history_core(tickers, start=None, end=None, interval="1d", use_cache=True):
    out = {}
    for t in tickers:
        if t == champion_strategy.MARKET_FILTER_TICKER:
            # 노이즈 없이 매끄럽게 우상향 -> 200일선 위에 항상 머물러 시장필터가 우연히 발동하지 않음
            out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=8.0, seed=hash(t) % 1000, noise_std=0.0)
        elif t in _STRONG_LEADERS:
            out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=40.0, seed=hash(t) % 1000)
        else:
            out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=-15.0, seed=hash(t) % 1000)
    return out


def test_run_core_backtest_rotates_into_positive_momentum_leaders(monkeypatch):
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", _fake_get_multiple_price_history_core)

    result = champion_strategy.run_core_backtest(BT_START, BT_END)

    assert result["equity_net"].iloc[0] == pytest.approx(100.0)
    # 리밸런싱일마다 비중 절대합은 0(후보 없음) 또는 1.0(시장필터 미발동, top4 동일비중)이어야 한다.
    rebal_weight_sums = result["weights"].sum(axis=1)
    nonzero = rebal_weight_sums[rebal_weight_sums > 0]
    assert not nonzero.empty
    assert (nonzero.round(6).isin([1.0])).all()
    # 하락 자산에는 어느 시점에도 비중이 실리지 않아야 한다.
    for laggard in _WEAK_LAGGARDS:
        assert (result["weights"][laggard] == 0.0).all()
    # 상승 자산 중 실제로 top4에 든 종목이 있어야 한다(적어도 한 시점 이상 비중을 가짐).
    assert any((result["weights"][leader] > 0).any() for leader in _STRONG_LEADERS)


def _fake_get_multiple_price_history_market_filter_down(tickers, start=None, end=None, interval="1d", use_cache=True):
    out = {}
    for t in tickers:
        if t == champion_strategy.MARKET_FILTER_TICKER:
            # 장기 하락 후 최근 반등 -> 종가가 200일선 아래에 머물도록 구성
            out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=-25.0, seed=1)
        else:
            out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=20.0, seed=hash(t) % 1000)
    return out


def test_run_core_backtest_applies_market_filter_when_spy_downtrend(monkeypatch):
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", _fake_get_multiple_price_history_market_filter_down)

    result = champion_strategy.run_core_backtest(BT_START, BT_END, apply_market_filter=True)
    rebal_weight_sums = result["weights"].sum(axis=1).round(6)
    nonzero = rebal_weight_sums[rebal_weight_sums > 0]
    assert not nonzero.empty
    # SPY가 장기 하락 추세라 200일선 아래에 있을 시점이 많으므로, 절반(0.5)짜리 비중이 최소 한 번은 나와야 한다.
    assert (nonzero == 0.5).any()

    result_no_filter = champion_strategy.run_core_backtest(BT_START, BT_END, apply_market_filter=False)
    nonzero_no_filter = result_no_filter["weights"].sum(axis=1).round(6)
    nonzero_no_filter = nonzero_no_filter[nonzero_no_filter > 0]
    # 필터를 끄면 항상 풀비중(1.0)이어야 한다.
    assert (nonzero_no_filter == 1.0).all()


def test_semiannual_rebal_dates_only_january_and_july():
    idx = pd.bdate_range("2022-01-01", "2023-12-31")
    dates = champion_strategy._semiannual_rebal_dates(idx, "2022-01-01", "2023-12-31")
    assert len(dates) == 4  # 2022-01, 2022-07, 2023-01, 2023-07
    assert all(d.month in (1, 7) for d in dates)


def test_donchian_trailing_stop_positions_enters_on_breakout_and_exits_on_stop():
    idx = pd.bdate_range("2023-01-02", periods=40)
    close = pd.Series(100.0, index=idx)
    close.iloc[25:] = 130.0  # 확실한 돈치안 상단 돌파(진입)
    close.iloc[35:] = 100.0  # 고점(130) 대비 15% 초과 하락(청산)

    position = champion_strategy.donchian_trailing_stop_positions(close, entry_window=20, stop_pct=0.15)
    assert position.iloc[26] == 1  # 돌파 다음날 진입 상태
    assert position.iloc[-1] == 0  # 트레일링스탑에 걸려 청산된 상태


def _make_satellite_mocks(monkeypatch, pool_tickers, breakout_tickers):
    def _fake_sample_universe(n, as_of_date=None, use_point_in_time_market_cap=False, use_cache=True):
        return pd.DataFrame({"ticker": pool_tickers})

    def _fake_get_multiple_price_history(tickers, start=None, end=None, interval="1d", use_cache=True):
        out = {}
        for t in tickers:
            if t in breakout_tickers:
                out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=50.0, seed=hash(t) % 1000)
            else:
                # 꾸준히 하락 -> 20일 신고가를 만들 일이 없어 돈치안 진입 신호가 절대 발생하지 않음
                out[t] = _price_series_over_range(
                    BT_START, BT_END, annual_return_pct=-30.0, warmup_days=800, seed=hash(t) % 1000, noise_std=0.0
                )
        return out

    monkeypatch.setattr(champion_strategy, "sample_universe", _fake_sample_universe)
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", _fake_get_multiple_price_history)


def test_run_satellite_backtest_picks_only_active_breakout_candidates(monkeypatch):
    pool = ["AAA", "BBB", "CCC", "DDD"]
    breakout = {"AAA", "BBB"}
    _make_satellite_mocks(monkeypatch, pool, breakout)

    core_idx = pd.bdate_range(BT_START, BT_END)
    result = champion_strategy.run_satellite_backtest(BT_START, BT_END, core_idx, top_k=3)

    assert set(result["tickers_ever_held"]) <= breakout
    for log_entry in result["rebal_log"]:
        assert set(log_entry["picks"]) <= breakout
    assert not result["ret_net"].empty


def test_run_satellite_backtest_raises_without_rebal_dates_in_range():
    short_idx = pd.bdate_range("2022-02-01", "2022-02-10")
    with pytest.raises(ValueError):
        champion_strategy.run_satellite_backtest("2022-02-01", "2022-02-10", short_idx)


def test_run_champion_backtest_blends_core_and_satellite(monkeypatch):
    def _fake_core_history(tickers, start=None, end=None, interval="1d", use_cache=True):
        return _fake_get_multiple_price_history_core(tickers, start, end, interval, use_cache)

    pool = ["AAA", "BBB", "CCC"]
    breakout = {"AAA"}

    def _fake_sample_universe(n, as_of_date=None, use_point_in_time_market_cap=False, use_cache=True):
        return pd.DataFrame({"ticker": pool})

    call_log = {"n": 0}

    def _dispatching_get_multiple_price_history(tickers, start=None, end=None, interval="1d", use_cache=True):
        call_log["n"] += 1
        if set(tickers) & set(pool):
            out = {}
            for t in tickers:
                pct = 50.0 if t in breakout else 0.5
                out[t] = _price_series_over_range(BT_START, BT_END, annual_return_pct=pct, warmup_days=800, seed=hash(t) % 1000)
            return out
        return _fake_core_history(tickers, start, end, interval, use_cache)

    monkeypatch.setattr(champion_strategy, "sample_universe", _fake_sample_universe)
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", _dispatching_get_multiple_price_history)

    result = champion_strategy.run_champion_backtest(BT_START, BT_END, satellite_weight=0.15)

    assert result["satellite_weight_applied"] == pytest.approx(0.15)
    assert result["equity_net"].iloc[0] == pytest.approx(100.0)
    assert not result["core"]["ret_net"].empty
    assert not result["satellite"]["ret_net"].empty


def test_run_champion_backtest_falls_back_to_core_only_when_satellite_empty(monkeypatch):
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", _fake_get_multiple_price_history_core)

    def _fake_sample_universe_empty(n, as_of_date=None, use_point_in_time_market_cap=False, use_cache=True):
        return pd.DataFrame({"ticker": []})

    monkeypatch.setattr(champion_strategy, "sample_universe", _fake_sample_universe_empty)

    result = champion_strategy.run_champion_backtest(BT_START, BT_END, satellite_weight=0.15)
    assert result["satellite_weight_applied"] == 0.0
    pd.testing.assert_series_equal(result["ret_net"], result["core"]["ret_net"])


# ----------------------------------------------------------------------------
# 옵션 칼라 헤지 (작업 2026-09-14 추가)
# ----------------------------------------------------------------------------


def test_bs_put_call_price_satisfy_put_call_parity():
    # 유러피언 콜-풋 패리티: C - P = S - K*exp(-rT) (배당 없음 가정, Black-Scholes 공식 정합성 검증)
    S, K, T, r, sigma = 100.0, 105.0, 21 / 252, 0.03, 0.20
    call = champion_strategy.bs_call_price(S, K, T, r, sigma)
    put = champion_strategy.bs_put_price(S, K, T, r, sigma)
    assert (call - put) == pytest.approx(S - K * math.exp(-r * T), abs=1e-8)


def test_bs_prices_fall_back_to_intrinsic_value_at_expiry():
    assert champion_strategy.bs_put_price(90.0, 100.0, 0.0, 0.03, 0.2) == pytest.approx(10.0)
    assert champion_strategy.bs_call_price(110.0, 100.0, 0.0, 0.03, 0.2) == pytest.approx(10.0)
    assert champion_strategy.bs_put_price(110.0, 100.0, 0.0, 0.03, 0.2) == pytest.approx(0.0)


def _flat_spy_vix(start: str, end: str, warmup_days: int = 60, vix_level: float = 20.0):
    idx = pd.bdate_range(start=pd.Timestamp(start) - pd.Timedelta(warmup_days, unit="D"), end=pd.Timestamp(end))
    spy_close = np.full(len(idx), 400.0)
    vix_close = np.full(len(idx), vix_level)
    spy_df = pd.DataFrame({"Open": spy_close, "High": spy_close, "Low": spy_close, "Close": spy_close, "Volume": 1}, index=idx)
    vix_df = pd.DataFrame({"Open": vix_close, "High": vix_close, "Low": vix_close, "Close": vix_close, "Volume": 1}, index=idx)
    return spy_df, vix_df


def _patch_spy_vix_fedfunds(monkeypatch, spy_df, vix_df, rate: float = 2.0):
    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True, **kwargs):
        if ticker == "SPY":
            return spy_df.copy()
        if ticker == champion_strategy.VIX_TICKER:
            return vix_df.copy()
        raise AssertionError(f"unexpected ticker requested: {ticker}")

    monkeypatch.setattr(champion_strategy, "get_price_history", _fake_get_price_history)
    monkeypatch.setattr(champion_strategy.fred_data, "get_series", lambda series_id, use_cache=True: pd.Series([rate], index=[pd.Timestamp("2000-01-01")]))


def test_build_collar_overlay_returns_rolls_monthly_on_flat_market(monkeypatch):
    start, end = "2022-01-03", "2022-06-30"
    spy_df, vix_df = _flat_spy_vix(start, end)
    _patch_spy_vix_fedfunds(monkeypatch, spy_df, vix_df)

    trading_index = pd.bdate_range(start=start, end=end)
    result = champion_strategy.build_collar_overlay_returns(trading_index, start, end)

    assert list(result["overlay_ret"].index) == list(trading_index)
    # 1~6월 매달 첫 거래일마다 롤 -> 6번
    assert len(result["roll_log"]) == 6
    for row in result["roll_log"]:
        assert row["put_strike"] == pytest.approx(row["spy_at_roll"] * champion_strategy.COLLAR_PUT_MONEYNESS)
        assert row["call_strike"] == pytest.approx(row["spy_at_roll"] * champion_strategy.COLLAR_CALL_MONEYNESS)
        # 완전히 평탄한 시장(만기 시 SPY 변화 없음)이면 페이오프가 발생하지 않아야 한다
        assert row["net_payoff_pct"] == pytest.approx(0.0, abs=1e-9)


def test_build_collar_overlay_returns_pays_off_on_crash_at_expiry():
    """만기일에 SPY가 풋 행사가 아래로 급락하면 풋 매수분이 그만큼 페이오프를 지급해야 한다."""
    idx = pd.bdate_range(start="2022-01-03", end="2022-02-15")
    spy_close = np.full(len(idx), 400.0)
    spy_close[-5:] = 300.0  # 만기 무렵 25% 급락
    spy_df = pd.DataFrame({"Open": spy_close, "High": spy_close, "Low": spy_close, "Close": spy_close, "Volume": 1}, index=idx)
    vix_close = np.full(len(idx), 20.0)
    vix_df = pd.DataFrame({"Open": vix_close, "High": vix_close, "Low": vix_close, "Close": vix_close, "Volume": 1}, index=idx)

    result = champion_strategy.build_collar_overlay_returns(idx, "2022-01-03", "2022-02-15", tenor_days=len(idx) - 1)
    # 유일한 롤의 payoff가 만기일(마지막 거래일)에 큰 양의 값으로 잡혀야 한다(풋 행사가 - 급락 후 종가)
    payoff_on_last_day = result["overlay_ret"].iloc[-1]
    assert payoff_on_last_day > 0.10


def test_run_champion_backtest_with_collar_adds_comparison_fields(monkeypatch):
    monkeypatch.setattr(champion_strategy, "get_multiple_price_history", _fake_get_multiple_price_history_core)
    spy_df, vix_df = _flat_spy_vix(BT_START, BT_END, warmup_days=60)
    _patch_spy_vix_fedfunds(monkeypatch, spy_df, vix_df)

    def _fake_sample_universe_empty(n, as_of_date=None, use_point_in_time_market_cap=False, use_cache=True):
        return pd.DataFrame({"ticker": []})

    monkeypatch.setattr(champion_strategy, "sample_universe", _fake_sample_universe_empty)

    result = champion_strategy.run_champion_backtest_with_collar(BT_START, BT_END, satellite_weight=0.15)

    assert "collar_ret_net" in result and "collar_equity_net" in result and "collar_metrics" in result
    assert result["collar_equity_net"].iloc[0] == pytest.approx(100.0)
    assert len(result["collar_roll_log"]) > 0
    # 기존 챔피언 백테스트 필드는 그대로 유지되어야 한다(칼라는 추가 필드일 뿐 기존 동작을 안 바꿈)
    pd.testing.assert_series_equal(result["ret_net"], result["core"]["ret_net"])


def test_compute_live_collar_state_returns_none_without_price_data(monkeypatch):
    monkeypatch.setattr(champion_strategy, "get_price_history", lambda *a, **k: pd.DataFrame())
    assert champion_strategy.compute_live_collar_state() is None


def test_compute_live_collar_state_computes_strikes_from_latest_roll(monkeypatch):
    today = pd.Timestamp.today().normalize()
    start = today - pd.Timedelta(90, unit="D")
    idx = pd.bdate_range(start=start, end=today)
    spy_df, vix_df = _flat_spy_vix(str(start.date()), str(today.date()))
    spy_df = spy_df.reindex(idx).ffill()
    vix_df = vix_df.reindex(idx).ffill()
    _patch_spy_vix_fedfunds(monkeypatch, spy_df, vix_df)

    state = champion_strategy.compute_live_collar_state()

    assert state is not None
    assert state["put_strike"] == pytest.approx(state["spy_at_roll"] * champion_strategy.COLLAR_PUT_MONEYNESS)
    assert state["call_strike"] == pytest.approx(state["spy_at_roll"] * champion_strategy.COLLAR_CALL_MONEYNESS)
    assert 0 <= state["days_remaining"] <= champion_strategy.COLLAR_TENOR_DAYS
    # 완전히 평탄한 시장에서는 마크투모델 손익이 아주 작아야 한다(시간가치 변화 정도만 남음)
    assert abs(state["mark_to_model_pnl_pct_of_satellite_notional"]) < 1.0


def test_load_market_regime_context_returns_none_without_snapshot(monkeypatch):
    import core.market_regime as market_regime

    monkeypatch.setattr(
        market_regime, "select_regime_for_trading",
        lambda snapshot=None: {"trading_regime": None, "is_ambiguous": True, "total_score": None, "snapshot": None},
    )
    assert champion_strategy.load_market_regime_context() is None


def test_load_market_regime_context_returns_snapshot_when_present(monkeypatch):
    import core.market_regime as market_regime

    fake_result = {"trading_regime": "강세장", "is_ambiguous": False, "total_score": 50.0, "snapshot": {"regime": "강세장"}}
    monkeypatch.setattr(market_regime, "select_regime_for_trading", lambda snapshot=None: fake_result)
    assert champion_strategy.load_market_regime_context() == fake_result


# ----------------------------------------------------------------------------
# 리밸런싱 diff (작업 2026-09-14 추가)
# ----------------------------------------------------------------------------


def _holdings_pnl_df(rows: list[dict]) -> pd.DataFrame:
    """{"ticker","market_value"} 리스트로 core.portfolio.get_portfolio_pnl()과 동일한 형태
    (weight_pct 포함)의 DataFrame을 만든다."""
    df = pd.DataFrame(rows)
    total = df["market_value"].sum()
    df["weight_pct"] = df["market_value"] / total * 100 if total else None
    return df


_CORE_RESULT_NO_FILTER = {
    "top4": ["XLK", "XLY", "XLC", "XLV"],
    "per_ticker_weight": 0.85 / 4,
    "cash_weight_from_filter": 0.0,
}


def test_compute_rebalance_diff_empty_when_no_holdings():
    df = champion_strategy.compute_rebalance_diff(_CORE_RESULT_NO_FILTER, holdings_pnl=pd.DataFrame(), cash_balance=0.0)
    assert df.empty
    assert list(df.columns) == champion_strategy.REBALANCE_DIFF_COLUMNS


def test_compute_rebalance_diff_flags_buy_for_recommended_ticker_not_held():
    holdings = _holdings_pnl_df([{"ticker": "TLT", "market_value": 10_000.0}])
    df = champion_strategy.compute_rebalance_diff(_CORE_RESULT_NO_FILTER, holdings_pnl=holdings, cash_balance=0.0)

    xlk_row = df[df["ticker"] == "XLK"].iloc[0]
    assert xlk_row["action"] == "매수"
    assert xlk_row["current_weight_pct"] == pytest.approx(0.0)
    assert xlk_row["target_weight_pct"] == pytest.approx(0.85 / 4 * 100)
    assert xlk_row["target_value"] == pytest.approx(0.85 / 4 * 10_000.0)

    tlt_row = df[df["ticker"] == "TLT"].iloc[0]
    assert tlt_row["action"] == "매도"  # 목표비중 0인데 100% 보유 중 -> 전량 매도 신호
    assert tlt_row["source"] == "보유중(추천 목록 밖)"


def test_compute_rebalance_diff_holds_when_within_band():
    target_pct = 0.85 / 4
    holdings = _holdings_pnl_df(
        [{"ticker": "XLK", "market_value": target_pct * 10_000.0}, {"ticker": "CASH_FILLER", "market_value": (1 - target_pct) * 10_000.0}]
    )
    df = champion_strategy.compute_rebalance_diff(_CORE_RESULT_NO_FILTER, holdings_pnl=holdings, cash_balance=0.0)
    xlk_row = df[df["ticker"] == "XLK"].iloc[0]
    assert xlk_row["action"] == "유지"


def test_compute_rebalance_diff_combines_core_and_satellite_weight_for_overlapping_ticker():
    core_result = {**_CORE_RESULT_NO_FILTER, "top4": ["NVDA", "XLY", "XLC", "XLV"]}
    satellite_result = {"selected": ["NVDA", "AMD"], "per_ticker_weights": {"NVDA": 0.10, "AMD": 0.05}, "unallocated_weight": 0.0}
    holdings = _holdings_pnl_df([{"ticker": "NVDA", "market_value": 5_000.0}])

    df = champion_strategy.compute_rebalance_diff(
        core_result, satellite_result=satellite_result, holdings_pnl=holdings, cash_balance=0.0
    )

    nvda_row = df[df["ticker"] == "NVDA"].iloc[0]
    assert nvda_row["source"] == "코어+새틀라이트"
    assert nvda_row["target_weight_pct"] == pytest.approx((0.85 / 4 + 0.10) * 100)


def test_compute_rebalance_diff_adds_cash_row_when_filter_and_satellite_leave_unallocated():
    core_result = {"top4": ["XLK"], "per_ticker_weight": 0.85 / 4 * 0.5, "cash_weight_from_filter": 0.85 * 0.5}
    satellite_result = {"selected": [], "per_ticker_weights": {}, "unallocated_weight": 0.15}
    holdings = _holdings_pnl_df([{"ticker": "XLK", "market_value": 1_000.0}])

    df = champion_strategy.compute_rebalance_diff(
        core_result, satellite_result=satellite_result, holdings_pnl=holdings, cash_balance=0.0
    )

    cash_row = df[df["ticker"] == "CASH"].iloc[0]
    assert cash_row["target_weight_pct"] == pytest.approx((0.85 * 0.5 + 0.15) * 100)
    assert cash_row["current_weight_pct"] == pytest.approx(0.0)
    assert cash_row["current_value"] == pytest.approx(0.0)
    # cash_balance=0인데 목표비중은 크므로(> HOLD_BAND) 다른 종목과 동일한 기준으로 "매수"가 나와야 함
    # (예전처럼 무조건 "현금 보유"로 특수취급하지 않음).
    assert cash_row["action"] == "매수"


def test_compute_rebalance_diff_cash_balance_injected_reflects_actual_current_value():
    """cash_balance를 직접 주입하면 CASH 행의 current_weight_pct/current_value가 실제 값을 반영하고,
    총 계좌가치에도 더해진다(2026-09-14 추가 — 현금 잔고 추적 기능)."""
    core_result = {"top4": ["XLK"], "per_ticker_weight": 0.85 / 4 * 0.5, "cash_weight_from_filter": 0.85 * 0.5}
    satellite_result = {"selected": [], "per_ticker_weights": {}, "unallocated_weight": 0.15}
    holdings = _holdings_pnl_df([{"ticker": "XLK", "market_value": 1_000.0}])

    df = champion_strategy.compute_rebalance_diff(
        core_result, satellite_result=satellite_result, holdings_pnl=holdings, cash_balance=2_000.0
    )

    total_value = 1_000.0 + 2_000.0
    cash_row = df[df["ticker"] == "CASH"].iloc[0]
    assert cash_row["current_value"] == pytest.approx(2_000.0)
    assert cash_row["current_weight_pct"] == pytest.approx(2_000.0 / total_value * 100, abs=0.01)

    xlk_row = df[df["ticker"] == "XLK"].iloc[0]
    # XLK의 현재비중도 이제 (보유종목+현금) 전체 계좌가치를 분모로 계산되어야 함
    assert xlk_row["current_weight_pct"] == pytest.approx(1_000.0 / total_value * 100, abs=0.01)
    assert xlk_row["target_value"] == pytest.approx(core_result["per_ticker_weight"] * total_value)


def test_compute_rebalance_diff_cash_only_no_target_still_shown_when_actual_cash_present():
    """목표 현금비중이 0이어도(코어/새틀라이트가 완전히 배분됨) 실제 현금 잔고가 있으면 CASH 행이
    나와야 한다(예전엔 현금을 아예 몰랐으니 이런 행 자체가 있을 수 없었음)."""
    holdings = _holdings_pnl_df([{"ticker": "XLK", "market_value": 1_000.0}])
    df = champion_strategy.compute_rebalance_diff(_CORE_RESULT_NO_FILTER, holdings_pnl=holdings, cash_balance=500.0)

    assert "CASH" in df["ticker"].tolist()
    cash_row = df[df["ticker"] == "CASH"].iloc[0]
    assert cash_row["target_weight_pct"] == pytest.approx(0.0)
    assert cash_row["current_value"] == pytest.approx(500.0)
    assert cash_row["action"] == "매도"  # 목표 0인데 현금을 들고 있으니 다른 자산으로 옮기라는 신호


def test_compute_rebalance_diff_omits_satellite_when_not_yet_scanned():
    holdings = _holdings_pnl_df([{"ticker": "XLK", "market_value": 1_000.0}])
    df = champion_strategy.compute_rebalance_diff(
        _CORE_RESULT_NO_FILTER, satellite_result=None, holdings_pnl=holdings, cash_balance=0.0
    )
    assert "CASH" not in df["ticker"].tolist()  # 새틀라이트 미배정분을 모르는 채로 현금이라 단정하지 않음


def test_compute_rebalance_diff_calls_get_portfolio_pnl_when_not_injected(monkeypatch):
    called = {"n": 0}

    def _fake_get_portfolio_pnl():
        called["n"] += 1
        return _holdings_pnl_df([{"ticker": "XLK", "market_value": 1_000.0}])

    import core.portfolio as portfolio

    monkeypatch.setattr(portfolio, "get_portfolio_pnl", _fake_get_portfolio_pnl)
    monkeypatch.setattr(portfolio, "get_cash_balance", lambda: 0.0)
    champion_strategy.compute_rebalance_diff(_CORE_RESULT_NO_FILTER)
    assert called["n"] == 1


def test_compute_rebalance_diff_calls_get_cash_balance_when_not_injected(monkeypatch):
    called = {"n": 0}

    def _fake_get_cash_balance():
        called["n"] += 1
        return 3_000.0

    import core.portfolio as portfolio

    holdings = _holdings_pnl_df([{"ticker": "XLK", "market_value": 1_000.0}])
    monkeypatch.setattr(portfolio, "get_portfolio_pnl", lambda: holdings)
    monkeypatch.setattr(portfolio, "get_cash_balance", _fake_get_cash_balance)
    df = champion_strategy.compute_rebalance_diff(_CORE_RESULT_NO_FILTER)
    assert called["n"] == 1
    cash_row = df[df["ticker"] == "CASH"].iloc[0]
    assert cash_row["current_value"] == pytest.approx(3_000.0)


# ----------------------------------------------------------------------------
# 텔레그램 신호 변경 알림 (작업 2026-09-14 추가)
# ----------------------------------------------------------------------------


def _patch_signal_state_path(monkeypatch, tmp_path):
    path = tmp_path / "champion_signal_state.json"
    monkeypatch.setattr(champion_strategy, "SIGNAL_STATE_CACHE_PATH", path)
    return path


def _patch_core_and_satellite(monkeypatch, top4, above_200dma, satellite_selected):
    monkeypatch.setattr(
        champion_strategy, "compute_core_recommendation",
        lambda: {"as_of": "2026-09-14", "top4": top4, "above_200dma": above_200dma},
    )
    monkeypatch.setattr(
        champion_strategy, "compute_satellite_recommendation",
        lambda: {"selected": satellite_selected},
    )


def test_check_and_notify_signal_changes_notifies_on_first_run(monkeypatch, tmp_path):
    _patch_signal_state_path(monkeypatch, tmp_path)
    _patch_core_and_satellite(monkeypatch, ["XLK", "XLY"], True, ["NVDA"])
    sent = []

    result = champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)

    assert result["changed"] is True
    assert len(sent) == 1
    assert "최초 신호 기록" in sent[0]


def test_check_and_notify_signal_changes_silent_when_unchanged(monkeypatch, tmp_path):
    _patch_signal_state_path(monkeypatch, tmp_path)
    _patch_core_and_satellite(monkeypatch, ["XLK", "XLY"], True, ["NVDA"])
    sent = []
    champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)  # 최초 1회 저장

    result = champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)

    assert result["changed"] is False
    assert result["message"] is None
    assert len(sent) == 1  # 두 번째 호출에서는 알림이 추가되지 않음


def test_check_and_notify_signal_changes_notifies_when_core_top4_changes(monkeypatch, tmp_path):
    _patch_signal_state_path(monkeypatch, tmp_path)
    _patch_core_and_satellite(monkeypatch, ["XLK", "XLY"], True, ["NVDA"])
    sent = []
    champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)

    _patch_core_and_satellite(monkeypatch, ["XLE", "XLF"], True, ["NVDA"])
    result = champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)

    assert result["changed"] is True
    assert "코어 top4" in sent[-1]


def test_check_and_notify_signal_changes_notifies_when_market_filter_flips(monkeypatch, tmp_path):
    _patch_signal_state_path(monkeypatch, tmp_path)
    _patch_core_and_satellite(monkeypatch, ["XLK", "XLY"], True, ["NVDA"])
    sent = []
    champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)

    _patch_core_and_satellite(monkeypatch, ["XLK", "XLY"], False, ["NVDA"])
    result = champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)

    assert result["changed"] is True
    assert "시장필터" in sent[-1]


def test_check_and_notify_signal_changes_notifies_when_satellite_changes(monkeypatch, tmp_path):
    _patch_signal_state_path(monkeypatch, tmp_path)
    _patch_core_and_satellite(monkeypatch, ["XLK", "XLY"], True, ["NVDA"])
    sent = []
    champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)

    _patch_core_and_satellite(monkeypatch, ["XLK", "XLY"], True, ["AMD"])
    result = champion_strategy.check_and_notify_signal_changes(notify_fn=sent.append)

    assert result["changed"] is True
    assert "새틀라이트" in sent[-1]


def test_check_and_notify_signal_changes_skips_satellite_when_not_included(monkeypatch, tmp_path):
    _patch_signal_state_path(monkeypatch, tmp_path)
    called = {"satellite": False}

    def _fake_satellite():
        called["satellite"] = True
        return {"selected": []}

    monkeypatch.setattr(
        champion_strategy, "compute_core_recommendation",
        lambda: {"as_of": "2026-09-14", "top4": ["XLK"], "above_200dma": True},
    )
    monkeypatch.setattr(champion_strategy, "compute_satellite_recommendation", _fake_satellite)

    champion_strategy.check_and_notify_signal_changes(include_satellite=False, notify_fn=lambda m: None)
    assert called["satellite"] is False


def test_check_and_notify_signal_changes_persists_state_to_disk(monkeypatch, tmp_path):
    path = _patch_signal_state_path(monkeypatch, tmp_path)
    _patch_core_and_satellite(monkeypatch, ["XLK"], True, ["NVDA"])

    champion_strategy.check_and_notify_signal_changes(notify_fn=lambda m: None)

    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["core_top4"] == ["XLK"]
