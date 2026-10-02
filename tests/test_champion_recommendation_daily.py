"""매일 09:01 KST '✅ 지금 할 일' 자동 재추천 잡(champion_recommendation_daily) 테스트.

네트워크 없음: 계산(compute_recommendation)과 텔레그램 전송을 가짜로 바꿔 끼운다. 확인하는 것:
  - 스케줄 표·레지스트리·main() 에 09:01 Asia/Seoul(09:00 은 대회 마감 알림 자리), 켜고 끌 수 있는 키로 등록됐는가(주문 잡이 아님)
  - 잡이 버튼과 같은 계산(오늘 날짜, 사이징 equal)을 한 번 부르고 요약 1건만 보내는가
  - 계산 실패·VM 여유 없음·전송 실패가 실패로 기록되고 예외를 밖으로 내지 않는가
  - 요약 문구: 목표 비중(코어·BIL·새틀라이트·현금), 직전 추천 대비 변화, 다음 확인일, '주문이 아님', 15줄 이하
"""

from datetime import date

import pytest

import core.champion_strategy as cs
from core import champion_recommendation as cr
from core import process_registry
from core import telegram_notify
from core.job_schedule import SCHEDULED_JOBS_BY_ID
from scheduler import run_scheduler
from tests.test_champion_recommendation import _compute, _core_result, _today_pick

JOB = "champion_recommendation_daily"


def _rec(as_of="2026-10-02", top4=("DBC", "XLE", "XLK", "XLV"), picks=("CAT", "GEV", "JNJ"), status="above",
         action=None):
    core = _core_result(top4=top4, status=status)
    weights = dict(core["per_ticker_weights"])
    if status == "below":  # 시장필터 축소분은 단기국채(BIL)로 간다(compute_core_recommendation 과 같은 형태)
        weights[cs.CORE_CASH_ETF] = cs.CORE_WEIGHT * 0.5
    return {
        "params": cr.cache_params(as_of),
        "as_of": as_of,
        "computed_at": f"{as_of}T00:05:00+00:00",
        "core": {"top4": list(top4), "per_ticker_weights": weights, "market_filter_status": status},
        "satellite": {"today": {"picks": list(picks),
                                "sleeve_weights": {t: 1 / len(picks) for t in picks} if picks else {}}},
        "action": action or {"has_changes": False, "headline": "바꿀 것 없음"},
        "from_cache": False,
    }


@pytest.fixture()
def job_env(monkeypatch, tmp_path):
    """토글 상태·캐시 폴더 격리, 가짜 계산·전송·실패 기록, VM 여유 있음."""
    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "process_toggles.json")
    monkeypatch.setattr(cr, "CACHE_DIR", tmp_path / "cache")
    calls = {"compute": [], "sent": [], "failures": []}

    def fake_compute(as_of=None, **kw):
        calls["compute"].append((as_of, kw))
        return _rec(as_of=as_of.isoformat())

    monkeypatch.setattr(cr, "compute_recommendation", fake_compute)
    monkeypatch.setattr(telegram_notify, "send_message", lambda text: calls["sent"].append(text) or True)
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda job_id, err: calls["failures"].append((job_id, str(err))))
    monkeypatch.setattr(run_scheduler, "has_headroom", lambda: True)
    monkeypatch.setattr(run_scheduler, "CHAMPION_REC_HEADROOM_WAIT_S", 0)
    monkeypatch.setattr(run_scheduler, "CHAMPION_REC_HEADROOM_POLL_S", 0)
    return calls


# ============================================================================================
# 등록
# ============================================================================================

def test_job_is_registered_at_0900_kst_with_a_toggle_key():
    job = SCHEDULED_JOBS_BY_ID[JOB]
    assert job.process_key == JOB
    assert job.cron == {"hour": 9, "minute": 1, "timezone": "Asia/Seoul"}
    entry = process_registry.PROCESS_REGISTRY[JOB]
    assert entry["default_enabled"] is True
    assert not entry.get("places_orders")  # 계산·알림만 — 주문 잡이 아니다
    assert "09:01 KST" in entry["description"] and "주문 없음" in entry["description"]


