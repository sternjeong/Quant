"""core/telegram_notify.py 단위 테스트.

실제 텔레그램 API를 호출하지 않도록 requests.post를 monkeypatch 한다.
"""

import pytest

from core import telegram_notify


def test_is_configured_false_when_env_vars_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram_notify.is_configured() is False


def test_is_configured_true_when_both_env_vars_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    assert telegram_notify.is_configured() is True


def test_send_message_returns_false_without_configuration(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram_notify.send_message("hello") is False


def test_send_message_posts_to_telegram_api_when_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    calls = []

    class _FakeResponse:
        status_code = 200

    def _fake_post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data, "timeout": timeout})
        return _FakeResponse()

    monkeypatch.setattr(telegram_notify.requests, "post", _fake_post)

    result = telegram_notify.send_message("테스트 메시지")

    assert result is True
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.telegram.org/botfake-token/sendMessage"
    assert calls[0]["data"] == {"chat_id": "12345", "text": "테스트 메시지"}


def test_send_message_returns_false_on_non_200_response(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    class _FakeResponse:
        status_code = 400

    monkeypatch.setattr(telegram_notify.requests, "post", lambda *a, **k: _FakeResponse())
    assert telegram_notify.send_message("hello") is False


def test_send_message_returns_false_on_network_exception(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    def _raise(*a, **k):
        raise ConnectionError("network down")

    monkeypatch.setattr(telegram_notify.requests, "post", _raise)
    assert telegram_notify.send_message("hello") is False
