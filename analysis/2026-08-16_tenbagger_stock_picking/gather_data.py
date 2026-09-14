#!/usr/bin/env python3
"""텐베거 발굴 리포트용 실데이터 수집 스크립트.

기존 검증된 인프라만 재사용한다 (재구현 금지):
- core.sector_strength.get_latest_theme_strength_snapshot() — 섹터/테마 RS 점수(이미 있는 스냅샷)
- core.market_regime.get_latest_market_regime_snapshot() — 시장 국면 종합점수(이미 있는 스냅샷)
- core.screener.screen() — PER/PBR/시총/섹터/RSI/200일선 필터
- core.valuation.fetch_valuation_inputs() / peg_ratio() — PEG, ROE 프록시 계산

산출물: report_data.json (build_report.py가 읽어서 HTML을 생성)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from core.db import init_db
from core.market_regime import get_latest_market_regime_snapshot
from core.sector_strength import get_latest_theme_strength_snapshot
from core.screener import screen, get_universe
from core.valuation import fetch_valuation_inputs, peg_ratio

init_db()  # 이 worktree엔 로컬 DB가 아직 없어(gitignore) 새로 생성 — CI 스냅샷 JSON이 폴백으로 쓰임

OUT_DIR = Path(__file__).resolve().parent

# 테마 강도 모듈(core/sector_strength.py)의 한글 테마명 -> 스크리너가 쓰는 GICS 섹터명 매핑.
# 세부테마(반도체/DRAM/우주/방산/냉각/사이버보안/클라우드/로보틱스/광통신/원자력)는 GICS 표준
# 11섹터에 없으므로, 해당 테마의 대표 기업들이 실제로 속한 상위 GICS 섹터로 근사 매핑한다
# (예: 반도체 -> Information Technology). 이 근사는 리포트에 명시한다.
THEME_TO_GICS = {
    "기술": "Information Technology",
    "금융": "Financials",
    "헬스케어": "Health Care",
    "임의소비재": "Consumer Discretionary",
    "필수소비재": "Consumer Staples",
    "에너지": "Energy",
    "산업재": "Industrials",
    "소재": "Materials",
    "유틸리티": "Utilities",
    "부동산": "Real Estate",
    "커뮤니케이션": "Communication Services",
    "반도체": "Information Technology",
    "메모리/DRAM": "Information Technology",
    "우주": "Industrials",
    "방산": "Industrials",
    "냉각": "Information Technology",
    "사이버보안": "Information Technology",
    "클라우드": "Information Technology",
    "로보틱스": "Industrials",
    "광통신": "Information Technology",
    "원자력": "Utilities",
}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> None:
    result: dict = {"meta": {"generated": date.today().isoformat()}}

    # ------------------------------------------------------------------
    # 1) 시장 국면 스냅샷 (core.market_regime) — 이미 검증된 4신호 합산 프레임워크, 재계산 안 함
    # ------------------------------------------------------------------
    log("시장 국면 스냅샷 로딩...")
    regime_snap = get_latest_market_regime_snapshot()
    if regime_snap is not None:
        computed_at = regime_snap.get("computed_at")
        regime_snap_serializable = dict(regime_snap)
        regime_snap_serializable["computed_at"] = (
            computed_at.isoformat() if hasattr(computed_at, "isoformat") else str(computed_at)
        )
        result["market_regime"] = regime_snap_serializable
        log(f"  -> {regime_snap['regime']} (총점 {regime_snap['total_score']:.1f}, 기준일 {regime_snap_serializable['computed_at']})")
    else:
        result["market_regime"] = None
        log("  -> 스냅샷 없음")

    # ------------------------------------------------------------------
    # 2) 섹터/테마 강도 스냅샷 (core.sector_strength) — IBD 스타일 RS 점수, 이미 검증된 공식
    # ------------------------------------------------------------------
    log("섹터/테마 강도 스냅샷 로딩...")
    theme_snap = get_latest_theme_strength_snapshot()
    if theme_snap is not None:
        theme_df: pd.DataFrame = theme_snap["theme_scores"]
        computed_at = theme_snap.get("computed_at")
        result["theme_strength"] = {
            "computed_at": computed_at.isoformat() if hasattr(computed_at, "isoformat") else str(computed_at),
            "themes": theme_df.to_dict(orient="records"),
        }
        log(f"  -> {len(theme_df)}개 테마 로딩 완료, 1위: {theme_df.iloc[0]['theme']} (RS {theme_df.iloc[0]['rs_score']:.0f})")
    else:
        theme_df = pd.DataFrame()
        result["theme_strength"] = None
        log("  -> 스냅샷 없음")

    # ------------------------------------------------------------------
    # 3) 상위 테마 -> GICS 섹터 매핑 (스크리너 필터용, 중복 제거 후 상위 3개)
    # ------------------------------------------------------------------
    top_gics_sectors: list[str] = []
    top_themes_detail = []
    if not theme_df.empty:
        for _, row in theme_df.iterrows():
            gics = THEME_TO_GICS.get(row["theme"])
            top_themes_detail.append({"theme": row["theme"], "rs_score": row["rs_score"], "gics_sector": gics})
            if gics and gics not in top_gics_sectors:
                top_gics_sectors.append(gics)
            if len(top_gics_sectors) >= 3:
                break
    result["hot_sectors_gics"] = top_gics_sectors
    result["theme_to_gics_top"] = top_themes_detail
    log(f"핫섹터(GICS 매핑, 중복제거 상위3): {top_gics_sectors}")

    # ------------------------------------------------------------------
    # 4) 스크리닝 프레임워크 1단계 — core.screener.screen()으로 1차 필터
    #    (시총 상한 · 핫섹터 · 200일선 위 · PER 상한만 우선 적용, PBR은 상한 없음 — 지적자산 왜곡 논의 반영)
    # ------------------------------------------------------------------
    SCREEN_FILTERS = {
        "sectors": top_gics_sectors,
        "market_cap_max": 30_000_000_000,  # 300억 달러 이하 (S&P500 내에서 상대적 중소형 근사, 캐벗은 리포트에 명시)
        "per_max": 60,
        "above_sma200": True,
    }
    log(f"1단계 screen() 실행: {SCREEN_FILTERS}")
    screened = screen(filters=SCREEN_FILTERS, include_technicals=True)
    log(f"  -> 1단계 통과 {len(screened)}종목")
    result["screen_filters_stage1"] = SCREEN_FILTERS
    result["screen_stage1_results"] = screened.to_dict(orient="records")

    # ------------------------------------------------------------------
    # 5) 2단계 — PEG/ROE 프록시로 추가 필터 (core.valuation 재사용)
    #    PEG <= 1.5 (Lynch 기준보다 살짝 관대하게), 이익성장률 >= 15%, ROE 프록시 >= 15%
    # ------------------------------------------------------------------
    STAGE2_PEG_MAX = 1.5
    STAGE2_GROWTH_MIN_PCT = 15.0
    STAGE2_ROE_MIN_PCT = 15.0

    final_candidates = []
    for _, row in screened.iterrows():
        ticker = row["ticker"]
        try:
            vinputs = fetch_valuation_inputs(ticker)
        except Exception as e:
            log(f"  {ticker}: valuation 조회 실패 ({e})")
            continue

        per = vinputs.get("trailingPE")
        eps = vinputs.get("trailingEps")
        bvps = vinputs.get("bookValue")
        earnings_growth = vinputs.get("earningsGrowth")
        earnings_growth_pct = earnings_growth * 100 if earnings_growth is not None else None

        peg = peg_ratio(per, earnings_growth_pct)
        roe_proxy_pct = (eps / bvps * 100) if (eps and bvps and bvps > 0) else None

        passes = (
            peg is not None and peg <= STAGE2_PEG_MAX and peg > 0
            and earnings_growth_pct is not None and earnings_growth_pct >= STAGE2_GROWTH_MIN_PCT
            and roe_proxy_pct is not None and roe_proxy_pct >= STAGE2_ROE_MIN_PCT
        )
        if passes:
            final_candidates.append(
                {
                    "ticker": ticker,
                    "name": row.get("name"),
                    "sector": row.get("sector"),
                    "market_cap": row.get("market_cap"),
                    "per": per,
                    "pbr": row.get("pbr"),
                    "peg": peg,
                    "earnings_growth_pct": earnings_growth_pct,
                    "roe_proxy_pct": roe_proxy_pct,
                    "rsi": row.get("rsi"),
                    "above_sma200": row.get("above_sma200"),
                }
            )

    log(f"2단계(PEG<={STAGE2_PEG_MAX}, 성장률>={STAGE2_GROWTH_MIN_PCT}%, ROE프록시>={STAGE2_ROE_MIN_PCT}%) 통과: {len(final_candidates)}종목")
    result["screen_filters_stage2"] = {
        "peg_max": STAGE2_PEG_MAX,
        "earnings_growth_min_pct": STAGE2_GROWTH_MIN_PCT,
        "roe_proxy_min_pct": STAGE2_ROE_MIN_PCT,
    }
    final_candidates.sort(key=lambda r: (r["peg"] if r["peg"] is not None else 999))
    result["final_candidates"] = final_candidates

    # ------------------------------------------------------------------
    # 6) 유니버스 메타 정보
    # ------------------------------------------------------------------
    universe = get_universe()
    result["meta"]["universe_size"] = len(universe)
    result["meta"]["universe_source"] = "S&P500 (core.screener.get_universe, 위키피디아 캐시)"

    out_path = OUT_DIR / "report_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    log(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
