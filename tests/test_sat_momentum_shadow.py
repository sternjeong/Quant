"""모멘텀 새틀라이트 앞으로 기록(core/sat_momentum_shadow.py) — 점수·선정, 달마다 한 줄(수정 불가), 기록된 종목으로만 평가, 판정 대기."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from core import sat_momentum_shadow as sm

DAYS = pd.bdate_range("2025-06-02", "2029-03-30")


def _series(drift: float, idx=DAYS) -> pd.Series:
    return pd.Series(100 * np.exp(drift * np.arange(len(idx))), index=idx)


def _universe(n: int = 320) -> dict[str, pd.Series]:
    # T000 이 가장 강하고 번호가 클수록 약하다
    return {f"T{i:03d}": _series(0.002 - i * 0.00001) for i in range(n)}


def _price_fn(series: dict[str, pd.Series]):
    def fn(t, start, end):
        s = series.get(t)
        if s is None:
            raise KeyError(t)
        s = s.loc[start:end]
        return pd.DataFrame({"Close": s, "Adj Close": s})
    return fn


def test_scores_and_pick_order():
    idx = DAYS[:260]
    closes = pd.DataFrame({"A": _series(0.003, idx), "B": _series(0.001, idx), "C": _series(-0.001, idx)})
    closes.loc[closes.index[-1], "C"] = np.nan  # 형성일 가격이 없는 종목은 빠진다
    sc = sm.scores(closes)
    assert sm.pick(sc["MOM6"], 2) == ["A", "B"] and "C" not in sc["MOM6"]
    assert sm.pick(pd.Series({"Y": 0.1, "X": 0.1, "Z": 0.0}), 2) == ["X", "Y"]  # 동점은 티커순


def test_record_once_per_month_and_needs_enough_names(tmp_path):
    led = tmp_path / "c.jsonl"
    uni = {**_universe(), "SPY": _series(0.0005)}
    members = lambda d: [t for t in uni if t != "SPY"]  # noqa: E731
    now = datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc)  # 미 동부 11-20 18:00 → 11-20 완성
    first = sm.record(path=led, price_fn=_price_fn(uni), members_fn=members, now=now)
    assert first["recorded"] and first["formed_on"] == "2026-11-20"
    assert first["picks"]["MOM6"] == ["T000", "T001", "T002", "T003", "T004"]
    again = sm.record(path=led, price_fn=_price_fn(uni), members_fn=members, now=datetime(2026, 11, 25, 23, 0, tzinfo=timezone.utc))
    assert not again["recorded"] and "이미" in again["reason"]
    few = sm.record(path=tmp_path / "f.jsonl", price_fn=_price_fn(uni), members_fn=lambda d: ["T000", "T001"], now=now)
    assert not few["recorded"] and "내일 다시" in few["reason"]
    assert len(sm.load_ledger(led)) == 1


def test_record_waits_for_settled_close(tmp_path):
    uni = {**_universe(), "SPY": _series(0.0005)}
    # 미 동부 2026-12-01 10:00 — 12-01 봉은 미완성이라 11-30 로 형성, 그달은 11월
    res = sm.record(path=tmp_path / "c.jsonl", price_fn=_price_fn(uni), members_fn=lambda d: list(_universe()),
                    now=datetime(2026, 12, 1, 15, 0, tzinfo=timezone.utc))
    assert res["formed_on"] == "2026-11-30" and res["month"] == "2026-11"


def test_evaluate_waits_then_judges_mean_and_median():
    spy = _series(0.0003)
    rows = []
    for m in sm.JUDGED_MONTHS:
        formed = DAYS[DAYS.strftime("%Y-%m") == m][0]
        rows.append({"month": m, "formed_on": formed.date().isoformat(),
                     "arms": {"MOM6": {"picks": ["W"]}, "MOM12_1": {"picks": ["L"]}}})
    closes = {"W": _series(0.0008), "L": _series(-0.0005)}
    early = sm.evaluate(rows[:3], closes, spy.loc[:"2027-03-01"])
    assert early["verdict"].startswith("판정 전")
    assert early["arms"]["MOM6"]["interim_mean_excess_open"] > 0
    full = sm.evaluate(rows, closes, spy)
    a = full["arms"]["MOM6"]
    assert a["judged_complete"] == 12 and full["verdict"] == "PASS" and a["mean_excess"] >= sm.TARGET
    assert full["arms"]["MOM12_1"]["verdict"].startswith("참고")
    weak = sm.evaluate(rows, {"W": _series(0.0004), "L": closes["L"]}, spy)  # 초과 연 2~3%p → 목표 미달
    assert weak["verdict"] == "FAIL"
    assert "PASS" in sm.summary_line(full) and "판정 전" in sm.summary_line(early)


def test_cohort_uses_last_price_after_delisting():
    spy = _series(0.0)
    s = _series(0.001)
    gone = s.loc[:"2027-03-01"]
    row = {"month": "2026-11", "formed_on": "2026-11-20", "arms": {"MOM6": {"picks": ["G"]}}}
    c = sm.cohort_result(row, "MOM6", {"G": gone}, spy)
    assert c["complete"] and abs(c["return"] - (gone.iloc[-1] / gone.loc["2026-11-23"] - 1 - 0.0016)) < 1e-9


def test_job_registered():
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    job = SCHEDULED_JOBS_BY_ID["sat_momentum_shadow_record"]
    assert (job.cron["hour"], job.cron["minute"]) == (7, 50)
    assert PROCESS_REGISTRY["sat_momentum_shadow_record"]["default_enabled"] is True
