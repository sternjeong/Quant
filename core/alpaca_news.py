"""core/alpaca_news.py — Alpaca Market Data 뉴스 API 를 point-in-time 기사 목록으로 정규화한다(읽기 전용).

배경: FMP/Finnhub 무료 티어는 뉴스·경제 캘린더가 유료이고 Alpha Vantage 뉴스는 하루 25콜이라 과거 뉴스 실험이
막혀 있었다. Alpaca 뉴스는 paper 키의 Market Data 로 과거 날짜 조회가 가능하다고 문서에 나와 있다(**미검증**).

PIT 원칙: 기사의 `created_at`(최초 게시 시각)만 '알 수 있었던 시각'으로 쓴다. `updated_at` 은 나중에 고쳐진 시각이라
과거 시점 백테스트에 쓰면 미래 정보가 섞이므로 별도 필드로만 보존한다. `as_of` 를 주면 그 시각 이후 게시분을 제거한다.
감성 점수는 만들지 않는다(이 모듈은 수집·정규화까지). 응답 파싱 지점은 `_normalize_article` 한 곳이다.
네트워크는 주입 가능한 `get_json` 으로만 일어난다.
"""

from __future__ import annotations

from typing import Any, Callable, Optional
from urllib.parse import urlencode

import requests

from core import account_sync

DATA_BASE_URL = "https://data.alpaca.markets"
MAX_PAGES = 20  # 무한 페이지네이션 방지
PAGE_LIMIT = 50


def _data_get_json(path: str) -> Any:
    headers = account_sync._auth_headers()
    account_sync._throttle()
    r = requests.get(DATA_BASE_URL + path, headers=headers, timeout=account_sync.REQUEST_TIMEOUT_SEC)
    r.raise_for_status()
    return r.json()


def _normalize_article(raw: dict) -> Optional[dict[str, Any]]:
    created = raw.get("created_at")
    if not created or not raw.get("headline"):
        return None  # 게시 시각이 없으면 PIT 를 보장할 수 없어 버린다
    return {
        "id": raw.get("id"), "published_at": created, "updated_at": raw.get("updated_at"),
        "headline": raw["headline"], "summary": raw.get("summary") or "", "source": raw.get("source"),
        "url": raw.get("url"), "symbols": [s.upper() for s in (raw.get("symbols") or [])],
    }


def fetch_news(
    symbols: list[str], start: str, end: str, *, as_of: Optional[str] = None,
    get_json: Optional[Callable[[str], Any]] = None,
) -> list[dict[str, Any]]:
    """[start, end] 기사를 published_at 오름차순·id 중복 제거로 반환. as_of(ISO, UTC 문자열 비교) 이후 게시분은 제외."""
    get = get_json or _data_get_json
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    token: Optional[str] = None
    for _ in range(MAX_PAGES):
        params = {"symbols": ",".join(s.upper() for s in symbols), "start": start, "end": end,
                  "limit": PAGE_LIMIT, "sort": "asc"}
        if token:
            params["page_token"] = token
        payload = get("/v1beta1/news?" + urlencode(params))
        for raw in payload.get("news") or []:
            art = _normalize_article(raw)
            if art is None or art["id"] in seen:
                continue
            if as_of and art["published_at"] > as_of:
                continue
            seen.add(art["id"])
            out.append(art)
        token = payload.get("next_page_token")
        if not token:
            break
    out.sort(key=lambda a: a["published_at"])
    return out
