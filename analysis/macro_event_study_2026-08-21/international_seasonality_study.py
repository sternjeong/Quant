"""달력 효과의 국제 재현성 검증 — 지금까지 이 프로젝트가 확인한 계절성 효과들("5월에 팔고
떠나라", 그 안에서도 특히 9월 효과, 요일효과의 "이상현상 소멸")은 전부 S&P500(미국)만으로
검증됐다. 이 스크립트는 같은 로직(seasonality_event_study.py의 11~4월/5~10월 구간 정의,
weekday_event_study.py의 월요일 효과 소멸 검증 방식)을 독일(DAX)·일본(니케이225)·영국(FTSE100)
세 개 비미국 지수에 그대로 적용해, 이 계절성들이 미국 시장 고유의 현상인지 아니면 여러 시장에
걸쳐 나타나는 보편적 현상인지를 검증한다.

지수 선정 이유: 구조적으로 서로 다른 3개 주요 시장을 고른다 — 독일(유럽 대표, 1987년말~),
일본(아시아 대표, 1965년~, 이 프로젝트에서 가장 긴 비미국 데이터), 영국(유럽이지만 독일과는
다른 금융허브 성격, 1984년~). 전부 야후파이낸스에서 안정적으로 긴 일별 데이터가 확보된다.

사전등록 가설(결과 계산 전 명시):
  H1: "5월에 팔고 떠나라"(11~4월 > 5~10월) 격차가 3개 지수 중 최소 2개에서 같은 부호로
      재현된다. "재현" 기준을 미리 정한다 — 단순히 평균 격차가 양수인 것만으로는 부족하고,
      우호적 반기(11~4월)의 승률이 55%를 넘어야 한다(노이즈가 아니라는 최소 기준).
  H2: 9월 효과(9월이 최저 또는 최저에 가까운 달) 자체가 3개 지수 중 최소 2개에서 재현된다 —
      "5~10월 전체가 약하다"와는 별개의 주장이므로 H1과 분리해서 검증한다.
  H3(탐색적, 강한 사전 확신 없음): 미국 요일효과에서 나타난 "이상현상 소멸"(과거엔 강했으나
      최근 20~30년 약화/역전)이 계절성 효과에서도 3개 지수 중 어딘가 나타나는지 확인한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"

INDICES = {
    "^GDAXI": {"name_kr": "독일 DAX", "start": "1987-12-30"},
    "^N225": {"name_kr": "일본 니케이225", "start": "1965-01-05"},
    "^FTSE": {"name_kr": "영국 FTSE100", "start": "1984-01-03"},
}

MONTH_LABELS = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]


def compute_half_year_periods(close, current_year):
    unfav, fav = [], []
    years = sorted(set(close.index.year))
    for y in years:
        try:
            unfav_start = pd.Timestamp(y, 5, 1)
            unfav_end = pd.Timestamp(y, 10, 31)
            seg = close.loc[unfav_start:unfav_end]
            if len(seg) > 60 and y < current_year:
                prior_price = close.asof(unfav_start - pd.Timedelta(days=1))
                ret = round(100 * (seg.iloc[-1] / prior_price - 1), 3)
                if pd.notna(ret):
                    unfav.append({"period": f"{y}-05~{y}-10", "return_pct": ret})
        except Exception:
            pass
        try:
            fav_start = pd.Timestamp(y, 11, 1)
            fav_end = pd.Timestamp(y + 1, 4, 30)
            seg = close.loc[fav_start:fav_end]
            if len(seg) > 60 and (y + 1) < current_year:
                prior_price = close.asof(fav_start - pd.Timedelta(days=1))
                ret = round(100 * (seg.iloc[-1] / prior_price - 1), 3)
                if pd.notna(ret):
                    fav.append({"period": f"{y}-11~{y+1}-04", "return_pct": ret})
        except Exception:
            pass
    return unfav, fav


def summarize(rets, label):
    n = len(rets)
    if n == 0:
        print(f"[{label}] n=0", flush=True)
        return {"n": 0, "mean_pct": None, "win_rate_pct": None}
    mean = round(sum(rets) / n, 3)
    win = round(100 * sum(1 for r in rets if r > 0) / n, 1)
    print(f"[{label}] n={n}, 평균={mean}%, 승률={win}%", flush=True)
    return {"n": n, "mean_pct": mean, "win_rate_pct": win}


def main():
    current_year = pd.Timestamp.today().year  # 2026
    results = {}

    for ticker, meta in INDICES.items():
        print(f"\n=== {meta['name_kr']} ({ticker}) ===", flush=True)
        hist = get_multiple_price_history([ticker], start="1950-01-01", end="2026-08-20", interval="1d")[ticker]
        close = hist["Close"].dropna()
        daily_ret = close.pct_change().dropna()
        first_year, last_year = close.index.min().year, close.index.max().year

        # --- H1: 반기 구간 비교 ---
        unfav, fav = compute_half_year_periods(close, current_year)
        s_unfav = summarize([p["return_pct"] for p in unfav], f"{meta['name_kr']} 5~10월")
        s_fav = summarize([p["return_pct"] for p in fav], f"{meta['name_kr']} 11~4월")

        h1_pass = bool(s_fav["mean_pct"] is not None and s_unfav["mean_pct"] is not None
                       and s_fav["mean_pct"] > s_unfav["mean_pct"] and s_fav["win_rate_pct"] > 55.0)

        # --- H2: 월별 분해, 9월 효과 ---
        monthly = (1 + daily_ret).resample("MS").prod() - 1
        monthly = monthly * 100
        monthly_by_month = {}
        for m in range(1, 13):
            vals = monthly[monthly.index.month == m]
            monthly_by_month[m] = {
                "n": len(vals), "mean_pct": round(vals.mean(), 3) if len(vals) else None,
                "win_rate_pct": round(100 * (vals > 0).mean(), 1) if len(vals) else None,
            }
        means = {m: monthly_by_month[m]["mean_pct"] for m in range(1, 13) if monthly_by_month[m]["mean_pct"] is not None}
        sorted_months = sorted(means.items(), key=lambda kv: kv[1])
        sep_mean = means.get(9)
        sep_rank = [m for m, _ in sorted_months].index(9) + 1 if 9 in means else None
        # H2 기준: 9월이 최저 또는 2번째로 낮은 달(공동 최저에 가까운 수준)
        h2_pass = bool(sep_rank is not None and sep_rank <= 2)
        print(f"[{meta['name_kr']}] 9월 평균={sep_mean}%, 순위(낮은 순)={sep_rank}/12", flush=True)

        # --- H3: 최근 구간(약 30년 또는 가용 기간의 절반 중 짧은 쪽) 재검증 ---
        recent_years = min(30, (last_year - first_year) // 2)
        recent_cutoff = current_year - recent_years
        unfav_recent = [p for p in unfav if int(p["period"][:4]) >= recent_cutoff]
        fav_recent = [p for p in fav if int(p["period"][:4]) >= recent_cutoff]
        s_unfav_recent = summarize([p["return_pct"] for p in unfav_recent], f"{meta['name_kr']} 최근{recent_years}년 5~10월")
        s_fav_recent = summarize([p["return_pct"] for p in fav_recent], f"{meta['name_kr']} 최근{recent_years}년 11~4월")

        decay_detected = False
        if s_fav["mean_pct"] is not None and s_fav_recent["mean_pct"] is not None:
            full_gap = s_fav["mean_pct"] - s_unfav["mean_pct"]
            recent_gap = s_fav_recent["mean_pct"] - s_unfav_recent["mean_pct"] if s_unfav_recent["mean_pct"] is not None else None
            if recent_gap is not None and full_gap > 0 and (recent_gap <= 0 or recent_gap < full_gap * 0.5):
                decay_detected = True

        results[ticker] = {
            "name_kr": meta["name_kr"], "first_year": first_year, "last_year": last_year,
            "unfavorable": s_unfav, "favorable": s_fav,
            "h1_pass": h1_pass,
            "monthly_breakdown": monthly_by_month, "september_mean_pct": sep_mean,
            "september_rank_lowest": sep_rank, "h2_pass": h2_pass,
            "recent_years_window": recent_years,
            "recent_unfavorable": s_unfav_recent, "recent_favorable": s_fav_recent,
            "h3_decay_detected": decay_detected,
        }

    print("\n=== 요약 ===", flush=True)
    for ticker, r in results.items():
        print(f"{r['name_kr']}: H1={'PASS' if r['h1_pass'] else 'FAIL'}, "
              f"H2={'PASS' if r['h2_pass'] else 'FAIL'}(9월 순위 {r['september_rank_lowest']}), "
              f"H3 소멸감지={'YES' if r['h3_decay_detected'] else 'NO'}", flush=True)

    h1_count = sum(1 for r in results.values() if r["h1_pass"])
    h2_count = sum(1 for r in results.values() if r["h2_pass"])
    h1_verdict = "CONFIRMED" if h1_count >= 2 else ("MIXED" if h1_count == 1 else "DISCONFIRMED")
    h2_verdict = "CONFIRMED" if h2_count >= 2 else ("MIXED" if h2_count == 1 else "DISCONFIRMED")
    print(f"\nH1 전체 판정: {h1_verdict} ({h1_count}/3 지수 통과)", flush=True)
    print(f"H2 전체 판정: {h2_verdict} ({h2_count}/3 지수 통과)", flush=True)

    out_json = {"results": results, "h1_overall_verdict": h1_verdict, "h2_overall_verdict": h2_verdict,
                "h1_pass_count": h1_count, "h2_pass_count": h2_count}
    with open(f"{OUT_DIR}/international_seasonality_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
