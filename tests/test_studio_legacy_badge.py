"""전략 스튜디오 페이지: legacy(점수 v1/버전 미기록) 튜닝 결과에 배지·경고가 붙고 v2 순위와 섞이지 않는다.

Streamlit AppTest로 실제 페이지 스크립트를 임시 SQLite DB(운영 DB 아님)에 대해 돌린다. 네트워크는 막는다.
기대값은 요구사항에서 정했다: legacy는 삭제하지 않고 표시하되 기본 리더보드에서는 v2와 섞지 않는다.
"""
import pathlib
import socket
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

import core.db as db
from core.models import Strategy, StrategyTuningResult, StrategyTuningRun
from core.strategy_tuning import LEGACY_SCORE_WARNING

PAGE = pathlib.Path(__file__).resolve().parents[1] / "app" / "pages" / "1_전략_스튜디오.py"
LEGACY_BADGE, CURRENT_BADGE = "⚠️ legacy", "✅ v2 (현재)"


@pytest.fixture
def seeded_app(tmp_path, monkeypatch):
    def _blocked(*a, **k):
        raise OSError("network access blocked in unit test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)

    engine = create_engine(f"sqlite:///{tmp_path / 'page.db'}", connect_args={"check_same_thread": False}, future=True)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))
    db.init_db()
    with db.get_session() as s:
        s.add(Strategy(id=3, name="야간전략", source="manual", indicator_config="{}"))
        s.flush()
        for version, ticker, excess in ((None, "OLDX", 99.0), (2, "NEWX", 5.0)):
            run = StrategyTuningRun(base_strategy_id=3, base_config="{}", universe="[]", train_ratio=0.75,
                                    intensity="보통", start_date=date(2020, 1, 1), end_date=date(2021, 1, 1))
            if version:
                run.style_score_version = version
            s.add(run)
            s.flush()
            s.add(StrategyTuningResult(run_id=run.id, ticker=ticker, excess_return=excess, significance_p_value=0.01,
                                       skill_pct_of_total=10.0, trained_regime="강세장", sector="Tech",
                                       style_type="성장주", tuned_config='{"a": 1}'))
    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _tables_with_version_column(at):
    return [d.value for d in at.dataframe if "점수 버전" in d.value.columns]


def _leaderboard(at):
    return next(t for t in _tables_with_version_column(at) if "티커" in t.columns)


def test_history_table_marks_legacy_and_current_runs(seeded_app):
    history = next(t for t in _tables_with_version_column(seeded_app) if "티커" not in t.columns)
    assert sorted(history["점수 버전"]) == sorted([CURRENT_BADGE, LEGACY_BADGE])
    captions = " ".join(str(c.value) for c in seeded_app.caption)
    assert "legacy 점수 버전 실행" in captions and "삭제되지 않음" in captions


def test_leaderboard_hides_legacy_by_default_and_labels_v2(seeded_app):
    board = _leaderboard(seeded_app)
    assert list(board["티커"]) == ["NEWX"]                    # legacy 99.0 does NOT top the v2 ranking
    assert set(board["점수 버전"]) == {CURRENT_BADGE}          # committed CI JSON rows (no version) are legacy -> hidden too
    captions = " ".join(str(c.value) for c in seeded_app.caption)
    assert "legacy 점수 버전 결과" in captions and "숨겼습니다" in captions


def test_including_legacy_shows_badges_and_a_warning(seeded_app):
    at = seeded_app.checkbox(key="nightly_include_legacy").check().run()
    assert not at.exception
    board = _leaderboard(at)
    by_ticker = dict(zip(board["티커"], board["점수 버전"]))
    assert by_ticker["OLDX"] == LEGACY_BADGE and by_ticker["NEWX"] == CURRENT_BADGE
    warnings = " ".join(str(w.value) for w in at.warning)
    assert LEGACY_SCORE_WARNING in warnings
