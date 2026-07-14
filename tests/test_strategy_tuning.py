"""core/strategy_tuning.py 단위 테스트 (모듈 A 확장: 다종목 미세튜닝 엔진).

테스트용 대표 전략으로 "볼린저 밴드 하단 반전 1:2:6 전략"을 사용한다: 밴드 하단 이탈(10%) ->
상승 인걸 캔들 확인(+20%) -> RSI 30 상향 돌파로 반전 확인(+60%) 순으로 분할 진입하고, 상단 도달(10%)
-> RSI 70 상향 돌파(+20%) -> RSI 50 하향 이탈(잔량 전부, 반전 실패 시 청산) 순으로 분할 청산한다.
진입 조건(하단/인걸/RSI상향)과 청산 조건(상단/RSI과매수/RSI하향)이 방향상 겹치지 않아
진입=청산 자기모순(PROGRESS.md에 기록된 기존 버그 패턴) 없이 안전하게 설계되어 있다.

네트워크(yfinance)를 타지 않도록 관련 함수를 모두 monkeypatch 로 대체한다.
"""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import core.strategy_tuning as st_mod

BOLLINGER_1_2_6 = {
    "entry_stages": [
        {
            "weight": 0.1,
            "logic": "AND",
            "conditions": [
                {"indicator": "bollinger", "period": 20, "std_dev": 2.0, "band": "lower", "op": "break_below"}
            ],
        },
        {"weight": 0.2, "logic": "AND", "conditions": [{"indicator": "engulfing", "direction": "bullish"}]},
        {
            "weight": 0.6,
            "logic": "AND",
            "conditions": [{"indicator": "rsi_cross", "period": 14, "level": 30, "direction": "up"}],
        },
    ],
    "exit_stages": [
        {
            "weight": 0.1,
            "logic": "AND",
            "conditions": [
                {"indicator": "bollinger", "period": 20, "std_dev": 2.0, "band": "upper", "op": "break_above"}
            ],
        },
        {
            "weight": 0.2,
            "logic": "AND",
            "conditions": [{"indicator": "rsi_cross", "period": 14, "level": 70, "direction": "up"}],
        },
        {
            "weight": 0.6,
            "logic": "AND",
            "conditions": [{"indicator": "rsi_cross", "period": 14, "level": 50, "direction": "down"}],
        },
    ],
    "emergency_exit": {
        "logic": "AND",
        "conditions": [
            {"indicator": "bollinger", "period": 20, "std_dev": 2.0, "band": "upper", "op": "break_above"},
            {"indicator": "rsi_cross", "period": 14, "level": 70, "direction": "up"},
        ],
    },
}

REGIME_BASE_CONFIG = {
    "logic": "AND",
    "conditions": [
        {"indicator": "ma_cross", "short": 20, "long": 60, "ma_type": "sma", "type": "golden"},
        {"indicator": "rsi", "period": 14, "op": "<", "value": 30},
    ],
}

EXPRESSION_BASE_CONFIG = {"expression": "close > sma(close, 20) and rsi(close, 14) < 30"}


def _make_price_df(n=300, seed=1, trend=0.0005):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-02", periods=n)
    returns = rng.normal(trend, 0.01, n)
    close = 100 * np.cumprod(1 + returns)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1_000_000},
        index=idx,
    )


# ----------------------------------------------------------------------------
# sample_universe
# ----------------------------------------------------------------------------


def test_sample_universe_balances_across_sectors(monkeypatch):
    tickers_a = [f"A{i}" for i in range(5)]
    tickers_b = [f"B{i}" for i in range(5)]
    universe = pd.DataFrame({"Symbol": tickers_a + tickers_b, "Sector": ["SectorA"] * 5 + ["SectorB"] * 5})
    monkeypatch.setattr(st_mod.screener, "get_universe", lambda use_cache=True: universe)

    market_caps = {t: 100 - i for i, t in enumerate(tickers_a)}
    market_caps.update({t: 200 - i for i, t in enumerate(tickers_b)})
    monkeypatch.setattr(
        st_mod.screener, "get_fundamentals", lambda ticker, use_cache=True: {"market_cap": market_caps.get(ticker, 0)}
    )

    result = st_mod.sample_universe(n=4)
    assert len(result) == 4
    assert (result["sector"] == "SectorA").sum() == 2
    assert (result["sector"] == "SectorB").sum() == 2
    assert set(result[result["sector"] == "SectorA"]["ticker"]) == {"A0", "A1"}
    assert set(result[result["sector"] == "SectorB"]["ticker"]) == {"B0", "B1"}


