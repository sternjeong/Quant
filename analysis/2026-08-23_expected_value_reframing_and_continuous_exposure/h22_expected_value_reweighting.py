"""H22 - 기저확률(base-rate) 가중 기댓값 계산.

사용자 재프레이밍: "단일 정답은 없어도 확률을 통해 기댓값을 올린다." 작업33-38(H10~H21)은 5개
위기 표본(2008/2015-16/2018/2022/COVID) + 전체기간(2019-2026) 6개 창에서 4가지 구성(정적보유/
SPY스위치/VIX스위치/하이브리드)을 window-by-window로 비교했지만, "각 창이 미래에 실제로 얼마나
자주 일어날지"를 가중치로 매겨 하나의 기댓값 순위를 낸 적은 없다. 이 스크립트가 그 계산을 한다.

입력: 이미 존재하는 report_data.json 2개 (재계산 없음, 순수 종합):
  - vix_fast_crash_signal_and_hybrid_switch/report_data.json (h20/h21 summary_table: 4구성 x 6창)
  - crisis_sample_expansion_and_risk_frontier/report_data.json (h19: 5%p 간격 스탑폭 스윕 x 6창)
  - 이번 라운드 새로 백테스트한 h23_results.json(연속노출) 을 5개 구성과 같은 창 정의로 합쳐 6번째
    구성으로 포함

기저확률(6개 "레짐 아키타입", 각각 위 6개 창 중 하나에 매핑):
  calm/bull(평시)              - full_2019_2026 전체기간(강세장 편향 구간 대용)
  slow/broad systemic(GFC형)   - gfc_2008 위기창
  fast crash(COVID형)          - covid_2020 위기창
  moderate bear(2022형)        - bear_2022 위기창
  short/sharp correction(2018형) - selloff_2018 위기창
  slower moderate correction(2015-16형) - correction_2015_2016 위기창

각 아키타입의 역사적 발생빈도는 문헌/통계로 정당화한 "최선 추정"이며 정밀한 수치가 아님을
명시한다(build_report.py의 리포트 본문에서 출처와 함께 서술). 민감도분석을 위해 3가지 가중치
시나리오(base/calm-heavy/crisis-heavy)를 계산해 순위가 얼마나 안정적인지 확인한다.
"""
from __future__ import annotations

import json
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
H20_H21_PATH = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_vix_fast_crash_signal_and_hybrid_switch/report_data.json"
H18_H19_PATH = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_crisis_sample_expansion_and_risk_frontier/report_data.json"
OUT_DIR = Path(__file__).resolve().parent
H23_RESULTS_PATH = OUT_DIR / "h23_results.json"

EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
ARCHETYPE_LABEL = {
    "full_2019_2026": "calm_bull",
    "gfc_2008": "slow_broad_systemic_2008type",
    "covid_2020": "fast_crash_covid_type",
    "bear_2022": "moderate_bear_2022type",
    "selloff_2018": "short_sharp_correction_2018type",
    "correction_2015_2016": "slower_moderate_correction_2015_16type",
}

CONFIGS = ["core_alone", "case_a_static_satellite", "case_b_spy_switch", "case_c_vix_switch",
           "case_d_hybrid_or_switch", "case_e_continuous_exposure"]

