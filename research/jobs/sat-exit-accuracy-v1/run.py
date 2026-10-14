"""새틀라이트 매도 신호 정확도 검증 — 4개 고정 규칙, 결과 후 파라미터 탐색 금지."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import satellite_lab as sl  # noqa: E402

DATA_START = "2010-01-01"
DECISION_END = pd.Timestamp("2024-09-30")
SPLIT = pd.Timestamp("2017-06-01")
N_TRIALS = 4
BOOTSTRAPS = 5000
BOOTSTRAP_SEED = 20261012
COST = 8.0 / 10_000.0  # S-SEED-000 incumbent cost, fixed at 8bp per side.
RULES = ("trail10", "mom6_nonpositive", "rs12_nonpositive", "mom6_and_rs12_nonpositive")
LABELS = {
    "trail10": "고점 대비 10% 하락",
    "mom6_nonpositive": "6개월 총수익률 0 이하",
    "rs12_nonpositive": "12개월 SPY 상대수익률 0 이하",
    "mom6_and_rs12_nonpositive": "6개월 모멘텀·12개월 상대강도 동시 0 이하",
}


def _atomic_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _load_data(smoke: bool):
    if smoke:
        price_provider, pool_provider = sl.synthetic_providers(
            n_tickers=40, start="2008-01-01", end="2026-09-30", seed=20261012
        )
        data = sl.build_data(
            {"champion40"}, start=DATA_START, end="2026-09-30", pool_provider=pool_provider,
            price_provider=price_provider, calendar_ticker="SPY",
        )
        spy_frame = price_provider("SPY", "2008-01-01", "2026-09-30")
    else:
        data = sl.build_data({"champion40"}, start=DATA_START)
        from core import hypothesis_engine as he

        end = data.trading_days[-1].date().isoformat()
        spy_map = he.load_prices(["SPY"], date.fromisoformat("2008-01-01"), date.fromisoformat(end))
        spy_frame = spy_map.get("SPY")
    if spy_frame is None or spy_frame.empty:
        raise RuntimeError("SPY 가격 이력을 읽지 못함")
    spy_field = "Adj Close" if "Adj Close" in spy_frame and spy_frame["Adj Close"].notna().any() else "Close"
    # Keep the 800-day warm-up history supplied by satellite_lab; signals need it.
    spy = pd.to_numeric(spy_frame[spy_field], errors="coerce").dropna().sort_index()
    return data, spy


def _series(df: pd.DataFrame, column: str, index: pd.DatetimeIndex) -> pd.Series:
    if column not in df:
        return pd.Series(np.nan, index=index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").reindex(index).ffill(limit=2)


def _first_exit(rule: str, ticker: str, start_i: int, end_i: int, days: pd.DatetimeIndex,
                raw_map: dict, total_map: dict, spy: pd.Series):
    raw = raw_map[ticker]
    total = total_map[ticker]
    start_date, end_date = days[start_i], days[end_i]
    first_date = days[min(start_i + 1, len(days) - 1)]
    candidate_dates = days[(days >= first_date) & (days < end_date)]
    raw_idx, total_idx = raw.index, total.index
    spy_idx = spy.index
    entry_raw_i = raw_idx.searchsorted(start_date)
    if entry_raw_i >= len(raw_idx):
        return None
    for signal_date in candidate_dates:
        raw_i = raw_idx.searchsorted(signal_date)
        total_i = total_idx.searchsorted(signal_date)
        if raw_i >= len(raw_idx) or raw_idx[raw_i] != signal_date or total_i >= len(total_idx) or total_idx[total_i] != signal_date:
            continue
        c = raw.iloc[raw_i]
        if not np.isfinite(c):
            continue
        mom6 = False
        rs12 = False
        if total_i >= 126 and np.isfinite(total.iloc[total_i]) and np.isfinite(total.iloc[total_i - 126]) and total.iloc[total_i - 126] > 0:
            mom6 = total.iloc[total_i] / total.iloc[total_i - 126] - 1.0 <= 0.0
        if total_i >= 252:
            spy_i = spy_idx.searchsorted(signal_date)
            if spy_i >= len(spy_idx) or spy_idx[spy_i] != signal_date or spy_i < 252:
                spy_i = -1
            s0, s1 = total.iloc[total_i - 252], total.iloc[total_i]
            m0, m1 = (spy.iloc[spy_i - 252], spy.iloc[spy_i]) if spy_i >= 0 else (np.nan, np.nan)
            if all(np.isfinite(x) for x in (s0, s1, m0, m1)) and min(s0, m0) > 0:
                rs12 = (s1 / s0 - 1.0) <= (m1 / m0 - 1.0)
        if rule == "trail10":
            trail = raw.iloc[entry_raw_i:raw_i + 1].dropna()
            hit = bool(len(trail) and c <= float(trail.max()) * 0.90)
        elif rule == "mom6_nonpositive":
            hit = mom6
        elif rule == "rs12_nonpositive":
            hit = rs12
        else:
            hit = mom6 and rs12
        fill_pos_calendar = days.searchsorted(signal_date) + 1
        if fill_pos_calendar >= len(days):
            continue
        fill_date = days[fill_pos_calendar]
        fill_i = total_idx.searchsorted(fill_date)
        if hit and fill_date < end_date and fill_i < len(total_idx) and total_idx[fill_i] == fill_date and np.isfinite(total.iloc[fill_i]):
            return signal_date, fill_date
    return None


def _bootstrap(candidate_rows: list[dict], alpha: float) -> dict:
    """반기 코호트를 함께 재표집해 종목 간 동시 충격을 보존한다."""
    n = len(candidate_rows)
    if n == 0:
        return {"n_cohorts": 0, "mean_delta": None, "delta_lower": None,
                "precision": None, "precision_lower": None}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    deltas, precisions = [], []
    row_events = [r["events"] for r in candidate_rows]
    for _ in range(BOOTSTRAPS):
        ix = rng.integers(0, n, n)
        deltas.append(float(np.mean([candidate_rows[int(i)]["mean_delta"] for i in ix])))
        ev = [ok for i in ix for ok in row_events[int(i)]]
        if ev:
            precisions.append(float(np.mean(ev)))
    events = [ok for group in row_events for ok in group]
    return {
        "n_cohorts": n,
        "mean_delta": float(np.mean([r["mean_delta"] for r in candidate_rows])),
        "delta_lower": float(np.quantile(deltas, alpha)),
        "n_exit_events": len(events),
        "precision": float(np.mean(events)) if events else None,
        "precision_lower": float(np.quantile(precisions, alpha)) if precisions else None,
    }


def _build_cohorts(data, spy: pd.Series, smoke: bool) -> tuple[list[dict], dict]:
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    signal = sl.load_signal(code)
    incumbent = sl.run_variant(spec, spec["signal"]["params_grid"][0], signal, data)
    schedule = [(pd.Timestamp(d), list(picks)) for d, picks in incumbent["schedule"]]
    days = data.trading_days
    pos_by_date = {d: i for i, d in enumerate(days)}
    raw_map = {t: _series(df, "Close", df.index) for t, df in data.ohlcv.items()}
    total_map = {t: _series(df, "Adj Close", df.index) if "Adj Close" in df and df["Adj Close"].notna().any()
                 else _series(df, "Close", df.index) for t, df in data.ohlcv.items() if t in data.closes.columns}
    scheduled_slots = usable_slots = censored_slots = 0
    decision_scheduled = decision_usable = decision_censored = 0
    cohorts: list[dict] = []
    for j in range(len(schedule) - 1):
        start, picks = schedule[j]
        end, _ = schedule[j + 1]
        if start < pd.Timestamp(DATA_START) or start not in pos_by_date or end not in pos_by_date:
            continue
        start_i, end_i = pos_by_date[start], pos_by_date[end]
        if end_i - start_i < 100:
            continue
        slot_rows = []
        for ticker in picks:
            scheduled_slots += 1
            is_decision_slot = end <= DECISION_END
            decision_scheduled += int(is_decision_slot)
            if ticker not in raw_map or ticker not in total_map:
                censored_slots += 1
                decision_censored += int(is_decision_slot)
                continue
            raw, total = raw_map[ticker], total_map[ticker]
            ix0, ix1 = total.index.searchsorted(start), total.index.searchsorted(end)
            entry = total.iloc[ix0] if ix0 < len(total) and total.index[ix0] == start else np.nan
            finish = total.iloc[ix1] if ix1 < len(total) and total.index[ix1] == end else np.nan
            # Pair every policy on the same complete entry/end population. Long gaps are censored,
            # since forward-filling a delisting price would silently turn it into a flat position.
            window = total.loc[(total.index >= start) & (total.index <= end)].reindex(days[start_i:end_i + 1]).ffill(limit=2)
            if (not np.isfinite(entry) or entry <= 0 or not np.isfinite(finish) or finish <= 0
                    or window.isna().mean() > 0.10):
                censored_slots += 1
                decision_censored += int(is_decision_slot)
                continue
            usable_slots += 1
            decision_usable += int(is_decision_slot)
            base_value = (1.0 - COST) * (finish / entry) * (1.0 - COST)
            slot = {"ticker": ticker, "base_net": float(base_value - 1.0), "policies": {}}
            for rule in RULES:
                hit = _first_exit(rule, ticker, start_i, end_i, days, raw_map, total_map, spy)
                if hit is None:
                    slot["policies"][rule] = {"net": slot["base_net"], "event": None, "early": False}
                    continue
                signal_date, fill_date = hit
                fill_pos = total.index.searchsorted(fill_date)
                fill = total.iloc[fill_pos] if fill_pos < len(total) and total.index[fill_pos] == fill_date else np.nan
                if not np.isfinite(fill) or fill <= 0:
                    slot["policies"][rule] = {"net": slot["base_net"], "event": None, "early": False}
                    continue
                net = (1.0 - COST) * (fill / entry) * (1.0 - COST) - 1.0
                after_exit_hold = (1.0 - COST) * (finish / fill) - 1.0
                event_correct = bool(after_exit_hold <= 0.0)
                days_left = end_i - pos_by_date[fill_date]
                slot["policies"][rule] = {
                    "net": float(net), "event": event_correct,
                    "false_exit_upside": max(0.0, float(after_exit_hold)),
                    "early": bool(days_left >= 20), "signal_date": signal_date.date().isoformat(),
                    "fill_date": fill_date.date().isoformat(),
                }
            slot_rows.append(slot)
        if not slot_rows:
            continue
        row = {"start": start, "end": end, "slots": slot_rows}
        row["base_mean"] = float(np.mean([s["base_net"] for s in slot_rows]))
        row["results"] = {}
        for rule in RULES:
            outcomes = [s["policies"][rule] for s in slot_rows]
            nets = [x["net"] for x in outcomes]
            events = [x["event"] for x in outcomes if x["event"] is not None]
            losing_base = [s for s in slot_rows if s["base_net"] < 0]
            early_losses = [s for s in losing_base if s["policies"][rule]["early"]]
            row["results"][rule] = {
                "mean_net": float(np.mean(nets)),
                "mean_delta": float(np.mean(nets) - row["base_mean"]),
                "events": events,
                "false_exit_upside": [x["false_exit_upside"] for x in outcomes if x.get("event") is False],
                "losing_slots": len(losing_base),
                "early_losses": len(early_losses),
            }
        cohorts.append(row)
    return cohorts, {"scheduled_slots": decision_scheduled, "usable_slots": decision_usable,
                     "censored_slots": censored_slots,
                     "coverage": decision_usable / decision_scheduled if decision_scheduled else 0.0,
                     "all_period_scheduled_slots": scheduled_slots,
                     "all_period_usable_slots": usable_slots,
                     "all_period_censored_slots": censored_slots,
                     "smoke": smoke}


def _eval_rule(rule: str, cohorts: list[dict], years: float) -> dict:
    alpha = 0.05 / N_TRIALS
    rows = [{"mean_delta": c["results"][rule]["mean_delta"], "events": c["results"][rule]["events"]}
            for c in cohorts]
    boot = _bootstrap(rows, alpha)
    deltas = np.asarray([r["mean_delta"] for r in rows], dtype=float)
    sd = float(deltas.std(ddof=1)) if len(deltas) > 1 else 0.0
    observed_ir = float(deltas.mean() / sd * math.sqrt(2.0)) if sd > 0 else 0.0
    power = rp.power_report(years, N_TRIALS)
    event_n = boot["n_exit_events"]
    event_cohorts = sum(bool(c["results"][rule]["events"]) for c in cohorts)
    positive_periods = {}
    for name, lo, hi in (("A", pd.Timestamp(DATA_START), SPLIT), ("B", SPLIT, DECISION_END)):
        part = [c["results"][rule]["mean_delta"] for c in cohorts if lo <= c["start"] < hi]
        positive_periods[name] = float(np.mean(part)) if part else None
    losing = sum(c["results"][rule]["losing_slots"] for c in cohorts)
    early_losses = sum(c["results"][rule]["early_losses"] for c in cohorts)
    false = [x for c in cohorts for x in c["results"][rule]["false_exit_upside"]]
    noop = rp.noop_guard(deltas)
    if len(cohorts) < 10:
        verdict = "NOT_EVALUABLE_DATA"
        reasons = ["최종 판정 구간의 완결 반기 코호트가 사전 최소치 10개 미달"]
    elif noop:
        verdict = "NOT_EVALUABLE"
        reasons = [noop]
    elif event_n < 20 or event_cohorts < 12:
        verdict = "FAIL_UNDERPOWERED"
        reasons = [f"매도 이벤트 {event_n}건·코호트 {event_cohorts}개로 사전 최소치(20·12) 미달"]
    else:
        passed = (boot["precision_lower"] is not None and boot["precision_lower"] > 0.50
                  and boot["mean_delta"] > 0 and boot["delta_lower"] > 0
                  and all(positive_periods[k] is not None and positive_periods[k] > 0 for k in ("A", "B")))
        verdict = "PASS_FORWARD_CANDIDATE" if passed else rp.classify_fail(observed_ir, power)
        reasons = [] if passed else [
            f"정확도 보정 하한 {boot['precision_lower']:.1%} (기준 >50%)",
            f"반기당 평균 순 개선 {boot['mean_delta'] * 10000:+.1f}bp; 보정 하한 {boot['delta_lower'] * 10000:+.1f}bp",
            f"구간 A/B 개선 {positive_periods['A'] if positive_periods['A'] is not None else float('nan'):+.5f} / "
            f"{positive_periods['B'] if positive_periods['B'] is not None else float('nan'):+.5f}",
        ]
    return {
        "verdict": verdict, "reasons": reasons, "n_exit_events": event_n,
        "n_exit_cohorts": event_cohorts, "precision": boot["precision"],
        "precision_family_lower": boot["precision_lower"],
        "mean_cohort_delta": boot["mean_delta"], "delta_family_lower": boot["delta_lower"],
        "annualized_active_ir": observed_ir, "power": power,
        "false_exit_count": len(false),
        "mean_false_exit_upside": float(np.mean(false)) if false else None,
        "losing_hold_slots": losing, "loss_recall": early_losses / losing if losing else None,
        "early_losses": early_losses, "period_mean_delta": positive_periods,
        "bootstrap": {"replicates": BOOTSTRAPS, "seed": BOOTSTRAP_SEED,
                      "family_alpha": alpha, "cluster": "semiannual rebalance cohort"},
    }


def _report(payload: dict) -> str:
    lines = [
        "# 새틀라이트 매도 신호 정확도 v1 결과", "",
        f"생성 {payload['generated_at']} · 데이터 {payload['data_start']}~{payload['data_end']}"
        + (" · **합성 데이터 스모크 — 실측 결과 아님**" if payload["smoke"] else ""), "",
        f"## 최종 판정 구간 ({payload['decision_start']}~{payload['decision_end']})", "",
        f"기준선 보유 구간 {payload['n_cohorts']}개 · 유효 종목 구간 {payload['coverage']['usable_slots']}/"
        f"{payload['coverage']['scheduled_slots']} ({payload['coverage']['coverage']:.1%}) · 검열 {payload['coverage']['censored_slots']}개.",
        rp.power_line(payload["power"]), "",
        "정확도는 매도 이벤트 중 다음 반기까지 보유했으면 현금(수익 0)보다 손해였을 이벤트 비율이다. "
        "순 개선은 같은 종목·반기 구간에서 조기 매도 정책이 현행 보유보다 얼마나 나았는지다.", "",
        "| 신호 | 판정 | 매도 이벤트 | 정확도 (가족 보정 하한) | 반기당 순 개선 bp (하한) | 손실 구간 포착 | 오매도 뒤 놓친 상승 | 사유 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for rule in RULES:
        r = payload["results"][rule]
        precision = "—" if r["precision"] is None else f"{r['precision']:.1%} ({r['precision_family_lower']:.1%})"
        delta = "—" if r["mean_cohort_delta"] is None else f"{r['mean_cohort_delta']*10000:+.1f} ({r['delta_family_lower']*10000:+.1f})"
        recall = "—" if r["loss_recall"] is None else f"{r['loss_recall']:.1%} ({r['early_losses']}/{r['losing_hold_slots']})"
        upside = "—" if r["mean_false_exit_upside"] is None else f"{r['mean_false_exit_upside']:.1%} ({r['false_exit_count']}건)"
        lines.append(f"| {LABELS[rule]} | **{r['verdict']}** | {r['n_exit_events']} | {precision} | {delta} | {recall} | {upside} | {'; '.join(r['reasons']) or '사전 기준 통과'} |")
    lines += ["", "## 해석 한계", "",
              "- 2024-10 이후 완결 구간은 참고 전용이며 최종 판정·신호 선택에 쓰지 않았다.",
              "- 과거 S&P500 구성원은 시점별로 선택하지만 가격 원천에 상장폐지 종목이 빠질 수 있다. 검열 비율을 함께 보며, 결과를 상폐 포함 CRSP 검증으로 오해하면 안 된다.",
              "- 현금 수익률은 0으로 두고 진입·매도 비용은 편도 8bp를 적용했다. 실제 세금·환율·체결가는 모델링하지 않았다.",
              "- PASS는 전진 원장 후보일 뿐이고 매도 규칙이나 엔진 변경 승인이 아니다. 과거 표본의 좋은 결과도 채택을 뜻하지 않는다.", ""]
    if payload["smoke"]:
        lines.insert(2, "**스모크 결과는 연구 코드 실행 확인용이며 성과 판정에 사용할 수 없다.**")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data, spy = _load_data(args.smoke)
    cohorts_all, coverage_all = _build_cohorts(data, spy, args.smoke)
    decision = [c for c in cohorts_all if c["end"] <= DECISION_END]
    report_only = [c for c in cohorts_all if c["end"] > DECISION_END]
    yrs = max(0.01, len(decision) / 2.0)
    enough_data = (coverage_all["scheduled_slots"] > 0 and coverage_all["usable_slots"] >= 40
                   and coverage_all["coverage"] >= 0.80)
    results = {rule: _eval_rule(rule, decision, yrs) for rule in RULES}
    if not enough_data:
        for rule in RULES:
            results[rule]["verdict"] = "NOT_EVALUABLE_DATA"
            results[rule]["reasons"] = ["완결 구간·유효 종목 수 또는 자료 커버리지가 사전 최소치 미달"]
    # Post-2024-10 is descriptive only. Do not compute or emit a verdict for it.
    post_summary = {}
    for rule in RULES:
        rows = [c["results"][rule] for c in report_only]
        post_summary[rule] = {
            "n_cohorts": len(rows),
            "mean_cohort_delta": float(np.mean([r["mean_delta"] for r in rows])) if rows else None,
            "n_exit_events": sum(len(r["events"]) for r in rows),
        }
    payload = {
        "id": "sat-exit-accuracy-v1", "judge_version": "sat-exit-accuracy-judge/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "smoke": args.smoke, "data_start": str(data.trading_days[0].date()),
        "data_end": str(data.trading_days[-1].date()), "decision_start": DATA_START,
        "decision_end": DECISION_END.date().isoformat(), "split": SPLIT.date().isoformat(),
        "n_cohorts": len(decision), "n_report_only_cohorts": len(report_only),
        "coverage": coverage_all, "power": rp.power_report(yrs, N_TRIALS),
        "verdicts": {k: v["verdict"] for k, v in results.items()}, "results": results,
        "report_only_2024_10_plus": post_summary,
        "caveats": ["Yahoo 가격의 상장폐지 종목 누락 가능성", "현금수익 0 가정", "세금·환율 미반영",
                    "각 반기 코호트 독립 모델이며 연속 계좌의 잔류 종목·실제 체결은 재현하지 않음"],
    }
    _atomic_json(out / "results.json", payload)
    (out / "REPORT.md").write_text(_report(payload), encoding="utf-8")
    for rule in RULES:
        r = results[rule]
        print(f"{rule}: {r['verdict']} exits={r['n_exit_events']} precision={r['precision']} "
              f"delta={r['mean_cohort_delta']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
