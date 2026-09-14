"""H33 - 블록부트스트랩으로 표본오차(sampling uncertainty) 정량화.

H30(작업42)은 명시적으로 "여전히 6개 창뿐이다... 몬테카를로는 '이 6개 숫자를 어떻게 가중하느냐'의
불확실성만 다루지, '이 6개 숫자 자체가 얼마나 정확한가'의 불확실성(백테스트 표본오차)은 다루지
않는다"는 한계를 남겼다. 이번 라운드는 그 갭을 닫는다: H22의 핵심 비교(core_alone vs
case_a_static_satellite)에 쓰인 6개 창의 실제 일별수익률 시계열을 복원하고, 블록부트스트랩으로
각 창의 샤프비율 표본분포(신뢰구간)를 만든 뒤, H30의 디리클레 가중치 불확실성과 교차시켜
"가중치 불확실성 vs 표본오차, 뭐가 더 지배적인가"를 직접 비교한다.

데이터 출처(재계산 최소화, 기존 저장분 재사용):
  - gfc_2008 crisis_window: H12(2026-08-22_regime_conditional_satellite_switch)가 저장한
    gfc_core_ret.csv / gfc_sat_ret.csv
  - bear_2022 crisis_window, full_2019_2026 full_period: H16(satellite_realtime_stop_and_reentry)이
    저장한 full_core_ret.csv / full_static_sat_ret.csv (2019-08-12~2026-08-19 전체, crisis_window로
    슬라이스)
  - correction_2015_2016 / selloff_2018 / covid_2020: 저장된 CSV가 없으므로 h20과 동일한 방식으로
    champion_strategy.run_champion + h11의 build_satellite_returns_period를 새로 실행해 복원
    (h20_vix_fast_signal.run_new_episode와 동일한 절차, VIX 신호 계산은 생략 - 이번 라운드에
    필요없음)

블록부트스트랩 설계:
  일별수익률은 자기상관/변동성 군집(GARCH효과)이 있어 i.i.d. 리샘플은 불확실성을 과소평가한다.
  이동블록부트스트랩(moving block bootstrap, 순환식 wrap-around)을 사용: 블록길이 L일짜리 조각을
  치환추출로 이어붙여 원래 길이와 같은 합성 수익률 시계열을 만들고, 그 샤프비율을 기록한다.
  L=20일(약 1개월, 일별 금융수익률에 흔히 쓰이는 관례적 선택 - 월간 변동성 군집 스케일과 대략
  맞음)을 중심값으로 채택하고, L=10/40도 함께 돌려 결론이 블록길이 선택 자체에 얼마나 민감한지
  로버스트니스로 보고한다(H30이 K=15/30/60 세 값으로 K민감도를 보고한 것과 동일한 정신).
  각 (창, 구성, 블록길이) 조합마다 2000회 리샘플.

한계: COVID 위기창은 약 5주(~35거래일)뿐이라 L=40 블록길이에서는 사실상 원 시계열 전체를 통째로
쓰는 것과 큰 차이가 없어(비독립 블록이 1~2개뿐) 부트스트랩 분산이 인위적으로 좁아질 수 있다 -
이런 초단기 창은 신뢰구간을 액면 그대로 믿지 말라고 본문에서 명시적으로 경고한다.
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

import numpy as np
import pandas as pd

from champion_strategy import run_champion, CHAMPION_UNIVERSE
from h1_core_satellite import blend_returns
from h11_crisis_robustness_test import build_satellite_returns_period

OUT_DIR = Path(__file__).resolve().parent
H12_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_regime_conditional_satellite_switch"
H16_DIR = Path(MAIN_CHECKOUT) / "analysis/2026-08-22_satellite_realtime_stop_and_reentry_research"

SATELLITE_WEIGHT = 0.15
TRADING_DAYS = 252

# episode label -> (full_start, full_end, crisis_start, crisis_end)
EPISODES = {
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
    "full_2019_2026": ("2019-08-12", "2026-08-19", "2019-08-12", "2026-08-19"),  # window == crisis == full
}
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
BLOCK_LENGTHS = [10, 20, 40]
N_BOOT = 2000
SEED = 20260823


def log(msg):
    print(f"[h33] {msg}", flush=True)


def slice_window(s: pd.Series, start: str, end: str) -> pd.Series:
    return s[(s.index >= start) & (s.index <= end)]


def load_gfc() -> tuple[pd.Series, pd.Series]:
    core_ret = pd.read_csv(H12_DIR / "gfc_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_ret = pd.read_csv(H12_DIR / "gfc_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    return core_ret, sat_ret


def load_bear2022_and_full() -> tuple[pd.Series, pd.Series]:
    core_ret = pd.read_csv(H16_DIR / "full_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    sat_ret = pd.read_csv(H16_DIR / "full_static_sat_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    return core_ret, sat_ret


def build_fresh(label: str) -> tuple[pd.Series, pd.Series]:
    full_start, full_end, _, _ = EPISODES[label]
    log(f"  {label}: 신규 코어+새틀라이트 백테스트 {full_start}~{full_end}")
    core = run_champion(full_start, full_end)
    trading_index = core["ret_net"].index
    sat = build_satellite_returns_period(full_start, full_end, trading_index, exclude=set(CHAMPION_UNIVERSE), method="trend_following")
    return core["ret_net"], sat["ret_net"]


def gather_window_returns() -> dict:
    """episode -> {'core_alone': ret_series(window-sliced), 'case_a_static_satellite': ret_series}"""
    out = {}
    t0 = time.time()

    core_gfc, sat_gfc = load_gfc()
    core_bear, sat_bear = load_bear2022_and_full()

    fresh = {}
    for label in ("correction_2015_2016", "selloff_2018", "covid_2020"):
        fresh[label] = build_fresh(label)

    for label in EPISODE_ORDER:
        full_start, full_end, crisis_start, crisis_end = EPISODES[label]
        if label == "gfc_2008":
            core_ret, sat_ret = core_gfc, sat_gfc
        elif label in ("bear_2022", "full_2019_2026"):
            core_ret, sat_ret = core_bear, sat_bear
        else:
            core_ret, sat_ret = fresh[label]

        static_blend = blend_returns(core_ret, sat_ret, SATELLITE_WEIGHT)
        w_start, w_end = (full_start, full_end) if label == "full_2019_2026" else (crisis_start, crisis_end)
        core_w = slice_window(core_ret, w_start, w_end)
        blend_w = slice_window(static_blend, w_start, w_end)
        out[label] = {
            "core_alone": core_w,
            "case_a_static_satellite": blend_w,
            "window_used": [w_start, w_end],
            "n_obs": int(len(core_w)),
        }
        log(f"  {label}: window={w_start}~{w_end}, n_obs={len(core_w)}")

    log(f"gather_window_returns 완료 ({time.time()-t0:.1f}s)")
    return out


def annualized_sharpe(ret: np.ndarray) -> float:
    if len(ret) < 2:
        return float("nan")
    mu, sd = np.mean(ret), np.std(ret, ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(mu / sd * np.sqrt(TRADING_DAYS))


def moving_block_bootstrap_sharpe(ret: np.ndarray, block_len: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """순환(wrap-around) 이동블록부트스트랩: n_obs 길이와 같은 합성 시계열을 n_boot개 생성, 각각의
    연율화 샤프비율을 반환."""
    n = len(ret)
    if n == 0:
        return np.full(n_boot, np.nan)
    block_len = min(block_len, n)
    n_blocks_needed = int(np.ceil(n / block_len))
    max_start = n  # circular: any start 0..n-1 valid
    sharpes = np.empty(n_boot)
    ext = np.concatenate([ret, ret])  # allow wrap-around slicing
    for b in range(n_boot):
        starts = rng.integers(0, max_start, size=n_blocks_needed)
        pieces = [ext[s:s + block_len] for s in starts]
        synth = np.concatenate(pieces)[:n]
        sharpes[b] = annualized_sharpe(synth)
    return sharpes


def bootstrap_all(window_returns: dict) -> dict:
    rng = np.random.default_rng(SEED)
    out = {}
    for label, d in window_returns.items():
        out[label] = {"window_used": d["window_used"], "n_obs": d["n_obs"], "by_config": {}}
        for cfg in ("core_alone", "case_a_static_satellite"):
            ret = d[cfg].values.astype(float)
            point_sharpe = annualized_sharpe(ret)
            per_block = {}
            for L in BLOCK_LENGTHS:
                boot = moving_block_bootstrap_sharpe(ret, L, N_BOOT, rng)
                boot = boot[~np.isnan(boot)]
                if len(boot) == 0:
                    per_block[str(L)] = None
                    continue
                per_block[str(L)] = {
                    "block_len": L,
                    "n_boot_valid": int(len(boot)),
                    "n_nonoverlapping_blocks_approx": round(d["n_obs"] / L, 1),
                    "mean": float(np.mean(boot)),
                    "std": float(np.std(boot)),
                    "ci90": [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))],
                    "ci50": [float(np.percentile(boot, 25)), float(np.percentile(boot, 75))],
                }
            out[label]["by_config"][cfg] = {
                "point_estimate_sharpe": point_sharpe,
                "n_obs": d["n_obs"],
                "bootstrap_by_block_len": per_block,
            }
            log(f"  bootstrap {label}/{cfg}: point={point_sharpe:.3f}, "
                f"L=20 CI90={per_block.get('20', {}).get('ci90')}")
    return out


def main():
    window_returns = gather_window_returns()

    # save daily return CSVs for transparency/reuse
    for label, d in window_returns.items():
        d["core_alone"].to_csv(OUT_DIR / f"{label}_core_alone_ret.csv", header=["ret"])
        d["case_a_static_satellite"].to_csv(OUT_DIR / f"{label}_case_a_ret.csv", header=["ret"])

    boot_results = bootstrap_all(window_returns)

    out = {
        "meta": {
            "n_boot": N_BOOT, "seed": SEED, "block_lengths": BLOCK_LENGTHS,
            "trading_days": TRADING_DAYS, "episode_order": EPISODE_ORDER,
        },
        "bootstrap": boot_results,
    }
    (OUT_DIR / "h33_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    log("saved h33_results.json")


if __name__ == "__main__":
    main()
