"""대선주기 x 계절성 스택 검증 — 이 프로젝트에서 독립적으로 확인된 두 달력 효과("5월에 팔고
떠나라" 계절성, 대선 임기 4년 주기)를 처음으로 겹쳐서 본다. CPI x GDP "골디락스" 교차검증에서
얻은 교훈 — 개별로 강한 두 신호를 단순히 곱하면 기대한 증폭 효과가 안 나올 수 있다 — 이 두
"순수 달력" 효과에도 똑같이 적용되는지, 아니면 달력 효과는 매크로 국면 효과와 다르게 행동하는지
검증한다.

방법론: presidential_cycle_event_study.py의 `연도 % 4` 계산(날짜 조사 불필요, 순수 산수)과
seasonality_event_study.py의 11~4월/5~10월 6개월 구간 정의를 그대로 재사용해, 매 연도에 대해
(1) 임기 연차 라벨과 (2) 11~4월/5~10월 반기 수익률을 동시에 계산한 뒤 4x2 교차표를 만든다.
진행 중인(미완결) 연도/구간은 제외한다(2026-08-23 기준).

사전등록 가설(결과 계산 전에 명시):
  H1: "3년차(대선전해)의 11~4월" 구간이 (a) 3년차 연간 평균과 (b) 11~4월 전체 평균을
      모두 능가한다 — 즉 두 효과가 진짜로 결합되어 증폭된다.
  H2: 최약체 조합("2년차 x 5~10월")이 단순히 "나쁜 것 두 개의 합"이 아니라 부분적으로
      상쇄되거나 예상 밖으로 움직일 수 있다(FOMC CPI 교차검증의 "침체+감속" 패턴과 유사한지 확인).
  H3: 셀당 표본이 작을 것으로 예상(임기연차당 약 19년, 반기로 나누면 셀당 n=18~19에서
      더 줄어듬) — n<6인 셀은 방향성 참고로만 명시하고 과신하지 않는다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
YEAR_LABELS = {1: "1년차(집권원년)", 2: "2년차(중간선거)", 3: "3년차(대선전해)", 0: "4년차(대선해)"}


def main():
    print("S&P500 일별 데이터 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1950-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]

    current_year = pd.Timestamp.today().year  # 2026
    years = sorted(set(close.index.year))

    rows = []  # 반기 단위 레코드: year, cycle_year, half(favorable/unfavorable), return_pct
    for y in years:
        cycle_year = y % 4
        cycle_label = YEAR_LABELS[cycle_year]

        # 5~10월(비우호적) 구간 — y년 안에서 완결되므로 y < current_year면 항상 완결
        if y < current_year:
            try:
                unfav_start = pd.Timestamp(y, 5, 1)
                unfav_end = pd.Timestamp(y, 10, 31)
                seg = close.loc[unfav_start:unfav_end]
                if len(seg) > 100:
                    ret = round(100 * (seg.iloc[-1] / close.asof(unfav_start - pd.Timedelta(days=1)) - 1), 3)
                    rows.append({"year": y, "cycle_year": cycle_year, "cycle_label": cycle_label,
                                 "half": "unfavorable", "half_label": "5~10월", "period": f"{y}-05~{y}-10",
                                 "return_pct": ret})
            except Exception:
                pass

        # 11월~익년4월(우호적) 구간 — y+1년 4월까지 필요, 익년이 완결되어야(< current_year) 포함
        if y + 1 < current_year:
            try:
                fav_start = pd.Timestamp(y, 11, 1)
                fav_end = pd.Timestamp(y + 1, 4, 30)
                seg = close.loc[fav_start:fav_end]
                if len(seg) > 100:
                    ret = round(100 * (seg.iloc[-1] / close.asof(fav_start - pd.Timedelta(days=1)) - 1), 3)
                    rows.append({"year": y, "cycle_year": cycle_year, "cycle_label": cycle_label,
                                 "half": "favorable", "half_label": "11~4월", "period": f"{y}-11~{y+1}-04",
                                 "return_pct": ret})
            except Exception:
                pass

    df = pd.DataFrame(rows)
    print(f"반기 구간 {len(df)}건 계산 완료 (연도 {df['year'].min()}~{df['year'].max()})", flush=True)

    def summarize(sub, label):
        rets = sub["return_pct"].tolist()
        n = len(rets)
        if n == 0:
            print(f"[{label}] n=0 (데이터 없음)", flush=True)
            return {"n": 0, "mean_pct": None, "win_rate_pct": None}
        mean = round(sum(rets) / n, 3)
        win = round(100 * sum(1 for r in rets if r > 0) / n, 1)
        worst = round(min(rets), 2)
        best = round(max(rets), 2)
        flag = " [n<6, 방향성 참고만]" if n < 6 else ""
        print(f"[{label}] n={n}, 평균={mean}%, 승률={win}%, 최저={worst}%, 최고={best}%{flag}", flush=True)
        return {"n": n, "mean_pct": mean, "win_rate_pct": win, "worst_pct": worst, "best_pct": best,
                "small_sample": n < 6}

    # --- 8칸 교차표: 4개 임기연차 x 2개 반기 ---
    print("\n=== 4x2 교차표(임기연차 x 반기) ===", flush=True)
    cross_tab = {}
    for cy in [1, 2, 3, 0]:
        cross_tab[str(cy)] = {}
        for half in ["favorable", "unfavorable"]:
            sub = df[(df["cycle_year"] == cy) & (df["half"] == half)]
            key = "11~4월" if half == "favorable" else "5~10월"
            cross_tab[str(cy)][key] = summarize(sub, f"{YEAR_LABELS[cy]} x {key}")

    # --- 참조용: 임기연차별 연간(양 반기 통합 아님, 별도 계산) 평균 ---
    # presidential_cycle_event_study.json이 이미 있으면 재사용, 없으면 근사 계산(연간 종가 기준)
    print("\n=== 참조: 임기연차별 연간 평균(연간 수익률, 별도 계산) ===", flush=True)
    annual_rows = []
    for y in years:
        if y >= current_year:
            continue
        seg = close[close.index.year == y]
        if len(seg) < 100:
            continue
        prior = close[close.index < seg.index[0]]
        if len(prior) == 0:
            continue
        ret = round(100 * (seg.iloc[-1] / prior.iloc[-1] - 1), 3)
        annual_rows.append({"year": y, "cycle_year": y % 4, "return_pct": ret})
    annual_df = pd.DataFrame(annual_rows)
    annual_summary = {}
    for cy in [1, 2, 3, 0]:
        sub = annual_df[annual_df["cycle_year"] == cy]
        annual_summary[str(cy)] = summarize(sub, f"{YEAR_LABELS[cy]} 연간")

    # --- 참조용: 반기 전체(임기연차 무관) 평균 ---
    print("\n=== 참조: 반기 전체 평균(임기연차 무관) ===", flush=True)
    half_summary = {}
    for half, key in [("favorable", "11~4월"), ("unfavorable", "5~10월")]:
        sub = df[df["half"] == half]
        half_summary[key] = summarize(sub, f"전체 {key}")

    # --- H1 판정 ---
    y3_fav = cross_tab["3"]["11~4월"]
    y3_annual = annual_summary["3"]
    fav_all = half_summary["11~4월"]
    h1_verdict = "CONFIRMED" if (y3_fav["mean_pct"] is not None and y3_annual["mean_pct"] is not None
                                  and fav_all["mean_pct"] is not None
                                  and y3_fav["mean_pct"] > y3_annual["mean_pct"]
                                  and y3_fav["mean_pct"] > fav_all["mean_pct"]) else "DISCONFIRMED"

    # --- H2 판정: 2년차 x 5~10월 vs 단순 합 기대치 비교 ---
    y2_unfav = cross_tab["2"]["5~10월"]
    y2_annual = annual_summary["2"]
    unfav_all = half_summary["5~10월"]

    print("\n=== 요약 ===", flush=True)
    print(f"H1: 3년차x11~4월 평균={y3_fav['mean_pct']}% vs 3년차 연간={y3_annual['mean_pct']}% "
          f"vs 11~4월 전체={fav_all['mean_pct']}% => {h1_verdict}", flush=True)
    print(f"H2 참고: 2년차x5~10월 평균={y2_unfav['mean_pct']}% (n={y2_unfav['n']}) vs "
          f"2년차 연간={y2_annual['mean_pct']}% vs 5~10월 전체={unfav_all['mean_pct']}%", flush=True)

    out_json = {
        "half_year_records": df.to_dict(orient="records"),
        "cross_tab": cross_tab,
        "annual_summary_by_cycle_year": annual_summary,
        "half_summary_overall": half_summary,
        "h1_verdict": h1_verdict,
    }
    with open(f"{OUT_DIR}/cycle_x_seasonality_stack_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
