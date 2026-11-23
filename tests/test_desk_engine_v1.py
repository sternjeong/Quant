"""desk-engine-lab / desk-engine-v1 — 특징·결과 손 계산, 미래 정보 차단, 전문가 예측 성질, 앙상블 가중, 검정·등급, 스모크 전 경로."""

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
STUDY = "desk-engine-v1"


def _mod(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


lab = _mod("desk_engine_lab", "research/jobs/desk-engine-lab/lab.py")
run = _mod("desk_engine_v1", f"research/jobs/{STUDY}/run.py")


@pytest.fixture(scope="module")
def panel():
    m, assets = lab.synthetic_panel(n_assets=6, n_days=2200, seed=3)
    ms = lab.market_state(m)
    origins = m.index[252::lab.STEP]
    frames = {}
    for k, lp in assets.items():
        f = lab.asset_frame(lp, m)
        f[["mdd", "mvolr"]] = ms
        frames[k] = f
    return m, assets, lab.build_points(frames, origins, with_market=True)


# ---------------------------------------------------------------- 상수·job.json
def test_constants_and_job_json():
    from core.research_jobs import validate_job

    assert lab.HORIZONS == (21, 63, 126, 252) and lab.TAUS == (0.1, 0.25, 0.5, 0.75, 0.9)
    assert lab.EXPERTS == ("CLIM", "VOL", "ANALOG", "TILT") and lab.CAP == 12000 and lab.KAPPA == 50.0
    assert len(run.FAMILY) == 6 and run.ALPHA == 0.05 / 6
    assert run.JUDGED_END == "2024-09-30" and run.DATA_END == "2026-11-20"
    data = json.loads((ROOT / "research" / "jobs" / STUDY / "job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, STUDY, ROOT)
    assert not err and job is not None
    assert {"results.json", "REPORT.md", "model.json"} <= set(data["outputs"])


# ---------------------------------------------------------------- 특징·결과
def test_asset_frame_hand_values():
    m, assets, _ = None, None, None
    idx = pd.bdate_range("2010-01-04", periods=700)
    rng = np.random.default_rng(1)
    lp = pd.Series(np.cumsum(rng.normal(0.0003, 0.01, 700)), index=idx)
    f = lab.asset_frame(lp)
    t = 500
    assert f["ret63"].iloc[t] == pytest.approx(lp.iloc[t + 63] - lp.iloc[t])
    assert f["mn21"].iloc[t] == pytest.approx(lp.iloc[t + 1:t + 22].min() - lp.iloc[t])
    assert f["dd"].iloc[t] == pytest.approx(lp.iloc[t] - lp.iloc[t - 251:t + 1].max())
    assert f["trend"].iloc[t] == pytest.approx(lp.iloc[t] - math.log(np.exp(lp.iloc[t - 199:t + 1]).mean()))
    assert f["end63"].iloc[t] == idx[t + 63]
    assert np.isnan(f["ret252"].iloc[-10]) and pd.isna(f["end252"].iloc[-10])
    assert f["ex21"].isna().all()                      # 시장을 안 주면 beat 결과 없음


def test_features_use_no_future():
    idx = pd.bdate_range("2010-01-04", periods=900)
    rng = np.random.default_rng(2)
    lp = pd.Series(np.cumsum(rng.normal(0, 0.01, 900)), index=idx)
    lp2 = lp.copy()
    lp2.iloc[601:] += np.linspace(0, 0.5, 299)        # 600 뒤 미래만 바꿈
    cols = list(lab.OWN) + [f"s{h}" for h in lab.HORIZONS]
    a, b = lab.asset_frame(lp)[cols].iloc[:601], lab.asset_frame(lp2)[cols].iloc[:601]
    pd.testing.assert_frame_equal(a, b)


def test_build_points_sorted_and_finite(panel):
    _, _, P = panel
    assert len(P["date"]) > 400 and P["feats"] == lab.OWN + lab.MKT
    assert (np.diff(P["date"].astype("int64")) >= 0).all()
    assert np.isfinite(P["X"]).all() and np.isfinite(P["S"]).all() and (P["S"] > 0).all()
    assert np.isnan(P["RET"][-1, -1])                  # 마지막 기준일의 12개월 결과는 아직 없음


# ---------------------------------------------------------------- 서고·전문가
def test_library_hides_unrealized_outcomes(panel):
    _, _, P = panel
    a = int(len(P["date"]) * 0.7)
    D = P["date"][a]
    lib = lab.library_at(P, a, D)
    assert lib is not None and len(lib["X"]) <= lab.CAP
    cand = np.where(P["END"][:a, 0] <= D)[0]
    assert len(lib["X"]) == len(cand)
    late = P["END"][cand, 3] > D
    assert late.any() and np.isnan(lib["RET"][late, 3]).all() and np.isfinite(lib["RET"][~late & ~np.isnat(P["END"][cand, 3]), 3]).all()


def test_forecast_block_properties(panel):
    _, _, P = panel
    a = len(P["date"]) - 6
    lib = lab.library_at(P, a, P["date"][a])
    FQ, FP, info = lab.forecast_block(lib, P["X"][a:], P["S"][a:])
    assert FQ.shape == (6, 4, 4, 5) and FP.shape == (6, 4, 4, 3)
    assert np.isfinite(FQ).all() and (np.diff(FQ, axis=-1) >= -1e-12).all()        # 분위수 단조
    assert ((FP >= 0) & (FP <= 1)).all()
    assert np.allclose(FQ[:, 0], FQ[:1, 0])                                         # CLIM 은 자산과 무관
    FQ2, FP2, _ = lab.forecast_block(lib, P["X"][a:], P["S"][a:] * 2)
    assert np.allclose(FQ2[:, 1], FQ[:, 1] * 2)                                     # VOL 은 축척에 비례
    assert (FP2[:, 1, :, 1] >= FP[:, 1, :, 1] - 1e-12).all()                        # 변동성이 크면 낙폭 확률이 크다
    assert np.allclose(FP[:, 3, :, 1], FP[:, 1, :, 1])                              # TILT 의 dd15 = VOL
    assert all(n >= lab.MIN_LIB for n in info["n"])


def test_forecast_block_needs_library(panel):
    _, _, P = panel
    small = {k: P[k][:50] for k in ("X", "S", "RET", "MN", "EX")}
    FQ, FP, _ = lab.forecast_block(small, P["X"][-2:], P["S"][-2:])
    assert np.isnan(FQ).all() and np.isnan(FP).all()


def test_kernel_weights_reach_min_ess():
    rng = np.random.default_rng(5)
    Ul, Uq = rng.random((3000, 5)), rng.random((4, 5))
    W, band = lab.kernel_weights(Uq, Ul)
    ess = W.sum(1) ** 2 / (W ** 2).sum(1)
    assert (ess >= lab.ESS_MIN).all() and (band >= lab.B0).all()


def test_pinball_and_weights():
    q = np.array([[-0.1, -0.05, 0.0, 0.05, 0.1]])
    assert lab.pinball(np.array([0.0]), q)[0] == pytest.approx((0.1 * 0.1 + 0.25 * 0.05 + 0 + 0.25 * 0.05 + 0.1 * 0.1) / 5)
    assert np.allclose(lab.ens_weights(None, 0), 0.25)
    assert np.allclose(lab.ens_weights(np.array([1.0, 0.9, 0.9, 0.9]), lab.WARM_POINTS - 1), 0.25)
    w = lab.ens_weights(np.array([1.0, 0.98, 0.98, 1.0]), 1000)
    assert w.sum() == pytest.approx(1) and w[1] == pytest.approx(w[2]) and w[1] / w[0] == pytest.approx(math.exp(1.0))


def test_combine_is_weighted_average():
    FQ = np.zeros((1, 4, 4, 5))
    FP = np.zeros((1, 4, 4, 3))
    for e in range(4):
        FQ[0, e], FP[0, e] = e, e / 10
    Wt = np.zeros((4, 4, 4))
    Wt[..., 1] = 1.0                                   # 모두 VOL
    q, p = lab.combine(FQ, FP, Wt)
    assert np.allclose(q, 1.0) and np.allclose(p, 0.1)
    FP[0, :, :, 2] = np.nan                            # beat 없는 층
    _, p = lab.combine(FQ, FP, Wt)
    assert np.isnan(p[0, :, 2]).all() and np.allclose(p[0, :, :2], 0.1)


# ---------------------------------------------------------------- 걸어 나가기
@pytest.fixture(scope="module")
def walked(panel):
    _, _, P = panel
    return P, lab.walk(P)


def test_walk_shapes_and_ensemble(walked):
    P, out = walked
    n = len(P["date"])
    assert out["FQ"].shape == (n, 5, 4, 5) and out["weights"].shape == (4, 4, 4)
    assert np.allclose(out["weights"].sum(axis=-1), 1.0)
    done = np.isfinite(out["FQ"][:, -1, 0, 2])
    assert done.sum() > 100 and not done[:20].any()    # 서고가 찰 때까지는 예측 없음
    lo, hi = out["FQ"][done, :4, 0, 2].min(axis=1), out["FQ"][done, :4, 0, 2].max(axis=1)
    ens = out["FQ"][done, -1, 0, 2]
    assert ((ens >= lo - 1e-6) & (ens <= hi + 1e-6)).all()                           # 앙상블은 전문가 사이


def test_walk_uses_no_future(panel, walked):
    P, out = walked
    cut = int(len(P["date"]) * 0.8)
    D = P["date"][cut]
    P2 = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in P.items()}
    for hi in range(4):
        late = ~(P["END"][:, hi] <= D)                 # D 뒤에 실현되는(또는 아직 없는) 결과를 흔든다
        for key in ("RET", "MN", "EX"):
            P2[key][late, hi] = P2[key][late, hi] * 3 + 0.2
    out2 = lab.walk(P2)
    early = P["date"] <= D
    assert np.array_equal(out["FQ"][early], out2["FQ"][early], equal_nan=True)
    assert np.array_equal(out["FP"][early], out2["FP"][early], equal_nan=True)
    assert not np.array_equal(out["FQ"][~early], out2["FQ"][~early], equal_nan=True)


def test_score_layer_cells(walked):
    P, out = walked
    first, last = pd.Timestamp(P["date"][0]), pd.Timestamp(P["date"][-1])
    mid = first + (last - first) / 2
    eras = [("E1", str(first.date()), str(mid.date())), ("E2", str((mid + pd.Timedelta(1, unit="D")).date()), str(last.date()))]
    cells = lab.score_layer(P, out, eras, str(last.date()), 0.05 / 6)
    assert {"21:q", "63:q", "63:dd15", "63:beat", "252:up"} <= set(cells)
    c = cells["63:q"]
    assert c["n_points"] > 0 and set(c["eras"]) == {"E1", "E2"} and c["grade"] in lab.GRADES
    assert 0.5 < c["coverage80"] < 1.0
    assert c["skill"] == pytest.approx(1 - c["mean_loss"]["ENS"] / c["mean_loss"]["CLIM"])


# ---------------------------------------------------------------- 검정·등급
def test_signflip_and_grade():
    assert lab.signflip_p(np.array([1.0, 1.0, 1.0, 1.0])) == pytest.approx(1 / 16)
    assert lab.signflip_p(np.array([0.5])) is None
    p_big = lab.signflip_p(np.full(30, 0.1) + np.linspace(-0.01, 0.01, 30))
    assert p_big < 0.001
    assert lab.signflip_p(np.linspace(-1, 1, 31)) > 0.3
    a = 0.05 / 6
    assert lab.grade(0.05, 0.001, [0.1, 0.2], a) == "강함"
    assert lab.grade(0.05, 0.02, [0.1, 0.2], a) == "보통"
    assert lab.grade(0.05, 0.001, [0.1, -0.2], a) == "약함"
    assert lab.grade(0.05, 0.5, [0.1, 0.2], a) == "약함"
    assert lab.grade(-0.01, 0.001, [0.1, 0.2], a) == "없음"
    assert lab.grade(None, None, [], a) == "없음"


# ---------------------------------------------------------------- 모형 저장·실시간 예측
def test_export_and_live_forecast_match_walk_machinery(panel, walked):
    m, assets, _ = panel
    P, out = walked
    df = lab.export_library(P)
    lib = lab.library_from_frame(pd.read_csv(pd.io.common.StringIO(df.to_csv(index=False))))
    assert lib["feats"] == P["feats"] and len(lib["X"]) == len(df)
    st = lab.latest_state(assets["A00"], m)
    assert st is not None and len(st["x"]) == len(P["feats"]) and st["date"] == assets["A00"].index[-1]
    f = lab.forecast_live(lib, out["weights"], st["x"], st["s"])
    assert set(f["q"]) == set(lab.ALL) and f["q"]["ENS"].shape == (4, 5) and f["p"]["ENS"].shape == (4, 3)
    assert np.isfinite(f["q"]["ENS"]).all() and (np.diff(f["q"]["ENS"], axis=-1) >= -1e-12).all()
    assert lab.latest_state(assets["A00"].iloc[:100], m) is None


# ---------------------------------------------------------------- 스모크 전 경로
@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    d = tmp_path_factory.mktemp("smoke")
    assert run.main(["--smoke", "--out", str(d / "o"), "--checkpoint", str(d / "c")]) == 0
    return d / "o"


def test_smoke_end_to_end(smoke):
    res = json.loads((smoke / "results.json").read_text(encoding="utf-8"))
    assert res["smoke"] is True and set(res["verdicts"]) == {k for k, _, _ in run.FAMILY}
    assert all(v["label"] in run.LABELS and v["grade"] in lab.GRADES for v in res["verdicts"].values())
    assert set(res["summary"]) == set(res["verdicts"])
    assert res["now"] and len(res["now"]["rows"]) == 4
    model = json.loads((smoke / "model.json").read_text(encoding="utf-8"))
    assert set(model["layers"]) == {"market", "industry", "stock"}
    for name, layer in model["layers"].items():
        lib = lab.library_from_frame(pd.read_csv(smoke / layer["library"]))
        assert list(lib["feats"]) == layer["feats"] and len(lib["X"]) >= lab.MIN_LIB
        assert np.asarray(layer["weights"]).shape == (4, 4, 4)
        assert "63:q" in layer["cells"] and layer["cells"]["63:q"]["grade"] in lab.GRADES
    rep = (smoke / "REPORT.md").read_text(encoding="utf-8")
    assert "스모크" in rep and "## 판정" in rep and "지금 읽기" in rep and "## 한계" in rep
    for f in ("results.json", "REPORT.md", "model.json"):
        assert (smoke / f).stat().st_size < 256 * 1024


def test_ledger_has_hypothesis():
    led = json.loads((ROOT / "research" / "frontier" / "hypotheses.json").read_text(encoding="utf-8"))
    hit = [h for h in led["hypotheses"] if h.get("study_id") == STUDY]
    assert len(hit) == 1 and hit[0]["id"] == "H-030"
