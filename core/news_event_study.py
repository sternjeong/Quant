"""core/news_event_study.py — 뉴스 게시 이후 수익률을 평소 수익률과 비교한다(로드맵 P2, 연구 전용).

core.alpaca_news 가 준 PIT 기사(published_at=created_at)와 일봉(Open/Close)을 받는다.

진입 규칙(미래 정보 차단): 기사가 미 동부 09:30 이전에 게시됐으면 그날 시가, 이후면 다음 거래일 시가에 진입한다.
같은 종목·같은 진입일의 기사는 1개 이벤트로 묶는다(같은 뉴스의 여러 기사로 표본이 부풀지 않게).
수익 = 진입 시가 → h 거래일째 종가. 비교군 = 같은 가격 구간의 모든 거래일에 같은 규칙으로 진입했을 때의 평균.

정직성 규칙: 이벤트 n >= MIN_EVENTS(30) 일 때만 평균·초과수익을 낸다(미만이면 None). 감성·방향은 판단하지 않으므로
이 결과는 "뉴스가 난 날 이후 변동이 평소와 다른가"까지만 말한다. 비용·생존편향은 반영하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
OPEN_ET = time(9, 30)
MIN_EVENTS = 30
HORIZONS = (1, 5)


def entry_index(published_at: str, days: pd.DatetimeIndex) -> int | None:
    """진입할 일봉 위치. 해당 거래일이 없으면 None."""
    ts = datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(ET)
    day = pd.Timestamp(ts.date())
    pos = int(days.searchsorted(day))
    if pos < len(days) and days[pos] == day and ts.time() >= OPEN_ET:
        pos += 1  # 장 시작 뒤 게시 → 다음 거래일
    return pos if pos < len(days) else None


def _fwd(prices: pd.DataFrame, i: int, h: int) -> float | None:
    j = i + h - 1
    if j >= len(prices):
        return None
    return float(prices["Close"].iloc[j] / prices["Open"].iloc[i] - 1.0)


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def event_study(articles: Iterable[dict[str, Any]], prices_by_ticker: dict[str, pd.DataFrame]) -> dict[str, Any]:
    events: set[tuple[str, int]] = set()
    for a in articles:
        for sym in a.get("symbols") or []:
            px = prices_by_ticker.get(sym)
            if px is None or px.empty:
                continue
            i = entry_index(a["published_at"], pd.DatetimeIndex(px.index).normalize())
            if i is not None:
                events.add((sym, i))
    out: dict[str, Any] = {"n_events": len(events), "min_events": MIN_EVENTS, "horizons": {}}
    for h in HORIZONS:
        ev = [r for s, i in events if (r := _fwd(prices_by_ticker[s], i, h)) is not None]
        base = [r for s, px in prices_by_ticker.items() if px is not None
                for i in range(len(px)) if (r := _fwd(px, i, h)) is not None]
        ok = len(ev) >= MIN_EVENTS
        em, bm = _mean(ev), _mean(base)
        out["horizons"][f"{h}d"] = {
            "n": len(ev), "status": "ok" if ok else "insufficient_sample",
            "event_mean_pct": round(em * 100, 4) if ok and em is not None else None,
            "baseline_mean_pct": round(bm * 100, 4) if bm is not None else None,
            "excess_pct_points": round((em - bm) * 100, 4) if ok and em is not None and bm is not None else None,
            "event_abs_mean_pct": round(_mean([abs(x) for x in ev]) * 100, 4) if ok else None,
            "baseline_abs_mean_pct": round(_mean([abs(x) for x in base]) * 100, 4) if base else None,
        }
    return out
