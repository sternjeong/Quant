"""pytest 공용 fixture.

테스트는 실제 운영 DB(data/quant.db)를 건드리지 않도록, 매 테스트마다
임시 SQLite 파일에 대해 엔진/세션을 새로 만들어 사용한다.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import models


@pytest.fixture()
def db_session(tmp_path):
    """테스트 전용 임시 SQLite DB에 연결된 세션을 반환한다."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(bind=engine)
    session = session_local()
    try:
        yield session
    finally:
        session.close()
