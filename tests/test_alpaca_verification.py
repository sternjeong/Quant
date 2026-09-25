"""core.alpaca_verification: 읽기 전용 검증 오케스트레이션. 모든 외부 호출은 mock, 실제 네트워크·주문 없음.

기대값은 요구사항에서 정했다: 키 없음은 예외 없이 no_credentials, 7일 안 PASS 가 있으면 재실행 안 함,
결과는 data/verification/alpaca_YYYYMMDD_HHMM.json 으로 저장, 키 값은 어디에도 새지 않음, --write 자동 실행 없음.
"""
import inspect
import json
import socket
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import alpaca_verification as av

NOW = datetime(2026, 9, 24, 1, 5, tzinfo=timezone.utc)
KEY, SECRET = "AKTESTKEYVALUE12345", "SECRETVALUE67890zzz"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise AssertionError("network access attempted in a unit test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv(av.KEY_ENV, KEY)
    monkeypatch.setenv(av.SECRET_ENV, SECRET)


@pytest.fixture
def no_creds(monkeypatch):
    monkeypatch.delenv(av.KEY_ENV, raising=False)
    monkeypatch.delenv(av.SECRET_ENV, raising=False)


def _ok(summary="ok"):
    return lambda: {"verdict": "PASS", "summary": summary, "failing": [], "detail": None}


def _checks(**overrides):
    base = {name: _ok() for name in av.DEFAULT_CHECKS}
    base.update(overrides)
    return base


def _write_result(directory, when, overall="PASS", failing=None):
    directory.mkdir(parents=True, exist_ok=True)
    data = {"status": "completed", "overall": overall, "generated_at": when.isoformat(timespec="seconds"),
            "checks": {"corporate_actions": {"verdict": overall, "failing": failing or []}}}
    (directory / f"alpaca_{when.strftime('%Y%m%d_%H%M')}.json").write_text(json.dumps(data), encoding="utf-8")


# ---- credentials / run ----------------------------------------------------------------------------

def test_no_credentials_returns_status_without_exception_or_checks_or_file(no_creds, tmp_path):
    def boom():
        raise AssertionError("no check may run without credentials")
    result = av.run_alpaca_verification(tmp_path, checks={"x": boom}, now=NOW)
    assert result["status"] == "no_credentials" and result["overall"] is None
    assert result["checks"] == {} and result["write_phase_executed"] is False
    assert list(tmp_path.iterdir()) == []


def test_all_pass_is_saved_with_timestamped_name_and_loadable(creds, tmp_path):
    result = av.run_alpaca_verification(tmp_path, checks=_checks(), now=NOW)
    assert result["status"] == "completed" and result["overall"] == "PASS"
    assert [p.name for p in tmp_path.iterdir()] == ["alpaca_20260924_0105.json"]
    loaded = av.load_latest_verification(tmp_path)
    assert loaded["overall"] == "PASS" and set(loaded["checks"]) == set(av.DEFAULT_CHECKS)
    assert loaded["write_phase_executed"] is False and "읽기 전용" in loaded["verified_scope"]


def test_default_check_set_is_the_five_read_only_checks():
    assert list(av.DEFAULT_CHECKS) == ["idempotency_read_only", "corporate_actions", "price_crosscheck", "account_schema",
                                       "market_meta_news"]


@pytest.mark.parametrize("verdicts, expected", [
    (["PASS", "PASS", "PASS", "PASS"], "PASS"),
    (["PASS", "UNEXPECTED", "PASS", "PASS"], "UNEXPECTED"),
    (["PASS", "UNEXPECTED", "FAIL", "PASS"], "FAIL"),
])
def test_overall_is_worst_verdict(creds, tmp_path, verdicts, expected):
    checks = {n: (lambda v=v: {"verdict": v, "summary": "", "failing": [], "detail": None})
              for n, v in zip(av.DEFAULT_CHECKS, verdicts)}
    assert av.run_alpaca_verification(tmp_path, checks=checks, now=NOW)["overall"] == expected


def test_exception_in_one_check_is_unexpected_and_others_still_run(creds, tmp_path):
    ran = []

    def crash():
        raise RuntimeError("boom")

    def later():
        ran.append(1)
        return {"verdict": "PASS", "summary": "", "failing": [], "detail": None}
    result = av.run_alpaca_verification(tmp_path, checks={"a": crash, "b": later}, now=NOW)
    assert result["checks"]["a"]["verdict"] == "UNEXPECTED" and "RuntimeError" in result["checks"]["a"]["failing"][0]
    assert ran == [1] and result["overall"] == "UNEXPECTED"


def test_unknown_verdict_string_is_not_trusted(creds, tmp_path):
    result = av.run_alpaca_verification(tmp_path, checks={"a": lambda: {"verdict": "OK"}}, now=NOW)
    assert result["checks"]["a"]["verdict"] == "UNEXPECTED"


# ---- secrets never leak ---------------------------------------------------------------------------------

def test_key_values_are_scrubbed_from_saved_file_and_telegram_text(creds, tmp_path):
    leaky = lambda: {"verdict": "FAIL", "summary": f"header {KEY}", "failing": [f"step: bad {SECRET} value"],
                     "detail": {"echo": f"{KEY}:{SECRET}"}}
    result = av.run_alpaca_verification(tmp_path, checks={"corporate_actions": leaky}, now=NOW)
    saved = (tmp_path / "alpaca_20260924_0105.json").read_text(encoding="utf-8")
    text = av.format_telegram_summary({"status": "completed", "overall": "FAIL",
                                       "checks": {"corporate_actions": {"verdict": "FAIL", "failing": [f"x {KEY} {SECRET}"]}}})
    for blob in (saved, json.dumps(result, ensure_ascii=False), text):
        assert KEY not in blob and SECRET not in blob
    assert "<redacted>" in saved


def test_no_credentials_message_names_variables_but_not_values(no_creds, monkeypatch):
    monkeypatch.setenv(av.KEY_ENV, "")           # empty string counts as missing
    text = av.format_telegram_summary({"status": "no_credentials"})
    assert av.KEY_ENV in text and "키가 없어" in text


# ---- --write is never run ---------------------------------------------------------------------------

def test_idempotency_check_always_calls_verify_with_write_false(creds, monkeypatch):
    calls = []
    fake = SimpleNamespace(
        PaperApi=lambda key, secret: "api",
        verify=lambda api, key, secret, **kw: calls.append(kw) or {
            "overall": "PASS", "summary": {"PASS": 5}, "steps": [], "mode": "read_only", "unmapped_statuses": []},
    )
    monkeypatch.setattr(av, "_load_script", lambda name: fake)
    res = av.check_idempotency_read_only()
    assert calls == [{"write": False}] and res["verdict"] == "PASS"
    assert res["detail"]["idempotency_verified"] is False


def test_module_never_requests_write_mode():
    source = inspect.getsource(av)
    assert "write=True" not in source
    assert "/v2/orders" not in source and "paper_execution" not in source


def test_idempotency_failure_lines_name_the_step_and_status(creds, monkeypatch):
    steps = [{"id": "R3_unknown_id", "verdict": "FAIL", "actual_status": 500, "expected": "404", "note": "unknown id answered 500"},
             {"id": "R1_clock", "verdict": "PASS", "actual_status": 200, "expected": "200", "note": ""}]
    fake = SimpleNamespace(PaperApi=lambda k, s: None,
                           verify=lambda *a, **k: {"overall": "FAIL", "summary": {}, "steps": steps, "mode": "read_only"})
    monkeypatch.setattr(av, "_load_script", lambda name: fake)
    res = av.check_idempotency_read_only()
    assert res["verdict"] == "FAIL" and len(res["failing"]) == 1
    assert "R3_unknown_id" in res["failing"][0] and "500" in res["failing"][0] and "404" in res["failing"][0]


def test_price_crosscheck_unadjusted_alpaca_is_fail_and_unavailable_is_unexpected(monkeypatch):
    def fake_mod(recent_unavailable, split_verdict):
        return SimpleNamespace(
            DEFAULT_SYMBOLS=["AAPL"], VERDICT_UNAVAILABLE="unavailable",
            step_recent=lambda *a: {"summary": {"unavailable": recent_unavailable}},
            step_aapl_split=lambda *a: {"verdict": split_verdict, "note": "n"})
    monkeypatch.setattr(av, "_load_script", lambda n: fake_mod(0, "alpaca_split_adjusted"))
    assert av.check_price_crosscheck()["verdict"] == "PASS"
    monkeypatch.setattr(av, "_load_script", lambda n: fake_mod(0, "alpaca_unadjusted"))
    assert av.check_price_crosscheck()["verdict"] == "FAIL"
    monkeypatch.setattr(av, "_load_script", lambda n: fake_mod(2, "alpaca_split_adjusted"))
    assert av.check_price_crosscheck()["verdict"] == "UNEXPECTED"
    monkeypatch.setattr(av, "_load_script", lambda n: fake_mod(0, "inconclusive"))
    assert av.check_price_crosscheck()["verdict"] == "UNEXPECTED"


def test_account_schema_mapping(monkeypatch):
    import core.account_sync as acct
    cases = [({"ok": True, "skipped": False, "errors": []}, "PASS"),
             ({"ok": True, "skipped": False, "errors": ["bad field"]}, "UNEXPECTED"),
             ({"ok": False, "skipped": False, "reason": "http 500", "errors": []}, "UNEXPECTED"),
             ({"ok": False, "skipped": True, "reason": "no key", "errors": []}, "UNEXPECTED")]
    for payload, expected in cases:
        monkeypatch.setattr(acct, "sync_paper_account", lambda persist=True, _p=payload: _p)
        assert av.check_account_schema()["verdict"] == expected
    seen = {}
    monkeypatch.setattr(acct, "sync_paper_account", lambda persist=True: seen.update(persist=persist) or {"ok": True, "errors": []})
    av.check_account_schema()
    assert seen["persist"] is False                     # never writes the DB


# ---- load / recent pass / summary ----------------------------------------------------------------------

def test_load_latest_none_when_missing_and_skips_corrupt_file(tmp_path):
    assert av.load_latest_verification(tmp_path / "nope") is None
    _write_result(tmp_path, NOW - timedelta(days=1))
    (tmp_path / "alpaca_20260924_0000.json").write_text("{not json", encoding="utf-8")   # newest name, corrupt
    assert av.load_latest_verification(tmp_path)["generated_at"].startswith("2026-09-23")


def test_find_recent_pass_uses_seven_day_window(tmp_path):
    _write_result(tmp_path, NOW - timedelta(days=6, hours=23))
    assert av.find_recent_pass(tmp_path, now=NOW) is not None
    other = tmp_path / "old"
    _write_result(other, NOW - timedelta(days=8))
    assert av.find_recent_pass(other, now=NOW) is None


def test_newer_failure_does_not_hide_a_recent_pass_and_failure_alone_is_not_a_pass(tmp_path):
    _write_result(tmp_path, NOW - timedelta(days=5), "PASS")
    _write_result(tmp_path, NOW - timedelta(days=1), "FAIL")
    assert av.find_recent_pass(tmp_path, now=NOW)["overall"] == "PASS"
    only_fail = tmp_path / "f"
    _write_result(only_fail, NOW - timedelta(days=1), "UNEXPECTED")
    assert av.find_recent_pass(only_fail, now=NOW) is None


def test_summary_reports_age_and_overall(tmp_path):
    assert av.summarize_latest_verification(tmp_path, now=NOW)["has_result"] is False
    _write_result(tmp_path, NOW - timedelta(days=2), "FAIL", ["corp: ex_date missing"])
    s = av.summarize_latest_verification(tmp_path, now=NOW)
    assert s["has_result"] and s["age_days"] == 2.0 and s["overall"] == "FAIL" and s["failing"] == ["corp: ex_date missing"]


def test_ui_status_levels(tmp_path):
    assert av.verification_status_for_ui(tmp_path, now=NOW)["level"] == "unknown"
    _write_result(tmp_path, NOW - timedelta(days=1), "PASS")
    ui = av.verification_status_for_ui(tmp_path, now=NOW)
    assert ui["level"] == "ok" and not ui["stale"] and "PASS" in ui["label"]
    assert av.verification_status_for_ui(tmp_path, now=NOW + timedelta(days=10))["level"] == "warn"
    for overall, level in (("FAIL", "error"), ("UNEXPECTED", "warn")):
        d = tmp_path / overall
        _write_result(d, NOW - timedelta(days=1), overall)
        assert av.verification_status_for_ui(d, now=NOW)["level"] == level


# ---- bootstrap -----------------------------------------------------------------------------------------

def _runner(overall, failing=None, calls=None):
    def run(directory, now=None):
        if calls is not None:
            calls.append(1)
        return {"status": "completed", "overall": overall, "path": "p",
                "checks": {"idempotency_read_only": {"verdict": overall, "failing": failing or []}}}
    return run


def test_bootstrap_skips_silently_when_recent_pass_exists(tmp_path):
    _write_result(tmp_path, NOW - timedelta(days=3))
    calls, sent = [], []
    out = av.run_bootstrap_if_needed(tmp_path, now=NOW, runner=_runner("PASS", calls=calls), notify=sent.append)
    assert out["action"] == "skipped_recent_pass" and calls == [] and sent == []


def test_bootstrap_runs_and_sends_exactly_one_message_when_no_pass(tmp_path):
    calls, sent = [], []
    out = av.run_bootstrap_if_needed(tmp_path, now=NOW, runner=_runner("PASS", calls=calls), notify=lambda t: sent.append(t) or True)
    assert out["action"] == "ran" and out["notified"] is True and calls == [1] and len(sent) == 1
    assert "PASS" in sent[0]


def test_bootstrap_failure_message_lists_check_and_assumption_one_line_each(tmp_path):
    sent = []
    fails = ["R3_unknown_id: unknown id answered 500 (응답 500, 기대 404)", "R2_account: id field missing"]
    av.run_bootstrap_if_needed(tmp_path, now=NOW, runner=_runner("FAIL", fails), notify=lambda t: sent.append(t) or True)
    lines = sent[0].splitlines()
    assert "FAIL" in lines[0]
    assert any("멱등성" in l and "R3_unknown_id" in l for l in lines)
    assert any("R2_account" in l for l in lines)
    assert "미검증" in lines[-1]


def test_bootstrap_does_not_repeat_the_same_failure_notice_within_three_days(tmp_path):
    sent = []
    notify = lambda t: sent.append(t) or True
    run = _runner("UNEXPECTED", ["R1_clock: auth rejected"])
    av.run_bootstrap_if_needed(tmp_path, now=NOW, runner=run, notify=notify)
    av.run_bootstrap_if_needed(tmp_path, now=NOW + timedelta(days=1), runner=run, notify=notify)
    assert len(sent) == 1
    av.run_bootstrap_if_needed(tmp_path, now=NOW + timedelta(days=1), runner=_runner("UNEXPECTED", ["R9: other"]), notify=notify)
    assert len(sent) == 2                                                     # different failure -> notify
    av.run_bootstrap_if_needed(tmp_path, now=NOW + timedelta(days=5), runner=_runner("UNEXPECTED", ["R9: other"]), notify=notify)
    assert len(sent) == 3                                                     # same failure again after 3+ days


def test_bootstrap_failed_telegram_send_is_not_recorded_as_notified(tmp_path):
    out = av.run_bootstrap_if_needed(tmp_path, now=NOW, runner=_runner("FAIL", ["x"]), notify=lambda t: False)
    assert out["notified"] is False
    sent = []
    av.run_bootstrap_if_needed(tmp_path, now=NOW, runner=_runner("FAIL", ["x"]), notify=lambda t: sent.append(t) or True)
    assert len(sent) == 1                                                      # retried next time


def test_bootstrap_without_credentials_uses_real_runner_and_reports_missing_keys(no_creds, tmp_path):
    sent = []
    out = av.run_bootstrap_if_needed(tmp_path, now=NOW, notify=lambda t: sent.append(t) or True)
    assert out["status"] == "no_credentials" and len(sent) == 1 and "키가 없어" in sent[0]
    assert list(tmp_path.glob("alpaca_*.json")) == []
