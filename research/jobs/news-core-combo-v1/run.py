"""검증 연구 news-core-combo-v1: 현 코어 규칙(모멘텀 순위 + 200일선)에 신문 기반 뉴스 지수(GPR·EPU)를 결합하는 네 가지 방식을
아무도 보지 않은 1927~2007 자료로 판정. (사전 등록, 2026-11-21 — 규칙은 SPEC.md 와 이 파일에 결과를 보기 전에 고정)

왜: 뉴스 연구가 단일 변수(news-drift-v1, 종목 기사 수 → FAIL)에 머물렀다. 사용자 지시(2026-11-21)로 뉴스를 단독 신호가 아니라
현 코어가 이미 쓰는 팩터에 '결합'했을 때 나아지는지 본다.

후보(가족 4개): N1 추세×뉴스(AND, 조용한 하락은 줄이지 않음) · N2 추세×뉴스(OR, 뉴스 극단+단기 하락이면 미리 줄임)
               · N3 모멘텀×뉴스 민감도(뉴스 위험 높은 달 순위 기울기) · N4 N1+N3.
PASS(모두): (a) 샤프 > B0, Memmel 한쪽 p < 0.05/4 (b) 연수익 B0 −0.3%p 이내 (c) MDD B0 −2%p 이내 (d) 하위 구간 3/4 샤프 우위
           (e) 지연 2개월 판도 샤프 > B0. PASS 는 전진 원장에 올릴 후보라는 뜻까지만이다.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402

_spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research" / "jobs" / "core-longrun-v1" / "lab.py")
lab = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "Rule"):
    _spec.loader.exec_module(lab)

JUDGE_VERSION = "news-combo-judge/v1"
NEWS_CSV = Path(__file__).resolve().parent / "data" / "news_indices_monthly.csv"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
LAG = 1                 # 달 m 리밸런싱에 m−1 달 지수까지
LAG_ROBUST = 2          # 조건 (e)
PCT_WINDOW = 60         # 백분위 창(개월, 자기 포함)
SD_WINDOW = 120         # 충격 표준화 창(개월)
BETA_WINDOW = 120       # 산업 뉴스 민감도 회귀 창(개월)
BETA_MIN = 60
CALM_NR = 0.5           # N1: NR ≤ 이 값이면 '조용함'
SHOCK_NR = 0.9          # N2: NR ≥ 이 값이면 '극단'
SHOCK_RET_ROWS = 21     # N2: 시장 직전 21거래일 수익 < 0
TILT_NR = 0.75          # N3: NR ≥ 이 값인 달에만 순위 기울기
P_MAX = 0.05 / 4
CAGR_TOL = 0.003
MDD_TOL = 0.02
MIN_SUB_WINS = 3


@dataclass(frozen=True)
class Cand:
    name: str
    filter: str = "base"    # base(현 규칙) / confirm(N1) / early(N2)
    tilt: bool = False      # N3 순위 기울기


B0 = Cand("B0")
CANDIDATES = (Cand("N1_confirm", "confirm"), Cand("N2_early", "early"), Cand("N3_tilt", "base", True), Cand("N4_full", "confirm", True))
LABELS = {"B0": "현 코어 복제", "N1_confirm": "N1 추세×뉴스(AND): 조용한 하락은 줄이지 않음",
          "N2_early": "N2 추세×뉴스(OR): 뉴스 극단+단기 하락이면 미리 줄임",
          "N3_tilt": "N3 모멘텀×뉴스 민감도: 뉴스 위험 높은 달 순위 기울기", "N4_full": "N4 N1 필터 + N3 순위"}
SOURCES = {"both": ("gpr", "epu"), "gpr": ("gpr",), "epu": ("epu",)}


def _f(v, pct=True, sign=False, nd=1):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if pct:
        return f"{v * 100:+.{nd}f}%" if sign else f"{v * 100:.{nd}f}%"
    return f"{v:+.2f}" if sign else f"{v:.2f}"


# =================================================================================================
# 뉴스 상태
# =================================================================================================

def load_news(path: Path = NEWS_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.index = pd.PeriodIndex(df.pop("month"), freq="M")
    return df.rename(columns={"gpr_hist": "gpr", "epu_news": "epu"}).astype(float).sort_index()


def pct_trailing(x: pd.Series, window: int = PCT_WINDOW) -> pd.Series:
    """x[k] 가 직전 window 개 값(자기 포함) 중 차지하는 백분위(≤ 비율). 창이 덜 차면 결측."""
    return x.rolling(window, min_periods=window).apply(lambda a: float((a <= a[-1]).mean()), raw=True)


def innovation(x: pd.Series) -> pd.Series:
    d = np.log(x).diff()
    return d / d.rolling(SD_WINDOW, min_periods=SD_WINDOW).std()


def news_state(news: pd.DataFrame, lag: int = LAG, source: str = "both") -> dict[str, pd.Series]:
    """nr: 리밸런싱 달 m → NR(m) (지수 달 m−lag 기준). u: 지수 달 k → 충격 u(k). lag 는 민감도 회귀 창 끝에도 쓴다."""
    cols = SOURCES[source]
    full = pd.period_range(news.index[0], news.index[-1] + lag, freq="M")
    nr_k = pd.concat([pct_trailing(news[c]) for c in cols], axis=1).mean(axis=1, skipna=False)
    u = pd.concat([innovation(news[c]) for c in cols], axis=1).mean(axis=1, skipna=False)
    return {"nr": nr_k.reindex(full).shift(lag), "u": u, "lag": lag}


def monthly_frame(rets: pd.DataFrame) -> pd.DataFrame:
    return (1 + rets).groupby(rets.index.to_period("M")).prod(min_count=1) - 1


def sensitivities(ex_m: pd.DataFrame, u: pd.Series, month: pd.Period, lag: int, cols: list[int]) -> dict[int, float]:
    """달 k ∈ [m−lag−BETA_WINDOW+1, m−lag] 의 산업 초과(− 시장) 월수익을 u(k)에 회귀한 기울기. 자료가 BETA_MIN 개월 미만이면 뺀다."""
    end = month - lag
    ks = pd.period_range(end - BETA_WINDOW + 1, end, freq="M")
    x = u.reindex(ks).to_numpy()
    y = ex_m.reindex(ks).to_numpy()
    out = {}
    for j in cols:
        ok = np.isfinite(x) & np.isfinite(y[:, j])
        if ok.sum() < BETA_MIN:
            continue
        xv, yv = x[ok], y[ok, j]
        vx = float(np.var(xv, ddof=1))
        if vx > 0:
            out[j] = float(np.cov(xv, yv, ddof=1)[0, 1] / vx)
    return out


# =================================================================================================
# 규칙
# =================================================================================================

def news_weights(rets: pd.DataFrame, mkt: pd.Series, cand: Cand, state: Optional[dict], rule=None) -> tuple[pd.DataFrame, dict]:
    """lab.target_weights(동일가중)와 같은 골격에 뉴스 결합만 더한다. B0 는 lab.target_weights 와 매일 같아야 한다.
    달 m 첫 거래일 d 에 d 전 거래일 종가까지의 가격과 NR(m)(지수 달 m−lag)만 쓴다. 뉴스 상태가 결측인 달은 B0 대로."""
    rule = rule or lab.Rule()
    idx = rets.index
    logr = np.log1p(rets)
    mom = np.expm1(logr.rolling(rule.lookback, min_periods=rule.lookback).sum()).to_numpy()
    level_s = (1 + mkt.reindex(idx).fillna(0.0)).cumprod()
    sma = level_s.rolling(rule.sma_window, min_periods=rule.sma_window).mean().to_numpy()
    level = level_s.to_numpy()
    cols = list(rets.columns)
    months = idx.to_period("M")
    firsts = lab.month_first_mask(idx)
    ex_m = monthly_frame(rets).sub(monthly_frame(mkt.reindex(idx).to_frame("m"))["m"], axis=0) if cand.tilt else None
    out = np.zeros((len(idx), len(cols)))
    last = np.zeros(len(cols))
    act = {"months": 0, "news_known": 0, "filter_changed": 0, "tilt_months": 0, "picks_changed": 0}
    for i in range(1, len(idx)):
        if firsts[i]:
            sd = i - 1
            m = mom[sd]
            nr = float(state["nr"].get(months[i], np.nan)) if state is not None else float("nan")
            known = math.isfinite(nr)
            eligible = [j for j in range(len(cols)) if np.isfinite(m[j]) and m[j] > 0]
            plain = sorted(eligible, key=lambda j: (-m[j], cols[j]))[: rule.top_n]
            picks = plain
            if cand.tilt and known and nr >= TILT_NR and len(eligible) > rule.top_n:
                act["tilt_months"] += 1
                b = sensitivities(ex_m, state["u"], months[i], state["lag"], eligible)
                by_m = sorted(eligible, key=lambda j: (-m[j], cols[j]))
                rank_m = {j: r for r, j in enumerate(by_m)}
                by_b = sorted(eligible, key=lambda j: (-b.get(j, -np.inf), rank_m[j]))
                rank_b = {j: r for r, j in enumerate(by_b)}
                picks = sorted(eligible, key=lambda j: ((rank_m[j] + rank_b[j]) / 2, rank_m[j]))[: rule.top_n]
            row = np.zeros(len(cols))
            for j in picks:
                row[j] = 1.0 / rule.top_n
            below = bool(np.isfinite(sma[sd]) and level[sd] < sma[sd])
            cut = below
            if known and cand.filter == "confirm":
                cut = below and nr > CALM_NR
            elif known and cand.filter == "early":
                r21 = level[sd] / level[sd - SHOCK_RET_ROWS] - 1 if sd >= SHOCK_RET_ROWS else 0.0
                cut = below or (nr >= SHOCK_NR and r21 < 0)
            if cut:
                row = row * rule.filter_cut
            act["months"] += 1
            act["news_known"] += int(known)
            act["filter_changed"] += int(cut != below)
            act["picks_changed"] += int(set(picks) != set(plain))
            last = row
        out[i] = last
    return pd.DataFrame(out, index=idx, columns=cols), act


def run_rule(ind: pd.DataFrame, mkt: pd.Series, rf: pd.Series, cand: Cand, state: Optional[dict], bps: float = lab.COST_BPS):
    w, act = news_weights(ind, mkt, cand, state)
    return lab.strategy_returns(ind, rf, w, bps), act, w


# =================================================================================================
# 판정
# =================================================================================================

def monthly_excess(r: pd.Series, rf: pd.Series) -> pd.Series:
    return lab.monthly(r) - lab.monthly(rf.reindex(r.index).fillna(0.0))


def summary(r: pd.Series, rf: pd.Series) -> dict:
    return {"cagr": lab.cagr(r), "mdd": lab.mdd(r), "sharpe_monthly": lab.sharpe_monthly(r, rf), "sharpe_daily": lab.sharpe_daily(r, rf)}


def judge(cand_full: pd.Series, base_full: pd.Series, lag2_full: pd.Series, rf: pd.Series) -> dict:
    """전체 일별 수익(워밍업 포함)을 받아 판정 구간·하위 구간으로 자른다."""
    c, b = lab.window(cand_full, lab.MAIN_START, lab.MAIN_END), lab.window(base_full, lab.MAIN_START, lab.MAIN_END)
    sc, sb = summary(c, rf), summary(b, rf)
    sl2 = summary(lab.window(lag2_full, lab.MAIN_START, lab.MAIN_END), rf)
    mt = lab.memmel_test(monthly_excess(c, rf).to_numpy(), monthly_excess(b, rf).to_numpy())
    subs = []
    for a, e in lab.SUBPERIODS:
        x, y = lab.window(cand_full, a, e), lab.window(base_full, a, e)
        subs.append({"start": a, "end": e, "sharpe_cand": lab.sharpe_monthly(x, rf), "sharpe_base": lab.sharpe_monthly(y, rf),
                     "cagr_cand": lab.cagr(x), "cagr_base": lab.cagr(y)})
    wins = sum(1 for s in subs if math.isfinite(s["sharpe_cand"]) and s["sharpe_cand"] > s["sharpe_base"])
    checks = {
        "a_sharpe_memmel": bool(sc["sharpe_monthly"] > sb["sharpe_monthly"] and mt["p_one_sided"] < P_MAX),
        "b_cagr_not_worse": bool(sc["cagr"] >= sb["cagr"] - CAGR_TOL),
        "c_mdd_not_worse": bool(sc["mdd"] >= sb["mdd"] - MDD_TOL),
        "d_subperiod_sharpe": wins >= MIN_SUB_WINS,
        "e_lag2_sharpe": bool(sl2["sharpe_monthly"] > sb["sharpe_monthly"]),
    }
    return {"cand": sc, "base": sb, "lag2": sl2, "memmel": mt, "subperiods": subs, "subperiod_wins": wins, "checks": checks,
            "noop": rp.noop_guard((c - b).tolist())}


def etf_era(news: pd.DataFrame, smoke: bool) -> dict:
    """보고만: 실제 16자산 ETF(배당 포함 총수익, 현금 BIL, SPY 200일선)에 같은 규칙. 신호도 총수익으로 계산(라이브 엔진은 가격 신호) — 보고용 근사."""
    try:
        from core import champion_strategy as cs

        spy, bil = cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF
        tick = list(dict.fromkeys(list(cs.CORE_UNIVERSE) + [spy, bil]))
        if smoke:
            idx = pd.bdate_range("2005-06-01", "2012-12-31")
            rng = np.random.default_rng(5)
            adj = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(idx)))) for t in tick}, index=idx)
            adj[bil] = 90 + np.arange(len(idx)) * 0.002
        else:
            from core.market_data import get_multiple_price_history

            h = get_multiple_price_history(tick, start="2005-06-01", end=None, interval="1d")
            adj = pd.DataFrame({t: h[t]["Adj Close"] for t in tick if t in h and not h[t].empty}).sort_index()
            adj = adj.reindex(adj[spy].dropna().index)
        core_cols = [t for t in cs.CORE_UNIVERSE if t in adj.columns]
        rets = adj[core_cols].pct_change(fill_method=None)
        mkt = adj[spy].pct_change(fill_method=None).fillna(0.0)
        rf = adj[bil].pct_change(fill_method=None).fillna(0.0)
        bps = cs.CORE_COST_BPS_PER_SIDE
        state = news_state(news, LAG, "both")
        rows = {"SPY 그냥 보유": mkt}
        for c in (B0, *CANDIDATES):
            rows[LABELS[c.name]] = run_rule(rets, mkt, rf, c, None if c is B0 else state, bps)[0]
        keep = lambda s: lab.window(s, lab.COMPARE_START)  # noqa: E731
        return {"start": str(keep(mkt).index[0].date()), "end": str(keep(mkt).index[-1].date()),
                "basis": "세전 달러, 배당 포함, 현금 = BIL, 16자산(DBC 제외)", "rows": {k: summary(keep(v), keep(rf)) for k, v in rows.items()}}
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
    power = rp.power_report(years, len(CANDIDATES))  # 결과를 보기 전에(구간·시도 수만)

    news = load_news()
    news_sha = hashlib.sha256(NEWS_CSV.read_bytes()).hexdigest()
    data = lab.synthetic_data() if a.smoke else lab.load_real()
    rf, mkt, ind = data["rf"], data["mkt"], data["ind12"]
    states = {(s, lag): news_state(news, lag, s) for s in SOURCES for lag in (LAG, LAG_ROBUST)}

    base, _, w0 = run_rule(ind, mkt, rf, B0, None)
    repro = float((w0 - lab.target_weights(ind, mkt, lab.Rule())).abs().to_numpy().max())

    verdicts: dict[str, Any] = {}
    detail, activity, variants = {}, {}, {}
    for c in CANDIDATES:
        r1, act, _ = run_rule(ind, mkt, rf, c, states[("both", LAG)])
        r2, _, _ = run_rule(ind, mkt, rf, c, states[("both", LAG_ROBUST)])
        jd = judge(r1, base, r2, rf)
        effect = jd["memmel"]["z"] / math.sqrt(years)
        jd["effect_ir_equiv"] = effect
        if jd["noop"]:
            verdicts[c.name] = "NOT_EVALUABLE"
        elif all(jd["checks"].values()):
            verdicts[c.name] = "PASS"
        else:
            verdicts[c.name] = "FAIL"
            verdicts[f"{c.name}_fail_class"] = rp.classify_fail(effect, power)
        detail[c.name], activity[c.name] = jd, act
        variants[c.name] = {}
        for s in ("gpr", "epu"):
            rv, actv, _ = run_rule(ind, mkt, rf, c, states[(s, LAG)])
            sv = summary(lab.window(rv, lab.MAIN_START, lab.MAIN_END), rf)
            sv["filter_changed"], sv["picks_changed"] = actv["filter_changed"], actv["picks_changed"]
            variants[c.name][s] = sv
    passed = [c.name for c in CANDIDATES if verdicts[c.name] == "PASS"]
    verdicts["overall"] = "NEWS_COMBO_HELPS" if passed else "NO_NEWS_EDGE"

    ind49 = {}
    if data.get("ind49") is not None:
        i49 = data["ind49"]
        for c in (B0, *CANDIDATES):
            r49 = run_rule(i49, mkt, rf, c, None if c is B0 else states[("both", LAG)])[0]
            ind49[c.name] = summary(lab.window(r49, lab.MAIN_START, lab.MAIN_END), rf)
    compare = {"start": lab.COMPARE_START, "end": str(mkt.index[-1].date()),
               "market": summary(lab.window(mkt, lab.COMPARE_START), rf), "B0": summary(lab.window(base, lab.COMPARE_START), rf)}
    for c in CANDIDATES:
        compare[c.name] = summary(lab.window(run_rule(ind, mkt, rf, c, states[("both", LAG)])[0], lab.COMPARE_START), rf)

    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "source": data["source"],
              "news_source": {"file": str(NEWS_CSV.relative_to(PROJECT_ROOT)), "sha256": news_sha,
                              "first": str(news.index[0]), "last": str(news.index[-1]),
                              "series": "GPRH (Caldara & Iacoviello) + news-based EPU (Baker, Bloom & Davis), monthly"},
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "power": power, "b0_reproduction_max_abs_diff": repro,
              "rule": {"lag": LAG, "lag_robust": LAG_ROBUST, "pct_window": PCT_WINDOW, "sd_window": SD_WINDOW,
                       "beta_window": BETA_WINDOW, "beta_min": BETA_MIN, "calm_nr": CALM_NR, "shock_nr": SHOCK_NR,
                       "shock_ret_rows": SHOCK_RET_ROWS, "tilt_nr": TILT_NR, "p_max": P_MAX, "cagr_tol": CAGR_TOL,
                       "mdd_tol": MDD_TOL, "min_subperiod_wins": MIN_SUB_WINS, "main_window": [lab.MAIN_START, lab.MAIN_END],
                       "subperiods": lab.SUBPERIODS, "core": "FF12 momentum top4 (252 rows, >0), equal weight, market SMA200 ×0.5, RF cash, 10bp"},
              "main": detail, "activity": activity, "single_source": variants, "ind49": ind49,
              "compare_2008": compare, "etf_era": etf_era(news, a.smoke)}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(result, a.smoke), encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


def render(r: dict, smoke: bool) -> str:
    v = r["verdicts"]
    L = [f"# 뉴스 지수 × 현 코어 결합 ({JUDGE_VERSION}){' — 스모크(가짜 산업 자료)' if smoke else ''}", "",
         "현 코어가 이미 쓰는 두 팩터(12개월 모멘텀 순위, 시장 200일선)에 신문 기반 뉴스 지수(지정학 위험 GPR·정책 불확실성 EPU)를 "
         f"결합하는 네 방식을 아무도 보지 않은 **{lab.MAIN_START} ~ {lab.MAIN_END}** Ken French 12 산업 자료로 판정한다.", "",
         f"**종합: {v['overall']}** — PASS 는 '전진 원장에 올릴 후보'까지만 뜻한다. 엔진은 바뀌지 않았다.", "",
         rp.power_line(r["power"]), "",
         "| 후보 | 판정 | 샤프(월별) 후보 / B0 | Memmel p | 연수익 후보 / B0 | MDD 후보 / B0 | 하위 구간 | 지연 2개월 샤프 |",
         "|---|---|---|---|---|---|---|---|"]
    for name, jd in r["main"].items():
        c, b, mt, ck = jd["cand"], jd["base"], jd["memmel"], jd["checks"]
        verdict = v[name] + (f" ({v[name + '_fail_class']})" if f"{name}_fail_class" in v else "")
        L.append(f"| {LABELS[name]} | **{verdict}** | {_f(c['sharpe_monthly'], False)} / {_f(b['sharpe_monthly'], False)} "
                 f"{'✓' if ck['a_sharpe_memmel'] else '✗'} | {mt['p_one_sided']:.3f} | {_f(c['cagr'])} / {_f(b['cagr'])} "
                 f"{'✓' if ck['b_cagr_not_worse'] else '✗'} | {_f(c['mdd'])} / {_f(b['mdd'])} {'✓' if ck['c_mdd_not_worse'] else '✗'} "
                 f"| {jd['subperiod_wins']}/4 {'✓' if ck['d_subperiod_sharpe'] else '✗'} | {_f(jd['lag2']['sharpe_monthly'], False)} "
                 f"{'✓' if ck['e_lag2_sharpe'] else '✗'} |")
    L += ["", f"판정 기준(사전 고정): (a) 샤프 > B0 & Memmel 한쪽 p < {P_MAX:.4f}(0.05/4) (b) 연수익 ≥ B0 − {CAGR_TOL * 100:.1f}%p "
          f"(c) MDD ≥ B0 − {MDD_TOL * 100:.0f}%p (d) 하위 구간 {MIN_SUB_WINS}/4 이상 샤프 우위 (e) 지연 2개월 판 샤프 > B0.",
          f"B0 재현 검사(core-longrun-v1 규칙과 목표 비중 최대 차이): {r['b0_reproduction_max_abs_diff']:.2e}", ""]
    L += ["## 뉴스 규칙이 실제로 바꾼 달", "", "| 후보 | 리밸런싱 달 | 뉴스 상태 있음 | 필터 결정 바뀜 | 기울기 적용 | 종목 바뀜 |", "|---|---|---|---|---|---|"]
    for name, a in r["activity"].items():
        L.append(f"| {LABELS[name]} | {a['months']} | {a['news_known']} | {a['filter_changed']} | {a['tilt_months']} | {a['picks_changed']} |")
    L += ["", "## 하위 구간 샤프(후보 / B0)", "", "| 후보 | " + " | ".join(f"{s0[:4]}~{s1[:4]}" for s0, s1 in lab.SUBPERIODS) + " |",
          "|---|" + "---|" * len(lab.SUBPERIODS)]
    for name, jd in r["main"].items():
        L.append(f"| {LABELS[name]} | " + " | ".join(f"{_f(s['sharpe_cand'], False)} / {_f(s['sharpe_base'], False)}" for s in jd["subperiods"]) + " |")
    b0 = next(iter(r["main"].values()))["base"]
    L += ["", "## 어느 뉴스가 효과를 냈나(보고만 — 판정 구간, 지수 하나씩)", "",
          "| 후보 | 둘 다(판정) 샤프 | GPR 단독 샤프 | EPU 단독 샤프 | GPR 단독 연수익 | EPU 단독 연수익 |", "|---|---|---|---|---|---|"]
    for name, sv in r["single_source"].items():
        L.append(f"| {LABELS[name]} | {_f(r['main'][name]['cand']['sharpe_monthly'], False)} | {_f(sv['gpr']['sharpe_monthly'], False)} | "
                 f"{_f(sv['epu']['sharpe_monthly'], False)} | {_f(sv['gpr']['cagr'])} | {_f(sv['epu']['cagr'])} |")
    L.append(f"| B0 | {_f(b0['sharpe_monthly'], False)} | | | {_f(b0['cagr'])} | |")

    def row(name, s):
        return f"| {name} | {_f(s['cagr'])} | {_f(s['mdd'])} | {_f(s['sharpe_monthly'], False)} |"

    if r["ind49"]:
        L += ["", "## 49 산업(견고성, 보고만 — 판정 구간)", "", "| | 연수익 | MDD | 샤프(월별) |", "|---|---|---|---|"]
        L += [row(LABELS[k], s) for k, s in r["ind49"].items()]
    c = r["compare_2008"]
    L += ["", f"## 2008~{c['end'][:4]} (12 산업, 이미 여러 연구가 본 구간 — 보고만)", "", "| | 연수익 | MDD | 샤프(월별) |", "|---|---|---|---|",
          row("시장", c["market"])] + [row(LABELS[k], c[k]) for k in ("B0", *[x.name for x in CANDIDATES])]
    e = r["etf_era"]
    L += ["", "## ETF 시대(실제 16자산, 보고만)", ""]
    if "skipped" in e:
        L += [f"건너뜀: {e['skipped']}"]
    else:
        L += [f"{e['start']} ~ {e['end']}, {e['basis']}. 2024-10~ 소진 구간 포함, 신호도 총수익 기준(라이브는 가격) — 판정에 쓰지 않음.", "",
              "| | 연수익 | MDD | 샤프(월별) |", "|---|---|---|---|"] + [row(k, s) for k, s in e["rows"].items()]
    L += ["", "판정 규칙은 결과를 보기 전에 SPEC.md·run.py 에 고정했다. 한계: 두 지수는 연구자가 역사를 알고 고른 키워드 지수다(백분위·직전 창으로 "
          "수준 보정의 미래 정보는 막지만 키워드 선택 편향은 못 막는다). 산업 포트폴리오는 실제 16자산과 다르고(메커니즘만 시험) 세전·환율 미반영. "
          "종목 단위 뉴스는 과거 자료가 없어 다루지 않는다. PASS 도 엔진 자동 반영이 아니다.",
          f"뉴스 자료: {r['news_source']['series']} {r['news_source']['first']}~{r['news_source']['last']}, sha256 {r['news_source']['sha256'][:12]}…"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
