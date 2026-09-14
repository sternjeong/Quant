"""트랙 E(신규) — 지금까지 이 프로젝트는 항상 "S&P500이 어떻게 반응했나"만 봤다. 같은 CPI
발표 이벤트(가속/감속 국면 구분은 기존 cpi_release_event_study.py와 동일한 방법론)에 대해
이번엔 주식이 아니라 채권(TLT)·금(GLD)·달러(DX-Y.NYB)가 어떻게 반응했는지 본다 — "물가가
식을 때 어느 자산이 진짜 웃는가"를 자산군을 가로질러 비교한다.

데이터 제약: GLD는 2004-11부터, TLT는 2002-07부터 존재 — 세 자산을 전부 비교하려면 CPI
이벤트를 2005년 이후로 제한해야 한다(달러지수 단독이면 1999년부터 가능하지만, 이 스크립트는
세 자산을 나란히 비교하는 게 목적이라 공통 구간으로 통일한다)."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import os

import pandas as pd
import requests
from dotenv import load_dotenv

from core import fred_data
from core.market_data import get_multiple_price_history

load_dotenv()
OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60]
CPI_RELEASE_ID = 10
ASSETS = {"TLT": "채권(TLT)", "GLD": "금(GLD)", "DX-Y.NYB": "달러지수"}
COMMON_START = "2005-01-01"  # GLD 워밍업 포함 안전마진


def fetch_release_dates(release_id: int, start: str) -> list[str]:
    key = os.getenv("FRED_API_KEY")
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?release_id={release_id}"
        f"&api_key={key}&file_type=json&realtime_start={start}&limit=10000"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return sorted(d["date"] for d in r.json().get("release_dates", []))


def main():
    print("CPI 발표일 조회 중...", flush=True)
    release_dates = [d for d in fetch_release_dates(CPI_RELEASE_ID, "1994-01-01") if d >= COMMON_START]
    print(f"{COMMON_START} 이후 발표일 {len(release_dates)}건", flush=True)

    cpi = fred_data.get_series("CPIAUCSL", start="1993-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

    def cpi_accel_asof(release_date: pd.Timestamp):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = cpi_accel[cpi_accel.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    hist = get_multiple_price_history(list(ASSETS.keys()), start="2004-06-01", end="2026-08-20", interval="1d")

    results = {}
    for ticker, label in ASSETS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 데이터 없음", flush=True)
            continue
        close = df["Close"]
        idx = close.index

        rows = []
        for date_str in release_dates:
            event_date = pd.Timestamp(date_str)
            if event_date not in idx:
                continue
            pos = idx.get_loc(event_date)
            if pos < 1 or pos + max(HORIZONS) >= len(idx):
                continue
            day0_close = close.iloc[pos]
            fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in HORIZONS}
            accel = cpi_accel_asof(event_date)
            rows.append({"date": date_str, "accel_pp": accel, **fwd})

        df_rows = pd.DataFrame(rows).dropna(subset=["accel_pp"])
        print(f"\n=== {label} ===", flush=True)

        def summarize(sub, sublabel):
            out = {"n": len(sub)}
            for h in HORIZONS:
                col = f"fwd_{h}d_pct"
                vals = sub[col].dropna()
                out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
                out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
            print(f"  [{sublabel}] n={out['n']}, +60일={out['fwd_60d_mean_pct']}%(승률{out['fwd_60d_win_rate_pct']}%)", flush=True)
            return out

        accel_sub = df_rows[df_rows["accel_pp"] > 0]
        decel_sub = df_rows[df_rows["accel_pp"] <= 0]
        results[ticker] = {
            "label": label,
            "accelerating": summarize(accel_sub, "물가가속"),
            "decelerating": summarize(decel_sub, "물가감속"),
        }

    with open(f"{OUT_DIR}/cross_asset_cpi_study.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
