"""놀고 있는 Claude Code 대화 세션을 찾아 보여 주고, 요청(또는 켜 둔 자동 정리)이 있으면 닫아 VM 메모리를 돌려받는다.

배경(2026-11-15, docs/COMPUTE_OFFLOAD_DESIGN.md 2(a)): 2코어·12GB VM 에 사람이 열어 두고 잊은 `claude` 대화 세션이 19개,
합쳐 약 4.9GB 가 상주했다. 모델 계산은 Anthropic 쪽이지만 node 클라이언트가 세션마다 200~400MB 를 붙잡고 있어
연구 실행기가 "VM 여유 메모리 부족"으로 양보하곤 했다.

동작(quant-session-reaper.timer 가 10분마다 root 로 1회 실행):
1. /proc 에서 대화형 `claude` 프로세스를 모두 찾는다. `-p/--print`(비대화 실행: 텔레그램 러너·야간 에이전트·세션 자동 재개)는 건드리지 않는다.
2. 세션마다 다음을 잰다.
   - 터미널(/dev/pts/N) 마지막 입력 시각(atime)
   - 프로세스 트리(자식 포함) CPU 누적 시간
   - 메모리(RSS, 트리 합)
   - 작업 폴더, 붙어 있는 tmux 세션 이름
3. '놀고 있음'은 다음 둘을 모두 만족하는 경우다.
   - 터미널 입력이 idle_hours(기본 24시간) 넘게 없다.
   - 최근 cpu_window_minutes(기본 60분) 동안 트리 CPU 가 cpu_idle_seconds(기본 10초) 넘게 늘지 않았다.
   사람이 안 봐도 혼자 일하는 자동 세션(CPU 가 계속 늘어남)은 놀고 있음이 아니다.
4. 닫기는 다음 두 경우에만 한다.
   - 관제 센터 '놀고 있는 AI 세션'(/idle-sessions) 화면에서 '닫기'를 누른 세션(requests.json)
   - 자동 정리를 켠 경우(toggles.json, 기본 꺼짐) '놀고 있음' 세션 중 '자동 정리 제외'가 아닌 것
   닫기는 SIGTERM(10초 뒤 살아 있으면 SIGKILL)이다. 대화 기록(~/.claude/projects/…/*.jsonl)은 그대로 남아,
   그 폴더에서 `claude --resume` 으로 다시 열 수 있다. 닫기 직전에 pid·시작 시각·이름을 다시 확인한다(pid 재사용 방지).

상태: data/session_reaper/state.json(이 스크립트만 쓴다). 켜기/끄기: toggles.json, 닫기 요청: requests.json(관제 화면이 쓴다).
stdlib 만 쓴다(시스템 python3 로 root 가 실행 — 프로젝트 venv 불필요).
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = PROJECT_ROOT / "data" / "session_reaper"
ALERT_SCRIPT = PROJECT_ROOT / "deploy" / "send_telegram_alert.sh"

DEFAULT_CONFIG: dict[str, Any] = {
    "idle_hours": 24.0,
    "cpu_window_minutes": 60,
    "cpu_idle_seconds": 10.0,
    "term_grace_seconds": 10,
    "history_keep": 60,
    "notify": True,
}
CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE_KB = (os.sysconf("SC_PAGE_SIZE") // 1024) if hasattr(os, "sysconf") else 4


def _now_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------------------------------------------
# /proc 읽기
# ---------------------------------------------------------------------------------------------------------------

def _stat_fields(proc: Path, pid: int) -> Optional[list[str]]:
    """/proc/<pid>/stat 의 ')' 뒤 필드들. [0]=state, [1]=ppid, [11]=utime, [12]=stime, [19]=starttime, [21]=rss(pages)."""
    try:
        raw = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    return raw[raw.rfind(")") + 2:].split()


def read_processes(proc: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        pid = int(d.name)
        f = _stat_fields(proc, pid)
        if not f or len(f) < 22:
            continue
        try:
            comm = (d / "comm").read_text().strip()
            argv = [a for a in (d / "cmdline").read_bytes().split(b"\0") if a]
            uid = d.stat().st_uid
        except OSError:
            continue
        out[pid] = {
            "pid": pid, "ppid": int(f[1]), "comm": comm, "argv": [a.decode("utf-8", "replace") for a in argv],
            "uid": uid, "cpu": (int(f[11]) + int(f[12])) / CLK_TCK, "start": int(f[19]),
            "rss_mb": int(f[21]) * PAGE_KB / 1024,
        }
    return out


def is_interactive_claude(p: dict) -> bool:
    if p["comm"] != "claude" or not p["argv"]:
        return False
    args = p["argv"][1:]
    return not any(a in ("-p", "--print") for a in args)


def _children(procs: dict[int, dict]) -> dict[int, list[int]]:
    kids: dict[int, list[int]] = {}
    for p in procs.values():
        kids.setdefault(p["ppid"], []).append(p["pid"])
    return kids


def tree(pid: int, kids: dict[int, list[int]]) -> list[int]:
    out, stack = [], [pid]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(kids.get(cur, []))
    return out


def tty_of(proc: Path, pid: int) -> Optional[str]:
    try:
        target = os.readlink(proc / str(pid) / "fd" / "0")
    except OSError:
        return None
    return target if target.startswith("/") and target != "/dev/null" else None  # 파이프·소켓·/dev/null 은 터미널이 아니다


def _user(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def tmux_panes(user: str, runner: Callable[[list[str]], str]) -> dict[int, str]:
    """{pane 셸 pid: tmux 세션 이름}. tmux 가 없거나 서버가 없으면 빈 dict."""
    try:
        out = runner(["runuser", "-u", user, "--", "tmux", "list-panes", "-a", "-F", "#{pane_pid} #{session_name}"])
    except Exception:
        return {}
    panes = {}
    for line in out.splitlines():
        pid, _, name = line.partition(" ")
        if pid.isdigit():
            panes[int(pid)] = name
    return panes


def _default_runner(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout


# ---------------------------------------------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------------------------------------------

def session_key(p: dict) -> str:
    return f"{p['pid']}-{p['start']}"


def scan(proc: Path, now: float, state: dict, config: dict, runner: Callable[[list[str]], str] = _default_runner) -> list[dict]:
    procs = read_processes(proc)
    kids = _children(procs)
    samples: dict[str, list] = state.get("samples") or {}
    panes_by_user: dict[str, dict[int, str]] = {}
    sessions = []
    for p in procs.values():
        if not is_interactive_claude(p):
            continue
        key = session_key(p)
        members = [procs[x] for x in tree(p["pid"], kids) if x in procs]
        tree_cpu = round(sum(m["cpu"] for m in members), 2)
        rss = round(sum(m["rss_mb"] for m in members), 1)
        user = _user(p["uid"])
        tty = tty_of(proc, p["pid"])
        input_at = None
        if tty:
            try:
                input_at = os.stat(tty).st_atime
            except OSError:
                input_at = None
        try:
            cwd = os.readlink(proc / str(p["pid"]) / "cwd")
        except OSError:
            cwd = ""
        if user not in panes_by_user:
            panes_by_user[user] = tmux_panes(user, runner)
        tmux_name, cur = None, p["ppid"]
        for _ in range(6):  # pane 셸까지 몇 단계 위로
            if cur in panes_by_user[user]:
                tmux_name = panes_by_user[user][cur]
                break
            if cur not in procs:
                break
            cur = procs[cur]["ppid"]

        hist = [s for s in samples.get(key, []) if now - s[0] <= 24 * 3600]
        hist.append([now, tree_cpu])
        samples[key] = hist[-200:]
        window = config["cpu_window_minutes"] * 60
        older = [s for s in hist if now - s[0] >= window]
        cpu_growth = round(tree_cpu - older[-1][1], 2) if older else None
        idle_h = round((now - input_at) / 3600, 1) if input_at else None

        if idle_h is None:
            status = "no_tty"
        elif idle_h < config["idle_hours"]:
            status = "active"
        elif cpu_growth is None:
            status = "measuring"
        elif cpu_growth > config["cpu_idle_seconds"]:
            status = "working"
        else:
            status = "idle"
        sessions.append({
            "key": key, "pid": p["pid"], "start": p["start"], "user": user, "cwd": cwd, "tty": tty or "",
            "tmux": tmux_name, "args": " ".join(p["argv"][1:])[:120], "rss_mb": rss, "tree_cpu": tree_cpu,
            "cpu_growth_window": cpu_growth, "input_idle_hours": idle_h,
            "input_at": _now_iso(input_at) if input_at else None, "status": status,
        })
    live = {s["key"] for s in sessions}
    state["samples"] = {k: v for k, v in samples.items() if k in live}
    return sorted(sessions, key=lambda s: (s["status"] != "idle", -(s["input_idle_hours"] or 0)))


def choose_closures(sessions: list[dict], toggles: dict, requests: dict) -> list[tuple[dict, str]]:
    """(세션, 이유) 목록. 이유: 'requested'(화면에서 닫기) / 'auto'(자동 정리 켬 + 놀고 있음 + 제외 아님)."""
    out = []
    excluded = {k for k, v in (toggles.get("sessions") or {}).items() if (v or {}).get("exclude")}
    auto = bool(toggles.get("auto_close", False))
    for s in sessions:
        if s["key"] in requests:
            out.append((s, "requested"))
        elif auto and s["status"] == "idle" and s["key"] not in excluded:
            out.append((s, "auto"))
    return out


def close_session(proc: Path, s: dict, grace: float, kill: Callable[[int, int], None] = os.kill,
                  sleep: Callable[[float], None] = time.sleep) -> str:
    """같은 프로세스(pid·시작 시각·이름)인지 다시 확인한 뒤 SIGTERM, 남아 있으면 SIGKILL. 결과: closed/killed/gone/mismatch."""
    def same() -> bool:
        f = _stat_fields(proc, s["pid"])
        try:
            comm = (proc / str(s["pid"]) / "comm").read_text().strip()
        except OSError:
            return False
        return bool(f) and int(f[19]) == s["start"] and comm == "claude"

    if not same():
        return "gone" if not (proc / str(s["pid"])).exists() else "mismatch"
    kill(s["pid"], signal.SIGTERM)
    waited = 0.0
    while waited < grace:
        sleep(0.5)
        waited += 0.5
        if not same():
            return "closed"
    if same():
        kill(s["pid"], signal.SIGKILL)
        return "killed"
    return "closed"


# ---------------------------------------------------------------------------------------------------------------
# 한 회차
# ---------------------------------------------------------------------------------------------------------------

def run_once(proc: Path = Path("/proc"), state_dir: Path = STATE_DIR, now: Optional[float] = None, dry_run: bool = False,
             runner: Callable[[list[str]], str] = _default_runner, kill: Callable[[int, int], None] = os.kill,
             sleep: Callable[[float], None] = time.sleep, notify: Optional[Callable[[str], None]] = None) -> dict:
    now = time.time() if now is None else now
    config = {**DEFAULT_CONFIG, **_read_json(state_dir / "config.json", {})}
    state = _read_json(state_dir / "state.json", {})
    toggles = _read_json(state_dir / "toggles.json", {})
    requests = _read_json(state_dir / "requests.json", {})

    sessions = scan(proc, now, state, config, runner)
    closures = choose_closures(sessions, toggles, requests)
    history = state.get("history") or []
    closed = []
    if not dry_run:
        for s, why in closures:
            result = close_session(proc, s, config["term_grace_seconds"], kill, sleep)
            entry = {"at": _now_iso(now), "reason": why, "result": result, "user": s["user"], "cwd": s["cwd"],
                     "tmux": s["tmux"], "rss_mb": s["rss_mb"], "input_idle_hours": s["input_idle_hours"]}
            history.insert(0, entry)
            if result in ("closed", "killed"):
                closed.append(entry)
        # 처리했거나(닫힘·이미 없음) 지금 목록에 없는 요청은 지운다.
        live = {s["key"] for s in sessions}
        handled = {s["key"] for s, _ in closures}
        remaining = {k: v for k, v in requests.items() if k in live and k not in handled}
        if remaining != requests:
            _write_json(state_dir / "requests.json", remaining)
        closed_keys = {s["key"] for s, _ in closures}
        sessions = [s for s in sessions if s["key"] not in closed_keys]

    idle = [s for s in sessions if s["status"] == "idle"]
    out = {
        "updated_at": _now_iso(now), "config": {k: config[k] for k in ("idle_hours", "cpu_window_minutes", "cpu_idle_seconds")},
        "auto_close": bool(toggles.get("auto_close", False)), "sessions": sessions,
        "totals": {"sessions": len(sessions), "rss_mb": round(sum(s["rss_mb"] for s in sessions), 1),
                   "idle": len(idle), "idle_rss_mb": round(sum(s["rss_mb"] for s in idle), 1)},
        "history": history[: config["history_keep"]], "samples": state.get("samples") or {},
    }
    if dry_run:
        return out
    _write_json(state_dir / "state.json", out)
    if closed and config.get("notify", True):
        freed = round(sum(e["rss_mb"] for e in closed))
        lines = [f"[AI 세션 정리] {len(closed)}개 닫음 — 메모리 약 {freed}MB 회수"]
        for e in closed[:10]:
            where = e["tmux"] and f"tmux {e['tmux']}" or e["cwd"]
            why = "화면에서 요청" if e["reason"] == "requested" else f"자동(입력 {e['input_idle_hours']}시간 없음)"
            lines.append(f"- {where} · {round(e['rss_mb'])}MB · {why}")
        lines.append("대화 기록은 남아 있어 그 폴더에서 claude --resume 으로 다시 열 수 있습니다.")
        (notify or _telegram)("\n".join(lines))
    return out


def _telegram(message: str) -> None:
    if ALERT_SCRIPT.exists():
        subprocess.run([str(ALERT_SCRIPT), message], capture_output=True, timeout=30)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="닫지 않고 저장·알림 없이 지금 판정만 JSON 으로 출력")
    args = ap.parse_args(argv)
    out = run_once(dry_run=args.dry_run)
    if args.dry_run:
        out.pop("samples", None)
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
