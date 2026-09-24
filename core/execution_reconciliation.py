"""체결 대조 엔진 (ENG: live 체결 vs 백테스트 예상 체결).

목적은 하나다. **실제 Alpaca paper 체결**을 core.trade_ledger 의 원장 행과 *같은 스키마*로
정규화해서, 같은 주문 단위로 (a) 실측 슬리피지(bp), (b) 예상 수량 대비 실제 체결 수량,
(c) 주문→체결 지연, (d) 미체결·부분체결·거절 분류를 계산하는 것이다.

정직성 규칙(core.candidate_ledger 의 판정 관례와 동일):
- 표본이 MIN_SAMPLE_FOR_REPRESENTATIVE(30) 건 미만이면 대표값을 주장하지 않는다.
  요약 dict 의 status 가 ``insufficient_sample`` 이 되고 median/분위수 필드는 None 이다
  (관측된 값 자체는 ``observed_*`` 로 남기되 "이 계정의 슬리피지는 X bp" 라고 말하지 않는다).
- compare_with_cost_assumptions() 는 core.trade_ledger.COST_SCENARIOS_BPS 의 **가정값**과
  실측값의 차이를 표로 보여줄 뿐이다. 어느 쪽이 더 낫다는 판단도, 백테스트 결과 갱신도 하지 않는다.

이 모듈은 **조회 전용**이다. 주문 제출·취소 코드는 없다(제출은 core.paper_execution 만 한다).
자격증명은 환경변수(ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET)에서만 읽고 값은
출력하지도 저장하지도 않는다.

DB 저장: 하지 않는다. 체결 이력의 원본(source of truth)은 브로커 계정이고 언제든 다시 조회할 수
있으므로, 같은 값을 로컬 테이블에 복제해 이중 원장을 만드는 대신 매 실행마다 조회해 리포트를
만든다(scripts/reconcile_paper_fills.py). 필요해지면 그때 core/models.py 에 테이블을 추가한다.
"""

from __future__ import annotations

import os
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional, Sequence

import pandas as pd
import requests

from core.paper_execution import PAPER_BASE_URL, classify_order_state
from core.trade_ledger import COST_SCENARIOS_BPS, LEDGER_COLUMNS

KEY_ENV = "ALPACA_PAPER_API_KEY"
SECRET_ENV = "ALPACA_PAPER_API_SECRET"

# 대표값을 주장하기 위한 최소 표본 수. 이 아래는 'insufficient_sample'.
MIN_SAMPLE_FOR_REPRESENTATIVE = 30

# 원장 스키마(LEDGER_COLUMNS)에 없는, 대조에만 필요한 식별 컬럼. 원장 컬럼 뒤에 붙는다.
RECON_ID_COLUMNS = ["client_order_id", "order_id", "symbol", "fill_status"]

# 분류 라벨
STATUS_FILLED = "filled"
STATUS_PARTIAL = "partial_fill"
STATUS_UNFILLED = "unfilled"
STATUS_REJECTED = "rejected"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_PLACED = "not_placed"

_RETRY_STATUS = {429, 500, 502, 503, 504}


class FillQueryError(RuntimeError):
    """체결 이력 조회가 (재시도 후에도) 실패했다."""


