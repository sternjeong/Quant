"""검증 연구 core-weight-v1: 코어 4종목을 1:1:1:1(각 21.25%) 대신 다르게 나누면 나아지나. (사전 등록, 2026-10-08)

사용자 요청(2026-10-08): "코어의 경우에도 지금은 1:1:1 로 하고 있는데 이 비도 어떻게 조종하면 될지 파악하는 R&D도 만들어줘".
종목 선정(16자산 12개월 모멘텀 상위 4, 12개월 > 0, SPY 200일선 아래 절반, 남는 몫 BIL)은 그대로 두고 '나누는 법'만 바꾼다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
W0 현 코어: 같은 비중(슬롯당 1/4)
W1 순위 가중: 1위 40% · 2위 30% · 3위 20% · 4위 10% (빈 슬롯 몫은 BIL)
W2 모멘텀 크기 비례: 12개월 수익률에 비례
W3 위험 균등 기여(ERC): 최근 126거래일 공분산으로 각 종목의 위험 기여가 같게
W4 변동성 역수(참고 — core-rnd-v1·v2 의 C09 와 같은 방식, 이미 탈락했지만 같은 판정에 다시 넣어 비교)
W5 같은 비중 + 변동성 목표 12%: 코어 예상 변동성(63일 공분산)이 12% 를 넘으면 비중을 줄이고 남는 몫은 BIL
기간 2008-01 ~ 실행일(배당 포함 총수익, 편도 3bp, 다음 날 체결), 마지막 2년 떼어 둠.
판정 core-weight-judge/v1 — 변형마다, 모두 만족해야 PASS(사람 검토 대기, 엔진 자동 반영 없음):
  1. 앞 구간 샤프(BIL 초과) > W0, W0 대비 초과의 Deflated Sharpe ≥ 0.95(시도 5)
  2. 가족(W0~W5) CSCV 과적합 확률 PBO ≤ 25%     3. 떼어 둔 2년 샤프 > W0
  4. 카카오 계좌(tax_fx 기본, 3,000만 원, 원화) 세후·청산 후 연수익 > W0
보고: 최대낙폭, 평균 회전율, 평균 BIL 비중, SPY 대비 세후 차이.
한계: 코어 연구가 같은 기간으로 여러 번 진행됨(DSR 은 이 가족 5개만 반영), W4 는 이미 본 방식.
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

_spec = importlib.util.spec_from_file_location("rebound_v1", PROJECT_ROOT / "research" / "jobs" / "rebound-rnd-v1" / "run.py")
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)

JUDGE_VERSION = "core-weight-judge/v1"
START = "2008-01-01"
VARIANTS = {
    "W1": ("순위 가중 40·30·20·10", {"weighting": "rank"}),
    "W2": ("모멘텀 크기 비례", {"weighting": "score"}),
    "W3": ("위험 균등 기여(ERC)", {"weighting": "erc"}),
    "W4": ("변동성 역수(참고, 이미 탈락한 방식)", {"weighting": "inverse_vol"}),
    "W5": ("같은 비중 + 변동성 목표 12%", {"vol_target": 0.12}),
}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    price, total, fx = rb._data(a.smoke)
    start = "2007-06-01" if a.smoke else START
    pc, pe = rb._split(price)
    tc, te = rb._split(total)
    base = cl.CoreConfig(cash="bil")
    cfgs = {"W0": base, **{k: cl.with_changes(base, **over) for k, (_, over) in VARIANTS.items()}}
    rets, weights = {}, {}
    for k, cfg in cfgs.items():
        rets[k] = cl.run(pc, pe, cfg, start, total=(tc, te))
        weights[k] = cl.build_weights(pc, pe, cfg)
    idx = rets["W0"].index
    bil = te[cs.CORE_CASH_ETF].pct_change(fill_method=None).reindex(idx).fillna(0.0)
    split = idx[-1] - pd.DateOffset(years=2)
    is_mask = idx < split
    names = list(cfgs)
    pbo = sp.cscv_pbo(np.column_stack([(rets[k] - bil).to_numpy() for k in names])[np.asarray(is_mask)])

    def sharpe(r):
        r = r.dropna()
        return float(r.mean() / r.std(ddof=1) * math.sqrt(252)) if len(r) > 2 and r.std(ddof=1) > 0 else float("nan")

    close = pd.concat([pc, pe], axis=1)
    adj = pd.concat([tc, te], axis=1)
    close, adj = close.loc[:, ~close.columns.duplicated()], adj.loc[:, ~adj.columns.duplicated()]

    def after_tax(w):
        w = w[w.index >= pd.Timestamp(start)]
        r = tx.simulate(w, close, adj, fx, tx.AccountConfig())
        yrs = (w.index[-1] - w.index[0]).days / 365.25
        return {"cagr_liq": (r["final_after_liquidation_krw"] / 30_000_000) ** (1 / yrs) - 1, "mdd": r["mdd_after"],
                "tax_m": r["totals"]["capital_gains_tax_krw"] / 1e6}

    tax = {k: after_tax(weights[k]) for k in names}
    tax["SPY"] = after_tax(pd.DataFrame({cs.MARKET_FILTER_TICKER: 1.0}, index=weights["W0"].index))
    act_srs = [sp.moments((rets[k] - rets["W0"])[is_mask].to_numpy())["sr"] for k in VARIANTS]
    verdicts, details, report = {}, {}, {}
    for k in names:
        w = weights[k][weights[k].index >= pd.Timestamp(start)]
        turnover = float(w.diff().abs().sum(axis=1).mean() * 252)
        eq = (1 + rets[k]).cumprod()
        report[k] = {"sharpe_is": sharpe((rets[k] - bil)[is_mask]), "sharpe_holdout": sharpe((rets[k] - bil)[~is_mask]),
                     "mdd": float((eq / eq.cummax() - 1).min()), "turnover_per_year": turnover,
                     "avg_bil": float(w.get(cs.CORE_CASH_ETF, pd.Series(0.0, index=w.index)).mean()),
                     "after_tax_vs_spy_pp": (tax[k]["cagr_liq"] - tax["SPY"]["cagr_liq"]) * 100}
        if k == "W0":
            continue
        mo = sp.moments((rets[k] - rets["W0"])[is_mask].to_numpy())
        dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], len(VARIANTS), act_srs)["dsr"]
        checks = {"is_sharpe_gt_w0": report[k]["sharpe_is"] > report["W0"]["sharpe_is"], "dsr_ge_0.95": dsr >= sp.DSR_MIN,
                  "family_pbo_le_25pct": pbo is not None and pbo["pbo"] <= sp.PBO_MAX,
                  "holdout_sharpe_gt_w0": report[k]["sharpe_holdout"] > report["W0"]["sharpe_holdout"],
                  "after_tax_gt_w0": tax[k]["cagr_liq"] > tax["W0"]["cagr_liq"]}
        verdicts[k] = "PASS" if all(checks.values()) else "FAIL"
        details[k] = {"label": VARIANTS[k][0], "checks": checks, "dsr": dsr}
    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "family_pbo": pbo, "after_tax": tax, "report": report, "holdout_start": str(split.date())}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    lbl = {"W0": "현 코어(같은 비중)", **{k: f"{k} {v[0]}" for k, v in VARIANTS.items()}}
    lines = [f"# 코어 비중 R&D v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if a.smoke else ''}", "",
             f"가족 PBO {('—' if pbo is None else f'{pbo['pbo']:.0%}')} · 떼어 둔 구간 {split.date()}~", "",
             "| | 판정 | 샤프 앞/떼어 둔 | 최대낙폭 | 세후 원화(청산 후) | SPY 대비(세후) | 연 회전율 | 평균 BIL |", "|---|---|---|---|---|---|---|---|"]
    for k in names:
        r = report[k]
        lines.append(f"| {lbl[k]} | {verdicts.get(k, '기준')} | {r['sharpe_is']:.2f} / {r['sharpe_holdout']:.2f} | {r['mdd'] * 100:.1f}% | "
                     f"{tax[k]['cagr_liq'] * 100:.2f}% | {r['after_tax_vs_spy_pp']:+.2f}%p | {r['turnover_per_year']:.1f} | {r['avg_bil'] * 100:.0f}% |")
    lines += ["", f"SPY 그냥 보유 세후 {tax['SPY']['cagr_liq'] * 100:.2f}%.",
              "판정: 앞 구간 샤프 > 현 코어 & DSR ≥ 0.95(시도 5) & 가족 PBO ≤ 25% & 떼어 둔 2년 샤프 > 현 코어 & 세후 > 현 코어. PASS 도 사람 검토 대기.",
              "한계: 같은 기간으로 코어 연구가 여러 번 진행됨(DSR 은 이 가족만 반영), W4 는 이미 탈락한 방식의 재확인."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
