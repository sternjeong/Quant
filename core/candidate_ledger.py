"""RES-01: 모든 후보 shadow 원장 — 주문에 영향 없는 관측 전용 인프라 (2026-09-21).

목적: 채택한 종목만이 아니라 보류·거절·결측 후보까지 같은 진입·청산·비용 계약으로 끝까지 추적해
"채택이 보류/거절보다 비용 후 기대값을 실제로 높였는가"를 사후에 검증할 수 있는 반사실 원장을 쌓는다.
이 모듈은 성과나 승률 개선을 주장하지 않는다. 주문 경로(core.paper_execution, scripts/champion_paper_trade.py)와
스케줄러는 이 모듈을 호출하지 않는다(연결은 별도 단계). 설계 배경은 docs/CANDIDATE_LEDGER_SPEC.md 참고.

## 사전 고정 계약 (코드 상수 = 사전 등록. 결과를 본 뒤 바꾸면 탐색 결과로만 취급한다)
- 진입: decision_cutoff 이후 첫 미국 정규장 세션의 시가(Open). core.trade_ledger 의 "t 종가 이후 신호 -> t+1 시가 체결"
  관례를 시각으로 일반화한 것이다. 날짜만 준 cutoff 는 그 날 미 동부 23:59:59(장 마감 후)로 본다 -> 다음 세션 시가.
  시각이 있는 cutoff 는 개장(09:30 미 동부, DST 반영) 이전이면 당일 시가, 이후면(정각 포함) 다음 세션 시가.
- 청산(하나로 고정): 진입 세션 + horizon 거래일 뒤 세션의 **시가**. 진입·청산 모두 시가라 trade_ledger 의 체결 관례
  (신호 다음 세션 시가 체결)와 같고, 종가/시가를 섞지 않는다. 거래일력은 벤치마크(SPY) 세션을 쓴다.
- 주 horizon: PRIMARY_HORIZON_DAYS = 20 거래일 하나. 5/60 거래일은 진단 전용(role='diagnostic')이며 다중검정 대상이다.
  판정(verdict)은 주 horizon·주 대상·주 비용 시나리오에서만 가능하다(decide_verdict).
- 비용: core.trade_ledger.COST_SCENARIOS_BPS 의 편도 5/10/25bp(수수료+슬리피지, 세금 0)를 모두 저장하고,
  주 검정은 PRIMARY_COST_SCENARIO = '10bp' 하나로 사전 고정한다. 왕복 순수익은 trade_ledger 의 전량 매수-전량 매도와 동일하다.
- 주 검정 대상: PRIMARY_TARGET = 'net_excess_spy' (비용 후 수익 - 같은 진입/청산 세션 시가 기준 SPY 수익).
  섹터 잔차('net_excess_sector')는 섹터 ETF 를 β=1 로 단순 차감한 값이다(회귀 잔차 아님, 진단용).
- 가격 기준: 캐시된 원시 Open(core.market_data, auto_adjust=False). 분할은 반영, 배당은 미반영(총수익 아님).
  Adj Close 비율 조정은 캐시가 증분 병합돼 조정 기준일이 행마다 다를 수 있어 쓰지 않는다.

## 결측 처리 (조용한 0 처리 금지)
가격 결측·상장폐지·진입 불가는 status='missing' + 사유 문자열로 남기고 수익 컬럼은 NULL 이다. 지표는 결측을 제외하고
결측 수·결측률을 따로 보고하며, 결측률이 높으면 판정을 '미입증'으로 내린다(생존편향 방지). 티커 데이터가 벤치마크보다
MISSING_GRACE_SESSIONS 세션 넘게 뒤처질 때만 결측으로 확정하고 그 전에는 pending 이다.

## 판정 규칙 (자동 긍정/기각 금지)
동일 선택률 무작위 보류 기준선 대비 비용 후 초과수익 증분의 종목·날짜 군집(pigeonhole) 부트스트랩 신뢰구간이 0을
포함하면 verdict='미입증'(코드로 강제). 신뢰구간이 0을 배제해도 표본·PIT·결측 조건을 모두 통과해야 '양성_검토대상' 또는
'기각_검토대상'이 되며, 이는 사람이 검토할 후보라는 뜻이지 채택/폐기 결정이 아니다(auto_decision=False).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from core.trade_ledger import COST_SCENARIOS_BPS

# ---------------------------------------------------------------------------
# 사전 고정 상수
# ---------------------------------------------------------------------------
LEDGER_VERSION = "candidate-ledger/2026-09"

PRIMARY_HORIZON_DAYS = 20
DIAGNOSTIC_HORIZONS = (5, 60)
ALL_HORIZONS = tuple(sorted((PRIMARY_HORIZON_DAYS,) + DIAGNOSTIC_HORIZONS))

BENCHMARK_TICKER = "SPY"
PRIMARY_COST_SCENARIO = "10bp"
PRIMARY_TARGET = "net_excess_spy"

DECISIONS = ("selected", "held", "rejected", "missing_data")
ELIGIBLE_DECISIONS = ("selected", "held", "rejected")  # 선택률·무작위 기준선 풀(원전략이 고를 수 있었던 후보)
REST_DECISIONS = ("held", "rejected")  # 채택 대비 비교군

ENTRY_RULE = "open of first NYSE session strictly after decision_cutoff (09:30 America/New_York)"
EXIT_RULE = "open of session (entry session + horizon trading days); benchmark SPY sessions define the calendar"
PRICE_BASIS = "unadjusted Open as cached (core.market_data auto_adjust=False; splits reflected, dividends not)"

MARKET_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MISSING_GRACE_SESSIONS = 5

# 판정 게이트(사전 제안값 — 범용 최적값이 아니며 실제 검정력 분석으로 대체해야 한다)
MIN_SELECTED_FOR_VERDICT = 30
MIN_TICKER_CLUSTERS_FOR_VERDICT = 20
MIN_DATE_BLOCKS_FOR_VERDICT = 6
MIN_SELECTED_FOR_REJECTION = 100
MIN_DATE_BLOCKS_FOR_REJECTION = 12
MAX_MISSING_OUTCOME_RATE = 0.10

DEFAULT_N_BOOT = 2000
DEFAULT_N_RANDOM_DRAWS = 1000
BOOTSTRAP_SEED = 20260921
DEFAULT_MAX_MISSING_FACTORS = 2

VERDICT_UNPROVEN = "미입증"
VERDICT_POSITIVE_REVIEW = "양성_검토대상"
VERDICT_REJECT_REVIEW = "기각_검토대상"

DISCLAIMER = (
    "이 원장은 관측 인프라다. 표시된 수치는 성과·승률 개선의 증거가 아니며, 판정은 사람이 검토할 후보일 뿐 자동 채택/폐기가 아니다. "
    "PIT 인증되지 않은 행, 표본 부족, 결측률 과다, 진단 horizon 은 항상 '미입증'이다."
)

TIME_CONTRACT_FIELDS = (
    "source_publication", "system_first_seen", "extraction_completed", "decision_cutoff", "next_executable_fill",
)

# GICS(core.screener) 및 yfinance sector 표기 -> SPDR 섹터 ETF (섹터 잔차 계산용)
SECTOR_ETF_BY_SECTOR = {
    "information technology": "XLK", "technology": "XLK",
    "financials": "XLF", "financial services": "XLF",
    "health care": "XLV", "healthcare": "XLV",
    "consumer discretionary": "XLY", "consumer cyclical": "XLY",
    "consumer staples": "XLP", "consumer defensive": "XLP",
    "energy": "XLE", "industrials": "XLI",
    "materials": "XLB", "basic materials": "XLB",
    "utilities": "XLU", "real estate": "XLRE", "communication services": "XLC",
}

PriceProvider = Callable[[str, str, str], pd.DataFrame]


# ---------------------------------------------------------------------------
# 공용 유틸
# ---------------------------------------------------------------------------
def _isnull(v: Any) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _jsonable(obj: Any) -> Any:
    """numpy/pandas 값과 NaN 을 JSON 안전 값으로 바꾼다(NaN/inf -> None)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return None if _isnull(obj) else obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset)):
        return [_jsonable(v) for v in sorted(obj, key=str)]
    if isinstance(obj, (list, tuple, np.ndarray, pd.Series)):
        return [_jsonable(v) for v in obj]
    return str(obj)


def _dumps(obj: Any) -> str:
    return json.dumps(_jsonable(obj), ensure_ascii=False, sort_keys=True)


def _as_date(x: Any = None) -> date:
    if x is None:
        return date.today()
    if isinstance(x, pd.Timestamp):
        return x.date()
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return pd.Timestamp(x).date()


