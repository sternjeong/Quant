"""챔피언 전략 '지금 기준 재추천' 한 덩어리 (2026-09-28 추가).

화면(app/pages/11_챔피언_전략.py) 맨 위의 버튼 한 번으로 "지금 무엇을 들고 있어야 하나 / 과거
같은 길이 구간에서 어떤 범위가 나왔나 / 왜 이걸 믿어야 하나 / 지금 바꿀 것이 있나"를 한 화면에
채우기 위한 조합 모듈이다.

**새 계산 로직을 만들지 않는다.** 이미 감사·검증된 함수만 조합한다:
  - 코어 추천: champion_strategy.compute_core_recommendation
  - 새틀라이트 **주 추천(오늘자 재선정)**: champion_strategy._pick_satellite_at_date(오늘)
  - 새틀라이트 **참고(직전 반기일에 매수했다면 지금 보유 중일 종목)**:
    champion_strategy.compute_satellite_recommendation_point_in_time
    (내부에서 _pick_satellite_at_date(직전 1·7월 첫 거래일)를 호출)

둘은 **같은 함수이고 날짜 인자만 다르다.** 규칙의 내용은 "1월·7월이라는 날짜에 사라"가 아니라 "이
선정 절차로 뽑아서 6개월 보유하라"이고, 1월·7월은 반기 주기의 위상을 정하려고 고른 시작점일 뿐
그 두 날짜가 특별하다고 이 리서치 프로그램이 밝힌 바 없다. 따라서 **아직 아무것도 보유하지 않은
사람에게는 오늘자 재선정이 규칙을 벗어나는 일이 아니라 같은 규칙을 오늘 적용하는 것**이고, 직전
반기일 목록은 그때 실제로 매수한 경우에만 의미가 있다. 그래서 오늘자를 주 추천으로 두고 직전
반기일 목록은 참고로 내린다(2026-09-28 사용자 지적으로 순서를 바로잡았다).
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
    "코어는 매달 첫 거래일에 바뀌고, 새틀라이트는 뽑은 날부터 6개월 보유가 원칙입니다 — 오늘 계산한 값이 "
    "곧 '지금 당장 사고팔아라'라는 뜻은 아닙니다.",
)

UNVERIFIED_NOTES = (
    "창별 최대낙폭 분포와 'SPY 를 이긴 구간 비율'은 기존 분위 계산(champion_tracking)을 창마다 그대로 "
    "적용해 세어 본 표시값입니다 — 별도 감사를 받은 판정 규칙이 아닙니다.",
    "트레일링스탑 여유(%)는 선정 함수가 내부에서 쓰는 '고점 대비 15% 하락' 규칙을 다시 계산해 보여 주는 "
    "표시값입니다. 백테스트는 반기 사이 중도 청산을 하지 않으므로 이 값이 매도 신호는 아닙니다.",
    "다음 반기 리밸런싱일은 NYSE 휴장일 근사(core/filing_changes.nyse_holidays)로 구한 예정일입니다.",
    "오늘 매수할 경우의 다음 재선정일은 '매수일 + 6개월'로 계산한 값입니다(반기 주기는 그대로이고 위상만 "
    "매수일에 맞춥니다). 백테스트는 1월·7월 위상으로만 측정했으므로 이 위상 자체는 측정된 값이 아닙니다.",
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

def next_reselection_after_purchase(buy_date: date, months: int = 6) -> dict:
    """보유 시작일 기준 다음 재선정일(= 매수일 + 6개월). 반기 주기는 그대로, 위상만 매수일에 맞춘다.

    1월·7월 첫 거래일은 반기 주기의 위상을 정하려고 고른 시작점일 뿐이므로(모듈 docstring 참고),
    오늘 매수하는 사람의 다음 재선정일은 달력상 1월이 아니라 '매수일 + 6개월'이다. 말일 매수는
    pd.DateOffset 이 그 달 말일로 클램프한다(2026-08-31 → 2027-02-28, 2027-08-31 → 2028-02-29).
    raw_date 는 그 달력 날짜, date 는 휴장일이면 다음 거래일로 민 날짜다.
    """
    raw = (pd.Timestamp(buy_date) + pd.DateOffset(months=months)).date()
    adjusted = raw
    for _ in range(10):
        if _is_trading(adjusted):
            break
        adjusted += timedelta(days=1)
    return {
        "bought": buy_date.isoformat(),
        "raw_date": raw.isoformat(),
        "date": adjusted.isoformat(),
        "months": months,
        "basis": "보유 시작일 + 6개월(반기 주기 유지, 위상만 매수일 기준)",
    }


# 시작 날짜(위상)에 대한 정직한 표시 — 기다리라거나 지금 사라고 권하지 않는다.
TIMING_NOTE = (
    "이 백테스트가 실제로 측정한 것은 1월·7월에 시작한 구간들입니다. 시작 날짜를 언제로 잡느냐가 결과를 "
    "얼마나 흔드는지는 아직 측정되지 않았습니다(시차 분할 검증 연구가 진행 중입니다). "
    "다만 이것이 '1월까지 기다려라'의 근거는 아닙니다 — 1월 2일도 똑같이 측정되지 않은 시작 날짜 하나이고, "
    "기다리는 동안 이 몫을 현금으로 비워두는 선택이 따라옵니다. "
    "어느 쪽이 낫다는 증거가 없으므로 이 화면은 어느 쪽도 권하지 않습니다."
)


def satellite_diff_note(rule_picks: list[str], today_picks: list[str], next_rebal: dict) -> str:
    """오늘자 재선정(주 추천)과 '직전 반기일에 매수했다면 지금 보유 중일 종목'의 차이를 한 줄로.

    선정 절차는 날짜 인자만 다른 같은 함수이므로 오늘자가 규칙을 벗어난 것이 아니다(모듈 docstring
    참고). 직전 반기일 목록은 그때 실제로 매수한 경우에만 의미가 있다고 문구에 명시한다.
    """
    prev = next_rebal.get("previous_date") or "직전 반기 리밸런싱일"
    rule_s = "·".join(rule_picks) if rule_picks else "없음(현금)"
    today_s = "·".join(today_picks) if today_picks else "없음(현금)"
    if list(rule_picks) == list(today_picks):
        return f"오늘 다시 뽑은 결과는 {today_s} 이고, {prev}에 매수했다면 지금 들고 있을 종목과 같습니다."
    return (f"오늘 다시 뽑으면 {today_s} 입니다. {prev}에 매수했다면 지금은 {rule_s} 을 들고 있을 것입니다"
            "(그때 실제로 매수한 경우에만 의미가 있습니다).")


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


def action_summary(*, core: dict, picks: list[str], next_reselection: dict,
                   previous: Optional[dict] = None,
                   stop_rows: Optional[list[dict]] = None) -> dict:
    """'지금 실제로 바꿀 것이 있는가' 한 줄 + 항목. 주문하지 않는다(문구만 만든다).

    picks: 주 추천(오늘자 재선정) 새틀라이트 종목 — 화면 맨 위와 같은 목록을 기준으로 비교한다.
    next_reselection: next_reselection_after_purchase() 결과(매수일 + 6개월).
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
                     f"{cs.SATELLITE_DONCHIAN_STOP_PCT:.0%}) 아래입니다. 백테스트는 보유 6개월 사이 중도 청산을 "
                     "하지 않으므로 규칙상 매도 신호가 아니라 경고입니다."),
        })

    if previous is None:
        headline = (f"{ACTION_NO_BASELINE} — 어제 상태 캐시(champion_signal_state.json)가 없어 무엇이 바뀌는지 "
                    f"비교하지 못했습니다. 지금 추천: 코어 {', '.join(top4) or '없음'} / 새틀라이트 "
                    f"{', '.join(picks) or '없음(현금)'}")
        return {"headline": headline, "items": items, "has_changes": None, "places_orders": False,
                "compared_with": None}

    core_text = _swap_text("코어", list(previous.get("core_top4") or []), top4)
    # 새틀라이트는 비교하지 않는다 — 어제 밤 저장 상태(champion_signal_state.json)의 새틀라이트는
    # '빠른 근사 스캔'(compute_satellite_recommendation, 다른 방법론·5종목)이라 오늘자 point-in-time
    # 재선정과 비교하면 매번 '교체 필요'가 뜬다(2026-10-02 사용자 지적). 실제 매매할 것은
    # order_plan()이 내 보유와 비교해 보여 준다.
    changes = [t for t in (core_text,) if t]
    items.append({
        "kind": "note",
        "text": ("새틀라이트는 어제 밤 저장 목록(빠른 근사 스캔 — 다른 방법론)과 비교하지 않습니다. "
                 "실제로 사고팔 것은 '지금 할 일'의 주문 목록(내 보유와 비교)을 보세요."),
    })
    if changes:
        headline = " · ".join(changes)
        items = [{"kind": "change", "text": t} for t in changes] + items
    else:
        headline = (f"{ACTION_NO_CHANGE} — 오늘 매수했다면 다음 새틀라이트 재선정은 "
                    f"{next_reselection.get('date')}(매수일 + {next_reselection.get('months')}개월)입니다. "
                    "코어는 매달 첫 거래일에 다시 봅니다.")
    return {"headline": headline, "items": items, "has_changes": bool(changes), "places_orders": False,
            "compared_with": previous.get("as_of")}


