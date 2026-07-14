"""core/strategy_tuning.py 단위 테스트 (모듈 A 확장: 다종목 미세튜닝 엔진).

테스트용 대표 전략으로 "볼린저 밴드 하단 반전 1:2:6 전략"을 사용한다: 밴드 하단 이탈(10%) ->
상승 인걸 캔들 확인(+20%) -> RSI 30 상향 돌파로 반전 확인(+60%) 순으로 분할 진입하고, 상단 도달(10%)
-> RSI 70 상향 돌파(+20%) -> RSI 50 하향 이탈(잔량 전부, 반전 실패 시 청산) 순으로 분할 청산한다.
진입 조건(하단/인걸/RSI상향)과 청산 조건(상단/RSI과매수/RSI하향)이 방향상 겹치지 않아
진입=청산 자기모순(PROGRESS.md에 기록된 기존 버그 패턴) 없이 안전하게 설계되어 있다.

네트워크(yfinance)를 타지 않도록 관련 함수를 모두 monkeypatch 로 대체한다.
"""

import json
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


def test_build_param_grid_expression_without_gemini_key_returns_original_only(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: False)
    candidates = st_mod.build_param_grid(EXPRESSION_BASE_CONFIG, "주도주", "보통")
    assert candidates == [EXPRESSION_BASE_CONFIG]


# ----------------------------------------------------------------------------
# expression 전략 전용 Gemini 튜닝 (identify_tunable_numbers / build_param_grid 확장 /
# generate_structural_variants / tune_expression_strategy_for_ticker)
# ----------------------------------------------------------------------------


class _FakeGeminiResponse:
    def __init__(self, payload: dict):
        self.text = json.dumps(payload, ensure_ascii=False)


def test_extract_numeric_literals_finds_values_in_order():
    literals = st_mod._extract_numeric_literals("close > sma(close, 20) and rsi(close, 14) < 30")
    assert [lit["value"] for lit in literals] == [20, 14, 30]
    assert [lit["text"] for lit in literals] == ["20", "14", "30"]


def test_identify_tunable_numbers_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: False)
    assert st_mod.identify_tunable_numbers(EXPRESSION_BASE_CONFIG["expression"]) == []


def test_identify_tunable_numbers_filters_non_tunable_and_uses_suggested_range(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: True)

    def _fake_generate(**kwargs):
        return _FakeGeminiResponse(
            {
                "numbers": [
                    {"index": 0, "tunable": True, "role": "이평 기간", "suggested_min": 10, "suggested_max": 40},
                    {"index": 1, "tunable": True, "role": "RSI 기간", "suggested_min": 7, "suggested_max": 21},
                    {"index": 2, "tunable": False, "role": "과매도 임계값(고정)", "suggested_min": 30, "suggested_max": 30},
                ]
            }
        )

    monkeypatch.setattr(st_mod.gemini_client, "generate_content", _fake_generate)

    result = st_mod.identify_tunable_numbers(EXPRESSION_BASE_CONFIG["expression"])
    assert {r["value"] for r in result} == {20, 14}  # 30(tunable=False)은 제외됨
    sma_period = next(r for r in result if r["value"] == 20)
    assert sma_period["suggested_min"] == 10.0
    assert sma_period["suggested_max"] == 40.0


def test_identify_tunable_numbers_returns_empty_on_count_mismatch(monkeypatch):
    """Gemini가 반환한 개수가 실제 숫자 개수와 다르면 신뢰할 수 없으니 원본 그대로 폴백해야 한다."""
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: True)
    monkeypatch.setattr(
        st_mod.gemini_client, "generate_content",
        lambda **kwargs: _FakeGeminiResponse({"numbers": [{"index": 0, "tunable": True, "role": "x", "suggested_min": 1, "suggested_max": 2}]}),
    )
    result = st_mod.identify_tunable_numbers(EXPRESSION_BASE_CONFIG["expression"])  # 숫자 3개인데 응답은 1개
    assert result == []


def test_identify_tunable_numbers_returns_empty_on_api_failure(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: True)

    def _raise(**kwargs):
        raise RuntimeError("429")

    monkeypatch.setattr(st_mod.gemini_client, "generate_content", _raise)
    assert st_mod.identify_tunable_numbers(EXPRESSION_BASE_CONFIG["expression"]) == []


