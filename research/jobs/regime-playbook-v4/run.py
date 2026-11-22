"""regime-playbook-v4 — 얼린 '위기 → 현금' 플레이북의 이득이 타이밍인가 평균 메뉴(소형 가치·2배)인가, 그리고 실제 ETF(SPY·IJS·SSO·BIL)로도 되나.

python research/jobs/regime-playbook-v4/run.py --out OUT --checkpoint CK [--smoke]
v1(국면·메뉴)·v2(과세 이연 계좌)·v3(고정 비중)·intl(지역 자료) 함수를 불러 쓴다. 규칙·판정은 SPEC.md.
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

RULES_VERSION = "regime-playbook/v4"
JUDGE_VERSION = "playbook4-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
PICKS = {"CALM_BULL": "SV", "NERVOUS_BULL": "L2", "QUIET_BEAR": "L2", "CRISIS": "CASH"}
US_SELECTION = ("1929-01-01", "1966-12-31")
US_SETS = {"US_B": ("1967-01-01", "2007-12-31"), "US_C": ("2008-01-01", None)}
REGION_SETS = {"Europe": "유럽", "Japan": "일본", "Asia_Pacific_ex_Japan": "아시아태평양(일본 제외)"}
SET_LABELS = {"US_B": "미국 1967~2007", "US_C": "미국 2008~", **REGION_SETS}
MIN_SETS = 4
ETF_START = "2001-01-01"
ETF_TICKERS = {"M": "SPY", "SV": "IJS", "L2": "SSO", "CASH": "BIL"}
SSO_START, BIL_START = "2006-06-21", "2007-05-30"
L2_FEE = 0.009
TAX_ISA_END = 0.099
USEFUL_EXCESS = 0.01
ALPHA = 0.05 / 2
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


def _intl():
    return _load("regime_playbook_intl_v1_run", "research/jobs/regime-playbook-intl-v1/run.py")


# ---------------------------------------------------------------- A. 분해
def menu_weights(us_menu: pd.DataFrame) -> dict[str, float]:
    """미국 선택 시대 국면 비율 → 같은 평균 메뉴 비중(결과를 보기 전에 정해지는 값)."""
    v1 = _v1()
    st = v1.applied_states(v1.month_states(us_menu["M"]))
    months = v1.era(us_menu, *US_SELECTION).index.to_period("M").unique()
    share = st.reindex(months).value_counts(normalize=True)
    w: dict[str, float] = {}
    for s, k in PICKS.items():
        w[k] = w.get(k, 0.0) + float(share.get(s, 0.0))
    tot = sum(w.values())
    return {k: v / tot for k, v in w.items() if v > 0}


def decompose(menu: pd.DataFrame, weights: dict[str, float], start: str, end: Optional[str]) -> dict[str, Any]:
    v1, v2, v3 = _v1(), _v2(), _v3()
    st = v1.applied_states(v1.month_states(menu["M"]))
    m = v1.era(menu, start, end)
    sched = v1.schedule_from_playbook(st, PICKS, m.index.to_period("M").unique())
    acc = v2.account(m, sched, "deferred")
    stat = v3.static_returns(m, weights)
    diff = (v1.monthly_returns(acc["daily"]) - v1.monthly_returns(stat)).dropna()
    pb, sm = acc["cagr_after"], v3.deferred_cagr(stat)
    return {"start": str(m.index[0].date()), "end": str(m.index[-1].date()), "playbook_after": pb, "menu_after": sm,
            "mkt_after": v3.deferred_cagr(m["M"]), "beyond_menu": pb - sm, "mdd": v1.mdd(acc["daily"]), "mdd_menu": v1.mdd(stat),
            "monthly_diff": {str(k): float(v) for k, v in diff.items()}}


def judge_a(sets: dict[str, dict]) -> tuple[str, dict]:
    wins = sum(1 for x in sets.values() if x["beyond_menu"] >= 0)
    regional = [pd.Series(sets[k]["monthly_diff"]) for k in REGION_SETS if k in sets]
    pooled = pd.concat(regional, axis=1).dropna().mean(axis=1) if regional else pd.Series(dtype=float)
    t, p = _v1().one_sided(pooled.to_numpy()) if len(pooled) else (None, None)
    ok = wins >= MIN_SETS and t is not None and t > 0 and p is not None and p < ALPHA
    return ("TIMING_BEYOND_MENU" if ok else "MENU_ONLY"), {"wins": wins, "sets": len(sets), "t": t, "p": p, "months": int(len(pooled))}


# ---------------------------------------------------------------- B. 실제 ETF
def etf_menu(prices: dict[str, pd.Series], rf: pd.Series) -> pd.DataFrame:
    """일수익 메뉴. SSO·BIL 상장 전은 합성(SPY 2배 − 현금 − 보수, Ken French RF)."""
    spy = prices["SPY"].pct_change()
    idx = spy.dropna().index
    rf = rf.reindex(idx).ffill().fillna(0.0)
    l2_syn = 2 * (spy.reindex(idx) - rf) + rf - L2_FEE / 252
    sso = prices["SSO"].pct_change().reindex(idx) if "SSO" in prices else pd.Series(np.nan, index=idx)
    bil = prices["BIL"].pct_change().reindex(idx) if "BIL" in prices else pd.Series(np.nan, index=idx)
    l2 = l2_syn.where(idx < pd.Timestamp(SSO_START), sso).fillna(l2_syn)
    cash = rf.where(idx < pd.Timestamp(BIL_START), bil).fillna(rf)
    sv = prices["IJS"].pct_change().reindex(idx)
    m = spy.reindex(idx)
    return _v1().build_menu(m, cash, m, sv, m, m).assign(L2=l2).dropna()


def eval_etf(menu: pd.DataFrame) -> dict[str, Any]:
    v1, v2, v3 = _v1(), _v2(), _v3()
    st = v1.applied_states(v1.month_states(menu["M"]))
    m = menu.loc[ETF_START:]
    sched = v1.schedule_from_playbook(st, PICKS, m.index.to_period("M").unique())
    s = v2.summarize(m, sched, "deferred")
    acc = v2.account(m, sched, "deferred")
    years = max((m.index[-1] - m.index[0]).days / 365.25, 1e-9)
    isa = lambda r: float(max((g := float((1 + r).prod())) - TAX_ISA_END * max(g - 1, 0), 1e-12) ** (1 / years) - 1)  # noqa: E731
    yr = ((1 + acc["daily"]).groupby(m.index.year).prod() - (1 + m["M"]).groupby(m.index.year).prod())
    verdict = "ETF_HOLDS" if s["excess_after"] >= USEFUL_EXCESS and s["mdd"] >= s["mdd_mkt"] - MDD_TOL else "FAIL"
    return {**s, "start": str(m.index[0].date()), "end": str(m.index[-1].date()), "isa_after": isa(acc["daily"]), "isa_mkt": isa(m["M"]),
            "yearly_excess": {int(k): float(v) for k, v in yr.items()}, "verdict": verdict,
            "ijs_cagr": float((1 + m["SV"]).prod() ** (1 / years) - 1), "spy_cagr_pre": float((1 + m["M"]).prod() ** (1 / years) - 1)}


def fetch_etf_prices() -> dict[str, pd.Series]:
    from core.market_data import get_price_history

    out = {}
    for tk in ETF_TICKERS.values():
        df = get_price_history(tk, start="1999-01-01", interval="1d")
        if df is None or df.empty:
            continue
        col = "Adj Close" if "Adj Close" in df.columns else "Close"
        s = df[col]
        out[tk] = (s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s).astype(float).dropna()
    if "SPY" not in out or "IJS" not in out:
        raise RuntimeError("SPY·IJS 가격을 받지 못함")
    out = {k: v.set_axis(pd.DatetimeIndex(v.index).tz_localize(None).normalize()) for k, v in out.items()}
    return out


def synthetic_etf(seed: int = 3) -> tuple[dict[str, pd.Series], pd.Series]:
    idx = pd.bdate_range("1999-01-04", "2026-11-20")
    r = np.random.default_rng(seed)
    ex = r.normal(0.0003, 0.012, len(idx))
    for a, b in (("2000-09-01", "2002-10-09"), ("2008-09-01", "2009-03-09"), ("2020-02-20", "2020-03-23")):
        ex[(idx >= a) & (idx <= b)] -= 0.003
    rf = pd.Series(0.0001, index=idx)
    spy = pd.Series(100 * np.cumprod(1 + ex + 0.0001), index=idx)
    ijs = pd.Series(100 * np.cumprod(1 + 1.1 * ex + 0.0002 + r.normal(0, 0.005, len(idx))), index=idx)
    sso = pd.Series(100 * np.cumprod(1 + 2 * ex + 0.0001 - 0.009 / 252), index=idx)[SSO_START:]
    bil = pd.Series(100 * np.cumprod(1 + rf.to_numpy()), index=idx)[BIL_START:]
    return {"SPY": spy, "IJS": ijs, "SSO": sso, "BIL": bil}, rf


# ---------------------------------------------------------------- 실행
def evaluate(us_menu: pd.DataFrame, regions: dict[str, pd.DataFrame], etf_prices: dict[str, pd.Series], etf_rf: pd.Series) -> dict[str, Any]:
    us_menu = us_menu.dropna()
    w = menu_weights(us_menu)
    sets = {k: decompose(us_menu, w, a, b) for k, (a, b) in US_SETS.items()}
    for k, menu in regions.items():
        sets[k] = decompose(menu, w, _intl().EVAL_START, None)
    va, info = judge_a(sets)
    etf = eval_etf(etf_menu(etf_prices, etf_rf))
    return {"menu_weights": w, "decomposition": sets, "a_info": info, "etf": etf,
            "verdicts": {"A_decomposition": va, "B_etf": etf["verdict"]}}


def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x * 100:+.{nd}f}%"


def report(res: dict, smoke: bool) -> str:
    v, e, ai = res["verdicts"], res["etf"], res["a_info"]
    L = [f"# 플레이북 분해 + 실제 ETF (regime-playbook-v4{' · 스모크' if smoke else ''})", "",
         "얼린 '위기 → 현금' 플레이북(과세 이연 계좌)의 이득이 국면 타이밍인지 평균 메뉴(소형 가치·2배) 보유의 값인지, 그리고 실제 ETF 로도 되는지. 규칙·판정은 SPEC.md(결과 전 고정).", "",
         f"**판정:** A 분해 **{v['A_decomposition']}** · B 실제 ETF **{v['B_etf']}**", "",
         "같은 평균 메뉴 비중(미국 1929~1966 국면 비율): " + " + ".join(f"{k} {x * 100:.0f}%" for k, x in res["menu_weights"].items()), "",
         f"## A. 타이밍 대 평균 메뉴 — 플레이북 ≥ 고정 메뉴인 묶음 {ai['wins']}/{ai['sets']} (필요 {MIN_SETS}), 해외 3지역 월 차이 t {('—' if ai['t'] is None else f'{ai['t']:.2f}')} / 단측 p "
         f"{('—' if ai['p'] is None else f'{ai['p']:.4f}')} (필요 < {ALPHA:.3f})", "",
         "| 묶음 | 기간 | 플레이북 세후 | 고정 메뉴 세후 | 시장 세후 | 플레이북 − 고정 메뉴 | MDD 플레이북 / 고정 메뉴 |", "|---|---|---|---|---|---|---|"]
    for k, x in res["decomposition"].items():
        L.append(f"| {SET_LABELS[k]} | {x['start']} ~ {x['end']} | {_pct(x['playbook_after'])} | {_pct(x['menu_after'])} | {_pct(x['mkt_after'])} | "
                 f"**{_pct(x['beyond_menu'])}** | {_pct(x['mdd'], 1)} / {_pct(x['mdd_menu'], 1)} |")
    L += ["", f"## B. 실제 ETF (SPY·IJS·SSO·BIL, {e['start']} ~ {e['end']})", "",
          "| | 세전 CAGR | 과세 이연 세후 | ISA 형 세후 근사 | MDD | 교체 |", "|---|---|---|---|---|---|",
          f"| 플레이북 | {_pct(e['cagr_pre'])} | {_pct(e['cagr_after'])} | {_pct(e['isa_after'])} | {_pct(e['mdd'], 1)} | {e['switches']} |",
          f"| SPY 그냥 보유 | {_pct(e['spy_cagr_pre'])} | {_pct(e['mkt_cagr_after'])} | {_pct(e['isa_mkt'])} | {_pct(e['mdd_mkt'], 1)} | 0 |", "",
          f"세후 초과(과세 이연) **{_pct(e['excess_after'])}** · 시장 이긴 해 {e['years_beat']}/{e['years']} · 참고: IJS 그냥 보유 세전 {_pct(e['ijs_cagr'])}", "",
          "연도별 세전 초과: " + ", ".join(f"{y} {_pct(x, 1)}" for y, x in e["yearly_excess"].items()), "",
          "## 읽는 법", "",
          "- A 가 MENU_ONLY 면 이득은 국면 교체가 아니라 '평균적으로 소형 가치·2배를 들고 있던 것'의 값이다 — 그 경우 고정 비중이 더 단순하고 세금·교체 부담이 적다.",
          "- B 는 2001 이후라 미국 2008~ 구간과 겹친다. 새 증거라기보다 실제 상품으로 옮길 수 있는지 확인이다.",
          "- 연금저축·IRP 는 레버리지 ETF 를 살 수 없는 것으로 알려져 있다 — 2배 칸이 있는 이 플레이북은 계좌 구조 검토가 먼저다.",
          "- 통과도 엔진·계좌 반영이 아니다. 전진 원장 후보이며 반영은 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in ("daily", "monthly_diff")}
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
    v1, intl = _v1(), _intl()
    if a.smoke:
        us = v1.load_smoke()
        regions = {k: intl.synthetic_region(11 + i) for i, k in enumerate(REGION_SETS)}
        prices, rf = synthetic_etf()
    else:
        us = v1.load_real()
        regions = {k: intl.load_region(k) for k in REGION_SETS}
        prices, rf = fetch_etf_prices(), us["CASH"]
    res = evaluate(us, regions, prices, rf)
    res.update(rules=RULES_VERSION, judge=JUDGE_VERSION, smoke=bool(a.smoke))
    (out / "results.json").write_text(json.dumps(_strip(res), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
