"""VM 에서 실행하는 읽기 전용 검증: 자산 거래가능·휴장 캘린더·뉴스 응답 스키마가 가정과 맞는지 확인한다.

사용: python scripts/verify_alpaca_meta_news.py   (키 값은 출력하지 않는다. 키는 .env 에서 로드)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core import account_sync, alpaca_market_meta as meta, alpaca_news


def main() -> int:
    if not account_sync.credentials_available():
        print("키가 환경에 없습니다(값은 출력하지 않음).")
        return 2
    ok = True
    rep = meta.check_tradability(["AAPL", "SPY", "ZZZZNOPE"])
    print("자산:", {k: v["verdict"] for k, v in rep.items()}, "(기대: AAPL/SPY tradable, ZZZZNOPE not_found)")
    ok &= rep["AAPL"]["verdict"] == meta.TRADABLE and rep["ZZZZNOPE"]["verdict"] == meta.NOT_FOUND
    days = meta.fetch_trading_days("2025-11-24", "2025-11-30")
    print("캘린더:", json.dumps(days))
    ok &= any(d["date"] == "2025-11-28" and d["early_close"] for d in days) and not any(d["date"] == "2025-11-27" for d in days)
    news = alpaca_news.fetch_news(["AAPL"], "2020-03-01", "2020-03-03")
    print(f"뉴스(2020-03, 과거 조회): {len(news)}건, 첫 건 키:", sorted(news[0]) if news else None)
    ok &= len(news) > 0
    print("결과:", "가정과 일치" if ok else "가정과 다름 — _normalize_* 파싱 지점을 고칠 것")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
