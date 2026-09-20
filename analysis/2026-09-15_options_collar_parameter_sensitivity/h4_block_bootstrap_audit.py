"""H4 - 블록부트스트랩 표본오차 x 디리클레 국면가중 결합전파 (H33/작업49 h_bootstrap_audit.py 방법론
그대로 재사용) 를 "칼라 파라미터 그리드의 이웃값들"에 적용한다.

목적: H2(그리드 스윕)의 점추정만으로는 "이 조합이 저 조합보다 좋다"가 노이즈인지 신호인지 알 수
없다 — 이 프로그램의 반복된 메타발견(가중치만 반영한 승률 90%대가 블록부트스트랩 결합전파를 거치면
50%대로 무너진다)이 파라미터 그리드에도 적용되는지 직접 감사한다. 베이스라인(put=1.00,call=1.05,
tenor=21)과 이웃 후보 4개(딥아웃풋/와이드콜/롱테너/제로코스트)를 각각 무헤지 새틀라이트와 비교해,
"칼라가 이긴다"는 방향이 파라미터를 조금만 바꿔도 신뢰구간이 겹치는 노이즈 수준인지 확인한다.

방법론(h33_block_bootstrap_sample_error.py / h_bootstrap_audit.py와 완전히 동일, 새로 발명하지
않음): 순환 이동블록부트스트랩(L=10/20/40, 창당/구성당 2000회) + 디리클레 국면가중치(base/calm_heavy/
crisis_heavy 시나리오, h22_expected_value_reweighting.py의 값 그대로) 결합전파(10,000 draw).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/quant")

import numpy as np
import pandas as pd

from core.champion_strategy import build_collar_overlay_returns, SATELLITE_WEIGHT
from h2_moneyness_tenor_grid import build_zero_cost_collar_overlay

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

VARIANTS = {
    "collar_baseline": {"put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": 21},
    "collar_deep_otm_put": {"put_moneyness": 0.90, "call_moneyness": 1.05, "tenor_days": 21},
    "collar_wide_otm_call": {"put_moneyness": 1.00, "call_moneyness": 1.10, "tenor_days": 21},
    "collar_long_tenor": {"put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": 63},
    "collar_zero_cost": {"put_moneyness": 1.00, "call_moneyness": None, "tenor_days": 21, "zero_cost": True},
}
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
TRADING_DAYS = 252
SEED = 20260915

BASE_RATES = {
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
    print(f"[h4] {msg}", flush=True)


def load_group_returns(group: str) -> dict:
    unhedged = pd.read_csv(OUT_DIR / f"{group}_unhedged_blend_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    return {"unhedged_blend": unhedged}


def build_variant_ret(cached: dict, full_start: str, full_end: str, variant: dict) -> pd.Series:
    trading_index = cached["unhedged_blend"].index
    if variant.get("zero_cost"):
        overlay = build_zero_cost_collar_overlay(trading_index, full_start, full_end, variant["put_moneyness"], variant["tenor_days"])
    else:
        overlay = build_collar_overlay_returns(trading_index, full_start, full_end, variant["put_moneyness"],
                                                variant["call_moneyness"], variant["tenor_days"])
    overlay_scaled = overlay["overlay_ret"].reindex(trading_index).fillna(0.0) * SATELLITE_WEIGHT
    return cached["unhedged_blend"] + overlay_scaled


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
    n = len(ret)
    if n == 0:
        return np.full(n_boot, np.nan)
    block_len = min(block_len, n)
    n_blocks_needed = int(np.ceil(n / block_len))
    ext = np.concatenate([ret, ret])
    sharpes = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks_needed)
        pieces = [ext[s:s + block_len] for s in starts]
        synth = np.concatenate(pieces)[:n]
        sharpes[b] = annualized_sharpe(synth)
    return sharpes


def gather_window_returns() -> dict:
    out = {}
    group_cache = {}
    for episode in EPISODE_ORDER:
        group_key = GROUP_OF[episode]
        if group_key not in group_cache:
            group_cache[group_key] = load_group_returns(group_key)
        cached = group_cache[group_key]
        full_start, full_end, crisis_start, crisis_end = EPISODES[episode]
        is_full = episode == "full_2019_2026"
        ws, we = (full_start, full_end) if is_full else (crisis_start, crisis_end)

        series = {"unhedged_satellite": slice_window(cached["unhedged_blend"], ws, we)}
        for vname, vparams in VARIANTS.items():
            full_ret = build_variant_ret(cached, full_start, full_end, vparams)
            series[vname] = slice_window(full_ret, ws, we)

        out[episode] = {"window_used": [ws, we], "n_obs": int(len(series["unhedged_satellite"])), "series": series}
        log(f"{episode}: window={ws}~{we}, n_obs={out[episode]['n_obs']}")
    return out


def bootstrap_all(window_returns: dict) -> tuple[dict, dict]:
    rng = np.random.default_rng(SEED)
    summary = {}
    raw20 = {}
    configs = ["unhedged_satellite"] + list(VARIANTS.keys())
    for label, d in window_returns.items():
        summary[label] = {"window_used": d["window_used"], "n_obs": d["n_obs"], "by_config": {}}
        raw20[label] = {}
        for cfg in configs:
            ret = d["series"][cfg].values.astype(float)
            point_sharpe = annualized_sharpe(ret)
            per_block = {}
            for L in BLOCK_LENGTHS:
                boot = moving_block_bootstrap_sharpe(ret, L, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                if len(boot) == 0:
                    per_block[str(L)] = None
                    continue
                per_block[str(L)] = {
                    "block_len": L, "n_boot_valid": int(len(boot)),
                    "mean": float(np.mean(boot)), "std": float(np.std(boot)),
                    "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
                }
                if L == 20:
                    raw20[label][cfg] = boot
            summary[label]["by_config"][cfg] = {
                "point_estimate_sharpe": point_sharpe, "n_obs": d["n_obs"],
                "bootstrap_by_block_len": per_block,
            }
            log(f"  {label}/{cfg}: point={point_sharpe:.3f} L20_CI90={per_block.get('20', {}).get('ci90')}")
    return summary, raw20


def dirichlet_draws(scenario: str, n: int, rng: np.random.Generator) -> np.ndarray:
    rates = BASE_RATES[scenario]
    alpha = np.array([rates[ep] * K_CENTRAL for ep in EPISODE_ORDER])
    return rng.dirichlet(alpha, size=n)


def combined_gap_analysis(raw20: dict) -> dict:
    rng = np.random.default_rng(SEED + 1)
    out = {}
    pairs = [(v, "unhedged_satellite") for v in VARIANTS]
    for scenario in BASE_RATES:
        dir_draws = dirichlet_draws(scenario, N_DRAWS, rng)
        out[scenario] = {}
        for cfg_a, cfg_b in pairs:
            ev_a = np.zeros(N_DRAWS)
            ev_b = np.zeros(N_DRAWS)
            for i, ep in enumerate(EPISODE_ORDER):
                samples_a = raw20[ep][cfg_a]
                samples_b = raw20[ep][cfg_b]
                idx_a = rng.integers(0, len(samples_a), size=N_DRAWS)
                idx_b = rng.integers(0, len(samples_b), size=N_DRAWS)
                ev_a += dir_draws[:, i] * samples_a[idx_a]
                ev_b += dir_draws[:, i] * samples_b[idx_b]
            gap = ev_a - ev_b
            out[scenario][f"{cfg_a}_vs_{cfg_b}"] = {
                "mean_gap": float(np.mean(gap)),
                "ci90_gap": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
                "pct_draws_a_ahead": float(np.mean(gap > 0)),
            }
            log(f"  combined[{scenario}] {cfg_a} vs {cfg_b}: win_rate={out[scenario][f'{cfg_a}_vs_{cfg_b}']['pct_draws_a_ahead']:.3f}")
    return out


def main():
    t0 = time.time()
    window_returns = gather_window_returns()
    boot_summary, raw20 = bootstrap_all(window_returns)
    combined = combined_gap_analysis(raw20)

    out = {
        "meta": {"n_boot": N_BOOT, "seed": SEED, "block_lengths": BLOCK_LENGTHS,
                 "trading_days": TRADING_DAYS, "episode_order": EPISODE_ORDER,
                 "variants": VARIANTS, "n_draws_combined": N_DRAWS, "base_rate_scenarios": BASE_RATES},
        "bootstrap": boot_summary,
        "combined_dirichlet_x_bootstrap": combined,
    }
    (OUT_DIR / "h4_bootstrap_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"저장 완료: h4_bootstrap_results.json ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
