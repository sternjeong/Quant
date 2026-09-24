"""백그라운드 프로세스/연구 잡을 사용자가 직관적으로 켜고 끌 수 있게 하는 중앙 레지스트리.

배경(2026-09-19): scheduler/run_scheduler.py의 야간 전략 미세튜닝(strategy_nightly_tuning_job)이
사용자가 요청한 적도, 알지도 못한 채로 계속 돌고 있었다 — 이전 세션이 자체적으로 만들어 넣은 기능을
사용자가 나중에야 알게 된 것. 이 모듈은 그런 일이 다시 일어나지 않도록, 스케줄러의 모든 야간 잡을
하나의 카탈로그(PROCESS_REGISTRY)로 모으고 각각의 on/off 상태를 사용자가 확인·변경할 수 있게 한다.

저장 방식이 SQLite(core.db)가 아니라 평범한 JSON 파일인 이유: deploy/codex_telegram/runner.py가
stdlib만 쓰는 독립 프로세스로 설계돼 있어(core/를 임포트하지 않음, 시스템 python3로 실행) 텔레그램
명령으로 잡을 켜고 끄려면 이 runner.py도 같은 상태를 읽고 써야 한다 — .experiment-control/
control.json이 이미 같은 이유로 JSON 파일을 쓰는 것과 동일한 패턴이다. runner.py 쪽에서는 이
모듈을 임포트하지 않고 아주 작은 read/write 헬퍼를 자기 파일 안에 똑같이 복제한다(core/
resource_guard.py 문서에 설명된 이 저장소의 기존 관례).

새 스케줄러 잡을 추가할 때는:
    1. PROCESS_REGISTRY에 항목 추가 (label/description/category/default_enabled)
    2. 잡 함수 맨 앞에 `if not is_enabled("그 키"): print(...); return` 추가
이 두 가지만 지키면 텔레그램 /processes 에 자동으로 나타나고 사용자가 끌 수 있다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOGGLE_STATE_PATH = PROJECT_ROOT / "data" / "process_toggles.json"

# category: "research"(연구/튜닝 — 결과가 쌓일 뿐 꺼도 당장 알림이 끊기지 않음),
#           "alert"(챔피언 전략 등 실사용 신호/알림 — 끄면 그 알림이 안 옴),
#           "maintenance"(캐시 예열/데이터 위생 — 끄면 다른 잡이 대신 그 자리에서 재계산을 떠안을 수 있음)
PROCESS_REGISTRY: dict[str, dict] = {
    "strategy_nightly_tuning": {
        "label": "야간 전략 미세튜닝",
        "description": "전략 라이브러리 #3(볼린저 밴드 하단 반전 1:2:6 전략)을 백본으로 00:05~04:00 KST 반복 미세튜닝",
        "category": "research",
        # 2026-09-19: 사용자가 요청한 적 없는 기능이었다는 게 밝혀져 기본값을 꺼짐으로 전환.
        "default_enabled": False,
    },
    "champion_signal_alert": {
        "label": "챔피언 전략 신호 변경 알림",
        "description": "코어 top4/시장필터/새틀라이트 보유종목이 바뀌면 텔레그램으로 알림 (00:10 KST)",
        "category": "alert", "default_enabled": True,
    },
    "champion_correlation_snapshot": {
        "label": "챔피언 전략 상관관계 스냅샷",
        "description": "보유종목 간 상관관계를 매일 이력으로 저장 (00:11 KST)",
        "category": "maintenance", "default_enabled": True,
    },
    "champion_ledger_record": {
        "label": "챔피언 전략 페이퍼 트레이딩 원장",
        "description": "추천 비중을 실제로 따랐다면의 실현수익률을 매일 누적 기록 (00:12 KST)",
        "category": "research", "default_enabled": True,
    },
    "champion_benchmark_gap": {
        "label": "챔피언 전략 벤치마크 격차 알림",
        "description": "페이퍼 트레이딩 원장이 60/40(SPY/TLT) 대비 크게 뒤처지면 텔레그램 알림 (00:13 KST)",
        "category": "alert", "default_enabled": True,
    },
    "champion_rebalance_reminder": {
        "label": "챔피언 전략 리밸런싱 예정 알림",
        "description": "코어/새틀라이트 리밸런싱일(및 칼라 헤지 롤 예정)을 하루 전 텔레그램 알림 (00:15 KST)",
        "category": "alert", "default_enabled": True,
    },
    "champion_earnings_reminder": {
        "label": "챔피언 전략 실적 발표 예정 알림",
        "description": "새틀라이트 보유종목 중 5거래일 이내 실적 발표가 있으면 텔레그램 알림 (00:16 KST)",
        "category": "alert", "default_enabled": True,
    },
    "champion_alpha_decay": {
        "label": "챔피언 전략 알파 감쇠 체크",
        "description": "전체기간 대비 최근 6개월 백테스트 성과 이탈 여부를 매일 확인 (00:18 KST)",
        "category": "alert", "default_enabled": True,
    },
    "fred_indicator_prewarm": {
        "label": "FRED 거시지표 캐시 예열",
        "description": "FRED 거시지표(환율 등) 캐시를 매일 미리 강제 갱신 (00:20 KST)",
        "category": "maintenance", "default_enabled": True,
    },
    "data_integrity_check": {
        "label": "데이터 무결성 체크",
        "description": "가격/FRED 캐시/뉴스 다이제스트 이상 감지 시 텔레그램 알림 (00:22 KST)",
        "category": "maintenance", "default_enabled": True,
    },
    "daily_briefing": {
        "label": "오늘의 브리핑",
        "description": "그날 밤 다른 모든 챔피언 전략 잡의 결과를 모은 HTML 요약을 텔레그램으로 전송 (00:25 KST)",
        "category": "alert", "default_enabled": True,
    },
    "champion_weekly_report": {
        "label": "챔피언 전략 주간 보고",
        "description": "매주 일요일 코어/새틀라이트 현황과 상관관계를 담은 HTML 보고 전송 (일 20:20 America/New_York)",
        "category": "alert", "default_enabled": True,
    },
    "market_snapshot": {
        "label": "시장 국면/섹터 강도 스냅샷",
        "description": "시장 국면·섹터 강도를 매일 미리 계산해 저장 (00:00 KST)",
        "category": "maintenance", "default_enabled": True,
    },
    "watchlist_scan": {
        "label": "관심종목 스캔",
        "description": "평일 장마감 후 관심종목 전략 조건 충족 여부 확인 (평일 16:30 America/New_York)",
        "category": "alert", "default_enabled": True,
    },
    "threads_weekly_report": {
        "label": "Threads 주간 인사이트",
        "description": "추적 중인 티커의 주간 AI 인사이트 리포트 생성 (일 20:00 America/New_York)",
        "category": "research", "default_enabled": True,
    },
    "daily_news_digest": {
        "label": "일일 뉴스 다이제스트",
        "description": "티커별 뉴스 요약 HTML/텔레그램 보고 (매일 07:30 KST)",
        "category": "alert", "default_enabled": True,
    },
    "candidate_ledger_record": {
        "label": "후보 shadow 원장 기록 (RES-01)",
        "description": (
            "발굴/섹터리더/새틀라이트 후보 전체(채택+보류+거절)를 관측 전용으로 동결 기록 — 주문에는 "
            "영향 없음, 성과·승률 개선을 아직 입증하지 않은 연구 인프라 (00:27 KST)"
        ),
        "category": "research", "default_enabled": True,
    },
    "candidate_ledger_outcome_update": {
        "label": "후보 shadow 원장 성과 채움 (RES-01)",
        "description": "이미 기록된 후보 판단의 만기 도래한 horizon 결과를 가격 캐시로 채움 (00:28 KST)",
        "category": "research", "default_enabled": True,
    },
}


def _load_state() -> dict:
    try:
        with open(TOGGLE_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    TOGGLE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOGGLE_STATE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(TOGGLE_STATE_PATH)


def is_enabled(key: str) -> bool:
    """key가 레지스트리에 없으면(오타/설계 누락 방지용) True로 본다 — 모르는 잡을 실수로 막지 않는다.

    저장된 상태가 없으면 PROCESS_REGISTRY의 default_enabled를 쓴다."""
    entry = PROCESS_REGISTRY.get(key)
    default = entry["default_enabled"] if entry else True
    state = _load_state()
    return bool(state.get(key, {}).get("enabled", default))


def set_enabled(key: str, enabled: bool, actor: Optional[str] = None) -> dict:
    """key의 on/off 상태를 저장한다. 알 수 없는 key면 ValueError(오타로 조용히 무시되는 것 방지)."""
    if key not in PROCESS_REGISTRY:
        raise ValueError(f"알 수 없는 프로세스: {key}")
    state = _load_state()
    state[key] = {
        "enabled": enabled,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
    }
    _save_state(state)
    return state[key]


def list_processes() -> list[dict]:
    """카탈로그 전체를 현재 상태와 합쳐 반환한다 (텔레그램 /processes 등에서 그대로 렌더링).

    Returns: [{"key", "label", "description", "category", "enabled", "updated_at"}, ...]
        PROCESS_REGISTRY에 정의된 순서를 그대로 유지한다.
    """
    state = _load_state()
    result = []
    for key, meta in PROCESS_REGISTRY.items():
        saved = state.get(key, {})
        result.append({
            "key": key,
            "label": meta["label"],
            "description": meta["description"],
            "category": meta["category"],
            "enabled": bool(saved.get("enabled", meta["default_enabled"])),
            "updated_at": saved.get("updated_at"),
        })
    return result
