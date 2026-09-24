"""core/candidate_recorder.py (RES-01 shadow 원장을 실제 후보 흐름에 연결) 테스트.

원칙: 원전략 함수는 monkeypatch 로 가짜 결과를 주입하고, 실제 네트워크나 실제 discover_candidates
전체 스캔은 호출하지 않는다. 이 테스트는 "기록이 요구사항대로 되는가"만 검증하며 투자 성과를
주장하지 않는다.
"""

import ast
import inspect
from pathlib import Path

import pandas as pd
import pytest

from core import candidate_recorder as rec
from core.models import CandidateBatch, CandidateDecision

AS_OF = pd.Timestamp("2026-06-10").date()

FORBIDDEN_IMPORTS = {"core.paper_execution", "scripts.champion_paper_trade", "core", "champion_paper_trade"}


def test_module_never_imports_order_path():
    """소스 검사: 주문 경로(core.paper_execution, scripts/champion_paper_trade)를 import 하지 않는다."""
    src = Path(rec.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    bad = [n for n in names if n.startswith("core.paper_execution") or n.startswith("scripts.champion_paper_trade")]
    assert bad == [], f"주문 경로를 import 하면 안 된다: {bad}"


def _fake_discovery_df():
    df = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "DDD"],
            "sector": ["Tech", "Tech", "Health", "Health"],
            "composite_score": [90.0, 70.0, 50.0, None],
            "momentum_score": [90.0, 70.0, 50.0, None],
            "growth_score": [90.0, 70.0, 50.0, None],
            "value_score": [90.0, 70.0, 50.0, None],
            "quality_score": [90.0, 70.0, 50.0, None],
            "trailing_pe": [10.0, 12.0, 14.0, None],
            "price_to_book": [2.0, 2.0, 2.0, None],
            "earnings_growth": [0.1, 0.1, 0.1, None],
            "market_cap": [1e9, 1e9, 1e9, None],
            "n_missing_factors": [0, 0, 0, 4],
            "missing_factors": [[], [], [], ["momentum", "growth", "value", "quality"]],
            "sector_rank_fallback": [False, False, False, False],
            "fallback_flags": [[], [], [], []],
            "data_errors": [[], [], [], ["fundamentals"]],
        }
    )
    df.attrs["meta"] = {"pit_verified": False, "as_of_date": AS_OF.isoformat()}
    return df


def test_record_stock_discovery_selected_and_held(db_session, monkeypatch):
    monkeypatch.setattr("core.stock_discovery.discover_candidates", lambda **kw: _fake_discovery_df())
    out = rec._record_stock_discovery(AS_OF, session=db_session)
    assert out["inserted"] is True
    assert out["n_pool"] == 4
    decisions = db_session.query(CandidateDecision).filter_by(source="stock_discovery").all()
    by_ticker = {d.ticker: d.decision for d in decisions}
    assert by_ticker["AAA"] == "selected"
    assert by_ticker["DDD"] == "missing_data"


def _fake_leader_growth(theme):
    return {
        "theme": theme, "candidates_count": 3,
        "leader": {"ticker": "LEAD", "name": "Leader Co", "market_cap": 5e9},
        "growth_stocks": [
            {"ticker": "GROW1", "name": "Grow One", "earnings_growth": 0.3, "growth_data_missing": False},
            {"ticker": "GROW2", "name": "Grow Two", "earnings_growth": None, "growth_data_missing": True},
        ],
    }


