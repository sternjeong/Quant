"""에이전트 토큰 예산 (설계 4.2절) — 역할별 모델·턴·시간·주간 횟수, 하룻밤/주간 비용 상한, 사용 기록.

비용 단위는 Claude CLI(`--output-format json`)가 보고하는 total_cost_usd(API 환산 금액)다. 구독 요금제에서는 실제 청구액이
아니라 '사용량 한도를 얼마나 쓰는지'의 대리 지표로 쓴다. 값이 없으면 역할별 추정값(EST_COST_USD)으로 센다.

설정 근거(2026-09-25 결정, 사용자가 '적당히' 위임):
- 주간 $60 ≈ Writer 3회×$4 + Critic 14회×$1.5 + Implementer 12회×$1.5 + Scout 7회×$0.2 + Post-mortem 1회×$1 ≈ $53 + 여유.
- 하룻밤 $15: Writer 가 도는 밤(월·수·금)에 전체 사이클(Writer→Implementer→Critic)을 한 번 돌 수 있는 크기.
- 비싼 모델(Opus)은 가설 작성(Writer)과 코드 검증(Critic)에만. 코드 작성은 Sonnet, 수집은 Haiku.
- 03:00 KST 시작, 05:30 이후 새 작업 금지, 05:50 강제 종료 — 06:10 paper 자동 주문·사용자 아침 사용과 겹치지 않게.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USAGE_LOG = PROJECT_ROOT / "data" / "agent_usage.jsonl"
KST = timezone(timedelta(hours=9))

NIGHTLY_CAP_USD = 15.0
WEEKLY_CAP_USD = 60.0
BATCH_START = time(3, 0)
LAST_LAUNCH = time(5, 30)
HARD_STOP = time(5, 50)


@dataclass(frozen=True)
class RoleConfig:
    model: str
    max_turns: int
    timeout_sec: int
    weekly_runs: int
    est_cost_usd: float
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)  # KST 요일(월=0)


ROLES: dict[str, RoleConfig] = {
    "scout": RoleConfig("haiku", 12, 15 * 60, 7, 0.2),
    "writer": RoleConfig("opus", 25, 30 * 60, 3, 4.0, weekdays=(0, 2, 4)),
    "implementer": RoleConfig("sonnet", 40, 30 * 60, 12, 1.5),
    "critic": RoleConfig("opus", 15, 20 * 60, 14, 1.5),
    "postmortem": RoleConfig("sonnet", 15, 20 * 60, 1, 1.0, weekdays=(6,)),
}


# 역할별 모델은 사람이 수시로 바꿀 수 있다(허브 /research 드롭다운, 텔레그램 /models). 바꾼 값은 이 파일에 저장되고
# 다음 에이전트 실행부터 적용된다. 파일이 없거나 값이 잘못되면 ROLES 의 기본 모델을 쓴다.
MODEL_OVERRIDES = PROJECT_ROOT / "data" / "agent_models.json"
MODEL_CHOICES = ("haiku", "sonnet", "opus")
# 비용 추정용 상대 단가(sonnet=1). CLI 가 실제 금액을 보고하면 그 값을 쓴다.
MODEL_COST_FACTOR = {"haiku": 0.25, "sonnet": 1.0, "opus": 2.5}


def model_overrides() -> dict[str, str]:
    try:
        raw = json.loads(MODEL_OVERRIDES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for role, v in (raw.items() if isinstance(raw, dict) else []):
        m = v.get("model") if isinstance(v, dict) else v
        if role in ROLES and m in MODEL_CHOICES:
            out[role] = m
    return out


def set_model(role: str, model: str, actor: str = "hub") -> None:
    if role not in ROLES or model not in MODEL_CHOICES:
        raise ValueError(f"잘못된 역할/모델: {role}/{model}")
    try:
        raw = json.loads(MODEL_OVERRIDES.read_text(encoding="utf-8"))
        raw = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        raw = {}
    raw[role] = {"model": model, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "actor": actor}
    MODEL_OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_OVERRIDES.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MODEL_OVERRIDES)


def effective(role: str) -> RoleConfig:
    """사람이 고른 모델을 반영한 역할 설정. 추정 비용도 모델 단가 비율로 조정한다."""
    base = ROLES[role]
    model = model_overrides().get(role, base.model)
    if model == base.model:
        return base
    est = base.est_cost_usd * MODEL_COST_FACTOR[model] / MODEL_COST_FACTOR.get(base.model, 1.0)
    return RoleConfig(model, base.max_turns, base.timeout_sec, base.weekly_runs, round(est, 3), base.weekdays)


def kst(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(KST)


def week_start_kst(now: Optional[datetime] = None) -> datetime:
    k = kst(now)
    return (k - timedelta(days=k.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def batch_day_start(now: Optional[datetime] = None) -> datetime:
    """이번 배치(오늘 03:00 KST)의 시작 — 하룻밤 합계의 기준."""
    k = kst(now)
    return k.replace(hour=BATCH_START.hour, minute=BATCH_START.minute, second=0, microsecond=0)


def read_usage(path: Optional[Path] = None) -> list[dict]:
    path = path or USAGE_LOG
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def record(entry: dict, path: Optional[Path] = None) -> None:
    path = path or USAGE_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _cost(e: dict) -> float:
    c = e.get("cost_usd")
    if isinstance(c, (int, float)):
        return float(c)
    base = ROLES.get(e.get("role"), ROLES["implementer"])
    model = e.get("model") or base.model
    return base.est_cost_usd * MODEL_COST_FACTOR.get(model, 1.0) / MODEL_COST_FACTOR.get(base.model, 1.0)


def summary(now: Optional[datetime] = None, path: Optional[Path] = None) -> dict:
    rows = read_usage(path)
    wk, night = week_start_kst(now), batch_day_start(now)
    week_rows = [r for r in rows if datetime.fromisoformat(r["at"]) >= wk]
    night_rows = [r for r in rows if datetime.fromisoformat(r["at"]) >= night]
    runs = {role: sum(1 for r in week_rows if r.get("role") == role) for role in ROLES}
    return {"week_cost": sum(map(_cost, week_rows)), "night_cost": sum(map(_cost, night_rows)), "week_runs": runs,
            "weekly_cap": WEEKLY_CAP_USD, "nightly_cap": NIGHTLY_CAP_USD, "limit_hits_week": sum(1 for r in week_rows if r.get("limited"))}


def can_launch(role: str, now: Optional[datetime] = None, path: Optional[Path] = None) -> tuple[bool, str]:
    cfg = effective(role)
    k = kst(now)
    if k.weekday() not in cfg.weekdays:
        return False, f"{role}: 오늘은 실행 요일 아님"
    if not (BATCH_START <= k.time() < LAST_LAUNCH):
        return False, "새 작업 시작 가능 시간(03:00~05:30 KST) 밖"
    s = summary(now, path)
    if s["week_runs"][role] >= cfg.weekly_runs:
        return False, f"{role}: 주간 {cfg.weekly_runs}회 소진"
    if s["week_cost"] + cfg.est_cost_usd > WEEKLY_CAP_USD:
        return False, f"주간 예산 ${WEEKLY_CAP_USD:.0f} 도달(사용 ${s['week_cost']:.2f})"
    if s["night_cost"] + cfg.est_cost_usd > NIGHTLY_CAP_USD:
        return False, f"하룻밤 예산 ${NIGHTLY_CAP_USD:.0f} 도달(사용 ${s['night_cost']:.2f})"
    return True, "ok"


def seconds_until_hard_stop(now: Optional[datetime] = None) -> float:
    k = kst(now)
    stop = k.replace(hour=HARD_STOP.hour, minute=HARD_STOP.minute, second=0, microsecond=0)
    return (stop - k).total_seconds()
