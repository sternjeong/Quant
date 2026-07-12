"""모듈 E: 퀀트 스크리너.

PER/PBR/시가총액/섹터/기술적 지표(RSI, 200일선 위/아래) 등 조건으로 미국 주식(기본: S&P500)을
필터링한다. 종목 유니버스는 위키피디아 S&P500 목록을 받아와 파일 캐시하고, 네트워크 실패 시
저장소에 포함된 최소 대체 목록(_FALLBACK_UNIVERSE)으로 대체한다 (core.nl_strategy 등과 동일한
fallback 패턴).

스크리닝 결과는 core.watchlist.add_to_watchlist 로 바로 관심 티커에 추가할 수 있다.
"""

from __future__ import annotations

import json
import time
from io import StringIO
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests
import yfinance as yf

from core.indicators import sma
from core.market_data import get_price_history

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UNIVERSE_CACHE_FILE = CACHE_DIR / "sp500_universe.csv"
UNIVERSE_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24시간 (구성종목이 자주 바뀌지 않음)

FUNDAMENTALS_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6시간, core.market_data 와 동일 정책

WIKIPEDIA_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; QuantResearchBot/1.0; personal use)"}

# 네트워크로 최신 목록을 가져오지 못했을 때 쓰는 대체용 소규모 목록 (섹터 대표 종목 위주, 정확한 전체
# S&P500 목록이 아님을 UI에 안내한다).
_FALLBACK_UNIVERSE = pd.DataFrame(
    [
        ("AAPL", "Apple Inc.", "Information Technology"),
        ("MSFT", "Microsoft Corp.", "Information Technology"),
        ("NVDA", "NVIDIA Corp.", "Information Technology"),
        ("GOOGL", "Alphabet Inc.", "Communication Services"),
        ("AMZN", "Amazon.com Inc.", "Consumer Discretionary"),
        ("META", "Meta Platforms Inc.", "Communication Services"),
        ("TSLA", "Tesla Inc.", "Consumer Discretionary"),
        ("BRK.B", "Berkshire Hathaway", "Financials"),
        ("JPM", "JPMorgan Chase & Co.", "Financials"),
        ("V", "Visa Inc.", "Financials"),
        ("UNH", "UnitedHealth Group", "Health Care"),
        ("JNJ", "Johnson & Johnson", "Health Care"),
        ("XOM", "Exxon Mobil Corp.", "Energy"),
        ("PG", "Procter & Gamble", "Consumer Staples"),
        ("HD", "Home Depot Inc.", "Consumer Discretionary"),
        ("KO", "Coca-Cola Co.", "Consumer Staples"),
        ("PEP", "PepsiCo Inc.", "Consumer Staples"),
        ("NEE", "NextEra Energy", "Utilities"),
        ("PLD", "Prologis Inc.", "Real Estate"),
        ("LIN", "Linde plc", "Materials"),
    ],
    columns=["Symbol", "Security", "Sector"],
)


