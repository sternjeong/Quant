"""트랙 G — "인상"이라고 다 같은 인상이 아니다: 정상 긴축 vs 인플레이션 진압.

지금까지 이 프로젝트의 모든 "금리 인상" 분석(FOMC 스터디, 자산군 교차분석, 섹터 반응)은 인상을
전부 하나로 묶어서 봤다. 하지만 인상에는 최소 두 가지 서로 다른 성격이 있을 수 있다:

  - "정상 긴축": 물가가 이미 안정된/식고 있는 상태에서 하는 인상 — "경기가 튼튼해서" 하는 인상
  - "인플레이션 진압": 물가가 이미 높은 상태에서 하는 인상 — "물가를 잡으려고" 하는 방어적 인상
    (가장 뚜렷한 예: 2022년 인상 사이클)

사전 등록 가설(결과를 보기 전에 먼저 적어둔다 — 결과를 본 뒤 문구를 바꾸지 않는다):
  H1: 인플레이션 진압형 인상은 정상 긴축형 인상보다 이후 60거래일 S&P500 수익률이 더
      낮거나 마이너스일 것이다.
  H2: 섹터 반응 스터디(cross_asset_sector_fomc.py)에서 나온 "기술주가 인상기에도 잘 갔다"는
      뜻밖의 결과(XLK +2.91%, 승률68.8%, 2005년 이후 32건 전체 인상 기준)는 정상 긴축형
      인상이 견인한 것이고, 인플레이션 진압형 인상에서는 기술주 성과가 뚜렷이 나쁠 것이다
      (해당 리포트에 미검증 한계로 명시됐던 부분).
  H3(탐색적, 방향 예측 없음): 유틸리티/필수소비재(XLU/XLP, "방어주")는 원래 금리에 덜
      민감하므로 두 인상 유형 간 격차가 기술주보다 작을 것이다.

분류 방법(수익률 데이터를 보기 전에 먼저 정한다):
  1. fomc_rate_event_study.py의 build_target_rate_series()/detect_rate_changes()를 그대로
     재사용해 모든 인상 이벤트(change_bps > 0)를 가져온다.
  2. 각 인상일 시점에 "이미 알려져 있던" 가장 최근 CPI 전년동월비(YoY, FRED CPIAUCSL로 직접
     계산)를 구한다.
  3. "물가가 이미 뜨거운 상태"의 사전 등록 기준값(threshold)은 연준의 암묵적 안전권 2%보다
     확실히 위인 3.0%로 정한다 — 안전권 부근(2~2.5%)은 애매하므로 뚜렷하게 위인 값을 고른다.
     CPI YoY(발표일 기준 최근값) > 3.0% -> "인플레이션 진압형", 그 이하 -> "정상 긴축형".
     사후에 결과가 깔끔해 보이도록 기준을 고르지 않기 위해, 대안 기준값 2.5%로도 동일 분석을
     반복해 결론이 기준값에 민감한지(threshold-robustness) 별도로 검증한다.
  4. 각 그룹의 실제 건수를 먼저 보고한다 — 표본이 작으면(<8건) 정직하게 참고용이라고 명시한다.
  5. H1은 S&P500(^GSPC)에 대해 CPI 데이터가 존재하는 1994년 이후 전체 구간으로 검증한다(GLD/TLT가
     필요 없으므로 이 프로젝트의 다른 자산군 스터디보다 2005년 제약 없이 더 긴 구간을 쓸 수 있다).
  6. H2/H3은 cross_asset_sector_fomc.py와 동일한 9개 섹터ETF, 2005년 이후 구간으로 검증한다
     (섹터ETF 데이터 제약).
  7. 각 가설의 결과는 CONFIRMED/DISCONFIRMED/MIXED로 명시적으로 판정한다 — 애매한 결과를
     억지로 깔끔한 스토리로 포장하지 않는다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
SECTOR_HORIZONS = [5, 20, 60]
PRIMARY_THRESHOLD = 3.0
ALT_THRESHOLD = 2.5
SECTORS = {
    "XLK": "기술", "XLF": "금융", "XLE": "에너지", "XLV": "헬스케어",
    "XLI": "산업재", "XLY": "임의소비재", "XLP": "필수소비재", "XLU": "유틸리티", "XLB": "소재",
}
SECTOR_START = "2005-01-01"


def build_cpi_yoy() -> pd.Series:
    cpi = fred_data.get_series("CPIAUCSL", start="1993-01-01")
    return cpi.pct_change(12) * 100  # 전년동월비(%)


def cpi_yoy_asof(cpi_yoy: pd.Series, event_date: pd.Timestamp) -> float | None:
    """해당 인상일 시점에 '이미 알려져 있던' 가장 최근 CPI YoY. CPI는 보통 익월 중순 발표되므로
    전전월 데이터까지만 안다고 보수적으로 가정한다(발표 시차 2개월)."""
    ref_month = pd.Timestamp(event_date.year, event_date.month, 1) - pd.DateOffset(months=2)
    avail = cpi_yoy[cpi_yoy.index <= ref_month]
    if len(avail) == 0 or pd.isna(avail.iloc[-1]):
        return None
    return float(avail.iloc[-1])


def summarize(sub: pd.DataFrame, label: str, horizons: list[int]) -> dict:
    if len(sub) == 0:
        print(f"  [{label}] 표본 없음", flush=True)
        return {"n": 0}
    out = {"n": len(sub)}
    for h in horizons:
        col = f"fwd_{h}d_pct"
        vals = sub[col].dropna()
        out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3) if len(vals) else None
        out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1) if len(vals) else None
    print(f"  [{label}] n={out['n']}, +5일={out.get('fwd_5d_mean_pct')}%, "
          f"+20일={out.get('fwd_20d_mean_pct')}%, +60일={out.get('fwd_60d_mean_pct')}%"
          f"(승률{out.get('fwd_60d_win_rate_pct')}%)"
          + (f", +120일={out.get('fwd_120d_mean_pct')}%" if "fwd_120d_mean_pct" in out else ""),
          flush=True)
    return out


def classify_hikes(hikes: pd.DataFrame, cpi_yoy: pd.Series, threshold: float) -> pd.DataFrame:
    hikes = hikes.copy()
    hikes["cpi_yoy_asof"] = [cpi_yoy_asof(cpi_yoy, d) for d in hikes.index]
    hikes["character"] = hikes["cpi_yoy_asof"].apply(
        lambda v: None if v is None else ("inflation_fighting" if v > threshold else "normal_tightening"))
    return hikes


def build_spx_hike_table(hikes: pd.DataFrame) -> pd.DataFrame:
    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    rows = []
    for event_date, row in hikes.iterrows():
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
            continue
        day0_close = close.iloc[pos]
        fwd = {}
        ok = True
        for h in HORIZONS:
            fut_pos = pos + h
            if fut_pos < len(idx):
                fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3)
            else:
                fwd[f"fwd_{h}d_pct"] = None
        rows.append({
            "date": str(event_date.date()), "change_bps": int(row["change_bps"]),
            "cpi_yoy_asof": row["cpi_yoy_asof"], "character": row["character"], **fwd,
        })
    return pd.DataFrame(rows)


def build_sector_hike_table(hikes: pd.DataFrame) -> dict:
    hikes_2005 = hikes[hikes.index >= SECTOR_START]
    hist = get_multiple_price_history(list(SECTORS.keys()), start="2004-06-01", end="2026-08-20", interval="1d")

    sector_results = {}
    for ticker, label in SECTORS.items():
        df = hist.get(ticker)
        if df is None or df.empty:
            print(f"[경고] {ticker} 없음", flush=True)
            continue
        close = df["Close"]
        idx = close.index

        rows = []
        for event_date, row in hikes_2005.iterrows():
            pos = idx.searchsorted(event_date)
            if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
                continue
            if pos + max(SECTOR_HORIZONS) >= len(idx):
                continue
            day0_close = close.iloc[pos]
            fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in SECTOR_HORIZONS}
            rows.append({"date": str(event_date.date()), "character": row["character"], **fwd})
        df_rows = pd.DataFrame(rows)
        print(f"\n=== {label}({ticker}) ===", flush=True)
        normal_sub = df_rows[df_rows["character"] == "normal_tightening"]
        fight_sub = df_rows[df_rows["character"] == "inflation_fighting"]
        sector_results[ticker] = {
            "label": label,
            "normal_tightening": summarize(normal_sub, "정상긴축", SECTOR_HORIZONS),
            "inflation_fighting": summarize(fight_sub, "인플레이션진압", SECTOR_HORIZONS),
        }
    return sector_results


def run_full_analysis(hikes_raw: pd.DataFrame, cpi_yoy: pd.Series, threshold: float, verbose: bool = True) -> dict:
    hikes = classify_hikes(hikes_raw, cpi_yoy, threshold)
    valid = hikes.dropna(subset=["character"])
    n_normal = int((valid["character"] == "normal_tightening").sum())
    n_fight = int((valid["character"] == "inflation_fighting").sum())
    if verbose:
        print(f"\n[threshold={threshold}%] 분류 가능 인상 {len(valid)}/{len(hikes)}건 "
              f"— 정상긴축 {n_normal}건, 인플레이션진압 {n_fight}건", flush=True)

    spx_table = build_spx_hike_table(valid)
    if verbose:
        print(f"\n=== H1 검증 (S&P500, 1994년 이후, threshold={threshold}%) ===", flush=True)
    spx_normal = summarize(spx_table[spx_table["character"] == "normal_tightening"], "정상긴축", HORIZONS) if verbose \
        else summarize(spx_table[spx_table["character"] == "normal_tightening"], "정상긴축", HORIZONS)
    spx_fight = summarize(spx_table[spx_table["character"] == "inflation_fighting"], "인플레이션진압", HORIZONS)

    return {
        "threshold": threshold, "n_normal": n_normal, "n_fighting": n_fight,
        "spx_normal": spx_normal, "spx_fighting": spx_fight,
        "hikes_table": valid,
        "spx_table": spx_table,
    }


def main():
    print("금리 시계열 구축 및 인상 이벤트 탐지 중...", flush=True)
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    hikes_raw = events[events["change_bps"] > 0]
    print(f"전체 인상 이벤트: {len(hikes_raw)}건 ({hikes_raw.index.min().date()} ~ {hikes_raw.index.max().date()})", flush=True)

    cpi_yoy = build_cpi_yoy()

    # 주 분석: threshold = 3.0%
    primary = run_full_analysis(hikes_raw, cpi_yoy, PRIMARY_THRESHOLD)

    # H2/H3: 섹터 반응 (2005년 이후, threshold=3.0% 분류 사용)
    print(f"\n=== H2/H3 검증 (섹터ETF 9종, 2005년 이후, threshold={PRIMARY_THRESHOLD}%) ===", flush=True)
    sector_results = build_sector_hike_table(primary["hikes_table"])

    # 기준값 민감도 체크: threshold = 2.5%
    print("\n\n### 기준값 민감도 체크 (threshold=2.5%) ###", flush=True)
    alt = run_full_analysis(hikes_raw, cpi_yoy, ALT_THRESHOLD)

    out = {
        "primary_threshold": PRIMARY_THRESHOLD,
        "alt_threshold": ALT_THRESHOLD,
        "n_total_hikes": len(hikes_raw),
        "primary": {
            "n_normal": primary["n_normal"], "n_fighting": primary["n_fighting"],
            "spx_normal": primary["spx_normal"], "spx_fighting": primary["spx_fighting"],
            "hike_events": primary["spx_table"].to_dict(orient="records"),
        },
        "alt": {
            "n_normal": alt["n_normal"], "n_fighting": alt["n_fighting"],
            "spx_normal": alt["spx_normal"], "spx_fighting": alt["spx_fighting"],
        },
        "sectors": sector_results,
    }
    with open(f"{OUT_DIR}/hike_character_split_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
