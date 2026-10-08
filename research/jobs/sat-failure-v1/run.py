"""분석 sat-failure-v1: 새틀라이트가 고른 종목 중 실패한 것은 '고를 때' 무엇이 달랐나. (탐색 연구, 2026-10-08)

사용자 요청(2026-10-08): "새틀라이트의 경우 종목 선정 실패 일자들도 존재하는데 원인을 분석함으로써 더 고도화할 수 있는 R&D".
두 단계로 나눈다(과적합 방지):
  1) 이 작업 = 탐색. 떼어 둔 마지막 2년은 보지 않는다. 앞 구간에서 실패한 선정과 나머지를 '선정 시점에 알 수 있던 특징'으로 비교.
  2) 확인 = 유의한 특징을 거르는 규칙을 새틀라이트 R&D 아이디어로 만들어 sat-judge/v2(떼어 둔 2년·DSR·누적 시도)로 심판. 이 작업은 판정하지 않는다.

## 사전 등록 (결과를 보기 전에 고정)
대상: 새틀라이트 현 규칙 S-SEED-000(champion40, 돈치안 20일 추세 활성 중 12개월 모멘텀 상위 3, 반기 보유)의 2010~ 선정.
결과: 종목별 보유 구간 수익(배당 포함) − 같은 구간 SPY 수익. 실패 = −10%p 미만, 큰 실패 = −20%p 미만.
특징(리밸런싱 전날 종가까지): mom12(12개월 수익), mom1(최근 21일), ext50(종가/50일선−1), ext200, vol63(63일 연환산 변동성),
  off_high(종가/252일 최고가−1), rank_pct(풀 안 12개월 모멘텀 백분위), breadth(풀에서 추세 활성 비율), spy_200(SPY 200일선 위=1),
  spy_mom6(SPY 6개월 수익), spy_vol63, same_sector(같은 SIC 2자리 업종을 고른 수 − 1, 재무 데이터가 있을 때), gp_assets, rev_yoy(있을 때).
검정: 특징마다 실패 vs 나머지의 순위 효과크기(rank-biserial)와 순열검정 p(2,000회, 양측), 특징 수로 본페로니(α=0.05).
  유의(본페로니 통과)한 특징만 '다음 아이디어 후보'로 적는다. 구간 단위: 세 종목 평균 초과 < −10%p 인 반기의 시장 특징도 따로 비교.
한계: 선정 표본 약 100건(반기 ~31회 × 3), 특징끼리 상관 있음, champion40 풀의 생존편향.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import satellite_lab as sl  # noqa: E402

FAIL_EXCESS = -0.10
BIG_FAIL = -0.20
N_PERM = 2000
ALPHA = 0.05
PICK_FEATURES = ["mom12", "mom1", "ext50", "ext200", "vol63", "off_high", "rank_pct", "same_sector", "gp_assets", "rev_yoy"]
MARKET_FEATURES = ["breadth", "spy_200", "spy_mom6", "spy_vol63"]


def rank_biserial(a: np.ndarray, b: np.ndarray) -> float:
    """a(실패) 가 b 보다 큰 쌍 비율 − 작은 쌍 비율. +면 실패 쪽이 큼."""
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    gt = sum(np.sum(x > b) for x in a)
    lt = sum(np.sum(x < b) for x in a)
    return float((gt - lt) / (len(a) * len(b)))


def perm_p(values: np.ndarray, is_fail: np.ndarray, rng, n: int = N_PERM) -> float:
    obs = abs(rank_biserial(values[is_fail], values[~is_fail]))
    if not math.isfinite(obs):
        return float("nan")
    hits = 0
    for _ in range(n):
        p = rng.permutation(is_fail)
        if abs(rank_biserial(values[p], values[~p])) >= obs - 1e-12:
            hits += 1
    return (hits + 1) / (n + 1)


def features_at(df: pd.DataFrame) -> dict:
    c = df["Close"].dropna()
    out = {}
    if len(c) < 253:
        return out
    last = float(c.iloc[-1])
    out["mom12"] = last / float(c.iloc[-253]) - 1
    out["mom1"] = last / float(c.iloc[-22]) - 1
    out["ext50"] = last / float(c.iloc[-50:].mean()) - 1
    out["ext200"] = last / float(c.iloc[-200:].mean()) - 1
    r = c.pct_change().iloc[-63:]
    out["vol63"] = float(r.std() * math.sqrt(252))
    out["off_high"] = last / float(c.iloc[-252:].max()) - 1
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    signal = sl.load_signal(code)
    params = dict(spec["signal"]["params_grid"][0])
    store = None
    if a.smoke:
        pp, poolp = sl.synthetic_providers(n_tickers=40, start="2008-01-01", end="2016-12-30")
        data = sl.build_data({"champion40"}, start="2010-01-01", end="2016-12-30", pool_provider=poolp, price_provider=pp)
        from core.fundamentals_pit import SyntheticStore
        store = SyntheticStore()
        spy_df = pp("SPY", "2008-01-01", "2016-12-30")
    else:
        data = sl.build_data({"champion40"}, start=sl.LAB_START, log=lambda s: print(s, flush=True))
        from core import hypothesis_engine as he
        spy_df = he.load_prices(["SPY"], data.trading_days[0].date() - pd.Timedelta(days=800), data.trading_days[-1].date()).get("SPY")
        try:
            from core.fundamentals_pit import Store
            store = Store()
        except Exception:  # noqa: BLE001
            store = None
    spy_close = spy_df["Close"].reindex(data.trading_days).ffill()
    spy_total = (spy_df["Adj Close"] if "Adj Close" in spy_df.columns else spy_df["Close"]).reindex(data.trading_days).ffill()
    run = sl.run_variant(spec, params, signal, data)
    sched = [(pd.Timestamp(d), picks) for d, picks in run["schedule"]]
    split = sl.holdout_split(run["returns"].index)
    rows = []
    for i, (d, picks) in enumerate(sched):
        end = sched[i + 1][0] if i + 1 < len(sched) else data.trading_days[-1]
        cutoff = sl._prev_day(data.trading_days, d)
        members = data.pool("champion40", d)
        prices = sl._signal_prices(data, members, cutoff, d)
        mom = {t: (features_at(df).get("mom12")) for t, df in prices.items()}
        mom_vals = sorted(v for v in mom.values() if v is not None)
        active = signal(prices, cutoff, params)
        breadth = len(active) / max(len(prices), 1)
        sc = spy_close.loc[:cutoff].dropna()
        mkt = {"breadth": breadth, "spy_200": float(sc.iloc[-1] > sc.iloc[-200:].mean()) if len(sc) >= 200 else np.nan,
               "spy_mom6": float(sc.iloc[-1] / sc.iloc[-127] - 1) if len(sc) > 127 else np.nan,
               "spy_vol63": float(sc.pct_change().iloc[-63:].std() * math.sqrt(252)) if len(sc) > 64 else np.nan}
        sics = {}
        fund = {}
        if store is not None:
            for t in picks:
                try:
                    v = store.view(t, cutoff.date()) or {}
                except Exception:  # noqa: BLE001
                    v = {}
                fund[t] = v
                sics[t] = (v.get("sic") or 0) // 100 or None
        spy_ret = float(spy_total.loc[end] / spy_total.loc[d] - 1)
        for t in picks:
            col = data.closes[t]
            if pd.isna(col.get(d)):
                continue
            seg = col.loc[d:end].ffill()
            ret = float(seg.iloc[-1] / seg.iloc[0] - 1)
            f = features_at(prices[t]) if t in prices else {}
            f["rank_pct"] = (sum(1 for v in mom_vals if v <= (mom.get(t) or -1e9)) / len(mom_vals)) if mom_vals else np.nan
            f["same_sector"] = (sum(1 for u in picks if sics.get(u) and sics.get(u) == sics.get(t)) - 1) if sics.get(t) else np.nan
            f["gp_assets"] = (fund.get(t) or {}).get("gp_assets", np.nan)
            f["rev_yoy"] = (fund.get(t) or {}).get("rev_yoy", np.nan)
            rows.append({"date": str(d.date()), "ticker": t, "ret": ret, "spy_ret": spy_ret, "excess": ret - spy_ret,
                         "holdout": bool(split is not None and d >= split), **mkt, **{k: f.get(k, np.nan) for k in PICK_FEATURES}})
    df = pd.DataFrame(rows)
    df.to_csv(out / "picks.csv", index=False)
    is_df = df[~df["holdout"]].copy()
    is_df["fail"] = is_df["excess"] < FAIL_EXCESS
    rng = np.random.default_rng(20261008)
    feats = PICK_FEATURES + MARKET_FEATURES
    res = {}
    for f in feats:
        sub = is_df[[f, "fail"]].dropna()
        x, y = sub[f].to_numpy(dtype=float), sub["fail"].to_numpy(dtype=bool)
        if y.sum() < 5 or (~y).sum() < 5:
            res[f] = {"n": len(sub), "note": "표본 부족"}
            continue
        res[f] = {"n": int(len(sub)), "fail_median": float(np.median(x[y])), "other_median": float(np.median(x[~y])),
                  "effect": rank_biserial(x[y], x[~y]), "p": perm_p(x, y, rng)}
    m = len([f for f in res if "p" in res[f]])
    for f, r in res.items():
        if "p" in r:
            r["significant"] = bool(r["p"] <= ALPHA / max(m, 1))
    per = is_df.groupby("date").agg(excess=("excess", "mean"), **{k: (k, "first") for k in MARKET_FEATURES}).reset_index()
    per["bad"] = per["excess"] < FAIL_EXCESS
    period = {}
    for f in MARKET_FEATURES:
        sub = per[[f, "bad"]].dropna()
        x, y = sub[f].to_numpy(dtype=float), sub["bad"].to_numpy(dtype=bool)
        if y.sum() >= 3 and (~y).sum() >= 3:
            period[f] = {"bad_median": float(np.median(x[y])), "other_median": float(np.median(x[~y])), "effect": rank_biserial(x[y], x[~y]),
                         "p": perm_p(x, y, rng)}
    sig = {f: r for f, r in res.items() if r.get("significant")}
    summary = {"is_picks": int(len(is_df)), "fail_rate": float(is_df["fail"].mean()) if len(is_df) else None,
               "big_fail_rate": float((is_df["excess"] < BIG_FAIL).mean()) if len(is_df) else None,
               "significant_features": {f: ("실패 쪽이 큼" if r["effect"] > 0 else "실패 쪽이 작음") for f, r in sig.items()} or "없음"}
    result = {"kind": "탐색 분석(판정 없음)", "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "summary": summary, "features": res, "period_features": period, "holdout_start": None if split is None else str(split.date())}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    worst = is_df.sort_values("excess").head(10)
    lines = [f"# 새틀라이트 실패 원인 분석 v1 (탐색){' — 스모크' if a.smoke else ''}", "",
             f"앞 구간 선정 {summary['is_picks']}건 · 실패(SPY 대비 −10%p 미만) {summary['fail_rate'] or 0:.0%} · 큰 실패(−20%p 미만) {summary['big_fail_rate'] or 0:.0%}. "
             f"떼어 둔 구간({result['holdout_start']}~)은 보지 않았다.", "",
             "## 선정 시점 특징: 실패 vs 나머지", "", "| 특징 | 실패 중앙값 | 나머지 중앙값 | 효과(+면 실패가 큼) | p(순열) | 본페로니 유의 |", "|---|---|---|---|---|---|"]
    for f, r in res.items():
        if "p" not in r:
            lines.append(f"| {f} | — | — | — | — | {r.get('note', '')} |")
            continue
        lines.append(f"| {f} | {r['fail_median']:.3f} | {r['other_median']:.3f} | {r['effect']:+.2f} | {r['p']:.4f} | {'예' if r['significant'] else ''} |")
    lines += ["", "## 나쁜 반기(세 종목 평균 −10%p 미만)의 시장 상황", "", "| 특징 | 나쁜 반기 | 나머지 | 효과 | p |", "|---|---|---|---|---|"]
    for f, r in period.items():
        lines.append(f"| {f} | {r['bad_median']:.3f} | {r['other_median']:.3f} | {r['effect']:+.2f} | {r['p']:.4f} |")
    lines += ["", "## 가장 크게 실패한 선정 10건", "", "| 날짜 | 종목 | 수익 | SPY | 초과 | 12개월 모멘텀 | 50일선 이격 |", "|---|---|---|---|---|---|---|"]
    for _, r in worst.iterrows():
        lines.append(f"| {r['date']} | {r['ticker']} | {r['ret'] * 100:+.0f}% | {r['spy_ret'] * 100:+.0f}% | {r['excess'] * 100:+.0f}%p | "
                     f"{(r['mom12'] if pd.notna(r['mom12']) else float('nan')) * 100:+.0f}% | {(r['ext50'] if pd.notna(r['ext50']) else float('nan')) * 100:+.0f}% |")
    lines += ["", "다음 단계: 유의한 특징을 거르는 규칙을 새틀라이트 R&D 아이디어로 등록해 sat-judge/v2 로 확인한다(이 분석은 판정이 아니다).",
              "한계: 표본 약 100건, 특징끼리 상관, champion40 풀 생존편향."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
