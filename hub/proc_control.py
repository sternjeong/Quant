"""관제 허브 '과부하 비상 정지' 화면 — CPU·메모리 과부하 때 무거운 프로세스를 일시정지/재개/종료한다 (2026-11-15).

라우트(hub/server.py): GET /emergency   POST /emergency/signal (pid, sig), /emergency/bulk (mode=pause_heavy|resume_all)

- CPU 사용률은 프로세스 평생 평균(/live)이 아니라 지금 1초 동안 잰 값이다 — 과부하 순간의 범인을 찾는 용도.
- 일시정지(SIGSTOP)는 작업을 잃지 않고 얼린다(재개 SIGCONT로 이어서 진행). 과부하 때는 종료보다 일시정지가 먼저다.
- 허브는 quant 계정이라 ubuntu 계정 프로세스는 root 도우미(deploy/proc_control/quant-proc-signal, setup.sh 로 설치)를
  sudo 로 거쳐야 한다. 도우미가 없으면 quant 계정 프로세스만 직접 다룬다.
- 대상·보호 규칙은 도우미 파일 하나가 원본이다(아래에서 그 파일을 불러와 같은 check() 를 쓴다).
- 모든 조작은 data/proc_control.log 에 한 줄씩 남긴다.
"""

from __future__ import annotations

import html
import importlib.machinery
import importlib.util
import os
import pwd
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from hub import ui
from hub.live_status import classify, redact

E = html.escape
PROJECT_ROOT = Path(__file__).resolve().parent.parent
HELPER_SRC = PROJECT_ROOT / "deploy" / "proc_control" / "quant-proc-signal"
HELPER_BIN = Path("/usr/local/sbin/quant-proc-signal")
LOG_PATH = PROJECT_ROOT / "data" / "proc_control.log"
HEAVY_CPU = 15.0  # '무거운 작업 전부 일시정지' 대상: 지금 1초 CPU 사용률이 이 이상
SHOW_TOP = 15
SIGNAL_LABELS = {"STOP": "일시정지", "CONT": "재개", "TERM": "종료", "KILL": "강제 종료"}
_CLK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_helper_ok: tuple[float, bool] = (0.0, False)