def test_sample_universe_empty_when_no_sectors(monkeypatch):
    monkeypatch.setattr(
        st_mod.screener, "get_universe", lambda use_cache=True: pd.DataFrame(columns=["Symbol", "Sector"])
    )
    result = st_mod.sample_universe(n=10)
    assert result.empty


# ----------------------------------------------------------------------------
# compute_style_scores
# ----------------------------------------------------------------------------


def test_compute_style_scores_tags_cyclical_and_defensive_by_sector(monkeypatch):
    tickers_df = pd.DataFrame({"ticker": ["CYC", "DEF"], "sector": ["Industrials", "Utilities"]})
    monkeypatch.setattr(
        st_mod.valuation,
        "fetch_valuation_inputs",
        lambda t: {"trailingPE": 20, "priceToBook": 3, "earningsGrowth": 0.1},
    )
    monkeypatch.setattr(st_mod, "get_price_history", lambda t, start=None, end=None, use_cache=True: _make_price_df())

    result = st_mod.compute_style_scores(tickers_df, "2020-01-01", "2021-01-01").set_index("ticker")
    assert result.loc["CYC", "cyclical_score"] == 100.0
    assert result.loc["CYC", "defensive_score"] == 0.0
    assert result.loc["DEF", "defensive_score"] == 100.0
    assert result.loc["DEF", "cyclical_score"] == 0.0


def test_compute_style_scores_momentum_ranks_hot_above_cold(monkeypatch):
    tickers_df = pd.DataFrame({"ticker": ["HOT", "COLD"], "sector": [None, None]})
    monkeypatch.setattr(st_mod.valuation, "fetch_valuation_inputs", lambda t: {})

    def _fake_price(ticker, start=None, end=None, use_cache=True):
        return _make_price_df(trend=0.01 if ticker == "HOT" else -0.005)

    monkeypatch.setattr(st_mod, "get_price_history", _fake_price)

    result = st_mod.compute_style_scores(tickers_df, "2020-01-01", "2021-01-01").set_index("ticker")
    assert result.loc["HOT", "momentum_score"] > result.loc["COLD", "momentum_score"]


def test_compute_style_scores_assigns_primary_type_from_all_labels(monkeypatch):
    tickers_df = pd.DataFrame({"ticker": ["X"], "sector": ["Utilities"]})
    monkeypatch.setattr(st_mod.valuation, "fetch_valuation_inputs", lambda t: {"trailingPE": 15, "priceToBook": 2})
    monkeypatch.setattr(st_mod, "get_price_history", lambda t, start=None, end=None, use_cache=True: _make_price_df())

    result = st_mod.compute_style_scores(tickers_df, "2020-01-01", "2021-01-01")
    row = result.iloc[0]
    assert row["style_type"] in st_mod.STYLE_LABELS
    assert set(row["style_scores"].keys()) == set(st_mod.STYLE_LABELS)


def test_compute_style_scores_empty_input_returns_empty_df():
    result = st_mod.compute_style_scores(pd.DataFrame(columns=["ticker", "sector"]), "2020-01-01", "2021-01-01")
    assert result.empty


# ----------------------------------------------------------------------------
# build_param_grid — 볼린저 1:2:6 전략(staged)과 레짐 전략 둘 다 검증
# ----------------------------------------------------------------------------


def test_build_param_grid_expression_returns_original_only():
    candidates = st_mod.build_param_grid(EXPRESSION_BASE_CONFIG, "주도주", "보통")
    assert candidates == [EXPRESSION_BASE_CONFIG]


