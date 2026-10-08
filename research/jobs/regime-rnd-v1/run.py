"""검증 연구 regime-rnd-v1: 강세장에는 지금 뜨는 테마(로봇이 뜨면 로봇 ETF), 시장이 고꾸라지면 현 코어의 방어 운용. (사전 등록, 2026-10-08)

사용자 의견(2026-10-08): "강세장 혹은 안정적일 때는 시장의 흐름을 타다가 시장이 고꾸라질 때는 방어적으로" +
"강세장에서 로봇이 잘나가면 SPY 가 아니라 로봇 ETF 를 들면 더 많이 벌거 아니야" → 사용자가 "등록해".

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
국면(매월 첫 거래일, 전날 종가 기준): SPY ≥ 200일 이동평균이면 강세, 아니면 약세.
강세 운용 = 테마 순환: theme-rotation-v1 과 같은 28개 테마(상장 252거래일 뒤부터), '불장' = 200일선 위 & 최근 63거래일 수익률 > SPY,
  그중 63거래일 수익률 상위 3개 같은 비중(불장 테마가 3개 미만이면 남는 슬롯은 SPY). 테마 순환 연구의 결과를 보기 전에 고정한 설정이다
  (그 연구의 18개 중 중간값 L63·상위 3·매월).
약세 운용 = 현 코어(core_lab 기본: 16자산 12개월 모멘텀 상위 4, 12개월 > 0, SPY 200일선 아래 절반, 남는 몫 BIL)의 그달 비중.
변형: R1 강세 = 테마 100% · R2 강세 = 테마 50% + SPY 50%.  참고(판정 대상 아님): H5 강세 = SPY 100%, 현 코어 V0, SPY 그냥 보유.
체결: 다음 날, 편도 5bp. 기간 2007-01 ~ 실행일, 마지막 2년은 떼어 둔다.
판정 regime-judge/v1 — 변형마다, 모두 만족해야 PASS(사람 검토 대기, 엔진 자동 반영 없음):
  1. 카카오페이증권 계좌(tax_fx 기본, 3,000만 원, 원화) 세후·청산 후 연수익이 SPY 그냥 보유보다 전체 기간 +2.0%p 이상
  2. 떼어 둔 2년의 세후·청산 후 연수익도 SPY 보다 높음
  3. 앞 구간 SPY 대비 일별 초과의 Deflated Sharpe ≥ 0.95(시도 2) & 가족(SPY·V0·H5·R1·R2) CSCV 과적합 확률 PBO ≤ 25%
  4. 세후 원화 최대낙폭이 SPY 보다 5%p 넘게 나쁘지 않음
보고: 강세·약세 국면별 SPY 대비 수익, 국면 전환 횟수, 연도별 SPY 대비 격차.
한계: 사라진 테마 ETF 는 데이터에 없음(생존편향), 테마 ETF 다수가 2010 전후 상장, 200일선 신호의 잦은 오신호(휩쏘) 비용은 결과에 그대로 반영.
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

JUDGE_VERSION = "regime-judge/v1"
START = "2007-01-01"
THEMES = ["SMH", "IGV", "SKYY", "HACK", "ROBO", "ARKK", "IBB", "XBI", "IHI", "ITA", "TAN", "ICLN", "LIT", "URA", "GDX",
          "XOP", "OIH", "KRE", "XHB", "IYT", "XRT", "FDN", "SOCL", "PHO", "XME", "COPX", "MOO", "PAVE"]  # theme-rotation-v1 과 같은 목록
L, TOP_N, BPS = 63, 3, 5.0
SPY, BIL = cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF
MIN_EDGE = 0.02
MDD_TOL = 0.05


def _data(smoke: bool):
    tick = list(dict.fromkeys(THEMES + list(cs.CORE_UNIVERSE) + [SPY, BIL]))
    if smoke:
        idx = pd.bdate_range("2005-01-03", "2014-12-31")
        rng = np.random.default_rng(21)
        drift = np.where((idx >= "2008-01-01") & (idx < "2009-03-01"), -0.0015, 0.0005)
        close = pd.DataFrame({t: 50 * np.exp(np.cumsum(drift + rng.normal(0.0001, 0.014, len(idx)))) for t in tick}, index=idx)
        close[BIL] = 90 + np.arange(len(idx)) * 0.002
        return close, close.copy(), pd.Series(1100.0, index=idx)
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history(tick, start="2005-06-01", end=None, interval="1d")
    close = pd.DataFrame({t: h[t]["Close"] for t in tick if t in h and not h[t].empty}).sort_index()
    adj = pd.DataFrame({t: h[t]["Adj Close"] for t in tick if t in h and not h[t].empty}).sort_index()
    days = close[SPY].dropna().index
    return close.reindex(days), adj.reindex(days), tx.usdkrw_series()


def month_firsts(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.Series(days, index=days).groupby(days.to_period("M")).first().values)


def theme_row(close, sma, ret, age, prev) -> dict:
    spy_r = ret.at[prev, SPY]
    bulls = []
    for t in THEMES:
        if t not in close.columns:
            continue
        c, s, r = close.at[prev, t], sma.at[prev, t], ret.at[prev, t]
        if age.at[prev, t] >= 252 and pd.notna(c) and pd.notna(s) and pd.notna(r) and c > s and pd.notna(spy_r) and r > spy_r:
            bulls.append((t, float(r)))
    bulls.sort(key=lambda kv: (-kv[1], kv[0]))
    chosen = [t for t, _ in bulls[:TOP_N]]
    row = {t: 1.0 / TOP_N for t in chosen}
    row[SPY] = row.get(SPY, 0.0) + (TOP_N - len(chosen)) / TOP_N
    return row


def build(close: pd.DataFrame, core_w: pd.DataFrame, start: str, bull_mode: str) -> tuple[pd.DataFrame, list]:
    days = close.index[close.index >= pd.Timestamp(start)]
    sma = close.rolling(200, min_periods=200).mean()
    ret = close / close.shift(L) - 1
    age = close.notna().cumsum()
    cols = list(dict.fromkeys([t for t in THEMES if t in close.columns] + list(core_w.columns) + [SPY]))
    w = pd.DataFrame(np.nan, index=days, columns=cols)
    log = []
    for d in month_firsts(days):
        i = close.index.get_loc(d)
        prev = close.index[i - 1]
        bull = pd.notna(sma.at[prev, SPY]) and close.at[prev, SPY] >= sma.at[prev, SPY]
        row = pd.Series(0.0, index=cols)
        if bull:
            if bull_mode == "spy":
                row[SPY] = 1.0
            else:
                tr = theme_row(close, sma, ret, age, prev)
                share = 1.0 if bull_mode == "theme" else 0.5
                for t, x in tr.items():
                    row[t] += x * share
                row[SPY] += 1.0 - share
        else:
            cw = core_w.loc[:d].iloc[-1] if (core_w.index <= d).any() else pd.Series(dtype=float)
            for t, x in cw.items():
                row[t] += float(x)
        w.loc[d] = row
        log.append((d, "강세" if bull else "약세", [t for t in cols if row[t] > 0]))
    w = w.ffill().fillna(0.0)
    # 약세 국면 안에서도 코어가 월중에 바꾸지 않으므로(코어도 월초 리밸런싱) 월초 값 유지로 충분하다
    return w, log


def daily_returns(w: pd.DataFrame, adj: pd.DataFrame) -> pd.Series:
    r = adj[w.columns].pct_change(fill_method=None).reindex(w.index).fillna(0.0)
    ex = w.shift(1).fillna(0.0)
    turnover = (ex - ex.shift(1).fillna(0.0)).abs().sum(axis=1)
    return (r * ex).sum(axis=1) - turnover * BPS / 1e4


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    close, adj, fx = _data(a.smoke)
    start = "2006-06-01" if a.smoke else START
    core_cols = [t for t in cs.CORE_UNIVERSE if t in close.columns]
    extra = close[[SPY, BIL]]
    core_w = cl.build_weights(close[core_cols], extra, cl.CoreConfig(cash="bil"))
    weights, logs = {}, {}
    for name, mode in (("R1", "theme"), ("R2", "half"), ("H5", "spy")):
        weights[name], logs[name] = build(close, core_w, start, mode)
    days = weights["R1"].index
    weights["V0"] = core_w.reindex(days).fillna(0.0)
    weights["SPY"] = pd.DataFrame({SPY: 1.0}, index=days)
    names = ["SPY", "V0", "H5", "R1", "R2"]
    rets = {k: daily_returns(weights[k], adj) for k in names}
    split = days[-1] - pd.DateOffset(years=2)
    is_mask = np.asarray(days < split)
    pbo = sp.cscv_pbo(np.column_stack([rets[k].to_numpy() for k in names])[is_mask])

    def after_tax(k, lo=None):
        w = weights[k] if lo is None else weights[k][weights[k].index >= lo]
        r = tx.simulate(w, close, adj, fx, tx.AccountConfig())
        yrs = (w.index[-1] - w.index[0]).days / 365.25
        return {"cagr_liq": (r["final_after_liquidation_krw"] / 30_000_000) ** (1 / yrs) - 1, "mdd": r["mdd_after"],
                "tax_m": r["totals"]["capital_gains_tax_krw"] / 1e6, "fees_m": r["totals"]["fees_krw"] / 1e6}

    tax = {k: after_tax(k) for k in names}
    tax_ho = {k: after_tax(k, split) for k in names}
    act_srs = [sp.moments((rets[k] - rets["SPY"])[is_mask].to_numpy())["sr"] for k in ("R1", "R2")]
    verdicts, details = {}, {}
    for k in ("R1", "R2"):
        mo = sp.moments((rets[k] - rets["SPY"])[is_mask].to_numpy())
        dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], 2, act_srs)["dsr"]
        edge = tax[k]["cagr_liq"] - tax["SPY"]["cagr_liq"]
        checks = {"after_tax_edge_ge_2pp": edge >= MIN_EDGE, "holdout_after_tax_gt_spy": tax_ho[k]["cagr_liq"] > tax_ho["SPY"]["cagr_liq"],
                  "dsr_ge_0.95": dsr >= sp.DSR_MIN, "family_pbo_le_25pct": pbo is not None and pbo["pbo"] <= sp.PBO_MAX,
                  "mdd_not_worse_than_spy_by_5pp": tax[k]["mdd"] >= tax["SPY"]["mdd"] - MDD_TOL}
        verdicts[k] = "PASS" if all(checks.values()) else "FAIL"
        details[k] = {"checks": checks, "dsr": dsr, "after_tax_edge_pp": edge * 100}
    regime = pd.Series({d: s for d, s, _ in logs["R1"]})
    state = regime.reindex(days).ffill()
    by_regime = {}
    for k in names:
        rr = rets[k]
        by_regime[k] = {st: float(((1 + rr[state == st]).prod()) ** (252 / max((state == st).sum(), 1)) - 1) for st in ("강세", "약세")}
    switches = int((regime != regime.shift(1)).sum() - 1)
    yearly = {k: ((1 + rets[k]).groupby(days.year).prod() - 1) for k in names}
    gap = {k: {int(y): float(yearly[k][y] - yearly["SPY"][y]) for y in yearly["SPY"].index} for k in names if k != "SPY"}
    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "family_pbo": pbo, "after_tax": tax, "after_tax_holdout": tax_ho,
              "by_regime_annualized": by_regime, "regime_switches": switches, "yearly_gap_vs_spy": gap,
              "holdout_start": str(split.date()), "recent": [(str(d.date()), s, c) for d, s, c in logs["R1"][-6:]]}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    lbl = {"SPY": "SPY 그냥 보유", "V0": "현 코어", "H5": "H5 강세 SPY / 약세 코어", "R1": "R1 강세 테마 100% / 약세 코어",
           "R2": "R2 강세 테마 50%+SPY 50% / 약세 코어"}

    def pct(v):
        return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:.1f}%"
    lines = [f"# 국면 R&D v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if a.smoke else ''}", "",
             f"국면 전환 {switches}회 · 가족 PBO {('—' if pbo is None else f'{pbo['pbo']:.0%}')} · 떼어 둔 구간 {split.date()}~", "",
             "| | 판정 | 세후 원화(청산 후) 전체 | 떼어 둔 2년 | 원화 MDD | 강세 국면 연율(세전) | 약세 국면 연율(세전) | 양도세(백만) |",
             "|---|---|---|---|---|---|---|---|"]
    for k in names:
        lines.append(f"| {lbl[k]} | {verdicts.get(k, '참고')} | {pct(tax[k]['cagr_liq'])} | {pct(tax_ho[k]['cagr_liq'])} | {pct(tax[k]['mdd'])} | "
                     f"{pct(by_regime[k]['강세'])} | {pct(by_regime[k]['약세'])} | {tax[k]['tax_m']:.1f} |")
    lines += ["", "판정 기준(R1·R2): 세후 원화가 SPY 보다 전체 +2.0%p 이상 & 떼어 둔 2년도 SPY 보다 높음 & DSR ≥ 0.95 & 가족 PBO ≤ 25% & MDD 가 SPY 보다 5%p 넘게 나쁘지 않음.",
              "", "## 연도별 SPY 대비 격차(세전)", "", "| 연도 | " + " | ".join(lbl[k] for k in names if k != "SPY") + " |",
              "|---|" + "---|" * (len(names) - 1)]
    for y in sorted(gap["R1"]):
        lines.append(f"| {y} | " + " | ".join(f"{gap[k][y] * 100:+.1f}%p" for k in names if k != "SPY") + " |")
    lines += ["", "R1 최근 판단: " + "; ".join(f"{d} {s} {', '.join(c)}" for d, s, c in result["recent"]), "",
              "한계: 사라진 테마 ETF 없음(생존편향), 테마 ETF 다수 2010 전후 상장, 200일선 오신호 비용 포함. PASS 도 사람 검토 대기."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
