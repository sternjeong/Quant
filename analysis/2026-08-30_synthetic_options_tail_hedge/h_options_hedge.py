"""새틀라이트 슬리브를 위한 합성 옵션 기반 테일 리스크 헤지 (프로텍티브 풋 / 칼라).

배경(작업33~38): 코어 챔피언 위에 얹은 개별주 새틀라이트 슬리브(15% 비중)를 보호하기 위해
SPY-200일선 스위치, VIX 기반 신속 스위치, 둘의 하이브리드까지 시도했지만 셋 다 "추세를 감지한
뒤" 반응하는 후행 지표라 COVID형 급락(5주 -34%)에서는 구조적으로 늦어 오히려 코어단독/무대응보다
성과가 나빴다(h21_results.json: covid_2020 core_alone 샤프 +0.13 vs hybrid -0.18, MDD -6.71% vs
-7.42%). 이번 라운드는 "감지"가 필요 없는 도구, 즉 사전에 정의된 페이오프를 갖는 옵션 헤지를
시도한다: 매달 롤링하는 합성 프로텍티브 풋(또는 콜 매도로 프리미엄을 일부 상쇄하는 칼라)을
SPY에 붙여 새틀라이트 비중(15%)에 해당하는 노셔널을 방어한다.

왜 SPY 기초자산인가 (새틀라이트 바스켓 자체가 아니라):
  - 새틀라이트는 반기 리밸런싱되는 3종목 바스켓이라 종목 자체에 상장옵션이 없거나 유동성이
    부족한 경우가 흔하고, 종목이 바뀔 때마다 바스켓 옵션을 새로 설계해야 해 비현실적이다.
  - 실전에서 포트폴리오 레벨 테일 리스크를 옵션으로 방어하려는 사람은 거의 항상 SPY/SPX
    옵션처럼 유동성이 큰 지수 상품을 쓴다 - 새틀라이트가 개별주 강세장 베타가 크다는 특성상
    시장 전체가 급락할 때 함께 무너지는 상관관계가 높으므로(이번 COVID/2008 사례가 정확히 이
    "동반 급락" 케이스), 지수 풋이 합리적인 대리 헤지(proxy hedge)다.
  - 노셔널은 포트폴리오의 새틀라이트 비중(15%)만큼만 SPY 풋으로 방어한다(전체 포트폴리오가
    아니라 "위기 시 감지 없이 새틀라이트를 보호"하는 것이 목표이므로).

합성 가격결정 모형(Black-Scholes, 명시적 가정):
  - 기초자산가격 S: SPY 종가.
  - 내재변동성 sigma: VIX 종가(연율화 %)를 100으로 나눈 값을 그대로 사용 - 실제 SPY 옵션의
    내재변동성 대리치로 흔히 쓰이는 방법(VIX 자체가 S&P500 30일 내재변동성 지수). 스마일/스큐,
    만기별 텀 구조는 반영하지 않는다(한계 섹션에서 명시).
  - 무위험금리 r: FRED FEDFUNDS(실효 연방기금금리) 캐시를 롤 시점 최근값으로 사용.
  - 만기 T: 21거래일(~1개월, 매월 첫 거래일 롤). 이 저장소의 새틀라이트 반기 리밸런싱보다
    빈번하지만, 실제 상장옵션의 표준 만기 주기(월물)에 맞춘 현실적 선택.
  - 행사가 K: 풋은 모네니스(moneyness) 파라미터로 조절(기본 ATM=1.00, 민감도 체크로 5% OTM=0.95).
    칼라의 콜은 기본 5% OTM(1.05).
  - 프리미엄 인식: 매 롤 시점(월초)에 프리미엄을 새틀라이트 노셔널(포트폴리오의 15%) 기준
    비율로 그날 하루의 초과수익률로 차감(풋 매수=차감, 콜 매도=가산)한다. 페이오프는 만기일
    (다음 롤 직전 거래일)에 하루짜리 수익률로 인식한다 - 옵션의 일일 마크투마켓(델타/감마 변화)은
    추적하지 않는 단순화(한계 섹션에서 명시). 이렇게 하면 "옵션은 실제로 돈이 드는 보험"이라는
    경제성(평상시 프리미엄 드래그, 위기시 페이오프)은 그대로 반영되면서 계산이 크게 단순해진다.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))

import math

import numpy as np
import pandas as pd


class _NormCDF:
    """scipy 미설치 환경 대응 - 표준정규 누적분포함수를 math.erf로 직접 구현(정확한 폐형식,
    근사가 아님: Phi(x) = 0.5*(1+erf(x/sqrt(2))))."""

    @staticmethod
    def cdf(x):
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


norm = _NormCDF()

from champion_strategy import COST_BPS_PER_SIDE
from h1_core_satellite import blend_returns
from h12_regime_switch import blend_returns_time_varying, perf_metrics_slice
from core.backtest_engine import calculate_metrics, _first_trading_day_of_month_mask
from core.market_data import get_price_history
from core.market_regime import VIX_TICKER

H20_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_vix_fast_crash_signal_and_hybrid_switch"
OUT_DIR = Path(__file__).resolve().parent

SATELLITE_WEIGHT = 0.15
TENOR_DAYS = 21          # 약 1개월(거래일 기준), 표준 월물 만기 근사
DEFAULT_R = 0.02         # FEDFUNDS 로드 실패 시 폴백
FALLBACK_VOL = 0.20      # VIX 결측 시 폴백(연 20%, 장기 평균 근사)

EPISODE_ORDER = ["gfc_2008", "correction_2015_2016", "selloff_2018", "bear_2022", "covid_2020", "full_2019_2026"]


def log(msg):
    print(f"[hedge] {msg}", flush=True)


def load_h20_series() -> dict:
    with open(H20_DIR / "h20_series_cache.pkl", "rb") as f:
        return pickle.load(f)


def load_h20_results() -> dict:
    return json.loads((H20_DIR / "h20_results.json").read_text(encoding="utf-8"))


def load_h21_results() -> dict:
    return json.loads((H20_DIR / "h21_results.json").read_text(encoding="utf-8"))


def load_fedfunds() -> pd.Series:
    df = pd.read_csv(Path(MAIN_CHECKOUT) / "data/cache/fred_FEDFUNDS.csv", parse_dates=[0], index_col=0)
    s = df.iloc[:, 0].astype(float) / 100.0
    s = s.sort_index()
    return s


def bs_put_price(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_call_price(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)


def fetch_spy_vix(start: str, end: str, warmup_days: int = 60) -> pd.DataFrame:
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).date().isoformat()
    spy = get_price_history("SPY", start=fetch_start, end=end, interval="1d")["Close"]
    vix = get_price_history(VIX_TICKER, start=fetch_start, end=end, interval="1d")["Close"]
    df = pd.DataFrame({"spy": spy}).join(pd.DataFrame({"vix": vix}), how="left")
    df["vix"] = df["vix"].ffill()
    return df


def build_option_overlay_returns(trading_index: pd.DatetimeIndex, start: str, end: str,
                                  put_moneyness: float, mode: str, call_moneyness: float = 1.05,
                                  tenor_days: int = TENOR_DAYS) -> dict:
    """월별 롤링 합성 풋(mode='put') 또는 칼라(mode='collar') 오버레이의 일별 수익률(오버레이분만,
    새틀라이트 비중 곱하기 전 '옵션 자체의 기초자산 대비 수익률')을 만든다.
    반환: overlay_ret(트레이딩 인덱스 정렬, 기초자산 100% 노셔널 기준), roll_log(진단용)."""
    px = fetch_spy_vix(start, end)
    px = px.reindex(trading_index).ffill()
    fedfunds = load_fedfunds()

    roll_mask = _first_trading_day_of_month_mask(trading_index)
    roll_dates = list(trading_index[roll_mask])
    if len(roll_dates) == 0 or roll_dates[0] != trading_index[0]:
        roll_dates = [trading_index[0]] + roll_dates

    overlay_ret = pd.Series(0.0, index=trading_index)
    roll_log = []
    for i, rd in enumerate(roll_dates):
        pos = trading_index.get_loc(rd)
        exp_pos = min(pos + tenor_days, len(trading_index) - 1)
        expiry = trading_index[exp_pos]
        S0 = float(px.loc[rd, "spy"])
        vix0 = px.loc[rd, "vix"]
        sigma = float(vix0) / 100.0 if pd.notna(vix0) else FALLBACK_VOL
        try:
            r = float(fedfunds.asof(rd))
            if pd.isna(r):
                r = DEFAULT_R
        except Exception:
            r = DEFAULT_R
        T = tenor_days / 252.0
        K_put = S0 * put_moneyness
        put0 = bs_put_price(S0, K_put, T, r, sigma)
        S_T = float(px.loc[expiry, "spy"])
        put_payoff = max(K_put - S_T, 0.0)

        premium_pct_debit = -put0 / S0
        payoff_pct_credit = put_payoff / S0

        if mode == "collar":
            K_call = S0 * call_moneyness
            call0 = bs_call_price(S0, K_call, T, r, sigma)
            call_payoff = max(S_T - K_call, 0.0)
            premium_pct_debit += call0 / S0          # 콜 매도로 프리미엄 수취(가산)
            payoff_pct_credit -= call_payoff / S0     # 콜이 ITM으로 만기되면 손실(차감)

        overlay_ret.loc[rd] += premium_pct_debit
        overlay_ret.loc[expiry] += payoff_pct_credit
        roll_log.append({
            "roll_date": str(rd.date()), "expiry_date": str(expiry.date()),
            "S0": round(S0, 2), "S_T": round(S_T, 2), "vix0": round(float(vix0), 2) if pd.notna(vix0) else None,
            "sigma": round(sigma, 4), "r": round(r, 4), "K_put": round(K_put, 2),
            "put_premium_pct": round(put0 / S0, 5),
            "net_premium_pct_debit": round(premium_pct_debit, 5),
            "payoff_pct_credit": round(payoff_pct_credit, 5),
        })
    return {"overlay_ret": overlay_ret, "roll_log": roll_log}


def metrics_from_ret(ret: pd.Series) -> dict:
    eq = (1 + ret.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    return calculate_metrics(eq, [], eq.index[0], eq.index[-1])


def run_episode(label: str, series: dict, put_moneyness: float, call_moneyness: float) -> dict:
    ep = series[label]
    core_ret = ep["_core_ret"]
    sat_ret = ep["_sat_realtime_ret"]
    trading_index = core_ret.index
    start, end = str(trading_index[0].date()), str(trading_index[-1].date())

    log(f"{label}: 옵션 오버레이 계산 ({start}~{end}, {len(trading_index)}거래일)")
    put_overlay = build_option_overlay_returns(trading_index, start, end, put_moneyness, mode="put")
    collar_overlay = build_option_overlay_returns(trading_index, start, end, put_moneyness, mode="collar",
                                                   call_moneyness=call_moneyness)

    # 새틀라이트 수익률에 옵션 오버레이를 얹는다: 오버레이는 SPY 100% 노셔널 기준이므로
    # 새틀라이트 비중(SATELLITE_WEIGHT)에 해당하는 노셔널만 방어한다고 보고, 오버레이 수익률에
    # SATELLITE_WEIGHT를 곱해 코어+새틀라이트 블렌드에 그대로 더한다(포트폴리오 레벨 오버레이).
    put_overlay_scaled, _ = put_overlay["overlay_ret"].align(core_ret, join="right", fill_value=0.0)
    collar_overlay_scaled, _ = collar_overlay["overlay_ret"].align(core_ret, join="right", fill_value=0.0)

    unhedged_blend = blend_returns(core_ret, sat_ret, SATELLITE_WEIGHT)
    put_hedged_blend = unhedged_blend + SATELLITE_WEIGHT * put_overlay_scaled
    collar_hedged_blend = unhedged_blend + SATELLITE_WEIGHT * collar_overlay_scaled

    return {
        "core_ret": core_ret, "sat_ret": sat_ret,
        "unhedged_blend": unhedged_blend, "put_hedged_blend": put_hedged_blend, "collar_hedged_blend": collar_hedged_blend,
        "put_roll_log": put_overlay["roll_log"], "collar_roll_log": collar_overlay["roll_log"],
    }


def summarize(ep_returns: dict, window: tuple, hybrid_blend: pd.Series = None) -> dict:
    ws, we = window
    row = {
        "core_alone": perf_metrics_slice(ep_returns["core_ret"], ws, we),
        "unhedged_satellite": perf_metrics_slice(ep_returns["unhedged_blend"], ws, we),
        "protective_put": perf_metrics_slice(ep_returns["put_hedged_blend"], ws, we),
        "collar": perf_metrics_slice(ep_returns["collar_hedged_blend"], ws, we),
    }
    if hybrid_blend is not None:
        row["trend_hybrid_switch"] = perf_metrics_slice(hybrid_blend, ws, we)
    return row


def main(put_moneyness: float = 1.00, call_moneyness: float = 1.05, tag: str = "main"):
    series = load_h20_series()
    h20 = load_h20_results()

    per_episode = {}
    for label in EPISODE_ORDER:
        ep_series = series[label]
        core_ret = ep_series["_core_ret"]
        sat_ret = ep_series["_sat_realtime_ret"]
        spy_w = ep_series["_spy_weight"]
        vix_w = ep_series["_vix_weight"]

        ep_returns = run_episode(label, series, put_moneyness, call_moneyness)

        # 하이브리드(작업38 최선 트렌드 메커니즘) 블렌드 재구성 - h21 로직 그대로 재사용
        spy_a, vix_a = spy_w.align(vix_w, join="inner")
        hybrid_on = (spy_a > 0) & (vix_a > 0)
        hybrid_w = hybrid_on.astype(float) * SATELLITE_WEIGHT
        hybrid_blend = blend_returns_time_varying(core_ret, sat_ret, hybrid_w)

        h20_ep = h20["episodes"][label]
        crisis_start, crisis_end = h20_ep["crisis_window"]
        full_start, full_end = h20_ep["full_period"]
        wkey = "full_period" if label == "full_2019_2026" else "crisis_window"

        table_full = summarize(ep_returns, (full_start, full_end), hybrid_blend)
        table_crisis = summarize(ep_returns, (crisis_start, crisis_end), hybrid_blend) if wkey == "crisis_window" else None

        put_prem_paid = sum(r["net_premium_pct_debit"] for r in ep_returns["put_roll_log"] if r["net_premium_pct_debit"] < 0)
        put_payoff_recv = sum(r["payoff_pct_credit"] for r in ep_returns["put_roll_log"])
        collar_prem_net = sum(r["net_premium_pct_debit"] for r in ep_returns["collar_roll_log"])
        collar_payoff_net = sum(r["payoff_pct_credit"] for r in ep_returns["collar_roll_log"])

        per_episode[label] = {
            "window_used": wkey, "full_period": [full_start, full_end], "crisis_window": [crisis_start, crisis_end],
            "table_full_period": table_full, "table_crisis_window": table_crisis,
            "n_option_rolls": len(ep_returns["put_roll_log"]),
            "put_cumulative_premium_paid_pct": round(put_prem_paid * 100, 3),
            "put_cumulative_payoff_received_pct": round(put_payoff_recv * 100, 3),
            "put_net_pnl_pct_of_notional": round((put_prem_paid + put_payoff_recv) * 100, 3),
            "collar_net_premium_pct": round(collar_prem_net * 100, 3),
            "collar_net_payoff_pct": round(collar_payoff_net * 100, 3),
            "collar_net_pnl_pct_of_notional": round((collar_prem_net + collar_payoff_net) * 100, 3),
        }
        wsum = table_crisis if wkey == "crisis_window" else table_full
        log(f"{label} [{wkey}]: core={wsum['core_alone']['sharpe']:.2f} unhedged={wsum['unhedged_satellite']['sharpe']:.2f} "
            f"put={wsum['protective_put']['sharpe']:.2f} collar={wsum['collar']['sharpe']:.2f} hybrid={wsum['trend_hybrid_switch']['sharpe']:.2f}")

    summary_rows = []
    for label in EPISODE_ORDER:
        ep = per_episode[label]
        w = ep["table_crisis_window"] if ep["window_used"] == "crisis_window" else ep["table_full_period"]
        row = {"episode": label, "window_used": ep["window_used"]}
        for cfg in ["core_alone", "unhedged_satellite", "protective_put", "collar", "trend_hybrid_switch"]:
            m = w[cfg]
            row[cfg] = {"cagr": m.get("cagr"), "mdd": m.get("mdd"), "sharpe": m.get("sharpe"), "calmar": m.get("calmar")}
        summary_rows.append(row)

    result = {
        "meta": {
            "satellite_weight": SATELLITE_WEIGHT, "tenor_days": TENOR_DAYS,
            "put_moneyness": put_moneyness, "call_moneyness": call_moneyness,
            "vol_source": "VIX close / 100 (implied-vol proxy)", "rate_source": "FRED FEDFUNDS (effective fed funds, daily asof)",
            "episode_order": EPISODE_ORDER, "tag": tag,
        },
        "episodes": per_episode,
        "summary_table": summary_rows,
    }
    out_path = OUT_DIR / f"h_options_results_{tag}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {out_path}")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--put-moneyness", type=float, default=1.00)
    ap.add_argument("--call-moneyness", type=float, default=1.05)
    ap.add_argument("--tag", type=str, default="main")
    args = ap.parse_args()
    main(args.put_moneyness, args.call_moneyness, args.tag)