def test_build_param_grid_preserves_bollinger_1_2_6_structure():
    candidates = st_mod.build_param_grid(BOLLINGER_1_2_6, "주도주", "빠름")
    assert len(candidates) >= 1
    for c in candidates:
        assert len(c["entry_stages"]) == 3
        assert len(c["exit_stages"]) == 3
        assert "emergency_exit" in c
        # 백본 유지 원칙: 지표 종류/방향/밴드 등 구조는 절대 바뀌지 않아야 하고 숫자 파라미터만 변한다.
        assert c["entry_stages"][0]["conditions"][0]["indicator"] == "bollinger"
        assert c["entry_stages"][0]["conditions"][0]["band"] == "lower"
        assert c["entry_stages"][1]["conditions"][0]["indicator"] == "engulfing"
        assert c["entry_stages"][1]["conditions"][0]["direction"] == "bullish"
        assert c["exit_stages"][0]["conditions"][0]["band"] == "upper"
        assert c["exit_stages"][2]["conditions"][0]["direction"] == "down"
        assert c["emergency_exit"]["conditions"][1]["level"] == pytest.approx(70, abs=15)  # 임계값만 흔들림


def test_build_param_grid_bollinger_1_2_6_varies_numeric_params():
    candidates = st_mod.build_param_grid(BOLLINGER_1_2_6, "성장주", "정밀")
    entry_stage3_levels = {c["entry_stages"][2]["conditions"][0]["level"] for c in candidates}
    std_devs = {c["entry_stages"][0]["conditions"][0]["std_dev"] for c in candidates}
    assert len(entry_stage3_levels) > 1
    assert len(std_devs) > 1


def test_build_param_grid_regime_produces_multiple_period_values():
    candidates = st_mod.build_param_grid(REGIME_BASE_CONFIG, "성장주", "빠름")
    short_values = {c["conditions"][0]["short"] for c in candidates}
    assert len(short_values) > 1


def test_build_param_grid_style_direction_leader_shorter_than_defensive():
    leader_candidates = st_mod.build_param_grid(REGIME_BASE_CONFIG, "주도주", "정밀")
    defensive_candidates = st_mod.build_param_grid(REGIME_BASE_CONFIG, "경기방어주", "정밀")
    original_short = REGIME_BASE_CONFIG["conditions"][0]["short"]

    leader_min_short = min(c["conditions"][0]["short"] for c in leader_candidates)
    defensive_max_short = max(c["conditions"][0]["short"] for c in defensive_candidates)
    assert leader_min_short < original_short
    assert defensive_max_short > original_short


def test_build_param_grid_respects_intensity_budget_and_is_reproducible():
    big_config = {
        "logic": "AND",
        "conditions": [
            {"indicator": "ma_cross", "short": 20, "long": 60, "ma_type": "sma", "type": "golden"},
            {"indicator": "rsi", "period": 14, "op": "<", "value": 30},
            {"indicator": "bollinger", "period": 20, "std_dev": 2.0, "band": "lower", "op": "break_below"},
        ],
    }
    candidates1 = st_mod.build_param_grid(big_config, "성장주", "빠름")
    candidates2 = st_mod.build_param_grid(big_config, "성장주", "빠름")
    assert len(candidates1) <= st_mod._INTENSITY_BUDGET["빠름"] + 1  # 예산 + 원본 1개
    assert candidates1 == candidates2  # 고정 시드라 재실행해도 같은 후보 집합이어야 한다


def test_build_param_grid_no_tunable_params_returns_original():
    config = {"logic": "AND", "conditions": [{"indicator": "engulfing", "direction": "bullish"}]}
    candidates = st_mod.build_param_grid(config, "주도주", "보통")
    assert candidates == [config]


# ----------------------------------------------------------------------------
# train_test_split_dates
# ----------------------------------------------------------------------------


