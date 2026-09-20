"""H_corr 후속 - 블록부트스트랩 표본오차 감사 + 순열검정(순환이동 플라시보).

h_signals_and_backtest.py는 계산비용 때문에 풀(40종목) 상관관계(pool_corr)를 6개 창 중
full_2019_2026/gfc_2008/bear_2022(파생) 3개에서만 계산했고, covid_2020/selloff_2018/
correction_2015_2016 3개는 생략했다(본문 disclose). 그래서 이 감사의 **주 신호는 holdings_corr**
(보유종목 3~10개 상관관계, 6개 창 전부 계산됨)로 삼고, pool_corr는 그것이 계산된 곳에서만 보조
증거로 다룬다.

1. 블록부트스트랩 표본오차(작업44 H33과 완전히 동일한 방법 - moving_block_bootstrap_sharpe 함수를
   그대로 복사해 재사용, 재구현이 아니라 동일 코드): 순환 이동블록, L=10/20/40(중심 20),
   창×구성당 2,000회. core_alone/core_plus_static_satellite/switch_spy/switch_holdings_corr/
   switch_spy_or_holdings_corr 5개 구성 x 6개 창. 이 프로그램의 핵심 규칙("순열검정만으로 끝내지
   않는다, 반드시 표본오차를 감사한다")을 그대로 따른다.
2. 순열검정(순환이동 플라시보): holdings_corr와 pool_corr 두 스위치 신호 각각의 실제 on/off
   시점이 무작위 타이밍보다 나은지 확인한다(둘 다 full_2019_2026 창에서만 - pool_corr는 이 창에서
   계산됐고, holdings_corr는 어디서나 계산되지만 비교 가능성을 위해 같은 창을 씀). 신호(불/베어
   시계열)를 랜덤 오프셋만큼 순환이동(circular shift)시켜 "같은 온/오프 비율, 같은 블록구조를
   가졌지만 실제 시장과의 시점 관계는 끊긴" 플라시보 신호를 500회 만들고, 그 각각으로 스위치한
   코어+새틀라이트 블렌드의 Sharpe를 계산해 실제 신호의 Sharpe가 플라시보 분포에서 몇 백분위에
   있는지를 본다. (H9/H10이 쓴 "무작위 종목선택 대비 백분위" placebo와 같은 정신을 시그널 타이밍에
   적용한 변형 - 이 라운드에서 새로 설계, 근거는 본문에 명시.)
3. H33b와 동일한 방식(디리클레 가중치 x 부트스트랩 표본오차 결합전파)으로 holdings_corr/
   spy_or_holdingscorr 스위치가 static_satellite/switch_spy 대비 기댓값 관점에서 이기는 draw
   비율(승률)을 계산한다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
TRADING_DAYS = 252

EPISODES = {
    "full_2019_2026": ("2019-08-12", "2026-08-19", "2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30"),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
}
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
BOOT_CONFIGS = ["core_alone", "core_plus_static_satellite", "switch_spy", "switch_holdings_corr", "switch_spy_or_holdings_corr"]
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
SEED = 20260914

# 작업39(H22)/작업44(H33b)와 동일한 기저확률(base-rate) 시나리오 - 재사용
BASE_RATE_SCENARIOS = {
    "base": {"full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04, "bear_2022": 0.10,
             "selloff_2018": 0.16, "correction_2015_2016": 0.17},
    "calm_heavy": {"full_2019_2026": 0.65, "gfc_2008": 0.015, "covid_2020": 0.02, "bear_2022": 0.065,
                   "selloff_2018": 0.12, "correction_2015_2016": 0.13},
    "crisis_heavy": {"full_2019_2026": 0.35, "gfc_2008": 0.06, "covid_2020": 0.07, "bear_2022": 0.14,
                     "selloff_2018": 0.19, "correction_2015_2016": 0.19},
}
K_CENTRAL = 30.0
N_DRAWS = 10000


def log(msg):
    print(f"[h_boot] {msg}", flush=True)


def slice_window(s: pd.Series, start: str, end: str) -> pd.Series:
    return s[(s.index >= start) & (s.index <= end)]


def annualized_sharpe(ret: np.ndarray) -> float:
    if len(ret) < 2:
        return float("nan")
    mu, sd = np.mean(ret), np.std(ret, ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(mu / sd * np.sqrt(TRADING_DAYS))


def moving_block_bootstrap_sharpe(ret: np.ndarray, block_len: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """작업44(H33) h33_block_bootstrap_sample_error.py의 moving_block_bootstrap_sharpe와 동일한
    순환(wrap-around) 이동블록부트스트랩 - 재구현 아님, 동일 알고리즘을 그대로 복사."""
    n = len(ret)
    if n == 0:
        return np.full(n_boot, np.nan)
    block_len = min(block_len, n)
    n_blocks_needed = int(np.ceil(n / block_len))
    max_start = n
    sharpes = np.empty(n_boot)
    ext = np.concatenate([ret, ret])
    for b in range(n_boot):
        starts = rng.integers(0, max_start, size=n_blocks_needed)
        pieces = [ext[s:s + block_len] for s in starts]
        synth = np.concatenate(pieces)[:n]
        sharpes[b] = annualized_sharpe(synth)
    return sharpes


def gather_window_returns() -> dict:
    out = {}
    for label in EPISODE_ORDER:
        full_start, full_end, crisis_start, crisis_end = EPISODES[label]
        out[label] = {"window_used": [crisis_start if label != "full_2019_2026" else full_start,
                                       crisis_end if label != "full_2019_2026" else full_end]}
        # bear_2022는 full_2019_2026과 정확히 같은 전체기간 구축을 재사용한 창이라(h_signals_and_backtest
        # main()의 절약 조치와 동일한 이유) CSV도 별도 저장분이 없다 - full_2019_2026 CSV를 그대로 읽어
        # bear_2022의 위기창만 슬라이스한다.
        source_label = "full_2019_2026" if label == "bear_2022" else label
        for cfg in BOOT_CONFIGS:
            fpath = OUT_DIR / f"{source_label}_{cfg}.csv"
            s = pd.read_csv(fpath, index_col=0, parse_dates=True).iloc[:, 0]
            ws, we = out[label]["window_used"]
            out[label][cfg] = slice_window(s, ws, we)
        out[label]["n_obs"] = int(len(out[label][BOOT_CONFIGS[0]]))
    return out


def bootstrap_all(window_returns: dict) -> tuple[dict, dict]:
    rng = np.random.default_rng(SEED)
    summary, raw_samples = {}, {}
    for label in EPISODE_ORDER:
        d = window_returns[label]
        summary[label] = {"window_used": d["window_used"], "n_obs": d["n_obs"], "by_config": {}}
        raw_samples[label] = {}
        for cfg in BOOT_CONFIGS:
            ret = d[cfg].values.astype(float)
            point_sharpe = annualized_sharpe(ret)
            per_block, samples_l20 = {}, None
            for L in BLOCK_LENGTHS:
                boot = moving_block_bootstrap_sharpe(ret, L, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                if len(boot) == 0:
                    per_block[str(L)] = None
                    continue
                per_block[str(L)] = {
                    "mean": float(np.mean(boot)), "std": float(np.std(boot)),
                    "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
                }
                if L == 20:
                    samples_l20 = boot
            summary[label]["by_config"][cfg] = {"point_estimate_sharpe": point_sharpe, "bootstrap_by_block_len": per_block}
            raw_samples[label][cfg] = samples_l20.tolist() if samples_l20 is not None else []
            log(f"  {label}/{cfg}: point={point_sharpe:.3f}, L20 CI90={per_block.get('20', {}).get('ci90')}")
    return summary, raw_samples


# ---------------------------------------------------------------------------
# 순열검정(순환이동 플라시보) - pool_corr 스위치 신호가 무작위 타이밍보다 나은지
# ---------------------------------------------------------------------------

def circular_shift_permutation_test(core_ret: pd.Series, sat_ret: pd.Series, bull_signal: pd.Series,
                                      satellite_weight: float, n_perm: int = 500, seed: int = SEED) -> dict:
    """bull_signal(불/베어 시계열)을 무작위 오프셋만큼 순환이동시켜 온/오프 비율과 블록구조는
    그대로 유지한 채 실제 시장과의 시점 관계만 끊은 플라시보 신호를 n_perm개 생성, 각각으로 스위치한
    코어+새틀라이트 블렌드의 Sharpe를 계산해 실제 신호의 Sharpe가 그 분포에서 몇 백분위인지 반환."""
    import sys
    sys.path.insert(0, "/opt/quant")
    sys.path.insert(0, "/opt/quant/analysis/2026-08-19_champion_beta_and_satellite_research")
    sys.path.insert(0, "/opt/quant/analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test")
    sys.path.insert(0, "/opt/quant/analysis/2026-08-22_regime_conditional_satellite_switch")
    sys.path.insert(0, "/opt/quant/analysis/2026-08-22_satellite_specific_crisis_signal_and_2021_case_study")
    from h12_regime_switch import build_regime_switched_weight_series, blend_returns_time_varying

    idx = core_ret.index
    bull_aligned = bull_signal.reindex(idx).fillna(True)
    values = bull_aligned.values.astype(bool)
    n = len(values)

    def sharpe_for_bull_array(arr: np.ndarray) -> float:
        bull_s = pd.Series(arr, index=idx)
        wser = build_regime_switched_weight_series(idx, bull_s, satellite_weight)
        blended = blend_returns_time_varying(core_ret, sat_ret, wser)
        return annualized_sharpe(blended.values.astype(float))

    actual_sharpe = sharpe_for_bull_array(values)

    rng = np.random.default_rng(seed)
    perm_sharpes = np.empty(n_perm)
    for i in range(n_perm):
        shift = int(rng.integers(1, n - 1))
        shifted = np.roll(values, shift)
        perm_sharpes[i] = sharpe_for_bull_array(shifted)

    perm_sharpes = perm_sharpes[~np.isnan(perm_sharpes)]
    percentile = float(np.mean(perm_sharpes <= actual_sharpe) * 100) if len(perm_sharpes) else None
    return {
        "actual_sharpe": actual_sharpe, "n_perm": int(len(perm_sharpes)),
        "perm_mean": float(np.mean(perm_sharpes)) if len(perm_sharpes) else None,
        "perm_std": float(np.std(perm_sharpes)) if len(perm_sharpes) else None,
        "percentile_of_actual": percentile,
        "bear_day_fraction": float((~values).mean()),
    }


# ---------------------------------------------------------------------------
# 디리클레 가중치 x 부트스트랩 결합전파 (H33b와 동일 방식)
# ---------------------------------------------------------------------------

def dirichlet_draws(rates: dict, n: int, rng: np.random.Generator) -> np.ndarray:
    alpha = np.array([rates[ep] * K_CENTRAL for ep in EPISODE_ORDER])
    return rng.dirichlet(alpha, size=n)


def combined_win_rate(raw_samples: dict, scen_rates: dict, cfg_a: str, cfg_b: str, rng: np.random.Generator) -> dict:
    dir_draws = dirichlet_draws(scen_rates, N_DRAWS, rng)
    ev = {}
    for cfg in (cfg_a, cfg_b):
        per_ep = []
        for ep in EPISODE_ORDER:
            samples = np.array(raw_samples[ep][cfg])
            idx = rng.integers(0, len(samples), size=N_DRAWS)
            per_ep.append(samples[idx])
        stacked = np.column_stack(per_ep)
        ev[cfg] = np.sum(stacked * dir_draws, axis=1)
    gap = ev[cfg_a] - ev[cfg_b]
    return {
        "pct_draws_a_ahead": float(np.mean(gap > 0)),
        "mean_gap": float(np.mean(gap)),
        "ci90_gap": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
    }


def main():
    t0 = time.time()
    log("일별수익률 CSV 로드...")
    window_returns = gather_window_returns()
    for ep in EPISODE_ORDER:
        log(f"  {ep}: n_obs={window_returns[ep]['n_obs']}")

    log("블록부트스트랩 (2,000회 x 3개 블록길이 x 5개구성 x 6개창)...")
    boot_summary, raw_samples = bootstrap_all(window_returns)

    log("순열검정(순환이동 플라시보, pool_corr/holdings_corr 신호, full_2019_2026 창)...")
    core_full = window_returns["full_2019_2026"]["core_alone"]
    static_full = pd.read_csv(OUT_DIR / "full_2019_2026_core_plus_static_satellite.csv", index_col=0, parse_dates=True).iloc[:, 0]
    # sat_ret을 core/static으로부터 역산: static = (1-w)core + w*sat -> sat = (static-(1-w)core)/w
    w = 0.15
    sat_full = (static_full - (1 - w) * core_full) / w
    bulls_full = pd.read_csv(OUT_DIR / "full_2019_2026_bull_signals.csv", index_col=0, parse_dates=True)

    perm_result_pool = circular_shift_permutation_test(core_full, sat_full, bulls_full["pool_corr_bull"].astype(bool), w, n_perm=500)
    log(f"  pool_corr 순열검정: actual_sharpe={perm_result_pool['actual_sharpe']:.3f}, "
        f"percentile={perm_result_pool['percentile_of_actual']}")
    perm_result_holdings = circular_shift_permutation_test(core_full, sat_full, bulls_full["holdings_corr_bull"].astype(bool), w, n_perm=500, seed=SEED + 1)
    log(f"  holdings_corr 순열검정: actual_sharpe={perm_result_holdings['actual_sharpe']:.3f}, "
        f"percentile={perm_result_holdings['percentile_of_actual']}")

    log("디리클레 x 부트스트랩 결합전파 승률(holdings_corr 기준, 6개 창 전부)...")
    rng = np.random.default_rng(SEED)
    combined = {}
    for scen_name, rates in BASE_RATE_SCENARIOS.items():
        total = sum(rates.values())
        norm_rates = {k: v / total for k, v in rates.items()}
        combined[scen_name] = {
            "holdings_corr_vs_static": combined_win_rate(raw_samples, norm_rates, "switch_holdings_corr", "core_plus_static_satellite", rng),
            "holdings_corr_vs_spy_switch": combined_win_rate(raw_samples, norm_rates, "switch_holdings_corr", "switch_spy", rng),
            "spy_or_holdingscorr_vs_spy_switch": combined_win_rate(raw_samples, norm_rates, "switch_spy_or_holdings_corr", "switch_spy", rng),
            "spy_or_holdingscorr_vs_static": combined_win_rate(raw_samples, norm_rates, "switch_spy_or_holdings_corr", "core_plus_static_satellite", rng),
        }
        log(f"  {scen_name}: holdings_corr_vs_static={combined[scen_name]['holdings_corr_vs_static']['pct_draws_a_ahead']:.3f}, "
            f"spy_or_holdingscorr_vs_spy={combined[scen_name]['spy_or_holdingscorr_vs_spy_switch']['pct_draws_a_ahead']:.3f}")

    out = {
        "meta": {"seed": SEED, "n_boot": N_BOOT, "block_lengths": BLOCK_LENGTHS, "n_draws": N_DRAWS,
                 "n_perm": 500, "episode_order": EPISODE_ORDER, "boot_configs": BOOT_CONFIGS},
        "bootstrap": boot_summary,
        "permutation_test_pool_corr": perm_result_pool,
        "permutation_test_holdings_corr": perm_result_holdings,
        "combined_dirichlet_x_bootstrap": combined,
    }
    with open(OUT_DIR / "h_boot_perm_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: h_boot_perm_results.json (총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
