"""검증 연구 synthesis-rnd-v1: 정반합 — '원수익으로 SPY를 이긴다'는 기준을 접고, 위험조정 기준으로 다시 본다. (사전 등록, 2026-10-09)

사용자 요청(2026-10-09): "지금까지 결론을 통해 극복할 수 있는지 … 정반합을 통해 새롭게 연구해볼만한 주제가 무엇인지 찾은 후 진행해봐".

## 정반합 (결과를 보기 전에 고정한 논리)
정(명제): 타이밍·종목선정·국면전환·눌림매수로 챔피언이 SPY 를 세후 원수익으로 이길 수 있다.
  → rebound-rnd-v1·regime-rnd-v1·theme-rotation-v1·analyst-rnd-v1·dip-rnd-v1·limits-rnd-v1·core-weight-v1·core-rnd-v1/v2 **전부 FAIL**(원수익 기준).
반(반명제): 그럼 그냥 SPY 만 들고 있는 게 낫다.
  → 부분적으로만 맞다. limits-rnd-v1 에서 SPY 50%+현 코어 50%가 수익/MDD 0.62 로 전체 1위(SPY 단독 0.40), core-weight-v1 에서
    위험균등기여(ERC) 가중이 떼어 둔 구간 샤프 1.50 으로 1위(현 코어 1.24, SPY 미계산이나 두 연구 모두 ERC·50/50 블렌드가 위험 지표에서 최상위).
합(새 가설, 이 연구): '세후 원수익 ≥ SPY' 라는 기준 자체가 이 강세장 데이터에서 과도하게 엄격하다. 대신 **위험조정 기준**(수익/MDD, 샤프)으로
  미리 판정을 다시 정해, ERC 가중 코어 + SPY 영구보유 블렌드가 SPY 단독과 현 코어(같은 비중) 둘 다를 위험조정으로 이기는지 확인한다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
코어 신호(선정)는 그대로, 비중만 core-weight-v1 의 ERC(위험균등기여, 126일 공분산) 사용. SPY 는 한 번 사서 끝까지 팔지 않는다(세금 이연).
S1 SPY 70% 영구 + ERC 코어 30%   S2 SPY 50% 영구 + ERC 코어 50%   S3 SPY 30% 영구 + ERC 코어 70%
비교 대상(기준): B1 SPY 그냥 보유   B2 현 코어(같은 비중, V0)
기간 2008-01 ~ 실행일(배당 포함 총수익, 편도 3bp), 마지막 2년 떼어 둠. 계좌: tax_fx 기본(카카오, 3,000만 원, 원화). 두 계좌(SPY·ERC코어)로 계산.
판정 synthesis-judge/v1 — 변형마다, 모두 만족해야 PASS(사람 검토 대기, 엔진 자동 반영 없음). **원수익 우위는 요구하지 않는다** — 이것이 이 연구의 핵심 전환:
  1. 세후·청산 후 수익/|MDD| 비율이 전체 기간에 B1·B2 둘 다보다 높음
  2. 떼어 둔 2년에서도 수익/|MDD| 비율이 B1·B2 둘 다보다 높음
  3. 떼어 둔 2년 샤프(BIL 초과)가 B1·B2 둘 다보다 높음
  4. 현 코어(B2) 대비 앞 구간 일별 초과수익의 Deflated Sharpe ≥ 0.95(시도 3) & 가족(S1~S3+B1+B2) CSCV 과적합 확률 PBO ≤ 25%
보고(판정과 별도): 원수익 비교(세후·세전), 양도세, MDD.
한계: 두 계좌 계산은 250만 원 공제를 계좌마다 따로(실제는 합산 — 청산 해에 유리하게 근사), ERC 는 코어 선정 자체는 바꾸지 않음, 같은 기간 코어 연구가 여러 번 진행됨.
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

_spec = importlib.util.spec_from_file_location("limits_v1", PROJECT_ROOT / "research" / "jobs" / "limits-rnd-v1" / "run.py")
lm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lm)

JUDGE_VERSION = "synthesis-judge/v1"
START = "2008-01-01"
CAPITAL = 30_000_000
SPY, BIL = cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF
SPY_SHARES = {"S1": 0.70, "S2": 0.50, "S3": 0.30}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    close, adj, fx = lm.rg._data(a.smoke)
    start = "2006-06-01" if a.smoke else START
    core_cols = [t for t in cs.CORE_UNIVERSE if t in close.columns]
    extra = close[[SPY, BIL]]
    extra_adj = adj[[SPY, BIL]]
    erc_w = cl.build_weights(adj[core_cols], extra_adj, cl.CoreConfig(cash="bil", weighting="erc"))
    v0_w = cl.build_weights(adj[core_cols], extra_adj, cl.CoreConfig(cash="bil"))
    days = erc_w.index[erc_w.index >= pd.Timestamp(start)]
    erc_w, v0_w = erc_w.reindex(days).fillna(0.0), v0_w.reindex(days).fillna(0.0)
    spy_w = pd.DataFrame({SPY: 1.0}, index=days)
    data = (close, adj, fx)
    split = days[-1] - pd.DateOffset(years=2)

    variants = {
        "S1": ("SPY 70% 영구 + ERC 코어 30%", [(spy_w, 0.70 * CAPITAL), (erc_w, 0.30 * CAPITAL)]),
        "S2": ("SPY 50% 영구 + ERC 코어 50%", [(spy_w, 0.50 * CAPITAL), (erc_w, 0.50 * CAPITAL)]),
        "S3": ("SPY 30% 영구 + ERC 코어 70%", [(spy_w, 0.30 * CAPITAL), (erc_w, 0.70 * CAPITAL)]),
        "B1": ("SPY 그냥 보유", [(spy_w, CAPITAL)]),
        "B2": ("현 코어(같은 비중)", [(v0_w, CAPITAL)]),
    }
    yrs = (days[-1] - days[0]).days / 365.25
    yrs_ho = (days[-1] - split).days / 365.25
    stats, daily = {}, {}
    for k, (label, parts) in variants.items():
        vals, liq, tax_m = lm.combine(parts, data)
        _, liq_ho, _ = lm.combine(parts, data, split)
        dd_full = float((vals / vals.cummax() - 1).min())
        vals_ho = vals[vals.index >= split]
        dd_ho = float((vals_ho / vals_ho.cummax() - 1).min()) if len(vals_ho) else 0.0
        daily[k] = vals.pct_change().fillna(0.0)
        cagr_full = (liq / CAPITAL) ** (1 / yrs) - 1
        cagr_ho = (liq_ho / CAPITAL) ** (1 / yrs_ho) - 1
        stats[k] = {"label": label, "cagr_liq": cagr_full, "cagr_liq_holdout": cagr_ho, "mdd": dd_full, "mdd_holdout": dd_ho,
                    "tax_m": tax_m / 1e6, "return_per_mdd": cagr_full / abs(dd_full) if dd_full < 0 else None,
                    "return_per_mdd_holdout": cagr_ho / abs(dd_ho) if dd_ho < 0 else None}

    names = list(variants)
    is_mask = np.asarray(days < split)
    bil_r = adj[BIL].pct_change(fill_method=None).reindex(days).fillna(0.0)
    mat = np.column_stack([(daily[k] - bil_r).to_numpy() for k in names])
    pbo = sp.cscv_pbo(mat[is_mask])

    def sharpe(r):
        r = r.dropna()
        return float(r.mean() / r.std(ddof=1) * math.sqrt(252)) if len(r) > 2 and r.std(ddof=1) > 0 else float("nan")

    act_srs = [sp.moments((daily[k] - daily["B2"])[is_mask].to_numpy())["sr"] for k in ("S1", "S2", "S3")]
    verdicts, details = {}, {}
    for k in ("S1", "S2", "S3"):
        s = stats[k]
        mo = sp.moments((daily[k] - daily["B2"])[is_mask].to_numpy())
        dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], 3, act_srs)["dsr"]
        sh_ho = sharpe((daily[k] - bil_r)[~is_mask])
        checks = {
            "return_per_mdd_full_beats_both": (s["return_per_mdd"] is not None and stats["B1"]["return_per_mdd"] is not None
                                               and stats["B2"]["return_per_mdd"] is not None
                                               and s["return_per_mdd"] > stats["B1"]["return_per_mdd"]
                                               and s["return_per_mdd"] > stats["B2"]["return_per_mdd"]),
            "return_per_mdd_holdout_beats_both": (s["return_per_mdd_holdout"] is not None and stats["B1"]["return_per_mdd_holdout"] is not None
                                                  and stats["B2"]["return_per_mdd_holdout"] is not None
                                                  and s["return_per_mdd_holdout"] > stats["B1"]["return_per_mdd_holdout"]
                                                  and s["return_per_mdd_holdout"] > stats["B2"]["return_per_mdd_holdout"]),
            "holdout_sharpe_beats_both": sh_ho > sharpe((daily["B1"] - bil_r)[~is_mask]) and sh_ho > sharpe((daily["B2"] - bil_r)[~is_mask]),
            "dsr_ge_0.95": dsr >= sp.DSR_MIN, "family_pbo_le_25pct": pbo is not None and pbo["pbo"] <= sp.PBO_MAX,
        }
        verdicts[k] = "PASS" if all(checks.values()) else "FAIL"
        details[k] = {"label": s["label"], "checks": checks, "dsr": dsr, "sharpe_holdout": sh_ho}

    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details, "family_pbo": pbo, "stats": stats, "holdout_start": str(split.date())}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"
    def ratio(v):
        return "—" if v is None else f"{v:.2f}"
    lines = [f"# 정반합 R&D v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if a.smoke else ''}", "",
             "정(SPY를 원수익으로 이긴다)·반(그냥 SPY만)·합(위험조정 기준으로 ERC 코어+SPY 영구보유 블렌드 재평가) — 판정은 원수익 우위를 요구하지 않는다.", "",
             f"가족 PBO {('—' if pbo is None else f'{pbo['pbo']:.0%}')} · 떼어 둔 구간 {split.date()}~", "",
             "| | 판정 | 세후 원수익(전체) | 수익/MDD(전체) | 수익/MDD(떼어 둔 2년) | 샤프(떼어 둔 2년, BIL 초과) | MDD | 양도세(백만) |",
             "|---|---|---|---|---|---|---|---|"]
    for k in names:
        s = stats[k]
        sh = details.get(k, {}).get("sharpe_holdout")
        if sh is None:
            r = (daily[k] - bil_r)[~is_mask].dropna()
            sh = float(r.mean() / r.std(ddof=1) * math.sqrt(252)) if len(r) > 2 and r.std(ddof=1) > 0 else float("nan")
        lines.append(f"| {s['label']} | {verdicts.get(k, '기준')} | {pct(s['cagr_liq'])} | {ratio(s['return_per_mdd'])} | "
                     f"{ratio(s['return_per_mdd_holdout'])} | {sh:.2f} | {pct(s['mdd'])} | {s['tax_m']:.1f} |")
    lines += ["", "판정 기준: 수익/MDD(전체·떼어 둔 2년)가 SPY·현 코어 둘 다보다 높음 & 떼어 둔 2년 샤프가 둘 다보다 높음 & "
              "현 코어 대비 DSR ≥ 0.95(시도 3) & 가족 PBO ≤ 25%. **원수익이 SPY보다 높아야 한다는 조건은 없음**(이 연구의 핵심 — 정반합).",
              "", "한계: 두 계좌는 250만 원 공제를 각자 적용, ERC 는 코어 선정 자체는 바꾸지 않음, 같은 기간으로 코어 연구가 여러 번 진행됨.",
              "PASS 도 사람 검토 대기이며 엔진에 자동 반영되지 않는다."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
