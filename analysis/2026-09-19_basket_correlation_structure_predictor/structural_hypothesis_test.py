""""상관구조가 IREN 패턴 재현을 예측한다"는 가설을 8개 바스켓(기존6+신규2) 전체로 정식 검정.

historical_era_trend_following_extension(작업88)이 가설로만 남긴 것을 이 라운드가 두 단계로
검증한다:
  1) 사후 데이터(기존 6개 바스켓)에서 상관관계와 재현여부/샤프격차의 관계를 정량화(Spearman,
     그룹평균차 순열검정) — 이건 작업88 시점엔 숫자로 확인되지 않았던 부분.
  2) 상관구조를 먼저 예측(사전등록)한 신규 2개 바스켓(EV SPAC 붐-버스트=HIGH예측,
     희귀질환 바이오텍=LOW예측)의 실제 상관계수·백테스트 결과를 대조해 진짜 아웃오브샘플
     검증을 수행 — 이게 이 라운드의 핵심 기여다(사후 패턴매칭이 아니라 예측 성공/실패를 미리
     정해둔 기준으로 판정).

scipy 없이 numpy만으로 스피어만 상관계수(순위 피어슨)와 정확 순열검정(그룹 평균차, 8개 중 4개
뽑는 전체 C(8,4)=70가지 조합 전수)을 직접 구현한다 — 통계 라이브러리가 없어 발명한 게 아니라
scipy 자체가 이 환경에 없어서다(둘 다 표준적으로 정의된 통계량).
"""
import itertools
import json

import numpy as np

OUT_DIR = "/opt/quant/analysis/2026-09-19_basket_correlation_structure_predictor"

IREN_JSON = "/opt/quant/analysis/2026-08-16_iren_volatile_momentum_stocks/report_data.json"
NONAI_JSON = "/opt/quant/analysis/2026-09-14_nonai_control_basket_volatility_momentum/backtest_results.json"
ERA_JSON = "/opt/quant/analysis/2026-09-17_historical_era_trend_following_extension/backtest_results.json"


def log(msg):
    print(f"[hyp] {msg}", flush=True)


def spearman(x, y):
    """순위 기반 피어슨 상관계수(scipy 없이 직접 구현). 동순위는 평균순위로 처리."""
    def rank(a):
        order = np.argsort(a, kind="mergesort")
        ranks = np.empty(len(a))
        sorted_a = a[order]
        i = 0
        while i < len(a):
            j = i
            while j + 1 < len(a) and sorted_a[j + 1] == sorted_a[i]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = rank(np.asarray(x, dtype=float)), rank(np.asarray(y, dtype=float))
    return float(np.corrcoef(rx, ry)[0, 1])


def exact_permutation_group_test(values: np.ndarray, is_group_a: np.ndarray):
    """그룹 라벨을 고정한 채 '어느 조합이 그룹A(재현됨)로 뽑혔는가'를 전수 나열해, 관측된
    그룹평균차가 무작위 배정 대비 몇 백분위인지 정확히(exact) 계산한다. n=8, |A|=4 → C(8,4)=70가지."""
    n = len(values)
    n_a = int(is_group_a.sum())
    observed_diff = float(values[is_group_a].mean() - values[~is_group_a].mean())
    all_diffs = []
    idx = np.arange(n)
    for combo in itertools.combinations(idx, n_a):
        combo = set(combo)
        mask = np.array([i in combo for i in idx])
        d = values[mask].mean() - values[~mask].mean()
        all_diffs.append(d)
    all_diffs = np.array(all_diffs)
    # 양측검정: |관측값|보다 크거나 같은 순열의 비율
    p_two_sided = float(np.mean(np.abs(all_diffs) >= abs(observed_diff) - 1e-12))
    percentile = float(100.0 * np.mean(all_diffs <= observed_diff))
    return {
        "observed_diff_mean_corr_A_minus_B": round(observed_diff, 4),
        "n_total_combinations": len(all_diffs),
        "exact_p_two_sided": round(p_two_sided, 4),
        "percentile_of_observed": round(percentile, 2),
    }


