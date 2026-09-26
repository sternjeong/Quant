"""엔진 카드(백그라운드 서비스)를 눌렀을 때 "지금 무슨 잡을 돌리고 있는지"를 보여주고 켜고 끄게 한다.

배경: 엔진 상태 페이지는 systemd 유닛 상태 한 줄과 "이 엔진은 별도 웹 UI 없이 백그라운드로 동작합니다"라는
막다른 문장뿐이었다. 정작 그 엔진이 무슨 잡을 몇 개 돌리는지, 지금 정상인지, 끄려면 어떻게 하는지는 화면에서
알 수 없어서 텔레그램 `/processes` 로만 가능했다(사용자는 폰으로 운영한다 — 웹에서도 같은 걸 할 수 있어야 한다).

여기서 하는 일:
  - 엔진 → 그 엔진이 실제로 돌리는 잡 목록을 잇는다(스케줄러는 core.job_schedule의 29개 전부).
  - 잡마다 예정 시각(한국시간), 지금 상태(core.job_health), 켜짐/꺼짐을 한 줄로 보여준다.
  - 켜기/끄기 버튼을 둔다. **주문을 내는 잡**(places_orders)은 텔레그램과 똑같이 한 번 더 확인을 받는다 —
    웹 클릭 한 번으로 실계좌성 주문 잡이 켜지면 안 된다.

상태 조회(DB·systemd)는 실패해도 페이지 전체가 죽지 않게 각각 막아 둔다.
"""

from __future__ import annotations

import html
import subprocess
from typing import Any

# 엔진 슬롯 id → 그 엔진이 돌리는 잡의 출처.
# 지금은 스케줄러만 토글 가능한 잡을 갖는다. 나머지 엔진은 잡 목록이 아니라 무슨 일을 하는지 설명으로 보여준다.
SCHEDULER_SLOT_ID = "scheduler"

CATEGORY_LABELS = {
    "alert": "알림",
    "research": "연구·기록",
    "maintenance": "유지보수",
}

STATE_LABELS = {
    "ok": ("정상", "ok"),
    "pending": ("실행 예정", "warn"),
    "error": ("오류", "bad"),
    "missed": ("실행 놓침", "bad"),
    "overdue": ("기록 없음", "bad"),
    "disabled": ("꺼짐", "off"),
    "no-history": ("이력 없음", "unknown"),
}

