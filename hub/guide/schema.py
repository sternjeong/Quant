"""관제 센터 사용 설명서의 데이터 형식과 검증.

설명서는 세 층으로 나뉜다.
  1) 자동 생성(hub/guide/live.py): 화면 목록·자동 잡 표·현재 켜짐/꺼짐·최근 변경·배포 버전. 코드에서 매번 읽으므로 낡지 않는다.
  2) 사람이 쓴 설명(content_*.py): 아래 dataclass 로 적는다. 각 항목은 근거 파일(sources)과 확인일(verified)을 가진다.
  3) 누락 차단(tests/test_hub_guide.py): 새 화면/잡/모듈/스크립트에 설명이 없거나, 사라진 것에 설명이 남아 있으면 테스트가 실패한다.
     자동배포의 테스트 관문(deploy/auto_deploy.sh)이 pytest 를 돌리므로 설명 없이는 배포되지 않는다.

이 모듈은 표준 라이브러리만 쓴다(허브는 stdlib 서버).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

STATUS_CHOICES = ("운영중", "관측 전용", "실험", "도구", "보관")
GROUP_CHOICES = ("운용", "리서치 인프라", "데이터", "분석·백테스트", "운영·안전", "화면 지원")
RISK_CHOICES = ("읽기 전용", "파일/DB 쓰기", "주문 가능", "서버 설정 변경")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class PageGuide:
    """Streamlit 화면 하나. path 는 core.app_navigation.PageSpec.path 와 정확히 같아야 한다."""

    path: str
    summary: str  # 한 줄: 이 화면이 무엇인가
    when_to_use: str  # 언제 여는가
    steps: tuple[str, ...]  # 사용 순서(화면에서 무엇을 누르고 무엇을 보나)
    reading: tuple[str, ...] = ()  # 결과/지표를 어떻게 읽나
    cautions: tuple[str, ...] = ()  # 오해하기 쉬운 점·한계
    related_jobs: tuple[str, ...] = ()  # 이 화면의 데이터를 채우는 자동 잡 id(SCHEDULED_JOBS)
    sources: tuple[str, ...] = ()  # 근거 파일(저장소 루트 기준, 존재해야 함)
    verified: str = ""  # 이 설명을 코드와 대조한 날짜 YYYY-MM-DD
    plain_summary: str = ""  # 선택: 처음 보는 사람용 쉬운 한 줄(상세 맨 위 '한눈에'). 코드·기존 설명에서 확인되는 사실만
    example: str = ""  # 선택: 구체적인 사용 예 한 가지


@dataclass(frozen=True)
class ModuleGuide:
    """엔진 모듈(core/*.py) 하나. module 은 저장소 루트 기준 경로."""

    module: str
    name: str  # 사람이 읽는 이름
    group: str  # GROUP_CHOICES
    status: str  # STATUS_CHOICES
    what: str  # 무엇을 하는가
    how_to_use: str  # 사용자가 이것을 어떻게 활용하나(화면/텔레그램/자동)
    where_to_see: str  # 결과를 보는 곳(화면 이름, 텔레그램, 파일 등). 없으면 "화면 없음"
    cautions: str = ""
    sources: tuple[str, ...] = ()  # 기본은 module 자신. 추가 근거가 있으면 적는다
    verified: str = ""


@dataclass(frozen=True)
class ScriptGuide:
    """운영·연구 스크립트(scripts/*.py 또는 deploy/ 아래 도구) 하나."""

    path: str
    name: str
    when_to_run: str
    command: str  # 실행 예시(키·비밀번호 값 금지)
    risk: str  # RISK_CHOICES
    what_it_prints: str  # 결과를 어떻게 읽나
    verified: str = ""


@dataclass(frozen=True)
class JobGuide:
    """자동 잡 하나의 사용자용 보충 설명. 이름·시각·설명·현재 상태는 레지스트리에서 자동으로 온다."""

    job_id: str
    where_to_see: str  # 결과를 어디서 보나
    if_alert: str = ""  # 알림/실패가 오면 무엇을 하나
    verified: str = ""


@dataclass(frozen=True)
class Term:
    term: str
    meaning: str
    why_it_matters: str = ""


@dataclass(frozen=True)
class Routine:
    """상황별 사용 순서(예: 매일 아침 5분 루틴)."""

    id: str
    title: str
    when: str
    steps: tuple[str, ...]
    tips: tuple[str, ...] = ()
    card_title: str = ""  # 선택: 설명서 첫 화면 할 일 카드의 짧은 이름(사용자 말투, 예: '알림이 왔어요')
    icon: str = ""  # 선택: 할 일 카드 아이콘(이모지 하나)
    plain_summary: str = ""  # 선택: 이 과업을 쉬운 말 한 줄로


@dataclass(frozen=True)
class OpsSection:
    """운영 안내(텔레그램 명령, 백업, 워치독, 배포, 알림 해석 등)."""

    id: str
    title: str
    body: tuple[str, ...]  # 문단 목록
    items: tuple[tuple[str, str], ...] = ()  # (이름, 설명) 목록
    verified: str = ""


@dataclass(frozen=True)
class GuideContent:
    pages: tuple[PageGuide, ...] = ()
    modules: tuple[ModuleGuide, ...] = ()
    internal_modules: dict = field(default_factory=dict)  # core 경로 -> 설명하지 않는 이유
    scripts: tuple[ScriptGuide, ...] = ()
    internal_scripts: dict = field(default_factory=dict)
    jobs: tuple[JobGuide, ...] = ()
    glossary: tuple[Term, ...] = ()
    routines: tuple[Routine, ...] = ()
    ops: tuple[OpsSection, ...] = ()
    start_here: tuple[str, ...] = ()  # 처음 오는 사람을 위한 문단들


def _valid_date(value: str) -> bool:
    if not _DATE_RE.match(value or ""):
        return False
    try:
        return date.fromisoformat(value) <= date.today()
    except ValueError:
        return False


def validate_entries(content: GuideContent) -> list[str]:
    """이미 적힌 항목들의 형식 문제를 모은다(누락 여부는 coverage 검사가 따로 본다)."""
    problems: list[str] = []

    def need(label: str, **fields: str) -> None:
        for key, value in fields.items():
            if not str(value or "").strip():
                problems.append(f"{label}: '{key}' 가 비어 있습니다")

    for p in content.pages:
        need(f"화면 {p.path}", summary=p.summary, when_to_use=p.when_to_use)
        if not p.steps:
            problems.append(f"화면 {p.path}: 'steps' 가 비어 있습니다")
        if not _valid_date(p.verified):
            problems.append(f"화면 {p.path}: verified 가 YYYY-MM-DD(오늘 이전)가 아닙니다: {p.verified!r}")
        for s in p.sources:
            if not (PROJECT_ROOT / s).exists():
                problems.append(f"화면 {p.path}: 근거 파일이 없습니다: {s}")
    for m in content.modules:
        need(f"모듈 {m.module}", name=m.name, what=m.what, how_to_use=m.how_to_use, where_to_see=m.where_to_see)
        if m.group not in GROUP_CHOICES:
            problems.append(f"모듈 {m.module}: group 은 {GROUP_CHOICES} 중 하나여야 합니다: {m.group!r}")
        if m.status not in STATUS_CHOICES:
            problems.append(f"모듈 {m.module}: status 는 {STATUS_CHOICES} 중 하나여야 합니다: {m.status!r}")
        if not _valid_date(m.verified):
            problems.append(f"모듈 {m.module}: verified 가 YYYY-MM-DD(오늘 이전)가 아닙니다: {m.verified!r}")
        for s in (m.module, *m.sources):
            if not (PROJECT_ROOT / s).exists():
                problems.append(f"모듈 {m.module}: 근거 파일이 없습니다: {s}")
    for path, reason in content.internal_modules.items():
        if not str(reason).strip():
            problems.append(f"내부 모듈 {path}: 설명하지 않는 이유가 비어 있습니다")
        if not (PROJECT_ROOT / path).exists():
            problems.append(f"내부 모듈 {path}: 파일이 없습니다(삭제됐다면 목록에서 지우세요)")
    for s in content.scripts:
        need(f"스크립트 {s.path}", name=s.name, when_to_run=s.when_to_run, command=s.command, what_it_prints=s.what_it_prints)
        if s.risk not in RISK_CHOICES:
            problems.append(f"스크립트 {s.path}: risk 는 {RISK_CHOICES} 중 하나여야 합니다: {s.risk!r}")
        if not _valid_date(s.verified):
            problems.append(f"스크립트 {s.path}: verified 가 YYYY-MM-DD(오늘 이전)가 아닙니다: {s.verified!r}")
        if not (PROJECT_ROOT / s.path).exists():
            problems.append(f"스크립트 {s.path}: 파일이 없습니다")
    for path, reason in content.internal_scripts.items():
        if not str(reason).strip():
            problems.append(f"내부 스크립트 {path}: 설명하지 않는 이유가 비어 있습니다")
        if not (PROJECT_ROOT / path).exists():
            problems.append(f"내부 스크립트 {path}: 파일이 없습니다(삭제됐다면 목록에서 지우세요)")
    for j in content.jobs:
        need(f"잡 {j.job_id}", where_to_see=j.where_to_see)
        if not _valid_date(j.verified):
            problems.append(f"잡 {j.job_id}: verified 가 YYYY-MM-DD(오늘 이전)가 아닙니다: {j.verified!r}")
    for t in content.glossary:
        need(f"용어 {t.term}", meaning=t.meaning)
    for r in content.routines:
        need(f"루틴 {r.id}", title=r.title, when=r.when)
        if not r.steps:
            problems.append(f"루틴 {r.id}: steps 가 비어 있습니다")
    for o in content.ops:
        need(f"운영 {o.id}", title=o.title)
        if not (o.body or o.items):
            problems.append(f"운영 {o.id}: body/items 가 모두 비어 있습니다")
        if not _valid_date(o.verified):
            problems.append(f"운영 {o.id}: verified 가 YYYY-MM-DD(오늘 이전)가 아닙니다: {o.verified!r}")
    # 중복 키
    for label, keys in (
        ("화면", [p.path for p in content.pages]), ("모듈", [m.module for m in content.modules]),
        ("스크립트", [s.path for s in content.scripts]), ("잡", [j.job_id for j in content.jobs]),
        ("용어", [t.term for t in content.glossary]), ("루틴", [r.id for r in content.routines]),
        ("운영", [o.id for o in content.ops]),
    ):
        dup = sorted({k for k in keys if keys.count(k) > 1})
        if dup:
            problems.append(f"{label} 설명이 중복됩니다: {dup}")
    return problems
