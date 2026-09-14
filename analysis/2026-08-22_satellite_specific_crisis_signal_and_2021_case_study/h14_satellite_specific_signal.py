"""H14 - 새틀라이트 전용 국지적 위기 신호.

배경(작업34/H12/H13): 국면조건부 스위치는 SPY vs 200일선(챔피언 자체 시장필터)만 본다. 그 라운드가
스스로 남긴 한계: "이번엔 시장 전체가 무너진 광범위 위기(2008)라 SPY 자체가 빨리 꺾여서 통했을 뿐,
섹터 국지적 위기(SPY는 200일선 위인데 새틀라이트 풀만 무너지는 경우)는 못 잡을 수 있다."

이 스크립트는:
  1. 새틀라이트 자체의 point-in-time 후보 풀(H10과 동일한 sample_universe(n=40, as_of_date=..,
     use_point_in_time_market_cap=True) 호출로 뽑는 40종목 후보군, 챔피언 유니버스+SPY 제외)의
     "풀 breadth"(그 풀 중 자기 200일선 위에 있는 종목의 비율)를 반기 리밸런싱마다 갱신되는
     point-in-time 방식으로 매일 계산한다.
  2. 실제 보유중인 새틀라이트 슬리브(H10의 추세추종 선정 결과, 반기 정적보유) 자체의 실현
     트레일링 낙폭(running peak 대비 낙폭)도 계산한다.
  3. 두 신호를 SPY 200일선 신호와 비교해 "SPY는 불(bull)인데 새틀라이트 신호는 베어"인 괴리
     구간(연속 10거래일 이상)을 찾아 날짜와 함께 보고한다.
  4. breadth 신호/실현낙폭 신호 단독, 그리고 SPY 신호와의 AND/OR 결합으로 국면조건부 스위치를
     만들어 H12와 동일한 3개 구간(2019-2026 전체/2022/2008 GFC)에서 백테스트한다.

재사용: h12_regime_switch.py의 fetch_spy_regime_signal/build_regime_switched_weight_series/
blend_returns_time_varying/perf_metrics_slice, h10의 point-in-time 풀 후보 로직, h11의 GFC 3자산
코어+새틀라이트 구축 로직. core/·app/는 건드리지 않고 메인 체크아웃에서 직접 임포트한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-21_satellite_signal_upgrade_and_crisis_test"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))

import numpy as np
import pandas as pd

from champion_strategy import CHAMPION_UNIVERSE, MARKET_FILTER_TICKER, MARKET_FILTER_MA
from h1_core_satellite import semiannual_rebal_dates, blend_returns
from h11_crisis_robustness_test import (
    run_three_asset_champion, build_satellite_returns_period,
    GFC_FULL_START, GFC_FULL_END, GFC_CRISIS_START, GFC_CRISIS_END, THREE_ASSET_UNIVERSE,
)
from h12_regime_switch import (
    fetch_spy_regime_signal, build_regime_switched_weight_series, blend_returns_time_varying,
    perf_metrics_slice, SATELLITE_WEIGHT_ON,
)
from core.backtest_engine import calculate_metrics
from core.market_data import get_multiple_price_history
from core.strategy_tuning import sample_universe

PRIOR_H10_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test"
PRIOR_H12_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch"
OUT_DIR = Path(__file__).resolve().parent

SATELLITE_POOL_N = 40
FULL_START, FULL_END = "2019-08-12", "2026-08-19"
BEAR2022_START, BEAR2022_END = "2022-01-01", "2022-12-31"
BREADTH_THRESHOLD = 0.5   # 풀의 50% 미만이 자기 200일선 아래면 "약세"
DRAWDOWN_THRESHOLD = -0.10  # 새틀라이트 슬리브 실현낙폭이 -10% 넘으면 "위기"
DRAWDOWN_RECOVER = -0.05    # 복귀 조건(히스테리시스): 낙폭이 -5%보다 얕아지면 다시 ON


def log(msg):
    print(f"[h14] {msg}", flush=True)


def pool_candidates_at_date(rebal_date: pd.Timestamp) -> list[str]:
    as_of_str = rebal_date.date().isoformat()
    pool = sample_universe(n=SATELLITE_POOL_N, as_of_date=as_of_str, use_point_in_time_market_cap=True, use_cache=True)
    return [t for t in pool["ticker"].tolist() if t not in CHAMPION_UNIVERSE and t != MARKET_FILTER_TICKER]


def build_pool_breadth_signal(start: str, end: str, trading_index: pd.DatetimeIndex) -> tuple[pd.Series, list[dict]]:
    """반기마다 point-in-time 후보 풀을 갱신하고, 그 풀(고정 멤버십, 다음 리밸런싱까지 유지) 중
    자기 200일선 위에 있는 종목의 비율(breadth)을 매일 계산해서 반환한다."""
    rebal_dates = semiannual_rebal_dates(trading_index, start, end)
    log(f"{len(rebal_dates)}개 반기 리밸런싱일에서 풀 구성: {[str(d.date()) for d in rebal_dates]}")

    pool_log = []
    per_period_pool: list[tuple[pd.Timestamp, list[str]]] = []
    all_tickers: set[str] = set()
    for i, d in enumerate(rebal_dates):
        t0 = time.time()
        cands = pool_candidates_at_date(d)
        log(f"  [{i+1}/{len(rebal_dates)}] {d.date()}: 풀 {len(cands)}종목 ({time.time()-t0:.1f}s)")
        pool_log.append({"date": str(d.date()), "pool_size": len(cands), "pool": cands})
        per_period_pool.append((d, cands))
        all_tickers.update(cands)

    all_tickers = sorted(all_tickers)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=400)).date().isoformat()
    histories = get_multiple_price_history(all_tickers, start=fetch_start, end=end, interval="1d")

    closes = pd.DataFrame({t: histories[t]["Close"] for t in all_tickers if t in histories and not histories[t].empty})
    full_idx = trading_index[(trading_index >= pd.Timestamp(start)) & (trading_index <= pd.Timestamp(end))]
    closes = closes.sort_index().ffill()
    sma200 = closes.rolling(MARKET_FILTER_MA, min_periods=MARKET_FILTER_MA).mean()
    above = (closes >= sma200)

    # 리밸런싱일마다 풀 멤버십(고정, 다음 리밸런싱까지) 적용 -> 그날그날 유효 멤버 중 breadth 계산
    breadth = pd.Series(index=full_idx, dtype=float)
    rebal_set = {d: cands for d, cands in per_period_pool}
    current_pool: list[str] = []
    for dt in full_idx:
        if dt in rebal_set:
            current_pool = rebal_set[dt]
        if not current_pool:
            breadth[dt] = np.nan
            continue
        valid = [t for t in current_pool if t in above.columns]
        if dt in above.index and valid:
            row = above.loc[dt, valid].dropna()
        else:
            row = pd.Series(dtype=float)
        breadth[dt] = float(row.mean()) if len(row) > 0 else np.nan

    breadth = breadth.ffill()
    breadth.name = "pool_breadth"
    return breadth, pool_log


def build_drawdown_signal(sat_ret: pd.Series) -> pd.Series:
    """새틀라이트 슬리브 자체 실현수익률로 running-peak 대비 트레일링 낙폭을 계산."""
    eq = (1 + sat_ret.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    dd.name = "sat_realized_dd"
    return dd


def signal_to_bull(sig: pd.Series, kind: str) -> pd.Series:
    """kind='breadth': sig>=BREADTH_THRESHOLD 이면 bull. kind='drawdown': 히스테리시스 적용."""
    if kind == "breadth":
        return (sig >= BREADTH_THRESHOLD).rename("bull")
    elif kind == "drawdown":
        bull = pd.Series(True, index=sig.index)
        state = True
        for dt in sig.index:
            d = sig[dt]
            if state and d <= DRAWDOWN_THRESHOLD:
                state = False
            elif (not state) and d >= DRAWDOWN_RECOVER:
                state = True
            bull[dt] = state
        return bull.rename("bull")
    raise ValueError(kind)


def find_divergence_episodes(spy_bull: pd.Series, other_bull: pd.Series, min_len: int = 10) -> list[dict]:
    """SPY는 bull인데 other는 bear인 연속구간(min_len 거래일 이상)을 찾는다."""
    idx = spy_bull.index.intersection(other_bull.index)
    diverge = spy_bull.reindex(idx) & (~other_bull.reindex(idx))
    episodes = []
    in_run, run_start = False, None
    for i, dt in enumerate(idx):
        v = bool(diverge[dt])
        if v and not in_run:
            in_run, run_start = True, dt
        elif not v and in_run:
            run_end = idx[i - 1]
            run_len = idx.get_loc(run_end) - idx.get_loc(run_start) + 1
            if run_len >= min_len:
                episodes.append({"start": str(run_start.date()), "end": str(run_end.date()), "trading_days": int(run_len)})
            in_run = False
    if in_run:
        run_end = idx[-1]
        run_len = idx.get_loc(run_end) - idx.get_loc(run_start) + 1
        if run_len >= min_len:
            episodes.append({"start": str(run_start.date()), "end": str(run_end.date()), "trading_days": int(run_len)})
    return episodes


def combined_signal(a: pd.Series, b: pd.Series, mode: str) -> pd.Series:
    idx = a.index.intersection(b.index)
    if mode == "and":
        return (a.reindex(idx) & b.reindex(idx)).rename("bull")
    elif mode == "or":
        return (a.reindex(idx) | b.reindex(idx)).rename("bull")
    raise ValueError(mode)


def run_period_backtest(core_ret: pd.Series, sat_ret: pd.Series, signals: dict[str, pd.Series],
                         windows: dict[str, tuple[str, str]]) -> dict:
    """signals: name -> bull(bool) series (raw, not yet lagged/switched-weighted). 각 신호로 스위치
    가중치를 만들고 코어+새틀라이트 블렌드를 windows별로 평가."""
    static_blend = blend_returns(core_ret, sat_ret, SATELLITE_WEIGHT_ON)
    out = {}
    for wname, (ws, we) in windows.items():
        row = {
            "core_alone": perf_metrics_slice(core_ret, ws, we),
            "core_plus_static_satellite": perf_metrics_slice(static_blend, ws, we),
        }
        for sname, bull in signals.items():
            weight_series = build_regime_switched_weight_series(core_ret.index, bull, SATELLITE_WEIGHT_ON)
            blended = blend_returns_time_varying(core_ret, sat_ret, weight_series)
            row[f"switch_{sname}"] = perf_metrics_slice(blended, ws, we)
        out[wname] = row
    return out


def part_full_and_2022() -> dict:
    log("전체기간/2022 - H10 저장 CSV 재사용 + 풀breadth/실현낙폭/SPY 신호 계산")
    core_ret = pd.read_csv(PRIOR_H10_DIR / "core_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_ret = pd.read_csv(PRIOR_H10_DIR / "sat_trend_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    trading_index = core_ret.index

    spy_bull_raw = fetch_spy_regime_signal(FULL_START, FULL_END)
    spy_bull = spy_bull_raw.reindex(trading_index).ffill()

    breadth, pool_log = build_pool_breadth_signal(FULL_START, FULL_END, trading_index)
    breadth_bull = signal_to_bull(breadth, "breadth")

    dd = build_drawdown_signal(sat_ret)
    dd_bull = signal_to_bull(dd, "drawdown")

    and_bull = combined_signal(spy_bull, breadth_bull, "and")
    or_bull = combined_signal(spy_bull, breadth_bull, "or")

    episodes = find_divergence_episodes(spy_bull, breadth_bull, min_len=10)
    log(f"  SPY불+풀breadth약세 괴리구간(>=10거래일): {len(episodes)}건")
    for e in episodes:
        log(f"    {e['start']} ~ {e['end']} ({e['trading_days']}거래일)")

    signals = {"spy": spy_bull, "pool_breadth": breadth_bull, "sat_drawdown": dd_bull,
               "spy_and_breadth": and_bull, "spy_or_breadth": or_bull}
    windows = {"full_2019_2026": (FULL_START, FULL_END), "bear_2022": (BEAR2022_START, BEAR2022_END)}
    table = run_period_backtest(core_ret, sat_ret, signals, windows)

    return {
        "windows": table,
        "divergence_episodes": episodes,
        "pool_log": pool_log,
        "breadth_series": breadth,
        "dd_series": dd,
        "spy_bull": spy_bull,
        "breadth_bull": breadth_bull,
        "dd_bull": dd_bull,
        "core_ret": core_ret,
        "sat_ret": sat_ret,
    }


def part_gfc_2008(chosen_method: str) -> dict:
    log(f"2008 GFC - 3자산 코어 재구축 + point-in-time 새틀라이트({chosen_method}) + 풀breadth/실현낙폭 신호")
    core = run_three_asset_champion(GFC_FULL_START, GFC_FULL_END)
    trading_index = core["ret_net"].index
    sat = build_satellite_returns_period(GFC_FULL_START, GFC_FULL_END, trading_index,
                                          exclude=set(THREE_ASSET_UNIVERSE), method=chosen_method)

    spy_bull_raw = fetch_spy_regime_signal(GFC_FULL_START, GFC_FULL_END)
    spy_bull = spy_bull_raw.reindex(trading_index).ffill()

    breadth, pool_log = build_pool_breadth_signal(GFC_FULL_START, GFC_FULL_END, trading_index)
    breadth_bull = signal_to_bull(breadth, "breadth")

    dd = build_drawdown_signal(sat["ret_net"])
    dd_bull = signal_to_bull(dd, "drawdown")

    and_bull = combined_signal(spy_bull, breadth_bull, "and")
    or_bull = combined_signal(spy_bull, breadth_bull, "or")

    episodes = find_divergence_episodes(spy_bull, breadth_bull, min_len=10)
    log(f"  2008구간 SPY불+풀breadth약세 괴리구간(>=10거래일): {len(episodes)}건")
    for e in episodes:
        log(f"    {e['start']} ~ {e['end']} ({e['trading_days']}거래일)")

    signals = {"spy": spy_bull, "pool_breadth": breadth_bull, "sat_drawdown": dd_bull,
               "spy_and_breadth": and_bull, "spy_or_breadth": or_bull}
    windows = {"full_2007_2009": (GFC_FULL_START, GFC_FULL_END), "crisis_2007_10_2009_06": (GFC_CRISIS_START, GFC_CRISIS_END)}
    table = run_period_backtest(core["ret_net"], sat["ret_net"], signals, windows)

    return {
        "windows": table,
        "divergence_episodes": episodes,
        "pool_log": pool_log,
        "breadth_series": breadth,
        "dd_series": dd,
        "spy_bull": spy_bull,
        "breadth_bull": breadth_bull,
        "dd_bull": dd_bull,
        "core_ret": core["ret_net"],
        "sat_ret": sat["ret_net"],
    }


def main():
    t0 = time.time()
    h10 = json.loads((PRIOR_H10_DIR / "h10_results.json").read_text(encoding="utf-8"))
    chosen_method = "trend_following" if (
        h10["placebo_retest_vs_h9_null"]["trend_following_percentile"]
        > h10["placebo_retest_vs_h9_null"]["momentum_percentile_recomputed"]
    ) else "momentum"
    log(f"H10 채택 방식: {chosen_method}")

    p1 = part_full_and_2022()
    p2 = part_gfc_2008(chosen_method)

    def strip(d):
        return {k: v for k, v in d.items() if k not in (
            "breadth_series", "dd_series", "spy_bull", "breadth_bull", "dd_bull", "core_ret", "sat_ret")}

    result = {
        "meta": {"satellite_weight_on": SATELLITE_WEIGHT_ON, "breadth_threshold": BREADTH_THRESHOLD,
                  "drawdown_threshold": DRAWDOWN_THRESHOLD, "drawdown_recover": DRAWDOWN_RECOVER,
                  "chosen_satellite_method": chosen_method},
        "full_and_2022": strip(p1),
        "gfc_2008": strip(p2),
    }
    with open(OUT_DIR / "h14_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h14_results.json'}")

    # H15에서 재사용할 시계열 저장 (전체기간용)
    p1["breadth_series"].to_frame("breadth").to_csv(OUT_DIR / "full_pool_breadth.csv")
    p1["dd_series"].to_frame("dd").to_csv(OUT_DIR / "full_sat_drawdown.csv")
    p1["spy_bull"].to_frame("spy_bull").to_csv(OUT_DIR / "full_spy_bull.csv")
    p1["breadth_bull"].to_frame("breadth_bull").to_csv(OUT_DIR / "full_breadth_bull.csv")
    log(f"CSV 저장 완료 (H15 재사용용, 총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
