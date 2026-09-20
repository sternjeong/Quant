"""H1 - 6개 역사적 구간의 코어+새틀라이트(무헤지) 일별 수익률을 캐시한다.

목적: 이번 라운드(칼라 옵션 헤지의 모네니스/테너 파라미터 민감도)는 코어/새틀라이트 계산 자체를
바꾸지 않는다 — core.champion_strategy.run_champion_backtest()를 6개 구간에 대해 "한 번만" 실행해
core_ret/satellite_ret/unhedged_blend(15% 새틀라이트 정적편입, 무헤지) 일별수익률을 CSV로 저장해두면,
이후 모네니스×테너 그리드(칼라 오버레이는 SPY/VIX 종가 + Black-Scholes 폐형식이라 계산이 훨씬 가볍다)
스윕에서 매번 비싼 새틀라이트 point-in-time 스캔을 반복하지 않아도 된다.

구간 정의(작업44 H33/h33_block_bootstrap_sample_error.py 그대로 재사용 — 새로 만들지 않음):
  gfc_2008, correction_2015_2016, selloff_2018, bear_2022, covid_2020, full_2019_2026
  (bear_2022와 full_2019_2026은 동일한 전체기간(2019-08-12~2026-08-19)을 공유하므로 한 번만 계산)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/quant")

import pandas as pd

from core.champion_strategy import run_champion_backtest, SATELLITE_WEIGHT

OUT_DIR = Path(__file__).resolve().parent

# episode -> (full_start, full_end, crisis_start, crisis_end) — h33/h23와 동일
EPISODES = {
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
    "full_2019_2026": ("2019-08-12", "2026-08-19", "2019-08-12", "2026-08-19"),
}
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]

# bear_2022/full_2019_2026은 같은 전체기간을 쓰므로 계산을 한 번만 하고 공유
FULL_WINDOW_GROUPS = {
    "gfc_2008": "gfc_2008",
    "correction_2015_2016": "correction_2015_2016",
    "selloff_2018": "selloff_2018",
    "covid_2020": "covid_2020",
    "bear_2022": "full_2019_2026_shared",
    "full_2019_2026": "full_2019_2026_shared",
}


def log(msg):
    print(f"[h1] {msg}", flush=True)


def main():
    computed: dict[str, dict] = {}
    meta = {}
    t_start = time.time()

    for group_key in sorted(set(FULL_WINDOW_GROUPS.values())):
        # 이 그룹에 속한 아무 episode에서나 전체기간을 가져온다 (같은 그룹이면 전체기간이 동일)
        rep_label = next(lbl for lbl, g in FULL_WINDOW_GROUPS.items() if g == group_key)
        full_start, full_end, _, _ = EPISODES[rep_label]
        log(f"그룹 {group_key} ({rep_label} 대표) 챔피언 백테스트 실행: {full_start} ~ {full_end}")
        t0 = time.time()
        result = run_champion_backtest(full_start, full_end, satellite_weight=SATELLITE_WEIGHT)
        elapsed = time.time() - t0
        log(f"  완료 ({elapsed:.1f}s), n_days={len(result['ret_net'])}, "
            f"satellite_weight_applied={result['satellite_weight_applied']}")

        core_ret = result["core"]["ret_net"]
        sat_ret = result["satellite"]["ret_net"]
        unhedged_blend = result["ret_net"]

        computed[group_key] = {
            "core_ret": core_ret, "sat_ret": sat_ret, "unhedged_blend": unhedged_blend,
        }
        meta[group_key] = {
            "full_start": full_start, "full_end": full_end,
            "elapsed_sec": round(elapsed, 1),
            "n_days": int(len(unhedged_blend)),
            "satellite_weight_applied": result["satellite_weight_applied"],
            "core_metrics": result["core"]["metrics"] if "metrics" in result["core"] else None,
            "satellite_tickers_ever_held": result["satellite"].get("tickers_ever_held", []),
        }

        # CSV로 저장 (재사용/투명성)
        core_ret.to_csv(OUT_DIR / f"{group_key}_core_ret.csv", header=["ret"])
        sat_ret.to_csv(OUT_DIR / f"{group_key}_sat_ret.csv", header=["ret"])
        unhedged_blend.to_csv(OUT_DIR / f"{group_key}_unhedged_blend_ret.csv", header=["ret"])

    total_elapsed = time.time() - t_start
    log(f"전체 완료 ({total_elapsed:.1f}s)")

    meta_out = {
        "episodes": EPISODES, "episode_order": EPISODE_ORDER,
        "full_window_groups": FULL_WINDOW_GROUPS,
        "group_computation_meta": meta,
        "satellite_weight": SATELLITE_WEIGHT,
        "total_elapsed_sec": round(total_elapsed, 1),
    }
    (OUT_DIR / "h1_meta.json").write_text(json.dumps(meta_out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log("저장 완료: h1_meta.json + *_core_ret.csv / *_sat_ret.csv / *_unhedged_blend_ret.csv")


if __name__ == "__main__":
    main()
