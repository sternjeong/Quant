import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "research" / "jobs" / "sleeve-weight-v1"


def _load():
    spec = importlib.util.spec_from_file_location("sleeve_weight_v1", JOB / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_job_contract_and_fixed_gates():
    job = json.loads((JOB / "job.json").read_text(encoding="utf-8"))
    assert job["id"] == "sleeve-weight-v1" and job["summary_from"] == "verdicts"
    m = _load()
    assert m.WEIGHTS == {"W15": 0.15, "W25": 0.25, "W35": 0.35, "W50": 0.50}
    assert (m.MIN_CAGR_EDGE, m.MAX_MDD_WORSE, m.STRESS_EXTRA_FEE, m.N_TRIALS, m.HOLDOUT_YEARS) == (0.010, 0.030, 0.0008, 4, 2)


def test_smoke_resume_then_complete(tmp_path, monkeypatch):
    m = _load()
    monkeypatch.setenv("RESEARCH_JOB_DEADLINE_EPOCH", "0")
    args = ["--smoke", "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ck")]
    assert m.main(args) == 3
    monkeypatch.delenv("RESEARCH_JOB_DEADLINE_EPOCH")
    assert m.main(args) == 0
    res = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == {"W25", "W35", "W50"}
    assert all(v == "SMOKE_ONLY" for v in res["verdicts"].values())
    assert "생존편향" in (tmp_path / "out" / "REPORT.md").read_text(encoding="utf-8")