def fetch_sp500_from_wikipedia() -> pd.DataFrame:
    """위키피디아에서 S&P500 구성종목 목록을 가져온다. 실패 시 빈 DataFrame."""
    try:
        resp = requests.get(WIKIPEDIA_SP500_URL, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        df = tables[0][["Symbol", "Security", "GICS Sector"]].copy()
        df.columns = ["Symbol", "Security", "Sector"]
        df["Symbol"] = df["Symbol"].str.replace(".", "-", regex=False)  # yfinance 표기(BRK.B -> BRK-B)
        return df
    except Exception:
        return pd.DataFrame(columns=["Symbol", "Security", "Sector"])


def get_universe(use_cache: bool = True, cache_ttl: int = UNIVERSE_CACHE_TTL_SECONDS) -> pd.DataFrame:
    """스크리닝 대상 종목 유니버스(S&P500)를 반환한다.

    캐시가 있고 유효하면 캐시를 쓰고, 없거나 만료됐으면 위키피디아에서 새로 받아 캐시에 저장한다.
    네트워크 실패 시 소규모 대체 목록(_FALLBACK_UNIVERSE)을 반환한다.

    Returns:
        columns: Symbol, Security, Sector
    """
    if use_cache and UNIVERSE_CACHE_FILE.exists():
        age = time.time() - UNIVERSE_CACHE_FILE.stat().st_mtime
        if age < cache_ttl:
            try:
                return pd.read_csv(UNIVERSE_CACHE_FILE)
            except Exception:
                pass

    df = fetch_sp500_from_wikipedia()
    if df.empty:
        if UNIVERSE_CACHE_FILE.exists():
            try:
                return pd.read_csv(UNIVERSE_CACHE_FILE)  # 만료됐어도 없는 것보단 낫다
            except Exception:
                pass
        return _FALLBACK_UNIVERSE.copy()

    if use_cache:
        try:
            df.to_csv(UNIVERSE_CACHE_FILE, index=False)
        except Exception:
            pass
    return df


def _fundamentals_cache_file(ticker: str) -> Path:
    safe = ticker.replace("/", "-")
    return CACHE_DIR / f"fundamentals_{safe}.json"


def get_fundamentals(ticker: str, use_cache: bool = True, cache_ttl: int = FUNDAMENTALS_CACHE_TTL_SECONDS) -> dict:
    """yfinance에서 PER/PBR/시가총액/섹터 등 펀더멘털 정보를 가져온다 (파일 캐시 적용).

    Returns:
        {"ticker", "name", "sector", "per", "pbr", "market_cap"}
        조회 실패한 값은 None (예외를 던지지 않음).
    """
    cache_file = _fundamentals_cache_file(ticker)
    if use_cache and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < cache_ttl:
            try:
                return json.loads(cache_file.read_text())
            except Exception:
                pass

    result = {"ticker": ticker, "name": None, "sector": None, "per": None, "pbr": None, "market_cap": None}
    try:
        info = yf.Ticker(ticker).info
        result["name"] = info.get("longName") or info.get("shortName")
        result["sector"] = info.get("sector")
        result["per"] = info.get("trailingPE")
        result["pbr"] = info.get("priceToBook")
        result["market_cap"] = info.get("marketCap")
    except Exception:
        pass

    if use_cache:
        try:
            cache_file.write_text(json.dumps(result))
        except Exception:
            pass
    return result


def _passes_filters(row: dict, filters: dict[str, Any]) -> bool:
    def _in_range(value: Optional[float], min_key: str, max_key: str) -> bool:
        if value is None:
            return filters.get(min_key) is None and filters.get(max_key) is None
        if filters.get(min_key) is not None and value < filters[min_key]:
            return False
        if filters.get(max_key) is not None and value > filters[max_key]:
            return False
        return True

    if filters.get("sectors") and row.get("sector") not in filters["sectors"]:
        return False
    if not _in_range(row.get("per"), "per_min", "per_max"):
        return False
    if not _in_range(row.get("pbr"), "pbr_min", "pbr_max"):
        return False
    if not _in_range(row.get("market_cap"), "market_cap_min", "market_cap_max"):
        return False
    if not _in_range(row.get("rsi"), "rsi_min", "rsi_max"):
        return False
    if filters.get("above_sma200") is not None:
        if row.get("above_sma200") is None or row["above_sma200"] != filters["above_sma200"]:
            return False
    return True


def screen(
    tickers: Optional[list[str]] = None,
    filters: Optional[dict[str, Any]] = None,
    include_technicals: bool = True,
) -> pd.DataFrame:
    """조건에 맞는 종목을 필터링한다.

    Args:
        tickers: 스크리닝 대상 티커 목록 (None이면 get_universe() 전체 사용)
        filters: per_min/per_max, pbr_min/pbr_max, market_cap_min/max, sectors(list),
                 rsi_min/rsi_max, above_sma200(bool) 등 (모두 선택적, None이면 해당 조건 미적용)
        include_technicals: True면 RSI/200일선 계산을 위해 가격 데이터도 조회 (느려질 수 있음)

    Returns:
        조건을 충족하는 종목의 DataFrame (컬럼: ticker, name, sector, per, pbr, market_cap, price, rsi, above_sma200),
        시가총액 내림차순 정렬.
    """
    filters = filters or {}

    if tickers is None:
        universe = get_universe()
        if filters.get("sectors"):
            universe = universe[universe["Sector"].isin(filters["sectors"])]
        tickers = universe["Symbol"].tolist()

    rows: list[dict] = []
    for ticker in tickers:
        fundamentals = get_fundamentals(ticker)
        row = dict(fundamentals)
        row["price"] = None
        row["rsi"] = None
        row["above_sma200"] = None

        needs_technicals = include_technicals and (
            filters.get("rsi_min") is not None
            or filters.get("rsi_max") is not None
            or filters.get("above_sma200") is not None
        )
        if needs_technicals:
            try:
                df = get_price_history(ticker)
                if not df.empty:
                    row["price"] = float(df["Close"].iloc[-1])
                    from core.indicators import compute_rsi

                    rsi_series = compute_rsi(df, period=14)
                    if not rsi_series.empty and pd.notna(rsi_series.iloc[-1]):
                        row["rsi"] = float(rsi_series.iloc[-1])
                    sma200 = sma(df["Close"], 200)
                    if not sma200.empty and pd.notna(sma200.iloc[-1]):
                        row["above_sma200"] = bool(row["price"] > sma200.iloc[-1])
            except Exception:
                pass

        if _passes_filters(row, filters):
            rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(
            columns=["ticker", "name", "sector", "per", "pbr", "market_cap", "price", "rsi", "above_sma200"]
        )
    return result.sort_values("market_cap", ascending=False, na_position="last").reset_index(drop=True)


def list_sectors() -> list[str]:
    """유니버스에 존재하는 섹터 목록(정렬)을 반환한다 (필터 UI 드롭다운용)."""
    universe = get_universe()
    return sorted(universe["Sector"].dropna().unique().tolist())
