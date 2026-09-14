"""H12 - 국면조건부 새틀라이트 스위치(binary on/off).

배경(작업33/H11): 코어(17자산 챔피언)+15% 추세추종 새틀라이트 블렌드는 2019-2026 전체 구간과
2022년 약세장에서는 코어 단독 대비 견고했지만, 2008년 금융위기(SPY/TLT/GLD 3자산 근사 코어)에서는
코어 단독(CAGR+3.45%, 샤프0.29)이 새틀라이트를 얹는 순간 마이너스(CAGR-3.70%, 샤프-0.16)로
뒤집혔다. 그 라운드가 명시적으로 남긴 다음 과제: "위기 국면에는 새틀라이트를 0%로 끄는
국면조건부 스위치".

설계: 챔피언 자체가 이미 쓰고 있는 이진 시장필터 신호(SPY 종가 vs 200일 이동평균, champion_strategy.py
build_champion_weights)를 그대로 재사용한다 - 새 국면 분류기를 만들지 않는다. 작업21/23이 이미
"이진 필터가 연속/시그모이드 필터를 이긴다"를 두 차례 확인했으므로 여기서도 이진을 채택.

스위치 로직: 매 거래일 t에 대해, 전일(t-1) SPY 종가가 200일 이평 위/아래인지로 그날의 새틀라이트
비중을 정한다(챔피언 자체의 월간 룩어헤드 방지 관례와 동일하게 "신호는 전일 확정치 사용, 적용은
당일부터"): SPY(t-1) >= SMA200(t-1) -> 새틀라이트 15%, 아니면 0%(코어 100%). 새틀라이트가 보유한
개별 종목 자체(반기 리밸런싱 로직)는 H10과 동일하게 그대로 유지 - 스위치는 "그 새틀라이트에 얼마를
배분할지"만 매일 결정한다.

3개 구성 x 3개 구간을 비교한다:
  (a) 코어 단독
  (b) 코어 + 상시 15% 새틀라이트(H10/H11 정적 베이스라인)
  (c) 코어 + 국면조건부 새틀라이트(0%/15% 스위치, 이번 라운드 신규)
구간: 전체 2019-08~2026-08, 2022년 약세장, 2008 금융위기(2007-10~2009-06 위기구간 + 2007~2009 전체)

H11과 동일하게 2019-2026/2022 구간은 H10이 저장한 CSV(core_ret_net.csv, sat_trend_ret_net.csv 등)를
그대로 재사용하고, 2008 GFC는 h11_crisis_robustness_test.py의 3자산 코어+point-in-time 새틀라이트
구축 로직을 재사용(직접 재실행, 캐시 데이터 사용)한다.
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

import numpy as np
import pandas as pd

from champion_strategy import MARKET_FILTER_MA, compute_portfolio_returns
from h1_core_satellite import blend_returns
from h11_crisis_robustness_test import (
    run_three_asset_champion, build_satellite_returns_period,
    GFC_FULL_START, GFC_FULL_END, GFC_CRISIS_START, GFC_CRISIS_END,
    THREE_ASSET_UNIVERSE,
)
from core.backtest_engine import calculate_metrics
from core.market_data import get_multiple_price_history

PRIOR_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test"
OUT_DIR = Path(__file__).resolve().parent

SATELLITE_WEIGHT_ON = 0.15
FULL_START, FULL_END = "2019-08-12", "2026-08-19"
BEAR2022_START, BEAR2022_END = "2022-01-01", "2022-12-31"


def log(msg):
    print(f"[h12] {msg}", flush=True)


def fetch_spy_regime_signal(start: str, end: str, extra_warmup_days: int = 400) -> pd.Series:
    """SPY 종가 >= 200일 이평이면 True(강세/평시), 아니면 False(약세/위기). 인덱스는 거래일 전체
    (워밍업 포함), 값은 그날 '확정된' 신호(당일 종가 기준) - 실제 적용 시에는 반드시 1일 shift해서
    사용해야 룩어헤드가 없다(적용부에서 shift 처리)."""
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=extra_warmup_days)).date().isoformat()
    hist = get_multiple_price_history(["SPY"], start=fetch_start, end=end, interval="1d")
    spy = hist["SPY"]["Close"]
    sma = spy.rolling(MARKET_FILTER_MA, min_periods=MARKET_FILTER_MA).mean()
    bull = spy >= sma
    bull.name = "spy_bull_regime"
    return bull


def build_regime_switched_weight_series(trading_index: pd.DatetimeIndex, regime_bull_raw: pd.Series,
                                         weight_on: float = SATELLITE_WEIGHT_ON) -> pd.Series:
    """trading_index의 각 거래일에 대해, 전일 확정 국면 신호로 결정된 새틀라이트 비중(0 또는
    weight_on)을 반환한다. 룩어헤드 방지: t일 비중은 (t-1)일 종가로 계산된 신호를 사용."""
    regime_aligned = regime_bull_raw.reindex(trading_index).ffill()
    signal_lagged = regime_aligned.shift(1).fillna(False)  # 전일 신호를 오늘 적용(챔피언 관례와 동일)
    w = signal_lagged.astype(float) * weight_on
    w.name = "satellite_weight_switched"
    return w


def blend_returns_time_varying(core_ret: pd.Series, sat_ret: pd.Series, weight_series: pd.Series) -> pd.Series:
    core_a, sat_a = core_ret.align(sat_ret, join="inner")
    w = weight_series.reindex(core_a.index).fillna(0.0)
    blended = (1 - w) * core_a + w * sat_a
    blended.name = "blend_switched"
    return blended


def perf_metrics_slice(ret: pd.Series, start: str, end: str) -> dict:
    sliced = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if len(sliced) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "calmar": None, "n_days": len(sliced)}
    eq = (1 + sliced.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
    m["n_days"] = int(len(sliced))
    return m


def three_config_table(core_ret: pd.Series, sat_ret: pd.Series, weight_series: pd.Series,
                        windows: dict[str, tuple[str, str]]) -> dict:
    static_blend = blend_returns(core_ret, sat_ret, SATELLITE_WEIGHT_ON)
    switched_blend = blend_returns_time_varying(core_ret, sat_ret, weight_series)

    out = {}
    for wname, (ws, we) in windows.items():
        out[wname] = {
            "core_alone": perf_metrics_slice(core_ret, ws, we),
            "core_plus_static_satellite": perf_metrics_slice(static_blend, ws, we),
            "core_plus_regime_switched_satellite": perf_metrics_slice(switched_blend, ws, we),
        }
    return out, static_blend, switched_blend


def part_full_and_2022() -> dict:
    log("전체기간/2022 - H10 저장 CSV 재사용 + SPY 국면 신호 재계산")
    core_ret = pd.read_csv(PRIOR_DIR / "core_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_ret = pd.read_csv(PRIOR_DIR / "sat_trend_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]

    regime_raw = fetch_spy_regime_signal(FULL_START, FULL_END)
    weight_series = build_regime_switched_weight_series(core_ret.index, regime_raw)

    n_bull_days = int((weight_series > 0).sum())
    n_total = len(weight_series)
    log(f"  국면 스위치: 전체 {n_total}거래일 중 새틀라이트 ON(강세) {n_bull_days}일 "
        f"({n_bull_days/n_total*100:.1f}%), OFF(약세/위기) {n_total-n_bull_days}일")

    windows = {
        "full_2019_2026": (FULL_START, FULL_END),
        "bear_2022": (BEAR2022_START, BEAR2022_END),
    }
    table, static_blend, switched_blend = three_config_table(core_ret, sat_ret, weight_series, windows)
    return {
        "windows": table,
        "regime_on_pct": round(n_bull_days / n_total * 100, 2),
        "weight_series": weight_series,
        "switched_blend_ret": switched_blend,
        "static_blend_ret": static_blend,
        "core_ret": core_ret,
        "sat_ret": sat_ret,
    }


def part_gfc_2008(chosen_method: str) -> dict:
    log(f"2008 GFC - 3자산 코어 재구축 + point-in-time 새틀라이트({chosen_method}) + SPY 국면 신호")
    core = run_three_asset_champion(GFC_FULL_START, GFC_FULL_END)
    trading_index = core["ret_net"].index
    log(f"  3자산 코어 지표(전체): {core['metrics']}")

    sat = build_satellite_returns_period(GFC_FULL_START, GFC_FULL_END, trading_index,
                                          exclude=set(THREE_ASSET_UNIVERSE), method=chosen_method)
    log(f"  새틀라이트 지표(전체): {sat['metrics']}")

    regime_raw = fetch_spy_regime_signal(GFC_FULL_START, GFC_FULL_END)
    weight_series = build_regime_switched_weight_series(trading_index, regime_raw)
    n_bull_days = int((weight_series > 0).sum())
    n_total = len(weight_series)
    log(f"  국면 스위치(2008): 전체 {n_total}거래일 중 ON {n_bull_days}일 ({n_bull_days/n_total*100:.1f}%)")

    windows = {
        "full_2007_2009": (GFC_FULL_START, GFC_FULL_END),
        "crisis_2007_10_2009_06": (GFC_CRISIS_START, GFC_CRISIS_END),
    }
    table, static_blend, switched_blend = three_config_table(core["ret_net"], sat["ret_net"], weight_series, windows)
    return {
        "windows": table,
        "regime_on_pct": round(n_bull_days / n_total * 100, 2),
        "weight_series": weight_series,
        "switched_blend_ret": switched_blend,
        "static_blend_ret": static_blend,
        "core_ret": core["ret_net"],
        "sat_ret": sat["ret_net"],
        "satellite_rebal_log": sat["rebal_log"],
        "satellite_tickers_ever_held": sat["tickers_ever_held"],
    }


def main():
    t0 = time.time()
    h10 = json.loads((PRIOR_DIR / "h10_results.json").read_text(encoding="utf-8"))
    chosen_method = "trend_following" if (
        h10["placebo_retest_vs_h9_null"]["trend_following_percentile"]
        > h10["placebo_retest_vs_h9_null"]["momentum_percentile_recomputed"]
    ) else "momentum"
    log(f"H10 채택 방식: {chosen_method}")

    p1 = part_full_and_2022()
    p2 = part_gfc_2008(chosen_method)

    def strip_series(d):
        return {k: v for k, v in d.items() if not k.endswith("_ret") and k != "weight_series"}

    result = {
        "meta": {"satellite_weight_on": SATELLITE_WEIGHT_ON, "market_filter_ma": MARKET_FILTER_MA,
                  "chosen_satellite_method": chosen_method},
        "full_and_2022": strip_series(p1),
        "gfc_2008": {**strip_series(p2), "satellite_rebal_log": p2["satellite_rebal_log"],
                     "satellite_tickers_ever_held": p2["satellite_tickers_ever_held"]},
    }
    with open(OUT_DIR / "h12_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h12_results.json'}")

    # H13에서 재사용할 시계열 저장
    p1["weight_series"].to_frame("weight").to_csv(OUT_DIR / "full2022_weight_series.csv")
    p1["core_ret"].to_frame("core_ret").to_csv(OUT_DIR / "full2022_core_ret.csv")
    p1["sat_ret"].to_frame("sat_ret").to_csv(OUT_DIR / "full2022_sat_ret.csv")
    p2["weight_series"].to_frame("weight").to_csv(OUT_DIR / "gfc_weight_series.csv")
    p2["core_ret"].to_frame("core_ret").to_csv(OUT_DIR / "gfc_core_ret.csv")
    p2["sat_ret"].to_frame("sat_ret").to_csv(OUT_DIR / "gfc_sat_ret.csv")
    log(f"CSV 저장 완료 (H13 재사용용, 총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
