"""트랙 F 후속: VIX 급등 스터디(vix_spike_event_study.py)에서 예고했던 두 가지 후속 검증을
사전등록(pre-registration) 방식으로 수행한다 — 결과를 보기 전에 가설과 임계값을 먼저 못박는다.

H1 (안일함/거울상 검증): "VIX 급등 후엔 반등한다"의 정반대, 즉 VIX가 극단적으로 낮을 때
(시장이 너무 안일해져 있을 때)는 그 뒤 S&P500 수익률이 평균보다 나쁠 것이라는 가설. 주 임계값은
VIX≤13(흔히 회자되는 "극단적 안일함" 수준), 보조/강건성 확인용으로 VIX≤15도 같이 본다. 이벤트
탐지 규칙은 원래 스터디를 거울상으로 뒤집는다 — "직전 20거래일 동안 계속 임계값 위에 있다가
처음으로 그 임계값 아래로 내려온 날".

H2 (이벤트 탐지 민감도 검증): 원래 스터디는 "직전 20거래일 미만 유지 후 첫 돌파"라는 룩백
윈도우를 하나만 썼고 민감도 검증을 하지 않았다. 이번엔 같은 VIX≥30/40/50 임계값을 10거래일·
30거래일 룩백으로도 다시 돌려, "문턱이 높을수록 반등도 강하다"는 원래 결론이 룩백 선택에
흔들리는지 확인한다. 이건 새로운 주장이 아니라 기존 주장이 버티는지 확인하는 재현성 점검이다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
LOW_THRESHOLDS = [13, 15]
HIGH_THRESHOLDS = [30, 40, 50]
LOOKBACK_WINDOWS = [10, 20, 30]
ORIGINAL_LOOKBACK = 20


def detect_high_spike_events(vix: pd.Series, threshold: float, lookback: int):
    """직전 lookback거래일 동안 계속 threshold 미만이었다가 처음으로 threshold를 넘은 날을
    이벤트로 잡는다(원래 스터디와 동일 로직)."""
    above = vix >= threshold
    events = []
    n = len(vix)
    armed = True
    i = lookback
    while i < n:
        if armed and above.iloc[i] and not above.iloc[i - lookback:i].any():
            events.append(vix.index[i])
            armed = False
        if not above.iloc[i] and not armed:
            window = above.iloc[max(0, i - lookback + 1):i + 1]
            if len(window) == lookback and not window.any():
                armed = True
        i += 1
    return events


def detect_low_calm_events(vix: pd.Series, threshold: float, lookback: int = ORIGINAL_LOOKBACK):
    """거울상 규칙: 직전 lookback거래일 동안 계속 threshold 초과였다가 처음으로 threshold
    이하로 내려온 날을 "안일함 진입" 이벤트로 잡는다."""
    below = vix <= threshold
    events = []
    n = len(vix)
    armed = True
    i = lookback
    while i < n:
        if armed and below.iloc[i] and not below.iloc[i - lookback:i].any():
            events.append(vix.index[i])
            armed = False
        if not below.iloc[i] and not armed:
            window = below.iloc[max(0, i - lookback + 1):i + 1]
            if len(window) == lookback and not window.any():
                armed = True
        i += 1
    return events


def build_rows(dates, close, idx, vix):
    rows = []
    for event_date in dates:
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx):
            continue
        day0_close = close.iloc[pos]
        vix_val = float(vix.loc[event_date]) if event_date in vix.index else None
        fwd = {}
        for h in HORIZONS:
            fut_pos = pos + h
            if fut_pos < len(idx):
                fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3)
            else:
                fwd[f"fwd_{h}d_pct"] = None
        rows.append({"date": str(idx[pos].date()), "vix": round(vix_val, 1) if vix_val is not None else None, **fwd})
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


def main():
    print("VIX(VIXCLS) 조회 중...", flush=True)
    vix = fred_data.get_series("VIXCLS", start="1990-01-01").dropna()

    fallback_used = False
    if len(vix) < 100:
        fallback_used = True
        vix_hist = get_multiple_price_history(["^VIX"], start="1990-01-01", end="2026-08-20", interval="1d")["^VIX"]
        vix = vix_hist["Close"].dropna()

    print("S&P500(^GSPC) 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1990-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    # ===== H1: 안일함(저VIX) 이벤트 =====
    print("\n===== H1: 저VIX(안일함) 이벤트 =====", flush=True)
    h1_results = {}
    for th in LOW_THRESHOLDS:
        events = detect_low_calm_events(vix, th)
        print(f"\nVIX<= {th} 진입 이벤트: {len(events)}건", flush=True)
        for d in events:
            print(f"  {d.date()}  VIX={vix.loc[d]:.1f}", flush=True)
        df = build_rows(events, close, idx, vix)
        s = summarize(df, f"VIX<={th}")
        h1_results[str(th)] = {"events": df.to_dict(orient="records"), "summary": s}

    # ===== H2: 룩백 윈도우 민감도 =====
    print("\n===== H2: 룩백 윈도우 민감도(10/20/30거래일) =====", flush=True)
    h2_results = {}
    for lookback in LOOKBACK_WINDOWS:
        h2_results[str(lookback)] = {}
        for th in HIGH_THRESHOLDS:
            events = detect_high_spike_events(vix, th, lookback)
            df = build_rows(events, close, idx, vix)
            s = summarize(df, f"lookback={lookback}, VIX>={th}")
            h2_results[str(lookback)][str(th)] = {"n_events": len(events), "summary": s}

    out_json = {
        "fallback_to_yahoo_vix": fallback_used,
        "vix_range": [str(vix.index.min().date()), str(vix.index.max().date())],
        "horizons": HORIZONS,
        "h1_low_thresholds": LOW_THRESHOLDS,
        "h1_results": h1_results,
        "h2_lookback_windows": LOOKBACK_WINDOWS,
        "h2_high_thresholds": HIGH_THRESHOLDS,
        "h2_results": h2_results,
    }
    with open(f"{OUT_DIR}/vix_complacency_and_sensitivity_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
