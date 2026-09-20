"""Quant VM 허브 대시보드에 표시할 앱/엔진 목록.

새 서비스를 VM에 배포하면 여기에 슬롯 하나를 추가하기만 하면 hub/server.py가 자동으로
카드를 렌더링한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppSlot:
    id: str
    title: str
    description: str
    unit: str  # 상태 조회에 쓸 systemd 유닛 이름
    kind: str  # "web" (같은 호스트의 다른 포트) | "link" (별도 주소, url) | "report" (최신 HTML 리포트 서빙) | "engine" (상태만 표시)
    port: int | None = None  # kind == "web"일 때 슬롯이 직접 링크할 포트
    url: str | None = None  # kind == "link"일 때 슬롯이 링크할 전체 주소(예: nginx 뒤 HTTPS 도메인)
    report_glob: str | None = None  # kind == "report"일 때 최신 파일을 찾을 glob 패턴(저장소 루트 기준)


SLOTS: list[AppSlot] = [
    AppSlot(
        id="streamlit",
        title="퀀트 대시보드",
        description="전략 백테스팅 · 스크리너 · 포트폴리오 등 메인 Streamlit 웹앱",
        unit="quant-streamlit.service",
        kind="web",
        port=8501,
    ),
    AppSlot(
        id="scheduler",
        title="백그라운드 스케줄러",
        description="장마감 후 관심종목 스캔, 주간 리포트, 나이틀리 튜닝 등 예약 작업",
        unit="quant-scheduler.service",
        kind="engine",
    ),
    AppSlot(
        id="experiment-supervisor",
        title="2주 실험 슈퍼바이저",
        description="전략 실험을 자동 진행하고 매일 텔레그램으로 HTML 리포트 발송",
        unit="quant-experiment-supervisor.service",
        kind="report",
        report_glob=".experiment-control/reports/*.html",
    ),
    AppSlot(
        id="codex-telegram",
        title="Codex/Claude 텔레그램 에이전트",
        description="텔레그램 지시를 받아 무인으로 코드를 작성 · 배포하는 상시 리스너",
        unit="codex-telegram.service",
        kind="engine",
    ),
    AppSlot(
        id="vm-health",
        title="VM 헬스체크",
        description="디스크/메모리 사용률을 주기적으로 점검하고 임계값 초과 시 텔레그램 알림",
        unit="quant-vm-health.service",
        kind="engine",
    ),
    AppSlot(
        id="code-server",
        title="브라우저 코드 스페이스",
        description="VS Code 기반 브라우저 IDE(code-server) — HTTPS 주소로 접속, 로그인 비밀번호 필요",
        unit="code-server@ubuntu.service",
        kind="link",
        url="https://hessejeong.duckdns.org/",
    ),
]
