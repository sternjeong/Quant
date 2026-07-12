"""모듈 G: FRED(미 연준) 거시경제 지표 조회 + 파일 캐싱.

core.market_data 와 동일하게 data/cache/ 아래 CSV로 캐싱한다(스케줄러에서도 재사용 가능하도록
Streamlit에 의존하지 않음). FRED_API_KEY가 없거나 호출이 실패해도 예외를 던지지 않고 빈 Series를
반환한다 (UI가 "API 키를 설정해주세요" 안내를 보여줄 수 있도록).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24시간 (거시지표는 발표 주기가 길어 자주 안 바뀜)

# 대시보드에 기본으로 보여줄 지표 (SPEC.md: 금리, GDP, 물가, 실업률 등)
DEFAULT_INDICATORS: dict[str, dict[str, str]] = {
    "FEDFUNDS": {"label": "기준금리 (연방기금금리)", "unit": "%"},
    "CPIAUCSL": {"label": "소비자물가지수 (CPI)", "unit": "지수"},
    "UNRATE": {"label": "실업률", "unit": "%"},
    "GDPC1": {"label": "실질 GDP", "unit": "십억달러"},
    "INDPRO": {"label": "산업생산지수", "unit": "지수"},
    "T10Y2Y": {"label": "10년-2년 국채금리차", "unit": "%p"},
}


def is_configured() -> bool:
    """FRED_API_KEY 환경변수가 설정되어 있는지 확인한다."""
    return bool(os.getenv("FRED_API_KEY"))


def _cache_file(series_id: str) -> Path:
    return CACHE_DIR / f"fred_{series_id}.csv"


def get_series(
    series_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    use_cache: bool = True,
    cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
) -> pd.Series:
    """FRED 시계열 하나를 가져온다 (파일 캐시 적용).

    FRED_API_KEY가 없거나 호출이 실패하면 빈 Series를 반환한다 (예외를 던지지 않음).
    """
    cache_file = _cache_file(series_id)

    if use_cache and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < cache_ttl:
            try:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                return df.iloc[:, 0]
            except Exception:
                pass

    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        return pd.Series(dtype=float, name=series_id)

    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        series = fred.get_series(series_id, observation_start=start, observation_end=end)
        series.name = series_id

        if use_cache and not series.empty:
            try:
                series.to_csv(cache_file)
            except Exception:
                pass
        return series
    except Exception:
        return pd.Series(dtype=float, name=series_id)


def get_latest_value(series_id: str) -> Optional[float]:
    """시계열의 가장 최근 값을 반환한다. 데이터가 없으면 None."""
    series = get_series(series_id).dropna()
    if series.empty:
        return None
    return float(series.iloc[-1])


def get_indicator_snapshot(indicators: Optional[dict[str, dict[str, str]]] = None) -> list[dict]:
    """대시보드 카드용으로 기본 지표들의 최신값 + 전체 시계열을 모아 반환한다."""
    indicators = indicators or DEFAULT_INDICATORS
    result = []
    for series_id, meta in indicators.items():
        series = get_series(series_id).dropna()
        if series.empty:
            result.append(
                {
                    "series_id": series_id,
                    "label": meta["label"],
                    "unit": meta["unit"],
                    "latest_value": None,
                    "latest_date": None,
                    "series": series,
                }
            )
        else:
            result.append(
                {
                    "series_id": series_id,
                    "label": meta["label"],
                    "unit": meta["unit"],
                    "latest_value": float(series.iloc[-1]),
                    "latest_date": series.index[-1].strftime("%Y-%m-%d"),
                    "series": series,
                }
            )
    return result
