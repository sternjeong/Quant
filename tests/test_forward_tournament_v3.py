"""앞으로 토너먼트 v3(core/forward_tournament_v3.py) — 기록 멱등성·시작 관문, 1월만 슬리브 리셋(그 사이 표류), 엇갈린 하위 슬리브가
자기 재선정 사이에 고정, K6 버퍼, KRS 자격, SC2 월 1회 상위 2, v1·v2 와의 실패 격리, 원장 기반 평가, 판정 문턱, 상태 파일·관제 센터 줄."""

from __future__ import annotations

import zlib
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from core import forward_tournament_v3 as ft3

FULL_IDX = pd.bdate_range("2025-01-01", "2027-12-31")
POOL = [f"P{i:02d}" for i in range(12)]
STRONG = ["Q00", "Q01", "Q02"]


def _ohlc(t: str, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """티커 이름으로 정해지는 결정론 가격. P 종목은 꾸준히 올라 추세가 살아 있고 번호가 클수록 모멘텀이 크다. Q 는 더 강하다."""
    seed = zlib.crc32(t.encode())
    rng = np.random.default_rng(seed)
    if t.startswith("P"):
        mu, sd = 0.0004 + 0.0001 * int(t[1:]), 0.002
    elif t.startswith("Q"):
        mu, sd = 0.0030 + 0.0001 * int(t[1:]), 0.002
    else:
        mu, sd = 0.0003 + (seed % 7) * 0.0001, 0.006 + (seed % 5) * 0.002
    c = 50 * np.exp(np.cumsum(rng.normal(mu, sd, len(FULL_IDX))))
    df = pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Adj Close": c}, index=FULL_IDX)
    return df.loc[df.index.isin(idx)]


def _after(end: str) -> datetime:
    """그날 뉴욕 장 마감 뒤(UTC 23:00 = 뉴욕 19:00)."""
    d = pd.Timestamp(end)
    return datetime(d.year, d.month, d.day, 23, 0, tzinfo=timezone.utc)


def _env(end: str, pool=None):
    idx = FULL_IDX[FULL_IDX <= pd.Timestamp(end)]
    calls = []

    def price_fn(tickers):
        return {t: _ohlc(t, idx) for t in tickers}

    def sat_price_fn(tickers, day):
        calls.append(str(day))
        return {t: _ohlc(t, idx) for t in tickers}

    return dict(price_fn=price_fn, pool_fn=lambda p, d: list(pool or POOL), sat_price_fn=sat_price_fn, now=_after(end)), calls


def _rec(led, end, pool=None):
    env, calls = _env(end, pool)
    res = ft3.record(path=led, **env)
    return res, calls


def _rets(tickers):
    return pd.DataFrame({t: _ohlc(t, FULL_IDX)["Adj Close"] for t in tickers}).pct_change()


def test_record_idempotent_and_start_gate(tmp_path):
    led = tmp_path / "l.jsonl"
    env, _ = _env("2026-10-16")
    env["now"] = datetime(2026, 10, 16, 15, 39, tzinfo=timezone.utc)  # 00:39 KST 10-17 = 뉴욕 10-16 11:39(장중)
    res = ft3.record(path=led, **env)
    assert not res["recorded"] and res["date"] == "2026-10-15" and "시작 전" in res["reason"]
    assert ft3.load_armed(led)["start_not_before"] == "2026-10-16"
    assert not led.exists()
    first, calls = _rec(led, "2026-10-16")
    again, _ = _rec(led, "2026-10-16")
    assert first["recorded"] and first["date"] == "2026-10-16" and not first["errors"]
    assert not again["recorded"] and again["reason"] == "이미 기록됨"
    assert ft3.load_armed(led)["start_not_before"] == "2026-10-16"  # 첫 시도 시각은 바뀌지 않음
    rows = ft3.load_ledger(led)
    assert len(rows) == 1 and rows[0]["judge_version"] == "forward-tournament/v3" and rows[0]["start"] == "2026-10-16"
    w = rows[0]["weights"]
    assert set(w) == set(ft3.CANDIDATES)
    assert w["B0"] == {"SPY": 1.0}
    for cid in ft3.CANDIDATES:
        assert sum(w[cid].values()) == pytest.approx(1.0)
    assert w["P1"]["SPY"] == pytest.approx(0.85) and w["P4"]["SPY"] == pytest.approx(0.5) and w["P1ST"]["SPY"] == pytest.approx(0.85)
    sat = rows[0]["satellite"]
    mom = {t: (lambda c: c.iloc[-1] / c.iloc[-253] - 1)(_ohlc(t, FULL_IDX)["Close"].loc[:"2026-10-16"]) for t in POOL}
    top3 = sorted(POOL, key=lambda t: -mom[t])[:3]
    for k in ft3.SAT_STATES:  # 모두 첫 기록일에 처음 고름(버퍼 상태도 보유가 없어 그냥 상위 3)
        assert sat[k]["picks"] == top3 and sat[k]["rebalanced"] == "2026-10-16"
    for t in top3:
        assert w["P1"][t] == pytest.approx(0.05) and w["P1ST"][t] == pytest.approx(0.05)
        assert w["B1"][t] == pytest.approx(0.05) and w["P4"][t] == pytest.approx(0.10)
    assert len(w["SC2"]) == 2 and all(v == pytest.approx(0.5) for v in w["SC2"].values())
    assert set(w["SC2"]) <= set(ft3.SECTORS)
    assert sum(v for t, v in w["B1"].items() if t not in top3) == pytest.approx(0.85)
    assert "DBC" not in w["B1"]
    assert calls == ["2026-10-16"]  # 새틀라이트 풀 가격은 하루 한 번만 읽음


def test_start_waits_for_first_attempt_date(tmp_path):
    led = tmp_path / "l.jsonl"
    env, _ = _env("2026-10-19")
    env["now"] = datetime(2026, 10, 20, 15, 39, tzinfo=timezone.utc)  # 첫 시도 = 뉴욕 10-20(장중) → 10-19 는 시작 전
    assert not ft3.record(path=led, **env)["recorded"]
    assert ft3.load_armed(led)["start_not_before"] == "2026-10-20"
    res, _ = _rec(led, "2026-10-20")
    assert res["recorded"] and res["date"] == "2026-10-20"


def test_live_mode_drifts_until_target_changes(tmp_path):
    led = tmp_path / "l.jsonl"
    _rec(led, "2026-10-16")
    res, calls = _rec(led, "2026-10-19")
    assert res["recorded"] and calls == []
    r0, r1 = ft3.load_ledger(led)
    gap = _rets(list(r0["weights"]["B1"]))
    exp = ft3.ft2.drift(r0["weights"]["B1"], gap.loc["2026-10-19"].to_dict())
    assert r1["weights"]["B1"] == pytest.approx(exp)  # 매매 없음 → 표류
    assert "B1" not in r1["trades"] and "KRS" not in r1["trades"]
    assert r1["weights"]["B0"] == pytest.approx({"SPY": 1.0})


def test_january_only_sleeve_reset_with_drift(tmp_path):
    led = tmp_path / "l.jsonl"
    for end in ("2026-12-29", "2026-12-31"):
        _rec(led, end)
    r0, r1 = ft3.load_ledger(led)
    gap = _rets(sorted({t for b in r0["books"]["P1"].values() for t in b if t != ft3.CASH_KEY})).loc["2026-12-30":"2026-12-31"]
    exp = ft3.drift_book(r0["books"]["P1"], gap)
    assert sum(r1["books"]["P1"]["spy"].values()) == pytest.approx(sum(exp["spy"].values()))
    assert r1["weights"]["P1"]["SPY"] != pytest.approx(0.85)  # 표류
    assert "P1" not in r1["trades"]
    res, calls = _rec(led, "2027-01-04")
    last = ft3.load_ledger(led)[-1]
    assert calls == ["2027-01-04"] and last["satellite"]["SAT"]["rebalanced"] == "2027-01-04"
    assert last["satellite"]["ST_B"]["rebalanced"] == "2026-12-29"  # 3월까지 그대로
    for cid, spy in (("P1", 0.85), ("P4", 0.50), ("P1ST", 0.85)):
        assert last["weights"][cid]["SPY"] == pytest.approx(spy)
        assert last["trades"][cid][0] == "january"
    # 7월 재선정은 새틀라이트 슬리브 안에서만(SPY 슬리브는 표류한 그대로)
    _rec(led, "2027-06-30")
    _rec(led, "2027-07-01")
    a, b = ft3.load_ledger(led)[-2:]
    tick = sorted({t for bk in a["books"]["P1"].values() for t in bk if t != ft3.CASH_KEY})
    exp = ft3.drift_book(a["books"]["P1"], _rets(tick).loc["2027-07-01":"2027-07-01"])
    assert b["satellite"]["SAT"]["rebalanced"] == "2027-07-01"
    assert b["books"]["P1"]["spy"]["SPY"] == pytest.approx(exp["spy"]["SPY"]) and b["books"]["P1"]["spy"]["SPY"] != pytest.approx(0.85)
    sat = {t: v for t, v in b["books"]["P1"]["SAT"].items() if t != ft3.CASH_KEY}
    assert sum(b["books"]["P1"]["SAT"].values()) == pytest.approx(sum(exp["SAT"].values()))
    assert len(set(round(v, 12) for v in sat.values())) == 1  # 슬리브 안은 균등
    assert b["trades"]["P1"] == ["sleeve:SAT"]
    assert sum(v for t, v in b["weights"]["B1"].items() if t in b["satellite"]["SAT"]["picks"]) == pytest.approx(0.15)  # 라이브 방식은 전체 85/15


def test_staggered_sub_sleeves_frozen_between_their_reselections(tmp_path):
    led = tmp_path / "l.jsonl"
    _rec(led, "2026-10-16")
    res, calls = _rec(led, "2026-10-30")
    assert calls == []
    res, calls = _rec(led, "2026-11-02")
    a, b = ft3.load_ledger(led)[-2:]
    assert calls == ["2026-11-02"]
    assert b["satellite"]["ST_C"]["rebalanced"] == "2026-11-02"  # 5·11월 묶음만 다시 고름
    for k in ("SAT", "ST_A", "ST_B"):
        assert b["satellite"][k]["rebalanced"] == "2026-10-16"
    tick = sorted({t for bk in a["books"]["P1ST"].values() for t in bk if t != ft3.CASH_KEY})
    exp = ft3.drift_book(a["books"]["P1ST"], _rets(tick).loc["2026-11-02":"2026-11-02"])
    for s in ("spy", "ST_A", "ST_B"):
        assert b["books"]["P1ST"][s] == pytest.approx(exp[s])  # 다른 묶음은 표류만
    c = {t: v for t, v in b["books"]["P1ST"]["ST_C"].items() if t != ft3.CASH_KEY}
    assert sum(c.values()) == pytest.approx(sum(exp["ST_C"].values())) and len(set(round(v, 12) for v in c.values())) == 1
    assert b["trades"]["P1ST"] == ["sleeve:ST_C"]
    assert "P1" not in b["trades"]
    _rec(led, "2027-01-04")
    res, calls = _rec(led, "2027-03-01")
    last = ft3.load_ledger(led)[-1]
    assert calls == ["2027-03-01"]
    assert last["satellite"]["ST_B"]["rebalanced"] == "2027-03-01"
    assert last["satellite"]["ST_A"]["rebalanced"] == "2027-01-04" and last["satellite"]["ST_C"]["rebalanced"] == "2026-11-02"


def test_k6_buffer_keeps_winners_that_slip_to_rank_six(tmp_path):
    led = tmp_path / "l.jsonl"
    _rec(led, "2026-12-31")
    first = ft3.load_ledger(led)[0]["satellite"]
    old = first["ST_A"]["picks"]
    _rec(led, "2027-01-04", pool=POOL + STRONG)  # 더 강한 3종목이 풀에 들어옴 → 기존 상위 3은 4~6위
    sat = ft3.load_ledger(led)[-1]["satellite"]
    assert sorted(sat["SAT"]["picks"]) == STRONG and sat["SAT"]["kept"] == []  # 버퍼 없음: 모두 교체
    assert sorted(sat["ST_A"]["picks"]) == sorted(old) and sorted(sat["ST_A"]["kept"]) == sorted(old)  # K6: 유지
    assert sat["ST_B"]["picks"] == old  # 3·9월 묶음은 아직 다시 고르지 않음


def test_select_with_buffer_rules():
    pool = {"A": 9.0, "B": 8.0, "C": 7.0, "D": 6.0, "E": 5.0, "F": 4.0, "G": 3.0, "H": 2.0}
    assert ft3.select_with_buffer(["F", "G"], pool, {"F": 4.0, "G": 3.0}, None) == (["A", "B", "C"], [])
    picks, kept = ft3.select_with_buffer(["F", "G"], pool, {"F": 4.0, "G": 3.0}, 6)
    assert kept == ["F"] and picks == ["F", "A", "B"]  # F 는 6위 → 유지, G 는 7위 → 교체
    # 풀 밖 보유 종목은 자기 점수로 같은 순위 식(2위 → 유지), 점수 없음(추세 꺼짐·가격 없음) → 교체
    picks, kept = ft3.select_with_buffer(["Z", "Y"], pool, {"Z": 8.5, "Y": None}, 6)
    assert kept == ["Z"] and picks == ["Z", "A", "B"]


def test_krs_core_requires_beating_spy():
    from core import core_lab as cl

    idx = pd.bdate_range("2024-01-01", "2025-12-31")
    n = len(idx)
    t = np.arange(n)
    closes = pd.DataFrame({"A": 100 * np.exp(0.0010 * t), "B": 100 * np.exp(0.0002 * t), "C": 100 * np.exp(-0.0003 * t)}, index=idx)
    extra = pd.DataFrame({"SPY": 100 * np.exp(0.0005 * t), "BIL": 100 * np.exp(0.0001 * t)}, index=idx)
    base = cl.CoreConfig(cash="bil", universe=("A", "B", "C"))
    zero = cl.build_weights(closes, extra, base).iloc[-1]
    krs = cl.build_weights(closes, extra, cl.with_changes(base, abs_filter="spy")).iloc[-1]
    assert zero["A"] == pytest.approx(0.25) and zero["B"] == pytest.approx(0.25) and zero["BIL"] == pytest.approx(0.5)
    assert krs["A"] == pytest.approx(0.25) and krs["B"] == 0 and krs["BIL"] == pytest.approx(0.75)  # B 는 > 0 이지만 SPY 에 못 미침
    short = extra.copy()
    short.loc[:, "SPY"] = np.nan  # SPY 수익률 없음 → 아무도 자격 없음
    krs2 = cl.build_weights(closes, short, cl.with_changes(base, abs_filter="spy", market_filter="none")).iloc[-1]
    assert krs2[["A", "B", "C"]].sum() == 0 and krs2["BIL"] == pytest.approx(1.0)


def test_sc2_top2_monthly_signal_from_previous_day():
    idx = pd.bdate_range("2025-06-02", "2026-11-03")
    rng = np.random.default_rng(5)
    total = pd.DataFrame({t: 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.001, len(idx)))) for t in ft3.SECTORS + ("SPY",)},
                         index=idx)
    total["XLK"] = 100 * np.exp(0.0020 * np.arange(len(idx)))
    total["XLE"] = 100 * np.exp(0.0015 * np.arange(len(idx)))
    spike = total.copy()
    spike.loc["2026-11-02":, "XLU"] *= 10  # 결정일 당일 급등은 신호에 들어가지 않는다(신호 = 전 거래일 10-30)
    got = ft3.sc2_target(spike.loc[:"2026-11-02"])
    assert got["month"] == "2026-11" and got["signal_date"] == "2026-10-30"
    assert got["picks"] == ["XLK", "XLE"] and got["weights"] == {"XLK": 0.5, "XLE": 0.5}
    assert ft3.sc2_target(spike.loc[:"2026-11-03"])["picks"] == ["XLK", "XLE"]  # 그달 안에서는 같은 결정
    # 신호가 있는 섹터가 4개 미만 → SPY 100%
    few = total[["XLK", "XLE", "XLU", "SPY"]]
    assert ft3.sc2_target(few.loc[:"2026-11-02"])["weights"] == {"SPY": 1.0}


