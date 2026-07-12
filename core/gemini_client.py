"""여러 Gemini API 키/모델을 순서대로 시도하는 공통 호출 헬퍼.

core/nl_strategy.py, core/threads_summary.py, core/portfolio.py 가 전부 이 모듈을 통해서만
Gemini를 호출한다 (client 생성·재시도 로직을 여러 곳에 중복하지 않기 위함). 하나의 (모델, 키)
조합이 쿼터 소진(429 RESOURCE_EXHAUSTED)으로 실패하면 자동으로 같은 모델의 다음 키로, 그마저
다 떨어지면 다음 모델로 넘어간다. 그 외의 실패(400 등 요청 자체 문제, 네트워크 오류)는 재시도 없이
즉시 상위로 전파해 호출부의 기존 키워드 기반 대체(fallback) 로직이 그대로 동작하게 한다.

GEMINI_API_KEYS(쉼표로 구분된 여러 키) 환경변수를 우선 사용하고, 없으면 기존 GEMINI_API_KEY
(단일 키)를 그대로 지원한다.
"""

from __future__ import annotations

import os
from typing import Any, Optional

# 2026-07-12 기준 이 계정(무료 티어)에서 실제로 응답 가능한 것을 확인한 모델만 사용한다.
# gemini-*-pro-* 계열(3-pro-preview/3.1-pro-preview/2.5-pro/pro-latest)과 gemini-2.0-flash(-lite),
# gemini-2.5-flash-lite(신규 프로젝트에 더 이상 제공 안 함)는 전부 무료 티어에서 429/404로 항상
# 실패해서 후보에서 제외했다. 결제를 연결하면 pro 계열도 다시 시도해볼 수 있다.
COMPLEX_TASK_MODELS = ["gemini-3-flash-preview", "gemini-3.5-flash", "gemini-2.5-flash", "gemini-flash-latest"]
LIGHT_TASK_MODELS = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-2.5-flash"]


def _load_api_keys() -> list[str]:
    multi = os.getenv("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in multi.split(",") if k.strip()]
    if keys:
        return keys
    single = os.getenv("GEMINI_API_KEY", "").strip()
    return [single] if single else []


def has_api_key() -> bool:
    return bool(_load_api_keys())


def _log_call(model: str, key_index: int, status: str, error_message: Optional[str] = None) -> None:
    """호출 시도 결과를 기록한다 (core.theme의 우측 상단 사용량 배지용). 실패해도 실제 AI 호출 흐름에
    영향을 주면 안 되므로 예외를 전부 삼킨다 — 로깅은 부가 기능이지 핵심 경로가 아니다."""
    try:
        from core.db import get_session
        from core.models import GeminiCallLog

        with get_session() as session:
            session.add(
                GeminiCallLog(
                    model=model,
                    key_label=f"key{key_index + 1}",
                    status=status,
                    error_message=(error_message[:500] if error_message else None),
                )
            )
    except Exception:
        pass


def get_usage_today() -> dict:
    """오늘(UTC) 호출 시도 현황 요약. Google 무료 티어는 잔여 할당량 조회 API가 없어, 이 앱이 자체
    기록한 시도/성공/한도초과(429)/기타오류 횟수를 근사치로 보여주는 용도다 (core.theme의 배지용)."""
    from datetime import datetime

    from core.db import get_session
    from core.models import GeminiCallLog

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        with get_session() as session:
            rows = session.query(GeminiCallLog).filter(GeminiCallLog.called_at >= today_start).all()
            statuses = [r.status for r in rows]
    except Exception:
        statuses = []

    return {
        "configured_keys": len(_load_api_keys()),
        "total": len(statuses),
        "ok": statuses.count("ok"),
        "quota_exceeded": statuses.count("quota_exceeded"),
        "error": statuses.count("error"),
        "last_status": statuses[-1] if statuses else None,
    }


def generate_content(
    models: list[str],
    contents: str,
    system_instruction: Optional[str] = None,
    response_mime_type: Optional[str] = None,
    response_json_schema: Optional[dict[str, Any]] = None,
):
    """models 순서대로, 각 모델마다 등록된 키 순서대로 시도해 첫 성공 응답을 반환한다.

    모든 (모델, 키) 조합이 429로 실패하면 마지막 429 예외를 그대로 던진다(호출부가 fallback 처리).
    429가 아닌 예외(400 등)는 재시도 없이 즉시 던진다 — 요청 자체가 잘못된 경우 다른 키/모델로
    바꿔도 똑같이 실패할 뿐이므로 조용히 낭비하지 않는다.

    시도마다 결과를 GeminiCallLog에 기록한다(core.theme의 우측 상단 사용량 배지가 이 기록을 읽는다).
    """
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    keys = _load_api_keys()
    if not keys:
        raise RuntimeError("GEMINI_API_KEY(S)가 설정되지 않았습니다.")

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type=response_mime_type,
        response_json_schema=response_json_schema,
    )

    last_exc: Optional[Exception] = None
    for model in models:
        for key_index, key in enumerate(keys):
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(model=model, contents=contents, config=config)
                _log_call(model, key_index, "ok")
                return response
            except genai_errors.APIError as e:
                last_exc = e
                if getattr(e, "code", None) == 429:
                    _log_call(model, key_index, "quota_exceeded", str(e))
                    continue  # 이 키로는 이 모델 쿼터가 소진됨 -> 다음 키(또는 다음 모델)로 전환
                _log_call(model, key_index, "error", str(e))
                raise
    assert last_exc is not None
    raise last_exc
