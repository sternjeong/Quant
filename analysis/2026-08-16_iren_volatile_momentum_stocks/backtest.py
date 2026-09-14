"""IREN류 변동성 종목(비트코인 채굴 -> AI/HPC 데이터센터 피벗 테마) 백테스트.

트랙 C 두 번째 리포트 — 텐베거 리포트(2026-08-16)가 스스로 밝힌 한계("S&P500 유니버스가 진짜
소형/테마주 텐베거 후보를 구조적으로 배제한다")를 정면으로 다룬다. 여기서는 스크리닝이 아니라
"이미 좋아하는 이런 유형의 종목을 어떻게 다루면 최대한 벌 수 있는가"를 실제 백테스트로 검증한다.

4개 접근을 비교한다:
  1) 베이스라인: 단일종목(IREN)/바스켓 매수후보유
  2) 바스켓 내 모멘텀 로테이션 (analysis/kostolany_market_report_2026-08-12/momentum_rotation.py의
     듀얼모멘텀 패턴을 이 바스켓에 적용)
  3) 추세추종 돈치안 브레이크아웃 + % 트레일링스탑 (단일종목/바스켓)
  4) 2)/3) 중 우승 전략에 core.position_sizing 변동성타게팅 오버레이

전 구간 왕복 0.1% 거래비용(편도 5bp) 반영. 결과: report_data.json
"""
import json
import pickle

import numpy as np
import pandas as pd

from common import (
    OUT_DIR, PIVOT_BASKET, PIVOT_BASKET_WITH_CORZ, CONTRAST_BASKET, ALL_TICKERS, BENCH,
    END, FEE_BPS, COST_RATE, load_histories, closes_frame, metrics_from_returns, cost_series,
)
from core.backtest_engine import calculate_metrics, run_buy_and_hold, _first_trading_day_of_month_mask
from core.position_sizing import realized_annual_volatility_pct, volatility_target_weight


def log(msg):
    print(f"[bt] {msg}", flush=True)


def find_common_start(closes: pd.DataFrame, warmup_days: int) -> pd.Timestamp:
    """전 종목이 warmup_days만큼의 유효 이력을 확보하는 가장 이른 날짜(=백테스트 시작 가능일)."""
    first_valid = {c: closes[c].first_valid_index() for c in closes.columns}
    starts = []
    for c, fv in first_valid.items():
        if fv is None:
            continue
        idx = closes.index.get_indexer([fv])[0]
        if idx + warmup_days >= len(closes.index):
            starts.append(closes.index[-1])
        else:
            starts.append(closes.index[idx + warmup_days])
    return max(starts)


def build_momentum_weights(closes: pd.DataFrame, momentum_window: int, top_n: int) -> pd.DataFrame:
    """momentum_rotation.py와 동일한 듀얼모멘텀(절대+상대) 로직. 월별 리밸런싱, 후보부족은 현금."""
    momentum = closes.pct_change(momentum_window)
    is_rebal = _first_trading_day_of_month_mask(closes.index)
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            candidates = mom[mom > 0].sort_values(ascending=False)
            picks = candidates.index[:top_n]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / top_n
            last_weights = w
        weights.iloc[i] = last_weights.values
    return weights


def run_rotation(closes: pd.DataFrame, start: pd.Timestamp, momentum_window: int, top_n: int):
    weights_full = build_momentum_weights(closes, momentum_window, top_n)
    sliced = closes[closes.index >= start]
    weights = weights_full.loc[sliced.index]
    daily_ret = sliced.pct_change().fillna(0.0)
    executed_weights = weights.shift(1).fillna(0.0)
    port_ret = (daily_ret * executed_weights).sum(axis=1)
    cost = cost_series(executed_weights)  # 실행비중 변화 기준 turnover 비용(체결일 반영)
    port_ret_after_cost = port_ret - cost
    m, eq = metrics_from_returns(port_ret_after_cost)
    return m, eq, weights


