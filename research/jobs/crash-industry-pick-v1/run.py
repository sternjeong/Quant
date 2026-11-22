"""crash-industry-pick-v1 — 시장 급락 진입(−15%) 때 12 산업 중 무엇을 사야 1년 뒤 시장보다 나았나. 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-industry-pick-v1/run.py --out OUT --checkpoint CK [--smoke]
급락 사건 정의·쌍 통계는 crash-rebound-signal-v1 의 함수를 그대로 쓴다. 계산은 수십 초라 체크포인트를 쓰지 않는다.
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

RULES_VERSION = "crash-industry-pick/v1"
JUDGE_VERSION = "industry-pick-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
ERAS = {"A": ("1927-07-01", "1966-12-31"), "B": ("1967-01-01", "2007-12-31"), "C": ("2008-01-01", None)}
JUDGED = ("A", "B")
PICKS = ("P1_MOST_FALLEN", "P2_LEAST_FALLEN", "P3_HIGH_BETA", "P4_LOW_BETA")
PICK_LABELS = {"P1_MOST_FALLEN": "가장 많이 빠진 3 산업", "P2_LEAST_FALLEN": "가장 덜 빠진 3 산업",
               "P3_HIGH_BETA": "베타 높은 3 산업", "P4_LOW_BETA": "베타 낮은 3 산업"}
TOP_N = 3
HIGH_WIN = 252
BETA_WIN = 252
PRIMARY_H = 250
HORIZONS = (60, 120, 250)
MIN_EP = 5
ALPHA = 0.05 / len(PICKS)


def _load(name: str, rel: str):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cr():
    return _load("crash_rebound_signal_v1_run", "research/jobs/crash-rebound-signal-v1/run.py")


def _lab():
    return _load("core_longrun_lab", "research/jobs/core-longrun-v1/lab.py")


# ---------------------------------------------------------------- 순수 함수
def entry_days(mkt: pd.Series) -> list[tuple[int, bool]]:
    """급락 진입 위치(시장 누적지수가 252일 고점 대비 −15% 이하가 되는 날)와 진행 중 여부."""
    cr = _cr()
    frame = cr.state_frame((1 + mkt).cumprod())
    return [(a, open_) for a, _b, open_ in cr.episodes(frame)], frame.index


def rank_at(ind: pd.DataFrame, mkt: pd.Series, i: int) -> dict[str, list[str]]:
    """i 일 종가까지의 정보로 네 후보의 산업 3개. 252일 자료가 다 있는 산업만."""
    win = ind.iloc[max(0, i - BETA_WIN + 1): i + 1]
    ok = [c for c in ind.columns if win[c].notna().all() and len(win) == BETA_WIN]
    if len(ok) < 2 * TOP_N:
        return {}
    wealth = (1 + win[ok]).cumprod()
    dd = (wealth.iloc[-1] / wealth.max() - 1).sort_values()
    m = mkt.iloc[max(0, i - BETA_WIN + 1): i + 1].to_numpy()
    var = float(np.var(m, ddof=1))
    beta = pd.Series({c: float(np.cov(win[c].to_numpy(), m, ddof=1)[0, 1] / var) if var > 0 else 1.0 for c in ok}).sort_values()
    return {"P1_MOST_FALLEN": list(dd.index[:TOP_N]), "P2_LEAST_FALLEN": list(dd.index[-TOP_N:]),
            "P3_HIGH_BETA": list(beta.index[-TOP_N:]), "P4_LOW_BETA": list(beta.index[:TOP_N])}


def hold_return(rets: pd.DataFrame, cols: list[str], i: int, h: int) -> Optional[float]:
    """i 일 다음 거래일 종가에 똑같이 사서 h 일 보유(표류) — 수익 구간 = i+2 … i+1+h."""
    a, b = i + 2, i + 2 + h
    if b > len(rets):
        return None
    block = rets.iloc[a:b][cols].fillna(0.0).to_numpy()
    return float(np.mean(np.prod(1 + block, axis=0)) - 1)


def era_of(date: pd.Timestamp) -> str:
    for k, (a, b) in ERAS.items():
        if date >= pd.Timestamp(a) and (b is None or date <= pd.Timestamp(b)):
            return k
    return "pre"


def evaluate(mkt: pd.Series, ind: pd.DataFrame) -> dict[str, Any]:
    cr = _cr()
    idx = mkt.index.intersection(ind.index)
    mkt, ind = mkt.reindex(idx), ind.reindex(idx)
    starts, fidx = entry_days(mkt)
    pos = {d: k for k, d in enumerate(idx)}
    rows = []
    for a, open_ in starts:
        d = fidx[a]
        i = pos.get(d)
        if i is None:
            continue
        picks = rank_at(ind, mkt, i)
        if not picks:
            continue
        rec = {"date": str(d.date()), "era": era_of(d), "open": open_, "picks": picks, "D": {}}
        mret = mkt.to_frame("M")
        for h in HORIZONS:
            m = hold_return(mret, ["M"], i, h)
            for p, cols in picks.items():
                r = hold_return(ind, cols, i, h)
                rec["D"].setdefault(p, {})[h] = (None if m is None or r is None else float(math.log1p(r) - math.log1p(m)))
        rows.append(rec)
    eras: dict[str, Any] = {}
    for e in ERAS:
        er = [r for r in rows if r["era"] == e]
        eras[e] = {"episodes": len(er), "picks": {}}
        for p in PICKS:
            eras[e]["picks"][p] = {h: cr.paired_stats([r["D"][p][h] for r in er if r["D"][p][h] is not None]) for h in HORIZONS}
    verdicts = {}
    for p in PICKS:
        st = [eras[e]["picks"][p][PRIMARY_H] for e in JUDGED]
        if any(s["n"] < MIN_EP for s in st):
            verdicts[p] = "NOT_EVALUABLE"
        elif all(s["mean"] is not None and s["mean"] > 0 and s["p"] is not None and s["p"] < ALPHA for s in st):
            verdicts[p] = "PICK_HELPS"
        else:
            verdicts[p] = "FAIL"
    return {"episodes": rows, "eras": eras, "verdicts": verdicts}


# ---------------------------------------------------------------- 자료
def load(smoke: bool) -> tuple[pd.Series, pd.DataFrame, Optional[pd.DataFrame]]:
    d = _lab().synthetic_data() if smoke else _lab().load_real()
    return d["mkt"], d["ind12"], d.get("ind49")


# ---------------------------------------------------------------- 보고
def _pct(x: Optional[float], nd: int = 1) -> str:
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x * 100:+.{nd}f}%"


def report(res: dict, r49: Optional[dict], smoke: bool) -> str:
    L = [f"# 급락 진입 때 무엇을 살까 — 12 산업 (crash-industry-pick-v1{' · 스모크' if smoke else ''})", "",
         "시장이 252일 고점 대비 −15% 아래로 내려간 날, 그날 종가까지의 정보로 12 산업 중 3개를 골라 다음 날 사서 250일 들고 있으면 시장보다 나았나. 규칙·판정은 SPEC.md(결과 전 고정).", "",
         "**판정:** " + " · ".join(f"{p}({PICK_LABELS[p]}) **{v}**" for p, v in res["verdicts"].items()), "",
         f"판정 기준({JUDGE_VERSION}): 시대 A(1927~1966)·B(1967~2007) 각각 사건 ≥ {MIN_EP}, 두 시대 모두 250일 D(로그, 대 시장) 평균 > 0 이고 단측 p < {ALPHA:.4f}.", ""]
    names = {"A": "시대 A 1927~1966 (판정)", "B": "시대 B 1967~2007 (판정)", "C": "시대 C 2008~ (보고만)"}
    for e, title in names.items():
        x = res["eras"][e]
        L += [f"## {title} — 사건 {x['episodes']}개", "",
              "| 후보 | 250일 D 평균 / 중앙 | 시장 이긴 비율 | 단측 p | 120일 D | 60일 D | 평가 사건 |", "|---|---|---|---|---|---|---|"]
        for p in PICKS:
            s, s120, s60 = (x["picks"][p][h] for h in (250, 120, 60))
            L.append(f"| {PICK_LABELS[p]} | {_pct(s['mean'])} / {_pct(s['median'])} | {'—' if s['win'] is None else f'{s['win'] * 100:.0f}%'} | "
                     f"{'—' if s['p'] is None else f'{s['p']:.4f}'} | {_pct(s120['mean'])} | {_pct(s60['mean'])} | {s['n']} |")
        L.append("")
    if r49:
        L += ["## 견고성: 49 산업 같은 규칙 (보고만)", "", "| 후보 | A 250일 D | B 250일 D | C 250일 D |", "|---|---|---|---|"]
        for p in PICKS:
            L.append(f"| {PICK_LABELS[p]} | " + " | ".join(_pct(r49["eras"][e]["picks"][p][250]["mean"]) for e in ("A", "B", "C")) + " |")
        L.append("")
    L += ["## 사건별 고른 산업", "", "| 진입일 | 시대 | 많이 빠진 3 | 덜 빠진 3 | 고베타 3 | 저베타 3 | 250일 D(많이 빠진) |", "|---|---|---|---|---|---|---|"]
    for r in res["episodes"]:
        pk = r["picks"]
        L.append(f"| {r['date']}{' (진행 중)' if r['open'] else ''} | {r['era']} | {', '.join(pk['P1_MOST_FALLEN'])} | {', '.join(pk['P2_LEAST_FALLEN'])} | "
                 f"{', '.join(pk['P3_HIGH_BETA'])} | {', '.join(pk['P4_LOW_BETA'])} | {_pct(r['D']['P1_MOST_FALLEN'][250])} |")
    L += ["", "## 읽는 법", "",
          "- D 가 양수면 그 후보가 같은 날 산 시장보다 1년 뒤 더 많이 남겼다는 뜻이다(로그 차이).",
          "- 사건이 시대당 10개 안팎이라 매우 큰 효과만 통과한다. FAIL 이 '효과 없음'의 증명은 아니다.",
          "- 산업 지수는 실제 업종 ETF 와 다르고 세금·비용을 넣지 않았다. 통과도 추천 반영이 아니며 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
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
    mkt, i12, i49 = load(a.smoke)
    res = evaluate(mkt, i12)
    r49 = evaluate(mkt, i49) if i49 is not None else None
    res.update(rules=RULES_VERSION, judge=JUDGE_VERSION, smoke=bool(a.smoke),
               robust_49={p: {e: r49["eras"][e]["picks"][p][250]["mean"] for e in ERAS} for p in PICKS} if r49 else None)
    (out / "results.json").write_text(json.dumps(_clean(res), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, r49, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
