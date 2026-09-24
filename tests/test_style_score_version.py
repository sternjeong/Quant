"""스타일 점수 결측 처리(ENG-10 동일 결함) + 점수 버전 + ENG-04 필드 저장 왕복 테스트.

기대값은 구현이 아닌 요구사항에서 정했다:
- 결측은 순위에서 제외하고 중립값(50), 결측 플래그 부여, PER 대체 없음.
- 점수 버전: 신규=2, 저장 레코드에 기록, 버전 없음/1은 legacy로 표시하고 삭제·덮어쓰지 않는다.
"""

import json
from contextlib import contextmanager
from datetime import date

import pandas as pd
import pytest

import core.strategy_tuning as st_mod
from core.models import StrategyTuningResult, StrategyTuningRun


def _price_df(trend=0.002, n=300):
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    close = pd.Series([100 * (1 + trend) ** i for i in range(n)], index=idx)
    return pd.DataFrame({"Close": close, "Open": close, "High": close, "Low": close, "Volume": 1000})


def _style_scores(monkeypatch, valuation_by_ticker, prices_by_ticker=None):
    monkeypatch.setattr(st_mod.valuation, "fetch_valuation_inputs", lambda t: valuation_by_ticker[t])

    def _px(t, start=None, end=None, use_cache=True):
        if prices_by_ticker is None:
            return _price_df()
        return prices_by_ticker[t]

    monkeypatch.setattr(st_mod, "get_price_history", _px)
    df = pd.DataFrame({"ticker": list(valuation_by_ticker), "sector": [None] * len(valuation_by_ticker)})
    return st_mod.compute_style_scores(df, "2020-01-01", "2021-12-31").set_index("ticker")


def test_missing_earnings_growth_is_neutral_not_top_and_not_per_substituted(monkeypatch):
    vals = {
        "A": {"trailingPE": 10, "priceToBook": 1, "earningsGrowth": 0.5},
        "B": {"trailingPE": 10, "priceToBook": 1, "earningsGrowth": 0.1},
        "C": {"trailingPE": 999, "priceToBook": 1, "earningsGrowth": None},  # 초고PER 결측
        "D": {"trailingPE": 10, "priceToBook": 1, "earningsGrowth": 0.3},
    }
    r = _style_scores(monkeypatch, vals)
    # 유효값 3개만 순위: 0.1->33.3, 0.3->66.7, 0.5->100. 결측은 중립 50.
    assert r.loc["C", "growth_score"] == pytest.approx(50.0)
    assert r.loc["A", "growth_score"] == pytest.approx(100.0)
    assert r.loc["B", "growth_score"] == pytest.approx(100 / 3)
    assert r.loc["D", "growth_score"] == pytest.approx(200 / 3)
    assert bool(r.loc["C", "growth_data_missing"]) is True
    assert bool(r.loc["A", "growth_data_missing"]) is False


def test_missing_momentum_is_neutral_not_top(monkeypatch):
    vals = {t: {"trailingPE": 10, "priceToBook": 1, "earningsGrowth": 0.1} for t in "ABC"}
    prices = {"A": _price_df(0.003), "B": _price_df(-0.001), "C": pd.DataFrame()}  # C 가격 없음
    r = _style_scores(monkeypatch, vals, prices)
    assert r.loc["C", "momentum_score"] == pytest.approx(50.0)
    assert r.loc["A", "momentum_score"] == pytest.approx(100.0)
    assert r.loc["B", "momentum_score"] == pytest.approx(50.0)  # 유효 2개 중 하위 = 50


def test_percentile_score_all_missing_is_neutral():
    out = st_mod._percentile_score(pd.Series([None, None], dtype=float))
    assert list(out) == [50.0, 50.0]


def test_style_score_version_constants():
    assert st_mod.STYLE_SCORE_VERSION == 2
    assert st_mod.LEGACY_STYLE_SCORE_VERSION == 1


# --- 저장 왕복 -------------------------------------------------------------


@pytest.fixture
def patched_session(db_session, monkeypatch):
    @contextmanager
    def _fake():
        yield db_session
        db_session.commit()

    monkeypatch.setattr(st_mod, "get_session", _fake)
    return db_session


def _save(results, **kw):
    df = pd.DataFrame({"ticker": [r["ticker"] for r in results], "sector": [None] * len(results)})
    return st_mod.save_tuning_run({"k": 1}, df, "2020-01-01", "2021-01-01", 0.75, "보통", results, **kw)


