"""트랙 E 5차 확장 — 지금까지 채권/금/달러 3개 자산군만 봤던 것을 S&P500 섹터 9개(1998년
상장한 오리지널 SPDR 섹터ETF: XLK·XLF·XLE·XLV·XLI·XLY·XLP·XLU·XLB)로 넓힌다. 트랙E에서
이미 검증한 연준 금리결정 이벤트(2005년 이후 53건)를 그대로 재사용해 "금리 인상/인하에
민감한 섹터는 따로 있는가"를 확인한다. XLRE(2015년 상장)·XLC(2018년 상장)는 기간이 짧아
제외."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60]
SECTORS = {
    "XLK": "기술",
    "XLF": "금융",
    "XLE": "에너지",
    "XLV": "헬스케어",
    "XLI": "산업재",
    "XLY": "임의소비재",
    "XLP": "필수소비재",
    "XLU": "유틸리티",
    "XLB": "소재",
}
COMMON_START = "2005-01-01"


def main():
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    events = events[events.index >= COMMON_START]
    print(f"{COMMON_START} 이후 금리변경 이벤트: {len(events)}건 "
          f"(인상 {int((events['change_bps']>0).sum())}, 인하 {int((events['change_bps']<0).sum())})", flush=True)

    hist = get_multiple_price_history(list(SECTORS.keys()), start="2004-06-01", end="2026-08-20", interval="1d")

    results = {}
    for ticker, label in SECTORS.items():
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
        print(f"\n=== {label}({ticker}) ===", flush=True)

        def summarize(sub, sublabel):
            out = {"n": len(sub)}
            for h in HORIZONS:
                col = f"fwd_{h}d_pct"
                vals = sub[col].dropna()
                out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3) if len(vals) else None
                out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1) if len(vals) else None
            print(f"  [{sublabel}] n={out['n']}, +60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
            return out

        hike_sub = df_rows[df_rows["direction"] == "hike"]
        cut_sub = df_rows[df_rows["direction"] == "cut"]
        results[ticker] = {"label": label, "hike": summarize(hike_sub, "인상"), "cut": summarize(cut_sub, "인하")}

    # 섹터간 스프레드 정리: 인하 국면에서 가장 유리한/불리한 섹터 랭킹
    ranked = sorted(results.items(), key=lambda kv: (kv[1]["cut"]["fwd_60d_mean_pct"] or 0), reverse=True)
    print("\n=== 인하 후 +60일 섹터 랭킹 ===", flush=True)
    for ticker, r in ranked:
        print(f"  {r['label']}({ticker}): {r['cut']['fwd_60d_mean_pct']}% (승률{r['cut']['fwd_60d_win_rate_pct']}%)", flush=True)

    with open(f"{OUT_DIR}/cross_asset_sector_fomc.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
