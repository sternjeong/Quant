"""GDP 발표일 이벤트 스터디 — 연준 금리·물가·고용에 이어 "3대 거시지표"의 마지막 한 조각.

GDP는 분기당 3번(속보치·잠정치·확정치) 발표된다 — 시장은 보통 그 분기의 "첫 번째"(속보치) 발표에
가장 크게 반응하고 이후 수정치엔 덜 반응한다는 게 정설이므로, 이 스터디는 각 분기 클러스터의
첫 발표일만 "속보치"로 분리해서 나머지(수정치)와 비교한다. 국면 구분은 앞의 CPI/PCE와 같은 방식
(전년동기비 GDP 성장률이 가속/감속 중인지)."""
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
GDP_RELEASE_ID = 53  # Gross Domestic Product (FRED)


def fetch_release_dates(release_id: int, start: str) -> list[str]:
    key = os.getenv("FRED_API_KEY")
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?release_id={release_id}"
        f"&api_key={key}&file_type=json&realtime_start={start}&limit=10000"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return [d["date"] for d in r.json().get("release_dates", [])]


def split_advance_vs_revision(dates: list[str]) -> tuple[list[str], list[str]]:
    """GDP는 분기당 속보치·2차·3차 순서로 정확히 3번씩 발표되며 간격이 전부 비슷해(약 4주)
    "큰 갭"으로는 구분이 안 된다 — 대신 발표 순서 자체가 항상 (속보,2차,3차)를 반복하므로
    3개씩 끊어 그룹의 첫 번째만 속보치로 분류한다."""
    ts = sorted(pd.Timestamp(d) for d in dates)
    advance, revision = [], []
    for i, t in enumerate(ts):
        if i % 3 == 0:
            advance.append(str(t.date()))
        else:
            revision.append(str(t.date()))
    return advance, revision


def main():
    print("GDP 발표일 조회 중...", flush=True)
    release_dates = fetch_release_dates(GDP_RELEASE_ID, "1994-01-01")
    advance_dates, revision_dates = split_advance_vs_revision(release_dates)
    print(f"발표일 {len(release_dates)}건 -> 속보치 {len(advance_dates)}건 / 수정치 {len(revision_dates)}건", flush=True)

    gdp = fred_data.get_series("GDPC1", start="1992-01-01")
    gdp_yoy = gdp.pct_change(4) * 100
    yoy_accel = gdp_yoy.diff(1)  # 분기 데이터라 전분기 대비 가속/감속

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def yoy_accel_asof(release_date: pd.Timestamp):
        avail = yoy_accel[yoy_accel.index < release_date - pd.DateOffset(months=1)]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def build_rows(dates: list[str]) -> pd.DataFrame:
        rows = []
        for date_str in dates:
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
            rows.append({"date": date_str, "day0_return_pct": day0_ret,
                         "yoy_accel_pp": round(accel, 3) if accel is not None else None, **fwd})
        return pd.DataFrame(rows)

    df_advance = build_rows(advance_dates)
    df_revision = build_rows(revision_dates)
    print(f"가격 매칭: 속보치 {len(df_advance)}/{len(advance_dates)}, 수정치 {len(df_revision)}/{len(revision_dates)}", flush=True)

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

    print("\n=== 속보치 vs 수정치 ===", flush=True)
    summary_advance = summarize(df_advance, "속보치")
    summary_revision = summarize(df_revision, "수정치(2·3차)")

    valid = df_advance.dropna(subset=["yoy_accel_pp"])
    print("\n=== 속보치만: 성장 가속 vs 감속 국면 ===", flush=True)
    summary_accel = summarize(valid[valid["yoy_accel_pp"] > 0], "가속(성장세 강화)")
    summary_decel = summarize(valid[valid["yoy_accel_pp"] <= 0], "감속(성장세 둔화)")

    out_json = {
        "advance_events": df_advance.to_dict(orient="records"),
        "revision_events": df_revision.to_dict(orient="records"),
        "summary": {
            "advance": summary_advance, "revision": summary_revision,
            "accelerating": summary_accel, "decelerating": summary_decel,
        },
    }
    with open(f"{OUT_DIR}/gdp_release_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
