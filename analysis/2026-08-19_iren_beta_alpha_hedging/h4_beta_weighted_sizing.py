"""H4 — 베타가중 포지션 사이징(고정 베타 예산) 가설 검증.

가설(H4): 포트폴리오 전체의 목표 베타를 고정해두고(예: 0.3), 종목별 개별 베타에 반비례하게
비중을 배분하면(고베타 종목은 적게, 저베타 종목은 많이 담아 합산 베타를 맞춤) 동일 위험(=동일
목표 베타) 수준에서 순수 동일가중 대비 고유 알파 기여가 더 커지는지 검증한다.

H3과의 차이: H3은 "저베타 종목에 더 담는다"는 자산배분(틸트) 그 자체를 100% 투자 상태에서
비교했다. H4는 한 걸음 더 나아가 "포트폴리오 전체 베타를 특정 목표치(예: 0.3)로 고정"하는
현금오버레이까지 포함한다 — 즉 레버리지 없이, 위험자산 비중(=1-현금비중)을 조절해 목표 베타를
맞춘 뒤, 그 안에서 동일가중과 역베타가중 중 어느 쪽이 더 나은지를 "같은 베타 예산" 조건에서
비교한다.

방법론:
  1. H3과 동일한 월간 리밸런싱·90일 롤링 베타(t-1까지 데이터, 룩어헤드 방지)를 사용한다.
  2. 리밸런싱 시점마다 두 "위험자산 내부 비중"을 계산: (a) 동일가중(raw), (b) 역베타가중(raw,
     베타 하한 0.3로 클리핑). 각각의 위험자산 내부 가중평균 베타(weighted_avg_beta)를 구한다.
  3. 목표 베타(TARGET_BETA=0.3)를 위험자산 내부 가중평균 베타로 나눠 "투자비중"(invested_fraction
     = min(1.0, target/weighted_avg_beta))을 구하고, 나머지는 현금(수익률 0, 무위험수익률 가정과
     동일하게 0으로 둠 — Sharpe 계산 관례와 일치)으로 둔다. 레버리지(투자비중>1)는 쓰지 않는다.
  4. 최종 비중 = raw_weights × invested_fraction. 이렇게 만든 두 포트폴리오(EW-beta-budget,
     InvBeta-beta-budget)의 일간수익률을 시뮬레이션한다.
  5. 전체 구간 단순회귀로 사후(ex-post) 실현 베타·알파(연환산)를 추정해 "실제로 목표 베타 근처에
     있었는지"와 "고유 알파(잔차 초과수익)가 어느 쪽이 더 큰지"를 비교한다. 사후 알파와 샤프
     둘 다 InvBeta가 EW를 앞서면 채택.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import (
    MARKET_TICKER,
    PEER_TICKERS,
    align,
    daily_returns,
    fetch_close,
    one_factor_ols,
    perf_metrics,
    rolling_beta,
)
from h3_low_beta_tilt import BETA_WINDOW, END, REBALANCE_EVERY, START, _beta_matrix, _build_universe_data

TARGET_BETA = 0.30
BETA_FLOOR = 0.3
TRADING_DAYS_PER_YEAR = 252


def _simulate_beta_budget(returns_df: pd.DataFrame, beta_df: pd.DataFrame, target_beta: float) -> dict[str, pd.Series]:
    idx = returns_df.index
    n = len(idx)
    first_valid = beta_df.dropna(how="any").index.min()
    start_pos = idx.get_loc(first_valid)
    rebal_positions = set(range(start_pos, n, REBALANCE_EVERY))

    tickers = list(returns_df.columns)
    weights = {"EW_budget": None, "InvBeta_budget": None}
    invested_fraction_log = {"EW_budget": [], "InvBeta_budget": []}
    port_rets = {k: [] for k in weights}
    port_dates = []

    for i in range(start_pos, n):
        if i in rebal_positions:
            beta_row = beta_df.iloc[i]
            valid_mask = beta_row.notna()
            active = [t for t in tickers if valid_mask.get(t, False)]
            if not active:
                continue
            beta_active = beta_row[active].clip(lower=BETA_FLOOR)

            ew_raw = pd.Series(1.0 / len(active), index=active)
            ew_avg_beta = float((ew_raw * beta_active).sum())
            ew_invested = min(1.0, target_beta / ew_avg_beta) if ew_avg_beta > 0 else 1.0
            ew_final = (ew_raw * ew_invested).reindex(tickers).fillna(0.0)

            inv = 1.0 / beta_active
            invbeta_raw = inv / inv.sum()
            invbeta_avg_beta = float((invbeta_raw * beta_active).sum())
            invbeta_invested = min(1.0, target_beta / invbeta_avg_beta) if invbeta_avg_beta > 0 else 1.0
            invbeta_final = (invbeta_raw * invbeta_invested).reindex(tickers).fillna(0.0)

            weights["EW_budget"] = ew_final
            weights["InvBeta_budget"] = invbeta_final
            invested_fraction_log["EW_budget"].append(ew_invested)
            invested_fraction_log["InvBeta_budget"].append(invbeta_invested)

        row = returns_df.iloc[i]
        port_dates.append(idx[i])
        for k in weights:
            w = weights[k]
            if w is None:
                port_rets[k].append(np.nan)
            else:
                # 현금 비중은 수익률 0으로 취급 (남은 비중 = 1 - w.sum())
                port_rets[k].append(float((row.fillna(0.0) * w).sum()))

    result = {}
    for k, vals in port_rets.items():
        result[k] = pd.Series(vals, index=port_dates).dropna()
    avg_invested = {k: round(float(np.mean(v)), 3) if v else None for k, v in invested_fraction_log.items()}
    return result, avg_invested


def run_universe(tickers: list[str], label: str) -> dict:
    returns_df, r_mkt = _build_universe_data(tickers)
    beta_df = _beta_matrix(returns_df, r_mkt, BETA_WINDOW)
    port_rets, avg_invested = _simulate_beta_budget(returns_df, beta_df, TARGET_BETA)

    metrics = {}
    expost = {}
    for k, s in port_rets.items():
        metrics[k] = perf_metrics(s)
        pr, mr = align(s, r_mkt)
        alpha_daily, beta_expost, r2 = one_factor_ols(pr.values, mr.values)
        alpha_annual_pct = round(((1 + alpha_daily) ** TRADING_DAYS_PER_YEAR - 1) * 100, 2)
        expost[k] = {
            "realized_beta": round(beta_expost, 3),
            "alpha_daily_pct": round(alpha_daily * 100, 4),
            "alpha_annualized_pct": alpha_annual_pct,
            "r2": round(r2, 3),
        }

    invbeta_wins_alpha = expost["InvBeta_budget"]["alpha_annualized_pct"] > expost["EW_budget"]["alpha_annualized_pct"]
    invbeta_wins_sharpe = metrics["InvBeta_budget"]["sharpe"] > metrics["EW_budget"]["sharpe"]

    return {
        "label": label,
        "tickers": list(returns_df.columns),
        "target_beta": TARGET_BETA,
        "n_days": int(len(returns_df)),
        "start": str(returns_df.index.min().date()),
        "end": str(returns_df.index.max().date()),
        "avg_invested_fraction": avg_invested,
        "metrics": metrics,
        "expost_regression": expost,
        "invbeta_beats_ew_alpha": bool(invbeta_wins_alpha),
        "invbeta_beats_ew_sharpe": bool(invbeta_wins_sharpe),
        "verdict_hint": "채택" if (invbeta_wins_alpha and invbeta_wins_sharpe) else ("부분채택" if (invbeta_wins_alpha or invbeta_wins_sharpe) else "기각"),
    }


def run() -> dict:
    primary_tickers = [t for t in PEER_TICKERS if t != "CORZ"]
    primary = run_universe(primary_tickers, "6종목(CORZ 제외, 긴 공통구간)")
    robustness = run_universe(PEER_TICKERS, "7종목 전체(CORZ 포함, 짧은 공통구간)")

    return {
        "hypothesis": "H4",
        "target_beta": TARGET_BETA,
        "beta_window_days": BETA_WINDOW,
        "rebalance_every_days": REBALANCE_EVERY,
        "primary": primary,
        "robustness_all7": robustness,
        "verdict_hint": primary["verdict_hint"],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
