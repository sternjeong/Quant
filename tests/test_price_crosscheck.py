"""core.price_crosscheck 테스트 (2026-09-24).

전부 mock 기반 — 실제 네트워크 호출은 하지 않는다(requests 세션을 주입하거나 fetch 함수를
주입한다). 기대값(bp 등)은 요구사항에서 손계산으로 독립 산출했다.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from core import data_integrity
from core.price_crosscheck import (
    AlpacaCredentials, AlpacaDataUnavailable, CLOSE_MATCH_BP, CLOSE_MINOR_BP,
    VERDICT_MAJOR, VERDICT_MATCH, VERDICT_MINOR, VERDICT_MISSING_ALPACA,
    VERDICT_MISSING_YFINANCE, VERDICT_UNAVAILABLE, check_price_crosscheck,
    compare_series, crosscheck_symbol, crosscheck_symbols, fetch_alpaca_daily_bars,
    normalize_alpaca_bars, normalize_yfinance_frame,
)

CREDS = AlpacaCredentials("test-key", "test-secret")


# --------------------------------------------------------------------------- #
# 헬퍼
# --------------------------------------------------------------------------- #

def _yf_frame(rows: dict[str, float], volumes: dict[str, float] | None = None) -> pd.DataFrame:
    index = pd.DatetimeIndex(sorted(rows))
    data = {"Close": [rows[d.strftime("%Y-%m-%d")] for d in index]}
    if volumes:
        data["Volume"] = [volumes.get(d.strftime("%Y-%m-%d"), 0.0) for d in index]
    return pd.DataFrame(data, index=index)


def _bars(rows: dict[str, float], volumes: dict[str, float] | None = None) -> list[dict]:
    return [
        {"t": f"{day}T04:00:00Z", "c": close, "v": (volumes or {}).get(day)}
        for day, close in sorted(rows.items())
    ]


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    """requests 호환 최소 mock — 호출 기록을 남기고 준비된 응답을 순서대로 돌려준다."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --------------------------------------------------------------------------- #
# (a) 일치 / 경미한 차이 / 큰 차이 분류 — 손계산 bp
# --------------------------------------------------------------------------- #

def test_close_diff_classification_by_hand_computed_bp():
    # 손계산:
    #   100.00 -> 100.10 : 0.10/100 = 0.1% = 10bp   (<=25bp)        -> match
    #   200.00 -> 201.00 : 1.00/200 = 0.5% = 50bp   (25~150bp)      -> minor_diff
    #   50.00  -> 52.00  : 2.00/50  = 4.0% = 400bp  (>150bp)        -> major_diff
    yf = {"2026-09-01": 100.0, "2026-09-02": 200.0, "2026-09-03": 50.0}
    ap = {"2026-09-01": 100.10, "2026-09-02": 201.0, "2026-09-03": 52.0}

    result = compare_series("TEST", normalize_yfinance_frame(_yf_frame(yf)), normalize_alpaca_bars(_bars(ap)))
    by_date = {row["date"]: row for row in result["days"]}

    assert by_date["2026-09-01"]["verdict"] == VERDICT_MATCH
    assert by_date["2026-09-01"]["diff_bp"] == pytest.approx(10.0)
    assert by_date["2026-09-02"]["verdict"] == VERDICT_MINOR
    assert by_date["2026-09-02"]["diff_bp"] == pytest.approx(50.0)
    assert by_date["2026-09-03"]["verdict"] == VERDICT_MAJOR
    assert by_date["2026-09-03"]["diff_bp"] == pytest.approx(400.0)
    assert result["summary"][VERDICT_MATCH] == 1
    assert result["summary"][VERDICT_MINOR] == 1
    assert result["summary"][VERDICT_MAJOR] == 1
    assert result["overlap_days"] == 3


def test_threshold_boundaries_are_inclusive_on_the_lower_verdict():
    # 정확히 임계값인 경우: 25bp -> match, 150bp -> minor (경계는 낮은 심각도 쪽 포함)
    match_close = 100.0 * (1 + CLOSE_MATCH_BP / 10_000.0)      # 100.25
    minor_close = 100.0 * (1 + CLOSE_MINOR_BP / 10_000.0)      # 101.50
    result = compare_series(
        "TEST",
        normalize_yfinance_frame(_yf_frame({"2026-09-01": 100.0, "2026-09-02": 100.0})),
        normalize_alpaca_bars(_bars({"2026-09-01": match_close, "2026-09-02": minor_close})),
    )
    verdicts = [row["verdict"] for row in result["days"]]
    assert verdicts == [VERDICT_MATCH, VERDICT_MINOR]


