"""승격 가설의 paper 편입(research 슬리브)·승인 버튼·텔레그램 목록 동기화."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import hypothesis_registry as reg
from core import hypothesis_shadow as sh
from core import models
from core import research_sleeve as rs
from core.paper_execution import SLEEVE_RESEARCH, build_order_plan, enforce_order_gate
from scripts.champion_paper_trade import build_plan

ROOT = Path(__file__).resolve().parent.parent
CORE = {"top4": ["XLK"], "per_ticker_weights": {"XLK": 0.2, "XLV": 0.2}, "new_orders_allowed": True}
SAT = {"selected": [], "per_ticker_weights": {"NVDA": 0.1}, "new_orders_allowed": True}
SPEC = {"source": "t", "thesis": "t", "universe": {"type": "list", "tickers": ["AAA"]}, "signal": {"params_grid": [{}]},
        "portfolio": {"top_k": 2, "rebalance": "monthly", "max_weight": 0.25}, "period": {"start": "2016-01-01"},
        "kill_criteria": {"min_rebalances": 12, "max_drawdown": 0.5}}


@pytest.fixture()
def db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'r.db'}")
    models.Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _promoted(db, hid, weights, as_of):
    reg.register_draft({**SPEC, "id": hid}, session=db)
    reg.freeze(hid, "def score(p,a,k): return {}", session=db)
    for to in (reg.PASS, reg.SHADOW, reg.CANDIDATE, reg.PROMOTED):
        reg.transition(hid, to, session=db)
    db.add(models.HypothesisShadowRecord(hypothesis_id=hid, as_of=as_of, weights_json=json.dumps({"w": weights, "days": 1})))
    db.commit()


# ---------------------------------------------------------------- 목표 계산
def test_no_promoted_means_empty_open_sleeve(db):
    r = rs.compute_research_targets(session=db, today=date(2026, 10, 6))
    assert r == {"targets": {}, "new_orders_allowed": True, "hold_reason": "", "hypotheses": []}


def test_allocation_per_hypothesis_hand_computed(db):
    _promoted(db, "H-20261001-001", {"AAA": 0.25, "BBB": 0.25}, date(2026, 10, 5))
    r = rs.compute_research_targets(session=db, today=date(2026, 10, 6))
    assert r["targets"] == pytest.approx({"AAA": 0.0125, "BBB": 0.0125})   # 가설 1개 → 5% × 25%
    for i in (2, 3, 4):
        _promoted(db, f"H-20261001-00{i}", {"AAA": 0.5}, date(2026, 10, 5))
    r = rs.compute_research_targets(session=db, today=date(2026, 10, 6))
    # 가설 4개 → 가설당 min(5%, 10%/4)=2.5%. AAA = 2.5%×25% + 3×(2.5%×50%)
    assert r["targets"]["AAA"] == pytest.approx(0.025 * 0.25 + 3 * 0.025 * 0.5)
    assert sum(r["targets"].values()) <= rs.SLEEVE_FRACTION + 1e-12


def test_stale_record_holds_whole_sleeve(db):
    _promoted(db, "H-20261001-001", {"AAA": 0.25}, date(2026, 10, 5))
    _promoted(db, "H-20261001-002", {"BBB": 0.25}, date(2026, 9, 20))
    r = rs.compute_research_targets(session=db, today=date(2026, 10, 6))
    assert r["new_orders_allowed"] is False and r["targets"] == {} and "H-20261001-002" in r["hold_reason"]


# ---------------------------------------------------------------- 계획 합성·게이트
def test_research_none_is_byte_identical_to_champion_only():
    positions = {}
    a = build_plan(CORE, SAT, positions, 10000.0)
    b = build_plan(CORE, SAT, positions, 10000.0, None)
    assert a == b and "research_new_orders_allowed" not in a


def test_empty_research_sleeve_keeps_champion_orders_same():
    base = build_plan(CORE, SAT, {}, 10000.0)
    r = build_plan(CORE, SAT, {}, 10000.0, {"targets": {}, "new_orders_allowed": True})
    assert r["orders"] == base["orders"]


def test_research_scales_champion_and_labels_new_symbols():
    r = build_plan(CORE, SAT, {}, 10000.0, {"targets": {"AAA": 0.05, "XLK": 0.02}, "new_orders_allowed": True})
    orders = {o["symbol"]: float(o["notional"]) for o in r["orders"]}
    assert orders["AAA"] == pytest.approx(500.0)
    assert orders["XLV"] == pytest.approx(0.2 * (1 - 0.07) * 10000)          # 챔피언 목표는 (1-7%)로 축소
    assert orders["XLK"] == pytest.approx((0.2 * 0.93 + 0.02) * 10000)       # 겹치는 종목은 합산
    assert r["sleeve_of"]["AAA"] == SLEEVE_RESEARCH and r["sleeve_of"]["XLK"] == "core"  # 겹치면 챔피언 라벨


def test_research_hold_blocks_only_research_buys():
    plan = build_plan(CORE, SAT, {}, 10000.0, {"targets": {"AAA": 0.05}, "new_orders_allowed": False, "hold_reason": "x"})
    assert not any(o["symbol"] == "AAA" for o in plan["orders"])            # 보류 슬리브는 계획에서 빠진다
    assert any(o["symbol"] == "XLV" for o in plan["orders"])


def test_gate_fails_closed_when_research_flag_missing():
    plan = build_order_plan({"AAA": 0.05}, {}, 10000.0, sleeve_of={"AAA": SLEEVE_RESEARCH},
                            research_new_orders_allowed=True)
    assert enforce_order_gate(plan)[0]
    tampered = {**plan}
    tampered.pop("research_new_orders_allowed")
    allowed, blocked = enforce_order_gate(tampered)
    assert not allowed and blocked[0]["symbol"] == "AAA"


# ---------------------------------------------------------------- shadow: 승격 가설 기록 지속, 미완성 봉 제외
def test_latest_trading_day_excludes_unfinished_bar():
    import pandas as pd
    from zoneinfo import ZoneInfo

    idx = pd.bdate_range("2026-10-01", "2026-10-06")
    df = pd.DataFrame({"Close": range(len(idx))}, index=idx)
    prov = lambda t, a, b: df  # noqa: E731
    et = ZoneInfo("America/New_York")
    assert sh.latest_trading_day(prov, now_et=datetime(2026, 10, 6, 11, 48, tzinfo=et)) == date(2026, 10, 5)
    assert sh.latest_trading_day(prov, now_et=datetime(2026, 10, 6, 17, 0, tzinfo=et)) == date(2026, 10, 6)


def test_candidate_message_has_buttons():
    b = sh.approval_buttons("H-20261005-001")
    assert [x["callback_data"] for x in b[0]] == ["h:promote:H-20261005-001", "h:retire:H-20261005-001"]
    assert all(len(x["callback_data"].encode()) <= 64 for x in b[0])       # 텔레그램 제한
