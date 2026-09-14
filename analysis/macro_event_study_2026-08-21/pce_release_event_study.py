"""PCE(개인소비지출 물가지수) 발표일 이벤트 스터디 — 연준이 실제로 목표로 삼는 물가지표.

CPI는 소비자가 직접 낸 영수증 기반, PCE는 기업 판매 데이터까지 포함해 더 넓게 집계하고 연준의
공식 2% 인플레이션 목표도 PCE 기준이다. CPI와 결과가 같은 방향인지, 아니면 "연준이 진짜 보는
지표라 더 강하게 반응하는지"를 비교한다. 방법론은 CPI/NFP 스터디와 동일(가속/둔화 국면 구분,
FRED release/dates API로 정확한 발표일 확보)."""
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
PCE_RELEASE_ID = 54  # Personal Income and Outlays (FRED) — PCE 물가지수 포함


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
    print("PCE 발표일 조회 중...", flush=True)
    release_dates = fetch_release_dates(PCE_RELEASE_ID, "1994-01-01")
    print(f"발표일 {len(release_dates)}건 ({release_dates[0]} ~ {release_dates[-1]})", flush=True)

    pce = fred_data.get_series("PCEPI", start="1993-01-01")
    pce_yoy = pce.pct_change(12) * 100
    yoy_accel = pce_yoy.diff(3)

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def yoy_accel_asof(release_date: pd.Timestamp):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = yoy_accel[yoy_accel.index <= ref_month]
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

        accel = yoy_accel_asof(event_date)
        rows.append({
            "date": date_str, "day0_return_pct": day0_ret,
            "yoy_accel_pp": round(accel, 3) if accel is not None else None,
            **fwd,
        })

    df = pd.DataFrame(rows)
    print(f"\n가격+PCE 매칭 성공: {len(df)}/{len(release_dates)}건", flush=True)

    def summarize(sub: pd.DataFrame, label: str) -> dict:
        if len(sub) == 0:
            print(f"[{label}] 표본 없음", flush=True)
            return {}
        out = {"n": len(sub), "day0_mean_pct": round(sub["day0_return_pct"].mean(), 3)}
        for h in HORIZONS:
            col = f"fwd_{h}d_pct"
            out[f"fwd_{h}d_mean_pct"] = round(sub[col].dropna().mean(), 3)
            out[f"fwd_{h}d_win_rate_pct"] = round(100 * (sub[col].dropna() > 0).mean(), 1)
        print(f"[{label}] n={out['n']}, 발표일={out['day0_mean_pct']}%, "
              f"+5일={out.get('fwd_5d_mean_pct')}%(승률{out.get('fwd_5d_win_rate_pct')}%), "
              f"+20일={out.get('fwd_20d_mean_pct')}%(승률{out.get('fwd_20d_win_rate_pct')}%), "
              f"+60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
        return out

    print("\n=== 전체 ===", flush=True)
    summary_all = summarize(df, "전체")

    valid = df.dropna(subset=["yoy_accel_pp"])
    print("\n=== PCE 가속 vs 감속 국면 ===", flush=True)
    summary_accel = summarize(valid[valid["yoy_accel_pp"] > 0], "가속(뜨거워지는 물가)")
    summary_decel = summarize(valid[valid["yoy_accel_pp"] <= 0], "감속(식는 물가)")

    out_json = {
        "events": df.to_dict(orient="records"),
        "summary": {"all": summary_all, "accelerating": summary_accel, "decelerating": summary_decel},
    }
    with open(f"{OUT_DIR}/pce_release_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
