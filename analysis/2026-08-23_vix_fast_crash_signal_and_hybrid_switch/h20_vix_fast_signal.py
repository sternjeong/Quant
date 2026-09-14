"""H20 - VIX 급등 기반 신속 위기신호.

배경(작업37/H18-H19): 코어(17자산 챔피언)+15% 추세추종 새틀라이트+실시간청산+SPY-200일선
포트폴리오 스위치("Case B") 조합을 2008/2015-16/2018/2022/2020(COVID) 5개 위기 표본에서 검증한
결과, MDD는 5개 전부 개선됐지만 샤프는 2008 단 1개에서만 개선됐다. 특히 COVID 급락(2020-02-19~
2020-04-30, SPY가 약 5주만에 -34%)에서는 Case B가 코어단독보다 오히려 크게 악화됐다(샤프 -0.44 vs
+0.13) - SPY 200일선과 새틀라이트 자체의 돈치안20일 신호 둘 다 "추세"를 보는 후행 지표라 며칠~몇주
단위로 벌어지는 급락에는 구조적으로 못 따라간다는 것이 그 라운드의 결론.

이 스크립트는 VIX(옵션 내재변동성, S&P500 30일 기대변동성 - 가격 추세가 아니라 "현재 옵션 시장이
가격에 반영한 공포 수준"이므로 이론상 추세지표보다 반응이 빠를 수 있음)를 기반으로 한 신속
위기신호를 만들어 SPY-200일선 스위치를 대체했을 때 COVID 같은 급락에 실제로 더 빨리 반응하는지
직접 검증한다.

VIX 신호 설계: core.market_regime.score_vix()가 이미 CBOE 공식 정의+업계 관행 임계값(15/20/25/30)으로
밴드를 나누고 있고, 30 이상을 "패닉"으로 분류한다 - 이 30을 절대 임계값으로 채택한다(새로 발명하지
않음). 여기에 "급등 자체"를 포착하기 위해 10거래일 변동률(ROC10) >= +50%를 추가 조건으로 OR
결합한다(레벨이 아직 30 미만이어도 짧은 기간에 급하게 튀어오르는 것 자체를 신호로 잡기 위함).
신호가 True(위기)면 새틀라이트 비중을 0으로, False(평시)면 15%로 - SPY 스위치(h12_regime_switch)와
동일한 이진 온오프 구조, 동일 룩어헤드 방지 관례(전일 확정 신호를 당일 적용, 1일 shift).

2008/2022는 h18(작업37)이 이미 계산해 저장한 결과(core_alone/case_a/case_b)에 이 스크립트가
새로 계산하는 VIX 스위치(case_vix)만 추가한다(코어/새틀라이트 재계산 없이, h12/h16이 저장한
새틀라이트 반환수익률 CSV를 그대로 재사용). 나머지 3개 에피소드(2015-16/2018/COVID)는
h18과 동일한 방식으로 새로 코어+새틀라이트를 구축한다(캐시된 데이터라 재계산 비용은 작음).
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
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_satellite_realtime_stop_and_reentry_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-23_crisis_sample_expansion_and_risk_frontier"))

import numpy as np
import pandas as pd

from champion_strategy import run_champion, CHAMPION_UNIVERSE
from h1_core_satellite import blend_returns
from h11_crisis_robustness_test import build_satellite_returns_period, run_three_asset_champion, THREE_ASSET_UNIVERSE
from h12_regime_switch import (
    fetch_spy_regime_signal, build_regime_switched_weight_series, blend_returns_time_varying,
    SATELLITE_WEIGHT_ON, perf_metrics_slice,
)
from h16_realtime_trailing_stop_exit import build_realtime_exit_weights
from core.market_data import get_price_history
from core.market_regime import VIX_TICKER

OUT_DIR = Path(__file__).resolve().parent
H16_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_satellite_realtime_stop_and_reentry_research"
H12_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch"
H18_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_crisis_sample_expansion_and_risk_frontier"

SATELLITE_WEIGHT = 0.15
VIX_LEVEL_THRESHOLD = 30.0     # core.market_regime._VIX_BANDS의 "패닉" 임계값(기존 관례 재사용)
VIX_ROC_WINDOW = 10            # 10거래일
VIX_ROC_THRESHOLD = 0.50       # 10거래일간 +50% 이상 급등

# 5개 위기 에피소드 (h18과 동일 정의)
EPISODES = {
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
}
NEW_EPISODES = {k: v for k, v in EPISODES.items() if k in ("correction_2015_2016", "selloff_2018", "covid_2020")}
EPISODE_ORDER = ["gfc_2008", "correction_2015_2016", "selloff_2018", "bear_2022", "covid_2020"]
FULL_PERIOD_LABEL = "full_2019_2026"
FULL_START, FULL_END = "2019-08-12", "2026-08-19"


def log(msg):
    print(f"[h20] {msg}", flush=True)


def fetch_vix_signal(start: str, end: str, extra_warmup_days: int = 90) -> dict:
    """VIX 기반 위기신호 3종(레벨/ROC급등/결합)을 계산한다. 결합신호가 메인 채택 신호."""
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=extra_warmup_days)).date().isoformat()
    df = get_price_history(VIX_TICKER, start=fetch_start, end=end, interval="1d")
    vix = df["Close"]
    level_crisis = (vix >= VIX_LEVEL_THRESHOLD).fillna(False)
    roc = vix / vix.shift(VIX_ROC_WINDOW) - 1.0
    roc_crisis = (roc >= VIX_ROC_THRESHOLD).fillna(False)
    combined_crisis = (level_crisis | roc_crisis)
    combined_crisis.name = "vix_crisis_regime"
    return {"vix": vix, "level_crisis": level_crisis, "roc_crisis": roc_crisis, "combined_crisis": combined_crisis}


def build_vix_switched_weight_series(trading_index: pd.DatetimeIndex, crisis_raw: pd.Series,
                                      weight_on: float = SATELLITE_WEIGHT_ON) -> pd.Series:
    """crisis_raw(True=위기)를 SPY스위치와 동일한 형태(True=평시/ON)로 뒤집어 기존 함수 재사용."""
    ok_signal = ~crisis_raw
    ok_signal.name = "vix_ok_regime"
    return build_regime_switched_weight_series(trading_index, ok_signal, weight_on)


def count_flips(weight_series: pd.Series) -> dict:
    on = (weight_series > 0).astype(int)
    diff = on.diff().fillna(0)
    return {
        "n_flip_to_on": int((diff == 1).sum()),
        "n_flip_to_off": int((diff == -1).sum()),
        "total_flips": int((diff != 0).sum()),
        "flip_off_dates": [str(d.date()) for d in weight_series.index[diff == -1]],
        "flip_on_dates": [str(d.date()) for d in weight_series.index[diff == 1]],
    }


def four_way_windows(core_ret, sat_static_ret, sat_realtime_ret, spy_weight_series, vix_weight_series,
                      windows: dict) -> dict:
    static_blend = blend_returns(core_ret, sat_static_ret, SATELLITE_WEIGHT)
    spy_switch_blend = blend_returns_time_varying(core_ret, sat_realtime_ret, spy_weight_series)
    vix_switch_blend = blend_returns_time_varying(core_ret, sat_realtime_ret, vix_weight_series)
    table = {}
    for wname, (ws, we) in windows.items():
        table[wname] = {
            "core_alone": perf_metrics_slice(core_ret, ws, we),
            "case_a_static_satellite": perf_metrics_slice(static_blend, ws, we),
            "case_b_spy_switch": perf_metrics_slice(spy_switch_blend, ws, we),
            "case_c_vix_switch": perf_metrics_slice(vix_switch_blend, ws, we),
        }
    return table, {"static": static_blend, "spy_switch": spy_switch_blend, "vix_switch": vix_switch_blend}


def run_new_episode(label: str, full_start: str, full_end: str, crisis_start: str, crisis_end: str) -> dict:
    t0 = time.time()
    log(f"=== {label}: 코어 구축 {full_start}~{full_end} ===")
    core = run_champion(full_start, full_end)
    trading_index = core["ret_net"].index
    log(f"  코어 지표(전체): {core['metrics']}")

    sat = build_satellite_returns_period(full_start, full_end, trading_index, exclude=set(CHAMPION_UNIVERSE), method="trend_following")
    log(f"  정적 새틀라이트 지표(전체): {sat['metrics']}, 반기 리밸런싱 {len(sat['rebal_log'])}회")

    rt = build_realtime_exit_weights(sat["rebal_log"], full_start, full_end, trading_index)
    n_exits = sum(1 for e in rt["exit_events"] if e["exited_early"])
    log(f"  실시간청산 지표(전체): {rt['metrics']}, 조기청산 {n_exits}/{len(rt['exit_events'])}")

    spy_raw = fetch_spy_regime_signal(full_start, full_end)
    spy_weight = build_regime_switched_weight_series(trading_index, spy_raw, SATELLITE_WEIGHT)

    vix_sig = fetch_vix_signal(full_start, full_end)
    vix_weight = build_vix_switched_weight_series(trading_index, vix_sig["combined_crisis"].reindex(trading_index).ffill().fillna(False), SATELLITE_WEIGHT)

    windows = {"full_period": (full_start, full_end), "crisis_window": (crisis_start, crisis_end)}
    table, blends = four_way_windows(core["ret_net"], sat["ret_net"], rt["ret_net"], spy_weight, vix_weight, windows)

    spy_flips = count_flips(spy_weight)
    vix_flips = count_flips(vix_weight)
    spy_flips_crisis = count_flips(spy_weight[(spy_weight.index >= crisis_start) & (spy_weight.index <= crisis_end)])
    vix_flips_crisis = count_flips(vix_weight[(vix_weight.index >= crisis_start) & (vix_weight.index <= crisis_end)])

    result = {
        "label": label, "full_period": [full_start, full_end], "crisis_window": [crisis_start, crisis_end],
        "windows": table,
        "spy_switch_flips_full": spy_flips, "vix_switch_flips_full": vix_flips,
        "spy_switch_flips_crisis_window": spy_flips_crisis, "vix_switch_flips_crisis_window": vix_flips_crisis,
        "elapsed_s": round(time.time() - t0, 1),
        "_core_ret": core["ret_net"], "_sat_realtime_ret": rt["ret_net"], "_spy_weight": spy_weight, "_vix_weight": vix_weight,
    }
    log(f"  {label} 완료 ({result['elapsed_s']}s) | SPY전환 {spy_flips['total_flips']}회 vs VIX전환 {vix_flips['total_flips']}회(전체구간)")
    return result


def run_reused_episode(label: str) -> dict:
    """2008/2022는 h16/h12가 저장한 새틀라이트/코어 수익률 CSV를 그대로 재사용, VIX 스위치만 신규 계산."""
    full_start, full_end, crisis_start, crisis_end = EPISODES[label]
    t0 = time.time()
    if label == "bear_2022":
        core_ret = pd.read_csv(H16_DIR / "full_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        sat_static_ret = pd.read_csv(H16_DIR / "full_static_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        sat_rt_ret = pd.read_csv(H16_DIR / "full_realtime_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        spy_weight = pd.read_csv(H12_DIR / "full2022_weight_series.csv", index_col=0, parse_dates=True).iloc[:, 0]
    elif label == "gfc_2008":
        core_ret = pd.read_csv(H12_DIR / "gfc_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        sat_static_ret = pd.read_csv(H12_DIR / "gfc_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        # H16은 GFC 실시간청산 새틀라이트 수익률 시계열을 CSV로 저장하지 않았으므로(전체구간 CSV만
        # 저장) 여기서만 h16_realtime_trailing_stop_exit의 함수로 재구축(재계산 - h12가 저장한
        # rebal_log 재사용, 신규 선정 로직 없음)
        h12 = json.loads((H12_DIR / "h12_results.json").read_text(encoding="utf-8"))
        rebal_log = h12["gfc_2008"]["satellite_rebal_log"]
        core3 = run_three_asset_champion(full_start, full_end)
        trading_index = core3["ret_net"].index
        rt = build_realtime_exit_weights(rebal_log, full_start, full_end, trading_index)
        sat_rt_ret = rt["ret_net"]
        spy_weight = pd.read_csv(H12_DIR / "gfc_weight_series.csv", index_col=0, parse_dates=True).iloc[:, 0]
    else:
        raise ValueError(label)

    trading_index = core_ret.index
    vix_sig = fetch_vix_signal(full_start, full_end)
    vix_weight = build_vix_switched_weight_series(trading_index, vix_sig["combined_crisis"].reindex(trading_index).ffill().fillna(False), SATELLITE_WEIGHT)

    windows = {"full_period": (full_start, full_end), "crisis_window": (crisis_start, crisis_end)}
    table, blends = four_way_windows(core_ret, sat_static_ret, sat_rt_ret, spy_weight, vix_weight, windows)

    spy_flips = count_flips(spy_weight)
    vix_flips = count_flips(vix_weight)
    spy_flips_crisis = count_flips(spy_weight[(spy_weight.index >= crisis_start) & (spy_weight.index <= crisis_end)])
    vix_flips_crisis = count_flips(vix_weight[(vix_weight.index >= crisis_start) & (vix_weight.index <= crisis_end)])

    result = {
        "label": label, "full_period": [full_start, full_end], "crisis_window": [crisis_start, crisis_end],
        "windows": table,
        "spy_switch_flips_full": spy_flips, "vix_switch_flips_full": vix_flips,
        "spy_switch_flips_crisis_window": spy_flips_crisis, "vix_switch_flips_crisis_window": vix_flips_crisis,
        "elapsed_s": round(time.time() - t0, 1), "note": "코어/새틀라이트는 h12/h16 저장분 재사용, VIX 스위치만 신규 계산",
        "_core_ret": core_ret, "_sat_realtime_ret": sat_rt_ret, "_spy_weight": spy_weight, "_vix_weight": vix_weight,
    }
    log(f"  {label}(재사용) 완료 ({result['elapsed_s']}s) | SPY전환 {spy_flips['total_flips']}회 vs VIX전환 {vix_flips['total_flips']}회(전체구간)")
    return result


def run_full_period_2019_2026() -> dict:
    """전체기간(2019-2026, 위기무관) 6번째 창 - h18에는 없던 창, H20/H21 스펙이 명시적으로 요구."""
    return run_reused_episode("bear_2022") | {"label": FULL_PERIOD_LABEL}


def covid_reaction_speed_comparison(covid_ep: dict) -> dict:
    """COVID 위기구간에서 VIX 스위치 vs SPY 스위치가 각각 언제 처음 OFF로 전환됐는지, 그 시점까지
    SPY 시장 자체의 낙폭과 새틀라이트(실시간청산판) 낙폭이 최종 낙폭 대비 몇 %나 이미 실현됐는지."""
    crisis_start, crisis_end = covid_ep["crisis_window"]
    spy_weight = covid_ep["_spy_weight"]
    vix_weight = covid_ep["_vix_weight"]

    def first_off_in_window(weight_series):
        w = weight_series[(weight_series.index >= crisis_start) & (weight_series.index <= crisis_end)]
        on = (w > 0).astype(int)
        diff = on.diff().fillna(0)
        offs = w.index[diff == -1]
        if len(offs) > 0:
            return str(offs[0].date())
        # 위기 진입 전에 이미 꺼져있었는지 확인
        pre = weight_series[weight_series.index < crisis_start]
        if len(pre) and pre.iloc[-1] == 0:
            return "already_off_before_crisis"
        return None

    spy_off_date = first_off_in_window(spy_weight)
    vix_off_date = first_off_in_window(vix_weight)

    # SPY 시장 자체의 위기구간 낙폭 궤적
    spy_hist = get_price_history("SPY", start=(pd.Timestamp(crisis_start) - pd.DateOffset(days=10)).date().isoformat(), end=crisis_end, interval="1d")
    spy_close = spy_hist["Close"]
    spy_close_win = spy_close[(spy_close.index >= crisis_start) & (spy_close.index <= crisis_end)]
    spy_peak = spy_close_win.cummax()
    spy_dd = spy_close_win / spy_peak - 1.0
    final_spy_mdd = float(spy_dd.min())
    final_spy_mdd_date = spy_dd.idxmin()

    # 새틀라이트(실시간청산판) 위기구간 낙폭 궤적
    sat_ret = covid_ep["_sat_realtime_ret"]
    sat_win = sat_ret[(sat_ret.index >= crisis_start) & (sat_ret.index <= crisis_end)]
    sat_eq = (1 + sat_win.fillna(0.0)).cumprod()
    sat_dd = sat_eq / sat_eq.cummax() - 1.0
    final_sat_mdd = float(sat_dd.min()) if len(sat_dd) else None

    def pct_realized(off_date, dd_series, final_mdd):
        if off_date in (None, "already_off_before_crisis"):
            return None
        ts = pd.Timestamp(off_date)
        if ts not in dd_series.index or final_mdd == 0:
            return None
        return round(float(dd_series.loc[ts]) / final_mdd * 100, 1)

    result = {
        "crisis_window": [crisis_start, crisis_end],
        "spy_switch_first_off_date": spy_off_date,
        "vix_switch_first_off_date": vix_off_date,
        "spy_market_final_dd_pct": round(final_spy_mdd * 100, 2),
        "spy_market_final_dd_date": str(final_spy_mdd_date.date()),
        "satellite_realtime_final_dd_pct": round(final_sat_mdd * 100, 2) if final_sat_mdd is not None else None,
        "pct_of_spy_market_dd_already_realized_at_spy_switch_off": pct_realized(spy_off_date, spy_dd, final_spy_mdd),
        "pct_of_spy_market_dd_already_realized_at_vix_switch_off": pct_realized(vix_off_date, spy_dd, final_spy_mdd),
        "pct_of_satellite_dd_already_realized_at_spy_switch_off": pct_realized(spy_off_date, sat_dd, final_sat_mdd) if final_sat_mdd else None,
        "pct_of_satellite_dd_already_realized_at_vix_switch_off": pct_realized(vix_off_date, sat_dd, final_sat_mdd) if final_sat_mdd else None,
    }
    log(f"COVID 반응속도: SPY스위치 OFF={spy_off_date}, VIX스위치 OFF={vix_off_date}")
    log(f"  SPY시장 최종낙폭 {result['spy_market_final_dd_pct']}% 중 SPY스위치 시점까지 실현 "
        f"{result['pct_of_spy_market_dd_already_realized_at_spy_switch_off']}%, "
        f"VIX스위치 시점까지 실현 {result['pct_of_spy_market_dd_already_realized_at_vix_switch_off']}%")
    return result


def whipsaw_false_alarm_check(episodes: dict) -> dict:
    """2015-16/2018 - 실제로는 위기가 본격화되지 않은(또는 상대적으로 얕은) 조정 구간에서 VIX
    스위치가 SPY 스위치보다 더 자주/더 일찍 새틀라이트를 껐는지(휘프쏘/오탐 여부)."""
    out = {}
    for label in ("correction_2015_2016", "selloff_2018"):
        ep = episodes[label]
        out[label] = {
            "spy_switch_total_flips_full_period": ep["spy_switch_flips_full"]["total_flips"],
            "vix_switch_total_flips_full_period": ep["vix_switch_flips_full"]["total_flips"],
            "spy_switch_flips_in_crisis_window": ep["spy_switch_flips_crisis_window"]["total_flips"],
            "vix_switch_flips_in_crisis_window": ep["vix_switch_flips_crisis_window"]["total_flips"],
            "vix_switch_off_dates_full_period": ep["vix_switch_flips_full"]["flip_off_dates"],
            "spy_switch_off_dates_full_period": ep["spy_switch_flips_full"]["flip_off_dates"],
            "case_b_spy_vs_case_c_vix_sharpe_crisis_window": {
                "spy": ep["windows"]["crisis_window"]["case_b_spy_switch"].get("sharpe"),
                "vix": ep["windows"]["crisis_window"]["case_c_vix_switch"].get("sharpe"),
            },
        }
    return out


def main():
    t0 = time.time()
    episodes = {}
    episodes["gfc_2008"] = run_reused_episode("gfc_2008")
    episodes["bear_2022"] = run_reused_episode("bear_2022")
    for label, (fs, fe, cs, ce) in NEW_EPISODES.items():
        episodes[label] = run_new_episode(label, fs, fe, cs, ce)
    episodes[FULL_PERIOD_LABEL] = run_full_period_2019_2026()

    covid_speed = covid_reaction_speed_comparison(episodes["covid_2020"])
    whipsaw = whipsaw_false_alarm_check(episodes)

    # 요약 표: 6개 창 x (core/A/B/C) crisis_window(전체기간 창은 full_period) CAGR/MDD/Sharpe
    summary_rows = []
    order = EPISODE_ORDER + [FULL_PERIOD_LABEL]
    for label in order:
        ep = episodes[label]
        wkey = "full_period" if label == FULL_PERIOD_LABEL else "crisis_window"
        w = ep["windows"][wkey]
        row = {"episode": label, "window_used": wkey, "window_dates": ep["crisis_window"] if wkey == "crisis_window" else ep["full_period"]}
        for cfg in ["core_alone", "case_a_static_satellite", "case_b_spy_switch", "case_c_vix_switch"]:
            m = w[cfg]
            row[cfg] = {"cagr": m.get("cagr"), "mdd": m.get("mdd"), "sharpe": m.get("sharpe")}
        summary_rows.append(row)

    def strip(ep):
        return {k: v for k, v in ep.items() if not k.startswith("_")}

    result = {
        "meta": {
            "satellite_weight": SATELLITE_WEIGHT, "vix_level_threshold": VIX_LEVEL_THRESHOLD,
            "vix_roc_window": VIX_ROC_WINDOW, "vix_roc_threshold": VIX_ROC_THRESHOLD,
            "episode_order": order,
        },
        "episodes": {k: strip(v) for k, v in episodes.items()},
        "summary_table": summary_rows,
        "covid_reaction_speed_comparison": covid_speed,
        "whipsaw_false_alarm_check": whipsaw,
    }
    with open(OUT_DIR / "h20_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h20_results.json'} (총 {time.time()-t0:.0f}s)")

    # H21 재사용용: 각 에피소드의 시계열(core_ret/sat_realtime_ret/spy_weight/vix_weight)을 pickle로 저장
    import pickle
    with open(OUT_DIR / "h20_series_cache.pkl", "wb") as f:
        pickle.dump({k: {sk: sv for sk, sv in v.items() if sk.startswith("_")} for k, v in episodes.items()}, f)
    log("H21 재사용용 시계열 캐시 저장 완료 (h20_series_cache.pkl)")


if __name__ == "__main__":
    main()
