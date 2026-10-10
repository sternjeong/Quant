"""앞으로 토너먼트 v2(core/forward_tournament_v2.py) — 기록 멱등성, 새틀라이트 6개월 고정, 블렌드 표류·연초 리밸런싱,
원장 기반 평가, 판정 문턱, v2 실패가 v1 기록에 영향 없음."""

from __future__ import annotations

import zlib
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from core import forward_tournament_v2 as ft2
from core import guru_history as gh

NOW = datetime(2027, 12, 31, tzinfo=timezone.utc)  # 모든 합성 날짜보다 뒤 — 미완료 봉 가드가 끼어들지 않게
FULL_IDX = pd.bdate_range("2025-01-01", "2027-06-30")
POOL = [f"P{i:02d}" for i in range(12)]


def _ohlc(t: str, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """티커 이름으로 정해지는 결정론 가격. P 종목은 꾸준히 올라 추세가 살아 있고 번호가 클수록 모멘텀이 크다."""
    seed = zlib.crc32(t.encode())
    rng = np.random.default_rng(seed)
    full = pd.bdate_range("2025-01-01", "2027-06-30")
    if t.startswith("P"):
        mu, sd = 0.0004 + 0.0001 * int(t[1:]), 0.002
    else:
        mu, sd = 0.0003 + (seed % 7) * 0.0001, 0.006 + (seed % 5) * 0.002
    c = 50 * np.exp(np.cumsum(rng.normal(mu, sd, len(full))))
    df = pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Adj Close": c}, index=full)
    return df.loc[df.index.isin(idx)]


def _env(end: str):
    idx = FULL_IDX[FULL_IDX <= pd.Timestamp(end)]
    calls = []

    def price_fn(tickers):
        return {t: _ohlc(t, idx) for t in tickers}

    def sat_price_fn(tickers, day):
        calls.append(str(day))
        return {t: _ohlc(t, idx) for t in tickers}

    return dict(price_fn=price_fn, pool_fn=lambda pool, d: list(POOL), sat_price_fn=sat_price_fn,
                guru_store=gh.SyntheticStore(), now=NOW), calls


def test_record_idempotent_and_waits_for_start(tmp_path):
    led = tmp_path / "l.jsonl"
    env, _ = _env("2026-10-09")
    assert not ft2.record(path=led, **env)["recorded"]  # 2026-10-12 전
    env, calls = _env("2026-10-12")
    first = ft2.record(path=led, **env)
    again = ft2.record(path=led, **env)
    assert first["recorded"] and first["date"] == "2026-10-12" and not first["errors"]
    assert not again["recorded"] and again["reason"] == "이미 기록됨"
    rows = ft2.load_ledger(led)
    assert len(rows) == 1 and rows[0]["judge_version"] == "forward-tournament/v2"
    w = rows[0]["weights"]
    assert set(w) == set(ft2.CANDIDATES)
    assert w["B0"] == {"SPY": 1.0}
    for cid in ("B1", "C1", "C2"):
        assert sum(w[cid].values()) == pytest.approx(1.0)
    assert w["C1"]["SPY"] == pytest.approx(0.5) and w["C2"]["SPY"] == pytest.approx(0.3)
    assert "DBC" not in w["B1"]
    for cid in ft2.SATELLITES:
        assert len(w[cid]) == 3 and all(v == pytest.approx(1 / 3) for v in w[cid].values())
        assert set(w[cid]) <= set(POOL)
    mom = {t: (lambda c: c.iloc[-1] / c.iloc[-253] - 1)(_ohlc(t, FULL_IDX)["Close"].loc[:"2026-10-12"]) for t in POOL}
    assert rows[0]["satellite"]["S0"]["picks"] == sorted(POOL, key=lambda t: -mom[t])[:3]  # 12개월 모멘텀 순
    assert len(calls) == 2  # 새틀라이트 두 후보만 가격을 읽음


def test_partial_us_session_bar_is_not_recorded(tmp_path):
    env, _ = _env("2026-10-13")
    env["now"] = datetime(2026, 10, 13, 15, 39, tzinfo=timezone.utc)  # 00:39 KST 10-14 = 뉴욕 10-13 11:39(장중)
    res = ft2.record(path=tmp_path / "l.jsonl", **env)
    assert res["date"] == "2026-10-12"


def test_satellite_picks_frozen_between_six_month_rebalances(tmp_path):
    led = tmp_path / "l.jsonl"
    for end in ("2026-10-12", "2026-10-13"):
        env, calls = _env(end)
        ft2.record(path=led, **env)
    assert calls == []  # 둘째 날은 다시 고르지 않음
    rows = ft2.load_ledger(led)
    w1, w2 = rows[0]["weights"]["S0"], rows[1]["weights"]["S0"]
    assert set(w1) == set(w2)
    rets = {t: float(_ohlc(t, FULL_IDX)["Adj Close"].pct_change().loc["2026-10-13"]) for t in w1}
    assert w2 == pytest.approx(ft2.drift(w1, rets))  # 보유 종목이 수익에 따라 표류
    assert w2 != pytest.approx(w1)
    env, calls = _env("2027-04-09")  # 6개월(2027-04-12) 전
    ft2.record(path=led, **env)
    assert calls == [] and ft2.load_ledger(led)[-1]["satellite"]["S1"]["rebalanced"] == "2026-10-12"
    env, calls = _env("2027-04-12")
    ft2.record(path=led, **env)
    last = ft2.load_ledger(led)[-1]
    assert len(calls) == 2 and last["satellite"]["S0"]["rebalanced"] == "2027-04-12"
    assert all(v == pytest.approx(1 / 3) for v in last["weights"]["S0"].values())


def test_satellite_failure_keeps_previous_holdings_and_reports(tmp_path, monkeypatch):
    led = tmp_path / "l.jsonl"
    env, _ = _env("2026-10-12")
    ft2.record(path=led, **env)
    env, _ = _env("2027-04-12")

    def boom(*a, **k):
        raise RuntimeError("pool down")

    env["pool_fn"] = boom
    res = ft2.record(path=led, **env)
    assert res["recorded"] and set(res["errors"]) == {"S0", "S1"}
    last = ft2.load_ledger(led)[-1]
    assert last["satellite"]["S0"]["rebalanced"] == "2026-10-12"  # 다음 날 다시 고름
    assert set(last["weights"]["S0"]) == set(ft2.load_ledger(led)[0]["weights"]["S0"])


def test_blend_sleeves_drift_then_reset_on_first_trading_day_of_year(tmp_path):
    led = tmp_path / "l.jsonl"
    for end in ("2026-12-29", "2026-12-31"):
        env, _ = _env(end)
        ft2.record(path=led, **env)
    rows = ft2.load_ledger(led)
    assert rows[0]["sleeves"]["C1"] == pytest.approx(0.5)
    rets = pd.DataFrame({t: _ohlc(t, FULL_IDX)["Adj Close"] for t in list(ft2.CORE_UNIVERSE_V2) + ["SPY", "BIL"]}).pct_change()
    gap = rets.loc["2026-12-30":"2026-12-31"]
    g_spy = float((1 + gap["SPY"]).prod())
    _, g_core = ft2._drift_path(rows[0]["components"]["ERC"], gap)
    for cid, s0 in (("C1", 0.5), ("C2", 0.3)):
        expect = s0 * g_spy / (s0 * g_spy + (1 - s0) * g_core)
        assert rows[1]["sleeves"][cid] == pytest.approx(expect)
        assert rows[1]["sleeves"][cid] != pytest.approx(s0)
        assert rows[1]["weights"][cid]["SPY"] == pytest.approx(expect)
    env, _ = _env("2027-01-04")
    ft2.record(path=led, **env)
    last = ft2.load_ledger(led)[-1]
    assert last["sleeves"]["C1"] == pytest.approx(0.5) and last["sleeves"]["C2"] == pytest.approx(0.3)


def _rows(idx, weights):
    return [{"date": str(d.date()), "weights": weights} for d in idx]


def _rets(n, seed=3):
    idx = pd.bdate_range("2026-10-12", periods=n)
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0004, 0.012, n)
    spy[100:130] = -0.008  # 약 21% 하락 구간
    core = rng.normal(0.0003, 0.009, n)
    core[100:130] = -0.006
    safe = 0.5 * spy + rng.normal(0.0002, 0.003, n)
    safe[100:130] = -0.002
    df = pd.DataFrame({"SPY": spy, "CORE": core, "SAFE": safe, "BIL": 0.0001,
                       "X": rng.normal(0.0004, 0.015, n), "Y": rng.normal(0.0004, 0.015, n)}, index=idx)
    df["W"] = df["X"] + 0.002 + rng.normal(0, 0.002, n)
    return idx, df


