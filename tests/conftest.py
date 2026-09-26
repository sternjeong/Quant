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

# 실제 외부 서비스의 키. 테스트 중에는 빈 값으로 가린다(2026-09-25).
# VM 에서는 모듈 import 시 load_dotenv() 가 /opt/quant/.env 의 실제 키를 읽어 오므로, 가리지 않으면
# 테스트 결과가 "키가 있는 환경/없는 환경"에 따라 달라지고(자동배포 테스트 관문이 VM 에서만 실패했다),
# 운이 나쁘면 테스트가 실제 Alpaca paper 계좌나 텔레그램으로 요청을 보낼 수 있다.
# 삭제하지 않고 빈 문자열로 두는 이유: load_dotenv() 는 이미 있는 변수를 덮어쓰지 않으므로(override=False),
# 테스트 도중 다른 모듈이 load_dotenv() 를 다시 불러도 실제 키가 되살아나지 않는다.
# 키가 있는 경로를 시험하려는 테스트는 monkeypatch.setenv 로 가짜 값을 넣으면 된다(이 fixture 뒤에 적용된다).
EXTERNAL_SERVICE_CREDENTIAL_ENV = (
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_API_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)


@pytest.fixture(autouse=True)
def _mask_external_service_credentials(monkeypatch):
    for name in EXTERNAL_SERVICE_CREDENTIAL_ENV:
        monkeypatch.setenv(name, "")


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


@pytest.fixture(autouse=True)
def _offline_french_factors(monkeypatch, tmp_path):
    """Ken French 데이터는 테스트 중 받지 않고 실제 캐시도 읽지 않는다(심판 테스트가 네트워크·환경에 좌우되지 않게)."""
    from core import french_factors

    def _no_network(_name):
        raise OSError("offline in tests")

    monkeypatch.setattr(french_factors, "_fetch", _no_network)
    monkeypatch.setattr(french_factors, "CACHE_DIR", tmp_path / "french_cache")
