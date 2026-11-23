"""crash-landmark-v1 — job.json, 스모크 전 경로(결과·보고서·predictions.csv 형식), 미래 정보 차단, 랜드마크 예측의 경계."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "crash-landmark-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")
run = _mod("crash_landmark_v1", f"research/jobs/{STUDY}/run.py")


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
    assert {r["landmark"] for r in rows} == {0, 21, 63, 126}
    judged = [r for r in rows if r["judged_m1"] == 1]
    assert judged and all(r["market"] == "US" and r["era"] in lab.US_STRATA and r["model"] in ("LM", "BASE") for r in judged)
    assert res["detail"]["LM_M1"]["n"]["pooled"] == sum(1 for e in res["episodes"] if e["era"] in lab.US_STRATA and e["d1"] is not None)


def _ctx_with_changed_future(data, pos, factor=0.6):
    L2 = data["L"].copy()
    L2.iloc[pos + 1:] = L2.iloc[pos + 1:] * np.linspace(1.0, factor, len(L2) - pos - 1)
    d2 = dict(data, L=L2)
    return lab.us_context(d2)


def test_no_lookahead():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    recs = ctx["recs"]
    r = next(j for j in recs if j["t0"] > 6000 and lab.landmark_state(j, 63) is not None)
    asof = r["t0"] + 63
    a_b, a_m = lab.landmark_base(recs, r, 63), lab.landmark_lm(recs, r, 63)
    ctx2 = _ctx_with_changed_future(data, asof)
    r2 = next(j for j in ctx2["recs"] if j["t0"] == r["t0"])
    b_b, b_m = lab.landmark_base(ctx2["recs"], r2, 63), lab.landmark_lm(ctx2["recs"], r2, 63)
    for k in ("m1_v1", "m1_trunc", "m2"):
        for q in a_b[k]:
            assert a_b[k][q] == pytest.approx(b_b[k][q], abs=1e-12)
    for k in ("m1", "m2"):
        assert (a_m[k] is None) == (b_m[k] is None)
        for q in a_m[k] or {}:
            assert a_m[k][q] == pytest.approx(b_m[k][q], abs=1e-12)
    assert (a_b["n1"], a_b["n2"], a_m["n1"], a_m["n2"]) == (b_b["n1"], b_b["n2"], b_m["n1"], b_m["n2"])


def test_landmark_bounds():
    ctx = lab.us_context(lab.load_us(True))
    recs = ctx["recs"]
    n = 0
    for r in recs:
        for e in lab.LANDMARKS:
            st = lab.landmark_state(r, e)
            if st is None:
                continue
            B, M = lab.landmark_base(recs, r, e), lab.landmark_lm(recs, r, e)
            for q in (B["m1_trunc"], M["m1"]):
                if q is None:
                    continue
                vals = [q[f"{x:g}"] for x in lab.Q]
                assert all(v <= st["m"] + 1e-12 for v in vals)
                assert vals == sorted(vals)
                n += 1
            if M["m2"] is not None:
                vals = [M["m2"][h] for h in lab.HZ]
                assert all(b >= a - 1e-12 for a, b in zip(vals, vals[1:]))
    assert n > 20
