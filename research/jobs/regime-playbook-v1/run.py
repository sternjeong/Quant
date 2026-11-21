"""regime-playbook-v1 — 국면(추세×변동성)마다 다른 메뉴를 들고 가면 시장을 크게 이기나. 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/regime-playbook-v1/run.py --out OUT --checkpoint CK [--smoke]
계산은 수십 초라 체크포인트를 쓰지 않는다(계약상 인자만 받는다).
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

RULES_VERSION = "regime-playbook/v1"
JUDGE_VERSION = "playbook-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
ERAS = {"selection": ("1929-01-01", "1966-12-31"), "confirmation": ("1967-01-01", "2007-12-31"),
        "report_2008": ("2008-01-01", None)}
MENU = ("M", "CASH", "L2", "MOM", "SV", "LV", "DEF")
MENU_LABELS = {"M": "시장", "CASH": "현금", "L2": "합성 2배", "MOM": "대형 승자", "SV": "소형 가치", "LV": "대형 가치", "DEF": "방어 산업"}
STATES = ("CALM_BULL", "NERVOUS_BULL", "QUIET_BEAR", "CRISIS")
STATE_LABELS = {"CALM_BULL": "조용한 강세(200일선 위·변동성 낮음)", "NERVOUS_BULL": "불안한 강세(200일선 위·변동성 높음)",
                "QUIET_BEAR": "조용한 약세(200일선 아래·변동성 낮음)", "CRISIS": "위기(200일선 아래·변동성 높음)"}
MA_DAYS, VOL_DAYS, VOL_MIN_MONTHS = 200, 21, 24
MIN_STATE_MONTHS = 24
L2_FEE = 0.009
COST_ONE_WAY = 0.0015
TAX = 0.22
GOAL_EXCESS = 0.07
USEFUL_EXCESS = 0.01
ALPHA = 0.05
LOCAL_ALPHA = 0.05 / len(STATES)
MDD_TOL = 0.05


def _lab():
    spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research" / "jobs" / "core-longrun-v1" / "lab.py")
    mod = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(spec))
    if not hasattr(mod, "to_weekdays"):
        spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 메뉴·국면 (순수 함수)
def build_menu(mkt: pd.Series, rf: pd.Series, mom: pd.Series, sv: pd.Series, lv: pd.Series, defensive: pd.Series) -> pd.DataFrame:
    l2 = 2 * (mkt - rf) + rf - L2_FEE / 252
    return pd.DataFrame({"M": mkt, "CASH": rf, "L2": l2, "MOM": mom, "SV": sv, "LV": lv, "DEF": defensive})


def month_states(mkt: pd.Series) -> pd.Series:
    """월말(그 달 마지막 거래일) 종가로 정한 국면. 인덱스 = 월(Period). 판정 불가 달은 NaN."""
    wealth = (1 + mkt).cumprod()
    ma = wealth.rolling(MA_DAYS, min_periods=MA_DAYS).mean()
    vol = mkt.rolling(VOL_DAYS, min_periods=VOL_DAYS).std() * math.sqrt(252)
    month = mkt.index.to_period("M")
    last = pd.Series(np.arange(len(mkt)), index=mkt.index).groupby(month).max().to_numpy()
    w_m, ma_m, vol_m = wealth.iloc[last], ma.iloc[last], vol.iloc[last]
    periods = month.unique()
    med = pd.Series(vol_m.to_numpy(), index=periods).expanding(min_periods=VOL_MIN_MONTHS).median()
    up = pd.Series(w_m.to_numpy() > ma_m.to_numpy(), index=periods)
    hi = pd.Series(vol_m.to_numpy() > med.to_numpy(), index=periods)
    ok = pd.Series(ma_m.notna().to_numpy() & med.notna().to_numpy(), index=periods)
    lab = np.where(up, np.where(hi, "NERVOUS_BULL", "CALM_BULL"), np.where(hi, "CRISIS", "QUIET_BEAR"))
    return pd.Series(lab, index=periods).where(ok)


def applied_states(states: pd.Series) -> pd.Series:
    """m 달 말 국면 → m+1 달에 적용."""
    s = states.copy()
    s.index = s.index + 1
    return s


def monthly_returns(daily: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return (1 + daily).groupby(daily.index.to_period("M")).prod() - 1


def choose_playbook(mret: pd.DataFrame, st: pd.Series) -> dict[str, Any]:
    """국면마다 '메뉴 월 수익 − 시장' 평균이 가장 큰 메뉴. 국면 달 < MIN_STATE_MONTHS 면 M."""
    st = st.reindex(mret.index)
    out = {}
    for s in STATES:
        rows = mret[st == s]
        if len(rows) < MIN_STATE_MONTHS:
            out[s] = {"pick": "M", "months": int(len(rows)), "excess": {}}
            continue
        ex = rows.sub(rows["M"], axis=0).mean()
        out[s] = {"pick": str(ex.idxmax()), "months": int(len(rows)), "excess": {k: float(v) for k, v in ex.items()}}
    return out


def schedule_from_playbook(st: pd.Series, picks: dict[str, str], months: pd.PeriodIndex) -> pd.Series:
    st = st.reindex(months)
    return pd.Series([picks.get(x, "M") if isinstance(x, str) else "M" for x in st], index=months)


def run_account(menu: pd.DataFrame, sched: pd.Series) -> dict[str, Any]:
    """월별 메뉴 일정(sched: Period → 메뉴)대로 일별 보유. 바뀌는 달 첫날 비용, 세금 근사(SPEC)."""
    month = menu.index.to_period("M")
    pick = sched.reindex(month).fillna("M").to_numpy()
    r = menu.to_numpy()[np.arange(len(menu)), [MENU.index(p) for p in pick]]
    switch_day = np.zeros(len(menu), dtype=bool)
    first = np.r_[True, month[1:] != month[:-1]]
    prev = np.concatenate([pick[:1], pick[:-1]])
    switch_day[first & (pick != prev)] = True
    switch_day[0] = False
    gross = pd.Series(r, index=menu.index)
    net = gross - switch_day * 2 * COST_ONE_WAY
    # 세금 근사 계좌(1 에서 시작)
    v, basis, realized, year = 1.0, 1.0, 0.0, menu.index[0].year
    after = np.empty(len(menu))
    for i, (d, x) in enumerate(zip(menu.index, net.to_numpy())):
        if d.year != year:
            tax = TAX * max(realized, 0.0)
            if tax > 0:
                basis *= (v - tax) / v
                v -= tax
            realized, year = 0.0, d.year
        if switch_day[i]:
            realized += v - basis
            basis = v
        v *= 1 + x
        after[i] = v
    final_tax = TAX * max(realized, 0.0)
    v_end = v - final_tax
    v_end -= TAX * max(v_end - basis * (v_end / v), 0.0)
    years = max((menu.index[-1] - menu.index[0]).days / 365.25, 1e-9)
    return {"daily": net, "switches": int(switch_day.sum()),
            "cagr_pre": float((1 + net).prod() ** (1 / years) - 1), "cagr_after": float(v_end ** (1 / years) - 1)}


def mdd(r: pd.Series) -> Optional[float]:
    if r.empty:
        return None
    w = (1 + r).cumprod()
    return float((w / w.cummax() - 1).min())


def t_sf(t: float, df: int) -> float:
    """스튜던트 t 위꼬리 P(T > t) — scipy 없이 심프슨 적분(crash-inverse-v1 과 같은 방법)."""
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    f = lambda u: c * (1 + u * u / df) ** (-(df + 1) / 2)  # noqa: E731
    b, n = abs(t), 2000
    h = b / n
    area = (f(0.0) + f(b) + sum((4 if k % 2 else 2) * f(k * h) for k in range(1, n))) * h / 3
    upper = 0.5 - area
    return float(min(1.0, max(0.0, upper if t >= 0 else 1 - upper)))


def one_sided(x: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    x = np.asarray(x, dtype=float)
    if len(x) < 3 or np.std(x, ddof=1) == 0:
        return None, None
    t = float(np.mean(x) / (np.std(x, ddof=1) / math.sqrt(len(x))))
    return t, t_sf(t, len(x) - 1)


def era(df, a: str, b: Optional[str]):
    return df.loc[a:b] if b else df.loc[a:]


def era_period(s: pd.Series, a: str, b: Optional[str]) -> pd.Series:
    pa = pd.Period(a, "M")
    return s[s.index >= pa] if b is None else s[(s.index >= pa) & (s.index <= pd.Period(b, "M"))]


def year_oracle_schedule(menu: pd.DataFrame) -> pd.Series:
    yr = (1 + menu).groupby(menu.index.year).prod() - 1
    best = yr.idxmax(axis=1)
    months = menu.index.to_period("M").unique()
    return pd.Series([best[m.year] for m in months], index=months)


def summarize(menu: pd.DataFrame, sched: pd.Series, st: pd.Series) -> dict[str, Any]:
    acc = run_account(menu, sched)
    mkt_acc = run_account(menu, pd.Series("M", index=sched.index))
    mret, mm = monthly_returns(acc["daily"]), monthly_returns(menu["M"])
    ex = (mret - mm).dropna()
    t, p = one_sided(ex.to_numpy())
    yr_s, yr_m = (1 + acc["daily"]).groupby(menu.index.year).prod() - 1, (1 + menu["M"]).groupby(menu.index.year).prod() - 1
    yex = yr_s - yr_m
    return {"cagr_pre": acc["cagr_pre"], "cagr_after": acc["cagr_after"], "mkt_cagr_pre": mkt_acc["cagr_pre"],
            "mkt_cagr_after": mkt_acc["cagr_after"], "excess_after": acc["cagr_after"] - mkt_acc["cagr_after"],
            "excess_pre": acc["cagr_pre"] - mkt_acc["cagr_pre"], "monthly_excess_mean": float(ex.mean()) if len(ex) else None,
            "t": t, "p": p, "mdd": mdd(acc["daily"]), "mdd_mkt": mdd(menu["M"]), "switches": acc["switches"],
            "years": int(len(yex)), "years_ge_goal": int((yex >= GOAL_EXCESS).sum()), "years_beat": int((yex > 0).sum()),
            "state_share": {s: float((st.reindex(sched.index) == s).mean()) for s in STATES}}


def local_edges(menu: pd.DataFrame, st: pd.Series, picks: dict[str, str]) -> dict[str, Any]:
    mret = monthly_returns(menu)
    st = st.reindex(mret.index)
    out = {}
    for s in STATES:
        k = picks[s]
        rows = mret[st == s]
        if k == "M":
            out[s] = {"pick": k, "months": int(len(rows)), "verdict": "MARKET", "mean": None, "p": None}
            continue
        x = (rows[k] - rows["M"]).to_numpy()
        t, p = one_sided(x)
        holds = len(x) >= MIN_STATE_MONTHS and len(x) and x.mean() > 0 and p is not None and p < LOCAL_ALPHA
        out[s] = {"pick": k, "months": int(len(x)), "mean": float(x.mean()) if len(x) else None, "t": t, "p": p,
                  "verdict": "LOCAL_HOLDS" if holds else "LOCAL_FAILS"}
    return out


def evaluate(menu: pd.DataFrame) -> dict[str, Any]:
    menu = menu.dropna()
    st = applied_states(month_states(menu["M"]))
    mret_all = monthly_returns(menu)
    sel = ERAS["selection"]
    book = choose_playbook(era_period(mret_all, *sel), st)
    picks = {s: book[s]["pick"] for s in STATES}
    res: dict[str, Any] = {"playbook": book, "picks": picks, "eras": {}}
    for name, (a, b) in ERAS.items():
        m = era(menu, a, b)
        if m.empty:
            continue
        months = m.index.to_period("M").unique()
        honest = summarize(m, schedule_from_playbook(st, picks, months), st)
        is_book = choose_playbook(era_period(mret_all, a, b), st)
        is_picks = {s: is_book[s]["pick"] for s in STATES}
        res["eras"][name] = {
            "honest": honest,
            "state_oracle_is": {**summarize(m, schedule_from_playbook(st, is_picks, months), st), "picks": is_picks},
            "year_oracle": summarize(m, year_oracle_schedule(m), st),
            "local": local_edges(m, st, picks),
            "menu_cagr": {k: float((1 + m[k]).prod() ** (252 / len(m)) - 1) for k in MENU},
        }
    c = res["eras"]["confirmation"]["honest"]
    useful = (c["excess_after"] >= USEFUL_EXCESS and c["monthly_excess_mean"] is not None and c["monthly_excess_mean"] > 0
              and c["p"] is not None and c["p"] < ALPHA and c["mdd"] >= c["mdd_mkt"] - MDD_TOL)
    res["verdict"] = "GOAL_MET" if useful and c["excess_after"] >= GOAL_EXCESS else ("USEFUL" if useful else "FAIL")
    res["local_verdicts"] = {s: x["verdict"] for s, x in res["eras"]["confirmation"]["local"].items()}
    raw = month_states(menu["M"]).dropna()
    res["latest"] = {"month": str(raw.index[-1]), "state": str(raw.iloc[-1]), "next_pick": picks.get(str(raw.iloc[-1]), "M")}
    return res


# ---------------------------------------------------------------- 자료
def load_real() -> pd.DataFrame:
    from core import french_factors as ff

    lab = _lab()
    ff3, i12, m6, p25 = (ff.load(n) for n in ("ff3_daily", "ind12_daily", "mom6_daily", "ports25_daily"))
    if any(x is None for x in (ff3, i12, m6, p25)):
        raise RuntimeError("Ken French 일별 자료(FF3·12 산업·6 모멘텀·25 규모×BM)를 받지 못함")
    wk = lambda s: lab.to_weekdays(s.astype(float))  # noqa: E731
    rf, mkt = wk(ff3["RF"]), wk(ff3["Mkt-RF"] + ff3["RF"])
    defensive = wk(i12[["NoDur", "Hlth", "Utils"]].mean(axis=1))
    menu = build_menu(mkt, rf, wk(m6["BIG HiPRIOR"]), wk(p25["SMALL HiBM"]), wk(p25["BIG HiBM"]), defensive)
    return menu.dropna()


def load_smoke() -> pd.DataFrame:
    lab = _lab()
    d = lab.synthetic_data()
    rf, mkt, i12 = d["rf"], d["mkt"], d["ind12"]
    rng = np.random.default_rng(11)
    ex = (mkt - rf).to_numpy()
    noise = lambda b, s: pd.Series(rf.to_numpy() + b * ex + rng.normal(0, s, len(ex)), index=mkt.index)  # noqa: E731
    return build_menu(mkt, rf, noise(1.1, 0.004), noise(1.2, 0.006), noise(1.0, 0.004), i12.iloc[:, :3].mean(axis=1)).dropna()


# ---------------------------------------------------------------- 보고
def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def report(res: dict, smoke: bool) -> str:
    L = [f"# 국면별 전략 교체(플레이북) 검증 (regime-playbook-v1{' · 스모크' if smoke else ''})", "",
         "국면(추세×변동성, 그 시점 정보만)마다 다른 메뉴를 들고 가면 시장을 크게 이기나. 규칙·판정은 결과 보기 전에 고정했다(SPEC.md).", "",
         f"**판정: {res['verdict']}** (목표 GOAL_MET = 확인 시대 세후 근사 +{GOAL_EXCESS * 100:.0f}%p 이상)", "",
         "**국소점(확인 시대 국면별):** " + " · ".join(f"{STATE_LABELS[s].split('(')[0]} → {MENU_LABELS[res['picks'][s]]} **{v}**"
                                              for s, v in res["local_verdicts"].items()), "",
         f"자료 마지막 달 {res['latest']['month']} 국면: {STATE_LABELS.get(res['latest']['state'], res['latest']['state'])} → 플레이북 다음 달 메뉴: "
         f"{MENU_LABELS[res['latest']['next_pick']]} (Ken French 자료는 한두 달 늦다)", "",
         "## 선택 시대(1929~1966)에서 고른 플레이북", "",
         "| 국면 | 달 수 | 고른 메뉴 | 메뉴별 월 초과 평균(대 시장) |", "|---|---|---|---|"]
    for s in STATES:
        b = res["playbook"][s]
        exs = ", ".join(f"{k} {v * 100:+.2f}%" for k, v in b["excess"].items() if k != "M") or "—"
        L.append(f"| {STATE_LABELS[s]} | {b['months']} | {MENU_LABELS[b['pick']]} | {exs} |")
    L.append("")
    titles = {"selection": "선택 시대 1929~1966 (표본 안)", "confirmation": "확인 시대 1967~2007 (판정)", "report_2008": "2008 이후 (보고만)"}
    for name, e in res["eras"].items():
        L += [f"## {titles[name]}", "",
              "| 방식 | 세전 CAGR | 세후 근사 CAGR | 시장 세후 | 세후 초과 | 월 초과 단측 p | MDD / 시장 | 교체 횟수 | 시장 이긴 해 / +7%p 넘은 해 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for key, lab in (("honest", "정직한 플레이북(판정)"), ("state_oracle_is", "국면 정보 천장(그 시대 보고 고름)"), ("year_oracle", "사후 천장(해마다 최고 메뉴)")):
            x = e[key]
            L.append(f"| {lab} | {_pct(x['cagr_pre'])} | {_pct(x['cagr_after'])} | {_pct(x['mkt_cagr_after'])} | **{_pct(x['excess_after'])}** | "
                     f"{'—' if x['p'] is None else f'{x['p']:.4f}'} | {_pct(x['mdd'], 1)} / {_pct(x['mdd_mkt'], 1)} | {x['switches']} | "
                     f"{x['years_beat']}/{x['years']} · {x['years_ge_goal']}/{x['years']} |")
        L += ["", "국면별 국소점: " + " · ".join(
            f"{STATE_LABELS[s].split('(')[0]}({v['months']}달) {MENU_LABELS[v['pick']]} {_pct(v['mean'])}/월 {v['verdict']}" for s, v in e["local"].items()),
              "", "메뉴 그냥 보유 CAGR(세전): " + ", ".join(f"{MENU_LABELS[k]} {_pct(v)}" for k, v in e["menu_cagr"].items()), ""]
    L += ["## 읽는 법", "",
          "- 사후 천장은 '그해 무엇이 최고일지 미리 알았다면'이다. 실전에서는 불가능하며 국소점 접근의 원리적 최대치를 보여 줄 뿐이다.",
          "- 사후 천장 − 정직한 플레이북 = 국면을 미리 알 수 없어서 잃는 몫. 국면 정보 천장 − 정직한 플레이북 = 과거 국면 승자가 다음 시대에 바뀌어서 잃는 몫.",
          "- 세금은 근사(교체 때 실현, 연 22%, 공제·환율 없음). 시장 그냥 보유는 끝에 한 번 청산.",
          "- GOAL_MET·USEFUL 도 엔진 채택이 아니다. 전진 원장 후보이며 엔진 반영은 사용자 확인 뒤 별도 작업이다."]
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
    res = evaluate(load_smoke() if a.smoke else load_real())
    res.update(rules=RULES_VERSION, judge=JUDGE_VERSION, smoke=bool(a.smoke),
               verdicts={"playbook": res["verdict"], **{f"local_{s}": v for s, v in res["local_verdicts"].items()}})
    (out / "results.json").write_text(json.dumps(_strip(res), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
