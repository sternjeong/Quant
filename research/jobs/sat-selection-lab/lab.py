"""새틀라이트 종목 선정 방식 탐색 — 세 연구(sat-pool-v1, sat-leader-v1, sat-follower-v1)가 함께 쓰는 공용 코드 (2026-10-11 사전 등록).

이 모듈은 core/satellite_lab.py 의 엔진(simulate·_signal_prices·pick_top·S-SEED-000 신호)을 그대로 쓰고,
여기에 (1) 후보 풀 만들기(시총 상위 N, 섹터 대장주, 대장주+추종주), (2) 선정 규칙, (3) 보유기간 격자 {1,3,6,12}개월,
(4) 사전 고정 판정 sat-selection-judge/v1 을 더한다. 판정 상수는 결과를 보기 전에 고정했고 바꾸려면 새 id 로 다시 등록한다.
core/*.py 는 건드리지 않는다(엔진의 현 규칙 동작 불변). 주문 경로와 연결되어 있지 않다.

규칙 요약(자세한 것은 각 연구 SPEC.md):
  * 기준선 B0 = S-SEED-000(돈치안 20일 추세 활성 + 15% 트레일링스탑 상태, 252일 모멘텀, 상위 3, 균등) on champion40_pit2, 보유 6개월.
  * 후보는 모두 같은 신호/비용(편도 8bp)/수익(Adj Close)/종가 체결, top_k=3 균등, 보유 중 청산 없음.
  * 신호는 리밸런싱일 전날까지의 자료만 쓴다(상관·변동성·수익률은 모두 '리밸런싱일 이전' 행만).
  * 보유기간은 앞 구간(2010-01~2017-05-31, 선정 구간)에서만 고르고, 뒤 구간(2017-06-01~2024-10-08, 확인 구간)에서 판정한다.
    2024-10-09 이후는 보고만 한다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import signal as _signal
import sys
import tempfile
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import pvariance
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import hypothesis_engine as he  # noqa: E402
from core import hypothesis_judge as hj  # noqa: E402
from core import research_power as rp  # noqa: E402
from core import satellite_lab as sl  # noqa: E402

RULES_VERSION = "sat-selection-judge/v1 (2026-10-11)"
JUDGE_NAME = "sat-selection-judge/v1"

# ---- 사전 고정 값 ---------------------------------------------------------------------------------
HOLDS = (1, 3, 6, 12)                      # 보유기간 격자(개월)
HOLD_MONTHS = {1: tuple(range(1, 13)), 3: (1, 4, 7, 10), 6: (1, 7), 12: (1,)}
BASELINE_HOLD = 6
TOP_K = 3
START = "2010-01-01"                       # 첫 리밸런싱은 2010-01 첫 거래일
DATA_START = "2009-12-01"                  # 2010-01 첫 거래일의 '전날'이 있도록 한 달 앞에서 읽는다
DATA_END = "2026-10-09"                    # 고정(재개해도 같은 자료)
SELECTION_END = "2017-05-31"               # 선정 구간(앞 절반) 끝
CONFIRM_START = "2017-06-01"               # 확인 구간(뒤 절반) 시작
JUDGED_END = "2024-10-08"                  # 판정 구간 끝(포함)
HOLDOUT_START = "2024-10-09"               # 보고만(소진된 구간, 규칙 3)
N_RANDOM = 500
RANDOM_SEED = 20261011
RANDOM_PCTL = 95.0
MDD_TOLERANCE = 0.05                       # 확인 구간 MDD 가 기준선보다 이 이상 나쁘면 탈락
CORR_WINDOW = 252
CORR_MIN_OBS = 200
S3_CORR = 0.6
S4_CORR = 0.7
GAP_WINDOW = 63
VOL_MULT = 1.5
ROW_FOR_SIGNAL_MIN = 50                    # 63일 변동성 계산에 필요한 최소 관측
REPRO_TOL_SHARPE = 0.05                    # 기준선 재현 허용 오차(등록부 IS 연샤프 대비)
REPRO_FIRST_RETURN_AFTER = "2010-07-01"    # 등록부 기준선은 2010-01 선정이 '전날 없음'으로 빠져 2010-07 선정부터 시작
SAFETY_SECONDS = 90
TRADING_DAYS = 252

# 코어 섹터 ETF -> GICS 섹터(현재 분류, 시점 기준 아님)
SECTOR_ETFS = {
    "XLC": "Communication Services", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLE": "Energy",
    "XLF": "Financials", "XLV": "Health Care", "XLI": "Industrials", "XLB": "Materials", "XLRE": "Real Estate",
    "XLK": "Information Technology", "XLU": "Utilities",
}
GICS_TO_ETF = {v: k for k, v in SECTOR_ETFS.items()}

# 전략 목록. kind: champion(기준선) / topn(시총 상위 N) / leaders / leaders_followers / follower_gap / follower_momentum(통제)
STRATEGIES: dict[str, dict] = {
    "B0": {"kind": "champion", "title": "기준선 S-SEED-000 on champion40_pit2(라이브 풀), 보유 6개월", "candidate": False},
    "S1_70": {"kind": "topn", "n": 70, "title": "S1 시총 상위 70(PIT S&P500), 현 규칙", "candidate": True},
    "S1_100": {"kind": "topn", "n": 100, "title": "S1 시총 상위 100(PIT S&P500), 현 규칙", "candidate": True},
    "S1_150": {"kind": "topn", "n": 150, "title": "S1 시총 상위 150(PIT S&P500), 현 규칙", "candidate": True},
    "S2": {"kind": "leaders", "scope": "held", "title": "S2 코어 보유 섹터의 대장주, 현 규칙", "candidate": True},
    "S2p": {"kind": "leaders", "scope": "all", "title": "S2p 위약: 모든 섹터의 대장주, 현 규칙", "candidate": True},
    "S3": {"kind": "leaders_followers", "scope": "held", "title": "S3 코어 보유 섹터의 대장주 + 추종주(상관 ≥ 0.6), 현 규칙", "candidate": True},
    "S3p": {"kind": "leaders_followers", "scope": "all", "title": "S3p 위약: 모든 섹터의 대장주 + 추종주, 현 규칙", "candidate": True},
    "S4": {"kind": "follower_gap", "scope": "held", "title": "S4 안전한 추종주 따라잡기(상관 ≥ 0.7, 추세 활성, 변동성 ≤ 1.5배, 격차 순)", "candidate": True},
    "S4c": {"kind": "follower_momentum", "scope": "held", "title": "S4c 통제: S4 와 같은 후보를 현 규칙(모멘텀)으로 고름", "candidate": False},
}
JOB_STRATEGIES = {
    "sat-pool-v1": ["S1_70", "S1_100", "S1_150"],
    "sat-leader-v1": ["S2", "S2p", "S3", "S3p"],
    "sat-follower-v1": ["S4"],
}
JOB_CONTROLS = {"sat-pool-v1": [], "sat-leader-v1": [], "sat-follower-v1": ["S4c"]}
JOB_TITLES = {
    "sat-pool-v1": "새틀라이트 선정: 후보 풀 확대(S&P500 시총 상위 70·100·150)",
    "sat-leader-v1": "새틀라이트 선정: 코어와 연결된 섹터 대장주·추종주(S2·S3, 위약 S2p·S3p)",
    "sat-follower-v1": "새틀라이트 선정: 안전한 추종주 따라잡기(S4) + 대장주-추종주 관계 진단(D1)",
}
# CRSP 변형(2026-10-11 범위 확장): 같은 전략·같은 판정, 자료원만 CRSP(1963~)
for _fam in ("pool", "leader", "follower"):
    JOB_STRATEGIES[f"sat-{_fam}-crsp-v1"] = JOB_STRATEGIES[f"sat-{_fam}-v1"]
    JOB_CONTROLS[f"sat-{_fam}-crsp-v1"] = JOB_CONTROLS[f"sat-{_fam}-v1"]
    JOB_TITLES[f"sat-{_fam}-crsp-v1"] = JOB_TITLES[f"sat-{_fam}-v1"] + " — CRSP 1963~2007 (상장폐지 포함)"
JOB_BACKEND = {j: ("crsp" if "-crsp-" in j else "yahoo_pit") for j in JOB_STRATEGIES}
CANDIDATES = [s for s, v in STRATEGIES.items() if v["candidate"]]
# 시도 수 = (판정 대상 전략 × 보유기간) 세 연구 합계. 통제(S4c)·기준선은 판정하지 않으므로 세지 않는다.
N_TRIALS_TOTAL = len(CANDIDATES) * len(HOLDS)

# ---- leader-follower-robust-v1 (2026-10-11 사전 등록) 추가 전략 — 모두 candidate: False 여서 위 CANDIDATES·N_TRIALS_TOTAL
# (sat-pool/leader/follower 세 연구의 공유 시도 수)에 영향이 없다. 이 연구의 시도 수·판정은 그 작업의 run.py 가 따로 계산한다.
# F(전체) = 모든 섹터의 대장주(상위 L)+추종주(상관 ≥ rho). C1=대장주만, C2=추종주만(대장주 제외), C4=상관 대신 다음 시총 순위.
LF_RHOS = (0.5, 0.6, 0.7, 0.8)
LF_LS = (1, 2, 3)
LF_CTRL_RHO, LF_CTRL_L = 0.6, 1


def lf_sid(rho: float, leaders: int, variant: str = "F") -> str:
    return f"{variant}_r{int(round(rho * 100))}_L{leaders}"


for _rho in LF_RHOS:
    for _L in LF_LS:
        STRATEGIES[lf_sid(_rho, _L, "F")] = {
            "kind": "lf", "rho": _rho, "L": _L, "variant": "F", "candidate": False,
            "title": f"LF F ρ≥{_rho} L={_L}: 모든 섹터의 대장주(상위{_L})+추종주(상관≥{_rho}), 현 규칙",
        }
for _variant, _desc in (("C1", "대장주만(추종주 제외)"), ("C2", "추종주만(대장주 제외)"), ("C4", "대장주 + 다음 시총 순위(상관 대신 크기)")):
    STRATEGIES[lf_sid(LF_CTRL_RHO, LF_CTRL_L, _variant)] = {
        "kind": "lf", "rho": LF_CTRL_RHO, "L": LF_CTRL_L, "variant": _variant, "candidate": False,
        "title": f"LF {_variant} 통제(ρ≥{LF_CTRL_RHO} L={LF_CTRL_L}): {_desc}, 현 규칙",
    }
del _rho, _L, _variant, _desc


def lf_pool_members(env: "Env", d: pd.Timestamp, sectors: list[str], rho: float, leaders: int
                    ) -> tuple[set[str], set[str], dict[str, int]]:
    """(모든 대장주 집합, 모든 추종주 집합, {섹터: 추종주 수}). 추종주는 그 섹터의 '시총 1위(L1)'와의 상관만 본다
    (SPEC 의 '더 간단한 쪽' 선택 — 섹터당 L>1 이어도 L2·L3 와는 상관을 보지 않는다)."""
    leaders_all: set[str] = set()
    followers_all: set[str] = set()
    counts: dict[str, int] = {}
    for s in sectors:
        ls = env.leaders_n(d, s, leaders)
        if not ls:
            continue
        leaders_all.update(ls)
        l1 = ls[0]
        fl = env.followers(d, s, l1, rho)
        fl = {f: c for f, c in fl.items() if f not in ls}  # L>1 인 다른 대장주가 l1 보다 작은 시총이면 추종주로 겹치지 않게 뺀다
        followers_all.update(fl)
        counts[s] = len(fl)
    return leaders_all, followers_all, counts


def lf_pool_variant(env: "Env", d: pd.Timestamp, sectors: list[str], rho: float, leaders: int, variant: str
                    ) -> list[str]:
    leaders_all, followers_all, counts = lf_pool_members(env, d, sectors, rho, leaders)
    if variant == "F":
        pool = leaders_all | followers_all
    elif variant == "C1":
        pool = set(leaders_all)
    elif variant == "C2":
        pool = set(followers_all)
    elif variant == "C4":
        pool = set(leaders_all)
        for s in sectors:
            ls = env.leaders_n(d, s, leaders)
            k = counts.get(s, 0)
            if ls and k:
                cand = [t for t in env.sector_members(d, s) if t not in ls]
                cand.sort(key=lambda t: (-env.cap(d, t), t))
                pool.update(cand[:k])
    else:
        raise ValueError(variant)
    return sorted(pool)


PASS, FAIL, FAIL_UNDERPOWERED, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "FAIL_UNDERPOWERED", "NOT_EVALUABLE"


# ---- 실행 프로필: 백엔드(자료원)마다 창이 다르다. 판정 함수는 P 를 읽는다(run_job 이 set_profile 로 고른다) ----------------
from types import SimpleNamespace  # noqa: E402

ETF_PROFILE = SimpleNamespace(name="yahoo_pit", start=START, selection_end=SELECTION_END, confirm_start=CONFIRM_START,
                              judged_end=JUDGED_END, holdout_start=HOLDOUT_START, rules_version=RULES_VERSION,
                              era="ETF 시대 2010-01~", comparison_baseline="S-SEED-000 / champion40_pit2(섹터 균형) / 6개월")
CRSP_PROFILE = SimpleNamespace(name="crsp", start="1963-07-01", selection_end="1985-12-31", confirm_start="1986-01-01",
                               judged_end="2007-12-31", holdout_start="2008-01-01",
                               rules_version="sat-selection-judge/v1-crsp (2026-10-11)",
                               era="CRSP 장기 1963-07~", comparison_baseline="현 규칙 / PIT 시총 상위 40(섹터 균형 없음) / 6개월")
P = ETF_PROFILE


def set_profile(profile) -> None:
    global P
    P = profile


class Stop(Exception):
    """시간 예산 끝, SIGTERM, 또는 --max-units-per-run — 체크포인트는 이미 저장돼 있다."""


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


# =================================================================================================
# 날짜·보유기간
# =================================================================================================

def monthly_first_days(days: pd.DatetimeIndex, start: Optional[str] = None) -> list[pd.Timestamp]:
    start = start or P.start
    s = pd.Series(days, index=days)
    firsts = s.groupby(days.to_period("M")).min()
    return [d for d in firsts if d >= pd.Timestamp(start)]


def hold_dates(monthly: list[pd.Timestamp], hold: int) -> list[pd.Timestamp]:
    months = HOLD_MONTHS[hold]
    return [d for d in monthly if d.month in months]


# =================================================================================================
# 시점 시가총액 (core.point_in_time_market_cap 의 pit2 계산과 같은 식, 가격은 리밸런싱 '전날' 종가)
# =================================================================================================

def market_cap_asof(close: pd.Series, shares_hist: pd.Series, splits: pd.Series, asof: pd.Timestamp) -> Optional[float]:
    """발행주식수(asof 까지의 최신) × 누적 분할 배율(asof 이후 분할) × asof 까지의 마지막 종가. 하나라도 없으면 None.

    asof 가 발행주식수 이력 시작보다 이르면 가장 이른 값을 쓰고 '이력 시작일 이후' 분할만 곱한다(2026-10-08 pit2 수정과 같음).
    close 는 분할 조정된 종가(get_price_history 의 Close)여야 한다."""
    if shares_hist is None or len(shares_hist) == 0 or close is None or len(close) == 0:
        return None
    px = close[close.index <= asof].dropna()
    if px.empty:
        return None
    prior = shares_hist[shares_hist.index <= asof]
    if prior.empty:
        base_ts, shares = shares_hist.index[0], float(shares_hist.iloc[0])
    else:
        base_ts, shares = asof, float(prior.iloc[-1])
    factor = 1.0
    if splits is not None and len(splits):
        for ratio in splits[splits.index > base_ts]:
            factor *= float(ratio)
    cap = float(px.iloc[-1]) * shares * factor
    return cap if math.isfinite(cap) and cap > 0 else None


def compute_caps(data: "sl.LabData", monthly: list[pd.Timestamp], shares_map: dict, splits_map: dict) -> dict[str, dict[str, float]]:
    """{리밸런싱일 ISO: {티커: 시총}} — sp500_pit·champion40 풀 구성원 모두."""
    out: dict[str, dict[str, float]] = {}
    prev = {d: _prev_day(data.trading_days, d) for d in monthly}
    closes = {t: df["Close"] for t, df in data.ohlcv.items()}
    for d in monthly:
        cut = prev[d]
        if cut is None:
            continue
        members = set(data.pool("sp500_pit", d)) | set(data.pool("champion40", d))
        row = {}
        for t in members:
            c = market_cap_asof(closes.get(t), shares_map.get(t), splits_map.get(t), cut)
            if c is not None:
                row[t] = c
        out[d.date().isoformat()] = row
    return out


def _prev_day(days: pd.DatetimeIndex, d: pd.Timestamp) -> Optional[pd.Timestamp]:
    i = days.searchsorted(d) - 1
    return days[i] if i >= 0 else None


# =================================================================================================
# 환경 (한 번 읽어 모든 전략이 공유)
# =================================================================================================

class Env:
    def __init__(self, data: "sl.LabData", caps: dict, sector_of: dict, core_held: dict,
                 signal: Callable, params: dict, pool_sizes: Optional[dict] = None,
                 sector_dated: Optional[dict] = None, all_sectors: Optional[list] = None, baseline_pool_n: Optional[int] = None):
        self.data = data
        self.days = data.trading_days
        self.closes = data.closes
        _c = data.closes
        if _c.shape[0] * _c.shape[1] > 30_000_000:   # CRSP 규모: 메모리 절약을 위해 float32 수익률(상관·변동성에는 충분)
            _a = _c.to_numpy()
            _r = np.full(_a.shape, np.nan, dtype=np.float32)
            _r[1:] = (_a[1:] / _a[:-1] - 1.0).astype(np.float32)
            self.ret = pd.DataFrame(_r, index=_c.index, columns=_c.columns)
        else:
            self.ret = _c.pct_change(fill_method=None)
        self.caps = caps                      # {date_iso: {ticker: cap}}
        self.sector_of = sector_of            # {ticker: 섹터} (시점 무관 분류 — ETF 시대)
        self.sector_dated = sector_dated      # {날짜 ISO: {ticker: 섹터}} (시점별 분류 — CRSP, 있으면 우선)
        self.all_sectors = sorted(all_sectors if all_sectors else SECTOR_ETFS)
        self.baseline_pool_n = baseline_pool_n  # None 이면 풀 제공자의 champion40, 정수면 PIT 시총 상위 N(섹터 균형 없음)
        self._members_cache: dict = {}
        self.core_held = core_held            # {date_iso: [섹터 ETF...]}
        self.signal = signal
        self.params = params
        self.pool_sizes = pool_sizes or {}
        self.monthly = monthly_first_days(self.days)
        self.prev = {d: _prev_day(self.days, d) for d in self.monthly}
        self.score_cache: dict = {}
        self.corr_cache: dict = {}
        self.b0_cache: dict = {}
        self.sma_cache: dict = {}

    # -- 기본 조회
    def pos(self, d: pd.Timestamp) -> int:
        """d 이상인 첫 거래일의 위치 — d '이전' 행은 [: pos)."""
        return int(self.days.searchsorted(d))

    def tradable(self, d: pd.Timestamp, t: str) -> bool:
        return t in self.closes.columns and pd.notna(self.closes.at[d, t])

    def cap(self, d: pd.Timestamp, t: str) -> Optional[float]:
        return self.caps.get(d.date().isoformat(), {}).get(t)

    def sector(self, t: str, d: pd.Timestamp) -> Optional[str]:
        if self.sector_dated is not None:
            return self.sector_dated.get(d.date().isoformat(), {}).get(t)
        return self.sector_of.get(t)

    def members(self, d: pd.Timestamp) -> list[str]:
        """그 시점 S&P500 편입 종목 중 d 에 거래 가능하고 시총을 아는 것."""
        if d not in self._members_cache:
            self._members_cache[d] = [t for t in self.data.pool("sp500_pit", d) if self.tradable(d, t) and self.cap(d, t) is not None]
        return list(self._members_cache[d])

    def hist_ok(self, d: pd.Timestamp, t: str) -> bool:
        df = self.data.ohlcv.get(t)
        cut = self.prev[d]
        return df is not None and cut is not None and int(df.index.searchsorted(cut, side="right")) >= sl.MIN_HISTORY_ROWS

    # -- 현 규칙 점수(추세 활성인 종목만 점수가 있다)
    def inc_scores(self, d: pd.Timestamp, tickers: list[str]) -> dict[str, float]:
        cut = self.prev[d]
        need = [t for t in tickers if (t, d) not in self.score_cache]
        if need and cut is not None:
            prices = sl._signal_prices(self.data, need, cut, d)
            elig = {t for t in prices if self.tradable(d, t)}
            scores = self.signal({t: prices[t] for t in elig}, cut, dict(self.params)) or {}
            for t in need:
                v = scores.get(t)
                try:
                    v = float(v) if v is not None else None
                except (TypeError, ValueError):
                    v = None
                self.score_cache[(t, d)] = v if (v is not None and math.isfinite(v)) else None
        elif need:
            for t in need:
                self.score_cache[(t, d)] = None
        return {t: self.score_cache[(t, d)] for t in tickers if self.score_cache.get((t, d)) is not None}

    def inc_pick(self, d: pd.Timestamp, tickers: list[str]) -> list[str]:
        scores = self.inc_scores(d, tickers)
        return sl.pick_top(scores, TOP_K, set(scores))

    def b0(self, d: pd.Timestamp) -> tuple[list[str], list[str]]:
        """(champion40 풀, 현 규칙 선정) — 폴백에도 쓴다."""
        if d not in self.b0_cache:
            pool = self.top_n(d, self.baseline_pool_n) if self.baseline_pool_n else list(self.data.pool("champion40", d))
            cut = self.prev[d]
            prices = sl._signal_prices(self.data, pool, cut, d) if cut is not None else {}
            tick = [t for t in pool if t in prices and self.tradable(d, t)]
            self.b0_cache[d] = (pool, self.inc_pick(d, tick))
        return self.b0_cache[d]

    # -- 시가총액 순위·대장주
    def top_n(self, d: pd.Timestamp, n: int) -> list[str]:
        ms = self.members(d)
        ms.sort(key=lambda t: (-self.cap(d, t), t))
        return ms[:n]

    def leaders(self, d: pd.Timestamp, sectors) -> dict[str, str]:
        """섹터 ETF -> 그 시점 S&P500 편입 종목 중 시총 최대(동률은 티커순). 구성원이 없는 섹터는 빠진다."""
        best: dict[str, tuple[float, str]] = {}
        for t in self.members(d):
            s = self.sector(t, d)
            if s is None or s not in sectors:
                continue
            key = (-self.cap(d, t), t)
            if s not in best or key < best[s]:
                best[s] = key
        return {s: v[1] for s, v in best.items()}

    def sector_members(self, d: pd.Timestamp, sector: str) -> list[str]:
        return [t for t in self.members(d) if self.sector(t, d) == sector]

    def leaders_n(self, d: pd.Timestamp, sector: str, n: int) -> list[str]:
        """그 섹터 구성원 중 시총 상위 n (동률은 티커순, 내림차순 시총). 비어 있으면 [].
        (leader-follower-robust-v1 사전 등록 — 섹터당 대장주 L 명)"""
        ms = sorted(self.sector_members(d, sector), key=lambda t: (-self.cap(d, t), t))
        return ms[:n]

    # -- 상관·수익률·변동성 (모두 d '이전' 행만)
    def corr_table(self, d: pd.Timestamp, leader: str, cands: list[str]) -> dict[str, float]:
        key = (d, leader)
        cache = self.corr_cache.setdefault(key, {})
        need = [c for c in cands if c not in cache]
        if need:
            i = self.pos(d)
            R = self.ret.iloc[max(0, i - CORR_WINDOW):i]
            if leader in R.columns:
                L = R[leader]
                for c in need:
                    if c not in R.columns:
                        cache[c] = None
                        continue
                    both = L.notna() & R[c].notna()
                    if int(both.sum()) < CORR_MIN_OBS:
                        cache[c] = None
                        continue
                    a, b = L[both].to_numpy(), R[c][both].to_numpy()
                    sa, sb = a.std(), b.std()
                    cache[c] = float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb)) if sa > 0 and sb > 0 else None
            else:
                for c in need:
                    cache[c] = None
        return {c: cache[c] for c in cands if cache.get(c) is not None}

    def followers(self, d: pd.Timestamp, sector: str, leader: str, threshold: float) -> dict[str, float]:
        """같은 섹터에서 시총이 대장주보다 작고 직전 252거래일 일수익 상관 ≥ threshold 인 종목 -> 상관."""
        lcap = self.cap(d, leader)
        cands = [t for t in self.sector_members(d, sector) if t != leader and self.cap(d, t) < lcap]
        corr = self.corr_table(d, leader, cands)
        return {t: c for t, c in corr.items() if c >= threshold}

    def ret_window(self, d: pd.Timestamp, t: str, window: int) -> Optional[float]:
        i = self.pos(d)
        if i - 1 - window < 0 or t not in self.closes.columns:
            return None
        a, b = self.closes[t].iloc[i - 1 - window], self.closes[t].iloc[i - 1]
        if pd.isna(a) or pd.isna(b) or a <= 0:
            return None
        return float(b / a - 1.0)

    def vol_window(self, d: pd.Timestamp, t: str, window: int) -> Optional[float]:
        i = self.pos(d)
        if t not in self.ret.columns:
            return None
        x = self.ret[t].iloc[max(0, i - window):i].dropna()
        return float(x.std(ddof=1)) if len(x) >= ROW_FOR_SIGNAL_MIN else None


# =================================================================================================
# 선정 규칙 (순수 — 테스트가 직접 부른다)
# =================================================================================================

def catchup_gap(leader_ret: float, follower_ret: float) -> float:
    """따라잡기 격자 = 대장주 63일 수익률 − 추종주 63일 수익률 (+ 이면 추종주가 덜 올랐다)."""
    return float(leader_ret) - float(follower_ret)


def rank_by_gap(gaps: dict[str, float], k: int = TOP_K) -> list[str]:
    """격차 내림차순(동점 티커순) 상위 k. 격차가 0 이하여도 담는다(양수 조건 없음)."""
    return sl.pick_top(gaps, k, set(gaps))


def is_safe(follower_vol: Optional[float], leader_vol: Optional[float], mult: float = VOL_MULT) -> bool:
    """'안전' = 추종주 63일 변동성 ≤ mult × 대장주 63일 변동성 (둘 다 알아야 함)."""
    if follower_vol is None or leader_vol is None or not (math.isfinite(follower_vol) and math.isfinite(leader_vol)):
        return False
    return follower_vol <= mult * leader_vol


def _scope_sectors(env: Env, spec: dict, d: pd.Timestamp) -> tuple[list[str], bool]:
    """(대상 섹터 ETF 목록, 폴백 여부). held 범위에서 코어가 섹터 ETF 를 하나도 안 들면 폴백."""
    if spec.get("scope") == "all":
        return list(env.all_sectors), False
    held = [s for s in env.core_held.get(d.date().isoformat(), []) if s in env.all_sectors]
    return sorted(held), len(held) == 0


def plan_at(env: Env, sid: str, d: pd.Timestamp) -> dict:
    """리밸런싱일 d 의 선정. 반환: pool(점수를 매기는 후보), picks, fallback, empty, rand_pool(무작위 기준선이 뽑는 풀),
    held(대상 섹터), leaders, cands({추종주: 대장주} — S4 계열), pairs({고른 추종주: 대장주})."""
    spec = STRATEGIES[sid]
    kind = spec["kind"]
    rec: dict[str, Any] = {"fallback": False, "held": [], "leaders": {}, "cands": {}, "pairs": {}}
    if kind == "lf":
        pool = lf_pool_variant(env, d, list(env.all_sectors), spec["rho"], spec["L"], spec["variant"])
        rec.update(pool=pool, picks=env.inc_pick(d, pool))
    elif kind == "champion":
        pool, picks = env.b0(d)
        rec.update(pool=pool, picks=picks)
    elif kind == "topn":
        n = env.pool_sizes.get(sid, spec["n"])
        pool = env.top_n(d, n)
        rec.update(pool=pool, picks=env.inc_pick(d, pool))
    else:
        sectors, fallback = _scope_sectors(env, spec, d)
        rec["held"] = sectors
        if fallback:
            pool, picks = env.b0(d)
            rec.update(pool=pool, picks=picks, fallback=True)
        else:
            leaders = env.leaders(d, set(sectors))
            rec["leaders"] = leaders
            if kind == "leaders":
                pool = sorted(leaders.values())
                rec.update(pool=pool, picks=env.inc_pick(d, pool))
            elif kind == "leaders_followers":
                pool, pairs = set(leaders.values()), {}
                for s, L in leaders.items():
                    for f in env.followers(d, s, L, S3_CORR):
                        pool.add(f)
                        pairs[f] = L
                pool = sorted(pool)
                picks = env.inc_pick(d, pool)
                rec.update(pool=pool, picks=picks, pairs={p: pairs[p] for p in picks if p in pairs})
            else:  # follower_gap / follower_momentum
                cands: dict[str, str] = {}
                for s, L in leaders.items():
                    fl = env.followers(d, s, L, S4_CORR)
                    if not fl:
                        continue
                    scores = env.inc_scores(d, sorted(fl))           # 점수가 있다 = 현 규칙과 같은 추세 활성
                    lvol = env.vol_window(d, L, GAP_WINDOW)
                    for f in scores:
                        if is_safe(env.vol_window(d, f, GAP_WINDOW), lvol):
                            cands[f] = L
                rec["cands"] = dict(sorted(cands.items()))
                rec["pool"] = sorted(cands)
                if kind == "follower_gap":
                    gaps = {}
                    for f, L in cands.items():
                        lr, fr = env.ret_window(d, L, GAP_WINDOW), env.ret_window(d, f, GAP_WINDOW)
                        if lr is not None and fr is not None:
                            gaps[f] = catchup_gap(lr, fr)
                    picks = rank_by_gap(gaps)
                else:
                    scores = env.inc_scores(d, sorted(cands))
                    picks = sl.pick_top(scores, TOP_K, set(scores))
                rec.update(picks=picks, pairs={p: cands[p] for p in picks})
    rec["empty"] = len(rec["picks"]) == 0
    rec["rand_pool"] = sorted(t for t in rec["pool"] if env.tradable(d, t) and env.hist_ok(d, t))
    return rec


def build_plan(env: Env, sid: str) -> dict[str, dict]:
    return {d.date().isoformat(): plan_at(env, sid, d) for d in env.monthly if env.prev[d] is not None}


def schedule_for(plan: dict, monthly: list[pd.Timestamp], hold: int) -> list[tuple[pd.Timestamp, list[str]]]:
    return [(d, list(plan[d.date().isoformat()]["picks"])) for d in hold_dates(monthly, hold) if d.date().isoformat() in plan]


def simulate_cell(env: Env, schedule: list, bps: Optional[float] = None) -> dict:
    from core.champion_strategy import SATELLITE_COST_BPS_PER_SIDE

    bps = SATELLITE_COST_BPS_PER_SIDE if bps is None else bps
    out = sl.simulate(env.closes, schedule, env.days[-1], None, bps, cache=env.sma_cache)
    return {"returns": out["returns"], "n_periods": out["n_periods"], "avg_turnover": out["avg_turnover"]}


def random_sim_stats(env: Env, plan: dict, hold: int, sid: str, i: int, bps: Optional[float] = None) -> tuple[float, float]:
    """무작위 선정 i 번째 시뮬레이션의 (선정 구간 연샤프, 확인 구간 연샤프). 시드는 (고정, 전략·보유, i)로 결정."""
    rng = np.random.default_rng([RANDOM_SEED, zlib.crc32(f"{sid}|{hold}".encode()) % 1_000_003, i])
    sched = []
    for d in hold_dates(env.monthly, hold):
        rec = plan.get(d.date().isoformat())
        if rec is None:
            continue
        el = rec["rand_pool"]
        sched.append((d, [str(x) for x in rng.choice(el, size=min(TOP_K, len(el)), replace=False)] if el else []))
    r = simulate_cell(env, sched, bps)["returns"]
    return segment_sharpe(r, "sel"), segment_sharpe(r, "conf")


# =================================================================================================
# 구간·통계
# =================================================================================================

def segment(r: pd.Series, part: str) -> pd.Series:
    if part == "sel":
        return r[r.index <= pd.Timestamp(P.selection_end)]
    if part == "conf":
        return r[(r.index >= pd.Timestamp(P.confirm_start)) & (r.index <= pd.Timestamp(P.judged_end))]
    if part == "judged":
        return r[r.index <= pd.Timestamp(P.judged_end)]
    if part == "holdout":
        return r[r.index >= pd.Timestamp(P.holdout_start)]
    raise ValueError(part)


def segment_sharpe(r: pd.Series, part: str) -> float:
    s = he.stats(segment(r, part))
    return float(s.get("sharpe_annual", float("nan")))


def info_ratio(active: pd.Series) -> float:
    """일별 활성 수익의 연 정보비율 = 평균/표준편차 × √252 (표본 30일 미만·분산 0 이면 nan)."""
    x = active.dropna()
    if len(x) < 30:
        return float("nan")
    sd = float(x.std(ddof=1))
    return float(x.mean() / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else float("nan")


def active_returns(r: pd.Series, base: pd.Series) -> pd.Series:
    return sl._active(r, base)


def finite(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


# =================================================================================================
# 판정 sat-selection-judge/v1 (순수 함수)
# =================================================================================================

def choose_hold(sel_irs: dict[int, float]) -> Optional[int]:
    """보유기간은 선정 구간의 활성 정보비율 최대로만 고른다(유한한 값만, 동률은 짧은 쪽). 없으면 None."""
    ok = [(h, v) for h, v in sel_irs.items() if finite(v)]
    if not ok:
        return None
    return max(ok, key=lambda hv: (hv[1], -hv[0]))[0]


def neighbor_holds(chosen: int, grid=HOLDS) -> tuple[list[int], str]:
    """이웃 보유기간과 규칙. 가운데면 양쪽 이웃 모두(rule='both'), 끝이면 안쪽으로 가장 가까운 두 격자 중 하나 이상(rule='any')."""
    i = list(grid).index(chosen)
    if 0 < i < len(grid) - 1:
        return [grid[i - 1], grid[i + 1]], "both"
    step = 1 if i == 0 else -1
    return [grid[i + step], grid[i + 2 * step]], "any"


def neighbors_pass(chosen: int, conf_irs: dict[int, float]) -> tuple[bool, list[int], str]:
    nb, rule = neighbor_holds(chosen)
    vals = [conf_irs.get(h) for h in nb]
    flags = [finite(v) and v > 0 for v in vals]
    return (all(flags) if rule == "both" else any(flags)), nb, rule


def decide(*, noop_reason: Optional[str], baseline_ok: bool, chosen: Optional[int], conf_active_ir: Optional[float],
           conf_sharpe: Optional[float], rand_threshold: Optional[float], conf_irs: dict[int, float],
           cand_conf_mdd: Optional[float], base_conf_mdd: Optional[float], power_conf: dict) -> tuple[str, dict]:
    """사전 고정 판정. 반환 (판정, 관문별 상세).
    (a) 확인 구간 활성 샤프(vs 기준선) > 0  (b) 확인 구간 샤프 ≥ 같은 풀·보유·top_k 무작위 500회의 95백분위
    (c) 이웃 보유기간의 확인 구간 활성 샤프도 양수  (d) 확인 구간 MDD 가 기준선보다 5%p 넘게 나쁘지 않음.
    DSR 은 통과 조건이 아니라 함께 출력한다. 무효 실행(기준선과 매일 같음)·기준선 재현 실패·계산 불가는 NOT_EVALUABLE."""
    gates: dict[str, Any] = {}
    if noop_reason:
        return NOT_EVALUABLE, {"reason": noop_reason}
    if not baseline_ok:
        return NOT_EVALUABLE, {"reason": "기준선 재현 실패(등록부 IS 샤프와 ±0.05 초과 차이) — 같은 엔진이 아님"}
    if chosen is None or not all(finite(x) for x in (conf_active_ir, conf_sharpe, cand_conf_mdd, base_conf_mdd)):
        return NOT_EVALUABLE, {"reason": "수치가 유한하지 않음(표본 부족)"}
    if rand_threshold is None or not finite(rand_threshold):
        return NOT_EVALUABLE, {"reason": "무작위 기준선 없음"}
    gates["a_active_positive"] = bool(conf_active_ir > 0)
    gates["b_beats_random_p95"] = bool(conf_sharpe >= rand_threshold)
    ok_c, nb, rule = neighbors_pass(chosen, conf_irs)
    gates["c_neighbors"] = bool(ok_c)
    gates["c_detail"] = {"neighbors": nb, "rule": rule, "conf_active_ir": {str(h): conf_irs.get(h) for h in nb}}
    gates["d_mdd_ok"] = bool(cand_conf_mdd >= base_conf_mdd - MDD_TOLERANCE)
    if all(gates[k] for k in ("a_active_positive", "b_beats_random_p95", "c_neighbors", "d_mdd_ok")):
        return PASS, gates
    return rp.classify_fail(conf_active_ir, power_conf), gates


def check_baseline_reproduction(base_returns: pd.Series, ref_sharpe: Optional[float], split: Optional[str] = None,
                                tol: float = REPRO_TOL_SHARPE) -> dict:
    """랩 기준선(S-SEED-000/champion40, 6개월)의 IS 연샤프가 등록부의 현 규칙 IS 연샤프와 ±tol 안인가.
    IS = 등록부 split 이전 수익, 등록부 첫 수익일(2010-07-01 선정 다음 날) 이후. ref 가 없으면 UNVERIFIED(검증 불가)."""
    end = pd.Timestamp(split or P.judged_end)
    r = base_returns[(base_returns.index > pd.Timestamp(REPRO_FIRST_RETURN_AFTER)) & (base_returns.index < end)]
    ours = float(he.stats(r).get("sharpe_annual", float("nan")))
    if ref_sharpe is None or not finite(ref_sharpe):
        return {"status": "UNVERIFIED", "ours": ours, "registry": None, "diff": None, "tolerance": tol,
                "note": "등록부 값을 읽지 못해 재현을 확인하지 못했다(판정은 계속하되 보고서에 표시)."}
    diff = ours - float(ref_sharpe)
    return {"status": "OK" if abs(diff) <= tol else "MISMATCH", "ours": ours, "registry": float(ref_sharpe),
            "diff": diff, "tolerance": tol, "n_days": int(len(r))}


def read_registry_reference() -> tuple[Optional[float], Optional[str]]:
    """VM 등록부(data/satellite_lab/registry.json)의 현 규칙 IS 연샤프와 split 날짜. 못 읽으면 (None, None)."""
    try:
        reg = sl.load_registry()
        inc = reg.get("incumbent") or {}
        v = ((inc.get("stats") or {}).get("is") or {}).get("sharpe_annual")
        return (float(v) if v is not None else None), inc.get("split")
    except Exception:  # noqa: BLE001
        return None, None


# =================================================================================================
# 대장주-추종주 관계 진단 D1 (판정하지 않음)
# =================================================================================================

def pair_stats(env: Env, d: pd.Timestamp, nd: Optional[pd.Timestamp], follower: str, leader: str) -> Optional[dict]:
    """d 이전 252거래일 베타·상승/하락 포착률, d→nd 보유기간(종가 대 종가) 수익률 비교."""
    i = env.pos(d)
    R = env.ret.iloc[max(0, i - CORR_WINDOW):i]
    if follower not in R.columns or leader not in R.columns:
        return None
    both = R[follower].notna() & R[leader].notna()
    if int(both.sum()) < CORR_MIN_OBS:
        return None
    f, l = R[follower][both].to_numpy(), R[leader][both].to_numpy()
    var = float(np.var(l))
    if var <= 0:
        return None
    beta = float(np.mean((f - f.mean()) * (l - l.mean())) / var)
    up, dn = l > 0, l < 0
    upcap = float(f[up].mean() / l[up].mean()) if up.any() and l[up].mean() != 0 else float("nan")
    dncap = float(f[dn].mean() / l[dn].mean()) if dn.any() and l[dn].mean() != 0 else float("nan")
    end = nd if nd is not None else env.days[-1]
    fa, fb = env.closes.at[d, follower], env.closes.at[end, follower] if end in env.closes.index else float("nan")
    la, lb = env.closes.at[d, leader], env.closes.at[end, leader] if end in env.closes.index else float("nan")
    if any(pd.isna(x) for x in (fa, fb, la, lb)) or fa <= 0 or la <= 0:
        return {"beta": beta, "upcap": upcap, "dncap": dncap, "fwd_f": None, "fwd_l": None}
    return {"beta": beta, "upcap": upcap, "dncap": dncap, "fwd_f": float(fb / fa - 1), "fwd_l": float(lb / la - 1)}


def _agg_pairs(rows: list[dict]) -> dict:
    fw = [r for r in rows if r.get("fwd_f") is not None]
    out: dict[str, Any] = {"n_pairs": len(rows), "n_with_forward": len(fw)}
    if rows:
        out["beta_mean"] = float(np.nanmean([r["beta"] for r in rows]))
        out["upcap_median"] = float(np.nanmedian([r["upcap"] for r in rows]))
        out["dncap_median"] = float(np.nanmedian([r["dncap"] for r in rows]))
    if fw:
        beat = np.array([r["fwd_f"] > r["fwd_l"] for r in fw])
        lup = np.array([r["fwd_l"] > 0 for r in fw])
        out["share_follower_beats_leader"] = float(beat.mean())
        out["mean_excess_follower_minus_leader"] = float(np.mean([r["fwd_f"] - r["fwd_l"] for r in fw]))
        out["n_leader_up"], out["n_leader_down"] = int(lup.sum()), int((~lup).sum())
        out["share_beats_when_leader_up"] = float(beat[lup].mean()) if lup.any() else None
        out["share_beats_when_leader_down"] = float(beat[~lup].mean()) if (~lup).any() else None
    return out


def diagnostics_d1(env: Env, plans: dict[str, dict], holds=HOLDS) -> dict:
    """plans: {전략: plan}. 전략별·보유기간별로 '고른 (대장주, 추종주) 쌍'과 '후보 전체 쌍'(S4 계열)을 요약."""
    out: dict[str, Any] = {}
    for sid, plan in plans.items():
        out[sid] = {}
        for h in holds:
            dates = [d for d in hold_dates(env.monthly, h) if d.date().isoformat() in plan and d <= pd.Timestamp(P.judged_end)]
            all_dates = hold_dates(env.monthly, h)
            nxt = {d: (all_dates[k + 1] if k + 1 < len(all_dates) else None) for k, d in enumerate(all_dates)}
            picked, allc = [], []
            for d in dates:
                rec = plan[d.date().isoformat()]
                for f, L in rec["pairs"].items():
                    s = pair_stats(env, d, nxt[d], f, L)
                    if s:
                        picked.append(s)
                for f, L in rec["cands"].items():
                    s = pair_stats(env, d, nxt[d], f, L)
                    if s:
                        allc.append(s)
            out[sid][str(h)] = {"picked_pairs": _agg_pairs(picked), "all_candidate_pairs": _agg_pairs(allc)}
    return out


# =================================================================================================
# 체크포인트
# =================================================================================================

def atomic_pickle(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_ckpt(path: Path, fingerprint: dict):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)  # 이 스크립트가 쓴 파일만 읽는다
    except Exception:  # noqa: BLE001
        return None
    return obj["payload"] if isinstance(obj, dict) and obj.get("fingerprint") == fingerprint else None


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


class Budget:
    """새로 하는 계산 단위(전략 계획·셀 시뮬레이션·무작위 묶음)를 세고 시간 예산·SIGTERM·단위 상한에서 Stop."""

    def __init__(self, max_units: int = 0):
        raw = os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH")
        self.deadline = (float(raw) if raw else time.time() + 3 * 3600) - SAFETY_SECONDS
        self.max_units = max_units
        self.units = 0
        self.flag = False

    def check(self) -> None:
        if self.flag or time.time() > self.deadline or (self.max_units and self.units >= self.max_units):
            raise Stop()

    def done(self) -> None:
        self.units += 1


# =================================================================================================
# 입력: 실데이터 / 합성(스모크)
# =================================================================================================

def _pool_wrapper(base: Callable, start_d: date) -> Callable:
    return lambda pt, d: [] if d < start_d else base(pt, d)


def real_static_and_data(log_fn: Callable, ck: Path, fp: dict) -> tuple["sl.LabData", dict]:
    """실데이터: 가격은 캐시에서 매번 읽고, 시총·섹터·코어 보유는 한 번 계산해 체크포인트에 저장한다."""
    from concurrent.futures import ThreadPoolExecutor

    from core import champion_strategy as cs
    from core import point_in_time_market_cap as pm
    from core import screener

    pool = _pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40", "sp500_pit"}, start=DATA_START, end=DATA_END, pool_provider=pool, log=log_fn)
    static = load_ckpt(ck / "static.pkl", fp)
    if static is None:
        monthly = monthly_first_days(data.trading_days)
        tickers = sorted(data.ohlcv)
        log_fn(f"발행주식수·분할 읽는 중({len(tickers)}종목)")

        def _splits(t):
            try:
                import yfinance as yf

                s = yf.Ticker(t).splits
                if s is None or s.empty:
                    return pd.Series(dtype=float)
                idx = pd.DatetimeIndex(s.index)
                if getattr(idx, "tz", None) is not None:
                    idx = idx.tz_localize(None)
                return pd.Series(s.values, index=idx)
            except Exception:  # noqa: BLE001
                return pd.Series(dtype=float)

        with ThreadPoolExecutor(max_workers=8) as ex:
            shares = dict(zip(tickers, ex.map(lambda t: pm.get_shares_outstanding_history(t), tickers)))
            splits = dict(zip(tickers, ex.map(_splits, tickers)))
        caps = compute_caps(data, monthly, shares, splits)
        uni = screener.get_universe(use_cache=True)
        sector_of = {}
        for sym, sec in zip(uni["Symbol"], uni["Sector"]):
            etf = GICS_TO_ETF.get(sec)
            if etf:
                sector_of[he.price_symbol(str(sym))] = etf
        log_fn("코어 백테스트(일별 목표 비중 — 보유 섹터 ETF)")
        w = cs.run_core_backtest(START)["weights"]
        core_held = held_sectors_from_weights(w, monthly)
        static = {"caps": caps, "sector_of": sector_of, "core_held": core_held,
                  "meta": {"strategy_version": cs.CHAMPION_STRATEGY_VERSION, "core_universe": list(w.columns),
                           "n_sector_tickers": len(sector_of), "cap_coverage": cap_coverage(caps, data)}}
        atomic_pickle(ck / "static.pkl", {"fingerprint": fp, "payload": static})
        log_fn("시총·섹터·코어 보유 체크포인트 저장")
    return data, static


def held_sectors_from_weights(w: pd.DataFrame, monthly: list[pd.Timestamp]) -> dict[str, list[str]]:
    """코어 일별 목표 비중에서 리밸런싱일 d 행(전날 종가 신호로 정해진 비중)에 비중 > 0 인 섹터 ETF."""
    out = {}
    for d in monthly:
        sub = w.loc[:d]
        if sub.empty:
            out[d.date().isoformat()] = []
            continue
        row = sub.iloc[-1]
        out[d.date().isoformat()] = sorted(s for s in SECTOR_ETFS if s in row.index and float(row[s]) > 1e-9)
    return out


def cap_coverage(caps: dict, data: "sl.LabData") -> dict:
    """리밸런싱일마다 편입 종목 중 시총을 아는 비율의 평균(결측 = 상장폐지·주식수 없음)."""
    fr = []
    for k, row in caps.items():
        d = pd.Timestamp(k)
        mem = data.pool("sp500_pit", d)
        if mem:
            fr.append(sum(1 for t in mem if t in row) / len(mem))
    return {"mean": float(np.mean(fr)) if fr else None, "min": float(np.min(fr)) if fr else None}


def synthetic_world(seed: int = 11, start: str = "2008-06-02", end: str = "2026-06-30", per_sector: int = 6) -> dict:
    """스모크·테스트용 합성 세계: 섹터 요인 + 개별 잡음(같은 섹터 종목끼리 상관이 생긴다), 시총 순위가 시간에 따라 바뀐다."""
    days = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    n = len(days)
    market = rng.normal(0.0002, 0.006, n)
    sec = list(SECTOR_ETFS)
    factor = rng.normal(0.0002, 0.009, (n, len(sec)))
    frames, sector_of, shares, join = {}, {}, {}, {}
    names = []
    for si, etf in enumerate(sec):
        for k in range(per_sector):
            t = f"S{si:02d}{k}"
            names.append(t)
            r = 0.8 * market + rng.uniform(0.6, 1.4) * factor[:, si] + rng.normal(0.0, rng.uniform(0.005, 0.014), n)
            close = 50 * np.exp(np.cumsum(r))
            frames[t] = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                                      "Adj Close": close, "Volume": 1e6}, index=days)
            sector_of[t] = etf
            shares[t] = pd.Series([float(np.exp(rng.uniform(np.log(1e8), np.log(5e9))))], index=[days[0]])
            join[t] = pd.Timestamp("2014-01-02") if k == per_sector - 1 else pd.Timestamp("2000-01-01")
    spy = 100 * np.exp(np.cumsum(0.8 * market + rng.normal(0.0001, 0.003, n)))
    frames["SPY"] = pd.DataFrame({"Open": spy, "High": spy, "Low": spy, "Close": spy, "Adj Close": spy, "Volume": 1e6}, index=days)
    names = sorted(names)
    champion = names[: min(40, len(names))]

    def price_provider(t, s, e):
        df = frames.get(t)
        return df.loc[s:e] if df is not None else pd.DataFrame()

    def pool_provider(pool_type, d):
        if pool_type == "champion40":
            return [t for t in champion if pd.Timestamp(d) >= join[t]]
        return [t for t in names if pd.Timestamp(d) >= join[t]]

    # 코어 보유: 매월 번갈아 섹터 ETF 1~4개, 일부 달은 섹터 ETF 없음(폴백 경로)
    idx = days[days >= pd.Timestamp(START)]
    cw = pd.DataFrame(0.0, index=idx, columns=sorted(SECTOR_ETFS) + ["TLT", "GLD"])
    ym = pd.Series(idx.year * 12 + idx.month, index=idx)
    for m in sorted(ym.unique()):
        mask = (ym == m).to_numpy()
        pattern = int(m) % 5
        if pattern == 0:
            cw.loc[mask, "TLT"] = 0.5
            cw.loc[mask, "GLD"] = 0.5
        else:
            held = [sec[(int(m) + j) % len(sec)] for j in range(pattern)]
            for s_ in held:
                cw.loc[mask, s_] = 0.25
    return {"price_provider": price_provider, "pool_provider": pool_provider, "shares": shares, "sector_of": sector_of,
            "core_weights": cw, "end": end}


def smoke_static_and_data(log_fn: Callable) -> tuple["sl.LabData", dict]:
    w = synthetic_world()
    pool = _pool_wrapper(w["pool_provider"], date.fromisoformat(START))
    data = sl.build_data({"champion40", "sp500_pit"}, start=DATA_START, end=w["end"], pool_provider=pool,
                         price_provider=w["price_provider"], log=log_fn)
    monthly = monthly_first_days(data.trading_days)
    splits = {t: pd.Series(dtype=float) for t in w["shares"]}
    caps = compute_caps(data, monthly, w["shares"], splits)
    static = {"caps": caps, "sector_of": w["sector_of"], "core_held": held_sectors_from_weights(w["core_weights"], monthly),
              "meta": {"synthetic": True, "cap_coverage": cap_coverage(caps, data)}}
    return data, static


class Backend:
    """자료 계층 인터페이스. load() 는 (sl.LabData, static) 을 돌려준다.
    LabData: trading_days / ohlcv{티커: DataFrame(Close…)} / closes(수익용 총수익 가격) / pool("sp500_pit"|"champion40", 날짜).
    static: caps{리밸런싱일 ISO: {티커: PIT 시총}}, 섹터(sector_of 고정 분류 또는 sector_dated 시점 분류), core_held{ISO: [코어가 든 섹터]},
    all_sectors, baseline_pool_n(None=풀 제공자의 champion40), meta. 구현: yahoo_pit(ETF 시대), crsp(1963~)."""

    name = ""

    def load(self, log_fn: Callable, ck: Path, fp: dict, smoke: bool):  # pragma: no cover - 인터페이스
        raise NotImplementedError


class YahooPitBackend(Backend):
    name = "yahoo_pit"

    def load(self, log_fn, ck, fp, smoke):
        static_data = smoke_static_and_data(log_fn) if smoke else real_static_and_data(log_fn, ck, fp)
        data, static = static_data
        static.setdefault("all_sectors", sorted(SECTOR_ETFS))
        return data, static


class CrspBackend(Backend):
    name = "crsp"

    def load(self, log_fn, ck, fp, smoke):
        import importlib.util

        spec_ = importlib.util.spec_from_file_location("sat_selection_crsp", Path(__file__).resolve().parent / "crsp.py")
        crsp = sys.modules.setdefault("sat_selection_crsp", importlib.util.module_from_spec(spec_))
        if not hasattr(crsp, "build_bundle"):
            spec_.loader.exec_module(crsp)
        directory = crsp.CRSP_DIR
        if smoke:
            directory = ck / "smoke_crsp"
            if not (directory / "daily.csv").exists():
                crsp.write_synthetic(directory)
        data = static = None
        cached = load_ckpt(ck / "crsp_static.pkl", fp)
        data, bundle = crsp.build_bundle(directory, start=P.start, log=log_fn)
        if cached is None:
            monthly = bundle["monthly"]
            cl = crsp.load_core_longrun_lab()
            if smoke:
                syn = cl.synthetic_data(n12=12, n49=16, start="1960-01-01", end="2012-12-31")
                ind12 = syn["ind12"].copy()
                ind12.columns = list(crsp.FF12_NAMES)
                mkt = syn["mkt"]
            else:
                real = cl.load_real()
                ind12, mkt = real["ind12"], real["mkt"]
            held = crsp.industry_core_held(monthly, ind12, mkt, cl)
            cached = {"core_held": held, "all_sectors": list(crsp.FF12_NAMES)}
            atomic_pickle(ck / "crsp_static.pkl", {"fingerprint": fp, "payload": cached})
        static = {"caps": bundle["caps"], "sector_dated": bundle["sector_dated"], "sector_of": {}, "core_held": cached["core_held"],
                  "all_sectors": cached["all_sectors"], "baseline_pool_n": 40, "meta": bundle["meta"]}
        return data, static


BACKENDS = {"yahoo_pit": YahooPitBackend(), "crsp": CrspBackend()}


def crsp_inputs_fingerprint(directory) -> dict:
    out = {}
    for fname in ("daily.csv", "names.csv", "delists.csv", "sp500.csv"):
        p = Path(directory) / fname
        out[fname] = [p.stat().st_size, int(p.stat().st_mtime)] if p.exists() else None
    return out


def write_missing_data_outputs(out: Path, job_id: str, problems: list[str], crsp_mod) -> None:
    payload = {"id": job_id, "verdicts": {"study": "NOT_EVALUABLE_DATA"}, "smoke": False, "input_status": "CRSP_EXPORT_NOT_FOUND",
               "problems": problems, "expected_dir": "data/research_inputs/crsp_sp500",
               "expected_files": sorted(crsp_mod.FILES), "required_columns": crsp_mod.FILES,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    atomic_write(out / "results.json", json.dumps(payload, ensure_ascii=False, indent=2))
    atomic_write(out / "REPORT.md", f"# {JOB_TITLES[job_id]}\n\n판정: **NOT_EVALUABLE_DATA** — CRSP 내보내기 파일이 준비되지 않았다. 판정은 수행하지 않았다.\n\n"
                 "문제: " + "; ".join(problems) + "\n\n## 필요한 파일 (VM 의 data/research_inputs/crsp_sp500/)\n\n```\n" + crsp_mod.EXTRACTION_SPEC + "```\n\n"
                 "파일을 둔 뒤 `python scripts/research_jobs_admin.py retry " + job_id + " --fresh` 로 다시 돌린다.\n")


def make_env(data: "sl.LabData", static: dict, smoke: bool) -> Env:
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    sizes = {"S1_70": 20, "S1_100": 30, "S1_150": 45} if smoke else None
    return Env(data, static["caps"], static.get("sector_of") or {}, static["core_held"], sl.load_signal(code),
               dict(spec["signal"]["params_grid"][0]), pool_sizes=sizes, sector_dated=static.get("sector_dated"),
               all_sectors=static.get("all_sectors"), baseline_pool_n=static.get("baseline_pool_n"))


# =================================================================================================
# 분석
# =================================================================================================

def _stats_block(r: pd.Series, base: pd.Series, part: str) -> dict:
    seg = segment(r, part)
    s = he.stats(seg)
    act = active_returns(r, base)
    return {"n_days": int(s.get("n_days", 0)), "sharpe": s.get("sharpe_annual"), "ann_return": s.get("ann_return"),
            "mdd": s.get("max_drawdown"), "active_ir": info_ratio(segment(act, part))}


def overlap_with_b0(plan: dict, b0_plan: dict, dates: list[pd.Timestamp]) -> Optional[float]:
    vals = []
    for d in dates:
        k = d.date().isoformat()
        if k in plan and k in b0_plan and plan[k]["picks"]:
            vals.append(len(set(plan[k]["picks"]) & set(b0_plan[k]["picks"])) / len(plan[k]["picks"]))
    return float(np.mean(vals)) if vals else None


def analyze(env: Env, plans: dict, cells: dict, randoms: dict, job_id: str, candidates: list[str], controls: list[str],
            repro: dict, smoke: bool, d1: Optional[dict] = None) -> tuple[dict, str]:
    """plans {sid: plan}, cells {(sid, hold): 셀}, randoms {(sid, hold): {'sel': [...], 'conf': [...]}}."""
    base_r = cells[("B0", BASELINE_HOLD)]["returns"]
    base_conf = he.stats(segment(base_r, "conf"))
    base_judged = segment(base_r, "judged")
    years_conf = (pd.Timestamp(P.judged_end) - pd.Timestamp(P.confirm_start)).days / 365.25
    years_full = (pd.Timestamp(P.judged_end) - base_r.index[0]).days / 365.25
    power_conf = rp.power_report(years_conf, N_TRIALS_TOTAL)
    power_full = rp.power_report(years_full, N_TRIALS_TOTAL)
    baseline_ok = repro["status"] != "MISMATCH"

    # 셀별 지표
    table: dict[str, dict] = {}
    full_srs = []   # 시도들의 전체 판정 창 활성 일 샤프(DSR 분산용)
    for sid in candidates + controls:
        table[sid] = {}
        for h in HOLDS:
            c = cells[(sid, h)]
            r = c["returns"]
            b_same = cells[("B0", h)]["returns"]
            dates = [d for d in hold_dates(env.monthly, h) if d <= pd.Timestamp(P.judged_end) and d.date().isoformat() in plans[sid]]
            recs = [plans[sid][d.date().isoformat()] for d in dates]
            row = {
                "sel": _stats_block(r, base_r, "sel"), "conf": _stats_block(r, base_r, "conf"),
                "holdout": _stats_block(r, base_r, "holdout"),
                "conf_vs_same_hold_baseline_ir": info_ratio(segment(active_returns(r, b_same), "conf")),
                "sel_vs_same_hold_baseline_ir": info_ratio(segment(active_returns(r, b_same), "sel")),
                "avg_turnover": c["avg_turnover"], "n_periods": c["n_periods"],
                "overlap_with_b0": overlap_with_b0(plans[sid], plans["B0"], dates),
                "fallback_share": float(np.mean([x["fallback"] for x in recs])) if recs else None,
                "empty_share": float(np.mean([x["empty"] for x in recs])) if recs else None,
                "avg_picks": float(np.mean([len(x["picks"]) for x in recs])) if recs else None,
            }
            rd = randoms.get((sid, h))
            if rd and rd.get("conf"):
                dist = [x for x in rd["conf"] if finite(x)]
                row["random"] = {"n": len(dist), "conf_median": float(np.median(dist)) if dist else None,
                                 "conf_p95": float(np.percentile(dist, RANDOM_PCTL)) if dist else None,
                                 "conf_pctl_of_candidate": sl.percentile_of(row["conf"]["sharpe"], dist) if finite(row["conf"]["sharpe"]) else None}
            table[sid][h] = row
            if sid in candidates:
                act_j = segment(active_returns(r, base_r), "judged")
                s = he.stats(act_j)
                if "sharpe_daily" in s:
                    full_srs.append(s["sharpe_daily"])
    var_pool = pvariance(full_srs) if len(full_srs) >= 2 else (sl.DEFAULT_ACTIVE_SR_ANNUAL_SD / math.sqrt(TRADING_DAYS)) ** 2

    verdicts, detail = {}, {}
    for sid in candidates:
        sel_irs = {h: table[sid][h]["sel"]["active_ir"] for h in HOLDS}
        conf_irs = {h: table[sid][h]["conf"]["active_ir"] for h in HOLDS}
        chosen = choose_hold(sel_irs)
        noop = None
        dsr = None
        rec_row: dict[str, Any] = {}
        if chosen is not None:
            r = cells[(sid, chosen)]["returns"]
            act_j = segment(active_returns(r, base_r), "judged")
            noop = rp.noop_guard(act_j.to_numpy())
            st = he.stats(act_j)
            dsr = hj.deflated_sharpe(st.get("sharpe_daily", 0.0), st.get("n_days", 0), st.get("skew", 0.0),
                                     st.get("kurtosis", 3.0), N_TRIALS_TOTAL, var_pool)
            dsr = {**dsr, "dsr": round(float(dsr["dsr"]), 4), "n_trials": N_TRIALS_TOTAL, "active_sharpe_annual": st.get("sharpe_annual"),
                   "n_days": st.get("n_days")}
            row = table[sid][chosen]
            rd = randoms.get((sid, chosen)) or {}
            dist = [x for x in rd.get("conf", []) if finite(x)]
            thr = float(np.percentile(dist, RANDOM_PCTL)) if dist else None
            verdict, gates = decide(
                noop_reason=noop, baseline_ok=baseline_ok, chosen=chosen, conf_active_ir=row["conf"]["active_ir"],
                conf_sharpe=row["conf"]["sharpe"], rand_threshold=thr, conf_irs=conf_irs,
                cand_conf_mdd=row["conf"]["mdd"], base_conf_mdd=base_conf.get("max_drawdown"), power_conf=power_conf)
            rec_row = {"random_threshold_p95": thr}
        else:
            verdict, gates = NOT_EVALUABLE, {"reason": "선정 구간 활성 정보비율을 구할 수 없음"}
        verdicts[sid] = verdict
        detail[sid] = {"chosen_hold": chosen, "selection_active_ir": {str(h): v for h, v in sel_irs.items()},
                       "confirmation_active_ir": {str(h): v for h, v in conf_irs.items()}, "gates": gates, "dsr_full_window": dsr,
                       "noop_guard": noop, **rec_row}
    verdict_out = {k: (f"SMOKE_ONLY({v})" if smoke else v) for k, v in verdicts.items()}
    result = {
        "kind": "pre-registered verdict", "id": job_id, "rules_version": P.rules_version, "judge": JUDGE_NAME, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rules": {"holds": list(HOLDS), "baseline_hold": BASELINE_HOLD, "top_k": TOP_K, "selection_end": P.selection_end,
                  "confirmation_start": P.confirm_start, "judged_end": P.judged_end, "holdout_start": P.holdout_start, "data_end": DATA_END,
                  "n_random": N_RANDOM, "random_seed": RANDOM_SEED, "random_percentile": RANDOM_PCTL, "mdd_tolerance": MDD_TOLERANCE,
                  "corr_window": CORR_WINDOW, "s3_corr": S3_CORR, "s4_corr": S4_CORR, "gap_window": GAP_WINDOW, "vol_mult": VOL_MULT,
                  "n_trials_total": N_TRIALS_TOTAL, "bps_one_way": 8.0},
        "strategies": {sid: STRATEGIES[sid]["title"] for sid in candidates + controls},
        "baseline_reproduction": repro, "power": {"confirmation": power_conf, "full": power_full},
        "dsr_variance_daily": var_pool, "table": {sid: {str(h): v for h, v in rows.items()} for sid, rows in table.items()},
        "detail": detail, "verdicts": verdict_out, "verdicts_raw": verdicts,
        "baseline": {"confirmation": _stats_block(base_r, base_r, "conf"), "selection": _stats_block(base_r, base_r, "sel"),
                     "holdout": _stats_block(base_r, base_r, "holdout"),
                     "same_hold": {str(h): {"sel": _stats_block(cells[("B0", h)]["returns"], base_r, "sel"),
                                            "conf": _stats_block(cells[("B0", h)]["returns"], base_r, "conf")} for h in HOLDS}},
        "b0_random": {str(h): {"conf_median": float(np.median([x for x in randoms[("B0", h)]["conf"] if finite(x)])),
                               "n": len(randoms[("B0", h)]["conf"])} for h in HOLDS if ("B0", h) in randoms and randoms[("B0", h)].get("conf")},
        "fallback_note": "S2·S3·S4(held 범위)는 코어가 섹터 ETF 를 하나도 들지 않은 달에 현 규칙 champion40 선정으로 대체(폴백).",
        "meta": {**static_meta(env), **getattr(env, "static_meta", {})},
    }
    if d1 is not None:
        result["diagnostic_D1"] = d1
    return result, build_report(result, job_id, candidates, controls)


def static_meta(env: Env) -> dict:
    return {"n_monthly_dates": len(env.monthly), "n_sector_tickers": len(env.sector_of),
            "n_dates_with_held_sectors": sum(1 for v in env.core_held.values() if v),
            "n_dates_total": len(env.core_held)}


def pct(x, signed: bool = False) -> str:
    if not finite(x):
        return "—"
    return f"{x:+.1%}" if signed else f"{x:.1%}"


def num(x, nd: int = 2) -> str:
    return "—" if not finite(x) else f"{x:.{nd}f}"


def build_report(r: dict, job_id: str, candidates: list[str], controls: list[str]) -> str:
    smoke = r["smoke"]
    rp_ = r["baseline_reproduction"]
    L = [f"# {JOB_TITLES[job_id]}{' (스모크 — 합성 데이터)' if smoke else ''}", "",
         f"사전 고정 판정 {JUDGE_NAME}. 판정 구간 {P.start[:7]} ~ {P.judged_end}(선정 구간 ~{P.selection_end} / 확인 구간 {P.confirm_start}~). "
         f"{P.holdout_start} 이후는 보고만(소진된 구간).", "",
         "## 판정", ""]
    for sid in candidates:
        d = r["detail"][sid]
        v = r["verdicts"][sid]
        g = d["gates"]
        dsr = d.get("dsr_full_window") or {}
        L.append(f"- **{sid}** {STRATEGIES[sid]['title']}: **{v}** — 선정 구간에서 고른 보유기간 {d['chosen_hold']}개월")
        if "a_active_positive" in g:
            L.append(f"  - (a) 확인 구간 활성 샤프 {num(r['table'][sid][str(d['chosen_hold'])]['conf']['active_ir'])} > 0: {g['a_active_positive']} · "
                     f"(b) 확인 구간 샤프 ≥ 무작위 95백분위({num(d.get('random_threshold_p95'))}): {g['b_beats_random_p95']} · "
                     f"(c) 이웃 보유기간 {g['c_detail']['neighbors']}({g['c_detail']['rule']}) 활성 샤프 양수: {g['c_neighbors']} · "
                     f"(d) MDD 기준선 대비 −5%p 이내: {g['d_mdd_ok']}")
        else:
            L.append(f"  - {g.get('reason')}")
        L.append(f"  - DSR(전체 판정 창 {r['power']['full']['years']}년, 시도 {dsr.get('n_trials', N_TRIALS_TOTAL)}개): {num(dsr.get('dsr'), 3)} "
                 f"(통과 조건 아님, 참고) · 확인 구간 MDE 연 IR {r['power']['confirmation']['mde_ir']:.2f} · 전체 창 MDE 연 IR {r['power']['full']['mde_ir']:.2f}")
    L += ["", rp.power_line(r["power"]["confirmation"]).replace("검정력(사전 계산)", "확인 구간 검정력(사전 계산)"),
          rp.power_line(r["power"]["full"]).replace("검정력(사전 계산)", "전체 판정 창 검정력(사전 계산)"), "",
          f"시도 수(세 연구 합계) = 판정 대상 전략 {len(CANDIDATES)}개 × 보유기간 {len(HOLDS)}개 = **{N_TRIALS_TOTAL}**. "
          "PASS_FORWARD_CANDIDATE 는 '전진 원장에 올릴 후보'일 뿐이다(core/forward_tournament_v2.py 후보는 이미 고정되어 있어 이 연구가 바꾸지 않는다). "
          "엔진 반영은 사용자 확인 뒤 별도 작업.", "",
          "## 기준선 재현", "",
          f"- 랩 기준선 {P.comparison_baseline} 의 IS 연샤프 {num(rp_.get('ours'), 3)} vs 등록부 {num(rp_.get('registry'), 3)} "
          f"→ 차이 {num(rp_.get('diff'), 3)} (허용 ±{rp_['tolerance']}) = **{rp_['status']}**. {rp_.get('note', '')}", ""]
    b = r["baseline"]
    L += [f"- 기준선 확인 구간: 샤프 {num(b['confirmation']['sharpe'])}, 연수익 {pct(b['confirmation']['ann_return'])}, MDD {pct(b['confirmation']['mdd'])} · "
          f"선정 구간 샤프 {num(b['selection']['sharpe'])} · 떼어 둔 구간(보고) 샤프 {num(b['holdout']['sharpe'])}", ""]
    if r.get("b0_random"):
        L += ["- 같은 구조 무작위(champion40, top 3)의 확인 구간 샤프 중앙값: " +
              ", ".join(f"{h}개월 {num(v['conf_median'])}" for h, v in r["b0_random"].items()), ""]
    L += ["## 전략 × 보유기간", "",
          "활성 샤프 = 일별 (후보 − 기준선 B0 6개월)의 연 정보비율. '같은 보유기간 기준선 대비'는 같은 보유기간의 champion40 현 규칙과 비교한 값(보유기간 효과 분리용). "
          "무작위 백분위 = 후보 확인 구간 샤프가 같은 풀·보유기간 무작위 선정 분포에서 차지하는 위치. 겹침 = 후보 종목이 기준선 종목과 겹친 평균 비율. "
          "폴백 = 코어에 섹터 ETF 가 없어 현 규칙 선정으로 대체한 비율. 빈 선정 = 종목이 하나도 없어 현금이던 비율.", ""]
    for sid in candidates + controls:
        L += [f"### {sid} — {STRATEGIES[sid]['title']}", "",
              "| 보유 | 선정 활성샤프 | 확인 활성샤프 | (같은 보유 기준선 대비 선정/확인) | 확인 샤프 | 확인 연수익 | 확인 MDD | 무작위 중앙/p95 | 후보 무작위 백분위 | 회전율 | 겹침 | 폴백 | 빈 선정 | 평균 종목수 | 떼어 둔 구간(보고) 활성샤프/샤프 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        ch = r["detail"].get(sid, {}).get("chosen_hold")
        for h in HOLDS:
            x = r["table"][sid][str(h)]
            rd = x.get("random") or {}
            mark = " ★" if h == ch else ""
            L.append(f"| {h}개월{mark} | {num(x['sel']['active_ir'])} | {num(x['conf']['active_ir'])} | "
                     f"{num(x['sel_vs_same_hold_baseline_ir'])} / {num(x['conf_vs_same_hold_baseline_ir'])} | {num(x['conf']['sharpe'])} | "
                     f"{pct(x['conf']['ann_return'])} | {pct(x['conf']['mdd'])} | {num(rd.get('conf_median'))} / {num(rd.get('conf_p95'))} | "
                     f"{pct(rd.get('conf_pctl_of_candidate'))} | {num(x['avg_turnover'])} | {pct(x['overlap_with_b0'])} | {pct(x['fallback_share'])} | "
                     f"{pct(x['empty_share'])} | {num(x['avg_picks'])} | {num(x['holdout']['active_ir'])} / {num(x['holdout']['sharpe'])} |")
        L.append("")
    if "diagnostic_D1" in r:
        L += ["## 진단 D1 — 추종주가 대장주를 따라잡는가 (판정 아님)", "",
              "고른 (대장주, 추종주) 쌍과 후보 전체 쌍(상관 ≥ 0.7·추세 활성·안전 필터 통과)에 대해: 직전 252거래일 베타, 상승/하락 포착률(추종주 평균 수익 ÷ 대장주 평균 수익, 대장주 상승일/하락일), "
              "그리고 리밸런싱일 종가 → 다음 리밸런싱일 종가 보유기간에 추종주 수익률이 대장주를 넘었는지(전체, 대장주가 오른 기간, 내린 기간). 판정 구간(~2024-10-08) 쌍만.", ""]
        for sid, byh in r["diagnostic_D1"].items():
            L += [f"### {sid}", "", "| 보유 | 구분 | 쌍 수(전방 수익 있음) | 베타 평균 | 상승 포착 중앙 | 하락 포착 중앙 | 추종주>대장주 | 대장주 상승기 | 대장주 하락기 | 평균 초과(추종−대장) |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for h, parts in byh.items():
                for lab_, key in (("고른 쌍", "picked_pairs"), ("후보 전체", "all_candidate_pairs")):
                    a = parts[key]
                    L.append(f"| {h}개월 | {lab_} | {a['n_pairs']} ({a['n_with_forward']}) | {num(a.get('beta_mean'))} | {num(a.get('upcap_median'))} | "
                             f"{num(a.get('dncap_median'))} | {pct(a.get('share_follower_beats_leader'))} | {pct(a.get('share_beats_when_leader_up'))} | "
                             f"{pct(a.get('share_beats_when_leader_down'))} | {pct(a.get('mean_excess_follower_minus_leader'), True)} |")
            L.append("")
    m = r["meta"]
    L += ["## 이 연구가 증명하는 것과 증명하지 못하는 것", "",
          "- 증명하는 것: 선정 구간에서 보유기간을 고르고 확인 구간에서 같은 규칙이 기준선·무작위보다 나았는지(또는 아닌지)에 대한 과거 자료상의 증거. "
          "PASS 라도 '앞으로 쌓이는 전진 원장에 올릴 후보'일 뿐 수익 개선의 증거가 아니다.",
          f"- 증명하지 못하는 것: 확인 구간 약 {r['power']['confirmation']['years']}년·시도 {N_TRIALS_TOTAL}개에서는 연 IR 이 {r['power']['confirmation']['mde_ir']:.2f} 보다 작은 효과를 가려낼 수 없다 "
          "(FAIL_UNDERPOWERED 는 '효과 없음'이 아니라 '판별 불가'에 가깝다). 보유기간 12개월은 리밸런싱이 연 1회라 확인 구간 표본이 7~8번뿐이다.",
          "- 코어 연결(S2·S3·S4)은 코어의 월별 보유 섹터(ETF 시대: 섹터 ETF, CRSP: core-longrun-v1 복제 규칙이 든 FF12 산업)와 종목 섹터를 이은 것이다. 위약 S2p·S3p 와의 차이가 '코어 연결' 효과의 크기를 말해 준다.", "",
          "## 한계", "",
          *(["- CRSP 자료: 상장폐지 종목 포함(생존편향 없음). 단 dlret 이 비었거나 −55/−66/−88/−99 인 폐지는 손실을 반영하지 못한다 "
             f"(성과 관련 폐지 중 유효 dlret 없음 {((r['meta'].get('delists') or {}).get('performance_delist_without_valid_dlret'))}건 — 후보를 실제보다 좋게 만들 수 있다). "
             "섹터 = 그 시점 SIC 의 FF12 산업, 시가총액 = |prc|×shrout×1000(전 거래일), 신호·수익은 총수익 지수(분할·배당 조정). "
             "코어는 ETF 가 아니라 core-longrun-v1 복제 규칙(FF12 산업 모멘텀 상위 4, 200일 시장 필터)의 보유 산업으로 대신했다. 기준선 풀 = PIT 시총 상위 40(섹터 균형 없음)."]
            if P.name == "crsp" else [
             "- 생존편향: 상장폐지 종목은 가격 소스에 없어 후보에서 빠진다(성과를 실제보다 좋게 만들 수 있다).",
             "- 섹터 분류는 현재 S&P500 표(시점 기준 아님)다 — 지금 지수에 없는 종목은 섹터를 몰라 S2·S3·S4 후보에서 빠진다. "
             f"(섹터를 아는 종목 {m['n_sector_tickers']}개)",
             "- 시가총액은 발행주식수 이력 × 리밸런싱 전날 종가의 근사다(core.point_in_time_market_cap 과 같은 식, 시총 커버리지 "
             f"{pct((r['meta'].get('cap_coverage') or {}).get('mean'))})."]),
          f"- 폴백: 코어가 섹터 ETF 를 하나도 들지 않은 달이 전체 {m['n_dates_total'] - m['n_dates_with_held_sectors']}/{m['n_dates_total']}개월(S2·S3·S4 는 그달 현 규칙 선정).",
          "- 비용은 편도 8bp 단순 모델, 배당 포함 조정 가격 수익, 세금·슬리피지 없음. 같은 기간을 여러 연구가 반복해 보는 데서 오는 과적합 위험은 DSR 로 부분적으로만 반영된다."]
    return "\n".join(L) + "\n"


# =================================================================================================
# 실행 본체
# =================================================================================================

def run_job(job_id: str, argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-units-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 계산 단위 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    smoke = bool(a.smoke)
    backend_name = JOB_BACKEND[job_id]
    set_profile(CRSP_PROFILE if backend_name == "crsp" else ETF_PROFILE)
    fp = {"rules": P.rules_version, "backend": backend_name, "smoke": smoke, "data_end": DATA_END if not smoke else "synthetic",
          "n_random": 20 if smoke else N_RANDOM}
    if backend_name == "crsp" and not smoke:
        import importlib.util

        spec_ = importlib.util.spec_from_file_location("sat_selection_crsp", Path(__file__).resolve().parent / "crsp.py")
        crsp_mod = sys.modules.setdefault("sat_selection_crsp", importlib.util.module_from_spec(spec_))
        if not hasattr(crsp_mod, "build_bundle"):
            spec_.loader.exec_module(crsp_mod)
        problems = crsp_mod.input_problems()
        if problems:
            write_missing_data_outputs(out, job_id, problems, crsp_mod)
            log(f"{job_id}: CRSP 입력 없음 — NOT_EVALUABLE_DATA ({'; '.join(problems)})")
            return 0
        fp["inputs"] = crsp_inputs_fingerprint(crsp_mod.CRSP_DIR)
    n_random, chunk = (20, 10) if smoke else (N_RANDOM, 50)
    budget = Budget(a.max_units_per_run)

    def on_term(signum, frame):  # noqa: ARG001
        budget.flag = True

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    candidates, controls = JOB_STRATEGIES[job_id], JOB_CONTROLS[job_id]
    need = ["B0"] + candidates + controls
    try:
        log(f"{job_id}: 데이터 준비")
        data, static = BACKENDS[backend_name].load(log, ck, fp, smoke)
        env = make_env(data, static, smoke)
        env.static_meta = static.get("meta", {})
        plans: dict[str, dict] = {}
        for sid in need:
            path = ck / f"plan_{sid}.pkl"
            got = load_ckpt(path, fp)
            if got is None:
                budget.check()
                log(f"선정 계획 {sid}")
                got = build_plan(env, sid)
                atomic_pickle(path, {"fingerprint": fp, "payload": got})
                budget.done()
            plans[sid] = got
        cells: dict = {}
        for sid in need:
            for h in HOLDS:
                path = ck / f"cell_{sid}_{h}.pkl"
                got = load_ckpt(path, fp)
                if got is None:
                    budget.check()
                    log(f"시뮬레이션 {sid} {h}개월")
                    got = simulate_cell(env, schedule_for(plans[sid], env.monthly, h))
                    atomic_pickle(path, {"fingerprint": fp, "payload": got})
                    budget.done()
                cells[(sid, h)] = got
        randoms: dict = {}
        for sid in ["B0"] + candidates:
            for h in HOLDS:
                path = ck / f"rand_{sid}_{h}.pkl"
                got = load_ckpt(path, fp) or {"sel": [], "conf": []}
                while len(got["conf"]) < n_random:
                    budget.check()
                    i0 = len(got["conf"])
                    for i in range(i0, min(n_random, i0 + chunk)):
                        s_, c_ = random_sim_stats(env, plans[sid], h, sid, i)
                        got["sel"].append(s_)
                        got["conf"].append(c_)
                    atomic_pickle(path, {"fingerprint": fp, "payload": got})
                    budget.done()
                    log(f"무작위 {sid} {h}개월 {len(got['conf'])}/{n_random}")
                randoms[(sid, h)] = got
        d1 = None
        if job_id == "sat-follower-v1":
            d1_plans = {"S4": plans["S4"]}
            d1 = diagnostics_d1(env, d1_plans)
            s3 = load_ckpt(ck / "plan_S3.pkl", fp)
            if s3 is None:
                budget.check()
                s3 = build_plan(env, "S3")
                atomic_pickle(ck / "plan_S3.pkl", {"fingerprint": fp, "payload": s3})
                budget.done()
            d1.update(diagnostics_d1(env, {"S3(고른 추종주)": s3}))
        if backend_name == "crsp":
            repro = {"status": "NOT_APPLICABLE", "ours": float(he.stats(segment(cells[("B0", BASELINE_HOLD)]["returns"], "sel")).get("sharpe_annual", float("nan"))),
                     "registry": None, "diff": None, "tolerance": REPRO_TOL_SHARPE,
                     "note": "CRSP 기준선은 새틀라이트 랩 등록부에 대응물이 없다(PIT 시총 상위 40, 섹터 균형 없음). 재현 확인 대신 단위 검산(테스트)만 한다."}
        else:
            ref, split = (None, None) if smoke else read_registry_reference()
            repro = check_baseline_reproduction(cells[("B0", BASELINE_HOLD)]["returns"], ref, split)
            if smoke:
                repro["note"] = "스모크(합성 데이터)라 등록부와 비교하지 않는다."
        result, report = analyze(env, plans, cells, randoms, job_id, candidates, controls, repro, smoke, d1)
    except Stop:
        log("시간 예산 끝(또는 단위 상한) — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    atomic_write(out / "results.json", json.dumps(result, ensure_ascii=False, indent=1, default=str))
    atomic_write(out / "REPORT.md", report)
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0
