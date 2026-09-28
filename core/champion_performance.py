"""챔피언 전략 성과 해부 — "이 전략을 실제로 썼다면 언제 사고 언제 팔아 얼마를 벌었나"(2026-09-26 추가).

두 가지를 **절대 섞지 않고** 따로 계산한다.

1. 백테스트(가상, 과거): core.champion_strategy.run_champion_backtest 가 만든 코어·새틀라이트
   비중 시계열을 그대로 가져와(새 전략 로직 없음) 다음을 복원한다.
   - 거래(보유 구간) 목록: 슬리브·티커·매수일·매도일·매수가·매도가·보유일수·비용 반영 수익률·
     손익 금액·같은 구간 SPY 수익률과 초과수익. 보유 중 비중 조정은 events(매수/추가매수/일부매도/
     매도)로 따로 남기고, 화면은 보유 구간 단위로 묶어 보여 준다.
   - 자산곡선: 전략 전체·코어 단독·새틀라이트 단독·SPY 매수보유·60/40(SPY/TLT, 매일 비중 유지).
   - 연도별 요약, 티커별 누적 기여.
   손익 금액은 백테스트와 **같은 관례**(weights.shift(1) 체결, 비중 변화분 × 편도 비용)로 매일의
   티커별 기여를 더한 값이라, 모든 거래의 손익 합 = 자산곡선의 총손익이 정확히 맞는다
   (reconciliation.max_abs_return_diff 로 기존 백테스트 수익률과의 차이를 함께 저장한다).

2. 실시간(실제 시장 기록): ChampionLedgerEntry(2026-09-19~)의 '추천을 따랐다면' 누적 자산과
   같은 기간 SPY·60/40, 그리고 paper 계좌 스냅샷(AccountSnapshot, 있으면)의 실제 모의투자 자산.
   실제 주문 기록이 아니다.

결과는 초기 금액과 무관한 배수(1.0 = 초기 금액)로 저장하고 화면에서 입력 금액을 곱한다 — 금액을
바꿔도 재계산이 필요 없다. 무거운 백테스트 결과는 data/cache/champion_performance_<해시>.json 에
캐시한다(입력 파라미터 + 전략 버전 + 비용 가정 해시). 이 모듈은 주문 경로를 import 하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from core import champion_strategy as cs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_PREFIX = "champion_performance_"
PERF_SCHEMA_VERSION = 1  # 저장 형식이 바뀌면 올린다(옛 캐시는 키가 달라져 자동으로 무시된다)

DEFAULT_INITIAL_CAPITAL = 10_000.0
BENCHMARK_TICKER = "SPY"
BOND_TICKER = "TLT"
SIXTY_FORTY_EQUITY_WEIGHT = 0.6
LIVE_MIN_DAYS = cs.BENCHMARK_MIN_LEDGER_DAYS  # 이보다 짧으면 "아직 판단 불가"
_EPS = 1e-12

SLEEVE_CORE = "코어"
SLEEVE_SATELLITE = "새틀라이트"

PriceFn = Callable[..., dict]


# ----------------------------------------------------------------------------
# 순수 계산 (테스트에서 합성 가중치·가격으로 직접 부른다)
# ----------------------------------------------------------------------------

def sleeve_contributions(closes: pd.DataFrame, weights: pd.DataFrame, cost_bps_per_side: float) -> dict:
    """cs._compute_portfolio_returns 와 같은 관례로 티커별 일별 기여(비용 반영)를 분해한다.

    contrib[t, i] = r[t, i] * w_exec[t, i] - |w_exec[t, i] - w_exec[t-1, i]| * cost
    합계(행 합)는 _compute_portfolio_returns 의 ret_net 과 같다.
    """
    closes = closes.loc[weights.index, weights.columns]
    daily_ret = closes.pct_change().fillna(0.0)
    executed = weights.shift(1).fillna(0.0)
    turnover = (executed - executed.shift(1).fillna(0.0)).abs()
    cost = turnover * (cost_bps_per_side / 10000.0)
    contrib = daily_ret * executed - cost
    return {"contrib": contrib, "executed": executed, "ret_net": contrib.sum(axis=1)}


def _run_bounds(active: np.ndarray) -> list[tuple[int, int]]:
    """True 가 이어지는 구간의 (첫 인덱스, 마지막 인덱스) 목록."""
    runs = []
    start = None
    for i, flag in enumerate(active):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(active) - 1))
    return runs


def extract_trades(
    sleeve: str,
    closes: pd.DataFrame,
    weights: pd.DataFrame,
    cost_bps_per_side: float,
    sleeve_weight: float,
    portfolio_growth_prev: pd.Series,
    spy_close: pd.Series,
) -> tuple[list[dict], list[dict]]:
    """한 슬리브의 비중 시계열에서 보유 구간(거래) 목록과 비중 변화 이벤트를 복원한다.

    체결 관례(cs._compute_portfolio_returns): 날짜 d 에 정해진 목표 비중은 d 종가에 체결된 것으로
    보고 d+1 수익부터 반영된다. 그래서 보유 구간 [a, b](실행 비중 > 0 인 날들)의 매수일은 a-1
    (신호일 = 리밸런싱일) 종가, 매도일은 b 종가다. 마지막 날까지 들고 있으면 '보유 중'(평가).

    portfolio_growth_prev: 전략 전체 자산의 '전일' 배수(초기=1.0) — 손익을 초기 금액 대비 배수로
    환산하는 데 쓴다. sleeve_weight: 전체 포트폴리오에서 이 슬리브 비중(코어 0.85 등).
    반환 손익(pnl_x)은 초기 금액 대비 배수(0.012 = 초기 금액의 1.2%)다.
    """
    parts = sleeve_contributions(closes, weights, cost_bps_per_side)
    contrib, executed = parts["contrib"], parts["executed"]
    idx = weights.index
    n = len(idx)
    growth_prev = portfolio_growth_prev.reindex(idx).fillna(1.0).to_numpy()
    closes = closes.loc[idx]
    spy = spy_close.reindex(idx).ffill()
    c = cost_bps_per_side / 10000.0

    trades: list[dict] = []
    events: list[dict] = []
    for ticker in weights.columns:
        w_exec = executed[ticker].to_numpy()
        w_target = weights[ticker].to_numpy()
        dollar = contrib[ticker].to_numpy() * sleeve_weight * growth_prev
        px = closes[ticker].to_numpy()
        for a, b in _run_bounds(w_exec > _EPS):
            buy_i = a - 1 if a > 0 else a
            is_open = b == n - 1
            sell_i = b
            # 매도 비용은 비중이 0으로 바뀐 다음 날(b+1)의 회전율에 붙는다 → 그 날까지 이 거래 몫.
            pnl_end = b if is_open else b + 1
            pnl_x = float(dollar[a:pnl_end + 1].sum())
            entry_px, exit_px = float(px[buy_i]), float(px[sell_i])
            price_ret = exit_px / entry_px - 1.0 if entry_px > 0 else float("nan")
            n_sides = 1 if is_open else 2
            net_ret = (1.0 + price_ret) * (1.0 - c) ** n_sides - 1.0
            spy_ret = float(spy.iloc[sell_i] / spy.iloc[buy_i] - 1.0) if spy.iloc[buy_i] > 0 else float("nan")
            seg_w = w_target[buy_i:b]  # 이 구간에 적용된 목표 비중들(신호일 기준)
            n_adj = int(np.sum(np.abs(np.diff(seg_w)) > _EPS)) if len(seg_w) > 1 else 0
            trades.append({
                "sleeve": sleeve,
                "ticker": str(ticker),
                "buy_date": idx[buy_i].date().isoformat(),
                "sell_date": idx[sell_i].date().isoformat(),
                "is_open": bool(is_open),
                "buy_price": round(entry_px, 4),
                "sell_price": round(exit_px, 4),
                "holding_days": int((idx[sell_i] - idx[buy_i]).days),
                "price_return_pct": round(price_ret * 100, 4),
                "net_return_pct": round(net_ret * 100, 4),
                "spy_return_pct": round(spy_ret * 100, 4),
                "excess_vs_spy_pct": round((net_ret - spy_ret) * 100, 4),
                "avg_portfolio_weight_pct": round(float(np.mean(w_exec[a:b + 1])) * sleeve_weight * 100, 4),
                "n_adjustments": n_adj,
                "pnl_x": pnl_x,
            })

        # 이벤트: 목표 비중이 바뀐 신호일마다 한 줄(체결가 = 그날 종가).
        prev = 0.0
        for i in range(n):
            cur = float(w_target[i])
            if abs(cur - prev) > _EPS:
                if prev <= _EPS:
                    action = "매수"
                elif cur <= _EPS:
                    action = "매도"
                elif cur > prev:
                    action = "추가매수"
                else:
                    action = "일부매도"
                delta_port_x = (cur - prev) * sleeve_weight * float(growth_prev[min(i + 1, n - 1)])
                price = float(px[i])
                events.append({
                    "sleeve": sleeve, "ticker": str(ticker), "date": idx[i].date().isoformat(), "action": action,
                    "price": round(price, 4),
                    "weight_before_pct": round(prev * sleeve_weight * 100, 4),
                    "weight_after_pct": round(cur * sleeve_weight * 100, 4),
                    "notional_x": delta_port_x,  # 초기 금액 대비 거래 금액(+매수/-매도)
                    "shares_per_capital": (delta_port_x / price) if price > 0 else None,  # 초기 금액 1당 주식 수
                })
            prev = cur
    return trades, events


def drawdown_info(growth: pd.Series) -> dict:
    """최대낙폭(%)과 그 구간(고점일·저점일·회복일)."""
    if growth.empty:
        return {"mdd_pct": 0.0, "peak_date": None, "trough_date": None, "recovery_date": None}
    running_max = growth.cummax()
    dd = growth / running_max - 1.0
    trough = dd.idxmin()
    peak = growth.loc[:trough].idxmax()
    after = growth.loc[trough:]
    recovered = after[after >= growth.loc[peak]]
    return {
        "mdd_pct": round(float(dd.min()) * 100, 4),
        "peak_date": peak.date().isoformat(),
        "trough_date": trough.date().isoformat(),
        "recovery_date": recovered.index[0].date().isoformat() if not recovered.empty else None,
    }


def _cagr_pct(growth: pd.Series) -> Optional[float]:
    if len(growth) < 2:
        return None
    years = (growth.index[-1] - growth.index[0]).days / 365.25
    if years <= 0 or growth.iloc[-1] <= 0:
        return None
    return round((float(growth.iloc[-1] / growth.iloc[0]) ** (1 / years) - 1) * 100, 4)


def yearly_table(curves: dict[str, pd.Series]) -> list[dict]:
    """연도별 수익률(%) — 첫 해는 시작일부터, 마지막 해는 종료일까지(부분 연도 표시)."""
    strat = curves["strategy"]
    rows = []
    years = sorted(set(strat.index.year))
    for y in years:
        row: dict[str, Any] = {"year": int(y)}
        in_year = strat.index.year == y
        idx_year = strat.index[in_year]
        # 첫 해가 1월 첫 주 이후에 시작하거나 마지막 해가 12월 말 전에 끝나면 '부분 연도'
        row["partial"] = bool(
            (y == years[0] and (idx_year[0].month, idx_year[0].day) > (1, 7))
            or (y == years[-1] and (idx_year[-1].month, idx_year[-1].day) < (12, 24))
        )
        row["start"] = idx_year[0].date().isoformat()
        row["end"] = idx_year[-1].date().isoformat()
        for name, s in curves.items():
            if s is None or s.empty:
                row[f"{name}_pct"] = None
                continue
            before = s[s.index < idx_year[0]]
            base = float(before.iloc[-1]) if not before.empty else float(s.iloc[0])
            end_val = float(s[s.index <= idx_year[-1]].iloc[-1])
            row[f"{name}_pct"] = round((end_val / base - 1) * 100, 4)
        before = strat[strat.index < idx_year[0]]
        base_x = float(before.iloc[-1]) if not before.empty else float(strat.iloc[0])
        row["strategy_pnl_x"] = float(strat[in_year].iloc[-1]) - base_x
        if row.get("spy_pct") is not None and row.get("strategy_pct") is not None:
            row["diff_vs_spy_pct"] = round(row["strategy_pct"] - row["spy_pct"], 4)
        rows.append(row)
    return rows


def ticker_contributions(trades: list[dict]) -> list[dict]:
    """티커별 누적 손익(초기 금액 대비 배수) — 손익 큰 순."""
    agg: dict[tuple[str, str], dict] = {}
    for t in trades:
        key = (t["ticker"], t["sleeve"])
        a = agg.setdefault(key, {"ticker": t["ticker"], "sleeve": t["sleeve"], "pnl_x": 0.0, "n_trades": 0,
                                 "n_wins": 0, "holding_days": 0})
        a["pnl_x"] += t["pnl_x"]
        a["n_trades"] += 1
        a["n_wins"] += 1 if t["pnl_x"] > 0 else 0
        a["holding_days"] += t["holding_days"]
    return sorted(agg.values(), key=lambda r: r["pnl_x"], reverse=True)


def _series_to_json(s: pd.Series) -> dict:
    return {"dates": [d.date().isoformat() for d in s.index], "values": [round(float(v), 8) for v in s.values]}


def series_from_json(obj: Optional[dict]) -> pd.Series:
    if not obj:
        return pd.Series(dtype=float)
    return pd.Series(obj["values"], index=pd.to_datetime(obj["dates"]), dtype=float)


# ----------------------------------------------------------------------------
# 백테스트 성과 해부 (run_champion_backtest 결과 + 같은 가격 원천)
# ----------------------------------------------------------------------------

def _satellite_weights_from_log(rebal_log: list[dict], closes: pd.DataFrame) -> pd.DataFrame:
    """cs.run_satellite_backtest 내부 루프와 동일하게 rebal_log 의 weights 를 ffill 한다.

    run_satellite_backtest 가 비중 시계열을 반환하지 않아 같은 입력(rebal_log)으로 같은 절차를
    되풀이한다(전략 판단은 하지 않음 — 이미 정해진 종목·비중을 날짜 축에 까는 것뿐). 결과가 기존
    백테스트 수익률과 같은지는 reconciliation 으로 확인한다.
    """
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_w = pd.Series(0.0, index=closes.columns)
    rebal_set = {pd.Timestamp(r["date"]): r.get("weights") or {} for r in rebal_log}
    for dt in closes.index:
        if dt in rebal_set:
            w = pd.Series(0.0, index=closes.columns)
            for t, wt in rebal_set[dt].items():
                if t in w.index:
                    w[t] = wt
            last_w = w
        weights.loc[dt] = last_w.values
    return weights


def analyze_backtest(bt: dict, price_fn: Optional[PriceFn] = None) -> dict:
    """run_champion_backtest 결과를 받아 거래·자산곡선·요약을 배수(초기=1.0) 단위로 만든다.

    price_fn(tickers, start=, end=, interval=) 는 cs.get_multiple_price_history 와 같은 형태 —
    기본은 champion_strategy 모듈이 쓰는 그것(같은 가격 원천·같은 캐시)이다.
    """
    price_fn = price_fn or cs.get_multiple_price_history
    core = bt["core"]
    satellite = bt["satellite"]
    end = bt["end"]
    core_weights: pd.DataFrame = core["weights"]
    idx = core_weights.index

    # --- 코어 가격: run_core_backtest 와 같은 호출(같은 캐시) ---
    core_tickers = list(cs.CORE_UNIVERSE)
    fetch_start = (pd.Timestamp(bt["start"]) - pd.DateOffset(days=cs.BACKTEST_WARMUP_DAYS)).date().isoformat()
    hist = price_fn(core_tickers + [cs.MARKET_FILTER_TICKER], start=fetch_start, end=end, interval="1d")
    closes_all = cs._closes_from_histories(hist, core_tickers + [cs.MARKET_FILTER_TICKER])
    core_closes = closes_all.reindex(idx)[list(core_weights.columns)]
    spy_close = closes_all[cs.MARKET_FILTER_TICKER].reindex(idx).ffill()

    sw = float(bt.get("satellite_weight_applied") or 0.0)
    blended = bt["ret_net"]
    strat_growth = (1.0 + blended).cumprod()
    strat_growth.iloc[0] = 1.0
    growth_prev = strat_growth.shift(1).fillna(1.0)

    core_parts = sleeve_contributions(core_closes, core_weights, cs.CORE_COST_BPS_PER_SIDE)
    trades, events = extract_trades(SLEEVE_CORE, core_closes, core_weights, cs.CORE_COST_BPS_PER_SIDE,
                                    1.0 - sw, growth_prev, spy_close)
    recon_core = float((core_parts["ret_net"] - core["ret_net"].reindex(idx)).abs().max())

    sat_growth = None
    recon_sat = None
    if sw > 0 and satellite.get("tickers_ever_held"):
        sat_tickers = list(satellite["tickers_ever_held"])
        sat_start = (pd.Timestamp(bt["start"]) - pd.DateOffset(days=cs.SATELLITE_BACKTEST_WARMUP_DAYS)).date().isoformat()
        sat_hist = price_fn(sat_tickers, start=sat_start, end=end, interval="1d")
        sat_closes = cs._closes_from_histories(sat_hist, sat_tickers)
        sat_idx = satellite["ret_net"].index
        sat_closes = sat_closes.reindex(sat_idx).ffill()
        sat_weights = _satellite_weights_from_log(satellite["rebal_log"], sat_closes)
        sat_parts = sleeve_contributions(sat_closes, sat_weights, cs.SATELLITE_COST_BPS_PER_SIDE)
        recon_sat = float((sat_parts["ret_net"] - satellite["ret_net"]).abs().max())
        s_trades, s_events = extract_trades(SLEEVE_SATELLITE, sat_closes, sat_weights, cs.SATELLITE_COST_BPS_PER_SIDE,
                                            sw, growth_prev.reindex(sat_idx).fillna(1.0), spy_close.reindex(sat_idx).ffill())
        trades += s_trades
        events += s_events
        sat_growth = (1.0 + satellite["ret_net"]).cumprod()
        sat_growth.iloc[0] = 1.0

    core_growth = (1.0 + core["ret_net"]).cumprod()
    core_growth.iloc[0] = 1.0
    spy_growth = spy_close / spy_close.iloc[0]
    sixty_forty = None
    if BOND_TICKER in closes_all.columns:
        r = closes_all[[BENCHMARK_TICKER, BOND_TICKER]].reindex(idx).ffill().pct_change().fillna(0.0)
        mix = SIXTY_FORTY_EQUITY_WEIGHT * r[BENCHMARK_TICKER] + (1 - SIXTY_FORTY_EQUITY_WEIGHT) * r[BOND_TICKER]
        sixty_forty = (1.0 + mix).cumprod()

    trades.sort(key=lambda t: (t["buy_date"], t["sleeve"], t["ticker"]))
    events.sort(key=lambda e: (e["date"], e["sleeve"], e["ticker"]))
    total_pnl_from_trades = float(sum(t["pnl_x"] for t in trades))
    curves = {"strategy": strat_growth, "core": core_growth, "satellite": sat_growth,
              "spy": spy_growth, "sixty_forty": sixty_forty}
    closed = [t for t in trades if not t["is_open"]]

    summary = {
        "start": idx[0].date().isoformat(), "end": idx[-1].date().isoformat(),
        "final_x": float(strat_growth.iloc[-1]),
        "total_return_pct": round((float(strat_growth.iloc[-1]) - 1) * 100, 4),
        "cagr_pct": _cagr_pct(strat_growth),
        "drawdown": drawdown_info(strat_growth),
        "spy_final_x": float(spy_growth.iloc[-1]),
        "spy_total_return_pct": round((float(spy_growth.iloc[-1]) - 1) * 100, 4),
        "spy_cagr_pct": _cagr_pct(spy_growth),
        "spy_drawdown": drawdown_info(spy_growth),
        "sixty_forty_total_return_pct": (round((float(sixty_forty.iloc[-1]) - 1) * 100, 4)
                                         if sixty_forty is not None else None),
        "satellite_weight_applied": sw,
        "n_trades": len(trades), "n_closed_trades": len(closed),
        "n_winning_closed_trades": sum(1 for t in closed if t["net_return_pct"] > 0),
        "n_open_trades": len(trades) - len(closed),
        "cost_bps_per_side": {"core": cs.CORE_COST_BPS_PER_SIDE, "satellite": cs.SATELLITE_COST_BPS_PER_SIDE},
    }
    reconciliation = {
        "max_abs_return_diff_core": recon_core,
        "max_abs_return_diff_satellite": recon_sat,
        "trade_pnl_sum_x": total_pnl_from_trades,
        "equity_pnl_x": float(strat_growth.iloc[-1]) - 1.0,
        # 코어/새틀라이트 일별 수익률 분해가 기존 백테스트와 1e-9 이내, 거래 손익 합이 자산곡선 총손익과 1e-6 이내
        "ok": bool(recon_core < 1e-9 and (recon_sat is None or recon_sat < 1e-9)
                   and abs(total_pnl_from_trades - (float(strat_growth.iloc[-1]) - 1.0)) < 1e-6),
    }
    return {
        "kind": "backtest",
        "summary": summary,
        "curves": {k: _series_to_json(v) for k, v in curves.items() if v is not None},
        "trades": trades,
        "events": events,
        "yearly": yearly_table({k: v for k, v in curves.items() if v is not None and k in ("strategy", "spy", "sixty_forty")}),
        "ticker_contributions": ticker_contributions(trades),
        "satellite_rebal_log": [
            {"date": r["date"], "picks": list(r.get("picks") or []), "pool_size": r.get("pool_size"),
             "n_active_trend": r.get("n_active_trend")}
            for r in satellite.get("rebal_log", [])
        ],
        "reconciliation": reconciliation,
    }


# ----------------------------------------------------------------------------
# 캐시
# ----------------------------------------------------------------------------

def cache_params(start: str, end: str, satellite_weight: float = cs.SATELLITE_WEIGHT) -> dict:
    return {
        "start": str(start), "end": str(end), "satellite_weight": round(float(satellite_weight), 4),
        "strategy_version": cs.CHAMPION_STRATEGY_VERSION, "schema": PERF_SCHEMA_VERSION,
        "cost_core_bps": cs.CORE_COST_BPS_PER_SIDE, "cost_satellite_bps": cs.SATELLITE_COST_BPS_PER_SIDE,
    }


def cache_key(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cache_path(params: dict, cache_dir: Optional[Path] = None) -> Path:
    return Path(cache_dir or CACHE_DIR) / f"{CACHE_PREFIX}{cache_key(params)}.json"


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_cached(params: dict, cache_dir: Optional[Path] = None) -> Optional[dict]:
    path = cache_path(params, cache_dir)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if data.get("params") == params else None


def list_cached(cache_dir: Optional[Path] = None) -> list[dict]:
    """저장된 성과 캐시의 (params, computed_at, path) 목록 — 최근 계산 순. 계산은 하지 않는다."""
    out = []
    for p in Path(cache_dir or CACHE_DIR).glob(f"{CACHE_PREFIX}*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        params = data.get("params") or {}
        if params.get("schema") != PERF_SCHEMA_VERSION:
            continue
        out.append({"params": params, "computed_at": data.get("computed_at"), "path": str(p)})
    return sorted(out, key=lambda r: r.get("computed_at") or "", reverse=True)


def load_latest_cached(start: Optional[str] = None, satellite_weight: Optional[float] = None,
                       cache_dir: Optional[Path] = None) -> Optional[dict]:
    """조건(시작일·새틀라이트 비중)에 맞는 캐시 중 가장 최근 계산본. 조건이 None 이면 무시."""
    for row in list_cached(cache_dir):
        p = row["params"]
        if start is not None and p.get("start") != str(start):
            continue
        if satellite_weight is not None and abs(float(p.get("satellite_weight", -1)) - float(satellite_weight)) > 1e-9:
            continue
        if p.get("strategy_version") != cs.CHAMPION_STRATEGY_VERSION:
            continue
        try:
            with open(row["path"], encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def latest_snapshot_meta(cache_dir: Optional[Path] = None) -> Optional[dict]:
    """공통 상태 헤더용 — 가장 최근 캐시의 계산 시각·버전(계산·네트워크 없음)."""
    rows = list_cached(cache_dir)
    if not rows:
        return None
    row = rows[0]
    return {"computed_at": row["computed_at"], "strategy_version": row["params"].get("strategy_version"),
            "pit": "부분 검증"}


def compute_backtest_performance(
    start: str,
    end: str,
    satellite_weight: float = cs.SATELLITE_WEIGHT,
    *,
    use_cache: bool = True,
    cache_dir: Optional[Path] = None,
    backtest_fn: Optional[Callable[..., dict]] = None,
    price_fn: Optional[PriceFn] = None,
    progress_path: Optional[Path] = None,
) -> dict:
    """백테스트 → 성과 해부 → 캐시 저장. 캐시가 있으면 즉시 반환(느린 새틀라이트 스캔 생략).

    job_manager 로 감싸서 부른다(새틀라이트는 반기마다 point-in-time 스캔이라 1년≈2분 이상).
    """
    params = cache_params(start, end, satellite_weight)
    if use_cache:
        cached = load_cached(params, cache_dir)
        if cached is not None:
            cached["from_cache"] = True
            return cached
    backtest_fn = backtest_fn or cs.run_champion_backtest
    if progress_path:
        _atomic_write_json(Path(progress_path), {"stage": "backtest", "params": params,
                                                 "started_at": _now_iso()})
    bt = backtest_fn(start, end, satellite_weight=satellite_weight)
    if progress_path:
        _atomic_write_json(Path(progress_path), {"stage": "analyze", "params": params, "started_at": _now_iso()})
    result = analyze_backtest(bt, price_fn=price_fn)
    result["params"] = params
    result["computed_at"] = _now_iso()
    if use_cache:
        _atomic_write_json(cache_path(params, cache_dir), result)
    result["from_cache"] = False
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------
# 금액 환산 (배수 → 달러)
# ----------------------------------------------------------------------------

def to_dollars(result: dict, capital: float) -> dict:
    """배수 단위 결과를 초기 금액 기준 달러로 환산한 표시용 DataFrame 들."""
    capital = float(capital)
    curves = {k: series_from_json(v) * capital for k, v in result["curves"].items()}
    trades = pd.DataFrame(result["trades"])
    if not trades.empty:
        trades["pnl_usd"] = trades["pnl_x"] * capital
    events = pd.DataFrame(result["events"])
    if not events.empty:
        events["notional_usd"] = events["notional_x"] * capital
        events["shares"] = events["shares_per_capital"].astype(float) * capital
    contrib = pd.DataFrame(result["ticker_contributions"])
    if not contrib.empty:
        contrib["pnl_usd"] = contrib["pnl_x"] * capital
    yearly = pd.DataFrame(result["yearly"])
    if not yearly.empty:
        yearly["strategy_pnl_usd"] = yearly["strategy_pnl_x"] * capital
    s = result["summary"]
    return {
        "curves": curves, "trades": trades, "events": events, "contrib": contrib, "yearly": yearly,
        "final_usd": s["final_x"] * capital, "pnl_usd": (s["final_x"] - 1.0) * capital,
        "spy_final_usd": s["spy_final_x"] * capital, "spy_pnl_usd": (s["spy_final_x"] - 1.0) * capital,
    }


# ----------------------------------------------------------------------------
# 실시간(실제 시장 기록) — 백테스트와 섞지 않는다
# ----------------------------------------------------------------------------

def _load_paper_snapshots() -> list[tuple[date, float]]:
    from core.db import get_session
    from core.models import AccountSnapshot

    with get_session() as db:
        rows = (db.query(AccountSnapshot)
                .filter(AccountSnapshot.source == "alpaca_paper", AccountSnapshot.as_of.isnot(None))
                .order_by(AccountSnapshot.as_of, AccountSnapshot.id).all())
        return [(r.as_of, float(r.equity)) for r in rows if r.equity]


def ledger_weight_changes(entries: list[dict]) -> list[dict]:
    """원장에 저장된 '다음 날 적용 비중'의 변화 기록(신규 편입·비중 변경·제외)."""
    out = []
    prev: dict[str, tuple[str, float]] = {}
    for e in entries:
        cur = {t: (SLEEVE_CORE, float(w)) for t, w in (e.get("core_weights") or {}).items() if w}
        cur.update({t: (SLEEVE_SATELLITE, float(w)) for t, w in (e.get("satellite_weights") or {}).items() if w})
        for t in sorted(set(prev) | set(cur)):
            before = prev.get(t, (None, 0.0))[1]
            after = cur.get(t, (None, 0.0))[1]
            if abs(after - before) <= 1e-6:
                continue
            action = "편입" if before <= 1e-9 else ("제외" if after <= 1e-9 else "비중 변경")
            sleeve = (cur.get(t) or prev.get(t))[0]
            out.append({"date": e["entry_date"], "ticker": t, "sleeve": sleeve, "action": action,
                        "weight_before_pct": round(before * 100, 3), "weight_after_pct": round(after * 100, 3)})
        prev = cur
    return out


def build_live_record(
    entries: Optional[list[dict]] = None,
    paper_snapshots: Optional[list[tuple[date, float]]] = None,
    price_fn: Optional[PriceFn] = None,
) -> dict:
    """ChampionLedgerEntry 원장(가상 '따랐다면') + 같은 기간 SPY·60/40 + paper 계좌(있으면).

    entries/paper_snapshots/price_fn 를 주입하면 DB·네트워크 없이 계산한다(테스트).
    """
    if entries is None:
        entries = cs.list_ledger_entries(limit=5000)
    if paper_snapshots is None:
        try:
            paper_snapshots = _load_paper_snapshots()
        except Exception:  # noqa: BLE001 - 테이블이 없는 옛 DB 등
            paper_snapshots = []
    out: dict[str, Any] = {"kind": "live", "n_entries": len(entries), "min_days": LIVE_MIN_DAYS,
                           "ledger_start_expected": "2026-09-19"}
    paper = sorted({d: e for d, e in paper_snapshots if e and e > 0}.items())
    out["paper"] = {
        "available": bool(paper),
        "n_snapshots": len(paper),
        "curve": _series_to_json(pd.Series([e / paper[0][1] for _, e in paper],
                                           index=pd.to_datetime([d for d, _ in paper]))) if paper else None,
        "last_equity": paper[-1][1] if paper else None,
        "first_date": paper[0][0].isoformat() if paper else None,
        "last_date": paper[-1][0].isoformat() if paper else None,
    }
    if not entries:
        out.update({"available": False, "enough": False,
                    "reason": "원장 기록이 아직 없습니다(매일 밤 기록 잡이 쌓기 시작하면 여기에 나타납니다)."})
        return out

    ledger = pd.Series([float(e["cumulative_equity"]) / 100.0 for e in entries],
                       index=pd.to_datetime([e["entry_date"] for e in entries]))
    base = float(ledger.iloc[0])
    ledger = ledger / base if base > 0 else ledger
    out.update({
        "available": True,
        "enough": len(entries) >= LIVE_MIN_DAYS,
        "start_date": entries[0]["entry_date"], "end_date": entries[-1]["entry_date"],
        "ledger_curve": _series_to_json(ledger),
        "ledger_total_return_pct": round((float(ledger.iloc[-1]) - 1) * 100, 4),
        "current_weights": {
            "core": entries[-1].get("core_weights") or {},
            "satellite": entries[-1].get("satellite_weights") or {},
        },
        "weight_changes": ledger_weight_changes(entries),
        "daily": [{"date": e["entry_date"], "realized_return_pct": e["realized_return_pct"],
                   "cumulative_equity": e["cumulative_equity"]} for e in entries],
    })

    price_fn = price_fn or cs.get_multiple_price_history
    spy_curve = sixty_curve = None
    try:
        hist = price_fn([BENCHMARK_TICKER, BOND_TICKER], start=out["start_date"],
                        end=(pd.Timestamp(out["end_date"]) + pd.DateOffset(days=1)).date().isoformat(), interval="1d")
        spy = hist.get(BENCHMARK_TICKER)
        tlt = hist.get(BOND_TICKER)
        if spy is not None and not spy.empty:
            spy_c = spy["Close"].copy()
            spy_c.index = pd.to_datetime(spy_c.index).tz_localize(None) if getattr(spy_c.index, "tz", None) else pd.to_datetime(spy_c.index)
            spy_c = spy_c[(spy_c.index >= ledger.index[0]) & (spy_c.index <= ledger.index[-1])]
            if not spy_c.empty:
                spy_curve = spy_c / spy_c.iloc[0]
                if tlt is not None and not tlt.empty:
                    tlt_c = tlt["Close"].copy()
                    tlt_c.index = pd.to_datetime(tlt_c.index).tz_localize(None) if getattr(tlt_c.index, "tz", None) else pd.to_datetime(tlt_c.index)
                    tlt_c = tlt_c.reindex(spy_c.index).ffill()
                    # compute_benchmark_comparison 과 같은 매수보유 혼합(리밸런싱 없음)
                    sixty_curve = SIXTY_FORTY_EQUITY_WEIGHT * spy_curve + (1 - SIXTY_FORTY_EQUITY_WEIGHT) * (tlt_c / tlt_c.iloc[0])
    except Exception as exc:  # noqa: BLE001 - 벤치마크 실패가 원장 표시를 막지 않게
        out["benchmark_error"] = f"{type(exc).__name__}"
    out["spy_curve"] = _series_to_json(spy_curve) if spy_curve is not None else None
    out["sixty_forty_curve"] = _series_to_json(sixty_curve) if sixty_curve is not None else None
    out["spy_total_return_pct"] = round((float(spy_curve.iloc[-1]) - 1) * 100, 4) if spy_curve is not None else None
    out["sixty_forty_total_return_pct"] = (round((float(sixty_curve.iloc[-1]) - 1) * 100, 4)
                                           if sixty_curve is not None else None)
    return out


def format_pct(v: Optional[float], digits: int = 1, signed: bool = True) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"


def format_usd(v: Optional[float], signed: bool = False) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    sign = ("+" if v >= 0 else "−") if signed else ("−" if v < 0 else "")
    return f"{sign}${abs(v):,.0f}"


DEFAULT_PERIOD_YEARS = 5  # 기본 기간: (올해-5)년 1월 1일 ~ 오늘 — 새틀라이트 반기(1·7월) 시작과 맞춘다


def default_start(today: Optional[date] = None) -> str:
    today = today or date.today()
    return date(today.year - DEFAULT_PERIOD_YEARS, 1, 1).isoformat()