def test_train_test_split_dates_chronological_and_ratio():
    train_start, train_end, test_start, test_end = st_mod.train_test_split_dates("2020-01-01", "2020-12-31", 0.75)
    assert train_start == "2020-01-01"
    assert pd.Timestamp(train_end) < pd.Timestamp(test_start)
    assert test_end == "2020-12-31"
    total_days = (pd.Timestamp("2020-12-31") - pd.Timestamp("2020-01-01")).days
    train_days = (pd.Timestamp(train_end) - pd.Timestamp(train_start)).days
    assert train_days == pytest.approx(total_days * 0.75, abs=1)


# ----------------------------------------------------------------------------
# tune_strategy_for_ticker
# ----------------------------------------------------------------------------


def _metrics(sharpe=0.0, trade_count=10, cagr=0.0, mdd=0.0, cumulative_return=0.0, win_rate=0.0):
    return {
        "sharpe": sharpe,
        "trade_count": trade_count,
        "cagr": cagr,
        "mdd": mdd,
        "cumulative_return": cumulative_return,
        "win_rate": win_rate,
    }


def _fake_test_comparison(strategy_cagr, benchmark_cagr, ticker_cagr=0.0):
    return {
        "strategy": SimpleNamespace(metrics=_metrics(cagr=strategy_cagr, sharpe=1.0, mdd=-5.0)),
        "buy_and_hold_ticker": SimpleNamespace(metrics=_metrics(cagr=ticker_cagr)),
        "buy_and_hold_benchmark": SimpleNamespace(metrics=_metrics(cagr=benchmark_cagr)),
    }


def test_tune_strategy_for_ticker_picks_best_sharpe_candidate(monkeypatch):
    config = {
        "logic": "AND",
        "conditions": [{"indicator": "ma_cross", "short": 20, "long": 60, "ma_type": "sma", "type": "golden"}],
    }
    candidates = st_mod.build_param_grid(config, "성장주", "빠름")
    short_values = sorted({c["conditions"][0]["short"] for c in candidates})
    best_short = short_values[-1]

    def _fake_run(ticker, cfg, start, end, label="전략"):
        short = cfg["conditions"][0].get("short", 0)
        sharpe = 5.0 if short == best_short else 0.1
        return SimpleNamespace(metrics=_metrics(sharpe=sharpe))

    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(st_mod, "run_backtest", _fake_run)
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end: _fake_test_comparison(strategy_cagr=15.0, benchmark_cagr=10.0),
    )

    result = st_mod.tune_strategy_for_ticker("TEST", config, "성장주", "2020-01-01", "2021-12-31")
    assert result["tuned_config"]["conditions"][0]["short"] == best_short
    assert result["excess_return"] == pytest.approx(5.0)
    assert result["test_comparison"]["strategy"]["cagr"] == 15.0


def test_tune_strategy_for_ticker_falls_back_to_original_when_all_candidates_excluded(monkeypatch):
    config = {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 30}]}
    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    # 모든 후보가 거래 횟수 미달(1건, _MIN_TRADE_COUNT=5)이라 원본으로 폴백해야 한다.
    monkeypatch.setattr(
        st_mod, "run_backtest", lambda ticker, cfg, start, end, label="전략": SimpleNamespace(metrics=_metrics(sharpe=99.0, trade_count=1))
    )
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end: _fake_test_comparison(strategy_cagr=0.0, benchmark_cagr=0.0),
    )

    result = st_mod.tune_strategy_for_ticker("TEST", config, "가치주", "2020-01-01", "2021-12-31")
    assert result["tuned_config"]["conditions"][0]["period"] == config["conditions"][0]["period"]


def test_tune_strategy_for_ticker_excludes_candidates_with_health_warnings(monkeypatch):
    def _fake_health(cfg):
        entry_cond = cfg["entry_stages"][0]["conditions"][0]
        return ["진입=청산 자기모순"] if entry_cond.get("std_dev") == 2.5 else []

    monkeypatch.setattr(st_mod, "diagnose_strategy_health", _fake_health)
    monkeypatch.setattr(
        st_mod, "run_backtest", lambda ticker, cfg, start, end, label="전략": SimpleNamespace(metrics=_metrics(sharpe=1.0))
    )
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end: _fake_test_comparison(strategy_cagr=5.0, benchmark_cagr=4.0),
    )

    result = st_mod.tune_strategy_for_ticker("TEST", BOLLINGER_1_2_6, "주도주", "2020-01-01", "2021-12-31")
    assert result["tuned_config"]["entry_stages"][0]["conditions"][0].get("std_dev") != 2.5
    assert result["health_warnings"] == []


