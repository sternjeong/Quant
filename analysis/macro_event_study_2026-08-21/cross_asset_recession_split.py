"""트랙 E 3차 확장 — 채권(TLT)이 CPI·FOMC 두 크로스에셋 테스트 모두에서 "인하/감속에 유리해야
하는데 오히려 약했다"는 이상 패턴을 보였다. 트랙 A의 "침체 중 인하 vs 보험성 인하" 구분(NBER
공식 침체판정)을 자산군 반응에도 그대로 적용해, 이 이상 패턴이 위기성 인하(2008·2020 등)가
평상시 인하를 오염시킨 결과인지 직접 확인한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
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
    cuts = events[events["change_bps"] < 0]
    print(f"{COMMON_START} 이후 인하 이벤트: {len(cuts)}건", flush=True)

    recession = fred_data.get_series("USREC", start="2004-01-01")
    recession_monthly = recession.asfreq("MS")

    def is_recession(dt: pd.Timestamp) -> bool:
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        nearest = recession_monthly.index[recession_monthly.index <= month_start]
        if len(nearest) == 0:
            return False
        return bool(recession_monthly.loc[nearest[-1]] == 1.0)

    cuts = cuts.copy()
    cuts["recession"] = [is_recession(d) for d in cuts.index]
    print(f"  침체 중 인하: {int(cuts['recession'].sum())}건, 보험성 인하: {int((~cuts['recession']).sum())}건", flush=True)
    for d, row in cuts.iterrows():
        print(f"   {d.date()}: {'침체중' if row['recession'] else '보험성'}", flush=True)

    hist = get_multiple_price_history(list(ASSETS.keys()), start="2004-06-01", end="2026-08-20", interval="1d")

    results = {"n_recession_cuts": int(cuts["recession"].sum()), "n_insurance_cuts": int((~cuts["recession"]).sum())}
    for ticker, label in ASSETS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            continue
        close = df["Close"]
        idx = close.index

        rows = []
        for event_date, row in cuts.iterrows():
            pos = idx.searchsorted(event_date)
            if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
                continue
            if pos + max(HORIZONS) >= len(idx):
                continue
            day0_close = close.iloc[pos]
            fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in HORIZONS}
            rows.append({"date": str(event_date.date()), "recession": bool(row["recession"]), **fwd})

        df_rows = pd.DataFrame(rows)
        print(f"\n=== {label} ===", flush=True)

        def summarize(sub, sublabel):
            out = {"n": len(sub)}
            for h in HORIZONS:
                col = f"fwd_{h}d_pct"
                vals = sub[col].dropna()
                out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3) if len(vals) else None
                out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1) if len(vals) else None
            print(f"  [{sublabel}] n={out['n']}, +60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
            return out

        rec_sub = df_rows[df_rows["recession"]]
        ins_sub = df_rows[~df_rows["recession"]]
        results[ticker] = {
            "label": label,
            "recession_cut": summarize(rec_sub, "침체중 인하"),
            "insurance_cut": summarize(ins_sub, "보험성 인하"),
        }

    with open(f"{OUT_DIR}/cross_asset_recession_split.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