def test_main_registers_the_job_once_without_overlap(monkeypatch):
    added = []

    class _Fake:
        def add_job(self, func, trigger=None, id=None, **kw):
            added.append((func, trigger, id, kw))

        def get_jobs(self):
            return []

        def add_listener(self, *a, **k):
            return None

        def start(self):
            return None

    monkeypatch.setattr(run_scheduler, "BlockingScheduler", lambda *a, **k: _Fake())
    monkeypatch.setattr(run_scheduler, "init_db", lambda: None)
    monkeypatch.setattr(run_scheduler, "attach_job_run_listener", lambda scheduler: None)
    monkeypatch.setattr(run_scheduler, "record_registered_jobs", lambda ids: None)
    run_scheduler.main()

    mine = [a for a in added if a[2] == JOB]
    assert len(mine) == 1
    func, trigger, _, kw = mine[0]
    assert func is run_scheduler.champion_recommendation_daily_job
    assert str(trigger.timezone) == "Asia/Seoul"
    fields = {f.name: str(f) for f in trigger.fields}
    assert fields["hour"] == "9" and fields["minute"] == "1"
    assert kw.get("max_instances") == 1


# ============================================================================================
# 잡 함수
# ============================================================================================

def test_job_computes_like_the_button_and_sends_one_message(job_env):
    run_scheduler.champion_recommendation_daily_job()

    assert len(job_env["compute"]) == 1
    as_of, kw = job_env["compute"][0]
    assert as_of == date.today()  # 화면 버튼·freshness() 와 같은 서버 날짜
    assert kw["sizing_method"] == "equal"  # 화면 사이징 기본값
    assert len(job_env["sent"]) == 1
    text = job_env["sent"][0]
    assert text.startswith(cr.DAILY_TITLE)
    assert "주문이 아닙니다" in text and "DBC" in text and "CAT" in text
    assert job_env["failures"] == []


def test_job_skips_when_disabled(job_env):
    process_registry.set_enabled(JOB, False)
    run_scheduler.champion_recommendation_daily_job()
    assert job_env["compute"] == [] and job_env["sent"] == [] and job_env["failures"] == []


def test_compute_failure_is_reported_and_does_not_raise(job_env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("price feed down")

    monkeypatch.setattr(cr, "compute_recommendation", boom)
    run_scheduler.champion_recommendation_daily_job()  # 예외가 밖으로 나오면 실패

    assert job_env["failures"] == [(JOB, "RuntimeError: price feed down")]
    assert len(job_env["sent"]) == 1
    assert "자동 재추천 실패" in job_env["sent"][0] and "price feed down" in job_env["sent"][0]
    assert "다시 추천" in job_env["sent"][0]  # 버튼으로 직접 계산하라는 안내


def test_failure_notice_error_never_escapes(job_env, monkeypatch):
    monkeypatch.setattr(cr, "compute_recommendation", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))

    def send_raises(text):
        raise OSError("telegram down")

    monkeypatch.setattr(telegram_notify, "send_message", send_raises)
    run_scheduler.champion_recommendation_daily_job()
    assert job_env["failures"] == [(JOB, "ValueError: x")]


def test_no_headroom_skips_the_heavy_compute_and_reports(job_env, monkeypatch):
    checks = []
    monkeypatch.setattr(run_scheduler, "has_headroom", lambda: checks.append(1) or False)
    monkeypatch.setattr(run_scheduler, "CHAMPION_REC_HEADROOM_WAIT_S", 2)
    monkeypatch.setattr(run_scheduler, "CHAMPION_REC_HEADROOM_POLL_S", 1)
    slept = []
    import time

    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    run_scheduler.champion_recommendation_daily_job()

    assert job_env["compute"] == []
    assert len(checks) == 3 and slept == [1, 1]  # 0·1·2초에 확인하고 포기
    assert len(job_env["failures"]) == 1 and "VM 여유" in job_env["failures"][0][1]
    assert len(job_env["sent"]) == 1 and "자동 재추천 실패" in job_env["sent"][0]


