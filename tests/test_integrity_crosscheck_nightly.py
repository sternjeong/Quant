"""(2026-09-25) data_integrity_check 야간 잡의 Alpaca 가격 교차 대조 배선 테스트.

요구사항(독립적으로 정한 기대값):
    - Alpaca 키가 없으면 교차 대조를 건너뛰고 run_integrity_checks 는 예전처럼 인자 없이 불린다.
    - 키가 있으면 상한 이내 종목(코어·위성 보유+SPY 순)만 대조한다.
    - major 불일치·분할 의심만 텔레그램 대상이고, 같은 (종목, 날짜) 불일치는 다음 날 다시 알리지 않는다.
    - 조회 불가 같은 다른 교차 대조 경고는 텔레그램으로 보내지 않는다.
실제 네트워크·실제 텔레그램은 쓰지 않는다.
"""

from datetime import datetime

from core import data_integrity as di
from core.price_crosscheck import VERDICT_MAJOR, check_price_crosscheck
from scheduler import run_scheduler

KEYS = {"ALPACA_PAPER_API_KEY": "k", "ALPACA_PAPER_API_SECRET": "s"}


def _major(symbol, dates):
    return {"check": "price_crosscheck_major_diff", "severity": "warning",
            "detail": f"{symbol}: 종가 큰 불일치", "ticker": symbol, "dates": list(dates)}


def _result(anomalies):
    return {"checks": list(anomalies), "anomalies": list(anomalies), "ok": not anomalies}


# ---------------------------------------------------------------------------
# 키 없음: 예전 동작 그대로
# ---------------------------------------------------------------------------
def test_without_keys_job_calls_integrity_checks_without_crosscheck(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
    calls = []
    monkeypatch.setattr(di, "run_integrity_checks", lambda *a, **k: calls.append((a, k)) or _result([]))
    monkeypatch.setattr(di, "crosscheck_priority_tickers",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("키 없으면 대상 선정도 하지 않는다")))
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    sent = []
    monkeypatch.setattr(run_scheduler, "send_message", sent.append)

    run_scheduler.data_integrity_check_job()

    assert calls == [((), {})]
    assert sent == []


def test_price_crosscheck_enabled_follows_keys():
    assert di.price_crosscheck_enabled(env={}) is False
    assert di.price_crosscheck_enabled(env={"ALPACA_PAPER_API_KEY": "k"}) is False
    assert di.price_crosscheck_enabled(env=KEYS) is True


# ---------------------------------------------------------------------------
# 키 있음: 상한 이내 종목만
# ---------------------------------------------------------------------------
def test_priority_tickers_are_holdings_then_spy_and_capped():
    holdings = {"core_top4": ["XLK", "XLF", "GLD", "TLT"], "satellite_selected": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]}
    out = di.crosscheck_priority_tickers(max_symbols=10, holdings_fn=lambda: holdings)
    assert out[:4] == ["XLK", "XLF", "GLD", "TLT"]
    assert len(out) == 10  # 보유 10개 + SPY 11개 중 상한 10
    assert di.crosscheck_priority_tickers(max_symbols=3, holdings_fn=lambda: None)[0] == "SPY"
    assert len(di.crosscheck_priority_tickers(max_symbols=3, holdings_fn=lambda: None)) == 3


def test_crosscheck_only_compares_symbols_within_cap():
    seen = []

    def fake_report(tickers, start, end, **kwargs):
        seen.extend(tickers)
        return {"symbols": {}}

    check_price_crosscheck(tickers=[f"T{i}" for i in range(15)], today=datetime(2026, 9, 24),
                           crosscheck_fn=fake_report, env=KEYS, max_symbols=di.CROSSCHECK_NIGHTLY_MAX_SYMBOLS)
    assert len(seen) == di.CROSSCHECK_NIGHTLY_MAX_SYMBOLS <= 10


