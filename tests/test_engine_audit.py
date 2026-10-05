"""주간 엔진 점검(core/engine_audit.py) — 항목별로 '고장'을 제대로 잡는지, 한 항목이 깨져도 나머지가 도는지, 잡 등록."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from core import engine_audit as ea

NOW = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)  # 월요일 09:00 KST


def test_services_detects_stopped_unit(monkeypatch):
    monkeypatch.setattr(ea.shutil, "which", lambda name: "/bin/systemctl")
    fake = lambda cmd, **k: SimpleNamespace(stdout="inactive" if cmd[-1] == "quant-hub" else "active")  # noqa: E731
    r = ea.check_services(run=fake)
    assert r["status"] == ea.FAIL and "quant-hub=inactive" in r["detail"]


def test_deploy_sync(tmp_path):
    same = lambda cmd, **k: SimpleNamespace(stdout="abc1234def")  # noqa: E731
    assert ea.check_deploy_sync(run=same, root=tmp_path)["status"] == ea.OK
    diff = lambda cmd, **k: SimpleNamespace(stdout="aaa1111" if cmd[-1] == "HEAD" else "bbb2222")  # noqa: E731
    r = ea.check_deploy_sync(run=diff, root=tmp_path)
    assert r["status"] == ea.WARN and "aaa1111" in r["detail"]


def test_research_runner(tmp_path):
    p = tmp_path / "state.json"
    assert ea.check_research_runner(NOW, p)["status"] == ea.WARN  # 상태 파일 없음
    p.write_text(json.dumps({"runner": {"last_tick_at": (NOW - timedelta(days=3)).isoformat()}, "jobs": {}}))
    assert ea.check_research_runner(NOW, p)["status"] == ea.FAIL  # 3일째 안 깨어남
    p.write_text(json.dumps({"runner": {"last_tick_at": (NOW - timedelta(hours=2)).isoformat()},
                             "jobs": {"a": {"status": "done"}, "b": {"status": "failed"}}}))
    r = ea.check_research_runner(NOW, p)
    assert r["status"] == ea.FAIL and "b" in r["detail"]
    p.write_text(json.dumps({"runner": {"last_tick_at": (NOW - timedelta(hours=2)).isoformat()}, "jobs": {"a": {"status": "done"}}}))
    assert ea.check_research_runner(NOW, p)["status"] == ea.OK


def test_satellite_lab_flags_polluted_rounds(tmp_path):
    from core import satellite_lab as sl

    state, variants = tmp_path / "state", tmp_path / "variants"
    spec = {"id": sl.INCUMBENT_ID, "parent": None, "title": "t", "thesis": "t", "source": "s", "pool": {"type": "champion40"},
            "signal": {"params_grid": [{}]}, "portfolio": {"top_k": 3, "hold_months": 6}, "exit": {"type": "none"}}
    sl.freeze(spec, "def score(prices, as_of, params):\n    return {}\n", "seed", state_dir=state)
    with sl.edit_registry(state) as reg:
        reg["incumbent"] = {"random_percentile_is": 0.9}
    (variants / "S-20261005-001").mkdir(parents=True)
    sl.save_agent_state("S-20261005-001", {"rounds": 7}, state)
    r = ea.check_satellite_lab(NOW, state, variants)
    assert r["status"] == ea.WARN and "S-20261005-001(설계 7회)" in r["detail"]
    sl.save_agent_state("S-20261005-001", {"rounds": 2}, state)
    assert ea.check_satellite_lab(NOW, state, variants)["status"] == ea.OK


def test_agent_batch(tmp_path):
    log = tmp_path / "usage.jsonl"
    assert ea.check_agent_batch(NOW, log)["status"] == ea.FAIL  # 7일 동안 0건
    rows = []
    for d in range(7):
        at = (NOW - timedelta(days=d, hours=6)).astimezone(ea.KST).isoformat()
        rows += [{"at": at, "role": "scout", "ok": True, "cost_usd": 0.1},
                 {"at": at, "role": "sat_designer", "ok": True, "cost_usd": 2.0}]
    log.write_text("\n".join(json.dumps(r) for r in rows))
    assert ea.check_agent_batch(NOW, log)["status"] == ea.OK
    rows = [dict(r, ok=False) if r["role"] == "sat_designer" else r for r in rows]
    log.write_text("\n".join(json.dumps(r) for r in rows))
    r = ea.check_agent_batch(NOW, log)
    assert r["status"] == ea.WARN and "실패" in r["detail"]


def test_daily_recommendation_counts_only_since_version_start(monkeypatch):
    from core import champion_recommendation as cr

    def rows(dates):
        return [{"params": {"as_of": d}} for d in dates]

    days = [(NOW.date() - timedelta(days=i)).isoformat() for i in range(1, 8)]
    monkeypatch.setattr(cr, "list_cached", lambda cache_dir=None: rows(days))
    assert ea.check_daily_recommendation(NOW)["status"] == ea.OK
    monkeypatch.setattr(cr, "list_cached", lambda cache_dir=None: rows(days[:2]))  # 버전이 2일 전 바뀜 → 그 전은 세지 않음
    assert ea.check_daily_recommendation(NOW)["status"] == ea.OK
    monkeypatch.setattr(cr, "list_cached", lambda cache_dir=None: rows([days[0], days[4]]))
    r = ea.check_daily_recommendation(NOW)
    assert r["status"] == ea.FAIL and "3일" in r["detail"]


def test_run_audit_survives_a_broken_check_and_formats(tmp_path):
    def boom(now):
        raise RuntimeError("깨짐")

    checks = (("가짜 정상", lambda now: ea._c("가짜 정상", ea.OK, "좋음")), ("가짜 고장", boom))
    rep = ea.run_audit(NOW, checks)
    assert rep["overall"] == ea.FAIL and rep["counts"] == {"ok": 1, "warn": 0, "fail": 1}
    msg = ea.format_message(rep)
    assert msg.splitlines()[1].startswith("❌ 가짜 고장") and "점검 자체가 실패" in msg
    path = ea.save(rep, tmp_path)
    assert json.loads(path.read_text())["overall"] == "fail" and (tmp_path / "2026-10-12.json").exists()


def test_job_registered_weekly_monday():
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    job = SCHEDULED_JOBS_BY_ID["engine_weekly_audit"]
    assert job.cron["day_of_week"] == "mon" and (job.cron["hour"], job.cron["minute"]) == (8, 15)
    entry = PROCESS_REGISTRY["engine_weekly_audit"]
    assert entry["default_enabled"] is True and not entry.get("places_orders")
