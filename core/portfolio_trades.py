"""매수·매도 기록 (2026-11-20, 사용자 요청 "내가 매도한 것을 입력할 수 없어 … 매수/매도 한 것을 알려주면 포트폴리오를 관리").

한 줄에 한 건('XLK 3 매도 210.5', '매수 SPY 2 650 11/19', 'XLE 전량 매도 95')을 적으면 한 번에 반영한다:
  - 보유 기록: 매수는 매입 기록 한 줄 추가, 매도는 그 종목 기록들을 같은 비율로 줄인다(이동평균 단가 유지 — 한국 해외주식
    양도세의 이동평균법과 같은 셈). 다 팔면 기록을 지운다.
  - 현금 잔고: 매수 금액·수수료를 빼고 매도 대금에서 수수료를 뺀 만큼 더한다(모자라면 0 으로 두고 알린다).
  - 올해 실현 이익(data/tax_year.json, 세금 플래너): 매도의 원화 실현 손익(매입일·매도일 환율 근사)을 더한다.
    아직 입력하지 않은 해면 건드리지 않는다(기준값을 모르기 때문).
  - 계좌 성과 장부: 시작 잔고가 있으면 같은 매매를 사건으로 함께 적는다(실패해도 보유 반영은 유지, 사유를 알림).
되돌리기는 마지막 한 건만 된다(그 종목의 직전 보유·현금·더한 세금을 그대로 복원). 주문과 연결되어 있지 않다.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Optional

from core.db import get_session
from core.models import PortfolioHolding, PortfolioTrade

SIDE_WORDS = {"매수": "BUY", "buy": "BUY", "샀음": "BUY", "샀다": "BUY", "샀어": "BUY",
              "매도": "SELL", "sell": "SELL", "팔았음": "SELL", "팔았다": "SELL", "팔았어": "SELL"}
ALL_WORDS = {"전량", "전부", "all"}
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DATE_MD = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_FEE = re.compile(r"(?:수수료|fee)\s*[:=]?\s*\$?\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _parse_date(tok: str, today: date) -> Optional[date]:
    m = _DATE_ISO.match(tok)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = _DATE_MD.match(tok)
    if m:
        d = date(today.year, int(m[1]), int(m[2]))
        return d if d <= today else date(today.year - 1, d.month, d.day)
    return None


def parse_trade_text(text: str, today: Optional[date] = None) -> list[dict]:
    """줄마다 {side, ticker, quantity(None=전량), price, fee, trade_date}. 순서는 자유, '주'·'$'·'@'·',' 는 무시.
    첫 숫자 = 수량, 두 번째 숫자 = 체결 단가($). 날짜(YYYY-MM-DD 또는 M/D)가 없으면 오늘."""
    today = today or date.today()
    out: list[dict] = []
    for n, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fee = 0.0
        m = _FEE.search(line)
        if m:
            fee = float(m[1])
            line = line[:m.start()] + " " + line[m.end():]
        toks = re.sub(r"[,$@]", " ", line).replace("주", " ").replace("달러", " ").split()
        side = ticker = None
        nums: list[float] = []
        d = None
        sell_all = False
        for t in toks:
            low = t.lower()
            if low in SIDE_WORDS:
                side = SIDE_WORDS[low]
            elif low in ALL_WORDS:
                sell_all = True
            elif _parse_date(t, today):
                d = _parse_date(t, today)
            elif re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", t):
                nums.append(float(t))
            elif ticker is None and _TICKER.match(t.upper()) and t.isascii():
                ticker = t.upper()
            else:
                raise ValueError(f"{n}번째 줄: '{t}' 를 읽지 못했습니다 — 예: 'XLK 3 매도 210.5'")
        if side is None:
            raise ValueError(f"{n}번째 줄: 매수인지 매도인지 적어 주세요: {raw!r}")
        if ticker is None:
            raise ValueError(f"{n}번째 줄: 티커가 없습니다: {raw!r}")
        if sell_all and side != "SELL":
            raise ValueError(f"{n}번째 줄: '전량'은 매도에만 씁니다.")
        qty = None if sell_all else (nums.pop(0) if nums else None)
        if qty is None and not sell_all:
            raise ValueError(f"{n}번째 줄: 수량이 없습니다: {raw!r}")
        if not nums:
            raise ValueError(f"{n}번째 줄: 체결 단가($)가 없습니다 — 예: 'XLK 3 매도 210.5'")
        price = nums.pop(0)
        if nums:
            raise ValueError(f"{n}번째 줄: 숫자가 너무 많습니다(수량·단가만): {raw!r}")
        if (qty is not None and qty <= 0) or price <= 0 or not math.isfinite(price):
            raise ValueError(f"{n}번째 줄: 수량과 단가는 0보다 커야 합니다.")
        d = d or today
        if d > today:
            raise ValueError(f"{n}번째 줄: 미래 날짜입니다: {d}")
        out.append({"side": side, "ticker": ticker, "quantity": qty, "price": price, "fee": fee, "trade_date": d})
    return out


def _lots(session, ticker: str) -> list[PortfolioHolding]:
    return (session.query(PortfolioHolding).filter(PortfolioHolding.ticker == ticker)
            .order_by(PortfolioHolding.purchase_date, PortfolioHolding.id).all())


def _snapshot(lots: list[PortfolioHolding]) -> str:
    return json.dumps([{"ticker": h.ticker, "quantity": h.quantity, "purchase_price": h.purchase_price,
                        "purchase_date": h.purchase_date.isoformat(), "strategy_role": h.strategy_role,
                        "review_date": h.review_date.isoformat() if h.review_date else None, "thesis": h.thesis}
                       for h in lots], ensure_ascii=False)


def _realized_krw(lots: list[PortfolioHolding], qty: float, price: float, fee: float, d: date, fx=None) -> Optional[float]:
    """원화 실현 손익: 매도 대금(매도일 환율) − 판 몫의 원화 취득가(매입일 환율, 이동평균). 환율이 없으면 None."""
    try:
        from core import tax_planner as tp

        fx = tp.load_fx() if fx is None else fx
        total = sum(h.quantity for h in lots)
        cost = sum(h.quantity * h.purchase_price * (1 + tp.KAKAO_FEE) * tp.fx_on(fx, h.purchase_date) for h in lots)
        return (qty * price - fee) * tp.fx_on(fx, d) - cost * qty / total
    except Exception:  # noqa: BLE001 - 환율을 못 읽어도 보유 반영은 한다
        return None


def preview(trades: list[dict], holdings: Optional[list[dict]] = None) -> list[dict]:
    """저장 전 미리보기: 종목별 지금 수량 → 바뀐 수량. 보유보다 많이 팔면 오류."""
    from core.portfolio import list_holdings

    have: dict[str, float] = {}
    for h in (list_holdings() if holdings is None else holdings):
        have[h["ticker"]] = have.get(h["ticker"], 0.0) + float(h["quantity"])
    rows = []
    for t in trades:
        before = have.get(t["ticker"], 0.0)
        qty = before if t["quantity"] is None else t["quantity"]
        if t["side"] == "SELL" and qty > before + 1e-9:
            raise ValueError(f"{t['ticker']}: 기록된 보유 {before:g}주보다 많이 팔 수 없습니다({qty:g}주). "
                             "보유 기록이 실제와 다르면 '잔고 한 번에 맞추기'로 먼저 맞추세요.")
        after = before + qty if t["side"] == "BUY" else before - qty
        have[t["ticker"]] = after
        rows.append({**t, "quantity": qty, "before": before, "after": after,
                     "amount": qty * t["price"] + (t["fee"] if t["side"] == "BUY" else -t["fee"])})
    return rows


def record_trades(trades: list[dict], *, note: Optional[str] = None, fx=None, ledger: bool = True) -> list[dict]:
    """여러 건을 순서대로 반영한다(한 건씩 커밋 — 앞 건은 되돌리기로 무를 수 있다). 결과 행 목록을 돌려준다."""
    from core import tax_planner as tp
    from core.portfolio import get_cash_balance, holding_strategy_role, set_cash_balance

    results = []
    for t in preview(trades):
        msgs: list[str] = []
        cash = get_cash_balance()
        with get_session() as session:
            lots = _lots(session, t["ticker"])
            snap = _snapshot(lots)
            qty, price, fee = float(t["quantity"]), float(t["price"]), float(t["fee"])
            realized_usd = realized_krw = None
            if t["side"] == "BUY":
                session.add(PortfolioHolding(
                    ticker=t["ticker"], quantity=qty, purchase_price=price, purchase_date=t["trade_date"],
                    strategy_role=holding_strategy_role(t["ticker"], lots[0].strategy_role if lots else None),
                    thesis=(note or "").strip() or None))
                new_cash = cash - qty * price - fee
            else:
                total = sum(h.quantity for h in lots)
                avg = sum(h.quantity * h.purchase_price for h in lots) / total
                realized_usd = qty * (price - avg) - fee
                realized_krw = _realized_krw(lots, qty, price, fee, t["trade_date"], fx)
                keep = (total - qty) / total
                for h in lots:
                    if keep <= 1e-9:
                        session.delete(h)
                    else:
                        h.quantity = h.quantity * keep
                new_cash = cash + qty * price - fee
            if new_cash < -0.005:
                msgs.append(f"현금 기록(${cash:,.2f})이 매수 금액보다 적어 0 으로 두었습니다 — 실제 예수금을 '현금 잔고'에서 맞추세요.")
            row = PortfolioTrade(trade_date=t["trade_date"], side=t["side"], ticker=t["ticker"], quantity=qty,
                                 price_usd=price, fee_usd=fee, realized_usd=realized_usd, realized_krw=realized_krw,
                                 cash_before=cash, lots_before=snap, note=(note or "").strip() or None)
            session.add(row)
            session.flush()
            trade_id = row.id
        set_cash_balance(max(0.0, new_cash))
        tax_added = None
        if realized_krw is not None:
            year = t["trade_date"].year
            base = tp.load_realized(year)
            if base is None:
                msgs.append(f"{year}년 실현 이익을 아직 입력하지 않아 세금 플래너에 더하지 않았습니다('세후 수익 계산' 화면).")
            else:
                tp.save_realized(year, base + realized_krw)
                tax_added = realized_krw
        elif t["side"] == "SELL":
            msgs.append("환율을 읽지 못해 원화 실현 손익을 계산하지 못했습니다 — 세금 플래너의 올해 실현 이익을 직접 고쳐 주세요.")
        ledger_id = None
        if ledger:
            try:
                from core import portfolio_account_history as ah

                if ah.load_ledger() is not None:
                    ledger_id = ah.append_event(t["trade_date"], t["side"], ticker=t["ticker"], quantity=qty,
                                                price_usd=price, fee_usd=fee)
            except Exception as exc:  # noqa: BLE001 - 장부는 보조 기록
                msgs.append(f"계좌 성과 장부에는 적지 못했습니다: {exc}")
        with get_session() as session:
            row = session.get(PortfolioTrade, trade_id)
            row.tax_added_krw, row.ledger_event_id = tax_added, ledger_id
        results.append({**t, "id": trade_id, "quantity": qty, "realized_usd": realized_usd, "realized_krw": realized_krw,
                        "cash_after": max(0.0, new_cash), "messages": msgs})
    return results


def list_trades(limit: int = 50) -> list[dict]:
    with get_session() as session:
        rows = session.query(PortfolioTrade).order_by(PortfolioTrade.id.desc()).limit(limit).all()
        return [{"id": r.id, "trade_date": r.trade_date, "side": r.side, "ticker": r.ticker, "quantity": r.quantity,
                 "price_usd": r.price_usd, "fee_usd": r.fee_usd, "realized_usd": r.realized_usd,
                 "realized_krw": r.realized_krw, "note": r.note} for r in rows]


def undo_last_trade() -> dict:
    """마지막 한 건을 무른다: 그 종목 보유 기록·현금·세금 플래너에 더한 금액·장부 사건을 직전 상태로."""
    from core import tax_planner as tp
    from core.portfolio import set_cash_balance

    with get_session() as session:
        row = session.query(PortfolioTrade).order_by(PortfolioTrade.id.desc()).first()
        if row is None:
            raise ValueError("되돌릴 매매 기록이 없습니다.")
        info = {"id": row.id, "side": row.side, "ticker": row.ticker, "quantity": row.quantity,
                "trade_date": row.trade_date, "messages": []}
        for h in _lots(session, row.ticker):
            session.delete(h)
        for lot in json.loads(row.lots_before):
            session.add(PortfolioHolding(
                ticker=lot["ticker"], quantity=lot["quantity"], purchase_price=lot["purchase_price"],
                purchase_date=date.fromisoformat(lot["purchase_date"]), strategy_role=lot.get("strategy_role"),
                review_date=date.fromisoformat(lot["review_date"]) if lot.get("review_date") else None,
                thesis=lot.get("thesis")))
        cash_before, tax_added, ledger_id, year = row.cash_before, row.tax_added_krw, row.ledger_event_id, row.trade_date.year
        session.delete(row)
    if cash_before is not None:
        set_cash_balance(cash_before)
    if tax_added:
        base = tp.load_realized(year)
        if base is not None:
            tp.save_realized(year, base - tax_added)
    if ledger_id is not None:
        try:
            from core.models import PortfolioPerformanceEvent

            with get_session() as session:
                last = (session.query(PortfolioPerformanceEvent)
                        .order_by(PortfolioPerformanceEvent.as_of.desc(), PortfolioPerformanceEvent.id.desc()).first())
                if last is not None and last.id == ledger_id:
                    session.delete(last)
                else:
                    info["messages"].append("계좌 성과 장부의 사건은 마지막 사건이 아니라 그대로 두었습니다.")
        except Exception as exc:  # noqa: BLE001
            info["messages"].append(f"계좌 성과 장부 사건을 지우지 못했습니다: {exc}")
    return info


def format_result(r: dict) -> str:
    side = "매수" if r["side"] == "BUY" else "매도"
    s = f"{r['trade_date']} {r['ticker']} {r['quantity']:g}주 {side} @ ${r['price']:,.2f}"
    if r.get("realized_usd") is not None:
        s += f" · 실현 ${r['realized_usd']:,.2f}"
        if r.get("realized_krw") is not None:
            s += f" (약 {r['realized_krw']:,.0f}원)"
    s += f" · 현금 ${r['cash_after']:,.2f}"
    return s + "".join(f"\n  ⚠ {m}" for m in r.get("messages") or [])
