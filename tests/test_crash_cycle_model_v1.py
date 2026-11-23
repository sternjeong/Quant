"""crash-cycle-model-v1 — 순수 함수(손 계산), 사건 정의·병합·중도절단, 미래 정보 차단, 판정 규칙, 스모크 전 경로."""

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
spec = importlib.util.spec_from_file_location("crash_cycle_model_v1", ROOT / "research" / "jobs" / "crash-cycle-model-v1" / "run.py")
cc = importlib.util.module_from_spec(spec)
sys.modules["crash_cycle_model_v1"] = cc
spec.loader.exec_module(cc)


# ---------------------------------------------------------------- 순수 함수
def test_wquantile_equal_weights_hazen():
    y, w = [1, 2, 3, 4], [1, 1, 1, 1]
    assert cc.wquantile(y, w, 0.5) == pytest.approx(2.5)
    assert cc.wquantile(y, w, 0.25) == pytest.approx(1.5)
    assert cc.wquantile(y, w, 0.05) == pytest.approx(1.0)
    assert cc.wquantile(y, w, 0.95) == pytest.approx(4.0)


def test_wquantile_unequal():
    assert cc.wquantile([0, 10], [3, 1], 0.5) == pytest.approx(2.5)          # c = [0.375, 0.875]
    assert cc.wquantile([0, 10, 99], [3, 1, 0], 0.5) == pytest.approx(2.5)   # 가중치 0 인 점은 무시


def test_pinball():
    assert cc.pinball(1, 0, 0.9) == pytest.approx(0.9)
    assert cc.pinball(0, 1, 0.9) == pytest.approx(0.1)
    assert cc.pinball(2, 0, 0.5) == pytest.approx(1.0)


def test_km_hand_case():
    tau, S = cc.wkm([2, 3, 3, 5, 8], [1, 1, 0, 1, 0])
    for h, v in ((1, 1.0), (2, 0.8), (4, 0.6), (5, 0.3), (10, 0.3)):
        assert cc.surv_at(tau, S, h) == pytest.approx(v)


def test_beran_weighted():
    tau, S = cc.wkm([1, 2], [1, 1], [1, 3])
    assert cc.surv_at(tau, S, 1) == pytest.approx(0.75)
    assert cc.surv_at(tau, S, 2) == pytest.approx(0.0)
    t, e = [2, 3, 3, 5, 8], [1, 1, 0, 1, 0]
    tk, sk = cc.wkm(t, e)
    tc, sc = cc.wkm(t, e, [2.7] * 5)
    assert np.allclose(tk, tc) and np.allclose(sk, sc)


def test_brier():
    F = {252: 0.2, 504: 0.6, 756: 0.9, 1260: 1.0}
    assert cc.brier(300, F) == pytest.approx(np.mean([0.04, 0.16, 0.01, 0.0]))
    assert cc.brier(300, F) == pytest.approx(0.0525)


def test_kernel_weights_rules():
    assert cc.kernel_weights([1, 2, 3, 4, 5], 3) is None                     # 학습 5개
    assert cc.kernel_weights([2.0] * 8, 2.0) is None                          # σ = 0
    assert cc.kernel_weights(list(range(8)), float("nan")) is None            # x_new NaN
    w = cc.kernel_weights([0, 1, 2, 3, 4, 5, 6, 7], 3)
    assert w[3] == pytest.approx(1.0)                                         # 같은 값 = 1
    assert w[3] > w[4] > w[5] > w[6] > w[7] and w[3] > w[2] > w[1] > w[0]     # 멀수록 감소
    w2 = cc.kernel_weights([0, 1, 2, 3, 4, 5, 6, 7, float("nan")], 3)
    assert w2[8] == pytest.approx(np.mean(w2[:8]))                            # NaN 학습점 = 평균 가중치
    assert cc.n_eff(np.ones(5)) == pytest.approx(5.0)


def test_signflip_exact():
    assert cc.signflip_p([1, 1, 1])["p"] == pytest.approx(0.125)
    assert cc.signflip_p([1, -1])["p"] == pytest.approx(0.75)
    assert cc.signflip_p([0, 0, 0])["p"] == pytest.approx(1.0)
    r = cc.signflip_p([1] * 17)
    assert r["method"] == "mc" and r["p"] < 1e-4
    assert cc.signflip_p([])["p"] is None


