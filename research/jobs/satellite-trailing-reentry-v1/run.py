"""현 새틀라이트 선정에 종가 10% 추적손절·즉시 재선정을 적용해 세후 비교한다."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core import research_power as rp  # noqa: E402
from core import satellite_lab as sl  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "satellite-trailing-reentry-v1"
START = "2010-01-01"
DECISION_END = pd.Timestamp("2024-09-30")
SAT_WEIGHT = 0.15
STOP_FRACTION = 0.10
BOOTSTRAPS = 5000
BLOCK = 126
SEED = 20261014
TRIALS = 2  # B 대 A, B 대 SPY — 판정 전에 고정
MIN_DIFF = 0.003
VARIANTS = ("champion", "trail10_reentry", "spy")
LABELS = {"champion": "현 챔피언(코어 85%+새틀라이트 15%)",
          "trail10_reentry": "최고 종가 10% 추적손절·재선정 챔피언", "spy": "SPY 100% 보유"}


def _atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def _panel(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    close, adj = {}, {}
    for ticker, frame in frames.items():
        if frame is None or frame.empty or "Close" not in frame:
            continue
        f = frame.copy()
        idx = pd.DatetimeIndex(f.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        f.index = idx.normalize()
        f = f[~f.index.duplicated(keep="last")].sort_index()
        close[ticker] = pd.to_numeric(f["Close"], errors="coerce")
        adj[ticker] = pd.to_numeric(f["Adj Close"], errors="coerce") if "Adj Close" in f and f["Adj Close"].notna().any() else close[ticker]
    return pd.DataFrame(close), pd.DataFrame(adj)


def _smoke_inputs(log):
    """네트워크 없이 합성 자료로 실행 계약과 포트폴리오 경로를 확인한다."""
    full_start, end = "2008-01-01", "2026-06-30"
    price_provider, pool_provider = sl.synthetic_providers(n_tickers=60, start=full_start, end=end, seed=SEED)
    data = sl.build_data({"champion40"}, start="2009-12-01", end=end,
                         pool_provider=pool_provider, price_provider=price_provider, calendar_ticker="SPY")
    rng = np.random.default_rng(SEED + 1)
    core = [f"CORE{i}" for i in range(4)]
    frames = {t: data.ohlcv[t] for t in data.ohlcv}
    frames["SPY"] = price_provider("SPY", full_start, end)
    for i, ticker in enumerate(core):
        r = rng.normal(0.00025 + i * 0.00002, 0.009, len(data.trading_days))
        c = 80 * np.cumprod(1 + r)
        frames[ticker] = pd.DataFrame({"Close": c, "Adj Close": c * np.cumprod(1 + np.full(len(c), 0.00001))}, index=data.trading_days)
    close, adj = _panel(frames)
    core_w = pd.DataFrame(0.0, index=data.trading_days, columns=core)
    core_w[core[0]] = 1.0
    core_w.loc[core_w.index.month.isin([4, 5, 6]), core[0]] = 0.0
    core_w.loc[core_w.index.month.isin([4, 5, 6]), core[1]] = 1.0
    fx = pd.Series(1300.0, index=data.trading_days)
    return {"data": data, "core_w": core_w, "close": close, "adj": adj, "fx": fx,
            "meta": {"synthetic": True, "data_end": end}}


def _real_inputs(log):
    from core import champion_strategy as cs
    from core import market_data

    log("코어 일별 목표 비중 및 point-in-time 후보 가격 불러오는 중")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = lambda pt, d: [] if d < date.fromisoformat(START) else sl.default_pool_provider()(pt, d)
    data = sl.build_data({"champion40"}, start="2009-12-01", pool_provider=pool, log=log)
    core_tickers = sorted(set(core_w.columns) | {"SPY"})
    hist = market_data.get_multiple_price_history(core_tickers, start="2009-06-01", end=None, interval="1d")
    frames = {t: data.ohlcv.get(t) for t in data.ohlcv}
    frames.update({t: hist.get(t) for t in core_tickers})
    close, adj = _panel(frames)
    return {"data": data, "core_w": core_w, "close": close, "adj": adj, "fx": tx.usdkrw_series(),
            "meta": {"synthetic": False, "core_universe": list(core_w.columns),
                     "pool_cache_tag": sl.POOL_CACHE_TAG, "satellite_judge_version": sl.JUDGE_VERSION}}


def _incumbent_signal():
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    return spec, sl.load_signal(code), dict(spec["signal"]["params_grid"][0])


def _ranked_on(data, signal, spec, params, day: pd.Timestamp, cutoff: pd.Timestamp | None = None) -> list[str]:
    """cutoff 종가까지의 정보로 day 시점 PIT 후보를 순위화한다."""
    days = data.trading_days
    i = days.searchsorted(day)
    cutoff = pd.Timestamp(cutoff if cutoff is not None else day)
    ci = days.searchsorted(cutoff)
    if i >= len(days) or days[i] != day or ci >= len(days) or days[ci] != cutoff:
        return []
    members = data.pool("champion40", day)
    prices = sl._signal_prices(data, members, cutoff, day)
    eligible = {t for t in prices if t in data.closes.columns and pd.notna(data.closes.at[day, t])}
    scores = sl._call_signal(signal, spec, data, {t: prices[t] for t in eligible}, day, params)
    return sl.pick_top(scores, len(eligible), eligible)


def build_satellite_logs(data) -> tuple[list[dict], list[dict], dict]:
    """Build incumbent and stop/re-entry logs; each logged weight is a fraction of the satellite sleeve."""
    spec, signal, params = _incumbent_signal()
    days = data.trading_days
    rebalances = sl.rebalance_dates(days, 6)
    if not rebalances:
        raise RuntimeError("반기 재선정일이 없음")
    incumbent, trailing = [], []
    slots: list[str | None] = [None, None, None]
    peaks: dict[str, float] = {}
    stopped: set[str] = set()
    pending: list[tuple[int, int, str, pd.Timestamp]] = []  # fill index, slot, old ticker, signal date
    counters = {"scheduled_rebalances": 0, "stop_signals": 0, "stop_fills": 0, "replacement_buys": 0,
                "unfilled_slots": 0, "daily_pick_calls": 0}
    rebalance_set = {days.searchsorted(d): d for d in rebalances}
    incumbent_slots: list[str | None] = [None, None, None]
    close = data.closes
    raw_close = {t: pd.to_numeric(df["Close"], errors="coerce") for t, df in data.ohlcv.items() if "Close" in df}

    for i, day in enumerate(days):
        if i in rebalance_set:
            d = rebalance_set[i]
            if d < pd.Timestamp(START):
                continue
            previous = days[i - 1] if i else None
            rank = _ranked_on(data, signal, spec, params, d, previous) if previous is not None else []
            picks = rank[:3]
            incumbent_slots = list(picks) + [None] * max(0, 3 - len(picks))
            incumbent_weight = SAT_WEIGHT / max(1, len(picks))
            incumbent.append({"date": d.date().isoformat(), "weights": {t: incumbent_weight for t in picks}})
            prior_peaks = dict(peaks)
            prior_slots = list(slots)
            slots = incumbent_slots.copy()
            slot_weights = [incumbent_weight if t else 0.0 for t in slots]
            peaks = {}
            for ticker in slots:
                if not ticker or ticker not in raw_close:
                    continue
                px = raw_close[ticker].get(day, np.nan)
                if np.isfinite(px):
                    peaks[ticker] = max(prior_peaks.get(ticker, float(px)), float(px)) if ticker in prior_slots else float(px)
            stopped.clear()
            pending.clear()
            counters["scheduled_rebalances"] += 1
            trailing.append({"date": d.date().isoformat(), "weights": {t: slot_weights[j] for j, t in enumerate(slots) if t}})

        # Execute yesterday's close-triggered exits today at the close, then fill each same slot.
        fills = [x for x in pending if x[0] == i]
        pending = [x for x in pending if x[0] != i]
        if fills:
            for _, slot, old, sig_day in fills:
                if slots[slot] == old:
                    slots[slot] = None
                if old in stopped:
                    stopped.add(old)
                counters["stop_fills"] += 1
            rank = _ranked_on(data, signal, spec, params, sig_day)
            counters["daily_pick_calls"] += 1
            for _, slot, old, _ in fills:
                replacement = next((t for t in rank if t not in slots and t not in stopped
                                    and t in close.columns and pd.notna(close.at[day, t])), None)
                if replacement is not None:
                    slots[slot] = replacement
                    peaks[replacement] = float(raw_close.get(replacement, close[replacement]).reindex([day]).iloc[0])
                    counters["replacement_buys"] += 1
                else:
                    counters["unfilled_slots"] += 1
            trailing.append({"date": day.date().isoformat(), "weights": {t: slot_weights[j] for j, t in enumerate(slots) if t}})

        # Observe the close and schedule a sale for the next trading day's close.
        if i + 1 < len(days):
            for slot, ticker in enumerate(slots):
                if not ticker or ticker not in raw_close:
                    continue
                series = raw_close[ticker]
                value = series.get(day, np.nan)
                if not np.isfinite(value) or value <= 0:
                    continue
                peak = max(peaks.get(ticker, float(value)), float(value))
                peaks[ticker] = peak
                if float(value) <= peak * (1.0 - STOP_FRACTION) and not any(x[2] == ticker for x in pending):
                    pending.append((i + 1, slot, ticker, day))
                    stopped.add(ticker)
                    counters["stop_signals"] += 1

    return incumbent, trailing, counters


def build_weights(core_w: pd.DataFrame, close: pd.DataFrame, logs: dict[str, list[dict]]) -> dict[str, pd.DataFrame]:
    idx = core_w.index[core_w.index >= pd.Timestamp(logs["champion"][0]["date"])]
    columns = sorted(set(core_w.columns) | set(close.columns))
    base = core_w.reindex(idx).fillna(0.0) * (1.0 - SAT_WEIGHT)
    out = {}
    for name in ("champion", "trail10_reentry"):
        w = base.reindex(columns=columns, fill_value=0.0).copy()
        rows = sorted(logs[name], key=lambda x: x["date"])
        current = {}
        ri = 0
        for day in idx:
            while ri < len(rows) and pd.Timestamp(rows[ri]["date"]) <= day:
                current = rows[ri]["weights"]
                ri += 1
            for ticker, fraction in current.items():
                if ticker in w.columns:
                    w.at[day, ticker] += float(fraction)
        out[name] = w
    spy = pd.DataFrame(0.0, index=idx, columns=columns)
    spy["SPY"] = 1.0
    out["spy"] = spy
    return out


def _ann(values: pd.Series, initial: float, end: pd.Timestamp) -> float:
    v = values.loc[:end]
    years = (v.index[-1] - v.index[0]).days / 365.25
    if years <= 0 or initial <= 0 or v.iloc[-1] <= 0:
        return float("nan")
    return float((v.iloc[-1] / initial) ** (1 / years) - 1)


def _ann_between(values: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    segment = values.loc[start:end]
    years = (segment.index[-1] - segment.index[0]).days / 365.25 if len(segment) > 1 else 0
    if years <= 0 or segment.iloc[0] <= 0 or segment.iloc[-1] <= 0:
        return float("nan")
    return float((segment.iloc[-1] / segment.iloc[0]) ** (1 / years) - 1)


def _returns(values: pd.Series, initial: float, end: pd.Timestamp) -> pd.Series:
    s = values.loc[:end].copy()
    prev = s.shift(1)
    prev.iloc[0] = initial
    return s / prev - 1


def _bootstrap_diff(ra: np.ndarray, rb: np.ndarray, ppy: float, *, seed: int) -> np.ndarray:
    n = len(ra)
    block = min(BLOCK, n)
    n_blocks = math.ceil(n / block)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(BOOTSTRAPS, n_blocks))
    ix = ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(BOOTSTRAPS, -1)[:, :n]
    def ann(x):
        return np.exp(np.log1p(x).sum(axis=1) * ppy / n) - 1
    return ann(ra[ix]) - ann(rb[ix])


def _mdd(values: pd.Series) -> float:
    x = values.to_numpy(dtype=float)
    peak = np.maximum.accumulate(x)
    return float(np.min(x / peak - 1))


def _analyze(sims: dict, counters: dict, meta: dict, smoke: bool, coverage: dict) -> tuple[dict, str]:
    vals = {k: v["values_krw"] for k, v in sims.items()}
    idx = vals["champion"].index
    dec_idx = idx[idx <= DECISION_END]
    if len(dec_idx) < 2:
        raise RuntimeError("판정 구간 거래일이 부족함")
    dec_end = pd.Timestamp(dec_idx[-1])
    first = pd.Timestamp(idx[0])
    mid = first + (dec_end - first) / 2
    half_cut = pd.Timestamp(idx[idx <= mid][-1])
    initial = tx.AccountConfig().initial_krw
    ppy = len(dec_idx) / ((dec_end - first).days / 365.25)
    comparisons = {}
    for candidate, baseline in (("trail10_reentry", "champion"), ("trail10_reentry", "spy")):
        a, b = _returns(vals[candidate], initial, dec_end), _returns(vals[baseline], initial, dec_end)
        daily = (a - b).to_numpy(dtype=float)
        ir = float(np.mean(daily) / np.std(daily, ddof=1) * math.sqrt(ppy)) if len(daily) > 1 and np.std(daily, ddof=1) > 0 else 0.0
        boot = _bootstrap_diff(a.to_numpy(), b.to_numpy(), ppy, seed=SEED)
        alpha = 1 - 0.05 / TRIALS
        comparisons[f"{candidate}_vs_{baseline}"] = {
            "decision_cagr_diff": _ann(vals[candidate], initial, dec_end) - _ann(vals[baseline], initial, dec_end),
            "first_half_cagr_diff": _ann(vals[candidate], initial, half_cut) - _ann(vals[baseline], initial, half_cut),
            "second_half_cagr_diff": _ann_between(vals[candidate], half_cut, dec_end)
                                           - _ann_between(vals[baseline], half_cut, dec_end),
            "daily_active_ir": ir, "noop_reason": rp.noop_guard(daily),
            "bootstrap_lower_family": float(np.quantile(boot, 1 - alpha)),
            "bootstrap_median": float(np.median(boot)),
            "bootstrap_upper_family": float(np.quantile(boot, alpha)),
        }
    summary = {}
    post_days = idx[idx > dec_end]
    for name, sim in sims.items():
        series = sim["values_krw"]
        last = series.index[-1]
        post_start = dec_end if len(post_days) else None
        summary[name] = {"label": LABELS[name], "cagr_after_tax_decision": _ann(series, initial, dec_end),
                         "cagr_after_tax_post_2024_10_report_only": _ann_between(series, post_start, last) if post_start is not None else None,
                         "mdd_after_tax_decision": _mdd(series.loc[:dec_end]),
                         "final_krw": float(series.iloc[-1]), "tax_krw": float(sim.get("totals", {}).get("capital_gains_tax_krw", 0)),
                         "fees_krw": float(sim.get("totals", {}).get("fees_krw", 0)),
                         "fx_cost_krw": float(sim.get("totals", {}).get("fx_cost_krw", 0)),
                         "dividend_tax_krw": float(sim.get("totals", {}).get("dividend_tax_krw", 0)),
                         "period_end": str(last.date())}
    primary = comparisons["trail10_reentry_vs_champion"]
    years = (dec_end - first).days / 365.25
    power = rp.power_report(years, TRIALS)
    noop = primary["noop_reason"]
    enough = len(dec_idx) >= 1260 and years >= 10
    data_ok = enough and min(coverage.values(), default=0.0) >= 0.80
    if noop:
        verdict = "NOT_EVALUABLE"
    elif not data_ok:
        verdict = "NOT_EVALUABLE_DATA"
    elif (primary["decision_cagr_diff"] >= MIN_DIFF and primary["first_half_cagr_diff"] > 0
          and primary["second_half_cagr_diff"] > 0 and primary["bootstrap_lower_family"] > 0):
        verdict = "PASS_FORWARD_CANDIDATE"
    else:
        verdict = rp.classify_fail(primary["daily_active_ir"], power)
    results = {"kind": "pre-registered verdict", "id": JOB_ID, "smoke": smoke,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "periods": {"decision": [str(first.date()), str(dec_end.date())], "post_2024_10_report_only":
                           [str(post_days[0].date()), str(idx[-1].date())] if len(post_days) else None,
                           "first_half_end": str(half_cut.date()), "trading_days": len(dec_idx)},
               "rules": {"stop_pct": STOP_FRACTION, "trigger": "unadjusted daily close <= highest close since entry * 0.90",
                         "execution": "next trading day close", "replacement": "same PIT champion40 + Donchian20/252d momentum ranking using signal-date close; exclude held and stopped names until semiannual reset; keep replaced slot weight; otherwise cash",
                         "comparisons": list(comparisons), "min_cagr_diff": MIN_DIFF, "block_days": BLOCK,
                         "bootstraps": BOOTSTRAPS, "seed": SEED, "family_alpha": 0.05, "post_2024_10": "report only"},
               "variants": summary, "comparisons": comparisons, "power": power, "power_line": rp.power_line(power),
               "price_coverage_decision": coverage,
               "power_class": None if verdict in ("PASS_FORWARD_CANDIDATE", "NOT_EVALUABLE") else verdict,
               "verdict_raw": verdict, "verdicts": {"trail10_vs_champion": f"SMOKE_ONLY({verdict})" if smoke else verdict,
                                                      "observed_cagr_winner": max(summary, key=lambda k: summary[k]["cagr_after_tax_decision"])},
               "events": counters, "data_meta": meta, "limitations": ["무료 자료 생존편향·상폐가격 누락", "갭 하락은 다음 거래일 종가 체결이라 10% 손실 제한 보장 아님", "추정 세금·환전, 슬리피지·시장충격 제외"]}
    lines = [f"# 새틀라이트 10% 추적 손절·재선정 비교{' (스모크, 합성 자료)' if smoke else ''}", "",
             f"판정: **{results['verdicts']['trail10_vs_champion']}** — PASS는 전진 원장 후보이며 전략 채택을 뜻하지 않음.", "",
             f"판정 구간: {first.date()} ~ {dec_end.date()} (2024-10 이후 최종 판정에서 제외).", "",
             "## 세후 결과", "", "| 전략 | 판정 구간 연복리 | 2024-10 이후 연복리(참고) | 판정 구간 최대낙폭 | 최종 원화 평가액 | 양도세(모델) | 수수료 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for key in VARIANTS:
        m = summary[key]
        post = m["cagr_after_tax_post_2024_10_report_only"]
        post_text = f"{post:.2%}" if post is not None else "자료 없음"
        lines.append(f"| {m['label']} | {m['cagr_after_tax_decision']:.2%} | {post_text} | {m['mdd_after_tax_decision']:.2%} | {m['final_krw']:,.0f}원 | {m['tax_krw']:,.0f}원 | {m['fees_krw']:,.0f}원 |")
    lines += ["", "## 비교·판정", "", f"- 추적 손절 챔피언 − 현 챔피언: 판정 구간 {primary['decision_cagr_diff'] * 100:+.2f}%p, 앞 절반 {primary['first_half_cagr_diff'] * 100:+.2f}%p, 뒤 절반 {primary['second_half_cagr_diff'] * 100:+.2f}%p.",
              f"- 두 비교 보정 블록 부트스트랩 97.5% 하한: {primary['bootstrap_lower_family'] * 100:+.2f}%p. 관측 연 IR {primary['daily_active_ir']:.3f}.",
              f"- 추적 손절 챔피언 − SPY: 판정 구간 {comparisons['trail10_reentry_vs_spy']['decision_cagr_diff'] * 100:+.2f}%p (SPY는 보고 비교이며 PASS 관문은 현 챔피언 대비).",
              f"- {results['power_line']}", "", "## 체결·자료 한계", "",
              f"- 정기 반기 재선정 {counters['scheduled_rebalances']}회, 손절 신호 {counters['stop_signals']}건, 매도 체결 {counters['stop_fills']}건, 대체 매수 {counters['replacement_buys']}건, 후보 부재 슬롯 {counters['unfilled_slots']}회.",
              "- 최고 종가는 미조정 종가로 추적하고 총수익은 배당 포함 조정 종가로 평가했다. 손절 신호 다음 거래일 종가에 체결하므로 갭 하락 시 손실은 10%를 넘을 수 있다.",
              "- 과거 상장폐지 가격 누락과 PIT 시가총액 근사 때문에 생존편향이 남는다. 비교는 가상 재구성이며 실제 주문 성과가 아니다.",
              "- 연구 결과는 엔진·주문 규칙을 바꾸지 않는다. PASS도 전진 원장 후보일 뿐, 채택은 별도 검토가 필요하다.", ""]
    return results, "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    def log(text):
        print(text, flush=True)
    inputs = _smoke_inputs(log) if args.smoke else _real_inputs(log)
    incumbent_log, trail_log, counters = build_satellite_logs(inputs["data"])
    logs = {"champion": incumbent_log, "trail10_reentry": trail_log}
    weights = build_weights(inputs["core_w"], inputs["close"], logs)
    simulations = {}
    coverage = {}
    cfg = tx.AccountConfig()
    for name in VARIANTS:
        log(f"세후 시뮬레이션: {name}")
        active = weights[name].loc[weights[name].index <= DECISION_END]
        observed = inputs["close"].reindex(index=active.index, columns=active.columns).notna()
        mask = active.abs() > 1e-12
        coverage[name] = float((observed & mask).to_numpy().sum() / max(1, mask.to_numpy().sum()))
        simulations[name] = tx.simulate(weights[name], inputs["close"], inputs["adj"], inputs["fx"], cfg)
    result, report = _analyze(simulations, counters, inputs["meta"], args.smoke, coverage)
    _atomic_json(out / "results.json", result)
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
