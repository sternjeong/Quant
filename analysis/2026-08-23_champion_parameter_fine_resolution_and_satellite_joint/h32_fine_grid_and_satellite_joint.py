"""H32 - H31(16라운드) 결합 그리드 우승점 (15개월, 분기)의 정밀 재검증 + 새틀라이트 비중까지 3차원.

배경(작업43/H31): 룩백(5값: 6/9/12/15/18개월) x 리밸런싱(4값: 격주/월간/6주/분기) = 20칸 조(粗)그리드에서
결합 최적점이 (15개월, 분기)로 나왔고, 순차 최적화 기본값(12개월, 월간)은 20개 중 5~6위였다. 하지만
H31 스스로 "그리드 해상도가 거칠다"와 "새틀라이트 비중까지 결합하면 최적점이 바뀔 수 있다"는 두 가지를
다음 라운드 과제로 명시했다. 이 스크립트는 그 두 과제를 순서대로 닫는다.

Stage 1 — 정밀 2D 그리드:
  룩백: 9~18개월(1개월 간격, 10값) — H31이 "9~15개월 구간이 완만한 고원"이라 보고했으므로 그 고원
    전체를 촘촘히 덮고, 우승점(15) 주변으로 18개월까지 여유를 둔다. (H31의 6개월 지점은 양 극단에서
    항상 최하위권이었으므로 정밀 재검증 우선순위가 낮다고 판단해 제외 — 계산량 억제.)
  리밸런싱: 월간(21일)/6주(30일)/2개월(42일)/분기(63일) 4값 — H31의 격주(10일)는 4개 조합 모두에서
    분기·6주 대비 뚜렷하게 낮은 기대샤프였으므로 제외하고, 대신 우승 구간인 6주~분기 사이를 촘촘히
    메우는 2개월(42일) 지점을 새로 추가했다. H31의 4값 중 3개(월간/6주/분기)는 그대로 유지해 직접
    비교 가능.
  → 10 x 4 = 40 그리드점 x 6개 창 = 240회 백테스트. H31의 5x4=20 대비 각 축 해상도를 약 2배로
    올렸다(룩백 3개월 간격 -> 1개월 간격, 리밸런싱 4값 유지하되 우승권에 재배치).
  H31의 계산-비용 교훈을 따라, H31이 이미 검증한 "고정 달력기준일 리밸런싱 마스크"를 그대로 재사용한다
  (버그 수정판 그대로, 재발명하지 않음).

Stage 2 — 새틀라이트 비중 결합(3번째 차원):
  Stage 1의 정밀 최적점(lookback*, freq*)과 순차 기본값(12개월, 월간)을 각각 코어로 삼아, H5와 동일한
  point-in-time 새틀라이트(반기 리밸런싱, 12개월 모멘텀 상위 3종목)를 0/10/15/20/25/30% 비중으로
  블렌드한다. point-in-time 유니버스 표본추출이 창마다 실제 네트워크/캐시 조회를 요구해 비용이 커서
  (H5도 동일한 이유로 전체기간 단일창만 썼다), Stage 2는 전체기간(2019-08-12~2026-08-19) 단일창에서만
  수행한다 - 6창 기댓값 가중은 Stage 1에서만 적용하고 Stage 2는 H5 방법론을 그대로 따른다(명시적
  간소화, 04절 한계에 서술).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"  # 항상 최신 core/ 참조 (이 워크트리 core/는 이 라운드 목적상 그대로 두되, 안전하게 main도 함께 sys.path에 꽂는다)
WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))
sys.path.insert(0, MAIN_CHECKOUT)
CHAMPION_DIR = str(WORKTREE_ROOT / "analysis" / "2026-08-19_champion_beta_and_satellite_research")
sys.path.insert(0, CHAMPION_DIR)

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics
from champion_strategy import (  # noqa: E402
    CHAMPION_UNIVERSE, MARKET_FILTER_TICKER, MARKET_FILTER_MA, MARKET_FILTER_SCALE_BELOW,
    TOP_N, WARMUP_DAYS, fetch_champion_histories, _closes_from_histories, compute_portfolio_returns,
    run_champion,
)
from h1_core_satellite import build_satellite_returns, blend_returns  # noqa: E402

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
LOOKBACK_MONTHS = [9, 10, 11, 12, 13, 14, 15, 16, 17, 18]
FREQUENCIES = {"monthly_21d": 21, "sixweek_30d": 30, "twomonth_42d": 42, "quarterly_63d": 63}

MAX_LOOKBACK_DAYS = max(LOOKBACK_MONTHS) * TRADING_DAYS_PER_MONTH
EXTRA_WARMUP_DAYS = max(WARMUP_DAYS, MAX_LOOKBACK_DAYS + 60)

# H22와 완전히 동일한 기저확률 시나리오 가중치 (h31_joint_parameter_grid.py에서 그대로 이식)
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

SEQUENTIAL_CHOICE = {"lookback_months": 12, "freq_name": "monthly_21d"}
H31_COARSE_WINNER = {"lookback_months": 15, "freq_name": "quarterly_63d"}
SATELLITE_WEIGHTS = [0.0, 0.10, 0.15, 0.20, 0.25, 0.30]

REBAL_PHASE_ANCHOR = pd.Timestamp("2000-01-03")  # H31이 실측으로 발견/수정한 고정 달력기준일 위상 - 그대로 재사용


def normalize(weights: dict) -> dict:
    s = sum(weights.values())
    return {k: v / s for k, v in weights.items()}


def n_day_rebal_mask(index: pd.DatetimeIndex, n: int) -> pd.Series:
    """H31의 버그 수정판 그대로: 고정 달력기준일로부터 영업일수 mod n. (인덱스 위치 기준 마스크는
    warmup 크기에 따라 위상이 밀리는 아티팩트가 있음을 H31이 실측으로 확인했으므로 재사용하지 않는다.)"""
    index_days = index.values.astype("datetime64[D]")
    busdays = np.busday_count(np.datetime64(REBAL_PHASE_ANCHOR.date()), index_days)
    mask = pd.Series((busdays % n) == 0, index=index)
    mask.iloc[0] = True
    return mask


def build_weights_joint(closes, market_close, momentum_window_days, rebal_days):
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


def run_champion_joint(start, end, momentum_window_days, rebal_days, return_weights_idx=None):
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
    out = {"sharpe": metrics["sharpe"], "cagr": metrics["cagr"], "mdd": metrics["mdd"],
           "avg_annual_turnover_pct": round(float(avg_annual_turnover) * 100, 1)}
    if return_weights_idx is not None:
        return out, result
    return out


def stage1_fine_grid():
    t0 = time.time()
    lookup = {ep: {} for ep in WINDOWS}
    n_done = 0
    n_total = len(LOOKBACK_MONTHS) * len(FREQUENCIES) * len(WINDOWS)
    for months in LOOKBACK_MONTHS:
        window_days = months * TRADING_DAYS_PER_MONTH
        for freq_name, rebal_days in FREQUENCIES.items():
            for ep, (start, end) in WINDOWS.items():
                m = run_champion_joint(start, end, window_days, rebal_days)
                lookup[ep].setdefault(str(months), {})[freq_name] = m
                n_done += 1
            print(f"[h32-s1] lookback={months}m x {freq_name} done ({n_done}/{n_total}) t={time.time()-t0:.1f}s", flush=True)

    out = {
        "episode_windows": {k: list(v) for k, v in WINDOWS.items()},
        "lookback_months": LOOKBACK_MONTHS,
        "frequencies": FREQUENCIES,
        "sequential_choice": SEQUENTIAL_CHOICE,
        "h31_coarse_winner": H31_COARSE_WINNER,
        "raw_lookup_table": lookup,
        "scenarios": {},
    }

    for scen_name, weights in SCENARIOS.items():
        w = normalize(weights)
        ev_grid = {}
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
        h31_key = f"{H31_COARSE_WINNER['lookback_months']}|{H31_COARSE_WINNER['freq_name']}"
        h31_val = ev_grid[h31_key]
        h31_rank = [i for i, (k, _) in enumerate(ranking) if k == h31_key][0] + 1
        out["scenarios"][scen_name] = {
            "weights_normalized": w,
            "expected_value_grid": ev_grid,
            "ranking_by_expected_sharpe": ranking,
            "fine_grid_optimum": {"key": joint_best_key, **joint_best_val},
            "sequential_choice_value": {"key": seq_key, **seq_val},
            "sequential_rank_out_of_40": seq_rank,
            "h31_coarse_winner_value": {"key": h31_key, **h31_val},
            "h31_coarse_winner_rank_out_of_40": h31_rank,
            "sharpe_gap_fine_minus_sequential": round(joint_best_val["expected_sharpe"] - seq_val["expected_sharpe"], 4),
            "sharpe_gap_fine_minus_h31coarse": round(joint_best_val["expected_sharpe"] - h31_val["expected_sharpe"], 4),
        }

    return out


def stage2_satellite_joint(refined_optimum: dict):
    START, END = "2019-08-12", "2026-08-19"
    print(f"[h32-s2] 새틀라이트 결합 (전체기간 단일창 {START}~{END}, H5 방법론 그대로 재사용)", flush=True)

    core_seq = run_champion(START, END)  # 순차 기본값(12개월/월간) - champion_strategy 기본 파라미터와 동일
    print(f"[h32-s2] 순차 기본값 코어(12mo/monthly) 지표: {core_seq['metrics']}", flush=True)

    refined_months = refined_optimum["lookback_months"]
    refined_freq_name = refined_optimum["freq_name"]
    refined_days = FREQUENCIES[refined_freq_name]
    refined_metrics, core_refined_result = run_champion_joint(
        START, END, refined_months * TRADING_DAYS_PER_MONTH, refined_days, return_weights_idx=True,
    )
    print(f"[h32-s2] 정밀그리드 최적 코어({refined_months}mo/{refined_freq_name}) 지표: {refined_metrics}", flush=True)

    trading_index = core_seq["ret_net"].index
    sat = build_satellite_returns(START, END, trading_index)
    print(f"[h32-s2] 새틀라이트 단독 지표: {sat['metrics']}", flush=True)

    def frontier_for(core_ret, core_metrics_dict, label):
        frontier = []
        for sw in SATELLITE_WEIGHTS:
            if sw == 0.0:
                m = core_metrics_dict
            else:
                br = blend_returns(core_ret, sat["ret_net"], sw)
                eq = (1 + br).cumprod() * 100.0
                eq.iloc[0] = 100.0
                m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
            frontier.append({"satellite_weight": sw, "metrics": m})
            print(f"  [{label}] sw={sw:.2f}: sharpe={m['sharpe']:.3f} cagr={m['cagr']:.2f}% mdd={m['mdd']:.2f}%", flush=True)
        sharpes = [f["metrics"]["sharpe"] for f in frontier]
        peak_idx = int(np.argmax(sharpes))
        return {"frontier": frontier, "peak_sharpe_weight": frontier[peak_idx]["satellite_weight"],
                "peak_sharpe_metrics": frontier[peak_idx]["metrics"]}

    seq_frontier = frontier_for(core_seq["ret_net"], core_seq["metrics"], "sequential(12mo/monthly)")
    refined_frontier = frontier_for(core_refined_result["ret_net"], refined_metrics,
                                     f"refined({refined_months}mo/{refined_freq_name})")

    return {
        "period": {"start": START, "end": END},
        "methodology_note": (
            "H5(2026-08-20)와 동일한 point-in-time 새틀라이트 구축 로직(반기 리밸런싱, 12개월 모멘텀 "
            "상위 3종목)을 그대로 재사용. point-in-time 유니버스 표본추출 비용 때문에 전체기간 단일창만 "
            "사용(H5와 동일한 절충) - Stage 1의 6창 기댓값 가중은 여기 적용되지 않는다."
        ),
        "core_sequential_metrics": core_seq["metrics"],
        "core_refined_metrics": refined_metrics,
        "refined_optimum_used": {"lookback_months": refined_months, "freq_name": refined_freq_name},
        "satellite_standalone_metrics": sat["metrics"],
        "satellite_tickers_ever_held": sat["tickers_ever_held"],
        "sequential_core_frontier": seq_frontier,
        "refined_core_frontier": refined_frontier,
    }


def main():
    t0 = time.time()
    print("[h32] === Stage 1: 정밀 2D 그리드 ===", flush=True)
    stage1 = stage1_fine_grid()
    (OUT_DIR / "h32_stage1_results.json").write_text(json.dumps(stage1, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[h32] Stage 1 저장 완료 t={time.time()-t0:.1f}s", flush=True)

    # base 시나리오의 fine_grid_optimum을 정밀 최적점으로 채택 (3개 시나리오 모두 동일한지 확인 로그로 출력)
    base_opt = stage1["scenarios"]["base"]["fine_grid_optimum"]
    for scen in SCENARIOS:
        opt = stage1["scenarios"][scen]["fine_grid_optimum"]
        print(f"[h32] scenario={scen} fine_grid_optimum={opt['key']} sharpe={opt['expected_sharpe']}", flush=True)
    refined_optimum = {"lookback_months": base_opt["lookback_months"], "freq_name": base_opt["freq_name"]}
    print(f"[h32] Stage 2에 사용할 정밀 최적점(base 시나리오 기준): {refined_optimum}", flush=True)

    print("[h32] === Stage 2: 새틀라이트 비중 결합 ===", flush=True)
    stage2 = stage2_satellite_joint(refined_optimum)
    (OUT_DIR / "h32_stage2_results.json").write_text(json.dumps(stage2, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[h32] Stage 2 저장 완료 t={time.time()-t0:.1f}s", flush=True)

    combined = {"stage1": stage1, "stage2": stage2, "refined_optimum_used_for_stage2": refined_optimum,
                "total_runtime_sec": round(time.time() - t0, 1)}
    (OUT_DIR / "report_data.json").write_text(json.dumps(combined, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[h32] 전체 완료, report_data.json 저장. 총 소요 {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
