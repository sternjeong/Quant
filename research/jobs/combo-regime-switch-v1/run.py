"""combo-regime-switch-v1 — X2(코어 50 + 업종 모멘텀 VT20 50)를 실시간 신호가 켜질 때만 들고 가면 시장을 이기나. 규칙·판정은 SPEC.md.

python research/jobs/combo-regime-switch-v1/run.py --out OUT --checkpoint CK [--smoke]
계산은 수 분이라 체크포인트를 쓰지 않는다(계약상 인자만 받는다).
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

RULES_VERSION = "combo-regime-switch/v1"
JUDGE_VERSION = "combo-switch-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
ERAS = {"A": ("1929-01-01", "1966-12-31"), "B": ("1967-01-01", "2007-12-31"), "C": ("2008-01-01", None)}
SIGNALS = ("S1_DISP", "S2_TREND", "S3_EDGE")
SIGNAL_LABELS = {"S1_DISP": "산업 간 격차 큼(126일, 과거 중앙값 위)", "S2_TREND": "시장 200일선 아래", "S3_EDGE": "X2 가 최근 252일 시장을 이김"}
DISP_DAYS, MA_DAYS, EDGE_DAYS, MIN_MONTHS = 126, 200, 252, 24
COST_ONE_WAY = 0.0010
TAX = 0.22
MIN_EXCESS = 0.01
ALPHA = 0.05 / len(SIGNALS)
MDD_TOL = 0.05
GOAL_EXCESS = 0.07


def _load(name: str, rel: str):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fc():
    return _load("factor_combo_v1_run", "research/jobs/factor-combo-v1/run.py")


# ---------------------------------------------------------------- 신호 (순수 함수, 월말 값 → 다음 달 적용)
def _month_last(index: pd.DatetimeIndex) -> np.ndarray:
    month = index.to_period("M")
    return pd.Series(np.arange(len(index)), index=index).groupby(month).max().to_numpy()


def month_signals(mkt: pd.Series, ind: pd.DataFrame, x2: pd.Series) -> pd.DataFrame:
    """인덱스 = 월(Period, 판정한 달). 값 = 신호 켜짐(bool), 판정 불가는 NaN."""
    idx = mkt.index
    last = _month_last(idx)
    periods = idx.to_period("M").unique()
    cum_ind = (1 + ind.fillna(0.0)).cumprod()
    disp = (cum_ind / cum_ind.shift(DISP_DAYS) - 1).where(ind.notna()).std(axis=1, ddof=1)
    d_m = pd.Series(disp.iloc[last].to_numpy(), index=periods)
    med = d_m.expanding(min_periods=MIN_MONTHS).median()
    w = (1 + mkt).cumprod()
    ma = w.rolling(MA_DAYS, min_periods=MA_DAYS).mean()
    wx = (1 + x2).cumprod()
    edge = (wx / wx.shift(EDGE_DAYS)) - (w / w.shift(EDGE_DAYS))
    out = pd.DataFrame(index=periods, dtype=object)
    out["S1_DISP"] = pd.Series(d_m.to_numpy() > med.to_numpy(), index=periods).where(med.notna() & d_m.notna())
    out["S2_TREND"] = pd.Series(w.iloc[last].to_numpy() < ma.iloc[last].to_numpy(), index=periods).where(ma.iloc[last].notna().to_numpy())
    e_m = edge.iloc[last]
    out["S3_EDGE"] = pd.Series(e_m.to_numpy() > 0, index=periods).where(e_m.notna().to_numpy())
    return out


def applied(sig: pd.Series) -> pd.Series:
    s = sig.copy()
    s.index = s.index + 1
    return s


# ---------------------------------------------------------------- 계좌
def switch_returns(x2: pd.Series, mkt: pd.Series, on_month: pd.Series) -> tuple[pd.Series, np.ndarray]:
    """on_month(Period → bool, NaN 은 시장)대로 X2/시장. 바뀌는 달 첫날 비용."""
    month = mkt.index.to_period("M")
    on = on_month.reindex(month).eq(True).to_numpy()
    r = np.where(on, x2.to_numpy(), mkt.to_numpy())
    first = np.r_[True, month[1:] != month[:-1]]
    prev = np.concatenate([on[:1], on[:-1]])
    sw = first & (on != prev)
    sw[0] = False
    return pd.Series(r - sw * 2 * COST_ONE_WAY, index=mkt.index), sw


def after_tax_cagr(r: pd.Series, sw: np.ndarray) -> float:
    """regime-playbook-v1 과 같은 근사: 교체 때 평가익 실현, 연말 22%, 끝에 청산."""
    v, basis, realized, year = 1.0, 1.0, 0.0, r.index[0].year
    for d, x, s in zip(r.index, r.to_numpy(), sw):
        if d.year != year:
            tax = TAX * max(realized, 0.0)
            if tax > 0:
                basis *= (v - tax) / v
                v -= tax
            realized, year = 0.0, d.year
        if s:
            realized += v - basis
            basis = v
        v *= 1 + x
    v_pre = v
    v -= TAX * max(realized, 0.0)
    basis *= v / v_pre
    v -= TAX * max(v - basis, 0.0)
    years = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
    return float(v ** (1 / years) - 1)


def cagr(r: pd.Series) -> Optional[float]:
    if len(r) < 2:
        return None
    years = max((r.index[-1] - r.index[0]).days / 365.25, 1e-9)
    return float((1 + r).prod() ** (1 / years) - 1)


def mdd(r: pd.Series) -> Optional[float]:
    if r.empty:
        return None
    w = (1 + r).cumprod()
    return float((w / w.cummax() - 1).min())


def t_sf(t: float, df: int) -> float:
    """스튜던트 t 위꼬리 — scipy 없이 심프슨 적분(crash-inverse-v1 과 같은 방법)."""
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


def monthly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def era(s: pd.Series, a: str, b: Optional[str]) -> pd.Series:
    return s.loc[a:b] if b else s.loc[a:]


def oracle_on(x2: pd.Series, mkt: pd.Series) -> pd.Series:
    """사후 천장: 해마다 그해 나은 쪽(보고만)."""
    yx, ym = (1 + x2).groupby(x2.index.year).prod(), (1 + mkt).groupby(mkt.index.year).prod()
    months = mkt.index.to_period("M").unique()
    return pd.Series([bool(yx[m.year] > ym[m.year]) for m in months], index=months)


def era_stats(r: pd.Series, sw: np.ndarray, m: pd.Series, x2: pd.Series) -> dict[str, Any]:
    return {"cagr": cagr(r), "cagr_after": after_tax_cagr(r, sw), "mkt_cagr": cagr(m), "x2_cagr": cagr(x2),
            "excess": (cagr(r) or 0) - (cagr(m) or 0), "mdd": mdd(r), "mdd_mkt": mdd(m), "switches": int(sw.sum()),
            "mkt_cagr_after": after_tax_cagr(m, np.zeros(len(m), dtype=bool))}


def evaluate(mkt: pd.Series, ind: pd.DataFrame, x2: pd.Series) -> dict[str, Any]:
    idx = mkt.index.intersection(x2.index).intersection(ind.index)
    mkt, ind, x2 = mkt.reindex(idx), ind.reindex(idx), x2.reindex(idx).fillna(0.0)
    sigs = month_signals(mkt, ind, x2)
    out: dict[str, Any] = {"signals": {}}
    variants = {s: applied(sigs[s]) for s in SIGNALS}
    variants["ORACLE"] = oracle_on(x2, mkt)
    for name, on in variants.items():
        per = {}
        for e, (a, b) in ERAS.items():
            m, x = era(mkt, a, b), era(x2, a, b)
            if m.empty:
                continue
            r, sw = switch_returns(x, m, on)
            st = era_stats(r, sw, m, x)
            st["on_share"] = float(on.reindex(m.index.to_period("M").unique()).eq(True).mean())
            per[e] = st
        full_m = era(mkt, ERAS["A"][0], ERAS["B"][1])
        r_full, _ = switch_returns(era(x2, ERAS["A"][0], ERAS["B"][1]), full_m, on)
        t, p = one_sided((monthly(r_full) - monthly(full_m)).to_numpy())
        rec: dict[str, Any] = {"eras": per, "t_1929_2007": t, "p_1929_2007": p}
        if name in SIGNALS:
            A, B, C = per.get("A"), per.get("B"), per.get("C")
            ok = (A is not None and B is not None and C is not None
                  and A["excess"] >= MIN_EXCESS and B["excess"] >= MIN_EXCESS and C["excess"] >= 0
                  and p is not None and p < ALPHA and t is not None and t > 0
                  and all(x["mdd"] >= x["mdd_mkt"] - MDD_TOL for x in (A, B, C)))
            rec["verdict"] = "SWITCH_HELPS" if ok else "FAIL"
        out["signals"][name] = rec
    last = sigs.dropna(how="all")
    out["latest"] = {"month": str(last.index[-1]), **{s: (None if pd.isna(last[s].iloc[-1]) else bool(last[s].iloc[-1])) for s in SIGNALS}}
    x2_only = {e: {"x2_cagr": cagr(era(x2, a, b)), "mkt_cagr": cagr(era(mkt, a, b))} for e, (a, b) in ERAS.items()}
    out["x2_hold"] = x2_only
    return out


# ---------------------------------------------------------------- 자료
def load(smoke: bool) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    fc = _fc()
    data = fc.lab.synthetic_data() if smoke else fc.lab.load_real()
    rf, mkt, ind = data["rf"], data["mkt"], data["ind12"]
    parts = fc.sleeves(data, fc.COST_BPS)
    x2_combo = next(c for c in fc.COMBOS if c.name.startswith("X2"))
    x2, _ = fc.combo_returns(parts, x2_combo, mkt, rf, fc.COST_BPS)
    return mkt.reindex(ind.index).fillna(0.0), ind, x2


# ---------------------------------------------------------------- 보고
def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def report(res: dict, smoke: bool) -> str:
    sg = res["signals"]
    L = [f"# 결합 전략 X2 국면 교체 검증 (combo-regime-switch-v1{' · 스모크' if smoke else ''})", "",
         "X2(현 코어 50 + 업종 상위 2·목표 변동성 20% 50)를 그 시점 신호가 켜질 때만 들고 가고, 꺼지면 시장. 규칙·판정은 결과 보기 전에 고정했다(SPEC.md).", "",
         "**판정:** " + " · ".join(f"{s}({SIGNAL_LABELS[s]}) **{sg[s]['verdict']}**" for s in SIGNALS), "",
         f"판정 기준({JUDGE_VERSION}): A(1929~1966)·B(1967~2007) 모두 세전 CAGR ≥ 시장 + {MIN_EXCESS * 100:.0f}%p, 1929~2007 월 초과 단측 p < {ALPHA:.4f}, "
         f"C(2008~) 시장에 지지 않음, 최대낙폭 A·B·C 모두 시장보다 {MDD_TOL * 100:.0f}%p 넘게 깊지 않음.", "",
         f"자료 마지막 달 {res['latest']['month']} 신호: " + ", ".join(
             f"{s} {'—' if res['latest'][s] is None else ('켜짐(X2)' if res['latest'][s] else '꺼짐(시장)')}" for s in SIGNALS), "",
         "X2 그냥 보유 대 시장(세전 CAGR): " + " · ".join(f"{e} {_pct(v['x2_cagr'])} / {_pct(v['mkt_cagr'])}" for e, v in res["x2_hold"].items()), ""]
    titles = {"A": "A 1929~1966 (판정)", "B": "B 1967~2007 (판정)", "C": "C 2008~ (판정, 여러 번 본 구간)"}
    for e, title in titles.items():
        L += [f"## {title}", "", "| 방식 | 세전 CAGR | 시장 | 세전 초과 | 목표(+7%p)까지 | 세후 근사 / 시장 세후 | MDD / 시장 | 교체 | X2 든 달 비율 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for name, rec in sg.items():
            x = rec["eras"].get(e)
            if not x:
                continue
            lab = "사후 천장(해마다 나은 쪽, 보고만)" if name == "ORACLE" else f"{name} {SIGNAL_LABELS[name]}"
            L.append(f"| {lab} | {_pct(x['cagr'])} | {_pct(x['mkt_cagr'])} | **{_pct(x['excess'])}** | {_pct(GOAL_EXCESS - x['excess'])} | "
                     f"{_pct(x['cagr_after'])} / {_pct(x['mkt_cagr_after'])} | {_pct(x['mdd'], 1)} / {_pct(x['mdd_mkt'], 1)} | {x['switches']} | {x['on_share'] * 100:.0f}% |")
        L.append("")
    L += ["1929~2007 월 초과 단측 p: " + ", ".join(f"{s} {'—' if sg[s]['p_1929_2007'] is None else f'{sg[s]['p_1929_2007']:.4f}'}" for s in SIGNALS), "",
          "## 읽는 법", "",
          "- 사후 천장은 '그해 X2 와 시장 중 무엇이 나을지 미리 알았다면'이다. 실전에서는 불가능하며 이 교체 방식의 원리적 최대치다.",
          "- 세후 근사는 교체 때 실현되는 세금만 넣었다. X2 내부 매매의 세금은 빠져 있어 실제 세후는 더 나쁘다.",
          "- X2 재료는 1927~2007 자료로 골랐다(재료 선택 편향). C 구간이 가장 중요한 확인이다.",
          "- SWITCH_HELPS 도 엔진 채택이 아니다. 전진 원장 후보이며 엔진 반영은 사용자 확인 뒤 별도 작업이다."]
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
    mkt, ind, x2 = load(a.smoke)
    res = evaluate(mkt, ind, x2)
    res.update(rules=RULES_VERSION, judge=JUDGE_VERSION, smoke=bool(a.smoke),
               verdicts={s: res["signals"][s]["verdict"] for s in SIGNALS})
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
