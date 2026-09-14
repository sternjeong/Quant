"""H2 — 챔피언의 베타 정체성: 17자산 로테이션 챔피언의 초과수익은 진짜 알파인가, 위장된 베타인가.

작업28(IREN류 종목 베타/알파 분리 연구)의 H1(시장 베타 헤지) 방법론을 그대로 가져와 대상만 개별
종목에서 "챔피언 전략의 포트폴리오 수익률 시계열"로 바꿔 적용한다:
  1. 챔피언의 일간 수익률(비용 반영) vs SPY 일간 수익률로 롤링(126거래일) OLS 베타를 추정한다.
     베타 = Cov(R_port, R_mkt) / Var(R_mkt), lookahead 방지를 위해 t일의 헤지비율은 t-1일까지의
     데이터로 추정한 베타(shift(1))를 쓴다.
  2. 헤지 후 수익률 = R_port,t − beta_{t-1} × R_mkt,t (달러중립 오버레이, 차입/공매도 비용
     미반영 — 작업28과 동일한 한계를 그대로 명시).
  3. 헤지 전/후 CAGR·연변동성·샤프·MDD 비교, 정적(전체구간 단일) 베타 헤지도 참고용으로 병행.
  4. 초과수익 분해: 챔피언의 SPY 대비 초과수익(연율) 중 "베타로 설명되는 부분"(베타 x SPY
     초과수익률 근사) vs "헤지 후에도 남는 부분"(알파)의 비율을 계산해 정량적으로 보고한다.

확장(시간 허용 시): momentum_rotation_gfc_validation.html(No.07, 작업22 H20)이 쓴 3자산
근사(SPY+TLT+GLD, 절대+상대모멘텀 top2)를 2007-2026으로 재구현해 2008년 금융위기까지 포함한
장기 구간에서도 같은 헤지 검증을 반복한다 — 17자산 챔피언 자체는 섹터 ETF가 2018년 이후 상장이라
그 이전으로 못 가지만, 이 축소판은 갈 수 있다.
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import math
import numpy as np
import pandas as pd

from champion_strategy import run_champion, MARKET_FILTER_TICKER
from core.backtest_engine import _first_trading_day_of_month_mask, calculate_metrics
from core.market_data import get_price_history

TRADING_DAYS_PER_YEAR = 252
ROLLING_WINDOW = 126  # IREN 베타헤지 연구(작업28)와 동일 — 약 6개월


def rolling_beta(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    cov = y.rolling(window).cov(x)
    var = x.rolling(window).var()
    return cov / var


def one_factor_ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float, float]:
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    alpha, b = coef
    fitted = X @ coef
    resid = y - fitted
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(alpha), float(b), r2


def perf_metrics(ret: pd.Series) -> dict:
    ret = ret.dropna()
    if len(ret) < 2:
        return {"cagr_pct": None, "ann_vol_pct": None, "sharpe": None, "mdd_pct": None,
                "total_return_pct": None, "n_days": len(ret)}
    equity = (1.0 + ret).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    n_years = len(ret) / TRADING_DAYS_PER_YEAR
    cagr = (equity.iloc[-1]) ** (1.0 / n_years) - 1.0 if n_years > 0 and equity.iloc[-1] > 0 else float("nan")
    std = ret.std(ddof=0)
    sharpe = float(ret.mean() / std * math.sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    ann_vol = float(std * math.sqrt(TRADING_DAYS_PER_YEAR))
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    mdd = float(drawdown.min())
    return {
        "cagr_pct": round(cagr * 100.0, 2),
        "ann_vol_pct": round(ann_vol * 100.0, 2),
        "sharpe": round(sharpe, 3),
        "mdd_pct": round(mdd * 100.0, 2),
        "total_return_pct": round(total_return * 100.0, 2),
        "n_days": int(len(ret)),
    }


def hedge_champion(start: str, end: str, window: int = ROLLING_WINDOW) -> dict:
    core = run_champion(start, end)
    port_ret = core["ret_net"]
    mkt_close = core["market_close"]
    mkt_ret = mkt_close.pct_change().dropna()

    common_idx = port_ret.index.intersection(mkt_ret.index)
    r_port = port_ret.reindex(common_idx)
    r_mkt = mkt_ret.reindex(common_idx)

    beta_roll = rolling_beta(r_port, r_mkt, window).shift(1)
    valid = beta_roll.dropna().index
    r_port_v = r_port.reindex(valid)
    r_mkt_v = r_mkt.reindex(valid)
    beta_v = beta_roll.reindex(valid).clip(lower=-2.0, upper=3.0)

    unhedged_ret = r_port_v
    hedged_ret = r_port_v - beta_v * r_mkt_v

    alpha_static, beta_static, r2_static = one_factor_ols(r_port.values, r_mkt.values)
    static_hedged_ret = r_port_v - beta_static * r_mkt_v

    unhedged_metrics = perf_metrics(unhedged_ret)
    hedged_metrics = perf_metrics(hedged_ret)
    static_hedged_metrics = perf_metrics(static_hedged_ret)

    spy_metrics = perf_metrics(r_mkt_v)

    # 초과수익 분해 — CAGR 격차 기반 비율은 이 구간처럼 챔피언 CAGR이 SPY와 거의 같을 때(분모가
    # 0에 가까워짐) 숫자가 폭주해 무의미해진다(실측 확인됨) — 대신 표준적인 단일요인 회귀의 절편
    # (젠센 알파, 일간 -> 연율화 복리)을 "베타를 통제한 뒤에도 남는 몫"으로 보고한다.
    excess_return_pct = unhedged_metrics["cagr_pct"] - spy_metrics["cagr_pct"]
    beta_explained_pct = unhedged_metrics["cagr_pct"] - hedged_metrics["cagr_pct"]
    static_alpha_annualized_pct = round(((1.0 + alpha_static) ** TRADING_DAYS_PER_YEAR - 1.0) * 100.0, 2)
    alpha_share_of_total_cagr_pct = (
        round(static_alpha_annualized_pct / unhedged_metrics["cagr_pct"] * 100.0, 1)
        if unhedged_metrics["cagr_pct"] else None
    )

    return {
        "period": {"start": str(valid.min().date()), "end": str(valid.max().date())},
        "window_days": window,
        "avg_rolling_beta": round(float(beta_v.mean()), 3),
        "beta_std": round(float(beta_v.std()), 3),
        "static_full_sample_beta": round(beta_static, 3),
        "static_beta_r2": round(r2_static, 3),
        "unhedged": unhedged_metrics,
        "rolling_hedged": hedged_metrics,
        "static_hedged": static_hedged_metrics,
        "spy_benchmark": spy_metrics,
        "sharpe_improved_rolling": bool(hedged_metrics["sharpe"] > unhedged_metrics["sharpe"]),
        "sharpe_delta_rolling": round(hedged_metrics["sharpe"] - unhedged_metrics["sharpe"], 3),
        "mdd_improved_rolling": bool(hedged_metrics["mdd_pct"] > unhedged_metrics["mdd_pct"]),
        "excess_return_vs_spy_cagr_pct": round(excess_return_pct, 2),
        "beta_explained_cagr_pct": round(beta_explained_pct, 2),
        "alpha_after_hedge_cagr_pct": hedged_metrics["cagr_pct"],
        "static_alpha_annualized_pct": static_alpha_annualized_pct,
        "alpha_share_of_total_cagr_pct": alpha_share_of_total_cagr_pct,
        "verdict_hint": "채택(진짜 알파 근거)" if hedged_metrics["sharpe"] >= unhedged_metrics["sharpe"] else "기각(베타 정체성)",
    }


# ---------------------------------------------------------------------------
# 확장: 3자산(SPY+TLT+GLD) 근사판으로 2008 금융위기 포함 장기 구간(2007~2026) 검증
# (작업22 H20과 동일한 축소 유니버스 재사용 — 섹터 ETF가 2018년 이후 상장이라 그 이전을 못 가는
#  17자산 챔피언의 한계를 시간 허용 시 보완한다)
# ---------------------------------------------------------------------------
THREE_ASSET_UNIVERSE = ["SPY", "TLT", "GLD"]
THREE_ASSET_TOP_N = 2
THREE_ASSET_MOMENTUM_WINDOW = 252


def _three_asset_champion(start: str, end: str) -> dict:
    from core.market_data import get_multiple_price_history
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=400)).date().isoformat()
    histories = get_multiple_price_history(THREE_ASSET_UNIVERSE, start=fetch_start, end=end, interval="1d")
    closes = pd.DataFrame({t: histories[t]["Close"] for t in THREE_ASSET_UNIVERSE if t in histories}).ffill()

    momentum = closes.pct_change(THREE_ASSET_MOMENTUM_WINDOW)
    is_rebal = _first_trading_day_of_month_mask(closes.index)
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_w = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            cand = mom[mom > 0].sort_values(ascending=False)
            picks = cand.index[:THREE_ASSET_TOP_N]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / THREE_ASSET_TOP_N
            last_w = w
        weights.iloc[i] = last_w.values

    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    closes_s = closes.loc[sliced_idx]
    weights_s = weights.loc[sliced_idx]

    daily_ret = closes_s.pct_change().fillna(0.0)
    executed = weights_s.shift(1).fillna(0.0)
    port_ret_gross = (daily_ret * executed).sum(axis=1)
    prev_executed = executed.shift(1).fillna(0.0)
    turnover = (executed - prev_executed).abs().sum(axis=1)
    port_ret_net = port_ret_gross - turnover * (5.0 / 10000.0)

    equity = (1 + port_ret_net).cumprod() * 100.0
    equity.iloc[0] = 100.0
    metrics = calculate_metrics(equity, [], sliced_idx[0], sliced_idx[-1])

    return {"ret_net": port_ret_net, "metrics": metrics, "market_close": closes_s["SPY"]}


def hedge_three_asset_champion(start: str, end: str, window: int = ROLLING_WINDOW) -> dict:
    core = _three_asset_champion(start, end)
    port_ret = core["ret_net"]
    mkt_ret = core["market_close"].pct_change().dropna()
    common_idx = port_ret.index.intersection(mkt_ret.index)
    r_port = port_ret.reindex(common_idx)
    r_mkt = mkt_ret.reindex(common_idx)

    beta_roll = rolling_beta(r_port, r_mkt, window).shift(1)
    valid = beta_roll.dropna().index
    r_port_v = r_port.reindex(valid)
    r_mkt_v = r_mkt.reindex(valid)
    beta_v = beta_roll.reindex(valid).clip(lower=-2.0, upper=3.0)

    unhedged_ret = r_port_v
    hedged_ret = r_port_v - beta_v * r_mkt_v
    unhedged_metrics = perf_metrics(unhedged_ret)
    hedged_metrics = perf_metrics(hedged_ret)
    spy_metrics = perf_metrics(r_mkt_v)

    return {
        "period": {"start": str(valid.min().date()), "end": str(valid.max().date())},
        "core_metrics_full_period": core["metrics"],
        "avg_rolling_beta": round(float(beta_v.mean()), 3),
        "unhedged": unhedged_metrics,
        "rolling_hedged": hedged_metrics,
        "spy_benchmark": spy_metrics,
        "sharpe_improved_rolling": bool(hedged_metrics["sharpe"] > unhedged_metrics["sharpe"]),
        "sharpe_delta_rolling": round(hedged_metrics["sharpe"] - unhedged_metrics["sharpe"], 3),
    }


def run() -> dict:
    primary = hedge_champion("2019-08-12", "2026-08-19")
    robustness_2015 = hedge_champion("2015-01-01", "2026-08-19")
    three_asset_gfc = hedge_three_asset_champion("2007-01-01", "2026-08-19")
    return {
        "hypothesis": "H2",
        "primary_17asset_2019_2026": primary,
        "robustness_17asset_2015_2026": robustness_2015,
        "three_asset_proxy_2007_2026_incl_gfc": three_asset_gfc,
    }


if __name__ == "__main__":
    import json
    out = run()
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    with open(Path(__file__).parent / "h2_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print("SAVED h2_result.json")
