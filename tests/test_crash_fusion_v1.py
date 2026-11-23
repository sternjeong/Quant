"""crash-fusion-v1 — 상수·job.json, 섞기·TWOPH 손 계산, 홈 절차, 검정력, 미래 정보 차단, 스모크 전 경로(결과·보고서·predictions.csv)."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "crash-fusion-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("crash_cycle_lab", "research/jobs/crash-cycle-lab/lab.py")
run = _mod("crash_fusion_v1", f"research/jobs/{STUDY}/run.py")


# ---------------------------------------------------------------- 1·2 상수·job.json
def test_constants():
    assert run.KEYS == ("SIMMIX_M1_INTL", "SIMMIX_M2_INTL", "TWOPH_M2_US", "TWOPH_M2_INTL")
    assert run.K == 4 == len(run.KEYS)
    assert run.FAMILY_ALPHA == 0.05
    assert run.W_MIX == 0.5
    assert run.GRID_E == lab.LANDMARKS
    assert run.LABELS == ("BEATS_LANDMARK", "FAIL", "NOT_EVALUABLE")
    assert set(run.VERDICT_SPEC) == set(run.KEYS)


def test_job_json_valid():
    from core.research_jobs import validate_job

    data = json.loads((ROOT / "research" / "jobs" / STUDY / "job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, STUDY, ROOT)
    assert err == "" and job is not None


# ---------------------------------------------------------------- 3·4 섞기
QA = {"0.1": -0.40, "0.25": -0.30, "0.5": -0.22, "0.75": -0.18, "0.9": -0.16}
QB = {"0.1": -0.30, "0.25": -0.26, "0.5": -0.20, "0.75": -0.17, "0.9": -0.15}
FA = {252: 0.40, 504: 0.60, 756: 0.70, 1260: 0.85}
FB = {252: 0.50, 504: 0.70, 756: 0.80, 1260: 0.90}


def test_mix_hand():
    mq = run.mix_q(QA, QB)
    for k, v in {"0.1": -0.35, "0.25": -0.28, "0.5": -0.21, "0.75": -0.175, "0.9": -0.155}.items():
        assert mq[k] == pytest.approx(v, abs=1e-12)
    mf = run.mix_F(FA, FB)
    for h, v in {252: 0.45, 504: 0.65, 756: 0.75, 1260: 0.875}.items():
        assert mf[h] == pytest.approx(v, abs=1e-12)
    mf2 = run.mix_F({str(h): v for h, v in FA.items()}, {str(h): v for h, v in FB.items()})
    assert set(mf2) == set(lab.HZ)
    for h in lab.HZ:
        assert mf2[h] == pytest.approx(mf[h], abs=1e-15)
    assert run.mix_q(None, QB) is None and run.mix_q(QA, None) is None
    assert run.mix_F(None, FB) is None and run.mix_F(FA, None) is None
    assert lab.score_m2(300, FA) == pytest.approx(0.108125, abs=1e-9)
    assert lab.score_m2(300, FB) == pytest.approx(0.0975, abs=1e-9)
    assert lab.score_m2(300, mf) == pytest.approx(0.10078125, abs=1e-9)
    assert lab.score_m1(-0.25, QA) == pytest.approx(0.0138, abs=1e-9)
    assert lab.score_m1(-0.25, QB) == pytest.approx(0.0125, abs=1e-9)
    assert lab.score_m1(-0.25, mq) == pytest.approx(0.01315, abs=1e-9)


def test_mix_convexity_property():
    rng = np.random.default_rng(7)
    for _ in range(200):
        qa = np.sort(-rng.uniform(0.15, 0.8, 5))
        qb = np.sort(-rng.uniform(0.15, 0.8, 5))
        a = dict(zip(run.QK, qa))
        b = dict(zip(run.QK, qb))
        fd = -rng.uniform(0.15, 0.8)
        m = run.mix_q(a, b)
        assert lab.score_m1(fd, m) <= 0.5 * (lab.score_m1(fd, a) + lab.score_m1(fd, b)) + 1e-12
        fa = dict(zip(lab.HZ, np.sort(rng.uniform(0, 1, 4))))
        fb = dict(zip(lab.HZ, np.sort(rng.uniform(0, 1, 4))))
        R = int(rng.integers(1, 2001))
        mf = run.mix_F(fa, fb)
        assert lab.score_m2(R, mf) <= 0.5 * (lab.score_m2(R, fa) + lab.score_m2(R, fb)) + 1e-12


# ---------------------------------------------------------------- 5·6·7 TWOPH
def _close(got: dict, want: dict, tol=1e-12):
    assert set(got) == set(want)
    for h, v in want.items():
        assert got[h] == pytest.approx(v, abs=tol), h


def test_twoph_arrays_hand():
    a = run.twoph_from_arrays([0, 10, 20], [0, -0.1, -0.2], [100, 200, 300], [1, 1, 1], [0.1, 0.2, 0.3], 0.1, hs=(5, 150, 250, 400))
    _close(a, {5: 0.0, 150: 1 / 3, 250: 2 / 3, 400: 1.0})
    b = run.twoph_from_arrays([0, 0, 0], [0, 0, 0], [50, 100, 150], [1, 0, 1], [0.1] * 3, 0.1, hs=(40, 60, 160))
    _close(b, {40: 0.0, 60: 1 / 3, 160: 1.0})
    assert lab.X_FLOOR == pytest.approx(0.0512933, abs=1e-7)
    c = run.twoph_from_arrays([0, 0, 0], [0, 0, 0], [50, 100, 150], [1, 0, 1], [0.1] * 3, 0.01, hs=(25, 26, 77))
    _close(c, {25: 0.0, 26: 1 / 3, 77: 1.0})
    d = run.twoph_from_arrays([0, 10, 20], [0, -0.1, -0.2], [100, 200, 300], [1, 0, 1], [0.1, 0.2, 0.3], 0.15)
    vals = [d[h] for h in lab.HZ]
    assert all(y >= x - 1e-15 for x, y in zip(vals, vals[1:]))
    hs = tuple(range(1, 3000, 37))
    dd = run.twoph_from_arrays([0, 10, 20], [0, -0.1, -0.2], [100, 200, 300], [1, 0, 1], [0.1, 0.2, 0.3], 0.15, hs=hs)
    vv = [dd[h] for h in hs]
    assert all(y >= x - 1e-15 for x, y in zip(vv, vv[1:]))


def _analog(Lv, rec, end1, rec_date_pos):
    idx = pd.bdate_range("2000-01-03", periods=7)
    return {"t0": 1, "tP": 0, "P": 100.0, "dd0": -0.16, "rec": rec, "R": None if rec is None else rec - 1, "end1": end1,
            "depth_settled": True, "_idx": idx, "_Lv": np.array(Lv, dtype=float), "_last": 6, "t0_date": idx[1],
            "end1_date": idx[end1], "rec_date": None if rec_date_pos is None else idx[rec_date_pos]}, idx


def test_twoph_analog_hand():
    j, idx = _analog([100, 84, 80, 70, 90, 96, 101], 6, 6, 6)
    D = idx[6]
    want = {1: (1, -0.133531, 0.356675, 3, 1), 2: (0, 0.0, 0.356675, 3, 1), 3: (0, 0.0, 0.105361, 2, 1), 4: (0, 0.0, 0.0512933, 1, 1)}
    for e, w in want.items():
        got = run.twoph_analog(j, e, D)
        assert got[0] == w[0] and got[3] == w[3] and got[4] == w[4], e
        assert got[1] == pytest.approx(w[1], abs=1e-6) and got[2] == pytest.approx(w[2], abs=1e-6), e
    assert run.twoph_analog(j, 5, D) is None
    j2, idx2 = _analog([100, 84, 80, 70, 90, 96, 99], None, 5, None)
    got = run.twoph_analog(j2, 1, idx2[6])
    assert got[0] == 1 and got[3] == 3 and got[4] == 0
    assert got[1] == pytest.approx(-0.133531, abs=1e-6) and got[2] == pytest.approx(0.356675, abs=1e-6)


def test_twoph_reduces_to_lm_scaled():
    N = 5040
    idx = pd.bdate_range("1990-01-01", periods=N)
    Lv = np.full(N, 100.0)
    spans = []
    for b in range(8):
        o, Lb = 560 * b, 150 + 50 * b
        Lv[o], Lv[o + 1] = 100.0, 84.0
        for k in range(Lb + 1):
            Lv[o + 2 + k] = 80 + 20 * k / Lb
        spans.append((o, Lb))
    o = 4480
    Lv[o], Lv[o + 1], Lv[o + 2] = 100.0, 84.0, 80.0
    Lv[o + 3:] = 83.0
    analogs = []
    for o_b, Lb in spans:
        rec = o_b + 2 + Lb
        analogs.append({"t0": o_b + 1, "tP": o_b, "P": 100.0, "dd0": -0.16, "rec": rec, "R": Lb + 1, "end1": rec, "depth_settled": True,
                        "y": math.log(80 / 84), "FD": -0.20, "market": "US", "id": f"US:{idx[o_b + 1].date()}", "stratum": "B",
                        "t0_date": idx[o_b + 1], "end1_date": idx[rec], "rec_date": idx[rec], "_idx": idx, "_Lv": Lv, "_last": N - 1})
    tgt = {"t0": o + 1, "tP": o, "P": 100.0, "dd0": -0.16, "rec": None, "R": None, "end1": o + 757, "depth_settled": False, "y": None,
           "FD": None, "market": "US", "id": f"US:{idx[o + 1].date()}", "stratum": "B", "t0_date": idx[o + 1], "end1_date": None,
           "rec_date": None, "_idx": idx, "_Lv": Lv, "_last": N - 1}
    tw = run.twoph(analogs, tgt, 2)["m2"]
    lm = lab.landmark_lm(analogs, tgt, 2)["m2"]
    _close(tw, lm)
    _close(tw, {252: 0.5, 504: 1.0, 756: 1.0, 1260: 1.0})


# ---------------------------------------------------------------- 8·9 홈·검정력
def _dets(ps, allpos=(True, True, True, True)):
    return {k: {"p": p, "allpos": a and p is not None, "evaluable": p is not None} for k, p, a in zip(run.KEYS, ps, allpos)}


def test_holm_hand():
    k1, k2, k3, k4 = run.KEYS
    h = run.holm_labels(_dets((0.010, 0.016, 0.030, 0.040)))
    assert [h[k]["verdict"] for k in run.KEYS] == ["BEATS_LANDMARK", "BEATS_LANDMARK", "FAIL", "FAIL"]
    assert h[k3]["fail_kind"] == "FAIL_UNDERPOWERED" and h[k4]["fail_kind"] == "FAIL_UNDERPOWERED"
    assert h[k4]["holm_reject"] is False and h[k3]["holm_reject"] is False

    h = run.holm_labels(_dets((0.001, 0.014, 0.024, 0.06), allpos=(False, True, True, True)))
    assert h[k1]["holm_reject"] is True and h[k1]["verdict"] == "FAIL" and h[k1]["fail_kind"] == "FAIL"
    assert h[k2]["verdict"] == "BEATS_LANDMARK" and h[k3]["verdict"] == "BEATS_LANDMARK"
    assert h[k4]["verdict"] == "FAIL" and h[k4]["fail_kind"] == "FAIL_UNDERPOWERED"

    h = run.holm_labels(_dets((None, 0.013, 0.5, 0.6)))
    assert h[k1]["verdict"] == "NOT_EVALUABLE" and h[k1]["holm_rank"] is None and h[k1]["holm_reject"] is False
    assert h[k2]["holm_rank"] == 1 and h[k2]["holm_threshold"] == pytest.approx(0.0125)
    assert h[k2]["verdict"] == "FAIL" and h[k2]["fail_kind"] == "FAIL_UNDERPOWERED"
    assert h[k3]["verdict"] == "FAIL" and h[k4]["verdict"] == "FAIL"

    h = run.holm_labels(_dets((0.5, 0.012, 0.012, 0.6)))
    assert (h[k2]["holm_rank"], h[k3]["holm_rank"], h[k1]["holm_rank"], h[k4]["holm_rank"]) == (1, 2, 3, 4)
    assert h[k2]["holm_threshold"] == pytest.approx(0.0125) and h[k3]["holm_threshold"] == pytest.approx(0.05 / 3)
    assert h[k1]["holm_threshold"] == pytest.approx(0.025) and h[k4]["holm_threshold"] == pytest.approx(0.05)
    assert h[k2]["verdict"] == "BEATS_LANDMARK" and h[k3]["verdict"] == "BEATS_LANDMARK"
    assert h[k1]["verdict"] == "FAIL" and h[k4]["verdict"] == "FAIL"


def test_power_holm():
    p = run.power_holm(21)
    assert p["needed_effect_sd"]["first"] == pytest.approx(0.529, abs=1e-2)
    assert p["needed_effect_sd"]["last"] == pytest.approx(0.376, abs=1e-2)
    assert p["min_p"] == 2.0 ** -21
    assert p["pass_prob_first"]["0.5"] == pytest.approx(0.52, abs=0.02)
    q = run.power_holm(1)
    assert q["needed_effect_sd"]["first"] is None and q["needed_effect_sd"]["last"] is None and q["min_p"] is None
    assert all(v is None for v in q["pass_prob_first"].values())


# ---------------------------------------------------------------- 10·11 미래 정보 차단
def _ctx_with_changed_future(data, pos, factor=0.6):
    L2 = data["L"].copy()
    L2.iloc[pos + 1:] = L2.iloc[pos + 1:] * np.linspace(1.0, factor, len(L2) - pos - 1)
    return lab.us_context(dict(data, L=L2))


def _same_preds(a, b):
    assert set(a["pred"]) == set(b["pred"]) == {"BASE", "LM", "SIM", "SIMMIX", "TWOPH", "LMB", "LM_POOL"}
    for name in a["pred"]:
        for x, y in zip(a["pred"][name], b["pred"][name]):
            assert (x is None) == (y is None), name
            if x is None:
                continue
            assert set(x) == set(y)
            for k in x:
                assert x[k] == pytest.approx(y[k], abs=1e-12), (name, k)


def test_no_lookahead_us():
    data = lab.load_us(True)
    ctx = lab.us_context(data)
    recs = ctx["recs"]
    r = next(j for j in recs if j["t0"] > 6000 and lab.landmark_state(j, 63) is not None and lab.landmark_lm(recs, j, 63)["m1"] is not None)
    a = run.pair_calc(recs, recs, r, 63, 200)
    ctx2 = _ctx_with_changed_future(data, r["t0"] + 63)
    r2 = next(j for j in ctx2["recs"] if j["t0"] == r["t0"])
    b = run.pair_calc(ctx2["recs"], ctx2["recs"], r2, 63, 200)
    assert a["pred"]["SIM"][0] is not None and a["pred"]["TWOPH"][1] is not None
    _same_preds(a, b)


def test_no_lookahead_intl():
    intl = lab.synthetic_intl()
    us = lab.us_context(lab.load_us(True))["recs"]
    key = lab.INTL_REGIONS[0]
    mc = lab.market_context(intl[key], key)
    r = next(j for j in mc["eps"] if lab.landmark_state(j, 63) is not None and lab.landmark_state(j, 63)["tau"] >= lab.SIM_MIN_HIST)
    tau = r["t0"] + 63
    a = run.pair_calc(us, us + mc["eps"], r, 63, 200)
    L2 = intl[key].copy()
    L2.iloc[tau + 1:] = L2.iloc[tau + 1:] * 0.5
    mc2 = lab.market_context(L2, key)
    r2 = next(j for j in mc2["eps"] if j["t0"] == r["t0"])
    b = run.pair_calc(us, us + mc2["eps"], r2, 63, 200)
    assert a["pred"]["SIM"][0] is not None
    _same_preds(a, b)


# ---------------------------------------------------------------- 12·13·14 스모크
@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    d = tmp_path_factory.mktemp("smoke")
    assert run.main(["--smoke", "--out", str(d / "o"), "--checkpoint", str(d / "c")]) == 0
    return d / "o"


def test_smoke_end_to_end(smoke):
    res = json.loads((smoke / "results.json").read_text(encoding="utf-8"))
    assert list(res["verdicts"]) == list(run.KEYS)
    assert all(v in run.LABELS for v in res["verdicts"].values())
    assert res["family"]["k"] == 4 and res["family"]["alpha"] == 0.05 and res["family"]["method"] == "holm"
    assert len(res["summary"]) <= 8
    assert [e["key"] for e in res["events"]] == [k for k, _l, _d in lab.v1().EVENTS]
    rep = (smoke / "REPORT.md").read_text(encoding="utf-8")
    for s in ("지금 읽기 (설명용 — 추천 아님)", "사용자가 든 7개 사건", lab.READING_HEADER, "급락 N일째 조견표 (설명용)", "이미 본 것과 그 영향"):
        assert s in rep
    for _k, label, _d in lab.v1().EVENTS:
        assert label in rep
    assert "nan" not in rep.lower().replace("financ", "")
    assert len(res["reading_table"]["rows"]) == 21
    text = (smoke / "predictions.csv").read_text(encoding="utf-8")
    assert text.split("\n")[0] == ",".join(lab.PRED_COLUMNS)
    rows = lab.read_predictions(smoke / "predictions.csv")
    assert rows
    for r in rows:
        assert r["study"] == STUDY
        assert r["landmark"] in (21, 63, 126)
        assert r["model"] in ("BASE", "LM", "SIM", "SIMMIX", "TWOPH")
    base = {(r["market"], r["episode_id"], r["landmark"]) for r in rows if r["model"] == "BASE"}
    for r in rows:
        assert (r["market"], r["episode_id"], r["landmark"]) in base
    for f in ("results.json", "REPORT.md", "predictions.csv"):
        assert (smoke / f).stat().st_size < 256 * 1024


def test_smoke_bounds(smoke):
    rows = lab.read_predictions(smoke / "predictions.csv")
    qc = ("d_q10", "d_q25", "d_q50", "d_q75", "d_q90")
    rc = tuple(f"r_{h}" for h in lab.HZ)
    for r in rows:
        if r["model"] == "TWOPH":
            assert all(r[c] is None for c in qc)
        if r[qc[0]] is not None:
            v = [r[c] for c in qc]
            assert all(b >= a - 1e-9 for a, b in zip(v, v[1:])) and v[-1] <= 1e-9
        if r[rc[0]] is not None:
            v = [r[c] for c in rc]
            assert all(b >= a - 1e-9 for a, b in zip(v, v[1:]))
            assert all(-1e-9 <= x <= 1 + 1e-9 for x in v)


def test_judged_flags(smoke):
    res = json.loads((smoke / "results.json").read_text(encoding="utf-8"))
    rows = lab.read_predictions(smoke / "predictions.csv")
    for r in rows:
        if r["judged_m1"] == 1:
            assert r["market"] != "US" and r["era"] in ("I1", "I2") and r["model"] in ("BASE", "LM", "SIMMIX")
        if r["judged_m2"] == 1:
            assert r["era"] in ("A", "B", "C", "I1", "I2") and r["model"] in ("BASE", "LM", "SIMMIX", "TWOPH")
            if r["market"] == "US":
                assert r["model"] != "SIMMIX"
        if r["model"] == "SIM":
            assert r["judged_m1"] == 0 and r["judged_m2"] == 0
    ids = {r["episode_id"] for r in rows if r["market"] == "US" and r["model"] == "TWOPH" and r["judged_m2"] == 1}
    assert res["detail"]["TWOPH_M2_US"]["n"]["pooled"] == len(ids)
