"""중요한 방법론 점검: 지금까지 core.position_sizing.portfolio_volatility_target_weights를
백테스트 전체 기간의 일별수익률에 대해 "한 번만" 호출해 그 비중을 처음부터 끝까지 그대로 썼다.
이 함수 자체는 스냅샷 시점의 실시간 추천용으로 설계된 것(전체 구간 표준편차를 구하는 게 정상 용법)
이라 문제가 없지만, 백테스트에 쓸 때 "전체 구간"에는 미래 구간도 포함되므로 룩어헤드 편향이다 —
2015년 시점의 비중을 정하는 데 2026년까지의 변동성 정보가 쓰인 셈.

이 모듈은 같은 함수를 유지한 채, 분기마다 그 시점까지의 과거 1년치 데이터만 넣어 재호출하고
다음 분기까지 그 비중을 유지하는 "롤링(워크포워드)" 버전을 제공한다 — 룩어헤드 없이 실전과
동일한 방식.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import pandas as pd

from core.position_sizing import portfolio_volatility_target_weights


def rolling_risk_parity_weights(
    daily_returns: pd.DataFrame, lookback_days: int = 252, rebal_freq: str = "QS", max_weight: float = 1.0,
) -> pd.DataFrame:
    """분기(rebal_freq="QS")마다 그 시점 이전 lookback_days 데이터만으로 리스크패리티 비중을
    재계산해, 다음 재계산 시점까지 그대로 유지하는 일별 비중 DataFrame을 반환한다(룩어헤드 없음).
    """
    idx = daily_returns.index
    rebal_dates = pd.date_range(idx[0], idx[-1], freq=rebal_freq)
    weights_daily = pd.DataFrame(0.0, index=idx, columns=daily_returns.columns)

    current_weights = pd.Series(1.0 / daily_returns.shape[1], index=daily_returns.columns)
    rebal_ptr = 0
    for i, dt in enumerate(idx):
        while rebal_ptr < len(rebal_dates) and rebal_dates[rebal_ptr] <= dt:
            hist = daily_returns.loc[:dt].iloc[-lookback_days:]
            if len(hist) >= max(20, lookback_days // 4):
                w = portfolio_volatility_target_weights(hist.dropna(how="all", axis=0), max_weight=max_weight)
                if w:
                    current_weights = pd.Series(0.0, index=daily_returns.columns)
                    for k, v in w.items():
                        if k in current_weights.index:
                            current_weights[k] = v
                    if current_weights.sum() > 0:
                        current_weights = current_weights / current_weights.sum()
            rebal_ptr += 1
        weights_daily.iloc[i] = current_weights.values

    return weights_daily


if __name__ == "__main__":
    # 간단한 자체 점검
    import numpy as np
    dates = pd.bdate_range("2015-01-01", "2016-12-31")
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(0, 0.01, size=(len(dates), 3)), index=dates, columns=["A", "B", "C"])
    w = rolling_risk_parity_weights(df, lookback_days=60, rebal_freq="QS")
    print(w.resample("QS").first())