def test_sc2_rebalances_monthly_and_drifts_between(tmp_path):
    led = tmp_path / "l.jsonl"
    for end in ("2026-10-16", "2026-10-30", "2026-11-02"):
        _rec(led, end)
    r0, r1, r2 = ft3.load_ledger(led)
    assert "SC2" not in r1["trades"]
    exp = ft3.ft2.drift(r0["weights"]["SC2"], _rets(list(r0["weights"]["SC2"])).loc["2026-10-19":"2026-10-30"].add(1).prod().sub(1).to_dict())
    assert sum(r1["weights"]["SC2"].values()) == pytest.approx(1.0)
    assert r1["weights"]["SC2"] != pytest.approx({t: 0.5 for t in r0["weights"]["SC2"]})
    assert set(r1["weights"]["SC2"]) == set(exp)
    assert r2["trades"]["SC2"] == ["sleeve:sec"] and r2["components"]["sc2"]["month"] == "2026-11"
    assert all(v == pytest.approx(0.5) for v in r2["weights"]["SC2"].values())


def test_satellite_failure_retries_next_day_and_keeps_others(tmp_path):
    led = tmp_path / "l.jsonl"
    env, _ = _env("2026-10-16")

    def boom(*a, **k):
        raise RuntimeError("pool down")

    env["pool_fn"] = boom
    res = ft3.record(path=led, **env)
    assert res["recorded"] and set(res["errors"]) == set(ft3.SAT_STATES)
    row = ft3.load_ledger(led)[0]
    assert row["weights"]["P1"] == pytest.approx({"SPY": 0.85})  # 첫 선정 실패 → 그 슬리브는 현금
    assert row["satellite"]["SAT"] == {}
    res, calls = _rec(led, "2026-10-19")  # 다음 기록일에 다시 고름
    last = ft3.load_ledger(led)[-1]
    assert calls == ["2026-10-19"] and last["satellite"]["SAT"]["rebalanced"] == "2026-10-19"
    assert sum(last["weights"]["P1"].values()) == pytest.approx(1.0, abs=1e-6)


