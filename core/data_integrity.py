"""모듈: 야간 데이터 무결성 체크 (2026-09-19 추가).

목적: yfinance/FRED/뉴스 파이프라인이 "에러 없이 조용히" 이상한 데이터를 캐시에 남기는 경우를
잡아내기 위한 것 — 예외를 던지는 실패는 이미 각 core.* 모듈이 로그를 남기지만, 0원짜리 종가나
반나절 지연된 FRED 캐시처럼 "그냥 이상한 값"은 아무도 알아채지 못한 채 전략 신호에 스며들 수
있다. 이 모듈은 새 계산 로직을 추가하지 않는다 — core.market_data/core.fred_data/core.news_digest가
이미 저장해둔 데이터를 읽어서 검사만 한다(읽기 전용, side effect 없음).

각 체크는 작은 순수 함수로, 콘솔에 찍지 않고 구조화된 finding(dict)을 리스트로 반환한다 —
scheduler/run_scheduler.py의 data_integrity_check_job()이 그걸 모아 print/텔레그램 알림으로 쓴다.

체크 3종:
    1. check_price_anomalies(): 챔피언 전략 코어+새틀라이트(+시장필터 SPY) 최근 ~10거래일 가격을
       검사 — 종가<=0, |일간수익률|>50%(진짜 데이터 글리치만 잡기 위한 넉넉한 임계값 — 실제
       개별주 폭락/급등도 하루 50%를 넘는 경우는 극히 드물다, 상한가/서킷브레이커 없는 미국
       시장에서도 드묾), 중복 인덱스, 5일 초과(주말 감안) stale 캐시.
    2. check_fred_cache_anomalies(): data/cache/fred_*.csv 파일을 검사 — 비어있음/파싱 불가/
       발표 주기 대비 과도하게 오래된 최신 행. 시리즈마다 발표 주기가 달라(core.fred_data의
       DEFAULT_INDICATORS 참고) 임계값을 다르게 둔다: 일별 시리즈(T10Y2Y/DEXKOUS/BAMLH0A0HYM2/
       T10Y3M)는 10일, 월별 시리즈(FEDFUNDS/CPIAUCSL/UNRATE/INDPRO/CFNAI)는 60일, 분기별(GDPC1)은
       120일(발표 지연 감안) — DEFAULT_CACHE_TTL_SECONDS(24시간)보다 한참 넉넉하게 잡아 "정상
       발표 지연"과 "캐시가 갱신을 멈췄다"를 구분한다.
    3. check_news_digest_anomalies(): 최근 24시간 내 생성된 NewsTickerDigest 행 중 summary가
       비어있거나 공백뿐이거나 source_links가 유효 JSON이 아닌 경우를 잡는다.

(옵트인) 4. core.price_crosscheck의 Alpaca 2차 소스 교차검증 —
    run_integrity_checks(enable_price_crosscheck=True)일 때만 추가로 실행된다. 키가 없거나
    모듈에 문제가 있어도 위 세 체크의 동작/반환 필드는 변하지 않는다(additive).
    2026-09-25부터 야간 잡(scheduler/run_scheduler.py data_integrity_check_job)이 Alpaca 키가 있을 때만
    (price_crosscheck_enabled()) 이를 켠다. 대상은 crosscheck_priority_tickers()(챔피언 코어 top4 ->
    위성 채택 -> SPY 순, 최대 CROSSCHECK_NIGHTLY_MAX_SYMBOLS개). 텔레그램 알림은 major 불일치·분할 의심만,
    그리고 처음 보는 (체크, 종목, 날짜)만 보낸다(route_crosscheck_anomalies / mark_crosscheck_alerted,
    상태 파일 data/cache/price_crosscheck_alert_state.json). 어느 소스가 옳은지는 판정하지 않는다.

run_integrity_checks()가 위 세 체크를 모두 돌려 {"checks": [...], "anomalies": [...], "ok": bool}을
반환한다 — anomalies는 severity가 "critical" 또는 "warning"인 finding만 모은 부분집합(체크가
"이상 없음"으로 반환한 정상 finding은 checks에만 남고 anomalies에는 안 들어간다).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRED_CACHE_DIR = PROJECT_ROOT / "data" / "cache"

# 실제 데이터 글리치(0 나눗셈 오류, 배당 조정 버그, 상장폐지 후 잔여 캐시 등)만 잡기 위한 넉넉한
# 임계값 — 미국 개별주는 상/하한가가 없지만 하루 50%를 넘는 진짜 가격 변동은 극히 드물다(실적
# 쇼크/M&A 발표 정도). 이보다 낮추면 정상적인 변동성 높은 날(예: 어닝 서프라이즈)까지 오탐한다.
PRICE_DAILY_RETURN_ABS_THRESHOLD = 0.50

# 최근 캐시가 이보다 오래되면(주말 포함 달력일 기준) stale로 본다 — 주중 3일 연휴(금~월)에도
# 오탐하지 않도록 5일로 넉넉하게 잡는다.
PRICE_STALE_DAYS = 5

# 가격 이상치 검사용 최근 조회 구간(거래일이 아니라 달력일 기준 lookback — 매일 밤 전체 이력을
# 다시 받을 필요 없이 최근 며칠만 보면 충분하다).
PRICE_LOOKBACK_CALENDAR_DAYS = 15

# FRED 시리즈 발표 주기별 stale 임계값(일). core.fred_data.DEFAULT_INDICATORS 기준 분류.
FRED_DAILY_SERIES = {"T10Y2Y", "DEXKOUS", "BAMLH0A0HYM2", "T10Y3M"}
FRED_MONTHLY_SERIES = {"FEDFUNDS", "CPIAUCSL", "UNRATE", "INDPRO", "CFNAI"}
FRED_QUARTERLY_SERIES = {"GDPC1"}
FRED_STALE_DAYS_DAILY = 10
FRED_STALE_DAYS_MONTHLY = 60
FRED_STALE_DAYS_QUARTERLY = 120
FRED_STALE_DAYS_DEFAULT = 60  # 위 세 분류에 없는 미지의 fred_*.csv 파일용 기본값

NEWS_DIGEST_LOOKBACK_HOURS = 24

# --- 야간 Alpaca 가격 교차 대조 (2026-09-25) --------------------------------------------------
# 대조 종목 상한: 챔피언 코어 top4 + 위성 최대 5 + SPY = 10. 종목당 Alpaca 일봉 요청 1회(6시간 캐시)라
# 야간 요청은 많아야 10회 안팎(재시도 제외)이다.
CROSSCHECK_NIGHTLY_MAX_SYMBOLS = 10
# 텔레그램 알림 대상이 되는 교차 대조 finding(나머지 교차 대조 경고는 로그·결과에만 남긴다).
CROSSCHECK_ALERT_CHECKS = ("price_crosscheck_major_diff", "price_crosscheck_split_suspect")
CROSSCHECK_ALERT_STATE_PATH = PROJECT_ROOT / "data" / "cache" / "price_crosscheck_alert_state.json"
# 상태 파일에서 (종목, 날짜) 키를 지우는 기준(그 거래일로부터 달력일). 교차 대조 조회 구간(30일)보다 길어야
# 지운 날짜가 다시 조회 구간에 들어와 재알림되는 일이 없다.
CROSSCHECK_ALERT_STATE_RETENTION_DAYS = 60


def _finding(check: str, severity: str, detail: str, ticker: Optional[str] = None) -> dict:
    return {"check": check, "severity": severity, "detail": detail, "ticker": ticker}


def _champion_priority_tickers() -> list[str]:
    """챔피언 전략의 현재 핵심 티커(코어+새틀라이트+시장필터)를 우선순위로 반환한다.

    get_current_holdings()가 아직 계산된 적 없으면(캐시 파일 없음) CORE_UNIVERSE로 폴백한다 —
    새틀라이트가 없어도 코어 유니버스 최소한은 매일 밤 검사할 수 있도록.
    """
    from core.champion_strategy import CORE_UNIVERSE, MARKET_FILTER_TICKER, get_current_holdings

    holdings = get_current_holdings()
    if holdings and holdings.get("tickers"):
        tickers = list(holdings["tickers"])
    else:
        tickers = list(CORE_UNIVERSE)

    if MARKET_FILTER_TICKER not in tickers:
        tickers.append(MARKET_FILTER_TICKER)
    return sorted(set(tickers))


def check_price_anomalies(
    tickers: Optional[list[str]] = None,
    fetch_fn: Optional[Callable[[list[str], str], dict[str, pd.DataFrame]]] = None,
    today: Optional[datetime] = None,
) -> list[dict]:
    """가격 데이터 이상치 검사 (종가<=0, |일간수익률|>50%, 중복 인덱스, stale 캐시).

    Args:
        tickers: 검사할 티커 목록. None이면 _champion_priority_tickers()로 결정.
        fetch_fn: (tickers, start) -> {ticker: DataFrame} 함수 (테스트 주입용). None이면
            core.market_data.get_multiple_price_history.
        today: "오늘" 기준 시각(테스트 주입용). None이면 datetime.now().

    Returns: finding 리스트. 정상이면 check="price_ok" severity="info" finding 하나만 포함.
    """
    if tickers is None:
        tickers = _champion_priority_tickers()
    if fetch_fn is None:
        from core.market_data import get_multiple_price_history as fetch_fn
    if today is None:
        today = datetime.now()
    if not tickers:
        return [_finding("price_ok", "info", "검사할 티커가 없습니다.")]

    start = (today - timedelta(days=PRICE_LOOKBACK_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    histories = fetch_fn(tickers, start)

    findings: list[dict] = []
    for ticker in tickers:
        df = histories.get(ticker) if histories else None
        if df is None or df.empty:
            findings.append(_finding("price_missing", "warning", f"{ticker}: 최근 가격 데이터를 가져오지 못했습니다.", ticker))
            continue

        if "Close" not in df.columns:
            findings.append(_finding("price_malformed", "warning", f"{ticker}: 'Close' 컬럼이 없습니다.", ticker))
            continue

        if df.index.duplicated().any():
            dup_count = int(df.index.duplicated().sum())
            findings.append(_finding("price_duplicate_index", "warning", f"{ticker}: 중복된 날짜 인덱스 {dup_count}건.", ticker))

        close = df["Close"].dropna()
        if (close <= 0).any():
            bad_dates = [str(d) for d in close[close <= 0].index]
            findings.append(_finding("price_zero_or_negative", "critical", f"{ticker}: 종가 <= 0인 날짜 {bad_dates}.", ticker))

        if len(close) >= 2:
            daily_return = close.pct_change().dropna()
            spikes = daily_return[daily_return.abs() > PRICE_DAILY_RETURN_ABS_THRESHOLD]
            if not spikes.empty:
                detail_pairs = [f"{d.date() if hasattr(d, 'date') else d}: {v:+.1%}" for d, v in spikes.items()]
                findings.append(
                    _finding(
                        "price_return_spike", "critical",
                        f"{ticker}: 하루 |수익률|>{PRICE_DAILY_RETURN_ABS_THRESHOLD:.0%} 급변 감지 {detail_pairs}.", ticker,
                    )
                )

        if len(df.index) > 0:
            try:
                last_date = pd.Timestamp(df.index[-1])
                if last_date.tzinfo is not None:
                    last_date = last_date.tz_localize(None)
                stale_days = (pd.Timestamp(today) - last_date).days
                if stale_days > PRICE_STALE_DAYS:
                    findings.append(
                        _finding("price_stale", "warning", f"{ticker}: 최신 캐시 데이터가 {stale_days}일 전({last_date.date()})으로 오래됐습니다.", ticker)
                    )
            except Exception:
                pass

    if not findings:
        findings.append(_finding("price_ok", "info", f"{len(tickers)}개 티커 가격 데이터 이상 없음."))
    return findings


def check_fred_cache_anomalies(
    cache_dir: Optional[Path] = None,
    today: Optional[datetime] = None,
) -> list[dict]:
    """FRED 캐시(data/cache/fred_*.csv) 이상치 검사 (비어있음/파싱 불가/발표주기 대비 stale).

    Args:
        cache_dir: fred_*.csv 파일이 있는 디렉토리 (테스트 주입용). None이면 FRED_CACHE_DIR.
        today: "오늘" 기준 시각(테스트 주입용). None이면 datetime.now().

    Returns: finding 리스트. 검사할 파일이 없으면 check="fred_cache_ok" info finding 하나.
    """
    if cache_dir is None:
        cache_dir = FRED_CACHE_DIR
    if today is None:
        today = datetime.now()

    cache_dir = Path(cache_dir)
    files = sorted(cache_dir.glob("fred_*.csv")) if cache_dir.exists() else []

    findings: list[dict] = []
    for path in files:
        series_id = path.stem[len("fred_"):]

        if path.stat().st_size == 0:
            findings.append(_finding("fred_cache_empty", "critical", f"{series_id}: 캐시 파일이 비어있습니다({path.name}).", series_id))
            continue

        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
        except Exception as exc:  # noqa: BLE001
            findings.append(_finding("fred_cache_malformed", "critical", f"{series_id}: 캐시 파일을 읽을 수 없습니다: {exc}.", series_id))
            continue

        if df.empty:
            findings.append(_finding("fred_cache_empty", "critical", f"{series_id}: 캐시에 행이 없습니다({path.name}).", series_id))
            continue

        if series_id in FRED_DAILY_SERIES:
            threshold = FRED_STALE_DAYS_DAILY
        elif series_id in FRED_MONTHLY_SERIES:
            threshold = FRED_STALE_DAYS_MONTHLY
        elif series_id in FRED_QUARTERLY_SERIES:
            threshold = FRED_STALE_DAYS_QUARTERLY
        else:
            threshold = FRED_STALE_DAYS_DEFAULT

        try:
            last_date = pd.Timestamp(df.index[-1])
            if last_date.tzinfo is not None:
                last_date = last_date.tz_localize(None)
            stale_days = (pd.Timestamp(today) - last_date).days
            if stale_days > threshold:
                findings.append(
                    _finding(
                        "fred_cache_stale", "warning",
                        f"{series_id}: 최신 데이터가 {stale_days}일 전({last_date.date()})으로, 예상 발표 주기(임계값 {threshold}일) 대비 오래됐습니다.",
                        series_id,
                    )
                )
        except Exception:
            findings.append(_finding("fred_cache_malformed", "warning", f"{series_id}: 인덱스에서 날짜를 파싱할 수 없습니다.", series_id))

    if not findings:
        if files:
            findings.append(_finding("fred_cache_ok", "info", f"{len(files)}개 FRED 캐시 파일 이상 없음."))
        else:
            findings.append(_finding("fred_cache_ok", "info", "검사할 FRED 캐시 파일이 없습니다."))
    return findings


def check_news_digest_anomalies(
    rows: Optional[list[dict]] = None,
    today: Optional[datetime] = None,
) -> list[dict]:
    """최근 24시간 내 NewsTickerDigest 행의 summary/source_links 무결성 검사.

    Args:
        rows: 검사할 행들(테스트 주입용). 각 행은 {"ticker", "summary", "source_links", "created_at"}
            형태의 dict. None이면 core.db/core.models로 직접 조회한다.
        today: "오늘" 기준 시각(테스트 주입용, rows를 직접 넘길 땐 최근 24시간 필터가 이미
            적용됐다고 가정하고 무시됨). None이면 datetime.now().

    Returns: finding 리스트. 검사 대상 행이 없으면 check="news_digest_ok" info finding 하나.
    """
    if today is None:
        today = datetime.now()

    if rows is None:
        from core.db import get_session
        from core.models import NewsTickerDigest

        cutoff = today - timedelta(hours=NEWS_DIGEST_LOOKBACK_HOURS)
        with get_session() as session:
            db_rows = (
                session.query(NewsTickerDigest)
                .filter(NewsTickerDigest.created_at >= cutoff)
                .all()
            )
            rows = [
                {
                    "ticker": r.ticker,
                    "summary": r.summary,
                    "source_links": r.source_links,
                    "created_at": r.created_at,
                }
                for r in db_rows
            ]

    findings: list[dict] = []
    for row in rows:
        ticker = row.get("ticker")
        summary = row.get("summary") or ""
        if not summary.strip():
            findings.append(_finding("news_digest_empty_summary", "warning", f"{ticker}: 요약이 비어있습니다.", ticker))

        source_links = row.get("source_links")
        try:
            parsed = json.loads(source_links) if source_links is not None else None
            if not isinstance(parsed, list):
                raise ValueError("source_links가 JSON 배열이 아닙니다.")
        except Exception:
            findings.append(_finding("news_digest_invalid_links", "warning", f"{ticker}: source_links가 유효한 JSON이 아닙니다: {source_links!r}.", ticker))

    if not findings:
        findings.append(_finding("news_digest_ok", "info", f"최근 {NEWS_DIGEST_LOOKBACK_HOURS}시간 뉴스 다이제스트 {len(rows)}건 이상 없음."))
    return findings


def run_price_crosscheck_checks(
    tickers: Optional[list[str]] = None,
    today: Optional[datetime] = None,
    **kwargs: Any,
) -> list[dict]:
    """Alpaca 2차 소스 교차검증(옵트인). core.price_crosscheck를 지연 import 한다.

    이 모듈을 임포트하는 것만으로 requests 호출이 일어나지 않게, 그리고 price_crosscheck 쪽
    문제가 기존 세 체크를 절대 깨뜨리지 않게 import와 실행을 모두 감싼다.
    """
    try:
        from core.price_crosscheck import check_price_crosscheck
    except Exception as exc:  # noqa: BLE001
        return [_finding("price_crosscheck_unavailable", "warning",
                         f"교차검증 모듈을 불러오지 못했습니다: {type(exc).__name__}.")]
    try:
        return check_price_crosscheck(tickers=tickers, today=today, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return [_finding("price_crosscheck_unavailable", "warning",
                         f"교차검증 실행이 실패했습니다: {type(exc).__name__}.")]


def run_integrity_checks(
    price_fetch_fn: Optional[Callable[[list[str], str], dict[str, pd.DataFrame]]] = None,
    price_tickers: Optional[list[str]] = None,
    fred_cache_dir: Optional[Path] = None,
    news_rows: Optional[list[dict]] = None,
    today: Optional[datetime] = None,
    enable_price_crosscheck: bool = False,
    crosscheck_kwargs: Optional[dict] = None,
    crosscheck_tickers: Optional[list[str]] = None,
) -> dict:
    """세 가지 체크(가격/FRED 캐시/뉴스 다이제스트)를 모두 실행한다.

    각 인자는 테스트 주입용(실제 스케줄러 호출 시에는 전부 생략해 기본 동작을 쓴다).

    enable_price_crosscheck=True를 주면 네 번째 체크로 core.price_crosscheck의 Alpaca 교차검증을
    **추가로** 돌린다(2026-09-24 추가, additive). 기본값 False인 이유: Alpaca 키가 없는 환경
    (CI, 로컬)에서 기존 동작이 조금도 달라지면 안 되고, 네트워크 호출을 야간 잡에 기본으로
    끼워 넣지 않기 위해서다. 키가 없으면 켜도 info finding 하나만 남고 anomalies는 늘지 않는다.
    crosscheck_tickers를 주면 교차 대조 대상만 따로 정한다(없으면 price_tickers, 그것도 없으면 기본 목록).

    Returns: {"checks": [...모든 finding], "anomalies": [...severity가 critical/warning인 finding만],
        "ok": bool(anomalies가 비어있으면 True)}
    """
    checks: list[dict] = []
    checks.extend(check_price_anomalies(tickers=price_tickers, fetch_fn=price_fetch_fn, today=today))
    checks.extend(check_fred_cache_anomalies(cache_dir=fred_cache_dir, today=today))
    checks.extend(check_news_digest_anomalies(rows=news_rows, today=today))
    if enable_price_crosscheck:
        checks.extend(run_price_crosscheck_checks(
            tickers=crosscheck_tickers if crosscheck_tickers is not None else price_tickers,
            today=today, **(crosscheck_kwargs or {})
        ))

    anomalies = [c for c in checks if c["severity"] in ("critical", "warning")]
    return {"checks": checks, "anomalies": anomalies, "ok": len(anomalies) == 0}


def price_crosscheck_enabled(env: Optional[dict] = None) -> bool:
    """야간 잡이 교차 대조를 켤지: Alpaca 키 두 개가 환경에 있을 때만 True(값은 보지 않는다).
    모듈을 불러오지 못하면 False — 그 경우 야간 잡은 예전과 똑같이 동작한다."""
    try:
        from core.price_crosscheck import credentials_available
    except Exception:  # noqa: BLE001
        return False
    try:
        return bool(credentials_available(env))
    except Exception:  # noqa: BLE001
        return False


def crosscheck_priority_tickers(
    max_symbols: int = CROSSCHECK_NIGHTLY_MAX_SYMBOLS,
    holdings_fn: Optional[Callable[[], Optional[dict]]] = None,
) -> list[str]:
    """교차 대조 대상: 챔피언 코어 top4 -> 위성 채택 -> SPY(시장필터) 순으로 최대 max_symbols개.
    보유 캐시가 없거나 읽기에 실패하면 SPY + CORE_UNIVERSE 앞쪽으로 채운다(전체 유니버스 스캔 금지)."""
    try:
        from core.champion_strategy import CORE_UNIVERSE, MARKET_FILTER_TICKER, get_current_holdings
    except Exception:  # noqa: BLE001
        return []
    holdings = None
    try:
        holdings = (holdings_fn or get_current_holdings)()
    except Exception:  # noqa: BLE001
        holdings = None
    ordered: list[str] = []
    if holdings:
        ordered.extend(holdings.get("core_top4") or [])
        ordered.extend(holdings.get("satellite_selected") or [])
        ordered.append(MARKET_FILTER_TICKER)
    else:
        ordered.append(MARKET_FILTER_TICKER)
        ordered.extend(CORE_UNIVERSE)
    out: list[str] = []
    for t in ordered:
        tick = str(t or "").strip().upper()
        if tick and tick not in out:
            out.append(tick)
    return out[:max(0, int(max_symbols))]


def _crosscheck_alert_keys(finding: dict) -> list[str]:
    dates = finding.get("dates") or []
    if not dates:
        # 날짜가 없으면 detail 전체를 키로 쓴다(같은 문구면 같은 불일치로 본다).
        return [f"{finding.get('check')}|{finding.get('ticker')}|{finding.get('detail')}"]
    return [f"{finding.get('check')}|{finding.get('ticker')}|{d}" for d in dates]


def _load_alert_state(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def route_crosscheck_anomalies(
    anomalies: list[dict],
    *,
    state_path: Optional[Path] = None,
) -> dict:
    """야간 잡의 알림 대상을 가른다.

    Returns: {"base": 교차 대조 이외 anomalies(기존 알림 규칙 그대로),
              "crosscheck_new": 처음 보는 (체크, 종목, 날짜)가 하나라도 있는 major·분할 의심 finding,
              "crosscheck_suppressed": 이미 알린 major·분할 의심 finding,
              "crosscheck_log_only": 알림 대상이 아닌 교차 대조 경고(조회 불가·yfinance 누락 등)}
    교차 대조 finding 이 없으면 상태 파일을 읽지도 않는다.
    """
    base = [a for a in anomalies if not str(a.get("check", "")).startswith("price_crosscheck")]
    cross = [a for a in anomalies if str(a.get("check", "")).startswith("price_crosscheck")]
    alertable = [a for a in cross if a.get("check") in CROSSCHECK_ALERT_CHECKS]
    log_only = [a for a in cross if a.get("check") not in CROSSCHECK_ALERT_CHECKS]
    new: list[dict] = []
    suppressed: list[dict] = []
    if alertable:
        seen = _load_alert_state(state_path or CROSSCHECK_ALERT_STATE_PATH)
        for a in alertable:
            (new if any(k not in seen for k in _crosscheck_alert_keys(a)) else suppressed).append(a)
    return {"base": base, "crosscheck_new": new, "crosscheck_suppressed": suppressed, "crosscheck_log_only": log_only}


def mark_crosscheck_alerted(
    findings: list[dict],
    *,
    state_path: Optional[Path] = None,
    today: Optional[datetime] = None,
) -> None:
    """알림을 보낸 finding 의 (체크, 종목, 날짜) 키를 상태 파일에 적는다. 오래된 키는 정리한다.
    쓰기 실패는 조용히 넘긴다(다음 날 한 번 더 알릴 뿐, 점검 자체를 막지 않는다)."""
    path = Path(state_path or CROSSCHECK_ALERT_STATE_PATH)
    now = today or datetime.now()
    state = _load_alert_state(path)
    for f in findings:
        for k in _crosscheck_alert_keys(f):
            state.setdefault(k, now.strftime("%Y-%m-%d"))
    cutoff = (now - timedelta(days=CROSSCHECK_ALERT_STATE_RETENTION_DAYS)).strftime("%Y-%m-%d")
    kept = {}
    for k, alerted_on in state.items():
        key_date = k.rsplit("|", 1)[-1]
        ref = key_date if len(key_date) == 10 and key_date[4] == "-" else str(alerted_on)
        if ref >= cutoff:
            kept[k] = alerted_on
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(kept, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def format_anomaly_telegram_message(anomalies: list[dict]) -> str:
    """anomalies를 심각도별로 그룹핑한 텔레그램 알림 텍스트로 조립한다."""
    critical = [a for a in anomalies if a["severity"] == "critical"]
    warning = [a for a in anomalies if a["severity"] == "warning"]

    lines = [f"🚨 데이터 무결성 이상 감지 (critical {len(critical)}건, warning {len(warning)}건)"]
    if critical:
        lines.append("\n[critical]")
        lines.extend(f"- {a['detail']}" for a in critical)
    if warning:
        lines.append("\n[warning]")
        lines.extend(f"- {a['detail']}" for a in warning)
    return "\n".join(lines)