_WEEKDAY_KO = {"mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}


def describe_cron(cron: dict) -> str:
    """core.job_schedule의 cron 인자를 사람이 읽는 한 줄로. 시간대는 표기해 준다(KST/ET 혼재)."""
    timezone = str(cron.get("timezone", ""))
    zone = "KST" if "Seoul" in timezone else ("ET" if "New_York" in timezone else timezone)
    hour, minute = cron.get("hour"), cron.get("minute")
    clock = f"{int(hour):02d}:{int(minute):02d}" if hour is not None and minute is not None else "?"
    day_of_week = cron.get("day_of_week")
    if not day_of_week:
        return f"매일 {clock} {zone}"
    if day_of_week == "mon-fri":
        return f"평일 {clock} {zone}"
    days = "·".join(_WEEKDAY_KO.get(part.strip().lower(), part) for part in str(day_of_week).split(","))
    return f"매주 {days} {clock} {zone}"


def _job_ids_by_process_key() -> dict[str, dict]:
    """process_key → {job_id, cron}. 스케줄 표를 읽지 못하면 빈 dict."""
    try:
        from core.job_schedule import SCHEDULED_JOBS
    except Exception:  # noqa: BLE001 — 표를 못 읽어도 페이지는 떠야 한다
        return {}
    return {job.process_key: {"job_id": job.job_id, "cron": job.cron} for job in SCHEDULED_JOBS}


def _health_by_job_id() -> dict[str, dict]:
    """job_id → 판정 결과. DB를 못 읽으면 빈 dict(상태는 '확인 불가'로 표시된다)."""
    try:
        from core.job_health import compute_job_health

        return {entry["job_id"]: entry for entry in compute_job_health()["jobs"]}
    except Exception:  # noqa: BLE001
        return {}


def _places_orders(key: str) -> bool:
    try:
        from core.process_registry import PROCESS_REGISTRY

        return bool(PROCESS_REGISTRY.get(key, {}).get("places_orders"))
    except Exception:  # noqa: BLE001
        return False


def collect_processes() -> list[dict[str, Any]]:
    """스케줄러가 돌리는 잡 전체를 화면에 필요한 형태로 모은다(레지스트리 정의 순서 유지)."""
    try:
        from core.process_registry import list_processes

        processes = list_processes()
    except Exception:  # noqa: BLE001
        return []

    schedule = _job_ids_by_process_key()
    health = _health_by_job_id()
    rows = []
    for process in processes:
        key = process["key"]
        entry = schedule.get(key, {})
        job_id = entry.get("job_id")
        state = (health.get(job_id) or {}).get("state") if job_id else None
        if not process["enabled"]:
            state = "disabled"  # 꺼둔 잡은 "기록 없음"이 아니라 "꺼짐"으로 보이는 게 정직하다
        rows.append({
            **process,
            "job_id": job_id,
            "schedule": describe_cron(entry["cron"]) if entry.get("cron") else "예약 없음",
            "state": state,
            "last_run": (health.get(job_id) or {}).get("last_recorded_at") if job_id else None,
            "places_orders": _places_orders(key),
        })
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "enabled": sum(1 for row in rows if row["enabled"]),
        "disabled": sum(1 for row in rows if not row["enabled"]),
        "problem": sum(1 for row in rows if row["state"] in ("error", "missed", "overdue")),
    }


def apply_toggle(key: str, enabled: bool, confirmed: bool = False, actor: str = "hub") -> tuple[bool, str]:
    """(적용됨, 사람이 읽는 결과). 주문을 내는 잡을 켤 때는 confirmed가 True여야 한다(텔레그램과 같은 규칙)."""
    try:
        from core.process_registry import PROCESS_REGISTRY, set_enabled
    except Exception as exc:  # noqa: BLE001
        return False, f"프로세스 목록을 불러오지 못했습니다: {type(exc).__name__}"
    if key not in PROCESS_REGISTRY:
        return False, "알 수 없는 잡입니다."
    if enabled and PROCESS_REGISTRY[key].get("places_orders") and not confirmed:
        return False, "확인이 필요합니다."
    set_enabled(key, enabled, actor)
    return True, f'{PROCESS_REGISTRY[key]["label"]} — {"켜짐" if enabled else "꺼짐"}'


# ---- 렌더링 -------------------------------------------------------------------------------------

def _pill(text: str, tone: str) -> str:
    colors = {
        "ok": ("#15321f", "#57d38c"), "warn": ("#3a2f12", "#e8b339"), "bad": ("#3a1b1b", "#ef6b6b"),
        "off": ("#22262c", "#8b939e"), "unknown": ("#22262c", "#8b939e"),
    }
    background, color = colors.get(tone, colors["unknown"])
    return (f'<span style="background:{background};color:{color};border-radius:999px;'
            f'padding:.12rem .55rem;font-size:.72rem;white-space:nowrap">{html.escape(text)}</span>')


def _state_pill(state: str | None) -> str:
    label, tone = STATE_LABELS.get(state or "", ("확인 불가", "unknown"))
    return _pill(label, tone)


def _toggle_button(row: dict[str, Any]) -> str:
    """켜짐이면 끄기 버튼, 꺼짐이면 켜기 버튼. 주문 잡을 켜는 경우에만 확인 화면을 거친다."""
    key = html.escape(row["key"])
    if row["enabled"]:
        label, color, action, extra = "끄기", "#3a1b1b", "/processes/toggle", ""
    elif row["places_orders"]:
        label, color, action, extra = "켜기…", "#2c3a52", "/processes/confirm", ""
    else:
        label, color, action, extra = "켜기", "#1d3a2a", "/processes/toggle", ""
    value = "0" if row["enabled"] else "1"
    return (f'<form method="post" action="{action}" style="margin:0">'
            f'<input type="hidden" name="key" value="{key}">'
            f'<input type="hidden" name="enabled" value="{value}">{extra}'
            f'<button type="submit" style="background:{color};color:#e6e8ea;border:1px solid #333a44;'
            f'border-radius:8px;padding:.3rem .7rem;font-size:.78rem;cursor:pointer">{label}</button></form>')


