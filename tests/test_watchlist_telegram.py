"""관심종목 스캔 잡 / Threads 주간 잡의 텔레그램 알림 테스트 (2026-09-25).

요구사항:
- 충족 0건이면 텔레그램을 보내지 않는다.
- 충족이 있으면 요약 1건을 보내고, 내용에 종목이 들어간다.
- 같은 날(같은 기준일) 재실행하면 다시 보내지 않는다.
- 텔레그램 미설정/전송 실패여도 잡은 예외 없이 끝나고 alerts_log 는 기록된다. 전송 실패는 report_job_failure 로 남는다.
- Threads 주간 잡은 완료 알림 1건을 텔레그램으로 보낸다.

외부 호출은 전부 가짜로 바꾼다: 전략 평가(core.watchlist.evaluate), HTTP(core.telegram_notify.requests.post),
데스크톱 알림, DB 세션(임시 SQLite).
"""

from contextlib import contextmanager

import pytest

import core.telegram_notify as telegram_notify
import core.watchlist as watchlist
from core import process_registry
from core.models import AlertLog, Strategy, WatchlistItem
from scheduler import run_scheduler


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture()
def env(db_session, monkeypatch, tmp_path):
    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(watchlist, "get_session", _fake_get_session)
    monkeypatch.setattr(watchlist, "TELEGRAM_SENT_STATE_PATH", tmp_path / "sent.json")
    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "toggles.json")
    monkeypatch.setattr(run_scheduler, "send_desktop_notification", lambda *a, **k: None)

    failures = []
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda job_id, err: failures.append((job_id, str(err))))

    posts = []

    def _fake_post(url, data=None, timeout=None, **kwargs):
        posts.append({"url": url, "data": dict(data or {})})
        return _Resp(200)

    monkeypatch.setattr(telegram_notify.requests, "post", _fake_post)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "dummy-chat")

    return {"db": db_session, "posts": posts, "failures": failures, "monkeypatch": monkeypatch}


def _add_items(db, tickers):
    strategy = Strategy(name="골든크로스", indicator_config="{}", source="manual")
    db.add(strategy)
    db.commit()
    for t in tickers:
        db.add(WatchlistItem(ticker=t, strategy_id=strategy.id))
    db.commit()


def _patch_evaluate(monkeypatch, triggered_tickers, as_of="2026-09-24"):
    def _fake_evaluate(ticker, indicator_config):
        hit = ticker in triggered_tickers
        return {
            "triggered": hit,
            "in_position": hit,
            "as_of": as_of,
            "message": f"{ticker}: {'신규 진입 신호' if hit else '조건 미충족'}",
        }

    monkeypatch.setattr(watchlist, "evaluate", _fake_evaluate)


def _message_posts(posts):
    return [p for p in posts if p["url"].endswith("/sendMessage")]


def test_no_triggered_sends_nothing(env):
    _add_items(env["db"], ["AAPL", "MSFT"])
    _patch_evaluate(env["monkeypatch"], set())

    run_scheduler.watchlist_scan_job()

    assert env["posts"] == []
    assert env["db"].query(AlertLog).count() == 0
    assert env["failures"] == []


def test_triggered_sends_one_summary_with_tickers(env):
    _add_items(env["db"], ["AAPL", "MSFT", "NVDA"])
    _patch_evaluate(env["monkeypatch"], {"AAPL", "NVDA"})

    run_scheduler.watchlist_scan_job()

    msgs = _message_posts(env["posts"])
    assert len(msgs) == 1
    text = msgs[0]["data"]["text"]
    assert "AAPL" in text and "NVDA" in text
    assert "MSFT" not in text
    assert "골든크로스" in text
    assert env["db"].query(AlertLog).count() == 2
    assert env["failures"] == []


def test_rerun_same_day_does_not_resend(env):
    _add_items(env["db"], ["AAPL"])
    _patch_evaluate(env["monkeypatch"], {"AAPL"})

    run_scheduler.watchlist_scan_job()
    run_scheduler.watchlist_scan_job()

    assert len(_message_posts(env["posts"])) == 1


def test_new_as_of_day_sends_again(env):
    _add_items(env["db"], ["AAPL"])
    _patch_evaluate(env["monkeypatch"], {"AAPL"}, as_of="2026-09-24")
    run_scheduler.watchlist_scan_job()
    _patch_evaluate(env["monkeypatch"], {"AAPL"}, as_of="2026-09-25")
    run_scheduler.watchlist_scan_job()

    assert len(_message_posts(env["posts"])) == 2