def test_evaluate_waits_then_judges_from_ledger():
    idx, rets = _rets(300)
    weights = {"B0": {"SPY": 1.0}, "B1": {"CORE": 1.0}, "C1": {"SAFE": 1.0}, "C2": {"SPY": 1.0},
               "S0": {"X": 0.5, "Y": 0.5}, "S1": {"W": 1.0}}
    rows = _rows(idx, weights)
    early = ft2.evaluate(rows[:60], rets)
    assert early["candidates"]["C1"]["verdict"].startswith("판정 전") and early["candidates"]["B0"]["verdict"] == "기준"
    assert early["candidates"]["S1"]["verdict"].startswith("판정 전")
    full = ft2.evaluate(rows, rets)
    c = full["candidates"]
    assert full["days"] == 299  # 첫 기록 다음 날부터
    assert c["C1"]["verdict"] == "PASS"
    assert c["C2"]["verdict"] == "NOT_EVALUABLE"  # B0 와 매일 같음
    assert c["S1"]["verdict"] == "PASS" and c["S1"]["ir_vs_S0"] >= 0.5
    assert full["rank_core"][0] == "C1"
    # 비용: 첫날 진입 비용만(같은 비중을 계속 기록 → 표류분만큼 되돌리는 회전)
    s = ft2.series_from_ledger(rows, "B0", rets)
    assert s.iloc[0] == pytest.approx(rets["SPY"].iloc[1] - ft2.COST_BPS / 1e4)
    assert s.iloc[1:].to_numpy() == pytest.approx(rets["SPY"].iloc[2:].to_numpy())
    worse = rets.copy()
    worse["W"] = worse["X"] - 0.002
    assert ft2.evaluate(rows, worse)["candidates"]["S1"]["verdict"] == "FAIL"


