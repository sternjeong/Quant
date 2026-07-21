"""전략 라이브러리 관리 (모듈 A 확장): 저장된 전략 조회/수정/삭제 공용 로직.

app/pages/1_전략_스튜디오.py의 "📊 지표 조합 백테스트"(조회/저장)와 "🗂️ 전략 관리"(목록/수정/삭제) 탭 양쪽에서
동일한 함수를 재사용한다. 전략 삭제 시 다른 테이블(backtest_results/watchlist/alerts_log)이
참조하는 데이터를 정리해 고아 레코드가 남지 않도록 한다 (SQLite는 기본적으로 FK를 강제하지
않으므로, 정합성은 애플리케이션 레벨에서 직접 챙긴다).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from core.db import get_session
from core.models import AlertLog, BacktestResult, Strategy, WatchlistItem
from core.strategy_engine import is_combined_config, is_expression_config, is_staged_config


def detect_strategy_type(indicator_config: str | dict) -> str:
    """indicator_config 의 JSON 형태만으로 전략 유형을 판별한다.

    Returns:
        "combined" (두 개 이상의 전략을 합성한 전략, combine+strategies 키 존재),
        "staged" (1:2:6 단계별 전략, entry_stages 키 존재), "expression" (직접 수식 전략,
        expression 키 존재) 또는 "regime" (일반 AND/OR 레짐 전략)
    """
    try:
        if is_combined_config(indicator_config):
            return "combined"
        if is_staged_config(indicator_config):
            return "staged"
        return "expression" if is_expression_config(indicator_config) else "regime"
    except (TypeError, ValueError, json.JSONDecodeError):
        return "regime"


def list_strategies(include_archived: bool = False) -> list[dict]:
    """전략 라이브러리 전체를 UI에 표시하기 좋은 dict 리스트로 반환한다 (최신 생성순).

    각 항목에는 연결된 관심종목 수 / 저장된 백테스트 결과 수도 함께 담아, 관리 화면에서
    삭제 전에 영향 범위를 미리 보여줄 수 있게 한다.

    include_archived=False(기본)면 보관(archive) 처리된 구버전 전략은 제외한다 - 백테스트/미세튜닝/
    전략 합성/관심종목 연결처럼 "지금 쓸 전략을 고르는" 화면에서 쓴다. 전략 관리 화면처럼 보관된
    것까지 다 보여줘야 하는 곳만 True로 호출한다.
    """
    with get_session() as session:
        query = session.query(Strategy)
        if not include_archived:
            query = query.filter(Strategy.is_archived.is_(False))
        rows = query.order_by(Strategy.created_at.desc()).all()
        result = []
        for s in rows:
            result.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "source": s.source or "",
                    "description": s.description or "",
                    "indicator_config": s.indicator_config,
                    "strategy_type": detect_strategy_type(s.indicator_config),
                    "is_archived": s.is_archived,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                    "watchlist_count": len(s.watchlist_items),
                    "backtest_result_count": len(s.backtest_results),
                }
            )
        return result


def get_strategy(strategy_id: int) -> Optional[dict]:
    """전략 1건을 조회한다. 없으면 None."""
    with get_session() as session:
        s = session.get(Strategy, strategy_id)
        if s is None:
            return None
        return {
            "id": s.id,
            "name": s.name,
            "source": s.source or "",
            "description": s.description or "",
            "indicator_config": s.indicator_config,
            "strategy_type": detect_strategy_type(s.indicator_config),
            "is_archived": s.is_archived,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "watchlist_count": len(s.watchlist_items),
            "backtest_result_count": len(s.backtest_results),
        }


def archive_strategy(strategy_id: int) -> None:
    """전략을 삭제하지 않고 보관(archive) 처리한다 - '활성 선택' 목록에서만 숨긴다.

    언제든 unarchive_strategy로 되돌릴 수 있다. 기존에 이 전략을 참조하는 관심종목/백테스트
    결과는 그대로 남아 계속 동작한다(archive는 신규 선택 목록에서만 제외하는 것이지 참조 무효화가
    아니다).
    """
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise ValueError(f"전략(id={strategy_id})을 찾을 수 없습니다.")
        strategy.is_archived = True


def unarchive_strategy(strategy_id: int) -> None:
    """보관 처리된 전략을 다시 활성 선택 목록으로 복원한다."""
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise ValueError(f"전략(id={strategy_id})을 찾을 수 없습니다.")
        strategy.is_archived = False


def validate_indicator_config(indicator_config: str) -> dict[str, Any]:
    """전략 관리 화면에서 JSON을 직접 수정할 때 저장 전 최소한의 유효성을 검증한다.

    문법 오류나 최상위 스키마 오류가 있으면 ValueError를 던진다. 반환값은 파싱된 dict.
    """
    try:
        config = json.loads(indicator_config)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {e}") from e

    if not isinstance(config, dict):
        raise ValueError("indicator_config는 JSON 객체(dict)여야 합니다.")

    _validate_config_schema(config)
    return config


def _validate_config_schema(config: dict) -> None:
    """indicator_config dict 하나의 스키마를 검증한다.

    복합(combine+strategies) 전략은 하위 전략마다 이 함수를 재귀적으로 다시 호출해 검증한다
    (하위 전략도 레짐/직접 수식/1:2:6 단계별/복합 어떤 스키마든 될 수 있으므로).
    """
    if "combine" in config or "strategies" in config:
        strategies = config.get("strategies")
        if not isinstance(strategies, list) or len(strategies) < 2:
            raise ValueError("strategies는 2개 이상의 하위 전략 설정을 담은 배열이어야 합니다.")
        if config.get("combine") not in ("AND", "OR"):
            raise ValueError("combine은 'AND' 또는 'OR'이어야 합니다.")
        for sub in strategies:
            if not isinstance(sub, dict):
                raise ValueError("strategies의 각 항목은 JSON 객체(dict)여야 합니다.")
            _validate_config_schema(sub)
    elif "entry_stages" in config:
        entry_stages = config.get("entry_stages")
        exit_stages = config.get("exit_stages")
        if not isinstance(entry_stages, list) or not entry_stages:
            raise ValueError("entry_stages는 1개 이상의 항목을 가진 배열이어야 합니다.")
        if not isinstance(exit_stages, list) or not exit_stages:
            raise ValueError("exit_stages는 1개 이상의 항목을 가진 배열이어야 합니다.")
        for stage in (*entry_stages, *exit_stages):
            if not isinstance(stage, dict) or "conditions" not in stage:
                raise ValueError("각 단계(stage)는 최소한 'conditions' 키를 가진 객체여야 합니다.")
    elif "expression" in config:
        from core.expression_engine import ExpressionError, validate_syntax

        expression = config.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("expression은 비어있지 않은 문자열이어야 합니다.")
        try:
            validate_syntax(expression)
        except ExpressionError as e:
            raise ValueError(f"수식 검증 실패: {e}") from e
    else:
        conditions = config.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise ValueError(
                "conditions는 1개 이상의 항목을 가진 배열이어야 합니다 "
                "(또는 entry_stages/expression/combine 스키마 사용)."
            )


def update_strategy(
    strategy_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    indicator_config: Optional[str] = None,
) -> None:
    """전략의 이름/설명/조건(JSON)을 수정한다.

    indicator_config 를 바꾸는 경우 validate_indicator_config 로 먼저 검증한다 (실패 시 ValueError).
    """
    if indicator_config is not None:
        validate_indicator_config(indicator_config)

    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise ValueError(f"전략(id={strategy_id})을 찾을 수 없습니다.")
        if name is not None:
            strategy.name = name
        if description is not None:
            strategy.description = description
        if indicator_config is not None:
            strategy.indicator_config = indicator_config


def delete_strategy(strategy_id: int) -> None:
    """전략을 삭제한다.

    연관 데이터 정리 방식:
    - backtest_results: 전략에 종속된 결과이므로 함께 삭제한다.
    - watchlist_items / alerts_log: 전략이 사라져도 의미가 있는 별도 개체(관심종목/알림 이력)이므로
      삭제하지 않고 strategy_id 를 NULL로 되돌려 고아 참조만 제거한다.
    """
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            return

        session.query(BacktestResult).filter(BacktestResult.strategy_id == strategy_id).delete()
        session.query(WatchlistItem).filter(WatchlistItem.strategy_id == strategy_id).update(
            {WatchlistItem.strategy_id: None}
        )
        session.query(AlertLog).filter(AlertLog.strategy_id == strategy_id).update(
            {AlertLog.strategy_id: None}
        )
        session.delete(strategy)