def _rules():
    loader = importlib.machinery.SourceFileLoader("quant_proc_signal", str(HELPER_SRC))
    spec = importlib.util.spec_from_loader("quant_proc_signal", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


RULES = _rules()


def helper_available() -> bool:
    """도우미가 설치돼 있고 quant 가 sudo 로 실행할 수 있는지(5분 캐시)."""
    global _helper_ok
    if time.time() - _helper_ok[0] < 300:
        return _helper_ok[1]
    ok = False
    if HELPER_BIN.exists():
        try:
            ok = subprocess.run(["sudo", "-n", "-l", str(HELPER_BIN)], capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
    _helper_ok = (time.time(), ok)
    return ok


# ---------------------------------------------------------------- 측정
def _uids() -> dict[int, str]:
    out = {}
    for u in RULES.ALLOWED_USERS:
        try:
            out[pwd.getpwnam(u).pw_uid] = u
        except KeyError:
            continue
    return out


def _read_proc(proc: Path, uids: dict[int, str]) -> dict[int, dict]:
    rows = {}
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            uid = d.stat().st_uid
            if uid not in uids:
                continue
            raw = (d / "stat").read_text()
            comm = raw[raw.index("(") + 1:raw.rindex(")")]
            fields = raw.rsplit(")", 1)[1].split()
            rows[int(d.name)] = {"pid": int(d.name), "user": uids[uid], "comm": comm, "state": fields[0],
                                 "ticks": int(fields[11]) + int(fields[12]), "start": int(fields[19]),
                                 "rss_mb": int(fields[21]) * _PAGE / 1e6}
        except (OSError, ValueError, IndexError):
            continue
    return rows


def _cpu_total(proc: Path) -> tuple[int, int]:
    parts = [int(x) for x in (proc / "stat").read_text().splitlines()[0].split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    return sum(parts), idle


def sample(interval: float = 1.0, proc: Path = Path("/proc")) -> dict:
    """{'rows': [...], 'cpu_busy': %, 'load': (1,5,15), 'mem': {...}} — rows 는 지금 CPU 사용률 내림차순."""
    uids = _uids()
    t0, i0 = _cpu_total(proc)
    a = _read_proc(proc, uids)
    time.sleep(interval)
    t1, i1 = _cpu_total(proc)
    b = _read_proc(proc, uids)
    ncpu = os.cpu_count() or 1
    rows = []
    for pid, r in b.items():
        prev = a.get(pid)
        cpu = 100.0 * (r["ticks"] - prev["ticks"]) / _CLK / interval if prev and prev["start"] == r["start"] else 0.0
        try:
            cmd = (proc / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            continue
        if not cmd:
            continue
        why = RULES.check(pid) if proc == Path("/proc") else ""
        rows.append({**r, "cpu": cpu, "cmd": redact(cmd)[:240], "what": classify(cmd) or r["comm"], "protected": why,
                     "paused": r["state"] == "T"})
    rows.sort(key=lambda r: (-r["cpu"], -r["rss_mb"]))
    mem = {}
    try:
        for line in (proc / "meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0]) / 1024 / 1024  # GiB
    except (OSError, ValueError):
        pass
    dt = max(t1 - t0, 1)
    return {"rows": rows, "cpu_busy": 100.0 * (1 - (i1 - i0) / dt), "ncpu": ncpu, "load": os.getloadavg(),
            "mem_total": mem.get("MemTotal"), "mem_avail": mem.get("MemAvailable")}


def paused_processes(proc: Path = Path("/proc")) -> list[dict]:
    """일시정지(T) 상태로 남아 있는 ubuntu·quant 프로세스 — 개요 경고용(측정 없이 빠르게)."""
    return [r for r in _read_proc(proc, _uids()).values() if r["state"] == "T"]


# ---------------------------------------------------------------- 조작
def _log(sig: str, results: list[tuple[int, bool, str]]) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            for pid, ok, msg in results:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {sig} {pid} {'ok' if ok else 'fail'} {msg}\n")
    except OSError:
        pass


def send(sig: str, pids: list[int]) -> list[tuple[int, bool, str]]:
    """[(pid, 성공, 메시지)]. 도우미가 있으면 sudo 로, 없으면 허브 자신의 계정(quant) 프로세스만 직접."""
    if sig not in RULES.SIGNALS or not pids:
        return []
    pids = [int(p) for p in pids][:48]
    results: list[tuple[int, bool, str]] = []
    if helper_available():
        r = subprocess.run(["sudo", "-n", str(HELPER_BIN), sig, *map(str, pids)], capture_output=True, text=True, timeout=10)
        lines = {ln.split(" ", 1)[0]: ln for ln in r.stdout.splitlines()}
        for pid in pids:
            line = lines.get(str(pid), f"{pid} 응답 없음")
            results.append((pid, line.endswith(" ok"), line.split(" ", 1)[1] if " " in line else line))
    else:
        me = os.getuid()
        for pid in pids:
            why = RULES.check(pid)
            try:
                owner = os.stat(f"/proc/{pid}").st_uid
            except OSError:
                owner = None
            if why:
                results.append((pid, False, why))
            elif owner != me:
                results.append((pid, False, "다른 계정 프로세스 — root 도우미 설치 필요"))
            else:
                try:
                    os.kill(pid, getattr(signal, f"SIG{sig}"))
                    results.append((pid, True, "ok"))
                except OSError as exc:
                    results.append((pid, False, exc.strerror or "실패"))
    _log(sig, results)
    return results


def bulk(mode: str) -> list[tuple[int, bool, str]]:
    if mode == "pause_heavy":
        rows = sample()["rows"]
        pids = [r["pid"] for r in rows if r["cpu"] >= HEAVY_CPU and not r["protected"] and not r["paused"]]
        return send("STOP", pids)
    if mode == "resume_all":
        return send("CONT", [r["pid"] for r in paused_processes()])
    return []


def summarize(sig: str, results: list[tuple[int, bool, str]]) -> str:
    if not results:
        return "대상 프로세스가 없습니다."
    ok = sum(1 for _, good, _ in results if good)
    fails = [f"{pid}: {msg}" for pid, good, msg in results if not good]
    return f"{SIGNAL_LABELS.get(sig, sig)} {ok}개 완료" + (f" · 실패 {len(fails)}개 ({'; '.join(fails[:3])})" if fails else "")


# ---------------------------------------------------------------- 화면
def card_badge() -> str:
    try:
        paused = paused_processes()
        load1 = os.getloadavg()[0]
    except OSError:
        return ui.pill("확인 불가", "muted")
    ncpu = os.cpu_count() or 1
    pills = []
    if paused:
        pills.append(ui.pill(f"일시정지 {len(paused)}개", "warn"))
    if load1 >= ncpu * 1.5:
        pills.append(ui.pill(f"과부하 {load1:.1f}", "bad"))
    elif load1 >= ncpu:
        pills.append(ui.pill(f"부하 {load1:.1f}", "warn"))
    return "".join(pills) or ui.pill(f"부하 {load1:.1f}", "ok")


def _btn(sig: str, pid: int, *, primary: bool = False, confirm: str = "") -> str:
    onsubmit = f' onsubmit="return confirm(\'{E(confirm)}\')"' if confirm else ""
    return (f'<form method="post" action="/emergency/signal"{onsubmit} style="margin:0">'
            f'<input type="hidden" name="pid" value="{pid}"><input type="hidden" name="sig" value="{sig}">'
            f'<button class="btn{" primary" if primary else ""}" type="submit" '
            f'style="min-height:34px;padding:0 10px;font-size:.8rem">{SIGNAL_LABELS[sig]}</button></form>')


def _row(r: dict, can_other: bool) -> str:
    tone = "bad" if r["cpu"] >= 50 else "warn" if r["cpu"] >= HEAVY_CPU else "muted"
    title_extra = ui.pill(f"CPU {r['cpu']:.0f}%", tone) + ui.pill(f"{r['rss_mb'] / 1024:.1f}GB" if r["rss_mb"] >= 1024 else f"{r['rss_mb']:.0f}MB", "muted", plain=True)
    if r["paused"]:
        title_extra += ui.pill("일시정지됨", "warn")
    desc = f"{r['user']} · pid {r['pid']} · {r['cmd']}"
    if r["protected"]:
        end = ui.pill("보호", "muted")
    elif r["user"] != "quant" and not can_other:
        end = ui.pill("도우미 설치 필요", "muted")
    elif r["paused"]:
        end = _btn("CONT", r["pid"], primary=True) + _btn("TERM", r["pid"], confirm=f"pid {r['pid']} 을(를) 종료할까요? 진행 중인 작업이 끝납니다.")
    else:
        end = (_btn("STOP", r["pid"], primary=True)
               + _btn("TERM", r["pid"], confirm=f"pid {r['pid']} ({r['what']}) 을(를) 종료할까요? 진행 중인 작업이 끝납니다.")
               + _btn("KILL", r["pid"], confirm=f"pid {r['pid']} 을(를) 강제 종료할까요? 저장되지 않은 결과는 사라집니다."))
    return ui.row(r["what"], icon="⚙", desc=desc, title_extra_html=title_extra, end_html=end)


def render_body(message: str = "", data: Optional[dict] = None) -> str:
    data = data or sample()
    rows, ncpu = data["rows"], data["ncpu"]
    load1, load5, _ = data["load"]
    can_other = helper_available()
    heavy = [r for r in rows if r["cpu"] >= HEAVY_CPU and not r["protected"] and not r["paused"]]
    paused = [r for r in rows if r["paused"]]
    if load1 >= ncpu * 1.5 or data["cpu_busy"] >= 95:
        tone, title = "bad", "과부하 상태입니다"
    elif load1 >= ncpu or data["cpu_busy"] >= 80:
        tone, title = "warn", "부하가 높습니다"
    else:
        tone, title = "ok", "여유 있습니다"
    sub = (f"지금 CPU {data['cpu_busy']:.0f}% 사용 · 부하 {load1:.1f} (코어 {ncpu}개 기준 {ncpu}.0 이 꽉 찬 상태)"
           + (f" · 일시정지 중 {len(paused)}개" if paused else ""))
    mem_used = (data["mem_total"] - data["mem_avail"]) if data["mem_total"] and data["mem_avail"] is not None else None
    tiles = ui.stats([
        ui.stat("CPU 지금", f"{data['cpu_busy']:.0f}%", f"코어 {ncpu}개", tone),
        ui.stat("부하(1분/5분)", f"{load1:.1f} / {load5:.1f}", f"{ncpu}.0 = 꽉 참", tone),
        ui.stat("메모리", f"{mem_used:.1f}/{data['mem_total']:.0f}GB" if mem_used is not None else "—",
                f"남은 {data['mem_avail']:.1f}GB" if data["mem_avail"] is not None else "",
                "bad" if data["mem_avail"] is not None and data["mem_avail"] < 1 else "ok"),
        ui.stat("일시정지 중", str(len(paused)), "잊지 말고 재개", "warn" if paused else "ok"),
    ])
    bulk_html = ('<div class="panel" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0">'
                 '<form method="post" action="/emergency/bulk" style="margin:0" onsubmit="return confirm(\'CPU 를 많이 쓰는 작업을 모두 일시정지할까요? 재개하면 이어서 진행됩니다.\')">'
                 '<input type="hidden" name="mode" value="pause_heavy">'
                 f'<button class="btn primary" type="submit">⏸ 무거운 작업 전부 일시정지 ({len(heavy)}개)</button></form>'
                 '<form method="post" action="/emergency/bulk" style="margin:0"><input type="hidden" name="mode" value="resume_all">'
                 f'<button class="btn" type="submit">▶ 일시정지한 것 전부 재개 ({len(paused)}개)</button></form>'
                 f'<span class="meta">무거운 작업 = 지금 CPU {HEAVY_CPU:.0f}% 이상 · 보호 프로세스 제외</span></div>')
    msg = ui.callout(E(message), icon="✓") if message else ""
    helper_note = "" if can_other else ui.callout(
        "지금은 관제 센터(quant 계정)의 프로세스만 멈출 수 있습니다. ubuntu 계정 작업(Claude 세션, 데이터셋 빌드 등)까지 "
        "멈추려면 VM 터미널에서 한 번 <code>sudo bash /opt/quant/deploy/proc_control/setup.sh</code> 를 실행하세요.",
        icon="🔒", tone="warn")
    top = [r for r in rows if r["cpu"] >= 1 or r["paused"]][:SHOW_TOP] or rows[:5]
    help_html = ui.callout(
        "<b>일시정지</b>는 작업을 잃지 않고 얼립니다 — 부하가 내려가면 <b>재개</b>로 이어서 진행됩니다. 과부하 때는 이것부터. "
        "<b>종료</b>는 정상 종료 요청, <b>강제 종료</b>는 즉시 끝냅니다(저장 안 된 결과는 사라짐). "
        "관제 센터·nginx·SSH·tmux·셸과 root 프로세스는 보호되어 건드릴 수 없습니다. 조작 기록: data/proc_control.log", icon="💡")
    return (f'{msg}{ui.verdict(tone, title, sub)}{tiles}{helper_note}{bulk_html}'
            f'{ui.section("지금 CPU 를 쓰는 프로세스 (1초 측정)", ui.row_list(_row(r, can_other) for r in top))}{help_html}')