def _process_row(row: dict[str, Any]) -> str:
    order_mark = ' <span title="주문을 내는 잡">💸</span>' if row["places_orders"] else ""
    return (
        '<tr style="border-top:1px solid #23272e">'
        f'<td style="padding:.5rem .4rem"><div style="font-size:.88rem">{html.escape(row["label"])}{order_mark}</div>'
        f'<div style="color:#7d848d;font-size:.74rem;margin-top:.15rem">{html.escape(row["description"])}</div></td>'
        f'<td style="padding:.5rem .4rem;color:#9aa0a8;font-size:.76rem;white-space:nowrap">{html.escape(row["schedule"])}</td>'
        f'<td style="padding:.5rem .4rem">{_state_pill(row["state"])}</td>'
        f'<td style="padding:.5rem .4rem;text-align:right">{_toggle_button(row)}</td>'
        '</tr>'
    )


def render_process_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p style="color:#8b939e">잡 목록을 불러오지 못했습니다.</p>'
    counts = summarize(rows)
    parts = [
        f'<p style="color:#9aa0a8;font-size:.85rem">자동 잡 {counts["total"]}개 — '
        f'켜짐 {counts["enabled"]}, 꺼짐 {counts["disabled"]}'
        + (f', <b style="color:#ef6b6b">확인 필요 {counts["problem"]}</b>' if counts["problem"] else '')
        + '</p>'
    ]
    for category, label in CATEGORY_LABELS.items():
        group = [row for row in rows if row["category"] == category]
        if not group:
            continue
        parts.append(f'<h2 style="margin:1.2rem 0 .3rem;font-size:1rem">{label} <span style="color:#7d848d;'
                     f'font-weight:400;font-size:.8rem">{len(group)}개</span></h2>')
        parts.append('<table style="width:100%;border-collapse:collapse">'
                     + ''.join(_process_row(row) for row in group) + '</table>')
    parts.append('<p style="margin-top:1.2rem;color:#5b6472;font-size:.76rem">'
                 '끄면 그 잡은 다음 예정 시각에 "건너뜀"으로 돌고, 다시 켜면 그다음 예정 시각부터 재개합니다. '
                 '같은 목록을 텔레그램 <code>/processes</code> 로도 켜고 끌 수 있습니다.</p>')
    return ''.join(parts)


def render_confirm_body(key: str) -> str:
    """주문을 내는 잡을 켜기 전에 한 번 더 묻는 화면(텔레그램의 확인 단계와 같은 역할)."""
    try:
        from core.process_registry import PROCESS_REGISTRY

        meta = PROCESS_REGISTRY.get(key)
    except Exception:  # noqa: BLE001
        meta = None
    if meta is None:
        return '<p style="color:#ef6b6b">알 수 없는 잡입니다.</p><p><a class="back" href="/status/scheduler">돌아가기</a></p>'
    return (
        f'<h1>{html.escape(meta["label"])} 켜기</h1>'
        f'<p class="subtitle">{html.escape(meta["description"])}</p>'
        '<p style="background:#3a2f12;border:1px solid #5a4a1e;border-radius:8px;padding:.7rem .9rem;'
        'color:#e8b339;font-size:.85rem;margin-top:1rem">'
        '이 잡은 <b>주문을 냅니다</b>. 켜면 예정 시각마다 자동으로 주문이 제출됩니다. 정말 켤까요?</p>'
        '<div style="display:flex;gap:.6rem;margin-top:1rem">'
        '<form method="post" action="/processes/toggle" style="margin:0">'
        f'<input type="hidden" name="key" value="{html.escape(key)}">'
        '<input type="hidden" name="enabled" value="1">'
        '<input type="hidden" name="confirm" value="1">'
        '<button type="submit" style="background:#7a2f2f;color:#fff;border:0;border-radius:8px;'
        'padding:.55rem 1.1rem;font-size:.85rem;cursor:pointer">네, 켭니다</button></form>'
        '<a href="/status/scheduler" style="background:#22262c;color:#e6e8ea;border:1px solid #333a44;'
        'border-radius:8px;padding:.55rem 1.1rem;font-size:.85rem;text-decoration:none">취소</a>'
        '</div>'
    )


