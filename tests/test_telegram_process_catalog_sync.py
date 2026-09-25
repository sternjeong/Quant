"""텔레그램 /processes 목록이 레지스트리·스케줄 표와 어긋나지 않는지 강제한다.

deploy/codex_telegram/runner.py 는 stdlib-only(시스템 python3)라 core 를 import 하지 않고
core/process_registry.py 를 ast 로 읽는다. 이 테스트는 그 읽기 결과(= 텔레그램이 보여 주는 키)가
PROCESS_REGISTRY 키, core.job_schedule 의 process_key 와 모두 같은지 확인한다. 잡을 추가하면 텔레그램
쪽은 자동으로 따라오고, 레지스트리를 러너가 못 읽는 형태(리터럴이 아닌 식)로 바꾸면 여기서 실패한다.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from core.job_schedule import SCHEDULED_JOBS
from core.process_registry import PROCESS_REGISTRY

RUNNER_PATH = Path(__file__).resolve().parent.parent / "deploy" / "codex_telegram" / "runner.py"


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("telegram_runner_under_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def service(runner, tmp_path):
    svc = runner.Service({"state_dir": str(tmp_path / "state"), "projects": {"quant": str(tmp_path)},
                          "default_project": "quant", "default_backend": "claude"})
    svc.chat = "1"
    return svc


def test_runner_catalog_matches_registry_exactly(runner):
    catalog = runner.load_process_catalog()
    assert [e["key"] for e in catalog] == list(PROCESS_REGISTRY)
    for entry in catalog:
        meta = PROCESS_REGISTRY[entry["key"]]
        assert entry["label"] == meta["label"]
        assert entry["category"] == meta["category"]
        assert entry["default_enabled"] is meta["default_enabled"]
        assert entry["places_orders"] is bool(meta.get("places_orders", False))


def test_runner_keys_equal_registry_keys_equal_schedule_keys(service):
    with service.db() as db:
        _, last_markup = service.process_command(db, "")  # 앞 조각들은 outbox 로, 마지막 조각은 반환값
        rows = [json.loads(r[0]) for r in db.execute("SELECT markup FROM outbox WHERE markup IS NOT NULL")]
    rows.append(last_markup)
    shown = {button["callback_data"].removeprefix("p:")
             for markup in rows for row in markup["inline_keyboard"] for button in row}
    schedule_keys = {job.process_key for job in SCHEDULED_JOBS}
    assert shown == set(PROCESS_REGISTRY) == schedule_keys


def test_every_category_is_grouped_by_the_runner(runner):
    known = {c for c, _ in runner.PROCESS_CATEGORIES}
    assert {meta["category"] for meta in PROCESS_REGISTRY.values()} <= known


def test_order_placing_jobs_are_off_by_default_and_need_confirmation(service):
    order_jobs = [k for k, meta in PROCESS_REGISTRY.items() if meta.get("places_orders")]
    assert "paper_auto_trade" in order_jobs
    for key in order_jobs:
        assert PROCESS_REGISTRY[key]["default_enabled"] is False
        entry, needs_confirm = service.apply_process_toggle(key, True)
        assert needs_confirm is True
        assert service.is_process_enabled(key, entry["default_enabled"]) is False


def test_runner_toggle_file_is_what_the_scheduler_reads(service, monkeypatch):
    from core import process_registry

    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", service.process_toggles_path())
    service.set_process_enabled("guru_holdings_sync", False)
    assert process_registry.is_enabled("guru_holdings_sync") is False
    service.apply_process_toggle("paper_auto_trade", True, confirmed=True)
    assert process_registry.is_enabled("paper_auto_trade") is True
