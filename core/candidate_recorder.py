"""shadow 후보 원장을 실제 후보 생성 흐름에 '관측 전용'으로 연결하는 스케줄 잡 어댑터.

core/candidate_ledger.py(RES-01, docs/CANDIDATE_LEDGER_SPEC.md)는 진입/청산/비용/PIT 규칙과 지표를
갖고 있지만, 실제 후보를 기록하는 호출부가 없었다. 이 모듈이 그 호출부다.

설계 원칙(중요):
    - Streamlit 페이지 렌더링 시점이 아니라 스케줄된 잡에서만 기록한다. 페이지를 열 때마다 기록하면
      같은 날 같은 후보가 여러 번 "관측"된 것처럼 보여 표본이 오염된다(하루 1회 스냅샷이 원장의 전제).
    - 원전략 함수(core.stock_discovery, core.sector_leaders, core.champion_strategy)는 이 모듈이
      읽기만 하고 수정하지 않는다. 주문 경로(core.paper_execution, scripts/champion_paper_trade.py)는
      import 도 호출도 하지 않는다 — tests/test_candidate_recorder.py 의 소스 검사가 이를 강제한다.
    - 세 소스(stock_discovery, sector_leaders, champion_satellite) 중 하나가 실패해도 나머지는
      계속 기록한다. 각 소스의 성공/실패와 사유는 반환 dict 에 남는다.
    - 시간 계약을 지어내지 않는다. 가격·재무 기반 후보(stock_discovery, sector_leaders)는
      source_publication 이 없으므로 decision_cutoff(=잡 실행 시각)만 채우고 나머지 4개 시간 필드는
      비워 둔다 — 그 결과 core.candidate_ledger.compute_pit_status 가 pit_certified=False 를 매기고,
      core.candidate_ledger.decide_verdict 는 이 사실만으로 항상 '미입증'을 반환한다(원장 규칙 그대로,
      이 모듈이 규칙을 우회하지 않는다). 이 잡은 성과나 승률 개선을 계산하거나 주장하지 않는다.
    - stock_discovery 는 as_of_date 시점 재무·가격이 아니라 현재 스냅샷이므로 df.attrs["meta"]의
      pit_verified=False 가 그대로 후보 집합 meta 에 보존된다(어댑터가 이미 하는 일이며, 이 모듈은 그
      값을 바꾸지 않는다).

배포 시 유의: 이 잡은 스케줄러의 candidate_ledger_record_job(매일 00:27 KST)으로 등록돼 있어, VM 에서는 매일 밤
CandidateBatch/CandidateDecision 행이 실제 운영 DB(core.db)에 쓰인다. Codespace 단위 테스트에서는 임시 SQLite 세션만 쓴다.
"""

from __future__ import annotations

import traceback
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

from core.candidate_ledger import (
    FrozenCandidateSet,
    champion_satellite_to_candidate_set,
    record_candidate_set,
    sector_leaders_to_candidate_set,
    stock_discovery_to_candidate_set,
)

# 원전략 기본값과 별개로, 원장이 "전체 후보"를 채택/보류/거절로 나눠 기록하려면 채택 개수보다
# 넉넉한 후보 풀이 필요하다. discover_candidates 기본 top_n(30)은 상위만 자르므로 여기서는 더
# 크게 잡는다. S&P500 전체(500+)를 매일 스캔하면 비용이 크므로 기본값은 타협값이며, 실제 채택 수
# (STOCK_DISCOVERY_SELECTED_N)보다 훨씬 큰 held 표본을 남기는 데 목적이 있다.
STOCK_DISCOVERY_POOL_N = 100
STOCK_DISCOVERY_SELECTED_N = 10
STOCK_DISCOVERY_STRATEGY_VERSION = "stock_discovery_sector_rank_v2"
SECTOR_LEADERS_STRATEGY_VERSION = "sector_leaders_v2"
CHAMPION_SATELLITE_SOURCE_STRATEGY_PREFIX = "champion_satellite"


def _now_utc_naive() -> datetime:
    return datetime.utcnow()


def _cutoff_for(as_of: date) -> datetime:
    """가격·재무 기반 후보의 decision_cutoff. 그 날의 장 마감 이후로 본다(잡은 장 마감 후 실행).

    core.candidate_ledger.normalize_time 이 날짜만 받으면 그 날 23:59:59(미 동부, 장 마감 후)로
    해석하는 관례를 그대로 따른다 — 여기서 시각을 직접 지어내지 않고 날짜만 넘긴다.
    """
    return datetime.combine(as_of, datetime.min.time())


def _record_stock_discovery(as_of: date, session=None) -> dict:
    """core.stock_discovery.discover_candidates 결과를 전량 기록한다."""
    from core.stock_discovery import discover_candidates

    df = discover_candidates(top_n=STOCK_DISCOVERY_POOL_N, as_of_date=as_of.isoformat())
    cset = stock_discovery_to_candidate_set(
        df, strategy_version=STOCK_DISCOVERY_STRATEGY_VERSION, decision_cutoff=_cutoff_for(as_of),
        selected_n=STOCK_DISCOVERY_SELECTED_N,
    )
    result = record_candidate_set(cset, session=session)
    result["n_pool"] = len(cset.records)
    return result