def test_many_triggered_are_truncated_with_remainder(env):
    tickers = [f"T{i:02d}" for i in range(13)]
    _add_items(env["db"], tickers)
    _patch_evaluate(env["monkeypatch"], set(tickers))

    run_scheduler.watchlist_scan_job()

    msgs = _message_posts(env["posts"])
    assert len(msgs) == 1
    text = msgs[0]["data"]["text"]
    assert "13건" in text
    assert "외 3건" in text


def test_not_configured_job_finishes_and_logs_alerts(env):
    env["monkeypatch"].delenv("TELEGRAM_BOT_TOKEN", raising=False)
    env["monkeypatch"].delenv("TELEGRAM_CHAT_ID", raising=False)
    _add_items(env["db"], ["AAPL"])
    _patch_evaluate(env["monkeypatch"], {"AAPL"})

    run_scheduler.watchlist_scan_job()  # 예외 없이 끝나야 한다

    assert env["posts"] == []
    assert env["db"].query(AlertLog).count() == 1


def test_send_failure_job_finishes_reports_failure_and_retries_next_run(env):
    def _raise(*a, **k):
        raise ConnectionError("network down")

    env["monkeypatch"].setattr(telegram_notify.requests, "post", _raise)
    _add_items(env["db"], ["AAPL"])
    _patch_evaluate(env["monkeypatch"], {"AAPL"})

    run_scheduler.watchlist_scan_job()  # 예외 없이 끝나야 한다

    assert env["db"].query(AlertLog).count() == 1
    assert len(env["failures"]) == 1
    assert env["failures"][0][0] == "daily_watchlist_scan"

    # 실패한 건은 '보냄'으로 기록되지 않으므로 복구 후 재실행 때 보낸다.
    posts = env["posts"]
    env["monkeypatch"].setattr(
        telegram_notify.requests, "post",
        lambda url, data=None, timeout=None, **k: posts.append({"url": url, "data": dict(data or {})}) or _Resp(200),
    )
    run_scheduler.watchlist_scan_job()
    assert len(_message_posts(posts)) == 1


def test_non_200_response_counts_as_failure(env):
    env["monkeypatch"].setattr(telegram_notify.requests, "post", lambda *a, **k: _Resp(500))
    _add_items(env["db"], ["AAPL"])
    _patch_evaluate(env["monkeypatch"], {"AAPL"})

    run_scheduler.watchlist_scan_job()

    assert env["db"].query(AlertLog).count() == 1
    assert [f[0] for f in env["failures"]] == ["daily_watchlist_scan"]


def test_threads_weekly_job_sends_one_completion_message(env):
    mp = env["monkeypatch"]
    mp.setattr(run_scheduler, "list_tracked_tickers", lambda: ["AAPL", "TSLA"])
    mp.setattr(
        run_scheduler, "generate_weekly_report",
        lambda ticker, days=7: {
            "ticker": ticker, "period_start": "2026-09-18", "period_end": "2026-09-25",
            "post_count": 3 if ticker == "AAPL" else 0, "report": "요약",
        },
    )
    saved = []
    mp.setattr(run_scheduler, "save_weekly_report", lambda *a, **k: saved.append(a))

    run_scheduler.threads_weekly_report_job()

    assert len(saved) == 1
    assert len(env["posts"]) == 1
    assert env["posts"][0]["url"].endswith("/sendMessage")
    text = env["posts"][0]["data"]["text"]
    assert "Threads" in text
    assert "2개 티커 중 1개" in text
    assert env["failures"] == []


def test_threads_weekly_job_send_failure_does_not_raise(env):
    mp = env["monkeypatch"]
    mp.setattr(telegram_notify.requests, "post", lambda *a, **k: _Resp(500))
    mp.setattr(run_scheduler, "list_tracked_tickers", lambda: ["AAPL"])
    mp.setattr(
        run_scheduler, "generate_weekly_report",
        lambda ticker, days=7: {"ticker": ticker, "period_start": "a", "period_end": "b", "post_count": 1, "report": "r"},
    )
    mp.setattr(run_scheduler, "save_weekly_report", lambda *a, **k: None)

    run_scheduler.threads_weekly_report_job()

    assert [f[0] for f in env["failures"]] == ["weekly_threads_report"]
