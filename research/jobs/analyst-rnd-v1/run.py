"""검증 연구 analyst-rnd-v1: 애널리스트 목표가·등급 변경을 새틀라이트 선정에 더하면 현 규칙보다 나아지나. (사전 등록, 2026-10-08)

사용자 요청(2026-10-08): "평론가들이 어느 주식은 목표가가 얼마다 … 활용하면 좋지 않을까?" — 공포지수(VIX)는 info-rnd-v1·tech-rnd-v1 에서
이미 기각돼 다시 시험하지 않는다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
기준: 새틀라이트 R&D 현 규칙 S-SEED-000(champion40 풀, 돈치안 20일 추세 활성 중 12개월 모멘텀 상위 3, 반기 보유, 배당 포함 수익, 편도 8bp).
데이터: yfinance upgrades_downgrades(애널리스트별 등급·목표가 변경, 날짜 있음). 리밸런싱일 '전날까지' 발표된 것만 쓴다(미래 정보 없음).
  데이터가 없는 종목은 '변경 없음'으로 본다(거부·가점 없음). 기간: 2013-01 첫 리밸런싱부터(데이터가 2012년부터라 90일 이력 확보).
변형(모두 현 규칙의 점수·후보는 그대로, 아래만 더함 — 파라미터 탐색 없음):
  V1 목표가 하향 거부권  — 직전 90일 목표가 하향 ≥ 2건이고 하향 > 상향인 후보는 제외(다음 순위가 채움)
  V2 등급 하향 거부권    — 직전 30일 등급 하향(Action=down)이 1건이라도 있으면 제외
  V3 목표가 상향 가점    — 현 규칙 상위 6(2×3) 후보 중 직전 90일 (상향 − 하향) 건수가 많은 순 3개(동점은 현 규칙 점수)
  V4 목표가 괴리 상위    — 현 규칙 상위 6 후보 중 직전 180일 회사별 최신 목표가 평균 ÷ 전날 종가가 큰 순 3개(목표가 2개 이상만, 없으면 뒤로)
판정 analyst-judge/v1 (변형마다 현 규칙 대비, 모두 만족해야 PASS = 사람 검토 대기, 엔진 자동 반영 없음):
  1. 앞 구간(마지막 2년 전까지) 반기 구간별 초과수익의 평균 > 0 이고 단측 t ≥ 본페로니 임계값(α = 0.05/4, 자유도 = 구간 수 − 1)
  2. 떼어 둔 마지막 2년 누적 초과수익 > 0
  3. 앞 구간 반기 중 선택이 실제로 바뀐 구간 ≥ 3 (효과를 낼 기회가 있었는지)
한계: 무료 데이터 누락·소급 수정 가능성, 풀이 현재 S&P500 기반 champion40(생존편향), 표본이 반기 약 20개로 작다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import satellite_lab as sl  # noqa: E402

JUDGE_VERSION = "analyst-judge/v1"
START = "2012-09-01"
FIRST_REBAL = pd.Timestamp("2013-01-01")
ALPHA = 0.05
VARIANTS = {
    "V1": "목표가 하향 거부권(90일 하향 ≥ 2 & 하향 > 상향)",
    "V2": "등급 하향 거부권(30일 내 하향 1건)",
    "V3": "목표가 상향 가점(상위 6 중 90일 상향−하향 순)",
    "V4": "목표가 괴리 상위(상위 6 중 평균 목표가 ÷ 종가 순)",
}


# ---------------------------------------------------------------- 애널리스트 데이터
def _fetch_actions(tickers, cache_path: Path, smoke: bool, rng=None) -> dict[str, pd.DataFrame]:
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    out = {}
    for i, t in enumerate(sorted(tickers)):
        if t not in cache:
            if smoke:
                days = pd.bdate_range("2012-01-02", "2016-12-30")
                pick = sorted(rng.choice(len(days), size=int(rng.integers(5, 40)), replace=False))
                rows = []
                for j in pick:
                    up = rng.random() < 0.5
                    prior = float(rng.uniform(20, 80))
                    rows.append({"date": str(days[j].date()), "firm": f"F{rng.integers(0, 6)}", "action": "up" if up and rng.random() < 0.3 else ("down" if rng.random() < 0.2 else "main"),
                                 "pt_action": "Raises" if up else "Lowers", "cur": prior * (1.1 if up else 0.9), "prior": prior})
                cache[t] = rows
            else:
                try:
                    import yfinance as yf

                    ud = yf.Ticker(t).upgrades_downgrades
                    rows = []
                    if ud is not None and not ud.empty:
                        for d, r in ud.iterrows():
                            rows.append({"date": str(pd.Timestamp(d).date()), "firm": str(r.get("Firm") or ""),
                                         "action": str(r.get("Action") or ""), "pt_action": str(r.get("priceTargetAction") or ""),
                                         "cur": float(r.get("currentPriceTarget") or 0.0), "prior": float(r.get("priorPriceTarget") or 0.0)})
                    cache[t] = rows
                except Exception as exc:  # noqa: BLE001 - 한 종목 실패는 '데이터 없음'
                    print(f"  {t} 조회 실패: {type(exc).__name__}", flush=True)
                    cache[t] = []
                time.sleep(0.3)
            if i % 25 == 0:
                cache_path.write_text(json.dumps(cache), encoding="utf-8")
        df = pd.DataFrame(cache[t])
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
        out[t] = df
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return out


def _window(df: pd.DataFrame, cutoff: pd.Timestamp, days: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    return df[(df["date"] <= cutoff) & (df["date"] > cutoff - pd.Timedelta(days=days))]


def _counts(df: pd.DataFrame, cutoff, days: int) -> tuple[int, int]:
    w = _window(df, cutoff, days)
    if w.empty:
        return 0, 0
    raises = ((w["pt_action"] == "Raises") | ((w["prior"] > 0) & (w["cur"] > w["prior"]))).sum()
    lowers = ((w["pt_action"] == "Lowers") | ((w["prior"] > 0) & (w["cur"] > 0) & (w["cur"] < w["prior"]))).sum()
    return int(raises), int(lowers)


def _implied_upside(df: pd.DataFrame, cutoff, price: float) -> float | None:
    w = _window(df, cutoff, 180)
    if w.empty or not price > 0:
        return None
    w = w[w["cur"] > 0].sort_values("date").groupby("firm").tail(1)
    if len(w) < 2:
        return None
    return float(w["cur"].mean() / price - 1)


def make_signal(base, vid: str, actions: dict, top_k: int, log: dict):
    def signal(prices, cutoff, params):
        scores = base(prices, cutoff, params)
        ranked = sorted(((t, s) for t, s in scores.items() if s is not None and math.isfinite(float(s))), key=lambda kv: (-kv[1], kv[0]))
        base_pick = [t for t, _ in ranked[:top_k]]
        cut = pd.Timestamp(cutoff)
        if vid == "V0":
            new = dict(scores)
        elif vid in ("V1", "V2"):
            new = {}
            for t, s in scores.items():
                df = actions.get(t)
                if vid == "V1":
                    r, l = _counts(df, cut, 90)
                    veto = l >= 2 and l > r
                else:
                    w = _window(df, cut, 30)
                    veto = (not w.empty) and (w["action"] == "down").any()
                new[t] = None if veto else s
        else:
            top = ranked[:2 * top_k]
            keyed = []
            for t, s in top:
                if vid == "V3":
                    r, l = _counts(actions.get(t), cut, 90)
                    keyed.append((t, (r - l, s)))
                else:
                    px = float(prices[t]["Close"].dropna().iloc[-1]) if t in prices else float("nan")
                    up = _implied_upside(actions.get(t), cut, px)
                    keyed.append((t, (0 if up is None else 1, up if up is not None else -1e9, s)))
            keyed.sort(key=lambda kv: kv[1], reverse=True)
            # pick_top 은 점수 내림차순이므로 순서를 점수로 바꿔 넘긴다
            new = {t: float(len(keyed) - i) for i, (t, _) in enumerate(keyed)}
        chosen = sorted(((t, s) for t, s in new.items() if s is not None and math.isfinite(float(s))), key=lambda kv: (-kv[1], kv[0]))[:top_k]
        log.setdefault(vid, []).append({"date": str(cut.date()), "changed": sorted(t for t, _ in chosen) != sorted(base_pick)})
        return new
    return signal


def t_quantile(p: float, df: int) -> float:
    """스튜던트 t 분위수(scipy 없이) — 정규 분위수에 코니시-피셔 전개 4항(자유도 5 이상에서 오차 ~0.01 이하)."""
    from statistics import NormalDist

    z = NormalDist().inv_cdf(p)
    v = float(df)
    return float(z + (z ** 3 + z) / (4 * v) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * v ** 2)
                 + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * v ** 3)
                 + (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / (92160 * v ** 4))


def _period_returns(r: pd.Series, schedule) -> pd.Series:
    dates = [pd.Timestamp(d) for d, _ in schedule]
    out = {}
    for i, d in enumerate(dates):
        end = dates[i + 1] if i + 1 < len(dates) else r.index[-1] + pd.Timedelta(days=1)
        seg = r[(r.index > d) & (r.index <= end)]
        if len(seg):
            out[d] = float((1 + seg).prod() - 1)
    return pd.Series(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    base = sl.load_signal(code)
    params = dict(spec["signal"]["params_grid"][0])
    k = spec["portfolio"]["top_k"]
    if a.smoke:
        pp, poolp = sl.synthetic_providers(n_tickers=30, start="2011-01-01", end="2016-12-30")
        data = sl.build_data({spec["pool"]["type"]}, start=START, end="2016-12-30", pool_provider=poolp, price_provider=pp)
    else:
        data = sl.build_data({spec["pool"]["type"]}, start=START, log=lambda s: print(s, flush=True))
    tickers = set()
    for d in sl.rebalance_dates(data.trading_days, spec["portfolio"]["hold_months"]):
        tickers.update(data.pool(spec["pool"]["type"], d))
    actions = _fetch_actions(tickers, ck / "analyst_actions.json", a.smoke, np.random.default_rng(3))
    coverage = sum(1 for t in tickers if actions.get(t) is not None and not actions[t].empty) / max(len(tickers), 1)

    log: dict = {}
    runs = {}
    for vid in ["V0", *VARIANTS]:
        res = sl.run_variant(spec, params, make_signal(base, vid, actions, k, log), data)
        sched = [(d, p) for d, p in res["schedule"] if pd.Timestamp(d) >= FIRST_REBAL]
        runs[vid] = {"returns": res["returns"], "schedule": sched}
    base_r = runs["V0"]["returns"]
    split = base_r.index[-1] - pd.DateOffset(years=2)
    n_var = len(VARIANTS)
    verdicts, details = {}, {}
    for vid, label in VARIANTS.items():
        act = (runs[vid]["returns"] - base_r.reindex(runs[vid]["returns"].index).fillna(0.0)).dropna()
        act = act[act.index > FIRST_REBAL]
        per = _period_returns(runs[vid]["returns"], runs["V0"]["schedule"]) - _period_returns(base_r, runs["V0"]["schedule"])
        is_per = per[per.index < split]
        n = len(is_per)
        t = float(is_per.mean() / (is_per.std(ddof=1) / math.sqrt(n))) if n > 2 and is_per.std(ddof=1) > 0 else float("nan")
        t_crit = t_quantile(1 - ALPHA / n_var, max(n - 1, 1))
        hold = float((1 + act[act.index >= split]).prod() - 1)
        changed = sum(1 for x in log.get(vid, []) if x["changed"] and pd.Timestamp(x["date"]) < split and pd.Timestamp(x["date"]) >= FIRST_REBAL)
        checks = {"is_mean_positive_and_t": bool(n > 2 and is_per.mean() > 0 and t >= t_crit), "holdout_positive": hold > 0,
                  "changed_periods_ge_3": changed >= 3}
        verdicts[vid] = "PASS" if all(checks.values()) else "FAIL"
        full = (1 + act).prod() - 1
        yrs = max(len(act) / 252, 1e-9)
        details[vid] = {"label": label, "checks": checks, "is_periods": n, "is_mean_period_excess": float(is_per.mean()) if n else None,
                        "t": t, "t_crit": t_crit, "holdout_cum_excess": hold, "changed_periods_is": changed,
                        "full_annual_excess": float((1 + full) ** (1 / yrs) - 1)}
    yrs0 = len(base_r[base_r.index > FIRST_REBAL]) / 252
    base_cagr = float((1 + base_r[base_r.index > FIRST_REBAL]).prod() ** (1 / yrs0) - 1) if yrs0 else None
    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "coverage": coverage, "n_tickers": len(tickers),
              "baseline_cagr": base_cagr, "holdout_start": str(split.date())}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    lines = [f"# 애널리스트 R&D v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if a.smoke else ''}", "",
             f"기준: 현 새틀라이트 규칙(S-SEED-000) 연 {base_cagr * 100:.2f}% (2013-01~). 애널리스트 데이터가 있는 종목 {coverage:.0%} / {len(tickers)}종목. 떼어 둔 구간 {split.date()}~.", "",
             "| 변형 | 판정 | 연 초과(전체) | 앞 구간 반기 평균 초과 | t / 임계 | 떼어 둔 2년 누적 초과 | 선택이 바뀐 반기 |", "|---|---|---|---|---|---|---|"]
    for vid, d in details.items():
        lines.append(f"| {vid} {d['label']} | {verdicts[vid]} | {d['full_annual_excess'] * 100:+.2f}% | "
                     f"{(d['is_mean_period_excess'] or 0) * 100:+.2f}% | {d['t']:.2f} / {d['t_crit']:.2f} | {d['holdout_cum_excess'] * 100:+.2f}% | {d['changed_periods_is']} |")
    lines += ["", "PASS 는 사람 검토 대기이며 엔진에 자동 반영되지 않는다.",
              "한계: 무료 데이터 누락·소급 수정 가능성, champion40 풀의 생존편향, 반기 표본이 작음."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
