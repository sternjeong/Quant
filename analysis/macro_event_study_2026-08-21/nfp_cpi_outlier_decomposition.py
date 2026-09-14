"""트랙 A 후속의 후속 — NFP×CPI 2x2 교차 스터디(`nfp_cpi_joint_regime_study.py`)에서 발견된
"평균 vs 승률 불일치"를 이상치 분해로 파헤친다.

배경: 그 스터디의 H2에서 "고용가속+물가감속"(최선 후보) 칸이 승률로는 최고(79.7%, n=79)였지만
평균수익률로는 "고용둔화+물가감속"(냉각) 칸(+3.98%)에 밀렸다(+3.55%) — 승률 1등인데 평균은
2등인 이 불일치가 미해명 상태로 남아 다음 과제로 지정됐다.

이 스크립트는 원 스터디의 분류 로직(NFP 모멘텀·CPI 추세 프록시, 이벤트 날짜)을 그대로
재사용해서 새로 유도하지 않는다 — 순수하게 그 스터디가 만든 두 칸(고용가속+물가감속 vs
고용둔화+물가감속)의 +60일 수익률 분포만 다시 뜯어본다.

사전등록 가설 (결과를 보기 전에 여기 기록):
H1: "냉각"(고용둔화+물가감속) 칸의 더 높은 평균은 소수의 큰 양(+)의 이상치가 끌어올린 것이지,
    분포 전체가 고르게 나은 게 아니다 — 즉 각 칸에서 가장 큰 양의 수익률 1건씩만 제거하면
    두 칸의 평균수익률 격차가 "상당히"(사전에 기준을 못박음: 최소 30% 이상) 줄어들어야 한다.
H2: "냉각" 칸의 최대 이상치들이 특정 NBER 침체-회복기(예: 2009, 2020)에 몰려 있다 — "고용둔화+
    물가감속"이라는 라벨이 마침 이미 과매도된 시장이 반등하던 시점과 우연히 겹쳤을 뿐, 그
    라벨 자체가 원인이 아닌 교란요인일 가능성을 NBER 침체 플래그(USREC, 이 프로젝트의 기존
    `cross_asset_recession_split.py`와 동일 방식)로 태깅해 검증한다.
H3: 칸당 상위 2~3개 이상치를 제거한 뒤(표준적인 로버스트니스 기법 — 정확히 몇 개를 제거했는지,
    왜 그 개수인지 명시하고 결론이 뒤집히는 개수를 임의로 고르지 않는다: "상위 1개 제거"와
    "상위 3개 제거" 둘 다 시도해 둘 다 보고한다), 승률 1위("고용가속+물가감속")가 평균수익률
    에서도 1위가 되는지 확인한다. 된다면 원래의 불일치는 이상치 때문이었고 승률이 더 "진짜"
    신호였다는 뜻이고, 안 된다면 이상치와 무관하게 두 칸이 서로 다른 위험/분포 형태를 가진다는
    뜻으로 그 자체로 흥미로운 발견이다 — 어느 쪽이든 있는 그대로 보고한다.
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
    """nfp_cpi_joint_regime_study.py와 동일한 분류 로직 재사용."""
    release_dates = fetch_release_dates(NFP_RELEASE_ID, "1994-01-01")

    payems = fred_data.get_series("PAYEMS", start="1993-01-01")
    mom_change = payems.diff()
    trail3 = mom_change.rolling(3).mean()
    nfp_momentum = trail3.diff(3)

    cpi = fred_data.get_series("CPIAUCSL", start="1993-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

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

    def cpi_accel_asof(release_date):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = cpi_accel[cpi_accel.index <= ref_month]
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
        cpi_acc = cpi_accel_asof(event_date)
        rec = usrec_asof(event_date)
        rows.append({
            "date": date_str,
            "nfp_momentum_k": round(nfp_mom, 1) if nfp_mom is not None else None,
            "cpi_accel_pp": round(cpi_acc, 3) if cpi_acc is not None else None,
            "recession": rec,
            **fwd,
        })

    df = pd.DataFrame(rows)
    return df.dropna(subset=["nfp_momentum_k", "cpi_accel_pp"])


def leave_one_out_max(sub: pd.DataFrame, col: str, k: int):
    """상위 k개(가장 큰 양의 값)를 제거한 뒤 평균 반환."""
    sorted_sub = sub.sort_values(col, ascending=False)
    removed = sorted_sub.head(k)
    kept = sorted_sub.iloc[k:]
    return kept[col].mean(), removed


def main():
    print("데이터 구축 중(원 스터디와 동일 로직)...", flush=True)
    valid = build_valid_df()
    print(f"교차분류 가능 표본: {len(valid)}건", flush=True)

    q_ad = valid[(valid["nfp_momentum_k"] > 0) & (valid["cpi_accel_pp"] <= 0)].copy()  # 고용가속+물가감속
    q_dd = valid[(valid["nfp_momentum_k"] <= 0) & (valid["cpi_accel_pp"] <= 0)].copy()  # 고용둔화+물가감속(냉각)
    print(f"고용가속+물가감속(AD) n={len(q_ad)}, 고용둔화+물가감속(DD, 냉각) n={len(q_dd)}", flush=True)

    col = "fwd_60d_pct"
    orig_ad_mean = round(q_ad[col].mean(), 3)
    orig_dd_mean = round(q_dd[col].mean(), 3)
    orig_ad_win = round(100 * (q_ad[col] > 0).mean(), 1)
    orig_dd_win = round(100 * (q_dd[col] > 0).mean(), 1)
    orig_gap = round(orig_dd_mean - orig_ad_mean, 3)
    print(f"\n원본: AD 평균={orig_ad_mean}%(승률{orig_ad_win}%), DD(냉각) 평균={orig_dd_mean}%(승률{orig_dd_win}%), "
          f"격차(DD-AD)={orig_gap}pp", flush=True)

    # H1: leave-one-out-max (top 1 제거)
    ad_mean_lo1, ad_removed_1 = leave_one_out_max(q_ad, col, 1)
    dd_mean_lo1, dd_removed_1 = leave_one_out_max(q_dd, col, 1)
    gap_lo1 = round(dd_mean_lo1 - ad_mean_lo1, 3)
    gap_shrink_pct = round(100 * (1 - abs(gap_lo1) / abs(orig_gap)), 1) if orig_gap != 0 else None
    print(f"\n[H1: top-1 제거] AD 평균={round(ad_mean_lo1,3)}%, DD 평균={round(dd_mean_lo1,3)}%, "
          f"격차={gap_lo1}pp (원래 대비 {gap_shrink_pct}% 축소)", flush=True)

    # H3: top-1, top-3 제거
    ad_mean_lo3, ad_removed_3 = leave_one_out_max(q_ad, col, 3)
    dd_mean_lo3, dd_removed_3 = leave_one_out_max(q_dd, col, 3)
    gap_lo3 = round(dd_mean_lo3 - ad_mean_lo3, 3)
    print(f"[H3: top-3 제거] AD 평균={round(ad_mean_lo3,3)}%, DD 평균={round(dd_mean_lo3,3)}%, "
          f"격차={gap_lo3}pp", flush=True)

    winner_lo1 = "AD" if ad_mean_lo1 > dd_mean_lo1 else "DD"
    winner_lo3 = "AD" if ad_mean_lo3 > dd_mean_lo3 else "DD"
    print(f"\ntop-1 제거 후 평균 1위: {winner_lo1} / top-3 제거 후 평균 1위: {winner_lo3}", flush=True)

    # H2: 이상치의 침체(회복기) 여부
    dd_top5 = q_dd.sort_values(col, ascending=False).head(5)
    ad_top5 = q_ad.sort_values(col, ascending=False).head(5)
    print("\n[냉각(DD) 칸 상위 5개 이상치]", flush=True)
    for _, r in dd_top5.iterrows():
        print(f"  {r['date']}: +60일={r[col]}%, 당시 침체(USREC 전월 기준)={r['recession']}", flush=True)
    print("\n[고용가속+물가감속(AD) 칸 상위 5개 이상치]", flush=True)
    for _, r in ad_top5.iterrows():
        print(f"  {r['date']}: +60일={r[col]}%, 당시 침체(USREC 전월 기준)={r['recession']}", flush=True)

    n_dd_top5_recession = int(dd_top5["recession"].sum())
    n_ad_top5_recession = int(ad_top5["recession"].sum())

    out = {
        "n_ad": len(q_ad), "n_dd": len(q_dd),
        "orig_ad_mean": orig_ad_mean, "orig_dd_mean": orig_dd_mean,
        "orig_ad_win": orig_ad_win, "orig_dd_win": orig_dd_win, "orig_gap": orig_gap,
        "h1_top1": {
            "ad_mean": round(ad_mean_lo1, 3), "dd_mean": round(dd_mean_lo1, 3),
            "gap": gap_lo1, "gap_shrink_pct": gap_shrink_pct,
        },
        "h3_top3": {
            "ad_mean": round(ad_mean_lo3, 3), "dd_mean": round(dd_mean_lo3, 3), "gap": gap_lo3,
        },
        "winner_lo1": winner_lo1, "winner_lo3": winner_lo3,
        "dd_top5_outliers": dd_top5[["date", col, "recession"]].to_dict("records"),
        "ad_top5_outliers": ad_top5[["date", col, "recession"]].to_dict("records"),
        "n_dd_top5_recession": n_dd_top5_recession, "n_ad_top5_recession": n_ad_top5_recession,
        "dd_removed_top1": dd_removed_1[["date", col]].to_dict("records"),
        "ad_removed_top1": ad_removed_1[["date", col]].to_dict("records"),
        "dd_removed_top3": dd_removed_3[["date", col]].to_dict("records"),
        "ad_removed_top3": ad_removed_3[["date", col]].to_dict("records"),
    }
    with open(f"{OUT_DIR}/nfp_cpi_outlier_decomposition.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
