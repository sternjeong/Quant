"""BTC 배분·매매 시점 탐색. 계약은 같은 폴더의 SPEC.md."""
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

DATA_START, START, END = "2014-09-17", "2015-01-01", "2026-10-02"
SPLITS = (("early", "2015-01-01", "2020-01-01"),
          ("middle", "2020-01-01", "2023-01-01"),
          ("late", "2023-01-01", "2026-10-03"))
JOB_ID = "champion-crypto-v4"
IDS = ["H1", "H2", "H3", "H4", "T1", "T2", "T3", "T4", "T5", "T6", "V1", "V2"]
STOP = False


def stop(*_):
    global STOP
    STOP = True


def atomic(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(pickle.dumps(value))
    os.replace(tmp, path)


def metrics(r, annual_periods=252):
    r = pd.Series(r, dtype=float).dropna()
    eq = (1 + r).cumprod()
    peak = eq.cummax().clip(lower=1)
    underwater = eq < peak
    runs = underwater.ne(underwater.shift()).cumsum()
    duration = int(underwater.groupby(runs).sum().max()) if underwater.any() else 0
    return {"cagr": float(eq.iloc[-1] ** (annual_periods / len(r)) - 1),
            "volatility": float(r.std(ddof=1) * np.sqrt(252)),
            "mdd": float((eq / peak - 1).min()), "max_underwater_days": duration,
            "total": float(eq.iloc[-1] - 1)}


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


def make_candidates(core, sat, cash, prices):
    idx = core.index
    coin_ret = prices.pct_change(fill_method=None).reindex(idx)
    ema_on = {span: (prices > prices.ewm(span=span, adjust=False, min_periods=span).mean()).reindex(idx)
              for span in (50, 100, 200)}
    vol60 = prices.pct_change(fill_method=None).rolling(60, min_periods=60).std() * np.sqrt(365)
    candidates, stress = {}, {}
    configs = [(f"H{i}", "hold", weight, None, None)
               for i, weight in enumerate((.01, .025, .05, .10), start=1)]
    configs += [(f"T{j}", "trend", weight, span, None)
                for j, (span, weight) in enumerate(((50, .025), (50, .05), (100, .025),
                                                    (100, .05), (200, .025), (200, .05)), start=1)]
    configs += [(f"V{i}", "vol", .05, 100, target) for i, target in enumerate((.15, .25), start=1)]
    for cid, kind, budget, span, target in configs:
        if kind == "hold":
            w = pd.Series(budget, index=idx)
            total_budget = budget
        elif kind == "trend":
            w = ema_on[span].astype("boolean").fillna(False).astype(float) * budget
            total_budget = budget
        else:
            w = (target / vol60).clip(upper=budget).where(ema_on[span], 0).fillna(0).reindex(idx)
            total_budget = budget
        held = w.shift(1).fillna(0)
        held_budget = pd.Series(total_budget, index=idx)
        cash_w = (total_budget - w).shift(1).fillna(total_budget)
        core_w = .85 - held_budget
        ret_before_cost = core_w * core + .15 * sat + held * coin_ret.fillna(0) + cash_w * cash
        other_weight = (1 - held).clip(lower=1e-9)
        other_return = (core_w * core + .15 * sat + cash_w * cash) / other_weight
        coin_drift_turn = held * other_weight * (coin_ret - other_return).abs()
        cash_rest_weight = (1 - cash_w).clip(lower=1e-9)
        cash_rest_return = (core_w * core + .15 * sat + held * coin_ret.fillna(0)) / cash_rest_weight
        cash_drift_turn = cash_w * cash_rest_weight * (cash - cash_rest_return).abs()
        coin_turn = held.diff().abs().fillna(w.iloc[0]).fillna(0) + coin_drift_turn.fillna(0)
        cash_turn = cash_w.diff().abs().fillna(cash_w).fillna(0) + cash_drift_turn.fillna(0)
        alloc_turn = held_budget.diff().abs().fillna(held_budget).fillna(0)
        candidates[cid] = ret_before_cost - coin_turn * .0008 - cash_turn * .0003 - alloc_turn * .0003
        stress[cid] = ret_before_cost - coin_turn * .005 - cash_turn * .0003 - alloc_turn * .0003
    return candidates, stress


def evaluate(base, candidates, stress):
    result = {}
    for cid, r in candidates.items():
        m, bm = metrics(r), metrics(base)
        splits = {}
        for name, start, end in SPLITS:
            mask = (r.index >= start) & (r.index < end)
            splits[name] = metrics(r.loc[mask])["cagr"] - metrics(base.loc[mask])["cagr"]
        active = (r - base).loc[r.index >= "2023-01-01"]
        sd = active.std(ddof=1)
        ir = float(active.mean() / sd * np.sqrt(252)) if sd and np.isfinite(sd) else 0.0
        result[cid] = {**m, "cagr_delta": m["cagr"] - bm["cagr"],
                       "mdd_delta": m["mdd"] - bm["mdd"], "split_cagr_delta": splits,
                       "late_ir": ir, "p_raw": pvalue(active),
                       "stress_cagr_delta": metrics(stress[cid])["cagr"] - bm["cagr"]}
    for cid, p in zip(IDS, holm([result[c]["p_raw"] for c in IDS])):
        r = result[cid]
        r["p_holm"] = p
        r["gates"] = {"cagr": r["cagr_delta"] >= .005, "risk": r["mdd_delta"] >= -.03,
                      "early": r["split_cagr_delta"]["early"] > 0,
                      "middle": r["split_cagr_delta"]["middle"] > 0,
                      "late": r["split_cagr_delta"]["late"] > 0,
                      "ir": r["late_ir"] >= .5, "stress": r["stress_cagr_delta"] > 0,
                      "holm": p <= .05}
        r["verdict"] = "CANDIDATE_FORWARD_ONLY" if all(r["gates"].values()) else "FAIL"
    return result


def properties(prices, base, core, spy):
    output = {}
    coin_returns = prices.pct_change(fill_method=None).dropna()
    for ticker, px in prices.items():
        r = coin_returns[ticker].dropna()
        equity = (1 + r).cumprod()
        peak = equity.cummax().clip(lower=1)
        underwater = equity < peak
        groups = underwater.ne(underwater.shift()).cumsum()
        daily = r.index.dayofweek
        weekend = daily >= 5
        rolling = r.rolling(90, min_periods=60).std() * np.sqrt(365)
        aligned = r.reindex(base.index).dropna()
        indexes = aligned.index
        output[ticker] = {
            **metrics(r, annual_periods=365), "annualized_volatility_365d": float(r.std(ddof=1) * np.sqrt(365)),
            "skew": float(r.skew()), "excess_kurtosis": float(r.kurtosis()),
            "worst_day": float(r.min()), "best_day": float(r.max()),
            "positive_day_fraction": float((r > 0).mean()),
            "max_drawdown_recovery_days": int(underwater.groupby(groups).sum().max()) if underwater.any() else 0,
            "weekend_abs_return_share": float(r.loc[weekend].abs().sum() / r.abs().sum()),
            "mean_weekend_return": float(r.loc[weekend].mean()),
            "mean_weekday_return": float(r.loc[~weekend].mean()),
            "rolling_30d_volatility_quantiles": {str(q): float((r.rolling(30, min_periods=30).std() * np.sqrt(365)).quantile(q)) for q in (.1, .5, .9)},
            "rolling_90d_volatility_quantiles": {str(q): float(rolling.quantile(q)) for q in (.1, .5, .9)},
            "correlation_on_us_trading_days": {"champion": float(aligned.corr(base.loc[indexes])),
                                               "core": float(aligned.corr(core.loc[indexes])),
                                               "spy": float(aligned.corr(spy.loc[indexes]))},
            "rolling_90d_correlation_with_champion": {
                "mean": float(aligned.rolling(90, min_periods=60).corr(base.loc[indexes]).mean()),
                "p10": float(aligned.rolling(90, min_periods=60).corr(base.loc[indexes]).quantile(.1)),
                "p90": float(aligned.rolling(90, min_periods=60).corr(base.loc[indexes]).quantile(.9))}}
    return output


def inputs(smoke):
    if smoke:
        days = pd.bdate_range("2014-01-01", END)
        rng = np.random.default_rng(260106)
        core = pd.Series(rng.normal(.0003, .01, len(days)), index=days)
        sat = pd.Series(rng.normal(.0002, .015, len(days)), index=days)
        cash = pd.Series(.00005, index=days)
        crypto_days = pd.date_range(DATA_START, END)
        prices = pd.Series(100 * np.exp(np.cumsum(rng.normal(.0005, .025, len(crypto_days)))), index=crypto_days, name="BTC-USD")
        spy = core.copy()
        return core, sat, cash, prices, spy, {"synthetic_smoke": True}
    from core.market_data import get_multiple_price_history, get_price_history
    bt = cs.run_champion_backtest("2014-01-01", "2026-10-03")
    core, sat = bt["core"]["ret_net"].align(bt["satellite"]["ret_net"], join="inner")
    tickers = list(dict.fromkeys(list(bt["core"]["weights"].columns) + ["SPY", "BTC-USD"] + bt["satellite"]["tickers_ever_held"]))
    hist = get_multiple_price_history(tickers, start="2014-01-01", end="2026-10-03", interval="1d")
    core_names = list(bt["core"]["weights"].columns) + ["SPY"]
    prices_core = cs._closes_from_histories(hist, core_names, field=cs.CORE_PRICE_FIELD).reindex(core.index)
    btc = hist["BTC-USD"]["Close"].copy()
    btc.index = pd.DatetimeIndex(btc.index).tz_localize(None).normalize()
    btc = btc[~btc.index.duplicated(keep="last")]
    calendar = pd.date_range(DATA_START, END)
    btc = btc.reindex(calendar)
    missing = btc.index[btc.isna()]
    repaired = []
    if len(missing):
        fresh = get_price_history("BTC-USD", start=missing.min().strftime("%Y-%m-%d"),
                                  end=(missing.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                                  interval="1d", use_cache=False)
        fresh.index = pd.DatetimeIndex(fresh.index).tz_localize(None).normalize()
        patch = fresh["Close"].reindex(missing)
        btc.loc[missing] = patch
        repaired = [str(d.date()) for d in missing[patch.notna()]]
    if btc.isna().any():
        raise ValueError(f"BTC 달력 일봉 누락: {list(btc.index[btc.isna()][:10])}")
    if prices_core[["BIL", "SPY"]].isna().any().any() or str(core.index[-1].date()) != END:
        raise ValueError("기준선 BIL/SPY 가격 또는 종료일 누락")
    weights = bt["core"]["weights"].reindex(core.index)
    if (prices_core[weights.columns].isna() & weights.shift(1).fillna(0).gt(0)).any().any():
        raise ValueError("코어 보유 가격 결측")
    parts = cp.sleeve_contributions(prices_core[weights.columns], weights, cs.CORE_COST_BPS_PER_SIDE)["contrib"]
    if (parts.sum(axis=1) - core).abs().max() > 1e-9:
        raise ValueError("코어 기여 대조 실패")
    sat_prices = cs._closes_from_histories(hist, bt["satellite"]["tickers_ever_held"]).reindex(core.index).ffill()
    sat_weights = cp._satellite_weights_from_log(bt["satellite"]["rebal_log"], sat_prices)
    sat_parts = cp.sleeve_contributions(sat_prices, sat_weights, cs.SATELLITE_COST_BPS_PER_SIDE)["contrib"]
    if (sat_parts.sum(axis=1) - sat).abs().max() > 1e-9:
        raise ValueError("새틀라이트 기여 대조 실패")
    spy = prices_core["SPY"].pct_change(fill_method=None).fillna(0)
    cash = prices_core["BIL"].pct_change(fill_method=None).fillna(0)
    metadata = {"source": "Yahoo Finance via yfinance", "data_start": DATA_START, "end": END,
                "calendar_days": len(calendar), "repaired_dates": repaired}
    return core, sat, cash, btc, spy, metadata


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    out, ck = Path(args.out), Path(args.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, stop)
    from core import market_data as md
    fingerprint = hashlib.sha256(Path(__file__).read_bytes() + Path(__file__).with_name("SPEC.md").read_bytes()
                                 + Path(cs.__file__).read_bytes() + Path(cp.__file__).read_bytes()
                                 + Path(md.__file__).read_bytes()).hexdigest()
    path = ck / ("smoke.pkl" if args.smoke else "real.pkl")
    saved = pickle.loads(path.read_bytes()) if path.exists() else {}
    if saved and saved["contract"] != fingerprint:
        raise ValueError("체크포인트 계약 불일치: 새 ID 필요")
    if not saved:
        saved = {"contract": fingerprint, "input": inputs(args.smoke)}
        atomic(path, saved)
    if STOP or time.time() > float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH", "inf")) - 45:
        return 3
    core, sat, cash, btc, spy, metadata = saved["input"]
    coin_calendar = pd.date_range(DATA_START, END)
    prices = btc.reindex(coin_calendar)
    candidates, stress = make_candidates(core, sat, cash, prices)
    keep = (core.index >= START) & (core.index <= END)
    core, sat, cash, spy = (x.loc[keep] for x in (core, sat, cash, spy))
    candidates = {k: v.loc[keep] for k, v in candidates.items()}
    stress = {k: v.loc[keep] for k, v in stress.items()}
    base = .85 * core + .15 * sat
    verdicts = evaluate(base, candidates, stress)
    btc_properties = properties(prices.to_frame("BTC-USD"), base, core, spy)
    hashes = [hashlib.sha256(pd.util.hash_pandas_object(v, index=True).values.tobytes()).hexdigest()
              for v in saved["input"][:5]]
    payload = {"id": JOB_ID, "smoke": args.smoke, "contract_sha256": fingerprint,
               "input_sha256": hashes, "start": START, "end": END, "splits": SPLITS,
               "crypto_data": metadata, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
               "baseline": metrics(base), "btc_characteristics": btc_properties,
               "candidates": verdicts,
               "verdicts": {k: "SMOKE_ONLY" if args.smoke else v["verdict"] for k, v in verdicts.items()}}
    lines = ["# BTC 특성·비중·매수/매도 규칙 연구", "",
             "합성 스모크 — 실제 성과 아님" if args.smoke else "탐색 연구 — 통과해도 전진검증 후보이며 자동 반영 없음", "",
             f"기간 {START}~{END} · 기준선 코어 85% + 새틀라이트 15%", "",
             "## BTC 특성", "", "```json", json.dumps(btc_properties["BTC-USD"], ensure_ascii=False, indent=2), "```", "",
             "## 후보 결과", "", "| ID | 판정 | 전체 CAGR 차이 | MDD 차이 | 2023~ IR | 50bp 비용 CAGR 차이 | 통과하지 못한 관문 |",
             "|---|---|---:|---:|---:|---:|---|"]
    for cid, row in verdicts.items():
        gates = ", ".join(k for k, passed in row["gates"].items() if not passed) or "없음"
        lines.append(f"| {cid} | {'SMOKE_ONLY' if args.smoke else row['verdict']} | {row['cagr_delta']:+.2%} | {row['mdd_delta']:+.2%} | {row['late_ir']:.2f} | {row['stress_cagr_delta']:+.2%} | {gates} |")
    lines += ["", "기간별 수익, 입력·보완 데이터 출처와 해시는 results.json에 기록한다. 지표 정의와 판정 한계는 같은 폴더 SPEC.md 참조.",
              "BTC 실제 편입은 별도 사용자 확인 및 전진검증 이후에만 다룬다."]
    tmp = out / "results.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    os.replace(tmp, out / "results.json")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
