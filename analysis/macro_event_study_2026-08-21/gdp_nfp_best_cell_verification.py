"""GDP×NFP 교차검증(`nfp_gdp_joint_regime_study.py`)에서 발견된 예상 밖 1위 칸 &mdash;
"고용둔화+성장가속"(+60일 평균 +4.51%, 승률 81.7%, n=82) &mdash; 이 우연/이상치/특정 시기
쏠림 때문이 아니라 진짜 신뢰할 만한 패턴인지 검증한다. 원 스터디가 스스로 "다음 과제"로
남긴 후속 검증이며, 메타요약 캡스톤의 "냉각=CPI 특유" 재해석이 이 발견 하나에 기대고 있어
검증이 중요하다.

이벤트 분류·날짜는 `nfp_gdp_joint_regime_study.py`를 그대로 재사용한다(새로 유도하지 않음) —
이건 그 스터디 자체 데이터의 재분석이지 새로운 독립 검증이 아니다.

사전등록 가설 (결과를 보기 전에 여기 기록):
H1 (시기 쏠림 점검): "고용둔화+성장가속" 칸의 강한 성과가 특정 한 시기(하나의 확장국면이나
    한 시대)에 집중된 게 아니라 여러 경기 사이클에 걸쳐 분산돼 있다. 기준을 사전에 못박는다:
    이 칸의 "초과수익"(전체 무조건부 평균 대비)의 50% 이상이 단일 5년 구간 안의 이벤트에서
    나온다면 "시기에 쏠린 결과"로 간주하고 일반 패턴으로서 신뢰도를 크게 낮춘다.
H2 (이상치 점검, `nfp_cpi_outlier_decomposition.py`의 방법을 그대로 재사용): 이 칸에서 상위
    1~3개 이상치를 제거하면 다른 3개 칸 대비 순위가 바뀌는가? 1~3개만 제거해도 1위 자리를
    잃는다면 원래 발견이 이상치에 의존한 것이라는 증거다.
H3 (경제적 스토리 점검, 엄격한 가설이 아니라 탐색): "고용은 둔화되는데 성장은 가속"이 말이
    되는 국면인가, 아니면 통계적으로는 나타나지만 경제적으로는 앞뒤가 안 맞는 조합인가?
    침체 직후 GDP는 기저효과로 빠르게 반등하는데 고용은 뒤늦게 따라오는 "고용 없는 회복
    (jobless recovery)" 현상일 가능성을 `cross_asset_recession_split.py`와 같은 방식으로
    USREC 태깅해 확인한다 &mdash; 만약 이 칸의 이벤트 상당수가 침체 인근에 몰려 있다면,
    이건 요행이 아니라 설명 가능한 진짜 패턴이라는 뜻이다.
"""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import os

import pandas as pd
import requests
from dotenv import load_dotenv

from core import fred_data
from core.market_data import get_multiple_price_history

load_dotenv()
OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [1, 5, 20, 60]
NFP_RELEASE_ID = 50


def fetch_release_dates(release_id: int, start: str) -> list[str]:
    key = os.getenv("FRED_API_KEY")
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?release_id={release_id}"
        f"&api_key={key}&file_type=json&realtime_start={start}&limit=10000"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return [d["date"] for d in r.json().get("release_dates", [])]


