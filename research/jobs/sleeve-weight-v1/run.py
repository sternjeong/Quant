"""검증 연구 sleeve-weight-v1: 새틀라이트 비중 15% vs 25·35·50% (사전 등록, 2026-10-10). 계약·판정은 SPEC.md.

판정 sleeve-judge/v1 은 아래 상수와 judge() 에 고정한다(결과를 보기 전). 바꾸려면 새 id.
전체 계산은 VM 연구 실행기만 수행한다. 대화·Codespace 에서는 --smoke 만.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import signal
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core import sprint_lab as sp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "sleeve-weight-v1"
JUDGE_VERSION = "sleeve-judge/v1"
START = "2010-01-01"
HOLDOUT_YEARS = 2
WEIGHTS = {"W15": 0.15, "W25": 0.25, "W35": 0.35, "W50": 0.50}
BASE = "W15"
CANDIDATES = ("W25", "W35", "W50")
# --- 사전 등록 판정 기준 (고정) ---
MIN_CAGR_EDGE = 0.010      # 1. 앞 구간 세후 원화 CAGR +1.0%p 이상
MAX_MDD_WORSE = 0.030      # 2. 앞 구간 MDD 악화 3%p 이내
STRESS_EXTRA_FEE = 0.0008  # 5. 편도 +8bp
N_TRIALS = len(WEIGHTS)    # 4. DSR 시도 수
STOP = False


def _stop(*_):
    global STOP
    STOP = True


def _atomic(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(pickle.dumps(value))
    os.replace(tmp, path)


def _out_of_time() -> bool:
    return STOP or time.time() > float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH", "inf")) - 60


def _real_inputs() -> dict:
    from core import champion_strategy as cs
    from core.market_data import get_multiple_price_history

    if abs(cs.SATELLITE_WEIGHT - 0.15) > 1e-12:
        raise ValueError("엔진 새틀라이트 비중이 15%가 아님 — 기준선 불일치")
    bt = cs.run_champion_backtest(START, date.today().isoformat())
    if bt["satellite_weight_applied"] != cs.SATELLITE_WEIGHT:
        raise ValueError("새틀라이트 15% 기준선 재현 불가")
    core_r, sat_r = bt["core"]["ret_net"].align(bt["satellite"]["ret_net"], join="inner")
    gap = float(((1 - cs.SATELLITE_WEIGHT) * core_r + cs.SATELLITE_WEIGHT * sat_r - bt["ret_net"].reindex(core_r.index)).abs().max())
    if gap > 1e-9:
        raise ValueError(f"엔진 블렌드 재현 실패 (최대 차이 {gap})")
    log = bt["satellite"]["rebal_log"]
    core_w = bt["core"]["weights"]
    tick = list(dict.fromkeys(list(core_w.columns) + sorted({t for r in log for t in (r.get("weights") or {})}) + ["SPY"]))
    hist = get_multiple_price_history(tick, start="2009-06-01", end=None, interval="1d")
    close = pd.DataFrame({t: hist[t]["Close"] for t in tick if t in hist and not hist[t].empty}).ffill()
    adj = pd.DataFrame({t: hist[t]["Adj Close"] for t in tick if t in hist and not hist[t].empty}).ffill()
    usd = {"cagr": bt["metrics"].get("cagr") if isinstance(bt.get("metrics"), dict) else None}
    return {"core_w": core_w, "log": log, "close": close, "adj": adj, "fx": tx.usdkrw_series(),
            "repro": {"blend_max_gap": gap, "satellite_weight_applied": bt["satellite_weight_applied"],
                      "strategy_version": cs.CHAMPION_STRATEGY_VERSION, "engine_usd_metrics": usd}}


def _smoke_inputs() -> dict:
    idx = pd.bdate_range("2010-01-04", "2016-12-30")
    rng = np.random.default_rng(11)
    names = ["C1", "C2", "S1", "S2", "S3", "SPY"]
    close = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.013, len(idx)))) for t in names}, index=idx)
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    log = [{"date": str(d.date()), "weights": {a: 0.5, b: 0.5}}
           for d, (a, b) in zip(pd.bdate_range("2010-01-04", "2016-12-30", freq="6BMS"), [("S1", "S2"), ("S2", "S3"), ("S1", "S3")] * 5)]
    return {"core_w": core_w, "log": log, "close": close, "adj": close, "fx": pd.Series(1100.0, index=idx),
            "repro": {"synthetic_smoke": True}}


def _turnover(w: pd.DataFrame) -> float:
    years = (w.index[-1] - w.index[0]).days / 365.25
    return float(w.diff().abs().sum(axis=1).iloc[1:].sum() / 2 / years) if years > 0 else 0.0


def _sim(w: pd.DataFrame, inp: dict, cfg: tx.AccountConfig) -> dict:
    r = tx.simulate(w, inp["close"], inp["adj"], inp["fx"], cfg)
    years = (w.index[-1] - w.index[0]).days / 365.25
    liq = r["final_after_liquidation_krw"] / cfg.initial_krw
    vals = r["values_krw"]
    return {"cagr_pre": r["cagr_pre"], "cagr_after": r["cagr_after"], "cagr_after_liq": liq ** (1 / years) - 1,
            "total_after_liq": liq - 1, "mdd": r["mdd_after"], "totals": r["totals"],
            "daily": vals.pct_change().fillna(0.0), "start": str(w.index[0].date()), "end": str(w.index[-1].date())}


def judge(sims: dict, split: pd.Timestamp) -> tuple[dict, dict, dict | None]:
    """sleeve-judge/v1 — SPEC.md 판정 1~5. sims[name][segment] (segment: is·holdout·is_stress)."""
    def rpm(s):
        return s["total_after_liq"] / abs(s["mdd"]) if s["mdd"] < 0 else math.inf

    names = list(WEIGHTS)
    daily = {k: sims[k]["is"]["daily"] for k in names}
    mat = np.column_stack([daily[k].to_numpy() for k in names])
    pbo = sp.cscv_pbo(mat)
    active = {k: (daily[k] - daily[BASE]).to_numpy() for k in CANDIDATES}
    srs = [sp.moments(active[k])["sr"] for k in CANDIDATES]
    b = sims[BASE]
    verdicts, details = {}, {}
    for k in CANDIDATES:
        s = sims[k]
        mo = sp.moments(active[k])
        dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], N_TRIALS, srs)["dsr"]
        edge = s["is"]["cagr_after_liq"] - b["is"]["cagr_after_liq"]
        edge_stress = s["is_stress"]["cagr_after_liq"] - b["is_stress"]["cagr_after_liq"]
        checks = {
            "1_is_after_tax_cagr_edge_ge_1pp": edge >= MIN_CAGR_EDGE,
            "2_is_mdd_not_worse_than_3pp": s["is"]["mdd"] >= b["is"]["mdd"] - MAX_MDD_WORSE,
            "3_holdout_return_per_mdd_ge_base": rpm(s["holdout"]) >= rpm(b["holdout"]),
            "4_family_pbo_le_25pct_and_dsr_ge_0.95": pbo is not None and pbo["pbo"] <= sp.PBO_MAX and dsr >= sp.DSR_MIN,
            "5_edge_survives_8bp_stress": edge_stress >= MIN_CAGR_EDGE,
        }
        verdicts[k] = "PASS" if all(checks.values()) else "FAIL"
        details[k] = {"checks": checks, "is_cagr_edge": edge, "is_cagr_edge_stress": edge_stress, "dsr": dsr,
                      "holdout_return_per_mdd": rpm(s["holdout"]), "base_holdout_return_per_mdd": rpm(b["holdout"])}
    return verdicts, details, pbo


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, _stop)
    here = Path(__file__)
    fingerprint = hashlib.sha256(here.read_bytes() + here.with_name("SPEC.md").read_bytes()
                                 + Path(tx.__file__).read_bytes() + Path(sp.__file__).read_bytes()).hexdigest()
    path = ck / ("smoke.pkl" if a.smoke else "real.pkl")
    state = pickle.loads(path.read_bytes()) if path.exists() else {}
    if state and state.get("contract") != fingerprint:
        raise ValueError("체크포인트 계약 불일치: 새 id 필요")
    if not state:
        state = {"contract": fingerprint, "input": _smoke_inputs() if a.smoke else _real_inputs(), "sims": {}}
        _atomic(path, state)
    inp = state["input"]
    weights = {k: tx.champion_weights(inp["core_w"], inp["log"], w) for k, w in WEIGHTS.items()}
    days = weights[BASE].index
    split = days[-1] - pd.DateOffset(years=HOLDOUT_YEARS)
    weights["SPY"] = tx.buy_and_hold_weights(days)
    base_cfg = tx.AccountConfig()
    stress_cfg = tx.AccountConfig(fee_rate=base_cfg.fee_rate + STRESS_EXTRA_FEE)
    segments = {"full": (days, base_cfg), "is": (days[days < split], base_cfg),
                "holdout": (days[days >= split], base_cfg), "is_stress": (days[days < split], stress_cfg)}
    for name, w in weights.items():
        for seg, (idx, cfg) in segments.items():
            key = f"{name}:{seg}"
            if key in state["sims"] or (name == "SPY" and seg == "is_stress"):
                continue
            if _out_of_time():
                _atomic(path, state)
                return 3
            state["sims"][key] = _sim(w.reindex(idx), inp, cfg)
            _atomic(path, state)
    sims = {n: {seg: state["sims"][f"{n}:{seg}"] for seg in segments if f"{n}:{seg}" in state["sims"]} for n in weights}
    verdicts, details, pbo = judge(sims, split)
    if a.smoke:
        verdicts = {k: "SMOKE_ONLY" for k in verdicts}
    report_rows = {}
    for n in weights:
        f = sims[n]["full"]
        report_rows[n] = {seg: {k: v for k, v in s.items() if k != "daily"} for seg, s in sims[n].items()}
        report_rows[n]["turnover_per_year"] = _turnover(weights[n].reindex(days))
        report_rows[n]["tax_cost_drag"] = f["cagr_pre"] - f["cagr_after"]
    payload = {"id": JOB_ID, "judge_version": JUDGE_VERSION, "smoke": a.smoke, "contract_sha256": fingerprint,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "start": str(days[0].date()), "end": str(days[-1].date()), "holdout_start": str(split.date()),
               "reproduction": inp["repro"], "satellite_rebalances": len(inp["log"]),
               "verdicts": verdicts, "details": details, "family_pbo": pbo, "stats": report_rows}
    tmp = out / "results.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, out / "results.json")

    def pct(v):
        return f"{v * 100:.2f}%"
    label = {"W15": "새틀라이트 15%(현재)", "W25": "새틀라이트 25%", "W35": "새틀라이트 35%", "W50": "새틀라이트 50%", "SPY": "SPY 그냥 보유(참고)"}
    lines = [f"# 새틀라이트 비중 연구 v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터, 실제 성과 아님)' if a.smoke else ''}", "",
             f"기간 {payload['start']} ~ {payload['end']}, 떼어 둔 구간 {payload['holdout_start']}~. 초기 3,000만 원, 카카오페이증권 가정, 원화·세후·청산 후.",
             f"가족 PBO {('—' if pbo is None else f'{pbo['pbo']:.0%}')}", "",
             "| | 판정 | 앞 구간 세후 CAGR | 앞 구간 MDD | +8bp 앞 구간 CAGR | 떼어 둔 2년 수익 | 떼어 둔 2년 MDD | 전체 세전→세후 | 회전율/년 | 세금·비용 끌림 | 양도세(백만) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n in weights:
        s = sims[n]
        st = pct(s["is_stress"]["cagr_after_liq"]) if "is_stress" in s else "—"
        lines.append(f"| {label[n]} | {verdicts.get(n, '기준' if n == BASE else '참고')} | {pct(s['is']['cagr_after_liq'])} | {pct(s['is']['mdd'])} | {st} | "
                     f"{pct(s['holdout']['total_after_liq'])} | {pct(s['holdout']['mdd'])} | {pct(s['full']['cagr_pre'])}→{pct(s['full']['cagr_after'])} | "
                     f"{report_rows[n]['turnover_per_year']:.2f} | {pct(report_rows[n]['tax_cost_drag'])} | {s['full']['totals']['capital_gains_tax_krw'] / 1e6:.1f} |")
    for k in CANDIDATES:
        miss = [g for g, ok in details[k]["checks"].items() if not ok]
        lines.append(f"\n{label[k]} 미충족: {', '.join(miss) or '없음'} (DSR {details[k]['dsr']:.2f})")
    lines += ["", "판정(모두 만족, 기준 15% 대비): ① 앞 구간 세후 원화 CAGR +1.0%p 이상 ② 원화 MDD 악화 3%p 이내 "
              "③ 떼어 둔 2년 수익/|MDD| ≥ 15% ④ 가족 PBO ≤ 25% & DSR ≥ 0.95(시도 4) ⑤ 편도 +8bp 비용에서도 ①이 유지.",
              "",
              "**생존편향 주의**: 새틀라이트 후보군에 상장폐지·편출 종목이 빠져 있어 새틀라이트 수익이 실제보다 좋게 나올 수 있고, "
              "비중을 올릴수록 이 편향이 결과에 더 크게 실린다.",
              "**회전율·세금 끌림**: 위 표의 회전율(연간 편도 합/2)과 세전−세후 CAGR 차이가 새틀라이트 반기 교체의 비용·양도세 부담을 보여 준다.",
              "", "PASS 는 사람 검토 후보일 뿐이며 엔진·주문 비중은 자동으로 바뀌지 않는다. 과거 결과이며 미래 수익을 뜻하지 않는다."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
