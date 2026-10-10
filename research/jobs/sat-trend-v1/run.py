"""검증 연구 sat-trend-v1: 새틀라이트(대형주 선정)를 주력으로 쓰되 SPY 200일선 아래면 BIL 로 빠지기 (사전 등록, 2026-10-10).

사용자 목표(2026-10-10): "안전하면서 시장을 압도적으로 이기는 방법". 엔진 안에서 SPY 를 크게 이긴 유일한 부품은 새틀라이트
(2018-03~2026-10 월별 단독 CAGR 26.2%, MDD −22.6%)다. 다만 단독으로 쓰면 하락장 노출이 그대로다. 근거(우리 엔진 재현 아님):
Faber(2007, "A Quantitative Approach to Tactical Asset Allocation") — 10개월/200일선 필터가 수익은 비슷하게, 낙폭은 크게 줄였다.
Antonacci(dual momentum) — 절대 모멘텀 필터가 상대 모멘텀 전략의 큰 하락을 잘랐다. 반론: 새틀라이트 후보가 현재 S&P500 명단이라
생존편향(실제보다 좋게), 필터 오신호 비용·세금. sleeve-weight-v1(필터 없이 15/25/35/50% 비중만 바꿈)과 다르다 —
여기서는 비중을 크게 하는 대신 새틀라이트 슬리브에만 시장 추세 필터를 건다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
새틀라이트 선정: core.champion_strategy.run_champion_backtest 의 반기 point-in-time 선정 기록(champion-aftertax-v1 과 같은 방식).
필터: 매월 첫 거래일, 전날 SPY 종가 < 200일선이면 새틀라이트 몫 전부 BIL, 위면 선정 종목(기록 비중).
T1 새틀라이트 100% + 필터
T2 SPY 50% 영구 보유(세금 이연) + 새틀라이트 50% + 필터 (계좌 둘로 계산)
비교 대상: SPY 그냥 보유. 기간 2010-01 ~ 실행일(첫 선정일부터), 마지막 2년 떼어 둠. 계좌 core/tax_fx 기본.
판정 lever-judge/v1(lev-trend-v1/run.py 의 judge 를 그대로 import): 세후·청산 후 원화 ≥ SPY + 3%p & 원화 MDD ≥ −29.2%
& 떼어 둔 2년 > SPY & DSR ≥ 0.95(시도 6 = 이 연구 2 + lev-trend-v1 4) & 가족 PBO ≤ 25%. PASS = 사람 검토 후보.
한계: 생존편향(가장 큼 — PASS 라도 delisted 데이터로 다시 확인 전에는 반영 금지), 돈치안 손절은 선정 기록에 없어 반영 안 됨,
두 계좌 공제 각자 적용, 일봉 종가 체결.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import tax_fx as tx  # noqa: E402

_spec = importlib.util.spec_from_file_location("lev_trend_v1", PROJECT_ROOT / "research" / "jobs" / "lev-trend-v1" / "run.py")
lv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lv)

START = "2010-01-01"
SPY, BIL = lv.SPY, lv.BIL


def _real():
    from core import champion_strategy as cs
    from core.market_data import get_multiple_price_history

    log = cs.run_champion_backtest(START, date.today().isoformat())["satellite"]["rebal_log"]
    tick = sorted({t for r in log for t in (r.get("weights") or {})} | {SPY, BIL})
    h = get_multiple_price_history(tick, start="2009-01-01", end=None, interval="1d")
    close = pd.DataFrame({t: h[t]["Close"] for t in tick if t in h and not h[t].empty}).sort_index()
    adj = pd.DataFrame({t: h[t]["Adj Close"] for t in tick if t in h and not h[t].empty}).sort_index()
    days = close[SPY].dropna().index
    return log, close.reindex(days).ffill(), adj.reindex(days).ffill(), tx.usdkrw_series()


def _smoke():
    idx = pd.bdate_range("2008-01-02", "2014-12-31")
    rng = np.random.default_rng(11)
    drift = np.where((idx >= "2008-06-01") & (idx < "2009-03-01"), -0.002, 0.0005)
    names = ["S1", "S2", "S3", SPY]
    close = pd.DataFrame({t: 50 * np.exp(np.cumsum(drift + rng.normal(0.0002, 0.015, len(idx)))) for t in names}, index=idx)
    close[BIL] = 90 + np.arange(len(idx)) * 0.002
    log = [{"date": "2010-01-04", "weights": {"S1": 0.5, "S2": 0.5}}, {"date": "2011-07-01", "weights": {"S2": 0.5, "S3": 0.5}},
           {"date": "2013-01-02", "weights": {"S1": 0.5, "S3": 0.5}}]
    return log, close, close.copy(), pd.Series(1100.0, index=idx)


def filtered_satellite(close, log):
    sat = tx.champion_weights(pd.DataFrame(index=close.index), log, 1.0)
    days = sat.index
    sma = close[SPY].rolling(200, min_periods=200).mean()
    below = (close[SPY] < sma).astype(float).shift(1).reindex(days)
    first = pd.Series(days, index=days).groupby(days.to_period("M")).transform("first")
    state = pd.Series(np.where(days == first.values, below.fillna(0.0), np.nan), index=days).ffill().fillna(0.0)
    w = sat.mul(1 - state, axis=0)
    w[BIL] = state
    return w.fillna(0.0), int((state.diff().abs() > 0).sum())


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log, close, adj, fx = _smoke() if a.smoke else _real()
    sat_f, switches = filtered_satellite(close, log)
    days = sat_f.index
    split = days[-1] - pd.DateOffset(years=2)
    cap = lv.CAPITAL
    spy_w = tx.buy_and_hold_weights(days)
    variants = {"SPY": ("SPY 그냥 보유", [(spy_w, cap)]),
                "T1": ("T1 새틀라이트 100% + 200일선 필터", [(sat_f, cap)]),
                "T2": ("T2 SPY 50% 영구 + 새틀라이트 50% + 필터", [(spy_w, 0.5 * cap), (sat_f, 0.5 * cap)])}
    stats, daily = lv.summarize(variants, close, adj, fx, days, split)
    names = ["SPY", "T1", "T2"]
    verdicts, details, pbo = lv.judge(names, daily, stats, days, split)
    result = {"judge_version": lv.JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "stats": stats, "family_pbo": pbo, "filter_switches": switches,
              "satellite_rebalances": len(log), "period": [str(days[0].date()), str(days[-1].date())], "holdout_start": str(split.date())}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    lv.write_report(out, "추세 필터 새틀라이트 주력 v1", verdicts, details, stats, names, pbo, split, a.smoke,
                    [f"필터 전환 {switches}회, 새틀라이트 반기 선정 {len(log)}회.",
                     "한계: 새틀라이트 후보가 현재 S&P500 명단(생존편향 — PASS 라도 상장폐지 포함 데이터로 재확인 전 반영 금지), "
                     "돈치안 손절 미반영, 두 계좌 공제 각자 적용, 일봉 종가 체결. 과거 결과이며 앞으로의 수익을 뜻하지 않는다."])
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