def test_roundtrip_preserves_eng04_fields_and_score_version(patched_session):
    ledger = {"candidates_generated": 12, "n_trials": 9}
    neighbor = {"is_stable": False, "n_neighbors": 4}
    mt = {"dsr": 0.61, "n_trials": 9}
    run_id = _save(
        [{"ticker": "A", "excess_return": 3.0, "search_ledger": ledger,
          "neighbor_stability": neighbor, "multiple_testing": mt}]
    )
    run = st_mod.get_tuning_run(run_id)
    assert run["style_score_version"] == 2
    assert run["score_version_status"] == "current"
    res = run["results"][0]
    assert res["search_ledger"] == ledger
    assert res["neighbor_stability"] == neighbor
    assert res["multiple_testing"] == mt
    assert res["style_score_version"] == 2


def test_roundtrip_absent_eng04_fields_are_none(patched_session):
    run_id = _save([{"ticker": "A", "excess_return": 1.0}])
    res = st_mod.get_tuning_run(run_id)["results"][0]
    assert res["search_ledger"] is None and res["neighbor_stability"] is None
    assert res["multiple_testing"] is None


def _insert_legacy(session, version=None):
    run = StrategyTuningRun(
        base_strategy_id=None, base_config="{}", universe="[]", train_ratio=0.75, intensity="보통",
        start_date=date(2020, 1, 1), end_date=date(2021, 1, 1),
    )
    if version is not None:
        run.style_score_version = version
    session.add(run)
    session.flush()
    session.add(StrategyTuningResult(run_id=run.id, ticker="OLD", excess_return=99.0,
                                     significance_p_value=0.01, skill_pct_of_total=50.0))
    session.commit()
    return run.id


def test_legacy_rows_preserved_and_flagged(patched_session):
    legacy_id = _insert_legacy(patched_session)  # 버전 없음
    v1_id = _insert_legacy(patched_session, version=1)
    new_id = _save([{"ticker": "NEW", "excess_return": 5.0, "significance_p_value": 0.01,
                     "skill_pct_of_total": 10.0}])

    for rid in (legacy_id, v1_id):
        run = st_mod.get_tuning_run(rid)
        assert run is not None and run["results"][0]["ticker"] == "OLD"  # 보존
        assert run["score_version_status"] == "legacy"
        assert run["results"][0]["excess_return"] == 99.0  # 덮어쓰지 않음
    assert st_mod.get_tuning_run(new_id)["score_version_status"] == "current"


def test_top_results_flag_and_filter_by_score_version(patched_session):
    from core.models import Strategy

    s = Strategy(name="s", source="manual", indicator_config="{}")
    patched_session.add(s)
    patched_session.commit()
    sid = s.id
    _save([{"ticker": "NEW", "excess_return": 5.0, "significance_p_value": 0.01, "skill_pct_of_total": 10.0}],
          base_strategy_id=sid)
    run = StrategyTuningRun(
        base_strategy_id=sid, base_config="{}", universe="[]", train_ratio=0.75, intensity="보통",
        start_date=date(2020, 1, 1), end_date=date(2021, 1, 1),
    )
    patched_session.add(run)
    patched_session.flush()
    patched_session.add(StrategyTuningResult(run_id=run.id, ticker="OLD", excess_return=99.0,
                                             significance_p_value=0.01, skill_pct_of_total=50.0))
    patched_session.commit()

    allr = {r["ticker"]: r for r in st_mod.get_top_tuning_results(sid, limit=10)}
    assert allr["OLD"]["score_version_status"] == "legacy" and allr["OLD"]["style_score_version"] is None
    assert allr["NEW"]["score_version_status"] == "current" and allr["NEW"]["style_score_version"] == 2
    only = st_mod.get_top_tuning_results(sid, limit=10, score_version=2)
    assert [r["ticker"] for r in only] == ["NEW"]


def test_add_missing_columns_adds_version_columns_to_old_tables(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect, text
    import core.db as db

    eng = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE strategy_tuning_runs (id INTEGER PRIMARY KEY, base_config TEXT)"))
        c.execute(text("CREATE TABLE strategy_tuning_results (id INTEGER PRIMARY KEY, run_id INTEGER)"))
        c.execute(text("INSERT INTO strategy_tuning_runs (id, base_config) VALUES (1, '{}')"))
    monkeypatch.setattr(db, "engine", eng)
    db._add_missing_columns()
    cols_run = {c["name"] for c in inspect(eng).get_columns("strategy_tuning_runs")}
    cols_res = {c["name"] for c in inspect(eng).get_columns("strategy_tuning_results")}
    assert "style_score_version" in cols_run
    assert {"search_ledger", "neighbor_stability", "multiple_testing", "style_score_version"} <= cols_res
    with eng.begin() as c:  # 기존 행 유지, 버전 NULL
        assert c.execute(text("SELECT style_score_version FROM strategy_tuning_runs WHERE id=1")).scalar() is None
