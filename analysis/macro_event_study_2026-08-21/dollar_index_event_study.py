"""트랙 A 확장(신규) — 달러지수 자체를 임계값 교차 "신호"로 검증한다.

지금까지 트랙 E(자산군 교차분석)의 CPI/FOMC/대선주기 스터디들은 달러지수(DX-Y.NYB)를
"다른 사건에 반응하는 자산" 중 하나로만 다뤘다. 이번엔 처음으로 달러지수 자체를 장단기
금리역전·VIX 급등·크레딧 스프레드처럼 "선을 넘는" 독립 신호로 취급해, "달러가 너무 강하면
S&P500(미국 다국적기업 실적)에 역풍"이라는 통설과 그 거울상("약달러가 수출기업에 순풍")을
검증한다.

**데이터 출처 선택과 근거(사전 공개)**: DX-Y.NYB(야후파이낸스, ICE 달러인덱스)와
DTWEXBGS(FRED, 무역가중 광의 달러지수) 둘 다 확인했다.
  - DX-Y.NYB: 1971-01-04 ~ 현재, 총 14,136거래일(약 56년) — 이 프로젝트의 다른 장기 시리즈
    (T10Y2Y 50년, BAA10Y 40년)와 비슷하거나 더 긴 축에 속한다.
  - DTWEXBGS: 2006-01-02 ~ 현재, 총 5,390거래일(약 20년)만 제공 — 2008년 위기는 겨우 담지만
    1980년대 초 레이건 시절 슈퍼달러 강세, 1985년 플라자합의발 달러 급락 같은 이 신호의
    가장 유명한 역사적 사례들을 아예 담지 못한다.
  둘 다 "무역가중 달러지수"라는 개념은 같지만 구성 바스켓이 다르다(DXY는 유로 비중이 커
  유로화 출범(1999) 이전엔 전신 통화 바스켓으로 소급 계산된 값). 그래도 "달러 강세/약세라는
  큰 국면"을 잡는 목적에는 문제 없고, 표본 기간이 2.6배 이상 길다는 실익이 훨씬 크므로
  **DX-Y.NYB를 주 데이터로 채택**한다. 이 결정을 리포트에도 그대로 공개한다.

**방법론(장단기 금리역전·크레딧 스프레드 스터디와 동일한 규율 재사용)**:
  - 서지(SURGE) = 달러지수가 자기 자신의 "직전 2년(504거래일) rolling 80퍼센타일"을 넘어서는
    상태가 최소 10거래일 연속 유지될 때, 그 유지구간의 첫날을 이벤트로 잡는다(장단기 금리역전
    스터디의 "10거래일 지속 필터"를 그대로 재사용해 0/경계 근처 노이즈성 돌파를 걸러낸다).
  - 콜랩스(COLLAPSE) = 거울상으로 "직전 2년 rolling 20퍼센타일" 아래로 최소 10거래일 연속
    유지될 때의 첫날.
  - 두 임계값(80/20퍼센타일)은 이 프로젝트가 크레딧 스프레드 스터디에서 쓴 "사후에 유리한
    걸 고르지 않는다"는 원칙을 따라 결과를 보기 전에 정한, 무난한 라운드 넘버다.
  - 룩어헤드 방지를 위해 rolling 퍼센타일은 1일 shift한 값을 기준으로 판정한다.

**사전등록 가설(결과를 보기 전에 명시)**:
  H1: 달러 서지(강달러) 시작일 기준 S&P500의 +5/20/60/120거래일 순방향 수익률이 무조건부
      기준선(전체 거래일 평균)보다 나쁠 것이다 — "강달러는 미국 다국적기업 수출/해외실적에
      역풍"이라는 통설.
  H2(거울상): 달러 콜랩스(약달러) 시작일 기준 S&P500 순방향 수익률이 기준선보다 좋을 것이다 —
      "약달러는 수출기업에 순풍"이라는 통설의 거울상 검증. H1만 보고 끝내지 않고 H2도 동일한
      엄밀함으로 검증한다.
  H3(탐색적): (a) 서지/콜랩스 이벤트를 NBER 침체(USREC) 여부로 나눠 국면에 따라 다르게
      움직이는지 확인한다(이 프로젝트에서 반복 확인된 "국면이 중요하다" 주제의 재현 여부).
      (b) 달러 서지/콜랩스 시점이 이미 확립된 다른 위기 게이지(VIX>=30 급등, 크레딧 스프레드
      스트레스, 장단기 금리역전)와 겹치는지 정성적 교차표만 본다(엄밀한 통계 검정이 아니라
      "달러 강세가 이미 알려진 스트레스 시기에 동반되는 현상인지, 독립적인 현상인지"를 보는
      탐색적 크로스체크).

표본이 아주 작을 수 있다는 걸 미리 밝혀둔다(2년 rolling 퍼센타일 + 10거래일 지속 필터를
같이 쓰면 상당히 제한적인 결과가 나올 수 있음) — 정직하게 보고하고 방향성 참고로 다룬다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
MIN_PERSIST_DAYS = 10
ROLLING_WINDOW = 504  # 약 2년(거래일)
SURGE_PCTILE = 0.80
COLLAPSE_PCTILE = 0.20


def detect_sustained_crossings(above: pd.Series, min_persist: int = MIN_PERSIST_DAYS):
    """above: bool Series(True=조건 충족 상태). 상태가 바뀐 뒤 min_persist거래일 연속 유지되면
    그 시작일을 이벤트로 잡는다(장단기 금리역전·크레딧 스프레드 스터디와 동일한 방법론)."""
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


def build_fwd_table(dates: list, close: pd.Series) -> pd.DataFrame:
    idx = close.index
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
        rows.append({"date": str(idx[pos].date()), "pos": int(pos), **fwd})
    return pd.DataFrame(rows)


def summarize(sub: pd.DataFrame, label: str) -> dict:
    if len(sub) == 0:
        print(f"  [{label}] 표본 없음", flush=True)
        return {"n": 0}
    out = {"n": len(sub)}
    for h in HORIZONS:
        col = f"fwd_{h}d_pct"
        if col not in sub.columns:
            continue
        vals = sub[col].dropna()
        if len(vals) == 0:
            continue
        out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
        out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
    print(f"  [{label}] n={out['n']}, "
          f"+60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%), "
          f"+120일={out.get('fwd_120d_mean_pct')}%(승률{out.get('fwd_120d_win_rate_pct')}%)", flush=True)
    return out


def baseline_forward_returns(close: pd.Series) -> dict:
    idx = close.index
    out = {"n": len(idx)}
    for h in HORIZONS:
        fwd = 100 * (close.shift(-h) / close - 1)
        vals = fwd.dropna()
        out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
        out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
    return out


def load_other_gauge_dates():
    """기존 스터디들이 이미 만들어둔 위기게이지 이벤트 날짜를 재사용한다(재계산하지 않음)."""
    gauges = {}
    try:
        with open(f"{OUT_DIR}/yield_curve_event_study.json", encoding="utf-8") as f:
            yc = json.load(f)
        gauges["inversion"] = set(yc["inversion_dates"])
    except Exception:
        gauges["inversion"] = set()
    try:
        with open(f"{OUT_DIR}/credit_spread_event_study.json", encoding="utf-8") as f:
            cs = json.load(f)
        gauges["credit_stress"] = {r["date"] for r in cs["events_pctile"]}
    except Exception:
        gauges["credit_stress"] = set()
    try:
        with open(f"{OUT_DIR}/vix_spike_event_study.json", encoding="utf-8") as f:
            vx = json.load(f)
        gauges["vix30"] = {r["date"] for r in vx["results"]["30"]["events"]}
    except Exception:
        gauges["vix30"] = set()
    return gauges


def crosstab_overlap(event_dates: list, close_idx: pd.DatetimeIndex, gauge_dates: set, window: int = 20) -> int:
    """이벤트 날짜가 다른 게이지 이벤트로부터 +-window거래일 안에 있으면 "겹침"으로 센다."""
    if not gauge_dates:
        return 0
    gauge_ts = sorted(pd.Timestamp(d) for d in gauge_dates)
    count = 0
    for ed in event_dates:
        ed = pd.Timestamp(ed)
        for gd in gauge_ts:
            if abs((close_idx.get_indexer([ed], method="nearest")[0]) -
                   (close_idx.get_indexer([gd], method="nearest")[0])) <= window:
                count += 1
                break
    return count


def main():
    print("달러지수(DX-Y.NYB) 조회 중...", flush=True)
    dxy_hist = get_multiple_price_history(["DX-Y.NYB"], start="1971-01-01", end="2026-09-05", interval="1d")["DX-Y.NYB"]
    dxy = dxy_hist["Close"].dropna()
    print(f"DXY 데이터: {len(dxy)}건 ({dxy.index.min().date()} ~ {dxy.index.max().date()})", flush=True)

    rolling_p80 = dxy.shift(1).rolling(ROLLING_WINDOW).quantile(SURGE_PCTILE)
    rolling_p20 = dxy.shift(1).rolling(ROLLING_WINDOW).quantile(COLLAPSE_PCTILE)
    valid_from = rolling_p80.first_valid_index()
    print(f"롤링 2년 퍼센타일 기준 유효 시작일: {valid_from.date()}", flush=True)

    above_p80 = (dxy > rolling_p80).reindex(dxy.index).fillna(False)
    above_p80 = above_p80[dxy.index >= valid_from]
    below_p20 = (dxy < rolling_p20).reindex(dxy.index).fillna(False)
    below_p20 = below_p20[dxy.index >= valid_from]

    surge_on, surge_off = detect_sustained_crossings(above_p80)
    collapse_on, collapse_off = detect_sustained_crossings(below_p20)
    print(f"\n[서지: 직전2년 80퍼센타일 상향돌파 10거래일+ 지속] 시작 {len(surge_on)}건, 해소 {len(surge_off)}건", flush=True)
    for d in surge_on:
        print("  서지 시작:", d.date(), "| 당시 DXY:", round(float(dxy.loc[d]), 2))
    print(f"\n[콜랩스: 직전2년 20퍼센타일 하향돌파 10거래일+ 지속] 시작 {len(collapse_on)}건, 해소 {len(collapse_off)}건", flush=True)
    for d in collapse_on:
        print("  콜랩스 시작:", d.date(), "| 당시 DXY:", round(float(dxy.loc[d]), 2))

    print("\nS&P500 가격 데이터 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1970-01-01", end="2026-09-05", interval="1d")["^GSPC"]
    close = spx_hist["Close"].dropna()

    df_surge = build_fwd_table(surge_on, close)
    df_collapse = build_fwd_table(collapse_on, close)

    print("\n=== 기준선(전체 거래일 평균 순방향 수익률) ===", flush=True)
    baseline = baseline_forward_returns(close)
    for h in HORIZONS:
        print(f"  +{h}일 기준선: {baseline.get(f'fwd_{h}d_mean_pct')}%(승률{baseline.get(f'fwd_{h}d_win_rate_pct')}%)", flush=True)

    print("\n=== H1: 달러 서지 이후 S&P500 ===", flush=True)
    s_surge = summarize(df_surge, "서지")
    print("\n=== H2: 달러 콜랩스 이후 S&P500 ===", flush=True)
    s_collapse = summarize(df_collapse, "콜랩스")

    # H1/H2 verdict
    def worse_than_baseline(summary):
        flags = []
        for h in HORIZONS:
            m = summary.get(f"fwd_{h}d_mean_pct")
            b = baseline.get(f"fwd_{h}d_mean_pct")
            if m is None or b is None:
                continue
            flags.append(m < b)
        return flags

    def better_than_baseline(summary):
        flags = []
        for h in HORIZONS:
            m = summary.get(f"fwd_{h}d_mean_pct")
            b = baseline.get(f"fwd_{h}d_mean_pct")
            if m is None or b is None:
                continue
            flags.append(m > b)
        return flags

    h1_flags = worse_than_baseline(s_surge)
    h2_flags = better_than_baseline(s_collapse)
    print(f"\nH1 판정용(서지가 기준선보다 나쁜 호라이즌 수): {sum(h1_flags)}/{len(h1_flags)}", flush=True)
    print(f"H2 판정용(콜랩스가 기준선보다 좋은 호라이즌 수): {sum(h2_flags)}/{len(h2_flags)}", flush=True)

    # H3(a): 침체 분리
    print("\n=== H3(a): 침체(USREC) 여부로 분리 ===", flush=True)
    recession = fred_data.get_series("USREC", start="1970-01-01")
    recession_monthly = recession.asfreq("MS")

    def is_recession(dt_str: str) -> bool:
        dt = pd.Timestamp(dt_str)
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        if month_start in recession_monthly.index:
            return bool(recession_monthly.loc[month_start] == 1.0)
        nearest = recession_monthly.index[recession_monthly.index <= month_start]
        if len(nearest) == 0:
            return False
        return bool(recession_monthly.loc[nearest[-1]] == 1.0)

    for df, label in [(df_surge, "서지"), (df_collapse, "콜랩스")]:
        if len(df) == 0:
            continue
        df["recession"] = df["date"].apply(is_recession)

    h3a = {}
    for df, key in [(df_surge, "surge"), (df_collapse, "collapse")]:
        if len(df) == 0:
            h3a[key] = {"n_recession": 0, "n_norecession": 0}
            continue
        n_rec = int(df["recession"].sum())
        n_norec = int((~df["recession"]).sum())
        print(f"[{key}] 침체중 {n_rec}건, 비침체중 {n_norec}건", flush=True)
        h3a[key] = {
            "n_recession": n_rec, "n_norecession": n_norec,
            "recession_events": df[df["recession"]].to_dict(orient="records"),
            "norecession_events": df[~df["recession"]].to_dict(orient="records"),
        }
        if n_rec >= 3:
            h3a[key]["recession_summary"] = summarize(df[df["recession"]], f"{key}-침체중")
        if n_norec >= 3:
            h3a[key]["norecession_summary"] = summarize(df[~df["recession"]], f"{key}-비침체중")

    # H3(b): 다른 위기게이지와의 겹침
    print("\n=== H3(b): 다른 위기게이지와의 시점 겹침(교차표, 정성적) ===", flush=True)
    gauges = load_other_gauge_dates()
    h3b = {}
    for df, dates, key in [(df_surge, surge_on, "surge"), (df_collapse, collapse_on, "collapse")]:
        n = len(dates)
        overlap = {}
        for gname, gdates in gauges.items():
            c = crosstab_overlap(dates, close.index, gdates, window=20)
            overlap[gname] = {"overlap_n": c, "total_gauge_events": len(gdates)}
            print(f"  [{key}] vs {gname}: {c}/{n}건이 +-20거래일 내 겹침 (게이지 전체 이벤트 {len(gdates)}건)", flush=True)
        h3b[key] = {"n_events": n, "overlap": overlap}

    out = {
        "series_used": "DX-Y.NYB (yfinance ICE US Dollar Index) — chosen over FRED DTWEXBGS for ~56yr vs ~20yr history",
        "dxy_history": {"start": str(dxy.index.min().date()), "end": str(dxy.index.max().date()), "n": len(dxy)},
        "threshold": {"type": "rolling_2yr_percentile", "window_days": ROLLING_WINDOW,
                      "surge_percentile": SURGE_PCTILE, "collapse_percentile": COLLAPSE_PCTILE},
        "min_persist_days": MIN_PERSIST_DAYS,
        "surge_events": df_surge.to_dict(orient="records"),
        "collapse_events": df_collapse.to_dict(orient="records"),
        "surge_dates": [str(d.date()) for d in surge_on],
        "collapse_dates": [str(d.date()) for d in collapse_on],
        "baseline": baseline,
        "summary_surge": s_surge,
        "summary_collapse": s_collapse,
        "h1_verdict_flags_worse_than_baseline": h1_flags,
        "h2_verdict_flags_better_than_baseline": h2_flags,
        "h3a_recession_split": h3a,
        "h3b_gauge_overlap": h3b,
    }
    with open(f"{OUT_DIR}/dollar_index_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
