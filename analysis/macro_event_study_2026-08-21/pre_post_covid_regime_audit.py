"""품질관리 감사 — "2020년 이후 국면"이 이 프로젝트의 다른 조인트/자산군 발견들도 조용히
왜곡하고 있는가?

계기: GDP×NFP 베스트셀 재검증(gdp_nfp_best_cell_verification.py)에서, 그 스터디의 깜짝
1등 셀이 낸 초과수익의 50.05%가 2020-11~2025-11 구간("포스트코로나 국면" — 대규모 재정·통화
부양, 역대급 물가급등 후 진정, AI 랠리로 특징지어지는 시기) 하나에 몰려 있다는 게 발견됐다.
질문: 이 왜곡이 그 스터디만의 문제인가, 아니면 이 프로젝트의 다른 조인트/자산군 발견에도
조용히 섞여 있는가?

이 스크립트는 **새로운 분석을 만드는 게 아니라**, 이미 검증된 4개 발견의 사건별 분류 로직을
그대로 재사용해(원본 스크립트에서 함수/로직을 그대로 가져옴) 2020-01-01을 기준으로 표본을
쪼개서 "핵심 결론이 두 시대 모두에서 같은 방향으로 성립하는가"만 재확인하는 감사(audit)다.

사전 등록 가설(결과를 계산하기 전에 적어둔다, 4개 스터디 전부에 동일 기준 적용):
  H1: 아래 4개 스터디 각각의 핵심 결론이 2020년 이전(pre-2020)과 2020년 이후(2020+) 둘
      다에서 같은 부호/방향으로 성립한다 — 즉 어느 한 시대만의 우연이 아니다. "성립한다"의
      기준은 두 하위표본에서 방향(부호)이 같으면 통과(크기가 달라도 무방)다. 부호가 뒤집히거나
      거의 사라지면 "시대의존적, 유보문구 필요"로 명시적으로 표시한다.
    - 스터디 A(CPI×GDP 조인트, joint_regime_event_study.py): 핵심 결론 = "물가감속(CPI
      decel) 국면이 성장 방향과 무관하게 물가가속 국면보다 60일 승률이 높다"(디스인플레이션
      축이 지배적).
    - 스터디 B(NFP×CPI 조인트, nfp_cpi_joint_regime_study.py): 핵심 결론 = 위와 동일한
      패턴이 NFP를 트리거로 삼아도 재현됨 — "물가감속 국면(고용방향 무관)이 물가가속 국면보다
      60일 승률이 높다."
    - 스터디 C(자산군교차 FOMC, cross_asset_fomc_study.py): 핵심 결론 = "금(GLD)은 인하 후
      60일 반응이 인상 후 반응보다 크고, 둘 다 양(+)이다."
    - 스터디 D(섹터 로테이션, cross_asset_sector_fomc.py): 핵심 결론 = "금융(XLF)은 인하
      후 60일 반응이 평균 마이너스이고 승률도 50% 미만이다(9개 섹터 중 최악)."
  H2(탐색적, 강한 사전 예측 없음): 4개 감사 대상에 걸쳐 2020년 이후 하위표본이 2020년 이전과
      체계적으로 다른 공통 패턴(예: 변동폭이 일관되게 커짐, 특정 방향으로의 쏠림, 유독 높은
      승률)이 있는지 서술적으로만 보고한다 — 억지로 하나의 결론으로 몰아가지 않는다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json
import os

import pandas as pd
import requests
from dotenv import load_dotenv

from core import fred_data
from core.market_data import get_multiple_price_history
from fomc_rate_event_study import build_target_rate_series, detect_rate_changes

load_dotenv()
OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
CUTOFF = pd.Timestamp("2020-01-01")
HORIZONS = [1, 5, 20, 60]
SECTOR_HORIZONS = [5, 20, 60]


def fetch_release_dates(release_id: int, start: str) -> list[str]:
    """joint_regime_event_study.py / nfp_cpi_joint_regime_study.py와 동일한 함수(그대로 재사용)."""
    key = os.getenv("FRED_API_KEY")
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?release_id={release_id}"
        f"&api_key={key}&file_type=json&realtime_start={start}&limit=10000"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return [d["date"] for d in r.json().get("release_dates", [])]


def summarize(sub: pd.DataFrame, col: str) -> dict:
    if len(sub) == 0:
        return {"n": 0}
    vals = sub[col].dropna()
    if len(vals) == 0:
        return {"n": len(sub)}
    return {"n": len(sub), "mean_pct": round(vals.mean(), 3), "win_rate_pct": round(100 * (vals > 0).mean(), 1)}


def split_era(df: pd.DataFrame, date_col: str = "date") -> tuple[pd.DataFrame, pd.DataFrame]:
    dt = pd.to_datetime(df[date_col])
    pre = df[dt < CUTOFF]
    post = df[dt >= CUTOFF]
    return pre, post


# ---------------------------------------------------------------------------
# 스터디 A: CPI×GDP 조인트 (joint_regime_event_study.py 로직 그대로 재사용)
# ---------------------------------------------------------------------------
def rebuild_study_a() -> pd.DataFrame:
    print("[A] CPI×GDP 조인트 이벤트 재구축 중...", flush=True)
    release_dates = fetch_release_dates(10, "1994-01-01")  # CPI release_id=10

    cpi = fred_data.get_series("CPIAUCSL", start="1993-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

    gdp = fred_data.get_series("GDPC1", start="1992-01-01")
    gdp_yoy = gdp.pct_change(4) * 100
    gdp_accel = gdp_yoy.diff(1)
    gdp_known_asof = pd.Series(gdp_accel.values, index=gdp_accel.index + pd.DateOffset(days=45))

    spx_hist = get_multiple_price_history(["^GSPC"], start="1993-06-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def cpi_accel_asof(release_date):
        ref_month = pd.Timestamp(release_date.year, release_date.month, 1) - pd.DateOffset(months=1)
        avail = cpi_accel[cpi_accel.index <= ref_month]
        if len(avail) == 0 or pd.isna(avail.iloc[-1]):
            return None
        return float(avail.iloc[-1])

    def gdp_accel_asof(release_date):
        avail = gdp_known_asof[gdp_known_asof.index <= release_date]
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
        day0_close = close.iloc[pos]
        fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in HORIZONS}
        c_acc = cpi_accel_asof(event_date)
        g_acc = gdp_accel_asof(event_date)
        rows.append({"date": date_str, "cpi_accel_pp": c_acc, "gdp_accel_pp": g_acc, **fwd})

    df = pd.DataFrame(rows).dropna(subset=["cpi_accel_pp", "gdp_accel_pp"])
    print(f"  재구축 완료: {len(df)}건", flush=True)
    return df


# ---------------------------------------------------------------------------
# 스터디 B: NFP×CPI 조인트 (nfp_cpi_joint_regime_study.py 로직 그대로 재사용)
# ---------------------------------------------------------------------------
def rebuild_study_b() -> pd.DataFrame:
    print("[B] NFP×CPI 조인트 이벤트 재구축 중...", flush=True)
    release_dates = fetch_release_dates(50, "1994-01-01")  # NFP release_id=50

    payems = fred_data.get_series("PAYEMS", start="1993-01-01")
    mom_change = payems.diff()
    trail3 = mom_change.rolling(3).mean()
    nfp_momentum = trail3.diff(3)

    cpi = fred_data.get_series("CPIAUCSL", start="1993-01-01")
    cpi_yoy = cpi.pct_change(12) * 100
    cpi_accel = cpi_yoy.diff(3)

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
        rows.append({"date": date_str, "nfp_momentum_k": nfp_mom, "cpi_accel_pp": cpi_acc, **fwd})

    df = pd.DataFrame(rows).dropna(subset=["nfp_momentum_k", "cpi_accel_pp"])
    print(f"  재구축 완료: {len(df)}건", flush=True)
    return df


# ---------------------------------------------------------------------------
# 스터디 C: 자산군교차 FOMC (cross_asset_fomc_study.py 로직 그대로 재사용, GLD만)
# ---------------------------------------------------------------------------
def rebuild_study_c() -> pd.DataFrame:
    print("[C] 자산군교차 FOMC(금) 이벤트 재구축 중...", flush=True)
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    events = events[events.index >= "2005-01-01"]

    hist = get_multiple_price_history(["GLD"], start="2004-06-01", end="2026-08-20", interval="1d")
    close = hist["GLD"]["Close"]
    idx = close.index

    rows = []
    for event_date, row in events.iterrows():
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
            continue
        if pos + max(SECTOR_HORIZONS) >= len(idx):
            continue
        day0_close = close.iloc[pos]
        fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in SECTOR_HORIZONS}
        rows.append({"date": str(event_date.date()), "direction": "hike" if row["change_bps"] > 0 else "cut", **fwd})
    df = pd.DataFrame(rows)
    print(f"  재구축 완료: {len(df)}건 (인상 {int((df['direction']=='hike').sum())}, 인하 {int((df['direction']=='cut').sum())})", flush=True)
    return df


# ---------------------------------------------------------------------------
# 스터디 D: 섹터 로테이션 (cross_asset_sector_fomc.py 로직 그대로 재사용, XLF만)
# ---------------------------------------------------------------------------
def rebuild_study_d() -> pd.DataFrame:
    print("[D] 섹터 로테이션(금융 XLF) 이벤트 재구축 중...", flush=True)
    rate = build_target_rate_series()
    events = detect_rate_changes(rate)
    events = events[events.index >= "2005-01-01"]

    hist = get_multiple_price_history(["XLF"], start="2004-06-01", end="2026-08-20", interval="1d")
    close = hist["XLF"]["Close"]
    idx = close.index

    rows = []
    for event_date, row in events.iterrows():
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx) or idx[pos] != event_date:
            continue
        if pos + max(SECTOR_HORIZONS) >= len(idx):
            continue
        day0_close = close.iloc[pos]
        fwd = {f"fwd_{h}d_pct": round(100 * (close.iloc[pos + h] / day0_close - 1), 3) for h in SECTOR_HORIZONS}
        rows.append({"date": str(event_date.date()), "direction": "hike" if row["change_bps"] > 0 else "cut", **fwd})
    df = pd.DataFrame(rows)
    print(f"  재구축 완료: {len(df)}건 (인상 {int((df['direction']=='hike').sum())}, 인하 {int((df['direction']=='cut').sum())})", flush=True)
    return df


def main():
    out = {}

    # --- A: CPI×GDP ---
    df_a = rebuild_study_a()
    pre_a, post_a = split_era(df_a)
    print("\n=== A 검증: 물가감속(decel) vs 물가가속(accel), +60일 승률, 시대별 ===", flush=True)
    res_a = {}
    for era_label, sub in [("pre2020", pre_a), ("post2020", post_a)]:
        decel = summarize(sub[sub["cpi_accel_pp"] <= 0], "fwd_60d_pct")
        accel = summarize(sub[sub["cpi_accel_pp"] > 0], "fwd_60d_pct")
        print(f"  [{era_label}] 감속 n={decel.get('n')} 승률{decel.get('win_rate_pct')}% / "
              f"가속 n={accel.get('n')} 승률{accel.get('win_rate_pct')}%", flush=True)
        res_a[era_label] = {"decel": decel, "accel": accel}
    out["study_a_cpi_gdp"] = res_a

    # --- B: NFP×CPI ---
    df_b = rebuild_study_b()
    pre_b, post_b = split_era(df_b)
    print("\n=== B 검증: 물가감속(decel) vs 물가가속(accel), +60일 승률, 시대별 ===", flush=True)
    res_b = {}
    for era_label, sub in [("pre2020", pre_b), ("post2020", post_b)]:
        decel = summarize(sub[sub["cpi_accel_pp"] <= 0], "fwd_60d_pct")
        accel = summarize(sub[sub["cpi_accel_pp"] > 0], "fwd_60d_pct")
        print(f"  [{era_label}] 감속 n={decel.get('n')} 승률{decel.get('win_rate_pct')}% / "
              f"가속 n={accel.get('n')} 승률{accel.get('win_rate_pct')}%", flush=True)
        res_b[era_label] = {"decel": decel, "accel": accel}
    out["study_b_nfp_cpi"] = res_b

    # --- C: 금(GLD) 인하 vs 인상 ---
    df_c = rebuild_study_c()
    pre_c, post_c = split_era(df_c)
    print("\n=== C 검증: 금(GLD) 인하 vs 인상, +60일, 시대별 ===", flush=True)
    res_c = {}
    for era_label, sub in [("pre2020", pre_c), ("post2020", post_c)]:
        cut = summarize(sub[sub["direction"] == "cut"], "fwd_60d_pct")
        hike = summarize(sub[sub["direction"] == "hike"], "fwd_60d_pct")
        print(f"  [{era_label}] 인하 n={cut.get('n')} 평균{cut.get('mean_pct')}% / "
              f"인상 n={hike.get('n')} 평균{hike.get('mean_pct')}%", flush=True)
        res_c[era_label] = {"cut": cut, "hike": hike}
    out["study_c_gold_fomc"] = res_c

    # --- D: 금융(XLF) 인하 반응 ---
    df_d = rebuild_study_d()
    pre_d, post_d = split_era(df_d)
    print("\n=== D 검증: 금융(XLF) 인하 후 반응, 시대별 ===", flush=True)
    res_d = {}
    for era_label, sub in [("pre2020", pre_d), ("post2020", post_d)]:
        cut = summarize(sub[sub["direction"] == "cut"], "fwd_60d_pct")
        print(f"  [{era_label}] 인하 n={cut.get('n')} 평균{cut.get('mean_pct')}% 승률{cut.get('win_rate_pct')}%", flush=True)
        res_d[era_label] = {"cut": cut}
    out["study_d_xlf_cuts"] = res_d

    with open(f"{OUT_DIR}/pre_post_covid_regime_audit.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
