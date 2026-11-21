"""검증 연구 factor-combo-v1: 따로 살아남은 인자(위험 효율 코어·변동성 맞춤 업종 모멘텀·필터 달린 2배 다리)를 한 계좌에서 결합하면
시장과 현 코어를 함께 크게 이기나. (사전 등록, 2026-11-21 — 규칙은 SPEC.md 와 이 파일에 결과를 보기 전에 고정)

후보(가족 4개, 비율 고정): X1 시장 40 + ERC 코어 40 + 2배 다리 20 · X2 코어 50 + SC2VT20 50 · X3 네 소매 위험 균등
                         · X4 코어를 시장 변동성까지 레버리지(상한 2배).
PASS(모두): (a) 연수익 ≥ 시장 + 2.0%p (b) ≥ 코어 + 0.5%p (c) MDD 시장보다 나쁘지 않음 (d) 최악 252일 ≥ 시장 최악 − 5%p
           (e) 하위 구간 3/4 이상 시장·코어 각각 이김 (f) CAPM 알파 t ≥ 2.0 (g) 편도 30bp 에서도 (a)·(b).
재료를 고른 자료와 판정 자료가 같으므로 PASS 는 전진 원장에 올릴 후보라는 뜻까지만이다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402


def _load(name: str, rel: str):
    if name in sys.modules and getattr(sys.modules[name], "__file__", None):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lab = _load("core_longrun_lab", "research/jobs/core-longrun-v1/lab.py")
mvs = _load("mom_volscale_run", "research/jobs/mom-volscale-v1/run.py")
dlab = _load("dca_dip_lab", "research/jobs/dca-dip-deploy-v1/lab.py")

JUDGE_VERSION = "factor-combo-judge/v1"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
COST_BPS = 10.0
STRESS_BPS = 30.0
ERC_WINDOW = 126
LEV_MKT_WINDOW = 252
LEV_CORE_WINDOW = 126
LEV_CAP = 2.0
LEV_SPREAD = 0.01           # 1배 초과분 차입 = RF + 연 1%
MIN_ACTIVE_ROWS = 126
CAGR_VS_MKT = 0.02
CAGR_VS_CORE = 0.005
WORST_TOL = 0.05
MIN_SUB_WINS = 3
ALPHA_T = 2.0


@dataclass(frozen=True)
class Combo:
    name: str
    label: str
    weights: dict = field(default_factory=dict)   # 고정 비중(소매 이름 → 비중). 비어 있으면 mode 로
    mode: str = "fixed"                           # fixed / erc / lever


COMBOS = (
    Combo("X1_core_mkt_leg", "시장 40 + ERC 코어 40 + 2배 다리 20", {"MKT": 0.4, "CORE_ERC": 0.4, "LEG2F": 0.2}),
    Combo("X2_core_sector", "코어 50 + 업종 모멘텀 변동성 맞춤 50", {"CORE": 0.5, "SC2VT20": 0.5}),
    Combo("X3_sleeve_erc", "네 소매 위험 균등(시장·코어·업종 VT20·2배 다리)", {"MKT": 0, "CORE": 0, "SC2VT20": 0, "LEG2F": 0}, "erc"),
    Combo("X4_core_levered", "코어를 시장 변동성까지 레버리지(상한 2배)", {"CORE": 1.0}, "lever"),
)
REFERENCE = Combo("R_mkt50_erc50", "시장 50 + ERC 코어 50 (synthesis-rnd-v2 통과 기준, 보고만)", {"MKT": 0.5, "CORE_ERC": 0.5})
SLEEVE_LABELS = {"MKT": "시장", "CORE": "현 코어(모멘텀 상위 4 + 200일선)", "CORE_ERC": "ERC 코어",
                 "SC2VT20": "업종 상위 2 + 목표 변동성 20%", "LEG2F": "2배 시장 다리(200일선 ±2%)"}


def _f(v, pct=True, sign=False, nd=1):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if pct:
        return f"{v * 100:+.{nd}f}%" if sign else f"{v * 100:.{nd}f}%"
    return f"{v:+.2f}" if sign else f"{v:.2f}"


# =================================================================================================
# 재료 소매 (원 연구 코드 그대로)
# =================================================================================================

def sector_vt20(ind: pd.DataFrame, mkt: pd.Series, rf: pd.Series, bps: float) -> pd.Series:
    """mom-volscale-v1 의 I2/VT20/none: 252행 총수익 상위 2, 직전 126행 비조정 소매 변동성으로 min(0.20/vol, 1)."""
    sched = mvs.pick_schedule(ind, "I2")
    raw = mvs.raw_sleeve(ind, rf, sched, 2)
    below = mvs.market_below_sma(mkt, ind.index)
    exp = mvs.exposure_schedule(raw, below, sched, "VT20", "none")
    return mvs.simulate(ind, rf, sched, exp, 2, bps)["returns"]


def sleeves(data: dict, bps: float = COST_BPS) -> dict[str, pd.Series]:
    rf, mkt, ind = data["rf"], data["mkt"], data["ind12"]
    idx = ind.index
    return {
        "MKT": mkt.reindex(idx).fillna(0.0),
        "CORE": lab.strategy_returns(ind, rf, lab.target_weights(ind, mkt, lab.Rule()), bps),
        "CORE_ERC": lab.strategy_returns(ind, rf, lab.target_weights(ind, mkt, lab.Rule(weighting="erc")), bps),
        "SC2VT20": sector_vt20(ind, mkt, rf, bps),
        "LEG2F": dlab.leg_returns(mkt.reindex(idx).fillna(0.0), rf.reindex(idx).fillna(0.0), mode="band200", cost_bps=bps),
    }


def active_start(r: pd.Series, rf: pd.Series) -> int:
    """소매가 RF 와 처음 달라진 행(아직 투자 전인 워밍업을 건너뛰려고). 끝까지 같으면 len."""
    d = np.abs(r.to_numpy() - rf.reindex(r.index).fillna(0.0).to_numpy()) > 1e-12
    hit = np.flatnonzero(d)
    return int(hit[0]) if len(hit) else len(r)


# =================================================================================================
# 결합
# =================================================================================================

def lever_returns(core: pd.Series, mkt: pd.Series, rf: pd.Series, bps: float = COST_BPS) -> tuple[pd.Series, pd.Series]:
    """X4: 매달 첫 거래일 d 에 노출 e = min(시장 직전 252행 변동성 / 코어 직전 126행 변동성, 2.0)(코어 활동 126행 전이면 1.0).
    다음 날부터 수익 = RF + e × (코어 − RF) − max(e−1, 0) × 차입 가산/252. 노출이 바뀐 날 |Δe| × bps."""
    idx = core.index
    c, m = core.to_numpy(), mkt.reindex(idx).fillna(0.0).to_numpy()
    f = rf.reindex(idx).fillna(0.0).to_numpy()
    start = active_start(core, rf)
    firsts = lab.month_first_mask(idx)
    e, prev = 1.0, 1.0
    out, expo = np.zeros(len(idx)), np.ones(len(idx))
    for i in range(1, len(idx)):
        if firsts[i]:
            d = i  # 결정은 d 종가, 창은 d−1 행까지
            if d - start >= LEV_CORE_WINDOW and d >= LEV_MKT_WINDOW:
                vm = float(np.std(m[d - LEV_MKT_WINDOW: d], ddof=1))
                vc = float(np.std(c[d - LEV_CORE_WINDOW: d], ddof=1))
                e = min(vm / vc, LEV_CAP) if vc > 0 else 1.0
            else:
                e = 1.0
        out[i] = f[i] + prev * (c[i] - f[i]) - max(prev - 1.0, 0.0) * LEV_SPREAD / 252
        if e != prev:
            out[i] = (1 + out[i]) * (1 - abs(e - prev) * bps / 1e4) - 1
        expo[i] = prev
        prev = e if firsts[i] else prev
    return pd.Series(out, index=idx), pd.Series(expo, index=idx)


def combine(parts: dict[str, pd.Series], combo: Combo, rf: pd.Series, bps: float = COST_BPS) -> tuple[pd.Series, pd.DataFrame]:
    """소매 비중을 매달 첫 거래일 종가에 목표로 되돌리고(다음 날부터 적용) 그 사이에는 표류. 비용 = Σ|목표 − 표류| × bps.
    erc: 직전 ERC_WINDOW 행 공분산 위험 균등(모든 소매가 MIN_ACTIVE_ROWS 행 활동하기 전에는 같은 비중)."""
    names = list(combo.weights)
    R = pd.concat([parts[k] for k in names], axis=1).fillna(0.0).to_numpy()
    idx = parts[names[0]].index
    starts = [active_start(parts[k], rf) for k in names]
    firsts = lab.month_first_mask(idx)
    fixed = np.array([combo.weights[k] for k in names], dtype=float)
    h = np.full(len(names), 1.0 / len(names)) if combo.mode == "erc" else fixed.copy()
    out = np.zeros(len(idx))
    W = np.zeros((len(idx), len(names)))
    for i in range(len(idx)):
        if i > 0:
            g = h * (1 + R[i])
            out[i] = g.sum() - 1.0
            h = g / g.sum()
        if firsts[i] and i > 0:
            if combo.mode == "erc":
                tgt = np.full(len(names), 1.0 / len(names))
                if all(i - s >= MIN_ACTIVE_ROWS for s in starts):
                    er = lab.erc_weights(pd.DataFrame(R[max(0, i - ERC_WINDOW): i], columns=names))  # d−1 행까지
                    if er:
                        tgt = np.array([er[k] for k in names])
            else:
                tgt = fixed
            tv = float(np.abs(tgt - h).sum())
            out[i] = (1 + out[i]) * (1 - tv * bps / 1e4) - 1
            h = tgt.copy()
        W[i] = h
    return pd.Series(out, index=idx), pd.DataFrame(W, index=idx, columns=names)


def combo_returns(parts: dict[str, pd.Series], combo: Combo, mkt: pd.Series, rf: pd.Series, bps: float = COST_BPS) -> tuple[pd.Series, dict]:
    if combo.mode == "lever":
        r, e = lever_returns(parts["CORE"], mkt, rf, bps)
        return r, {"avg_exposure": float(e.mean()), "max_exposure": float(e.max())}
    r, w = combine(parts, combo, rf, bps)
    return r, {"avg_weights": {k: float(v) for k, v in w.mean().items()}}


# =================================================================================================
# 판정
# =================================================================================================

def worst_252(r: pd.Series) -> float:
    eq = (1 + r).cumprod()
    roll = eq / eq.shift(252) - 1
    return float(roll.min()) if roll.notna().any() else float("nan")


def summary(r: pd.Series, rf: pd.Series) -> dict:
    return {"cagr": lab.cagr(r), "mdd": lab.mdd(r), "worst_252": worst_252(r), "sharpe_monthly": lab.sharpe_monthly(r, rf)}


def judge(cand: pd.Series, cand_stress: pd.Series, mkt: pd.Series, core: pd.Series, core_stress: pd.Series, rf: pd.Series) -> dict:
    """전체 일별 수익을 받아 판정 구간·하위 구간으로 자른다."""
    w = lambda s: lab.window(s, lab.MAIN_START, lab.MAIN_END)  # noqa: E731
    sc, sm, sk = summary(w(cand), rf), summary(w(mkt), rf), summary(w(core), rf)
    ss, sks = summary(w(cand_stress), rf), summary(w(core_stress), rf)
    cp = lab.capm(w(cand), mkt, rf)
    subs = []
    for a, b in lab.SUBPERIODS:
        subs.append({"start": a, "end": b, "cand": lab.cagr(lab.window(cand, a, b)), "market": lab.cagr(lab.window(mkt, a, b)),
                     "core": lab.cagr(lab.window(core, a, b))})
    win_m = sum(s["cand"] > s["market"] for s in subs)
    win_c = sum(s["cand"] > s["core"] for s in subs)
    checks = {
        "a_cagr_vs_market": bool(sc["cagr"] >= sm["cagr"] + CAGR_VS_MKT),
        "b_cagr_vs_core": bool(sc["cagr"] >= sk["cagr"] + CAGR_VS_CORE),
        "c_mdd_vs_market": bool(sc["mdd"] >= sm["mdd"]),
        "d_worst252": bool(sc["worst_252"] >= sm["worst_252"] - WORST_TOL),
        "e_subperiods": bool(win_m >= MIN_SUB_WINS and win_c >= MIN_SUB_WINS),
        "f_alpha_t": bool(cp["alpha_annual"] > 0 and cp["alpha_t_nw6"] >= ALPHA_T),
        "g_cost_stress": bool(ss["cagr"] >= sm["cagr"] + CAGR_VS_MKT and ss["cagr"] >= sks["cagr"] + CAGR_VS_CORE),
    }
    return {"cand": sc, "market": sm, "core": sk, "stress": ss, "core_stress": sks, "capm": cp, "subperiods": subs,
            "wins_vs_market": win_m, "wins_vs_core": win_c, "checks": checks, "noop": rp.noop_guard((w(cand) - w(mkt)).tolist())}


def correlations(parts: dict[str, pd.Series], rf: pd.Series) -> dict:
    mon = pd.DataFrame({k: lab.monthly(lab.window(v, lab.MAIN_START, lab.MAIN_END)) for k, v in parts.items()})
    ex = mon.sub(lab.monthly(lab.window(rf.reindex(parts["MKT"].index).fillna(0.0), lab.MAIN_START, lab.MAIN_END)), axis=0)
    c = ex.corr()
    return {a: {b: float(c.loc[a, b]) for b in c.columns} for a in c.index}


def etf_era(smoke: bool) -> dict:
    """보고만: SPY·16자산 코어(총수익 신호 근사)·섹터 SPDR 11개 상위 2 VT20·합성 2배 SPY 다리(200일선 ±2%), 현금 BIL, 편도 3bp."""
    try:
        from core import champion_strategy as cs

        spy, bil = cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF
        sectors = [t for t in cs.CORE_UNIVERSE if t.startswith("XL")]
        tick = list(dict.fromkeys(list(cs.CORE_UNIVERSE) + [spy, bil]))
        if smoke:
            idx = pd.bdate_range("2005-06-01", "2012-12-31")
            rng = np.random.default_rng(5)
            adj = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(idx)))) for t in tick}, index=idx)
            adj[bil] = 90 + np.arange(len(idx)) * 0.002
        else:
            from core.market_data import get_multiple_price_history

            h = get_multiple_price_history(tick, start="2005-06-01", end=None, interval="1d")
            adj = pd.DataFrame({t: h[t]["Adj Close"] for t in tick if t in h and not h[t].empty}).sort_index()
            adj = adj.reindex(adj[spy].dropna().index)
        core_cols = [t for t in cs.CORE_UNIVERSE if t in adj.columns]
        rets = adj[core_cols].pct_change(fill_method=None)
        mkt = adj[spy].pct_change(fill_method=None).fillna(0.0)
        rf = adj[bil].pct_change(fill_method=None).fillna(0.0)
        bps = cs.CORE_COST_BPS_PER_SIDE
        data = {"rf": rf, "mkt": mkt, "ind12": rets}
        parts = sleeves(data, bps)
        parts["SC2VT20"] = sector_vt20(rets[[t for t in sectors if t in rets.columns]], mkt, rf, bps)
        rows = {"SPY 그냥 보유": mkt, SLEEVE_LABELS["CORE"]: parts["CORE"]}
        for c in (*COMBOS, REFERENCE):
            rows[c.label] = combo_returns(parts, c, mkt, rf, bps)[0]
        keep = lambda s: lab.window(s, lab.COMPARE_START)  # noqa: E731
        return {"start": str(keep(mkt).index[0].date()), "end": str(keep(mkt).index[-1].date()),
                "basis": "세전 달러, 배당 포함, 현금 = BIL, 2배 다리는 합성(실제 SSO 아님)",
                "rows": {k: summary(keep(v), keep(rf)) for k, v in rows.items()}}
    except Exception as exc:  # noqa: BLE001 — 보고용, 판정과 무관
        return {"skipped": f"{type(exc).__name__}: {exc}"[:300]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    years = (pd.Timestamp(lab.MAIN_END) - pd.Timestamp(lab.MAIN_START)).days / 365.25
    power = rp.power_report(years, len(COMBOS))  # 결과를 보기 전에(구간·시도 수만)

    data = lab.synthetic_data() if a.smoke else lab.load_real()
    rf, mkt = data["rf"], data["mkt"]
    parts, parts_s = sleeves(data, COST_BPS), sleeves(data, STRESS_BPS)

    verdicts: dict[str, Any] = {}
    detail, extra = {}, {}
    for c in COMBOS:
        r, info = combo_returns(parts, c, mkt, rf, COST_BPS)
        rs, _ = combo_returns(parts_s, c, mkt, rf, STRESS_BPS)
        jd = judge(r, rs, parts["MKT"], parts["CORE"], parts_s["CORE"], rf)
        ir = jd["capm"]["appraisal_ir"]
        if jd["noop"]:
            verdicts[c.name] = "NOT_EVALUABLE"
        elif all(jd["checks"].values()):
            verdicts[c.name] = "PASS"
        else:
            verdicts[c.name] = "FAIL"
            verdicts[f"{c.name}_fail_class"] = rp.classify_fail(ir, power)
        detail[c.name], extra[c.name] = jd, info
    verdicts["overall"] = "COMBO_HELPS" if any(verdicts[c.name] == "PASS" for c in COMBOS) else "NO_COMBO_EDGE"

    ref_r, _ = combo_returns(parts, REFERENCE, mkt, rf, COST_BPS)
    main_w = lambda s: lab.window(s, lab.MAIN_START, lab.MAIN_END)  # noqa: E731
    reported = {"sleeves": {k: summary(main_w(v), rf) for k, v in parts.items()}, "reference": summary(main_w(ref_r), rf),
                "correlations": correlations(parts, rf)}
    ind49 = {}
    if data.get("ind49") is not None:
        p49 = sleeves({"rf": rf, "mkt": mkt, "ind12": data["ind49"]}, COST_BPS)
        ind49 = {c.name: summary(main_w(combo_returns(p49, c, mkt, rf)[0]), rf) for c in COMBOS}
        ind49["CORE"] = summary(main_w(p49["CORE"]), rf)
    cmp_w = lambda s: lab.window(s, lab.COMPARE_START)  # noqa: E731
    compare = {"start": lab.COMPARE_START, "end": str(mkt.index[-1].date()), "MKT": summary(cmp_w(parts["MKT"]), rf),
               "CORE": summary(cmp_w(parts["CORE"]), rf)}
    for c in (*COMBOS, REFERENCE):
        compare[c.name] = summary(cmp_w(combo_returns(parts, c, mkt, rf)[0]), rf)

    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "source": data["source"],
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "power": power,
              "rule": {"combos": {c.name: {"label": c.label, "weights": c.weights, "mode": c.mode} for c in COMBOS},
                       "cost_bps": COST_BPS, "stress_bps": STRESS_BPS, "erc_window": ERC_WINDOW, "lev_windows": [LEV_MKT_WINDOW, LEV_CORE_WINDOW],
                       "lev_cap": LEV_CAP, "lev_spread": LEV_SPREAD, "cagr_vs_market": CAGR_VS_MKT, "cagr_vs_core": CAGR_VS_CORE,
                       "worst_tol": WORST_TOL, "min_subperiod_wins": MIN_SUB_WINS, "alpha_t": ALPHA_T,
                       "main_window": [lab.MAIN_START, lab.MAIN_END], "subperiods": lab.SUBPERIODS},
              "main": detail, "combo_info": extra, "reported": reported, "ind49": ind49, "compare_2008": compare,
              "etf_era": etf_era(a.smoke)}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(result, a.smoke), encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


def render(r: dict, smoke: bool) -> str:
    v = r["verdicts"]
    labels = {c.name: c.label for c in (*COMBOS, REFERENCE)}
    L = [f"# 살아남은 인자 결합 ({JUDGE_VERSION}){' — 스모크(가짜 자료)' if smoke else ''}", "",
         "따로 살아남은 재료(위험 효율 코어 · 변동성 맞춤 업종 모멘텀 · 필터 달린 2배 다리)를 한 계좌에서 결합하는 4가지를 "
         f"**{lab.MAIN_START} ~ {lab.MAIN_END}** Ken French 12 산업 자료로 판정한다. 시장과 현 코어를 둘 다 이겨야 한다.", "",
         f"**종합: {v['overall']}** — PASS 는 '전진 원장에 올릴 후보'까지만 뜻한다. 재료를 고른 자료와 판정 자료가 같아 결과는 낙관적이다. 엔진은 바뀌지 않았다.", "",
         rp.power_line(r["power"]), "",
         "| 후보 | 판정 | 연수익 (시장 / 코어) | MDD (시장) | 최악 252일 (시장) | 하위 구간 시장·코어 | 알파 / t | 30bp 연수익 |",
         "|---|---|---|---|---|---|---|---|"]
    for name, jd in r["main"].items():
        c, m, k, ck, cp = jd["cand"], jd["market"], jd["core"], jd["checks"], jd["capm"]
        mark = lambda b: "✓" if b else "✗"  # noqa: E731
        verdict = v[name] + (f" ({v[name + '_fail_class']})" if f"{name}_fail_class" in v else "")
        L.append(f"| {labels[name]} | **{verdict}** | {_f(c['cagr'])} ({_f(m['cagr'])} / {_f(k['cagr'])}) {mark(ck['a_cagr_vs_market'])}{mark(ck['b_cagr_vs_core'])} "
                 f"| {_f(c['mdd'])} ({_f(m['mdd'])}) {mark(ck['c_mdd_vs_market'])} | {_f(c['worst_252'])} ({_f(m['worst_252'])}) {mark(ck['d_worst252'])} "
                 f"| {jd['wins_vs_market']}/4 · {jd['wins_vs_core']}/4 {mark(ck['e_subperiods'])} | {_f(cp['alpha_annual'], sign=True)} / {cp['alpha_t_nw6']:.2f} {mark(ck['f_alpha_t'])} "
                 f"| {_f(jd['stress']['cagr'])} {mark(ck['g_cost_stress'])} |")
    L += ["", f"판정 기준(사전 고정): (a) 연수익 ≥ 시장 + {CAGR_VS_MKT * 100:.1f}%p (b) ≥ 코어 + {CAGR_VS_CORE * 100:.1f}%p (c) MDD 시장보다 나쁘지 않음 "
          f"(d) 최악 252일 ≥ 시장 최악 − {WORST_TOL * 100:.0f}%p (e) 하위 구간 {MIN_SUB_WINS}/4 이상 시장·코어 각각 이김 (f) 알파 t ≥ {ALPHA_T} (g) 편도 30bp 에서도 (a)·(b).", ""]
    L += ["## 결합 후보 정보", ""]
    for name, info in r["combo_info"].items():
        if "avg_exposure" in info:
            L.append(f"- {labels[name]}: 평균 노출 {info['avg_exposure']:.2f}배, 최대 {info['max_exposure']:.2f}배")
        else:
            L.append(f"- {labels[name]}: 평균 비중 " + ", ".join(f"{SLEEVE_LABELS[k]} {w * 100:.0f}%" for k, w in info["avg_weights"].items()))
    L += ["", "## 하위 구간 연수익(후보 / 시장 / 코어)", "", "| 후보 | " + " | ".join(f"{a[:4]}~{b[:4]}" for a, b in lab.SUBPERIODS) + " |",
          "|---|" + "---|" * len(lab.SUBPERIODS)]
    for name, jd in r["main"].items():
        L.append(f"| {labels[name]} | " + " | ".join(f"{_f(s['cand'])} / {_f(s['market'])} / {_f(s['core'])}" for s in jd["subperiods"]) + " |")

    def row(name, s):
        return f"| {name} | {_f(s['cagr'])} | {_f(s['mdd'])} | {_f(s['worst_252'])} | {_f(s['sharpe_monthly'], False)} |"

    rep = r["reported"]
    L += ["", "## 재료 소매 단독(판정 구간, 보고)", "", "| | 연수익 | MDD | 최악 252일 | 샤프(월별) |", "|---|---|---|---|---|"]
    L += [row(SLEEVE_LABELS[k], s) for k, s in rep["sleeves"].items()] + [row(labels[REFERENCE.name], rep["reference"])]
    cor = rep["correlations"]
    keys = list(cor)
    L += ["", "## 재료 사이 월별 초과수익 상관(판정 구간) — 결합 이득은 상관이 낮을 때만 생긴다", "",
          "| | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    L += [f"| {a} | " + " | ".join(f"{cor[a][b]:.2f}" for b in keys) + " |" for a in keys]
    if r["ind49"]:
        L += ["", "## 49 산업(견고성, 보고만 — 판정 구간)", "", "| | 연수익 | MDD | 최악 252일 | 샤프(월별) |", "|---|---|---|---|---|"]
        L += [row(labels.get(k, SLEEVE_LABELS.get(k, k)), s) for k, s in r["ind49"].items()]
    c = r["compare_2008"]
    L += ["", f"## 2008~{c['end'][:4]} (12 산업, 이미 여러 연구가 본 구간 — 보고만)", "", "| | 연수익 | MDD | 최악 252일 | 샤프(월별) |", "|---|---|---|---|---|",
          row("시장", c["MKT"]), row(SLEEVE_LABELS["CORE"], c["CORE"])] + [row(labels[x.name], c[x.name]) for x in (*COMBOS, REFERENCE)]
    e = r["etf_era"]
    L += ["", "## ETF 시대(보고만)", ""]
    if "skipped" in e:
        L += [f"건너뜀: {e['skipped']}"]
    else:
        L += [f"{e['start']} ~ {e['end']}, {e['basis']}. 2024-10~ 소진 구간 포함 — 판정에 쓰지 않음.", "",
              "| | 연수익 | MDD | 최악 252일 | 샤프(월별) |", "|---|---|---|---|---|"] + [row(k, s) for k, s in e["rows"].items()]
    L += ["", "판정 규칙은 결과를 보기 전에 SPEC.md·run.py 에 고정했다. 한계: 재료 선택 편향(재료를 고른 자료 = 판정 자료), 산업 포트폴리오 ≠ 실제 ETF, "
          "세전·환율 미반영, 레버리지 차입 비용은 가정값(RF+1%). PASS 도 엔진 자동 반영이 아니다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
