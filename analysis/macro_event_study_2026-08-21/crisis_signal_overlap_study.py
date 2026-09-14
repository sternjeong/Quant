"""트랙 F/H 후속: 이 프로젝트가 독립적으로 검증한 세 가지 "위기 게이지" — VIX 급등(트랙F,
빠른 반등), 장단기 금리역전(트랙A확장, 느린 선행신호, 6개월~2년+ 시차), 크레딧 스프레드
스트레스(트랙H, 동행에 가까움, 중앙값 79거래일 시차) — 를 겹쳐보면 단독으로 볼 때와 다른
그림이 나오는지 사전등록 방식으로 검증한다.

세 신호는 전부 이미 이 프로젝트에서 검증이 끝난 기존 정의를 그대로 재사용한다(새 임계값을
만들지 않는다) — VIX&ge;30(직전20거래일 미만 유지 후 첫 돌파, vix_spike_event_study.py),
T10Y2Y<0(10거래일 연속 유지돼야 진짜 역전으로 인정, yield_curve_event_study.py), BAA10Y
스프레드가 직전3년 롤링 90퍼센타일을 넘어섬(10거래일 연속 유지, credit_spread_event_study.py).

사전등록 가설(결과를 보기 전에 적어둔다):
  H1: VIX&ge;30 급등이 "금리역전이 이미 진행 중인 시기"에 벌어지면, "역전이 없는 시기"에
      벌어진 VIX 급등과 순방향 60·120거래일 수익률이 다를 것이다. 방향은 사전에 확정하지
      않는다 — VIX 급등 자체는 빠른 반등을 예고하지만(트랙F), 역전 중이라는 건 침체가
      상대적으로 더 가까울 수 있다는 뜻이라(비록 시차가 길어도) 두 힘이 충돌하는 구간이라
      결과를 미리 단정하지 않고 검증한다. 겹치는 사건 수 자체가 매우 적을 것으로 예상되며
      (역전은 특정 구간에만 지속되고 VIX 급등도 드묾), n<8이면 방향성 참고로만 다룬다.
  H2: 크레딧 스프레드도 함께 스트레스 상태(트랙H의 적응형 90퍼센타일 기준)인 VIX&ge;30 급등은,
      크레딧 스프레드가 평온한 VIX&ge;30 급등보다 +5·+20일 반등이 더 약하고 느릴 것이다(신용
      스트레스는 트랙H에서 빠른 반등 신호가 아니라고 확인됐으므로, "신용시장이 진짜라고
      확인해주는" VIX 급등은 단순 패닉이 아닐 가능성). 다만 +120일까지 가면 VIX 급등의
      장기 반등력(트랙F 후속 H2에서 룩백에 강건하다고 확인됨) 덕분에 격차가 좁혀질 것으로
      예상한다.
  H3(탐색적, 가설 검정 아님): 원래 VIX&ge;30 급등 35건 중 몇 건이 역전 중이었고 몇 건이
      크레딧 스트레스 중이었는지 단순 교차표로 보여준다 — 세 신호가 실제로 얼마나 독립적인지
      (또는 겹치는지) 확인해, 이후 "위기 신호 종합 대시보드"를 만들 때 참고할 기초 자료로
      남긴다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
VIX_THRESHOLD = 30
VIX_LOOKBACK = 20
INV_MIN_PERSIST = 10
CREDIT_ROLLING_WINDOW = 756
CREDIT_PERCENTILE = 0.90
CREDIT_MIN_PERSIST = 10


def detect_high_spike_events(series: pd.Series, threshold: float, lookback: int):
    """직전 lookback거래일 동안 계속 threshold 미만이었다가 처음으로 threshold를 넘은 날을
    이벤트로 잡는다(vix_spike_event_study.py와 동일 로직)."""
    above = series >= threshold
    events = []
    n = len(series)
    armed = True
    i = lookback
    while i < n:
        if armed and above.iloc[i] and not above.iloc[i - lookback:i].any():
            events.append(series.index[i])
            armed = False
        if not above.iloc[i] and not armed:
            window = above.iloc[max(0, i - lookback + 1):i + 1]
            if len(window) == lookback and not window.any():
                armed = True
        i += 1
    return events


def detect_sustained_state(above: pd.Series, min_persist: int):
    """above: bool Series. 상태가 바뀐 뒤 min_persist거래일 연속 유지되면 그 시작일을 진짜
    전환으로 인정한다(yield_curve_event_study.py/credit_spread_event_study.py와 동일 로직).
    반환: (전환 시작일 목록, 전환 종료일 목록, "필터링된 상태" bool Series)."""
    state = above.astype(int)
    n = len(state)
    filtered = pd.Series(0, index=state.index)
    events_on, events_off = [], []
    i = 1
    prev_confirmed_state = state.iloc[0]
    filtered.iloc[0] = prev_confirmed_state
    cursor_state = state.iloc[0]
    while i < n:
        cur_state = state.iloc[i]
        if cur_state != cursor_state:
            window = state.iloc[i:i + min_persist]
            if len(window) == min_persist and (window == cur_state).all():
                (events_on if cur_state == 1 else events_off).append(state.index[i])
                cursor_state = cur_state
        filtered.iloc[i] = cursor_state
        i += 1
    return events_on, events_off, filtered.astype(bool)


def build_rows(dates, close, idx):
    rows = []
    for event_date in dates:
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx):
            continue
        day0_close = close.iloc[pos]
        fwd = {}
        for h in HORIZONS:
            fut_pos = pos + h
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3) if fut_pos < len(idx) else None
        rows.append({"date": str(idx[pos].date()), **fwd})
    return pd.DataFrame(rows)


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


def main():
    print("VIX(VIXCLS) 조회 중...", flush=True)
    vix = fred_data.get_series("VIXCLS", start="1990-01-01").dropna()
    print("T10Y2Y(장단기 금리차) 조회 중...", flush=True)
    spread10y2y = fred_data.get_series("T10Y2Y", start="1990-01-01").dropna()
    print("BAA10Y(크레딧 스프레드) 조회 중...", flush=True)
    baa10y = fred_data.get_series("BAA10Y", start="1990-01-01", use_cache=False).dropna()

    print("S&P500(^GSPC) 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1990-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    # ===== 이벤트/상태 탐지 (기존 스터디의 정의를 그대로 재사용) =====
    vix_events = detect_high_spike_events(vix, VIX_THRESHOLD, VIX_LOOKBACK)
    print(f"\nVIX>={VIX_THRESHOLD} 급등 이벤트: {len(vix_events)}건", flush=True)

    inv_on, inv_off, inv_state = detect_sustained_state(spread10y2y < 0, INV_MIN_PERSIST)
    print(f"금리역전 시작(10거래일 지속형): {len(inv_on)}건, 정상화: {len(inv_off)}건", flush=True)

    rolling_p90 = baa10y.shift(1).rolling(CREDIT_ROLLING_WINDOW).quantile(CREDIT_PERCENTILE)
    valid_from = rolling_p90.first_valid_index()
    above_credit = (baa10y > rolling_p90).reindex(baa10y.index).fillna(False)
    above_credit = above_credit[baa10y.index >= valid_from]
    credit_on, credit_off, credit_state = detect_sustained_state(above_credit, CREDIT_MIN_PERSIST)
    print(f"크레딧 스트레스 시작(90퍼센타일, 10거래일 지속형): {len(credit_on)}건, 해소: {len(credit_off)}건", flush=True)

    def inv_state_asof(d: pd.Timestamp) -> bool:
        avail = inv_state[inv_state.index <= d]
        return bool(avail.iloc[-1]) if len(avail) else False

    def credit_state_asof(d: pd.Timestamp) -> bool:
        avail = credit_state[credit_state.index <= d]
        return bool(avail.iloc[-1]) if len(avail) else False

    # ===== H3: 탐색적 교차표 =====
    print("\n=== H3: VIX>=30 이벤트 35건 중 다른 신호와의 중첩 (탐색적) ===", flush=True)
    tag_rows = []
    for d in vix_events:
        row = {
            "date": str(d.date()), "vix": round(float(vix.loc[d]), 1),
            "inverted": inv_state_asof(d), "credit_stress": credit_state_asof(d),
        }
        tag_rows.append(row)
        print(f"  {row['date']}  VIX={row['vix']}  역전중={row['inverted']}  크레딧스트레스중={row['credit_stress']}", flush=True)
    tag_df = pd.DataFrame(tag_rows)
    n_inv = int(tag_df["inverted"].sum())
    n_credit = int(tag_df["credit_stress"].sum())
    n_both = int((tag_df["inverted"] & tag_df["credit_stress"]).sum())
    print(f"\n요약: 역전중 {n_inv}/{len(tag_df)}건, 크레딧스트레스중 {n_credit}/{len(tag_df)}건, "
          f"둘다 {n_both}/{len(tag_df)}건", flush=True)

    # ===== H1: VIX 급등 x 금리역전 여부 =====
    vix_dates_inv = [d for d in vix_events if inv_state_asof(d)]
    vix_dates_noinv = [d for d in vix_events if not inv_state_asof(d)]
    print(f"\n=== H1: VIX>=30 급등, 역전중 vs 비역전중 ===", flush=True)
    df_inv = build_rows(vix_dates_inv, close, idx)
    df_noinv = build_rows(vix_dates_noinv, close, idx)
    s_h1_inv = summarize(df_inv, "VIX급등 x 역전중")
    s_h1_noinv = summarize(df_noinv, "VIX급등 x 비역전중")

    # ===== H2: VIX 급등 x 크레딧 스트레스 여부 =====
    vix_dates_credit = [d for d in vix_events if credit_state_asof(d)]
    vix_dates_nocredit = [d for d in vix_events if not credit_state_asof(d)]
    print(f"\n=== H2: VIX>=30 급등, 크레딧스트레스중 vs 평온 ===", flush=True)
    df_credit = build_rows(vix_dates_credit, close, idx)
    df_nocredit = build_rows(vix_dates_nocredit, close, idx)
    s_h2_credit = summarize(df_credit, "VIX급등 x 크레딧스트레스중")
    s_h2_nocredit = summarize(df_nocredit, "VIX급등 x 크레딧평온")

    out_json = {
        "vix_threshold": VIX_THRESHOLD, "vix_lookback": VIX_LOOKBACK,
        "n_vix_events": len(vix_events),
        "h3_crosstab": {
            "events": tag_df.to_dict(orient="records"),
            "n_total": len(tag_df), "n_inverted": n_inv, "n_credit_stress": n_credit, "n_both": n_both,
        },
        "h1": {
            "vix_x_inverted": {"n_events": len(vix_dates_inv), "summary": s_h1_inv},
            "vix_x_not_inverted": {"n_events": len(vix_dates_noinv), "summary": s_h1_noinv},
        },
        "h2": {
            "vix_x_credit_stress": {"n_events": len(vix_dates_credit), "summary": s_h2_credit},
            "vix_x_credit_calm": {"n_events": len(vix_dates_nocredit), "summary": s_h2_nocredit},
        },
    }
    with open(f"{OUT_DIR}/crisis_signal_overlap_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
