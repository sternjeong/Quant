"""사전 등록 계약은 SPEC.md. 전체 계산은 VM 실행기만 수행한다."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import signal
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core import champion_strategy as cs
from core import champion_performance as cp

START, END, SPLIT = "2016-01-01", "2026-10-02", "2023-01-01"
COINS = ["BTC-USD", "ETH-USD"]
IDS = ["C1", "C2", "C3", "C4"]
STOP = False


def stop(*_):
    global STOP
    STOP = True


def atomic(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(pickle.dumps(value))
    os.replace(tmp, path)


def metrics(r):
    eq = (1 + r).cumprod()
    peak = eq.cummax().clip(lower=1)
    return {"cagr": float(eq.iloc[-1] ** (252 / len(r)) - 1),
            "mdd": float((eq / peak - 1).min()), "total": float(eq.iloc[-1] - 1)}


def holm(ps):
    order = np.argsort(ps)
    adjusted = np.zeros(len(ps))
    last = 0.0
    for rank, i in enumerate(order):
        last = max(last, min(1.0, (len(ps) - rank) * ps[i]))
        adjusted[i] = last
    return adjusted.tolist()


def pvalue(active, repeats=2000):
    x = np.asarray(active, dtype=float)
    observed = x.mean()
    centered = x - observed
    rng = np.random.default_rng(260106)
    hits = 0
    for _ in range(repeats):
        starts = rng.integers(0, len(x), size=int(np.ceil(len(x) / 20)))
        sample = centered[((starts[:, None] + np.arange(20)) % len(x)).ravel()[:len(x)]]
        hits += sample.mean() >= observed
    return (hits + 1) / (repeats + 1)


def evaluate(base, variants, stress):
    result = {}
    for cid, r in variants.items():
        full, ref = metrics(r), metrics(base)
        gaps = {k: metrics(r.loc[m])["cagr"] - metrics(base.loc[m])["cagr"]
                for k, m in (("early", r.index < SPLIT), ("late", r.index >= SPLIT))}
        active = (r - base).loc[r.index >= SPLIT]
        sd = active.std(ddof=1)
        ir = float(active.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0
        result[cid] = {**full, "cagr_delta": full["cagr"] - ref["cagr"],
                       "mdd_delta": full["mdd"] - ref["mdd"], "split_delta": gaps,
                       "late_ir": ir, "p_raw": pvalue(active),
                       "stress_cagr_delta": metrics(stress[cid])["cagr"] - ref["cagr"]}
    for cid, p in zip(IDS, holm([result[c]["p_raw"] for c in IDS])):
        r = result[cid]
        r["p_holm"] = p
        r["gates"] = {"cagr": r["cagr_delta"] >= .005, "risk": r["mdd_delta"] >= -.03,
                      "early": r["split_delta"]["early"] > 0, "late": r["split_delta"]["late"] > 0,
                      "ir": r["late_ir"] >= .5, "stress": r["stress_cagr_delta"] > 0,
                      "holm": p <= .05}
        r["verdict"] = "CANDIDATE_FORWARD_ONLY" if all(r["gates"].values()) else "FAIL"
    return result


def variants(core, sat, cash, calendar, cost=.0008):
    idx = core.index
    prices = calendar.reindex(idx)
    coin_ret = prices.pct_change(fill_method=None)
    on = (calendar > calendar.ewm(span=100, adjust=False, min_periods=100).mean()).astype(float).reindex(idx)
    # 첫 수익일에도 직전 거래일 신호·수익을 유지하기 위해 전체 입력에서 먼저 계산한다.
    mix_calendar = calendar.pct_change(fill_method=None).mean(axis=1)
    vol = mix_calendar.rolling(60, min_periods=60).std() * np.sqrt(365)
    scale = (.20 / vol).clip(upper=1).reindex(idx)
    out = {}
    for cid in IDS:
        w = on * .025
        if cid == "C2":
            w["BTC-USD"], w["ETH-USD"] = on["BTC-USD"] * .05, 0.0
        budget = pd.Series(.05, index=idx)
        if cid == "C4":
            w = w.mul(scale, axis=0)
            budget = w.sum(axis=1)
        held = w.shift(1).fillna(0)
        held_budget = budget.shift(1).fillna(0)
        cash_weight = (budget - w.sum(axis=1)).shift(1).fillna(0)
        crypto = (held * coin_ret.fillna(0)).sum(axis=1)
        turnover = held.diff().fillna(held).abs().sum(axis=1)
        cash_turn = cash_weight.diff().fillna(cash_weight).abs()
        alloc_turn = held_budget.diff().fillna(held_budget).abs()
        cw, sw = (.85, .15 - held_budget) if cid == "C3" else (.85 - held_budget, .15)
        out[cid] = cw * core + sw * sat + crypto + cash_weight * cash - turnover * cost - (cash_turn + alloc_turn) * .0003
    return out


def diagnose(core, sat, base, spy, weights, parts, sat_parts):
    rows = []
    for year in sorted(set(base.index.year)):
        m = base.index.year == year
        growth = (1 + base.loc[m]).cumprod().shift(1).fillna(1)
        rows.append({"year": int(year), "end": str(base.loc[m].index[-1].date()),
                     "partial": year == 2026,
                     "returns": {k: float((1 + v.loc[m]).prod() - 1) for k, v in
                                 (("champion", base), ("core", core), ("satellite", sat), ("spy", spy))},
                     "core_contribution": float((growth * .85 * core.loc[m]).sum()),
                     "satellite_contribution": float((growth * .15 * sat.loc[m]).sum()),
                     "core_bil_average": float(weights.shift(1).loc[m].get("BIL", pd.Series(0., index=base.loc[m].index)).mean()),
                     "core_ticker_contributions": parts.loc[m].mul(growth * .85, axis=0).sum().to_dict(),
                     "satellite_ticker_contributions": sat_parts.loc[m].mul(growth * .15, axis=0).sum().to_dict()})
    monthly = pd.DataFrame({"champion": base, "core": core, "satellite": sat, "spy": spy})
    monthly = monthly.groupby(monthly.index.strftime("%Y-%m")).agg(lambda x: (1 + x).prod() - 1)
    return {"yearly": rows, "monthly": monthly.to_dict(orient="index")}


def inputs(smoke):
    if smoke:
        days = pd.bdate_range("2015-01-01", "2026-10-02")
        rng = np.random.default_rng(7)
        core = pd.Series(rng.normal(.0003, .01, len(days)), index=days)
        sat = pd.Series(rng.normal(.0004, .016, len(days)), index=days)
        cash = pd.Series(.0001, index=days)
        cal = pd.date_range("2015-01-01", "2026-10-02")
        coins = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(.0004, .03, len(cal)))) for t in COINS}, index=cal)
        weights = pd.DataFrame({"BIL": .2, "FAKE": .8}, index=days)
        parts = pd.DataFrame({"FAKE": core}, index=days)
        return core, sat, cash, coins, core, weights, parts, pd.DataFrame({"FAKE_SAT": sat}, index=days)
    from core.market_data import get_multiple_price_history
    bt = cs.run_champion_backtest("2015-01-01", "2026-10-03")
    if bt["satellite_weight_applied"] != .15:
        raise ValueError("새틀라이트 15% 기준선 불가")
    core, sat = bt["core"]["ret_net"].align(bt["satellite"]["ret_net"], join="inner")
    sat_names = bt["satellite"]["tickers_ever_held"]
    tick = list(dict.fromkeys(list(bt["core"]["weights"].columns) + ["SPY"] + COINS + sat_names))
    hist = get_multiple_price_history(tick, start="2014-01-01", end="2026-10-03", interval="1d")
    core_names = list(bt["core"]["weights"].columns) + ["SPY"]
    prices = cs._closes_from_histories(hist, core_names, field=cs.CORE_PRICE_FIELD).reindex(core.index)
    coins = pd.DataFrame({t: hist[t]["Close"] for t in COINS})
    coins = coins.loc["2015-09-01":END]
    if not coins.index.equals(pd.date_range(coins.index[0], coins.index[-1])) or coins.isna().any().any():
        raise ValueError("코인 달력 일봉 누락")
    if prices[["BIL", "SPY"]].isna().any().any() or str(core.index[-1].date()) != END:
        raise ValueError("기준선 현금·SPY 가격/종료일 누락")
    cash = prices["BIL"].pct_change(fill_method=None).fillna(0)
    spy = prices["SPY"].pct_change(fill_method=None).fillna(0)
    weights = bt["core"]["weights"].reindex(core.index)
    if (prices[weights.columns].isna() & weights.shift(1).fillna(0).gt(0)).any().any():
        raise ValueError("코어 보유 가격 결측")
    parts = cp.sleeve_contributions(prices[weights.columns], weights, cs.CORE_COST_BPS_PER_SIDE)["contrib"]
    if (parts.sum(axis=1) - core).abs().max() > 1e-9:
        raise ValueError("코어 기여 대조 실패")
    sat_prices = cs._closes_from_histories(hist, sat_names).reindex(core.index).ffill()
    sat_weights = cp._satellite_weights_from_log(bt["satellite"]["rebal_log"], sat_prices)
    sat_parts = cp.sleeve_contributions(sat_prices, sat_weights, cs.SATELLITE_COST_BPS_PER_SIDE)["contrib"]
    if (sat_prices.isna() & sat_weights.shift(1).fillna(0).gt(0)).any().any():
        raise ValueError("새틀라이트 보유 가격 결측")
    if (sat_parts.sum(axis=1) - sat).abs().max() > 1e-9:
        raise ValueError("새틀라이트 기여 대조 실패")
    return core, sat, cash, coins, spy, weights, parts, sat_parts


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, stop)
    fingerprint = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("SPEC.md").read_bytes()
                                 + Path(cs.__file__).read_bytes() + Path(cp.__file__).read_bytes()).hexdigest()
    path = ck / ("smoke.pkl" if a.smoke else "real.pkl")
    saved = pickle.loads(path.read_bytes()) if path.exists() else {}
    if saved and saved["contract"] != fingerprint:
        raise ValueError("체크포인트 계약 불일치: 새 id 필요")
    if not saved:
        saved = {"contract": fingerprint, "input": inputs(a.smoke)}
        atomic(path, saved)
    if STOP or time.time() > float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH", "inf")) - 45:
        return 3
    core, sat, cash, coins, spy, weights, parts, sat_parts = saved["input"]
    # 코인 상장 초기 결측은 워밍업만 제외하고 평가기간은 고정한다.
    common = core.index[core.index >= "2015-09-01"]
    core, sat, cash = core.reindex(common), sat.reindex(common), cash.reindex(common)
    vs = variants(core, sat, cash, coins)
    stress = variants(core, sat, cash, coins, .0025)
    keep = (common >= START) & (common <= END)
    core, sat, cash = core.loc[keep], sat.loc[keep], cash.loc[keep]
    base = .85 * core + .15 * sat
    candidates = evaluate(base, {k: v.loc[keep] for k, v in vs.items()}, {k: v.loc[keep] for k, v in stress.items()})
    diagnostic = diagnose(core, sat, base, spy.reindex(base.index), weights.reindex(base.index), parts.reindex(base.index), sat_parts.reindex(base.index))
    hashes = [hashlib.sha256(pd.util.hash_pandas_object(v, index=True).values.tobytes()).hexdigest() for v in saved["input"]]
    payload = {"id": "champion-crypto-v2", "smoke": a.smoke, "contract_sha256": fingerprint,
               "input_sha256": hashes, "start": START, "end": END, "split": SPLIT,
               "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
               "baseline": metrics(base), "diagnostics": diagnostic, "candidates": candidates,
               "verdicts": {k: "SMOKE_ONLY" if a.smoke else v["verdict"] for k, v in candidates.items()}}
    body = ["# 챔피언 손실 분해·코인 결합 v2", "", "합성 스모크 — 실제 성과 아님" if a.smoke else "탐색 연구 — 좋은 결과도 전진검증 후보이며 자동 반영 없음", "",
            f"기간 {START}~{END} · 기준선 코어 85% + 새틀라이트 15%", "",
            "| 연도 | 챔피언 | SPY | 코어 자체 | 새틀라이트 자체 | 코어 기여 | 새틀라이트 기여 |", "|---|---|---|---|---|---|---|"]
    for r in diagnostic["yearly"]:
        v = r["returns"]
        body.append(f"| {r['year']}{' YTD' if r['partial'] else ''} | {v['champion']:.2%} | {v['spy']:.2%} | {v['core']:.2%} | {v['satellite']:.2%} | {r['core_contribution']:.2%} | {r['satellite_contribution']:.2%} |")
    body += ["", "| 후보 | 판정 | CAGR 개선 | MDD 차이 | 뒤 구간 IR | Holm p | 비용 스트레스 개선 |", "|---|---|---|---|---|---|---|"]
    for k, v in candidates.items():
        body.append(f"| {k} | {payload['verdicts'][k]} | {v['cagr_delta']:+.2%} | {v['mdd_delta']:+.2%} | {v['late_ir']:.2f} | {v['p_holm']:.4f} | {v['stress_cagr_delta']:+.2%} |")
        body.append(f"\n{k} 미충족: {', '.join(g for g, ok in v['gates'].items() if not ok) or '없음'}\n")
    body += ["", "월별·종목별 기여는 results.json. 판정·비용·신호·생존편향·세금 제외·일봉 시각 차이·역사 재사용 한계는 SPEC.md 참고.", "기존 forward 토너먼트·코인 shadow 판정과 주문 배분은 변경하지 않는다."]
    tmp = out / "results.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    os.replace(tmp, out / "results.json")
    (out / "REPORT.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