def _rows(idx, weights):
    return [{"date": str(d.date()), "weights": weights} for d in idx]


def _eval_rets(n, seed=3):
    idx = pd.bdate_range("2026-10-16", periods=n)
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0004, 0.012, n)
    spy[100:130] = -0.008
    df = pd.DataFrame({"SPY": spy, "BIL": 0.0001}, index=idx)
    df["UP"] = df["SPY"] + 0.0001          # 연 약 +2.5%p, 낙폭 비슷 → PASS
    df["DEEP"] = df["SPY"] * 1.6 + 0.0004   # 수익은 높지만 낙폭이 훨씬 깊음 → FAIL
    df["LOW"] = df["SPY"] - 0.0001          # 수익 낮음 → FAIL
    df["CH"] = df["SPY"] * 0.8
    return idx, df


def test_evaluate_waits_then_judges_from_ledger():
    idx, rets = _eval_rets(300)
    weights = {"B0": {"SPY": 1.0}, "B1": {"CH": 1.0}, "P1": {"UP": 1.0}, "P4": {"SPY": 1.0}, "P1ST": {"LOW": 1.0},
               "KRS": {"DEEP": 1.0}, "SC2": {"UP": 0.5, "SPY": 0.5}, "SC2VT20": {"SPY": 0.5, "BIL": 0.5}}
    rows = _rows(idx, weights)
    early = ft3.evaluate(rows[:60], rets)
    assert early["candidates"]["P1"]["verdict"].startswith("판정 전") and early["candidates"]["B0"]["verdict"] == "기준"
    assert early["rank_note"] == "판정 아님"
    full = ft3.evaluate(rows, rets)
    c = full["candidates"]
    assert full["days"] == 299
    assert c["P1"]["verdict"] == "PASS" and c["P1"]["cagr_vs_B0"] >= 0.01
    assert c["P4"]["verdict"] == "NOT_EVALUABLE"  # B0 와 매일 같음
    assert c["P1ST"]["verdict"] == "FAIL"
    assert c["KRS"]["verdict"] == "FAIL" and c["KRS"]["cagr_vs_B0"] >= 0.01 and c["KRS"]["mdd_vs_B0"] < -0.03
    assert c["B1"]["verdict"] == "기준"
    assert c["P1"]["ir_vs_B1"] is not None and c["P1"]["cagr_vs_B1"] == pytest.approx(c["P1"]["cagr"] - c["B1"]["cagr"])
    assert [c[k]["cagr"] for k in full["rank"]] == sorted((c[k]["cagr"] for k in full["rank"]), reverse=True) and set(full["rank"]) == set(ft3.CANDIDATES)
    s = ft3.series_from_ledger(rows, "B0", rets)
    assert s.iloc[0] == pytest.approx(rets["SPY"].iloc[1] - ft3.COST_BPS / 1e4)  # 첫날 진입 비용만
    s = ft3.series_from_ledger(rows[:2], "P1", rets.assign(UP=0.0))
    assert s.iloc[0] == pytest.approx(-ft3.STOCK_COST_BPS / 1e4)  # ETF 가 아닌 종목은 8bp


