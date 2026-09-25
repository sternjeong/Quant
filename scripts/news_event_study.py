"""Alpaca 뉴스 이벤트 스터디를 한 번 실행한다(VM, 읽기 전용).

사용: python scripts/news_event_study.py AAPL MSFT --start 2024-01-01 --end 2024-12-31
결과는 data/research/news_event_study_*.json 에 저장한다. 키 값은 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core import alpaca_news, news_event_study
from core.candidate_ledger import default_price_provider


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    a = ap.parse_args(argv)
    tickers = [t.upper() for t in a.tickers]
    articles = alpaca_news.fetch_news(tickers, a.start, a.end)
    prices = {t: default_price_provider(t, a.start, a.end) for t in tickers}
    res = news_event_study.event_study([{**x, "symbols": [s for s in x["symbols"] if s in tickers]} for x in articles], prices)
    res.update({"tickers": tickers, "start": a.start, "end": a.end, "n_articles": len(articles)})
    out = ROOT / "data" / "research" / f"news_event_study_{datetime.now():%Y%m%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res["horizons"], ensure_ascii=False, indent=2), f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
