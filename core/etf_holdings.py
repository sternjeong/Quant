"""모듈 D: ETF/액티브펀드 구성종목 조회.

- 미국 ETF: 운용사가 공개하는 holdings 파일을 자동 연동한다.
  현재는 SPDR(State Street/SSGA) 계열 ETF(SPY, XLK, XLF 등)의 일별 holdings xlsx를
  자동으로 받아온다 (파일 캐시 적용). iShares/Invesco 등은 봇 차단(지역/약관 동의 게이트)이
  걸려 있어 이 환경에서는 자동 연동이 불가능했으므로, 그런 ETF나 국내(한국) ETF/펀드는
  아래 parse_uploaded_holdings() 로 CSV/엑셀 파일을 직접 업로드해서 보도록 지원한다.
- 국내(한국) ETF/펀드: 무료 API가 없으므로 CSV/엑셀 파일 업로드 파싱으로 지원한다.
"""

from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SPDR_XLSX_URL = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{ticker_lower}.xlsx"
SPDR_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6시간 (market_data.py 와 동일한 기준)

STANDARD_COLUMNS = ["ticker", "name", "weight_pct", "shares", "sector"]


def fetch_spdr_etf_holdings(ticker: str, use_cache: bool = True) -> pd.DataFrame:
    """SPDR(SSGA) 계열 미국 ETF의 최신 구성종목을 가져온다 (예: SPY, XLK, XLF, XLE ...).

    Returns:
        columns=[ticker, name, weight_pct, shares, sector] DataFrame.
        해당 ETF가 SPDR 계열이 아니거나 조회 실패 시 빈 DataFrame을 반환한다(예외를 던지지 않음).
    """
    ticker = (ticker or "").strip().upper()
    if not ticker:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    cache_file = CACHE_DIR / f"spdr_holdings_{ticker}.xlsx"

    content: Optional[bytes] = None
    if use_cache and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < SPDR_CACHE_TTL_SECONDS:
            content = cache_file.read_bytes()

    if content is None:
        url = SPDR_XLSX_URL.format(ticker_lower=ticker.lower())
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            resp.raise_for_status()
            content = resp.content
        except Exception:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        if use_cache:
            try:
                cache_file.write_bytes(content)
            except Exception:
                pass

    try:
        # SSGA xlsx는 상단 4줄이 펀드명/티커/기준일 안내라서 5번째 줄(0-indexed 4)이 헤더.
        df = pd.read_excel(io.BytesIO(content), header=4)
    except Exception:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    if "Name" not in df.columns or "Ticker" not in df.columns:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    df = df.dropna(subset=["Name"])
    out = pd.DataFrame(
        {
            "ticker": df.get("Ticker"),
            "name": df.get("Name"),
            "weight_pct": pd.to_numeric(df.get("Weight"), errors="coerce"),
            "shares": pd.to_numeric(df.get("Shares Held"), errors="coerce"),
            "sector": df.get("Sector") if "Sector" in df.columns else None,
        }
    )
    return out.reset_index(drop=True)


# 헤더 자동 인식을 위한 한글/영문 컬럼명 후보 (국내 ETF/펀드 CSV/엑셀 대응).
# 표준 필드를 이 순서로 먼저 배정한다: ticker처럼 구체적인 필드부터 배정해야
# "종목코드"(ticker) 컬럼이 "종목"이라는 느슨한 별칭 때문에 name으로 잘못 잡히는 걸 막을 수 있다.
_COLUMN_ALIASES = {
    "ticker": ["ticker", "symbol", "종목코드", "티커", "코드"],
    "weight_pct": ["weight_pct", "weight", "비중(%)", "비중", "구성비중", "구성비율"],
    "shares": ["shares held", "shares", "보유수량", "수량"],
    "sector": ["sector", "섹터", "업종"],
    "name": ["name", "종목명", "구성종목", "company", "종목"],
}


