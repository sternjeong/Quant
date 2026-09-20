"""블록부트스트랩 신뢰도 감사 — H1/H2/H3의 핵심 샤프비율 비교를 표본오차 관점에서 재검증.

이 저장소(트랙D 작업44, 트랙C 작업48/49)가 이미 쓴 방법론을 새로 만들지 않고 그대로 재사용한다:
원형 이동블록부트스트랩(moving_block_bootstrap_sharpe, 블록길이 10/20/40일, 2000회)로 각 구성의
샤프비율 표본분포를 만들고, 승률(win_rate = 구성A가 구성B를 이긴 부트스트랩 표본 비율)을 두 분포
간 원소별 비교로 추정한다 — 작업49(analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/
h_bootstrap_audit.py)가 "칼라 vs 무헤지" 승률을 계산한 것과 정확히 같은 방식.

감사 대상(H1~H3의 daily_returns csv에서 복원):
  - collar_spy vs unhedged (H1, 전체기간 + 낙폭구간)
  - collar_beta_scaled vs collar_spy (H2, 전체기간 + 낙폭구간)
  - collar_btc vs collar_spy (H3, 전체기간 + 낙폭구간) — 핵심 대조
  - collar_btc vs unhedged (H3, 낙폭구간) — "BTC칼라가 실제로 위기를 방어했다"는 주장 자체의 신뢰도
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "/opt/quant")
H33_DIR = "/opt/quant/analysis/2026-08-23_block_bootstrap_sample_error_quantification"
sys.path.insert(0, H33_DIR)
# h33 모듈 자체가 예전 워크트리 절대경로("/workspaces/Quant")를 하드코딩해서 champion_strategy/
# h1_core_satellite/h11_crisis_robustness_test 를 import 한다 - 이 저장소(/opt/quant)에서 그대로
# import만 재사용하려면 동일 파일이 실제로 위치한 로컬 analysis 폴더를 먼저 경로에 넣어주면 된다
# (h33의 로직 자체는 전혀 건드리지 않음, 순수 경로 해석 문제).
sys.path.insert(0, "/opt/quant/analysis/2026-08-19_champion_beta_and_satellite_research")
sys.path.insert(0, "/opt/quant/analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test")

import numpy as np
import pandas as pd

from common import OUT_DIR, max_drawdown_episode, equity_from_returns, log
from h33_block_bootstrap_sample_error import moving_block_bootstrap_sharpe, annualized_sharpe

BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
SEED = 20260915


def slice_window(s: pd.Series, start: str, end: str) -> pd.Series:
    return s[(s.index >= start) & (s.index <= end)]


def boot_for_series(ret: pd.Series, rng: np.random.Generator) -> dict:
    arr = ret.values.astype(float)
    point = annualized_sharpe(arr)
    by_L = {}
    for L in BLOCK_LENGTHS:
        boot = moving_block_bootstrap_sharpe(arr, L, N_BOOT, rng)
        boot = boot[~np.isnan(boot)]
        by_L[str(L)] = {
            "n_boot_valid": int(len(boot)),
            "mean": float(np.mean(boot)) if len(boot) else None,
            "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))] if len(boot) else None,
            "pct_sharpe_le_0": float(np.mean(boot <= 0)) if len(boot) else None,
            "_raw": boot,
        }
    return {"point_estimate_sharpe": point, "n_obs": len(arr), "by_block_len": by_L}


def win_rate(boot_a: dict, boot_b: dict, L: int = 20) -> float:
    a = boot_a["by_block_len"][str(L)]["_raw"]
    b = boot_b["by_block_len"][str(L)]["_raw"]
    n = min(len(a), len(b))
    if n == 0:
        return float("nan")
    return float(np.mean(a[:n] > b[:n]))


def strip_raw(d: dict) -> dict:
    out = json.loads(json.dumps({
        "point_estimate_sharpe": d["point_estimate_sharpe"], "n_obs": d["n_obs"],
        "by_block_len": {L: {k: v for k, v in blk.items() if k != "_raw"} for L, blk in d["by_block_len"].items()},
    }))
    return out


def audit_file(csv_path: str, pairs: list[tuple[str, str]], window: tuple[str, str] | None, rng) -> dict:
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    if window is not None:
        df = slice_window(df, window[0], window[1])
    boots = {col: boot_for_series(df[col], rng) for col in df.columns}
    comparisons = {}
    for a, b in pairs:
        if a not in boots or b not in boots:
            continue
        comparisons[f"{a}_vs_{b}"] = {
            "win_rate_a_over_b_L20": win_rate(boots[a], boots[b], 20),
            "win_rate_a_over_b_L10": win_rate(boots[a], boots[b], 10),
            "win_rate_a_over_b_L40": win_rate(boots[a], boots[b], 40),
            "point_gap": boots[a]["point_estimate_sharpe"] - boots[b]["point_estimate_sharpe"],
        }
    return {"n_obs": len(df), "by_config": {k: strip_raw(v) for k, v in boots.items()}, "comparisons": comparisons}


def main():
    rng = np.random.default_rng(SEED)

    # 낙폭구간 윈도우 재계산(H1과 동일 정의 재사용 - unhedged 컬럼 기준)
    h1_ret = pd.read_csv(f"{OUT_DIR}/h1_daily_returns.csv", index_col=0, parse_dates=True)
    unhedged_equity = equity_from_returns(h1_ret["unhedged"])
    episode = max_drawdown_episode(unhedged_equity)
    window = (episode["peak_date"], episode["recovery_date"])
    log(f"낙폭구간 윈도우(재확인): {window}, drawdown={episode['drawdown_pct']}%")

    result = {"meta": {"n_boot": N_BOOT, "block_lengths": BLOCK_LENGTHS, "seed": SEED, "episode_window": episode}}

    log("H1 감사(collar_spy vs unhedged, protective_put vs unhedged)...")
    h1_pairs = [("collar", "unhedged"), ("protective_put", "unhedged")]
    result["h1_full_period"] = audit_file(f"{OUT_DIR}/h1_daily_returns.csv", h1_pairs, None, rng)
    result["h1_drawdown_episode"] = audit_file(f"{OUT_DIR}/h1_daily_returns.csv", h1_pairs, window, rng)

    log("H2 감사(collar_beta_scaled vs collar_1x_notional)...")
    h2_pairs = [("collar_beta_scaled", "collar_1x_notional"), ("collar_1x_notional", "unhedged")]
    result["h2_full_period"] = audit_file(f"{OUT_DIR}/h2_daily_returns.csv", h2_pairs, None, rng)
    result["h2_drawdown_episode"] = audit_file(f"{OUT_DIR}/h2_daily_returns.csv", h2_pairs, window, rng)

    log("H3 감사(collar_btc vs collar_spy, collar_btc vs unhedged)...")
    h3_pairs = [("collar_btc", "collar_spy"), ("collar_btc", "unhedged"), ("collar_spy", "unhedged")]
    result["h3_full_period"] = audit_file(f"{OUT_DIR}/h3_daily_returns.csv", h3_pairs, None, rng)
    result["h3_drawdown_episode"] = audit_file(f"{OUT_DIR}/h3_daily_returns.csv", h3_pairs, window, rng)

    for key in ["h1_full_period", "h1_drawdown_episode", "h2_full_period", "h2_drawdown_episode",
                "h3_full_period", "h3_drawdown_episode"]:
        log(f"  {key}: {result[key]['comparisons']}")

    with open(f"{OUT_DIR}/bootstrap_audit_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log("부트스트랩 감사 완료.")
    return result


if __name__ == "__main__":
    main()
