"""코인 추세 슬리브 앞으로 기록(core/crypto_shadow.py) — 신호, 수정 불가 원장, 기록된 상태로만 평가, 판정 대기."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from core import crypto_shadow as cx


def _px(trend: float, n: int = 200, end: str = "2026-10-05"):
    idx = pd.date_range(end=end, periods=n, freq="D")
    c = 100 * np.exp(np.cumsum(np.full(n, trend)))
    return pd.DataFrame({"Close": c}, index=idx)


def test_signal_state_above_and_below_ema():
    st = cx.signal_state({"BTC-USD": _px(0.01), "ETH-USD": _px(-0.01)})
    assert st["BTC-USD"]["on"] is True and st["ETH-USD"]["on"] is False
    assert cx.signal_state({"BTC-USD": _px(0.01, n=30)})["BTC-USD"]["on"] is None  # 이력 부족


def test_record_is_append_only(tmp_path):
    led = tmp_path / "l.jsonl"
    fn = lambda t: _px(0.01 if t == "BTC-USD" else -0.01)  # noqa: E731
    first = cx.record(path=led, price_fn=fn, now=datetime(2026, 10, 5, 15, 37, tzinfo=timezone.utc))
    again = cx.record(path=led, price_fn=lambda t: _px(-0.02), now=datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc))
    assert first["recorded"] and not again["recorded"] and again["reason"] == "이미 기록됨"
    rows = cx.load_ledger(led)
    assert len(rows) == 1 and rows[0]["assets"]["BTC-USD"]["on"] is True


def test_evaluate_uses_recorded_states_and_waits_for_12_months():
    idx = pd.bdate_range("2026-10-06", periods=300)
    rows = [{"date": d.date().isoformat(), "assets": {"BTC-USD": {"on": True}, "ETH-USD": {"on": False}}} for d in idx]
    coins = pd.DataFrame({"BTC-USD": 0.002, "ETH-USD": -0.05}, index=idx)
    core = pd.Series(0.0003, index=idx)
    cash = pd.Series(0.0001, index=idx)
    early = cx.evaluate(rows[:50], coins, core, cash)
    assert early["verdict"].startswith("판정 전")
    full = cx.evaluate(rows, coins, core, cash)
    assert full["days"] >= cx.MIN_DAYS and full["cumulative_active"] > 0
    # ETH 는 기록상 '보유 안 함'이라 큰 하락을 받지 않는다(다시 계산하지 않고 기록대로)
    assert full["sleeve_cumulative"] > 0
    rng = np.random.default_rng(0)
    full2 = cx.evaluate(rows, pd.DataFrame({"BTC-USD": rng.normal(0, 0.04, len(idx)), "ETH-USD": 0.0}, index=idx), core, cash)
    assert full2["verdict"] in ("PASS", "FAIL")


def test_job_registered():
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    job = SCHEDULED_JOBS_BY_ID["crypto_shadow_record"]
    assert (job.cron["hour"], job.cron["minute"]) == (0, 37)
    assert PROCESS_REGISTRY["crypto_shadow_record"]["default_enabled"] is True
