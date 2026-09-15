"""리서치 에이전트 D (라운드 1) — 후보 전략 백테스트 + 매매빈도 실측 + 순열검정/블록부트스트랩 감사.

이 스크립트는 새 전략을 발명하지 않는다. `core/champion_strategy.py`가 이미 라이브로 계산하는
두 개의 기존 구성을 그대로 실행해 "매매빈도 제약(월 1~3회)" 관점에서 비교한다:

  - 후보 1 "코어 단독": run_core_backtest() 기본값 그대로 (17자산, 월간 리밸런싱, top4 동일비중,
    양(+)모멘텀 필터, SPY 200일선 이진 시장필터) — 새틀라이트 제외.
  - 후보 2 "코어+새틀라이트": run_champion_backtest() 기본값 그대로(코어와 동일 + 15% 새틀라이트
    반기(1월/7월) 정적 리밸런싱, 돈치안 20일 브레이크아웃+트레일링스탑 추세추종).

confidence_table(analysis/2026-09-05_research_program_synthesis/report_data.json) 기준:
  - robust: 코어 17자산 유니버스
  - moderate: 12개월 모멘텀 랭킹, 새틀라이트 정적보유(청산/스위치 메커니즘)
  - weak: 리밸런싱 주기(월간), 이진 시장필터, 새틀라이트 포함 여부/선정방식
두 후보 모두 이미 라이브 기본값이므로 이 스크립트가 처음 만드는 파라미터 조합은 없다 — "발명"이
아니라 "실측"이다. weak 등급 구성요소(시장필터·새틀라이트 포함여부)는 이미 살아있는 기본값을
그대로 쓰되, 그 확신도가 낮다는 것을 결론에 정직하게 반영한다.

측정 항목:
  1. 월평균 매매횟수(회전율이 아니라 실제 주문 발생 횟수 — 종목별 비중이 0이 아닌 값으로
     바뀔 때마다 1건으로 센다. 시장필터가 켜지고 꺼지며 기존 보유 종목의 비중만 바뀌는 것도
     실제로는 주문이 필요하므로 1건으로 센다).
  2. CAGR/MDD/샤프/칼마 (core.backtest_engine.calculate_metrics, 기존 관례 그대로).
  3. 순열검정 — 작업21(No.06)이 멀티에셋 모멘텀 로테이션에 썼던 방법론("매달 상위4개 랭킹 대신
     양모멘텀 후보 중 무작위 4개를 뽑아도 비슷한가")을 코드가 삭제된 관례에 따라 이번 후보의
     정확한 백테스트 구간/설정으로 재구현한다(core.champion_strategy._build_core_weights의
     신호계산 로직은 그대로 재사용하고 선택 스텝만 랜덤으로 바꾼 로컬 변형).
  4. 블록부트스트랩 — 작업44/45(H33/H34)와 동일 방법론(순환 이동블록부트스트랩, L=10/20/40일
     중심 20일, 창당 표본 재사용) 재사용, 여기서는 전체 구간 단일 창에 적용(각 후보의 샤프
     표본오차 + 후보1 대비 후보2의 승률).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics, _first_trading_day_of_month_mask
from core.champion_strategy import (
    CORE_UNIVERSE, CORE_MOMENTUM_LOOKBACK_DAYS, CORE_TOP_N, MARKET_FILTER_TICKER,
    MARKET_FILTER_SMA_WINDOW, MARKET_FILTER_EXPOSURE_CUT, SATELLITE_WEIGHT,
    run_core_backtest, run_champion_backtest, _compute_portfolio_returns, _closes_from_histories,
)
from core.market_data import get_multiple_price_history, get_price_history

OUT_DIR = Path(__file__).resolve().parent
START = "2019-08-12"  # 작업44/45(H33/H34)가 쓴 "full_2019_2026" 창과 동일 — 17자산(XLC/XLRE 포함)
                       # 모멘텀 웜업(약 1년)을 감안한 시작점, 기존 감사와 비교 가능하게 유지.
END = "2026-09-11"
SEED = 20260914
N_PERMUTATIONS = 200
N_BOOT = 1500
BLOCK_LENGTHS = [10, 20, 40]
TRADING_DAYS = 252


def log(msg):
    print(f"[D-round1] {msg}", flush=True)


# ----------------------------------------------------------------------------
# 1) 매매빈도 실측
# ----------------------------------------------------------------------------
def count_weight_change_trades(weights: pd.DataFrame, eps: float = 1e-9) -> dict:
    """weights(일별, ffill됨)에서 종목별 비중이 바뀐 날짜만 골라 "그 날 바뀐 종목 수"를 더한다.
    최초 진입(첫 행)도 매수로 센다. 반환: total_trades, n_rebalance_events, per_event_log."""
    diffs = weights.diff().abs()
    diffs.iloc[0] = weights.iloc[0].abs()
    changed_counts = (diffs > eps).sum(axis=1)
    events = changed_counts[changed_counts > 0]
    return {
        "total_trades": int(events.sum()),
        "n_rebalance_events": int(len(events)),
        "per_event": [{"date": str(d.date()), "n_tickers_traded": int(c)} for d, c in events.items()],
    }


def count_satellite_trades(rebal_log: list[dict]) -> dict:
    total = 0
    per_event = []
    prev_picks: set[str] = set()
    for entry in rebal_log:
        picks = set(entry["picks"])
        n = len(picks - prev_picks) + len(prev_picks - picks)
        total += n
        per_event.append({"date": entry["date"], "n_tickers_traded": n, "picks": entry["picks"]})
        prev_picks = picks
    return {"total_trades": total, "n_rebalance_events": len(rebal_log), "per_event": per_event}


def n_months_in_period(start: str, end: str) -> float:
    return (pd.Timestamp(end) - pd.Timestamp(start)).days / 30.4368


# ----------------------------------------------------------------------------
# 2) 순열검정 (무작위 선택 vs 실제 모멘텀 랭킹) — 코어 로테이션 전용
# ----------------------------------------------------------------------------
def _build_core_weights_random(
    closes: pd.DataFrame,
    market_close: pd.Series,
    rng: np.random.Generator,
    apply_market_filter: bool = True,
    top_n: int = CORE_TOP_N,
    exposure_cut: float = MARKET_FILTER_EXPOSURE_CUT,
) -> pd.DataFrame:
    """core.champion_strategy._build_core_weights와 완전히 동일한 신호/시장필터 로직이지만,
    top-N 랭킹 선택 대신 "양(+)모멘텀 후보 중 무작위 top_n개"를 뽑는다(작업21 방법론 재구현)."""
    momentum = closes.pct_change(CORE_MOMENTUM_LOOKBACK_DAYS)
    is_rebal = _first_trading_day_of_month_mask(closes.index)
    sma200 = market_close.rolling(MARKET_FILTER_SMA_WINDOW, min_periods=MARKET_FILTER_SMA_WINDOW).mean()

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            eligible = mom[mom > 0].index.tolist()
            n_pick = min(top_n, len(eligible))
            picks = rng.choice(eligible, size=n_pick, replace=False) if n_pick > 0 else []
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / top_n
            if apply_market_filter and signal_date in sma200.index and not pd.isna(sma200.loc[signal_date]):
                if market_close.loc[signal_date] < sma200.loc[signal_date]:
                    w = w * exposure_cut
            last_weights = w
        weights.iloc[i] = last_weights.values
    return weights


def run_core_permutation_test(start: str, end: str, n_permutations: int, seed: int) -> dict:
    tickers = list(CORE_UNIVERSE)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=400)).date().isoformat()
    histories = get_multiple_price_history(tickers + [MARKET_FILTER_TICKER], start=fetch_start, end=end, interval="1d")
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    closes_sliced = closes.loc[sliced_idx]

    actual = run_core_backtest(start, end)
    actual_sharpe = actual["metrics"]["sharpe"]

    rng = np.random.default_rng(seed)
    permuted_sharpes = []
    for it in range(n_permutations):
        w_full = _build_core_weights_random(closes, market_close, rng)
        w_sliced = w_full.loc[sliced_idx]
        result = _compute_portfolio_returns(closes_sliced, w_sliced)
        m = calculate_metrics(result["equity_net"], [], sliced_idx[0], sliced_idx[-1])
        permuted_sharpes.append(m["sharpe"])
        if (it + 1) % 40 == 0:
            log(f"   순열검정 {it + 1}/{n_permutations} (현재까지 평균 샤프 {np.mean(permuted_sharpes):.3f})")

    worse = sum(1 for s in permuted_sharpes if s < actual_sharpe)
    better_or_equal = sum(1 for s in permuted_sharpes if s >= actual_sharpe)
    percentile = round(100.0 * worse / len(permuted_sharpes), 2)
    p_value = round((better_or_equal + 1) / (n_permutations + 1), 4)

    return {
        "actual_sharpe": actual_sharpe,
        "permuted_sharpes": [round(float(s), 4) for s in permuted_sharpes],
        "permuted_mean": round(float(np.mean(permuted_sharpes)), 4),
        "permuted_std": round(float(np.std(permuted_sharpes)), 4),
        "percentile": percentile,
        "p_value": p_value,
        "n_permutations": n_permutations,
        "methodology": (
            "작업21(No.06) 방법론 재구현 — 매달 상위4개 모멘텀 랭킹 대신 양(+)모멘텀 후보 중 "
            "무작위 4개를 뽑되 시장필터/비용모델/리밸런싱 스케줄은 실제 후보1과 완전히 동일하게 유지."
        ),
    }


# ----------------------------------------------------------------------------
# 3) 블록부트스트랩 (작업44/45 H33/H34와 동일 방법론)
# ----------------------------------------------------------------------------
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


def bootstrap_audit(ret_by_cfg: dict[str, pd.Series], rng: np.random.Generator) -> dict:
    out = {}
    boot_l20 = {}
    for cfg, ret in ret_by_cfg.items():
        arr = ret.values.astype(float)
        point_sharpe = annualized_sharpe(arr)
        per_block = {}
        for L in BLOCK_LENGTHS:
            boot = moving_block_bootstrap_sharpe(arr, L, N_BOOT, rng)
            boot = boot[~np.isnan(boot)]
            if L == 20:
                boot_l20[cfg] = boot
            per_block[str(L)] = {
                "n_boot_valid": int(len(boot)),
                "mean": float(np.mean(boot)) if len(boot) else None,
                "std": float(np.std(boot)) if len(boot) else None,
                "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))] if len(boot) else None,
            }
        out[cfg] = {"n_obs": int(len(arr)), "point_estimate_sharpe": point_sharpe, "bootstrap_by_block_len": per_block}
        log(f"   부트스트랩 {cfg}: point_sharpe={point_sharpe:.3f}, L=20 CI90={per_block['20']['ci90']}")

    # 후보2(코어+새틀라이트) vs 후보1(코어단독) 승률 — L=20 표본 페어 비교(같은 시장기간, 독립표본 취급)
    win_rate = None
    if "candidate_2_core_satellite" in boot_l20 and "candidate_1_core_only" in boot_l20:
        a = boot_l20["candidate_1_core_only"]
        b = boot_l20["candidate_2_core_satellite"]
        n = min(len(a), len(b))
        win_rate = float(np.mean(b[:n] > a[:n]))
    return {"by_config": out, "candidate2_vs_candidate1_win_rate_L20": win_rate}


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    t0 = time.time()
    result = {
        "meta": {
            "generated": "2026-09-14",
            "round": 1,
            "period": {"start": START, "end": END},
            "seed": SEED,
            "n_permutations": N_PERMUTATIONS,
            "n_boot": N_BOOT,
            "block_lengths": BLOCK_LENGTHS,
        }
    }

    log("=== 후보 1: 코어 단독 백테스트 ===")
    c1 = run_core_backtest(START, END)
    log(f"   메트릭: {c1['metrics']}")
    c1_trades = count_weight_change_trades(c1["weights"])
    months = n_months_in_period(c1["start"], c1["end"])
    c1_trades_per_month = c1_trades["total_trades"] / months
    log(f"   매매횟수: 총 {c1_trades['total_trades']}건 / {months:.1f}개월 = 월평균 {c1_trades_per_month:.2f}건")

    log("=== 후보 2: 코어+새틀라이트 백테스트 ===")
    c2 = run_champion_backtest(START, END)
    log(f"   메트릭: {c2['metrics']}")
    c2_core_trades = count_weight_change_trades(c2["core"]["weights"])
    c2_sat_trades = count_satellite_trades(c2["satellite"]["rebal_log"])
    c2_total_trades = c2_core_trades["total_trades"] + c2_sat_trades["total_trades"]
    c2_trades_per_month = c2_total_trades / months
    log(f"   코어 매매: {c2_core_trades['total_trades']}건, 새틀라이트 매매: {c2_sat_trades['total_trades']}건, "
        f"합계 월평균 {c2_trades_per_month:.2f}건")

    log("=== SPY 매수보유 벤치마크 ===")
    spy = get_price_history("SPY", start=START, end=END, use_cache=True)
    spy_ret = spy["Close"].pct_change().fillna(0.0)
    spy_ret = spy_ret[(spy_ret.index >= pd.Timestamp(c1["start"])) & (spy_ret.index <= pd.Timestamp(c1["end"]))]
    spy_equity = (1.0 + spy_ret).cumprod() * 100.0
    spy_equity.iloc[0] = 100.0
    spy_metrics = calculate_metrics(spy_equity, [], spy_ret.index[0], spy_ret.index[-1])
    log(f"   SPY 메트릭: {spy_metrics}")

    result["candidate_1_core_only"] = {
        "label": "코어 단독 (챔피언 코어 기본값 그대로, 새틀라이트 제외)",
        "start": c1["start"], "end": c1["end"],
        "metrics": c1["metrics"],
        "trades": c1_trades,
        "trades_per_month": round(c1_trades_per_month, 3),
    }
    result["candidate_2_core_satellite"] = {
        "label": "코어+새틀라이트 (챔피언 기본값 그대로, 15% 반기 새틀라이트 포함)",
        "start": c2["start"], "end": c2["end"],
        "metrics": c2["metrics"],
        "core_trades": c2_core_trades,
        "satellite_trades": c2_sat_trades,
        "total_trades": c2_total_trades,
        "trades_per_month": round(c2_trades_per_month, 3),
    }
    result["spy_buyhold"] = {"metrics": spy_metrics}
    result["n_months_in_period"] = round(months, 2)

    log("=== 순열검정 (후보1 코어 로테이션 — 무작위선택 대비) ===")
    perm = run_core_permutation_test(START, END, N_PERMUTATIONS, SEED)
    log(f"   실제 샤프 {perm['actual_sharpe']} -> 백분위 {perm['percentile']}, p={perm['p_value']}")
    result["permutation_test_candidate_1"] = perm

    log("=== 블록부트스트랩 감사 (후보1/후보2/SPY) ===")
    rng = np.random.default_rng(SEED + 1)
    ret_by_cfg = {
        "candidate_1_core_only": c1["ret_net"],
        "candidate_2_core_satellite": c2["ret_net"],
        "spy_buyhold": spy_ret,
    }
    boot = bootstrap_audit(ret_by_cfg, rng)
    result["bootstrap_audit"] = boot

    result["total_runtime_sec"] = round(time.time() - t0, 1)
    with open(OUT_DIR / "report_data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/report_data.json (총 {result['total_runtime_sec']}초)")


if __name__ == "__main__":
    main()
