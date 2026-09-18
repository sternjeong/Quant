"""과거 특정 시점의 시가총액을 근사 계산한다 (2026-08-13, No.09 리서치가 드러낸 인프라 공백).

core.screener.get_fundamentals()는 yfinance의 "지금" 시점 정보(Ticker.info)만 제공한다 —
core.strategy_tuning.sample_universe()에 as_of_date를 넘겨도 종목 편입 여부는 point-in-time으로
걸러지지만, 그중 어떤 종목을 표본에 넣을지 정하는 섹터별 시가총액 순위는 여전히 "지금" 시가총액
기준이었다. No.09 리서치(개별주 모멘텀 로테이션)에서 이 때문에 "그 시점에 지수에 있었고 지금 보니
크게 성장한 종목" 위주로 표본이 뽑히는 은근한 사후편향을 발견했다.

해결: yfinance.Ticker.get_shares_full()이 분기별 발행주식수 이력(SEC 정기공시 기준 스냅샷)을
제공한다 — 이 발행주식수 x 그 시점 종가(core.market_data.get_price_history, 이미 룩어헤드 없는
영구 로컬 캐시 보유)로 point-in-time 시가총액을 근사한다.

한계(정직하게 명시):
    1. get_shares_full()이 제공하는 가장 이른 날짜 이전을 물으면 그 가장 이른 값으로 근사한다
       (실제 값이 아니라 "변동 없었다"는 가정 — 상장 초기 급격한 증자가 있었던 종목은 부정확할 수
       있음). 일부 종목(예: META)은 이력 자체가 몇 년 안 되게 짧을 수 있다.
    2. 발행주식수는 SEC 정기공시 시점(분기~반기 간격)에만 갱신되는 계단식 데이터라, 자사주 매입/
       공모가 분기 중간에 있었으면 며칠~몇 주 오차가 난다.
    3. 이 근사치는 "그때 실제로 관찰 가능했던 시가총액"이 아니라 "그때 발행주식수 x 그때 종가"다 —
       실제 순수 point-in-time 데이터 벤더(CRSP 등) 대비 정밀도는 떨어지지만, 최소한 "현재 시가총액
       기준으로 표본을 뽑는" 것보다는 사후편향이 훨씬 적다.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from core.market_data import get_price_history

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 발행주식수는 분기 단위로만 실제로 바뀌므로 가격 캐시(6시간)보다 훨씬 길게 잡는다 — 매번 다시
# 받아올 필요가 없다.
SHARES_CACHE_TTL_SECONDS = 14 * 24 * 60 * 60  # 14일
_MAX_WORKERS = 10


def _shares_cache_file(ticker: str) -> Path:
    safe = ticker.replace("/", "-").replace(":", "-")
    return CACHE_DIR / f"shares_outstanding_{safe}.parquet"


def get_shares_outstanding_history(ticker: str, use_cache: bool = True) -> pd.Series:
    """yfinance에서 발행주식수 이력(비정기 보고일 기준 스냅샷)을 받아온다 (파일 캐시 적용).

    Returns: 날짜(DatetimeIndex, tz 제거·오름차순) -> 발행주식수 Series. 조회 실패/데이터
        없음이면 빈 Series (예외를 던지지 않음 — core.market_data.get_price_history와 동일 관례).
    """
    cache_file = _shares_cache_file(ticker)
    if use_cache and cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < SHARES_CACHE_TTL_SECONDS:
            try:
                df = pd.read_parquet(cache_file)
                return df["shares"].sort_index()
            except Exception:
                pass

    try:
        raw = yf.Ticker(ticker).get_shares_full(start="2000-01-01")
        if raw is None or raw.empty:
            series = pd.Series(dtype="float64")
        else:
            idx = pd.DatetimeIndex(raw.index)
            if getattr(idx, "tz", None) is not None:
                idx = idx.tz_localize(None)
            series = pd.Series(raw.values, index=idx).astype("float64").sort_index()
            series = series[~series.index.duplicated(keep="last")]
    except Exception:
        series = pd.Series(dtype="float64")

    if use_cache:
        try:
            pd.DataFrame({"shares": series}).to_parquet(cache_file)
        except Exception:
            pass
    return series


def _cumulative_split_factor_after(ticker: str, as_of_ts: pd.Timestamp, use_cache: bool = True) -> float:
    """as_of_ts 이후에 일어난 액면분할(및 병합)의 누적 배율을 계산한다.

    core.market_data.get_price_history의 종가는 yfinance가 auto_adjust=False로 받아와도 액면분할은
    항상 자동 반영해서 준다(배당만 별도 조정) — 즉 "오늘 기준으로 조정된" 가격이다. 반면
    get_shares_full()이 주는 발행주식수는 그 시점 실제(미조정) 값이라, 이후 분할이 있었던 종목은
    가격(조정됨)×주식수(미조정)를 그대로 곱하면 분할 배율만큼 틀어진다(2026-08-13 발견 — NVDA는
    2019년 이후 4:1(2021)+10:1(2024)=40배 분할이 있어 이 보정 없이는 시가총액이 40배 과소평가됨).
    이 함수가 그 배율을 구해 발행주식수에 곱해 가격 조정 기준과 맞춘다.
    """
    try:
        splits = yf.Ticker(ticker).splits
    except Exception:
        return 1.0
    if splits is None or splits.empty:
        return 1.0
    idx = pd.DatetimeIndex(splits.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    splits = pd.Series(splits.values, index=idx)
    after = splits[splits.index > as_of_ts]
    if after.empty:
        return 1.0
    factor = 1.0
    for ratio in after:
        factor *= float(ratio)
    return factor


def get_market_cap_asof(ticker: str, as_of_date: str, use_cache: bool = True) -> Optional[float]:
    """특정 시점의 근사 시가총액(그 시점까지의 최신 발행주식수 x 그 시점 종가)을 계산한다.

    발행주식수·가격 둘 중 하나라도 그 시점 데이터를 구할 수 없으면 None을 반환한다(호출자가
    "이 종목은 이번엔 계산 불가"로 처리하도록 — core.market_regime의 신호 함수들과 동일한 관례).
    """
    shares_hist = get_shares_outstanding_history(ticker, use_cache=use_cache)
    if shares_hist.empty:
        return None

    as_of_ts = pd.Timestamp(as_of_date)
    prior = shares_hist[shares_hist.index <= as_of_ts]
    # 모듈 docstring 한계 1번: 가장 이른 데이터보다 과거를 물으면 가장 이른 값으로 근사한다.
    shares = float(prior.iloc[-1]) if not prior.empty else float(shares_hist.iloc[0])
    shares *= _cumulative_split_factor_after(ticker, as_of_ts, use_cache=use_cache)

    fetch_start = (as_of_ts - pd.DateOffset(days=10)).date().isoformat()
    fetch_end = (as_of_ts + pd.DateOffset(days=1)).date().isoformat()
    price_df = get_price_history(ticker, start=fetch_start, end=fetch_end, interval="1d", use_cache=use_cache)
    if price_df is None or price_df.empty or "Close" not in price_df.columns:
        return None
    price_df = price_df[price_df.index <= as_of_ts]
    if price_df.empty:
        return None
    price = float(price_df["Close"].iloc[-1])

    return price * shares


def get_market_caps_asof_batch(
    tickers: list[str], as_of_date: str, use_cache: bool = True
) -> dict[str, Optional[float]]:
    """여러 종목의 point-in-time 시가총액을 병렬로 계산한다.

    core.market_data.get_multiple_price_history와 동일한 스레드풀 병렬화 패턴(네트워크 I/O
    위주라 효과가 큼) — 대량 종목(예: S&P500 전체)을 순차 조회하면 느리기 때문.

    Returns: {ticker: 시가총액 또는 None(계산 불가)}.
    """
    if not tickers:
        return {}

    def _one(t: str) -> Optional[float]:
        try:
            return get_market_cap_asof(t, as_of_date, use_cache=use_cache)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {t: executor.submit(_one, t) for t in tickers}
        return {t: future.result() for t, future in futures.items()}
