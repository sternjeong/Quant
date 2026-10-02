"""검증 연구 exec-rnd-v1: 같은 종목을 '언제·얼마에' 사고팔면 리밸런싱 날 종가보다 나은가. (사전 등록, 2026-10-02)

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
매매 목록(종목 선택은 그대로):
  - 코어: 라이브 엔진 _build_core_weights(가격 신호, 남는 몫 BIL)의 목표 비중 변화. BIL 매매는 제외. 비중 × CORE_WEIGHT.
  - 새틀라이트: 새틀라이트 R&D 현 규칙(S-SEED-000, champion40 풀)의 반기 재선정 — 새로 담는 종목 매수, 빠지는 종목 매도.
  - 기간: 2010-01-01 ~ 실행일. 마지막 2년은 떼어 둔다.
실행 방법(core/execution_lab.RULES, 매수·매도 대칭): 다음 날 시가 / 지정가 1%·5일 / 2%·5일 / 3%·10일 / 3분할 / 눌림목.
새틀라이트 익절: +20%·+40% 도달 종가에 팔고 다음 재선정까지 현금.
칸 = (슬리브, 방향, 방법) 26개.
판정 exec-judge/v1 (칸마다, 모두 만족해야 PASS = 사람 검토 대기, 엔진 자동 반영 없음):
  - IS 리밸런싱 날짜 단위 가중 평균 개선 > 0 이고 t ≥ 본페로니 임계값(단측 α=0.05/칸 수)
  - 떼어 둔 2년의 평균 개선 > 0
  - IS 를 시간순 3등분했을 때 2구간 이상에서 평균 개선 > 0
한계: 일봉 근사 체결(저가가 지정가에 닿으면 지정가 체결), 기다리는 동안의 현금 이자·세금 미반영, 새틀라이트 상장폐지 종목 결측.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import champion_strategy as cs  # noqa: E402
from core import execution_lab as xl  # noqa: E402
from core import satellite_lab as sl  # noqa: E402

START = "2010-01-01"


def _ohlc_frames(smoke: bool):
    tickers = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    if smoke:
        idx = pd.bdate_range("2009-01-01", "2016-12-30")
        rng = np.random.default_rng(9)
        hist = {}
        for t in tickers:
            c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(idx))))
            o = c * np.exp(rng.normal(0, 0.004, len(idx)))
            hist[t] = pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.006, "Low": np.minimum(o, c) * 0.994,
                                    "Close": c, "Adj Close": c, "Volume": 1e6}, index=idx)
        return hist
    from core.market_data import get_multiple_price_history

    return get_multiple_price_history(tickers, start="2008-06-01", end=None, interval="1d")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    start = "2011-01-03" if a.smoke else START

    # --- 코어 매매 ---
    hist = _ohlc_frames(a.smoke)
    tick = [t for t in list(cs.CORE_UNIVERSE) + [cs.CORE_CASH_ETF] if t in hist]
    closes = cs._closes_from_histories(hist, tick + [cs.MARKET_FILTER_TICKER])
    w = cs._build_core_weights(closes[tick], closes[cs.MARKET_FILTER_TICKER],
                               cash_ticker=cs.CORE_CASH_ETF if cs.CORE_CASH_ETF in tick else None)
    w = w[w.index >= pd.Timestamp(start)]
    trades = xl.core_trades(w, cs.CORE_WEIGHT)
    frames = {t: hist[t].sort_index() for t in tick}

    # --- 새틀라이트 매매 ---
    if a.smoke:
        pp, poolp = sl.synthetic_providers(n_tickers=30, start="2009-01-01", end="2016-12-30")
        data = sl.build_data({"champion40"}, start=start, end="2016-12-30", pool_provider=poolp, price_provider=pp)
    else:
        data = sl.build_data({"champion40"}, start=start)
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    sched = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)["schedule"]
    trades += xl.satellite_trades(sched, cs.SATELLITE_WEIGHT)
    frames.update({t: df.sort_index() for t, df in data.ohlcv.items()})

    last = max(df.index[-1] for df in frames.values())
    split = last - pd.DateOffset(years=xl.HOLDOUT_YEARS)
    cells: dict[str, pd.DataFrame] = {}
    for sleeve in ("core", "satellite"):
        for side in ("buy", "sell"):
            rows = [tr for tr in trades if tr["sleeve"] == sleeve and tr["side"] == side]
            for rule in xl.RULES:
                recs = [{"date": tr["date"], "w": tr["w"], "imp": xl.improvement(frames[tr["ticker"]], tr["date"], side, rule)}
                        for tr in rows if tr["ticker"] in frames]
                cells[f"{sleeve}|{side}|{rule}"] = pd.DataFrame(recs, columns=["date", "w", "imp"])
    for name, tp in xl.TAKE_PROFITS.items():
        recs = []
        for tr in trades:
            if tr["sleeve"] == "satellite" and tr["side"] == "buy" and tr["ticker"] in frames:
                end = tr.get("end") or last
                recs.append({"date": tr["date"], "w": tr["w"], "imp": xl.take_profit_improvement(frames[tr["ticker"]], tr["date"], end, tp)})
        cells[f"satellite|hold|{name}"] = pd.DataFrame(recs, columns=["date", "w", "imp"])

    res = xl.judge(cells, split)
    verdicts = {k: v["verdict"] for k, v in res["cells"].items()}
    for k, v in res["cells"].items():
        print(f"{k}: {v['verdict']} IS {v.get('mean_is_bps')}bp t={v.get('t_is')} OOS {v.get('mean_oos_bps')}bp 연 {v.get('portfolio_bps_per_year')}bp", flush=True)
    payload = {"id": "exec-rnd-v1", "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "period_start": start, "split": str(split.date()), "n_trades": len(trades),
               "n_core_trades": sum(1 for t in trades if t["sleeve"] == "core"),
               "n_satellite_trades": sum(1 for t in trades if t["sleeve"] == "satellite"),
               "verdicts": verdicts, **res}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(payload), encoding="utf-8")
    return 0


LABEL = {"buy": "매수", "sell": "매도", "hold": "보유 중", "core": "코어", "satellite": "새틀라이트",
         **xl.RULES, "tp20": "+20% 익절", "tp40": "+40% 익절"}


def report(p: dict) -> str:
    lines = ["# 매매 실행 R&D v1 — 언제·얼마에 사고팔까", "",
             f"생성 {p['generated_at']} · {p['period_start']}~ · 떼어 둔 구간 {p['split']} 이후 · 매매 {p['n_trades']}건"
             f"(코어 {p['n_core_trades']}, 새틀라이트 {p['n_satellite_trades']})" + (" · **스모크(합성 데이터) — 실제 결과 아님**" if p["smoke"] else ""), "",
             "기준: 리밸런싱 날 종가 매매. 숫자는 그 기준 대비 개선(bp=0.01%). 매수는 더 싸게 산 만큼, 매도는 더 비싸게 판 만큼 +.", "",
             f"## 판정 (exec-judge/v1, 칸 {p['n_tests']}개 → t 임계값 {p['t_crit']})", "",
             "| 슬리브 | 방향 | 방법 | 판정 | 앞 구간 평균 | t | 최근 2년 평균 | 포트폴리오 연 효과 | 유리했던 비율 | 사유 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in p["cells"].items():
        sleeve, side, rule = k.split("|")
        f = lambda x: "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.1f}bp"  # noqa: E731
        lines.append(f"| {LABEL[sleeve]} | {LABEL[side]} | {LABEL[rule]} | **{v['verdict']}** | {f(v.get('mean_is_bps'))} | "
                     f"{'—' if v.get('t_is') is None else v.get('t_is')} | {f(v.get('mean_oos_bps'))} | {f(v.get('portfolio_bps_per_year'))} | "
                     f"{'—' if v.get('hit_rate') is None else f'{v['hit_rate']:.0%}'} | {'; '.join(v.get('reasons') or []) or '—'} |")
    lines += ["", "- 포트폴리오 연 효과: 매매 비중을 곱해 1년 평균으로 환산한 전체 계좌 기준 효과(대략치).",
              "- PASS 도 엔진에 자동 반영되지 않는다. 일봉 근사 체결이라 실제 지정가 체결과 다를 수 있다. 과거 결과는 미래를 보장하지 않는다."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