def test_headroom_that_frees_up_lets_the_job_run(job_env, monkeypatch):
    answers = iter([False, True])
    monkeypatch.setattr(run_scheduler, "has_headroom", lambda: next(answers))
    monkeypatch.setattr(run_scheduler, "CHAMPION_REC_HEADROOM_WAIT_S", 5)
    monkeypatch.setattr(run_scheduler, "CHAMPION_REC_HEADROOM_POLL_S", 1)
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)
    run_scheduler.champion_recommendation_daily_job()
    assert len(job_env["compute"]) == 1 and len(job_env["sent"]) == 1 and job_env["failures"] == []


def test_send_failure_is_recorded_but_not_when_telegram_is_unconfigured(job_env, monkeypatch):
    monkeypatch.setattr(telegram_notify, "send_message", lambda text: False)
    run_scheduler.champion_recommendation_daily_job()
    assert job_env["failures"] == [(JOB, "재추천은 저장됐지만 텔레그램 요약 전송 실패")]

    job_env["failures"].clear()
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: False)
    run_scheduler.champion_recommendation_daily_job()
    assert job_env["failures"] == []


# ============================================================================================
# 계산 → 캐시 → 화면이 '오늘 계산한 추천'으로 읽는다 (실제 compute_recommendation, 가짜 입력)
# ============================================================================================

def test_run_daily_refresh_fills_the_cache_the_page_reads_and_compares_with_previous_day(tmp_path, monkeypatch):
    sent = []
    stamps = iter(f"2026-10-0{d}T00:0{m}:00+00:00" for d, m in ((1, 1), (2, 1), (2, 2), (2, 3)))
    monkeypatch.setattr(cr, "_now_iso", lambda: next(stamps))  # 실제로는 하루 간격 — 같은 초에 겹치지 않게

    def compute(as_of, sizing_method="equal", cache_dir=None):
        top4 = ("XLK", "GLD", "XLE", "TLT") if as_of == date(2026, 10, 1) else ("XLK", "GLD", "XLE", "XLV")
        return _compute(cache_dir, as_of=as_of, core_fn=lambda sizing_method="equal": _core_result(top4=top4))

    first = cr.run_daily_refresh(date(2026, 10, 1), notify=sent.append, cache_dir=tmp_path, compute_fn=compute)
    assert first["compared_with"] is None and "비교할 이전 결과 없음" in first["message"]

    second = cr.run_daily_refresh(date(2026, 10, 2), notify=lambda t: sent.append(t) or True,
                                  cache_dir=tmp_path, compute_fn=compute)
    assert second["sent"] is True and second["compared_with"] == "2026-10-01"
    assert "직전 추천(2026-10-01) 대비: 코어 TLT → XLV" in second["message"]
    assert len(sent) == 2

    latest = cr.load_latest_cached(tmp_path)  # 화면(app/pages/11_챔피언_전략.py)이 읽는 함수
    assert latest["as_of"] == "2026-10-02"
    assert cr.freshness(latest, today=date(2026, 10, 2))["level"] == "fresh"

    # 같은 날 다시 돌면 캐시를 쓰고, 비교 대상은 여전히 전날 결과다(같은 날 결과와 비교하지 않음)
    third = cr.run_daily_refresh(date(2026, 10, 2), notify=None, cache_dir=tmp_path, compute_fn=compute)
    assert third["from_cache"] is True and third["compared_with"] == "2026-10-01" and third["sent"] is False


def test_notify_exception_does_not_undo_the_saved_recommendation(tmp_path):
    def compute(as_of, sizing_method="equal", cache_dir=None):
        return _compute(cache_dir, as_of=as_of)

    def boom(_text):
        raise OSError("network")

    res = cr.run_daily_refresh(date(2026, 10, 2), notify=boom, cache_dir=tmp_path, compute_fn=compute)
    assert res["sent"] is False
    assert cr.load_latest_cached(tmp_path)["as_of"] == "2026-10-02"


# ============================================================================================
# 요약 문구
# ============================================================================================

