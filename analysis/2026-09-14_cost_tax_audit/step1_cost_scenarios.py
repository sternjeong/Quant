"""1단계: 코어+새틀라이트 라이브 챔피언 전략을 비용 시나리오별로 재백테스트.

에이전트 F(비용/세금 감사관) — D의 새 후보가 없어 core/champion_strategy.py의 라이브 기본설정을
감사 대상으로 삼는다(페르소나 프롬프트의 명시적 폴백 지시). BACKTEST_COST_BPS_PER_SIDE=5.0(왕복
0.1%)이 이 저장소가 지금까지 한 번도 감사하지 않은 가정이므로 여기서 처음 감사한다.

비용 시나리오(왕복 기준, cost_bps_per_side = 왕복bps/2):
  - current_0.1pct : 현재 가정 그대로 (5.0bp/side)
  - moderate_0.3pct: 미국주식 매매수수료 0.25%/편도(무프로모션 표준가) 수준을 반영 (15.0bp/side)
  - conservative_0.5pct: 수수료+슬리피지 보수적 합산 (25.0bp/side)
  - no_promo_0.8pct: 프로모션 전혀 없는 표준 수수료+슬리피지 최악 시나리오 (40.0bp/side)

기간은 이 저장소 관례(H33/H34)의 "full_2019_2026" 창을 그대로 재사용 — CORE_UNIVERSE 17종목 중
가장 늦게 상장한 XLC(2018-06-19)가 실질적 제약이라 252일 모멘텀 웜업을 감안하면 2019년 중반이
17종목이 다 갖춰지는 첫 시점이다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))

import numpy as np
import pandas as pd

from core.champion_strategy import (
    CORE_UNIVERSE, MARKET_FILTER_TICKER, BACKTEST_WARMUP_DAYS, SATELLITE_BACKTEST_WARMUP_DAYS,
    _build_core_weights, _compute_portfolio_returns, _closes_from_histories,
    _semiannual_rebal_dates, _pick_satellite_at_date,
    run_satellite_backtest, calculate_metrics,
)
from core.market_data import get_multiple_price_history

OUT_DIR = Path(__file__).resolve().parent
FULL_START = "2019-08-12"
FULL_END = "2026-09-14"

# cost_bps_per_side -> 왕복(round-trip) bps는 turnover(완전 로테이션 시 약 2.0)를 곱해서 나옴:
# cost = turnover * (cost_bps_per_side/10000). 완전 교체시 turnover≈2.0 이므로 왕복cost% = cost_bps_per_side*2/10000*100
COST_SCENARIOS = {
    "current_0.1pct_rt": 5.0,
    "moderate_0.3pct_rt": 15.0,
    "conservative_0.5pct_rt": 25.0,
    "no_promo_0.8pct_rt": 40.0,
}


def log(msg):
    print(f"[step1] {msg}", flush=True)


def main():
    tickers = list(CORE_UNIVERSE)
    fetch_start = (pd.Timestamp(FULL_START) - pd.DateOffset(days=BACKTEST_WARMUP_DAYS)).date().isoformat()
    log(f"코어+SPY 가격 로딩 (fetch_start={fetch_start})...")
    histories = get_multiple_price_history(tickers + [MARKET_FILTER_TICKER], start=fetch_start, end=FULL_END, interval="1d")
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = _build_core_weights(closes, market_close, apply_market_filter=True)
    sliced_idx = closes.index[(closes.index >= pd.Timestamp(FULL_START)) & (closes.index <= pd.Timestamp(FULL_END))]
    closes_sliced = closes.loc[sliced_idx]
    weights_sliced = weights_full.loc[sliced_idx]

    # ---- 거래(회전) 이벤트 카운트: 리밸런싱일마다 top4 구성이 바뀐 만큼 진입/청산 이벤트로 집계 ----
    is_rebal_change = weights_sliced.ne(weights_sliced.shift(1)).any(axis=1)
    core_rebal_dates = weights_sliced.index[is_rebal_change]
    trade_events = 0
    prev_held = set()
    for dt in core_rebal_dates:
        held = set(weights_sliced.loc[dt][weights_sliced.loc[dt] > 0].index)
        entries = held - prev_held
        exits = prev_held - held
        trade_events += len(entries) + len(exits)
        prev_held = held
    n_years = (sliced_idx[-1] - sliced_idx[0]).days / 365.25
    core_trades_per_year = trade_events / n_years
    log(f"코어: 리밸런싱 변경일수={len(core_rebal_dates)}, 총 진입/청산 이벤트={trade_events}, "
        f"기간={n_years:.2f}년 -> 연평균 매매(편도 기준)={core_trades_per_year:.2f}회/년")

    core_results = {}
    for name, bps in COST_SCENARIOS.items():
        res = _compute_portfolio_returns(closes_sliced, weights_sliced, cost_bps_per_side=bps)
        metrics = calculate_metrics(res["equity_net"], [], sliced_idx[0], sliced_idx[-1])
        annual_cost_pct = float(res["turnover"].sum() * (bps / 10000.0) / n_years * 100)
        core_results[name] = {
            "cost_bps_per_side": bps,
            "metrics": metrics,
            "avg_annual_cost_drag_pct": annual_cost_pct,
        }
        res["ret_net"].to_csv(OUT_DIR / f"core_ret_{name}.csv")
        log(f"코어 [{name}] cost_bps/side={bps}: {metrics}, 연평균비용drag={annual_cost_pct:.3f}%")

    # ---- SPY 매수보유 참고선(비용 0) ----
    spy_close = closes_all[MARKET_FILTER_TICKER].loc[sliced_idx]
    spy_ret = spy_close.pct_change().fillna(0.0)
    spy_equity = (1.0 + spy_ret).cumprod() * 100.0
    spy_equity.iloc[0] = 100.0
    spy_metrics = calculate_metrics(spy_equity, [], sliced_idx[0], sliced_idx[-1])
    log(f"SPY 매수보유 참고: {spy_metrics}")

    # ---- 체크포인트: 새틀라이트(느림) 시작 전에 코어 결과를 먼저 저장해둔다(중단 시 재사용) ----
    json.dump({
        "meta": {"full_start": str(sliced_idx[0].date()), "full_end": str(sliced_idx[-1].date()), "n_years": n_years},
        "core_trade_events": trade_events,
        "core_rebal_change_days": len(core_rebal_dates),
        "core_trades_per_year": core_trades_per_year,
        "core_results": core_results,
        "spy_buyhold_metrics": spy_metrics,
        "satellite_done": False,
    }, open(OUT_DIR / "step1_core_checkpoint.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
    log("체크포인트 저장: step1_core_checkpoint.json (코어 완료, 새틀라이트 시작 전)")

    # ---- 새틀라이트: point-in-time 리밸런싱 스캔은 한 번만(느림) 하고, weights/closes를 뽑아
    # 비용 시나리오는 _compute_portfolio_returns만 재호출해 빠르게 재계산한다.
    #
    # 주의(2026-09-14, 감사 실용화 — 중요한 한계로 보고서에도 명시): 라이브 기본값(전체 2019-2026
    # 구간의 반기 리밸런싱 ~14회 x pool_n=40)은 오래전 상장폐지/합병된 종목(ABMD/ATVI/CTXS/WCG/
    # SIVB/SBNY 등)을 반복 조회하며 yfinance rate-limit 재시도에 계속 걸려, 이 감사를 실행하는 이
    # 환경(코드스페이스 샌드박스)에서 완주까지 비현실적으로 오래 걸렸다(두 차례 시도, 각각 10분+
    # 소요 후 중단). 이 감사의 목적은 "이 슬리브가 대략 얼마나 자주 거래하고 비용 민감도가 어느
    # 정도인가"이지 정확한 종목선정 재현이 아니므로, 계산량을 감당 가능한 수준으로 낮춘다:
    #   - 최근 반기 리밸런싱 4회(약 2년)만 재스캔 (전체 14회가 아님)
    #   - pool_n=15 (라이브 기본값 40 대신)
    # 코어(85% 비중, 감사의 핵심)는 전체 2019-2026 구간을 그대로 쓴다 — 이 축소는 새틀라이트(15%
    # 비중)에만 적용된다.
    log("새틀라이트 반기 리밸런싱 point-in-time 스캔 시작 (최근 4회만, 감사 실용화)...")
    trading_index = closes_sliced.index
    sat_rebal_dates_full = _semiannual_rebal_dates(trading_index, FULL_START, FULL_END)
    N_RECENT_REBAL = 4
    sat_rebal_dates = sat_rebal_dates_full[-N_RECENT_REBAL:]
    sat_window_start = str(sat_rebal_dates[0].date())
    rebal_log = []
    all_tickers: set[str] = set()
    per_period_weights = []
    AUDIT_SATELLITE_POOL_N = 15
    for d in sat_rebal_dates:
        info = _pick_satellite_at_date(d, pool_n=AUDIT_SATELLITE_POOL_N)
        rebal_log.append(info)
        per_period_weights.append((d, info["weights"]))
        all_tickers.update(info["picks"])
        log(f"   반기 리밸런싱 {d.date()}: pool={info['pool_size']}, 활성추세={info['n_active_trend']}, picks={info['picks']}")
    all_tickers = sorted(all_tickers)

    # 새틀라이트는 축소된 최근 창(sat_window_start~FULL_END)에서만 계산한다(위 주의사항 참고).
    sat_trading_index = trading_index[trading_index >= pd.Timestamp(sat_window_start)]
    sat_n_years = (sat_trading_index[-1] - sat_trading_index[0]).days / 365.25

    sat_fetch_start = (sat_rebal_dates[0] - pd.DateOffset(days=SATELLITE_BACKTEST_WARMUP_DAYS)).date().isoformat()
    sat_histories = get_multiple_price_history(all_tickers, start=sat_fetch_start, end=FULL_END, interval="1d")
    sat_closes = _closes_from_histories(sat_histories, all_tickers).reindex(sat_trading_index).ffill()

    sat_weights = pd.DataFrame(0.0, index=sat_trading_index, columns=sat_closes.columns)
    last_w = pd.Series(0.0, index=sat_closes.columns)
    rebal_set = dict(per_period_weights)
    for dt in sat_trading_index:
        if dt in rebal_set:
            w_map = rebal_set[dt]
            w = pd.Series(0.0, index=sat_closes.columns)
            for t, wt in w_map.items():
                if t in w.index:
                    w[t] = wt
            last_w = w
        sat_weights.loc[dt] = last_w.values

    # 새틀라이트 매매 이벤트 카운트 (반기마다 사실상 전량 교체에 가까움 -> entries+exits)
    sat_trade_events = 0
    prev_held = set()
    for d, w_map in per_period_weights:
        held = set(t for t, w in w_map.items() if w > 0)
        sat_trade_events += len(held - prev_held) + len(prev_held - held)
        prev_held = held
    sat_trades_per_year = sat_trade_events / sat_n_years
    log(f"새틀라이트: 최근 반기 리밸런싱 {len(sat_rebal_dates)}회({sat_n_years:.2f}년 창), "
        f"총 진입/청산 이벤트={sat_trade_events} -> 연평균 매매(편도 기준)={sat_trades_per_year:.2f}회/년")

    satellite_results = {}
    for name, bps in COST_SCENARIOS.items():
        res = _compute_portfolio_returns(sat_closes, sat_weights, cost_bps_per_side=bps)
        metrics = calculate_metrics(res["equity_net"], [], sat_trading_index[0], sat_trading_index[-1])
        annual_cost_pct = float(res["turnover"].sum() * (bps / 10000.0) / sat_n_years * 100)
        satellite_results[name] = {"cost_bps_per_side": bps, "metrics": metrics, "avg_annual_cost_drag_pct": annual_cost_pct}
        res["ret_net"].to_csv(OUT_DIR / f"satellite_ret_{name}.csv")
        log(f"새틀라이트 [{name}] cost_bps/side={bps}: {metrics}, 연평균비용drag={annual_cost_pct:.3f}%")

    total_trade_events = trade_events + sat_trade_events
    # 코어(7년 창)와 새틀라이트(2년 창)는 창 길이가 달라 "총 이벤트/각자 연수" 합산이 아니라
    # 각 슬리브의 연평균 매매횟수를 그대로 더해 포트폴리오 전체의 "연평균 편도 매매횟수" 근사치로 쓴다.
    total_trades_per_year = core_trades_per_year + sat_trades_per_year
    log(f"통합(코어+새틀라이트) 연평균 매매(편도)={total_trades_per_year:.2f}회/년 "
        f"(왕복 기준 대략 {total_trades_per_year/2:.2f}회/년)")

    json.dump({
        "meta": {
            "full_start": str(sliced_idx[0].date()), "full_end": str(sliced_idx[-1].date()), "n_years": n_years,
            "satellite_window_start": sat_window_start, "satellite_n_years": sat_n_years,
            "satellite_audit_note": (
                "새틀라이트는 계산비용(yfinance rate-limit) 문제로 전체기간이 아니라 최근 반기 리밸런싱 "
                f"{N_RECENT_REBAL}회({sat_n_years:.2f}년 창)만, pool_n={AUDIT_SATELLITE_POOL_N}(라이브 기본값 40 "
                "대신)으로 축소 재계산했다. 코어(85% 비중, 이 감사의 핵심)는 전체 2019-2026 구간 그대로."
            ),
        },
        "core_trade_events": trade_events,
        "core_rebal_change_days": len(core_rebal_dates),
        "core_trades_per_year": core_trades_per_year,
        "core_results": core_results,
        "spy_buyhold_metrics": spy_metrics,
        "satellite_rebal_log": [
            {"date": r["date"], "pool_size": r["pool_size"], "n_active_trend": r["n_active_trend"], "picks": r["picks"]}
            for r in rebal_log
        ],
        "satellite_trade_events": sat_trade_events,
        "satellite_trades_per_year": sat_trades_per_year,
        "satellite_results": satellite_results,
        "total_trade_events": total_trade_events,
        "total_trades_per_year": total_trades_per_year,
    }, open(OUT_DIR / "step1_results.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
    log("step1_results.json 저장 완료")


if __name__ == "__main__":
    main()
