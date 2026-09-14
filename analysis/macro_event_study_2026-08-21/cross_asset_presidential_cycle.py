"""트랙 E 4차 확장 — 대선주기 효과(3년차가 가장 좋다, presidential_cycle_event_study.py에서
S&P500 기준 확인됨: +17.18%/89.5%)를 채권(TLT)·금(GLD)·달러지수에도 그대로 적용해본다.
GLD 상장(2004-11) 제약으로 2005년 이후 완결 연도만 사용 — 표본이 각 연차 5개뿐이라 매우
작지만, 트랙E의 다른 두 이벤트(CPI/FOMC)와 같은 자산군·같은 기간대이므로 비교는 가능하다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
YEAR_LABELS = {1: "1년차(집권원년)", 2: "2년차(중간선거)", 3: "3년차(대선전해)", 0: "4년차(대선해)"}
ASSETS = {"TLT": "채권(TLT)", "GLD": "금(GLD)", "DX-Y.NYB": "달러지수"}
START_YEAR = 2005


def main():
    hist = get_multiple_price_history(list(ASSETS.keys()), start="2004-06-01", end="2026-08-20", interval="1d")
    current_year = pd.Timestamp.today().year

    results = {}
    for ticker, label in ASSETS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 없음", flush=True)
            continue
        close = df["Close"]
        years = sorted(y for y in set(close.index.year) if y >= START_YEAR)

        rows = []
        for y in years:
            if y >= current_year:
                continue
            seg = close[close.index.year == y]
            if len(seg) < 100:
                continue
            prior = close[close.index < seg.index[0]]
            if len(prior) == 0:
                continue
            ret = round(100 * (seg.iloc[-1] / prior.iloc[-1] - 1), 3)
            cycle_year = y % 4
            rows.append({"year": y, "cycle_year": cycle_year, "return_pct": ret})

        df_rows = pd.DataFrame(rows)
        print(f"\n=== {label} ({df_rows['year'].min()}~{df_rows['year'].max()}, n={len(df_rows)}) ===", flush=True)

        def summarize(sub, sublabel):
            rets = sub["return_pct"].tolist()
            n = len(rets)
            if n == 0:
                return {"n": 0}
            mean = round(sum(rets) / n, 3)
            win = round(100 * sum(1 for r in rets if r > 0) / n, 1)
            print(f"  [{sublabel}] n={n}, 평균={mean}%, 승률={win}%", flush=True)
            return {"n": n, "mean_pct": mean, "win_rate_pct": win}

        summary = {}
        for cy in [1, 2, 3, 0]:
            sub = df_rows[df_rows["cycle_year"] == cy]
            summary[str(cy)] = summarize(sub, YEAR_LABELS[cy])
        results[ticker] = {"label": label, "years": df_rows.to_dict(orient="records"), "summary": summary}

    with open(f"{OUT_DIR}/cross_asset_presidential_cycle.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
