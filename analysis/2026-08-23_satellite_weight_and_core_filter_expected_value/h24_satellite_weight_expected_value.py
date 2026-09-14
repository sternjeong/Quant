"""H24 - 새틀라이트 비중(현재 15% 고정) 자체의 기댓값 재검증.

작업31/H5는 point-in-time 새틀라이트 비중을 0~50%로 스윕했지만 2019-2026 전체기간(강세장 편향)
하나에서만 샤프 정점을 봤다(15~20%). 이 스크립트는 H22가 확립한 기저확률 가중 기댓값 방법론을
그대로 재사용해 같은 스윕을 6개 창(전체기간 + 5개 위기표본)에서 반복하고, "기댓값 최적" 비중이
얼마인지, 그 답이 시나리오 가중치(base/calm_heavy/crisis_heavy)에 얼마나 민감한지를 본다.

코어: champion_strategy.run_champion (필터 포함 -- 현재 실제 챔피언 정의 그대로. H24는 필터를
건드리지 않는다, 그건 H25의 몫).
새틀라이트: H18/H22가 "기댓값 승자"로 확정한 정적보유 trend_following 방식(h11의
build_satellite_returns_period, method="trend_following") 그대로 재사용.

원시데이터 재사용 정책(재계산 비용 절감, 방법론은 100% 동일하게 유지):
  - full_2019_2026 / bear_2022: 같은 2019-08-12~2026-08-19 원시 코어/새틀라이트 수익률 시계열을
    공유 -- h16 라운드(2026-08-22)가 저장한 full_core_ret.csv/full_static_sat_ret.csv를 그대로
    재사용(같은 champion_strategy.run_champion 필터=ON 기본값, 같은 h11 trend_following 새틀라이트
    로직으로 만들어졌음을 코드로 확인함).
  - gfc_2008: 새틀라이트 수익률(h12가 저장한 gfc_sat_ret.csv, trend_following)은 재사용하되, 코어
    수익률은 h11/h12/h16의 3자산 근사가 필터를 아예 갖고 있지 않은 별도 구현이라(champion_strategy와
    다름) 새로 champion_strategy.run_champion(tickers=[SPY,TLT,GLD], apply_market_filter=True)로
    다시 계산해 "현재 챔피언과 동일한 필터 정의"를 보장한다(빠름 -- 3자산 가격만 필요).
  - covid_2020 / selloff_2018 / correction_2015_2016: 코어·새틀라이트 둘 다 새로 계산(H18과 완전히
    동일한 방식 -- champion_strategy.run_champion 17자산 + h11 build_satellite_returns_period
    trend_following, 반기 리밸런싱).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-21_satellite_signal_upgrade_and_crisis_test"))

import pandas as pd

from champion_strategy import run_champion, CHAMPION_UNIVERSE
from h1_core_satellite import blend_returns
from h11_crisis_robustness_test import build_satellite_returns_period
from core.backtest_engine import calculate_metrics

OUT_DIR = Path(__file__).resolve().parent
H16_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_satellite_realtime_stop_and_reentry_research"
H12_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch"

THREE_ASSET_UNIVERSE = ["SPY", "TLT", "GLD"]
SATELLITE_WEIGHTS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

# (label, full_start, full_end, crisis_start, crisis_end, universe, share_key)
# share_key: episodes with the same key reuse the same raw core/sat return series (different date slice only)
WINDOWS = [
    ("full_2019_2026", "2019-08-12", "2026-08-19", None, None, CHAMPION_UNIVERSE, "full17"),
    ("bear_2022", "2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31", CHAMPION_UNIVERSE, "full17"),
    ("gfc_2008", "2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30", THREE_ASSET_UNIVERSE, "gfc3"),
    ("covid_2020", "2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30", CHAMPION_UNIVERSE, "covid17"),
    ("selloff_2018", "2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15", CHAMPION_UNIVERSE, "selloff17"),
    ("correction_2015_2016", "2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15", CHAMPION_UNIVERSE, "correction17"),
]


def log(msg):
    print(f"[h24] {msg}", flush=True)


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
    """(core_ret, sat_ret) 반환. 캐시된 CSV가 있으면 재사용, 없으면 새로 계산."""
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

    # covid17 / selloff17 / correction17: 둘 다 새로 계산(단, 이 스크립트 자체가 저장한 로컬 CSV
    # 캐시가 있으면 재사용 -- 새틀라이트 비중 스윕 범위를 넓히려고 재실행할 때 point-in-time 조회를
    # 반복하지 않기 위함).
    core_cache = OUT_DIR / f"_cache_{share_key}_core_ret.csv"
    sat_cache = OUT_DIR / f"_cache_{share_key}_sat_ret.csv"
    if core_cache.exists() and sat_cache.exists():
        log(f"  [{share_key}] 로컬 캐시 CSV 재사용")
        core_ret = pd.read_csv(core_cache, index_col=0, parse_dates=True).iloc[:, 0]
        sat_ret = pd.read_csv(sat_cache, index_col=0, parse_dates=True).iloc[:, 0]
        return core_ret, sat_ret

    log(f"  [{share_key}] 코어+새틀라이트 신규 계산 {fs}~{fe}")
    core = run_champion(fs, fe, tickers=universe, apply_market_filter=True)
    trading_index = core["ret_net"].index
    sat = build_satellite_returns_period(fs, fe, trading_index, exclude=set(universe), method="trend_following")
    log(f"    코어 지표: {core['metrics']}  새틀라이트 지표: {sat['metrics']}")
    core["ret_net"].to_frame("core_ret").to_csv(core_cache)
    sat["ret_net"].to_frame("sat_ret").to_csv(sat_cache)
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
            else:
                blended = blend_returns(core_ret, sat_ret, sw)
            full_m = perf_metrics_slice(blended, fs, fe)
            crisis_m = perf_metrics_slice(blended, cs, ce) if cs else None
            frontier.append({"satellite_weight": sw, "full_period": full_m, "crisis_window": crisis_m})
            if crisis_m:
                log(f"  {label} sw={sw:.2f}: full_sharpe={full_m['sharpe']} crisis_sharpe={crisis_m['sharpe']}")
            else:
                log(f"  {label} sw={sw:.2f}: full_sharpe={full_m['sharpe']}")

        episodes[label] = {
            "full_period": [fs, fe], "crisis_window": [cs, ce] if cs else None,
            "universe_n": len(universe), "frontier": frontier,
        }

    out = {
        "meta": {"generated_from": "h24_satellite_weight_expected_value.py", "satellite_weights": SATELLITE_WEIGHTS,
                  "elapsed_s": round(time.time() - t0, 1)},
        "episodes": episodes,
    }
    (OUT_DIR / "h24_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"저장 완료: h24_results.json (총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
