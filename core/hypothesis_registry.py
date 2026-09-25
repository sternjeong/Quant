"""가설 레지스트리 — 상태 전이·시도 카운터·동결/shadow 상한 (설계 S1, docs/AGENTIC_QUANT_SYSTEM_DESIGN.md 3.1절).

상태: draft → frozen → judged_pass | judged_fail → shadow → promotion_candidate → promoted_paper | retired
      (draft 는 abandoned 로도 끝날 수 있다)
- 되돌리는 전이는 없다. 허용되지 않은 전이는 TransitionError.
- 동결 시 스펙과 신호 코드 원문을 DB 에 복사한다. 이후 심판·shadow 는 파일이 아니라 이 동결본만 쓴다.
- 누적 시도 수 = 한 번이라도 동결된 모든 가설의 n_trials 합. 실패·폐기돼도 줄지 않는다(다중검정 보정의 N).
- 주간 동결 상한(KST ISO 주 기준) WEEKLY_FREEZE_CAP, shadow 동시 상한 SHADOW_CAP.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

from core import hypothesis_spec as hs
from core.models import Hypothesis, HypothesisEvent

WEEKLY_FREEZE_CAP = 10
SHADOW_CAP = 20
KST = timezone(timedelta(hours=9))

DRAFT, FROZEN, PASS, FAIL = "draft", "frozen", "judged_pass", "judged_fail"
SHADOW, CANDIDATE, PROMOTED, RETIRED, ABANDONED = "shadow", "promotion_candidate", "promoted_paper", "retired", "abandoned"
TRANSITIONS = {
    DRAFT: {FROZEN, ABANDONED},
    FROZEN: {PASS, FAIL},
    PASS: {SHADOW, RETIRED},
    SHADOW: {CANDIDATE, RETIRED},
    CANDIDATE: {PROMOTED, RETIRED},
    PROMOTED: {RETIRED},
}
FROZEN_STATES = {FROZEN, PASS, FAIL, SHADOW, CANDIDATE, PROMOTED, RETIRED}


class TransitionError(RuntimeError):
    pass


class CapReached(RuntimeError):
    pass


@contextmanager
def _session(session=None) -> Iterator[Any]:
    if session is not None:
        yield session
        session.commit()
        return
    from core.db import get_session, init_db

    init_db()
    with get_session() as db:
        yield db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _kst_week_start(now_utc_naive: datetime) -> datetime:
    kst = now_utc_naive.replace(tzinfo=timezone.utc).astimezone(KST)
    monday = (kst - timedelta(days=kst.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.astimezone(timezone.utc).replace(tzinfo=None)


def _move(db, hyp: Hypothesis, to: str, note: str = "", now: Optional[datetime] = None) -> None:
    if to not in TRANSITIONS.get(hyp.status, set()):
        raise TransitionError(f"{hyp.id}: {hyp.status} → {to} 는 허용되지 않음")
    db.add(HypothesisEvent(hypothesis_id=hyp.id, from_status=hyp.status, to_status=to, note=note[:2000],
                           at=now or _utcnow()))
    hyp.status = to
    hyp.updated_at = now or _utcnow()


def register_draft(spec: dict, *, session=None, now: Optional[datetime] = None) -> str:
    """스펙을 검증해 draft 로 등록한다. 같은 id 가 이미 있으면 draft 일 때만 스펙을 갱신한다."""
    clean = hs.validate(spec)
    with _session(session) as db:
        hyp = db.get(Hypothesis, clean["id"])
        if hyp is not None and hyp.status != DRAFT:
            raise TransitionError(f"{hyp.id}: 이미 {hyp.status} — 동결 후에는 스펙을 바꿀 수 없음(새 가설로 등록)")
        payload = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        if hyp is None:
            hyp = Hypothesis(id=clean["id"], parent_id=clean.get("parent"), source=clean["source"], status=DRAFT,
                             spec_json=payload, n_trials=hs.n_trials(clean), created_at=now or _utcnow(),
                             updated_at=now or _utcnow())
            db.add(hyp)
            db.add(HypothesisEvent(hypothesis_id=hyp.id, from_status=None, to_status=DRAFT, note="registered",
                                   at=now or _utcnow()))
        else:
            hyp.spec_json, hyp.n_trials, hyp.updated_at = payload, hs.n_trials(clean), now or _utcnow()
        return hyp.id


def frozen_this_week(db, now: Optional[datetime] = None) -> int:
    start = _kst_week_start(now or _utcnow())
    return db.query(Hypothesis).filter(Hypothesis.frozen_at.isnot(None), Hypothesis.frozen_at >= start).count()


def freeze(hyp_id: str, signal_code: str, *, session=None, now: Optional[datetime] = None) -> dict:
    """draft 를 동결한다(스펙+코드 복사, 해시 기록). 주간 상한을 넘으면 CapReached."""
    now = now or _utcnow()
    with _session(session) as db:
        hyp = db.get(Hypothesis, hyp_id)
        if hyp is None:
            raise KeyError(hyp_id)
        if frozen_this_week(db, now) >= WEEKLY_FREEZE_CAP:
            raise CapReached(f"이번 주 동결 {WEEKLY_FREEZE_CAP}개 상한 도달")
        spec = json.loads(hyp.spec_json)
        _move(db, hyp, FROZEN, "frozen", now)
        hyp.signal_code = signal_code
        hyp.spec_hash = hs.spec_hash(spec, signal_code)
        hyp.frozen_at = now
        return {"id": hyp.id, "spec_hash": hyp.spec_hash, "n_trials": hyp.n_trials}


def transition(hyp_id: str, to: str, note: str = "", *, session=None, now: Optional[datetime] = None,
               judge: Optional[dict] = None) -> None:
    with _session(session) as db:
        hyp = db.get(Hypothesis, hyp_id)
        if hyp is None:
            raise KeyError(hyp_id)
        if to == SHADOW and db.query(Hypothesis).filter(Hypothesis.status == SHADOW).count() >= SHADOW_CAP:
            raise CapReached(f"shadow 동시 {SHADOW_CAP}개 상한 도달")
        _move(db, hyp, to, note, now)
        if judge is not None:
            hyp.judge_json = json.dumps(judge, ensure_ascii=False, default=str)


def cumulative_trials(db) -> int:
    rows = db.query(Hypothesis.n_trials).filter(Hypothesis.status.in_(FROZEN_STATES)).all()
    return int(sum(r[0] or 0 for r in rows))


def get(hyp_id: str, *, session=None) -> Optional[dict]:
    with _session(session) as db:
        hyp = db.get(Hypothesis, hyp_id)
        return _as_dict(hyp) if hyp else None


def list_by_status(*statuses: str, session=None) -> list[dict]:
    with _session(session) as db:
        q = db.query(Hypothesis)
        if statuses:
            q = q.filter(Hypothesis.status.in_(statuses))
        return [_as_dict(h) for h in q.order_by(Hypothesis.created_at).all()]


def funnel(*, session=None, now: Optional[datetime] = None) -> dict:
    with _session(session) as db:
        counts: dict[str, int] = {}
        for (status,) in db.query(Hypothesis.status).all():
            counts[status] = counts.get(status, 0) + 1
        return {"counts": counts, "cumulative_trials": cumulative_trials(db),
                "frozen_this_week": frozen_this_week(db, now), "weekly_freeze_cap": WEEKLY_FREEZE_CAP,
                "shadow_cap": SHADOW_CAP}


def recent_events(limit: int = 20, *, session=None) -> list[dict]:
    with _session(session) as db:
        rows = db.query(HypothesisEvent).order_by(HypothesisEvent.at.desc(), HypothesisEvent.id.desc()).limit(limit).all()
        return [{"id": r.hypothesis_id, "from": r.from_status, "to": r.to_status, "note": r.note, "at": r.at} for r in rows]


def _as_dict(h: Hypothesis) -> dict:
    return {"id": h.id, "parent_id": h.parent_id, "source": h.source, "status": h.status,
            "spec": json.loads(h.spec_json), "signal_code": h.signal_code, "spec_hash": h.spec_hash,
            "n_trials": h.n_trials, "judge": json.loads(h.judge_json) if h.judge_json else None,
            "created_at": h.created_at, "frozen_at": h.frozen_at, "updated_at": h.updated_at}
