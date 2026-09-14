"""H31 - 모멘텀 룩백기간 x 리밸런싱 주기 결합(joint) 그리드 탐색.

작업40(H27)이 룩백기간을, 작업41(H29)이 리밸런싱 주기를 각각 "다른 파라미터는 그 시점까지의
기존 기본값에 고정한 채" 독립적으로 스윕해 12개월/월간이라는 "순차 최적화" 결과에 도달했다. 이
스크립트는 두 파라미터를 동시에 바꾸는 2D 그리드를 만들어, H22와 동일한 기저확률 가중 기댓값
프레임으로 각 그리드 점을 채점하고, 순차 최적점(12개월, 월간)이 실제 결합 최적점과 얼마나
가까운지를 직접 확인한다.

그리드 해상도(명시적 트레이드오프, 스펙이 요구한대로 정직하게 축소):
  - 룩백: 6/9/12/15/18개월 (H27이 스윕한 3~18개월 범위 중 3개월 지점만 제외 - 3개월은 H27에서
    세 시나리오 모두 뚜렷한 꼴찌였으므로 결합그리드에서 굳이 재확인할 값이 아니라고 판단, 나머지
    5개 지점은 H27과 동일하게 유지해 직접 비교 가능하게 함)
  - 리밸런싱: 격주(10일)/월간(21일)/6주(30일)/분기(63일) 4개 (H29가 스윕한 5개 중 "주간(5일)"만
    제외 - H29 결과에서 주간은 세 시나리오 모두 압도적 꼴찌(회전율 연1014%로 비용 폭발)였으므로
    결합그리드에서 재확인 우선순위가 가장 낮다고 판단)
  → 5 x 4 = 20 그리드점 x 6개 창(전체기간+5개 위기) = 120회 백테스트.
  H27/H29 개별 스윕은 6곳 x 6개 값 = 36회였으므로, 격자 해상도를 낮춰(각 축 6->5, 6->4) 계산량을
  120회로 억제했다 - 온전한 2D 결과를 우선한다는 스펙 요구를 그대로 따름.

champion_strategy의 build_champion_weights 로직을 momentum_window와 rebal_days 둘 다 파라미터로
받도록 일반화한 버전을 이 스크립트 안에 직접 구현한다(H27의 momentum_window만 바꾸는 버전과 H29의
rebal_days만 바꾸는 버전을 병합).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, "/workspaces/Quant/analysis/2026-08-19_champion_beta_and_satellite_research")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics
from champion_strategy import (  # noqa: E402
    CHAMPION_UNIVERSE, MARKET_FILTER_TICKER, MARKET_FILTER_MA, MARKET_FILTER_SCALE_BELOW,
    TOP_N, WARMUP_DAYS, fetch_champion_histories, _closes_from_histories, compute_portfolio_returns,
)

OUT_DIR = Path(__file__).resolve().parent

WINDOWS = {
    "full_2019_2026": ("2019-08-12", "2026-08-19"),
    "gfc_2008": ("2007-10-01", "2009-06-30"),
    "covid_2020": ("2020-02-19", "2020-04-30"),
    "bear_2022": ("2022-01-01", "2022-12-31"),
    "selloff_2018": ("2018-09-01", "2019-01-15"),
    "correction_2015_2016": ("2015-08-01", "2016-02-15"),
}

TRADING_DAYS_PER_MONTH = 21
LOOKBACK_MONTHS = [6, 9, 12, 15, 18]  # H27과 동일 범위(3개월 지점만 제외, 사유는 모듈 docstring)
FREQUENCIES = {"biweekly_10d": 10, "monthly_21d": 21, "sixweek_30d": 30, "quarterly_63d": 63}  # H29와 동일(주간만 제외)

MAX_LOOKBACK_DAYS = max(LOOKBACK_MONTHS) * TRADING_DAYS_PER_MONTH
EXTRA_WARMUP_DAYS = max(WARMUP_DAYS, MAX_LOOKBACK_DAYS + 60)

SCENARIOS = {
    "base": {
        "full_2019_2026": 0.50, "gfc_2008": 0.03, "covid_2020": 0.04,
        "bear_2022": 0.10, "selloff_2018": 0.16, "correction_2015_2016": 0.17,
    },
    "calm_heavy": {
        "full_2019_2026": 0.65, "gfc_2008": 0.015, "covid_2020": 0.02,
        "bear_2022": 0.065, "selloff_2018": 0.12, "correction_2015_2016": 0.13,
    },
    "crisis_heavy": {
        "full_2019_2026": 0.35, "gfc_2008": 0.06, "covid_2020": 0.07,
        "bear_2022": 0.14, "selloff_2018": 0.19, "correction_2015_2016": 0.19,
    },
}

SEQUENTIAL_CHOICE = {"lookback_months": 12, "freq_name": "monthly_21d"}  # 작업40/41이 순차적으로 도달한 기본값


def normalize(weights: dict) -> dict:
    s = sum(weights.values())
    return {k: v / s for k, v in weights.items()}


REBAL_PHASE_ANCHOR = pd.Timestamp("2000-01-03")  # 고정 달력 기준일 - 아래 설명 참고


def n_day_rebal_mask(index: pd.DatetimeIndex, n: int) -> pd.Series:
    """N거래일마다 리밸런싱하되, 위상(phase)을 고정된 달력 기준일(REBAL_PHASE_ANCHOR)로부터의
    영업일수(busday_count)로 결정한다.

    H29(원본)는 "인덱스 0번째 거래일부터 N거래일 간격"으로 마스크를 만들었는데, 이는 인덱스 0번째가
    '어떤 날짜'인지(=fetch_start를 얼마나 여유있게 잡았는지)에 따라 실제 리밸런싱 날짜의 위상이
    임의로 밀린다. H31은 그리드 전체(5개 룩백 x 4개 빈도)에 필요한 최대 warmup이 H27/H29 개별
    스윕보다 커서(18개월 룩백 대응) fetch_start를 더 여유있게 잡아야 했는데, 그 결과 같은 "월간"
    빈도라도 H29가 보고한 수치와 크게 달라지는 것을 발견했다(예: 12개월/월간 조합의 기대샤프가
    H29의 원 수치와 큰 차이). 원인을 실측으로 확인한 결과 순전히 이 위상 아티팩트였다(경제적
    차이가 아님). 이를 없애기 위해 인덱스 위치 대신 고정 기준일로부터의 영업일수 mod n으로
    리밸런싱일을 정의해 fetch_start(warmup)를 얼마로 잡든 같은 파라미터 조합이 같은 실제 리밸런싱
    날짜를 갖도록 만들었다."""
    index_days = index.values.astype("datetime64[D]")
    busdays = np.busday_count(np.datetime64(REBAL_PHASE_ANCHOR.date()), index_days)
    mask = pd.Series((busdays % n) == 0, index=index)
    mask.iloc[0] = True
    return mask


def build_weights_joint(
    closes: pd.DataFrame, market_close: pd.Series, momentum_window_days: int, rebal_days: int,
) -> pd.DataFrame:
    """champion_strategy.build_champion_weights를 momentum_window와 rebal 빈도 둘 다 가변으로 일반화."""
    momentum = closes.pct_change(momentum_window_days)
    is_rebal = n_day_rebal_mask(closes.index, rebal_days)
    sma200 = market_close.rolling(MARKET_FILTER_MA, min_periods=MARKET_FILTER_MA).mean()

    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    last_weights = pd.Series(0.0, index=closes.columns)
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            signal_date = closes.index[i - 1]
            mom = momentum.loc[signal_date]
            candidates = mom[mom > 0].sort_values(ascending=False)
            picks = candidates.index[:TOP_N]
            w = pd.Series(0.0, index=closes.columns)
            if len(picks) > 0:
                w[picks] = 1.0 / TOP_N
            if signal_date in sma200.index and not pd.isna(sma200.loc[signal_date]):
                if market_close.loc[signal_date] < sma200.loc[signal_date]:
                    w = w * MARKET_FILTER_SCALE_BELOW
            last_weights = w
        weights.iloc[i] = last_weights.values
    return weights


def run_champion_joint(start: str, end: str, momentum_window_days: int, rebal_days: int) -> dict:
    tickers = list(CHAMPION_UNIVERSE)
    fetch_start = (pd.Timestamp(start) - pd.DateOffset(days=EXTRA_WARMUP_DAYS * 1.6)).date().isoformat()
    histories = fetch_champion_histories(fetch_start, end, tickers)
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = build_weights_joint(closes, market_close, momentum_window_days, rebal_days)

    sliced_idx = closes.index[(closes.index >= pd.Timestamp(start)) & (closes.index <= pd.Timestamp(end))]
    closes_sliced = closes.loc[sliced_idx]
    weights_sliced = weights_full.loc[sliced_idx]

    result = compute_portfolio_returns(closes_sliced, weights_sliced)
    metrics = calculate_metrics(result["equity_net"], [], sliced_idx[0], sliced_idx[-1])
    avg_annual_turnover = result["turnover"].mean() * 252
    return {"sharpe": metrics["sharpe"], "cagr": metrics["cagr"], "mdd": metrics["mdd"],
            "avg_annual_turnover_pct": round(float(avg_annual_turnover) * 100, 1)}


def main():
    t0 = time.time()
    # lookup[episode][lookback_months][freq_name] = metrics
    lookup: dict = {ep: {} for ep in WINDOWS}
    n_done = 0
    n_total = len(LOOKBACK_MONTHS) * len(FREQUENCIES) * len(WINDOWS)
    for months in LOOKBACK_MONTHS:
        window_days = months * TRADING_DAYS_PER_MONTH
        for freq_name, rebal_days in FREQUENCIES.items():
            for ep, (start, end) in WINDOWS.items():
                m = run_champion_joint(start, end, window_days, rebal_days)
                lookup[ep].setdefault(str(months), {})[freq_name] = m
                n_done += 1
            print(f"[h31] lookback={months}m x {freq_name} done ({n_done}/{n_total}) t={time.time()-t0:.1f}s", flush=True)

    out = {
        "episode_windows": {k: list(v) for k, v in WINDOWS.items()},
        "lookback_months": LOOKBACK_MONTHS,
        "frequencies": FREQUENCIES,
        "sequential_choice": SEQUENTIAL_CHOICE,
        "phase_anchor_note": (
            "N거래일 리밸런싱 마스크의 위상을 고정 달력기준일(2000-01-03)로부터의 영업일수 mod n으로 "
            "고정했다(H29 원본의 '배열 인덱스 0번째부터' 방식은 warmup 크기에 따라 위상이 임의로 밀려 "
            "같은 명목 빈도라도 실제 리밸런싱 날짜가 달라지는 아티팩트가 있음을 실측 중 발견해 수정)."
        ),
        "grid_resolution_note": (
            "H27(6개 룩백값: 3/6/9/12/15/18개월) x H29(5개 빈도: 주간5/격주10/월간21/6주30/분기63)의 "
            "개별 스윕 대비, 결합그리드는 계산량 억제를 위해 룩백에서 3개월(양 시나리오 최하위 확정)을, "
            "빈도에서 주간(회전율/비용 폭발로 최하위 확정)을 제외해 5x4=20그리드점으로 축소했다."
        ),
        "raw_lookup_table": lookup,
        "scenarios": {},
    }

    for scen_name, weights in SCENARIOS.items():
        w = normalize(weights)
        ev_grid = {}  # "months|freq" -> {expected_sharpe, expected_cagr_pct, mdd_worst_case}
        for months in LOOKBACK_MONTHS:
            mk = str(months)
            for freq_name in FREQUENCIES:
                sharpe_ev, cagr_ev = 0.0, 0.0
                for ep, wt in w.items():
                    m = lookup[ep][mk][freq_name]
                    sharpe_ev += wt * m["sharpe"]
                    cagr_ev += wt * m["cagr"]
                crisis_mdds = [lookup[ep][mk][freq_name]["mdd"] for ep in w if ep != "full_2019_2026"]
                key = f"{mk}|{freq_name}"
                ev_grid[key] = {
                    "lookback_months": months, "freq_name": freq_name,
                    "expected_sharpe": round(sharpe_ev, 4),
                    "expected_cagr_pct": round(cagr_ev, 4),
                    "mdd_worst_case": round(min(crisis_mdds), 2),
                }
        ranking = sorted(ev_grid.items(), key=lambda kv: -kv[1]["expected_sharpe"])
        joint_best_key, joint_best_val = ranking[0]
        seq_key = f"{SEQUENTIAL_CHOICE['lookback_months']}|{SEQUENTIAL_CHOICE['freq_name']}"
        seq_val = ev_grid[seq_key]
        seq_rank = [i for i, (k, _) in enumerate(ranking) if k == seq_key][0] + 1
        out["scenarios"][scen_name] = {
            "weights_normalized": w,
            "expected_value_grid": ev_grid,
            "ranking_by_expected_sharpe": ranking,
            "joint_optimum": {"key": joint_best_key, **joint_best_val},
            "sequential_choice_value": {"key": seq_key, **seq_val},
            "sequential_rank_out_of_20": seq_rank,
            "sharpe_gap_joint_minus_sequential": round(joint_best_val["expected_sharpe"] - seq_val["expected_sharpe"], 4),
        }

    (OUT_DIR / "h31_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("[h31] saved h31_results.json")
    for scen_name in SCENARIOS:
        s = out["scenarios"][scen_name]
        print(f"--- {scen_name} ---")
        print(f"  joint optimum: {s['joint_optimum']}")
        print(f"  sequential(12mo,monthly): {s['sequential_choice_value']} rank={s['sequential_rank_out_of_20']}/20")
        print(f"  gap(joint - sequential) expected sharpe: {s['sharpe_gap_joint_minus_sequential']}")


if __name__ == "__main__":
    main()
