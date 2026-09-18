"""텔레그램으로 알림을 보낸다.

core/notify.py(데스크톱 알림, `plyer` 기반)와는 다른 채널이다 — 데스크톱 알림은 Streamlit 앱이나
scheduler/run_scheduler.py가 떠 있는 그 컴퓨터 화면에만 뜨지만, 텔레그램은 서버(Oracle VM 등)에서
직접 사용자 휴대폰으로 알림을 보낼 수 있어 "컴퓨터를 켜두지 않아도 알림을 받고 싶다"는 요구에 맞는다.

core/ 관례: 설정(토큰/채팅ID)이 없거나 전송에 실패해도 예외를 던지지 않는다(다른 core 모듈과 동일 —
알림은 부가 기능이라 실패해도 호출부의 본 작업을 막으면 안 된다).
"""

from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API_BASE = "https://api.telegram.org"
_REQUEST_TIMEOUT_SECONDS = 10


def is_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN")) and bool(os.getenv("TELEGRAM_CHAT_ID"))


def send_message(text: str) -> bool:
    """텔레그램으로 메시지를 보낸다. 설정이 없거나 전송에 실패하면 False(예외 없음)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        return resp.status_code == 200
    except Exception:
        return False


def send_document(path: str | Path, caption: str = "") -> bool:
    """HTML 등 작은 보고서 파일을 텔레그램 문서로 전송한다.

    알림은 부가 기능이므로 파일이 없거나 전송에 실패해도 예외를 호출부에 전달하지 않는다.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    report_path = Path(path)
    if not token or not chat_id or not report_path.is_file():
        return False
    try:
        with report_path.open("rb") as report:
            resp = requests.post(
                f"{TELEGRAM_API_BASE}/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"document": (report_path.name, report, "text/html")},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        return resp.status_code == 200
    except Exception:
        return False
