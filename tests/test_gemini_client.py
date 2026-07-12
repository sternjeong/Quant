"""core/gemini_client.py 단위 테스트 (여러 키/모델 순차 시도 및 429 자동 전환, 사용량 로깅)."""

from contextlib import contextmanager

import google.genai as genai
import pytest
from google.genai import errors as genai_errors

import core.db as core_db
import core.gemini_client as gemini_client


@pytest.fixture(autouse=True)
def _isolate_db(db_session, monkeypatch):
    """generate_content()가 남기는 GeminiCallLog가 실제 운영 DB(data/quant.db)를 건드리지 않도록,
    이 파일의 모든 테스트에서 core.db.get_session을 임시 SQLite로 바꿔치기한다."""

    @contextmanager
    def _fake_get_session():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(core_db, "get_session", _fake_get_session)


def test_load_api_keys_prefers_plural_env_var(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "k1, k2 ,k3")
    monkeypatch.setenv("GEMINI_API_KEY", "single-key")
    assert gemini_client._load_api_keys() == ["k1", "k2", "k3"]


def test_load_api_keys_falls_back_to_singular_env_var(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "single-key")
    assert gemini_client._load_api_keys() == ["single-key"]


def test_has_api_key_false_when_nothing_set(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert gemini_client.has_api_key() is False


def test_generate_content_switches_key_on_quota_exhaustion(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "bad-key,good-key")

    class _FakeModels:
        @staticmethod
        def generate_content(model, contents, config):
            # bad-key로 만든 client만 429를 낸다 (good-key는 성공)
            raise genai_errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    class _FakeModelsOK:
        @staticmethod
        def generate_content(model, contents, config):
            return "ok-response"

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModelsOK() if api_key == "good-key" else _FakeModels()

    monkeypatch.setattr(genai, "Client", _FakeClient)

    result = gemini_client.generate_content(models=["model-a"], contents="hi")
    assert result == "ok-response"


def test_generate_content_raises_immediately_on_non_quota_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "key1,key2")

    class _FakeModels:
        @staticmethod
        def generate_content(model, contents, config):
            raise genai_errors.ClientError(400, {"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}})

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    calls = []
    orig_init = _FakeClient.__init__

    def _tracked_init(self, api_key):
        calls.append(api_key)
        orig_init(self, api_key)

    _FakeClient.__init__ = _tracked_init
    monkeypatch.setattr(genai, "Client", _FakeClient)

    try:
        gemini_client.generate_content(models=["model-a"], contents="hi")
        assert False, "400 에러는 재시도 없이 즉시 올라와야 한다"
    except genai_errors.ClientError as e:
        assert e.code == 400
    # key2는 아예 시도되지 않아야 한다 (400은 재시도 대상이 아님)
    assert calls == ["key1"]


def test_generate_content_raises_last_error_when_all_combos_exhausted(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "key1,key2")

    class _FakeModels:
        @staticmethod
        def generate_content(model, contents, config):
            raise genai_errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    monkeypatch.setattr(genai, "Client", _FakeClient)

    try:
        gemini_client.generate_content(models=["model-a", "model-b"], contents="hi")
        assert False, "모든 조합이 429면 마지막 예외를 던져야 한다"
    except genai_errors.ClientError as e:
        assert e.code == 429


def test_generate_content_logs_successful_call(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "good-key")

    class _FakeModels:
        @staticmethod
        def generate_content(model, contents, config):
            return "ok-response"

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    monkeypatch.setattr(genai, "Client", _FakeClient)
    gemini_client.generate_content(models=["model-a"], contents="hi")
    usage = gemini_client.get_usage_today()

    assert usage == {
        "configured_keys": 1,
        "total": 1,
        "ok": 1,
        "quota_exceeded": 0,
        "error": 0,
        "last_status": "ok",
    }


def test_generate_content_logs_quota_exceeded_then_success(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "bad-key,good-key")

    class _FakeModelsBad:
        @staticmethod
        def generate_content(model, contents, config):
            raise genai_errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    class _FakeModelsOK:
        @staticmethod
        def generate_content(model, contents, config):
            return "ok-response"

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModelsOK() if api_key == "good-key" else _FakeModelsBad()

    monkeypatch.setattr(genai, "Client", _FakeClient)

    gemini_client.generate_content(models=["model-a"], contents="hi")
    usage = gemini_client.get_usage_today()

    assert usage["total"] == 2  # bad-key(429) 시도 1건 + good-key(성공) 시도 1건
    assert usage["ok"] == 1
    assert usage["quota_exceeded"] == 1
    assert usage["last_status"] == "ok"  # 결과적으로 성공했으므로 마지막 기록은 ok


def test_generate_content_logs_non_quota_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "key1")

    class _FakeModels:
        @staticmethod
        def generate_content(model, contents, config):
            raise genai_errors.ClientError(400, {"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}})

    class _FakeClient:
        def __init__(self, api_key):
            self.models = _FakeModels()

    monkeypatch.setattr(genai, "Client", _FakeClient)
    try:
        gemini_client.generate_content(models=["model-a"], contents="hi")
    except genai_errors.ClientError:
        pass
    usage = gemini_client.get_usage_today()

    assert usage["total"] == 1
    assert usage["error"] == 1
    assert usage["last_status"] == "error"


def test_get_usage_today_without_api_key_reports_zero_configured_keys(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    usage = gemini_client.get_usage_today()

    assert usage["configured_keys"] == 0
    assert usage["total"] == 0
    assert usage["last_status"] is None


def test_log_call_swallows_db_errors(monkeypatch):
    @contextmanager
    def _broken_get_session():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(core_db, "get_session", _broken_get_session)

    gemini_client._log_call("model-a", 0, "ok")  # 예외 없이 조용히 무시돼야 한다
