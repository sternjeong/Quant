"""core/threads_summary.py 단위 테스트 (모듈 B: Threads 글 -> 티커별 요약)."""

import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

import core.threads_summary as threads_summary
from core.models import ThreadsSummary, ThreadsWeeklyReport


@pytest.fixture()
def patched_session(db_session, monkeypatch):
    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(threads_summary, "get_session", _fake_get_session)
    return db_session


@pytest.fixture(autouse=True)
def _mock_latest_price(monkeypatch):
    """save_weekly_report/generate_report_feedback가 실제 yfinance를 타지 않도록 고정값으로 목 처리."""
    monkeypatch.setattr(threads_summary, "get_latest_price", lambda ticker: 150.0)


def test_fallback_extract_finds_ticker_like_tokens_and_skips_common_words():
    result = threads_summary._fallback_extract("I think AAPL and MSFT will pop, but the market is risky.")
    assert "AAPL" in result["tickers"]
    assert "MSFT" in result["tickers"]
    assert "I" not in result["tickers"]
    assert "THE" not in result["tickers"]
    assert "요약을 생성하지 못했습니다" in result["summary"]


def test_analyze_text_without_api_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    result = threads_summary.analyze_text("$TSLA to the moon")
    assert result["tickers"] == ["TSLA"]


def test_analyze_text_handles_api_failure_gracefully(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    class _FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            raise RuntimeError("network down")

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", _FakeClient)

    result = threads_summary.analyze_text("NVDA earnings beat expectations")
    assert "NVDA" in result["tickers"]
    assert "AI 호출 실패" in result["summary"]


def test_save_and_list_summaries(patched_session):
    summary_id = threads_summary.save_summary("AAPL 실적 좋음", ["aapl"], "애플 실적이 좋다는 내용")
    assert isinstance(summary_id, int)

    summaries = threads_summary.list_summaries()
    assert len(summaries) == 1
    assert summaries[0]["tickers"] == ["AAPL"]
    assert summaries[0]["ai_summary"] == "애플 실적이 좋다는 내용"


def test_save_summary_rejects_blank_text(patched_session):
    with pytest.raises(ValueError):
        threads_summary.save_summary("   ", ["AAPL"], "요약")


def test_update_tickers_allows_manual_retagging(patched_session):
    summary_id = threads_summary.save_summary("원문", ["AAPL"], "요약")
    threads_summary.update_tickers(summary_id, ["msft", "goog"])

    summaries = threads_summary.list_summaries()
    assert summaries[0]["tickers"] == ["GOOG", "MSFT"]


def test_update_tickers_raises_for_missing_id(patched_session):
    with pytest.raises(ValueError):
        threads_summary.update_tickers(999, ["AAPL"])


def test_delete_summary(patched_session):
    summary_id = threads_summary.save_summary("원문", ["AAPL"], "요약")
    threads_summary.delete_summary(summary_id)
    assert threads_summary.list_summaries() == []


def test_list_summaries_filters_by_ticker(patched_session):
    threads_summary.save_summary("글1", ["AAPL"], "요약1")
    threads_summary.save_summary("글2", ["MSFT"], "요약2")
    threads_summary.save_summary("글3", ["AAPL", "MSFT"], "요약3")

    aapl_only = threads_summary.list_summaries(ticker="aapl")
    assert {s["ai_summary"] for s in aapl_only} == {"요약1", "요약3"}


def test_list_tracked_tickers_dedupes_and_sorts(patched_session):
    threads_summary.save_summary("글1", ["MSFT"], "요약1")
    threads_summary.save_summary("글2", ["AAPL", "MSFT"], "요약2")

    assert threads_summary.list_tracked_tickers() == ["AAPL", "MSFT"]


def test_get_ticker_history_is_chronological_oldest_first(patched_session):
    threads_summary.save_summary("글1", ["AAPL"], "첫번째")
    threads_summary.save_summary("글2", ["AAPL"], "두번째")

    history = threads_summary.get_ticker_history("AAPL")
    assert [h["ai_summary"] for h in history] == ["첫번째", "두번째"]


# ----------------------------------------------------------------------------
# 주간 AI 인사이트 리포트
# ----------------------------------------------------------------------------


def _insert_summary_at(session, days_ago: int, tickers: list[str], ai_summary: str) -> None:
    row = ThreadsSummary(
        raw_text=f"{ai_summary} 원문",
        tickers=json.dumps(tickers),
        ai_summary=ai_summary,
        created_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    session.add(row)
    session.commit()


def test_list_summaries_between_filters_by_date_range(patched_session):
    _insert_summary_at(patched_session, days_ago=10, tickers=["AAPL"], ai_summary="오래된 글")
    _insert_summary_at(patched_session, days_ago=2, tickers=["AAPL"], ai_summary="최근 글")

    start = datetime.utcnow() - timedelta(days=7)
    end = datetime.utcnow()
    result = threads_summary.list_summaries_between("AAPL", start, end)

    assert [r["ai_summary"] for r in result] == ["최근 글"]


def test_generate_weekly_report_without_posts_returns_guidance_message(patched_session, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    result = threads_summary.generate_weekly_report("AAPL", days=7)
    assert result["post_count"] == 0
    assert "저장 글이 없습니다" in result["report"]


def test_generate_weekly_report_without_api_key_uses_fallback_digest(patched_session, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _insert_summary_at(patched_session, days_ago=1, tickers=["AAPL"], ai_summary="애플 실적 호조")

    result = threads_summary.generate_weekly_report("AAPL", days=7)
    assert result["post_count"] == 1
    assert "자동 리포트 실패" in result["report"]
    assert "애플 실적 호조" in result["report"]


def test_generate_weekly_report_handles_api_failure_gracefully(patched_session, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    _insert_summary_at(patched_session, days_ago=1, tickers=["NVDA"], ai_summary="엔비디아 신고가")

    class _FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            raise RuntimeError("network down")

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", _FakeClient)

    result = threads_summary.generate_weekly_report("NVDA", days=7)
    assert "AI 호출 실패" in result["report"]
    assert result["post_count"] == 1


def test_save_and_list_weekly_reports(patched_session):
    now = datetime.utcnow()
    report_id = threads_summary.save_weekly_report(
        "aapl", now - timedelta(days=7), now, post_count=3, report_text="이번 주 핵심 테마: ..."
    )
    assert isinstance(report_id, int)

    reports = threads_summary.list_weekly_reports("AAPL")
    assert len(reports) == 1
    assert reports[0]["ticker"] == "AAPL"
    assert reports[0]["post_count"] == 3
    assert reports[0]["report_text"] == "이번 주 핵심 테마: ..."
    assert reports[0]["price_at_generation"] == 150.0


def test_delete_weekly_report(patched_session):
    now = datetime.utcnow()
    id1 = threads_summary.save_weekly_report("AAPL", now, now, post_count=1, report_text="리포트1")
    threads_summary.save_weekly_report("AAPL", now, now, post_count=1, report_text="리포트2")

    threads_summary.delete_weekly_report(id1)

    remaining = threads_summary.list_weekly_reports("AAPL")
    assert len(remaining) == 1
    assert remaining[0]["report_text"] == "리포트2"


def test_get_weekly_report_returns_none_for_missing_id(patched_session):
    assert threads_summary.get_weekly_report(999) is None


# ----------------------------------------------------------------------------
# 리포트 사후 검증(회고) 피드백
# ----------------------------------------------------------------------------


def test_generate_report_feedback_raises_for_missing_report(patched_session):
    with pytest.raises(ValueError):
        threads_summary.generate_report_feedback(999)


def test_generate_report_feedback_without_api_key_uses_fallback(patched_session, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    now = datetime.utcnow()
    report_id = threads_summary.save_weekly_report("AAPL", now, now, post_count=2, report_text="원본 리포트")
    # created_at은 save_weekly_report 호출 시점(now)으로 자동 기록되므로, "30일 전에 생성된 리포트"를
    # 흉내내려면 저장 후 직접 되돌려야 한다.
    row = patched_session.get(ThreadsWeeklyReport, report_id)
    row.created_at = now - timedelta(days=30)
    patched_session.commit()
    # 저장 시점 가격은 150.0(autouse mock), 회고 시점 가격은 180.0으로 변경(+20%)
    monkeypatch.setattr(threads_summary, "get_latest_price", lambda ticker: 180.0)

    result = threads_summary.generate_report_feedback(report_id)
    assert result["price_at_generation"] == 150.0
    assert result["current_price"] == 180.0
    assert result["price_change_pct"] == pytest.approx(20.0)
    assert result["elapsed_days"] >= 29
    assert "자동 회고 실패" in result["feedback"]
    assert "+20.0%" in result["feedback"]


def test_generate_report_feedback_handles_api_failure_gracefully(patched_session, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    now = datetime.utcnow()
    report_id = threads_summary.save_weekly_report("NVDA", now, now, post_count=1, report_text="원본 리포트")

    class _FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            raise RuntimeError("network down")

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    import google.genai as genai

    monkeypatch.setattr(genai, "Client", _FakeClient)

    result = threads_summary.generate_report_feedback(report_id)
    assert "AI 호출 실패" in result["feedback"]


def test_save_report_feedback_updates_report(patched_session):
    now = datetime.utcnow()
    report_id = threads_summary.save_weekly_report("AAPL", now, now, post_count=1, report_text="원본")

    threads_summary.save_report_feedback(report_id, "회고 내용입니다", 160.0)

    updated = threads_summary.get_weekly_report(report_id)
    assert updated["feedback_text"] == "회고 내용입니다"
    assert updated["feedback_price"] == 160.0
    assert updated["feedback_generated_at"] is not None
