"""트랙 H 후속 — 크레딧 스프레드 스트레스 x 침체(USREC)로 "호라이즌-반전" 패턴을 다시 검증한다.

배경: four_gauge_dashboard_study.py(네 개 위기 게이지: VIX·장단기 금리역전·크레딧스프레드·TED를
쌓아 게이지 개수(0~4개)별 순방향 수익률을 본 캡스톤)는 "게이지가 많을수록 장기(+60·120일)는
계단식으로 단조 악화되지만, 단기(+5·20일)는 오히려 게이지가 많을수록 승률이 높아지는" 독특한
"장기 단조 악화·단기 반전" 모양을 발견했다. 그 스터디의 "다음 후보"로, 이 모양이 네 게이지를
쌓은 특정 조합에서만 나오는 우연인지 확인하기 위해 horizon_reversal_replication_study.py가
더 단순한 2-게이지 조합(VIX>=30 급등 x USREC 침체)으로 재현을 시도했으나 **재현 실패**했다 —
침체중 VIX 급등은 장기뿐 아니라 단기(+5·20일)에도 비침체보다 한결같이 약해서(단조적으로 나쁨),
"단기엔 반전"이라는 핵심 모양이 나타나지 않았다. 그 스터디 자신의 "다음 후보"는 VIX 대신
크레딧 스프레드 x 침체 조합으로 한 번 더 시도해볼 것을 명시적으로 제안했다 — 이 스크립트가
그 과제를 수행한다.

이번 조합이 특히 흥미로운 이유: VIX는 이 프로젝트에서 이미 "빠르게 평균회귀하는" 성질이
확립된 지표(트랙F 원 스터디, 안일함 후속검증)인 반면, 크레딧 스프레드는 credit_spread_event_
study.py의 H2에서 "장단기 금리역전(선행)보다는 동행에 가깝다"(저점까지 중앙값 79거래일)고
이미 결론지어진, VIX보다 훨씬 느리게 움직이는 신호다. 만약 "호라이즌-반전" 모양이 정말
"빠른 신호 + 느린 확인신호"의 조합에서만 나온다는 이론이 맞다면, 크레딧 스프레드(느림) x
침체(느림)라는 "느린 신호 두 개"의 조합에서도 반전이 안 나타나야 한다 — VIX x 침체 실패와
같은 결과가 나와야 이론이 힘을 얻는다.

사전 등록 가설(결과를 보기 전에 적어둔다):
  H1: 크레딧 스프레드 스트레스 이벤트(credit_spread_event_study.py의 정의를 그대로 재사용 —
      직전 3년(756거래일) rolling 90퍼센타일 상향돌파 + 10거래일 연속 유지 필터, 절대 임계값
      아님)를 침체중/비침체로 나누면 네 게이지 대시보드와 같은 "장기엔 단조적으로 악화되지만
      단기엔 오히려 반전"되는 모양이 나타날 것이다.
      **사전 예측(결과를 보기 전에 명시)**: 크레딧 스프레드는 이미 "동행지표"로 확립돼 있어
      VIX 같은 빠른 평균회귀 성질이 없다 — 따라서 이 가설은 VIX x 침체 조합과 마찬가지로
      **재현되지 않을 것으로 예측한다**. 즉 침체중 크레딧스트레스 이벤트는 장기뿐 아니라
      단기에도 비침체보다 한결같이(단조적으로) 약할 것으로 예상한다(반전 없음).
      예측이 맞으면: "호라이즌-반전 모양은 VIX처럼 빠르게 평균회귀하는 성분이 최소 하나 있어야
      나타난다"는 이론에 힘을 싣는 두 번째 독립 증거가 된다(VIX x 침체 실패에 이어).
      예측이 틀리면(반전 모양이 실제로 나타나면): "느린 신호 두 개를 쌓아도 반전이 나온다"는
      뜻이므로 "빠른 성분 필요" 이론을 직접 반박하는 놀라운 발견이 되고, 그렇게 명확히 표시한다.
  H2(표본크기 정직성, 결과를 보기 전에 명시): credit_spread_event_study.py 원 스터디에서 이미
      13건의 주 기준 이벤트 중 침체중은 단 3건뿐이었다(H3에서 확인됨) — 이번에도 침체중 셀은
      n<5로 작을 가능성이 매우 높다. 이 프로젝트의 소표본 원칙(샴의 법칙, VIX>=50 리포트와
      동일)에 따라 n<5인 셀은 평균/승률 집계 대신 사례별 원자료를 그대로 표로 싣는다.

방법론: 이벤트 탐지는 credit_spread_event_study.py의 detect_sustained_crossings 함수와
ROLLING_WINDOW(756거래일)·PERCENTILE(0.90)·기본 10거래일 연속유지 필터를 그대로 import해서
재사용한다(새로 정의하지 않음). 침체 태깅은 cross_asset_recession_split.py /
horizon_reversal_replication_study.py와 동일한 "USREC 월별 시리즈에서 해당 이벤트 월 이하
최근월 조회" 방식을 그대로 쓴다. 호라이즌은 horizon_reversal_replication_study.py와 동일하게
5/20/60/120거래일(250일 아님 — 저점-시차 분석은 이번 스코프 밖)."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history
from credit_spread_event_study import detect_sustained_crossings, ROLLING_WINDOW, PERCENTILE

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
MIN_N_FOR_STATS = 5  # H2: 이 밑이면 집계 대신 사례별 원자료만 기록


def main():
    print("BAA10Y(Baa 회사채-10년국채 스프레드) 조회 중...", flush=True)
    spread = fred_data.get_series("BAA10Y", start="1986-01-01").dropna()
    print(f"스프레드 데이터: {len(spread)}건 ({spread.index.min().date()} ~ {spread.index.max().date()})", flush=True)

    # credit_spread_event_study.py와 완전히 동일한 주 기준: 직전 3년 rolling 90퍼센타일
    # (룩어헤드 방지 위해 1일 shift), 10거래일 연속 유지 필터
    rolling_p90 = spread.shift(1).rolling(ROLLING_WINDOW).quantile(PERCENTILE)
    valid_from = rolling_p90.first_valid_index()
    print(f"롤링 90퍼센타일 기준 유효 시작일: {valid_from.date()}", flush=True)

    above_pctile = (spread > rolling_p90).reindex(spread.index).fillna(False)
    above_pctile = above_pctile[spread.index >= valid_from]
    events_on, _events_off = detect_sustained_crossings(above_pctile)
    print(f"\n[크레딧스트레스 이벤트: 직전3년 90퍼센타일 상향돌파, 10거래일 지속] {len(events_on)}건", flush=True)
    for d in events_on:
        print("  스트레스 시작:", d.date(), "| 당시 스프레드:", round(float(spread.loc[d]), 2), "%p")

    print("\nS&P500 가격 데이터 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1985-01-01", end="2026-09-11", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    print("\nUSREC(NBER 침체 판정) 조회 중...", flush=True)
    recession = fred_data.get_series("USREC", start="1985-01-01")
    recession_monthly = recession.asfreq("MS")

    def is_recession(dt: pd.Timestamp) -> bool:
        month_start = pd.Timestamp(dt.year, dt.month, 1)
        nearest = recession_monthly.index[recession_monthly.index <= month_start]
        if len(nearest) == 0:
            return False
        return bool(recession_monthly.loc[nearest[-1]] == 1.0)

    rows = []
    for event_date in events_on:
        pos = idx.searchsorted(event_date)
        if pos <= 0 or pos >= len(idx):
            continue
        aligned_date = idx[pos]
        day0_close = close.iloc[pos]
        rec = is_recession(aligned_date)
        fwd = {}
        for h in HORIZONS:
            fut_pos = pos + h
            fwd[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3) if fut_pos < len(idx) else None
        rows.append({"date": str(aligned_date.date()), "spread_pct_p": round(float(spread.loc[event_date]), 2),
                     "recession": rec, **fwd})
        print(f"  {aligned_date.date()}  스프레드={spread.loc[event_date]:.2f}%p  {'침체중' if rec else '비침체'}", flush=True)

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
    s_all = summarize(df, "크레딧스트레스 전체")
    rec_sub = df[df["recession"]]
    norec_sub = df[~df["recession"]]

    n_rec = int(df["recession"].sum())
    n_norec = int((~df["recession"]).sum())
    small_n_rec = n_rec < MIN_N_FOR_STATS
    small_n_norec = n_norec < MIN_N_FOR_STATS

    print(f"\nH2 표본크기 점검: 침체중 n={n_rec}, 비침체 n={n_norec} (기준 n<{MIN_N_FOR_STATS} -> 집계 대신 사례별 원자료)", flush=True)

    if small_n_rec:
        print(f"  [침체중] n={n_rec} < {MIN_N_FOR_STATS} — 집계 대신 개별 사례만 기록"
              f" (단, 아래 h1_verdict 기계적 체크는 참고용으로 계속 계산함)", flush=True)
        s_rec = summarize(rec_sub, "침체중(참고용, n<5)")
    else:
        s_rec = summarize(rec_sub, "침체중")

    if small_n_norec:
        print(f"  [비침체] n={n_norec} < {MIN_N_FOR_STATS} — 집계 대신 개별 사례만 기록", flush=True)
        s_norec = {"n": n_norec}
    else:
        s_norec = summarize(norec_sub, "비침체")

    # H1 판정 (horizon_reversal_replication_study.py와 동일한 방향 체크 로직).
    # 소표본(n<5)이어도 기계적 체크 자체는 그대로 계산해 투명하게 공개한다 — 다만 그 결과를
    # "통계적으로 확정된 재현/미재현"이 아니라 "참고용, 취약함"으로 명시적으로 표시한다.
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
    h1_verdict = {"long_worse": long_worse, "short_not_worse": short_not_worse,
                  "shape_mechanically_replicated": bool(long_worse and short_not_worse),
                  "reference_only_small_n": small_n_rec or small_n_norec}
    print(f"\nH1 방향 체크(n<{MIN_N_FOR_STATS}이면 참고용): 장기(60/120)에 침체중이 더 나쁨={long_worse}, "
          f"단기(5/20) 중 최소 하나는 침체중이 안 나쁘거나 더 좋음(반전 여지)={short_not_worse}", flush=True)
    if small_n_rec:
        print("  ** 침체중 n=3이라 이 체크는 통계적 근거가 아니라 참고용/취약함으로만 취급할 것 **", flush=True)

    out_json = {
        "spread_range": [str(spread.index.min().date()), str(spread.index.max().date())],
        "spx_range": [str(idx.min().date()), str(idx.max().date())],
        "rolling_window_days": ROLLING_WINDOW,
        "percentile": PERCENTILE,
        "horizons": HORIZONS,
        "min_n_for_stats": MIN_N_FOR_STATS,
        "n_total": len(df),
        "n_recession": n_rec,
        "n_norecession": n_norec,
        "small_n_recession_cell": small_n_rec,
        "small_n_norecession_cell": small_n_norec,
        "summary_all": s_all,
        "summary_recession": s_rec,
        "summary_norecession": s_norec,
        "h1_verdict": h1_verdict,
        "events": df.to_dict(orient="records"),
        "recession_events": rec_sub.to_dict(orient="records"),
        "norecession_events": norec_sub.to_dict(orient="records"),
    }
    with open(f"{OUT_DIR}/credit_recession_horizon_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    print("\nDONE")


if __name__ == "__main__":
    main()