def _record_sector_leaders(as_of: date, themes: Optional[list[str]] = None, session=None) -> dict:
    """core.sector_leaders.compute_leader_and_growth 결과를 테마별로 기록한다.

    compute_leader_and_growth 는 후보 풀(테마 내 전체 종목) 자체를 반환하지 않으므로,
    get_theme_candidate_tickers 로 티커 목록만 pool 로 넘긴다 — 점수 없이 held/missing_data 로만
    구분되며, 어댑터가 leader/growth_stocks 항목의 growth_data_missing 여부로 missing_data 를
    가려낸다(docs/CANDIDATE_LEDGER_SPEC.md 참고).
    """
    from core.sector_leaders import compute_leader_and_growth, get_theme_candidate_tickers
    from core.sector_strength import THEME_UNIVERSE

    theme_list = themes if themes is not None else list(THEME_UNIVERSE.keys())
    per_theme: dict[str, Any] = {}
    n_batches, n_inserted, n_conflict, errors = 0, 0, 0, []
    for theme in theme_list:
        try:
            result = compute_leader_and_growth(theme)
            pool = get_theme_candidate_tickers(theme)
            cset = sector_leaders_to_candidate_set(
                result, strategy_version=SECTOR_LEADERS_STRATEGY_VERSION, decision_cutoff=_cutoff_for(as_of),
                pool=pool,
            )
            rec = record_candidate_set(cset, session=session)
            per_theme[theme] = {**rec, "n_pool": len(cset.records)}
            n_batches += 1
            n_inserted += 1 if rec["inserted"] else 0
            n_conflict += 1 if rec["conflict"] else 0
        except Exception as exc:  # noqa: BLE001 - 테마 하나 실패가 나머지를 막지 않는다
            per_theme[theme] = {"error": f"{type(exc).__name__}: {exc}"}
            errors.append(theme)
    return {
        "themes_attempted": len(theme_list), "themes_recorded": n_batches, "inserted": n_inserted,
        "conflict": n_conflict, "errors": errors, "per_theme": per_theme,
    }


def _record_champion_satellite(as_of: date, session=None) -> dict:
    """core.champion_strategy.compute_satellite_recommendation_point_in_time 결과를 기록한다.

    라이브 스캔(compute_satellite_recommendation)이 아니라 point-in-time 버전을 쓴다 — 백테스트가
    실제로 검증한 방법론과 같은 함수이고, new_orders_allowed=False(데이터 부족) 를 반환해 어댑터가
    채택을 조용히 청산 대신 held 로 기록하게 한다(ENG-03 규칙과 동일).
    """
    from core.champion_strategy import compute_satellite_recommendation_point_in_time

    result = compute_satellite_recommendation_point_in_time(as_of_date=as_of.isoformat())
    strategy_version = f"{CHAMPION_SATELLITE_SOURCE_STRATEGY_PREFIX}/{result.get('sizing_method', 'equal')}"
    cset = champion_satellite_to_candidate_set(
        result, strategy_version=strategy_version, decision_cutoff=_cutoff_for(as_of),
    )
    rec = record_candidate_set(cset, session=session)
    rec["n_pool"] = len(cset.records)
    rec["new_orders_allowed"] = result.get("new_orders_allowed")
    return rec


def record_daily_candidates(
    as_of: Optional[date] = None, *, session=None, sector_themes: Optional[list[str]] = None,
) -> dict:
    """세 소스(stock_discovery, sector_leaders, champion_satellite)의 오늘 후보를 원장에 동결 기록한다.

    소스 하나가 예외를 내도 나머지는 계속 진행한다. 같은 날 재실행은 멱등하다(candidate_set_id 가
    이미 있으면 record_candidate_set 이 아무것도 바꾸지 않는다 — core.candidate_ledger 문서 참고).

    Returns:
        {"as_of", "sources": {"stock_discovery": {...} | {"error": ...}, "sector_leaders": {...}, ...},
         "ok": bool(하나 이상 성공)}
    """
    as_of_date = as_of or date.today()
    sources: dict[str, Any] = {}
    for name, fn in (
        ("stock_discovery", lambda: _record_stock_discovery(as_of_date, session=session)),
        ("sector_leaders", lambda: _record_sector_leaders(as_of_date, themes=sector_themes, session=session)),
        ("champion_satellite", lambda: _record_champion_satellite(as_of_date, session=session)),
    ):
        try:
            sources[name] = fn()
        except Exception as exc:  # noqa: BLE001 - 한 소스의 실패가 나머지 기록을 막지 않는다
            sources[name] = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(limit=3)}
    def _source_ok(v: dict) -> bool:
        if "error" in v:
            return False
        if "themes_attempted" in v:  # sector_leaders: 테마별 부분 실패를 감안해 1개 이상 기록됐어야 성공
            return v.get("themes_recorded", 0) > 0
        return True

    return {
        "as_of": as_of_date.isoformat(),
        "sources": sources,
        "ok": any(_source_ok(v) for v in sources.values()),
    }


def summarize_recording(result: dict) -> str:
    """record_daily_candidates 결과를 사람이 읽는 한 줄 요약으로 바꾼다(로그/알림용)."""
    parts = []
    for name, v in result.get("sources", {}).items():
        if "error" in v:
            parts.append(f"{name}=ERROR({v['error']})")
        elif name == "sector_leaders":
            parts.append(f"{name}=themes:{v.get('themes_recorded')}/{v.get('themes_attempted')}")
        else:
            parts.append(f"{name}=pool:{v.get('n_pool')},inserted:{v.get('inserted')}")
    return f"[candidate_recorder] {result.get('as_of')} " + " ".join(parts)
