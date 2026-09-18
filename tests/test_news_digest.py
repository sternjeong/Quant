"""뉴스 리서치는 네트워크/API 키 없이 핵심 저장·대체 경로를 검증한다."""

from contextlib import contextmanager
from datetime import datetime, timedelta
import json

from core import news_digest
from core.models import NewsArticle


def _patch_db(monkeypatch, db_session):
    @contextmanager
    def session_context():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    monkeypatch.setattr(news_digest, "get_session", session_context)
    monkeypatch.setattr(news_digest, "init_db", lambda: None)


def test_normalise_url_and_event_classification():
    assert news_digest._normalise_url("https://Example.com/a/?utm_source=x#part") == "https://example.com/a"
    assert news_digest._normalise_url("javascript:alert(1)") == ""
    assert news_digest.classify_event("Company raises earnings guidance") == "earnings"
    assert news_digest.classify_event("Analyst upgrades the stock") == "analyst"


def test_refresh_deduplicates_url_and_merges_tickers(monkeypatch, db_session):
    _patch_db(monkeypatch, db_session)
    item = news_digest.ArticleInput(
        provider="finnhub", provider_id="1", url="https://news.example/a", headline="ETF earnings update",
        excerpt="short", source="Example", published_at=datetime.utcnow(),
    )
    monkeypatch.setattr(news_digest, "_finnhub_articles", lambda ticker, since: [item])
    monkeypatch.setattr(news_digest, "_fmp_articles", lambda ticker, since: [])

    result = news_digest.refresh_news(["XLK", "XLF"])

    assert result["added"] == 1
    article = db_session.query(NewsArticle).one()
    assert json.loads(article.tickers) == ["XLK", "XLF"]


def test_digest_uses_fallback_when_gemini_unavailable(monkeypatch, db_session):
    _patch_db(monkeypatch, db_session)
    db_session.add(NewsArticle(
        provider="finnhub", url="https://news.example/a", headline="XLK earnings beat", excerpt="Revenue rose.",
        source="Example", published_at=datetime.utcnow(), tickers=json.dumps(["XLK"]), event_type="earnings",
    ))
    db_session.commit()
    monkeypatch.setattr(news_digest.gemini_client, "has_api_key", lambda: False)

    result = news_digest.generate_daily_digests(["XLK"], force=True)

    assert len(result["digests"]) == 1
    assert result["digests"][0]["summary_status"] == "fallback"
    assert "[1]" in result["digests"][0]["summary"]


def test_html_report_escapes_summary_and_only_keeps_http_links(tmp_path, monkeypatch):
    monkeypatch.setattr(news_digest, "_REPORT_DIR", tmp_path)
    path = news_digest.write_daily_html_report([{
        "ticker": "XLK", "article_count": 1, "summary": "<script>bad</script>", "summary_status": "fallback",
        "source_links": [
            {"title": "safe", "url": "https://example.com/a", "source": "Example"},
            {"title": "bad", "url": "javascript:alert(1)", "source": "Bad"},
        ],
    }], now=datetime(2026, 1, 2, 3, 4, 5))
    content = path.read_text(encoding="utf-8")
    assert "&lt;script&gt;bad&lt;/script&gt;" in content
    assert "javascript:" not in content
    assert "https://example.com/a" in content
