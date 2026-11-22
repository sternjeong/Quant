"""regime-playbook-v2 — v1 플레이북의 세금 누수(교체 실현)와 낙폭(2배 자리)을 고치면 세전 이득이 세후로 남나. 규칙·판정은 SPEC.md.

python research/jobs/regime-playbook-v2/run.py --out OUT --checkpoint CK [--smoke]
v1(research/jobs/regime-playbook-v1/run.py)의 자료·메뉴·국면 함수를 그대로 불러 쓴다. 계산은 수십 초라 체크포인트를 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RULES_VERSION = "regime-playbook/v2"
JUDGE_VERSION = "playbook2-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
PICKS_V1 = {"CALM_BULL": "SV", "NERVOUS_BULL": "L2", "QUIET_BEAR": "L2", "CRISIS": "LV"}   # v1 선택 시대(1929~1966) 결과
ERAS = {"selection": ("1929-01-01", "1966-12-31"), "B": ("1967-01-01", "2007-12-31"), "C": ("2008-01-01", None)}
JUDGED = ("B", "C")
VARIANTS = {
    "P_TAXFREE": {"account": "deferred", "hyst": False, "nolev": False},
    "P_HYST": {"account": "taxable", "hyst": True, "nolev": False},
    "P_NOLEV_HYST": {"account": "taxable", "hyst": True, "nolev": True},
    "P_NOLEV_TAXFREE": {"account": "deferred", "hyst": False, "nolev": True},
}
VARIANT_LABELS = {"P_TAXFREE": "과세 이연 계좌 · 매달 교체", "P_HYST": "일반 계좌 · 두 달 확인 뒤 교체",
                  "P_NOLEV_HYST": "일반 계좌 · 두 달 확인 · 2배 자리를 시장으로", "P_NOLEV_TAXFREE": "과세 이연 계좌 · 매달 · 2배 자리를 시장으로"}
TAX_TAXABLE = 0.22
TAX_DEFERRED_END = 0.055
GOAL_EXCESS = 0.07
USEFUL_EXCESS = 0.01
ALPHA = 0.05 / len(VARIANTS)
MDD_TOL = 0.05


def _v1():
    name = "regime_playbook_v1_run"
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "research" / "jobs" / "regime-playbook-v1" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 일정·계좌 (순수 함수)
def hysteresis(states: pd.Series) -> pd.Series:
    """새 국면이 두 달 연속일 때만 바꾼다(그 전에는 앞 국면 유지). 판정 불가(NaN) 달은 그대로 NaN."""
    out, cur, prev = [], None, None
    for s in states:
        if not isinstance(s, str):
            out.append(cur if cur is not None else s)
            prev = None
            continue
        if cur is None or (s == prev and s != cur):
            cur = s
        prev = s
        out.append(cur)
    return pd.Series(out, index=states.index, dtype=object)


def picks_for(nolev: bool) -> dict[str, str]:
    return {k: ("M" if nolev and v == "L2" else v) for k, v in PICKS_V1.items()}


def account(menu: pd.DataFrame, sched: pd.Series, kind: str) -> dict[str, Any]:
    """kind='taxable': v1 과 같은 근사(교체 때 실현, 연말 22%, 끝에 22% 청산). kind='deferred': 교체 세금 없음, 끝에 이익의 5.5%."""
    v1 = _v1()
    month = menu.index.to_period("M")
    pick = sched.reindex(month).fillna("M").to_numpy()
    r = menu.to_numpy()[np.arange(len(menu)), [v1.MENU.index(p) for p in pick]]
    first = np.r_[True, month[1:] != month[:-1]]
    prev = np.concatenate([pick[:1], pick[:-1]])
    sw = first & (pick != prev)
    sw[0] = False
    net = pd.Series(r - sw * 2 * v1.COST_ONE_WAY, index=menu.index)
    years = max((menu.index[-1] - menu.index[0]).days / 365.25, 1e-9)
    if kind == "deferred":
        v = float((1 + net).prod())
        v_end = v - TAX_DEFERRED_END * max(v - 1.0, 0.0)
    else:
        v, basis, realized, year = 1.0, 1.0, 0.0, menu.index[0].year
        for d, x, s in zip(menu.index, net.to_numpy(), sw):
            if d.year != year:
                tax = TAX_TAXABLE * max(realized, 0.0)
                if tax > 0:
                    basis *= (v - tax) / v
                    v -= tax
                realized, year = 0.0, d.year
            if s:
                realized += v - basis
                basis = v
            v *= 1 + x
        v_pre = v
        v -= TAX_TAXABLE * max(realized, 0.0)
        basis *= v / v_pre
        v_end = v - TAX_TAXABLE * max(v - basis, 0.0)
    return {"daily": net, "switches": int(sw.sum()), "cagr_pre": float((1 + net).prod() ** (1 / years) - 1),
            "cagr_after": float(max(v_end, 1e-12) ** (1 / years) - 1)}


def summarize(menu: pd.DataFrame, sched: pd.Series, kind: str) -> dict[str, Any]:
    v1 = _v1()
    acc = account(menu, sched, kind)
    mkt = account(menu, pd.Series("M", index=sched.index), kind)
    ex = (v1.monthly_returns(acc["daily"]) - v1.monthly_returns(menu["M"])).dropna()
    t, p = v1.one_sided(ex.to_numpy())
    ys = (1 + acc["daily"]).groupby(menu.index.year).prod() - (1 + menu["M"]).groupby(menu.index.year).prod()
    return {"cagr_pre": acc["cagr_pre"], "cagr_after": acc["cagr_after"], "mkt_cagr_pre": mkt["cagr_pre"], "mkt_cagr_after": mkt["cagr_after"],
            "excess_after": acc["cagr_after"] - mkt["cagr_after"], "excess_pre": acc["cagr_pre"] - mkt["cagr_pre"],
            "monthly_excess_mean": float(ex.mean()) if len(ex) else None, "t": t, "p": p,
            "mdd": v1.mdd(acc["daily"]), "mdd_mkt": v1.mdd(menu["M"]), "switches": acc["switches"],
            "years": int(len(ys)), "years_beat": int((ys > 0).sum()), "years_ge_goal": int((ys >= GOAL_EXCESS).sum())}


def judge(per: dict[str, dict]) -> str:
    if not all(e in per for e in JUDGED):
        return "FAIL"
    B, C = per["B"], per["C"]
    useful = (all(per[e]["excess_after"] >= USEFUL_EXCESS for e in JUDGED)
              and B["monthly_excess_mean"] is not None and B["monthly_excess_mean"] > 0 and B["p"] is not None and B["p"] < ALPHA
              and all(per[e]["mdd"] >= per[e]["mdd_mkt"] - MDD_TOL for e in JUDGED))
    if useful and all(per[e]["excess_after"] >= GOAL_EXCESS for e in JUDGED):
        return "GOAL_MET"
    return "USEFUL" if useful else "FAIL"


def evaluate(menu: pd.DataFrame) -> dict[str, Any]:
    v1 = _v1()
    menu = menu.dropna()
    st = v1.applied_states(v1.month_states(menu["M"]))
    res: dict[str, Any] = {"picks_v1": PICKS_V1, "variants": {}}
    for name, cfg in VARIANTS.items():
        states = hysteresis(st) if cfg["hyst"] else st
        picks = picks_for(cfg["nolev"])
        per = {}
        for e, (a, b) in ERAS.items():
            m = v1.era(menu, a, b)
            if m.empty:
                continue
            months = m.index.to_period("M").unique()
            per[e] = summarize(m, v1.schedule_from_playbook(states, picks, months), cfg["account"])
        res["variants"][name] = {"config": cfg, "picks": picks, "eras": per, "verdict": judge(per)}
    # 참고: v1 그대로(일반 계좌·매달·L2) — 같은 함수로 다시 계산해 v1 보고서와 맞는지 보는 기준
    per = {}
    for e, (a, b) in ERAS.items():
        m = v1.era(menu, a, b)
        if not m.empty:
            per[e] = summarize(m, v1.schedule_from_playbook(st, PICKS_V1, m.index.to_period("M").unique()), "taxable")
    res["reference_v1"] = per
    return res


# ---------------------------------------------------------------- 보고
def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def report(res: dict, smoke: bool) -> str:
    V = res["variants"]
    L = [f"# 플레이북 세금·낙폭 고치기 (regime-playbook-v2{' · 스모크' if smoke else ''})", "",
         "v1 의 국면별 메뉴(1929~1966 에서 고름)를 고정하고 계좌 종류·교체 규칙·2배 자리만 바꿨다. 규칙·판정은 결과 보기 전에 고정했다(SPEC.md).", "",
         "**판정:** " + " · ".join(f"{k}({VARIANT_LABELS[k]}) **{x['verdict']}**" for k, x in V.items()), "",
         f"판정 기준({JUDGE_VERSION}): B(1967~2007)·C(2008~) 모두 같은 계좌의 시장 대비 세후 초과 ≥ +{USEFUL_EXCESS * 100:.0f}%p, "
         f"B 월 초과 단측 p < {ALPHA:.4f}, 최대낙폭 B·C 모두 시장보다 {MDD_TOL * 100:.0f}%p 넘게 깊지 않음. GOAL_MET 은 B·C 모두 +{GOAL_EXCESS * 100:.0f}%p 이상.", "",
         "B·C 는 v1 에서 이미 한 번 본 자료다 — 결과는 낙관적으로 읽는다.", ""]
    titles = {"selection": "선택 시대 1929~1966 (보고만)", "B": "B 1967~2007 (판정)", "C": "C 2008~ (판정)"}
    for e, title in titles.items():
        L += [f"## {title}", "",
              "| 변형 | 세전 CAGR | 세후 CAGR | 같은 계좌 시장 세후 | 세후 초과 | 목표(+7%p)까지 | 월 초과 단측 p | MDD / 시장 | 교체 | 시장 이긴 해 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        rows = [(k, VARIANT_LABELS[k], x["eras"].get(e)) for k, x in V.items()] + [("v1", "참고: v1 그대로", res["reference_v1"].get(e))]
        for k, lab, x in rows:
            if not x:
                continue
            L.append(f"| {lab} | {_pct(x['cagr_pre'])} | {_pct(x['cagr_after'])} | {_pct(x['mkt_cagr_after'])} | **{_pct(x['excess_after'])}** | "
                     f"{_pct(GOAL_EXCESS - x['excess_after'])} | {'—' if x['p'] is None else f'{x['p']:.4f}'} | {_pct(x['mdd'], 1)} / {_pct(x['mdd_mkt'], 1)} | "
                     f"{x['switches']} | {x['years_beat']}/{x['years']} |")
        L.append("")
    L += ["## 읽는 법", "",
          "- 과세 이연 계좌는 한도(연금저축·IRP 합산 연 1,800만 원 납입)가 있어 목돈 전체에 쓸 수 없다. 5.5% 는 연금소득세 근사다.",
          "- 같은 계좌 종류의 시장과 비교한다. 과세 이연 계좌의 초과는 '그 계좌 안에서 시장 대신 플레이북을 굴리면'의 값이다.",
          "- 소형 가치 지수는 실제로 사기 어려운 초소형주 비중이 크다. 통과해도 실제 ETF 대체 확인이 먼저다.",
          "- USEFUL·GOAL_MET 도 엔진 채택이 아니다. 전진 원장 후보이며 엔진 반영은 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k != "daily"}
    return o


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    Path(a.checkpoint).mkdir(parents=True, exist_ok=True)
    v1 = _v1()
    res = evaluate(v1.load_smoke() if a.smoke else v1.load_real())
    res.update(rules=RULES_VERSION, judge=JUDGE_VERSION, smoke=bool(a.smoke), verdicts={k: x["verdict"] for k, x in res["variants"].items()})
    (out / "results.json").write_text(json.dumps(_strip(res), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
