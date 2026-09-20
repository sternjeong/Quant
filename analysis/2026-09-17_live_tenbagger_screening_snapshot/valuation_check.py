"""discover_results.json의 default 변형 상위 종목에 대해 "정당 PER/PBR"을 고든성장모형/
잔여이익모형에서 대수적으로 역산해 실제 PER/PBR과 대조한다.

analysis/2026-08-16_tenbagger_stock_picking/build_report.py 01~02절이 유도한 것과 정확히
같은 공식을 재사용한다(새 밸류에이션 로직 발명 없음):
  정당 P/E = (1-b)(1+g) / (r-g),  g = b * ROE   (b=이익유보율=1-배당성향)
  정당 P/B = (ROE - g) / (r-g)
ROE 프록시는 같은 리포트(gather_data.py)의 관례 그대로 trailingEps / bookValue 를 쓴다.
요구수익률 r은 core.valuation.ddm_intrinsic_value 의 기본값(0.09)을 그대로 따른다.

r <= g(성장이 요구수익률을 추월)인 경우 모형이 수학적으로 붕괴(분모 음수/발산)한다 — 이 경우
정당 P/E·P/B를 억지로 계산하지 않고 None(모형 붕괴)으로 정직하게 표시한다.
"""
import json
import time

import yfinance as yf

OUT_DIR = "/opt/quant/analysis/2026-09-17_live_tenbagger_screening_snapshot"
REQUIRED_RETURN = 0.09  # core.valuation.ddm_intrinsic_value 기본값과 동일
TOP_N = 20


def justified_pe(b, roe, r=REQUIRED_RETURN):
    if b is None or roe is None:
        return None, None
    g = b * roe
    if r <= g:
        return None, g  # 모형 붕괴
    return (1 - b) * (1 + g) / (r - g), g


def justified_pb(roe, g, r=REQUIRED_RETURN):
    if roe is None or g is None:
        return None
    if r <= g:
        return None
    return (roe - g) / (r - g)


def main():
    with open(f"{OUT_DIR}/discover_results.json", encoding="utf-8") as f:
        D = json.load(f)
    top = D["results"]["default"][:TOP_N]

    rows = []
    for i, cand in enumerate(top):
        ticker = cand["ticker"]
        print(f"[valuation] {i+1}/{len(top)} {ticker} ...")
        info = {}
        try:
            info = yf.Ticker(ticker).info
        except Exception as e:
            print(f"  fetch failed: {e}")
        trailing_eps = info.get("trailingEps")
        book_value = info.get("bookValue")
        dividend_rate = info.get("dividendRate")
        actual_pe = info.get("trailingPE") or cand.get("trailing_pe")
        actual_pb = info.get("priceToBook") or cand.get("price_to_book")

        roe_proxy = (trailing_eps / book_value) if (trailing_eps and book_value and book_value > 0) else None
        payout_ratio = (dividend_rate / trailing_eps) if (dividend_rate and trailing_eps and trailing_eps > 0) else 0.0
        payout_ratio = max(0.0, min(payout_ratio, 1.0))  # 배당>이익(비정상)인 경우 상한 100%로 클립
        b = 1 - payout_ratio

        jpe, g = justified_pe(b, roe_proxy)
        jpb = justified_pb(roe_proxy, g)

        rows.append(
            {
                "ticker": ticker,
                "name": cand.get("name"),
                "sector": cand.get("sector"),
                "composite_score": cand.get("composite_score"),
                "trailing_eps": trailing_eps,
                "book_value": book_value,
                "roe_proxy": roe_proxy,
                "retention_ratio_b": b,
                "sustainable_growth_g": g,
                "required_return": REQUIRED_RETURN,
                "model_collapsed": (g is not None and g >= REQUIRED_RETURN),
                "justified_pe": jpe,
                "actual_trailing_pe": actual_pe,
                "justified_pb": jpb,
                "actual_price_to_book": actual_pb,
            }
        )
        time.sleep(0.3)

    with open(f"{OUT_DIR}/valuation_check.json", "w", encoding="utf-8") as f:
        json.dump({"required_return": REQUIRED_RETURN, "rows": rows}, f, indent=1, default=str)
    print("[valuation] saved valuation_check.json")


if __name__ == "__main__":
    main()
