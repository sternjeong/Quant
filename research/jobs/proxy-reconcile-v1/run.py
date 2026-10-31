"""검증 연구 proxy-reconcile-v1 (2026-10-23 사전 등록): 1927~2007 학술 자료(Ken French)에서 얻은 결론을 실제 ETF 에 옮길 수 있나.

같은 2000~2024 기간에 같은 규칙을 두 세계에서 돌려 서로 맞는지 본다:
  학술 세계  — Ken French 시장 + 12 산업(시가총액 가중, 배당 포함)
  ETF 세계   — SPY + Select Sector SPDR 9 개(XLB XLE XLF XLI XLK XLP XLU XLV XLY, 조정 종가)
규칙 5 개: 팔지 않는 월 10만 원 적립의 EW(똑같이)·DD(1년 고점 대비 가장 많이 빠진 곳)·MA200(200일선 대비 가장 아래)·REV36(3년 수익 가장 낮은 곳),
그리고 매달 갈아타는 MOM2(252일 수익 상위 2, 균등, 총수익·편도 10bp 비용). 각 세계의 시장(French 시장 / SPY)이 기준이다.
측정: 2000-01 부터 매달 시작하는 10년 구간(끝 ≤ 2024-09-30)마다 (규칙 초과수익 연율, 세계 간 차이 = ETF − 학술). 적립 규칙은 팔지 않는 계좌의 세후 IRR 차이,
MOM2 는 세전 연 수익 차이(세금은 두 세계에 같은 식이라 차이의 원인이 아님 — 아래 주의).
판정(규칙마다) TRANSFERABLE ⇔ ① 구간별 세계 간 차이 중앙값의 절댓값 ≤ 1.0%p ② 두 세계 구간별 초과수익의 스피어먼 상관 ≥ 0.5.
NOT_TRANSFERABLE 이면 아래를 보고한다: 시장 대용(French 시장 대 SPY)의 연 수익 차이·상관, 세계별 초과수익 중앙값, 편도 회전율.
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

V1 = L._load_mod("_dca_asset_pick_v1", "research/jobs/dca-asset-pick-v1/run.py")
SSB = L._load_mod("_dca_ssb", "research/jobs/spy-sector-blend-v1/run.py")

JOB_ID = "proxy-reconcile-v1"
RULES_VERSION = "proxy-reconcile-v1/2026-10-23"
MONTHLY_KRW = 100_000
BUYONLY = ("EW", "DD", "MA200", "REV36")
RULES = BUYONLY + ("MOM2",)
LABELS = {"EW": "똑같이 나눔", "DD": "1년 고점 대비 가장 많이 빠진 곳", "MA200": "200일선 대비 가장 아래",
          "REV36": "3년 수익 가장 낮은 곳", "MOM2": "252일 수익 상위 2 (매달 갈아탐, 세전)"}
ETF9 = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
HORIZON = 10
FIRST_START, JUDGED_END = "2000-01-01", "2024-09-30"
GAP_MAX, CORR_MIN = 0.010, 0.5
MOM_ROWS, MOM_COST_BPS = 252, 10.0


def weights_fn(rule: str, scores: dict, px: np.ndarray, n: int):
    """열 0 = 시장, 1..n = 산업/섹터."""
    if rule == "EW":
        return lambda r: [(1 + j, 1.0 / n) for j in range(n)]
    key = {"DD": "DD12", "MA200": "MA200", "REV36": "REV36"}[rule]

    def f(r):
        j = V1.pick(scores[key][r])
        return [(0, 1.0)] if j < 0 else [(1 + j, 1.0)]
    return f


def buyonly_diffs(px: np.ndarray, cg: np.ndarray, days, scores, wins, n, rules=BUYONLY) -> dict[str, list]:
    out = {r: [] for r in rules}
    for s, e in wins:
        base = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r: [(0, 1.0)])
        for rule in rules:
            a = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, weights_fn(rule, scores, px, n))
            out[rule].append(a["irr"] - base["irr"])
    return out


def mom2_returns(ret_ind: pd.DataFrame, ret_mkt: pd.Series, k: int = 2) -> tuple[pd.Series, float]:
    """매달 첫 거래일 전날 종가까지의 252일 수익 상위 k, 균등, 그날부터 한 달 보유. 편도 비용 10bp × 바뀐 비중. 반환 (일 수익, 편도 회전율/년)."""
    days = ret_ind.index
    lvl = (1 + ret_ind.fillna(0.0)).cumprod().where(ret_ind.notna().cummax())
    score = (lvl / lvl.shift(MOM_ROWS) - 1.0).shift(1).to_numpy()
    flags = L.lab.month_first_mask(days)
    n = ret_ind.shape[1]
    R = ret_ind.fillna(0.0).to_numpy()
    w = np.zeros(n)
    out = np.zeros(len(days))
    turn = 0.0
    for i in range(len(days)):
        # 표류
        if i > 0:
            g = w * (1 + R[i])
            out[i] = g.sum() - w.sum()
            w = g / g.sum() * w.sum() if g.sum() > 0 else w
        if flags[i]:
            sc = score[i]
            ok = np.flatnonzero(np.isfinite(sc))
            nw = np.zeros(n)
            if len(ok) >= k:
                nw[ok[np.argsort(-sc[ok], kind="stable")[:k]]] = 1.0 / k
            else:
                nw[:] = 0.0
            t = float(np.abs(nw - w).sum()) / 2.0
            turn += t
            out[i] -= (MOM_COST_BPS / 1e4) * 2 * t
            w = nw
    yrs = (days[-1] - days[0]).days / 365.25
    return pd.Series(out, index=days), turn / yrs


def cagr(r: np.ndarray) -> float:
    n = len(r)
    return float(np.prod(1 + r) ** (252.0 / n) - 1) if n else float("nan")


def mom2_diffs(strat: pd.Series, mkt: pd.Series, wins) -> list[float]:
    out = []
    for s, e in wins:
        a, b = strat.loc[s:e].to_numpy()[1:], mkt.reindex(strat.index).loc[s:e].to_numpy()[1:]
        out.append(cagr(a) - cagr(b))
    return out


def world(name, mkt_ret: pd.Series, ind_ret: pd.DataFrame, rf: pd.Series, wins) -> dict:
    days = mkt_ret.dropna().index
    ind_ret = ind_ret.reindex(days)
    ind_px = ind_ret.apply(L.level)
    mkt_px = L.level(mkt_ret.reindex(days))
    panel = np.column_stack([mkt_px.to_numpy(), ind_px.to_numpy()])
    cg = np.cumprod(1 + rf.reindex(days).fillna(0.0).to_numpy() * (1 - L.INTEREST_TAX))
    scores = V1.score_tables(ind_px)
    d = buyonly_diffs(panel, cg, days, scores, wins, ind_ret.shape[1])
    strat, turn = mom2_returns(ind_ret, mkt_ret)
    d["MOM2"] = mom2_diffs(strat, mkt_ret.reindex(days), wins)
    return {"diffs": d, "mom2_turnover_one_way_per_year": turn,
            "mkt_cagr_full": cagr(mkt_ret.reindex(days).loc[wins[0][0]:wins[-1][1]].fillna(0.0).to_numpy())}


def load_etf(smoke: bool) -> dict:
    inp = SSB.synthetic_etf() if smoke else SSB.load_etf_real()
    adj = inp["adj"]
    cols = ["SPY"] + [t for t in ETF9 if t in adj.columns]
    a = adj[cols].dropna(subset=["SPY"]).ffill(limit=3)
    ret = a.pct_change(fill_method=None)
    bil = adj["BIL"].reindex(a.index).ffill().pct_change(fill_method=None).fillna(0.0)
    return {"mkt": ret["SPY"], "ind": ret[[t for t in cols if t != "SPY"]], "rf": bil, "cols": cols}


def body(R):
    data = R.stage("inputs_fr", lambda: L.load_long_synthetic() if R.smoke else L.load_long_real())
    etf = R.stage("inputs_etf", lambda: load_etf(R.smoke))
    first = "2012-01-01" if R.smoke else FIRST_START
    jend = pd.Timestamp("2016-06-30" if R.smoke else JUDGED_END)
    hz = 2 if R.smoke else HORIZON
    common = etf["mkt"].dropna().index.intersection(data["mkt"].dropna().index)
    wins = [w for w in L.re_.rolling_windows(common, hz, step="A" if R.smoke else "M", first_start=first) if w[1] <= jend]
    fr = R.stage("world_fr", lambda: world("FR", data["mkt"], data["ind12"], data["rf"], wins))
    et = R.stage("world_etf", lambda: world("ETF", etf["mkt"], etf["ind"], etf["rf"], wins))
    res, verdicts = {}, {}
    for rule in RULES:
        a, b = np.array(fr["diffs"][rule], dtype=float), np.array(et["diffs"][rule], dtype=float)
        gap = b - a
        rho = float(pd.Series(a).rank().corr(pd.Series(b).rank())) if len(a) > 2 else float("nan")
        ok = bool(np.isfinite(rho) and abs(np.nanmedian(gap)) <= GAP_MAX and rho >= CORR_MIN)
        res[rule] = {"n_windows": len(a), "median_excess_french": float(np.nanmedian(a)), "median_excess_etf": float(np.nanmedian(b)),
                     "median_gap_etf_minus_french": float(np.nanmedian(gap)), "mean_gap": float(np.nanmean(gap)), "spearman": rho,
                     "p10_gap": float(np.nanpercentile(gap, 10)), "p90_gap": float(np.nanpercentile(gap, 90)), "transferable": ok}
        v = "TRANSFERABLE" if ok else "NOT_TRANSFERABLE"
        verdicts[rule] = f"SMOKE_ONLY({v})" if R.smoke else v
    verdicts["transferable"] = f"{sum(r['transferable'] for r in res.values())}/{len(RULES)}"
    # 시장 대용 품질
    m_fr = data["mkt"].reindex(common).fillna(0.0).loc[first:]
    m_et = etf["mkt"].reindex(common).fillna(0.0).loc[first:]
    proxy = {"french_mkt_cagr": cagr(m_fr.to_numpy()), "spy_cagr": cagr(m_et.to_numpy()), "daily_corr": float(np.corrcoef(m_fr, m_et)[0, 1])}
    result = L.rnd({"judge_version": RULES_VERSION, "smoke": R.smoke, "source": data.get("source"), "etf_menu": etf["cols"], "verdicts": verdicts,
                    "rules": res, "market_proxy": proxy,
                    "mom2_turnover": {"french": fr["mom2_turnover_one_way_per_year"], "etf": et["mom2_turnover_one_way_per_year"]},
                    "windows": {"n": len(wins), "first": str(wins[0][0].date()), "last_end": str(wins[-1][1].date()), "horizon_years": hz},
                    "rule": {"gap_max": GAP_MAX, "corr_min": CORR_MIN, "monthly_krw": MONTHLY_KRW, "labels": LABELS}})
    if R.smoke:
        assert len(wins) >= 3 and all(r["n_windows"] == len(wins) for r in res.values()), "구간 부족"
    return result, render(result)


def render(r: dict) -> str:
    P, v = L.pct, r["verdicts"]
    out = [f"# 학술 자료 결론을 실제 ETF 에 옮길 수 있나 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "같은 기간(2000~2024)·같은 규칙을 학술 세계(Ken French 시장 + 12 산업)와 ETF 세계(SPY + 섹터 ETF 9개)에서 돌려, 세계 간 초과수익이 서로 맞는지 본다. "
           "맞으면 1927~2007 의 긴 근거를 실제 ETF 판단에 쓸 수 있다.", "",
           f"**옮길 수 있음(TRANSFERABLE) {v['transferable']}** — " + " · ".join(f"{r['rule']['labels'][k]} **{v[k]}**" for k in RULES), "",
           "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", "",
           f"- 구간: {r['windows']['first']} 부터 매달 시작하는 {r['windows']['horizon_years']}년 구간 {r['windows']['n']}개(끝 ≤ {r['windows']['last_end']}). 두 세계에 같은 시작·끝 날짜.",
           "- 적립 규칙(EW·DD·MA200·REV36): 팔지 않는 월 10만 원, 끝에 모두 판다고 보고 세후 IRR 의 (규칙 − 그 세계 시장) 차이. 환율 1,300 원 고정(두 세계 같음). "
           "MOM2: 매달 252일 수익 상위 2 균등, 편도 10bp, 세전 연 수익의 (규칙 − 시장) 차이.",
           f"- TRANSFERABLE ⇔ 구간별 (ETF 초과 − 학술 초과) 중앙값의 절댓값 ≤ {r['rule']['gap_max'] * 100:.1f}%p 이고 두 세계 구간별 초과수익의 스피어먼 상관 ≥ {r['rule']['corr_min']}.", "",
           "## 규칙별 결과", "",
           "| 규칙 | 학술 초과 중앙값 | ETF 초과 중앙값 | 차이 중앙값 (10분위 ~ 90분위) | 스피어먼 | 판정 |", "|---|---|---|---|---|---|"]
    for k in RULES:
        s = r["rules"][k]
        out.append(f"| {r['rule']['labels'][k]} | {P(s['median_excess_french'], True, 2)}p | {P(s['median_excess_etf'], True, 2)}p | "
                   f"{P(s['median_gap_etf_minus_french'], True, 2)}p ({P(s['p10_gap'], True, 1)} ~ {P(s['p90_gap'], True, 1)}) | {s['spearman']:.2f} | **{v[k]}** |")
    mp = r["market_proxy"]
    out += ["", "## 시장 대용 품질", "",
            f"French 시장 연 수익 {P(mp['french_mkt_cagr'], nd=2)} · SPY {P(mp['spy_cagr'], nd=2)} · 일별 수익 상관 {mp['daily_corr']:.4f}. "
            f"MOM2 편도 회전율(연): 학술 {P(r['mom2_turnover']['french'], nd=0)} · ETF {P(r['mom2_turnover']['etf'], nd=0)}.", "",
            "## 읽는 법", "",
            "- 차이 중앙값이 작고 상관이 높으면 학술 자료의 결과가 ETF 에서도 비슷하게 나온다는 뜻이다. 차이가 크면 메뉴 구성(12 산업 대 9 섹터), 시장 대용의 차이, "
            "산업 정의(SIC 대 GICS)의 차이가 원인이다 — 이때 1927~2007 결과를 실제 ETF 에 그대로 쓰지 않는다.",
            "", "## 주의", "",
            "- 구간이 크게 겹친다(2000~2024 에서 겹치지 않는 10년은 2개 남짓). 이 비교는 '두 세계가 같은 역사에서 얼마나 같은가'를 보는 것이지 규칙이 좋은지 가리는 것이 아니다.",
            "- MOM2 는 세전이다. 세금은 두 세계에 같은 식으로 붙으므로 두 세계 차이의 원인은 아니다(정밀 세금 비교는 별도).",
            "- 섹터 ETF 9개는 2018 년 이전 XLC·XLRE 가 없어 9개로 맞췄다. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
