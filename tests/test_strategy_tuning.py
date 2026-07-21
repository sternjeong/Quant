"""core/strategy_tuning.py 단위 테스트 (모듈 A 확장: 다종목 미세튜닝 엔진).

테스트용 대표 전략으로 "볼린저 밴드 하단 반전 1:2:6 전략"을 사용한다: 밴드 하단 이탈(10%) ->
상승 인걸 캔들 확인(+20%) -> RSI 30 상향 돌파로 반전 확인(+60%) 순으로 분할 진입하고, 상단 도달(10%)
-> RSI 70 상향 돌파(+20%) -> RSI 50 하향 이탈(잔량 전부, 반전 실패 시 청산) 순으로 분할 청산한다.
진입 조건(하단/인걸/RSI상향)과 청산 조건(상단/RSI과매수/RSI하향)이 방향상 겹치지 않아
진입=청산 자기모순(PROGRESS.md에 기록된 기존 버그 패턴) 없이 안전하게 설계되어 있다.

네트워크(yfinance)를 타지 않도록 관련 함수를 모두 monkeypatch 로 대체한다.
"""

import copy
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

# 2026-07-15 볼린저 응용 매매법 4종에서 새로 추가된 지표(bbw_squeeze_release/double_pattern/
# rsi_divergence)의 신규 파라미터 키(threshold/lookback/hold_bars/band_period/band_std/
# pivot_lookback/pattern_window/volume_mult/rsi_period)가 build_param_grid에서 인식되는지
# 검증하기 위한 staged 전략. 각 단계 조건의 indicator/direction 자체는 서로 겹치지 않게 구성했다.
NEW_INDICATORS_STAGED_CONFIG = {
    "entry_stages": [
        {
            "weight": 0.4,
            "logic": "AND",
            "conditions": [
                {
                    "indicator": "bbw_squeeze_release",
                    "period": 20,
                    "std_dev": 2.0,
                    "threshold": 0.1,
                    "lookback": 20,
                    "hold_bars": 3,
                }
            ],
        },
        {
            "weight": 0.6,
            "logic": "AND",
            "conditions": [
                {
                    "indicator": "rsi_divergence",
                    "direction": "bullish",
                    "rsi_period": 14,
                    "band_period": 20,
                    "pivot_lookback": 5,
                    "pattern_window": 40,
                }
            ],
        },
    ],
    "exit_stages": [
        {
            "weight": 1.0,
            "logic": "AND",
            "conditions": [
                {
                    "indicator": "double_pattern",
                    "direction": "bearish",
                    "band_period": 20,
                    "band_std": 2.0,
                    "pivot_lookback": 5,
                    "pattern_window": 40,
                    "volume_mult": 1.5,
                }
            ],
        },
    ],
}


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


def test_sample_universe_as_of_date_restricts_to_point_in_time_constituents(monkeypatch):
    """as_of_date를 주면 현재 유니버스 전체가 아니라 그 시점 point-in-time 종목만 후보가 되어야
    한다(survivorship bias 완화, PROGRESS.md 백로그 1번). 현재 유니버스에 없는(=지수에서 편출된)
    종목도 섹터 "Unknown"으로 후보에 남아야 한다."""
    tickers_a = [f"A{i}" for i in range(4)]
    universe = pd.DataFrame({"Symbol": tickers_a, "Sector": ["SectorA"] * 4})
    monkeypatch.setattr(st_mod.screener, "get_universe", lambda use_cache=True: universe)
    market_caps = {t: 100 - i for i, t in enumerate(tickers_a)}
    market_caps["DELISTED_FROM_INDEX"] = 50
    monkeypatch.setattr(
        st_mod.screener, "get_fundamentals", lambda ticker, use_cache=True: {"market_cap": market_caps.get(ticker, 0)}
    )
    monkeypatch.setattr(
        st_mod.point_in_time_universe,
        "get_constituents_as_of",
        lambda as_of_date, csv_path=None: ["A0", "A1", "DELISTED_FROM_INDEX"],
    )

    result = st_mod.sample_universe(n=3, as_of_date="2020-01-01")
    assert set(result["ticker"]) == {"A0", "A1", "DELISTED_FROM_INDEX"}
    assert "A2" not in set(result["ticker"])  # 현재 유니버스엔 있지만 그 시점엔 없었던 종목
    delisted_row = result[result["ticker"] == "DELISTED_FROM_INDEX"].iloc[0]
    assert delisted_row["sector"] == "Unknown"  # 현재 유니버스 섹터 매핑에 없는 종목


def test_sample_universe_empty_when_no_sectors(monkeypatch):
    monkeypatch.setattr(
        st_mod.screener, "get_universe", lambda use_cache=True: pd.DataFrame(columns=["Symbol", "Sector"])
    )
    result = st_mod.sample_universe(n=10)
    assert result.empty


def test_sample_universe_random_seed_still_respects_sector_quota(monkeypatch):
    """random_seed를 줘도 섹터별 할당량(균등 배분 원칙)은 그대로 지켜야 한다 — 대상만 무작위."""
    tickers_a = [f"A{i}" for i in range(10)]
    tickers_b = [f"B{i}" for i in range(10)]
    universe = pd.DataFrame({"Symbol": tickers_a + tickers_b, "Sector": ["SectorA"] * 10 + ["SectorB"] * 10})
    monkeypatch.setattr(st_mod.screener, "get_universe", lambda use_cache=True: universe)
    market_caps = {t: 100 - i for i, t in enumerate(tickers_a + tickers_b)}
    monkeypatch.setattr(
        st_mod.screener, "get_fundamentals", lambda ticker, use_cache=True: {"market_cap": market_caps.get(ticker, 0)}
    )

    result = st_mod.sample_universe(n=6, random_seed=42)
    assert len(result) == 6
    assert (result["sector"] == "SectorA").sum() == 3
    assert (result["sector"] == "SectorB").sum() == 3


def test_sample_universe_random_seed_is_reproducible_but_differs_from_deterministic(monkeypatch):
    """같은 시드로 두 번 뽑으면 완전히 같은 표본이 나와야 하고(재현 가능), 시드가 없을 때(결정론적
    시총 상위)와는 다른 표본이 나올 수 있어야 한다(야간 반복 튜닝에서 실제로 다른 종목을 탐색하는
    핵심 근거)."""
    tickers = [f"T{i}" for i in range(10)]
    universe = pd.DataFrame({"Symbol": tickers, "Sector": ["SectorA"] * 10})
    monkeypatch.setattr(st_mod.screener, "get_universe", lambda use_cache=True: universe)
    market_caps = {t: 100 - i for i, t in enumerate(tickers)}  # T0가 시총 1위
    monkeypatch.setattr(
        st_mod.screener, "get_fundamentals", lambda ticker, use_cache=True: {"market_cap": market_caps.get(ticker, 0)}
    )

    deterministic = set(st_mod.sample_universe(n=3)["ticker"])
    assert deterministic == {"T0", "T1", "T2"}  # 시총 상위 3개

    seeded_once = set(st_mod.sample_universe(n=3, random_seed=7)["ticker"])
    seeded_twice = set(st_mod.sample_universe(n=3, random_seed=7)["ticker"])
    assert seeded_once == seeded_twice  # 재현 가능

    seeded_other = set(st_mod.sample_universe(n=3, random_seed=999)["ticker"])
    # 시드가 다르면 표본도 달라질 수 있어야 한다(10개 중 3개 조합이 다양하므로 충돌 확률이 낮음).
    assert seeded_once != seeded_other or seeded_once != deterministic


# ----------------------------------------------------------------------------
# get_top_tuning_results — 야간 반복 미세튜닝 리더보드 (2026-07-15)
# ----------------------------------------------------------------------------


def test_get_top_tuning_results_orders_by_excess_return_and_filters_errors(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)

    tickers_df = pd.DataFrame({"ticker": ["A", "B", "C"], "sector": ["Tech", "Tech", "Tech"]})
    results_run1 = [
        {"ticker": "A", "sector": "Tech", "trained_regime": "약세장", "excess_return": 5.0, "test_comparison": {"strategy": {"cagr": 10.0}}},
        {"ticker": "B", "sector": "Tech", "trained_regime": "강세장", "excess_return": 1.0, "test_comparison": {"strategy": {"cagr": 3.0}}},
        {"ticker": "C", "sector": "Tech", "error": "실패"},  # excess_return 없음 -> 제외돼야 함
    ]
    run1_id = st_mod.save_tuning_run(
        BOLLINGER_1_2_6, tickers_df, "2020-01-01", "2021-01-01", 0.75, "빠름", results_run1, base_strategy_id=3
    )

    results_run2 = [
        {"ticker": "D", "sector": "Tech", "excess_return": 8.0, "test_comparison": {"strategy": {"cagr": 12.0}}},
    ]
    st_mod.save_tuning_run(
        BOLLINGER_1_2_6, tickers_df, "2020-01-01", "2021-01-01", 0.75, "정밀", results_run2, base_strategy_id=3
    )

    # 다른 백본 전략(base_strategy_id=99)의 결과는 섞이면 안 된다.
    results_other_strategy = [
        {"ticker": "Z", "sector": "Tech", "excess_return": 99.0, "test_comparison": {}},
    ]
    st_mod.save_tuning_run(
        BOLLINGER_1_2_6, tickers_df, "2020-01-01", "2021-01-01", 0.75, "빠름", results_other_strategy,
        base_strategy_id=99,
    )

    top = st_mod.get_top_tuning_results(base_strategy_id=3, limit=10)
    tickers_in_order = [r["ticker"] for r in top]
    assert tickers_in_order == ["D", "A", "B"]  # excess_return 내림차순, C(에러)/Z(다른 전략) 제외
    assert top[0]["excess_return"] == 8.0
    assert top[0]["run_intensity"] == "정밀"
    a_result = next(r for r in top if r["ticker"] == "A")
    assert a_result["trained_regime"] == "약세장"