def build_valid_df():
    """nfp_gdp_joint_regime_study.py와 동일한 분류 로직 재사용."""
    release_dates = fetch_release_dates(NFP_RELEASE_ID, "1994-01-01")

    payems = fred_data.get_series("PAYEMS", start="1993-01-01")
    mom_change = payems.diff()
    trail3 = mom_change.rolling(3).mean()
    nfp_momentum = trail3.diff(3)

    gdp = fred_data.get_series("GDPC1", start="1992-01-01")
    gdp_yoy = gdp.pct_change(4) * 100
    gdp_accel = gdp_yoy.diff(1)

    usrec = fred_data.get_series("USREC", start="1993-01-01")

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def nfp_momentum_asof(release_date):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = nfp_momentum[nfp_momentum.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def gdp_accel_asof(release_date):
        avail = gdp_accel[gdp_accel.index < release_date - pd.DateOffset(months=1)]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def usrec_asof(release_date):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = usrec[usrec.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return bool(avail.iloc[-1] > 0)

    rows = []
    for date_str in release_dates:
        event_date = pd.Timestamp(date_str)
        if event_date not in idx:
            continue
        pos = idx.get_loc(event_date)
        if pos < 1 or pos + max(HORIZONS) >= len(idx):
            continue

        day0_close = close.iloc[pos]
        fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in HORIZONS}

        nfp_mom = nfp_momentum_asof(event_date)
        gdp_acc = gdp_accel_asof(event_date)
        rec = usrec_asof(event_date)
        rows.append({
            "date": date_str,
            "nfp_momentum_k": round(nfp_mom, 1) if nfp_mom is not None else None,
            "gdp_accel_pp": round(gdp_acc, 3) if gdp_acc is not None else None,
            "recession": rec,
            **fwd,
        })

    df = pd.DataFrame(rows)
    return df.dropna(subset=["nfp_momentum_k", "gdp_accel_pp"])


def leave_one_out_max(sub: pd.DataFrame, col: str, k: int):
    sorted_sub = sub.sort_values(col, ascending=False)
    removed = sorted_sub.head(k)
    kept = sorted_sub.iloc[k:]
    return kept[col].mean(), removed


def main():
    print("데이터 구축 중(원 스터디와 동일 로직)...", flush=True)
    valid = build_valid_df()
    print(f"교차분류 가능 표본: {len(valid)}건", flush=True)

    col = "fwd_60d_pct"
    baseline_mean = valid[col].mean()
    print(f"전체 무조건부 평균(+60일) = {round(baseline_mean, 3)}%", flush=True)

    q_aa = valid[(valid["nfp_momentum_k"] > 0) & (valid["gdp_accel_pp"] > 0)]    # 고용가속+성장가속
    q_ad = valid[(valid["nfp_momentum_k"] > 0) & (valid["gdp_accel_pp"] <= 0)]   # 고용가속+성장둔화
    q_da = valid[(valid["nfp_momentum_k"] <= 0) & (valid["gdp_accel_pp"] > 0)].copy()  # 고용둔화+성장가속(대상 칸)
    q_dd = valid[(valid["nfp_momentum_k"] <= 0) & (valid["gdp_accel_pp"] <= 0)]  # 고용둔화+성장둔화(냉각)

    cells = {"aa_goldilocks": q_aa, "ad": q_ad, "da_target": q_da, "dd_cooling": q_dd}
    for name, sub in cells.items():
        print(f"[{name}] n={len(sub)}, +60일 평균={round(sub[col].mean(),3)}%, "
              f"승률={round(100*(sub[col]>0).mean(),1)}%", flush=True)

    # H1: 시기 쏠림 - 대상 칸의 초과수익(무조건부 평균 대비)이 특정 5년 구간에 몰려있는가
    q_da["excess"] = q_da[col] - baseline_mean
    q_da["dt"] = pd.to_datetime(q_da["date"])
    total_excess = q_da["excess"].sum()
    print(f"\n[H1] 대상 칸 총 초과수익 합계 = {round(total_excess, 3)}", flush=True)

    best_window_share = 0.0
    best_window = None
    dates_sorted = q_da["dt"].sort_values().tolist()
    for start_date in dates_sorted:
        end_date = start_date + pd.DateOffset(years=5)
        window_sub = q_da[(q_da["dt"] >= start_date) & (q_da["dt"] < end_date)]
        window_excess = window_sub["excess"].sum()
        share = (window_excess / total_excess) if total_excess != 0 else 0
        if share > best_window_share:
            best_window_share = share
            best_window = (str(start_date.date()), str(end_date.date()), len(window_sub))
    print(f"[H1] 초과수익이 가장 많이 몰린 5년 구간: {best_window}, 비중={round(100*best_window_share,1)}%", flush=True)

    # 연도별 분포도 같이 출력(참고)
    q_da["year"] = q_da["dt"].dt.year
    yearly = q_da.groupby("year")[col].agg(["count", "mean"]).round(2)
    print("\n[H1 참고] 연도별 이벤트 수·평균 +60일 수익률:", flush=True)
    print(yearly.to_string(), flush=True)

    # H2: 이상치 제거 후 순위 재확인
    da_mean_lo1, da_removed_1 = leave_one_out_max(q_da, col, 1)
    da_mean_lo3, da_removed_3 = leave_one_out_max(q_da, col, 3)
    other_means = {name: round(sub[col].mean(), 3) for name, sub in cells.items() if name != "da_target"}
    print(f"\n[H2] top-1 제거 후 대상 칸 평균={round(da_mean_lo1,3)}%, top-3 제거 후={round(da_mean_lo3,3)}%", flush=True)
    print(f"[H2] 비교 대상(원본 유지) 다른 3칸 평균: {other_means}", flush=True)
    rank_after_lo1 = "1위 유지" if da_mean_lo1 > max(other_means.values()) else "1위 상실"
    rank_after_lo3 = "1위 유지" if da_mean_lo3 > max(other_means.values()) else "1위 상실"
    print(f"[H2] top-1 제거 후 순위: {rank_after_lo1} / top-3 제거 후 순위: {rank_after_lo3}", flush=True)

    # H3: 침체 인근 여부
    n_recession = int(q_da["recession"].sum())
    n_total = len(q_da)
    print(f"\n[H3] 대상 칸 중 발표 시점(전월 기준) 침체중이었던 비율: {n_recession}/{n_total} "
          f"({round(100*n_recession/n_total,1)}%)", flush=True)

    # 침체 종료 후 사후 회복기(침체 종료 후 24개월 이내)까지 포함해 재확인
    usrec = fred_data.get_series("USREC", start="1993-01-01")
    recession_end_dates = []
    prev = 0
    for dt, val in usrec.items():
        if prev == 1 and val == 0:
            recession_end_dates.append(dt)
        prev = val
    def near_recession_recovery(event_date_str, window_months=24):
        d = pd.Timestamp(event_date_str)
        for end_dt in recession_end_dates:
            if end_dt <= d < end_dt + pd.DateOffset(months=window_months):
                return True
        return False
    q_da["near_recovery"] = q_da["date"].apply(near_recession_recovery)
    n_recovery = int(q_da["near_recovery"].sum())
    print(f"[H3] 침체중이거나 침체 종료 후 24개월 이내(회복기)인 비율: "
          f"{n_recession + n_recovery - int((q_da['recession'] & q_da['near_recovery']).sum())}/{n_total}", flush=True)

    top_events = q_da.sort_values(col, ascending=False).head(10)[["date", col, "recession", "near_recovery"]]
    print("\n[대상 칸 상위 10개 이벤트]", flush=True)
    print(top_events.to_string(), flush=True)

    out = {
        "n_total": len(valid), "baseline_mean_60d": round(baseline_mean, 3),
        "cells": {name: {"n": len(sub), "mean_60d": round(sub[col].mean(), 3),
                          "win_rate": round(100 * (sub[col] > 0).mean(), 1)} for name, sub in cells.items()},
        "h1": {
            "total_excess": round(total_excess, 3),
            "best_5yr_window": best_window, "best_window_share_pct": round(100 * best_window_share, 1),
            "yearly": yearly.reset_index().to_dict("records"),
        },
        "h2": {
            "top1_removed_mean": round(da_mean_lo1, 3), "top3_removed_mean": round(da_mean_lo3, 3),
            "other_cell_means": other_means, "rank_after_top1": rank_after_lo1, "rank_after_top3": rank_after_lo3,
            "removed_top1": da_removed_1[["date", col]].to_dict("records"),
            "removed_top3": da_removed_3[["date", col]].to_dict("records"),
        },
        "h3": {
            "n_recession": n_recession, "n_total": n_total,
            "pct_recession": round(100 * n_recession / n_total, 1),
            "top10_events": top_events.to_dict("records"),
        },
    }
    with open(f"{OUT_DIR}/gdp_nfp_best_cell_verification.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
