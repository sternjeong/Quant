"""트랙 D×E 교란요인 해소 스터디 — sector_presidential_cycle_study.py가 발견한 "9개 섹터 전부가
3년차가 아니라 1년차(집권원년)를 최고로 본다"는 결과에 스스로 명시했던 미해결 교란요인을 직접
검증한다: 1년차 표본에 2009년·2021년(둘 다 침체 직후 회복기)이 우연히 섞여 있어, "임기 1년차"
자체가 아니라 "침체 회복기"가 결과를 밀어올린 것 아닌가?

방법: cross_asset_recession_split.py와 동일하게 FRED USREC(월별 침체 플래그)로 각 NBER 침체의
"종료월"을 찾고, 그 종료연도의 "다음 달력연도"를 통째로 "회복연도"로 태깅한다(예: 2009년 6월
종료 -> 회복연도=2010년, 2020년 4월 종료 -> 회복연도=2021년). presidential_cycle_event_study.py
(1951~2025, 전체지수)와 sector_presidential_cycle_study.py(2005~2025, 섹터ETF)가 이미 계산해둔
연도별 수익률 JSON을 그대로 재사용하고(가격 재조회 없음), 여기에 회복연도 태그만 추가해
"회복연도 포함 1년차" vs "회복연도 제외 1년차"를 비교한다.

사전등록 가설(계산 전에 명시, 그대로 인용):
- H1: 임기 1년차 버킷에서 "침체 직후 회복연도"에 해당하는 달력연도들을 제외하면(USREC 플래그
  재사용, 침체 종료월의 다음 달력연도를 회복연도로 표시), 전체지수 스터디(1951~2025)와 섹터
  스터디(2005~2025) 둘 다에서 남은 "1년차·비회복연도"가 더 이상 3년차보다 압도적으로 강하게
  보이지 않을 것이다 — 즉 "1년차가 강하다"가 "회복연도가 강한데 우연히 임기 1년차에 몰려
  있었다"로 무너지는지 테스트한다. 구체적 예측: 2009년(1년차)과 2021년(1년차)이 둘 다 회복연도로
  플래그됐던 만큼, 회복연도 제외 후 전체지수 표본에서는 3년차가 다시 우위를 되찾거나 최소한
  1년차와의 격차가 크게 좁혀질 것으로 예측한다(원래 3년차 발견 자체가 75년치로 매우 견고했으므로).
  다만 섹터 스터디는 표본이 훨씬 작아(2005~2025, 사이클 4~5바퀴) 2개 연도만 제외해도 결과가
  애매해질 수 있다고 미리 경계한다.
- H2(역방향 검증, 확증편향 방지용): "임기 연차"라는 라벨과 완전히 무관하게, "NBER 침체 종료
  다음 달력연도"만을 독자적인 축으로 놓고 전체 가용 기간(2005년 이후로 한정하지 않고 1951년부터)
  S&P500 수익률을 계산한다. 만약 회복연도가 어떤 임기연차에 해당하든 상관없이 그 자체로 강한
  성과를 보인다면, 이는 "1년차 효과"가 사실 "회복연도 효과"를 임기연차로 잘못 라벨링한 결과라는
  것을 독립적으로 뒷받침하는 증거가 된다.
- H3(소표본 정직성, 계산 전에 인정): 섹터 스터디는 칸당 표본이 이미 n=5~6으로 작은데, 거기서
  2개 연도(2010·2021 — 아래 실제 계산 결과 참고)를 추가로 제외하면 남는 표본은 n=3~4로 매우
  얇아진다. 섹터별 제외-후 비교는 어떤 결과가 나오든 방향성 참고용으로만 취급하고, 확신 있는
  결론은 표본이 훨씬 큰 전체지수 결과 쪽에 더 무겁게 둔다.

※ 계산 과정에서 발견한 중요한 방법론적 수정(사전에 알 수 없었던 것): 원래 섹터 스터디가
"우연히 섞여 있다"고 지목한 연도는 2009·2021이었지만, USREC의 실제 침체 "종료월"(마지막
침체월) 기준으로 엄밀히 계산하면 2008~09년 대침체는 2009년 6월에 종료되어 "다음 달력연도"는
2009년이 아니라 2010년이다(2009년 자체는 1~6월이 여전히 침체 중이라 "완전한 회복연도"가
아니라 침체와 회복이 섞인 해). 코로나 침체는 2020년 4월 종료라 다음 달력연도는 2021년으로
원래 짐작과 일치한다. 이 차이 자체가 흥미로운 발견이라 아래 리포트에 그대로 반영한다
(2010년은 임기 2년차, 2021년만 임기 1년차 — 즉 엄밀하게는 두 회복연도 중 하나만 1년차 버킷에
들어간다).
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
YEAR_LABELS = {1: "1년차(집권원년)", 2: "2년차(중간선거)", 3: "3년차(대선전해)", 0: "4년차(대선해)"}


def get_recovery_years() -> list[int]:
    """USREC 월별 플래그에서 각 침체의 종료월(마지막 침체=1인 달)을 찾고, 그 다음 달력연도를
    "회복연도"로 반환한다. cross_asset_recession_split.py와 동일한 USREC 재사용, 캐시가
    1988년 이후로 잘려 있을 수 있어 use_cache=False로 1948년부터 강제 재조회한다."""
    rec = fred_data.get_series("USREC", start="1948-01-01", use_cache=False)
    rec = rec.dropna()
    prev = rec.shift(1)
    end_months = rec.index[(prev == 1.0) & (rec == 0.0)]  # 침체 종료 다음달(첫 0인 달)
    recovery_years = sorted(set((em - pd.DateOffset(months=1)).year + 1 for em in end_months))
    return recovery_years


def summarize(rets: list[float]) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0}
    mean = round(sum(rets) / n, 3)
    win = round(100 * sum(1 for r in rets if r > 0) / n, 1)
    return {"n": n, "mean_pct": mean, "win_rate_pct": win}


def main():
    recovery_years = get_recovery_years()
    print(f"회복연도(침체 종료 다음 달력연도): {recovery_years}", flush=True)

    # ---------- 전체지수 (1951~2025) ----------
    idx_data = json.load(open(f"{OUT_DIR}/presidential_cycle_event_study.json", encoding="utf-8"))
    idx_years = idx_data["years"]
    for row in idx_years:
        row["is_recovery"] = row["year"] in recovery_years

    index_result = {}
    for cy in [1, 2, 3, 0]:
        cell = [r for r in idx_years if r["cycle_year"] == cy]
        before = summarize([r["return_pct"] for r in cell])
        after = summarize([r["return_pct"] for r in cell if not r["is_recovery"]])
        excluded = [r["year"] for r in cell if r["is_recovery"]]
        index_result[str(cy)] = {"label": YEAR_LABELS[cy], "before": before, "after": after, "excluded_years": excluded}
        print(f"[전체지수 {YEAR_LABELS[cy]}] 제외전 n={before['n']} 평균={before.get('mean_pct')}% "
              f"| 제외후 n={after['n']} 평균={after.get('mean_pct')}% (제외연도={excluded})", flush=True)

    # ---------- 섹터 (2005~2025) ----------
    sector_data = json.load(open(f"{OUT_DIR}/sector_presidential_cycle_study.json", encoding="utf-8"))
    sector_result = {}
    for ticker, r in sector_data.items():
        cell = r["summary"]["1"]  # 1년차만 대상
        years = cell.get("years", [])
        rets = cell.get("returns", [])
        before = summarize(rets)
        kept = [(y, ret) for y, ret in zip(years, rets) if y not in recovery_years]
        after = summarize([ret for _, ret in kept])
        excluded = [y for y in years if y in recovery_years]
        sector_result[ticker] = {"label": r["label"], "before": before, "after": after, "excluded_years": excluded,
                                   "year3_mean": r["summary"]["3"].get("mean_pct")}
        print(f"[섹터 {r['label']}] 1년차 제외전 n={before['n']} 평균={before.get('mean_pct')}% "
              f"| 제외후 n={after['n']} 평균={after.get('mean_pct')}% (제외연도={excluded}) "
              f"| 참고 3년차 평균={r['summary']['3'].get('mean_pct')}%", flush=True)

    # ---------- H2: 회복연도 자체를 독립축으로 (임기연차 라벨 무시, 1951~2025 전체 기간) ----------
    all_years = idx_years
    recovery_rets = [r["return_pct"] for r in all_years if r["is_recovery"]]
    non_recovery_rets = [r["return_pct"] for r in all_years if not r["is_recovery"]]
    h2 = {"recovery": summarize(recovery_rets), "non_recovery": summarize(non_recovery_rets)}
    print(f"\n[H2] 회복연도 단독축: n={h2['recovery']['n']} 평균={h2['recovery'].get('mean_pct')}% "
          f"승률={h2['recovery'].get('win_rate_pct')}% vs 비회복연도 n={h2['non_recovery']['n']} "
          f"평균={h2['non_recovery'].get('mean_pct')}% 승률={h2['non_recovery'].get('win_rate_pct')}%", flush=True)

    out = {
        "recovery_years": recovery_years,
        "index_study": index_result,
        "sector_study": sector_result,
        "h2_standalone_recovery_axis": h2,
    }
    with open(f"{OUT_DIR}/recovery_year_confound_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
