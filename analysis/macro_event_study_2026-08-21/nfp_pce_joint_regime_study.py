"""트랙 A 후속: "냉각이 골디락스를 근소하게 이긴다"는 패턴이 CPI×GDP·NFP×CPI 두 번
재현됐다가 GDP×NFP에서 깨진 것("성장×고용" 조합에서는 골디락스가 뚜렷하게 앞섬)을 두고,
"CPI 자체가 특별해서"인지 "인플레이션 감속이라는 개념 자체가 특별해서"인지를 가리는 검증이다.

이 프로젝트는 이미 CPI와 PCE(연준이 실제로 목표로 삼는 물가지표)가 단독 스플릿에서 거의
동일한 숫자를 냈다는 걸 확인했다(pce_release_event_study.py). "인플레이션 감속 개념" 가설이
맞다면, CPI를 PCE로 바꿔도 NFP×CPI 스터디의 패턴(①격차가 커진다 ②냉각이 골디락스와 근소하게
대등하거나 앞선다 ③물가 축이 여전히 교차표를 지배)이 그대로 재현돼야 한다. 반대로 재현되지
않는다면 "CPI 시리즈 자체"에 뭔가 특별한 게 있었다는, 훨씬 설명하기 어려운 결과가 된다.

방법론은 nfp_cpi_joint_regime_study.py와 완전히 동일 — NFP 발표일을 사건(트리거)으로 고정,
그 시점에 이미 알려진 가장 최근 PCE YoY 추세(가속/감속)를 배경변수로 태깅해 2x2로 나눈다.
NFP 모멘텀 분류 로직(nfp_release_event_study.py)과 PCE YoY 가속 로직(pce_release_event_study.py)을
그대로 재사용 — CPI를 PCE로 바꾼 것 외에는 원 스터디와 완전히 동일한 설계라, 결과가 다르다면
그건 방법론 차이가 아니라 지표 자체의 차이라고 말할 수 있다.

사전등록 가설(결과 계산 전 명시):
  H1: PCE×NFP 2x2에서 "고용둔화+물가감속"(냉각)이 "고용가속+물가감속"(골디락스형)보다
      평균수익률이 높거나 대등해야 CPI 기반 패턴이 재현된 것으로 판정한다. CPI와 PCE가
      단독 스플릿에서 거의 동일했다는 걸 감안해, 이 가설은 재현될 것(CONFIRMED/REPLICATED)
      으로 예측한다 — 재현되면 GDP×NFP의 반증은 "CPI 특정성"이 아니라 "성장-고용 조합
      특성"이라는 쪽으로 해석이 강화된다.
  H2: PCE가 교차표 안에서 보이는 배경변수 지배력(같은 NFP 상태 안에서 PCE만 바꿀 때의
      결과 변화)이 CPI가 NFP×CPI 스터디에서 보인 7~13배 압도와 비슷한 규모인지 확인한다 —
      비슷하면 "CPI 고유 현상"이 아니라 "물가지표라면 다 그렇다"는 쪽을 지지한다.
  H3(표본 규모 사전 점검): PCE 발표일도 월간이라 NFP×CPI 스터디(칸당 n=79~114)와 비슷한
      규모가 나올 것으로 예상한다 — 눈에 띄게 작거나 크면 이유를 밝힌다.
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

    # NFP 모멘텀 (nfp_release_event_study.py / nfp_cpi_joint_regime_study.py와 동일 로직)
    payems = fred_data.get_series("PAYEMS", start="1993-01-01")
    mom_change = payems.diff()
    trail3 = mom_change.rolling(3).mean()
    nfp_momentum = trail3.diff(3)

    # PCE 가속/감속 (pce_release_event_study.py와 동일 로직 — CPI 대신 PCE)
    pce = fred_data.get_series("PCEPI", start="1993-01-01")
    pce_yoy = pce.pct_change(12) * 100
    pce_accel = pce_yoy.diff(3)

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def nfp_momentum_asof(release_date: pd.Timestamp):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = nfp_momentum[nfp_momentum.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def pce_accel_asof(release_date: pd.Timestamp):
        # NFP 발표 시점에 "이미 알려진" 가장 최근 PCE 수치 사용(룩어헤드 없음)
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = pce_accel[pce_accel.index <= ref_month]
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
        pce_acc = pce_accel_asof(event_date)
        rows.append({
            "date": date_str, "day0_return_pct": day0_ret,
            "nfp_momentum_k": round(nfp_mom, 1) if nfp_mom is not None else None,
            "pce_accel_pp": round(pce_acc, 3) if pce_acc is not None else None,
            **fwd,
        })

    df = pd.DataFrame(rows)
    valid = df.dropna(subset=["nfp_momentum_k", "pce_accel_pp"])
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

    print("\n=== PCE 단독 축(이번 표본에서 재확인) ===", flush=True)
    s_pce_accel = summarize(valid[valid["pce_accel_pp"] > 0], "PCE 가속(전체)")
    s_pce_decel = summarize(valid[valid["pce_accel_pp"] <= 0], "PCE 감속(전체)")

    print("\n=== 2x2 교차 국면 (NFP x PCE) ===", flush=True)
    q_accel_decel = valid[(valid["nfp_momentum_k"] > 0) & (valid["pce_accel_pp"] <= 0)]   # 고용가속+물가감속(골디락스형)
    q_accel_accel = valid[(valid["nfp_momentum_k"] > 0) & (valid["pce_accel_pp"] > 0)]    # 고용가속+물가가속(과열/모호)
    q_decel_decel = valid[(valid["nfp_momentum_k"] <= 0) & (valid["pce_accel_pp"] <= 0)]  # 고용둔화+물가감속(냉각)
    q_decel_accel = valid[(valid["nfp_momentum_k"] <= 0) & (valid["pce_accel_pp"] > 0)]   # 고용둔화+물가가속(스태그플레이션 우려)

    s_ad = summarize(q_accel_decel, "고용가속+물가감속(골디락스형)")
    s_aa = summarize(q_accel_accel, "고용가속+물가가속(과열/모호)")
    s_dd = summarize(q_decel_decel, "고용둔화+물가감속(냉각)")
    s_da = summarize(q_decel_accel, "고용둔화+물가가속(스태그플레이션 우려)")

    # --- H1 판정 ---
    h1_pass = (s_dd.get("fwd_60d_mean_pct") is not None and s_ad.get("fwd_60d_mean_pct") is not None
               and s_dd["fwd_60d_mean_pct"] >= s_ad["fwd_60d_mean_pct"])
    h1_verdict = "CONFIRMED(REPLICATED)" if h1_pass else "NOT REPLICATED"

    # --- H2: PCE축 vs NFP축 지배력 비교 ---
    # 같은 NFP 상태 안에서 PCE만 바꿀 때 변화량(가속->둔화 각각)
    pce_effect_when_nfp_accel = abs(s_ad["fwd_60d_mean_pct"] - s_aa["fwd_60d_mean_pct"]) if s_ad.get("fwd_60d_mean_pct") is not None and s_aa.get("fwd_60d_mean_pct") is not None else None
    pce_effect_when_nfp_decel = abs(s_dd["fwd_60d_mean_pct"] - s_da["fwd_60d_mean_pct"]) if s_dd.get("fwd_60d_mean_pct") is not None and s_da.get("fwd_60d_mean_pct") is not None else None
    # 같은 PCE 상태 안에서 NFP만 바꿀 때 변화량
    nfp_effect_when_pce_decel = abs(s_ad["fwd_60d_mean_pct"] - s_dd["fwd_60d_mean_pct"]) if s_ad.get("fwd_60d_mean_pct") is not None and s_dd.get("fwd_60d_mean_pct") is not None else None
    nfp_effect_when_pce_accel = abs(s_aa["fwd_60d_mean_pct"] - s_da["fwd_60d_mean_pct"]) if s_aa.get("fwd_60d_mean_pct") is not None and s_da.get("fwd_60d_mean_pct") is not None else None

    ratio_low = None
    ratio_high = None
    if all(v is not None and v > 0 for v in [nfp_effect_when_pce_decel, nfp_effect_when_pce_accel]):
        ratios = [pce_effect_when_nfp_accel / nfp_effect_when_pce_accel, pce_effect_when_nfp_decel / nfp_effect_when_pce_decel]
        ratio_low, ratio_high = round(min(ratios), 2), round(max(ratios), 2)

    print(f"\n=== H2: 배경변수 지배력 비교 ===", flush=True)
    print(f"같은 NFP상태에서 PCE만 바꿀 때 변화: 가속시={pce_effect_when_nfp_accel}, 둔화시={pce_effect_when_nfp_decel}", flush=True)
    print(f"같은 PCE상태에서 NFP만 바꿀 때 변화: 감속시={nfp_effect_when_pce_decel}, 가속시={nfp_effect_when_pce_accel}", flush=True)
    print(f"PCE/NFP 지배력 비율 범위: {ratio_low}~{ratio_high}배 (CPI×NFP 스터디는 7~13배)", flush=True)

    out_json = {
        "n_total": len(valid),
        "univariate": {
            "nfp_accel": s_nfp_accel, "nfp_decel": s_nfp_decel,
            "pce_accel": s_pce_accel, "pce_decel": s_pce_decel,
        },
        "quadrants": {
            "accel_decel": s_ad, "accel_accel": s_aa,
            "decel_decel": s_dd, "decel_accel": s_da,
        },
        "h1_verdict": h1_verdict,
        "h2_dominance_ratio_range": [ratio_low, ratio_high],
    }
    with open(f"{OUT_DIR}/nfp_pce_joint_regime_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
