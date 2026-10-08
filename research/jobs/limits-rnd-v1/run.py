"""검증 연구 limits-rnd-v1: 앞선 4개 연구(반등장·국면·테마·애널리스트)가 모두 탈락한 원인을 정면으로 고친 변형. (사전 등록, 2026-10-08)

사용자 요청(2026-10-08): "모두 탈락에서 한계를 극복할 수 있는 연구도 이어서 진행해봐".
진단된 한계: ① 세금 — 자주 갈아타 양도세 19.7~39.8백만(3,000만 원 계좌, 2007~), SPY 는 0(이연)
             ② 오신호 — 200일선 국면 전환 28회, 매번 비용·세금 ③ 쏠림 — 테마 100% 는 원화 MDD −44%.
처방: SPY 를 '영구 보유'(팔지 않음 → 세금 이연)하고 전술은 작은 비중에만, 국면 전환에는 완충 구간을 둔다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
L1 SPY 80% 영구 + 20% 현 코어                         (두 계좌로 계산: SPY 계좌는 끝까지 팔지 않음)
L2 SPY 80% 영구 + 20% R1(강세 테마 3개 / 약세 현 코어) (regime-rnd-v1 의 R1 규칙 그대로)
L3 H5 + 완충: 약세 진입은 SPY < 200일선 × 0.97, 강세 복귀는 SPY ≥ 200일선 (월초 판단) — 강세 SPY 100%, 약세 현 코어
L4 R2 + 완충: 같은 완충, 강세 = 테마 50% + SPY 50%, 약세 = 현 코어
L5 SPY 50% 영구 + 50% 현 코어
비교 대상: SPY 그냥 보유. 기간 2007-01 ~ 실행일, 편도 5bp, 마지막 2년 떼어 둠. 계좌: tax_fx 기본(카카오, 3,000만 원, 원화).
판정 limits-judge/v1 — 변형마다, 모두 만족해야 PASS(사람 검토 대기, 엔진 자동 반영 없음):
  1. 세후·청산 후 원화 연수익 ≥ SPY + 0.5%p (전체)       2. 떼어 둔 2년도 세후·청산 후 ≥ SPY
  3. 원화 최대낙폭이 SPY 보다 나쁘지 않음                   4. 앞 구간 SPY 대비 일별 초과 DSR ≥ 0.95(시도 5) & 가족 PBO ≤ 25%
보고: 세후 수익/최대낙폭(위험 대비), 양도세 합계, 국면 전환 횟수.
한계: 두 계좌 계산은 250만 원 공제를 계좌마다 따로 적용(실제는 합산 — 청산 해에 최대 55만 원 정도 유리하게 계산됨), 테마 생존편향.
"""

from __future__ import annotations

import argparse
import importlib.util
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

