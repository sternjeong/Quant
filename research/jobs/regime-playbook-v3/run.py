"""regime-playbook-v3 — 위기 칸(대형 가치)을 현금/시장으로 고치면 낙폭이 고쳐지나, 그리고 국면 교체가 같은 노출의 고정 비중보다 나은가.

python research/jobs/regime-playbook-v3/run.py --out OUT --checkpoint CK [--smoke]
v1(자료·메뉴·국면)과 v2(과세 이연 계좌)의 함수를 불러 쓴다. 규칙·판정은 SPEC.md. 계산은 수십 초라 체크포인트를 쓰지 않는다.
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

RULES_VERSION = "regime-playbook/v3"
JUDGE_VERSION = "playbook3-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
BASE_PICKS = {"CALM_BULL": "SV", "NERVOUS_BULL": "L2", "QUIET_BEAR": "L2"}
VARIANTS = {"Q_CRISIS_CASH": "CASH", "Q_CRISIS_MKT": "M"}
VARIANT_LABELS = {"Q_CRISIS_CASH": "위기 → 현금", "Q_CRISIS_MKT": "위기 → 시장"}
ERAS = {"selection": ("1929-01-01", "1966-12-31"), "B": ("1967-01-01", "2007-12-31"), "C": ("2008-01-01", None)}
JUDGED = ("B", "C")
USEFUL_EXCESS = 0.01
GOAL_EXCESS = 0.07
ALPHA = 0.05 / len(VARIANTS)
MDD_TOL = 0.05


def _load(name: str, rel: str):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _v1():
    return _load("regime_playbook_v1_run", "research/jobs/regime-playbook-v1/run.py")


def _v2():
    return _load("regime_playbook_v2_run", "research/jobs/regime-playbook-v2/run.py")


# ---------------------------------------------------------------- 순수 함수
def picks_for(crisis: str) -> dict[str, str]:
    return {**BASE_PICKS, "CRISIS": crisis}


def beta(r: pd.Series, mkt: pd.Series, rf: pd.Series) -> float:
    """월 초과수익 회귀 베타(일별 → 월별 복리)."""
    v1 = _v1()
    y = (v1.monthly_returns(r) - v1.monthly_returns(rf)).dropna()
    x = (v1.monthly_returns(mkt) - v1.monthly_returns(rf)).reindex(y.index)
    var = float(np.var(x, ddof=1))
    return float(np.cov(y, x, ddof=1)[0, 1] / var) if var > 0 else 1.0


def static_weights(b: float) -> dict[str, float]:
    """같은 노출 대조군: β 1~2 → 시장 (2−β) + 2배 (β−1), β<1 → 시장 β + 현금, β>2 → 2배 100%."""
    if b >= 2:
        return {"L2": 1.0}
    if b >= 1:
        return {"M": 2 - b, "L2": b - 1}
    return {"M": max(b, 0.0), "CASH": 1 - max(b, 0.0)}


def static_returns(menu: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """매달 첫 거래일에 목표 비중으로 되돌림(그 사이 표류), 비용 = 비중 차이 × 0.15%."""
    v1 = _v1()
    names = list(weights)
    R = menu[names].to_numpy()
    tgt = np.array([weights[k] for k in names])
    month = menu.index.to_period("M")
    first = np.r_[True, month[1:] != month[:-1]]
    h, out = tgt.copy(), np.zeros(len(menu))
    for i in range(len(menu)):
        g = h * (1 + R[i])
        out[i] = g.sum() - 1.0
        h = g / g.sum()
        if i + 1 < len(menu) and first[i + 1]:
            tv = float(np.abs(tgt - h).sum())
            out[i] -= tv * v1.COST_ONE_WAY * (1 + out[i])
            h = tgt.copy()
    return pd.Series(out, index=menu.index)


def deferred_cagr(r: pd.Series) -> float:
    v2 = _v2()
    years = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
    v = float((1 + r).prod())
    return float(max(v - v2.TAX_DEFERRED_END * max(v - 1.0, 0.0), 1e-12) ** (1 / years) - 1)


def judge(per: dict[str, dict]) -> str:
    if not all(e in per for e in JUDGED):
        return "FAIL"
    B = per["B"]
    a = all(per[e]["excess_vs_mkt"] >= USEFUL_EXCESS for e in JUDGED)
    c = all(per[e]["mdd"] >= per[e]["mdd_mkt"] - MDD_TOL for e in JUDGED)
    p_ok = B["monthly_excess_mean"] is not None and B["monthly_excess_mean"] > 0 and B["p"] is not None and B["p"] < ALPHA
    b = all(per[e]["excess_vs_static"] >= 0 for e in JUDGED)
    if a and c and p_ok:
        return "TIMING_HELPS" if b else "BETA_ONLY"
    return "FAIL"


def evaluate(menu: pd.DataFrame) -> dict[str, Any]:
    v1, v2 = _v1(), _v2()
    menu = menu.dropna()
    st = v1.applied_states(v1.month_states(menu["M"]))
    res: dict[str, Any] = {"variants": {}}
    for name, crisis in VARIANTS.items():
        picks = picks_for(crisis)
        sel = v1.era(menu, *ERAS["selection"])
        acc_sel = v2.account(sel, v1.schedule_from_playbook(st, picks, sel.index.to_period("M").unique()), "deferred")
        b_sel = beta(acc_sel["daily"], sel["M"], sel["CASH"])
        w = static_weights(b_sel)
        per = {}
        for e, (a, b) in ERAS.items():
            m = v1.era(menu, a, b)
            if m.empty:
                continue
            s = summ = v2.summarize(m, v1.schedule_from_playbook(st, picks, m.index.to_period("M").unique()), "deferred")
            stat = static_returns(m, w)
            static_after = deferred_cagr(stat)
            per[e] = {**summ, "excess_vs_mkt": s["excess_after"], "static_cagr_after": static_after,
                      "excess_vs_static": s["cagr_after"] - static_after, "mdd_static": v1.mdd(stat)}
        rec = {"crisis": crisis, "picks": picks, "beta_selection": b_sel, "static_weights": w, "eras": per, "verdict": judge(per)}
        rec["goal_met"] = all(per.get(e, {}).get("excess_vs_mkt", -1) >= GOAL_EXCESS for e in JUDGED)
        res["variants"][name] = rec
    return res


# ---------------------------------------------------------------- 보고
def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def report(res: dict, smoke: bool) -> str:
    V = res["variants"]
    L = [f"# 플레이북 위기 칸 고치기 + 타이밍 대 노출 (regime-playbook-v3{' · 스모크' if smoke else ''})", "",
         "과세 이연 계좌에서 v1 국면 메뉴의 위기 칸만 현금/시장으로 바꾸고, 같은 노출(선택 시대 베타)의 고정 비중과도 비교한다. 규칙·판정은 SPEC.md(결과 전 고정).", "",
         "**판정:** " + " · ".join(f"{k}({VARIANT_LABELS[k]}) **{x['verdict']}**{' · GOAL_MET' if x['goal_met'] else ''}" for k, x in V.items()), "",
         f"판정 기준({JUDGE_VERSION}): B(1967~2007)·C(2008~) 모두 같은 계좌 시장 대비 세후 ≥ +{USEFUL_EXCESS * 100:.0f}%p, 최대낙폭 시장보다 {MDD_TOL * 100:.0f}%p 넘게 "
         f"깊지 않음, B 월 초과 단측 p < {ALPHA:.3f} — 여기에 같은 노출 대조군에도 지지 않으면 TIMING_HELPS, 지면 BETA_ONLY.", "",
         "B·C 는 v1·v2 에서 이미 두 번 본 자료다 — 통과도 강한 증거가 아니다.", ""]
    for k, x in V.items():
        L.append(f"- {k}: 선택 시대 베타 {x['beta_selection']:.2f} → 대조군 " + " + ".join(f"{a} {b * 100:.0f}%" for a, b in x["static_weights"].items()))
    L.append("")
    titles = {"selection": "선택 시대 1929~1966 (보고만)", "B": "B 1967~2007 (판정)", "C": "C 2008~ (판정)"}
    for e, title in titles.items():
        L += [f"## {title}", "",
              "| 변형 | 세전 CAGR | 세후 CAGR | 시장 세후 | 대 시장 | 같은 노출 대조군 세후 | 대 대조군 | 목표(+7%p)까지 | 월 초과 p | MDD / 시장 / 대조군 | 교체 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, x in V.items():
            d = x["eras"].get(e)
            if not d:
                continue
            L.append(f"| {VARIANT_LABELS[k]} | {_pct(d['cagr_pre'])} | {_pct(d['cagr_after'])} | {_pct(d['mkt_cagr_after'])} | **{_pct(d['excess_vs_mkt'])}** | "
                     f"{_pct(d['static_cagr_after'])} | **{_pct(d['excess_vs_static'])}** | {_pct(GOAL_EXCESS - d['excess_vs_mkt'])} | "
                     f"{'—' if d['p'] is None else f'{d['p']:.4f}'} | {_pct(d['mdd'], 1)} / {_pct(d['mdd_mkt'], 1)} / {_pct(d['mdd_static'], 1)} | {d['switches']} |")
        L.append("")
    L += ["## 읽는 법", "",
          "- '대 대조군'이 음수면 국면 교체 없이 같은 평균 노출(시장 + 2배 고정 비중)만으로 같거나 더 벌었다는 뜻이다 — 이득은 타이밍이 아니라 노출의 값.",
          "- 과세 이연 계좌는 한도(연금저축·IRP 합산 연 1,800만 원 납입)가 있고 5.5% 는 연금소득세 근사다.",
          "- 통과도 엔진·계좌 반영이 아니다. 전진 원장 후보이며 반영은 사용자 확인 뒤 별도 작업이다."]
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
