"""crash-inverse-v1 — 급락 신호 뒤 인버스(−1배) 보유가 이득이었나. 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-inverse-v1/run.py --out OUT --checkpoint CK [--smoke]
계산은 수 초라 체크포인트를 쓰지 않는다(계약상 인자만 받는다).
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

RULES_VERSION = "crash-inverse/v1"
JUDGE_VERSION = "inverse-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
ERAS = {"selection": ("1927-07-01", "1966-12-31"), "confirmation": ("1967-01-01", "2007-12-31")}
REPORT_ERA = ("2008-01-01", None)
SIGNALS = ("D1", "D5", "BEAR")
HOLDS = (5, 20)
VARIANTS = [f"{s}_H{h}" for s in SIGNALS for h in HOLDS]
N_TRIALS = len(VARIANTS)
ALPHA = 0.05 / N_TRIALS
MIN_EVENTS = 15
INV_FEE = 0.009
COST_ONE_WAY = 0.0015
OVERLAY_W = 0.20
D1_TH, D5_TH, BEAR_DD, BEAR_HIGH, BEAR_MA = -0.03, -0.07, -0.10, 252, 200
LABELS = {"D1": "하루 −3% 이하", "D5": "5일 누적 −7% 이하", "BEAR": "고점 −10% 이하 + 200일선 아래"}


def _lab():
    spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research" / "jobs" / "core-longrun-v1" / "lab.py")
    mod = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(spec))
    if not hasattr(mod, "to_weekdays"):
        spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 신호·수익 (순수 함수)
def signals(mkt: pd.Series) -> dict[str, pd.Series]:
    """t 일 종가까지의 정보로 켜지는 급락 신호(bool)."""
    wealth = (1 + mkt).cumprod()
    r5 = wealth / wealth.shift(5) - 1
    dd = wealth / wealth.rolling(BEAR_HIGH, min_periods=BEAR_HIGH).max() - 1
    ma = wealth.rolling(BEAR_MA, min_periods=BEAR_MA).mean()
    return {"D1": mkt <= D1_TH, "D5": r5 <= D5_TH, "BEAR": (dd <= BEAR_DD) & (wealth < ma)}


def inverse_returns(mkt: pd.Series, rf: pd.Series) -> pd.Series:
    return -(mkt - rf) + rf - INV_FEE / 252


def active_mask(sig: pd.Series, hold: int) -> pd.Series:
    """신호일 t → t+2 ~ t+1+hold 일 수익에 인버스 보유(다음 거래일 종가 진입). 보유 중 새 신호는 그날부터 연장."""
    s = sig.to_numpy(dtype=bool)
    on = np.zeros(len(s), dtype=bool)
    for i in np.flatnonzero(s):
        on[i + 2:i + 2 + hold] = True
    return pd.Series(on, index=sig.index)


def events(sig: pd.Series, hold: int) -> list[int]:
    """겹치지 않는 사건의 신호일 위치(앞 사건의 보유가 끝난 뒤의 신호만)."""
    out, free_from = [], 0
    for i in np.flatnonzero(sig.to_numpy(dtype=bool)):
        if i >= free_from and i + 1 + hold < len(sig):
            out.append(int(i))
            free_from = i + 2 + hold
    return out


def event_returns(idx: list[int], ret: pd.Series, rf: pd.Series, hold: int, cost: float) -> np.ndarray:
    r, c = ret.to_numpy(), rf.to_numpy()
    return np.array([np.prod(1 + r[i + 2:i + 2 + hold]) - np.prod(1 + c[i + 2:i + 2 + hold]) - cost for i in idx])


def overlay_returns(mkt: pd.Series, inv: pd.Series, on: pd.Series) -> pd.Series:
    w = on.astype(float) * OVERLAY_W
    gross = (1 - w) * mkt + w * inv
    turn = w.diff().abs().fillna(w.iloc[0]) * 2  # 시장에서 빼서 인버스로(또는 반대) — 양쪽 매매
    return gross - turn * COST_ONE_WAY


def cagr(r: pd.Series) -> Optional[float]:
    if len(r) < 2:
        return None
    return float((1 + r).prod() ** (252 / len(r)) - 1)


def mdd(r: pd.Series) -> Optional[float]:
    if r.empty:
        return None
    w = (1 + r).cumprod()
    return float((w / w.cummax() - 1).min())


def t_test_one_sided(x: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    if len(x) < 3 or np.std(x, ddof=1) == 0:
        return None, None
    t = float(np.mean(x) / (np.std(x, ddof=1) / math.sqrt(len(x))))
    return t, t_sf(t, len(x) - 1)


def t_sf(t: float, df: int) -> float:
    """스튜던트 t 분포 위꼬리 확률 P(T > t) — scipy 없이(VM venv) 밀도를 심프슨 적분한다."""
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    f = lambda u: c * (1 + u * u / df) ** (-(df + 1) / 2)  # noqa: E731
    a, b = 0.0, abs(t)
    n = 2000
    h = (b - a) / n
    area = (f(a) + f(b) + sum((4 if k % 2 else 2) * f(a + k * h) for k in range(1, n))) * h / 3
    upper = 0.5 - area
    return float(min(1.0, max(0.0, upper if t >= 0 else 1 - upper)))


def era_slice(s: pd.Series, start: str, end: Optional[str]) -> pd.Series:
    return s.loc[start:end] if end else s.loc[start:]


def evaluate(mkt: pd.Series, rf: pd.Series) -> dict[str, Any]:
    inv = inverse_returns(mkt, rf)
    sigs = signals(mkt)
    out: dict[str, Any] = {}
    for v in VARIANTS:
        sname, hold = v.split("_H")[0], int(v.split("_H")[1])
        on_all = active_mask(sigs[sname], hold)
        per: dict[str, Any] = {}
        for era, (a, b) in {**ERAS, "report_2008": REPORT_ERA}.items():
            m, c, iv = era_slice(mkt, a, b), era_slice(rf, a, b), era_slice(inv, a, b)
            sg, on = era_slice(sigs[sname], a, b), era_slice(on_all, a, b)
            idx = events(sg, hold)
            ev = event_returns(idx, iv, c, hold, 2 * COST_ONE_WAY)
            mk = event_returns(idx, m, c, hold, 0.0)
            t, p = t_test_one_sided(ev)
            ov = overlay_returns(m, iv, on)
            per[era] = {"n_events": len(idx), "event_mean": float(ev.mean()) if len(ev) else None,
                        "event_median": float(np.median(ev)) if len(ev) else None,
                        "event_win": float((ev > 0).mean()) if len(ev) else None, "t": t, "p": p,
                        "market_after_mean": float(mk.mean()) if len(mk) else None,
                        "cagr_market": cagr(m), "cagr_overlay": cagr(ov), "mdd_market": mdd(m), "mdd_overlay": mdd(ov),
                        "days_on_share": float(on.mean()) if len(on) else None,
                        "first_event": str(m.index[idx[0]].date()) if idx else None}
        gates = {}
        for era in ERAS:
            e = per[era]
            gates[era] = {"a_events": e["n_events"] >= MIN_EVENTS,
                          "b_positive": e["event_mean"] is not None and e["event_mean"] > 0 and e["p"] is not None and e["p"] < ALPHA,
                          "c_cagr": e["cagr_overlay"] is not None and e["cagr_market"] is not None and e["cagr_overlay"] >= e["cagr_market"]}
        if not all(g["a_events"] for g in gates.values()):
            verdict = "NOT_EVALUABLE"
        elif all(all(g.values()) for g in gates.values()):
            verdict = "INVERSE_HELPS"
        else:
            verdict = "FAIL"
        out[v] = {"verdict": verdict, "gates": gates, "eras": per}
    latest = {s: bool(sigs[s].iloc[-1]) for s in SIGNALS}
    return {"variants": out, "latest_date": str(mkt.index[-1].date()), "latest_signals": latest}


# ---------------------------------------------------------------- 자료·보고
def load_real() -> tuple[pd.Series, pd.Series]:
    from core import french_factors as ff

    lab = _lab()
    ff3 = ff.load("ff3_daily")
    if ff3 is None:
        raise RuntimeError("Ken French 일별 FF3 자료를 받지 못함")
    rf = lab.to_weekdays(ff3["RF"].astype(float))
    mkt = lab.to_weekdays((ff3["Mkt-RF"] + ff3["RF"]).astype(float))
    idx = rf.index.intersection(mkt.index)
    return mkt.reindex(idx).dropna(), rf.reindex(idx).fillna(0.0)


def load_smoke() -> tuple[pd.Series, pd.Series]:
    d = _lab().synthetic_data()
    lab = _lab()
    rf, mkt = lab.to_weekdays(d["rf"]), lab.to_weekdays(d["mkt"])
    idx = rf.index.intersection(mkt.index)
    return mkt.reindex(idx).dropna(), rf.reindex(idx).fillna(0.0)


def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def report(res: dict, smoke: bool) -> str:
    v = res["variants"]
    lines = [f"# 급락장 인버스 검증 (crash-inverse-v1{' · 스모크' if smoke else ''})", "",
             "급락 신호 다음 거래일에 인버스(−1배)를 사서 정해진 기간 들고 있었다면 이득이었나. 규칙·판정은 결과를 보기 전에 고정했다(SPEC.md).", "",
             "**판정:** " + " · ".join(f"{k} **{x['verdict']}**" for k, x in v.items()), "",
             f"판정 기준({JUDGE_VERSION}): 두 시대(1927~1966, 1967~2007) 모두 ① 겹치지 않는 사건 ≥ {MIN_EVENTS} ② 사건 수익 평균 > 0, 단측 p < {ALPHA:.4f}"
             f"(본페로니 {N_TRIALS}) ③ 평소 시장 100% + 신호 동안 20% 인버스 계좌의 CAGR ≥ 시장 그냥 보유. 2008 이후는 보고만.", "",
             f"자료 마지막 날 {res['latest_date']} 신호: " + ", ".join(f"{s}({LABELS[s]}) {'켜짐' if on else '꺼짐'}" for s, on in res["latest_signals"].items())
             + " — Ken French 자료는 한두 달 늦게 갱신된다.", ""]
    for era_key, title in (("selection", "selection 1927~1966 (판정)"), ("confirmation", "confirmation 1967~2007 (판정)"),
                           ("report_2008", "2008 이후 (보고만)")):
        lines += [f"## {title}", "",
                  "| 변형 | 사건 수 | 인버스 사건 수익 평균/중앙 | 이긴 비율 | 단측 p | 같은 기간 시장 초과 평균(반등) | 덧씌운 계좌 CAGR / 시장 | MDD 덧씌움 / 시장 | 신호 켜진 날 비율 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for k, x in v.items():
            e = x["eras"][era_key]
            lines.append(f"| {k} | {e['n_events']} | {_pct(e['event_mean'])} / {_pct(e['event_median'])} | "
                         f"{'—' if e['event_win'] is None else f'{e['event_win'] * 100:.0f}%'} | "
                         f"{'—' if e['p'] is None else f'{e['p']:.4f}'} | {_pct(e['market_after_mean'])} | "
                         f"{_pct(e['cagr_overlay'])} / {_pct(e['cagr_market'])} | {_pct(e['mdd_overlay'], 1)} / {_pct(e['mdd_market'], 1)} | "
                         f"{_pct(e['days_on_share'], 1)} |")
        lines.append("")
    lines += ["## 읽는 법", "",
              "- '같은 기간 시장 초과 평균'이 양수면 급락 뒤 시장이 오히려 반등했다는 뜻이다(인버스 사건 수익은 대략 그 반대 부호).",
              "- PASS 도 엔진 채택이 아니다. 사용자 확인 뒤 아침 메시지 안내를 붙이는 작업을 따로 한다. 전부 FAIL 이면 인버스 추천은 넣지 않는다.",
              "- 세금은 넣지 않았다(인버스 매매는 실현이익을 더 만들어 세후로는 더 불리해질 뿐이다)."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    Path(a.checkpoint).mkdir(parents=True, exist_ok=True)
    mkt, rf = load_smoke() if a.smoke else load_real()
    res = evaluate(mkt, rf)
    res.update(rules=RULES_VERSION, judge=JUDGE_VERSION, smoke=bool(a.smoke),
               verdicts={k: x["verdict"] for k, x in res["variants"].items()})
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
