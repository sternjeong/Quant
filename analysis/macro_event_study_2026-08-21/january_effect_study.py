"""1월 효과("소형주가 1월에 대형주보다 유독 크게 이긴다") 검증 — 지금까지 트랙 D에서 다룬
계절성 효과들("5월에 팔고 떠나라", 9월 효과)은 전부 "언제 시장에 있어야 하는가"에 대한
효과였다. 1월 효과는 다르다 — "어떤 종목이 특정 달에 더 잘 나가는가"라는 완전히 다른 종류의
계절성이다. 전통적 설명은 "12월 절세매도(tax-loss selling)"다 — 연말에 손실 난 소형주를
세금 목적으로 팔았다가, 1월에 다시 사들이면서 소형주가 반등한다는 이론이다.

데이터: 러셀2000(^RUT, 소형주 대표, 1987년 9월~)과 S&P500(^GSPC, 대형주 대표)을 같은
기간으로 비교한다. 러셀2000은 1984년에 만들어졌지만 야후파이낸스 일별 데이터는 1987년부터
확보된다 — 이 프로젝트의 다른 미국 계절성 스터디(1950년~)보다 훨씬 짧은 39년치 데이터라는
제약을 사전에 명시한다.

방법론: seasonality_event_study.py와 동일한 월별 복리수익률 계산 로직을 재사용해, 매달
"소형주 수익률 - 대형주 수익률"(스프레드)을 계산하고 12개월 전부를 비교한다. 요일효과
스터디에서 확립한 "이상현상 소멸" 검증 관행(전체 기간 vs 최근 구간 재검증)을 그대로 적용한다.

사전등록 가설(결과 계산 전 명시):
  H1: 1월의 (소형주-대형주) 스프레드가 12개월 중 상위 2위 안에 들어야 "확인"으로 판정한다
      (단순히 양수인 것만으로는 부족).
  H2(이상현상 소멸 검증): 1월 효과가 존재했다면, 잘 알려지고 차익거래하기 쉬운 효과이므로
      최근 15~20년만 떼어보면 요일효과처럼 약화/소멸됐는지 확인한다(반면 이전 스터디에서
      확인한 "5~10월 계절성"은 차익거래가 어려운 6개월 단위 효과라 소멸하지 않았다).
  H3(메커니즘 검증, 탐색적): 전통적 설명(12월 절세매도)이 맞다면 12월에는 스프레드가 평균보다
      낮아야(소형주가 상대적으로 부진해야) 한다 — 실제로 그런지 확인한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
MONTH_LABELS = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]


def monthly_returns(close):
    daily_ret = close.pct_change().dropna()
    monthly = (1 + daily_ret).resample("MS").prod() - 1
    return monthly * 100


def main():
    print("러셀2000(소형주) · S&P500(대형주) 일별 데이터 조회 중...", flush=True)
    hist = get_multiple_price_history(["^RUT", "^GSPC"], start="1950-01-01", end="2026-08-20", interval="1d")
    small = hist["^RUT"]["Close"].dropna()
    large = hist["^GSPC"]["Close"].dropna()

    # 공통 구간만 사용(러셀2000이 늦게 시작)
    common_start = max(small.index.min(), large.index.min())
    small = small[small.index >= common_start]
    large = large[large.index >= common_start]
    first_year = common_start.year + 1 if common_start.month > 1 else common_start.year
    last_year = min(small.index.max().year, large.index.max().year)
    current_year = pd.Timestamp.today().year

    print(f"공통 구간: {common_start.date()} ~ (첫 완결연도 {first_year}, 현재연도 {current_year} 제외)", flush=True)

    small_m = monthly_returns(small)
    large_m = monthly_returns(large)

    # 진행 중인 마지막 달(2026-08) 이후는 이미 데이터가 없으니 자동 제외됨. 다만 스프레드 계산은
    # 두 시리즈의 교집합 인덱스만 사용.
    common_idx = small_m.index.intersection(large_m.index)
    small_m = small_m.loc[common_idx]
    large_m = large_m.loc[common_idx]
    spread = (small_m - large_m).round(3)

    monthly_summary = {}
    for m in range(1, 13):
        vals = spread[spread.index.month == m]
        n = len(vals)
        mean = round(vals.mean(), 3) if n else None
        win = round(100 * (vals > 0).mean(), 1) if n else None
        monthly_summary[m] = {"n": n, "mean_spread_pct": mean, "win_rate_pct": win}
        print(f"[{MONTH_LABELS[m-1]}] n={n}, 평균스프레드={mean}%p, 소형주우세비율={win}%", flush=True)

    means_sorted = sorted(((m, monthly_summary[m]["mean_spread_pct"]) for m in range(1, 13)), key=lambda kv: -kv[1])
    jan_rank = [m for m, _ in means_sorted].index(1) + 1
    all_months_avg = round(sum(monthly_summary[m]["mean_spread_pct"] for m in range(1, 13)) / 12, 3)
    jan_mean = monthly_summary[1]["mean_spread_pct"]
    h1_pass = bool(jan_rank <= 2)
    print(f"\n1월 스프레드 순위(높은 순): {jan_rank}/12, 1월 평균={jan_mean}%p, 전체월평균={all_months_avg}%p", flush=True)

    # --- H2: 최근 구간 재검증 ---
    total_years = last_year - first_year
    recent_years = min(20, total_years // 2)
    recent_cutoff_year = current_year - recent_years
    spread_recent = spread[spread.index.year >= recent_cutoff_year]
    spread_early = spread[spread.index.year < recent_cutoff_year]

    jan_recent = spread_recent[spread_recent.index.month == 1]
    jan_early = spread_early[spread_early.index.month == 1]
    jan_recent_mean = round(jan_recent.mean(), 3) if len(jan_recent) else None
    jan_recent_win = round(100 * (jan_recent > 0).mean(), 1) if len(jan_recent) else None
    jan_early_mean = round(jan_early.mean(), 3) if len(jan_early) else None
    jan_early_win = round(100 * (jan_early > 0).mean(), 1) if len(jan_early) else None

    print(f"\n[1월 스프레드] 초기구간(~{recent_cutoff_year - 1}) n={len(jan_early)} 평균={jan_early_mean}%p 승률={jan_early_win}% "
          f"vs 최근{recent_years}년({recent_cutoff_year}~) n={len(jan_recent)} 평균={jan_recent_mean}%p 승률={jan_recent_win}%",
          flush=True)

    decay_detected = False
    if jan_early_mean is not None and jan_recent_mean is not None:
        if jan_early_mean > 0 and (jan_recent_mean <= 0 or jan_recent_mean < jan_early_mean * 0.5):
            decay_detected = True
    h2_verdict = "CONFIRMED(소멸 감지)" if decay_detected else "DISCONFIRMED(소멸 안 됨/유지)"

    # --- H3: 12월 메커니즘 체크 ---
    dec_mean = monthly_summary[12]["mean_spread_pct"]
    dec_rank = [m for m, _ in means_sorted].index(12) + 1  # 높은 순 순위 -> 낮을수록 나쁨은 뒤쪽 순위
    h3_pass = bool(dec_mean < all_months_avg)
    print(f"\n[12월] 평균스프레드={dec_mean}%p (전체평균 {all_months_avg}%p 대비 {'낮음(가설과 일치)' if h3_pass else '높거나 같음(가설과 불일치)'}), "
          f"순위(높은 순)={dec_rank}/12", flush=True)

    h1_verdict = "CONFIRMED" if h1_pass else "DISCONFIRMED"
    h3_verdict = "CONFIRMED" if h3_pass else "DISCONFIRMED"

    print(f"\n=== 최종 판정 ===", flush=True)
    print(f"H1(1월 스프레드 상위2위): {h1_verdict} (실제 순위 {jan_rank}/12)", flush=True)
    print(f"H2(이상현상 소멸): {h2_verdict}", flush=True)
    print(f"H3(12월 절세매도 메커니즘): {h3_verdict}", flush=True)

    out_json = {
        "common_start": str(common_start.date()), "first_year": first_year, "last_year": last_year,
        "monthly_summary": monthly_summary, "january_rank_highest": jan_rank,
        "january_mean_spread_pct": jan_mean, "all_months_avg_spread_pct": all_months_avg,
        "h1_verdict": h1_verdict,
        "recent_years_window": recent_years, "recent_cutoff_year": recent_cutoff_year,
        "january_early": {"n": len(jan_early), "mean_spread_pct": jan_early_mean, "win_rate_pct": jan_early_win},
        "january_recent": {"n": len(jan_recent), "mean_spread_pct": jan_recent_mean, "win_rate_pct": jan_recent_win},
        "h2_verdict": h2_verdict,
        "december_mean_spread_pct": dec_mean, "december_rank_highest": dec_rank, "h3_verdict": h3_verdict,
    }
    with open(f"{OUT_DIR}/january_effect_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
