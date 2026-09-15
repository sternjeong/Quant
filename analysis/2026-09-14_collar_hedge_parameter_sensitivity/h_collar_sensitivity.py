"""옵션 칼라 헤지(2026-09-14 라이브화, core/champion_strategy.py)의 파라미터 민감도 감사.

배경(agent_b_market_portfolio.md가 명시한 미해결 과제): 작업57에서 합성 Black-Scholes 칼라
(ATM 풋 매수 + 5% OTM 콜 매도, 21거래일 월물 롤)를 core/champion_strategy.py로 그대로 이식해
라이브 계산 가능하게 만들었지만, 이 정확한 파라미터 조합(moneyness/tenor)이 이 프로그램의 표준
감사(스윕 + 순열/플라시보 + 블록부트스트랩 + 기저확률 기댓값)를 거친 적은 한 번도 없다. 작업48/49는
"칼라(1.00/1.05/21일)가 무헤지보다 나은가"만 감사했지 "왜 하필 이 숫자들인가"는 감사하지 않았다.

이 스크립트는 4단계로 감사한다(이 저장소의 기존 인프라를 그대로 재사용 — 새 계산 방법론 발명 없음):
  H-A 완만성(smoothness) 그리드: put_moneyness x call_moneyness x tenor_days 24개 조합의 점추정치가
      고립된 스파이크가 아니라 완만한 고원을 이루는지 (과최적화 의심 낮추기).
  H-B 플라시보(무작위 대조군): 실제 라이브 파라미터(1.00/1.05/21)가 넓은 범위에서 무작위로 뽑은
      200개 파라미터 조합 대비 몇 백분위인지 — "이 특정 숫자가 우연이 아니라 진짜 나은 선택인가".
  H-C 블록부트스트랩 표본오차: H33/H_bootstrap(작업44/49)과 정확히 동일한 방법론(순환 이동블록,
      L=10/20/40, 창×구성당 2,000회)을 대표 파라미터 4개(라이브 기본값 + 변형 3개)에 적용.
  H-D 결합전파 기댓값: H33b/H_combined(작업45/49)와 동일한 디리클레(K=30, 3개 시나리오) x
      블록부트스트랩 결합전파로 "칼라 vs 무헤지" 승률·신뢰구간을 파라미터 4개 전부에 대해 산출.

재사용 소스: h_options_hedge.py(작업48, load_h20_series/load_h20_results/fetch_spy_vix/load_fedfunds/
bs_put_price/bs_call_price/blend_returns/blend_returns_time_varying/perf_metrics_slice),
h_bootstrap_audit.py(작업49, moving_block_bootstrap_sharpe/BASE_RATES/dirichlet_draws 방법론).
데이터 재사용을 위해 SPY/VIX/FEDFUNDS는 에피소드당 1회만 fetch하고(hh.fetch_spy_vix/hh.load_fedfunds),
그 뒤 파라미터 그리드 전체는 순수 계산(Black-Scholes 재평가)만 반복해 네트워크 호출을 없앤다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-22_regime_conditional_satellite_switch"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-30_synthetic_options_tail_hedge"))

import numpy as np
import pandas as pd

import h_options_hedge as hh  # noqa: E402  (작업48 원본 — load_h20_series/fetch_spy_vix/BS가격 재사용)

OUT_DIR = Path(__file__).resolve().parent

EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
TRADING_DAYS = 252
SEED = 20260914
RNG_GLOBAL = np.random.default_rng(SEED)

# ---------------------------------------------------------------------------
# H-A/H-B 그리드 정의
# ---------------------------------------------------------------------------
GRID_PUT_MONEYNESS = [1.00, 0.95]          # ATM / 5% OTM(더 저렴, 보호 시작점이 더 멂)
GRID_CALL_MONEYNESS = [1.03, 1.05, 1.07, 1.10]  # 라이브 기본값(1.05) 포함
GRID_TENOR_DAYS = [21, 42, 63]              # 월물 / 2개월물 / 분기물(대략)

LIVE_DEFAULT = {"put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": 21}

# H-C/H-D에 넘길 대표 파라미터 4개(라이브 기본값 + 의미 있는 변형 3개 — 그리드서치 최댓값을 그대로
# 뽑지 않는다: "이건 하나의 가설 검증이지 데이터마이닝이 아니다"라는 프로그램 규칙에 따라, 최고
# 점추정치가 아니라 실무적으로 구별되는 대안들을 미리 정해 비교한다).
REPRESENTATIVE_CONFIGS = {
    "live_default_atm_put_5pct_call_monthly": {"put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": 21},
    "cheaper_otm_put_5pct": {"put_moneyness": 0.95, "call_moneyness": 1.05, "tenor_days": 21},
    "wider_call_10pct": {"put_moneyness": 1.00, "call_moneyness": 1.10, "tenor_days": 21},
    "quarterly_tenor_63d": {"put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": 63},
    # H-A 그리드에서 점추정 기준 최상위권(top5 중 3개)을 차지한 조합 — 우연인지 부트스트랩으로 확인.
    "bimonthly_tenor_42d": {"put_moneyness": 1.00, "call_moneyness": 1.05, "tenor_days": 42},
}

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
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
N_PLACEBO = 200


def log(msg):
    print(f"[sens] {msg}", flush=True)


def annualized_sharpe(ret: np.ndarray) -> float:
    if len(ret) < 2:
        return float("nan")
    mu, sd = np.mean(ret), np.std(ret, ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(mu / sd * np.sqrt(TRADING_DAYS))


def moving_block_bootstrap_sharpe(ret: np.ndarray, block_len: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """H33/H_bootstrap과 동일 — 순환 이동블록부트스트랩으로 샤프의 표본분포를 근사."""
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


def slice_window(s: pd.Series, start: str, end: str) -> pd.Series:
    return s[(s.index >= start) & (s.index <= end)]


# ---------------------------------------------------------------------------
# 1회 fetch: 에피소드별 SPY/VIX/FEDFUNDS + 코어/새틀라이트 캐시 수익률
# ---------------------------------------------------------------------------

def load_episode_context() -> dict:
    series = hh.load_h20_series()
    h20 = hh.load_h20_results()
    ctx = {}
    for label in EPISODE_ORDER:
        core_ret = series[label]["_core_ret"]
        sat_ret = series[label]["_sat_realtime_ret"]
        trading_index = core_ret.index
        start, end = str(trading_index[0].date()), str(trading_index[-1].date())
        log(f"{label}: SPY/VIX/FEDFUNDS 1회 fetch ({start}~{end}, {len(trading_index)}거래일)")
        px = hh.fetch_spy_vix(start, end).reindex(trading_index).ffill()
        fedfunds = hh.load_fedfunds()

        h20_ep = h20["episodes"][label]
        crisis_start, crisis_end = h20_ep["crisis_window"]
        full_start, full_end = h20_ep["full_period"]
        wkey = "full_period" if label == "full_2019_2026" else "crisis_window"
        w_start, w_end = (full_start, full_end) if wkey == "full_period" else (crisis_start, crisis_end)

        unhedged_blend = hh.blend_returns(core_ret, sat_ret, hh.SATELLITE_WEIGHT)
        ctx[label] = {
            "trading_index": trading_index, "px": px, "fedfunds": fedfunds,
            "core_ret": core_ret, "unhedged_blend": unhedged_blend,
            "window_used": [w_start, w_end], "wkey": wkey,
        }
    return ctx


def build_overlay_fast(ctx_ep: dict, put_moneyness: float, call_moneyness: float, tenor_days: int) -> pd.Series:
    """hh.build_option_overlay_returns(mode='collar')와 동일 로직이지만 px/fedfunds를 이미 fetch한
    상태로 받아 네트워크 호출 없이 순수 계산만 반복한다(그리드 스윕용)."""
    trading_index = ctx_ep["trading_index"]
    px = ctx_ep["px"]
    fedfunds = ctx_ep["fedfunds"]

    from core.backtest_engine import _first_trading_day_of_month_mask
    roll_mask = _first_trading_day_of_month_mask(trading_index)
    roll_dates = list(trading_index[roll_mask])
    if len(roll_dates) == 0 or roll_dates[0] != trading_index[0]:
        roll_dates = [trading_index[0]] + roll_dates

    overlay_ret = pd.Series(0.0, index=trading_index)
    for rd in roll_dates:
        pos = trading_index.get_loc(rd)
        exp_pos = min(pos + tenor_days, len(trading_index) - 1)
        expiry = trading_index[exp_pos]
        S0 = float(px.loc[rd, "spy"])
        vix0 = px.loc[rd, "vix"]
        sigma = float(vix0) / 100.0 if pd.notna(vix0) else hh.FALLBACK_VOL
        try:
            r = float(fedfunds.asof(rd))
            if pd.isna(r):
                r = hh.DEFAULT_R
        except Exception:
            r = hh.DEFAULT_R
        T = tenor_days / 252.0
        K_put = S0 * put_moneyness
        K_call = S0 * call_moneyness
        put0 = hh.bs_put_price(S0, K_put, T, r, sigma)
        call0 = hh.bs_call_price(S0, K_call, T, r, sigma)
        S_T = float(px.loc[expiry, "spy"])
        put_payoff = max(K_put - S_T, 0.0)
        call_payoff = max(S_T - K_call, 0.0)

        net_premium_pct_debit = (call0 - put0) / S0
        net_payoff_pct_credit = (put_payoff - call_payoff) / S0
        overlay_ret.loc[rd] += net_premium_pct_debit
        overlay_ret.loc[expiry] += net_payoff_pct_credit
    return overlay_ret


def collar_blend_for_params(ctx: dict, label: str, put_moneyness: float, call_moneyness: float, tenor_days: int) -> pd.Series:
    ep = ctx[label]
    overlay = build_overlay_fast(ep, put_moneyness, call_moneyness, tenor_days)
    overlay_scaled, _ = overlay.align(ep["core_ret"], join="right", fill_value=0.0)
    return ep["unhedged_blend"] + hh.SATELLITE_WEIGHT * overlay_scaled


def ev_sharpe_for_params(ctx: dict, put_moneyness: float, call_moneyness: float, tenor_days: int,
                          base_rate_scenario: str = "base") -> dict:
    """기저확률(base 시나리오) 가중 기댓값 샤프 — 그리드 스윕/플라시보용 빠른 점수화(부트스트랩 없음)."""
    weights = BASE_RATES[base_rate_scenario]
    total_w = sum(weights.values())
    ev_sharpe = 0.0
    per_ep = {}
    for label in EPISODE_ORDER:
        ep = ctx[label]
        blend = collar_blend_for_params(ctx, label, put_moneyness, call_moneyness, tenor_days)
        m = hh.perf_metrics_slice(blend, *ep["window_used"])
        sharpe = m["sharpe"] if m["sharpe"] is not None else 0.0
        per_ep[label] = {"sharpe": sharpe, "cagr": m["cagr"], "mdd": m["mdd"]}
        ev_sharpe += (weights[label] / total_w) * sharpe
    return {"ev_sharpe": ev_sharpe, "per_episode": per_ep}


# ---------------------------------------------------------------------------
# H-A: 완만성 그리드
# ---------------------------------------------------------------------------

def run_smoothness_grid(ctx: dict) -> dict:
    log("=== H-A: 완만성(smoothness) 그리드 (put x call x tenor) ===")
    rows = []
    t0 = time.time()
    for pm in GRID_PUT_MONEYNESS:
        for cm in GRID_CALL_MONEYNESS:
            for td in GRID_TENOR_DAYS:
                res = ev_sharpe_for_params(ctx, pm, cm, td, "base")
                rows.append({"put_moneyness": pm, "call_moneyness": cm, "tenor_days": td,
                             "ev_sharpe_base": res["ev_sharpe"], "per_episode": res["per_episode"]})
                log(f"  put={pm} call={cm} tenor={td}: EV_sharpe(base)={res['ev_sharpe']:.4f}")
    log(f"H-A 완료 ({time.time()-t0:.1f}s, {len(rows)}개 조합)")

    ev_values = np.array([r["ev_sharpe_base"] for r in rows])
    live = next(r for r in rows if r["put_moneyness"] == 1.00 and r["call_moneyness"] == 1.05 and r["tenor_days"] == 21)
    return {
        "grid_rows": rows,
        "n_combos": len(rows),
        "ev_sharpe_range": [float(ev_values.min()), float(ev_values.max())],
        "ev_sharpe_std": float(ev_values.std()),
        "live_default_ev_sharpe": live["ev_sharpe_base"],
        "live_default_rank_from_top": int((ev_values > live["ev_sharpe_base"]).sum()) + 1,
    }


# ---------------------------------------------------------------------------
# H-B: 플라시보 — 무작위 파라미터 대조군
# ---------------------------------------------------------------------------

def run_placebo_test(ctx: dict) -> dict:
    log(f"=== H-B: 플라시보 무작위 파라미터 대조군 (N={N_PLACEBO}) ===")
    rng = np.random.default_rng(SEED + 7)
    live = ev_sharpe_for_params(ctx, **LIVE_DEFAULT, base_rate_scenario="base")["ev_sharpe"]
    log(f"  라이브 기본값(1.00/1.05/21) EV_sharpe(base) = {live:.4f}")

    random_scores = []
    random_params = []
    for i in range(N_PLACEBO):
        pm = float(rng.uniform(0.85, 1.00))
        cm = float(rng.uniform(1.02, 1.20))
        td = int(rng.integers(15, 71))
        res = ev_sharpe_for_params(ctx, pm, cm, td, "base")
        random_scores.append(res["ev_sharpe"])
        random_params.append({"put_moneyness": round(pm, 4), "call_moneyness": round(cm, 4), "tenor_days": td})
        if (i + 1) % 40 == 0:
            log(f"  플라시보 {i+1}/{N_PLACEBO} 진행 중...")

    random_scores = np.array(random_scores)
    percentile = float((random_scores < live).mean() * 100.0)
    return {
        "n_placebo": N_PLACEBO,
        "param_ranges": {"put_moneyness": [0.85, 1.00], "call_moneyness": [1.02, 1.20], "tenor_days": [15, 70]},
        "live_default_ev_sharpe": live,
        "random_mean": float(random_scores.mean()),
        "random_median": float(np.median(random_scores)),
        "random_std": float(random_scores.std()),
        "random_min": float(random_scores.min()),
        "random_max": float(random_scores.max()),
        "live_default_percentile": percentile,
        "random_params_sample": random_params[:10],
    }


# ---------------------------------------------------------------------------
# H-C/H-D: 대표 파라미터 4개에 대한 블록부트스트랩 + 결합전파
# ---------------------------------------------------------------------------

def run_bootstrap_and_combined(ctx: dict) -> dict:
    log("=== H-C/H-D: 대표 파라미터 4개 블록부트스트랩 + 결합전파 ===")
    rng = np.random.default_rng(SEED + 13)

    # 무헤지 새틀라이트(모든 config 공통 baseline) 부트스트랩 — 1회만 계산
    unhedged_boot = {}
    unhedged_point = {}
    for label in EPISODE_ORDER:
        ep = ctx[label]
        ret = slice_window(ep["unhedged_blend"], *ep["window_used"]).values.astype(float)
        unhedged_point[label] = annualized_sharpe(ret)
        boot20 = moving_block_bootstrap_sharpe(ret, 20, N_BOOT, rng)
        unhedged_boot[label] = boot20[~np.isnan(boot20)]
        log(f"  unhedged_satellite/{label}: point={unhedged_point[label]:.3f}")

    config_results = {}
    for cfg_name, params in REPRESENTATIVE_CONFIGS.items():
        log(f"-- config: {cfg_name} {params} --")
        by_episode = {}
        raw20 = {}
        for label in EPISODE_ORDER:
            ep = ctx[label]
            blend = collar_blend_for_params(ctx, label, **params)
            ret = slice_window(blend, *ep["window_used"]).values.astype(float)
            point_sharpe = annualized_sharpe(ret)
            per_block = {}
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
                    raw20[label] = boot
            by_episode[label] = {"point_sharpe": point_sharpe, "n_obs": int(len(ret)), "bootstrap_by_block_len": per_block}
            log(f"  {label}: point={point_sharpe:.3f} L20_CI90={per_block.get('20', {}).get('ci90')}")

        # H-D 결합전파: 이 config의 칼라 vs 무헤지 새틀라이트, 3개 기저확률 시나리오
        combined = {}
        for scenario, rates in BASE_RATES.items():
            alpha = np.array([rates[ep] * K_CENTRAL for ep in EPISODE_ORDER])
            dir_draws = rng.dirichlet(alpha, size=N_DRAWS)
            ev_collar = np.zeros(N_DRAWS)
            ev_unhedged = np.zeros(N_DRAWS)
            for i, label in enumerate(EPISODE_ORDER):
                sc = raw20.get(label)
                su = unhedged_boot.get(label)
                if sc is None or su is None or len(sc) == 0 or len(su) == 0:
                    continue
                idx_c = rng.integers(0, len(sc), size=N_DRAWS)
                idx_u = rng.integers(0, len(su), size=N_DRAWS)
                ev_collar += dir_draws[:, i] * sc[idx_c]
                ev_unhedged += dir_draws[:, i] * su[idx_u]
            gap = ev_collar - ev_unhedged
            combined[scenario] = {
                "win_rate_collar": float(np.mean(gap > 0)),
                "mean_gap": float(np.mean(gap)),
                "ci90_gap": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
                "mean_ev_collar": float(np.mean(ev_collar)), "mean_ev_unhedged": float(np.mean(ev_unhedged)),
            }
            log(f"  combined[{scenario}]: win_rate(collar)={combined[scenario]['win_rate_collar']:.3f} "
                f"CI90_gap={combined[scenario]['ci90_gap']}")

        config_results[cfg_name] = {
            "params": params, "by_episode": by_episode, "combined_dirichlet_x_bootstrap": combined,
        }

    return {
        "unhedged_satellite_point": unhedged_point,
        "representative_configs": config_results,
    }


def main():
    t0 = time.time()
    ctx = load_episode_context()

    grid = run_smoothness_grid(ctx)
    placebo = run_placebo_test(ctx)
    boot_combined = run_bootstrap_and_combined(ctx)

    out = {
        "meta": {
            "episode_order": EPISODE_ORDER, "live_default": LIVE_DEFAULT,
            "grid_put_moneyness": GRID_PUT_MONEYNESS, "grid_call_moneyness": GRID_CALL_MONEYNESS,
            "grid_tenor_days": GRID_TENOR_DAYS, "representative_configs": REPRESENTATIVE_CONFIGS,
            "base_rate_scenarios": BASE_RATES, "block_lengths": BLOCK_LENGTHS, "n_boot": N_BOOT,
            "n_draws_combined": N_DRAWS, "k_central": K_CENTRAL, "n_placebo": N_PLACEBO, "seed": SEED,
        },
        "smoothness_grid": grid,
        "placebo_test": placebo,
        "bootstrap_and_combined": boot_combined,
    }
    (OUT_DIR / "h_collar_sensitivity_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    log(f"저장 완료: h_collar_sensitivity_results.json ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
