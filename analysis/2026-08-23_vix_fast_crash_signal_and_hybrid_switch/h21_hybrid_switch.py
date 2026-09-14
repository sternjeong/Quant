"""H21 - 빠름(VIX)+느림(SPY-200일선) 이중속도 하이브리드 스위치.

H20이 검증한 VIX 기반 신속 신호는 이론상 COVID형 급락엔 SPY-200일선보다 빠르게 반응할 수 있지만,
그 자체로 2015-16/2018 같은 "위기로 번지지 않은 변동성 스파이크" 구간에서 휘프쏘를 일으킬 위험도
같이 갖고 있다(H20 결과에서 실측). 이 스크립트는 두 신호를 OR로 결합한 하이브리드 스위치를 만든다:

  새틀라이트 OFF <=> (SPY < 200일선) OR (VIX 위기신호 True)

즉 "느린 신호(SPY추세)가 이미 알고 있던 2008형 위기 방어력은 유지하면서, 느린 신호가 아직
못 잡은 급락(COVID형)은 빠른 신호(VIX)가 커버"하도록 설계한 절충안. h20_series_cache.pkl에 저장된
6개 창(5위기+전체기간)의 코어/새틀라이트(실시간청산)/SPY가중치/VIX가중치 시계열을 그대로 재사용해
새로 코어·새틀라이트를 재구축하지 않는다(재계산 없음 - 순수 조합 로직만 추가).

검증 항목:
  1. 6개 창(5위기+2019-2026 전체기간) x 5가지 구성(core_alone/case_a_static/case_b_spy만/
     case_c_vix만/case_d_hybrid) CAGR/MDD/Sharpe 통합표.
  2. 하이브리드의 전환 횟수(6개 창 합산) 및 전환비용(왕복0.1%=편도5bp, h13/작업34 관례 재사용)
     반영 전후 샤프 - SPY단독 대비 전환비용이 유의미하게 늘었는지 정량화.
  3. 최종 권고: 하이브리드가 Case B(SPY전용)의 2008형 방어력을 유지하면서 COVID 실패를 고치고,
     2015-16/2018 휘프쏘 비용을 감내할만한 수준으로 억제하는지 - 6개 창 전체를 아우르는 단일 최선
     구성이 있는지, 아니면 여전히 트레이드오프가 남는지.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))

import pandas as pd

from champion_strategy import COST_BPS_PER_SIDE
from h1_core_satellite import blend_returns
from h12_regime_switch import blend_returns_time_varying, perf_metrics_slice, SATELLITE_WEIGHT_ON
from core.backtest_engine import calculate_metrics

OUT_DIR = Path(__file__).resolve().parent
SATELLITE_WEIGHT = 0.15
SWITCH_COST_BPS_PER_SIDE = COST_BPS_PER_SIDE  # 5bp, 이 저장소 기존 관례(왕복 0.1%)

EPISODE_ORDER = ["gfc_2008", "correction_2015_2016", "selloff_2018", "bear_2022", "covid_2020", "full_2019_2026"]


def log(msg):
    print(f"[h21] {msg}", flush=True)


def load_h20_series() -> dict:
    with open(OUT_DIR / "h20_series_cache.pkl", "rb") as f:
        return pickle.load(f)


def load_h20_results() -> dict:
    return json.loads((OUT_DIR / "h20_results.json").read_text(encoding="utf-8"))


def build_hybrid_weight_series(spy_weight: pd.Series, vix_weight: pd.Series, weight_on: float = SATELLITE_WEIGHT) -> pd.Series:
    """OR 결합: 둘 중 하나라도 OFF(0)면 하이브리드도 OFF. 둘 다 ON이어야 하이브리드 ON."""
    spy_a, vix_a = spy_weight.align(vix_weight, join="inner")
    spy_on = spy_a > 0
    vix_on = vix_a > 0
    hybrid_on = spy_on & vix_on
    w = hybrid_on.astype(float) * weight_on
    w.name = "satellite_weight_hybrid"
    return w


def count_flips(weight_series: pd.Series) -> dict:
    on = (weight_series > 0).astype(int)
    diff = on.diff().fillna(0)
    return {
        "n_flip_to_on": int((diff == 1).sum()),
        "n_flip_to_off": int((diff == -1).sum()),
        "total_flips": int((diff != 0).sum()),
        "flip_off_dates": [str(d.date()) for d in weight_series.index[diff == -1]],
    }


def switch_cost_adjusted(core_ret: pd.Series, sat_ret: pd.Series, weight: pd.Series, cost_bps: float) -> tuple[pd.Series, pd.Series]:
    core_a, sat_a = core_ret.align(sat_ret, join="inner")
    w = weight.reindex(core_a.index).fillna(0.0)
    gross = (1 - w) * core_a + w * sat_a
    dw = w.diff().abs().fillna(0.0)
    cost = dw * (cost_bps / 10000.0)
    net = gross - cost
    return gross, net


def metrics_from_ret(ret: pd.Series) -> dict:
    eq = (1 + ret.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    return calculate_metrics(eq, [], eq.index[0], eq.index[-1])


def main():
    series = load_h20_series()
    h20 = load_h20_results()

    per_episode = {}
    all_flip_counts_full = {}
    all_flip_counts_crisis = {}

    for label in EPISODE_ORDER:
        ep_series = series[label]
        core_ret = ep_series["_core_ret"]
        sat_ret = ep_series["_sat_realtime_ret"]
        spy_w = ep_series["_spy_weight"]
        vix_w = ep_series["_vix_weight"]
        hybrid_w = build_hybrid_weight_series(spy_w, vix_w, SATELLITE_WEIGHT)

        h20_ep = h20["episodes"][label]
        crisis_start, crisis_end = h20_ep["crisis_window"]
        full_start, full_end = h20_ep["full_period"]
        wkey_for_summary = "full_period" if label == "full_2019_2026" else "crisis_window"

        hybrid_blend = blend_returns_time_varying(core_ret, sat_ret, hybrid_w)

        windows = {"full_period": (full_start, full_end), "crisis_window": (crisis_start, crisis_end)}
        table = {}
        for wname, (ws, we) in windows.items():
            base = h20_ep["windows"][wname]
            table[wname] = {
                "core_alone": base["core_alone"],
                "case_a_static_satellite": base["case_a_static_satellite"],
                "case_b_spy_switch": base["case_b_spy_switch"],
                "case_c_vix_switch": base["case_c_vix_switch"],
                "case_d_hybrid_or_switch": perf_metrics_slice(hybrid_blend, ws, we),
            }

        flips_full = count_flips(hybrid_w)
        flips_crisis = count_flips(hybrid_w[(hybrid_w.index >= crisis_start) & (hybrid_w.index <= crisis_end)])
        all_flip_counts_full[label] = flips_full["total_flips"]
        all_flip_counts_crisis[label] = flips_crisis["total_flips"]

        # 전환비용 반영 (전체기간 창 기준)
        gross, net = switch_cost_adjusted(core_ret, sat_ret, hybrid_w, SWITCH_COST_BPS_PER_SIDE)
        m_gross = metrics_from_ret(gross[(gross.index >= full_start) & (gross.index <= full_end)])
        m_net = metrics_from_ret(net[(net.index >= full_start) & (net.index <= full_end)])
        cost_drag_bps = float((gross - net)[(gross.index >= full_start) & (gross.index <= full_end)].sum() * 10000)

        per_episode[label] = {
            "crisis_window": [crisis_start, crisis_end], "full_period": [full_start, full_end],
            "windows": table,
            "hybrid_flips_full_period": flips_full, "hybrid_flips_crisis_window": flips_crisis,
            "spy_flips_full_period_total": h20_ep["spy_switch_flips_full"]["total_flips"],
            "vix_flips_full_period_total": h20_ep["vix_switch_flips_full"]["total_flips"],
            "hybrid_switch_cost_full_period": {
                "sharpe_before_cost": m_gross["sharpe"], "sharpe_after_cost": m_net["sharpe"],
                "cumulative_cost_drag_bps": round(cost_drag_bps, 2),
            },
        }
        log(f"{label}: 하이브리드 전환(전체구간) {flips_full['total_flips']}회 "
            f"(SPY단독 {h20_ep['spy_switch_flips_full']['total_flips']}회, VIX단독 {h20_ep['vix_switch_flips_full']['total_flips']}회) "
            f"| 위기구간 전환 {flips_crisis['total_flips']}회 | 전환비용반영 샤프 {m_gross['sharpe']:.4f}->{m_net['sharpe']:.4f}")

    total_hybrid_flips_full = sum(all_flip_counts_full.values())
    total_spy_flips_full = sum(h20["episodes"][lb]["spy_switch_flips_full"]["total_flips"] for lb in EPISODE_ORDER)
    total_vix_flips_full = sum(h20["episodes"][lb]["vix_switch_flips_full"]["total_flips"] for lb in EPISODE_ORDER)

    # 요약표 (5구성 x 6창)
    summary_rows = []
    for label in EPISODE_ORDER:
        ep = per_episode[label]
        wkey = "full_period" if label == "full_2019_2026" else "crisis_window"
        w = ep["windows"][wkey]
        row = {"episode": label, "window_used": wkey}
        for cfg in ["core_alone", "case_a_static_satellite", "case_b_spy_switch", "case_c_vix_switch", "case_d_hybrid_or_switch"]:
            m = w[cfg]
            row[cfg] = {"cagr": m.get("cagr"), "mdd": m.get("mdd"), "sharpe": m.get("sharpe")}
        summary_rows.append(row)

    result = {
        "meta": {"satellite_weight": SATELLITE_WEIGHT, "switch_cost_bps_per_side": SWITCH_COST_BPS_PER_SIDE, "episode_order": EPISODE_ORDER},
        "episodes": per_episode,
        "summary_table": summary_rows,
        "turnover_comparison_all_windows_combined": {
            "total_hybrid_flips": total_hybrid_flips_full,
            "total_spy_only_flips": total_spy_flips_full,
            "total_vix_only_flips": total_vix_flips_full,
            "flips_per_episode_hybrid": all_flip_counts_full,
            "flips_per_episode_hybrid_crisis_window_only": all_flip_counts_crisis,
        },
    }
    with open(OUT_DIR / "h21_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h21_results.json'}")
    log(f"전체 6개 창 합산 전환 횟수: 하이브리드={total_hybrid_flips_full}, SPY단독={total_spy_flips_full}, VIX단독={total_vix_flips_full}")


if __name__ == "__main__":
    main()
