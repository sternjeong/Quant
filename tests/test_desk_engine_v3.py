"""desk-engine-lab-v3 / desk-engine-v3 — 2판과 같은 ENS1·V2, 변동성 회귀 축척 위 전문가, 재무 순위, 한 표 나누기, 핀볼 기준 보정, 미래 정보 차단, 판정, 스모크 전 경로."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
STUDY = "desk-engine-v3"


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
lab = _mod("desk_engine_lab_v3", "research/jobs/desk-engine-lab-v3/lab.py")
run = _mod("desk_engine_v3", f"research/jobs/{STUDY}/run.py")
run2 = _mod("desk_engine_v2", "research/jobs/desk-engine-v2/run.py")


@pytest.fixture(scope="module")
def panel():
    """(2판 점 표, 3판 점 표(앞 1/4 과 자산 하나는 재무가 없음), 시장 3판 점 표(업종 서고를 빌림))."""
    m, assets = lab1.synthetic_panel(n_assets=6, n_days=2200, seed=3)
    origins = m.index[252::lab1.STEP]
    ms2 = lab2.market_state2(m)
    f2 = {}
    for k, lp in assets.items():
        f2[k] = lab2.asset_frame2(lp, m)
        f2[k][["mdd", "mvolr", "m21", "m252"]] = ms2
    P2 = lab2.attach(lab1.build_points(f2, origins, with_market=True), f2, True)
    raw = np.random.default_rng(4).normal(size=(len(P2["date"]), len(lab.FX)))
    raw[P2["date"] < P2["date"][len(P2["date"]) // 4]] = np.nan
    raw[::7, 1] = np.nan
    raw[P2["asset"] == 0] = np.nan                                                         # 재무 기록이 없는 회사
    P3 = lab.attach3(P2, raw)
    fm = {"MKT": lab2.asset_frame2(m)}
    Pm = lab.attach3(lab2.attach(lab1.build_points(fm, m.index[252::5], with_market=False), fm, False, borrow=P3))
    return P2, P3, Pm


@pytest.fixture(scope="module")
def walked(panel):
    P2, P3, _ = panel
    return lab2.walk2(P2), lab.walk3(P3)


def _block(P, back=6):
    a = len(P["date"]) - back
    D = P["date"][a]
    lib = lab.library3(P, lab2.lib_index(P, a, D), D)
    return lib, (P["X"][a:], P["S"][a:], P["HX"][a:], P["XR"][a:], P["FR"][a:]), a


# ---------------------------------------------------------------- 상수·job.json
def test_constants_and_job_json():
    from core.research_jobs import validate_job

    assert lab.EXPERTS3[:6] == lab2.EXPERTS2 and lab.POOL == ("CLIM", "VOL", "HAR", "ANALOG_H", "TILT_H", "SIXTH_H", "FUND")
    assert lab.MODELS[-6:] == ("ENS1", "ENS2", "V2", "ENS3", "CAL3", "V3") and lab.FX == ("gp_assets", "rev_yoy", "rev_acc", "ni_yoy")
    assert len(run.FAMILY) == 8 and run.ALPHA == 0.05 / 8 and run.LABELS[0] == "BEATS_V1" and run.FAMILY == run2.FAMILY
    assert (run.JUDGED_END, run.DATA_END) == (run2.JUDGED_END, run2.DATA_END)              # 1판·2판과 같은 자료·판정 기간
    assert (run.SWITCH_MIN_PASS, run.SWITCH_WORST, run.FUND_LAG_DAYS) == (3, -0.005, 1)
    data = json.loads((ROOT / "research" / "jobs" / STUDY / "job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, STUDY, ROOT)
    assert not err and job is not None
    assert {"results.json", "REPORT.md", "model.json"} <= set(data["outputs"])


# ---------------------------------------------------------------- 입력
def test_xs_ranks_nan_and_attach3(panel):
    dates = np.array(["2020-01-01"] * 4 + ["2020-02-01"] * 2, dtype="datetime64[D]")
    raw = np.array([[3.0], [1.0], [2.0], [np.nan], [5.0], [9.0]])
    r = lab.xs_ranks_nan(dates, raw)[:, 0]
    assert r[[0, 1, 2, 4, 5]] == pytest.approx([2.5 / 3, 0.5 / 3, 1.5 / 3, 0.25, 0.75]) and np.isnan(r[3])   # 아는 값끼리만 순위, 모르면 NaN
    P2, P3, Pm = panel
    for k in ("asset", "date", "X", "S", "RET", "MN", "EX", "END", "prio", "HX", "RV", "XR"):
        assert np.array_equal(P2[k], P3[k], equal_nan=True), k                             # 점 집합·2판 입력은 그대로
    assert np.isnan(P3["FR"][:10]).all() and np.isfinite(P3["FR"][-1]).any() and np.isnan(Pm["FR"]).all()
    F = lab.phi_nan(np.array([[0.5, np.nan, 1.0, 0.0]]))
    assert F.shape == (1, 8) and F[0, 1] == 0 and F[0, 5] == 0 and F[0, 2] > 0 and F[0, 3] < 0   # 모르는 값의 항은 0


def test_fund_values_and_lag():
    v = {"gp_assets": 0.3, "rev_yoy": 0.10, "rev_yoy_prev": 0.04, "ni_yoy": None}
    out = run.fund_values(v)
    assert out[:3] == pytest.approx([0.3, 0.10, 0.06]) and np.isnan(out[3]) and np.isnan(run.fund_values(None)).all()
    assert np.isnan(run.fund_values({"gp_assets": None, "rev_yoy": 0.1, "rev_yoy_prev": None})[2])   # 가속은 둘 다 알아야
    seen = []
    P = {"date": np.array(["2020-03-02", "2020-04-01"], dtype="datetime64[D]"), "asset": np.array([0, 0]), "names": ["AAA"]}
    raw, info = run.fund_raw(P, lambda name, asof: seen.append((name, asof)) or (v if asof >= date(2020, 3, 15) else None))
    assert seen == [("AAA", date(2020, 3, 1)), ("AAA", date(2020, 3, 31))]                 # 기준일 전날까지 공시된 것만
    assert np.isnan(raw[0]).all() and raw[1, 0] == 0.3 and info["points_known"] == 1 and info["tickers_with_fundamentals"] == 1


def test_disk_fundamentals_point_in_time(tmp_path, monkeypatch):
    from core import fundamentals_pit as fp

    rec = {"ticker": "AAA", "fetched_at": "2020-01-01T00:00:00+00:00", "sic": 1, "earnings_dates": [],
           "facts": {"gross_profit": [["2018-01-01", "2018-12-31", 40.0, "2019-02-20", "10-K"]],
                     "assets": [[None, "2018-12-31", 100.0, "2019-02-20", "10-K"]], "revenue": [], "net_income": [], "cost_of_revenue": []}}
    (tmp_path / "AAA.json").write_text(json.dumps(rec), encoding="utf-8")
    (tmp_path / "GONE.json").write_text(json.dumps({"ticker": "GONE", "fetched_at": "2020-01-01T00:00:00+00:00", "missing": "cik"}), encoding="utf-8")
    monkeypatch.setattr(fp, "STORE_DIR", tmp_path)
    view = run.DiskFundamentals()
    assert view.store.fetch is False                                                       # 받지 않는다(네트워크 없음)
    assert view("AAA", date(2019, 2, 19)) is None                                          # 공시 전에는 모른다
    assert view("AAA", date(2019, 2, 20))["gp_assets"] == pytest.approx(0.4)
    assert view("GONE", date(2019, 6, 1)) is None and view("NOFILE", date(2019, 6, 1)) is None


# ---------------------------------------------------------------- 전문가
def test_forecast_block3_properties(panel):
    _, P, _ = panel
    lib, args, _ = _block(P)
    FQ, FP, S3q, _ = lab.forecast_block3(lib, *args, "XRANK")
    FQ2, FP2, _ = lab2.forecast_block2(lib, *args[:4], "XRANK")
    assert FQ.shape == (6, 10, 4, 5) and np.array_equal(FQ[:, :6], FQ2) and np.array_equal(FP[:, :6], FP2)   # 앞 여섯은 2판 그대로
    assert np.isfinite(FQ).all() and (np.diff(FQ, axis=-1) >= -1e-12).all() and ((FP >= 0) & (FP <= 1)).all()
    Sl3, Sq3 = lab.har_base(lib, args[2], args[1])
    assert np.array_equal(S3q, Sq3) and not np.allclose(S3q, args[1])
    FQh, FPh, _ = lab1.forecast_block(dict(lib, S=Sl3), args[0], Sq3)
    assert np.allclose(FQh[:, 1], FQ[:, lab.I_HAR]) and np.allclose(FPh[:, 1], FP[:, lab.I_HAR])              # 그 축척의 VOL = HAR
    assert np.array_equal(FQh[:, 2], FQ[:, lab.I_AH]) and np.array_equal(FQh[:, 3], FQ[:, lab.I_TH])
    assert not np.allclose(FQ[:, lab.I_AH], FQ[:, 2]) and not np.allclose(FQ[:, lab.I_TH], FQ[:, 3])          # 1판 축척의 것과 다르다
    for e in (lab.I_TH, lab.I_SH, lab.I_FUND):
        assert np.allclose(FP[:, e, :, 1], FP[:, lab.I_HAR, :, 1])                                            # dd15 는 HAR 과 같다
    assert not np.allclose(FQ[:, lab.I_SH], FQ[:, lab.I_HAR]) and not np.allclose(FQ[:, lab.I_FUND], FQ[:, lab.I_HAR])
    assert np.ptp(FP[:, lab.I_FUND, :, 2], axis=0).max() > 0
    # 1판 축척을 넣으면 shifted 는 2판 XRANK 와 같다
    mh = np.isfinite(lib["RET"][:, 1]) & np.isfinite(lib["MN"][:, 1])
    sl = lib["S"][mh, 1]
    q, up, beat = lab.shifted(lib["RET"][mh, 1] / sl, lib["EX"][mh, 1] / sl, np.ones(int(mh.sum()), bool), lab2._phi(lib["XR"])[mh],
                              lab2._phi(args[3]), np.ones(6, bool), args[1][:, 1])
    assert np.allclose(q, FQ2[:, 5, 1]) and np.allclose(up, FP2[:, 5, 1, 0]) and np.allclose(beat, FP2[:, 5, 1, 2])


def test_fund_falls_back_to_har_when_unknown(panel):
    _, P, _ = panel
    lib, args, _ = _block(P)
    FR = args[4].copy()
    FR[:3] = np.nan
    FQ, FP, _, _ = lab.forecast_block3(lib, *args[:4], FR, "XRANK")
    assert np.allclose(FQ[:3, lab.I_FUND], FQ[:3, lab.I_HAR], atol=1e-12) and np.allclose(FP[:3, lab.I_FUND], FP[:3, lab.I_HAR], atol=1e-12)
    assert not np.allclose(FQ[3:, lab.I_FUND], FQ[3:, lab.I_HAR])
    for kw in (dict(lib=dict(lib, FR=np.full_like(lib["FR"], np.nan)), FR=args[4]), dict(lib=lib, FR=np.full_like(FR, np.nan))):
        FQn, FPn, _, _ = lab.forecast_block3(kw["lib"], *args[:4], kw["FR"], "XRANK")
        assert np.allclose(FQn[:, lab.I_FUND], FQn[:, lab.I_HAR], atol=1e-12) and np.allclose(FPn[:, lab.I_FUND], FPn[:, lab.I_HAR], atol=1e-12)
    nolib = dict(lib, RV=np.full_like(lib["RV"], np.nan))                                  # 변동성 회귀를 못 하면 1판 축척으로 돌아간다
    FQv, _, S3v, _ = lab.forecast_block3(nolib, *args, "XRANK")
    assert np.array_equal(S3v, args[1]) and np.allclose(FQv[:, lab.I_AH], FQv[:, 2]) and np.allclose(FQv[:, lab.I_TH], FQv[:, 3])


def test_shifted_uses_only_known_rows_and_direction():
    rng = np.random.default_rng(6)
    n = 4000
    FR = rng.random((n, 4))
    z = 0.8 * (FR[:, 0] - 0.5) + rng.normal(0, 1, n)
    known = np.arange(n) >= 1000
    z[~known] += 5.0                                                                       # 재무를 모르는 점의 결과는 회귀에 들어가지 않는다
    FR[~known] = np.nan
    Fq = np.full((3, 4), 0.5)
    Fq[0, 0], Fq[1, 0], Fq[2] = 0.95, 0.05, np.nan
    qmask = np.isfinite(Fq).any(axis=1)
    q, up, beat = lab.shifted(z, None, known, lab.phi_nan(FR)[known], lab.phi_nan(Fq), qmask, np.ones(3))
    base = lab1._uq(np.sort(z), np.array(lab.TAUS))
    d = q[:, 2] - base[2]
    assert beat is None and d[0] > 0.2 and d[1] < -0.2 and d[2] == 0 and up[0] > up[2] > up[1]
    assert np.allclose(d[:2], lab2.rank_shift(lab.phi_nan(FR)[known], z[known], lab.phi_nan(Fq))[:2])


def test_borrow_h_uses_har_scaled_industry_library(panel):
    _, P3, Pm = panel
    a = len(Pm["date"]) - 1
    D = Pm["date"][a]
    lib = lab.library3(Pm, lab2.lib_index(Pm, a, D), D)
    blib = lab2.library2(P3, lab2.lib_index(P3, int(np.searchsorted(P3["date"], D, side="left")), D), D)
    args = (Pm["X"][a:], Pm["S"][a:], Pm["HX"][a:], Pm["XR"][a:], Pm["FR"][a:])
    FQ, FP, S3q, _ = lab.forecast_block3(lib, *args, "BORROW", blib)
    mb = np.isfinite(blib["RET"][:, 1]) & np.isfinite(blib["MN"][:, 1])
    sb = lab2.har_scales(blib["HX"][mb], blib["RV"][mb, 1], blib["HX"][mb][:1], blib["S"][mb, 1], blib["S"][mb, 1][:1])[0]
    z = np.sort(blib["RET"][mb, 1] / sb)
    assert FQ[0, lab.I_SH, 1] == pytest.approx(lab1._uq(z, np.array(lab.TAUS)) * S3q[0, 1])
    assert not np.allclose(FQ[0, lab.I_SH, 1], FQ[0, 5, 1]) and np.isnan(FP[0, :, :, 2]).all()
    assert np.allclose(FQ[:, lab.I_FUND], FQ[:, lab.I_HAR]) and np.allclose(FP[:, lab.I_FUND, :, :2], FP[:, lab.I_HAR, :, :2])   # 시장 층에는 재무가 없다
    FQn, _, _, _ = lab.forecast_block3(lib, *args, "BORROW", None)
    assert np.allclose(FQn[:, lab.I_SH], FQn[:, lab.I_HAR])                                # 빌릴 서고가 없으면 HAR


# ---------------------------------------------------------------- 한 표 나누기·보정
def test_dedupe_shares_one_vote():
    F = np.array([[1.0, 2.0, 2.0, 3.0], [1.5, 2.5, 2.5, 3.5]])
    assert lab.dedupe(np.full(4, 0.25), F) == pytest.approx([1 / 3, 1 / 6, 1 / 6, 1 / 3])
    assert lab.dedupe(np.array([0.1, 0.6, 0.2, 0.1]), F) == pytest.approx(np.array([0.1, 0.3, 0.1, 0.1]) / 0.6)   # 묶음의 표 = 구성원 가중의 평균
    F2 = F.copy()
    F2[1, 2] += 1e-6                                                                       # 한 질의라도 다르면 다른 전문가
    assert lab.dedupe(np.full(4, 0.25), F2) == pytest.approx([0.25] * 4)
    Fn = np.full((2, 3), np.nan)
    assert lab.dedupe(np.full(3, 1 / 3), Fn) == pytest.approx([1 / 3] * 3)
    FQ = np.random.default_rng(1).normal(size=(3, 7, 4, 5))
    FP = np.random.default_rng(2).random((3, 7, 4, 3))
    FP[:, 4:, :, 1] = FP[:, 2:3, :, 1]                                                     # dd15: 전문가 2·4·5·6 이 같은 값
    Wt = lab.pool_weights(np.full((4, 4, 7), 1 / 7), FQ, FP)
    assert np.allclose(Wt.sum(axis=-1), 1.0) and np.allclose(Wt[:, 0], 1 / 7)
    assert np.allclose(Wt[:, 2], np.array([1, 1, 0.25, 1, 0.25, 0.25, 0.25]) / 4)


def test_calib3_minimises_pinball_and_shrinks():
    rng = np.random.default_rng(8)
    cal, cal_eq = lab.Calib3(), lab.Calib3()
    ys, qs, ss = [], [], []
    zq = np.array([-1.2816, -0.6745, 0.0, 0.6745, 1.2816])
    for i in range(60):
        s = np.where(rng.random(200) < 0.5, 0.02, 0.10)
        y = rng.normal(0.0, 1.0, 200) * s * np.where(s > 0.05, 1.0, 2.0)                  # 축척이 큰 점은 폭이 맞고, 작은 점은 실제가 2배 넓다
        q = zq[None, :] * s[:, None]
        if i == lab2.CAL_MIN_DATES - 1:
            assert not cal.shifts().any() and not cal.active().any()                       # 기준일이 모자라면 이동 없음
        cal.add(0, y, q, s)
        cal_eq.add(0, y, q, np.full(200, 0.05) * 0 + s.mean())
        ys.append(y), qs.append(q), ss.append(s)
    y, q, s = np.concatenate(ys), np.concatenate(qs), np.concatenate(ss)
    sh, m = cal.shifts()[0], 60.0
    raw = sh / (m / (m + lab2.CAL_N0))
    assert cal.active().tolist() == [True, False, False, False] and not cal.shifts()[1:].any()
    tau = np.array(lab.TAUS)

    def loss(c, j):
        e = y - q[:, j] - s * c
        return np.maximum(tau[j] * e, (tau[j] - 1) * e).sum()

    for j in (0, 4):
        grid = raw[j] + np.linspace(-0.3, 0.3, 61)
        assert loss(raw[j], j) <= min(loss(c, j) for c in grid) + 1e-9                     # 줄이기 전 이동이 과거 핀볼 손실을 가장 작게 한다
    assert raw[0] < -0.05 and raw[4] > 0.05                                                # 좁은 범위를 바깥으로
    # 같은 가중이면 보통 분위수(1판 _uq)와 같다
    c2 = lab.Calib3()
    for _ in range(lab2.CAL_MIN_DATES):
        c2.add(1, y[:50], q[:50], np.full(50, 0.05))
    u = (y[:50, None] - q[:50]) / 0.05
    U = np.tile(u, (lab2.CAL_MIN_DATES, 1))
    m2 = lab2.CAL_MIN_DATES * 21 / 63
    assert c2.shifts()[1] == pytest.approx([lab1._uq(np.sort(U[:, j]), tau[j:j + 1])[0] * m2 / (m2 + lab2.CAL_N0) for j in range(5)])


def test_assemble3_blend_and_inactive():
    rng = np.random.default_rng(9)
    FQ = np.sort(rng.normal(size=(4, 10, 4, 5)), axis=-1)
    FP = rng.random((4, 10, 4, 3))
    S = np.full((4, 4), 0.1)
    base = np.full((4, 4, 7), 1 / 7)
    sh = np.tile(np.array([-0.5, -0.2, 0.0, 0.2, 0.5]), (4, 1))
    blend = np.tile(np.array([0.25, 0.75]), (4, 1))
    act = np.array([True, False, True, False])
    q, p, qc, qv = lab.assemble3(FQ, FP, S, base, sh, blend, act)
    assert np.allclose(q, FQ[:, lab.POOL_IDX].mean(axis=1)) and np.allclose(p, FP[:, lab.POOL_IDX].mean(axis=1))
    assert np.allclose(qc[:, 0], q[:, 0] + 0.1 * sh[0]) and np.array_equal(qc[:, 1], q[:, 1]) and np.array_equal(qv[:, 1], q[:, 1])   # 보정 전에는 그대로
    assert np.allclose(qv[:, 0], 0.25 * q[:, 0] + 0.75 * qc[:, 0]) and (np.diff(qv, axis=-1) >= 0).all()


# ---------------------------------------------------------------- 걸어 나가기
def test_walk3_reproduces_v2(panel, walked):
    _, P3, _ = panel
    o2, o3 = walked
    n = len(P3["date"])
    assert o3["FQ"].shape == (n, 16, 4, 5) and o3["weights3"].shape == (4, 4, 7) and o3["blend"].shape == (4, 2)
    assert np.array_equal(o2["FQ"][:, :6], o3["FQ"][:, :6], equal_nan=True) and np.array_equal(o2["FP"][:, :6], o3["FP"][:, :6], equal_nan=True)
    for i2, i3 in ((lab2.I_ENS1, lab.I_ENS1), (lab2.I_ENS2, lab.I_ENS2), (lab2.I_V2, lab.I_V2)):   # 비교 대상은 2판 걸어 나가기와 같다
        assert np.array_equal(o2["FQ"][:, i2], o3["FQ"][:, i3], equal_nan=True) and np.array_equal(o2["FP"][:, i2], o3["FP"][:, i3], equal_nan=True)
        assert np.array_equal(o2["LQ"][:, i2], o3["LQ"][:, i3], equal_nan=True)
    assert np.allclose(o2["weights1"], o3["weights1"]) and np.allclose(o2["weights2"], o3["weights2"]) and np.allclose(o2["shifts"], o3["shifts2"])
    assert np.allclose(o3["weights3"].sum(axis=-1), 1.0) and np.allclose(o3["blend"].sum(axis=-1), 1.0)
    done = np.isfinite(o3["FQ"][:, lab.I_V3, 0, 2])
    assert done.sum() > 100 and (np.diff(o3["FQ"][done, lab.I_V3, 0], axis=-1) >= -1e-6).all()
    assert np.array_equal(o3["FP"][:, lab.I_V3], o3["FP"][:, lab.I_ENS3], equal_nan=True)   # 확률은 보정하지 않는다
    ca = o3["CA"][:, 0]
    assert ca.any() and (~ca & done).any() and o3["cal_active"][0] and o3["shifts3"][0].any()
    assert np.array_equal(o3["FQ"][~ca & done, lab.I_V3, 0], o3["FQ"][~ca & done, lab.I_ENS3, 0])           # 보정 시작 전: V3 = ENS3
    assert not np.array_equal(o3["FQ"][ca, lab.I_V3, 0], o3["FQ"][ca, lab.I_ENS3, 0])
    lo = np.minimum(o3["FQ"][ca, lab.I_ENS3, 0], o3["FQ"][ca, lab.I_CAL3, 0]) - 1e-6
    hi = np.maximum(o3["FQ"][ca, lab.I_ENS3, 0], o3["FQ"][ca, lab.I_CAL3, 0]) + 1e-6
    assert ((o3["FQ"][ca, lab.I_V3, 0] >= lo) & (o3["FQ"][ca, lab.I_V3, 0] <= hi)).all()   # V3 는 보정 전·후 사이
    assert o3["blend_dates"][0] > 0 and np.isfinite(o3["S3"][done]).all()
    known = np.isfinite(P3["FR"]).any(axis=1) & done
    assert not np.allclose(o3["FQ"][known, lab.I_FUND, 0], o3["FQ"][known, lab.I_HAR, 0])
    early = ~np.isfinite(P3["FR"]).any(axis=1) & done
    assert early.any() and np.allclose(o3["FQ"][early, lab.I_FUND], o3["FQ"][early, lab.I_HAR], atol=1e-6, equal_nan=True)


def test_walk3_uses_no_future(panel, walked):
    _, P, _ = panel
    out = walked[1]
    cut = int(len(P["date"]) * 0.8)
    D = P["date"][cut]
    Pf = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in P.items()}
    for hi in range(4):
        late = ~(P["END"][:, hi] <= D)
        for key in ("RET", "MN", "EX", "RV"):
            Pf[key][late, hi] = Pf[key][late, hi] * 3 + 0.2
    Pf["FR"][P["date"] > D] = 0.9                                                          # 뒤 기준일의 재무도 앞 예측을 못 바꾼다
    out2 = lab.walk3(Pf)
    early = P["date"] <= D
    assert np.array_equal(out["FQ"][early], out2["FQ"][early], equal_nan=True)
    assert np.array_equal(out["FP"][early], out2["FP"][early], equal_nan=True)
    assert not np.array_equal(out["FQ"][~early], out2["FQ"][~early], equal_nan=True)


def test_market_walk_with_borrow(panel):
    _, _, Pm = panel
    out = lab.walk3(Pm)
    done = np.isfinite(out["FQ"][:, lab.I_V3, 1, 2])
    assert done.sum() > 30
    assert not np.allclose(out["FQ"][done, lab.I_SH, 1], out["FQ"][done, lab.I_HAR, 1])    # BORROW_H 가 HAR 과 다른 값을 낸다
    assert np.isnan(out["FP"][:, :, :, 2]).all()


# ---------------------------------------------------------------- 점수·판정
def test_score_layer3(panel, walked):
    _, P, _ = panel
    out = walked[1]
    first, last = pd.Timestamp(P["date"][0]), pd.Timestamp(P["date"][-1])
    mid = first + (last - first) / 2
    eras = [("E1", str(first.date()), str(mid.date())), ("E2", str((mid + pd.Timedelta(1, unit="D")).date()), str(last.date()))]
    cells = lab.score_layer3(P, out, eras, str(last.date()), 0.05 / 8)
    assert set(cells) == {f"{h}:{k}" for h in lab.HORIZONS for k in lab.KINDS}
    c = cells["63:q"]
    assert set(c) >= {"vs_clim", "vs_v1", "vs_v2", "v2_vs_v1", "v1_vs_clim", "ens3_vs_v1", "vs_har", "expert_skill", "coverage80"}
    assert set(c["coverage80"]) == {"ENS1", "V2", "ENS3", "CAL3", "V3"} and set(c["expert_skill"]) == set(lab.MODELS[1:])
    c2 = lab2.score_layer2(P, {k: (v[:, :9] if k in ("FQ", "FP", "LQ", "LB") else v) for k, v in walked[0].items()}, eras, str(last.date()), 0.05 / 8)
    assert c["v2_vs_v1"]["skill"] == pytest.approx(c2["63:q"]["vs_v1"]["skill"], abs=1e-9)  # 2판 성적이 같은 점에서 재현된다


def test_verdict_rules_and_switch_advice():
    def cell(skill, p, eras, evaluable=True):
        d = {"skill": skill, "p": p, "evaluable": evaluable, "grade": "약함", "eras": {k: {"skill": s} for k, s in eras.items()}}
        return {"vs_v1": d, "vs_v2": d, "v2_vs_v1": d, "vs_clim": d, "v1_vs_clim": d}

    good = cell(0.02, 0.001, {"A": 0.01, "B": 0.02, "C": 0.03})
    layers = {"market": {"cells": {"63:q": good, "63:dd15": cell(0.02, 0.001, {"A": 0.01, "B": -0.01, "C": 0.03})}},
              "industry": {"cells": {"63:q": cell(0.02, 0.01, {"A": 0.01}), "63:dd15": cell(0.02, 0.001, {"A": 0.01}, evaluable=False)}},
              "stock": None}
    v = run.verdicts_of(layers)
    assert v["MKT_Q63"]["label"] == "BEATS_V1" and v["MKT_Q63"]["skill_vs_v2"] == 0.02
    assert v["MKT_DD63"]["label"] == "FAIL"                 # 한 시대라도 음수면 탈락
    assert v["IND_Q63"]["label"] == "FAIL"                  # p 가 0.05/8 을 넘으면 탈락
    assert [v[k]["label"] for k in ("IND_DD63", "IND_BEAT63", "STK_Q63", "STK_DD63", "STK_BEAT63")] == ["NOT_EVALUABLE"] * 5
    adv = run.switch_advice(v)
    assert adv["propose_switch"] is False and adv["n_pass"] == 1 and adv["n_judged"] == 3
    three = {k: {"label": "BEATS_V1", "skill": 0.01} for k in "abc"}
    assert run.switch_advice(three | {"d": {"label": "FAIL", "skill": -0.004}})["propose_switch"] is True
    assert run.switch_advice(three | {"d": {"label": "FAIL", "skill": -0.006}})["propose_switch"] is False   # 뚜렷이 나빠진 칸이 있으면 제안하지 않는다
    assert run.switch_advice({"a": {"label": "NOT_EVALUABLE"}})["propose_switch"] is False


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
    assert res["now"] and len(res["now"]["rows"]) == 4 and set(res["switch_advice"]) >= {"propose_switch", "n_pass", "rule"}
    fi = res["data"]["fundamentals"]
    assert 0 < fi["points_known"] < fi["points"] and fi["known_share_by_year"]["2010"] == 0
    es = res["layers"]["stock"]["cells"]["63:beat"]["expert_skill"]
    assert es["FUND"] != es["HAR"]                                                         # 종목 층에서 재무 전문가가 실제로 다른 값을 냈다
    ei = res["layers"]["industry"]["cells"]["63:beat"]["expert_skill"]
    assert ei["FUND"] == pytest.approx(ei["HAR"], abs=1e-9)                                # 업종 층에는 재무가 없다
    rep = (smoke / "REPORT.md").read_text(encoding="utf-8")
    assert "스모크" in rep and "## 판정" in rep and "지금 읽기" in rep and "## 한계" in rep and "재무 자료가 닿은 범위" in rep
    for f in ("results.json", "REPORT.md", "model.json"):
        assert (smoke / f).stat().st_size < 256 * 1024


def test_smoke_model_drives_live_forecast(smoke):
    model = json.loads((smoke / "model.json").read_text(encoding="utf-8"))
    assert model["study"] == STUDY and model["lab_version"] == lab.LAB_VERSION and model["pool"] == list(lab.POOL)
    m, assets = lab1.synthetic_panel(n_assets=3, n_days=900, seed=21)
    libs = {n: lab.library_from_frame3(pd.read_csv(smoke / layer["library"])) for n, layer in model["layers"].items()}
    for name, layer in model["layers"].items():
        lib = libs[name]
        assert list(lib["feats"]) == layer["feats"] and list(lib["hx"]) == layer["hx"] and lib["FR"].shape == (len(lib["X"]), 4)
        st = lab2.latest_state2(assets["A01"], m if name != "market" else None)
        blib = libs["industry"] if layer["borrow_library"] else None
        f = lab.forecast_live3(lib, layer, st, blib)
        six = layer["sixth"]
        for e in ("V3", "CAL3", "ENS3", "V2", "ENS1", "HAR", "ANALOG_H", "TILT_H", six, f"{six}_H", "FUND"):
            assert np.isfinite(f["q"][e]).all() and (np.diff(f["q"][e], axis=-1) >= -1e-12).all(), e
        p = f["p"]["V3"][:, :2]
        assert ((p >= 0) & (p <= 1)).all() and np.allclose(f["weights"].sum(axis=-1), 1.0)
        assert np.isfinite(f["p"]["V3"][:, 2]).all() == (name != "market")
        assert np.allclose(f["q"]["FUND"], f["q"]["HAR"])                                  # 재무 값을 안 주면 FUND = HAR
        assert f["weights"][1, 2, lab.POOL.index("FUND")] <= np.asarray(layer["weights3"])[1, 2, lab.POOL.index("FUND")] + 1e-12   # 같은 값은 한 표
        assert set(layer["cells"]["63:q"]) >= {"grade", "skill", "grade_vs_v1", "grade_vs_v2", "v1_grade", "coverage80"}
    st = lab2.latest_state2(assets["A01"], m)
    st["fx"] = [0.4, 0.2, 0.05, 0.3]
    assert model["layers"]["stock"]["fx_grid"] is None                                     # 스모크는 종목이 20개 미만이라 격자가 없다
    layer = dict(model["layers"]["stock"], fx_grid=[np.linspace(-1, 1, lab2.GRID).tolist()] * 3 + [None])
    f = lab.forecast_live3(libs["stock"], layer, st)
    assert not np.allclose(f["q"]["FUND"], f["q"]["HAR"]) and np.isfinite(f["q"]["V3"]).all()   # 재무 값을 주면 FUND 가 움직인다


def test_ledger_has_hypothesis():
    led = json.loads((ROOT / "research" / "frontier" / "hypotheses.json").read_text(encoding="utf-8"))
    hit = [h for h in led["hypotheses"] if h.get("study_id") == STUDY]
    assert len(hit) == 1 and hit[0]["id"] == "H-032"


def test_fx_grid_needs_twenty_values():
    n = 30
    P = {"date": np.array(["2020-01-01"] * 5 + ["2020-02-01"] * n, dtype="datetime64[D]"), "FXRAW": np.full((n + 5, 4), np.nan)}
    assert lab.fx_grid(P) is None
    P["FXRAW"][5:, 0] = np.arange(n, dtype=float)
    P["FXRAW"][5:15, 1] = 1.0
    g = lab.fx_grid(P)
    assert g[0][0] == 0 and g[0][-1] == n - 1 and len(g[0]) == lab2.GRID and g[1] is None and g[2] is None
    assert lab._to_rank([14.5, 1.0, np.nan, 2.0], g, np.nan)[0, 0] == pytest.approx(0.5) and np.isnan(lab._to_rank([14.5, 1.0, np.nan, 2.0], g, np.nan)[0, 1:]).all()
