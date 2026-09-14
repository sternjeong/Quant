"""트랙 G × 트랙 E 크로스오버 — 인하의 물가 국면(디스인플레이션 vs 안정물가)에 따라 섹터
반응이 달라지는가.

트랙G의 인상 스터디(hike_character_split_study.py)는 "기술주가 인상기에도 잘 갔다"는
섹터 스터디(cross_asset_sector_fomc.py)의 결과가 인상의 두 성격(정상긴축/인플레이션진압)
모두에서 재현되는지 확인했다(H2 DISCONFIRMED — 기술주는 두 유형 모두에서 견조, 격차가
9개 섹터 중 가장 작은 축이었다). 이번엔 그 거울상 질문을 인하 쪽에 던진다 — 섹터 스터디가
찾은 "금융주가 인하 후 가장 크게 다친다"(XLF, 21건 인하 전체 풀링 기준 &minus;6.66%,
승률42.9%, 9개 섹터 중 최악)는 결과가 인하의 두 성격(디스인플레이션/안정물가,
cut_character_split_study.py가 이미 정의한 분류) 양쪽에서 똑같이 나타나는지, 아니면 한쪽에
쏠려 있는지 확인한다.

새로 만들지 않고 재사용하는 것:
  - detect_rate_changes()로 인하 이벤트 탐지 (fomc_rate_event_study.py)
  - CPI YoY 3개월전대비 가속/감속 대리지표로 디스인플레이션/안정물가 분류
    (cut_character_split_study.py와 동일한 정의: diff(3) <= 0 -> 디스인플레이션)
  - 9개 섹터ETF(XLK/XLF/XLE/XLV/XLI/XLY/XLP/XLU/XLB), 2005년 이후, +5/20/60거래일 반응
    측정 방식 (cross_asset_sector_fomc.py와 동일)

사전 등록 가설(결과를 계산하기 전에 적어둔다):
  H1: 금융주(XLF)의 인하 후 부진("순이자마진 압박" 가설)은 안정물가 인하보다 디스인플레이션
      인하에서 더 심할 것이다 — 물가가 실제로 식고 있다는 건 더 길고 깊은 인하 사이클을
      암시하므로, 순이자마진 압박 논리가 더 강하게 작동할 것이라는 예상.
  H2: 에너지(XLE)의 인하 후 호조(원래 스터디에서 +4.42%였지만 승률 47.6%로 절반 미만이라
      "소수의 큰 반등이 평균을 끌어올렸을 뿐"이라고 이미 한계로 명시됨)는 두 인하 성격 중
      한쪽에 쏠려 있을 것이다 — 어느 쪽이 더 일관된(승률이 더 높은) 성과를 보이는지 확인한다.
  H3(인상 스터디 재현 시도): 기술주(XLK)는 인하의 두 성격 사이에서도 격차가 작을 것이다 —
      인상 스터디에서 확인된 "기술주는 정상긴축/인플레이션진압 격차가 9개 섹터 중 가장
      작았다(0.48%p)"는 패턴이, 인하 쪽 두 성격(디스인플레이션/안정물가) 사이에서도 똑같이
      재현되는지 — 즉 "여러 국면에 걸친 회복력"이 인상 상황에서만 나타나는 게 아니라 기술주
      자체의 일반적 속성인지 확인한다.

방법론 메모: 2005년 이후 인하는 21건뿐이고 이를 다시 두 성격으로 쪼개면 셀당 표본이 더
작아진다(사전에 표본이 작을 것으로 예상 — n<5인 셀은 방향성 참고로만 명시)."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60]
SECTOR_START = "2005-01-01"
SECTORS = {
    "XLK": "기술", "XLF": "금융", "XLE": "에너지", "XLV": "헬스케어",
    "XLI": "산업재", "XLY": "임의소비재", "XLP": "필수소비재", "XLU": "유틸리티", "XLB": "소재",
}


def cpi_accel_asof(cpi_accel: pd.Series, event_date: pd.Timestamp):
    """cut_character_split_study.py와 동일한 정의: 발표 시차를 감안해 전월 데이터까지만
    '이미 알려져 있었다'고 본다."""
    ref_month = pd.Timestamp(event_date.year, event_date.month, 1) - pd.DateOffset(months=1)
    avail = cpi_accel[cpi_accel.index <= ref_month]
    if len(avail) == 0 or pd.isna(avail.iloc[-1]):
        return None
    return float(avail.iloc[-1])


def summarize(sub: pd.DataFrame, label: str, horizons=HORIZONS) -> dict:
    if len(sub) == 0:
        print(f"    [{label}] 표본 없음", flush=True)
        return {"n": 0}
    out = {"n": len(sub)}
    for h in horizons:
        col = f"fwd_{h}d_pct"
        vals = sub[col].dropna()
        if len(vals) == 0:
            continue
        out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
        out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
    print(f"    [{label}] n={out['n']}, +60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
    return out


def main():
    print("금리 시계열 구축 및 인하 이벤트 탐지 중...", flush=True)
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    cuts_raw = events[events["change_bps"] < 0]
    cuts_2005 = cuts_raw[cuts_raw.index >= SECTOR_START]
    print(f"2005년 이후 인하 이벤트: {len(cuts_2005)}건", flush=True)

    cpi = fred_data.get_series("CPIAUCSL", start="1988-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

    cuts_meta = cuts_2005.copy()
    cuts_meta["cpi_accel_pp"] = [cpi_accel_asof(cpi_accel, d) for d in cuts_meta.index]
    cuts_meta["disinflationary"] = cuts_meta["cpi_accel_pp"].apply(
        lambda v: None if v is None else (v <= 0))
    valid_cuts = cuts_meta.dropna(subset=["cpi_accel_pp"])
    n_disinfl = int(valid_cuts["disinflationary"].sum())
    n_stable = int((~valid_cuts["disinflationary"]).sum())
    print(f"CPI 매칭된 2005년 이후 인하: {len(valid_cuts)}건 — "
          f"디스인플레이션 {n_disinfl}건, 안정물가 {n_stable}건", flush=True)
    for d, row in valid_cuts.iterrows():
        tag = "디스인플레이션" if row["disinflationary"] else "안정물가"
        print(f"  {d.date()}: {row['change_bps']}bp, CPI가속도={row['cpi_accel_pp']:.2f}pp -> {tag}", flush=True)

    print("\n섹터ETF 가격 데이터 조회 중...", flush=True)
    hist = get_multiple_price_history(list(SECTORS.keys()), start="2004-06-01", end="2026-08-20", interval="1d")

    results = {}
    for ticker, label in SECTORS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 없음", flush=True)
            continue
        close = df["Close"]
        idx = close.index

        rows = []
        for event_date, row in valid_cuts.iterrows():
            pos = idx.searchsorted(event_date)
            if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
                continue
            if pos + max(HORIZONS) >= len(idx):
                continue
            day0_close = close.iloc[pos]
            fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in HORIZONS}
            rows.append({"date": str(event_date.date()), "disinflationary": row["disinflationary"], **fwd})
        df_rows = pd.DataFrame(rows)
        print(f"\n=== {label}({ticker}) ===", flush=True)
        disinfl_sub = df_rows[df_rows["disinflationary"] == True]
        stable_sub = df_rows[df_rows["disinflationary"] == False]
        results[ticker] = {
            "label": label,
            "disinflationary": summarize(disinfl_sub, "디스인플레이션 인하"),
            "stable": summarize(stable_sub, "안정물가 인하"),
        }

    with open(f"{OUT_DIR}/cut_character_sector_study.json", "w", encoding="utf-8") as f:
        json.dump({
            "n_cuts_2005": len(cuts_2005), "n_cpi_matched": len(valid_cuts),
            "n_disinflationary": n_disinfl, "n_stable": n_stable,
            "events": valid_cuts.reset_index().rename(columns={"index": "date"}).to_dict(orient="records"),
            "sectors": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
