"""검증 연구 synthesis-rnd-v2: 미리 고정한 단 하나의 블렌드(시장 50% + ERC 코어 50%, 매년 재조정)를 아무도 보지 않은 1927~2007 자료로 판정. (사전 등록, 2026-10-10)

왜: synthesis-rnd-v1 은 SPY 영구보유 + ERC 코어 블렌드가 위험조정으로 낫다는 '합'을 2008~ 자료로 봤지만, 같은 구간을 이미 여러 연구가 봤고
떼어 둔 2024-10~ 도 소진됐다(가족 PBO 89%). 비율을 결과로 고르지 않으려고 50/50 하나만 미리 고정하고, 판정은 Ken French 산업 자료의
1927-07 ~ 2007-12 로 한다. 변형이 하나라 가족 PBO 는 없다.

코어 = core-longrun-v1 복제 규칙(12 산업, 모멘텀 상위 4, 시장 200일선 필터 × 0.5, 편도 10bp)에 ERC(126거래일 공분산 위험 균등 기여) 비중.
블렌드 = 시장(Mkt-RF+RF) 50% + 코어 50%, 매년 첫 거래일 종가에 50/50 재조정(재조정 회전율 × 10bp).
PASS(모두): (a) 월별 초과수익 샤프 블렌드 > 시장, Jobson–Korkie/Memmel 한쪽 p < 0.05 (b) 연수익/|MDD| 블렌드 > 시장
           (c) 블렌드 MDD 가 시장보다 5%p 이상 얕음 (d) 4개 하위 구간 중 3개 이상에서 샤프 블렌드 > 시장.
PASS 는 전진 원장에 올릴 후보라는 뜻까지만이다.
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

from core import research_power as rp  # noqa: E402

_spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research" / "jobs" / "core-longrun-v1" / "lab.py")
lab = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "Rule"):
    _spec.loader.exec_module(lab)

JUDGE_VERSION = "synthesis-judge/v2"
BLEND_MARKET_SHARE = 0.50       # 판정 대상(사전 고정)
REPORT_MARKET_SHARE = 0.30      # 보고만: v1 에서 사후로 가장 좋아 보였던 30/70(떼어 둔 구간 샤프 최고) — 사후 선택임을 표시
P_MAX = 0.05
MDD_MARGIN = 0.05
MIN_SUB_WINS = 3


def _f(v, pct=True, sign=False, nd=1):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if pct:
        return f"{v * 100:+.{nd}f}%" if sign else f"{v * 100:.{nd}f}%"
    return f"{v:+.2f}" if sign else f"{v:.2f}"


def monthly_excess(r: pd.Series, rf: pd.Series) -> pd.Series:
    return lab.monthly(r) - lab.monthly(rf.reindex(r.index).fillna(0.0))


def summary(r: pd.Series, rf: pd.Series) -> dict:
    c, d = lab.cagr(r), lab.mdd(r)
    return {"cagr": c, "mdd": d, "return_per_mdd": c / abs(d) if d < 0 else None,
            "sharpe_monthly": lab.sharpe_monthly(r, rf), "sharpe_daily": lab.sharpe_daily(r, rf)}


def judge(blend: pd.Series, market: pd.Series, rf: pd.Series) -> dict:
    """판정 구간의 블렌드·시장 일별 수익(같은 날짜)으로 (a)~(d)."""
    sb, sm = summary(blend, rf), summary(market, rf)
    mt = lab.memmel_test(monthly_excess(blend, rf).to_numpy(), monthly_excess(market, rf).to_numpy())
    subs = []
    for a, b in lab.SUBPERIODS:
        x, y = lab.window(blend, a, b), lab.window(market, a, b)
        subs.append({"start": a, "end": b, "sharpe_blend": lab.sharpe_monthly(x, rf), "sharpe_market": lab.sharpe_monthly(y, rf),
                     "mdd_blend": lab.mdd(x), "mdd_market": lab.mdd(y)})
    wins = sum(1 for s in subs if math.isfinite(s["sharpe_blend"]) and s["sharpe_blend"] > s["sharpe_market"])
    checks = {
        "a_sharpe_memmel": bool(sb["sharpe_monthly"] > sm["sharpe_monthly"] and mt["p_one_sided"] < P_MAX),
        "b_return_per_mdd": bool(sb["return_per_mdd"] is not None and sm["return_per_mdd"] is not None
                                 and sb["return_per_mdd"] > sm["return_per_mdd"]),
        "c_mdd_5pp": bool(sb["mdd"] - sm["mdd"] >= MDD_MARGIN),
        "d_subperiod_sharpe": wins >= MIN_SUB_WINS,
    }
    return {"blend": sb, "market": sm, "memmel": mt, "subperiods": subs, "subperiod_wins": wins, "checks": checks}


def etf_era(smoke: bool) -> dict:
    """보고만: synthesis-rnd-v1 의 실제 ETF 계산(core_lab ERC 코어 비중, 배당 포함, 편도 3bp)을 세전 달러로 다시 — 2008-01 ~.
    실패하면 건너뛴다(판정과 무관)."""
    try:
        from core import champion_strategy as cs
        from core import core_lab as cl

        spy, bil = cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF
        tick = list(dict.fromkeys(list(cs.CORE_UNIVERSE) + [spy, bil]))
        if smoke:
            idx = pd.bdate_range("2006-01-02", "2012-12-31")
            rng = np.random.default_rng(5)
            adj = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(idx)))) for t in tick}, index=idx)
            adj[bil] = 90 + np.arange(len(idx)) * 0.002
        else:
            from core.market_data import get_multiple_price_history

            h = get_multiple_price_history(tick, start="2005-06-01", end=None, interval="1d")
            adj = pd.DataFrame({t: h[t]["Adj Close"] for t in tick if t in h and not h[t].empty}).sort_index()
            adj = adj.reindex(adj[spy].dropna().index)
        core_cols = [t for t in cs.CORE_UNIVERSE if t in adj.columns]
        extra = adj[[spy, bil]]
        w = cl.build_weights(adj[core_cols], extra, cl.CoreConfig(cash="bil", weighting="erc"))
        keep = adj.index >= pd.Timestamp(lab.COMPARE_START)
        core_r = cl.portfolio_returns(adj[core_cols][keep], extra[keep], w.reindex(adj.index).fillna(0.0)[keep])
        spy_r = adj[spy].pct_change(fill_method=None)[keep].fillna(0.0)
        rf = adj[bil].pct_change(fill_method=None)[keep].fillna(0.0)
        rows = {"SPY 그냥 보유": spy_r, "ERC 코어": core_r,
                "SPY 50% + ERC 코어 50%(매년 재조정)": lab.blend_returns(spy_r, core_r, BLEND_MARKET_SHARE, cs.CORE_COST_BPS_PER_SIDE),
                "SPY 30% + ERC 코어 70%(사후 선택)": lab.blend_returns(spy_r, core_r, REPORT_MARKET_SHARE, cs.CORE_COST_BPS_PER_SIDE)}
        return {"start": str(spy_r.index[0].date()), "end": str(spy_r.index[-1].date()), "basis": "세전 달러, 배당 포함, 현금 = BIL",
                "rows": {k: summary(v, rf) for k, v in rows.items()}}
    except Exception as exc:  # noqa: BLE001 — 보고용, 판정과 무관
        return {"skipped": f"{type(exc).__name__}: {exc}"[:300]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    years = (pd.Timestamp(lab.MAIN_END) - pd.Timestamp(lab.MAIN_START)).days / 365.25
    power = rp.power_report(years, 1)  # 결과를 보기 전에(구간·시도 수만)

    data = lab.synthetic_data() if a.smoke else lab.load_real()
    rf, mkt, ind = data["rf"], data["mkt"], data["ind12"]
    core_erc = lab.strategy_returns(ind, rf, lab.target_weights(ind, mkt, lab.Rule(weighting="erc")), lab.COST_BPS)
    core_eq = lab.strategy_returns(ind, rf, lab.target_weights(ind, mkt, lab.Rule()), lab.COST_BPS)

    def blend_on(share, start, end=None):
        return lab.blend_returns(lab.window(mkt, start, end), lab.window(core_erc, start, end), share, lab.COST_BPS)

    b50 = blend_on(BLEND_MARKET_SHARE, lab.MAIN_START, lab.MAIN_END)
    m_main = lab.window(mkt, lab.MAIN_START, lab.MAIN_END)
    jd = judge(b50, m_main, rf)
    noop = rp.noop_guard((b50 - m_main).tolist())
    checks = jd["checks"]
    verdicts = {k: ("PASS" if v else "FAIL") for k, v in checks.items()}
    if noop:
        verdicts["blend_50_50"] = "NOT_EVALUABLE"
    else:
        verdicts["blend_50_50"] = "PASS" if all(checks.values()) else "FAIL"
    # 효과 크기: Memmel z 를 연수의 제곱근으로 나눠 power_report 의 IR 척도에 맞춘다(z ≥ 1.645 ⇔ 효과 ≥ MDE).
    effect = jd["memmel"]["z"] / math.sqrt(years)
    if verdicts["blend_50_50"] == "FAIL":
        verdicts["fail_class"] = rp.classify_fail(effect, power)

    reported = {
        "blend_30_70_posthoc": judge(blend_on(REPORT_MARKET_SHARE, lab.MAIN_START, lab.MAIN_END), m_main, rf),
        "core_erc_alone": summary(lab.window(core_erc, lab.MAIN_START, lab.MAIN_END), rf),
        "core_equal_alone": summary(lab.window(core_eq, lab.MAIN_START, lab.MAIN_END), rf),
    }
    m_cmp = lab.window(mkt, lab.COMPARE_START)
    compare = {"market": summary(m_cmp, rf), "core_erc": summary(lab.window(core_erc, lab.COMPARE_START), rf),
               "blend_50_50": summary(blend_on(BLEND_MARKET_SHARE, lab.COMPARE_START), rf),
               "blend_30_70_posthoc": summary(blend_on(REPORT_MARKET_SHARE, lab.COMPARE_START), rf),
               "start": lab.COMPARE_START, "end": str(m_cmp.index[-1].date())}
    yearly = lab.yearly_table(blend_on(BLEND_MARKET_SHARE, lab.MAIN_START), lab.window(mkt, lab.MAIN_START))

    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "source": data["source"],
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "power": power, "effect_ir_equiv": effect, "noop_guard": noop,
              "rule": {"blend": f"market {BLEND_MARKET_SHARE:.0%} + ERC core {1 - BLEND_MARKET_SHARE:.0%}, annual rebalance (first trading day)",
                       "calendar": "weekdays (weekend returns compounded into next weekday)",
                       "core": "FF12 momentum top4 (252 rows, >0), ERC 126-row cov × picks/4, market SMA200 filter ×0.5, RF cash, 10bp",
                       "main_window": [lab.MAIN_START, lab.MAIN_END], "subperiods": lab.SUBPERIODS,
                       "sharpe_basis": "monthly excess over RF, annualized ×√12", "p_max": P_MAX, "mdd_margin": MDD_MARGIN,
                       "min_subperiod_wins": MIN_SUB_WINS},
              "main": jd, "reported": reported, "compare_2008": compare, "etf_era": etf_era(a.smoke), "yearly_blend_vs_market": yearly}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(result, a.smoke), encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


def render(r: dict, smoke: bool) -> str:
    m, v = r["main"], r["verdicts"]
    b, mk, mt = m["blend"], m["market"], m["memmel"]
    L = [f"# 정반합 R&D v2 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "결과를 보기 전에 고정한 단 하나의 블렌드 — **시장 50% + ERC 코어 50%, 매년 첫 거래일 재조정** — 를 아무도 보지 않은 "
         f"**{lab.MAIN_START} ~ {lab.MAIN_END}** Ken French 자료로 판정한다. 변형이 하나라 가족 PBO 는 없다.", "",
         f"**판정: {v['blend_50_50']}**" + (f" ({v['fail_class']})" if "fail_class" in v else "")
         + " — PASS 는 '전진 원장에 올릴 후보'까지만 뜻한다.", "",
         "| 조건(사전 고정) | 관측 | 판정 |", "|---|---|---|",
         f"| (a) 샤프(월별 초과수익) 블렌드 > 시장, Memmel 한쪽 p < {P_MAX} | {_f(b['sharpe_monthly'], False)} vs {_f(mk['sharpe_monthly'], False)}, "
         f"z {mt['z']:.2f}, p {mt['p_one_sided']:.3f} | {v['a_sharpe_memmel']} |",
         f"| (b) 연수익/최대낙폭 블렌드 > 시장 | {_f(b['return_per_mdd'], False)} vs {_f(mk['return_per_mdd'], False)} | {v['b_return_per_mdd']} |",
         f"| (c) 최대낙폭이 시장보다 5%p 이상 얕음 | {_f(b['mdd'])} vs {_f(mk['mdd'])} | {v['c_mdd_5pp']} |",
         f"| (d) 4개 하위 구간 중 3개 이상 샤프 우위 | {m['subperiod_wins']}/4 | {v['d_subperiod_sharpe']} |", "",
         rp.power_line(r["power"]) + f" 이 연구의 효과 크기(Memmel z/√연수) = {r['effect_ir_equiv']:.2f}.", ""]
    if r.get("noop_guard"):
        L += [f"무효 실행: {r['noop_guard']}", ""]
    L += ["## 하위 구간", "", "| 구간 | 샤프 블렌드 | 샤프 시장 | 낙폭 블렌드 | 낙폭 시장 |", "|---|---|---|---|---|"]
    for s in m["subperiods"]:
        L.append(f"| {s['start'][:4]}~{s['end'][:4]} | {_f(s['sharpe_blend'], False)} | {_f(s['sharpe_market'], False)} | {_f(s['mdd_blend'])} | {_f(s['mdd_market'])} |")

    def row(name, s):
        return f"| {name} | {_f(s['cagr'])} | {_f(s['mdd'])} | {_f(s['return_per_mdd'], False)} | {_f(s['sharpe_monthly'], False)} |"

    rep = r["reported"]
    L += ["", "## 판정 구간 비교(보고 포함)", "", "| | 연수익 | 최대낙폭 | 수익/낙폭 | 샤프(월별) |", "|---|---|---|---|---|",
          row("시장 50% + ERC 코어 50% (판정 대상)", b), row("시장(Mkt-RF+RF)", mk),
          row("시장 30% + ERC 코어 70% (보고만 — v1 사후 최고, 사후 선택)", rep["blend_30_70_posthoc"]["blend"]),
          row("ERC 코어 단독", rep["core_erc_alone"]), row("동일가중 코어 단독", rep["core_equal_alone"]), ""]
    c = r["compare_2008"]
    L += [f"## 2008~{c['end'][:4]} (Ken French 자료, 이미 여러 연구가 본 구간 — 보고만)", "",
          "| | 연수익 | 최대낙폭 | 수익/낙폭 | 샤프(월별) |", "|---|---|---|---|---|",
          row("시장 50% + ERC 코어 50%", c["blend_50_50"]), row("시장", c["market"]), row("ERC 코어", c["core_erc"]),
          row("시장 30% + ERC 코어 70% (사후 선택)", c["blend_30_70_posthoc"]), ""]
    e = r["etf_era"]
    L += ["## ETF 시대(실제 SPY·17자산 ERC 코어, 보고만)", ""]
    if "skipped" in e:
        L += [f"건너뜀: {e['skipped']}", ""]
    else:
        L += [f"{e['start']} ~ {e['end']}, {e['basis']}. 2024-10~ 구간 포함(소진된 구간 — 판정에 쓰지 않음).", "",
              "| | 연수익 | 최대낙폭 | 수익/낙폭 | 샤프(월별) |", "|---|---|---|---|---|"]
        L += [row(k, s) for k, s in e["rows"].items()] + [""]
    L += ["## 연도별(블렌드 50/50 vs 시장, 세전)", "", "| 연도 | 블렌드 | 시장 | 차이 |", "|---|---|---|---|"]
    for y in r["yearly_blend_vs_market"]:
        L.append(f"| {y['year']}{'' if y['year'] <= 2007 else ' (비교)'} | {_f(y['strategy'])} | {_f(y['market'])} | {_f(y['excess'], sign=True)} |")
    L += ["", "판정 규칙은 결과를 보기 전에 SPEC.md·run.py 에 고정했다. 한계: 산업 포트폴리오는 실제 17자산 코어와 다르고(메커니즘만 시험), "
          "세금·환율은 넣지 않았다(세전). Memmel 검정은 정규·독립 가정이라 월별 수익으로 계산했다. PASS 도 엔진 자동 반영이 아니다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
