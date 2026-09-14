"""트랙 F&times;H 후속의 후속: crisis_signal_overlap_study.py의 H2에서 나온 가장 인상적인
숫자 — "크레딧 스프레드도 같이 스트레스 상태였던 VIX&ge;30 급등"(n=12)은 +120일 평균
&minus;5.66%(승률25%)로, 크레딧이 평온했던 급등(n=23, +10.65%/승률86%)과 극명하게
갈렸다 — 이게 정말 "크레딧 스프레드"라는 새 정보인지, 아니면 이 프로젝트가 이미 네 번
(트랙A 침체+디스인플레이션 인하, 트랙B 충격사건, 트랙F VIX&ge;50, 트랙H 크레딧스프레드)
독립적으로 확인한 "침체(NBER) 여부"라는 기존 교란요인의 재탕일 뿐인지 확인한다.

기존 정의를 전부 그대로 재사용한다 — VIX&ge;30(직전 20거래일 미만 후 첫 돌파), 크레딧
스트레스(BAA10Y 직전3년 90퍼센타일 10거래일 지속형), USREC(NBER 공식 침체 판정, cross_asset_
recession_split.py와 동일한 월별 정렬 로직). 새 임계값은 만들지 않는다.

사전등록 가설(결과를 보기 전에 적어둔다):
  H1: "크레딧확인" 12건 중 대부분이 NBER 침체 기간에 발생했을 것이다. 사전 확정 기준:
      12건 중 70% 이상이 침체중이면 "침체 교란요인의 재포장에 가깝다", 50% 미만이면 "진짜
      독립적인 정보다", 50~70%는 "애매함/부분 중첩"으로 보고한다.
  H2: 침체 여부를 통제한 뒤에도 "크레딧확인" 여부가 여전히 결과를 가르는지 확인한다 — 침체중
      VIX급등만 놓고 봤을 때도 크레딧확인 급등이 더 나쁜지, 비침체중 VIX급등만 놓고 봤을 때도
      같은 패턴이 나오는지 따로 본다. 셀 크기가 매우 작을 것으로 예상되며(원래 n=35 표본을
      3중으로 쪼개는 것이므로), n<4인 셀은 통계치 대신 개별 사례 목록으로만 보고한다.
  H3(탐색적): 크레딧확인 12건 전체를 침체 여부와 함께 표로 그대로 공개한다 — H1·H2의 결론
      뒤에 있는 원재료를 독자가 직접 볼 수 있게 한다."""
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
CREDIT_ROLLING_WINDOW = 756
CREDIT_PERCENTILE = 0.90
CREDIT_MIN_PERSIST = 10


