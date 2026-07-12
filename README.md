# Quant — 개인용 주식 도우미

나 혼자 로컬(localhost)에서 실행하는 미국 주식 전략 검증 · 모니터링 · 리서치 대시보드.
자세한 기획/스펙은 [`SPEC.md`](./SPEC.md) 참고.

## 디렉터리 구조

```
Quant/
├── app/
│   ├── Home.py           # Streamlit 진입점 (사이드바 네비게이션 + 소개)
│   └── pages/             # 각 모듈이 추가하는 페이지 (예: 1_백테스팅.py)
├── core/                  # 공용 백엔드 로직 (DB, 모델, 시장데이터 등)
│   ├── db.py               # SQLAlchemy 세션/엔진 관리
│   ├── models.py            # ORM 모델 (테이블 정의)
│   └── market_data.py        # yfinance 캐싱 래퍼
├── scheduler/
│   └── run_scheduler.py    # 매일 미국 장마감 후 실행되는 독립 스케줄러
├── data/
│   ├── quant.db (자동 생성) # SQLite DB 파일
│   └── cache/               # 시장데이터 캐시 (git에는 커밋되지 않음)
├── tests/                 # pytest 테스트
├── requirements.txt
├── .env.example
└── SPEC.md
```

## 설치

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # 이후 .env 안의 값(FRED_API_KEY 등)을 채워넣는다
```

## 실행

### 1. 웹 대시보드 (Streamlit)

```bash
streamlit run app/Home.py
```

브라우저에서 `http://localhost:8501` 로 접속. 최초 실행 시 `data/quant.db` 가 자동 생성된다.

### 2. 백그라운드 스케줄러 (타점 알림)

Streamlit 앱과는 완전히 별도의 프로세스로, 항상 켜두어야 브라우저를 열지 않아도
매일 미국 장마감 후 관심 종목 스캔 + 데스크톱 알림을 받을 수 있다.

```bash
python scheduler/run_scheduler.py
```

기본적으로 평일 미국 동부시간(America/New_York) 16:30에 관심 종목(watchlist)을 스캔한다.
(장마감 16:00 + 데이터 반영 대기 30분)

macOS/Linux에서 재부팅 후에도 계속 실행되게 하려면 `launchd`/`systemd`/`cron` 등 OS 스케줄러나
`tmux`/`screen`/`nohup` 으로 상시 구동 프로세스로 등록해두는 것을 권장한다.

### 3. 테스트

```bash
pytest
```

## 개발 컨벤션 (이후 모듈 개발 시 반드시 준수)

- **DB/모델**: 새 테이블이 필요하면 `core/models.py` 에 클래스를 추가한다. 별도 마이그레이션
  도구는 쓰지 않고, `core/db.py` 의 `init_db()` (`Base.metadata.create_all`) 로 없는 테이블만
  생성하는 방식이다. 기존 테이블의 컬럼을 변경/삭제해야 하면 `data/quant.db` 를 지우고
  다시 생성하거나 수동 마이그레이션 스크립트를 추가한다.
- **세션 사용**: DB 접근은 항상 `core.db.get_session()` 컨텍스트 매니저를 사용한다.
  ```python
  from core.db import get_session
  from core.models import Strategy

  with get_session() as session:
      session.add(Strategy(...))
      # with 블록 정상 종료 시 자동 commit
  ```
- **JSON 컬럼**: SQLite에는 네이티브 JSON 타입이 없으므로 `indicator_config`, `tickers` 등은
  `Text` 컬럼에 `json.dumps()` 로 저장하고 읽을 때 `json.loads()` 로 파싱한다.
- **sys.path 부트스트랩**: `app/Home.py`, `app/pages/*.py`, `scheduler/*.py` 등 core.*를
  임포트해야 하는 모든 진입점 스크립트 최상단에는 아래 코드를 그대로 복사해서 넣는다
  (Streamlit/스케줄러가 프로젝트 루트를 자동으로 sys.path에 넣어주지 않기 때문).
  ```python
  import sys
  from pathlib import Path

  PROJECT_ROOT = Path(__file__).resolve().parent.parent
  if str(PROJECT_ROOT) not in sys.path:
      sys.path.insert(0, str(PROJECT_ROOT))
  ```
  (`app/pages/` 안의 파일은 `parent.parent.parent` 가 되어야 하므로, 실제 depth에 맞게 조정)
- **Streamlit 페이지 파일명 규칙**: `app/pages/` 안에 `{순번}_{한글이름}.py` 형식으로 만든다.
  순번은 SPEC.md의 모듈 순서(A~H)를 기준으로 매긴다. 예:
  - `1_백테스팅.py` (모듈 A)
  - `2_Threads_요약.py` (모듈 B)
  - `3_관심종목_모니터링.py` (모듈 C)
  - `4_거장_포트폴리오.py` (모듈 D)
  - `5_퀀트_스크리너.py` (모듈 E)
  - `6_밸류에이션.py` (모듈 F)
  - `7_매크로_대시보드.py` (모듈 G)
  - `8_포트폴리오_관리.py` (모듈 H)

  Streamlit은 파일명 앞자리 숫자로 사이드바 노출 순서를 정하고, `_` 뒤 텍스트를 페이지 제목으로
  보여준다 (파일명에 이모지를 붙이면 사이드바에 그대로 표시되므로 필요시 활용 가능).
- **시장 데이터 조회**: 개별 종목 가격은 직접 `yfinance` 를 호출하지 말고 항상
  `core.market_data.get_price_history(ticker, start, end, interval="1d")` 를 사용한다
  (파일 캐시가 적용되어 반복 조회 시 API 호출을 줄여준다). 여러 종목은
  `get_multiple_price_history(tickers, start, end)` 사용.
- **환경변수**: API 키 등은 `.env` 에 넣고 `python-dotenv` 로 로드한다 (`.env` 는 git에 커밋 금지,
  `.env.example` 에 placeholder만 추가/유지한다).
- **공용 로직은 core/ 에**: Streamlit 페이지 코드(`app/pages/*.py`)에는 UI 로직만 두고,
  전략 평가/지표 계산/외부 API 연동 등 재사용 가능한 로직은 `core/` 아래에 모듈을 새로 만들어
  구현한다 (예: `core/strategy_engine.py`, `core/indicators.py`, `core/sec_edgar.py`,
  `core/fred_data.py` 등). 스케줄러도 같은 `core/` 로직을 그대로 재사용해야 하므로 필수.
