"""CPI(소비자물가지수) 발표일 이벤트 스터디 (트랙 A 확장).

FOMC 스터디와 같은 원칙: 발표일을 사람이 손으로 캘린더에서 옮기지 않고 FRED의 공식 "release
dates" API로 직접 가져온다(1994~2026, 410번의 실제 발표일). 정확한 시장 컨센서스(예상치) 데이터는
무료로 구할 수 없었으므로, "인플레이션이 가속 중이었는가 감속 중이었는가"(전년동월비가 3개월 전보다
더 높아졌는지)를 대리 지표로 써서 "뜨거운 물가 국면"과 "식는 물가 국면"에서 발표일 반응이 다른지
비교한다 — 이건 진짜 서프라이즈(예상 대비 실제)가 아니라 방향성 국면 구분이라는 점을 리포트에
명시한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import os

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

from core import fred_data
from core.market_data import get_multiple_price_history

load_dotenv()
OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [1, 5, 20, 60]
CPI_RELEASE_ID = 10  # Consumer Price Index (FRED)


def fetch_release_dates(release_id: int, start: str) -> list[str]:
    key = os.getenv("FRED_API_KEY")
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?release_id={release_id}"
        f"&api_key={key}&file_type=json&realtime_start={start}&limit=10000"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()
    return [d["date"] for d in data.get("release_dates", [])]


def main():
    print("CPI 발표일 조회 중...", flush=True)
    release_dates = fetch_release_dates(CPI_RELEASE_ID, "1994-01-01")
    print(f"발표일 {len(release_dates)}건 ({release_dates[0]} ~ {release_dates[-1]})", flush=True)

    cpi = fred_data.get_series("CPIAUCSL", start="1993-01-01")
    cpi_yoy = cpi.pct_change(12) * 100  # 전년동월비(%)
    yoy_accel = cpi_yoy.diff(3)  # 3개월 전 대비 얼마나 가속/감속했는지(%p)

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def yoy_accel_asof(release_date: pd.Timestamp) -> float | None:
        # 발표되는 CPI는 보통 전월 데이터 — 그 발표 시점에 "이미 알려진" 가장 최근 값 사용
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
    print(f"\n가격+CPI 매칭 성공: {len(df)}/{len(release_dates)}건", flush=True)

    def summarize(sub: pd.DataFrame, label: str) -> dict:
        if len(sub) == 0:
            print(f"[{label}] 표본 없음", flush=True)
            return {}
        out = {"n": len(sub), "day0_mean_pct": round(sub["day0_return_pct"].mean(), 3)}
        for h in HORIZONS:
            col = f"fwd_{h}d_pct"
            out[f"fwd_{h}d_mean_pct"] = round(sub[col].dropna().mean(), 3)
            out[f"fwd_{h}d_win_rate_pct"] = round(100 * (sub[col].dropna() > 0).mean(), 1)
        print(f"[{label}] n={out['n']}, 발표일평균={out['day0_mean_pct']}%, "
              f"+5일={out.get('fwd_5d_mean_pct')}%(승률{out.get('fwd_5d_win_rate_pct')}%), "
              f"+20일={out.get('fwd_20d_mean_pct')}%(승률{out.get('fwd_20d_win_rate_pct')}%), "
              f"+60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
        return out

    print("\n=== 전체 ===", flush=True)
    summary_all = summarize(df, "전체")

    valid = df.dropna(subset=["yoy_accel_pp"])
    print("\n=== 인플레이션 가속 vs 감속 국면 ===", flush=True)
    summary_accel = summarize(valid[valid["yoy_accel_pp"] > 0], "가속(뜨거워지는 물가)")
    summary_decel = summarize(valid[valid["yoy_accel_pp"] <= 0], "감속(식는 물가)")

    out_json = {
        "events": df.to_dict(orient="records"),
        "summary": {"all": summary_all, "accelerating": summary_accel, "decelerating": summary_decel},
    }
    with open(f"{OUT_DIR}/cpi_release_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
