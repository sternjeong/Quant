"""연준 금리 '변경'일 이벤트 스터디 (1990~2026).

방법론:
1. FRED DFEDTAR(1990~2008, 단일 목표금리) + DFEDTARU/DFEDTARL(2008~2026, 목표범위 중간값)을
   이어붙여 하루도 빠짐없는 연속 목표금리 시계열을 만든다.
2. 값이 바뀐 날(=FOMC가 실제로 금리를 움직인 날)을 자동 탐지한다 — 사람이 회의 일정을 손으로
   기억해서 옮겨적는 방식이 아니라, 공식 통계에서 직접 검출하므로 날짜 오류 리스크가 없다.
   (주의: 이 방식은 "동결" 결정은 잡지 못한다 — 동결은 06장에서 FMP 경제캘린더 API가 오면
   추가 검증 예정이라고 기록해둔다.)
3. 각 변경일에 대해 S&P500의 발표일 반응(전일종가→발표일종가), 익일 반응(발표일종가→익일종가),
   그리고 +5/+20/+60거래일 누적수익률을 측정한다.
4. NBER 공식 경기침체 판정(FRED USREC)으로 각 이벤트를 "침체 중" vs "침체 아님"으로 나눠, 같은
   방향(인상/인하)의 결정이라도 거시 맥락에 따라 시장 반응이 달라지는지 확인한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import numpy as np
import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [1, 5, 20, 60]  # 거래일


def build_target_rate_series() -> pd.Series:
    pre = fred_data.get_series("DFEDTAR", start="1990-01-01", end="2008-12-15")
    upper = fred_data.get_series("DFEDTARU", start="2008-12-16")
    lower = fred_data.get_series("DFEDTARL", start="2008-12-16")
    post = (upper + lower) / 2
    combined = pd.concat([pre, post]).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined


def detect_rate_changes(rate: pd.Series) -> pd.DataFrame:
    diffs = rate.diff()
    changes = diffs[(diffs != 0) & diffs.notna()]
    return pd.DataFrame({"change_bps": (changes * 100).round(0), "new_rate": rate.loc[changes.index]})


def main():
    print("금리 시계열 구축 중...", flush=True)
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    print(f"탐지된 금리 변경 이벤트: {len(events)}건 ({events.index.min().date()} ~ {events.index.max().date()})", flush=True)

    recession = fred_data.get_series("USREC", start="1988-01-01")
    recession_monthly = recession.reindex(recession.index).asfreq("MS")

    def is_recession(dt: pd.Timestamp) -> bool:
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        if month_start in recession_monthly.index:
            return bool(recession_monthly.loc[month_start] == 1.0)
        nearest = recession_monthly.index[recession_monthly.index <= month_start]
        if len(nearest) == 0:
            return False
        return bool(recession_monthly.loc[nearest[-1]] == 1.0)

    spx_hist = get_multiple_price_history(["^GSPC"], start="1989-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    spx_close = spx_hist["Close"]
    spx_idx = spx_close.index

    rows = []
    for event_date, row in events.iterrows():
        pos = spx_idx.searchsorted(event_date)
        if pos == 0 or pos >= len(spx_idx):
            continue
        if spx_idx[pos] != event_date:
            if pos >= len(spx_idx):
                continue
        anchor_pos = pos if pos < len(spx_idx) and spx_idx[pos] == event_date else pos
        if anchor_pos <= 0 or anchor_pos >= len(spx_idx):
            continue

        prior_close = spx_close.iloc[anchor_pos - 1]
        announce_close = spx_close.iloc[anchor_pos] if spx_idx[anchor_pos] == event_date else spx_close.iloc[anchor_pos]
        day0_ret = round(100 * (announce_close / prior_close - 1), 3)

        fwd = {}
        for h in HORIZONS:
            fut_pos = anchor_pos + h
            if fut_pos < len(spx_idx):
                fwd[f"fwd_{h}d_pct"] = round(100 * (spx_close.iloc[fut_pos] / announce_close - 1), 3)
            else:
                fwd[f"fwd_{h}d_pct"] = None

        rows.append({
            "date": str(event_date.date()),
            "change_bps": int(row["change_bps"]),
            "direction": "hike" if row["change_bps"] > 0 else "cut",
            "new_rate_pct": float(row["new_rate"]),
            "recession": is_recession(event_date),
            "day0_return_pct": day0_ret,
            **fwd,
        })

    df = pd.DataFrame(rows)
    print(f"\n가격 데이터 매칭 성공: {len(df)}/{len(events)}건", flush=True)

    def summarize(sub: pd.DataFrame, label: str):
        if len(sub) == 0:
            print(f"[{label}] 표본 없음", flush=True)
            return {}
        out = {"n": len(sub), "day0_mean_pct": round(sub["day0_return_pct"].mean(), 3)}
        for h in HORIZONS:
            col = f"fwd_{h}d_pct"
            out[f"fwd_{h}d_mean_pct"] = round(sub[col].dropna().mean(), 3)
            out[f"fwd_{h}d_win_rate_pct"] = round(100 * (sub[col].dropna() > 0).mean(), 1)
        print(f"[{label}] n={out['n']}, 발표일평균={out['day0_mean_pct']}%, "
              f"+5일평균={out.get('fwd_5d_mean_pct')}%(승률{out.get('fwd_5d_win_rate_pct')}%), "
              f"+20일평균={out.get('fwd_20d_mean_pct')}%(승률{out.get('fwd_20d_win_rate_pct')}%), "
              f"+60일평균={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
        return out

    print("\n=== 전체 ===", flush=True)
    summary_all = summarize(df, "전체")

    print("\n=== 방향별 ===", flush=True)
    summary_hike = summarize(df[df["direction"] == "hike"], "인상")
    summary_cut = summarize(df[df["direction"] == "cut"], "인하")

    print("\n=== 침체 여부 x 방향 ===", flush=True)
    summary_cut_recession = summarize(df[(df["direction"] == "cut") & (df["recession"])], "인하ㆍ침체중")
    summary_cut_norecession = summarize(df[(df["direction"] == "cut") & (~df["recession"])], "인하ㆍ침체아님(보험성 인하)")
    summary_hike_recession = summarize(df[(df["direction"] == "hike") & (df["recession"])], "인상ㆍ침체중")
    summary_hike_norecession = summarize(df[(df["direction"] == "hike") & (~df["recession"])], "인상ㆍ침체아님")

    print("\n=== 폭별(25bp 이하 vs 50bp 이상) ===", flush=True)
    summary_small = summarize(df[df["change_bps"].abs() <= 25], "25bp이하")
    summary_large = summarize(df[df["change_bps"].abs() > 25], "50bp이상(자이언트)")

    out_json = {
        "events": df.to_dict(orient="records"),
        "summary": {
            "all": summary_all, "hike": summary_hike, "cut": summary_cut,
            "cut_recession": summary_cut_recession, "cut_norecession": summary_cut_norecession,
            "hike_recession": summary_hike_recession, "hike_norecession": summary_hike_norecession,
            "small_change": summary_small, "large_change": summary_large,
        },
    }
    with open(f"{OUT_DIR}/fomc_rate_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
