"""H36 - H24 새틀라이트 비중 스윕(0~50%)을 60/70/80/90/100%까지 확장.

H24(analysis/2026-08-23_satellite_weight_and_core_filter_expected_value/
h24_satellite_weight_expected_value.py)는 0~50% 범위에서 기댓값 샤프가 스윕 상한까지 단조증가하는
것을 발견했다(즉 진짜 정점을 찾지 못함). 이 스크립트는 정확히 같은 코어(필터 포함 -- H35가 다루는
필터 문제와는 독립)+새틀라이트(trend_following, H18/H22가 확정한 정적보유 방식) 구성과 동일한 6개
창, 동일한 기저확률가중(H22 SCENARIOS)을 재사용하되 비중 리스트만 0.6/0.7/0.8/0.9/1.0으로 확장한다.

원시 코어/새틀라이트 수익률 재사용 정책은 H24와 완전히 동일(같은 share_key 캐싱 방식) -- 비중만
확장하므로 원시 시계열은 전혀 새로 계산할 필요가 없다(H24가 저장한 캐시 CSV를 그대로 재사용).
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
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-21_satellite_signal_upgrade_and_crisis_test"))

import pandas as pd

from champion_strategy import run_champion, CHAMPION_UNIVERSE  # noqa: E402
from h1_core_satellite import blend_returns  # noqa: E402
from h11_crisis_robustness_test import build_satellite_returns_period  # noqa: E402
from core.backtest_engine import calculate_metrics  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
H24_DIR = WORKTREE_ROOT / "analysis/2026-08-23_satellite_weight_and_core_filter_expected_value"
H16_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_satellite_realtime_stop_and_reentry_research"
H12_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch"

THREE_ASSET_UNIVERSE = ["SPY", "TLT", "GLD"]
# H24의 0~50% 그대로 + 확장분 60~100%
SATELLITE_WEIGHTS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]

WINDOWS = [
    ("full_2019_2026", "2019-08-12", "2026-08-19", None, None, CHAMPION_UNIVERSE, "full17"),
    ("bear_2022", "2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31", CHAMPION_UNIVERSE, "full17"),
    ("gfc_2008", "2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30", THREE_ASSET_UNIVERSE, "gfc3"),
    ("covid_2020", "2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30", CHAMPION_UNIVERSE, "covid17"),
    ("selloff_2018", "2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15", CHAMPION_UNIVERSE, "selloff17"),
    ("correction_2015_2016", "2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15", CHAMPION_UNIVERSE, "correction17"),
]


def log(msg):
    print(f"[h36] {msg}", flush=True)


def perf_metrics_slice(ret: pd.Series, start: str, end: str) -> dict:
    sliced = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if len(sliced) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "calmar": None, "n_days": len(sliced)}
    eq = (1 + sliced.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
    m["n_days"] = int(len(sliced))
    return m


def get_raw_series(share_key: str, fs: str, fe: str, universe: list) -> tuple:
    """H24와 완전히 동일한 캐시/계산 전략. H24가 만든 캐시(H24_DIR)를 최우선으로 재사용."""
    if share_key == "full17":
        core_ret = pd.read_csv(H16_DIR / "full_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        sat_ret = pd.read_csv(H16_DIR / "full_static_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        log(f"  [{share_key}] h16 캐시 CSV 재사용 (n={len(core_ret)})")
        return core_ret, sat_ret

    if share_key == "gfc3":
        log(f"  [{share_key}] 코어 재계산(champion_strategy, 3자산, 필터=ON), 새틀라이트는 h12 캐시 재사용")
        core = run_champion(fs, fe, tickers=THREE_ASSET_UNIVERSE, apply_market_filter=True)
        sat_ret = pd.read_csv(H12_DIR / "gfc_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
        return core["ret_net"], sat_ret

    h24_core_cache = H24_DIR / f"_cache_{share_key}_core_ret.csv"
    h24_sat_cache = H24_DIR / f"_cache_{share_key}_sat_ret.csv"
    if h24_core_cache.exists() and h24_sat_cache.exists():
        log(f"  [{share_key}] H24 캐시 CSV 재사용")
        core_ret = pd.read_csv(h24_core_cache, index_col=0, parse_dates=True).iloc[:, 0]
        sat_ret = pd.read_csv(h24_sat_cache, index_col=0, parse_dates=True).iloc[:, 0]
        return core_ret, sat_ret

    log(f"  [{share_key}] 코어+새틀라이트 신규 계산 {fs}~{fe}")
    core = run_champion(fs, fe, tickers=universe, apply_market_filter=True)
    trading_index = core["ret_net"].index
    sat = build_satellite_returns_period(fs, fe, trading_index, exclude=set(universe), method="trend_following")
    core["ret_net"].to_frame("core_ret").to_csv(OUT_DIR / f"_cache_{share_key}_core_ret.csv")
    sat["ret_net"].to_frame("sat_ret").to_csv(OUT_DIR / f"_cache_{share_key}_sat_ret.csv")
    return core["ret_net"], sat["ret_net"]


def main():
    t0 = time.time()
    cache = {}
    episodes = {}

    for label, fs, fe, cs, ce, universe, share_key in WINDOWS:
        if share_key not in cache:
            cache[share_key] = get_raw_series(share_key, fs, fe, universe)
        core_ret, sat_ret = cache[share_key]

        frontier = []
        for sw in SATELLITE_WEIGHTS:
            if sw == 0.0:
                blended = core_ret
            elif sw == 1.0:
                blended = sat_ret
            else:
                blended = blend_returns(core_ret, sat_ret, sw)
            full_m = perf_metrics_slice(blended, fs, fe)
            crisis_m = perf_metrics_slice(blended, cs, ce) if cs else None
            frontier.append({"satellite_weight": sw, "full_period": full_m, "crisis_window": crisis_m})
            if crisis_m:
                log(f"  {label} sw={sw:.2f}: full_sharpe={full_m['sharpe']} crisis_sharpe={crisis_m['sharpe']} crisis_mdd={crisis_m['mdd']}")
            else:
                log(f"  {label} sw={sw:.2f}: full_sharpe={full_m['sharpe']}")

        episodes[label] = {
            "full_period": [fs, fe], "crisis_window": [cs, ce] if cs else None,
            "universe_n": len(universe), "frontier": frontier,
        }

    out = {
        "meta": {"generated_from": "h36_satellite_weight_extended_sweep.py", "satellite_weights": SATELLITE_WEIGHTS,
                  "elapsed_s": round(time.time() - t0, 1)},
        "episodes": episodes,
    }
    (OUT_DIR / "h36_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"저장 완료: h36_results.json (총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