def test_get_top_tuning_results_respects_limit(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)

    tickers_df = pd.DataFrame({"ticker": [f"T{i}" for i in range(5)], "sector": ["Tech"] * 5})
    results = [{"ticker": f"T{i}", "sector": "Tech", "excess_return": float(i)} for i in range(5)]
    st_mod.save_tuning_run(
        BOLLINGER_1_2_6, tickers_df, "2020-01-01", "2021-01-01", 0.75, "보통", results, base_strategy_id=3
    )

    top = st_mod.get_top_tuning_results(base_strategy_id=3, limit=2)
    assert len(top) == 2
    assert [r["ticker"] for r in top] == ["T4", "T3"]


def test_get_top_tuning_results_includes_base_config(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)

    tickers_df = pd.DataFrame({"ticker": ["A"], "sector": ["Tech"]})
    results = [{"ticker": "A", "sector": "Tech", "excess_return": 5.0, "tuned_config": BOLLINGER_1_2_6}]
    st_mod.save_tuning_run(
        BOLLINGER_1_2_6, tickers_df, "2020-01-01", "2021-01-01", 0.75, "빠름", results, base_strategy_id=3
    )

    top = st_mod.get_top_tuning_results(base_strategy_id=3, limit=10)
    assert top[0]["base_config"] == BOLLINGER_1_2_6


# ----------------------------------------------------------------------------
# describe_tuning_diff / summarize_tuning_diff — 야간 리더보드 상세보기 (2026-07-16)
# ----------------------------------------------------------------------------


def test_describe_tuning_diff_detects_changed_condition_and_weight():
    tuned = copy.deepcopy(BOLLINGER_1_2_6)
    tuned["entry_stages"][2]["conditions"][0]["level"] = 35  # RSI 상향 돌파 레벨 30 -> 35
    tuned["entry_stages"][0]["weight"] = 0.15  # 진입 1단계 비중 0.1 -> 0.15
    tuned["entry_stages"][1]["weight"] = 0.15  # 합계 유지를 위해 2단계도 같이 조정(정규화된 것처럼)

    diff = st_mod.describe_tuning_diff(BOLLINGER_1_2_6, tuned)
    assert diff["schema"] == "json"
    assert diff["unchanged"] is False

    condition_changes = [c for c in diff["changes"] if c["kind"] == "condition"]
    assert len(condition_changes) == 1
    assert condition_changes[0]["indicator"] == "rsi_cross"
    assert "30" in condition_changes[0]["before"]
    assert "35" in condition_changes[0]["after"]

    weight_changes = {c["path"]: c for c in diff["changes"] if c["kind"] == "weight"}
    assert "entry_stages[0]" in weight_changes
    assert "entry_stages[1]" in weight_changes
    assert "10%" in weight_changes["entry_stages[0]"]["before"]
    assert "15%" in weight_changes["entry_stages[0]"]["after"]


def test_describe_tuning_diff_reports_unchanged_when_original_kept():
    tuned = copy.deepcopy(BOLLINGER_1_2_6)  # 완전히 동일 -> 원본 그대로 채택된 경우
    diff = st_mod.describe_tuning_diff(BOLLINGER_1_2_6, tuned)
    assert diff["unchanged"] is True
    assert diff["changes"] == []


def test_describe_tuning_diff_expression_schema_compares_whole_string():
    base = {"expression": "close > sma(close, 20) and rsi(close, 14) < 30"}
    tuned = {"expression": "close > sma(close, 40) and rsi(close, 14) < 30"}
    diff = st_mod.describe_tuning_diff(base, tuned)
    assert diff["schema"] == "expression"
    assert diff["unchanged"] is False
    assert diff["changes"][0]["before"] == base["expression"]
    assert diff["changes"][0]["after"] == tuned["expression"]


def test_describe_tuning_diff_skips_paths_missing_after_structural_change():
    # backbone_changed로 조건 개수 자체가 줄어든 경우 -> 사라진 경로는 조용히 건너뛰어야 함(크래시 없음)
    tuned = copy.deepcopy(BOLLINGER_1_2_6)
    tuned["entry_stages"] = tuned["entry_stages"][:1]
    diff = st_mod.describe_tuning_diff(BOLLINGER_1_2_6, tuned)
    assert diff["schema"] == "json"  # 예외 없이 처리됨


def test_summarize_tuning_diff_unchanged_message():
    diff = {"schema": "json", "unchanged": True, "changes": []}
    text = st_mod.summarize_tuning_diff(diff)
    assert "그대로" in text


def test_summarize_tuning_diff_lists_each_change_in_korean():
    diff = {
        "schema": "json",
        "unchanged": False,
        "changes": [
            {"path": "entry_stages[2].conditions[0]", "kind": "condition", "indicator": "rsi_cross",
             "before": "RSI(14) 30 상향 돌파", "after": "RSI(14) 35 상향 돌파"},
        ],
    }
    text = st_mod.summarize_tuning_diff(diff)
    assert "rsi_cross" in text
    assert "RSI(14) 30 상향 돌파 → RSI(14) 35 상향 돌파" in text


def test_summarize_tuning_diff_prefixes_warning_when_backbone_changed():
    diff = {"schema": "expression", "unchanged": False, "changes": [{"before": "a", "after": "b"}]}
    text = st_mod.summarize_tuning_diff(diff, backbone_changed=True)
    assert text.startswith("⚠️")


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


def test_build_regime_switch_variant_combines_trend_filter_and_original(monkeypatch):
    """종목 자체 상승추세(종가>이평)면 신고가 돌파로, 그 외엔 원본 진입 조건 그대로 쓰는 결정론적
    국면 스위치 수식을 만들어야 한다(SPEC 12절, Gemini 없이 고정 템플릿)."""
    result = st_mod._build_regime_switch_variant("rsi(close, 14) < 30")
    assert result is not None
    assert "sma(close, 200)" in result
    assert "highest(close, 60)" in result
    assert "rsi(close, 14) < 30" in result  # 원본 진입 조건은 그대로 보존


def test_build_regime_switch_variant_uses_custom_periods():
    result = st_mod._build_regime_switch_variant("rsi(close, 14) < 30", trend_ma_period=100, breakout_lookback=20)
    assert "sma(close, 100)" in result
    assert "highest(close, 20)" in result


def test_build_regime_switch_variant_returns_none_when_combination_invalid(monkeypatch):
    monkeypatch.setattr(
        st_mod, "validate_syntax", lambda expr: (_ for _ in ()).throw(st_mod.ExpressionError("invalid"))
    )
    assert st_mod._build_regime_switch_variant("rsi(close, 14) < 30") is None


def test_generate_structural_variants_for_config_dispatches_by_schema(monkeypatch):
    """expression/레짐/1:2:6 세 스키마 모두 각자 맞는 생성 경로로 위임되어야 한다."""
    calls = []

    def _fake_expr(expr, style_type, n=st_mod._MAX_STRUCTURAL_VARIANTS):
        calls.append("expression")
        return [f"{expr} > 0"]

    def _fake_json(base_config, style_type, schema_note, item_schema, required_keys, n):
        calls.append(schema_note)
        return [{"conditions": []}] if "logic" in required_keys else [{"entry_stages": [], "exit_stages": []}]

    monkeypatch.setattr(st_mod, "generate_structural_variants", _fake_expr)
    monkeypatch.setattr(st_mod, "_generate_structural_variants_json", _fake_json)

    expr_variants = st_mod.generate_structural_variants_for_config(EXPRESSION_BASE_CONFIG, "성장주")
    assert calls == ["expression"]
    # Gemini 제안(모킹됨) + 결정론적 국면 스위치 변형(3d절)이 하나 더 추가되어야 한다.
    assert expr_variants[0] == {"expression": "close > sma(close, 20) and rsi(close, 14) < 30 > 0"}
    assert "highest(close, 60)" in expr_variants[1]["expression"]

    regime_variants = st_mod.generate_structural_variants_for_config(REGIME_BASE_CONFIG, "성장주")
    assert calls[-1] == "레짐(AND/OR)"
    assert regime_variants == [{"conditions": []}]

    staged_variants = st_mod.generate_structural_variants_for_config(BOLLINGER_1_2_6, "성장주")
    assert calls[-1] == "1:2:6 단계별"
    assert staged_variants == [{"entry_stages": [], "exit_stages": []}]


