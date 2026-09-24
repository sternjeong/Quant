"""core/account_sync.py — 실계좌 조회·파싱, 목표 대비 이탈 계산, 보류 슬리브의 unknown 처리.

실제 네트워크는 절대 쓰지 않는다(requests.get 을 전부 monkeypatch 한다).
기대값은 요구사항에서 손으로 계산한 값이며 구현을 다시 읽어 만든 값이 아니다.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core import account_sync
from core.models import AccountPositionSnapshot, AccountSnapshot

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _no_throttle_and_no_keys(monkeypatch):
    monkeypatch.setattr(account_sync, "MIN_REQUEST_INTERVAL_SEC", 0)
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)


def _set_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "dummy-key")
    monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "dummy-secret")


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


ACCOUNT_PAYLOAD = {
    "equity": "100000", "cash": "67000", "buying_power": "134000",
    "long_market_value": "33000", "status": "ACTIVE", "currency": "USD",
    "account_number": "PA-SECRET-123",
}
POSITIONS_PAYLOAD = [
    {"symbol": "SPY", "qty": "50", "avg_entry_price": "480", "current_price": "500",
     "market_value": "25000", "unrealized_pl": "1000", "side": "long"},
    {"symbol": "TLT", "qty": "55", "avg_entry_price": "92", "current_price": "90.90909",
     "market_value": "5000", "unrealized_pl": "-60", "side": "long"},
    {"symbol": "GLD", "qty": "15", "avg_entry_price": "190", "current_price": "200",
     "market_value": "3000", "unrealized_pl": "150", "side": "long"},
]


def _install_fake_http(monkeypatch, account=None, positions=None, calls=None):
    _set_keys(monkeypatch)

    def fake_get(url, headers=None, timeout=None):
        if calls is not None:
            calls.append((url, headers))
        if url.endswith("/v2/account"):
            return _Response(ACCOUNT_PAYLOAD if account is None else account)
        if url.endswith("/v2/positions"):
            return _Response(POSITIONS_PAYLOAD if positions is None else positions)
        raise AssertionError(f"예상치 못한 URL: {url}")

    monkeypatch.setattr(account_sync.requests, "get", fake_get)


# 목표: 코어 SPY 20% / TLT 10%, 새틀라이트 NVDA 5%
CORE_OK = {"new_orders_allowed": True, "per_ticker_weights": {"SPY": 0.20, "TLT": 0.10}}
SAT_OK = {"new_orders_allowed": True, "per_ticker_weights": {"NVDA": 0.05}}
SAT_HOLD = {"new_orders_allowed": False, "per_ticker_weights": {},
            "allocation_reason": "후보 풀 가격 데이터 부족으로 보류"}
CORE_HOLD = {"new_orders_allowed": False, "per_ticker_weights": {},
             "allocation_reason": "시장필터 unknown"}


# ---- (a) 계좌·포지션 파싱 --------------------------------------------------------------------------

def test_fetch_account_and_positions_parse_strings_into_numbers(monkeypatch):
    calls = []
    _install_fake_http(monkeypatch, calls=calls)

    account = account_sync.fetch_account()
    assert account["equity"] == 100000.0 and account["cash"] == 67000.0
    assert account["buying_power"] == 134000.0 and account["long_market_value"] == 33000.0
    # 계좌번호 같은 식별값은 담지 않는다
    assert "account_number" not in account

    positions = account_sync.fetch_positions()
    assert [p["ticker"] for p in positions] == ["GLD", "SPY", "TLT"]  # 티커 정렬
    spy = next(p for p in positions if p["ticker"] == "SPY")
    assert spy["qty"] == 50.0 and spy["avg_entry_price"] == 480.0
    assert spy["market_value"] == 25000.0 and spy["unrealized_pl"] == 1000.0

    assert all(url.startswith("https://paper-api.alpaca.markets") for url, _ in calls)
    assert all(h["APCA-API-KEY-ID"] == "dummy-key" for _, h in calls)


def test_fetch_account_state_isolates_failures(monkeypatch):
    _set_keys(monkeypatch)

    def boom(*a, **k):
        import requests

        raise requests.ConnectionError("network down")

    monkeypatch.setattr(account_sync.requests, "get", boom)
    state = account_sync.fetch_account_state()
    assert state["ok"] is False and state["account"] is None
    assert "account:" in state["error"]


def test_get_json_retries_once_on_429(monkeypatch):
    _set_keys(monkeypatch)
    attempts = []

    def flaky(url, headers=None, timeout=None):
        attempts.append(url)
        if len(attempts) == 1:
            return _Response({}, status_code=429)
        return _Response(ACCOUNT_PAYLOAD)

    monkeypatch.setattr(account_sync.requests, "get", flaky)
    assert account_sync.fetch_account()["equity"] == 100000.0
    assert len(attempts) == 2


# ---- (b) 이탈 계산 손계산 --------------------------------------------------------------------------

def _state():
    return {"ok": True, "source": "alpaca_paper", "fetched_at": None,
            "account": {"equity": 100000.0, "cash": 67000.0, "buying_power": 134000.0,
                        "long_market_value": 33000.0},
            "positions": [
                {"ticker": "GLD", "qty": 15.0, "avg_entry_price": 190.0, "current_price": 200.0,
                 "market_value": 3000.0, "unrealized_pl": 150.0},
                {"ticker": "SPY", "qty": 50.0, "avg_entry_price": 480.0, "current_price": 500.0,
                 "market_value": 25000.0, "unrealized_pl": 1000.0},
                {"ticker": "TLT", "qty": 55.0, "avg_entry_price": 92.0, "current_price": 90.9,
                 "market_value": 5000.0, "unrealized_pl": -60.0},
            ], "error": None}


def test_drift_is_actual_minus_target_in_percentage_points():
    """자산 100,000 / SPY 25,000(=25%) vs 목표 20% → +5.0%p, TLT 5,000(=5%) vs 10% → -5.0%p."""
    drift = account_sync.compute_drift(_state(), CORE_OK, SAT_OK)
    by_ticker = {r["ticker"]: r for r in drift["positions"]}

    assert by_ticker["SPY"]["weight_pct"] == pytest.approx(25.0)
    assert by_ticker["SPY"]["target_weight_pct"] == pytest.approx(20.0)
    assert by_ticker["SPY"]["drift_pct_points"] == pytest.approx(5.0)
    assert by_ticker["SPY"]["action"] == "overweight"

    assert by_ticker["TLT"]["drift_pct_points"] == pytest.approx(-5.0)
    assert by_ticker["TLT"]["action"] == "underweight"


def test_held_without_target_and_target_without_holding_when_everything_is_known():
    """두 슬리브 모두 목표 확정: GLD(3%)는 목표에 없는 보유, NVDA(5%)는 목표인데 미보유."""
    drift = account_sync.compute_drift(_state(), CORE_OK, SAT_OK)

    assert drift["held_not_in_target"] == [{"ticker": "GLD", "weight_pct": 3.0}]
    assert [r["ticker"] for r in drift["target_not_held"]] == ["NVDA"]
    assert drift["target_not_held"][0]["drift_pct_points"] == pytest.approx(-5.0)
    assert drift["unknown_positions"] == [] and drift["n_unknown"] == 0

    # |+5| + |-5| + |+3| + |-5| = 18.0 %p, 회전 = 절반 = 9.0%
    assert drift["total_abs_drift_pct"] == pytest.approx(18.0)
    assert drift["turnover_needed_pct"] == pytest.approx(9.0)
    assert drift["turnover_is_partial"] is False
    assert drift["max_abs_drift_pct_points"] == pytest.approx(5.0)
    assert drift["rebalance_review_suggested"] is True


def test_sleeve_level_drift_hand_checked():
    """코어 목표 30%(20+10) vs 실제 30%(25+5) → 0.0%p. 새틀라이트 목표 5% vs 실제 0% → -5.0%p."""
    sleeves = account_sync.compute_drift(_state(), CORE_OK, SAT_OK)["sleeves"]

    assert sleeves["core"]["status"] == "comparable"
    assert sleeves["core"]["target_weight_pct"] == pytest.approx(30.0)
    assert sleeves["core"]["actual_weight_pct"] == pytest.approx(30.0)
    assert sleeves["core"]["drift_pct_points"] == pytest.approx(0.0)

    assert sleeves["satellite"]["target_weight_pct"] == pytest.approx(5.0)
    assert sleeves["satellite"]["actual_weight_pct"] == pytest.approx(0.0)
    assert sleeves["satellite"]["drift_pct_points"] == pytest.approx(-5.0)


def test_drift_is_none_when_equity_is_unknown():
    state = _state()
    state["account"]["equity"] = None
    drift = account_sync.compute_drift(state, CORE_OK, SAT_OK)
    assert all(r["weight_pct"] is None and r["drift_pct_points"] is None for r in drift["positions"])


# ---- (c) 보류 슬리브는 unknown, 절대 "전량 매도 필요"가 아니다 -----------------------------------

def test_satellite_hold_makes_unmatched_holdings_unknown_not_a_full_liquidation():
    drift = account_sync.compute_drift(_state(), CORE_OK, SAT_HOLD)
    by_ticker = {r["ticker"]: r for r in drift["positions"]}

    # GLD 는 보류 중인 새틀라이트의 목표였을 수도 있다 → 목표 0%(전량 매도)로 단정하면 안 된다
    assert by_ticker["GLD"]["drift_status"] == "unknown"
    assert by_ticker["GLD"]["target_weight_pct"] is None
    assert by_ticker["GLD"]["drift_pct_points"] is None
    assert by_ticker["GLD"]["action"] == "none"
    assert "보류" in by_ticker["GLD"]["drift_reason"]

    assert drift["held_not_in_target"] == []
    assert [p["ticker"] for p in drift["unknown_positions"]] == ["GLD"]
    assert drift["unknown_sleeves"] == ["satellite"]
    assert drift["sleeves"]["satellite"]["status"] == "unknown"
    assert drift["sleeves"]["satellite"]["target_weight_pct"] is None
    assert "보류" in drift["sleeves"]["satellite"]["reason"]

    # 비교 가능한 코어 종목은 그대로 계산된다: |+5| + |-5| = 10.0 → 회전 5.0%(부분값)
    assert by_ticker["SPY"]["drift_pct_points"] == pytest.approx(5.0)
    assert drift["total_abs_drift_pct"] == pytest.approx(10.0)
    assert drift["turnover_needed_pct"] == pytest.approx(5.0)
    assert drift["turnover_is_partial"] is True


def test_core_hold_does_not_turn_every_holding_into_a_sell():
    drift = account_sync.compute_drift(_state(), CORE_HOLD, SAT_HOLD)

    assert drift["sleeves"]["core"]["status"] == "unknown"
    assert all(r["drift_status"] == "unknown" for r in drift["positions"])
    assert all(r["target_weight_pct"] is None for r in drift["positions"])
    assert drift["held_not_in_target"] == []
    assert drift["total_abs_drift_pct"] == pytest.approx(0.0)
    assert drift["turnover_is_partial"] is True
    assert drift["rebalance_review_suggested"] is False


def test_missing_recommendation_object_is_unknown_too():
    drift = account_sync.compute_drift(_state(), None, None)
    assert drift["sleeves"]["core"]["status"] == "unknown"
    assert drift["sleeves"]["satellite"]["status"] == "unknown"
    assert drift["held_not_in_target"] == []


# ---- (d) 주문 경로 import 금지 (AST) ---------------------------------------------------------------

FORBIDDEN_MODULES = {"core.paper_execution", "paper_execution", "scripts.champion_paper_trade",
                     "champion_paper_trade", "core.trade_ledger"}


def _imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("relative_path", ["core/account_sync.py", "scripts/sync_paper_account.py"])
def test_module_never_imports_the_order_submission_path(relative_path):
    assert not (_imported_modules(PROJECT_ROOT / relative_path) & FORBIDDEN_MODULES), relative_path


def test_module_only_ever_issues_http_get():
    """requests 는 get 만 호출한다 — 주문을 낼 수 있는 post/put/delete/patch/request 는 없다."""
    tree = ast.parse((PROJECT_ROOT / "core/account_sync.py").read_text(encoding="utf-8"))
    used = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "requests"
    }
    assert used & {"post", "put", "delete", "patch", "request", "Session"} == set(), used
    assert "get" in used


def test_source_has_no_order_keywords():
    src = (PROJECT_ROOT / "core/account_sync.py").read_text(encoding="utf-8")
    assert "/v2/orders" not in src
    assert "submit_plan" not in src and "build_order_plan" not in src


# ---- (e) 키가 없으면 잡이 건너뛰고 죽지 않는다 -----------------------------------------------------

def test_sync_paper_account_skips_without_credentials(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("키가 없는데 네트워크를 호출했다")

    monkeypatch.setattr(account_sync.requests, "get", explode)
    result = account_sync.sync_paper_account()
    assert result["skipped"] is True and result["ok"] is False
    assert "ALPACA_PAPER_API_KEY" in result["reason"]
    assert result["saved"] is False


def test_scheduler_job_skips_quietly_without_credentials(monkeypatch, capsys):
    from scheduler import run_scheduler

    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: True)
    monkeypatch.setattr(account_sync.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("네트워크 호출")))
    called = []
    monkeypatch.setattr(run_scheduler, "report_job_failure", lambda *a: called.append(a))

    run_scheduler.account_snapshot_sync_job()  # 예외 없이 끝나야 한다

    out = capsys.readouterr().out
    assert "건너뜀" in out
    assert called == []  # 키 없음은 잡 실패가 아니다
    assert "dummy" not in out.lower()


def test_scheduler_job_is_gated_by_the_process_toggle(monkeypatch, capsys):
    from scheduler import run_scheduler

    monkeypatch.setattr(run_scheduler, "is_enabled", lambda key: False)
    run_scheduler.account_snapshot_sync_job()
    assert "비활성화됨" in capsys.readouterr().out


# ---- (f) DB 왕복 -----------------------------------------------------------------------------------

def test_snapshot_round_trip(db_session, monkeypatch):
    _install_fake_http(monkeypatch)
    state = account_sync.fetch_account_state()
    assert state["ok"] is True
    drift = account_sync.compute_drift(state, CORE_OK, SAT_HOLD)

    snapshot = account_sync.save_snapshot(db_session, state, drift)
    db_session.commit()

    stored = db_session.query(AccountSnapshot).one()
    assert stored.equity == 100000.0 and stored.cash == 67000.0
    assert stored.n_positions == 3 and stored.source == "alpaca_paper"
    summary = json.loads(stored.drift_summary)
    assert summary["turnover_is_partial"] is True
    assert summary["sleeves"]["satellite"]["status"] == "unknown"
    assert "account_number" not in stored.drift_summary
    assert "dummy" not in (stored.drift_summary + (stored.note or "")).lower()

    rows = {r.ticker: r for r in db_session.query(AccountPositionSnapshot).all()}
    assert set(rows) == {"SPY", "TLT", "GLD"}
    assert rows["SPY"].weight_pct == pytest.approx(25.0)
    assert rows["SPY"].target_weight_pct == pytest.approx(20.0)
    assert rows["SPY"].drift_pct_points == pytest.approx(5.0)
    assert rows["SPY"].drift_status == "comparable" and rows["SPY"].sleeve == "core"
    # 보류 슬리브 때문에 비교 불가인 GLD 는 목표 0 이 아니라 NULL 이다
    assert rows["GLD"].target_weight_pct is None and rows["GLD"].drift_status == "unknown"
    assert rows["GLD"].snapshot_id == snapshot.id


def test_sync_paper_account_persists_through_an_injected_session(db_session, monkeypatch):
    _install_fake_http(monkeypatch)
    monkeypatch.setattr(account_sync, "_load_recommendations", lambda: (CORE_OK, SAT_OK, []))

    result = account_sync.sync_paper_account(session=db_session)

    assert result["ok"] is True and result["saved"] is True
    assert result["snapshot_id"] == db_session.query(AccountSnapshot).one().id
    assert result["drift"]["informational_only"] is True


def test_summarize_drift_is_human_readable_and_leaks_nothing():
    text = account_sync.summarize_drift(account_sync.compute_drift(_state(), CORE_OK, SAT_HOLD))
    assert "부분값" in text and "비교불가" in text
