"""트랙 A(동결 국면) x 트랙 E(섹터 로테이션) 크로스오버 — 섹터별 "동결 국면" 반응 스터디.

지금까지 두 스터디가 따로 존재했다: ① `fomc_pause_regime_study.py`는 연준이 금리를 오래
(180일 이상) 그대로 두는 "장기 동결 국면" 자체가 S&amp;P500 전체에 유리하다는 걸 확인했다
(동결 구간 평균 연율화 +14.75% vs 무조건부 기준선 +8.73%). ② `cross_asset_sector_fomc.py`는
"금리를 인상/인하하는 순간"에 9개 섹터가 어떻게 다르게 반응하는지 확인했다(금융이 인하 후
가장 나쁨, -6.66%/승률42.9%).

아무도 "인상/인하의 순간"이 아니라 "동결 국면 그 자체" 동안 9개 섹터가 어떻게 반응하는지는
본 적이 없다. 이 프로젝트에서 반복적으로 나온 패턴 — "전체(pooled) 지표가 좋아 보여도 섹터별로
쪼개면 크게 갈린다"(인상/인하 스터디에서 이미 확인) — 이 "동결"이라는 새로운 국면에도 그대로
적용되는지 확인한다.

방법론: 동결 구간 탐지는 `fomc_pause_regime_study.py`와 완전히 동일한 로직(`build_target_rate_series`
+ `detect_rate_changes`, 180일 이상 간격을 "장기 동결"로 정의)을 그대로 재사용해 재탐지한다
(로직이 결정론적이므로 동일한 18개 구간이 나온다 — 재검증됨). 섹터 ETF 데이터는
`cross_asset_sector_fomc.py`와 동일한 9개 오리지널 SPDR 섹터(XLK/XLF/XLE/XLV/XLI/XLY/XLP/XLU/XLB)
및 동일한 2005년 이후 제약을 사용한다(ETF 상장 자체는 1998년이지만, 기존 섹터 스터디가
"2005년 이후"로 표본을 통일했으므로 직접 비교를 위해 동일하게 맞춘다).

18개 동결 구간 중 2005년 이후 시작한 것만 섹터 스터디와 비교 가능 — 실제로 몇 건이 해당하는지는
계산 후 본문에 명시한다(결과를 보기 전에 미리 셀 수는 없음, `fomc_pause_regime_study.json`의
날짜 리스트를 그대로 필터링).

사전등록 가설 (결과를 보기 전에 여기 기록):
H1: 금융(XLF)은 금리 "국면"(인상/인하)에 민감하다는 게 이미 확인됐다(인하 후 -6.66%/승률42.9%,
    9개 섹터 중 최악 — 예대마진 압박 + 위기성 인하 혼입). "동결 = 조용하고 안정적인 배경"이라는
    직관에 따르면, 금융에게 동결은 인하의 마진압박도 없고 인상이 몰고 올 수도 있는 위험도 없는
    "가장 편안한 국면"일 것이다. 따라서 금융의 동결 구간 반응이 자기 자신의 인상/인하 반응
    (비교 기준선: 인상 +0.412%/승률56.2%, 인하 -6.664%/승률42.9%, 둘 다 `cross_asset_sector_fomc.json`
    기존 수치)보다 확연히 낫게(더 높은 연율화 수익률로) 나올 것이라 예측한다.
H2: 9개 섹터를 동결 구간 평균 연율화 수익률로 순위 매겼을 때, 그 순위가 인상 국면 순위(동결
    국면은 흔히 인상 사이클이 "끝났다"고 판단된 뒤에 오므로, 인상 후반부와 성격이 비슷할 수
    있다는 직관)와 더 비슷한지, 인하 국면 순위(동결은 때로 인하를 앞두고 있어 선행적 성격을
    공유할 수 있다는 직관)와 더 비슷한지 스피어만 순위상관으로 비교한다. 결과를 보기 전에는
    방향을 예단하지 않는다(탐색적으로 어느 쪽이 더 가까운지만 보고).
H3 (탐색적): 9개 섹터 중 "동결 구간 성적 - 무조건부(전체 기간) 성적" 격차가 가장 큰 섹터,
    즉 국면 자체(동결이냐 아니냐)에 가장 민감한 섹터가 어디인지 확인한다. 이미 검증된
    인상/인하 축(트랙E)보다 "동결/비동결" 축에 더 크게 좌우되는 섹터가 있는지가 핵심 질문.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
PAUSE_MIN_DAYS = 180
DATA_END = "2026-08-20"
SECTOR_START = "2005-01-01"
SECTORS = {
    "XLK": "기술", "XLF": "금융", "XLE": "에너지", "XLV": "헬스케어", "XLI": "산업재",
    "XLY": "임의소비재", "XLP": "필수소비재", "XLU": "유틸리티", "XLB": "소재",
}

# 기존 cross_asset_sector_fomc.py에서 확인된 인상/인하 반응(+60일, 2005년 이후 53건) — 비교용으로 하드코딩(재계산 X, 그대로 재사용)
SECTOR_HIKE_CUT = {
    "XLK": {"hike_60d": 2.909, "hike_win": 68.8, "cut_60d": 1.308, "cut_win": 52.4},
    "XLF": {"hike_60d": 0.412, "hike_win": 56.2, "cut_60d": -6.664, "cut_win": 42.9},
    "XLE": {"hike_60d": 2.124, "hike_win": 50.0, "cut_60d": 4.417, "cut_win": 47.6},
    "XLV": {"hike_60d": 1.245, "hike_win": 71.9, "cut_60d": 1.042, "cut_win": 52.4},
    "XLI": {"hike_60d": 1.237, "hike_win": 59.4, "cut_60d": -0.94, "cut_win": 52.4},
    "XLY": {"hike_60d": 1.04, "hike_win": 56.2, "cut_60d": -0.07, "cut_win": 57.1},
    "XLP": {"hike_60d": 0.467, "hike_win": 59.4, "cut_60d": 0.774, "cut_win": 47.6},
    "XLU": {"hike_60d": 1.404, "hike_win": 56.2, "cut_60d": 0.706, "cut_win": 57.1},
    "XLB": {"hike_60d": 0.363, "hike_win": 53.1, "cut_60d": 1.43, "cut_win": 52.4},
}


def annualized_return(close_seg):
    if len(close_seg) < 2:
        return None
    days = (close_seg.index[-1] - close_seg.index[0]).days
    if days <= 0:
        return None
    ret = close_seg.iloc[-1] / close_seg.iloc[0] - 1
    return round(100 * ((1 + ret) ** (365.25 / days) - 1), 3)


def main():
    print("금리 시계열 재구축(fomc_pause_regime_study.py와 동일 로직) 중...", flush=True)
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    change_dates = sorted(events.index.tolist())

    rate_start = rate.index.min()
    rate_end = min(rate.index.max(), pd.Timestamp(DATA_END))
    boundaries = [rate_start] + change_dates + [rate_end]

    all_pauses = []
    for i in range(len(boundaries) - 1):
        start_dt, end_dt = boundaries[i], boundaries[i + 1]
        duration_days = (end_dt - start_dt).days
        if duration_days < PAUSE_MIN_DAYS:
            continue
        all_pauses.append({"start": start_dt, "end": end_dt, "duration_days": duration_days})

    print(f"전체 장기 동결 구간(180일 이상): {len(all_pauses)}건 (원 스터디와 동일해야 함)", flush=True)

    pauses = [p for p in all_pauses if p["start"] >= pd.Timestamp(SECTOR_START)]
    print(f"이 중 {SECTOR_START} 이후 시작 = 섹터ETF로 검증 가능한 구간: {len(pauses)}/{len(all_pauses)}건", flush=True)
    for p in pauses:
        print(f"  {p['start'].date()} ~ {p['end'].date()} ({p['duration_days']}일)", flush=True)

    hist = get_multiple_price_history(list(SECTORS.keys()), start="2004-06-01", end=DATA_END, interval="1d")

    results = {}
    for ticker, label in SECTORS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 없음", flush=True)
            continue
        close = df["Close"]

        # 동결 구간별 연율화 수익률
        pause_anns = []
        pause_detail = []
        for p in pauses:
            seg = close[(close.index >= p["start"]) & (close.index <= p["end"])]
            ann = annualized_return(seg)
            if ann is not None:
                pause_anns.append(ann)
            pause_detail.append({"start": str(p["start"].date()), "end": str(p["end"].date()), "annualized_pct": ann})

        mean_pause_ann = round(sum(pause_anns) / len(pause_anns), 3) if pause_anns else None

        # 무조건부(전체 2005~) 연율화 수익률
        full_seg = close[close.index >= pd.Timestamp(SECTOR_START)]
        unconditional_ann = annualized_return(full_seg)

        results[ticker] = {
            "label": label,
            "n_pauses": len(pause_anns),
            "pause_mean_annualized_pct": mean_pause_ann,
            "unconditional_annualized_pct": unconditional_ann,
            "gap_pause_minus_unconditional_pct": round(mean_pause_ann - unconditional_ann, 3) if (mean_pause_ann is not None and unconditional_ann is not None) else None,
            "hike_60d_mean_pct": SECTOR_HIKE_CUT[ticker]["hike_60d"],
            "hike_60d_win_pct": SECTOR_HIKE_CUT[ticker]["hike_win"],
            "cut_60d_mean_pct": SECTOR_HIKE_CUT[ticker]["cut_60d"],
            "cut_60d_win_pct": SECTOR_HIKE_CUT[ticker]["cut_win"],
            "pause_detail": pause_detail,
        }
        print(f"{label}({ticker}): 동결평균연율화={mean_pause_ann}% (n={len(pause_anns)}), "
              f"무조건부={unconditional_ann}%, 격차={results[ticker]['gap_pause_minus_unconditional_pct']}%", flush=True)

    # 순위 비교 (H2)
    df_rank = pd.DataFrame({
        t: {
            "pause": r["pause_mean_annualized_pct"],
            "hike": r["hike_60d_mean_pct"],
            "cut": r["cut_60d_mean_pct"],
        } for t, r in results.items()
    }).T

    df_rank["pause_rank"] = df_rank["pause"].rank(ascending=False)
    df_rank["hike_rank"] = df_rank["hike"].rank(ascending=False)
    df_rank["cut_rank"] = df_rank["cut"].rank(ascending=False)

    corr_pause_hike = round(df_rank["pause_rank"].corr(df_rank["hike_rank"], method="pearson"), 3)
    corr_pause_cut = round(df_rank["pause_rank"].corr(df_rank["cut_rank"], method="pearson"), 3)

    print(f"\n[H2] 동결 순위 vs 인상 순위 스피어만 상관 = {corr_pause_hike}", flush=True)
    print(f"[H2] 동결 순위 vs 인하 순위 스피어만 상관 = {corr_pause_cut}", flush=True)
    print("\n동결 구간 순위(연율화 수익률 내림차순):", flush=True)
    for t, row in df_rank.sort_values("pause_rank").iterrows():
        print(f"  {int(row['pause_rank'])}. {SECTORS[t]}({t}): 동결={row['pause']}% / 인상순위={int(row['hike_rank'])} / 인하순위={int(row['cut_rank'])}", flush=True)

    # H1: 금융 비교
    xlf = results["XLF"]
    print(f"\n[H1] 금융(XLF): 동결평균연율화={xlf['pause_mean_annualized_pct']}%, "
          f"인상반응(+60d)={xlf['hike_60d_mean_pct']}%(승률{xlf['hike_60d_win_pct']}%), "
          f"인하반응(+60d)={xlf['cut_60d_mean_pct']}%(승률{xlf['cut_60d_win_pct']}%)", flush=True)

    # H3: 격차 최대 섹터
    gap_ranked = sorted(results.items(), key=lambda kv: abs(kv[1]["gap_pause_minus_unconditional_pct"] or 0), reverse=True)
    print("\n[H3] 동결-무조건부 격차(절대값) 랭킹:", flush=True)
    for t, r in gap_ranked:
        print(f"  {r['label']}({t}): 격차={r['gap_pause_minus_unconditional_pct']}%p (동결={r['pause_mean_annualized_pct']}%, 무조건부={r['unconditional_annualized_pct']}%)", flush=True)

    out = {
        "pause_min_days": PAUSE_MIN_DAYS,
        "sector_start": SECTOR_START,
        "n_pauses_total": len(all_pauses),
        "n_pauses_usable": len(pauses),
        "pauses_usable": [{"start": str(p["start"].date()), "end": str(p["end"].date()), "duration_days": p["duration_days"]} for p in pauses],
        "sectors": results,
        "h2_spearman": {"pause_vs_hike": corr_pause_hike, "pause_vs_cut": corr_pause_cut},
        "h3_top_gap_ticker": gap_ranked[0][0],
        "h3_top_gap_pct": gap_ranked[0][1]["gap_pause_minus_unconditional_pct"],
    }
    with open(f"{OUT_DIR}/sector_pause_regime_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
