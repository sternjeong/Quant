"""설명서에서 코드로부터 자동으로 읽어 오는 부분 — 사람이 고치지 않아도 낡지 않는다.

- 화면 목록: core.app_navigation.NAVIGATION
- 자동 잡: core.job_schedule.SCHEDULED_JOBS + core.process_registry(이름·설명·현재 켜짐/꺼짐)
- 배포 버전·최근 변경: git (읽기 전용, 고정 인자, 타임아웃)
- 낡음 감지: 설명의 근거 파일이 verified 날짜 이후에 커밋됐는지

표준 라이브러리 + 위 stdlib-only 모듈만 쓴다.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from hub.guide.schema import PROJECT_ROOT

_GIT_TIMEOUT = 5
_CACHE_TTL = 600  # 초. 설명서를 열 때마다 git 을 수십 번 부르지 않는다
_cache: dict = {}


def _git(*args: str, cwd: Optional[Path] = None) -> Optional[str]:
    """읽기 전용 git 호출. 실패(없음/타임아웃/저장소 아님)는 None."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(cwd or PROJECT_ROOT), capture_output=True, text=True, timeout=_GIT_TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _cached(key: tuple, producer):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    value = producer()
    _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    _cache.clear()


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
def navigation() -> dict[str, list[tuple[str, str, str]]]:
    """{업무공간: [(path, title, icon), ...]} — Streamlit 사이드바와 같은 정의를 쓴다."""
    from core.app_navigation import NAVIGATION

    return {ws: [(p.path, p.title, p.icon) for p in pages] for ws, pages in NAVIGATION.items()}


def navigation_paths() -> set[str]:
    return {path for pages in navigation().values() for path, _, _ in pages}


# ---------------------------------------------------------------------------
# 자동 잡
# ---------------------------------------------------------------------------
_DOW_KO = {"mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}


@dataclass(frozen=True)
class JobRow:
    job_id: str
    label: str
    description: str
    category: str
    when_text: str  # "매일 00:27 KST" / "일 20:20 America/New_York (= 월 09:20 KST)"
    enabled: Optional[bool]  # None 이면 레지스트리에 없음(테스트가 막는다)


def _kst_equivalent(cron: dict) -> str:
    """다른 시간대의 잡을 오늘 기준 KST 로 환산해 보여 준다(서머타임 반영). 실패하면 빈 문자열."""
    tz = cron.get("timezone")
    if not tz or tz == "Asia/Seoul":
        return ""
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(tz))
        dt = now.replace(hour=int(cron.get("hour", 0)), minute=int(cron.get("minute", 0)), second=0, microsecond=0)
        kst = dt.astimezone(ZoneInfo("Asia/Seoul"))
    except Exception:  # noqa: BLE001 - tzdata 가 없으면 원래 시간대만 보여 준다
        return ""
    text = f"{kst:%H:%M} KST"
    dow = cron.get("day_of_week")
    if dow and "-" not in str(dow) and str(dow) in _DOW_KO:
        # 요일이 하루 밀리는지 계산
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        shift = (kst.date() - dt.date()).days
        text = f"{_DOW_KO[days[(days.index(str(dow)) + shift) % 7]]} {text}"
    return text


def format_when(cron: dict) -> str:
    hour, minute = int(cron.get("hour", 0)), int(cron.get("minute", 0))
    tz = cron.get("timezone", "")
    dow = cron.get("day_of_week")
    if dow is None:
        day = "매일"
    elif "-" in str(dow):
        a, b = str(dow).split("-", 1)
        day = f"{_DOW_KO.get(a, a)}~{_DOW_KO.get(b, b)}"
    else:
        day = _DOW_KO.get(str(dow), str(dow))
    base = f"{day} {hour:02d}:{minute:02d} {'KST' if tz == 'Asia/Seoul' else tz}"
    kst = _kst_equivalent(cron)
    return f"{base} (= {kst})" if kst else base


def job_rows() -> list[JobRow]:
    from core import process_registry as pr
    from core.job_schedule import SCHEDULED_JOBS

    rows = []
    for job in SCHEDULED_JOBS:
        entry = pr.PROCESS_REGISTRY.get(job.process_key)
        rows.append(
            JobRow(
                job_id=job.job_id,
                label=(entry or {}).get("label", job.job_id),
                description=(entry or {}).get("description", ""),
                category=(entry or {}).get("category", ""),
                when_text=format_when(job.cron),
                enabled=pr.is_enabled(job.process_key) if entry else None,
            )
        )
    return rows


def job_ids() -> set[str]:
    from core.job_schedule import SCHEDULED_JOBS

    return {j.job_id for j in SCHEDULED_JOBS}


# ---------------------------------------------------------------------------
# 배포 버전 · 최근 변경 · 낡음
# ---------------------------------------------------------------------------
def deployed_version() -> dict:
    def produce() -> dict:
        sha = _git("rev-parse", "--short", "HEAD")
        date_ = _git("log", "-1", "--format=%cs")
        subject = _git("log", "-1", "--format=%s")
        return {"sha": sha, "date": date_, "subject": subject, "available": sha is not None}

    return _cached(("version",), produce)


def recent_changes(limit: int = 25) -> list[dict]:
    """최근 커밋 목록(병합 커밋 제외). git 이 없으면 빈 목록."""

    def produce() -> list[dict]:
        out = _git("log", f"-{int(limit)}", "--no-merges", "--format=%cs%x1f%h%x1f%s")
        rows = []
        for line in (out or "").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                rows.append({"date": parts[0], "sha": parts[1], "subject": parts[2]})
        return rows

    return _cached(("changes", limit), produce)


def last_commit_date(paths: tuple[str, ...]) -> Optional[str]:
    """근거 파일들 중 가장 최근 커밋 날짜(YYYY-MM-DD). 알 수 없으면 None."""
    existing = tuple(p for p in paths if (PROJECT_ROOT / p).exists())
    if not existing:
        return None
    return _cached(("last", existing), lambda: _git("log", "-1", "--format=%cs", "--", *existing) or None)


def is_stale(verified: str, paths: tuple[str, ...]) -> Optional[bool]:
    """근거 파일이 verified 날짜 이후에 바뀌었으면 True. 판단 불가(git 없음)면 None."""
    last = last_commit_date(paths)
    if last is None or not verified:
        return None
    return last > verified