def test_substitute_numbers_preserves_int_vs_float_style():
    expr = "close > sma(close, 20) and stdev(close, 5) < 2.5"
    literals = st_mod._extract_numeric_literals(expr)
    new_expr = st_mod._substitute_numbers(expr, literals, (30, 8, 3.25))
    assert new_expr == "close > sma(close, 30) and stdev(close, 8) < 3.25"


def test_build_expression_param_grid_uses_identified_numbers(monkeypatch):
    sma_period_literal = st_mod._extract_numeric_literals(EXPRESSION_BASE_CONFIG["expression"])[0]
    monkeypatch.setattr(
        st_mod, "identify_tunable_numbers",
        lambda expr: [{**sma_period_literal, "role": "기간", "suggested_min": 10.0, "suggested_max": 30.0}],
    )
    candidates = st_mod.build_param_grid(EXPRESSION_BASE_CONFIG, "성장주", "빠름")
    periods = sorted({st_mod._extract_numeric_literals(c["expression"])[0]["value"] for c in candidates})
    assert len(periods) >= 2  # 원본(20)과 최소 1개 이상의 변형이 함께 있어야 함
    assert 20 in periods
    for c in candidates:
        st_mod.validate_syntax(c["expression"])  # 전부 실제로 실행 가능해야 함


def test_build_expression_param_grid_no_tunable_numbers_returns_original(monkeypatch):
    monkeypatch.setattr(st_mod, "identify_tunable_numbers", lambda expr: [])
    candidates = st_mod.build_param_grid(EXPRESSION_BASE_CONFIG, "성장주", "빠름")
    assert candidates == [EXPRESSION_BASE_CONFIG]


def test_generate_structural_variants_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: False)
    assert st_mod.generate_structural_variants("close > sma(close, 20)", "주도주") == []


def test_generate_structural_variants_filters_invalid_and_caps_at_n(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: True)
    monkeypatch.setattr(
        st_mod.gemini_client, "generate_content",
        lambda **kwargs: _FakeGeminiResponse(
            {
                "variants": [
                    "close > ema(close, 10) and rsi(close, 14) < 25",  # 유효
                    "close > nonexistent_function(close, 5)",  # 미지원 함수 -> 거부
                    "close < bb_lower(close, 20)",  # 유효
                    "import os",  # 문법 자체가 실행 거부 대상 -> 거부
                    "close > ema(close, 50)",  # 유효(하지만 budget n=2라 안 담길 수도 있음)
                ]
            }
        ),
    )
    variants = st_mod.generate_structural_variants("close > sma(close, 20)", "주도주", n=2)
    assert len(variants) == 2
    for v in variants:
        st_mod.validate_syntax(v)  # 반환된 것은 전부 실행 가능해야 함


def test_generate_structural_variants_returns_empty_on_api_failure(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: True)
    monkeypatch.setattr(st_mod.gemini_client, "generate_content", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("fail")))
    assert st_mod.generate_structural_variants("close > sma(close, 20)", "주도주") == []


def test_tune_expression_strategy_skips_structural_search_when_already_outperforming(monkeypatch):
    """1단계(숫자 튜닝)만으로 test에서 둘 다 이기면 generate_structural_variants를 아예 호출하지
    않아야 한다 (구조 변경은 escape hatch로만 쓰여야 함)."""
    calls = {"structural": 0}

    def _fake_tune(ticker, cfg, style_type, start, end, train_ratio=0.75, intensity="보통"):
        result = dict(
            ticker=ticker, style_type=style_type, tuned_config=cfg,
            train_metrics=_metrics(sharpe=1.0),
            test_comparison={
                "strategy": {"cagr": 20.0}, "buy_and_hold_ticker": {"cagr": 10.0}, "buy_and_hold_benchmark": {"cagr": 8.0},
            },
            excess_return=12.0, health_warnings=[],
        )
        return result

    def _fake_variants(expr, style_type, n=3):
        calls["structural"] += 1
        return ["close > ema(close, 10)"]

    monkeypatch.setattr(st_mod, "tune_strategy_for_ticker", _fake_tune)
    monkeypatch.setattr(st_mod, "generate_structural_variants", _fake_variants)

    result = st_mod.tune_expression_strategy_for_ticker(
        "TEST", EXPRESSION_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31"
    )
    assert calls["structural"] == 0
    assert result["backbone_changed"] is False
    assert result["outperformed_ticker_bh"] is True
    assert result["outperformed_benchmark_bh"] is True


