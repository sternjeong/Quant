"""트랙H 캡스톤: 네 개 위기 게이지(VIX·장단기 금리역전·크레딧 스프레드·TED 은행간 자금조달
스트레스)를 하나의 "종합 대시보드"로 합쳐, 몇 개가 동시에 켜지는지(0~4개)에 따라 그 뒤
S&P500 순방향 수익률이 실제로 더 나빠지는지 검증한다.

이 프로젝트는 crisis_signal_overlap_study.py에서 VIX 급등과 크레딧 스트레스가 동시에 겹치면
VIX 단독보다 결과가 더 나쁘다는 걸 이미 확인했다(H2). 이번엔 그 발견이 "게이지 개수가 많을수록
점점 더 나빠진다"는 일반 법칙으로 확장되는지, 그리고 정말 3개 이상이 동시에 켜지는 "전부
빨간불" 순간이 역사적으로 얼마나 드문지 확인한다.

네 게이지 모두 이 프로젝트가 이미 검증한 정의를 그대로 재사용한다 — VIX&ge;30(그날 종가
기준, credit_confirmed_vix_recession_check.py의 겹침 확인 방식과 동일한 단순 레벨), T10Y2Y<0
(10거래일 연속 유지, yield_curve_event_study.py), BAA10Y가 직전3년 90퍼센타일 초과(10거래일
연속 유지, credit_spread_event_study.py), TED가 직전3년 90퍼센타일 초과(10거래일 연속 유지,
bank_funding_stress_study.py). TED가 2022-01-21 이후 데이터가 없으므로, 네 게이지를 모두 볼
수 있는 공통 구간(1990~2022-01-21)으로 분석 범위를 제한한다 — 이후 구간(2022년 긴축, 2023
지역은행위기, 2025 관세충격)은 이 대시보드로 볼 수 없다는 한계를 그대로 밝힌다.

"이벤트"를 세는 방식: 하루하루의 원(raw) 게이지 개수가 아니라, "같은 게이지 개수가 유지되는
최대 연속구간(에피소드)"의 시작일을 하나의 이벤트로 삼는다 — VIX가 40거래일 연속 30 이상을
유지했다고 그걸 40개의 독립 이벤트로 세지 않기 위함이다(사전등록 요구사항).

사전등록 가설(결과를 보기 전에 적어둔다):
  H1: 게이지 2개 이상이 동시에 켜진 에피소드는 정확히 1개만 켜진 에피소드보다 그 뒤 순방향
      수익률이 더 나쁠 것이다 — crisis_signal_overlap_study.py의 H2(크레딧까지 겹치면 VIX
      단독보다 나쁨) 발견이 게이지 수를 일반화해도 성립하는지 확인한다. 구체적으로 0→1→2→3→4개로
      갈수록 대체로 단조적으로(monotonic) 나빠질 것으로 예상하며, 실제로 단조성이 유지되는지
      아니면 어딘가에서 깨지는지 보고한다.
  H2: 각 게이지가 개별적으로도 드문 사건이므로, 3개 이상이 동시에 켜지는 "전부 빨간불" 순간은
      역사적으로 매우 드물 것이다(뚜렷이 구분되는 에피소드가 5개 미만일 것으로 예상). 정확한
      개수와 날짜(연속구간은 하나의 사건으로 묶어) 그대로 보고한다.
  H3(탐색적): H2에서 찾은 3개 이상 동시점등 에피소드들 사이에서도, 이 프로젝트가 이미 5번
      독립 확인한 "사건의 무서움보다 실제 시스템 붕괴 여부가 중요하다" 패턴(리먼=실제 붕괴 vs
      코로나=정책대응으로 시스템 유지)이 재현되는지 확인한다."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
HORIZONS = [5, 20, 60, 120]
ANALYSIS_START = "1990-01-01"
ANALYSIS_END = "2022-01-21"  # TED(TEDRATE) 최종 유효일 — 네 게이지 공통 구간

VIX_THRESHOLD = 30
CREDIT_ROLLING_WINDOW = 756
CREDIT_PERCENTILE = 0.90
CREDIT_MIN_PERSIST = 10
TED_ROLLING_WINDOW = 756
TED_PERCENTILE = 0.90
TED_MIN_PERSIST = 10
INV_MIN_PERSIST = 10


def detect_sustained_state(above: pd.Series, min_persist: int):
    """above: bool Series. 상태가 바뀐 뒤 min_persist거래일 연속 유지되면 그 시작일을 진짜
    전환으로 인정한다(이 프로젝트의 기존 스터디들과 동일 로직). "필터링된 상태" bool Series 반환."""
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


def main():
    print("VIX(VIXCLS) 조회 중...", flush=True)
    vix = fred_data.get_series("VIXCLS", start=ANALYSIS_START).dropna()
    print("T10Y2Y(장단기 금리차) 조회 중...", flush=True)
    spread10y2y = fred_data.get_series("T10Y2Y", start=ANALYSIS_START).dropna()
    print("BAA10Y(크레딧 스프레드) 조회 중...", flush=True)
    baa10y = fred_data.get_series("BAA10Y", start="1987-01-01", use_cache=False).dropna()  # 롤링윈도우용 여유
    print("TEDRATE(TED 스프레드) 조회 중...", flush=True)
    ted = fred_data.get_series("TEDRATE", start="1987-01-01", use_cache=False).dropna()

    print("S&P500(^GSPC) 조회 중...", flush=True)
    spx_hist = get_multiple_price_history(["^GSPC"], start="1989-01-01", end="2022-06-01", interval="1d")["^GSPC"]
    close = spx_hist["Close"]
    idx = close.index

    # ===== 게이지별 상태 계산 =====
    vix_state = (vix >= VIX_THRESHOLD)  # 단순 레벨(그날 종가 기준), 지속필터 없음

    inv_state = detect_sustained_state(spread10y2y < 0, INV_MIN_PERSIST)

    rolling_p90_credit = baa10y.shift(1).rolling(CREDIT_ROLLING_WINDOW).quantile(CREDIT_PERCENTILE)
    valid_from_credit = rolling_p90_credit.first_valid_index()
    above_credit = (baa10y > rolling_p90_credit).reindex(baa10y.index).fillna(False)
    above_credit = above_credit[baa10y.index >= valid_from_credit]
    credit_state = detect_sustained_state(above_credit, CREDIT_MIN_PERSIST)

    rolling_p90_ted = ted.shift(1).rolling(TED_ROLLING_WINDOW).quantile(TED_PERCENTILE)
    valid_from_ted = rolling_p90_ted.first_valid_index()
    above_ted = (ted > rolling_p90_ted).reindex(ted.index).fillna(False)
    above_ted = above_ted[ted.index >= valid_from_ted]
    ted_state = detect_sustained_state(above_ted, TED_MIN_PERSIST)

    # ===== 공통 거래일 인덱스(S&P500 기준)에 정렬(각 상태를 그 시점까지 알려진 값으로 ffill) =====
    common_start = max(pd.Timestamp(ANALYSIS_START), vix.index.min(), inv_state.index.min(),
                        credit_state.index.min(), ted_state.index.min())
    common_end = pd.Timestamp(ANALYSIS_END)
    trading_days = idx[(idx >= common_start) & (idx <= common_end)]
    print(f"\n분석 공통 구간: {trading_days.min().date()} ~ {trading_days.max().date()} ({len(trading_days)}거래일)", flush=True)

    def asof_series(state: pd.Series, days: pd.DatetimeIndex) -> pd.Series:
        s = state.reindex(state.index.union(days)).sort_index().ffill()
        return s.reindex(days).fillna(False).astype(bool)

    vix_al = asof_series(vix_state, trading_days)
    inv_al = asof_series(inv_state, trading_days)
    credit_al = asof_series(credit_state, trading_days)
    ted_al = asof_series(ted_state, trading_days)

    gauge_count = (vix_al.astype(int) + inv_al.astype(int) + credit_al.astype(int) + ted_al.astype(int))
    gauge_count.index = trading_days

    print("\n게이지 개수 분포(거래일 기준):", flush=True)
    print(gauge_count.value_counts().sort_index(), flush=True)

    # ===== 에피소드(같은 게이지 개수가 유지되는 최대 연속구간) 탐지 =====
    episodes = []
    n = len(gauge_count)
    i = 0
    while i < n:
        val = gauge_count.iloc[i]
        start_pos = i
        j = i
        while j + 1 < n and gauge_count.iloc[j + 1] == val:
            j += 1
        episodes.append({"gauge_count": int(val), "start_idx": start_pos, "end_idx": j,
                          "start_date": trading_days[start_pos], "end_date": trading_days[j],
                          "length_days": j - start_pos + 1})
        i = j + 1
    print(f"\n총 에피소드 수: {len(episodes)}건", flush=True)

    # ===== 각 에피소드 시작일 기준 순방향 수익률 =====
    for ep in episodes:
        pos = idx.searchsorted(ep["start_date"])
        if pos <= 0 or pos >= len(idx):
            for h in HORIZONS:
                ep[f"fwd_{h}d_pct"] = None
            continue
        day0_close = close.iloc[pos]
        for h in HORIZONS:
            fut_pos = pos + h
            ep[f"fwd_{h}d_pct"] = round(100 * (close.iloc[fut_pos] / day0_close - 1), 3) if fut_pos < len(idx) else None

    ep_df = pd.DataFrame(episodes)

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

    print("\n=== H1: 게이지 개수별 에피소드 순방향 수익률(에피소드 시작일 기준) ===", flush=True)
    summaries = {}
    for gc in [0, 1, 2, 3, 4]:
        sub = ep_df[ep_df["gauge_count"] == gc]
        summaries[str(gc)] = summarize(sub, f"게이지 {gc}개")

    # ===== H2: 3개 이상 동시점등 에피소드 =====
    print("\n=== H2: 게이지 3개 이상 동시점등 에피소드 ===", flush=True)
    high_eps = ep_df[ep_df["gauge_count"] >= 3].copy()
    print(f"3개 이상 에피소드: {len(high_eps)}건", flush=True)
    for _, r in high_eps.iterrows():
        print(f"  게이지{r['gauge_count']}개  {r['start_date'].date()} ~ {r['end_date'].date()} "
              f"({r['length_days']}거래일)  +60일={r.get('fwd_60d_pct')}%  +120일={r.get('fwd_120d_pct')}%", flush=True)

    out_json = {
        "analysis_range": {"start": str(trading_days.min().date()), "end": str(trading_days.max().date())},
        "gauge_count_distribution": gauge_count.value_counts().sort_index().to_dict(),
        "n_episodes_total": len(episodes),
        "summaries_by_gauge_count": summaries,
        "episodes_3plus": high_eps.assign(
            start_date=high_eps["start_date"].astype(str), end_date=high_eps["end_date"].astype(str)
        ).to_dict(orient="records"),
        "all_episodes": ep_df.assign(
            start_date=ep_df["start_date"].astype(str), end_date=ep_df["end_date"].astype(str)
        ).to_dict(orient="records"),
    }
    with open(f"{OUT_DIR}/four_gauge_dashboard_study.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2, default=str)
    print("\nDONE")


if __name__ == "__main__":
    main()
