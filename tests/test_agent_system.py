"""에이전트 층(예산·배치)·shadow·심판 통과 경로·허브 화면 — 네트워크·Claude 없이 가짜 러너로 검증."""

import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import agent_batch as ab
from core import agent_budget as bud
from core import hypothesis_judge as hj
from core import hypothesis_registry as reg
from core import hypothesis_shadow as sh
from core import hypothesis_spec as hs
from core import models

MON_0310 = datetime(2026, 10, 4, 18, 10, tzinfo=timezone.utc)  # = 2026-10-05(월) 03:10 KST


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    import core.db as cdb

    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    models.Base.metadata.create_all(eng)
    monkeypatch.setattr(cdb, "SessionLocal", sessionmaker(bind=eng))
    monkeypatch.setattr(cdb, "init_db", lambda: None)
    return eng


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    root = tmp_path / "research"
    for name, val in {"RESEARCH": root, "WS": root / "hypotheses", "SCOUT_DIR": root / "scout",
                      "FAILURES": root / "failures.md", "CONTEXT": root / "context.md"}.items():
        monkeypatch.setattr(ab, name, val)
    monkeypatch.setattr(bud, "USAGE_LOG", tmp_path / "usage.jsonl")
    return root


# ---------------------------------------------------------------- 예산
def test_budget_window_weekday_and_caps(ws):
    assert bud.can_launch("scout", MON_0310)[0]
    assert bud.can_launch("writer", MON_0310)[0]                                  # 월요일
    assert not bud.can_launch("writer", MON_0310 + timedelta(days=1))[0]          # 화요일
    assert "시간" in bud.can_launch("scout", MON_0310 + timedelta(hours=3))[1]    # 06:10 KST
    for _ in range(3):
        bud.record({"at": bud.kst(MON_0310).isoformat(), "role": "writer", "cost_usd": 4.0})
    assert bud.can_launch("critic", MON_0310)[0]                                  # 12 + 1.5 ≤ 15
    assert "하룻밤" in bud.can_launch("writer", MON_0310)[1] or "주간 3회" in bud.can_launch("writer", MON_0310)[1]
    bud.record({"at": bud.kst(MON_0310).isoformat(), "role": "critic", "cost_usd": 2.0})
    assert "하룻밤" in bud.can_launch("critic", MON_0310)[1]                      # 14 + 1.5 > 15