_spec = importlib.util.spec_from_file_location("regime_v1", PROJECT_ROOT / "research" / "jobs" / "regime-rnd-v1" / "run.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

JUDGE_VERSION = "limits-judge/v1"
START = "2007-01-01"
SPY, BIL = rg.SPY, rg.BIL
EDGE = 0.005
ENTER_BEAR, EXIT_BEAR = 0.97, 1.00
CAPITAL = 30_000_000


def build_hysteresis(close, core_w, start, bull_mode):
    days = close.index[close.index >= pd.Timestamp(start)]
    sma = close.rolling(200, min_periods=200).mean()
    ret = close / close.shift(rg.L) - 1
    age = close.notna().cumsum()
    cols = list(dict.fromkeys([t for t in rg.THEMES if t in close.columns] + list(core_w.columns) + [SPY]))
    w = pd.DataFrame(np.nan, index=days, columns=cols)
    state, switches, last = "bull", 0, None
    for d in rg.month_firsts(days):
        i = close.index.get_loc(d)
        prev = close.index[i - 1]
        s, px = sma.at[prev, SPY], close.at[prev, SPY]
        if pd.notna(s):
            if state == "bull" and px < s * ENTER_BEAR:
                state = "bear"
            elif state == "bear" and px >= s * EXIT_BEAR:
                state = "bull"
        if last is not None and state != last:
            switches += 1
        last = state
        row = pd.Series(0.0, index=cols)
        if state == "bull":
            if bull_mode == "spy":
                row[SPY] = 1.0
            else:
                tr = rg.theme_row(close, sma, ret, age, prev)
                for t, x in tr.items():
                    row[t] += x * 0.5
                row[SPY] += 0.5
        else:
            cw = core_w.loc[:d].iloc[-1]
            for t, x in cw.items():
                row[t] += float(x)
        w.loc[d] = row
    return w.ffill().fillna(0.0), switches


def account(w, close, adj, fx, capital, lo=None):
    w = w if lo is None else w[w.index >= lo]
    r = tx.simulate(w, close, adj, fx, tx.AccountConfig(initial_krw=capital))
    return r


def combine(parts, data, lo=None):
    """parts: [(weights, capital)] 각자 계좌, data: (close, adj, fx). 합친 가치·청산 후 금액·양도세."""
    res = [account(w, *data, cap, lo) for w, cap in parts]
    vals = sum(r["values_krw"] for r in res)
    liq = sum(r["final_after_liquidation_krw"] for r in res)
    tax = sum(r["totals"]["capital_gains_tax_krw"] for r in res)
    return vals, liq, tax


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    close, adj, fx = rg._data(a.smoke)
    start = "2006-06-01" if a.smoke else START
    core_cols = [t for t in cs.CORE_UNIVERSE if t in close.columns]
    core_w = cl.build_weights(close[core_cols], close[[SPY, BIL]], cl.CoreConfig(cash="bil"))
    r1, _ = rg.build(close, core_w, start, "theme")
    days = r1.index
    core_d = core_w.reindex(days).fillna(0.0)
    spy_w = pd.DataFrame({SPY: 1.0}, index=days)
    l3, sw3 = build_hysteresis(close, core_w, start, "spy")
    l4, sw4 = build_hysteresis(close, core_w, start, "half")
    variants = {
        "L1": ("SPY 80% 영구 + 현 코어 20%", [(spy_w, 0.8 * CAPITAL), (core_d, 0.2 * CAPITAL)]),
        "L2": ("SPY 80% 영구 + R1 국면·테마 20%", [(spy_w, 0.8 * CAPITAL), (r1, 0.2 * CAPITAL)]),
        "L3": ("완충 국면 전환(강세 SPY / 약세 코어)", [(l3, CAPITAL)]),
        "L4": ("완충 국면 전환(강세 테마 50%+SPY 50% / 약세 코어)", [(l4, CAPITAL)]),
        "L5": ("SPY 50% 영구 + 현 코어 50%", [(spy_w, 0.5 * CAPITAL), (core_d, 0.5 * CAPITAL)]),
        "SPY": ("SPY 그냥 보유", [(spy_w, CAPITAL)]),
    }
    split = days[-1] - pd.DateOffset(years=2)
    yrs = (days[-1] - days[0]).days / 365.25
    yrs_ho = (days[-1] - split).days / 365.25
    stats = {}
    daily = {}
    for k, (label, parts) in variants.items():
        vals, liq, tax = combine(parts, (close, adj, fx))
        _, liq_ho, _ = combine(parts, (close, adj, fx), split)
        dd = float((vals / vals.cummax() - 1).min())
        daily[k] = vals.pct_change().fillna(0.0)
        stats[k] = {"label": label, "cagr_liq": (liq / CAPITAL) ** (1 / yrs) - 1, "cagr_liq_holdout": (liq_ho / CAPITAL) ** (1 / yrs_ho) - 1,
                    "mdd": dd, "tax_m": tax / 1e6}
        stats[k]["return_per_mdd"] = stats[k]["cagr_liq"] / abs(dd) if dd < 0 else None
    names = ["SPY", "L1", "L2", "L3", "L4", "L5"]
    is_mask = np.asarray(days < split)
    mat = np.column_stack([daily[k].reindex(days).fillna(0.0).to_numpy() for k in names])
    pbo = sp.cscv_pbo(mat[is_mask])
    act_srs = [sp.moments((daily[k] - daily["SPY"]).reindex(days).fillna(0.0)[is_mask].to_numpy())["sr"] for k in names[1:]]
    verdicts, details = {}, {}
    for k in names[1:]:
        mo = sp.moments((daily[k] - daily["SPY"]).reindex(days).fillna(0.0)[is_mask].to_numpy())
        dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], 5, act_srs)["dsr"]
        checks = {"after_tax_ge_spy_plus_0.5pp": stats[k]["cagr_liq"] >= stats["SPY"]["cagr_liq"] + EDGE,
                  "holdout_after_tax_ge_spy": stats[k]["cagr_liq_holdout"] >= stats["SPY"]["cagr_liq_holdout"],
                  "mdd_not_worse_than_spy": stats[k]["mdd"] >= stats["SPY"]["mdd"],
                  "dsr_ge_0.95": dsr >= sp.DSR_MIN, "family_pbo_le_25pct": pbo is not None and pbo["pbo"] <= sp.PBO_MAX}
        verdicts[k] = "PASS" if all(checks.values()) else "FAIL"
        details[k] = {"checks": checks, "dsr": dsr}
    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "stats": stats, "family_pbo": pbo, "switches": {"L3": sw3, "L4": sw4},
              "holdout_start": str(split.date())}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"
    lines = [f"# 한계 극복 R&D v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if a.smoke else ''}", "",
             f"완충 국면 전환 횟수 L3 {sw3}회 · L4 {sw4}회(regime-rnd-v1 은 28회) · 가족 PBO {pct((pbo or {}).get('pbo'))} · 떼어 둔 구간 {split.date()}~", "",
             "| | 판정 | 세후·청산 후(전체) | 떼어 둔 2년 | 원화 MDD | 수익/MDD | 양도세(백만) |", "|---|---|---|---|---|---|---|"]
    for k in names:
        s = stats[k]
        lines.append(f"| {s['label']} | {verdicts.get(k, '기준')} | {pct(s['cagr_liq'])} | {pct(s['cagr_liq_holdout'])} | {pct(s['mdd'])} | "
                     f"{'—' if s['return_per_mdd'] is None else f'{s['return_per_mdd']:.2f}'} | {s['tax_m']:.1f} |")
    lines += ["", "판정: 세후 ≥ SPY + 0.5%p & 떼어 둔 2년 ≥ SPY & 원화 MDD 가 SPY 보다 나쁘지 않음 & DSR ≥ 0.95(시도 5) & 가족 PBO ≤ 25%. PASS 도 사람 검토 대기.",
              "한계: 두 계좌는 250만 원 공제를 각자 적용(청산 해에 조금 유리), 테마 ETF 생존편향."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