def test_message_lists_target_weights_filter_and_next_dates():
    text = cr.daily_todo_message(_rec(), previous=None, today=date(2026, 10, 2))
    lines = text.splitlines()
    assert len(lines) <= 15
    assert lines[0] == f"{cr.DAILY_TITLE} — 기준일 2026-10-02"
    assert "오늘 계산한 추천입니다" in lines[1] and "주문이 아닙니다" in lines[1]
    per_core = cs.CORE_WEIGHT / 4 * 100
    per_sat = cs.SATELLITE_WEIGHT / 3 * 100
    assert f"· 코어: DBC {per_core:.1f}%, XLE {per_core:.1f}%, XLK {per_core:.1f}%, XLV {per_core:.1f}%" in lines
    assert f"· 새틀라이트: CAT {per_sat:.1f}%, GEV {per_sat:.1f}%, JNJ {per_sat:.1f}%" in lines
    assert not any(line.startswith("· 현금") or "BIL" in line for line in lines)  # 다 투자하면 현금·BIL 줄 없음
    assert "SPY 200일선 위" in text
    assert "직전 추천 대비: 비교할 이전 결과 없음" in lines
    assert "다음 확인: 코어 2026-11-02(매달 첫 거래일) · 새틀라이트는 오늘 사면 2027-04-02까지 보유" in lines


def test_message_shows_bil_cash_and_filter_below():
    text = cr.daily_todo_message(_rec(status="below", picks=()), today=date(2026, 10, 2))
    assert f"· 코어 남는 몫(단기국채): BIL {cs.CORE_WEIGHT * 50:.1f}%" in text
    assert "· 새틀라이트: 없음(그 몫은 현금)" in text
    assert f"· 현금: {cs.SATELLITE_WEIGHT * 100:.1f}%" in text
    assert "200일선 아래" in text


def test_message_unknown_filter_says_hold_new_orders():
    text = cr.daily_todo_message(_rec(status="unknown"), today=date(2026, 10, 2))
    assert "신규 주문 보류" in text


def test_message_reports_changes_versus_previous_and_saved_signal():
    prev = _rec(as_of="2026-10-01", top4=("DBC", "XLE", "XLK", "TLT"), picks=("CAT", "GEV", "MRK"), status="below")
    now = _rec(action={"has_changes": True, "headline": "코어 1개 교체 필요(TLT→XLV)"})
    text = cr.daily_todo_message(now, previous=prev, today=date(2026, 10, 2))
    assert ("직전 추천(2026-10-01) 대비: 코어 TLT → XLV · 새틀라이트 MRK → JNJ · 시장필터 200일선 아래 → 200일선 위"
            in text)
    assert "어젯밤 저장 신호 대비: 코어 1개 교체 필요(TLT→XLV)" in text
    same = cr.daily_todo_message(_rec(), previous=_rec(as_of="2026-10-01"), today=date(2026, 10, 2))
    assert "직전 추천(2026-10-01) 대비: 종목 변화 없음" in same
    assert "어젯밤 저장 신호 대비" not in same


def test_latest_cached_before_skips_same_day_and_other_strategy_versions(tmp_path, monkeypatch):
    for as_of in ("2026-09-30", "2026-10-01", "2026-10-02"):
        rec = _rec(as_of=as_of)
        cr._atomic_write_json(cr.cache_path(rec["params"], tmp_path), rec)
    assert cr.latest_cached_before(date(2026, 10, 2), tmp_path)["as_of"] == "2026-10-01"
    assert cr.latest_cached_before(date(2026, 9, 30), tmp_path) is None
    monkeypatch.setattr(cs, "CHAMPION_STRATEGY_VERSION", "other-version")
    assert cr.latest_cached_before(date(2026, 10, 2), tmp_path) is None  # 전략 버전이 바뀌면 비교하지 않는다


def test_failure_message_is_short_and_points_to_the_button():
    text = cr.daily_failure_message("x" * 500)
    assert len(text.splitlines()) == 3 and "x" * 201 not in text
    assert "🔄 지금 기준으로 다시 추천" in text


def test_today_pick_helper_is_compatible():  # 위 통합 테스트가 기대는 합성 입력 형태가 바뀌면 여기서 먼저 깨진다
    assert _today_pick()["picks"] == ["CCC", "DDD"]
