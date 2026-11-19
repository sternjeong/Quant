"""hub/proc_control.py 검증 — 가짜 /proc 로 1초 측정, 보호 규칙, 조작 경로(도우미 없음)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hub import proc_control as pc


def _fake_proc(root: Path, procs: dict[int, tuple[str, str, int, str]], cpu=(1000, 800)) -> None:
    """procs: pid -> (comm, state, ticks, cmdline)."""
    root.mkdir(exist_ok=True)
    total, idle = cpu
    (root / "stat").write_text(f"cpu  {total - idle} 0 0 {idle} 0 0 0 0 0 0\n")
    (root / "meminfo").write_text("MemTotal:       12000000 kB\nMemAvailable:    3000000 kB\n")
    for pid, (comm, state, ticks, cmd) in procs.items():
        d = root / str(pid)
        d.mkdir(exist_ok=True)
        fields = [state, "1"] + ["0"] * 9 + [str(ticks), "0"] + ["0"] * 6 + ["100", "0", "2560"]
        (d / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields) + "\n")
        (d / "cmdline").write_bytes(cmd.replace(" ", "\0").encode())


def test_sample_measures_current_cpu(tmp_path, monkeypatch):
    root = tmp_path / "proc"
    me = os.getuid()
    monkeypatch.setattr(pc, "_uids", lambda: {me: "quant"})
    _fake_proc(root, {10: ("python3", "R", 100, "python3 make_dataset.py"), 11: ("node", "S", 50, "node idle.js"),
                      12: ("python3", "T", 5, "python3 paused.py")})
    real_sleep = time.sleep

    def fake_sleep(_):
        _fake_proc(root, {10: ("python3", "R", 190, "python3 make_dataset.py"), 11: ("node", "S", 51, "node idle.js"),
                          12: ("python3", "T", 5, "python3 paused.py")}, cpu=(1200, 820))
    monkeypatch.setattr(pc.time, "sleep", fake_sleep)
    data = pc.sample(1.0, proc=root)
    monkeypatch.setattr(pc.time, "sleep", real_sleep)
    rows = {r["pid"]: r for r in data["rows"]}
    tick = os.sysconf("SC_CLK_TCK")
    assert rows[10]["cpu"] == pytest.approx(90 * 100 / tick)
    assert data["rows"][0]["pid"] == 10  # 지금 가장 많이 쓰는 것이 맨 위
    assert rows[12]["paused"] and not rows[10]["paused"]
    assert data["cpu_busy"] == pytest.approx(90.0)
    assert data["mem_avail"] == pytest.approx(3000000 / 1024 / 1024)


def test_rules_come_from_the_helper_file():
    assert pc.RULES.SIGNALS.keys() == {"STOP", "CONT", "TERM", "KILL"}
    assert "nginx" in pc.RULES.PROTECTED_COMM
    assert pc.RULES.check(1) != ""                      # pid 1 / root 프로세스는 거부
    assert "없는 프로세스" in pc.RULES.check(999999999)


def test_send_without_helper_pauses_and_resumes_own_process(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "helper_available", lambda: False)
    monkeypatch.setattr(pc, "LOG_PATH", tmp_path / "log")
    monkeypatch.setattr(pc.RULES, "ALLOWED_USERS", pc.RULES.ALLOWED_USERS + (os.environ.get("USER") or "",))
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        res = pc.send("STOP", [child.pid])
        if res and not res[0][1] and "계정" in res[0][2]:
            pytest.skip("test user not in ALLOWED_USERS on this machine")
        assert res == [(child.pid, True, "ok")]
        time.sleep(0.2)
        assert Path(f"/proc/{child.pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "T"
        assert pc.send("CONT", [child.pid])[0][1]
        assert "STOP" in (tmp_path / "log").read_text()
    finally:
        child.kill()


def test_send_refuses_bad_input(monkeypatch):
    monkeypatch.setattr(pc, "helper_available", lambda: False)
    assert pc.send("HUP", [123]) == []
    assert pc.send("STOP", []) == []
    assert not pc.send("STOP", [1])[0][1]


def test_summarize():
    assert pc.summarize("STOP", []) == "대상 프로세스가 없습니다."
    assert pc.summarize("STOP", [(1, True, "ok"), (2, False, "보호 프로세스(sshd)")]).startswith("일시정지 1개 완료 · 실패 1개")


def test_render_body_and_badge(monkeypatch):
    monkeypatch.setattr(pc, "helper_available", lambda: False)
    data = {"rows": [{"pid": 10, "user": "ubuntu", "comm": "python3", "state": "R", "ticks": 0, "start": 0, "rss_mb": 170,
                      "cpu": 92.0, "cmd": "python3 make_dataset.py", "what": "python3", "protected": "", "paused": False},
                     {"pid": 11, "user": "quant", "comm": "python3", "state": "T", "ticks": 0, "start": 0, "rss_mb": 50,
                      "cpu": 0.0, "cmd": "python3 x.py", "what": "연구 작업", "protected": "", "paused": True}],
            "cpu_busy": 99.0, "ncpu": 2, "load": (3.2, 3.0, 2.5), "mem_total": 11.6, "mem_avail": 2.4}
    html = pc.render_body(data=data)
    assert 'class="verdict bad"' in html and "도우미 설치 필요" in html  # ubuntu 프로세스는 도우미 없이는 막음
    assert 'name="sig" value="CONT"' in html                            # 일시정지된 quant 프로세스는 재개 버튼
    assert "무거운 작업 전부 일시정지 (1개)" in html
    assert pc.card_badge()


def test_annotate_shows_folder_branch_parent_and_tmux_panes(tmp_path, monkeypatch):
    repo = tmp_path / "repos" / "worktrees" / "Quant-x"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/feature-a\n")
    folders = {20: str(repo / "sub"), 30: str(repo), 31: "/srv/contests/coin-arb", 32: "/opt/quant"}
    (repo / "sub").mkdir()
    monkeypatch.setattr(pc, "HOME", str(tmp_path))
    monkeypatch.setattr(pc, "cwds", lambda pids, proc=None: {p: folders[p] for p in pids if p in folders})
    root = tmp_path / "proc"
    root.mkdir()
    (root / "uptime").write_text("100000.0 1.0\n")
    tick = os.sysconf("SC_CLK_TCK")

    def r(pid, ppid, comm, cmd, start=0):
        return {"pid": pid, "ppid": ppid, "user": "ubuntu", "comm": comm, "cmd": cmd, "start": start}
    procs = {p["pid"]: p for p in [
        r(5, 1, "tmux: server", "tmux new -s use"),
        r(10, 5, "claude", "claude --resume -n p12cards do things"),
        r(20, 10, "python3", "python3 train.py", start=int((100000 - 7500) * tick)),
        r(30, 5, "bash", "-bash"), r(31, 5, "bash", "-bash"), r(32, 5, "bash", "-bash")]}
    rows = [procs[20], procs[5]]
    pc.annotate(rows, procs, root)
    ctx = procs[20]["context"]
    assert "~/repos/worktrees/Quant-x/sub (작업 폴더 Quant-x)" in ctx and "브랜치 feature-a" in ctx
    assert "2시간 5분째" in ctx and "Claude 세션 'p12cards'(pid 10)이 실행" in ctx and "tmux 안" in ctx
    tmux = procs[5]["context"]
    assert "tmux 창 4개" in tmux and "AI 대회 coin-arb" in tmux and "Quant 엔진(배포본)" in tmux
    html = pc._row({**procs[20], "cpu": 40.0, "rss_mb": 100, "what": "python3", "protected": "", "paused": False}, True)
    assert "브랜치 feature-a" in html and "python3 train.py" in html and "작업 폴더 Quant-x" in html


def test_helper_info_prints_cwd_for_allowed_users_only():
    me = os.environ.get("USER") or ""
    out = pc.RULES.info(os.getpid())
    if me not in pc.RULES.ALLOWED_USERS:
        assert "거부" in out
    else:
        assert out == f"{os.getpid()} cwd {os.getcwd()}"
    assert "거부" in pc.RULES.info(1)