def test_with_keys_job_enables_crosscheck_with_capped_tickers(monkeypatch, tmp_path):
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    calls = []
    monkeypatch.setattr(di, "crosscheck_priority_tickers", lambda *a, **k: ["XLK", "SPY"])
    monkeypatch.setattr(di, "run_integrity_checks", lambda *a, **k: calls.append(k) or _result([]))
    monkeypatch.setattr(di, "CROSSCHECK_ALERT_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    monkeypatch.setattr(run_scheduler, "send_message", lambda text: True)

    run_scheduler.data_integrity_check_job()

    assert calls[0]["enable_price_crosscheck"] is True
    assert calls[0]["crosscheck_tickers"] == ["XLK", "SPY"]
    assert calls[0]["crosscheck_kwargs"]["max_symbols"] <= 10


# ---------------------------------------------------------------------------
# 반복 알림 억제
# ---------------------------------------------------------------------------
def test_major_finding_carries_dates():
    def fake_report(tickers, start, end, **kwargs):
        return {"symbols": {"AAA": {
            "summary": {"match": 3, "minor_diff": 0, "major_diff": 2, "missing_in_alpaca": 0,
                        "missing_in_yfinance": 0, "unavailable": 0},
            "days": [{"date": "2026-09-10", "verdict": VERDICT_MAJOR, "diff_bp": 300.0},
                     {"date": "2026-09-11", "verdict": VERDICT_MAJOR, "diff_bp": -500.0}],
            "split_suspects": [{"date": "2026-09-12", "symbol": "AAA", "jump_side": "alpaca",
                                "yfinance_return": 0.01, "alpaca_return": 0.5}],
            "volume_flags": []}}}

    findings = check_price_crosscheck(tickers=["AAA"], today=datetime(2026, 9, 24), crosscheck_fn=fake_report, env=KEYS)
    by = {f["check"]: f for f in findings}
    assert by["price_crosscheck_major_diff"]["dates"] == ["2026-09-10", "2026-09-11"]
    assert by["price_crosscheck_split_suspect"]["dates"] == ["2026-09-12"]


def test_same_mismatch_is_alerted_once_across_days(monkeypatch, tmp_path):
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    state = tmp_path / "state.json"
    monkeypatch.setattr(di, "CROSSCHECK_ALERT_STATE_PATH", state)
    monkeypatch.setattr(di, "crosscheck_priority_tickers", lambda *a, **k: ["AAA"])
    anomalies = {"now": [_major("AAA", ["2026-09-10"])]}
    monkeypatch.setattr(di, "run_integrity_checks", lambda *a, **k: _result(anomalies["now"]))
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    sent = []
    monkeypatch.setattr(run_scheduler, "send_message", lambda text: sent.append(text) or True)

    run_scheduler.data_integrity_check_job()  # 첫날: 알림
    run_scheduler.data_integrity_check_job()  # 다음 날 같은 불일치: 알림 없음
    assert len(sent) == 1 and "AAA" in sent[0]

    anomalies["now"] = [_major("AAA", ["2026-09-10", "2026-09-17"])]  # 새 날짜가 생기면 다시 알림
    run_scheduler.data_integrity_check_job()
    assert len(sent) == 2


def test_failed_send_does_not_mark_alerted(tmp_path, monkeypatch):
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(di, "CROSSCHECK_ALERT_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(di, "crosscheck_priority_tickers", lambda *a, **k: ["AAA"])
    monkeypatch.setattr(di, "run_integrity_checks", lambda *a, **k: _result([_major("AAA", ["2026-09-10"])]))
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    attempts = []
    monkeypatch.setattr(run_scheduler, "send_message", lambda text: attempts.append(text) or False)

    run_scheduler.data_integrity_check_job()
    run_scheduler.data_integrity_check_job()
    assert len(attempts) == 2  # 전송 실패면 다음 날 다시 시도한다


def test_non_alertable_crosscheck_warnings_are_log_only(tmp_path):
    unavailable = {"check": "price_crosscheck_unavailable", "severity": "warning", "detail": "x", "ticker": "AAA"}
    base = {"check": "price_zero_or_negative", "severity": "critical", "detail": "y", "ticker": "BBB"}
    routed = di.route_crosscheck_anomalies([unavailable, base], state_path=tmp_path / "s.json")
    assert routed["base"] == [base]
    assert routed["crosscheck_new"] == []
    assert routed["crosscheck_log_only"] == [unavailable]
    assert not (tmp_path / "s.json").exists()


def test_base_anomalies_still_alert_every_day(monkeypatch, tmp_path):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
    base = {"check": "price_zero_or_negative", "severity": "critical", "detail": "BBB 0원", "ticker": "BBB"}
    monkeypatch.setattr(di, "run_integrity_checks", lambda *a, **k: _result([base]))
    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    sent = []
    monkeypatch.setattr(run_scheduler, "send_message", lambda text: sent.append(text) or True)

    run_scheduler.data_integrity_check_job()
    run_scheduler.data_integrity_check_job()
    assert len(sent) == 2  # 기존 세 체크의 알림 규칙은 바뀌지 않는다


def test_state_prunes_old_dates(tmp_path):
    path = tmp_path / "s.json"
    di.mark_crosscheck_alerted([_major("AAA", ["2026-06-01"])], state_path=path, today=datetime(2026, 6, 2))
    di.mark_crosscheck_alerted([_major("BBB", ["2026-09-20"])], state_path=path, today=datetime(2026, 9, 24))
    import json
    keys = json.loads(path.read_text())
    assert any("BBB" in k for k in keys)
    assert not any("AAA" in k for k in keys)