# ============================================================================================
# '지금 할 일' 카드 (2026-10-02 추가) — 화면 맨 위 한 장으로 "무엇을 사고팔아 무엇을 들고 있어야
# 하나"를 답한다. 재추천 결과와 '포트폴리오' 화면에 입력한 보유를 합치기만 하고 새 신호는 만들지 않는다.
# ============================================================================================

CASH_TICKER = "CASH"


def target_allocation(rec: dict) -> list[dict]:
    """재추천 결과 → 포트폴리오 전체 기준 목표 비중 행 [{ticker, sleeve, weight(0~1)}].

    코어는 이미 전체 기준 비중(per_ticker_weights), 새틀라이트는 슬리브 안 비중이라 슬리브 비중을 곱한다.
    남는 몫(시장필터 축소분·새틀라이트 미배정)은 현금 행 하나로 둔다.
    """
    core = rec.get("core") or {}
    sat_today = (rec.get("satellite") or {}).get("today") or {}
    sat_weight = float((rec.get("params") or {}).get("satellite_weight", cs.SATELLITE_WEIGHT))
    weights: dict[str, float] = {}
    sleeves: dict[str, str] = {}
    for t, w in (core.get("per_ticker_weights") or {}).items():
        weights[t] = weights.get(t, 0.0) + float(w)
        sleeves[t] = "코어"
    for t, w in (sat_today.get("sleeve_weights") or {}).items():
        weights[t] = weights.get(t, 0.0) + float(w) * sat_weight
        sleeves[t] = "코어+새틀라이트" if t in sleeves else "새틀라이트"
    order = {"코어": 0, "코어+새틀라이트": 1, "새틀라이트": 2}
    rows = [{"ticker": t, "sleeve": sleeves[t], "weight": w}
            for t, w in sorted(weights.items(), key=lambda kv: (order[sleeves[kv[0]]], -kv[1], kv[0]))]
    cash = 1.0 - sum(weights.values())
    if cash > 1e-6:
        rows.append({"ticker": CASH_TICKER, "sleeve": "현금", "weight": cash})
    return rows


