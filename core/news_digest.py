"""티커별 뉴스 수집·요약 공용 로직.

V1은 이미 설정된 Finnhub/FMP 뉴스 API의 제목, 짧은 설명, 원문 링크만 이용한다. 기사 전문을
스크래핑하거나 유료 매체의 접근 제한을 우회하지 않는다. 이 모듈은 Streamlit 화면과 scheduler,
Telegram 명령이 하나의 SQLite 이력을 보게 하는 유일한 뉴스 데이터 경로다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import html
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

import requests

from core import gemini_client
from core.champion_strategy import CORE_UNIVERSE
from core.db import get_session, init_db
from core.models import NewsArticle, NewsTickerDigest, NewsTickerSubscription


_REQUEST_TIMEOUT_SECONDS = 20
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_WHITESPACE_RE = re.compile(r"\s+")
_REPORT_DIR = Path(__file__).resolve().parent.parent / ".news-digest" / "reports"


@dataclass(frozen=True)
class ArticleInput:
    provider: str
    provider_id: str | None
    url: str
    headline: str
    excerpt: str
    source: str
    published_at: datetime | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean_text(value: Any, limit: int) -> str:
    value = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    return value[:limit]


def _normalise_url(url: str) -> str:
    """추적 파라미터를 제거한 URL로 공급자 간 중복을 낮춘다."""
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", ""))
    except ValueError:
        return ""


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError, OSError):
        return None


def classify_event(headline: str) -> str:
    """요약 화면에서 훑기 위한 보수적 키워드 분류이며 매매 신호가 아니다."""
    text = headline.lower()
    rules = (
        ("earnings", ("earnings", "quarterly result", "revenue", "eps", "실적")),
        ("guidance", ("guidance", "forecast", "outlook", "전망")),
        ("m&a", ("acquire", "acquisition", "merger", "takeover", "deal")),
        ("regulation", ("sec", "fed", "regulator", "tariff", "sanction", "antitrust", "규제")),
        ("legal", ("lawsuit", "settlement", "court", "sue", "litigation")),
        ("analyst", ("upgrade", "downgrade", "price target", "analyst")),
        ("macro", ("inflation", "jobs report", "gdp", "interest rate", "oil price", "cpi")),
    )
    return next((kind for kind, words in rules if any(word in text for word in words)), "other")


def normalise_tickers(tickers: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in tickers:
        ticker = str(value).strip().upper()
        if _TICKER_RE.fullmatch(ticker) and ticker not in result:
            result.append(ticker)
    return result


def ensure_default_subscriptions() -> list[str]:
    """첫 실행일 때만 챔피언 전략의 코어 ETF를 뉴스 대상에 넣는다."""
    init_db()
    with get_session() as session:
        existing = session.query(NewsTickerSubscription).count()
        if not existing:
            session.add_all(NewsTickerSubscription(ticker=ticker) for ticker in CORE_UNIVERSE)
        rows = (
            session.query(NewsTickerSubscription)
            .filter(NewsTickerSubscription.enabled.is_(True))
            .order_by(NewsTickerSubscription.ticker)
            .all()
        )
        return [row.ticker for row in rows]


def list_subscriptions(include_disabled: bool = False) -> list[dict[str, Any]]:
    init_db()
    with get_session() as session:
        query = session.query(NewsTickerSubscription)
        if not include_disabled:
            query = query.filter(NewsTickerSubscription.enabled.is_(True))
        rows = query.order_by(NewsTickerSubscription.ticker).all()
        return [{"ticker": row.ticker, "enabled": row.enabled, "created_at": row.created_at} for row in rows]


def replace_subscriptions(tickers: Iterable[str]) -> list[str]:
    """UI에서 확정한 전체 구독 목록을 원자적으로 반영한다."""
    cleaned = normalise_tickers(tickers)
    if not cleaned:
        raise ValueError("뉴스 구독 티커를 하나 이상 입력하세요.")
    init_db()
    with get_session() as session:
        session.query(NewsTickerSubscription).delete()
        session.add_all(NewsTickerSubscription(ticker=ticker, enabled=True) for ticker in cleaned)
    return cleaned


def _finnhub_articles(ticker: str, since: datetime) -> list[ArticleInput]:
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        return []
    payload = requests.get(
        "https://finnhub.io/api/v1/company-news",
        params={"symbol": ticker, "from": since.date().isoformat(), "to": _utcnow().date().isoformat(), "token": key},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ).json()
    if not isinstance(payload, list):
        return []
    results: list[ArticleInput] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = _normalise_url(item.get("url", ""))
        headline = _clean_text(item.get("headline"), 500)
        if url and headline:
            results.append(ArticleInput(
                provider="finnhub", provider_id=str(item.get("id") or "") or None, url=url,
                headline=headline, excerpt=_clean_text(item.get("summary"), 1500),
                source=_clean_text(item.get("source"), 180), published_at=_parse_datetime(item.get("datetime")),
            ))
    return results


def _fmp_articles(ticker: str, since: datetime) -> list[ArticleInput]:
    """FMP stable endpoint. 응답 형식이 변하면 해당 공급자만 빈 결과로 처리한다."""
    key = os.getenv("FMP_API_KEY")
    if not key:
        return []
    payload = requests.get(
        "https://financialmodelingprep.com/stable/news/stock",
        params={"symbols": ticker, "limit": 20, "apikey": key},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ).json()
    if not isinstance(payload, list):
        return []
    results: list[ArticleInput] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        published_at = _parse_datetime(item.get("publishedDate") or item.get("published_at"))
        if published_at and published_at < since:
            continue
        url = _normalise_url(item.get("url") or item.get("link") or "")
        headline = _clean_text(item.get("title") or item.get("headline"), 500)
        if url and headline:
            results.append(ArticleInput(
                provider="fmp", provider_id=str(item.get("id") or item.get("newsId") or "") or None, url=url,
                headline=headline, excerpt=_clean_text(item.get("text") or item.get("summary"), 1500),
                source=_clean_text(item.get("site") or item.get("publisher") or "FMP", 180),
                published_at=published_at,
            ))
    return results


def _save_article(session: Any, item: ArticleInput, ticker: str) -> bool:
    existing = session.query(NewsArticle).filter(NewsArticle.url == item.url).first()
    if existing is None and item.provider_id:
        existing = (
            session.query(NewsArticle)
            .filter(NewsArticle.provider == item.provider, NewsArticle.provider_id == item.provider_id)
            .first()
        )
    if existing:
        tickers = normalise_tickers(json.loads(existing.tickers or "[]") + [ticker])
        existing.tickers = json.dumps(tickers)
        return False
    session.add(NewsArticle(
        provider=item.provider, provider_id=item.provider_id, url=item.url, headline=item.headline,
        excerpt=item.excerpt, source=item.source, published_at=item.published_at, tickers=json.dumps([ticker]),
        event_type=classify_event(item.headline),
    ))
    return True


def refresh_news(tickers: Iterable[str] | None = None, since_hours: int = 30) -> dict[str, Any]:
    """두 공급자에서 최근 기사 메타데이터를 수집한다. 한 공급자의 실패는 다른 수집을 막지 않는다."""
    selected = normalise_tickers(tickers or ensure_default_subscriptions())
    since = _utcnow() - timedelta(hours=max(1, since_hours))
    errors: list[str] = []
    added = 0
    attempted = 0
    init_db()
    with get_session() as session:
        for ticker in selected:
            for provider, fetcher in (("Finnhub", _finnhub_articles), ("FMP", _fmp_articles)):
                try:
                    articles = fetcher(ticker, since)
                    attempted += len(articles)
                    for article in articles:
                        added += int(_save_article(session, article, ticker))
                except (requests.RequestException, ValueError, TypeError) as exc:
                    # API key 및 응답 내용은 로그/화면에 노출하지 않는다.
                    errors.append(f"{ticker} {provider}: {type(exc).__name__}")
    return {"tickers": selected, "added": added, "attempted": attempted, "errors": errors, "since": since}


def _articles_for_ticker(session: Any, ticker: str, since: datetime, limit: int = 8) -> list[NewsArticle]:
    rows = (
        session.query(NewsArticle)
        .filter((NewsArticle.published_at.is_(None)) | (NewsArticle.published_at >= since))
        .order_by(NewsArticle.published_at.desc(), NewsArticle.id.desc())
        .limit(500)
        .all()
    )
    return [row for row in rows if ticker in normalise_tickers(json.loads(row.tickers or "[]"))][:limit]


def _article_link(row: NewsArticle) -> dict[str, str]:
    return {"id": str(row.id), "title": row.headline, "url": row.url, "source": row.source or row.provider}


def _fallback_summary(ticker: str, articles: list[NewsArticle]) -> str:
    labels = ", ".join(sorted({article.event_type for article in articles if article.event_type != "other"}))
    headline_lines = "\n".join(f"• {article.headline} [{article.id}]" for article in articles[:3])
    prefix = f"최근 {len(articles)}건의 기사" + (f" ({labels})" if labels else "")
    return f"{prefix}가 수집되었습니다. 원문 링크를 열어 사실관계를 확인하세요.\n{headline_lines}"


_DIGEST_SYSTEM_PROMPT = """당신은 투자 리서치 보조자입니다. 제공된 기사 제목·짧은 설명만 사용해 한국어로 요약하세요.
각 티커마다 2~4개의 짧은 불릿을 작성하고, 각 사실 문장 끝에 반드시 제공된 [기사ID]를 붙이세요.
기사에 없는 사실, 가격 전망, 매수·매도 권고를 만들지 마세요. 상충하는 보도가 있으면 상충한다고 적으세요."""


def _gemini_summaries(article_map: dict[str, list[NewsArticle]]) -> dict[str, str]:
    payload = {
        "tickers": [
            {"ticker": ticker, "articles": [
                {"id": row.id, "source": row.source or row.provider, "headline": row.headline, "excerpt": row.excerpt}
                for row in articles[:5]
            ]}
            for ticker, articles in article_map.items()
        ]
    }
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
            "ticker": {"type": "string"}, "summary": {"type": "string"},
        }, "required": ["ticker", "summary"], "additionalProperties": False}}},
        "required": ["items"], "additionalProperties": False,
    }
    response = gemini_client.generate_content(
        models=gemini_client.LIGHT_TASK_MODELS, contents=json.dumps(payload, ensure_ascii=False),
        system_instruction=_DIGEST_SYSTEM_PROMPT, response_mime_type="application/json", response_json_schema=schema,
    )
    decoded = json.loads(response.text)
    summaries = {
        str(item.get("ticker", "")).upper(): _clean_text(item.get("summary"), 2400)
        for item in decoded.get("items", []) if isinstance(item, dict)
    }
    return {ticker: summaries[ticker] for ticker in article_map if summaries.get(ticker)}


def generate_daily_digests(
    tickers: Iterable[str] | None = None, days: int = 1, force: bool = False,
) -> dict[str, Any]:
    """최근 뉴스로 티커별 요약을 만들고 저장한다. Gemini 실패 시 항상 제목 기반 폴백을 남긴다."""
    selected = normalise_tickers(tickers or ensure_default_subscriptions())
    period_end = _utcnow()
    period_start = period_end - timedelta(days=max(1, days))
    recent_cutoff = period_end - timedelta(hours=20)
    init_db()
    with get_session() as session:
        article_map = {ticker: _articles_for_ticker(session, ticker, period_start) for ticker in selected}
        article_map = {ticker: articles for ticker, articles in article_map.items() if articles}
        if not force:
            existing_tickers = {
                row.ticker for row in session.query(NewsTickerDigest.ticker)
                .filter(NewsTickerDigest.created_at >= recent_cutoff).all()
            }
            article_map = {ticker: articles for ticker, articles in article_map.items() if ticker not in existing_tickers}
        if not article_map:
            return {"digests": [], "used_gemini": False, "reason": "새 기사 또는 새 요약 대상이 없습니다."}
        summaries: dict[str, str] = {}
        used_gemini = False
        if gemini_client.has_api_key():
            try:
                summaries = _gemini_summaries(article_map)
                used_gemini = bool(summaries)
            except Exception:  # Gemini API 장애/쿼터는 제목 기반 요약으로 안전하게 대체한다.
                summaries = {}
        created: list[dict[str, Any]] = []
        for ticker, articles in article_map.items():
            summary = summaries.get(ticker) or _fallback_summary(ticker, articles)
            status = "gemini" if ticker in summaries else "fallback"
            digest = NewsTickerDigest(
                ticker=ticker, period_start=period_start, period_end=period_end, article_count=len(articles),
                summary=summary, source_links=json.dumps([_article_link(row) for row in articles], ensure_ascii=False),
                summary_status=status,
            )
            session.add(digest)
            session.flush()
            created.append(_digest_dict(digest))
        return {"digests": created, "used_gemini": used_gemini, "reason": ""}


def run_news_pipeline(tickers: Iterable[str] | None = None, force: bool = False) -> dict[str, Any]:
    """수집과 종합 요약을 한 작업으로 묶어 UI와 스케줄러가 같은 절차를 사용하게 한다."""
    refresh = refresh_news(tickers=tickers)
    digest = generate_daily_digests(tickers=refresh["tickers"], force=force)
    return {"refresh": refresh, **digest}


def _digest_dict(row: NewsTickerDigest) -> dict[str, Any]:
    try:
        links = json.loads(row.source_links or "[]")
    except ValueError:
        links = []
    return {
        "id": row.id, "ticker": row.ticker, "period_start": row.period_start, "period_end": row.period_end,
        "article_count": row.article_count, "summary": row.summary, "source_links": links,
        "summary_status": row.summary_status, "created_at": row.created_at,
    }


def list_latest_digests(ticker: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    init_db()
    with get_session() as session:
        query = session.query(NewsTickerDigest)
        if ticker:
            query = query.filter(NewsTickerDigest.ticker == ticker.upper())
        rows = query.order_by(NewsTickerDigest.created_at.desc()).limit(limit).all()
        return [_digest_dict(row) for row in rows]


def list_news_articles(ticker: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with get_session() as session:
        rows = session.query(NewsArticle).order_by(NewsArticle.published_at.desc(), NewsArticle.id.desc()).limit(max(limit * 5, 100)).all()
        if ticker:
            rows = [row for row in rows if ticker.upper() in normalise_tickers(json.loads(row.tickers or "[]"))]
        return [{
            "id": row.id, "headline": row.headline, "excerpt": row.excerpt, "source": row.source or row.provider,
            "url": row.url, "published_at": row.published_at, "event_type": row.event_type,
            "tickers": normalise_tickers(json.loads(row.tickers or "[]")),
        } for row in rows[:limit]]


def render_daily_telegram_summary(digests: Iterable[dict[str, Any]]) -> str:
    rows = list(digests)
    if not rows:
        return "📰 뉴스 리서치: 최근 24시간에 새로 요약할 기사가 없습니다."
    lines = ["📰 일일 티커 뉴스 리서치"]
    for row in rows:
        text = _WHITESPACE_RE.sub(" ", row["summary"]).replace("•", "")[:175]
        lines.append(f"• {row['ticker']} ({row['article_count']}건): {text}")
    lines.append("원문 링크와 전체 요약은 첨부 HTML에서 확인하세요. 연구용 정보이며 매매 권고가 아닙니다.")
    return "\n".join(lines)[:3800]


def write_daily_html_report(digests: Iterable[dict[str, Any]], now: datetime | None = None) -> Path:
    """텔레그램 첨부용 독립 HTML을 만든다. 보고서는 git 추적 대상 밖에 둔다."""
    rows = list(digests)
    now = now or _utcnow()
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORT_DIR / f"news_{now.strftime('%Y%m%d_%H%M%S')}.html"
    sections: list[str] = []
    for row in rows:
        links = "".join(
            f'<li><a href="{html.escape(link.get("url", ""), quote=True)}">{html.escape(link.get("title", ""))}</a> '
            f'— {html.escape(link.get("source", ""))}</li>'
            for link in row.get("source_links", []) if _normalise_url(str(link.get("url", "")))
        ) or "<li>출처 링크가 제공되지 않았습니다.</li>"
        summary = html.escape(row["summary"]).replace("\n", "<br>")
        sections.append(
            f"<section><h2>{html.escape(row['ticker'])} <small>{row['article_count']}건 · {html.escape(row['summary_status'])}</small></h2>"
            f"<p>{summary}</p><h3>원문 출처</h3><ul>{links}</ul></section>"
        )
    body = "".join(sections) or "<p>새로 요약한 기사가 없습니다.</p>"
    path.write_text(
        "<!doctype html><html lang='ko'><meta charset='utf-8'><title>일일 티커 뉴스 리서치</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:32px auto;line-height:1.6;color:#202124}"
        "section{border-top:1px solid #ddd;padding:16px 0}small{color:#666;font-weight:normal}a{color:#175bc4}</style>"
        f"<body><h1>일일 티커 뉴스 리서치</h1><p>{now.strftime('%Y-%m-%d %H:%M UTC')} 생성 · "
        "기사 전문을 저장하지 않은 제목·짧은 설명 기반 요약입니다. 매매 권고가 아닙니다.</p>" + body + "</body></html>",
        encoding="utf-8",
    )
    return path