def _to_float(value: Any) -> Optional[float]:
    if value in (None, "", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class AlpacaFillReader:
    """Alpaca paper 계정의 **읽기 전용** 체결 이력 조회부.

    - /v2/orders?status=closed : 종료된 주문(체결/부분체결/거절/취소)을 submitted_at 기준 페이지네이션.
    - /v2/account/activities?activity_types=FILL : 체결 단위 활동(page_token 페이지네이션).
    429/5xx 는 지수 백오프로 재시도하고, 그래도 실패하면 지금까지 모은 페이지를 유지한 채
    partial=True 와 오류 요약을 돌려준다(부분 실패 허용). 자격증명 값은 절대 출력하지 않는다.
    """

    def __init__(self, key: str, secret: str, *, base_url: str = PAPER_BASE_URL,
                 session: Any = None, sleep: Callable[[float], None] = time.sleep,
                 max_retries: int = 3, timeout: float = 20.0, max_pages: int = 50):
        if not key or not secret:
            raise ValueError(f"{KEY_ENV} and {SECRET_ENV} are required")
        self._headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        self.base_url = base_url
        self._session = session or requests
        self._sleep = sleep
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_pages = max_pages

    @classmethod
    def from_env(cls, **kwargs: Any) -> "AlpacaFillReader":
        return cls(os.getenv(KEY_ENV, ""), os.getenv(SECRET_ENV, ""), **kwargs)

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        last_error = ""
        for attempt in range(self.max_retries):
            try:
                response = self._session.request(
                    "GET", self.base_url + path, headers=self._headers, params=params, timeout=self.timeout)
                status = getattr(response, "status_code", 200)
                if status in _RETRY_STATUS:
                    last_error = f"HTTP {status}"
                    self._sleep(min(2 ** attempt, 8))
                    continue
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as exc:  # 4xx (429 제외) 는 재시도해도 같다
                code = exc.response.status_code if exc.response is not None else 0
                raise FillQueryError(f"{path} failed: HTTP {code}") from None
            except (requests.RequestException, ValueError) as exc:
                last_error = type(exc).__name__
                self._sleep(min(2 ** attempt, 8))
        raise FillQueryError(f"{path} failed after {self.max_retries} attempts ({last_error})")

    def list_closed_orders(self, *, after: Any = None, until: Any = None, page_limit: int = 500) -> dict[str, Any]:
        """종료된 주문을 오래된 것부터 모은다. 반환: {orders, partial, errors, pages}."""
        params: dict[str, Any] = {"status": "closed", "limit": page_limit, "direction": "asc", "nested": "false"}
        if after is not None:
            params["after"] = _iso(after)
        if until is not None:
            params["until"] = _iso(until)
        orders: list[dict[str, Any]] = []
        seen: set[str] = set()
        errors: list[str] = []
        pages = 0
        partial = False
        while pages < self.max_pages:
            try:
                batch = self._get("/v2/orders", dict(params))
            except FillQueryError:
                if not orders:
                    raise  # 첫 페이지부터 실패 -> 전체 실패로 알린다
                errors.append("later page failed")
                partial = True
                break
            pages += 1
            batch = list(batch or [])
            fresh = [o for o in batch if str(o.get("id")) not in seen]
            for order in fresh:
                seen.add(str(order.get("id")))
            orders.extend(fresh)
            if len(batch) < page_limit or not fresh:
                break
            cursor = max((str(o.get("submitted_at") or "") for o in batch), default="")
            if not cursor or cursor == params.get("after"):
                partial = True
                errors.append("pagination cursor did not advance")
                break
            params["after"] = cursor
        else:
            partial = True
            errors.append(f"stopped at max_pages={self.max_pages}")
        return {"orders": orders, "partial": partial, "errors": errors, "pages": pages}

    def list_fill_activities(self, *, after: Any = None, until: Any = None, page_size: int = 100) -> dict[str, Any]:
        """FILL/PARTIAL_FILL 활동을 page_token 으로 모은다. 반환: {activities, partial, errors, pages}."""
        params: dict[str, Any] = {"activity_types": "FILL", "page_size": page_size, "direction": "asc"}
        if after is not None:
            params["after"] = _iso(after)
        if until is not None:
            params["until"] = _iso(until)
        activities: list[dict[str, Any]] = []
        errors: list[str] = []
        pages = 0
        partial = False
        while pages < self.max_pages:
            try:
                batch = self._get("/v2/account/activities", dict(params))
            except FillQueryError:
                if not activities:
                    raise
                errors.append("later page failed")
                partial = True
                break
            pages += 1
            batch = list(batch or [])
            activities.extend(batch)
            if len(batch) < page_size:
                break
            token = batch[-1].get("id")
            if not token or token == params.get("page_token"):
                partial = True
                errors.append("pagination token did not advance")
                break
            params["page_token"] = token
        else:
            partial = True
            errors.append(f"stopped at max_pages={self.max_pages}")
        return {"activities": activities, "partial": partial, "errors": errors, "pages": pages}


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return str(value)


# --------------------------------------------------------------------------------------
# 정규화: 실제 체결 -> core.trade_ledger 원장 행 스키마
# --------------------------------------------------------------------------------------

def classify_fill(order: dict[str, Any]) -> str:
    """주문 1건의 체결 결과 분류: filled / partial_fill / unfilled / rejected / unknown."""
    state = classify_order_state(order)
    filled_qty = _to_float(order.get("filled_qty")) or 0.0
    ordered_qty = _to_float(order.get("qty"))
    if state == "filled":
        return STATUS_FILLED
    if state == "partial" or (filled_qty > 0 and ordered_qty and filled_qty + 1e-9 < ordered_qty):
        return STATUS_PARTIAL
    if state == "rejected":
        return STATUS_REJECTED if filled_qty <= 0 else STATUS_PARTIAL
    if state == "open":
        return STATUS_UNFILLED
    return STATUS_UNKNOWN


def normalize_fills(orders: Iterable[dict[str, Any]],
                    expectations: Optional[dict[str, dict[str, Any]]] = None) -> pd.DataFrame:
    """실제 체결을 core.trade_ledger.LEDGER_COLUMNS 와 같은 컬럼 계약으로 정규화한다.

    매핑(백테스트 원장과 의미를 맞춘 것):
      signal_time    주문이 결정/제출된 시각(백테스트의 신호 시각에 해당). expectations 에
                     signal_time 이 있으면 그것을, 없으면 주문 submitted_at.
      fill_time      실제 체결 시각(filled_at).
      side           BUY / SELL (원장과 같은 대문자).
      quantity       실제 체결 수량(filled_qty).
      ref_open       백테스트가 가정한 체결 기준가(다음 시가). expectations['expected_price'] 가
                     없으면 NaN -> 슬리피지 계산 불가.
      fill_price     실제 평균 체결가(filled_avg_price).
      notional       quantity * fill_price.
      fee            브로커가 보고한 수수료(없으면 0.0; Alpaca paper 는 보통 0).
      slippage_cost  실측 슬리피지 금액 = quantity * (fill_price - ref_open) [매수] / 반대부호[매도].
                     ref_open 이 없으면 NaN.
      tax            거래세 보고값 없음 -> 0.0.
      cash_after/shares_after/nav_after
                     실계정 원장에서는 체결 1건 단위로 재구성하지 않으므로 NaN(컬럼은 유지).
    뒤에 RECON_ID_COLUMNS(client_order_id, order_id, symbol, fill_status)가 붙는다.
    """
    expectations = expectations or {}
    rows: list[dict[str, Any]] = []
    for order in orders:
        cid = str(order.get("client_order_id") or "")
        expected = expectations.get(cid, {})
        status = classify_fill(order)
        qty = _to_float(order.get("filled_qty")) or 0.0
        price = _to_float(order.get("filled_avg_price"))
        ref = _to_float(expected.get("expected_price"))
        side = str(order.get("side") or expected.get("side") or "").upper()
        fee = _to_float(order.get("fee")) or 0.0
        notional = qty * price if (price is not None and qty) else float("nan")
        if ref and price is not None and qty:
            signed = (price - ref) if side == "BUY" else (ref - price)
            slippage_cost = qty * signed
        else:
            slippage_cost = float("nan")
        rows.append({
            "signal_time": _to_dt(expected.get("signal_time")) or _to_dt(order.get("submitted_at")),
            "fill_time": _to_dt(order.get("filled_at")),
            "side": side,
            "quantity": qty,
            "ref_open": ref if ref is not None else float("nan"),
            "fill_price": price if price is not None else float("nan"),
            "notional": notional,
            "fee": fee,
            "slippage_cost": slippage_cost,
            "tax": 0.0,
            "cash_after": float("nan"),
            "shares_after": float("nan"),
            "nav_after": float("nan"),
            "client_order_id": cid,
            "order_id": str(order.get("id") or ""),
            "symbol": str(order.get("symbol") or expected.get("symbol") or ""),
            "fill_status": status,
        })
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS + RECON_ID_COLUMNS)


