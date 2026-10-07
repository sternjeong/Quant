from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core import core_lab as cl  # noqa: E402
from core.champion_strategy import CORE_UNIVERSE, MARKET_FILTER_TICKER  # noqa: E402

START = "2008-01-01"
FETCH_START = "2006-01-01"
ASSETS = {"IWM": "미국 소형주", "TIP": "물가연동국채", "VNQ": "미국 리츠", "VWO": "신흥국 주식", "LQD": "투자등급 회사채"}
VARIANTS = {**{f"add_{t.lower()}": (t,) for t in ASSETS}, "add_all_five": tuple(ASSETS)}
BASE = cl.CoreConfig()


def load_prices(smoke: bool):
    tickers = list(dict.fromkeys([*CORE_UNIVERSE, MARKET_FILTER_TICKER, cl.CASH_ETF, *cl.CREDIT_PAIR, *ASSETS]))
    if smoke:
        ix = pd.bdate_range("2008-01-01", "2026-09-30")
        rng = np.random.default_rng(260107)
        px = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(.0002, .01, len(ix)))) for t in tickers}, index=ix)
        px[cl.CASH_ETF] = 90
        adj = px * 1.0001
        return px, adj
    from core.market_data import get_multiple_price_history
    hist = get_multiple_price_history(tickers, start=FETCH_START, end=None, interval="1d")
    px = pd.DataFrame({t: hist[t]["Close"] for t in tickers if t in hist and not hist[t].empty})
    adj = pd.DataFrame({t: hist[t].get("Adj Close", hist[t]["Close"]) for t in tickers if t in hist and not hist[t].empty})
    return px, adj


def run_one(px, adj, additions):
    core = [t for t in CORE_UNIVERSE if t in px]
    extras = [t for t in [MARKET_FILTER_TICKER, cl.CASH_ETF, *cl.CREDIT_PAIR, *additions] if t in px and t not in core]
    total_core = [t for t in core if t in adj]
    total_extra = [t for t in extras if t in adj]
    return cl.run(px[core], px[extras], cl.with_changes(BASE, extra_assets=tuple(additions)), START,
                  total=(adj[total_core], adj[total_extra]))


def run_cost_stress(px, adj, additions, bps):
    core = [t for t in CORE_UNIVERSE if t in px]
    extras = [t for t in [MARKET_FILTER_TICKER, cl.CASH_ETF, *cl.CREDIT_PAIR, *additions] if t in px and t not in core]
    cfg = cl.with_changes(BASE, extra_assets=tuple(additions))
    weights = cl.build_weights(px[core], px[extras], cfg)
    total_core = [t for t in core if t in adj]
    total_extra = [t for t in extras if t in adj]
    return cl.portfolio_returns(adj[total_core], adj[total_extra], weights.reindex(adj.index).fillna(0.0), bps=bps)


def report(payload):
    lines = ["# 부족 자산군 ETF 후보 확장 연구", "", f"생성 {payload['generated_at']} · 공통 기간 {payload.get('period', ['—','—'])[0]} ~ {payload.get('period', ['—','—'])[1]}", "",
             "추가 후보는 연구용이다. PASS_REVIEW_ONLY는 챔피언 편입 승인이 아니다.", "", "| 후보 | 자산군 | 판정 | CAGR | 샤프 | 최대낙폭 | 미충족 관문 |", "|---|---|---:|---:|---:|---:|---|"]
    for key, row in payload["candidates"].items():
        st = row.get("stats", {})
        pct = lambda x: "—" if x is None else f"{100*x:.1f}%"
        lines.append(f"| {', '.join(row['assets'])} | {row['category']} | **{row['verdict']}** | {pct(st.get('cagr'))} | {st.get('sharpe_annual', float('nan')):.2f} | {pct(st.get('max_drawdown'))} | {', '.join(row.get('reasons', [])) or '—'} |")
    lines += ["", "데이터 부족 또는 공통 평가기간 8년 미만이면 NOT_EVALUABLE_DATA로 표기한다. 전체 결과는 VM에서 계산한다."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True); p.add_argument("--checkpoint", required=True); p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    px, adj = load_prices(a.smoke)
    missing_core = [t for t in [*CORE_UNIVERSE, MARKET_FILTER_TICKER] if t not in px or t not in adj]
    base = run_one(px, adj, ())
    eval_start = "2011-01-03" if a.smoke else START
    base = base.loc[base.index >= pd.Timestamp(eval_start)]
    split = cl.holdout_split(base.index) if len(base) else pd.Timestamp(START)
    candidates = {}
    for key, additions in VARIANTS.items():
        missing = [t for t in additions if t not in px or t not in adj]
        if missing_core or missing:
            candidates[key] = {"assets": list(additions), "category": ", ".join(ASSETS[t] for t in additions), "verdict": "NOT_EVALUABLE_DATA", "reasons": ["필수 자산 가격 열 누락"], "stats": {}}
            continue
        r = run_one(px, adj, additions).loc[lambda s: s.index >= pd.Timestamp(eval_start)]
        idx = base.index.intersection(r.index)
        r, b = r.loc[idx], base.loc[idx]
        if len(idx) < 8 * 252:
            candidates[key] = {"assets": list(additions), "category": ", ".join(ASSETS[t] for t in additions), "verdict": "NOT_EVALUABLE_DATA", "reasons": ["공통 평가기간 8년 미만"], "stats": cl.stats(r)}
            continue
        # core-judge gates are calculated for the fixed six hypotheses; the declared cost stress is separate.
        res = cl.judge({"returns": r}, b, [], n_trials=6, all_active_daily_srs=[])
        stress_r = run_cost_stress(px, adj, additions, 8).loc[idx]
        stress_b = run_cost_stress(px, adj, (), 8).loc[idx]
        stress_is = cl.stats((stress_r - stress_b)[idx < split])
        stress_pass = stress_is.get("cagr", 0.0) > 0
        verdict = "SMOKE_ONLY" if a.smoke else ("PASS_REVIEW_ONLY" if res["verdict"] == "PASS" and stress_pass else "FAIL")
        reasons = list(res.get("reasons", []))
        if not stress_pass:
            reasons.append("편도 8bp 비용 스트레스 IS 초과 CAGR ≤ 0")
        candidates[key] = {"assets": list(additions), "category": ", ".join(ASSETS[t] for t in additions), "verdict": verdict,
                           "reasons": reasons, "stats": cl.stats(r), "gates": res.get("gates"), "cost_stress_8bp_is_active": stress_is}
    payload = {"id": "core-universe-expansion-v1", "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "period": [str(base.index[0].date()), str(base.index[-1].date())] if len(base) else [], "missing_tickers": missing_core,
               "candidate_count": 6, "baseline": cl.stats(base), "candidates": candidates,
               "verdicts": {k: v["verdict"] for k, v in candidates.items()}}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
