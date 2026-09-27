"""core/champion_tracking.py — 기대값은 손계산 합성 데이터. 네트워크·실제 DB·실제 텔레그램 없음."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from core import champion_strategy as cs
from core import champion_tracking as ct
from core import process_registry


# ---- 합성 데이터 도우미 --------------------------------------------------------------------------------------

def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


LIVE_START = date(2026, 1, 5)  # 월요일


def synthetic_backtest(n_days: int = 200, spike_at: int = 100, spike: float = 0.10, crash_at: int = 50,
                       crash: float = -0.30) -> dict:
    """라이브 이전 200거래일: 대부분 0%, 하루 +10%, 하루 -30%. 길이 20 창 181개 = -30% 20개, +10% 20개, 0% 141개."""
    dates = weekdays(date(2025, 1, 6), n_days)
    assert dates[-1] < LIVE_START
    strat = [0.0] * n_days
    strat[spike_at] = spike
    strat[crash_at] = crash
    return {"dates": [d.isoformat() for d in dates], "strategy": strat, "spy": [0.0] * n_days,
            "tlt": [0.0] * n_days, "core_holdings": [[dates[0].isoformat(), {"AAA": 1.0}]],
            "generated_on": "2026-01-01", "strategy_version": cs.CHAMPION_STRATEGY_VERSION}


def live_setup(n_live: int, aaa_moves: dict[int, float] | None = None):
    """기준점 1일 + 라이브 n_live 거래일. AAA 는 지정한 날(1-based 라이브 인덱스)에 수익, SPY·TLT 는 평탄."""
    sessions = weekdays(LIVE_START - timedelta(days=3), n_live + 1)  # 첫 원소 = 직전 금요일(기준점)
    aaa, level = {}, 100.0
    for i, s in enumerate(sessions):
        level *= 1 + (aaa_moves or {}).get(i, 0.0)
        aaa[s] = level
    closes = {"AAA": aaa, "SPY": {s: 400.0 for s in sessions}, "TLT": {s: 90.0 for s in sessions}}
    # 원장은 매일(주말 포함) 기록된다. 첫 항목은 기준점(금요일) 장중 계산 → 월요일부터 적용
    days = (sessions[-1] - sessions[0]).days + 1
    entries = [{"entry_date": sessions[0] + timedelta(days=i + 1), "decision_date": sessions[0] + timedelta(days=i),
                "core_weights": {"AAA": 1.0}, "satellite_weights": {}, "realized_return_pct": 0.0} for i in range(days)]
    return sessions, closes, entries


# ---- 순수 계산 ----------------------------------------------------------------------------------------------

def test_rolling_windows_percentile_quantile_and_drawdown_hand_computed():
    assert ct.rolling_window_returns([0.1, -0.1, 0.2], 2) == pytest.approx([1.1 * 0.9 - 1, 0.9 * 1.2 - 1])
    assert ct.rolling_window_returns([0.1], 2) == []
    assert ct.percentile_rank([1, 2, 3, 4], 2.5) == 50.0
    assert ct.percentile_rank([1, 2, 3, 4], 2) == pytest.approx(37.5)  # 아래 1개 + 같은 값 절반
    assert ct.percentile_rank([1, 2, 3, 4], 0) == 0.0 and ct.percentile_rank([1, 2, 3, 4], 9) == 100.0
    assert ct.quantile([0, 10], 25) == pytest.approx(2.5)
    assert ct.max_drawdown([0.1, -0.5, 0.2]) == pytest.approx(-0.5)  # 1.1 → 0.55
    assert ct.max_drawdown([0.01, 0.02]) == 0.0
    ex = ct.rolling_window_excess([0.1, 0.0], [0.05, 0.0], [0.0, 0.0], 2)
    assert ex["spy"] == pytest.approx([0.05])
    assert ex["sixty_forty"] == pytest.approx([0.1 - 0.6 * 0.05])


@pytest.mark.parametrize("pct, expected", [
    (5.0, "normal"), (95.0, "normal"), (50.0, "normal"),
    (4.99, "outside"), (95.01, "outside"), (1.0, "outside"), (99.0, "outside"),
    (0.99, "deviation"), (99.01, "deviation"), (0.0, "deviation"), (100.0, "deviation"),
])
def test_classify_percentile_boundaries(pct, expected):
    assert ct.classify(20, pct, -0.01, -0.20) == expected


def test_classify_drawdown_breach_and_small_sample():
    assert ct.classify(20, 50.0, -0.31, -0.30) == "deviation"  # 백테스트 최악보다 깊음
    assert ct.classify(20, 50.0, -0.30, -0.30) == "normal"  # 같으면 넘은 것이 아님
    assert ct.classify(19, 0.0, -0.9, -0.1) == "insufficient"  # 20거래일 미만이면 판정하지 않음
    assert ct.classify(25, None, None, None) == "unavailable"
    assert ct.MIN_LIVE_SESSIONS == cs.BENCHMARK_MIN_LEDGER_DAYS == 20


# ---- 판정 전체 흐름 -------------------------------------------------------------------------------------------

def _evaluate(n_live, moves, **kw):
    sessions, closes, entries = live_setup(n_live, moves)
    return ct.evaluate(entries, kw.pop("backtest", synthetic_backtest()), closes, sessions[-1],
                       today=sessions[-1] + timedelta(days=1), **kw)


def test_normal_verdict_percentile_hand_computed():
    res = _evaluate(20, {3: 0.05})  # 라이브 20거래일 누적 +5%
    assert res["live"]["n_sessions"] == 20
    assert res["live"]["cum_return_pct"] == pytest.approx(5.0)
    cr = res["expected"]["cum_return"]
    assert cr["n_windows"] == 181
    assert cr["percentile"] == pytest.approx(round(100 * 161 / 181, 1))  # -30% 20개 + 0% 141개가 아래
    assert res["expected"]["worst_backtest_mdd_pct"] == pytest.approx(-30.0)
    assert res["verdict"] == "normal" and res["verdict_label"] == "백테스트 범위 안(정상)"
    # SPY·60/40 평탄 → 초과수익 = 누적수익, 백테스트 벤치마크도 0 이라 같은 분위
    assert res["benchmarks"]["excess_vs_spy_pct_points"] == pytest.approx(5.0)
    assert res["expected"]["excess_vs_spy"]["percentile"] == cr["percentile"]
    assert res["expected"]["excess_vs_sixty_forty"]["label"] == "백테스트 범위 안(정상)"
    assert res["same_period_backtest"]["n_sessions"] == 0  # 합성 백테스트는 라이브 기간을 덮지 않는다


def test_above_every_window_is_deviation_and_drawdown_breach_is_deviation():
    assert _evaluate(20, {3: 0.12})["verdict"] == "deviation"  # 모든 창(최대 +10%)보다 위 → 100분위
    res = _evaluate(20, {3: 0.10, 5: -0.35, 6: 0.60})  # 누적은 높지만 중간 낙폭 -35% < 백테스트 최악 -30%
    assert res["mdd_breach"] is True and res["verdict"] == "deviation"
    assert res["action_needed"] is True


def test_small_sample_shows_numbers_but_no_verdict():
    res = _evaluate(10, {3: 0.05})
    assert res["verdict"] == "insufficient" and res["verdict_label"] == "판정하기엔 이름(표본 부족)"
    assert res["expected"]["cum_return"]["percentile"] is not None  # 수치는 보여 준다
    assert "판정은 20거래일부터" in ct.format_message(res)


def test_no_backtest_is_unavailable_and_warns():
    res = _evaluate(20, {3: 0.05}, backtest=None)
    assert res["verdict"] == "unavailable"
    data = next(c for c in res["checks"] if c["name"] == "data")
    assert data["level"] == "warn" and "백테스트 계산 실패" in data["short"]


def test_weights_decided_during_a_session_do_not_earn_that_sessions_return():
    sessions, closes, _ = live_setup(3, {1: 0.05})  # 월요일(인덱스 1)에 +5%
    entries = [{"entry_date": sessions[1], "decision_date": sessions[1],  # 월요일 장중에 계산
                "core_weights": {"AAA": 1.0}, "satellite_weights": {}}]
    rows = ct.reconstruct_live_returns(entries, closes, sessions)
    assert [r["date"] for r in rows] == sessions[2:]  # 화요일부터
    assert all(r["return"] == pytest.approx(0.0) for r in rows)


def test_reconstruction_charges_backtest_costs_on_weight_changes_and_flags_missing_prices():
    sessions, closes, _ = live_setup(3)
    entries = [
        {"entry_date": sessions[0], "decision_date": sessions[0], "core_weights": {"AAA": 1.0}, "satellite_weights": {}},
        {"entry_date": sessions[1], "decision_date": sessions[1], "core_weights": {"AAA": 0.5}, "satellite_weights": {"ZZZ": 0.1}},
    ]
    rows = ct.reconstruct_live_returns(entries, closes, sessions)
    assert rows[0]["cost"] == 0.0  # 첫 비중은 이미 들고 있다고 본다
    # 코어 회전 0.5 × 3bp + 새틀라이트 회전 0.1 × 8bp
    assert rows[1]["cost"] == pytest.approx(0.5 * cs.CORE_COST_BPS_PER_SIDE / 1e4 + 0.1 * cs.SATELLITE_COST_BPS_PER_SIDE / 1e4)
    assert rows[1]["missing"] == ["ZZZ"]


# ---- 점검 ---------------------------------------------------------------------------------------------------

def test_signal_check_latest_ledger_vs_same_day_signal():
    sessions, closes, entries = live_setup(20, {3: 0.05})
    today = entries[-1]["entry_date"]
    ok = ct.evaluate(entries, synthetic_backtest(), closes, sessions[-1], today=today,
                     signal_state={"as_of": today.isoformat(), "core_top4": ["AAA"], "above_200dma": True})
    sig = next(c for c in ok["checks"] if c["name"] == "signal")
    assert sig["latest_matches_signal"] is True and sig["level"] == "ok"
    bad = ct.evaluate(entries, synthetic_backtest(), closes, sessions[-1], today=today,
                      signal_state={"as_of": today.isoformat(), "core_top4": ["BBB"], "above_200dma": True})
    sig = next(c for c in bad["checks"] if c["name"] == "signal")
    assert sig["latest_matches_signal"] is False and sig["level"] == "warn" and bad["action_needed"]


def _paper(**kw):
    base = {"n_snapshots": 5, "n_intervals": 4, "cum_gap_pct_points": -0.4, "tracking_error_annual_pct": None,
            "generated_at": "2026-02-01T00:00:00+00:00", "context": {"following": True}}
    base.update(kw)
    return base


@pytest.mark.parametrize("paper, auto, level", [
    (None, False, "info"),
    (_paper(), False, "ok"),
    (_paper(cum_gap_pct_points=-3.5), True, "warn"),
    (_paper(context={"following": False}), True, "warn"),
    (_paper(context={"following": False}), False, "info"),
    (_paper(generated_at="2026-01-20T00:00:00+00:00"), True, "warn"),
])
def test_execution_check_levels(paper, auto, level):
    c = ct._execution_check(paper, auto, date(2026, 2, 2))
    assert c["level"] == level


def test_data_check_recent_ledger_gap_and_non_session_records():
    sessions = weekdays(date(2026, 1, 5), 10)
    fri = sessions[4]
    entries = [{"entry_date": sessions[0] + timedelta(days=i), "decision_date": sessions[0] + timedelta(days=i),
                "realized_return_pct": 0.3, "core_weights": {}, "satellite_weights": {}} for i in range(12)
               if i != 9]  # 9번째 날 결측
    c = ct._data_check(entries, [], sessions, entries[-1]["entry_date"] + timedelta(days=1), True)
    assert c["ledger_missing_days"] == 1 and c["level"] == "warn"
    # 토·일(계산 날짜가 휴장일)에 0 이 아닌 수익을 적은 날 = 2일
    assert c["ledger_non_session_nonzero_days"] == 2 and fri + timedelta(days=1) not in sessions


# ---- 기존 알림과 중복 없음 · 주간 1회 전송 ------------------------------------------------------------------------

@pytest.fixture()
def isolated(tmp_path, monkeypatch, db_session):
    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "toggles.json")
    monkeypatch.setattr(cs, "SIGNAL_STATE_CACHE_PATH", tmp_path / "signal.json")
    monkeypatch.setattr(cs, "BENCHMARK_STATE_CACHE_PATH", tmp_path / "bench.json")
    monkeypatch.setattr(cs, "DECAY_STATE_CACHE_PATH", tmp_path / "decay.json")

    def _boom(*a, **k):
        raise AssertionError("기존 알림 함수를 다시 부르면 안 된다(중복 전송·재계산)")

    for name in ("check_and_notify_benchmark_gap", "check_and_notify_champion_alpha_decay",
                 "compute_benchmark_comparison", "compute_champion_alpha_decay", "run_champion_backtest",
                 "get_multiple_price_history"):
        monkeypatch.setattr(cs, name, _boom)
    return tmp_path


def _seed_ledger(db_session, sessions):
    from core.models import ChampionLedgerEntry

    for s in sessions[:-1]:
        # 계산 시각 = 그 거래일 15:12 UTC(11:12 ET) → 다음 거래일부터 적용
        db_session.add(ChampionLedgerEntry(entry_date=s + timedelta(days=1), core_weights=json.dumps({"AAA": 1.0}),
                                           satellite_weights="{}", realized_return_pct=0.1, cumulative_equity=100.0,
                                           created_at=datetime(s.year, s.month, s.day, 15, 12)))
    db_session.commit()


def _fake_prices(closes):
    def fetch(tickers, start=None, end=None, interval="1d"):
        return {t: pd.DataFrame({"Close": pd.Series({pd.Timestamp(d): v for d, v in closes[t].items()})})
                for t in tickers if t in closes}
    return fetch


def _run(isolated, db_session, notify, sessions, closes, **kw):
    return ct.run_weekly_tracking(
        notify, today=sessions[-1] + timedelta(days=2), session=db_session, price_fetcher=_fake_prices(closes),
        backtest_runner=kw.pop("runner", None), report_dir=isolated / "reports",
        backtest_cache_path=kw.pop("cache", isolated / "bt.json"), now_et=datetime(2026, 3, 7, 12, 0),
        paper_tracking_path=isolated / "paper.json")


def test_weekly_run_reads_existing_alert_states_without_resending_and_sends_once(isolated, db_session):
    sessions, closes, _ = live_setup(22, {3: 0.05})
    _seed_ledger(db_session, sessions)
    (isolated / "bench.json").write_text(json.dumps({"as_of": "2026-02-01", "is_lagging": True, "gap": -6.1}))
    (isolated / "decay.json").write_text(json.dumps({"as_of": "2026-02-01", "is_decayed": False, "decay_ratio": 0.9}))
    (isolated / "bt.json").write_text(json.dumps({**synthetic_backtest(),
                                                  "generated_on": (sessions[-1] + timedelta(days=2)).isoformat()}))
    sent: list[str] = []

    res = _run(isolated, db_session, lambda m: sent.append(m) or True, sessions, closes)
    assert len(sent) == 1 and res["notified_now"] is True
    assert res["existing_alerts"]["benchmark_gap_active"] is True and res["existing_alerts"]["alpha_decay_active"] is False
    assert "기존 알림 발동 중: 60/40 격차(이미 따로 보냄)" in sent[0]
    assert "알파 감쇠" not in sent[0]
    assert res["live"]["n_sessions"] == 22  # 기준점 금요일에 계산된 첫 원장은 월요일부터, 마지막 거래일 몫까지
    saved = json.loads((isolated / "reports" / f"champion_tracking_{(sessions[-1] + timedelta(days=2)).isoformat()}.json").read_text())
    assert saved["verdict"] == res["verdict"] and saved["limitations"]

    res2 = _run(isolated, db_session, lambda m: sent.append(m) or True, sessions, closes)  # 같은 날 재실행
    assert len(sent) == 1 and res2["notified_now"] is False and res2["notified"] is True


def test_backtest_cache_reuse_refresh_and_fallback(tmp_path, monkeypatch):
    path = tmp_path / "bt.json"
    fresh = {**synthetic_backtest(), "generated_on": "2026-03-01"}
    path.write_text(json.dumps(fresh))
    called = []

    def runner(start, end):
        called.append((start, end))
        idx = pd.bdate_range("2026-02-02", periods=5)
        core_w = pd.DataFrame({"AAA": [0.0, 1.0, 1.0, 0.5, 0.5]}, index=idx)
        return {"ret_net": pd.Series([0.0, 0.01, -0.02, 0.0, 0.03], index=idx), "core": {"weights": core_w},
                "satellite_weight_applied": 0.15}

    prices = _fake_prices({"SPY": {d.date(): 100.0 + i for i, d in enumerate(pd.bdate_range("2026-01-20", periods=20))},
                           "TLT": {d.date(): 90.0 for d in pd.bdate_range("2026-01-20", periods=20)}})
    assert ct.load_or_refresh_backtest(date(2026, 3, 5), path, runner=runner, price_fetcher=prices) == fresh
    assert called == []  # 6일 이내 캐시는 재사용
    data = ct.load_or_refresh_backtest(date(2026, 3, 8), path, runner=runner, price_fetcher=prices)
    assert called == [("2018-03-08", "2026-03-08")]  # 8년
    assert data["strategy"] == pytest.approx([0.01, -0.02, 0.0, 0.03]) and len(data["spy"]) == 4
    assert data["core_holdings"] == [["2026-02-02", {}], ["2026-02-03", {"AAA": 1.0}], ["2026-02-05", {"AAA": 0.5}]]
    assert json.loads(path.read_text())["generated_on"] == "2026-03-08"

    def broken(start, end):
        raise RuntimeError("no network")

    assert ct.load_or_refresh_backtest(date(2026, 3, 20), path, runner=broken)["generated_on"] == "2026-03-08"
    assert ct.load_or_refresh_backtest(date(2026, 3, 20), tmp_path / "none.json", runner=broken) is None


# ---- 잡 가드·예외 -------------------------------------------------------------------------------------------

def test_job_skips_when_disabled_and_reports_failures(tmp_path, monkeypatch):
    from scheduler import run_scheduler

    monkeypatch.setattr(process_registry, "TOGGLE_STATE_PATH", tmp_path / "toggles.json")
    hits, failures = [], []
    monkeypatch.setattr(ct, "run_weekly_tracking", lambda *a, **k: hits.append(1))
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda job, msg: failures.append((job, msg)))

    process_registry.set_enabled("champion_tracking_weekly", False)
    run_scheduler.champion_tracking_weekly_job()
    assert hits == [] and failures == []

    process_registry.set_enabled("champion_tracking_weekly", True)

    def boom(*a, **k):
        raise ValueError("bad cache")

    monkeypatch.setattr(ct, "run_weekly_tracking", boom)
    run_scheduler.champion_tracking_weekly_job()  # 예외가 스케줄러로 새지 않는다
    assert failures == [("champion_tracking_weekly", "ValueError: bad cache")]


def test_registry_default_on_alert_category():
    entry = process_registry.PROCESS_REGISTRY["champion_tracking_weekly"]
    assert entry["category"] == "alert" and entry["default_enabled"] is True


# ---- 텔레그램 문구 ------------------------------------------------------------------------------------------

def test_message_is_short_and_has_no_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:FAKE-TOKEN-VALUE")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "PKFAKEKEYVALUE")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "FAKESECRETVALUE")
    sessions, closes, entries = live_setup(20, {3: 0.05})
    res = ct.evaluate(entries, synthetic_backtest(), closes, sessions[-1], today=sessions[-1] + timedelta(days=1),
                      paper_tracking=_paper(generated_at=datetime.now().isoformat()), paper_auto_enabled=True)
    msg = ct.format_message(res)
    for secret in ("FAKE-TOKEN-VALUE", "987654321", "PKFAKEKEYVALUE", "FAKESECRETVALUE", "@", "api.telegram", "paper-api"):
        assert secret not in msg
    assert len(msg.splitlines()) <= 9 and len(msg) < 700
    assert msg.splitlines()[0].startswith("✅ 챔피언 주간 검증") and "백테스트 범위 안(정상)" in msg
    assert "조치: 필요 없음" in msg and "독립 표본 아님" in msg
    assert "89분위" in msg  # 161/181 = 88.95%
