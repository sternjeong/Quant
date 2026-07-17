"""core/era_validation.py 단위 테스트 (여러 시대 워크포워드 검증).

네트워크(yfinance)를 타지 않도록 compare_with_benchmarks / get_constituents_as_of를 모두
monkeypatch로 대체한다 (tests/test_strategy_tuning.py의 monkeypatch 스타일을 따름).
"""

from types import SimpleNamespace

import pytest

import core.era_validation as ev_mod

FAKE_CONFIG = {"expression": "close > sma(close, 20)"}

FOUR_ERAS = [
    {"name": "시대1", "start": "2000-01-01", "end": "2000-12-31", "character": "테스트용"},
    {"name": "시대2", "start": "2008-01-01", "end": "2008-12-31", "character": "테스트용"},
    {"name": "시대3", "start": "2020-01-01", "end": "2020-12-31", "character": "테스트용"},
    {"name": "시대4", "start": "2022-01-01", "end": "2022-12-31", "character": "테스트용"},
]


def _run(cagr: float) -> SimpleNamespace:
    return SimpleNamespace(metrics={"cagr": cagr})


def _fake_compare_factory(strategy_cagr_by_ticker: dict, bh_cagr: float = 5.0):
    def _fake_compare(ticker, config, start, end):
        return {
            "strategy": _run(strategy_cagr_by_ticker.get(ticker, 0.0)),
            "buy_and_hold_ticker": _run(bh_cagr),
            "buy_and_hold_benchmark": _run(bh_cagr),
        }

    return _fake_compare


def test_ticker_not_in_pit_universe_is_skipped_not_crashed(monkeypatch):
    """PIT 유니버스에 없는 종목은 그 시대에서 크래시 없이 건너뛰어야 한다."""
    monkeypatch.setattr(
        ev_mod.point_in_time_universe, "get_constituents_as_of", lambda as_of: ["AAA"]
    )
    monkeypatch.setattr(
        ev_mod, "compare_with_benchmarks", _fake_compare_factory({"AAA": 10.0})
    )

    result = ev_mod.validate_across_eras(FAKE_CONFIG, ["AAA", "BBB"], eras=FOUR_ERAS[:1])

    era_result = result["per_era"]["시대1"]
    assert era_result["n_tickers_tested"] == 1
    assert era_result["n_tickers_skipped_no_pit_data"] == 1
    assert "BBB" not in era_result["tickers"]
    assert "AAA" in era_result["tickers"]


def test_era_robustness_score_computes_correctly(monkeypatch):
    """4개 시대 중 2개 시대만 평균 초과수익률이 양수면 score는 0.5여야 한다."""
    monkeypatch.setattr(
        ev_mod.point_in_time_universe, "get_constituents_as_of", lambda as_of: ["AAA"]
    )

    # 시대1/시대2는 전략이 이기고(양수 초과수익), 시대3/시대4는 전략이 진다(음수 초과수익).
    def _fake_compare(ticker, config, start, end):
        winning_eras_cagr = {"2000-01-01": 20.0, "2008-01-01": 20.0, "2020-01-01": 1.0, "2022-01-01": 1.0}
        strat_cagr = winning_eras_cagr[start]
        return {
            "strategy": _run(strat_cagr),
            "buy_and_hold_ticker": _run(10.0),
            "buy_and_hold_benchmark": _run(10.0),
        }

    monkeypatch.setattr(ev_mod, "compare_with_benchmarks", _fake_compare)

    result = ev_mod.validate_across_eras(FAKE_CONFIG, ["AAA"], eras=FOUR_ERAS)

    assert result["era_robustness_score"] == pytest.approx(0.5)
    assert result["eras_used"] == ["시대1", "시대2", "시대3", "시대4"]


def test_run_backtest_exception_for_one_ticker_does_not_crash_era(monkeypatch):
    """한 종목의 백테스트가 예외를 던져도 해당 시대의 다른 종목들은 계속 처리돼야 한다."""
    monkeypatch.setattr(
        ev_mod.point_in_time_universe, "get_constituents_as_of", lambda as_of: ["AAA", "BBB", "CCC"]
    )

    def _fake_compare(ticker, config, start, end):
        if ticker == "BBB":
            raise ValueError("가격 데이터 부족")
        return {
            "strategy": _run(15.0),
            "buy_and_hold_ticker": _run(5.0),
            "buy_and_hold_benchmark": _run(5.0),
        }

    monkeypatch.setattr(ev_mod, "compare_with_benchmarks", _fake_compare)

    result = ev_mod.validate_across_eras(FAKE_CONFIG, ["AAA", "BBB", "CCC"], eras=FOUR_ERAS[:1])

    era_result = result["per_era"]["시대1"]
    assert era_result["n_tickers_tested"] == 2  # AAA, CCC만 성공
    assert era_result["tickers"]["BBB"]["error"] == "가격 데이터 부족"
    assert era_result["tickers"]["AAA"]["excess_return"] == pytest.approx(10.0)
    assert era_result["tickers"]["CCC"]["excess_return"] == pytest.approx(10.0)
    assert era_result["mean_excess_return"] == pytest.approx(10.0)
