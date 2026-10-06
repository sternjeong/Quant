import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

PATH = Path(__file__).resolve().parents[1] / "research/jobs/champion-crypto-v2/run.py"
spec = importlib.util.spec_from_file_location("champion_crypto_v2", PATH)
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


def test_future_prices_do_not_change_earlier_returns():
    core, sat, cash, coins, *_ = lab.inputs(True)
    first = lab.variants(core, sat, cash, coins)
    changed = coins.copy()
    changed.loc["2025-01-01":] *= 2
    second = lab.variants(core, sat, cash, changed)
    for cid in lab.IDS:
        pd.testing.assert_series_equal(first[cid].loc[:"2024-12-31"], second[cid].loc[:"2024-12-31"])


def test_zero_crypto_budget_reproduces_champion():
    core, sat, cash, coins, *_ = lab.inputs(True)
    # 계속 하락하면 EMA 아래: 고정 후보는 BIL, C4는 기존 코어로 복귀.
    coins[:] = np.exp(-np.arange(len(coins))[:, None] / 1000)
    r = lab.variants(core, sat, cash, coins)
    pd.testing.assert_series_equal(r["C4"].iloc[101:], (.85 * core + .15 * sat).iloc[101:])
    expected = .80 * core + .15 * sat + .05 * cash
    pd.testing.assert_series_equal(r["C1"].iloc[101:], expected.iloc[101:])


def test_holm_and_losing_candidate_cannot_pass():
    assert lab.holm([.01, .04, .03, .2]) == [.04, .09, .09, .2]
    core, *_ = lab.inputs(True)
    base = core.loc[lab.START:]
    losing = {cid: base - .0002 for cid in lab.IDS}
    verdicts = lab.evaluate(base, losing, losing)
    assert all(v["verdict"] == "FAIL" and not v["gates"]["cagr"] for v in verdicts.values())


def test_checkpoint_yield_then_resume_and_smoke_label(tmp_path, monkeypatch):
    args = ["--smoke", "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "checkpoint")]
    monkeypatch.setenv("RESEARCH_JOB_DEADLINE_EPOCH", "0")
    assert lab.main(args) == 3
    monkeypatch.delenv("RESEARCH_JOB_DEADLINE_EPOCH")
    monkeypatch.setattr(lab, "inputs", lambda _: (_ for _ in ()).throw(AssertionError("checkpoint must reuse input")))
    assert lab.main(args) == 0
    d = json.loads((tmp_path / "out/results.json").read_text())
    assert set(d["verdicts"].values()) == {"SMOKE_ONLY"}
    for row in d["diagnostics"]["yearly"]:
        assert abs(row["core_contribution"] + row["satellite_contribution"] - row["returns"]["champion"]) < 1e-12


def test_rnd_job_table_escapes_text_and_shows_status():
    from hub.satellite_lab_page import render_research_jobs
    body = render_research_jobs({"research_jobs": [{"id": "champion-crypto-v2", "title": "<coin>", "status": "in_progress"}]})
    assert "champion-crypto-v2" in body and "이어 계산 대기" in body
    assert "&lt;coin&gt;" in body and "<coin>" not in body
