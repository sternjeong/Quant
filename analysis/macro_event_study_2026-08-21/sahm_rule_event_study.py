"""샴의 법칙(Sahm Rule) 발동 이벤트 스터디 — "실업률이 이만큼 뛰면 이미 침체"라는, 장단기
금리역전과는 정반대 성격(선행지표가 아니라 동행/후행에 가까운 확정형 지표)의 유명한 침체 신호.

샴의 법칙: 실업률 3개월 평균이 최근 12개월 저점보다 0.5%p 이상 오르면 "이미 침체 국면"으로
판정한다 — 이 0.5라는 임계값은 사후에 스윕한 게 아니라 지표 창시자 클라우디아 샴이 정의한
바로 그 표준 임계값이다. FRED가 실시간 버전(SAHMREALTIME)을 직접 계산해서 제공한다.

발동 시점은 실업률 수치 자체가 아니라 "그 수치가 발표된 날"을 이벤트일로 잡는다(같은 프로젝트의
고용지표 스터디와 동일한 FRED release/dates API 사용) — 데이터가 존재하는 달과 시장이 그걸
실제로 알게 되는 날은 다르기 때문."""
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
HORIZONS = [5, 20, 60, 250, 500]
NFP_RELEASE_ID = 50
SAHM_THRESHOLD = 0.5


def fetch_release_dates(release_id: int, start: str) -> list[str]:
    key = os.getenv("FRED_API_KEY")
    url = (
        f"https://api.stlouisfed.org/fred/release/dates?release_id={release_id}"
        f"&api_key={key}&file_type=json&realtime_start={start}&limit=10000"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return sorted(pd.Timestamp(d["date"]) for d in r.json().get("release_dates", []))


def main():
    print("샴의 법칙(SAHMREALTIME) 조회 중...", flush=True)
    sahm = fred_data.get_series("SAHMREALTIME", start="1959-01-01").dropna()
    above = (sahm >= SAHM_THRESHOLD).astype(int)
    changes = above.diff()
    trigger_months = changes[changes == 1].index
    print(f"발동 {len(trigger_months)}건: {[str(d.date()) for d in trigger_months]}", flush=True)

    release_dates = fetch_release_dates(NFP_RELEASE_ID, "1959-01-01")

    def release_date_for_month(month_start: pd.Timestamp):
        # 그 달 실업률 데이터가 실제로 발표된(다음 달 초) 날짜를 찾는다
        candidates = [d for d in release_dates if d.year == month_start.year + (1 if month_start.month == 12 else 0)
                      and d.month == (1 if month_start.month == 12 else month_start.month + 1)]
        return candidates[0] if candidates else None

    spx_hist = get_multiple_price_history(["^GSPC"], start="1959-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    rows = []
    for month_start in trigger_months:
        event_date = release_date_for_month(month_start)
        if event_date is None:
            continue
        pos = idx.searchsorted(event_date)
        if pos >= len(idx) or pos <= 0:
            continue
        if idx[pos] != event_date:
            pass  # 가장 가까운 다음 거래일 사용(주식시장 휴장일 등)
        day0_close = close.iloc[pos]
        fwd = {}
        for h in HORIZONS:
            fut_pos = pos + h
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3) if fut_pos < len(idx) else None
        rows.append({"trigger_month": str(month_start.date()), "release_date": str(idx[pos].date()),
                     "sahm_value": round(float(sahm.loc[month_start]), 2), **fwd})

    df = pd.DataFrame(rows)
    print(f"\n가격 매칭 성공: {len(df)}/{len(trigger_months)}건", flush=True)

    def summarize(sub: pd.DataFrame, label: str) -> dict:
        if len(sub) == 0:
            return {}
        out = {"n": len(sub)}
        for h in HORIZONS:
            col = f"fwd_{h}d_pct"
            vals = sub[col].dropna()
            if len(vals) == 0:
                continue
            out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
            out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
        print(f"[{label}] n={out['n']}", flush=True)
        for h in HORIZONS:
            if f"fwd_{h}d_mean_pct" in out:
                print(f"   +{h}일: {out[f'fwd_{h}d_mean_pct']}% (승률 {out[f'fwd_{h}d_win_rate_pct']}%)", flush=True)
        return out

    print("\n=== 샴의 법칙 발동 이후 S&P500 ===", flush=True)
    s_all = summarize(df, "전체 발동")

    out_json = {"events": df.to_dict(orient="records"), "summary": s_all}
    with open(f"{OUT_DIR}/sahm_rule_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
