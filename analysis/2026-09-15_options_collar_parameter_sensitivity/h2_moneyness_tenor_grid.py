"""H2 - 칼라 옵션 헤지의 모네니스(풋/콜)×테너 파라미터 그리드 스윕.

배경: core/champion_strategy.py가 2026-09-14 라이브화한 합성 Black-Scholes 칼라(ATM 풋 매수 +
5%OTM 콜 매도, 매월 첫 거래일 롤, 21거래일 테너)는 report_data.json(confidence_table)이 명시하듯
"확신도 weak"로 조건부 채택됐을 뿐, 이 특정 (put=1.00, call=1.05, tenor=21) 조합 자체가 왜 이
숫자들인지는 감사된 적이 없다 — h_options_hedge.py 원 리서치(작업48)가 민감도 체크용으로 남겨둔
"5% OTM" 주석이 그대로 라이브 기본값이 됐을 뿐이다. 이번 라운드는 이 조합이 이웃값들과 비교해
완만한 고원(로버스트)인지, 아니면 우연히 좋아 보인 뾰족한 봉우리(과최적화)인지를 감사한다.

새 계산 로직을 만들지 않는다 — core.champion_strategy.build_collar_overlay_returns()(Black-Scholes
폐형식+SPY/VIX 종가+FRED 금리)를 그대로 호출하고, h1이 캐시해둔 core_ret/sat_ret/unhedged_blend
위에 오버레이만 얹는다(run_champion_backtest_with_collar과 동일한 조합 로직을 여기서 재현하되,
비싼 새틀라이트 재계산을 피하려고 캐시된 unhedged_blend를 재사용).

그리드:
  H2a 풋 모네니스: [1.00(ATM, 현재 기본값), 0.975(2.5% OTM), 0.95(5% OTM), 0.90(10% OTM)]
                   콜=1.05, 테너=21 고정
  H2b 콜 모네니스: [1.025, 1.05(현재 기본값), 1.075, 1.10] 풋=1.00, 테너=21 고정
                   + 제로코스트 변형(각 롤마다 콜 프리미엄이 풋 프리미엄과 같아지도록 콜 행사가를
                   이분탐색으로 직접 구함 — build_collar_overlay_returns가 지원하지 않는 유일한
                   변형이라 core.champion_strategy.bs_put_price/bs_call_price/_fedfunds_rate_asof를
                   그대로 재사용하는 얇은 어댑터를 이 파일에 추가)
  H2c 테너: [10, 21(현재 기본값), 42, 63]일 풋=1.00, 콜=1.05 고정
  H2d 이웃값 결합그리드(견고성/고원 확인): 풋 in {0.95,1.00} x 콜 in {1.05,1.10} x 테너 in {21,42}
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, _first_trading_day_of_month_mask
from core.champion_strategy import (
    build_collar_overlay_returns, bs_put_price, bs_call_price, _fedfunds_rate_asof,
    SATELLITE_WEIGHT, COLLAR_TENOR_DAYS, COLLAR_FALLBACK_VOL,
)
from core.market_data import get_price_history

OUT_DIR = Path(__file__).resolve().parent

EPISODES = {
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
    "full_2019_2026": ("2019-08-12", "2026-08-19", "2019-08-12", "2026-08-19"),
}
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
GROUP_OF = {
    "gfc_2008": "gfc_2008", "correction_2015_2016": "correction_2015_2016",
    "selloff_2018": "selloff_2018", "covid_2020": "covid_2020",
    "bear_2022": "full_2019_2026_shared", "full_2019_2026": "full_2019_2026_shared",
}

BASELINE = {"put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": COLLAR_TENOR_DAYS}

PUT_GRID = [1.00, 0.975, 0.95, 0.90]
CALL_GRID = [1.025, 1.05, 1.075, 1.10]
TENOR_GRID = [10, 21, 42, 63]
NEIGHBORHOOD_GRID = [
    {"put_moneyness": p, "call_moneyness": c, "tenor_days": t}
    for p in (0.95, 1.00) for c in (1.05, 1.10) for t in (21, 42)
]


def log(msg):
    print(f"[h2] {msg}", flush=True)


def load_group_returns(group: str) -> dict:
    core_ret = pd.read_csv(OUT_DIR / f"{group}_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_ret = pd.read_csv(OUT_DIR / f"{group}_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    unhedged = pd.read_csv(OUT_DIR / f"{group}_unhedged_blend_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    return {"core_ret": core_ret, "sat_ret": sat_ret, "unhedged_blend": unhedged}


def metrics_from_ret(ret: pd.Series, start=None, end=None) -> dict:
    r = ret.copy()
    if start is not None:
        r = r[(r.index >= pd.Timestamp(start)) & (r.index <= pd.Timestamp(end))]
    if r.empty:
        return calculate_metrics(pd.Series(dtype=float), [], start, end)
    eq = (1.0 + r.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    return calculate_metrics(eq, [], eq.index[0], eq.index[-1])


def build_zero_cost_collar_overlay(
    trading_index: pd.DatetimeIndex, start: str, end: str, put_moneyness: float,
    tenor_days: int = COLLAR_TENOR_DAYS, call_search_range: tuple = (1.001, 1.30), tol: float = 1e-5,
) -> dict:
    """제로코스트 칼라: 매 롤마다 콜 프리미엄이 풋 프리미엄과 (거의) 같아지도록 콜 행사가를
    이분탐색으로 구한다. build_collar_overlay_returns가 지원하지 않는 유일한 변형이라 여기서만
    얇은 어댑터로 추가한다 — 옵션가격 공식 자체(bs_put_price/bs_call_price)와 무위험금리 조회
    (_fedfunds_rate_asof), 롤 스케줄(_first_trading_day_of_month_mask)은 core.champion_strategy를
    그대로 재사용한다(새 계산 로직 추가 없음)."""
    warmup_days = 60
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=warmup_days)).date().isoformat()
    spy_close = get_price_history("SPY", start=fetch_start, end=end, use_cache=True)["Close"]
    vix_close = get_price_history("^VIX", start=fetch_start, end=end, use_cache=True)["Close"]
    px = pd.DataFrame({"spy": spy_close}).join(pd.DataFrame({"vix": vix_close}), how="left")
    px["vix"] = px["vix"].ffill()
    px = px.reindex(trading_index).ffill()

    roll_mask = _first_trading_day_of_month_mask(trading_index)
    roll_dates = list(trading_index[roll_mask])
    if len(roll_dates) == 0 or roll_dates[0] != trading_index[0]:
        roll_dates = [trading_index[0]] + roll_dates

    overlay_ret = pd.Series(0.0, index=trading_index)
    roll_log = []
    for rd in roll_dates:
        pos = trading_index.get_loc(rd)
        exp_pos = min(pos + tenor_days, len(trading_index) - 1)
        expiry = trading_index[exp_pos]
        S0 = float(px.loc[rd, "spy"])
        vix0 = px.loc[rd, "vix"]
        sigma = float(vix0) / 100.0 if pd.notna(vix0) else COLLAR_FALLBACK_VOL
        r = _fedfunds_rate_asof(rd)
        T = tenor_days / 252.0
        K_put = S0 * put_moneyness
        put0 = bs_put_price(S0, K_put, T, r, sigma)

        # 이분탐색: call_moneyness를 늘릴수록(행사가 상승) 콜 프리미엄은 감소(단조) -> put0와 일치하는 지점 탐색
        lo, hi = call_search_range
        call_lo, call_hi = bs_call_price(S0, S0 * lo, T, r, sigma), bs_call_price(S0, S0 * hi, T, r, sigma)
        if call_lo < put0:
            # lo에서조차 콜 프리미엄이 풋보다 작다 -> 제로코스트 불가능(변동성 낮음/풋이 비쌈), lo로 근사
            call_moneyness = lo
            call0 = call_lo
        elif call_hi > put0:
            call_moneyness = hi
            call0 = call_hi
        else:
            for _ in range(60):
                mid = (lo + hi) / 2
                cm = bs_call_price(S0, S0 * mid, T, r, sigma)
                if abs(cm - put0) < tol * max(S0, 1.0):
                    lo = hi = mid
                    break
                if cm > put0:
                    lo = mid
                else:
                    hi = mid
            call_moneyness = (lo + hi) / 2
            call0 = bs_call_price(S0, S0 * call_moneyness, T, r, sigma)

        K_call = S0 * call_moneyness
        S_T = float(px.loc[expiry, "spy"])
        put_payoff = max(K_put - S_T, 0.0)
        call_payoff = max(S_T - K_call, 0.0)
        net_premium_pct_debit = (call0 - put0) / S0
        net_payoff_pct_credit = (put_payoff - call_payoff) / S0

        overlay_ret.loc[rd] += net_premium_pct_debit
        overlay_ret.loc[expiry] += net_payoff_pct_credit
        roll_log.append({
            "roll_date": str(rd.date()), "expiry_date": str(expiry.date()),
            "call_moneyness_solved": round(call_moneyness, 4),
            "put_premium_pct": round(put0 / S0, 5), "call_premium_pct": round(call0 / S0, 5),
            "net_premium_pct": round(net_premium_pct_debit, 6),
        })
    return {"overlay_ret": overlay_ret, "roll_log": roll_log}


def run_grid_point(group: str, cached: dict, put_moneyness: float, call_moneyness: float, tenor_days: int,
                    zero_cost: bool = False) -> dict:
    full_start, full_end, crisis_start, crisis_end = EPISODES[
        "full_2019_2026" if group == "full_2019_2026_shared" else group
    ]
    trading_index = cached["unhedged_blend"].index
    if zero_cost:
        overlay = build_zero_cost_collar_overlay(trading_index, full_start, full_end, put_moneyness, tenor_days)
    else:
        overlay = build_collar_overlay_returns(trading_index, full_start, full_end, put_moneyness, call_moneyness, tenor_days)
    overlay_scaled = overlay["overlay_ret"].reindex(trading_index).fillna(0.0) * SATELLITE_WEIGHT
    collar_ret = cached["unhedged_blend"] + overlay_scaled

    total_premium = sum(r.get("net_premium_pct", r.get("net_premium_pct_debit", 0.0)) for r in overlay["roll_log"])
    total_payoff = sum(r.get("net_payoff_pct", r.get("payoff_pct_credit", 0.0)) for r in overlay["roll_log"])
    return {
        "n_rolls": len(overlay["roll_log"]),
        "cumulative_net_premium_pct_of_notional": round(total_premium * 100, 3),
        "cumulative_net_payoff_pct_of_notional": round(total_payoff * 100, 3),
        "collar_ret": collar_ret,
    }


def summarize_grid_point(group_label: str, cached: dict, collar_ret: pd.Series) -> dict:
    full_start, full_end, crisis_start, crisis_end = EPISODES[group_label]
    is_full_window = group_label == "full_2019_2026"
    windows = {"full_period": (full_start, full_end)}
    if not is_full_window:
        windows["crisis_window"] = (crisis_start, crisis_end)

    out = {}
    for wname, (ws, we) in windows.items():
        out[wname] = {
            "window": [ws, we],
            "core_alone": metrics_from_ret(cached["core_ret"], ws, we),
            "unhedged_satellite": metrics_from_ret(cached["unhedged_blend"], ws, we),
            "collar_hedged": metrics_from_ret(collar_ret, ws, we),
        }
    return out


def main():
    t0 = time.time()
    group_cache = {}
    for group_key in ("gfc_2008", "correction_2015_2016", "selloff_2018", "covid_2020", "full_2019_2026_shared"):
        group_cache[group_key] = load_group_returns(group_key)

    results = {"baseline": {}, "h2a_put_grid": {}, "h2b_call_grid": {}, "h2b_zero_cost": {},
               "h2c_tenor_grid": {}, "h2d_neighborhood_grid": []}

    for episode in EPISODE_ORDER:
        group_key = "full_2019_2026_shared" if episode in ("bear_2022", "full_2019_2026") else episode
        cached = group_cache[group_key]

        log(f"{episode}: 베이스라인(put=1.00,call=1.05,tenor=21)")
        base = run_grid_point(group_key, cached, **BASELINE)
        results["baseline"][episode] = {
            **{k: v for k, v in base.items() if k != "collar_ret"},
            "windows": summarize_grid_point(episode, cached, base["collar_ret"]),
        }

        results["h2a_put_grid"][episode] = []
        for pm in PUT_GRID:
            r = run_grid_point(group_key, cached, put_moneyness=pm, call_moneyness=1.05, tenor_days=21)
            results["h2a_put_grid"][episode].append({
                "put_moneyness": pm, "n_rolls": r["n_rolls"],
                "cum_premium_pct": r["cumulative_net_premium_pct_of_notional"],
                "cum_payoff_pct": r["cumulative_net_payoff_pct_of_notional"],
                "windows": summarize_grid_point(episode, cached, r["collar_ret"]),
            })
        log(f"  h2a put grid done")

        results["h2b_call_grid"][episode] = []
        for cm in CALL_GRID:
            r = run_grid_point(group_key, cached, put_moneyness=1.00, call_moneyness=cm, tenor_days=21)
            results["h2b_call_grid"][episode].append({
                "call_moneyness": cm, "n_rolls": r["n_rolls"],
                "cum_premium_pct": r["cumulative_net_premium_pct_of_notional"],
                "cum_payoff_pct": r["cumulative_net_payoff_pct_of_notional"],
                "windows": summarize_grid_point(episode, cached, r["collar_ret"]),
            })
        log(f"  h2b call grid done")

        r_zc = run_grid_point(group_key, cached, put_moneyness=1.00, call_moneyness=None, tenor_days=21, zero_cost=True)
        results["h2b_zero_cost"][episode] = {
            "n_rolls": r_zc["n_rolls"], "cum_premium_pct": r_zc["cumulative_net_premium_pct_of_notional"],
            "cum_payoff_pct": r_zc["cumulative_net_payoff_pct_of_notional"],
            "windows": summarize_grid_point(episode, cached, r_zc["collar_ret"]),
        }
        log(f"  h2b zero-cost done")

        results["h2c_tenor_grid"][episode] = []
        for td in TENOR_GRID:
            r = run_grid_point(group_key, cached, put_moneyness=1.00, call_moneyness=1.05, tenor_days=td)
            results["h2c_tenor_grid"][episode].append({
                "tenor_days": td, "n_rolls": r["n_rolls"],
                "cum_premium_pct": r["cumulative_net_premium_pct_of_notional"],
                "cum_payoff_pct": r["cumulative_net_payoff_pct_of_notional"],
                "windows": summarize_grid_point(episode, cached, r["collar_ret"]),
            })
        log(f"  h2c tenor grid done")

        for combo in NEIGHBORHOOD_GRID:
            r = run_grid_point(group_key, cached, **combo)
            w = summarize_grid_point(episode, cached, r["collar_ret"])
            key_window = "crisis_window" if "crisis_window" in w else "full_period"
            results["h2d_neighborhood_grid"].append({
                "episode": episode, **combo,
                "sharpe_collar": w[key_window]["collar_hedged"]["sharpe"],
                "sharpe_unhedged": w[key_window]["unhedged_satellite"]["sharpe"],
                "mdd_collar": w[key_window]["collar_hedged"]["mdd"],
            })
        log(f"{episode}: 전체 그리드 완료 ({time.time()-t0:.1f}s 누적)")

    (OUT_DIR / "h2_grid_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    log(f"저장 완료: h2_grid_results.json (총 {time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