def test_generate_structural_variants_json_filters_missing_required_keys(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: True)
    monkeypatch.setattr(
        st_mod.gemini_client, "generate_content",
        lambda **kwargs: _FakeGeminiResponse(
            {"variants": [{"logic": "AND", "conditions": [{"indicator": "rsi"}]}, {"logic": "AND"}, "not a dict"]}
        ),
    )
    valid = st_mod._generate_structural_variants_json(
        REGIME_BASE_CONFIG, "성장주", "레짐(AND/OR)",
        st_mod.nl_strategy.INDICATOR_CONFIG_SCHEMA["properties"]["indicator_config"], ("logic", "conditions"), 3,
    )
    assert valid == [{"logic": "AND", "conditions": [{"indicator": "rsi"}]}]


def test_generate_structural_variants_json_returns_empty_without_api_key(monkeypatch):
    monkeypatch.setattr(st_mod.gemini_client, "has_api_key", lambda: False)
    assert (
        st_mod._generate_structural_variants_json(
            REGIME_BASE_CONFIG, "성장주", "레짐(AND/OR)",
            st_mod.nl_strategy.INDICATOR_CONFIG_SCHEMA["properties"]["indicator_config"], ("logic", "conditions"), 3,
        )
        == []
    )


# ----------------------------------------------------------------------------
# tune_strategy_for_group / run_batch_tuning (2026-07-15부터: 종목별 독립 탐색 -> 스타일 그룹 풀링)
# ----------------------------------------------------------------------------


def test_group_min_required_rounds_up():
    assert st_mod._group_min_required(1) == 1
    assert st_mod._group_min_required(3) == 2  # 50%의 올림
    assert st_mod._group_min_required(4) == 2


def test_candidate_group_train_sharpe_requires_minimum_coverage(monkeypatch):
    """3종목 중 1종목만 유효하면(최소 2종목 필요) 이 후보는 탈락(None)해야 한다."""

    def _fake_run(ticker, cfg, start, end, label="전략", max_holding_days=None):
        trade_count = 10 if ticker == "A" else 1  # A만 유효, B/C는 매매 부족
        return SimpleNamespace(metrics=_metrics(sharpe=2.0, trade_count=trade_count))

    monkeypatch.setattr(st_mod, "run_backtest", _fake_run)
    score = st_mod._candidate_group_train_sharpe(["A", "B", "C"], REGIME_BASE_CONFIG, "2020-01-01", "2020-06-01")
    assert score is None


def test_candidate_group_train_sharpe_averages_valid_tickers(monkeypatch):
    sharpes = {"A": 1.0, "B": 3.0}

    def _fake_run(ticker, cfg, start, end, label="전략", max_holding_days=None):
        return SimpleNamespace(metrics=_metrics(sharpe=sharpes[ticker], trade_count=10))

    monkeypatch.setattr(st_mod, "run_backtest", _fake_run)
    score = st_mod._candidate_group_train_sharpe(["A", "B"], REGIME_BASE_CONFIG, "2020-01-01", "2020-06-01")
    assert score == pytest.approx(2.0)


def test_split_into_folds_covers_full_range_without_gaps():
    folds = st_mod._split_into_folds("2020-01-01", "2020-12-30", 3)
    assert len(folds) == 3
    assert folds[0][0] == "2020-01-01"
    assert folds[-1][1] == "2020-12-30"
    for (_, prev_end), (next_start, _) in zip(folds, folds[1:]):
        assert (pd.Timestamp(next_start) - pd.Timestamp(prev_end)).days == 1


_THREE_FOLDS = [("2020-01-01", "2020-04-01"), ("2020-04-02", "2020-07-01"), ("2020-07-02", "2020-10-01")]


def test_candidate_group_walkforward_score_no_variance_keeps_full_mean(monkeypatch):
    values = iter([2.0, 2.0, 2.0])
    monkeypatch.setattr(st_mod, "_candidate_group_train_sharpe", lambda tickers, cfg, s, e, max_holding_days=None: next(values))
    result = st_mod._candidate_group_walkforward_score(["A"], REGIME_BASE_CONFIG, _THREE_FOLDS)
    assert result["mean_sharpe"] == pytest.approx(2.0)
    assert result["std_sharpe"] == pytest.approx(0.0)
    assert result["score"] == pytest.approx(2.0)  # 변동 없으면 패널티도 없음


def test_candidate_group_walkforward_score_penalizes_inconsistent_folds(monkeypatch):
    """평균이 같아도(둘 다 폴드 평균 2.0) 폴드마다 들쭉날쭉한 후보는 점수가 더 낮아야 한다
    (뾰족한 피크=과최적화 신호에 패널티를 주는 게 SPEC 11.2절의 핵심)."""
    stable = iter([2.0, 2.0, 2.0])
    volatile = iter([5.0, -1.0, 2.0])
    monkeypatch.setattr(st_mod, "_candidate_group_train_sharpe", lambda tickers, cfg, s, e, max_holding_days=None: next(stable))
    stable_result = st_mod._candidate_group_walkforward_score(["A"], REGIME_BASE_CONFIG, _THREE_FOLDS)
    monkeypatch.setattr(st_mod, "_candidate_group_train_sharpe", lambda tickers, cfg, s, e, max_holding_days=None: next(volatile))
    volatile_result = st_mod._candidate_group_walkforward_score(["A"], REGIME_BASE_CONFIG, _THREE_FOLDS)

    assert stable_result["mean_sharpe"] == pytest.approx(volatile_result["mean_sharpe"], abs=1e-6)
    assert volatile_result["score"] < stable_result["score"]


def test_candidate_group_walkforward_score_requires_minimum_fold_coverage(monkeypatch):
    """3개 폴드 중 1개만 유효하면(최소 2개 필요) None을 반환해 후보에서 탈락시켜야 한다."""
    values = iter([2.0, None, None])
    monkeypatch.setattr(st_mod, "_candidate_group_train_sharpe", lambda tickers, cfg, s, e, max_holding_days=None: next(values))
    assert st_mod._candidate_group_walkforward_score(["A"], REGIME_BASE_CONFIG, _THREE_FOLDS) is None


def test_select_best_group_config_walkforward_picks_highest_scoring_candidate(monkeypatch):
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 20, "long": 60, "type": "golden"}]}
    candidates = st_mod.build_param_grid(config, "성장주", "빠름")
    short_values = sorted({c["conditions"][0]["short"] for c in candidates})
    best_short = short_values[-1]

    def _fake_run(ticker, cfg, start, end, label="train", max_holding_days=None):
        short = cfg["conditions"][0].get("short", 0)
        sharpe = 5.0 if short == best_short else 0.1  # 폴드/종목과 무관하게 후보별로 고정된 샤프
        return SimpleNamespace(metrics=_metrics(sharpe=sharpe, trade_count=10))

    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(st_mod, "run_backtest", _fake_run)

    best_config, trail = st_mod._select_best_group_config_walkforward(
        ["AAA", "BBB"], candidates, _THREE_FOLDS
    )

    assert best_config["conditions"][0]["short"] == best_short
    assert trail[0]["config"]["conditions"][0]["short"] == best_short
    assert all(trail[i]["score"] >= trail[i + 1]["score"] for i in range(len(trail) - 1))  # 점수 내림차순
    assert all(len(t["fold_sharpes"]) == st_mod._WALK_FORWARD_FOLDS for t in trail)


def test_group_mean_excess_return_averages_and_skips_errors():
    per_ticker = {
        "A": {"strategy": {"cagr": 20.0}, "buy_and_hold_benchmark": {"cagr": 10.0}},
        "B": {"strategy": {"cagr": 5.0}, "buy_and_hold_benchmark": {"cagr": 10.0}},
        "C": {"error": "실패"},
    }
    assert st_mod._group_mean_excess_return(per_ticker) == pytest.approx(2.5)  # (10 + (-5)) / 2


def test_group_mean_excess_return_all_failed_returns_negative_infinity():
    assert st_mod._group_mean_excess_return({"A": {"error": "실패"}}) == float("-inf")


# ----------------------------------------------------------------------------
# 국면별(약세장/강세장) 분리 트레이닝 (SPEC 13절, 2026-07-16)
# ----------------------------------------------------------------------------


def test_train_folds_for_regime_delegates_to_market_regime(monkeypatch):
    captured = {}

    def _fake_segments(start, end):
        captured["args"] = (start, end)
        return {"약세장": [("2020-01-01", "2020-03-01")], "강세장": [("2020-04-01", "2020-09-01")]}

    monkeypatch.setattr(st_mod.market_regime, "historical_regime_segments", _fake_segments)

    assert st_mod._train_folds_for_regime("2020-01-01", "2020-12-31", "약세장") == [("2020-01-01", "2020-03-01")]
    assert captured["args"] == ("2020-01-01", "2020-12-31")
    assert st_mod._train_folds_for_regime("2020-01-01", "2020-12-31", "강세장") == [("2020-04-01", "2020-09-01")]


