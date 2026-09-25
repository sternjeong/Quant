"""가설 shadow 전진 검증 (설계 S3, docs/AGENTIC_QUANT_SYSTEM_DESIGN.md 3.3절) — 관측 전용, 주문 없음.

매일(00:48 KST 잡):
1. judged_pass 가설을 오래된 순으로 shadow 에 올린다(동시 상한 SHADOW_CAP).
2. shadow 가설마다 오늘 기록 1건: 직전 기록의 비중이 오늘까지 실현한 수익(표류 반영, 리밸런싱 비용 차감)과
   다음에 적용할 비중. 비중은 스펙 주기(주/월)의 **새 기간 첫 기록일**에만 다시 계산한다(그 사이는 유지).
   백테스트는 기간 마지막 거래일 종가로 정하므로 하루 차이가 있다 — 알려진 차이로 남긴다.
3. 실현 거래일이 FORWARD_DAYS(60) 이상 쌓이면 판정: 전진 일평균 m 을 백테스트 일평균 μ·표준편차 σ 와 비교해
   z = (m−μ)/(σ/√n) ≥ −1.96(백테스트보다 유의하게 나쁘지 않음)이면 promotion_candidate, 아니면 retired.
   승격 후보는 "paper 에서 더 볼 가치가 있다"이지 검증 완료가 아니다.
신호에는 최근 SHADOW_HISTORY_DAYS 달력일 이력만 넘긴다(백테스트와 다른 점, 확장형 지표는 값이 다를 수 있다).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Callable, Optional

import pandas as pd

from core import hypothesis_engine as he
from core import hypothesis_registry as reg
from core.models import HypothesisShadowRecord

ET = ZoneInfo("America/New_York")
FORWARD_DAYS = 60
Z_FLOOR = -1.96
SHADOW_HISTORY_DAYS = 1100


def _period(d: date, rule: str) -> tuple:
    iso = d.isocalendar()
    return (iso[0], iso[1]) if rule == "weekly" else (d.year, d.month)


def _drift_return(weights: dict[str, float], prices: dict[str, pd.DataFrame], start: pd.Timestamp,
                  end: pd.Timestamp) -> tuple[float, int, dict[str, float]]:
    """start 종가 → end 종가 사이 표류 수익, 거래일 수, 표류 후 비중."""
    if not weights:
        return 0.0, 0, {}
    grown, days = {}, set()
    for t, w in weights.items():
        df = prices.get(t)
        col = "Adj Close" if df is not None and "Adj Close" in df else "Close"
        if df is None or df.empty:
            grown[t] = w
            continue
        seg = df[col].loc[start:end]
        days |= set(seg.index[1:])
        grown[t] = w * (float(seg.iloc[-1] / seg.iloc[0]) if len(seg) >= 2 else 1.0)
    cash = 1 - sum(weights.values())
    total = cash + sum(grown.values())
    return total - 1, len(days), {t: v / total for t, v in grown.items()}


def record_day(hyp: dict, as_of: date, *, session, price_provider=None) -> dict[str, Any]:
    spec, best = hyp["spec"], (hyp["judge"] or {}).get("best_params", {})
    db = session
    if db.query(HypothesisShadowRecord).filter_by(hypothesis_id=hyp["id"], as_of=as_of).first():
        return {"id": hyp["id"], "status": "already_recorded"}
    prev = (db.query(HypothesisShadowRecord).filter(HypothesisShadowRecord.hypothesis_id == hyp["id"])
            .order_by(HypothesisShadowRecord.as_of.desc()).first())
    tickers, members_at = he.resolve_universe(spec)
    start = as_of - timedelta(days=SHADOW_HISTORY_DAYS)
    prices = he.load_prices(tickers, start, as_of, price_provider)
    ts = pd.Timestamp(as_of)
    prices = {t: df.loc[:ts] for t, df in prices.items()}

    realized, days, drifted = None, 0, {}
    prev_w = json.loads(prev.weights_json)["w"] if prev else {}
    if prev:
        realized, days, drifted = _drift_return(prev_w, prices, pd.Timestamp(prev.as_of), ts)
    rule = spec["portfolio"]["rebalance"]
    rebalance = prev is None or _period(prev.as_of, rule) != _period(as_of, rule)
    if rebalance:
        eligible = {t for t in members_at(as_of) if t in prices and not prices[t].empty and prices[t].index.max() == ts}
        scores = he.load_signal(hyp["signal_code"])({t: prices[t] for t in eligible}, ts, dict(best)) or {}
        new_w = he.select_weights(scores, spec["portfolio"]["top_k"], spec["portfolio"]["max_weight"], eligible)
        turnover = sum(abs(new_w.get(k, 0) - drifted.get(k, 0)) for k in set(new_w) | set(drifted))
        bps = (hyp["judge"] or {}).get("cost_one_way_bps", he.DEFAULT_ONE_WAY_BPS)
        if realized is not None:
            realized -= turnover * bps / 1e4
    else:
        new_w = drifted
    db.add(HypothesisShadowRecord(hypothesis_id=hyp["id"], as_of=as_of, realized_return=realized,
                                  weights_json=json.dumps({"w": new_w, "days": days, "rebalanced": rebalance})))
    db.flush()
    return {"id": hyp["id"], "status": "recorded", "realized": realized, "days": days, "rebalanced": rebalance}


def forward_verdict(hyp: dict, *, session) -> Optional[dict[str, Any]]:
    rows = (session.query(HypothesisShadowRecord).filter(HypothesisShadowRecord.hypothesis_id == hyp["id"],
                                                         HypothesisShadowRecord.realized_return.isnot(None)).all())
    n = sum(json.loads(r.weights_json).get("days", 0) for r in rows)
    if n < FORWARD_DAYS:
        return None
    growth = math.prod(1 + r.realized_return for r in rows)
    m = growth ** (1 / n) - 1
    st = (hyp["judge"] or {}).get("stats", {})
    mu, sd = st.get("mean_daily", 0.0), st.get("sd_daily", 0.0)
    z = (m - mu) / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n_days": n, "forward_mean_daily": m, "forward_cum": growth - 1, "backtest_mean_daily": mu, "z": z,
            "verdict": "candidate" if z >= Z_FLOOR else "retire"}


US_CLOSE_SETTLED = (16, 15)  # 미 동부 16:15 이후에만 그날 일봉을 완성된 것으로 본다


def latest_trading_day(price_provider=None, today: Optional[date] = None, now_et: Optional[datetime] = None) -> Optional[date]:
    """완성된(장 마감된) 최신 거래일. 00:48 KST 는 미 장중이라 오늘 봉은 미완성이므로 제외한다."""
    now_et = now_et or datetime.now(ET)
    today = today or now_et.date()
    spy = he.load_prices(["SPY"], today - timedelta(days=10), today, price_provider).get("SPY")
    if spy is None:
        return None
    spy = spy.loc[:pd.Timestamp(today)]  # 공급자가 요청보다 긴 이력을 돌려줘도 today 이후는 보지 않는다
    if today == now_et.date() and (now_et.hour, now_et.minute) < US_CLOSE_SETTLED:
        spy = spy.loc[:pd.Timestamp(today - timedelta(days=1))]
    return spy.index.max().date() if not spy.empty else None


def approval_buttons(hid: str) -> list[list[dict]]:
    """텔레그램 인라인 버튼. 콜백은 deploy/codex_telegram/runner.py 의 'h:' 처리기가 받는다."""
    return [[{"text": "✅ paper 편입", "callback_data": f"h:promote:{hid}"},
             {"text": "🗑 종료", "callback_data": f"h:retire:{hid}"}]]


def candidate_message(h: dict, v: dict) -> str:
    from core.research_sleeve import PER_HYPOTHESIS_MAX, SLEEVE_FRACTION

    return (f"[가설 승격 후보] {h['id']}\n{h['spec']['thesis'][:120]}\n"
            f"전진 {v['n_days']}거래일 누적 {v['forward_cum']:+.2%} (백테스트 대비 z={v['z']:.2f})\n"
            f"편입하면 paper 계좌 research 슬리브(전체 {SLEEVE_FRACTION:.0%}, 가설당 최대 {PER_HYPOTHESIS_MAX:.0%})에 "
            f"다음 자동 주문부터 들어갑니다. 누르지 않으면 아무것도 바뀌지 않습니다.")


def run_daily(*, session=None, price_provider=None, today: Optional[date] = None,
              notify: Optional[Callable[[str, list], Any]] = None) -> dict[str, Any]:
    out: dict[str, Any] = {"promoted_to_shadow": [], "recorded": [], "errors": [], "verdicts": []}
    for h in reg.list_by_status(reg.PASS, session=session):
        try:
            reg.transition(h["id"], reg.SHADOW, "shadow 시작", session=session)
            out["promoted_to_shadow"].append(h["id"])
        except reg.CapReached:
            break
    as_of = latest_trading_day(price_provider, today)
    if as_of is None:
        out["errors"].append("SPY 최신 거래일 확인 실패 — 오늘 기록 건너뜀")
        return out
    out["as_of"] = as_of.isoformat()
    # 승격 후보·승격 가설도 계속 기록한다: 전진 성과 추적과 research 슬리브(paper 편입) 비중의 원천이다.
    for h in reg.list_by_status(reg.SHADOW, reg.CANDIDATE, reg.PROMOTED, session=session):
        try:
            with reg._session(session) as db:
                out["recorded"].append(record_day(h, as_of, session=db, price_provider=price_provider))
                v = forward_verdict(h, session=db) if h["status"] == reg.SHADOW else None
            if v:
                to = reg.CANDIDATE if v["verdict"] == "candidate" else reg.RETIRED
                reg.transition(h["id"], to, f"전진 {v['n_days']}일 z={v['z']:.2f}", session=session,
                               judge={**(h["judge"] or {}), "forward": v})
                out["verdicts"].append({"id": h["id"], **v})
                if to == reg.CANDIDATE and notify:
                    notify(candidate_message(h, v), approval_buttons(h["id"]))
        except Exception as exc:  # noqa: BLE001 — 한 가설의 오류가 나머지를 막지 않는다
            out["errors"].append(f"{h['id']}: {type(exc).__name__}: {exc}"[:300])
    return out
