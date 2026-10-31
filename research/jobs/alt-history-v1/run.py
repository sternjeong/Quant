"""검증 연구 alt-history-v1 (2026-10-23 사전 등록): 살아남은 '어디에 넣나' 규칙이 실제로 겪지 않은 가상 역사에서도 시장을 이기나.

지금까지 모든 결과는 '실제로 일어난 단 하나의 역사'를 매달 시작점만 바꿔 본 것이라, 겹치지 않는 20년이 반쪽마다 2개 남짓이다. 여기서는 1927~2024 일별 수익
(시장·12 산업·RF)을 2년 덩어리째 이어 붙여(모든 자산이 같은 날짜 덩어리를 쓴다 — 자산 간 관계 보존) 20·30년짜리 가상 역사를 1,000개씩 만들고,
각 역사에서 월 10만 원을 팔지 않고 넣었을 때 규칙이 시장 전체보다 세후로 많이 남는지 본다. 한 가상 역사 = 한 번의 시행이라 독립 표본이 1,000개다
(단, 모두 같은 98년에서 뽑았으므로 그 98년에 없던 일은 없다).
규칙(모두 팔지 않는 적립): EW12(12 산업 똑같이), UW12(가장 모자란 산업), DD12(1년 고점 대비 가장 많이 빠진 산업), MA200(200일선 대비 가장 아래 산업),
REV36(3년 수익 가장 낮은 산업), L15F(시장 85 + 필터 달린 합성 2배 다리 15). 기준 = 시장 100%.
판정(규칙마다): 20년·30년(전체 역사에서 뽑음) 모두 ① 시장보다 많이 남은 역사 ≥ 65% ② 세후 IRR 차이 중앙값 ≥ +0.3%p ③ 10분위 ≥ −1.5%p 이면 ROBUST_TO_ALT_HISTORY.
보고만: 1990~2024 만에서 뽑은 20년 가상 역사, 시장 자체가 나쁜 역사(시장 IRR 하위 10%)에서의 결과. 엔진은 바뀌지 않는다.
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

V1 = L._load_mod("_dca_asset_pick_v1", "research/jobs/dca-asset-pick-v1/run.py")

JOB_ID = "alt-history-v1"
RULES_VERSION = "alt-history-v1/2026-10-23"
MONTHLY_KRW = 100_000
ARMS = ("EW12", "UW12", "DD12", "MA200", "REV36", "L15F")
LABELS = {"EW12": "12 산업 똑같이", "UW12": "가장 모자란 산업", "DD12": "1년 고점 대비 가장 많이 빠진 산업",
          "MA200": "200일선 대비 가장 아래 산업", "REV36": "3년 수익 가장 낮은 산업", "L15F": "시장 85% + 필터 달린 합성 2배 15%"}
N_PATHS, N_PATHS_SMOKE = 1000, 24
BLOCK = 504
HORIZONS = (20, 30)
SOURCES = {"ALL": ("1926-07-01", None), "POST1990": ("1990-01-01", None)}
JUDGED = (("ALL", 20), ("ALL", 30))
REPORT_ONLY = (("POST1990", 20),)
WIN_SHARE_MIN, MEDIAN_IRR_MIN, P10_IRR_MIN = 0.65, 0.003, -0.015
SEED = 20261023
L15_W, L15_MODE = 0.15, "band200"
N_IND = 12


def make_weights_fns(arm: str, scores: dict, px: np.ndarray):
    """한 가상 역사에서 한 적립 행 → [(열, 비중)]. 열: 0 시장, 1..12 산업, 13 레버리지 다리. UW12 는 보유 단위를 기억한다."""
    if arm == "EW12":
        return lambda r: [(1 + j, 1.0 / N_IND) for j in range(N_IND)]
    if arm == "L15F":
        return lambda r: [(0, 1 - L15_W), (13, L15_W)]
    if arm == "UW12":
        units = np.zeros(N_IND)
        # 1 달러 단위로 센다(비중만 필요)

        def f(r):
            p = px[r, 1:1 + N_IND]
            val = np.where(np.isfinite(p), units * p, np.inf)
            j = int(np.argmin(val))
            units[j] += 1.0 / p[j]
            return [(1 + j, 1.0)]
        return f
    key = {"DD12": "DD12", "MA200": "MA200", "REV36": "REV36"}[arm]

    def g(r):
        j = V1.pick(scores[key][r])
        return [(0, 1.0)] if j < 0 else [(1 + j, 1.0)]
    return g


def one_path(src: dict, idx: np.ndarray, n_days: int) -> dict:
    cal = L.bdates(n_days)
    mkt = pd.Series(src["mkt"][idx], index=cal)
    rf = pd.Series(src["rf"][idx], index=cal)
    ind = pd.DataFrame(src["ind"][idx], index=cal)
    ind_px = ind.apply(L.level)
    leg = L.leg_returns(mkt, rf, mode=L15_MODE)
    panel = np.column_stack([L.level(mkt).to_numpy(), ind_px.to_numpy(), L.level(leg).to_numpy()])
    cg = np.cumprod(1 + rf.to_numpy() * (1 - L.INTEREST_TAX))
    scores = V1.score_tables(ind_px)
    s, e = cal[0], cal[-1]
    base = L.weighted_window(panel, cg, cal, s, e, MONTHLY_KRW, lambda r: [(0, 1.0)])
    out = {"market_irr": base["irr"]}
    for arm in ARMS:
        a = L.weighted_window(panel, cg, cal, s, e, MONTHLY_KRW, make_weights_fns(arm, scores, panel))
        out[arm] = L.pair_summary(a, base)
    return out


def source_arrays(data: dict, first: str) -> dict:
    days = data["mkt"].dropna().index
    sel = days >= pd.Timestamp(first)
    d = days[sel]
    return {"mkt": data["mkt"].reindex(d).fillna(0.0).to_numpy(), "rf": data["rf"].reindex(d).fillna(0.0).to_numpy(),
            "ind": data["ind12"].reindex(d).fillna(0.0).to_numpy(), "n": len(d)}


def eval_source(R, data, srcname, hz) -> dict:
    src = source_arrays(data, SOURCES[srcname][0])
    n_days = int(round(hz * 252))
    n_paths = N_PATHS_SMOKE if R.smoke else N_PATHS
    paths = L.block_paths(src["n"], n_days, BLOCK if not R.smoke else 126, n_paths, SEED + hz)
    rows = []
    for k in range(n_paths):
        rows.append(one_path(src, paths[k], n_days))
        if k % 50 == 0:
            R.check_time()
    res = {}
    mk = np.array([r["market_irr"] for r in rows], dtype=float)
    bad = mk <= np.nanpercentile(mk, 10)
    for arm in ARMS:
        pr = [{"diff_irr": r[arm]["diff_irr"], "win": r[arm]["win"]} for r in rows]
        v = L.kpi_pairs_verdict(pr, WIN_SHARE_MIN, MEDIAN_IRR_MIN, P10_IRR_MIN)
        bp = [p for p, b in zip(pr, bad) if b]
        v["bad_market_10pct"] = {"n": len(bp), "share_win": float(np.mean([p["win"] for p in bp])) if bp else None,
                                 "median_diff_irr": float(np.nanmedian([p["diff_irr"] for p in bp])) if bp else None}
        v["median_mdd_gap"] = float(np.nanmedian([r[arm]["mdd_gap"] for r in rows]))
        res[arm] = v
    res["_market"] = {"median_irr": float(np.nanmedian(mk)), "p10_irr": float(np.nanpercentile(mk, 10)), "p90_irr": float(np.nanpercentile(mk, 90))}
    return res


def body(R):
    data = R.stage("inputs", lambda: L.load_long_synthetic() if R.smoke else L.load_long_real())
    cells = {}
    for srcname, hz in JUDGED + REPORT_ONLY:
        name = f"{srcname}|{hz}y"
        cells[name] = R.stage("cell_" + name.replace("|", "_"), lambda s=srcname, h=hz: eval_source(R, data, s, h))
    verdicts = {}
    for arm in ARMS:
        ok = all(cells[f"{s}|{h}y"][arm]["pass"] is True for s, h in JUDGED)
        verdicts[arm] = f"SMOKE_ONLY({'ROBUST_TO_ALT_HISTORY' if ok else 'FAIL'})" if R.smoke else ("ROBUST_TO_ALT_HISTORY" if ok else "FAIL")
    verdicts["passed"] = f"{sum('ROBUST' in v for v in verdicts.values())}/{len(ARMS)}"
    result = L.rnd({"judge_version": RULES_VERSION, "smoke": R.smoke, "source": data.get("source"), "verdicts": verdicts, "cells": cells,
                    "rule": {"monthly_krw": MONTHLY_KRW, "n_paths": N_PATHS, "block_days": BLOCK, "horizons": HORIZONS, "judged": JUDGED,
                             "report_only": REPORT_ONLY, "thresholds": {"win_share_min": WIN_SHARE_MIN, "median_irr_min": MEDIAN_IRR_MIN, "p10_irr_min": P10_IRR_MIN},
                             "labels": LABELS}})
    if R.smoke:
        assert all(cells[f"{s}|{h}y"][a]["n"] > 0 for s, h in JUDGED for a in ARMS), "빈 칸"
        assert len({round(cells["ALL|20y"][a]["median_diff_irr"], 8) for a in ARMS}) > 2, "규칙이 서로 같은 결과"
    return result, render(result)


def render(r: dict) -> str:
    v, P = r["verdicts"], L.pct
    out = [f"# 가상 역사 2,000개 검증 — 팔지 않는 적립 규칙 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "실제로 일어난 단 하나의 역사 대신, 1927~2024 일별 수익을 2년 덩어리째 이어 붙여 만든 가상 역사 1,000개(20년·30년)에서 월 10만 원을 팔지 않고 넣었을 때 "
           "규칙이 시장 전체보다 세후로 많이 남기는지 본다. 한 가상 역사가 한 번의 독립 시행이다.", "",
           f"**판정: 가상 역사에서도 견고 {v['passed']}** — " + " · ".join(f"{r['rule']['labels'][a]} **{v[a]}**" for a in ARMS), "",
           "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", "",
           f"- 가상 역사: 시장·12 산업·RF 일별 수익을 같은 날짜 덩어리(2년 = {BLOCK}거래일, 원형)로 이어 붙임. 20년·30년 각 {N_PATHS}개. 한 덩어리 안의 자산 간 관계는 보존, 덩어리 사이는 끊김.",
           "- 계좌·세금: 팔지 않는 월 10만 원, 끝에 모두 판다고 보고 양도세 22%(250만 원 공제), 수수료 0.1% + 환전 0.05%, 환율 1,300 원 고정.",
           f"- 통과(ROBUST_TO_ALT_HISTORY): 전체 역사에서 뽑은 20년·30년 모두 ① 시장보다 많이 남은 역사 ≥ {WIN_SHARE_MIN:.0%} ② 세후 IRR 차이 중앙값 ≥ +{MEDIAN_IRR_MIN * 100:.1f}%p "
           f"③ 10분위 ≥ {P10_IRR_MIN * 100:.1f}%p.", ""]
    for name, c in r["cells"].items():
        mk = c["_market"]
        out += [f"## {name}{' (보고만)' if name in [f'{s}|{h}y' for s, h in REPORT_ONLY] else ''} — 시장 세후 IRR 중앙값 {P(mk['median_irr'], nd=2)} (10분위 {P(mk['p10_irr'], nd=2)} ~ 90분위 {P(mk['p90_irr'], nd=2)})", "",
                "| 규칙 | 역사 수 | 이긴 비율 | IRR 차이 중앙값 / 10분위 / 최악 | 시장이 나쁜 10% 역사에서 이긴 비율 / 차이 중앙값 | 계좌 낙폭 차이(중앙) | 통과 |", "|---|---|---|---|---|---|---|"]
        for a in ARMS:
            s = c[a]
            b = s.get("bad_market_10pct", {})
            out.append(f"| {r['rule']['labels'][a]} | {s['n']} | {P(s['share_win'], nd=0)} | {P(s['median_diff_irr'], True, 2)}p / {P(s['p10_diff_irr'], True, 2)}p / "
                       f"{P(s['min_diff_irr'], True, 1)}p | {P(b.get('share_win'), nd=0)} / {P(b.get('median_diff_irr'), True, 2)}p | {P(s['median_mdd_gap'], True)} | "
                       f"{'예' if s['pass'] else '아니오'} |")
        out.append("")
    out += ["## 주의", "",
            "- 가상 역사는 실제 98년의 조각이라 그 98년에 없던 일(예: 지금과 전혀 다른 금리 체제)은 없다. 덩어리 사이가 끊겨 장기 추세(모멘텀·평균회귀)가 약해질 수 있다.",
            "- 합성 2배 다리는 식으로 만든 것이며 실제 상품이 아니다. 12 산업은 Ken French 학술 포트폴리오다. 세금은 근사이며 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
