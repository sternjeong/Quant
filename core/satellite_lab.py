"""새틀라이트 R&D 센터 (2026-10-02) — 새틀라이트 종목 선정 규칙을 계속 연구하는 결정론 엔진·심판·등록부.

질문은 하나다: "이 규칙이 지금 챔피언 새틀라이트 규칙(현 규칙)보다, 그리고 같은 후보 풀에서 무작위로 고른 것보다
종목을 더 잘 고르는가?" 일반 가설 연구실(core.hypothesis_*)은 독립 전략을 SPY 와 비교하므로 이 질문에 답하지 않는다.

흐름
  아이디어(시작 목록 research/satellite_lab/seeds/ + 야간 에이전트 research/satellite_lab/variants/)
  → 동결(freeze: 스펙 검증·코드 해시·시도 수 누적, 이후 수정 불가) → 대기열
  → VM 연구 창에서 scripts/satellite_lab_worker.py 가 심판(judge_variant) → 등록부(data/satellite_lab/registry.json)
  → 관제 센터 '새틀라이트 R&D 센터' 순위표·텔레그램. 통과는 '사람 검토 대기'일 뿐 챔피언에 자동 반영되지 않는다.

공정한 비교: 후보·현 규칙·무작위 기준선이 **같은 시뮬레이터, 같은 후보 풀, 같은 비용**으로 돈다.
  - 리밸런싱일 d(보유 1·3·6개월 → 매월 / 1·4·7·10월 / 1·7월 첫 거래일)마다 신호는 d 전날 종가까지의 일봉만 본다.
  - d 종가에 동일가중 매수, 다음 리밸런싱일 종가까지 보유(비중은 가격에 따라 표류). 선택적 트레일링스탑:
    진입 후 고점 대비 stop_pct 하락한 날 종가에 팔고 그 몫은 다음 리밸런싱까지 현금(수익 0).
  - 비용: 편도 SATELLITE_COST_BPS_PER_SIDE(8bp) × 회전율(이어서 보유하는 종목은 비용 없음), 스탑 청산도 편도 비용.
  - 후보 풀: champion40(현 규칙이 쓰는 섹터 균등·그 시점 시총 상위 40종목 표본, 반기마다 갱신) 또는
    sp500_pit(그 시점 S&P500 편입 종목 전체). 코어 17자산·SPY 는 뺀다.

판정 규칙(JUDGE_VERSION, 결과를 보기 전에 고정 — 바꾸려면 새 버전으로 다시 등록): 맨 아래 judge_variant 참고.
계속 시도하면 우연히 좋아 보이는 것이 반드시 나온다 — 그래서 모든 시도(파라미터 조합)를 영구 누적해 G2 의 기준을
올리고, 마지막 2년은 파라미터 선택에 쓰지 않는다.

한계(결과에 그대로 남긴다): 무료 가격 소스에 없는 상장폐지 종목은 후보에서 빠진다(생존편향). 배당·세금·슬리피지 미반영.
champion40 풀은 그 시점 시총 근사(발행주식수 이력 × 종가)에 기대며 이 근사 자체는 별도 검증되지 않았다.
주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import types
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median, pvariance
from typing import Any, Callable, Iterable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAB_DIR = PROJECT_ROOT / "research" / "satellite_lab"
SEEDS_DIR = LAB_DIR / "seeds"          # 저장소에 커밋된 시작 목록(사람이 쓴 것)
VARIANTS_DIR = LAB_DIR / "variants"    # 야간 에이전트가 쓰는 곳(VM 로컬, .gitignore)
STATE_DIR = PROJECT_ROOT / "data" / "satellite_lab"
INCUMBENT_ID = "S-SEED-000"

JUDGE_VERSION = "sat-judge/v3"
# v3(2026-10-08): 관문은 그대로, champion40 후보 풀 '측정'만 바뀌었다 — core.point_in_time_market_cap 이 발행주식수 이력
# 시작(2015 말) 전 날짜에서 분할을 두 번 세던 버그(2014 AAPL 6배·GOOGL 2배 과대)와, 이름이 바뀐 종목(FB→META 등)이
# 가격이 없어 풀에서 빠지던 문제를 고쳤다. 풀 캐시 파일 이름도 바꿔(POOL_CACHE_TAG) 예전 풀을 다시 쓰지 않는다.
POOL_CACHE_TAG = "pit2"
# v2(2026-10-05): 판정 관문은 v1 과 같고 '측정'만 바뀌었다 — 수익을 배당 포함 조정 가격(Adj Close)으로 잰다(v1 은 Close, 배당 누락).
# 등록부가 v1 이면 migrate_registry() 가 v1 결과를 보관하고 모든 아이디어를 v2 로 다시 심판한다(누적 시도 수는 이어서 센다).
ID_RE = re.compile(r"^S-(SEED|\d{8})-\d{3}$")
POOLS = ("champion40", "sp500_pit")
HOLD_MONTHS = {1: (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12), 3: (1, 4, 7, 10), 6: (1, 7)}
TOP_K_RANGE = (3, 10)
EXIT_TYPES = ("none", "trailing_stop", "take_profit", "time_stop", "trend_break")
STOP_RANGE = (0.05, 0.40)
ENTRY_TYPES = ("close", "delay", "pullback")
TOPICS = ("selection", "entry", "exit", "guru")
# 2026-10-08: 가격 밖의 데이터. 스펙에 "data": ["fundamentals"] 가 있으면 신호는 score(prices, as_of, params, ctx) 로 불리고
# ctx.fundamentals(티커) 가 as_of(리밸런싱 전날)까지 공시된 재무·실적 발표만 돌려준다(core/fundamentals_pit.py).
DATA_SOURCES = ("fundamentals", "guru13f")  # guru13f(2026-10-08): ctx.guru(티커) — 거장 13F 보유(core/guru_history.py)  # 아이디어가 주로 바꾸는 것 — R&D 센터 주제 켜기/끄기(core/rnd_topics.py)와 연결
# 2026-10-05 확장(사용자 요청): 진입 타이밍·매도 규칙도 아이디어가 바꿀 수 있다. 범위(넘으면 계약 위반):
ENTRY_RANGES = {"delay": {"days": (1, 20)}, "pullback": {"sma": (3, 50), "max_wait": (1, 40)}}
EXIT_RANGES = {"trailing_stop": {"stop_pct": (0.05, 0.40)}, "take_profit": {"tp": (0.05, 2.0)},
               "time_stop": {"days": (5, 120)}, "trend_break": {"sma": (10, 200)}}
MAX_GRID = 4
LAB_START = "2010-01-01"
LOOKBACK_CALENDAR_DAYS = 730  # 신호에 넘기는 기간 — 현 규칙(SATELLITE_BACKTEST_WARMUP_DAYS)과 같은 리밸런싱일 전 730달력일
MIN_HISTORY_ROWS = 260       # 무작위 기준선 후보 자격: 이만큼 이력이 있는 종목(12개월 모멘텀 계산 가능 수준)
N_RANDOM = 200
RANDOM_SEED = 20261002
CHAMPION_POOL_N = 40
WEEKLY_AGENT_FREEZE_CAP = 6  # 에이전트 아이디어 동결 주간 상한(시도 수가 너무 빨리 불어나지 않게)

# --- 판정 기준 (sat-judge/v1, 2026-10-02 고정) ---------------------------------------------------
HOLDOUT_YEARS = 2            # 마지막 2년은 떼어 두고 파라미터 선택에 쓰지 않는다
MIN_IS_DAYS = 756            # IS 최소 약 3년
MIN_OOS_DAYS = 252
G1_RANDOM_PCTL = 0.95        # IS 샤프가 같은 구조 무작위 선정 분포의 95백분위 이상
G2_DSR = 0.95                # 현 규칙 대비 초과수익(일별)의 Deflated Sharpe ≥ 0.95, 누적 시도 수 반영
G3_OOS_RANDOM_PCTL = 0.50    # 떼어 둔 2년: 현 규칙보다 샤프가 높고, 무작위 분포 중앙 이상
G4_KEEP = 0.5                # 이웃 파라미터(×0.5·×1.5)의 초과 샤프가 모두 양수, 중앙값 ≥ 선택값의 50%
G5_MDD_TOLERANCE = 0.10      # IS 최대낙폭이 현 규칙보다 10%p 넘게 나쁘면 탈락
MIN_IS_PERIODS = 12
DEFAULT_ACTIVE_SR_ANNUAL_SD = 0.5
TRADING_DAYS = 252

STATUS_QUEUED, STATUS_PASS, STATUS_FAIL, STATUS_ERROR = "queued", "pass", "fail", "error"
MAX_JUDGE_ATTEMPTS = 3

PoolProvider = Callable[[str, date], list[str]]
PriceProvider = Callable[[str, str, str], pd.DataFrame]


class LabSpecError(ValueError):
    """새틀라이트 연구 스펙이 계약을 어겼다."""


# =================================================================================================
# 스펙
# =================================================================================================

def validate_spec(spec: dict) -> dict:
    """계약 검사 후 정규화한 사본. 위반이면 LabSpecError(모든 사유)."""
    e: list[str] = []
    if not isinstance(spec, dict):
        raise LabSpecError("스펙이 JSON 객체가 아님")
    if not ID_RE.match(str(spec.get("id", ""))):
        e.append("id: S-YYYYMMDD-NNN (시작 목록은 S-SEED-NNN) 형식")
    if spec.get("parent") is not None and not ID_RE.match(str(spec["parent"])):
        e.append("parent: S-… 형식 또는 null")
    for key, limit in (("thesis", 500), ("source", 300), ("title", 80)):
        val = str(spec.get(key) or "").strip()
        if not val or len(val) > limit:
            e.append(f"{key}: 1~{limit}자 필요")
    pool = (spec.get("pool") or {}).get("type")
    if pool not in POOLS:
        e.append(f"pool.type: {POOLS} 중 하나")
    grid = (spec.get("signal") or {}).get("params_grid")
    if not isinstance(grid, list) or not (1 <= len(grid) <= MAX_GRID) or not all(isinstance(g, dict) for g in grid):
        e.append(f"signal.params_grid: 1~{MAX_GRID}개의 객체 목록")
    elif len({json.dumps(g, sort_keys=True) for g in grid}) != len(grid):
        e.append("signal.params_grid: 같은 조합이 중복됨")
    pf = spec.get("portfolio") or {}
    top_k = pf.get("top_k")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not (TOP_K_RANGE[0] <= top_k <= TOP_K_RANGE[1]):
        e.append(f"portfolio.top_k: {TOP_K_RANGE[0]}~{TOP_K_RANGE[1]} 정수")
    if pf.get("hold_months") not in HOLD_MONTHS:
        e.append(f"portfolio.hold_months: {tuple(HOLD_MONTHS)} 중 하나")
    def _ranged(kind: str, cfg: dict, ranges: dict, label: str) -> dict:
        out = {"type": kind}
        for k2, (lo, hi) in ranges.get(kind, {}).items():
            val = cfg.get(k2)
            if not isinstance(val, (int, float)) or isinstance(val, bool) or not (lo <= val <= hi):
                e.append(f"{label}.{k2}: {lo}~{hi}")
            else:
                out[k2] = val
        return out

    ex = spec.get("exit") or {"type": "none"}
    if ex.get("type") not in EXIT_TYPES:
        e.append(f"exit.type: {EXIT_TYPES} 중 하나")
        ex_clean = {"type": "none"}
    else:
        ex_clean = _ranged(ex["type"], ex, EXIT_RANGES, "exit")
    en = spec.get("entry") or {"type": "close"}
    if en.get("type") not in ENTRY_TYPES:
        e.append(f"entry.type: {ENTRY_TYPES} 중 하나")
        en_clean = {"type": "close"}
    else:
        en_clean = _ranged(en["type"], en, ENTRY_RANGES, "entry")
    if spec.get("topic", "selection") not in TOPICS:
        e.append(f"topic: {TOPICS} 중 하나")
    data_src = spec.get("data", [])
    if not isinstance(data_src, list) or any(x not in DATA_SOURCES for x in data_src):
        e.append(f"data: {DATA_SOURCES} 의 부분 목록")
    if e:
        raise LabSpecError("; ".join(e))
    out = json.loads(json.dumps(spec))
    out["exit"] = ex_clean
    out["entry"] = en_clean
    out["topic"] = spec.get("topic", "selection")
    if spec.get("data"):
        out["data"] = sorted(set(spec["data"]))
    return out


def structure_key(spec: dict) -> str:
    """무작위 기준선을 공유하는 구조(풀·종목 수·보유기간·진입·청산). 진입·청산이 기본값이면 예전 키와 같다."""
    def part(cfg: Optional[dict], default: str) -> str:
        cfg = cfg or {"type": default}
        if cfg.get("type") == default:
            return ""
        if cfg.get("type") == "trailing_stop":
            return f"{cfg['stop_pct']:.3f}"
        return cfg["type"] + "(" + ",".join(f"{k}={cfg[k]}" for k in sorted(cfg) if k != "type") + ")"
    ex = part(spec.get("exit"), "none") or "none"
    en = part(spec.get("entry"), "close")
    key = f"{spec['pool']['type']}|k{spec['portfolio']['top_k']}|h{spec['portfolio']['hold_months']}|{ex}"
    return key + (f"|in:{en}" if en else "")


def load_signal(code: str) -> Callable:
    """신호 코드 원문을 격리된 네임스페이스에서 실행해 score 함수를 돌려준다(동결·검사된 코드만)."""
    mod = types.ModuleType("satellite_lab_signal")
    exec(compile(code, "<satellite_lab_signal>", "exec"), mod.__dict__)  # noqa: S102
    fn = mod.__dict__.get("score")
    if not callable(fn):
        raise LabSpecError("신호 코드에 score(prices, as_of, params) 함수가 없음")
    return fn


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# =================================================================================================
# 데이터
# =================================================================================================

def rebalance_dates(trading_days: pd.DatetimeIndex, hold_months: int) -> list[pd.Timestamp]:
    """보유기간에 맞는 달의 첫 거래일."""
    months = HOLD_MONTHS[hold_months]
    s = pd.Series(trading_days, index=trading_days)
    firsts = s.groupby(trading_days.to_period("M")).min()
    return [d for d in firsts if d.month in months]


def _anchor(d: date) -> date:
    """champion40 풀은 반기(1·7월) 단위로 갱신한다 — d 이전 가장 가까운 1/1 또는 7/1."""
    return date(d.year, 7, 1) if d.month >= 7 else date(d.year, 1, 1)


def default_pool_provider(cache_dir: Optional[Path] = None) -> PoolProvider:
    """실데이터 풀. champion40 은 현 규칙(_pick_satellite_at_date)과 같은 sample_universe 호출, 결과는 캐시."""
    cache = Path(cache_dir or STATE_DIR / "pools")

    def provider(pool_type: str, d: date) -> list[str]:
        from core.champion_strategy import CORE_UNIVERSE, MARKET_FILTER_TICKER

        exclude = set(CORE_UNIVERSE) | {MARKET_FILTER_TICKER}
        if pool_type == "sp500_pit":
            from core import hypothesis_engine as he

            dates, members = he._sp500_rows()
            i = bisect_right(dates, d) - 1
            raw = members[i] if i >= 0 else ()
            return sorted({he.price_symbol(t) for t in raw} - exclude)
        anchor = _anchor(d)
        path = cache / f"champion40_{POOL_CACHE_TAG}_{anchor.isoformat()}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        from core.strategy_tuning import sample_universe

        pool = sample_universe(n=CHAMPION_POOL_N, as_of_date=anchor.isoformat(),
                               use_point_in_time_market_cap=True, use_cache=True)
        tickers = [t for t in pool["ticker"].tolist() if t not in exclude]
        _atomic_write(path, json.dumps(tickers))
        return tickers

    return provider


@dataclass
class LabData:
    """한 번 읽어 여러 후보·기준선이 공유하는 가격·풀."""
    trading_days: pd.DatetimeIndex
    ohlcv: dict[str, pd.DataFrame]
    closes: pd.DataFrame                      # trading_days × 종목, 결측은 NaN(전방 채움 안 함)
    pools: dict[tuple[str, pd.Timestamp], list[str]] = field(default_factory=dict)
    pool_provider: Optional[PoolProvider] = None
    fundamentals: Any = None                  # core.fundamentals_pit.Store — 'fundamentals' 를 쓰는 아이디어만 필요
    guru: Any = None                          # core.guru_history.Store — 'guru13f' 를 쓰는 아이디어만 필요

    def pool(self, pool_type: str, d: pd.Timestamp) -> list[str]:
        key = (pool_type, d)
        if key not in self.pools:
            self.pools[key] = list(self.pool_provider(pool_type, d.date())) if self.pool_provider else []
        return self.pools[key]


def build_data(pool_types: Iterable[str], *, start: str = LAB_START, end: Optional[str] = None,
               pool_provider: Optional[PoolProvider] = None, price_provider: Optional[PriceProvider] = None,
               calendar_ticker: str = "SPY", log: Callable[[str], Any] = lambda s: None) -> LabData:
    """필요한 모든 리밸런싱일(매월 첫 거래일)의 풀 합집합 가격을 읽는다."""
    from core import hypothesis_engine as he

    pool_provider = pool_provider or default_pool_provider()
    end_d = date.fromisoformat(end) if end else date.today()
    start_d = date.fromisoformat(start)
    cal = he.load_prices([calendar_ticker], start_d, end_d, price_provider).get(calendar_ticker)
    if cal is None or cal.empty:
        raise RuntimeError(f"거래일 달력({calendar_ticker}) 가격을 읽지 못함")
    days = cal.index[(cal.index >= pd.Timestamp(start_d)) & (cal.index <= pd.Timestamp(end_d))]
    data = LabData(trading_days=days, ohlcv={}, closes=pd.DataFrame(index=days), pool_provider=pool_provider)
    tickers: set[str] = set()
    for pt in sorted(set(pool_types)):
        for d in rebalance_dates(days, 1):
            tickers.update(data.pool(pt, d))
    log(f"풀 합집합 {len(tickers)}종목 가격 읽는 중")
    prices = he.load_prices(sorted(tickers), start_d - timedelta(days=800), end_d, price_provider)
    data.ohlcv = {t: df[df.index <= pd.Timestamp(end_d)] for t, df in prices.items()}
    # 수익은 배당 포함 조정 가격(sat-judge/v2). 신호는 ohlcv 의 Close(가격)를 그대로 본다 — 현 규칙과 같은 선택을 하도록.
    data.closes = pd.DataFrame({t: (df["Adj Close"] if "Adj Close" in df.columns and df["Adj Close"].notna().any() else df["Close"])
                                for t, df in data.ohlcv.items()}).reindex(days)
    return data


# =================================================================================================
# 시뮬레이터
# =================================================================================================

def _sma(closes: pd.DataFrame, t: str, n: int, cache: Optional[dict]) -> pd.Series:
    key = (t, n)
    if cache is not None and key in cache:
        return cache[key]
    sma = closes[t].ffill().rolling(n, min_periods=n).mean()
    if cache is not None:
        cache[key] = sma
    return sma


def _period_values(closes: pd.DataFrame, window: pd.DataFrame, picks: list[str], bps: float,
                   entry: Optional[dict] = None, exit_rule: Optional[dict] = None,
                   cache: Optional[dict] = None) -> tuple[pd.DataFrame, set[str]]:
    """한 보유 구간의 종목별 가치(시작=1). 진입 전에는 현금(가치 1 유지), 청산한 날 종가에 팔고 이후 값 고정(편도 비용).

    entry: close(리밸런싱 날 종가) / delay(days 거래일 뒤 종가) / pullback(sma·max_wait — 그 안에 종가가 이동평균 아래로 오면 그날,
           아니면 max_wait 째 종가). exit_rule: none / trailing_stop(stop_pct) / take_profit(tp) / time_stop(days) / trend_break(sma).
    반환: (가치 표, 구간 끝에 아직 보유 중인 종목 집합)."""
    entry = entry or {"type": "close"}
    exit_rule = exit_rule or {"type": "none"}
    sub = window[picks].ffill()
    n = len(sub)
    arr = np.ones((n, len(picks)))
    holding = set()
    for j, t in enumerate(picks):
        c = sub[t].to_numpy(dtype=float)
        k = 0
        if entry["type"] == "delay":
            k = min(int(entry["days"]), n - 1)
        elif entry["type"] == "pullback":
            sma = _sma(closes, t, int(entry["sma"]), cache).reindex(sub.index).to_numpy()
            k = min(int(entry["max_wait"]), n - 1)
            for i in range(1, k + 1):
                if not np.isnan(sma[i]) and c[i] < sma[i]:
                    k = i
                    break
        v = np.ones(n)
        v[k:] = c[k:] / c[k]
        hit = None
        et = exit_rule["type"]
        if et == "trailing_stop":
            peak = np.maximum.accumulate(v[k:])
            idx = np.nonzero(v[k:] <= peak * (1 - exit_rule["stop_pct"]))[0]
            idx = idx[idx > 0]
            hit = k + idx[0] if len(idx) else None
        elif et == "take_profit":
            idx = np.nonzero(v[k + 1:] >= 1 + exit_rule["tp"])[0]
            hit = k + 1 + idx[0] if len(idx) else None
        elif et == "time_stop":
            hit = k + int(exit_rule["days"]) if k + int(exit_rule["days"]) < n else None
        elif et == "trend_break":
            sma = _sma(closes, t, int(exit_rule["sma"]), cache).reindex(sub.index).to_numpy()
            idx = np.nonzero((c[k + 1:] < sma[k + 1:]) & ~np.isnan(sma[k + 1:]))[0]
            hit = k + 1 + idx[0] if len(idx) else None
        if hit is not None:
            v[hit:] = v[hit] * (1 - bps / 1e4)
        else:
            holding.add(t)
        arr[:, j] = v
    return pd.DataFrame(arr, index=sub.index, columns=picks), holding


def simulate(closes: pd.DataFrame, schedule: list[tuple[pd.Timestamp, list[str]]], end: pd.Timestamp,
             stop_pct: Optional[float], bps: float, *, entry: Optional[dict] = None,
             exit_rule: Optional[dict] = None, cache: Optional[dict] = None) -> dict:
    """[(리밸런싱일, 종목들)] → 일별 순수익(첫 리밸런싱 다음 날 ~ end). 비중은 동일가중 후 표류.
    stop_pct 는 하위호환(= exit_rule trailing_stop). 진입·청산 규칙은 _period_values."""
    if exit_rule is None and stop_pct is not None:
        exit_rule = {"type": "trailing_stop", "stop_pct": stop_pct}
    cache = {} if cache is None else cache
    rets: list[pd.Series] = []
    prev_w: dict[str, float] = {}
    turnovers: list[float] = []
    for i, (d, picks) in enumerate(schedule):
        nxt = schedule[i + 1][0] if i + 1 < len(schedule) else end
        window = closes.loc[d:nxt]
        if len(window) < 2:
            continue
        picks = [t for t in picks if t in window.columns and pd.notna(window[t].iloc[0])]
        new_w = {t: 1.0 / len(picks) for t in picks} if picks else {}
        turnover = sum(abs(new_w.get(t, 0.0) - prev_w.get(t, 0.0)) for t in set(new_w) | set(prev_w))
        turnovers.append(turnover)
        if picks:
            vals, holding = _period_values(closes, window, picks, bps, entry, exit_rule, cache)
            sleeve = vals.mean(axis=1)
            r = sleeve.pct_change().iloc[1:]
            last = vals.iloc[-1]
            tot = float(last.sum())
            prev_w = {t: float(last[t]) / tot for t in holding} if tot > 0 else {}
        else:
            r = pd.Series(0.0, index=window.index[1:])
            prev_w = {}
        r = r.copy()
        if bps:
            r.iloc[0] = (1 + r.iloc[0]) * (1 - bps / 1e4 * turnover) - 1
        rets.append(r)
    series = pd.concat(rets) if rets else pd.Series(dtype=float)
    series = series[~series.index.duplicated(keep="first")]
    return {"returns": series, "n_periods": len(turnovers),
            "avg_turnover": float(np.mean(turnovers)) if turnovers else 0.0}


def _prev_day(days: pd.DatetimeIndex, d: pd.Timestamp) -> Optional[pd.Timestamp]:
    i = days.searchsorted(d) - 1
    return days[i] if i >= 0 else None


def _signal_prices(data: LabData, members: list[str], cutoff: pd.Timestamp,
                   rebal: Optional[pd.Timestamp] = None) -> dict[str, pd.DataFrame]:
    """리밸런싱일 전 LOOKBACK_CALENDAR_DAYS 부터 cutoff(전날) 종가까지. 현 규칙과 같은 창이라야 같은 종목을 고른다."""
    start = (rebal if rebal is not None else cutoff) - pd.DateOffset(days=LOOKBACK_CALENDAR_DAYS)
    out = {}
    for t in members:
        df = data.ohlcv.get(t)
        if df is None:
            continue
        i, j = df.index.searchsorted(start, side="left"), df.index.searchsorted(cutoff, side="right")
        if j - i < 60:
            continue
        out[t] = df.iloc[i:j]
    return out


def pick_top(scores: dict, top_k: int, eligible: set[str]) -> list[str]:
    """유한한 점수만, 점수 내림차순(동점은 티커순) top_k. 신호는 담지 않을 종목을 빼거나 None/NaN 을 준다."""
    rows = []
    for t, s in (scores or {}).items():
        if t not in eligible:
            continue
        try:
            v = float(s)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            rows.append((t, v))
    rows.sort(key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in rows[:top_k]]


def _call_signal(signal: Callable, spec: dict, data: LabData, prices: dict, cutoff, params: dict):
    """가격만 쓰는 아이디어는 예전처럼 3개 인자, 재무를 쓰는 아이디어는 시점 기준 ctx 를 4번째로."""
    need = set(spec.get("data") or [])
    if need:
        if "fundamentals" in need and data.fundamentals is None:
            raise LabSpecError("이 아이디어는 재무 데이터가 필요한데 준비되지 않음")
        if "guru13f" in need and data.guru is None:
            raise LabSpecError("이 아이디어는 거장 13F 데이터가 필요한데 준비되지 않음")
        from core.fundamentals_pit import Context

        return signal(prices, cutoff, dict(params), Context(data.fundamentals if "fundamentals" in need else None, cutoff,
                                                            data.guru if "guru13f" in need else None))
    return signal(prices, cutoff, dict(params))


def run_variant(spec: dict, params: dict, signal: Callable, data: LabData, *,
                bps: Optional[float] = None) -> dict:
    """신호로 매 리밸런싱일 종목을 골라 시뮬레이션한다."""
    from core.champion_strategy import SATELLITE_COST_BPS_PER_SIDE

    bps = SATELLITE_COST_BPS_PER_SIDE if bps is None else bps
    pool_type, k = spec["pool"]["type"], spec["portfolio"]["top_k"]
    schedule = []
    for d in rebalance_dates(data.trading_days, spec["portfolio"]["hold_months"]):
        cutoff = _prev_day(data.trading_days, d)
        if cutoff is None:
            continue
        members = data.pool(pool_type, d)
        prices = _signal_prices(data, members, cutoff, d)
        eligible = {t for t in prices if t in data.closes.columns and pd.notna(data.closes.at[d, t])}
        scores = _call_signal(signal, spec, data, {t: prices[t] for t in eligible}, cutoff, params)
        schedule.append((d, pick_top(scores, k, eligible)))
    ex = spec.get("exit") or {}
    out = simulate(data.closes, schedule, data.trading_days[-1], None, bps,
                   entry=spec.get("entry"), exit_rule=spec.get("exit"), cache=data.__dict__.setdefault("_sma_cache", {}))
    out["schedule"] = [(d.date().isoformat(), p) for d, p in schedule]
    return out


def random_baseline(spec: dict, data: LabData, split: Optional[pd.Timestamp], *, n: int = N_RANDOM,
                    seed: int = RANDOM_SEED, bps: Optional[float] = None,
                    deadline: Optional[float] = None) -> Optional[dict]:
    """같은 구조(풀·종목 수·보유기간·청산)로 후보 풀에서 무작위로 골랐을 때의 IS/OOS 연샤프 분포."""
    from core import hypothesis_engine as he
    from core.champion_strategy import SATELLITE_COST_BPS_PER_SIDE
    import time as _t

    bps = SATELLITE_COST_BPS_PER_SIDE if bps is None else bps
    pool_type, k = spec["pool"]["type"], spec["portfolio"]["top_k"]
    ex = spec.get("exit") or {}
    dates = rebalance_dates(data.trading_days, spec["portfolio"]["hold_months"])
    eligible_by_date = []
    for d in dates:
        cutoff = _prev_day(data.trading_days, d)
        if cutoff is None:
            continue
        el = []
        for t in data.pool(pool_type, d):
            df = data.ohlcv.get(t)
            if df is None or t not in data.closes.columns or pd.isna(data.closes.at[d, t]):
                continue
            if df.index.searchsorted(cutoff, side="right") >= MIN_HISTORY_ROWS:
                el.append(t)
        eligible_by_date.append((d, sorted(el)))
    rng = np.random.default_rng(seed)
    is_srs, oos_srs = [], []
    for _ in range(n):
        if deadline is not None and _t.time() > deadline:
            return None
        schedule = [(d, list(rng.choice(el, size=min(k, len(el)), replace=False)) if el else []) for d, el in eligible_by_date]
        r = simulate(data.closes, schedule, data.trading_days[-1], None, bps, entry=spec.get("entry"),
                     exit_rule=spec.get("exit"), cache=data.__dict__.setdefault("_sma_cache", {}))["returns"]
        is_part = r[r.index < split] if split is not None else r
        is_srs.append(he.stats(is_part).get("sharpe_annual", 0.0))
        if split is not None:
            oos_srs.append(he.stats(r[r.index >= split]).get("sharpe_annual", 0.0))
    return {"key": structure_key(spec), "n": n, "seed": seed, "is_sharpe": is_srs, "oos_sharpe": oos_srs}


def percentile_of(value: float, dist: list[float]) -> Optional[float]:
    if not dist:
        return None
    return float(np.mean([x < value for x in dist]) + 0.5 * np.mean([x == value for x in dist]))


def holdout_split(index: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    if len(index) == 0:
        return None
    split = index[-1] - pd.DateOffset(years=HOLDOUT_YEARS)
    n_is, n_oos = int((index < split).sum()), int((index >= split).sum())
    return split if n_is >= MIN_IS_DAYS and n_oos >= MIN_OOS_DAYS else None


# =================================================================================================
# 심판 (sat-judge/v1)
# =================================================================================================

def _segment(r: pd.Series, split: Optional[pd.Timestamp], part: str) -> pd.Series:
    if split is None:
        return r if part == "is" else r.iloc[0:0]
    return r[r.index < split] if part == "is" else r[r.index >= split]


def _active(r: pd.Series, base: pd.Series) -> pd.Series:
    both = pd.concat([r.rename("v"), base.rename("b")], axis=1).fillna(0.0)
    return both["v"] - both["b"]


def _round(d: dict, n: int = 4) -> dict:
    return {k: (round(v, n) if isinstance(v, float) else v) for k, v in d.items()}


def judge_variant(spec: dict, signal_code: str, data: LabData, *, incumbent: dict, baseline: dict,
                  cumulative_trials: int, prior_active_srs: list[float], bps: Optional[float] = None) -> dict:
    """사전 고정된 다섯 관문(G1~G5). 모두 통과해야 PASS(= 사람 검토 대기). 결과는 JSON 직렬화 가능."""
    from core import hypothesis_engine as he
    from core import hypothesis_judge as hj

    signal = load_signal(signal_code)
    inc_r = incumbent["returns"]
    split = holdout_split(inc_r.index)
    trials = []
    for params in spec["signal"]["params_grid"]:
        bt = run_variant(spec, params, signal, data, bps=bps)
        is_stats = he.stats(_segment(bt["returns"], split, "is"))
        act = he.stats(_segment(_active(bt["returns"], inc_r), split, "is"))
        trials.append({"params": params, "bt": bt, "is": is_stats, "active_is": act})
    best = max(trials, key=lambda t: t["is"].get("sharpe_daily", -1e9))
    r = best["bt"]["returns"]
    is_s, oos_s = best["is"], he.stats(_segment(r, split, "oos"))
    inc_is, inc_oos = he.stats(_segment(inc_r, split, "is")), he.stats(_segment(inc_r, split, "oos"))
    act_is = best["active_is"]
    trial_active_srs = [t["active_is"].get("sharpe_daily", 0.0) for t in trials]

    reasons: list[str] = []
    gates: dict[str, dict] = {}
    # G1 우연보다 나은가
    pct_is = percentile_of(is_s.get("sharpe_annual", 0.0), baseline.get("is_sharpe") or [])
    g1 = pct_is is not None and pct_is >= G1_RANDOM_PCTL
    gates["G1_beats_random"] = {"pass": g1, "percentile": pct_is, "threshold": G1_RANDOM_PCTL}
    if not g1:
        reasons.append(f"G1 무작위 대비 {('—' if pct_is is None else f'{pct_is * 100:.0f}')}백분위 < {G1_RANDOM_PCTL * 100:.0f}")
    # G2 현 규칙보다 나은가(다중검정 보정)
    pool = list(prior_active_srs) + trial_active_srs
    variance = pvariance(pool) if len(pool) >= 2 else (DEFAULT_ACTIVE_SR_ANNUAL_SD / math.sqrt(TRADING_DAYS)) ** 2
    n_total = max(int(cumulative_trials), len(trials))
    dsr = hj.deflated_sharpe(act_is.get("sharpe_daily", 0.0), act_is.get("n_days", 0), act_is.get("skew", 0.0),
                             act_is.get("kurtosis", 3.0), n_total, variance)
    g2 = dsr["dsr"] >= G2_DSR
    gates["G2_beats_incumbent_deflated"] = {"pass": g2, "dsr": round(dsr["dsr"], 4), "threshold": G2_DSR,
                                            "cumulative_trials": n_total,
                                            "active_sharpe_annual": round(act_is.get("sharpe_annual", 0.0), 3)}
    if not g2:
        reasons.append(f"G2 현 규칙 대비 초과의 DSR {dsr['dsr']:.2f} < {G2_DSR} (누적 시도 {n_total})")
    # G3 떼어 둔 2년
    if split is None:
        g3 = False
        reasons.append("G3 떼어 둘 2년을 만들 만큼 기간이 길지 않음")
        gates["G3_holdout"] = {"pass": False, "split": None}
    else:
        pct_oos = percentile_of(oos_s.get("sharpe_annual", 0.0), baseline.get("oos_sharpe") or [])
        beats = oos_s.get("sharpe_annual", 0.0) > inc_oos.get("sharpe_annual", 0.0)
        g3 = beats and pct_oos is not None and pct_oos >= G3_OOS_RANDOM_PCTL
        gates["G3_holdout"] = {"pass": g3, "split": split.date().isoformat(), "oos_sharpe": round(oos_s.get("sharpe_annual", 0.0), 3),
                               "incumbent_oos_sharpe": round(inc_oos.get("sharpe_annual", 0.0), 3), "oos_random_percentile": pct_oos}
        if not g3:
            reasons.append(f"G3 떼어 둔 2년: 샤프 {oos_s.get('sharpe_annual', 0.0):.2f} vs 현 규칙 "
                           f"{inc_oos.get('sharpe_annual', 0.0):.2f}, 무작위 대비 "
                           f"{'—' if pct_oos is None else f'{pct_oos * 100:.0f}'}백분위")
    # G4 파라미터 강건성
    neighbors = hj.neighbor_params(best["params"])
    nb_srs = []
    for p in neighbors:
        bt = run_variant(spec, p, signal, data, bps=bps)
        nb_srs.append(he.stats(_segment(_active(bt["returns"], inc_r), split, "is")).get("sharpe_annual", 0.0))
    chosen = act_is.get("sharpe_annual", 0.0)
    if nb_srs:
        g4 = all(x > 0 for x in nb_srs) and median(nb_srs) >= G4_KEEP * chosen
        if not g4:
            reasons.append(f"G4 이웃 파라미터 초과 샤프 {['%.2f' % x for x in nb_srs]} (선택 {chosen:.2f})")
    else:
        g4 = True
    gates["G4_param_robust"] = {"pass": g4, "neighbor_active_sharpe": [round(x, 3) for x in nb_srs],
                                "note": None if nb_srs else "숫자 파라미터 없음 — 검사 생략"}
    # G5 위험·표본
    is_periods = sum(1 for d, _ in best["bt"]["schedule"] if split is None or pd.Timestamp(d) < split)
    mdd_ok = is_s.get("max_drawdown", 0.0) >= inc_is.get("max_drawdown", 0.0) - G5_MDD_TOLERANCE
    g5 = mdd_ok and is_periods >= MIN_IS_PERIODS
    gates["G5_risk"] = {"pass": g5, "is_mdd": round(is_s.get("max_drawdown", 0.0), 3),
                        "incumbent_is_mdd": round(inc_is.get("max_drawdown", 0.0), 3), "is_periods": is_periods}
    if not mdd_ok:
        reasons.append(f"G5 IS 최대낙폭 {is_s.get('max_drawdown', 0.0):.0%} (현 규칙 {inc_is.get('max_drawdown', 0.0):.0%})")
    if is_periods < MIN_IS_PERIODS:
        reasons.append(f"G5 IS 리밸런싱 {is_periods}회 < {MIN_IS_PERIODS}")

    last = best["bt"]["schedule"][-1] if best["bt"]["schedule"] else (None, [])
    return {
        "judge_version": JUDGE_VERSION,
        "verdict": STATUS_PASS if not reasons else STATUS_FAIL,
        "reasons": reasons,
        "gates": gates,
        "best_params": best["params"],
        "trial_active_srs": trial_active_srs,
        "trials": [{"params": t["params"], "is_sharpe": round(t["is"].get("sharpe_annual", 0.0), 3),
                    "active_is_sharpe": round(t["active_is"].get("sharpe_annual", 0.0), 3)} for t in trials],
        "stats": {"is": _round(is_s), "oos": _round(oos_s), "incumbent_is": _round(inc_is), "incumbent_oos": _round(inc_oos)},
        "split": split.date().isoformat() if split is not None else None,
        "period": [str(data.trading_days[0].date()), str(data.trading_days[-1].date())],
        "n_periods": best["bt"]["n_periods"], "avg_turnover": round(best["bt"]["avg_turnover"], 3),
        "latest_picks": {"date": last[0], "tickers": last[1]},
        "random_baseline": {"key": baseline.get("key"), "n": baseline.get("n"),
                            "is_median": round(float(np.median(baseline["is_sharpe"])), 3) if baseline.get("is_sharpe") else None},
    }


def incumbent_report(incumbent: dict, baseline: dict) -> dict:
    """현 규칙 자체가 우연보다 나은가 — 사용자가 가장 먼저 묻는 질문의 답(판정이 아니라 보고)."""
    from core import hypothesis_engine as he

    r = incumbent["returns"]
    split = holdout_split(r.index)
    is_s, oos_s, full = he.stats(_segment(r, split, "is")), he.stats(_segment(r, split, "oos")), he.stats(r)
    return {"split": split.date().isoformat() if split is not None else None,
            "stats": {"is": _round(is_s), "oos": _round(oos_s), "full": _round(full)},
            "random_percentile_is": percentile_of(is_s.get("sharpe_annual", 0.0), baseline.get("is_sharpe") or []),
            "random_percentile_oos": percentile_of(oos_s.get("sharpe_annual", 0.0), baseline.get("oos_sharpe") or []),
            "random_is_median": round(float(np.median(baseline["is_sharpe"])), 3) if baseline.get("is_sharpe") else None,
            "n_periods": incumbent["n_periods"]}


# =================================================================================================
# 등록부 (data/satellite_lab/registry.json)
# =================================================================================================

def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def migrate_registry(state_dir: Optional[Path] = None) -> Optional[str]:
    """등록부가 이전 판정 버전이면 사본을 남기고 모든 아이디어를 현재 버전으로 다시 심판 대기열에 넣는다.

    아이디어·코드·누적 시도 수는 그대로 둔다(같은 아이디어를 다른 측정으로 다시 재는 것이지 새 시도가 아니다 —
    그렇다고 시도 수를 줄이지도 않는다). 바꿨으면 보관 파일 이름, 아니면 None.
    """
    reg = load_registry(state_dir)
    old = reg.get("judge_version") or ("sat-judge/v1" if reg.get("variants") else None)
    if old is None or old == JUDGE_VERSION:
        return None
    archive = registry_path(state_dir).with_name(f"registry_{old.replace('/', '_')}.json")
    _atomic_write(archive, json.dumps(reg, ensure_ascii=False, indent=1, default=str))
    with edit_registry(state_dir) as r:
        for v in r["variants"].values():
            v.update(status=STATUS_QUEUED, result=None, attempts=0, error=None, notified=False)
        r["incumbent"] = None
        r["judge_version"] = JUDGE_VERSION
        r["migrated_from"] = {"version": old, "archive": archive.name, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return archive.name


def registry_path(state_dir: Optional[Path] = None) -> Path:
    return Path(state_dir or STATE_DIR) / "registry.json"


def load_registry(state_dir: Optional[Path] = None) -> dict:
    p = registry_path(state_dir)
    if not p.exists():
        return {"variants": {}, "cumulative_trials": 0, "incumbent": None, "updated_at": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"variants": {}, "cumulative_trials": 0, "incumbent": None, "updated_at": None}


@contextlib.contextmanager
def edit_registry(state_dir: Optional[Path] = None):
    p = registry_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        reg = load_registry(state_dir)
        if not reg.get("variants") and not reg.get("judge_version"):
            reg["judge_version"] = JUDGE_VERSION
        yield reg
        reg["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _atomic_write(p, json.dumps(reg, ensure_ascii=False, indent=1, default=str))


def read_variant_dir(d: Path) -> tuple[dict, str]:
    spec = json.loads((d / "spec.json").read_text(encoding="utf-8"))
    code = (d / "signal.py").read_text(encoding="utf-8")
    if spec.get("id") != d.name:
        raise LabSpecError(f"id 불일치({spec.get('id')} ≠ 폴더 {d.name})")
    return validate_spec(spec), code


def frozen_this_week(reg: dict, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()
    return sum(1 for v in reg["variants"].values() if v.get("origin") == "agent" and (v.get("frozen_at") or "") >= week_ago)


def freeze(spec: dict, code: str, origin: str, *, state_dir: Optional[Path] = None,
           now: Optional[datetime] = None) -> dict:
    """동결: 등록부에 스펙·코드 해시를 기록하고 시도 수를 누적한다. 이미 있으면 그대로 둔다(수정 불가)."""
    spec = validate_spec(spec)
    load_signal(code)
    now = now or datetime.now(timezone.utc)
    with edit_registry(state_dir) as reg:
        if spec["id"] in reg["variants"]:
            return reg["variants"][spec["id"]]
        if origin == "agent" and frozen_this_week(reg, now) >= WEEKLY_AGENT_FREEZE_CAP:
            raise LabSpecError(f"이번 주 에이전트 동결 상한({WEEKLY_AGENT_FREEZE_CAP}) 도달")
        is_ref = spec["id"] == INCUMBENT_ID
        n = 0 if is_ref else len(spec["signal"]["params_grid"])
        reg["cumulative_trials"] = int(reg.get("cumulative_trials", 0)) + n
        entry = {"id": spec["id"], "origin": origin, "spec": spec, "signal_code": code, "signal_sha": sha(code),
                 "frozen_at": now.isoformat(timespec="seconds"), "trials": n, "status": STATUS_QUEUED,
                 "attempts": 0, "result": None, "notified": False, "reference": is_ref}
        reg["variants"][spec["id"]] = entry
        return entry


def sync_dir(root: Path, origin: str, *, state_dir: Optional[Path] = None,
             ready: Callable[[Path], bool] = lambda d: True, log: Callable[[str], Any] = lambda s: None) -> list[str]:
    """폴더의 스펙들을 동결한다(ready 가 참인 것만). 동결한 id 목록."""
    done = []
    known = load_registry(state_dir)["variants"]
    for d in sorted(p for p in Path(root).glob("S-*") if p.is_dir()):
        if d.name in known or not (d / "spec.json").exists() or not (d / "signal.py").exists() or not ready(d):
            continue
        try:
            spec, code = read_variant_dir(d)
            freeze(spec, code, origin, state_dir=state_dir)
            done.append(d.name)
        except (LabSpecError, ValueError, SyntaxError) as exc:
            log(f"동결 거부 {d.name}: {str(exc)[:200]}")
    return done


def queue(reg: dict) -> list[dict]:
    """심판 대기(현 규칙 기준선이 먼저 필요하므로 참조 규칙 제외). R&D 센터에서 꺼진 주제의 아이디어는 기다린다(지우지 않음)."""
    from core import rnd_topics

    on = {t: rnd_topics.sat_topic_on(t) for t in TOPICS}
    return sorted((v for v in reg["variants"].values()
                   if v["status"] == STATUS_QUEUED and not v.get("reference") and on.get(v["spec"].get("topic", "selection"), True)),
                  key=lambda v: (v["origin"] != "seed", v["frozen_at"], v["id"]))


def has_work(state_dir: Optional[Path] = None, seeds_dir: Optional[Path] = None,
             variants_dir: Optional[Path] = None) -> bool:
    """심판할 것이 있는가(새로 동결될 폴더 포함). 실행기가 빈 창에서 일을 줄지 정할 때 쓴다(가벼움)."""
    reg = load_registry(state_dir)
    if queue(reg) or reg.get("incumbent") is None:
        return True
    if reg.get("variants") and (reg.get("judge_version") or "sat-judge/v1") != JUDGE_VERSION:
        return True  # 판정 버전이 바뀌어 재심판이 필요
    known = set(reg["variants"])
    for root in (seeds_dir or SEEDS_DIR, variants_dir or VARIANTS_DIR):
        for d in Path(root).glob("S-*"):
            if d.name not in known and (d / "spec.json").exists() and (d / "signal.py").exists():
                return True
    return False


def leaderboard(reg: Optional[dict] = None) -> list[dict]:
    """화면용 행: 판정된 것은 현 규칙 대비 초과 샤프 순, 대기·오류는 뒤."""
    reg = reg if reg is not None else load_registry()
    rows = []
    for v in reg["variants"].values():
        if v.get("reference"):
            continue
        res = v.get("result") or {}
        g = res.get("gates") or {}
        rows.append({
            "id": v["id"], "title": v["spec"].get("title"), "origin": v["origin"], "status": v["status"],
            "thesis": v["spec"].get("thesis"), "structure": structure_key(v["spec"]), "trials": v.get("trials"),
            "frozen_at": v.get("frozen_at"), "best_params": res.get("best_params"),
            "is_sharpe": (res.get("stats") or {}).get("is", {}).get("sharpe_annual"),
            "oos_sharpe": (res.get("stats") or {}).get("oos", {}).get("sharpe_annual"),
            "active_is_sharpe": (g.get("G2_beats_incumbent_deflated") or {}).get("active_sharpe_annual"),
            "random_pct": (g.get("G1_beats_random") or {}).get("percentile"),
            "dsr": (g.get("G2_beats_incumbent_deflated") or {}).get("dsr"),
            "gates_passed": sum(1 for x in g.values() if x.get("pass")), "n_gates": len(g),
            "reasons": res.get("reasons") or ([v.get("error")] if v.get("error") else []),
            "latest_picks": res.get("latest_picks"),
        })
    order = {STATUS_PASS: 0, STATUS_FAIL: 1, STATUS_QUEUED: 2, STATUS_ERROR: 3}
    rows.sort(key=lambda r: (order.get(r["status"], 9), -(r["active_is_sharpe"] if r["active_is_sharpe"] is not None else -9)))
    return rows


def context_markdown(reg: Optional[dict] = None) -> str:
    """에이전트가 읽는 현황(research/satellite_lab/context.md) — 무엇을 이미 시도했고 왜 떨어졌나."""
    reg = reg if reg is not None else load_registry()
    inc = reg.get("incumbent") or {}
    lines = ["# 새틀라이트 R&D 현황 (자동 생성)", "",
             f"- 판정 규칙 {JUDGE_VERSION}, 누적 시도 수 N = {reg.get('cumulative_trials', 0)} (N 이 클수록 G2 기준이 엄격해진다)",
             f"- 현 규칙(S-SEED-000) 무작위 대비 IS 백분위: {inc.get('random_percentile_is')}", "",
             "| id | 상태 | 구조 | 아이디어 | 탈락 사유 |", "|---|---|---|---|---|"]
    for r in leaderboard(reg):
        lines.append(f"| {r['id']} | {r['status']} | {r['structure']} | {str(r['thesis'])[:90]} | "
                     f"{'; '.join(r['reasons'])[:200]} |")
    return "\n".join(lines) + "\n"


# =================================================================================================
# 야간 에이전트 트랙 상태 (data/satellite_lab/agent/<id>.json — 에이전트가 쓸 수 없는 곳)
# =================================================================================================

def agent_state_path(sid: str, state_dir: Optional[Path] = None) -> Path:
    return Path(state_dir or STATE_DIR) / "agent" / f"{sid}.json"


def agent_state(sid: str, state_dir: Optional[Path] = None) -> dict:
    try:
        return json.loads(agent_state_path(sid, state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_agent_state(sid: str, st: dict, state_dir: Optional[Path] = None) -> None:
    _atomic_write(agent_state_path(sid, state_dir), json.dumps(st, ensure_ascii=False, indent=1))


def variant_hash(d: Path) -> Optional[str]:
    """spec.json + signal.py 내용 해시(둘 중 하나라도 바뀌면 다시 검사·검토)."""
    try:
        return sha((d / "spec.json").read_text(encoding="utf-8") + "\n---\n" + (d / "signal.py").read_text(encoding="utf-8"))
    except OSError:
        return None


def agent_ready(d: Path, state_dir: Optional[Path] = None) -> bool:
    """야간 배치가 결정론 검사 통과 + Critic 승인을 확인한 바로 그 내용인가."""
    st = agent_state(d.name, state_dir)
    return bool(st.get("ready_hash")) and st.get("ready_hash") == variant_hash(d) and not st.get("abandoned")


def synthetic_providers(n_tickers: int = 60, start: str = "2008-01-01", end: str = "2026-09-30", seed: int = 7):
    """검사·스모크용 합성 가격(로그 정규 랜덤워크)과 풀. 실데이터가 아니다."""
    days = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    frames = {}
    for i in range(n_tickers):
        drift, vol = rng.normal(0.0003, 0.0003), rng.uniform(0.01, 0.03)
        close = 50 * np.exp(np.cumsum(rng.normal(drift, vol, len(days))))
        frames[f"T{i:02d}"] = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                                            "Close": close, "Volume": 1e6}, index=days)
    spy = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(days))))
    frames["SPY"] = pd.DataFrame({"Open": spy, "High": spy, "Low": spy, "Close": spy, "Volume": 1e6}, index=days)
    names = sorted(t for t in frames if t != "SPY")

    def price_provider(t, s, e):
        df = frames.get(t)
        return df.loc[s:e] if df is not None else pd.DataFrame()

    def pool_provider(pool_type, d):
        return names[:40] if pool_type == "champion40" else names

    return price_provider, pool_provider


def smoke_check(spec: dict, code: str) -> str:
    """에이전트 아이디어의 결정론 검사: 스펙 계약·코드 로드·합성 데이터 4년 실행·미래 비의존성. 실패면 예외."""
    spec = validate_spec(spec)
    signal = load_signal(code)
    price_provider, pool_provider = synthetic_providers(n_tickers=30, start="2019-01-01", end="2023-12-29")
    data = build_data({spec["pool"]["type"]}, start="2021-01-01", end="2023-12-29",
                      pool_provider=pool_provider, price_provider=price_provider)
    if "fundamentals" in (spec.get("data") or []):
        from core.fundamentals_pit import SyntheticStore

        data.fundamentals = SyntheticStore()
    if "guru13f" in (spec.get("data") or []):
        from core.guru_history import SyntheticStore as GuruSynthetic

        data.guru = GuruSynthetic()
    picked = 0
    for params in spec["signal"]["params_grid"]:
        out = run_variant(spec, params, signal, data)
        picked += sum(len(p) for _, p in out["schedule"])
    if picked == 0:
        raise LabSpecError("합성 데이터 3년 동안 한 종목도 고르지 않음 — 조건이 너무 좁거나 신호가 비어 있음")
    # 미래 비의존성: 마지막 리밸런싱 이후 가격을 바꿔도 그날의 선정이 같아야 한다
    d = rebalance_dates(data.trading_days, spec["portfolio"]["hold_months"])[-1]
    cutoff = _prev_day(data.trading_days, d)
    prices = _signal_prices(data, data.pool(spec["pool"]["type"], d), cutoff, d)
    params = spec["signal"]["params_grid"][0]
    a = _call_signal(signal, spec, data, {t: df.copy() for t, df in prices.items()}, cutoff, params)
    tampered = {}
    for t, df in data.ohlcv.items():
        if t in prices:
            x = df.copy()
            x.loc[x.index > cutoff, ["Open", "High", "Low", "Close"]] *= 3.0
            tampered[t] = x
    data2 = LabData(trading_days=data.trading_days, ohlcv=tampered, closes=data.closes, pools=data.pools,
                    fundamentals=data.fundamentals, guru=data.guru)
    b = _call_signal(signal, spec, data2, _signal_prices(data2, list(prices), cutoff, d), cutoff, params)
    if pick_top(a, spec["portfolio"]["top_k"], set(prices)) != pick_top(b, spec["portfolio"]["top_k"], set(prices)):
        raise LabSpecError("리밸런싱일 이후 가격을 바꾸자 선정이 달라짐(미래 참조 의심)")
    return f"smoke ok (선정 {picked}회)"


def notification_text(entry: dict) -> str:
    res = entry.get("result") or {}
    head = "✅ 통과 — 사람 검토 대기" if entry["status"] == STATUS_PASS else (
        "❌ 탈락" if entry["status"] == STATUS_FAIL else "⚠️ 계산 오류")
    lines = [f"[새틀라이트 R&D] {entry['id']} {entry['spec'].get('title')} — {head}"]
    if res.get("gates"):
        lines.append("관문: " + " ".join(f"{k.split('_')[0]}{'○' if g.get('pass') else '×'}" for k, g in res["gates"].items()))
    for r in (res.get("reasons") or [])[:3]:
        lines.append(f"· {r}")
    if entry["status"] == STATUS_PASS:
        lines.append("챔피언에는 자동 반영되지 않습니다. 관제 센터 '새틀라이트 R&D 센터'에서 확인 후 결정하세요.")
    if entry.get("error"):
        lines.append(f"· {entry['error'][:200]}")
    return "\n".join(lines)[:1500]
