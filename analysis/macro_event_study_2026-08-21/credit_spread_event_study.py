"""트랙 H — 신용시장의 "공포지수": 크레딧 스프레드 급등 이벤트 스터디.

VIX(주식 변동성)·장단기 금리차(금리 기대)와는 다른 세 번째 정보원 — 정크본드(투기등급 회사채)가
국채보다 얼마나 더 높은 금리를 요구하는지("크레딧 스프레드")를 본다. 이 스프레드는 신용시장이
불안할 때(2008, 2020, 2015~16 에너지신용 위기, 2022) 급격히 벌어지고, 평온할 때는 낮게
유지된다 — 주식시장 변동성이나 금리 기대와는 독립적으로 움직일 수 있는 신호다.

**데이터 출처 관련 중요 메모(2026-08-23 확인)**: 원래 계획한 FRED BAMLH0A0HYM2(ICE BofA
미국 하이일드 지수 옵션조정스프레드, "진짜" 정크본드 스프레드)를 조회했더니, FRED가 2026년
4월부터 이 시리즈를 "최근 3년치만" 제공하는 것으로 정책을 바꿨다는 걸 발견했다(FRED API
메타데이터에 "Starting in April 2026, this series will only include 3 years of observations"
라고 명시돼 있음 — 라이선스 제공처인 ICE Data의 정책 변경으로 보인다). 3년치(2023-08~2026-08)
로는 2008·2020 같은 진짜 신용위기를 하나도 담지 못해 이 스터디의 목적 자체가 무의미해진다.

그래서 이 스터디는 **FRED BAA10Y(무디스 Baa등급 회사채 금리 - 10년 국채금리, 1986년부터
전체 무제한 제공)로 대체**한다. 하이일드(투기등급) 스프레드보다는 한 단계 위인 "낮은
투자등급" 스프레드지만, 학계·연준 이코노미스트들도 신용시장 스트레스 게이지로 흔히 쓰는
지표이고(Gilchrist-Zakrajšek 초과채권프리미엄 연구 등이 이 계열), 무엇보다 2008·2011·
2015~16·2018·2020·2022 등 이 프로젝트가 다뤄온 모든 위기 국면을 실제로 담고 있다. 원래
쓰려던 800bps라는 절대 임계값은 하이일드 스프레드 기준으로 설계된 값이라 BAA10Y에는 그대로
쓸 수 없다 — 대신 BAA10Y의 전체 역사(1986~2026)에서 상위 10% 안에 드는 수준으로 사전에
근사한 300bp(3.0%p)를 절대 임계값 대안으로 쓴다(2008년 정점 약 6%p, 2020년 정점 약 4%p와
비교하면 "뚜렷한 스트레스"로 볼 수 있는 눈금이다). 이 대체 결정과 그 이유를 리포트에 그대로
공개한다 — 조용히 다른 지표로 바꿔치기하지 않는다.

사전 등록 가설(결과를 보기 전에 적어둔다):
  H1: 크레딧 스프레드가 극단적으로 벌어지는(신용 스트레스) 이벤트 이후, S&P500의 60~120거래일
      순방향 수익률은 평상시(기준선) 평균보다 높다 — VIX 급등 스터디의 "공포에 사라"와 같은
      역발상 매수 신호로 기능한다는 가설.
      사전 확정 기준: (1) 주 기준 — 스프레드가 자기 자신의 "직전 3년(756거래일) rolling 90
      퍼센타일"을 넘어서는 것(고정 bp가 아니라 국면에 맞춰 적응하는 기준 — 수십 년에 걸쳐
      스프레드의 구조적 수준 자체가 달라지기 때문에 이렇게 정의한다), (2) 보조/강건성 체크 —
      고정 절대 임계값 3.0%p(300bp).
  H2: 장단기 금리역전(선행지표, 실제 침체까지 시차 6개월~2년+, 매우 길고 들쭉날쭉)과 달리,
      크레딧 스프레드 급등은 "동행"에 가까운 신호일 것이다 — 즉 스프레드 급등 이벤트 시점이
      그 이후 250거래일 안에서 S&P500이 저점을 찍는 시점과 시간적으로 더 가까울 것이다.
      (장단기 금리역전의 6개월~2년+ 시차는 이미 이 프로젝트에서 확인된 값이라 재확인하지 않고
      그대로 인용해 비교한다.)
  H3(탐색적): 이 프로젝트 다른 곳에서 확립한 침체/비침체 구분(NBER USREC)을 크레딧 스트레스
      이벤트에 적용하면, 침체 중 이벤트는 결과가 양극화(일부는 크게 반등, 일부는 실제로 계속
      하락)되고 비침체 중 이벤트는 더 일관되게 완만한 상승을 보일 것이다(샴의 법칙 양극화와
      비슷한 패턴). 표본이 5건 미만인 셀은 통계표 대신 정성적으로만 서술한다(진짜 신용
      스트레스 이벤트 자체가 드물어서 셀이 매우 작아질 수 있다는 걸 미리 밝혀둔다).

방법론: 장단기 금리역전 스터디와 동일하게 "최소 10거래일 연속 유지"를 진짜 이벤트로 인정하는
필터를 그대로 적용해 노이즈 플리커링을 제거한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import numpy as np
import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120, 250]
MIN_PERSIST_DAYS = 10
ROLLING_WINDOW = 756  # 약 3년(거래일)
PERCENTILE = 0.90
FIXED_THRESHOLD_PP = 3.0  # BAA10Y 기준 대안 절대 임계값(%p)
TROUGH_WINDOW = 250  # H2: 이벤트 이후 며칠 안에서 저점을 찾을지


def detect_sustained_crossings(above: pd.Series, min_persist: int = MIN_PERSIST_DAYS):
    """above: bool Series(True=스트레스 상태). 상태가 바뀐 뒤 min_persist거래일 연속 유지되면
    그 시작일을 이벤트로 잡는다(장단기 금리역전 스터디와 동일한 방법론)."""
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


def summarize(sub: pd.DataFrame, label: str, horizons=HORIZONS) -> dict:
    if len(sub) == 0:
        print(f"  [{label}] 표본 없음", flush=True)
        return {"n": 0}
    out = {"n": len(sub)}
    for h in horizons:
        col = f"fwd_{h}d_pct"
        if col not in sub.columns:
            continue
        vals = sub[col].dropna()
        if len(vals) == 0:
            continue
        out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
        out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
        out[f"fwd_{h}d_min_pct"] = round(vals.min(), 3)
        out[f"fwd_{h}d_max_pct"] = round(vals.max(), 3)
    print(f"  [{label}] n={out['n']}, +60일={out.get('fwd_60d_mean_pct')}%(승률{out.get('fwd_60d_win_rate_pct')}%), "
          f"+120일={out.get('fwd_120d_mean_pct')}%(승률{out.get('fwd_120d_win_rate_pct')}%)", flush=True)
    return out


def baseline_forward_returns(close: pd.Series) -> dict:
    """전체 표본기간 모든 거래일 기준 순방향 수익률 분포(무작위 날짜 기준선) — 이벤트 이후
    수익률이 '평상시보다 높은지' 비교할 기준선."""
    idx = close.index
    out = {"n": len(idx)}
    for h in HORIZONS:
        fwd = 100 * (close.shift(-h) / close - 1)
        vals = fwd.dropna()
        out[f"fwd_{h}d_mean_pct"] = round(vals.mean(), 3)
        out[f"fwd_{h}d_win_rate_pct"] = round(100 * (vals > 0).mean(), 1)
    return out


def nearest_trough_lag(event_pos: int, close: pd.Series, window: int = TROUGH_WINDOW):
    """이벤트 시점부터 window거래일 안에서 종가 최저치(저점)를 찍는 시점까지의 거래일수(지연)."""
    idx = close.index
    end_pos = min(event_pos + window, len(idx) - 1)
    if end_pos <= event_pos:
        return None
    segment = close.iloc[event_pos:end_pos + 1]
    trough_pos_rel = int(np.argmin(segment.values))
    trough_date = segment.index[trough_pos_rel]
    lag_trading_days = trough_pos_rel
    lag_calendar_days = (trough_date - idx[event_pos]).days
    return {"trough_date": str(trough_date.date()), "lag_trading_days": lag_trading_days,
            "lag_calendar_days": lag_calendar_days}


def main():
    print("BAA10Y(Baa 회사채-10년국채 스프레드) 조회 중...", flush=True)
    spread = fred_data.get_series("BAA10Y", start="1986-01-01", use_cache=False).dropna()
    print(f"스프레드 데이터: {len(spread)}건 ({spread.index.min().date()} ~ {spread.index.max().date()})", flush=True)

    # 사전 확정 주 기준: 직전 3년 rolling 90퍼센타일(룩어헤드 방지 위해 1일 shift)
    rolling_p90 = spread.shift(1).rolling(ROLLING_WINDOW).quantile(PERCENTILE)
    valid_from = rolling_p90.first_valid_index()
    print(f"롤링 90퍼센타일 기준 유효 시작일: {valid_from.date()}", flush=True)

    above_pctile = (spread > rolling_p90).reindex(spread.index).fillna(False)
    above_pctile = above_pctile[spread.index >= valid_from]
    events_on_pctile, events_off_pctile = detect_sustained_crossings(above_pctile)
    print(f"\n[주 기준: 직전3년 90퍼센타일 상향돌파] 스트레스 이벤트 시작: {len(events_on_pctile)}건, "
          f"해소: {len(events_off_pctile)}건", flush=True)
    for d in events_on_pctile:
        print("  스트레스 시작:", d.date(), "| 당시 스프레드:", round(float(spread.loc[d]), 2), "%p")

    above_fixed = (spread > FIXED_THRESHOLD_PP)
    events_on_fixed, events_off_fixed = detect_sustained_crossings(above_fixed)
    print(f"\n[보조 기준: 고정 {FIXED_THRESHOLD_PP}%p 상향돌파] 스트레스 이벤트 시작: {len(events_on_fixed)}건", flush=True)
    for d in events_on_fixed:
        print("  스트레스 시작:", d.date(), "| 당시 스프레드:", round(float(spread.loc[d]), 2), "%p")

    print("\nS&P500 가격 데이터 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1985-01-01", end="2026-08-20", interval="1d")["^GSPC"]
    close = spx_hist["Close"]

    df_pctile = build_fwd_table(events_on_pctile, close)
    df_fixed = build_fwd_table(events_on_fixed, close)

    print("\n=== H1: 스트레스 이벤트 이후 S&P500 (주 기준: 90퍼센타일) ===", flush=True)
    s_pctile = summarize(df_pctile, "90퍼센타일 돌파")
    print("\n=== H1 보조: 고정 3.0%p 임계값 ===", flush=True)
    s_fixed = summarize(df_fixed, "고정3.0%p 돌파")

    print("\n=== 기준선(전체 거래일 평균 순방향 수익률) ===", flush=True)
    baseline = baseline_forward_returns(close)
    for h in HORIZONS:
        print(f"  +{h}일 기준선: {baseline.get(f'fwd_{h}d_mean_pct')}%(승률{baseline.get(f'fwd_{h}d_win_rate_pct')}%)", flush=True)

    # H2: 저점까지의 시차
    print("\n=== H2: 이벤트 -> 이후 250거래일 내 S&P500 저점까지의 시차 ===", flush=True)
    idx = close.index
    lag_records = []
    for event_date in events_on_pctile:
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx):
            continue
        info = nearest_trough_lag(pos, close)
        if info is None:
            continue
        info["event_date"] = str(idx[pos].date())
        lag_records.append(info)
        print(f"  {info['event_date']} -> 저점 {info['trough_date']} "
              f"({info['lag_trading_days']}거래일 = 약 {info['lag_calendar_days']}일)", flush=True)
    lag_df = pd.DataFrame(lag_records)
    lag_summary = {}
    if len(lag_df):
        lag_summary = {
            "n": len(lag_df),
            "median_lag_trading_days": float(lag_df["lag_trading_days"].median()),
            "mean_lag_trading_days": float(lag_df["lag_trading_days"].mean()),
            "median_lag_calendar_days": float(lag_df["lag_calendar_days"].median()),
            "mean_lag_calendar_days": float(lag_df["lag_calendar_days"].mean()),
        }
        print(f"\n  중앙값 시차: {lag_summary['median_lag_trading_days']:.0f}거래일 "
              f"(약 {lag_summary['median_lag_calendar_days']:.0f}일)", flush=True)
        print(f"  평균 시차: {lag_summary['mean_lag_trading_days']:.0f}거래일 "
              f"(약 {lag_summary['mean_lag_calendar_days']:.0f}일)", flush=True)

    # H3: 침체/비침체 분리
    print("\n=== H3: 침체(USREC) 여부로 분리 ===", flush=True)
    recession = fred_data.get_series("USREC", start="1985-01-01")
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

    df_pctile["recession"] = df_pctile["date"].apply(is_recession)
    n_rec = int(df_pctile["recession"].sum())
    n_norec = int((~df_pctile["recession"]).sum())
    print(f"침체중 이벤트 {n_rec}건, 비침체중 이벤트 {n_norec}건", flush=True)
    s_h3_rec, s_h3_norec = {"n": n_rec}, {"n": n_norec}
    if n_rec >= 5:
        s_h3_rec = summarize(df_pctile[df_pctile["recession"]], "침체중")
    else:
        print(f"  [침체중] n={n_rec} < 5 — 표본이 너무 작아 통계표 대신 개별 사례만 기록", flush=True)
    if n_norec >= 5:
        s_h3_norec = summarize(df_pctile[~df_pctile["recession"]], "비침체중")
    else:
        print(f"  [비침체중] n={n_norec} < 5 — 표본이 너무 작아 통계표 대신 개별 사례만 기록", flush=True)

    out = {
        "series_used": "BAA10Y (originally planned BAMLH0A0HYM2, truncated to 3yr by FRED policy 2026-04)",
        "spread_history": {"start": str(spread.index.min().date()), "end": str(spread.index.max().date()), "n": len(spread)},
        "primary_threshold": {"type": "rolling_3yr_p90", "window_days": ROLLING_WINDOW, "percentile": PERCENTILE},
        "fixed_threshold_pp": FIXED_THRESHOLD_PP,
        "events_pctile": df_pctile.to_dict(orient="records"),
        "events_fixed": df_fixed.to_dict(orient="records"),
        "summary_pctile": s_pctile,
        "summary_fixed": s_fixed,
        "baseline": baseline,
        "h2_lag": {"records": lag_records, "summary": lag_summary},
        "h3": {"n_recession": n_rec, "n_norecession": n_norec, "recession": s_h3_rec, "norecession": s_h3_norec,
               "recession_events": df_pctile[df_pctile["recession"]].to_dict(orient="records") if n_rec else [],
               "norecession_events": df_pctile[~df_pctile["recession"]].to_dict(orient="records") if n_norec else []},
    }
    with open(f"{OUT_DIR}/credit_spread_event_study.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
