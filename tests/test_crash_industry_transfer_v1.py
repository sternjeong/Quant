"""crash-industry-transfer-v1 — job.json, 스모크 전 경로, 날짜 D 뒤 업종·시장 자료를 바꿔도 같은 예측, 업종 기울기 0 이면 p_lb == 시장 π."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "crash-industry-transfer-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")
run = _mod("crash_industry_transfer_v1", f"research/jobs/{STUDY}/run.py")


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
    assert {r["model"] for r in rows} == {"BASE", "XFER"}
    assert all(r["market"] == "US" for r in rows)          # 업종 사건 예측은 저장하지 않는다
    assert res["models"]["industry_sample"]["n_industry_events"] > 100


def _calc(data, t0):
    ctx = lab.us_context(data)
    us = ctx["recs"]
    xmap = run.market_features(ctx)
    irecs, ixmap, _pc = run.industry_events(data["ind49"])
    r = next(j for j in us if j["t0"] == t0)
    return lab.two_state_episode(us, r, xmap, cls_recs=irecs, cls_xmap=ixmap, plb_recs=us, plb_xmap=xmap), xmap[r["id"]]


def test_no_lookahead():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    r = next(j for j in ctx["recs"] if j["stratum"] == "B")
    t0, D = r["t0"], r["t0_date"]
    a, xa = _calc(data, t0)
    d2 = dict(data)
    L2 = data["L"].copy()
    L2.iloc[t0 + 1:] = L2.iloc[t0 + 1:] * 0.5
    i49 = data["ind49"].copy()
    i49.loc[i49.index > D] = -0.002
    d2["L"], d2["ind49"] = L2, i49
    b, xb = _calc(d2, t0)
    assert xa == xb
    assert a["p_lb"] == b["p_lb"] and a["pi"] == b["pi"] and a["m1"] == b["m1"] and a["m2"] == b["m2"]
    assert a["n_cls"] == b["n_cls"]


def test_zero_slope_gives_market_pi():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    us = ctx["recs"]
    xmap = run.market_features(ctx)
    irecs, ixmap, _pc = run.industry_events(data["ind49"])
    flat = {k: [0.0, 1.0, 2.0, 3.0] for k in ixmap}         # 업종 특징이 모두 상수 → 기울기 0
    r = next(j for j in us if j["stratum"] == "B")
    ts = lab.two_state_episode(us, r, xmap, cls_recs=irecs, cls_xmap=flat, plb_recs=us, plb_xmap=xmap)
    _C, y = lab.cls_set(us, r["t0_date"])
    assert ts["unfit"] is None
    assert ts["p_lb"] == ts["pi"] == float(np.mean(y))
    assert ts["m1"] == ts["base"]["m1"] and ts["m2"] == ts["base"]["m2"]
