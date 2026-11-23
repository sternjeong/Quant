"""판단판 — 모형 읽기, 자산 한 장, 층 고르기, 포트폴리오 합치기, 저장·기록, 화면, 잡 등록."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from core import decision_desk as dd
from hub import desk_page


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """가짜 시장·종목으로 만든 작은 모형(시장 층 + 종목 층)과 가격."""
    lab = dd.lab()
    m, assets = lab.synthetic_panel(n_assets=6, n_days=2600, seed=4)
    ms = lab.market_state(m)
    origins = m.index[252::lab.STEP]
    frames = {}
    for k, lp in assets.items():
        f = lab.asset_frame(lp, m)
        f[["mdd", "mvolr"]] = ms
        frames[k] = f
    points = {"stock": lab.build_points(frames, origins, with_market=True),
              "market": lab.build_points({"MKT": lab.asset_frame(pd.concat([m, m + 7.0]).set_axis(
                  pd.bdate_range("1980-01-01", periods=2 * len(m))))}, pd.bdate_range("1980-01-01", periods=2 * len(m))[252::5], with_market=False)}
    d = tmp_path_factory.mktemp("model")
    model = {"study": "desk-engine-test", "lab_version": lab.LAB_VERSION, "data_end": "2009-12-18", "smoke": True, "layers": {}}
    for name, P in points.items():
        lab.export_library(P).to_csv(d / f"library_{name}.csv", index=False)
        cells = {f"{h}:{k}": {"grade": "보통" if h == 63 else "약함"} for h in lab.HORIZONS for k in lab.KINDS}
        model["layers"][name] = {"feats": list(P["feats"]), "library": f"library_{name}.csv",
                                 "weights": np.full((4, 4, 4), 0.25).tolist(), "cells": cells}
    (d / "model.json").write_text(json.dumps(model), encoding="utf-8")
    prices = {"SPY": m, **{f"T{k}": lp for k, lp in enumerate(assets.values())}}
    closes = {t: float(math.exp(s.iloc[-1])) for t, s in prices.items()}
    return {"dir": d, "prices": prices, "closes": closes, "model": dd.load_model(d)}


def test_load_model_and_missing(world, tmp_path):
    assert world["model"] is not None and set(world["model"]["libs"]) == {"market", "stock"}
    assert dd.load_model(tmp_path) is None


def test_layer_routing(world):
    model = world["model"]
    assert dd.layer_for("SPY", model) == "market" and dd.layer_for("NVDA", model) == "stock"
    assert dd.layer_for("XLE", model) == "stock"                    # 업종 층 모형이 없으면 종목 층으로
    assert dd.layer_for("XLE", {"libs": {"industry": 1, "stock": 1}}) == "industry"
    assert dd.layer_for(dd.PORTFOLIO_KEY, {"libs": {"industry": 1}}) == "industry"


def test_sheet_numbers(world):
    sh = dd.sheet(world["model"], "T0", world["prices"]["T0"], world["prices"]["SPY"])
    assert sh["layer"] == "stock" and "error" not in sh and len(sh["horizons"]) == 4
    for r in sh["horizons"]:
        assert r["q"] == sorted(r["q"]) and r["q"][0] > -1 and all(0 <= v <= 1 for v in r["p"].values())
        assert set(r["p"]) == {"up", "dd15", "beat"} and set(r["grade"]) == {"q", "up", "dd15", "beat"}
    assert sh["horizons"][1]["grade"]["q"] == "보통" and sh["horizons"][0]["grade"]["q"] == "약함"
    wide = [r["q"][4] - r["q"][0] for r in sh["horizons"]]
    assert wide == sorted(wide)                                     # 기간이 길수록 범위가 넓다
    st = sh["stats"]
    s = world["prices"]["T0"]
    assert st["dd_252"] == pytest.approx(math.expm1(s.iloc[-1] - s.iloc[-252:].max()))
    assert st["ret"]["63"] == pytest.approx(math.expm1(s.iloc[-1] - s.iloc[-64]))


def test_sheet_market_and_foreign_have_no_beat(world):
    mk = dd.sheet(world["model"], "SPY", world["prices"]["SPY"], None)
    assert mk["layer"] == "market" and all("beat" not in r["p"] for r in mk["horizons"])
    kr = dd.sheet(world["model"], "005930.KS", world["prices"]["T1"], world["prices"]["SPY"])
    assert kr["foreign"] and all("beat" not in r["p"] for r in kr["horizons"])
    assert any("미국 대형주" in f for f in kr["flags"])


def test_sheet_short_history(world):
    sh = dd.sheet(world["model"], "NEW", world["prices"]["T0"].iloc[-120:], world["prices"]["SPY"])
    assert "error" in sh and "horizons" not in sh


def test_sheet_uses_only_given_history(world):
    """마지막 날을 자르면 그 전날 기준 예측이 나온다(앞날 자료를 쓰지 않는다)."""
    s, m = world["prices"]["T2"], world["prices"]["SPY"]
    a = dd.sheet(world["model"], "T2", s.iloc[:-30], m.iloc[:-30])
    s2 = s.copy()
    s2.iloc[-30:] += 0.4
    b = dd.sheet(world["model"], "T2", s2.iloc[:-30], m.iloc[:-30])
    assert a["asof"] == str(s.index[-31].date()) and a["horizons"] == b["horizons"]


def test_aggregate_holdings():
    rows = dd.aggregate_holdings([{"ticker": "aaa", "quantity": 10, "purchase_price": 100}, {"ticker": "AAA", "quantity": 10, "purchase_price": 200},
                                  {"ticker": "BBB", "quantity": 5, "purchase_price": 50}, {"ticker": "CCC", "quantity": 0, "purchase_price": 1}],
                                 {"AAA": 300.0, "BBB": None})
    a, b = rows
    assert a["ticker"] == "AAA" and a["quantity"] == 20 and a["avg_cost"] == 150 and a["value"] == 6000 and a["pnl_pct"] == pytest.approx(1.0)
    assert a["weight"] == pytest.approx(1.0) and b["value"] is None and b["weight"] is None and len(rows) == 2


def test_portfolio_series(world):
    pr = world["prices"]
    pos = [{"ticker": "T0", "weight": 0.5}, {"ticker": "T1", "weight": 0.5}, {"ticker": "T9", "weight": 0.1},
           {"ticker": "T2", "weight": None}]
    lp, dropped = dd.portfolio_series(pos, pr | {"T9": pr["T0"].iloc[-50:]})
    assert dropped == ["T9"] and len(lp) == len(pr["T0"]) - 1
    r = 0.5 * np.expm1(pr["T0"].diff()) + 0.5 * np.expm1(pr["T1"].diff())
    assert lp.iloc[-1] == pytest.approx(np.log1p(r.dropna()).sum())
    assert dd.portfolio_series([{"ticker": "T9", "weight": 1.0}], {"T9": pr["T0"].iloc[-50:]}) == (None, ["T9"])


def _snap(world):
    holdings = [{"ticker": "T0", "quantity": 10, "purchase_price": 0.5}, {"ticker": "T1", "quantity": 1, "purchase_price": 2.0}]
    return dd.build_snapshot(world["model"], world["prices"], world["closes"], holdings, ["T2", "T0", "SPY", "ZZZ"], cash=100.0,
                             crash_lines=["급락 사건 아님"], now=datetime(2026, 11, 23, tzinfo=timezone.utc))


def test_build_snapshot(world):
    snap = _snap(world)
    assert snap["status"] == "ok" and snap["market"]["ticker"] == "SPY" and snap["asof"] == snap["market"]["asof"]
    assert [p["ticker"] for p in snap["positions"]] == sorted(["T0", "T1"], key=lambda t: -snap_value(snap, t))
    assert [w["ticker"] for w in snap["watch"]] == ["T2", "ZZZ"]     # 보유·SPY 는 관심 목록에서 뺀다
    assert snap["watch"][1]["error"] == "가격을 읽지 못함"
    p0 = next(p for p in snap["positions"] if p["ticker"] == "T0")
    r63 = next(r for r in p0["horizons"] if r["h"] == 63)
    assert p0["position"]["bad_case_63"] == pytest.approx(p0["position"]["value"] * r63["q"][0])
    port = snap["portfolio"]
    assert port["ticker"] == dd.PORTFOLIO_KEY and port["cash"] == 100.0 and len(port["horizons"]) == 4
    assert port["value"] == pytest.approx(sum(p["position"]["value"] for p in snap["positions"]))
    assert snap["model"]["smoke"] is True and snap["model"]["grades"]["stock"]["63:q"] == "보통"


def snap_value(snap, ticker):
    return next(p["position"]["value"] for p in snap["positions"] if p["ticker"] == ticker)


def test_snapshot_without_model_or_market(world):
    assert dd.build_snapshot(None, {}, {}, [], [])["status"] == "no_model"
    assert dd.build_snapshot(world["model"], {}, {}, [], [])["status"] == "no_market"


def test_write_snapshot_and_history_once(world, tmp_path):
    snap = _snap(world)
    n1 = dd.write_snapshot(snap, tmp_path)
    assert n1 == 5 and dd.write_snapshot(snap, tmp_path) == 0        # SPY + 포트폴리오 + 보유 2 + 관심 1, 두 번째는 덧붙이지 않음
    assert dd.read_snapshot(tmp_path)["asof"] == snap["asof"]
    rows = [json.loads(x) for x in (tmp_path / dd.HISTORY_NAME).read_text(encoding="utf-8").splitlines()]
    assert {r["ticker"] for r in rows} == {"SPY", dd.PORTFOLIO_KEY, "T0", "T1", "T2"} and len(rows[0]["horizons"]) == 4
    assert dd.read_snapshot(tmp_path / "none") is None


def test_page_renders(world):
    snap = _snap(world)
    html = desk_page.render_body({"snap": snap})
    for text in ("시장 (SPY)", "내 포트폴리오 전체", "보유 종목 2", "관심 종목 2", "읽는 법", "근거 등급", "시험용 모형", "급락 사건 아님", "ZZZ"):
        assert text in html
    assert "<script" not in html
    assert "아직 없습니다" in desk_page.render_body({"snap": None})
    assert "만들지 못했습니다" in desk_page.render_body({"snap": dd.build_snapshot(None, {}, {}, [], [])})
    assert "기준" in desk_page.card_badge({"snap": snap}) and "아직 없음" in desk_page.card_badge({"snap": None})


def test_page_escapes_text(world):
    snap = _snap(world)
    snap["watch"][1]["ticker"] = "<b>X</b>"
    snap["crash"] = ["<script>alert(1)</script>"]
    html = desk_page.render_body({"snap": snap})
    assert "<b>X</b>" not in html and "<script>alert" not in html


def test_hub_route_and_slot():
    from hub import server
    from hub.apps_registry import SLOTS

    slot = next(s for s in SLOTS if s.id == "desk")
    assert slot.kind == "desk" and server._slot_href(slot, "h") == "/desk"
    assert "판단판" in server.render_desk_page()


def test_job_is_registered():
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    cron = SCHEDULED_JOBS_BY_ID["decision_desk"].cron
    assert cron["day_of_week"] == "tue-sat" and (cron["hour"], cron["minute"]) == (8, 5)
    assert PROCESS_REGISTRY["decision_desk"]["default_enabled"] is True


def test_script_summary_lines(world):
    from scripts import decision_desk as script

    lines = script.summary_lines(_snap(world))
    assert lines[0].startswith("판단판 기준일") and any(x.strip().startswith("T0:") for x in lines)
    assert any("ZZZ: 가격을 읽지 못함" in x for x in lines)
    assert script.summary_lines({"status": "no_model", "message": "없음"}) == ["없음"]


def test_score_history_against_realized(world):
    s, m = world["prices"]["T0"], world["prices"]["SPY"]
    pos = len(s) - 80                                               # 21·63 은 지났고 126·252 는 대기
    row = {"asof": str(s.index[pos].date()), "ticker": "T0", "horizons": [
        {"h": h, "q": [-0.5, -0.1, 0.0, 0.1, 0.5], "p": {"up": 0.7, "dd15": 0.1, "beat": 0.5}} for h in (21, 63, 126, 252)]}
    port = {"asof": row["asof"], "ticker": dd.PORTFOLIO_KEY, "horizons": row["horizons"]}
    ls = dd.score_history([row, port, {"asof": "1999-01-01", "ticker": "T0", "horizons": row["horizons"]}], world["prices"])
    assert [r["h"] for r in ls["horizons"]] == [21, 63] and ls["pending"] == 2
    r21 = ls["horizons"][0]
    ret = float(s.iloc[pos + 21] - s.iloc[pos])
    assert r21["n"] == 1 and r21["coverage80"] == float(-0.5 <= math.expm1(ret) <= 0.5)
    assert r21["events"]["up"]["freq"] == float(ret > 0)
    assert r21["events"]["up"]["brier"] == pytest.approx((0.7 - float(ret > 0)) ** 2)
    assert r21["events"]["beat"]["freq"] == float(ret > float(m.iloc[pos + 21] - m.iloc[pos]))
    assert dd.score_history([], world["prices"]) == {"pending": 0, "horizons": []}


def test_page_live_score_section(world, tmp_path):
    snap = _snap(world)
    snap["live_score"] = {"pending": 3, "horizons": []}
    assert "기간이 다 지난 예측이 아직 없습니다" in desk_page.render_body({"snap": snap})
    snap["live_score"] = {"pending": 0, "horizons": [{"h": 21, "n": 12, "coverage80": 0.75, "events": {"up": {"n": 12, "brier": 0.2, "freq": 0.5, "mean_p": 0.6}}}]}
    html = desk_page.render_body({"snap": snap})
    assert "범위 적중(목표 80%)" in html and "75%" in html and "오름 예측 60% / 실제 50%" in html
    dd.write_snapshot(snap, tmp_path)
    assert len(dd.read_history(tmp_path)) == 5
