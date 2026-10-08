"""검증 연구 rebound-rnd-v1: 코어가 하락장 직후 반등(2009·2016·2019·2020·2023)을 빨리 잡아, 새틀라이트처럼 SPY 대비 알파를 낼 수 있나. (사전 등록, 2026-10-08)

배경: 2023 챔피언 +5.8% vs SPY +26.2%. 코어가 12개월 모멘텀으로 2022 승자(XLE·DBC)를 오래 들고 XLK 는 5월에야 편입,
1월 코어의 75% 가 BIL(12개월 > 0 자격을 통과한 자산이 적음) — docs/CHAMPION_2023_2026_CRYPTO_RESEARCH.md.
사용자 의도(2026-10-08): "새틀라이트를 통해 alpha 를 찾는 역할을 코어도 어느 정도 할 수 있도록."

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
기준선 V0 = 라이브 코어(core_lab: 16자산, 가격 12개월 모멘텀 상위 4, 12개월 > 0, SPY 200일선 아래면 절반, 남는 몫 BIL, 월초). 파라미터 탐색 없음:
  H1 전환점 가속 — SPY 가 200일선 아래→위로 올라선 뒤 6개월 동안 순위·자격을 3개월(63거래일) 수익률로
  H2 빈 슬롯은 SPY — 자격 미달로 비는 슬롯은 SPY 가 200일선 위면 SPY, 아니면 BIL(시장필터 축소분은 그대로 BIL)
  H3 H1 + H2
  H4 식은 승자 제외 — 최근 63거래일 수익률이 SPY 보다 10%p 넘게 뒤진 자산은 그달 제외
  H5 국면 전환 — 월초 점검 때 SPY 가 200일선 위(강세·안정)면 SPY 100%(시장 흐름을 탄다), 아래(고꾸라짐)면 V0 코어의 방어 운용
     (사용자 의견 2026-10-08: "강세장·안정적일 때는 시장 흐름을 타다가 고꾸라질 때는 방어적으로")
기간 2008-01 ~ 실행일(배당 포함 총수익, 편도 3bp, 다음 날 체결), 마지막 2년은 떼어 둔다.
판정 rebound-judge/v1 — 가설마다, 모두 만족해야 PASS(사람 검토 대기, 엔진 자동 반영 없음):
  1. 앞 구간 샤프(BIL 초과) > V0, 그리고 V0 대비 초과수익의 Deflated Sharpe ≥ 0.95(시도 5)
  2. 가족 전체(V0 + H1~H5)의 CSCV 과적합 확률 PBO ≤ 25%
  3. 떼어 둔 2년 샤프 > V0
  4. 카카오페이증권 계좌(tax_fx 기본, 3,000만 원, 원화) 세후·청산 후 연수익이 V0 보다 높음(전체 기간)
보고(판정과 별도, 사용자 목표 '코어 알파'): 세후·청산 후 연수익의 SPY 그냥 보유 대비 차이, SPY 대비 회귀 알파(연)·베타,
  반등 해(2009·2016·2019·2020·2023)와 하락 해(2008·2018·2022)의 연도별 SPY 대비 격차.
한계: 같은 기간 데이터로 여러 코어 연구가 이미 진행됨(전체 시도 수가 커서 DSR 은 이 가족 5개만 반영 — 낙관적일 수 있음), 반등 해 표본이 5개뿐.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import champion_strategy as cs  # noqa: E402
from core import core_lab as cl  # noqa: E402
from core import sprint_lab as sp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JUDGE_VERSION = "rebound-judge/v1"
START = "2008-01-01"
REBOUND_YEARS = (2009, 2016, 2019, 2020, 2023)
BEAR_YEARS = (2008, 2018, 2022)
HYPOTHESES = {
    "H1": ("전환점 가속(200일선 회복 후 6개월은 3개월 모멘텀)", {"turnaround_lookback": 63, "turnaround_months": 6}),
    "H2": ("빈 슬롯은 SPY(200일선 위일 때)", {"cash": "bil_spy"}),
    "H3": ("H1 + H2", {"turnaround_lookback": 63, "turnaround_months": 6, "cash": "bil_spy"}),
    "H4": ("식은 승자 제외(3개월 SPY 대비 −10%p)", {"cool_exclude": 0.10}),
    "H5": ("국면 전환(강세면 SPY 100%, 약세면 현 코어)", None),
}


def regime_switch_weights(core_w: pd.DataFrame, spy: pd.Series) -> pd.DataFrame:
    """H5: 코어 리밸런싱일(코어 비중이 바뀌는 월초)마다 전날 SPY 가 200일선 위면 SPY 100%, 아래면 그날 코어 비중. 다음 점검일까지 유지."""
    sma = spy.rolling(200, min_periods=200).mean()
    w = core_w.copy()
    if cs.MARKET_FILTER_TICKER not in w.columns:
        w[cs.MARKET_FILTER_TICKER] = 0.0
    month_first = pd.Series(w.index, index=w.index).groupby(w.index.to_period("M")).transform("first") == w.index
    state = None
    for i, d in enumerate(w.index):
        if month_first.iat[i] and i > 0:
            prev = w.index[i - 1]
            state = "bull" if pd.notna(sma.get(prev)) and spy.get(prev) >= sma.get(prev) else "bear"
        if state == "bull":
            w.iloc[i] = 0.0
            w.at[d, cs.MARKET_FILTER_TICKER] = 1.0
    return w


def _data(smoke: bool):
    tick = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    if smoke:
        idx = pd.bdate_range("2006-01-02", "2013-12-31")
        rng = np.random.default_rng(12)
        drift = np.where((idx >= "2008-01-01") & (idx < "2009-03-01"), -0.0015, 0.0006)
        price = pd.DataFrame({t: 50 * np.exp(np.cumsum(drift + rng.normal(0, 0.012, len(idx)))) for t in tick}, index=idx)
        price["BIL"] = 90 + np.arange(len(idx)) * 0.002
        return price, price.copy(), pd.Series(1100.0, index=idx)
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history(tick, start="2006-06-01", end=None, interval="1d")
    names = [t for t in tick if t in h and not h[t].empty]
    price = cs._closes_from_histories(h, names)
    total = cs._closes_from_histories(h, names, field="Adj Close")
    return price, total, tx.usdkrw_series()


def _split(df):
    core = [t for t in cs.CORE_UNIVERSE if t in df.columns]
    extra = df[[c for c in (cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF) if c in df.columns]]
    return df[core], extra


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    price, total, fx = _data(a.smoke)
    start = "2007-06-01" if a.smoke else START
    pc, pe = _split(price)
    tc, te = _split(total)
    base_cfg = cl.CoreConfig(cash="bil")
    cfgs = {"V0": base_cfg, **{h: cl.with_changes(base_cfg, **over) for h, (_, over) in HYPOTHESES.items() if over is not None}}
    rets, weights = {}, {}
    for k, cfg in cfgs.items():
        rets[k] = cl.run(pc, pe, cfg, start, total=(tc, te))
        weights[k] = cl.build_weights(pc, pe, cfg)
    w5 = regime_switch_weights(weights["V0"], pe[cs.MARKET_FILTER_TICKER])
    keep = tc.index >= pd.Timestamp(start)
    weights["H5"] = w5
    rets["H5"] = cl.portfolio_returns(tc[keep], te[keep], w5.reindex(tc.index).fillna(0.0)[keep])
    idx = rets["V0"].index
    bil = te[cs.CORE_CASH_ETF].pct_change(fill_method=None).reindex(idx).fillna(0.0)
    spy = te[cs.MARKET_FILTER_TICKER].pct_change(fill_method=None).reindex(idx).fillna(0.0)
    split = idx[-1] - pd.DateOffset(years=2)
    is_mask = idx < split
    names = ["V0", *HYPOTHESES]
    ex = np.column_stack([(rets[k] - bil).to_numpy() for k in names])
    pbo = sp.cscv_pbo(ex[is_mask])

    def sharpe(r):
        r = r.dropna()
        return float(r.mean() / r.std(ddof=1) * math.sqrt(252)) if len(r) > 2 and r.std(ddof=1) > 0 else float("nan")

    def after_tax(k):
        w = weights[k]
        w = w[w.index >= pd.Timestamp(start)]
        close = pd.concat([pc, pe], axis=1)
        adj = pd.concat([tc, te], axis=1)
        close, adj = close.loc[:, ~close.columns.duplicated()], adj.loc[:, ~adj.columns.duplicated()]
        r = tx.simulate(w, close, adj, fx, tx.AccountConfig())
        yrs = (w.index[-1] - w.index[0]).days / 365.25
        return {"cagr_liq": (r["final_after_liquidation_krw"] / 30_000_000) ** (1 / yrs) - 1, "cagr_pre": r["cagr_pre"],
                "mdd": r["mdd_after"], "tax_m": r["totals"]["capital_gains_tax_krw"] / 1e6}

    spy_w = pd.DataFrame({cs.MARKET_FILTER_TICKER: 1.0}, index=weights["V0"].index[weights["V0"].index >= pd.Timestamp(start)])
    weights["SPY"] = spy_w
    tax = {k: after_tax(k) for k in names + ["SPY"]}
    act_srs = [sp.moments((rets[k] - rets["V0"])[is_mask].to_numpy())["sr"] for k in HYPOTHESES]
    verdicts, details = {}, {}
    for h, (label, _) in HYPOTHESES.items():
        r, v0 = rets[h], rets["V0"]
        mo = sp.moments((r - v0)[is_mask].to_numpy())
        dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], len(HYPOTHESES), act_srs)["dsr"]
        checks = {"is_sharpe_gt_v0": sharpe((r - bil)[is_mask]) > sharpe((v0 - bil)[is_mask]), "dsr_ge_0.95": dsr >= sp.DSR_MIN,
                  "family_pbo_le_25pct": pbo is not None and pbo["pbo"] <= sp.PBO_MAX,
                  "holdout_sharpe_gt_v0": sharpe((r - bil)[~is_mask]) > sharpe((v0 - bil)[~is_mask]),
                  "after_tax_gt_v0": tax[h]["cagr_liq"] > tax["V0"]["cagr_liq"]}
        verdicts[h] = "PASS" if all(checks.values()) else "FAIL"
        details[h] = {"label": label, "checks": checks, "dsr": dsr}
    report = {}
    for k in names:
        r = rets[k]
        beta = float(np.cov(r, spy)[0, 1] / np.var(spy, ddof=1)) if np.var(spy) > 0 else float("nan")
        alpha = float(((r - bil) - beta * (spy - bil)).mean() * 252)
        yr = (1 + r).groupby(r.index.year).prod() - 1
        yspy = (1 + spy).groupby(spy.index.year).prod() - 1
        gap = (yr - yspy)
        report[k] = {"sharpe_is": sharpe((r - bil)[is_mask]), "sharpe_holdout": sharpe((r - bil)[~is_mask]), "alpha_vs_spy": alpha, "beta": beta,
                     "after_tax_vs_spy_pp": (tax[k]["cagr_liq"] - tax["SPY"]["cagr_liq"]) * 100,
                     "rebound_gap": {int(y): float(gap.get(y, np.nan)) for y in REBOUND_YEARS if y in gap.index},
                     "bear_gap": {int(y): float(gap.get(y, np.nan)) for y in BEAR_YEARS if y in gap.index}}
    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "family_pbo": pbo, "after_tax": tax, "report": report, "holdout_start": str(split.date())}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def pct(v):
        return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:+.1f}%"
    lbl = {"V0": "현 코어", **{h: f"{h} {l}" for h, (l, _) in HYPOTHESES.items()}}
    lines = [f"# 반등장 R&D v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if a.smoke else ''}", "",
             f"가족 과적합 확률 PBO {('—' if pbo is None else f'{pbo['pbo']:.0%}')} · 떼어 둔 구간 {split.date()}~", "",
             "| | 판정 | 세후 원화(청산 후) | SPY 대비(세후) | SPY 대비 알파(연) | 베타 | 샤프 앞/떼어 둔 |", "|---|---|---|---|---|---|---|"]
    for k in names:
        rp = report[k]
        lines.append(f"| {lbl[k]} | {verdicts.get(k, '기준')} | {tax[k]['cagr_liq'] * 100:.2f}% | {rp['after_tax_vs_spy_pp']:+.2f}%p | {pct(rp['alpha_vs_spy'])} | "
                     f"{rp['beta']:.2f} | {rp['sharpe_is']:.2f} / {rp['sharpe_holdout']:.2f} |")
    lines.append(f"| SPY 그냥 보유 | — | {tax['SPY']['cagr_liq'] * 100:.2f}% | — | — | 1.00 | — |")
    lines += ["", "## 반등 해·하락 해의 SPY 대비 격차(세전, 연도별)", "",
              "| | " + " | ".join(str(y) for y in REBOUND_YEARS) + " | " + " | ".join(f"하락 {y}" for y in BEAR_YEARS) + " |",
              "|---|" + "---|" * (len(REBOUND_YEARS) + len(BEAR_YEARS))]
    for k in names:
        rp = report[k]
        lines.append(f"| {lbl[k]} | " + " | ".join(pct(rp["rebound_gap"].get(y)) for y in REBOUND_YEARS) + " | "
                     + " | ".join(pct(rp["bear_gap"].get(y)) for y in BEAR_YEARS) + " |")
    lines += ["", "판정 기준: 앞 구간 샤프 > 현 코어 & DSR ≥ 0.95(시도 4), 가족 PBO ≤ 25%, 떼어 둔 2년 샤프 > 현 코어, 세후 원화 > 현 코어. "
              "SPY 대비 알파는 사용자 목표 확인용 보고이며 판정 조건이 아니다. PASS 도 사람 검토 대기.",
              "한계: 같은 기간으로 여러 코어 연구가 이미 진행됨(DSR 은 이 가족 4개만 반영), 반등 해 표본 5개."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
