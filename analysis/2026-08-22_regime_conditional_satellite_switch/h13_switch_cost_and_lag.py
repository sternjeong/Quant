"""H13 - 국면조건부 스위치(H12)의 현실적 대가: 회전율/휘프쏘 비용 + 반응 지연.

H12가 "이론적으로" 국면 스위치가 위기 구간의 손실을 막아주는지 봤다면, H13은 그 스위치가 실전에서도
쓸만한지 두 가지를 정량화한다:

1. 회전율/휘프쏘 비용: 스위치가 2019-2026(2022 포함) + 2008 GFC 구간을 합쳐 몇 번이나 on/off를
   뒤집는지 세고, 이 저장소의 기존 관례(왕복 0.1% = 편도 5bp, champion_strategy.COST_BPS_PER_SIDE와
   동일)를 "스위치 자체의 매매"에 적용한다 - 새틀라이트 15%를 껐다 켰다 하는 것 자체가 포트폴리오의
   15%를 매매하는 것이므로, 매 전환일마다 turnover=0.15에 5bp/10000을 곱해 그날의 블렌드 수익률에서
   추가로 차감하고, 스위치 비용을 반영한 순 샤프를 H12의 비용 미반영 순 샤프와 비교한다.

2. 반응 지연: 2008 GFC 구간에서 스위치가 실제로 "OFF"로 처음 전환된 날짜를 찾고, 그 시점까지 새틀라이트
   자체의 위기 구간 최종 낙폭 중 이미 몇 %가 발생했는지 계산한다(이진 추세/모멘텀 필터는 원래
   후행지표이므로 "이미 다 떨어진 뒤에 끄는" 사후약방문일 수 있다는 우려를 직접 수치로 검증).

H12가 저장한 CSV(full2022_weight_series.csv 등)를 그대로 재사용 - 재계산 없음.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))

import numpy as np
import pandas as pd

from champion_strategy import COST_BPS_PER_SIDE
from core.backtest_engine import calculate_metrics

OUT_DIR = Path(__file__).resolve().parent
SATELLITE_WEIGHT_ON = 0.15
SWITCH_COST_BPS_PER_SIDE = COST_BPS_PER_SIDE  # 5bp, 이 저장소 기존 관례(왕복 0.1%) 재사용

GFC_CRISIS_START, GFC_CRISIS_END = "2007-10-01", "2009-06-30"


def log(msg):
    print(f"[h13] {msg}", flush=True)


def load_period(prefix: str) -> dict:
    w = pd.read_csv(OUT_DIR / f"{prefix}_weight_series.csv", index_col=0, parse_dates=True).iloc[:, 0]
    core = pd.read_csv(OUT_DIR / f"{prefix}_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat = pd.read_csv(OUT_DIR / f"{prefix}_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    return {"weight": w, "core": core, "sat": sat}


def count_flips(weight_series: pd.Series) -> dict:
    on = (weight_series > 0).astype(int)
    diff = on.diff().fillna(0)
    flip_on_dates = weight_series.index[diff == 1]
    flip_off_dates = weight_series.index[diff == -1]
    return {
        "n_flip_to_on": int((diff == 1).sum()),
        "n_flip_to_off": int((diff == -1).sum()),
        "total_flips": int((diff != 0).sum()),
        "flip_on_dates": [str(d.date()) for d in flip_on_dates],
        "flip_off_dates": [str(d.date()) for d in flip_off_dates],
    }


def blended_with_switch_cost(core: pd.Series, sat: pd.Series, weight: pd.Series) -> tuple[pd.Series, pd.Series]:
    core_a, sat_a = core.align(sat, join="inner")
    w = weight.reindex(core_a.index).fillna(0.0)
    blended_gross = (1 - w) * core_a + w * sat_a

    # 스위치 매매비용: 비중이 바뀐 날 |Δw| * (편도bp/10000)을 그날 수익률에서 차감
    dw = w.diff().abs().fillna(0.0)
    switch_cost = dw * (SWITCH_COST_BPS_PER_SIDE / 10000.0)
    blended_net_of_switch_cost = blended_gross - switch_cost
    return blended_gross, blended_net_of_switch_cost


def metrics_from_ret(ret: pd.Series) -> dict:
    eq = (1 + ret.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    return calculate_metrics(eq, [], eq.index[0], eq.index[-1])


def part1_turnover_cost() -> dict:
    log("1) 회전율/휘프쏘 비용")
    full2022 = load_period("full2022")
    gfc = load_period("gfc")

    flips_full2022 = count_flips(full2022["weight"])
    flips_gfc = count_flips(gfc["weight"])
    total_flips_combined = flips_full2022["total_flips"] + flips_gfc["total_flips"]
    log(f"  전체 2019-2026(+2022 포함) 구간 전환 횟수: {flips_full2022['total_flips']}")
    log(f"  2008 GFC(2007-2009) 구간 전환 횟수: {flips_gfc['total_flips']}")
    log(f"  합계: {total_flips_combined}회")

    gross_f, net_f = blended_with_switch_cost(full2022["core"], full2022["sat"], full2022["weight"])
    gross_g, net_g = blended_with_switch_cost(gfc["core"], gfc["sat"], gfc["weight"])

    m_gross_f, m_net_f = metrics_from_ret(gross_f), metrics_from_ret(net_f)
    m_gross_g, m_net_g = metrics_from_ret(gross_g), metrics_from_ret(net_g)

    total_switch_cost_drag_full2022_bps = float((gross_f - net_f).sum() * 10000)
    total_switch_cost_drag_gfc_bps = float((gross_g - net_g).sum() * 10000)

    log(f"  [전체2019-2026] 스위치비용 미반영 샤프={m_gross_f['sharpe']:.4f} -> 반영후={m_net_f['sharpe']:.4f} "
        f"(누적비용 {total_switch_cost_drag_full2022_bps:.2f}bp)")
    log(f"  [2008 GFC]      스위치비용 미반영 샤프={m_gross_g['sharpe']:.4f} -> 반영후={m_net_g['sharpe']:.4f} "
        f"(누적비용 {total_switch_cost_drag_gfc_bps:.2f}bp)")

    return {
        "switch_cost_bps_per_side": SWITCH_COST_BPS_PER_SIDE,
        "flips_full_2019_2026": flips_full2022,
        "flips_gfc_2007_2009": flips_gfc,
        "total_flips_combined": total_flips_combined,
        "full_2019_2026": {
            "metrics_before_switch_cost": m_gross_f,
            "metrics_after_switch_cost": m_net_f,
            "cumulative_switch_cost_drag_bps": round(total_switch_cost_drag_full2022_bps, 2),
        },
        "gfc_2007_2009": {
            "metrics_before_switch_cost": m_gross_g,
            "metrics_after_switch_cost": m_net_g,
            "cumulative_switch_cost_drag_bps": round(total_switch_cost_drag_gfc_bps, 2),
        },
    }


def part2_reaction_lag() -> dict:
    log("2) 반응 지연 (2008 GFC)")
    gfc = load_period("gfc")
    w = gfc["weight"]
    sat = gfc["sat"]

    flips = count_flips(w)
    crisis_off_dates = [d for d in flips["flip_off_dates"] if GFC_CRISIS_START <= d <= GFC_CRISIS_END]
    if not crisis_off_dates:
        # 위기구간 진입 이전에 이미 꺼져있었을 수 있음 - 위기구간 시작 시점 상태 확인
        first_off_before_crisis = [d for d in flips["flip_off_dates"] if d < GFC_CRISIS_START]
        switch_off_date = first_off_before_crisis[-1] if first_off_before_crisis else None
        note = "위기구간 진입 이전에 이미 OFF로 전환돼 있었음(선제 방어)" if switch_off_date else \
               "위기구간 내내 스위치가 한 번도 OFF로 전환되지 않음"
    else:
        switch_off_date = crisis_off_dates[0]
        note = "위기구간 진입 이후 OFF로 전환(후행)"

    log(f"  스위치 최초 OFF 전환일: {switch_off_date} ({note})")

    # 위기구간(2007-10~2009-06) 내 새틀라이트 누적 낙폭 궤적 계산
    sat_crisis = sat[(sat.index >= pd.Timestamp(GFC_CRISIS_START)) & (sat.index <= pd.Timestamp(GFC_CRISIS_END))]
    eq = (1 + sat_crisis.fillna(0.0)).cumprod()
    running_max = eq.cummax()
    drawdown = eq / running_max - 1.0
    final_mdd = float(drawdown.min())
    mdd_date = drawdown.idxmin()

    if switch_off_date is not None and pd.Timestamp(switch_off_date) in drawdown.index:
        dd_at_switch = float(drawdown.loc[pd.Timestamp(switch_off_date)])
    elif switch_off_date is not None and pd.Timestamp(switch_off_date) < drawdown.index[0]:
        dd_at_switch = 0.0  # 위기구간 시작 전에 이미 꺼져 있었으므로 낙폭 0%에서 방어
    else:
        dd_at_switch = None

    pct_of_final_mdd_already_realized = (
        round(dd_at_switch / final_mdd * 100, 1) if (dd_at_switch not in (None,) and final_mdd != 0) else None
    )

    log(f"  위기구간 새틀라이트 최종 MDD: {final_mdd*100:.2f}% (발생일 {mdd_date.date()})")
    log(f"  스위치 OFF 시점의 낙폭: {dd_at_switch*100:.2f}%" if dd_at_switch is not None else "  스위치 OFF 시점 낙폭: N/A")
    log(f"  -> 최종 낙폭 대비 이미 실현된 비율: {pct_of_final_mdd_already_realized}%")

    return {
        "switch_off_date": switch_off_date,
        "note": note,
        "satellite_crisis_final_mdd_pct": round(final_mdd * 100, 2),
        "satellite_crisis_mdd_date": str(mdd_date.date()),
        "drawdown_pct_at_switch_off_date": round(dd_at_switch * 100, 2) if dd_at_switch is not None else None,
        "pct_of_final_mdd_already_realized_at_switch_off": pct_of_final_mdd_already_realized,
        "all_flip_off_dates_in_gfc_window": flips["flip_off_dates"],
        "all_flip_on_dates_in_gfc_window": flips["flip_on_dates"],
    }


def main():
    p1 = part1_turnover_cost()
    p2 = part2_reaction_lag()
    result = {"part1_turnover_and_switch_cost": p1, "part2_reaction_lag_2008": p2}
    with open(OUT_DIR / "h13_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h13_results.json'}")


if __name__ == "__main__":
    main()
