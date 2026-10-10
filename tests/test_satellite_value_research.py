import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("satellite_value_v1", ROOT / "research/jobs/satellite-value-v1/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_job_definition_matches_contract():
    job = json.loads((ROOT / "research/jobs/satellite-value-v1/job.json").read_text(encoding="utf-8"))
    assert job["id"] == "satellite-value-v1" and job["priority"] == 10 and job["resumable"] is True
    assert job["outputs"] == ["results.json", "REPORT.md"] and job["summary_from"] == "verdicts"
    assert (ROOT / job["entrypoint"]).is_file()


def test_pre_registered_constants_are_fixed():
    assert mod.MIN_FULL_DIFF == 0.003 and mod.CI_LOW_FLOOR == -0.005
    assert mod.N_BOOT == 1000 and mod.BLOCK_DAYS == 126 and mod.CI_PCT == (5.0, 95.0)
    assert mod.DECISION_END == "2024-09-30" and mod.SAT_WEIGHT == 0.15 and mod.DECISION_SETUP == "base_30m"


def test_decision_rule():
    d = mod.decide
    assert d(0.003, 0.001, 0.001, -0.0049) == mod.KEEP
    assert d(0.0029, 0.001, 0.001, 0.0) == mod.INCONCLUSIVE           # 차이 부족
    assert d(0.01, -0.001, 0.02, 0.0) == mod.INCONCLUSIVE             # 한 절반 음수
    assert d(0.01, 0.01, 0.0, 0.0) == mod.INCONCLUSIVE                # 절반 0 은 '> 0' 아님
    assert d(0.01, 0.01, 0.01, -0.005) == mod.INCONCLUSIVE            # 하한이 정확히 −0.5%p
    assert d(-0.0001, 0.01, 0.01, 0.0) == mod.SIMPLIFY
    assert d(0.0, -0.01, 0.01, -0.02) == mod.INCONCLUSIVE             # 0 은 SIMPLIFY 아님
    assert d(0.01, 0.01, 0.01, 0.0, noop_reason="같음") == mod.NOT_EVALUABLE
    assert d(float("nan"), 0.01, 0.01, 0.0) == mod.NOT_EVALUABLE


def test_bootstrap_is_deterministic_and_seeded():
    rng = np.random.default_rng(1)
    ra, rb = rng.normal(0.0005, 0.01, 1000), rng.normal(0.0003, 0.01, 1000)
    x = mod.block_bootstrap_diff(ra, rb, 252.0)
    y = mod.block_bootstrap_diff(ra, rb, 252.0)
    z = mod.block_bootstrap_diff(ra, rb, 252.0, seed=mod.BOOT_SEED + 1)
    assert x.shape == (mod.N_BOOT,) and np.array_equal(x, y) and not np.array_equal(x, z)
    lo, hi = np.percentile(x, mod.CI_PCT)
    assert lo < hi
    # 같은 계열끼리의 차이는 언제나 0
    assert np.allclose(mod.block_bootstrap_diff(ra, ra, 252.0, n_boot=50), 0.0)


def test_bootstrap_block_covers_full_series_when_block_is_whole_length():
    r = np.full(300, 0.001)
    out = mod.block_bootstrap_diff(r, np.zeros(300), 252.0, n_boot=5, block=300)
    assert np.allclose(out, (1.001 ** 252) - 1)


def test_segments_and_window_returns_are_consistent():
    idx = pd.bdate_range("2010-01-04", "2026-06-30")
    vals = pd.Series(np.linspace(30e6, 120e6, len(idx)), index=idx)
    segs = mod.segments(idx)
    assert segs["decision"][1] == pd.Timestamp("2024-09-30") and "post_2024_10" in segs
    assert segs["h2"][0] == segs["h1"][1]
    r = mod.window_returns(vals, 30e6, segs["decision"][1])
    years = (segs["decision"][1] - idx[0]).days / 365.25
    ann = float(mod.ann_from_returns(r.to_numpy(), len(r) / years))
    assert abs(ann - mod.seg_ann(vals, 30e6, None, segs["decision"][1])) < 1e-9


def test_spy_sleeve_uses_same_dates_and_constant_weight():
    idx = pd.bdate_range("2010-01-04", "2011-12-30")
    core = pd.DataFrame({"C1": 1.0}, index=idx)
    core.loc[core.index.month % 3 == 0, "C1"] = 0.5
    logs = {"A": [{"date": "2010-01-04", "weights": {"X": 1.0}}, {"date": "2010-07-01", "weights": {}}],
            "A2": [{"date": "2010-01-04", "weights": {"Y": 0.5, "Z": 0.5}}]}
    w = mod.build_weights(core, logs)
    assert all(w[k].index.equals(w["A"].index) for k in w)
    assert np.allclose(w["B"]["SPY"], 0.15)
    assert np.allclose(w["B"]["C1"], w["D"]["C1"] * 0.85)
    assert w["A"].loc["2010-07-01", "X"] == 0.0     # 빈 선정 = 새틀라이트 현금
    assert mod.schedule_to_log([(pd.Timestamp("2010-01-04"), ["A", "B"])])[0]["weights"] == {"A": 0.5, "B": 0.5}
