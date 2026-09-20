"""신규 2개 바스켓(EV SPAC 붐-버스트/희귀질환 바이오텍)의 추세추종 챔피언에 에이전트B(트랙D) 감사
기계(순열검정+블록부트스트랩)를 그대로 적용 — 트랙C 전체 관례(agent_c_tenbagger.md persona
"에이전트 B가 쓰는 순열검정+블록부트스트랩 감사 기계도 여기 그대로 적용한다") 그대로 계승.

analysis/2026-09-14_nonai_control_basket_volatility_momentum/audit_stats.py 와 동일한 방법론·
코드 구조(재구현 없음, import만 다름).
"""
import json
import sys

import numpy as np
import pandas as pd

from basket_common2 import BASKETS, OUT_DIR, END, COST_RATE

sys.path.insert(0, "/opt/quant/analysis/2026-08-19_champion_beta_and_satellite_research")
sys.path.insert(0, "/opt/quant/analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test")
sys.path.insert(0, "/opt/quant/analysis/2026-08-23_block_bootstrap_sample_error_quantification")
from h33_block_bootstrap_sample_error import moving_block_bootstrap_sharpe, annualized_sharpe  # noqa: E402

from core.backtest_engine import calculate_metrics, _shuffle_daily_bars  # noqa: E402
from core.market_data import get_price_history  # noqa: E402

from backtest import donchian_trailing_stop_positions  # noqa: E402

ENTRY_WINDOW = 20
STOP_PCT = 0.15
N_PERMUTATIONS = 200
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
SEED = 20260919


def log(msg):
    print(f"[audit] {msg}", flush=True)


def metrics_from_ret(ret: pd.Series) -> dict:
    equity = (1.0 + ret.fillna(0.0)).cumprod() * 100.0
    if len(equity) > 0:
        equity.iloc[0] = 100.0
    return calculate_metrics(equity, [], equity.index[0], equity.index[-1])


def basket_sharpe_from_closes(closes: pd.DataFrame, common_start: pd.Timestamp, entry_window: int, stop_pct: float) -> tuple[dict, pd.Series]:
    positions = pd.DataFrame({
        t: donchian_trailing_stop_positions(closes[t].dropna(), entry_window, stop_pct)
        for t in closes.columns
    })
    positions = positions.reindex(closes.index).fillna(0).astype(int)
    n_active = positions.sum(axis=1).replace(0, np.nan)
    weights = positions.div(n_active, axis=0).fillna(0.0)

    sliced_closes = closes[closes.index >= common_start]
    w = weights.loc[sliced_closes.index]
    daily_ret = sliced_closes.pct_change().fillna(0.0)
    executed_w = w.shift(1).fillna(0.0)
    port_ret = (daily_ret * executed_w).sum(axis=1)
    turnover = executed_w.diff().abs().sum(axis=1).fillna(0.0)
    cost = turnover * COST_RATE
    port_ret_after_cost = port_ret - cost
    return metrics_from_ret(port_ret_after_cost), port_ret_after_cost


def single_sharpe_from_close(close: pd.Series, common_start: pd.Timestamp, entry_window: int, stop_pct: float) -> tuple[dict, pd.Series]:
    position = donchian_trailing_stop_positions(close, entry_window, stop_pct)
    sliced_close = close[close.index >= common_start]
    pos_sliced = position.loc[sliced_close.index]
    daily_ret = sliced_close.pct_change().fillna(0.0)
    executed = pos_sliced.shift(1).fillna(0).astype(float)
    turnover = executed.diff().abs().fillna(0.0)
    strat_ret = daily_ret * executed - turnover * COST_RATE
    return metrics_from_ret(strat_ret), strat_ret


def load_raw(tickers, end=END):
    raw = {}
    for t in tickers:
        df = get_price_history(t, start="2005-01-01", end=end, use_cache=True)
        raw[t] = df
    return raw


def permutation_test(raw: dict, tickers: list[str], common_start: pd.Timestamp, rng_seed: int, mode: str):
    rng = np.random.default_rng(rng_seed)
    permuted = []
    for it in range(N_PERMUTATIONS):
        if mode == "basket":
            synth_closes = {}
            for t in tickers:
                df = raw[t]
                synth_df = _shuffle_daily_bars(df, df.index[0], df.index[-1], rng)
                synth_closes[t] = synth_df["Close"]
            synth_df_all = pd.DataFrame(synth_closes).sort_index()
            m, _ = basket_sharpe_from_closes(synth_df_all, common_start, ENTRY_WINDOW, STOP_PCT)
        else:
            df = raw[tickers[0]]
            synth_df = _shuffle_daily_bars(df, df.index[0], df.index[-1], rng)
            m, _ = single_sharpe_from_close(synth_df["Close"].dropna(), common_start, ENTRY_WINDOW, STOP_PCT)
        permuted.append(m["sharpe"])
        if (it + 1) % 50 == 0:
            log(f"      순열 {it + 1}/{N_PERMUTATIONS}")
    return permuted


