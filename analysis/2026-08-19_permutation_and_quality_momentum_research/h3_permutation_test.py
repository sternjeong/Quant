"""H3 — 작업27의 IREN류 추세추종(돈치안20+15%트레일링스탑) 챔피언이 순열검정을 통과하는가.

작업21(No.06)이 멀티에셋 모멘텀 로테이션에 적용한 순열검정은 "매달 상위4개 랭킹 대신 양(+)모멘텀
후보 중 무작위 4개를 뽑아도 비슷한가"를 봤다 — 월별 횡단면 랭킹/선택 스텝이 있는 전략에만 적용
가능한 방법이라, 랭킹/선택 스텝이 아예 없는(바스켓 전종목에 독립적으로 규칙을 적용하는) 작업27의
추세추종 규칙에는 그대로 이식할 수 없다(작업21의 원본 스크립트 `scripts/_sharpe_research_round4.py`도
연구 완료 후 관례대로 삭제됨).

대신 이 저장소의 백테스트 엔진(`core/backtest_engine.py`, 작업13/14 — Masters의 "4대 검증 테스트"의
하나로 이미 구현·pytest 검증된 공식 순열검정 인프라)에 있는 `_shuffle_daily_bars`를 **코드 그대로**
재사용한다. 이 함수는 각 날짜의 "전일 종가 대비 시가/고가/저가/종가 비율(캔들 모양)"은 보존한 채
날짜의 등장 "순서"만 무작위로 섞어, 변동성/드리프트 분포는 실제 데이터와 동일하지만 추세·자기상관은
사라진 가짜 시계열을 만든다 — 추세추종 전략의 순열검정에 정확히 맞는 귀무가설("이 순서/패턴이
아니라 순수 노이즈에도 이 정도 샤프가 우연히 나올 수 있는가")을 제공한다. `core.backtest_engine.
run_permutation_test`가 정확히 이 함수로 단일종목·단일 지표전략 순열검정을 이미 수행하지만
그 함수 자체는 `run_backtest(ticker, indicator_config, ...)` 형태의 단일종목 지표엔진 백테스트에
결합돼 있어 이 바스켓 전략(6종목 독립신호 + 동일가중 합성)에는 직접 적용할 수 없다 — 그래서
셔플 함수만 가져와 작업27의 실제 챔피언 로직(`analysis/2026-08-16_iren_volatile_momentum_stocks/
backtest.py`의 `donchian_trailing_stop_positions`/`run_trend_following_basket`, 코드 그대로 재사용)
위에서 돌린다.
"""
import json
import sys

PROJECT_ROOT = "/workspaces/Quant/.claude/worktrees/agent-ad691d1b13ff1f0a9"
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, f"{PROJECT_ROOT}/analysis/2026-08-16_iren_volatile_momentum_stocks")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, _shuffle_daily_bars
from core.market_data import get_price_history

# 작업27 챔피언 로직 그대로 재사용 (analysis/2026-08-16_iren_volatile_momentum_stocks/backtest.py)
from backtest import donchian_trailing_stop_positions  # noqa: E402
from common import PIVOT_BASKET, END, COST_RATE  # noqa: E402

OUT_DIR = f"{PROJECT_ROOT}/analysis/2026-08-19_permutation_and_quality_momentum_research"
COMMON_START = pd.Timestamp("2022-05-19")  # report_data.json의 main_basket_start
ENTRY_WINDOW = 20
STOP_PCT = 0.15
N_PERMUTATIONS = 200
SEED = 20260819


def log(msg):
    print(f"[h3] {msg}", flush=True)


def metrics_from_ret(ret: pd.Series) -> dict:
    equity = (1.0 + ret.fillna(0.0)).cumprod() * 100.0
    if len(equity) > 0:
        equity.iloc[0] = 100.0
    return calculate_metrics(equity, [], equity.index[0], equity.index[-1])


def basket_sharpe_from_closes(closes: pd.DataFrame, entry_window: int, stop_pct: float) -> dict:
    """run_trend_following_basket(analysis/.../backtest.py)과 동일 로직, 여기선 필요한 지표만 반환."""
    positions = pd.DataFrame({
        t: donchian_trailing_stop_positions(closes[t].dropna(), entry_window, stop_pct)
        for t in closes.columns
    })
    positions = positions.reindex(closes.index).fillna(0).astype(int)
    n_active = positions.sum(axis=1).replace(0, np.nan)
    weights = positions.div(n_active, axis=0).fillna(0.0)

    sliced_closes = closes[closes.index >= COMMON_START]
    w = weights.loc[sliced_closes.index]
    daily_ret = sliced_closes.pct_change().fillna(0.0)
    executed_w = w.shift(1).fillna(0.0)
    port_ret = (daily_ret * executed_w).sum(axis=1)
    turnover = executed_w.diff().abs().sum(axis=1).fillna(0.0)
    cost = turnover * COST_RATE
    port_ret_after_cost = port_ret - cost
    return metrics_from_ret(port_ret_after_cost)


