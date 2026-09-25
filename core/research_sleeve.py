"""research 슬리브 — 사람이 승격(promoted_paper)한 가설을 paper 계좌에 소액으로 편입한다(설계 S6).

목표 비중 = 가설별 배분 × 그 가설의 최신 shadow 비중(core.hypothesis_shadow 가 매일 기록, 승격 뒤에도 계속 기록).
- 슬리브 전체 SLEEVE_FRACTION(10%), 가설당 PER_HYPOTHESIS_MAX(5%). 가설이 n 개면 가설당 min(5%, 10%/n).
- 챔피언(core+satellite) 목표는 (1 − research 사용분)으로 줄여 전체가 100% 를 넘지 않게 한다.
  승격 가설이 없으면 research 목표는 비어 있고 챔피언 계획은 도입 전과 같다(core.paper_execution 의 None 경로).
- fail-closed: 승격 가설 중 하나라도 최신 기록이 STALE_DAYS(5일)보다 오래됐거나 비중을 읽을 수 없으면 슬리브 전체를
  보류한다(research 신규 매수 없음, 보유 유지). 보류는 매도 명령이 아니다.
- 종료(retired)된 가설의 종목은 research 목표에서 빠지고, 챔피언 목표에도 없으면 기존 위성 규칙에 따라 정리된다.
이 모듈은 주문을 내지 않는다. 목표만 만들고 제출은 기존 게이트(paper_auto_trade → submit_plan)가 한다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional

SLEEVE_FRACTION = 0.10
PER_HYPOTHESIS_MAX = 0.05
STALE_DAYS = 5


def compute_research_targets(*, session=None, today: Optional[date] = None) -> dict[str, Any]:
    from core import hypothesis_registry as reg
    from core.models import HypothesisShadowRecord

    today = today or date.today()
    promoted = reg.list_by_status(reg.PROMOTED, session=session)
    out: dict[str, Any] = {"targets": {}, "new_orders_allowed": True, "hold_reason": "", "hypotheses": []}
    if not promoted:
        return out
    per = min(PER_HYPOTHESIS_MAX, SLEEVE_FRACTION / len(promoted))
    stale = []
    with reg._session(session) as db:
        for h in promoted:
            rec = (db.query(HypothesisShadowRecord).filter(HypothesisShadowRecord.hypothesis_id == h["id"])
                   .order_by(HypothesisShadowRecord.as_of.desc()).first())
            if rec is None or (today - rec.as_of) > timedelta(days=STALE_DAYS):
                stale.append(h["id"])
                continue
            try:
                w = json.loads(rec.weights_json).get("w") or {}
            except ValueError:
                stale.append(h["id"])
                continue
            for sym, wt in w.items():
                out["targets"][sym] = out["targets"].get(sym, 0.0) + per * float(wt)
            out["hypotheses"].append({"id": h["id"], "allocation": per, "as_of": rec.as_of.isoformat(), "n_symbols": len(w)})
    if stale:
        return {"targets": {}, "new_orders_allowed": False, "hypotheses": out["hypotheses"],
                "hold_reason": f"승격 가설 최신 기록 없음/오래됨: {', '.join(stale)}"}
    return out