# --------------------------------------------------------------------------------------
# 대조
# --------------------------------------------------------------------------------------

def slippage_bps(expected_price: Optional[float], fill_price: Optional[float], side: str) -> Optional[float]:
    """실측 슬리피지(bp). 부호는 **불리할수록 양수**.

    매수: (체결가 - 예상가)/예상가 * 1e4, 매도: (예상가 - 체결가)/예상가 * 1e4.
    예: 예상 100.00, 실제 100.05 매수 -> +5.0bp.
    """
    if not expected_price or expected_price <= 0 or fill_price is None:
        return None
    side = (side or "").upper()
    if side not in ("BUY", "SELL"):
        return None
    diff = (fill_price - expected_price) if side == "BUY" else (expected_price - fill_price)
    return diff / expected_price * 1e4


def reconcile_orders(orders: Sequence[dict[str, Any]],
                     expectations: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, Any]:
    """client_order_id(core.paper_execution.client_order_id 규칙) 로 예상 주문과 실제 주문을 맞춘다.

    반환: {"rows": [...], "unmatched_expected": [...], "unmatched_actual": [...], "counts": {...}}
    각 row: 예상가/실제가/실측 슬리피지 bp, 예상 수량/체결 수량/체결률, 지연(초), 분류.
    expectations 에는 있으나 브로커에 없는 주문은 ``not_placed`` 로 남긴다.
    """
    expectations = dict(expectations or {})
    by_cid: dict[str, dict[str, Any]] = {}
    unmatched_actual: list[dict[str, Any]] = []
    for order in orders:
        cid = str(order.get("client_order_id") or "")
        if cid and cid in expectations:
            by_cid[cid] = order
        elif cid:
            by_cid.setdefault(cid, order)
            if expectations:
                unmatched_actual.append({"client_order_id": cid, "symbol": order.get("symbol"),
                                         "fill_status": classify_fill(order)})
        else:
            unmatched_actual.append({"client_order_id": "", "symbol": order.get("symbol"),
                                     "fill_status": classify_fill(order)})

    rows: list[dict[str, Any]] = []
    for cid, order in by_cid.items():
        expected = expectations.get(cid, {})
        side = str(order.get("side") or expected.get("side") or "").upper()
        fill_price = _to_float(order.get("filled_avg_price"))
        expected_price = _to_float(expected.get("expected_price"))
        filled_qty = _to_float(order.get("filled_qty")) or 0.0
        expected_qty = _to_float(expected.get("expected_quantity"))
        if expected_qty is None:
            expected_qty = _to_float(order.get("qty"))
        submitted_at = _to_dt(order.get("submitted_at"))
        filled_at = _to_dt(order.get("filled_at"))
        delay = (filled_at - submitted_at).total_seconds() if (submitted_at and filled_at) else None
        rows.append({
            "client_order_id": cid,
            "symbol": str(order.get("symbol") or expected.get("symbol") or ""),
            "side": side,
            "fill_status": classify_fill(order),
            "broker_status": str(order.get("status") or ""),
            "expected_price": expected_price,
            "fill_price": fill_price,
            "slippage_bp": slippage_bps(expected_price, fill_price, side),
            "expected_quantity": expected_qty,
            "filled_quantity": filled_qty,
            "quantity_fill_ratio": (filled_qty / expected_qty) if expected_qty else None,
            "submitted_at": submitted_at.isoformat() if submitted_at else None,
            "filled_at": filled_at.isoformat() if filled_at else None,
            "fill_delay_seconds": delay,
        })

    unmatched_expected = []
    for cid, expected in expectations.items():
        if cid in by_cid:
            continue
        unmatched_expected.append({"client_order_id": cid, "symbol": expected.get("symbol"),
                                   "side": str(expected.get("side") or "").upper(),
                                   "fill_status": STATUS_NOT_PLACED})
    rows.sort(key=lambda r: (r["symbol"], r["client_order_id"]))
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["fill_status"]] = counts.get(row["fill_status"], 0) + 1
    if unmatched_expected:
        counts[STATUS_NOT_PLACED] = len(unmatched_expected)
    return {"rows": rows, "unmatched_expected": unmatched_expected, "unmatched_actual": unmatched_actual,
            "counts": counts, "n_orders": len(rows) + len(unmatched_expected)}