def test_judge_thresholds():
    b0 = {"cagr": 0.10, "mdd": -0.20}
    assert ft3.judge({"cagr": 0.11, "mdd": -0.23}, b0)
    assert not ft3.judge({"cagr": 0.1099, "mdd": -0.10}, b0)   # +1.0%p 에 못 미침
    assert not ft3.judge({"cagr": 0.20, "mdd": -0.2301}, b0)   # 낙폭 3%p 넘게 나쁨


def test_status_snapshot_and_hub_row(tmp_path):
    from hub import satellite_lab_page as page

    led, stp = tmp_path / "l.jsonl", tmp_path / "status.json"
    for end in ("2026-10-16", "2026-10-19", "2026-10-20"):
        _rec(led, end)
    env, _ = _env("2026-10-21")
    st = ft3.refresh_status(path=led, status_path=stp, price_fn=env["price_fn"])
    assert st["days"] == 3 and st["records"] == 3 and ft3.load_status(stp)["rank"]
    assert st["judge_version"] == "forward-tournament/v3" and st["last_errors"] == {}
    html = page.render_tournament_v3_row({"records": 3, "last": "2026-10-20", "start": "2026-10-16", "min_days": 252,
                                          "status": ft3.load_status(stp), "labels": {"P1": "x"}})
    assert "앞으로 토너먼트 v3" in html and "3/252" in html and "판정 전" in html and "판정 아님" in html and "B1(현 챔피언) 대비" in html
    assert "기록 대기" in page.render_tournament_v3_row({"records": 0, "registered": "2026-10-16", "min_days": 252})
    assert "확인 불가" in page.render_tournament_v3_row({"error": "OSError"})
    shadows = page.render_shadows({"tournament_v3": {"records": 0, "registered": "2026-10-16", "min_days": 252}})
    assert "앞으로 토너먼트 v2" in shadows and "앞으로 토너먼트 v3" in shadows


