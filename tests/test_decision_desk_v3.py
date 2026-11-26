"""판단판 3판 모형 읽기 — lab_version 으로 엔진 고르기, 1판 경로 그대로, 3판 V3 + 같은 자리 ENS1 기록, 재무(디스크만) 대체, 화면·채점."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from core import decision_desk as dd
from hub import desk_page


def _layer(P, lab, library, *, fx_grid=None, borrow=None):
    H, K1, K2, KP = len(lab.HORIZONS), lab.K1, lab.K2, lab.KP
    nk = len(lab.KINDS)
    cells = {f"{h}:{k}": {"grade": "보통" if h == 63 else "약함", "grade_vs_v1": "강함" if (h, k) == (63, "q") else "없음"}
             for h in lab.HORIZONS for k in lab.KINDS}
    return {"feats": list(P["feats"]), "hx": list(P["hx"]), "sixth": P["sixth"], "library": library, "borrow_library": borrow,
            "weights1": np.full((H, nk, K1), 1 / K1).tolist(), "weights2": np.full((H, nk, K2), 1 / K2).tolist(),
            "shifts2": np.zeros((H, 5)).tolist(), "weights3": np.full((H, nk, KP), 1 / KP).tolist(),
            "shifts3": np.full((H, 5), 0.05).tolist(), "blend": [[0.5, 0.5]] * H, "cal_active": [True] * H,
            "xs_grid": None, "fx_grid": fx_grid, "cells": cells}


@pytest.fixture(scope="module")
def world3(tmp_path_factory):
    """가짜 시장·종목으로 만든 작은 3판 모형(시장 층은 업종 서고를 빌림, 종목 층은 재무 격자 있음)과 가격."""
    lab = dd.lab3()
    l1, l2 = lab.V, lab.L2
    m, assets = l1.synthetic_panel(n_assets=6, n_days=2200, seed=3)
    origins = m.index[252::l1.STEP]
    ms2 = l2.market_state2(m)
    f2 = {}
    for k, lp in assets.items():
        f2[k] = l2.asset_frame2(lp, m)
        f2[k][["mdd", "mvolr", "m21", "m252"]] = ms2
    P2 = l2.attach(l1.build_points(f2, origins, with_market=True), f2, True)
    raw = np.random.default_rng(4).normal(size=(len(P2["date"]), len(lab.FX)))
    raw[P2["asset"] == 0] = np.nan
    P3 = lab.attach3(P2, raw)
    fm = {"MKT": l2.asset_frame2(m)}
    Pm = lab.attach3(l2.attach(l1.build_points(fm, m.index[252::5], with_market=False), fm, False, borrow=P3))
    d = tmp_path_factory.mktemp("model3")
    for name, P in (("market", Pm), ("industry", P3), ("stock", P3)):
        lab.export_library3(P).to_csv(d / f"library_{name}.csv", index=False)
    grid = [np.linspace(-3, 3, l2.GRID).tolist()] * len(lab.FX)
    model = {"study": "desk-engine-v3-test", "lab_version": lab.LAB_VERSION, "data_end": "2008-06-30", "smoke": True,
             "layers": {"market": _layer(Pm, lab, "library_market.csv", borrow="library_industry.csv"),
                        "industry": _layer(P3, lab, "library_industry.csv"),
                        "stock": _layer(P3, lab, "library_stock.csv", fx_grid=grid)}}
    (d / "model.json").write_text(json.dumps(model), encoding="utf-8")
    prices = {"SPY": m, **{f"T{k}": lp for k, lp in enumerate(assets.values())}}
    closes = {t: float(math.exp(s.iloc[-1])) for t, s in prices.items()}
    return {"dir": d, "prices": prices, "closes": closes, "model": dd.load_model(d, tmp_path_factory.mktemp("nofund")), "lab": lab}


class FakeFund:
    def __init__(self, v):
        self.v, self.calls = v, []

    def values(self, ticker, asof):
        self.calls.append((ticker, str(pd.Timestamp(asof).date())))
        return list(self.v)


def _snap(w):
    holdings = [{"ticker": "T0", "quantity": 10, "purchase_price": 0.5}, {"ticker": "T1", "quantity": 1, "purchase_price": 2.0}]
    return dd.build_snapshot(w["model"], w["prices"], w["closes"], holdings, ["T2", "QQQ"], cash=10.0, crash_lines=["급락 사건 아님"],
                             now=datetime(2026, 11, 26, tzinfo=timezone.utc))


# ---------------------------------------------------------------- 설정·엔진 고르기
def test_default_setting_is_v1():
    assert dd.MODEL_STUDY == "desk-engine-v1" and dd.MODEL_DIR.name == "desk-engine-v1"
    assert dd.DEFAULT_LAB_VERSION == "desk-engine-lab/v1"


def test_dispatch_on_lab_version(world3, tmp_path):
    assert dd.engine_of({"lab_version": "desk-engine-lab/v1"})[1] is dd._predict_v1
    assert dd.engine_of({})[1] is dd._predict_v1                                        # lab_version 이 없는 옛 모형 = 1판
    assert dd.engine_of({"lab_version": "desk-engine-lab/v3"})[1] is dd._predict_v3
    assert dd.engine_of({"lab_version": "desk-engine-lab/v9"}) is None
    assert not dd.side_by_side({"lab_version": "desk-engine-lab/v1"}) and dd.side_by_side({"lab_version": "desk-engine-lab/v3"})
    bad = json.loads((world3["dir"] / "model.json").read_text(encoding="utf-8")) | {"lab_version": "desk-engine-lab/v9"}
    for f in world3["dir"].glob("library_*.csv"):
        (tmp_path / f.name).write_bytes(f.read_bytes())
    (tmp_path / "model.json").write_text(json.dumps(bad), encoding="utf-8")
    assert dd.load_model(tmp_path) is None                                               # 모르는 엔진은 읽지 않는다


def test_load_v3_model(world3):
    model = world3["model"]
    assert set(model["libs"]) == {"market", "industry", "stock"} and "FR" in model["libs"]["stock"]
    assert model["layers"]["market"]["borrow_library_layer"] == "industry" and model["layers"]["stock"]["borrow_library_layer"] is None
    assert isinstance(model["fund"], dd.DiskFundamentals)


# ---------------------------------------------------------------- 3판 한 장
def test_v3_sheet_matches_lab_and_carries_ens1(world3):
    model, lab, pr = world3["model"], world3["lab"], world3["prices"]
    model["fund"] = FakeFund([math.nan] * 4)
    sh = dd.sheet(model, "T1", pr["T1"], pr["SPY"])
    assert sh["layer"] == "stock" and "error" not in sh and len(sh["horizons"]) == 4 and sh["fx_known"] == 0
    st = lab.L2.latest_state2(pr["T1"].dropna(), pr["SPY"])
    st["fx"] = [math.nan] * 4
    f = lab.forecast_live3(model["libs"]["stock"], model["layers"]["stock"], st)
    for hi, r in enumerate(sh["horizons"]):
        assert r["q"] == pytest.approx([math.expm1(v) for v in f["q"]["V3"][hi]])
        assert r["v1"]["q"] == pytest.approx([math.expm1(v) for v in f["q"]["ENS1"][hi]])
        assert r["q_base"] == pytest.approx([math.expm1(v) for v in f["q"]["CLIM"][hi]])
        assert r["p"]["dd15"] == pytest.approx(f["p"]["V3"][hi][1]) and r["v1"]["p"]["dd15"] == pytest.approx(f["p"]["ENS1"][hi][1])
        assert r["q"] == sorted(r["q"]) and set(r["p"]) == set(r["v1"]["p"]) == {"up", "dd15", "beat"}
        assert set(r["grade_vs_v1"]) == {"q", "up", "dd15", "beat"}
    assert sh["horizons"][1]["grade"]["q"] == "보통" and sh["horizons"][1]["grade_vs_v1"]["q"] == "강함"   # model.json 칸에서
    assert sh["horizons"][0]["grade_vs_v1"]["q"] == "없음"
    assert any(not np.allclose(r["q"], r["v1"]["q"]) for r in sh["horizons"])          # 서로 다른 엔진의 값


def test_v3_market_borrow_and_industry(world3):
    model, pr = world3["model"], world3["prices"]
    mk = dd.sheet(model, "SPY", pr["SPY"], None)
    assert mk["layer"] == "market" and "fx_known" not in mk and all("beat" not in r["p"] for r in mk["horizons"])
    assert all("v1" in r for r in mk["horizons"])
    ind = dd.sheet(model, "QQQ", pr["T2"], pr["SPY"])
    assert ind["layer"] == "industry" and "fx_known" not in ind


def test_v3_fundamentals_feed_fund_expert_only_on_stock_layer(world3):
    model, pr = world3["model"], world3["prices"]
    model["fund"] = FakeFund([math.nan] * 4)
    a = dd.sheet(model, "T1", pr["T1"], pr["SPY"])
    fake = FakeFund([2.0, 2.0, 1.0, 2.5])
    model["fund"] = fake
    b = dd.sheet(model, "T1", pr["T1"], pr["SPY"])
    assert b["fx_known"] == 4 and fake.calls == [("T1", a["asof"])]                       # 기준일을 넘기고, 전날 처리는 reader 가
    assert any(not np.allclose(x["q"], y["q"]) for x, y in zip(a["horizons"], b["horizons"]))
    assert all(np.allclose(x["v1"]["q"], y["v1"]["q"]) for x, y in zip(a["horizons"], b["horizons"]))   # ENS1 은 재무를 쓰지 않는다
    model["fund"] = None                                                                  # 저장소 없음 = 모름
    c = dd.sheet(model, "T1", pr["T1"], pr["SPY"])
    assert c["fx_known"] == 0 and [x["q"] for x in c["horizons"]] == [x["q"] for x in a["horizons"]]
    model["fund"] = FakeFund([1.0] * 4)
    dd.sheet(model, "SPY", pr["SPY"], None)
    assert model["fund"].calls == []                                                      # 시장·업종 층은 재무를 묻지 않는다


def test_disk_fundamentals_point_in_time_and_no_network(tmp_path):
    from core import fundamentals_pit as fp

    rec = {"ticker": "AAA", "fetched_at": "2020-01-01T00:00:00+00:00", "sic": 1, "earnings_dates": [],
           "facts": {"gross_profit": [["2018-01-01", "2018-12-31", 40.0, "2019-02-20", "10-K"]],
                     "assets": [[None, "2018-12-31", 100.0, "2019-02-20", "10-K"]], "revenue": [], "net_income": [], "cost_of_revenue": []}}
    (tmp_path / "AAA.json").write_text(json.dumps(rec), encoding="utf-8")
    (tmp_path / "GONE.json").write_text(json.dumps({"ticker": "GONE", "fetched_at": "2020-01-01T00:00:00+00:00", "missing": "cik"}), encoding="utf-8")
    (tmp_path / "BAD.json").write_text("{not json", encoding="utf-8")
    f = dd.DiskFundamentals(tmp_path)
    assert f.store.fetch is False
    f.store._download = lambda t: pytest.fail("네트워크로 받으면 안 됨")
    assert np.isnan(f.values("AAA", "2019-02-20")).all()                                  # 기준일 당일 공시는 아직 모른다(전날까지)
    v = f.values("AAA", "2019-02-21")
    assert v[0] == pytest.approx(0.4) and np.isnan(v[1:]).all()
    assert v[0] == pytest.approx(fp.view_from_record(rec, date(2019, 2, 20))["gp_assets"])
    for t in ("GONE", "NOFILE", "BAD"):
        assert np.isnan(f.values(t, "2019-06-01")).all()
    assert not list(tmp_path.glob("NOFILE*"))                                             # 쓰지 않는다
    broken = dd.DiskFundamentals(tmp_path)
    broken.store = None
    assert np.isnan(broken.values("AAA", "2019-06-01")).all()


def test_fund_values_same_as_research_run():
    import importlib.util

    spec = importlib.util.spec_from_file_location("desk_engine_v3_run_for_test", dd.PROJECT_ROOT / "research/jobs/desk-engine-v3/run.py")
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    assert run.FUND_LAG_DAYS == dd.FUND_LAG_DAYS and len(dd.lab3().FX) == dd.FX_LEN
    for v in ({"gp_assets": 0.3, "rev_yoy": 0.10, "rev_yoy_prev": 0.04, "ni_yoy": None}, None,
              {"gp_assets": None, "rev_yoy": 0.1, "rev_yoy_prev": None, "ni_yoy": -0.2}):
        assert np.allclose(dd.fund_values(v), run.fund_values(v), equal_nan=True)


# ---------------------------------------------------------------- 판단판 한 장·기록·채점
def test_v3_snapshot_history_side_by_side(world3, tmp_path):
    world3["model"]["fund"] = FakeFund([math.nan] * 4)
    snap = _snap(world3)
    assert snap["status"] == "ok" and snap["model"]["lab_version"] == "desk-engine-lab/v3" and snap["model"]["compare"] == "ENS1"
    assert snap["model"]["grades_vs_v1"]["stock"]["63:q"] == "강함"
    n = dd.write_snapshot(snap, tmp_path)
    rows = dd.read_history(tmp_path)
    assert n == len(rows) == 5
    for r in rows:
        assert r["lab_version"] == "desk-engine-lab/v3" and r["model"] == "desk-engine-v3-test"
        for h in r["horizons"]:
            assert set(h) == {"h", "q", "p", "v1"} and len(h["v1"]["q"]) == 5 and set(h["v1"]["p"]) <= {"up", "dd15", "beat"}
    json.dumps(dd.read_snapshot(tmp_path))                                                # 저장한 한 장에 numpy 값이 없다


def test_v1_history_rows_unchanged_shape():
    snap = {"model": {"study": "desk-engine-v1"}, "market": {"asof": "2026-11-25", "ticker": "SPY", "layer": "market",
                                                             "horizons": [{"h": 21, "q": [-0.1, -0.05, 0.0, 0.05, 0.1], "p": {"up": 0.6}}]}}
    assert dd.history_rows(snap) == [{"asof": "2026-11-25", "ticker": "SPY", "layer": "market", "model": "desk-engine-v1",
                                      "horizons": [{"h": 21, "q": [-0.1, -0.05, 0.0, 0.05, 0.1], "p": {"up": 0.6}}]}]


def test_score_history_pairs_v3_with_v1(world3):
    s = world3["prices"]["T0"]
    pos = len(s) - 80
    h = lambda hh: {"h": hh, "q": [-0.2, -0.1, 0.0, 0.1, 0.2], "p": {"up": 0.6, "dd15": 0.1},  # noqa: E731
                    "v1": {"q": [-0.5, -0.2, 0.0, 0.2, 0.5], "p": {"up": 0.5, "dd15": 0.3}}}
    row = {"asof": str(s.index[pos].date()), "ticker": "T0", "horizons": [h(21), h(63), h(126)]}
    ls = dd.score_history([row], world3["prices"])
    assert [r["h"] for r in ls["horizons"]] == [21, 63] and ls["pending"] == 1
    c = ls["horizons"][0]["vs_v1"]
    y = math.expm1(float(s.iloc[pos + 21] - s.iloc[pos]))
    assert c["n"] == 1 and c["pinball"] == pytest.approx(dd._pinball(y, h(21)["q"])) and c["pinball_v1"] == pytest.approx(dd._pinball(y, h(21)["v1"]["q"]))
    up = float(y > 0)
    assert c["events"]["up"]["brier"] == pytest.approx((0.6 - up) ** 2) and c["events"]["up"]["brier_v1"] == pytest.approx((0.5 - up) ** 2)
    plain = {"asof": row["asof"], "ticker": "T0", "horizons": [{k: v for k, v in x.items() if k != "v1"} for x in row["horizons"]]}
    assert all("vs_v1" not in r for r in dd.score_history([plain], world3["prices"])["horizons"])   # 1판 기록은 예전 모양 그대로
    assert dd._pinball(0.0, [0.0] * 5) == 0.0 and dd._pinball(1.0, [0.0] * 5) == pytest.approx(0.5)


def test_v3_page_and_summary(world3):
    from scripts import decision_desk as script

    world3["model"]["fund"] = FakeFund([math.nan] * 4)
    snap = _snap(world3)
    snap["live_score"] = {"pending": 0, "horizons": [{"h": 21, "n": 3, "coverage80": 0.66, "events": {},
                                                      "vs_v1": {"n": 3, "pinball": 0.01, "pinball_v1": 0.02,
                                                                "events": {"dd15": {"n": 3, "brier": 0.1, "brier_v1": 0.2}}}}]}
    html = desk_page.render_body({"snap": snap})
    for text in ("1판 10~90%", "1판 대비", "3판 모형으로 읽는 중", "1판과 비교", "범위 손실 0.0100 / 1판 0.0200", "재무 값 0/4", "시험용 모형"):
        assert text in html
    assert "<script" not in html
    lines = script.summary_lines(snap)
    assert any("| 1판" in x for x in lines if x.strip().startswith("T0:"))


def test_v1_page_has_no_v3_columns():
    """1판 모형의 한 장(옛 모양)은 예전 화면 그대로 — 1판 비교 열·3판 설명이 붙지 않는다."""
    r = {"h": 63, "q": [-0.1, -0.05, 0.0, 0.05, 0.1], "q_base": [-0.1, -0.05, 0.0, 0.05, 0.1], "p": {"dd15": 0.1}, "p_base": {"dd15": 0.1},
         "grade": {"q": "강함", "dd15": "강함"}, "n": 100}
    sh = {"ticker": "SPY", "layer": "market", "asof": "2026-11-25", "horizons": [r], "flags": []}
    snap = {"status": "ok", "asof": "2026-11-25", "market": sh, "positions": [], "watch": [], "crash": [], "note": dd.NOTE,
            "model": {"study": "desk-engine-v1", "lab_version": "desk-engine-lab/v1"}}
    html = desk_page.render_body({"snap": snap})
    assert "1판 대비" not in html and "3판 모형" not in html and "재무 값" not in html
