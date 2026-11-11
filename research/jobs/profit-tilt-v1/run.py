"""검증 연구 profit-tilt-v1 (2026-11-11 사전 등록): 돈 잘 버는 회사·덜 퍼붓는 회사에 적립하면 시장을 이기나 (1963~2024).

PEAD(earnings-surprise-v1)는 무료 실적 자료로 실패했고, 가치(대형 가치주)는 edge-decay-v1 에서 2008 이후에도 살아 있었다. 학계에서
가치 다음으로 튼튼하다고 보는 '수익성(Novy-Marx 2013, FF5 RMW)'과 '보수적 투자(CMA)'는 우리 연구에서 한 번도 적립 계좌로 재지 않았다.
Ken French 일별 포트폴리오(시가총액 가중, CRSP 기반이라 생존 편향 없음)로 팔지 않는 월 10만 원 적립을 시장과 비교한다.

  BHOP = 대형 + 영업 수익성 상위 30% (6 ME×OP 의 'BIG HiOP')
  BLINV = 대형 + 자산 증가율 하위 30% (6 ME×INV 의 'BIG LoINV')
  VQ = 싸고(B/M 상위 20%) 돈 잘 버는(OP 상위 20%) 회사 (25 BEME×OP 의 'HiBM HiOP', 모든 규모 시가총액 가중)
  BVQ = 대형 가치(25 규모×BM 'BIG HiBM') 50% + BHOP 50% — 가치·수익성 섞기
  BV = 대형 가치 100% (기준 비교용, 보고)
모든 팔은 연 0.25% 운용 보수(실제 상품이 있다면 낼 비용)를 매일 뗀다. 시장은 FF3 Mkt-RF+RF(보수 없음 — SPY 0.09% 보다 유리).

구간: 10·20년, 매달 시작, 두 반쪽은 자료가 겹치지 않게 나눈다 — 앞(끝 ≤ 1994-06-30)·뒤(시작 ≥ 1994-07-01, 끝 ≤ 2024-09-30).
판정(BHOP·BLINV·VQ·BVQ 각각) TILT_BEATS_MARKET ⇔ 앞·뒤 × 10·20년 네 칸 모두 ① 시장보다 많이 남은 구간 ≥ 65% ② 세후 IRR 차이 중앙값 ≥ +0.5%p
③ 10분위 ≥ −1.5%p ④ 계좌 최대낙폭 중앙값이 시장보다 10%p 넘게 나쁘지 않음. 2008 이후 시작·2024-10 이후 끝 구간은 보고만.
네 팔을 동시에 보므로 하나라도 통과하면 '전진 원장 후보'일 뿐이다. 엔진은 바뀌지 않는다.
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

JOB_ID = "profit-tilt-v1"
RULES_VERSION = "profit-tilt-v1/2026-11-11"
MONTHLY_KRW = 100_000
TILT_FEE = 0.0025
FIRST_START = "1963-07-01"
H1_END, H2_START, H2_END = "1994-06-30", "1994-07-01", "2024-09-30"
RECENT_START = "2008-01-01"
HORIZONS = (10, 20)
WIN_SHARE_MIN, MEDIAN_IRR_MIN, P10_IRR_MIN, MDD_TOL = 0.65, 0.005, -0.015, 0.10
COLS = ["M", "BHOP", "BLINV", "VQ", "BV"]
SRC = {"BHOP": ("op6_daily", "BIG HiOP"), "BLINV": ("inv6_daily", "BIG LoINV"), "VQ": ("bmop25_daily", "HiBM HiOP"), "BV": ("ports25_daily", "BIG HiBM")}
ARMS = {"BHOP": [("BHOP", 1.0)], "BLINV": [("BLINV", 1.0)], "VQ": [("VQ", 1.0)], "BVQ": [("BV", 0.5), ("BHOP", 0.5)], "BV": [("BV", 1.0)]}
JUDGED_ARMS = ("BHOP", "BLINV", "VQ", "BVQ")
LABELS = {"BHOP": "대형 고수익성", "BLINV": "대형 보수적 투자", "VQ": "싸고 돈 잘 버는 회사", "BVQ": "대형 가치 50 + 대형 고수익성 50", "BV": "대형 가치(보고)"}
PASS, FAIL = "TILT_BEATS_MARKET", "FAIL"


def load_real() -> dict:
    from core import french_factors as ff

    ff3 = ff.load("ff3_daily")
    if ff3 is None:
        raise RuntimeError("Ken French FF3 일별 자료를 받지 못함")
    frames = {"rf": ff3["RF"].astype(float), "M": (ff3["Mkt-RF"] + ff3["RF"]).astype(float)}
    for k, (ds, col) in SRC.items():
        df = ff.load(ds)
        if df is None or col not in df:
            raise RuntimeError(f"Ken French {ds} 의 '{col}' 열을 받지 못함")
        frames[k] = df[col].astype(float)
    df = pd.DataFrame(frames).dropna()
    df = df[df.index >= pd.Timestamp(FIRST_START)]
    rf = L.lab.to_weekdays(df["rf"])
    rets = L.lab.clean_industry(L.lab.to_weekdays(df[COLS]))
    return {"rf": rf, "rets": rets.reindex(rf.index), "source": "Ken French data library (daily VW; FF3, 6 ME×OP, 6 ME×INV, 25 BEME×OP, 25 ME×BM)"}


def load_synthetic(seed: int = 11) -> dict:
    d = L.load_long_synthetic()
    idx = d["rf"].index
    idx = idx[idx >= pd.Timestamp(FIRST_START)]
    m = d["mkt"].reindex(idx)
    rng = np.random.default_rng(seed)
    rets = pd.DataFrame({"M": m}, index=idx)
    for i, k in enumerate(COLS[1:]):
        rets[k] = m * (0.95 + 0.05 * i) + rng.normal(0.00002 * (i - 1), 0.004, len(idx))
    return {"rf": d["rf"].reindex(idx), "rets": rets, "source": "synthetic (smoke)"}


def window_sets(days: pd.DatetimeIndex, h: int, smoke: bool) -> dict:
    wins = L.re_.rolling_windows(days, h, step="M", first_start=FIRST_START)
    wins = wins[::36 if smoke else 1]
    return {"first": [w for w in wins if w[1] <= pd.Timestamp(H1_END)],
            "second": [w for w in wins if w[0] >= pd.Timestamp(H2_START) and w[1] <= pd.Timestamp(H2_END)],
            "since2008": [w for w in wins if w[0] >= pd.Timestamp(RECENT_START) and w[1] <= pd.Timestamp(H2_END)],
            "unseen": [w for w in wins if w[1] > pd.Timestamp(H2_END)]}


def eval_set(days, px, cg, wins) -> dict:
    mk = [L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r: [(0, 1.0)]) for s, e in wins]
    out = {"MKT_irr_median": float(np.nanmedian([x["irr"] for x in mk])) if mk else None}
    for a, mix in ARMS.items():
        alloc = [(COLS.index(c), w) for c, w in mix]
        res = [L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r, alloc=alloc: alloc) for s, e in wins]
        rows = [L.pair_summary(x, b) for x, b in zip(res, mk)]
        v = L.kpi_pairs_verdict(rows, WIN_SHARE_MIN, MEDIAN_IRR_MIN, P10_IRR_MIN)
        if rows:
            v["median_mdd_gap"] = float(np.nanmedian([r["mdd_gap"] for r in rows]))
            v["median_ratio"] = float(np.nanmedian([r["ratio"] for r in rows]))
            v["irr_median"] = float(np.nanmedian([x["irr"] for x in res]))
            v["checks"]["mdd"] = v["median_mdd_gap"] >= -MDD_TOL
            v["pass"] = all(v["checks"].values())
        out[a] = v
    return out


def body(R: "L.Runner"):
    data = R.stage("inputs", lambda: load_synthetic() if R.smoke else load_real())
    rets, rf = data["rets"], data["rf"].fillna(0.0)
    days = rets.index
    adj = rets.copy()
    for c in COLS[1:]:
        adj[c] = adj[c] - TILT_FEE / 252
    px = np.column_stack([L.level(adj[c]).to_numpy() for c in COLS])
    cg = np.cumprod(1 + rf.to_numpy() * (1 - L.INTEREST_TAX))
    cells = {}
    for h in HORIZONS:
        for sn, wins in window_sets(days, h, R.smoke).items():
            cells[f"{h}y|{sn}"] = R.stage(f"set_{h}y_{sn}", lambda wins=wins: eval_set(days, px, cg, wins))
    judged = [f"{h}y|{sn}" for h in HORIZONS for sn in ("first", "second")]
    verdicts = {}
    for a in JUDGED_ARMS:
        ok = all(cells[k].get(a, {}).get("pass") is True for k in judged)
        verdicts[a] = PASS if ok else FAIL
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    verdicts["passed"] = f"{sum(PASS in v for v in verdicts.values())}/{len(JUDGED_ARMS)}"
    ann = {c: float((1 + adj[c]).prod() ** (252 / len(adj)) - 1) for c in COLS}
    result = L.rnd({"judge_version": RULES_VERSION, "smoke": R.smoke, "source": data["source"], "verdicts": verdicts, "cells": cells,
                    "full_period_cagr_after_fee": ann, "data_range": [str(days[0].date()), str(days[-1].date())],
                    "rule": {"monthly_krw": MONTHLY_KRW, "tilt_fee": TILT_FEE, "halves": [H1_END, H2_START, H2_END],
                             "thresholds": {"win_share_min": WIN_SHARE_MIN, "median_irr_min": MEDIAN_IRR_MIN, "p10_irr_min": P10_IRR_MIN, "mdd_tol": MDD_TOL}}})
    if R.smoke:
        assert all(cells[k]["BHOP"].get("n", 0) > 0 for k in judged), "빈 판정 구간"
        assert len({round(cells["10y|first"][a]["median_diff_irr"], 8) for a in ARMS}) > 2, "팔이 구별되지 않음"
    return result, render(result)


def render(r: dict) -> str:
    v, P = r["verdicts"], L.pct
    out = [f"# 수익성·보수적 투자 기울이기 — 팔지 않는 적립 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "돈 잘 버는 대형주, 자산을 덜 불리는 대형주, 싸고 돈 잘 버는 회사에 매달 10만 원씩 넣고 팔지 않으면 시장보다 세후로 많이 남는지 "
           f"Ken French 자료({r['data_range'][0]} ~ {r['data_range'][1]})로 본다.", "",
           f"**종합: {v['passed']} 통과** — " + " · ".join(f"{LABELS[a]} **{v[a]}**" for a in JUDGED_ARMS), "",
           "통과해도 엔진은 바뀌지 않는다(전진 원장 후보일 뿐).", "", "## 규칙 (결과를 보기 전에 고정)", "",
           f"- 모든 기울이기 팔은 연 {TILT_FEE * 100:.2f}% 보수를 매일 뗀다. 매수 수수료 0.1% + 환전 0.05%, 환율 1,300원 고정, 끝에 양도세 22% × (이익 − 250만 원).",
           f"- 앞 반쪽: 끝 ≤ {H1_END}. 뒤 반쪽: 시작 ≥ {H2_START}, 끝 ≤ {H2_END}. 10·20년 × 앞·뒤 네 칸 모두 통과해야 한다.",
           f"- 통과: 이긴 구간 ≥ {WIN_SHARE_MIN:.0%}, 세후 IRR 차이 중앙값 ≥ +{MEDIAN_IRR_MIN * 100:.1f}%p, 10분위 ≥ {P10_IRR_MIN * 100:.1f}%p, "
           f"계좌 최대낙폭 중앙값이 시장보다 {MDD_TOL * 100:.0f}%p 넘게 나쁘지 않음.", "",
           "## 전체 기간 연수익 (보수 뗀 뒤, 세전·적립 아님)", "", "| 자산 | 연수익 |", "|---|---|"]
    for c, x in r["full_period_cagr_after_fee"].items():
        out.append(f"| {LABELS.get(c, '시장') if c != 'M' else '시장'} | {P(x, nd=2)} |")
    for key, c in r["cells"].items():
        h, sn = key.split("|")
        name = {"first": "앞 반쪽", "second": "뒤 반쪽", "since2008": "2008 이후 시작 (보고만)", "unseen": "2024-10 이후 끝 (보고만)"}[sn]
        out += ["", f"## {h} — {name}", "", f"시장 IRR 중앙값 {P(c.get('MKT_irr_median'), nd=2)}", "",
                "| 팔 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 팔 IRR 중앙값 | 계좌 낙폭 차이 | 통과 |", "|---|---|---|---|---|---|---|"]
        for a in ARMS:
            s = c.get(a, {})
            if s.get("n"):
                out.append(f"| {LABELS[a]} | {s['n']} | {P(s['share_win'], nd=0)} | {P(s['median_diff_irr'], True, 2)}p / {P(s['p10_diff_irr'], True, 2)}p | "
                           f"{P(s.get('irr_median'), nd=2)} | {P(s.get('median_mdd_gap'), True)} | {'예' if s.get('pass') else '아니오'} |")
    out += ["", "## 주의", "",
            "- Ken French 포트폴리오는 매년 6월 다시 구성하는 '종이 포트폴리오'다. 같은 규칙의 실제 ETF(예: 수익성·가치 ETF)는 2013 년 이후에야 생겼고 구성 방식이 다르다.",
            "- 수익성·투자 팩터는 2013~2015 년에 공개됐다. 뒤 반쪽 대부분이 공개 전이라, 공개 뒤 효과가 줄었을 수 있다(2008 이후·2024-10 이후 칸을 함께 볼 것).",
            "- 네 팔을 동시에 시험한다. 구간이 크게 겹친다. 배당 원천징수 미반영. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    R = L.Runner(RULES_VERSION, argv)
    return R.run(body)


if __name__ == "__main__":
    raise SystemExit(main())