def single_sharpe_from_close(close: pd.Series, entry_window: int, stop_pct: float) -> dict:
    position = donchian_trailing_stop_positions(close, entry_window, stop_pct)
    sliced_close = close[close.index >= COMMON_START]
    pos_sliced = position.loc[sliced_close.index]
    daily_ret = sliced_close.pct_change().fillna(0.0)
    executed = pos_sliced.shift(1).fillna(0).astype(float)
    turnover = executed.diff().abs().fillna(0.0)
    strat_ret = daily_ret * executed - turnover * COST_RATE
    return metrics_from_ret(strat_ret)


def load_raw(tickers, end=END):
    """원본 OHLCV(전 이력) 로드 — _shuffle_daily_bars가 Open/High/Low/Close/Volume을 요구."""
    raw = {}
    for t in tickers:
        df = get_price_history(t, start="2005-01-01", end=end, use_cache=True)
        raw[t] = df
    return raw


def main():
    result = {
        "meta": {
            "entry_window": ENTRY_WINDOW, "stop_pct": STOP_PCT, "n_permutations": N_PERMUTATIONS,
            "common_start": COMMON_START.date().isoformat(), "end": END, "seed": SEED,
            "methodology": (
                "core.backtest_engine._shuffle_daily_bars 재사용 — 각 날짜의 캔들 모양(시/고/저/종가의 "
                "전일종가 대비 비율)은 보존하고 날짜 등장 순서만 무작위로 섞어 추세/자기상관을 제거한 "
                "가짜 시계열 200개를 만들고, 동일한 돈치안(20)+15%트레일링스탑 바스켓 규칙을 그대로 적용."
            ),
        }
    }

    log("원본 OHLCV 로딩...")
    raw = load_raw(PIVOT_BASKET)
    for t, df in raw.items():
        log(f"   {t}: {len(df)}행, {df.index[0].date()} ~ {df.index[-1].date()}")

    # 실제(비셔플) 챔피언 재확인
    closes_actual = pd.DataFrame({t: raw[t]["Close"] for t in PIVOT_BASKET}).sort_index()
    m_actual_basket = basket_sharpe_from_closes(closes_actual, ENTRY_WINDOW, STOP_PCT)
    m_actual_single = single_sharpe_from_close(raw["IREN"]["Close"].dropna(), ENTRY_WINDOW, STOP_PCT)
    log(f"실제 바스켓 챔피언 재확인: {m_actual_basket}")
    log(f"실제 IREN 단일 재확인: {m_actual_single}")
    result["actual_basket"] = m_actual_basket
    result["actual_single_iren"] = m_actual_single

    # ------------------------------------------------------------------
    # 순열검정 — 바스켓 챔피언 (주 검정 대상)
    # ------------------------------------------------------------------
    log(f"바스켓 순열검정 {N_PERMUTATIONS}회 시작...")
    rng = np.random.default_rng(SEED)
    permuted_basket_sharpes = []
    for it in range(N_PERMUTATIONS):
        synth_closes = {}
        for t in PIVOT_BASKET:
            df = raw[t]
            window_start = df.index[0]
            window_end = df.index[-1]
            synth_df = _shuffle_daily_bars(df, window_start, window_end, rng)
            synth_closes[t] = synth_df["Close"]
        synth_closes_df = pd.DataFrame(synth_closes).sort_index()
        m = basket_sharpe_from_closes(synth_closes_df, ENTRY_WINDOW, STOP_PCT)
        permuted_basket_sharpes.append(m["sharpe"])
        if (it + 1) % 40 == 0:
            log(f"   {it + 1}/{N_PERMUTATIONS} 완료 (지금까지 평균 샤프 {np.mean(permuted_basket_sharpes):.3f})")

    actual_sharpe_basket = m_actual_basket["sharpe"]
    worse = sum(1 for s in permuted_basket_sharpes if s < actual_sharpe_basket)
    better_or_equal = sum(1 for s in permuted_basket_sharpes if s >= actual_sharpe_basket)
    percentile_basket = round(100.0 * worse / len(permuted_basket_sharpes), 2)
    p_value_basket = round((better_or_equal + 1) / (N_PERMUTATIONS + 1), 4)
    log(f"바스켓: 실제 샤프 {actual_sharpe_basket} -> 백분위 {percentile_basket}, p={p_value_basket}, "
        f"무작위 200회 평균 {np.mean(permuted_basket_sharpes):.3f} (표준편차 {np.std(permuted_basket_sharpes):.3f})")

    result["permutation_basket"] = {
        "actual_sharpe": actual_sharpe_basket,
        "permuted_sharpes": [round(float(s), 4) for s in permuted_basket_sharpes],
        "permuted_mean": round(float(np.mean(permuted_basket_sharpes)), 4),
        "permuted_std": round(float(np.std(permuted_basket_sharpes)), 4),
        "percentile": percentile_basket,
        "p_value": p_value_basket,
    }

    # ------------------------------------------------------------------
    # 순열검정 — IREN 단일종목 (부가 검정, 작업27이 "스탑폭 전 구간에서 안정적"이라 평했던 대상)
    # ------------------------------------------------------------------
    log(f"IREN 단일종목 순열검정 {N_PERMUTATIONS}회 시작...")
    rng2 = np.random.default_rng(SEED + 1)
    permuted_single_sharpes = []
    df_iren = raw["IREN"]
    for it in range(N_PERMUTATIONS):
        synth_df = _shuffle_daily_bars(df_iren, df_iren.index[0], df_iren.index[-1], rng2)
        m = single_sharpe_from_close(synth_df["Close"].dropna(), ENTRY_WINDOW, STOP_PCT)
        permuted_single_sharpes.append(m["sharpe"])

    actual_sharpe_single = m_actual_single["sharpe"]
    worse_s = sum(1 for s in permuted_single_sharpes if s < actual_sharpe_single)
    better_s = sum(1 for s in permuted_single_sharpes if s >= actual_sharpe_single)
    percentile_single = round(100.0 * worse_s / len(permuted_single_sharpes), 2)
    p_value_single = round((better_s + 1) / (N_PERMUTATIONS + 1), 4)
    log(f"IREN단일: 실제 샤프 {actual_sharpe_single} -> 백분위 {percentile_single}, p={p_value_single}, "
        f"무작위 200회 평균 {np.mean(permuted_single_sharpes):.3f} (표준편차 {np.std(permuted_single_sharpes):.3f})")

    result["permutation_single_iren"] = {
        "actual_sharpe": actual_sharpe_single,
        "permuted_sharpes": [round(float(s), 4) for s in permuted_single_sharpes],
        "permuted_mean": round(float(np.mean(permuted_single_sharpes)), 4),
        "permuted_std": round(float(np.std(permuted_single_sharpes)), 4),
        "percentile": percentile_single,
        "p_value": p_value_single,
    }

    # ------------------------------------------------------------------
    # 스탑폭/진입창 세밀 스윕 — 15%가 고립된 스파이크인지 완만한 고원인지
    # ------------------------------------------------------------------
    log("스탑폭 세밀 스윕 (entry_window=20 고정)...")
    stop_sweep = []
    for sp in [0.10, 0.125, 0.15, 0.175, 0.20, 0.225, 0.25, 0.275, 0.30, 0.325, 0.35]:
        m = basket_sharpe_from_closes(closes_actual, ENTRY_WINDOW, sp)
        stop_sweep.append({"stop_pct": sp, **m})
        log(f"   stop_pct={sp}: sharpe={m['sharpe']}, mdd={m['mdd']}, cagr={m['cagr']}")
    result["stop_pct_fine_sweep"] = stop_sweep

    log("진입창(entry_window) 스윕 (stop_pct=0.15 고정)...")
    window_sweep = []
    for ew in [10, 15, 20, 25, 30, 40, 55]:
        m = basket_sharpe_from_closes(closes_actual, ew, STOP_PCT)
        window_sweep.append({"entry_window": ew, **m})
        log(f"   entry_window={ew}: sharpe={m['sharpe']}, mdd={m['mdd']}, cagr={m['cagr']}")
    result["entry_window_sweep"] = window_sweep

    # 2D 그리드(선택 지점) — 두 파라미터가 동시에 움직일 때도 15/20 근방이 강건한지
    log("2D 그리드 스윕 (stop_pct x entry_window, 축소판)...")
    grid = []
    for ew in [15, 20, 25, 30]:
        for sp in [0.125, 0.15, 0.175, 0.20, 0.25]:
            m = basket_sharpe_from_closes(closes_actual, ew, sp)
            grid.append({"entry_window": ew, "stop_pct": sp, "sharpe": m["sharpe"], "mdd": m["mdd"], "cagr": m["cagr"]})
    result["grid_2d_sweep"] = grid
    log(f"   2D 그리드 {len(grid)}개 조합 완료")

    with open(f"{OUT_DIR}/h3_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/h3_results.json")


if __name__ == "__main__":
    main()
