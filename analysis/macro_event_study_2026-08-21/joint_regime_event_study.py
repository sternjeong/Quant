"""물가(CPI)와 성장(GDP) 국면을 "따로 따로" 보는 게 아니라 직접 교차해서, 진짜 "골디락스"
(물가감속+성장가속) 조합이 다른 세 조합보다 실제로 나은지 직접 검증한다.

CPI 발표일(월간, 표본이 더 많음)을 기준 사건으로 삼고, 각 발표 시점에 "그때 알려져 있던 가장
최근" GDP 성장 모멘텀(가속/감속)을 같이 태깅해 2x2 매트릭스로 나눈다. 지금까지는 CPI와 GDP를
각각 따로 갈라 봤을 뿐 상호작용은 직접 확인하지 않았다."""
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
HORIZONS = [1, 5, 20, 60]
CPI_RELEASE_ID = 10


def fetch_release_dates(release_id: int, start: str) -> list[str]:
    key = os.getenv("FRED_API_KEY")
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?release_id={release_id}"
        f"&api_key={key}&file_type=json&realtime_start={start}&limit=10000"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return [d["date"] for d in r.json().get("release_dates", [])]


def main():
    print("CPI 발표일 조회 중...", flush=True)
    release_dates = fetch_release_dates(CPI_RELEASE_ID, "1994-01-01")

    cpi = fred_data.get_series("CPIAUCSL", start="1993-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

    gdp = fred_data.get_series("GDPC1", start="1992-01-01")
    gdp_yoy = gdp.pct_change(4) * 100
    gdp_accel = gdp_yoy.diff(1)
    # GDP는 분기 데이터 + 발표 지연(~1개월)을 감안해, 그 시점에 "이미 알려졌을" 값만 쓰도록
    # 분기말 + 45일을 지나야 그 분기 수치가 시장에 반영됐다고 간주
    gdp_known_asof = pd.Series(gdp_accel.values, index=gdp_accel.index + pd.DateOffset(days=45))

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def cpi_accel_asof(release_date: pd.Timestamp):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = cpi_accel[cpi_accel.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def gdp_accel_asof(release_date: pd.Timestamp):
        avail = gdp_known_asof[gdp_known_asof.index <= release_date]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    rows = []
    for date_str in release_dates:
        event_date = pd.Timestamp(date_str)
        if event_date not in idx:
            continue
        pos = idx.get_loc(event_date)
        if pos < 1 or pos + max(HORIZONS) >= len(idx):
            continue

        prior_close = close.iloc[pos - 1]
        day0_close = close.iloc[pos]
        day0_ret = round(100 * (day0_close / prior_close - 1), 3)
        fwd = {}
        for h in HORIZONS:
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[pos + h] / day0_close - 1), 3)

        c_acc = cpi_accel_asof(event_date)
        g_acc = gdp_accel_asof(event_date)
        rows.append({
            "date": date_str, "day0_return_pct": day0_ret,
            "cpi_accel_pp": round(c_acc, 3) if c_acc is not None else None,
            "gdp_accel_pp": round(g_acc, 3) if g_acc is not None else None,
            **fwd,
        })

    df = pd.DataFrame(rows)
    valid = df.dropna(subset=["cpi_accel_pp", "gdp_accel_pp"])
    print(f"교차분류 가능 표본: {len(valid)}/{len(df)}건", flush=True)

    def summarize(sub: pd.DataFrame, label: str) -> dict:
        if len(sub) == 0:
            print(f"[{label}] 표본 없음", flush=True)
            return {}
        out = {"n": len(sub), "day0_mean_pct": round(sub["day0_return_pct"].mean(), 3)}
        for h in HORIZONS:
            col = f"fwd_{h}d_pct"
            out[f"fwd_{h}d_mean_pct"] = round(sub[col].dropna().mean(), 3)
            out[f"fwd_{h}d_win_rate_pct"] = round(100 * (sub[col].dropna() > 0).mean(), 1)
        print(f"[{label}] n={out['n']}, +20일={out.get('fwd_20d_mean_pct')}%(승률{out.get('fwd_20d_win_rate_pct')}%), "
              f"+60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
        return out

    goldilocks = valid[(valid["cpi_accel_pp"] <= 0) & (valid["gdp_accel_pp"] > 0)]
    stagflation = valid[(valid["cpi_accel_pp"] > 0) & (valid["gdp_accel_pp"] <= 0)]
    mixed_hot_strong = valid[(valid["cpi_accel_pp"] > 0) & (valid["gdp_accel_pp"] > 0)]
    mixed_cool_weak = valid[(valid["cpi_accel_pp"] <= 0) & (valid["gdp_accel_pp"] <= 0)]

    print("\n=== 2x2 교차 국면 ===", flush=True)
    s_gold = summarize(goldilocks, "골디락스(물가감속+성장가속)")
    s_stag = summarize(stagflation, "스태그플레이션(물가가속+성장감속)")
    s_hot_strong = summarize(mixed_hot_strong, "혼합1(물가가속+성장가속, 과열)")
    s_cool_weak = summarize(mixed_cool_weak, "혼합2(물가감속+성장감속, 냉각)")

    out_json = {
        "n_total": len(valid),
        "quadrants": {
            "goldilocks": s_gold, "stagflation": s_stag,
            "overheating": s_hot_strong, "cooling_off": s_cool_weak,
        },
    }
    with open(f"{OUT_DIR}/joint_regime_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
