"""core/alpaca_market_meta.py — 네트워크 없이 mock get_json 으로 검증. 기대값은 요구사항에서 직접 정했다."""

import ast
from pathlib import Path

from core import alpaca_market_meta as m


def _assets(payloads):
    def get(path):
        v = payloads[path.rsplit("/", 1)[1]]
        if isinstance(v, Exception):
            raise v
        return v
    return get


def test_tradability_verdicts_and_isolation():
    get = _assets({
        "AAPL": {"symbol": "AAPL", "status": "active", "tradable": True, "fractionable": True, "shortable": True},
        "DEAD": {"symbol": "DEAD", "status": "inactive", "tradable": False},
        "HALT": {"symbol": "HALT", "status": "active", "tradable": False},
        "NOPE": RuntimeError("HTTP 404 on /v2/assets/NOPE"),
        "FLAKY": RuntimeError("HTTP 503"),
    })
    rep = m.check_tradability(["aapl", "DEAD", "HALT", "NOPE", "FLAKY", "AAPL"], get_json=get)
    assert list(rep) == ["AAPL", "DEAD", "HALT", "NOPE", "FLAKY"]  # 대문자화·중복 제거
    assert rep["AAPL"]["verdict"] == m.TRADABLE and rep["AAPL"]["fractionable"] is True
    assert rep["DEAD"]["verdict"] == m.INACTIVE
    assert rep["HALT"]["verdict"] == m.NOT_TRADABLE
    assert rep["NOPE"]["verdict"] == m.NOT_FOUND
    assert rep["FLAKY"]["verdict"] == m.LOOKUP_FAILED
    assert m.untradable(rep) == ["DEAD", "HALT", "NOPE"]  # 조회 실패는 '거래불가'로 단정하지 않는다


def test_calendar_early_close_and_trading_day():
    rows = [{"date": "2026-11-27", "open": "09:30", "close": "13:00"},
            {"date": "2026-11-30", "open": "09:30", "close": "16:00"}]
    days = m.fetch_trading_days("2026-11-26", "2026-11-30", get_json=lambda p: rows)
    assert [d["early_close"] for d in days] == [True, False]
    assert m.is_trading_day("2026-11-27", get_json=lambda p: rows[:1]) is True
    assert m.is_trading_day("2026-11-26", get_json=lambda p: []) is False  # 추수감사절
    def boom(p): raise RuntimeError("x")
    assert m.is_trading_day("2026-11-26", get_json=boom) is None


def test_module_is_get_only_and_has_no_order_imports():
    src = (Path(m.__file__)).read_text(encoding="utf-8")
    imported = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    assert not any("paper_execution" in (i or "") for i in imported)
    assert "requests.post" not in src and "requests.delete" not in src