def test_judge_scores():
    a, b = [0.01] * 5, [0.01] * 11
    assert cc.judge_scores([0.01] * 3, b)["verdict"] == "NOT_EVALUABLE"
    assert cc.judge_scores([0.0] * 5, [0.0] * 11)["verdict"] == "NOT_EVALUABLE"   # noop
    assert cc.judge_scores(a, b)["verdict"] == "BEATS_BASELINE"
    assert cc.signflip_p(a + b)["p"] == pytest.approx(2 ** -16)
    j = cc.judge_scores([-0.01] * 5, b)
    assert j["verdict"] == "FAIL" and j["fail_kind"] == "FAIL"
    A = [0.05, -0.04, 0.05, -0.04, 0.05]
    B = [0.05, -0.04] * 5 + [0.05]
    j = cc.judge_scores(A, B)
    assert np.mean(A) > 0 and np.mean(B) > 0 and cc.signflip_p(A + B)["p"] >= cc.ALPHA
    assert j["verdict"] == "FAIL" and j["fail_kind"] == "FAIL_UNDERPOWERED"
    assert cc.judge_return(a, b)["verdict"] == "BEATS_LUMP"


def test_judge_insurance():
    G, D = [0.10] * 5, [-0.01] * 5
    G2, D2 = [0.10] * 11, [-0.01] * 11
    assert cc.judge_insurance(D, D2, G, G2)["verdict"] == "CHEAP_INSURANCE"
    assert cc.judge_insurance([-0.05] * 5, [-0.05] * 11, G, G2)["verdict"] == "FAIL"
    assert cc.judge_insurance(D, D2, [0.04] * 5, [0.04] * 11)["verdict"] == "FAIL"
    assert cc.judge_insurance(D[:3], D2, G[:3], G2)["verdict"] == "NOT_EVALUABLE"


def test_schedule_path():
    n = 900
    Lv, rf0 = np.full(n, 10.0), np.zeros(n)
    for s in cc.SCHEDULES.values():
        p = cc.schedule_path(Lv, rf0, 1, 756, s)
        assert np.allclose(p, 1.0)
    rf = np.full(n, 0.0001)
    lump = cc.schedule_path(Lv, rf, 1, 756, cc.SCHEDULES["LUMP"])
    dca12 = cc.schedule_path(Lv, rf, 1, 756, cc.SCHEDULES["DCA12"])
    assert dca12[-1] > lump[-1]
    Lv2 = np.full(n, 10.0)
    Lv2[2:] = 20.0                                                           # e+1 에 가격 2배
    assert cc.schedule_path(Lv2, rf0, 1, 756, cc.SCHEDULES["LUMP"])[-1] == pytest.approx(2.0)
    assert cc.schedule_path(Lv2, rf0, 1, 756, cc.SCHEDULES["DCA6"])[-1] < 2.0
    for name in ("DCA6", "DCA12", "HALF6"):
        _p, cash = cc.schedule_path(Lv, rf, 1, 756, cc.SCHEDULES[name], with_cash=True)
        last_off = max(o for o, _f in cc.SCHEDULES[name])
        assert np.all(cash[last_off:] == 0.0)                                 # 이자 포함 전부 투입
        assert cash[last_off - 1] > 0


# ---------------------------------------------------------------- 사건
def _seg(a, b, n):
    return list(np.linspace(a, b, n + 1)[1:])


