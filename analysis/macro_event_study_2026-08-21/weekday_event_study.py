"""요일 효과("월요일 효과" — 월요일 수익률이 유독 나쁘다는 유명한 통설) 검증. 이번 프로젝트에서
가장 큰 표본(76년치 일별 수익률, 요일당 수천 건)이라 통계적으로 가장 탄탄한 테스트가 될 수 있다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
WEEKDAY_NAMES = {0: "월요일", 1: "화요일", 2: "수요일", 3: "목요일", 4: "금요일"}


def main():
    print("S&P500 일별 데이터 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1950-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    daily_ret = close.pct_change().dropna() * 100

    print(f"전체 거래일: {len(daily_ret)}건 ({daily_ret.index.min().date()} ~ {daily_ret.index.max().date()})", flush=True)

    by_weekday = {}
    for wd in range(5):
        vals = daily_ret[daily_ret.index.weekday == wd]
        mean = round(vals.mean(), 4)
        win = round(100 * (vals > 0).mean(), 2)
        by_weekday[wd] = {"n": len(vals), "mean_pct": mean, "win_rate_pct": win}
        print(f"[{WEEKDAY_NAMES[wd]}] n={len(vals)}, 평균={mean}%, 승률={win}%", flush=True)

    # 최근 30년만 따로(구조변화 여부 확인 — 요일효과는 2000년대 이후 사라졌다는 연구가 많음)
    recent = daily_ret[daily_ret.index >= "1996-01-01"]
    print(f"\n=== 최근 30년만(1996~) ===", flush=True)
    by_weekday_recent = {}
    for wd in range(5):
        vals = recent[recent.index.weekday == wd]
        mean = round(vals.mean(), 4)
        win = round(100 * (vals > 0).mean(), 2)
        by_weekday_recent[wd] = {"n": len(vals), "mean_pct": mean, "win_rate_pct": win}
        print(f"[{WEEKDAY_NAMES[wd]}] n={len(vals)}, 평균={mean}%, 승률={win}%", flush=True)

    out_json = {
        "full_period": {"start": str(daily_ret.index.min().date()), "end": str(daily_ret.index.max().date())},
        "by_weekday_full": {str(k): v for k, v in by_weekday.items()},
        "by_weekday_recent": {str(k): v for k, v in by_weekday_recent.items()},
    }
    with open(f"{OUT_DIR}/weekday_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
