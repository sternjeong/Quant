import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("day4_handoff", Path(__file__).with_name("build_handoff.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row():
    return {"fill_session": "2026-07-01", "signal_session": "2026-06-30",
            "signal_close_utc": "2026-06-30T20:00:00+00:00", "fill_open_utc": "2026-07-01T13:30:00+00:00",
            "membership_snapshot_date": "2026-06-30", "raw_identifier": "ABC-201701", "cache_ticker_hint": "ABC"}


def test_reused_ticker_does_not_merge_distinct_raw_securities():
    one, two = row(), row()
    two["raw_identifier"] = "ABC"
    original = copy.deepcopy([one, two])
    result = module.requests_from_rows([one, two])
    assert {r["raw_identifier"] for r in result} == {"ABC", "ABC-201701"}
    assert [one, two] == original


def test_duplicate_cannot_inflate_coverage():
    with pytest.raises(ValueError, match="duplicate_raw"):
        module.requests_from_rows([row(), row()])


@pytest.mark.parametrize("field,value", [
    ("signal_session", "2026-07-01"),
    ("membership_snapshot_date", "2026-07-01"),
    ("signal_close_utc", "2026-07-01T20:00:00+00:00"),
    ("signal_close_utc", "2026-06-30T20:00:00"),
    ("raw_identifier", ""),
])
def test_future_same_day_or_ambiguous_keys_rejected(field, value):
    item = row()
    item[field] = value
    with pytest.raises(ValueError):
        module.requests_from_rows([item])


def test_boundary_cannot_depend_on_security():
    one, two = row(), row()
    two.update(raw_identifier="OTHER", signal_close_utc="2026-06-30T19:00:00+00:00")
    with pytest.raises(ValueError, match="inconsistent_boundary"):
        module.requests_from_rows([one, two])


def test_empty_is_not_coverage():
    with pytest.raises(ValueError, match="empty_request"):
        module.requests_from_rows([])
