"""트랙 F: VIX(공포지수) 급등 이벤트 스터디 — "공포에 사라(VIX 급등=매수 신호)"라는 유명한
격언을 검증한다. VIX(CBOE Volatility Index)는 S&P500 옵션의 내재변동성으로 만든 지수로,
시장이 앞으로 얼마나 출렁일지에 대한 "공포 온도계"다. 값이 높을수록 투자자들이 불안해한다는
뜻이다.

FRED의 일별 VIX 종가(VIXCLS, 1990년부터)를 사용한다. VIX는 장단기 금리차처럼 천천히 움직이는
지표가 아니라 하루이틀 만에 급등락하는 스파이키한 지표라서, "임계값을 넘은 날"을 그대로 이벤트로
잡으면 같은 급등 국면 안에서 여러 번 중복 카운트된다(예: 2008년 10월 한 달에 VIX가 40을 수십
번 오르내림). 그래서 이 스터디는 "직전 20거래일 동안 계속 임계값 아래에 있다가 처음으로 그
임계값을 뚫고 올라온 날"만 하나의 "급등 이벤트"로 센다 — 이 규칙은 결과를 보기 전에 미리
정한 것이다.

임계값은 사후에 데이터에 맞춰 고른 게 아니라, 시장에서 흔히 회자되는 라운드 넘버 세 개
(VIX 30 / 40 / 50)를 사전에 그대로 쓴다. 30은 "공포 국면 진입"으로 흔히 불리고, 40은
"패닉급", 50은 2008/2020 같은 극단적 위기에서만 본 수준이다.

이 프로젝트의 다른 트랙들(연준 인하의 침체중/보험성 구분, 샴의 법칙의 leading/coincident
구분)에서 반복적으로 확인된 교훈 — "사건이 얼마나 무서워 보였는가"보다 "그 위기가 실제로
어떻게 해소됐는가"가 더 중요하다 — 이 VIX 급등에도 적용되는지, NBER 공식 침체 판정(USREC)으로
나눠서 확인한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
THRESHOLDS = [30, 40, 50]
LOOKBACK_BELOW = 20  # 직전 20거래일 동안 임계값 아래에 있어야 "새 급등"으로 인정


def detect_spike_events(vix: pd.Series, threshold: float, lookback: int = LOOKBACK_BELOW):
    """직전 lookback거래일 동안 계속 threshold 미만이었다가 처음으로 threshold를 넘은 날을
    이벤트로 잡는다. 이벤트 발생 후에는 다시 threshold 아래로 내려가 lookback일을 채울 때까지
    새 이벤트를 세지 않는다(같은 급등 국면 내 재상승 중복 방지)."""
    above = vix >= threshold
    events = []
    n = len(vix)
    i = lookback
    armed = True  # 처음엔 데이터 시작부터 lookback일을 "아래에 있었다"고 간주하지 않음 -> 아래서 체크
    while i < n:
        if armed and above.iloc[i] and not above.iloc[i - lookback:i].any():
            events.append(vix.index[i])
            armed = False
        if not above.iloc[i]:
            # threshold 아래로 내려온 뒤 lookback일 연속 아래 유지되면 재무장
            if not armed:
                window = above.iloc[max(0, i - lookback + 1):i + 1]
                if len(window) == lookback and not window.any():
                    armed = True
        i += 1
    return events


def main():
    print("VIX(VIXCLS) 조회 중...", flush=True)
    vix = fred_data.get_series("VIXCLS", start="1990-01-01").dropna()
    print(f"VIX 데이터: {vix.index.min().date()} ~ {vix.index.max().date()}, {len(vix)}개", flush=True)

    fallback_used = False
    if len(vix) < 100:
        fallback_used = True
        print("VIXCLS 데이터가 부족함 -> Yahoo Finance ^VIX로 대체", flush=True)
        vix_hist = get_multiple_price_history(["^VIX"], start="1990-01-01", end="2026-08-20", interval="1d")["^VIX"]
        vix = vix_hist["Close"].dropna()

    print("S&P500(^GSPC) 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1990-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index
    print(f"S&P500 데이터: {idx.min().date()} ~ {idx.max().date()}, {len(idx)}개", flush=True)

    print("USREC(NBER 침체 판정) 조회 중...", flush=True)
    recession = fred_data.get_series("USREC", start="1988-01-01")
    recession_monthly = recession.asfreq("MS")

    def is_recession(dt: pd.Timestamp) -> bool:
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        nearest = recession_monthly.index[recession_monthly.index <= month_start]
        if len(nearest) == 0:
            return False
        return bool(recession_monthly.loc[nearest[-1]] == 1.0)

    def build_rows(dates, threshold):
        rows = []
        for event_date in dates:
            pos = idx.searchsorted(event_date)
            if pos <= 0 or pos >= len(idx):
                continue
            # 정확히 같은 날 거래일이 없으면 다음 거래일 사용
            aligned_date = idx[pos] if idx[pos] != event_date else event_date
            day0_close = close.iloc[pos]
            vix_val = float(vix.loc[event_date]) if event_date in vix.index else None
            fwd = {}
            for h in HORIZONS:
                fut_pos = pos + h
                if fut_pos < len(idx):
                    fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3)
                else:
                    fwd[f"fwd_{h}d_pct"] = None
            rows.append({
                "date": str(idx[pos].date()),
                "vix": round(vix_val, 1) if vix_val is not None else None,
                "recession": is_recession(idx[pos]),
                "threshold": threshold,
                **fwd,
            })
        return pd.DataFrame(rows)

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

    all_results = {}
    for th in THRESHOLDS:
        print(f"\n=== VIX >= {th} 급등 이벤트 탐지 ===", flush=True)
        events = detect_spike_events(vix, th)
        print(f"급등 이벤트: {len(events)}건", flush=True)
        for d in events:
            print(f"  {d.date()}  VIX={vix.loc[d]:.1f}", flush=True)
        df = build_rows(events, th)
        s_all = summarize(df, f"VIX>={th} 전체")
        s_rec = summarize(df[df["recession"]], f"VIX>={th} 침체중") if len(df) else {}
        s_norec = summarize(df[~df["recession"]], f"VIX>={th} 비침체") if len(df) else {}
        all_results[str(th)] = {
            "events": df.to_dict(orient="records"),
            "summary_all": s_all,
            "summary_recession": s_rec,
            "summary_norecession": s_norec,
        }

    out_json = {
        "fallback_to_yahoo_vix": fallback_used,
        "vix_range": [str(vix.index.min().date()), str(vix.index.max().date())],
        "spx_range": [str(idx.min().date()), str(idx.max().date())],
        "lookback_below_days": LOOKBACK_BELOW,
        "thresholds": THRESHOLDS,
        "horizons": HORIZONS,
        "results": all_results,
    }
    with open(f"{OUT_DIR}/vix_spike_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
