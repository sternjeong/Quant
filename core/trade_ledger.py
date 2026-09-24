"""옵트인 체결 원장 백테스트 (ENG-01).

기존 core.backtest_engine.compute_equity_curve (close.pct_change() * shift(1)) 경로는 기준선으로
그대로 유지된다. 이 모듈은 그와 별개로 다음을 제공하는 새 경로이며, 호출하지 않으면 아무 영향이 없다.

1. 체결 모델: 신호일 t 종가 이후 확정된 목표 비중을 t+1(다음 거래일) 시가(Open)에서 체결한다.
   t+1 시가와 t 종가 사이의 갭 손익은 체결 전 기존 보유분에 그대로 반영된다.
   마지막 날의 신호는 체결할 다음 거래일이 없어 체결되지 않는다(미체결로 남김).
2. 비용 분리: 수수료(fee_bps, 매수·매도 양쪽 명목금액), 슬리피지(slippage_bps, 매수는 시가보다
   불리하게 높게·매도는 낮게 체결), 세금(tax_bps, 매도 명목금액에만)을 각각 별도 기록한다.
3. 거래 원장: 수량·현금·NAV와 신호 시각/체결 시각을 행 단위로 남긴다.

기업행동(배당·분할) 처리: 기본값은 여전히 미반영이다(기존 동작 불변). 옵트인으로
run_ledger_backtest(corporate_actions=...) 에 기업행동 목록(core.corporate_actions.CorporateAction
또는 같은 필드의 dict)을 주면 (a) 현금배당 ex-date 에 '그날 체결 전 보유 수량 x 주당 배당금'을
현금으로 입금해 NAV 에 반영하고 원장에 side="dividend" 행을 남기며, (b) 분할 ex-date 에 보유
수량을 비율만큼 곱하고 평균 취득단가를 같은 비율로 나눈다. 분할은 원장 행이 아니라
결과의 corporate_actions 표에 기록한다. 인자를 주지 않으면 아래 설명대로 완전히 종전과 같다.

주의: 분할 조정은 '분할이 반영되지 않은 원시 가격'과 함께 써야 한다. 이미 분할이 소급 반영된
가격(대부분의 yfinance 캐시)에 분할 조정을 또 적용하면 이중 계산이 된다. 마찬가지로 조정가격
(Adj Close 기준)에 배당 현금을 더하면 배당이 이중 계산된다. 선택은 호출자 책임이다.

이하 기본 경로 설명: 입력 DataFrame의 Open/Close를 그대로 쓰며,
core.market_data 는 auto_adjust=False 로 받는다. 실제 캐시 데이터(AAPL 2020-08 분할 구간 확인)에서
Close 는 분할이 이미 소급 반영돼 있고 배당만 반영되지 않았다(Adj Close 가 배당까지 반영). 따라서
캐시 데이터에서 adjust_ohlc_by_adj_close 의 실제 효과는 분할 보정이 아니라 배당 재투자 가정의
총수익 기준 전환이다. 분할이 반영되지 않은 원시 가격을 넣으면 분할 구간이 왜곡된다(합성 테스트로 확인).
현금배당 원장은 위의 corporate_actions 옵트인에서만 동작한다. 조정가격 사용은 호출자가 명시적으로 선택해야 한다.

주의: 이 모듈의 수치는 실행 모델 검증용이며 실제 성과 주장에 쓰지 않는다. 비용 시나리오의 수수료/
슬리피지 배분은 가정값이며 특정 증권사 요율이 아니다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

# 편도 총비용 5/10/25bp 시나리오(수수료+슬리피지). 배분은 가정. 세금은 별도 파라미터.
COST_SCENARIOS_BPS = {
    "5bp": {"fee_bps": 2.0, "slippage_bps": 3.0},
    "10bp": {"fee_bps": 4.0, "slippage_bps": 6.0},
    "25bp": {"fee_bps": 10.0, "slippage_bps": 15.0},
}

PRICE_BASIS_ADJUSTED = "adjusted OHLC (Adj Close/Close ratio applied to Open/High/Low/Close)"
DIVIDEND_NOTE_RAW = ("배당 현금 유입 미반영: 배당 수익이 누락된다(분할이 반영되지 않은 원시 가격이면 분할 구간도 왜곡된다)")
DIVIDEND_NOTE_ADJUSTED = ("배당 현금 유입은 별도 원장으로 반영하지 않음: 조정가격은 배당을 즉시 재투자한 "
                          "총수익 근사이며 실제 배당 지급일 현금흐름·배당세와 다르다")
DIVIDEND_NOTE_MODELED = ("현금배당을 ex-date 에 '체결 전 보유 수량 x 주당 배당금'만큼 현금 입금으로 반영했다"
                         "(배당세·재투자 지연 미반영). 조정가격과 함께 쓰면 배당이 이중 계산된다")

CORPORATE_ACTION_COLUMNS = [
    "date", "type", "symbol", "ex_date", "amount", "split_ratio",
    "shares_before", "shares_after", "cash_delta", "basis_before", "basis_after",
    "applied", "reason",
]

LEDGER_COLUMNS = [
    "signal_time", "fill_time", "side", "quantity", "ref_open", "fill_price",
    "notional", "fee", "slippage_cost", "tax", "cash_after", "shares_after", "nav_after",
]


@dataclass
class LedgerBacktestResult:
    ledger: pd.DataFrame  # 체결 1건당 1행 (LEDGER_COLUMNS)
    daily: pd.DataFrame  # 일별 종가 기준 cash/shares/nav
    nav: pd.Series  # 종가 기준 NAV (일별)
    total_fee: float = 0.0
    total_slippage_cost: float = 0.0
    total_tax: float = 0.0
    params: dict = field(default_factory=dict)
    # 옵트인 기업행동 경로에서만 채워진다(미사용 시 빈 표 / 0.0).
    corporate_actions: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=CORPORATE_ACTION_COLUMNS))
    total_dividend_cash: float = 0.0
    final_cost_basis: float = 0.0  # 평균 취득단가(분할 조정 반영). 보유 없으면 0.0


def adjust_ohlc_by_adj_close(df: pd.DataFrame) -> pd.DataFrame:
    """Adj Close/Close 비율로 Open/High/Low/Close 를 동일하게 조정한 사본을 반환한다.

    Adj Close 는 배당(및 분할이 반영되지 않은 입력이면 분할) 조정계수를 일자별로 담는다. 실제 캐시 데이터에서는 배당 조정이 주된 효과다. Adj Close 는 그대로 두며
    Volume 은 조정하지 않는다. 입력은 변경하지 않는다.
    """
    if "Adj Close" not in df.columns or "Close" not in df.columns:
        raise ValueError("df 에 Adj Close, Close 컬럼이 필요합니다")
    out = df.copy()
    ratio = out["Adj Close"].astype(float) / out["Close"].astype(float)
    for col in ("Open", "High", "Low", "Close"):
        if col in out.columns:
            out[col] = out[col].astype(float) * ratio
    return out


def _action_field(action, name):
    """CorporateAction 데이터클래스와 dict 를 같이 받는다."""
    if isinstance(action, dict):
        return action.get(name)
    return getattr(action, name, None)


def _normalize_corporate_actions(actions, index: pd.DatetimeIndex) -> tuple[dict, list[dict]]:
    """기업행동을 {인덱스 위치: [정규화 dict]} 와 미적용 사유 목록으로 나눈다.

    ex_date 가 없거나 df 인덱스의 거래일이 아니면 적용하지 않고 사유를 남긴다(추측 금지).
    """
    by_date: dict[pd.Timestamp, int] = {}
    for i, ts in enumerate(index):
        by_date.setdefault(pd.Timestamp(ts).normalize(), i)
    events: dict[int, list[dict]] = {}
    skipped: list[dict] = []
    for action in actions or []:
        kind = _action_field(action, "type") or "unknown"
        symbol = _action_field(action, "symbol") or ""
        ex_raw = _action_field(action, "ex_date")
        amount = _action_field(action, "amount")
        ratio = _action_field(action, "split_ratio")
        row = {"type": kind, "symbol": symbol, "ex_date": ex_raw,
               "amount": amount, "split_ratio": ratio}
        if kind not in ("cash_dividend", "special_cash_dividend", "forward_split", "reverse_split"):
            skipped.append({**row, "reason": f"unsupported type: {kind}"})
            continue
        if kind in ("cash_dividend", "special_cash_dividend") and not (isinstance(amount, (int, float)) and amount > 0):
            skipped.append({**row, "reason": "missing or non-positive dividend amount"})
            continue
        if kind in ("forward_split", "reverse_split") and not (isinstance(ratio, (int, float)) and ratio > 0):
            skipped.append({**row, "reason": "missing or non-positive split ratio"})
            continue
        if ex_raw is None:
            skipped.append({**row, "reason": "missing ex_date"})
            continue
        try:
            ts = pd.Timestamp(ex_raw).normalize()
        except (ValueError, TypeError):
            skipped.append({**row, "reason": "unparsable ex_date"})
            continue
        pos = by_date.get(ts)
        if pos is None:
            skipped.append({**row, "reason": "ex_date not a session in the price index"})
            continue
        events.setdefault(pos, []).append(row)
    # 같은 날에는 분할을 먼저(수량 기준 정렬) 적용한 뒤 배당을 지급한다.
    for pos in events:
        events[pos].sort(key=lambda r: 0 if r["type"].endswith("split") else 1)
    return events, skipped


def run_ledger_backtest(
    df: pd.DataFrame,
    position: pd.Series,
    initial_cash: float = 100.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    tax_bps: float = 0.0,
    integer_shares: bool = False,
    price_basis: Optional[str] = None,
    corporate_actions=None,
    buy_slippage_bps: Optional[float] = None,
    sell_slippage_bps: Optional[float] = None,
) -> LedgerBacktestResult:
    """목표 비중(0~1) 시리즈를 다음 거래일 시가 체결 원장으로 시뮬레이션한다.

    corporate_actions: None(기본)이면 기업행동을 전혀 반영하지 않는다(종전과 동일).
    주어지면 core.corporate_actions.CorporateAction 또는 같은 필드의 dict 목록으로 보고,
    ex-date 당일 시가 체결 **전에** 배당 현금 입금·분할 수량/단가 조정을 적용한다.

    buy_slippage_bps/sell_slippage_bps: None(기본)이면 slippage_bps 를 양쪽에 쓴다(종전과 동일).
    주어지면 해당 방향만 이 값으로 덮어쓴다. 실측 교정용이라 음수(유리한 체결)도 허용하되 -10000bp 초과만 막는다.

    df: Open/Close 컬럼과 DatetimeIndex. position: 신호일(종가 기준) 목표 비중, df 와 같은 인덱스.
    integer_shares=True 면 매수/매도 수량을 정수로 내림한다(기본은 소수 주 허용).
    NAV 는 일별 종가로 평가한 cash + shares * Close 이다.
    """
    if not {"Open", "Close"}.issubset(df.columns):
        raise ValueError("df 에 Open, Close 컬럼이 필요합니다")
    if min(fee_bps, slippage_bps, tax_bps) < 0:
        raise ValueError("비용 bps 는 음수일 수 없습니다")
    pos = position.reindex(df.index).fillna(0.0).astype(float).clip(0.0, 1.0)
    for _v in (buy_slippage_bps, sell_slippage_bps):
        if _v is not None and _v <= -1e4:
            raise ValueError("방향별 슬리피지 bps 는 -10000 보다 커야 합니다")
    fee_r, slip_r, tax_r = fee_bps / 1e4, slippage_bps / 1e4, tax_bps / 1e4
    slip_buy = slip_r if buy_slippage_bps is None else buy_slippage_bps / 1e4
    slip_sell = slip_r if sell_slippage_bps is None else sell_slippage_bps / 1e4

    cash = float(initial_cash)
    shares = 0.0
    rows = []
    daily = []
    idx = df.index
    opens = df["Open"].astype(float).values
    closes = df["Close"].astype(float).values

    basis = 0.0  # 평균 취득단가
    ca_rows: list[dict] = []
    total_dividend_cash = 0.0
    ca_events, ca_skipped = ({}, [])
    if corporate_actions is not None:
        ca_events, ca_skipped = _normalize_corporate_actions(corporate_actions, idx)
        for row in ca_skipped:
            ca_rows.append({**{c: None for c in CORPORATE_ACTION_COLUMNS}, **row,
                            "date": None, "applied": False})

    for i, ts in enumerate(idx):
        # 기업행동은 그날 체결 전(= 전일 종가 기준 보유 수량)에 적용한다.
        for ev in ca_events.get(i, ()):  # corporate_actions=None 이면 항상 비어 있다
            shares_before, basis_before, cash_delta = shares, basis, 0.0
            if ev["type"] in ("forward_split", "reverse_split"):
                ratio = float(ev["split_ratio"])
                shares = shares * ratio
                basis = basis / ratio if ratio else basis
            else:  # 현금배당
                cash_delta = shares * float(ev["amount"])
                cash += cash_delta
                total_dividend_cash += cash_delta
                if cash_delta > 0:
                    rows.append({
                        "signal_time": ts, "fill_time": ts, "side": "dividend",
                        "quantity": shares, "ref_open": float(ev["amount"]),
                        "fill_price": float(ev["amount"]), "notional": cash_delta,
                        "fee": 0.0, "slippage_cost": 0.0, "tax": 0.0,
                        "cash_after": cash, "shares_after": shares,
                        "nav_after": cash + shares * opens[i],
                    })
            ca_rows.append({"date": ts, "type": ev["type"], "symbol": ev["symbol"],
                            "ex_date": ev["ex_date"], "amount": ev["amount"],
                            "split_ratio": ev["split_ratio"], "shares_before": shares_before,
                            "shares_after": shares, "cash_delta": cash_delta,
                            "basis_before": basis_before, "basis_after": basis,
                            "applied": True, "reason": None})
        # 전일 신호를 오늘 시가에 체결
        if i > 0:
            target_w = float(pos.iloc[i - 1])
            op = opens[i]
            nav_open = cash + shares * op
            target_shares = target_w * nav_open / op if op > 0 else shares
            delta = target_shares - shares
            side = None
            qty = 0.0
            if delta > 1e-12:  # 매수
                px = op * (1 + slip_buy)
                qty = delta
                max_qty = cash / (px * (1 + fee_r)) if px > 0 else 0.0
                qty = min(qty, max_qty)
                if integer_shares:
                    qty = math.floor(qty + 1e-9)
                side = "BUY"
            elif delta < -1e-12:  # 매도
                px = op * (1 - slip_sell)
                qty = min(-delta, shares)
                if integer_shares:
                    qty = math.floor(qty + 1e-9)
                side = "SELL"
            if side and qty > 1e-12:
                notional = qty * px
                fee = notional * fee_r
                slip_cost = qty * op * (slip_buy if side == "BUY" else slip_sell)
                if side == "BUY":
                    tax = 0.0
                    cash -= notional + fee
                    basis = ((basis * shares) + notional + fee) / (shares + qty) if (shares + qty) > 0 else 0.0
                    shares += qty
                else:
                    tax = notional * tax_r
                    cash += notional - fee - tax
                    shares -= qty
                rows.append({
                    "signal_time": idx[i - 1], "fill_time": ts, "side": side, "quantity": qty,
                    "ref_open": op, "fill_price": px, "notional": notional, "fee": fee,
                    "slippage_cost": slip_cost, "tax": tax, "cash_after": cash,
                    "shares_after": shares, "nav_after": cash + shares * op,
                })
        daily.append({"date": ts, "cash": cash, "shares": shares, "nav": cash + shares * closes[i]})

    daily_df = pd.DataFrame(daily).set_index("date")
    ledger = pd.DataFrame(rows, columns=LEDGER_COLUMNS)
    ca_df = pd.DataFrame(ca_rows, columns=CORPORATE_ACTION_COLUMNS)
    # 실제로 현금이 들어왔을 때만 True(배당일에 보유가 0이면 NAV 에 반영된 배당 현금흐름이 없다).
    dividends_applied = bool(float(total_dividend_cash) > 0)
    splits_applied = bool(len(ca_df)) and bool((ca_df["applied"].astype(bool) & ca_df["type"].isin(
        ["forward_split", "reverse_split"])).any())
    if dividends_applied:
        dividend_note = DIVIDEND_NOTE_MODELED
    else:
        dividend_note = DIVIDEND_NOTE_ADJUSTED if price_basis == PRICE_BASIS_ADJUSTED else DIVIDEND_NOTE_RAW
    return LedgerBacktestResult(
        ledger=ledger,
        daily=daily_df,
        nav=daily_df["nav"],
        total_fee=float(ledger["fee"].sum()) if len(ledger) else 0.0,
        total_slippage_cost=float(ledger["slippage_cost"].sum()) if len(ledger) else 0.0,
        total_tax=float(ledger["tax"].sum()) if len(ledger) else 0.0,
        corporate_actions=ca_df,
        total_dividend_cash=float(total_dividend_cash),
        final_cost_basis=float(basis),
        params={"initial_cash": initial_cash, "fee_bps": fee_bps, "slippage_bps": slippage_bps,
                "tax_bps": tax_bps, "integer_shares": integer_shares,
                "price_basis": price_basis or "unadjusted Open/Close as given (no corporate actions)",
                "dividend_cash_flow_modeled": dividends_applied,
                "split_adjustment_modeled": splits_applied,
                "corporate_actions_provided": corporate_actions is not None,
                "corporate_actions_applied": int(ca_df["applied"].astype(bool).sum()) if len(ca_df) else 0,
                "corporate_actions_skipped": len(ca_skipped),
                "dividend_note": dividend_note},
    )


def run_cost_scenarios(
    df: pd.DataFrame,
    position: pd.Series,
    initial_cash: float = 100.0,
    tax_bps: float = 0.0,
    integer_shares: bool = False,
    scenarios: Optional[dict] = None,
    price_basis: Optional[str] = None,
    corporate_actions=None,
    measured_calibration: Optional[dict] = None,
) -> dict:
    """비용 없음(0bp)과 5/10/25bp 시나리오를 한 번에 실행해 {이름: LedgerBacktestResult} 로 반환.

    measured_calibration(옵트인, 기본 None): core.cost_calibration 의 결과 dict. status=="ok" 이고
    scenario 가 있을 때만 'measured' 시나리오를 추가한다(표본 부족·unavailable 이면 아무것도 추가하지
    않으며 가정값으로 대체하지도 않는다). 추가된 결과의 params 에 표본 수·산출 시각·라벨을 남긴다.
    """
    sc = {"0bp": {"fee_bps": 0.0, "slippage_bps": 0.0}}
    sc.update(scenarios or COST_SCENARIOS_BPS)
    out = {
        name: run_ledger_backtest(df, position, initial_cash, tax_bps=tax_bps,
                                  integer_shares=integer_shares, price_basis=price_basis,
                                  corporate_actions=corporate_actions, **kw)
        for name, kw in sc.items()
    }
    cal = measured_calibration
    if cal and cal.get("status") == "ok" and cal.get("scenario"):
        m = cal["scenario"]
        res = run_ledger_backtest(
            df, position, initial_cash, tax_bps=tax_bps, integer_shares=integer_shares,
            price_basis=price_basis, corporate_actions=corporate_actions,
            fee_bps=float(m.get("fee_bps", 0.0)), slippage_bps=float(m["slippage_bps"]),
            buy_slippage_bps=m.get("buy_slippage_bps"), sell_slippage_bps=m.get("sell_slippage_bps"))
        res.params.update({
            "scenario_label": "measured vs assumed",
            "measured_sample_n": cal.get("n"),
            "measured_generated_at": cal.get("generated_at"),
            "measured_stale": bool(cal.get("stale", False)),
            "measured_fee_note": m.get("fee_note"),
            "measured_side_split": m.get("side_split"),
        })
        out["measured"] = res
    return out
