"""새벽 미리 계산(core/dawn_precompute.py) — 등록·한 단계 실패가 나머지를 막지 않음·화면이 읽는 저장/불러오기."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from core import dawn_precompute as dp
from core.job_schedule import SCHEDULED_JOBS_BY_ID
from core.process_registry import PROCESS_REGISTRY


def test_registered_at_0640_kst_and_enabled():
    job = SCHEDULED_JOBS_BY_ID["dawn_precompute"]
    assert job.cron == {"hour": 6, "minute": 40, "timezone": "Asia/Seoul"}
    assert PROCESS_REGISTRY["dawn_precompute"]["default_enabled"] is True
    assert dp.schedule_label() == "06:40"


def test_as_of_is_korean_date():
    # 06:40 KST 는 UTC 로 전날 21:40 — 기준일은 한국 날짜여야 막 끝난 미국 장 봉이 들어간다
    assert dp.kst_today(datetime(2026, 10, 4, 21, 40, tzinfo=timezone.utc)) == date(2026, 10, 5)
    assert dp.default_backtest_start(date(2028, 2, 29)) == date(2025, 2, 28)


def test_one_failing_step_does_not_stop_the_others_and_notifies_once(tmp_path):
    calls, sent = [], []

    def ok(as_of, cache_dir):
        calls.append(as_of)
        return "ok"

    def boom(as_of, cache_dir):
        raise RuntimeError("down")

    steps = (("a", "A", ok), ("b", "B", boom), ("c", "C", ok))
    s = dp.run_all(date(2026, 10, 5), steps=steps, notify=lambda m: sent.append(m) or True, cache_dir=tmp_path)
    assert len(calls) == 2 and s["failed"] == ["b"] and s["status"] != "ok"
    assert len(sent) == 1 and s["notified"]
    assert dp.load_status(tmp_path)  # 실행 기록이 남는다


def test_all_ok_is_silent(tmp_path):
    sent = []
    s = dp.run_all(date(2026, 10, 5), steps=(("a", "A", lambda d, c: "ok"),), notify=sent.append, cache_dir=tmp_path)
    assert not s["failed"] and not sent


def test_saved_result_is_loaded_with_frames_and_age(tmp_path):
    params = dp.result_params(dp.KIND_CHAMPION_BACKTEST, date(2026, 10, 3))
    df = pd.DataFrame({"x": [1.0, 2.0]}, index=pd.to_datetime(["2026-10-01", "2026-10-02"]))
    dp.save_result(dp.KIND_CHAMPION_BACKTEST, params, {"equity": df, "n": 3}, cache_dir=tmp_path)
    got = dp.load_latest(dp.KIND_CHAMPION_BACKTEST, today=date(2026, 10, 5), cache_dir=tmp_path)
    assert got is not None and got["age_days"] == 2 and not got["is_today"]
    assert got["result"]["n"] == 3
    pd.testing.assert_frame_equal(got["result"]["equity"], df, check_freq=False)
    assert "2일 전" in dp.loaded_caption(got)
    # 다른 사이징이나 너무 오래된 결과는 보여 주지 않는다
    assert dp.load_latest(dp.KIND_CHAMPION_BACKTEST, sizing_method="inverse_vol", today=date(2026, 10, 5), cache_dir=tmp_path) is None
    assert dp.load_latest(dp.KIND_CHAMPION_BACKTEST, today=date(2026, 10, 30), cache_dir=tmp_path) is None