# ----------------------------------------------------------------------------
# run_batch_tuning
# ----------------------------------------------------------------------------


def test_run_batch_tuning_continues_after_single_ticker_failure(monkeypatch):
    tickers_df = pd.DataFrame({"ticker": ["OK", "BAD"], "sector": ["Utilities", "Energy"]})
    fake_styles = pd.DataFrame(
        {
            "ticker": ["OK", "BAD"],
            "sector": ["Utilities", "Energy"],
            "style_type": ["경기방어주", "경기민감주"],
            "style_scores": [{"경기방어주": 90}, {"경기민감주": 80}],
        }
    )
    monkeypatch.setattr(st_mod, "compute_style_scores", lambda df, start, end: fake_styles)

    def _fake_tune(ticker, base_config, style_type, start, end, train_ratio=0.75, intensity="보통"):
        if ticker == "BAD":
            raise RuntimeError("데이터 조회 실패")
        return {
            "ticker": ticker, "style_type": style_type, "tuned_config": base_config,
            "train_metrics": {}, "test_comparison": {}, "excess_return": 1.0, "health_warnings": [],
        }

    monkeypatch.setattr(st_mod, "tune_strategy_for_ticker", _fake_tune)

    results = st_mod.run_batch_tuning({"logic": "AND", "conditions": []}, tickers_df, "2020-01-01", "2021-01-01")
    assert len(results) == 2
    ok = next(r for r in results if r["ticker"] == "OK")
    bad = next(r for r in results if r["ticker"] == "BAD")
    assert ok["excess_return"] == 1.0
    assert ok["style_type"] == "경기방어주"
    assert "error" in bad
    assert bad["style_type"] == "경기민감주"


# ----------------------------------------------------------------------------
# save_tuning_run / list_tuning_runs / get_tuning_run
# ----------------------------------------------------------------------------


def test_save_and_get_tuning_run_roundtrip(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)

    tickers_df = pd.DataFrame({"ticker": ["AAA", "BBB"], "sector": ["Utilities", "Energy"]})
    results = [
        {
            "ticker": "AAA", "sector": "Utilities", "style_type": "경기방어주",
            "style_scores": {"경기방어주": 90.0}, "tuned_config": BOLLINGER_1_2_6,
            "train_metrics": {"sharpe": 1.0}, "test_comparison": {"strategy": {"cagr": 5.0}},
            "excess_return": 2.0, "health_warnings": [],
        },
        {"ticker": "BBB", "sector": "Energy", "error": "실패"},
    ]

    run_id = st_mod.save_tuning_run(
        BOLLINGER_1_2_6, tickers_df, "2020-01-01", "2021-01-01", 0.75, "보통", results
    )
    assert run_id is not None

    fetched = st_mod.get_tuning_run(run_id)
    assert fetched["intensity"] == "보통"
    assert fetched["train_ratio"] == 0.75
    assert len(fetched["results"]) == 2

    aaa = next(r for r in fetched["results"] if r["ticker"] == "AAA")
    assert aaa["excess_return"] == 2.0
    assert aaa["style_scores"] == {"경기방어주": 90.0}
    assert aaa["tuned_config"]["entry_stages"][0]["conditions"][0]["indicator"] == "bollinger"

    bbb = next(r for r in fetched["results"] if r["ticker"] == "BBB")
    assert bbb["error"] == "실패"
    assert bbb["tuned_config"] is None
    assert bbb["health_warnings"] == []

    listed = st_mod.list_tuning_runs()
    assert any(r["id"] == run_id and r["universe_size"] == 2 for r in listed)


def test_get_tuning_run_returns_none_for_missing_id(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    assert st_mod.get_tuning_run(999) is None
