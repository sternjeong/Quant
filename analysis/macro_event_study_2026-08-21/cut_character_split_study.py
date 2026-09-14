"""트랙 G 확장 — 인하에도 인상과 같은 거울상 분류를 적용하고, 인상 스터디의 2022년 편중
한계를 직접 검증한다.

Part 1: "인하도 다 같은 인하가 아니다" — 인상을 물가 국면으로 나눴던 것과 대칭으로, 인하도
"물가가 뚜렷이 식고 있을 때의 인하"(디스인플레이션 인하)와 "물가가 뚜렷이 식지 않는 상태에서의
인하"(안정물가 인하 — 순수 성장보험 등 물가 외 이유로 인하)로 나눈다. CPI 가속/감속 판정은
새로 만들지 않고 cpi_release_event_study.py/joint_regime_event_study.py/fomc_cpi_cross_study.py
에서 이미 쓴 "전년동월비 3개월 전 대비 변화(diff(3))" 대리지표를 그대로 재사용한다
(diff(3) <= 0 -> 감속/디스인플레이션, > 0 -> 감속 아님).

  H1: 디스인플레이션 인하는 안정물가 인하보다 60거래일 순방향 S&P500 수익률이 더 높을
      것이다 — 물가가 식고 있으면 연준이 계속 완화할 여지가 커지기 때문.
  H2: 이 새 CPI축을 기존 침체축(NBER USREC, fomc_cpi_cross_study.py가 이미 문서화한
      "침체+물가감속=최악, 비침체+물가감속=최선" 패턴)과 교차한 2x2에서, "비침체+디스인플레이션"
      셀(가장 순수한 호재성 인하)이 4개 셀 중 가장 좋을 것이다. 셀 크기가 작을 수 있다는 걸
      미리 밝혀둔다(이 프로젝트의 다른 2x2 교차들도 셀당 n=7~15 수준이었다).

Part 2: Track G(hike_character_split_study.py) 리포트가 한계로 명시했던 대로, "인플레이션
진압형" 인상 25건 중 2022년 사이클이 큰 비중을 차지해 실질적으로 더 적은 수의 독립 사이클을
25건으로 부풀렸을 수 있다는 우려를 직접 검증한다.

  H3: 2022년 인상 이벤트를 "인플레이션 진압형" 표본에서 통째로 제외하고 H1(원 트랙G 가설)을
      재실행한다. 원래 결과(진압형 +2.00% > 정상긴축 +1.19%, 60거래일 평균)가 2022년
      고유 동학에 의해 만들어진 것이라면, 2022년을 빼면 진압형 평균이 정상긴축 쪽으로
      되돌아가거나 그 아래로 내려가야 한다. 거의 안 바뀐다면 원래 결과가 2022년만의
      우연이 아니라는 증거다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes
from hike_character_split_study import (
    PRIMARY_THRESHOLD, build_cpi_yoy, cpi_yoy_asof, classify_hikes, build_spx_hike_table,
)

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]


def cpi_accel_asof(cpi_accel: pd.Series, event_date: pd.Timestamp):
    """joint_regime/fomc_cpi_cross 스터디와 동일한 정의: 발표시차를 감안해 전월 데이터까지만
    '알려져 있었다'고 본다."""
    ref_month = pd.Timestamp(event_date.year, event_date.month, 1) - pd.DateOffset(months=1)
    avail = cpi_accel[cpi_accel.index <= ref_month]
    if len(avail) == 0 or pd.isna(avail.iloc[-1]):
        return None
    return float(avail.iloc[-1])


def is_recession(recession_monthly: pd.Series, dt: pd.Timestamp) -> bool:
    month_start = pd.Timestamp(dt.year, dt.month, 1)
    nearest = recession_monthly.index[recession_monthly.index <= month_start]
    if len(nearest) == 0:
        return False
    return bool(recession_monthly.loc[nearest[-1]] == 1.0)


def summarize(sub: pd.DataFrame, label: str, horizons=HORIZONS) -> dict:
    if len(sub) == 0:
        print(f"  [{label}] 표본 없음", flush=True)
        return {"n": 0}
    out = {"n": len(sub)}
    for h in horizons:
        col = f"fwd_{h}d_pct"
        if col not in sub.columns:
            continue
        vals = sub[col].dropna()
        if len(vals) == 0:
            continue
        out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
        out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
    print(f"  [{label}] n={out['n']}, +60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%), "
          f"+120일={out.get('fwd_120d_mean_pct')}%(승률{out.get('fwd_120d_win_rate_pct')}%)", flush=True)
    return out


def build_spx_table(dates_with_meta: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
    idx = close.index
    rows = []
    for event_date, row in dates_with_meta.iterrows():
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
            continue
        day0_close = close.iloc[pos]
        fwd = {}
        for h in HORIZONS:
            fut_pos = pos + h
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3) if fut_pos < len(idx) else None
        rows.append({"date": str(event_date.date()), **row.to_dict(), **fwd})
    return pd.DataFrame(rows)


def main():
    print("=== PART 1: 인하의 물가 국면 분류 ===\n", flush=True)
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    cuts_raw = events[events["change_bps"] < 0]
    print(f"전체 인하 이벤트: {len(cuts_raw)}건 ({cuts_raw.index.min().date()} ~ {cuts_raw.index.max().date()})", flush=True)

    cpi = fred_data.get_series("CPIAUCSL", start="1988-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

    recession = fred_data.get_series("USREC", start="1988-01-01")
    recession_monthly = recession.asfreq("MS")

    cuts_meta = cuts_raw.copy()
    cuts_meta["cpi_accel_pp"] = [cpi_accel_asof(cpi_accel, d) for d in cuts_meta.index]
    cuts_meta["recession"] = [is_recession(recession_monthly, d) for d in cuts_meta.index]
    cuts_meta["disinflationary"] = cuts_meta["cpi_accel_pp"].apply(
        lambda v: None if v is None else (v <= 0))

    valid_cuts = cuts_meta.dropna(subset=["cpi_accel_pp"])
    n_disinfl = int(valid_cuts["disinflationary"].sum())
    n_stable = int((~valid_cuts["disinflationary"]).sum())
    print(f"CPI 매칭된 인하: {len(valid_cuts)}/{len(cuts_raw)}건 "
          f"— 디스인플레이션 인하 {n_disinfl}건, 안정물가 인하 {n_stable}건", flush=True)

    spx_hist = get_multiple_price_history(["^GSPC"], start="1989-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]

    df_cuts = build_spx_table(valid_cuts, close)

    print("\n=== H1: 디스인플레이션 인하 vs 안정물가 인하 (S&P500) ===", flush=True)
    s_disinfl = summarize(df_cuts[df_cuts["disinflationary"] == True], "디스인플레이션 인하")
    s_stable = summarize(df_cuts[df_cuts["disinflationary"] == False], "안정물가 인하")

    print("\n=== H2: 침체축 x 물가축 2x2 ===", flush=True)
    s_rec_disinfl = summarize(df_cuts[(df_cuts["recession"] == True) & (df_cuts["disinflationary"] == True)], "침체+디스인플레이션")
    s_rec_stable = summarize(df_cuts[(df_cuts["recession"] == True) & (df_cuts["disinflationary"] == False)], "침체+안정물가")
    s_norec_disinfl = summarize(df_cuts[(df_cuts["recession"] == False) & (df_cuts["disinflationary"] == True)], "비침체+디스인플레이션")
    s_norec_stable = summarize(df_cuts[(df_cuts["recession"] == False) & (df_cuts["disinflationary"] == False)], "비침체+안정물가")

    print("\n\n=== PART 2: 2022년 제외 강건성 체크 (Track G H1 재검증) ===\n", flush=True)
    hikes_raw = events[events["change_bps"] > 0]
    cpi_yoy_full = build_cpi_yoy()
    hikes_classified = classify_hikes(hikes_raw, cpi_yoy_full, PRIMARY_THRESHOLD)
    valid_hikes = hikes_classified.dropna(subset=["character"])
    spx_hike_table = build_spx_hike_table(valid_hikes)

    print("=== 원래 결과 (2022년 포함) ===", flush=True)
    orig_normal = summarize(spx_hike_table[spx_hike_table["character"] == "normal_tightening"], "정상긴축(전체)")
    orig_fighting = summarize(spx_hike_table[spx_hike_table["character"] == "inflation_fighting"], "인플레이션진압(전체, 2022포함)")

    is_2022 = pd.to_datetime(spx_hike_table["date"]).dt.year == 2022
    n_2022_in_fighting = int(((spx_hike_table["character"] == "inflation_fighting") & is_2022).sum())
    print(f"\n2022년에 발생한 '인플레이션 진압형' 인상: {n_2022_in_fighting}건", flush=True)

    fighting_excl_2022 = spx_hike_table[(spx_hike_table["character"] == "inflation_fighting") & (~is_2022)]
    print("\n=== 2022년 제외 후 ===", flush=True)
    s_fighting_excl = summarize(fighting_excl_2022, "인플레이션진압(2022 제외)")
    print(f"\n(비교용) 정상긴축(변동없음): n={orig_normal.get('n')}, +60일={orig_normal.get('fwd_60d_mean_pct')}%", flush=True)

    out = {
        "part1_cuts": {
            "n_total_cuts": len(cuts_raw), "n_cpi_matched": len(valid_cuts),
            "n_disinflationary": n_disinfl, "n_stable": n_stable,
            "h1": {"disinflationary": s_disinfl, "stable": s_stable},
            "h2_2x2": {
                "recession_disinflationary": s_rec_disinfl, "recession_stable": s_rec_stable,
                "norecession_disinflationary": s_norec_disinfl, "norecession_stable": s_norec_stable,
            },
            "events": df_cuts.to_dict(orient="records"),
        },
        "part2_2022_check": {
            "original": {"normal_tightening": orig_normal, "inflation_fighting_all": orig_fighting},
            "n_2022_in_fighting_bucket": n_2022_in_fighting,
            "inflation_fighting_excl_2022": s_fighting_excl,
        },
    }
    with open(f"{OUT_DIR}/cut_character_split_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
