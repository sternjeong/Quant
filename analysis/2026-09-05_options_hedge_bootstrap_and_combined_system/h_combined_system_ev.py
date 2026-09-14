"""H_combined - 코어+새틀라이트+칼라 통합 시스템의 기댓값(H22 기저확률 가중) 재검증.

작업48의 옵션헤지 리포트는 칼라를 "새틀라이트 슬리브 단독"에 대해서만 비교했다. 이 스크립트는
동일한 옵션 오버레이 수익률을, H22가 쓴 정확한 기저확률 시나리오(base/calm_heavy/crisis_heavy)로
가중해 (a) 코어단독, (b) 코어+새틀라이트(무헤지, 이 프로그램의 기존 기댓값-선호 baseline),
(c) 코어+새틀라이트+칼라, 세 구성의 기댓값 샤프/CAGR 순위를 낸다. 칼라 오버레이는 새틀라이트
비중(15%)에만 적용되므로("포트폴리오 전체가 아니라 새틀라이트를 보호"), 평시 프리미엄 드래그도
포트폴리오 전체가 아닌 그 15% 슬리브에서만 발생 - 이 스크립트는 그 희석 효과가 기댓값 순위를
바꾸는지 정량적으로 확인한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-30_synthetic_options_tail_hedge"))

import h_options_hedge as hh

OUT_DIR = Path(__file__).resolve().parent
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
CONFIGS = ["core_alone", "unhedged_satellite", "collar_full_system"]

BASE_RATES = {
    "base": {"full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04, "bear_2022": 0.10,
             "selloff_2018": 0.16, "correction_2015_2016": 0.17},
    "calm_heavy": {"full_2019_2026": 0.65, "gfc_2008": 0.015, "covid_2020": 0.02, "bear_2022": 0.065,
                   "selloff_2018": 0.12, "correction_2015_2016": 0.13},
    "crisis_heavy": {"full_2019_2026": 0.35, "gfc_2008": 0.06, "covid_2020": 0.07, "bear_2022": 0.14,
                     "selloff_2018": 0.19, "correction_2015_2016": 0.19},
}


def log(msg):
    print(f"[combined] {msg}", flush=True)


def normalize(w: dict) -> dict:
    s = sum(w.values())
    return {k: v / s for k, v in w.items()}


def gather_per_episode_metrics() -> dict:
    series = hh.load_h20_series()
    h20 = hh.load_h20_results()
    out = {}
    for label in EPISODE_ORDER:
        log(f"  {label}: 재계산")
        ep_returns = hh.run_episode(label, series, put_moneyness=1.00, call_moneyness=1.05)
        h20_ep = h20["episodes"][label]
        crisis_start, crisis_end = h20_ep["crisis_window"]
        full_start, full_end = h20_ep["full_period"]
        wkey = "full_period" if label == "full_2019_2026" else "crisis_window"
        w_start, w_end = (full_start, full_end) if wkey == "full_period" else (crisis_start, crisis_end)

        m_core = hh.perf_metrics_slice(ep_returns["core_ret"], w_start, w_end)
        m_unhedged = hh.perf_metrics_slice(ep_returns["unhedged_blend"], w_start, w_end)
        m_collar = hh.perf_metrics_slice(ep_returns["collar_hedged_blend"], w_start, w_end)

        out[label] = {
            "window_used": [w_start, w_end], "wkey": wkey,
            "core_alone": {"sharpe": m_core["sharpe"], "cagr": m_core["cagr"], "mdd": m_core["mdd"]},
            "unhedged_satellite": {"sharpe": m_unhedged["sharpe"], "cagr": m_unhedged["cagr"], "mdd": m_unhedged["mdd"]},
            "collar_full_system": {"sharpe": m_collar["sharpe"], "cagr": m_collar["cagr"], "mdd": m_collar["mdd"]},
        }
        log(f"  {label}: core={m_core['sharpe']:.2f} unhedged={m_unhedged['sharpe']:.2f} collar={m_collar['sharpe']:.2f}")
    return out


def expected_value_table(lookup: dict, weights: dict) -> dict:
    w = normalize(weights)
    ev = {cfg: {"sharpe": 0.0, "cagr": 0.0} for cfg in CONFIGS}
    for ep, wt in w.items():
        for cfg in CONFIGS:
            m = lookup[ep][cfg]
            ev[cfg]["sharpe"] += wt * m["sharpe"]
            ev[cfg]["cagr"] += wt * m["cagr"]
    for cfg in CONFIGS:
        crisis_mdds = [lookup[ep][cfg]["mdd"] for ep in w if ep != "full_2019_2026"]
        ev[cfg]["mdd_worst_case"] = min(crisis_mdds) if crisis_mdds else None
    return ev


def rank(ev: dict, metric: str = "sharpe") -> list:
    return sorted([(cfg, v[metric]) for cfg, v in ev.items()], key=lambda x: -x[1])


def main():
    lookup = gather_per_episode_metrics()

    ev_by_scenario = {}
    rank_by_scenario = {}
    for scen, weights in BASE_RATES.items():
        ev = expected_value_table(lookup, weights)
        ev_by_scenario[scen] = ev
        rank_by_scenario[scen] = {
            "by_sharpe": rank(ev, "sharpe"),
            "by_cagr": rank(ev, "cagr"),
        }
        log(f"  scenario={scen}: EV_sharpe core={ev['core_alone']['sharpe']:.3f} "
            f"unhedged={ev['unhedged_satellite']['sharpe']:.3f} collar={ev['collar_full_system']['sharpe']:.3f} "
            f"| EV_cagr core={ev['core_alone']['cagr']*100:.2f}% unhedged={ev['unhedged_satellite']['cagr']*100:.2f}% "
            f"collar={ev['collar_full_system']['cagr']*100:.2f}%")

    out = {
        "meta": {"episode_order": EPISODE_ORDER, "configs": CONFIGS, "base_rate_scenarios": BASE_RATES,
                 "satellite_weight": hh.SATELLITE_WEIGHT},
        "per_episode_metrics": lookup,
        "expected_value_by_scenario": ev_by_scenario,
        "rank_by_scenario": rank_by_scenario,
    }
    (OUT_DIR / "h_combined_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log("저장 완료: h_combined_results.json")


if __name__ == "__main__":
    main()
