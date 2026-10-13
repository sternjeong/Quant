"""leader-catch 신호의 PIT S&P500 개별주 전이 연구. 신호·판정은 SPEC.md 고정."""
from __future__ import annotations
import argparse, json, math, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core import research_power as rp  # noqa: E402
from core import satellite_lab as sl  # noqa: E402

ID = "leader-catch-single-stock-v1"
SIGNALS = ("F2", "F3", "F5", "C")
LABELS = {"F2": "6개월 모멘텀", "F3": "252일 고점 근접도", "F5": "12개월 SPY 상대강도", "C": "F2·F3·F5 순위 평균"}
DATA_START, DATA_END = "2000-01-01", "2024-09-30"
CONF_START = pd.Timestamp("2013-01-01")
CONF_END = pd.Timestamp("2024-09-30")
BLOCK, DRAWS, SEED, K = 12, 2000, 20261013, 10
ALPHA = 0.05 / len(SIGNALS)


def _load(smoke):
    if smoke:
        pp, pools = sl.synthetic_providers(n_tickers=80, start="1997-01-01", end=DATA_END, seed=20261013)
        data = sl.build_data({"sp500_pit"}, start=DATA_START, end=DATA_END, pool_provider=pools,
                             price_provider=pp, calendar_ticker="SPY")
        spy = pp("SPY", "1997-01-01", DATA_END)["Close"]
        return data, spy
    data = sl.build_data({"sp500_pit"}, start=DATA_START, end=DATA_END)
    from core import hypothesis_engine as he
    prices = he.load_prices(["SPY"], "1997-01-01", DATA_END)
    if "SPY" not in prices or prices["SPY"].empty:
        raise RuntimeError("SPY 워밍업 가격을 불러오지 못함")
    df = prices["SPY"]
    col = "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close"
    return data, pd.to_numeric(df[col], errors="coerce").dropna()


def _scores(data, spy, members, cutoff):
    vals = {s: {} for s in ("F2", "F3", "F5")}
    for ticker in members:
        df = data.ohlcv.get(ticker)
        if df is None:
            continue
        col = "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close"
        px = pd.to_numeric(df[col], errors="coerce").dropna()
        i = px.index.searchsorted(cutoff, side="right") - 1
        if i < 252 or px.index[i] > cutoff:
            continue
        now = float(px.iloc[i])
        p126, p252 = float(px.iloc[i-126]), float(px.iloc[i-252])
        if min(now, p126, p252) <= 0:
            continue
        hist = px.iloc[i-251:i+1]
        if len(hist) < 252:
            continue
        m = spy.index.searchsorted(cutoff, side="right") - 1
        if m < 252 or spy.index[m] > cutoff:
            continue
        sn, s0 = float(spy.iloc[m]), float(spy.iloc[m-252])
        if min(sn, s0) <= 0:
            continue
        vals["F2"][ticker] = now / p126 - 1
        vals["F3"][ticker] = now / float(hist.max())
        vals["F5"][ticker] = (now / p252 - 1) - (sn / s0 - 1)
    if vals["F2"]:
        rank = {s: pd.Series(v, dtype=float).rank(pct=True, method="average") for s, v in vals.items()}
        common = set.intersection(*(set(rank[s].index) for s in rank))
        vals["C"] = {t: float(np.mean([rank[s][t] for s in ("F2", "F3", "F5")])) for t in common}
    else:
        vals["C"] = {}
    return vals


def _nw_t(x, lags=6):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 24:
        return None
    z = x - x.mean()
    var = float(np.dot(z, z) / n)
    for lag in range(1, min(lags, n-1)+1):
        cov = float(np.dot(z[lag:], z[:-lag]) / n)
        var += 2 * (1 - lag/(lags+1)) * cov
    se = math.sqrt(max(var, 0) / n)
    return float(x.mean()/se) if se > 0 else 0.0


def _block_lower(monthly, alpha, seed):
    rows = [np.asarray(x, dtype=float) for x in monthly if len(x)]
    if not rows:
        return None
    n = len(rows)
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(DRAWS):
        ix = []
        while len(ix) < n:
            start = int(rng.integers(0, n))
            ix.extend((start + j) % n for j in range(BLOCK))
        chosen = [rows[i] for i in ix[:n]]
        flat = np.concatenate(chosen)
        stats.append(float(flat.mean()))
    return float(np.quantile(stats, alpha))


