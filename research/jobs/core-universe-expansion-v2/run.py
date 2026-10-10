"""core-universe-expansion-v2 — v1 의 배관 버그를 고친 재실행(사전 등록 질문·후보·관문은 v1 과 같다).

v1 버그(2026-10-10 발견): 추가 ETF 를 `extra` 프레임에만 넘겨서 core_lab._tranche_weights 의 순위 후보
(`closes` 의 열만 본다)에 들어가지 않았다. 그래서 모든 후보의 수익이 기준선과 매일 같았고 FAIL 판정은 무효다.
v2 는 추가 ETF 를 `closes`(순위 후보)와 총수익 `closes` 쪽에 넣는다(core/forward_tournament.py 와 같은 방식).

추가된 것(판정 설계 규칙, docs/RESEARCH_JOBS.md):
- noop_guard: 활성 수익이 매일 0 이면 FAIL 이 아니라 NOT_EVALUABLE_NOOP.
- power_report(앞 구간 연수, 6) → results.json "power", power_line → REPORT.md.
- FAIL 이면 classify_fail 로 fail_kind(FAIL / FAIL_UNDERPOWERED)를 따로 적는다(판정은 FAIL 그대로).
- 진단: 후보마다 추가 ETF 가 실제로 고른 리밸런싱 달의 비율(배관 수정이 실제 데이터에서 작동했는지 증거).
PASS_REVIEW_ONLY 는 '전진 원장에 올릴 후보'까지만 뜻한다. 채택·챔피언 편입이 아니다.
"""

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
from core import research_power as rp  # noqa: E402
from core.champion_strategy import CORE_UNIVERSE, MARKET_FILTER_TICKER  # noqa: E402

JOB_ID = "core-universe-expansion-v2"
START = "2008-01-01"
FETCH_START = "2006-01-01"
ASSETS = {"IWM": "미국 소형주", "TIP": "물가연동국채", "VNQ": "미국 리츠", "VWO": "신흥국 주식", "LQD": "투자등급 회사채"}
VARIANTS = {**{f"add_{t.lower()}": (t,) for t in ASSETS}, "add_all_five": tuple(ASSETS)}
N_TRIALS = 6               # 사전 등록 가설 수(v1 과 같음)
STRESS_BPS = 8             # 편도 비용 스트레스(v1 과 같음)
MIN_COMMON_DAYS = 8 * 252  # 공통 평가 8년 미만이면 NOT_EVALUABLE_DATA(v1 과 같음)
SMOKE_EVAL_START = "2011-01-03"
BASE = cl.CoreConfig()


# ---------------------------------------------------------------------------------------------
# 데이터
# ---------------------------------------------------------------------------------------------

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


def frames(px: pd.DataFrame, additions) -> tuple[list[str], list[str]]:
    """(순위 후보 열, 보조 열). v1 버그 수정: 추가 ETF 는 순위 후보(closes) 쪽에 들어가야 한다."""
    ranked = [t for t in [*CORE_UNIVERSE, *additions] if t in px]
    ranked = list(dict.fromkeys(ranked))
    extras = [t for t in [MARKET_FILTER_TICKER, cl.CASH_ETF, *cl.CREDIT_PAIR] if t in px and t not in ranked]
    return ranked, extras


def config_for(additions) -> cl.CoreConfig:
    return cl.with_changes(BASE, extra_assets=tuple(additions))


def run_one(px: pd.DataFrame, adj: pd.DataFrame, additions, start: str = START) -> pd.Series:
    """신호는 Close, 수익은 Adj Close(분배금 포함) — v1 과 같은 데이터 처리."""
    ranked, extras = frames(px, additions)
    t_ranked = [t for t in ranked if t in adj]
    t_extras = [t for t in extras if t in adj]
    return cl.run(px[ranked], px[extras], config_for(additions), start, total=(adj[t_ranked], adj[t_extras]))


def weights_for(px: pd.DataFrame, additions) -> pd.DataFrame:
    ranked, extras = frames(px, additions)
    return cl.build_weights(px[ranked], px[extras], config_for(additions))


def cost_stress(adj: pd.DataFrame, px: pd.DataFrame, weights: pd.DataFrame, additions, bps: float = STRESS_BPS) -> pd.Series:
    """v1 의 run_cost_stress 와 같은 계산(가격 신호 비중, 총수익, 편도 bps) — 추가 ETF 는 순위 후보 쪽."""
    ranked, extras = frames(px, additions)
    t_ranked = [t for t in ranked if t in adj]
    t_extras = [t for t in extras if t in adj]
    return cl.portfolio_returns(adj[t_ranked], adj[t_extras], weights.reindex(adj.index).fillna(0.0), bps=bps)


