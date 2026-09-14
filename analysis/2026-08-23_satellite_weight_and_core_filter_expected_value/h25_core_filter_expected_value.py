"""H25 - 챔피언 코어 자체의 이진 시장필터(SPY<200SMA -> 50% 축소)도 기댓값에서 지는가.

작업39(H22)가 새틀라이트 레벨 스위치(SPY스위치/VIX스위치/하이브리드)를 기저확률 가중 기댓값으로
평가해 전부 정적보유(무스위치)에 진다는 걸 보였다. 이 스크립트는 정확히 같은 렌즈를, 그 스위치들이
아니라 챔피언 17자산 코어 자체의 "존재 이유가 다른" 필터 -- 개별 새틀라이트 슬리브가 아니라 포트폴리오
전체에 적용되는 이진 시장필터 -- 에 적용한다.

비교 대상 (동일 유니버스·동일 랭킹·동일 리밸런싱, 필터 유무만 다름):
  (a) with_filter    : champion_strategy.run_champion(..., apply_market_filter=True)  (현재 챔피언)
  (b) without_filter  : champion_strategy.run_champion(..., apply_market_filter=False) (필터만 제거, 나머지 동일)

6개 창(H22와 동일 아키타입 매핑, H18/H16이 확립한 정확히 같은 날짜/유니버스 관례 재사용):
  full_2019_2026(2019-08-12~2026-08-19, 17자산) / bear_2022(같은 원시데이터, 2022-01-01~2022-12-31 슬라이스)
  gfc_2008(2007-01-01~2009-12-31, SPY/TLT/GLD 3자산 근사 -- 2008년 당시 HYG/DBC/XLC/XLRE 등 다수
    미상장이라 작업22/23/H11이 확립한 관례) / crisis 2007-10-01~2009-06-30
  covid_2020(2019-01-01~2020-12-31, 17자산) / crisis 2020-02-19~2020-04-30
  selloff_2018(2017-06-01~2019-06-30, 17자산 중 XLC/XLRE 제외 15자산 -- 모멘텀 계산에서 미상장 자산은
    NaN이 되어 후보에서 자동 제외되므로 champion_strategy.CHAMPION_UNIVERSE 그대로 넘겨도 무방)
    / crisis 2018-09-01~2019-01-15
  correction_2015_2016(2014-06-01~2016-06-30, 17자산 중 XLC 제외) / crisis 2015-08-01~2016-02-15

각 창에서 "전체기간"과 "위기 서브윈도우" 둘 다 지표를 내고, H22의 기저확률 시나리오(base/calm_heavy/
crisis_heavy)로 기댓값화한다(전체기간 창은 full_2019_2026 아키타입에, 나머지는 각자의 위기
서브윈도우로 그 아키타입에 매핑 -- H22와 동일 관례).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

MAIN_CHECKOUT = "/workspaces/Quant"  # core/ 및 캐시된 가격 데이터는 항상 main의 최신 버전을 사용
sys.path.insert(0, MAIN_CHECKOUT)
sys.path.insert(0, str(Path(MAIN_CHECKOUT) / "analysis" / "2026-08-19_champion_beta_and_satellite_research"))

import pandas as pd

from champion_strategy import run_champion, CHAMPION_UNIVERSE
from core.backtest_engine import calculate_metrics

OUT_DIR = Path(__file__).resolve().parent

THREE_ASSET_UNIVERSE = ["SPY", "TLT", "GLD"]

# (label, full_start, full_end, crisis_start, crisis_end, universe)
WINDOWS = {
    "full_2019_2026": ("2019-08-12", "2026-08-19", None, None, CHAMPION_UNIVERSE),
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30", THREE_ASSET_UNIVERSE),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30", CHAMPION_UNIVERSE),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31", CHAMPION_UNIVERSE),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15", CHAMPION_UNIVERSE),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15", CHAMPION_UNIVERSE),
}


def log(msg):
    print(f"[h25] {msg}", flush=True)


def perf_metrics_slice(ret: pd.Series, start: str, end: str) -> dict:
    sliced = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if len(sliced) < 2:
        return {"cagr": None, "mdd": None, "sharpe": None, "calmar": None, "n_days": len(sliced)}
    eq = (1 + sliced.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    m = calculate_metrics(eq, [], eq.index[0], eq.index[-1])
    m["n_days"] = int(len(sliced))
    return m


def main():
    t0 = time.time()
    results = {}
    # full_2019_2026과 bear_2022는 원시데이터(17자산 가격이력)가 같으므로 한 번만 계산해서 공유
    shared_full = {}

    for label, (fs, fe, cs, ce, universe) in WINDOWS.items():
        cache_key = (tuple(universe), fs, fe)
        if cache_key in shared_full:
            log(f"{label}: 원시데이터 재사용({fs}~{fe}, {len(universe)}자산)")
            with_f, without_f = shared_full[cache_key]
        else:
            log(f"{label}: 코어 실행 {fs}~{fe} ({len(universe)}자산, 필터 ON/OFF 각 1회)")
            with_f = run_champion(fs, fe, tickers=universe, apply_market_filter=True)
            without_f = run_champion(fs, fe, tickers=universe, apply_market_filter=False)
            shared_full[cache_key] = (with_f, without_f)
            log(f"  filter=ON  전체지표: {with_f['metrics']}")
            log(f"  filter=OFF 전체지표: {without_f['metrics']}")

        full_period = {
            "with_filter": perf_metrics_slice(with_f["ret_net"], fs, fe),
            "without_filter": perf_metrics_slice(without_f["ret_net"], fs, fe),
        }
        crisis_window = None
        if cs and ce:
            crisis_window = {
                "with_filter": perf_metrics_slice(with_f["ret_net"], cs, ce),
                "without_filter": perf_metrics_slice(without_f["ret_net"], cs, ce),
            }
            log(f"  crisis({cs}~{ce}) with_filter sharpe={crisis_window['with_filter']['sharpe']} "
                f"without_filter sharpe={crisis_window['without_filter']['sharpe']}")

        results[label] = {
            "full_period": [fs, fe], "crisis_window": [cs, ce] if cs else None,
            "universe_n": len(universe), "universe": universe,
            "metrics": {"full_period": full_period, "crisis_window": crisis_window},
        }

    out = {
        "meta": {"generated_from": "h25_core_filter_expected_value.py", "elapsed_s": round(time.time() - t0, 1)},
        "episodes": results,
    }
    (OUT_DIR / "h25_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log(f"저장 완료: h25_results.json (총 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