def test_evaluate_group_config_on_regime_matched_test_picks_longest_segment(monkeypatch):
    monkeypatch.setattr(
        st_mod.market_regime, "historical_regime_segments",
        lambda start, end: {"약세장": [("2020-01-01", "2020-02-01"), ("2020-06-01", "2020-09-01")]},
    )
    captured = {}

    def _fake_eval(tickers, config, seg_start, seg_end, max_holding_days=None):
        captured["segment"] = (seg_start, seg_end)
        return {"A": {"strategy": {"cagr": 20.0}, "buy_and_hold_benchmark": {"cagr": 5.0}}}

    monkeypatch.setattr(st_mod, "_evaluate_group_config_on_test", _fake_eval)

    result = st_mod._evaluate_group_config_on_regime_matched_test(["A"], {}, "2020-01-01", "2020-12-31", "약세장")

    assert captured["segment"] == ("2020-06-01", "2020-09-01")  # 더 긴 구간(3개월 > 1개월)이 선택돼야 함
    assert result["segment_start"] == "2020-06-01"
    assert result["mean_excess_return"] == pytest.approx(15.0)


def test_evaluate_group_config_on_regime_matched_test_none_when_no_matching_segment(monkeypatch):
    monkeypatch.setattr(st_mod.market_regime, "historical_regime_segments", lambda start, end: {"약세장": []})
    result = st_mod._evaluate_group_config_on_regime_matched_test(["A"], {}, "2020-01-01", "2020-12-31", "약세장")
    assert result is None


def test_tune_strategy_for_group_uses_regime_folds_when_regime_given(monkeypatch):
    """regime을 넘기면 달력 등분 폴드(_split_into_folds) 대신 실제 국면 구간(SPEC 13.4절)이
    _select_best_group_config_walkforward의 폴드로 그대로 전달돼야 한다."""
    regime_folds = [("2020-02-01", "2020-04-01"), ("2020-08-01", "2020-10-01")]
    monkeypatch.setattr(st_mod, "_train_folds_for_regime", lambda ts, te, regime: regime_folds)
    monkeypatch.setattr(
        st_mod, "_split_into_folds",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("regime이 지정됐는데 달력 폴드를 씀")),
    )

    captured = {}

    def _fake_select(tickers, candidates, folds, max_holding_days=None):
        captured["folds"] = folds
        return copy.deepcopy(REGIME_BASE_CONFIG), []

    monkeypatch.setattr(st_mod, "_select_best_group_config_walkforward", _fake_select)
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end, max_holding_days=None: _fake_test_comparison(strategy_cagr=15.0, benchmark_cagr=10.0),
    )
    monkeypatch.setattr(st_mod, "run_backtest", lambda ticker, cfg, start, end, label="train", max_holding_days=None: SimpleNamespace(metrics=_metrics()))
    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    # test 구간엔 국면 일치 구간이 없다고 가정(폴드 위임 여부만 검증하는 게 이 테스트의 목적이라
    # test 평가 자체는 단순화) -> 2026-07-17 정정 이후 검증 불가(None)로 나오는 게 정상.
    monkeypatch.setattr(st_mod.market_regime, "historical_regime_segments", lambda start, end: {"약세장": []})
    monkeypatch.setattr(st_mod, "generate_structural_variants_for_config", lambda *a, **k: [])

    result = st_mod.tune_strategy_for_group(
        ["AAA"], REGIME_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31", regime="약세장"
    )

    assert captured["folds"] == regime_folds
    assert result["trained_regime"] == "약세장"
    assert result["group_mean_excess_return"] is None  # test 구간에 약세장 구간이 없어 검증 불가
    assert result["insufficient_regime_data"] is False


def test_tune_strategy_for_group_falls_back_when_no_regime_segments_in_train(monkeypatch):
    """train 구간 안에 해당 국면 구간이 하나도 없으면(예: 5년 이력에 뚜렷한 약세장이 없음) 원본
    config를 그대로 쓰고 insufficient_regime_data=True로 표시해야 한다(SPEC 13.5절)."""
    monkeypatch.setattr(st_mod, "_train_folds_for_regime", lambda ts, te, regime: [])
    monkeypatch.setattr(
        st_mod, "_select_best_group_config_walkforward",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("폴드가 없는데 워크포워드 탐색을 시도함")),
    )
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end, max_holding_days=None: _fake_test_comparison(strategy_cagr=15.0, benchmark_cagr=10.0),
    )
    monkeypatch.setattr(st_mod, "run_backtest", lambda ticker, cfg, start, end, label="train", max_holding_days=None: SimpleNamespace(metrics=_metrics()))
    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(st_mod.market_regime, "historical_regime_segments", lambda start, end: {"약세장": []})
    monkeypatch.setattr(st_mod, "generate_structural_variants_for_config", lambda *a, **k: [])

    result = st_mod.tune_strategy_for_group(
        ["AAA"], REGIME_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31", regime="약세장"
    )

    assert result["insufficient_regime_data"] is True
    assert result["group_config"] == REGIME_BASE_CONFIG
    assert result["regime_matched_test"] is None
    assert result["group_mean_excess_return"] is None


def test_tune_strategy_for_group_with_regime_reports_matched_segment_as_primary_metric(monkeypatch):
    """2026-07-17 정정: regime이 지정되면 group_mean_excess_return/per_ticker_test_comparison은
    test 구간 전체가 아니라 국면 일치 구간에서만 평가한 값이어야 한다 — "약세장 config를 강세장
    데이터로 검증하지 않는다"는 사용자 확정 원칙."""
    monkeypatch.setattr(st_mod, "_train_folds_for_regime", lambda ts, te, regime: [("2020-01-01", "2020-06-01")])
    monkeypatch.setattr(st_mod, "_select_best_group_config_walkforward", lambda *a, **k: (copy.deepcopy(REGIME_BASE_CONFIG), []))
    monkeypatch.setattr(st_mod, "run_backtest", lambda ticker, cfg, start, end, label="train", max_holding_days=None: SimpleNamespace(metrics=_metrics()))
    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    # test 구간 안에 약세장 구간이 하나 있고(2021-01-01~2021-06-01), 그 바깥(강세장 등)에서 호출되면
    # 완전히 다른(훨씬 나쁜) 수치를 주도록 만들어 "정말로 국면 구간만 썼는지"를 구분해낼 수 있게 한다.
    matched_segment = ("2021-01-01", "2021-06-01")
    monkeypatch.setattr(st_mod.market_regime, "historical_regime_segments", lambda start, end: {"약세장": [matched_segment]})

    def _fake_compare(ticker, cfg, start, end, max_holding_days=None):
        if (start, end) == matched_segment:
            return _fake_test_comparison(strategy_cagr=20.0, benchmark_cagr=5.0)  # 초과수익 15
        return _fake_test_comparison(strategy_cagr=-50.0, benchmark_cagr=50.0)  # 전체 기간이면 완전히 다른 값

    monkeypatch.setattr(st_mod, "compare_with_benchmarks", _fake_compare)

    result = st_mod.tune_strategy_for_group(
        ["AAA"], REGIME_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31", regime="약세장"
    )

    assert result["group_mean_excess_return"] == pytest.approx(15.0)
    assert result["per_ticker_test_comparison"]["AAA"]["strategy"]["cagr"] == 20.0
    assert result["regime_matched_test"]["segment_start"] == matched_segment[0]
    assert result["regime_matched_test"]["segment_end"] == matched_segment[1]


def test_tune_strategy_for_group_regime_none_is_unaffected(monkeypatch):
    """regime을 안 넘기면(기본값) 기존 달력 등분 워크포워드 그대로 동작하고 국면 관련 필드는
    비활성 상태여야 한다(레거시 호환)."""
    monkeypatch.setattr(
        st_mod, "_train_folds_for_regime",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("regime=None인데 국면 폴드를 조회함")),
    )
    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(st_mod, "run_backtest", lambda ticker, cfg, start, end, label="전략", max_holding_days=None: SimpleNamespace(metrics=_metrics(sharpe=1.0)))
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end, max_holding_days=None: _fake_test_comparison(strategy_cagr=15.0, benchmark_cagr=10.0),
    )

    result = st_mod.tune_strategy_for_group(["AAA"], REGIME_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31")

    assert result["trained_regime"] is None
    assert result["insufficient_regime_data"] is False
    assert result["regime_matched_test"] is None


def test_tune_strategy_for_group_shares_one_config_across_tickers_and_stays_honest_on_test(monkeypatch):
    """그룹 안 모든 종목이 동일한 tuned_config를 받아야 하고(풀링 트레이닝의 핵심), test 구간
    성과가 후보 선택에 전혀 쓰이지 않아야 한다(train/test 분리 원칙 — 사용자 확정)."""
    config = {"logic": "AND", "conditions": [{"indicator": "ma_cross", "short": 20, "long": 60, "type": "golden"}]}
    candidates = st_mod.build_param_grid(config, "성장주", "빠름")
    short_values = sorted({c["conditions"][0]["short"] for c in candidates})
    best_short = short_values[-1]

    def _fake_run(ticker, cfg, start, end, label="전략", max_holding_days=None):
        short = cfg["conditions"][0].get("short", 0)
        sharpe = 5.0 if short == best_short else 0.1  # 모든 종목에 동일하게 적용 -> 그룹 평균도 동일 순위
        return SimpleNamespace(metrics=_metrics(sharpe=sharpe))

    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(st_mod, "run_backtest", _fake_run)
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end, max_holding_days=None: _fake_test_comparison(strategy_cagr=15.0, benchmark_cagr=10.0),
    )
    # test 구간을 참조했다면 이 gemini 호출이 발생했을 것 (mean_excess=5.0 > 0 이라 escape hatch 자체가 불필요)
    monkeypatch.setattr(
        st_mod, "generate_structural_variants_for_config",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("이겼는데도 구조 변경을 시도함")),
    )

    result = st_mod.tune_strategy_for_group(["AAA", "BBB", "CCC"], config, "성장주", "2020-01-01", "2021-12-31")

    assert result["group_config"]["conditions"][0]["short"] == best_short
    for ticker in ("AAA", "BBB", "CCC"):
        assert result["per_ticker_test_comparison"][ticker]["strategy"]["cagr"] == 15.0
    assert result["group_mean_excess_return"] == pytest.approx(5.0)
    assert result["group_win_ratio"] == 1.0
    assert result["backbone_changed"] is False
    assert result["tuning_trail"]  # 다중 구간 워크포워드 트레일이 함께 반환되어야 함(SPEC 11절)
    assert result["tuning_trail"][0]["config"]["conditions"][0]["short"] == best_short


