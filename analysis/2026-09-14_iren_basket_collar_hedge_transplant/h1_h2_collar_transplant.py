"""H1/H2 - SPY 합성 칼라 헤지를 IREN류 피벗 바스켓에 이식.

H1: 무헤지 바스켓(정적 균등가중 매수후보유) + SPY 콜라 오버레이(1배 노셔널) -> 개선되는가?
H2: 트랙C 챔피언(20일 돈치안+15%트레일링스탑, 바스켓/IREN단일) + 같은 콜라 오버레이 -> 이미
    트레일링스탑이 하방을 일부 방어하는 상태에서 콜라를 더하면 추가로 개선되는가, 아니면 중복
    보호라 한계효용이 없는가?

방법론: 콜라 자체는 `core.champion_strategy.build_collar_overlay_returns`를 그대로 호출(새 옵션
가격 로직을 만들지 않음) - SPY 100% 노셔널 기준 월별 롤 수익률을 계산한 뒤, 전략의 트레이딩
인덱스에 맞춰 가중치(overlay_weight)를 곱해 더한다. overlay_weight=1.0은 "바스켓 1달러당 SPY
콜라 1달러 노셔널"이라는 순진한(naive) 기준선이다 - 이 바스켓의 실측 시장베타(2.5~3배, 작업28)를
반영한 스케일링은 h3에서 별도로 다룬다.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from hedge_common import (
    OUT_DIR, PIVOT_BASKET, END, ENTRY_WINDOW, STOP_PCT, MOM_WINDOW,
    load_histories, closes_frame, find_common_start,
    basket_static_buy_hold_returns, collar_overlay_for_index, metrics_from_ret,
)
from backtest import run_trend_following_single, run_trend_following_basket
from core.market_data import get_price_history


def log(msg):
    print(f"[h1h2] {msg}", flush=True)


def combine(base_ret: pd.Series, overlay_ret: pd.Series, weight: float) -> pd.Series:
    idx = base_ret.index
    ov = overlay_ret.reindex(idx).fillna(0.0)
    return base_ret + ov * weight


def main():
    log("가격 데이터 로딩...")
    hist = load_histories(PIVOT_BASKET)
    closes_all = closes_frame(hist)
    closes_main = closes_all[PIVOT_BASKET].dropna(how="all")
    common_start = find_common_start(closes_main, MOM_WINDOW)
    log(f"공통 시작일: {common_start.date()} ~ {END}")

    # ------------------------------------------------------------------
    # 베이스라인 수익률 시계열 복원
    # ------------------------------------------------------------------
    basket_bh_ret = basket_static_buy_hold_returns(closes_main, common_start)
    iren_close = closes_all["IREN"].dropna()
    iren_bh_ret = iren_close[iren_close.index >= common_start].pct_change().fillna(0.0)
    iren_bh_ret.iloc[0] = 0.0

    m_single, _, _ = run_trend_following_single(iren_close, common_start, ENTRY_WINDOW, STOP_PCT)
    from hedge_common import metrics_from_ret as _mr  # noqa
    # run_trend_following_single/basket 은 (metrics, equity, position)을 반환 - 여기서는 수익률
    # 시계열이 필요하므로 backtest.py 내부 로직(도치안 신호)만 재사용해 직접 복원한다(감사1과 동일 패턴).
    from hedge_common import donchian_trailing_stop_positions
    from hedge_common import COST_RATE

    def strategy_daily_returns(close: pd.Series, start: pd.Timestamp) -> pd.Series:
        position = donchian_trailing_stop_positions(close, ENTRY_WINDOW, STOP_PCT)
        sliced_close = close[close.index >= start]
        pos_sliced = position.loc[sliced_close.index]
        daily_ret = sliced_close.pct_change().fillna(0.0)
        executed = pos_sliced.shift(1).fillna(0).astype(float)
        turnover = executed.diff().abs().fillna(0.0)
        return daily_ret * executed - turnover * COST_RATE

    def basket_daily_returns(closes: pd.DataFrame, start: pd.Timestamp) -> pd.Series:
        positions = pd.DataFrame({t: donchian_trailing_stop_positions(closes[t].dropna(), ENTRY_WINDOW, STOP_PCT)
                                   for t in closes.columns})
        positions = positions.reindex(closes.index).fillna(0).astype(int)
        n_active = positions.sum(axis=1).replace(0, np.nan)
        weights = positions.div(n_active, axis=0).fillna(0.0)
        sliced_closes = closes[closes.index >= start]
        w = weights.loc[sliced_closes.index]
        daily_ret = sliced_closes.pct_change().fillna(0.0)
        executed_w = w.shift(1).fillna(0.0)
        port_ret = (daily_ret * executed_w).sum(axis=1)
        from hedge_common import cost_series
        cost = cost_series(executed_w)
        return port_ret - cost

    iren_trend_ret = strategy_daily_returns(iren_close, common_start)
    basket_trend_ret = basket_daily_returns(closes_main, common_start)

    log(f"베이스라인 샤프 - 바스켓매수후보유: {metrics_from_ret(basket_bh_ret)['sharpe']}, "
        f"IREN매수후보유: {metrics_from_ret(iren_bh_ret)['sharpe']}, "
        f"IREN추세추종: {metrics_from_ret(iren_trend_ret)['sharpe']}, "
        f"바스켓추세추종: {metrics_from_ret(basket_trend_ret)['sharpe']}")

    # ------------------------------------------------------------------
    # 콜라 오버레이 (SPY 100% 노셔널 기준) - 4개 시계열의 트레이딩 인덱스가 서로 다르므로(상장일
    # 차이) 각각에 맞춰 계산한다. build_collar_overlay_returns는 매월 첫 거래일 롤이라 인덱스가
    # 바뀌면 롤 스케줄도 바뀐다 - 이건 의도된 동작(각 전략이 실제로 그 기간에 보유했을 콜라를
    # 재현하는 것).
    # ------------------------------------------------------------------
    log("콜라 오버레이 계산...")
    overlays = {}
    for label, ret in [
        ("basket_bh", basket_bh_ret), ("iren_bh", iren_bh_ret),
        ("iren_trend", iren_trend_ret), ("basket_trend", basket_trend_ret),
    ]:
        start_str = ret.index[0].date().isoformat()
        ov_ret, roll_log = collar_overlay_for_index(ret.index, start_str, END)
        overlays[label] = {"ret": ov_ret, "roll_log": roll_log}
        log(f"  {label}: n_rolls={len(roll_log)}, overlay_ann_mean={ov_ret.mean()*252:.4f}")

    # ------------------------------------------------------------------
    # 1배 노셔널 결합
    # ------------------------------------------------------------------
    results = {}
    baselines = {
        "basket_bh": basket_bh_ret, "iren_bh": iren_bh_ret,
        "iren_trend": iren_trend_ret, "basket_trend": basket_trend_ret,
    }
    for label, base_ret in baselines.items():
        unhedged_m = metrics_from_ret(base_ret)
        hedged_ret = combine(base_ret, overlays[label]["ret"], 1.0)
        hedged_m = metrics_from_ret(hedged_ret)
        results[label] = {
            "n_days": int(len(base_ret)), "start": str(base_ret.index[0].date()), "end": str(base_ret.index[-1].date()),
            "unhedged": unhedged_m, "collar_1x": hedged_m,
            "sharpe_improved": bool(hedged_m["sharpe"] > unhedged_m["sharpe"]),
            "sharpe_delta": round(hedged_m["sharpe"] - unhedged_m["sharpe"], 4),
            "mdd_improved": bool(hedged_m["mdd"] > unhedged_m["mdd"]),
            "mdd_delta": round(hedged_m["mdd"] - unhedged_m["mdd"], 3),
        }
        log(f"  [{label}] 무헤지 샤프{unhedged_m['sharpe']} MDD{unhedged_m['mdd']} -> "
            f"콜라1x 샤프{hedged_m['sharpe']} MDD{hedged_m['mdd']} (delta_sharpe={results[label]['sharpe_delta']})")

    # ------------------------------------------------------------------
    # 저장 - 부트스트랩(h3/h4)에서 재사용할 수 있도록 수익률 시계열을 CSV로 남긴다.
    # ------------------------------------------------------------------
    for label, ret in baselines.items():
        ret.to_csv(OUT_DIR / f"{label}_unhedged_ret.csv", header=["ret"])
        overlays[label]["ret"].to_csv(OUT_DIR / f"{label}_collar_overlay_ret.csv", header=["ret"])

    out = {
        "meta": {
            "generated": END, "basket": PIVOT_BASKET, "entry_window": ENTRY_WINDOW, "stop_pct": STOP_PCT,
            "common_start": str(common_start.date()), "end": END,
        },
        "h1_h2_results": results,
        "roll_logs": {label: overlays[label]["roll_log"] for label in overlays},
    }
    with open(OUT_DIR / "h1_h2_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log("저장 완료: h1_h2_results.json")


if __name__ == "__main__":
    main()
