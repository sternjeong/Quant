"""고용지표(비농업고용, NFP) 발표일 이벤트 스터디 (트랙 A 확장 2번째).

CPI 스터디와 같은 방법론 — FRED release/dates API로 정확한 발표일을 가져오고(release_id=50,
"Employment Situation"), 컨센서스 데이터가 없으므로 "고용 증가세가 가속 중인가 둔화 중인가"를
대리 지표로 쓴다(트레일링 3개월 평균 순고용증감 vs 그 3개월 전의 같은 평균)."""
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
NFP_RELEASE_ID = 50  # Employment Situation (FRED)


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
    print("고용지표 발표일 조회 중...", flush=True)
    release_dates = fetch_release_dates(NFP_RELEASE_ID, "1994-01-01")
    print(f"발표일 {len(release_dates)}건 ({release_dates[0]} ~ {release_dates[-1]})", flush=True)

    payems = fred_data.get_series("PAYEMS", start="1993-01-01")
    mom_change = payems.diff()
    trail3 = mom_change.rolling(3).mean()
    momentum = trail3.diff(3)  # 3개월 평균 증감이 그 3개월 전보다 가속/둔화됐는지

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def momentum_asof(release_date: pd.Timestamp):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = momentum[momentum.index <= ref_month]
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

        mom_val = momentum_asof(event_date)
        rows.append({
            "date": date_str, "day0_return_pct": day0_ret,
            "job_momentum_k": round(mom_val, 1) if mom_val is not None else None,
            **fwd,
        })

    df = pd.DataFrame(rows)
    print(f"\n가격+고용 매칭 성공: {len(df)}/{len(release_dates)}건", flush=True)

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

    valid = df.dropna(subset=["job_momentum_k"])
    print("\n=== 고용 가속 vs 둔화 국면 ===", flush=True)
    summary_accel = summarize(valid[valid["job_momentum_k"] > 0], "가속(고용증가세 강화)")
    summary_decel = summarize(valid[valid["job_momentum_k"] <= 0], "둔화(고용증가세 약화)")

    out_json = {
        "events": df.to_dict(orient="records"),
        "summary": {"all": summary_all, "accelerating": summary_accel, "decelerating": summary_decel},
    }
    with open(f"{OUT_DIR}/nfp_release_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
