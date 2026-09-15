"""H5 - 트랙C 자체 관례(track_c_bootstrap_confidence_audit)를 그대로 이어받아, H1~H3의 "콜라가
손해"라는 결론에 원형 이동블록부트스트랩 감사를 적용한다.

H1~H3의 점추정(단일 백테스트 1회 비교)만으로는 "무헤지가 항상 이겼다"는 게 우연한 한 경로의
산물인지, 표본오차를 감안해도 강건한지 알 수 없다. h33_block_bootstrap_sample_error.py(트랙D)와
audit1_iren_trend_bootstrap.py(트랙C 자신의 선례)가 쓴 것과 동일한 방법(순환 이동블록부트스트랩,
block_len=10/20/40, 2000회)을 무헤지 vs 콜라1x 두 시계열 각각에 적용해 신뢰구간을 구하고, 게다가
"두 시계열의 샤프 차이" 자체의 부트스트랩 분포(같은 블록 인덱스로 두 시계열을 동시에 리샘플링해
쌍대비교, paired resampling)까지 계산해 "무헤지가 이긴다"는 방향이 얼마나 자주 재현되는지 승률로
보고한다.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from hedge_common import OUT_DIR, END, N_BOOT, BLOCK_LENGTHS, SEED, annualized_sharpe


def log(msg):
    print(f"[h5] {msg}", flush=True)


def paired_moving_block_bootstrap(base: np.ndarray, hedged: np.ndarray, block_len: int, n_boot: int,
                                   rng: np.random.Generator) -> dict:
    """base/hedged를 '같은 날짜 인덱스'로 동시에 블록 리샘플링(paired) - 매크로 충격(예: 특정일
    폭락)이 두 시계열에 동시에 반영된 채로 재표본추출되도록 해, 콜라의 방어효과 유무를 왜곡 없이
    비교한다."""
    n = len(base)
    block_len = min(block_len, n)
    n_blocks_needed = int(np.ceil(n / block_len))
    ext_base = np.concatenate([base, base])
    ext_hedged = np.concatenate([hedged, hedged])
    sharpe_base = np.empty(n_boot)
    sharpe_hedged = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks_needed)
        pieces_base = np.concatenate([ext_base[s:s + block_len] for s in starts])[:n]
        pieces_hedged = np.concatenate([ext_hedged[s:s + block_len] for s in starts])[:n]
        sharpe_base[b] = annualized_sharpe(pieces_base)
        sharpe_hedged[b] = annualized_sharpe(pieces_hedged)
    diff = sharpe_hedged - sharpe_base  # 양수면 콜라가 이김
    return {
        "base_sharpe_mean": float(np.mean(sharpe_base)), "base_sharpe_ci90": [float(np.percentile(sharpe_base, 5)), float(np.percentile(sharpe_base, 95))],
        "hedged_sharpe_mean": float(np.mean(sharpe_hedged)), "hedged_sharpe_ci90": [float(np.percentile(sharpe_hedged, 5)), float(np.percentile(sharpe_hedged, 95))],
        "diff_mean": float(np.mean(diff)), "diff_ci90": [float(np.percentile(diff, 5)), float(np.percentile(diff, 95))],
        "win_rate_hedged": float(np.mean(diff > 0)),
    }


def main():
    rng = np.random.default_rng(SEED)
    results = {}
    for label in ["basket_bh", "basket_trend", "iren_bh", "iren_trend"]:
        base = pd.read_csv(OUT_DIR / f"{label}_unhedged_ret.csv", index_col=0, parse_dates=True)["ret"]
        overlay = pd.read_csv(OUT_DIR / f"{label}_collar_overlay_ret.csv", index_col=0, parse_dates=True)["ret"]
        overlay = overlay.reindex(base.index).fillna(0.0)
        hedged = base + overlay * 1.0  # 1x 콜라(h1/h2 기본 시나리오)

        by_block = {}
        for L in BLOCK_LENGTHS:
            by_block[str(L)] = paired_moving_block_bootstrap(base.values, hedged.values, L, N_BOOT, rng)
        results[label] = {
            "n_obs": int(len(base)),
            "point_sharpe_unhedged": annualized_sharpe(base.values),
            "point_sharpe_collar1x": annualized_sharpe(hedged.values),
            "by_block_len": by_block,
        }
        L20 = by_block["20"]
        log(f"{label}: 점추정 무헤지{results[label]['point_sharpe_unhedged']:.3f} vs 콜라1x{results[label]['point_sharpe_collar1x']:.3f} | "
            f"L20 승률(콜라가 이길 확률)={L20['win_rate_hedged']*100:.1f}%, 차이90%CI={L20['diff_ci90']}")

    out = {"meta": {"generated": END, "n_boot": N_BOOT, "block_lengths": BLOCK_LENGTHS, "seed": SEED}, "h5_results": results}
    with open(OUT_DIR / "h5_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    log("저장 완료: h5_results.json")


if __name__ == "__main__":
    main()
