"""트랙 H 후속 — 2023년 3월 지역은행 위기, 신용시장 렌즈로 다시 보기.

Track H(신용시장 스프레드 스터디)의 ROADMAP "다음 후보"에 오래 남아 있던 항목: 원래
계획했던 FRED BAMLH0A0HYM2(ICE BofA 하이일드 옵션조정스프레드)가 2026년 4월부터 "최근
3년치만" 제공되도록 정책이 바뀌어, 그 스터디는 대신 BAA10Y(전체 역사 제공)를 썼다. 그런데
그 3년치 창이 마침 2023년 3월 SVB(실리콘밸리은행)·시그니처은행 파산, 크레디트스위스-UBS
인수라는 지역은행 위기를 담고 있을 것으로 기대됐다 — 이 사건은 이미 이 프로젝트의 curated
shock 스터디(주식/자산군 레벨, `curated_shock_events.py`)에서 다뤘지만, 신용시장 자체의
반응은 아직 본 적이 없었다.

**데이터 가용 범위, 계산 전에 먼저 확인(중요한 발견)**: 2026-09-05 현재 FRED
BAMLH0A0HYM2를 직접 조회하면 가용 구간은 **2023-09-05 ~ 2026-09-03**이다. 이건 "최근 3년"이
오늘 날짜 기준으로 매일 굴러가는 rolling window라는 뜻이고, 결과적으로 **2023년 3월(SVB
위기)은 이미 이 창 밖으로 밀려나 하나도 안 남아 있다.** 이 프로젝트의 로컬 캐시 히스토리를
git으로 거슬러 올라가 봐도(2026-08-23 스터디 시점 캐시조차 2023-07-17이 최초 관측치) 이
시리즈가 이 프로젝트 내에서 단 한 번도 2023년 3월을 담아본 적이 없다는 것도 확인했다 — 즉
"3년치 창이 3월 위기를 담고 있다"는 미션의 전제 자체가 현재 시점에서는 성립하지 않는다.
이걸 조용히 넘기지 않고 그대로 보고한 뒤, Track H 본 스터디와 동일한 방식으로 **BAA10Y(무디스
Baa 회사채&minus;10년국채, 1986년부터 무제한 제공)로 대체**해서 이 미니 스터디를 진행한다.
정크본드보다 한 단계 높은 투자등급 스프레드라 절대 크기는 하이일드 스프레드보다 작게
움직이지만, 방향성 신호로는 이 프로젝트가 이미 여러 번 검증해서 쓰고 있는 지표다.

사전 등록 가설(계산 전에 적어둔다):
  H1: BAA10Y가 2023년 3월 지역은행 위기 구간(대략 2023-03-08 SVB 파산 ~ 2023-03-20
      크레디트스위스-UBS 인수)에서 "진짜, 감지 가능한" 벌어짐을 보인다. 이걸 절대 bp
      크기가 아니라 상대적 크기(위기 전 기준선 대비 %증가, 그리고 BAA10Y 자체의 34년
      역사 안에서 이 구간 고점이 몇 퍼센타일에 해당하는지)로 따져서, 이 프로젝트가 이미
      본 다른 위기(2008/2020)의 BAA10Y 기반 벌어짐과 "상대적으로" 비교할 만한 크기인지
      확인한다(절대 수준 자체가 다른 스프레드 시리즈라 절대 bp 비교는 하지 않는다).
  H2: 이 신용 스프레드의 벌어짐이, 이 프로젝트의 메모에 이미 정리된 이 사건의 유명한
      주식시장 스트레스 날짜들(SVB 파산 2023-03-10, 시그니처은행 폐쇄 주말 이후 2023-03-13,
      크레디트스위스-UBS 인수 발표 주말 이후 2023-03-20 전후)보다 먼저 움직였는지, 같이
      움직였는지, 늦게 움직였는지를 본다 — "신용시장 신호가 실제로 주식시장 패닉보다
      일찍/동시에/늦게 나타나는가"라는 좁은 질문이며, Track H 본 스터디의 전체 시차
      분포 스터디와는 다른, 이 사건 하나에 대한 타이밍 확인이다.
  H3(탐색적, 이 프로젝트의 "사건이 무서워 보였는가보다 시스템이 실제로 무너졌는가가
      중요하다"는, 이미 6번 독립 재현된 패턴과 연결): 2023년 3월이 결국 "당국 개입(FDIC
      전액보증, 연준 BTFP 신설, UBS의 CS 인수)으로 더 큰 은행 시스템 붕괴를 막은, 봉쇄된
      해프닝"이었는지, 아니면 신용시장 데이터가 더 깊은 위기의 징후를 보였는지를 신용
      데이터 자체로 살펴본다. 그리고 패닉의 최저점(주식시장 기준)에서부터의 60거래일
      순방향 수익률이, 이 프로젝트가 이미 정리해둔 "봉쇄된 해프닝, 강한 반등"
      사례들(LTCM 1998, 코로나 2020, +120일 기준 +15~32%)과 "진짜 시스템 붕괴, 약한/없는
      반등" 사례(리먼 2008, +120일 &minus;43.3%)중 어느 쪽에 더 가까운지 비교한다.

방법론: Track H 본 스터디와 동일한 절대 임계값(3.0%p)·적응형 임계값(직전3년 90퍼센타일)을
그대로 재사용해서 2023년 3월 구간이 그 기준을 실제로 넘었는지도 확인한다(넘지 않았다면
그 자체가 "본 스터디의 이벤트 탐지 기준으로는 이 사건이 잡히지 않았다"는 중요한 사실이다).
S&P500(^GSPC) 일별 종가로 이 프로젝트의 curated shock 스터디가 이미 확정해 둔 이벤트 데이터
(`curated_shock_events.json`, 2023-03-10, SVB 파산일 기준 +60일 +10.94%)를 재사용하고,
패닉 최저 종가일(위기 구간 안에서 종가 최저인 날)을 새로 찾아 그날 기준 순방향 수익률도
따로 계산한다(H3에서 요구하는 "패닉의 최악의 날" 기준)."""
import sys
sys.path.insert(0, "/workspaces/Quant")