def _evaluate(data, spy):
    days = data.trading_days
    schedule = sl.rebalance_dates(days, 1)
    records = {s: [] for s in SIGNALS}
    coverage = {"months": 0, "eligible_members": 0, "missing_start_or_end": 0, "months_with_10_scores": 0}
    for d, nxt in zip(schedule[:-1], schedule[1:]):
        if d < pd.Timestamp(DATA_START) or d >= CONF_END or nxt > CONF_END:
            continue
        pos = days.searchsorted(d)
        if pos < 1:
            continue
        cutoff = days[pos-1]
        members = data.pool("sp500_pit", d)
        score_map = _scores(data, spy, members, cutoff)
        d0, d1 = data.closes.index.searchsorted(d), data.closes.index.searchsorted(nxt)
        if d0 >= len(days) or d1 >= len(days):
            continue
        rets = {}
        for t in members:
            if t not in data.closes:
                continue
            a, b = data.closes[t].iloc[d0], data.closes[t].iloc[d1]
            if np.isfinite(a) and np.isfinite(b) and a > 0:
                rets[t] = float(b/a - 1)
        if len(rets) < K:
            continue
        coverage["months"] += 1
        coverage["eligible_members"] += len(rets)
        allret = pd.Series(rets)
        threshold = float(allret.quantile(2/3))
        benchmark = float(allret.mean())
        coverage["missing_start_or_end"] += max(0, len(members)-len(rets))
        for sig in SIGNALS:
            scores = score_map[sig]
            ranked = sorted(((t, v) for t, v in scores.items() if t in rets and np.isfinite(v)), key=lambda x: (-x[1], x[0]))
            if len(ranked) < K:
                continue
            coverage["months_with_10_scores"] += int(sig == "F2")
            selected = [t for t, _ in ranked[:K]]
            r = np.array([rets[t] for t in selected], dtype=float)
            records[sig].append({"date": d, "hit": (r > threshold).astype(float), "active": float(r.mean()-benchmark), "n_selected": len(selected)})
    return records, coverage