def _quantile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _summarize_values(values: Sequence[float], min_sample: int) -> dict[str, Any]:
    """표본이 min_sample 미만이면 대표값(중앙값·분위수)을 **주장하지 않는다**."""
    n = len(values)
    summary: dict[str, Any] = {"n": n, "min_sample_for_representative": min_sample}
    if n < min_sample:
        summary.update({
            "status": "insufficient_sample",
            "median_bp": None, "p25_bp": None, "p75_bp": None, "p10_bp": None, "p90_bp": None,
            "note": (f"표본 {n}건 < {min_sample}건: 대표 슬리피지를 주장하지 않는다. "
                     "아래 observed_* 는 관측된 원시 범위일 뿐 추정치가 아니다."),
        })
        if n:
            summary.update({"observed_min_bp": min(values), "observed_max_bp": max(values),
                            "observed_mean_bp": statistics.fmean(values)})
        return summary
    summary.update({
        "status": "ok",
        "median_bp": statistics.median(values),
        "p25_bp": _quantile(values, 0.25),
        "p75_bp": _quantile(values, 0.75),
        "p10_bp": _quantile(values, 0.10),
        "p90_bp": _quantile(values, 0.90),
        "mean_bp": statistics.fmean(values),
    })
    return summary


def summarize_slippage(rows: Sequence[dict[str, Any]], *,
                       min_sample: int = MIN_SAMPLE_FOR_REPRESENTATIVE) -> dict[str, Any]:
    """실측 슬리피지 요약: 전체 / 매수·매도 분리 / 심볼별. 표본 부족은 명시한다."""
    usable = [r for r in rows if r.get("slippage_bp") is not None
              and r.get("fill_status") in (STATUS_FILLED, STATUS_PARTIAL)]
    overall = _summarize_values([r["slippage_bp"] for r in usable], min_sample)
    by_side = {
        side: _summarize_values([r["slippage_bp"] for r in usable if r["side"] == side], min_sample)
        for side in ("BUY", "SELL")
    }
    symbols = sorted({r["symbol"] for r in usable})
    by_symbol = {
        symbol: _summarize_values([r["slippage_bp"] for r in usable if r["symbol"] == symbol], min_sample)
        for symbol in symbols
    }
    delays = [r["fill_delay_seconds"] for r in rows if r.get("fill_delay_seconds") is not None]
    fill_ratios = [r["quantity_fill_ratio"] for r in rows if r.get("quantity_fill_ratio") is not None]
    return {
        "overall": overall,
        "by_side": by_side,
        "by_symbol": by_symbol,
        "n_rows": len(rows),
        "n_with_reference_price": len(usable),
        "fill_delay_seconds": {
            "n": len(delays),
            "median": statistics.median(delays) if delays else None,
            "max": max(delays) if delays else None,
        },
        "quantity_fill_ratio": {
            "n": len(fill_ratios),
            "median": statistics.median(fill_ratios) if fill_ratios else None,
            "min": min(fill_ratios) if fill_ratios else None,
        },
    }


