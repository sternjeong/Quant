"""crash-intl-pool-v1 — job.json, 스모크 전 경로, 날짜 D 뒤 미국·해외 자료를 바꿔도 같은 예측, 1992 이전 미국 사건은 POOL == BASE."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "crash-intl-pool-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")
run = _mod("crash_intl_pool_v1", f"research/jobs/{STUDY}/run.py")


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
    assert {r["market"] for r in rows} == {"US", "Europe", "Japan", "Asia_Pacific_ex_Japan"}
    assert {r["model"] for r in rows} == {"BASE", "POOL"}
    judged = [r for r in rows if r["judged_m1"] == 1 or r["judged_m2"] == 1]
    assert judged and all(r["market"] != "US" and r["era"] in lab.INTL_STRATA for r in judged)
    assert res["detail"]["POOL_M1"]["n"]["pooled"] == len(res["models"]["clusters"]["m1"])


def _intl_changed(intl, D, factor=0.5):
    out = {}
    for k, Lr in intl.items():
        L2 = Lr.copy()
        m = L2.index > D
        L2[m] = L2[m] * factor
        out[k] = L2
    return out


def test_no_lookahead():
    data = lab.load_us(True)
    intl = lab.synthetic_intl()
    ctx = lab.us_context(data)
    ic = {k: lab.market_context(v, k) for k, v in intl.items()}
    irecs = [r for k in lab.INTL_REGIONS for r in ic[k]["eps"]]
    r = next(j for j in irecs if j["stratum"] == "I2")
    D = r["t0_date"]
    a = run.episode_calc(ctx["recs"], ctx["recs"] + irecs, r)
    L2 = data["L"].copy()
    L2[L2.index > D] = L2[L2.index > D] * 0.5
    ctx2 = lab.us_context(dict(data, L=L2))
    intl2 = _intl_changed(intl, D)
    ic2 = {k: lab.market_context(v, k) for k, v in intl2.items()}
    irecs2 = [j for k in lab.INTL_REGIONS for j in ic2[k]["eps"]]
    r2 = next(j for j in irecs2 if j["id"] == r["id"])
    b = run.episode_calc(ctx2["recs"], ctx2["recs"] + irecs2, r2)
    for k in ("base", "pool"):
        assert a[k]["m1"] == b[k]["m1"] and a[k]["m2"] == b[k]["m2"] and a[k]["n_train"] == b[k]["n_train"]


def test_pool_equals_base_before_1992():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    intl = lab.synthetic_intl()
    irecs = [r for k, v in intl.items() for r in lab.market_context(v, k)["eps"]]
    n = 0
    for r in ctx["recs"]:
        if r["t0_date"] < pd.Timestamp("1992-01-01"):
            c = run.episode_calc(ctx["recs"], ctx["recs"] + irecs, r)
            assert c["pool"]["m1"] == c["base"]["m1"] and c["pool"]["m2"] == c["base"]["m2"]
            n += 1
    assert n > 10
