"""H18 - 위기 표본 확장 검증 (n=2 -> n=5).

배경(작업36/H16-H17): Case A(정적보유, 순수익률 최대화) vs Case B(실시간청산+SPY스위치, 위기방어)
이분법은 딱 2개 위기 표본(2008 GFC, 2022 약세장)에만 근거한다. 이 스크립트는 3개 위기 에피소드를
추가한다: COVID 급락(2020-02-19~2020-04-30), 2018년말 셀오프(2018-09-01~2019-01-15),
2015-2016 조정(2015-08-01~2016-02-15).

2008/2022는 작업36(H16)이 이미 계산해 저장한 h16_results.json을 그대로 재사용한다(재계산 불필요 -
동일 정책·동일 데이터). 나머지 3개 에피소드는 이 스크립트가 새로 계산한다:
  - 코어: 17자산 챔피언(champion_strategy.run_champion) 그대로 사용 - XLC(2018-06 상장)·
    XLRE(2015-10 상장)처럼 그 시점에 아직 상장 전인 자산은 모멘텀이 NaN이라 후보에서 자동
    제외되므로(champion_strategy.build_champion_weights의 `mom[mom > 0]`), 별도 처리 없이도
    "그 시점에 실제로 존재했던 자산만" 자연스럽게 쓰인다 - 이건 2008 GFC와는 다른 상황이다:
    2008년엔 애초에 상장된 자산 자체가 너무 적어(HYG 2007-04, DBC 2006-02 상장이라 전체
    17자산 중 상당수가 없음) 작업22/23/H11이 SPY/TLT/GLD 3자산 근사로 대체하는 확립된 관례를
    썼고, 이 라운드는 그 관례를 그대로 유지(재계산 없이 h16 결과 재사용)한다. 반면 2015-16년과
    2018년엔 11개 GICS 섹터 중 9개(XLC/XLRE 제외)+TLT/IEF/GLD/EFA/HYG/DBC 총 15자산이 이미
    다 상장돼 있어 챔피언 코어를 정상적으로 쓸 수 있다.
  - 새틀라이트: H10 방식(point-in-time 40종목 풀, 돈치안20+15%트레일링스탑 신호 활성 종목 중
    모멘텀 상위3, 반기 리밸런싱) 그대로 재사용, 정적보유판과 H16 실시간청산판 둘 다 계산.
  - SPY 200일선 스위치: H12 방식 그대로 재사용.
  - core-alone / Case A(core+정적새틀라이트) / Case B(core+실시간청산새틀라이트+SPY스위치)
    3구성을 "전체기간(각 에피소드의 lookback 포함 풀 구간)"과 "위기 서브윈도우"에서 비교.
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

import pandas as pd

from champion_strategy import run_champion, compute_portfolio_returns, _closes_from_histories, CHAMPION_UNIVERSE
from h1_core_satellite import semiannual_rebal_dates, blend_returns
from h11_crisis_robustness_test import (
    build_satellite_returns_period, SATELLITE_TOP_K, SATELLITE_COST_BPS_PER_SIDE,
)
from h12_regime_switch import fetch_spy_regime_signal, build_regime_switched_weight_series, blend_returns_time_varying, SATELLITE_WEIGHT_ON
from h16_realtime_trailing_stop_exit import build_realtime_exit_weights, perf_metrics_slice
from core.backtest_engine import calculate_metrics

OUT_DIR = Path(__file__).resolve().parent
H16_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_satellite_realtime_stop_and_reentry_research"

SATELLITE_WEIGHT = 0.15

# 새로 계산할 3개 에피소드: (label, full_period_start, full_period_end, crisis_start, crisis_end)
NEW_EPISODES = {
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
}


def log(msg):
    print(f"[h18] {msg}", flush=True)


def run_episode(label: str, full_start: str, full_end: str, crisis_start: str, crisis_end: str) -> dict:
    t0 = time.time()
    log(f"=== {label}: 코어(17자산 챔피언) 구축 {full_start}~{full_end} ===")
    core = run_champion(full_start, full_end)
    trading_index = core["ret_net"].index
    log(f"  코어 지표(전체): {core['metrics']}")

    log(f"  새틀라이트(정적보유, point-in-time) 구축 중...")
    sat = build_satellite_returns_period(full_start, full_end, trading_index, exclude=set(CHAMPION_UNIVERSE), method="trend_following")
    log(f"  새틀라이트 지표(전체, 정적보유): {sat['metrics']}, 반기 리밸런싱 {len(sat['rebal_log'])}회")

    log(f"  새틀라이트 실시간청산 재구축 중...")
    rt = build_realtime_exit_weights(sat["rebal_log"], full_start, full_end, trading_index, top_k=SATELLITE_TOP_K)
    n_exits = sum(1 for e in rt["exit_events"] if e["exited_early"])
    log(f"  실시간청산 지표(전체): {rt['metrics']}, 조기청산 {n_exits}/{len(rt['exit_events'])}")

    static_blend = blend_returns(core["ret_net"], sat["ret_net"], SATELLITE_WEIGHT)
    rt_blend = blend_returns(core["ret_net"], rt["ret_net"], SATELLITE_WEIGHT)

    regime_raw = fetch_spy_regime_signal(full_start, full_end)
    weight_series = build_regime_switched_weight_series(trading_index, regime_raw, SATELLITE_WEIGHT_ON)
    rt_switch_blend = blend_returns_time_varying(core["ret_net"], rt["ret_net"], weight_series)

    windows = {"full_period": (full_start, full_end), "crisis_window": (crisis_start, crisis_end)}
    table = {}
    for wname, (ws, we) in windows.items():
        table[wname] = {
            "core_alone": perf_metrics_slice(core["ret_net"], ws, we),
            "case_a_static_satellite": perf_metrics_slice(static_blend, ws, we),
            "case_b_realtime_exit_plus_switch": perf_metrics_slice(rt_switch_blend, ws, we),
        }

    result = {
        "label": label, "full_period": [full_start, full_end], "crisis_window": [crisis_start, crisis_end],
        "core_universe_used": sorted(core["closes"].columns.tolist()),
        "n_early_exits": n_exits, "n_slots": len(rt["exit_events"]),
        "satellite_rebal_log": sat["rebal_log"],
        "windows": table,
        "elapsed_s": round(time.time() - t0, 1),
    }
    log(f"  {label} 완료 ({result['elapsed_s']}s)")
    return result


def load_2008_2022_from_h16() -> dict:
    """작업36(H16)이 이미 계산해 저장한 2008/2022 결과를 재계산 없이 그대로 재사용."""
    h16 = json.loads((H16_DIR / "h16_results.json").read_text(encoding="utf-8"))

    def remap(win: dict) -> dict:
        return {
            "core_alone": win["core_alone"],
            "case_a_static_satellite": win["core_plus_static_satellite"],
            "case_b_realtime_exit_plus_switch": win["core_plus_realtime_exit_satellite_plus_spy_switch"],
        }

    bear2022 = {
        "label": "bear_2022", "full_period": ["2019-08-12", "2026-08-19"], "crisis_window": ["2022-01-01", "2022-12-31"],
        "core_universe_used": None,  # 17자산 챔피언, champion_strategy.CHAMPION_UNIVERSE
        "n_early_exits": h16["full_and_2022"]["n_early_exits"], "n_slots": h16["full_and_2022"]["n_slots"],
        "windows": {
            "full_period": remap(h16["full_and_2022"]["windows"]["full_2019_2026"]),
            "crisis_window": remap(h16["full_and_2022"]["windows"]["bear_2022"]),
        },
        "note": "작업36(H16) 결과 재사용, 재계산 없음",
    }
    gfc2008 = {
        "label": "gfc_2008", "full_period": ["2007-01-01", "2009-12-31"], "crisis_window": ["2007-10-01", "2009-06-30"],
        "core_universe_used": ["SPY", "TLT", "GLD"],
        "n_early_exits": h16["gfc_2008"]["n_early_exits"], "n_slots": h16["gfc_2008"]["n_slots"],
        "windows": {
            "full_period": remap(h16["gfc_2008"]["windows"]["full_2007_2009"]),
            "crisis_window": remap(h16["gfc_2008"]["windows"]["crisis_2007_10_2009_06"]),
        },
        "note": "작업36(H16) 결과 재사용, 재계산 없음 (SPY/TLT/GLD 3자산 근사 코어, 작업22/23/H11 확립 관례)",
    }
    return {"bear_2022": bear2022, "gfc_2008": gfc2008}


def main():
    t0 = time.time()
    episodes = load_2008_2022_from_h16()
    log(f"2008/2022는 H16 결과 재사용 완료")

    for label, (fs, fe, cs, ce) in NEW_EPISODES.items():
        episodes[label] = run_episode(label, fs, fe, cs, ce)

    # 요약 표: 5개 에피소드 x (core_alone/CaseA/CaseB) crisis_window CAGR/MDD/Sharpe
    summary_rows = []
    order = ["gfc_2008", "correction_2015_2016", "selloff_2018", "bear_2022", "covid_2020"]
    for label in order:
        ep = episodes[label]
        cw = ep["windows"]["crisis_window"]
        row = {"episode": label, "crisis_window": ep["crisis_window"]}
        for cfg in ["core_alone", "case_a_static_satellite", "case_b_realtime_exit_plus_switch"]:
            m = cw[cfg]
            row[cfg] = {"cagr": m.get("cagr"), "mdd": m.get("mdd"), "sharpe": m.get("sharpe")}
        b_beats_a_sharpe = (row["case_b_realtime_exit_plus_switch"]["sharpe"] or -999) >= (row["case_a_static_satellite"]["sharpe"] or -999)
        b_beats_a_mdd = abs(row["case_b_realtime_exit_plus_switch"]["mdd"] or 999) <= abs(row["case_a_static_satellite"]["mdd"] or 999)
        row["case_b_beats_case_a_sharpe"] = bool(b_beats_a_sharpe)
        row["case_b_beats_case_a_mdd"] = bool(b_beats_a_mdd)
        summary_rows.append(row)

    result = {
        "meta": {"satellite_weight": SATELLITE_WEIGHT, "episode_order": order},
        "episodes": episodes,
        "summary_table_crisis_window": summary_rows,
    }
    with open(OUT_DIR / "h18_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h18_results.json'} (총 {time.time()-t0:.0f}s)")
    for row in summary_rows:
        log(f"  {row['episode']}: A_sharpe={row['case_a_static_satellite']['sharpe']} B_sharpe={row['case_b_realtime_exit_plus_switch']['sharpe']} "
            f"B>=A(sharpe)={row['case_b_beats_case_a_sharpe']} B<=A(mdd)={row['case_b_beats_case_a_mdd']}")


if __name__ == "__main__":
    main()
