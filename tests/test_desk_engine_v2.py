"""desk-engine-lab-v2 / desk-engine-v2 — 1판과 같은 점·같은 ENS1, 새 전문가(HAR·XRANK·BORROW), 증거 가중, 구간 보정, 미래 정보 차단, 판정, 스모크 전 경로."""

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
STUDY = "desk-engine-v2"


def _mod(name, rel):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab1 = _mod("desk_engine_lab", "research/jobs/desk-engine-lab/lab.py")
lab = _mod("desk_engine_lab_v2", "research/jobs/desk-engine-lab-v2/lab.py")
run = _mod("desk_engine_v2", f"research/jobs/{STUDY}/run.py")
run1 = _mod("desk_engine_v1", "research/jobs/desk-engine-v1/run.py")


@pytest.fixture(scope="module")
def panel():
    """(1판 점 표, 2판 점 표, 시장 2판 점 표(업종 서고를 빌림))."""
    m, assets = lab1.synthetic_panel(n_assets=6, n_days=2200, seed=3)
    origins = m.index[252::lab1.STEP]
    ms1, ms2 = lab1.market_state(m), lab.market_state2(m)
    f1, f2 = {}, {}
    for k, lp in assets.items():
        f1[k] = lab1.asset_frame(lp, m)
        f1[k][["mdd", "mvolr"]] = ms1
        f2[k] = lab.asset_frame2(lp, m)
        f2[k][["mdd", "mvolr", "m21", "m252"]] = ms2
    P1 = lab1.build_points(f1, origins, with_market=True)
    P2 = lab.attach(lab1.build_points(f2, origins, with_market=True), f2, True)
    # 시장 점은 21거래일 간격이면 서고 250점에 못 미친다 — 시험에서는 5일 간격으로 늘린다
    fm = {"MKT": lab.asset_frame2(m)}
    Pm = lab.attach(lab1.build_points(fm, m.index[252::5], with_market=False), fm, False, borrow=P2)
    return P1, P2, Pm


@pytest.fixture(scope="module")
def walked(panel):
    P1, P2, _ = panel
    return lab1.walk(P1), lab.walk2(P2)


