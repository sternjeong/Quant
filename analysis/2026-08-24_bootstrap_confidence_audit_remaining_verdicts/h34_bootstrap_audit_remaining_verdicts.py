"""H34 - H33 블록부트스트랩 감사를 나머지 세 판정(H26/H28/H32)으로 확장.

H33(작업44, 18라운드)은 H22 핵심 비교(코어단독 vs 코어+정적새틀라이트) 하나에만 블록부트스트랩
표본오차 정량화를 적용했다. 이번 라운드는 정확히 같은 방법론(순환 이동블록부트스트랩, 블록길이
10/20/40일 중심 20일, 창당 2000회 재표본, H30식 디리클레 가중치와 결합 전파)을 아직 감사받지
않은 세 개의 주요 "채택" 판정에 확장한다:

  (a) H26 - 시스템(코어+새틀라이트) vs SPY 매수보유
  (b) H28 - 변동성타겟팅 오버레이 없음 vs 있음
  (c) H32 - 분기 리밸런싱 vs 월간 리밸런싱 (룩백은 H32 최종 권고대로 12개월 고정, 리밸런싱 주기만 격리)

데이터 재구성 방식(재계산 최소화):
  - core_alone / case_a_static_satellite 일별수익률: H33이 이미 저장해 둔
    analysis/2026-08-23_block_bootstrap_sample_error_quantification/{ep}_core_alone_ret.csv,
    {ep}_case_a_ret.csv 를 그대로 재사용 (재백테스트 없음).
  - spy_buyhold 일별수익률: core.market_data.get_price_history로 SPY 종가를 받아 각 창으로
    슬라이스 후 pct_change (신규, 매우 저비용).
  - vol_targeted / no_overlay 일별수익률: champion_strategy.run_champion을 6개 창에 대해 새로
    실행(H28과 동일한 코드/파라미터: target_vol=18%, cap=1.0, 20일 실현변동성, 1일 시차)해
    net_ret을 얻고, H28의 vol_target_scale()을 그대로 적용해 두 번째 시계열을 만든다.
  - quarterly(63일) / monthly(21일) 리밸런싱 일별수익률: H32의 run_champion_joint()를 그대로
    재사용해 6개 창 x 2개 주기(룩백은 12개월=252일로 고정)를 새로 실행한다.

블록부트스트랩 설계는 H33과 동일: L=10/20/40일, 창당 2000회, circular moving block, SEED는
H33과 동일 값(20260823)을 이어서 재현성을 유지한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-23_champion_parameter_fine_resolution_and_satellite_joint"))

import numpy as np
import pandas as pd

from core.market_data import get_price_history
from champion_strategy import run_champion, CHAMPION_UNIVERSE  # noqa: E402
from h32_fine_grid_and_satellite_joint import run_champion_joint  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
H33_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_block_bootstrap_sample_error_quantification"

WINDOWS = {
    "full_2019_2026": ("2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-10-01", "2009-06-30"),
    "covid_2020": ("2020-02-19", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
    "selloff_2018": ("2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2015-08-01", "2016-02-15"),
}
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
SEED = 20260823
TRADING_DAYS = 252

# H28 파라미터 (그대로 재사용)
TARGET_VOL_ANNUAL = 18.0
VOL_CAP = 1.0
VOL_WINDOW = 20

# H32 파라미터: 룩백 12개월(252일) 고정, 리밸런싱만 21일(월간) vs 63일(분기)
LOOKBACK_DAYS_12M = 252
REBAL_FREQS = {"monthly_21d": 21, "quarterly_63d": 63}


def log(msg):
    print(f"[h34] {msg}", flush=True)


def annualized_sharpe(ret: np.ndarray) -> float:
    if len(ret) < 2:
        return float("nan")
    mu, sd = np.mean(ret), np.std(ret, ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(mu / sd * np.sqrt(TRADING_DAYS))


def moving_block_bootstrap_sharpe(ret: np.ndarray, block_len: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
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


# ---------------------------------------------------------------------------
# (a) SPY buy-and-hold daily returns
# ---------------------------------------------------------------------------
def load_h33_core_and_satellite() -> dict:
    """H33이 저장한 core_alone / case_a_static_satellite 일별수익률을 그대로 로드."""
    out = {}
    for ep in EPISODE_ORDER:
        core = pd.read_csv(H33_DIR / f"{ep}_core_alone_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        sat = pd.read_csv(H33_DIR / f"{ep}_case_a_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        out[ep] = {"core_alone": core, "case_a_static_satellite": sat}
    return out


def build_spy_buyhold_returns() -> dict:
    earliest = min(pd.Timestamp(s) for s, _ in WINDOWS.values())
    latest = max(pd.Timestamp(e) for _, e in WINDOWS.values())
    hist = get_price_history("SPY", start=(earliest - pd.DateOffset(days=10)).date().isoformat(),
                              end=latest.date().isoformat(), interval="1d")
    close = hist["Close"].ffill()
    daily_ret = close.pct_change().dropna()

    out = {}
    for ep, (start, end) in WINDOWS.items():
        sliced = daily_ret[(daily_ret.index >= pd.Timestamp(start)) & (daily_ret.index <= pd.Timestamp(end))]
        out[ep] = sliced
        log(f"  spy_buyhold {ep}: n_obs={len(sliced)}")
    return out


# ---------------------------------------------------------------------------
# (b) vol-targeted vs no-overlay daily returns
# ---------------------------------------------------------------------------
def vol_target_scale(daily_ret: pd.Series, target_vol_annual: float, cap: float,
                      window: int = VOL_WINDOW, floor: float = 0.0) -> pd.Series:
    realized_vol = daily_ret.rolling(window, min_periods=window).std() * np.sqrt(TRADING_DAYS)
    scale = (target_vol_annual / 100.0) / realized_vol
    return scale.clip(lower=floor, upper=cap).fillna(1.0)


def build_vol_targeting_returns() -> dict:
    out = {}
    t0 = time.time()
    for ep, (start, end) in WINDOWS.items():
        r = run_champion(start, end)
        net_ret = r["ret_net"]
        scale = vol_target_scale(net_ret, TARGET_VOL_ANNUAL, VOL_CAP)
        scaled_ret = net_ret * scale.shift(1).fillna(1.0)
        out[ep] = {"no_overlay": net_ret, "vol_targeted": scaled_ret}
        log(f"  vol_targeting {ep}: n_obs={len(net_ret)} t={time.time()-t0:.1f}s")
    return out


# ---------------------------------------------------------------------------
# (c) quarterly vs monthly rebalance daily returns (lookback fixed at 12mo)
# ---------------------------------------------------------------------------
def build_rebalance_freq_returns() -> dict:
    out = {}
    t0 = time.time()
    for ep, (start, end) in WINDOWS.items():
        out[ep] = {}
        for freq_name, rebal_days in REBAL_FREQS.items():
            _, result = run_champion_joint(start, end, LOOKBACK_DAYS_12M, rebal_days, return_weights_idx=True)
            out[ep][freq_name] = result["ret_net"]
            log(f"  rebalance {ep}/{freq_name}: n_obs={len(result['ret_net'])} t={time.time()-t0:.1f}s")
    return out


# ---------------------------------------------------------------------------
# generic bootstrap driver
# ---------------------------------------------------------------------------
def bootstrap_comparison(window_series: dict, configs: list[str], rng: np.random.Generator,
                          save_prefix: str) -> dict:
    """window_series: {ep: {cfg: pd.Series}}. Returns summary dict + saves raw boot samples for L=20."""
    out = {}
    boot_samples_l20 = {ep: {} for ep in window_series}
    for ep, d in window_series.items():
        out[ep] = {"n_obs": {}, "by_config": {}}
        for cfg in configs:
            ret = d[cfg].values.astype(float)
            out[ep]["n_obs"][cfg] = int(len(ret))
            point_sharpe = annualized_sharpe(ret)
            per_block = {}
            for L in BLOCK_LENGTHS:
                boot = moving_block_bootstrap_sharpe(ret, L, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                if L == 20:
                    boot_samples_l20[ep][cfg] = boot.tolist()
                if len(boot) == 0:
                    per_block[str(L)] = None
                    continue
                per_block[str(L)] = {
                    "block_len": L, "n_boot_valid": int(len(boot)),
                    "n_nonoverlapping_blocks_approx": round(len(ret) / L, 1),
                    "mean": float(np.mean(boot)), "std": float(np.std(boot)),
                    "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
                    "ci50": [float(np.percentile(boot, 25)), float(np.percentile(boot, 75))],
                }
            out[ep]["by_config"][cfg] = {
                "point_estimate_sharpe": point_sharpe,
                "bootstrap_by_block_len": per_block,
            }
            log(f"  [{save_prefix}] bootstrap {ep}/{cfg}: point={point_sharpe:.3f}, "
                f"L=20 CI90={per_block.get('20', {}).get('ci90')}")
    return out, boot_samples_l20


# ---------------------------------------------------------------------------
# combined weighting x sampling propagation (H33b style)
# ---------------------------------------------------------------------------
BASE_RATES = {
    "full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04,
    "bear_2022": 0.10, "selloff_2018": 0.16, "correction_2015_2016": 0.17,
}
K_CENTRAL = 30.0
N_DRAWS = 10000


def dirichlet_draws(n: int, rng: np.random.Generator) -> np.ndarray:
    alpha = np.array([BASE_RATES[ep] * K_CENTRAL for ep in EPISODE_ORDER])
    return rng.dirichlet(alpha, size=n)


def combined_propagation(boot_l20: dict, point_sharpe: dict, cfg_a: str, cfg_b: str, rng: np.random.Generator) -> dict:
    """cfg_b(challenger, e.g. 'case_a_static_satellite'/'vol_targeted'/'quarterly_63d') vs
    cfg_a(incumbent baseline, e.g. 'core_alone'/'no_overlay'/'monthly_21d')."""
    dir_draws = dirichlet_draws(N_DRAWS, rng)

    def draw_ev(cfg):
        per_ep_samples = []
        for ep in EPISODE_ORDER:
            samples = np.array(boot_l20[ep][cfg])
            idx = rng.integers(0, len(samples), size=N_DRAWS)
            per_ep_samples.append(samples[idx])
        stacked = np.column_stack(per_ep_samples)
        return np.sum(stacked * dir_draws, axis=1)

    ev_a = draw_ev(cfg_a)
    ev_b = draw_ev(cfg_b)
    gap = ev_b - ev_a
    win_rate_b = float(np.mean(ev_b > ev_a))

    # weighting-only (H30 style): point estimates only, dirichlet weighting
    ev_matrix_a = np.array([point_sharpe[ep][cfg_a] for ep in EPISODE_ORDER])
    ev_matrix_b = np.array([point_sharpe[ep][cfg_b] for ep in EPISODE_ORDER])
    weighting_only_a = dir_draws @ ev_matrix_a
    weighting_only_b = dir_draws @ ev_matrix_b
    weighting_only_win_rate_b = float(np.mean(weighting_only_b > weighting_only_a))

    # sampling-only: fixed weights (base rates), bootstrap resample only
    fixed_w = np.array([BASE_RATES[ep] for ep in EPISODE_ORDER])
    fixed_w = fixed_w / fixed_w.sum()

    def draw_ev_fixed(cfg):
        per_ep_samples = []
        for ep in EPISODE_ORDER:
            samples = np.array(boot_l20[ep][cfg])
            idx = rng.integers(0, len(samples), size=N_DRAWS)
            per_ep_samples.append(samples[idx])
        stacked = np.column_stack(per_ep_samples)
        return stacked @ fixed_w

    sampling_only_a = draw_ev_fixed(cfg_a)
    sampling_only_b = draw_ev_fixed(cfg_b)
    sampling_only_win_rate_b = float(np.mean(sampling_only_b > sampling_only_a))

    return {
        "cfg_baseline": cfg_a, "cfg_challenger": cfg_b,
        "weighting_only_win_rate_challenger": weighting_only_win_rate_b,
        "sampling_only_win_rate_challenger": sampling_only_win_rate_b,
        "combined_win_rate_challenger": win_rate_b,
        "combined_gap_challenger_minus_baseline": {
            "mean": float(np.mean(gap)),
            "ci90": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
        },
        "combined_mean_expected_sharpe": {cfg_a: float(np.mean(ev_a)), cfg_b: float(np.mean(ev_b))},
    }


def main():
    t0 = time.time()

    log("=== (a) SPY buy-and-hold 데이터 준비 ===")
    core_sat = load_h33_core_and_satellite()
    spy = build_spy_buyhold_returns()
    win_a = {ep: {"spy_buyhold": spy[ep], "core_alone": core_sat[ep]["core_alone"],
                  "case_a_static_satellite": core_sat[ep]["case_a_static_satellite"]}
             for ep in EPISODE_ORDER}
    for ep in EPISODE_ORDER:
        spy[ep].to_csv(OUT_DIR / f"{ep}_spy_buyhold_ret.csv", header=["ret"])

    log("=== (b) 변동성타겟팅 데이터 준비 (신규 백테스트 6회) ===")
    vt = build_vol_targeting_returns()
    win_b = vt
    for ep in EPISODE_ORDER:
        vt[ep]["no_overlay"].to_csv(OUT_DIR / f"{ep}_no_overlay_ret.csv", header=["ret"])
        vt[ep]["vol_targeted"].to_csv(OUT_DIR / f"{ep}_vol_targeted_ret.csv", header=["ret"])

    log("=== (c) 리밸런싱 주기 데이터 준비 (신규 백테스트 12회) ===")
    rb = build_rebalance_freq_returns()
    win_c = rb
    for ep in EPISODE_ORDER:
        rb[ep]["monthly_21d"].to_csv(OUT_DIR / f"{ep}_monthly_21d_ret.csv", header=["ret"])
        rb[ep]["quarterly_63d"].to_csv(OUT_DIR / f"{ep}_quarterly_63d_ret.csv", header=["ret"])

    log(f"데이터 준비 완료 t={time.time()-t0:.1f}s. 부트스트랩 시작.")

    rng = np.random.default_rng(SEED)
    boot_a, samples_a = bootstrap_comparison(win_a, ["spy_buyhold", "core_alone", "case_a_static_satellite"], rng, "H26")
    boot_b, samples_b = bootstrap_comparison(win_b, ["no_overlay", "vol_targeted"], rng, "H28")
    boot_c, samples_c = bootstrap_comparison(win_c, ["monthly_21d", "quarterly_63d"], rng, "H32")

    point_a = {ep: {cfg: boot_a[ep]["by_config"][cfg]["point_estimate_sharpe"] for cfg in
                    ["spy_buyhold", "core_alone", "case_a_static_satellite"]} for ep in EPISODE_ORDER}
    point_b = {ep: {cfg: boot_b[ep]["by_config"][cfg]["point_estimate_sharpe"] for cfg in
                    ["no_overlay", "vol_targeted"]} for ep in EPISODE_ORDER}
    point_c = {ep: {cfg: boot_c[ep]["by_config"][cfg]["point_estimate_sharpe"] for cfg in
                    ["monthly_21d", "quarterly_63d"]} for ep in EPISODE_ORDER}

    rng2 = np.random.default_rng(SEED + 1)
    combined_a = combined_propagation(samples_a, point_a, "spy_buyhold", "case_a_static_satellite", rng2)
    combined_a_core_vs_spy = combined_propagation(samples_a, point_a, "spy_buyhold", "core_alone", np.random.default_rng(SEED + 2))
    combined_b = combined_propagation(samples_b, point_b, "no_overlay", "vol_targeted", np.random.default_rng(SEED + 3))
    combined_c = combined_propagation(samples_c, point_c, "monthly_21d", "quarterly_63d", np.random.default_rng(SEED + 4))

    log(f"H26 system vs SPY combined win_rate(system)={combined_a['combined_win_rate_challenger']:.3f}")
    log(f"H26 core_alone vs SPY combined win_rate(core_alone)={combined_a_core_vs_spy['combined_win_rate_challenger']:.3f}")
    log(f"H28 vol_targeted vs no_overlay combined win_rate(vol_targeted)={combined_b['combined_win_rate_challenger']:.3f}")
    log(f"H32 quarterly vs monthly combined win_rate(quarterly)={combined_c['combined_win_rate_challenger']:.3f}")

    out = {
        "meta": {
            "n_boot": N_BOOT, "n_draws": N_DRAWS, "seed": SEED, "block_lengths": BLOCK_LENGTHS,
            "trading_days": TRADING_DAYS, "episode_order": EPISODE_ORDER, "k_central": K_CENTRAL,
            "base_rates": BASE_RATES,
        },
        "bootstrap_h26_system_vs_spy": boot_a,
        "bootstrap_h28_vol_targeting": boot_b,
        "bootstrap_h32_rebalance_freq": boot_c,
        "combined_h26_system_vs_spy": combined_a,
        "combined_h26_core_alone_vs_spy": combined_a_core_vs_spy,
        "combined_h28_vol_targeted_vs_no_overlay": combined_b,
        "combined_h32_quarterly_vs_monthly": combined_c,
        "total_runtime_sec": round(time.time() - t0, 1),
    }
    (OUT_DIR / "h34_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"saved h34_results.json, total runtime={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