def order_plan(targets: list[dict], holdings: Optional[dict[str, float]] = None, cash: float = 0.0,
               capital: float = 10_000.0, band_pct: float = cs.REBALANCE_HOLD_BAND_PCT) -> dict:
    """목표 비중과 내 보유(티커→평가금액, 현금)를 비교해 매도/매수/유지 목록을 만든다. 주문하지 않는다.

    보유와 현금이 모두 비어 있으면 '처음 매수'로 보고 capital 을 총액으로 쓴다(basis="fresh").
    비중 차이가 band_pct(%p) 미만이면 '유지'. 목표에 없는 보유는 '전량 매도'.
    rows 는 매도 → 매수 → 유지 순(매도 대금으로 매수하는 순서)이며 현금 행은 넣지 않는다.
    """
    holdings = {t: float(v or 0.0) for t, v in (holdings or {}).items() if t != CASH_TICKER}
    cash = float(cash or 0.0)
    fresh = not any(v > 0 for v in holdings.values()) and cash <= 0
    total = float(capital) if fresh else sum(holdings.values()) + cash
    target_w = {r["ticker"]: r["weight"] for r in targets if r["ticker"] != CASH_TICKER}
    sleeves = {r["ticker"]: r["sleeve"] for r in targets}
    rows = []
    for t in sorted(set(target_w) | set(holdings)):
        cur = holdings.get(t, 0.0)
        tgt = target_w.get(t, 0.0) * total
        delta = tgt - cur
        diff_pct = (delta / total * 100) if total > 0 else 0.0
        if t not in target_w:
            action = "전량 매도"
        elif abs(diff_pct) < band_pct:
            action = "유지"
        else:
            action = "매수" if delta > 0 else "매도"
        rows.append({"ticker": t, "sleeve": sleeves.get(t, "추천 밖 보유"), "action": action,
                     "current_value": round(cur, 2), "target_value": round(tgt, 2),
                     "delta_value": round(delta, 2), "diff_pct": round(diff_pct, 2)})
    rank = {"전량 매도": 0, "매도": 1, "매수": 2, "유지": 3}
    rows.sort(key=lambda r: (rank[r["action"]], -abs(r["delta_value"])))
    target_cash = sum(r["weight"] for r in targets if r["ticker"] == CASH_TICKER) * total
    return {"basis": "fresh" if fresh else "holdings", "total": round(total, 2),
            "target_cash": round(target_cash, 2), "rows": rows,
            "n_trades": sum(1 for r in rows if r["action"] != "유지")}


