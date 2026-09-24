"""core/corporate_actions.py 테스트 (requests mock 전용, 실제 네트워크 호출 없음).

기대값은 Alpaca Corporate Actions API 문서의 응답 형태와 이 모듈의 요구사항에서 종이로 정했다.
실제 응답 스키마는 검증되지 않았으므로(키 없음), 여기서 쓰는 payload 는 '문서 기준 가정'이며
방어적 파싱(없는 필드 -> None/unknown)이 요구사항이다.
"""

import json

import pytest
import requests

from core.corporate_actions import (
    AlpacaCorporateActionsClient,
    CorporateAction,
    CorporateActionsError,
    actions_from_json,
    actions_to_json,
    parse_payload,
)


class _Resp:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("no json")
        return self._payload


class _Session:
    """요청을 기록하고 미리 정한 응답을 순서대로 돌려주는 가짜 세션."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        item = self.responses.pop(0) if self.responses else _Resp(200, {})
        if isinstance(item, Exception):
            raise item
        return item


def _client(tmp_path, responses, **kw):
    return AlpacaCorporateActionsClient(
        "k", "s", cache_dir=tmp_path / "ca", session=_Session(responses),
        min_interval_seconds=0.0, sleep=lambda _s: None, **kw)


DIV_ROW = {"symbol": "AAPL", "ex_date": "2024-02-09", "record_date": "2024-02-12",
           "payable_date": "2024-02-15", "rate": "0.24", "special": False,
           "process_date": "2024-02-09"}
SPLIT_ROW = {"symbol": "AAPL", "ex_date": "2020-08-31", "record_date": "2020-08-24",
             "payable_date": "2020-08-28", "new_rate": 4, "old_rate": 1}


def _payload(rows, token=None):
    return {"corporate_actions": rows, "next_page_token": token}


def test_env_credentials_required(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
    with pytest.raises(CorporateActionsError):
        AlpacaCorporateActionsClient.from_env()


def test_credentials_never_leak_in_repr_or_errors(tmp_path):
    c = AlpacaCorporateActionsClient("SECRETKEY", "SECRETVALUE", cache_dir=tmp_path,
                                     session=_Session([_Resp(401)]), min_interval_seconds=0.0,
                                     sleep=lambda _s: None)
    assert "SECRETKEY" not in repr(c) and "SECRETVALUE" not in repr(c)
    with pytest.raises(CorporateActionsError) as exc:
        c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    assert "SECRETKEY" not in str(exc.value) and "SECRETVALUE" not in str(exc.value)


def test_parse_dividend_and_split_fields(tmp_path):
    c = _client(tmp_path, [_Resp(200, _payload({"cash_dividends": [DIV_ROW],
                                                "forward_splits": [SPLIT_ROW]}))])
    actions, cached = c.fetch_symbol("AAPL", "2020-01-01", "2024-12-31")
    assert cached is False
    by_type = {a.type: a for a in actions}
    div = by_type["cash_dividend"]
    assert (div.ex_date, div.record_date, div.payable_date) == ("2024-02-09", "2024-02-12", "2024-02-15")
    assert div.amount == pytest.approx(0.24)  # 문자열 "0.24" 도 float 로
    assert div.split_ratio is None and div.source == "alpaca" and div.fetched_at
    split = by_type["forward_split"]
    assert split.split_ratio == pytest.approx(4.0)  # new_rate/old_rate = 4/1
    assert split.ex_date == "2020-08-31" and split.amount is None
    # 헤더에 자격증명이 들어가되 캐시 파일에는 없어야 한다
    cache_files = list((tmp_path / "ca").glob("*.json"))
    assert cache_files and "APCA" not in cache_files[0].read_text()


def test_special_dividend_flag(tmp_path):
    row = {**DIV_ROW, "special": True, "rate": 1.5}
    c = _client(tmp_path, [_Resp(200, _payload({"cash_dividends": [row]}))])
    actions, _ = c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    assert actions[0].type == "special_cash_dividend" and actions[0].amount == pytest.approx(1.5)


def test_reverse_split_ratio_below_one(tmp_path):
    row = {"symbol": "XYZ", "ex_date": "2023-05-01", "new_rate": 1, "old_rate": 10}
    c = _client(tmp_path, [_Resp(200, _payload({"reverse_splits": [row]}))])
    actions, _ = c.fetch_symbol("XYZ", "2023-01-01", "2023-12-31")
    assert actions[0].type == "reverse_split" and actions[0].split_ratio == pytest.approx(0.1)


def test_missing_fields_become_none_not_guesses(tmp_path):
    rows = {"cash_dividends": [{"symbol": "AAPL"}],                      # 금액·날짜 없음
            "forward_splits": [{"symbol": "AAPL", "ex_date": "2024-03-01"}],  # 비율 없음
            "weird_new_group": [{"symbol": "AAPL", "ex_date": "2024-04-01"}]}  # 모르는 그룹
    c = _client(tmp_path, [_Resp(200, _payload(rows))])
    actions, _ = c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    by_type = {a.type: a for a in actions}
    assert by_type["cash_dividend"].amount is None
    assert by_type["cash_dividend"].ex_date is None
    assert by_type["forward_split"].split_ratio is None
    assert "unknown" in by_type  # 모르는 그룹은 unknown 으로 보존
    assert by_type["unknown"].raw == {"symbol": "AAPL", "ex_date": "2024-04-01"}


def test_pagination_follows_next_page_token(tmp_path):
    p1 = _payload({"cash_dividends": [{**DIV_ROW, "ex_date": "2024-02-09"}]}, token="TOK1")
    p2 = _payload({"cash_dividends": [{**DIV_ROW, "ex_date": "2024-05-10"}]}, token=None)
    c = _client(tmp_path, [_Resp(200, p1), _Resp(200, p2)])
    actions, _ = c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    assert [a.ex_date for a in actions] == ["2024-02-09", "2024-05-10"]
    calls = c._session.calls
    assert len(calls) == 2
    assert "page_token" not in calls[0]["params"]
    assert calls[1]["params"]["page_token"] == "TOK1"
    assert calls[0]["params"]["symbols"] == "AAPL"
    assert calls[0]["params"]["start"] == "2024-01-01" and calls[0]["params"]["end"] == "2024-12-31"


def test_cache_hit_avoids_second_request(tmp_path):
    c = _client(tmp_path, [_Resp(200, _payload({"cash_dividends": [DIV_ROW]}))])
    first, cached1 = c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    second, cached2 = c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    assert (cached1, cached2) == (False, True)
    assert c.request_count == 1
    assert [a.to_dict() for a in first] == [a.to_dict() for a in second]


def test_cache_key_separates_range_and_symbol(tmp_path):
    c = _client(tmp_path, [_Resp(200, _payload({"cash_dividends": [DIV_ROW]})),
                           _Resp(200, _payload({"cash_dividends": [DIV_ROW]}))])
    c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    c.fetch_symbol("AAPL", "2023-01-01", "2023-12-31")
    assert c.request_count == 2


def test_partial_failure_keeps_other_symbols(tmp_path):
    ok = _Resp(200, _payload({"cash_dividends": [DIV_ROW]}))
    c = _client(tmp_path, [ok, _Resp(404), ok], max_attempts=1)
    res = c.fetch(["AAPL", "BROKEN", "MSFT"], "2024-01-01", "2024-12-31")
    assert set(res.actions) == {"AAPL", "MSFT"}
    assert "BROKEN" in res.errors and "AAPL" not in res.errors
    assert len(res.all_actions()) == 2


def test_network_exception_isolated_per_symbol(tmp_path):
    c = _client(tmp_path, [requests.ConnectionError("boom"),
                           _Resp(200, _payload({"cash_dividends": [DIV_ROW]}))], max_attempts=1)
    res = c.fetch(["BAD", "AAPL"], "2024-01-01", "2024-12-31")
    assert list(res.actions) == ["AAPL"] and "BAD" in res.errors


def test_retry_on_429_then_success(tmp_path):
    c = _client(tmp_path, [_Resp(429), _Resp(200, _payload({"cash_dividends": [DIV_ROW]}))],
                max_attempts=3, base_delay_seconds=0.0)
    actions, _ = c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    assert len(actions) == 1 and c.request_count == 2


def test_rate_limit_sleeps_between_requests(tmp_path):
    slept = []
    clock = iter([0.0, 0.0, 0.0, 0.0])
    c = AlpacaCorporateActionsClient(
        "k", "s", cache_dir=tmp_path, min_interval_seconds=0.5, sleep=slept.append,
        clock=lambda: 0.0,
        session=_Session([_Resp(200, _payload({"cash_dividends": [DIV_ROW]}, token="T")),
                          _Resp(200, _payload({}))]))
    c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    assert slept and slept[0] == pytest.approx(0.5)  # 두 번째 페이지 전 대기
    del clock


def test_empty_and_malformed_payloads(tmp_path):
    c = _client(tmp_path, [_Resp(200, {}), _Resp(200, {"corporate_actions": []})])
    a1, _ = c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")
    a2, _ = c.fetch_symbol("MSFT", "2024-01-01", "2024-12-31")
    assert a1 == [] and a2 == []
    assert parse_payload({"corporate_actions": {"cash_dividends": "nope"}}, "now") == []


def test_bad_json_raises_corporate_actions_error(tmp_path):
    c = _client(tmp_path, [_Resp(200, bad_json=True)], max_attempts=1)
    with pytest.raises(CorporateActionsError):
        c.fetch_symbol("AAPL", "2024-01-01", "2024-12-31")


def test_json_roundtrip():
    a = CorporateAction(symbol="AAPL", type="cash_dividend", ex_date="2024-02-09", amount=0.24,
                        fetched_at="2024-02-09T00:00:00+00:00")
    back = actions_from_json(actions_to_json([a]))
    assert back[0].to_dict() == a.to_dict()
    assert json.loads(a.to_json())["source"] == "alpaca"
    # 모르는 필드가 섞여 있어도 from_dict 가 깨지지 않는다
    assert CorporateAction.from_dict({**a.to_dict(), "brand_new_field": 1}).amount == 0.24


def test_types_param_and_dedup(tmp_path):
    c = _client(tmp_path, [_Resp(200, _payload({}))])
    c.fetch(["aapl", "AAPL", ""], "2024-01-01", "2024-12-31", types=("cash_dividend",))
    assert c.request_count == 1
    assert c._session.calls[0]["params"]["types"] == "cash_dividend"
