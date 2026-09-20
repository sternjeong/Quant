#!/usr/bin/env python3
"""discover_results.json + valuation_check.json + 오늘자 섹터강도/시장국면 스냅샷을 묶어
report_data.json을 만든다.

이 라운드는 과거 검증(백테스트)이 아니라 2026-09-18(스캔 실행일 2026-09-17 저녁~2026-09-18
사이 발생한 미완성 산출물을 이번 세션이 이어받아 재실행) 시점의 "지금 이 순간" 횡단면
스크리닝이다 — discover_run.py 자체가 이미 이 문서 상단에 그 사실을 명시해뒀다. 순열검정/
블록부트스트랩은 시계열 수익률이 있어야 적용 가능한 방법론이라 여기엔 쓰지 않는다(적용 대상이
아예 다름). 대신 이 스크립트는 3가지 다른 종류의 감사를 계산한다:
  H1 강건성: 가중치 변형 3종(default/momentum_heavy/quality_heavy) 상위20 자카드 중첩도
  H2 교차검증: 상향식(팩터 합성 스코어) 상위 종목의 섹터 분포가 하향식(core.sector_strength)
      엔진이 오늘 독립적으로 뽑은 "뜨거운 테마"와 일치하는가
  H3 밸류에이션: 고든성장모형 정당PER/PBR 역산이 오늘의 상위 후보에 적용 가능한가(모형 붕괴 비율)
  H4(보너스) 시가총액 분포: 오늘의 상위 후보가 진짜 소형 텐베거 후보군인지, 그냥 대형주
      로테이션인지
"""
import json
import os
from datetime import datetime, timezone

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

with open(f"{OUT_DIR}/discover_results.json", encoding="utf-8") as f:
    DISCOVER = json.load(f)

with open(f"{OUT_DIR}/valuation_check.json", encoding="utf-8") as f:
    VALUATION = json.load(f)

import sys

sys.path.insert(0, "/opt/quant")
from core.market_regime import get_latest_market_regime_snapshot
from core.sector_strength import get_latest_theme_strength_snapshot

theme_snap = get_latest_theme_strength_snapshot()
regime_snap = get_latest_market_regime_snapshot()


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return None
    return len(a & b) / len(a | b)


def top_tickers(variant, n=20):
    return [r["ticker"] for r in DISCOVER["results"][variant][:n]]

VARIANTS = ["default", "momentum_heavy", "quality_heavy"]
TOP20 = {v: top_tickers(v, 20) for v in VARIANTS}

overlap_pairs = [("default", "momentum_heavy"), ("default", "quality_heavy"), ("momentum_heavy", "quality_heavy")]
overlaps = []
for a, b in overlap_pairs:
    common = sorted(set(TOP20[a]) & set(TOP20[b]))
    overlaps.append(
        {
            "pair": [a, b],
            "jaccard": jaccard(TOP20[a], TOP20[b]),
            "overlap_n": len(common),
            "overlap_tickers": common,
        }
    )

# 3개 변형 전부에 공통으로 나오는 종목("가중치 불문 핵심 신호")
core_all3 = sorted(set(TOP20["default"]) & set(TOP20["momentum_heavy"]) & set(TOP20["quality_heavy"]))

# H2: 상향식 상위 20(default)의 섹터 분포 vs 오늘 섹터강도 스냅샷 상위 5테마
default_top20_rows = DISCOVER["results"]["default"][:20]
sector_counts: dict[str, int] = {}
for r in default_top20_rows:
    sec = r.get("sector") or "Unknown"
    sector_counts[sec] = sector_counts.get(sec, 0) + 1
sector_counts_sorted = sorted(sector_counts.items(), key=lambda x: -x[1])

theme_rows = theme_snap["theme_scores"].to_dict(orient="records") if theme_snap else []
top5_themes = theme_rows[:5]

# 대략적 테마->GICS 섹터 매핑(gather_data.py/tenbagger 리포트의 관례를 그대로 재사용)
THEME_TO_GICS = {
    "반도체": "Technology",
    "사이버보안": "Technology",
    "에너지": "Energy",
    "클라우드": "Technology",
    "기술": "Technology",
    "헬스케어": "Healthcare",
    "냉각": "Industrials",
    "금융": "Financial Services",
}
top5_gics = sorted({THEME_TO_GICS.get(t["theme"], t["theme"]) for t in top5_themes})