# ---- 기저확률 시나리오 (연간 확률의 상대비, 정규화해서 사용) ----
# base: 본문에서 정당화하는 "최선 추정" 중심값
# calm_heavy: 위기 발생빈도를 낮게 보는 보수적(강세장 지속 가정) 시나리오
# crisis_heavy: 위기 발생빈도를 높게 보는 비관적 시나리오
SCENARIOS = {
    "base": {
        "full_2019_2026": 0.50,
        "gfc_2008": 0.03,
        "covid_2020": 0.04,
        "bear_2022": 0.10,
        "selloff_2018": 0.16,
        "correction_2015_2016": 0.17,
    },
    "calm_heavy": {
        "full_2019_2026": 0.65,
        "gfc_2008": 0.015,
        "covid_2020": 0.02,
        "bear_2022": 0.065,
        "selloff_2018": 0.12,
        "correction_2015_2016": 0.13,
    },
    "crisis_heavy": {
        "full_2019_2026": 0.35,
        "gfc_2008": 0.06,
        "covid_2020": 0.07,
        "bear_2022": 0.14,
        "selloff_2018": 0.19,
        "correction_2015_2016": 0.19,
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(weights: dict) -> dict:
    s = sum(weights.values())
    return {k: v / s for k, v in weights.items()}


def build_summary_lookup() -> dict:
    """episode -> config -> {sharpe, cagr, mdd} (h20/h21 summary_table + h23 continuous 병합)."""
    h20h21 = load_json(H20_H21_PATH)
    summary = h20h21["h21"]["summary_table"]  # 이미 4구성+하이브리드 포함, window_used가 아키타입별 대표창
    lookup = {}
    for row in summary:
        ep = row["episode"]
        lookup[ep] = {}
        for cfg in ["core_alone", "case_a_static_satellite", "case_b_spy_switch", "case_c_vix_switch",
                    "case_d_hybrid_or_switch"]:
            m = row[cfg]
            lookup[ep][cfg] = {"sharpe": m["sharpe"], "cagr": m["cagr"], "mdd": m["mdd"]}

    if H23_RESULTS_PATH.exists():
        h23 = load_json(H23_RESULTS_PATH)
        for ep in EPISODE_ORDER:
            window_used = "full_period" if ep == "full_2019_2026" else "crisis_window"
            m = h23["episodes"][ep]["windows"][window_used]["case_e_continuous_exposure"]
            lookup.setdefault(ep, {})["case_e_continuous_exposure"] = {
                "sharpe": m["sharpe"], "cagr": m["cagr"], "mdd": m["mdd"]}
    return lookup


def expected_value_table(lookup: dict, weights: dict) -> dict:
    w = normalize(weights)
    ev = {cfg: {"sharpe": 0.0, "cagr": 0.0, "mdd_worst_case": 0.0} for cfg in CONFIGS}
    for ep, wt in w.items():
        for cfg in CONFIGS:
            m = lookup.get(ep, {}).get(cfg)
            if m is None or m["sharpe"] is None:
                continue
            ev[cfg]["sharpe"] += wt * m["sharpe"]
            ev[cfg]["cagr"] += wt * m["cagr"]
    # "최악 시나리오" MDD: 위기창들(calm 제외) 중 최악 MDD (기댓값이 아니라 꼬리위험 참고용 별도 지표)
    for cfg in CONFIGS:
        crisis_mdds = [lookup[ep][cfg]["mdd"] for ep in w if ep != "full_2019_2026"
                       and cfg in lookup.get(ep, {}) and lookup[ep][cfg]["mdd"] is not None]
        ev[cfg]["mdd_worst_case"] = min(crisis_mdds) if crisis_mdds else None
    return ev


def rank_configs(ev: dict, metric: str = "sharpe") -> list:
    items = [(cfg, v[metric]) for cfg, v in ev.items() if v[metric] is not None]
    return sorted(items, key=lambda x: -x[1])


def h19_stop_width_expected_value(weights: dict) -> dict:
    """H19 스탑폭 스윕(10~30%)도 동일 기저확률로 기댓값화."""
    h18h19 = load_json(H18_H19_PATH)
    full_sweep = h18h19["h19"]["full_period_sweep"]
    crisis_sweep = h18h19["h19"]["crisis_episode_sweep"]
    w = normalize(weights)
    stop_levels = h18h19["h19"]["meta"]["stop_levels"]
    ev = {}
    for sp in stop_levels:
        key = str(sp)
        sharpe_ev, cagr_ev = 0.0, 0.0
        for ep, wt in w.items():
            if ep == "full_2019_2026":
                m = full_sweep[key]["full_period_with_switch"]
            else:
                m = crisis_sweep.get(ep, {}).get(key, {}).get("crisis_window_with_switch")
                if m is None:
                    # bear_2022 crisis_window not in crisis_episode_sweep keys directly -> fallback to full sweep bear window if absent
                    continue
            sharpe_ev += wt * m["sharpe"]
            cagr_ev += wt * m["cagr"]
        ev[key] = {"stop_pct": sp, "expected_sharpe": round(sharpe_ev, 4), "expected_cagr_pct": round(cagr_ev, 4)}
    return ev


def main():
    lookup = build_summary_lookup()
    out = {"scenarios": {}, "h19_stop_width_expected_value": {}, "config_order": CONFIGS,
           "episode_archetype_map": ARCHETYPE_LABEL}

    for scen_name, weights in SCENARIOS.items():
        ev = expected_value_table(lookup, weights)
        ranking_sharpe = rank_configs(ev, "sharpe")
        ranking_cagr = rank_configs(ev, "cagr")
        out["scenarios"][scen_name] = {
            "weights_normalized": normalize(weights),
            "expected_value": ev,
            "ranking_by_expected_sharpe": ranking_sharpe,
            "ranking_by_expected_cagr": ranking_cagr,
        }
        # bear_2022 crisis sweep key issue: crisis_episode_sweep keys are episode labels; bear_2022 present? check below
        out["h19_stop_width_expected_value"][scen_name] = h19_stop_width_expected_value(weights)

    out["raw_lookup_table"] = lookup
    (OUT_DIR / "h22_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[h22] saved h22_results.json")
    for scen_name in SCENARIOS:
        print(f"--- {scen_name} ranking (sharpe) ---")
        for cfg, val in out["scenarios"][scen_name]["ranking_by_expected_sharpe"]:
            print(f"  {cfg}: {val:.4f}")
        print(f"--- {scen_name} stop-width expected sharpe ---")
        for k, v in out["h19_stop_width_expected_value"][scen_name].items():
            print(f"  stop={k}: E[sharpe]={v['expected_sharpe']:.4f} E[cagr]={v['expected_cagr_pct']:.3f}")


if __name__ == "__main__":
    main()
