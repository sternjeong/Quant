"""desk-engine-v4 실행 스크립트 — 사전 등록 상수·job.json, 판정·제안 규칙, 작은 가짜 층으로 전 경로(결과·보고서·모형 → 실시간 예측), 장부.

공용 코드(lab v4)의 성질은 tests/test_desk_engine_v4_lab.py 가 본다. 스모크 전체 실행(약 6분)은 여기서 돌리지 않는다."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "desk-engine-v4"


def _mod(name, rel):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab1 = _mod("desk_engine_lab", "research/jobs/desk-engine-lab/lab.py")
lab2 = _mod("desk_engine_lab_v2", "research/jobs/desk-engine-lab-v2/lab.py")
lab3 = _mod("desk_engine_lab_v3", "research/jobs/desk-engine-lab-v3/lab.py")
lab = _mod("desk_engine_lab_v4", "research/jobs/desk-engine-lab-v4/lab.py")
run = _mod("desk_engine_v4", f"research/jobs/{STUDY}/run.py")
run3 = _mod("desk_engine_v3", "research/jobs/desk-engine-v3/run.py")


def test_constants_and_job_json():
    from core.research_jobs import validate_job

    assert run.FAMILY == run3.FAMILY and run.ALPHA == 0.05 / 8 and run.LABELS == run3.LABELS
    assert (run.JUDGED_END, run.DATA_END) == (run3.JUDGED_END, run3.DATA_END)              # 앞선 판과 같은 자료·판정 기간
    assert (run.SWITCH_MIN_PASS, run.SWITCH_WORST, run.PREFER_WORST_VS_V3) == (3, -0.005, -0.005)
    assert (lab.STACK_PICKS, lab.DL_RIDGE, lab.DL_CLIP, lab.DL_MIN_EVENTS, lab.DL_ITERS) == (10, 0.05, 1.5, 20, 8)
    assert lab.POOL4 == ("CLIM", "VOL", "HAR", "ANALOG_H", "TILT_H", "SIXTH_H", "DDLOGIT")
    data = json.loads((ROOT / "research" / "jobs" / STUDY / "job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, STUDY, ROOT)
    assert not err and job is not None
    assert {"results.json", "REPORT.md", "model.json"} <= set(data["outputs"])


def _cell(skill, p, eras, evaluable=True, vs3=0.0, v3=None):
    d = lambda s, pp: {"skill": s, "p": pp, "evaluable": evaluable, "grade": "약함", "eras": {k: {"skill": e} for k, e in eras.items()}}  # noqa: E731
    return {"vs_v1": d(skill, p), "vs_v3": d(vs3, 0.5), "v3_vs_v1": d(*(v3 or (skill, p))), "vs_har": d(0.0, 0.5), "vs_clim": d(skill, p),
            "v1_vs_clim": d(skill, p)}


def test_verdict_rules():
    era3 = {"A": 0.01, "B": 0.02, "C": 0.03}
    layers = {"market": {"cells": {"63:q": _cell(0.02, 0.001, era3, vs3=0.004, v3=(0.01, 0.5)),
                                   "63:dd15": _cell(0.02, 0.001, {"A": 0.01, "B": -0.01, "C": 0.03})}},
              "industry": {"cells": {"63:q": _cell(0.02, 0.01, {"A": 0.01}), "63:dd15": _cell(0.02, 0.001, {"A": 0.01}, evaluable=False)}},
              "stock": None}
    v = run.verdicts_of(layers)
    assert v["MKT_Q63"]["label"] == "BEATS_V1" and v["MKT_Q63"]["skill_vs_v3"] == 0.004 and v["MKT_Q63"]["v3_label"] == "FAIL"
    assert v["MKT_DD63"]["label"] == "FAIL" and v["MKT_DD63"]["v3_label"] == "FAIL"        # 한 시대라도 음수면 탈락(3판 재판정도 같은 규칙)
    assert v["IND_Q63"]["label"] == "FAIL"                                                  # p 가 0.05/8 을 넘으면 탈락
    assert [v[k]["label"] for k in ("IND_DD63", "IND_BEAT63", "STK_Q63", "STK_DD63", "STK_BEAT63")] == ["NOT_EVALUABLE"] * 5
    adv = run.switch_advice(v)
    assert adv["propose_switch"] is False and adv["prefer_v4_over_v3"] is False and (adv["n_pass"], adv["n_pass_v3"], adv["n_judged"]) == (1, 0, 3)


def test_switch_and_prefer_advice():
    def key(label, skill, vs3, v3="FAIL"):
        return {"label": label, "skill": skill, "skill_vs_v3": vs3, "v3_label": v3}

    base = {k: key("BEATS_V1", 0.01, 0.002, "BEATS_V1") for k in "abc"}
    adv = run.switch_advice(base | {"d": key("FAIL", -0.004, -0.004)})
    assert adv["propose_switch"] is True and adv["prefer_v4_over_v3"] is True and adv["mean_skill_vs_v3"] == pytest.approx(0.0005)
    assert run.switch_advice(base | {"d": key("FAIL", -0.006, 0.0)})["propose_switch"] is False            # 1판보다 뚜렷이 나빠진 칸
    worse = run.switch_advice(base | {"d": key("FAIL", 0.0, -0.006)})
    assert worse["propose_switch"] is True and worse["prefer_v4_over_v3"] is False                         # 3판보다 뚜렷이 나빠진 칸
    assert run.switch_advice(base | {"d": key("FAIL", 0.0, -0.004, "BEATS_V1")})["prefer_v4_over_v3"] is False   # 3판보다 통과 수가 적다
    assert run.switch_advice({k: key("BEATS_V1", 0.01, -0.001, "BEATS_V1") for k in "abc"})["prefer_v4_over_v3"] is False   # 평균이 0 이하
    none = run.switch_advice({"a": {"label": "NOT_EVALUABLE"}})
    assert none["propose_switch"] is False and none["prefer_v4_over_v3"] is False and none["mean_skill_vs_v3"] is None


# ---------------------------------------------------------------- 작은 가짜 층으로 전 경로
@pytest.fixture(scope="module")
def small(tmp_path_factory):
    """3판 테스트와 같은 가짜 자료(종목 6개)로 run.main 전 경로. 시대가 실제 달력과 달라 판정은 모두 평가 불가다."""
    m, assets = lab1.synthetic_panel(n_assets=6, n_days=2200, seed=3)
    ms2 = lab2.market_state2(m)
    f2 = {}
    for k, lp in assets.items():
        f2[k] = lab2.asset_frame2(lp, m)
        f2[k][["mdd", "mvolr", "m21", "m252"]] = ms2
    P2 = lab2.attach(lab1.build_points(f2, m.index[252::lab1.STEP], with_market=True), f2, True)
    raw = np.random.default_rng(4).normal(size=(len(P2["date"]), len(lab3.FX)))
    raw[P2["date"] < P2["date"][len(P2["date"]) // 4]] = np.nan
    stock = lab3.attach3(P2, raw)
    fm = {"MKT": lab2.asset_frame2(m)}
    mkt = lab3.attach3(lab2.attach(lab1.build_points(fm, m.index[252::5], with_market=False), fm, False, borrow=stock))
    info = {"french": {"source": "test"}, "stock": {"reason": "test"}, "fundamentals": None}
    mp = pytest.MonkeyPatch()
    mp.setattr(run3, "build_layers", lambda smoke: ({"mlp": m}, {"market": mkt, "industry": None, "stock": stock}, info))
    d = tmp_path_factory.mktemp("v4")
    try:
        assert run.main(["--smoke", "--out", str(d / "o"), "--checkpoint", str(d / "c")]) == 0
    finally:
        mp.undo()
    return d / "o", m, assets


def test_small_end_to_end(small):
    out, _, _ = small
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert res["study"] == STUDY and res["lab_version"] == lab.LAB_VERSION and set(res["verdicts"]) == {k for k, _, _ in run.FAMILY}
    assert all(v["label"] == "NOT_EVALUABLE" for v in res["verdicts"].values()) and res["switch_advice"]["propose_switch"] is False
    assert res["layers"]["industry"] is None and res["layers"]["market"]["sixth"] == "BORROW"
    st = res["layers"]["stock"]
    w = np.array(st["weights4"])
    assert w.shape == (4, 4, len(lab.POOL4)) and np.allclose(w.sum(axis=-1), 1.0, atol=1e-3) and np.allclose(np.array(st["blend4"]).sum(axis=-1), 1.0)
    c = st["cells"]["63:dd15"]
    assert set(c) >= {"vs_clim", "vs_v1", "vs_v3", "v3_vs_v1", "stk4_vs_v1", "vs_har", "ddl_vs_har", "expert_skill"}
    assert {"V4", "STK4", "CAL4", "DDLOGIT", "V3", "ENS1"} <= set(c["expert_skill"])
    assert res["now"] and len(res["now"]["rows"]) == 4 and all(len(r["q_v4"]) == 5 for r in res["now"]["rows"])
    rep = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "스모크" in rep and "## 판정 (V4 대 1판)" in rep and "쌓기 가중" in rep and "지금 읽기" in rep and "## 한계" in rep and "평가 불가" in rep
    assert len(res["limits"]) == len(run.LIMITS) and "네 번째" in res["limits"][0]


def test_small_model_drives_live_forecast(small):
    import pandas as pd

    out, m, assets = small
    model = json.loads((out / "model.json").read_text(encoding="utf-8"))
    assert model["study"] == STUDY and model["lab_version"] == lab.LAB_VERSION and model["pool"] == list(lab.POOL4) and "fx" not in model
    libs = {n: lab.library_from_frame4(pd.read_csv(out / layer["library"])) for n, layer in model["layers"].items()}
    assert set(libs) == {"market", "stock"}
    for name, layer in model["layers"].items():
        assert "fx_grid" not in layer and set(layer) >= {"weights1", "weights4", "shifts4", "blend4", "cal_active4", "sixth", "cells"}
        st = lab2.latest_state2(assets["A01"], m if name != "market" else None)
        f = lab.forecast_live4(libs[name], layer, st, libs["stock"] if layer["borrow_library"] else None)   # 재무 값 없이 예측한다
        for e in ("V4", "CAL4", "STK4", "ENS1", "HAR", "DDLOGIT"):
            assert np.isfinite(f["q"][e]).all() and (np.diff(f["q"][e], axis=-1) >= -1e-12).all(), e
        p = f["p"]["V4"][:, :2]
        assert ((p >= 0) & (p <= 1)).all() and np.isfinite(f["p"]["V4"][:, 2]).all() == (name != "market")
        assert set(layer["cells"]["63:q"]) >= {"grade", "skill", "grade_vs_v1", "grade_vs_v3", "v1_grade", "coverage80"}


def test_ledger_has_hypothesis():
    led = json.loads((ROOT / "research" / "frontier" / "hypotheses.json").read_text(encoding="utf-8"))
    hit = [h for h in led["hypotheses"] if h.get("study_id") == STUDY]
    assert len(hit) == 1 and hit[0]["id"] == "H-037" and hit[0]["parent"] == "desk-engine-v3"
