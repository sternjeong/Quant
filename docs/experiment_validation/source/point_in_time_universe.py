"""과거 특정 시점의 S&P500 구성종목(point-in-time constituents)을 제공하는 모듈.

survivorship bias 방지용: 현재 S&P500 목록을 과거 백테스트/튜닝에 그대로 쓰면
"지금까지 살아남아 크게 오른 종목들"만 남아있는 목록을 과거 시점에도 적용하는
오류가 생긴다. 이 모듈은 fja05680/sp500 프로젝트가 배포하는 히스토리 CSV
(data/sp500_historical_constituents.csv)를 읽어, 임의의 과거 날짜 기준으로
실제 그 시점에 S&P500에 속해 있던 티커 목록을 돌려준다.

원본 CSV의 `tickers` 컬럼은 편입/이탈 이벤트가 있을 때마다 한 행씩 기록되며,
이후 제외된 티커에는 `TICKER-YYYYMM` 형식으로 이탈 시점이 접미사로 붙어있는
경우가 있다(예: `AAL-199702`). 이 모듈은 그런 접미사를 제거하고, 이 저장소의
다른 코드(core/screener.py)와 동일하게 `.`을 `-`로 치환해 yfinance 표기법
(`BRK.B` -> `BRK-B`)에 맞춘다.

이 core 패키지는 Streamlit에 의존하지 않는 것이 이 저장소의 관례이므로
(core/market_data.py 상단 주석 참고), st.cache_data 대신 plain
functools.lru_cache로 CSV 파싱 결과를 캐시한다.
"""

from __future__ import annotations

import functools
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

DEFAULT_CSV_PATH = "data/sp500_historical_constituents.csv"

_SUFFIX_RE = re.compile(r"-\d{6}$")


def _normalize_ticker(raw: str) -> str:
    """CSV의 원본 티커 표기를 yfinance 표기법으로 정규화한다.

    - `TICKER-YYYYMM` 형태의 이탈일자 접미사를 제거한다 (예: `AAL-199702` -> `AAL`).
    - `.`을 `-`로 치환한다 (예: `BRK.B` -> `BRK-B`), core/screener.py의 관례를 따름.
    """
    ticker = raw.strip()
    ticker = _SUFFIX_RE.sub("", ticker)
    ticker = ticker.replace(".", "-")
    return ticker


@functools.lru_cache(maxsize=8)
def load_historical_constituents_table(
    csv_path: str = DEFAULT_CSV_PATH,
) -> pd.DataFrame:
    """S&P500 히스토리 구성종목 CSV를 읽어 DataFrame으로 반환한다 (lru_cache로 캐시).

    반환 DataFrame 컬럼:
        - date: pd.Timestamp, 해당 구성종목 목록이 유효해지기 시작한 날짜
        - tickers: str, CSV 원본 그대로의 콤마 구분 문자열
        - tickers_list: list[str], 정규화 및 정렬된 티커 리스트

    날짜 오름차순으로 정렬되어 반환된다.
    """
    path = Path(csv_path)
    if not path.is_absolute():
        # 저장소 루트 기준 상대경로도 허용 (core/ 밑에서 실행되는 스크립트 대응)
        candidates = [path, Path(__file__).resolve().parent.parent / path]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break

    df = pd.read_csv(path, dtype={"tickers": str})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    def _parse_tickers(raw: str) -> list[str]:
        if not isinstance(raw, str) or not raw.strip():
            return []
        normalized = [_normalize_ticker(t) for t in raw.split(",") if t.strip()]
        return sorted(set(normalized))

    df["tickers_list"] = df["tickers"].apply(_parse_tickers)
    return df


def get_constituents_as_of(
    as_of_date: str | datetime,
    csv_path: str = DEFAULT_CSV_PATH,
) -> list[str]:
    """주어진 날짜 기준으로 S&P500에 속해 있었던 티커 목록을 반환한다.

    `date <= as_of_date`를 만족하는 행 중 가장 최근(date가 가장 큰) 행을 사용한다.
    as_of_date가 데이터의 가장 이른 날짜보다 이전이면(이 파일은 1996년까지
    거슬러 올라간다), 에러 없이 가장 이른 행을 그대로 사용한다.

    반환값은 정렬된 티커 리스트(list[str])이다.
    """
    if isinstance(as_of_date, str):
        as_of_ts = pd.to_datetime(as_of_date)
    else:
        as_of_ts = pd.Timestamp(as_of_date)

    table = load_historical_constituents_table(csv_path)
    if table.empty:
        return []

    eligible = table[table["date"] <= as_of_ts]
    if eligible.empty:
        # as_of_date가 데이터 시작일보다 이전 -> 가장 이른 행을 사용
        row = table.iloc[0]
    else:
        row = eligible.iloc[-1]

    return sorted(row["tickers_list"])