def test_record_sector_leaders_all_themes_recorded_and_pool_held(db_session, monkeypatch):
    monkeypatch.setattr("core.sector_leaders.compute_leader_and_growth", _fake_leader_growth)
    monkeypatch.setattr(
        "core.sector_leaders.get_theme_candidate_tickers", lambda theme: ["LEAD", "GROW1", "GROW2", "OTHER"]
    )
    monkeypatch.setattr("core.sector_strength.THEME_UNIVERSE", {"기술": ["XLK"], "금융": ["XLF"]})
    out = rec._record_sector_leaders(AS_OF, session=db_session)
    assert out["themes_attempted"] == 2
    assert out["themes_recorded"] == 2
    assert out["errors"] == []
    # OTHER는 pool에만 있고 leader/growth가 아니므로 held여야 한다.
    all_decisions = db_session.query(CandidateDecision).filter_by(source="sector_leaders").all()
    d_by_ticker = {d.ticker: d.decision for d in all_decisions}
    assert d_by_ticker["LEAD"] == "selected"
    assert d_by_ticker["GROW1"] == "selected"
    assert d_by_ticker["GROW2"] == "selected"  # 성장 결측이어도 원전략이 채택했으면 selected
    assert d_by_ticker["OTHER"] == "held"


def test_record_sector_leaders_one_theme_failure_does_not_block_others(db_session, monkeypatch):
    def flaky(theme):
        if theme == "금융":
            raise RuntimeError("boom")
        return _fake_leader_growth(theme)

    monkeypatch.setattr("core.sector_leaders.compute_leader_and_growth", flaky)
    monkeypatch.setattr("core.sector_leaders.get_theme_candidate_tickers", lambda theme: ["LEAD", "GROW1"])
    monkeypatch.setattr("core.sector_strength.THEME_UNIVERSE", {"기술": ["XLK"], "금융": ["XLF"]})
    out = rec._record_sector_leaders(AS_OF, session=db_session)
    assert out["themes_attempted"] == 2
    assert out["themes_recorded"] == 1
    assert out["errors"] == ["금융"]
    assert "error" in out["per_theme"]["금융"]


def _fake_satellite_pit_blocked(**kw):
    return {
        "as_of": AS_OF.isoformat(), "rebal_date": "2026-01-02", "selected": ["XYZ"],
        "per_ticker_weights": {}, "sizing_method": "equal", "new_orders_allowed": False,
        "allocation_reason": "spy_data_unknown",
    }


def _fake_satellite_pit_ok(**kw):
    return {
        "as_of": AS_OF.isoformat(), "rebal_date": "2026-01-02", "selected": ["XYZ", "ABC"],
        "per_ticker_weights": {"XYZ": 0.05, "ABC": 0.05}, "sizing_method": "equal",
        "new_orders_allowed": True, "allocation_reason": "ok",
    }


def test_record_champion_satellite_blocked_is_held_not_liquidated(db_session, monkeypatch):
    monkeypatch.setattr(
        "core.champion_strategy.compute_satellite_recommendation_point_in_time",
        _fake_satellite_pit_blocked,
    )
    out = rec._record_champion_satellite(AS_OF, session=db_session)
    assert out["new_orders_allowed"] is False
    d = db_session.query(CandidateDecision).filter_by(source="champion_satellite", ticker="XYZ").one()
    assert d.decision == "held"
    assert d.order_proposal is None


def test_record_champion_satellite_ok_is_selected_with_proposal(db_session, monkeypatch):
    monkeypatch.setattr(
        "core.champion_strategy.compute_satellite_recommendation_point_in_time",
        _fake_satellite_pit_ok,
    )
    out = rec._record_champion_satellite(AS_OF, session=db_session)
    assert out["new_orders_allowed"] is True
    d = db_session.query(CandidateDecision).filter_by(source="champion_satellite", ticker="XYZ").one()
    assert d.decision == "selected"
    assert d.order_proposal is not None


def test_pit_not_certified_because_time_contract_is_not_invented(db_session, monkeypatch):
    """가격·재무 기반 후보는 source_publication 등이 없으므로 pit_certified=False 여야 한다."""
    monkeypatch.setattr("core.stock_discovery.discover_candidates", lambda **kw: _fake_discovery_df())
    rec._record_stock_discovery(AS_OF, session=db_session)
    d = db_session.query(CandidateDecision).filter_by(source="stock_discovery", ticker="AAA").one()
    assert d.pit_certified is False