def freshness(rec: Optional[dict], today: Optional[date] = None,
              live_core_top4: Optional[list[str]] = None) -> dict:
    """재추천 결과를 지금 그대로 써도 되는지. 써도 되면 ok=True.

    낡았다고 보는 경우: 결과가 없음 / 기준일이 지난달(그 사이 코어 월간 리밸런싱일이 지남) /
    오늘 다시 계산한 코어 top4 가 결과와 다름. 하루이틀 지난 것만으로는 막지 않고 알려만 준다.
    """
    today = today or date.today()
    if not rec:
        return {"ok": False, "level": "missing", "reason": "아직 추천을 계산하지 않았습니다."}
    n = days_ago(rec, today)
    as_of = str((rec.get("params") or {}).get("as_of") or rec.get("as_of") or "")
    rec_top4 = sorted((rec.get("core") or {}).get("top4") or [])
    if as_of[:7] and as_of[:7] != today.isoformat()[:7]:
        return {"ok": False, "level": "stale", "days": n,
                "reason": (f"{as_of} 기준 추천이라 이번 달 코어 리밸런싱(매달 첫 거래일)이 반영되지 않았습니다. "
                           "먼저 다시 계산하세요.")}
    if live_core_top4 is not None and sorted(live_core_top4) != rec_top4:
        return {"ok": False, "level": "stale", "days": n,
                "reason": (f"오늘 다시 계산한 코어({', '.join(sorted(live_core_top4))})가 추천 결과"
                           f"({', '.join(rec_top4)})와 다릅니다. 먼저 다시 계산하세요.")}
    if n:
        return {"ok": True, "level": "aging", "days": n,
                "reason": f"{n}일 전({as_of}) 계산 결과입니다. 매수 직전이라면 다시 계산하는 편이 안전합니다."}
    return {"ok": True, "level": "fresh", "days": 0, "reason": "오늘 계산한 추천입니다."}


