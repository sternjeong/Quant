"""사용량 한도로 멈춘 Claude Code / Codex 대화 세션을 한도가 풀린 뒤 자동으로 '이어서 진행'시킨다.

대상은 사람이 VM 에서 대화형으로 쓰던 세션이다(VS Code 확장·code-server·터미널). 텔레그램 러너
(deploy/codex_telegram)와 야간 에이전트(core/agent_batch.py)는 `--no-session-persistence`·`--ephemeral` 로
세션 파일을 남기지 않고 자체 재시도가 있으므로 여기서 다루지 않는다(파일이 없으니 발견도 안 된다).

동작(quant-session-resume.timer 가 5분마다 root 로 1회 실행):
1. VM 사용자 계정 목록에서 Claude/Codex 세션 기록이 있는 홈을 찾아 읽는다.
   - Claude: ~/.claude/projects/*/<세션ID>.jsonl. 마지막 대화 기록이 `isApiErrorMessage` + `error == "rate_limit"`
     ("You've hit your session limit · resets 11:20am (UTC)") 이면 한도로 멈춘 세션이다.
   - Codex: ~/.codex/sessions/**/rollout-*.jsonl (하위 에이전트 제외). 마지막 턴에 한도 오류 이벤트가 있거나
     rate_limits 스냅샷이 한도 도달(rate_limit_reached_type 또는 100%)이고 그 턴이 정상 답변으로 끝나지 않았으면 멈춘 세션이다.
2. 초기화 시각(Claude 는 오류 문구, Codex 는 resets_at)이 지나면 그 계정 권한으로 같은 세션을 이어서 실행한다:
   `claude -p --resume <ID>` / `codex exec resume <ID>` — systemd-run 임시 유닛이라 VM 재부팅·이 스크립트와 무관하게
   돌고 journalctl -u <유닛> 으로 기록을 본다. 같은 세션 파일에 이어 쓰므로 VS Code 에서 그 세션을 다시 열면 이어진 내용이 보인다.
3. 다음 회차에 결과를 판정한다: 마지막 기록이 더는 한도 오류가 아니면 '이어서 진행됨', 다시 한도에 걸렸으면 다음 초기화를 기다린다.

켜고 끄기: data/session_resume/toggles.json(관제 센터 /session-resume 화면이 쓴다). 전체 스위치와 세션별 스위치가 있고
기록이 없으면 둘 다 켜짐이 기본이다. 상태: data/session_resume/state.json(이 스크립트만 쓴다).

권한: 원래 세션의 권한 모드를 그대로 쓴다(Claude permissionMode, Codex sandbox). 더 넓히지 않는다. 비대화 실행이라
승인이 필요한 동작은 거절된 채 진행된다(Codex approval=never, Claude manual 모드는 승인 필요한 도구가 거부됨).

stdlib 만 쓴다(시스템 python3 로 root 가 실행 — 프로젝트 venv 불필요).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = PROJECT_ROOT / "data" / "session_resume"
ALERT_SCRIPT = PROJECT_ROOT / "deploy" / "send_telegram_alert.sh"

DEFAULT_CONFIG: dict[str, Any] = {
    "accounts": None,  # None: pwd 의 모든 로컬 계정 중 세션 기록이 있는 홈. 목록 지정 시 해당 계정만.
    "claude_bin": None,  # 자동 탐색. 문자열 또는 {사용자: 경로}로 고정 가능.
    "codex_bin": {},  # {"사용자": "경로"} — 없으면 자동 탐색
    "scan_days": 8,  # 이보다 오래 손대지 않은 세션 파일은 읽지 않는다
    "resume_window_hours": 36,  # 초기화(또는 멈춤) 후 이 시간이 지나도록 못 이었으면 자동 재개하지 않는다(오래된 세션을 갑자기 깨우지 않음)
    "reset_margin_minutes": 3,  # 초기화 시각 직후 바로 치지 않고 조금 기다린다
    "unknown_reset_wait_minutes": 30,  # 초기화 시각을 못 읽었을 때 멈춘 뒤 이만큼 기다렸다 시도
    "retry_after_failure_minutes": 30,
    "max_attempts": 4,  # 같은 멈춤에서 실패·재차 한도를 합쳐 이만큼 시도하면 포기
    "max_concurrent": 2,
    "run_timeout_hours": 6,
    "history_keep": 60,
    "notify": True,
}

RESUME_PROMPT = (
    "[자동 재개] 직전 작업이 사용량 한도로 중단되었고, 한도가 초기화되어 VM 이 이 세션을 자동으로 이어서 실행했습니다. "
    "사용자는 지금 자리에 없습니다. 중단 직전까지의 대화와 작업 상태(git status 등)를 확인하고, 하던 작업을 이어서 끝까지 진행하세요. "
    "이미 끝난 작업이면 결과만 짧게 정리하세요. push·배포·삭제처럼 되돌리기 어렵거나 외부에 공개되는 작업은 원래 대화에서 "
    "사용자가 이미 허락한 범위 안에서만 하고, 그 밖의 결정이 필요하면 하지 말고 무엇이 필요한지 마지막에 적으세요."
)

CODEX_LIMIT = re.compile(r"usage_limit_(?:reached|exceeded)|usage limit|rate_limit_exceeded|hit your usage limit|\b429\b", re.I)
_CLAUDE_RESET = re.compile(
    r"resets\s+(?:(?P<mon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2}),\s*)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)\s*(?:\((?P<tz>[^)]+)\))?",
    re.I)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
CLAUDE_MODES = {"acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan"}


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    _match_owner(path)


def _match_owner(path: Path) -> None:
    """root 로 돌아도 상태 폴더·파일 소유자를 data/ 주인(quant)에 맞춘다 — 허브(quant)가 읽고 토글 파일을 쓸 수 있게."""
    if os.geteuid() != 0:
        return
    try:
        st = STATE_DIR.parent.stat()
        for target in (STATE_DIR, path):
            os.chown(target, st.st_uid, st.st_gid)
    except OSError:
        pass


def _iter_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _short(text: Any, limit: int = 80) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------
def parse_claude_reset(text: str, stopped_at: datetime) -> Optional[datetime]:
    """'resets 11:20am (UTC)' / 'resets Sep 24, 1am (UTC)' → 초기화 시각(UTC). 못 읽으면 None."""
    m = _CLAUDE_RESET.search(text or "")
    if not m:
        return None
    tzname = (m.group("tz") or "UTC").strip()
    try:
        from zoneinfo import ZoneInfo

        tz = timezone.utc if tzname.upper() == "UTC" else ZoneInfo(tzname)
    except Exception:  # noqa: BLE001 - 모르는 표기는 UTC 로 본다
        tz = timezone.utc
    hour = int(m.group("h")) % 12 + (12 if m.group("ap").lower() == "pm" else 0)
    minute = int(m.group("m") or 0)
    base = stopped_at.astimezone(tz)
    if m.group("mon"):
        month = _MONTHS.get(m.group("mon").lower())
        if not month:
            return None
        cand = base.replace(month=month, day=int(m.group("day")), hour=hour, minute=minute, second=0, microsecond=0)
        if cand < base - timedelta(days=1):
            cand = cand.replace(year=cand.year + 1)
    else:
        cand = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= base - timedelta(minutes=1):
            cand += timedelta(days=1)
    return cand.astimezone(timezone.utc)


def _claude_text(message: Any) -> str:
    content = (message or {}).get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def scan_claude(path: Path) -> Optional[dict]:
    """한도로 멈춘 Claude 세션이면 정보 dict, 아니면 None."""
    last = None
    cwd = mode = title = first_user = None
    session_id = path.stem
    for rec in _iter_jsonl(path):
        t = rec.get("type")
        if t == "ai-title" and rec.get("aiTitle"):
            title = rec["aiTitle"]
        elif t == "summary" and rec.get("summary") and not title:
            title = rec["summary"]
        if t not in ("user", "assistant") or rec.get("isSidechain"):
            continue
        cwd = rec.get("cwd") or cwd
        mode = rec.get("permissionMode") or mode
        if t == "user" and first_user is None and not rec.get("isMeta"):
            txt = _claude_text(rec.get("message"))
            if txt and not txt.startswith("<"):
                first_user = txt
        last = rec
    if not last or last.get("type") != "assistant" or not last.get("isApiErrorMessage") or last.get("error") != "rate_limit":
        return None
    stopped = _parse_ts(last.get("timestamp"))
    if stopped is None:
        return None
    text = _claude_text(last.get("message"))
    return {
        "backend": "claude", "session_id": session_id, "cwd": cwd, "title": _short(title or first_user or session_id),
        "stopped_at": stopped, "reset_at": parse_claude_reset(text, stopped), "reason": _short(text, 120),
        "mode": mode, "transcript": str(path),
    }


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------
def _codex_limit_reset(rate_limits: Any) -> tuple[bool, Optional[datetime]]:
    if not isinstance(rate_limits, dict):
        return False, None
    reached = bool(rate_limits.get("rate_limit_reached_type"))
    resets: list[float] = []
    for key in ("primary", "secondary"):
        w = rate_limits.get(key)
        if isinstance(w, dict) and float(w.get("used_percent") or 0) >= 100:
            reached = True
            if w.get("resets_at"):
                resets.append(float(w["resets_at"]))
    if reached and not resets:
        for key in ("primary", "secondary"):
            w = rate_limits.get(key)
            if isinstance(w, dict) and w.get("resets_at"):
                resets.append(float(w["resets_at"]))
    reset = datetime.fromtimestamp(max(resets), tz=timezone.utc) if resets else None
    return reached, reset


def scan_codex(path: Path) -> Optional[dict]:
    """한도로 멈춘 Codex 최상위 세션이면 정보 dict, 아니면 None.

    판정: 마지막 task_started 이후(마지막 턴)에 한도 오류 이벤트가 있거나 rate_limits 스냅샷이 한도 도달이고,
    그 턴이 답변(last_agent_message)으로 끝나지 않았으며 사용자가 직접 멈추지(turn_aborted) 않았을 것.
    """
    meta = None
    cwd = title = None
    sandbox = model = effort = None
    turn: dict[str, Any] = {}
    for rec in _iter_jsonl(path):
        rtype = rec.get("type")
        p = rec.get("payload") or {}
        ptype = p.get("type") if isinstance(p, dict) else None
        if rtype == "session_meta" and meta is None:
            meta = p
            cwd = p.get("cwd")
            continue
        if rtype == "turn_context":
            cwd = p.get("cwd") or cwd
            sandbox = p.get("sandbox_policy") or sandbox
            model = p.get("model") or model
            effort = p.get("effort") or effort
            continue
        if rtype != "event_msg":
            continue
        if ptype == "user_message" and title is None:
            title = p.get("message")
        if ptype == "task_started":
            turn = {"started": _parse_ts(rec.get("timestamp")), "limited": False, "reset": None, "evidence_at": None,
                    "answered": False, "aborted": False, "reason": ""}
        elif not turn:
            continue
        elif ptype in ("error", "stream_error") and CODEX_LIMIT.search(json.dumps(p, ensure_ascii=False)):
            turn.update(limited=True, evidence_at=_parse_ts(rec.get("timestamp")), reason=_short(p.get("message"), 120))
        elif ptype == "token_count":
            reached, reset = _codex_limit_reset(p.get("rate_limits"))
            if reached:
                turn.update(limited=True, evidence_at=_parse_ts(rec.get("timestamp")))
                turn["reset"] = reset or turn.get("reset")
                turn["reason"] = turn.get("reason") or "Codex 사용량 한도 도달"
        elif ptype == "task_complete":
            turn["answered"] = bool(p.get("last_agent_message"))
        elif ptype == "turn_aborted":
            turn["aborted"] = True
    if not meta or not isinstance(meta.get("source"), str):  # 하위 에이전트(source 가 dict)는 부모가 이어 간다
        return None
    if not turn or not turn.get("limited") or turn.get("answered") or turn.get("aborted"):
        return None
    stopped = turn.get("evidence_at") or turn.get("started")
    if stopped is None:
        return None
    return {
        "backend": "codex", "session_id": str(meta.get("id")), "cwd": cwd, "title": _short(title or meta.get("id")),
        "stopped_at": stopped, "reset_at": turn.get("reset"), "reason": turn.get("reason") or "Codex 사용량 한도",
        "sandbox": sandbox, "model": model, "effort": effort, "transcript": str(path),
    }


# ---------------------------------------------------------------------------
# 발견
# ---------------------------------------------------------------------------
def _recent_files(pattern: str, cutoff: float) -> list[Path]:
    out = []
    for name in glob.glob(pattern, recursive=True):
        try:
            if os.path.getmtime(name) >= cutoff:
                out.append(Path(name))
        except OSError:
            continue
    return out


def discover_accounts(cfg: dict) -> list[dict[str, str]]:
    """VM의 로컬 사용자 계정을 나열한다. 명시 목록은 테스트·운영 범위 제한용이다."""
    configured = cfg.get("accounts")
    if configured is not None:
        return configured
    accounts = []
    seen = set()
    for entry in pwd.getpwall():
        user, home = entry.pw_name, entry.pw_dir
        if user in seen or not home or not os.path.isdir(home):
            continue
        seen.add(user)
        if (Path(home) / ".claude" / "projects").is_dir() or (Path(home) / ".codex" / "sessions").is_dir():
            accounts.append({"user": user, "home": home})
    return accounts


def discover(cfg: dict, now: datetime) -> list[dict]:
    cutoff = (now - timedelta(days=cfg["scan_days"])).timestamp()
    found: dict[str, dict] = {}
    for acct in discover_accounts(cfg):
        user, home = acct["user"], acct["home"]
        scans = [(scan_claude, f"{home}/.claude/projects/*/*.jsonl"),
                 (scan_codex, f"{home}/.codex/sessions/**/rollout-*.jsonl")]
        for fn, pattern in scans:
            for path in _recent_files(pattern, cutoff):
                info = fn(path)
                if not info:
                    continue
                info.update(user=user, home=home)
                info["key"] = f"{info['backend']}:{user}:{info['session_id']}"
                prev = found.get(info["key"])  # Codex 는 같은 세션이 여러 파일일 수 있다 — 가장 최근 멈춤만
                if prev is None or info["stopped_at"] > prev["stopped_at"]:
                    found[info["key"]] = info
    return list(found.values())


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def codex_bin_for(cfg: dict, user: str, home: str) -> Optional[str]:
    explicit = (cfg.get("codex_bin") or {}).get(user)
    if explicit:
        return explicit
    cands = sorted(glob.glob(f"{home}/.codex/packages/*/releases/*/bin/codex"), key=os.path.getmtime, reverse=True)
    cands += [f"{home}/.local/bin/codex", f"{home}/.npm-global/bin/codex",
              *sorted(glob.glob(f"{home}/.nvm/versions/node/*/bin/codex"), reverse=True),
              f"{home}/.codex-telegram-runtime/node_modules/.bin/codex"]
    which = shutil.which("codex")
    if which:
        cands.append(which)
    return next((c for c in cands if os.access(c, os.X_OK)), None)


def claude_bin_for(cfg: dict, user: str, home: str) -> Optional[str]:
    configured = cfg.get("claude_bin")
    if isinstance(configured, dict):
        configured = configured.get(user)
    if configured:
        return str(configured)
    candidates = [f"{home}/.local/bin/claude", f"{home}/.claude/local/claude",
                  f"{home}/.npm-global/bin/claude", "/usr/local/bin/claude", shutil.which("claude")]
    return next((str(c) for c in candidates if c and os.access(c, os.X_OK)), None)


def build_command(info: dict, cfg: dict) -> Optional[list[str]]:
    if info["backend"] == "claude":
        binary = claude_bin_for(cfg, info.get("user", ""), info.get("home", ""))
        if not binary:
            return None
        mode = info.get("mode") or "manual"
        mode = "manual" if mode == "default" else mode
        if mode not in CLAUDE_MODES:
            mode = "manual"
        return [binary, "-p", "--resume", info["session_id"], "--permission-mode", mode,
                "--output-format", "json", RESUME_PROMPT]
    codex = codex_bin_for(cfg, info["user"], info["home"])
    if not codex:
        return None
    sb = info.get("sandbox") or {}
    sandbox_mode = {"danger-full-access": "danger-full-access", "read-only": "read-only"}.get(sb.get("type"), "workspace-write")
    cmd = [codex, "exec", "resume", "--skip-git-repo-check", "-c", 'approval_policy="never"',
           "-c", f'sandbox_mode="{sandbox_mode}"']
    if sandbox_mode == "workspace-write" and sb.get("network_access"):
        cmd += ["-c", "sandbox_workspace_write.network_access=true"]
    if info.get("model"):
        cmd += ["-m", str(info["model"])]
    if info.get("effort"):
        cmd += ["-c", f'model_reasoning_effort="{info["effort"]}"']
    return cmd + [info["session_id"], RESUME_PROMPT]


def unit_name(info: dict, now: datetime) -> str:
    sid = re.sub(r"[^0-9a-zA-Z]", "", info["session_id"])[:12]
    return f"session-resume-{info['backend']}-{sid}-{int(now.timestamp())}"


def launch(info: dict, cfg: dict, now: datetime, *, dry_run: bool = False) -> tuple[Optional[str], str]:
    """systemd-run 임시 유닛으로 세션 주인 권한에서 재개 실행. (유닛 이름 또는 None, 메시지)."""
    cmd = build_command(info, cfg)
    if not cmd:
        return None, f"{info['backend']} 실행 파일을 찾지 못함"
    try:
        pw = pwd.getpwnam(info["user"])
    except KeyError:
        return None, f"계정 없음: {info['user']}"
    cwd = info.get("cwd") if info.get("cwd") and os.path.isdir(info["cwd"]) else info["home"]
    unit = unit_name(info, now)
    run = ["systemd-run", f"--unit={unit}", "--collect", "--quiet", f"--uid={pw.pw_uid}", f"--gid={pw.pw_gid}",
           f"--working-directory={cwd}", f"--setenv=HOME={info['home']}", f"--setenv=USER={info['user']}",
           f"--setenv=LOGNAME={info['user']}",
           f"--setenv=PATH={info['home']}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
           f"-p", f"RuntimeMaxSec={int(cfg['run_timeout_hours'] * 3600)}", "-p", "Nice=5",
           f"--description=한도 후 세션 자동 재개 {info['backend']} {info['session_id']}", "--", *cmd]
    if dry_run:
        return unit, " ".join(run)
    try:
        res = subprocess.run(run, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"systemd-run 실패: {type(exc).__name__}"
    if res.returncode != 0:
        return None, f"systemd-run 실패: {_short(res.stderr, 200)}"
    return unit, "시작"


def unit_running(unit: str) -> bool:
    try:
        res = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.stdout.strip() in ("active", "activating", "deactivating", "reloading")


def notify(cfg: dict, text: str) -> None:
    if not cfg.get("notify") or not ALERT_SCRIPT.exists():
        return
    try:
        subprocess.run([str(ALERT_SCRIPT), text], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------------------
# 상태·토글
# ---------------------------------------------------------------------------
def load_toggles() -> dict:
    data = _read_json(STATE_DIR / "toggles.json", {})
    return data if isinstance(data, dict) else {}


def is_enabled(toggles: dict, key: Optional[str] = None) -> bool:
    if key is None:
        return bool(toggles.get("enabled", True))
    entry = (toggles.get("sessions") or {}).get(key) or {}
    return bool(entry.get("enabled", True))


def _label(e: dict) -> str:
    where = os.path.basename((e.get("cwd") or "").rstrip("/")) or "?"
    return f"{e['backend'].capitalize()} · {e['user']} · {where} · {e.get('title') or e['session_id']}"


def due_at(e: dict, cfg: dict) -> datetime:
    if e.get("retry_after"):
        return _parse_ts(e["retry_after"])
    reset = _parse_ts(e.get("reset_at"))
    stopped = _parse_ts(e["stopped_at"])
    if reset:
        return reset + timedelta(minutes=cfg["reset_margin_minutes"])
    return stopped + timedelta(minutes=cfg["unknown_reset_wait_minutes"])


def tick(cfg: dict, now: Optional[datetime] = None, *, dry_run: bool = False,
         launcher=launch, running=unit_running, notifier=notify) -> dict:
    now = now or _now()
    state = _read_json(STATE_DIR / "state.json", {})
    sessions: dict[str, dict] = state.get("sessions") or {}
    history: list[dict] = state.get("history") or []
    toggles = load_toggles()
    master_on = is_enabled(toggles)
    found = {c["key"]: c for c in discover(cfg, now)}
    messages: list[str] = []

    # 1) 실행 중이던 재개의 결과 판정
    for key, e in list(sessions.items()):
        if e.get("status") != "resuming":
            continue
        if e.get("unit") and running(e["unit"]):
            continue
        c = found.get(key)
        if c is None:
            e.update(status="resumed", finished_at=_iso(now))
            messages.append(f"✅ 이어서 진행 완료: {_label(e)}")
        elif c["stopped_at"] > (_parse_ts(e.get("launched_at")) or now):
            e.update(status="waiting", finished_at=_iso(now), retry_after=None, note="재개 중 다시 한도 도달 — 다음 초기화 대기")
            messages.append(f"⏳ 재개했지만 다시 한도: {_label(e)} — 다음 초기화 뒤 다시 시도")
        else:
            e.update(status="waiting", finished_at=_iso(now), note="재개 실행이 이어서 진행하지 못하고 끝남",
                     retry_after=_iso(now + timedelta(minutes=cfg["retry_after_failure_minutes"])))
            messages.append(f"⚠️ 재개 실행이 실패: {_label(e)} — journalctl -u {e.get('unit')}")

    # 2) 발견 목록 반영
    for key, c in found.items():
        e = sessions.get(key)
        stopped_iso = _iso(c["stopped_at"])
        fields = {k: c.get(k) for k in ("backend", "user", "home", "session_id", "cwd", "title", "reason", "transcript",
                                        "mode", "sandbox", "model", "effort")}
        fields.update(stopped_at=stopped_iso, reset_at=_iso(c.get("reset_at")))
        if e is None:
            e = {"key": key, "status": "waiting", "attempts": 0, "first_seen": _iso(now)}
            sessions[key] = e
        elif e.get("stopped_at") != stopped_iso and e.get("status") not in ("resuming",):
            e.pop("retry_after", None)  # 새 멈춤 — 새 초기화 시각을 따른다
            if e.get("status") in ("resumed", "expired"):
                e["attempts"] = 0
                e["status"] = "waiting"
        e.update(fields)

    # 3) 더 이상 멈춘 상태가 아닌 세션은 기록으로 옮긴다(사람이 직접 이어 갔거나 재개가 끝남)
    for key in list(sessions):
        e = sessions[key]
        if key in found or e.get("status") == "resuming":
            continue
        if e.get("status") != "resumed":
            e["status"] = "continued"  # 자동 재개 없이 멈춤이 풀림(사람이 이어 감)
            e["finished_at"] = _iso(now)
        history.insert(0, sessions.pop(key))
    del history[cfg["history_keep"]:]

    # 4) 재개할 차례인 세션 실행
    active = sum(1 for e in sessions.values() if e.get("status") == "resuming")
    for key, e in sorted(sessions.items(), key=lambda kv: kv[1]["stopped_at"]):
        if e.get("status") == "resuming":
            continue
        if not master_on or not is_enabled(toggles, key):
            e["status"] = "off"
            continue
        if e.get("status") == "off":
            e["status"] = "waiting"
        due = due_at(e, cfg)
        e["due_at"] = _iso(due)
        if e.get("attempts", 0) >= cfg["max_attempts"]:
            e["status"] = "gave_up"
            continue
        if now - due > timedelta(hours=cfg["resume_window_hours"]):
            e["status"] = "expired"  # 너무 오래 지났다 — 자동으로 깨우지 않는다(화면에서 확인만)
            continue
        if e.get("status") in ("gave_up", "expired"):
            e["status"] = "waiting"
        if now < due or active >= cfg["max_concurrent"]:
            continue
        unit, msg = launcher(e, cfg, now, dry_run=dry_run)
        e["attempts"] = e.get("attempts", 0) + 1
        e["last_message"] = msg
        if unit:
            e.update(status="resuming", unit=unit, launched_at=_iso(now), retry_after=None, note=None)
            active += 1
            messages.append(f"▶️ 한도 초기화 — 세션 이어서 진행 시작({e['attempts']}회차): {_label(e)}")
        else:
            e.update(status="waiting", note=msg,
                     retry_after=_iso(now + timedelta(minutes=cfg["retry_after_failure_minutes"])))
            messages.append(f"⚠️ 세션 재개를 시작하지 못함: {_label(e)} — {msg}")

    state = {"updated_at": _iso(now), "enabled": master_on, "sessions": sessions, "history": history}
    if not dry_run:
        _write_json(STATE_DIR / "state.json", state)
        if messages:
            notifier(cfg, "[세션 자동 재개]\n" + "\n".join(messages) + "\n관제 센터 /session-resume 에서 확인·끄기")
    return state


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    override = _read_json(STATE_DIR / "config.json", {})
    if isinstance(override, dict):
        cfg.update(override)
    return cfg


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="사용량 한도로 멈춘 Claude/Codex 세션 자동 재개")
    ap.add_argument("--dry-run", action="store_true", help="발견·판단만 출력하고 실행·저장·알림은 하지 않음")
    args = ap.parse_args(argv)
    cfg = load_config()
    state = tick(cfg, dry_run=args.dry_run)
    if args.dry_run:
        print(json.dumps({k: {f: v.get(f) for f in ("status", "title", "cwd", "stopped_at", "reset_at", "due_at", "attempts")}
                          for k, v in state["sessions"].items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
