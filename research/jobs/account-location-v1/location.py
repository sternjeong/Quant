"""account-location-v1 계좌 위치(asset location) 시뮬레이터 — 계약·가정은 같은 폴더 SPEC.md.

한 가구(사람 한 명)의 계좌 여러 개를 날마다 함께 굴린다.
  - 해외 계좌(ovs): 미국 상장 ETF, 달러 보유, core/tax_fx 기본과 같은 가정(수수료 0.1%, 환전 스프레드 0.05%,
    양도세 250만 원 공제 후 22% 다음 해 5월 납부, 배당 원천징수 15% 후 같은 종목 재투자, 이동평균 취득가).
  - 국내 계좌(dom): KRX 상장 대체 ETF(원화 지수 = 미국 ETF 원천징수 후 총수익 × 환율 − 연 차감).
      pension(연금저축): 계좌 안 매매·분배 비과세, 끝에 한 번 (평가액 − 원금) × 연금소득세율.
      isa(중개형 ISA): 3년마다 해지 — (평가액 − 원금 − 200만 원) × 9.9% 뒤 전액 연금저축으로 이전.
      taxable(일반 국내 계좌): 팔 때마다 이익 × 15.4%(손실 상계 없음), 분배금 추가 0.4%p.
  - 납입 한도: 해마다 첫 거래일(과 시작일)에 해외 계좌에서 한도만큼 옮긴다(팔아서 원화로 — 그 차익은 그해 양도차익).
    대체 ETF 가 없는 자산(no proxy)을 담을 몫(reserve_share × 가구 자산)은 해외 계좌에 남긴다.
  - 가구 단위 배분: 목표 비중 중 대체 ETF 가 있는 자산은 국내 계좌부터 채우고, 나머지·대체 없는 자산은 해외 계좌가 든다.
    국내 계좌가 대체 가능 몫보다 크면 남는 몫은 국내 계좌의 달러 단기채(BIL 대체)로 둔다.
세금 계산은 추정이며 신고·세무 자문이 아니다. 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

TAUS = {"low": 0.033, "high": 0.055, "lump": 0.165}  # 연금소득세(80세+ 3.3% / 55~69세 5.5%) · 연금외 수령 기타소득세 16.5%
CASH = "BIL"


@dataclass(frozen=True)
class Rules:
    ovs_fee: float = 0.001             # 카카오페이증권 해외주식 수수료(tax_fx.KAKAO_FEE)
    fx_spread: float = 0.0005          # 1% × (1 − 95% 우대)
    cg_rate: float = 0.22
    cg_deduction: float = 2_500_000
    div_withholding: float = 0.15
    tax_pay_month: int = 5
    dom_fee: float = 0.00015           # 국내 ETF 매매 수수료(확인 필요)
    dom_slippage: float = 0.0005       # 국내 ETF 호가 차이 반쪽(확인 필요)
    pension_cap: float = 18_000_000    # 연금저축+IRP 합산 연 납입 한도
    isa_cap: float = 20_000_000        # 중개형 ISA 연 납입 한도(이월 미반영)
    isa_total_cap: float = 100_000_000
    isa_free: float = 2_000_000        # 일반형 비과세 한도
    isa_rate: float = 0.099
    isa_years: int = 3
    domestic_rate: float = 0.154       # 국내 상장 해외 ETF 매매차익·분배금(배당소득)

    @property
    def dom_cost(self) -> float:
        return self.dom_fee + self.dom_slippage


SCHEME_ACCOUNTS = {"L0": (), "L1": ("pension",), "L2": ("isa",), "L12": ("pension", "isa"), "L3": ("taxable",)}


# ---------------------------------------------------------------- 순수 세금 함수(테스트 대상)
def isa_settlement_tax(gain_krw: float, rules: Rules = Rules()) -> float:
    """ISA 해지(만기) 세금: 순이익에서 비과세 한도를 뺀 몫 × 9.9%."""
    return max(0.0, gain_krw - rules.isa_free) * rules.isa_rate


def pension_withdrawal_tax(value_krw: float, principal_krw: float, tau: float) -> float:
    """연금 인출 세금(끝에 한 번): 운용수익(평가액 − 세액공제 안 받은 원금) × 세율. 손실이면 0."""
    return max(0.0, value_krw - principal_krw) * tau


def overseas_cg_tax(realized_krw: float, rules: Rules = Rules()) -> float:
    return max(0.0, realized_krw - rules.cg_deduction) * rules.cg_rate


def migration_room(scheme: str, pension_room: float, isa_room: float) -> dict[str, float]:
    """이번 해 옮길 수 있는 금액(계좌별, 연금 먼저)."""
    acc = SCHEME_ACCOUNTS[scheme]
    out = {}
    if "pension" in acc:
        out["pension"] = pension_room
    if "isa" in acc:
        out["isa"] = isa_room
    if "taxable" in acc:
        out["taxable"] = math.inf
    return out


# ---------------------------------------------------------------- 가격
def dividend_yield(close: pd.DataFrame, adj: pd.DataFrame) -> pd.DataFrame:
    """그날 분배금 / 전날 종가(core.tax_fx 와 같은 복원)."""
    tr = adj / adj.shift(1)
    d = (close.shift(1) * tr - close).clip(lower=0).fillna(0.0)
    return (d / close.shift(1)).replace([np.inf, -np.inf], 0.0).fillna(0.0)


def reference_krw_index(close: pd.DataFrame, adj: pd.DataFrame, fx: pd.Series, withholding: float = 0.15) -> pd.DataFrame:
    """미국 ETF 원천징수 후 총수익 × 원/달러 (대체 ETF 가 따라가야 할 기준, 비용 차감 전). 시작 1000."""
    tr = adj.pct_change(fill_method=None).fillna(0.0)
    r = tr - withholding * dividend_yield(close, adj)
    f = fx.reindex(close.index).ffill().bfill()
    g = (1 + r).mul(f / f.shift(1), axis=0).fillna(1.0)
    g.iloc[0] = 1.0
    return 1000 * g.cumprod()


def proxy_krw_index(ref: pd.DataFrame, deductions: dict[str, float]) -> pd.DataFrame:
    """대체 ETF 원화 지수 = 기준 × (1 − 연 차감)^(경과 거래일/252)."""
    out = {}
    for t in ref.columns:
        d = float(deductions.get(t, 0.0))
        k = np.arange(len(ref.index), dtype=float)
        out[t] = ref[t] * (1 - d) ** (k / 252.0)
    return pd.DataFrame(out, index=ref.index)


# ---------------------------------------------------------------- 계좌
@dataclass
class Overseas:
    rules: Rules
    tickers: list
    shares: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)       # 원화 취득가 합(이동평균)
    cash_usd: float = 0.0
    realized: dict = field(default_factory=dict)   # 연도 → 원화 실현손익
    paid: dict = field(default_factory=dict)       # 연도 → 낸 양도세
    fees_krw: float = 0.0
    fx_cost_krw: float = 0.0
    div_tax_krw: float = 0.0

    def holdings_usd(self, px: dict) -> float:
        return sum(q * px[t] for t, q in self.shares.items() if q > 0)

    def value_krw(self, px: dict, rate: float) -> float:
        return (self.cash_usd + self.holdings_usd(px)) * rate

    def deposit_krw(self, krw: float, rate: float) -> None:
        self.cash_usd += krw / (rate * (1 + self.rules.fx_spread))
        self.fx_cost_krw += krw - krw / (1 + self.rules.fx_spread)

    def sell(self, t: str, q: float, px: float, rate: float, year: int) -> None:
        sh = self.shares.get(t, 0.0)
        q = min(q, sh)
        if q <= 1e-12 or not px > 0:
            return
        gross = q * px
        fee = gross * self.rules.ovs_fee
        basis = self.cost[t] * q / sh
        self.cost[t] -= basis
        self.shares[t] = sh - q
        if self.shares[t] <= 1e-12:
            self.shares[t], self.cost[t] = 0.0, 0.0
        self.realized[year] = self.realized.get(year, 0.0) + (gross - fee) * rate - basis
        self.fees_krw += fee * rate
        self.cash_usd += gross - fee

    def buy(self, t: str, usd: float, px: float, rate: float) -> None:
        if usd <= 1e-9 or not px > 0:
            return
        q = usd / (px * (1 + self.rules.ovs_fee))
        gross = q * px
        fee = gross * self.rules.ovs_fee
        self.cash_usd -= gross + fee
        self.fees_krw += fee * rate
        self.shares[t] = self.shares.get(t, 0.0) + q
        self.cost[t] = self.cost.get(t, 0.0) + (gross + fee) * rate

    def outstanding_tax(self, year: int) -> float:
        return max(0.0, overseas_cg_tax(self.realized.get(year, 0.0), self.rules) - self.paid.get(year, 0.0))

    def pay_tax(self, year: int, krw: float, px: dict, rate: float, today_year: int) -> None:
        """원화 세금 krw 를 달러를 팔아(모자라면 비중대로 매도) 낸다. 보유가 없으면 현금이 음수(빚)가 된다."""
        if krw <= 0:
            return
        need_usd = krw / (rate * (1 - self.rules.fx_spread))
        short = need_usd - max(self.cash_usd, 0.0)
        hold = self.holdings_usd(px)
        if short > 0 and hold > 0:
            f = min(1.0, short * 1.01 / (hold * (1 - self.rules.ovs_fee)))
            for t in list(self.shares):
                self.sell(t, self.shares[t] * f, px[t], rate, today_year)
        self.cash_usd -= need_usd
        self.fx_cost_krw += krw * self.rules.fx_spread
        self.paid[year] = self.paid.get(year, 0.0) + krw

    def withdraw_krw(self, krw: float, px: dict, rate: float, year: int) -> float:
        """원화 krw 만큼 팔아서 원화로 바꿔 내보낸다. 거의 전부면 전량 매도 후 그해·지난해 세금을 먼저 낸다."""
        total = self.value_krw(px, rate)
        if krw <= 0 or total <= 0:
            return 0.0
        if krw >= 0.98 * total:
            for t in list(self.shares):
                self.sell(t, self.shares[t], px[t], rate, year)
            for y in sorted(self.realized):
                due = self.outstanding_tax(y)
                if due > 0:
                    self.pay_tax(y, due, px, rate, year)
            out = max(0.0, self.cash_usd) * rate * (1 - self.rules.fx_spread)
            self.fx_cost_krw += max(0.0, self.cash_usd) * rate * self.rules.fx_spread
            self.cash_usd = min(self.cash_usd, 0.0)
            return out
        need_usd = krw / (rate * (1 - self.rules.fx_spread))
        short = need_usd - max(self.cash_usd, 0.0)
        hold = self.holdings_usd(px)
        if short > 0 and hold > 0:
            f = min(1.0, short / (hold * (1 - self.rules.ovs_fee)))
            for t in list(self.shares):
                self.sell(t, self.shares[t] * f, px[t], rate, year)
        self.cash_usd -= need_usd
        self.fx_cost_krw += krw * self.rules.fx_spread / (1 - self.rules.fx_spread)
        return krw

    def dividends(self, divs: dict, px: dict, rate: float) -> None:
        for t, q in list(self.shares.items()):
            d = divs.get(t, 0.0)
            if q > 0 and d > 0:
                gross = q * d
                tax = gross * self.rules.div_withholding
                self.div_tax_krw += tax * rate
                self.cash_usd += gross - tax
                self.buy(t, gross - tax, px[t], rate)

    def final_krw(self, px: dict, rate: float, year: int) -> tuple[float, float]:
        """전량 매도 + 남은 양도세(지난해 미납분 포함) + 원화 환전. (최종 원화, 이때 낸 세금)"""
        for t in list(self.shares):
            self.sell(t, self.shares[t], px[t], rate, year)
        tax = sum(self.outstanding_tax(y) for y in self.realized)
        cash = self.cash_usd * rate
        return cash * (1 - self.rules.fx_spread) - tax, tax

    def rebalance_to(self, targets_krw: dict, px: dict, rate: float, year: int) -> None:
        cur = {t: self.shares.get(t, 0.0) * px[t] for t in set(self.shares) | set(targets_krw)}
        for t, v in cur.items():
            want = targets_krw.get(t, 0.0) / rate
            if v > want + 1e-6 and px[t] > 0:
                self.sell(t, (v - want) / px[t], px[t], rate, year)
        for t, want_krw in targets_krw.items():
            want = want_krw / rate
            if want > cur.get(t, 0.0) + 1e-6:
                self.buy(t, min(want - cur.get(t, 0.0), max(self.cash_usd, 0.0)), px[t], rate)


@dataclass
class Domestic:
    kind: str                     # pension | isa | taxable
    rules: Rules
    units: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)
    cash: float = 0.0
    principal: float = 0.0        # 세액공제 안 받은 납입 원금(연금: 납입 + ISA 이전, ISA: 이번 ISA 납입)
    opened: Optional[pd.Timestamp] = None
    total_in: float = 0.0         # 이번 ISA 누적 납입(총 한도용)
    fees_krw: float = 0.0
    tax_krw: float = 0.0          # 계좌에서 이미 낸 세금(ISA 해지·일반 계좌 매도·분배금)
    contributions: list = field(default_factory=list)

    def value(self, px: dict) -> float:
        return self.cash + sum(u * px[t] for t, u in self.units.items() if u > 0)

    def deposit(self, krw: float, day: pd.Timestamp, source: str = "overseas") -> None:
        if krw <= 0:
            return
        self.cash += krw
        self.principal += krw
        self.total_in += krw
        if self.opened is None:
            self.opened = day
        self.contributions.append({"date": str(day.date()), "kind": self.kind, "krw": round(krw), "source": source})

    def sell(self, t: str, u: float, px: float) -> None:
        have = self.units.get(t, 0.0)
        u = min(u, have)
        if u <= 1e-12 or not px > 0:
            return
        gross = u * px
        fee = gross * self.rules.dom_cost
        basis = self.cost[t] * u / have
        self.cost[t] -= basis
        self.units[t] = have - u
        if self.units[t] <= 1e-12:
            self.units[t], self.cost[t] = 0.0, 0.0
        self.fees_krw += fee
        net = gross - fee
        if self.kind == "taxable":
            tax = max(0.0, net - basis) * self.rules.domestic_rate  # 매도마다 원천징수, 손실 상계 없음
            self.tax_krw += tax
            net -= tax
        self.cash += net

    def buy(self, t: str, krw: float, px: float) -> None:
        if krw <= 1e-6 or not px > 0:
            return
        u = krw / (px * (1 + self.rules.dom_cost))
        self.fees_krw += krw - u * px
        self.cash -= krw
        self.units[t] = self.units.get(t, 0.0) + u
        self.cost[t] = self.cost.get(t, 0.0) + krw

    def distribution_tax(self, yields: dict) -> None:
        """일반 국내 계좌: 분배금 과세 15.4% 중 펀드 단계 15% 원천징수를 넘는 0.4%p 를 좌수로 차감."""
        if self.kind != "taxable":
            return
        extra = self.rules.domestic_rate - self.rules.div_withholding
        for t, u in self.units.items():
            y = yields.get(t, 0.0)
            if u > 0 and y > 0:
                self.units[t] = u * (1 - extra * y)

    def rebalance_to(self, targets: dict, px: dict) -> None:
        cur = {t: self.units.get(t, 0.0) * px[t] for t in set(self.units) | set(targets)}
        for t, v in cur.items():
            want = targets.get(t, 0.0)
            if v > want + 1e-6 and px[t] > 0:
                self.sell(t, (v - want) / px[t], px[t])
        for t, want in targets.items():
            if want > cur.get(t, 0.0) + 1e-6:
                self.buy(t, min(want - cur.get(t, 0.0), max(self.cash, 0.0)), px[t])

    def liquidate(self, px: dict) -> float:
        for t in list(self.units):
            self.sell(t, self.units[t], px[t])
        return self.cash

    def settle_isa(self, px: dict) -> float:
        """ISA 해지: 전량 매도, 9.9% 과세 후 금액(연금 이전용)."""
        v = self.liquidate(px)
        tax = isa_settlement_tax(v - self.principal, self.rules)
        self.tax_krw += tax
        out = v - tax
        self.cash, self.principal, self.total_in, self.opened = 0.0, 0.0, 0.0, None
        return out


# ---------------------------------------------------------------- 가구 시뮬레이션
def household_targets(w: dict, proxied: set, v_ovs: float, dom_vals: dict) -> tuple[dict, dict]:
    """가구 목표(원화)를 계좌별로 나눈다. 반환: (해외 목표 {종목: 원화}, {계좌: {종목: 원화}})."""
    v_adv = sum(dom_vals.values())
    V = v_ovs + v_adv
    sp = sum(x for t, x in w.items() if t in proxied)
    sn = sum(x for t, x in w.items() if t not in proxied)
    ovs, dom = {}, {k: {} for k in dom_vals}
    if v_adv <= 0:
        return {t: x * V for t, x in w.items() if x > 0}, dom
    if sp > 0 and v_adv <= sp * V + 1e-9:
        for t, x in w.items():
            if t in proxied:
                m = x / sp
                for k, vk in dom_vals.items():
                    dom[k][t] = vk * m
                ovs[t] = max(0.0, x * V - v_adv * m)
            elif x > 0:
                ovs[t] = x * V
    else:
        excess = v_adv - sp * V
        for k, vk in dom_vals.items():
            share = vk / v_adv
            for t, x in w.items():
                if t in proxied and x > 0:
                    dom[k][t] = x * V * share
            dom[k][CASH] = dom[k].get(CASH, 0.0) + excess * share
        if sn > 0 and v_ovs > 0:
            for t, x in w.items():
                if t not in proxied and x > 0:
                    ovs[t] = x * V * min(1.0, v_ovs / (sn * V))
    return ovs, dom


def simulate(weights: pd.DataFrame, close: pd.DataFrame, adj: pd.DataFrame, fx: pd.Series, proxy_px: pd.DataFrame,
             scheme: str, capital: float, rules: Rules = Rules(), *, proxied: Optional[set] = None,
             reserve_share: float = 0.0, spy_sleeve: float = 0.0, spy: str = "SPY") -> dict:
    """weights: 날짜 × 종목 목표 비중(코어 슬리브). 목표가 바뀌는 날과 돈이 옮겨진 날에 계좌별로 매매한다.
    proxy_px: 대체 ETF 원화 지수(열 = 미국 종목 이름). proxied: 대체 ETF 가 있는 종목(국내 계좌에 담을 수 있음).
    spy_sleeve: 자본 중 해외 계좌에 SPY 로 사서 끝까지 들고 갈 몫(정반합 S2 블렌드 = 0.5)."""
    days = weights.index
    tickers = list(weights.columns)
    all_us = list(dict.fromkeys(tickers + ([spy] if spy_sleeve > 0 else [])))
    close = close.reindex(index=days, columns=all_us).ffill()
    adj = adj.reindex(index=days, columns=all_us).ffill()
    f = fx.reindex(days).ffill().bfill()
    divs = (close.shift(1) * (adj / adj.shift(1)) - close).clip(lower=0).fillna(0.0)
    dyield = dividend_yield(close, adj)
    proxied = set(proxied if proxied is not None else [t for t in tickers if t in proxy_px.columns])
    proxied &= set(proxy_px.columns)
    kpx = proxy_px.reindex(index=days).ffill().bfill()
    change = weights.diff().abs().sum(axis=1) > 1e-9
    change.iloc[0] = True

    ovs = Overseas(rules, tickers)
    spy_acct = Overseas(rules, [spy]) if spy_sleeve > 0 else None
    accounts = {k: Domestic(k, rules) for k in SCHEME_ACCOUNTS[scheme]}
    pension = accounts.get("pension") or (Domestic("pension", rules) if "isa" in accounts else None)
    if pension is not None and "pension" not in accounts:
        accounts["pension"] = pension  # L2: ISA 만기 이전만 받는다(직접 납입 없음)
    direct = SCHEME_ACCOUNTS[scheme]
    values, migrations, isa_rolls = [], [], []
    core_cap = capital * (1 - spy_sleeve)
    last_year = None
    us_cols = {t: j for j, t in enumerate(all_us)}
    wmat = weights.to_numpy(dtype=float)

    for i, d in enumerate(days):
        rate = float(f.iat[i])
        px = {t: float(close.iat[i, us_cols[t]]) for t in all_us}
        kp = {t: float(kpx.at[d, t]) for t in proxied}
        if i > 0:
            dv = {t: float(divs.iat[i, us_cols[t]]) for t in all_us}
            ovs.dividends(dv, px, rate)
            if spy_acct is not None:
                spy_acct.dividends(dv, px, rate)
            if "taxable" in accounts:
                accounts["taxable"].distribution_tax({t: float(dyield.iat[i, us_cols[t]]) for t in proxied if t in us_cols})
        # 지난해 양도세(5월 마지막 거래일)
        if i + 1 < len(days) and d.month == rules.tax_pay_month and days[i + 1].month != rules.tax_pay_month:
            for acct in (ovs, spy_acct):
                if acct is not None:
                    due = acct.outstanding_tax(d.year - 1)
                    acct.pay_tax(d.year - 1, due, px, rate, d.year)
        flow = False
        # ISA 만기 → 연금저축 이전
        isa = accounts.get("isa")
        if isa is not None and isa.opened is not None and d >= isa.opened + pd.DateOffset(years=rules.isa_years):
            amt = isa.settle_isa(kp)
            pension.deposit(amt, d, source="isa_rollover")
            isa_rolls.append({"date": str(d.date()), "krw": round(amt)})
            flow = True
        # 납입(시작일, 해마다 첫 거래일)
        if direct and (i == 0 or d.year != last_year):
            room = migration_room(scheme, rules.pension_cap,
                                  min(rules.isa_cap, rules.isa_total_cap - (isa.total_in if isa is not None else 0.0)))
            dom_now = sum(a.value(kp) for a in accounts.values())
            if i == 0:
                avail = core_cap * (1 - reserve_share)
            else:
                v_ovs = ovs.value_krw(px, rate)
                pending = ovs.outstanding_tax(d.year - 1)
                avail = max(0.0, v_ovs - pending - reserve_share * (v_ovs + dom_now))
            want = 0.0
            plan = {}
            for k, r in room.items():
                take = min(r, avail - want)
                if take > 0:
                    plan[k] = take
                    want += take
            if i == 0:
                got = want
                ovs.deposit_krw(core_cap - want, rate)
            else:
                got = ovs.withdraw_krw(want, px, rate, d.year) if want > 0 else 0.0
            scale = got / want if want > 0 else 0.0
            for k, amt in plan.items():
                accounts[k].deposit(amt * scale, d)
            if want > 0:
                migrations.append({"date": str(d.date()), **{k: round(v * scale) for k, v in plan.items()}})
                flow = True
        elif i == 0:
            ovs.deposit_krw(core_cap, rate)
        if i == 0 and spy_acct is not None:
            spy_acct.deposit_krw(capital * spy_sleeve, rate)
            spy_acct.buy(spy, spy_acct.cash_usd, px[spy], rate)
        last_year = d.year
        # 매매
        if change.iat[i] or flow:
            row = {t: float(wmat[i, j]) for j, t in enumerate(tickers) if wmat[i, j] > 0}
            resid = 1.0 - sum(row.values())
            if resid > 1e-9:
                row[CASH] = row.get(CASH, 0.0) + resid
            dom_vals = {k: a.value(kp) for k, a in accounts.items()}
            ovs_t, dom_t = household_targets(row, proxied, ovs.value_krw(px, rate), dom_vals)
            for k, tg in dom_t.items():  # 대체 ETF 가 없는 몫(BIL 대체도 없을 때)은 국내 계좌에 원화 현금으로 남는다
                accounts[k].rebalance_to({t: v for t, v in tg.items() if t in kp}, kp)
            ovs.rebalance_to(ovs_t, px, rate, d.year)
        v = ovs.value_krw(px, rate) + sum(a.value(kp) for a in accounts.values())
        if spy_acct is not None:
            v += spy_acct.value_krw(px, rate)
        values.append(v)

    # 끝: 전부 정산
    last = len(days) - 1
    rate = float(f.iat[last])
    px = {t: float(close.iat[last, us_cols[t]]) for t in all_us}
    kp = {t: float(kpx.iat[last, kpx.columns.get_loc(t)]) for t in proxied}
    yr = days[-1].year
    ovs_final, ovs_end_tax = ovs.final_krw(px, rate, yr)
    spy_final, spy_end_tax = spy_acct.final_krw(px, rate, yr) if spy_acct is not None else (0.0, 0.0)
    isa_end = taxable_end = 0.0
    pension_value = pension_principal = 0.0
    for k, a in accounts.items():
        if k == "isa":
            isa_end = a.settle_isa(kp) if a.opened is not None or a.value(kp) > 0 else 0.0
        elif k == "taxable":
            taxable_end = a.liquidate(kp)
        elif k == "pension":
            pension_value = a.liquidate(kp)
            pension_principal = a.principal
    base = ovs_final + spy_final + isa_end + taxable_end
    years = (days[-1] - days[0]).days / 365.25
    finals, cagr, pension_tax = {}, {}, {}
    for name, tau in TAUS.items():
        pt = pension_withdrawal_tax(pension_value, pension_principal, tau)
        pension_tax[name] = pt
        finals[name] = base + pension_value - pt
        cagr[name] = (finals[name] / capital) ** (1 / years) - 1 if years > 0 and finals[name] > 0 else float("nan")
    series = pd.Series(values, index=days)
    accts = [ovs] + ([spy_acct] if spy_acct is not None else [])
    return {
        "scheme": scheme, "capital": capital, "years": years, "start": str(days[0].date()), "end": str(days[-1].date()),
        "final_krw": finals, "cagr_after": cagr, "values_krw": series,
        "mdd": float((series / series.cummax() - 1).min()),
        "totals": {
            "overseas_cg_tax_krw": sum(sum(a.paid.values()) for a in accts) + ovs_end_tax + spy_end_tax,
            "overseas_fees_krw": sum(a.fees_krw for a in accts), "fx_cost_krw": sum(a.fx_cost_krw for a in accts),
            "overseas_div_tax_krw": sum(a.div_tax_krw for a in accts),
            "domestic_fees_krw": sum(a.fees_krw for a in accounts.values()),
            "domestic_tax_krw": sum(a.tax_krw for a in accounts.values()),
            "pension_withdrawal_tax_krw": pension_tax,
            "pension_value_krw": pension_value, "pension_principal_krw": pension_principal,
        },
        "migrations": migrations, "isa_rollovers": isa_rolls,
        "contributions": [c for a in accounts.values() for c in a.contributions],
    }


def coverage(weights: pd.DataFrame, proxied: set) -> float:
    """대체 ETF 가 있는 자산의 평균 비중 / 코어 전체 평균 비중(현금 몫 BIL 포함)."""
    w = weights.copy()
    tot = w.sum(axis=1)
    resid = (1 - tot).clip(lower=0)
    cov_num = w[[c for c in w.columns if c in proxied]].sum(axis=1) + (resid if CASH in proxied else 0.0)
    den = (tot + resid).mean()
    return float(cov_num.mean() / den) if den > 0 else 0.0


# ---------------------------------------------------------------- 1단계: 추적 오차
def tracking_stats(proxy_tr: pd.Series, ref_us: pd.Series, fx: pd.Series, min_days: int = 250) -> dict:
    """대체 ETF(원화 총수익, KRX 날짜) vs 미국 ETF 원천징수 후 총수익 × 환율.
    KRX 날짜 t 에는 t 이전 마지막 미국 종가·그날 환율을 맞춘다(장 시간 차이). 반환: 겹친 기간, 일별·월별 추적오차, 연 추적 차이(drag)."""
    p = proxy_tr.dropna()
    p = p[p > 0]
    r = (ref_us * fx.reindex(ref_us.index).ffill()).dropna()
    if p.empty or r.empty:
        return {"n_days": 0}
    left = pd.DataFrame({"date": p.index, "proxy": p.to_numpy()})
    right = pd.DataFrame({"date": r.index, "ref": r.to_numpy()})
    m = pd.merge_asof(left.sort_values("date"), right.sort_values("date"), on="date", allow_exact_matches=False).dropna()
    if len(m) < 20:
        return {"n_days": int(len(m))}
    m = m.set_index("date")
    dr = m.pct_change().dropna()
    te_d = float((dr["proxy"] - dr["ref"]).std(ddof=1) * math.sqrt(252))
    mm = m.resample("ME").last().pct_change().dropna()
    te_m = float((mm["proxy"] - mm["ref"]).std(ddof=1) * math.sqrt(12)) if len(mm) > 2 else None
    yrs = (m.index[-1] - m.index[0]).days / 365.25
    out = {"n_days": int(len(m)), "start": str(m.index[0].date()), "end": str(m.index[-1].date()), "years": round(yrs, 2),
           "te_daily_ann": te_d, "te_monthly_ann": te_m, "n_months": int(len(mm))}
    if len(m) >= min_days and yrs > 0:
        g_ref = (m["ref"].iloc[-1] / m["ref"].iloc[0]) ** (1 / yrs)
        g_px = (m["proxy"].iloc[-1] / m["proxy"].iloc[0]) ** (1 / yrs)
        out["measured_drag"] = float(1 - g_px / g_ref)  # 연 몇 % 덜 벌었나(+ 면 대체 ETF 가 뒤짐)
    return out


def decide_deduction(us_exp: float, proxy_exp: float, stats: dict, *, fixed_resid: float = 0.003, cap: float = 0.03) -> dict:
    """사전 등록 차감 규칙: 보수 차이 + 측정 잔여 추적 차이(0~3% 로 자름, 측정 불가면 0.3% 고정). 합이 음수면 0."""
    exp_diff = proxy_exp - us_exp
    if stats.get("measured_drag") is not None:
        resid_raw = stats["measured_drag"] - exp_diff
        resid, source = min(max(resid_raw, 0.0), cap), "measured"
    else:
        resid_raw, resid, source = None, fixed_resid, "fixed"
    return {"expense_diff": exp_diff, "resid_raw": resid_raw, "resid_used": resid, "source": source,
            "deduction": max(0.0, exp_diff + resid)}