def test_engine_audit_v3_check(tmp_path, monkeypatch):
    from core import engine_audit as ea

    led = tmp_path / "l.jsonl"
    monkeypatch.setattr(ft3, "LEDGER", led)
    monkeypatch.setattr(ft3, "STATUS", tmp_path / "status.json")
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert ea.check_forward_tournament_v3(now)["status"] == ea.OK
    assert ea.check_forward_tournament_v3(datetime(2026, 11, 30, tzinfo=timezone.utc))["status"] == ea.WARN
    _rec(led, "2026-10-16")
    chk = ea.check_forward_tournament_v3(now)
    assert chk["status"] == ea.OK and "1일 기록" in chk["detail"]
    assert ea.check_forward_tournament_v3(datetime(2026, 10, 30, tzinfo=timezone.utc))["status"] == ea.WARN
    assert any(name == "앞으로 토너먼트 v3" for name, _ in ea.CHECKS)


def test_v3_failure_isolated_from_v1_v2(tmp_path, monkeypatch):
    from core import forward_tournament as ft
    from core import forward_tournament_v2 as ft2
    from core import process_registry, rnd_topics
    from scheduler import run_scheduler

    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "toggles.json")
    monkeypatch.setattr(rnd_topics, "is_on", lambda key: True)
    calls, failures = [], []
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda job, msg: failures.append((job, msg)))
    monkeypatch.setattr(ft, "record", lambda *a, **k: calls.append("v1") or {"recorded": True})
    monkeypatch.setattr(ft2, "record", lambda *a, **k: calls.append("v2") or {"recorded": True, "errors": {}})
    monkeypatch.setattr(ft2, "refresh_status", lambda *a, **k: {})
    monkeypatch.setattr(ft3, "refresh_status", lambda *a, **k: {})

    def boom(*a, **k):
        raise ValueError("broke")

    monkeypatch.setattr(ft3, "record", boom)
    run_scheduler.forward_tournament_record_job()
    assert calls == ["v1", "v2"] and failures == [("forward_tournament_v3_record", "ValueError: broke")]

    # v1·v2 가 실패해도 v3 는 기록된다
    calls.clear()
    failures.clear()
    monkeypatch.setattr(ft, "record", boom)
    monkeypatch.setattr(ft2, "record", boom)
    monkeypatch.setattr(ft3, "record", lambda *a, **k: calls.append("v3") or {"recorded": True, "errors": {}})
    run_scheduler.forward_tournament_record_job()
    assert calls == ["v3"]
    assert [f[0] for f in failures] == ["forward_tournament_record", "forward_tournament_v2_record"]

    # v3 새틀라이트 선정 실패는 v3 키로만 알림
    failures.clear()
    monkeypatch.setattr(ft, "record", lambda *a, **k: {"recorded": True})
    monkeypatch.setattr(ft2, "record", lambda *a, **k: {"recorded": True, "errors": {}})
    monkeypatch.setattr(ft3, "record", lambda *a, **k: {"recorded": True, "errors": {"ST_C": "RuntimeError: x"}})
    run_scheduler.forward_tournament_record_job()
    assert failures == [("forward_tournament_v3_record", "ST_C RuntimeError: x")]


