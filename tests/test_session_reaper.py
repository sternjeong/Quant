"""놀고 있는 AI 세션 수거기(deploy/session_reaper/reaper.py)와 관제 화면(hub/idle_sessions_page.py).

가짜 /proc 트리(stat·comm·cmdline·fd/0·cwd)를 만들어 실제 프로세스에는 신호를 보내지 않는다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("session_reaper", ROOT / "deploy" / "session_reaper" / "reaper.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

HOUR = 3600.0
NOW = 1_800_000_000.0


class FakeProc:
    def __init__(self, tmp: Path):
        self.root = tmp / "proc"
        self.root.mkdir()
        self.ttys = tmp / "pts"
        self.ttys.mkdir()

    def add(self, pid, ppid, comm="claude", argv=("claude",), cpu_ticks=0, start=1000, rss_pages=25600, tty_idle_h=None,
            cwd="/home/u/repo"):
        d = self.root / str(pid)
        d.mkdir()
        (d / "comm").write_text(comm + "\n")
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        fields = ["S", str(ppid)] + ["0"] * 9 + [str(cpu_ticks), "0"] + ["0"] * 6 + [str(start), "0", str(rss_pages)]
        (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n")
        (d / "fd").mkdir()
        if tty_idle_h is not None:
            tty = self.ttys / str(pid)
            tty.write_text("")
            os.utime(tty, (NOW - tty_idle_h * HOUR, NOW - tty_idle_h * HOUR))
            os.symlink(tty, d / "fd" / "0")
        else:
            os.symlink("pipe:[1]", d / "fd" / "0")
        os.symlink(cwd, d / "cwd")
        return d

    def set_cpu(self, pid, ticks):
        st = (self.root / str(pid) / "stat").read_text().split()
        st[2 + 11] = str(ticks)
        (self.root / str(pid) / "stat").write_text(" ".join(st) + "\n")

    def remove(self, pid):
        import shutil
        shutil.rmtree(self.root / str(pid))


def _tmux(mapping):
    def runner(cmd):
        return "\n".join(f"{pid} {name}" for pid, name in mapping.items())
    return runner


@pytest.fixture
def fp(tmp_path):
    return FakeProc(tmp_path)


def _scan(fp, state, now=NOW, runner=None):
    return {s["pid"]: s for s in R.scan(fp.root, now, state, dict(R.DEFAULT_CONFIG), runner or _tmux({}))}


def test_only_interactive_claude_is_listed(fp):
    fp.add(10, 1, comm="bash", argv=("bash",))
    fp.add(11, 10, tty_idle_h=1)
    fp.add(12, 10, argv=("claude", "-p", "--resume", "x"), tty_idle_h=99)  # 비대화 실행(봇·재개기)은 제외
    fp.add(13, 10, argv=("claude", "--print", "hi"), tty_idle_h=99)
    assert set(_scan(fp, {})) == {11}


def test_idle_needs_both_old_input_and_flat_cpu_over_the_window(fp):
    fp.add(20, 1, tty_idle_h=30, cpu_ticks=1000)   # 입력 30시간 없음, CPU 그대로 → 놀고 있음
    fp.add(21, 1, tty_idle_h=30, cpu_ticks=1000)   # 입력 없음, 그런데 혼자 일함 → working
    fp.add(22, 1, tty_idle_h=2, cpu_ticks=1000)    # 최근 입력 → active
    state = {}
    first = _scan(fp, state, now=NOW - 2 * HOUR)
    assert first[20]["status"] == "measuring" and first[22]["status"] == "active"
    fp.set_cpu(21, 1000 + 100 * 60)  # 60초 증가
    later = _scan(fp, state, now=NOW)
    assert later[20]["status"] == "idle"
    assert later[21]["status"] == "working"
    assert later[22]["status"] == "active"


def test_child_cpu_counts_as_work_and_rss_sums_the_tree(fp):
    fp.add(30, 1, tty_idle_h=50, cpu_ticks=0, rss_pages=25600)  # 100MB
    fp.add(31, 30, comm="node", argv=("node", "mcp"), cpu_ticks=0, rss_pages=12800)  # 자식 50MB
    state = {}
    _scan(fp, state, now=NOW - 2 * HOUR)
    fp.set_cpu(31, 100 * 30)  # 자식이 30초 일함(명령 실행 중)
    s = _scan(fp, state)[30]
    assert s["status"] == "working"
    assert s["rss_mb"] == pytest.approx(150.0, abs=0.5)


def test_tmux_session_is_found_through_the_pane_shell(fp):
    fp.add(40, 1, comm="bash", argv=("bash",))
    fp.add(41, 40, tty_idle_h=1)
    assert _scan(fp, {}, runner=_tmux({40: "notion"}))[41]["tmux"] == "notion"


def test_choose_closures_respects_requests_auto_switch_and_exclusions():
    sessions = [{"key": "1-1", "status": "idle"}, {"key": "2-2", "status": "idle"}, {"key": "3-3", "status": "active"},
                {"key": "4-4", "status": "working"}]
    assert R.choose_closures(sessions, {}, {}) == []  # 자동 정리는 기본 꺼짐
    picked = R.choose_closures(sessions, {"auto_close": True, "sessions": {"2-2": {"exclude": True}}}, {"3-3": {}})
    assert [(s["key"], why) for s, why in picked] == [("1-1", "auto"), ("3-3", "requested")]


def test_close_verifies_identity_then_term_then_kill(fp):
    fp.add(50, 1, tty_idle_h=40, start=777)
    sent = []

    def kill(pid, sig):
        sent.append((pid, sig))
        if sig == signal.SIGTERM and pid == 50 and len(sent) == 1:
            pass  # 무시하는 프로세스 흉내 → SIGKILL 까지 간다

    s = {"pid": 50, "start": 777}
    assert R.close_session(fp.root, s, grace=1.0, kill=kill, sleep=lambda _: None) == "killed"
    assert sent == [(50, signal.SIGTERM), (50, signal.SIGKILL)]

    sent.clear()
    assert R.close_session(fp.root, {"pid": 50, "start": 999}, grace=1.0, kill=kill, sleep=lambda _: None) == "mismatch"
    assert R.close_session(fp.root, {"pid": 51, "start": 1}, grace=1.0, kill=kill, sleep=lambda _: None) == "gone"
    assert sent == []  # 다른 프로세스·없는 프로세스에는 신호를 보내지 않는다


def test_run_once_closes_requested_session_records_history_and_notifies(fp, tmp_path):
    fp.add(60, 1, tty_idle_h=3, start=5)
    fp.add(61, 1, tty_idle_h=80, start=6)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "requests.json").write_text(json.dumps({"60-5": {"requested_at": "x"}, "999-1": {}}))
    killed, sent = [], []

    def kill(pid, sig):
        killed.append((pid, sig))
        fp.remove(pid)  # SIGTERM 에 바로 종료

    out = R.run_once(proc=fp.root, state_dir=state_dir, now=NOW, runner=_tmux({}), kill=kill, sleep=lambda _: None,
                     notify=sent.append)
    assert killed == [(60, signal.SIGTERM)]
    assert [s["pid"] for s in out["sessions"]] == [61]
    assert out["history"][0]["reason"] == "requested" and out["history"][0]["result"] == "closed"
    assert json.loads((state_dir / "requests.json").read_text()) == {}  # 처리한 요청·사라진 세션 요청은 지움
    assert len(sent) == 1 and "1개 닫음" in sent[0] and "claude --resume" in sent[0]
    saved = json.loads((state_dir / "state.json").read_text())
    assert saved["totals"]["sessions"] == 1


def test_dry_run_never_signals_or_writes(fp, tmp_path):
    fp.add(70, 1, tty_idle_h=3, start=5)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "requests.json").write_text(json.dumps({"70-5": {}}))
    out = R.run_once(proc=fp.root, state_dir=state_dir, now=NOW, dry_run=True, runner=_tmux({}),
                     kill=lambda *a: pytest.fail("signal sent in dry-run"), notify=lambda m: pytest.fail("notified"))
    assert out["sessions"][0]["pid"] == 70
    assert not (state_dir / "state.json").exists()


def test_auto_close_only_idle_and_not_excluded(fp, tmp_path):
    fp.add(80, 1, tty_idle_h=50, start=1)
    fp.add(81, 1, tty_idle_h=50, start=2)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "toggles.json").write_text(json.dumps({"auto_close": True, "sessions": {"81-2": {"exclude": True}}}))
    killed = []

    def kill(pid, sig):
        killed.append(pid)
        fp.remove(pid)

    common = dict(proc=fp.root, state_dir=state_dir, runner=_tmux({}), kill=kill, sleep=lambda _: None, notify=lambda m: None)
    R.run_once(now=NOW - 2 * HOUR, **common)  # 첫 회차: CPU 재는 중이라 닫지 않음
    assert killed == []
    out = R.run_once(now=NOW, **common)
    assert killed == [80]
    assert out["history"][0]["reason"] == "auto"
    assert [s["pid"] for s in out["sessions"]] == [81]


# --- 관제 화면 ---------------------------------------------------------------------------------------------------


@pytest.fixture
def page(tmp_path, monkeypatch):
    from hub import idle_sessions_page as p
    monkeypatch.setattr(p, "STATE_DIR", tmp_path / "reaper")
    return p


def test_page_requests_and_toggles_round_trip(page):
    page.request_close("12-34")
    page.set_exclude("12-34", True)
    page.set_auto(True)
    d = page.collect()
    assert "12-34" in d["requests"] and "12-34" in d["excluded"] and d["auto_close"] is True
    page.cancel_close("12-34")
    page.set_exclude("12-34", False)
    page.set_auto(False)
    d = page.collect()
    assert d["requests"] == {} and d["excluded"] == set() and d["auto_close"] is False


def test_page_renders_sessions_and_badge(page):
    page.STATE_DIR.mkdir(parents=True)
    (page.STATE_DIR / "state.json").write_text(json.dumps({
        "updated_at": "2026-11-15T01:00:00+00:00", "config": {"idle_hours": 24, "cpu_window_minutes": 60, "cpu_idle_seconds": 10},
        "totals": {"sessions": 2, "rss_mb": 600, "idle": 1, "idle_rss_mb": 300},
        "sessions": [{"key": "1-2", "pid": 1, "user": "ubuntu", "cwd": "/srv/x", "tmux": "9", "args": "", "rss_mb": 300,
                      "status": "idle", "input_idle_hours": 72.0, "cpu_growth_window": 0.4},
                     {"key": "3-4", "pid": 3, "user": "ubuntu", "cwd": "/srv/y", "tmux": None, "args": "--resume", "rss_mb": 300,
                      "status": "active", "input_idle_hours": 0.2, "cpu_growth_window": None}],
        "history": [{"at": "2026-11-15T00:00:00+00:00", "reason": "auto", "result": "closed", "cwd": "/srv/z", "tmux": None,
                     "rss_mb": 250}]}))
    d = page.collect()
    body = page.render_body(d)
    assert "놀고 있음" in body and "tmux <b>9</b>" in body and "3.0일 전" in body and "/idle-sessions/close" in body
    assert "최근 닫은 세션" in body
    assert "놀고 있음 1" in page.card_badge(d)
