"""R&D 센터 주제 켜기/끄기·새틀라이트 진입/매도 규칙 확장·코어 분기 연구실 (2026-10-05)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from core import core_rnd as crd
from core import rnd_topics as rt
from core import satellite_lab as sl


@pytest.fixture()
def topics(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "STATE_PATH", tmp_path / "rnd_topics.json")
    return tmp_path


# ---------------------------------------------------------------- 주제 스위치
def test_topics_default_on_and_persist(topics):
    assert all(v["on"] for v in rt.all_states().values()) and len(rt.TOPICS) == 8
    rt.set_on("sat_entry", False, actor="test")
    assert rt.is_on("sat_entry") is False and rt.is_on("sat_exit") is True
    assert rt.enabled_sat_topics() == ["selection", "exit", "guru"]
    assert rt.sat_topic_on("entry") is False and rt.sat_topic_on(None) is True
    rt.set_on("sat_entry", True)
    assert rt.is_on("sat_entry") and len(json.loads((topics / "rnd_topics.json").read_text())["log"]) == 2
    with pytest.raises(KeyError):
        rt.set_on("nope", True)


# ---------------------------------------------------------------- 진입·매도 규칙
def _window():
    idx = pd.bdate_range("2021-01-04", periods=12)
    c = pd.Series([100, 99, 97, 101, 105, 110, 120, 125, 118, 112, 108, 109.0], index=idx)
    return pd.DataFrame({"A": c})


def test_entry_delay_and_pullback():
    w = _window()
    v, _ = sl._period_values(w, w, ["A"], 0.0, entry={"type": "delay", "days": 3})
    assert v["A"].iloc[:4].tolist() == [1, 1, 1, 1] and v["A"].iloc[-1] == pytest.approx(109 / 101)
    sma_closes = w.copy()
    v2, _ = sl._period_values(sma_closes, w, ["A"], 0.0, entry={"type": "pullback", "sma": 2, "max_wait": 5})
    assert v2["A"].iloc[-1] == pytest.approx(109 / 99)  # 첫날(1번째 거래일) 종가가 2일 평균 아래 → 99 에 진입


def test_exit_rules():
    w = _window()
    tp, held = sl._period_values(w, w, ["A"], 0.0, exit_rule={"type": "take_profit", "tp": 0.15})
    assert tp["A"].iloc[-1] == pytest.approx(1.20) and held == set()  # 120 도달일 종가에 팔고 고정
    ts, _ = sl._period_values(w, w, ["A"], 0.0, exit_rule={"type": "time_stop", "days": 4})
    assert ts["A"].iloc[-1] == pytest.approx(1.05)
    tb, _ = sl._period_values(w, w, ["A"], 0.0, exit_rule={"type": "trend_break", "sma": 3})
    assert tb["A"].iloc[-1] < 1.2 and tb["A"].iloc[-1] == tb["A"].iloc[-2]
    none, held2 = sl._period_values(w, w, ["A"], 0.0)
    assert none["A"].iloc[-1] == pytest.approx(1.09) and held2 == {"A"}


def test_spec_validation_for_entry_exit_topic():
    base = {"id": "S-20261006-001", "parent": None, "title": "t", "thesis": "t", "source": "s", "pool": {"type": "champion40"},
            "signal": {"params_grid": [{}]}, "portfolio": {"top_k": 3, "hold_months": 6}}
    ok = sl.validate_spec({**base, "topic": "exit", "exit": {"type": "time_stop", "days": 60}, "entry": {"type": "delay", "days": 5}})
    assert ok["exit"] == {"type": "time_stop", "days": 60} and ok["entry"]["days"] == 5
    with pytest.raises(sl.LabSpecError) as e:
        sl.validate_spec({**base, "topic": "timing", "exit": {"type": "take_profit", "tp": 5}, "entry": {"type": "pullback", "sma": 1}})
    assert "topic" in str(e.value) and "exit.tp" in str(e.value) and "entry.sma" in str(e.value)


def test_satellite_queue_waits_when_topic_off(topics, tmp_path):
    spec = {"id": "S-20261006-001", "parent": None, "title": "t", "thesis": "t", "source": "s", "pool": {"type": "champion40"},
            "signal": {"params_grid": [{}]}, "portfolio": {"top_k": 3, "hold_months": 6}, "topic": "entry",
            "entry": {"type": "delay", "days": 3}}
    sl.freeze(spec, "def score(prices, as_of, params):\n    return {}\n", "agent", state_dir=tmp_path / "s")
    reg = sl.load_registry(tmp_path / "s")
    assert [v["id"] for v in sl.queue(reg)] == ["S-20261006-001"]
    rt.set_on("sat_entry", False)
    assert sl.queue(reg) == []  # 기다릴 뿐 지우지 않는다
    rt.set_on("sat_entry", True)
    assert len(sl.queue(sl.load_registry(tmp_path / "s"))) == 1


# ---------------------------------------------------------------- 코어 분기 연구실
def _idea(**over):
    d = {"id": "Q-2026q4-01", "title": "5종목", "thesis": "더 넓게", "source": "core-rnd-v2", "topic": "selection",
         "config": {"top_n": 5}, "exit_rule": {"kind": "none"}, "neighbors": [{"config": {"top_n": 6}}]}
    d.update(over)
    return d


def test_core_idea_validation_and_trials(tmp_path):
    with pytest.raises(crd.CoreIdeaError) as e:
        crd.validate_idea(_idea(id="Q-1", config={"top_n": 9, "leverage": 2}, exit_rule={"kind": "trail", "p": 0.9, "freq": "x"}))
    msg = str(e.value)
    assert "id" in msg and "top_n" in msg and "leverage" in msg and "exit_rule.p" in msg and "exit_rule.freq" in msg
    with pytest.raises(crd.CoreIdeaError, match="달라야"):
        crd.validate_idea(_idea(config={}, exit_rule={"kind": "none"}))
    crd.freeze(_idea(), state_dir=tmp_path)
    crd.freeze(_idea(), state_dir=tmp_path)  # 같은 id 재동결은 무시
    assert crd.load_registry(tmp_path)["cumulative_trials"] == crd.PRIOR_CORE_TRIALS + 1
    cfg = crd.build_config({"top_n": 5, "lookbacks": [126, 252]})
    assert cfg.top_n == 5 and cfg.lookbacks == (126, 252) and cfg.cash == "bil"


def test_core_sync_and_has_work_follows_topic(topics, tmp_path):
    d = tmp_path / "ideas" / "2026q4"
    d.mkdir(parents=True)
    (d / "Q-2026q4-01.json").write_text(json.dumps(_idea()), encoding="utf-8")
    (d / "Q-2026q4-02.json").write_text(json.dumps(_idea(id="Q-2026q4-02", title="")), encoding="utf-8")
    out = crd.sync_ideas("2026q4", ideas_dir=tmp_path / "ideas", state_dir=tmp_path / "st")
    assert out["frozen"] == ["Q-2026q4-01"] and "title" in out["errors"]["Q-2026q4-02"]
    assert crd.has_work(tmp_path / "st")
    rt.set_on("core_quarterly", False)
    assert not crd.has_work(tmp_path / "st")
    assert crd.quarter_of(datetime(2026, 11, 2).date()) == "2026q4"


def test_core_worker_smoke(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    p = subprocess.run([sys.executable, str(root / "scripts/core_lab_worker.py"), "--smoke", "--out", str(tmp_path / "o"),
                        "--checkpoint", str(tmp_path / "c")], cwd=root, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    reg = crd.load_registry(tmp_path / "c" / "smoke_state")
    assert reg["ideas"]["Q-2026q4-01"]["status"] in ("pass", "fail")


# ---------------------------------------------------------------- 야간 배치
def test_sat_plan_rotates_topics_and_pauses_off(topics, tmp_path, monkeypatch):
    from core import agent_batch as ab
    from core import agent_budget as budget

    monkeypatch.setattr(ab, "SAT_WS", tmp_path / "variants")
    monkeypatch.setattr(sl, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(budget, "can_launch", lambda role, now=None, path=None: (True, "ok"))
    now = datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)
    role, sid, extra = ab.sat_plan(now, set())
    assert role == "sat_designer" and extra["topic"] == "selection"
    (ab.SAT_WS / sid).mkdir(parents=True)
    sl.save_agent_state(sid, {"rounds": 1, "topic": "selection"})
    _, _, extra2 = ab.sat_plan(now, {("sat_designer", "new"), ("sat_designer", sid)}) or (None, None, {})
    rt.set_on("sat_selection", False)
    rt.set_on("sat_entry", False)
    res = ab.sat_plan(now, {("sat_designer", sid)})
    assert res[2]["topic"] == "exit"  # 켜진 주제만, 가장 적게 한 주제
    rt.set_on("sat_exit", False)
    rt.set_on("sat_guru", False)
    assert ab.sat_plan(now, {("sat_designer", sid)}) is None  # 모두 꺼지면 새 아이디어 없음
    assert "언제 팔지" in ab.prompt_for("sat_designer", "S-20261007-001", now, {"new": True, "topic": "exit"})


def test_core_plan_batch_waits_for_judge_then_moves_to_next_batch(topics, tmp_path, monkeypatch):
    """2026-10-10 재설계: 분기당 1회 한도가 아니라 세대(배치 N개)가 전부 심판될 때마다 다음 배치를 쓴다."""
    from core import agent_batch as ab
    from core import agent_budget as budget

    monkeypatch.setattr(ab, "CORE_IDEAS_DIR", tmp_path / "ideas")
    monkeypatch.setattr(ab, "CORE_STATE_DIR", tmp_path / "st")
    monkeypatch.setattr(budget, "can_launch", lambda role, now=None, path=None: (True, "ok"))
    now = datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)

    task = ab.core_plan(now, set())
    assert task[0] == "core_designer" and task[1] == "2026q4"
    assert task[2]["new"] is True and task[2]["feedback"] is None
    batch1 = task[2]["ids"]
    assert batch1 == ["Q-2026q4-01", "Q-2026q4-02", "Q-2026q4-03"]
    # run_batch 의 실행 후처리가 하는 일(배치 id 기록)을 여기선 직접 흉내낸다 — core_plan 자체는 계획만 한다.
    crd.save_agent_state("2026q4", {"pending_ids": batch1, "batch_attempts": 0}, state_dir=ab.CORE_STATE_DIR)

    d = tmp_path / "ideas" / "2026q4"
    d.mkdir(parents=True)
    (d / f"{batch1[0]}.json").write_text(json.dumps(_idea(id=batch1[0])), encoding="utf-8")
    # core_plan 이 호출될 때 이 파일을 동결(=심판 대기 큐에 등록)한다 — 아직 심판 전이라 다음 배치는 안 나온다.
    assert ab.core_plan(now, set()) is None
    st = crd.agent_state("2026q4", state_dir=ab.CORE_STATE_DIR)
    assert st["pending_ids"] == batch1
    reg_ = crd.load_registry(ab.CORE_STATE_DIR)
    assert reg_["ideas"][batch1[0]]["status"] == crd.STATUS_QUEUED

    # 심판이 끝났다고 가정(코드가 처리하는 부분, 여기선 registry 를 직접 갈아끼운다) — 다음 배치로 넘어가야 한다.
    with crd.edit_registry(ab.CORE_STATE_DIR) as reg2:
        reg2["ideas"][batch1[0]]["status"] = crd.STATUS_FAIL
    task2 = ab.core_plan(now, set())
    assert task2[2]["new"] is True
    batch2 = task2[2]["ids"]
    assert batch2 == ["Q-2026q4-04", "Q-2026q4-05", "Q-2026q4-06"]  # 직전 배치 id와 안 겹침

    rt.set_on("core_quarterly", False)
    assert ab.core_plan(datetime(2027, 1, 5, 19, 0, tzinfo=timezone.utc), set()) is None
    assert "core_designer" in budget.ROLES and ab.tools_for("core_designer", "2026q4")[-1] == "Edit(research/core_lab/ideas/2026q4/**)"


def test_hub_topics_section_has_toggle_forms(topics):
    from hub import satellite_lab_page as page

    html_out = page.render_topics({"topics": rt.all_states()})
    assert html_out.count('action="/rnd/topics"') == len(rt.TOPICS)
    assert "ON" in html_out and "OFF" in html_out and "aria-label=" in html_out
    assert ">끄기</button>" not in html_out and ">켜기</button>" not in html_out


def test_hub_leaderboard_renders_fail_reasons_inline_and_readably():
    from hub import satellite_lab_page as page

    row = {"id": "S-1", "title": "후보", "origin": "seed", "status": "fail", "gates_passed": 1,
           "n_gates": 5, "active_is_sharpe": 0.2, "random_pct": 0.4, "dsr": 0.3,
           "is_sharpe": 1.1, "oos_sharpe": -0.2, "structure": "momentum", "best_params": {},
           "latest_picks": {}, "reasons": ["무작위 관문 미달", "마지막 2년 초과 성과 없음", "파라미터 강건성 부족"]}
    html_out = page.render_body({"rows": [row], "registry": {"variants": {}, "cumulative_trials": 1},
                                 "judge_version": "test", "topics": {}, "research_jobs": []})
    assert 'class="sat-fail-reasons" style="min-width:280px;white-space:normal' in html_out
    assert "무작위 관문 미달" in html_out and "마지막 2년 초과 성과 없음" in html_out
    assert "<br>마지막 2년" not in html_out and "sat-fail-reasons" in html_out
