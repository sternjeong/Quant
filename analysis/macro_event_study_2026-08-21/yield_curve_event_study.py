"""장단기 금리역전(10년-2년 국채금리차, T10Y2Y) 이벤트 스터디 — "경기침체 예고 신호"로 널리
알려진 지표를 실제로 검증한다. 1976년부터 50년치 일별 데이터로 이 프로젝트에서 가장 긴 표본.

역전 시작/해소 시점을 그냥 "부호가 바뀐 날"로 잡으면 0 근처에서 며칠 단위로 수십 번 플리커링
하는 노이즈에 오염된다(1981~82, 1988~90, 1998, 2006, 2024 등에서 확인됨). 그래서 "최소 10거래일
이상 지속된" 진짜 역전/정상화만 이벤트로 잡는다 — 그 지속 구간의 첫날을 이벤트 날짜로 쓴다.

역전은 통상 "1~2년 뒤 침체 예고"로 알려져 있으므로, 짧은 호라이즌(+5·+20일)뿐 아니라 훨씬 긴
호라이즌(+250거래일=약 1년, +500거래일=약 2년)까지 같이 본다 — 지금까지 이 프로젝트가 쓴 60일
호라이즌으로는 이 지표의 진짜 예고력을 볼 수 없다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 250, 500]
MIN_PERSIST_DAYS = 10


def detect_sustained_crossings(spread: pd.Series, min_persist: int = MIN_PERSIST_DAYS):
    sign = (spread < 0).astype(int)  # 1=역전, 0=정상
    inversions, normalizations = [], []
    i = 0
    n = len(sign)
    prev_state = sign.iloc[0]
    while i < n:
        cur_state = sign.iloc[i]
        if cur_state != prev_state:
            # 이 시점부터 min_persist일간 상태가 유지되는지 확인
            window = sign.iloc[i:i + min_persist]
            if len(window) == min_persist and (window == cur_state).all():
                event_date = sign.index[i]
                if cur_state == 1:
                    inversions.append(event_date)
                else:
                    normalizations.append(event_date)
                prev_state = cur_state
        i += 1
    return inversions, normalizations


def main():
    print("장단기 금리차(T10Y2Y) 조회 중...", flush=True)
    spread = fred_data.get_series("T10Y2Y", start="1976-01-01").dropna()
    inversions, normalizations = detect_sustained_crossings(spread)
    print(f"지속형 역전 시작: {len(inversions)}건, 정상화(역전 해소): {len(normalizations)}건", flush=True)
    for d in inversions:
        print("  역전 시작:", d.date())
    for d in normalizations:
        print("  정상화:", d.date())

    spx_hist = get_multiple_price_history(["^GSPC"], start="1975-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    def build_rows(dates):
        rows = []
        for event_date in dates:
            pos = idx.searchsorted(event_date)
            if pos >= len(idx) or idx[pos] != event_date:
                # 국채시장 휴장일과 주식시장 휴장일이 다를 수 있어 가장 가까운 다음 거래일 사용
                pos = idx.searchsorted(event_date)
            if pos <= 0 or pos >= len(idx):
                continue
            day0_close = close.iloc[pos]
            fwd = {}
            for h in HORIZONS:
                fut_pos = pos + h
                if fut_pos < len(idx):
                    fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3)
                else:
                    fwd[f"fwd_{h}d_pct"] = None
            rows.append({"date": str(idx[pos].date()), **fwd})
        return pd.DataFrame(rows)

    df_inv = build_rows(inversions)
    df_norm = build_rows(normalizations)

    def summarize(sub: pd.DataFrame, label: str) -> dict:
        if len(sub) == 0:
            print(f"[{label}] 표본 없음", flush=True)
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

    print("\n=== 역전 시작 이후 S&P500 ===", flush=True)
    s_inv = summarize(df_inv, "역전 시작")
    print("\n=== 정상화(역전 해소) 이후 S&P500 ===", flush=True)
    s_norm = summarize(df_norm, "정상화")

    out_json = {
        "inversion_dates": [str(d.date()) for d in inversions],
        "normalization_dates": [str(d.date()) for d in normalizations],
        "inversion_events": df_inv.to_dict(orient="records"),
        "normalization_events": df_norm.to_dict(orient="records"),
        "summary": {"inversion": s_inv, "normalization": s_norm},
    }
    with open(f"{OUT_DIR}/yield_curve_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