def test_missing_record_days_drift_without_cost():
    idx, rets = _rets(10)
    rows = [{"date": str(idx[0].date()), "weights": {"S0": {"X": 0.5, "Y": 0.5}}}]
    s = ft2.series_from_ledger(rows, "S0", rets)
    assert len(s) == 1  # 마지막 기록 다음 거래일까지만
    rows.append({"date": str(idx[5].date()), "weights": {"S0": {"X": 0.5, "Y": 0.5}}})
    s = ft2.series_from_ledger(rows, "S0", rets)
    w = {"X": 0.5, "Y": 0.5}
    expect = []
    for i in range(1, 7):
        r = rets.iloc[i][["X", "Y"]].to_dict()
        cost = ft2.SAT_COST_BPS / 1e4 if i == 1 else 0.0
        if i == 6:  # 기록일 5 의 1/2·1/2 로 되돌리는 회전 비용
            cost = sum(abs(0.5 - v) for v in w.values()) * ft2.SAT_COST_BPS / 1e4
            w = {"X": 0.5, "Y": 0.5}
        expect.append(sum(w[t] * r[t] for t in w) - cost)
        w = ft2.drift(w, r)
    assert s.to_numpy() == pytest.approx(np.array(expect))


def test_judge_thresholds():
    b0 = {"sharpe": 0.8, "mdd": -0.30, "return_per_mdd": 0.40}
    b1 = {"sharpe": 0.7, "mdd": -0.25, "return_per_mdd": 0.45}
    ok = {"sharpe": 0.81, "mdd": -0.25, "return_per_mdd": 0.46}
    assert ft2.judge_blend(ok, b0, b1)
    assert not ft2.judge_blend({**ok, "mdd": -0.251}, b0, b1)          # 5%p 에 못 미침
    assert not ft2.judge_blend({**ok, "sharpe": 0.8}, b0, b1)          # 샤프 같음은 통과 아님
    assert not ft2.judge_blend({**ok, "return_per_mdd": 0.44}, b0, b1)  # B1 보다 낮음
    assert not ft2.judge_blend({**ok, "return_per_mdd": None}, b0, b1)
    s0 = {"mdd": -0.30}
    good = {"ir_vs_S0": 0.5, "excess_vs_S0": 0.01, "mdd": -0.35}
    assert ft2.judge_satellite(good, s0)
    assert not ft2.judge_satellite({**good, "ir_vs_S0": 0.49}, s0)
    assert not ft2.judge_satellite({**good, "excess_vs_S0": 0.0}, s0)
    assert not ft2.judge_satellite({**good, "mdd": -0.351}, s0)


