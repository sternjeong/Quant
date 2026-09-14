"""편향 없는 유니버스(2015년/2000년 시점 무작위 표본) 각 종목의 실제 GICS 섹터를 yfinance에서
가져와 섹터 ETF 티커로 매핑한다 — "그 쏠림 섹터 안의 대장주"를 제대로 검증하려면 필요.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")
import json
import pickle
import time
import yfinance as yf

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"

SECTOR_TO_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Financial": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def fetch_sectors(tickers):
    mapping = {}
    for i, t in enumerate(tickers):
        try:
            info = yf.Ticker(t).info
            sector = info.get("sector")
            etf = SECTOR_TO_ETF.get(sector)
            mapping[t] = {"sector": sector, "etf": etf}
        except Exception as e:
            mapping[t] = {"sector": None, "etf": None, "error": str(e)}
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(tickers)} 완료", flush=True)
        time.sleep(0.15)
    return mapping


def main():
    with open(f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl", "rb") as f:
        bull_meta = pickle.load(f)
    with open(f"{OUT_DIR}/bear_market_robustness_curves.pkl", "rb") as f:
        bear_meta = pickle.load(f)

    print("2015 유니버스 섹터 조회 중...", flush=True)
    bull_map = fetch_sectors(bull_meta["ok_tickers"])
    print("2000 유니버스 섹터 조회 중...", flush=True)
    bear_map = fetch_sectors(bear_meta["ok_tickers"])

    with open(f"{OUT_DIR}/sector_mapping.json", "w", encoding="utf-8") as f:
        json.dump({"bull_2015": bull_map, "bear_2000": bear_map}, f, ensure_ascii=False, indent=2)

    # 섹터별 종목 수 요약
    from collections import Counter
    bull_etf_counts = Counter(v["etf"] for v in bull_map.values() if v["etf"])
    bear_etf_counts = Counter(v["etf"] for v in bear_map.values() if v["etf"])
    print("\n2015 유니버스 섹터ETF별 종목 수:", dict(bull_etf_counts))
    print("2000 유니버스 섹터ETF별 종목 수:", dict(bear_etf_counts))
    print("매핑 실패(None):", sum(1 for v in bull_map.values() if not v["etf"]), "/", len(bull_map),
          "(2015)", sum(1 for v in bear_map.values() if not v["etf"]), "/", len(bear_map), "(2000)")
    print("DONE")


if __name__ == "__main__":
    main()