def next_checkpoints(today: Optional[date] = None, trading_days: Optional[frozenset] = None) -> dict:
    """다음에 이 화면을 다시 볼 날: 코어(다음 달 첫 거래일)·새틀라이트(오늘 매수 시 + 6개월)."""
    today = today or date.today()
    this_month_first = first_trading_day_of_month(today.year, today.month, trading_days)
    ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return {
        "core_next": first_trading_day_of_month(ny, nm, trading_days).isoformat(),
        "core_rebalance_this_month": this_month_first.isoformat(),
        "core_rebalanced_recently": 0 <= (today - this_month_first).days <= 7,
        "satellite_next": next_reselection_after_purchase(today)["date"],
    }


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

    # 주 추천: 오늘자 재선정 — 아직 보유하지 않은 사람에게는 이것이 규칙의 정상 적용이다
    today_info = satellite_today_fn(pd.Timestamp(as_of), sizing_method=sizing_method)
    today_picks = list(today_info.get("picks") or [])

    # 참고: 직전 반기일에 매수했다면 지금 보유 중일 종목 — 같은 함수, 날짜 인자만 직전 반기일
    rule = satellite_rule_fn(as_of_date=as_of.isoformat(), sizing_method=sizing_method)
    rule_picks = list(rule.get("selected") or [])

    next_rebal = next_satellite_rebalance(as_of)
    next_reselection = next_reselection_after_purchase(as_of)

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

    # 근거는 주 추천(오늘자 재선정) 기준으로 계산한다 — 화면 맨 위에 붙는 표가 이것이다.
    evidence_rows = satellite_evidence(
        today_picks, as_of.isoformat(), as_of,
        candidates=today_candidates, price_fn=price_fn, sector_map=sector_map,
    )

    satellite_block = {
        "if_bought_at_last_rebal": {
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
        "today": {
            "as_of": as_of.isoformat(),
            "picks": today_picks,
            "sleeve_weights": today_info.get("weights") or {},
            "pool_size": today_info.get("pool_size"),
            "n_active_trend": today_info.get("n_active_trend"),
            "candidates": today_candidates,
            "is_primary": True,
        },
        "diff_note": satellite_diff_note(rule_picks, today_picks, next_rebal),
        "same_picks": list(rule_picks) == list(today_picks),
        "next_reselection_if_bought_today": next_reselection,
        "next_rebalance": next_rebal,  # 1·7월 달력 기준(참고 목록 쪽에서만 쓴다)
        "timing_note": TIMING_NOTE,
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
    action = action_summary(core=core, picks=today_picks, next_reselection=next_reselection,
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


# ============================================================================================
# 종목 차트 보조 (2026-10-02 추가) — '지금 할 일' 카드에서 종목을 눌러 차트를 볼 때 쓴다.
#
# 이 전략에는 지정가·목표 매수가가 없다. 규칙은 리밸런싱일 종가(=그때의 시장가)에 사는 것이고,
# 더 싼 가격을 기다렸다 사는 방식은 검증하지 않았다. 그래서 여기서는 '좋은 매수가'를 만들지 않고
# 규칙이 실제로 쓰는 기준값(현재가, 새틀라이트의 20일 돌파선·트레일링스탑, 코어의 12개월 전 가격)과
# 매수 금액 ÷ 현재가 = 대략 몇 주만 돌려준다. 지지·저항선 같은 새 신호는 계산하지 않는다.
# ============================================================================================

CHART_LOOKBACK_CALENDAR_DAYS = 420  # 12개월 모멘텀 기준가(252거래일 전)까지 담기도록 1년보다 넉넉히


def chart_tickers(targets: list[dict]) -> list[str]:
    """목표 포트폴리오 행 → 차트를 열 수 있는 종목 목록(현금 제외, 표의 순서 그대로)."""
    return [r["ticker"] for r in targets if r.get("ticker") and r["ticker"] != CASH_TICKER]


def fetch_chart_history(ticker: str, today: Optional[date] = None,
                        price_fn: Optional[Callable] = None,
                        lookback_days: int = CHART_LOOKBACK_CALENDAR_DAYS) -> Optional[pd.DataFrame]:
    """종목 하나의 일봉(약 14개월). 받지 못하면(오프라인·빈 값·예외) None — 화면이 안내 문구를 띄운다."""
    today = today or date.today()
    if price_fn is None:
        from core import market_data

        price_fn = market_data.get_price_history
    start = (today - timedelta(days=lookback_days)).isoformat()
    try:
        df = price_fn(ticker, start=start)
    except Exception:  # noqa: BLE001 - 네트워크·데이터 오류는 화면에서 안내만 한다
        return None
    if df is None or df.empty or "Close" not in df.columns or df["Close"].dropna().empty:
        return None
    return df


def estimate_shares(amount: float, price: Optional[float]) -> dict:
    """금액 ÷ 현재가 → 정수 주(내림). 가격이 없거나 0 이하면 shares=None."""
    amount = abs(float(amount or 0.0))
    if price is None or not price > 0:
        return {"shares": None, "cost": None, "leftover": None}
    shares = max(int(amount / float(price) + 1e-9), 0)  # 양수라 int() 가 곧 내림
    cost = round(shares * float(price), 2)
    return {"shares": shares, "cost": cost, "leftover": round(amount - cost, 2)}


def entry_chart_levels(close: pd.Series, sleeve: str, evidence_row: Optional[dict] = None,
                       evidence_as_of: Optional[str] = None) -> dict:
    """차트에 그을 기준선. 새 신호가 아니라 규칙이 이미 쓰는 값만 꺼낸다.

    - 현재가: 마지막 종가와 그 날짜.
    - 새틀라이트: 20일 돌파선(직전 20거래일 최고 종가 — cs.donchian_trailing_stop_positions 의 진입 기준)과
      트레일링스탑 기준(진입 이후 최고 종가 × (1 − SATELLITE_DONCHIAN_STOP_PCT)). 트레일링스탑은 추천 결과의
      근거 행(evidence_row)을 그대로 쓰고, 추천 계산일(evidence_as_of) 뒤로 종가가 더 올랐으면 그만큼만
      고점을 올린다. 근거 행이 없으면 받은 종가로 같은 함수를 돌려 계산한다.
    - 코어: 12개월 전 가격(CORE_MOMENTUM_LOOKBACK_DAYS 거래일 전 종가 — 모멘텀 순위가 비교하는 기준).
    """
    close = close.dropna()
    out: dict = {"last_close": None, "last_date": None, "levels": [], "stop_headroom_pct": None,
                 "trailing_stop": None, "breakout_level": None, "momentum_ref": None, "momentum_12m_pct": None}
    if close.empty:
        return out
    last = float(close.iloc[-1])
    out["last_close"] = round(last, 2)
    out["last_date"] = pd.Timestamp(close.index[-1]).date().isoformat()
    out["levels"].append({"key": "last", "label": "현재가", "price": round(last, 2)})

    if "새틀라이트" in (sleeve or ""):
        win = cs.SATELLITE_DONCHIAN_WINDOW
        if len(close) > win:
            breakout = float(close.iloc[-1 - win:-1].max())
            out["breakout_level"] = round(breakout, 2)
            out["levels"].append({"key": "breakout", "label": f"{win}일 돌파선", "price": round(breakout, 2)})
        stop = None
        ev_stop = (evidence_row or {}).get("trailing_stop")
        if ev_stop:
            peak = float(ev_stop) / (1 - cs.SATELLITE_DONCHIAN_STOP_PCT)
            if evidence_as_of:
                after = close[close.index > pd.Timestamp(evidence_as_of)]
                if not after.empty:
                    peak = max(peak, float(after.max()))
            stop = peak * (1 - cs.SATELLITE_DONCHIAN_STOP_PCT)
        elif len(close) > win:
            pos = cs.donchian_trailing_stop_positions(close)
            if int(pos.iloc[-1]) == 1:
                i = len(pos) - 1
                while i > 0 and pos.iloc[i - 1] == 1:
                    i -= 1
                stop = float(close.iloc[i:].max()) * (1 - cs.SATELLITE_DONCHIAN_STOP_PCT)
        if stop:
            out["trailing_stop"] = round(stop, 2)
            out["stop_headroom_pct"] = round((last / stop - 1) * 100, 2)
            out["levels"].append({"key": "stop", "label": "트레일링스탑 기준", "price": round(stop, 2)})

    if "코어" in (sleeve or ""):
        n = cs.CORE_MOMENTUM_LOOKBACK_DAYS
        if len(close) > n:
            ref = float(close.iloc[-1 - n])
            out["momentum_ref"] = round(ref, 2)
            out["momentum_12m_pct"] = round((last / ref - 1) * 100, 2) if ref else None
            out["levels"].append({"key": "momentum_ref", "label": "12개월 전 가격", "price": round(ref, 2)})
    return out