def test_episode_trigger_recovery_merge_censor():
    v = list(np.linspace(50, 100, 300))                 # 0..299, 고점 100 @299
    v += _seg(100, 84, 20)                              # 300..319 하락 → 발생일
    v += _seg(84, 96, 20)                               # 320..339 −4% 로 반등 → 기존 정의 종료
    v += _seg(96, 84, 20)                               # 340..359 다시 하락 → 같은 고점 → 병합
    v += _seg(84, 101, 40)                              # 360..399 회복
    v += _seg(101, 110, 100)                            # 400..499 새 고점 110 @499
    v += _seg(110, 90, 20) + [90.0] * 41                # 500..560 하락 후 미회복
    Lv = np.array(v)
    L = pd.Series(Lv, index=pd.bdate_range("2000-01-03", periods=len(Lv)))
    eps, frame = cc.build_episodes(L)
    t0a = 300 + int(np.flatnonzero(Lv[300:320] <= 85.0)[0])
    t0b = 340 + int(np.flatnonzero(Lv[340:360] <= 85.0)[0])
    reca = 360 + int(np.flatnonzero(Lv[360:400] >= 100.0)[0])
    t0c = 500 + int(np.flatnonzero(Lv[500:] <= 110 * 0.85)[0])
    assert len(eps) == 2
    a, c = eps
    assert a["t0"] == t0a and a["tP"] == 299 and a["P"] == pytest.approx(100.0)
    assert a["dd0"] == pytest.approx(Lv[t0a] / 100 - 1)
    assert [r["_pos"] for r in a["retriggers"]] == [t0b]
    assert a["rec"] == reca and a["R"] == reca - t0a
    assert a["depth_settled"] and a["end1"] == reca
    assert a["FD"] == pytest.approx(84 / 100 - 1)
    assert c["t0"] == t0c and c["tP"] == 499 and c["rec"] is None and c["R"] is None
    assert not c["depth_settled"] and c["FD"] is None


def test_features_no_lookahead():
    n = 800
    r = np.random.default_rng(1)
    Lv = np.cumprod(1 + r.normal(0.0004, 0.01, n))
    Fv = np.cumprod(1 + r.normal(0.0003, 0.012, n))
    rfv = np.where(np.arange(n) < 400, 0.0001, 0.0002)
    t, tP = 600, 550
    f = cc.features_at(Lv, Fv, rfv, t, tP)
    assert f["SPEED"] == pytest.approx(math.log(50))
    assert f["RUNUP"] == pytest.approx(math.log(Lv[550] / Lv[46]))
    assert f["FINREL"] == pytest.approx(math.log(Fv[600] / Fv[550]) - math.log(Lv[600] / Lv[550]))
    assert f["RATECHG"] == pytest.approx(252 * 0.0002 - 252 * 0.0001)      # rfa(600) − rfa(348)
    L2, F2, r2 = Lv.copy(), Fv.copy(), rfv.copy()
    L2[t + 1:] *= 3
    F2[t + 1:] *= 0.1
    r2[t + 1:] = 0.05
    assert _js(cc.features_at(L2, F2, r2, t, tP)) == _js(f)
    assert math.isnan(cc.features_at(Lv, Fv, rfv, 300, 200)["RUNUP"])        # tP < 504


def _js(o) -> str:
    return json.dumps(cc._clean(o), sort_keys=True)


@pytest.fixture(scope="module")
def smoke_data():
    return cc.load(True)


def _perturbed(data, pos):
    """pos 이후의 시장·금융·RF 자료만 바꾼 사본."""
    d = dict(data)
    L = data["L"].copy()
    rng = np.random.default_rng(5)
    k = len(L) - pos - 1
    L.iloc[pos + 1:] = float(L.iloc[pos]) * np.cumprod(1 + rng.normal(-0.001, 0.02, k))   # pos 까지는 비트 단위로 같게
    d["L"] = L
    F = data["F"].copy()
    F.iloc[pos + 1:] = F.iloc[pos + 1:] * 0.5
    d["F"] = F
    rf = data["rf"].copy()
    rf.iloc[pos + 1:] = 0.001
    d["rf"] = rf
    return d


def test_expanding_window_no_lookahead(smoke_data):
    ctx = cc.build_context(smoke_data["L"], smoke_data["rf"], smoke_data["F"], smoke_data["F49"], None)
    ep = next(j for j in ctx["eps"] if j["era"] == "B" and j["_p1"] and j["_p2"])
    ctx2 = cc.build_context(*(lambda d: (d["L"], d["rf"], d["F"], d["F49"], None))(_perturbed(smoke_data, ep["t0"])))
    ep2 = next(j for j in ctx2["eps"] if j["t0"] == ep["t0"])
    assert ep2["tP"] == ep["tP"] and _js(ep2["feat"]) == _js(ep["feat"])
    assert _js(ep2["_p1"]) == _js(ep["_p1"])
    assert _js(ep2["_p2"]) == _js(ep["_p2"])
    assert not np.allclose(ctx2["Lv"][ep["t0"] + 1:], ctx["Lv"][ep["t0"] + 1:])   # 미래는 실제로 바뀌었다