def test_record_daily_candidates_one_source_failure_does_not_block_others(db_session, monkeypatch):
    monkeypatch.setattr("core.stock_discovery.discover_candidates", lambda **kw: _fake_discovery_df())
    monkeypatch.setattr(
        "core.sector_leaders.compute_leader_and_growth", lambda theme: (_ for _ in ()).throw(RuntimeError("x"))
    )
    monkeypatch.setattr("core.sector_leaders.get_theme_candidate_tickers", lambda theme: [])
    monkeypatch.setattr("core.sector_strength.THEME_UNIVERSE", {"기술": ["XLK"]})
    monkeypatch.setattr(
        "core.champion_strategy.compute_satellite_recommendation_point_in_time",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom-satellite")),
    )
    out = rec.record_daily_candidates(AS_OF, session=db_session)
    assert out["ok"] is True  # stock_discovery는 성공
    assert "error" not in out["sources"]["stock_discovery"]
    # sector_leaders는 모든 테마가 개별적으로 실패해도 함수 자체는 죽지 않고 errors 리스트로 보고한다.
    assert out["sources"]["sector_leaders"]["errors"] == ["기술"]
    assert "error" in out["sources"]["champion_satellite"]


def test_record_daily_candidates_all_sources_fail_ok_is_false(db_session, monkeypatch):
    monkeypatch.setattr(
        "core.stock_discovery.discover_candidates", lambda **kw: (_ for _ in ()).throw(RuntimeError("x"))
    )
    monkeypatch.setattr("core.sector_strength.THEME_UNIVERSE", {"기술": ["XLK"]})
    monkeypatch.setattr(
        "core.sector_leaders.compute_leader_and_growth", lambda theme: (_ for _ in ()).throw(RuntimeError("z"))
    )
    monkeypatch.setattr("core.sector_leaders.get_theme_candidate_tickers", lambda theme: [])
    monkeypatch.setattr(
        "core.champion_strategy.compute_satellite_recommendation_point_in_time",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("y")),
    )
    out = rec.record_daily_candidates(AS_OF, session=db_session)
    assert out["ok"] is False


def test_rerun_same_day_is_idempotent_no_duplicate_rows(db_session, monkeypatch):
    monkeypatch.setattr("core.stock_discovery.discover_candidates", lambda **kw: _fake_discovery_df())
    r1 = rec._record_stock_discovery(AS_OF, session=db_session)
    r2 = rec._record_stock_discovery(AS_OF, session=db_session)
    assert r1["inserted"] is True
    assert r2["inserted"] is False
    assert r2["conflict"] is False
    n_batches = db_session.query(CandidateBatch).filter_by(source="stock_discovery").count()
    assert n_batches == 1
    n_decisions = db_session.query(CandidateDecision).filter_by(source="stock_discovery").count()
    assert n_decisions == 4  # 중복 없음


def test_summarize_recording_reports_errors_inline():
    fake = {
        "as_of": "2026-06-10",
        "sources": {
            "stock_discovery": {"n_pool": 4, "inserted": True},
            "sector_leaders": {"themes_recorded": 1, "themes_attempted": 2},
            "champion_satellite": {"error": "RuntimeError: boom"},
        },
    }
    line = rec.summarize_recording(fake)
    assert "2026-06-10" in line
    assert "ERROR" in line
    assert "boom" in line


def test_record_daily_candidates_default_as_of_is_today(db_session, monkeypatch):
    monkeypatch.setattr("core.stock_discovery.discover_candidates", lambda **kw: _fake_discovery_df())
    monkeypatch.setattr("core.sector_strength.THEME_UNIVERSE", {})
    monkeypatch.setattr(
        "core.champion_strategy.compute_satellite_recommendation_point_in_time",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("skip")),
    )
    out = rec.record_daily_candidates(session=db_session)
    assert out["as_of"] == pd.Timestamp.today().date().isoformat()