def selection_diagnostics(weights: pd.DataFrame, additions, eval_start: str) -> dict:
    """평가 기간의 리밸런싱 달 중 추가 ETF 가 실제로 비중 > 0 으로 뽑힌 달의 비율."""
    mask = cl._first_trading_day_mask(weights.index, 0)
    mask.iloc[0] = False  # _tranche_weights 는 i > 0 에서만 리밸런싱한다
    days = weights.index[mask.to_numpy() & (weights.index >= pd.Timestamp(eval_start))]
    out = {}
    for t in additions:
        if t not in weights.columns:
            out[t] = {"rebalance_months": int(len(days)), "selected_months": 0, "selected_fraction": 0.0,
                      "note": "비중 열 없음(순위 후보에 들어가지 않음)"}
            continue
        sel = int((weights.loc[days, t] > 1e-12).sum())
        out[t] = {"rebalance_months": int(len(days)), "selected_months": sel,
                  "selected_fraction": round(sel / len(days), 4) if len(days) else 0.0}
    return out


# ---------------------------------------------------------------------------------------------
# 판정(사전 등록 — 결과를 보기 전 고정)
# ---------------------------------------------------------------------------------------------

def decide(active: pd.Series, judge_res: dict, stress_pass: bool, power: dict, smoke: bool) -> dict:
    """후보 판정. 순서: 무효 실행(NOT_EVALUABLE_NOOP) → 스모크(SMOKE_ONLY) → core-judge/v1 + 비용 스트레스."""
    reasons = list(judge_res.get("reasons", []))
    if not stress_pass:
        reasons.append(f"편도 {STRESS_BPS}bp 비용 스트레스 IS 초과 CAGR ≤ 0")
    noop = rp.noop_guard(list(active.to_numpy()))
    if noop:
        return {"verdict": "NOT_EVALUABLE_NOOP", "fail_kind": None, "reasons": [noop], "would_be_reasons": reasons}
    raw = "PASS_REVIEW_ONLY" if (judge_res.get("verdict") == "PASS" and stress_pass) else "FAIL"
    observed_ir = (judge_res.get("gates", {}).get("G1_improves_corrected", {}) or {}).get("active_sharpe_annual")
    fail_kind = rp.classify_fail(observed_ir, power) if raw == "FAIL" else None
    if smoke:
        return {"verdict": "SMOKE_ONLY", "fail_kind": None, "reasons": reasons, "would_be_verdict": raw, "would_be_fail_kind": fail_kind}
    return {"verdict": raw, "fail_kind": fail_kind, "reasons": reasons}


# ---------------------------------------------------------------------------------------------
# 보고
# ---------------------------------------------------------------------------------------------

