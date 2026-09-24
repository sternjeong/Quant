"""Alpaca paper 계좌의 **실제** 보유 상태를 조회해 저장하고, 챔피언 전략의 목표 비중과 비교한다.

왜 필요한가
-----------
core.champion_strategy.record_daily_ledger_entry() 가 쌓는 원장은 "추천 비중을 그대로 따랐다면"의
가상 수익률이다. 실제 계좌가 그 목표와 얼마나 벌어져 있는지는 아무도 추적하지 않았다. 이 모듈은
그 간극만 메운다.

조회 전용이라는 계약
--------------------
- HTTP 는 GET 만 쓴다. 주문 생성·제출 코드는 이 모듈에 없으며, core.paper_execution 과
  scripts/champion_paper_trade.py 를 **import 하지도 않는다**(tests/test_account_sync.py 가 소스
  AST 로 강제한다).
- 리밸런싱이 필요한지 여부는 **정보로만** 계산한다. 이 모듈의 출력이 주문으로 이어지는 경로는 없다.
- API 키는 환경변수에서만 읽고, 값을 출력·로그·DB 에 남기지 않는다. 계좌번호도 저장하지 않는다.

보류(new_orders_allowed=False)를 0% 로 번역하지 않는다
------------------------------------------------------
챔피언 전략의 슬리브는 데이터가 모자라면 new_orders_allowed=False 로 "보류"하고 per_ticker_weights
를 비운다. 이 빈 목표를 "목표 비중 0%"로 읽으면 "전량 매도 필요"라는 정반대 결론이 나온다(ENG-03
에서 고친 것과 같은 결함). 그래서 보류 슬리브는 목표 0 이 아니라 **비교 불가(unknown)** 로 표시하고,
그 슬리브에 속할 수 있는 보유 종목은 이탈 계산에서 제외하며 회전 필요량도 부분값(partial)으로
표시한다.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

import requests

PAPER_ACCOUNT_BASE_URL = "https://paper-api.alpaca.markets"
SOURCE_ALPACA_PAPER = "alpaca_paper"

SLEEVE_CORE = "core"
SLEEVE_SATELLITE = "satellite"
SLEEVE_UNASSIGNED = "unassigned"

STATUS_COMPARABLE = "comparable"
STATUS_UNKNOWN = "unknown"

# Alpaca 는 분당 200 요청을 허용한다. 이 잡은 요청이 두 개뿐이지만, 사람이 스크립트를 연달아
# 돌려도 절대 한도에 닿지 않도록 요청 사이 최소 간격을 둔다.
MIN_REQUEST_INTERVAL_SEC = 0.35
REQUEST_TIMEOUT_SEC = 20
MAX_ATTEMPTS = 2  # 429/5xx/네트워크 오류 1회 재시도

# 이 %p 이상 벌어진 종목이 하나라도 있으면 "사람이 들여다볼 만하다"고 **알리기만** 한다.
DRIFT_ALERT_PCT_POINTS = 5.0

_last_request_at: float = 0.0


class MissingCredentialsError(RuntimeError):
    """ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET 가 환경변수에 없다."""


def credentials_available() -> bool:
    """키가 둘 다 있는지만 알려준다 — 값은 절대 반환하지 않는다."""
    return bool(os.getenv("ALPACA_PAPER_API_KEY")) and bool(os.getenv("ALPACA_PAPER_API_SECRET"))


def _auth_headers() -> dict[str, str]:
    key = os.getenv("ALPACA_PAPER_API_KEY", "")
    secret = os.getenv("ALPACA_PAPER_API_SECRET", "")
    if not key or not secret:
        raise MissingCredentialsError(
            "ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET 환경변수가 필요합니다 (값은 기록하지 않습니다)"
        )
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _throttle() -> None:
    global _last_request_at
    if MIN_REQUEST_INTERVAL_SEC > 0:
        wait = MIN_REQUEST_INTERVAL_SEC - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
    _last_request_at = time.monotonic()


def _get_json(path: str) -> Any:
    """paper 엔드포인트에 GET 만 보낸다. 이 모듈에 다른 HTTP 메서드는 존재하지 않는다."""
    headers = _auth_headers()
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _throttle()
        try:
            response = requests.get(PAPER_ACCOUNT_BASE_URL + path, headers=headers, timeout=REQUEST_TIMEOUT_SEC)
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(f"HTTP {response.status_code} on {path}")
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:  # noqa: PERF203
            last_exc = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(min(1.0, MIN_REQUEST_INTERVAL_SEC * attempt))
    raise RuntimeError(f"{path} 조회 실패: {type(last_exc).__name__}: {last_exc}")


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_account() -> dict[str, Any]:
    """/v2/account — 자산·현금·매수여력만 뽑는다(계좌번호 등 식별값은 담지 않는다)."""
    raw = _get_json("/v2/account")
    return {
        "equity": _to_float(raw.get("equity")),
        "cash": _to_float(raw.get("cash")),
        "buying_power": _to_float(raw.get("buying_power")),
        "long_market_value": _to_float(raw.get("long_market_value")),
        "status": raw.get("status"),
        "currency": raw.get("currency"),
    }


def fetch_positions() -> list[dict[str, Any]]:
    """/v2/positions — 종목별 수량·평단·평가액·미실현손익."""
    raw = _get_json("/v2/positions")
    if not isinstance(raw, list):
        return []
    positions = []
    for row in raw:
        ticker = str(row.get("symbol") or "").upper()
        if not ticker:
            continue
        positions.append({
            "ticker": ticker,
            "qty": _to_float(row.get("qty")),
            "avg_entry_price": _to_float(row.get("avg_entry_price")),
            "current_price": _to_float(row.get("current_price")),
            "market_value": _to_float(row.get("market_value")),
            "unrealized_pl": _to_float(row.get("unrealized_pl")),
            "side": row.get("side"),
        })
    return sorted(positions, key=lambda p: p["ticker"])


def fetch_account_state() -> dict[str, Any]:
    """계좌 + 포지션을 한 번에 조회한다. 실패는 격리해 ok=False 로 돌려주고 예외를 올리지 않는다."""
    state: dict[str, Any] = {
        "ok": False,
        "source": SOURCE_ALPACA_PAPER,
        "fetched_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "account": None,
        "positions": [],
        "error": None,
    }
    if not credentials_available():
        state["error"] = "credentials_missing"
        return state
    try:
        state["account"] = fetch_account()
    except Exception as exc:  # noqa: BLE001 - 조회 실패가 잡 전체를 죽이지 않게 한다
        state["error"] = f"account: {type(exc).__name__}: {exc}"
        return state
    try:
        state["positions"] = fetch_positions()
    except Exception as exc:  # noqa: BLE001
        state["error"] = f"positions: {type(exc).__name__}: {exc}"
        return state
    state["ok"] = True
    return state


# ---- 목표 비중 읽기 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class SleeveTarget:
    """한 슬리브의 목표. status=unknown 이면 weights 는 의미 없고 비교에서 제외된다."""

    sleeve: str
    status: str
    weights: dict[str, float]
    reason: str


def _sleeve_target(sleeve: str, recommendation: Optional[dict], flag: str = "new_orders_allowed") -> SleeveTarget:
    if not isinstance(recommendation, dict):
        return SleeveTarget(sleeve, STATUS_UNKNOWN, {}, "추천을 계산하지 못함")
    if recommendation.get(flag) is not True:
        # 보류: 목표 0% 가 아니라 "모름". 전량 매도 필요로 번역하면 안 된다.
        reason = str(recommendation.get("allocation_reason") or "").strip()
        return SleeveTarget(sleeve, STATUS_UNKNOWN, {}, reason or f"{sleeve} 슬리브 신규 주문 보류(목표 비중 비교 불가)")
    weights = {
        str(t).upper(): float(w) * 100.0
        for t, w in (recommendation.get("per_ticker_weights") or {}).items()
        if _to_float(w) is not None
    }
    return SleeveTarget(sleeve, STATUS_COMPARABLE, weights, "")


def build_target_weights(core: Optional[dict], satellite: Optional[dict]) -> dict[str, SleeveTarget]:
    """챔피언 전략 추천 2건을 슬리브별 목표(%)로 바꾼다 — 읽기만 하고 아무것도 바꾸지 않는다."""
    return {
        SLEEVE_CORE: _sleeve_target(SLEEVE_CORE, core),
        SLEEVE_SATELLITE: _sleeve_target(SLEEVE_SATELLITE, satellite),
    }


# ---- 이탈(드리프트) 계산 ---------------------------------------------------------------------------


def compute_drift(
    account_state: dict[str, Any],
    core: Optional[dict] = None,
    satellite: Optional[dict] = None,
) -> dict[str, Any]:
    """실제 비중과 목표 비중의 차이를 계산한다. 정보 제공 전용 — 주문을 만들지 않는다.

    drift_pct_points = 실제 비중(%) - 목표 비중(%). 양수면 과다보유(예: 목표 20% vs 실제 25% → +5.0).

    보류 슬리브(status=unknown)는 목표가 0 이 아니라 **모름**이다:
      - 그 슬리브의 종목이 무엇이었을지도 모르므로, 어떤 목표에도 없는 보유 종목을 "전량 매도 필요"로
        분류하지 않고 unknown_positions 로 따로 뺀다.
      - 회전 필요량은 비교 가능한 부분만 더하고 turnover_is_partial=True 로 표시한다.
    """
    targets = build_target_weights(core, satellite)
    account = account_state.get("account") or {}
    equity = _to_float(account.get("equity"))
    positions = list(account_state.get("positions") or [])

    all_comparable = all(t.status == STATUS_COMPARABLE for t in targets.values())
    unknown_sleeves = [t.sleeve for t in targets.values() if t.status == STATUS_UNKNOWN]
    unknown_reason = "; ".join(f"{t.sleeve}: {t.reason}" for t in targets.values() if t.status == STATUS_UNKNOWN)

    sleeve_of: dict[str, str] = {}
    target_pct: dict[str, float] = {}
    for sleeve in (SLEEVE_CORE, SLEEVE_SATELLITE):
        for ticker, weight in targets[sleeve].weights.items():
            sleeve_of.setdefault(ticker, sleeve)
            target_pct[ticker] = target_pct.get(ticker, 0.0) + weight

    rows: list[dict[str, Any]] = []
    unknown_positions: list[dict[str, Any]] = []
    held_not_in_target: list[dict[str, Any]] = []
    actual_by_sleeve: dict[str, float] = {SLEEVE_CORE: 0.0, SLEEVE_SATELLITE: 0.0}

    for position in positions:
        ticker = position["ticker"]
        market_value = _to_float(position.get("market_value"))
        weight_pct = (market_value / equity * 100.0) if (equity and equity > 0 and market_value is not None) else None
        sleeve = sleeve_of.get(ticker, SLEEVE_UNASSIGNED)
        row = {
            "ticker": ticker,
            "qty": position.get("qty"),
            "avg_entry_price": position.get("avg_entry_price"),
            "current_price": position.get("current_price"),
            "market_value": market_value,
            "unrealized_pl": position.get("unrealized_pl"),
            "weight_pct": weight_pct,
            "sleeve": sleeve,
            "target_weight_pct": None,
            "drift_pct_points": None,
            "drift_status": STATUS_UNKNOWN,
            "drift_reason": "",
            "action": "none",
        }
        if sleeve in actual_by_sleeve and weight_pct is not None:
            actual_by_sleeve[sleeve] += weight_pct

        if weight_pct is None:
            row["drift_reason"] = "평가액 또는 계좌 자산을 알 수 없어 비중을 계산할 수 없음"
        elif ticker in target_pct:
            row["target_weight_pct"] = round(target_pct[ticker], 4)
            row["drift_pct_points"] = round(weight_pct - target_pct[ticker], 4)
            row["drift_status"] = STATUS_COMPARABLE
            row["action"] = _action_for(row["drift_pct_points"])
        elif all_comparable:
            # 두 슬리브 모두 목표가 확정된 경우에만 "목표에 없는 보유"라고 단정할 수 있다.
            row["target_weight_pct"] = 0.0
            row["drift_pct_points"] = round(weight_pct, 4)
            row["drift_status"] = STATUS_COMPARABLE
            row["action"] = "not_in_target"
            held_not_in_target.append({"ticker": ticker, "weight_pct": round(weight_pct, 4)})
        else:
            # 보류 슬리브가 있으므로 이 종목이 그 슬리브의 목표였을 수도 있다 → 비교 불가.
            row["drift_reason"] = (
                f"목표 비중 비교 불가 — 보류 중인 슬리브({', '.join(unknown_sleeves)})가 있어 "
                f"'목표에 없음'과 '아직 모름'을 구분할 수 없다. {unknown_reason}"
            )
            unknown_positions.append({"ticker": ticker, "weight_pct": round(weight_pct, 4), "reason": row["drift_reason"]})
        rows.append(row)

    held_tickers = {p["ticker"] for p in positions}
    target_not_held = [
        {
            "ticker": ticker,
            "sleeve": sleeve_of.get(ticker, SLEEVE_UNASSIGNED),
            "target_weight_pct": round(weight, 4),
            "drift_pct_points": round(-weight, 4),
            "action": "buy",
        }
        for ticker, weight in sorted(target_pct.items())
        if ticker not in held_tickers
    ]

    comparable_drifts = [abs(r["drift_pct_points"]) for r in rows if r["drift_status"] == STATUS_COMPARABLE]
    comparable_drifts += [abs(r["drift_pct_points"]) for r in target_not_held]
    total_abs_drift_pct = round(sum(comparable_drifts), 4)

    sleeves: dict[str, Any] = {}
    for sleeve in (SLEEVE_CORE, SLEEVE_SATELLITE):
        target = targets[sleeve]
        if target.status == STATUS_COMPARABLE:
            target_sum = round(sum(target.weights.values()), 4)
            actual_sum = round(actual_by_sleeve[sleeve], 4) if equity else None
            sleeves[sleeve] = {
                "status": STATUS_COMPARABLE,
                "target_weight_pct": target_sum,
                "actual_weight_pct": actual_sum,
                "drift_pct_points": round(actual_sum - target_sum, 4) if actual_sum is not None else None,
                "reason": "",
            }
        else:
            sleeves[sleeve] = {
                "status": STATUS_UNKNOWN,
                "target_weight_pct": None,
                "actual_weight_pct": None,
                "drift_pct_points": None,
                "reason": target.reason,
            }

    max_abs_drift = max(comparable_drifts) if comparable_drifts else 0.0
    return {
        "as_of": str(date.today()),
        "equity": equity,
        "cash": _to_float(account.get("cash")),
        "buying_power": _to_float(account.get("buying_power")),
        "positions": rows,
        "sleeves": sleeves,
        "target_not_held": target_not_held,
        "held_not_in_target": held_not_in_target,
        "unknown_positions": unknown_positions,
        "unknown_sleeves": unknown_sleeves,
        "n_unknown": len(unknown_positions) + len(unknown_sleeves),
        "total_abs_drift_pct": total_abs_drift_pct,
        # 자기자금 내 교체라면 실제 거래금액은 절대편차의 절반이다(매도 한 번 + 매수 한 번).
        "turnover_needed_pct": round(total_abs_drift_pct / 2.0, 4),
        "turnover_is_partial": not all_comparable,
        "max_abs_drift_pct_points": round(max_abs_drift, 4),
        # 정보 제공 전용 플래그다. 이 값이 True 여도 이 모듈은 아무 주문도 만들지 않는다.
        "rebalance_review_suggested": bool(max_abs_drift >= DRIFT_ALERT_PCT_POINTS),
        "informational_only": True,
    }


def _action_for(drift_pct_points: float) -> str:
    if drift_pct_points > 0:
        return "overweight"
    if drift_pct_points < 0:
        return "underweight"
    return "none"


def summarize_drift(drift: dict[str, Any]) -> str:
    """사람이 한 줄로 읽을 요약 — 민감값 없음."""
    sleeve_bits = ", ".join(
        f"{name}={info['status']}" + (f"({info['drift_pct_points']:+.1f}%p)" if info.get("drift_pct_points") is not None else "")
        for name, info in (drift.get("sleeves") or {}).items()
    )
    partial = " (부분값 — 보류 슬리브 있음)" if drift.get("turnover_is_partial") else ""
    return (
        f"보유 {len(drift.get('positions') or [])}종목, 최대 이탈 {drift.get('max_abs_drift_pct_points', 0):.1f}%p, "
        f"필요 회전 {drift.get('turnover_needed_pct', 0):.1f}%{partial}, 비교불가 {drift.get('n_unknown', 0)}건 [{sleeve_bits}]"
    )


# ---- 저장 ------------------------------------------------------------------------------------------


def save_snapshot(session, account_state: dict[str, Any], drift: dict[str, Any]) -> Any:
    """스냅샷 1건 + 종목별 행을 저장한다(세션 commit 은 호출부 책임)."""
    from core.models import AccountPositionSnapshot, AccountSnapshot

    account = account_state.get("account") or {}
    summary = {k: v for k, v in drift.items() if k != "positions"}
    snapshot = AccountSnapshot(
        as_of=date.today(),
        fetched_at=account_state.get("fetched_at") or datetime.now(timezone.utc).replace(tzinfo=None),
        source=account_state.get("source") or SOURCE_ALPACA_PAPER,
        equity=_to_float(account.get("equity")),
        cash=_to_float(account.get("cash")),
        buying_power=_to_float(account.get("buying_power")),
        long_market_value=_to_float(account.get("long_market_value")),
        n_positions=len(account_state.get("positions") or []),
        drift_summary=json.dumps(summary, ensure_ascii=False, default=str),
        note=summarize_drift(drift),
    )
    session.add(snapshot)
    session.flush()
    for row in drift.get("positions") or []:
        session.add(AccountPositionSnapshot(
            snapshot_id=snapshot.id,
            ticker=row["ticker"],
            qty=_to_float(row.get("qty")),
            avg_entry_price=_to_float(row.get("avg_entry_price")),
            current_price=_to_float(row.get("current_price")),
            market_value=_to_float(row.get("market_value")),
            unrealized_pl=_to_float(row.get("unrealized_pl")),
            weight_pct=row.get("weight_pct"),
            target_weight_pct=row.get("target_weight_pct"),
            drift_pct_points=row.get("drift_pct_points"),
            drift_status=row.get("drift_status"),
            drift_reason=row.get("drift_reason") or None,
            sleeve=row.get("sleeve"),
        ))
    return snapshot


def _load_recommendations() -> tuple[Optional[dict], Optional[dict], list[str]]:
    """챔피언 전략 추천을 읽기만 한다. 실패한 슬리브는 None → unknown 으로 흘러간다."""
    errors: list[str] = []
    core = satellite = None
    try:
        from core.champion_strategy import compute_core_recommendation

        core = compute_core_recommendation()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"core: {type(exc).__name__}: {exc}")
    try:
        from core.champion_strategy import compute_satellite_recommendation_point_in_time

        satellite = compute_satellite_recommendation_point_in_time()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"satellite: {type(exc).__name__}: {exc}")
    return core, satellite, errors


def sync_paper_account(*, persist: bool = True, session=None) -> dict[str, Any]:
    """스냅샷 1회 + 이탈 리포트. 키가 없으면 skipped=True 로 조용히 건너뛰고 사유를 남긴다.

    조회 전용 — 어떤 경로로도 주문을 만들거나 제출하지 않는다.
    """
    result: dict[str, Any] = {
        "ok": False, "skipped": False, "reason": None, "saved": False,
        "snapshot_id": None, "drift": None, "errors": [],
    }
    if not credentials_available():
        result["skipped"] = True
        result["reason"] = "ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET 환경변수 없음 — 계좌 조회 건너뜀"
        return result

    state = fetch_account_state()
    if not state["ok"]:
        result["reason"] = str(state.get("error") or "계좌 조회 실패")
        result["errors"].append(result["reason"])
        return result

    core, satellite, errors = _load_recommendations()
    result["errors"].extend(errors)
    drift = compute_drift(state, core, satellite)
    result["drift"] = drift
    result["ok"] = True

    if persist:
        try:
            if session is not None:
                snapshot = save_snapshot(session, state, drift)
                session.commit()
                result["snapshot_id"] = snapshot.id
            else:
                from core.db import get_session, init_db

                init_db()
                with get_session() as db:
                    snapshot = save_snapshot(db, state, drift)
                    db.flush()
                    result["snapshot_id"] = snapshot.id
            result["saved"] = True
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"save: {type(exc).__name__}: {exc}")
    return result