# --------------------------------------------------------------------------------------
# 가정 비용 vs 실측 비교 (차이 표시까지만)
# --------------------------------------------------------------------------------------

DISCLAIMER = ("core.trade_ledger 의 5/10/25bp 는 가정값이고 아래 실측은 paper 계정 표본이다. "
              "이 표는 차이를 보여줄 뿐이며, 어느 쪽이 더 정확하다는 판단이나 백테스트 결과 갱신은 하지 않는다.")


def compare_with_cost_assumptions(summary: dict[str, Any], *,
                                  scenarios: Optional[dict[str, dict[str, float]]] = None) -> dict[str, Any]:
    """가정 슬리피지(bp)와 실측 요약을 나란히 놓은 표를 만든다. 판단·갱신은 하지 않는다."""
    scenarios = scenarios or COST_SCENARIOS_BPS
    overall = summary.get("overall", {})
    measured = overall.get("median_bp") if overall.get("status") == "ok" else None
    table = []
    for name, params in scenarios.items():
        assumed = float(params.get("slippage_bps", 0.0))
        table.append({
            "scenario": name,
            "assumed_slippage_bps": assumed,
            "assumed_fee_bps": float(params.get("fee_bps", 0.0)),
            "measured_median_slippage_bps": measured,
            "difference_bps": (measured - assumed) if measured is not None else None,
        })
    return {
        "table": table,
        "measured_status": overall.get("status", "insufficient_sample"),
        "measured_n": overall.get("n", 0),
        "comparable": measured is not None,
        "note": DISCLAIMER if measured is not None else (
            DISCLAIMER + " 현재 표본이 부족해 실측 대표값을 비교에 넣지 않았다(difference_bps=None)."),
    }


def build_report(orders: Sequence[dict[str, Any]],
                 expectations: Optional[dict[str, dict[str, Any]]] = None, *,
                 min_sample: int = MIN_SAMPLE_FOR_REPRESENTATIVE,
                 query_meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """조회 결과 -> 대조 -> 요약 -> 가정 비용 비교까지의 전체 리포트(순수 함수, 네트워크 없음)."""
    recon = reconcile_orders(orders, expectations)
    summary = summarize_slippage(recon["rows"], min_sample=min_sample)
    ledger = normalize_fills(orders, expectations)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": query_meta or {},
        "counts": recon["counts"],
        "n_orders": recon["n_orders"],
        "rows": recon["rows"],
        "unmatched_expected": recon["unmatched_expected"],
        "unmatched_actual": recon["unmatched_actual"],
        "slippage_summary": summary,
        "cost_assumption_comparison": compare_with_cost_assumptions(summary),
        "ledger_columns": LEDGER_COLUMNS + RECON_ID_COLUMNS,
        "ledger_rows": len(ledger),
    }
