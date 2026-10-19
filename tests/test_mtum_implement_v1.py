"""mtum-implement-v1 pre-registration and synthetic smoke regression."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
JOB = "mtum-implement-v1"
SPEC = importlib.util.spec_from_file_location("mtum_implement_v1_test", ROOT / "research/jobs" / JOB / "run.py")
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def test_job_contract_is_valid_and_fixed():
    from core.research_jobs import Config, load_job_definitions

    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert JOB in valid, invalid.get(JOB)
    job = json.loads((ROOT / "research/jobs" / JOB / "job.json").read_text())
    assert job["revision"] == 1 and job["resumable"] is True
    assert job["outputs"] == ["results.json", "REPORT.md"]
    assert MOD.W_MOM == 0.5 and MOD.HORIZON_YEARS == 5 and MOD.N_TRIALS == 1


def test_spy_mtum_weights_are_50_50_and_rebalance_only_in_january():
    data = MOD.smoke_prices()
    idx = data["adj"].index[(data["adj"].index >= "2015-01-01") & (data["adj"].index <= "2017-12-31")]
    weights = MOD.strategy_weights(idx[0], idx[-1], data)
    changes = weights.diff().abs().sum(axis=1)
    change_days = [idx[0], *list(changes[changes > 0].index)]
    assert all(d.month == 1 for d in change_days[1:])
    assert np.allclose(weights[MOD.MTUM], 0.5)
    assert np.all(weights.sum(axis=1) <= 1.0)
    assert np.allclose(weights.sum(axis=1), 1.0, atol=1e-8)


def test_bootstrap_is_deterministic_and_paired():
    a = np.linspace(-0.02, 0.025, 500)
    b = np.linspace(-0.018, 0.02, 500)
    one = MOD.bootstrap_cagr_diff(a, b)
    two = MOD.bootstrap_cagr_diff(a, b)
    assert one == two
    assert one["n"] == 2000 and one["block_days"] == 126
    assert one["low90"] <= one["median"] <= one["high90"]


def test_pre_registered_verdict_requires_every_gate():
    summary = {"share_terminal_win": .70, "median_diff_irr": .005, "p10_diff_irr": -.015,
               "median_strategy_mdd_tw": -.20, "median_benchmark_mdd_tw": -.24}
    boot = {"low90": -.0049}
    power = MOD.rp.power_report(10.45, 1)
    verdict, checks = MOD.judgment(summary, boot, .8, power)
    assert verdict == "PASS_FORWARD_CANDIDATE" and all(checks.values())
    boot["low90"] = -.005
    verdict, checks = MOD.judgment(summary, boot, .8, power)
    assert verdict != "PASS_FORWARD_CANDIDATE"
    assert checks["paired_bootstrap_low90_gt_minus_0.5pp"] is False


def test_smoke_writes_only_synthetic_nonjudgment_result(tmp_path):
    out, checkpoint = tmp_path / "out", tmp_path / "checkpoint"
    code = MOD.main(["--smoke", "--out", str(out), "--checkpoint", str(checkpoint)])
    assert code == 0
    result = json.loads((out / "results.json").read_text())
    assert result["smoke"] is True
    assert result["verdicts"]["spy_50_mtum_50"] == "SMOKE_ONLY"
    assert "synthetic" in result["period"]["source"]