def donchian_trailing_stop_positions(close: pd.Series, entry_window: int, stop_pct: float) -> pd.Series:
    """단일종목 돈치안 브레이크아웃 진입 + % 트레일링스탑 청산 신호(0/1) 생성.

    진입: 오늘 종가가 [t-entry_window, t-1] 구간 최고종가를 갱신하면 익일 진입.
    청산: 진입 이후 도달한 최고종가 대비 stop_pct만큼 하락하면 익일 청산.
    """
    rolling_max = close.shift(1).rolling(entry_window, min_periods=entry_window).max()
    breakout = close > rolling_max

    position = pd.Series(0, index=close.index, dtype=int)
    in_pos = False
    peak = None
    for i in range(len(close)):
        c = close.iloc[i]
        if in_pos:
            peak = max(peak, c)
            if c <= peak * (1 - stop_pct):
                in_pos = False
                peak = None
        else:
            if breakout.iloc[i]:
                in_pos = True
                peak = c
        position.iloc[i] = 1 if in_pos else 0
    return position


def run_trend_following_single(close: pd.Series, start: pd.Timestamp, entry_window: int, stop_pct: float):
    position = donchian_trailing_stop_positions(close, entry_window, stop_pct)
    df = pd.DataFrame({"Close": close})
    sliced_close = close[close.index >= start]
    pos_sliced = position.loc[sliced_close.index]
    daily_ret = sliced_close.pct_change().fillna(0.0)
    executed = pos_sliced.shift(1).fillna(0).astype(float)
    turnover = executed.diff().abs().fillna(0.0)
    strat_ret = daily_ret * executed - turnover * COST_RATE
    m, eq = metrics_from_returns(strat_ret)
    trade_count = int((position.diff() == 1).sum())
    m["trade_count"] = trade_count
    return m, eq, position


def run_trend_following_basket(closes: pd.DataFrame, start: pd.Timestamp, entry_window: int, stop_pct: float):
    """바스켓의 각 종목에 독립적으로 동일한 돈치안+트레일링스탑 신호를 적용하고, '그 날 신호가 켜진
    종목들'에 동일가중(1/보유종목수)으로 배분한다(나머지는 현금) — 개별 종목 타이밍의 바스켓 합성."""
    positions = pd.DataFrame({t: donchian_trailing_stop_positions(closes[t].dropna(), entry_window, stop_pct)
                               for t in closes.columns})
    positions = positions.reindex(closes.index).fillna(0).astype(int)
    n_active = positions.sum(axis=1).replace(0, np.nan)
    weights = positions.div(n_active, axis=0).fillna(0.0)

    sliced_closes = closes[closes.index >= start]
    w = weights.loc[sliced_closes.index]
    daily_ret = sliced_closes.pct_change().fillna(0.0)
    executed_w = w.shift(1).fillna(0.0)
    port_ret = (daily_ret * executed_w).sum(axis=1)
    cost = cost_series(executed_w)
    port_ret_after_cost = port_ret - cost
    m, eq = metrics_from_returns(port_ret_after_cost)
    avg_active = float(positions.sum(axis=1).loc[sliced_closes.index].mean())
    m["avg_active_names"] = round(avg_active, 2)
    return m, eq, positions


def vol_target_overlay(strategy_ret: pd.Series, target_vol_list, cap_list):
    results = []
    curves = {}
    for target_vol in target_vol_list:
        for cap in cap_list:
            equity_proxy = (1.0 + strategy_ret.fillna(0.0)).cumprod() * 100.0
            realized_vol = equity_proxy.rolling(21).apply(
                lambda x: realized_annual_volatility_pct(pd.Series(x)) or 0.0, raw=False
            )
            scale = realized_vol.apply(
                lambda v: volatility_target_weight(target_vol, v, max_weight=cap) if v and v > 0 else 0.0
            )
            scaled_ret = strategy_ret * scale.shift(1).fillna(0.0)
            m, eq = metrics_from_returns(scaled_ret)
            results.append({"target_vol": target_vol, "cap": cap, **m})
            curves[(target_vol, cap)] = eq
    return pd.DataFrame(results), curves


