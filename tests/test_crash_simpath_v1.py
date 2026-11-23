"""crash-simpath-v1 — job.json, 스모크 전 경로, 모의의 미래 정보 차단, 모의 분위수 ≤ 발생일 깊이."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "crash-simpath-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")
run = _mod("crash_simpath_v1", f"research/jobs/{STUDY}/run.py")


def check_smoke_contract(out: Path, study: str) -> dict:
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    keys = [k for k, s in lab.FAMILY if s == study]
    assert list(res["verdicts"]) == keys
    assert all(v in lab.LABELS for v in res["verdicts"].values())
    assert res["family"]["alpha"] == pytest.approx(lab.ALPHA, abs=1e-6) and res["family"]["alpha_expr"] == "0.05/15" and res["family"]["k"] == 15
    assert len(res["summary"]) <= 8
    assert [e["key"] for e in res["events"]] == [k for k, _l, _d in lab.v1().EVENTS]
    rep = (out / "REPORT.md").read_text(encoding="utf-8")
    for s in ("지금 읽기 (설명용 — 추천 아님)", "사용자가 든 7개 사건", lab.READING_HEADER):
        assert s in rep
    for _k, label, _d in lab.v1().EVENTS:
        assert label in rep
    assert "nan" not in rep.lower().replace("financ", "")
    text = (out / "predictions.csv").read_text(encoding="utf-8")
    assert text.split("\n")[0] == ",".join(lab.PRED_COLUMNS)
    rows = lab.read_predictions(out / "predictions.csv")
    assert rows
    for r in rows:
        assert set(r) == set(lab.PRED_COLUMNS)
        assert r["study"] == study
    base = {(r["market"], r["episode_id"], r["landmark"]) for r in rows if r["model"] == "BASE"}
    for r in rows:
        assert (r["market"], r["episode_id"], r["landmark"]) in base
    for f in ("results.json", "REPORT.md", "predictions.csv"):
        assert (out / f).stat().st_size < 256 * 1024
    return res


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    d = tmp_path_factory.mktemp("smoke")
    assert run.main(["--smoke", "--out", str(d / "o"), "--checkpoint", str(d / "c")]) == 0
    return d / "o"


def test_job_json_valid():
    from core.research_jobs import validate_job

    data = json.loads((ROOT / "research" / "jobs" / STUDY / "job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, STUDY, ROOT)
    assert err == "" and job is not None


def test_smoke_end_to_end(smoke):
    res = check_smoke_contract(smoke, STUDY)
    rows = lab.read_predictions(smoke / "predictions.csv")
    assert {"BASE", "SIM", "SIM_IID"} <= {r["model"] for r in rows}
    assert res["constants"]["n_paths_used"] == lab.N_SIM_SMOKE
    dd0 = {e["id"]: e["dd0"] for e in res["episodes"]}
    n = 0
    for r in rows:
        if r["model"] in ("SIM", "SIM_IID") and r["landmark"] == 0:
            qs = [r[c] for c in ("d_q10", "d_q25", "d_q50", "d_q75", "d_q90")]
            assert all(q <= dd0[r["episode_id"]] + 1e-6 for q in qs)
            assert qs == sorted(qs)
            n += 1
    assert n > 10
    judged = [r for r in rows if r["judged_m1"] == 1 or r["judged_m2"] == 1]
    assert judged and all(r["landmark"] == 0 and r["market"] == "US" and r["model"] in ("SIM", "BASE") for r in judged)


def test_no_lookahead():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    r = next(j for j in ctx["recs"] if j["stratum"] == "B")
    a = run.episode_calc(ctx["recs"], r, 200, landmarks=False, iid=True)
    L2 = data["L"].copy()
    L2.iloc[r["t0"] + 1:] = L2.iloc[r["t0"] + 1:] * 0.5
    ctx2 = lab.us_context(dict(data, L=L2))
    r2 = next(j for j in ctx2["recs"] if j["t0"] == r["t0"])
    b = run.episode_calc(ctx2["recs"], r2, 200, landmarks=False, iid=True)
    assert a["sim"] == b["sim"] and a["sim_iid"] == b["sim_iid"]
    assert a["base0"]["m1"] == b["base0"]["m1"] and a["base0"]["m2"] == b["base0"]["m2"]
    Lv = ctx["Lv"].copy()
    tau = r["t0"] + 63
    s1 = lab.simulate(Lv, "US", r["P"], tau, -0.2, 63, 200)
    Lv[tau + 1:] = 1.0
    assert lab.simulate(Lv, "US", r["P"], tau, -0.2, 63, 200) == s1