def test_tune_expression_strategy_tries_structural_variants_when_underperforming(monkeypatch):
    """1단계가 둘 다 못 이기면 구조 변형 후보들을 시도하고, test 성과가 가장 좋은 것을 채택해야 한다."""

    def _fake_tune(ticker, cfg, style_type, start, end, train_ratio=0.75, intensity="보통"):
        expr = cfg["expression"]
        # 원본은 못 이기고, "better" 변형은 확실히 이기고, "worse" 변형은 더 나쁘게 설계
        if "better" in expr:
            strat_cagr = 25.0
        elif "worse" in expr:
            strat_cagr = -5.0
        else:
            strat_cagr = 3.0
        return dict(
            ticker=ticker, style_type=style_type, tuned_config=cfg,
            train_metrics=_metrics(sharpe=1.0),
            test_comparison={
                "strategy": {"cagr": strat_cagr}, "buy_and_hold_ticker": {"cagr": 10.0}, "buy_and_hold_benchmark": {"cagr": 8.0},
            },
            excess_return=strat_cagr - 8.0, health_warnings=[],
        )

    monkeypatch.setattr(st_mod, "tune_strategy_for_ticker", _fake_tune)
    monkeypatch.setattr(
        st_mod, "generate_structural_variants",
        lambda expr, style_type, n=3: ["worse(close)", "better(close)"],
    )

    result = st_mod.tune_expression_strategy_for_ticker(
        "TEST", EXPRESSION_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31"
    )
    assert result["backbone_changed"] is True
    assert "better" in result["tuned_config"]["expression"]
    assert result["test_comparison"]["strategy"]["cagr"] == 25.0
    assert result["outperformed_ticker_bh"] is True
    assert result["outperformed_benchmark_bh"] is True


def test_tune_expression_strategy_never_regresses_below_first_pass(monkeypatch):
    """구조 변형 후보가 전부 1단계 결과보다 나쁘면, 절대 그쪽으로 안 바뀌고 1단계 결과를 유지해야
    한다(backbone_changed=False로 유지 — 손해 보는 방향으로 절대 안 감)."""

    def _fake_tune(ticker, cfg, style_type, start, end, train_ratio=0.75, intensity="보통"):
        strat_cagr = 5.0 if "expression" in cfg and "worse" not in cfg["expression"] else -20.0
        return dict(
            ticker=ticker, style_type=style_type, tuned_config=cfg,
            train_metrics=_metrics(sharpe=1.0),
            test_comparison={
                "strategy": {"cagr": strat_cagr}, "buy_and_hold_ticker": {"cagr": 10.0}, "buy_and_hold_benchmark": {"cagr": 8.0},
            },
            excess_return=strat_cagr - 8.0, health_warnings=[],
        )

    monkeypatch.setattr(st_mod, "tune_strategy_for_ticker", _fake_tune)
    monkeypatch.setattr(
        st_mod, "generate_structural_variants",
        lambda expr, style_type, n=3: ["worse(close)", "also_worse(close)"],
    )

    result = st_mod.tune_expression_strategy_for_ticker(
        "TEST", EXPRESSION_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31"
    )
    assert result["backbone_changed"] is False
    assert result["tuned_config"]["expression"] == EXPRESSION_BASE_CONFIG["expression"]
    assert result["test_comparison"]["strategy"]["cagr"] == 5.0


