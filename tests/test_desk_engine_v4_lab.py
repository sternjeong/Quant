"""desk-engine-lab-v4 — DDLOGIT(HAR 확률 출발 로지스틱), 쌓기(탐욕 선택), walk4(3판 그대로 + 4판), 점수, 실시간 경로."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


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
TAU = np.array(lab.TAUS)
ZQ = np.array([-1.2816, -0.6745, 0.0, 0.6745, 1.2816])                                     # 표준 정규 분위수


@pytest.fixture(scope="module")
def panel():
    """(3판 점 표(앞 1/4 과 자산 하나는 재무가 없음), 시장 3판 점 표(업종 서고를 빌림), 시장 가격, 자산 가격) — 3판 테스트와 같은 구성."""
    m, assets = lab1.synthetic_panel(n_assets=6, n_days=2200, seed=3)
    origins = m.index[252::lab1.STEP]
    ms2 = lab2.market_state2(m)
    f2 = {}
    for k, lp in assets.items():
        f2[k] = lab2.asset_frame2(lp, m)
        f2[k][["mdd", "mvolr", "m21", "m252"]] = ms2
    P2 = lab2.attach(lab1.build_points(f2, origins, with_market=True), f2, True)
    raw = np.random.default_rng(4).normal(size=(len(P2["date"]), len(lab3.FX)))
    raw[P2["date"] < P2["date"][len(P2["date"]) // 4]] = np.nan
    raw[::7, 1] = np.nan
    raw[P2["asset"] == 0] = np.nan
    P3 = lab3.attach3(P2, raw)
    fm = {"MKT": lab2.asset_frame2(m)}
    Pm = lab3.attach3(lab2.attach(lab1.build_points(fm, m.index[252::5], with_market=False), fm, False, borrow=P3))
    return P3, Pm, m, assets


@pytest.fixture(scope="module")
def walked(panel):
    """(3판 walk3, 4판 walk4(3판을 안에서 다시 돌림), 시장 walk4). 한 번만 계산한다."""
    P3, Pm, _, _ = panel
    return lab3.walk3(P3), lab.walk4(P3), lab.walk4(Pm)


def _block(P, back=6):
    a = len(P["date"]) - back
    D = P["date"][a]
    lib = lab3.library3(P, lab2.lib_index(P, a, D), D)
    return lib, (P["X"][a:], P["S"][a:], P["HX"][a:]), a


def _layer(P, out):
    """model.json 층 모양(desk-engine-v3 run.layer_model 과 같은 방식, 4판 열)."""
    r = lambda a: np.round(a, 6).tolist()  # noqa: E731
    return {"feats": list(P["feats"]), "hx": list(P["hx"]), "sixth": P["sixth"], "weights1": r(out["weights1"]), "weights4": r(out["weights4"]),
            "shifts4": r(out["shifts4"]), "blend4": r(out["blend4"]), "cal_active4": [bool(x) for x in out["cal_active4"]],
            "xs_grid": lab2.xs_grid(P)}


def _pin(F, y, w):
    e = y[:, None] - F
    return float(w @ np.maximum(TAU * e, (TAU - 1) * e).mean(axis=-1))


def _brier(p, t, w):
    return float(w @ (p - t) ** 2)


def _on_grid(w):
    """가중이 어떤 m ≤ STACK_PICKS 에 대해 1/m 의 배수인가."""
    return any(np.allclose(w * m, np.round(w * m), atol=1e-9) for m in range(1, lab.STACK_PICKS + 1))


# ---------------------------------------------------------------- 상수
def test_constants():
    assert lab.LAB_VERSION == "desk-engine-lab/v4" and lab.L3 is lab3 and lab.L2 is lab2
    assert lab.POOL4 == ("CLIM", "VOL", "HAR", "ANALOG_H", "TILT_H", "SIXTH_H", "DDLOGIT") and "FUND" not in lab.POOL4
    assert lab.MODELS[:16] == lab3.MODELS and lab.MODELS[16:] == ("DDLOGIT", "STK4", "CAL4", "V4") and lab.M == 20 and lab.M3 == 16
    assert (lab.I_DDL, lab.I_STK4, lab.I_CAL4, lab.I_V4) == (16, 17, 18, 19) and lab.KP4 == 7
    assert [lab.MODELS[i] for i in lab.POOL4_IDX] == list(lab.POOL4) and lab3.I_FUND not in lab.POOL4_IDX
    assert (lab.I_HAR, lab.I_ENS1, lab.I_V3) == (lab3.I_HAR, lab3.I_ENS1, lab3.I_V3) and lab.EVENTS[lab.I_DD - 1] == "dd15"
    assert lab.STACK_PICKS == 10 and lab.DL_CLIP == 1.5 and lab.DL_MIN_EVENTS == 20


# ---------------------------------------------------------------- 1) DDLOGIT
def _dl_data(rng, n, effect=0.0, const_p=False):
    """HAR 확률 pl(로짓 정규), 상태 순위 U[n,3], 사건 y. 진짜 로짓 = 로짓(pl) + effect·(U0 − 0.5)√12."""
    U = rng.random((n, 3))
    g = np.full(n, -1.2) if const_p else rng.normal(-1.3, 0.8, n)
    true = g + effect * (U[:, 0] - 0.5) * math.sqrt(12.0)
    y = (rng.random(n) < 1.0 / (1.0 + np.exp(-true))).astype(float)
    return U, y, 1.0 / (1.0 + np.exp(-g)), 1.0 / (1.0 + np.exp(-true))


def test_dd_logit_needs_events():
    rng = np.random.default_rng(1)
    U, _, p, _ = _dl_data(rng, 400)
    Uq, pq = U[:5], p[:5]
    for n1 in (0, lab.DL_MIN_EVENTS - 1):
        y = np.zeros(400)
        y[:n1] = 1
        assert lab.dd_logit(U, y, p, Uq, pq) is None                                       # 사건이 모자람
        assert lab.dd_logit(U, 1 - y, p, Uq, pq) is None                                   # 비사건이 모자람
    y = np.zeros(400)
    y[:lab.DL_MIN_EVENTS] = 1
    assert lab.dd_logit(U, y, p, Uq, pq) is not None and lab.dd_logit(U, 1 - y, p, Uq, pq) is not None   # 딱 한도면 회귀한다
    y = np.zeros(2 * lab.DL_MIN_EVENTS - 1)
    y[:lab.DL_MIN_EVENTS] = 1
    assert lab.dd_logit(U[:len(y)], y, p[:len(y)], Uq, pq) is None                         # 비사건 19개


def test_dd_logit_stays_near_calibrated_har():
    rng = np.random.default_rng(2)
    U, y, p, _ = _dl_data(rng, 6000)
    Uq, _, pq, _ = _dl_data(rng, 500)
    out = lab.dd_logit(U, y, p, Uq, pq)
    dev = np.log(out / (1 - out)) - lab._logit(pq)
    assert np.abs(dev).max() < 0.35 and np.abs(out - pq).mean() < 0.02                     # 잘 맞는 HAR 은 거의 그대로


def test_dd_logit_learns_state_effect_and_beats_har_out_of_sample():
    rng = np.random.default_rng(3)
    U, y, p, _ = _dl_data(rng, 6000, effect=0.8)
    Uf, yf, pf, truef = _dl_data(rng, 6000, effect=0.8)
    out = lab.dd_logit(U, y, p, Uf, pf)
    w = np.full(len(yf), 1.0 / len(yf))
    assert _brier(out, yf, w) < _brier(pf, yf, w) - 1e-3                                   # 새 자료에서 브라이어가 낮다
    assert np.abs(out - truef).mean() < np.abs(pf - truef).mean() * 0.5
    Uq = np.full((3, 3), 0.5)
    Uq[0, 0], Uq[1, 0] = 0.95, 0.05
    pq = np.full(3, 0.2)
    o = lab.dd_logit(U, y, p, Uq, pq)
    assert o[0] > o[2] + 0.1 and o[1] < o[2] - 0.05 and abs(o[2] - 0.2) < 0.03              # 상태가 높으면 위, 낮으면 아래, 가운데는 그대로
    Uc, yc, pc, _ = _dl_data(rng, 3000, effect=0.8, const_p=True)                          # HAR 확률이 모두 같아도(표준편차 0) 돈다
    oc = lab.dd_logit(Uc, yc, pc, Uq, np.full(3, pc[0]))
    assert oc is not None and np.isfinite(oc).all() and oc[0] > oc[2] > oc[1]


def test_dd_logit_clip_range_and_determinism():
    rng = np.random.default_rng(4)
    U, y, p, _ = _dl_data(rng, 4000, effect=4.0)                                            # 아주 센 상태 효과 → 한도에 걸린다
    Uq = rng.random((400, 3))
    pq = np.concatenate([rng.random(396), [0.0, 1.0, 1e-7, 1 - 1e-7]])                     # 끝값은 DL_EPS 로 잘라 로짓을 잡는다
    out = lab.dd_logit(U, y, p, Uq, pq)
    assert out.shape == (400,) and np.isfinite(out).all() and ((out > 0) & (out < 1)).all()
    dev = np.log(out / (1 - out)) - lab._logit(pq)
    assert np.abs(dev).max() <= lab.DL_CLIP + 1e-9 and np.abs(dev).max() > lab.DL_CLIP - 1e-6   # 한도 안, 그리고 실제로 걸림
    assert np.array_equal(out, lab.dd_logit(U, y, p, Uq, pq))                              # 결정적
    assert np.array_equal(out[:7], lab.dd_logit(U, y, p, Uq[:7], pq[:7]))                  # 질의마다 따로(묶음과 무관)


def test_ddlogit_block_on_library(panel, monkeypatch):
    P3, _, _, _ = panel
    lib, (X, S, HX), a = _block(P3)
    dd = lab.ddlogit_block(lib, X, S, HX)
    assert dd.shape == (len(X), lab.H)
    fin = np.isfinite(dd)
    assert fin.any() and (np.isnan(dd) | fin).all() and ((dd[fin] >= 0) & (dd[fin] <= 1)).all()
    assert (fin.all(axis=0) | ~fin.any(axis=0)).all()                                      # 기간 단위로 회귀하거나 못 하거나
    small = {k: v[:lab1.MIN_LIB - 1] for k, v in lib.items()}
    assert np.isnan(lab.ddlogit_block(small, X, S, HX)).all()                              # 서고가 작으면 모두 NaN
    assert lab.ddlogit_block(lib, X[:0], S[:0], HX[:0]).shape == (0, lab.H)
    # 출발점 pq 는 3판 HAR 의 낙폭 확률이다
    real, calls = lab.dd_logit, []

    def spy(Ul, yl, pl, Uq, pq):
        calls.append((yl, pl, pq))
        return real(Ul, yl, pl, Uq, pq)

    monkeypatch.setattr(lab, "dd_logit", spy)
    dd2 = lab.ddlogit_block(lib, X, S, HX)
    assert np.array_equal(dd, dd2, equal_nan=True)
    FQ, FP, _, _ = lab3.forecast_block3(lib, X, S, HX, P3["XR"][a:], P3["FR"][a:], "XRANK")
    his = [hi for hi in range(lab.H) if int((np.isfinite(lib["RET"][:, hi]) & np.isfinite(lib["MN"][:, hi])).sum()) >= lab1.MIN_LIB]
    assert len(calls) == len(his)
    for (yl, pl, pq), hi in zip(calls, his):
        assert np.allclose(pq, FP[:, lab.I_HAR, hi, 1])
        assert ((pl >= 0) & (pl <= 1)).all() and set(np.unique(yl)) <= {0.0, 1.0}
        if np.isfinite(dd[:, hi]).all():
            assert not np.allclose(dd[:, hi], pq)                                          # 회귀가 되면 HAR 과 다르다


# ---------------------------------------------------------------- 2) 쌓기
def test_stack_quantile_single_best_and_opposite_biases():
    rng = np.random.default_rng(5)
    n = 3000
    y = rng.normal(size=n)
    w = np.full(n, 1.0 / n)
    good = np.tile(ZQ, (n, 1))
    F = np.stack([good + 3.0, good, good - 2.5], axis=1)
    assert lab.stack_quantile(F, y, w) == pytest.approx([0, 1, 0])                         # 섞어도 나아지지 않으면 하나에 전부
    F2 = np.stack([good - 1.0, good + 1.0], axis=1)
    w2 = lab.stack_quantile(F2, y, w)
    assert w2 == pytest.approx([0.5, 0.5])                                                 # 반대 치우침은 섞는다
    mix = np.einsum("nkt,k->nt", F2, w2)
    assert _pin(mix, y, w) <= min(_pin(F2[:, j], y, w) for j in range(2))
    Fi = np.stack([good + 2.0, good, good, good], axis=1)
    assert lab.stack_quantile(Fi, y, w) == pytest.approx([0, 1, 0, 0])                     # 같은 전문가끼리는 앞 번호가 다 가진다
    half = np.arange(n) < n // 2                                                           # 가중이 결과를 정한다
    yb = np.where(half, y + 2.0, y - 2.0)
    Fb = np.stack([good + 2.0, good - 2.0], axis=1)
    wa = np.where(half, 0.9, 0.1)
    assert lab.stack_quantile(Fb, yb, wa / wa.sum())[0] >= 0.8 and lab.stack_quantile(Fb, yb, (1 - wa) / (1 - wa).sum())[1] >= 0.8


def test_stack_quantile_first_pick_is_best_single(monkeypatch):
    rng = np.random.default_rng(6)
    F = np.sort(rng.normal(size=(500, 5, 5)), axis=-1)
    y = rng.normal(size=500)
    w = rng.random(500)
    w /= w.sum()
    best = int(np.argmin([_pin(F[:, j], y, w) for j in range(5)]))
    monkeypatch.setattr(lab, "STACK_PICKS", 1)
    assert lab.stack_quantile(F, y, w) == pytest.approx(np.eye(5)[best])


@pytest.mark.parametrize("seed", range(6))
def test_stack_quantile_properties(seed):
    rng = np.random.default_rng(100 + seed)
    n, k = 400, 1 + seed % 6 + 1
    y = rng.standard_t(4, n) * 0.1
    F = np.sort(rng.normal(0, 0.1, (n, k, 5)) + rng.normal(0, 0.05, (1, k, 1)) + ZQ * rng.uniform(0.03, 0.2, (1, k, 1)), axis=-1)
    w = rng.random(n)
    w /= w.sum()
    wt = lab.stack_quantile(F, y, w)
    assert wt.shape == (k,) and wt.sum() == pytest.approx(1.0) and (wt >= 0).all() and _on_grid(wt)
    assert _pin(np.einsum("nkt,k->nt", F, wt), y, w) <= min(_pin(F[:, j], y, w) for j in range(k)) + 1e-12   # 섞은 것 ≤ 가장 나은 한 명(표본 안)
    # 손으로 짠 같은 탐욕 절차와 같다
    S, counts, best, bc = np.zeros((n, 5)), np.zeros(k), np.inf, None
    for m in range(lab.STACK_PICKS):
        losses = [_pin((S + F[:, j]) / (m + 1), y, w) for j in range(k)]
        j = int(np.argmin(losses))
        counts[j] += 1
        S = S + F[:, j]
        if losses[j] < best:
            best, bc = losses[j], counts.copy()
    assert wt == pytest.approx(bc / bc.sum())


def _brute_event(Pm, t, w):
    """한 점씩 손실을 직접 계산하는 같은 탐욕 쌓기."""
    n, k = Pm.shape
    S, counts, best, bc = np.zeros(n), np.zeros(k), np.inf, None
    for m in range(lab.STACK_PICKS):
        losses = [_brier((S + Pm[:, j]) / (m + 1), t, w) for j in range(k)]
        j = int(np.argmin(losses))
        counts[j] += 1
        S = S + Pm[:, j]
        if losses[j] < best:
            best, bc = losses[j], counts.copy()
    return bc / bc.sum()


@pytest.mark.parametrize("seed", range(8))
def test_stack_event_matches_brute_force(seed):
    rng = np.random.default_rng(200 + seed)
    n, k = 300, 2 + seed % 6
    truth = rng.uniform(0.05, 0.6, n)
    t = (rng.random(n) < truth).astype(float)
    Pm = np.clip(truth[:, None] + rng.normal(0, rng.uniform(0.02, 0.3, k), (n, k)) + rng.normal(0, 0.1, k), 0, 1)
    w = rng.random(n)
    w /= w.sum()
    wt = lab.stack_event(Pm, t, w)
    assert wt == pytest.approx(_brute_event(Pm, t, w), abs=1e-12)
    assert wt.sum() == pytest.approx(1.0) and _on_grid(wt)
    assert _brier(Pm @ wt, t, w) <= min(_brier(Pm[:, j], t, w) for j in range(k)) + 1e-12


def test_stack_event_simple_cases(monkeypatch):
    rng = np.random.default_rng(7)
    n = 4000
    pt = rng.uniform(0.1, 0.5, n)
    t = (rng.random(n) < pt).astype(float)
    w = np.full(n, 1.0 / n)
    Pm = np.stack([np.clip(pt + 0.3, 0, 1), pt, np.full(n, 0.9)], axis=1)
    assert lab.stack_event(Pm, t, w) == pytest.approx([0, 1, 0])
    Po = np.stack([np.clip(pt - 0.1, 0, 1), np.clip(pt + 0.1, 0, 1)], axis=1)
    wo = lab.stack_event(Po, t, w)
    assert wo == pytest.approx([0.5, 0.5]) and _brier(Po @ wo, t, w) < min(_brier(Po[:, j], t, w) for j in range(2))
    assert lab.stack_event(np.stack([Pm[:, 0], pt, pt], axis=1), t, w) == pytest.approx([0, 1, 0])   # 같은 전문가는 앞 번호
    monkeypatch.setattr(lab, "STACK_PICKS", 1)
    assert lab.stack_event(Pm, t, w) == pytest.approx([0, 1, 0])


def test_date_weights_and_history():
    block = np.array([0, 0, 0, 1, 2, 2, 3])
    ok = np.array([True, True, False, True, False, False, True])
    w, nd = lab.date_weights(ok, block)
    assert nd == 3 and w == pytest.approx([1 / 6, 1 / 6, 0, 1 / 3, 0, 0, 1 / 3]) and w.sum() == pytest.approx(1.0)
    w0, nd0 = lab.date_weights(np.zeros(7, bool), block)
    assert nd0 == 0 and not w0.any()
    we, nde = lab.date_weights(np.zeros(0, bool), np.zeros(0, np.int64))
    assert nde == 0 and len(we) == 0
    h = lab.History()
    h.add(1, np.array([4, 5, 6]))
    h.add(1, np.zeros(0, np.int64))                                                        # 빈 묶음은 세지 않는다
    h.add(1, np.array([9]))
    assert h.idx[1].tolist() == [4, 5, 6, 9] and h.block[1].tolist() == [0, 0, 0, 1] and h.nb == [0, 2, 0, 0] and h.version == [0, 2, 0, 0]
    assert len(h.idx[0]) == 0


def _fake(rng, n_dates, per=25):
    n = n_dates * per
    FQ = np.full((n, lab.M, lab.H, 5), np.nan)
    FQ[:, lab.POOL4_IDX] = np.sort(rng.normal(0, 0.1, (n, 7, lab.H, 5)) + ZQ * 0.1, axis=-1)
    FQ[:, [lab.I_STK4, lab.I_CAL4]] = np.sort(rng.normal(0, 0.1, (n, 2, lab.H, 5)) + ZQ * 0.1, axis=-1)
    FP = np.full((n, lab.M, lab.H, 3), np.nan)
    FP[:, lab.POOL4_IDX] = rng.random((n, 7, lab.H, 3))
    y = rng.normal(0, 0.1, (n, lab.H))
    truth = (rng.random((n, lab.H, 3)) < 0.4).astype(float)
    truth[:, :, 2] = np.nan                                                                # beat 정답이 없음
    FQ[3, lab.POOL4_IDX[2], 1] = np.nan                                                    # 쓸 수 없는 점
    y[5, 1] = np.nan
    return FQ, FP, y, truth, per


@pytest.mark.parametrize("n_dates", [lab2.MIN_DATES - 1, lab2.MIN_DATES + 3])
def test_stack_weights_h_and_blend(n_dates):
    rng = np.random.default_rng(8)
    FQ, FP, y, truth, per = _fake(rng, n_dates)
    hist = lab.History()
    for d in range(n_dates):
        hist.add(1, np.arange(d * per, (d + 1) * per))
    Wt = lab.stack_weights_h(FQ, FP, y, truth, hist, 1, lab.POOL4_IDX)
    Bt = lab.blend_weights_h(FQ, y, hist, 1)
    assert Wt.shape == (4, 7) and np.allclose(Wt.sum(axis=1), 1.0) and Bt.sum() == pytest.approx(1.0)
    assert np.allclose(Wt[3], 1 / 7)                                                       # 정답 없는 사건은 같은 가중
    assert np.allclose(lab.stack_weights_h(FQ, FP, y, truth, hist, 0, lab.POOL4_IDX), 1 / 7)   # 실현 기록이 없는 기간
    assert np.allclose(lab.blend_weights_h(FQ, y, hist, 0), 0.5)
    if n_dates < lab2.MIN_DATES:
        assert np.allclose(Wt, 1 / 7) and np.allclose(Bt, 0.5)                             # 기준일이 모자라면 같은 가중
        return
    idx, block = hist.idx[1], hist.block[1]
    F = FQ[idx][:, lab.POOL4_IDX, 1]
    w, nd = lab.date_weights(np.isfinite(F).all(axis=(1, 2)) & np.isfinite(y[idx, 1]), block)
    assert nd == n_dates and w[3] == 0 and w[5] == 0
    assert Wt[0] == pytest.approx(lab.stack_quantile(F[w > 0], y[idx, 1][w > 0], w[w > 0]))
    for e in range(2):
        we, _ = lab.date_weights(np.ones(len(idx), bool), block)
        assert Wt[1 + e] == pytest.approx(lab.stack_event(FP[idx][:, lab.POOL4_IDX, 1, e], truth[idx, 1, e], we))
    Fb = FQ[idx][:, [lab.I_STK4, lab.I_CAL4], 1]
    wb, _ = lab.date_weights(np.isfinite(Fb).all(axis=(1, 2)) & np.isfinite(y[idx, 1]), block)
    assert Bt == pytest.approx(lab.stack_quantile(Fb[wb > 0], y[idx, 1][wb > 0], wb[wb > 0]))


def test_assemble4_blend_and_inactive():
    rng = np.random.default_rng(9)
    FQp = np.sort(rng.normal(size=(5, 7, 4, 5)), axis=-1)
    FPp = rng.random((5, 7, 4, 3))
    S = rng.uniform(0.05, 0.2, (5, 4))
    W = rng.random((4, 4, 7))
    W /= W.sum(axis=-1, keepdims=True)
    sh = np.tile(np.array([-0.5, -0.2, 0.0, 0.2, 0.5]), (4, 1))
    blend = np.tile(np.array([0.3, 0.7]), (4, 1))
    act = np.array([True, False, True, False])
    q, p, qc, qv = lab.assemble4(FQp, FPp, S, W, sh, blend, act)
    q0, p0 = lab1.combine(FQp, FPp, W)
    assert np.allclose(q, q0) and np.allclose(p, p0) and ((p >= 0) & (p <= 1)).all()
    assert np.array_equal(qc[:, ~act], q[:, ~act]) and np.array_equal(qv[:, ~act], q[:, ~act])   # 보정 전: CAL4 = V4 = STK4
    assert np.allclose(qc[:, act], np.sort(q[:, act] + S[:, act, None] * sh[act][None], axis=-1))
    assert np.allclose(qv[:, act], 0.3 * q[:, act] + 0.7 * qc[:, act])
    for a in (q, qc, qv):
        assert (np.diff(a, axis=-1) >= -1e-12).all()
    _, _, _, qv1 = lab.assemble4(FQp, FPp, S, W, sh, np.tile([1.0, 0.0], (4, 1)), act)
    assert np.allclose(qv1, q)                                                             # 섞기 가중이 STK4 에 전부면 V4 = STK4


# ---------------------------------------------------------------- 3) 걸어 나가기
def test_walk4_keeps_v3_and_adds_v4(panel, walked):
    P3, _, _, _ = panel
    o3, o4, _ = walked
    n = len(P3["date"])
    assert o4["FQ"].shape == (n, 20, 4, 5) and o4["FP"].shape == (n, 20, 4, 3) and o4["LQ"].shape == (n, 20, 4) and o4["LB"].shape == (n, 20, 4, 3)
    for k in ("FQ", "FP", "LQ", "LB"):
        assert np.array_equal(o4[k][:, :16], o3[k], equal_nan=True), k                     # 앞 16개는 3판 그대로
    for k in ("weights1", "weights3", "shifts3", "blend", "cal_active", "weights2", "shifts2"):
        assert np.array_equal(o4[k], o3[k]), k
    assert np.array_equal(o4["S3"], o3["S3"], equal_nan=True)
    # DDLOGIT: 분위수·오를·이길 확률은 HAR, 낙폭 확률만 다르다
    assert np.array_equal(o4["FQ"][:, lab.I_DDL], o4["FQ"][:, lab.I_HAR], equal_nan=True)
    assert np.array_equal(o4["FP"][:, lab.I_DDL, :, [0, 2]], o4["FP"][:, lab.I_HAR, :, [0, 2]], equal_nan=True)
    d, h = o4["FP"][:, lab.I_DDL, :, 1], o4["FP"][:, lab.I_HAR, :, 1]
    assert np.array_equal(np.isfinite(d), np.isfinite(h)) and ((d[np.isfinite(d)] >= 0) & (d[np.isfinite(d)] <= 1)).all()
    assert (np.abs(d - h) > 1e-4).sum() > 100
    dev = lab._logit(d.astype(float)) - lab._logit(h.astype(float))
    assert np.nanmax(np.abs(dev)) <= lab.DL_CLIP + 1e-4                                    # float32 저장 여유
    # STK4·CAL4·V4
    stk, cal, v4, ens1 = (o4["FQ"][:, e] for e in (lab.I_STK4, lab.I_CAL4, lab.I_V4, lab.I_ENS1))
    pool_ok = np.isfinite(o4["FQ"][:, lab.POOL4_IDX]).all(axis=1)
    assert np.array_equal(np.isfinite(stk), pool_ok) and np.array_equal(np.isfinite(v4), np.isfinite(stk))
    assert np.array_equal(np.isfinite(v4), np.isfinite(ens1))                              # 이 자료에서는 ENS1 이 있는 곳에 V4 도 있다
    assert np.isfinite(v4[:, 0, 2]).sum() > 100
    pmin, pmax = o4["FQ"][:, lab.POOL4_IDX].min(axis=1), o4["FQ"][:, lab.POOL4_IDX].max(axis=1)
    f = np.isfinite(stk)
    assert ((stk[f] >= pmin[f] - 1e-6) & (stk[f] <= pmax[f] + 1e-6)).all()                 # 쌓기는 볼록 결합
    for a in (stk, cal, v4):
        ff = np.isfinite(a).all(axis=-1)
        assert (np.diff(a[ff], axis=-1) >= -1e-6).all()
    for e in (lab.I_CAL4, lab.I_V4):
        assert np.array_equal(o4["FP"][:, e], o4["FP"][:, lab.I_STK4], equal_nan=True)     # 확률은 보정하지 않는다
    ca = o4["CA4"]
    assert ca.any() and (~ca[:, 0] & f[:, 0, 0]).any()
    off = ~ca[:, :, None] & np.ones((1, 1, 5), bool)
    assert np.array_equal(v4[off], stk[off], equal_nan=True) and np.array_equal(cal[off], stk[off], equal_nan=True)
    on = ca[:, :, None] & np.isfinite(stk)
    lo, hi = np.minimum(stk, cal) - 1e-6, np.maximum(stk, cal) + 1e-6
    assert ((v4[on] >= lo[on]) & (v4[on] <= hi[on])).all() and not np.allclose(cal[on], stk[on])   # V4 는 보정 전·후 사이
    # 손실은 저장된 예측으로 다시 계산된다
    y = P3["RET"]
    truth = lab1.event_truth(P3["RET"], P3["MN"], P3["EX"])
    for e in range(16, 20):
        assert np.allclose(o4["LQ"][:, e], lab1.pinball(y, o4["FQ"][:, e].astype(float)), equal_nan=True)
        assert np.allclose(o4["LB"][:, e], (o4["FP"][:, e].astype(float) - truth) ** 2, equal_nan=True)


def test_walk4_outputs(walked):
    _, o4, _ = walked
    assert o4["weights4"].shape == (4, 4, 7) and np.allclose(o4["weights4"].sum(axis=-1), 1.0) and (o4["weights4"] >= 0).all()
    assert all(_on_grid(w) for w in o4["weights4"].reshape(-1, 7))
    assert not np.allclose(o4["weights4"], 1 / 7)                                          # 실제로 쌓았다
    assert o4["shifts4"].shape == (4, 5) and o4["blend4"].shape == (4, 2) and np.allclose(o4["blend4"].sum(axis=-1), 1.0)
    assert o4["cal_active4"].dtype == bool and o4["cal_active4"].shape == (4,) and o4["cal_active4"][0]
    assert (o4["CA4"][-1] <= o4["cal_active4"]).all() and (o4["CA4"][:-1] <= o4["CA4"][1:]).all()   # 보정은 한번 켜지면 꺼지지 않는다
    assert not o4["shifts4"][~o4["cal_active4"]].any() and o4["shifts4"][o4["cal_active4"]].any()
    rd, bd = o4["realized_dates"], o4["blend_dates"]
    assert rd.shape == (4,) and (rd > lab2.MIN_DATES).all() and (bd <= rd).all() and bd[0] > 0
    assert (rd[:-1] >= rd[1:]).all()                                                       # 긴 기간일수록 실현된 기준일이 적다
    assert np.allclose(o4["blend4"][bd < lab2.MIN_DATES], 0.5)


def test_walk4_out3_shortcut_is_identical(panel, walked):
    P3, _, _, _ = panel
    o3, o4, _ = walked
    o4b = lab.walk4(P3, out3=o3)
    for k in ("FQ", "FP", "LQ", "LB", "CA4"):
        assert np.array_equal(o4b[k], o4[k], equal_nan=True), k
    assert np.array_equal(o4b["weights4"], o4["weights4"]) and np.array_equal(o4b["blend4"], o4["blend4"])


def test_walk4_uses_no_future(panel, walked):
    P, _, _, _ = panel
    out = walked[1]
    cut = int(len(P["date"]) * 0.8)
    D = P["date"][cut]
    Pf = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in P.items()}
    for hi in range(4):
        late = ~(P["END"][:, hi] <= D)
        for key in ("RET", "MN", "EX", "RV"):
            Pf[key][late, hi] = Pf[key][late, hi] * 3 + 0.2
    Pf["FR"][P["date"] > D] = 0.9
    out2 = lab.walk4(Pf)
    early = P["date"] <= D
    for e in range(16, 20):
        assert np.array_equal(out["FQ"][early, e], out2["FQ"][early, e], equal_nan=True), lab.MODELS[e]
        assert np.array_equal(out["FP"][early, e], out2["FP"][early, e], equal_nan=True), lab.MODELS[e]
    assert np.array_equal(out["FQ"][early], out2["FQ"][early], equal_nan=True) and np.array_equal(out["CA4"][early], out2["CA4"][early])
    for e in (lab.I_STK4, lab.I_V4):
        assert not np.array_equal(out["FQ"][~early, e], out2["FQ"][~early, e], equal_nan=True)
    assert not np.array_equal(out["FP"][~early, lab.I_DDL, :, 1], out2["FP"][~early, lab.I_DDL, :, 1], equal_nan=True)


def test_market_walk4(panel, walked):
    _, Pm, _, _ = panel
    om = walked[2]
    assert np.isnan(om["FP"][:, :, :, 2]).all()                                            # 시장 층에는 이길 사건이 없다
    assert np.allclose(om["weights4"][:, 3], 1 / 7)                                        # 그 칸은 같은 가중
    done = np.isfinite(om["FQ"][:, lab.I_V4, 1, 2])
    assert done.sum() > 30 and np.isfinite(om["FP"][done, lab.I_V4, 1, :2]).all()
    assert np.allclose(om["weights4"].sum(axis=-1), 1.0) and om["FQ"].shape[1] == 20


# ---------------------------------------------------------------- 4) 점수
def _eras(P):
    first, last = pd.Timestamp(P["date"][0]), pd.Timestamp(P["date"][-1])
    mid = first + (last - first) / 2
    return [("E1", str(first.date()), str(mid.date())), ("E2", str((mid + pd.Timedelta(1, unit="D")).date()), str(last.date()))], str(last.date())


def test_score_layer4(panel, walked):
    P, Pm, _, _ = panel
    o3, o4, om = walked
    eras, end = _eras(P)
    cells = lab.score_layer4(P, o4, eras, end, 0.05 / 8)
    assert set(cells) == {f"{h}:{k}" for h in lab.HORIZONS for k in lab.KINDS}
    c = cells["63:q"]
    assert set(c) >= {"vs_clim", "vs_v1", "vs_v3", "v3_vs_v1", "v1_vs_clim", "stk4_vs_v1", "vs_har", "ddl_vs_har", "expert_skill", "coverage80"}
    assert set(c["coverage80"]) == {"ENS1", "V3", "STK4", "CAL4", "V4"} and set(c["expert_skill"]) == set(lab.MODELS[1:])
    assert {"V4", "DDLOGIT", "STK4"} <= set(c["expert_skill"]) and all(0 <= v <= 1 for v in c["coverage80"].values())
    for kind in ("q", "up", "beat"):
        assert cells[f"63:{kind}"]["ddl_vs_har"]["skill"] == pytest.approx(0.0, abs=1e-12)  # DDLOGIT 은 낙폭 확률만 다르다
    assert "coverage80" not in cells["63:dd15"]
    assert any(abs(cells[f"{h}:dd15"]["ddl_vs_har"]["skill"] or 0) > 1e-6 for h in lab.HORIZONS)
    c3 = lab3.score_layer3(P, o3, eras, end, 0.05 / 8)
    assert c["v3_vs_v1"]["skill"] == pytest.approx(c3["63:q"]["vs_v1"]["skill"], abs=1e-9)   # 3판 성적이 같은 점에서 재현된다
    assert c["v3_vs_v1"]["n_points"] == c3["63:q"]["vs_v1"]["n_points"]
    eras_m, end_m = _eras(Pm)
    cm = lab.score_layer4(Pm, om, eras_m, end_m, 0.05 / 8)
    assert not any(k.endswith(":beat") for k in cm) and "63:q" in cm                       # 시장 층은 이길 칸이 없다


# ---------------------------------------------------------------- 5) 저장·실시간
def test_library_frame_roundtrip(panel):
    P3, _, _, _ = panel
    df = lab.export_library4(P3)
    assert not any(c.startswith("fr_") for c in df.columns) and df.equals(lab2.export_library2(P3))
    lib = lab.library_from_frame4(df)
    lib3 = lab.library_from_frame4(lab3.export_library3(P3))                               # 3판 서고(재무 열 있음)도 읽는다
    for L in (lib, lib3):
        assert list(L["feats"]) == list(P3["feats"]) and list(L["hx"]) == list(P3["hx"])
        assert L["FR"].shape == (len(L["X"]), len(lab3.FX)) and np.isnan(L["FR"]).all()
    assert np.array_equal(lib["X"], lib3["X"]) and np.array_equal(lib["RET"], lib3["RET"], equal_nan=True)


def test_forecast_live4_from_exported_library(panel, walked):
    P3, Pm, m, assets = panel
    _, o4, om = walked
    libs = {"stock": lab.library_from_frame4(lab.export_library4(P3)), "market": lab.library_from_frame4(lab.export_library4(Pm))}
    for name, P, out in (("stock", P3, o4), ("market", Pm, om)):
        layer = _layer(P, out)
        st = lab2.latest_state2(assets["A01"], m if name == "stock" else None)
        assert "fx" not in st                                                              # 재무 자료 없이 예측한다
        blib = libs["stock"] if name == "market" else None
        f = lab.forecast_live4(libs[name], layer, st, blib)
        six = layer["sixth"]
        for e in ("V4", "STK4", "CAL4", "ENS1", "DDLOGIT", "HAR", "CLIM", "VOL", "ANALOG_H", "TILT_H", six, f"{six}_H", "FUND"):
            assert e in f["q"] and e in f["p"], e
            assert f["q"][e].shape == (4, 5) and np.isfinite(f["q"][e]).all() and (np.diff(f["q"][e], axis=-1) >= -1e-12).all(), e
        for e in ("V4", "STK4", "CAL4", "ENS1", "DDLOGIT"):
            p = f["p"][e][:, :2]
            assert np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all(), e
            assert np.isfinite(f["p"][e][:, 2]).all() == (name == "stock"), e
        assert np.array_equal(f["q"]["DDLOGIT"], f["q"]["HAR"]) and np.array_equal(f["p"]["DDLOGIT"][:, [0, 2]], f["p"]["HAR"][:, [0, 2]], equal_nan=True)
        assert np.array_equal(f["p"]["V4"], f["p"]["STK4"], equal_nan=True) and np.array_equal(f["p"]["CAL4"], f["p"]["STK4"], equal_nan=True)
        assert np.allclose(f["weights"], layer["weights4"]) and len(f["n"]) == 4
        ca = np.asarray(layer["cal_active4"])
        assert np.array_equal(f["q"]["V4"][~ca], f["q"]["STK4"][~ca])
        f2 = lab.forecast_live4(libs[name], layer, dict(st, fx=[0.4, 0.2, 0.05, 0.3]), blib)   # 재무 값을 줘도 무시한다
        for e in ("V4", "STK4", "DDLOGIT"):
            assert np.array_equal(f["q"][e], f2["q"][e]) and np.array_equal(f["p"][e], f2["p"][e], equal_nan=True)


def test_forecast_live4_matches_walk_at_last_origin(panel, walked):
    """마지막 기준일의 한 점을 같은 서고·같은 상태로 넣으면 전문가·DDLOGIT 은 걸어 나가기 값과 같고, STK4·CAL4·V4 는 assemble4(최종 가중) 그대로다."""
    P, _, _, _ = panel
    _, o4, _ = walked
    D = P["date"][-1]
    a = int(np.searchsorted(P["date"], D, side="left"))
    lib = lab3.library3(P, lab2.lib_index(P, a, D), D)
    r = a + 1
    xs, xr = P["XRAW"][r], P["XR"][r]
    assert np.isfinite(xs).all()
    grid = [np.linspace(v - u, v + 1 - u, lab2.GRID).tolist() for v, u in zip(xs, xr)]     # 상태 값을 그 점의 순위로 바꾸는 격자
    layer = dict(_layer(P, o4), xs_grid=grid)
    st = {"x": P["X"][r], "s": P["S"][r], "hx": P["HX"][r], "xs": xs.tolist()}
    f = lab.forecast_live4(lib, layer, st)
    names = list(lab3.EXPERTS3[:5]) + ["XRANK", "ANALOG_H", "TILT_H", "XRANK_H"]
    for i, e in enumerate(names):
        assert np.allclose(f["q"][e], o4["FQ"][r, i], rtol=1e-5, atol=1e-7), e
        assert np.allclose(f["p"][e], o4["FP"][r, i], rtol=1e-5, atol=1e-7, equal_nan=True), e
    assert np.allclose(f["p"]["DDLOGIT"], o4["FP"][r, lab.I_DDL], rtol=1e-5, atol=1e-7)  # 같은 서고면 같은 회귀
    w = lambda k: np.asarray(layer[k], float)  # noqa: E731
    q1, _ = lab1.combine(o4["FQ"][r:r + 1, :lab3.K1].astype(float), o4["FP"][r:r + 1, :lab3.K1].astype(float), w("weights1"))
    assert np.allclose(f["q"]["ENS1"], q1[0], rtol=1e-5, atol=1e-6)
    q, p, qc, qv = lab.assemble4(o4["FQ"][r:r + 1, lab.POOL4_IDX].astype(float), o4["FP"][r:r + 1, lab.POOL4_IDX].astype(float),
                                 o4["S3"][r:r + 1], w("weights4"), w("shifts4"), w("blend4"), np.asarray(layer["cal_active4"], bool))
    for k, v in (("STK4", q), ("CAL4", qc), ("V4", qv)):
        assert np.allclose(f["q"][k], v[0], rtol=1e-5, atol=1e-6), k
    assert np.allclose(f["p"]["STK4"], p[0], rtol=1e-5, atol=1e-6, equal_nan=True)
