"""40-week moving average; assumptions and frozen decision rules in SPEC.md."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
START, HOLDOUT, END = "2008-01-02", "2021-01-04", "2025-12-31"
FEE = 0.001


def signals(price):
    # A week's last trading day becomes known only when the following week starts.
    weeks = price.index.to_period("W-FRI")
    weekly = price.groupby(weeks).last()
    average = weekly.rolling(40, min_periods=40).mean()
    decisions = (weekly >= average).where(average.notna(), False)
    first = ~weeks.duplicated()
    targets = pd.Series(np.nan, index=price.index)
    first_idx = np.flatnonzero(first)
    for i in first_idx[1:]:
        targets.iloc[i] = float(decisions.loc[weeks[i - 1]])
    return targets.ffill().fillna(0.0)


def evaluate(price, target, start, end):
    p = price.loc[start:end]
    t = target.reindex(p.index)
    if len(p) < 2 or t.isna().any():
        raise ValueError("insufficient data")
    nav, held, trades, peak, drawdown = 1.0, 0.0, 0, 1.0, 0.0
    exposure = []
    prev = None
    for date, value in p.items():
        if prev is not None:
            nav *= 1 + held * (value / prev - 1)
        desired = float(t.loc[date])
        if desired != held:
            nav *= 1 - FEE
            trades += 1
            held = desired
        peak = max(peak, nav)
        drawdown = min(drawdown, nav / peak - 1)
        exposure.append(held)
        prev = value
    years = (p.index[-1] - p.index[0]).days / 365.25
    return {"start": str(p.index[0].date()), "end": str(p.index[-1].date()),
            "cagr": nav ** (1 / years) - 1, "mdd": drawdown, "final_nav": nav,
            "trades": trades, "exposure": float(np.mean(exposure))}


def load(smoke):
    if smoke:
        idx = pd.bdate_range("2006-01-02", END)
        rng = np.random.default_rng(40)
        return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, len(idx)))), index=idx)
    from core.market_data import get_multiple_price_history
    history = get_multiple_price_history(["SPY"], start="2006-01-01", end="2026-01-01", interval="1d")
    s = history["SPY"]["Adj Close"].dropna().sort_index()
    if len(s) < 1000 or s.index[0] > pd.Timestamp("2006-02-01") or s.index[-1] < pd.Timestamp("2025-12-29"):
        raise ValueError("SPY price history is incomplete")
    if not s.index.is_unique or (s <= 0).any():
        raise ValueError("invalid SPY prices")
    return s


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    price = load(args.smoke)
    target = signals(price)
    buy_hold = pd.Series(1.0, index=price.index)
    stats = {}
    for name, lo in [("full", START), ("holdout", HOLDOUT)]:
        stats[name] = {"strategy": evaluate(price, target, lo, END),
                       "buy_hold": evaluate(price, buy_hold, lo, END)}
    full, hold = stats["full"], stats["holdout"]
    checks = {"full_cagr_within_2pp": full["strategy"]["cagr"] >= full["buy_hold"]["cagr"] - .02,
              "full_mdd_improves_5pp": full["strategy"]["mdd"] >= full["buy_hold"]["mdd"] + .05,
              "holdout_cagr_within_3pp": hold["strategy"]["cagr"] >= hold["buy_hold"]["cagr"] - .03}
    result = {"smoke": args.smoke, "verdicts": {"weekly_ma40": "PASS_REVIEW" if all(checks.values()) else "FAIL"},
              "checks": checks, "stats": stats}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    out.joinpath("results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    lines = ["# SPY 40주 이동평균 백테스트" + (" — 합성 스모크" if args.smoke else ""), "",
             f"판정: {result['verdicts']['weekly_ma40']}", "", "| 기간 | 전략 | CAGR | MDD | 최종 자산(초기 1) | 거래 횟수 | 노출률 |", "|---|---|---:|---:|---:|---:|---:|"]
    for period, variants in stats.items():
        for name, s in variants.items():
            lines.append(f"| {period} ({s['start']}~{s['end']}) | {name} | {s['cagr']:.2%} | {s['mdd']:.2%} | {s['final_nav']:.4f} | {s['trades']} | {s['exposure']:.1%} |")
    lines += ["", "판정 조건: " + json.dumps(checks, ensure_ascii=False), "", "수정종가·다음 주 첫 거래일 종가 체결, 거래당 0.10%. 세금·환율·현금 이자 제외. 고정 과거 구간은 독립 미열람 검증이 아니다. 자세한 규칙은 SPEC.md."]
    out.joinpath("REPORT.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
