"""오늘(2026-09-17) 시점 S&P500 전체를 core.stock_discovery.discover_candidates()로 스캔한다.

주의 — 이건 과거 검증(백테스트)이 아니라 "지금 이 순간" 유니버스를 스크리닝한 라이브 스냅샷이다.
순열검정/블록부트스트랩 같은 통계적 유의성 검정은 시계열 수익률이 있어야 적용 가능한데, 이건
단일 시점 횡단면(cross-section) 스코어링이라 그 방법론이 적용되지 않는다 — 대신 이 스크립트는
"가중치를 바꿔도 상위 종목 리스트가 안정적인가"(강건성)와 "탑다운 섹터강도 엔진과 교차검증되는가"
라는 다른 종류의 감사를 적용한다.

세 가중치 변형을 돌린다:
  - default:   core.stock_discovery.DEFAULT_WEIGHTS 그대로 (모멘텀0.30/성장0.30/가치0.25/퀄리티0.15)
  - momentum_heavy: 모멘텀0.60/성장0.20/가치0.10/퀄리티0.10 — "지금 뜨는 종목"에 치우친 변형
  - quality_heavy:  모멘텀0.10/성장0.20/가치0.20/퀄리티0.50 — QMJ(품질팩터) 쪽으로 치우친 변형

새 스크리닝 로직은 만들지 않는다 — core.stock_discovery.discover_candidates()만 그대로 호출.
"""
import json
import time

from core.stock_discovery import discover_candidates

OUT_DIR = "/opt/quant/analysis/2026-09-17_live_tenbagger_screening_snapshot"

WEIGHT_VARIANTS = {
    "default": {"momentum": 0.30, "growth": 0.30, "value": 0.25, "quality": 0.15},
    "momentum_heavy": {"momentum": 0.60, "growth": 0.20, "value": 0.10, "quality": 0.10},
    "quality_heavy": {"momentum": 0.10, "growth": 0.20, "value": 0.20, "quality": 0.50},
}

HOT_SECTORS = ["Information Technology", "Energy"]  # sector_strength 스냅샷 상위 테마(반도체/클라우드=IT, 에너지) 근사


def main():
    results = {}

    t0 = time.time()
    print("[discover] full universe, default weights ...")
    df_default = discover_candidates(universe_n=None, weights=WEIGHT_VARIANTS["default"], top_n=50, use_cache=True)
    print(f"  -> {len(df_default)} rows in {time.time()-t0:.1f}s")
    results["default"] = df_default.to_dict(orient="records")

    for variant in ("momentum_heavy", "quality_heavy"):
        t1 = time.time()
        print(f"[discover] full universe, {variant} weights ...")
        df = discover_candidates(universe_n=None, weights=WEIGHT_VARIANTS[variant], top_n=50, use_cache=True)
        print(f"  -> {len(df)} rows in {time.time()-t1:.1f}s")
        results[variant] = df.to_dict(orient="records")

    t2 = time.time()
    print(f"[discover] hot-sector filter ({HOT_SECTORS}), default weights ...")
    df_hot = discover_candidates(
        universe_n=None, weights=WEIGHT_VARIANTS["default"], sector_filter=HOT_SECTORS, top_n=30, use_cache=True
    )
    print(f"  -> {len(df_hot)} rows in {time.time()-t2:.1f}s")
    results["hot_sector"] = df_hot.to_dict(orient="records")

    with open(f"{OUT_DIR}/discover_results.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "meta": {
                    "as_of": "2026-09-17",
                    "weight_variants": WEIGHT_VARIANTS,
                    "hot_sectors": HOT_SECTORS,
                    "total_runtime_sec": time.time() - t0,
                },
                "results": results,
            },
            f,
            indent=1,
            default=str,
        )
    print(f"[discover] saved discover_results.json, total {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
