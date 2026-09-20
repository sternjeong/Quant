"""2개 독립 시대(2018 크립토윈터 이전 MARA/RIOT, 1998~2002 닷컴버블)에 작업27(IREN류) 챔피언
로직을 그대로 이식.

목적: "돈치안20+15%트레일링스탑 추세추종이 매수후보유·로테이션을 이긴다"는 IREN 패턴(2022-05~
2026-08, 4.25년)이 그 시대(AI 인프라 슈퍼사이클)에 국한된 것인지, 아니면 진짜 극단적 약세장을
포함한 완전히 다른 시대에도 재현되는지 검증한다.

analysis/2026-08-16_iren_volatile_momentum_stocks/backtest.py 의 find_common_start /
build_momentum_weights / run_rotation / donchian_trailing_stop_positions /
run_trend_following_single / run_trend_following_basket 를 import로 그대로 재사용(재발명 없음).
"""
import json

import numpy as np
import pandas as pd

from common_era import BASKETS, BENCH, OUT_DIR, FEE_BPS, load_histories, closes_frame, metrics_from_returns

# 작업27 원본 챔피언 로직 재사용 (새 방법론 발명 없음). 모듈 이름 충돌을 피하려고 basket_common
# 계열의 관례대로 이 폴더 공용 모듈은 common_era.py로 명명했다(원본 common.py와 별도).
from backtest import (  # noqa: E402  (analysis/2026-08-16.../backtest.py, sys.path 에 이미 추가됨)
    find_common_start,
    run_rotation,
    donchian_trailing_stop_positions,
    run_trend_following_single,
    run_trend_following_basket,
)
from core.backtest_engine import run_buy_and_hold

ENTRY_WINDOW = 20
STOP_PCT = 0.15
MOM_WINDOW = 126  # IREN 연구와 동일 (6개월 웜업 후 랭킹)


def log(msg):
    print(f"[bt] {msg}", flush=True)


def basket_static_buy_hold(closes: pd.DataFrame, start: pd.Timestamp) -> tuple[dict, pd.Series]:
    sliced = closes[closes.index >= start]
    n = sliced.shape[1]
    shares = (1.0 / n) / sliced.iloc[0]
    equity = (sliced * shares).sum(axis=1) * 100.0
    ret = equity.pct_change().fillna(0.0)
    return metrics_from_returns(ret)