def report(payload: dict) -> str:
    per = payload.get("period") or ["—", "—"]
    lines = ["# 부족 자산군 ETF 후보 확장 연구 v2 (v1 배관 버그 수정 재실행)", "",
             f"생성 {payload['generated_at']} · 공통 기간 {per[0]} ~ {per[-1]}" + (" · **스모크(합성 데이터)**" if payload.get("smoke") else ""), "",
             "v1(core-universe-expansion-v1)은 추가 ETF 가 순위 후보에 들어가지 않아 모든 후보가 기준선과 같았다 — v1 판정은 무효. "
             "v2 는 추가 ETF 를 순위 후보·총수익 프레임에 넣어 같은 사전 등록 질문·관문으로 다시 판정한다.", "",
             "**PASS_REVIEW_ONLY 는 '전진 원장에 올릴 후보'까지만 뜻한다.** 채택·챔피언 편입 승인이 아니며 성과를 보장하지 않는다.", ""]
    if payload.get("power"):
        lines += [rp.power_line(payload["power"]), ""]
    lines += ["| 후보 | 자산군 | 판정 | FAIL 성격 | CAGR | 샤프 | 최대낙폭 | IS 활성 IR | 추가 ETF 선택 달 비율 | 미충족 관문 |",
              "|---|---|---:|---|---:|---:|---:|---:|---|---|"]
    pct = lambda x: "—" if x is None else f"{100 * x:.1f}%"  # noqa: E731
    for row in payload["candidates"].values():
        st = row.get("stats", {})
        sh = st.get("sharpe_annual")
        ir = ((row.get("gates") or {}).get("G1_improves_corrected") or {}).get("active_sharpe_annual")
        sel = ", ".join(f"{t} {100 * d['selected_fraction']:.0f}%" for t, d in (row.get("selection") or {}).items()) or "—"
        lines.append(f"| {', '.join(row['assets'])} | {row['category']} | **{row['verdict']}** | {row.get('fail_kind') or '—'} | "
                     f"{pct(st.get('cagr'))} | {'—' if sh is None else f'{sh:.2f}'} | {pct(st.get('max_drawdown'))} | "
                     f"{'—' if ir is None else f'{ir:.2f}'} | {sel} | {', '.join(row.get('reasons', [])) or '—'} |")
    lines += ["",
              "- NOT_EVALUABLE_NOOP: 후보 수익이 기준선과 매일 같음(후보 설정이 계산에 반영되지 않음) — FAIL 이 아니다.",
              "- FAIL_UNDERPOWERED: FAIL 이지만 관측 IS 활성 IR 이 최소 검출 효과(MDE)보다 작고 양수 — '효과 없음'이 아니라 판별 불가에 가깝다.",
              "- NOT_EVALUABLE_DATA: 가격 열 누락 또는 공통 평가기간 8년 미만.",
              "- G2(떼어 둔 2년)는 v1 사전 등록과 같게 유지했다. 2024-10 이후 구간은 이미 여러 연구가 본 구간이라 정직한 시험대가 아니다(판정 설계 규칙 3).",
              "- 전체 결과는 VM 연구 실행기에서 계산한다."]
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

    px, adj = load_prices(a.smoke)
    missing_core = [t for t in [*CORE_UNIVERSE, MARKET_FILTER_TICKER] if t not in px or t not in adj]
    eval_start = SMOKE_EVAL_START if a.smoke else START
    base = run_one(px, adj, ())
    base = base.loc[base.index >= pd.Timestamp(eval_start)]
    split = cl.holdout_split(base.index) if len(base) else pd.Timestamp(START)
    # 검정력은 기준선 날짜(앞 구간 길이)만으로 계산한다 — 후보 결과와 무관(결과 전 고정).
    years_is = float((base.index < split).sum()) / cl.TRADING_DAYS if len(base) else 0.0
    power = rp.power_report(years_is, N_TRIALS)
    base_w = weights_for(px, ())
    stress_b_full = cost_stress(adj, px, base_w, ())

    candidates = {}
    for key, additions in VARIANTS.items():
        row = {"assets": list(additions), "category": ", ".join(ASSETS[t] for t in additions)}
        missing = [t for t in additions if t not in px or t not in adj]
        if missing_core or missing:
            candidates[key] = {**row, "verdict": "NOT_EVALUABLE_DATA", "fail_kind": None, "reasons": ["필수 자산 가격 열 누락"], "stats": {}}
            continue
        r = run_one(px, adj, additions)
        r = r.loc[r.index >= pd.Timestamp(eval_start)]
        idx = base.index.intersection(r.index)
        r, b = r.loc[idx], base.loc[idx]
        w = weights_for(px, additions)
        selection = selection_diagnostics(w, additions, eval_start)
        if len(idx) < MIN_COMMON_DAYS:
            candidates[key] = {**row, "verdict": "NOT_EVALUABLE_DATA", "fail_kind": None, "reasons": ["공통 평가기간 8년 미만"],
                               "stats": cl.stats(r), "selection": selection}
            continue
        active = r - b
        res = cl.judge({"returns": r}, b, [], n_trials=N_TRIALS, all_active_daily_srs=[])
        stress_r = cost_stress(adj, px, w, additions).loc[idx]
        stress_is = cl.stats((stress_r - stress_b_full.loc[idx])[idx < split])
        stress_pass = stress_is.get("cagr", 0.0) > 0
        dec = decide(active, res, stress_pass, power, a.smoke)
        candidates[key] = {**row, **dec, "stats": cl.stats(r), "gates": res.get("gates"),
                           f"cost_stress_{STRESS_BPS}bp_is_active": stress_is, "selection": selection,
                           "active_nonzero_days": int((active.abs() > 1e-12).sum())}

    payload = {"id": JOB_ID, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "supersedes": "core-universe-expansion-v1 (배관 버그로 무효 — 추가 ETF 가 순위 후보에 없었음)",
               "judge_version": cl.JUDGE_VERSION, "n_trials": N_TRIALS,
               "period": [str(base.index[0].date()), str(base.index[-1].date())] if len(base) else [],
               "holdout_split": str(split.date()), "missing_tickers": missing_core, "power": power,
               "candidate_count": len(VARIANTS), "baseline": cl.stats(base), "candidates": candidates,
               "verdicts": {k: v["verdict"] for k, v in candidates.items()},
               "fail_kinds": {k: v.get("fail_kind") for k, v in candidates.items() if v.get("fail_kind")},
               "pass_meaning": "PASS_REVIEW_ONLY = 전진 원장 후보(채택 아님)"}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
