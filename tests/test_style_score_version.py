"""예전 튜닝 결과 표(strategy_tuning_runs/results)에 점수 버전·ENG-04 열을 덧붙이는 DB 이전 테스트.

튜닝 엔진 코드는 2026-11-15 지웠지만 VM DB 에 표가 남아 있으므로 core.db 의 열 추가 이전은 계속 확인한다.
"""


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