def unwrap(d):
    return d["metrics"] if "metrics" in d else d


def main():
    with open(f"{OUT_DIR}/correlation_results.json", encoding="utf-8") as f:
        corr = json.load(f)
    with open(f"{OUT_DIR}/backtest_results.json", encoding="utf-8") as f:
        new_bt = json.load(f)
    with open(IREN_JSON, encoding="utf-8") as f:
        iren = json.load(f)
    with open(NONAI_JSON, encoding="utf-8") as f:
        nonai = json.load(f)
    with open(ERA_JSON, encoding="utf-8") as f:
        era = json.load(f)

    # 8개 바스켓의 (bh_sharpe, rot_sharpe, tf_basket_sharpe) 수집 — 전부 각 원본 json에서 직접
    # 읽어온다(재입력으로 인한 오타 방지).
    sharpe_table = {
        "iren": {
            "bh": unwrap(iren["basket_static_buy_hold"])["sharpe"],
            "rot": unwrap(iren["momentum_rotation"])["sharpe"],
            "tf": iren["trend_following_best"]["basket"]["sharpe"],
        },
        "shipping": {
            "bh": nonai["shipping"]["basket_static_buy_hold"]["sharpe"],
            "rot": nonai["shipping"]["momentum_rotation"]["sharpe"],
            "tf": nonai["shipping"]["trend_following_basket"]["sharpe"],
        },
        "cannabis": {
            "bh": nonai["cannabis"]["basket_static_buy_hold"]["sharpe"],
            "rot": nonai["cannabis"]["momentum_rotation"]["sharpe"],
            "tf": nonai["cannabis"]["trend_following_basket"]["sharpe"],
        },
        "solar": {
            "bh": nonai["solar"]["basket_static_buy_hold"]["sharpe"],
            "rot": nonai["solar"]["momentum_rotation"]["sharpe"],
            "tf": nonai["solar"]["trend_following_basket"]["sharpe"],
        },
        "crypto_winter_2018": {
            "bh": era["crypto_winter_2018"]["basket_static_buy_hold"]["sharpe"],
            "rot": era["crypto_winter_2018"]["momentum_rotation"]["sharpe"],
            "tf": era["crypto_winter_2018"]["trend_following_basket"]["sharpe"],
        },
        "dotcom_bubble_2000": {
            "bh": era["dotcom_bubble_2000"]["basket_static_buy_hold"]["sharpe"],
            "rot": era["dotcom_bubble_2000"]["momentum_rotation"]["sharpe"],
            "tf": era["dotcom_bubble_2000"]["trend_following_basket"]["sharpe"],
        },
        "ev_spac_bust": {
            "bh": new_bt["ev_spac_bust"]["basket_static_buy_hold"]["sharpe"],
            "rot": new_bt["ev_spac_bust"]["momentum_rotation"]["sharpe"],
            "tf": new_bt["ev_spac_bust"]["trend_following_basket"]["sharpe"],
        },
        "biotech_catalyst": {
            "bh": new_bt["biotech_catalyst"]["basket_static_buy_hold"]["sharpe"],
            "rot": new_bt["biotech_catalyst"]["momentum_rotation"]["sharpe"],
            "tf": new_bt["biotech_catalyst"]["trend_following_basket"]["sharpe"],
        },
    }

    names = list(sharpe_table.keys())
    avg_corr = np.array([corr[n]["correlation"]["mean"] for n in names])
    sharpe_gap = np.array([sharpe_table[n]["tf"] - max(sharpe_table[n]["bh"], sharpe_table[n]["rot"]) for n in names])
    reproduced = sharpe_gap > 0  # TF바스켓이 매수후보유·로테이션 둘 다 이겼는가

    predicted_high_corr = {"ev_spac_bust": True, "biotech_catalyst": False}
    predicted_reproduce = {"ev_spac_bust": True, "biotech_catalyst": False}

    log("바스켓별 (평균상관, 샤프격차, 재현여부):")
    per_basket = {}
    for i, n in enumerate(names):
        log(f"  {n:22s} corr={avg_corr[i]:.4f}  gap={sharpe_gap[i]:+.3f}  reproduced={bool(reproduced[i])}")
        per_basket[n] = {
            "avg_pairwise_corr": round(float(avg_corr[i]), 4),
            "sharpe_gap": round(float(sharpe_gap[i]), 4),
            "reproduced": bool(reproduced[i]),
            "bh_sharpe": sharpe_table[n]["bh"], "rot_sharpe": sharpe_table[n]["rot"], "tf_basket_sharpe": sharpe_table[n]["tf"],
        }

    # ---------------- 1) 상관관계 vs 샤프격차 (연속, n=8, 스피어만) ----------------
    rho = spearman(avg_corr, sharpe_gap)
    log(f"스피어만(평균상관 vs 샤프격차, n=8): rho={rho:.4f}")

    # ---------------- 2) 재현여부(이진) 그룹 간 평균상관 차이 — 정확 순열검정 ----------------
    exact_test = exact_permutation_group_test(avg_corr, reproduced)
    log(f"정확 순열검정(재현군 vs 미재현군 평균상관 차이): {exact_test}")

    # ---------------- 3) 기존 6개(사후)만으로 같은 검정 — 신규 2개 추가가 결론을 어떻게 바꾸는지 대조 ----------------
    orig6_mask = np.array([n not in predicted_high_corr for n in names])
    rho_orig6 = spearman(avg_corr[orig6_mask], sharpe_gap[orig6_mask])
    exact_test_orig6 = exact_permutation_group_test(avg_corr[orig6_mask], reproduced[orig6_mask])
    log(f"[대조] 기존6개만: 스피어만={rho_orig6:.4f}, 순열검정={exact_test_orig6}")

    # ---------------- 4) 사전등록 예측 성공/실패 판정 ----------------
    preregistration = {}
    for n in ["ev_spac_bust", "biotech_catalyst"]:
        actual_high_corr = bool(avg_corr[names.index(n)] >= np.median(avg_corr[orig6_mask]))
        corr_prediction_correct = actual_high_corr == predicted_high_corr[n]
        outcome_prediction_correct = bool(reproduced[names.index(n)]) == predicted_reproduce[n]
        preregistration[n] = {
            "predicted_high_correlation": predicted_high_corr[n],
            "actual_avg_corr": round(float(avg_corr[names.index(n)]), 4),
            "actual_high_relative_to_existing6_median": actual_high_corr,
            "correlation_mechanism_prediction_correct": corr_prediction_correct,
            "predicted_reproduce": predicted_reproduce[n],
            "actual_reproduced": bool(reproduced[names.index(n)]),
            "outcome_prediction_correct": outcome_prediction_correct,
        }
        log(f"사전등록 판정 [{n}]: {preregistration[n]}")

    result = {
        "meta": {
            "method": "scipy 미설치 환경이라 스피어만/정확순열검정을 numpy로 직접 구현(표준 정의 그대로, 새 통계량 발명 없음)",
            "n_baskets": len(names),
        },
        "per_basket": per_basket,
        "spearman_corr_vs_sharpe_gap_all8": round(rho, 4),
        "spearman_corr_vs_sharpe_gap_orig6": round(rho_orig6, 4),
        "exact_permutation_reproduced_grouping_all8": exact_test,
        "exact_permutation_reproduced_grouping_orig6": exact_test_orig6,
        "preregistration_verdicts": preregistration,
    }

    with open(f"{OUT_DIR}/structural_hypothesis_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {OUT_DIR}/structural_hypothesis_results.json")


if __name__ == "__main__":
    main()