def normalize_time(value: Any) -> Optional[datetime]:
    """시각 입력을 naive UTC datetime 으로 정규화한다(저장 관례: 이 저장소 DB 는 naive UTC).

    - None/NaN/빈 문자열 -> None
    - 날짜만 있는 입력(date, 'YYYY-MM-DD') -> 그 날 미 동부 23:59:59(가장 늦은 시각, 보수적) -> UTC
    - tz-aware -> UTC 로 변환 후 tz 제거, tz-naive datetime/Timestamp/문자열 -> UTC 로 간주
    """
    if _isnull(value):
        return None
    date_only = False
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        date_only = len(s) <= 10
        ts = pd.Timestamp(s)
    elif isinstance(value, (pd.Timestamp, datetime)):
        ts = pd.Timestamp(value)
    elif isinstance(value, date):
        date_only = True
        ts = pd.Timestamp(value)
    else:
        ts = pd.Timestamp(value)
    if _isnull(ts):
        return None
    if date_only:
        local = datetime.combine(ts.date(), time(23, 59, 59), tzinfo=MARKET_TZ)
        return local.astimezone(timezone.utc).replace(tzinfo=None)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_pydatetime()


def _ny_local(dt_utc_naive: datetime) -> datetime:
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(MARKET_TZ)


def session_open_utc(session_date: date) -> datetime:
    """세션 날짜의 정규장 개장 시각(09:30 미 동부)을 naive UTC 로."""
    local = datetime.combine(_as_date(session_date), MARKET_OPEN, tzinfo=MARKET_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def resolve_entry_position(calendar: Iterable, cutoff: Any) -> Optional[int]:
    """calendar(정렬된 세션 날짜) 안에서 cutoff 이후 첫 체결 가능 세션의 위치. 아직 없으면 None.

    개장 시각 이전 cutoff 는 당일 시가, 개장 시각 이후(정각 포함)나 날짜만 준 cutoff 는 다음 세션 시가.
    """
    c = normalize_time(cutoff)
    if c is None:
        return None
    local = _ny_local(c)
    threshold = local.date() if local.time() < MARKET_OPEN else local.date() + timedelta(days=1)
    dates = pd.DatetimeIndex(calendar).normalize()
    pos = int(dates.searchsorted(pd.Timestamp(threshold), side="left"))
    return pos if pos < len(dates) else None


def compute_pit_status(
    source_publication: Any, system_first_seen: Any, extraction_completed: Any,
    decision_cutoff: Any, next_executable_fill: Any,
) -> tuple[bool, list[str]]:
    """시간 계약 5개 필드가 모두 있고 source_publication <= system_first_seen <= extraction_completed <=
    decision_cutoff <= next_executable_fill 순서일 때만 PIT 인증(True). 사유 목록을 함께 반환한다."""
    values = [normalize_time(v) for v in (
        source_publication, system_first_seen, extraction_completed, decision_cutoff, next_executable_fill)]
    issues = [f"missing:{name}" for name, v in zip(TIME_CONTRACT_FIELDS, values) if v is None]
    present = [(n, v) for n, v in zip(TIME_CONTRACT_FIELDS, values) if v is not None]
    for (n1, v1), (n2, v2) in zip(present, present[1:]):
        if v1 > v2:
            issues.append(f"order_violation:{n1}>{n2}")
    return (not issues), issues


def sector_etf_for(sector: Optional[str]) -> Optional[str]:
    if _isnull(sector):
        return None
    return SECTOR_ETF_BY_SECTOR.get(str(sector).strip().lower())


# ---------------------------------------------------------------------------
# 후보 레코드 / 동결된 후보 집합
# ---------------------------------------------------------------------------
@dataclass
class CandidateRecord:
    """후보 판단 1건. 시간 계약 필드는 없으면 None 으로 두며 지어내지 않는다(pit_certified=False)."""

    ticker: str
    decision: str
    decision_reason: str = ""
    scores: dict = field(default_factory=dict)
    order_proposal: Optional[dict] = None
    rank: Optional[int] = None
    sector: Optional[str] = None
    sector_etf: Optional[str] = None
    source_publication: Any = None
    system_first_seen: Any = None
    extraction_completed: Any = None
    decision_cutoff: Any = None
    next_executable_fill: Any = None
    info_url: Optional[str] = None
    info_doc_id: Optional[str] = None
    info_hash: Optional[str] = None
    info_revision: Optional[str] = None
    event_id: Optional[str] = None
    info_cost: Optional[dict] = None

    def __post_init__(self) -> None:
        self.ticker = str(self.ticker or "").strip().upper()
        if not self.ticker:
            raise ValueError("ticker 가 비어 있습니다")
        if self.decision not in DECISIONS:
            raise ValueError(f"decision 은 {DECISIONS} 중 하나여야 합니다: {self.decision!r}")
        for name in TIME_CONTRACT_FIELDS:
            setattr(self, name, normalize_time(getattr(self, name)))
        if _isnull(self.sector):
            self.sector = None
        if self.sector_etf is None:
            self.sector_etf = sector_etf_for(self.sector)


def compute_candidate_set_id(tickers: Iterable[str], strategy_version: str, source: str, decision_cutoff: Any) -> str:
    """동결된 후보 집합 해시: 정렬된 티커 집합 + 전략 버전 + 출처 + 정규화된 결정 시각."""
    cutoff = normalize_time(decision_cutoff)
    canonical = json.dumps(
        {
            "tickers": sorted({str(t).strip().upper() for t in tickers}),
            "strategy_version": strategy_version,
            "source": source,
            "decision_cutoff": cutoff.isoformat() if cutoff else None,
        },
        sort_keys=True, ensure_ascii=False,
    )
    return "cs_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass
class FrozenCandidateSet:
    """한 번의 스캔/판단이 만든 후보 전체(채택·보류·거절·결측). 기록 후에는 덮어쓰지 않는다."""

    source: str
    strategy_version: str
    decision_cutoff: Any
    records: list
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.decision_cutoff = normalize_time(self.decision_cutoff)
        seen: set[str] = set()
        for r in self.records:
            if r.ticker in seen:
                raise ValueError(f"후보 집합에 중복 티커가 있습니다: {r.ticker}")
            seen.add(r.ticker)
            if r.decision_cutoff is None:
                r.decision_cutoff = self.decision_cutoff

    @property
    def candidate_set_id(self) -> str:
        return compute_candidate_set_id(
            [r.ticker for r in self.records], self.strategy_version, self.source, self.decision_cutoff)

    @property
    def decisions_fingerprint(self) -> str:
        payload = sorted((r.ticker, r.decision, r.decision_reason or "") for r in self.records)
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# DB 세션 처리
# ---------------------------------------------------------------------------
@contextmanager
def _session_scope(session=None):
    """session 을 주입하면 그대로 쓰고 끝에서 commit(예외면 rollback). 없으면 core.db.get_session()."""
    if session is not None:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
    else:
        from core.db import get_session, init_db

        init_db()  # create_all: 새 테이블만 만들고 기존 행은 건드리지 않는다
        with get_session() as s:
            yield s


def record_candidate_set(cset: FrozenCandidateSet, session=None) -> dict:
    """후보 집합을 원장에 동결 기록한다(멱등). 같은 candidate_set_id 가 이미 있으면 아무것도 바꾸지 않는다.

    Returns: {"candidate_set_id", "inserted", "n_decisions", "conflict"}. conflict=True 는 같은 집합을 다른
    판단으로 다시 기록하려 했다는 뜻이며 기존 기록은 보존된다.
    """
    from core.models import CandidateBatch, CandidateDecision

    cid = cset.candidate_set_id
    fp = cset.decisions_fingerprint
    with _session_scope(session) as s:
        existing = s.query(CandidateBatch).filter_by(candidate_set_id=cid).one_or_none()
        if existing is not None:
            return {
                "candidate_set_id": cid, "inserted": False, "n_decisions": existing.n_candidates,
                "conflict": existing.decisions_fingerprint is not None and existing.decisions_fingerprint != fp,
            }
        batch = CandidateBatch(
            candidate_set_id=cid, source=cset.source, strategy_version=cset.strategy_version,
            decision_cutoff=cset.decision_cutoff, n_candidates=len(cset.records),
            decisions_fingerprint=fp, meta=_dumps(cset.meta or {}),
        )
        s.add(batch)
        s.flush()
        for r in cset.records:
            cutoff = r.decision_cutoff or cset.decision_cutoff
            ok, issues = compute_pit_status(
                r.source_publication, r.system_first_seen, r.extraction_completed, cutoff, r.next_executable_fill)
            s.add(CandidateDecision(
                batch_id=batch.id, candidate_set_id=cid, ticker=r.ticker, strategy_version=cset.strategy_version,
                source=cset.source, decision=r.decision, decision_reason=r.decision_reason or "", rank=r.rank,
                scores=_dumps(r.scores or {}),
                order_proposal=None if r.order_proposal is None else _dumps(r.order_proposal),
                sector=r.sector, sector_etf=r.sector_etf,
                source_publication=r.source_publication, system_first_seen=r.system_first_seen,
                extraction_completed=r.extraction_completed, decision_cutoff=cutoff,
                next_executable_fill=r.next_executable_fill, pit_certified=ok,
                pit_note="; ".join(issues) or None,
                info_url=r.info_url, info_doc_id=r.info_doc_id, info_content_hash=r.info_hash,
                info_revision=r.info_revision, event_id=r.event_id,
                info_cost=None if r.info_cost is None else _dumps(r.info_cost),
            ))
    return {"candidate_set_id": cid, "inserted": True, "n_decisions": len(cset.records), "conflict": False}


# ---------------------------------------------------------------------------
# 가격 · 진입/청산 · 비용 (순수 함수)
# ---------------------------------------------------------------------------
def default_price_provider(ticker: str, start: str, end: str) -> pd.DataFrame:
    """core.market_data 의 로컬 캐시 정책을 그대로 쓰는 기본 공급자. end 는 yfinance 관례대로 배타적.

    명시적 end 를 주므로 캐시가 그 범위를 이미 덮고 있으면 네트워크 호출이 없다(기존 정책).
    """
    from core import market_data

    return market_data.get_price_history(ticker, start=start, end=end, interval="1d", use_cache=True)


def round_trip_return(open_entry: float, open_exit: float, scenario: Optional[str] = None) -> float:
    """진입 시가 -> 청산 시가 왕복 수익률. scenario=None 이면 비용 없는 총수익, 아니면 편도 비용 시나리오 차감 후.

    core.trade_ledger 체결 모델과 같다: 매수 시가*(1+슬리피지)*(1+수수료), 매도 시가*(1-슬리피지)*(1-수수료), 세금 0.
    """
    ratio = float(open_exit) / float(open_entry)
    if scenario is None:
        return ratio - 1.0
    sc = COST_SCENARIOS_BPS[scenario]
    f, s = sc["fee_bps"] / 1e4, sc["slippage_bps"] / 1e4
    return ratio * (1 - s) * (1 - f) / ((1 + s) * (1 + f)) - 1.0


_EMPTY_PRICES = pd.DataFrame({"Open": pd.Series(dtype=float)}, index=pd.DatetimeIndex([]))


def _clean_prices(df: Optional[pd.DataFrame], as_of_date: date) -> pd.DataFrame:
    """Open 만 남기고 날짜 인덱스를 정규화(tz 제거, 중복 제거, 정렬)하며 as_of 이후 봉은 버린다."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or "Open" not in df.columns:
        return _EMPTY_PRICES
    out = pd.DataFrame({"Open": pd.to_numeric(df["Open"], errors="coerce")})
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out.index = idx.normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out[out.index <= pd.Timestamp(as_of_date)]


def _blank_outcome() -> dict:
    return {
        "status": "pending", "reason": None, "entry_date": None, "entry_open": None, "exit_date": None,
        "exit_open": None, "gross_return": None, "net_returns": {name: None for name in COST_SCENARIOS_BPS},
        "benchmark_return": None, "sector_etf_return": None, "detail": {},
    }


def _finish(out: dict, status: str, reason: Optional[str], detail: Optional[dict] = None) -> dict:
    out["status"], out["reason"] = status, reason
    if detail:
        out["detail"].update(detail)
    return out


def _classify_missing_bar(stock: pd.DataFrame, d: pd.Timestamp, which: str, grace_passed: bool) -> tuple[str, str, dict]:
    if stock.empty:
        if grace_passed:
            return "missing", "no_price_data", {}
        return "pending", "price_data_unavailable", {}
    first, last = stock.index.min(), stock.index.max()
    detail = {"ticker_first_bar": first.date().isoformat(), "ticker_last_bar": last.date().isoformat()}
    if which == "entry" and first > d:
        return "missing", "not_listed_at_entry", detail
    if last < d:
        if grace_passed:
            return "missing", f"data_ended_before_{which}", detail
        return "pending", "ticker_data_lagging", detail
    return "missing", f"no_{which}_bar", detail


def compute_outcome(
    cutoff: Any, horizon: int, stock_df: Optional[pd.DataFrame], bench_df: Optional[pd.DataFrame],
    sector_df: Optional[pd.DataFrame] = None, *, as_of: Any = None,
    grace_sessions: int = MISSING_GRACE_SESSIONS, _prepared: bool = False,
) -> dict:
    """후보 1건·horizon 1개의 사후 결과를 계산한다(순수 함수, 네트워크 없음).

    status: final | pending | missing. missing/pending 이면 수익 값은 None(0 아님)이고 reason 에 사유가 있다.
    as_of 이후의 봉은 절대 쓰지 않는다.
    """
    as_of_date = _as_date(as_of)
    out = _blank_outcome()
    if normalize_time(cutoff) is None:
        return _finish(out, "missing", "decision_cutoff_missing")

    if _prepared:
        stock, bench, sector = stock_df, bench_df, sector_df
    else:
        stock = _clean_prices(stock_df, as_of_date)
        bench = _clean_prices(bench_df, as_of_date)
        sector = None if sector_df is None else _clean_prices(sector_df, as_of_date)

    bench_ok = bench[(bench["Open"].notna()) & (bench["Open"] > 0)]
    cal = bench_ok.index
    if len(cal) == 0:
        return _finish(out, "pending", "benchmark_unavailable")
    e = resolve_entry_position(cal, cutoff)
    if e is None:
        return _finish(out, "pending", "entry_session_not_reached")
    x = e + int(horizon)
    entry_d = cal[e]

    if x >= len(cal):
        # 청산 세션이 아직 없다. 진입 봉만 확인해 기록하되(체결 시각 확정용) 결측 판정은 하지 않는다.
        if entry_d in stock.index and pd.notna(stock.at[entry_d, "Open"]) and stock.at[entry_d, "Open"] > 0:
            out["entry_date"], out["entry_open"] = entry_d.date(), float(stock.at[entry_d, "Open"])
        return _finish(out, "pending", "horizon_not_reached")

    exit_d = cal[x]
    grace_passed = (len(cal) - 1 - x) >= grace_sessions

    # 진입 봉
    if entry_d not in stock.index:
        status, reason, detail = _classify_missing_bar(stock, entry_d, "entry", grace_passed)
        return _finish(out, status, reason, detail)
    entry_open = stock.at[entry_d, "Open"]
    if pd.isna(entry_open) or entry_open <= 0:
        return _finish(out, "missing", "invalid_entry_open")
    out["entry_date"], out["entry_open"] = entry_d.date(), float(entry_open)

    # 청산 봉
    if exit_d not in stock.index:
        status, reason, detail = _classify_missing_bar(stock, exit_d, "exit", grace_passed)
        return _finish(out, status, reason, detail)
    exit_open = stock.at[exit_d, "Open"]
    if pd.isna(exit_open) or exit_open <= 0:
        return _finish(out, "missing", "invalid_exit_open")

    out["exit_date"], out["exit_open"] = exit_d.date(), float(exit_open)
    out["gross_return"] = round_trip_return(entry_open, exit_open)
    out["net_returns"] = {name: round_trip_return(entry_open, exit_open, name) for name in COST_SCENARIOS_BPS}
    out["benchmark_return"] = round_trip_return(bench_ok.at[entry_d, "Open"], bench_ok.at[exit_d, "Open"])

    if sector is None:
        out["detail"]["sector_note"] = "sector_etf_unavailable"
    else:
        try:
            so, sx = sector.at[entry_d, "Open"], sector.at[exit_d, "Open"]
        except KeyError:
            so = sx = float("nan")
        if pd.notna(so) and pd.notna(sx) and so > 0 and sx > 0:
            out["sector_etf_return"] = round_trip_return(so, sx)
        else:
            out["detail"]["sector_note"] = "sector_etf_price_missing"
    return _finish(out, "final", None)


# ---------------------------------------------------------------------------
# 결과 갱신 (update_forward_outcomes)
# ---------------------------------------------------------------------------
def _ny_date(dt_utc_naive: Optional[datetime]) -> Optional[date]:
    return None if dt_utc_naive is None else _ny_local(dt_utc_naive).date()


def _apply_outcome(row, out: dict, horizon: int, as_of_date: date, benchmark: str, sector_etf: Optional[str]) -> None:
    row.role = "primary" if horizon == PRIMARY_HORIZON_DAYS else "diagnostic"
    row.status = out["status"]
    row.status_reason = out["reason"]
    row.entry_date, row.entry_open = out["entry_date"], out["entry_open"]
    row.exit_date, row.exit_open = out["exit_date"], out["exit_open"]
    row.gross_return = out["gross_return"]
    row.net_return_5bp = out["net_returns"].get("5bp")
    row.net_return_10bp = out["net_returns"].get("10bp")
    row.net_return_25bp = out["net_returns"].get("25bp")
    row.benchmark_ticker = benchmark
    row.benchmark_return = out["benchmark_return"]
    row.sector_etf_ticker = sector_etf
    row.sector_etf_return = out["sector_etf_return"]
    row.price_basis = PRICE_BASIS
    row.exit_rule = EXIT_RULE
    row.resolved_as_of = as_of_date
    row.detail = _dumps(out["detail"]) if out["detail"] else None


def update_forward_outcomes(
    as_of: Any = None, *, price_provider: Optional[PriceProvider] = None, session=None,
    horizons: Sequence[int] = ALL_HORIZONS, benchmark: str = BENCHMARK_TICKER,
    strategy_version: Optional[str] = None, grace_sessions: int = MISSING_GRACE_SESSIONS,
) -> dict:
    """아직 확정되지 않은(없거나 pending 인) (후보, horizon) 결과를 as_of 까지의 가격으로 채운다.

    - 멱등: final/missing 은 종결 상태라 다시 계산하지 않고, pending 행은 같은 행을 갱신한다(중복 행 없음).
    - 가격은 price_provider(ticker, start, end) 로 받는다. 기본은 core.market_data 캐시 정책. end 는 배타적.
    - 공급자 예외는 해당 티커의 결과를 pending('provider_error: ...')으로 남기고 나머지는 계속 처리한다.
    - 진입 세션이 확정되면 결정 행의 next_executable_fill 을 채우고 PIT 인증 여부를 다시 계산한다.
    Returns: 요약 dict(finalized/missing/pending 은 이번 실행에서 그 상태로 기록된 (후보, horizon) 수).
    """
    from core.models import CandidateDecision, CandidateOutcome

    as_of_date = _as_date(as_of)
    horizons = tuple(sorted({int(h) for h in horizons}))
    provider = price_provider or default_price_provider
    summary: dict = {
        "as_of": as_of_date.isoformat(), "horizons": list(horizons), "n_decisions_examined": 0,
        "finalized": 0, "missing": 0, "pending": 0, "skipped_terminal": 0, "tickers_fetched": 0,
        "by_reason": {}, "errors": [],
    }
    reasons: Counter = Counter()

    with _session_scope(session) as s:
        dq = s.query(CandidateDecision)
        oq = s.query(CandidateOutcome).join(CandidateDecision, CandidateOutcome.decision_id == CandidateDecision.id)
        if strategy_version:
            dq = dq.filter(CandidateDecision.strategy_version == strategy_version)
            oq = oq.filter(CandidateDecision.strategy_version == strategy_version)
        decisions = dq.order_by(CandidateDecision.id).all()
        existing: dict[int, dict[int, Any]] = defaultdict(dict)
        for o in oq.all():
            existing[o.decision_id][o.horizon_days] = o

        todo = []
        for d in decisions:
            need = [h for h in horizons if h not in existing[d.id] or existing[d.id][h].status == "pending"]
            if need:
                todo.append((d, need))
            else:
                summary["skipped_terminal"] += 1
        summary["n_decisions_examined"] = len(todo)

        # 가격 조회: 필요한 티커를 한 번씩만
        cutoff_dates = [_ny_date(d.decision_cutoff) for d, _ in todo if d.decision_cutoff is not None]
        frames: dict[str, pd.DataFrame] = {}
        fetch_errors: dict[str, str] = {}
        if cutoff_dates:
            start = (min(cutoff_dates) - timedelta(days=10)).isoformat()
            end = (as_of_date + timedelta(days=1)).isoformat()
            wanted = {benchmark}
            for d, _ in todo:
                if d.decision_cutoff is not None:
                    wanted.add(d.ticker)
                    if d.sector_etf:
                        wanted.add(d.sector_etf)
            for t in sorted(wanted):
                try:
                    frames[t] = _clean_prices(provider(t, start, end), as_of_date)
                except Exception as exc:  # noqa: BLE001 - 티커 하나의 실패가 전체를 멈추지 않게 한다
                    fetch_errors[t] = f"{type(exc).__name__}: {exc}"
                    summary["errors"].append(f"{t}: {fetch_errors[t]}")
            summary["tickers_fetched"] = len(frames)
        bench = frames.get(benchmark, _EMPTY_PRICES)

        for d, need in todo:
            for h in need:
                if d.ticker in fetch_errors:
                    out = _finish(_blank_outcome(), "pending", f"provider_error: {fetch_errors[d.ticker]}")
                else:
                    sector = frames.get(d.sector_etf) if d.sector_etf else None
                    out = compute_outcome(
                        d.decision_cutoff, h, frames.get(d.ticker, _EMPTY_PRICES), bench, sector,
                        as_of=as_of_date, grace_sessions=grace_sessions, _prepared=True)
                    if d.sector_etf is None and out["detail"].get("sector_note"):
                        out["detail"]["sector_note"] = "no_sector_etf_mapping"
                row = existing[d.id].get(h)
                if row is None:
                    row = CandidateOutcome(decision_id=d.id, horizon_days=h)
                    s.add(row)
                    existing[d.id][h] = row
                _apply_outcome(row, out, h, as_of_date, benchmark, d.sector_etf)

                key = {"final": "finalized", "missing": "missing", "pending": "pending"}[out["status"]]
                summary[key] += 1
                if out["reason"]:
                    reasons[f"{out['status']}:{str(out['reason']).split(':')[0]}"] += 1

                if out["entry_date"] is not None and d.next_executable_fill is None:
                    d.next_executable_fill = session_open_utc(out["entry_date"])
                    ok, issues = compute_pit_status(
                        d.source_publication, d.system_first_seen, d.extraction_completed,
                        d.decision_cutoff, d.next_executable_fill)
                    d.pit_certified = ok
                    d.pit_note = "; ".join(issues) or None
    summary["by_reason"] = dict(reasons)
    return summary


# ---------------------------------------------------------------------------
# 프레임 로딩
# ---------------------------------------------------------------------------
FRAME_COLUMNS = [
    "decision_id", "candidate_set_id", "ticker", "strategy_version", "source", "decision", "decision_date", "sector",
    "pit_certified", "horizon_days", "status", "status_reason", "entry_date", "exit_date", "gross_return",
    "net_return", "benchmark_return", "sector_etf_return", "net_excess_spy", "net_excess_sector",
]


def _nan(v: Any) -> float:
    return float("nan") if v is None else float(v)


def load_outcome_frame(
    session=None, horizon: int = PRIMARY_HORIZON_DAYS, *, strategy_version: Optional[str] = None,
    source: Optional[str] = None, cost_scenario: str = PRIMARY_COST_SCENARIO,
) -> pd.DataFrame:
    """결정별 1행(해당 horizon 의 결과를 왼쪽 조인)의 프레임. final 이 아닌 행의 수익 값은 NaN 이다.

    net_return 은 cost_scenario(편도 bp) 차감 후, net_excess_spy = net_return - benchmark_return,
    net_excess_sector = net_return - sector_etf_return(섹터 ETF 없으면 NaN).
    """
    from sqlalchemy import and_

    from core.models import CandidateDecision, CandidateOutcome

    if cost_scenario not in COST_SCENARIOS_BPS:
        raise ValueError(f"알 수 없는 cost_scenario: {cost_scenario}")
    col = f"net_return_{cost_scenario}"
    rows = []
    with _session_scope(session) as s:
        q = s.query(CandidateDecision, CandidateOutcome).outerjoin(
            CandidateOutcome,
            and_(CandidateOutcome.decision_id == CandidateDecision.id, CandidateOutcome.horizon_days == horizon))
        if strategy_version:
            q = q.filter(CandidateDecision.strategy_version == strategy_version)
        if source:
            q = q.filter(CandidateDecision.source == source)
        for d, o in q.order_by(CandidateDecision.id).all():
            final = o is not None and o.status == "final"
            net = _nan(getattr(o, col)) if final else float("nan")
            bench = _nan(o.benchmark_return) if final else float("nan")
            sect = _nan(o.sector_etf_return) if final else float("nan")
            nd = _ny_date(d.decision_cutoff)
            rows.append({
                "decision_id": d.id, "candidate_set_id": d.candidate_set_id, "ticker": d.ticker,
                "strategy_version": d.strategy_version, "source": d.source, "decision": d.decision,
                "decision_date": pd.Timestamp(nd) if nd else pd.NaT, "sector": d.sector,
                "pit_certified": bool(d.pit_certified), "horizon_days": horizon,
                "status": o.status if o is not None else "absent",
                "status_reason": o.status_reason if o is not None else None,
                "entry_date": o.entry_date if o is not None else None,
                "exit_date": o.exit_date if o is not None else None,
                "gross_return": _nan(o.gross_return) if final else float("nan"),
                "net_return": net, "benchmark_return": bench, "sector_etf_return": sect,
                "net_excess_spy": net - bench, "net_excess_sector": net - sect,
            })
    df = pd.DataFrame(rows, columns=FRAME_COLUMNS)
    df["decision_date"] = pd.to_datetime(df["decision_date"])
    df.attrs["cost_scenario"] = cost_scenario
    df.attrs["horizon_days"] = horizon
    return df


# ---------------------------------------------------------------------------
# 지표
# ---------------------------------------------------------------------------
def _pf_raw(values: Any, weights: Any = None) -> float:
    v = np.asarray(values, dtype=float)
    w = np.ones_like(v) if weights is None else np.asarray(weights, dtype=float)
    gains = float((w * np.clip(v, 0, None)).sum())
    losses = float((w * np.clip(-v, 0, None)).sum())
    if losses > 0:
        return gains / losses
    return math.inf if gains > 0 else math.nan


def _pf_fields(pf: float) -> dict:
    return {
        "profit_factor": None if (math.isinf(pf) or math.isnan(pf)) else pf,
        "profit_factor_infinite": bool(math.isinf(pf)),
    }


def summarize_values(values: Any) -> dict:
    """그룹 요약: n, 평균(비용 후 기대값), 승률(값>0), 분위수, 최대 손실(최솟값), 손익비(이익합/손실합)."""
    v = np.asarray(list(values) if not isinstance(values, np.ndarray) else values, dtype=float)
    v = v[~np.isnan(v)]
    if v.size == 0:
        return {"n": 0, "mean": None, "win_rate": None, "p05": None, "p25": None, "p50": None, "p75": None,
                "p95": None, "max_loss": None, "profit_factor": None, "profit_factor_infinite": False}
    q = np.quantile(v, [0.05, 0.25, 0.5, 0.75, 0.95])
    out = {
        "n": int(v.size), "mean": float(v.mean()), "win_rate": float((v > 0).mean()),
        "p05": float(q[0]), "p25": float(q[1]), "p50": float(q[2]), "p75": float(q[3]), "p95": float(q[4]),
        "max_loss": float(v.min()),
    }
    out.update(_pf_fields(_pf_raw(v)))
    return out


def _weighted_summary(values: np.ndarray, weights: np.ndarray) -> dict:
    tot = float(weights.sum())
    if tot <= 0:
        return {"n_eff": 0.0, "mean": None, "win_rate": None, "profit_factor": None, "profit_factor_infinite": False}
    out = {
        "n_eff": tot, "mean": float((weights * values).sum() / tot),
        "win_rate": float((weights * (values > 0)).sum() / tot),
    }
    out.update(_pf_fields(_pf_raw(values, weights)))
    return out


def _date_blocks(dates: pd.Series, block_days: int) -> np.ndarray:
    d = pd.to_datetime(dates, errors="coerce")
    if d.notna().sum() == 0:
        return np.full(len(d), -1, dtype=int)
    days = (d - d.min()).dt.days
    codes = np.where(d.notna(), np.floor(days.fillna(0).to_numpy(dtype=float) / block_days), -1)
    return codes.astype(int)


def _cluster_bootstrap(vals, is_sel, is_rest, pw, tcode, bcode, n_t, n_b, n_boot, rng) -> dict:
    """종목 x 날짜 블록 pigeonhole 부트스트랩(Owen 2007): 종목 군집과 날짜 블록을 각각 복원추출해 관측 가중치를
    (종목 횟수 x 블록 횟수)로 둔다. 두 방향 의존을 모두 반영하며 보수적(분산 과대)인 방향의 근사다.
    겹치는 label 기간은 블록 길이(>= horizon)로 완화할 뿐 purge/embargo 를 대체하지 않는다."""
    sel_f, rest_f = is_sel.astype(float), is_rest.astype(float)
    sv, rv, bv = sel_f * vals, rest_f * vals, pw * vals
    chunk = max(1, min(n_boot, int(2_000_000 // max(len(vals), 1))))
    res = {"sel": [], "rest": [], "base": []}
    done = 0
    while done < n_boot:
        m = min(chunk, n_boot - done)
        ct = rng.multinomial(n_t, np.full(n_t, 1.0 / n_t), size=m)
        cb = rng.multinomial(n_b, np.full(n_b, 1.0 / n_b), size=m)
        w = (ct[:, tcode] * cb[:, bcode]).astype(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            res["sel"].append((w @ sv) / (w @ sel_f))
            res["rest"].append((w @ rv) / (w @ rest_f))
            res["base"].append((w @ bv) / (w @ pw))
        done += m
    return {k: np.concatenate(v) for k, v in res.items()}


def _ci(arr: np.ndarray, alpha: float, n_boot: int) -> tuple[Optional[float], Optional[float]]:
    ok = arr[np.isfinite(arr)]
    if ok.size < max(1, int(0.9 * n_boot)):
        return None, None
    lo, hi = np.percentile(ok, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def _random_baseline_mc(vals, batch_ids, is_sel, n_draws: int, rng) -> Optional[dict]:
    """같은 선택률(배치별 채택 수 k_b)로 무작위 보류했을 때의 평균 분포(시드 고정 몬테카를로)."""
    totals, total_k = np.zeros(n_draws), 0
    for b in np.unique(batch_ids):
        mask = batch_ids == b
        vb = vals[mask]
        k = int(is_sel[mask].sum())
        m = vb.size
        if k == 0 or m == 0:
            continue
        if k >= m:
            totals += vb.sum()
        else:
            idx = np.argpartition(rng.random((n_draws, m)), k - 1, axis=1)[:, :k]
            totals += vb[idx].sum(axis=1)
        total_k += k
    if total_k == 0:
        return None
    means = totals / total_k
    sel_mean = float(vals[is_sel].mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {
        "n_draws": int(n_draws), "mean": float(means.mean()), "p025": float(lo), "p975": float(hi),
        "selected_mean": sel_mean,
        "p_random_ge_selected": float((1 + int((means >= sel_mean - 1e-15).sum())) / (n_draws + 1)),
        "note": "진단용 기술 통계(군집 의존 미반영). 판정은 군집 부트스트랩 신뢰구간만 사용한다.",
    }


def decide_verdict(
    ci_low: Optional[float], ci_high: Optional[float], *, horizon: int, target: str, cost_scenario: str,
    n_selected: int, n_ticker_clusters: int, n_date_blocks: int, pit_fraction: Optional[float],
    missing_rate: Optional[float], require_pit: bool = True,
) -> tuple[str, list[str]]:
    """판정 규칙을 코드로 강제한다. 어느 결함이라도 있거나 신뢰구간이 0을 포함하면 '미입증'.

    신뢰구간이 0을 배제하고 모든 게이트를 통과해도 결과는 '검토 대상'일 뿐(자동 채택/폐기 아님)이다.
    기각 검토는 더 큰 표본(MIN_SELECTED_FOR_REJECTION, MIN_DATE_BLOCKS_FOR_REJECTION)을 추가로 요구한다.
    """
    reasons: list[str] = []
    if horizon != PRIMARY_HORIZON_DAYS:
        reasons.append("diagnostic_horizon_not_verdict_bearing")
    if target != PRIMARY_TARGET:
        reasons.append("non_primary_target")
    if cost_scenario != PRIMARY_COST_SCENARIO:
        reasons.append("non_primary_cost_scenario")
    if n_selected <= 0:
        reasons.append("no_selected_outcomes")
    elif (n_selected < MIN_SELECTED_FOR_VERDICT or n_ticker_clusters < MIN_TICKER_CLUSTERS_FOR_VERDICT
          or n_date_blocks < MIN_DATE_BLOCKS_FOR_VERDICT):
        reasons.append(f"insufficient_sample(n_selected={n_selected},ticker_clusters={n_ticker_clusters},"
                       f"date_blocks={n_date_blocks})")
    if ci_low is None or ci_high is None:
        reasons.append("ci_unavailable")
    elif ci_low <= 0 <= ci_high:
        reasons.append("ci_includes_zero")
    if require_pit and (pit_fraction is None or pit_fraction < 1.0):
        reasons.append("not_pit_certified")
    if missing_rate is not None and missing_rate > MAX_MISSING_OUTCOME_RATE:
        reasons.append("high_outcome_missing_rate")
    if reasons:
        return VERDICT_UNPROVEN, reasons
    if ci_low > 0:
        return VERDICT_POSITIVE_REVIEW, []
    if n_selected < MIN_SELECTED_FOR_REJECTION or n_date_blocks < MIN_DATE_BLOCKS_FOR_REJECTION:
        return VERDICT_UNPROVEN, ["below_power_threshold_for_rejection"]
    return VERDICT_REJECT_REVIEW, []


def evaluate_selection(
    frame: pd.DataFrame, *, horizon: int = PRIMARY_HORIZON_DAYS, value_col: str = PRIMARY_TARGET,
    cost_scenario: Optional[str] = None, n_boot: int = DEFAULT_N_BOOT, n_random_draws: int = DEFAULT_N_RANDOM_DRAWS,
    seed: int = BOOTSTRAP_SEED, require_pit: bool = True, alpha: float = 0.05,
    eligible_decisions: Sequence[str] = ELIGIBLE_DECISIONS, rest_decisions: Sequence[str] = REST_DECISIONS,
) -> dict:
    """채택 vs 보류/거절의 비용 후 성과를 같은 계약으로 비교하고 판정 규칙을 적용한다.

    frame 은 load_outcome_frame 결과(또는 같은 컬럼을 가진 프레임): decision, ticker, candidate_set_id,
    decision_date, pit_certified, value_col. value_col 이 NaN 인 행은 결측으로 세고 평균에서 제외한다(0 처리 안 함).
    """
    cost_scenario = cost_scenario or frame.attrs.get("cost_scenario", PRIMARY_COST_SCENARIO)
    df = frame.copy().reset_index(drop=True)
    for col, default in (("candidate_set_id", "_all"), ("ticker", ""), ("decision_date", pd.NaT),
                         ("pit_certified", False)):
        if col not in df.columns:
            df[col] = default
    v = pd.to_numeric(df[value_col], errors="coerce")
    has = v.notna()

    n_decisions = {d: int((df["decision"] == d).sum()) for d in DECISIONS}
    n_missing_outcome = {d: int(((df["decision"] == d) & ~has).sum()) for d in DECISIONS}
    missing_rate = float((~has).sum() / len(df)) if len(df) else 0.0

    elig_mask = df["decision"].isin(eligible_decisions) & has
    E = df[elig_mask].copy()
    E["_v"] = v[elig_mask]
    vals = E["_v"].to_numpy(dtype=float)
    is_sel = (E["decision"] == "selected").to_numpy()
    is_rest = E["decision"].isin(rest_decisions).to_numpy()
    batch = E["candidate_set_id"].astype(str)
    m_b = batch.map(batch.value_counts()).to_numpy(dtype=float) if len(E) else np.array([])
    k_b = batch.map(batch[is_sel].value_counts()).fillna(0).to_numpy(dtype=float) if len(E) else np.array([])
    pw = k_b / m_b if len(E) else np.array([])

    n_sel = int(is_sel.sum())
    coverage = (n_sel / len(E)) if len(E) else None
    sel_summary = summarize_values(vals[is_sel])
    rest_summary = summarize_values(vals[is_rest])
    miss_grp = df[(df["decision"] == "missing_data") & has]
    base_summary = _weighted_summary(vals, pw) if len(E) else _weighted_summary(np.array([]), np.array([]))
    by_decision = {
        d: (float(vals[(E["decision"] == d).to_numpy()].mean()) if ((E["decision"] == d).any()) else None)
        for d in rest_decisions
    }
    missed = {
        "mean_excess": rest_summary["mean"], "n": rest_summary["n"], "by_decision": by_decision,
        "note": "보류·거절 후보의 평균(주 대상) 값. 양수이면 채택하지 않아 놓친 기회가 있었다는 뜻.",
    }

    # 군집 부트스트랩
    inc: dict = {"selected_minus_random": None, "selected_minus_rest": None, "selected_ev": None}
    block_days = int(math.ceil(horizon * 7 / 5))
    tcode = bcode = None
    n_sel_tickers = n_sel_blocks = 0
    if len(E):
        tcode, tuniq = pd.factorize(E["ticker"].astype(str))
        bcode_raw = _date_blocks(E["decision_date"], block_days)
        bcode, buniq = pd.factorize(bcode_raw)
        n_sel_tickers = int(len(np.unique(tcode[is_sel]))) if n_sel else 0
        n_sel_blocks = int(len(np.unique(bcode[is_sel]))) if n_sel else 0
    meta_ci = {"n_boot": int(n_boot), "seed": int(seed), "alpha": alpha,
               "n_ticker_clusters": n_sel_tickers, "n_date_blocks": n_sel_blocks, "block_days": block_days,
               "method": "pigeonhole two-way cluster bootstrap (ticker x date-block), percentile CI"}
    est_random = est_rest = est_sel = None
    if n_sel and len(E):
        est_sel = float(vals[is_sel].mean())
        est_random = est_sel - float((pw * vals).sum() / pw.sum())
        est_rest = (est_sel - float(vals[is_rest].mean())) if is_rest.any() else None
        rng = np.random.default_rng(seed)
        boot = _cluster_bootstrap(vals, is_sel, is_rest, pw, tcode, bcode, len(tuniq), len(buniq), n_boot, rng)
        lo, hi = _ci(boot["sel"] - boot["base"], alpha, n_boot)
        inc["selected_minus_random"] = {"estimate": est_random, "ci_low": lo, "ci_high": hi, **meta_ci}
        lo_r, hi_r = _ci(boot["sel"] - boot["rest"], alpha, n_boot)
        inc["selected_minus_rest"] = {"estimate": est_rest, "ci_low": lo_r, "ci_high": hi_r, **meta_ci}
        lo_s, hi_s = _ci(boot["sel"], alpha, n_boot)
        inc["selected_ev"] = {"estimate": est_sel, "ci_low": lo_s, "ci_high": hi_s, **meta_ci}
    mc = None
    if n_sel and len(E):
        mc = _random_baseline_mc(vals, batch.to_numpy(), is_sel, n_random_draws, np.random.default_rng([seed, 1]))
        if mc is not None:
            mc["seed"] = int(seed)

    ci_low = inc["selected_minus_random"]["ci_low"] if inc["selected_minus_random"] else None
    ci_high = inc["selected_minus_random"]["ci_high"] if inc["selected_minus_random"] else None
    pit_fraction = float(E["pit_certified"].astype(bool).mean()) if len(E) else None

    verdict, reasons = decide_verdict(
        ci_low, ci_high, horizon=horizon, target=value_col, cost_scenario=cost_scenario, n_selected=n_sel,
        n_ticker_clusters=n_sel_tickers, n_date_blocks=n_sel_blocks, pit_fraction=pit_fraction,
        missing_rate=missing_rate, require_pit=require_pit)

    # 경고: 승률만 올라 선택률로 설명되는 경우
    warnings: list[str] = []
    wr_sel, wr_base = sel_summary["win_rate"], base_summary["win_rate"]
    win_up = wr_sel is not None and wr_base is not None and wr_sel > wr_base + 1e-12
    ev_improved = ci_low is not None and ci_low > 0
    pf_sel = _pf_raw(vals[is_sel]) if n_sel else math.nan
    pf_base = _pf_raw(vals, pw) if len(E) else math.nan
    pf_improved = bool(pf_sel > pf_base)  # NaN 비교는 False
    win_rate_warning = bool(win_up and coverage is not None and coverage < 1.0 and not (ev_improved and pf_improved))
    if win_rate_warning:
        warnings.append(
            f"승률이 동일 선택률 무작위 보류 기준선보다 높지만(채택 {wr_sel:.1%} vs 기준선 {wr_base:.1%}, 선택률 {coverage:.1%}) "
            "비용 후 기대값·손익비 개선이 신뢰구간으로 입증되지 않았다. 선택률 하락(덜 거래함)으로 설명될 수 있어 개선으로 읽지 않는다.")
    rest_outperformed = bool(rest_summary["mean"] is not None and sel_summary["mean"] is not None
                             and rest_summary["mean"] > sel_summary["mean"])
    if rest_outperformed:
        warnings.append("보류·거절 후보의 평균이 채택 후보보다 높다(놓친 기회 비용이 채택 성과보다 크다).")
    high_missing = missing_rate > MAX_MISSING_OUTCOME_RATE
    if high_missing:
        warnings.append(f"결과 결측률 {missing_rate:.1%} — 상장폐지/데이터 결측이 결과를 왜곡할 수 있다.")
    if pit_fraction is not None and pit_fraction < 1.0:
        warnings.append(f"PIT 인증 비율 {pit_fraction:.0%} — 시간 계약이 불완전해 판정은 '미입증'으로 제한된다.")

    role = "primary" if horizon == PRIMARY_HORIZON_DAYS else "diagnostic"
    return {
        "horizon_days": horizon, "role": role, "multiple_testing": role == "diagnostic",
        "target": value_col, "cost_scenario": cost_scenario, "require_pit": require_pit,
        "n_decisions": n_decisions, "n_missing_outcome": n_missing_outcome, "missing_outcome_rate": missing_rate,
        "coverage": coverage,
        "groups": {
            "selected": sel_summary, "rest": rest_summary, "missing_data": summarize_values(miss_grp[value_col]
                                                                                             if len(miss_grp) else []),
            "random_baseline_expected": base_summary,
        },
        "missed_opportunity": missed, "incremental": inc, "random_baseline_mc": mc,
        "pit_certified_fraction": pit_fraction,
        "warnings": warnings,
        "warning_flags": {
            "win_rate_selectivity": win_rate_warning, "high_missing_rate": high_missing,
            "not_pit_certified": bool(pit_fraction is None or pit_fraction < 1.0),
            "insufficient_sample": any(r.startswith("insufficient_sample") for r in reasons),
            "rest_outperformed_selected": rest_outperformed,
        },
        "verdict": verdict, "verdict_reasons": reasons, "auto_decision": False,
        "requires_human_approval": verdict != VERDICT_UNPROVEN,
    }


def build_ledger_report(
    session=None, *, strategy_version: Optional[str] = None, source: Optional[str] = None,
    horizons: Sequence[int] = ALL_HORIZONS, cost_scenario: str = PRIMARY_COST_SCENARIO, **eval_kwargs,
) -> dict:
    """주 horizon(판정 가능) 1개와 진단 horizon 들(다중검정 표시)의 평가를 한 번에 만든다."""
    hs = sorted(set(int(h) for h in horizons) | {PRIMARY_HORIZON_DAYS})
    with _session_scope(session) as s:
        frames = {h: load_outcome_frame(s, h, strategy_version=strategy_version, source=source,
                                        cost_scenario=cost_scenario) for h in hs}
    primary = evaluate_selection(frames[PRIMARY_HORIZON_DAYS], horizon=PRIMARY_HORIZON_DAYS,
                                 cost_scenario=cost_scenario, **eval_kwargs)
    diagnostics = [evaluate_selection(frames[h], horizon=h, cost_scenario=cost_scenario, **eval_kwargs)
                   for h in hs if h != PRIMARY_HORIZON_DAYS]
    return {
        "ledger_version": LEDGER_VERSION, "strategy_version": strategy_version, "source": source,
        "rules": {
            "primary_horizon_days": PRIMARY_HORIZON_DAYS, "diagnostic_horizons": list(DIAGNOSTIC_HORIZONS),
            "primary_target": PRIMARY_TARGET, "primary_cost_scenario": PRIMARY_COST_SCENARIO,
            "benchmark": BENCHMARK_TICKER, "entry_rule": ENTRY_RULE, "exit_rule": EXIT_RULE,
            "price_basis": PRICE_BASIS,
        },
        "primary": primary, "diagnostics": diagnostics, "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# 어댑터 (순수 함수: 기존 모듈의 결과 -> 후보 집합). 기존 모듈은 수정하지 않는다.
# ---------------------------------------------------------------------------
def _clean_value(v: Any) -> Any:
    if isinstance(v, (list, tuple, set, np.ndarray)):
        return list(v)
    return None if _isnull(v) else v


def _list_of(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set, np.ndarray, pd.Series)):
        return list(v)
    return [] if _isnull(v) else [v]


def _ticker_list(x: Any) -> list[str]:
    if x is None:
        return []
    if isinstance(x, pd.DataFrame):
        return [str(t) for t in x["ticker"].tolist()] if "ticker" in x.columns else []
    return [str(t) for t in _list_of(x)]


def _time_kwargs(time_contract: Optional[dict]) -> dict:
    allowed = ("source_publication", "system_first_seen", "extraction_completed")
    return {k: v for k, v in (time_contract or {}).items() if k in allowed}


def stock_discovery_to_candidate_set(
    df: pd.DataFrame, *, strategy_version: str, decision_cutoff: Any, selected_n: Optional[int] = None,
    min_composite_score: Optional[float] = None, max_missing_factors: int = DEFAULT_MAX_MISSING_FACTORS,
    order_proposals: Optional[dict] = None, time_contract: Optional[dict] = None, source: str = "stock_discovery",
) -> FrozenCandidateSet:
    """core.stock_discovery.discover_candidates 결과 -> 후보 집합.

    판단 규칙(어댑터 정책, 원전략 순위를 바꾸지 않는다): composite_score 내림차순 rank. 채택 = rank <= selected_n
    (None 이면 df 의 모든 행이 이미 채택 집합이라고 본다) 이고 점수 >= min_composite_score(주어졌을 때).
    미채택 중 결측(data_errors 에 price_history/fundamentals/valuation_inputs 가 있거나 결측 팩터 수 >=
    max_missing_factors, 점수 NaN)은 missing_data, 점수 미달은 rejected, 나머지는 held. 원전략이 채택한 행은
    결측이 있어도 selected 로 기록하고 결측 사실은 점수 JSON 에 남긴다. df 는 보통 top_n 으로 잘려 있어 전체 후보
    집합을 기록하려면 호출부가 더 큰 top_n 으로 실행해야 한다. meta(df.attrs['meta'])의 pit_verified=False 를 보존한다.
    """
    meta = _jsonable(dict(df.attrs.get("meta", {}))) if df is not None else {}
    meta.update({"adapter": "stock_discovery", "selected_n": selected_n, "min_composite_score": min_composite_score,
                 "max_missing_factors": max_missing_factors})
    if df is None or df.empty:
        return FrozenCandidateSet(source, strategy_version, decision_cutoff, [], meta)
    d = df.copy()
    d["_score"] = pd.to_numeric(d["composite_score"], errors="coerce")
    d = d.sort_values(["_score", "ticker"], ascending=[False, True], kind="mergesort", na_position="last")
    d = d.reset_index(drop=True)
    score_cols = [c for c in (
        "composite_score", "momentum_score", "growth_score", "value_score", "quality_score",
        "momentum_contrib", "growth_contrib", "value_contrib", "quality_contrib", "trailing_pe", "price_to_book",
        "earnings_growth", "market_cap", "n_missing_factors", "missing_factors", "sector_rank_fallback",
        "fallback_flags", "data_errors") if c in d.columns]
    hard_errors = {"price_history", "fundamentals", "valuation_inputs"}
    records = []
    for i, r in d.iterrows():
        rank = i + 1
        score = r["_score"]
        errors = [str(e) for e in _list_of(r.get("data_errors"))]
        n_missing = 0 if _isnull(r.get("n_missing_factors")) else int(r.get("n_missing_factors"))
        missing_factors = [str(x) for x in _list_of(r.get("missing_factors"))]
        bad_errors = sorted(hard_errors & set(errors))
        if _isnull(score):
            rank = None
        selected = (not _isnull(score)) and (selected_n is None or rank <= selected_n) and (
            min_composite_score is None or score >= min_composite_score)
        if selected:
            decision = "selected"
            reason = "all_rows_selected" if selected_n is None else f"top_n_selected(rank={rank}<={selected_n})"
        elif bad_errors or _isnull(score) or n_missing >= max_missing_factors:
            decision = "missing_data"
            parts = []
            if bad_errors:
                parts.append("data_errors:" + ",".join(bad_errors))
            if _isnull(score):
                parts.append("composite_score_missing")
            if n_missing >= max_missing_factors:
                parts.append(f"missing_factors({n_missing}>={max_missing_factors}):" + ",".join(missing_factors))
            reason = "; ".join(parts)
        elif min_composite_score is not None and score < min_composite_score:
            decision, reason = "rejected", f"below_min_composite_score({score:.2f}<{min_composite_score})"
        else:
            decision, reason = "held", f"below_top_n_cutoff(rank={rank}>{selected_n})"
        records.append(CandidateRecord(
            ticker=r["ticker"], decision=decision, decision_reason=reason,
            scores={c: _clean_value(r[c]) for c in score_cols}, rank=rank,
            order_proposal=(order_proposals or {}).get(r["ticker"]) if decision == "selected" else None,
            sector=None if _isnull(r.get("sector")) else r.get("sector"), **_time_kwargs(time_contract)))
    return FrozenCandidateSet(source, strategy_version, decision_cutoff, records, meta)


def _theme_proxy(theme: Optional[str]) -> Optional[str]:
    try:
        from core.sector_strength import THEME_UNIVERSE

        proxies = THEME_UNIVERSE.get(theme) or []
        return proxies[0] if proxies else None
    except Exception:  # noqa: BLE001 - 테마 ETF 조회 실패는 섹터 잔차 결측으로만 남는다
        return None


def _pool_items(pool: Any) -> Optional[list[dict]]:
    if pool is None:
        return None
    if isinstance(pool, pd.DataFrame):
        return pool.to_dict("records")
    return [{"ticker": x} if isinstance(x, str) else dict(x) for x in pool]


def sector_leaders_to_candidate_set(
    result: dict, *, strategy_version: str, decision_cutoff: Any, pool: Any = None,
    time_contract: Optional[dict] = None, source: str = "sector_leaders",
) -> FrozenCandidateSet:
    """core.sector_leaders.compute_leader_and_growth / analyze_theme_relationships 결과 -> 후보 집합.

    대장주(leader)와 성장주(growth_stocks)는 selected. 결과 dict 는 미채택 후보를 담지 않으므로 호출부가 후보 풀
    (티커 목록/딕셔너리 목록/DataFrame)을 pool 로 넘기면 미채택은 held, 성장 데이터 결측(growth_data_missing=True 또는
    earnings_growth 결측)은 missing_data 로 기록한다. pool 이 없으면 채택만 기록되며 meta['pool_recorded']=False 로
    반사실 비교가 불가능함을 명시한다. 섹터 ETF 는 result['proxies'][0](없으면 THEME_UNIVERSE)이다.
    """
    theme = result.get("theme")
    proxies = result.get("proxies") or []
    sector_etf = proxies[0] if proxies else _theme_proxy(theme)
    tk = _time_kwargs(time_contract)
    records: list[CandidateRecord] = []
    seen: set[str] = set()

    def _add_selected(item: dict, role: str) -> None:
        t = str(item.get("ticker", "")).strip().upper()
        if not t or t in seen:
            return
        seen.add(t)
        scores = {k: _clean_value(v) for k, v in item.items() if k not in ("ticker", "name")}
        scores["role"] = role
        records.append(CandidateRecord(
            t, "selected", f"{role}_selected(theme={theme})", scores=scores, rank=len(records) + 1,
            sector=theme, sector_etf=sector_etf, **tk))

    if result.get("leader"):
        _add_selected(result["leader"], "leader")
    for g in result.get("growth_stocks") or []:
        _add_selected(g, "growth")

    items = _pool_items(pool)
    if items is not None:
        for it in items:
            t = str(it.get("ticker", "")).strip().upper()
            if not t or t in seen:
                continue
            seen.add(t)
            gm = it.get("growth_data_missing")
            missing = (gm is True) or (gm is None and "earnings_growth" in it and _isnull(it.get("earnings_growth")))
            scores = {k: _clean_value(v) for k, v in it.items() if k not in ("ticker", "name")}
            if missing:
                decision, reason = "missing_data", "growth_data_missing_in_theme_pool"
            else:
                decision, reason = "held", "not_selected_in_theme_pool"
            records.append(CandidateRecord(t, decision, reason, scores=scores, sector=theme,
                                           sector_etf=sector_etf, **tk))
    meta = {"adapter": "sector_leaders", "theme": theme, "pool_recorded": items is not None,
            "candidates_count": result.get("candidates_count"), "sector_etf": sector_etf,
            "note": "대장주/성장주는 분석 화면의 선정이며 주문이 아니다. 채택=모듈이 고른 후보."}
    return FrozenCandidateSet(source, strategy_version, decision_cutoff if decision_cutoff is not None else None,
                              records, _jsonable(meta))


def champion_satellite_to_candidate_set(
    result: dict, *, strategy_version: str, decision_cutoff: Any = None, missing_tickers: Optional[Iterable[str]] = None,
    rejected_tickers: Optional[Iterable[str]] = None, sectors: Optional[dict] = None,
    time_contract: Optional[dict] = None, source: str = "champion_satellite",
) -> FrozenCandidateSet:
    """챔피언 위성 후보 집합 -> 후보 집합. 세 가지 결과 형식을 받는다.

    1) core.champion_strategy.compute_satellite_recommendation(라이브 스캔): candidates(돌파 후보 DataFrame, 3개월 모멘텀
       순), selected, per_ticker_weights. 돌파 후보 중 top-N 밖은 held.
    2) compute_satellite_recommendation_point_in_time: selected, per_ticker_weights, picks(DataFrame, 채택 종목). 후보 풀 없음.
       new_orders_allowed=False 이면 원전략이 골랐어도 주문이 보류된 것이므로 held 로 기록한다.
    3) _pick_satellite_at_date 원형(date/picks 리스트/weights=슬리브 내 비중). 후보 풀 없음.
    missing_tickers(스캔 중 이력 부족/조회 실패)는 missing_data, rejected_tickers(돌파 없음)는 rejected 로 호출부가 넘긴 것만
    기록한다. 결정 시각은 인자, 없으면 result['as_of'] 또는 result['date'](날짜만 -> 종가 이후) 에서 유도한다.
    """
    cutoff = decision_cutoff if decision_cutoff is not None else (result.get("as_of") or result.get("date"))
    if cutoff is None:
        raise ValueError("decision_cutoff 를 인자로 주거나 result 에 as_of/date 가 있어야 합니다")
    tk = _time_kwargs(time_contract)
    sectors = sectors or {}
    selected = _ticker_list(result.get("selected") if result.get("selected") is not None else result.get("picks"))
    portfolio_w = result.get("per_ticker_weights") or {}
    sleeve_w = result.get("weights") or {}
    sizing = result.get("sizing_method")
    blocked = result.get("new_orders_allowed") is False
    cands = result.get("candidates")
    cand_rows = cands.to_dict("records") if isinstance(cands, pd.DataFrame) and "ticker" in cands.columns else None

    def _proposal(t: str) -> Optional[dict]:
        if blocked:
            return None
        if t in portfolio_w:
            p = {"target_weight": portfolio_w[t], "sleeve": "satellite"}
        elif t in sleeve_w:
            p = {"sleeve_weight": sleeve_w[t], "sleeve": "satellite"}
        else:
            return None
        if sizing:
            p["sizing_method"] = sizing
        return p

    def _rec(t: str, decision: str, reason: str, scores: dict, rank: Optional[int]) -> CandidateRecord:
        return CandidateRecord(t, decision, reason, scores=scores, rank=rank,
                               order_proposal=_proposal(t) if decision == "selected" else None,
                               sector=sectors.get(t), **tk)

    records: list[CandidateRecord] = []
    seen: set[str] = set()
    sel_set = {t.upper() for t in selected}

    def _decide_for_selected(t: str, scores: dict, rank: Optional[int]) -> CandidateRecord:
        if blocked:
            return _rec(t, "held", f"new_orders_blocked: {result.get('allocation_reason', '')}".strip(), scores, rank)
        return _rec(t, "selected", "satellite_top_n_selected", scores, rank)

    if cand_rows is not None:
        for i, row in enumerate(cand_rows, start=1):
            t = str(row["ticker"]).strip().upper()
            if t in seen:
                continue
            seen.add(t)
            scores = {k: _clean_value(v) for k, v in row.items() if k != "ticker"}
            scores["donchian_breakout"] = True
            if t in sel_set:
                records.append(_decide_for_selected(t, scores, i))
            else:
                records.append(_rec(t, "held", f"breakout_below_top_n(rank={i})", scores, i))
    for i, t in enumerate(selected, start=1):
        t = t.strip().upper()
        if t in seen:
            continue
        seen.add(t)
        records.append(_decide_for_selected(t, {}, i))
    for t in _ticker_list(missing_tickers):
        t = t.strip().upper()
        if t not in seen:
            seen.add(t)
            records.append(_rec(t, "missing_data", "history_unavailable_or_short", {}, None))
    for t in _ticker_list(rejected_tickers):
        t = t.strip().upper()
        if t not in seen:
            seen.add(t)
            records.append(_rec(t, "rejected", "no_donchian_breakout", {}, None))
    meta = {
        "adapter": "champion_satellite", "pool_recorded": cand_rows is not None, "sizing_method": sizing,
        "as_of": result.get("as_of") or result.get("date"), "rebal_date": result.get("rebal_date"),
        "scanned_count": result.get("scanned_count"), "pool_size": result.get("pool_size"),
        "n_active_trend": result.get("n_active_trend"), "new_orders_allowed": result.get("new_orders_allowed"),
        "allocation_reason": result.get("allocation_reason"),
    }
    return FrozenCandidateSet(source, strategy_version, cutoff, records, _jsonable(meta))