# ---------------------------------------------------------------- 배치 전체 흐름(가짜 에이전트)
SIGNAL = "def score(prices, as_of, params):\n    return {t: 1.0 for t in prices}\n"
TEST = ("from pathlib import Path\nimport importlib.util\n"
        "def test_ok():\n    spec = importlib.util.spec_from_file_location('s', Path(__file__).with_name('signal.py'))\n"
        "    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "    assert m.score({'A': None}, None, {}) == {'A': 1.0}\n")


def _fake_runner(ws, critic_verdict="approve", calls=None):
    def run(role, prompt, tools, cfg, timeout):
        calls.append((role, prompt))
        if role == "scout":
            (ws / "scout").mkdir(parents=True, exist_ok=True)
            (ws / "scout" / "seed.md").write_text("seed")
        elif role == "writer":
            hid = prompt.split("이 id 만 쓴다: ")[1].split(",")[0].split(".")[0].strip()
            d = ws / "hypotheses" / hid
            d.mkdir(parents=True, exist_ok=True)
            spec = {"id": hid, "source": "scout", "thesis": "t", "universe": {"type": "list", "tickers": ["A"]},
                    "signal": {"params_grid": [{}]}, "portfolio": {"top_k": 1, "rebalance": "monthly", "max_weight": 0.2},
                    "period": {"start": "2015-01-01"}, "kill_criteria": {"min_rebalances": 12, "max_drawdown": 0.5}}
            (d / "spec.json").write_text(json.dumps(spec))
        elif role == "implementer":
            hid = prompt.split()[1].rstrip(":")
            (ws / "hypotheses" / hid / "signal.py").write_text(SIGNAL)
            (ws / "hypotheses" / hid / "test_signal.py").write_text(TEST)
        elif role == "critic":
            hid = prompt.split()[1].rstrip(":")
            (ws / "hypotheses" / hid / "critic.json").write_text(json.dumps({"verdict": critic_verdict, "issues": []}))
        return {"ok": True, "limited": False, "cost_usd": 0.5, "turns": 3, "duration_s": 1.0}
    return run


def test_full_cycle_one_night_writer_to_judge(tmpdb, ws):
    calls, judged = [], []

    def fake_judge(hid):
        judged.append(hid)
        reg.transition(hid, reg.FAIL, "fake", judge={"verdict": "fail", "reasons": ["DSR 낮음"], "trial_srs": [0.01]})
        return {"status": "fail", "judge": {"reasons": ["DSR 낮음"]}}

    res = ab.run_batch(now_fn=lambda: MON_0310, runner=_fake_runner(ws, calls=calls), judge_fn=fake_judge)
    roles = [c[0] for c in calls]
    assert roles[:4] == ["scout", "writer", "implementer", "critic"]
    hid = judged[0]
    assert hid.startswith("H-20261005-")
    h = reg.get(hid)
    assert h["status"] == reg.FAIL and h["signal_code"] == SIGNAL and h["n_trials"] == 1
    assert reg.funnel()["cumulative_trials"] == 1
    assert any(x.startswith("동결") for x in res["log"]) and any(x.startswith("심판") for x in res["log"])
    assert len(bud.read_usage()) == len(calls) and res["budget"]["night_cost"] == pytest.approx(0.5 * len(calls))
    assert (ws / "context.md").exists()


def test_critic_reject_loops_to_implementer_then_abandons(tmpdb, ws):
    calls = []
    ab.run_batch(now_fn=lambda: MON_0310, runner=_fake_runner(ws, "reject", calls), judge_fn=lambda h: {})
    hid = next(h["id"] for h in reg.list_by_status())
    # 한 밤에 (implementer, hid)·(critic, hid)는 한 번씩만 → 아직 draft
    assert reg.get(hid)["status"] == reg.DRAFT
    st = json.loads((ws / "hypotheses" / hid / "state.json").read_text())
    assert st["impl_rounds"] == 1 and st["test_ok"] is True
    st["impl_rounds"] = ab.MAX_IMPL_ROUNDS
    (ws / "hypotheses" / hid / "state.json").write_text(json.dumps(st))
    ab.housekeeping(MON_0310, set(), [], lambda h: {})
    assert reg.get(hid)["status"] == reg.ABANDONED


def test_invalid_spec_is_rejected_not_registered(tmpdb, ws):
    d = ws / "hypotheses" / "H-20261005-009"
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps({"id": "H-20261005-009"}))
    log = []
    ab.housekeeping(MON_0310, set(), log, lambda h: {})
    assert reg.get("H-20261005-009") is None
    assert "invalid" in json.loads((d / "state.json").read_text()) and log[0].startswith("스펙 거부")


def test_usage_limit_stops_batch(tmpdb, ws):
    calls = []
    def limited(role, *a):
        calls.append(role)
        return {"ok": False, "limited": True}
    res = ab.run_batch(now_fn=lambda: MON_0310, runner=limited, judge_fn=lambda h: {})
    assert calls == ["scout"] and res["stop_reason"] == "usage limit"


def test_guard_reverts_writes_outside_research(tmpdb, ws):
    from core.agent_batch import PROJECT_ROOT

    stray = PROJECT_ROOT / "zz_agent_violation_test.txt"
    before = ab._porcelain()
    stray.write_text("x")
    try:
        assert "zz_agent_violation_test.txt" in ab._guard(before)
        assert not stray.exists()
    finally:
        stray.unlink(missing_ok=True)


def test_child_env_drops_broker_and_telegram_secrets(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "x")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "keep")
    env = ab._child_env()
    assert "ALPACA_PAPER_API_SECRET" not in env and "TELEGRAM_BOT_TOKEN" not in env
    assert env["ANTHROPIC_API_KEY"] == "keep"


