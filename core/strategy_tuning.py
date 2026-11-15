"""종목 표본 뽑기와 train/test 기간 나누기.

예전에는 S&P500 섹터 균등 표본에 스타일별 파라미터 미세튜닝을 돌리는 엔진이었다(STRATEGY_TUNING_ENGINE_SPEC.md).
튜닝을 돌리던 전략 스튜디오 화면이 2026-11-10 삭제됐고, 그 뒤로 쓰이지 않던 튜닝·저장·생성 코드는 2026-11-15 지웠다.
남은 두 함수는 챔피언 전략·시장 진단·새틀라이트 R&D·앞으로 토너먼트가 쓴다.

    sample_universe(n=100, ...) -> pd.DataFrame      섹터 균등 n종목 표본(그 시점 편입·시총 기준 선택 가능)
    train_test_split_dates(start, end, ratio) -> tuple   시계열 순서 그대로 train/test 분리
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from core import point_in_time_market_cap, point_in_time_universe, screener


def sample_universe(
    n: int = 100,
    use_cache: bool = True,
    random_seed: Optional[int] = None,
    as_of_date: Optional[str | date | datetime] = None,
    use_point_in_time_market_cap: bool = False,
) -> pd.DataFrame:
    """S&P500 유니버스에서 섹터별로 균등 배분된 n종목 표본을 추출한다.

    시총 상위 n개를 그냥 뽑으면 빅테크 섹터로 편중되어(STRATEGY_TUNING_ENGINE_SPEC.md 5절 결정)
    섹터별 스타일 비교가 무의미해지므로, 섹터마다 기본 할당량(n // 섹터수)을 배분하고 나머지는
    섹터 전체 시가총액 합이 큰 섹터부터 1개씩 더 배분한다.

    random_seed가 None이면(기본값) 섹터별 할당량을 시가총액 상위 순으로 결정론적으로 채운다(기존
    동작 그대로 — 대화형 UI에서 같은 n을 여러 번 눌러도 항상 같은 표본이 나와야 함). random_seed를
    주면(2026-07-15 추가, 야간 반복 미세튜닝에서 매번 다른 표본을 탐색하기 위함) 섹터별 할당량 안에서
    시드 기반 무작위 추출로 바꾼다 — 그래도 재현 가능하도록 같은 시드면 항상 같은 표본이 나온다.

    as_of_date를 주면(2026-07-17 추가, survivorship bias 완화 — PROGRESS.md 백로그 1번)
    "지금 시점 S&P500"이 아니라 `core.point_in_time_universe`가 제공하는 그 시점 실제 편입종목
    목록으로 후보를 제한한다(`core/point_in_time_universe.py` 참고, fja05680/sp500 CSV 기반).
    이렇게 하면 학습 시작 시점 이후 지수에서 편출된 종목(예: GE, 인텔)도 표본에 남을 수 있다.
    단, 상장폐지까지 간 종목은 yfinance 자체에 가격 데이터가 없어 여전히 빠질 수 있다(알려진 한계,
    PROGRESS.md 백로그 1번 참고). None이면(기본값) 기존과 동일하게 현재 S&P500 전체가 후보다.

    use_point_in_time_market_cap을 True로 주면(2026-08-13 추가, No.09 리서치가 드러낸 사후편향
    타개 — PROGRESS.md 작업25 참고) 섹터별 할당량을 채울 때 쓰는 시가총액 랭킹 자체를
    core.point_in_time_market_cap(발행주식수 이력 x 그 시점 종가 근사)으로 계산한다 — as_of_date가
    편입 여부만 그 시점 기준으로 걸러주고 랭킹은 여전히 "지금" 시가총액을 쓰던 기존 동작의 한계를
    해소한다. as_of_date 없이 이 옵션만 켜면 as_of_date=오늘로 취급해 사실상 기존과 동일하다(과거
    시점을 지정해야 의미가 있음). 기본값 False — 기존 호출부(야간 튜닝 등)의 동작을 바꾸지 않는다.

    Returns:
        columns: ticker, sector(GICS 영문), market_cap. 시가총액 내림차순 정렬.
    """
    universe = screener.get_universe(use_cache=use_cache)

    if as_of_date is not None:
        pit_tickers = set(point_in_time_universe.get_constituents_as_of(as_of_date))
        current_sector_map = dict(zip(universe["Symbol"], universe["Sector"]))
        universe = pd.DataFrame(
            {
                "Symbol": sorted(pit_tickers),
                "Sector": [current_sector_map.get(t, "Unknown") for t in sorted(pit_tickers)],
            }
        )

    sectors = sorted(universe["Sector"].dropna().unique().tolist())
    if not sectors:
        return pd.DataFrame(columns=["ticker", "sector", "market_cap"])

    if use_point_in_time_market_cap:
        cap_asof = as_of_date if as_of_date is not None else date.today().isoformat()
        cap_map = point_in_time_market_cap.get_market_caps_asof_batch(
            universe["Symbol"].tolist(), str(cap_asof), use_cache=use_cache
        )
        rows = [
            {"ticker": sym, "sector": sector, "market_cap": cap_map.get(sym) or 0}
            for sym, sector in zip(universe["Symbol"], universe["Sector"])
        ]
    else:
        rows = []
        for _, r in universe.iterrows():
            fundamentals = screener.get_fundamentals(r["Symbol"], use_cache=use_cache)
            rows.append(
                {"ticker": r["Symbol"], "sector": r["Sector"], "market_cap": fundamentals.get("market_cap") or 0}
            )
    df = pd.DataFrame(rows)

    base_quota = max(1, n // len(sectors))
    remainder = max(0, n - base_quota * len(sectors))
    sector_total_cap = df.groupby("sector")["market_cap"].sum().sort_values(ascending=False)
    quotas = {s: base_quota for s in sectors}
    for s in sector_total_cap.index[:remainder]:
        quotas[s] += 1

    picked = []
    for s in sectors:
        sector_df = df[df["sector"] == s]
        quota = min(quotas.get(s, base_quota), len(sector_df))
        if random_seed is None:
            picked.append(sector_df.sort_values("market_cap", ascending=False).head(quota))
        else:
            picked.append(sector_df.sample(n=quota, random_state=random_seed))
    result = pd.concat(picked, ignore_index=True) if picked else pd.DataFrame(columns=df.columns)
    return result.sort_values("market_cap", ascending=False).reset_index(drop=True)


_DEFAULT_TRAIN_RATIO = 0.75


def train_test_split_dates(start: str, end: str, train_ratio: float = _DEFAULT_TRAIN_RATIO) -> tuple[str, str, str, str]:
    """시작~종료 기간을 시계열 순서 그대로 train/test로 분리한다(랜덤 셔플 없음).

    Returns:
        (train_start, train_end, test_start, test_end) 문자열(YYYY-MM-DD) 튜플.
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    total_days = (end_ts - start_ts).days
    split_ts = start_ts + timedelta(days=int(total_days * train_ratio))
    train_start = start_ts.date().isoformat()
    train_end = split_ts.date().isoformat()
    test_start = (split_ts + timedelta(days=1)).date().isoformat()
    test_end = end_ts.date().isoformat()
    return train_start, train_end, test_start, test_end