def test_run_batch_tuning_dispatches_expression_configs_to_expression_tuner(monkeypatch):
    tickers_df = pd.DataFrame({"ticker": ["AAA"], "sector": ["Utilities"]})
    fake_styles = pd.DataFrame(
        {"ticker": ["AAA"], "sector": ["Utilities"], "style_type": ["경기방어주"], "style_scores": [{"경기방어주": 90}]}
    )
    monkeypatch.setattr(st_mod, "compute_style_scores", lambda df, start, end: fake_styles)

    calls = {"expression_tuner": 0, "regular_tuner": 0}

    def _fake_expr_tune(ticker, cfg, style_type, start, end, train_ratio=0.75, intensity="보통"):
        calls["expression_tuner"] += 1
        return {"ticker": ticker, "style_type": style_type, "tuned_config": cfg, "train_metrics": {}, "test_comparison": {}, "excess_return": 0.0, "health_warnings": []}

    def _fake_regular_tune(ticker, cfg, style_type, start, end, train_ratio=0.75, intensity="보통"):
        calls["regular_tuner"] += 1
        return {"ticker": ticker, "style_type": style_type, "tuned_config": cfg, "train_metrics": {}, "test_comparison": {}, "excess_return": 0.0, "health_warnings": []}

    monkeypatch.setattr(st_mod, "tune_expression_strategy_for_ticker", _fake_expr_tune)
    monkeypatch.setattr(st_mod, "tune_strategy_for_ticker", _fake_regular_tune)

    st_mod.run_batch_tuning(EXPRESSION_BASE_CONFIG, tickers_df, "2020-01-01", "2021-01-01")
    assert calls["expression_tuner"] == 1
    assert calls["regular_tuner"] == 0

    st_mod.run_batch_tuning(REGIME_BASE_CONFIG, tickers_df, "2020-01-01", "2021-01-01")
    assert calls["expression_tuner"] == 1
    assert calls["regular_tuner"] == 1


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
            "excess_return": 2.0, "health_warnings": [], "backbone_changed": True,
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
    assert aaa["backbone_changed"] is True

    bbb = next(r for r in fetched["results"] if r["ticker"] == "BBB")
    assert bbb["error"] == "실패"
    assert bbb["tuned_config"] is None
    assert bbb["health_warnings"] == []
    assert bbb["backbone_changed"] is False  # 명시 안 하면 기본값 False

    listed = st_mod.list_tuning_runs()
    assert any(r["id"] == run_id and r["universe_size"] == 2 for r in listed)


def test_run_and_save_tuning_uses_provided_tickers_df_over_sample_universe(db_session, monkeypatch):
    """UI '직접 선택' 모드: tickers_df가 주어지면 sample_universe()를 절대 호출하지 않아야 한다."""
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)

    def _boom(n, use_cache=True):
        raise AssertionError("tickers_df가 주어졌는데도 sample_universe()가 호출됨")

    monkeypatch.setattr(st_mod, "sample_universe", _boom)
    monkeypatch.setattr(
        st_mod, "run_batch_tuning",
        lambda base_config, tickers_df, start, end, train_ratio, intensity: [
            {
                "ticker": t, "style_type": "주도주", "sector": "Utilities", "style_scores": {},
                "tuned_config": base_config, "train_metrics": {}, "test_comparison": {},
                "excess_return": 0.0, "health_warnings": [],
            }
            for t in tickers_df["ticker"]
        ],
    )

    manual_df = pd.DataFrame({"ticker": ["NVDA", "AMD"], "sector": ["Information Technology"] * 2})
    run_id = st_mod.run_and_save_tuning(
        BOLLINGER_1_2_6, 100, "2020-01-01", "2021-01-01", tickers_df=manual_df
    )
    fetched = st_mod.get_tuning_run(run_id)
    assert {r["ticker"] for r in fetched["results"]} == {"NVDA", "AMD"}


def test_run_and_save_tuning_falls_back_to_sample_universe_when_no_tickers_df(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(
        st_mod, "sample_universe", lambda n, use_cache=True: pd.DataFrame({"ticker": ["AAPL"], "sector": ["Information Technology"]})
    )
    monkeypatch.setattr(
        st_mod, "run_batch_tuning",
        lambda base_config, tickers_df, start, end, train_ratio, intensity: [
            {
                "ticker": t, "style_type": "성장주", "sector": "Information Technology", "style_scores": {},
                "tuned_config": base_config, "train_metrics": {}, "test_comparison": {},
                "excess_return": 0.0, "health_warnings": [],
            }
            for t in tickers_df["ticker"]
        ],
    )

    run_id = st_mod.run_and_save_tuning(BOLLINGER_1_2_6, 100, "2020-01-01", "2021-01-01")
    fetched = st_mod.get_tuning_run(run_id)
    assert {r["ticker"] for r in fetched["results"]} == {"AAPL"}


def test_get_tuning_run_returns_none_for_missing_id(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    assert st_mod.get_tuning_run(999) is None
