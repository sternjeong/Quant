"""세션 초반 연준 금리 스터디는 "침체 중 인하 vs 보험성 인하"를 NBER 공식 침체판정으로 나눴다.
이번 조인트 스터디는 "물가가 식고 있는가"가 결과를 지배한다는 걸 보여줬다 — 그렇다면 금리 결정
109건도 recession 대신 CPI 가속/감속으로 다시 나누면 더(혹은 다르게) 설명되는지 확인한다.
같은 원칙: 사후에 유리한 설명을 고르지 않고, 두 축을 나란히 놓고 실제로 비교한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import numpy as np
import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [1, 5, 20, 60]


def main():
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)

    cpi = fred_data.get_series("CPIAUCSL", start="1988-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

    recession = fred_data.get_series("USREC", start="1988-01-01")
    recession_monthly = recession.asfreq("MS")

    def cpi_accel_asof(dt: pd.Timestamp):
        ref_month = pd.Timestamp(dt.year, dt.month, 1) - pd.DateOffset(months=1)
        avail = cpi_accel[cpi_accel.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def is_recession(dt: pd.Timestamp) -> bool:
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        nearest = recession_monthly.index[recession_monthly.index <= month_start]
        if len(nearest) == 0:
            return False
        return bool(recession_monthly.loc[nearest[-1]] == 1.0)

    spx_hist = get_multiple_price_history(["^GSPC"], start="1989-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    rows = []
    for event_date, row in events.iterrows():
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
            continue
        if pos + max(HORIZONS) >= len(idx):
            continue
        prior_close = close.iloc[pos - 1]
        day0_close = close.iloc[pos]
        fwd = {}
        for h in HORIZONS:
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[pos + h] / day0_close - 1), 3)
        accel = cpi_accel_asof(event_date)
        rows.append({
            "date": str(event_date.date()), "direction": "hike" if row["change_bps"] > 0 else "cut",
            "recession": is_recession(event_date),
            "cpi_accel_pp": round(accel, 3) if accel is not None else None,
            **fwd,
        })

    df = pd.DataFrame(rows)
    cuts = df[df["direction"] == "cut"].dropna(subset=["cpi_accel_pp"])
    print(f"인하 이벤트(CPI 매칭됨): {len(cuts)}건", flush=True)

    def summarize(sub: pd.DataFrame, label: str) -> dict:
        if len(sub) == 0:
            print(f"[{label}] 표본 없음", flush=True)
            return {}
        out = {"n": len(sub)}
        for h in HORIZONS:
            col = f"fwd_{h}d_pct"
            out[f"fwd_{h}d_mean_pct"] = round(sub[col].dropna().mean(), 3)
            out[f"fwd_{h}d_win_rate_pct"] = round(100 * (sub[col].dropna() > 0).mean(), 1)
        print(f"[{label}] n={out['n']}, +20일={out.get('fwd_20d_mean_pct')}%(승률{out.get('fwd_20d_win_rate_pct')}%), "
              f"+60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
        return out

    print("\n=== 기존 축: 침체 여부(NBER) ===", flush=True)
    s_recession = summarize(cuts[cuts["recession"]], "침체 중 인하")
    s_norecession = summarize(cuts[~cuts["recession"]], "보험성 인하")

    print("\n=== 새 축: 물가 가속/감속 ===", flush=True)
    s_cpi_accel = summarize(cuts[cuts["cpi_accel_pp"] > 0], "물가가속 중 인하")
    s_cpi_decel = summarize(cuts[cuts["cpi_accel_pp"] <= 0], "물가감속 중 인하")

    print("\n=== 두 축 동시 교차(2x2) ===", flush=True)
    s_rec_accel = summarize(cuts[cuts["recession"] & (cuts["cpi_accel_pp"] > 0)], "침체+물가가속")
    s_rec_decel = summarize(cuts[cuts["recession"] & (cuts["cpi_accel_pp"] <= 0)], "침체+물가감속")
    s_norec_accel = summarize(cuts[~cuts["recession"] & (cuts["cpi_accel_pp"] > 0)], "비침체+물가가속")
    s_norec_decel = summarize(cuts[~cuts["recession"] & (cuts["cpi_accel_pp"] <= 0)], "비침체+물가감속(진짜 보험성)")

    out_json = {
        "recession_axis": {"recession": s_recession, "no_recession": s_norecession},
        "cpi_axis": {"accelerating": s_cpi_accel, "decelerating": s_cpi_decel},
        "cross": {
            "recession_accel": s_rec_accel, "recession_decel": s_rec_decel,
            "norecession_accel": s_norec_accel, "norecession_decel": s_norec_decel,
        },
    }
    with open(f"{OUT_DIR}/fomc_cpi_cross_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
