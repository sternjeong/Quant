"""crash-internals-v1 — job.json, 스모크 전 경로, 발생일 뒤 시장·12·49 산업 자료를 바꿔도 특징·INTERNAL 예측이 같음."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "crash-internals-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")
run = _mod("crash_internals_v1", f"research/jobs/{STUDY}/run.py")


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
    check_smoke_contract(smoke, STUDY)
    rows = lab.read_predictions(smoke / "predictions.csv")
    assert {"BASE", "INTERNAL"} <= {r["model"] for r in rows}
    assert all(r["p_lb"] is not None for r in rows if r["model"] == "INTERNAL")


def _calc(data, t0):
    ctx = lab.us_context(data)
    arr = run.feature_arrays(ctx, data["ind12"], data["ind49"])
    feats = {r["id"]: run.features_at(arr, r["t0"]) for r in ctx["recs"]}
    xmap = {k: [v[f] for f in run.FEATS] for k, v in feats.items()}
    r = next(j for j in ctx["recs"] if j["t0"] == t0)
    return feats[r["id"]], lab.two_state_episode(ctx["recs"], r, xmap)


def test_no_lookahead():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    r = next(j for j in ctx["recs"] if j["stratum"] == "B")
    t0, D = r["t0"], r["t0_date"]
    fa, a = _calc(data, t0)
    d2 = dict(data)
    L2 = data["L"].copy()
    L2.iloc[t0 + 1:] = L2.iloc[t0 + 1:] * 0.5
    d2["L"] = L2
    i12, i49 = data["ind12"].copy(), data["ind49"].copy()
    i12.loc[i12.index > D] = 0.003
    i49.loc[i49.index > D] = -0.002
    d2["ind12"], d2["ind49"] = i12, i49
    fb, b = _calc(d2, t0)
    assert fa == fb
    assert a["p_lb"] == b["p_lb"] and a["m1"] == b["m1"] and a["m2"] == b["m2"]
