"""트랙 D×E 크로스오버 — 대선주기 효과(Year3=대선전해가 압도적으로 좋다, S&P500 전체 기준
+17.18%/승률89.5%, 1951~2025)가 섹터별로도 똑같이 "3년차가 최고"로 나타나는지, 아니면 이미
같은 대선주기 효과를 채권/금/달러로 넓혔을 때(cross_asset_presidential_cycle.py) 자산마다
최고의 해가 전부 달랐던 것처럼 섹터별로도 갈리는지 검증한다.

섹터ETF 9개(오리지널 SPDR: XLK·XLF·XLE·XLV·XLI·XLY·XLP·XLU·XLB)는 1998년 상장이라 2005년
이후만 안전하게 쓸 수 있다(cross_asset_sector_fomc.py와 동일한 제약). 대선 임기 연차는
presidential_cycle_event_study.py와 완전히 동일하게 "연도 % 4"로 계산한다(날짜 조사 불필요):

  연도 % 4 == 1  ->  임기 1년차(집권 원년)
  연도 % 4 == 2  ->  임기 2년차(중간선거 해)
  연도 % 4 == 3  ->  임기 3년차(대선 전 해)
  연도 % 4 == 0  ->  임기 4년차(대선 해)

사전등록 가설(계산 전에 명시):
- H1: 2005년 이후 완결 연도만 쓰면 임기 사이클은 4~5바퀴 정도밖에 안 돼(연차당 n=4~5),
  75년/18~19바퀴짜리 S&P500 전체 스터디보다 표본이 훨씬 작다는 걸 명시적으로 경고한다.
  9개 섹터 전부가 3년차를 최고 또는 최상위권으로 보이면 "S&P500 전체와 동일한 패턴이
  섹터 단위에서도 균일하게 재현된다"로, 일부 섹터만 3년차가 아닌 다른 해가 최고라면
  "채권/금/달러 크로스에셋 확장과 마찬가지로 섹터 단위에서도 효과가 갈린다"로 판정한다.
  사전 예측: 크로스에셋 확장에서 이미 자산마다 최고의 해가 전부 달랐던 전례가 있으므로,
  9개 섹터 중 최소 2~3개는 3년차가 아닌 다른 해를 최고로 보일 것으로 예상한다.
- H2(탐색적): 3년차에서 벗어나는 섹터가 있다면, 이미 이 프로젝트의 인상/인하 스터디에서
  정책금리에 유독 민감하다고 확인된 경기민감 섹터(금융XLF·산업재XLI·소재XLB)가 방어주
  (유틸리티XLU·필수소비재XLP·헬스케어XLV)보다 더 크게 벗어나는지 확인한다. 어느 쪽으로
  나오든(경기민감 섹터가 더 벗어나든, 반대든, 차이가 없든) 있는 그대로 보고한다.
- H3(표본 정직성 확인, 사전에 약속): 연차당 표본이 n=4~5로 매우 작을 것이 뻔하므로, 어떤
  단일 섹터의 "최고의 해" 주장도 과신하지 않는다 — 9섹터×4연차 표 전체를 그대로 공개해서
  독자가 직접 노이즈 수준을 판단할 수 있게 하고, 극단값(한 해가 칸 전체를 좌우하는 경우)은
  명시적으로 플래그한다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
YEAR_LABELS = {1: "1년차(집권원년)", 2: "2년차(중간선거)", 3: "3년차(대선전해)", 0: "4년차(대선해)"}
SECTORS = {
    "XLK": "기술",
    "XLF": "금융",
    "XLE": "에너지",
    "XLV": "헬스케어",
    "XLI": "산업재",
    "XLY": "임의소비재",
    "XLP": "필수소비재",
    "XLU": "유틸리티",
    "XLB": "소재",
}
START_YEAR = 2005
CYCLICAL = {"XLF", "XLI", "XLB"}
DEFENSIVE = {"XLU", "XLP", "XLV"}


def main():
    hist = get_multiple_price_history(list(SECTORS.keys()), start="2004-06-01", end="2026-08-20", interval="1d")
    current_year = pd.Timestamp.today().year

    results = {}
    for ticker, label in SECTORS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 없음", flush=True)
            continue
        close = df["Close"]
        years = sorted(y for y in set(close.index.year) if y >= START_YEAR)

        rows = []
        for y in years:
            if y >= current_year:
                continue  # 진행 중인 연도 제외 (presidential_cycle_event_study.py와 동일 규칙)
            seg = close[close.index.year == y]
            if len(seg) < 100:
                continue
            prior = close[close.index < seg.index[0]]
            if len(prior) == 0:
                continue
            ret = round(100 * (seg.iloc[-1] / prior.iloc[-1] - 1), 3)
            cycle_year = y % 4
            rows.append({"year": y, "cycle_year": cycle_year, "return_pct": ret})

        df_rows = pd.DataFrame(rows)
        print(f"\n=== {label}({ticker}) ({df_rows['year'].min()}~{df_rows['year'].max()}, n={len(df_rows)}) ===", flush=True)

        summary = {}
        for cy in [1, 2, 3, 0]:
            sub = df_rows[df_rows["cycle_year"] == cy]
            rets = sub["return_pct"].tolist()
            years_used = sub["year"].tolist()
            n = len(rets)
            if n == 0:
                summary[str(cy)] = {"n": 0}
                continue
            mean = round(sum(rets) / n, 3)
            win = round(100 * sum(1 for r in rets if r > 0) / n, 1)
            print(f"  [{YEAR_LABELS[cy]}] n={n}, 연도={years_used}, 수익률={rets}, 평균={mean}%, 승률={win}%", flush=True)
            summary[str(cy)] = {"n": n, "mean_pct": mean, "win_rate_pct": win, "years": years_used, "returns": rets}

        best_cy = max([1, 2, 3, 0], key=lambda cy: summary[str(cy)].get("mean_pct", -999))
        results[ticker] = {"label": label, "summary": summary, "best_cycle_year": best_cy,
                            "best_cycle_label": YEAR_LABELS[best_cy]}

    print("\n=== 섹터별 최고의 해 요약 ===", flush=True)
    year3_count = 0
    for ticker, r in results.items():
        marker = " <- 3년차 O" if r["best_cycle_year"] == 3 else " <- 3년차 아님"
        if r["best_cycle_year"] == 3:
            year3_count += 1
        print(f"  {r['label']}({ticker}): 최고={r['best_cycle_label']}{marker}", flush=True)
    print(f"\n3년차가 최고인 섹터: {year3_count}/9", flush=True)

    # H2: 경기민감 vs 방어 섹터의 "3년차 이탈 정도" 비교 (3년차 평균 - 최고연차 평균의 차이)
    print("\n=== H2: 경기민감 vs 방어 섹터의 3년차 이탈폭 ===", flush=True)
    for group_name, group in [("경기민감", CYCLICAL), ("방어", DEFENSIVE)]:
        for ticker in group:
            r = results.get(ticker)
            if not r:
                continue
            y3_mean = r["summary"]["3"].get("mean_pct")
            best_mean = r["summary"][str(r["best_cycle_year"])].get("mean_pct")
            gap = round((best_mean - y3_mean), 3) if y3_mean is not None and best_mean is not None else None
            print(f"  [{group_name}] {r['label']}({ticker}): 3년차={y3_mean}%, 최고({r['best_cycle_label']})={best_mean}%, 이탈폭={gap}pp", flush=True)

    with open(f"{OUT_DIR}/sector_presidential_cycle_study.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
