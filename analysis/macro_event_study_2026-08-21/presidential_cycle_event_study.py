"""미국 대통령 임기 4년 주기 계절성 검증 — "임기 3년차(프리 일렉션 이어)가 증시에 가장 좋다"는
유명한 통설. 대통령 선거는 항상 4로 나눠지는 해(1952, 1956, ... 2020, 2024)에 열리고 새 임기는
이듬해 1월에 시작하므로, 임기 연차는 달력 연도의 나머지 연산만으로 정확히 구분된다(날짜를
따로 찾아볼 필요가 없다 — 계산 자체가 검증 가능한 사실).

  연도 % 4 == 1  ->  임기 1년차(집권 원년)
  연도 % 4 == 2  ->  임기 2년차(중간선거 해)
  연도 % 4 == 3  ->  임기 3년차(대선 전 해)
  연도 % 4 == 0  ->  임기 4년차(대선 해)
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

    years = sorted(set(close.index.year))
    current_year = pd.Timestamp.today().year
    rows = []
    for y in years:
        if y >= current_year:
            continue  # 진행 중인(미완결) 연도는 제외 — 부분 수익률을 완결 연도와 섞으면 안 됨
        seg = close[close.index.year == y]
        if len(seg) < 100:
            continue
        prior = close[close.index < seg.index[0]]
        if len(prior) == 0:
            continue
        start_price = prior.iloc[-1]
        end_price = seg.iloc[-1]
        ret = round(100 * (end_price / start_price - 1), 3)
        cycle_year = y % 4
        rows.append({"year": y, "cycle_year": cycle_year, "cycle_label": YEAR_LABELS[cycle_year], "return_pct": ret})

    df = pd.DataFrame(rows)
    print(f"연도별 수익률 {len(df)}건 계산 완료 ({df['year'].min()}~{df['year'].max()})", flush=True)

    def summarize(sub, label):
        rets = sub["return_pct"].tolist()
        n = len(rets)
        mean = round(sum(rets) / n, 3)
        win = round(100 * sum(1 for r in rets if r > 0) / n, 1)
        worst = round(min(rets), 2)
        best = round(max(rets), 2)
        print(f"[{label}] n={n}, 평균={mean}%, 승률={win}%, 최저={worst}%, 최고={best}%", flush=True)
        return {"n": n, "mean_pct": mean, "win_rate_pct": win, "worst_pct": worst, "best_pct": best}

    print("\n=== 임기 연차별 ===", flush=True)
    summary = {}
    for cy in [1, 2, 3, 0]:
        sub = df[df["cycle_year"] == cy]
        summary[str(cy)] = summarize(sub, YEAR_LABELS[cy])

    out_json = {"years": df.to_dict(orient="records"), "summary": summary}
    with open(f"{OUT_DIR}/presidential_cycle_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
