"""SQLAlchemy ORM 모델 정의.

이 프로젝트의 모든 테이블은 여기에 정의한다.
새 모듈을 개발하며 테이블이 더 필요하면 이 파일에 클래스를 추가하고,
core/db.py 의 init_db() 를 다시 실행(또는 앱 재시작)하면 테이블이 자동 생성된다.

컨벤션:
- 모든 모델은 정수 자동증가 PK `id` 를 가진다.
- 생성 시각은 `created_at` (기본값 utcnow), 갱신 시각이 필요하면 `updated_at` 을 둔다.
- JSON으로 저장해야 하는 값(지표 조합 조건, 티커 리스트 등)은 Text 컬럼에
  json.dumps() 로 직렬화해서 저장한다 (SQLite는 JSON 타입이 없으므로).
  core/db.py 에는 별도 헬퍼가 없으니 사용하는 쪽에서 json.dumps/json.loads 를 직접 호출한다.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Strategy(Base):
    """전략 라이브러리: 백테스팅 엔진(모듈 A)에서 생성/저장되는 매매 전략.

    indicator_config 예시 (JSON 문자열):
        {
            "logic": "AND",
            "conditions": [
                {"indicator": "ma_cross", "short": 20, "long": 60, "type": "golden"},
                {"indicator": "rsi", "period": 14, "op": "<", "value": 30}
            ]
        }
    """

    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)  # 예: "골든크로스+RSI 눌림목", "후보1"
    indicator_config = Column(Text, nullable=False)  # 지표 조합 조건 (JSON 문자열)
    source = Column(String(100), nullable=True)  # 예: "youtube_script", "manual", "candidate"
    description = Column(Text, nullable=True)  # 원문 스크립트 / AI 해석 결과 설명
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    watchlist_items = relationship("WatchlistItem", back_populates="strategy")
    backtest_results = relationship("BacktestResult", back_populates="strategy")
    alerts = relationship("AlertLog", back_populates="strategy")

    def __repr__(self) -> str:
        return f"<Strategy id={self.id} name={self.name!r}>"


class WatchlistItem(Base):
    """관심 티커 (최대 50개). 종목별로 적용할 전략을 strategy_id로 연결."""

    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    memo = Column(Text, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    strategy = relationship("Strategy", back_populates="watchlist_items")

    def __repr__(self) -> str:
        return f"<WatchlistItem id={self.id} ticker={self.ticker!r} strategy_id={self.strategy_id}>"


class BacktestResult(Base):
    """전략 x 종목 x 기간별 백테스팅 결과."""

    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=False)
    ticker = Column(String(20), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

    cumulative_return = Column(Float, nullable=True)  # 누적수익률 (%)
    cagr = Column(Float, nullable=True)  # 연평균 복리 성장률 (%)
    mdd = Column(Float, nullable=True)  # 최대낙폭 (%, 음수)
    sharpe = Column(Float, nullable=True)  # 샤프지수
    win_rate = Column(Float, nullable=True)  # 승률 (%)
    trade_count = Column(Integer, nullable=True)  # 매매 횟수

    extra_metrics = Column(Text, nullable=True)  # 추후 지표 확장용 JSON 문자열
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    strategy = relationship("Strategy", back_populates="backtest_results")

    def __repr__(self) -> str:
        return f"<BacktestResult id={self.id} strategy_id={self.strategy_id} ticker={self.ticker!r}>"


class ThreadsSummary(Base):
    """Threads 등에서 붙여넣은 원문과 AI 티커 인식/요약 결과 (모듈 B)."""

    __tablename__ = "threads_summaries"

    id = Column(Integer, primary_key=True)
    raw_text = Column(Text, nullable=False)  # 붙여넣은 원문
    tickers = Column(Text, nullable=True)  # 인식된 티커 목록 (JSON 배열 문자열), 사용자가 직접 수정 가능
    ai_summary = Column(Text, nullable=True)  # AI 요약
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<ThreadsSummary id={self.id} created_at={self.created_at}>"


class ThreadsWeeklyReport(Base):
    """티커별 주간 AI 인사이트 리포트 (모듈 B 확장).

    ThreadsSummary(개별 글)를 기간(period_start~period_end)으로 묶어 AI가 생성한 종합 리포트.
    같은 티커에 여러 번 생성할 수 있어(수동 재생성/스케줄러) history로 여러 행을 남긴다.

    price_at_generation은 리포트 생성 시점의 종가(기준가)를 담아, 이후 generate_report_feedback()
    이 "그때 이 가격에서 어떻게 됐는지"를 계산할 수 있게 한다. feedback_* 컬럼은 사후 검증(회고) 결과로,
    다시 생성하면 최신값으로 덮어쓴다(리포트 자체처럼 여러 버전을 남기지는 않음 — 필요하면 나중에 확장).
    """

    __tablename__ = "threads_weekly_reports"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    post_count = Column(Integer, nullable=False)
    report_text = Column(Text, nullable=False)
    price_at_generation = Column(Float, nullable=True)  # 리포트 생성 시점 종가 (조회 실패 시 None)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    feedback_text = Column(Text, nullable=True)  # AI 사후 검증(회고) 결과
    feedback_price = Column(Float, nullable=True)  # 회고 시점 종가
    feedback_generated_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<ThreadsWeeklyReport id={self.id} ticker={self.ticker!r} period={self.period_start.date()}~{self.period_end.date()}>"


class GuruHolding(Base):
    """거장/펀드 13F 공시 기반 보유 종목 (모듈 D)."""

    __tablename__ = "guru_holdings"

    id = Column(Integer, primary_key=True)
    guru_name = Column(String(100), nullable=False, index=True)  # 예: "Warren Buffett"
    fund_name = Column(String(200), nullable=True)  # 예: "Berkshire Hathaway"
    ticker = Column(String(20), nullable=True, index=True)  # 13F 종목명에서 티커 역추적 실패 시 None
    issuer_name = Column(String(300), nullable=True)  # 13F 원문 종목명(nameOfIssuer). 티커 미확인 시 표시용
    shares = Column(Float, nullable=True)  # 보유수량
    weight_pct = Column(Float, nullable=True)  # 포트폴리오 내 비중 (%)
    filing_date = Column(Date, nullable=True)  # 13F 공시일
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<GuruHolding id={self.id} guru={self.guru_name!r} ticker={self.ticker!r}>"


class PortfolioHolding(Base):
    """내가 실제로 보유한 종목 (모듈 H)."""

    __tablename__ = "portfolio_holdings"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    quantity = Column(Float, nullable=False)  # 보유 수량
    purchase_price = Column(Float, nullable=False)  # 매입 단가
    purchase_date = Column(Date, nullable=False)  # 매입일
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PortfolioHolding id={self.id} ticker={self.ticker!r} qty={self.quantity}>"


class AlertLog(Base):
    """스케줄러가 매일 장마감 후 스캔하여 감지한 타점 알림 이력 (모듈 C)."""

    __tablename__ = "alerts_log"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), nullable=False, index=True)
    strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    message = Column(Text, nullable=True)  # 알림 내용 (예: "20/60 골든크로스 발생")
    is_read = Column(Boolean, default=False, nullable=False)

    strategy = relationship("Strategy", back_populates="alerts")

    def __repr__(self) -> str:
        return f"<AlertLog id={self.id} ticker={self.ticker!r} detected_at={self.detected_at}>"


class StrategyTuningRun(Base):
    """다종목 미세튜닝 실행 배치 1건 (모듈 A 확장 — 유튜브 전략을 100종목에 적용 + 파라미터 튜닝).

    base_strategy_id가 있으면 전략 라이브러리에 이미 저장된 전략을 백본으로 재튜닝한 것이고(계보
    추적용), 없으면 자연어 해석 직후(저장 전) 임시 결과로 바로 실행한 것이다. 사용자가 반년 주기로
    같은 base_strategy_id에 대해 이 배치를 반복 실행할 것을 전제로 하므로(장기 이력 누적), 실행마다
    새 행을 남기고 절대 덮어쓰지 않는다.
    """

    __tablename__ = "strategy_tuning_runs"

    id = Column(Integer, primary_key=True)
    base_strategy_id = Column(Integer, ForeignKey("strategies.id"), nullable=True)
    base_config = Column(Text, nullable=False)  # 튜닝 전 원본 indicator_config (JSON 문자열)
    universe = Column(Text, nullable=False)  # 이번 실행에 사용한 종목 티커 리스트 (JSON 배열 문자열)
    train_ratio = Column(Float, nullable=False, default=0.75)
    intensity = Column(String(20), nullable=False, default="보통")  # "빠름" | "보통" | "정밀"
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    base_strategy = relationship("Strategy")
    results = relationship(
        "StrategyTuningResult", back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<StrategyTuningRun id={self.id} base_strategy_id={self.base_strategy_id}>"


class StrategyTuningResult(Base):
    """StrategyTuningRun 배치 내 종목 1건의 튜닝 결과 (모듈 A 확장).

    test_comparison에는 core.backtest_engine.compare_with_benchmarks() 와 동일한 3-way 비교
    (튜닝된 전략 적용 vs 해당 종목 매수보유 vs S&P500 매수보유)의 test 구간 지표를 JSON으로 담는다.
    """

    __tablename__ = "strategy_tuning_results"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("strategy_tuning_runs.id"), nullable=False, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    sector = Column(String(100), nullable=True)
    style_type = Column(String(30), nullable=True)  # 주도주|성장주|가치주|경기민감주|경기방어주|퀄리티 컴파운더
    style_scores = Column(Text, nullable=True)  # 6개 스타일 점수 (JSON 객체 문자열)
    tuned_config = Column(Text, nullable=True)  # 튜닝된 indicator_config (JSON 문자열)
    train_metrics = Column(Text, nullable=True)  # train 구간 성과 지표 (JSON 객체 문자열)
    test_comparison = Column(Text, nullable=True)  # test 구간 3-way 비교 지표 (JSON 객체 문자열)
    excess_return = Column(Float, nullable=True)  # test 구간 전략 CAGR - S&P500 매수보유 CAGR
    health_warnings = Column(Text, nullable=True)  # JSON 배열 문자열
    # expression(직접 수식) 전략에서 숫자만 튜닝해도 매수보유를 못 이겨 Gemini가 구조 자체를 바꾼
    # 대안으로 교체됐는지 (2026-07-14, core.strategy_tuning.tune_expression_strategy_for_ticker).
    # JSON(레짐/1:2:6) 전략은 백본을 절대 안 바꾸므로 항상 False.
    backbone_changed = Column(Boolean, nullable=False, default=False)
    error = Column(Text, nullable=True)  # 이 종목만 실행 실패했을 때의 메시지 (배치 전체는 계속 진행)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    run = relationship("StrategyTuningRun", back_populates="results")

    def __repr__(self) -> str:
        return f"<StrategyTuningResult id={self.id} run_id={self.run_id} ticker={self.ticker!r}>"


class GeminiCallLog(Base):
    """core.gemini_client.generate_content() 호출 시도 이력 (우측 상단 사용량 배지 표시용, core.theme).

    Google 무료 티어는 잔여 할당량을 조회하는 API가 없어, 앱이 자체적으로 시도 결과를 기록해
    "오늘 몇 번 시도했는지/몇 번 한도초과(429)로 막혔는지"를 근사적으로 보여주는 용도로만 쓴다.
    """

    __tablename__ = "gemini_call_log"

    id = Column(Integer, primary_key=True)
    called_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    model = Column(String(50), nullable=False)
    key_label = Column(String(20), nullable=False)  # 실제 키 값은 저장하지 않고 "key1"/"key2"처럼만 표기
    status = Column(String(20), nullable=False)  # "ok" | "quota_exceeded" | "error"
    error_message = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<GeminiCallLog id={self.id} model={self.model!r} status={self.status!r}>"
