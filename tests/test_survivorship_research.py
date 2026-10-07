import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_expanded_asset_job_smoke_marks_all_candidates(tmp_path):
    mod = _load("research/jobs/core-universe-expansion-v1/run.py", "universe_expansion")
    assert mod.main(["--smoke", "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ckpt")]) == 0
    d = json.loads((tmp_path / "out/results.json").read_text())
    assert len(d["candidates"]) == 6
    assert set(d["verdicts"].values()) == {"SMOKE_ONLY"}
    assert set(mod.ASSETS) == {"IWM", "TIP", "VNQ", "VWO", "LQD"}


def test_delisted_job_smoke_uses_separate_adverse_delist_label(tmp_path):
    mod = _load("research/jobs/delisted-precursors-v1/run.py", "delisted_precursors")
    assert mod.main(["--smoke", "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ckpt")]) == 0
    d = json.loads((tmp_path / "out/results.json").read_text())
    assert d["verdicts"]["study"] == "SMOKE_ONLY"
    assert d["adverse_events_dlret_le_minus50pct"] == 8
    assert d["dlret_missing_code_counts"]["-88.0"] == 1
    assert d["dlret_missing_code_counts"]["-99.0"] == 1
    assert d["cases_with_features"] > 0 and d["controls"] > 0
    assert len(d["warning_signals"]) == 5


def test_rnd_center_has_distinct_expansion_and_survivorship_section():
    from hub.satellite_lab_page import render_research_jobs

    html = render_research_jobs({"research_jobs": [
        {"id": "core-universe-expansion-v1", "title": "ETF 확장", "status": "pending"},
        {"id": "delisted-precursors-v1", "title": "상폐 신호", "status": "pending"},
        {"id": "champion-crypto-v4", "title": "코인", "status": "done"},
    ]})
    assert "자산군 확장·생존편향 연구" in html
    assert html.count("core-universe-expansion-v1") == 1
    assert html.count("delisted-precursors-v1") == 1
    assert html.count("champion-crypto-v4") == 1
    assert "S&amp;P 지수 편출은 상장폐지와 구별합니다" in html
