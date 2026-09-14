"""H23 - 연속 확률 기반 노출 사이징(continuous crisis-probability exposure) vs 이산 스위치.

배경: 작업38(H20/H21)까지 테스트한 모든 스위치(SPY-200일선, VIX, 하이브리드 OR결합)는 전부 이산
(0% 또는 15%) on/off다. 사용자의 재프레이밍("단일 정답은 없어도 확률로 기댓값을 올린다")을 그대로
받아, "지금이 위기인지 아닌지"를 하드 임계값으로 양자화하지 않고 매일 연속적인 위기확률을 추정해서
그 확률의 여집합만큼 새틀라이트 비중을 부드럽게 줄이는 방식이 이산 스위치보다 기대값(Sharpe/CAGR)
측면에서 실제로 더 나은지 직접 새로 백테스트한다.

설계(정직하게 단순한 함수형태):
  vix_component(t)  = clip((VIX(t) - 15) / (30 - 15), 0, 1)
      15는 core.market_regime의 "평온" 밴드 하한, 30은 H20이 채택한 "패닉" 절대임계값 - 기존
      관례를 그대로 재사용, 새로 발명한 숫자 아님.
  spy_component(t)  = clip( max(0, (SMA200(t) - SPY(t)) / SMA200(t)) / 0.15, 0, 1)
      SPY가 200일선 위에 있으면 0, 200일선 대비 -15% 이상 벌어지면 1(포화) - 15%는 H19가 스윕한
      트레일링스탑 폭의 상단(0.30)의 절반, 그리고 새틀라이트 목표비중 자체가 15%라는 점과 우연히
      일치하는 라운드 넘버로 선택(정확한 최적화 없음, 명시적 가정).
  combined(t) = 1 - (1 - vix_component(t)) * (1 - spy_component(t))   [soft-OR, 두 신호 중 하나만
      켜져도 확률이 올라가되 이산 OR스위치처럼 계단식이 아니라 연속적으로]
  crisis_prob(t) = sigmoid(6 * (combined(t) - 0.5))                   [완만한 로지스틱 스무딩 -
      combined가 0.5 근방을 지날 때만 확률이 빠르게 변하고, 극단값 근처에서는 평평해짐]
  satellite_weight(t) = 0.15 * (1 - crisis_prob(t))                   [연속 사이징]

룩어헤드 방지: SPY스위치/VIX스위치와 동일하게 전일 확정치를 1일 shift해서 당일 비중에 적용.

코어/새틀라이트(실시간청산) 수익률 시계열은 h20_series_cache.pkl(직전 라운드 저장분)을 그대로
재사용한다 - 17자산 챔피언 재구축 비용을 피함. 이 파일이 없으면 스크립트가 즉시 에러를 낸다
(조용히 폴백하지 않음 - 사용자 프로세스 규칙).
"""
from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
H20_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_vix_fast_crash_signal_and_hybrid_switch"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))

import numpy as np
import pandas as pd

from h12_regime_switch import blend_returns_time_varying, perf_metrics_slice, SATELLITE_WEIGHT_ON
from core.market_data import get_price_history, get_multiple_price_history
from core.market_regime import VIX_TICKER

OUT_DIR = Path(__file__).resolve().parent
SATELLITE_WEIGHT = SATELLITE_WEIGHT_ON  # 0.15
VIX_CALM, VIX_PANIC = 15.0, 30.0
SPY_DD_SATURATION = 0.15
LOGISTIC_STEEPNESS = 6.0
MARKET_FILTER_MA = 200

EPISODES = {
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
    "full_2019_2026": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
}
EPISODE_ORDER = ["gfc_2008", "correction_2015_2016", "selloff_2018", "bear_2022", "covid_2020", "full_2019_2026"]


def log(msg):
    print(f"[h23] {msg}", flush=True)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def build_continuous_crisis_prob(full_start: str, full_end: str, extra_warmup_days: int = 400) -> pd.Series:
    fetch_start = (pd.Timestamp(full_start) - pd.DateOffset(days=extra_warmup_days)).date().isoformat()
    vix_df = get_price_history(VIX_TICKER, start=fetch_start, end=full_end, interval="1d")
    vix = vix_df["Close"]
    spy_hist = get_multiple_price_history(["SPY"], start=fetch_start, end=full_end, interval="1d")
    spy = spy_hist["SPY"]["Close"]
    sma = spy.rolling(MARKET_FILTER_MA, min_periods=MARKET_FILTER_MA).mean()

    vix_component = ((vix - VIX_CALM) / (VIX_PANIC - VIX_CALM)).clip(0.0, 1.0)
    spy_dd = ((sma - spy) / sma).clip(lower=0.0)
    spy_component = (spy_dd / SPY_DD_SATURATION).clip(0.0, 1.0)

    vix_a, spy_a = vix_component.align(spy_component, join="inner")
    combined = 1.0 - (1.0 - vix_a.fillna(0.0)) * (1.0 - spy_a.fillna(0.0))
    crisis_prob = sigmoid(LOGISTIC_STEEPNESS * (combined - 0.5))
    crisis_prob.name = "crisis_prob"
    return crisis_prob, vix_component, spy_component


