"""five_strategy_batch_ci: the leaderboard JSON holds only current-score (v2) results; legacy results are
counted separately (never deleted).  DB access is faked -- no real tuning, no network.

Expected values come from the requirement: v1 and v2 tuning results must not be ranked together.
"""
import importlib.util
import json
import pathlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import core.strategy_tuning as st_mod

_spec = importlib.util.spec_from_file_location(
    "five_strategy_batch_ci", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "five_strategy_batch_ci.py")
batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(batch)


def _row(ticker, excess, version, sid, run_id):
    return {
        "ticker": ticker, "sector": "Tech", "style_type": "growth", "trained_regime": "강세장",
        "excess_return": excess, "style_score_version": version,
        "score_version_status": st_mod.score_version_status(version), "tuned_config": {"k": ticker},
        "backbone_changed": False, "run_id": run_id, "run_intensity": "보통",
    }


# strategy 1: legacy result has the HIGHEST excess return (the old bug: it would top the leaderboard)
DB = {
    1: [_row("OLD1", 99.0, None, 1, 10), _row("NEW1", 5.0, 2, 1, 11), _row("V1", 50.0, 1, 1, 12), _row("NEW2", 3.0, 2, 1, 13)],
    2: [_row("OLD2", 80.0, 1, 2, 20), _row("NEW3", 4.0, 2, 2, 21)],
}


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    calls = []

    def fake_top(strategy_id, limit=10, require_significant=True, score_version=None):
        calls.append({"strategy_id": strategy_id, "limit": limit, "score_version": score_version})
        rows = [dict(r) for r in DB[strategy_id]]
        if score_version is not None:
            rows = [r for r in rows if r["style_score_version"] == score_version]
        rows.sort(key=lambda r: r["excess_return"], reverse=True)
        return rows[:limit]

    class FakeSession:
        def get(self, model, sid):
            return SimpleNamespace(name=f"strategy-{sid}")

    @contextmanager
    def fake_get_session():
        yield FakeSession()

    monkeypatch.setattr(batch, "get_top_tuning_results", fake_top)
    monkeypatch.setattr(batch, "get_session", fake_get_session)
    monkeypatch.setattr(batch, "TOP10_JSON_PATH", tmp_path / "top10.json")
    monkeypatch.setattr(batch, "LEGACY_SUMMARY_JSON_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(batch, "REPORT_PATH", tmp_path / "report.md")
    monkeypatch.setattr(batch, "MIN_PER_STRATEGY", 1)
    return SimpleNamespace(calls=calls, top=tmp_path / "top10.json", legacy=tmp_path / "legacy.json",
                           report=tmp_path / "report.md")


def test_leaderboard_json_contains_only_current_score_results(fake_env):
    batch._select_and_export([1, 2])
    exported = json.loads(fake_env.top.read_text(encoding="utf-8"))
    assert exported                                                            # not empty
    names = " ".join(e["name"] for e in exported)
    assert "NEW1" in names and "NEW2" in names and "NEW3" in names
    assert "OLD1" not in names and "V1" not in names and "OLD2" not in names
    assert {e["style_score_version"] for e in exported} == {batch.STYLE_SCORE_VERSION}
    assert {e["score_version_status"] for e in exported} == {"current"}
    # ranks stay ordered by excess return among v2 results only
    assert [e["excess_return"] for e in exported] == sorted((e["excess_return"] for e in exported), reverse=True)
    # still a plain list: scripts/import_five_strategy_batch_results.py reads it that way
    assert isinstance(exported, list) and all("indicator_config" in e for e in exported)


def test_v2_filter_is_requested_from_the_query(fake_env):
    batch._select_and_export([1])
    filtered = [c for c in fake_env.calls if c["score_version"] is not None]
    assert filtered and all(c["score_version"] == st_mod.STYLE_SCORE_VERSION for c in filtered)


def test_legacy_counted_separately_not_deleted_and_not_ranked(fake_env):
    batch._select_and_export([1, 2])
    summary = json.loads(fake_env.legacy.read_text(encoding="utf-8"))
    per = {p["strategy_id"]: p for p in summary["per_strategy"]}
    assert per[1]["legacy_count"] == 2 and per[1]["current_count"] == 2      # OLD1 + V1 vs NEW1 + NEW2
    assert per[2]["legacy_count"] == 1 and per[2]["current_count"] == 1
    assert {r["ticker"] for r in per[1]["legacy_top"]} == {"OLD1", "V1"}
    assert per[1]["legacy_top"][0]["excess_return"] == 99.0                  # kept, just not on the leaderboard
    assert all("tuned_config" not in r for r in per[1]["legacy_top"])        # summary only, no configs
    assert summary["style_score_version_in_leaderboard"] == st_mod.STYLE_SCORE_VERSION
    report = fake_env.report.read_text(encoding="utf-8")
    assert "legacy 건수" in report and "2건" in report and "OLD1" not in report


def test_higher_legacy_score_never_displaces_a_current_result(fake_env):
    """The regression: with the unfiltered query the 99.0 legacy row would have been rank 1."""
    batch._select_and_export([1])
    exported = json.loads(fake_env.top.read_text(encoding="utf-8"))
    assert exported[0]["excess_return"] == 5.0 and "NEW1" in exported[0]["name"]


def test_no_v2_results_yields_empty_leaderboard_but_legacy_still_reported(fake_env, monkeypatch):
    monkeypatch.setitem(DB, 1, [_row("OLD1", 99.0, None, 1, 10)])
    batch._select_and_export([1])
    assert json.loads(fake_env.top.read_text(encoding="utf-8")) == []
    assert json.loads(fake_env.legacy.read_text(encoding="utf-8"))["per_strategy"][0]["legacy_count"] == 1


def test_helpers_partition_and_badge_from_version_not_stored_status():
    rows = [{"style_score_version": 2}, {"style_score_version": 1}, {"style_score_version": None}, {}]
    current, legacy = st_mod.partition_by_score_version(rows)
    assert len(current) == 1 and len(legacy) == 3
    # a JSON copy saved with a stale "current" label but an old version number is legacy
    assert st_mod.result_score_status({"style_score_version": 1, "score_version_status": "current"}) == "legacy"
    assert st_mod.result_score_status({}) == "legacy"
    assert "legacy" in st_mod.score_version_badge("legacy") and "v2" in st_mod.score_version_badge("current")
    assert "legacy" in st_mod.score_version_badge("something-else")
