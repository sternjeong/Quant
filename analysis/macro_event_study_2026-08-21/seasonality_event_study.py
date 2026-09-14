""""5월에 팔고 떠나라"(Sell in May and Go Away) 계절성 통설 검증 — 이 프로젝트에서 처음으로
매크로 발표/신호가 아니라 순수 달력 효과를 다룬다. 1950~2026년 S&P500 76년치 일별 데이터로
(1) 5~10월(비우호적 6개월) vs 11~4월(우호적 6개월) 수익률을 비교하고, (2) 월별 평균수익률로
어느 달이 실제로 그 효과를 이끄는지 분해한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"


def main():
    print("S&P500 일별 데이터 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1950-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    daily_ret = close.pct_change().dropna()

    # 월별 수익률(각 달의 첫 거래일 시가 개념 대신, 그 달의 일별수익률 복리)
    monthly = (1 + daily_ret).resample("MS").prod() - 1
    monthly = monthly * 100

    # (1) 5~10월 vs 11~4월 6개월 구간 수익률(연도별)
    favorable_periods = []  # 11월~익년4월
    unfavorable_periods = []  # 5월~10월

    years = sorted(set(close.index.year))
    for y in years:
        try:
            unfav_start = pd.Timestamp(y, 5, 1)
            unfav_end = pd.Timestamp(y, 10, 31)
            seg = close.loc[unfav_start:unfav_end]
            if len(seg) > 100:
                ret = round(100 * (seg.iloc[-1] / close.asof(unfav_start - pd.Timedelta(days=1)) - 1), 3)
                unfavorable_periods.append({"period": f"{y}-05~{y}-10", "return_pct": ret})
        except Exception:
            pass
        try:
            fav_start = pd.Timestamp(y, 11, 1)
            fav_end = pd.Timestamp(y + 1, 4, 30)
            seg = close.loc[fav_start:fav_end]
            if len(seg) > 100:
                ret = round(100 * (seg.iloc[-1] / close.asof(fav_start - pd.Timedelta(days=1)) - 1), 3)
                favorable_periods.append({"period": f"{y}-11~{y+1}-04", "return_pct": ret})
        except Exception:
            pass

    def summarize(periods, label):
        rets = [p["return_pct"] for p in periods]
        n = len(rets)
        mean = round(sum(rets) / n, 3)
        win = round(100 * sum(1 for r in rets if r > 0) / n, 1)
        print(f"[{label}] n={n}, 평균={mean}%, 승률={win}%", flush=True)
        return {"n": n, "mean_pct": mean, "win_rate_pct": win}

    print("\n=== 6개월 구간 비교 ===", flush=True)
    s_unfav = summarize(unfavorable_periods, "5~10월(sell in May)")
    s_fav = summarize(favorable_periods, "11~4월(우호적 계절)")

    # (2) 월별 평균 수익률 분해
    monthly_by_month = {}
    for m in range(1, 13):
        vals = monthly[monthly.index.month == m]
        monthly_by_month[m] = {
            "n": len(vals), "mean_pct": round(vals.mean(), 3),
            "win_rate_pct": round(100 * (vals > 0).mean(), 1),
        }
        print(f"[{m}월] n={monthly_by_month[m]['n']}, 평균={monthly_by_month[m]['mean_pct']}%, "
              f"승률={monthly_by_month[m]['win_rate_pct']}%", flush=True)

    out_json = {
        "unfavorable_periods": unfavorable_periods, "favorable_periods": favorable_periods,
        "summary": {"unfavorable": s_unfav, "favorable": s_fav},
        "monthly_breakdown": monthly_by_month,
    }
    with open(f"{OUT_DIR}/seasonality_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