def test_tune_strategy_for_group_tries_structural_variant_when_group_underperforms(monkeypatch):
    """그룹 평균이 test 구간에서 S&P500을 못 이기면(mean_excess<=0) 구조 변경을 시도하고, 그룹
    평균이 실제로 개선되는 변형만 채택해야 한다."""
    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(
        st_mod, "run_backtest", lambda ticker, cfg, start, end, label="전략", max_holding_days=None: SimpleNamespace(metrics=_metrics(sharpe=1.0))
    )

    def _fake_compare(ticker, cfg, start, end, max_holding_days=None):
        # 원본(REGIME_BASE_CONFIG) 및 그 숫자 변형은 못 이기고, "better" 태그가 붙은 구조 변형만 이긴다.
        strat_cagr = 25.0 if cfg.get("_tag") == "better" else 3.0
        return _fake_test_comparison(strategy_cagr=strat_cagr, benchmark_cagr=8.0)

    monkeypatch.setattr(st_mod, "compare_with_benchmarks", _fake_compare)
    monkeypatch.setattr(
        st_mod, "generate_structural_variants_for_config",
        lambda base_config, style_type, n=3: [
            {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 25}], "_tag": "worse"},
            {"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 20}], "_tag": "better"},
        ],
    )

    result = st_mod.tune_strategy_for_group(["AAA", "BBB"], REGIME_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31")

    assert result["backbone_changed"] is True
    assert result["group_config"].get("_tag") == "better"
    assert result["group_mean_excess_return"] == pytest.approx(17.0)  # 25 - 8


def test_tune_strategy_for_group_never_regresses_below_first_pass(monkeypatch):
    """구조 변형이 전부 원본 그룹 결과보다 나쁘면 원본을 그대로 유지해야 한다."""
    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(
        st_mod, "run_backtest", lambda ticker, cfg, start, end, label="전략", max_holding_days=None: SimpleNamespace(metrics=_metrics(sharpe=1.0))
    )
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end: _fake_test_comparison(strategy_cagr=3.0, benchmark_cagr=8.0),
    )
    monkeypatch.setattr(
        st_mod, "generate_structural_variants_for_config",
        lambda base_config, style_type, n=3: [{"logic": "AND", "conditions": [{"indicator": "rsi", "period": 14, "op": "<", "value": 20}]}],
    )

    result = st_mod.tune_strategy_for_group(["AAA"], REGIME_BASE_CONFIG, "성장주", "2020-01-01", "2021-12-31")

    assert result["backbone_changed"] is False
    # 구조 변형(조건 1개짜리 rsi 단독 전략)으로 안 바뀌고, 원본과 같은 구조(ma_cross+rsi 2조건)의
    # 숫자 튜닝 결과를 유지해야 한다 (모든 후보가 동점 sharpe라 정확히 어떤 숫자 조합이 뽑히는지는
    # 결정론적이지 않으므로, 원본 그대로인지가 아니라 "구조가 안 바뀌었는지"로 검증한다).
    assert len(result["group_config"]["conditions"]) == 2
    assert result["group_config"]["conditions"][0]["indicator"] == "ma_cross"
    assert result["group_config"]["conditions"][1]["indicator"] == "rsi"


def test_run_batch_tuning_groups_tickers_by_style_and_trains_each_regime_separately(monkeypatch):
    """같은 스타일 종목은 한 그룹으로 묶이고(SPEC 13절), 그 그룹은 국면(약세장/강세장/횡보장)마다 각각
    한 번씩 -- 총 3번 -- tune_strategy_for_group이 호출되어 종목당 결과가 국면별로 3행씩 나와야 한다."""
    tickers_df = pd.DataFrame({"ticker": ["A", "B", "C"], "sector": ["Utilities", "Utilities", "Energy"]})
    fake_styles = pd.DataFrame(
        {
            "ticker": ["A", "B", "C"],
            "sector": ["Utilities", "Utilities", "Energy"],
            "style_type": ["경기방어주", "경기방어주", "경기민감주"],
            "style_scores": [{"경기방어주": 90}, {"경기방어주": 80}, {"경기민감주": 70}],
        }
    )
    monkeypatch.setattr(st_mod, "compute_style_scores", lambda df, start, end: fake_styles)

    calls = []

    def _fake_group_tune(tickers, base_config, style_type, start, end, train_ratio=0.75, intensity="보통", regime=None, max_holding_days=None):
        calls.append((tuple(sorted(tickers)), style_type, regime))
        shared_config = {**base_config, "_style": style_type, "_regime": regime}
        return {
            "style_type": style_type,
            "tickers": tickers,
            "trained_regime": regime,
            "group_config": shared_config,
            "backbone_changed": False,
            "group_mean_excess_return": 1.0,
            "group_win_ratio": 1.0,
            "health_warnings": [],
            "per_ticker_train_metrics": {t: _metrics() for t in tickers},
            "per_ticker_test_comparison": {
                t: {"strategy": {"cagr": 15.0}, "buy_and_hold_ticker": {"cagr": 10.0}, "buy_and_hold_benchmark": {"cagr": 10.0}}
                for t in tickers
            },
            "insufficient_regime_data": False,
            "regime_matched_test": None,
        }

    monkeypatch.setattr(st_mod, "tune_strategy_for_group", _fake_group_tune)

    results = st_mod.run_batch_tuning(REGIME_BASE_CONFIG, tickers_df, "2020-01-01", "2021-01-01")

    assert set(calls) == {
        (("A", "B"), "경기방어주", "약세장"), (("A", "B"), "경기방어주", "강세장"), (("A", "B"), "경기방어주", "횡보장"),
        (("C",), "경기민감주", "약세장"), (("C",), "경기민감주", "강세장"), (("C",), "경기민감주", "횡보장"),
    }
    assert len(results) == 9  # 3종목 x 3국면
    a_rows = [r for r in results if r["ticker"] == "A"]
    b_rows = [r for r in results if r["ticker"] == "B"]
    c_rows = [r for r in results if r["ticker"] == "C"]
    assert {r["trained_regime"] for r in a_rows} == {"약세장", "강세장", "횡보장"}
    for regime in ("약세장", "강세장", "횡보장"):
        a_row = next(r for r in a_rows if r["trained_regime"] == regime)
        b_row = next(r for r in b_rows if r["trained_regime"] == regime)
        c_row = next(r for r in c_rows if r["trained_regime"] == regime)
        assert a_row["tuned_config"] == b_row["tuned_config"]  # 같은 그룹·국면 -> 동일 config
        assert a_row["tuned_config"] != c_row["tuned_config"]  # 다른 그룹 -> 다른 config
        assert a_row["excess_return"] == pytest.approx(5.0)


def test_run_batch_tuning_continues_after_single_group_failure(monkeypatch):
    """한 스타일×국면 조합의 튜닝이 통째로 실패해도 나머지 조합은 계속 진행되어야 한다."""
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

    def _fake_group_tune(tickers, base_config, style_type, start, end, train_ratio=0.75, intensity="보통", regime=None, max_holding_days=None):
        if style_type == "경기민감주":
            raise RuntimeError("데이터 조회 실패")
        return {
            "style_type": style_type, "tickers": tickers, "trained_regime": regime,
            "group_config": base_config, "backbone_changed": False,
            "group_mean_excess_return": 1.0, "group_win_ratio": 1.0, "health_warnings": [],
            "per_ticker_train_metrics": {t: _metrics() for t in tickers},
            "per_ticker_test_comparison": {
                t: {"strategy": {"cagr": 1.0}, "buy_and_hold_ticker": {"cagr": 0.0}, "buy_and_hold_benchmark": {"cagr": 0.0}}
                for t in tickers
            },
            "insufficient_regime_data": False,
            "regime_matched_test": None,
        }

    monkeypatch.setattr(st_mod, "tune_strategy_for_group", _fake_group_tune)

    results = st_mod.run_batch_tuning({"logic": "AND", "conditions": []}, tickers_df, "2020-01-01", "2021-01-01")
    assert len(results) == 6  # OK: 3국면 성공, BAD: 3국면 실패
    ok_rows = [r for r in results if r["ticker"] == "OK"]
    bad_rows = [r for r in results if r["ticker"] == "BAD"]
    assert len(ok_rows) == 3 and len(bad_rows) == 3
    assert {r["trained_regime"] for r in ok_rows} == {"약세장", "강세장", "횡보장"}
    assert {r["trained_regime"] for r in bad_rows} == {"약세장", "강세장", "횡보장"}
    for r in ok_rows:
        assert r["excess_return"] == 1.0
        assert r["style_type"] == "경기방어주"
    for r in bad_rows:
        assert "error" in r
        assert r["style_type"] == "경기민감주"


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