def main():
    result = {"meta": {"end_date": END, "fee_bps_oneway": FEE_BPS, "round_trip_cost_pct": FEE_BPS * 2 / 100}}

    # ------------------------------------------------------------------
    # 0) 데이터 로딩 + 실제 상장(재상장)일 확인
    # ------------------------------------------------------------------
    log("가격 데이터 로딩...")
    hist = load_histories(ALL_TICKERS + BENCH)
    closes_all = closes_frame(hist)
    listing_dates = {t: (closes_all[t].first_valid_index().date().isoformat() if closes_all[t].first_valid_index() is not None else None)
                      for t in ALL_TICKERS}
    log(f"상장(재상장)일: {listing_dates}")
    result["listing_dates"] = listing_dates

    # ------------------------------------------------------------------
    # 1) 메인 바스켓(6종, CORZ 제외) 공통 시작일 산출 — 모멘텀 웜업 126거래일(6개월) 확보
    # ------------------------------------------------------------------
    MOM_WINDOW = 126
    TOP_N = 3
    closes_main = closes_all[PIVOT_BASKET].dropna(how="all")
    common_start = find_common_start(closes_main, MOM_WINDOW)
    log(f"메인 바스켓(CORZ 제외 {PIVOT_BASKET}) 웜업 확보 공통 시작일: {common_start.date()}")
    result["main_basket"] = PIVOT_BASKET
    result["main_basket_start"] = common_start.date().isoformat()
    result["main_basket_end"] = END
    result["momentum_window_days"] = MOM_WINDOW
    result["top_n"] = TOP_N

    # ------------------------------------------------------------------
    # 2) 베이스라인 — IREN 단일종목 매수후보유
    # ------------------------------------------------------------------
    log("2) 베이스라인: IREN 매수후보유...")
    iren_bh = run_buy_and_hold("IREN", start=listing_dates["IREN"], end=END, fee_bps=FEE_BPS, slippage_bps=0.0)
    result["iren_buy_hold"] = {"metrics": iren_bh.metrics, "start": listing_dates["IREN"], "end": END}
    log(f"   IREN 매수후보유(상장일부터): {iren_bh.metrics}")

    iren_bh_common = run_buy_and_hold("IREN", start=common_start.date().isoformat(), end=END, fee_bps=FEE_BPS, slippage_bps=0.0)
    result["iren_buy_hold_common_window"] = {"metrics": iren_bh_common.metrics, "start": common_start.date().isoformat(), "end": END}
    log(f"   IREN 매수후보유(공통구간): {iren_bh_common.metrics}")

    # ------------------------------------------------------------------
    # 3) 베이스라인 — 바스켓 균등가중 매수후보유(정적, 리밸런싱 없음)
    # ------------------------------------------------------------------
    log("3) 베이스라인: 바스켓 균등가중 매수후보유(정적)...")
    sliced_main = closes_main[closes_main.index >= common_start].ffill()
    norm = sliced_main / sliced_main.iloc[0]
    static_eq = norm.mean(axis=1) * 100.0
    m_static = calculate_metrics(static_eq, [], static_eq.index[0], static_eq.index[-1])
    result["basket_static_buy_hold"] = {"metrics": m_static, "start": common_start.date().isoformat(), "end": END}
    log(f"   바스켓 정적 균등보유: {m_static}")

    # 참고: 매일 리밸런싱되는(=일별 동일가중 재조정) 버전도 참고치로 병기 (저장소 기존 관례)
    daily_rebal_ret = sliced_main.pct_change().fillna(0.0).mean(axis=1)
    m_daily, eq_daily = metrics_from_returns(daily_rebal_ret)
    result["basket_daily_rebalanced_hold"] = {"metrics": m_daily}
    log(f"   바스켓 일별 리밸런싱 균등보유(참고): {m_daily}")

    # ------------------------------------------------------------------
    # 4) SPY / BTC 벤치마크 (같은 공통구간)
    # ------------------------------------------------------------------
    spy_bh = run_buy_and_hold("SPY", start=common_start.date().isoformat(), end=END)
    btc_bh = run_buy_and_hold("BTC-USD", start=common_start.date().isoformat(), end=END)
    result["spy_buy_hold"] = {"metrics": spy_bh.metrics}
    result["btc_buy_hold"] = {"metrics": btc_bh.metrics}
    log(f"   SPY 매수후보유: {spy_bh.metrics}")
    log(f"   BTC-USD 매수후보유: {btc_bh.metrics}")

    # ------------------------------------------------------------------
    # 5) 모멘텀 로테이션 (바스켓 내 상위 top_n, 월 리밸런싱, 절대모멘텀 필터)
    # ------------------------------------------------------------------
    log("5) 모멘텀 로테이션...")
    m_rot, eq_rot, w_rot = run_rotation(closes_main, common_start, MOM_WINDOW, TOP_N)
    result["momentum_rotation"] = {"metrics": m_rot, "momentum_window": MOM_WINDOW, "top_n": TOP_N}
    log(f"   모멘텀 로테이션(window={MOM_WINDOW}, top{TOP_N}): {m_rot}")

    # 민감도: momentum window/top_n 스윕
    sweep_rows = []
    for mw in [63, 126, 189, 252]:
        cstart = find_common_start(closes_main, mw)
        for tn in [1, 2, 3]:
            try:
                m, _, _ = run_rotation(closes_main, cstart, mw, tn)
                sweep_rows.append({"momentum_window": mw, "top_n": tn, "start": cstart.date().isoformat(), **m})
            except Exception as e:
                log(f"   스윕 실패 mw={mw} tn={tn}: {e}")
    sweep_df = pd.DataFrame(sweep_rows)
    sweep_df.to_csv(f"{OUT_DIR}/rotation_sweep.csv", index=False, encoding="utf-8-sig")
    result["rotation_sweep"] = sweep_df.to_dict(orient="records")
    log(f"   모멘텀 스윕 결과 저장 (n={len(sweep_df)})")

    # ------------------------------------------------------------------
    # 6) 추세추종 돈치안 브레이크아웃 + % 트레일링스탑 — 단일종목(IREN), 바스켓
    # ------------------------------------------------------------------
    log("6) 추세추종(돈치안+트레일링스탑)...")
    ENTRY_WINDOW = 20
    tf_sweep = []
    for stop_pct in [0.15, 0.20, 0.25, 0.30, 0.35]:
        m_single, eq_single, pos_single = run_trend_following_single(
            closes_all["IREN"].dropna(), common_start, ENTRY_WINDOW, stop_pct)
        m_basket, eq_basket, pos_basket = run_trend_following_basket(
            closes_main, common_start, ENTRY_WINDOW, stop_pct)
        tf_sweep.append({"stop_pct": stop_pct, "scope": "IREN_single", **m_single})
        tf_sweep.append({"stop_pct": stop_pct, "scope": "basket", **m_basket})
    tf_df = pd.DataFrame(tf_sweep)
    tf_df.to_csv(f"{OUT_DIR}/trend_following_sweep.csv", index=False, encoding="utf-8-sig")
    result["trend_following_sweep"] = tf_df.to_dict(orient="records")
    log(f"   추세추종 스윕: {tf_df.to_string()}")

    # 채택: 바스켓 스윕에서 샤프 최고인 stop_pct를 대표값으로
    best_tf_basket = tf_df[tf_df["scope"] == "basket"].sort_values("sharpe", ascending=False).iloc[0]
    best_stop_pct = float(best_tf_basket["stop_pct"])
    m_tf_basket_best, eq_tf_basket_best, pos_tf_basket_best = run_trend_following_basket(
        closes_main, common_start, ENTRY_WINDOW, best_stop_pct)
    m_tf_single_best, eq_tf_single_best, pos_tf_single_best = run_trend_following_single(
        closes_all["IREN"].dropna(), common_start, ENTRY_WINDOW, best_stop_pct)
    result["trend_following_best"] = {
        "entry_window": ENTRY_WINDOW, "stop_pct": best_stop_pct,
        "basket": m_tf_basket_best, "iren_single": m_tf_single_best,
    }
    log(f"   채택 stop_pct={best_stop_pct}: 바스켓 {m_tf_basket_best} / IREN단일 {m_tf_single_best}")

    # ------------------------------------------------------------------
    # 7) 챔피언 선정 (모멘텀 로테이션 vs 추세추종 바스켓, 샤프 기준) + 변동성타게팅 오버레이
    # ------------------------------------------------------------------
    log("7) 챔피언 선정 및 변동성타게팅 오버레이...")
    champion_name = "momentum_rotation" if m_rot["sharpe"] >= m_tf_basket_best["sharpe"] else "trend_following_basket"
    champion_ret = (eq_rot.pct_change().fillna(0.0) if champion_name == "momentum_rotation"
                    else eq_tf_basket_best.pct_change().fillna(0.0))
    result["champion"] = champion_name
    log(f"   챔피언: {champion_name} (모멘텀 샤프 {m_rot['sharpe']} vs 추세추종바스켓 샤프 {m_tf_basket_best['sharpe']})")

    vt_df, vt_curves = vol_target_overlay(champion_ret, [15.0, 20.0, 25.0, 30.0, 40.0], [1.0, 1.3])
    vt_df.to_csv(f"{OUT_DIR}/vol_target_sweep.csv", index=False, encoding="utf-8-sig")
    result["vol_target_sweep"] = vt_df.to_dict(orient="records")
    no_lev = vt_df[vt_df["cap"] == 1.0].sort_values("sharpe", ascending=False).iloc[0]
    with_lev = vt_df[vt_df["cap"] == 1.3].sort_values("sharpe", ascending=False).iloc[0]
    result["vol_target_best_no_leverage"] = no_lev.to_dict()
    result["vol_target_best_with_leverage"] = with_lev.to_dict()
    log(f"   변동성타게팅 무레버리지 최선: {no_lev.to_dict()}")
    log(f"   변동성타게팅 1.3배 상한 최선: {with_lev.to_dict()}")

    champion_no_overlay = m_rot if champion_name == "momentum_rotation" else m_tf_basket_best
    result["champion_no_overlay"] = champion_no_overlay

    # ------------------------------------------------------------------
    # 8) 고정비율(fixed-fractional) 방식 참고 계산 — core.position_sizing 실사용 예시
    #    (챔피언 전략의 대표 거래 하나로 fixed_fractional_size 실제 호출 예시를 남긴다)
    # ------------------------------------------------------------------
    from core.position_sizing import fixed_fractional_size
    example_entry = float(closes_all["IREN"].dropna().iloc[-60])
    example_stop = example_entry * (1 - best_stop_pct)
    ff_example = fixed_fractional_size(account_value=100_000, risk_pct=2.0, entry_price=example_entry, stop_price=example_stop)
    result["fixed_fractional_example"] = {
        "account_value": 100_000, "risk_pct": 2.0, "entry_price": round(example_entry, 2),
        "stop_price": round(example_stop, 2), "stop_pct_used": best_stop_pct, **ff_example,
    }
    log(f"   고정비율 사이징 예시(IREN, stop {best_stop_pct*100:.0f}%): {ff_example}")

    # ------------------------------------------------------------------
    # 9) 강건성 체크 — CORZ 포함 9종 바스켓(짧은 구간), 대조군(MARA/RIOT) 별도 매수후보유
    # ------------------------------------------------------------------
    log("9) 강건성 체크: CORZ 포함 바스켓, 대조군 매수후보유...")
    closes_corz = closes_all[PIVOT_BASKET_WITH_CORZ].dropna(how="all")
    corz_start = find_common_start(closes_corz, MOM_WINDOW)
    m_rot_corz, eq_rot_corz, _ = run_rotation(closes_corz, corz_start, MOM_WINDOW, TOP_N)
    sliced_corz = closes_corz[closes_corz.index >= corz_start].ffill()
    norm_corz = sliced_corz / sliced_corz.iloc[0]
    static_eq_corz = norm_corz.mean(axis=1) * 100.0
    m_static_corz = calculate_metrics(static_eq_corz, [], static_eq_corz.index[0], static_eq_corz.index[-1])
    result["robustness_with_corz"] = {
        "basket": PIVOT_BASKET_WITH_CORZ, "start": corz_start.date().isoformat(), "end": END,
        "momentum_rotation": m_rot_corz, "static_buy_hold": m_static_corz,
    }
    log(f"   CORZ포함(9종 중 CORZ만 짧음, {corz_start.date()}~) 모멘텀로테이션: {m_rot_corz}")
    log(f"   CORZ포함 정적균등보유: {m_static_corz}")

    contrast_metrics = {}
    for t in CONTRAST_BASKET:
        bh = run_buy_and_hold(t, start=listing_dates[t], end=END, fee_bps=FEE_BPS, slippage_bps=0.0)
        bh_common = run_buy_and_hold(t, start=common_start.date().isoformat(), end=END, fee_bps=FEE_BPS, slippage_bps=0.0)
        contrast_metrics[t] = {"full_history": bh.metrics, "common_window": bh_common.metrics, "listing_date": listing_dates[t]}
        log(f"   대조군 {t} 매수후보유(전체이력): {bh.metrics} / (공통구간): {bh_common.metrics}")
    result["contrast_basket_buy_hold"] = contrast_metrics

    # 대조군도 포함한 8종 전체(피벗6+대조2) 정적균등보유/로테이션 (테마 자체 vs 개별선택 비교용)
    closes_all8 = closes_all[PIVOT_BASKET + CONTRAST_BASKET].dropna(how="all")
    start8 = find_common_start(closes_all8, MOM_WINDOW)
    sliced8 = closes_all8[closes_all8.index >= start8].ffill()
    norm8 = sliced8 / sliced8.iloc[0]
    static_eq8 = norm8.mean(axis=1) * 100.0
    m_static8 = calculate_metrics(static_eq8, [], static_eq8.index[0], static_eq8.index[-1])
    m_rot8, eq_rot8, _ = run_rotation(closes_all8, start8, MOM_WINDOW, TOP_N)
    result["all8_incl_contrast"] = {
        "basket": PIVOT_BASKET + CONTRAST_BASKET, "start": start8.date().isoformat(),
        "static_buy_hold": m_static8, "momentum_rotation": m_rot8,
    }
    log(f"   피벗+대조군 8종 정적균등보유: {m_static8}")
    log(f"   피벗+대조군 8종 모멘텀로테이션: {m_rot8}")

    # ------------------------------------------------------------------
    # 저장
    # ------------------------------------------------------------------
    with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/report_data.json")

    with open(f"{OUT_DIR}/curves.pkl", "wb") as f:
        pickle.dump({
            "iren_bh_common": iren_bh_common.equity_curve,
            "basket_static": static_eq,
            "spy_bh": spy_bh.equity_curve,
            "btc_bh": btc_bh.equity_curve,
            "momentum_rotation": eq_rot,
            "trend_following_basket_best": eq_tf_basket_best,
            "trend_following_iren_best": eq_tf_single_best,
            "champion_ret": champion_ret,
            "vt_curves": vt_curves,
        }, f)
    log("DONE")


if __name__ == "__main__":
    main()