def test_tools_are_scoped_per_role():
    assert "Write(research/hypotheses/H-1/**)" in ab.tools_for("implementer", "H-1")
    assert not any(t.startswith(("Write", "Edit")) and "critic.json" not in t for t in ab.tools_for("critic", "H-1"))
    assert not any("Bash" in t for t in ab.tools_for("writer"))


# ---------------------------------------------------------------- 좋은 전략은 통과, shadow
def _px(values, start):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({"Open": values, "High": values, "Low": values, "Close": values}, index=idx)


def _world(n=1500, seed=1):
    rng = np.random.default_rng(seed)
    spy = 100 * np.cumprod(1 + rng.normal(0.0002, 0.012, n))
    good = 100 * np.cumprod(1 + rng.normal(0.0012, 0.006, n))  # 시장과 독립, 높은 샤프
    return {"SPY": _px(list(spy), "2015-01-01"), "GOOD": _px(list(good), "2015-01-01")}


GOOD_SPEC = {"id": "H-20261005-100", "source": "test", "thesis": "GOOD 보유",
             "universe": {"type": "list", "tickers": ["GOOD"]}, "signal": {"params_grid": [{}]},
             "portfolio": {"top_k": 1, "rebalance": "monthly", "max_weight": 0.25},
             "period": {"start": "2016-01-01", "end": "2020-12-31"}, "kill_criteria": {"min_rebalances": 12, "max_drawdown": 0.5}}


def test_genuinely_good_strategy_passes_judge_and_shadows(tmpdb):
    world = _world()
    provider = lambda t, a, b: world[t]  # noqa: E731
    reg.register_draft(GOOD_SPEC)
    reg.freeze(GOOD_SPEC["id"], SIGNAL)
    out = hj.judge_frozen(GOOD_SPEC["id"], price_provider=provider, champion_corr_fn=None)
    assert out["status"] == "pass", out.get("judge", {}).get("reasons")
    j = out["judge"]
    assert j["dsr"] >= 0.95 and abs(j["corr_spy"]) < 0.3

    last = world["SPY"].index[-1].date()
    r1 = sh.run_daily(price_provider=provider, today=last - timedelta(days=40))
    assert GOOD_SPEC["id"] in r1["promoted_to_shadow"] and r1["recorded"][0]["rebalanced"] is True
    r2 = sh.run_daily(price_provider=provider, today=last)
    rec = r2["recorded"][0]
    assert rec["status"] == "recorded" and rec["days"] > 20 and rec["realized"] > 0
    assert sh.run_daily(price_provider=provider, today=last)["recorded"][0]["status"] == "already_recorded"


def test_forward_verdict_z_rule(tmpdb):
    from core.db import get_session
    from core.models import HypothesisShadowRecord

    hyp = {"id": "H-X", "judge": {"stats": {"mean_daily": 0.001, "sd_daily": 0.01}}}
    with get_session() as db:
        db.add(HypothesisShadowRecord(hypothesis_id="H-X", as_of=date(2026, 1, 2), realized_return=0.01,
                                      weights_json=json.dumps({"w": {}, "days": 59})))
        db.flush()
        assert sh.forward_verdict(hyp, session=db) is None                   # 59일 < 60
        db.add(HypothesisShadowRecord(hypothesis_id="H-X", as_of=date(2026, 1, 3), realized_return=-0.30,
                                      weights_json=json.dumps({"w": {}, "days": 1})))
        db.flush()
        v = sh.forward_verdict(hyp, session=db)
        assert v["n_days"] == 60 and v["verdict"] == "retire" and v["z"] < -1.96


# ---------------------------------------------------------------- 허브
def test_research_page_renders_with_data(tmpdb, ws):
    from hub import research_status, server

    reg.register_draft(GOOD_SPEC)
    data = research_status.collect()
    body = research_status.render_body(data)
    assert "누적 시도 수 N" in body and "초안" in body and "writer" in body
    assert "누적 시도 0" in research_status.card_badge(data)
    assert "AI 에이전트 연구" in server.render_research_page()
