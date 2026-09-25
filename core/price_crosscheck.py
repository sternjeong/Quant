"""모듈: Alpaca 가격 교차검증 (2026-09-24 추가).

목적: 이 저장소의 모든 가격은 yfinance 단일 소스(core.market_data, auto_adjust=False)다.
단일 소스이므로 "잘못된 종가 / 누락된 거래일 / 분할 미반영" 같은 오류를 스스로 잡을 방법이
없다. core.data_integrity의 기존 체크는 한 소스 안에서의 이상치(0원, 급변, stale)만 보고
**다른 소스와 대조하지는 못한다**. 이 모듈은 Alpaca Market Data API(일봉)를 **읽기 전용
2차 소스**로 붙여, 같은 심볼·같은 날짜의 두 소스 값을 대조해 불일치를 플래그로 보고한다.

설계 원칙
---------
- 기존 yfinance 경로(core.market_data)는 전혀 건드리지 않는다. 이 모듈은 core.market_data를
  읽기만 하고, 전략/백테스트 가격 소스는 여전히 yfinance 단독이다.
- **판정이 아니라 플래그**다. 불일치가 나와도 "yfinance가 틀렸다"고 단정하지 않는다
  (아래 IEX/SIP 한계 참고). 사람이 보고 판단할 근거만 구조화해 내놓는다.
- 조용한 통과 금지: 조회 실패·키 없음·데이터 없음은 전부 ``unavailable`` 판정으로 드러낸다.
  (성공한 대조가 0건인데 "이상 없음"으로 끝나는 경로는 없다.)

IEX / SIP 한계 (중요 계약)
--------------------------
Alpaca 무료(paper) 티어의 주식 시장데이터는 기본적으로 **IEX 피드**다. IEX는 미국 전체
거래량의 소수 지분만 체결하는 단일 거래소이므로:
  - **거래량**은 전체 시장(SIP) 대비 구조적으로 훨씬 작다. 따라서 거래량 차이는 "오류"의
    증거가 될 수 없고, 참고 지표로만 기록한다(심각도 info 고정).
  - **종가**도 SIP 공식 종가(Nasdaq/NYSE 마감 경매 가격)가 아니라 IEX에서의 마지막 체결가일
    수 있어, 유동성이 낮은 종목일수록 수 bp~수십 bp 차이가 정상적으로 발생한다.
  - **조회 가능한 과거 기간에 제한**이 있을 수 있다(구독 등급에 따라 최근 N년 또는 IEX 데이터
    시작 시점 이전은 비어서 돌아온다). 과거 구간이 비어 있는 것은 "yfinance에 없는 봉"이
    아니라 대개 **피드 커버리지 한계**이므로, 그런 경우도 오류가 아니라 플래그다.
  - **분할 조정 정책**이 yfinance와 다를 수 있다. 이 모듈은 ``adjustment=split``(분할만 조정,
    배당 미조정)을 기본으로 요청한다 — core.market_data가 auto_adjust=False로 받는 yfinance
    종가 역시 분할은 소급 반영되고 배당은 반영되지 않는 값이라 이 조합이 가장 가깝다.
    다만 Alpaca가 실제로 분할 조정본을 주는지는 **사람이 scripts/verify_price_crosscheck.py로
    확인해야 하는 사항**이며(AAPL 2020-08-31 4:1 분할 구간 단계 포함), 확인 전까지는 이
    모듈의 분할 의심 플래그는 "둘 중 한쪽의 조정 정책 차이일 수 있음"을 뜻한다.
이 한계는 결과 메타(``meta["limitations"]``, ``FEED_LIMITATIONS``)에도 그대로 실려 나간다.

자격증명
--------
환경변수 ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET에서만 읽는다
(core.paper_execution.AlpacaPaperBroker와 같은 방식). 값은 출력하지도 저장하지도 않는다.

캐시
----
core.market_data의 관례(data/cache/ 아래 파일, mtime 기반 TTL)를 따른다. 응답은 심볼·구간·
피드·조정정책별로 JSON 파일 하나에 저장하고, TTL 안이면 네트워크를 타지 않는다.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "alpaca"

ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
BARS_PATH_TEMPLATE = "/v2/stocks/{symbol}/bars"

KEY_ENV = "ALPACA_PAPER_API_KEY"
SECRET_ENV = "ALPACA_PAPER_API_SECRET"

# 무료 티어 기본 피드. 유료 구독이 있는 환경에서만 "sip"로 바꿔 쓸 수 있게 인자로 노출한다.
DEFAULT_FEED = "iex"
# 분할만 조정(배당 미조정) — yfinance auto_adjust=False 종가와 가장 가까운 조합. 위 docstring 참고.
DEFAULT_ADJUSTMENT = "split"

DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60  # core.market_data.DEFAULT_CACHE_TTL_SECONDS와 동일하게 6시간
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_PAGE_LIMIT = 10_000  # Alpaca bars 엔드포인트의 페이지당 최대치
MAX_PAGES = 50  # 페이지네이션 무한루프 방지 상한 (일봉 기준 사실상 도달 불가)

# --- 레이트리밋/재시도 -------------------------------------------------------
# 무료 티어는 분당 200요청 수준이라 일상적인 소수 심볼 대조에서는 걸리지 않지만, 429/5xx가
# 오면 지수 백오프로 몇 번만 재시도하고 그래도 안 되면 unavailable로 격리한다(전체 실패 금지).
RETRY_STATUS = (429, 500, 502, 503, 504)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0
# 심볼 사이에 두는 최소 간격(초). 여러 심볼을 연속 조회할 때 레이트리밋을 스스로 피하기 위한 값.
INTER_SYMBOL_SLEEP_SECONDS = 0.15

# --- 임계값 -------------------------------------------------------------------
# 종가 차이(bp = 0.01%). IEX 마지막 체결가와 SIP 공식 종가는 유동성이 좋은 대형주라도 수 bp
# 차이가 나는 것이 정상이므로, 그 정상 잡음 구간(<=25bp = 0.25%)은 match로 본다.
CLOSE_MATCH_BP = 25.0
# 25bp~150bp(0.25%~1.5%)는 minor_diff — 저유동성 종목의 피드 차이로 설명 가능한 범위이며
# 단독으로는 데이터 오류라고 볼 수 없다. 추세적으로 반복되면 사람이 볼 값.
CLOSE_MINOR_BP = 150.0
# 150bp를 넘으면 major_diff — 이 정도면 피드 차이만으로는 설명하기 어렵고, 잘못된 종가나
# 조정 정책 불일치(분할/역분할)를 의심할 구간이다.

# 분할 의심: 하루 만에 ±40% 이상 변동이 **한쪽 소스에만** 나타나는 경우. 4:1 분할은 -75%,
# 2:1은 -50%, 3:2는 -33%로 나타나므로 40%는 흔한 2:1/4:1/3:1을 확실히 잡으면서 실적 쇼크
# 수준의 정상 급변(대개 30% 이내)과는 구분되는 선이다. 3:2처럼 40% 미만인 분할은 이 규칙으로는
# 안 잡히지만, 그 경우 종가 차이가 major_diff로 먼저 드러난다.
SPLIT_SUSPECT_RETURN_ABS = 0.40
# 위 급변이 "한쪽에만" 있다고 보는 기준: 반대쪽 소스의 같은 날 수익률 절대값이 이보다 작을 것.
SPLIT_SUSPECT_OTHER_SIDE_MAX = 0.10

# 거래량 괴리: IEX 피드는 전체 시장의 일부만 담으므로 큰 차이가 **정상**이다. 따라서 이
# 임계값은 오류 판정이 아니라 "이 종목은 IEX 커버리지가 특히 낮다"는 참고용 표시다.
VOLUME_RATIO_REPORT_BELOW = 0.02   # Alpaca 거래량이 yfinance의 2% 미만
VOLUME_RATIO_REPORT_ABOVE = 5.0    # 또는 5배 초과(= 조정/집계 정책 차이 의심)

VERDICT_MATCH = "match"
VERDICT_MINOR = "minor_diff"
VERDICT_MAJOR = "major_diff"
VERDICT_MISSING_ALPACA = "missing_in_alpaca"
VERDICT_MISSING_YFINANCE = "missing_in_yfinance"
VERDICT_UNAVAILABLE = "unavailable"

ALL_VERDICTS = (
    VERDICT_MATCH, VERDICT_MINOR, VERDICT_MAJOR,
    VERDICT_MISSING_ALPACA, VERDICT_MISSING_YFINANCE, VERDICT_UNAVAILABLE,
)

FEED_LIMITATIONS = {
    "feed_note": (
        "Alpaca 무료 티어는 IEX 피드다. 거래량은 전체 시장(SIP) 대비 구조적으로 작고, 종가도 "
        "SIP 공식 마감가가 아닌 IEX 마지막 체결가일 수 있다."
    ),
    "history_note": (
        "구독 등급에 따라 조회 가능한 과거 기간에 제한이 있을 수 있다. 과거 구간이 비어 있는 것은 "
        "대개 피드 커버리지 한계이며 yfinance 오류의 증거가 아니다."
    ),
    "adjustment_note": (
        "요청 adjustment는 분할 조정(배당 미조정)으로, yfinance auto_adjust=False와 맞춘 값이다. "
        "Alpaca가 실제로 분할 조정본을 주는지는 scripts/verify_price_crosscheck.py로 사람이 확인해야 한다."
    ),
    "interpretation": (
        "불일치는 플래그일 뿐 판정이 아니다. 어느 소스가 옳은지 이 모듈은 결정하지 않는다."
    ),
}


class AlpacaDataUnavailable(Exception):
    """Alpaca 일봉을 가져오지 못했음을 나타낸다(키 없음/네트워크/HTTP 오류/응답 파싱 실패).

    이 예외는 항상 unavailable 판정으로 변환되어 결과에 남는다 — 조용히 무시되지 않는다.
    """


@dataclass(frozen=True)
class AlpacaCredentials:
    """환경변수에서만 읽는 자격증명. 값은 repr/로그에 절대 싣지 않는다."""

    key: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "AlpacaCredentials":
        source = env if env is not None else os.environ
        key = source.get(KEY_ENV, "") or ""
        secret = source.get(SECRET_ENV, "") or ""
        if not key or not secret:
            raise AlpacaDataUnavailable(
                f"{KEY_ENV}/{SECRET_ENV} 환경변수가 없어 Alpaca 교차검증을 할 수 없습니다."
            )
        return cls(key, secret)

    def headers(self) -> dict[str, str]:
        return {"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret}

    def __repr__(self) -> str:  # pragma: no cover - 방어용
        return "AlpacaCredentials(<redacted>)"


def credentials_available(env: Optional[dict] = None) -> bool:
    """키가 환경에 있는지만 확인한다(값은 반환하지 않는다)."""
    source = env if env is not None else os.environ
    return bool(source.get(KEY_ENV)) and bool(source.get(SECRET_ENV))


# --------------------------------------------------------------------------- #
# 캐시
# --------------------------------------------------------------------------- #

def _cache_path(symbol: str, start: str, end: str, feed: str, adjustment: str) -> Path:
    safe = symbol.replace("/", "-").replace(":", "-").upper()
    return CACHE_DIR / f"{safe}_1d_{start}_{end}_{feed}_{adjustment}.json"


def _read_cache(path: Path, ttl: int) -> Optional[list[dict]]:
    if ttl <= 0 or not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime >= ttl:
            return None
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        bars = payload.get("bars")
        return bars if isinstance(bars, list) else None
    except Exception:
        return None  # 손상된 캐시는 없는 것으로 취급하고 다시 받아온다


def _write_cache(path: Path, symbol: str, bars: list[dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump({"symbol": symbol, "bars": bars}, fh)
    except Exception:
        pass  # 캐시 쓰기 실패는 조회 결과에 영향을 주지 않는다


# --------------------------------------------------------------------------- #
# Alpaca 일봉 조회
# --------------------------------------------------------------------------- #

def fetch_alpaca_daily_bars(
    symbol: str,
    start: str,
    end: str,
    *,
    credentials: Optional[AlpacaCredentials] = None,
    feed: str = DEFAULT_FEED,
    adjustment: str = DEFAULT_ADJUSTMENT,
    use_cache: bool = True,
    cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
    session: Any = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """Alpaca 일봉(1Day)을 [{t,o,h,l,c,v}, ...] 리스트로 반환한다(페이지네이션 포함).

    Args:
        symbol: 티커(대문자).
        start, end: "YYYY-MM-DD" (양끝 포함 의도; end 당일 봉까지 요청한다).
        credentials: None이면 환경변수에서 읽는다(없으면 AlpacaDataUnavailable).
        feed: 기본 "iex"(무료 티어). docstring의 IEX/SIP 한계 참고.
        adjustment: 기본 "split".
        use_cache/cache_ttl: data/cache/alpaca 아래 JSON 캐시 사용 여부와 TTL(초).
        session: requests 호환 객체(테스트 주입용). None이면 requests 모듈.
        sleep_fn: 백오프 대기 함수(테스트 주입용).

    Raises:
        AlpacaDataUnavailable: 키 없음/HTTP 오류/재시도 소진/응답 파싱 실패.
    """
    path = _cache_path(symbol, start, end, feed, adjustment)
    if use_cache:
        cached = _read_cache(path, cache_ttl)
        if cached is not None:
            return cached

    if credentials is None:
        credentials = AlpacaCredentials.from_env()

    http = session if session is not None else requests
    url = ALPACA_DATA_BASE_URL + BARS_PATH_TEMPLATE.format(symbol=symbol)

    bars: list[dict] = []
    page_token: Optional[str] = None
    for _ in range(MAX_PAGES):
        params = {
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "limit": DEFAULT_PAGE_LIMIT,
            "adjustment": adjustment,
            "feed": feed,
        }
        if page_token:
            params["page_token"] = page_token

        payload = _request_with_retry(http, url, params, credentials, sleep_fn, symbol)
        page_bars = payload.get("bars")
        if page_bars is None:
            page_bars = []
        if isinstance(page_bars, dict):  # 멀티심볼 응답 형태 방어
            page_bars = page_bars.get(symbol, []) or []
        if not isinstance(page_bars, list):
            raise AlpacaDataUnavailable(f"{symbol}: Alpaca 응답의 bars 형식을 해석할 수 없습니다.")
        bars.extend(page_bars)

        page_token = payload.get("next_page_token")
        if not page_token:
            break
    else:  # pragma: no cover - MAX_PAGES 도달은 사실상 불가
        raise AlpacaDataUnavailable(f"{symbol}: 페이지네이션이 {MAX_PAGES}페이지를 초과했습니다.")

    if use_cache:
        _write_cache(path, symbol, bars)
    return bars


def _request_with_retry(
    http: Any,
    url: str,
    params: dict,
    credentials: AlpacaCredentials,
    sleep_fn: Callable[[float], None],
    symbol: str,
) -> dict:
    last_error = ""
    for attempt in range(MAX_RETRIES):
        try:
            response = http.get(url, headers=credentials.headers(), params=params,
                                timeout=DEFAULT_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - 네트워크 계열 전부
            last_error = f"요청 실패: {type(exc).__name__}"
            if attempt == MAX_RETRIES - 1:
                break
            sleep_fn(RETRY_BACKOFF_SECONDS * (2 ** attempt))
            continue

        status = getattr(response, "status_code", None)
        if status in RETRY_STATUS:
            last_error = f"HTTP {status}"
            if attempt == MAX_RETRIES - 1:
                break
            sleep_fn(RETRY_BACKOFF_SECONDS * (2 ** attempt))
            continue
        if status is not None and status >= 400:
            # 401/403(권한), 404(심볼 없음) 등은 재시도해도 같으므로 즉시 격리한다.
            raise AlpacaDataUnavailable(f"{symbol}: Alpaca 응답 HTTP {status}.")

        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            raise AlpacaDataUnavailable(f"{symbol}: Alpaca 응답을 JSON으로 해석할 수 없습니다.")
        if not isinstance(payload, dict):
            raise AlpacaDataUnavailable(f"{symbol}: Alpaca 응답이 객체가 아닙니다.")
        return payload

    raise AlpacaDataUnavailable(f"{symbol}: Alpaca 조회를 재시도 {MAX_RETRIES}회 후 포기했습니다({last_error}).")


# --------------------------------------------------------------------------- #
# 정규화 & 대조
# --------------------------------------------------------------------------- #

def _bar_date(bar: dict) -> Optional[str]:
    raw = bar.get("t")
    if not raw:
        return None
    text = str(raw)
    # "2020-08-31T04:00:00Z" 또는 "2020-08-31" 모두 날짜 부분만 쓴다.
    return text[:10] if len(text) >= 10 else None


def normalize_alpaca_bars(bars: Iterable[dict]) -> dict[str, dict]:
    """Alpaca bars 리스트를 {"YYYY-MM-DD": {"close": float, "volume": float}}로 정규화한다."""
    out: dict[str, dict] = {}
    for bar in bars or []:
        day = _bar_date(bar)
        if day is None or bar.get("c") is None:
            continue
        try:
            close = float(bar["c"])
        except (TypeError, ValueError):
            continue
        try:
            volume = float(bar.get("v")) if bar.get("v") is not None else None
        except (TypeError, ValueError):
            volume = None
        out[day] = {"close": close, "volume": volume}
    return out


def normalize_yfinance_frame(df: Optional[pd.DataFrame]) -> dict[str, dict]:
    """core.market_data가 주는 DataFrame을 {"YYYY-MM-DD": {"close", "volume"}}로 정규화한다."""
    out: dict[str, dict] = {}
    if df is None or getattr(df, "empty", True) or "Close" not in df.columns:
        return out
    for idx, row in df.iterrows():
        try:
            ts = pd.Timestamp(idx)
        except Exception:
            continue
        close = row.get("Close")
        if close is None or pd.isna(close):
            continue
        volume = row.get("Volume") if "Volume" in df.columns else None
        try:
            volume = float(volume) if volume is not None and not pd.isna(volume) else None
        except (TypeError, ValueError):
            volume = None
        out[ts.strftime("%Y-%m-%d")] = {"close": float(close), "volume": volume}
    return out


def _diff_bp(yf_close: float, alpaca_close: float) -> float:
    """yfinance 종가 대비 Alpaca 종가 차이를 bp(0.01%)로. 부호는 Alpaca가 높으면 +."""
    if yf_close == 0:
        return float("inf")
    return (alpaca_close - yf_close) / yf_close * 10_000.0


def _classify_bp(abs_bp: float) -> str:
    if abs_bp <= CLOSE_MATCH_BP:
        return VERDICT_MATCH
    if abs_bp <= CLOSE_MINOR_BP:
        return VERDICT_MINOR
    return VERDICT_MAJOR


def _daily_returns(series: dict[str, dict]) -> dict[str, float]:
    """정규화된 {날짜: {...}}에서 날짜순 연속 종가 수익률을 계산한다."""
    days = sorted(series)
    out: dict[str, float] = {}
    for prev, cur in zip(days, days[1:]):
        prev_close = series[prev]["close"]
        if prev_close:
            out[cur] = series[cur]["close"] / prev_close - 1.0
    return out


def compare_series(
    symbol: str,
    yf_series: dict[str, dict],
    alpaca_series: dict[str, dict],
) -> dict:
    """정규화된 두 소스를 날짜 단위로 대조해 판정 리스트와 요약을 반환한다.

    Returns:
        {"symbol", "days": [ {date, verdict, ...}, ... ], "summary": {verdict: count},
         "split_suspects": [...], "volume_flags": [...], "overlap_days": int}
    """
    days = sorted(set(yf_series) | set(alpaca_series))
    yf_returns = _daily_returns(yf_series)
    alpaca_returns = _daily_returns(alpaca_series)

    rows: list[dict] = []
    split_suspects: list[dict] = []
    volume_flags: list[dict] = []
    overlap = 0

    for day in days:
        yf_row = yf_series.get(day)
        ap_row = alpaca_series.get(day)

        if yf_row is not None and ap_row is None:
            rows.append({
                "date": day, "verdict": VERDICT_MISSING_ALPACA,
                "yfinance_close": yf_row["close"], "alpaca_close": None, "diff_bp": None,
                "note": "Alpaca(IEX)에 해당 거래일 봉이 없습니다 — 피드 커버리지 한계일 수 있습니다.",
            })
            continue
        if yf_row is None and ap_row is not None:
            rows.append({
                "date": day, "verdict": VERDICT_MISSING_YFINANCE,
                "yfinance_close": None, "alpaca_close": ap_row["close"], "diff_bp": None,
                "note": "yfinance 캐시에 해당 거래일이 없습니다.",
            })
            continue

        overlap += 1
        bp = _diff_bp(yf_row["close"], ap_row["close"])
        verdict = _classify_bp(abs(bp))
        row = {
            "date": day, "verdict": verdict,
            "yfinance_close": yf_row["close"], "alpaca_close": ap_row["close"],
            "diff_bp": round(bp, 4) if bp not in (float("inf"), float("-inf")) else None,
            "yfinance_volume": yf_row.get("volume"), "alpaca_volume": ap_row.get("volume"),
        }

        # 분할 의심: 하루 ±40% 이상 변동이 한쪽에만 있는 경우.
        yr = yf_returns.get(day)
        ar = alpaca_returns.get(day)
        if yr is not None and ar is not None:
            one_side = None
            if abs(yr) >= SPLIT_SUSPECT_RETURN_ABS and abs(ar) < SPLIT_SUSPECT_OTHER_SIDE_MAX:
                one_side = "yfinance"
            elif abs(ar) >= SPLIT_SUSPECT_RETURN_ABS and abs(yr) < SPLIT_SUSPECT_OTHER_SIDE_MAX:
                one_side = "alpaca"
            if one_side:
                suspect = {
                    "date": day, "symbol": symbol, "jump_side": one_side,
                    "yfinance_return": round(yr, 6), "alpaca_return": round(ar, 6),
                    "note": ("한쪽 소스에서만 하루 ±40% 이상 변동 — 분할 조정 정책 차이 의심. "
                             "어느 쪽이 옳은지는 이 모듈이 판정하지 않습니다."),
                }
                split_suspects.append(suspect)
                row["split_suspect"] = True

        # 거래량 괴리(참고용 — IEX 특성상 큰 차이는 정상).
        yv, av = yf_row.get("volume"), ap_row.get("volume")
        if yv and av is not None and yv > 0:
            ratio = av / yv
            if ratio < VOLUME_RATIO_REPORT_BELOW or ratio > VOLUME_RATIO_REPORT_ABOVE:
                flag = {
                    "date": day, "symbol": symbol, "ratio": round(ratio, 6),
                    "severity": "info",
                    "note": "IEX 피드는 전체 시장의 일부만 담으므로 거래량 차이는 오류 증거가 아닙니다.",
                }
                volume_flags.append(flag)
                row["volume_ratio"] = round(ratio, 6)

        rows.append(row)

    summary = {verdict: 0 for verdict in ALL_VERDICTS}
    for row in rows:
        summary[row["verdict"]] += 1

    return {
        "symbol": symbol, "days": rows, "summary": summary,
        "split_suspects": split_suspects, "volume_flags": volume_flags,
        "overlap_days": overlap,
    }


def crosscheck_symbol(
    symbol: str,
    start: str,
    end: str,
    *,
    yf_fetch_fn: Optional[Callable[..., Any]] = None,
    alpaca_fetch_fn: Optional[Callable[..., list[dict]]] = None,
    credentials: Optional[AlpacaCredentials] = None,
    feed: str = DEFAULT_FEED,
    adjustment: str = DEFAULT_ADJUSTMENT,
    use_cache: bool = True,
) -> dict:
    """심볼 하나를 [start, end] 구간에서 교차검증한다. 실패는 unavailable로 격리한다.

    Returns:
        compare_series()의 결과 dict, 또는 조회 실패 시
        {"symbol", "days": [], "summary": {... "unavailable": 1}, "unavailable_reason": str, ...}
    """
    def _unavailable(reason: str) -> dict:
        summary = {verdict: 0 for verdict in ALL_VERDICTS}
        summary[VERDICT_UNAVAILABLE] = 1
        return {
            "symbol": symbol, "days": [], "summary": summary,
            "split_suspects": [], "volume_flags": [], "overlap_days": 0,
            "unavailable_reason": reason,
        }

    try:
        if alpaca_fetch_fn is not None:
            bars = alpaca_fetch_fn(symbol, start, end)
        else:
            bars = fetch_alpaca_daily_bars(
                symbol, start, end, credentials=credentials, feed=feed,
                adjustment=adjustment, use_cache=use_cache,
            )
    except AlpacaDataUnavailable as exc:
        return _unavailable(str(exc))
    except Exception as exc:  # noqa: BLE001 - 어떤 실패도 조용히 통과시키지 않는다
        return _unavailable(f"{symbol}: Alpaca 조회 중 예외 {type(exc).__name__}.")

    try:
        if yf_fetch_fn is None:
            from core.market_data import get_price_history as yf_fetch_fn  # 읽기 전용 사용
        df = yf_fetch_fn(symbol, start=start, end=end, interval="1d")
    except Exception as exc:  # noqa: BLE001
        return _unavailable(f"{symbol}: yfinance 조회 중 예외 {type(exc).__name__}.")

    yf_series = normalize_yfinance_frame(df)
    alpaca_series = normalize_alpaca_bars(bars)

    if not yf_series and not alpaca_series:
        return _unavailable(f"{symbol}: 두 소스 모두 {start}~{end} 구간 데이터가 없습니다.")

    return compare_series(symbol, yf_series, alpaca_series)


def crosscheck_symbols(
    symbols: list[str],
    start: str,
    end: str,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> dict:
    """여러 심볼을 대조한다. 한 심볼의 실패가 다른 심볼을 막지 않는다(부분 실패 격리).

    Returns:
        {"start", "end", "symbols": {symbol: result}, "summary": {verdict: count},
         "meta": {...한계 명시...}}
    """
    results: dict[str, dict] = {}
    for i, symbol in enumerate(symbols):
        if i > 0 and INTER_SYMBOL_SLEEP_SECONDS > 0:
            sleep_fn(INTER_SYMBOL_SLEEP_SECONDS)
        results[symbol] = crosscheck_symbol(symbol, start, end, **kwargs)

    summary = {verdict: 0 for verdict in ALL_VERDICTS}
    for result in results.values():
        for verdict, count in result["summary"].items():
            summary[verdict] = summary.get(verdict, 0) + count

    return {
        "start": start, "end": end, "symbols": results, "summary": summary,
        "meta": {
            "source": "alpaca_market_data_v2_bars",
            "feed": kwargs.get("feed", DEFAULT_FEED),
            "adjustment": kwargs.get("adjustment", DEFAULT_ADJUSTMENT),
            "limitations": dict(FEED_LIMITATIONS),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


# --------------------------------------------------------------------------- #
# core.data_integrity 연결용 (옵트인)
# --------------------------------------------------------------------------- #

# 교차검증 기본 조회 구간(달력일). 최근 30일이면 IEX 커버리지가 확실하면서 거래일 ~20일을
# 확보해 단발성 잡음과 추세적 불일치를 구분할 수 있다.
CROSSCHECK_LOOKBACK_CALENDAR_DAYS = 30
# 한 번에 대조할 심볼 수 상한(야간 잡 실행시간·레이트리밋 보호).
CROSSCHECK_MAX_SYMBOLS = 5


def _crosscheck_finding(check: str, severity: str, detail: str, ticker: Optional[str] = None) -> dict:
    return {"check": check, "severity": severity, "detail": detail, "ticker": ticker}


def check_price_crosscheck(
    tickers: Optional[list[str]] = None,
    today: Optional[datetime] = None,
    *,
    crosscheck_fn: Optional[Callable[..., dict]] = None,
    env: Optional[dict] = None,
    max_symbols: int = CROSSCHECK_MAX_SYMBOLS,
    **kwargs: Any,
) -> list[dict]:
    """Alpaca 교차검증을 core.data_integrity finding 형식으로 변환한다(옵트인 전용).

    키가 없으면 severity="info"인 finding 하나만 돌려주고 끝낸다 — 키 없는 환경에서 경보를
    만들지 않기 위함이며, 애초에 이 체크는 기본적으로 실행되지 않는다(data_integrity의
    enable_price_crosscheck=False 기본값).

    심각도 매핑:
        major_diff / missing_in_yfinance -> warning (사람이 볼 불일치 플래그)
        unavailable                      -> warning (조용한 통과 금지)
        minor_diff / missing_in_alpaca   -> info    (IEX 피드 차이로 설명 가능)
    """
    if today is None:
        today = datetime.now()
    if not credentials_available(env):
        return [_crosscheck_finding(
            "price_crosscheck_skipped", "info",
            f"{KEY_ENV}/{SECRET_ENV}가 없어 Alpaca 교차검증을 건너뜁니다.",
        )]

    if tickers is None:
        try:
            from core.data_integrity import _champion_priority_tickers

            tickers = _champion_priority_tickers()
        except Exception:
            tickers = []
    tickers = list(tickers)[:max_symbols]
    if not tickers:
        return [_crosscheck_finding("price_crosscheck_skipped", "info", "교차검증할 티커가 없습니다.")]

    start = (today - timedelta(days=CROSSCHECK_LOOKBACK_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    fn = crosscheck_fn or crosscheck_symbols
    try:
        report = fn(tickers, start, end, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return [_crosscheck_finding(
            "price_crosscheck_unavailable", "warning",
            f"Alpaca 교차검증 실행이 실패했습니다: {type(exc).__name__}.",
        )]

    findings: list[dict] = []
    for symbol, result in (report.get("symbols") or {}).items():
        summary = result.get("summary") or {}
        if summary.get(VERDICT_UNAVAILABLE):
            findings.append(_crosscheck_finding(
                "price_crosscheck_unavailable", "warning",
                f"{symbol}: Alpaca 교차검증 불가 — {result.get('unavailable_reason', '사유 미상')}",
                symbol,
            ))
            continue

        if summary.get(VERDICT_MAJOR):
            major_days = [d for d in result.get("days", []) if d["verdict"] == VERDICT_MAJOR]
            worst = max(major_days, key=lambda d: abs(d.get("diff_bp") or 0.0))
            finding = _crosscheck_finding(
                "price_crosscheck_major_diff", "warning",
                (f"{symbol}: 종가 큰 불일치 {summary[VERDICT_MAJOR]}일 "
                 f"(최대 {worst['date']} {worst.get('diff_bp')}bp). 어느 소스가 옳은지는 미판정 — "
                 "IEX/SIP 피드 차이 가능성 포함."),
                symbol,
            )
            # (2026-09-25) 반복 알림 억제용 구조화 필드: 불일치 거래일 목록(core.data_integrity 가 (종목, 날짜)로 중복 판단).
            finding["dates"] = sorted({str(d["date"]) for d in major_days if d.get("date")})
            findings.append(finding)
        if summary.get(VERDICT_MISSING_YFINANCE):
            findings.append(_crosscheck_finding(
                "price_crosscheck_missing_in_yfinance", "warning",
                f"{symbol}: Alpaca에만 있고 yfinance 캐시에 없는 거래일 {summary[VERDICT_MISSING_YFINANCE]}건.",
                symbol,
            ))
        if summary.get(VERDICT_MISSING_ALPACA):
            findings.append(_crosscheck_finding(
                "price_crosscheck_missing_in_alpaca", "info",
                (f"{symbol}: yfinance에만 있고 Alpaca(IEX)에 없는 거래일 "
                 f"{summary[VERDICT_MISSING_ALPACA]}건 — 피드 커버리지 한계일 수 있습니다."),
                symbol,
            ))
        if summary.get(VERDICT_MINOR):
            findings.append(_crosscheck_finding(
                "price_crosscheck_minor_diff", "info",
                f"{symbol}: 경미한 종가 차이 {summary[VERDICT_MINOR]}일(25~150bp).",
                symbol,
            ))
        for suspect in result.get("split_suspects") or []:
            finding = _crosscheck_finding(
                "price_crosscheck_split_suspect", "warning",
                (f"{symbol}: {suspect['date']} 분할 조정 의심 — {suspect['jump_side']} 쪽만 "
                 f"하루 {suspect['yfinance_return'] if suspect['jump_side'] == 'yfinance' else suspect['alpaca_return']:+.1%} 변동."),
                symbol,
            )
            finding["dates"] = [str(suspect["date"])]
            findings.append(finding)

    if not findings:
        findings.append(_crosscheck_finding(
            "price_crosscheck_ok", "info",
            f"{len(tickers)}개 티커 Alpaca 교차검증 이상 없음(대조 성공).",
        ))
    return findings