# weight(stage 진입/청산 비중) 튜닝 — 2026-07-15 사용자 확정: 각 stage weight를 독립적으로 흔들되
# entry_stages/exit_stages 각각 합계는 항상 1.0으로 재정규화(총 진입/청산 비중이 100%를 벗어나
# 레버리지/미투자가 생기지 않게 함).


def test_build_param_grid_varies_stage_weights():
    candidates = st_mod.build_param_grid(BOLLINGER_1_2_6, "성장주", "정밀")
    entry_stage1_weights = {c["entry_stages"][0]["weight"] for c in candidates}
    assert len(entry_stage1_weights) > 1  # weight도 이제 흔들려야 한다


def test_build_param_grid_normalizes_stage_weight_sums_to_one():
    """BOLLINGER_1_2_6의 원본 weight 합은 0.1+0.2+0.6=0.9(1.0이 아님)지만, 튜닝된 후보는 항상 합이
    1.0(100%)이 되도록 재정규화되어야 한다(2026-07-15 사용자 확정). 예외는 목록에 그대로 덧붙는
    "원본 폴백" 후보 하나뿐 — 그건 원본 그대로 남아야 다른 후보와 정직하게 비교할 수 있다."""
    candidates = st_mod.build_param_grid(BOLLINGER_1_2_6, "주도주", "정밀")
    assert len(candidates) > 1
    assert BOLLINGER_1_2_6 in candidates  # 원본 폴백은 재정규화되지 않고 그대로 포함되어야 한다

    tuned_candidates = [c for c in candidates if c != BOLLINGER_1_2_6]
    assert tuned_candidates  # 폴백 말고도 실제 튜닝된 후보가 있어야 함
    for c in tuned_candidates:
        entry_sum = sum(s["weight"] for s in c["entry_stages"])
        exit_sum = sum(s["weight"] for s in c["exit_stages"])
        assert entry_sum == pytest.approx(1.0, abs=1e-3)
        assert exit_sum == pytest.approx(1.0, abs=1e-3)


def test_build_param_grid_single_stage_weight_untouched():
    """stage가 1개뿐이면(합계를 흔들 대상이 없음) weight는 원본 그대로 유지되어야 한다."""
    config = {
        "entry_stages": [
            {"weight": 1.0, "logic": "AND", "conditions": [{"indicator": "rsi_cross", "period": 14, "level": 30, "direction": "up"}]}
        ],
        "exit_stages": [
            {"weight": 1.0, "logic": "AND", "conditions": [{"indicator": "rsi_cross", "period": 14, "level": 70, "direction": "down"}]}
        ],
    }
    candidates = st_mod.build_param_grid(config, "성장주", "정밀")
    for c in candidates:
        assert c["entry_stages"][0]["weight"] == 1.0
        assert c["exit_stages"][0]["weight"] == 1.0


def test_normalize_stage_weights_rescales_to_one():
    """원본 합계(0.9)와 무관하게 항상 1.0으로 맞춰야 한다(2026-07-15 사용자 확정)."""
    candidate = copy.deepcopy(BOLLINGER_1_2_6)
    candidate["entry_stages"][0]["weight"] = 0.13
    st_mod._normalize_stage_weights(candidate)
    assert sum(s["weight"] for s in candidate["entry_stages"]) == pytest.approx(1.0, abs=1e-4)
    # 비율은 유지되어야 한다: 0.13 : 0.2 : 0.6 정규화 결과가 원래 비율과 같은 방향
    assert candidate["entry_stages"][0]["weight"] < candidate["entry_stages"][2]["weight"]


def test_describe_tunable_params_includes_stage_weights():
    rows = st_mod.describe_tunable_params(BOLLINGER_1_2_6)
    weight_rows = [r for r in rows if r["key"] == "weight"]
    assert len(weight_rows) == 6  # entry_stages 3개 + exit_stages 3개
    assert {r["category"] for r in weight_rows} == {"비중배분"}
    assert {r["path"] for r in weight_rows} == {
        "entry_stages[0]", "entry_stages[1]", "entry_stages[2]",
        "exit_stages[0]", "exit_stages[1]", "exit_stages[2]",
    }


def test_describe_tunable_params_no_weight_rows_for_regime_config():
    """entry_stages/exit_stages가 아예 없는 레짐(AND/OR flat) 전략은 weight 미리보기 대상이 없다."""
    rows = st_mod.describe_tunable_params(REGIME_BASE_CONFIG)
    assert not any(r["key"] == "weight" for r in rows)


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


# describe_tunable_params — 실행 전 미리보기 (build_param_grid와 같은 분류/범위 공식을 공유해야 함)


def test_describe_tunable_params_lists_all_six_styles_per_param():
    rows = st_mod.describe_tunable_params(BOLLINGER_1_2_6)
    assert rows  # 볼린저/RSI 파라미터가 여럿 있으므로 비어있으면 안 됨
    for row in rows:
        assert set(row["style_ranges"].keys()) == set(st_mod.STYLE_TYPES)
        lo, hi = row["style_ranges"]["성장주"]
        assert lo <= hi


def test_describe_tunable_params_matches_build_param_grid_bounds():
    """미리보기가 보여주는 스타일별 범위가 build_param_grid가 실제로 탐색하는 3값 집합{하한,원본,상한}과
    정확히 일치해야 한다 — 미리보기가 실제 탐색과 다른 숫자를 보여주면 사용자를 오도하게 되므로 이
    일치가 핵심. (배수가 1.0 미만인 스타일은 상한이 원본보다 작을 수 있어 min/max가 아니라 집합으로
    비교한다.)"""
    rows = st_mod.describe_tunable_params(REGIME_BASE_CONFIG)
    short_row = next(r for r in rows if r["key"] == "short")
    original = REGIME_BASE_CONFIG["conditions"][0]["short"]

    for style in st_mod.STYLE_TYPES:
        candidates = st_mod.build_param_grid(REGIME_BASE_CONFIG, style, "정밀")
        actual_values = {c["conditions"][0]["short"] for c in candidates}
        lo, hi = short_row["style_ranges"][style]
        assert actual_values == {lo, int(round(original)), hi}


def test_describe_tunable_params_preserves_backbone_fields_excluded():
    """indicator/direction/band 같은 구조 필드는 미리보기 대상에 나오면 안 된다(숫자만 튜닝 대상)."""
    rows = st_mod.describe_tunable_params(BOLLINGER_1_2_6)
    keys_seen = {r["key"] for r in rows}
    assert "indicator" not in keys_seen
    assert "direction" not in keys_seen
    assert "band" not in keys_seen


def test_describe_tunable_params_no_tunable_params_returns_empty():
    config = {"logic": "AND", "conditions": [{"indicator": "engulfing", "direction": "bullish"}]}
    assert st_mod.describe_tunable_params(config) == []


def test_describe_tunable_params_expression_schema_returns_empty():
    assert st_mod.describe_tunable_params(EXPRESSION_BASE_CONFIG) == []


def test_describe_tunable_params_expression_matches_build_expression_param_grid_bounds(monkeypatch):
    """미리보기 범위가 build_param_grid(expression 스키마)가 실제로 탐색하는 범위와 일치해야 한다."""
    sma_period_literal = st_mod._extract_numeric_literals(EXPRESSION_BASE_CONFIG["expression"])[0]
    fake_tunables = [{**sma_period_literal, "role": "기간", "suggested_min": 10.0, "suggested_max": 30.0}]
    monkeypatch.setattr(st_mod, "identify_tunable_numbers", lambda expr: fake_tunables)

    rows = st_mod.describe_tunable_params_expression(fake_tunables)
    assert len(rows) == 1
    assert set(rows[0]["style_ranges"].keys()) == set(st_mod.STYLE_TYPES)

    for style in st_mod.STYLE_TYPES:
        candidates = st_mod.build_param_grid(EXPRESSION_BASE_CONFIG, style, "정밀")
        actual_periods = {st_mod._extract_numeric_literals(c["expression"])[0]["value"] for c in candidates}
        lo, hi = rows[0]["style_ranges"][style]
        assert min(actual_periods) == lo
        assert max(actual_periods) == hi


