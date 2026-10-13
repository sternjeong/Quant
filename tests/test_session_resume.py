"""세션 자동 재개(deploy/session_resume/resumer.py)와 관제 화면(hub/session_resume_page.py)."""

from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("session_resumer", ROOT / "deploy" / "session_resume" / "resumer.py")
resumer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resumer)

UTC = timezone.utc
T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def _ts(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _write(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _claude_records(sid: str, *, limited: bool = True, after: list[dict] | None = None, mode: str = "auto") -> list[dict]:
    recs = [
        {"type": "user", "sessionId": sid, "cwd": "/home/u/proj", "permissionMode": mode, "timestamp": _ts(T0 - timedelta(minutes=5)),
         "message": {"role": "user", "content": "테스트를 고쳐줘"}},
        {"type": "assistant", "sessionId": sid, "cwd": "/home/u/proj", "timestamp": _ts(T0 - timedelta(minutes=4)),
         "message": {"role": "assistant", "content": [{"type": "text", "text": "작업 중"}]}},
        {"type": "assistant", "isSidechain": True, "sessionId": sid, "timestamp": _ts(T0 - timedelta(minutes=3)),
         "message": {"content": [{"type": "text", "text": "subagent"}]}},
    ]
    if limited:
        recs.append({"type": "assistant", "sessionId": sid, "cwd": "/home/u/proj", "timestamp": _ts(T0),
                     "isApiErrorMessage": True, "error": "rate_limit",
                     "message": {"content": [{"type": "text", "text": "You've hit your session limit · resets 11:20am (UTC)"}]}})
    recs.append({"type": "ai-title", "aiTitle": "테스트 고치기", "sessionId": sid})
    return recs + (after or [])


def _codex_records(sid: str, *, source="vscode", answered=False, aborted=False, reached=True) -> list[dict]:
    rl = {"primary": {"used_percent": 100.0 if reached else 40.0, "window_minutes": 300, "resets_at": int((T0 + timedelta(hours=2)).timestamp())},
          "secondary": {"used_percent": 20.0, "window_minutes": 10080, "resets_at": int((T0 + timedelta(days=3)).timestamp())},
          "rate_limit_reached_type": None}
    recs = [
        {"timestamp": _ts(T0 - timedelta(minutes=10)), "type": "session_meta", "payload": {"id": sid, "cwd": "/srv/x", "source": source}},
        {"timestamp": _ts(T0 - timedelta(minutes=9)), "type": "turn_context",
         "payload": {"cwd": "/srv/x", "sandbox_policy": {"type": "workspace-write", "network_access": True}, "model": "m1", "effort": "high"}},
        {"timestamp": _ts(T0 - timedelta(minutes=9)), "type": "event_msg", "payload": {"type": "user_message", "message": "모델 학습 이어서"}},
        {"timestamp": _ts(T0 - timedelta(minutes=9)), "type": "event_msg", "payload": {"type": "task_started"}},
        {"timestamp": _ts(T0), "type": "event_msg", "payload": {"type": "token_count", "info": None, "rate_limits": rl}},
    ]
    if answered:
        recs.append({"timestamp": _ts(T0), "type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "끝"}})
    if aborted:
        recs.append({"timestamp": _ts(T0), "type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}})
    return recs


def test_discovers_sessions_for_all_local_accounts(tmp_path, monkeypatch):
    homes = [tmp_path / "first", tmp_path / "second", tmp_path / "empty"]
    _write(homes[0] / ".claude" / "projects" / "p" / "s1.jsonl", _claude_records("s1"))
    _write(homes[1] / ".codex" / "sessions" / "2026" / "rollout-c1.jsonl", _codex_records("c1"))
    homes[2].mkdir()
    entries = [SimpleNamespace(pw_name=name, pw_dir=str(home)) for name, home in zip(("first", "second", "empty"), homes)]
    monkeypatch.setattr(resumer.pwd, "getpwall", lambda: entries)
    cfg = dict(resumer.DEFAULT_CONFIG)
    assert [a["user"] for a in resumer.discover_accounts(cfg)] == ["first", "second"]
    found = resumer.discover(cfg, T0 + timedelta(minutes=1))
    assert {e["key"] for e in found} == {"claude:first:s1", "codex:second:c1"}


# --------------------------------------------------------------------------- 초기화 시각
@pytest.mark.parametrize("text,expected", [
    ("You've hit your session limit · resets 11:20am (UTC)", datetime(2026, 10, 5, 11, 20, tzinfo=UTC)),
    ("You've hit your session limit · resets 2pm (UTC)", datetime(2026, 10, 5, 14, 0, tzinfo=UTC)),
    ("You've hit your session limit · resets 6:10am (UTC)", datetime(2026, 10, 6, 6, 10, tzinfo=UTC)),  # 이미 지난 시각 → 다음날
    ("You've hit your weekly limit · resets Oct 9, 1am (UTC)", datetime(2026, 10, 9, 1, 0, tzinfo=UTC)),
    ("You've hit your session limit · resets 7pm (Asia/Seoul)", datetime(2026, 10, 5, 10, 0, tzinfo=UTC)),
    ("API Error: 529 Overloaded", None),
])
def test_parse_claude_reset(text, expected):
    assert resumer.parse_claude_reset(text, T0) == expected


# --------------------------------------------------------------------------- Claude 판정
def test_scan_claude_detects_limit_stop(tmp_path):
    info = resumer.scan_claude(_write(tmp_path / "s1.jsonl", _claude_records("s1")))
    assert info["session_id"] == "s1" and info["cwd"] == "/home/u/proj" and info["mode"] == "auto"
    assert info["title"] == "테스트 고치기"
    assert info["reset_at"] == datetime(2026, 10, 5, 11, 20, tzinfo=UTC)


def test_scan_claude_ignores_continued_or_normal_sessions(tmp_path):
    later = [{"type": "user", "sessionId": "s2", "timestamp": _ts(T0 + timedelta(hours=3)), "message": {"content": "계속"}}]
    assert resumer.scan_claude(_write(tmp_path / "s2.jsonl", _claude_records("s2", after=later))) is None
    assert resumer.scan_claude(_write(tmp_path / "s3.jsonl", _claude_records("s3", limited=False))) is None


def test_scan_claude_ignores_other_api_errors(tmp_path):
    recs = _claude_records("s4", limited=False) + [{"type": "assistant", "timestamp": _ts(T0), "isApiErrorMessage": True,
                                                    "error": "server_error", "message": {"content": [{"type": "text", "text": "529"}]}}]
    assert resumer.scan_claude(_write(tmp_path / "s4.jsonl", recs)) is None


# --------------------------------------------------------------------------- Codex 판정
def test_scan_codex_detects_limit_stop(tmp_path):
    info = resumer.scan_codex(_write(tmp_path / "rollout-a.jsonl", _codex_records("c1")))
    assert info["session_id"] == "c1" and info["cwd"] == "/srv/x" and info["title"] == "모델 학습 이어서"
    assert info["reset_at"] == T0 + timedelta(hours=2)
    assert info["model"] == "m1" and info["sandbox"]["type"] == "workspace-write"


@pytest.mark.parametrize("kwargs", [{"answered": True}, {"aborted": True}, {"reached": False},
                                    {"source": {"subagent": {"other": "guardian"}}}])
def test_scan_codex_ignores_non_stopped(tmp_path, kwargs):
    assert resumer.scan_codex(_write(tmp_path / "rollout-b.jsonl", _codex_records("c2", **kwargs))) is None


def test_scan_codex_error_event(tmp_path):
    recs = _codex_records("c3", reached=False) + [
        {"timestamp": _ts(T0), "type": "event_msg", "payload": {"type": "error", "message": "You've hit your usage limit. Try again later."}}]
    info = resumer.scan_codex(_write(tmp_path / "rollout-c.jsonl", recs))
    assert info and info["reset_at"] is None and "usage limit" in info["reason"]


# --------------------------------------------------------------------------- 명령
def test_build_command_keeps_session_permissions(tmp_path):
    cfg = dict(resumer.DEFAULT_CONFIG, claude_bin="/usr/local/bin/claude", codex_bin={"u": "/bin/codex"})
    claude = resumer.build_command({"backend": "claude", "session_id": "s1", "mode": "default"}, cfg)
    assert claude[:4] == ["/usr/local/bin/claude", "-p", "--resume", "s1"]
    assert claude[claude.index("--permission-mode") + 1] == "manual"
    assert "--dangerously-skip-permissions" not in claude
    codex = resumer.build_command({"backend": "codex", "session_id": "c1", "user": "u", "home": str(tmp_path),
                                   "sandbox": {"type": "workspace-write", "network_access": True}, "model": "m1", "effort": "high"}, cfg)
    assert codex[:3] == ["/bin/codex", "exec", "resume"]
    assert 'sandbox_mode="workspace-write"' in codex and 'approval_policy="never"' in codex
    assert "sandbox_workspace_write.network_access=true" in codex
    assert codex[-2] == "c1" and "--dangerously-bypass-approvals-and-sandbox" not in codex


# --------------------------------------------------------------------------- 회차 흐름
@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(resumer, "STATE_DIR", tmp_path / "state")
    cfg = dict(resumer.DEFAULT_CONFIG, accounts=[{"user": "u", "home": str(home)}], notify=False)
    transcript = _write(home / ".claude" / "projects" / "-home-u-proj" / "s1.jsonl", _claude_records("s1"))
    launched: list[str] = []
    running: set[str] = set()

    def launcher(e, cfg, now, dry_run=False):
        unit = f"unit-{len(launched)}"
        launched.append(e["key"])
        running.add(unit)
        return unit, "시작"

    def run(now):
        return resumer.tick(cfg, now, launcher=launcher, running=lambda u: u in running, notifier=lambda c, t: None)

    return {"run": run, "launched": launched, "running": running, "transcript": transcript, "cfg": cfg, "tmp": tmp_path}


def test_waits_for_reset_then_resumes_and_records(env):
    import os

    os.utime(env["transcript"], (T0.timestamp(), T0.timestamp()))
    state = env["run"](T0 + timedelta(hours=1))  # 초기화(11:20) 전
    e = state["sessions"]["claude:u:s1"]
    assert e["status"] == "waiting" and env["launched"] == []

    state = env["run"](T0 + timedelta(hours=2, minutes=25))  # 초기화 + 여유 지남
    assert state["sessions"]["claude:u:s1"]["status"] == "resuming" and env["launched"] == ["claude:u:s1"]

    state = env["run"](T0 + timedelta(hours=2, minutes=30))  # 아직 실행 중 → 그대로, 중복 실행 없음
    assert state["sessions"]["claude:u:s1"]["status"] == "resuming" and len(env["launched"]) == 1

    env["running"].clear()  # 실행 끝, 세션이 정상 답변으로 이어짐
    _write(env["transcript"], _claude_records("s1", after=[
        {"type": "user", "timestamp": _ts(T0 + timedelta(hours=3)), "message": {"content": "[자동 재개]"}},
        {"type": "assistant", "timestamp": _ts(T0 + timedelta(hours=3)), "message": {"content": [{"type": "text", "text": "완료"}]}}]))
    state = env["run"](T0 + timedelta(hours=3, minutes=5))
    assert state["sessions"] == {}
    assert state["history"][0]["status"] == "resumed"
    saved = json.loads((env["tmp"] / "state" / "state.json").read_text(encoding="utf-8"))
    assert saved["history"][0]["key"] == "claude:u:s1"


def test_session_toggle_off_and_master_off_block_resume(env):
    tdir = env["tmp"] / "state"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "toggles.json").write_text(json.dumps({"sessions": {"claude:u:s1": {"enabled": False}}}), encoding="utf-8")
    state = env["run"](T0 + timedelta(hours=3))
    assert state["sessions"]["claude:u:s1"]["status"] == "off" and env["launched"] == []

    (tdir / "toggles.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    state = env["run"](T0 + timedelta(hours=3))
    assert state["enabled"] is False and env["launched"] == []

    (tdir / "toggles.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    state = env["run"](T0 + timedelta(hours=3))
    assert state["sessions"]["claude:u:s1"]["status"] == "resuming"


def test_limit_again_waits_for_next_reset_and_gives_up_after_max(env):
    env["run"](T0 + timedelta(hours=3))
    env["running"].clear()
    # 재개 중 다시 한도(새 멈춤 시각)
    again = _claude_records("s1")
    again[-2] = dict(again[-2], timestamp=_ts(T0 + timedelta(hours=3, minutes=10)))
    _write(env["transcript"], again)
    state = env["run"](T0 + timedelta(hours=3, minutes=15))
    e = state["sessions"]["claude:u:s1"]
    assert e["status"] == "waiting" and "다시 한도" in e["note"]
    # 같은 멈춤에서 실행이 계속 실패하면 max_attempts 뒤 포기
    now = T0 + timedelta(days=1, hours=2, minutes=30)
    for _ in range(6):
        env["running"].clear()
        state = env["run"](now)
        now += timedelta(hours=1)
    assert state["sessions"]["claude:u:s1"]["status"] == "gave_up"
    assert len(env["launched"]) == env["cfg"]["max_attempts"]


def test_old_stops_are_not_woken(env):
    state = env["run"](T0 + timedelta(days=3))
    assert state["sessions"]["claude:u:s1"]["status"] == "expired" and env["launched"] == []


def test_dry_run_writes_nothing(env):
    resumer.tick(env["cfg"], T0 + timedelta(hours=3), dry_run=True)
    assert not (env["tmp"] / "state" / "state.json").exists()


# --------------------------------------------------------------------------- 관제 화면
def test_hub_page_toggles_and_render(tmp_path, monkeypatch):
    from hub import session_resume_page as page

    monkeypatch.setattr(page, "STATE_DIR", tmp_path)
    (tmp_path / "state.json").write_text(json.dumps({"updated_at": "2026-10-05T09:00:00+00:00", "sessions": {
        "claude:u:s1": {"key": "claude:u:s1", "backend": "claude", "user": "u", "session_id": "s1", "cwd": "/home/u/<proj>",
                        "title": "<b>제목</b>", "status": "waiting", "attempts": 0, "stopped_at": "2026-10-05T09:00:00+00:00"}},
        "history": []}), encoding="utf-8")
    data = page.collect()
    assert data["enabled"] is True  # 기록 없으면 켜짐
    body = page.render_body(data)
    assert "&lt;b&gt;제목&lt;/b&gt;" in body and "<b>제목</b>" not in body
    assert 'value="claude:u:s1"' in body and "끄기" in body

    page.set_toggle("claude:u:s1", False)
    page.set_toggle(None, False)
    toggles = json.loads((tmp_path / "toggles.json").read_text(encoding="utf-8"))
    assert toggles["enabled"] is False and toggles["sessions"]["claude:u:s1"]["enabled"] is False
    assert "꺼짐" in page.card_badge(page.collect())
    # 재개기가 같은 파일 형식을 읽는다
    assert resumer.is_enabled(toggles) is False and resumer.is_enabled(toggles, "claude:u:s1") is False
    assert resumer.is_enabled(toggles, "codex:u:other") is True


def test_hub_route_rejects_bad_keys():
    from hub import server

    assert server.SESSION_KEY_RE.fullmatch("claude:ubuntu:75dc5ad4-52c5-420d-9dca-c21efd1520c5")
    assert server.SESSION_KEY_RE.fullmatch("codex:quant:01a10c3f-08e2-7e31-9018-9904d6185e98")
    assert not server.SESSION_KEY_RE.fullmatch("claude:ubuntu:../../etc")
    assert any(s.kind == "session_resume" for s in server.SLOTS)
    assert "세션 자동 재개" in server.render_session_resume_page()
