"""core/strategy_tuning.py 단위 테스트 (모듈 A 확장: 다종목 미세튜닝 엔진).

테스트용 대표 전략으로 "볼린저 밴드 하단 반전 1:2:6 전략"을 사용한다: 밴드 하단 이탈(10%) ->
상승 인걸 캔들 확인(+20%) -> RSI 30 상향 돌파로 반전 확인(+60%) 순으로 분할 진입하고, 상단 도달(10%)
-> RSI 70 상향 돌파(+20%) -> RSI 50 하향 이탈(잔량 전부, 반전 실패 시 청산) 순으로 분할 청산한다.
진입 조건(하단/인걸/RSI상향)과 청산 조건(상단/RSI과매수/RSI하향)이 방향상 겹치지 않아
진입=청산 자기모순(PROGRESS.md에 기록된 기존 버그 패턴) 없이 안전하게 설계되어 있다.

네트워크(yfinance)를 타지 않도록 관련 함수를 모두 monkeypatch 로 대체한다.
"""

from types import SimpleNamespace

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


# ----------------------------------------------------------------------------
# describe_tuning_diff / summarize_tuning_diff — 야간 리더보드 상세보기 (2026-07-16)
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# compute_style_scores
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# build_param_grid — 볼린저 1:2:6 전략(staged)과 레짐 전략 둘 다 검증
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# expression 전략 전용 Gemini 튜닝 (identify_tunable_numbers / build_param_grid 확장 /
# generate_structural_variants / tune_expression_strategy_for_ticker)
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# tune_strategy_for_group / run_batch_tuning (2026-07-15부터: 종목별 독립 탐색 -> 스타일 그룹 풀링)
# ----------------------------------------------------------------------------


_THREE_FOLDS = [("2020-01-01", "2020-04-01"), ("2020-04-02", "2020-07-01"), ("2020-07-02", "2020-10-01")]


# ----------------------------------------------------------------------------
# 과적합 진단: train 워크포워드 점수 vs test 성과 곡선 (2026-09-13)
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# 국면별(약세장/강세장) 분리 트레이닝 (SPEC 13절, 2026-07-16)
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# 짧은 구간 CAGR 연환산 아티팩트 + 순열검정/분해 테스트 유의성 통합 (2026-07-25)
#
# 사용자가 "야간 튜닝 결과가 그 종목에서는 이기는데 같은 섹터 다른 종목에 재학습 없이 적용하면
# 계속 진다"고 보고해 조사한 결과: (1) 국면 일치 test 세그먼트가 며칠~몇 주로 짧을 때 CAGR이
# 연환산 과정에서 폭발해(예: 2주 15% -> 연환산 1786%) 통계적으로 무의미한 값이 리더보드 1위를
# 차지하고 있었고, (2) backbone_changed 경로가 실제로는 test 성과로 backbone을 골라 데이터
# 스누핑이었으며, (3) "초과수익이 크다"와 "통계적으로 유의미한 엣지다"가 구분되지 않고 있었다.
# ----------------------------------------------------------------------------


# weight(stage 진입/청산 비중) 튜닝 — 2026-07-15 사용자 확정: 각 stage weight를 독립적으로 흔들되
# entry_stages/exit_stages 각각 합계는 항상 1.0으로 재정규화(총 진입/청산 비중이 100%를 벗어나
# 레버리지/미투자가 생기지 않게 함).


# describe_tunable_params — 실행 전 미리보기 (build_param_grid와 같은 분류/범위 공식을 공유해야 함)


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


def _fake_test_comparison(
    strategy_cagr,
    benchmark_cagr,
    ticker_cagr=0.0,
    strategy_return=None,
    benchmark_return=None,
    ticker_return=None,
    strategy_trade_count=10,
):
    """strategy_return/benchmark_return/ticker_return(cumulative_return)을 안 주면 대응하는
    *_cagr 값을 그대로 쓴다 — core.strategy_tuning이 excess_return을 cagr 대신
    cumulative_return으로 계산하도록 바뀐 뒤(2026-07-25)에도 숫자만 넘기는 기존 테스트가 값을
    그대로 재사용할 수 있게 하기 위함. 짧은 구간 CAGR 폭발 문제를 직접 검증하는 테스트는
    strategy_return 등을 cagr과 다르게 명시적으로 줘서 구분한다."""
    return {
        "strategy": SimpleNamespace(
            metrics=_metrics(
                cagr=strategy_cagr,
                cumulative_return=strategy_return if strategy_return is not None else strategy_cagr,
                sharpe=1.0, mdd=-5.0, trade_count=strategy_trade_count,
            )
        ),
        "buy_and_hold_ticker": SimpleNamespace(
            metrics=_metrics(cagr=ticker_cagr, cumulative_return=ticker_return if ticker_return is not None else ticker_cagr)
        ),
        "buy_and_hold_benchmark": SimpleNamespace(
            metrics=_metrics(cagr=benchmark_cagr, cumulative_return=benchmark_return if benchmark_return is not None else benchmark_cagr)
        ),
    }


# ----------------------------------------------------------------------------
# save_tuning_run / list_tuning_runs / get_tuning_run
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# select_live_strategy (SPEC 13.9절 — 라이브 국면 판단 확정, 2026-07-17)
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# classify_ticker_trend / classify_tickers_by_trend / select_strategy_for_ticker_trend
# (SPEC 14절 — 종목 자체 추세 기준 데이터셋 분리, 2026-07-17)
# ----------------------------------------------------------------------------