def test_build_param_grid_new_bollinger_indicators_preserves_structure_and_varies_numeric_params():
    """볼린저 응용 매매법 4종 신규 파라미터(threshold/lookback/hold_bars/band_period/band_std/
    pivot_lookback/pattern_window/volume_mult/rsi_period)가 build_param_grid에서 인식되어 여러
    값으로 흔들리면서도, 지표 종류/방향 등 백본은 그대로 유지되는지 확인한다."""
    candidates = st_mod.build_param_grid(NEW_INDICATORS_STAGED_CONFIG, "성장주", "정밀")
    assert len(candidates) > 1

    for c in candidates:
        squeeze = c["entry_stages"][0]["conditions"][0]
        divergence = c["entry_stages"][1]["conditions"][0]
        pattern = c["exit_stages"][0]["conditions"][0]
        assert squeeze["indicator"] == "bbw_squeeze_release"
        assert divergence["indicator"] == "rsi_divergence"
        assert divergence["direction"] == "bullish"
        assert pattern["indicator"] == "double_pattern"
        assert pattern["direction"] == "bearish"
        # threshold/volume_mult는 항상 양수인 비율/승수라 0 이하로 내려가면 안 된다.
        assert squeeze["threshold"] > 0
        assert pattern["volume_mult"] > 0
        assert pattern["band_std"] > 0

    def _values(extract):
        return {extract(c) for c in candidates}

    assert len(_values(lambda c: c["entry_stages"][0]["conditions"][0]["threshold"])) > 1
    assert len(_values(lambda c: c["entry_stages"][0]["conditions"][0]["lookback"])) > 1
    assert len(_values(lambda c: c["entry_stages"][0]["conditions"][0]["hold_bars"])) > 1
    assert len(_values(lambda c: c["entry_stages"][1]["conditions"][0]["rsi_period"])) > 1
    assert len(_values(lambda c: c["entry_stages"][1]["conditions"][0]["band_period"])) > 1
    assert len(_values(lambda c: c["entry_stages"][1]["conditions"][0]["pivot_lookback"])) > 1
    assert len(_values(lambda c: c["entry_stages"][1]["conditions"][0]["pattern_window"])) > 1
    assert len(_values(lambda c: c["exit_stages"][0]["conditions"][0]["band_period"])) > 1
    assert len(_values(lambda c: c["exit_stages"][0]["conditions"][0]["band_std"])) > 1
    assert len(_values(lambda c: c["exit_stages"][0]["conditions"][0]["pivot_lookback"])) > 1
    assert len(_values(lambda c: c["exit_stages"][0]["conditions"][0]["pattern_window"])) > 1
    assert len(_values(lambda c: c["exit_stages"][0]["conditions"][0]["volume_mult"])) > 1


def test_build_param_grid_style_direction_new_period_like_keys():
    """새로 _PERIOD_LIKE_KEYS에 추가된 키(rsi_period)도 기존 short/long과 동일하게 스타일 방향성
    (주도주=짧게, 경기방어주=길게)을 따르는지 확인한다."""
    leader_candidates = st_mod.build_param_grid(NEW_INDICATORS_STAGED_CONFIG, "주도주", "정밀")
    defensive_candidates = st_mod.build_param_grid(NEW_INDICATORS_STAGED_CONFIG, "경기방어주", "정밀")
    original_rsi_period = NEW_INDICATORS_STAGED_CONFIG["entry_stages"][1]["conditions"][0]["rsi_period"]

    leader_min = min(c["entry_stages"][1]["conditions"][0]["rsi_period"] for c in leader_candidates)
    defensive_max = max(c["entry_stages"][1]["conditions"][0]["rsi_period"] for c in defensive_candidates)
    assert leader_min < original_rsi_period
    assert defensive_max > original_rsi_period


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

    def _fake_run(ticker, cfg, start, end, label="전략", max_holding_days=None):
        short = cfg["conditions"][0].get("short", 0)
        sharpe = 5.0 if short == best_short else 0.1
        return SimpleNamespace(metrics=_metrics(sharpe=sharpe))

    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(st_mod, "run_backtest", _fake_run)
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end, max_holding_days=None: _fake_test_comparison(strategy_cagr=15.0, benchmark_cagr=10.0),
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
        st_mod, "run_backtest", lambda ticker, cfg, start, end, label="전략", max_holding_days=None: SimpleNamespace(metrics=_metrics(sharpe=1.0))
    )
    monkeypatch.setattr(
        st_mod, "compare_with_benchmarks",
        lambda ticker, cfg, start, end: _fake_test_comparison(strategy_cagr=5.0, benchmark_cagr=4.0),
    )

    result = st_mod.tune_strategy_for_ticker("TEST", BOLLINGER_1_2_6, "주도주", "2020-01-01", "2021-12-31")
    assert result["tuned_config"]["entry_stages"][0]["conditions"][0].get("std_dev") != 2.5
    assert result["health_warnings"] == []


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
            "tuning_trail": [{"mean_sharpe": 1.5, "std_sharpe": 0.1, "score": 1.45}],
            "trained_regime": "약세장", "insufficient_regime_data": False,
            "regime_matched_test": {"segment_start": "2020-06-01", "segment_end": "2020-09-01", "mean_excess_return": 3.0},
        },
        {"ticker": "BBB", "sector": "Energy", "trained_regime": "강세장", "error": "실패"},
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
    assert aaa["tuning_trail"] == [{"mean_sharpe": 1.5, "std_sharpe": 0.1, "score": 1.45}]
    assert aaa["trained_regime"] == "약세장"
    assert aaa["insufficient_regime_data"] is False
    assert aaa["regime_matched_test"] == {
        "segment_start": "2020-06-01", "segment_end": "2020-09-01", "mean_excess_return": 3.0
    }

    bbb = next(r for r in fetched["results"] if r["ticker"] == "BBB")
    assert bbb["error"] == "실패"
    assert bbb["tuned_config"] is None
    assert bbb["health_warnings"] == []
    assert bbb["tuning_trail"] == []
    assert bbb["backbone_changed"] is False  # 명시 안 하면 기본값 False
    assert bbb["trained_regime"] == "강세장"
    assert bbb["insufficient_regime_data"] is False  # 명시 안 하면 기본값 False
    assert bbb["regime_matched_test"] is None

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
        lambda base_config, tickers_df, start, end, train_ratio, intensity, max_holding_days=None: [
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


def test_run_and_save_tuning_threads_and_persists_max_holding_days(db_session, monkeypatch):
    """SPEC 15절 스윙 트레이딩 모드 — max_holding_days가 run_batch_tuning에 그대로 전달되고,
    저장된 StrategyTuningRun에서 list_tuning_runs()/get_tuning_run() 양쪽으로 다시 읽힐 수 있어야
    한다(UI 이력 표/재현성을 위해)."""
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)

    captured = {}

    def _fake_run_batch_tuning(base_config, tickers_df, start, end, train_ratio, intensity, max_holding_days=None):
        captured["max_holding_days"] = max_holding_days
        return [
            {
                "ticker": t, "style_type": "주도주", "sector": "Utilities", "style_scores": {},
                "tuned_config": base_config, "train_metrics": {}, "test_comparison": {},
                "excess_return": 0.0, "health_warnings": [],
            }
            for t in tickers_df["ticker"]
        ]

    monkeypatch.setattr(st_mod, "run_batch_tuning", _fake_run_batch_tuning)

    manual_df = pd.DataFrame({"ticker": ["NVDA"], "sector": ["Information Technology"]})
    run_id = st_mod.run_and_save_tuning(
        BOLLINGER_1_2_6, 100, "2020-01-01", "2021-01-01", tickers_df=manual_df,
        max_holding_days=st_mod._SWING_MAX_HOLDING_DAYS,
    )

    assert captured["max_holding_days"] == 126
    fetched = st_mod.get_tuning_run(run_id)
    assert fetched["max_holding_days"] == 126
    history_row = next(h for h in st_mod.list_tuning_runs() if h["id"] == run_id)
    assert history_row["max_holding_days"] == 126


