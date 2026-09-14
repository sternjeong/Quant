"""네트워크 호출 재시도 공용 유틸 (지수 백오프).

인스타그램(@fidetolabs) "Building A Self-Improving AI Trading Agent" 시리즈 Day 5가 보여준
"실패해도 스스로 복구하는 데이터 파이프라인"(재시도 1/3 실패 -> 1.5초 백오프 -> 재시도 2/3 실패
-> 다시 healthy) 아이디어를, 이 프로젝트가 실제로 가진 두 군데의 조용한 실패 지점에 적용한다.

- `core/fred_data.py::get_series()`: FRED API 호출이 예외를 던지면 그 이유(레이트리밋인지,
  일시적 네트워크 단절인지, 진짜 잘못된 series_id인지)를 구분하지 않고 바로 빈 Series를 반환했다
  (2026-09-13 이전). 스케줄러가 새벽에 매크로 캐시를 갱신하다 순단 한 번으로 그날 하루치 지표가
  통째로 빈 값이 되는 사고를 막기 위해, 던지기 전에 몇 번 더 시도한다.
- `core/market_data.py::_download()`: yfinance 호출은 원래 재시도 로직이 전혀 없었고
  (`get_price_history()` 안에서 직접 예외를 잡지도 않았다), 일시적 실패가 그대로 위로 전파되거나
  (단일 티커 조회) 그 티커만 조용히 빈 DataFrame으로 처리되곤 했다(다종목 병렬 조회).

이 모듈은 core 패키지 관례대로 Streamlit에 의존하지 않는다 (스케줄러에서도 그대로 사용).
"""

from __future__ import annotations

import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

# 재시도 콜백 시그니처: (시도 번호(1부터), 최대 시도 횟수, 다음 시도까지 대기(초), 이번에 발생한 예외)
OnRetryCallback = Callable[[int, int, float, BaseException], None]


def default_on_retry(label: str) -> OnRetryCallback:
    """print()로 재시도 상황을 남기는 기본 콜백을 만든다 (스케줄러 로그에서 그대로 보임).

    label은 "[fred_data] FEDFUNDS"처럼 무엇을 재시도하는지 식별하는 문자열.
    """

    def _on_retry(attempt: int, max_attempts: int, delay: float, exc: BaseException) -> None:
        print(
            f"{label} 조회 실패(시도 {attempt}/{max_attempts}) - {delay:.1f}초 후 재시도: "
            f"{type(exc).__name__}: {exc}"
        )

    return _on_retry


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.5,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_retry: Optional[OnRetryCallback] = None,
) -> T:
    """fn()이 exceptions에 해당하는 예외를 던지면 지수 백오프로 최대 max_attempts번까지 재시도한다.

    대기 시간은 시도 회차마다 base_delay_seconds * 2**(attempt - 1)초 (기본값 기준 1.5초 -> 3.0초
    -> ...). 마지막 시도까지 실패하면 그 마지막 예외를 그대로 다시 던진다 (호출부가 기존처럼
    자신의 try/except로 "빈 값 반환" 등 폴백을 결정하도록 — 이 함수 자체는 폴백 정책을 갖지 않는다).

    Args:
        fn: 인자 없이 호출할 콜러블 (호출부에서 클로저로 인자를 미리 묶어서 넘긴다).
        max_attempts: 최초 시도를 포함한 총 시도 횟수 (1이면 재시도 없음).
        base_delay_seconds: 첫 재시도 전 대기 시간(초). 이후 회차마다 2배씩 늘어난다.
        exceptions: 재시도 대상으로 삼을 예외 타입들. 그 외 예외는 즉시 그대로 전파된다.
        on_retry: 재시도 직전에 호출되는 콜백(로그/알림용). None이면 아무것도 하지 않는다.

    Returns:
        fn()의 성공한 반환값.

    Raises:
        마지막 시도에서도 발생한 예외 (exceptions에 해당하는 것만 재시도 대상이며, 그 외 예외는
        재시도 없이 즉시 전파된다).
    """
    if max_attempts < 1:
        raise ValueError("max_attempts는 1 이상이어야 합니다.")

    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except exceptions as exc:  # noqa: BLE001 - 재시도 여부는 exceptions 파라미터로 이미 제한됨
            if attempt == max_attempts:
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1))
            if on_retry is not None:
                on_retry(attempt, max_attempts, delay, exc)
            time.sleep(delay)

    # 위 루프는 항상 return 또는 raise로 끝나지만, 타입 체커/린터를 위한 안전망.
    raise RuntimeError("retry_with_backoff: 도달할 수 없는 코드 경로")