def test_negative_diff_sign_is_alpaca_minus_yfinance():
    # 100.00 -> 99.00 : -1.00/100 = -1.0% = -100bp -> minor_diff, 부호 음수
    result = compare_series(
        "TEST",
        normalize_yfinance_frame(_yf_frame({"2026-09-01": 100.0})),
        normalize_alpaca_bars(_bars({"2026-09-01": 99.0})),
    )
    assert result["days"][0]["diff_bp"] == pytest.approx(-100.0)
    assert result["days"][0]["verdict"] == VERDICT_MINOR


# --------------------------------------------------------------------------- #
# (b) 한쪽에만 있는 거래일
# --------------------------------------------------------------------------- #

def test_days_present_in_only_one_source_are_flagged_each_way():
    yf = {"2026-09-01": 10.0, "2026-09-02": 10.0}                      # 09-03 없음
    ap = {"2026-09-01": 10.0, "2026-09-03": 10.0}                      # 09-02 없음

    result = compare_series("TEST", normalize_yfinance_frame(_yf_frame(yf)), normalize_alpaca_bars(_bars(ap)))
    by_date = {row["date"]: row for row in result["days"]}

    assert by_date["2026-09-02"]["verdict"] == VERDICT_MISSING_ALPACA
    assert by_date["2026-09-02"]["alpaca_close"] is None
    assert by_date["2026-09-03"]["verdict"] == VERDICT_MISSING_YFINANCE
    assert by_date["2026-09-03"]["yfinance_close"] is None
    assert result["summary"][VERDICT_MISSING_ALPACA] == 1
    assert result["summary"][VERDICT_MISSING_YFINANCE] == 1
    assert result["overlap_days"] == 1


# --------------------------------------------------------------------------- #
# (c) 분할 의심
# --------------------------------------------------------------------------- #

def test_split_suspect_detected_when_only_one_source_jumps():
    # AAPL 2020-08-31 4:1 분할 형태: 한쪽만 -75%(=1/4), 다른 쪽은 거의 변화 없음.
    yf = {"2020-08-28": 499.23, "2020-08-31": 129.04}      # 조정본 아님(분할 전 원가격) -> -74.2%
    ap = {"2020-08-28": 124.81, "2020-08-31": 129.04}      # 분할 조정본 -> +3.4%

    result = compare_series("AAPL", normalize_yfinance_frame(_yf_frame(yf)), normalize_alpaca_bars(_bars(ap)))
    suspects = result["split_suspects"]

    assert len(suspects) == 1
    assert suspects[0]["date"] == "2020-08-31"
    assert suspects[0]["jump_side"] == "yfinance"
    assert suspects[0]["yfinance_return"] == pytest.approx(129.04 / 499.23 - 1, rel=1e-6)
    row = {r["date"]: r for r in result["days"]}["2020-08-31"]
    assert row.get("split_suspect") is True


def test_no_split_suspect_when_both_sources_jump_together():
    # 진짜 시장 폭락은 양쪽 모두 같이 움직이므로 분할 의심이 아니다.
    yf = {"2026-09-01": 100.0, "2026-09-02": 50.0}
    ap = {"2026-09-01": 100.0, "2026-09-02": 50.0}
    result = compare_series("TEST", normalize_yfinance_frame(_yf_frame(yf)), normalize_alpaca_bars(_bars(ap)))
    assert result["split_suspects"] == []


def test_volume_gap_is_reported_as_info_only():
    # IEX 거래량이 전체의 1% (0.01 < 0.02 임계값) -> 플래그되지만 심각도는 info.
    yf = {"2026-09-01": 100.0}
    result = compare_series(
        "TEST",
        normalize_yfinance_frame(_yf_frame(yf, volumes={"2026-09-01": 1_000_000.0})),
        normalize_alpaca_bars(_bars({"2026-09-01": 100.0}, volumes={"2026-09-01": 10_000.0})),
    )
    assert len(result["volume_flags"]) == 1
    assert result["volume_flags"][0]["ratio"] == pytest.approx(0.01)
    assert result["volume_flags"][0]["severity"] == "info"
    # 거래량 차이가 종가 판정을 바꾸지는 않는다.
    assert result["days"][0]["verdict"] == VERDICT_MATCH


# --------------------------------------------------------------------------- #
# (d) 조회 실패 -> unavailable (조용한 통과 아님)
# --------------------------------------------------------------------------- #

