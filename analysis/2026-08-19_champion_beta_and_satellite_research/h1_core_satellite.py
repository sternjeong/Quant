"""H1 — 코어-새틀라이트: point-in-time 개별주 모멘텀 새틀라이트가 순수 17자산 챔피언을 개선하는가.

설계(작업24/25 No.09/10의 실패를 반복하지 않도록):
  - 코어(80~90%): 순수 17자산 챔피언(champion_strategy.py) 그대로.
  - 새틀라이트(10~20%): 반기(6개월)마다 `core.strategy_tuning.sample_universe(as_of_date=t,
    use_point_in_time_market_cap=True)`로 "그 시점에 실제로 존재+주목받던" 종목 풀(섹터균등,
    point-in-time 시가총액 랭킹)을 뽑고, 그 풀 안에서 12개월 트레일링 모멘텀(코어와 동일한
    로직 — 리밸런싱일 전일 종가 기준 252거래일 수익률)이 양(+)인 종목 중 상위 3개를 동일가중
    보유. 후보가 3개 미만이면 남는 슬롯은 현금(코어와 동일 관례).
  - 새틀라이트 자체 수익률 시계열은 블렌드 비중과 무관하게 한 번만 계산하고, 코어/새틀라이트를
    (1-sw)*core_ret + sw*satellite_ret로 선형 블렌드한다(각 슬리브가 이미 각자 비용을 반영한
    순수익률이므로, 이 이상의 슬리브 간 리밸런싱 비용은 별도로 반영하지 않음 — 04절 한계에 명시).

정직성 체크포인트: point-in-time 표본만 쓰고, 사후에 특정 종목을 손으로 골라 끼워넣지 않는다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from champion_strategy import (
    CHAMPION_UNIVERSE,
    MARKET_FILTER_TICKER,
    fetch_champion_histories,
    _closes_from_histories,
    build_champion_weights,
    compute_portfolio_returns,
)
from core.backtest_engine import calculate_metrics
from core.market_data import get_multiple_price_history
from core.strategy_tuning import sample_universe

SATELLITE_POOL_N = 40  # 반기마다 point-in-time 후보 풀 크기
SATELLITE_TOP_K = 3
SATELLITE_MOMENTUM_WINDOW = 252
SATELLITE_COST_BPS_PER_SIDE = 5.0  # 코어와 동일(왕복 0.1%)
SATELLITE_WARMUP_DAYS = 400


def semiannual_rebal_dates(trading_index: pd.DatetimeIndex, start: str, end: str) -> list[pd.Timestamp]:
    """1월/7월 첫 거래일마다 리밸런싱하는 반기 스케줄(회전율을 제한하기 위해 챔피언의 월간보다
    느슨하게 잡음, 과제 지시사항의 "분기 단위" 예시보다 한 단계 더 보수적으로 택함 — point-in-time
    유니버스 표본추출 자체가 매 시점 실제 네트워크/캐시 조회 비용이 커서, 리서치 라운드를 여러 번
    돌리기 위한 현실적 절충)."""
    idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    months = pd.Series(idx.month, index=idx)
    is_target_month = months.isin([1, 7])
    marked = pd.Series(idx.to_period("M"), index=idx)
    is_first_of_month = marked.ne(marked.shift(1))
    mask = is_target_month & is_first_of_month
    dates = idx[mask].tolist()
    return dates


def pick_satellite_at_date(rebal_date: pd.Timestamp, top_k: int = SATELLITE_TOP_K) -> dict:
    """rebal_date 시점 point-in-time 유니버스에서 모멘텀 상위 top_k 종목을 고른다.

    편입 후보 풀은 sample_universe(as_of_date=rebal_date)로 얻고, 모멘텀 신호는 그 풀 종목들의
    가격이력을 따로 받아 "rebal_date 전일 종가"까지만 사용해 계산한다(룩어헤드 방지, 코어와 동일
    관례).
    """
    as_of_str = rebal_date.date().isoformat()
    pool = sample_universe(n=SATELLITE_POOL_N, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
    candidates = [t for t in pool["ticker"].tolist() if t not in CHAMPION_UNIVERSE and t != MARKET_FILTER_TICKER]

    fetch_start = (rebal_date - pd.DateOffset(days=SATELLITE_WARMUP_DAYS)).date().isoformat()
    fetch_end = rebal_date.date().isoformat()
    histories = get_multiple_price_history(candidates, start=fetch_start, end=fetch_end, interval="1d")

    momentum_scores = {}
    for t in candidates:
        df = histories.get(t)
        if df is None or df.empty:
            continue
        close = df["Close"]
        close = close[close.index < rebal_date]  # 전일까지만 사용(당일 미포함)
        if len(close) < SATELLITE_MOMENTUM_WINDOW + 5:
            continue
        mom = close.iloc[-1] / close.iloc[-1 - SATELLITE_MOMENTUM_WINDOW] - 1.0
        if pd.notna(mom):
            momentum_scores[t] = float(mom)

    ranked = sorted(momentum_scores.items(), key=lambda kv: kv[1], reverse=True)
    positive = [(t, m) for t, m in ranked if m > 0]
    picks = [t for t, m in positive[:top_k]]

    return {
        "date": as_of_str,
        "pool_size": len(candidates),
        "n_positive_momentum": len(positive),
        "picks": picks,
        "pick_momentum": {t: round(m, 4) for t, m in positive[:top_k]},
    }


def build_satellite_returns(start: str, end: str, trading_index: pd.DatetimeIndex, top_k: int = SATELLITE_TOP_K) -> dict:
    rebal_dates = semiannual_rebal_dates(trading_index, start, end)
    print(f"[satellite] {len(rebal_dates)}개 반기 리밸런싱일: {[str(d.date()) for d in rebal_dates]}", flush=True)

    all_picks_log = []
    all_tickers: set[str] = set()
    per_period_picks: list[tuple[pd.Timestamp, list[str]]] = []
    for i, d in enumerate(rebal_dates):
        t0 = time.time()
        info = pick_satellite_at_date(d, top_k=top_k)
        print(f"  [{i+1}/{len(rebal_dates)}] {info['date']}: picks={info['picks']} "
              f"(pool={info['pool_size']}, +모멘텀={info['n_positive_momentum']}, {time.time()-t0:.1f}s)", flush=True)
        all_picks_log.append(info)
        per_period_picks.append((d, info["picks"]))
        all_tickers.update(info["picks"])

    all_tickers = sorted(all_tickers)
    if not all_tickers:
        raise RuntimeError("새틀라이트 후보가 한 번도 뽑히지 않음 — point-in-time 인프라 점검 필요")

    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=SATELLITE_WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(all_tickers, start=fetch_start, end=end, interval="1d")
    closes = _closes_from_histories(histories, all_tickers)

    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    closes = closes.reindex(full_idx).ffill()

    weights = pd.DataFrame(0.0, index=full_idx, columns=closes.columns)
    last_w = pd.Series(0.0, index=closes.columns)
    rebal_set = {d: picks for d, picks in per_period_picks}
    for dt in full_idx:
        if dt in rebal_set:
            picks = rebal_set[dt]
            w = pd.Series(0.0, index=closes.columns)
            if picks:
                w[picks] = 1.0 / top_k
            last_w = w
        weights.loc[dt] = last_w.values

    result = compute_portfolio_returns(closes, weights, cost_bps_per_side=SATELLITE_COST_BPS_PER_SIDE)
    metrics = calculate_metrics(result["equity_net"], [], full_idx[0], full_idx[-1])

    return {
        "start": str(full_idx[0].date()),
        "end": str(full_idx[-1].date()),
        "rebal_log": all_picks_log,
        "tickers_ever_held": all_tickers,
        "metrics": metrics,
        "ret_net": result["ret_net"],
        "equity_net": result["equity_net"],
    }


def blend_returns(core_ret: pd.Series, sat_ret: pd.Series, satellite_weight: float) -> pd.Series:
    core_a, sat_a = core_ret.align(sat_ret, join="inner")
    blended = (1 - satellite_weight) * core_a + satellite_weight * sat_a
    blended.name = f"blend_sw{satellite_weight}"
    return blended


def run(start: str, end: str, satellite_weights: list[float] = (0.10, 0.20)) -> dict:
    print(f"=== H1 core-satellite: {start} ~ {end} ===", flush=True)
    core = None
    # 코어(순수 17자산 챔피언) — 새틀라이트 후보 풀 구축에 쓰는 trading_index도 이걸로 통일한다.
    from champion_strategy import run_champion
    core = run_champion(start, end)
    trading_index = core["ret_net"].index

    sat = build_satellite_returns(start, end, trading_index)

    core_metrics = core["metrics"]
    sat_metrics = sat["metrics"]

    blends = {}
    for sw in satellite_weights:
        br = blend_returns(core["ret_net"], sat["ret_net"], sw)
        eq = (1 + br).cumprod() * 100.0
        eq.iloc[0] = 100.0
        m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
        blends[str(sw)] = {"metrics": m}

    return {
        "period": {"start": start, "end": end},
        "core_metrics": core_metrics,
        "satellite_metrics": sat_metrics,
        "satellite_rebal_log": sat["rebal_log"],
        "satellite_tickers_ever_held": sat["tickers_ever_held"],
        "blends": blends,
    }


if __name__ == "__main__":
    import json
    out = run("2019-08-12", "2026-08-19")
    print(json.dumps({k: v for k, v in out.items() if k != "satellite_rebal_log"}, indent=2, ensure_ascii=False, default=str))
    with open(Path(__file__).parent / "h1_result_primary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print("SAVED h1_result_primary.json")
