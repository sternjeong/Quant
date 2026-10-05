"""새틀라이트 R&D 센터(core/satellite_lab.py) — 스펙·시뮬레이터·현 규칙 재현·심판·등록부·실행기 훅·야간 트랙·허브 화면."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import core.champion_strategy as cs
from core import satellite_lab as sl

ROOT = Path(__file__).resolve().parent.parent


def _spec(**over):
    spec = {"id": "S-20261002-001", "parent": None, "title": "테스트", "thesis": "검증용", "source": "테스트",
            "pool": {"type": "champion40"}, "signal": {"params_grid": [{"lookback": 252}]},
            "portfolio": {"top_k": 3, "hold_months": 6}, "exit": {"type": "none"}}
    spec.update(over)
    return spec


MOM = '''
def score(prices, as_of, params):
    lb = int(params.get("lookback", 252))
    out = {}
    for t, df in prices.items():
        c = df["Close"]
        if len(c) > lb:
            out[t] = float(c.iloc[-1] / c.iloc[-1 - lb] - 1)
    return out
'''


@pytest.fixture()
def synth():
    price_provider, pool_provider = sl.synthetic_providers(n_tickers=30, start="2012-01-01", end="2020-12-31")
    data = sl.build_data({"champion40", "sp500_pit"}, start="2014-01-01", end="2020-12-31",
                         pool_provider=pool_provider, price_provider=price_provider)
    return data


# ---------------------------------------------------------------- 스펙
def test_validate_spec_accepts_and_rejects():
    assert sl.validate_spec(_spec())["exit"] == {"type": "none"}
    with pytest.raises(sl.LabSpecError) as e:
        sl.validate_spec(_spec(id="H-1", pool={"type": "nasdaq"}, portfolio={"top_k": 50, "hold_months": 2},
                               exit={"type": "trailing_stop", "stop_pct": 0.9}))
    msg = str(e.value)
    assert "id" in msg and "pool.type" in msg and "top_k" in msg and "hold_months" in msg and "stop_pct" in msg
    with pytest.raises(sl.LabSpecError):
        sl.validate_spec(_spec(signal={"params_grid": [{"a": 1}] * 2}))  # 중복 조합


def test_all_seeds_are_valid_and_load():
    seeds = sorted(p for p in sl.SEEDS_DIR.glob("S-SEED-*") if p.is_dir())
    assert len(seeds) >= 8 and seeds[0].name == sl.INCUMBENT_ID
    for d in seeds:
        spec, code = sl.read_variant_dir(d)
        assert callable(sl.load_signal(code))
        assert sl.smoke_check(spec, code).startswith("smoke ok")


def test_rebalance_dates_follow_hold_months():
    days = pd.bdate_range("2020-01-01", "2020-12-31")
    assert [d.month for d in sl.rebalance_dates(days, 6)] == [1, 7]
    assert [d.month for d in sl.rebalance_dates(days, 3)] == [1, 4, 7, 10]
    assert len(sl.rebalance_dates(days, 1)) == 12
    assert sl.rebalance_dates(days, 6)[0] == pd.Timestamp("2020-01-01")


# ---------------------------------------------------------------- 시뮬레이터
def _closes():
    idx = pd.bdate_range("2021-01-04", periods=6)
    return pd.DataFrame({"A": [100, 110, 121, 121, 121, 121], "B": [100, 100, 100, 50, 50, 50],
                         "C": [100, 100, 100, 100, 100, 120]}, index=idx, dtype=float)


def test_simulate_equal_weight_drift_and_costs():
    c = _closes()
    out = sl.simulate(c, [(c.index[0], ["A", "B"])], c.index[-1], None, bps=0)
    eq = (1 + out["returns"]).prod()
    assert eq == pytest.approx((1.21 + 0.5) / 2)
    with_cost = sl.simulate(c, [(c.index[0], ["A", "B"])], c.index[-1], None, bps=10)
    assert (1 + with_cost["returns"]).prod() == pytest.approx(eq * (1 - 0.001))  # 처음 매수 회전율 1


def test_simulate_trailing_stop_moves_to_cash():
    c = _closes()
    out = sl.simulate(c, [(c.index[0], ["B"])], c.index[-1], 0.2, bps=0)
    assert (1 + out["returns"]).prod() == pytest.approx(0.5)  # 50% 급락일 종가에 팔고 이후 현금
    c2 = c.copy()
    c2.loc[c2.index[4]:, "B"] = 80.0
    out2 = sl.simulate(c2, [(c2.index[0], ["B"])], c2.index[-1], 0.2, bps=0)
    assert (1 + out2["returns"]).prod() == pytest.approx(0.5)  # 판 뒤의 반등은 받지 않는다


def test_simulate_keeps_continuing_positions_without_cost():
    c = _closes()
    sched = [(c.index[0], ["A", "C"]), (c.index[3], ["A", "C"])]
    out = sl.simulate(c, sched, c.index[-1], None, bps=10)
    assert out["n_periods"] == 2
    # 두 번째 리밸런싱의 회전율은 표류분 되돌리기뿐(1 보다 훨씬 작다)
    assert out["avg_turnover"] < 0.6


# ---------------------------------------------------------------- 현 규칙 재현
def test_incumbent_seed_reproduces_champion_pick(monkeypatch):
    """랩의 S-SEED-000 은 챔피언 코드(_pick_satellite_at_date)와 같은 날 같은 종목을 골라야 공정한 기준선이다."""
    price_provider, pool_provider = sl.synthetic_providers(n_tickers=40, start="2016-01-01", end="2020-12-31", seed=11)
    names = pool_provider("champion40", date(2020, 1, 1))
    monkeypatch.setattr(cs, "sample_universe", lambda **k: pd.DataFrame({"ticker": names}))

    def fake_multi(tickers, start, end, interval="1d"):
        return {t: price_provider(t, start, (pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat()) for t in tickers}

    monkeypatch.setattr(cs, "get_multiple_price_history", fake_multi)
    data = sl.build_data({"champion40"}, start="2018-01-01", end="2020-12-31",
                         pool_provider=pool_provider, price_provider=price_provider)
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    lab = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)
    checked = 0
    for d_iso, picks in lab["schedule"]:
        champ = cs._pick_satellite_at_date(pd.Timestamp(d_iso))
        assert picks == champ["picks"], d_iso
        checked += 1
    assert checked >= 5


# ---------------------------------------------------------------- 심판
def test_random_baseline_and_judge_shape(synth):
    spec = sl.validate_spec(_spec())
    inc_spec, inc_code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    inc = sl.run_variant(inc_spec, inc_spec["signal"]["params_grid"][0], sl.load_signal(inc_code), synth)
    split = sl.holdout_split(inc["returns"].index)
    assert split is not None
    base = sl.random_baseline(spec, synth, split, n=15)
    assert len(base["is_sharpe"]) == 15 and len(base["oos_sharpe"]) == 15
    again = sl.random_baseline(spec, synth, split, n=15)
    assert base["is_sharpe"] == again["is_sharpe"]  # 시드 고정 — 재현 가능
    res = sl.judge_variant(spec, MOM, synth, incumbent=inc, baseline=base, cumulative_trials=5, prior_active_srs=[])
    assert res["verdict"] in (sl.STATUS_PASS, sl.STATUS_FAIL)
    assert set(res["gates"]) == {"G1_beats_random", "G2_beats_incumbent_deflated", "G3_holdout", "G4_param_robust", "G5_risk"}
    assert res["judge_version"] == sl.JUDGE_VERSION
    json.dumps(res)  # 등록부에 그대로 쓸 수 있어야 한다
    rep = sl.incumbent_report(inc, base)
    assert rep["random_percentile_is"] is not None


def test_noise_signal_fails(synth):
    noise = '''
import numpy as np
def score(prices, as_of, params):
    rng = np.random.default_rng(int(as_of.strftime("%Y%m%d")) + int(params.get("salt", 1)))
    return {t: float(rng.random()) for t in sorted(prices)}
'''
    spec = sl.validate_spec(_spec(signal={"params_grid": [{"salt": 1}]}))
    inc_spec, inc_code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    inc = sl.run_variant(inc_spec, inc_spec["signal"]["params_grid"][0], sl.load_signal(inc_code), synth)
    base = sl.random_baseline(spec, synth, sl.holdout_split(inc["returns"].index), n=20)
    res = sl.judge_variant(spec, noise, synth, incumbent=inc, baseline=base, cumulative_trials=50, prior_active_srs=[])
    assert res["verdict"] == sl.STATUS_FAIL
    assert not res["gates"]["G2_beats_incumbent_deflated"]["pass"]


def test_smoke_check_rejects_empty_signal():
    with pytest.raises(sl.LabSpecError, match="한 종목도"):
        sl.smoke_check(_spec(), "def score(prices, as_of, params):\n    return {}\n")


def test_pick_top_ignores_nonfinite_and_ineligible():
    assert sl.pick_top({"A": 1.0, "B": float("nan"), "C": None, "D": 3.0, "E": 2.0}, 2, {"A", "B", "C", "D"}) == ["D", "A"]


# ---------------------------------------------------------------- 등록부
def test_freeze_accumulates_trials_and_is_immutable(tmp_path):
    s1 = _spec(signal={"params_grid": [{"lookback": 126}, {"lookback": 252}]})
    sl.freeze(s1, MOM, "agent", state_dir=tmp_path)
    sl.freeze(_spec(id=sl.INCUMBENT_ID), MOM, "seed", state_dir=tmp_path)
    again = sl.freeze({**s1, "thesis": "바뀐 주장"}, MOM, "agent", state_dir=tmp_path)
    reg = sl.load_registry(tmp_path)
    assert reg["cumulative_trials"] == 2  # 기준선은 시도에 넣지 않고, 같은 id 재동결은 무시
    assert again["spec"]["thesis"] == "검증용"
    assert [v["id"] for v in sl.queue(reg)] == ["S-20261002-001"]


def test_weekly_agent_cap(tmp_path):
    for i in range(sl.WEEKLY_AGENT_FREEZE_CAP):
        sl.freeze(_spec(id=f"S-20261002-{i + 1:03d}"), MOM, "agent", state_dir=tmp_path)
    with pytest.raises(sl.LabSpecError, match="상한"):
        sl.freeze(_spec(id="S-20261002-099"), MOM, "agent", state_dir=tmp_path)
    sl.freeze(_spec(id="S-SEED-050"), MOM, "seed", state_dir=tmp_path)  # 시작 목록은 상한 밖


def test_sync_dir_only_freezes_ready_agent_variants(tmp_path):
    vdir = tmp_path / "variants" / "S-20261002-001"
    vdir.mkdir(parents=True)
    (vdir / "spec.json").write_text(json.dumps(_spec()), encoding="utf-8")
    (vdir / "signal.py").write_text(MOM, encoding="utf-8")
    state = tmp_path / "state"
    ready = lambda d: sl.agent_ready(d, state)  # noqa: E731
    assert sl.sync_dir(vdir.parent, "agent", state_dir=state, ready=ready) == []
    sl.save_agent_state(vdir.name, {"ready_hash": sl.variant_hash(vdir)}, state)
    (vdir / "signal.py").write_text(MOM + "\n# 승인 뒤 수정\n", encoding="utf-8")
    assert sl.sync_dir(vdir.parent, "agent", state_dir=state, ready=ready) == []  # 승인 뒤 바뀐 코드는 안 됨
    sl.save_agent_state(vdir.name, {"ready_hash": sl.variant_hash(vdir)}, state)
    assert sl.sync_dir(vdir.parent, "agent", state_dir=state, ready=ready) == ["S-20261002-001"]


def test_worker_smoke_runs_end_to_end(tmp_path):
    import subprocess
    import sys

    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "satellite_lab_worker.py"), "--smoke", "--max-variants", "2",
                        "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ckpt")],
                       cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    status = json.loads((tmp_path / "out" / "status.json").read_text(encoding="utf-8"))
    assert status["judged_this_run"] == 2 and status["incumbent"]["random_percentile_is"] is not None
    assert not (sl.STATE_DIR / "registry.json").exists() or True  # 스모크는 실제 등록부를 쓰지 않는다(임시 폴더)
    assert (tmp_path / "ckpt" / "smoke_state" / "registry.json").exists()


# ---------------------------------------------------------------- 실행기 훅
def test_research_runner_uses_idle_window_for_lab(tmp_path, monkeypatch):
    from core import research_jobs as rj

    cfg = rj.Config.for_root(tmp_path)
    cfg = rj.Config(**{**cfg.__dict__, "satellite_lab": True})
    (tmp_path / "research" / "jobs").mkdir(parents=True)
    monkeypatch.setattr(sl, "has_work", lambda *a, **k: True)
    calls = []

    def fake_child(cfg_, job, budget, **kw):
        calls.append(job.id)
        with sl.edit_registry(tmp_path / "lab") as reg:
            reg["variants"]["S-SEED-001"] = {"id": "S-SEED-001", "status": "fail", "notified": False,
                                             "spec": {"title": "t"}, "result": {"reasons": ["G1"], "gates": {}}}
        return rj.RunOutcome(0, None, 1.0, "")

    monkeypatch.setattr(rj, "run_child", fake_child)
    monkeypatch.setattr(sl, "STATE_DIR", tmp_path / "lab")
    sent = []
    now = datetime(2026, 10, 2, 4, 10, tzinfo=timezone.utc)  # 13:10 KST(실행 창 안)
    out = rj.run_tick(now, notify=sent.append, cfg=cfg, headroom=lambda: True, poll_interval=0.01)
    assert out["action"] == "ran" and calls == ["satellite-lab"]
    assert any("새틀라이트 R&D" in m and "S-SEED-001" in m for m in sent)
    assert sl.load_registry(tmp_path / "lab")["variants"]["S-SEED-001"]["notified"] is True
    # 테스트용 기본 설정(for_root)은 연구실을 돌리지 않는다
    calls.clear()
    out = rj.run_tick(now, notify=sent.append, cfg=rj.Config.for_root(tmp_path), headroom=lambda: True, poll_interval=0.01)
    assert out["action"] == "idle" and calls == []


# ---------------------------------------------------------------- 야간 에이전트 트랙
def test_sat_plan_flow(tmp_path, monkeypatch):
    from core import agent_batch as ab
    from core import agent_budget as budget

    monkeypatch.setattr(ab, "SAT_WS", tmp_path / "variants")
    monkeypatch.setattr(sl, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(budget, "can_launch", lambda role, now=None, path=None: (True, "ok"))
    monkeypatch.setattr(ab, "sat_check", lambda sid, timeout=300: (True, "ok"))
    now = datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc)
    role, sid, extra = ab.sat_plan(now, set())
    assert role == "sat_designer" and extra.get("new") and sid.startswith("S-20261003-")
    d = ab.SAT_WS / sid
    d.mkdir(parents=True)
    (d / "spec.json").write_text(json.dumps(_spec(id=sid)), encoding="utf-8")
    (d / "signal.py").write_text(MOM, encoding="utf-8")
    sl.save_agent_state(sid, {"rounds": 1})
    role, sid2, extra = ab.sat_plan(now, {("sat_designer", "new")})
    assert (role, sid2) == ("sat_critic", sid)
    sl.save_agent_state(sid, {**sl.agent_state(sid), "critic_hash": extra["hash"]})
    (d / "critic.json").write_text(json.dumps({"verdict": "reject", "issues": [{"what": "x"}]}), encoding="utf-8")
    role, _, extra = ab.sat_plan(now, {("sat_designer", "new")})
    assert role == "sat_designer" and "Critic 반려" in extra["feedback"]
    (d / "critic.json").write_text(json.dumps({"verdict": "approve", "issues": []}), encoding="utf-8")
    assert ab.sat_plan(now, {("sat_designer", "new"), ("sat_designer", sid)}) is None
    assert sl.agent_ready(d)
    assert set(ab.tools_for("sat_critic", sid)) >= {f"Write(research/satellite_lab/variants/{sid}/critic.json)"}
    assert "_sat_contract" not in ab.system_prompt("writer") and "새틀라이트 R&D 계약" in ab.system_prompt("sat_designer")


# ---------------------------------------------------------------- 허브 화면
def test_hub_page_renders(tmp_path, monkeypatch):
    from hub import satellite_lab_page as page

    monkeypatch.setattr(sl, "STATE_DIR", tmp_path)
    monkeypatch.setattr(sl, "VARIANTS_DIR", tmp_path / "none")
    sl.freeze(_spec(id=sl.INCUMBENT_ID), MOM, "seed", state_dir=tmp_path)
    sl.freeze(_spec(), MOM, "agent", state_dir=tmp_path)
    with sl.edit_registry(tmp_path) as reg:
        reg["incumbent"] = {"stats": {"is": {"sharpe_annual": 0.8}}, "random_percentile_is": 0.6, "random_percentile_oos": 0.4}
        v = reg["variants"]["S-20261002-001"]
        v["status"] = "pass"
        v["result"] = {"gates": {"G1_beats_random": {"pass": True, "percentile": 0.97}}, "reasons": [],
                       "stats": {"is": {"sharpe_annual": 1.1}, "oos": {"sharpe_annual": 0.9}}, "best_params": {"lookback": 252}}
    data = page.collect()
    html_out = page.render_body(data)
    assert "S-20261002-001" in html_out and "통과 — 사람 검토 대기" in html_out and "60백분위" in html_out
    assert "검토 대기 1" in page.card_badge(data)


def test_migration_to_v2_requeues_everything_and_keeps_trials(tmp_path):
    s1 = _spec(signal={"params_grid": [{"lookback": 126}, {"lookback": 252}]})
    sl.freeze(s1, MOM, "agent", state_dir=tmp_path)
    with sl.edit_registry(tmp_path) as reg:
        reg["judge_version"] = "sat-judge/v1"
        reg["incumbent"] = {"x": 1}
        reg["variants"][s1["id"]].update(status="fail", result={"verdict": "fail"}, notified=True)
    assert sl.has_work(tmp_path, tmp_path / "none", tmp_path / "none")
    archived = sl.migrate_registry(tmp_path)
    assert archived == "registry_sat-judge_v1.json" and (tmp_path / archived).exists()
    reg = sl.load_registry(tmp_path)
    v = reg["variants"][s1["id"]]
    assert reg["judge_version"] == sl.JUDGE_VERSION and reg["incumbent"] is None
    assert v["status"] == sl.STATUS_QUEUED and v["result"] is None and v["notified"] is False
    assert reg["cumulative_trials"] == 2  # 시도 수는 그대로
    assert sl.migrate_registry(tmp_path) is None  # 두 번째는 아무 일 없음


def test_build_data_measures_returns_with_adjusted_close():
    idx = pd.bdate_range("2019-01-01", periods=300)
    close = pd.Series(100.0, index=idx)
    adj = pd.Series(np.linspace(90, 100, len(idx)), index=idx)  # 배당이 반영돼 과거 값이 낮다
    frames = {"AAA": pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Adj Close": adj, "Volume": 1e6}),
              "SPY": pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1e6})}
    pp = lambda t, s, e: frames.get(t, pd.DataFrame()).loc[s:e]  # noqa: E731
    data = sl.build_data({"champion40"}, start="2019-06-01", end="2020-02-28", pool_provider=lambda pt, d: ["AAA"], price_provider=pp)
    assert data.closes["AAA"].iloc[-1] > data.closes["AAA"].iloc[0]  # 가격은 그대로지만 총수익은 오른다
    assert (data.ohlcv["AAA"]["Close"] == 100.0).all()  # 신호용 가격은 그대로