def test_run_and_save_tuning_falls_back_to_sample_universe_when_no_tickers_df(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(
        st_mod, "sample_universe",
        lambda n, use_cache=True, random_seed=None, as_of_date=None: pd.DataFrame(
            {"ticker": ["AAPL"], "sector": ["Information Technology"]}
        ),
    )
    monkeypatch.setattr(
        st_mod, "run_batch_tuning",
        lambda base_config, tickers_df, start, end, train_ratio, intensity, max_holding_days=None: [
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


# ----------------------------------------------------------------------------
# select_live_strategy (SPEC 13.9절 — 라이브 국면 판단 확정, 2026-07-17)
# ----------------------------------------------------------------------------


def _bear_regime_df():
    """classify_daily_regime이 마지막 날을 "약세장"으로 판정하도록 -20%+ 급락하는 합성 OHLC."""
    idx = pd.date_range("2024-01-01", periods=260, freq="B")
    climb = np.linspace(100.0, 200.0, 230)
    crash = np.linspace(200.0, 100.0, 31)[1:]
    close = pd.Series(list(climb) + list(crash), index=idx, name="Close")
    return pd.DataFrame({"Close": close, "High": close * 1.01, "Low": close * 0.99}, index=idx)


def _bull_regime_df():
    """classify_daily_regime이 마지막 날을 "강세장"으로 판정하도록 꾸준히 오르는 합성 OHLC."""
    idx = pd.date_range("2024-01-01", periods=260, freq="B")
    close = pd.Series(np.linspace(100.0, 200.0, 260), index=idx, name="Close")
    return pd.DataFrame({"Close": close, "High": close * 1.01, "Low": close * 0.99}, index=idx)


def _sideways_regime_df():
    """classify_daily_regime이 마지막 날을 "횡보장"으로 판정하도록 거의 안 움직이는 합성 OHLC."""
    idx = pd.date_range("2024-01-01", periods=260, freq="B")
    rng = np.random.default_rng(0)
    close = pd.Series(100.0 + rng.normal(0, 0.05, len(idx)), index=idx, name="Close")
    return pd.DataFrame({"Close": close, "High": close * 1.001, "Low": close * 0.999}, index=idx)


def test_select_live_strategy_picks_bear_strategy_when_regime_is_bear(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    from core.models import Strategy as StrategyModel

    bear = StrategyModel(name="약세장용", indicator_config=json.dumps({"a": 1}), source="test")
    bull = StrategyModel(name="강세장용", indicator_config=json.dumps({"b": 2}), source="test")
    sideways = StrategyModel(name="횡보장용", indicator_config=json.dumps({"c": 3}), source="test")
    db_session.add_all([bear, bull, sideways])
    db_session.commit()

    monkeypatch.setattr(st_mod, "get_price_history", lambda *a, **k: _bear_regime_df())

    result = st_mod.select_live_strategy(bear.id, bull.id, sideways.id)

    assert result["trading_regime"] == "약세장"
    assert result["selected_strategy_id"] == bear.id
    assert result["selected_strategy_name"] == "약세장용"
    assert result["selected_config"] == {"a": 1}


def test_select_live_strategy_picks_bull_strategy_when_regime_is_bull(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    from core.models import Strategy as StrategyModel

    bear = StrategyModel(name="약세장용", indicator_config=json.dumps({"a": 1}), source="test")
    bull = StrategyModel(name="강세장용", indicator_config=json.dumps({"b": 2}), source="test")
    sideways = StrategyModel(name="횡보장용", indicator_config=json.dumps({"c": 3}), source="test")
    db_session.add_all([bear, bull, sideways])
    db_session.commit()

    monkeypatch.setattr(st_mod, "get_price_history", lambda *a, **k: _bull_regime_df())

    result = st_mod.select_live_strategy(bear.id, bull.id, sideways.id)

    assert result["trading_regime"] == "강세장"
    assert result["selected_strategy_id"] == bull.id
    assert result["selected_config"] == {"b": 2}


def test_select_live_strategy_picks_sideways_strategy_when_regime_is_sideways(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    from core.models import Strategy as StrategyModel

    bear = StrategyModel(name="약세장용", indicator_config=json.dumps({"a": 1}), source="test")
    bull = StrategyModel(name="강세장용", indicator_config=json.dumps({"b": 2}), source="test")
    sideways = StrategyModel(name="횡보장용", indicator_config=json.dumps({"c": 3}), source="test")
    db_session.add_all([bear, bull, sideways])
    db_session.commit()

    monkeypatch.setattr(st_mod, "get_price_history", lambda *a, **k: _sideways_regime_df())

    result = st_mod.select_live_strategy(bear.id, bull.id, sideways.id)

    assert result["trading_regime"] == "횡보장"
    assert result["selected_strategy_id"] == sideways.id
    assert result["selected_config"] == {"c": 3}


def test_select_live_strategy_no_price_data_returns_none_selection(monkeypatch):
    monkeypatch.setattr(st_mod, "get_price_history", lambda *a, **k: pd.DataFrame())
    result = st_mod.select_live_strategy(1, 2, 3)
    assert result["trading_regime"] is None
    assert result["selected_strategy_id"] is None
    assert result["selected_config"] is None
    assert "reason" in result


def test_select_live_strategy_missing_strategy_row_returns_none_selection(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(st_mod, "get_price_history", lambda *a, **k: _bear_regime_df())

    result = st_mod.select_live_strategy(9999, 9998, 9997)

    assert result["trading_regime"] == "약세장"
    assert result["selected_strategy_id"] is None
    assert result["selected_config"] is None


# ----------------------------------------------------------------------------
# classify_ticker_trend / classify_tickers_by_trend / select_strategy_for_ticker_trend
# (SPEC 14절 — 종목 자체 추세 기준 데이터셋 분리, 2026-07-17)
# ----------------------------------------------------------------------------


def _price_df(prices: list[float], start="2020-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(prices), freq="B")
    return pd.DataFrame({"Close": prices}, index=idx)


def test_classify_ticker_trend_detects_bullish():
    # 100 -> 300 over ~2 years: CAGR 훨씬 큰 상승
    df = _price_df([100.0, 300.0])
    df.index = pd.to_datetime(["2020-01-01", "2022-01-01"])
    assert st_mod.classify_ticker_trend(df) == "상승"


def test_classify_ticker_trend_detects_bearish():
    df = _price_df([100.0, 40.0])
    df.index = pd.to_datetime(["2020-01-01", "2022-01-01"])
    assert st_mod.classify_ticker_trend(df) == "하락"


def test_classify_ticker_trend_detects_sideways():
    df = _price_df([100.0, 105.0])
    df.index = pd.to_datetime(["2020-01-01", "2022-01-01"])
    assert st_mod.classify_ticker_trend(df) == "횡보"


def test_classify_ticker_trend_none_for_empty_or_insufficient_data():
    assert st_mod.classify_ticker_trend(pd.DataFrame()) is None
    assert st_mod.classify_ticker_trend(None) is None
    assert st_mod.classify_ticker_trend(_price_df([100.0])) is None


def test_classify_tickers_by_trend_skips_failed_lookups_and_falls_back_to_sideways_when_too_few(monkeypatch):
    """유효 종목이 3개 미만이면 3분위(상대순위)를 나눌 수 없어 전부 '횡보'로 처리해야 한다."""
    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True):
        if ticker == "BAD":
            raise RuntimeError("조회 실패")
        if ticker == "UP":
            df = _price_df([100.0, 300.0])
            df.index = pd.to_datetime(["2020-01-01", "2022-01-01"])
            return df
        df = _price_df([100.0, 40.0])
        df.index = pd.to_datetime(["2020-01-01", "2022-01-01"])
        return df

    monkeypatch.setattr(st_mod, "get_price_history", _fake_get_price_history)

    result = st_mod.classify_tickers_by_trend(["UP", "DOWN", "BAD"], "2020-01-01", "2022-01-01")

    assert result == {"UP": "횡보", "DOWN": "횡보"}
    assert "BAD" not in result


def test_classify_tickers_by_trend_uses_relative_tertiles_even_without_absolute_decliners(monkeypatch):
    """생존편향으로 절대 CAGR이 전부 플러스여도(하락 종목이 하나도 없어도), 상대적으로 가장
    부진한 1/3은 '하락'으로, 가장 좋은 1/3은 '상승'으로 분류돼야 한다(SPEC 14절 핵심 근거)."""
    # 6종목의 CAGR을 전부 양수로 구성(생존편향 시뮬레이션)하되 순위는 뚜렷하게 벌려둔다.
    cagr_by_ticker = {"A": 1.0, "B": 3.0, "C": 5.0, "D": 40.0, "E": 45.0, "F": 50.0}

    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True):
        target_cagr = cagr_by_ticker[ticker] / 100.0
        end_price = 100.0 * (1 + target_cagr) ** 2  # 2년 구간
        df = _price_df([100.0, end_price])
        df.index = pd.to_datetime(["2020-01-01", "2022-01-01"])
        return df

    monkeypatch.setattr(st_mod, "get_price_history", _fake_get_price_history)

    result = st_mod.classify_tickers_by_trend(list(cagr_by_ticker), "2020-01-01", "2022-01-01")

    assert result["A"] == "하락" and result["B"] == "하락"  # 하위 1/3 (모두 절대적으로는 플러스)
    assert result["E"] == "상승" and result["F"] == "상승"  # 상위 1/3
    assert result["C"] == "횡보" and result["D"] == "횡보"  # 중간


def test_select_strategy_for_ticker_trend_picks_matching_strategy(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake_get_session)
    from core.models import Strategy as StrategyModel

    bear = StrategyModel(name="하락장용", indicator_config=json.dumps({"a": 1}), source="test")
    bull = StrategyModel(name="상승장용", indicator_config=json.dumps({"b": 2}), source="test")
    sideways = StrategyModel(name="횡보장용", indicator_config=json.dumps({"c": 3}), source="test")
    db_session.add_all([bear, bull, sideways])
    db_session.commit()

    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True):
        df = _price_df([100.0, 300.0])
        df.index = pd.to_datetime(["2025-01-01", "2026-07-01"])
        return df

    monkeypatch.setattr(st_mod, "get_price_history", _fake_get_price_history)

    result = st_mod.select_strategy_for_ticker_trend("NVDA", bear.id, bull.id, sideways.id)

    assert result["trend"] == "상승"
    assert result["selected_strategy_id"] == bull.id
    assert result["selected_config"] == {"b": 2}


def test_select_strategy_for_ticker_trend_none_when_price_lookup_fails(monkeypatch):
    def _fake_get_price_history(ticker, start=None, end=None, use_cache=True):
        raise RuntimeError("조회 실패")

    monkeypatch.setattr(st_mod, "get_price_history", _fake_get_price_history)

    result = st_mod.select_strategy_for_ticker_trend("XYZ", 1, 2, 3)

    assert result["trend"] is None
    assert result["selected_strategy_id"] is None
