"""Alpaca Corporate Actions API 클라이언트 (ENG-01 배당·분할 데이터 소스).

목적: `core.trade_ledger` 의 원장 백테스트에 배당 현금 유입과 분할 조정을 넣기 위한 기업행동
데이터를 받아온다. 이 모듈은 데이터 수집만 담당하며, 호출하지 않으면 기존 동작에 아무 영향이 없다.

엔드포인트: GET https://data.alpaca.markets/v1/corporate-actions
  파라미터: symbols(쉼표 구분), types(쉼표 구분, 생략 가능), start, end(YYYY-MM-DD),
            limit, page_token, sort
  응답(관측된 문서 기준): {"corporate_actions": {"cash_dividends": [...], "forward_splits": [...],
            "reverse_splits": [...], "stock_dividends": [...], "cash_mergers": [...], ...},
            "next_page_token": str|None}

**실제 응답 스키마는 이 환경에서 검증하지 못했다**(키가 없어 401 만 확인). 그래서 파싱은 전부
방어적이다: 필드가 없으면 추측하지 않고 None/"unknown" 으로 두고, 모르는 행 종류는
type="unknown" 으로 원본 payload 와 함께 보존한다. 사람이 VM 에서
`scripts/verify_alpaca_corporate_actions.py` 를 돌려 실제 스키마와 대조해야 한다.

자격증명: 환경변수 ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET 에서만 읽는다
(core.paper_execution.AlpacaPaperBroker 와 같은 방식). 키/시크릿 값은 절대 로그·캐시·예외
메시지·stdout 에 남기지 않는다.

캐시: core.earnings_events.SecEdgarClient 의 관례를 따라 data/cache/alpaca_corporate_actions/
아래에 요청별 JSON 파일 하나 + fetched_at 메타를 둔다. 기본 TTL 은 1일이며, 과거 구간 조회는
호출자가 ttl_seconds=None 으로 영구 캐시 취급할 수 있다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "alpaca_corporate_actions"
BASE_URL = "https://data.alpaca.markets/v1/corporate-actions"
DEFAULT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_MIN_INTERVAL_SECONDS = 0.35  # 무료 플랜 200 req/min 여유 있게
DEFAULT_PAGE_LIMIT = 1000
MAX_PAGES = 50  # 페이지네이션 무한루프 방지
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 응답의 그룹 키 -> 정규화 type
TYPE_CASH_DIVIDEND = "cash_dividend"
TYPE_SPECIAL_DIVIDEND = "special_cash_dividend"
TYPE_FORWARD_SPLIT = "forward_split"
TYPE_REVERSE_SPLIT = "reverse_split"
TYPE_STOCK_DIVIDEND = "stock_dividend"
TYPE_CASH_MERGER = "cash_merger"
TYPE_UNKNOWN = "unknown"

GROUP_TO_TYPE = {
    "cash_dividends": TYPE_CASH_DIVIDEND,
    "special_cash_dividends": TYPE_SPECIAL_DIVIDEND,
    "forward_splits": TYPE_FORWARD_SPLIT,
    "reverse_splits": TYPE_REVERSE_SPLIT,
    "unit_splits": TYPE_UNKNOWN,
    "stock_dividends": TYPE_STOCK_DIVIDEND,
    "cash_mergers": TYPE_CASH_MERGER,
    "stock_mergers": TYPE_UNKNOWN,
    "stock_and_cash_mergers": TYPE_UNKNOWN,
}

# API 의 types 파라미터 값(그룹 키와 단수/복수가 다를 수 있어 별도 매핑)
DIVIDEND_AND_SPLIT_TYPES = ("cash_dividend", "forward_split", "reverse_split")

_AMOUNT_FIELDS = ("rate", "cash_rate", "amount", "payment", "dividend_rate")
_EX_DATE_FIELDS = ("ex_date", "ex_dividend_date", "effective_date", "process_date")
_RECORD_DATE_FIELDS = ("record_date",)
_PAYABLE_DATE_FIELDS = ("payable_date", "payment_date")


class CorporateActionsError(RuntimeError):
    """기업행동 조회 실패(자격증명 누락·HTTP 오류 등). 메시지에 자격증명 값을 담지 않는다."""


@dataclass
class CorporateAction:
    """정규화된 기업행동 1건. 모르는 값은 None 이며 추측하지 않는다."""

    symbol: str
    type: str = TYPE_UNKNOWN
    ex_date: Optional[str] = None       # ISO YYYY-MM-DD
    record_date: Optional[str] = None
    payable_date: Optional[str] = None
    amount: Optional[float] = None      # 주당 현금배당액
    split_ratio: Optional[float] = None  # 신주/구주 (2:1 분할 = 2.0, 1:10 병합 = 0.1)
    source: str = "alpaca"
    fetched_at: Optional[str] = None    # ISO UTC
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CorporateAction":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @property
    def is_dividend(self) -> bool:
        return self.type in (TYPE_CASH_DIVIDEND, TYPE_SPECIAL_DIVIDEND)

    @property
    def is_split(self) -> bool:
        return self.type in (TYPE_FORWARD_SPLIT, TYPE_REVERSE_SPLIT)


@dataclass
class CorporateActionsResult:
    """심볼별 기업행동 + 실패한 심볼. 실패 심볼은 결측으로 두고 나머지는 계속 진행한다."""

    actions: dict[str, list[CorporateAction]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)   # symbol -> 실패 사유(자격증명 값 없음)
    from_cache: dict[str, bool] = field(default_factory=dict)

    def all_actions(self) -> list[CorporateAction]:
        return [a for rows in self.actions.values() for a in rows]

    def to_dict(self) -> dict:
        return {
            "actions": {s: [a.to_dict() for a in rows] for s, rows in self.actions.items()},
            "errors": dict(self.errors),
            "from_cache": dict(self.from_cache),
        }


# -- 파싱 ---------------------------------------------------------------
def _as_iso_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _first(row: dict, fields: Iterable[str], caster) -> Optional[Any]:
    for f in fields:
        if f in row:
            got = caster(row[f])
            if got is not None:
                return got
    return None


def _split_ratio(row: dict) -> Optional[float]:
    """new_rate/old_rate. 둘 중 하나라도 없거나 0 이면 추측하지 않고 None."""
    new = _as_float(row.get("new_rate"))
    old = _as_float(row.get("old_rate"))
    if new is None or old is None or old == 0:
        ratio = _as_float(row.get("ratio"))
        return ratio if ratio and ratio > 0 else None
    ratio = new / old
    return ratio if ratio > 0 else None


def parse_action(group: str, row: dict, fetched_at: str, requested_symbol: Optional[str] = None) -> CorporateAction:
    """응답 1행을 정규화한다. 알 수 없는 그룹/필드는 unknown/None 으로 두고 raw 를 보존한다."""
    kind = GROUP_TO_TYPE.get(group, TYPE_UNKNOWN)
    symbol = str(row.get("symbol") or row.get("target_symbol") or requested_symbol or "").upper()
    action = CorporateAction(
        symbol=symbol,
        type=kind,
        ex_date=_first(row, _EX_DATE_FIELDS, _as_iso_date),
        record_date=_first(row, _RECORD_DATE_FIELDS, _as_iso_date),
        payable_date=_first(row, _PAYABLE_DATE_FIELDS, _as_iso_date),
        fetched_at=fetched_at,
        raw=dict(row),
    )
    if kind in (TYPE_CASH_DIVIDEND, TYPE_SPECIAL_DIVIDEND, TYPE_CASH_MERGER):
        action.amount = _first(row, _AMOUNT_FIELDS, _as_float)
        if kind == TYPE_CASH_DIVIDEND and row.get("special") is True:
            action.type = TYPE_SPECIAL_DIVIDEND
    if kind in (TYPE_FORWARD_SPLIT, TYPE_REVERSE_SPLIT, TYPE_UNKNOWN):
        action.split_ratio = _split_ratio(row)
    return action


def parse_payload(payload: dict, fetched_at: str, requested_symbol: Optional[str] = None) -> list[CorporateAction]:
    """한 페이지 응답 전체를 정규화한다. corporate_actions 가 없으면 빈 리스트."""
    groups = payload.get("corporate_actions")
    if not isinstance(groups, dict):
        return []
    out: list[CorporateAction] = []
    for group, rows in groups.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                out.append(parse_action(group, row, fetched_at, requested_symbol))
    return out


# -- 클라이언트 ---------------------------------------------------------
class AlpacaCorporateActionsClient:
    """읽기 전용 기업행동 클라이언트(캐시·요청간격·페이지네이션·심볼 단위 실패 격리)."""

    def __init__(
        self,
        key: str,
        secret: str,
        *,
        cache_dir: Optional[Path] = None,
        base_url: str = BASE_URL,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        max_attempts: int = 3,
        base_delay_seconds: float = 1.0,
        timeout_seconds: float = 20.0,
        session=None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if not key or not secret:
            raise CorporateActionsError(
                "ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET are required")
        # 헤더는 인스턴스 밖으로 노출하지 않는다(로그·직렬화 금지).
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                         "accept": "application/json"}
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.base_url = base_url
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay_seconds = base_delay_seconds
        self.timeout_seconds = timeout_seconds
        self._session = session
        self._sleep = sleep
        self._clock = clock
        self._now = now
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._last_request_at: Optional[float] = None
        self.request_count = 0  # 실제 네트워크 요청 수(캐시 적중 제외)

    @classmethod
    def from_env(cls, **kwargs) -> "AlpacaCorporateActionsClient":
        return cls(os.getenv("ALPACA_PAPER_API_KEY", ""), os.getenv("ALPACA_PAPER_API_SECRET", ""), **kwargs)

    def __repr__(self) -> str:  # 자격증명 유출 방지
        return f"<AlpacaCorporateActionsClient cache_dir={self.cache_dir}>"

    # -- rate limit / http ---------------------------------------------
    def _wait(self) -> None:
        if self._min_interval <= 0:
            return
        if self._last_request_at is not None:
            remaining = self._min_interval - (self._clock() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = self._clock()

    def _get_session(self):
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _get(self, params: dict) -> dict:
        last_error = "unknown error"
        for attempt in range(1, self.max_attempts + 1):
            self._wait()
            self.request_count += 1
            try:
                resp = self._get_session().get(self.base_url, headers=self._headers,
                                               params=params, timeout=self.timeout_seconds)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt == self.max_attempts:
                    break
                self._sleep(self.base_delay_seconds * (2 ** (attempt - 1)))
                continue
            status = getattr(resp, "status_code", 0)
            if status == 200:
                try:
                    return resp.json() or {}
                except ValueError as exc:
                    raise CorporateActionsError(f"JSON 파싱 실패: {type(exc).__name__}") from None
            if status in (401, 403):
                raise CorporateActionsError(
                    f"HTTP {status}: Alpaca 자격증명이 없거나 권한이 없다. 실행 환경에 "
                    "ALPACA_PAPER_API_KEY/ALPACA_PAPER_API_SECRET 를 설정하라(값은 기록하지 않는다).")
            if status in _RETRYABLE_STATUS:
                last_error = f"HTTP {status}"
                if attempt == self.max_attempts:
                    break
                self._sleep(self.base_delay_seconds * (2 ** (attempt - 1)))
                continue
            raise CorporateActionsError(f"HTTP {status}")
        raise CorporateActionsError(f"요청 실패: {last_error}")

    # -- cache ----------------------------------------------------------
    def _cache_path(self, symbol: str, start: str, end: str, types: tuple[str, ...]) -> Path:
        key = f"{symbol}|{start}|{end}|{','.join(types)}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", symbol)[:20] or "sym"
        return self.cache_dir / f"{safe}_{digest}.json"

    def _read_cache(self, path: Path, ttl_seconds: Optional[float]) -> Optional[list[CorporateAction]]:
        if not path.exists():
            return None
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(blob["fetched_at"])
            rows = blob["actions"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if ttl_seconds is not None and (self._now() - fetched_at).total_seconds() > ttl_seconds:
            return None
        try:
            return [CorporateAction.from_dict(r) for r in rows]
        except TypeError:
            return None

    def _write_cache(self, path: Path, actions: list[CorporateAction], fetched_at: str) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"fetched_at": fetched_at,
                                        "actions": [a.to_dict() for a in actions]},
                                       ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # 캐시 실패는 수집 실패가 아니다

    # -- 조회 ------------------------------------------------------------
    def fetch_symbol(
        self,
        symbol: str,
        start: str | date,
        end: str | date,
        *,
        types: Iterable[str] = DIVIDEND_AND_SPLIT_TYPES,
        ttl_seconds: Optional[float] = DEFAULT_TTL_SECONDS,
        use_cache: bool = True,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[CorporateAction], bool]:
        """한 심볼의 기업행동 전체(페이지네이션 포함)를 받는다. (actions, from_cache) 반환."""
        sym = str(symbol).upper().strip()
        s, e = _as_iso_date(start), _as_iso_date(end)
        if not sym or not s or not e:
            raise ValueError("symbol, start, end(YYYY-MM-DD) 가 필요합니다")
        tps = tuple(sorted(set(types or ())))
        path = self._cache_path(sym, s, e, tps)
        if use_cache:
            cached = self._read_cache(path, ttl_seconds)
            if cached is not None:
                return cached, True

        fetched_at = self._now().isoformat()
        params: dict[str, Any] = {"symbols": sym, "start": s, "end": e, "limit": int(limit)}
        if tps:
            params["types"] = ",".join(tps)
        out: list[CorporateAction] = []
        token: Optional[str] = None
        for _ in range(MAX_PAGES):
            page_params = dict(params)
            if token:
                page_params["page_token"] = token
            payload = self._get(page_params)
            out.extend(parse_payload(payload, fetched_at, requested_symbol=sym))
            token = payload.get("next_page_token") or None
            if not token:
                break
        out.sort(key=lambda a: (a.ex_date or "", a.type))
        if use_cache:
            self._write_cache(path, out, fetched_at)
        return out, False

    def fetch(
        self,
        symbols: Iterable[str],
        start: str | date,
        end: str | date,
        *,
        types: Iterable[str] = DIVIDEND_AND_SPLIT_TYPES,
        ttl_seconds: Optional[float] = DEFAULT_TTL_SECONDS,
        use_cache: bool = True,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> CorporateActionsResult:
        """여러 심볼을 순차 조회한다. 한 심볼이 실패해도 결측으로 두고 나머지는 계속한다."""
        result = CorporateActionsResult()
        seen: set[str] = set()
        for raw_symbol in symbols:
            sym = str(raw_symbol).upper().strip()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            try:
                actions, cached = self.fetch_symbol(sym, start, end, types=types,
                                                    ttl_seconds=ttl_seconds,
                                                    use_cache=use_cache, limit=limit)
            except (CorporateActionsError, requests.RequestException, ValueError) as exc:
                result.errors[sym] = f"{type(exc).__name__}: {exc}"
                continue
            result.actions[sym] = actions
            result.from_cache[sym] = cached
        return result


def actions_to_json(actions: Iterable[CorporateAction]) -> str:
    return json.dumps([a.to_dict() for a in actions], ensure_ascii=False, sort_keys=True)


def actions_from_json(text: str) -> list[CorporateAction]:
    return [CorporateAction.from_dict(d) for d in json.loads(text)]
