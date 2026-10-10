"""검증 연구 core-longrun-v1: 코어의 정체성(저베타·양의 알파·위기 방어)이 아무도 보지 않은 1927~2007 자료에서도 성립하나. (사전 등록, 2026-10-10)

왜: 2008~2026 으로 한 25개 안팎의 연구가 모두 FAIL 이었다. 증거가 말하는 현 코어는 '베타 ≈ 0.37, SPY 대비 알파 ≈ +4%/년,
위기에 강하고 V자 반등 해에 크게 뒤지는' 자산이다. 17년·DSR 관문으로는 현실적인 효과를 검출할 수 없고, 2024-10~ 떼어 둔 구간은
이미 소진됐다. 가장 깨끗한 시험은 아무도 보지 않은 자료 — Ken French 일별 산업 포트폴리오(1926~, CRSP)다.

규칙·가설·판정은 SPEC.md 와 lab.py 에 결과를 보기 전에 고정했다(바꾸려면 새 id).
H1 저베타: 전 구간 일별 CAPM 베타 < 0.6
H2 양의 알파: 월별 초과수익 CAPM 연 알파 > 0 & Newey-West(6) t ≥ 2.0
H3 위기 방어: 시장 −20% 넘는 하락 국면(시장 자료만으로 정함)의 70% 이상에서, 같은 고점→저점 구간 전략 낙폭이 더 작음
H4 안정성: 고정 4개 하위 구간 중 3개 이상에서 연 알파 > 0
판정: H1~H4 모두 → CORE_IDENTITY_CONFIRMED / H1·H3 통과인데 알파(H2 또는 H4) 미확인 → PARTIAL / 그 밖 → NOT_CONFIRMED.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402

_spec = importlib.util.spec_from_file_location("core_longrun_lab", Path(__file__).resolve().parent / "lab.py")
lab = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "Rule"):
    _spec.loader.exec_module(lab)

JUDGE_VERSION = "core-longrun-judge/v1"


def _f(v, pct=True, sign=False, nd=1):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if pct:
        return f"{v * 100:+.{nd}f}%" if sign else f"{v * 100:.{nd}f}%"
    return f"{v:+.2f}" if sign else f"{v:.2f}"


def compute(data: dict) -> dict:
    rf, mkt = data["rf"], data["mkt"]
    w12 = lab.target_weights(data["ind12"], mkt, lab.Rule())
    s12 = lab.strategy_returns(data["ind12"], rf, w12, lab.COST_BPS)
    s12_stress = lab.strategy_returns(data["ind12"], rf, w12, lab.STRESS_BPS)
    main = lab.evaluate_core(s12, mkt, rf, lab.MAIN_START, lab.MAIN_END)
    out = {"main": main,
           "stress_30bp": lab.evaluate_core(s12_stress, mkt, rf, lab.MAIN_START, lab.MAIN_END),
           "compare_2008": lab.evaluate_core(s12, mkt, rf, lab.COMPARE_START, None, subperiods=None),
           "yearly": lab.yearly_table(lab.window(s12, lab.MAIN_START), lab.window(mkt, lab.MAIN_START)),
           "noop": rp.noop_guard((lab.window(s12, lab.MAIN_START, lab.MAIN_END) - lab.window(mkt, lab.MAIN_START, lab.MAIN_END)).tolist()),
           "ind49": None}
    if data.get("ind49") is not None:
        w49 = lab.target_weights(data["ind49"], mkt, lab.Rule())
        s49 = lab.strategy_returns(data["ind49"], rf, w49, lab.COST_BPS)
        out["ind49"] = lab.evaluate_core(s49, mkt, rf, lab.MAIN_START, lab.MAIN_END)
    last = s12.index[-1]
    out["data_end"] = str(last.date())
    out["avg_exposure_main"] = float(lab.window(w12.sum(axis=1), lab.MAIN_START, lab.MAIN_END).mean())
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    years = (lab.pd.Timestamp(lab.MAIN_END) - lab.pd.Timestamp(lab.MAIN_START)).days / 365.25
    power = rp.power_report(years, 1)  # 결과를 보기 전에 계산(구간·시도 수만 쓴다)

    data = lab.synthetic_data() if a.smoke else lab.load_real()
    res = compute(data)
    m = res["main"]
    checks = m["checks"]
    verdicts = {k: lab.label(v) for k, v in checks.items()}
    if res["noop"]:
        verdict = "NOT_EVALUABLE"
    else:
        verdict = lab.core_verdict(checks)
    verdicts["core_identity"] = verdict
    fail_class = None
    if checks["H2_positive_alpha"] is not True:
        fail_class = rp.classify_fail(m["capm"]["appraisal_ir"], power)
        verdicts["H2_fail_class"] = fail_class

    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "source": data["source"],
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "power": power, "noop_guard": res["noop"],
              "rule": {"universe": "FF 12 industries (value-weighted)", "lookback_rows": lab.LOOKBACK, "top_n": lab.TOP_N,
                       "weighting": "equal 1/4, empty slot = RF", "market_filter": f"market index < SMA{lab.SMA_WINDOW} → ×{lab.FILTER_CUT}",
                       "rebalance": "first trading day of month, signal = previous close, executed next day",
                       "cost_bps_one_way": lab.COST_BPS, "stress_bps": lab.STRESS_BPS,
                       "main_window": [lab.MAIN_START, lab.MAIN_END], "subperiods": lab.SUBPERIODS,
                       "episode_threshold": lab.EPISODE_THRESHOLD},
              "thresholds": {"H1_beta_max": lab.H1_BETA_MAX, "H2_t_min": lab.H2_T_MIN, "H3_min_share": lab.H3_MIN_SHARE,
                             "H4_min_positive": lab.H4_MIN_POSITIVE},
              **{k: v for k, v in res.items() if k != "noop"}}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(result, a.smoke), encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


def render(r: dict, smoke: bool) -> str:
    m, cp = r["main"], r["main"]["capm"]
    v = r["verdicts"]
    L = [f"# 코어 장기 검증 v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "현 코어 규칙(모멘텀 상위 4·200일선 필터)을 Ken French 일별 12 산업 포트폴리오로 복제해, 아무 연구도 보지 않은 "
         f"**{lab.MAIN_START} ~ {lab.MAIN_END}** 에서 '저베타·양의 알파·위기 방어' 정체성이 성립하는지 본다. 2008~ 는 비교용 보고.", "",
         f"**최종 판정: {v['core_identity']}**", "",
         "| 가설 | 기준(사전 고정) | 관측 | 판정 |", "|---|---|---|---|",
         f"| H1 저베타 | 일별 CAPM 베타 < {lab.H1_BETA_MAX} | 베타 {_f(cp['beta_daily'], False)} (월별 {_f(cp['beta_monthly'], False)}) | {v['H1_low_beta']} |",
         f"| H2 양의 알파 | 연 알파 > 0 & NW(6) t ≥ {lab.H2_T_MIN} | 알파 {_f(cp['alpha_annual'], sign=True)}/년, t {_f(cp['alpha_t_nw6'], False)} | {v['H2_positive_alpha']} |",
         f"| H3 위기 방어 | −20% 하락 국면의 {lab.H3_MIN_SHARE:.0%} 이상에서 낙폭이 더 작음 | {len(m['episodes'])}개 국면 중 {sum(e['defended'] for e in m['episodes'])}개 ({_f(m['defended_share'], nd=0)}) | {v['H3_crisis_defense']} |",
         f"| H4 안정성 | 4개 하위 구간 중 {lab.H4_MIN_POSITIVE}개 이상 알파 > 0 | {sum(x['alpha_annual'] > 0 for x in m['subperiods'])}/4 | {v['H4_alpha_stability']} |",
         ""]
    if "H2_fail_class" in v:
        L += [f"H2 실패의 성격: {v['H2_fail_class']} (관측 평가비율 IR {_f(cp['appraisal_ir'], False)} vs 최소 검출 효과 {r['power']['mde_ir']:.2f})", ""]
    L += [rp.power_line(r["power"]), ""]
    if r.get("noop_guard"):
        L += [f"무효 실행: {r['noop_guard']}", ""]
    s, mk = m["strategy"], m["market"]
    L += ["## 판정 구간 요약", "", "| | 연수익 | 최대낙폭 | 샤프(월별) | 샤프(일별) |", "|---|---|---|---|---|",
          f"| 코어 복제(12 산업, 편도 10bp) | {_f(s['cagr'])} | {_f(s['mdd'])} | {_f(s['sharpe_monthly'], False)} | {_f(s['sharpe_daily'], False)} |",
          f"| 시장(Mkt-RF+RF) | {_f(mk['cagr'])} | {_f(mk['mdd'])} | {_f(mk['sharpe_monthly'], False)} | {_f(mk['sharpe_daily'], False)} |",
          "", f"평균 주식 비중(필터·빈 슬롯 반영): {_f(r['avg_exposure_main'], nd=0)}", "",
          "## 하위 구간 알파", "", "| 구간 | 연 알파 | t(NW6) | 베타 |", "|---|---|---|---|"]
    for x in m["subperiods"]:
        L.append(f"| {x['start'][:4]}~{x['end'][:4]} | {_f(x['alpha_annual'], sign=True)} | {_f(x['alpha_t_nw6'], False)} | {_f(x['beta_daily'], False)} |")
    L += ["", "## 시장 하락 국면(−20% 넘음, 시장 자료로만 정함)과 '보험료'", "",
          "보험료 = 저점 뒤 12개월 동안 전략 − 시장 수익(음수면 반등에서 뒤처진 몫).", "",
          "| 고점 | 저점 | 시장 낙폭 | 전략 낙폭 | 방어 | 저점 뒤 12개월 전략−시장 |", "|---|---|---|---|---|---|"]
    for e in m["episodes"]:
        L.append(f"| {e['peak']} | {e['trough']}{' (진행 중)' if e['ongoing'] else ''} | {_f(e['market_depth'])} | {_f(e['strategy_dd'])} | "
                 f"{'예' if e['defended'] else '아니오'} | {_f(e['excess_12m_after_trough'], sign=True)} |")
    L += ["", f"평균 보험료(저점 뒤 12개월 전략−시장): {_f(m['insurance_premium_avg'], sign=True)}", ""]

    def brief(title, x):
        if not x:
            return [f"- {title}: 자료 없음"]
        c = x["capm"]
        return [f"- {title}: 베타 {_f(c['beta_daily'], False)}, 연 알파 {_f(c['alpha_annual'], sign=True)} (t {_f(c['alpha_t_nw6'], False)}), "
                f"방어 {_f(x['defended_share'], nd=0)} ({len(x['episodes'])}개 국면), 연수익 {_f(x['strategy']['cagr'])} vs 시장 {_f(x['market']['cagr'])}, "
                f"최대낙폭 {_f(x['strategy']['mdd'])} vs {_f(x['market']['mdd'])} — 기준 통과 여부 "
                + ", ".join(f"{k.split('_')[0]} {lab.label(b)}" for k, b in x["checks"].items())]
    L += ["## 보고만(판정 아님)", ""]
    L += brief("비용 스트레스(편도 30bp), 판정 구간", r["stress_30bp"])
    L += brief("49 산업 판(같은 규칙·상위 4), 판정 구간", r["ind49"])
    L += brief(f"2008~{r['data_end'][:4]} 비교 구간(이미 여러 연구가 본 구간, 12 산업)", r["compare_2008"])
    L += ["", "## 연도별(세전, 12 산업 코어 복제 vs 시장)", "", "| 연도 | 코어 복제 | 시장 | 차이 |", "|---|---|---|---|"]
    for y in r["yearly"]:
        tag = "" if y["year"] <= 2007 else " (비교)"
        L.append(f"| {y['year']}{tag} | {_f(y['strategy'])} | {_f(y['market'])} | {_f(y['excess'], sign=True)} |")
    L += ["", "판정 규칙은 결과를 보기 전에 SPEC.md·lab.py 에 고정했다. 한계: 산업 포트폴리오는 ETF 17개 후보(채권·금·해외 포함)와 다르다 — "
          "이 연구는 '주식 산업 모멘텀 + 시장 필터'라는 메커니즘만 시험한다. 1952년 이전 토요일 거래 때문에 252행 ≈ 10개월. "
          "산업 포트폴리오에는 거래비용·세금이 실제보다 적게 반영된다.",
          "PASS(CONFIRMED)도 엔진 자동 반영이 아니다 — 사람 확인 뒤 별도 작업."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
