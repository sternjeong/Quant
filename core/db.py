"""SQLAlchemy 기반 SQLite 연결/세션 관리 유틸.

이 프로젝트의 DB는 로컬 파일 SQLite 하나(data/quant.db)를 공용으로 사용한다.
app/ (Streamlit) 과 scheduler/ (독립 스케줄러) 양쪽에서 동일하게 이 모듈을 통해 접근한다.

사용 예:
    from core.db import init_db, get_session
    from core.models import Strategy

    init_db()  # 앱/스케줄러 시작 시 1회 호출 (테이블 없으면 생성)

    with get_session() as session:
        session.add(Strategy(name="후보1", indicator_config="{}", source="manual"))
        # with 블록을 정상적으로 빠져나가면 자동 commit, 예외 발생 시 자동 rollback
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()  # .env 파일이 있으면 환경변수로 로드

# 프로젝트 루트 기준 data/ 디렉터리에 SQLite 파일 저장
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "quant.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

# SQLite + 멀티스레드(Streamlit, APScheduler)에서 사용하기 위해 check_same_thread=False
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """models.py 에 정의된 모든 테이블을 생성한다 (이미 존재하면 아무 것도 하지 않음).

    앱/스케줄러 진입점에서 한 번씩 호출해준다.
    """
    from core import models  # 지연 임포트로 순환참조 방지

    models.Base.metadata.create_all(bind=engine)


def get_engine():
    """공용 SQLAlchemy Engine 인스턴스를 반환한다."""
    return engine


@contextmanager
def get_session() -> Iterator[Session]:
    """with 문으로 사용하는 세션 컨텍스트 매니저.

    정상 종료 시 commit, 예외 발생 시 rollback 후 예외를 다시 던진다.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
