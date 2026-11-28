"""desk-engine-v5 — 공용 코드(lab v5)의 성질, 사전 등록 상수·job.json, 판정·제안 규칙, 작은 가짜 층으로 전 경로(결과·보고서·모형 → 실시간 예측), 장부.

스모크 전체 실행(약 4분)은 여기서 돌리지 않는다."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "desk-engine-v5"


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
lab = _mod("desk_engine_lab_v5", "research/jobs/desk-engine-lab-v5/lab.py")
run = _mod("desk_engine_v5", f"research/jobs/{STUDY}/run.py")
run3 = _mod("desk_engine_v3", "research/jobs/desk-engine-v3/run.py")
run4 = _mod("desk_engine_v4", "research/jobs/desk-engine-v4/run.py")


# ---------------------------------------------------------------- 사전 등록 상수
def test_constants_and_job_json():
    from core.research_jobs import validate_job

    assert run.FAMILY == run3.FAMILY and run.ALPHA == 0.05 / 8 and run.LABELS == run3.LABELS
    assert (run.JUDGED_END, run.DATA_END) == (run3.JUDGED_END, run3.DATA_END)              # 앞선 판과 같은 자료·판정 기간
    assert (run.SWITCH_MIN_PASS, run.SWITCH_WORST, run.PREFER_WORST_VS_V3) == (run4.SWITCH_MIN_PASS, run4.SWITCH_WORST, run4.PREFER_WORST_VS_V3)
    assert lab.HX_ADD == ("d5", "dneg", "lev", "levneg", "ddp") and (lab.D_CLIP, lab.LEV_CLIP, lab.DD_CLIP) == (2.0, 4.0, 1.5)
    assert lab.CALIBRATE == {"market": True, "industry": False, "stock": False}
    assert lab.MODELS5 == ("CLIM", "ENS1", "HAR", "V3", "HARX", "ENS5", "V3X", "V5")
    data = json.loads((ROOT / "research" / "jobs" / STUDY / "job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, STUDY, ROOT)
    assert not err and job is not None and data["resumable"] is True
    assert {"results.json", "REPORT.md", "model.json"} <= set(data["outputs"])


def _verdict(label="BEATS_V1", skill=0.01, vs3=0.001, v3="BEATS_V1"):
    return {"label": label, "skill": skill, "skill_vs_v3": vs3, "v3_label": v3}


def test_verdict_rule_needs_every_era_positive():
    d = {"p": 0.001, "eras": {"A": {"skill": 0.01}, "B": {"skill": 0.02}}}
    assert run._passes(d)
    assert not run._passes(dict(d, p=0.01)) and not run._passes(dict(d, p=None))
    assert not run._passes(dict(d, eras={"A": {"skill": -0.0001}, "B": {"skill": 0.02}}))


def test_switch_and_prefer_advice():
    v = {f"K{i}": _verdict() for i in range(3)} | {f"F{i}": _verdict("FAIL", 0.0, 0.0, "FAIL") for i in range(5)}
    a = run.switch_advice(v)
    assert a["propose_switch"] and a["prefer_v5_over_v3"] and (a["n_pass"], a["n_pass_v3"], a["n_judged"]) == (3, 3, 8)
    assert not run.switch_advice(v | {"F0": _verdict("FAIL", -0.006, 0.0, "FAIL")})["propose_switch"]                # 한 열쇠가 1판보다 뚜렷이 나쁨
    assert not run.switch_advice(v | {"K0": _verdict("FAIL", 0.01, 0.001, "BEATS_V1")})["propose_switch"]            # 통과 2개
    b = run.switch_advice(v | {"F0": _verdict("FAIL", 0.0, -0.006, "FAIL")})
    assert b["propose_switch"] and not b["prefer_v5_over_v3"]                                                       # 3판보다 뚜렷이 나쁜 열쇠
    c = run.switch_advice(v | {"F0": _verdict("FAIL", 0.0, 0.0, "BEATS_V1")})
    assert c["propose_switch"] and not c["prefer_v5_over_v3"]                                                       # 3판이 더 많이 통과
    assert not run.switch_advice({k: dict(x, skill_vs_v3=-0.001) for k, x in v.items()})["prefer_v5_over_v3"]       # 3판 대비 평균 음수


# ---------------------------------------------------------------- 회귀 입력
def _panel():
    m, assets = lab1.synthetic_panel(n_assets=6, n_days=2200, seed=3)
    return m, assets


def test_extra_frame_uses_only_the_past():
    m, _ = _panel()
    f = lab.extra_frame(m)
    cut = m.copy()
    cut.iloc[1500:] += np.linspace(0.0, 3.0, len(cut) - 1500)                 # 뒤쪽 가격을 바꿔도 앞쪽 값은 그대로
    assert np.allclose(f.iloc[:1500], lab.extra_frame(cut).iloc[:1500], equal_nan=True)
    r = m.diff()
    assert f["x5"].iloc[100] == pytest.approx(0.5 * np.log((r.iloc[96:101] ** 2).mean()))
    assert f["xneg"].iloc[100] == pytest.approx(0.5 * np.log((r.iloc[80:101].clip(upper=0) ** 2).mean()))
    flat = pd.Series(np.zeros(60), index=m.index[:60])
    assert np.isfinite(lab.extra_frame(flat).iloc[-1]).all()                   # 가격이 멈춰도 값이 유한하다


def test_hx_extend_fills_unknowns_with_neutral_values_and_clips():
    hx = ("h21", "h63", "h252", "hew")
    HX = np.array([[-4.0, -4.1, -4.2, -4.0], [-4.0, -4.1, -4.2, -4.0], [np.nan, -4.1, -4.2, -4.0]])
    XE = np.array([[-3.5, -4.6], [np.nan, np.nan], [-3.5, -4.6]])
    XRAW = np.full((3, len(lab2.XS)), np.nan)
    XRAW[0, lab2.XS.index("rev")], XRAW[0, lab2.XS.index("dd")] = -9.0, -3.0
    out = lab.hx_extend(HX, hx, XE, XRAW)
    assert out.shape == (3, 9) and np.array_equal(out[:, :4], HX, equal_nan=True)
    assert out[0, 4:].tolist() == pytest.approx([0.5, -0.6, -lab.LEV_CLIP, -lab.LEV_CLIP, -lab.DD_CLIP])
    assert out[1, 4:].tolist() == pytest.approx([0.0, lab.DNEG_FILL, 0.0, 0.0, 0.0])                    # 모르면 중립값
    assert np.isfinite(out[2, 4:]).all() and np.isnan(out[2, 0])                                         # 2판 입력이 없는 점은 그대로 없음(회귀 대신 1판 축척)
    up = lab.hx_extend(HX[:1], hx, XE[:1], np.where(np.isnan(XRAW[:1]), 2.0, 2.0))
    assert up[0, 6] == 2.0 and up[0, 7] == 0.0 and up[0, 8] == 0.0                                       # 오른 달: 음수 부분 0, 낙폭은 0 이하


def _layers(extended: bool):
    m, assets = _panel()
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
    return m, assets, mkt, stock


def test_extended_frames_only_add_columns_and_restore_the_lab():
    frame0, attach0 = lab2.asset_frame2, lab2.attach
    _, _, mkt0, stock0 = _layers(False)
    with lab.extended_frames():
        _, _, mkt1, stock1 = _layers(True)
    assert lab2.asset_frame2 is frame0 and lab2.attach is attach0
    for a, b in ((mkt0, mkt1), (stock0, stock1)):
        assert "XE" not in a and b["XE"].shape == (len(b["date"]), 2) and np.isfinite(b["XE"]).mean() > 0.95
        for k, v in a.items():
            if isinstance(v, np.ndarray) and v.dtype.kind in "fiMb":
                assert np.array_equal(v, b[k], equal_nan=v.dtype.kind in "fM"), k
        assert tuple(a["hx"]) == tuple(b["hx"]) and a["names"] == b["names"]


@pytest.fixture(scope="module")
def pairs():
    with lab.extended_frames():
        m, assets, mkt, stock = _layers(True)
    stock5 = lab.extend_points(stock, False)
    return m, assets, (mkt, lab.extend_points(mkt, True, stock5)), (stock, stock5)


def test_extend_points_keeps_points_and_drops_fundamentals(pairs):
    _, _, (mkt, mkt5), (stock, stock5) = pairs
    assert stock5["hx"] == tuple(stock["hx"]) + lab.HX_ADD and stock5["HX"].shape[1] == stock["HX"].shape[1] + 5
    assert np.isnan(stock5["FR"]).all() and np.isfinite(stock["FR"]).any()
    assert np.array_equal(np.isfinite(stock5["HX"]).all(axis=1), np.isfinite(stock["HX"]).all(axis=1))   # 회귀를 쓸 수 있는 점은 3판과 같다
    assert mkt5["borrow"] is stock5 and mkt5["calibrate"] is True and stock5["calibrate"] is False and stock5["borrow"] is None
    assert stock["HX"].shape[1] == len(stock["hx"])                                                      # 원래 점 표는 건드리지 않는다


def test_latest_state_matches_the_backtest_row(pairs):
    m, assets, _, (_, stock5) = pairs
    k = stock5["names"].index("A01")
    i = np.where(stock5["asset"] == k)[0][-1]
    D = pd.Timestamp(stock5["date"][i])
    st = lab.latest_state5(assets["A01"].loc[:D], m.loc[:D])
    assert st is not None and len(st["hx"]) == len(stock5["hx"])
    assert np.allclose(st["hx"], stock5["HX"][i], atol=1e-9)


@pytest.fixture(scope="module")
def walked(pairs):
    _, _, _, (stock, stock5) = pairs
    seen = []
    return stock, stock5, lab.walk5(stock, stock5, progress=lambda tag, i, n: seen.append(tag)), seen


def test_walk5_reproduces_v3_and_picks_v5_by_layer_rule(walked):
    stock, stock5, out, seen = walked
    assert set(seen) == {"3판", "5판"}
    o3 = lab3.walk3(stock)
    for m5, m3 in ((lab.I_CLIM, 0), (lab.I_ENS1, lab3.I_ENS1), (lab.I_HAR, lab3.I_HAR), (lab.I_V3, lab3.I_V3)):
        assert np.array_equal(out["FQ"][:, m5], o3["FQ"][:, m3], equal_nan=True) and np.array_equal(out["LB"][:, m5], o3["LB"][:, m3], equal_nan=True)
    assert np.array_equal(out["FQ"][:, lab.I_V5], out["FQ"][:, lab.I_ENS5], equal_nan=True)              # 종목 층: 보정 전
    assert not np.array_equal(out["FQ"][:, lab.I_HARX], out["FQ"][:, lab.I_HAR], equal_nan=True)         # 변동성 예측이 실제로 달라졌다
    q = out["FQ"][:, lab.I_V5].astype(float)
    ok = np.isfinite(q).all(axis=(1, 2))
    assert ok.sum() > 100 and (np.diff(q[ok], axis=-1) >= -1e-6).all()
    cal = lab.merge(dict(stock5, calibrate=True), o3, _o5(stock5))
    assert np.array_equal(cal["FQ"][:, lab.I_V5], cal["FQ"][:, lab.I_V3X], equal_nan=True)               # 보정을 쓰는 층: 3판 틀 그대로


_O5 = {}


def _o5(stock5):
    if "o" not in _O5:
        _O5["o"] = lab3.walk3(stock5)
    return _O5["o"]


def test_merge_refuses_mismatched_walks(walked):
    _, stock5, out, _ = walked
    o5 = _o5(stock5)
    bad = {k: (v.copy() if k in ("FQ", "FP") else v) for k, v in o5.items()}
    bad["FQ"][:, lab3.I_ENS1] += 0.01
    with pytest.raises(RuntimeError):
        lab.merge(stock5, bad, o5)


def test_scale_cells_report_both_losses(walked):
    _, stock5, out, _ = walked
    eras = [("S1", str(stock5["date"][0])[:10], str(stock5["date"][-1])[:10])]
    s = lab.scale_cells(stock5, out, eras, "2100-01-01", 0.00625)
    assert set(s) == {str(h) for h in lab.HORIZONS}
    for h in s:
        assert set(s[h]) == {"log2", "qlike"} and set(s[h]["log2"]) == {"harx_vs_har", "har_vs_v1"}
        assert s[h]["log2"]["harx_vs_har"]["n_points"] > 0 and s[h]["qlike"]["har_vs_v1"]["skill"] is not None


# ---------------------------------------------------------------- 작은 가짜 층으로 전 경로
@pytest.fixture(scope="module")
def small(tmp_path_factory):
    with lab.extended_frames():
        m, assets, mkt, stock = _layers(True)
    info = {"french": {"source": "test"}, "stock": {"reason": "test"}, "fundamentals": None}
    mp = pytest.MonkeyPatch()
    mp.setattr(run3, "build_layers", lambda smoke: ({"mlp": m}, {"market": mkt, "industry": None, "stock": stock}, info))
    d = tmp_path_factory.mktemp("v5")
    try:
        assert run.main(["--smoke", "--out", str(d / "o"), "--checkpoint", str(d / "c")]) == 0
        # 같은 체크포인트로 다시 실행 — 끝난 층은 다시 걷지 않고(걸으면 실패), 결과는 같아야 한다
        mp.setattr(lab3, "walk3", lambda *a, **k: pytest.fail("끝난 층을 다시 계산함"))
        assert run.main(["--smoke", "--out", str(d / "o2"), "--checkpoint", str(d / "c")]) == 0
    finally:
        mp.undo()
    return d / "o", m, assets


def test_small_end_to_end(small):
    out, _, _ = small
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert res["study"] == STUDY and res["lab_version"] == lab.LAB_VERSION and set(res["verdicts"]) == {k for k, _, _ in run.FAMILY}
    assert all(v["label"] == "NOT_EVALUABLE" for v in res["verdicts"].values()) and res["switch_advice"]["propose_switch"] is False
    assert res["layers"]["industry"] is None and res["layers"]["market"]["calibrate"] is True and res["layers"]["stock"]["calibrate"] is False
    st = res["layers"]["stock"]
    assert st["hx"][-5:] == list(lab.HX_ADD) and set(st["scales"]) == {str(h) for h in lab.HORIZONS}
    c = st["cells"]["63:dd15"]
    assert set(c) >= {"vs_clim", "vs_v1", "vs_v3", "v3_vs_v1", "vs_har", "harx_vs_har", "v3x_vs_v3", "ens5_vs_v1", "expert_skill"}
    assert set(c["expert_skill"]) == set(lab.MODELS5[1:])
    assert res["now"] and len(res["now"]["rows"]) == 4 and all(len(r["q_v5"]) == 5 for r in res["now"]["rows"])
    rep = (out / "REPORT.md").read_text(encoding="utf-8")
    assert "스모크" in rep and "## 판정 (V5 대 1판)" in rep and "변동성 예측 자체의 오차" in rep and "지금 읽기" in rep and "## 한계" in rep and "평가 불가" in rep
    assert len(res["limits"]) == len(run.LIMITS) and "다섯 번째" in res["limits"][0]


def test_resume_from_layer_checkpoints_gives_same_outputs(small):
    out, _, _ = small
    for name in ("results.json", "model.json", "REPORT.md", "library_stock.csv", "library_market.csv"):
        assert (out / name).read_bytes() == (out.parent / "o2" / name).read_bytes(), name
    assert sorted(p.name for p in (out.parent / "c").iterdir()) == ["layer_market.pkl", "layer_stock.pkl"]


def test_small_model_drives_live_forecast(small):
    out, m, assets = small
    model = json.loads((out / "model.json").read_text(encoding="utf-8"))
    assert model["study"] == STUDY and model["lab_version"] == lab.LAB_VERSION
    libs = {n: lab.library_from_frame5(pd.read_csv(out / layer["library"])) for n, layer in model["layers"].items()}
    assert set(libs) == {"market", "stock"}
    for name, layer in model["layers"].items():
        assert layer["fx_grid"] is None and layer["hx"][-5:] == list(lab.HX_ADD) and layer["calibrate"] is (name == "market")
        assert libs[name]["HX"].shape[1] == len(layer["hx"])
        st = lab.latest_state5(assets["A01"], m if name != "market" else None)
        f = lab.forecast_live5(libs[name], layer, st, libs["stock"] if layer["borrow_library"] else None)   # 재무 값 없이 예측한다
        for e in ("V5", "ENS5", "ENS1", "HARX", "CLIM"):
            assert np.isfinite(f["q"][e]).all() and (np.diff(f["q"][e], axis=-1) >= -1e-12).all(), e
        p = f["p"]["V5"][:, :2]
        assert ((p >= 0) & (p <= 1)).all() and np.isfinite(f["p"]["V5"][:, 2]).all() == (name != "market")
        assert np.array_equal(f["q"]["V5"], f["q"]["ENS5"]) == (name != "market")
        assert set(layer["cells"]["63:q"]) >= {"grade", "skill", "grade_vs_v1", "grade_vs_v3", "v1_grade", "coverage80"}


def test_ledger_has_hypothesis():
    led = json.loads((ROOT / "research" / "frontier" / "hypotheses.json").read_text(encoding="utf-8"))
    hit = [h for h in led["hypotheses"] if h.get("study_id") == STUDY]
    assert len(hit) == 1 and hit[0]["id"] == "H-038" and hit[0]["parent"] == "desk-engine-v4"
