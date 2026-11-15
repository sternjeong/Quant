"""검증 연구 sat-horizon-v2 (2026-11-15 사전 등록): '12-1 모멘텀 상위 5종목 × 12개월 보유'가 아직 보지 않은 구간에서도 S&P 500 을 7%p 넘게 이기나.

공시(결과를 본 뒤 세운 가설이다): sat-horizon-v1 은 네 기간 모두 선택 구간(2002~2012, 2009 반등 포함)에서 단기 반전(REV1M)을 골랐고
확인 구간에서 무너졌다(판정 SKILL_BELOW_TARGET·FAIL). 그 확인 구간(2013~2024-09)에서 사용자 목표(+7%p)에 가장 가까웠던 것이
MOM12_1 × 12개월이었다(평균 E +8.4%p, 중앙 +8.2%p, P(E≥7%p) 51% vs 무작위 25%, E>0 64%). 이 숫자는 고른 뒤에 본 것이라 증거가 아니다.
그래서 v1 이 한 번도 쓰지 않은 구간에서 이 가설 하나만 다시 잰다.

판정 구간(사전 고정, v1 이 쓰지 않은 자료): 형성 1997-01 ~ 2001-01(보유 끝 ≤ 2002-01-31). fja05680 시점 기준 편입은 1996-01 부터 있다.
규칙: v1 과 같다(매달 첫 거래일, 그날 편입·r−1·r−253·r 가격이 있는 종목 중 MOM12_1 상위 5개, r 종가 매수, 252거래일 뒤 매도, E = 평균 − SPY).
CONFIRMED ⇔ 모두:
  (a) 평균 E ≥ +7%p
  (b) 생존편향 스트레스: 평균 E − 3%p(1990년대는 상장폐지 누락이 더 많아 v1 의 2%보다 크게) ≥ +7%p
  (c) P(E ≥ 7%p) − 무작위 5종목 P 의 평균 > 0, 이동 블록 부트스트랩(12개월, 2,000회) 단측 p < 0.05
  (d) E 중앙값 > 0, E > 0 비율 ≥ 50%
  (e) 자료 충분: 형성 달 ≥ 36, 편입 종목 중 가격이 있는 비율의 중앙값 ≥ 50%(미만이면 NOT_EVALUABLE)
그 밖은 FAIL(관측 IR 이 최소 검출 효과보다 작으면 FAIL_UNDERPOWERED).
보고만(판정 아님): 같은 규칙의 시대별(1997~2001 · 2002~2012 · 2013~2024-09 · 2024-10~, 뒤 셋은 이미 본 구간), 종목 수 3·10·20,
1월만 형성(연 1회 교체), 그리고 v1 의 다른 규칙들의 같은 구간 값. 엔진은 바뀌지 않는다(사용자 확인 뒤 별도 작업).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SH = _load("sat_horizon_v1", HERE.parent / "sat-horizon-v1" / "run.py")  # 점수·고르기·전진 수익·가격 공급자를 그대로 쓴다
ES, L = SH.ES, SH.L
from core import research_power as rp  # noqa: E402

JOB_ID = "sat-horizon-v2"
RULES_VERSION = "sat-horizon-v2/2026-11-15"
RULE = "MOM12_1"
H = 252
PRICE_START = "1995-01-01"
JUDGE_FORM = (pd.Timestamp("1997-01-01"), pd.Timestamp("2001-01-31"))
JUDGE_END = pd.Timestamp("2002-01-31")
ERAS = {"1997-2001 (판정)": ("1997-01-01", "2001-01-31"), "2002-2012 (v1 선택, 본 구간)": ("2002-01-01", "2012-12-31"),
        "2013-2024-09 (v1 확인, 본 구간)": ("2013-01-01", "2023-09-30"), "2024-10~ (본 구간)": ("2023-10-01", "2100-01-01")}
SURV_DRAG = 0.03
ALPHA = 0.05
MIN_MONTHS = 36
MIN_COVERAGE = 0.50
TOP_NS = (3, 5, 10, 20)


def build(px: np.ndarray, days: pd.DatetimeIndex, tickers: list[str], members_at, spy_col: int, check=lambda: None) -> pd.DataFrame:
    """형성 달마다: 종목 수별 E, 무작위 5종목 P(E≥7%p)·평균, 편입 대비 가격 보유 비율, 고른 종목."""
    col_of = {t: i for i, t in enumerate(tickers)}
    rng = np.random.default_rng(SH.SEED)
    rows = []
    for r in SH.formation_rows(days):
        check()
        if r + H >= px.shape[0]:
            continue
        mem = members_at(days[r].date())
        if not mem:
            continue
        cols = np.array(sorted(col_of[t] for t in mem if t in col_of and col_of[t] != spy_col), dtype=int)
        coverage = len(cols) / len(mem)
        ok = np.isfinite(px[r - 1, cols]) & np.isfinite(px[r - 253, cols]) & np.isfinite(px[r, cols]) if len(cols) else np.array([], bool)
        cols = cols[ok]
        if len(cols) < SH.MIN_NAMES:
            continue
        sc = SH.scores(px, r, cols)
        spy = px[r + H, spy_col] / px[r, spy_col] - 1
        ex = SH.fwd_returns(px, r, H, cols) - spy
        row: dict[str, Any] = {"date": days[r], "end": days[r + H], "coverage": coverage, "n_names": int(np.isfinite(ex).sum())}
        for n in TOP_NS:
            idx = SH.top_n(sc[RULE], n)
            row[f"E{n}"] = float(np.nanmean(ex[idx])) if len(idx) else np.nan
        row["picks"] = ",".join(tickers[cols[i]] for i in SH.top_n(sc[RULE], 5))
        for k in SH.RULES:
            idx = SH.top_n(sc[k], 5)
            row[f"rule_{k}"] = float(np.nanmean(ex[idx])) if len(idx) else np.nan
        pool = np.flatnonzero(np.isfinite(ex))
        pick = np.argpartition(rng.random((SH.N_RANDOM, len(pool))), 5, axis=1)[:, :5]
        draws = ex[pool][pick].mean(axis=1)
        row["rand_hit7"], row["rand_mean"] = float(np.mean(draws >= SH.TARGET)), float(np.mean(draws))
        rows.append(row)
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def stats(e: pd.Series) -> dict[str, Any]:
    e = e.dropna()
    if e.empty:
        return {"n": 0}
    return {"n": int(len(e)), "mean": float(e.mean()), "median": float(e.median()), "hit7": float((e >= SH.TARGET).mean()),
            "hit0": float((e > 0).mean()), "p10": float(e.quantile(0.1)), "p90": float(e.quantile(0.9))}


def judge(t: pd.DataFrame, power: dict) -> dict[str, Any]:
    w = t[(t.index >= JUDGE_FORM[0]) & (t.index <= JUDGE_FORM[1]) & (t["end"] <= JUDGE_END)]
    out: dict[str, Any] = {"n_months": int(len(w))}
    cov = float(w["coverage"].median()) if len(w) else 0.0
    out["coverage_median"] = cov
    if len(w) < MIN_MONTHS or cov < MIN_COVERAGE:
        out["verdict"] = "NOT_EVALUABLE"
        out["reason"] = f"형성 달 {len(w)}(최소 {MIN_MONTHS}) · 가격 보유 비율 중앙값 {cov:.0%}(최소 {MIN_COVERAGE:.0%})"
        return out
    s = stats(w["E5"])
    d = ((w["E5"] >= SH.TARGET).astype(float) - w["rand_hit7"]).to_numpy()
    p = SH.block_boot_p(d, 12, SH.SEED + 7)
    active = (w["E5"] - w["rand_mean"]).to_numpy()
    ir = float(np.mean(active) / np.std(active)) if np.std(active) > 0 else None
    checks = {"a_mean_ge_target": s["mean"] >= SH.TARGET, "b_survivorship_stress": s["mean"] - SURV_DRAG >= SH.TARGET,
              "c_hit7_beats_random": bool(np.isfinite(p) and np.mean(d) > 0 and p < ALPHA),
              "d_not_gambling": s["median"] > 0 and s["hit0"] >= SH.HIT0_MIN}
    verdict = "CONFIRMED" if all(checks.values()) else rp.classify_fail(ir, power)
    noop = rp.noop_guard(active.tolist())
    if noop:
        verdict, out["reason"] = "NOT_EVALUABLE", noop
    out.update({"verdict": verdict, "checks": checks, "stats": s, "rand_hit7": float(w["rand_hit7"].mean()),
                "rand_mean": float(w["rand_mean"].mean()), "hit7_minus_random": float(np.mean(d)), "p_one_sided": p,
                "observed_ir_vs_random": ir, "first": str(w.index[0].date()), "last": str(w.index[-1].date())})
    return out


def report_tables(t: pd.DataFrame) -> dict[str, Any]:
    eras = {}
    for name, (a, b) in ERAS.items():
        w = t[(t.index >= a) & (t.index <= b)]
        if w.empty:
            continue
        eras[name] = {"coverage_median": float(w["coverage"].median()),
                      "top_n": {str(n): stats(w[f"E{n}"]) for n in TOP_NS},
                      "january_only_top5": stats(w[w.index.month == 1]["E5"]),
                      "rules_top5": {k: stats(w[f"rule_{k}"]) for k in SH.RULES},
                      "rand_hit7": float(w["rand_hit7"].mean())}
    return eras


def body(R):
    SH.PRICE_START = PRICE_START
    if R.smoke:
        inp = SH.synthetic_inputs()
        closes, members_at, tickers = inp["closes"], inp["members_at"], inp["tickers"]
        closes.index = closes.index - pd.DateOffset(years=5)  # 가짜 자료를 1995~ 로 옮겨 판정 구간을 지나게 한다
        source = "synthetic (smoke)"
    else:
        members_at, tickers = _members_1996()
        closes = SH.load_prices_real(R, [t for t in tickers if t != "SPY"])
        source = "core.market_data 조정 종가(Yahoo 캐시) + fja05680 S&P 500 시점 기준 구성종목(1996~)"
    old_start = SH.FORM_START
    SH.FORM_START = JUDGE_FORM[0]
    try:
        cols = list(closes.columns)
        px = closes.to_numpy(dtype=float)
        t = R.stage("table", lambda: build(px, closes.index, cols, members_at, cols.index("SPY"), R.check_time))
    finally:
        SH.FORM_START = old_start
    if t.empty:
        raise RuntimeError("형성 가능한 달이 없음")
    power = rp.power_report((JUDGE_END - JUDGE_FORM[0]).days / 365.25, 1)
    res = judge(t, power)
    verdicts = {"MOM12_1_12m": res["verdict"]}
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    result = L.rnd({"id": JOB_ID, "judge_version": RULES_VERSION, "smoke": R.smoke, "source": source, "verdicts": verdicts,
                    "power": power, "power_line": rp.power_line(power), "judge": res, "eras": report_tables(t),
                    "latest_picks": {"date": str(t.index[-1].date()), "tickers": t["picks"].iloc[-1]},
                    "rule": {"rule": RULE, "horizon_days": H, "judge_form": [str(x.date()) for x in JUDGE_FORM], "judge_end": str(JUDGE_END.date()),
                             "survivorship_drag": SURV_DRAG, "alpha": ALPHA, "min_months": MIN_MONTHS, "min_coverage": MIN_COVERAGE}})
    return result, render(result)


def _members_1996():
    """earnings-surprise-v1 의 sp500_members 는 2009 년부터 모은다 — 같은 원천에서 1996 년부터 모은다."""
    from bisect import bisect_right
    from datetime import date

    from core import hypothesis_engine as he

    dates, members = he._sp500_rows()
    everyone = sorted(set().union(*members))

    def at(d: date) -> frozenset:
        i = bisect_right(dates, d) - 1
        return members[i] if i >= 0 else frozenset()

    return at, everyone


def render(r: dict) -> str:
    P = L.pct
    j = r["judge"]
    out = [f"# 12-1 모멘텀 상위 5종목 × 12개월 — 보지 않은 구간(1997~2001) 확인 ({r['judge_version']})" + (" — 스모크(가짜 데이터)" if r["smoke"] else ""), "",
           f"**판정: {r['verdicts']['MOM12_1_12m']}**", "",
           "공시: 이 가설은 sat-horizon-v1 의 확인 구간 결과를 본 뒤 세웠다. 그래서 v1 이 쓰지 않은 1997~2001 형성분만으로 판정한다.", "",
           "## 판정 규칙(결과를 보기 전에 고정)", "",
           f"- 형성 {r['rule']['judge_form'][0]} ~ {r['rule']['judge_form'][1]}(끝 ≤ {r['rule']['judge_end']}), 시점 기준 S&P 500, 12-1 모멘텀 상위 5, 252거래일 보유, E = 평균 − SPY.",
           f"- CONFIRMED = (a) 평균 E ≥ +7%p (b) 평균 E − {r['rule']['survivorship_drag'] * 100:.0f}%p ≥ +7%p (c) P(E≥7%p) 가 무작위 5종목보다 높음, 블록 부트스트랩 p < {r['rule']['alpha']} "
           f"(d) E 중앙값 > 0·E>0 비율 ≥ 50% (e) 형성 달 ≥ {r['rule']['min_months']}·가격 보유 비율 중앙값 ≥ {r['rule']['min_coverage']:.0%}.",
           f"- {r['power_line']}", "", "## 판정 구간", ""]
    if j.get("checks"):
        s, ck = j["stats"], j["checks"]
        out += [f"형성 {j['n_months']}달({j['first']} ~ {j['last']}), 가격 보유 비율 중앙값 {P(j['coverage_median'], nd=0)}", "",
                "| 지표 | 값 | 기준 | 결과 |", "|---|---|---|---|",
                f"| 평균 E | {P(s['mean'], True, 1)} | ≥ +7%p | {'통과' if ck['a_mean_ge_target'] else '미달'} |",
                f"| 생존편향 차감 | {P(s['mean'] - r['rule']['survivorship_drag'], True, 1)} | ≥ +7%p | {'통과' if ck['b_survivorship_stress'] else '미달'} |",
                f"| P(E≥7%p) | {P(s['hit7'], nd=0)} (무작위 {P(j['rand_hit7'], nd=0)}, p={j['p_one_sided']}) | 무작위보다 높음 | {'통과' if ck['c_hit7_beats_random'] else '미달'} |",
                f"| 중앙 E / E>0 | {P(s['median'], True, 1)} / {P(s['hit0'], nd=0)} | > 0 / ≥ 50% | {'통과' if ck['d_not_gambling'] else '미달'} |", ""]
    else:
        out += [f"사유: {j.get('reason')}", ""]
    out += ["## 보고만: 시대별·종목 수별(뒤 세 구간은 이미 본 구간)", "", "| 시대 | 가격 보유 | 3종목 | 5종목 | 10종목 | 20종목 | 1월만(5) | 무작위 P(≥7%p) |", "|---|---|---|---|---|---|---|---|"]
    for name, e in r["eras"].items():
        f = lambda s: f"{P(s['mean'], True, 1)} / 중앙 {P(s['median'], True, 1)} / {P(s['hit7'], nd=0)}" if s.get("n") else "—"  # noqa: E731
        out.append(f"| {name} | {P(e['coverage_median'], nd=0)} | " + " | ".join(f(e["top_n"][str(n)]) for n in TOP_NS) + f" | {f(e['january_only_top5'])} | {P(e['rand_hit7'], nd=0)} |")
    out += ["", "칸 = 평균 E / 중앙 E / P(E≥7%p).", "", "## 보고만: v1 규칙들(5종목, 12개월) 시대별 평균 E", "",
            "| 규칙 | " + " | ".join(r["eras"]) + " |", "|---|" + "---|" * len(r["eras"])]
    for k in SH.RULES:
        out.append(f"| {k} | " + " | ".join(P(e["rules_top5"][k].get("mean"), True, 1) if e["rules_top5"][k].get("n") else "—" for e in r["eras"].values()) + " |")
    out += ["", f"최근 고른 종목({r['latest_picks']['date']}): {r['latest_picks']['tickers']}", "", "## 주의", "",
            "- 1990년대는 상장폐지 종목 누락이 더 많다(가격 보유 비율 참고). 그래서 생존편향 차감을 3%p 로 크게 잡았다.",
            "- 판정 구간은 4년, 12개월 보유가 겹치는 달들이라 독립 표본이 적다(블록 부트스트랩으로 반영, 검정력 낮음).",
            "- 세금·수수료 미반영. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