def test_fetch_failure_yields_unavailable_not_silent_pass():
    def _boom(symbol, start, end):
        raise AlpacaDataUnavailable("network down")

    result = crosscheck_symbol("AAPL", "2026-09-01", "2026-09-30", alpaca_fetch_fn=_boom)

    assert result["summary"][VERDICT_UNAVAILABLE] == 1
    assert result["days"] == []
    assert "network down" in result["unavailable_reason"]
    # match 판정이 하나도 없다 == 조용히 "이상 없음"으로 통과하지 않는다.
    assert result["summary"][VERDICT_MATCH] == 0


def test_unexpected_exception_is_also_isolated_as_unavailable():
    def _boom(symbol, start, end):
        raise RuntimeError("unexpected")

    result = crosscheck_symbol("AAPL", "2026-09-01", "2026-09-30", alpaca_fetch_fn=_boom)
    assert result["summary"][VERDICT_UNAVAILABLE] == 1
    assert "RuntimeError" in result["unavailable_reason"]


def test_one_symbol_failure_does_not_block_the_others():
    def _fetch(symbol, start, end):
        if symbol == "BAD":
            raise AlpacaDataUnavailable("no data")
        return _bars({"2026-09-01": 100.0})

    def _yf(symbol, start=None, end=None, interval="1d"):
        return _yf_frame({"2026-09-01": 100.0})

    report = crosscheck_symbols(
        ["GOOD", "BAD"], "2026-09-01", "2026-09-30",
        alpaca_fetch_fn=_fetch, yf_fetch_fn=_yf, sleep_fn=lambda _s: None,
    )
    assert report["symbols"]["GOOD"]["summary"][VERDICT_MATCH] == 1
    assert report["symbols"]["BAD"]["summary"][VERDICT_UNAVAILABLE] == 1
    assert report["summary"][VERDICT_UNAVAILABLE] == 1


def test_missing_credentials_is_unavailable_and_never_calls_network():
    session = _FakeSession([])
    with pytest.raises(AlpacaDataUnavailable):
        AlpacaCredentials.from_env(env={})
    result = crosscheck_symbol(
        "AAPL", "2026-09-01", "2026-09-30",
        alpaca_fetch_fn=lambda *a: (_ for _ in ()).throw(AlpacaDataUnavailable("키 없음")),
    )
    assert result["summary"][VERDICT_UNAVAILABLE] == 1
    assert session.calls == []


def test_report_meta_states_the_iex_sip_limitations():
    report = crosscheck_symbols(
        [], "2026-09-01", "2026-09-30", sleep_fn=lambda _s: None,
    )
    limitations = report["meta"]["limitations"]
    assert "IEX" in limitations["feed_note"]
    assert "판정이 아니다" in limitations["interpretation"]
    assert report["meta"]["feed"] == "iex"


# --------------------------------------------------------------------------- #
# HTTP 계층 (mock)
# --------------------------------------------------------------------------- #

def test_pagination_follows_next_page_token(tmp_path):
    session = _FakeSession([
        _FakeResponse({"bars": _bars({"2026-09-01": 1.0}), "next_page_token": "tok"}),
        _FakeResponse({"bars": _bars({"2026-09-02": 2.0}), "next_page_token": None}),
    ])
    bars = fetch_alpaca_daily_bars(
        "AAPL", "2026-09-01", "2026-09-02", credentials=CREDS, session=session, use_cache=False,
    )
    assert len(bars) == 2
    assert session.calls[1]["params"]["page_token"] == "tok"
    assert session.calls[0]["params"]["timeframe"] == "1Day"


def test_rate_limit_is_retried_then_succeeds():
    sleeps = []
    session = _FakeSession([
        _FakeResponse({}, status_code=429),
        _FakeResponse({"bars": _bars({"2026-09-01": 1.0})}),
    ])
    bars = fetch_alpaca_daily_bars(
        "AAPL", "2026-09-01", "2026-09-02", credentials=CREDS, session=session,
        use_cache=False, sleep_fn=sleeps.append,
    )
    assert len(bars) == 1
    assert sleeps  # 백오프가 실제로 일어났다


def test_auth_error_raises_unavailable_without_retry():
    session = _FakeSession([_FakeResponse({}, status_code=403)])
    with pytest.raises(AlpacaDataUnavailable):
        fetch_alpaca_daily_bars(
            "AAPL", "2026-09-01", "2026-09-02", credentials=CREDS, session=session,
            use_cache=False, sleep_fn=lambda _s: None,
        )
    assert len(session.calls) == 1


def test_empty_bars_response_is_handled_as_no_data():
    session = _FakeSession([_FakeResponse({"bars": None, "next_page_token": None})])
    bars = fetch_alpaca_daily_bars(
        "AAPL", "2026-09-01", "2026-09-02", credentials=CREDS, session=session, use_cache=False,
    )
    assert bars == []


