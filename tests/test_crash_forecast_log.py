"""scripts/crash_forecast_log.py — 급락 예측 기록기(가짜 자료, 네트워크 없음)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("crash_forecast_log", ROOT / "scripts" / "crash_forecast_log.py")
cfl = importlib.util.module_from_spec(_spec)
sys.modules["crash_forecast_log"] = cfl
_spec.loader.exec_module(cfl)

CRASH_START = "2026-10-01"


def fake_spy(end: str, drop_days: int = 20, drop: float = -0.25) -> pd.Series:
    """2026-10-01 부터 drop_days 동안 drop 만큼 빠지고 그 뒤 평평한 SPY."""
    idx = pd.bdate_range("2026-01-01", end)
    r = np.zeros(len(idx))
    k = int(idx.searchsorted(pd.Timestamp(CRASH_START)))
    r[k:k + drop_days] = (1 + drop) ** (1 / drop_days) - 1
    return pd.Series(100 * np.cumprod(1 + r), index=idx)


def ctx_until(end: str):
    return cfl.build(smoke=True, spy=fake_spy(end))


def at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def test_live_data_splices_spy_after_french_end():
    us = cfl.lab().load_us(True)
    data = cfl.live_data(us, fake_spy("2026-12-31"))
    L, last = data["L"], us["L"].index[-1]
    assert L.index.is_monotonic_increasing and L.index.is_unique
    assert L.loc[:last].equals(us["L"])
    assert data["french_last"] == last and data["spy_last"] == pd.Timestamp("2026-12-31")
    assert abs(L.iloc[-1] / L.loc[last] - 0.75) < 1e-9
    assert len(data["rf"]) == len(L) and len(data["F"]) == len(L)
    assert cfl.live_data(us, None)["L"].equals(us["L"])


def test_new_rows_trigger_then_landmarks_and_idempotent():
    ctx, _ = ctx_until("2026-10-30")
    rows = cfl.new_rows(ctx, [], now=at("2026-10-30"), log_start="2026-09-01")
    assert [r["landmark"] for r in rows] == [0]
    r0 = rows[0]
    assert r0["dd0"] <= -0.15 and r0["asof"] == r0["t0"] and set(r0["models"]) == {"BASE"}
    assert set(r0["models"]["BASE"]["depth"]) == {"0.1", "0.25", "0.5", "0.75", "0.9"}
    assert set(r0["models"]["BASE"]["recovery"]) == {"252", "504", "756", "1260"}
    assert cfl.new_rows(ctx, rows, now=at("2026-10-30"), log_start="2026-09-01") == []

    ctx2, _ = ctx_until("2027-06-30")
    more = cfl.new_rows(ctx2, rows, now=at("2027-06-30"), log_start="2026-09-01")
    assert [r["landmark"] for r in more] == [21, 63, 126]
    assert all(r["t0"] == r0["t0"] and set(r["models"]) == {"BASE", "LM"} for r in more)
    assert more[0]["late"] is True
    lm = more[1]["models"]["LM"]["depth"]
    assert lm["0.1"] <= lm["0.5"] <= lm["0.9"] <= more[1]["low_so_far"] + 1e-12


def test_prediction_does_not_use_later_data():
    """발생일 예측은 그 뒤 자료가 얼마나 더 있든 같다."""
    a = cfl.new_rows(ctx_until("2026-10-30")[0], [], now=at("2026-10-30"), log_start="2026-09-01")[0]
    b = cfl.new_rows(ctx_until("2027-06-30")[0], [], now=at("2026-10-30"), log_start="2026-09-01")[0]
    assert a["t0"] == b["t0"] and a["models"] == b["models"] and a["dd0"] == b["dd0"]


def test_log_start_and_shifted_trigger_date():
    ctx, _ = ctx_until("2026-10-30")
    assert cfl.new_rows(ctx, [], now=at("2026-10-30"), log_start="2027-01-01") == []
    row = cfl.new_rows(ctx, [], now=at("2026-10-30"), log_start="2026-09-01")[0]
    shifted = dict(row, t0=str((pd.Timestamp(row["t0"]) + pd.Timedelta(3, unit="D")).date()))
    assert cfl.new_rows(ctx, [shifted], now=at("2026-10-30"), log_start="2026-09-01") == []


def test_append_read_report_roundtrip(tmp_path):
    ctx, _ = ctx_until("2027-06-30")
    rows = cfl.new_rows(ctx, [], now=at("2027-06-30"), log_start="2026-09-01")
    path = tmp_path / "log" / "forecasts.jsonl"
    cfl.append_log(rows[:1], path)
    cfl.append_log(rows[1:], path)
    back = cfl.read_log(path)
    assert back == rows and cfl.read_log(tmp_path / "none.jsonl") == []
    o = cfl.outcome(ctx, back[0])
    assert o["recovered"] is False and o["low"] <= rows[0]["dd0"] and o["low"] == rows[-1]["low_so_far"] and o["days"] > 126
    text = cfl.report(ctx, back)
    assert "기준선" in text and "갱신 모델" in text and "미회복" in text
    assert "기록이 아직 없습니다" in cfl.report(ctx, [])


def test_job_is_registered():
    from core.job_schedule import SCHEDULED_JOBS_BY_ID
    from core.process_registry import PROCESS_REGISTRY

    assert SCHEDULED_JOBS_BY_ID["crash_forecast_log"].cron["day_of_week"] == "tue-sat"
    assert PROCESS_REGISTRY["crash_forecast_log"]["default_enabled"] is True