def test_reading_at_no_lookahead(smoke_data):
    ctx = cc.build_context(smoke_data["L"], smoke_data["rf"], smoke_data["F"], smoke_data["F49"], None)
    idx = ctx["idx"]
    for date in ("2001-09-17", "1998-08-17"):                              # 스모크 자료에서 사건 안 / 사건 밖
        pos = int(idx.searchsorted(pd.Timestamp(date)))
        a = cc._clean(cc.reading_at(ctx, pos, bootstrap=False))
        d2 = _perturbed(smoke_data, pos)
        ctx2 = cc.build_context(d2["L"], d2["rf"], d2["F"], d2["F49"], None)
        b = cc._clean(cc.reading_at(ctx2, pos, bootstrap=False))
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    states = {cc.reading_at(ctx, int(idx.searchsorted(pd.Timestamp(d))))["state"] for d in ("2001-09-17", "1998-08-17")}
    assert states == {"in_episode", "not_in_episode"}


def test_map_event():
    Lv = np.full(1000, 100.0)
    Lv[100:300] = 80.0                                                     # 사건 1: 100 에 시작, 300 에 회복
    Lv[500:600] = 70.0                                                     # 사건 2: 500 에 시작
    eps = [{"t0": 100, "P": 100.0}, {"t0": 500, "P": 100.0}]
    assert cc.map_event(eps, Lv, 100)["mapping"] == "trigger"
    m = cc.map_event(eps, Lv, 150)
    assert m["mapping"] == "inside" and m["ep"]["t0"] == 100 and m["lag_days"] == 50
    m = cc.map_event(eps, Lv, 400)
    assert m["mapping"] == "trigger_after" and m["ep"]["t0"] == 500 and m["lag_days"] == 100
    assert cc.map_event(eps, Lv, 700)["mapping"] == "none"
    m = cc.map_event(eps, Lv, 320)                                         # 사건 1 회복 뒤, 180 거래일 뒤 사건 2
    assert m["mapping"] == "trigger_after" and m["lag_days"] == 180
    assert cc.map_event(eps, Lv, 200)["ep"]["t0"] == 100                   # 아직 회복 전 = 안


# ---------------------------------------------------------------- 통합
def test_job_json_valid():
    from core.research_jobs import validate_job

    data = json.loads((ROOT / "research" / "jobs" / "crash-cycle-model-v1" / "job.json").read_text(encoding="utf-8"))
    job, err = validate_job(data, "crash-cycle-model-v1", ROOT)
    assert job is not None and err == ""


def test_smoke_end_to_end(tmp_path):
    assert cc.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    path = tmp_path / "o" / "results.json"
    res = json.loads(path.read_text(encoding="utf-8"))
    assert list(res["verdicts"]) == list(cc.VERDICT_KEYS) and len(res["verdicts"]) == 14
    allowed = {"BEATS_BASELINE", "BEATS_LUMP", "CHEAP_INSURANCE", "FAIL", "NOT_EVALUABLE"}
    assert all(v in allowed for v in res["verdicts"].values())
    assert len(res["summary"]) == 5
    assert [e["key"] for e in res["events"]] == [k for k, _l, _d in cc.EVENTS]
    assert res["current"]["state"] in {"in_episode", "not_in_episode"}
    assert res["data"]["network_extras"] == {"gspc": False, "spy": False, "cpi": False}
    rep = (tmp_path / "o" / "REPORT.md").read_text(encoding="utf-8")
    assert "지금 읽기 (설명용 — 추천 아님)" in rep and "사용자가 든 7개 사건" in rep
    assert "nan" not in rep.lower().replace("nancial", "")
    assert path.stat().st_size < 256 * 1024