def test_credentials_are_never_exposed_in_repr():
    assert "test-secret" not in repr(CREDS)
    assert "test-key" not in repr(CREDS)


def test_cache_avoids_a_second_network_call(monkeypatch, tmp_path):
    import core.price_crosscheck as pc

    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path / "alpaca")
    session = _FakeSession([_FakeResponse({"bars": _bars({"2026-09-01": 1.0})})])
    first = pc.fetch_alpaca_daily_bars(
        "AAPL", "2026-09-01", "2026-09-02", credentials=CREDS, session=session,
    )
    second = pc.fetch_alpaca_daily_bars(
        "AAPL", "2026-09-01", "2026-09-02", credentials=CREDS, session=session,
    )
    assert first == second
    assert len(session.calls) == 1  # 두 번째는 캐시에서


# --------------------------------------------------------------------------- #
# (e) 키 없을 때 data_integrity 기존 동작 불변
# --------------------------------------------------------------------------- #

def _integrity_kwargs():
    return {
        "price_fetch_fn": lambda tickers, start: {"SPY": _yf_frame({"2026-09-23": 100.0, "2026-09-24": 101.0})},
        "price_tickers": ["SPY"],
        "fred_cache_dir": None,
        "news_rows": [],
        "today": datetime(2026, 9, 24),
    }


def test_run_integrity_checks_unchanged_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
    kwargs = _integrity_kwargs()
    kwargs["fred_cache_dir"] = tmp_path

    result = data_integrity.run_integrity_checks(**kwargs)

    assert set(result) == {"checks", "anomalies", "ok"}
    assert not any(c["check"].startswith("price_crosscheck") for c in result["checks"])


def test_enabling_crosscheck_without_keys_adds_only_an_info_finding(monkeypatch, tmp_path):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
    kwargs = _integrity_kwargs()
    kwargs["fred_cache_dir"] = tmp_path

    baseline = data_integrity.run_integrity_checks(**kwargs)
    with_crosscheck = data_integrity.run_integrity_checks(enable_price_crosscheck=True, **kwargs)

    added = [c for c in with_crosscheck["checks"] if c not in baseline["checks"]]
    assert [c["check"] for c in added] == ["price_crosscheck_skipped"]
    assert added[0]["severity"] == "info"
    # 키가 없으면 anomalies/ok는 그대로다.
    assert with_crosscheck["anomalies"] == baseline["anomalies"]
    assert with_crosscheck["ok"] == baseline["ok"]


def test_check_price_crosscheck_maps_verdicts_to_severities():
    def _fake_report(tickers, start, end, **kwargs):
        return {
            "symbols": {
                "AAA": {
                    "summary": {"match": 5, "minor_diff": 1, "major_diff": 1,
                                "missing_in_alpaca": 2, "missing_in_yfinance": 1, "unavailable": 0},
                    "days": [{"date": "2026-09-10", "verdict": VERDICT_MAJOR, "diff_bp": 900.0}],
                    "split_suspects": [], "volume_flags": [],
                },
                "BBB": {
                    "summary": {"match": 0, "minor_diff": 0, "major_diff": 0,
                                "missing_in_alpaca": 0, "missing_in_yfinance": 0, "unavailable": 1},
                    "days": [], "split_suspects": [], "volume_flags": [],
                    "unavailable_reason": "HTTP 403",
                },
            },
        }

    findings = check_price_crosscheck(
        tickers=["AAA", "BBB"], today=datetime(2026, 9, 24),
        crosscheck_fn=_fake_report,
        env={"ALPACA_PAPER_API_KEY": "k", "ALPACA_PAPER_API_SECRET": "s"},
    )
    severity = {f["check"]: f["severity"] for f in findings}

    assert severity["price_crosscheck_major_diff"] == "warning"
    assert severity["price_crosscheck_missing_in_yfinance"] == "warning"
    assert severity["price_crosscheck_unavailable"] == "warning"
    assert severity["price_crosscheck_missing_in_alpaca"] == "info"
    assert severity["price_crosscheck_minor_diff"] == "info"


def test_crosscheck_module_failure_never_breaks_the_other_checks(monkeypatch, tmp_path):
    def _explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("core.price_crosscheck.check_price_crosscheck", _explode)
    kwargs = _integrity_kwargs()
    kwargs["fred_cache_dir"] = tmp_path

    result = data_integrity.run_integrity_checks(enable_price_crosscheck=True, **kwargs)

    assert any(c["check"] == "price_crosscheck_unavailable" for c in result["checks"])
    assert any(c["check"] == "price_ok" for c in result["checks"])
