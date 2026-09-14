"""트랙 H 네 번째 위기 게이지: 은행간 단기자금 조달 스트레스(TED 스프레드) 이벤트 스터디.

지금까지 이 프로젝트는 VIX(주식 옵션 변동성, 빠른 반등 신호)·장단기 금리역전(금리 기대, 느린
선행신호)·BAA10Y 크레딧 스프레드(회사채-국채, 동행신호이자 "공포에 사라"가 안 통하는 신호)를
검증했다. 이번엔 네 번째 독립 정보원 — 은행들이 서로에게 단기자금을 빌려줄 때 요구하는 금리
(LIBOR)가 "무위험" 단기 국채금리보다 얼마나 높은지(TED 스프레드, Treasury-EuroDollar) —를
추가한다. 이건 "은행 시스템 내부가 서로를 얼마나 못 믿는가"를 재는 지표로, 주식 변동성(VIX)·
회사채 신용(BAA10Y)과는 또 다른 각도다 — 2008년 리먼 사태 때 이 스프레드가 사상 최고치로
치솟은 이유가 바로 "어느 은행이 다음에 무너질지 아무도 몰라서 은행들끼리도 서로 돈을 안
빌려줬기 때문"이다.

**데이터 출처 관련 메모(사전 확인)**: FRED TEDRATE는 LIBOR 산정 방식 자체가 2022년 이후
단계적으로 폐지되면서 2022-01-21을 마지막으로 더 이상 갱신되지 않는다. 대안으로 SOFR 기반
스프레드를 직접 만들 수도 있지만 SOFR 역사가 2018년부터로 너무 짧고, FRED의 EPU(경제정책
불확실성 지수, WLEMUINDXD)는 은행 시스템과 무관한 다른 성격의 지표라 이번 목적엔 맞지 않는다.
그래서 **TEDRATE를 그대로 쓰되, 2022-01-21까지만 유효한 지표라는 걸 명시적으로 밝히고 그
이후(2022년 긴축 사이클, 2023년 지역은행 위기, 2025년 관세 충격)는 이 지표로 볼 수 없다는
한계로 리포트에 그대로 공개한다** — 1986~2022년 사이엔 2008 금융위기·2011 유럽위기·2020
코로나 등 이 프로젝트가 다뤄온 주요 위기를 대부분 담고 있어 검증 목적엔 충분하다.

사전등록 가설(결과를 보기 전에 적어둔다):
  H1: 은행간 자금조달 스트레스(TED 스프레드가 직전3년 90퍼센타일 초과, 크레딧 스프레드
      스터디와 동일한 적응형 기준)가 벌어진 뒤 S&P500의 순방향 수익률은, VIX 급등의 패턴
      (강한 역발상 반등)보다는 크레딧 스프레드 스터디의 패턴(동행에 가까움, "공포에 사라"가
      안 통함)에 더 가까울 것이다 — 자금조달 스트레스와 신용 스트레스는 둘 다 "은행/신용
      시스템"을 재는 지표라 경제적으로 더 가깝기 때문이다.
  H2: 이 새 지표(TED)의 스트레스 이벤트를 기존에 이미 확정한 VIX&ge;30 이벤트·BAA10Y
      크레딧스트레스 이벤트와 교차해, 얼마나 겹치는지 확인한다 — 겹침이 낮으면 진짜 "네 번째
      독립 신호"이고, 높으면 기존 신호의 재탕에 가깝다는 뜻이다.
  H3(탐색적): TED 스트레스 이벤트를 NBER 침체(USREC) 여부로 나눠, 이 프로젝트에서 이미 4번
      (트랙A·B·F·H) 독립 확인된 "사건의 무서움보다 실제 시스템 붕괴 여부가 중요하다" 패턴이
      다섯 번째로도 재현되는지 확인한다(재현되면 5번째, 표본이 작으면 방향성 참고로만)."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
TED_ROLLING_WINDOW = 756  # 약 3년(거래일), 크레딧 스프레드 스터디와 동일
TED_PERCENTILE = 0.90
TED_MIN_PERSIST = 10
TED_LAST_VALID_DATE = "2022-01-21"  # LIBOR 폐지로 이후 데이터 없음

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


def detect_sustained_crossings(above: pd.Series, min_persist: int):
    """above: bool Series. 상태가 바뀐 뒤 min_persist거래일 연속 유지되면 그 시작일을 이벤트로
    잡는다(yield_curve_event_study.py/credit_spread_event_study.py와 동일 로직)."""
    state = above.astype(int)
    events_on, events_off = [], []
    n = len(state)
    i = 1
    prev_state = state.iloc[0]
    while i < n:
        cur_state = state.iloc[i]
        if cur_state != prev_state:
            window = state.iloc[i:i + min_persist]
            if len(window) == min_persist and (window == cur_state).all():
                event_date = state.index[i]
                (events_on if cur_state == 1 else events_off).append(event_date)
                prev_state = cur_state
        i += 1
    return events_on, events_off


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


def baseline_forward_returns(close: pd.Series) -> dict:
    out = {"n": len(close.index)}
    for h in HORIZONS:
        fwd = 100 * (close.shift(-h) / close - 1)
        vals = fwd.dropna()
        out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
        out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
    return out


def main():
    print("TEDRATE(TED 스프레드) 조회 중...", flush=True)
    ted = fred_data.get_series("TEDRATE", start="1986-01-01", use_cache=False).dropna()
    print(f"TED 데이터: {len(ted)}건 ({ted.index.min().date()} ~ {ted.index.max().date()})", flush=True)
    print(f"※ LIBOR 폐지로 {TED_LAST_VALID_DATE} 이후 데이터 없음 — 2022년 이후 위기는 이 지표로 볼 수 없음", flush=True)

    print("VIX(VIXCLS) 조회 중...", flush=True)
    vix = fred_data.get_series("VIXCLS", start="1990-01-01").dropna()
    print("BAA10Y(크레딧 스프레드) 조회 중...", flush=True)
    baa10y = fred_data.get_series("BAA10Y", start="1986-01-01", use_cache=False).dropna()
    print("USREC(NBER 침체 판정) 조회 중...", flush=True)
    recession = fred_data.get_series("USREC", start="1986-01-01")
    recession_monthly = recession.asfreq("MS")

    print("S&P500(^GSPC) 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1986-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    # ===== TED 스트레스 이벤트 탐지 (직전3년 90퍼센타일, 10거래일 지속형) =====
    rolling_p90_ted = ted.shift(1).rolling(TED_ROLLING_WINDOW).quantile(TED_PERCENTILE)
    valid_from = rolling_p90_ted.first_valid_index()
    above_ted = (ted > rolling_p90_ted).reindex(ted.index).fillna(False)
    above_ted = above_ted[ted.index >= valid_from]
    ted_on, ted_off = detect_sustained_crossings(above_ted, TED_MIN_PERSIST)
    print(f"\nTED 스트레스 이벤트 시작(90퍼센타일, 10거래일 지속형): {len(ted_on)}건, 해소: {len(ted_off)}건", flush=True)
    for d in ted_on:
        print(f"  스트레스 시작: {d.date()} | TED={float(ted.loc[d]):.2f}%p", flush=True)

    df_ted = build_rows(ted_on, close, idx)

    print("\n=== H1: TED 스트레스 이벤트 이후 S&P500 ===", flush=True)
    s_ted = summarize(df_ted, "TED 스트레스")
    print("\n=== 기준선(전체 거래일 평균) ===", flush=True)
    baseline = baseline_forward_returns(close)
    for h in HORIZONS:
        print(f"  +{h}일 기준선: {baseline.get(f'fwd_{h}d_mean_pct')}%(승률{baseline.get(f'fwd_{h}d_win_rate_pct')}%)", flush=True)

    # ===== H2: 기존 VIX·크레딧 이벤트와 교차 =====
    vix_events = detect_high_spike_events(vix, VIX_THRESHOLD, VIX_LOOKBACK)
    rolling_p90_credit = baa10y.shift(1).rolling(CREDIT_ROLLING_WINDOW).quantile(CREDIT_PERCENTILE)
    valid_from_credit = rolling_p90_credit.first_valid_index()
    above_credit = (baa10y > rolling_p90_credit).reindex(baa10y.index).fillna(False)
    above_credit = above_credit[baa10y.index >= valid_from_credit]
    credit_state = detect_sustained_state(above_credit, CREDIT_MIN_PERSIST)
    vix_state = detect_sustained_state(vix >= VIX_THRESHOLD, 1)  # 참고용 단순 상태(지속필터 없음, VIX는 원래 급등감지가 별도 규칙)

    def credit_state_asof(d):
        avail = credit_state[credit_state.index <= d]
        return bool(avail.iloc[-1]) if len(avail) else False

    def vix_ge30_asof(d):
        # 그날 VIX 종가 자체가 30 이상이었는지(단순 레벨, 급등 이벤트 여부와는 별개 참고지표)
        avail = vix[vix.index <= d]
        return bool(avail.iloc[-1] >= VIX_THRESHOLD) if len(avail) else False

    print("\n=== H2: TED 스트레스 이벤트와 VIX/크레딧 겹침 ===", flush=True)
    tag_rows = []
    for d in ted_on:
        tag_rows.append({
            "date": str(d.date()), "ted": round(float(ted.loc[d]), 2),
            "vix_ge30_that_day": vix_ge30_asof(d), "credit_stress": credit_state_asof(d),
        })
    tag_df = pd.DataFrame(tag_rows)
    for _, r in tag_df.iterrows():
        print(f"  {r['date']}  TED={r['ted']}  VIX당일>=30={r['vix_ge30_that_day']}  크레딧스트레스중={r['credit_stress']}", flush=True)
    n_total = len(tag_df)
    n_vix = int(tag_df["vix_ge30_that_day"].sum()) if n_total else 0
    n_credit = int(tag_df["credit_stress"].sum()) if n_total else 0
    n_both = int((tag_df["vix_ge30_that_day"] & tag_df["credit_stress"]).sum()) if n_total else 0
    print(f"\n요약: 전체 {n_total}건 중 그날 VIX&ge;30인 경우 {n_vix}건, 크레딧스트레스중 {n_credit}건, 둘다 {n_both}건", flush=True)

    # ===== H3: 침체 여부 분리 =====
    def is_recession(dt: pd.Timestamp) -> bool:
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        nearest = recession_monthly.index[recession_monthly.index <= month_start]
        if len(nearest) == 0:
            return False
        return bool(recession_monthly.loc[nearest[-1]] == 1.0)

    df_ted["recession"] = [is_recession(pd.Timestamp(d)) for d in df_ted["date"]]
    print("\n=== H3: 침체(USREC) 여부로 분리 ===", flush=True)
    n_rec = int(df_ted["recession"].sum())
    n_norec = int((~df_ted["recession"]).sum())
    print(f"침체중 {n_rec}건, 비침체중 {n_norec}건", flush=True)
    print("\n개별 사례:", flush=True)
    for _, r in df_ted.iterrows():
        print(f"  {r['date']}  침체중={r['recession']}  " + "  ".join(
            f"+{h}일={r.get(f'fwd_{h}d_pct')}%" for h in HORIZONS), flush=True)

    out_json = {
        "series_used": "TEDRATE (FRED, valid through 2022-01-21 due to LIBOR discontinuation)",
        "ted_history": {"start": str(ted.index.min().date()), "end": str(ted.index.max().date())},
        "primary_threshold": {"type": "rolling_3yr_p90", "window_days": TED_ROLLING_WINDOW, "percentile": TED_PERCENTILE},
        "events": df_ted.to_dict(orient="records"),
        "summary": s_ted,
        "baseline": baseline,
        "h2_crosstab": {"events": tag_df.to_dict(orient="records"),
                        "n_total": n_total, "n_vix": n_vix, "n_credit": n_credit, "n_both": n_both},
        "h3_recession_split": {"n_recession": n_rec, "n_norecession": n_norec},
    }
    with open(f"{OUT_DIR}/bank_funding_stress_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
