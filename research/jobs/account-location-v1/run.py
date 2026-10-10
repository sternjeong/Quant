"""측정 연구 account-location-v1 (사전 등록, 2026-10-10): 계좌 위치(asset location) — 회전율 높은 코어를 국내 절세 계좌
(연금저축·중개형 ISA)에서 KRX 상장 대체 ETF 로 굴리고, SPY 는 해외 계좌에 영구 보유하면 세후 원화 수익이 얼마나 달라지나.

계약·대체 ETF 표·세금 가정·판정 규칙은 같은 폴더 SPEC.md(결과를 보기 전에 고정). 계산 엔진은 location.py.
통계 관문이 없는 측정 연구라 검정력 사전 계산(power_report)은 쓰지 않는다(results.json 의 power 는 null + 이유).
전체 계산은 VM 연구 실행기만 한다. 대화·Codespace 에서는 --smoke(가짜 데이터, 네트워크 없음)만.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import champion_strategy as cs  # noqa: E402
from core import core_lab as cl  # noqa: E402
from core.research_power import noop_guard  # noqa: E402

_spec = importlib.util.spec_from_file_location("account_location_engine", Path(__file__).with_name("location.py"))
loc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = loc
_spec.loader.exec_module(loc)

JUDGE_VERSION = "location-judge/v1"
START = "2010-01-01"
CAPITALS = (30_000_000, 100_000_000)
EDGE = 0.005               # L0 대비 +0.5%p/년
COVERAGE_MIN = 0.60        # 대체 ETF 가 있는 자산의 평균 비중
TE_MISMATCH = 0.08         # 월별 추적오차(연율) 이보다 크면(12개월 이상 관측) 대체 ETF 로 보지 않는다(환헤지·지수 불일치 의심)
SCHEMES = ("L0", "L1", "L2", "L12", "L3")
JUDGED = ("L1", "L2", "L12")
SCHEME_LABEL = {"L0": "해외 계좌만(현재)", "L1": "연금저축", "L2": "중개형 ISA(3년마다 연금 이전)", "L12": "연금저축 + ISA",
                "L3": "국내 일반 계좌(참고)"}
STRATS = {"core": ("현 코어(16자산 모멘텀, 현금 BIL)", 0.0), "blend": ("SPY 50% 영구 + ERC 코어 50%(정반합 S2)", 0.5)}
SPY, BIL = cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF

# 1단계 대체 ETF 표(SPEC.md 와 같음 — 결과를 보기 전에 고정). 보수는 연 %, 확인 안 된 값은 가정(SPEC.md '확인 필요').
# status: proxy(환노출 대체 있음) / hedged_only(환헤지 대체만 — 원화 수익 모형과 맞지 않아 대체 없음 처리) / none
MAPPING = {
    "XLC": {"krx": "463690.KS", "name": "KODEX 미국S&P500커뮤니케이션", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "XLY": {"krx": "453660.KS", "name": "KODEX 미국S&P500경기소비재", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "XLP": {"krx": "453630.KS", "name": "KODEX 미국S&P500필수소비재", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "XLE": {"krx": "218420.KS", "name": "KODEX 미국S&P에너지(합성)", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "XLF": {"krx": "453650.KS", "name": "KODEX 미국S&P500금융", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "XLV": {"krx": "453640.KS", "name": "KODEX 미국S&P500헬스케어", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "XLI": {"krx": "200030.KS", "name": "KODEX 미국S&P산업재(합성)", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "XLB": {"krx": None, "name": "없음", "status": "none", "us_exp": 0.0008, "proxy_exp": None},
    "XLRE": {"krx": "182480.KS", "name": "TIGER 미국MSCI리츠(합성 H)", "status": "hedged_only", "us_exp": 0.0008, "proxy_exp": None},
    "XLK": {"krx": "463680.KS", "name": "KODEX 미국S&P500테크놀로지", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "XLU": {"krx": "463640.KS", "name": "KODEX 미국S&P500유틸리티", "status": "proxy", "us_exp": 0.0008, "proxy_exp": 0.0025},
    "TLT": {"krx": "476760.KS", "name": "ACE 미국30년국채액티브", "status": "proxy", "us_exp": 0.0015, "proxy_exp": 0.0010},
    "IEF": {"krx": "305080.KS", "name": "TIGER 미국채10년선물", "status": "proxy", "us_exp": 0.0015, "proxy_exp": 0.0030},
    "GLD": {"krx": "411060.KS", "name": "ACE KRX금현물", "status": "proxy", "us_exp": 0.0040, "proxy_exp": 0.0050},
    "EFA": {"krx": "195970.KS", "name": "PLUS 선진국MSCI(합성 H)", "status": "hedged_only", "us_exp": 0.0033, "proxy_exp": None},
    "HYG": {"krx": "468380.KS", "name": "KODEX iShares미국하이일드액티브", "status": "proxy", "us_exp": 0.0049, "proxy_exp": 0.0030},
    "DBC": {"krx": None, "name": "없음(현 코어에서 제외된 PTP)", "status": "none", "us_exp": 0.0085, "proxy_exp": None},
    "BIL": {"krx": "329750.KS", "name": "TIGER 미국달러단기채권액티브", "status": "proxy", "us_exp": 0.0014, "proxy_exp": 0.0030},
    "SPY": {"krx": "360750.KS", "name": "TIGER 미국S&P500", "status": "reference", "us_exp": 0.000945, "proxy_exp": 0.0007},
}


def _smoke_data():
    idx = pd.bdate_range("2007-01-01", "2014-12-31")
    rng = np.random.default_rng(42)
    us = list(dict.fromkeys(list(cs.CORE_UNIVERSE) + [SPY, BIL]))
    close, adj = {}, {}
    for t in us:
        r = rng.normal(0.0003, 0.012, len(idx))
        c = 50 * np.exp(np.cumsum(r))
        dy = np.where(np.arange(len(idx)) % 63 == 62, 0.005, 0.0)  # 분기 분배
        close[t] = c
        adj[t] = c * np.cumprod(1 + dy)
    close, adj = pd.DataFrame(close, index=idx), pd.DataFrame(adj, index=idx)
    close[BIL] = adj[BIL] = 90 + np.arange(len(idx)) * 0.002
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.005, len(idx)))), index=idx)
    ref_us = loc.reference_krw_index(close, adj, pd.Series(1.0, index=idx))
    krx = {}
    kidx = idx[idx >= "2011-01-01"]
    for t, m in MAPPING.items():
        if not m["krx"] or t not in ref_us:
            continue
        base = (ref_us[t] * fx).reindex(kidx).shift(1).dropna()
        noise = np.exp(np.cumsum(rng.normal(-0.003 / 252, 0.002, len(base))))
        s = base * noise
        if t == "XLE":  # 환헤지된 것처럼 — 1단계 재분류(TE_MISMATCH) 경로 확인
            s = s / fx.reindex(s.index) * 1100
        krx[m["krx"]] = s
    return close, adj, fx, krx


def _real_data():
    from core import tax_fx as tx
    from core.market_data import get_multiple_price_history

    us = list(dict.fromkeys(list(cs.CORE_UNIVERSE) + [SPY, BIL]))
    h = get_multiple_price_history(us, start="2007-01-01", end=None, interval="1d")
    close = pd.DataFrame({t: h[t]["Close"] for t in us if t in h and not h[t].empty}).sort_index()
    adj = pd.DataFrame({t: h[t]["Adj Close"] for t in us if t in h and not h[t].empty}).sort_index()
    days = close[SPY].dropna().index
    close, adj = close.reindex(days), adj.reindex(days)
    krx_t = [m["krx"] for m in MAPPING.values() if m["krx"]]
    hk = get_multiple_price_history(krx_t, start="2010-01-01", end=None, interval="1d")
    krx = {}
    for t in krx_t:
        df = hk.get(t)
        if df is not None and not df.empty:
            col = "Adj Close" if "Adj Close" in df else "Close"
            krx[t] = df[col].dropna()
    return close, adj, tx.usdkrw_series(), krx


def stage1(close, adj, fx, krx):
    """대체 ETF 추적오차·차감·재분류. 반환 (표, 대체 가능 집합, 종목별 연 차감)."""
    ref_us = loc.reference_krw_index(close, adj, pd.Series(1.0, index=close.index))
    rows, proxied, ded = {}, set(), {}
    for t, m in MAPPING.items():
        row = {"name": m["name"], "krx": m["krx"], "status_registered": m["status"], "us_exp": m["us_exp"], "proxy_exp": m["proxy_exp"]}
        st = {"n_days": 0}
        if m["krx"] and t in ref_us and m["krx"] in krx:
            st = loc.tracking_stats(krx[m["krx"]], ref_us[t], fx)
        row["tracking"] = st
        status = m["status"]
        if status == "proxy" and (st.get("te_monthly_ann") or 0) > TE_MISMATCH and st.get("n_months", 0) >= 12:
            status = "mismatch_no_proxy"
        row["status_used"] = status
        if status == "proxy":
            dd = loc.decide_deduction(m["us_exp"], m["proxy_exp"], st)
            row["deduction"] = dd
            ded[t] = dd["deduction"]
            proxied.add(t)
        rows[t] = row
    return rows, proxied, ded


def run_all(close, adj, fx, krx, smoke: bool) -> dict:
    rows, proxied, ded = stage1(close, adj, fx, krx)
    universe = [t for t in cs.CORE_UNIVERSE if t in close.columns]
    proxied &= set(universe) | {BIL}
    reserve_share = sum(1 for t in universe if t not in proxied) / len(universe)
    extra, extra_adj = close[[SPY, BIL]], adj[[SPY, BIL]]
    v0 = cl.build_weights(close[universe], extra, cl.CoreConfig(cash="bil"))
    erc = cl.build_weights(adj[universe], extra_adj, cl.CoreConfig(cash="bil", weighting="erc"))
    start = "2008-06-01" if smoke else START
    days = v0.index[v0.index >= pd.Timestamp(start)]
    weights = {"core": v0.reindex(days).fillna(0.0), "blend": erc.reindex(days).fillna(0.0)}
    ref_krw = loc.reference_krw_index(close.reindex(days), adj.reindex(days), fx)
    proxy_px = loc.proxy_krw_index(ref_krw[[t for t in sorted(proxied) if t in ref_krw]], ded)
    mid = days[0] + (days[-1] - days[0]) / 2
    periods = {"full": days, "H1": days[days < mid], "H2": days[days >= mid]}
    cov = {k: loc.coverage(w, proxied) for k, w in weights.items()}

    sims, series = {}, {}
    for sk, (_, spy_sleeve) in STRATS.items():
        for cap in CAPITALS:
            for pk, pdays in periods.items():
                w = weights[sk].reindex(pdays)
                for sc in SCHEMES:
                    r = loc.simulate(w, close, adj, fx, proxy_px, sc, cap, proxied=proxied, reserve_share=reserve_share,
                                     spy_sleeve=spy_sleeve, spy=SPY)
                    key = f"{sk}|{cap}|{pk}|{sc}"
                    if pk == "full" and cap == CAPITALS[0]:
                        series[(sk, sc)] = r["values_krw"]
                    sims[key] = {k: v for k, v in r.items() if k not in ("values_krw", "contributions")}  # 결과 파일 256KB 제한

    # 엔진 대조(참고): 해외 계좌만(L0, 현 코어, 3,000만 원, 전체) vs core/tax_fx.simulate
    from core import tax_fx as tx

    t0 = tx.simulate(weights["core"], close, adj, fx, tx.AccountConfig(initial_krw=CAPITALS[0]))
    yrs = (days[-1] - days[0]).days / 365.25
    engine_check = {"tax_fx_cagr_after_liquidation": (t0["final_after_liquidation_krw"] / CAPITALS[0]) ** (1 / yrs) - 1,
                    "location_L0_cagr_after": sims[f"core|{CAPITALS[0]}|full|L0"]["cagr_after"]["low"],
                    "note": "location 엔진은 청산 매도 수수료·환전 스프레드·미납 지난해 세금까지 빼므로 조금 낮을 수 있다"}

    verdicts, details = {}, {}
    for sk in STRATS:
        for sc in JUDGED:
            vk = f"{sk}.{sc}"
            act = (series[(sk, sc)].pct_change() - series[(sk, "L0")].pct_change()).fillna(0.0)
            guard = noop_guard(act.to_numpy())
            checks, diffs = {}, {}
            for cap in CAPITALS:
                for pk in ("full", "H1", "H2"):
                    for tau in ("low", "high", "lump"):
                        a = sims[f"{sk}|{cap}|{pk}|{sc}"]["cagr_after"][tau]
                        b = sims[f"{sk}|{cap}|{pk}|L0"]["cagr_after"][tau]
                        diffs[f"{cap // 1_000_000}m_{pk}_{tau}"] = a - b
                        if pk in ("H1", "H2") and tau in ("low", "high"):
                            checks[f"{cap // 1_000_000}m_{pk}_{tau}_ge_0.5pp"] = bool(a - b >= EDGE)
            if cov[sk] < COVERAGE_MIN:
                verdict = "NOT_EVALUABLE_COVERAGE"
            elif guard:
                verdict = "NOT_EVALUABLE"
            else:
                verdict = "RECOMMEND_REVIEW" if all(checks.values()) else "NO_CHANGE"
            verdicts[vk] = verdict
            details[vk] = {"checks": checks, "diff_vs_L0": diffs, "noop_guard": guard, "coverage": cov[sk]}
    reference = {f"{sk}.L3": {f"{cap // 1_000_000}m_{pk}": sims[f"{sk}|{cap}|{pk}|L3"]["cagr_after"]["low"]
                              - sims[f"{sk}|{cap}|{pk}|L0"]["cagr_after"]["low"] for cap in CAPITALS for pk in ("full", "H1", "H2")}
                 for sk in STRATS}
    return {"stage1": rows, "proxied": sorted(proxied), "reserve_share": reserve_share, "coverage": cov,
            "periods": {k: [str(v[0].date()), str(v[-1].date())] for k, v in periods.items()},
            "sims": sims, "verdicts": verdicts, "details": details, "reference_L3_diff_low": reference,
            "engine_check": engine_check}


def _pct(v):
    return "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v * 100:.2f}%"


def report(res: dict, smoke: bool) -> str:
    L = [f"# 계좌 위치(asset location) 측정 v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "세금 자문이 아니다. 세법 가정은 SPEC.md(‘확인 필요’ 표시 포함). 과거를 2026년 세법으로 다시 계산한 가상 비교이며, "
         "대체 ETF 대부분은 2010년에 없었다(미국 ETF 수익 × 환율 − 차감으로 근사).", "",
         "검정력: 통계 관문이 없는 측정 연구라 power_report 를 쓰지 않는다(판정은 세후 원화 연수익 차이 ≥ 0.5%p 의 기계 계산).", "",
         f"기간 {res['periods']['full'][0]} ~ {res['periods']['full'][1]} · 절반 {res['periods']['H1'][0]}~{res['periods']['H1'][1]} / "
         f"{res['periods']['H2'][0]}~{res['periods']['H2'][1]}", "",
         "## 1단계 — 대체 ETF 추적", "",
         "| 미국 | KRX 대체 | 상태 | 겹친 기간 | 월 추적오차 | 측정 연 차이 | 적용 연 차감 |", "|---|---|---|---|---|---|---|"]
    for t, r in res["stage1"].items():
        st, dd = r["tracking"], r.get("deduction") or {}
        span = f"{st.get('start', '—')}~{st.get('end', '')} ({st.get('n_days', 0)}일)" if st.get("n_days") else "—"
        L.append(f"| {t} | {r['name']} {r['krx'] or ''} | {r['status_used']} | {span} | {_pct(st.get('te_monthly_ann'))} | "
                 f"{_pct(st.get('measured_drag'))} | {_pct(dd.get('deduction'))} {('(' + dd['source'] + ')') if dd else ''} |")
    L += ["", f"대체 가능(국내 계좌에 담는 것): {', '.join(res['proxied'])}. 해외 계좌 유보 몫 {res['reserve_share']:.1%}. "
          f"평균 비중 기준 대체 비율: " + ", ".join(f"{STRATS[k][0]} {v:.0%}" for k, v in res["coverage"].items()), "",
          "## 2단계 — 세후·청산 후 원화 연수익 (연금 인출세 낮음 3.3% / 높음 5.5% / 일시금 16.5%)", ""]
    for sk, (label, _) in STRATS.items():
        L += [f"### {label}", "", "| 방식 | 3천만 전체(낮/높/일시금) | 3천만 앞 절반 | 3천만 뒤 절반 | 1억 전체 | 1억 앞 절반 | 1억 뒤 절반 |",
              "|---|---|---|---|---|---|---|"]
        for sc in SCHEMES:
            cells = []
            for cap in CAPITALS:
                for pk in ("full", "H1", "H2"):
                    c = res["sims"][f"{sk}|{cap}|{pk}|{sc}"]["cagr_after"]
                    cells.append(f"{_pct(c['low'])} / {_pct(c['high'])} / {_pct(c['lump'])}" if pk == "full" or sc != "L0"
                                 else f"{_pct(c['low'])}")
            L.append(f"| {SCHEME_LABEL[sc]} | " + " | ".join(cells) + " |")
        L.append("")
    L += ["## 판정 (location-judge/v1)", "", "| 방식 | 판정 | 통과한 조건 |", "|---|---|---|"]
    for k, v in res["verdicts"].items():
        ch = res["details"][k]["checks"]
        L.append(f"| {k} | {v} | {sum(ch.values())}/{len(ch)} |")
    ec = res["engine_check"]
    L += ["", "규칙: 3천만·1억 × 앞·뒤 절반 × 연금 인출세 낮음·높음 8개 모두에서 L0 보다 세후 연수익 +0.5%p 이상이면 RECOMMEND_REVIEW, "
          "아니면 NO_CHANGE. 대체 비율 60% 미만이면 NOT_EVALUABLE_COVERAGE, 기준선과 매일 같으면 NOT_EVALUABLE. "
          "일시금 16.5%·L3(국내 일반 계좌)는 참고(판정 밖). RECOMMEND_REVIEW 도 사람 검토 대기이며 엔진·계좌에 자동 반영하지 않는다.", "",
          f"엔진 대조(L0 현 코어 3천만 전체): core/tax_fx {_pct(ec['tax_fx_cagr_after_liquidation'])} vs 이 엔진 {_pct(ec['location_L0_cagr_after'])}.", "",
          "주의: 연금은 55세 이후·연금 수령 한도 안에서 받아야 낮은 세율(연 1,500만 원 넘으면 종합과세 또는 16.5% 선택), 중도 인출은 16.5%. "
          "ISA 는 3년 의무 보유. 국내 섹터 ETF 는 거래대금이 작아 호가 차이가 가정(편도 0.05%)보다 클 수 있다. "
          "세액공제(연금 13.2~16.5%, ISA 만기 이전 10%)는 넣지 않았다(혜택 누락 — 보수적). 금융소득 종합과세(2,000만 원)는 L3 에서 미반영."]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    close, adj, fx, krx = _smoke_data() if a.smoke else _real_data()
    res = run_all(close, adj, fx, krx, a.smoke)
    result = {"judge_version": JUDGE_VERSION, "kind": "measurement (통계 관문 없음)", "smoke": a.smoke,
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "power": None, "power_note": "통계 관문이 없는 측정 연구 — power_report 미사용(docs/RESEARCH_JOBS.md 판정 설계 규칙 1 해당 없음)",
              "verdicts": res["verdicts"], **{k: v for k, v in res.items() if k != "verdicts"}}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
