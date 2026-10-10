"""검증 연구 lev-trend-v1: 추세 필터를 건 '적당한' 레버리지 SPY (사전 등록, 2026-10-10).

사용자 목표(2026-10-10): "안전하면서 시장을 압도적으로 이기는 방법". 24개 사전 등록 연구가 '고르기·비중·국면'으로는
세후 SPY 를 못 이긴다는 것을 보였다. 남은 거의 유일한 기계적 경로는 '시장 베타를 더 싸게 더 많이' 갖되 큰 하락장에서는
빠지는 것이다. 근거(우리 엔진에서 재현한 것 아님): Gayed & Bilello(2016, "Leverage for the Long Run", SSRN 2741701) —
S&P500 이 200일선 위일 때만 1.25~3배, 아래면 단기국채로 두면 1928~2015 에 위험 대비·절대 수익 모두 보유보다 나았다.
Moreira & Muir(2017, JF) — 변동성 역수로 노출을 조절하면 주식 샤프가 오른다. 반론: 200일선 오신호(whipsaw) 비용,
일일 리셋 레버리지의 변동성 감쇠, 2020-03 같은 급락은 신호보다 빠르다. dead_ends.md#4(모멘텀 크래시 필터)와는 다르다 —
여기서는 종목 선택이 아니라 지수 노출 자체를 켜고 끈다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
레버리지 자산: 합성 L배 SPY(일일 리셋). 일 수익 = L × SPY(배당 포함) − (L−1) × (BIL 일 수익 + 연 1.0%/252) − 연 0.9%/252(보수).
  즉 차입 비용과 레버리지 ETF 보수를 명시적으로 깎는다(공매도 없음, 마진 계좌 없음 — SSO·UPRO 같은 상품을 가정).
신호: 전날 SPY 종가 vs 200일 단순이동평균. 위 = 레버리지 자산, 아래 = BIL.
G1 1.5배, 매일 신호                G2 2배, 매일 신호
G3 1.5배, 월초 신호만(오신호·세금 줄이기)
G4 변동성 목표: 월초에 노출 = min(2, 15% ÷ 직전 20일 SPY 연환산 변동성), 200일선 아래면 0. 노출 = 2배 자산 비중(노출/2) + 나머지 BIL.
비교 대상: SPY 그냥 보유. 기간 2008-01-02 ~ 실행일(2008 금융위기 포함), 마지막 2년 떼어 둠. 계좌 core/tax_fx 기본(3,000만 원, 원화, 양도세 22%).
판정 lever-judge/v1 — 변형마다, 모두 만족해야 PASS(= 사람 검토 후보일 뿐, 엔진 자동 반영 없음):
  1. 세후·청산 후 원화 연수익 ≥ SPY + 3.0%p (전체)
  2. 원화 최대낙폭 ≥ −29.2% (champion-aftertax-v1 이 잰 현 챔피언 −24.2% + 5%p 허용; 그보다 나쁘면 탈락)
  3. 떼어 둔 2년 세후·청산 후 원화 > SPY
  4. 앞 구간 SPY 대비 일별 초과수익 DSR ≥ 0.95, 시도 수 = 6(이 연구 4 + sat-trend-v1 2, 함께 등록한 전부)
  5. 가족(SPY + 이 연구 변형) CSCV PBO ≤ 25%
  6. 비용 스트레스: 차입 가산금리 연 3.0%, 보수 연 1.0% 로도 세후·청산 후 ≥ SPY + 1.0%p
한계: 합성 상품(실제 SSO 는 2006 상장, 추적오차·스왑 비용 다름), 레버리지 ETF 의 국내 세제는 해외 ETF 와 같다고 가정, 일봉 종가 체결.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import sprint_lab as sp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JUDGE_VERSION = "lever-judge/v1"
START = "2008-01-02"
SPY, BIL = "SPY", "BIL"
CAPITAL = 30_000_000
EDGE = 0.03
MDD_FLOOR = -0.242 - 0.05
N_TRIALS = 6
STRESS_EDGE = 0.01
BASE_COST = {"spread": 0.010, "fee": 0.009}
STRESS_COST = {"spread": 0.030, "fee": 0.010}


def load_data(smoke: bool):
    if smoke:
        idx = pd.bdate_range("2005-01-03", "2013-12-31")
        rng = np.random.default_rng(7)
        drift = np.where((idx >= "2008-06-01") & (idx < "2009-03-01"), -0.002, 0.0005)
        spy = 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.012, len(idx))))
        close = pd.DataFrame({SPY: spy, BIL: 90 + np.arange(len(idx)) * 0.002}, index=idx)
        return close, close.copy(), pd.Series(1100.0, index=idx)
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history([SPY, BIL], start="2005-01-01", end=None, interval="1d")
    close = pd.DataFrame({t: h[t]["Close"] for t in (SPY, BIL)}).sort_index()
    adj = pd.DataFrame({t: h[t]["Adj Close"] for t in (SPY, BIL)}).sort_index()
    days = close[SPY].dropna().index
    return close.reindex(days).ffill(), adj.reindex(days).ffill(), tx.usdkrw_series()


def synthetic_levered(adj: pd.DataFrame, lev: float, spread: float, fee: float) -> pd.Series:
    r = adj[SPY].pct_change().fillna(0.0)
    rb = adj[BIL].pct_change().fillna(0.0)
    rl = lev * r - (lev - 1) * (rb + spread / 252) - fee / 252
    return 100 * (1 + rl).cumprod()


def build_weights(close, adj, start, lev, monthly, vol_target=None):
    days = close.index[close.index >= pd.Timestamp(start)]
    sma = close[SPY].rolling(200, min_periods=200).mean()
    above = (close[SPY] > sma).shift(1)
    vol = adj[SPY].pct_change().rolling(20).std().shift(1) * np.sqrt(252)
    lv = f"SPY{lev:g}X"
    w = pd.DataFrame(np.nan, index=days, columns=[lv, BIL])
    month_first = pd.Series(days, index=days).groupby(days.to_period("M")).transform("first")
    decide = days if not monthly else days[days == month_first.values]
    for d in decide:
        on = bool(above.get(d, False)) if pd.notna(above.get(d, np.nan)) else False
        if vol_target is None:
            x = 1.0 if on else 0.0
        else:
            expo = min(lev, vol_target / max(float(vol.get(d, np.nan)) if pd.notna(vol.get(d, np.nan)) else 1.0, 1e-6)) if on else 0.0
            x = expo / lev
        w.loc[d] = [x, 1.0 - x]
    w = w.ffill().fillna({lv: 0.0, BIL: 1.0})
    # 매일 신호에서 실제로 바뀐 날만 매매하도록 같은 값 유지(simulate 는 목표가 바뀌는 날만 매매)
    return w


def judge(names, daily, stats, days, split, n_trials=N_TRIALS):
    """names[0] = 비교 대상 'SPY'. 공통 판정(lever-judge/v1, sat-trend-v1 도 그대로 씀)."""
    is_mask = np.asarray(days < split)
    mat = np.column_stack([daily[k].reindex(days).fillna(0.0).to_numpy() for k in names])
    pbo = sp.cscv_pbo(mat[is_mask])
    act = {k: sp.moments((daily[k] - daily["SPY"]).reindex(days).fillna(0.0)[is_mask].to_numpy()) for k in names[1:]}
    srs = [m["sr"] for m in act.values()]
    verdicts, details = {}, {}
    for k in names[1:]:
        mo = act[k]
        dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], n_trials, srs)["dsr"]
        s, b = stats[k], stats["SPY"]
        checks = {"after_tax_ge_spy_plus_3pp": s["cagr_liq"] >= b["cagr_liq"] + EDGE,
                  "krw_mdd_ge_-29.2pct": s["mdd"] >= MDD_FLOOR,
                  "holdout_after_tax_gt_spy": s["cagr_liq_holdout"] > b["cagr_liq_holdout"],
                  "dsr_ge_0.95": dsr >= sp.DSR_MIN,
                  "family_pbo_le_25pct": pbo is not None and pbo["pbo"] <= sp.PBO_MAX}
        if "cagr_liq_stress" in s:
            checks["stress_after_tax_ge_spy_plus_1pp"] = s["cagr_liq_stress"] >= b["cagr_liq"] + STRESS_EDGE
        verdicts[k] = "PASS" if all(checks.values()) else "FAIL"
        details[k] = {"checks": checks, "dsr": dsr}
    return verdicts, details, pbo


def run_account(parts, close, adj, fx, lo=None):
    """parts: [(weights, capital)] — 계좌마다 따로 굴려 합친다."""
    vals, liq, tax = 0, 0.0, 0.0
    for w, cap in parts:
        ww = w if lo is None else w[w.index >= lo]
        r = tx.simulate(ww, close, adj, fx, tx.AccountConfig(initial_krw=cap))
        vals = vals + r["values_krw"]
        liq += r["final_after_liquidation_krw"]
        tax += r["totals"]["capital_gains_tax_krw"]
    return vals, liq, tax


def summarize(variants, close, adj, fx, days, split, capital=CAPITAL):
    yrs = (days[-1] - days[0]).days / 365.25
    yrs_ho = (days[-1] - split).days / 365.25
    stats, daily = {}, {}
    for k, (label, parts) in variants.items():
        vals, liq, tax = run_account(parts, close, adj, fx)
        _, liq_ho, _ = run_account(parts, close, adj, fx, split)
        daily[k] = vals.pct_change().fillna(0.0)
        dd = float((vals / vals.cummax() - 1).min())
        stats[k] = {"label": label, "cagr_liq": (liq / capital) ** (1 / yrs) - 1,
                    "cagr_liq_holdout": (liq_ho / capital) ** (1 / yrs_ho) - 1, "mdd": dd, "tax_m": tax / 1e6,
                    "trades": int(sum((w.diff().abs().sum(axis=1) > 1e-9).sum() for w, _ in parts))}
    return stats, daily


def write_report(out, title, verdicts, details, stats, names, pbo, split, smoke, notes):
    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"
    lines = [f"# {title} ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
             f"가족 PBO {pct((pbo or {}).get('pbo'))} · 떼어 둔 구간 {split.date()}~ · DSR 시도 수 {N_TRIALS}", "",
             "| | 판정 | 세후·청산 후(전체) | 떼어 둔 2년 | 원화 MDD | 비용 스트레스 | DSR | 매매일 | 양도세(백만) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for k in names:
        s = stats[k]
        d = details.get(k, {})
        lines.append(f"| {s['label']} | {verdicts.get(k, '기준')} | {pct(s['cagr_liq'])} | {pct(s['cagr_liq_holdout'])} | {pct(s['mdd'])} | "
                     f"{pct(s.get('cagr_liq_stress'))} | {'—' if 'dsr' not in d else f'{d['dsr']:.2f}'} | {s['trades']} | {s['tax_m']:.1f} |")
    lines += ["", "판정: 세후 ≥ SPY + 3%p & 원화 MDD ≥ −29.2% & 떼어 둔 2년 > SPY & DSR ≥ 0.95(시도 6) & 가족 PBO ≤ 25%"
              " (& 레버리지 변형은 비용 스트레스 ≥ SPY + 1%p). PASS 도 사람 검토 후보일 뿐 엔진에 반영되지 않는다.", *notes]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    close0, adj0, fx = load_data(a.smoke)
    start = "2006-01-02" if a.smoke else START
    specs = {"G1": ("1.5배, 매일 신호", 1.5, False, None), "G2": ("2배, 매일 신호", 2.0, False, None),
             "G3": ("1.5배, 월초 신호", 1.5, True, None), "G4": ("변동성 목표 15%(최대 2배), 월초", 2.0, True, 0.15)}

    def data_with(cost):
        close, adj = close0.copy(), adj0.copy()
        for lev in (1.5, 2.0):
            s = synthetic_levered(adj0, lev, cost["spread"], cost["fee"])
            close[f"SPY{lev:g}X"] = s
            adj[f"SPY{lev:g}X"] = s
        return close, adj

    close, adj = data_with(BASE_COST)
    closes, adjs = data_with(STRESS_COST)
    weights = {k: build_weights(close, adj, start, lev, m, vt) for k, (_, lev, m, vt) in specs.items()}
    days = next(iter(weights.values())).index
    split = days[-1] - pd.DateOffset(years=2)
    variants = {"SPY": ("SPY 그냥 보유", [(tx.buy_and_hold_weights(days), CAPITAL)])}
    variants.update({k: (f"{k} {lab}", [(weights[k], CAPITAL)]) for k, (lab, *_r) in specs.items()})
    stats, daily = summarize(variants, close, adj, fx, days, split)
    yrs = (days[-1] - days[0]).days / 365.25
    for k in specs:
        _, liq, _ = run_account([(weights[k], CAPITAL)], closes, adjs, fx)
        stats[k]["cagr_liq_stress"] = (liq / CAPITAL) ** (1 / yrs) - 1
    names = ["SPY", *specs]
    verdicts, details, pbo = judge(names, daily, stats, days, split)
    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "stats": stats, "family_pbo": pbo,
              "period": [str(days[0].date()), str(days[-1].date())], "holdout_start": str(split.date()),
              "costs": {"base": BASE_COST, "stress": STRESS_COST}}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    write_report(out, "추세 필터 레버리지 SPY v1", verdicts, details, stats, names, pbo, split, a.smoke,
                 ["한계: 합성 일일 리셋 상품(차입 BIL+1%·보수 0.9% 가정), 일봉 종가 체결, 해외 ETF 세제 가정. 과거 결과이며 앞으로의 수익을 뜻하지 않는다."])
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
