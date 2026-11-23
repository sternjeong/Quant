"""crash-macro-credit-v1 — job.json, 스모크 전 경로, 미래 정보 차단(월별 RF·무디스·시장), 기울기 0 이면 분할 비율이 고정 분할과 같음."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "crash-macro-credit-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")
run = _mod("crash_macro_credit_v1", f"research/jobs/{STUDY}/run.py")


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
    models = {r["model"] for r in rows}
    assert {"BASE", "MACRO", "SPLIT_P", "SPLIT_P0", "KERNEL_RATECHG_M"} <= models
    for r in rows:
        if r["model"] in ("SPLIT_P", "SPLIT_P0"):
            assert r["a_now"] is not None and r["d_q50"] is None and r["r_252"] is None
        if r["model"] == "MACRO":
            assert r["p_lb"] is not None and 0.05 <= r["p_lb"] <= 0.95
    assert res["detail"]["MAC_M3"]["verdict"] in ("BEATS_FIXED_SPLIT", "FAIL", "NOT_EVALUABLE")


def _changed(data, t0_date, pos):
    d2 = dict(data)
    L2 = data["L"].copy()
    L2.iloc[pos + 1:] = L2.iloc[pos + 1:] * np.linspace(1.0, 0.5, len(L2) - pos - 1)
    d2["L"] = L2
    m = pd.Period(t0_date, "M")
    rf2, mo2 = data["rf_m"].copy(), data["moodys"].copy()
    rf2[rf2.index >= m] = 0.05
    mo2.loc[mo2.index >= m] = 20.0
    d2["rf_m"], d2["moodys"] = rf2, mo2
    return d2


def _macro_for(data, t0):
    ctx = lab.us_context(data)
    us = ctx["recs"]
    _f, xmap = run.feature_map(us, data["rf_m"], data["moodys"])
    r = next(j for j in us if j["t0"] == t0)
    ts = lab.two_state_episode(us, r, xmap)
    return ts, run.m3_calc(ctx, r, ts), ctx


def test_no_lookahead():
    data = lab.load_us(True)
    data["rf_m"], data["moodys"] = lab.synthetic_rf_monthly(), lab.synthetic_moodys()
    ctx = lab.us_context(data)
    _f, xmap = run.feature_map(ctx["recs"], data["rf_m"], data["moodys"])
    r = next(j for j in ctx["recs"] if j["stratum"] == "B" and not lab.two_state_episode(ctx["recs"], j, xmap)["unfit"])
    a, _m3a, _c = _macro_for(data, r["t0"])
    b, _m3b, _c = _macro_for(_changed(data, r["t0_date"], r["t0"]), r["t0"])
    assert a["p_lb"] == b["p_lb"] and a["pi"] == b["pi"]
    for k in ("m1", "m2"):
        for q in a[k]:
            assert a[k][q] == pytest.approx(b[k][q], abs=1e-12)
    assert 1 - a["p_lb"] == 1 - b["p_lb"]   # a_now


def test_split_identity():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    us = ctx["recs"]
    xmap = {r["id"]: [0.01, 0.02, 0.03] for r in us}          # 특징이 모두 상수 → 기울기 0
    r = next(j for j in us if j["stratum"] == "B" and j["t0"] + 1 + run.M3_H <= ctx["last"])
    ts = lab.two_state_episode(us, r, xmap)
    assert ts["unfit"] is None and ts["p_lb"] == ts["pi"]
    m3 = run.m3_calc(ctx, r, ts)
    assert m3["a"] == m3["a0"] and m3["D3"] == 0.0
    assert ts["m1"] == ts["base"]["m1"] and ts["m2"] == ts["base"]["m2"]
