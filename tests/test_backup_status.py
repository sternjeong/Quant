"""core/backup_status.py — status.json → 브리핑/워치독용 판정."""

from __future__ import annotations

import json

from core import backup_status
from core.backup_status import describe_backup, load_backup_status

NOW = 1_800_000_000.0
HOUR = 3600


def _status(**overrides):
    base = {
        "ok": True, "error": None, "push_error": None, "offsite_configured": True,
        "last_success_epoch": NOW - 5 * HOUR, "last_push_success_epoch": NOW - 5 * HOUR,
        "files": 1300, "bytes": 280_000_000, "skipped": [], "quarantined": [],
        "restore_drill_ok": True, "restore_drill_source": "offsite", "last_restore_drill_epoch": NOW - 24 * HOUR,
    }
    base.update(overrides)
    return base


def test_missing_status_file_is_reported_honestly(tmp_path):
    assert load_backup_status(tmp_path / "nope.json") is None
    assert describe_backup(None)["level"] == "none"


def test_load_reads_the_json_and_tolerates_garbage(tmp_path):
    good = tmp_path / "status.json"
    good.write_text(json.dumps(_status()))
    assert load_backup_status(good)["files"] == 1300
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_backup_status(bad) is None


def test_healthy_backup_is_ok():
    result = describe_backup(_status(), NOW)
    assert result["level"] == "ok"
    assert any("push 정상" in line for line in result["lines"])


def test_no_offsite_remote_is_a_warning_not_an_error():
    result = describe_backup(_status(offsite_configured=False, last_push_success_epoch=None), NOW)
    assert result["level"] == "warn"
    assert any("디스크가 사라지면 복구 불가" in line for line in result["lines"])


def test_stale_backup_is_bad():
    result = describe_backup(_status(last_success_epoch=NOW - 40 * HOUR), NOW)
    assert result["level"] == "bad" and any("40시간 전" in line for line in result["lines"])


def test_failed_last_run_is_bad_and_shows_the_error():
    result = describe_backup(_status(ok=False, error="RuntimeError: disk full"), NOW)
    assert result["level"] == "bad" and any("disk full" in line for line in result["lines"])


def test_push_failure_or_long_push_gap_is_bad():
    assert describe_backup(_status(push_error="Permission denied"), NOW)["level"] == "bad"
    assert describe_backup(_status(last_push_success_epoch=NOW - 80 * HOUR), NOW)["level"] == "bad"
    assert describe_backup(_status(last_push_success_epoch=None), NOW)["level"] == "bad"


def test_quarantined_or_skipped_files_warn():
    assert describe_backup(_status(quarantined=[{"path": "docs/x", "reason": "r"}]), NOW)["level"] == "warn"
    assert describe_backup(_status(skipped=[{"path": "a", "size": 1, "reason": "너무 큼"}]), NOW)["level"] == "warn"


def test_never_succeeded_is_bad():
    assert describe_backup(_status(last_success_epoch=None), NOW)["level"] == "bad"


def test_default_path_points_at_the_vm_backup_dir():
    assert str(backup_status.STATUS_PATH).endswith("status.json")


def test_restore_drill_result_is_part_of_the_verdict():
    ok = describe_backup(_status(), NOW)
    assert ok["level"] == "ok" and any("복구 리허설 정상" in line for line in ok["lines"])

    failed = describe_backup(_status(restore_drill_ok=False, restore_drill_error="복구본 검증 실패: 내용 불일치: db/quant.db"), NOW)
    assert failed["level"] == "bad" and any("복구 리허설 실패(offsite)" in line for line in failed["lines"])

    stale = describe_backup(_status(last_restore_drill_epoch=NOW - 15 * 24 * HOUR), NOW)
    assert stale["level"] == "warn" and any("15일째 없음" in line for line in stale["lines"])


def test_offsite_without_any_drill_yet_is_a_warning_but_local_only_is_not_double_counted():
    never = describe_backup(_status(restore_drill_ok=None, last_restore_drill_epoch=None), NOW)
    assert never["level"] == "warn" and any("한 번도 못 했음" in line for line in never["lines"])
    local_only = describe_backup(_status(offsite_configured=False, last_push_success_epoch=None,
                                         restore_drill_ok=None, last_restore_drill_epoch=None), NOW)
    assert not any("리허설" in line for line in local_only["lines"])  # 원격이 없으면 리허설 경고를 따로 내지 않는다(미설정 경고가 이미 있음)


def test_secrets_backup_line_shown_when_configured_but_not_alarming():
    result = describe_backup(_status(secrets_backup_configured=True, secrets_backup_files=6), NOW)
    assert result["level"] == "ok"
    assert any("암호화된 비밀 백업 포함 (6개 파일)" in line for line in result["lines"])


def test_no_secrets_line_when_not_configured():
    result = describe_backup(_status(secrets_backup_configured=False), NOW)
    assert not any("비밀 백업" in line for line in result["lines"])
