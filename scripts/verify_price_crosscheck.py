#!/usr/bin/env python3
"""VM에서 사람이 돌리는 Alpaca 가격 교차검증 리포트 (읽기 전용).

이 저장소의 가격은 yfinance 단일 소스라 단일 소스 오류를 잡을 수단이 없다. 이 스크립트는
core.price_crosscheck를 써서 Alpaca Market Data(일봉)를 2차 소스로 붙여보고, 결과를 stdout에
JSON 한 덩어리로 낸다. **주문은 절대 내지 않는다**(데이터 엔드포인트만 호출하며, 이 파일에
paper/live 주문 URL은 등장하지 않는다). 로컬 상태를 바꾸는 것은 data/cache/alpaca 아래 응답
캐시 파일뿐이며 --no-cache로 그것도 끌 수 있다.

두 단계:
  1) recent  : 심볼 3~5개의 최근 N일(기본 30일) 종가 대조 — match/minor_diff/major_diff/
               missing_in_alpaca/missing_in_yfinance/unavailable 집계와 상위 불일치 날짜.
  2) aapl_split : AAPL 2020-08-31 4:1 분할 구간을 조회해 **Alpaca가 분할 조정 가격을 주는지**
               확인한다. 이 저장소의 yfinance 캐시는 종가에 분할이 소급 반영돼 있음이 확인된
               상태이므로, 분할 직전일(2020-08-28) 종가가 두 소스에서 비슷하면 Alpaca도
               조정본(adjusted), Alpaca 쪽만 약 4배 높으면 미조정(raw)이라는 뜻이다.

판정 해석 (중요):
  Alpaca 무료 티어는 IEX 피드다. 거래량은 전체 시장(SIP)보다 구조적으로 작고, 종가도 SIP 공식
  마감가가 아닐 수 있으며, 조회 가능한 과거 기간에 제한이 있을 수 있다. 따라서 불일치는
  **플래그일 뿐 "yfinance가 틀렸다"는 판정이 아니다**. 2020년 구간이 비어 있으면 그것은 데이터
  오류가 아니라 구독 등급의 과거 데이터 한계일 가능성이 높다(리포트에 그렇게 기록된다).

자격증명은 환경변수에서만 읽는다: ALPACA_PAPER_API_KEY, ALPACA_PAPER_API_SECRET.
값은 출력하지도 저장하지도 않으며, 안전망으로 출력 직전 문자열에서 한 번 더 제거한다.

사용법:
  export ALPACA_PAPER_API_KEY=...  ALPACA_PAPER_API_SECRET=...
  python scripts/verify_price_crosscheck.py
  python scripts/verify_price_crosscheck.py --symbols AAPL MSFT SPY --days 30 --no-cache

종료 코드: 0 대조 성공(불일치 유무와 무관), 2 일부/전부 조회 불가(unavailable), 3 설정 오류(키 없음).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.price_crosscheck import (  # noqa: E402
    DEFAULT_ADJUSTMENT, DEFAULT_FEED, FEED_LIMITATIONS, KEY_ENV, SECRET_ENV,
    VERDICT_UNAVAILABLE, AlpacaDataUnavailable, credentials_available,
    crosscheck_symbol, crosscheck_symbols, fetch_alpaca_daily_bars,
    normalize_alpaca_bars, normalize_yfinance_frame,
)

EXIT_OK, EXIT_UNAVAILABLE, EXIT_SETUP = 0, 2, 3

DEFAULT_SYMBOLS = ["AAPL", "MSFT", "SPY", "NVDA"]

# AAPL 4:1 분할 기준일(2020-08-31). 분할 직전 거래일은 2020-08-28.
AAPL_SPLIT_DATE = "2020-08-31"
AAPL_PRE_SPLIT_DATE = "2020-08-28"
AAPL_SPLIT_WINDOW_START = "2020-08-24"
AAPL_SPLIT_WINDOW_END = "2020-09-08"
AAPL_SPLIT_RATIO = 4.0
# 두 소스 종가 비율이 이 범위 안이면 "같은 조정 상태"로 본다(피드 차이 여유 포함).
SAME_ADJUSTMENT_RATIO_TOLERANCE = 0.05
# 비율이 4배 근처(±15%)면 Alpaca가 미조정(raw)이라는 뜻.
RAW_RATIO_TOLERANCE = 0.15


def _redact(text: str) -> str:
    """안전망: 혹시라도 키 값이 문자열에 섞여 들어갔으면 지운다."""
    for env_name in (KEY_ENV, SECRET_ENV):
        value = os.getenv(env_name)
        if value and len(value) >= 4:
            text = text.replace(value, "<redacted>")
    return text


def _top_mismatches(result: dict, limit: int = 5) -> list[dict]:
    rows = [d for d in result.get("days", []) if d["verdict"] in ("minor_diff", "major_diff")]
    rows.sort(key=lambda d: abs(d.get("diff_bp") or 0.0), reverse=True)
    return [
        {"date": d["date"], "verdict": d["verdict"], "diff_bp": d.get("diff_bp"),
         "yfinance_close": d.get("yfinance_close"), "alpaca_close": d.get("alpaca_close")}
        for d in rows[:limit]
    ]


def step_recent(symbols: list[str], days: int, use_cache: bool) -> dict:
    today = datetime.now()
    start = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    report = crosscheck_symbols(symbols, start, end, use_cache=use_cache)
    per_symbol = {}
    for symbol, result in report["symbols"].items():
        per_symbol[symbol] = {
            "summary": result["summary"],
            "overlap_days": result["overlap_days"],
            "unavailable_reason": _redact(str(result.get("unavailable_reason", ""))) or None,
            "top_mismatches": _top_mismatches(result),
            "split_suspects": result.get("split_suspects", []),
            "volume_flag_days": len(result.get("volume_flags", [])),
        }
    return {
        "step": "recent",
        "window": {"start": start, "end": end, "calendar_days": days},
        "symbols": per_symbol,
        "summary": report["summary"],
    }


def step_aapl_split(use_cache: bool) -> dict:
    """Alpaca가 AAPL 2020-08-31 4:1 분할 조정 가격을 주는지 확인한다."""
    out: dict = {
        "step": "aapl_split",
        "split_date": AAPL_SPLIT_DATE,
        "pre_split_date": AAPL_PRE_SPLIT_DATE,
        "window": {"start": AAPL_SPLIT_WINDOW_START, "end": AAPL_SPLIT_WINDOW_END},
        "expected_if_adjusted": (
            "yfinance 캐시는 분할 소급 반영본이므로, Alpaca도 조정본이면 2020-08-28 종가가 "
            "두 소스에서 비슷하게(비율 ~1.0) 나온다."
        ),
        "expected_if_raw": (
            f"Alpaca가 미조정이면 2020-08-28 Alpaca 종가 / yfinance 종가 ≈ {AAPL_SPLIT_RATIO:.0f}."
        ),
    }

    try:
        bars = fetch_alpaca_daily_bars(
            "AAPL", AAPL_SPLIT_WINDOW_START, AAPL_SPLIT_WINDOW_END, use_cache=use_cache,
        )
    except AlpacaDataUnavailable as exc:
        out["verdict"] = VERDICT_UNAVAILABLE
        out["note"] = _redact(str(exc))
        return out

    alpaca = normalize_alpaca_bars(bars)
    if not alpaca:
        out["verdict"] = VERDICT_UNAVAILABLE
        out["note"] = (
            "Alpaca가 2020년 구간을 비워서 돌려줬습니다. 이는 데이터 오류가 아니라 구독 등급의 "
            "과거 데이터(IEX) 커버리지 한계일 가능성이 큽니다 — 분할 조정 정책은 이 단계로 "
            "확인할 수 없습니다."
        )
        return out

    from core.market_data import get_price_history  # 읽기 전용

    yf = normalize_yfinance_frame(
        get_price_history("AAPL", start=AAPL_SPLIT_WINDOW_START, end=AAPL_SPLIT_WINDOW_END, interval="1d")
    )

    pre_yf = yf.get(AAPL_PRE_SPLIT_DATE)
    pre_ap = alpaca.get(AAPL_PRE_SPLIT_DATE)
    out["pre_split_close"] = {
        "yfinance": pre_yf["close"] if pre_yf else None,
        "alpaca": pre_ap["close"] if pre_ap else None,
    }
    out["post_split_close"] = {
        "yfinance": (yf.get(AAPL_SPLIT_DATE) or {}).get("close"),
        "alpaca": (alpaca.get(AAPL_SPLIT_DATE) or {}).get("close"),
    }

    if not pre_yf or not pre_ap or not pre_yf["close"]:
        out["verdict"] = VERDICT_UNAVAILABLE
        out["note"] = "분할 직전일 종가를 두 소스 모두에서 얻지 못해 조정 정책을 판단할 수 없습니다."
        return out

    ratio = pre_ap["close"] / pre_yf["close"]
    out["pre_split_ratio_alpaca_over_yfinance"] = round(ratio, 6)
    if abs(ratio - 1.0) <= SAME_ADJUSTMENT_RATIO_TOLERANCE:
        out["verdict"] = "alpaca_split_adjusted"
        out["note"] = "Alpaca도 분할 조정본으로 보입니다(yfinance와 같은 조정 상태)."
    elif abs(ratio - AAPL_SPLIT_RATIO) <= AAPL_SPLIT_RATIO * RAW_RATIO_TOLERANCE:
        out["verdict"] = "alpaca_unadjusted"
        out["note"] = (
            "Alpaca가 분할 미조정(raw) 가격을 준 것으로 보입니다. 이 경우 과거 구간 대조는 조정 "
            "차이로 major_diff가 대량 발생하므로 그대로 해석하면 안 됩니다."
        )
    else:
        out["verdict"] = "inconclusive"
        out["note"] = "비율이 1.0도 4.0도 아닙니다 — 사람이 직접 값을 확인해야 합니다."
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alpaca 가격 교차검증 리포트(읽기 전용)")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS,
                        help="대조할 심볼 3~5개 (기본: AAPL MSFT SPY NVDA)")
    parser.add_argument("--days", type=int, default=30, help="최근 대조 구간(달력일, 기본 30)")
    parser.add_argument("--no-cache", action="store_true", help="응답 캐시를 쓰지도 남기지도 않는다")
    parser.add_argument("--skip-split-check", action="store_true", help="AAPL 분할 구간 단계 생략")
    args = parser.parse_args(argv)

    if not credentials_available():
        sys.stderr.write(f"{KEY_ENV}/{SECRET_ENV} 환경변수가 필요합니다.\n")
        return EXIT_SETUP
    if not 1 <= len(args.symbols) <= 5:
        sys.stderr.write("심볼은 1~5개만 허용합니다(레이트리밋 보호).\n")
        return EXIT_SETUP

    use_cache = not args.no_cache
    steps = [step_recent([s.upper() for s in args.symbols], args.days, use_cache)]
    if not args.skip_split_check:
        steps.append(step_aapl_split(use_cache))

    report = {
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "feed": DEFAULT_FEED,
        "adjustment": DEFAULT_ADJUSTMENT,
        "limitations": dict(FEED_LIMITATIONS),
        "read_only": True,
        "steps": steps,
    }

    unavailable = (
        steps[0]["summary"].get(VERDICT_UNAVAILABLE, 0) > 0
        or any(s.get("verdict") == VERDICT_UNAVAILABLE for s in steps[1:])
    )
    report["exit_reason"] = "unavailable_present" if unavailable else "completed"

    print(_redact(json.dumps(report, ensure_ascii=False, indent=2, default=str)))
    return EXIT_UNAVAILABLE if unavailable else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
