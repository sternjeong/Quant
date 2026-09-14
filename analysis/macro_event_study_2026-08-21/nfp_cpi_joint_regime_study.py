"""트랙 A 후속: 고용지표(NFP)의 약한 단독 신호가 물가(CPI) 국면과 교차하면 선명해지는지
사전등록 방식으로 검증한다.

배경: `nfp_release_event_study.py`에서 NFP 가속/둔화는 거의 갈리지 않았다(+60일 가속
+1.81%/승률68% vs 둔화 +2.66%/승률70%, 격차 0.85%p) — "고용은 좋아도 나빠도 이중적으로
읽히는 지표"라는 설명이었다(강한 고용=경기 좋음이지만 동시에 "연준이 더 오래 긴축"이라는
뜻도 됨). 반면 `joint_regime_event_study.py`(CPI×GDP)는 두 축을 합쳐도 선명해지지 않았지만,
`fomc_cpi_cross_study.py`(연준인하×침체×CPI)는 오히려 선명해졌다 — 이 프로젝트에서 "두 축을
합치면 선명해지는가"는 매번 다르게 나온 열린 질문이다.

이 스크립트는 NFP 발표일을 사건(트리거)으로 고정하고, 그 시점에 이미 알려진 가장 최근 CPI
추세(가속/감속)를 배경변수로 태깅해 2x2로 나눈다. NFP를 트리거로 고정한 이유: "그날의 뉴스"가
곧 NFP 발표이므로(CPI는 그 시점의 배경 국면일 뿐, 그날 새로 발표되는 게 아님) — 이 프로젝트가
이미 확인한 "이벤트 트리거 vs 배경변수는 다른 질문"이라는 교훈을 그대로 적용한다."""
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
NFP_RELEASE_ID = 50  # Employment Situation


def fetch_release_dates(release_id: int, start: str) -> list[str]:
    key = os.getenv("FRED_API_KEY")
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?release_id={release_id}"
        f"&api_key={key}&file_type=json&realtime_start={start}&limit=10000"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return [d["date"] for d in r.json().get("release_dates", [])]


def main():
    print("고용지표(NFP) 발표일 조회 중...", flush=True)
    release_dates = fetch_release_dates(NFP_RELEASE_ID, "1994-01-01")
    print(f"발표일 {len(release_dates)}건 ({release_dates[0]} ~ {release_dates[-1]})", flush=True)

    # NFP 모멘텀 (nfp_release_event_study.py와 동일 로직)
    payems = fred_data.get_series("PAYEMS", start="1993-01-01")
    mom_change = payems.diff()
    trail3 = mom_change.rolling(3).mean()
    nfp_momentum = trail3.diff(3)

    # CPI 가속/감속 (joint_regime_event_study.py와 동일 로직)
    cpi = fred_data.get_series("CPIAUCSL", start="1993-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def nfp_momentum_asof(release_date: pd.Timestamp):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = nfp_momentum[nfp_momentum.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def cpi_accel_asof(release_date: pd.Timestamp):
        # NFP 발표 시점에 "이미 알려진" 가장 최근 CPI 수치 사용(룩어헤드 없음)
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = cpi_accel[cpi_accel.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    rows = []
    for date_str in release_dates:
        event_date = pd.Timestamp(date_str)
        if event_date not in idx:
            continue
        pos = idx.get_loc(event_date)
        if pos < 1 or pos + max(HORIZONS) >= len(idx):
            continue

        prior_close = close.iloc[pos - 1]
        day0_close = close.iloc[pos]
        day0_ret = round(100 * (day0_close / prior_close - 1), 3)
        fwd = {}
        for h in HORIZONS:
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[pos + h] / day0_close - 1), 3)

        nfp_mom = nfp_momentum_asof(event_date)
        cpi_acc = cpi_accel_asof(event_date)
        rows.append({
            "date": date_str, "day0_return_pct": day0_ret,
            "nfp_momentum_k": round(nfp_mom, 1) if nfp_mom is not None else None,
            "cpi_accel_pp": round(cpi_acc, 3) if cpi_acc is not None else None,
            **fwd,
        })

    df = pd.DataFrame(rows)
    valid = df.dropna(subset=["nfp_momentum_k", "cpi_accel_pp"])
    print(f"\n교차분류 가능 표본: {len(valid)}/{len(df)}건", flush=True)

    def summarize(sub: pd.DataFrame, label: str) -> dict:
        if len(sub) == 0:
            print(f"[{label}] 표본 없음", flush=True)
            return {}
        out = {"n": len(sub), "day0_mean_pct": round(sub["day0_return_pct"].mean(), 3)}
        for h in HORIZONS:
            col = f"fwd_{h}d_pct"
            out[f"fwd_{h}d_mean_pct"] = round(sub[col].dropna().mean(), 3)
            out[f"fwd_{h}d_win_rate_pct"] = round(100 * (sub[col].dropna() > 0).mean(), 1)
        print(f"[{label}] n={out['n']}, +20일={out.get('fwd_20d_mean_pct')}%(승률{out.get('fwd_20d_win_rate_pct')}%), "
              f"+60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%)", flush=True)
        return out

    print("\n=== NFP 단독 축(이번 표본에서 재확인) ===", flush=True)
    s_nfp_accel = summarize(valid[valid["nfp_momentum_k"] > 0], "NFP 가속(전체)")
    s_nfp_decel = summarize(valid[valid["nfp_momentum_k"] <= 0], "NFP 둔화(전체)")

    print("\n=== CPI 단독 축(이번 표본에서 재확인) ===", flush=True)
    s_cpi_accel = summarize(valid[valid["cpi_accel_pp"] > 0], "CPI 가속(전체)")
    s_cpi_decel = summarize(valid[valid["cpi_accel_pp"] <= 0], "CPI 감속(전체)")

    print("\n=== 2x2 교차 국면 (NFP x CPI) ===", flush=True)
    q_accel_decel = valid[(valid["nfp_momentum_k"] > 0) & (valid["cpi_accel_pp"] <= 0)]   # 고용가속+물가감속(최선 후보)
    q_accel_accel = valid[(valid["nfp_momentum_k"] > 0) & (valid["cpi_accel_pp"] > 0)]    # 고용가속+물가가속(과열/모호)
    q_decel_decel = valid[(valid["nfp_momentum_k"] <= 0) & (valid["cpi_accel_pp"] <= 0)]  # 고용둔화+물가감속(냉각)
    q_decel_accel = valid[(valid["nfp_momentum_k"] <= 0) & (valid["cpi_accel_pp"] > 0)]   # 고용둔화+물가가속(스태그플레이션 우려)

    s_ad = summarize(q_accel_decel, "고용가속+물가감속(최선 후보)")
    s_aa = summarize(q_accel_accel, "고용가속+물가가속(과열/모호)")
    s_dd = summarize(q_decel_decel, "고용둔화+물가감속(냉각)")
    s_da = summarize(q_decel_accel, "고용둔화+물가가속(스태그플레이션 우려)")

    out_json = {
        "n_total": len(valid),
        "univariate": {
            "nfp_accel": s_nfp_accel, "nfp_decel": s_nfp_decel,
            "cpi_accel": s_cpi_accel, "cpi_decel": s_cpi_decel,
        },
        "quadrants": {
            "accel_decel": s_ad, "accel_accel": s_aa,
            "decel_decel": s_dd, "decel_accel": s_da,
        },
    }
    with open(f"{OUT_DIR}/nfp_cpi_joint_regime_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
