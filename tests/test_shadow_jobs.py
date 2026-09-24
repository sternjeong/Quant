"""scheduler/run_scheduler.py 의 두 shadow 기록 잡 배선 검증 (guidance_shadow_record, filing_veto_shadow_record).

이 잡들은 관측 전용이다. 검증 대상은 세 가지뿐이다:
    1. is_enabled 가 False 면 기록 함수를 아예 부르지 않고 즉시 리턴한다(꺼진 잡이 몰래 도는 것 방지).
    2. 기록 함수가 예외를 던져도 잡이 죽지 않고 report_job_failure 로 이력에 남긴다(스케줄러 보호).
    3. 잡 함수 소스가 주문 경로 모듈을 import 하지 않는다(shadow 가 주문에 연결될 수 없음).
성과·승률 같은 주장은 하지 않는다.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from scheduler import run_scheduler

JOBS = (
    ("guidance_shadow_record", run_scheduler.guidance_shadow_record_job, "core.guidance_shadow", "record_guidance_shadow"),
    ("filing_veto_shadow_record", run_scheduler.filing_veto_shadow_record_job, "core.filing_veto_shadow", "record_filing_veto_shadow"),
)

FORBIDDEN_PREFIXES = ("core.paper_execution", "scripts.champion_paper_trade")


@pytest.mark.parametrize("process_key,job,module_path,fn_name", JOBS, ids=[j[0] for j in JOBS])
def test_disabled_job_returns_without_calling_the_recorder(process_key, job, module_path, fn_name, monkeypatch, capsys):
    import importlib

    mod = importlib.import_module(module_path)
    called = []
    monkeypatch.setattr(mod, fn_name, lambda *a, **k: called.append(1))
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: False)
    monkeypatch.setattr(
        run_scheduler, "report_job_failure",
        lambda *a, **k: pytest.fail("꺼진 잡이 실패를 보고하면 안 된다"),
    )

    job()

    assert called == []
    assert "건너뜀" in capsys.readouterr().out


@pytest.mark.parametrize("process_key,job,module_path,fn_name", JOBS, ids=[j[0] for j in JOBS])
def test_recorder_exception_is_swallowed_and_reported(process_key, job, module_path, fn_name, monkeypatch):
    import importlib

    mod = importlib.import_module(module_path)

    def boom(*a, **k):
        raise RuntimeError("shadow boom")

    reported = []
    monkeypatch.setattr(mod, fn_name, boom)
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda key, err: reported.append((key, err)))

    job()  # 예외가 새면 APScheduler 잡이 죽고 다음 날 스케줄까지 영향받는다

    assert reported == [(process_key, "RuntimeError: shadow boom")]


@pytest.mark.parametrize("process_key,job,module_path,fn_name", JOBS, ids=[j[0] for j in JOBS])
def test_job_source_never_imports_the_order_path(process_key, job, module_path, fn_name):
    tree = ast.parse(inspect.getsource(job).lstrip())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    bad = [n for n in names if any(n.startswith(p) for p in FORBIDDEN_PREFIXES)]
    assert bad == [], f"주문 경로를 import 하면 안 된다: {bad}"
    assert names == [module_path], f"shadow 기록 모듈만 lazy import 해야 한다: {names}"


@pytest.mark.parametrize("process_key,job,module_path,fn_name", JOBS, ids=[j[0] for j in JOBS])
def test_registry_entry_exists_and_is_observation_only(process_key, job, module_path, fn_name):
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    entry = PROCESS_REGISTRY[process_key]
    assert entry["category"] == "research" and entry["default_enabled"] is True
    assert "주문" in entry["description"]  # 관측 전용이라는 사실이 사용자가 보는 설명에 있어야 한다
    assert SCHEDULED_JOBS_BY_ID[process_key].process_key == process_key


def test_scheduled_times_are_00_30_and_00_32_kst():
    from core.job_schedule import SCHEDULED_JOBS_BY_ID

    assert SCHEDULED_JOBS_BY_ID["guidance_shadow_record"].cron == {
        "hour": 0, "minute": 30, "timezone": "Asia/Seoul"}
    assert SCHEDULED_JOBS_BY_ID["filing_veto_shadow_record"].cron == {
        "hour": 0, "minute": 32, "timezone": "Asia/Seoul"}
