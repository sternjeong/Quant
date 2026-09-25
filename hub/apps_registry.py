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
    kind: str  # "web" (같은 호스트의 다른 포트) | "link" (별도 주소, url) | "report" (최신 HTML 리포트 서빙) | "engine" (상태만 표시) | "alpaca" (Alpaca paper 결과 화면) | "ops" (운영 상태 화면) | "research" (에이전트 연구 화면)
    port: int | None = None  # kind == "web"일 때 슬롯이 직접 링크할 포트
    url: str | None = None  # kind == "link"일 때 슬롯이 링크할 전체 주소(예: nginx 뒤 HTTPS 도메인)
    report_glob: str | None = None  # kind == "report"일 때 최신 파일을 찾을 glob 패턴(저장소 루트 기준)
    category: str = "엔진"  # 대시보드에서 카드를 묶는 제목


SLOTS: list[AppSlot] = [
    AppSlot(
        id="streamlit",
        title="퀀트 대시보드",
        description="전략 백테스팅 · 스크리너 · 포트폴리오 등 메인 Streamlit 웹앱 — HTTPS 주소로 접속, 로그인 필요",
        unit="quant-streamlit.service",
        kind="link",
        category="앱",
        url="https://app.hessejeong.duckdns.org/",
    ),
    AppSlot(
        id="scheduler",
        title="백그라운드 스케줄러",
        description="장마감 후 관심종목 스캔, 주간 리포트, 챔피언 전략 · shadow 기록 등 예약 작업",
        unit="quant-scheduler.service",
        kind="engine",
    ),
    AppSlot(
        id="alpaca",
        title="Alpaca paper 검증",
        description="실 API 검증 · 추적오차 · 실측 비용 · 자동 주문 기록 (전략 검증용 모의 계좌, 실거래 없음)",
        unit="quant-scheduler.service",
        kind="alpaca",
        category="연구·검증",
    ),
    AppSlot(
        id="research",
        title="AI 에이전트 연구",
        description="가설 퍼널 · 누적 시도 수 · shadow/승격 후보 · 에이전트 예산 (매일 03:00 KST 배치)",
        unit="quant-scheduler.service",
        kind="research",
        category="연구·검증",
    ),
    AppSlot(
        id="ops",
        title="운영 상태",
        description="스케줄러 잡 건강 · 백업 · 서버 자원 · 예약 타이머 (텔레그램 알림과 같은 원천)",
        unit="quant-watchdog.timer",
        kind="ops",
        category="운영",
    ),
    AppSlot(
        id="report-daily-briefing",
        title="오늘의 브리핑",
        description="밤사이 챔피언·시장·잡 결과를 모은 최신 브리핑 (텔레그램으로도 발송)",
        unit="quant-scheduler.service",
        kind="report",
        category="리포트",
        report_glob="data/cache/champion_reports/daily_briefing_*.html",
    ),
    AppSlot(
        id="report-champion-weekly",
        title="챔피언 전략 주간 보고",
        description="일요일 20:20(ET)에 생성되는 챔피언 전략 주간 리포트의 최신본",
        unit="quant-scheduler.service",
        kind="report",
        category="리포트",
        report_glob="data/cache/champion_reports/champion_weekly_*.html",
    ),
    AppSlot(
        id="report-news-digest",
        title="티커별 뉴스 다이제스트",
        description="매일 07:30(KST) 생성되는 관심 종목 뉴스 리포트의 최신본",
        unit="quant-scheduler.service",
        kind="report",
        category="리포트",
        report_glob=".news-digest/reports/news_*.html",
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
        category="앱",
        url="https://code.hessejeong.duckdns.org/",
    ),
]