def detect_high_spike_events(series: pd.Series, threshold: float, lookback: int):
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
    state = above.astype(int)
    n = len(state)
    filtered = pd.Series(0, index=state.index)
    i = 1
    cursor_state = state.iloc[0]
    filtered.iloc[0] = cursor_state
    while i < n:
        cur_state = state.iloc[i]
        if cur_state != cursor_state:
            window = state.iloc[i:i + min_persist]
            if len(window) == min_persist and (window == cur_state).all():
                cursor_state = cur_state
        filtered.iloc[i] = cursor_state
        i += 1
    return filtered.astype(bool)


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
        rows.append({"date": event_date, "date_str": str(idx[pos].date()), **fwd})
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
    print("BAA10Y(크레딧 스프레드) 조회 중...", flush=True)
    baa10y = fred_data.get_series("BAA10Y", start="1990-01-01", use_cache=False).dropna()
    print("USREC(NBER 침체 판정) 조회 중...", flush=True)
    recession = fred_data.get_series("USREC", start="1990-01-01")
    recession_monthly = recession.asfreq("MS")

    print("S&P500(^GSPC) 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1990-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    vix_events = detect_high_spike_events(vix, VIX_THRESHOLD, VIX_LOOKBACK)
    print(f"\nVIX>={VIX_THRESHOLD} 급등 이벤트: {len(vix_events)}건", flush=True)

    rolling_p90 = baa10y.shift(1).rolling(CREDIT_ROLLING_WINDOW).quantile(CREDIT_PERCENTILE)
    valid_from = rolling_p90.first_valid_index()
    above_credit = (baa10y > rolling_p90).reindex(baa10y.index).fillna(False)
    above_credit = above_credit[baa10y.index >= valid_from]
    credit_state = detect_sustained_state(above_credit, CREDIT_MIN_PERSIST)

    def credit_state_asof(d: pd.Timestamp) -> bool:
        avail = credit_state[credit_state.index <= d]
        return bool(avail.iloc[-1]) if len(avail) else False

    def is_recession(dt: pd.Timestamp) -> bool:
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        nearest = recession_monthly.index[recession_monthly.index <= month_start]
        if len(nearest) == 0:
            return False
        return bool(recession_monthly.loc[nearest[-1]] == 1.0)

    tag_rows = []
    for d in vix_events:
        tag_rows.append({
            "date": d, "date_str": str(d.date()), "vix": round(float(vix.loc[d]), 1),
            "credit_confirmed": credit_state_asof(d), "recession": is_recession(d),
        })
    tag_df = pd.DataFrame(tag_rows)

    credit_confirmed = tag_df[tag_df["credit_confirmed"]]
    n_cc = len(credit_confirmed)
    n_cc_rec = int(credit_confirmed["recession"].sum())
    pct_cc_rec = round(100 * n_cc_rec / n_cc, 1) if n_cc else None
    print(f"\n=== H1: 크레딧확인 {n_cc}건 중 침체중 비율 ===", flush=True)
    print(f"침체중: {n_cc_rec}/{n_cc}건 ({pct_cc_rec}%)", flush=True)
    if pct_cc_rec is not None:
        if pct_cc_rec >= 70:
            h1_verdict = "침체 교란요인의 재포장에 가까움(>=70%)"
        elif pct_cc_rec < 50:
            h1_verdict = "진짜 독립적인 정보(<50%)"
        else:
            h1_verdict = "애매함/부분 중첩(50~70%)"
        print(f"H1 판정: {h1_verdict}", flush=True)
    else:
        h1_verdict = None

    print("\n=== H2: 침체 여부로 통제한 뒤 크레딧확인 축 재검증 ===", flush=True)

    def fwd_and_summarize(sub_df: pd.DataFrame, label: str):
        dates = list(sub_df["date"])
        fwd = build_rows(dates, close, idx).drop(columns=["date_str"])
        merged = sub_df.merge(fwd, on="date", how="left")
        if len(merged) < 4:
            print(f"[{label}] n={len(merged)} < 4 — 통계 대신 개별 사례", flush=True)
            for _, r in merged.iterrows():
                print(f"    {r['date_str']}  " + "  ".join(
                    f"+{h}일={r.get(f'fwd_{h}d_pct')}%" for h in HORIZONS), flush=True)
            return {"n": len(merged), "individual_cases": merged.to_dict(orient="records")}
        return summarize(merged, label)

    rec_cc = tag_df[(tag_df["recession"]) & (tag_df["credit_confirmed"])]
    rec_nocc = tag_df[(tag_df["recession"]) & (~tag_df["credit_confirmed"])]
    norec_cc = tag_df[(~tag_df["recession"]) & (tag_df["credit_confirmed"])]
    norec_nocc = tag_df[(~tag_df["recession"]) & (~tag_df["credit_confirmed"])]

    print("\n[침체중 x 크레딧확인]"); s_rec_cc = fwd_and_summarize(rec_cc, "침체중 x 크레딧확인")
    print("\n[침체중 x 크레딧비확인]"); s_rec_nocc = fwd_and_summarize(rec_nocc, "침체중 x 크레딧비확인")
    print("\n[비침체중 x 크레딧확인]"); s_norec_cc = fwd_and_summarize(norec_cc, "비침체중 x 크레딧확인")
    print("\n[비침체중 x 크레딧비확인]"); s_norec_nocc = fwd_and_summarize(norec_nocc, "비침체중 x 크레딧비확인")

    print("\n=== H3: 크레딧확인 12건 전체 개별 사례(탐색적) ===", flush=True)
    cc_fwd = build_rows(list(credit_confirmed["date"]), close, idx).drop(columns=["date_str"])
    cc_full = credit_confirmed.merge(cc_fwd, on="date", how="left")
    for _, r in cc_full.iterrows():
        print(f"  {r['date_str']}  VIX={r['vix']}  침체중={r['recession']}  "
              + "  ".join(f"+{h}일={r.get(f'fwd_{h}d_pct')}%" for h in HORIZONS), flush=True)

    out_json = {
        "n_vix_events": len(vix_events),
        "h1": {"n_credit_confirmed": n_cc, "n_recession_among_cc": n_cc_rec,
               "pct_recession_among_cc": pct_cc_rec, "verdict": h1_verdict},
        "h2": {
            "recession_x_credit_confirmed": s_rec_cc,
            "recession_x_credit_not_confirmed": s_rec_nocc,
            "norecession_x_credit_confirmed": s_norec_cc,
            "norecession_x_credit_not_confirmed": s_norec_nocc,
        },
        "h3_full_cases": cc_full.drop(columns=["date"]).to_dict(orient="records"),
    }
    with open(f"{OUT_DIR}/credit_confirmed_vix_recession_check.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