def render_engine_body(slot_id: str) -> str:
    """엔진 상태 페이지의 본문. 스케줄러는 잡 목록, 나머지는 무슨 일을 하는지 + 최근 실행."""
    if slot_id == SCHEDULER_SLOT_ID:
        return render_process_table(collect_processes())
    return _render_non_scheduler_body(slot_id)


NON_SCHEDULER_ENGINES = {
    "codex-telegram": {
        "does": "텔레그램으로 받은 지시를 큐에 넣고 Claude/Codex를 VM에서 실행합니다. "
                "메모(/note)·기록(/progress)·조회(/cat, /log, /repo) 같은 즉시 명령도 이 서비스가 처리합니다.",
        "control": "이 엔진 자체는 항상 떠 있어야 지시를 받을 수 있어서 화면에서 끄지 않습니다. "
                   "작업 대기열은 텔레그램 <code>/queue</code>, 최근 결과는 <code>/status</code>로 봅니다.",
    },
    "vm-health": {
        "does": "디스크·메모리 사용률을 주기적으로 확인하고 임계값을 넘으면 텔레그램으로 알립니다.",
        "control": "systemd 타이머로 돌며 켜고 끌 설정은 없습니다. 지금 수치는 관제 센터의 <b>운영 상태</b>에서 봅니다.",
    },
    "experiment-supervisor": {
        "does": "2주 전략 검증 실험을 무인으로 진행하고 매일 HTML 리포트를 보냅니다.",
        "control": "켜고 끄기는 텔레그램 <code>/experiment pause</code> · <code>/experiment resume</code>로 합니다.",
    },
}


def _render_non_scheduler_body(slot_id: str) -> str:
    info = NON_SCHEDULER_ENGINES.get(slot_id)
    if info is None:
        return ('<p style="color:#8b939e;font-size:.85rem">이 엔진이 돌리는 자동 잡 목록은 아직 화면에 연결돼 있지 않습니다. '
                '자동 잡 전체는 <a href="/status/scheduler">백그라운드 스케줄러</a>에서 봅니다.</p>')
    timers = _recent_timer_lines(slot_id)
    return (
        f'<p style="font-size:.88rem;line-height:1.6">{info["does"]}</p>'
        f'<p style="margin-top:.8rem;color:#9aa0a8;font-size:.82rem">{info["control"]}</p>'
        + (f'<p style="margin-top:.8rem;color:#7d848d;font-size:.78rem">{timers}</p>' if timers else '')
        + '<p style="margin-top:1.2rem;color:#5b6472;font-size:.76rem">'
          '자동 잡 29개의 켜고 끄기는 <a href="/status/scheduler">백그라운드 스케줄러</a>에서 합니다.</p>'
    )


_TIMER_UNITS = {"vm-health": "quant-vm-health.timer"}


def _recent_timer_lines(slot_id: str) -> str:
    unit = _TIMER_UNITS.get(slot_id)
    if not unit:
        return ""
    try:
        result = subprocess.run(
            ["systemctl", "show", unit, "--property=LastTriggerUSec", "--property=NextElapseUSecRealtime", "--value"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not values:
        return ""
    last = html.escape(values[0])
    nxt = html.escape(values[1]) if len(values) > 1 else "?"
    return f"마지막 실행: {last}<br>다음 실행: {nxt}"
