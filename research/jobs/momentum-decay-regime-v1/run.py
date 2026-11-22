"""momentum-decay-regime-v1 — 산업 간 상관·대형주 쏠림(실시간)이 X2 의 2008 이후 소멸을 설명하고, 낮을 때만 X2 를 들면 시장을 이기나. 규칙·판정은 SPEC.md.

python research/jobs/momentum-decay-regime-v1/run.py --out OUT --checkpoint CK [--smoke]
X2·계좌·통계 함수는 combo-regime-switch-v1 의 것을 그대로 쓴다. 계산은 수 분 안이라 체크포인트를 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RULES_VERSION = "momentum-decay-regime/v1"
JUDGE_VERSION = "decay-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
VARIABLES = ("C1_CORR", "C2_CAPDOM")
VAR_LABELS = {"C1_CORR": "산업 간 평균 상관(126일)", "C2_CAPDOM": "대형주 쏠림(시장 − 12 산업 평균, 252일)"}
CORR_DAYS, DOM_DAYS, MIN_MONTHS = 126, 252, 24
FIT = ("1929-01-01", "2007-12-31")
ERAS = {"A": ("1929-01-01", "1966-12-31"), "B": ("1967-01-01", "2007-12-31"), "C": ("2008-01-01", None)}
MIN_EXCESS = 0.01
MDD_TOL = 0.05
ALPHA = 0.05 / 4


def _load(name: str, rel: str):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cs():
    return _load("combo_regime_switch_v1_run", "research/jobs/combo-regime-switch-v1/run.py")


# ---------------------------------------------------------------- 변수 (월말 값, 과거만)
def _month_last(index: pd.DatetimeIndex) -> np.ndarray:
    return pd.Series(np.arange(len(index)), index=index).groupby(index.to_period("M")).max().to_numpy()


def month_variables(mkt: pd.Series, ind: pd.DataFrame) -> pd.DataFrame:
    """인덱스 = 판정한 달(Period). C1: 직전 126일 산업 쌍별 상관 평균, C2: 시장 252일 수익 − 12 산업 똑같이 평균 252일 수익."""
    idx = mkt.index
    last = _month_last(idx)
    periods = idx.to_period("M").unique()
    R = ind.to_numpy(dtype=float)
    c1 = np.full(len(last), np.nan)
    for j, i in enumerate(last):
        if i + 1 < CORR_DAYS:
            continue
        w = R[i + 1 - CORR_DAYS:i + 1]
        w = w[:, ~np.isnan(w).any(axis=0)]
        if w.shape[1] < 3:
            continue
        cm = np.corrcoef(w, rowvar=False)
        c1[j] = float(cm[np.triu_indices_from(cm, k=1)].mean())
    wm = (1 + mkt).cumprod()
    we = (1 + ind.mean(axis=1, skipna=True)).cumprod()
    dom = (wm / wm.shift(DOM_DAYS) - 1) - (we / we.shift(DOM_DAYS) - 1)
    return pd.DataFrame({"C1_CORR": c1, "C2_CAPDOM": dom.iloc[last].to_numpy()}, index=periods)


def expanding_z(s: pd.Series) -> pd.Series:
    mu = s.expanding(min_periods=MIN_MONTHS).mean()
    sd = s.expanding(min_periods=MIN_MONTHS).std()
    return (s - mu) / sd


def below_median(s: pd.Series) -> pd.Series:
    med = s.expanding(min_periods=MIN_MONTHS).median()
    return (s < med).where(med.notna() & s.notna())


def slope_test(y: pd.Series, x: pd.Series) -> dict[str, Any]:
    """y = a + b x 최소제곱, b 의 단측(b < 0) p."""
    d = pd.concat([y, x], axis=1).dropna()
    n = len(d)
    if n < 10:
        return {"n": n, "b": None, "t": None, "p": None}
    Y, X = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
    Xc = X - X.mean()
    b = float((Xc * (Y - Y.mean())).sum() / (Xc ** 2).sum())
    resid = Y - Y.mean() - b * Xc
    se = math.sqrt(float((resid ** 2).sum()) / (n - 2) / float((Xc ** 2).sum()))
    t = b / se if se > 0 else 0.0
    return {"n": n, "b": b, "t": t, "p": _cs().t_sf(-t, n - 2)}


# ---------------------------------------------------------------- 평가
def evaluate(mkt: pd.Series, ind: pd.DataFrame, x2: pd.Series) -> dict[str, Any]:
    cs = _cs()
    idx = mkt.index.intersection(x2.index).intersection(ind.index)
    mkt, ind, x2 = mkt.reindex(idx), ind.reindex(idx), x2.reindex(idx).fillna(0.0)
    var = month_variables(mkt, ind)
    ex_next = (cs.monthly(x2) - cs.monthly(mkt))          # 달 m 의 초과 — 변수는 m−1 월말
    res: dict[str, Any] = {"variables": {}, "verdicts": {}}
    for v in VARIABLES:
        z = expanding_z(var[v])
        z_applied = z.copy()
        z_applied.index = z_applied.index + 1
        fit = ex_next[(ex_next.index >= pd.Period(FIT[0], "M")) & (ex_next.index <= pd.Period(FIT[1], "M"))]
        t1 = slope_test(fit, z_applied.reindex(fit.index))
        on = cs.applied(below_median(var[v]))
        per = {}
        for e, (a, b) in ERAS.items():
            m, x = cs.era(mkt, a, b), cs.era(x2, a, b)
            r, sw = cs.switch_returns(x, m, on)
            per[e] = {**cs.era_stats(r, sw, m, x), "on_share": float(on.reindex(m.index.to_period("M").unique()).eq(True).mean())}
        full_m = cs.era(mkt, ERAS["A"][0], ERAS["B"][1])
        rf_, _ = cs.switch_returns(cs.era(x2, ERAS["A"][0], ERAS["B"][1]), full_m, on)
        t3t, t3p = cs.one_sided((cs.monthly(rf_) - cs.monthly(full_m)).to_numpy())
        T1 = t1["b"] is not None and t1["b"] < 0 and t1["p"] is not None and t1["p"] < ALPHA
        A, B, C = per["A"], per["B"], per["C"]
        T3 = (A["excess"] >= MIN_EXCESS and B["excess"] >= MIN_EXCESS and C["excess"] >= 0
              and t3p is not None and t3t is not None and t3t > 0 and t3p < ALPHA
              and all(x["mdd"] >= x["mdd_mkt"] - MDD_TOL for x in (A, B, C)))
        pre = var[v][(var.index >= pd.Period(FIT[0], "M")) & (var.index <= pd.Period(FIT[1], "M"))].dropna()
        post = var[v][var.index >= pd.Period(ERAS["C"][0], "M")].dropna()
        res["variables"][v] = {"slope": t1, "switch": per, "switch_t": t3t, "switch_p": t3p, "T1": bool(T1), "T3": bool(T3),
                               "mean_pre2008": float(pre.mean()) if len(pre) else None, "mean_post2008": float(post.mean()) if len(post) else None,
                               "latest": {"month": str(var[v].dropna().index[-1]), "value": float(var[v].dropna().iloc[-1]),
                                          "below_median": bool(below_median(var[v]).dropna().iloc[-1])}}
        res["verdicts"][v] = "EXPLAINS_AND_SWITCHES" if T1 and T3 else ("EXPLAINS_ONLY" if T1 else "FAIL")
    return res


# ---------------------------------------------------------------- 보고
def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x * 100:+.{nd}f}%"


def report(res: dict, smoke: bool) -> str:
    L = [f"# 모멘텀 계열 소멸의 실시간 원인 (momentum-decay-regime-v1{' · 스모크' if smoke else ''})", "",
         "산업 간 상관·대형주 쏠림이 X2(코어 50 + 업종 모멘텀 VT20 50)의 다음 달 초과수익을 설명하나, 그리고 그 변수가 낮을 때만 X2 를 들면 시장을 이기나. 규칙·판정은 SPEC.md(결과 전 고정).", "",
         "**판정:** " + " · ".join(f"{v}({VAR_LABELS[v]}) **{x}**" for v, x in res["verdicts"].items()), "",
         f"판정 기준({JUDGE_VERSION}): T1 = 1929~2007 X2 다음 달 초과를 변수 z 에 회귀한 기울기 < 0, 단측 p < {ALPHA:.4f}. "
         f"T3 = 변수가 과거 중앙값 아래일 때만 X2 — A·B 시장 + {MIN_EXCESS * 100:.0f}%p 이상, C(2008~) 지지 않음, MDD 5%p 이내, 1929~2007 월 초과 p < {ALPHA:.4f}.", ""]
    for v, x in res["variables"].items():
        s = x["slope"]
        L += [f"## {VAR_LABELS[v]}", "",
              f"- T1 설명: 기울기 {('—' if s['b'] is None else f'{s['b'] * 100:+.3f}%')}/z · t {('—' if s['t'] is None else f'{s['t']:.2f}')} · 단측 p "
              f"{('—' if s['p'] is None else f'{s['p']:.4f}')} · {s['n']}달 → {'✓' if x['T1'] else '✗'}",
              f"- 변수 평균: 1929~2007 {x['mean_pre2008']:.3f} · 2008~ {x['mean_post2008']:.3f} "
              f"({'2008 이후가 더 높음 — 소멸 방향과 맞음' if x['mean_post2008'] > x['mean_pre2008'] else '2008 이후가 더 낮음 — 소멸을 설명하지 못함'})",
              f"- 자료 마지막 달 {x['latest']['month']}: {x['latest']['value']:.3f} → {'과거 중앙값 아래(X2)' if x['latest']['below_median'] else '중앙값 위(시장)'}", "",
              "| 구간 | 세전 CAGR | 시장 | 초과 | MDD / 시장 | 교체 | X2 든 달 |", "|---|---|---|---|---|---|---|"]
        for e, label in (("A", "A 1929~1966"), ("B", "B 1967~2007"), ("C", "C 2008~")):
            d = x["switch"][e]
            L.append(f"| {label} | {_pct(d['cagr'])} | {_pct(d['mkt_cagr'])} | **{_pct(d['excess'])}** | {_pct(d['mdd'], 1)} / {_pct(d['mdd_mkt'], 1)} | {d['switches']} | {d['on_share'] * 100:.0f}% |")
        L += ["", f"T3 켜고 끄기: 1929~2007 월 초과 단측 p {('—' if x['switch_p'] is None else f'{x['switch_p']:.4f}')} → {'✓' if x['T3'] else '✗'}", ""]
    L += ["## 읽는 법", "",
          "- EXPLAINS_ONLY 는 변수가 X2 의 성과를 설명하지만 켜고 끄기로 시장을 이기지는 못했다는 뜻이다(국면 이해에는 쓰지만 전략은 아님).",
          "- 회귀는 자기상관 보정이 없는 단순 최소제곱이라 p 값이 낙관적일 수 있다. X2 재료는 1927~2007 로 골랐다.",
          "- 통과도 엔진 반영이 아니다. 전진 원장 후보이며 반영은 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    Path(a.checkpoint).mkdir(parents=True, exist_ok=True)
    mkt, ind, x2 = _cs().load(a.smoke)
    res = evaluate(mkt, ind, x2)
    res.update(rules=RULES_VERSION, judge=JUDGE_VERSION, smoke=bool(a.smoke))
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
