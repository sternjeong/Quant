"""core/retry.py 단위 테스트 (지수 백오프 재시도 공용 유틸).

Day5 "self-healing data pipeline" 아이디어를 core.fred_data/core.market_data에 적용하기 위해
도입한 공용 헬퍼. 여기서는 순수 함수 동작만 검증하고(네트워크 없음), 실제 적용은
test_fred_data.py/test_market_data.py에서 검증한다.
"""

import pytest

from core.retry import retry_with_backoff


def test_succeeds_on_first_attempt_without_sleeping(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("core.retry.time.sleep", lambda s: sleep_calls.append(s))

    result = retry_with_backoff(lambda: 42)

    assert result == 42
    assert sleep_calls == []


def test_retries_then_succeeds_with_exponential_backoff(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("core.retry.time.sleep", lambda s: sleep_calls.append(s))
    attempts = {"n": 0}

    def _flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("일시적 오류")
        return "ok"

    result = retry_with_backoff(_flaky, max_attempts=5, base_delay_seconds=1.5)

    assert result == "ok"
    assert attempts["n"] == 3
    assert sleep_calls == [1.5, 3.0]  # 지수 백오프: 1.5 * 2**(attempt-1)


def test_exhausts_retries_and_raises_last_exception(monkeypatch):
    monkeypatch.setattr("core.retry.time.sleep", lambda s: None)
    attempts = {"n": 0}

    def _always_fails():
        attempts["n"] += 1
        raise ValueError(f"failure #{attempts['n']}")

    with pytest.raises(ValueError, match="failure #3"):
        retry_with_backoff(_always_fails, max_attempts=3, base_delay_seconds=0.01)

    assert attempts["n"] == 3


def test_on_retry_callback_invoked_with_attempt_info(monkeypatch):
    monkeypatch.setattr("core.retry.time.sleep", lambda s: None)
    calls = []

    def _on_retry(attempt, max_attempts, delay, exc):
        calls.append((attempt, max_attempts, delay, str(exc)))

    attempts = {"n": 0}

    def _flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("boom")
        return "done"

    result = retry_with_backoff(_flaky, max_attempts=3, base_delay_seconds=2.0, on_retry=_on_retry)

    assert result == "done"
    assert calls == [(1, 3, 2.0, "boom")]


def test_non_retryable_exception_propagates_immediately(monkeypatch):
    """exceptions 파라미터에 지정하지 않은 예외 타입은 재시도 없이 바로 전파돼야 한다."""
    sleep_calls = []
    monkeypatch.setattr("core.retry.time.sleep", lambda s: sleep_calls.append(s))
    attempts = {"n": 0}

    def _fails_with_keyerror():
        attempts["n"] += 1
        raise KeyError("not retryable")

    with pytest.raises(KeyError):
        retry_with_backoff(_fails_with_keyerror, max_attempts=3, exceptions=(ConnectionError,))

    assert attempts["n"] == 1  # 재시도 없이 즉시 전파
    assert sleep_calls == []


def test_max_attempts_must_be_at_least_one():
    with pytest.raises(ValueError):
        retry_with_backoff(lambda: 1, max_attempts=0)
