"""H3 - 플라시보/순열검정: 칼라의 "위기 시점에 정확히 맞물린 페이오프"가 진짜 가치를 내는지,
아니면 그냥 변동성을 깎아 샤프를 부풀리는 계산상의 착시인지 감사한다.

이 프로그램의 확립된 규칙("정적 사전필터는 기본적으로 의심하고 무작위 대조군과 비교하라")을 헤지
오버레이에 적용한 버전이다. 두 가지 플라시보를 돈다:

  H3a 순열검정(페이오프 시점 셔플): 실제 칼라의 롤 로그(각 롤의 프리미엄 지불액 + 만기 페이오프)는
      "이 롤 사이클이 실제로 위기와 겹쳤는지"에 따라 서로 다른 페이오프를 낸다. 이 (프리미엄,페이오프)
      쌍의 순서를 무작위로 섞어(같은 총 비용/총 페이오프 풀을 유지한 채, 달력상 위치만 무작위 재배치)
      200회 합성 이력을 만들고, 위기창 샤프 개선폭(칼라-무헤지)의 무작위 분포에서 실제(섞지 않은)
      개선폭이 몇 백분위에 있는지 본다. 실제가 상위 백분위에 있어야 "위기 타이밍과 실제로 맞물려서"
      가치를 낸다는 주장이 성립한다 — 그렇지 않다면(중간 백분위 근처) 어느 배치로 섞어도 비슷한
      개선이 나온다는 뜻이라 "위기 방어" 서사 자체가 의심스러워진다.

  H3b 제로페이오프 플라시보(순수 비용 드래그): 같은 프리미엄 지불 스케줄은 그대로 두되 만기
      페이오프를 전부 0으로 만든 가짜 오버레이("보험료만 내고 한 번도 청구하지 않는" 극단)와
      비교한다. 실제 칼라가 이 플라시보보다 위기창에서 뚜렷이 낫다면 페이오프 자체(볼록성)가
      방어에 기여한다는 뜻이고, 비슷하다면 "칼라가 이긴다"는 관측이 사실은 프리미엄 드래그가
      만든 변동성 축소의 부작용(샤프 분모 감소)일 뿐일 수 있다는 경고 신호다.

옵션가격/롤 스케줄 계산은 새로 만들지 않는다 — core.champion_strategy.build_collar_overlay_returns를
그대로 호출해 baseline 롤 로그를 얻고, 그 위에서 프리미엄/페이오프 쌍만 재배열/영점처리한다.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/quant")

import numpy as np
import pandas as pd

from core.backtest_engine import calculate_metrics
from core.champion_strategy import build_collar_overlay_returns, SATELLITE_WEIGHT, COLLAR_TENOR_DAYS

OUT_DIR = Path(__file__).resolve().parent

EPISODES = {
    "gfc_2008": ("2007-01-01", "2009-12-31", "2007-10-01", "2009-06-30"),
    "correction_2015_2016": ("2014-06-01", "2016-06-30", "2015-08-01", "2016-02-15"),
    "selloff_2018": ("2017-06-01", "2019-06-30", "2018-09-01", "2019-01-15"),
    "bear_2022": ("2019-08-12", "2026-08-19", "2022-01-01", "2022-12-31"),
    "covid_2020": ("2019-01-01", "2020-12-31", "2020-02-19", "2020-04-30"),
    "full_2019_2026": ("2019-08-12", "2026-08-19", "2019-08-12", "2026-08-19"),
}
EPISODE_ORDER = ["full_2019_2026", "gfc_2008", "covid_2020", "bear_2022", "selloff_2018", "correction_2015_2016"]
GROUP_OF = {
    "gfc_2008": "gfc_2008", "correction_2015_2016": "correction_2015_2016",
    "selloff_2018": "selloff_2018", "covid_2020": "covid_2020",
    "bear_2022": "full_2019_2026_shared", "full_2019_2026": "full_2019_2026_shared",
}
N_PERMUTATIONS = 200
SEED = 20260915


def log(msg):
    print(f"[h3] {msg}", flush=True)


def load_group_returns(group: str) -> dict:
    core_ret = pd.read_csv(OUT_DIR / f"{group}_core_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    unhedged = pd.read_csv(OUT_DIR / f"{group}_unhedged_blend_ret.csv", index_col=0, parse_dates=True).iloc[:, 0]
    return {"core_ret": core_ret, "unhedged_blend": unhedged}


def metrics_from_ret(ret: pd.Series, start, end) -> dict:
    r = ret[(ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))]
    if r.empty:
        return calculate_metrics(pd.Series(dtype=float), [], start, end)
    eq = (1.0 + r.fillna(0.0)).cumprod() * 100.0
    eq.iloc[0] = 100.0
    return calculate_metrics(eq, [], eq.index[0], eq.index[-1])


def sharpe_from_ret(ret: pd.Series, start, end) -> float:
    return metrics_from_ret(ret, start, end)["sharpe"]


def overlay_from_roll_log(trading_index: pd.DatetimeIndex, roll_log: list[dict],
                           premium_key: str, payoff_key: str) -> pd.Series:
    overlay = pd.Series(0.0, index=trading_index)
    for r in roll_log:
        rd = pd.Timestamp(r["roll_date"])
        ed = pd.Timestamp(r["expiry_date"])
        if rd in overlay.index:
            overlay.loc[rd] += r[premium_key]
        if ed in overlay.index:
            overlay.loc[ed] += r[payoff_key]
    return overlay


def permutation_test(episode: str, cached: dict, roll_log: list[dict], window: tuple, rng: np.random.Generator) -> dict:
    trading_index = cached["unhedged_blend"].index
    ws, we = window
    n = len(roll_log)
    premiums = [r["net_premium_pct"] for r in roll_log]
    payoffs = [r["net_payoff_pct"] for r in roll_log]

    def build_and_score(order: np.ndarray) -> float:
        shuffled_log = [
            {"roll_date": roll_log[i]["roll_date"], "expiry_date": roll_log[i]["expiry_date"],
             "net_premium_pct": premiums[order[i]], "net_payoff_pct": payoffs[order[i]]}
            for i in range(n)
        ]
        overlay = overlay_from_roll_log(trading_index, shuffled_log, "net_premium_pct", "net_payoff_pct")
        overlay_scaled = overlay.reindex(trading_index).fillna(0.0) * SATELLITE_WEIGHT
        collar_ret = cached["unhedged_blend"] + overlay_scaled
        return sharpe_from_ret(collar_ret, ws, we) - sharpe_from_ret(cached["unhedged_blend"], ws, we)

    identity = np.arange(n)
    actual_delta = build_and_score(identity)

    null_deltas = []
    for _ in range(N_PERMUTATIONS):
        perm = rng.permutation(n)
        null_deltas.append(build_and_score(perm))
    null_deltas = np.array(null_deltas)
    percentile = float((null_deltas < actual_delta).mean() * 100)

    return {
        "n_rolls": n, "actual_sharpe_delta": actual_delta,
        "null_mean": float(np.mean(null_deltas)), "null_std": float(np.std(null_deltas)),
        "null_p5": float(np.percentile(null_deltas, 5)), "null_p95": float(np.percentile(null_deltas, 95)),
        "actual_percentile_in_null": percentile,
    }


def zero_payoff_placebo(episode: str, cached: dict, roll_log: list[dict], window: tuple) -> dict:
    trading_index = cached["unhedged_blend"].index
    ws, we = window
    zeroed_log = [{"roll_date": r["roll_date"], "expiry_date": r["expiry_date"],
                    "net_premium_pct": r["net_premium_pct"], "net_payoff_pct": 0.0} for r in roll_log]
    overlay = overlay_from_roll_log(trading_index, zeroed_log, "net_premium_pct", "net_payoff_pct")
    overlay_scaled = overlay.reindex(trading_index).fillna(0.0) * SATELLITE_WEIGHT
    placebo_ret = cached["unhedged_blend"] + overlay_scaled

    real_overlay = overlay_from_roll_log(trading_index, roll_log, "net_premium_pct", "net_payoff_pct")
    real_overlay_scaled = real_overlay.reindex(trading_index).fillna(0.0) * SATELLITE_WEIGHT
    real_collar_ret = cached["unhedged_blend"] + real_overlay_scaled

    return {
        "window": [ws, we],
        "unhedged": metrics_from_ret(cached["unhedged_blend"], ws, we),
        "real_collar": metrics_from_ret(real_collar_ret, ws, we),
        "zero_payoff_placebo": metrics_from_ret(placebo_ret, ws, we),
    }


def main():
    rng = np.random.default_rng(SEED)
    t0 = time.time()
    group_cache = {}
    results = {"meta": {"n_permutations": N_PERMUTATIONS, "seed": SEED}, "permutation": {}, "zero_payoff_placebo": {}}

    for episode in EPISODE_ORDER:
        group_key = GROUP_OF[episode]
        if group_key not in group_cache:
            group_cache[group_key] = load_group_returns(group_key)
        cached = group_cache[group_key]

        full_start, full_end, crisis_start, crisis_end = EPISODES[episode]
        is_full = episode == "full_2019_2026"
        window = (full_start, full_end) if is_full else (crisis_start, crisis_end)

        trading_index = cached["unhedged_blend"].index
        overlay_info = build_collar_overlay_returns(trading_index, full_start, full_end, 1.00, 1.05, COLLAR_TENOR_DAYS)
        roll_log = overlay_info["roll_log"]

        log(f"{episode}: 순열검정 시작 (n_rolls={len(roll_log)}, window={window})")
        perm_result = permutation_test(episode, cached, roll_log, window, rng)
        results["permutation"][episode] = perm_result
        log(f"  actual_delta={perm_result['actual_sharpe_delta']:.4f}, "
            f"null 90% CI=[{perm_result['null_p5']:.4f},{perm_result['null_p95']:.4f}], "
            f"percentile={perm_result['actual_percentile_in_null']:.1f}")

        zp_result = zero_payoff_placebo(episode, cached, roll_log, window)
        results["zero_payoff_placebo"][episode] = zp_result
        log(f"  zero-payoff placebo sharpe={zp_result['zero_payoff_placebo']['sharpe']:.3f} "
            f"vs real_collar={zp_result['real_collar']['sharpe']:.3f} vs unhedged={zp_result['unhedged']['sharpe']:.3f}")

    (OUT_DIR / "h3_placebo_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    log(f"저장 완료: h3_placebo_results.json ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
