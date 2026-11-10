"""검증 연구 engine-candidate-v1 (2026-11-10 사전 등록): 'SPY + 실제 2배 ETF(SSO) 20%' 엔진 후보가 정밀 한국 세금·실제 상품·적립식으로도 SPY 를 이기나.

배경: l15f-robust-v1(1927~2024 합성 2배)에서 비중 20~25% 만 견고, alt-history-v1·intl-check-v1·edge-decay-v1 에서도 레버리지 섞기가 통과.
다만 모두 합성 2배·근사 세금이었고, 필터가 없어도 통과해 '타이밍'이 아니라 '시장 노출 약 1.2배'의 위험 보상으로 보인다.
여기서는 실제 SSO(ProShares Ultra S&P500, 2006-06 상장) 가격·실제 원/달러·core/tax_fx 정밀 세금(카카오 기본값)으로 같은 질문을 확인한다.
후보(모두 적립금은 모자란 종목부터 산다 — underweight_first):
  SSO20H   SPY 80% + SSO 20%, 처음 한 번 맞추고 팔지 않음(적립금으로만 비중 회복)
  SSO20Y   같은 비중, 매년 1월 첫 거래일 전체를 80/20 으로 되돌림(팔 때 세금)
  SSO20F   SPY 80% + (200일선 완충 필터 켜짐이면 SSO, 꺼짐이면 BIL) 20%, 매달 첫 거래일 판단(전일 종가)
기준: SPY 그냥 보유(같은 날 같은 돈).
판정(시나리오 B 1,000만 원 + 매달 15만 원, 10년 구간, 2006-07 부터 매달 시작, 끝 ≤ 2024-09-30), 후보 3개 각각 CONTRIB_BEATS_SPY ⇔
  ① SPY 보다 많이 남은 구간 ≥ 70% ② 청산 세후 IRR 차이 중앙값 ≥ +0.5%p ③ 10분위 ≥ −1.5%p ④ 시간가중 MDD 중앙값이 SPY 보다 10%p 넘게 나쁘지 않음.
  (④는 레버리지 후보라 기존 5%p 대신 10%p — 결과 보기 전에 정함.) 5년 구간·시나리오 A/C 는 같은 규칙으로 보고만.
보고: 실현 베타(일별 수익의 SPY 회귀), 베타 1 단위당 초과 IRR, 낸 양도세, 2008·2020·2022 구간 계좌 낙폭.
엔진은 바뀌지 않는다. 통과해도 '전진 원장 후보'이며 채택은 사용자 확인 뒤 별도 작업이다.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dca-dip-deploy-v1"))
sys.path.insert(0, str(HERE.parents[2]))
import lab as L  # noqa: E402

from core import rolling_eval as re_  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "engine-candidate-v1"
RULES_VERSION = "engine-candidate-v1/2026-11-10"
SPY, SSO, BIL = "SPY", "SSO", "BIL"
TICKERS = [SPY, SSO, BIL]
W_LEV = 0.20
CANDS = ("SSO20H", "SSO20Y", "SSO20F")
LABELS = {"SPY": "SPY 그냥 보유", "SSO20H": "SPY 80 + SSO 20, 팔지 않음", "SSO20Y": "SPY 80 + SSO 20, 매년 되돌림",
          "SSO20F": "SPY 80 + SSO/BIL 20 (200일선 필터)"}
SCENARIOS = {"B": (10_000_000, 150_000), "A": (10_000_000, 0), "C": (3_000_000, 150_000)}
PRIMARY = "B"
HORIZONS = (10, 5)
PRIMARY_H = 10
FIRST_START, JUDGED_END = "2006-07-01", "2024-09-30"
WIN_MIN, MED_MIN, P10_MIN, MDD_TOL = 0.70, 0.005, -0.015, 0.10
PASS, FAIL = "CONTRIB_BEATS_SPY", "FAIL"
CRASH = {"2008 금융위기": ("2007-10-01", "2009-03-31"), "2020 코로나": ("2020-02-01", "2020-04-30"), "2022 긴축": ("2022-01-01", "2022-10-31")}


def load_real() -> dict:
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history(TICKERS, start="2006-01-01", end=None, interval="1d") or {}
    close, adj = {}, {}
    for t in TICKERS:
        df = h.get(t)
        if df is None or df.empty:
            continue
        for store, col in ((close, "Close"), (adj, "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close")):
            s = df[col].dropna()
            s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
            store[t] = s[~s.index.duplicated(keep="last")]
    if SPY not in adj or SSO not in adj:
        raise RuntimeError("SPY/SSO 가격을 받지 못함")
    days = adj[SSO].index
    close, adj = pd.DataFrame(close).reindex(days), pd.DataFrame(adj).reindex(days)
    fx = tx.usdkrw_series()
    return {"close": close[TICKERS], "adj": adj[TICKERS], "fx": fx, "source": "yfinance (Close/Adj Close), USDKRW tax_fx.usdkrw_series"}


def synthetic() -> dict:
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2006-06-21", "2019-12-31")
    r = rng.normal(0.0004, 0.012, len(idx))
    r[(idx >= "2008-09-01") & (idx <= "2009-03-01")] -= 0.004
    spy = 100 * np.cumprod(1 + r)
    sso = 50 * np.cumprod(1 + 2 * r - 0.00006)
    bil = 90 * np.cumprod(np.full(len(idx), 1.00008))
    adj = pd.DataFrame({SPY: spy, SSO: sso, BIL: bil}, index=idx)
    return {"close": adj * 0.99, "adj": adj, "fx": pd.Series(1200.0, index=idx), "source": "synthetic (smoke)"}


def frames(adj: pd.DataFrame) -> dict[str, pd.DataFrame]:
    idx = adj.index
    n = len(idx)
    base = np.tile([1 - W_LEV, W_LEV, 0.0], (n, 1))
    out = {"SSO20H": pd.DataFrame(base, index=idx, columns=TICKERS)}
    yr = idx.year
    jan = np.flatnonzero(np.r_[False, (yr[1:] != yr[:-1])])
    W = base.copy()
    flip = False
    bounds = list(jan) + [n]
    start = 0
    for b in bounds:                       # 1월마다 목표를 1e-8 만큼 바꿔 '목표 변경 = 전체 재조정'을 일으킨다
        if flip:
            W[start:b] *= (1 - 1e-8)
        flip, start = not flip, b
    out["SSO20Y"] = pd.DataFrame(W, index=idx, columns=TICKERS)
    state = L.leg_state(adj[SPY].ffill(), "band200").to_numpy()
    bil_ok = adj[BIL].notna().to_numpy()
    F = np.zeros((n, 3))
    F[:, 0] = 1 - W_LEV
    F[:, 1] = W_LEV * state
    F[:, 2] = W_LEV * (~state) * bil_ok
    out["SSO20F"] = pd.DataFrame(F, index=idx, columns=TICKERS)
    return out


def beta_stats(sim_twr: pd.Series, spy_adj: pd.Series) -> tuple[float, float]:
    a = sim_twr.pct_change().dropna()
    b = spy_adj.reindex(a.index).pct_change().dropna()
    a = a.reindex(b.index)
    if len(a) < 60:
        return float("nan"), float("nan")
    beta = float(np.cov(a, b)[0, 1] / np.var(b, ddof=1))
    return beta, float(np.corrcoef(a, b)[0, 1])


def body(R):
    inp = R.stage("inputs", lambda: synthetic() if R.smoke else load_real())
    adj = inp["adj"].ffill(limit=3)
    close = inp["close"].ffill(limit=3)
    panels = {"close": close.bfill(), "adj": adj.bfill(), "fx": inp["fx"]}
    fr = frames(adj)
    days = adj.index
    first = "2007-01-01" if R.smoke else FIRST_START
    jend = pd.Timestamp("2016-06-30" if R.smoke else JUDGED_END)
    hz_map = {10: 3, 5: 2} if R.smoke else {10: 10, 5: 5}
    cells, bench = {}, {}
    for scen, (init, monthly) in SCENARIOS.items():
        cfg = tx.AccountConfig(initial_krw=float(init), monthly_contribution_krw=float(monthly), contribution_policy="underweight_first")
        bench[scen] = L.load_ckpt(R.ck / f"bench_{scen}.pkl", {**R.fp, "s": scen}) or {}
        for hz in HORIZONS:
            if scen != PRIMARY and hz != PRIMARY_H:
                continue
            wins = re_.rolling_windows(days, hz_map[hz], step="A" if R.smoke else "M", first_start=first)
            for c in CANDS:
                key = f"{scen}|{hz}y|{c}"
                res = re_.evaluate_windows(fr[c], panels, wins, cfg, cache_path=R.ck / f"cell_{key.replace('|', '_')}.pkl",
                                           benchmark_cache=bench[scen], fingerprint={**R.fp, "cell": key},
                                           deadline=None if R.dl is None else (__import__("time").monotonic() + R.dl - __import__("time").time() - R.margin))
                L.atomic_pickle(R.ck / f"bench_{scen}.pkl", {"fingerprint": {**R.fp, "s": scen}, "payload": bench[scen]})
                R.log(f"{key}: {res['done']}/{len(wins)}")
                if not res["complete"]:
                    raise L.Stop()
                rows = res["rows"]
                judged = [r for r in rows if pd.Timestamp(r["end"]) <= jend]
                rep = [r for r in rows if pd.Timestamp(r["end"]) > jend]
                cells[key] = {"judged": re_.summarize(judged, hz_map[hz]) if judged else {"n_windows": 0},
                              "reported": re_.summarize(rep, hz_map[hz]) if rep else {"n_windows": 0},
                              "median_tax_strategy": float(np.median([r["strategy"]["capital_gains_tax_krw"] for r in judged])) if judged else None,
                              "median_tax_spy": float(np.median([r["benchmark"]["capital_gains_tax_krw"] for r in judged])) if judged else None}
    # 전체 기간 한 계좌(시나리오 B): 실현 베타, 낙폭 구간
    def full():
        a, b = days[days >= pd.Timestamp(first)][0], min(days[-1], jend)
        cfg = tx.AccountConfig(initial_krw=float(SCENARIOS[PRIMARY][0]), monthly_contribution_krw=float(SCENARIOS[PRIMARY][1]))
        out = {}
        for c in ("SPY",) + CANDS:
            w = tx.buy_and_hold_weights(days[(days >= a) & (days <= b)], SPY) if c == "SPY" else fr[c].loc[a:b]
            w = w.loc[:, w.abs().sum() > 0]
            s = tx.simulate(w, panels["close"], panels["adj"], panels["fx"], cfg)
            twr = s["twr_index"]
            beta, corr = beta_stats(twr, adj[SPY])
            crash = {}
            for nm, (x, y) in CRASH.items():
                seg = twr.loc[x:y]
                crash[nm] = re_.max_drawdown(seg) if len(seg) > 5 else None
            out[c] = {"irr_after_liquidation": float(s["irr_after_liquidation"]), "beta": beta, "corr": corr,
                      "mdd_tw": re_.max_drawdown(twr), "tax_krw": float(s["totals"]["capital_gains_tax_krw"]),
                      "terminal_krw": float(s["terminal_after_liquidation_krw"]), "crash_dd": crash}
        return out
    fullres = R.stage("full", full)
    verdicts, checks = {}, {}
    for c in CANDS:
        s = cells[f"{PRIMARY}|{PRIMARY_H}y|{c}"]["judged"]
        ok = None
        if s.get("n_windows"):
            gap = s["median_strategy_mdd_tw"] - s["median_benchmark_mdd_tw"]
            checks[c] = {"win_share": s["share_terminal_win"] >= WIN_MIN, "median_irr": s["median_diff_irr"] >= MED_MIN,
                         "p10_irr": s["p10_diff_irr"] >= P10_MIN, "mdd_tw": gap >= -MDD_TOL}
            ok = all(checks[c].values())
        v = PASS if ok else FAIL
        verdicts[c] = f"SMOKE_ONLY({v})" if R.smoke else v
    verdicts["passed"] = f"{sum(PASS in v and 'SMOKE' not in v for k, v in verdicts.items() if k in CANDS)}/{len(CANDS)}"
    spy_b = fullres["SPY"]["beta"]
    for c in CANDS:
        x = fullres[c]
        bx = x["beta"] - (spy_b if L.fin(spy_b) else 1.0)
        x["excess_irr_per_extra_beta"] = ((x["irr_after_liquidation"] - fullres["SPY"]["irr_after_liquidation"]) / bx) if L.fin(bx) and abs(bx) > 1e-3 else None
    result = L.rnd({"judge_version": RULES_VERSION, "smoke": R.smoke, "source": inp.get("source"), "verdicts": verdicts, "checks": checks,
                    "cells": cells, "full_span_B": fullres,
                    "rule": {"w_lev": W_LEV, "scenarios": SCENARIOS, "primary": [PRIMARY, PRIMARY_H], "first_start": FIRST_START,
                             "judged_end": JUDGED_END, "thresholds": {"win": WIN_MIN, "median": MED_MIN, "p10": P10_MIN, "mdd_tol": MDD_TOL},
                             "labels": LABELS}})
    if R.smoke:
        assert all(cells[f"B|10y|{c}"]["judged"].get("n_windows", 0) > 0 for c in CANDS), "빈 칸"
        assert fullres["SSO20H"]["beta"] > fullres["SPY"]["beta"], "레버리지가 베타를 올리지 않음"
    return result, render(result)


def render(r: dict) -> str:
    P, v = L.pct, r["verdicts"]
    out = [f"# 엔진 후보 — SPY + 실제 2배 ETF(SSO) 20% v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "합성 자료에서 유일하게 모든 관문을 통과한 '시장 + 2배 레버리지 일부'를 실제 SSO 가격·실제 환율·정밀 한국 세금(카카오 기본값)·적립식으로 다시 잰다.", "",
           f"**판정 (1,000만 원 + 매달 15만 원, 10년 구간, 대 SPY): 통과 {v['passed']}** — " + " · ".join(f"{LABELS[c]} **{v[c]}**" for c in CANDS), "",
           "통과는 '전진 원장 후보'일 뿐 채택이 아니다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", "",
           f"- 2006-07 부터 매달 시작하는 10년(판정)·5년(보고) 구간, 끝 ≤ {r['rule']['judged_end']}. 적립금은 모자란 종목부터 산다. 끝에 모두 판다고 보고 세금·비용 반영.",
           f"- 통과: ① SPY 보다 많이 남은 구간 ≥ {WIN_MIN:.0%} ② 세후 IRR 차이 중앙값 ≥ +{MED_MIN * 100:.1f}%p ③ 10분위 ≥ {P10_MIN * 100:.1f}%p "
           f"④ 시간가중 최대낙폭 중앙값이 SPY 보다 {MDD_TOL * 100:.0f}%p 넘게 나쁘지 않음(레버리지 후보라 10%p).", "",
           "## 구간별 결과", "",
           "| 칸 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 시간가중 MDD 중앙값 (SPY) | 낸 양도세 중앙값 (SPY) |", "|---|---|---|---|---|---|"]
    for k, c in r["cells"].items():
        s = c["judged"]
        if not s.get("n_windows"):
            continue
        man = (lambda x: "—" if x is None else f"{x / 10000:,.0f}만 원")
        out.append(f"| {k} | {s['n_windows']} | {P(s['share_terminal_win'], nd=0)} | {P(s['median_diff_irr'], True, 2)}p / {P(s['p10_diff_irr'], True, 2)}p | "
                   f"{P(s['median_strategy_mdd_tw'])} ({P(s['median_benchmark_mdd_tw'])}) | {man(c['median_tax_strategy'])} ({man(c['median_tax_spy'])}) |")
    out += ["", "## 한 계좌 전체 기간 (시나리오 B) — 위험 보상인가, 그 이상인가", "",
            "| 전략 | 청산 세후 IRR | 실현 베타 | 추가 베타 1 당 초과 IRR | 시간가중 MDD | 2008 | 2020 | 2022 | 낸 양도세 |", "|---|---|---|---|---|---|---|---|---|"]
    for c, x in r["full_span_B"].items():
        cd = x["crash_dd"]
        out.append(f"| {LABELS[c]} | {P(x['irr_after_liquidation'], nd=2)} | {x['beta']:.2f} | {P(x.get('excess_irr_per_extra_beta'), True, 2)} | {P(x['mdd_tw'])} | "
                   f"{P(cd.get('2008 금융위기'))} | {P(cd.get('2020 코로나'))} | {P(cd.get('2022 긴축'))} | {x['tax_krw'] / 10000:,.0f}만 원 |")
    out += ["", "읽는 법: 추가 베타 1 당 초과 IRR 이 SPY 의 '시장 초과 수익'(대략 연 5~7%)과 비슷하면 단순 위험 보상이고, 크게 높으면 필터·재조정이 더한 가치가 있다는 뜻이다.", "",
            "## 주의", "",
            "- SSO 는 하루 수익의 2배를 목표로 하는 상품이라 장기 수익이 2배가 되지 않는다(변동성 손실). 실제 가격에 보수·차입 비용이 이미 들어 있다.",
            "- 판정 구간은 2006~2024 한 번의 역사(겹치지 않는 10년은 2개 남짓)이고, 이미 여러 연구가 본 기간이다. 1927~ 장기 근거는 합성 2배로 l15f-robust-v1 에서 따로 봤다.",
            "- 레버리지는 폭락 때 계좌 낙폭을 키운다. 위 2008·2020·2022 낙폭을 반드시 함께 볼 것. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