def _result(sig, rows, power, enough):
    decision = [r for r in rows if CONF_START <= r["date"] <= CONF_END]
    month_hits = [r["hit"] for r in decision]
    hits = np.concatenate(month_hits) if month_hits else np.array([])
    active = np.array([r["active"] for r in decision], dtype=float)
    precision = float(hits.mean()) if len(hits) else None
    lower = _block_lower(month_hits, ALPHA, SEED + SIGNALS.index(sig)) if len(hits) else None
    mean_active = float(active.mean()) if len(active) else None
    t = _nw_t(active)
    sd = float(active.std(ddof=1)) if len(active) > 1 else 0.0
    ir = float(active.mean()/sd*math.sqrt(12)) if sd > 0 else 0.0
    segments = {}
    for label, lo, hi in (("2013-16", "2013-01-01", "2016-12-31"), ("2017-20", "2017-01-01", "2020-12-31"), ("2021-24-09", "2021-01-01", "2024-09-30")):
        a = [r["active"] for r in decision if pd.Timestamp(lo) <= r["date"] <= pd.Timestamp(hi)]
        segments[label] = float(np.mean(a)) if a else None
    noop = rp.noop_guard(active)
    if not enough:
        verdict, reason = "NOT_EVALUABLE_DATA", ["판정 구간 데이터 커버리지 또는 유효 월/종목 수 부족"]
    elif noop:
        verdict, reason = "NOT_EVALUABLE", [noop]
    elif len(decision) < 100 or len(hits) < 500:
        verdict, reason = "NOT_EVALUABLE_DATA", ["월 100개 또는 선택 종목 500개 미달"]
    else:
        passed = lower is not None and lower > 1/3 and mean_active is not None and mean_active > 0 and t is not None and t >= 2 and all(v is not None and v > 0 for v in segments.values())
        verdict = "PASS_FORWARD_CANDIDATE" if passed else rp.classify_fail(ir, power)
        reason = [] if passed else [f"적중률 보정 하한={lower:.1%} (기준 >33.3%)" if lower is not None else "적중률 자료 없음",
                                    f"월 초과수익={mean_active*10000:+.1f}bp, NW(6)t={t if t is not None else float('nan'):.2f} (기준 양수·t≥2)",
                                    "하위 구간 평균 초과수익=" + ", ".join(f"{k}:{v*10000:+.1f}bp" if v is not None else f"{k}:자료 없음" for k,v in segments.items())]
    return {"verdict": verdict, "reasons": reason, "n_months": len(decision), "n_selected": int(len(hits)),
            "precision": precision, "precision_family_lower": lower, "mean_monthly_active": mean_active,
            "nw6_t": t, "annualized_active_ir": ir, "power": power, "subperiod_mean_active": segments}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True); ap.add_argument("--checkpoint", required=True); ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    data, spy = _load(a.smoke)
    rows, coverage = _evaluate(data, spy)
    n_months = min((sum(CONF_START <= r["date"] <= CONF_END for r in rows[s]) for s in SIGNALS), default=0)
    years = max(0.01, n_months / 12)
    power = rp.power_report(years, len(SIGNALS))
    enough = n_months >= 100 and coverage["months"] > 0 and coverage["eligible_members"] >= 500 and coverage["missing_start_or_end"] / max(1, coverage["eligible_members"] + coverage["missing_start_or_end"]) <= 0.35
    results = {s: _result(s, rows[s], power, enough) for s in SIGNALS}
    payload = {"id": ID, "judge_version": "leader-catch-single-stock-judge/v1", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "smoke": a.smoke, "data_start": str(data.trading_days[0].date()), "data_end": str(data.trading_days[-1].date()),
               "decision_start": str(CONF_START.date()), "decision_end": str(CONF_END.date()), "signals": LABELS,
               "power": power, "coverage": coverage, "verdicts": {s:r["verdict"] for s,r in results.items()}, "results": results,
               "caveats": ["PIT membership list begins in 1996", "Yahoo may omit delisted security prices", "gross signal study: no tax, FX, or transaction costs", "not a forward or independent validation"]}
    (out/"results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = ["# leader-catch 단일 종목 전이 검증 v1 결과", "", f"생성 {payload['generated_at']} · {payload['data_start']}~{payload['data_end']}" + (" · **합성 스모크, 실측 결과 아님**" if a.smoke else ""), "",
             rp.power_line(power), "", f"커버리지: 평가 월 {coverage['months']}, 평균 후보 입력 종목 {coverage['eligible_members']/max(1,coverage['months']):.1f}/월; 시작·종료 가격 검열 추정 수 {coverage['missing_start_or_end']}.", "",
             "| 신호 | 판정 | 월 | 선택 종목 | 적중률 (가족 보정 하한) | 월 초과수익(bp) | NW(6) t | 하위구간 초과수익(bp) |", "|---|---|---:|---:|---:|---:|---:|---|"]
    for s,r in results.items():
        prec = "—" if r['precision'] is None else f"{r['precision']:.1%} ({r['precision_family_lower']:.1%})"
        act = "—" if r['mean_monthly_active'] is None else f"{r['mean_monthly_active']*10000:+.1f}"
        seg = ", ".join(f"{k} {v*10000:+.1f}" if v is not None else f"{k} —" for k,v in r['subperiod_mean_active'].items())
        lines.append(f"| {LABELS[s]} | **{r['verdict']}** | {r['n_months']} | {r['n_selected']} | {prec} | {act} | {r['nw6_t'] if r['nw6_t'] is not None else '—'} | {seg} |")
    lines += ["", "적중률은 선택 종목이 다음 달 유효 PIT 구성 종목 수익 상위 1/3에 든 비율이다. 초과수익은 상위 10 동일가중과 해당 월 전체 유효 종목 동일가중의 차이다.", "", "상장폐지 가격 누락 가능성 때문에 생존편향이 남는다. 결과는 비용·세금 전 신호 진단이며 개인 계좌 수익 추정이 아니다. PASS는 전진 원장 검토 후보일 뿐이고, 챔피언·주문 규칙은 변경하지 않는다.", ""]
    (out/"REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    for s,r in results.items(): print(f"{s}: {r['verdict']} n={r['n_selected']} precision={r['precision']} active={r['mean_monthly_active']}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