def _guess_column(columns: list[str], aliases: list[str]) -> Optional[str]:
    """alias를 우선순위대로(정확히 일치 > 부분 일치) 검사해 가장 그럴듯한 컬럼명을 찾는다."""
    normalized = {c: str(c).strip().lower() for c in columns}
    for alias in aliases:
        for col, norm in normalized.items():
            if norm == alias.lower():
                return col
    for alias in aliases:
        for col, norm in normalized.items():
            if alias.lower() in norm:
                return col
    return None


def _map_columns(columns: list[str]) -> dict[str, Optional[str]]:
    """표준 필드(ticker/weight_pct/shares/sector/name 순서)를 컬럼에 그리디하게 배정한다.

    한 컬럼이 여러 표준 필드에 중복 배정되지 않도록, 배정된 컬럼은 후보 풀에서 제외한다.
    """
    remaining = list(columns)
    mapping: dict[str, Optional[str]] = {}
    for std in ["ticker", "weight_pct", "shares", "sector", "name"]:
        col = _guess_column(remaining, _COLUMN_ALIASES[std])
        mapping[std] = col
        if col is not None:
            remaining.remove(col)
    return mapping


def parse_uploaded_holdings(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """사용자가 업로드한 CSV/엑셀 파일(ETF 또는 국내 펀드 구성종목)을 표준 컬럼으로 정규화한다.

    파일의 헤더가 어느 행에 있는지, 컬럼명이 한글/영문 어느 쪽인지 알 수 없으므로
    상위 몇 행을 훑어 그럴듯한 헤더 행을 찾고, 컬럼명을 표준(ticker/name/weight_pct/shares/sector)에 매핑한다.
    매핑에 실패한 컬럼은 비워둔다(그래도 원본을 최대한 보여주는 것이 목표).

    Raises:
        ValueError: 파일을 읽을 수 없거나(형식 오류) 종목명/티커 컬럼을 전혀 찾지 못한 경우.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    raw: pd.DataFrame

    def _try_read(header_row: int) -> Optional[pd.DataFrame]:
        try:
            if ext in ("xlsx", "xls"):
                return pd.read_excel(io.BytesIO(file_bytes), header=header_row)
            return pd.read_csv(io.BytesIO(file_bytes), header=header_row, encoding_errors="ignore")
        except Exception:
            return None

    # 헤더가 파일 맨 위가 아닐 수 있으므로(펀드명/기준일 안내 행 등) 0~7행을 모두 시도해보고
    # 표준 컬럼(ticker/name/weight/shares/sector)에 가장 많이 매칭되는 행을 헤더로 채택한다.
    # (단순히 처음 매칭되는 행을 쓰면 "Ticker Symbol:" 같은 안내 행을 헤더로 오인할 수 있음)
    best: Optional[pd.DataFrame] = None
    best_score = -1
    fallback: Optional[pd.DataFrame] = None
    for header_row in range(0, 8):
        candidate = _try_read(header_row)
        if candidate is None or candidate.empty:
            continue
        if fallback is None:
            fallback = candidate
        cols = [str(c) for c in candidate.columns]
        score = sum(1 for v in _map_columns(cols).values() if v is not None)
        if score > best_score:
            best_score = score
            best = candidate

    if best is None:
        best = fallback
    if best is None:
        raise ValueError("파일을 읽을 수 없습니다. CSV 또는 엑셀(xlsx) 형식인지 확인해주세요.")
    raw = best

    columns = [str(c) for c in raw.columns]
    col_map = _map_columns(columns)

    if col_map["name"] is None and col_map["ticker"] is None:
        raise ValueError("종목명 또는 티커 컬럼을 찾지 못했습니다. 파일 형식을 확인해주세요.")

    out = pd.DataFrame()
    for std in STANDARD_COLUMNS:
        src = col_map[std]
        out[std] = raw[src] if src is not None else None

    for numeric_col in ("weight_pct", "shares"):
        out[numeric_col] = (
            out[numeric_col]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False)
            .str.strip()
        )
        out[numeric_col] = pd.to_numeric(out[numeric_col], errors="coerce")

    out = out.dropna(subset=["name"] if col_map["name"] else ["ticker"], how="all")
    return out.reset_index(drop=True)
