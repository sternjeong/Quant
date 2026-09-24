"""튜닝 탐색 장부 + 과적합/이웃 안정성/다중검정 보정 (ENG-04). 순수 함수·데이터 구조만 (DB·백테스트 의존 없음).

- SearchLedger: 후보·재시도·탈락·test 열람 횟수 기록 (결과 dict에 additive 필드로 노출).
- compute_rank_instability: "test 1위가 바뀌었는가"(is_overfit)와 별개로 train 순위와 test 성과의 순위 상관.
- check_neighbor_stability: 채택 config의 이웃(파라미터 1개만 다른) 후보 점수가 급락하는 뾰족한 피크인지.
- deflated_sharpe_ratio: 탐색 후보 수(N)로 샤프 기대 최댓값을 보정한 확률(Bailey-Lopez de Prado 근사).
진단·보고 전용이며 채택 결정에 test 결과를 쓰지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any, Optional

_EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


@dataclass
class SearchLedger:
    """한 번의 튜닝 실행에서 실제로 시도한 탐색 규모. 다중검정 보정의 N 근거."""

    candidates_generated: int = 0  # 그리드가 만든 후보 총수
    rejected: int = 0  # 탈락 (구조 결함 또는 커버리지/매매횟수 미달로 점수 없음)
    scored: int = 0  # 점수가 매겨진 후보
    backbones_searched: int = 0  # 탐색한 backbone 수 (원본 + 구조 변형 재시도)
    structural_retries: int = 0  # 구조 변형 재시도 횟수 (escape hatch)
    test_views: int = 0  # test 구간을 열람(평가)한 횟수 — 많을수록 스누핑 위험
    notes: list = field(default_factory=list)

    def record_search(self, generated: int, scored: int) -> None:
        self.candidates_generated += generated
        self.rejected += max(0, generated - scored)
        self.scored += scored
        self.backbones_searched += 1

    def record_retry(self) -> None:
        self.structural_retries += 1

    def record_test_view(self, n: int = 1) -> None:
        self.test_views += n

    @property
    def n_trials(self) -> int:
        """다중검정 보정에 쓸 시행 수: 점수가 실제로 매겨진(=선택 경쟁에 참여한) 후보 수."""
        return self.scored

    def to_dict(self) -> dict:
        return {
            "candidates_generated": self.candidates_generated,
            "rejected": self.rejected,
            "scored": self.scored,
            "backbones_searched": self.backbones_searched,
            "structural_retries": self.structural_retries,
            "test_views": self.test_views,
            "n_trials": self.n_trials,
        }


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def compute_rank_instability(points: list[dict], min_points: int = 3) -> dict:
    """train 점수 순위와 test 점수의 스피어만 순위상관으로 순위 불안정을 측정한다.

    compute_overfitting_curve의 is_overfit(=test 1위가 rank1이 아님)과는 별개 지표:
    1위가 안 바뀌어도 나머지 순위가 뒤섞일 수 있고, 반대로 1위만 근소하게 밀려도 전체 순위는 안정적일 수 있다.
    points: [{"rank", "train_score", "test_score"|None}] (rank 작을수록 train 우수).
    Returns: {"n_valid", "spearman", "instability"(=(1-rho)/2, 0=안정~1=완전 역전), "top1_changed", "is_unstable"}
    유효 점수가 min_points 미만이면 spearman/instability/is_unstable=None (판단 근거 부족).
    """
    valid = [p for p in points if p.get("test_score") is not None]
    n = len(valid)
    top1_changed = None
    if n >= 2:
        best = max(valid, key=lambda p: p["test_score"])
        top1_changed = best["rank"] != min(p["rank"] for p in valid)
    if n < min_points:
        return {"n_valid": n, "spearman": None, "instability": None, "top1_changed": top1_changed, "is_unstable": None}
    train_goodness = [-p["rank"] for p in valid]
    test_vals = [p["test_score"] for p in valid]
    rt, rs = _average_ranks(train_goodness), _average_ranks(test_vals)
    mt, ms = sum(rt) / n, sum(rs) / n
    cov = sum((a - mt) * (b - ms) for a, b in zip(rt, rs))
    vt = math.sqrt(sum((a - mt) ** 2 for a in rt))
    vs = math.sqrt(sum((b - ms) ** 2 for b in rs))
    if vt == 0 or vs == 0:
        return {"n_valid": n, "spearman": None, "instability": None, "top1_changed": top1_changed, "is_unstable": None}
    rho = cov / (vt * vs)
    return {
        "n_valid": n,
        "spearman": round(rho, 3),
        "instability": round((1 - rho) / 2, 3),
        "top1_changed": top1_changed,
        "is_unstable": rho < 0.3,
    }


def _flatten_numeric(obj: Any, path: tuple = ()) -> Optional[dict]:
    """config를 {경로: 값} 리프 맵으로. 숫자가 아닌 리프는 같아야 이웃이므로 그대로 포함."""
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten_numeric(v, path + (k,)))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.update(_flatten_numeric(v, path + (i,)))
    else:
        out[path] = obj
    return out


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def find_neighbors(chosen: dict, trail: list[dict]) -> list[dict]:
    """trail 항목 중 chosen과 정확히 1개의 숫자 리프만 다른 것들(이웃)."""
    base = _flatten_numeric(chosen)
    neighbors = []
    for item in trail:
        other = _flatten_numeric(item["config"])
        if set(other) != set(base):
            continue
        diffs = [p for p in base if base[p] != other[p]]
        if len(diffs) == 1 and _is_num(base[diffs[0]]) and _is_num(other[diffs[0]]):
            neighbors.append(item)
    return neighbors


def check_neighbor_stability(
    trail: list[dict], chosen_config: Optional[dict] = None, min_neighbors: int = 2, retain_ratio: float = 0.5
) -> dict:
    """채택 config(기본: trail[0])의 이웃 점수가 채택 점수의 retain_ratio 이상 유지되는지 본다.

    추가 백테스트 없이 이미 계산된 trail 점수만 쓴다. 이웃 점수가 크게 떨어지면 뾰족한 피크(과적합 의심).
    점수가 0 이하이면 비율이 의미 없어 절대 낙폭(best - neighbor_mean)이 0 이하일 때만 안정으로 본다.
    Returns: {"n_neighbors", "best_score", "neighbor_mean", "neighbor_min", "retention", "is_stable"}
    이웃이 min_neighbors 미만이면 is_stable=None (판단 불가, 통과로 취급하지 않음).
    """
    if not trail:
        return {"n_neighbors": 0, "best_score": None, "neighbor_mean": None, "neighbor_min": None,
                "retention": None, "is_stable": None}
    chosen_item = trail[0]
    if chosen_config is not None:
        for it in trail:
            if it["config"] == chosen_config:
                chosen_item = it
                break
    best = chosen_item["score"]
    others = [it for it in trail if it is not chosen_item]
    nb = find_neighbors(chosen_item["config"], others)
    if len(nb) < min_neighbors:
        return {"n_neighbors": len(nb), "best_score": best, "neighbor_mean": None, "neighbor_min": None,
                "retention": None, "is_stable": None}
    scores = [it["score"] for it in nb]
    mean_s, min_s = sum(scores) / len(scores), min(scores)
    if best > 0:
        retention = mean_s / best
        stable = retention >= retain_ratio
    else:
        retention = None
        stable = mean_s >= best
    return {
        "n_neighbors": len(nb), "best_score": best, "neighbor_mean": round(mean_s, 3),
        "neighbor_min": round(min_s, 3),
        "retention": None if retention is None else round(retention, 3),
        "is_stable": stable,
    }


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """N개 무관 시행 중 최대 샤프의 기대값 근사 (Bailey & Lopez de Prado 2014). 단위는 입력 분산과 동일."""
    if n_trials <= 1 or sharpe_variance <= 0:
        return 0.0
    sd = math.sqrt(sharpe_variance)
    return sd * (
        (1 - _EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
        + _EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    )


def deflated_sharpe_ratio(
    observed_sharpe: float, n_trials: int, sharpe_variance: float, n_obs: int,
    skew: float = 0.0, kurtosis: float = 3.0,
) -> dict:
    """Deflated Sharpe Ratio 근사: 탐색 후보 수만큼 부풀려진 최대 샤프를 뺀 뒤의 "진짜 샤프>0" 확률.

    observed_sharpe, sharpe_variance는 **관측 1기간(예: 일간) 단위**여야 한다(연율 샤프면 sqrt(252)로 나눠 전달).
    n_obs: 관측 수. skew/kurtosis: 수익률 3·4차 모멘트(정규=0, 3).
    Returns: {"dsr"(0~1, 높을수록 우연이 아님), "expected_max_sharpe", "n_trials", "is_significant"(dsr>=0.95)}
    n_obs<2 이거나 분모가 비정상이면 dsr=None.
    """
    sr0 = expected_max_sharpe(n_trials, sharpe_variance)
    denom_sq = 1 - skew * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe**2
    if n_obs < 2 or denom_sq <= 0:
        return {"dsr": None, "expected_max_sharpe": round(sr0, 6), "n_trials": n_trials, "is_significant": None}
    z = (observed_sharpe - sr0) * math.sqrt(n_obs - 1) / math.sqrt(denom_sq)
    dsr = _N.cdf(z)
    return {"dsr": round(dsr, 4), "expected_max_sharpe": round(sr0, 6), "n_trials": n_trials,
            "is_significant": dsr >= 0.95}


def deflate_trail_sharpe(trail: list[dict], n_trials: int, n_obs_days: int, periods_per_year: int = 252) -> dict:
    """trail(연율 mean_sharpe)의 1위를 후보 분산·n_trials로 보정 (연율 -> 일간 환산 후 DSR).

    n_obs_days: train 구간 거래일 수 근사. trail이 2개 미만이면 분산 추정 불가 -> dsr=None.
    """
    sharpes = [t["mean_sharpe"] for t in trail if t.get("mean_sharpe") is not None]
    if len(sharpes) < 2:
        return {"dsr": None, "expected_max_sharpe": None, "n_trials": n_trials, "is_significant": None}
    m = sum(sharpes) / len(sharpes)
    var = sum((s - m) ** 2 for s in sharpes) / (len(sharpes) - 1)
    k = math.sqrt(periods_per_year)
    return deflated_sharpe_ratio(sharpes[0] / k, n_trials, var / periods_per_year, n_obs_days)
