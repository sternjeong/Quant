"""여러 시대(era)에 걸친 워크포워드 검증 — 시점 편향(time-period bias) 보완용 모듈.

`core/strategy_tuning.py`의 기존 train/test 분리는 하나의 연속된 과거 구간(예: train
2021-2023, test 2024-2025) 안에서만 검증한다. 이 구간 전체가 우연히 긴 강세장이었다면,
전략 로직이 실제로 가치를 더하지 않고 그냥 "계속 매수 상태 유지"만 해도 좋은 성과처럼 보일
위험이 있고, 성격이 다른 진짜 약세장/패닉/횡보장에서는 실패할 수 있다. 이 모듈은 이미
튜닝이 끝난(확정된) config를 재튜닝하지 않고, 성격이 뚜렷하게 다른 여러 역사적 시대에 그대로
다시 백테스트해 강건성을 확인한다.

`core/point_in_time_universe.py`가 종목 선정의 survivorship bias(생존편향)를 보완하는 모듈이라면,
이 모듈은 그 짝으로 시점 편향을 보완한다 — 이 둘은 서로 독립적으로 조합해서 쓸 수 있다.

이 core 패키지는 Streamlit에 의존하지 않는 것이 이 저장소의 관례이므로(core/market_data.py
상단 주석 참고), 이 모듈도 stateless/read-only로 유지한다 (DB 기록 없음, st.cache_data 없음).
"""

from __future__ import annotations

from typing import Any

from core import point_in_time_universe
from core.backtest_engine import compare_with_benchmarks

# 성격이 뚜렷하게 다른 역사적 시대들 (하드코딩 — 사용자 요청에 따라 잘 알려진 경계일 사용,
# 별도 웹 조회 없음). 5개 모두 "강세/약세/급락/급등/횡보"의 서로 다른 시장 성격을 대표한다.
MARKET_ERAS: list[dict] = [
    {
        "name": "닷컴버블 붕괴",
        "start": "2000-03-01",
        "end": "2002-10-01",
        "character": "장기 약세장/기술주 붕괴",
    },
    {
        "name": "글로벌 금융위기",
        "start": "2007-10-01",
        "end": "2009-03-01",
        "character": "패닉성 급락",
    },
    {
        "name": "코로나 충격 및 V자 회복",
        "start": "2020-02-01",
        "end": "2020-12-31",
        "character": "단기 급락 후 빠른 회복",
    },
    {
        "name": "2022 금리인상 약세장",
        "start": "2022-01-01",
        "end": "2022-12-31",
        "character": "완만한 장기 하락",
    },
    {
        "name": "2010년대 중반 횡보/조정 구간",
        "start": "2015-06-01",
        "end": "2016-06-01",
        "character": "박스권 횡보장/원유·중국발 조정",
    },
]


def validate_across_eras(
    config: dict,
    tickers: list[str],
    eras: list[dict] = MARKET_ERAS,
) -> dict:
    """이미 확정된 전략 config를, 재튜닝 없이 여러 역사적 시대에 그대로 재검증한다.

    각 시대마다, 각 종목이 그 시대 시작일 기준 실제 S&P500 구성종목이었는지
    (`point_in_time_universe.get_constituents_as_of`) 먼저 확인해 아니면 건너뛴다(그 시점에
    상장조차 안 됐거나 가격 데이터가 없는 경우가 많아 백테스트 자체가 무의미하기 때문).
    통과한 종목만 그 시대 [start, end] 구간에 대해 `compare_with_benchmarks`로 전략 대
    매수보유(개별종목) 성과를 비교한다. 개별 종목 백테스트가 예외를 던지면(데이터 부족 등)
    그 종목만 에러로 기록하고 해당 시대의 다른 종목들, 다른 시대들은 계속 처리한다.

    Args:
        config: 이미 튜닝/확정된 전략 config (JSON 스키마 또는 expression 스키마 모두 가능 —
            run_backtest/compare_with_benchmarks가 그대로 처리).
        tickers: 검증할 종목 티커 리스트.
        eras: 검증할 시대 목록(기본값 MARKET_ERAS). 각 dict는 최소 name/start/end 키를 가져야 함.

    Returns:
        {
            "per_era": {
                era_name: {
                    "mean_excess_return": float | None,   # 시대 평균 (전략 cagr - 종목 매수보유 cagr)
                    "win_ratio": float | None,             # 전략이 매수보유를 이긴 종목 비율
                    "n_tickers_tested": int,
                    "n_tickers_skipped_no_pit_data": int,  # PIT 유니버스 미포함으로 건너뛴 종목 수
                    "tickers": {ticker: {"excess_return": float, ...} | {"error": str}},
                },
                ...
            },
            "era_robustness_score": float,  # 평균 초과수익률이 양수였던 시대의 비율 (시대 개수 기준)
            "eras_used": [era_name, ...],
        }
    """
    per_era: dict[str, dict[str, Any]] = {}
    positive_era_count = 0

    for era in eras:
        era_name = era["name"]
        start, end = era["start"], era["end"]

        pit_universe = set(point_in_time_universe.get_constituents_as_of(start))

        n_skipped = 0
        ticker_results: dict[str, dict] = {}
        excess_returns: list[float] = []
        wins = 0

        for ticker in tickers:
            if ticker not in pit_universe:
                n_skipped += 1
                continue

            try:
                comparison = compare_with_benchmarks(ticker, config, start, end)
                strategy_metrics = comparison["strategy"].metrics
                bh_metrics = comparison["buy_and_hold_ticker"].metrics
                excess_return = round(
                    strategy_metrics.get("cagr", 0.0) - bh_metrics.get("cagr", 0.0), 2
                )
            except Exception as exc:  # noqa: BLE001 - 종목 하나의 실패가 시대 전체를 막지 않게 함
                ticker_results[ticker] = {"error": str(exc)}
                continue

            ticker_results[ticker] = {
                "excess_return": excess_return,
                "strategy_cagr": strategy_metrics.get("cagr"),
                "buy_and_hold_cagr": bh_metrics.get("cagr"),
            }
            excess_returns.append(excess_return)
            if excess_return > 0:
                wins += 1

        n_tested = len(excess_returns)
        mean_excess_return = round(sum(excess_returns) / n_tested, 2) if n_tested else None
        win_ratio = round(wins / n_tested, 4) if n_tested else None

        if mean_excess_return is not None and mean_excess_return > 0:
            positive_era_count += 1

        per_era[era_name] = {
            "mean_excess_return": mean_excess_return,
            "win_ratio": win_ratio,
            "n_tickers_tested": n_tested,
            "n_tickers_skipped_no_pit_data": n_skipped,
            "tickers": ticker_results,
        }

    era_robustness_score = round(positive_era_count / len(eras), 4) if eras else 0.0

    return {
        "per_era": per_era,
        "era_robustness_score": era_robustness_score,
        "eras_used": [era["name"] for era in eras],
    }