def test_status_snapshot_and_hub_row(tmp_path):
    from hub import satellite_lab_page as page

    led, stp = tmp_path / "l.jsonl", tmp_path / "status.json"
    for end in ("2026-10-12", "2026-10-13", "2026-10-14"):
        env, _ = _env(end)
        ft2.record(path=led, **env)
    env, _ = _env("2026-10-15")
    st = ft2.refresh_status(path=led, status_path=stp, price_fn=env["price_fn"])
    assert st["days"] == 3 and st["records"] == 3 and ft2.load_status(stp)["rank_core"]
    html = page.render_tournament_v2_row({"records": 3, "last": "2026-10-14", "start": "2026-10-12", "min_days": 252,
                                          "status": ft2.load_status(stp), "labels": {"C1": "x"}})
    assert "앞으로 토너먼트 v2" in html and "3/252" in html and "판정 전" in html and "중간 순위" in html
    assert "기록 대기" in page.render_tournament_v2_row({"records": 0, "start": "2026-10-12", "min_days": 252})


def test_v2_failure_does_not_affect_v1_record(tmp_path, monkeypatch):
    from core import forward_tournament as ft
    from core import process_registry, rnd_topics
    from scheduler import run_scheduler

    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "toggles.json")
    monkeypatch.setattr(rnd_topics, "is_on", lambda key: True)
    v1, failures = [], []
    monkeypatch.setattr(ft, "record", lambda *a, **k: v1.append(1) or {"recorded": True, "date": "2026-10-12"})
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda job, msg: failures.append((job, msg)))

    def boom(*a, **k):
        raise ValueError("v2 broke")

    monkeypatch.setattr(ft2, "record", boom)
    run_scheduler.forward_tournament_record_job()
    assert v1 == [1] and failures == [("forward_tournament_v2_record", "ValueError: v2 broke")]

    # v1 이 실패해도 v2 는 기록된다
    failures.clear()
    v2 = []
    monkeypatch.setattr(ft, "record", boom)
    monkeypatch.setattr(ft2, "record", lambda *a, **k: v2.append(1) or {"recorded": True, "date": "2026-10-12", "errors": {}})
    monkeypatch.setattr(ft2, "refresh_status", lambda *a, **k: {})
    run_scheduler.forward_tournament_record_job()
    assert v2 == [1] and failures == [("forward_tournament_record", "ValueError: v2 broke")]

    # 새틀라이트 선정 실패는 별도 키로 알림
    failures.clear()
    monkeypatch.setattr(ft, "record", lambda *a, **k: {"recorded": True})
    monkeypatch.setattr(ft2, "record", lambda *a, **k: {"recorded": True, "date": "2027-04-12", "errors": {"S1": "RuntimeError: x"}})
    run_scheduler.forward_tournament_record_job()
    assert failures == [("forward_tournament_v2_record", "S1 RuntimeError: x")]
