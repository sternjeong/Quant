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


def test_refresh_stops_retrying_a_provider_after_request_error(monkeypatch, db_session):
    _patch_db(monkeypatch, db_session)
    calls = []

    def unavailable(ticker, since):
        calls.append(ticker)
        raise news_digest.requests.HTTPError("unauthorized")

    monkeypatch.setattr(news_digest, "_finnhub_articles", unavailable)
    monkeypatch.setattr(news_digest, "_fmp_articles", lambda ticker, since: [])

    result = news_digest.refresh_news(["XLK", "XLF"])

    assert calls == ["XLK"]
    assert result["errors"] == ["XLK Finnhub: HTTPError"]


def _add_xlk_article(db_session):
    db_session.add(NewsArticle(
        provider="finnhub", url="https://news.example/a", headline="XLK earnings beat", excerpt="Revenue rose.",
        source="Example", published_at=datetime.utcnow(), tickers=json.dumps(["XLK"]), event_type="earnings",
    ))
    db_session.commit()


def _fake_proc(returncode=0, stdout="", stderr=""):
    class _Proc:
        pass

    proc = _Proc()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_digest_uses_fallback_when_claude_cli_missing(monkeypatch, db_session):
    _patch_db(monkeypatch, db_session)
    _add_xlk_article(db_session)
    monkeypatch.setattr(news_digest, "_resolve_claude_cli_bin", lambda: (_ for _ in ()).throw(RuntimeError("no bin")))

    result = news_digest.generate_daily_digests(["XLK"], force=True)

    assert len(result["digests"]) == 1
    assert result["digests"][0]["summary_status"] == "fallback"
    assert result["digests"][0]["sentiment"] is None
    assert "[1]" in result["digests"][0]["summary"]
    assert result["used_ai_summary"] is False


def test_digest_uses_claude_cli_summary_and_sentiment(monkeypatch, db_session):
    _patch_db(monkeypatch, db_session)
    _add_xlk_article(db_session)
    monkeypatch.setattr(news_digest, "_resolve_claude_cli_bin", lambda: "/usr/local/bin/claude")
    envelope = {
        "is_error": False,
        "subtype": "success",
        "result": '설명\n```json\n{"items": [{"ticker": "XLK", "summary": "요약 [1]", '
                   '"sentiment": "bullish", "sentiment_score": 0.6}]}\n```',
    }

    def fake_run(cmd, input, text, capture_output, timeout):
        return _fake_proc(returncode=0, stdout=json.dumps(envelope))

    monkeypatch.setattr(news_digest.subprocess, "run", fake_run)

    result = news_digest.generate_daily_digests(["XLK"], force=True)

    assert result["used_ai_summary"] is True
    digest = result["digests"][0]
    assert digest["summary_status"] == "claude"
    assert digest["summary"] == "요약 [1]"
    assert digest["sentiment"] == "bullish"
    assert digest["sentiment_score"] == 0.6


def test_digest_falls_back_on_malformed_json_response(monkeypatch, db_session):
    _patch_db(monkeypatch, db_session)
    _add_xlk_article(db_session)
    monkeypatch.setattr(news_digest, "_resolve_claude_cli_bin", lambda: "/usr/local/bin/claude")
    envelope = {"is_error": False, "subtype": "success", "result": "not json at all"}

    def fake_run(cmd, input, text, capture_output, timeout):
        return _fake_proc(returncode=0, stdout=json.dumps(envelope))

    monkeypatch.setattr(news_digest.subprocess, "run", fake_run)

    result = news_digest.generate_daily_digests(["XLK"], force=True)

    assert result["used_ai_summary"] is False
    assert result["digests"][0]["summary_status"] == "fallback"


def test_digest_falls_back_on_cli_nonzero_exit(monkeypatch, db_session):
    _patch_db(monkeypatch, db_session)
    _add_xlk_article(db_session)
    monkeypatch.setattr(news_digest, "_resolve_claude_cli_bin", lambda: "/usr/local/bin/claude")

    def fake_run(cmd, input, text, capture_output, timeout):
        return _fake_proc(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(news_digest.subprocess, "run", fake_run)

    result = news_digest.generate_daily_digests(["XLK"], force=True)

    assert result["used_ai_summary"] is False
    assert result["digests"][0]["summary_status"] == "fallback"


def test_migration_adds_sentiment_columns(tmp_path, monkeypatch):
    """구버전 스키마(감성 컬럼 없음)에 _add_missing_columns가 두 컬럼을 채워 넣는지 확인한다."""
    from sqlalchemy import create_engine, inspect, text

    from core import db as db_module

    old_engine = create_engine(f"sqlite:///{tmp_path / 'migration_test.db'}", connect_args={"check_same_thread": False})
    with old_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE news_ticker_digests (id INTEGER PRIMARY KEY, ticker VARCHAR(20), "
            "period_start DATETIME, period_end DATETIME, article_count INTEGER, summary TEXT, "
            "source_links TEXT, summary_status VARCHAR(30), created_at DATETIME)"
        ))
    monkeypatch.setattr(db_module, "engine", old_engine)

    db_module._add_missing_columns()

    inspector = inspect(old_engine)
    columns = {c["name"] for c in inspector.get_columns("news_ticker_digests")}
    assert {"sentiment", "sentiment_score"}.issubset(columns)


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
