"""H15 - 2021년 말~2022년 초 성장주 언와인드 사례 검증.

배경: 2021-11 무렵부터 고성장/고모멘텀 개별주가 SPY 자체보다 몇 달 먼저 무너지기 시작했다(SPY는
2022-01 초까지 사상최고치 부근). 이게 정확히 작업34/H12가 스스로 경고한 "SPY는 멀쩡한데 새틀라이트
풀만 무너지는" 시나리오의 실제 사례인지, 그리고 있다면 SPY 스위치가 반응하기 전까지 새틀라이트가
실제로 얼마나 피를 흘렸는지, H14의 풀breadth 신호가 더 빨리 반응했는지를 실제 point-in-time 데이터로
검증한다.

재사용: H10의 core_ret_net.csv/sat_trend_ret_net.csv(추세추종 새틀라이트, 반기 정적보유),
h10_results.json의 rebal_log(2021-07-01/2022-01-03 리밸런싱 종목), H12의 full2022_weight_series.csv
(SPY 200일선 스위치의 실제 적용 비중 시계열), H14가 이번 라운드에서 새로 계산한
full_breadth_bull.csv(풀breadth 신호)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

MAIN_CHECKOUT = "/workspaces/Quant"
PRIOR_H10_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test"
PRIOR_H12_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch"
OUT_DIR = Path(__file__).resolve().parent

WINDOW_START, WINDOW_END = "2021-09-01", "2022-03-31"


def log(msg):
    print(f"[h15] {msg}", flush=True)


def main():
    core_ret = pd.read_csv(PRIOR_H10_DIR / "core_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_ret = pd.read_csv(PRIOR_H10_DIR / "sat_trend_ret_net.csv", index_col=0, parse_dates=True).iloc[:, 0]
    spy_weight = pd.read_csv(PRIOR_H12_DIR / "full2022_weight_series.csv", index_col=0, parse_dates=True).iloc[:, 0]
    breadth_bull = pd.read_csv(OUT_DIR / "full_breadth_bull.csv", index_col=0, parse_dates=True).iloc[:, 0].astype(bool)
    breadth = pd.read_csv(OUT_DIR / "full_pool_breadth.csv", index_col=0, parse_dates=True).iloc[:, 0]

    h10 = json.loads((PRIOR_H10_DIR / "h10_results.json").read_text(encoding="utf-8"))
    rebal_log = h10["satellite_trend_following"]["rebal_log"]
    picks_2021h2 = next(r for r in rebal_log if r["date"] == "2021-07-01")
    picks_2022h1 = next(r for r in rebal_log if r["date"] == "2022-01-03")
    log(f"2021-07-01 리밸런싱 보유종목: {picks_2021h2['picks']}")
    log(f"2022-01-03 리밸런싱 보유종목: {picks_2022h1['picks']}")

    win = (slice(WINDOW_START, WINDOW_END),)
    sat_win = sat_ret[(sat_ret.index >= WINDOW_START) & (sat_ret.index <= WINDOW_END)]
    core_win = core_ret[(core_ret.index >= WINDOW_START) & (core_ret.index <= WINDOW_END)]
    spy_w_win = spy_weight[(spy_weight.index >= WINDOW_START) & (spy_weight.index <= WINDOW_END)]
    breadth_bull_win = breadth_bull[(breadth_bull.index >= WINDOW_START) & (breadth_bull.index <= WINDOW_END)]
    breadth_win = breadth[(breadth.index >= WINDOW_START) & (breadth.index <= WINDOW_END)]

    # SPY 스위치가 처음으로 0으로 꺼진 날짜 (윈도우 내)
    spy_off = spy_w_win[spy_w_win == 0.0]
    spy_first_off = spy_off.index[0] if len(spy_off) > 0 else None
    log(f"SPY 스위치 첫 OFF(윈도우 내): {spy_first_off.date() if spy_first_off is not None else '없음(윈도우 내내 ON)'}")

    # breadth 스위치가 처음으로 꺼진 날짜(윈도우 내)
    breadth_off = breadth_bull_win[~breadth_bull_win]
    breadth_first_off = breadth_off.index[0] if len(breadth_off) > 0 else None
    log(f"풀breadth 스위치 첫 OFF(윈도우 내): {breadth_first_off.date() if breadth_first_off is not None else '없음(윈도우 내내 ON)'}")

    # 새틀라이트 슬리브 실현 누적수익률/낙폭 시계열(윈도우 전체, 기준일=윈도우 시작)
    sat_eq = (1 + sat_win.fillna(0.0)).cumprod()
    sat_peak = sat_eq.cummax()
    sat_dd = sat_eq / sat_peak - 1.0
    sat_trough_date = sat_dd.idxmin()
    sat_trough_dd = float(sat_dd.min())
    # 주의: sat_eq.idxmax()는 윈도우 전체 기간의 글로벌 최고점을 주는데, 이 윈도우는 새틀라이트가
    # 2022-01-03 리밸런싱으로 TSLA/NVDA에서 COP/PLD/GOOGL(비성장주)로 갈아탄 이후(2022-03-25)에
    # 오히려 최고점을 찍는다 - 그건 "성장주 언와인드 직전 고점"이 아니다. 여기서 필요한 건 트로프
    # 직전까지의 러닝피크(=sat_peak가 이미 트로프 시점에 갖고 있는 값)가 실제로 언제 찍혔는지다.
    peak_value_at_trough = sat_peak.loc[sat_trough_date]
    sat_peak_date = sat_eq.loc[:sat_trough_date].idxmax()
    log(f"새틀라이트 윈도우 내 피크: {sat_peak_date.date()} (누적 {sat_eq.loc[sat_peak_date]:.4f}), "
        f"저점: {sat_trough_date.date()} (낙폭 {sat_trough_dd*100:.2f}%)")

    def cum_ret_between(ret: pd.Series, a, b) -> float:
        s = ret[(ret.index > a) & (ret.index <= b)]
        return float((1 + s.fillna(0.0)).prod() - 1.0)

    # SPY 스위치가 반응하기 전까지(피크~SPY첫OFF) 새틀라이트가 이미 입은 손실
    gap_result = {}
    if spy_first_off is not None:
        gap_ret_sat = cum_ret_between(sat_ret, sat_peak_date, spy_first_off)
        gap_days = len(sat_ret[(sat_ret.index > sat_peak_date) & (sat_ret.index <= spy_first_off)])
        # 낙폭 대비 진행률: SPY off 시점까지 발생한 낙폭 / 윈도우 저점까지의 최종낙폭
        dd_at_spy_off = float(sat_dd.get(spy_first_off, sat_dd.reindex([spy_first_off]).ffill().iloc[0] if spy_first_off in sat_dd.index else float('nan')))
        pct_of_final_dd_already_happened = (dd_at_spy_off / sat_trough_dd * 100.0) if sat_trough_dd != 0 else None
        gap_result = {
            "peak_date": str(sat_peak_date.date()),
            "spy_switch_off_date": str(spy_first_off.date()),
            "trading_days_from_peak_to_spy_off": gap_days,
            "satellite_cum_return_peak_to_spy_off_pct": round(gap_ret_sat * 100, 2),
            "satellite_drawdown_at_spy_off_pct": round(dd_at_spy_off * 100, 2),
            "satellite_final_window_trough_dd_pct": round(sat_trough_dd * 100, 2),
            "pct_of_final_dd_already_happened_by_spy_off": round(pct_of_final_dd_already_happened, 1) if pct_of_final_dd_already_happened is not None else None,
        }
        log(f"갭 분석: 피크({sat_peak_date.date()}) -> SPY 첫OFF({spy_first_off.date()}) 사이 "
            f"{gap_days}거래일 동안 새틀라이트 누적수익률 {gap_ret_sat*100:.2f}%, "
            f"그 시점 낙폭 {dd_at_spy_off*100:.2f}% (최종 윈도우 저점낙폭의 {pct_of_final_dd_already_happened:.1f}%)")
    else:
        log("경고: 윈도우 내에서 SPY 스위치가 한 번도 꺼지지 않음")

    breadth_gap_result = {}
    if breadth_first_off is not None:
        gap_ret_breadth = cum_ret_between(sat_ret, sat_peak_date, breadth_first_off)
        gap_days_b = len(sat_ret[(sat_ret.index > sat_peak_date) & (sat_ret.index <= breadth_first_off)])
        dd_at_breadth_off = float(sat_dd.get(breadth_first_off, float('nan')))
        breadth_gap_result = {
            "breadth_switch_off_date": str(breadth_first_off.date()),
            "trading_days_from_peak_to_breadth_off": gap_days_b,
            "satellite_cum_return_peak_to_breadth_off_pct": round(gap_ret_breadth * 100, 2),
            "satellite_drawdown_at_breadth_off_pct": round(dd_at_breadth_off * 100, 2),
        }
        if spy_first_off is not None:
            lead_days = (spy_first_off - breadth_first_off).days
            breadth_gap_result["breadth_leads_spy_by_calendar_days"] = int(lead_days)
            log(f"풀breadth가 SPY보다 {lead_days}일 {'먼저' if lead_days>0 else '늦게'} 꺼짐 "
                f"(breadth {breadth_first_off.date()} vs SPY {spy_first_off.date()})")
    else:
        log("풀breadth 스위치도 윈도우 내내 꺼지지 않음 - SPY와 마찬가지로 이 사례를 못 잡음")

    result = {
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "satellite_holdings": {
            "2021-07-01_to_2022-01-02": picks_2021h2["picks"],
            "2022-01-03_to_2022-06-30": picks_2022h1["picks"],
        },
        "spy_switch_gap": gap_result,
        "breadth_switch_gap": breadth_gap_result,
        "pool_breadth_series_window": {str(k.date()): (None if pd.isna(v) else round(float(v), 4)) for k, v in breadth_win.items()},
        "satellite_drawdown_series_window": {str(k.date()): round(float(v), 4) for k, v in sat_dd.items()},
        "satellite_daily_return_series_window": {str(k.date()): round(float(v), 5) for k, v in sat_win.items()},
    }
    with open(OUT_DIR / "h15_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR / 'h15_results.json'}")


if __name__ == "__main__":
    main()