def build_continuous_weight_series(trading_index: pd.DatetimeIndex, crisis_prob_raw: pd.Series,
                                    weight_on: float = SATELLITE_WEIGHT) -> pd.Series:
    prob_aligned = crisis_prob_raw.reindex(trading_index).ffill()
    prob_lagged = prob_aligned.shift(1).fillna(0.0)  # 전일 확정치 -> 당일 적용 (SPY/VIX 스위치와 동일 관례)
    w = (1.0 - prob_lagged) * weight_on
    w.name = "satellite_weight_continuous"
    return w


def avg_daily_turnover(weight_series: pd.Series) -> float:
    """이산 스위치의 '전환횟수' 대신 연속버전에 맞는 유사 지표: 일간 |Δw| 절대값의 평균(비중 기준)."""
    d = weight_series.diff().abs().dropna()
    return float(d.mean())


def main():
    t0 = time.time()
    cache_path = H20_DIR / "h20_series_cache.pkl"
    if not cache_path.exists():
        raise FileNotFoundError(f"h20 series cache not found at {cache_path} - 이전 라운드 저장분 필요")
    with open(cache_path, "rb") as f:
        series_cache = pickle.load(f)

    h20_results = json.loads((H20_DIR / "h20_results.json").read_text(encoding="utf-8"))

    results = {}
    weight_series_store = {}
    for label in EPISODE_ORDER:
        full_start, full_end, crisis_start, crisis_end = EPISODES[label]
        log(f"=== {label}: 연속노출 계산 {full_start}~{full_end} ===")
        cached = series_cache[label]
        core_ret = cached["_core_ret"]
        sat_realtime_ret = cached["_sat_realtime_ret"]
        trading_index = core_ret.index

        crisis_prob, vix_comp, spy_comp = build_continuous_crisis_prob(full_start, full_end)
        cont_weight = build_continuous_weight_series(trading_index, crisis_prob)
        blend = blend_returns_time_varying(core_ret, sat_realtime_ret, cont_weight)

        windows = {"full_period": (full_start, full_end), "crisis_window": (crisis_start, crisis_end)}
        window_metrics = {}
        for wname, (ws, we) in windows.items():
            window_metrics[wname] = {
                "core_alone": perf_metrics_slice(core_ret, ws, we),
                "case_e_continuous_exposure": perf_metrics_slice(blend, ws, we),
            }

        results[label] = {
            "full_period": [full_start, full_end],
            "crisis_window": [crisis_start, crisis_end],
            "windows": window_metrics,
            "avg_daily_abs_delta_weight_full_period": avg_daily_turnover(cont_weight),
            "mean_crisis_prob_full_period": float(crisis_prob.reindex(trading_index).mean()),
            "mean_satellite_weight_full_period": float(cont_weight.mean()),
            "elapsed_s": round(time.time() - t0, 1),
        }
        weight_series_store[label] = {
            "crisis_prob": crisis_prob,
            "continuous_weight": cont_weight,
        }
        log(f"  full_period continuous sharpe={window_metrics['full_period']['case_e_continuous_exposure'].get('sharpe')} "
            f"crisis_window continuous sharpe={window_metrics['crisis_window']['case_e_continuous_exposure'].get('sharpe')}")

    # ---- COVID/2008 반응속도 비교: 연속버전이 실제로 위기 시작 전에 비중을 얼마나 미리/서서히 줄였는가 ----
    reaction_speed = {}
    for label in ["covid_2020", "gfc_2008"]:
        cont_weight = weight_series_store[label]["continuous_weight"]
        crisis_start, crisis_end = EPISODES[label][2], EPISODES[label][3]
        pre_crisis = cont_weight[(cont_weight.index >= pd.Timestamp(crisis_start) - pd.Timedelta(days=30)) &
                                  (cont_weight.index <= pd.Timestamp(crisis_end))]
        first_below_half = pre_crisis[pre_crisis <= SATELLITE_WEIGHT * 0.5]
        first_near_zero = pre_crisis[pre_crisis <= SATELLITE_WEIGHT * 0.1]
        spy_switch_first_off = h20_results.get(label, {}).get("spy_switch_flips_full", {}) if label in h20_results else None
        reaction_speed[label] = {
            "weight_at_crisis_start": float(cont_weight.reindex([pd.Timestamp(crisis_start)], method="nearest").iloc[0]),
            "weight_at_crisis_end": float(cont_weight.reindex([pd.Timestamp(crisis_end)], method="nearest").iloc[0]),
            "first_date_weight_below_half": str(first_below_half.index[0].date()) if len(first_below_half) else None,
            "first_date_weight_near_zero": str(first_near_zero.index[0].date()) if len(first_near_zero) else None,
            "min_weight_in_crisis_window": float(cont_weight[(cont_weight.index >= pd.Timestamp(crisis_start)) &
                                                               (cont_weight.index <= pd.Timestamp(crisis_end))].min()),
        }

    out = {
        "meta": {
            "satellite_weight_on": SATELLITE_WEIGHT,
            "vix_calm": VIX_CALM,
            "vix_panic": VIX_PANIC,
            "spy_dd_saturation": SPY_DD_SATURATION,
            "logistic_steepness": LOGISTIC_STEEPNESS,
            "episode_order": EPISODE_ORDER,
            "formula": "crisis_prob = sigmoid(6*(soft_or(vix_component, spy_component) - 0.5)); satellite_weight = 0.15*(1-crisis_prob)",
        },
        "episodes": results,
        "reaction_speed_covid_gfc": reaction_speed,
    }
    (OUT_DIR / "h23_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"완료. h23_results.json 저장. 총 {round(time.time()-t0,1)}s")


if __name__ == "__main__":
    main()
