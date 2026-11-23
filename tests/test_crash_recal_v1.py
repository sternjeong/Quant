"""crash-recal-v1 — job.json, 스모크 전 경로, 날짜 D 뒤 자료를 바꿔도 같은 보정, RECAL 회복 확률은 h 에 대해 줄지 않고 분위수는 오름차순·발생일 깊이 이하."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "crash-recal-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")
run = _mod("crash_recal_v1", f"research/jobs/{STUDY}/run.py")


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
    assert {r["model"] for r in rows} == {"BASE", "RECAL"}
    judged = [r for r in rows if r["judged_m1"] == 1 or r["judged_m2"] == 1]
    assert judged and all(r["market"] != "US" and r["era"] in lab.INTL_STRATA for r in judged)


def _setup(data, intl):
    ctx = lab.us_context(data)
    irecs = [r for k in lab.INTL_REGIONS for r in lab.market_context(intl[k], k)["eps"]]
    allr = ctx["recs"] + irecs
    bases = {k["id"]: lab.base0(ctx["recs"], k) for k in allr}
    return ctx, irecs, allr, bases


def test_no_lookahead():
    data, intl = lab.load_us(True), lab.synthetic_intl()
    ctx, irecs, allr, bases = _setup(data, intl)
    r = next(j for j in irecs if j["stratum"] == "I2")
    D = r["t0_date"]
    a = run.episode_calc(allr, bases, r)
    L2 = data["L"].copy()
    L2[L2.index > D] = L2[L2.index > D] * 0.5
    intl2 = {}
    for k, v in intl.items():
        v2 = v.copy()
        v2[v2.index > D] = v2[v2.index > D] * 1.7
        intl2[k] = v2
    _c2, irecs2, allr2, bases2 = _setup(dict(data, L=L2), intl2)
    r2 = next(j for j in irecs2 if j["id"] == r["id"])
    b = run.episode_calc(allr2, bases2, r2)
    assert a["base"]["m1"] == b["base"]["m1"] and a["base"]["m2"] == b["base"]["m2"]
    assert a["recal"]["m1"] == b["recal"]["m1"] and a["recal"]["m2"] == b["recal"]["m2"]
    assert a["recal"]["c"] == b["recal"]["c"] and a["recal"]["delta"] == b["recal"]["delta"]


def test_recal_shapes():
    data, intl = lab.load_us(True), lab.synthetic_intl()
    _ctx, irecs, allr, bases = _setup(data, intl)
    n = 0
    for r in irecs + _ctx["recs"]:
        c = run.episode_calc(allr, bases, r)
        rc = c["recal"]
        if rc["m2"] is not None:
            v = [rc["m2"][h] for h in lab.HZ]
            assert all(b >= a for a, b in zip(v, v[1:]))
        if rc["m1"] is not None:
            q = [rc["m1"][f"{x:g}"] for x in lab.Q]
            assert q == sorted(q) and all(x <= r["dd0"] + 1e-12 for x in q)
            n += 1
    assert n > 20
