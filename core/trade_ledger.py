"""옵트인 체결 원장 백테스트 (ENG-01).

기존 core.backtest_engine.compute_equity_curve (close.pct_change() * shift(1)) 경로는 기준선으로
그대로 유지된다. 이 모듈은 그와 별개로 다음을 제공하는 새 경로이며, 호출하지 않으면 아무 영향이 없다.

1. 체결 모델: 신호일 t 종가 이후 확정된 목표 비중을 t+1(다음 거래일) 시가(Open)에서 체결한다.
   t+1 시가와 t 종가 사이의 갭 손익은 체결 전 기존 보유분에 그대로 반영된다.
   마지막 날의 신호는 체결할 다음 거래일이 없어 체결되지 않는다(미체결로 남김).
2. 비용 분리: 수수료(fee_bps, 매수·매도 양쪽 명목금액), 슬리피지(slippage_bps, 매수는 시가보다
   불리하게 높게·매도는 낮게 체결), 세금(tax_bps, 매도 명목금액에만)을 각각 별도 기록한다.
3. 거래 원장: 수량·현금·NAV와 신호 시각/체결 시각을 행 단위로 남긴다.

기업행동(배당·분할) 처리: 구현하지 않았다. 입력 DataFrame의 Open/Close를 그대로 쓰며,
core.market_data 는 auto_adjust=False 로 받는다. 실제 캐시 데이터(AAPL 2020-08 분할 구간 확인)에서
Close 는 분할이 이미 소급 반영돼 있고 배당만 반영되지 않았다(Adj Close 가 배당까지 반영). 따라서
캐시 데이터에서 adjust_ohlc_by_adj_close 의 실제 효과는 분할 보정이 아니라 배당 재투자 가정의
총수익 기준 전환이다. 분할이 반영되지 않은 원시 가격을 넣으면 분할 구간이 왜곡된다(합성 테스트로 확인).
현금배당 원장은 미구현이다. 조정가격 사용은 호출자가 명시적으로 선택해야 한다.

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


def run_ledger_backtest(
    df: pd.DataFrame,
    position: pd.Series,
    initial_cash: float = 100.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    tax_bps: float = 0.0,
    integer_shares: bool = False,
    price_basis: Optional[str] = None,
) -> LedgerBacktestResult:
    """목표 비중(0~1) 시리즈를 다음 거래일 시가 체결 원장으로 시뮬레이션한다.

    df: Open/Close 컬럼과 DatetimeIndex. position: 신호일(종가 기준) 목표 비중, df 와 같은 인덱스.
    integer_shares=True 면 매수/매도 수량을 정수로 내림한다(기본은 소수 주 허용).
    NAV 는 일별 종가로 평가한 cash + shares * Close 이다.
    """
    if not {"Open", "Close"}.issubset(df.columns):
        raise ValueError("df 에 Open, Close 컬럼이 필요합니다")
    if min(fee_bps, slippage_bps, tax_bps) < 0:
        raise ValueError("비용 bps 는 음수일 수 없습니다")
    pos = position.reindex(df.index).fillna(0.0).astype(float).clip(0.0, 1.0)
    fee_r, slip_r, tax_r = fee_bps / 1e4, slippage_bps / 1e4, tax_bps / 1e4

    cash = float(initial_cash)
    shares = 0.0
    rows = []
    daily = []
    idx = df.index
    opens = df["Open"].astype(float).values
    closes = df["Close"].astype(float).values

    for i, ts in enumerate(idx):
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
                px = op * (1 + slip_r)
                qty = delta
                max_qty = cash / (px * (1 + fee_r)) if px > 0 else 0.0
                qty = min(qty, max_qty)
                if integer_shares:
                    qty = math.floor(qty + 1e-9)
                side = "BUY"
            elif delta < -1e-12:  # 매도
                px = op * (1 - slip_r)
                qty = min(-delta, shares)
                if integer_shares:
                    qty = math.floor(qty + 1e-9)
                side = "SELL"
            if side and qty > 1e-12:
                notional = qty * px
                fee = notional * fee_r
                slip_cost = qty * op * slip_r
                if side == "BUY":
                    tax = 0.0
                    cash -= notional + fee
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
    return LedgerBacktestResult(
        ledger=ledger,
        daily=daily_df,
        nav=daily_df["nav"],
        total_fee=float(ledger["fee"].sum()) if len(ledger) else 0.0,
        total_slippage_cost=float(ledger["slippage_cost"].sum()) if len(ledger) else 0.0,
        total_tax=float(ledger["tax"].sum()) if len(ledger) else 0.0,
        params={"initial_cash": initial_cash, "fee_bps": fee_bps, "slippage_bps": slippage_bps,
                "tax_bps": tax_bps, "integer_shares": integer_shares,
                "price_basis": price_basis or "unadjusted Open/Close as given (no corporate actions)",
                "dividend_cash_flow_modeled": False,
                "dividend_note": DIVIDEND_NOTE_ADJUSTED if price_basis == PRICE_BASIS_ADJUSTED else DIVIDEND_NOTE_RAW},
    )


def run_cost_scenarios(
    df: pd.DataFrame,
    position: pd.Series,
    initial_cash: float = 100.0,
    tax_bps: float = 0.0,
    integer_shares: bool = False,
    scenarios: Optional[dict] = None,
    price_basis: Optional[str] = None,
) -> dict:
    """비용 없음(0bp)과 5/10/25bp 시나리오를 한 번에 실행해 {이름: LedgerBacktestResult} 로 반환."""
    sc = {"0bp": {"fee_bps": 0.0, "slippage_bps": 0.0}}
    sc.update(scenarios or COST_SCENARIOS_BPS)
    return {
        name: run_ledger_backtest(df, position, initial_cash, tax_bps=tax_bps,
                                  integer_shares=integer_shares, price_basis=price_basis, **kw)
        for name, kw in sc.items()
    }