def test_sc2vt20_vol_scaling_math_cap_and_bil_remainder():
    assert ft3.vol_exposure([0.01] * 125) == (1.0, None)  # 126일 전에는 1
    rng = np.random.default_rng(1)
    hi = list(rng.normal(0, 0.02, 200))  # 연 약 32% → 노출 < 1
    e, vol = ft3.vol_exposure(hi)
    exp_vol = float(pd.Series(hi[-126:]).std(ddof=1)) * np.sqrt(252)  # 마지막 126개만
    assert vol == pytest.approx(exp_vol) and e == pytest.approx(0.20 / exp_vol) and e < 1
    lo = list(rng.normal(0, 0.003, 130))
    assert ft3.vol_exposure(lo)[0] == 1.0  # 상한 1
    assert ft3.vt_inner({"XLK": 0.5, "XLE": 0.5}, 0.6) == pytest.approx({"XLK": 0.3, "XLE": 0.3, "BIL": 0.4})
    assert ft3.vt_inner({"XLK": 0.5, "XLE": 0.5}, 1.0) == {"XLK": 0.5, "XLE": 0.5}


def test_sc2vt20_prior_only_window_in_ledger(tmp_path, monkeypatch):
    led = tmp_path / "l.jsonl"
    seen = []
    orig = ft3.vol_exposure
    monkeypatch.setattr(ft3, "vol_exposure", lambda d: seen.append(list(d)) or orig(d))
    for end in ("2026-10-16", "2026-10-30", "2026-11-02"):
        _rec(led, end)
    r0, r1, r2 = ft3.load_ledger(led)
    assert r0["weights"]["SC2VT20"] == pytest.approx(r0["weights"]["SC2"])  # 기록 부족 → 노출 1
    assert len(seen) == 2 and seen[0] == []  # 시작일, 11-02 결정일에만 계산
    assert [d for d, _ in r2["sc2_rets"]] == ["2026-11-02"]
    assert len(seen[1]) == len(r1["sc2_rets"])  # 결정일 당일 수익은 빠짐
    assert r2["components"]["sc2vt"]["month"] == "2026-11" and r2["trades"]["SC2VT20"] == ["sleeve:secvt"]