hot_sector_top15 = DISCOVER["results"]["hot_sector"][:15]

# H3: 밸류에이션 모형 요약
val_rows = VALUATION["rows"]
n_collapsed = sum(1 for r in val_rows if r["model_collapsed"])
n_usable = len(val_rows) - n_collapsed
usable_rows = [r for r in val_rows if not r["model_collapsed"]]
# g가 요구수익률에 90% 이상 근접하면 (r-g) 분모가 거의 0에 가까워 정당PER/PBR이 수치적으로
# 불안정(발산)하다고 별도 플래그(모형 "생존"이지만 신뢰 불가) — STT(g=0.088, r=0.09)가 전형적 사례.
for r in usable_rows:
    r["numerically_unstable"] = r["sustainable_growth_g"] is not None and r["sustainable_growth_g"] >= 0.9 * r["required_return"]
n_unstable = sum(1 for r in usable_rows if r["numerically_unstable"])
n_reliable = n_usable - n_unstable
reliable_rows = [r for r in usable_rows if not r["numerically_unstable"]]
n_rich = sum(1 for r in reliable_rows if r["actual_trailing_pe"] and r["justified_pe"] and r["actual_trailing_pe"] > r["justified_pe"])
n_cheap = n_reliable - n_rich

# H4: 시가총액 분포
mkt_caps = [(r["ticker"], r.get("market_cap")) for r in default_top20_rows if r.get("market_cap")]
mkt_caps_sorted = sorted(mkt_caps, key=lambda x: x[1])
n_below_10b = sum(1 for _, mc in mkt_caps if mc < 10e9)
n_below_2b = sum(1 for _, mc in mkt_caps if mc < 2e9)

report = {
    "meta": {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "as_of_scan": DISCOVER["meta"]["as_of"],
        "universe": "S&P500 (core.screener.get_universe, 전종목, 상한 없음)",
        "weight_variants": DISCOVER["meta"]["weight_variants"],
        "hot_sectors_filter": DISCOVER["meta"]["hot_sectors"],
        "scan_runtime_sec": DISCOVER["meta"]["total_runtime_sec"],
        "required_return": VALUATION["required_return"],
        "market_regime": {
            "computed_at": str(regime_snap.get("computed_at")) if regime_snap else None,
            "regime": regime_snap.get("regime") if regime_snap else None,
            "total_score": regime_snap.get("total_score") if regime_snap else None,
            "pct_above_200sma": regime_snap.get("breadth", {}).get("pct_above_200sma") if regime_snap else None,
        },
    },
    "variants_top20": {v: DISCOVER["results"][v][:20] for v in VARIANTS},
    "hot_sector_top15": hot_sector_top15,
    "h1_robustness": {
        "overlaps": overlaps,
        "core_all3": core_all3,
    },
    "h2_cross_validation": {
        "theme_snapshot_computed_at": str(theme_snap["computed_at"]) if theme_snap else None,
        "top5_themes": top5_themes,
        "top5_gics_mapped": top5_gics,
        "bottom_up_sector_counts": sector_counts_sorted,
        "all_themes": theme_rows,
    },
    "h3_valuation": {
        "n_total": len(val_rows),
        "n_collapsed": n_collapsed,
        "n_usable": n_usable,
        "n_unstable": n_unstable,
        "n_reliable": n_reliable,
        "n_rich": n_rich,
        "n_cheap": n_cheap,
        "rows": val_rows,
    },
    "h4_market_cap": {
        "rows": mkt_caps_sorted,
        "n_below_10b": n_below_10b,
        "n_below_2b": n_below_2b,
        "min": mkt_caps_sorted[0] if mkt_caps_sorted else None,
        "max": mkt_caps_sorted[-1] if mkt_caps_sorted else None,
    },
}

with open(f"{OUT_DIR}/report_data.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=1, ensure_ascii=False, default=str)
print("[assemble] saved report_data.json")
