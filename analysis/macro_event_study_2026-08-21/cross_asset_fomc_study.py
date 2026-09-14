"""트랙 E 확장 — 연준 금리 변경일(트랙 A에서 이미 검증한 109건의 이벤트, 여기선 자산 데이터
제약으로 2005년 이후만 사용)에 대해 채권(TLT)·금(GLD)·달러지수가 어떻게 반응했는지 본다.
"금리 인상하면 채권 팔고 달러 사라"는 교과서적 조언을 자산별로 직접 검증한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60]
ASSETS = {"TLT": "채권(TLT)", "GLD": "금(GLD)", "DX-Y.NYB": "달러지수"}
COMMON_START = "2005-01-01"


def main():
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    events = events[events.index >= COMMON_START]
    print(f"{COMMON_START} 이후 금리변경 이벤트: {len(events)}건 (인상 {int((events['change_bps']>0).sum())}, "
          f"인하 {int((events['change_bps']<0).sum())})", flush=True)

    hist = get_multiple_price_history(list(ASSETS.keys()), start="2004-06-01", end="2026-08-20", interval="1d")

    results = {}
    for ticker, label in ASSETS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 없음", flush=True)
            continue
        close = df["Close"]
        idx = close.index

        rows = []
        for event_date, row in events.iterrows():
            pos = idx.searchsorted(event_date)
            if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
                continue
            if pos + max(HORIZONS) >= len(idx):
                continue
            day0_close = close.iloc[pos]
            fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in HORIZONS}
            rows.append({"date": str(event_date.date()), "direction": "hike" if row["change_bps"] > 0 else "cut", **fwd})

        df_rows = pd.DataFrame(rows)
        print(f"\n=== {label} ===", flush=True)

        def summarize(sub, sublabel):
            out = {"n": len(sub)}
            for h in HORIZONS:
                col = f"fwd_{h}d_pct"
                vals = sub[col].dropna()
                out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3) if len(vals) else None
                out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1) if len(vals) else None
            print(f"  [{sublabel}] n={out['n']}, +60일={out['fwd_60d_mean_pct']}%(승률{out['fwd_60d_win_rate_pct']}%)", flush=True)
            return out

        hike_sub = df_rows[df_rows["direction"] == "hike"]
        cut_sub = df_rows[df_rows["direction"] == "cut"]
        results[ticker] = {"label": label, "hike": summarize(hike_sub, "인상"), "cut": summarize(cut_sub, "인하")}

    with open(f"{OUT_DIR}/cross_asset_fomc_study.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
