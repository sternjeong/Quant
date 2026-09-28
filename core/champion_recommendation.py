"""챔피언 전략 '지금 기준 재추천' 한 덩어리 (2026-09-28 추가).

화면(app/pages/11_챔피언_전략.py) 맨 위의 버튼 한 번으로 "지금 무엇을 들고 있어야 하나 / 과거
같은 길이 구간에서 어떤 범위가 나왔나 / 왜 이걸 믿어야 하나 / 지금 바꿀 것이 있나"를 한 화면에
채우기 위한 조합 모듈이다.

**새 계산 로직을 만들지 않는다.** 이미 감사·검증된 함수만 조합한다:
  - 코어 추천: champion_strategy.compute_core_recommendation
  - 새틀라이트 ① 규칙상 지금 보유: champion_strategy.compute_satellite_recommendation_point_in_time
    (내부에서 _pick_satellite_at_date(직전 1·7월 첫 거래일)를 호출)
  - 새틀라이트 ② 오늘이 리밸런싱일이라면: champion_strategy._pick_satellite_at_date(오늘)
    — ①과 **같은 함수, 날짜 인자만 다르다**. ②는 참고용이며 규칙은 항상 ①이다.
  - 분포: champion_tracking 의 rolling_window_returns / rolling_window_excess / quantile /
    max_drawdown / expected_range (주간 추적 판정이 쓰는 그 계산 그대로, 같은 백테스트 캐시)
  - 자산곡선·슬리브 분해: champion_performance 의 캐시(curves)

새로 쓴(= 이 리서치 프로그램이 별도로 감사하지 않은) 부분은 UNVERIFIED_NOTES 에 적어 화면이 그대로
표시한다. 성과·승률이 좋아진다는 주장은 하지 않으며, 숫자가 나쁘면 나쁘게 돌려준다.

주문은 하지 않는다 — 계산·표시 전용이고 주문 경로(scripts/champion_paper_trade.py)를 import 하지
않는다. 무거운 계산(새틀라이트 point-in-time 스캔 2회 + 8년 백테스트 캐시)이라 호출부는
job_manager 로 감싸 백그라운드에서 돌려야 한다. 결과는 data/cache/ 에 배수(초기=1.0) 단위로
저장하므로 금액을 바꿔도 다시 계산하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

import core.champion_strategy as cs
from core import champion_performance as cp
from core import champion_tracking as ct

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_PREFIX = "champion_recommendation_"
REC_SCHEMA_VERSION = 1  # 저장 형식이 바뀌면 올린다(옛 캐시는 키가 달라져 자동으로 무시된다)

HORIZONS = (63, 126)  # 3개월·6개월(거래일) — champion_tracking 이 쓰는 것과 같은 창 길이 관례
HORIZON_LABELS = {63: "3개월(63거래일)", 126: "6개월(126거래일)"}

RESEARCH_JOBS_DIR = PROJECT_ROOT / "research" / "jobs"
RESEARCH_RESULTS_DIR = PROJECT_ROOT / "research" / "results"
SYNTHESIS_REPORT = "docs/reports/research_program_synthesis.html"

# 확신도 표(load_confidence_table)의 component 문자열에서 이 조각을 포함하는 항목을 각 절에 붙인다.
CORE_CONFIDENCE_KEYS = ("코어 자산군", "모멘텀 랭킹 방식", "리밸런싱 주기", "시장필터")
SATELLITE_CONFIDENCE_KEYS = ("새틀라이트 포함", "새틀라이트 선정", "새틀라이트 청산")

DISTRIBUTION_WARNING = (
    "이 범위는 '예상 수익'이 아니라 라이브 시작 전 백테스트에서 같은 길이 구간을 모두 겹쳐 모아 본 "
    "과거 실적 범위입니다. 겹치는 구간이라 독립 표본이 아니고 p-값처럼 읽으면 안 됩니다."
)

LIMITATIONS = (
    "백테스트는 과거 가격에 규칙을 적용한 가상 결과이며 미래 수익을 보장하지 않습니다.",
    "새틀라이트 후보 풀은 현재 S&P500 명단 기반이라 생존편향이 남아 있고, point-in-time 표본추출도 "
    "상장폐지 종목까지 되살리지는 못합니다.",
    "비용은 편도 고정 bp(코어 3bp·새틀라이트 8bp)만 반영하고 세금·슬리피지·배당은 넣지 않았습니다.",
    "코어는 매달·새틀라이트는 반기(1·7월)마다만 바뀌므로, 오늘 계산한 값이 곧 오늘 매매 신호라는 뜻은 아닙니다.",
)

UNVERIFIED_NOTES = (
    "창별 최대낙폭 분포와 'SPY 를 이긴 구간 비율'은 기존 분위 계산(champion_tracking)을 창마다 그대로 "
    "적용해 세어 본 표시값입니다 — 별도 감사를 받은 판정 규칙이 아닙니다.",
    "트레일링스탑 여유(%)는 선정 함수가 내부에서 쓰는 '고점 대비 15% 하락' 규칙을 다시 계산해 보여 주는 "
    "표시값입니다. 백테스트는 반기 사이 중도 청산을 하지 않으므로 이 값이 매도 신호는 아닙니다.",
    "다음 반기 리밸런싱일은 NYSE 휴장일 근사(core/filing_changes.nyse_holidays)로 구한 예정일입니다.",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================================================
# 다음 반기 리밸런싱일 (1월/7월 첫 거래일)
# ============================================================================================

def first_trading_day_of_month(year: int, month: int, trading_days: Optional[frozenset] = None) -> date:
    """그 달의 첫 거래일. 휴장일 판정은 core.filing_changes.is_trading_day(NYSE 휴장일 근사)를 재사용."""
    from core.filing_changes import is_trading_day

    d = date(year, month, 1)
    for _ in range(31):
        if is_trading_day(d, trading_days):
            return d
        d += timedelta(days=1)
    raise ValueError(f"{year}-{month:02d}에 거래일을 찾지 못했습니다")


def satellite_rebalance_days(as_of: date, trading_days: Optional[frozenset] = None) -> list[date]:
    """as_of 주변(작년~내년) 반기 리밸런싱일 목록 — SATELLITE_REBAL_MONTHS 각 달의 첫 거래일."""
    out = [
        first_trading_day_of_month(y, m, trading_days)
        for y in (as_of.year - 1, as_of.year, as_of.year + 1)
        for m in cs.SATELLITE_REBAL_MONTHS
    ]
    return sorted(out)


def next_satellite_rebalance(as_of: date, trading_days: Optional[frozenset] = None) -> dict:
    """as_of 기준 '다음' 반기 리밸런싱일(as_of 제외, 오늘이 리밸런싱일이면 그 다음 것)."""
    days = satellite_rebalance_days(as_of, trading_days)
    later = [d for d in days if d > as_of]
    earlier = [d for d in days if d <= as_of]
    nxt = later[0]
    n_trading = sum(
        1 for i in range((nxt - as_of).days)
        if _is_trading(as_of + timedelta(days=i + 1), trading_days)
    )
    return {
        "next_date": nxt.isoformat(),
        "previous_date": earlier[-1].isoformat() if earlier else None,
        "calendar_days_left": (nxt - as_of).days,
        "trading_days_left": n_trading,
        "is_rebalance_today": as_of in days,
        "calendar": "NYSE 휴장일 근사(core/filing_changes.nyse_holidays) — 확정 거래일력이 아닙니다",
    }


def _is_trading(d: date, trading_days: Optional[frozenset] = None) -> bool:
    from core.filing_changes import is_trading_day

    return is_trading_day(d, trading_days)


# ============================================================================================
# 분포 (champion_tracking 의 계산을 그대로 재사용)
# ============================================================================================

def window_max_drawdowns(returns: list[float], n: int) -> list[float]:
    """길이 n 의 겹치는 창마다 그 창 안의 최대낙폭(0 이하 소수). ct.max_drawdown 을 창마다 적용."""
    if n <= 0 or len(returns) < n:
        return []
    return [ct.max_drawdown(returns[i:i + n]) for i in range(len(returns) - n + 1)]


def dist_stats(values: list[float]) -> dict:
    """분포 요약(소수 그대로: 0.05 = 5%). 분위는 ct.quantile(선형보간)을 그대로 쓴다."""
    if not values:
        return {"n": 0, "p5": None, "p50": None, "p95": None, "worst": None, "best": None,
                "share_positive": None}
    return {
        "n": len(values),
        "p5": ct.quantile(values, 5),
        "p50": ct.quantile(values, 50),
        "p95": ct.quantile(values, 95),
        "worst": min(values),
        "best": max(values),
        "share_positive": sum(1 for v in values if v > 0) / len(values),
    }


def _pre_live_series(backtest: dict, live_start: date) -> tuple[list[date], list[float], list[float], Optional[list[float]]]:
    """라이브 시작 이전(ct.expected_range 와 같은 조건: d < live_start) 백테스트 일별 수익."""
    dates = [date.fromisoformat(d) for d in backtest["dates"]]
    idx = [i for i, d in enumerate(dates) if d < live_start]
    tlt = [backtest["tlt"][i] for i in idx] if backtest.get("tlt") else None
    return ([dates[i] for i in idx], [backtest["strategy"][i] for i in idx],
            [backtest["spy"][i] for i in idx], tlt)


def horizon_distribution(backtest: dict, live_start: date, n: int,
                         min_windows: int = ct.MIN_BACKTEST_WINDOWS) -> dict:
    """길이 n 창의 전략/SPY/초과수익/최대낙폭 분포. ct.expected_range 와 같은 입력·같은 창 만들기."""
    dates, strat, spy, tlt = _pre_live_series(backtest, live_start)
    windows = ct.rolling_window_returns(strat, n)
    spy_windows = ct.rolling_window_returns(spy, n)
    excess = ct.rolling_window_excess(strat, spy, tlt, n) if windows else {"spy": []}
    ex_spy = excess.get("spy") or []
    mdds = window_max_drawdowns(strat, n)

    worst_window = None
    if windows:
        i = min(range(len(windows)), key=lambda k: windows[k])
        worst_window = {"return": windows[i], "start": dates[i].isoformat(), "end": dates[i + n - 1].isoformat()}

    return {
        "horizon_days": n,
        "label": HORIZON_LABELS.get(n, f"{n}거래일"),
        "n_windows": len(windows),
        "enough_windows": len(windows) >= min_windows,
        "backtest_start": dates[0].isoformat() if dates else None,
        "backtest_end": dates[-1].isoformat() if dates else None,
        "strategy": dist_stats(windows),
        "spy": dist_stats(spy_windows),
        "excess_spy": dist_stats(ex_spy),
        "excess_sixty_forty": dist_stats(excess.get("sixty_forty") or []) if excess.get("sixty_forty") else None,
        "max_drawdown": dist_stats(mdds),
        "beat_spy_share": (sum(1 for v in ex_spy if v > 0) / len(ex_spy)) if ex_spy else None,
        "excess_spy_values": [round(float(v), 6) for v in ex_spy],
        "worst_window": worst_window,
    }


def sleeve_excess_distributions(perf: Optional[dict], horizons: tuple[int, ...] = HORIZONS) -> Optional[dict]:
    """새틀라이트 슬리브 **단독**의 SPY 대비 초과수익 분포 — champion_performance 캐시의 자산곡선 사용.

    성과 캐시가 없으면 None(모르는 것을 안다고 표시하지 않는다).
    """
    curves = (perf or {}).get("curves") or {}
    if not curves.get("satellite") or not curves.get("spy"):
        return None
    sat = cp.series_from_json(curves["satellite"])
    spy = cp.series_from_json(curves["spy"])
    if sat.empty or spy.empty:
        return None
    sat, spy = sat.align(spy, join="inner")
    sr = [float(v) for v in sat.pct_change().dropna()]
    br = [float(v) for v in spy.pct_change().dropna()]
    by_horizon = {}
    for n in horizons:
        ex = ct.rolling_window_excess(sr, br, None, n)["spy"] if len(sr) >= n else []
        by_horizon[str(n)] = {
            **dist_stats(ex),
            "label": HORIZON_LABELS.get(n, f"{n}거래일"),
            "beat_spy_share": (sum(1 for v in ex if v > 0) / len(ex)) if ex else None,
            "values": [round(float(v), 6) for v in ex],
        }
    return {
        "source_params": (perf or {}).get("params"),
        "computed_at": (perf or {}).get("computed_at"),
        "by_horizon": by_horizon,
    }


def equity_curves(backtest: Optional[dict], perf: Optional[dict] = None) -> Optional[dict]:
    """차트용 배수(시작=1.0) 자산곡선. 성과 캐시가 있으면 그것(코어·새틀라이트 포함), 없으면
    추적 백테스트 캐시의 일별 수익을 누적해 만든다(ct._cum_products 재사용)."""
    curves = (perf or {}).get("curves") or {}
    if curves.get("strategy") and curves.get("spy"):
        base = cp.series_from_json(curves["strategy"])
        if not base.empty:
            out = {"source": "champion_performance 캐시",
                   "dates": [d.date().isoformat() for d in base.index]}
            for key in ("strategy", "spy", "core", "satellite", "sixty_forty"):
                if not curves.get(key):
                    continue
                s = cp.series_from_json(curves[key]).reindex(base.index).ffill()
                if s.isna().all():
                    continue
                out[key] = [None if pd.isna(v) else round(float(v), 6) for v in s]
            return out
    if not backtest:
        return None
    dates = backtest["dates"]
    out = {"source": "champion_tracking 백테스트 캐시", "dates": list(dates)}
    for key, series in (("strategy", backtest.get("strategy")), ("spy", backtest.get("spy"))):
        if not series:
            continue
        out[key] = [round(float(v), 6) for v in ct._cum_products(series)[1:]]
    return out if out.get("strategy") else None


# ============================================================================================
# 근거 (종목별)
# ============================================================================================

def core_evidence(core_result: dict) -> list[dict]:
    """코어 17자산의 모멘텀 값·순위·top4 여부·비중 — compute_core_recommendation 결과를 옮길 뿐이다."""
    ranked = core_result.get("ranked")
    if ranked is None or len(ranked) == 0:
        return []
    weights = core_result.get("per_ticker_weights") or {}
    rows = []
    for rank, (_, r) in enumerate(ranked.iterrows(), start=1):
        mom = r.get("momentum_pct")
        rows.append({
            "ticker": r["ticker"],
            "rank": rank,
            "momentum_12m_pct": None if pd.isna(mom) else float(mom),
            "passes_absolute_momentum": bool(r.get("passes_absolute_momentum")),
            "in_top4": bool(r.get("in_top4")),
            "last_close": None if pd.isna(r.get("last_close")) else float(r.get("last_close")),
            "weight_pct": round(float(weights.get(r["ticker"], 0.0)) * 100, 2),
        })
    return rows


def _sector_map() -> dict[str, str]:
    """종목→GICS 섹터(표시 전용). 실패하면 빈 dict — 섹터는 없어도 추천에 영향이 없다."""
    try:
        from core import screener

        universe = screener.get_universe(use_cache=True)
        return {str(s): str(sec) for s, sec in zip(universe["Symbol"], universe["Sector"])}
    except Exception:  # noqa: BLE001 - 표시 전용 부가정보
        return {}


def satellite_evidence(picks: list[str], rebal_date: str, as_of: date, *,
                       candidates: Optional[list[dict]] = None,
                       price_fn: Optional[Callable] = None,
                       sector_map: Optional[dict[str, str]] = None) -> list[dict]:
    """새틀라이트 선정 종목별 근거: 돌파 발생일, 12개월 모멘텀과 후보 중 순위, 현재가와
    트레일링스탑 사이 여유(%), 섹터.

    돌파/스탑 판정은 선정에 쓰인 그 함수(cs.donchian_trailing_stop_positions)를 그대로 다시 돌린다.
    모멘텀·순위는 선정 결과(candidates)에서 그대로 옮긴다(재계산하지 않음).
    """
    if not picks:
        return []
    price_fn = price_fn or cs.get_multiple_price_history
    sector_map = sector_map if sector_map is not None else _sector_map()
    cand_by_ticker = {c["ticker"]: c for c in (candidates or [])}

    start = (pd.Timestamp(rebal_date) - pd.DateOffset(days=cs.SATELLITE_BACKTEST_WARMUP_DAYS)).date().isoformat()
    histories = price_fn(list(picks), start=start, end=as_of.isoformat(), interval="1d") or {}

    rows = []
    for t in picks:
        cand = cand_by_ticker.get(t, {})
        row = {
            "ticker": t,
            "sector": sector_map.get(t),
            "momentum_12m_pct": (round(float(cand["momentum_12m"]) * 100, 2)
                                 if cand.get("momentum_12m") is not None else None),
            "rank_among_breakouts": cand.get("rank"),
            "breakout_date": None,
            "current_price": None,
            "trailing_stop": None,
            "stop_headroom_pct": None,
            "trend_active": None,
        }
        df = histories.get(t)
        if df is not None and not df.empty:
            close = df["Close"].dropna()
            if len(close) > cs.SATELLITE_DONCHIAN_WINDOW:
                pos = cs.donchian_trailing_stop_positions(close)
                active = bool(pos.iloc[-1] == 1)
                row["trend_active"] = active
                runs = pos[pos == 1]
                entry_idx = None
                if len(runs) > 0:
                    # 현재(또는 마지막) 보유 구간의 시작 = 직전 0 다음 1
                    last_one = pos.index.get_loc(runs.index[-1])
                    i = last_one
                    while i > 0 and pos.iloc[i - 1] == 1:
                        i -= 1
                    entry_idx = i
                    row["breakout_date"] = pos.index[i].date().isoformat()
                row["current_price"] = round(float(close.iloc[-1]), 2)
                if active and entry_idx is not None:
                    peak = float(close.iloc[entry_idx:].max())
                    stop = peak * (1 - cs.SATELLITE_DONCHIAN_STOP_PCT)
                    row["trailing_stop"] = round(stop, 2)
                    row["stop_headroom_pct"] = round((float(close.iloc[-1]) / stop - 1) * 100, 2) if stop else None
        rows.append(row)
    return rows


def confidence_for(keys: tuple[str, ...], table: Optional[list[dict]] = None) -> list[dict]:
    """확신도 표에서 component 에 keys 조각이 들어간 항목만 고른다(등급을 바꾸지 않는다)."""
    table = table if table is not None else cs.load_confidence_table()
    return [r for r in table if any(k in r.get("component", "") for k in keys)]


def research_status(jobs_dir: Optional[Path] = None, results_dir: Optional[Path] = None) -> list[dict]:
    """등록된 검증 연구(research/jobs/*/job.json)와 그 판정(research/results/<id>/results.json).

    결과가 없으면 status='진행 중'. 판정은 결과 파일의 verdicts 를 그대로 옮긴다(해석하지 않음).
    """
    jobs_dir = Path(jobs_dir or RESEARCH_JOBS_DIR)
    results_dir = Path(results_dir or RESEARCH_RESULTS_DIR)
    out = []
    if not jobs_dir.exists():
        return out
    for job_file in sorted(jobs_dir.glob("*/job.json")):
        try:
            with open(job_file, encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, ValueError):
            continue
        job_id = job.get("id") or job_file.parent.name
        row = {"id": job_id, "title": job.get("title") or job_id, "status": "진행 중", "verdicts": None,
               "generated_at": None}
        res_file = results_dir / job_id / "results.json"
        if res_file.exists():
            try:
                with open(res_file, encoding="utf-8") as f:
                    res = json.load(f)
                verdicts = res.get("verdicts")
                row["status"] = "결과 있음" if verdicts else "결과 파일 있음(판정 없음)"
                row["verdicts"] = verdicts
                row["generated_at"] = res.get("generated_at")
            except (OSError, ValueError):
                row["status"] = "결과 파일을 읽지 못함"
        out.append(row)
    return out


# ============================================================================================
# 새틀라이트 ①/② 차이 문구 + 행동 결론
# ============================================================================================

def satellite_diff_note(rule_picks: list[str], today_picks: list[str], next_rebal: dict) -> str:
    """규칙상 보유(①)와 오늘 새로 뽑았을 때(②)의 차이를 한 줄로. ②는 참고용이라고 못박는다."""
    nxt = next_rebal.get("next_date")
    tail = (f"반기 규칙이라 다음 리밸런싱일 {nxt}(약 {next_rebal.get('trading_days_left')}거래일 뒤)까지 "
            "바꾸지 않습니다. ②는 참고용입니다.")
    rule_s = "·".join(rule_picks) if rule_picks else "없음(현금)"
    today_s = "·".join(today_picks) if today_picks else "없음(현금)"
    if list(rule_picks) == list(today_picks):
        return f"규칙 보유와 오늘 새로 뽑은 결과가 같습니다({rule_s}). {tail}"
    return f"규칙은 {rule_s} 보유, 오늘 새로 뽑으면 {today_s} — {tail}"


ACTION_NO_CHANGE = "바꿀 것 없음"
ACTION_NO_BASELINE = "비교 기준 없음"
ACTION_HOLD_ORDERS = "신규 주문 보류"


def _swap_text(label: str, before: list[str], after: list[str]) -> Optional[str]:
    """'코어 1개 교체 필요(A→B)' 같은 문구. 바뀐 것이 없으면 None."""
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    if not removed and not added:
        return None
    pairs = [f"{a}→{b}" for a, b in zip(removed, added)]
    leftover_sell = removed[len(pairs):]
    leftover_buy = added[len(pairs):]
    parts = list(pairs)
    parts += [f"{t} 매도" for t in leftover_sell]
    parts += [f"{t} 매수" for t in leftover_buy]
    n = max(len(removed), len(added))
    return f"{label} {n}개 교체 필요({', '.join(parts)})"


def action_summary(*, core: dict, rule_picks: list[str], next_rebal: dict,
                   previous: Optional[dict] = None,
                   stop_rows: Optional[list[dict]] = None) -> dict:
    """'지금 실제로 바꿀 것이 있는가' 한 줄 + 항목. 주문하지 않는다(문구만 만든다).

    previous: champion_strategy.get_current_holdings() 형식({"core_top4", "satellite_selected", "as_of"}).
        None 이면 비교 기준이 없다고 밝힌다(바꿀 것 없음이라고 단정하지 않는다).
    """
    items: list[dict] = []
    top4 = list(core.get("top4") or [])
    if core.get("market_filter_status") == "unknown":
        items.append({"kind": "hold", "text": f"{ACTION_HOLD_ORDERS} — {core.get('allocation_reason')}"})

    breached = [r["ticker"] for r in (stop_rows or []) if r.get("trend_active") is False]
    if breached:
        items.append({
            "kind": "note",
            "text": (f"참고: {', '.join(breached)} 은(는) 지금 트레일링스탑(고점 대비 "
                     f"{cs.SATELLITE_DONCHIAN_STOP_PCT:.0%}) 아래입니다. 백테스트는 반기 사이 중도 청산을 "
                     "하지 않으므로 규칙상 매도 신호가 아니라 경고입니다."),
        })

    if previous is None:
        headline = (f"{ACTION_NO_BASELINE} — 어제 상태 캐시(champion_signal_state.json)가 없어 무엇이 바뀌는지 "
                    f"비교하지 못했습니다. 지금 추천: 코어 {', '.join(top4) or '없음'} / 새틀라이트 "
                    f"{', '.join(rule_picks) or '없음(현금)'}")
        return {"headline": headline, "items": items, "has_changes": None, "places_orders": False,
                "compared_with": None}

    core_text = _swap_text("코어", list(previous.get("core_top4") or []), top4)
    sat_text = _swap_text("새틀라이트", list(previous.get("satellite_selected") or []), rule_picks)
    changes = [t for t in (core_text, sat_text) if t]
    if changes:
        headline = " · ".join(changes)
        items = [{"kind": "change", "text": t} for t in changes] + items
    else:
        headline = (f"{ACTION_NO_CHANGE} — 다음 새틀라이트 리밸런싱 {next_rebal.get('next_date')}"
                    f"(약 {next_rebal.get('trading_days_left')}거래일 뒤). 코어는 매달 첫 거래일에 다시 봅니다.")
    return {"headline": headline, "items": items, "has_changes": bool(changes), "places_orders": False,
            "compared_with": previous.get("as_of")}


# ============================================================================================
# 캐시
# ============================================================================================

def cache_params(as_of: date | str, sizing_method: str = "equal",
                 satellite_weight: float = cs.SATELLITE_WEIGHT) -> dict:
    return {
        "as_of": str(as_of),
        "sizing_method": str(sizing_method),
        "satellite_weight": round(float(satellite_weight), 4),
        "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
        "schema": REC_SCHEMA_VERSION,
        "horizons": list(HORIZONS),
        "cost_core_bps": cs.CORE_COST_BPS_PER_SIDE,
        "cost_satellite_bps": cs.SATELLITE_COST_BPS_PER_SIDE,
    }


def cache_key(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cache_path(params: dict, cache_dir: Optional[Path] = None) -> Path:
    return Path(cache_dir or CACHE_DIR) / f"{CACHE_PREFIX}{cache_key(params)}.json"


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def load_cached(params: dict, cache_dir: Optional[Path] = None) -> Optional[dict]:
    path = cache_path(params, cache_dir)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if data.get("params") == params else None


def list_cached(cache_dir: Optional[Path] = None) -> list[dict]:
    """저장된 재추천 캐시 목록(최근 계산 순). 전략 버전·스키마가 지금과 다른 것은 제외한다."""
    out = []
    for p in Path(cache_dir or CACHE_DIR).glob(f"{CACHE_PREFIX}*.json"):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        params = data.get("params") or {}
        if params.get("schema") != REC_SCHEMA_VERSION:
            continue
        if params.get("strategy_version") != cs.CHAMPION_STRATEGY_VERSION:
            continue
        out.append({"params": params, "computed_at": data.get("computed_at"), "path": str(p)})
    return sorted(out, key=lambda r: r.get("computed_at") or "", reverse=True)


def load_latest_cached(cache_dir: Optional[Path] = None) -> Optional[dict]:
    """가장 최근 재추천 결과(전략 버전이 바뀌면 옛 결과는 쓰지 않는다). 계산하지 않는다."""
    for row in list_cached(cache_dir):
        try:
            with open(row["path"], encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def days_ago(result: Optional[dict], today: Optional[date] = None) -> Optional[int]:
    """결과의 기준일(as_of)이 며칠 전인지."""
    if not result:
        return None
    as_of = (result.get("params") or {}).get("as_of")
    if not as_of:
        return None
    try:
        return ((today or date.today()) - date.fromisoformat(str(as_of))).days
    except ValueError:
        return None


# ============================================================================================
# 전체 계산
# ============================================================================================

def _live_start(as_of: date, ledger_loader: Optional[Callable] = None) -> tuple[date, Optional[str]]:
    """라이브 시작일 = 챔피언 원장 첫 항목. 없으면 as_of 다음 날(= 백테스트 전체를 분포에 씀)."""
    loader = ledger_loader or ct.load_ledger_entries
    try:
        entries = loader() or []
    except Exception:  # noqa: BLE001 - DB 없는 환경에서도 분포는 보여 준다
        entries = []
    dates = [e.get("entry_date") for e in entries if e.get("entry_date")]
    if dates:
        d = min(dates)
        return (d if isinstance(d, date) else date.fromisoformat(str(d))), "챔피언 원장 첫 항목"
    return as_of + timedelta(days=1), "원장 없음 — 백테스트 전체 구간을 씀"


def compute_recommendation(
    as_of: Optional[date] = None,
    *,
    sizing_method: str = "equal",
    satellite_weight: float = cs.SATELLITE_WEIGHT,
    use_cache: bool = True,
    cache_dir: Optional[Path] = None,
    core_fn: Optional[Callable] = None,
    satellite_rule_fn: Optional[Callable] = None,
    satellite_today_fn: Optional[Callable] = None,
    backtest_loader: Optional[Callable] = None,
    perf_loader: Optional[Callable] = None,
    holdings_fn: Optional[Callable] = None,
    ledger_loader: Optional[Callable] = None,
    price_fn: Optional[Callable] = None,
    sector_map: Optional[dict[str, str]] = None,
    confidence_table: Optional[list[dict]] = None,
) -> dict:
    """버튼 한 번에 채워지는 네 칸을 한 번에 계산해 캐시에 저장한다(JSON 직렬화 가능한 dict).

    느리다(새틀라이트 point-in-time 스캔 2회 + 필요시 8년 백테스트) — job_manager 로 감싸 부른다.
    모든 외부 계산은 인자로 바꿔 끼울 수 있다(테스트는 네트워크 없이 여기를 검증한다).
    """
    as_of = as_of or date.today()
    params = cache_params(as_of, sizing_method, satellite_weight)
    if use_cache:
        cached = load_cached(params, cache_dir)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    core_fn = core_fn or cs.compute_core_recommendation
    satellite_rule_fn = satellite_rule_fn or cs.compute_satellite_recommendation_point_in_time
    satellite_today_fn = satellite_today_fn or cs._pick_satellite_at_date
    backtest_loader = backtest_loader or ct.load_or_refresh_backtest
    perf_loader = perf_loader or (lambda: cp.load_latest_cached(satellite_weight=satellite_weight))
    holdings_fn = holdings_fn or cs.get_current_holdings

    # --- (1) 지금 무엇을 들고 있어야 하나 -----------------------------------------------
    core = core_fn(sizing_method=sizing_method)

    # ① 규칙대로 지금 보유해야 하는 종목: 직전 반기 리밸런싱일 기준(as_of 는 '지금')
    rule = satellite_rule_fn(as_of_date=as_of.isoformat(), sizing_method=sizing_method)
    rule_picks = list(rule.get("selected") or [])

    # ② 오늘이 리밸런싱일이라면 뽑힐 종목 — ①과 같은 함수, 날짜 인자만 오늘로 바꾼다(참고용)
    today_info = satellite_today_fn(pd.Timestamp(as_of), sizing_method=sizing_method)
    today_picks = list(today_info.get("picks") or [])

    next_rebal = next_satellite_rebalance(as_of)

    rule_candidates = rule.get("candidates")
    rule_candidates = (rule_candidates.to_dict("records")
                       if isinstance(rule_candidates, pd.DataFrame) else list(rule_candidates or []))
    today_candidates = [
        {"ticker": t, "momentum_12m": score, "rank": i, "selected": t in set(today_picks)}
        for i, (t, score) in enumerate(today_info.get("ranked_active") or [], start=1)
    ]
    rule_picks_table = rule.get("picks")
    rule_picks_table = (rule_picks_table.to_dict("records")
                        if isinstance(rule_picks_table, pd.DataFrame) else list(rule_picks_table or []))

    evidence_rows = satellite_evidence(
        rule_picks, rule.get("rebal_date") or as_of.isoformat(), as_of,
        candidates=rule_candidates, price_fn=price_fn, sector_map=sector_map,
    )

    satellite_block = {
        "rule": {
            "picks": rule_picks,
            "rebal_date": rule.get("rebal_date"),
            "per_ticker_weights": rule.get("per_ticker_weights") or {},
            "unallocated_weight": rule.get("unallocated_weight"),
            "new_orders_allowed": rule.get("new_orders_allowed"),
            "allocation_reason": rule.get("allocation_reason"),
            "pool_size": rule.get("pool_size"),
            "n_active_trend": rule.get("n_active_trend"),
            "picks_table": rule_picks_table,
            "candidates": rule_candidates,
        },
        "today_if_rebalance": {
            "as_of": as_of.isoformat(),
            "picks": today_picks,
            "sleeve_weights": today_info.get("weights") or {},
            "pool_size": today_info.get("pool_size"),
            "n_active_trend": today_info.get("n_active_trend"),
            "candidates": today_candidates,
            "is_reference_only": True,
        },
        "diff_note": satellite_diff_note(rule_picks, today_picks, next_rebal),
        "same_picks": list(rule_picks) == list(today_picks),
        "next_rebalance": next_rebal,
        "evidence": evidence_rows,
    }

    # --- (2) 기대 수익·변동: 점추정 없이 분포로 -----------------------------------------
    backtest = None
    try:
        backtest = backtest_loader(as_of)
    except Exception as exc:  # noqa: BLE001 - 분포가 없어도 (1)(3)(4)는 보여 준다
        backtest_error = f"{type(exc).__name__}: {exc}"
    else:
        backtest_error = None
    live_start, live_start_note = _live_start(as_of, ledger_loader)
    perf = None
    try:
        perf = perf_loader()
    except Exception:  # noqa: BLE001
        perf = None

    by_horizon = {}
    if backtest:
        for n in HORIZONS:
            by_horizon[str(n)] = horizon_distribution(backtest, live_start, n)
    distributions = {
        "available": bool(by_horizon),
        "error": backtest_error,
        "live_start": live_start.isoformat(),
        "live_start_note": live_start_note,
        "backtest_generated_on": (backtest or {}).get("generated_on"),
        "backtest_start": (backtest or {}).get("start"),
        "backtest_end": (backtest or {}).get("end"),
        "satellite_weight_applied": (backtest or {}).get("satellite_weight_applied"),
        "by_horizon": by_horizon,
        "satellite_sleeve": sleeve_excess_distributions(perf),
        "curves": equity_curves(backtest, perf),
        "warning": DISTRIBUTION_WARNING,
    }

    # --- (3) 왜 이걸 믿어야 하나 ----------------------------------------------------------
    table = confidence_table if confidence_table is not None else cs.load_confidence_table()
    references = {
        "core_confidence": confidence_for(CORE_CONFIDENCE_KEYS, table),
        "satellite_confidence": confidence_for(SATELLITE_CONFIDENCE_KEYS, table),
        "rejected_ideas": cs.load_rejected_ideas(),
        "synthesis_report": SYNTHESIS_REPORT,
        "research_jobs": research_status(),
        "research_note": (
            "새틀라이트 시의성·선정 방식의 약점 검증 연구는 VM 연구 실행기(research/jobs, "
            "docs/RESEARCH_JOBS.md)에서 진행됩니다 — 결과에 따라 아래 규칙이 바뀔 수 있습니다."
        ),
    }

    # --- (4) 지금 해야 할 행동 ------------------------------------------------------------
    try:
        previous = holdings_fn()
    except Exception:  # noqa: BLE001
        previous = None
    action = action_summary(core=core, rule_picks=rule_picks, next_rebal=next_rebal,
                            previous=previous, stop_rows=evidence_rows)

    result = {
        "params": params,
        "computed_at": _now_iso(),
        "as_of": as_of.isoformat(),
        "core": {
            "top4": list(core.get("top4") or []),
            "per_ticker_weights": core.get("per_ticker_weights") or {},
            "exposure_multiplier": core.get("exposure_multiplier"),
            "invested_weight_pct": round(float(core.get("exposure_multiplier") or 0.0) * cs.CORE_WEIGHT * 100, 2),
            "cash_weight_from_filter": core.get("cash_weight_from_filter"),
            "market_filter_status": core.get("market_filter_status"),
            "above_200dma": core.get("above_200dma"),
            "spy_price": core.get("spy_price"),
            "spy_sma200": core.get("spy_sma200"),
            "new_orders_allowed": core.get("new_orders_allowed"),
            "allocation_reason": core.get("allocation_reason"),
            "last_trading_date": core.get("last_trading_date"),
            "evidence": core_evidence(core),
        },
        "satellite": satellite_block,
        "distributions": distributions,
        "references": references,
        "action": action,
        "limitations": list(LIMITATIONS),
        "unverified_notes": list(UNVERIFIED_NOTES),
        "from_cache": False,
    }
    if use_cache:
        _atomic_write_json(cache_path(params, cache_dir), result)
    return result


# ============================================================================================
# 표시 보조 (화면이 그대로 쓰는 문자열 만들기 — 계산 없음)
# ============================================================================================

def fmt_pct(v: Optional[float], digits: int = 1, signed: bool = True) -> str:
    """소수(0.0512) → '+5.1%'. None 이면 '—'."""
    if v is None:
        return "—"
    return f"{v * 100:+.{digits}f}%" if signed else f"{v * 100:.{digits}f}%"


def fmt_range(stats: dict, digits: int = 1) -> str:
    """'중앙값 +4.2% (5~95백분위 -6.1% ~ +15.0%)'."""
    return (f"중앙값 {fmt_pct(stats.get('p50'), digits)} "
            f"(5~95백분위 {fmt_pct(stats.get('p5'), digits)} ~ {fmt_pct(stats.get('p95'), digits)})")
