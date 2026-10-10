"""core-longrun-v1 · synthesis-rnd-v2 공용 계산 (사전 등록 2026-10-10, 결과를 보기 전에 고정).

Ken French 일별 산업 포트폴리오(1926-07~, CRSP 기반 — 상장폐지 종목 포함이라 생존편향 없음)로 현 코어 규칙을 복제한다.
아무 연구도 보지 않은 1927-07-01 ~ 2007-12-31 이 판정 구간이고, 2008~ 는 비교 보고만 한다.

복제 규칙(바꾸지 않는다 — 바꾸려면 새 id):
- 후보 = FF 12 산업(시가총액 가중, 배당 포함 총수익). 49 산업 판은 견고성 보고만(같은 규칙, 상위 4).
- 매달 첫 거래일 d 에, d 전 거래일 종가까지의 252거래일(자료의 행 수) 총수익 모멘텀으로 줄 세워 모멘텀 > 0 인 상위 4개.
  동일가중(슬롯당 1/4, 빈 슬롯은 RF). synthesis-rnd-v2 의 코어는 같은 선정에 ERC(126거래일 공분산 위험 균등 기여) 비중
  × (선정 수 / 4) — core_lab.CoreConfig(weighting="erc") 와 같은 방식.
- 시장 필터: 시장 지수(Mkt-RF + RF 누적)가 d 전 거래일 종가 기준 200거래일 단순이동평균 아래면 비중 × 0.5, 나머지는 RF.
- 체결: d 종가에 체결, 수익은 d 다음 거래일부터(core_lab.portfolio_returns 와 같은 '다음 날 체결' 모델 — 목표 비중을 다음
  리밸런싱까지 일정하게 유지). 비용: 산업 비중 변화(회전율) × 편도 10bp(스트레스 30bp 보고).
- 1926-07 부터 워밍업. 49 산업 자료의 결측(-99.99): 시작 전은 결측 그대로(후보 아님), 시작 뒤 드문 결측일은 수익 0.

주의: 1952년 이전 자료에는 토요일 거래가 있어 252행 ≈ 10개월이다(행 수 기준으로 고정). 일별 연율화는 실제 연간 행 수로 한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Optional

import numpy as np
import pandas as pd

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
WARMUP_START = "1926-07-01"
MAIN_START, MAIN_END = "1927-07-01", "2007-12-31"
COMPARE_START = "2008-01-01"
SUBPERIODS = (("1927-07-01", "1946-12-31"), ("1947-01-01", "1966-12-31"),
              ("1967-01-01", "1986-12-31"), ("1987-01-01", "2007-12-31"))
LOOKBACK = 252
TOP_N = 4
SMA_WINDOW = 200
FILTER_CUT = 0.5
ERC_WINDOW = 126
COST_BPS = 10.0
STRESS_BPS = 30.0
EPISODE_THRESHOLD = 0.20   # 시장 하락 국면: 고점 대비 −20% 이하(하락 국면 종료는 저점 대비 +20% 반등)
NW_LAGS_MONTHLY = 6
H1_BETA_MAX = 0.6
H2_T_MIN = 2.0
H3_MIN_SHARE = 0.70
H4_MIN_POSITIVE = 3

_N = NormalDist()


@dataclass(frozen=True)
class Rule:
    top_n: int = TOP_N
    lookback: int = LOOKBACK
    weighting: str = "equal"   # equal / erc
    sma_window: int = SMA_WINDOW
    filter_cut: float = FILTER_CUT
    erc_window: int = ERC_WINDOW


# =================================================================================================
# 자료
# =================================================================================================

def clean_industry(rets: pd.DataFrame) -> pd.DataFrame:
    """시작 전 결측은 그대로(후보 아님), 시작 뒤 드문 결측일은 수익 0."""
    started = rets.notna().cummax()
    return rets.where(~(started & rets.isna()), 0.0)


def load_real() -> dict[str, Any]:
    """Ken French 일별 FF3·12 산업·49 산업. 12 산업이나 FF3 를 못 받으면 예외(실행기가 실패로 세고 다시 시도)."""
    from core import french_factors as ff

    ff3, i12, i49 = ff.load("ff3_daily"), ff.load("ind12_daily"), ff.load("ind49_daily")
    if ff3 is None or i12 is None:
        raise RuntimeError("Ken French 일별 FF3/12 산업 자료를 받지 못함")
    idx = ff3.index.intersection(i12.index).sort_values()
    out = {"rf": ff3["RF"].reindex(idx).astype(float), "mkt": (ff3["Mkt-RF"] + ff3["RF"]).reindex(idx).astype(float),
           "ind12": clean_industry(i12.reindex(idx).astype(float)), "ind49": None, "source": "Ken French data library (daily)"}
    if i49 is not None:
        out["ind49"] = clean_industry(i49.reindex(idx).astype(float))
    return out


def synthetic_data(seed: int = 7, n12: int = 12, n49: int = 16, start: str = WARMUP_START, end: str = "2026-08-31") -> dict[str, Any]:
    """스모크용 가짜 자료(네트워크 없음). 시장 폭락 구간을 몇 개 넣어 하락 국면 판정을 끝까지 태운다."""
    idx = pd.bdate_range(start, end)
    n = len(idx)
    rng = np.random.default_rng(seed)
    drift = np.full(n, 0.0004)
    for a, b, d in (("1929-09-01", "1932-06-30", -0.0025), ("1937-03-01", "1938-03-31", -0.003),
                    ("1973-01-01", "1974-10-31", -0.002), ("1987-10-01", "1987-10-30", -0.012),
                    ("2000-09-01", "2002-10-31", -0.0015), ("2008-09-01", "2009-03-09", -0.005),
                    ("2020-02-20", "2020-03-23", -0.012)):
        drift[(idx >= a) & (idx <= b)] = d
    rf = pd.Series(0.00012, index=idx)
    mkt_ex = drift + rng.normal(0, 0.009, n)

    def inds(k: int, s: int, late: bool) -> pd.DataFrame:
        r = np.random.default_rng(s)
        betas = np.linspace(0.5, 1.4, k)
        # 2년마다 바뀌는 산업별 추세 → 모멘텀이 잡을 거리가 있게
        blocks = np.arange(n) // 500
        trend = r.normal(0, 0.0004, (blocks.max() + 1, k))[blocks]
        ret = 0.00012 + mkt_ex[:, None] * betas + trend + r.normal(0, 0.007, (n, k))
        df = pd.DataFrame(ret, index=idx, columns=[f"I{j:02d}" for j in range(k)])
        if late:  # 늦게 생기는 산업 + 드문 결측일
            df.iloc[: n // 3, 0] = np.nan
            df.iloc[: n // 2, 1] = np.nan
            df.iloc[n // 2 + 10, 2] = np.nan
        return df

    return {"rf": rf, "mkt": pd.Series(mkt_ex, index=idx) + rf, "ind12": inds(n12, seed + 1, False),
            "ind49": clean_industry(inds(n49, seed + 2, True)), "source": "synthetic (smoke)"}


# =================================================================================================
# 규칙
# =================================================================================================

def month_first_mask(index: pd.DatetimeIndex) -> np.ndarray:
    per = index.to_period("M")
    m = np.ones(len(index), dtype=bool)
    m[1:] = per[1:] != per[:-1]
    return m


def erc_weights(window: pd.DataFrame, iters: int = 200) -> dict[str, float]:
    """위험 균등 기여 — core_lab._erc 와 같은 고정점 반복(일별 수익 창을 받는다). 합 = 1. 자료 부족이면 {}."""
    rets = window.dropna()
    if len(rets) < 60 or rets.shape[1] < 2:
        return {}
    cov = rets.cov().to_numpy() * 252
    n = cov.shape[0]
    w = np.full(n, 1.0 / n)
    for _ in range(iters):
        rc = w * (cov @ w)
        w = w * ((rc.sum() / n) / np.maximum(rc, 1e-12)) ** 0.5
        w = w / w.sum()
    return {t: float(x) for t, x in zip(rets.columns, w)}


def target_weights(rets: pd.DataFrame, mkt: pd.Series, rule: Rule = Rule()) -> pd.DataFrame:
    """월 첫 거래일 d 의 목표 비중(산업만, 나머지는 RF). d 전 거래일 종가까지의 자료만 쓴다. 다음 리밸런싱까지 유지."""
    idx = rets.index
    logr = np.log1p(rets)
    mom = np.expm1(logr.rolling(rule.lookback, min_periods=rule.lookback).sum()).to_numpy()
    level = (1 + mkt.reindex(idx).fillna(0.0)).cumprod()
    sma = level.rolling(rule.sma_window, min_periods=rule.sma_window).mean().to_numpy()
    level = level.to_numpy()
    cols = list(rets.columns)
    firsts = month_first_mask(idx)
    out = np.zeros((len(idx), len(cols)))
    last = np.zeros(len(cols))
    for i in range(1, len(idx)):
        if firsts[i]:
            sd = i - 1
            m = mom[sd]
            eligible = [j for j in range(len(cols)) if np.isfinite(m[j]) and m[j] > 0]
            picks = sorted(eligible, key=lambda j: (-m[j], cols[j]))[: rule.top_n]
            row = np.zeros(len(cols))
            for j in picks:
                row[j] = 1.0 / rule.top_n
            if rule.weighting == "erc" and len(picks) >= 2:
                lo = max(0, sd - rule.erc_window + 1)
                er = erc_weights(rets.iloc[lo: sd + 1, picks])
                if er:
                    scale = len(picks) / rule.top_n
                    row = np.zeros(len(cols))
                    for j in picks:
                        row[j] = er[cols[j]] * scale
            if np.isfinite(sma[sd]) and level[sd] < sma[sd]:
                row = row * rule.filter_cut
            last = row
        out[i] = last
    return pd.DataFrame(out, index=idx, columns=cols)


def strategy_returns(rets: pd.DataFrame, rf: pd.Series, weights: pd.DataFrame, bps: float = COST_BPS) -> pd.Series:
    """다음 날 체결(비중.shift(1)), 남는 몫은 RF, 비용 = 산업 비중 변화 합 × 편도 bp."""
    ex = weights.shift(1).fillna(0.0)
    rf = rf.reindex(rets.index).fillna(0.0)
    gross = (ex * rets.fillna(0.0)).sum(axis=1) + (1 - ex.sum(axis=1)) * rf
    turnover = ex.diff().abs().sum(axis=1)
    turnover.iloc[0] = ex.iloc[0].abs().sum()
    return gross - turnover * (bps / 10000.0)


def blend_returns(r_a: pd.Series, r_b: pd.Series, w_a: float, bps: float = COST_BPS) -> pd.Series:
    """두 소매(a, b)를 w_a : 1−w_a 로 시작해 매년 첫 거래일 종가에 다시 맞춘다(그 사이는 그대로 흘러감). 재조정 비용 = 회전율 × bp."""
    idx = r_a.index
    a, b = r_a.to_numpy(), r_b.reindex(idx).fillna(0.0).to_numpy()
    years = idx.year
    va, vb = w_a, 1.0 - w_a
    out = np.zeros(len(idx))
    for i in range(len(idx)):
        prev = va + vb
        va *= 1 + a[i]
        vb *= 1 + b[i]
        tot = va + vb
        if i > 0 and years[i] != years[i - 1]:
            turnover = (abs(va - w_a * tot) + abs(vb - (1 - w_a) * tot)) / tot
            tot *= 1 - turnover * bps / 10000.0
            va, vb = w_a * tot, (1 - w_a) * tot
        out[i] = tot / prev - 1
    return pd.Series(out, index=idx)


# =================================================================================================
# 통계
# =================================================================================================

def window(s: pd.Series, start: str, end: Optional[str] = None) -> pd.Series:
    return s.loc[pd.Timestamp(start): (pd.Timestamp(end) if end else None)]


def equity(r: pd.Series) -> pd.Series:
    return (1 + r).cumprod()


def mdd(r: pd.Series) -> float:
    eq = equity(r)
    return float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0


def years_of(r: pd.Series) -> float:
    return max((r.index[-1] - r.index[0]).days / 365.25, 1e-9) if len(r) > 1 else 0.0


def cagr(r: pd.Series) -> float:
    y = years_of(r)
    return float(equity(r).iloc[-1] ** (1 / y) - 1) if y > 0 else 0.0


def monthly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def sharpe_monthly(r: pd.Series, rf: pd.Series) -> float:
    ex = monthly(r) - monthly(rf.reindex(r.index).fillna(0.0))
    sd = float(ex.std(ddof=1))
    return float(ex.mean()) / sd * math.sqrt(12) if len(ex) > 2 and sd > 0 else float("nan")


def sharpe_daily(r: pd.Series, rf: pd.Series) -> float:
    ex = r - rf.reindex(r.index).fillna(0.0)
    sd = float(ex.std(ddof=1))
    per_year = len(ex) / years_of(r) if years_of(r) > 0 else 252
    return float(ex.mean()) / sd * math.sqrt(per_year) if len(ex) > 2 and sd > 0 else float("nan")


def capm(r: pd.Series, mkt: pd.Series, rf: pd.Series) -> dict[str, float]:
    """월별 초과수익 CAPM(Newey-West 6) + 일별 베타. 알파는 연율(월 × 12)."""
    from core.french_factors import ols_nw

    rf = rf.reindex(r.index).fillna(0.0)
    m = mkt.reindex(r.index).fillna(0.0)
    ys, xs = (monthly(r) - monthly(rf)), (monthly(m) - monthly(rf))
    fit = ols_nw(ys.to_numpy(), xs.to_numpy()[:, None], NW_LAGS_MONTHLY)
    resid = ys.to_numpy() - fit["coef"][0] - fit["coef"][1] * xs.to_numpy()
    rsd = float(np.std(resid, ddof=2)) if len(resid) > 2 else 0.0
    yd, xd = (r - rf).to_numpy(), (m - rf).to_numpy()
    vx = float(np.var(xd, ddof=1)) if len(xd) > 1 else 0.0
    beta_d = float(np.cov(yd, xd, ddof=1)[0, 1] / vx) if vx > 0 else float("nan")
    return {"beta_daily": beta_d, "beta_monthly": float(fit["coef"][1]), "alpha_annual": float(fit["coef"][0]) * 12,
            "alpha_t_nw6": float(fit["t"][0]), "appraisal_ir": float(fit["coef"][0]) / rsd * math.sqrt(12) if rsd > 0 else float("nan"),
            "months": int(fit["n"])}


def market_episodes(level: pd.Series, threshold: float = EPISODE_THRESHOLD) -> list[dict[str, Any]]:
    """시장 지수만으로 정한 하락 국면. 강세 상태에서 고점(직전 저점 이후 최고)보다 threshold 넘게 떨어지면 하락 국면,
    하락 국면 저점보다 threshold 넘게 오르면 국면 종료(고점→저점 1건 기록). 구간 끝까지 끝나지 않으면 '진행 중'으로 기록."""
    v, dates = level.to_numpy(), level.index
    out: list[dict[str, Any]] = []
    if len(v) == 0:
        return out
    bear = False
    pk, pk_i, tr, tr_i = v[0], 0, v[0], 0
    for i in range(1, len(v)):
        x = v[i]
        if not bear:
            if x > pk:
                pk, pk_i = x, i
            elif x <= pk * (1 - threshold):
                bear, tr, tr_i = True, x, i
        else:
            if x < tr:
                tr, tr_i = x, i
            elif x >= tr * (1 + threshold):
                out.append({"peak": dates[pk_i], "trough": dates[tr_i], "depth": float(tr / pk - 1), "ongoing": False})
                bear, pk, pk_i = False, x, i
    if bear:
        out.append({"peak": dates[pk_i], "trough": dates[tr_i], "depth": float(tr / pk - 1), "ongoing": True})
    return out


def episode_rows(strat_full: pd.Series, mkt_full: pd.Series, episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """국면마다 같은 고점→저점 구간의 전략 최대 낙폭과, 저점 뒤 12개월 전략−시장 수익 차('보험료', 자료 전체 사용)."""
    se, me = equity(strat_full), equity(mkt_full)
    rows = []
    for e in episodes:
        sub = se.loc[e["peak"]: e["trough"]]
        sdd = float((sub / sub.cummax() - 1).min())
        end = pd.Timestamp(e["trough"]) + pd.DateOffset(months=12)
        after_s, after_m = se.loc[e["trough"]: end], me.loc[e["trough"]: end]
        full12 = len(after_s) > 1 and pd.Timestamp(after_s.index[-1]) >= end - pd.DateOffset(days=7)
        prem = (float(after_s.iloc[-1] / after_s.iloc[0] - after_m.iloc[-1] / after_m.iloc[0]) if len(after_s) > 1 else None)
        rows.append({"peak": str(e["peak"].date()), "trough": str(e["trough"].date()), "market_depth": e["depth"],
                     "strategy_dd": sdd, "defended": abs(sdd) < abs(e["depth"]), "ongoing": e["ongoing"],
                     "excess_12m_after_trough": prem, "after_window_complete": bool(full12)})
    return rows


def yearly_table(strat: pd.Series, mkt: pd.Series) -> list[dict[str, Any]]:
    ys = (1 + strat).groupby(strat.index.year).prod() - 1
    ym = (1 + mkt.reindex(strat.index).fillna(0.0)).groupby(strat.index.year).prod() - 1
    return [{"year": int(y), "strategy": float(ys[y]), "market": float(ym[y]), "excess": float(ys[y] - ym[y])} for y in ys.index]


def memmel_test(r1: np.ndarray, r2: np.ndarray) -> dict[str, float]:
    """Jobson–Korkie 검정(Memmel 2003 보정): H0 SR1 ≤ SR2, 한쪽 p. r1·r2 는 같은 날짜의 초과수익."""
    r1, r2 = np.asarray(r1, float), np.asarray(r2, float)
    t = len(r1)
    s1, s2 = r1.std(ddof=1), r2.std(ddof=1)
    sr1, sr2 = r1.mean() / s1, r2.mean() / s2
    rho = float(np.corrcoef(r1, r2)[0, 1])
    var = (2 - 2 * rho + 0.5 * (sr1 ** 2 + sr2 ** 2 - 2 * sr1 * sr2 * rho ** 2)) / t
    if var <= 0:
        z = 0.0
    else:
        z = (sr1 - sr2) / math.sqrt(var)
    return {"sr1": float(sr1), "sr2": float(sr2), "rho": rho, "n": t, "z": float(z), "p_one_sided": float(1 - _N.cdf(z))}


# =================================================================================================
# core-longrun-v1 판정 (사전 등록)
# =================================================================================================

def evaluate_core(strat: pd.Series, mkt: pd.Series, rf: pd.Series, start: str, end: Optional[str],
                  subperiods: Optional[tuple] = SUBPERIODS) -> dict[str, Any]:
    """H1~H4 측정. strat·mkt 는 워밍업 포함 전체 일별 수익(보험료 계산에 구간 뒤 자료도 쓴다)."""
    s, m = window(strat, start, end), window(mkt, start, end)
    cp = capm(s, mkt, rf)
    eps = market_episodes(equity(m))
    rows = episode_rows(strat, mkt, eps)
    share = (sum(r["defended"] for r in rows) / len(rows)) if rows else None
    subs = []
    if subperiods:
        for a, b in subperiods:
            c = capm(window(strat, a, b), mkt, rf)
            subs.append({"start": a, "end": b, "alpha_annual": c["alpha_annual"], "alpha_t_nw6": c["alpha_t_nw6"],
                         "beta_daily": c["beta_daily"]})
    prems = [r["excess_12m_after_trough"] for r in rows if r["excess_12m_after_trough"] is not None]
    checks = {
        "H1_low_beta": cp["beta_daily"] < H1_BETA_MAX,
        "H2_positive_alpha": cp["alpha_annual"] > 0 and cp["alpha_t_nw6"] >= H2_T_MIN,
        "H3_crisis_defense": None if share is None else share >= H3_MIN_SHARE,
        "H4_alpha_stability": (sum(x["alpha_annual"] > 0 for x in subs) >= H4_MIN_POSITIVE) if subs else None,
    }
    return {"window": [start, end], "capm": cp, "episodes": rows, "defended_share": share, "subperiods": subs,
            "insurance_premium_avg": (float(np.mean(prems)) if prems else None), "checks": checks,
            "strategy": {"cagr": cagr(s), "mdd": mdd(s), "sharpe_monthly": sharpe_monthly(s, rf), "sharpe_daily": sharpe_daily(s, rf)},
            "market": {"cagr": cagr(m), "mdd": mdd(m), "sharpe_monthly": sharpe_monthly(m, rf), "sharpe_daily": sharpe_daily(m, rf)}}


def core_verdict(checks: dict[str, Optional[bool]]) -> str:
    """CONFIRMED: H1~H4 모두. PARTIAL: 방어 정체성(H1·H3)은 맞는데 알파(H2 또는 H4)가 확인되지 않음. 그 밖은 NOT_CONFIRMED."""
    h1, h2, h3, h4 = (checks.get(k) is True for k in ("H1_low_beta", "H2_positive_alpha", "H3_crisis_defense", "H4_alpha_stability"))
    if h1 and h2 and h3 and h4:
        return "CORE_IDENTITY_CONFIRMED"
    if h1 and h3:
        return "PARTIAL"
    return "NOT_CONFIRMED"


def label(v: Optional[bool]) -> str:
    return "NOT_EVALUABLE" if v is None else ("PASS" if v else "FAIL")
