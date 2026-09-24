"""실측 체결 비용으로 백테스트 비용 가정(5/10/25bp)을 교정하기 위한 연결 모듈.

core.execution_reconciliation 의 실측 슬리피지 요약에서 '실측 비용 시나리오'를 만든다.

정직성 규칙:
- 대표값은 표본 n >= MIN_SAMPLE(30) 일 때만 만든다. 미만이면 scenario=None,
  reason="insufficient_sample" 과 n 을 돌려준다. 값을 지어내거나 가정값으로 대체하지 않는다.
- 매수/매도 각각 n>=30 이면 방향별 중앙값을 쓴다. 한쪽이라도 30 미만이고 전체만 30 이상이면 전체
  중앙값을 양쪽에 쓰되 side_split=False 로 명시한다(둘 다 30 미만이면 위 규칙).
- 수수료는 이 표본으로 측정하지 못한다. 시나리오의 fee_bps 는 0.0 이며(슬리피지 전용), fee_note 에 적는다.
- 슬리피지 기준가는 체결일 시가(백테스트 체결 모델의 기준가)다. 장중 주문의 시가 대비 차이는
  순수 실행 비용이 아니라 시가 이후 가격 변동을 포함하므로 실측이 아닌 '근사'임을 basis 에 표시한다.
- 표본은 Alpaca paper 계정의 것이며 실계좌 비용과 같다는 보장이 없다. 응답 스키마는 문서 기반 가정이다.

조회 전용이다(주문 코드 없음). 자격증명은 환경변수에서만 읽고 값은 출력·저장하지 않는다.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from core.execution_reconciliation import (
    KEY_ENV,
    MIN_SAMPLE_FOR_REPRESENTATIVE,
    SECRET_ENV,
    AlpacaFillReader,
    FillQueryError,
    reconcile_orders,
    summarize_slippage,
)

MIN_SAMPLE = MIN_SAMPLE_FOR_REPRESENTATIVE
STALE_AFTER_DAYS = 14
DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "cache" / "cost_calibration.json"
LABEL = "measured vs assumed"
FEE_NOTE = "수수료는 이 표본으로 측정하지 않았다: fee_bps=0.0 (슬리피지 전용 시나리오)"
BASIS = ("reference=fill-date open (근사: 시가 이후 가격 변동 포함); source=Alpaca paper fills; "
         "schema=documentation-assumed")


def _stats(group: dict[str, Any]) -> dict[str, Any]:
    return {"n": group.get("n", 0), "median_bp": group.get("median_bp"),
            "p75_bp": group.get("p75_bp"), "p90_bp": group.get("p90_bp")}


def build_measured_scenario(summary: dict[str, Any], *, generated_at: Optional[str] = None) -> dict[str, Any]:
    """summarize_slippage() 결과 -> 실측 시나리오. 표본 부족이면 scenario=None + 사유."""
    overall = summary.get("overall", {})
    by_side = summary.get("by_side", {})
    n = int(overall.get("n", 0))
    out: dict[str, Any] = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "label": LABEL, "basis": BASIS, "n": n, "min_sample": MIN_SAMPLE,
        "stats": {"overall": _stats(overall), "BUY": _stats(by_side.get("BUY", {})),
                  "SELL": _stats(by_side.get("SELL", {}))},
    }
    if overall.get("status") != "ok" or overall.get("median_bp") is None or n < MIN_SAMPLE:
        out.update({"status": "insufficient_sample", "reason": "insufficient_sample", "scenario": None})
        return out
    buy, sell = by_side.get("BUY", {}), by_side.get("SELL", {})
    split = (buy.get("status") == "ok" and sell.get("status") == "ok"
             and buy.get("median_bp") is not None and sell.get("median_bp") is not None)
    med = float(overall["median_bp"])
    out["status"] = "ok"
    out["reason"] = None
    out["scenario"] = {
        "fee_bps": 0.0,
        "slippage_bps": med,
        "buy_slippage_bps": float(buy["median_bp"]) if split else med,
        "sell_slippage_bps": float(sell["median_bp"]) if split else med,
        "side_split": split,
        "fee_note": FEE_NOTE,
    }
    if not split:
        out["side_note"] = "매수 또는 매도 표본이 30건 미만이라 전체 중앙값을 양쪽에 동일하게 적용했다"
    return out


def build_calibration_from_orders(orders: list[dict[str, Any]],
                                  expectations: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, Any]:
    """주문 목록 -> 대조 -> 실측 시나리오(순수 함수, 네트워크 없음)."""
    recon = reconcile_orders(orders, expectations)
    return build_measured_scenario(summarize_slippage(recon["rows"]))


def _fill_reference_opens(orders: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """체결일 시가를 캐시/가격 소스에서 채워 expectations 를 만든다. 실패는 메모만 남긴다."""
    notes: list[str] = []
    expectations: dict[str, dict[str, Any]] = {}
    try:
        from core.market_data import get_price_history
    except Exception as exc:  # pragma: no cover - 환경 의존
        return expectations, [f"market_data unavailable: {type(exc).__name__}"]
    wanted: dict[str, set[str]] = {}
    for o in orders:
        day, sym = str(o.get("filled_at") or "")[:10], str(o.get("symbol") or "")
        if day and sym:
            wanted.setdefault(sym, set()).add(day)
    opens: dict[tuple[str, str], float] = {}
    for sym, days in wanted.items():
        try:
            end = (datetime.fromisoformat(max(days)) + timedelta(days=5)).date().isoformat()
            hist = get_price_history(sym, start=min(days), end=end)
        except Exception as exc:
            notes.append(f"{sym}: price lookup failed ({type(exc).__name__})")
            continue
        if hist is None or getattr(hist, "empty", True):
            notes.append(f"{sym}: no price rows")
            continue
        for ts, row in hist.iterrows():
            opens[(sym, str(ts)[:10])] = float(row["Open"])
    for o in orders:
        cid = str(o.get("client_order_id") or "")
        key = (str(o.get("symbol") or ""), str(o.get("filled_at") or "")[:10])
        if cid and key in opens:
            expectations[cid] = {"expected_price": opens[key]}
    return expectations, notes


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def refresh_cost_calibration(save_path: Optional[str | Path] = None) -> dict[str, Any]:
    """Alpaca paper 체결을 가져와 실측 비용 교정값을 계산·저장한다. 절대 예외를 던지지 않는다.

    반환 status: 'ok' | 'insufficient_sample' | 'unavailable'(키 없음/호출 실패, reason 포함).
    unavailable 이면 기존 저장 파일을 건드리지 않는다. 키 값은 출력·저장하지 않는다.
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        if not os.getenv(KEY_ENV) or not os.getenv(SECRET_ENV):
            return {"status": "unavailable", "reason": "missing_credentials", "generated_at": now, "saved": False}
        since = datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        try:
            fetched = AlpacaFillReader.from_env().list_closed_orders(after=since)
        except FillQueryError as exc:
            return {"status": "unavailable", "reason": f"fetch_failed: {exc}", "generated_at": now, "saved": False}
        orders = fetched["orders"]
        expectations, notes = _fill_reference_opens(orders)
        result = build_calibration_from_orders(orders, expectations)
        result["query"] = {"since": since.isoformat(), "n_closed_orders": len(orders),
                           "partial": fetched.get("partial", False), "errors": fetched.get("errors", []),
                           "reference_notes": notes}
        path = Path(save_path) if save_path else DEFAULT_PATH
        _atomic_write(path, result)
        result["saved"] = True
        result["path"] = str(path)
        return result
    except Exception as exc:  # 스케줄러에서 호출되므로 어떤 실패도 전파하지 않는다
        return {"status": "unavailable", "reason": f"error: {type(exc).__name__}", "generated_at": now,
                "saved": False}


def load_cost_calibration(path: Optional[str | Path] = None, *,
                          stale_after_days: int = STALE_AFTER_DAYS,
                          now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """저장된 교정 JSON 을 읽는다. 없거나 깨졌으면 None. stale_after_days 초과면 stale=True."""
    p = Path(path) if path else DEFAULT_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        gen = datetime.fromisoformat(str(data["generated_at"]))
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    ref = now or datetime.now(timezone.utc)
    age = (ref - gen).total_seconds() / 86400.0
    data["age_days"] = age
    data["stale"] = age > stale_after_days
    return data
