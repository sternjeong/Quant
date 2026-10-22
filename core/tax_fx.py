"""세후·환전 후 수익 계산 (2026-10-05, 사용자 요청 — 카카오페이증권 이용) — 백테스트가 무시해 온 '실제로 남는 돈'.

지금까지 백테스트는 편도 3~8bp 수수료만 넣고 세금·환전은 0 이었다. 이 모듈은 같은 목표 비중을 실제 계좌처럼 굴린다:
  - 매매는 목표 비중이 바뀌는 날(리밸런싱 날)에만 한다(그 사이 비중은 가격대로 표류). 소수점 주식 허용(옵션으로 정수 주).
  - 매매 수수료: 거래대금 × fee_rate(카카오페이증권 해외주식 기본 0.1% — 2026-10 조사).
  - 환전: 스프레드 fx_spread(증권사 기본 1% × (1 − 우대율). 카카오페이증권은 실시간 환전 시간에 95% 우대 → 0.05%,
    자동환전(원화 주문)은 우대 0% 라는 사용자 후기 — 확인 필요). 두 방식:
      usd_hold: 시작할 때 한 번 원화→달러, 그 뒤 달러로만 매매(평가는 그날 환율로 원화 환산).
      krw_each_trade: 살 때마다 원화→달러, 팔 때마다 달러→원화(현금은 원화로 보유).
  - 양도소득세: 해외주식 연간 순양도차익(원화, 결제일 환율 ≈ 그날 환율)에서 250만 원 공제 후 22%. 이월결손금 없음(그해 손실은 그해 이익에서만 상계).
    다음 해 5월 말에 낸다(현금이 모자라면 비중대로 팔아서 — 그 매도도 그해 양도차익에 들어간다). 취득가액: fifo(선입선출) 또는 average(이동평균) — 증권사마다 다르다.
  - 배당: 조정가(Adj Close)와 종가 차이로 배당을 복원, 미국 원천징수 15% 뗀 85% 를 달러 현금으로(다음 리밸런싱에 재투자).
    금융소득 2,000만 원 초과 종합과세는 넣지 않았다(배당이 그 규모가 되면 따로 봐야 한다).
월 적립(2026-10-17, 사용자 요청 — 처음 목돈 + 매달 적립으로 영원히 굴린다): monthly_contribution_krw > 0 이면 시작일 다음 달부터
  매달 첫 거래일에 원화가 들어온다(usd_hold 는 같은 스프레드로 바로 달러로, krw_each_trade 는 원화로 두었다가 살 때 환전).
  그날 종가에 산다 — underweight_first: 목표보다 모자란 종목만 모자란 만큼에 비례해 산다(팔지 않음), pro_rata: 목표 비중대로 산다.
  그날이 목표가 바뀌는 날이기도 하면 돈을 먼저 넣고 평소 리밸런싱을 한다(덜 판다). 세전 기준선도 같은 돈을 같은 방식으로 받는다.
  돈이 중간에 들어오므로 cagr_after·cagr_pre(최종/처음)는 의미가 없고 irr_after_liquidation(XIRR)·twr_index 를 본다.
결과는 원화 기준. 같은 목표 비중을 비용·세금·환전 없이 굴린 '세전 기준선'과 나란히 보여 준다. 주문 경로와 연결되어 있지 않다.
세금 계산은 추정이며 신고용이 아니다(신고는 증권사 양도소득세 대행·세무사 확인).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

TAX_RATE = 0.22
ANNUAL_DEDUCTION_KRW = 2_500_000
DIVIDEND_WITHHOLDING = 0.15
TAX_PAY_MONTH = 5  # 다음 해 5월(신고·납부 기한) 말
KAKAO_FEE = 0.001
BASE_FX_SPREAD = 0.01


@dataclass(frozen=True)
class AccountConfig:
    initial_krw: float = 30_000_000
    fee_rate: float = KAKAO_FEE
    fx_spread: float = BASE_FX_SPREAD * (1 - 0.95)  # 95% 우대 실시간 환전
    fx_mode: str = "usd_hold"        # usd_hold | krw_each_trade
    cost_basis: str = "average"      # average | fifo
    integer_shares: bool = False
    apply_tax: bool = True
    apply_dividend_tax: bool = True
    reinvest_dividends: bool = True  # 받는 날 같은 종목을 다시 산다(끄면 다음 리밸런싱까지 현금)
    harvest_gains: bool = False      # 연말 공제 채우기: 그해 실현 이익이 250만 원보다 적으면 이익 난 종목을 팔았다 바로 다시 사서 공제를 쓴다
    harvest_losses: bool = False     # 연말 손실 확정: 그해 실현 이익이 250만 원을 넘으면 손실 난 종목을 팔았다 바로 다시 사서 상계한다
    harvest_days_before_year_end: int = 3  # 12월 마지막 거래일에서 며칠(거래일) 앞에 하나 — 결제일이 해를 넘기지 않게
    monthly_contribution_krw: float = 0.0  # 시작일 다음 달부터 매달 첫 거래일에 넣는 원화(0 이면 예전과 똑같다)
    contribution_policy: str = "underweight_first"  # underweight_first | pro_rata


CONTRIBUTION_POLICIES = ("underweight_first", "pro_rata")


def allocate_contribution(policy: str, w: np.ndarray, cur: np.ndarray, tot: float, avail: float,
                          new_cash: float) -> np.ndarray:
    """새로 들어온 현금 new_cash(달러) 를 종목별 매수 금액으로 나눈다(파는 것은 없다).
    w: 목표 비중(합 ≤ 1, 나머지는 현금 목표 — 살 수 없는 종목은 0 으로 넘긴다), cur: 지금 평가액,
    tot: 새 현금을 넣은 뒤 총평가액, avail: 지금 쓸 수 있는 현금(새 현금 포함).
      underweight_first: 쓸 돈 = min(new_cash, avail − 현금 목표). 목표보다 모자란 종목에 모자란 금액(목표 − 지금)에 비례해 나눈다.
                         쓸 돈이 모자란 금액 합보다 크면 남는 돈은 목표 비중대로 나눈다.
      pro_rata: new_cash × Σw 를 목표 비중대로(현금 목표 비율만큼은 현금으로 남긴다)."""
    w = np.clip(np.nan_to_num(np.asarray(w, dtype=float)), 0.0, None)
    cur = np.nan_to_num(np.asarray(cur, dtype=float))
    out = np.zeros_like(w)
    sw = float(w.sum())
    if new_cash <= 0 or sw <= 0:
        return out
    if policy == "pro_rata":
        deploy = min(new_cash * min(sw, 1.0), max(avail, 0.0))
        return deploy * w / sw
    if policy != "underweight_first":
        raise ValueError(f"contribution_policy 는 {CONTRIBUTION_POLICIES} 중 하나: {policy!r}")
    deploy = min(new_cash, max(0.0, avail - max(0.0, 1.0 - sw) * tot))
    if deploy <= 0:
        return out
    short = np.where(w > 0, np.clip(w * tot - cur, 0.0, None), 0.0)
    s_tot = float(short.sum())
    if s_tot >= deploy and s_tot > 0:
        return deploy * short / s_tot
    return short + (deploy - s_tot) * w / sw


def xirr(flows: list) -> float:
    """연 환산 내부수익률(XIRR, 1년 = 365일). flows: [(날짜, 금액)] — 넣은 돈은 음수, 마지막 평가액은 양수.
    부호가 한쪽뿐이거나 −99% ~ +1000% 안에 해가 없으면 nan. 이분법으로 푼다."""
    if not flows:
        return float("nan")
    t0 = min(pd.Timestamp(d) for d, _ in flows)
    ts = np.array([(pd.Timestamp(d) - t0).days / 365.0 for d, _ in flows])
    cf = np.array([float(a) for _, a in flows])
    if not (cf > 0).any() or not (cf < 0).any():
        return float("nan")

    def npv(r: float) -> float:
        with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
            return float(np.sum(cf / (1.0 + r) ** ts))

    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return float("nan")
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_mid == 0 or hi - lo < 1e-14:
            return mid
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def contribution_days(days: pd.DatetimeIndex) -> np.ndarray:
    """적립일 표시: 시작일 다음부터 달이 바뀐 첫 거래일(시작일 자체는 아니다)."""
    m = np.asarray(days.year * 12 + days.month)
    out = np.zeros(len(days), dtype=bool)
    out[1:] = m[1:] != m[:-1]
    return out


def _twr(values: pd.Series, flows: pd.Series) -> pd.Series:
    """시간가중 지수(1 에서 시작): 그날 수익 = 오늘 평가액 / (전날 평가액 + 오늘 들어온 돈) − 1."""
    v = values.to_numpy(dtype=float)
    f = flows.to_numpy(dtype=float)
    out = np.ones(len(v))
    for i in range(1, len(v)):
        den = v[i - 1] + f[i]
        out[i] = out[i - 1] * (v[i] / den if den > 0 else 1.0)
    return pd.Series(out, index=values.index)


@dataclass
class _Pos:
    lots: list = field(default_factory=list)  # [(주수, 1주당 원화 취득가)]

    @property
    def shares(self) -> float:
        return sum(q for q, _ in self.lots)

    def buy(self, q: float, krw_per_share: float, method: str) -> None:
        if q <= 0:
            return
        if method == "average" and self.lots:
            tot_q = self.shares + q
            avg = (sum(a * b for a, b in self.lots) + q * krw_per_share) / tot_q
            self.lots = [(tot_q, avg)]
        else:
            self.lots.append((q, krw_per_share))

    def sell(self, q: float) -> float:
        """q 주를 팔 때의 원화 취득가 합(선입선출 — 이동평균이면 lot 이 하나라 같은 결과)."""
        cost, left, out = 0.0, q, []
        for lq, lp in self.lots:
            take = min(lq, left)
            cost += take * lp
            left -= take
            if lq - take > 1e-12:
                out.append((lq - take, lp))
        self.lots = out
        return cost


def _dividends_per_share(close: pd.DataFrame, adj: pd.DataFrame) -> pd.DataFrame:
    """그날 받은 1주당 배당(달러) 복원: 전날 종가 × 조정가 수익 − 오늘 종가 (음수는 0)."""
    tr = adj / adj.shift(1)
    d = close.shift(1) * tr - close
    return d.clip(lower=0).fillna(0.0)


def simulate(weights: pd.DataFrame, close: pd.DataFrame, adj: pd.DataFrame, usdkrw: pd.Series,
             cfg: AccountConfig = AccountConfig(), trade_allowed: Optional[pd.DataFrame] = None) -> dict[str, Any]:
    """weights: 날짜 × 종목 목표 비중(합 ≤ 1, 나머지는 현금). 목표가 바뀌는 날 그날 종가로 매매.
    close: 원래 종가(세금 계산용), adj: 배당 포함 조정가, usdkrw: 원/달러(그날 값, 결측은 전날 값).
    trade_allowed: 연구용 날짜×종목 매매 허용 표. 첫날은 모두 허용하며, 적립금 매수는 별도 처리한다."""
    days = weights.index
    tickers = list(weights.columns)
    close = close.reindex(index=days, columns=tickers).ffill()
    adj = adj.reindex(index=days, columns=tickers).ffill()
    fx = usdkrw.reindex(days).ffill().bfill()
    divs = _dividends_per_share(close, adj)
    change = weights.diff().abs().sum(axis=1) > 1e-9
    change.iloc[0] = True
    if trade_allowed is not None:
        if not trade_allowed.index.equals(days) or set(trade_allowed.columns) != set(tickers):
            raise ValueError("trade_allowed 날짜·종목은 weights 와 같아야 합니다")
        trade_allowed = trade_allowed.reindex(columns=tickers).fillna(False).astype(bool)
        if not trade_allowed.iloc[0].all():
            raise ValueError("trade_allowed 첫날은 모든 종목을 허용해야 합니다")

    if cfg.contribution_policy not in CONTRIBUTION_POLICIES:
        raise ValueError(f"contribution_policy 는 {CONTRIBUTION_POLICIES} 중 하나: {cfg.contribution_policy!r}")
    contrib = float(cfg.monthly_contribution_krw or 0.0)
    contrib_day = contribution_days(days) if contrib > 0 else np.zeros(len(days), dtype=bool)
    contrib_vals = np.where(contrib_day, contrib, 0.0)

    pos = {t: _Pos() for t in tickers}
    rate0 = float(fx.iloc[0])
    if cfg.fx_mode == "usd_hold":
        cash_usd, cash_krw = cfg.initial_krw / (rate0 * (1 + cfg.fx_spread)), 0.0
    else:
        cash_usd, cash_krw = 0.0, cfg.initial_krw
    fx_cost_krw = fee_krw = div_tax_krw = 0.0
    realized: dict[int, float] = {}
    tax_due: dict[int, float] = {}
    tax_paid_rows = []
    values = []
    year_rows: dict[int, dict] = {}

    def yr(y: int) -> dict:
        return year_rows.setdefault(y, {"year": y, "realized_gain_krw": 0.0, "tax_krw": 0.0, "fees_krw": 0.0,
                                        "fx_cost_krw": 0.0, "dividend_tax_krw": 0.0})

    def sell(t: str, q: float, i: int) -> None:
        nonlocal cash_usd, cash_krw, fee_krw, fx_cost_krw
        if q <= 0:
            return
        px, rate = float(close.iat[i, tickers.index(t)]), float(fx.iat[i])
        gross = q * px
        fee = gross * cfg.fee_rate
        cost_krw = pos[t].sell(q)
        proceeds_krw = (gross - fee) * rate
        y = days[i].year
        realized[y] = realized.get(y, 0.0) + proceeds_krw - cost_krw
        yr(y)["realized_gain_krw"] += proceeds_krw - cost_krw
        fee_krw += fee * rate
        yr(y)["fees_krw"] += fee * rate
        if cfg.fx_mode == "usd_hold":
            cash_usd += gross - fee
        else:
            got = (gross - fee) * rate * (1 - cfg.fx_spread)
            fx_cost_krw += (gross - fee) * rate * cfg.fx_spread
            yr(y)["fx_cost_krw"] += (gross - fee) * rate * cfg.fx_spread
            cash_krw += got

    def buy(t: str, usd_amount: float, i: int) -> None:
        nonlocal cash_usd, cash_krw, fee_krw, fx_cost_krw
        px, rate = float(close.iat[i, tickers.index(t)]), float(fx.iat[i])
        if usd_amount <= 0 or not px > 0:
            return
        q = usd_amount / (px * (1 + cfg.fee_rate))
        if cfg.integer_shares:
            q = math.floor(q)
        if q <= 0:
            return
        gross = q * px
        fee = gross * cfg.fee_rate
        y = days[i].year
        fee_krw += fee * rate
        yr(y)["fees_krw"] += fee * rate
        if cfg.fx_mode == "usd_hold":
            cash_usd -= gross + fee
        else:
            need_krw = (gross + fee) * rate * (1 + cfg.fx_spread)
            fx_cost_krw += (gross + fee) * rate * cfg.fx_spread
            yr(y)["fx_cost_krw"] += (gross + fee) * rate * cfg.fx_spread
            cash_krw -= need_krw
        pos[t].buy(q, (gross + fee) * rate / q, cfg.cost_basis)  # 수수료는 취득가액에 포함(필요경비)

    # 해마다 12월 마지막 거래일에서 harvest_days_before_year_end 거래일 앞(그해 12월 거래일이 그보다 적으면 없음)
    harvest_idx: set[int] = set()
    dec = pd.Series(range(len(days)), index=days)[days.month == 12]
    for _y, grp in dec.groupby(dec.index.year):
        if len(grp) > cfg.harvest_days_before_year_end and int(grp.iloc[-1]) + 1 < len(days):  # 그해 12월이 끝까지 있어야
            harvest_idx.add(int(grp.iloc[-1 - cfg.harvest_days_before_year_end]))
    harvests: list[dict] = []

    def unrealized_per_share(t: str, i: int) -> float:
        p = pos[t]
        if not p.shares:
            return 0.0
        avg = sum(q * c for q, c in p.lots) / p.shares
        px = float(close.iat[i, tickers.index(t)])
        return px * (1 - cfg.fee_rate) * float(fx.iat[i]) - (avg if cfg.cost_basis == "average" else p.lots[0][1])

    def _harvest(i: int) -> dict:
        y = days[i].year
        done = {"date": str(days[i].date()), "gains_realized_krw": 0.0, "losses_realized_krw": 0.0}
        cur = realized.get(y, 0.0)
        for t in tickers:
            px = float(close.iat[i, tickers.index(t)])
            if not pos[t].shares or not px > 0:
                continue
            g = unrealized_per_share(t, i)
            if cfg.harvest_gains and cur < ANNUAL_DEDUCTION_KRW and g > 0:
                room = (ANNUAL_DEDUCTION_KRW - cur) * 0.97  # 수수료·반올림 여유
                q = min(pos[t].shares, room / g)
            elif cfg.harvest_losses and cur > ANNUAL_DEDUCTION_KRW and g < 0:
                q = min(pos[t].shares, (cur - ANNUAL_DEDUCTION_KRW) / -g)
            else:
                continue
            if cfg.integer_shares:
                q = math.floor(q)
            if q <= 0:
                continue
            before = realized.get(y, 0.0)
            sell(t, q, i)
            delta = realized.get(y, 0.0) - before
            done["gains_realized_krw" if delta > 0 else "losses_realized_krw"] += delta
            cur = realized.get(y, 0.0)
            amount = q * px * (1 - cfg.fee_rate)
            if cfg.fx_mode != "usd_hold":
                amount *= (1 - cfg.fx_spread) / (1 + cfg.fx_spread)
            buy(t, amount, i)
        return done

    def value_usd(i: int) -> float:
        return cash_usd + sum(pos[t].shares * float(close.iat[i, j]) for j, t in enumerate(tickers) if pos[t].shares)

    def _contribute(i: int) -> None:
        """적립금을 넣는다(리밸런싱 날이 아니면 정책대로 바로 산다 — 파는 것은 없다)."""
        nonlocal cash_usd, cash_krw, fx_cost_krw
        rate, y = float(fx.iat[i]), days[i].year
        if cfg.fx_mode == "usd_hold":
            cash_usd += contrib / (rate * (1 + cfg.fx_spread))
            fx_cost_krw += contrib * cfg.fx_spread / (1 + cfg.fx_spread)
            yr(y)["fx_cost_krw"] += contrib * cfg.fx_spread / (1 + cfg.fx_spread)
        else:
            cash_krw += contrib
        if change.iat[i] and (trade_allowed is None or bool(trade_allowed.iloc[i].all())):
            return  # 이어서 평소 리밸런싱이 이 돈까지 맞춘다
        px = close.iloc[i].to_numpy(dtype=float)
        ok = np.isfinite(px) & (px > 0)
        sh = np.array([pos[t].shares for t in tickers])
        cur = np.where(ok, sh * np.nan_to_num(px), 0.0)
        tot = value_usd(i) + (cash_krw / rate if cfg.fx_mode == "krw_each_trade" else 0.0)
        w = np.where(ok, weights.iloc[i].reindex(tickers).fillna(0.0).to_numpy(dtype=float), 0.0)
        avail = cash_usd if cfg.fx_mode == "usd_hold" else cash_krw / (rate * (1 + cfg.fx_spread))
        alloc = allocate_contribution(cfg.contribution_policy, w, cur, tot, avail, contrib / (rate * (1 + cfg.fx_spread)))
        for j, t in enumerate(tickers):
            if alloc[j] > 1e-9:
                room = cash_usd if cfg.fx_mode == "usd_hold" else cash_krw / (rate * (1 + cfg.fx_spread))
                buy(t, min(float(alloc[j]), max(room, 0.0)), i)

    for i, d in enumerate(days):
        rate = float(fx.iat[i])
        # 배당(원천징수 15% 뗀 뒤 달러 현금)
        for j, t in enumerate(tickers):
            sh = pos[t].shares
            if sh and divs.iat[i, j] > 0:
                gross = sh * float(divs.iat[i, j])
                tax = gross * DIVIDEND_WITHHOLDING if cfg.apply_dividend_tax else 0.0
                div_tax_krw += tax * rate
                yr(d.year)["dividend_tax_krw"] += tax * rate
                net = gross - tax
                if cfg.fx_mode == "usd_hold":
                    cash_usd += net
                    if cfg.reinvest_dividends:
                        buy(t, net, i)
                else:
                    cash_krw += net * rate * (1 - cfg.fx_spread)
                    fx_cost_krw += net * rate * cfg.fx_spread
                    yr(d.year)["fx_cost_krw"] += net * rate * cfg.fx_spread
                    if cfg.reinvest_dividends:
                        buy(t, net * (1 - cfg.fx_spread) / (1 + cfg.fx_spread), i)
        # 양도소득세 납부(다음 해 5월 마지막 거래일 무렵)
        if cfg.apply_tax and i + 1 < len(days) and d.month == TAX_PAY_MONTH and days[i + 1].month != TAX_PAY_MONTH:
            due_year = d.year - 1
            if due_year not in tax_due:
                gain = realized.get(due_year, 0.0)
                tax = max(0.0, gain - ANNUAL_DEDUCTION_KRW) * TAX_RATE
                tax_due[due_year] = tax
                yr(due_year)["tax_krw"] = tax
                if tax > 0:
                    need_usd = tax / rate
                    avail = cash_usd if cfg.fx_mode == "usd_hold" else cash_krw / rate
                    short = need_usd - avail
                    if short > 0:  # 비중대로 팔아서 마련(그 매도 차익도 올해 양도차익)
                        tot = value_usd(i) - (cash_usd if cfg.fx_mode == "usd_hold" else 0.0)
                        for j, t in enumerate(tickers):
                            sh = pos[t].shares
                            if sh and tot > 0:
                                sell(t, sh * min(1.0, short * 1.01 / tot), i)
                    if cfg.fx_mode == "usd_hold":
                        cash_usd -= tax / (rate * (1 - cfg.fx_spread))  # 달러를 원화로 바꿔서 낸다
                        fx_cost_krw += tax * cfg.fx_spread
                    else:
                        cash_krw -= tax
                    tax_paid_rows.append({"date": str(d.date()), "for_year": due_year, "tax_krw": tax})
        # 월 적립(리밸런싱 날이면 돈만 넣고 아래 리밸런싱이 맞춘다)
        if contrib_day[i]:
            _contribute(i)
        # 리밸런싱
        if change.iat[i]:
            tot = value_usd(i) + (cash_krw / rate if cfg.fx_mode == "krw_each_trade" else 0.0)
            target = weights.iloc[i]
            cur = {t: pos[t].shares * float(close.iat[i, j]) for j, t in enumerate(tickers)}
            for t in tickers:  # 매도 먼저
                if trade_allowed is not None and not bool(trade_allowed.at[d, t]):
                    continue
                px = float(close.iat[i, tickers.index(t)])
                want = float(target.get(t, 0.0)) * tot
                if cur[t] > want + 1e-6 and px > 0:
                    sell(t, min(pos[t].shares, (cur[t] - want) / px), i)
            for t in tickers:
                if trade_allowed is not None and not bool(trade_allowed.at[d, t]):
                    continue
                want = float(target.get(t, 0.0)) * tot
                if want > cur[t] + 1e-6:
                    budget = want - cur[t]
                    if cfg.fx_mode == "usd_hold":
                        budget = min(budget, max(cash_usd, 0.0))
                    else:
                        budget = min(budget, max(cash_krw, 0.0) / (rate * (1 + cfg.fx_spread)))
                    buy(t, budget, i)
        # 연말 공제 채우기·손실 확정(팔았다 같은 날 다시 산다 — 보유는 그대로, 취득가만 바뀐다)
        if (cfg.harvest_gains or cfg.harvest_losses) and i in harvest_idx:
            harvests.append(_harvest(i))
        v_krw = value_usd(i) * rate + cash_krw if cfg.fx_mode == "krw_each_trade" else value_usd(i) * rate
        values.append(v_krw)

    series = pd.Series(values, index=days)
    # 세전 기준선: 같은 목표 비중을 비용·세금·환전 없이(비중은 리밸런싱 사이 표류), 원화 환산
    tr = adj.pct_change(fill_method=None).fillna(0.0)
    w = weights.where(change).ffill().fillna(0.0)
    drift_w, base_vals, v = None, [], 1.0
    for i in range(len(days) if contrib <= 0 else 0):  # 적립금이 있으면 아래 _pre_cost_with_contributions
        # 그날 수익은 전날 종가까지 들고 있던 비중으로 — 목표가 바뀌는 날은 그날 종가에 매매하므로 새 비중은 다음 날부터
        if i > 0 and drift_w is not None:
            g = drift_w * (1 + tr.iloc[i].to_numpy())
            port = g.sum() + (1 - drift_w.sum())
            v *= port
            drift_w = g / port if port > 0 else drift_w
        if change.iat[i] or drift_w is None:
            drift_w = w.iloc[i].to_numpy(dtype=float)
        base_vals.append(v)
    if contrib <= 0:
        base = pd.Series(base_vals, index=days) * (cfg.initial_krw / float(fx.iloc[0])) * fx
    else:
        base = _pre_cost_with_contributions(weights.reindex(columns=tickers).fillna(0.0), change, tr, fx,
                                            cfg.initial_krw, contrib_vals, cfg.contribution_policy)
    years = (days[-1] - days[0]).days / 365.25

    def cagr(s: pd.Series) -> float:
        return float((s.iloc[-1] / cfg.initial_krw) ** (1 / years) - 1) if years > 0 and s.iloc[-1] > 0 else float("nan")

    def mdd(s: pd.Series) -> float:
        return float((s / s.cummax() - 1).min())

    # 마지막 종가에 전량 매도하고 달러 잔액도 원화로 바꾼 가상 청산.
    # 기납부 세금은 위 현금 흐름에 이미 반영되어 있으므로, 아직 납부하지 않은 연도만 뺀다.
    last = len(days) - 1
    last_year, last_rate = days[-1].year, float(fx.iat[last])
    sale_gross_usd = sum(pos[t].shares * float(close.iat[last, j]) for j, t in enumerate(tickers))
    sale_fee_krw = sale_gross_usd * cfg.fee_rate * last_rate
    sale_net_usd = sale_gross_usd * (1 - cfg.fee_rate)
    sale_gain_krw = sale_net_usd * last_rate - sum(
        sum(q * basis for q, basis in pos[t].lots) for t in tickers
    )
    unpaid_prior_tax = sum(
        max(0.0, gain - ANNUAL_DEDUCTION_KRW) * TAX_RATE
        for year, gain in realized.items() if year < last_year and year not in tax_due
    ) if cfg.apply_tax else 0.0
    liquidation_tax = max(0.0, realized.get(last_year, 0.0) + sale_gain_krw - ANNUAL_DEDUCTION_KRW) * TAX_RATE if cfg.apply_tax else 0.0
    conversion_usd = cash_usd + sale_net_usd
    conversion_cost_krw = abs(conversion_usd) * last_rate * cfg.fx_spread
    terminal_krw = cash_krw + conversion_usd * last_rate - conversion_cost_krw - unpaid_prior_tax - liquidation_tax
    return {
        "values_krw": series, "pre_cost_krw": base,
        "final_krw": float(series.iloc[-1]), "final_pre_cost_krw": float(base.iloc[-1]),
        "cagr_after": cagr(series), "cagr_pre": cagr(base), "mdd_after": mdd(series), "mdd_pre": mdd(base),
        "totals": {"fees_krw": fee_krw, "fx_cost_krw": fx_cost_krw, "dividend_tax_krw": div_tax_krw,
                   "capital_gains_tax_krw": sum(tax_due.values())},
        "unpaid_tax_if_sold_now_krw": unpaid_prior_tax + liquidation_tax,
        "unpaid_prior_year_tax_krw": unpaid_prior_tax,
        "liquidation_current_year_tax_krw": liquidation_tax,
        "liquidation_sale_gain_krw": sale_gain_krw,
        "liquidation_trade_fees_krw": sale_fee_krw,
        "liquidation_fx_cost_krw": conversion_cost_krw,
        "final_after_liquidation_krw": terminal_krw,
        **_contribution_outputs(days, cfg.initial_krw, contrib_vals, series, base,
                                terminal_krw),
        "years": [year_rows[y] for y in sorted(year_rows)], "tax_payments": tax_paid_rows, "harvests": harvests,
        "config": cfg.__dict__.copy(),
    }


def _pre_cost_with_contributions(weights: pd.DataFrame, change: pd.Series, tr: pd.DataFrame, fx: pd.Series,
                                 initial_krw: float, contrib_vals: np.ndarray, policy: str) -> pd.Series:
    """세전 기준선(적립금 있음): 비용·세금·환전 없이 종목별 달러 평가액을 표류시키고, 같은 날 같은 정책으로 적립금을 넣는다.
    적립금이 0 이면 기존 기준선과 같은 값(수치 오차 수준)이다."""
    W = weights.to_numpy(dtype=float)
    R = tr.reindex(columns=weights.columns).fillna(0.0).to_numpy(dtype=float)
    ch = change.to_numpy()
    fxv = fx.to_numpy(dtype=float)
    h = np.zeros(W.shape[1])
    cash = initial_krw / fxv[0]
    out = np.empty(len(fxv))
    for i in range(len(fxv)):
        if i > 0:
            h = h * (1 + R[i])
        if contrib_vals[i] > 0:
            c = contrib_vals[i] / fxv[i]
            cash += c
            if not ch[i]:
                a = allocate_contribution(policy, W[i], h, h.sum() + cash, cash, c)
                h = h + a
                cash -= a.sum()
        if ch[i]:
            tot = h.sum() + cash
            h = W[i] * tot
            cash = tot - h.sum()
        out[i] = (h.sum() + cash) * fxv[i]
    return pd.Series(out, index=weights.index)


def _contribution_outputs(days: pd.DatetimeIndex, initial_krw: float, contrib_vals: np.ndarray, series: pd.Series,
                          base: pd.Series, terminal_after_liq: float) -> dict[str, Any]:
    """적립 관련 출력(적립금 0 이어도 낸다 — 그때 IRR 은 1년 = 365일 기준 청산 후 연수익률)."""
    flows = pd.Series(contrib_vals, index=days)
    cum = initial_krw + flows.cumsum()
    cf = [(days[0], -initial_krw)] + [(d, -float(a)) for d, a in flows[flows > 0].items()]
    return {
        "contributions_krw": flows,                 # 그날 넣은 적립금(처음 목돈 제외)
        "cumulative_contributed_krw": cum,          # 처음 목돈 + 그날까지 적립금 합
        "total_contributed_krw": float(cum.iloc[-1]),
        "terminal_after_liquidation_krw": float(terminal_after_liq),  # = final_after_liquidation_krw
        "irr_after_liquidation": xirr(cf + [(days[-1], float(terminal_after_liq))]),
        "irr_pre_cost": xirr(cf + [(days[-1], float(base.iloc[-1]))]),
        "twr_index": _twr(series, flows),           # 세후(청산 전) 계좌의 시간가중 지수
        "twr_pre_index": _twr(base, flows),
    }


def buy_and_hold_weights(index: pd.DatetimeIndex, ticker: str = "SPY") -> pd.DataFrame:
    """비교용: 처음에 한 번 사서 끝까지 보유(세금이 끝까지 이연된다)."""
    return pd.DataFrame({ticker: 1.0}, index=index)


def usdkrw_series() -> pd.Series:
    """원/달러 일별 환율. FRED DEXKOUS → (키가 없거나 실패하면) 캐시 파일 그대로 → yfinance KRW=X 순서."""
    try:
        from core.fred_data import _cache_file, get_series

        s = get_series("DEXKOUS").dropna()
        if s.empty and _cache_file("DEXKOUS").exists():
            s = pd.read_csv(_cache_file("DEXKOUS"), index_col=0, parse_dates=True).iloc[:, 0].dropna()
        if not s.empty:
            return s.astype(float)
    except Exception:  # noqa: BLE001
        pass
    from core.market_data import get_price_history

    return get_price_history("KRW=X", start="2005-01-01", interval="1d")["Close"].dropna()


def run_core_vs_spy(start: str = "2010-01-01", cfg: AccountConfig = AccountConfig()) -> dict[str, Any]:
    """화면용: 챔피언 코어(코어 100% — 새틀라이트 미포함)와 SPY 그냥 보유를 같은 계좌 설정으로 굴린다."""
    from core import champion_strategy as cs
    from core.market_data import get_multiple_price_history

    fx = usdkrw_series()
    w = cs.run_core_backtest(start)["weights"]
    tick = list(dict.fromkeys(list(w.columns) + ["SPY"]))
    first = (pd.Timestamp(start) - pd.Timedelta(days=400)).date().isoformat()
    hist = get_multiple_price_history(tick, start=first, end=None, interval="1d")
    close = pd.DataFrame({t: hist[t]["Close"] for t in tick if t in hist}).ffill()
    adj = pd.DataFrame({t: hist[t]["Adj Close"] for t in tick if t in hist}).ffill()
    return {"core": simulate(w, close, adj, fx, cfg),
            "spy": simulate(buy_and_hold_weights(w.index), close, adj, fx, cfg)}


def champion_weights(core_w: pd.DataFrame, rebal_log: list[dict], satellite_weight: float = 0.15) -> pd.DataFrame:
    """코어 일별 목표 비중 × (1 − sw) + 새틀라이트(반기 선정 로그를 다음 선정일까지 유지) × sw.
    첫 새틀라이트 선정일부터만 돌려준다(그 전에는 새틀라이트가 없어 비교가 안 맞음). 슬리브 사이는 매일 맞추지 않고
    어느 쪽이든 목표가 바뀌는 날에만 매매한다(실제 계좌처럼 그 사이 표류)."""
    log = sorted(({"date": pd.Timestamp(r["date"]), "weights": r.get("weights") or {}} for r in rebal_log), key=lambda r: r["date"])
    if not log:
        raise ValueError("새틀라이트 선정 기록이 없습니다.")
    idx = core_w.index[core_w.index >= log[0]["date"]]
    sat_cols = sorted({t for r in log for t in r["weights"]})
    sat = pd.DataFrame(np.nan, index=idx, columns=sat_cols)
    for r in log:
        if r["date"] in sat.index:
            sat.loc[r["date"]] = [float(r["weights"].get(t, 0.0)) for t in sat_cols]
    sat = sat.ffill().fillna(0.0)
    out = core_w.reindex(idx).fillna(0.0) * (1 - satellite_weight)
    for t in sat_cols:
        out[t] = out.get(t, 0.0) + sat[t] * satellite_weight
    return out


def run_champion_vs_core(cfg: AccountConfig = AccountConfig(), backtest: Optional[dict] = None,
                         satellite_weight: float = 0.15) -> dict[str, Any]:
    """화면용: 코어 85% + 새틀라이트 15% 를 세후로. 새틀라이트 선정 기록은 새벽 미리 계산(dawn_precompute)의 '챔피언 전략
    3. 백테스트(최근 3년)' 결과를 쓴다(없으면 ValueError — 그 화면에서 백테스트를 돌리거나 다음 날 새벽을 기다린다).
    같은 기간의 코어만·SPY 그냥 보유를 나란히 계산한다."""
    from core import champion_strategy as cs
    from core.market_data import get_multiple_price_history

    if backtest is None:
        from core import dawn_precompute as dp

        entry = dp.load_latest(dp.KIND_CHAMPION_BACKTEST)
        if entry is None:
            raise ValueError("새벽 미리 계산한 챔피언 백테스트(최근 3년)가 없습니다 — 챔피언 전략 화면 '3. 백테스트'를 먼저 돌리세요.")
        backtest = entry["result"]
    log = (backtest.get("satellite") or {}).get("rebal_log") or []
    start = str(min(pd.Timestamp(r["date"]) for r in log).date()) if log else str(backtest.get("start"))
    core_w = cs.run_core_backtest(start)["weights"]
    champ_w = champion_weights(core_w, log, satellite_weight)
    core_only = core_w.reindex(champ_w.index).fillna(0.0)
    tick = list(dict.fromkeys(list(champ_w.columns) + ["SPY"]))
    first = (pd.Timestamp(start) - pd.Timedelta(days=30)).date().isoformat()
    hist = get_multiple_price_history(tick, start=first, end=None, interval="1d")
    close = pd.DataFrame({t: hist[t]["Close"] for t in tick if t in hist and not hist[t].empty}).ffill()
    adj = pd.DataFrame({t: hist[t]["Adj Close"] for t in tick if t in hist and not hist[t].empty}).ffill()
    missing = [t for t in champ_w.columns if t not in close.columns and champ_w[t].abs().sum() > 0]
    fx = usdkrw_series()
    return {"champion": simulate(champ_w, close, adj, fx, cfg),
            "core": simulate(core_only, close, adj, fx, cfg),
            "spy": simulate(buy_and_hold_weights(champ_w.index), close, adj, fx, cfg),
            "start": str(champ_w.index[0].date()), "end": str(champ_w.index[-1].date()),
            "satellite_picks": [{"date": str(pd.Timestamp(r["date"]).date()), "picks": list((r.get("weights") or {}).keys())} for r in log],
            "missing_prices": missing}
