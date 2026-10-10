"""코어 분기 연구실 계산기 — VM 연구 실행기가 빈 창에 돌린다(core.research_jobs). core/core_rnd.py 대기열을 판정한다.

  python scripts/core_lab_worker.py --out <dir> --checkpoint <dir> [--smoke]

종료 코드: 0 = 대기열 비움, 3 = 시간 예산이 끝나 남은 것은 다음 창에. --smoke 는 합성 가격·임시 등록부(대화 세션에서는 이것만).
주제 'core_quarterly' 가 꺼져 있으면 아무것도 하지 않고 0. 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core import champion_strategy as cs  # noqa: E402
from core import core_lab as cl  # noqa: E402
from core import core_rnd as cr  # noqa: E402
from core import rnd_topics  # noqa: E402
from core import sprint_lab as sp  # noqa: E402

START = "2008-01-01"


def log(m):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {m}", flush=True)


def load(smoke: bool):
    tickers = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    if smoke:
        idx = pd.bdate_range("2006-01-02", "2016-12-30")
        rng = np.random.default_rng(8)
        hist = {t: pd.DataFrame({"Close": 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.011, len(idx))))}, index=idx) for t in tickers}
        for t in tickers:
            hist[t]["Adj Close"] = hist[t]["Close"] * np.exp(np.cumsum(np.full(len(idx), 0.00004)))
    else:
        from core.market_data import get_multiple_price_history

        hist = get_multiple_price_history(tickers, start="2006-01-01", end=None, interval="1d")
    names = [t for t in tickers if t in hist and not hist[t].empty]
    price = cs._closes_from_histories(hist, names)
    total = cs._closes_from_histories(hist, names, field=cs.CORE_PRICE_FIELD)
    core = [t for t in cs.CORE_UNIVERSE if t in names]
    ex = [t for t in (cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF) if t in names]
    return (price[core], price[ex]), (total[core], total[ex])


def run_idea(cfg_over: dict, exit_rule: dict, price, total, start: str) -> pd.Series:
    cfg = cr.build_config(cfg_over)
    sig = total if cfg.signal_basis == "total" else price
    w = cl.build_weights(sig[0], sig[1], cfg)
    if exit_rule and exit_rule.get("kind") != "none":
        w = sp.apply_core_exits(w, price[0], price[1][cs.MARKET_FILTER_TICKER], exit_rule)
    rc, re = total
    keep = rc.index >= pd.Timestamp(start)
    return cl.portfolio_returns(rc[keep], re[keep], w.reindex(rc.index).fillna(0.0)[keep])


def load_satellite(smoke: bool, index: pd.DatetimeIndex) -> pd.Series:
    """새틀라이트 슬리브 일간 순수익 — run_champion_backtest 와 같은 run_satellite_backtest 를 그대로 쓴다."""
    if smoke:
        rng = np.random.default_rng(11)
        return pd.Series(rng.normal(0.0006, 0.018, len(index)), index=index)
    from datetime import date

    return cs.run_satellite_backtest(START, date.today().isoformat(), index)["ret_net"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or time.time() + 3 * 3600) - 90
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    state_dir = Path(a.checkpoint) / "smoke_state" if a.smoke else None
    if a.smoke:
        cr.freeze({"id": "Q-2026q4-01", "title": "스모크", "thesis": "합성 데이터 확인", "source": "스모크",
                   "topic": "exit", "config": {"top_n": 5}, "exit_rule": {"kind": "trail", "p": 0.1, "freq": "weekly"},
                   "neighbors": [{"config": {"top_n": 4}}]}, "seed", state_dir)
        cr.freeze({"id": "Q-2026q4-02", "title": "스모크 비중", "thesis": "합성 데이터 확인", "source": "스모크",
                   "topic": "allocation", "config": {}, "satellite_weight": 0.3,
                   "neighbors": [{"config": {"top_n": 5}}]}, "seed", state_dir)
    elif not rnd_topics.is_on("core_quarterly"):
        log("주제 '코어 분기 연구'가 꺼져 있음 — 아무것도 하지 않음")
        return 0
    reg = cr.load_registry(state_dir)
    todo = cr.queue(reg)
    if not todo:
        log("대기 없음")
        return 0
    price, total = load(a.smoke)
    start = "2009-01-02" if a.smoke else START
    inc = run_idea({}, {"kind": "none"}, price, total, start)
    sat = None  # satellite_weight 아이디어가 있을 때만 한 번 계산(느림)
    judged = 0
    for entry in todo:
        if time.time() > deadline:
            break
        idea = entry["idea"]
        try:
            r = run_idea(idea["config"], idea["exit_rule"], price, total, start)
            nbs = [run_idea({**idea["config"], **(nb.get("config") or {})}, nb.get("exit_rule") or idea["exit_rule"], price, total, start)
                   for nb in idea.get("neighbors") or []]
            base = inc
            sw = idea.get("satellite_weight")
            if sw is not None:  # 전체 챔피언(코어+새틀라이트 sw) 대 현 챔피언(85/15)
                if sat is None:
                    sat = load_satellite(a.smoke, inc.index)
                base = cr.blend_champion(inc, sat, cr.CURRENT_SATELLITE_WEIGHT)
                r = cr.blend_champion(r, sat, sw)
                nbs = [cr.blend_champion(x, sat, sw) for x in nbs]
            res = cl.judge({"returns": r}, base, nbs, n_trials=int(cr.load_registry(state_dir)["cumulative_trials"]),
                           all_active_daily_srs=[])
            res["judged_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with cr.edit_registry(state_dir) as rg:
                v = rg["ideas"][entry["id"]]
                v.update(status=cr.STATUS_PASS if res["verdict"] == "PASS" else cr.STATUS_FAIL, result=res,
                         attempts=v.get("attempts", 0) + 1)
            log(f"판정 {entry['id']}: {res['verdict']} {'; '.join(res['reasons'])[:200]}")
        except Exception as exc:  # noqa: BLE001
            with cr.edit_registry(state_dir) as rg:
                v = rg["ideas"][entry["id"]]
                v["attempts"] = v.get("attempts", 0) + 1
                v["error"] = f"{type(exc).__name__}: {exc}"[:400]
                if v["attempts"] >= 3:
                    v["status"] = cr.STATUS_ERROR
            log(f"오류 {entry['id']}: {type(exc).__name__}: {exc}")
        judged += 1
    remaining = len(cr.queue(cr.load_registry(state_dir)))
    (out / "status.json").write_text(json.dumps({"judged": judged, "remaining": remaining}, ensure_ascii=False))
    return 3 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
