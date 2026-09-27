"""RES-04 가이던스 shadow 실험용 **실제 SEC 데이터 공급기**(2026-09-24).

core/guidance_shadow.py 의 record_guidance_shadow(events_by_ticker=...) 에 넣을 GuidanceObservation 목록을
실제 SEC EDGAR 자료로 만든다. 파싱·비교 로직은 하나도 새로 만들지 않는다 — 전부 기존 모듈을 호출한다:

    티커 -> core.filing_changes.EdgarClient.resolve_cik (SEC company_tickers.json)
         -> core.earnings_events.list_earnings_filings (8-K Item 2.02 목록, acceptance 시각)
         -> core.earnings_events.extract_from_filing (EX-99.1 보도자료 -> 규칙 기반 가이던스 추출)
         -> core.earnings_events.compute_guidance_changes (직전 가이던스와 비교 -> raised/lowered/...;
            방향은 연간 가이던스의 같은 회계연도 재발표끼리만, 분기는 unknown(quarterly_not_comparable))
         -> core.guidance_shadow.GuidanceObservation

안전장치(이 모듈의 존재 이유):
    (a) 하루 단위 파일 캐시: 같은 as_of 로 다시 호출하면 네트워크를 다시 때리지 않는다. 캐시가 다 맞으면
        HTTP 클라이언트 자체를 만들지 않는다.
    (b) 요청 속도: 기존 두 클라이언트의 기본 제한(core.earnings_events 는 요청 간 0.25초 = 초당 4회,
        core.filing_changes.RateLimiter 기본값)을 그대로 쓴다. 이 모듈은 제한을 새로 만들거나 풀지 않고,
        주입된 클라이언트도 초당 5회 상한을 넘지 않는지 확인한다.
    (c) 티커 하나가 실패해도 나머지는 계속 처리하고, 실패 사유를 결과(outcomes/failures)에 남긴다.
        단 403 등 접근 차단은 예외다 — 차단 상태에서 계속 두드리면 상황이 나빠지므로 즉시 중단하고
        남은 티커를 'aborted_sec_access_blocked' 로 남긴다.
    (d) User-Agent 는 core.earnings_events.get_user_agent()(SEC_EDGAR_USER_AGENT -> SEC_USER_AGENT ->
        개인정보 없는 기본값) 를 그대로 쓰며, 값은 이 모듈이 절대 출력·기록·캐시하지 않는다.
    (e) max_tickers(기본 20)로 한 번에 조회할 티커 수를 제한한다. 초과분은 조회하지 않고
        'skipped_max_tickers' 로 남긴다 — 느린 전체 스캔을 하지 않는다.
    (f) (2026-09-25 추가, 야간 잡 배선용) time_budget_seconds / max_network_requests 로 한 번 실행의 전체
        소요 시간과 SEC 요청 수에 상한을 둔다. 둘 다 **티커와 티커 사이**에서 검사하는 소프트 상한이다 —
        이미 시작한 티커 하나는 끝까지 처리하므로 최대 초과량은 티커 1개 분량(8-K 최대
        max_filings_per_ticker 건 x 요청 2회 + submissions 1회, 재시도 포함)이다. 상한에 걸리면 남은
        티커를 'skipped_budget' 으로 남기고 조회하지 않는다. 기본값(None)은 기존 동작(상한 없음) 그대로다.

주문 경로(core.paper_execution, scripts/champion_paper_trade.py)·스케줄러·DB 는 import 도 호출도 하지 않는다.
성과를 주장하지 않는 관측 전용 모듈이다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import time
from typing import Any, Callable, Optional, Sequence

from core.earnings_events import (
    COMPARISON_POLICY,
    MAX_REQUESTS_PER_SECOND,
    EarningsFiling,
    GuidanceChange,
    GuidanceItem,
    SecAccessError,
    SecEdgarClient,
    compute_guidance_changes,
    extract_from_filing,
    list_earnings_filings,
)
from core.guidance_shadow import GuidanceObservation

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "guidance_events"

# (e) 한 번에 조회할 티커 수 상한. 위성 채택 종목(보통 5~10개)에 여유를 둔 값.
DEFAULT_MAX_TICKERS = 20
# 관측 창: guidance_shadow 의 주 룩백(20거래일 ~= 28일)에 여유를 둔 달력일. 창 안의 발표만 관측이 된다.
DEFAULT_WINDOW_DAYS = 45
# 직전 가이던스를 찾기 위한 과거 조회 범위(4분기 + 여유). 비교 대상이 없으면 change 가 unknown/initiated 가 된다.
# 2026-09-25 점검(스펙 3·6절): 방향 판정은 연간 가이던스의 같은 회계연도 재발표끼리만 한다. 같은 FY 는 보통
# 직전 분기 발표(약 90일 전)에서 이미 한 번 나오고, 한 FY 의 첫 발표~마지막 재발표 간격도 약 9~10개월이라
# 400일·6건이면 충분하다(관측 창 45일 + 직전 발표 1~3건). 그래서 기본값을 바꾸지 않았다.
DEFAULT_HISTORY_DAYS = 400
# 티커당 내려받는 8-K Item 2.02 수 상한(1건당 요청 2회: 인덱스 + 보도자료). 티커당 최대 요청 = 1(submissions)
# + 2 x 6 = 13, 20티커면 260회로 야간 상한 300회 안이다(보도자료·인덱스는 영구 캐시라 평시엔 훨씬 적다).
DEFAULT_MAX_FILINGS_PER_TICKER = 6

STATUS_OK = "ok"
STATUS_CACHED = "ok_cached"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped_max_tickers"
STATUS_ABORTED = "aborted_sec_access_blocked"
STATUS_SKIPPED_BUDGET = "skipped_budget"

# 다시 조회해도 오늘 결과가 달라지지 않는 사유만 캐시한다(네트워크 오류·차단·속도제한은 캐시하지 않는다).
_CACHEABLE_FAIL_REASONS = ("ticker_not_found", "no_earnings_filings")

# 2: 비교 정책 annual_same_fy_v1 과 판정 근거 필드 추가(옛 정책으로 만든 같은 날 캐시를 재사용하지 않는다).
_CACHE_FORMAT = 2


# ---------------------------------------------------------------------------
# 결과 구조
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TickerFetchOutcome:
    """티커 1개 처리 결과. reason 에는 민감값(User-Agent 등)을 절대 담지 않는다."""

    ticker: str
    status: str  # ok / ok_cached / failed / skipped_max_tickers / aborted_sec_access_blocked / skipped_budget
    n_observations: int = 0
    reason: Optional[str] = None
    n_filings_examined: int = 0

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_OK, STATUS_CACHED)


@dataclass(frozen=True)
class GuidanceEventFetchResult:
    events_by_ticker: dict
    outcomes: tuple
    meta: dict

    @property
    def failures(self) -> dict:
        return {o.ticker: (o.reason or o.status) for o in self.outcomes if not o.ok}

    @property
    def n_network_requests(self) -> int:
        return int(self.meta.get("n_network_requests", 0))


# ---------------------------------------------------------------------------
# 직렬화 (캐시용) — GuidanceItem.to_record() 의 역함수. 새 파싱 규칙이 아니라 캐시 왕복용이다.
# ---------------------------------------------------------------------------
def _dec(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _item_from_record(rec: dict) -> GuidanceItem:
    prior = rec.get("prior_stated")
    return GuidanceItem(
        cik=rec.get("cik"), accession=rec.get("accession"), acceptance_utc=_dt(rec.get("acceptance_utc")),
        source_url=rec.get("source_url"), metric=rec.get("metric") or "", basis=rec.get("basis") or "unspecified",
        period_key=rec.get("period_key"), period_raw=rec.get("period_raw"), shape=rec.get("shape") or "point",
        low=_dec(rec.get("low")), high=_dec(rec.get("high")), unit=rec.get("unit"), currency=rec.get("currency"),
        anchor=rec.get("anchor") or "", flags=tuple(rec.get("flags") or ()),
        stated_action=rec.get("stated_action"),
        prior_stated=None if not prior else (_dec(prior[0]), _dec(prior[1])),
    )


def _num(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format(value, "f")


def _observation_to_record(obs: GuidanceObservation) -> dict:
    chg = obs.change
    return {
        "ticker": obs.ticker,
        "available_at": obs.available_at.isoformat() if obs.available_at else None,
        "approximate": bool(obs.approximate),
        "content_sha256": obs.content_sha256,
        "change": {
            "change": chg.change, "reason": chg.reason,
            "current": chg.current.to_record(),
            "previous": chg.previous.to_record() if chg.previous is not None else None,
            "mid_change": _num(chg.mid_change), "mid_change_pct": _num(chg.mid_change_pct),
            "width_old": _num(chg.width_old), "width_new": _num(chg.width_new),
            "flags": list(chg.flags),
            # 판정 근거(2026-09-25 추가). previous_* 는 previous 레코드에서 다시 계산되므로 읽을 때 쓰지 않는다.
            "reason_detail": chg.reason_detail, "comparison_method": chg.comparison_method,
            "period_type": chg.period_type, "policy": chg.policy,
            "evidence": chg.evidence(),
        },
    }


def _observation_from_record(rec: dict) -> GuidanceObservation:
    c = rec.get("change") or {}
    change = GuidanceChange(
        change=c.get("change") or "unknown", reason=c.get("reason") or "",
        current=_item_from_record(c.get("current") or {}),
        previous=_item_from_record(c["previous"]) if c.get("previous") else None,
        mid_change=_dec(c.get("mid_change")), mid_change_pct=_dec(c.get("mid_change_pct")),
        width_old=_dec(c.get("width_old")), width_new=_dec(c.get("width_new")),
        flags=tuple(c.get("flags") or ()),
        reason_detail=c.get("reason_detail"), comparison_method=c.get("comparison_method"),
        period_type=c.get("period_type"), policy=c.get("policy"),
    )
    return GuidanceObservation(ticker=rec.get("ticker") or "", change=change,
                               available_at=_dt(rec.get("available_at")),
                               approximate=bool(rec.get("approximate", True)),
                               content_sha256=rec.get("content_sha256") or None)


# ---------------------------------------------------------------------------
# (a) 하루 단위 파일 캐시
# ---------------------------------------------------------------------------
def _safe_ticker(ticker: str) -> str:
    return re.sub(r"[^A-Z0-9._-]", "_", str(ticker).strip().upper())[:20] or "UNKNOWN"


class _DayCache:
    """as_of 날짜별 티커 파일 캐시. 같은 날 같은 파라미터면 네트워크를 다시 때리지 않는다."""

    def __init__(self, cache_dir: Path, as_of: date, params: dict, *, enabled: bool = True):
        self.dir = Path(cache_dir) / as_of.isoformat()
        self.params = params
        self.enabled = enabled

    def _path(self, ticker: str) -> Path:
        return self.dir / f"{_safe_ticker(ticker)}.json"

    def read(self, ticker: str) -> Optional[dict]:
        if not self.enabled:
            return None
        path = self._path(ticker)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if payload.get("format") != _CACHE_FORMAT or payload.get("params") != self.params:
            return None  # 파라미터가 바뀌면 캐시를 재사용하지 않는다
        return payload

    def write(self, ticker: str, payload: dict) -> None:
        if not self.enabled:
            return
        body = {"format": _CACHE_FORMAT, "params": self.params, **payload}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path(ticker).with_suffix(".json.tmp")
            tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path(ticker))
        except OSError:
            pass  # 캐시 실패는 수집 실패가 아니다


# ---------------------------------------------------------------------------
# 실패 사유 분류 (민감값을 남기지 않는 짧은 코드)
# ---------------------------------------------------------------------------
class _NoFilings(RuntimeError):
    pass


def _failure_reason(exc: BaseException) -> str:
    kind = getattr(exc, "kind", None)
    if isinstance(exc, _NoFilings):
        return "no_earnings_filings"
    if kind:
        return f"{type(exc).__name__}:{kind}"
    return type(exc).__name__


# ---------------------------------------------------------------------------
# 티커 1개 처리 (네트워크)
# ---------------------------------------------------------------------------
def _resolve_cik(ticker_client, ticker: str) -> str:
    return ticker_client.resolve_cik(ticker)


def _observations_for_ticker(
    ticker: str,
    *,
    sec_client: SecEdgarClient,
    ticker_client,
    as_of: date,
    window_days: int,
    history_days: int,
    max_filings: int,
) -> tuple[list, int]:
    """티커 1개의 GuidanceObservation 목록과 검사한 8-K 수. 실패는 예외로 올린다(호출부가 사유를 남긴다)."""
    cik = _resolve_cik(ticker_client, ticker)
    filings: Sequence[EarningsFiling] = list_earnings_filings(
        sec_client, cik, since=as_of - timedelta(days=history_days), until=as_of)
    if not filings:
        raise _NoFilings(f"no 8-K Item 2.02 in range for {ticker}")
    filings = list(filings)[-max_filings:]  # acceptance 오름차순 -> 최근 것만

    window_start = as_of - timedelta(days=window_days)
    per_filing: list[tuple[EarningsFiling, list, Optional[str]]] = []
    history: list[GuidanceItem] = []
    for filing in filings:
        release, extraction = extract_from_filing(sec_client, filing)
        items = [it for it in extraction.items if not it.problems]
        # 보도자료 원문 해시(core.info_dedup.content_hash 와 같은 sha256 규칙) — 같은 8-K 가 여러 후보·여러 날에
        # 중복 근거로 세어지지 않도록 CandidateRecord.info_hash 로 옮겨 담는 데 쓴다(RES-02).
        sha = getattr(release, "content_sha256", None) if release is not None else None
        per_filing.append((filing, items, sha))
        history.extend(items)

    observations: list[GuidanceObservation] = []
    for filing, items, sha in per_filing:
        if filing.acceptance_utc.date() < window_start:
            continue  # 창 밖 발표는 history(비교 대상)로만 쓴다
        for change in compute_guidance_changes(items, history):
            observations.append(GuidanceObservation(
                ticker=ticker, change=change, available_at=filing.acceptance_utc, approximate=True,
                content_sha256=sha))
    return observations, len(per_filing)


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def _check_rate_limit(client: Any) -> None:
    """(b) 주입된 클라이언트가 초당 5회 상한을 넘지 않는지 확인한다(확인만, 값을 바꾸지 않는다)."""
    limiter = getattr(client, "_limiter", None)
    interval = getattr(limiter, "_min_interval", None)
    if isinstance(interval, (int, float)) and interval < 1.0 / MAX_REQUESTS_PER_SECOND:
        raise ValueError(f"요청 간격이 초당 {MAX_REQUESTS_PER_SECOND}회 상한을 넘습니다(SEC 규칙 위반).")


def fetch_guidance_events(
    tickers: Sequence[str],
    *,
    as_of: Optional[date] = None,
    max_tickers: int = DEFAULT_MAX_TICKERS,
    window_days: int = DEFAULT_WINDOW_DAYS,
    history_days: int = DEFAULT_HISTORY_DAYS,
    max_filings_per_ticker: int = DEFAULT_MAX_FILINGS_PER_TICKER,
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
    sec_client: Optional[SecEdgarClient] = None,
    ticker_client=None,
    time_budget_seconds: Optional[float] = None,
    max_network_requests: Optional[int] = None,
    clock: Callable[[], float] = time.monotonic,
) -> GuidanceEventFetchResult:
    """티커 목록 -> {ticker: [GuidanceObservation, ...]}. 실패한 티커는 사유만 남기고 나머지는 계속 처리한다.

    time_budget_seconds / max_network_requests 는 (f) 소프트 상한이다(티커 사이에서만 검사, None 이면 무제한).

    네트워크 클라이언트는 캐시 미스가 처음 생길 때만 만든다 — 캐시가 전부 맞으면 HTTP 세션조차 열지 않는다.
    sec_client/ticker_client 를 주입하면 오프라인 테스트가 가능하다(실제 네트워크 호출 없음).
    """
    as_of_date = as_of or date.today()
    if max_tickers < 0:
        raise ValueError("max_tickers 는 0 이상이어야 합니다.")

    wanted: list[str] = []
    for t in tickers or ():
        tick = str(t).strip().upper()
        if tick and tick not in wanted:
            wanted.append(tick)
    selected, overflow = wanted[:max_tickers], wanted[max_tickers:]

    if sec_client is not None:
        _check_rate_limit(sec_client)  # 주입된 클라이언트는 티커 루프 전에 검사한다(실패 격리에 삼켜지지 않게)

    params = {"window_days": window_days, "history_days": history_days, "max_filings": max_filings_per_ticker,
              "comparison_policy": COMPARISON_POLICY}
    cache = _DayCache(cache_dir or DEFAULT_CACHE_DIR, as_of_date, params, enabled=use_cache)

    events: dict[str, list] = {}
    outcomes: list[TickerFetchOutcome] = []
    clients_created = False
    aborted = False
    budget_stop: Optional[str] = None
    n_cache_hits = 0
    started = clock()

    def _requests_so_far() -> int:
        return int(getattr(sec_client, "request_count", 0) or 0) if clients_created else 0

    def _clients():
        nonlocal sec_client, ticker_client, clients_created
        if sec_client is None:
            sec_client = SecEdgarClient()
        if ticker_client is None:
            from core.filing_changes import EdgarClient

            ticker_client = EdgarClient()
        if not clients_created:
            _check_rate_limit(sec_client)
            clients_created = True
        return sec_client, ticker_client

    for tick in selected:
        if aborted:
            outcomes.append(TickerFetchOutcome(tick, STATUS_ABORTED, reason="sec_access_blocked"))
            continue
        if budget_stop:
            outcomes.append(TickerFetchOutcome(tick, STATUS_SKIPPED_BUDGET, reason=budget_stop))
            continue
        cached = cache.read(tick)
        if cached is not None:
            if cached.get("status") == STATUS_OK:
                obs = [_observation_from_record(r) for r in cached.get("observations") or []]
                if obs:
                    events[tick] = obs
                outcomes.append(TickerFetchOutcome(tick, STATUS_CACHED, len(obs),
                                                   n_filings_examined=int(cached.get("n_filings_examined") or 0)))
            else:
                outcomes.append(TickerFetchOutcome(tick, STATUS_FAILED, reason=cached.get("reason") or "unknown"))
            n_cache_hits += 1
            continue
        # (f) 네트워크가 필요한 티커를 시작하기 직전에만 예산을 검사한다(캐시 적중은 예산을 쓰지 않는다).
        if time_budget_seconds is not None and clock() - started >= time_budget_seconds:
            budget_stop = "time_budget_exceeded"
        elif max_network_requests is not None and _requests_so_far() >= max_network_requests:
            budget_stop = "request_budget_exceeded"
        if budget_stop:
            outcomes.append(TickerFetchOutcome(tick, STATUS_SKIPPED_BUDGET, reason=budget_stop))
            continue
        try:
            sec, tk_client = _clients()
            obs, n_filings = _observations_for_ticker(
                tick, sec_client=sec, ticker_client=tk_client, as_of=as_of_date, window_days=window_days,
                history_days=history_days, max_filings=max_filings_per_ticker)
        except SecAccessError:
            aborted = True
            outcomes.append(TickerFetchOutcome(tick, STATUS_FAILED, reason="sec_access_blocked"))
            continue
        except Exception as exc:  # noqa: BLE001 - 한 티커 실패가 나머지를 막지 않는다
            reason = _failure_reason(exc)
            if getattr(exc, "kind", None) in ("blocked", "undeclared_user_agent"):
                aborted = True
                reason = "sec_access_blocked"
            outcomes.append(TickerFetchOutcome(tick, STATUS_FAILED, reason=reason))
            if reason in _CACHEABLE_FAIL_REASONS:
                cache.write(tick, {"ticker": tick, "status": STATUS_FAILED, "reason": reason})
            continue
        if obs:
            events[tick] = obs
        outcomes.append(TickerFetchOutcome(tick, STATUS_OK, len(obs), n_filings_examined=n_filings))
        cache.write(tick, {"ticker": tick, "status": STATUS_OK, "n_filings_examined": n_filings,
                           "observations": [_observation_to_record(o) for o in obs]})

    for tick in overflow:
        outcomes.append(TickerFetchOutcome(tick, STATUS_SKIPPED, reason="max_tickers_limit"))

    meta = {
        "as_of": as_of_date.isoformat(),
        "n_tickers_requested": len(wanted),
        "n_tickers_queried": len(selected),
        "n_tickers_skipped": len(overflow),
        "n_tickers_ok": sum(1 for o in outcomes if o.ok),
        "n_tickers_failed": sum(1 for o in outcomes if o.status in (STATUS_FAILED, STATUS_ABORTED)),
        "n_cache_hits": n_cache_hits,
        "n_tickers_skipped_budget": sum(1 for o in outcomes if o.status == STATUS_SKIPPED_BUDGET),
        "n_network_requests": _requests_so_far(),
        "max_tickers": max_tickers,
        "time_budget_seconds": time_budget_seconds,
        "max_network_requests": max_network_requests,
        "stopped_on_budget": budget_stop,
        "elapsed_seconds": round(max(0.0, clock() - started), 3),
        "params": dict(params),
        "aborted_on_access_block": aborted,
        "note": "관측 전용. 주문 경로·DB·스케줄러와 연결되지 않는다. User-Agent 값은 기록하지 않는다.",
    }
    return GuidanceEventFetchResult(events, tuple(outcomes), meta)


def build_events_by_ticker(tickers: Sequence[str], **kwargs) -> dict:
    """events_by_ticker 만 필요할 때 쓰는 얇은 래퍼(실패 사유는 버려지므로 진단이 필요하면
    fetch_guidance_events 를 직접 쓴다)."""
    return fetch_guidance_events(tickers, **kwargs).events_by_ticker


DEFAULT_EVENT_FETCHER: Callable[..., GuidanceEventFetchResult] = fetch_guidance_events
