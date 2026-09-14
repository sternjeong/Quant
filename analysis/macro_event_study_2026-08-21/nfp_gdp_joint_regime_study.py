"""트랙 A 세 번째 교차검증 — CPI×GDP, NFP×CPI에 이어 3대 거시지표(물가·성장·고용)의 마지막
남은 짝인 GDP×NFP를 채운다. "냉각(둘 다 둔화)이 골디락스(둘 다 가속)를 근소하게 이긴다"는
패턴이 이 프로젝트에서 이미 두 번 독립적으로 나왔다 — 이번이 세 번째 재현 시도다.

트리거/배경변수 선택: NFP를 트리거로 고정한다(매월 발표, GDP는 분기당 3번뿐이라 표본이 훨씬
작아짐 — NFP를 트리거로 삼아야 표본을 최대한 확보할 수 있고, 이 프로젝트의 기존 NFP×CPI
스터디와도 같은 축을 맞출 수 있다). GDP는 그 시점에 이미 알려진 가장 최근 성장 추세(가속/감속)를
배경변수로 태깅한다.

분류 로직은 기존 스크립트에서 그대로 재사용한다 — 새로 유도하지 않는다:
- NFP 모멘텀: `nfp_release_event_study.py`와 동일(PAYEMS 3개월 평균 증감의 3개월 전 대비 변화)
- GDP 가속/감속: `gdp_release_event_study.py`와 동일(GDPC1 전년동기비의 전분기 대비 변화)

사전등록 가설 (결과를 보기 전에 여기 기록):
H1 (재현검증): "고용둔화+성장둔화"(이 조합에서의 "냉각" 칸)가 "고용가속+성장가속"(진짜
    "둘 다 좋음" = 골디락스에 해당하는 칸)보다 +60일 평균수익률이 더 높거나 비슷하다 — "냉각이
    골디락스를 이기거나 최소한 대등하다"는 패턴이 완전히 다른 지표 조합에서 세 번째로 독립
    재현되는지 검증한다.
H2 (트리거 vs 배경변수 재확인, 새 주장이 아니라 체크): 이 2x2 안에서 배경변수인 GDP가
    앞선 두 교차검증에서 CPI가 그랬던 것처럼 결과를 지배하는가? 아니면 트리거인 NFP가 더 큰
    역할을 하는가? 사전 예측: GDP는 원 4개 지표 비교에서 가장 큰 단독 격차(승률 79% vs 58%)를
    보였지만, 그 격차는 "GDP가 그날의 뉴스일 때"에 국한된 것으로 이미 확인됐다(joint_regime
    study). 여기서는 GDP가 트리거가 아니라 배경변수이므로, CPI가 두 스터디에서 구조적으로
    지배했던 것과 달리 GDP의 영향력은 더 약할 것으로 예측한다.
H3 (표본 크기 사전 점검): GDP는 분기당 3번만 발표되는 지표라 NFP×CPI 스터디의 칸당 n=79~114
    보다 표본이 작을 수 있다 — 칸당 n<30이면 앞선 두 교차검증보다 신뢰도가 낮은 재현임을
    명시적으로 밝히고, 대등한 확신도로 보고하지 않는다.
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

    # NFP 모멘텀 (nfp_release_event_study.py와 동일 로직)
    payems = fred_data.get_series("PAYEMS", start="1993-01-01")
    mom_change = payems.diff()
    trail3 = mom_change.rolling(3).mean()
    nfp_momentum = trail3.diff(3)

    # GDP 가속/감속 (gdp_release_event_study.py와 동일 로직)
    gdp = fred_data.get_series("GDPC1", start="1992-01-01")
    gdp_yoy = gdp.pct_change(4) * 100
    gdp_accel = gdp_yoy.diff(1)

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def nfp_momentum_asof(release_date: pd.Timestamp):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = nfp_momentum[nfp_momentum.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def gdp_accel_asof(release_date: pd.Timestamp):
        # gdp_release_event_study.py와 동일한 룩어헤드 방지 컷오프(발표 시차 감안 1개월 여유)
        avail = gdp_accel[gdp_accel.index < release_date - pd.DateOffset(months=1)]
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
        gdp_acc = gdp_accel_asof(event_date)
        rows.append({
            "date": date_str, "day0_return_pct": day0_ret,
            "nfp_momentum_k": round(nfp_mom, 1) if nfp_mom is not None else None,
            "gdp_accel_pp": round(gdp_acc, 3) if gdp_acc is not None else None,
            **fwd,
        })

    df = pd.DataFrame(rows)
    valid = df.dropna(subset=["nfp_momentum_k", "gdp_accel_pp"])
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

    print("\n=== GDP 단독 축(이번 표본에서 재확인) ===", flush=True)
    s_gdp_accel = summarize(valid[valid["gdp_accel_pp"] > 0], "GDP 가속(전체)")
    s_gdp_decel = summarize(valid[valid["gdp_accel_pp"] <= 0], "GDP 감속(전체)")

    print("\n=== 2x2 교차 국면 (NFP x GDP) ===", flush=True)
    q_aa = valid[(valid["nfp_momentum_k"] > 0) & (valid["gdp_accel_pp"] > 0)]     # 고용가속+성장가속(골디락스형)
    q_ad = valid[(valid["nfp_momentum_k"] > 0) & (valid["gdp_accel_pp"] <= 0)]    # 고용가속+성장둔화
    q_da = valid[(valid["nfp_momentum_k"] <= 0) & (valid["gdp_accel_pp"] > 0)]    # 고용둔화+성장가속
    q_dd = valid[(valid["nfp_momentum_k"] <= 0) & (valid["gdp_accel_pp"] <= 0)]   # 고용둔화+성장둔화(냉각)

    s_aa = summarize(q_aa, "고용가속+성장가속(골디락스형)")
    s_ad = summarize(q_ad, "고용가속+성장둔화")
    s_da = summarize(q_da, "고용둔화+성장가속")
    s_dd = summarize(q_dd, "고용둔화+성장둔화(냉각)")

    # H2 참고: 같은 NFP 상태 안에서 GDP만 바꿀 때 vs 같은 GDP 상태 안에서 NFP만 바꿀 때 얼마나 움직이는가
    gdp_effect_within_nfp_accel = abs((s_aa.get("fwd_60d_mean_pct") or 0) - (s_ad.get("fwd_60d_mean_pct") or 0))
    gdp_effect_within_nfp_decel = abs((s_da.get("fwd_60d_mean_pct") or 0) - (s_dd.get("fwd_60d_mean_pct") or 0))
    nfp_effect_within_gdp_accel = abs((s_aa.get("fwd_60d_mean_pct") or 0) - (s_da.get("fwd_60d_mean_pct") or 0))
    nfp_effect_within_gdp_decel = abs((s_ad.get("fwd_60d_mean_pct") or 0) - (s_dd.get("fwd_60d_mean_pct") or 0))
    print(f"\n[H2 참고] GDP축 효과: NFP가속 내 {round(gdp_effect_within_nfp_accel,3)}pp, "
          f"NFP둔화 내 {round(gdp_effect_within_nfp_decel,3)}pp / NFP축 효과: GDP가속 내 "
          f"{round(nfp_effect_within_gdp_accel,3)}pp, GDP둔화 내 {round(nfp_effect_within_gdp_decel,3)}pp", flush=True)

    out_json = {
        "n_total": len(valid),
        "univariate": {
            "nfp_accel": s_nfp_accel, "nfp_decel": s_nfp_decel,
            "gdp_accel": s_gdp_accel, "gdp_decel": s_gdp_decel,
        },
        "quadrants": {
            "accel_accel_goldilocks": s_aa, "accel_decel": s_ad,
            "decel_accel": s_da, "decel_decel_cooling": s_dd,
        },
        "h2_reference": {
            "gdp_effect_within_nfp_accel": round(gdp_effect_within_nfp_accel, 3),
            "gdp_effect_within_nfp_decel": round(gdp_effect_within_nfp_decel, 3),
            "nfp_effect_within_gdp_accel": round(nfp_effect_within_gdp_accel, 3),
            "nfp_effect_within_gdp_decel": round(nfp_effect_within_gdp_decel, 3),
        },
    }
    with open(f"{OUT_DIR}/nfp_gdp_joint_regime_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
