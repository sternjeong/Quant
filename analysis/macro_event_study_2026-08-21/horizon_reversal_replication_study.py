"""트랙 F×H 후속 — "장기엔 단조적으로 나빠지고, 단기엔 오히려 반전된다"는 호라이즌-반전
패턴이 다른 게이지 조합에서도 재현되는지 검증한다.

four_gauge_dashboard_study.py(네 개 위기 게이지: VIX·장단기 금리역전·크레딧스프레드·TED)의
"다음 후보"에 명시적으로 남겨진 과제다 — 그 스터디는 게이지 개수(0~4개)가 늘수록 +60·120일은
계단식으로 나빠지는데(0개 +9.27%→1개 +7.44%→2개 +3.40%→3개 &minus;0.68%), +5·20일은 오히려
게이지가 많을수록 승률이 높아지는 정반대 패턴을 보였다. 하지만 이건 그 스터디가 쓴 "네 게이지
조합" 하나에서만 관찰된 것이라 일반적인 현상인지 확인이 안 됐다.

이번엔 완전히 다른, 더 단순한 2-게이지 조합으로 재현을 시도한다: VIX&ge;30(주식 변동성, 빠르게
움직이는 지표)과 NBER 공식 침체 판정(USREC, 원래 4개 게이지 중 하나가 아니라 "경제가 실제로
안 좋은가"를 보는 근본적으로 다른 비(非)시장 기반 신호). VIX&ge;30 급등 이벤트를 침체중/비침체로
나눠(vix_spike_event_study.py의 탐지 로직·cross_asset_recession_split.py의 USREC 태깅 방식을
그대로 재사용), 침체중 그룹이 같은 호라이즌-반전 모양(장기엔 더 나쁘지만 단기엔 꼭 더 나쁘진
않음)을 보이는지 확인한다.

사전등록 가설(결과를 보기 전에 적어둔다):
  H1: VIX&ge;30 급등을 침체중/비침체로 나누면, 원래 네 게이지 대시보드와 같은 "장기엔 단조적으로
      나빠지지만 단기엔 반전"되는 모양이 침체중 그룹에서 나타날 것이다. 구체적 예측: VIX 자체가
      원래 빠르게 반등하는 성질(트랙F 원 스터디)이 있으므로, 침체중 VIX 급등이라도 단기(+5·20일)
      에는 제법 괜찮은 반등을 보이다가, 장기(+60·120일)에서 침체의 근본적인 경제 부진이 다시
      드러나며 비침체 그룹보다 나빠질 것으로 예상한다.
  H2(탐색적, 강한 사전 확신 없음): H1이 재현된다면, 이 호라이즌-반전 모양이 원래 4게이지 조합에
      국한된 우연이 아니라 "VIX처럼 빠르게 평균회귀하는 신호"와 "침체·크레딧스트레스처럼 느리게
      움직이는 확인신호"를 겹칠 때 나타나는 더 일반적인 특징일 수 있다는 이론적 해석을 시도한다.
      메커니즘을 엄밀히 검증한 건 아니므로 잠정적으로만 서술한다.
  H3(표본크기 사전점검): 침체중 VIX&ge;30 이벤트(원래 n=35의 부분집합)는 표본이 작을 가능성이
      높다 — n<8이면 통계적 결론이 아니라 방향성 참고로만 보고하고, "재현됨(REPLICATED)" 대신
      "방향 일치/불일치"라는 표현을 쓴다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history
from vix_spike_event_study import detect_spike_events, LOOKBACK_BELOW

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
VIX_THRESHOLD = 30
MIN_N_FOR_STATS = 8  # H3: 이 밑이면 "방향성 참고"로만 보고


def main():
    print("VIX(VIXCLS) 조회 중...", flush=True)
    vix = fred_data.get_series("VIXCLS", start="1990-01-01").dropna()
    print(f"VIX 데이터: {vix.index.min().date()} ~ {vix.index.max().date()}, {len(vix)}개", flush=True)

    print("S&P500(^GSPC) 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1990-01-01", end="2026-09-04", interval="1d")["^GSPC"]
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

    print(f"\n=== VIX >= {VIX_THRESHOLD} 급등 이벤트 탐지(vix_spike_event_study.py 로직 재사용) ===", flush=True)
    events = detect_spike_events(vix, VIX_THRESHOLD, LOOKBACK_BELOW)
    print(f"급등 이벤트: {len(events)}건", flush=True)

    rows = []
    for event_date in events:
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx):
            continue
        aligned_date = idx[pos]
        day0_close = close.iloc[pos]
        vix_val = float(vix.loc[event_date]) if event_date in vix.index else None
        rec = is_recession(aligned_date)
        fwd = {}
        for h in HORIZONS:
            fut_pos = pos + h
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3) if fut_pos < len(idx) else None
        rows.append({"date": str(aligned_date.date()), "vix": round(vix_val, 1) if vix_val is not None else None,
                      "recession": rec, **fwd})
        print(f"  {aligned_date.date()}  VIX={vix_val:.1f}  {'침체중' if rec else '비침체'}", flush=True)

    df = pd.DataFrame(rows)

    def summarize(sub: pd.DataFrame, label: str) -> dict:
        if len(sub) == 0:
            print(f"[{label}] 표본 없음", flush=True)
            return {"n": 0}
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

    print("\n=== 전체/침체중/비침체 요약 ===", flush=True)
    s_all = summarize(df, "VIX>=30 전체")
    s_rec = summarize(df[df["recession"]], "VIX>=30 침체중")
    s_norec = summarize(df[~df["recession"]], "VIX>=30 비침체")

    n_rec = int(df["recession"].sum())
    n_norec = int((~df["recession"]).sum())
    small_n = n_rec < MIN_N_FOR_STATS
    print(f"\nH3 표본크기 점검: 침체중 n={n_rec} (기준 n<{MIN_N_FOR_STATS} -> {'소표본, 방향성 참고만' if small_n else '통계적 언급 가능'})", flush=True)

    # H1 판정: 침체중이 장기(+60/120)에는 비침체보다 나쁘고, 단기(+5/20)는 "꼭 더 나쁘진 않음"(반전 여지)
    def get(s, h, key):
        return s.get(f"fwd_{h}d_{key}")

    long_worse = all(
        (get(s_rec, h, "mean_pct") is not None and get(s_norec, h, "mean_pct") is not None
         and get(s_rec, h, "mean_pct") < get(s_norec, h, "mean_pct"))
        for h in [60, 120]
    )
    short_not_worse = any(
        (get(s_rec, h, "win_rate_pct") is not None and get(s_norec, h, "win_rate_pct") is not None
         and get(s_rec, h, "win_rate_pct") >= get(s_norec, h, "win_rate_pct"))
        for h in [5, 20]
    )
    h1_directionally_consistent = long_worse and short_not_worse
    print(f"\nH1 방향 체크: 장기(60/120)에 침체중이 더 나쁨={long_worse}, 단기(5/20) 중 최소 하나는 침체중이 안 나쁘거나 더 좋음={short_not_worse}", flush=True)

    out_json = {
        "vix_range": [str(vix.index.min().date()), str(vix.index.max().date())],
        "spx_range": [str(idx.min().date()), str(idx.max().date())],
        "threshold": VIX_THRESHOLD,
        "lookback_below_days": LOOKBACK_BELOW,
        "horizons": HORIZONS,
        "min_n_for_stats": MIN_N_FOR_STATS,
        "n_total": len(df),
        "n_recession": n_rec,
        "n_norecession": n_norec,
        "small_n_recession_cell": small_n,
        "summary_all": s_all,
        "summary_recession": s_rec,
        "summary_norecession": s_norec,
        "h1_directionally_consistent": h1_directionally_consistent,
        "events": df.to_dict(orient="records"),
    }
    with open(f"{OUT_DIR}/horizon_reversal_replication_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
