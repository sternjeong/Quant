"""3단계: 한국 거주자 해외주식 양도소득세를 코어 슬리브의 실현손익 패턴에 적용.

세율/공제 기준(2026-09-14 웹검색으로 확인, 하드코딩 아님 — 이번 실행에서 실제로 검색해 확인):
  - 세율 22%(양도소득세 20% + 지방소득세 2%) — 국내 거주자의 해외주식(미국 ETF 포함) 양도소득에
    적용되는 분류과세 세율. 손익통산은 같은 과세연도(1/1~12/31) 내 모든 해외주식 거래에 대해서만
    허용되고, 연도를 넘긴 이월공제(loss carryforward)는 없다(국세청 해외주식 양도소득세 안내 기준).
  - 기본공제: 과세연도당 250만원(전체 해외주식 양도소득 합산 기준, 종목/거래횟수 무관하게 1회).
  출처: 국세청(nts.go.kr) 해외주식 양도소득세 안내, 미래에셋증권/유안타증권 고객센터 안내,
        calculatorhost.com "해외주식 양도소득세 2026" 요약(2026-09-14 웹검색 확인).

방법론(단순화, 명시):
  - 코어(17자산 로테이션) 슬리브만 시뮬레이션한다 — 새틀라이트는 반기 point-in-time 재구성이라
    가격 이력 조회 비용이 커서 이번 세금 시뮬레이션에서는 코어만 우선 감사하고, 새틀라이트는 매매
    빈도(연 최대 6회 편도, 반기 완전교체에 가까움)가 코어보다 훨씬 낮아 세금 총량 기여가 작다는
    점을 정성적으로만 언급한다(step1 매매횟수 비교 참고).
  - 각 티커의 보유구간(연속으로 weight>0인 구간)을 진입/청산으로 식별해 "거래"로 취급한다.
    시장필터(200일선 하회 시 코어 비중 0.5배 축소)로 인한 부분 트리밍은 무시한다(과세 이벤트를
    다소 과소 추정하는 단순화 — 실제로는 트리밍도 일부 실현손익을 만들어내므로, 이 시뮬레이션의
    세금 총액은 오히려 실제보다 "덜 나쁜 쪽"으로 편향돼 있음을 유의).
  - 실현손익은 (청산가/진입가-1)*진입시점 포지션 명목가치 - 왕복거래비용(conservative_0.5pct_rt
    시나리오, 0.5%)으로 계산한다. 원화 환산은 청산일 기준 DEXKOUS(원/달러) 종가를 사용한다(실제로는
    진입시점 환율 대비 청산시점 환율 변동분도 별도로 과세대상 환차익/환차손이 되지만, 이 시뮬레이션은
    "청산일 환율로 전체를 환산"하는 근사치를 쓴다 — 환율 자체의 방향성이 없다면 장기적으로 상쇄되는
    2차 효과로 간주하고 근사한다. 원/달러 변동성이 컸던 해는 이 근사가 부정확할 수 있음을 명시).
  - 계좌 규모(원화 총자본) 시나리오별로 연간 실현손익을 스케일링해 공제 250만원의 상대적 효과가
    계좌 크기에 따라 달라지는 것을 보여준다: 3천만원/1억원/3억원.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKTREE_ROOT))

import numpy as np
import pandas as pd

from core.champion_strategy import (
    CORE_UNIVERSE, MARKET_FILTER_TICKER, BACKTEST_WARMUP_DAYS, CORE_WEIGHT,
    _build_core_weights, _closes_from_histories,
)
from core.market_data import get_multiple_price_history

OUT_DIR = Path(__file__).resolve().parent
FULL_START = "2019-08-12"
FULL_END = "2026-09-14"
TAX_RATE = 0.22          # 2026-09-14 웹검색 확인: 양도소득세 20% + 지방소득세 2%
ANNUAL_DEDUCTION_KRW = 2_500_000  # 2026-09-14 웹검색 확인: 해외주식 양도소득 기본공제 250만원/년
ROUNDTRIP_COST_PCT = 0.005  # conservative_0.5pct_rt 시나리오와 동일(왕복 0.5%)
ACCOUNT_SIZES_KRW = [30_000_000, 100_000_000, 300_000_000]


def log(msg):
    print(f"[step3] {msg}", flush=True)


def load_dexkous() -> pd.Series:
    df = pd.read_csv(WORKTREE_ROOT / "data" / "cache" / "fred_DEXKOUS.csv", index_col=0, parse_dates=True)
    return df.iloc[:, 0].dropna()


def main():
    tickers = list(CORE_UNIVERSE)
    fetch_start = (pd.Timestamp(FULL_START) - pd.DateOffset(days=BACKTEST_WARMUP_DAYS)).date().isoformat()
    histories = get_multiple_price_history(tickers + [MARKET_FILTER_TICKER], start=fetch_start, end=FULL_END, interval="1d")
    closes_all = _closes_from_histories(histories, tickers + [MARKET_FILTER_TICKER])
    closes = closes_all[[t for t in tickers if t in closes_all.columns]]
    market_close = closes_all[MARKET_FILTER_TICKER]

    weights_full = _build_core_weights(closes, market_close, apply_market_filter=True)
    sliced_idx = closes.index[(closes.index >= pd.Timestamp(FULL_START)) & (closes.index <= pd.Timestamp(FULL_END))]
    closes_sliced = closes.loc[sliced_idx]
    weights_sliced = weights_full.loc[sliced_idx]

    fx = load_dexkous()

    def fx_rate_on_or_before(dt: pd.Timestamp) -> float:
        s = fx[fx.index <= dt]
        return float(s.iloc[-1]) if len(s) else float(fx.iloc[-1])

    # ---- 티커별 보유구간(진입~청산) 추출 ----
    trades = []
    for ticker in closes_sliced.columns:
        w = weights_sliced[ticker]
        held = w > 0
        # 진입일: held가 False->True로 바뀐 날, 청산일: True->False로 바뀐 날(그 전날까지 보유)
        change = held.astype(int).diff().fillna(held.astype(int).iloc[0])
        entry_dates = held.index[change == 1]
        exit_dates = held.index[change == -1]
        # 기간 끝까지 보유 중인 포지션은 "미실현"이므로 세금 시뮬레이션(실현손익 기준)에서 제외
        entry_dates = list(entry_dates)
        exit_dates = list(exit_dates)
        for entry_dt in entry_dates:
            later_exits = [d for d in exit_dates if d > entry_dt]
            if not later_exits:
                continue  # 기말까지 보유 -> 미실현, 제외
            exit_dt = later_exits[0]
            exit_dates.remove(exit_dt)
            entry_price = float(closes_sliced.loc[entry_dt, ticker])
            # 청산일의 직전 거래일 종가로 청산(진입과 동일 관례 - 신호 다음날 체결 가정과 정합적으로
            # 청산일 당일 종가 사용, 단순화)
            exit_price = float(closes_sliced.loc[exit_dt, ticker])
            weight_at_entry = float(weights_sliced.loc[entry_dt, ticker])
            gross_ret_pct = exit_price / entry_price - 1.0
            net_ret_pct = gross_ret_pct - ROUNDTRIP_COST_PCT
            fx_rate = fx_rate_on_or_before(exit_dt)
            trades.append({
                "ticker": ticker, "entry_date": str(entry_dt.date()), "exit_date": str(exit_dt.date()),
                "entry_price": entry_price, "exit_price": exit_price, "weight_at_entry": weight_at_entry,
                "gross_ret_pct": gross_ret_pct, "net_ret_pct": net_ret_pct, "fx_rate_krw_per_usd": fx_rate,
                "exit_year": exit_dt.year,
            })

    trades_df = pd.DataFrame(trades)
    log(f"코어 실현 거래(진입~청산 완료된 것만) 총 {len(trades_df)}건, "
        f"연도범위 {trades_df['exit_year'].min()}~{trades_df['exit_year'].max()}")
    trades_df.to_csv(OUT_DIR / "core_realized_trades.csv", index=False)

    # ---- 계좌 규모별 연간 실현손익(원화) 집계 + 세금 계산 ----
    account_results = {}
    for account_krw in ACCOUNT_SIZES_KRW:
        core_capital_krw = account_krw * CORE_WEIGHT  # CORE_WEIGHT=0.85 — 새틀라이트분 제외한 코어 배분
        trades_df["notional_krw"] = trades_df["weight_at_entry"] * core_capital_krw
        trades_df["gain_krw"] = trades_df["notional_krw"] * trades_df["net_ret_pct"]

        annual = trades_df.groupby("exit_year")["gain_krw"].sum().to_dict()
        annual_tax = {}
        total_pretax = 0.0
        total_tax = 0.0
        for year, gain in sorted(annual.items()):
            total_pretax += gain
            if gain > 0:
                taxable = max(0.0, gain - ANNUAL_DEDUCTION_KRW)
                tax = taxable * TAX_RATE
            else:
                tax = 0.0  # 손실연도는 세액 0, 이월공제 없음(다음 해로 손실을 넘기지 못함)
            total_tax += tax
            annual_tax[str(year)] = {
                "realized_gain_krw": round(gain, 0), "taxable_base_krw": round(max(0.0, gain - ANNUAL_DEDUCTION_KRW) if gain > 0 else 0.0, 0),
                "tax_krw": round(tax, 0),
            }
        effective_tax_rate_on_gains = (total_tax / total_pretax * 100) if total_pretax > 0 else None
        account_results[str(account_krw)] = {
            "account_krw": account_krw, "core_capital_krw": core_capital_krw,
            "annual": annual_tax,
            "total_pretax_gain_krw": round(total_pretax, 0),
            "total_tax_krw": round(total_tax, 0),
            "total_aftertax_gain_krw": round(total_pretax - total_tax, 0),
            "effective_tax_rate_on_total_gain_pct": round(effective_tax_rate_on_gains, 2) if effective_tax_rate_on_gains else None,
        }
        log(f"계좌 {account_krw:,.0f}원 (코어분 {core_capital_krw:,.0f}원): "
            f"세전 누적실현손익={total_pretax:,.0f}원, 세금 합계={total_tax:,.0f}원, "
            f"실효세율(세전이익 대비)={effective_tax_rate_on_gains}")

    json.dump({
        "meta": {
            "tax_rate": TAX_RATE, "annual_deduction_krw": ANNUAL_DEDUCTION_KRW,
            "roundtrip_cost_pct_used": ROUNDTRIP_COST_PCT,
            "n_trades": len(trades_df), "period": [FULL_START, FULL_END],
            "tax_source_note": (
                "2026-09-14 웹검색: 국세청/미래에셋증권/유안타증권/calculatorhost.com — 해외주식 양도소득세 "
                "22%(양도세20%+지방세2%), 기본공제 연 250만원, 손익통산은 같은 과세연도 내에서만, "
                "연도간 이월공제 없음."
            ),
        },
        "account_scenarios": account_results,
    }, open(OUT_DIR / "step3_results.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
    log("step3_results.json 저장 완료")


if __name__ == "__main__":
    main()
