"""검증 연구 l15f-robust-v1 (2026-10-23 사전 등록): '시장 + 필터 달린 2배 다리 일부' 적립이 정말 SPY(시장)를 꾸준히 이기나.

ETF 시대(2010~)와 1927~2007 모두에서 시장을 이긴 유일한 후보가 L15F(시장 85 + 합성 2배 15, 200일선 완충 필터)다. 하지만 그 결과는
(a) 차입 비용 연 1%·보수 연 0.9% 한 가지 가정 (b) 필터 한 가지 (c) 비중 15% 한 가지에서만 나왔다. 여기서는 팔지 않는 월 적립(10만 원) 계좌에서
비중·필터·차입 비용을 흔들고, 대공황·70년대·닷컴·금융위기 시작 구간의 꼬리 위험을 같이 본다. 모든 적립금은 (1−w) 시장 + w 다리로 들어가 팔지 않는다.
판정: 비중 {10,15,20,25%} × 필터 {band200, sma210, none} = 12 칸(차입 가산 연 1%·보수 연 0.9%) 각각이 BEATS_MARKET ⇔
선택(끝 ≤ 1966)·확인(1967~2007) × 10·20년 네 칸 모두 ① 시장보다 많이 남은 구간 ≥ 65% ② 세후 IRR 차이 중앙값 ≥ +0.3%p ③ 10분위 ≥ −1.5%p
④ 계좌 최대낙폭 중앙값이 시장보다 10%p 넘게 나쁘지 않음. 차입 비용 {0.5, 2%} 와 꼬리 구간은 보고하고, 아래 TAIL_OK 가 참이어야 '견고(ROBUST)'.
엔진은 바뀌지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dca-dip-deploy-v1"))
sys.path.insert(0, str(HERE.parents[2]))
import lab as L  # noqa: E402

JOB_ID = "l15f-robust-v1"
RULES_VERSION = "l15f-robust-v1/2026-10-23"
MONTHLY_KRW = 100_000
WEIGHTS = (0.10, 0.15, 0.20, 0.25)
MODES = ("band200", "sma210", "none")
FIN_SPREADS = (0.005, 0.010, 0.020)
MAIN_FIN = 0.010
HORIZONS = (10, 20)
JUDGED_SETS = ("selection", "confirmation")
WIN_SHARE_MIN, MEDIAN_IRR_MIN, P10_IRR_MIN, MDD_TOL = 0.65, 0.003, -0.015, 0.10
TAIL_STARTS = {"1929-09": "대공황", "1937-03": "1937 불황", "1973-01": "1973 약세장", "2000-03": "닷컴", "2007-10": "금융위기"}
TAIL_HORIZON = 10
TAIL_MAX_WORSE_DD = 0.10          # 꼬리 구간에서 계좌 최대낙폭이 시장보다 10%p 넘게 나쁘지 않아야
TAIL_MIN_RATIO = 0.90             # 꼬리 구간 끝 금액이 시장의 90% 이상이어야
PASS, FAIL = "BEATS_MARKET", "FAIL"


def cell_name(w, mode, fin) -> str:
    return f"w{int(round(w * 100))}|{mode}|fin{fin * 100:.1f}"


def build_panel(data: dict, w: float, mode: str, fin: float):
    days = data["mkt"].dropna().index
    mkt = data["mkt"].reindex(days)
    rf = data["rf"].reindex(days).fillna(0.0)
    leg = L.leg_returns(mkt, rf, fin_spread=fin, mode=mode)
    px = np.column_stack([L.level(mkt).to_numpy(), L.level(leg).to_numpy()])
    return days, px


def eval_cell(data, cg, w, mode, fin, sets_by_h, tails) -> dict:
    days, px = build_panel(data, w, mode, fin)
    out = {"windows": {}, "tail": {}}
    for h, sets in sets_by_h.items():
        for sn, wins in sets.items():
            rows = []
            for s, e in wins:
                a = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r: [(0, 1 - w), (1, w)])
                b = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r: [(0, 1.0)])
                rows.append(L.pair_summary(a, b))
            v = L.kpi_pairs_verdict(rows, WIN_SHARE_MIN, MEDIAN_IRR_MIN, P10_IRR_MIN)
            if rows:
                v["median_mdd_gap"] = float(np.nanmedian([r["mdd_gap"] for r in rows]))
                v["median_ratio"] = float(np.nanmedian([r["ratio"] for r in rows]))
                v["checks"]["mdd"] = v["median_mdd_gap"] >= -MDD_TOL
                v["pass"] = all(v["checks"].values())
            out["windows"][f"{h}y|{sn}"] = v
    for tag, (s, e) in tails.items():
        a = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r: [(0, 1 - w), (1, w)])
        b = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r: [(0, 1.0)])
        p = L.pair_summary(a, b)
        p.update({"strategy_mdd": a["mdd"], "market_mdd": b["mdd"]})
        out["tail"][tag] = p
    return out


def body(R: "L.Runner"):
    data = R.stage("inputs", lambda: L.load_long_synthetic() if R.smoke else L.load_long_real())
    days = data["mkt"].dropna().index
    cg = np.cumprod(1 + data["rf"].reindex(days).fillna(0.0).to_numpy() * (1 - L.INTEREST_TAX))
    sets_by_h = {h: L.window_sets(days, h, R.smoke) for h in HORIZONS}
    tails = {}
    for ym in TAIL_STARTS:
        s = days[days >= pd.Timestamp(ym + "-01")]
        if len(s) == 0:
            continue
        s = s[0]
        tgt = s + pd.DateOffset(years=TAIL_HORIZON)
        if tgt <= days[-1]:
            tails[ym] = (s, days[days <= tgt][-1])
    if R.smoke and not tails:
        s = days[days >= pd.Timestamp("2012-01-01")][0]
        tails["2012-01"] = (s, days[days <= s + pd.DateOffset(years=3)][-1])
    cells = {}
    grid = [(w, m, MAIN_FIN) for w in WEIGHTS for m in MODES] + [(0.15, "band200", f) for f in FIN_SPREADS if f != MAIN_FIN]
    for w, m, f in grid:
        name = cell_name(w, m, f)
        cells[name] = R.stage("cell_" + name.replace("|", "_"), lambda w=w, m=m, f=f: eval_cell(data, cg, w, m, f, sets_by_h, tails))
    verdicts, tail_ok = {}, {}
    for w in WEIGHTS:
        for m in MODES:
            c = cells[cell_name(w, m, MAIN_FIN)]
            ok = all(c["windows"].get(f"{h}y|{sn}", {}).get("pass") is True for h in HORIZONS for sn in JUDGED_SETS)
            t_ok = all(t["mdd_gap"] >= -TAIL_MAX_WORSE_DD and t["ratio"] >= TAIL_MIN_RATIO for t in c["tail"].values())
            nm = cell_name(w, m, MAIN_FIN)
            tail_ok[nm] = t_ok
            v = "ROBUST" if (ok and t_ok) else (PASS + "_BUT_FRAGILE_TAIL" if ok else FAIL)
            verdicts[nm] = f"SMOKE_ONLY({v})" if R.smoke else v
    n_ok = sum("ROBUST" in v for v in verdicts.values())
    verdicts["robust_cells"] = f"{n_ok}/{len(WEIGHTS) * len(MODES)}"
    fin_note = {f"fin{f * 100:.1f}": {k: cells[cell_name(0.15, "band200", f)]["windows"].get(k, {}).get("pass") for k in cells[cell_name(0.15, "band200", f)]["windows"]}
                for f in FIN_SPREADS}
    result = L.rnd({"judge_version": RULES_VERSION, "smoke": R.smoke, "source": data.get("source"), "verdicts": verdicts, "cells": cells,
                    "tail_ok": tail_ok, "financing_sensitivity_L15_band200": fin_note, "tail_starts": TAIL_STARTS,
                    "rule": {"monthly_krw": MONTHLY_KRW, "weights": WEIGHTS, "modes": MODES, "fin_spreads": FIN_SPREADS, "main_fin": MAIN_FIN,
                             "thresholds": {"win_share_min": WIN_SHARE_MIN, "median_irr_min": MEDIAN_IRR_MIN, "p10_irr_min": P10_IRR_MIN,
                                            "mdd_tol": MDD_TOL, "tail_max_worse_dd": TAIL_MAX_WORSE_DD, "tail_min_ratio": TAIL_MIN_RATIO}}})
    if R.smoke:
        c0 = cells[cell_name(0.15, "band200", MAIN_FIN)]
        assert all(c0["windows"][f"10y|{s}"].get("n", 0) > 0 for s in JUDGED_SETS), "빈 구간"
        assert cells[cell_name(0.25, "none", MAIN_FIN)]["tail"], "꼬리 칸 없음"
        assert len({round(cells[cell_name(w, "none", MAIN_FIN)]["windows"]["10y|selection"]["median_diff_irr"], 8) for w in WEIGHTS}) > 1, "비중이 결과에 반영되지 않음"
    return result, render(result)


def render(r: dict) -> str:
    v = r["verdicts"]
    P = L.pct
    out = [f"# 필터 달린 2배 다리 일부 + 시장 — 견고성 검증 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "팔지 않는 월 10만 원 적립에서, 새 돈의 일부를 필터 달린 2배 다리에 넣는 것(L15F 계열)이 비중·필터·차입 비용을 바꿔도, 그리고 대공황·70년대·닷컴·금융위기 같은 "
           "나쁜 시작 시점에도 시장을 이기는지 1927~2024 미국 자료로 본다.", "",
           f"**견고한 칸(ROBUST): {v['robust_cells']}** (통과 + 꼬리 구간 조건). 통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", "",
           "- 새 돈은 (1−w) 시장 + w 다리로 들어가 팔지 않는다. 다리 = 합성 2배(2×수익 − (RF + 차입 가산 연 1%) − 보수 연 0.9%), 필터가 꺼지면 RF. 켜고 끄는 날 다리 × 2 × 10bp 비용.",
           "- 필터: band200 = 매달 전일 종가가 200일선 ×1.02 위면 켜고 ×0.98 아래면 끔, sma210 = 같은 방식 210일, none = 늘 켜짐.",
           f"- 판정 칸: 비중 10/15/20/25% × 필터 3개 = 12 칸. BEATS_MARKET ⇔ 선택·확인 반쪽 × 10·20년 모두 ① 시장보다 많이 남은 구간 ≥ {WIN_SHARE_MIN:.0%} "
           f"② 세후 IRR 차이 중앙값 ≥ +{MEDIAN_IRR_MIN * 100:.1f}%p ③ 10분위 ≥ {P10_IRR_MIN * 100:.1f}%p ④ 계좌 최대낙폭 중앙값이 시장보다 {MDD_TOL * 100:.0f}%p 넘게 나쁘지 않음.",
           f"- ROBUST ⇔ 통과 + 꼬리 구간 5곳({', '.join(r['tail_starts'].values())}, 시작 후 {TAIL_HORIZON}년)에서 계좌 최대낙폭이 시장보다 {TAIL_MAX_WORSE_DD * 100:.0f}%p 넘게 나쁘지 않고 "
           f"끝 금액이 시장의 {TAIL_MIN_RATIO:.0%} 이상.", "",
           "## 칸별 판정", "", "| 칸 | 판정 | 꼬리 조건 |", "|---|---|---|"]
    for k, val in v.items():
        if k != "robust_cells":
            out.append(f"| {k} | **{val}** | {'충족' if r['tail_ok'].get(k) else '미충족'} |")
    for h in HORIZONS:
        for sn in ("selection", "confirmation", "post2008"):
            out += ["", f"## {h}년 구간 — {sn}{' (보고만)' if sn == 'post2008' else ''}", "",
                    "| 칸 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 남은 돈 비율 | 계좌 낙폭 차이(중앙) |", "|---|---|---|---|---|---|"]
            for name, c in r["cells"].items():
                s = c["windows"].get(f"{h}y|{sn}", {})
                if s.get("n"):
                    out.append(f"| {name} | {s['n']} | {P(s['share_win'], nd=0)} | {P(s['median_diff_irr'], True, 2)}p / {P(s['p10_diff_irr'], True, 2)}p | "
                               f"{s['median_ratio']:.3f} | {P(s['median_mdd_gap'], True)} |")
    out += ["", f"## 꼬리 구간 (시작 후 {TAIL_HORIZON}년, 적립 포함)", "",
            "| 칸 | 시작 | 끝 금액 비율 | IRR 차이 | 계좌 최대낙폭 (시장) |", "|---|---|---|---|---|"]
    for name, c in r["cells"].items():
        for ym, t in c["tail"].items():
            out.append(f"| {name} | {ym} {r['tail_starts'].get(ym, '')} | {t['ratio']:.3f} | {P(t['diff_irr'], True, 2)}p | {P(t['strategy_mdd'])} ({P(t['market_mdd'])}) |")
    out += ["", "## 주의", "",
            "- 구간이 크게 겹친다. 합성 2배는 실제 상품(운용 보수·차입 비용·추적 오차)이 아니라 식이다. 1930년대 변동성에서는 실제로 이런 상품이 없었다.",
            "- 환율 1,300 원 고정, 배당 원천징수 미반영, 세금은 마지막에 한 번 파는 근사. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    R = L.Runner(RULES_VERSION, argv)
    return R.run(body)


if __name__ == "__main__":
    raise SystemExit(main())
