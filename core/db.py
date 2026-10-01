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
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()  # .env 파일이 있으면 환경변수로 로드

# 프로젝트 루트 기준 data/ 디렉터리에 SQLite 파일 저장
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "quant.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

# SQLite + 멀티스레드(Streamlit, APScheduler)에서 사용하기 위해 check_same_thread=False.
# timeout: 쓰기 잠금이 풀릴 때까지 기다리는 시간(기본 5초). 야간 블록(00:00~01:00 KST)에 잡 수십 개가
# APScheduler 스레드풀에서 겹쳐 돌아 5초로는 모자랐다 — 2026-09-28에 variant_shadow_record가
# "database is locked"로 실패했다.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_concurrency_pragmas(dbapi_connection, _record) -> None:
    """SQLite 연결마다 동시성 설정을 건다 (다른 DB면 아무것도 하지 않는다).

    - journal_mode=WAL: 읽는 쪽이 쓰는 쪽을 막지 않는다. 기본값(delete)에서는 잡 하나가 쓰는 동안
      다른 잡의 읽기까지 막혀서 야간에 잠금 충돌이 났다. WAL은 DB 파일의 속성이라 한 번 켜면 유지된다.
    - busy_timeout: 그래도 겹치면 30초까지 기다린다(즉시 예외 대신).
    - synchronous=NORMAL: WAL에서 권장되는 값. 전원이 갑자기 나가도 DB는 깨지지 않고 마지막 트랜잭션만 잃을 수 있다.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# init_db()가 같은 engine에 대해 실제로는 한 번만 동작하도록 막는 상태. Streamlit/APScheduler
# 스레드풀에서 요청·잡마다 init_db()를 다시 불러도(관례적 1회 호출 가정이 지켜지지 않는 호출부가
# 많음) 두 번째 호출부터는 즉시 반환해, 이미 완료된 스키마 점검을 위해 또 DB 잠금을 시도하지 않는다.
# engine 객체 자체(동일성)로 캐시하므로 테스트가 monkeypatch로 engine을 교체하면 다시 수행된다.
_init_lock = threading.Lock()
_initialized_engine = None


def init_db() -> None:
    """models.py 에 정의된 모든 테이블을 생성한다 (이미 존재하면 아무 것도 하지 않음).

    앱/스케줄러 진입점에서 한 번씩 호출해준다. 같은 engine에 대해서는 실제 작업이 1회만 수행된다.
    """
    global _initialized_engine
    if _initialized_engine is engine:
        return
    with _init_lock:
        if _initialized_engine is engine:
            return
        from core import models  # 지연 임포트로 순환참조 방지

        models.Base.metadata.create_all(bind=engine)
        _add_missing_columns()
        _initialized_engine = engine


def _add_missing_columns() -> None:
    """create_all()은 없는 테이블만 만들 뿐 기존 테이블에 나중에 추가된 컬럼은 채워주지 않는다
    (SQLAlchemy 한계, 이 프로젝트엔 별도 마이그레이션 도구가 없음). 이미 배포된 SQLite 파일에도
    새 컬럼(예: SPEC 15절 max_holding_days)이 적용되도록 최소한의 ALTER TABLE ADD COLUMN을
    직접 실행한다 — 컬럼이 이미 있으면(OperationalError "duplicate column") 조용히 무시한다.

    컬럼 존재 여부는 먼저 읽기 전용 inspect()로 전부 확인하고, 실제로 추가할 컬럼이 하나도 없으면
    쓰기 트랜잭션(engine.begin())을 아예 열지 않는다 — 다른 프로세스가 쓰기 중이어도 이 흔한 경로
    (대부분의 호출에서 추가할 컬럼은 없다)가 그 잠금이 풀리길 기다리지 않도록 하기 위함이다.
    """
    from sqlalchemy import inspect, text

    additions = {
        "strategy_tuning_runs": [("max_holding_days", "INTEGER"), ("style_score_version", "INTEGER")],
        "strategy_tuning_results": [
            ("significance_p_value", "FLOAT"),
            ("skill_pct_of_total", "FLOAT"),
            ("search_ledger", "TEXT"),
            ("neighbor_stability", "TEXT"),
            ("multiple_testing", "TEXT"),
            ("style_score_version", "INTEGER"),
        ],
        "backtest_results": [
            ("profit_factor", "FLOAT"),
            ("calmar", "FLOAT"),
            ("avg_drawdown_days", "FLOAT"),
        ],
        "news_ticker_digests": [
            ("sentiment", "VARCHAR(20)"),
            ("sentiment_score", "FLOAT"),
        ],
        # 2026-09-24 실계좌 스냅샷(core/account_sync.py). 새로 만든 테이블이라 create_all()이
        # 처리하지만, 이미 만들어진 DB에 나중에 컬럼을 덧붙일 때도 기존 행이 깨지지 않도록
        # 전부 nullable 로 선언해 여기에 함께 적어둔다(있으면 조용히 건너뛴다).
        "account_snapshots": [
            ("drift_summary", "TEXT"),
            ("note", "TEXT"),
            ("long_market_value", "FLOAT"),
            ("n_positions", "INTEGER"),
        ],
        "account_position_snapshots": [
            ("target_weight_pct", "FLOAT"),
            ("drift_pct_points", "FLOAT"),
            ("drift_status", "VARCHAR(20)"),
            ("drift_reason", "TEXT"),
            ("sleeve", "VARCHAR(20)"),
            ("current_price", "FLOAT"),
        ],
    }
    inspector = inspect(engine)
    pending: list[tuple[str, str, str]] = []
    for table, columns in additions.items():
        if table not in inspector.get_table_names():
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for col_name, col_type in columns:
            if col_name not in existing:
                pending.append((table, col_name, col_type))

    if not pending:
        return

    with engine.begin() as conn:
        for table, col_name, col_type in pending:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))


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
