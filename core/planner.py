"""할 일·일정 — AI 대회·내 프로젝트·주식 관련 '오늘 / 이번 주' 할 일을 한곳에 모은다 (2026-11-15).

관제 허브 '할 일' 화면(hub/planner_page.py)의 뒷단. 할 일은 data/planner.json 하나에 저장한다(커밋하지 않음).
자동 항목(따로 적지 않아도 보임):
  - AI 대회: 아직 제출하지 않은 대회(core/contests.py 의 contest.json)를 '<대회> 제출하기'로. 메모의 할 일·사람 몫을 함께.
  - 주식: core/planner_signals.py 가 만든 data/planner_signals.json — 보유 매도/재검토, 관심종목 타점, 코어 리밸런싱.
자동 항목은 '확인함'(또는 대회는 '제출 완료')으로 지운다. 같은 시그널이 새 날짜로 다시 나오면 다시 보인다.
'이번 주'는 내일부터 7일 안(KST) — 주말에도 다음 며칠이 보이게 달력 주 대신 굴러가는 7일을 쓴다. 반복 할 일은 완료하면 다음 날짜로 넘어간다.
Notion 바로가기 주소도 같은 파일에 저장한다(관제 센터 개요의 Notion 슬롯이 읽는다).
이 모듈은 주문·전략 엔진과 무관하다.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from core.contests import KST

STATE_PATH = Path(os.environ.get("QUANT_PLANNER_FILE",
                                 Path(__file__).resolve().parent.parent / "data" / "planner.json"))
AREAS = ("AI 대회", "프로젝트", "주식", "기타")
REPEATS = {"": "반복 없음", "daily": "매일", "weekdays": "평일마다", "weekly": "매주", "monthly": "매달"}
DEFAULT_NOTION_URL = "https://www.notion.so/"
DONE_KEEP_DAYS = 14  # 완료 목록에 보여 줄 기간
WEEK_DAYS = 7
CONTEST_STALE_DAYS = 3  # 마감이 이만큼 지난 대회는 끝난 것으로 보고 숨긴다(상태를 안 바꿨어도)


class PlannerError(ValueError):
    pass


@dataclass
class Task:
    id: str
    title: str
    area: str = "기타"
    due: str = ""          # YYYY-MM-DD (KST). 비어 있으면 '언젠가'
    project: str = ""      # 대회 폴더 이름·저장소 이름·종목 등 자유 꼬리표
    link: str = ""         # Notion 페이지·대회 페이지 등
    note: str = ""
    repeat: str = ""       # REPEATS 키
    done: bool = False
    done_at: str = ""
    created_at: str = ""
    key: str = ""          # 세션이 기록한 할 일의 중복 방지 키(예: arbiter-hacks-v1:demo-video). plan add/done 이 쓴다
    origin: str = ""       # 기록한 곳(예: claude:arbiter-hacks-v1, codex:Quant). 화면에서 직접 쓴 것은 빈 값
    source: str = "task"   # task | contest | signal (자동 항목은 읽기 전용)
    kind: str = ""         # signal 의 종류: sell | review | signal | rebalance

    def due_date(self) -> Optional[date]:
        try:
            return date.fromisoformat(self.due) if self.due else None
        except ValueError:
            return None

    def days_left(self, today: date) -> Optional[int]:
        d = self.due_date()
        return None if d is None else (d - today).days

    def to_json(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "title", "area", "due", "project", "link", "note", "repeat",
                                              "done", "done_at", "created_at", "key", "origin")}


@dataclass
class Buckets:
    overdue: list[Task] = field(default_factory=list)
    today: list[Task] = field(default_factory=list)
    week: list[Task] = field(default_factory=list)     # 내일 ~ 7일 안
    later: list[Task] = field(default_factory=list)
    someday: list[Task] = field(default_factory=list)  # 마감 없음
    done: list[Task] = field(default_factory=list)


def today_kst(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(KST)).astimezone(KST).date()


def week_end(today: date) -> date:
    return today + timedelta(days=WEEK_DAYS)


# ---------------------------------------------------------------- 저장
def _load_raw(path: Optional[Path] = None) -> dict:
    path = path or STATE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_raw(data: dict, path: Optional[Path] = None) -> None:
    path = path or STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def list_tasks(path: Optional[Path] = None) -> list[Task]:
    known = set(Task.__dataclass_fields__) - {"source", "kind"}
    out = []
    for item in _load_raw(path).get("tasks", []):
        if isinstance(item, dict) and item.get("id") and item.get("title"):
            out.append(Task(**{k: v for k, v in item.items() if k in known}))
    return out


def _write_tasks(tasks: list[Task], path: Optional[Path] = None) -> None:
    data = _load_raw(path)
    data["tasks"] = [t.to_json() for t in tasks]
    _save_raw(data, path)


def notion_url(path: Optional[Path] = None) -> str:
    url = str(_load_raw(path).get("notion_url") or "").strip()
    return url if url.startswith("https://") else DEFAULT_NOTION_URL


def set_notion_url(url: str, path: Optional[Path] = None) -> None:
    url = (url or "").strip()
    if url and not url.startswith("https://"):
        raise PlannerError("Notion 주소는 https:// 로 시작해야 합니다.")
    data = _load_raw(path)
    data["notion_url"] = url
    _save_raw(data, path)


# ---------------------------------------------------------------- 입력 검증
def parse_due(text: str, today: date) -> str:
    """'2026-11-20', '오늘', '내일', '+3'(3일 뒤) 를 YYYY-MM-DD 로. 빈 값은 그대로."""
    text = (text or "").strip()
    if not text:
        return ""
    if text in ("오늘", "today"):
        return today.isoformat()
    if text in ("내일", "tomorrow"):
        return (today + timedelta(days=1)).isoformat()
    if text.startswith("+") and text[1:].isdigit():
        return (today + timedelta(days=int(text[1:]))).isoformat()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise PlannerError("마감은 2026-11-20 · 오늘 · 내일 · +3 같은 형식으로 적어 주세요.") from None


def _validate(title: str, area: str, link: str, repeat: str, due: str) -> None:
    errs = []
    if not title.strip() or len(title) > 200:
        errs.append("할 일 제목을 1~200자로 적어 주세요.")
    if area not in AREAS:
        errs.append("분야를 목록에서 골라 주세요.")
    if link and not link.startswith(("https://", "http://", "/")):
        errs.append("링크는 https:// 로 시작해야 합니다.")
    if repeat not in REPEATS:
        errs.append("반복 설정이 올바르지 않습니다.")
    if repeat and not due:
        errs.append("반복 할 일은 첫 마감 날짜가 필요합니다.")
    if errs:
        raise PlannerError(" ".join(errs))


# ---------------------------------------------------------------- 변경
def add_task(title: str, *, area: str = "기타", due: str = "", project: str = "", link: str = "", note: str = "",
             repeat: str = "", now: Optional[datetime] = None, path: Optional[Path] = None) -> Task:
    today = today_kst(now)
    due = parse_due(due, today)
    title, project, link, note = title.strip(), project.strip()[:80], link.strip(), note.strip()[:2000]
    _validate(title, area, link, repeat, due)
    task = Task(id=secrets.token_hex(4), title=title, area=area, due=due, project=project, link=link, note=note,
                repeat=repeat, created_at=(now or datetime.now(KST)).astimezone(KST).isoformat(timespec="seconds"))
    tasks = list_tasks(path)
    tasks.append(task)
    _write_tasks(tasks, path)
    return task


KEY_RE_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-_:./")


def _check_key(key: str) -> str:
    key = (key or "").strip().lower()
    if not key or len(key) > 120 or not set(key) <= KEY_RE_CHARS:
        raise PlannerError("key 는 영문 소문자·숫자·-_:./ 로 1~120자여야 합니다.")
    return key


def upsert_by_key(key: str, title: str, *, area: str = "기타", due: str = "", project: str = "", link: str = "",
                  note: str = "", origin: str = "", now: Optional[datetime] = None,
                  path: Optional[Path] = None) -> tuple[Task, bool]:
    """세션이 기록하는 할 일. 같은 key 의 열린 할 일이 있으면 내용을 갱신하고 (Task, False), 없으면 새로 (Task, True)."""
    key = _check_key(key)
    today = today_kst(now)
    due = parse_due(due, today)
    tasks = list_tasks(path)
    task = next((t for t in tasks if t.key == key and not t.done), None)
    if task is None:
        task = add_task(title, area=area, due=due, project=project, link=link, note=note, now=now, path=path)
        tasks = list_tasks(path)
        task = next(t for t in tasks if t.id == task.id)
        created = True
    else:
        created = False
    task.title, task.area, task.project = title.strip(), area, project.strip()[:80]
    task.due, task.link, task.note = due, link.strip(), note.strip()[:2000]
    task.key, task.origin = key, origin.strip()[:80]
    _validate(task.title, task.area, task.link, task.repeat, task.due)
    _write_tasks(tasks, path)
    return task, created


def done_by_key(key: str, *, now: Optional[datetime] = None, path: Optional[Path] = None) -> int:
    """key 가 같은 열린 할 일을 모두 완료로. 완료한 개수(없으면 0 — 오류 아님)."""
    key = _check_key(key)
    now = (now or datetime.now(KST)).astimezone(KST)
    tasks = list_tasks(path)
    n = 0
    for t in tasks:
        if t.key == key and not t.done:
            t.done, t.done_at = True, now.isoformat(timespec="seconds")
            n += 1
    if n:
        _write_tasks(tasks, path)
    return n


def update_task(task_id: str, *, now: Optional[datetime] = None, path: Optional[Path] = None, **fields) -> Task:
    tasks = list_tasks(path)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise PlannerError("없는 할 일입니다.")
    if "due" in fields:
        fields["due"] = parse_due(fields["due"], today_kst(now))
    for k in ("title", "area", "due", "project", "link", "note", "repeat"):
        if k in fields:
            setattr(task, k, str(fields[k]).strip())
    _validate(task.title, task.area, task.link, task.repeat, task.due)
    _write_tasks(tasks, path)
    return task


def next_due(due: date, repeat: str, today: date) -> date:
    """반복 할 일의 다음 마감. 밀린 반복은 오늘 이후 첫 날짜로 건너뛴다."""
    d = due
    while True:
        if repeat == "daily":
            d += timedelta(days=1)
        elif repeat == "weekdays":
            d += timedelta(days=3 if d.weekday() == 4 else 2 if d.weekday() == 5 else 1)
        elif repeat == "weekly":
            d += timedelta(days=7)
        elif repeat == "monthly":
            y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
            for day in (due.day, 30, 29, 28):  # 31일 → 짧은 달은 말일
                try:
                    d = date(y, m, day)
                    break
                except ValueError:
                    continue
        else:
            return d
        if d > today:
            return d


def set_done(task_id: str, done: bool = True, *, now: Optional[datetime] = None,
             path: Optional[Path] = None) -> Task:
    """완료 표시. 반복 할 일은 완료로 남기지 않고 다음 마감으로 넘긴다."""
    now = (now or datetime.now(KST)).astimezone(KST)
    tasks = list_tasks(path)
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise PlannerError("없는 할 일입니다.")
    if done and task.repeat and task.due_date():
        task.due = next_due(task.due_date(), task.repeat, now.date()).isoformat()
        task.done, task.done_at = False, ""
    else:
        task.done = done
        task.done_at = now.isoformat(timespec="seconds") if done else ""
    _write_tasks(tasks, path)
    return task


def delete_task(task_id: str, *, path: Optional[Path] = None) -> None:
    tasks = list_tasks(path)
    kept = [t for t in tasks if t.id != task_id]
    if len(kept) == len(tasks):
        raise PlannerError("없는 할 일입니다.")
    _write_tasks(kept, path)


# ---------------------------------------------------------------- 보기
SIGNALS_MAX_AGE = 30 * 60  # 초. 이보다 오래된 시그널 파일은 다시 만든다
_signal_proc = None


def _memo_lines(memo: str) -> str:
    """대회 메모(대회 탐색이 채운 형식)에서 '할 일'·'사람 몫' 줄만 뽑는다. 없으면 첫 줄."""
    lines = [ln.strip() for ln in (memo or "").splitlines() if ln.strip()]
    picked = [ln for ln in lines if ln.startswith(("할 일", "사람 몫"))]
    if not picked:
        for part in (memo or "").split(" / "):  # 'A / 할 일: B / 사람 몫: C' 한 줄 형식
            part = part.strip()
            if part.startswith(("할 일", "사람 몫")):
                picked.append(part)
    return " · ".join(picked) if picked else (lines[0] if lines else "")


def contest_tasks(now: Optional[datetime] = None) -> list[Task]:
    """아직 제출하지 않은 AI 대회를 '제출하기' 할 일로. 대회 폴더를 읽지 못해도 빈 목록."""
    today = today_kst(now)
    try:
        from core import contests as ct

        items = ct.list_contests()
    except Exception:  # noqa: BLE001 - 할 일 화면은 대회 폴더 문제와 무관하게 떠야 한다
        return []
    out = []
    for c in items:
        dl = c.deadline_dt()
        if dl is None or c.status in ("제출 완료", "종료") or (today - dl.date()).days > CONTEST_STALE_DAYS:
            continue
        clock = f" · 마감 {dl:%H:%M}" if "T" in c.deadline else ""
        state = "아직 시작 전" if c.status == "준비" else "제출 안 함"
        out.append(Task(id=f"contest:{c.slug}", title=f"{c.title} 제출하기{clock}", area="AI 대회",
                        due=dl.date().isoformat(), project=f"{c.slug} · {state}", link=f"/contests/{c.slug}",
                        note=_memo_lines(c.memo), source="contest"))
    return out


def signal_tasks(path: Optional[Path] = None) -> list[Task]:
    """data/planner_signals.json 의 주식 시그널. 파일이 없거나 깨졌으면 빈 목록."""
    from core import planner_signals as ps

    try:
        data = json.loads((path or ps.SIGNALS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for it in data.get("items", []):
        if isinstance(it, dict) and it.get("id") and it.get("title"):
            out.append(Task(id=str(it["id"]), title=str(it["title"]), area="주식", due=str(it.get("due") or ""),
                            project=str(it.get("project") or ""), link=str(it.get("link") or ""),
                            note=str(it.get("note") or ""), source="signal", kind=str(it.get("kind") or "")))
    return out


def signals_status(path: Optional[Path] = None) -> dict:
    """{'generated_at': str|None, 'age_min': int|None, 'errors': [...], 'running': bool}"""
    from core import planner_signals as ps

    path = path or ps.SIGNALS_PATH
    running = _signal_proc is not None and _signal_proc.poll() is None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = int((datetime.now().timestamp() - path.stat().st_mtime) // 60)
        return {"generated_at": data.get("generated_at"), "age_min": age, "errors": data.get("errors") or [],
                "running": running}
    except (OSError, ValueError):
        return {"generated_at": None, "age_min": None, "errors": [], "running": running}


def refresh_signals(force: bool = False) -> bool:
    """시그널 파일이 오래됐으면 낮은 우선순위 별도 프로세스로 다시 만든다(기다리지 않음). 띄웠으면 True."""
    global _signal_proc
    import subprocess
    import sys
    import time

    from core import planner_signals as ps

    if _signal_proc is not None and _signal_proc.poll() is None:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):  # 테스트가 개요를 그릴 때 실제 엔진 계산을 띄우지 않는다
        return False
    try:
        age = time.time() - ps.SIGNALS_PATH.stat().st_mtime
    except OSError:
        age = None
    if not force and age is not None and age < SIGNALS_MAX_AGE:
        return False
    _signal_proc = subprocess.Popen(["nice", "-n", "19", sys.executable, "-m", "core.planner_signals"],
                                    cwd=str(Path(__file__).resolve().parent.parent), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def dismissed(path: Optional[Path] = None) -> dict:
    d = _load_raw(path).get("dismissed")
    return d if isinstance(d, dict) else {}


def dismiss(item_id: str, *, now: Optional[datetime] = None, path: Optional[Path] = None) -> None:
    """자동 항목(시그널)을 '확인함'으로 숨긴다. 60일 넘은 기록은 정리한다."""
    if not item_id.startswith("sig:") or len(item_id) > 200:
        raise PlannerError("숨길 수 없는 항목입니다.")
    today = today_kst(now)
    data = _load_raw(path)
    kept = {k: v for k, v in (data.get("dismissed") or {}).items()
            if isinstance(v, str) and v >= (today - timedelta(days=60)).isoformat()}
    kept[item_id] = today.isoformat()
    data["dismissed"] = kept
    _save_raw(data, path)


def mark_contest_submitted(slug: str) -> None:
    from core import contests as ct

    try:
        ct.update(slug, status="제출 완료")
    except Exception as exc:  # noqa: BLE001 - 대회 모듈 오류를 화면 문구로
        raise PlannerError(f"대회 상태를 바꾸지 못했습니다: {exc}") from None


def _sort_key(t: Task) -> tuple:
    return (t.due or "9999-99-99", AREAS.index(t.area) if t.area in AREAS else 99, t.created_at)


def buckets(tasks: Optional[list[Task]] = None, *, now: Optional[datetime] = None,
            include_contests: bool = True, include_signals: bool = True) -> Buckets:
    today = today_kst(now)
    end = week_end(today)
    items = list_tasks() if tasks is None else list(tasks)
    if include_contests:
        items += contest_tasks(now)
    if include_signals:
        hidden = dismissed() if tasks is None else {}
        items += [t for t in signal_tasks() if t.id not in hidden]
    b = Buckets()
    for t in sorted(items, key=_sort_key):
        d = t.due_date()
        if t.done:
            try:
                fresh = (today - datetime.fromisoformat(t.done_at).astimezone(KST).date()).days <= DONE_KEEP_DAYS
            except ValueError:
                fresh = True
            if fresh:
                b.done.append(t)
        elif d is None:
            b.someday.append(t)
        elif d < today:
            b.overdue.append(t)
        elif d == today:
            b.today.append(t)
        elif d <= end:
            b.week.append(t)
        else:
            b.later.append(t)
    b.done.sort(key=lambda t: t.done_at, reverse=True)
    return b