def main():
    result = {"meta": {
        "entry_window": ENTRY_WINDOW, "stop_pct": STOP_PCT, "n_permutations": N_PERMUTATIONS,
        "block_lengths": BLOCK_LENGTHS, "n_boot": N_BOOT, "seed": SEED, "end": END,
        "methodology": (
            "순열검정: core.backtest_engine._shuffle_daily_bars 재사용(작업32/작업77과 동일 방법). "
            "블록부트스트랩: h33_block_bootstrap_sample_error.moving_block_bootstrap_sharpe 그대로 "
            "재사용(작업48/77과 동일 방법)."
        ),
        "iren_reference": {
            "note": "작업48(감사1) 결과(비교 기준선)",
            "permutation_basket_percentile": 93.0, "permutation_basket_p": 0.075,
            "permutation_single_percentile": 100.0, "permutation_single_p": 0.005,
        },
    }}

    for name, cfg in BASKETS.items():
        log(f"===== 바스켓: {name} =====")
        tickers = cfg["tickers"]
        rep = cfg["representative"]
        raw = load_raw(tickers)
        closes_actual = pd.DataFrame({t: raw[t]["Close"] for t in tickers}).sort_index()

        from backtest import find_common_start
        common_start = find_common_start(closes_actual.dropna(how="all"), 126)

        m_actual_basket, basket_ret = basket_sharpe_from_closes(closes_actual, common_start, ENTRY_WINDOW, STOP_PCT)
        m_actual_single, single_ret = single_sharpe_from_close(raw[rep]["Close"].dropna(), common_start, ENTRY_WINDOW, STOP_PCT)
        log(f"  실제 바스켓 샤프: {m_actual_basket['sharpe']}, 실제 단일({rep}) 샤프: {m_actual_single['sharpe']}")

        entry = {"common_start": common_start.date().isoformat(), "representative": rep}

        log(f"  바스켓 순열검정 {N_PERMUTATIONS}회...")
        perm_basket = permutation_test(raw, tickers, common_start, SEED, "basket")
        actual_sharpe_basket = m_actual_basket["sharpe"]
        worse = sum(1 for s in perm_basket if s < actual_sharpe_basket)
        better_or_equal = sum(1 for s in perm_basket if s >= actual_sharpe_basket)
        pct_basket = round(100.0 * worse / len(perm_basket), 2)
        p_basket = round((better_or_equal + 1) / (N_PERMUTATIONS + 1), 4)
        log(f"  바스켓 순열검정: 백분위 {pct_basket}, p={p_basket}")

        log(f"  단일({rep}) 순열검정 {N_PERMUTATIONS}회...")
        perm_single = permutation_test(raw, [rep], common_start, SEED + 1, "single")
        actual_sharpe_single = m_actual_single["sharpe"]
        worse_s = sum(1 for s in perm_single if s < actual_sharpe_single)
        better_s = sum(1 for s in perm_single if s >= actual_sharpe_single)
        pct_single = round(100.0 * worse_s / len(perm_single), 2)
        p_single = round((better_s + 1) / (N_PERMUTATIONS + 1), 4)
        log(f"  단일 순열검정: 백분위 {pct_single}, p={p_single}")

        entry["permutation_basket"] = {
            "actual_sharpe": actual_sharpe_basket, "percentile": pct_basket, "p_value": p_basket,
            "permuted_mean": round(float(np.mean(perm_basket)), 4), "permuted_std": round(float(np.std(perm_basket)), 4),
        }
        entry["permutation_single"] = {
            "actual_sharpe": actual_sharpe_single, "percentile": pct_single, "p_value": p_single,
            "permuted_mean": round(float(np.mean(perm_single)), 4), "permuted_std": round(float(np.std(perm_single)), 4),
        }

        log("  블록부트스트랩...")
        rng = np.random.default_rng(SEED + 2)
        boot_out = {}
        for label, ret in (("basket", basket_ret), ("single", single_ret)):
            ret_arr = ret.values.astype(float)
            point = annualized_sharpe(ret_arr)
            by_block = {}
            for L in BLOCK_LENGTHS:
                boot = moving_block_bootstrap_sharpe(ret_arr, L, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                ci = (float(np.percentile(boot, 5)), float(np.percentile(boot, 95))) if len(boot) else (None, None)
                pct_le_zero = float(np.mean(boot <= 0)) if len(boot) else None
                by_block[str(L)] = {"ci90": ci, "pct_le_zero": pct_le_zero, "width": (ci[1] - ci[0]) if ci[0] is not None else None}
            boot_out[label] = {"point_estimate_sharpe": round(float(point), 4), "n_obs": len(ret_arr), "by_block_len": by_block}
        entry["bootstrap"] = boot_out
        log(f"  부트스트랩 완료 (L=20 폭: 바스켓 {boot_out['basket']['by_block_len']['20']['width']}, "
            f"단일 {boot_out['single']['by_block_len']['20']['width']})")

        result[name] = entry

    with open(f"{OUT_DIR}/audit_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/audit_results.json")


if __name__ == "__main__":
    main()
