"""감사 2 - 베타/알파 헤징 H1(시장베타헤지)/H3(BAB 저베타틸트)에 부트스트랩+시나리오 MC 감사 적용.

작업28이 H1/H3를 검증한 방법은 "전체구간 한 번의 백테스트로 헤지전후/포트폴리오간 샤프를 비교"뿐
이었다 — 트랙D가 H22~H34에서 반복 적용한 두 겹 불확실성(가중치 불확실성 + 표본오차)이 한 번도
걸리지 않았다.

트랙D의 "6개 위기 아키타입"은 섹터 로테이션 챔피언(17자산, 다중 사이클) 얘기라 이 바스켓(단일
테마, IPO/피벗이 최근 몇 년 안에 몰려있음)에는 그대로 옮겨붙일 수 없다 — 애초에 2008/2015-16/2018
같은 창에는 이 종목들이 존재하지도 않았다. 대신 이 바스켓이 실제로 겪은 4개의 뚜렷이 다른 국면을
"시나리오 아키타입"으로 쓴다(비트코인 채굴~AI 피벗 테마 고유의 국면 구분, 웹 리서치로 확인된 사건
기준):
  - crypto_bull_2020_2021: 비트코인 3차 반감기 이후 대세 상승장(2020-01~2021-12) — 이 종목군이
    "채굴주"로만 움직였던 시기, AI 서사는 아직 없었음.
  - crypto_winter_2022: 연준 긴축 + FTX 파산(2022-11) 등 크립토 시장 전반 붕괴(2022-01~2022-12).
  - ai_pivot_rerating_2023_2025: ChatGPT발 AI 인프라 수요로 IREN 등이 채굴에서 AI/HPC 데이터센터로
    피벗을 선언하고 재평가받은 구간(2023-01~2025-12, 마이크로소프트-IREN 97억달러 계약 등 포함).
  - recent_2026: 2026년 진행분(2026-01~현재) — 아직 완결되지 않은 최신 구간, 별도 취급.
각 아키타입의 "기저확률"은 이 표본 안에서 실제로 관측된 거래일 비중을 기본 추정치로 쓴다(향후
어느 국면이 다시 올지 알 수 없다는 전제 하에, "과거에 이런 유형의 국면이 실제로 차지했던 시간
비중"을 최선의 사전 추정으로 삼는 H22와 동일한 논리) — 다만 이 자체가 "정답"이 아니라 하나의 정직한
가정이라는 걸 명시하고, H30 스타일로 디리클레 집중도(K=15/30/60)를 스윕해 민감도를 함께 보고한다.

방법론(H33/H33b와 완전히 동일한 두 단계):
  1. 각 아키타입 구간에서 H1(베이스라인 무헤지 vs 롤링베타헤지, 7종목 동일가중 바스켓)과 H3(EW vs
     저베타틸트 LB, 6종목 주표본)의 일별 수익률을 원본 h1/h3 스크립트와 동일한 계산으로 복원한다.
  2. 각 (아키타입 x 구성) 조합에 원형 이동블록부트스트랩(L=10/20/40, 2000회)을 적용해 샤프 표본분포를
     만든다.
  3. H33b와 동일하게 "가중치만(H30 방식)" / "표본오차만" / "결합" 세 가지 전파로 챌린저(헤지/저베타)가
     베이스라인(무헤지/EW)을 이기는 승률을 계산한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
HEDGE_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-19_iren_beta_alpha_hedging"
sys.path.insert(0, str(HEDGE_DIR))
BOOT_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-23_block_bootstrap_sample_error_quantification"
sys.path.insert(0, str(BOOT_DIR))

import numpy as np
import pandas as pd

from common import (
    MARKET_TICKER, PEER_TICKERS, align, daily_returns, fetch_close, one_factor_ols,
    rolling_beta,
)
from h3_low_beta_tilt import _build_universe_data, _beta_matrix, _momentum_matrix, _simulate, BETA_WINDOW, MOM_WINDOW as H3_MOM_WINDOW
from h33_block_bootstrap_sample_error import moving_block_bootstrap_sharpe, annualized_sharpe

OUT_DIR = Path(__file__).resolve().parent

ARCHETYPES = {
    "crypto_bull_2020_2021": ("2020-01-01", "2021-12-31"),
    "crypto_winter_2022": ("2022-01-01", "2022-12-31"),
    "ai_pivot_rerating_2023_2025": ("2023-01-01", "2025-12-31"),
    "recent_2026": ("2026-01-01", "2026-08-19"),
}
ARCHETYPE_ORDER = list(ARCHETYPES.keys())

H1_ROLLING_WINDOW = 126
H1_START, H1_END = "2020-01-01", "2026-08-19"
H3_START, H3_END = "2015-01-01", "2026-08-19"

BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
N_DRAWS = 10000
K_VALUES = [15, 30, 60]
K_CENTRAL = 30
SEED = 20260830


def log(msg):
    print(f"[audit2] {msg}", flush=True)


def slice_window(s: pd.Series, start: str, end: str) -> pd.Series:
    return s[(s.index >= start) & (s.index <= end)]


# ---------------------------------------------------------------------------
# H1: 7종목 동일가중 바스켓, 롤링베타 헤지 vs 무헤지 (h1_market_beta_hedge.hedge_basket 재구현,
#     반환값을 raw daily series로 확장)
# ---------------------------------------------------------------------------
def h1_basket_series(tickers: list[str], window: int = H1_ROLLING_WINDOW) -> tuple[pd.Series, pd.Series]:
    closes = {t: fetch_close(t, H1_START, H1_END) for t in tickers}
    closes = {t: c for t, c in closes.items() if not c.empty}
    rets = {t: daily_returns(c) for t, c in closes.items()}
    common_idx = None
    for r in rets.values():
        common_idx = r.index if common_idx is None else common_idx.intersection(r.index)
    common_idx = common_idx.sort_values()
    rets_aligned = pd.DataFrame({t: r.reindex(common_idx) for t, r in rets.items()}).dropna()
    basket_ret = rets_aligned.mean(axis=1)

    mkt_close = fetch_close(MARKET_TICKER, H1_START, H1_END)
    r_mkt = daily_returns(mkt_close)
    basket_ret_a, r_mkt_a = align(basket_ret, r_mkt)

    beta_roll = rolling_beta(basket_ret_a, r_mkt_a, window).shift(1)
    valid = beta_roll.dropna().index
    basket_v = basket_ret_a.reindex(valid)
    mkt_v = r_mkt_a.reindex(valid)
    beta_v = beta_roll.reindex(valid).clip(lower=-2.0, upper=5.0)

    unhedged_ret = basket_v
    hedged_ret = basket_v - beta_v * mkt_v
    return unhedged_ret, hedged_ret


# ---------------------------------------------------------------------------
# H3: 6종목 주표본, EW vs LB(저베타틸트) (h3_low_beta_tilt._simulate 그대로 재사용)
# ---------------------------------------------------------------------------
def h3_ew_lb_series(tickers: list[str]) -> tuple[pd.Series, pd.Series]:
    returns_df, r_mkt = _build_universe_data(tickers)
    beta_df = _beta_matrix(returns_df, r_mkt, BETA_WINDOW)
    mom_df = _momentum_matrix(returns_df, H3_MOM_WINDOW)
    port_rets = _simulate(returns_df, beta_df, mom_df)
    return port_rets["EW"], port_rets["LB"]


def bootstrap_sharpe_dist(ret: np.ndarray, rng: np.random.Generator, block_len: int = 20) -> tuple[float, np.ndarray]:
    point = annualized_sharpe(ret)
    boot = moving_block_bootstrap_sharpe(ret, block_len, N_BOOT, rng)
    boot = boot[~np.isnan(boot)]
    return point, boot


def compute_archetype_bootstrap(baseline_full: pd.Series, challenger_full: pd.Series, rng: np.random.Generator) -> dict:
    """전체 시리즈를 4개 아키타입 구간으로 슬라이스하고 각각 부트스트랩."""
    out = {}
    for arche, (a_start, a_end) in ARCHETYPES.items():
        base_w = slice_window(baseline_full, a_start, a_end).dropna()
        chal_w = slice_window(challenger_full, a_start, a_end).dropna()
        common_idx = base_w.index.intersection(chal_w.index)
        base_w, chal_w = base_w.reindex(common_idx), chal_w.reindex(common_idx)
        n_obs = int(len(common_idx))
        entry = {"n_obs": n_obs, "window": [a_start, a_end], "by_config": {}}
        for cfg_name, arr in (("baseline", base_w.values.astype(float)), ("challenger", chal_w.values.astype(float))):
            by_block = {}
            boot_l20 = None
            for L in BLOCK_LENGTHS:
                if n_obs < 5:
                    by_block[str(L)] = None
                    continue
                point, boot = bootstrap_sharpe_dist(arr, rng, block_len=L)
                by_block[str(L)] = {
                    "point_estimate_sharpe": point,
                    "mean": float(np.mean(boot)) if len(boot) else None,
                    "std": float(np.std(boot)) if len(boot) else None,
                    "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))] if len(boot) else None,
                }
                if L == 20:
                    boot_l20 = boot
            entry["by_config"][cfg_name] = {
                "point_estimate_sharpe": annualized_sharpe(arr) if n_obs >= 2 else None,
                "by_block_len": by_block,
                "_boot_l20_samples": boot_l20.tolist() if boot_l20 is not None else [],
            }
        out[arche] = entry
    return out


def base_rates_from_n_obs(archetype_boot: dict, valid_archetypes: list[str]) -> dict:
    """관측된 표본의 거래일 수를 기저확률로 사용 (baseline 구성 n_obs 기준), 유효한 아키타입만."""
    n_obs = {a: archetype_boot[a]["n_obs"] for a in valid_archetypes}
    total = sum(n_obs.values())
    return {a: n_obs[a] / total for a in valid_archetypes}


def dirichlet_draws(base_rates: dict, k: float, n: int, rng: np.random.Generator, order: list[str]) -> np.ndarray:
    alpha = np.array([base_rates[a] * k for a in order])
    alpha = np.clip(alpha, 1e-3, None)
    return rng.dirichlet(alpha, size=n)


def weighting_only_ev(draws: np.ndarray, point_sharpe: dict, order: list[str]) -> dict:
    ev = {}
    for cfg in ("baseline", "challenger"):
        vec = np.array([point_sharpe[a][cfg] for a in order])
        ev[cfg] = draws @ vec
    return ev


def sampling_only_ev(archetype_boot: dict, fixed_weights: np.ndarray, n: int, rng: np.random.Generator, order: list[str]) -> dict:
    ev = {}
    for cfg in ("baseline", "challenger"):
        per_arche = []
        for a in order:
            samples = np.array(archetype_boot[a]["by_config"][cfg]["_boot_l20_samples"])
            if len(samples) == 0:
                samples = np.array([archetype_boot[a]["by_config"][cfg]["point_estimate_sharpe"]] * 10)
            idx = rng.integers(0, len(samples), size=n)
            per_arche.append(samples[idx])
        stacked = np.column_stack(per_arche)
        ev[cfg] = stacked @ fixed_weights
    return ev


def combined_ev(archetype_boot: dict, dir_draws: np.ndarray, n: int, rng: np.random.Generator, order: list[str]) -> dict:
    ev = {}
    for cfg in ("baseline", "challenger"):
        per_arche = []
        for a in order:
            samples = np.array(archetype_boot[a]["by_config"][cfg]["_boot_l20_samples"])
            if len(samples) == 0:
                samples = np.array([archetype_boot[a]["by_config"][cfg]["point_estimate_sharpe"]] * 10)
            idx = rng.integers(0, len(samples), size=n)
            per_arche.append(samples[idx])
        stacked = np.column_stack(per_arche)
        ev[cfg] = np.sum(stacked * dir_draws, axis=1)
    return ev


def summarize(ev: dict) -> dict:
    stacked = np.column_stack([ev["baseline"], ev["challenger"]])
    winner_idx = np.argmax(stacked, axis=1)
    win_rate_challenger = float(np.mean(winner_idx == 1))
    gap = ev["challenger"] - ev["baseline"]
    return {
        "win_rate_challenger": win_rate_challenger,
        "mean_ev": {"baseline": float(np.mean(ev["baseline"])), "challenger": float(np.mean(ev["challenger"]))},
        "gap_challenger_minus_baseline": {
            "mean": float(np.mean(gap)),
            "ci90": [float(np.percentile(gap, 5)), float(np.percentile(gap, 95))],
            "pct_draws_challenger_ahead": float(np.mean(gap > 0)),
        },
    }


def run_hypothesis(label: str, baseline_full: pd.Series, challenger_full: pd.Series, rng: np.random.Generator) -> dict:
    log(f"{label}: 아키타입별 부트스트랩 계산 중...")
    archetype_boot = compute_archetype_bootstrap(baseline_full, challenger_full, rng)

    # 데이터가 사실상 없는(전 티커 교집합이 비어있는) 아키타입은 기저확률/전파 계산에서 제외한다
    # (예: H1의 7종목 바스켓은 IREN/CIFR/BTDR의 늦은 상장일 때문에 2020-2021 교집합이 거의 없음).
    MIN_OBS = 20
    excluded = []
    valid_archetypes = []
    for a in ARCHETYPE_ORDER:
        n = archetype_boot[a]["n_obs"]
        ps_base = archetype_boot[a]["by_config"]["baseline"]["point_estimate_sharpe"]
        ps_chal = archetype_boot[a]["by_config"]["challenger"]["point_estimate_sharpe"]
        if n < MIN_OBS or ps_base is None or ps_chal is None or (isinstance(ps_base, float) and np.isnan(ps_base)):
            excluded.append({"archetype": a, "n_obs": n, "reason": "insufficient_common_data"})
        else:
            valid_archetypes.append(a)

    base_rates = base_rates_from_n_obs(archetype_boot, valid_archetypes)
    point_sharpe = {a: {cfg: archetype_boot[a]["by_config"][cfg]["point_estimate_sharpe"] for cfg in ("baseline", "challenger")}
                    for a in valid_archetypes}

    k_sensitivity = {}
    for k in K_VALUES:
        dir_draws = dirichlet_draws(base_rates, k, N_DRAWS, rng, valid_archetypes)
        weighting_only_summary = summarize(weighting_only_ev(dir_draws, point_sharpe, valid_archetypes))
        k_sensitivity[str(k)] = weighting_only_summary["win_rate_challenger"]

    dir_draws_central = dirichlet_draws(base_rates, K_CENTRAL, N_DRAWS, rng, valid_archetypes)
    weighting_only = summarize(weighting_only_ev(dir_draws_central, point_sharpe, valid_archetypes))

    fixed_weights = np.array([base_rates[a] for a in valid_archetypes])
    sampling_only = summarize(sampling_only_ev(archetype_boot, fixed_weights, N_DRAWS, rng, valid_archetypes))

    combined = summarize(combined_ev(archetype_boot, dir_draws_central, N_DRAWS, rng, valid_archetypes))

    # strip large raw sample arrays before saving json (keep summary stats only)
    archetype_boot_clean = {}
    for a, d in archetype_boot.items():
        archetype_boot_clean[a] = {
            "n_obs": d["n_obs"], "window": d["window"],
            "by_config": {cfg: {"point_estimate_sharpe": d["by_config"][cfg]["point_estimate_sharpe"],
                                  "by_block_len": d["by_config"][cfg]["by_block_len"]}
                          for cfg in ("baseline", "challenger")},
        }

    return {
        "label": label,
        "valid_archetypes": valid_archetypes,
        "excluded_archetypes": excluded,
        "base_rates": base_rates,
        "archetype_bootstrap": archetype_boot_clean,
        "k_sensitivity_weighting_only_win_rate": k_sensitivity,
        "weighting_only_H30_style": weighting_only,
        "sampling_only_bootstrap": sampling_only,
        "combined_weighting_x_sampling": combined,
    }


def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)

    log("H1 데이터 로딩 (7종목 피어 바스켓)...")
    h1_unhedged, h1_hedged = h1_basket_series(PEER_TICKERS)
    h1_unhedged.to_csv(OUT_DIR / "h1_basket_unhedged_ret.csv", header=["ret"])
    h1_hedged.to_csv(OUT_DIR / "h1_basket_hedged_ret.csv", header=["ret"])
    h1_result = run_hypothesis("H1_market_beta_hedge_basket", h1_unhedged, h1_hedged, rng)

    log("H3 데이터 로딩 (6종목 주표본, EW vs LB)...")
    h3_tickers = [t for t in PEER_TICKERS if t != "CORZ"]
    h3_ew, h3_lb = h3_ew_lb_series(h3_tickers)
    h3_ew.to_csv(OUT_DIR / "h3_ew_ret.csv", header=["ret"])
    h3_lb.to_csv(OUT_DIR / "h3_lb_ret.csv", header=["ret"])
    h3_result = run_hypothesis("H3_low_beta_tilt", h3_ew, h3_lb, rng)

    out = {
        "meta": {
            "n_boot": N_BOOT, "n_draws": N_DRAWS, "block_lengths": BLOCK_LENGTHS,
            "k_values": K_VALUES, "k_central": K_CENTRAL, "seed": SEED,
            "archetypes": ARCHETYPES, "archetype_order": ARCHETYPE_ORDER,
            "h1_universe": PEER_TICKERS, "h3_universe": h3_tickers,
        },
        "h1": h1_result,
        "h3": h3_result,
    }
    (OUT_DIR / "audit2_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"저장 완료 audit2_results.json ({time.time()-t0:.1f}s)")
    log(f"H1 weighting-only win(hedge)={h1_result['weighting_only_H30_style']['win_rate_challenger']:.3f}, "
        f"combined={h1_result['combined_weighting_x_sampling']['win_rate_challenger']:.3f}")
    log(f"H3 weighting-only win(LB)={h3_result['weighting_only_H30_style']['win_rate_challenger']:.3f}, "
        f"combined={h3_result['combined_weighting_x_sampling']['win_rate_challenger']:.3f}")


if __name__ == "__main__":
    main()
