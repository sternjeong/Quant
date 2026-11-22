"""regime-playbook-intl-v1 — v3 플레이북(위기 → 현금/시장)을 얼려 처음 보는 해외 시장(유럽·일본·아시아태평양)에서 확인. 규칙·판정은 SPEC.md.

python research/jobs/regime-playbook-intl-v1/run.py --out OUT --checkpoint CK [--smoke]
v1(국면·메뉴)·v2(과세 이연 계좌)·v3(고정 비중 대조군) 함수를 불러 쓴다. 계산은 수 분 안이라 체크포인트를 쓰지 않는다.
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

RULES_VERSION = "regime-playbook-intl/v1"
JUDGE_VERSION = "playbook-intl-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
VARIANTS = {
    "Q_CRISIS_CASH": {"picks": {"CALM_BULL": "SV", "NERVOUS_BULL": "L2", "QUIET_BEAR": "L2", "CRISIS": "CASH"},
                      "static": {"M": 0.8420935579439377, "CASH": 0.1579064420560623}},
    "Q_CRISIS_MKT": {"picks": {"CALM_BULL": "SV", "NERVOUS_BULL": "L2", "QUIET_BEAR": "L2", "CRISIS": "M"},
                     "static": {"M": 0.624735540982555, "L2": 0.375264459017445}},
}
VARIANT_LABELS = {"Q_CRISIS_CASH": "위기 → 현금", "Q_CRISIS_MKT": "위기 → 시장"}
JUDGED_REGIONS = {"Europe": "유럽", "Japan": "일본", "Asia_Pacific_ex_Japan": "아시아태평양(일본 제외)"}
REPORT_REGIONS = {"Developed_ex_US": "선진국(미국 제외, 앞 3곳과 겹침)", "North_America": "북미(미국과 겹침)"}
EVAL_START = "1993-01-01"
MIN_REGIONS = 2
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


def _v3():
    return _load("regime_playbook_v3_run", "research/jobs/regime-playbook-v3/run.py")


# ---------------------------------------------------------------- 자료
def region_menu(mkt: pd.Series, rf: pd.Series, sv: pd.Series, lv: pd.Series) -> pd.DataFrame:
    """v1 메뉴 틀을 그대로 쓴다. 대형 승자·방어 산업은 이 연구에서 쓰지 않아 시장으로 채운다."""
    lab = _v1()._lab()
    wk = lambda s: lab.to_weekdays(s.astype(float))  # noqa: E731
    m, r = wk(mkt), wk(rf)
    return _v1().build_menu(m, r, m, wk(sv), wk(lv), m).dropna()


def load_region(key: str) -> pd.DataFrame:
    from core import french_factors as ff

    k3, k25 = f"intl_{key}_3", f"intl_{key}_25"
    ff.DATASETS.setdefault(k3, f"{key}_3_Factors_Daily_CSV.zip")
    ff.DATASETS.setdefault(k25, f"{key}_25_Portfolios_ME_BE-ME_Daily_CSV.zip")
    f3, p25 = ff.load(k3), ff.load(k25)
    if f3 is None or p25 is None or "BIG HiBM" not in p25 or "SMALL HiBM" not in p25:
        raise RuntimeError(f"Ken French {key} 자료를 받지 못함")
    idx = f3.index.intersection(p25.index).sort_values()
    return region_menu((f3["Mkt-RF"] + f3["RF"]).reindex(idx), f3["RF"].reindex(idx), p25["SMALL HiBM"].reindex(idx), p25["BIG HiBM"].reindex(idx))


def synthetic_region(seed: int) -> pd.DataFrame:
    idx = pd.bdate_range("1990-07-02", "2026-08-31")
    r = np.random.default_rng(seed)
    n = len(idx)
    drift = np.full(n, 0.0003)
    for a, b in (("2000-03-01", "2003-03-31"), ("2008-06-01", "2009-03-09"), ("2020-02-20", "2020-03-23")):
        drift[(idx >= a) & (idx <= b)] = -0.002
    ex = drift + r.normal(0, 0.011, n)
    rf = pd.Series(0.0001, index=idx)
    mkt = pd.Series(ex, index=idx) + rf
    sv = rf + 1.1 * ex + r.normal(0, 0.006, n)
    lv = rf + 1.0 * ex + r.normal(0, 0.005, n)
    return region_menu(mkt, rf, pd.Series(sv, index=idx), pd.Series(lv, index=idx))


# ---------------------------------------------------------------- 평가
def eval_region(menu: pd.DataFrame) -> dict[str, Any]:
    v1, v2, v3 = _v1(), _v2(), _v3()
    st = v1.applied_states(v1.month_states(menu["M"]))
    m = menu.loc[EVAL_START:]
    months = m.index.to_period("M").unique()
    out = {"start": str(m.index[0].date()), "end": str(m.index[-1].date()),
           "state_share": {s: float((st.reindex(months) == s).mean()) for s in v1.STATES}, "variants": {}}
    for name, cfg in VARIANTS.items():
        sched = v1.schedule_from_playbook(st, cfg["picks"], months)
        s = v2.summarize(m, sched, "deferred")
        acc = v2.account(m, sched, "deferred")
        stat = v3.static_returns(m, cfg["static"])
        st_after = v3.deferred_cagr(stat)
        mx = (v1.monthly_returns(acc["daily"]) - v1.monthly_returns(m["M"])).dropna()
        out["variants"][name] = {**s, "static_cagr_after": st_after, "excess_vs_static": s["cagr_after"] - st_after,
                                 "mdd_static": v1.mdd(stat), "monthly_excess": {str(k): float(v) for k, v in mx.items()},
                                 "region_pass": bool(s["excess_after"] >= USEFUL_EXCESS and s["mdd"] >= s["mdd_mkt"] - MDD_TOL)}
    return out


def pooled_test(regions: dict[str, dict], name: str) -> tuple[Optional[float], Optional[float], int]:
    series = [pd.Series(r["variants"][name]["monthly_excess"]) for r in regions.values()]
    if not series:
        return None, None, 0
    pooled = pd.concat(series, axis=1).dropna().mean(axis=1)
    t, p = _v1().one_sided(pooled.to_numpy())
    return t, p, int(len(pooled))


def evaluate(judged: dict[str, pd.DataFrame], reported: dict[str, pd.DataFrame]) -> dict[str, Any]:
    J = {k: eval_region(v) for k, v in judged.items()}
    R = {k: eval_region(v) for k, v in reported.items()}
    verdicts, pooled = {}, {}
    for name in VARIANTS:
        t, p, n = pooled_test(J, name)
        mean = float(np.mean([np.mean(list(r["variants"][name]["monthly_excess"].values())) for r in J.values()])) if J else None
        wins = sum(r["variants"][name]["region_pass"] for r in J.values())
        pooled[name] = {"t": t, "p": p, "months": n, "regions_pass": wins}
        ok = wins >= MIN_REGIONS and t is not None and t > 0 and p is not None and p < ALPHA and mean is not None and mean > 0
        verdicts[name] = "HOLDS_ABROAD" if ok else "FAIL"
    return {"judged": J, "reported": R, "pooled": pooled, "verdicts": verdicts}


# ---------------------------------------------------------------- 보고
def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x * 100:+.{nd}f}%"


def report(res: dict, smoke: bool) -> str:
    L = [f"# 플레이북 해외 확인 (regime-playbook-intl-v1{' · 스모크' if smoke else ''})", "",
         "regime-playbook-v3 의 규칙·대조군 비중을 그대로 얼려, 한 번도 쓰지 않은 해외 시장(1993~)에서 같은 성질이 나오는지 본다. 규칙·판정은 SPEC.md(결과 전 고정).", "",
         "**판정:** " + " · ".join(f"{k}({VARIANT_LABELS[k]}) **{v}**" for k, v in res["verdicts"].items()), "",
         f"판정 기준({JUDGE_VERSION}): 유럽·일본·아시아태평양 중 {MIN_REGIONS}곳 이상에서 그 지역 시장 대비 세후 ≥ +{USEFUL_EXCESS * 100:.0f}%p 이고 최대낙폭이 "
         f"{MDD_TOL * 100:.0f}%p 넘게 깊지 않음, 그리고 3지역 평균 월 초과 단측 p < {ALPHA:.3f}.", "",
         "| 변형 | 통과 지역 수 | 3지역 평균 월 초과 t / 단측 p | 달 수 |", "|---|---|---|---|"]
    for k, x in res["pooled"].items():
        L.append(f"| {VARIANT_LABELS[k]} | {x['regions_pass']}/{len(res['judged'])} | {'—' if x['t'] is None else f'{x['t']:.2f}'} / "
                 f"{'—' if x['p'] is None else f'{x['p']:.4f}'} | {x['months']} |")
    L.append("")
    for group, names, title in (("judged", JUDGED_REGIONS, "판정 지역"), ("reported", REPORT_REGIONS, "보고만")):
        for key, r in res[group].items():
            L += [f"## {names[key]} ({title}, {r['start']} ~ {r['end']})", "",
                  "국면 비율: " + ", ".join(f"{_v1().STATE_LABELS[s].split('(')[0]} {v * 100:.0f}%" for s, v in r["state_share"].items()), "",
                  "| 변형 | 세전 CAGR | 세후 CAGR | 시장 세후 | 대 시장 | 목표(+7%p)까지 | 같은 베타 대조군 세후 | 대 대조군 | MDD / 시장 / 대조군 | 교체 | 지역 통과 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
            for k, x in r["variants"].items():
                L.append(f"| {VARIANT_LABELS[k]} | {_pct(x['cagr_pre'])} | {_pct(x['cagr_after'])} | {_pct(x['mkt_cagr_after'])} | **{_pct(x['excess_after'])}** | "
                         f"{_pct(GOAL_EXCESS - x['excess_after'])} | {_pct(x['static_cagr_after'])} | {_pct(x['excess_vs_static'])} | "
                         f"{_pct(x['mdd'], 1)} / {_pct(x['mdd_mkt'], 1)} / {_pct(x['mdd_static'], 1)} | {x['switches']} | {'✓' if x['region_pass'] else '✗'} |")
            L.append("")
    L += ["## 읽는 법", "",
          "- 규칙은 미국 자료에서 정했고 여기서는 한 글자도 바꾸지 않았다. 해외에서도 성질이 나오면 미국 자료 재사용에 따른 과적합 걱정이 줄어든다.",
          "- '대 대조군'은 같은 평균 노출의 고정 비중 대비 — 양수면 국면 타이밍의 값이다.",
          "- 달러 기준 수익이라 환율 효과가 섞인다. 지역 소형 가치는 실제로 사기 어려운 작은 종목 비중이 크다.",
          "- HOLDS_ABROAD 도 엔진·계좌 반영이 아니다. 전진 원장 후보이며 반영은 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in ("daily", "monthly_excess")}
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
    if a.smoke:
        judged = {k: synthetic_region(11 + i) for i, k in enumerate(JUDGED_REGIONS)}
        reported = {k: synthetic_region(31 + i) for i, k in enumerate(REPORT_REGIONS)}
    else:
        judged = {k: load_region(k) for k in JUDGED_REGIONS}
        reported = {k: load_region(k) for k in REPORT_REGIONS}
    res = evaluate(judged, reported)
    res.update(rules=RULES_VERSION, judge=JUDGE_VERSION, smoke=bool(a.smoke))
    (out / "results.json").write_text(json.dumps(_strip(res), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