# ---------------------------------------------------------------- 상수·job.json
def test_constants_and_job_json():
    from core.research_jobs import validate_job

    assert lab.EXPERTS2 == ("CLIM", "VOL", "ANALOG", "TILT", "HAR", "SIXTH") and lab.MODELS[-3:] == ("ENS1", "ENS2", "V2")
    assert (lab.LAMBDA, lab.MIN_DATES, lab.CAL_MIN_DATES, lab.CAL_N0, lab.XR_RIDGE, lab.HAR_CLIP) == (1.0, 12, 36, 20.0, 0.02, 3.0)
    assert len(run.FAMILY) == 8 and run.ALPHA == 0.05 / 8 and run.LABELS[0] == "BEATS_V1"
    assert (run.JUDGED_END, run.DATA_END) == (run1.JUDGED_END, run1.DATA_END)              # 1판과 같은 자료·판정 기간
    data = json.loads((ROOT / "research" / "jobs" / STUDY / "job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, STUDY, ROOT)
    assert not err and job is not None
    assert {"results.json", "REPORT.md", "model.json"} <= set(data["outputs"])


# ---------------------------------------------------------------- 특징
def test_asset_frame2_hand_values_and_no_future():
    idx = pd.bdate_range("2010-01-04", periods=900)
    lp = pd.Series(np.cumsum(np.random.default_rng(1).normal(0.0003, 0.01, 900)), index=idx)
    f = lab.asset_frame2(lp)
    r, t = lp.diff(), 500
    assert f["rv63"].iloc[t] == pytest.approx(math.sqrt((r.iloc[t + 1:t + 64] ** 2).sum()))
    assert f["h21"].iloc[t] == pytest.approx(math.log(r.iloc[t - 20:t + 1].std()))
    assert f["h63"].iloc[t] == pytest.approx(math.log(r.iloc[t - 62:t + 1].std()))
    assert np.isnan(f["rv252"].iloc[-10])
    pd.testing.assert_frame_equal(f[list(lab1.asset_frame(lp).columns)], lab1.asset_frame(lp))   # 1판 열은 그대로
    lp2 = lp.copy()
    lp2.iloc[601:] += np.linspace(0, 0.5, 299)
    pd.testing.assert_frame_equal(f[list(lab.HX_OWN)].iloc[:601], lab.asset_frame2(lp2)[list(lab.HX_OWN)].iloc[:601])


def test_xs_ranks_within_date():
    dates = np.array(["2020-01-01"] * 4 + ["2020-02-01"] * 2, dtype="datetime64[D]")
    raw = np.array([[3.0], [1.0], [2.0], [np.nan], [5.0], [9.0]])
    assert lab.xs_ranks(dates, raw)[:, 0] == pytest.approx([2.5 / 3, 0.5 / 3, 1.5 / 3, 0.5, 0.25, 0.75])


def test_points_identical_to_v1(panel):
    P1, P2, _ = panel
    for k in ("asset", "date", "X", "S", "RET", "MN", "EX", "END", "prio"):
        assert np.array_equal(P1[k], P2[k], equal_nan=True), k
    assert P2["HX"].shape == (len(P1["date"]), 6) and np.isfinite(P2["HX"]).all()
    assert ((P2["XR"] > 0) & (P2["XR"] < 1)).all() and P2["sixth"] == "XRANK"
    a = int(len(P1["date"]) * 0.7)
    D = P1["date"][a]
    l1, l2 = lab1.library_at(P1, a, D), lab.library2(P2, lab.lib_index(P2, a, D), D)
    for k in l1:
        assert np.array_equal(l1[k], l2[k], equal_nan=True), k
    late = ~(P2["END"][lab.lib_index(P2, a, D)] <= D)
    assert late.any() and np.isnan(l2["RV"][late]).all()                                # 실현 안 된 변동성은 가린다


# ---------------------------------------------------------------- 전문가
def test_forecast_block2_properties(panel):
    _, P, _ = panel
    a = len(P["date"]) - 6
    lib = lab.library2(P, lab.lib_index(P, a, P["date"][a]), P["date"][a])
    args = (P["X"][a:], P["S"][a:], P["HX"][a:], P["XR"][a:])
    FQ, FP, _ = lab.forecast_block2(lib, *args, "XRANK")
    FQ1, FP1, _ = lab1.forecast_block(lib, P["X"][a:], P["S"][a:])
    assert FQ.shape == (6, 6, 4, 5) and np.array_equal(FQ[:, :4], FQ1) and np.array_equal(FP[:, :4], FP1)   # 앞 넷은 1판 그대로
    assert np.isfinite(FQ).all() and (np.diff(FQ, axis=-1) >= -1e-12).all() and ((FP >= 0) & (FP <= 1)).all()
    assert not np.allclose(FQ[:, 4], FQ[:, 1]) and not np.allclose(FQ[:, 5], FQ[:, 1])    # HAR·XRANK 는 VOL 과 다르다
    assert np.allclose(FP[:, 5, :, 1], FP[:, 1, :, 1])                                    # XRANK 의 dd15 = VOL
    assert np.ptp(FP[:, 5, :, 2], axis=0).max() > 0                                       # 시장 초과 확률이 자산마다 다르다
    nolib = dict(lib, RV=np.full_like(lib["RV"], np.nan))
    FQn, FPn, _ = lab.forecast_block2(nolib, *args, "XRANK")
    assert np.allclose(FQn[:, 4], FQ[:, 1]) and np.allclose(FPn[:, 4], FP[:, 1])          # 변동성 회귀를 못 하면 VOL
    FQb, FPb, _ = lab.forecast_block2(lib, *args, "BORROW", None)
    assert np.allclose(FQb[:, 5], FQ[:, 1]) and np.allclose(FPb[:, 5], FP[:, 1])          # 빌릴 서고가 없으면 VOL


def test_har_scales_recover_known_relation():
    rng = np.random.default_rng(5)
    HX = rng.normal(-4.5, 0.4, (3000, 2))
    rv = np.exp(0.3 + 0.7 * HX[:, 0] + 0.2 * HX[:, 1] + rng.normal(0, 0.05, 3000))
    base = np.exp(HX[:, 0])
    HXq = np.array([[-4.0, -4.6], [np.nan, -4.6]])
    sl, sq = lab.har_scales(HX, rv, HXq, base, np.array([0.02, 0.02]))
    assert sq[0] == pytest.approx(math.exp(0.3 + 0.7 * -4.0 + 0.2 * -4.6), rel=0.02)
    assert sq[1] == 0.02                                                                   # 입력이 없으면 1판 축척
    assert (sl <= base * lab.HAR_CLIP + 1e-12).all() and (sl >= base / lab.HAR_CLIP - 1e-12).all()
    assert lab.har_scales(HX[:100], rv[:100], HXq, base[:100], np.array([0.02, 0.02])) is None


def test_rank_shift_direction_and_clip():
    rng = np.random.default_rng(6)
    XR = rng.random((4000, 6))
    y = 0.8 * (XR[:, 0] - 0.5) + rng.normal(0, 1, 4000)
    q = np.full((2, 6), 0.5)
    q[0, 0], q[1, 0] = 0.95, 0.05
    d = lab.rank_shift(lab._phi(XR), y, lab._phi(q))
    assert d[0] > 0.2 and d[1] < -0.2 and np.abs(d).max() <= lab.XR_CLIP
    big = lab.rank_shift(lab._phi(XR), 50 * y, lab._phi(q))
    assert big[0] == lab.XR_CLIP and big[1] == -lab.XR_CLIP


def test_borrow_uses_industry_library(panel):
    _, P2, Pm = panel
    assert Pm["sixth"] == "BORROW"
    a = len(Pm["date"]) - 1
    D = Pm["date"][a]
    lib = lab.library2(Pm, lab.lib_index(Pm, a, D), D)
    blib = lab1.library_at(P2, int(np.searchsorted(P2["date"], D, side="left")), D)
    FQ, FP, _ = lab.forecast_block2(lib, Pm["X"][a:], Pm["S"][a:], Pm["HX"][a:], Pm["XR"][a:], "BORROW", blib)
    mb = np.isfinite(blib["RET"][:, 1]) & np.isfinite(blib["MN"][:, 1])
    z = np.sort(blib["RET"][mb, 1] / blib["S"][mb, 1])
    assert FQ[0, 5, 1] == pytest.approx(lab1._uq(z, np.array(lab.TAUS)) * Pm["S"][a, 1])
    assert np.isnan(FP[0, :, :, 2]).all()                                                  # 시장 층에는 beat 가 없다


# ---------------------------------------------------------------- 증거 가중·구간 보정
def test_evidence_weights():
    ev = lab.Evidence(3)
    rng = np.random.default_rng(7)
    for i in range(40):
        base = rng.normal(1.0, 0.05)
        row = np.array([[base, base, base + 0.02 + rng.normal(0, 0.01)]])
        if i == lab.MIN_DATES - 1:
            assert np.allclose(ev.weight(0, 0), 1 / 3)                                     # 기준일이 모자라면 같은 가중
        ev.add(0, 0, row)
        ev.add(3, 0, row)
    w0, w3 = ev.weight(0, 0), ev.weight(3, 0)
    assert w0.sum() == pytest.approx(1.0) and w0[0] == pytest.approx(w0[1]) and w0[2] < 0.01      # 같은 전문가는 같은 가중, 뚜렷이 나쁘면 0 근처
    assert w3[2] > w0[2]                                                                   # 긴 기간은 겹침만큼 덜 깎는다
    ev.add(0, 1, np.array([[np.nan, 1.0, 1.0]]))
    assert ev.n[0, 1] == 0                                                                 # 값이 빠진 점은 세지 않는다
    assert lab.Evidence().weights().shape == (4, 4, 6)


def test_calib_shift_and_shrink():
    cal = lab.Calib()
    rng = np.random.default_rng(8)
    taus = np.array(lab.TAUS)
    zq = np.array([-1.2816, -0.6745, 0.0, 0.6745, 1.2816])
    for i in range(60):
        y = rng.normal(0.0, 1.0, 200) * 0.05                # 실제 폭은 축척의 1배
        q = np.tile(zq * 2 * 0.05, (200, 1))                # 예측은 2배로 넓다
        if i == lab.CAL_MIN_DATES - 1:
            assert not cal.shifts().any()                   # 기준일이 모자라면 이동 없음
        cal.add(0, y, q, np.full(200, 0.05))
    sh = cal.shifts()[0]
    m = 60.0
    assert sh == pytest.approx(-zq * m / (m + lab.CAL_N0), abs=0.06)       # 넓은 범위를 안쪽으로, m/(m+20) 만큼만
    assert not cal.shifts()[1:].any()
    q3 = lab.apply_shift(np.tile(zq * 0.1, (3, 4, 1)), np.full((3, 4), 0.05), np.tile(np.array([0.5, 0, 0, 0, -0.5]), (4, 1)))
    assert (np.diff(q3, axis=-1) >= 0).all() and taus.shape == (5,)


# ---------------------------------------------------------------- 걸어 나가기
def test_walk2_reproduces_v1_ensemble(panel, walked):
    P1, P2, _ = panel
    o1, o2 = walked
    n = len(P2["date"])
    assert o2["FQ"].shape == (n, 9, 4, 5) and o2["weights2"].shape == (4, 4, 6)
    assert np.array_equal(o1["FQ"][:, :4], o2["FQ"][:, :4], equal_nan=True)
    assert np.array_equal(o1["FQ"][:, 4], o2["FQ"][:, lab.I_ENS1], equal_nan=True)         # ENS1 = 1판 ENS
    assert np.array_equal(o1["FP"][:, 4], o2["FP"][:, lab.I_ENS1], equal_nan=True)
    assert np.allclose(o1["weights"], o2["weights1"]) and np.array_equal(o1["realized"], o2["realized"])
    assert np.allclose(o2["weights2"].sum(axis=-1), 1.0)
    done = np.isfinite(o2["FQ"][:, lab.I_V2, 0, 2])
    assert done.sum() > 100 and (np.diff(o2["FQ"][done, lab.I_V2, 0], axis=-1) >= 0).all()
    assert np.array_equal(o2["FP"][:, lab.I_V2], o2["FP"][:, lab.I_ENS2], equal_nan=True)  # 확률은 보정하지 않는다
    assert o2["shifts"][0].any() and not np.array_equal(o2["FQ"][done, lab.I_V2, 0], o2["FQ"][done, lab.I_ENS2, 0])


def test_walk2_uses_no_future(panel, walked):
    _, P, _ = panel
    out = walked[1]
    cut = int(len(P["date"]) * 0.8)
    D = P["date"][cut]
    P2 = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in P.items()}
    for hi in range(4):
        late = ~(P["END"][:, hi] <= D)
        for key in ("RET", "MN", "EX", "RV"):
            P2[key][late, hi] = P2[key][late, hi] * 3 + 0.2
    out2 = lab.walk2(P2)
    early = P["date"] <= D
    assert np.array_equal(out["FQ"][early], out2["FQ"][early], equal_nan=True)
    assert np.array_equal(out["FP"][early], out2["FP"][early], equal_nan=True)
    assert not np.array_equal(out["FQ"][~early], out2["FQ"][~early], equal_nan=True)


def test_market_walk_with_borrow(panel):
    _, _, Pm = panel
    out = lab.walk2(Pm)
    done = np.isfinite(out["FQ"][:, lab.I_V2, 1, 2])
    assert done.sum() > 30
    assert not np.allclose(out["FQ"][done, 5, 1], out["FQ"][done, 1, 1])                   # BORROW 가 VOL 과 다른 값을 낸다
    assert np.isnan(out["FP"][:, :, :, 2]).all()


# ---------------------------------------------------------------- 점수·판정
def test_compare_and_score_layer(panel, walked):
    _, P, _ = panel
    out = walked[1]
    first, last = pd.Timestamp(P["date"][0]), pd.Timestamp(P["date"][-1])
    mid = first + (last - first) / 2
    eras = [("E1", str(first.date()), str(mid.date())), ("E2", str((mid + pd.Timedelta(1, unit="D")).date()), str(last.date()))]
    cells = lab.score_layer2(P, out, eras, str(last.date()), 0.05 / 8)
    assert set(cells) == {f"{h}:{k}" for h in lab.HORIZONS for k in lab.KINDS}
    c = cells["63:q"]
    assert set(c) >= {"vs_clim", "vs_v1", "v1_vs_clim", "ens2_vs_v1", "expert_skill", "coverage80"}
    assert set(c["coverage80"]) == {"ENS1", "ENS2", "V2"} and set(c["expert_skill"]) == set(lab.MODELS[1:])
    L = lab.cell_loss(out, 1, 0).copy()
    L[:, lab.I_V2] = L[:, lab.I_ENS1] * 0.9                                                # 모든 점에서 10% 나은 모형
    r = lab.compare(P, L, lab.I_V2, lab.I_ENS1, 1, eras, str(last.date()), 0.05 / 8, min_blocks=1)
    assert r["skill"] == pytest.approx(0.1) and r["p"] < 0.05 and all(e["skill"] == pytest.approx(0.1) for e in r["eras"].values())
    same = lab.compare(P, L, lab.I_ENS1, lab.I_ENS1, 1, eras, str(last.date()), 0.05 / 8, min_blocks=1)
    assert same["skill"] == 0 and same["grade"] == "없음"


def test_verdict_rules():
    def cell(skill, p, eras, evaluable=True):
        d = {"skill": skill, "p": p, "evaluable": evaluable, "grade": "약함", "eras": {k: {"skill": s} for k, s in eras.items()}}
        return {"vs_v1": d, "vs_clim": d, "v1_vs_clim": d}

    layers = {"market": {"cells": {"63:q": cell(0.02, 0.001, {"A": 0.01, "B": 0.02, "C": 0.03}),
                                   "63:dd15": cell(0.02, 0.001, {"A": 0.01, "B": -0.01, "C": 0.03})}},
              "industry": {"cells": {"63:q": cell(0.02, 0.01, {"A": 0.01}), "63:dd15": cell(0.02, 0.001, {"A": 0.01}, evaluable=False)}},
              "stock": None}
    v = run.verdicts_of(layers)
    assert v["MKT_Q63"]["label"] == "BEATS_V1"
    assert v["MKT_DD63"]["label"] == "FAIL"                 # 한 시대라도 음수면 탈락
    assert v["IND_Q63"]["label"] == "FAIL"                  # p 가 0.05/8 을 넘으면 탈락
    assert [v[k]["label"] for k in ("IND_DD63", "IND_BEAT63", "STK_Q63", "STK_DD63", "STK_BEAT63")] == ["NOT_EVALUABLE"] * 5


# ---------------------------------------------------------------- 스모크 전 경로
@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    d = tmp_path_factory.mktemp("smoke")
    assert run.main(["--smoke", "--out", str(d / "o"), "--checkpoint", str(d / "c")]) == 0
    return d / "o"


def test_smoke_end_to_end(smoke):
    res = json.loads((smoke / "results.json").read_text(encoding="utf-8"))
    assert res["smoke"] is True and set(res["verdicts"]) == {k for k, _, _ in run.FAMILY}
    assert all(v["label"] in run.LABELS for v in res["verdicts"].values())
    assert res["layers"]["market"]["sixth"] == "BORROW" and res["layers"]["stock"]["sixth"] == "XRANK"
    assert res["now"] and len(res["now"]["rows"]) == 4
    rep = (smoke / "REPORT.md").read_text(encoding="utf-8")
    assert "스모크" in rep and "## 판정" in rep and "지금 읽기" in rep and "## 한계" in rep
    for f in ("results.json", "REPORT.md", "model.json"):
        assert (smoke / f).stat().st_size < 256 * 1024


def test_smoke_model_drives_live_forecast(smoke):
    model = json.loads((smoke / "model.json").read_text(encoding="utf-8"))
    assert model["study"] == STUDY and model["lab_version"] == lab.LAB_VERSION
    m, assets = lab1.synthetic_panel(n_assets=3, n_days=900, seed=21)
    libs = {n: lab.library_from_frame2(pd.read_csv(smoke / layer["library"])) for n, layer in model["layers"].items()}
    for name, layer in model["layers"].items():
        lib = libs[name]
        assert list(lib["feats"]) == layer["feats"] and list(lib["hx"]) == layer["hx"]
        st = lab.latest_state2(assets["A01"], m if name != "market" else None)
        blib = libs["industry"] if layer["borrow_library"] else None
        f = lab.forecast_live2(lib, layer["weights2"], layer["shifts"], st, layer["sixth"], layer["xs_grid"], blib, layer["weights1"])
        for e in ("V2", "ENS2", "ENS1", "HAR", layer["sixth"]):
            assert np.isfinite(f["q"][e]).all() and (np.diff(f["q"][e], axis=-1) >= -1e-12).all()
        p = f["p"]["V2"][:, :2]
        assert ((p >= 0) & (p <= 1)).all()
        assert np.isfinite(f["p"]["V2"][:, 2]).all() == (name != "market")
        assert set(layer["cells"]["63:q"]) >= {"grade", "skill", "grade_vs_v1", "v1_grade", "coverage80"}


def test_ledger_has_hypothesis():
    led = json.loads((ROOT / "research" / "frontier" / "hypotheses.json").read_text(encoding="utf-8"))
    hit = [h for h in led["hypotheses"] if h.get("study_id") == STUDY]
    assert len(hit) == 1 and hit[0]["id"] == "H-031"
