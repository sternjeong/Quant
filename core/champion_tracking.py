"""core/champion_tracking.py — 챔피언 전략이 실제 시장에서 백테스트대로 움직이는지 주 1회 판정한다(관측 전용).

무엇을 비교하나
---------------
1) 라이브: core.models.ChampionLedgerEntry(00:12 KST champion_ledger_record)가 매일 저장한 **추천 비중**을
   완성된 일봉 종가에 다시 적용해 거래일별 수익을 재구성한다. 원장의 realized_return_pct 를 그대로 쓰지 않는
   이유: 00:12 KST 는 미 장중(11:12 ET)이라 원장은 그날 미완성 봉으로 수익을 적고, KST 일·월요일 기록은
   이미 적은 금요일 수익을 다시 적는다(ET 토·일에는 새 거래일이 없다). 재구성은 거래일마다 정확히 한 번,
   장 마감 종가로 계산한다. 원장 기록값과의 차이는 '데이터 점검'에 함께 보여 준다.
   비중 적용 규칙: 원장 항목이 실제로 계산된 시각(created_at, UTC)을 미 동부 날짜 x 로 바꾸고, x 보다 **뒤**
   거래일부터 적용한다(x 종가에 체결했다고 보고 x→다음 거래일 종가 수익부터). 계산 시각이 장중이어도 그날 수익에는
   쓰지 않으므로 선견(lookahead)이 없다. 서버 시간대(KST/UTC)에 따라 entry_date 가 하루 달라져도 created_at
   기준이라 영향이 없다. created_at 이 없으면 entry_date 를 x 로 본다(하루 늦게 적용하는 보수적 대체).
   비중이 바뀐 날에는 백테스트와 같은 편도 비용(코어 CORE_COST_BPS_PER_SIDE, 새틀라이트
   SATELLITE_COST_BPS_PER_SIDE)을 뺀다.
2) 기대 범위: run_champion_backtest 의 일별 순수익(라이브 시작 **이전** 구간만)으로 라이브와 같은 길이 N
   거래일의 구간 누적수익을 모든 시작일에 대해(겹치는 창) 만들고, 라이브 N일 누적수익이 그 분포의 몇 분위인지
   계산한다. SPY·60/40(SPY/TLT, core.champion_strategy.compute_benchmark_comparison 과 같은 매수보유 정의)
   대비 초과수익도 같은 방식으로 본다. 백테스트 일별 수익은 data/cache/champion_backtest_daily.json 에
   캐시하고 6일보다 오래됐을 때만 다시 계산한다(주간 잡이므로 사실상 주 1회).

판정 규칙(사전 고정 — 아래 상수, 결과를 보고 바꾸지 않는다)
------------------------------------------------------------
- N < MIN_LIVE_SESSIONS(20, 기존 벤치마크 비교의 BENCHMARK_MIN_LEDGER_DAYS 재사용) → '판정하기엔 이름(표본 부족)'.
  수치(분위 등)는 계산해 보여 주되 판정하지 않는다.
- 라이브 누적수익 분위 < 1 또는 > 99, 또는 라이브 최대낙폭이 백테스트(라이브 이전 전체 구간) 최악 낙폭보다 깊음
  → '이탈 — 확인 필요'.
- 분위 < 5 또는 > 95 → '범위 밖 — 주의'.
- 5 ≤ 분위 ≤ 95 → '백테스트 범위 안(정상)'.
- 한 줄 판정은 절대 누적수익·최대낙폭으로만 낸다. SPY·60/40 초과수익의 분위는 같은 규칙으로 각각 표시만 한다
  (세 검정을 묶으면 거짓 경보가 늘어난다).
- '조치 필요' = 판정이 '이탈' 이거나 점검(실행·신호·데이터) 중 경고가 하나라도 있을 때.

정직성(결과 JSON·설명서에도 적는다)
------------------------------------
- 겹치는 롤링 창의 분위는 독립 표본이 아니다. 창들이 대부분의 날을 공유하므로 분포의 꼬리가 실제보다 매끈해
  보일 수 있고, 분위를 p-값처럼 읽으면 안 된다.
- 라이브 기간이 짧으면 기대 범위가 넓어서 거의 모든 결과가 '범위 안'이 된다(판정력이 낮다). 매주 겹치는 기간을
  다시 판정하므로 주마다의 판정도 서로 독립이 아니다.
- 백테스트 자체가 PIT 한계(새틀라이트 유니버스 표본추출·생존편향, 배당 미포함 Close)를 가진다. '범위 안'은
  '백테스트와 모순되지 않는다'는 뜻이지 전략이 좋다는 증거가 아니다.

기존 알림과의 관계(중복 금지)
------------------------------
- champion_benchmark_gap(00:13, 60/40 대비 -5%p)·champion_alpha_decay(00:18, 최근 6개월 샤프 이탈)는 각자
  알림을 보낸다. 이 모듈은 그 함수를 호출하지 않고(재전송·재계산 없음) 그들이 남긴 상태 파일만 읽어 요약에
  "발동 중(이미 전송됨)" 한 줄로 표시한다.
- 이 잡의 주간 요약은 같은 날 여러 번 실행돼도 한 번만 보낸다(리포트 JSON 의 notified 로 판단).

조회·계산 전용이다. 주문 경로(core.paper_execution, scripts/champion_paper_trade.py)를 import 하지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from core import champion_strategy as cs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_CACHE_PATH = PROJECT_ROOT / "data" / "cache" / "champion_backtest_daily.json"
REPORT_DIR = PROJECT_ROOT / "data" / "reports"
PAPER_TRACKING_PATH = PROJECT_ROOT / "data" / "cache" / "paper_tracking.json"

ET = ZoneInfo("America/New_York")
US_CLOSE_SETTLED = (16, 15)  # core.hypothesis_shadow 와 같은 기준: 16:15 ET 이후에만 그날 봉을 완성으로 본다

# ---- 판정 규칙(사전 고정) --------------------------------------------------------------------------------------
MIN_LIVE_SESSIONS = cs.BENCHMARK_MIN_LEDGER_DAYS  # 20 — 기존 벤치마크 비교와 같은 최소 표본
NORMAL_BAND = (5.0, 95.0)  # 이 분위 범위 안(경계 포함)이면 정상
DEVIATION_BAND = (1.0, 99.0)  # 이 범위를 벗어나면(경계 제외) 이탈
BACKTEST_LOOKBACK_YEARS = cs.CHAMPION_DECAY_FULL_LOOKBACK_YEARS  # 8 — 알파 감쇠 체크와 같은 구간 규모
BACKTEST_CACHE_MAX_AGE_DAYS = 6  # 주간 잡이 매주 새로 계산하도록 7일보다 짧게
MIN_BACKTEST_WINDOWS = 50  # 이보다 적은 창으로는 분위를 매기지 않는다
PAPER_GAP_WARN_PCT_POINTS = 3.0  # paper 계좌와 원장 누적 괴리가 이보다 크면 실행 점검 경고
PAPER_TRACKING_STALE_DAYS = 3  # paper_tracking.json 이 이보다 오래되면 경고
LEDGER_RECENT_GAP_DAYS = 7  # 최근 이 기간 안에 원장이 빠진 날이 있으면 경고
MAX_WEIGHT_AGE_DAYS = 4  # 마지막 원장 항목에서 이보다 오래 지난 거래일은 라이브 창에 넣지 않는다(낡은 비중)

VERDICT_LABELS = {
    "normal": "백테스트 범위 안(정상)",
    "outside": "범위 밖 — 주의",
    "deviation": "이탈 — 확인 필요",
    "insufficient": "판정하기엔 이름(표본 부족)",
    "unavailable": "판정 불가(백테스트·가격 데이터 없음)",
}
VERDICT_ICONS = {"normal": "✅", "outside": "🟡", "deviation": "🔴", "insufficient": "⏳", "unavailable": "⚪"}

LIMITATIONS = (
    "겹치는 롤링 창의 분위는 독립 표본이 아니다 — p-값처럼 읽지 말 것.",
    "라이브 기간이 짧을수록 기대 범위가 넓어 판정력이 낮다. 매주 판정도 기간이 겹쳐 서로 독립이 아니다.",
    "백테스트는 PIT 한계(새틀라이트 유니버스 표본추출·생존편향, 배당 미포함 Close)가 있다. '범위 안'은 성과의 증거가 아니다.",
    "라이브 수익은 원장 비중을 완성 종가에 재적용한 가상 수익이며 실제 체결·배당·세금을 반영하지 않는다.",
    "원장은 매일 목표를 다시 계산하지만 백테스트 코어는 월초에만 리밸런싱한다 — 신호 점검의 불일치 일수는 이 구조 차이를 포함한다.",
)


# ============================================================================================================
# 순수 계산 (네트워크·DB 없음 — 테스트는 손계산 데이터로 여기를 검증한다)
# ============================================================================================================

def _cum_products(returns: list[float]) -> list[float]:
    out, g = [1.0], 1.0
    for r in returns:
        g *= 1.0 + r
        out.append(g)
    return out


def compound(returns: Iterable[float]) -> float:
    g = 1.0
    for r in returns:
        g *= 1.0 + r
    return g - 1.0


def rolling_window_returns(returns: list[float], n: int) -> list[float]:
    """길이 n 의 모든 겹치는 창의 누적수익(복리). len(returns) < n 이면 빈 리스트."""
    if n <= 0 or len(returns) < n:
        return []
    c = _cum_products(returns)
    return [c[i + n] / c[i] - 1.0 for i in range(len(returns) - n + 1)]


def rolling_window_excess(strategy: list[float], spy: list[float], tlt: Optional[list[float]], n: int,
                          equity_weight: float = cs.BENCHMARK_6040_EQUITY_WEIGHT) -> dict[str, list[float]]:
    """창마다 (전략 누적 - SPY 누적), (전략 누적 - 60/40 누적). 60/40 은 창 시작 시 60:40 매수보유
    (compute_benchmark_comparison 과 같은 정의 = 두 자산 누적수익의 가중합)."""
    s = rolling_window_returns(strategy, n)
    b = rolling_window_returns(spy, n)
    out = {"spy": [x - y for x, y in zip(s, b)]}
    if tlt is not None:
        t = rolling_window_returns(tlt, n)
        out["sixty_forty"] = [x - (equity_weight * y + (1 - equity_weight) * z) for x, y, z in zip(s, b, t)]
    return out


def percentile_rank(dist: list[float], x: float) -> Optional[float]:
    """x 가 분포 dist 에서 몇 분위인지(0~100). 같은 값은 절반만 센다(mid-rank)."""
    if not dist:
        return None
    below = sum(1 for v in dist if v < x)
    ties = sum(1 for v in dist if v == x)
    return 100.0 * (below + 0.5 * ties) / len(dist)


def quantile(dist: list[float], q: float) -> Optional[float]:
    """선형 보간 분위수(q: 0~100)."""
    if not dist:
        return None
    v = sorted(dist)
    pos = (len(v) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def max_drawdown(returns: list[float]) -> float:
    """일별 수익 목록의 최대낙폭(0 이하 소수, 예: -0.12). 시작점(1.0)을 포함한다."""
    peak, mdd = 1.0, 0.0
    for g in _cum_products(returns):
        peak = max(peak, g)
        mdd = min(mdd, g / peak - 1.0)
    return mdd


def classify(n_sessions: int, pctile: Optional[float], live_mdd: Optional[float],
             worst_backtest_mdd: Optional[float]) -> str:
    """사전 고정 규칙으로 판정 키를 돌려준다(VERDICT_LABELS 참고)."""
    if n_sessions < MIN_LIVE_SESSIONS:
        return "insufficient"
    if pctile is None:
        return "unavailable"
    mdd_breach = live_mdd is not None and worst_backtest_mdd is not None and live_mdd < worst_backtest_mdd
    if pctile < DEVIATION_BAND[0] or pctile > DEVIATION_BAND[1] or mdd_breach:
        return "deviation"
    if pctile < NORMAL_BAND[0] or pctile > NORMAL_BAND[1]:
        return "outside"
    return "normal"


def band_label(n_sessions: int, pctile: Optional[float]) -> str:
    """초과수익 분위처럼 낙폭 없이 분위만으로 같은 규칙을 적용한 라벨."""
    return classify(n_sessions, pctile, None, None)


def _sessions_of(closes: dict[str, dict[date, float]], ticker: str) -> list[date]:
    return sorted(closes.get(ticker, {}))


def decision_date(entry: dict) -> date:
    """원장 항목이 계산된 미 동부 날짜. 이 날짜보다 뒤 거래일부터 그 비중을 적용한다."""
    return entry.get("decision_date") or entry["entry_date"]


def governing_entries(entries: list[dict], sessions: list[date]) -> list[tuple[date, Optional[dict]]]:
    """거래일마다 그날 적용되는 원장 항목(계산 날짜 < 거래일 중 가장 최근)."""
    ordered = sorted(entries, key=decision_date)
    out, j, cur = [], 0, None
    for s in sessions:
        while j < len(ordered) and decision_date(ordered[j]) < s:
            cur = ordered[j]
            j += 1
        out.append((s, cur))
    return out


def reconstruct_live_returns(entries: list[dict], closes: dict[str, dict[date, float]], sessions: list[date],
                             core_cost_bps: float = cs.CORE_COST_BPS_PER_SIDE,
                             satellite_cost_bps: float = cs.SATELLITE_COST_BPS_PER_SIDE) -> list[dict]:
    """원장 비중을 완성 종가에 재적용한 거래일별 수익.

    entries: [{"entry_date": date, "decision_date": date(선택), "core_weights": {t: w}, "satellite_weights": {t: w}}]
    closes: {ticker: {date: close}}; sessions: 오름차순 거래일(첫 원소는 전일 종가 기준점으로만 쓴다).
    적용할 원장 항목이 생긴 거래일부터 수익을 만든다. 가격이 없는 종목은 그날 기여 0, missing 에 적는다.
    """
    out: list[dict] = []
    prev_weights: Optional[tuple[dict, dict]] = None
    gov = governing_entries(entries, sessions)
    for i in range(1, len(gov)):
        s, entry = gov[i]
        if entry is None:
            continue
        prev_s = gov[i - 1][0]
        core_w, sat_w = entry.get("core_weights") or {}, entry.get("satellite_weights") or {}
        ret, missing = 0.0, []
        for t, w in {**core_w, **sat_w}.items():
            if not w:
                continue
            c0, c1 = closes.get(t, {}).get(prev_s), closes.get(t, {}).get(s)
            if c0 is None or c1 is None or c0 <= 0:
                missing.append(t)
                continue
            ret += w * (c1 / c0 - 1.0)
        cost = 0.0
        if prev_weights is not None and (core_w, sat_w) != prev_weights:
            for new, old, bps in ((core_w, prev_weights[0], core_cost_bps), (sat_w, prev_weights[1], satellite_cost_bps)):
                turnover = sum(abs(new.get(t, 0.0) - old.get(t, 0.0)) for t in set(new) | set(old))
                cost += turnover * bps / 10000.0
        prev_weights = (core_w, sat_w)
        out.append({"date": s, "entry_date": entry["entry_date"], "return": ret - cost, "cost": cost,
                    "missing": sorted(missing)})
    return out


def _daily_returns(closes: dict[date, float], sessions: list[date]) -> list[Optional[float]]:
    out = []
    for a, b in zip(sessions, sessions[1:]):
        c0, c1 = closes.get(a), closes.get(b)
        out.append(c1 / c0 - 1.0 if c0 and c1 else None)
    return out


def expected_range(backtest: dict, live_start: date, n: int) -> dict:
    """라이브 시작 이전 백테스트 일별 수익으로 길이 n 창의 분포 요약."""
    dates = [date.fromisoformat(d) for d in backtest["dates"]]
    idx = [i for i, d in enumerate(dates) if d < live_start]
    strat = [backtest["strategy"][i] for i in idx]
    spy = [backtest["spy"][i] for i in idx]
    tlt = [backtest["tlt"][i] for i in idx] if backtest.get("tlt") else None
    windows = rolling_window_returns(strat, n) if n > 0 else []
    excess = rolling_window_excess(strat, spy, tlt, n) if n > 0 else {"spy": []}
    return {
        "n_backtest_days": len(strat),
        "backtest_start": dates[idx[0]].isoformat() if idx else None,
        "backtest_end": dates[idx[-1]].isoformat() if idx else None,
        "windows": windows, "excess_spy": excess.get("spy", []), "excess_sixty_forty": excess.get("sixty_forty"),
        "worst_mdd": max_drawdown(strat) if strat else None,
    }


def _pct(x: Optional[float], digits: int = 2) -> Optional[float]:
    return round(x * 100, digits) if x is not None else None


def _dist_summary(dist: Optional[list[float]], x: Optional[float]) -> dict:
    if not dist or len(dist) < MIN_BACKTEST_WINDOWS or x is None:
        return {"percentile": None, "p5": None, "p50": None, "p95": None, "n_windows": len(dist or [])}
    p = percentile_rank(dist, x)
    return {"percentile": round(p, 1), "p1": _pct(quantile(dist, 1)), "p5": _pct(quantile(dist, 5)),
            "p50": _pct(quantile(dist, 50)), "p95": _pct(quantile(dist, 95)), "p99": _pct(quantile(dist, 99)),
            "n_windows": len(dist)}


def _backtest_core_holdings_at(backtest: dict, d: date) -> Optional[set[str]]:
    """백테스트 코어 목표 비중 변경점 중 d 이하 최신의 보유 종목 집합."""
    best = None
    for ds, w in backtest.get("core_holdings", []):
        if date.fromisoformat(ds) <= d:
            best = w
        else:
            break
    return {t for t, v in best.items() if v > 0} if best is not None else None


def evaluate(entries: list[dict], backtest: Optional[dict], closes: dict[str, dict[date, float]],
             last_completed: date, *, paper_tracking: Optional[dict] = None, paper_auto_enabled: bool = False,
             signal_state: Optional[dict] = None, alert_states: Optional[dict] = None,
             today: Optional[date] = None) -> dict[str, Any]:
    """모든 원료를 받아 판정 결과(dict)를 만든다. I/O 없음."""
    today = today or date.today()
    entries = sorted(entries, key=lambda e: e["entry_date"])
    res: dict[str, Any] = {
        "as_of": today.isoformat(), "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
        "rules": {"min_live_sessions": MIN_LIVE_SESSIONS, "normal_band": list(NORMAL_BAND),
                  "deviation_band": list(DEVIATION_BAND), "mdd_rule": "라이브 최대낙폭이 백테스트 최악 낙폭보다 깊으면 이탈",
                  "headline_basis": "절대 누적수익 분위 + 최대낙폭 (초과수익 분위는 표시만)"},
        "limitations": list(LIMITATIONS),
        "n_ledger_entries": len(entries),
    }
    checks: list[dict] = []

    spy_sessions = [s for s in _sessions_of(closes, cs.BENCHMARK_6040_EQUITY_TICKER) if s <= last_completed]
    live_rows: list[dict] = []
    if entries and spy_sessions:
        first = min(decision_date(e) for e in entries)
        cap = max(decision_date(e) for e in entries) + timedelta(days=MAX_WEIGHT_AGE_DAYS)
        base = [s for s in spy_sessions if s <= first][-1:]  # 첫 적용 거래일의 전일 종가 기준점
        window_sessions = base + [s for s in spy_sessions if first < s <= cap]
        live_rows = reconstruct_live_returns(entries, closes, window_sessions)  # 기준점이 없으면 첫 거래일은 건너뛴다
    n = len(live_rows)
    live_rets = [r["return"] for r in live_rows]
    res["live"] = {
        "n_sessions": n,
        "start": live_rows[0]["date"].isoformat() if live_rows else None,
        "end": live_rows[-1]["date"].isoformat() if live_rows else None,
        "cum_return_pct": _pct(compound(live_rets)) if live_rows else None,
        "max_drawdown_pct": _pct(max_drawdown(live_rets)) if live_rows else None,
        "cost_pct": _pct(sum(r["cost"] for r in live_rows)) if live_rows else None,
    }

    # 같은 거래일의 벤치마크(SPY·60/40 매수보유)
    bench: dict[str, Optional[float]] = {"spy_pct": None, "sixty_forty_pct": None}
    if live_rows:
        sess = [s for s in spy_sessions if s <= live_rows[-1]["date"]]
        start_idx = sess.index(live_rows[0]["date"])
        seg = sess[max(start_idx - 1, 0):]
        spy_r = _daily_returns(closes.get(cs.BENCHMARK_6040_EQUITY_TICKER, {}), seg)
        tlt_r = _daily_returns(closes.get(cs.BENCHMARK_6040_BOND_TICKER, {}), seg)
        spy_cum = compound(r for r in spy_r if r is not None) if spy_r else None
        tlt_cum = compound(r for r in tlt_r if r is not None) if tlt_r and all(r is not None for r in tlt_r) else None
        w = cs.BENCHMARK_6040_EQUITY_WEIGHT
        bench = {"spy_pct": _pct(spy_cum),
                 "sixty_forty_pct": _pct(w * spy_cum + (1 - w) * tlt_cum) if spy_cum is not None and tlt_cum is not None else None}
    live_cum = compound(live_rets) if live_rows else None
    res["benchmarks"] = {
        **bench,
        "excess_vs_spy_pct_points": round(res["live"]["cum_return_pct"] - bench["spy_pct"], 2)
        if live_rows and bench["spy_pct"] is not None else None,
        "excess_vs_sixty_forty_pct_points": round(res["live"]["cum_return_pct"] - bench["sixty_forty_pct"], 2)
        if live_rows and bench["sixty_forty_pct"] is not None else None,
    }

    # 기대 범위(라이브 이전 백테스트)
    if backtest and live_rows and n > 0:
        er = expected_range(backtest, live_rows[0]["date"], n)
        ex_spy = res["benchmarks"]["excess_vs_spy_pct_points"]
        ex_64 = res["benchmarks"]["excess_vs_sixty_forty_pct_points"]
        res["expected"] = {
            "backtest_start": er["backtest_start"], "backtest_end": er["backtest_end"],
            "n_backtest_days": er["n_backtest_days"],
            "cum_return": _dist_summary(er["windows"], live_cum),
            "excess_vs_spy": _dist_summary(er["excess_spy"], ex_spy / 100 if ex_spy is not None else None),
            "excess_vs_sixty_forty": _dist_summary(er["excess_sixty_forty"], ex_64 / 100 if ex_64 is not None else None),
            "worst_backtest_mdd_pct": _pct(er["worst_mdd"]),
        }
        pctile = res["expected"]["cum_return"]["percentile"]
        verdict = classify(n, pctile, max_drawdown(live_rets), er["worst_mdd"])
        res["expected"]["excess_vs_spy"]["label"] = VERDICT_LABELS[band_label(n, res["expected"]["excess_vs_spy"]["percentile"])]
        res["expected"]["excess_vs_sixty_forty"]["label"] = VERDICT_LABELS[band_label(n, res["expected"]["excess_vs_sixty_forty"]["percentile"])]
        res["mdd_breach"] = (er["worst_mdd"] is not None and max_drawdown(live_rets) < er["worst_mdd"])
        # 같은 거래일에 백테스트 규칙이 낸 수익(캐시가 그 날짜를 덮는 만큼만)
        bt_map = dict(zip(backtest["dates"], backtest["strategy"]))
        same = [bt_map[r["date"].isoformat()] for r in live_rows if r["date"].isoformat() in bt_map]
        res["same_period_backtest"] = {"n_sessions": len(same), "cum_return_pct": _pct(compound(same)) if same else None}
    else:
        res["expected"] = None
        res["mdd_breach"] = False
        res["same_period_backtest"] = None
        # 라이브 거래일이 없으면 표본 부족, 라이브는 있는데 백테스트가 없으면 판정 불가
        verdict = "unavailable" if live_rows and n >= MIN_LIVE_SESSIONS else "insufficient"
    res["verdict"] = verdict
    res["verdict_label"] = VERDICT_LABELS[verdict]

    # ---- (a) 실행 정합성: paper 계좌 ------------------------------------------------------------------------
    checks.append(_execution_check(paper_tracking, paper_auto_enabled, today))
    # ---- (b) 신호 정합성 -------------------------------------------------------------------------------------
    checks.append(_signal_check(entries, live_rows, backtest, signal_state, spy_sessions))
    # ---- (c) 데이터 결측 -------------------------------------------------------------------------------------
    checks.append(_data_check(entries, live_rows, spy_sessions, today, backtest is not None))
    res["checks"] = checks

    # ---- 기존 알림 상태(읽기만 — 재전송하지 않는다) ------------------------------------------------------------
    alert_states = alert_states or {}
    bm, dc = alert_states.get("benchmark_gap") or {}, alert_states.get("alpha_decay") or {}
    res["existing_alerts"] = {
        "benchmark_gap_active": bool(bm.get("is_lagging")), "benchmark_gap_pct_points": bm.get("gap"),
        "benchmark_gap_as_of": bm.get("as_of"),
        "alpha_decay_active": bool(dc.get("is_decayed")), "alpha_decay_ratio": dc.get("decay_ratio"),
        "alpha_decay_as_of": dc.get("as_of"),
    }
    res["action_needed"] = verdict == "deviation" or any(c["level"] == "warn" for c in checks)
    return res


def _execution_check(pt: Optional[dict], paper_auto_enabled: bool, today: date) -> dict:
    """(a) paper 계좌가 추천을 실제로 따르는지 — 00:46 paper_tracking_refresh 가 남긴 파일만 읽는다(재계산 없음)."""
    c: dict[str, Any] = {"name": "execution", "level": "ok"}
    if not pt or not pt.get("n_snapshots"):
        c.update(level="info", short="paper 기록 없음", summary="paper 계좌 기록 없음 — 실행 점검 생략")
        return c
    following = (pt.get("context") or {}).get("following")
    gap = pt.get("cum_gap_pct_points")
    te = pt.get("tracking_error_annual_pct")
    c.update(following=following, cum_gap_pct_points=gap, tracking_error_annual_pct=te,
             n_intervals=pt.get("n_intervals"), paper_auto_trade_enabled=paper_auto_enabled)
    problems = []
    try:
        gen = datetime.fromisoformat(pt["generated_at"]).date() if pt.get("generated_at") else None
    except ValueError:
        gen = None
    if gen is None or (today - gen).days > PAPER_TRACKING_STALE_DAYS:
        problems.append("추적 파일이 오래됨")
    if following is False:
        if not paper_auto_enabled:
            c.update(level="info", short="paper 자동 주문 꺼짐",
                     summary="paper 자동 주문 꺼짐·포지션 없음 — 실행 점검 해당 없음")
            return c
        problems.append("paper 계좌에 포지션 없음(추천을 따르지 않는 중)")
    if gap is not None and abs(gap) > PAPER_GAP_WARN_PCT_POINTS:
        problems.append(f"원장 대비 괴리 {gap:+.1f}%p")
    if problems:
        c.update(level="warn", short="paper " + ", ".join(problems), summary="실행: " + ", ".join(problems))
        return c
    te_txt = f", 추적오차 {te:.1f}%/년" if te is not None else ""
    c["short"] = f"paper 괴리 {gap:+.1f}%p" if gap is not None else "paper 추종 중"
    c["summary"] = (f"실행: paper 추종 중(괴리 {gap:+.1f}%p{te_txt})" if gap is not None
                    else "실행: paper 추종 중(비교 구간 없음)")
    return c


def _signal_check(entries: list[dict], live_rows: list[dict], backtest: Optional[dict],
                  signal_state: Optional[dict], sessions: list[date]) -> dict:
    """(b) 원장 비중이 그날 추천과 같은가 + 같은 거래일 백테스트 규칙의 코어 종목과 얼마나 다른가."""
    c: dict[str, Any] = {"name": "signal", "level": "ok"}
    # 1) 최신 원장 코어 종목 == 같은 날 00:10 신호 캐시(core_top4). 같은 추천 함수를 2분 간격으로 부른 결과다.
    latest_match = None
    if entries and signal_state and signal_state.get("as_of"):
        last = entries[-1]
        if last["entry_date"].isoformat() == str(signal_state["as_of"]):
            ledger_core = sorted(t for t, w in (last.get("core_weights") or {}).items() if w)
            state_core = sorted(signal_state.get("core_top4") or [])
            latest_match = ledger_core == state_core
            c.update(latest_ledger_core=ledger_core, latest_signal_core=state_core)
    c["latest_matches_signal"] = latest_match
    # 2) 거래일별: 원장 코어 종목 vs 백테스트 규칙(월초 리밸런싱)이 그날 들고 있던 코어 종목
    mismatch, compared = 0, 0
    if backtest and live_rows:
        prev_of = {s: p for p, s in zip(sessions, sessions[1:])}
        by_date = {e["entry_date"]: e for e in entries}
        for r in live_rows:
            p = prev_of.get(r["date"])
            bt = _backtest_core_holdings_at(backtest, p) if p else None
            if bt is None:
                continue
            live = {t for t, w in ((by_date.get(r["entry_date"]) or {}).get("core_weights") or {}).items() if w}
            compared += 1
            mismatch += int(live != bt)
    c.update(backtest_compared_sessions=compared, backtest_mismatch_sessions=mismatch)
    bt_txt = f"백테스트 규칙과 코어 종목 다른 날 {mismatch}/{compared}" if compared else ""
    if latest_match is False:
        c["level"] = "warn"
        head = "최신 원장 비중이 같은 날 추천과 다름"
    elif latest_match is None:
        head = "같은 날 신호 기록 없음"
    else:
        head = "신호 일치"
    c["short"] = head + (f"({bt_txt})" if bt_txt else "")
    c["summary"] = "신호: " + head + (f" · {bt_txt}일(원장은 매일 재계산, 백테스트 코어는 월초 리밸런싱)" if bt_txt else "")
    return c


def _data_check(entries: list[dict], live_rows: list[dict], sessions: list[date], today: date,
                have_backtest: bool) -> dict:
    """(c) 데이터 결측: 원장 빠진 날, 보유 종목 가격 결측, 백테스트 실패, 원장 기록 방식 문제."""
    c: dict[str, Any] = {"name": "data", "level": "ok"}
    problems, notes = [], []
    if not have_backtest:
        problems.append("백테스트 계산 실패")
    if entries:
        have = {e["entry_date"] for e in entries}
        first = entries[0]["entry_date"]
        last_expected = max(entries[-1]["entry_date"], today - timedelta(days=1))  # 원장은 매일(주말 포함) 00:12 기록
        missing = [first + timedelta(days=i) for i in range((last_expected - first).days + 1)
                   if first + timedelta(days=i) not in have]
        recent = [d for d in missing if (today - d).days <= LEDGER_RECENT_GAP_DAYS]
        c.update(ledger_missing_days=len(missing), ledger_recent_missing_days=len(recent),
                 ledger_last_entry=entries[-1]["entry_date"].isoformat())
        if recent:
            problems.append(f"원장 최근 {LEDGER_RECENT_GAP_DAYS}일 중 {len(recent)}일 결측")
        elif missing:
            notes.append(f"원장 과거 결측 {len(missing)}일")
        # 원장 기록 방식: 계산 날짜(ET) x 의 기록은 x 거래일 몫(장중 미완성 봉)이다. x 가 휴장일인데 수익을 적었다면
        # 직전 거래일 수익을 한 번 더 적은 것이다(재구성은 종가로 따로 계산하므로 판정에는 영향 없음).
        if sessions:
            sess = set(sessions)
            dup = [e for e in entries if e.get("realized_return_pct")
                   and sessions[0] <= decision_date(e) <= sessions[-1] and decision_date(e) not in sess]
            c["ledger_non_session_nonzero_days"] = len(dup)
            if dup:
                notes.append(f"원장이 휴장일 몫 수익을 적은 날 {len(dup)}일(재구성에는 영향 없음)")
    price_gaps = [r for r in live_rows if r["missing"]]
    c["price_missing_sessions"] = len(price_gaps)
    if price_gaps:
        problems.append(f"보유 종목 가격 결측 {len(price_gaps)}거래일")
    if live_rows and entries:
        start, end = live_rows[0]["date"], live_rows[-1]["date"]
        # 계산 날짜 x 의 기록이 x 거래일 몫을 적는다 → [start, end] 범위 기록(휴장일 중복 포함)을 그대로 복리로
        recorded = [e["realized_return_pct"] / 100 for e in entries
                    if start <= decision_date(e) <= end and e.get("realized_return_pct") is not None]
        c["ledger_recorded_cum_pct"] = _pct(compound(recorded)) if recorded else None
        c["reconstructed_cum_pct"] = _pct(compound(r["return"] for r in live_rows))
    if problems:
        c["level"] = "warn"
    c["short"] = ", ".join(problems + notes) if (problems or notes) else "결측 없음"
    c["summary"] = "데이터: " + c["short"]
    return c


def format_message(res: dict) -> str:
    """텔레그램 요약 1건(짧게). 결과 dict 에는 키·계좌번호·토큰이 없으므로 문구에 들어갈 수 없다."""
    v = res["verdict"]
    live, exp, bm = res.get("live") or {}, res.get("expected") or {}, res.get("benchmarks") or {}
    lines = [f"{VERDICT_ICONS[v]} 챔피언 주간 검증 ({res['as_of']}): {res['verdict_label']}"]
    n = live.get("n_sessions") or 0
    if n:
        cr = exp.get("cum_return") or {}
        line = f"라이브 {n}거래일 누적 {live['cum_return_pct']:+.2f}%"
        if cr.get("percentile") is not None:
            line += f" = 백테스트 같은 길이 구간의 {cr['percentile']:.0f}분위(5~95분위 {cr['p5']:+.1f}~{cr['p95']:+.1f}%)"
        if v == "insufficient":
            line += f", 판정은 {MIN_LIVE_SESSIONS}거래일부터"
        lines.append(line)
        ex = []
        for key, name, pk in (("excess_vs_spy_pct_points", "SPY", "excess_vs_spy"),
                              ("excess_vs_sixty_forty_pct_points", "60/40", "excess_vs_sixty_forty")):
            if bm.get(key) is not None:
                p = (exp.get(pk) or {}).get("percentile")
                ex.append(f"{name} {bm[key]:+.2f}%p" + (f"({p:.0f}분위)" if p is not None else ""))
        if ex:
            lines.append("대비: " + " · ".join(ex))
        worst = exp.get("worst_backtest_mdd_pct")
        lines.append(f"최대낙폭: 라이브 {live['max_drawdown_pct']:.1f}%"
                     + (f" / 백테스트 최악 {worst:.1f}%" if worst is not None else ""))
    else:
        lines.append(f"비교할 라이브 거래일이 아직 없습니다(원장 {res.get('n_ledger_entries', 0)}건)")
    lines.append("점검: " + " · ".join(c["short"] for c in res.get("checks", [])))
    ea = res.get("existing_alerts") or {}
    active = [name for key, name in (("benchmark_gap_active", "60/40 격차"), ("alpha_decay_active", "알파 감쇠")) if ea.get(key)]
    if active:
        lines.append("기존 알림 발동 중: " + "·".join(active) + "(이미 따로 보냄)")
    lines.append("조치: " + ("필요 — 리포트 파일 확인" if res.get("action_needed") else "필요 없음"))
    lines.append("※ 겹치는 창 분위(독립 표본 아님)·짧은 기간은 판정력 낮음·백테스트 PIT 한계")
    return "\n".join(lines)


# ============================================================================================================
# I/O (캐시·DB·가격·파일) — 스케줄러 잡이 부르는 쪽
# ============================================================================================================

def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def compute_backtest_daily(today: date, lookback_years: int = BACKTEST_LOOKBACK_YEARS,
                           runner: Optional[Callable] = None, price_fetcher: Optional[Callable] = None) -> dict:
    """run_champion_backtest 를 1회 돌려 일별 순수익·SPY/TLT 수익·코어 보유 변경점을 캐시용 dict 로 만든다."""
    runner = runner or cs.run_champion_backtest
    price_fetcher = price_fetcher or cs.get_multiple_price_history
    import pandas as pd

    end = today.isoformat()
    start = (pd.Timestamp(today) - pd.DateOffset(years=lookback_years)).date().isoformat()
    bt = runner(start, end)
    ret = bt["ret_net"].iloc[1:]  # 첫날은 자산곡선 기준점(100)이라 수익으로 쓰지 않는다
    idx = list(ret.index)
    hist = price_fetcher([cs.BENCHMARK_6040_EQUITY_TICKER, cs.BENCHMARK_6040_BOND_TICKER],
                         start=(idx[0] - timedelta(days=10)).date().isoformat() if idx else start, end=None, interval="1d")

    def _bench(ticker: str) -> Optional[list[float]]:
        df = hist.get(ticker)
        if df is None or df.empty:
            return None
        c = df["Close"].reindex(bt["ret_net"].index).ffill()
        return [float(x) for x in c.pct_change().fillna(0.0).iloc[1:]]

    core_w = bt.get("core", {}).get("weights")
    holdings, last = [], None
    if core_w is not None:
        for dt, row in core_w.iterrows():
            w = {t: round(float(v), 6) for t, v in row.items() if v and v > 0}
            if w != last:
                holdings.append([dt.date().isoformat(), w])
                last = w
    spy = _bench(cs.BENCHMARK_6040_EQUITY_TICKER)
    if spy is None:
        raise RuntimeError("SPY 가격이 없어 백테스트 벤치마크를 만들 수 없습니다")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_on": today.isoformat(), "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
        "start": start, "end": end, "satellite_weight_applied": bt.get("satellite_weight_applied"),
        "dates": [d.date().isoformat() for d in idx], "strategy": [float(x) for x in ret],
        "spy": spy, "tlt": _bench(cs.BENCHMARK_6040_BOND_TICKER), "core_holdings": holdings,
        "note": "run_champion_backtest 일별 순수익(비용 반영). PIT 한계는 core/champion_tracking.py 참고.",
    }


def load_or_refresh_backtest(today: date, path: Path = BACKTEST_CACHE_PATH, force: bool = False,
                             **kw) -> Optional[dict]:
    """캐시가 없거나 BACKTEST_CACHE_MAX_AGE_DAYS 보다 오래됐거나 전략 버전이 바뀌면 다시 계산한다.
    계산이 실패하면 낡은 캐시라도 돌려준다(없으면 None)."""
    cached = _read_json(path)
    fresh = (cached and cached.get("strategy_version") == cs.CHAMPION_STRATEGY_VERSION
             and cached.get("generated_on")
             and (today - date.fromisoformat(cached["generated_on"])).days <= BACKTEST_CACHE_MAX_AGE_DAYS)
    if fresh and not force:
        return cached
    try:
        data = compute_backtest_daily(today, **kw)
    except Exception as exc:  # noqa: BLE001
        print(f"[champion_tracking] 백테스트 계산 실패: {type(exc).__name__}: {exc}")
        return cached
    _atomic_write_json(path, data)
    return data


def last_completed_session_cutoff(now_et: Optional[datetime] = None) -> date:
    """완성된 봉만 쓰기 위한 날짜 상한(16:15 ET 이전이면 어제까지)."""
    now_et = now_et or datetime.now(ET)
    d = now_et.date()
    return d if (now_et.hour, now_et.minute) >= US_CLOSE_SETTLED else d - timedelta(days=1)


def _et_date(created_at: Optional[datetime]) -> Optional[date]:
    """naive UTC(created_at 저장 형식) → 미 동부 날짜."""
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(ET).date()


def load_ledger_entries(session=None) -> list[dict]:
    from core.models import ChampionLedgerEntry

    def _run(db) -> list[dict]:
        rows = db.query(ChampionLedgerEntry).order_by(ChampionLedgerEntry.entry_date).all()
        return [{"entry_date": r.entry_date, "decision_date": _et_date(r.created_at),
                 "core_weights": json.loads(r.core_weights or "{}"),
                 "satellite_weights": json.loads(r.satellite_weights or "{}"),
                 "realized_return_pct": r.realized_return_pct, "cumulative_equity": r.cumulative_equity} for r in rows]

    if session is not None:
        return _run(session)
    from core.db import get_session, init_db

    init_db()
    with get_session() as db:
        return _run(db)


def fetch_closes(tickers: list[str], start: date, cutoff: date, price_fetcher: Optional[Callable] = None) -> dict[str, dict[date, float]]:
    price_fetcher = price_fetcher or cs.get_multiple_price_history
    hist = price_fetcher(sorted(set(tickers)), start=start.isoformat(), end=None, interval="1d")
    out: dict[str, dict[date, float]] = {}
    for t, df in (hist or {}).items():
        if df is None or df.empty:
            continue
        out[t] = {ts.date(): float(v) for ts, v in df["Close"].items() if ts.date() <= cutoff and v == v}
    return out


def report_path_for(d: date, report_dir: Path = REPORT_DIR) -> Path:
    return report_dir / f"champion_tracking_{d.isoformat()}.json"


def run_weekly_tracking(notify_fn: Optional[Callable[[str], Any]] = None, *, today: Optional[date] = None,
                        session=None, price_fetcher: Optional[Callable] = None,
                        backtest_runner: Optional[Callable] = None, report_dir: Path = REPORT_DIR,
                        backtest_cache_path: Path = BACKTEST_CACHE_PATH, now_et: Optional[datetime] = None,
                        paper_tracking_path: Path = PAPER_TRACKING_PATH) -> dict:
    """주간 잡 본체: 원료를 모아 판정하고 리포트 JSON 저장 + 텔레그램 1건(같은 날 재실행 시 재전송 없음)."""
    if notify_fn is None:
        from core.telegram_notify import send_message as notify_fn
    from core.process_registry import is_enabled

    today = today or date.today()
    out_path = report_path_for(today, report_dir)
    previous = _read_json(out_path)
    cutoff = last_completed_session_cutoff(now_et)

    entries = load_ledger_entries(session)
    backtest = load_or_refresh_backtest(today, backtest_cache_path, runner=backtest_runner, price_fetcher=price_fetcher)
    closes: dict[str, dict[date, float]] = {}
    if entries:
        tickers = {cs.BENCHMARK_6040_EQUITY_TICKER, cs.BENCHMARK_6040_BOND_TICKER}
        for e in entries:
            tickers.update(e["core_weights"])
            tickers.update(e["satellite_weights"])
        closes = fetch_closes(sorted(tickers), min(decision_date(e) for e in entries) - timedelta(days=10), cutoff,
                              price_fetcher)

    res = evaluate(
        entries, backtest, closes, cutoff,
        paper_tracking=_read_json(paper_tracking_path), paper_auto_enabled=is_enabled("paper_auto_trade"),
        signal_state=_read_json(cs.SIGNAL_STATE_CACHE_PATH),
        alert_states={"benchmark_gap": _read_json(cs.BENCHMARK_STATE_CACHE_PATH),
                      "alpha_decay": _read_json(cs.DECAY_STATE_CACHE_PATH)},
        today=today,
    )
    res["backtest_cache"] = ({"generated_on": backtest.get("generated_on"), "start": backtest.get("start"),
                              "end": backtest.get("end")} if backtest else None)
    res["message"] = format_message(res)
    already = bool(previous and previous.get("notified"))
    res["notified"] = already
    res["notified_now"] = False
    if not already:  # 같은 날 재실행(재시작·수동 실행)이면 다시 보내지 않는다
        sent = notify_fn(res["message"])
        res["notified"] = res["notified_now"] = sent is not False
    res["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _atomic_write_json(out_path, res)
    res["path"] = str(out_path)
    return res