import json

import pandas as pd

from core import fred_data
from core.market_data import get_multiple_price_history

OUT_DIR = "/workspaces/Quant/analysis/macro_event_study_2026-08-21"
FIXED_THRESHOLD_PP = 3.0
ROLLING_WINDOW = 756
PERCENTILE = 0.90

CRISIS_START = "2023-03-08"   # SVB 모회사 실버게이트 청산·SVB 주가 폭락 시작 전날 기준선
CRISIS_END = "2023-03-23"     # 크레디트스위스-UBS 인수 이후 스프레드 고점까지
WINDOW_START = "2023-02-01"
WINDOW_END = "2023-04-15"

EQUITY_DATES = {
    "SVB 파산·당국 인수 (금요일)": "2023-03-10",
    "시그니처은행 폐쇄 주말 이후 첫 거래일": "2023-03-13",
    "크레디트스위스-UBS 인수 발표 이후 첫 거래일": "2023-03-20",
}


def main():
    baa = fred_data.get_series("BAA10Y").dropna()
    hy = fred_data.get_series("BAMLH0A0HYM2").dropna()

    hy_range = {"start": str(hy.index.min().date()), "end": str(hy.index.max().date())}
    covers_march_2023 = hy.index.min() <= pd.Timestamp("2023-03-08")

    px = get_multiple_price_history(["^GSPC"], start="2023-01-01", end="2023-08-01")
    sp = px["^GSPC"]["Close"]

    # H1 -----------------------------------------------------------------
    window = baa.loc[WINDOW_START:WINDOW_END]
    pre_baseline = baa.loc[CRISIS_START]
    crisis_peak = baa.loc[CRISIS_START:CRISIS_END].max()
    crisis_peak_date = baa.loc[CRISIS_START:CRISIS_END].idxmax()
    rel_widen_pct = round(100 * (crisis_peak / pre_baseline - 1), 1)

    full_hist_percentile = round(100 * (baa < crisis_peak).mean(), 1)

    roll_p90 = baa.rolling(ROLLING_WINDOW, min_periods=500).quantile(PERCENTILE)
    adaptive_crossed = bool((baa.loc[CRISIS_START:CRISIS_END] > roll_p90.loc[CRISIS_START:CRISIS_END]).any())
    fixed_crossed = bool((baa.loc[CRISIS_START:CRISIS_END] > FIXED_THRESHOLD_PP).any())

    # 비교용: 2008 / 2020 상대적 벌어짐(같은 방식으로 재계산, BAA10Y 기준)
    base_2008 = baa.loc["2007-06-01":"2007-07-01"].mean()
    peak_2008 = baa.loc["2008-10-01":"2008-12-31"].max()
    rel_2008 = round(100 * (peak_2008 / base_2008 - 1), 1)

    base_2020 = baa.loc["2020-01-01":"2020-02-15"].mean()
    peak_2020 = baa.loc["2020-03-01":"2020-04-15"].max()
    rel_2020 = round(100 * (peak_2020 / base_2020 - 1), 1)

    h1 = {
        "pre_crisis_baseline_pct": float(pre_baseline),
        "crisis_peak_pct": float(crisis_peak),
        "crisis_peak_date": str(crisis_peak_date.date()),
        "relative_widening_pct": rel_widen_pct,
        "full_history_percentile_of_peak": full_hist_percentile,
        "adaptive_90pct_threshold_crossed": adaptive_crossed,
        "fixed_3.0pp_threshold_crossed": fixed_crossed,
        "comparison_2008_relative_widening_pct": rel_2008,
        "comparison_2020_relative_widening_pct": rel_2020,
    }

    # H2 -------------------------------------------------------------------
    daily_baa = window.reindex(pd.date_range(WINDOW_START, WINDOW_END, freq="B")).ffill()
    timeline = []
    for label, date in EQUITY_DATES.items():
        d = pd.Timestamp(date)
        prev_trading = baa.index[baa.index.get_indexer([d], method="pad")[0]]
        timeline.append({
            "equity_event": label,
            "date": date,
            "baa10y_on_date": float(baa.loc[prev_trading]),
            "baa10y_prior_trading_day": float(baa.loc[baa.index[baa.index.get_loc(prev_trading) - 1]]),
        })

    # H3 -------------------------------------------------------------------
    panic_window = sp.loc[CRISIS_START:CRISIS_END]
    trough_date = panic_window.idxmin()
    trough_close = panic_window.min()
    idx = sp.index
    pos = idx.get_loc(trough_date)
    fwd_from_trough = {}
    for h in [5, 20, 60, 120]:
        if pos + h < len(idx):
            fwd_from_trough[f"fwd_{h}d_pct"] = round(100 * (sp.iloc[pos + h] / trough_close - 1), 2)

    with open(f"{OUT_DIR}/curated_shock_events.json") as f:
        curated = json.load(f)
    svb_curated = next(r for r in curated if r["date"] == "2023-03-10")

    h3 = {
        "panic_trough_date": str(trough_date.date()),
        "panic_trough_close": float(trough_close),
        "fwd_returns_from_trough_pct": fwd_from_trough,
        "svb_curated_event_fwd_60d_pct": svb_curated["fwd_60d_pct"],
        "comparison_ltcm_covid_120d_pct_range": "+15% ~ +32%",
        "comparison_lehman_120d_pct": -43.3,
    }

    result = {
        "hy_oas_available_range": hy_range,
        "hy_oas_covers_march_2023": covers_march_2023,
        "h1": h1,
        "h2_timeline": timeline,
        "h3": h3,
    }
    with open(f"{OUT_DIR}/regional_bank_crisis_2023_study.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
