"""검증 연구 intl-check-v1 (2026-10-23 사전 등록): 미국에서 통한 '어디에 넣나'(가치·소형 가치)와 '시장 + 필터 달린 2배 다리'가 미국 밖에서도 통하나.

미국 한 나라, 그것도 지난 100년 가장 잘된 시장의 결과만으로는 '끝없이 운영'의 근거가 되기 어렵다. Ken French 지역별 일별 자료(1990-07~)로 다섯 지역 —
유럽, 일본, 아시아태평양(일본 제외), 북미(미국 + 캐나다), 선진국(미국 제외) — 에서 같은 규칙을 팔지 않는 월 10만 원 적립으로 돌려 본다.
(지역별 산업 포트폴리오는 공개되어 있지 않아 산업 고르기 규칙 DD12·MA200·REV36 은 해외에서 검증할 수 없다 — 이 한계를 보고서에 적는다.)
규칙: BV(그 지역 대형 가치주 BIG HiBM), SV(소형 가치주 SMALL HiBM), L15F(그 지역 시장 85% + 필터 달린 합성 2배 15%, lev-base-v1 와 같은 식·band200).
기준: 그 지역 시장(Mkt-RF + RF). 구간: 매달 시작하는 10년(모든 구간)·20년(가능하면). 청산 세후 IRR, 환율 1,300 원 고정(지역 통화 효과는 제외 — 주의 참조).
셀 통과(지역, 길이) ⇔ 이긴 구간 비율 ≥ 50% 이고 IRR 차이 중앙값 > 0. 규칙이 ROBUST_ABROAD ⇔ 10년 칸에서 다섯 지역 중 4곳 이상 통과 이고
20년 칸(구간이 있는 지역만)에서도 과반 통과. 엔진은 바뀌지 않는다.
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

JOB_ID = "intl-check-v1"
RULES_VERSION = "intl-check-v1/2026-10-23"
MONTHLY_KRW = 100_000
ARMS = ("BV", "SV", "L15F")
LABELS = {"BV": "대형 가치주", "SV": "소형 가치주", "L15F": "시장 85% + 필터 달린 합성 2배 15%"}
REGIONS = {"Europe": "유럽", "Japan": "일본", "Asia_Pacific_ex_Japan": "아시아태평양(일본 제외)", "North_America": "북미", "Developed_ex_US": "선진국(미국 제외)"}
REPORT_REGIONS = {"Developed": "선진국 전체(보고만)"}
HORIZONS = (10, 20)
CELL_WIN_MIN = 0.50
MIN_REGIONS_10Y = 4
SEED = 1


def load_region(key: str) -> dict:
    from core import french_factors as ff

    k3, k25 = f"intl_{key}_3", f"intl_{key}_25"
    ff.DATASETS.setdefault(k3, f"{key}_3_Factors_Daily_CSV.zip")
    ff.DATASETS.setdefault(k25, f"{key}_25_Portfolios_ME_BE-ME_Daily_CSV.zip")
    f3, p25 = ff.load(k3), ff.load(k25)
    if f3 is None or p25 is None or "BIG HiBM" not in p25 or "SMALL HiBM" not in p25:
        raise RuntimeError(f"Ken French {key} 자료를 받지 못함")
    idx = f3.index.intersection(p25.index).sort_values()
    return {"mkt": (f3["Mkt-RF"] + f3["RF"]).reindex(idx), "rf": f3["RF"].reindex(idx),
            "bv": p25["BIG HiBM"].reindex(idx), "sv": p25["SMALL HiBM"].reindex(idx)}


def synthetic_region(seed: int) -> dict:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("1990-07-02", "2026-08-31")
    m = rng.normal(0.0003, 0.011, len(idx))
    return {"mkt": pd.Series(m, index=idx), "rf": pd.Series(0.0001, index=idx),
            "bv": pd.Series(m * 1.0 + rng.normal(0.00005, 0.004, len(idx)), index=idx),
            "sv": pd.Series(m * 1.1 + rng.normal(0.0001, 0.006, len(idx)), index=idx)}


def eval_region(R, d: dict) -> dict:
    days = d["mkt"].dropna().index
    mkt = d["mkt"].reindex(days)
    rf = d["rf"].reindex(days).fillna(0.0)
    leg = L.leg_returns(mkt, rf)
    px = np.column_stack([L.level(mkt).to_numpy(), L.level(d["bv"].reindex(days)).to_numpy(), L.level(d["sv"].reindex(days)).to_numpy(),
                          L.level(leg).to_numpy()])
    cg = np.cumprod(1 + rf.to_numpy() * (1 - L.INTEREST_TAX))
    wfn = {"BV": lambda r: [(1, 1.0)], "SV": lambda r: [(2, 1.0)], "L15F": lambda r: [(0, 0.85), (3, 0.15)]}
    out = {"first": str(days[0].date()), "last": str(days[-1].date()), "cagr_market": float(np.prod(1 + mkt.fillna(0.0)) ** (252.0 / len(days)) - 1)}
    for hz in HORIZONS:
        h = 3 if R.smoke else hz
        wins = L.re_.rolling_windows(days, h, step=72 if R.smoke else "M", first_start=days[0])
        res = {a: [] for a in ARMS}
        for s, e in wins:
            base = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r: [(0, 1.0)])
            for a in ARMS:
                res[a].append(L.pair_summary(L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, wfn[a]), base))
        out[f"{hz}y"] = {a: (L.kpi_pairs_verdict(res[a], 0.0, -1.0, -1.0) if res[a] else {"n": 0}) for a in ARMS}
        out[f"{hz}y"]["_n_windows"] = len(wins)
    return out


def body(R):
    regions = {**REGIONS, **REPORT_REGIONS}
    cells = {}
    for i, key in enumerate(regions):
        def f(key=key, i=i):
            d = synthetic_region(100 + i) if R.smoke else load_region(key)
            return eval_region(R, d)
        cells[key] = R.stage("region_" + key, f)

    def cell_pass(c) -> "bool|None":
        if not c.get("n"):
            return None
        return bool(c["share_win"] >= CELL_WIN_MIN and c["median_diff_irr"] > 0)

    verdicts, detail = {}, {}
    for a in ARMS:
        p10 = {k: cell_pass(cells[k]["10y"][a]) for k in REGIONS}
        p20 = {k: cell_pass(cells[k]["20y"][a]) for k in REGIONS}
        n10 = sum(v is True for v in p10.values())
        have20 = [v for v in p20.values() if v is not None]
        ok20 = (sum(v is True for v in have20) * 2 > len(have20)) if have20 else False
        ok = n10 >= MIN_REGIONS_10Y and ok20
        detail[a] = {"pass_10y": p10, "pass_20y": p20, "n_pass_10y": n10, "n_20y_regions": len(have20)}
        verdicts[a] = f"SMOKE_ONLY({'ROBUST_ABROAD' if ok else 'FAIL'})" if R.smoke else ("ROBUST_ABROAD" if ok else "FAIL")
    verdicts["robust_abroad"] = f"{sum('ROBUST' in v for v in verdicts.values())}/{len(ARMS)}"
    result = L.rnd({"judge_version": RULES_VERSION, "smoke": R.smoke, "verdicts": verdicts, "regions": cells, "detail": detail,
                    "rule": {"monthly_krw": MONTHLY_KRW, "regions": regions, "labels": LABELS, "cell_win_min": CELL_WIN_MIN,
                             "min_regions_10y": MIN_REGIONS_10Y}})
    if R.smoke:
        assert all(cells[k]["10y"]["BV"].get("n", 0) > 0 for k in REGIONS), "빈 칸"
    return result, render(result)


def render(r: dict) -> str:
    P, v = L.pct, r["verdicts"]
    regions = r["rule"]["regions"]
    out = [f"# 미국 밖에서도 통하나 — 가치·레버리지 섞기 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "Ken French 지역별 일별 자료(1990-07~)로 유럽·일본·아시아태평양·북미·선진국(미국 제외)에서, 팔지 않는 월 10만 원 적립으로 가치주·소형 가치주·'시장 + 필터 달린 2배 다리'가 "
           "그 지역 시장보다 세후로 많이 남기는지 본다.", "",
           f"**미국 밖에서도 견고(ROBUST_ABROAD) {v['robust_abroad']}** — " + " · ".join(f"{LABELS[a]} **{v[a]}**" for a in ARMS), "",
           "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", "",
           "- 지역별 산업 포트폴리오가 없어 산업 고르기 규칙(DD12·MA200·REV36)은 해외에서 검증할 수 없다. 여기서는 가치·소형 가치·레버리지 섞기만 본다.",
           "- 규칙: BV = 그 지역 대형 가치주(BIG HiBM), SV = 소형 가치주(SMALL HiBM), L15F = 그 지역 시장 85% + 합성 2배 다리 15%(band200 필터). 기준은 그 지역 시장.",
           f"- 칸 통과 ⇔ 시장보다 많이 남은 구간 ≥ {r['rule']['cell_win_min']:.0%} 이고 세후 IRR 차이 중앙값 > 0. ROBUST_ABROAD ⇔ 10년 칸에서 다섯 지역 중 {r['rule']['min_regions_10y']}곳 이상 통과 + 20년 칸(구간이 있는 지역)에서 과반 통과.",
           "- 팔지 않는 월 10만 원, 청산 양도세 22%(250만 원 공제), 환율 1,300 원 고정(지역 통화 효과는 제외).", ""]
    for hz in HORIZONS:
        out += [f"## {hz}년 구간 — 지역별", "", "| 지역 | 규칙 | 구간 수 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 칸 통과 |", "|---|---|---|---|---|---|"]
        for k, name in regions.items():
            c = r["regions"][k]
            for a in ARMS:
                s = c[f"{hz}y"][a]
                if not s.get("n"):
                    out.append(f"| {name} | {LABELS[a]} | 0 | — | — | — |")
                    continue
                ok = r["detail"][a][f"pass_{hz}y"].get(k) if k in r["detail"][a][f"pass_{hz}y"] else None
                out.append(f"| {name} | {LABELS[a]} | {s['n']} | {P(s['share_win'], nd=0)} | {P(s['median_diff_irr'], True, 2)}p / {P(s['p10_diff_irr'], True, 2)}p | "
                           f"{'예' if ok else ('—' if ok is None else '아니오')} |")
        out.append("")
    out += ["## 지역 시장 연 수익 (참고)", "", "| 지역 | 자료 | 시장 연 수익 |", "|---|---|---|"]
    for k, name in regions.items():
        c = r["regions"][k]
        out.append(f"| {name} | {c['first']} ~ {c['last']} | {P(c['cagr_market'], nd=1)} |")
    out += ["", "## 주의", "",
            "- 1990-07~ 약 36년뿐이라 20년 구간은 겹침이 크고 표본이 매우 적다. 일본은 1990 년 거품 정점에서 시작해 장기 부진 구간이 길다 — 가치 효과는 크게 나올 수 있다.",
            "- 환율 1,300 원 고정으로 지역 통화(엔·유로) 변동은 제외했다. 실제 투자는 환 위험과 해외 ETF 접근성·비용이 다르다. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
