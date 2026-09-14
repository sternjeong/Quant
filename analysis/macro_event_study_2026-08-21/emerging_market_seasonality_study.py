"""신흥시장에서도 계절성 효과가 재현되나 — international_seasonality_study.py에서 선진시장
3곳(독일 DAX, 일본 니케이225, 영국 FTSE100) 모두에서 "5월에 팔고 떠나라"와 9월 효과가
강하게 재현된 걸 확인했다. 이번엔 시장 구조 자체가 다른 신흥시장 — 브라질 보베스파, 인도
센섹스, 한국 코스피 — 세 곳으로 같은 검증을 반복한다. 신흥시장은 기관/알고리즘 참여 비중이
낮고 통화위험·원자재 사이클·자본유출입 같은 선진시장과는 다른 거시 동인이 지배적일 수 있어,
계절성이 더 강하게(비효율적이라 차익거래가 덜 됨) 혹은 더 약하게(다른 요인이 지배적) 나타날
수 있다는 두 가지 상반된 가설이 모두 그럴듯하다.

지수 선정 이유: 지리적으로 서로 다른 3대륙의 대표 신흥시장 지수를 고른다 — 브라질 보베스파
(^BVSP, 남미 대표, 1993년~), 인도 센섹스(^BSESN, 남아시아 대표, 1997년~), 한국 코스피
(^KS11, 동아시아 대표, 1996년~). 전부 야후파이낸스에서 30년 안팎의 안정적인 일별 데이터가
확보된다(선진시장 3곳보다는 짧지만 통계적으로 의미 있는 길이).

방법론은 international_seasonality_study.py와 완전히 동일한 로직(반기 구간 정의, 월별 분해,
9월 효과 순위 계산)을 그대로 재사용한다 — 결과가 갈릴 경우 방법론 차이가 아니라 시장 자체의
차이 때문이라고 말할 수 있도록.

사전등록 가설(결과 계산 전 명시):
  H1: "5월에 팔고 떠나라" 격차가 신흥시장 3개 중 최소 2개에서 같은 부호+승률>55%로 재현된다
      (선진시장과 동일한 기준). 선진시장(3/3)과 비교해 재현 강도가 3/3(동일), 2/3(부분),
      0~1/3(거의 없음) 중 어느 쪽인지 명시적으로 비교한다.
  H2: 격차가 재현된다면 그 크기가 선진시장보다 (a) 더 크고 노이즈가 많을지(비효율적 시장,
      차익거래 부족) 또는 (b) 더 작고 신뢰도가 낮을지(통화위험·원자재 사이클 등 다른 거시
      동인이 지배적) 사전에 명확한 우세 가설 없이 두 방향 다 제시하고, 실제 데이터가 어느
      쪽인지 보고한다.
  H3(탐색적): 9월 효과(서구의 회계연도말·절세매도 캘린더에 묶인 현상일 수 있음)가 신흥시장
      에서도 나타나는지, 아니면 선진시장 고유 현상인지 확인한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"

INDICES = {
    "^BVSP": {"name_kr": "브라질 보베스파", "start": "1993-04-27"},
    "^BSESN": {"name_kr": "인도 센섹스", "start": "1997-07-01"},
    "^KS11": {"name_kr": "한국 코스피", "start": "1996-12-11"},
}

# 선진시장 비교 기준(international_seasonality_study.py 결과, 하드코딩된 참조값)
DEVELOPED_BASELINE = {
    "us": {"favorable": {"mean_pct": 6.95, "win_rate_pct": 76.0}, "unfavorable": {"mean_pct": 2.09, "win_rate_pct": 65.8}, "september_mean_pct": -0.63},
    "dax": {"favorable": {"mean_pct": 10.264, "win_rate_pct": 75.7}, "unfavorable": {"mean_pct": 0.526, "win_rate_pct": 57.9}, "september_mean_pct": -2.026, "september_rank_lowest": 1},
    "nikkei": {"favorable": {"mean_pct": 7.733, "win_rate_pct": 71.7}, "unfavorable": {"mean_pct": 0.846, "win_rate_pct": 52.5}, "september_mean_pct": -0.361, "september_rank_lowest": 2},
    "ftse": {"favorable": {"mean_pct": 6.336, "win_rate_pct": 80.5}, "unfavorable": {"mean_pct": -0.075, "win_rate_pct": 57.1}, "september_mean_pct": -0.806, "september_rank_lowest": 1},
}


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

        # --- H2: 격차 크기 비교(선진시장 대비) ---
        gap = None
        if s_fav["mean_pct"] is not None and s_unfav["mean_pct"] is not None:
            gap = round(s_fav["mean_pct"] - s_unfav["mean_pct"], 3)

        # --- H3: 월별 분해, 9월 효과 ---
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
        sep_win = monthly_by_month[9]["win_rate_pct"]
        sep_rank = [m for m, _ in sorted_months].index(9) + 1 if 9 in means else None
        h3_pass = bool(sep_rank is not None and sep_rank <= 2)
        print(f"[{meta['name_kr']}] 9월 평균={sep_mean}%, 순위(낮은 순)={sep_rank}/12", flush=True)

        results[ticker] = {
            "name_kr": meta["name_kr"], "first_year": first_year, "last_year": last_year,
            "unfavorable": s_unfav, "favorable": s_fav, "gap_pct": gap,
            "h1_pass": h1_pass,
            "monthly_breakdown": monthly_by_month, "september_mean_pct": sep_mean,
            "september_win_rate": sep_win, "september_rank_lowest": sep_rank, "h3_pass": h3_pass,
        }

        # 브라질만: 1993~94년 초인플레이션(Plano Real 이전, 헤알화 도입 1994-07)이 명목수익률을
        # 왜곡할 수 있어 1995년 이후만 따로 재계산해 강건성 확인(사후 임계값 아님 — 잘 알려진
        # 역사적 사건 기준으로 사전에 합리적으로 정할 수 있는 컷오프)
        if ticker == "^BVSP":
            close_post = close[close.index.year >= 1995]
            unfav_p, fav_p = compute_half_year_periods(close_post, current_year)
            s_unfav_p = summarize([p["return_pct"] for p in unfav_p], f"{meta['name_kr']}(1995~) 5~10월")
            s_fav_p = summarize([p["return_pct"] for p in fav_p], f"{meta['name_kr']}(1995~) 11~4월")
            daily_ret_p = close_post.pct_change().dropna()
            monthly_p = (1 + daily_ret_p).resample("MS").prod() - 1
            monthly_p = monthly_p * 100
            means_p = {m: round(monthly_p[monthly_p.index.month == m].mean(), 3) for m in range(1, 13)}
            sorted_p = sorted(means_p.items(), key=lambda kv: kv[1])
            sep_rank_p = [m for m, _ in sorted_p].index(9) + 1
            results[ticker]["post1995_robustness"] = {
                "unfavorable": s_unfav_p, "favorable": s_fav_p,
                "gap_pct": round(s_fav_p["mean_pct"] - s_unfav_p["mean_pct"], 3),
                "september_mean_pct": means_p[9], "september_rank_lowest": sep_rank_p,
            }
            print(f"[{meta['name_kr']} 1995년 이후만] 격차={results[ticker]['post1995_robustness']['gap_pct']}p, "
                  f"9월 순위={sep_rank_p}/12", flush=True)

    print("\n=== 요약 ===", flush=True)
    for ticker, r in results.items():
        print(f"{r['name_kr']}: H1={'PASS' if r['h1_pass'] else 'FAIL'}(격차={r['gap_pct']}p), "
              f"H3(9월효과)={'PASS' if r['h3_pass'] else 'FAIL'}(9월 순위 {r['september_rank_lowest']})", flush=True)

    h1_count = sum(1 for r in results.values() if r["h1_pass"])
    h3_count = sum(1 for r in results.values() if r["h3_pass"])
    h1_verdict = "CONFIRMED(선진시장과 동일 강도)" if h1_count == 3 else (
        "MIXED(부분 재현)" if h1_count == 2 else ("MIXED(약한 재현)" if h1_count == 1 else "DISCONFIRMED"))
    h3_verdict = "CONFIRMED" if h3_count >= 2 else ("MIXED" if h3_count == 1 else "DISCONFIRMED")

    # H2: 신흥시장 재현 성공 지수들의 평균 격차 vs 선진시장 평균 격차
    dev_gaps = [DEVELOPED_BASELINE[k]["favorable"]["mean_pct"] - DEVELOPED_BASELINE[k]["unfavorable"]["mean_pct"]
                for k in ["dax", "nikkei", "ftse"]]
    dev_avg_gap = round(sum(dev_gaps) / len(dev_gaps), 3)
    em_gaps = [r["gap_pct"] for r in results.values() if r["gap_pct"] is not None]
    em_avg_gap = round(sum(em_gaps) / len(em_gaps), 3) if em_gaps else None
    h2_direction = None
    if em_avg_gap is not None:
        h2_direction = "LARGER" if em_avg_gap > dev_avg_gap * 1.15 else ("SMALLER" if em_avg_gap < dev_avg_gap * 0.85 else "SIMILAR")

    print(f"\nH1 전체 판정: {h1_verdict} ({h1_count}/3 지수 통과, 선진시장은 3/3)", flush=True)
    print(f"H2: 신흥시장 평균 격차={em_avg_gap}p vs 선진시장 평균 격차={dev_avg_gap}p => {h2_direction}", flush=True)
    print(f"H3 전체 판정: {h3_verdict} ({h3_count}/3 지수 통과)", flush=True)

    out_json = {
        "results": results, "developed_baseline": DEVELOPED_BASELINE,
        "h1_overall_verdict": h1_verdict, "h1_pass_count": h1_count,
        "h2_em_avg_gap": em_avg_gap, "h2_dev_avg_gap": dev_avg_gap, "h2_direction": h2_direction,
        "h3_overall_verdict": h3_verdict, "h3_pass_count": h3_count,
    }
    with open(f"{OUT_DIR}/emerging_market_seasonality_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
