"""가설 스펙 v1 — 에이전트(또는 사람)가 쓰는 JSON 과 결정론 코드(심판·shadow) 사이의 계약.

docs/AGENTIC_QUANT_SYSTEM_DESIGN.md 2절. 스펙은 동결 후 수정할 수 없다. 고치려면 parent 를 가진 새 가설이 되며,
params_grid 의 조합 수가 그대로 시도 수(n_trials)로 누적된다 — 다중검정 보정(core.hypothesis_judge)의 근거.

신호 코드 계약(research/hypotheses/<id>/signal.py):
    def score(prices: dict[str, pd.DataFrame], as_of: pd.Timestamp, params: dict) -> dict[str, float]
prices 는 엔진이 as_of 종가까지 잘라서 넘긴다(Open/High/Low/Close/Volume). 미래 데이터는 인터페이스상 볼 수 없다.
점수가 높은 순으로 top_k 종목을 동일가중(종목당 max_weight 상한)으로 담는다. 양수·유한 점수만 후보가 된다.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

SPEC_VERSION = 1
ID_RE = re.compile(r"^H-\d{8}-\d{3}$")
UNIVERSE_TYPES = ("etf_core", "sp500_pit", "list")
REBALANCE = ("weekly", "monthly")
MAX_GRID = 8          # 한 가설이 소비할 수 있는 시도 수 상한
MAX_LIST_TICKERS = 200
MAX_WEIGHT_CAP = 0.25  # core.paper_execution.RiskLimits.max_position_weight 와 같다
MIN_START = date(2005, 1, 1)


class SpecError(ValueError):
    """스펙이 계약을 어겼다. 메시지는 사람이 읽을 사유 목록."""


def _date(value: Any, field: str, errors: list[str]) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        errors.append(f"{field}: YYYY-MM-DD 형식이 아님")
        return None


def validate(spec: dict) -> dict:
    """계약을 검사하고 정규화한 사본을 돌려준다. 위반이 있으면 SpecError(모든 사유를 한 번에)."""
    e: list[str] = []
    if not isinstance(spec, dict):
        raise SpecError("스펙이 JSON 객체가 아님")
    sid = spec.get("id", "")
    if not ID_RE.match(str(sid)):
        e.append("id: H-YYYYMMDD-NNN 형식이어야 함")
    if spec.get("parent") is not None and not ID_RE.match(str(spec["parent"])):
        e.append("parent: H-YYYYMMDD-NNN 형식이어야 함")
    thesis = str(spec.get("thesis") or "").strip()
    if not thesis or len(thesis) > 500:
        e.append("thesis: 1~500자 필요")
    if not str(spec.get("source") or "").strip():
        e.append("source: 필요")

    uni = spec.get("universe") or {}
    if uni.get("type") not in UNIVERSE_TYPES:
        e.append(f"universe.type: {UNIVERSE_TYPES} 중 하나")
    if uni.get("type") == "list":
        tickers = uni.get("tickers") or []
        if not (1 <= len(tickers) <= MAX_LIST_TICKERS) or not all(isinstance(t, str) and t.strip() for t in tickers):
            e.append(f"universe.tickers: 1~{MAX_LIST_TICKERS}개 문자열")

    grid = (spec.get("signal") or {}).get("params_grid")
    if not isinstance(grid, list) or not (1 <= len(grid) <= MAX_GRID) or not all(isinstance(g, dict) for g in grid):
        e.append(f"signal.params_grid: 1~{MAX_GRID}개의 객체 목록")

    pf = spec.get("portfolio") or {}
    top_k = pf.get("top_k")
    if not isinstance(top_k, int) or not (1 <= top_k <= 50):
        e.append("portfolio.top_k: 1~50 정수")
    if pf.get("rebalance") not in REBALANCE:
        e.append(f"portfolio.rebalance: {REBALANCE} 중 하나")
    mw = pf.get("max_weight", MAX_WEIGHT_CAP)
    if not isinstance(mw, (int, float)) or not (0 < mw <= MAX_WEIGHT_CAP):
        e.append(f"portfolio.max_weight: 0 초과 {MAX_WEIGHT_CAP} 이하")

    period = spec.get("period") or {}
    start = _date(period.get("start"), "period.start", e) if period.get("start") else None
    if start is None and "period.start: YYYY-MM-DD 형식이 아님" not in e:
        e.append("period.start: 필요")
    elif start and start < MIN_START:
        e.append(f"period.start: {MIN_START} 이후")
    if period.get("end"):
        end = _date(period["end"], "period.end", e)
        if start and end and end <= start:
            e.append("period.end: start 이후여야 함")

    kill = spec.get("kill_criteria") or {}
    if not isinstance(kill.get("min_rebalances"), int) or kill["min_rebalances"] < 12:
        e.append("kill_criteria.min_rebalances: 12 이상 정수")
    mdd = kill.get("max_drawdown")
    if not isinstance(mdd, (int, float)) or not (0 < mdd < 1):
        e.append("kill_criteria.max_drawdown: 0~1 사이 비율")
    if e:
        raise SpecError("; ".join(e))

    out = json.loads(json.dumps(spec))
    out["spec_version"] = SPEC_VERSION
    out["portfolio"]["max_weight"] = float(mw)
    if uni.get("type") == "list":
        out["universe"]["tickers"] = sorted({t.strip().upper() for t in uni["tickers"]})
    return out


def n_trials(spec: dict) -> int:
    return len(spec["signal"]["params_grid"])


def spec_hash(spec: dict, signal_code: str = "") -> str:
    blob = json.dumps(spec, sort_keys=True, ensure_ascii=False) + "\n--signal--\n" + signal_code
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