def main():
    result = {"meta": {
        "fee_bps_oneway": FEE_BPS, "round_trip_cost_pct": FEE_BPS * 2 / 100,
        "entry_window": ENTRY_WINDOW, "stop_pct": STOP_PCT, "momentum_window_days": MOM_WINDOW,
    }}

    for name, cfg in BASKETS.items():
        log(f"===== 바스켓: {name} ({cfg['label']}) =====")
        tickers = cfg["tickers"]
        rep = cfg["representative"]
        end = cfg["end"]
        load_start = cfg["load_start"]
        top_n = max(1, (len(tickers) + 1) // 2)

        log(f"  SPY 벤치마크 로딩 ({load_start}~{end})...")
        spy_hist = load_histories(BENCH, load_start, end)
        spy_close = closes_frame(spy_hist)["SPY"]

        hist = load_histories(tickers, load_start, end)
        closes = closes_frame(hist)
        listing_dates = {
            t: (closes[t].first_valid_index().date().isoformat() if t in closes and closes[t].first_valid_index() is not None else None)
            for t in tickers
        }
        log(f"  상장/데이터 시작일: {listing_dates}")

        common_start = find_common_start(closes.dropna(how="all"), MOM_WINDOW)
        log(f"  공통시작일(모멘텀 웜업 {MOM_WINDOW}거래일 확보): {common_start.date()} ~ {end}")

        entry = {
            "tickers": tickers,
            "representative": rep,
            "label": cfg["label"],
            "narrative": cfg["narrative"],
            "load_start": load_start,
            "listing_dates": listing_dates,
            "common_start": common_start.date().isoformat(),
            "end": end,
            "top_n": top_n,
        }

        # 1) 대표종목 매수후보유 (전체이력부터, 공통구간)
        rep_bh_full = run_buy_and_hold(rep, start=listing_dates[rep], end=end, fee_bps=FEE_BPS)
        rep_close_common = closes[rep][closes.index >= common_start].dropna()
        rep_ret_common = rep_close_common.pct_change().fillna(0.0)
        rep_bh_common_m, _ = metrics_from_returns(rep_ret_common)
        entry["representative_buy_hold_full"] = {"metrics": rep_bh_full.metrics, "start": listing_dates[rep], "end": end}
        entry["representative_buy_hold_common_window"] = rep_bh_common_m
        log(f"  대표종목({rep}) 매수후보유 공통구간: 샤프={rep_bh_common_m['sharpe']} MDD={rep_bh_common_m['mdd']}")

        # 2) 바스켓 정적 매수후보유
        m_bh, eq_bh = basket_static_buy_hold(closes, common_start)
        entry["basket_static_buy_hold"] = m_bh
        log(f"  바스켓 정적 매수후보유: 샤프={m_bh['sharpe']} MDD={m_bh['mdd']}")

        # 3) SPY 벤치마크(같은 공통구간)
        spy_common = spy_close[spy_close.index >= common_start].dropna()
        spy_ret = spy_common.pct_change().fillna(0.0)
        m_spy, _ = metrics_from_returns(spy_ret)
        entry["spy_buy_hold_common_window"] = m_spy
        log(f"  SPY(동일구간): 샤프={m_spy['sharpe']} MDD={m_spy['mdd']}")

        # 4) 바스켓 내 모멘텀 로테이션
        m_rot, eq_rot, _ = run_rotation(closes, common_start, MOM_WINDOW, top_n)
        entry["momentum_rotation"] = m_rot
        log(f"  모멘텀 로테이션(top{top_n}): 샤프={m_rot['sharpe']} MDD={m_rot['mdd']}")

        # 5) 추세추종: 대표종목 단일 + 바스켓
        m_tf_single, eq_tf_single, pos_single = run_trend_following_single(
            closes[rep].dropna(), common_start, ENTRY_WINDOW, STOP_PCT
        )
        m_tf_basket, eq_tf_basket, pos_basket = run_trend_following_basket(
            closes, common_start, ENTRY_WINDOW, STOP_PCT
        )
        entry["trend_following_single"] = m_tf_single
        entry["trend_following_basket"] = m_tf_basket
        log(f"  추세추종 단일({rep}): 샤프={m_tf_single['sharpe']} MDD={m_tf_single['mdd']}")
        log(f"  추세추종 바스켓: 샤프={m_tf_basket['sharpe']} MDD={m_tf_basket['mdd']}")

        # 나중 순열검정/부트스트랩에 쓸 일별 전략수익률 CSV로 저장
        sliced_close = closes[rep][closes.index >= common_start].dropna()
        pos_sliced = pos_single.loc[sliced_close.index]
        daily_ret = sliced_close.pct_change().fillna(0.0)
        executed = pos_sliced.shift(1).fillna(0).astype(float)
        turnover = executed.diff().abs().fillna(0.0)
        from common_era import COST_RATE
        single_strat_ret = daily_ret * executed - turnover * COST_RATE
        single_strat_ret.to_csv(f"{OUT_DIR}/{name}_single_trend_ret.csv")

        n_active = pos_basket.reindex(closes.index).fillna(0).sum(axis=1).replace(0, np.nan)
        weights = pos_basket.reindex(closes.index).fillna(0).div(n_active, axis=0).fillna(0.0)
        sliced_closes = closes[closes.index >= common_start]
        w = weights.loc[sliced_closes.index]
        daily_ret_b = sliced_closes.pct_change().fillna(0.0)
        executed_w = w.shift(1).fillna(0.0)
        port_ret = (daily_ret_b * executed_w).sum(axis=1)
        cost = executed_w.diff().abs().sum(axis=1).fillna(0.0) * COST_RATE
        basket_strat_ret = port_ret - cost
        basket_strat_ret.to_csv(f"{OUT_DIR}/{name}_basket_trend_ret.csv")

        # 참고: 이 시대의 실제 정점->저점 낙폭(전체이력 기준, 공통구간 제약 없이) — "진짜 극단적
        # 약세장을 포함하는가"를 리포트에서 직접 뒷받침하는 수치
        full_close = closes[rep].dropna()
        running_max = full_close.cummax()
        dd = (full_close / running_max - 1.0)
        entry["representative_full_history_max_drawdown_pct"] = round(float(dd.min()) * 100, 1)
        log(f"  {rep} 전체이력 최대낙폭(공통구간 제약 없음): {entry['representative_full_history_max_drawdown_pct']}%")

        result[name] = entry

    with open(f"{OUT_DIR}/backtest_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/backtest_results.json")


if __name__ == "__main__":
    main()
