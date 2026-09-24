"""스케줄러 잡 4개(alpaca_verification_bootstrap, cost_calibration_refresh, variant_shadow_record,
strategy_research_report): 비활성 즉시 리턴, 예외 시 report_job_failure, 없는 모듈(ImportError) 격리, 등록 표 일치.
모든 외부 호출은 mock, 실제 네트워크·주문 없음."""
import inspect
import re
import sys
from types import ModuleType

import pytest

from core.job_schedule import SCHEDULED_JOBS, SCHEDULED_JOBS_BY_ID
from core.process_registry import PROCESS_REGISTRY
from scheduler import run_scheduler

NEW_JOBS = {
    "alpaca_verification_bootstrap": run_scheduler.alpaca_verification_bootstrap_job,
    "cost_calibration_refresh": run_scheduler.cost_calibration_refresh_job,
    "variant_shadow_record": run_scheduler.variant_shadow_record_job,
    "strategy_research_report": run_scheduler.strategy_research_report_job,
}
LAZY = {  # 관측 전용 잡 -> (모듈, 함수)
    "cost_calibration_refresh": ("core.cost_calibration", "refresh_cost_calibration"),
    "variant_shadow_record": ("core.strategy_variants", "record_variant_shadow"),
    "strategy_research_report": ("core.strategy_variants", "write_research_report"),
}


@pytest.fixture
def failures(monkeypatch):
    recorded = []
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda job_id, err: recorded.append((job_id, str(err))))
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    return recorded


def _fake_module(monkeypatch, module_name, func_name, fn):
    mod = ModuleType(module_name)
    setattr(mod, func_name, fn)
    monkeypatch.setitem(sys.modules, module_name, mod)


# ---- 비활성 -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("job_id", NEW_JOBS)
def test_disabled_job_returns_immediately_without_any_work(monkeypatch, job_id):
    asked = []
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: asked.append(key) or False)
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda *a: pytest.fail("must not report"))

    def boom(*a, **k):
        raise AssertionError("work executed although disabled")
    import core.alpaca_verification as av
    monkeypatch.setattr(av, "run_bootstrap_if_needed", boom)
    for name, (module, func) in LAZY.items():
        _fake_module(monkeypatch, module, func, boom)
    NEW_JOBS[job_id]()
    assert asked == [job_id]


# ---- 부트스트랩 ---------------------------------------------------------------------------------------

def test_bootstrap_job_calls_core_once_and_reports_nothing_on_success(monkeypatch, failures):
    import core.alpaca_verification as av
    calls = []
    monkeypatch.setattr(av, "run_bootstrap_if_needed", lambda: calls.append(1) or {"action": "skipped_recent_pass"})
    run_scheduler.alpaca_verification_bootstrap_job()
    assert calls == [1] and failures == []


def test_bootstrap_job_exception_goes_to_report_job_failure_without_raising(monkeypatch, failures):
    import core.alpaca_verification as av

    def boom():
        raise RuntimeError("network exploded")
    monkeypatch.setattr(av, "run_bootstrap_if_needed", boom)
    run_scheduler.alpaca_verification_bootstrap_job()
    assert len(failures) == 1 and failures[0][0] == "alpaca_verification_bootstrap"
    assert "RuntimeError" in failures[0][1] and "network exploded" in failures[0][1]


# ---- 관측 전용 3종 --------------------------------------------------------------------------------------

@pytest.mark.parametrize("job_id", LAZY)
def test_observation_job_calls_its_function_and_reports_nothing_on_success(monkeypatch, failures, job_id):
    module, func = LAZY[job_id]
    calls = []
    _fake_module(monkeypatch, module, func, lambda: calls.append(1) or {"ok": True})
    NEW_JOBS[job_id]()
    assert calls == [1] and failures == []


@pytest.mark.parametrize("job_id", LAZY)
def test_missing_module_is_isolated_as_a_reported_failure(monkeypatch, failures, job_id):
    module, _ = LAZY[job_id]
    monkeypatch.setitem(sys.modules, module, None)          # makes `import` raise ImportError
    NEW_JOBS[job_id]()                                      # must not raise
    assert len(failures) == 1 and failures[0][0] == job_id and re.match(r"(ModuleNotFound|Import)Error", failures[0][1])


@pytest.mark.parametrize("job_id", LAZY)
def test_function_exception_is_reported_not_raised(monkeypatch, failures, job_id):
    module, func = LAZY[job_id]

    def boom():
        raise ValueError("bad data")
    _fake_module(monkeypatch, module, func, boom)
    NEW_JOBS[job_id]()
    assert failures == [(job_id, "ValueError: bad data")]


def test_one_missing_module_does_not_affect_the_other_jobs(monkeypatch, failures):
    monkeypatch.setitem(sys.modules, "core.cost_calibration", None)
    calls = []
    _fake_module(monkeypatch, "core.strategy_variants", "record_variant_shadow", lambda: calls.append(1))
    run_scheduler.cost_calibration_refresh_job()
    run_scheduler.variant_shadow_record_job()
    assert calls == [1] and [f[0] for f in failures] == ["cost_calibration_refresh"]


def test_new_jobs_never_touch_the_order_path():
    for fn in NEW_JOBS.values():
        src = inspect.getsource(fn)
        assert "paper_execution" not in src and "champion_paper_trade" not in src and "submit_plan" not in src


# ---- 등록 표 / 레지스트리 -------------------------------------------------------------------------------

def test_jobs_are_in_schedule_table_with_matching_process_keys():
    for job_id in NEW_JOBS:
        job = SCHEDULED_JOBS_BY_ID[job_id]
        assert job.process_key == job_id and job_id in PROCESS_REGISTRY
        assert job.cron["timezone"] == "Asia/Seoul"


def test_new_slots_are_after_0040_kst_and_do_not_collide_with_other_jobs():
    def slot(job):
        c = job.cron
        return (c.get("day_of_week"), c["hour"], c["minute"], c["timezone"])
    new = {jid: SCHEDULED_JOBS_BY_ID[jid] for jid in NEW_JOBS}
    for job in new.values():
        assert (job.cron["hour"], job.cron["minute"]) >= (0, 40)
    others = [slot(j) for j in SCHEDULED_JOBS if j.job_id not in NEW_JOBS]
    for job in new.values():
        s = slot(job)
        assert s not in others
        # 매일 도는 잡은 같은 시각의 요일 지정 잡과도 겹치지 않게 (분 단위로 유일)
        assert all((o[1], o[2]) != (s[1], s[2]) for o in others if o[3] == "Asia/Seoul")
    assert len({slot(j) for j in new.values()}) == 4
    assert SCHEDULED_JOBS_BY_ID["strategy_research_report"].cron["day_of_week"] == "sun"       # 주 1회


@pytest.mark.parametrize("job_id", list(LAZY))
def test_observation_jobs_registry_entries(job_id):
    entry = PROCESS_REGISTRY[job_id]
    assert entry["category"] == "research" and entry["default_enabled"] is True
    assert "관측 전용" in entry["description"]


def test_bootstrap_registry_entry_states_read_only_and_no_orders():
    entry = PROCESS_REGISTRY["alpaca_verification_bootstrap"]
    assert entry["default_enabled"] is True
    assert "주문을 내지 않" in entry["description"]


def test_each_new_job_function_has_matching_is_enabled_guard():
    for job_id, fn in NEW_JOBS.items():
        assert re.search(rf'is_enabled\(\s*"{re.escape(job_id)}"\s*\)', inspect.getsource(fn))
