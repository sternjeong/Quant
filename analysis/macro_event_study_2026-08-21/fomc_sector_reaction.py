"""금리 변경 이벤트에 대한 섹터별 반응 분해. 금리에 민감한 섹터(금융·리츠·유틸리티)와
성장주 섹터(기술)가 인상/인하에 다르게 반응하는지 확인 — 기존 SECTOR_ETFS_LEGACY/MODERN
데이터를 재사용."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import pandas as pd

from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
SECTORS = {
    "XLF": "금융", "XLRE": "리츠", "XLU": "유틸리티", "XLK": "기술",
    "XLY": "임의소비재", "XLP": "필수소비재", "XLE": "에너지", "XLI": "산업재",
    "XLV": "헬스케어", "XLB": "소재",
}
HORIZON = 60  # 거래일


def main():
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    print(f"이벤트 {len(events)}건", flush=True)

    tickers = list(SECTORS.keys())
    hist = get_multiple_price_history(tickers, start="1998-01-01", end="2026-08-20", interval="1d")

    out = {}
    for t in tickers:
        df = hist.get(t)
        if df is None or df.empty:
            continue
        close = df["Close"]
        idx = close.index

        hike_rets, cut_rets = [], []
        for event_date, row in events.iterrows():
            if event_date < idx.min() or event_date > idx.max():
                continue
            pos = idx.searchsorted(event_date)
            if pos <= 0 or pos >= len(idx):
                continue
            fut_pos = pos + HORIZON
            if fut_pos >= len(idx):
                continue
            ret = round(100 * (close.iloc[fut_pos] / close.iloc[pos] - 1), 3)
            if row["change_bps"] > 0:
                hike_rets.append(ret)
            else:
                cut_rets.append(ret)

        if len(hike_rets) == 0 or len(cut_rets) == 0:
            continue
        hike_mean = round(sum(hike_rets) / len(hike_rets), 2)
        cut_mean = round(sum(cut_rets) / len(cut_rets), 2)
        print(f"[{SECTORS[t]}({t})] 인상후+60일평균={hike_mean}%(n={len(hike_rets)}), "
              f"인하후+60일평균={cut_mean}%(n={len(cut_rets)}), 격차={round(cut_mean-hike_mean,2)}%p", flush=True)
        out[t] = {"label": SECTORS[t], "hike_fwd60_mean": hike_mean, "cut_fwd60_mean": cut_mean,
                   "n_hike": len(hike_rets), "n_cut": len(cut_rets)}

    with open(f"{OUT_DIR}/fomc_sector_reaction.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
