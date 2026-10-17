"""측정 연구 pension-sector-v1 (사전 등록, 2026-10-17): 섹터 모멘텀(SC2·SC2VT20)을 연금저축 안에서 KRX 대체 ETF 로 굴리면
세후 원화로 SPY(해외 계좌 영구 보유)와 같은 전략의 해외 계좌 판을 이기나.

계약·세금 가정·판정 규칙은 같은 폴더 SPEC.md(결과를 보기 전에 고정). 계좌 엔진·대체 ETF 표·차감 규칙은
account-location-v1 의 location.py / run.py 를 import 해서 쓴다(복사·수정 없음).
통계 관문이 없는 측정 연구라 power_report 는 쓰지 않는다. 전체 계산은 VM 연구 실행기만; 대화에서는 --smoke(가짜 데이터, 네트워크 없음).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import pickle
import signal as _signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core.research_power import noop_guard  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


loc = sys.modules.get("account_location_engine") or _load("account_location_engine", "research/jobs/account-location-v1/location.py")
alrun = sys.modules.get("account_location_run_for_pension") or _load(
    "account_location_run_for_pension", "research/jobs/account-location-v1/run.py")

JOB_ID = "pension-sector-v1"
RULES_VERSION = "pension-sector-v1/2026-10-17"
SECTORS_11 = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
SECTORS_9 = [t for t in SECTORS_11 if t not in ("XLB", "XLRE")]      # KRX 환노출 대체가 있는 9개
SPY, BIL = "SPY", "BIL"
TOP, LOOKBACK, MIN_VALID = 2, 252, 4
VT_TARGET, VT_WINDOW = 0.20, 126
STRATS = {"SC2": False, "SC2VT20": True}
CAPS = (30_000_000, 100_000_000)
TAUS = ("low", "high")                  # 판정에 쓰는 연금 인출세(3.3% / 5.5%); lump 16.5% 는 보고만
EDGE = 0.01                             # SPY·O 대비 +1.0%p/년 (사전 등록)
EDGE_TOL = 1e-9                         # 부동소수 오차(정확히 1.0%p 는 통과)
COVERAGE_MIN = 0.80
SENS_DRAGS = (0.0, 0.01, 0.02, 0.03)
BE_HI, BE_ITERS = 0.08, 9
FIXED_RESID_NOTE = "측정 겹침 1년 미만이면 잔여 추적 차이 0.30%/년 + 보수 차이(account-location-v1 규칙 그대로)"

REAL_PERIODS = {"full": ("2010-01-04", "2024-09-30"), "H1": ("2010-01-04", "2017-05-31"),
                "H2": ("2017-06-01", "2024-09-30"), "post": ("2024-10-01", None)}
SMOKE_PERIODS = {"full": ("2009-06-01", "2013-12-31"), "H1": ("2009-06-01", "2011-09-30"),
                 "H2": ("2011-10-03", "2013-12-31"), "post": ("2014-01-02", None)}
JUDGED_PERIODS = ("full", "H1", "H2")
MAIN_COMBOS = (("9", "L0"), ("9", "L1"), ("9", "L2"), ("11", "L0"))   # (메뉴, 방식) — L0=O 해외, L1=P 연금저축, L2=I 중개형 ISA
COMBO_LABEL = {("9", "L0"): "O 해외 계좌(9 섹터)", ("9", "L1"): "P 연금저축(9 섹터, 모형)", ("9", "L2"): "I 중개형 ISA(9 섹터, 보고만)",
               ("11", "L0"): "O 해외 계좌(원래 11 섹터, 보고만)"}


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 신호·비중 (결정일 d 전 거래일 종가까지의 자료만)
# =================================================================================================

def sector_weights(adj: pd.DataFrame, menu: list, vt: bool) -> pd.DataFrame:
    """날짜 × (메뉴 + BIL) 목표 비중. 매월 첫 거래일 d 에 전 거래일(d-1) 종가까지의 252거래일 총수익 상위 2 균등
    (신호 있는 섹터가 4개 미만이면 전액 BIL — 판정 구간에서는 일어나지 않음). vt 면 노출 = min(0.20/실현변동성, 1),
    변동성 = d 전 거래일까지 126거래일의 '맞추지 않은' 같은 전략 일별 수익 표준편차 × √252(126일 미만이면 노출 1), 남는 몫 BIL.
    달 안에서는 목표를 그대로 둔다(보유분은 가격대로 표류, 엔진이 목표가 바뀐 날만 매매)."""
    cols = [t for t in menu if t in adj.columns]
    A = adj[cols].to_numpy(dtype=float)
    rets = pd.DataFrame(A).pct_change(fill_method=None).fillna(0.0).to_numpy()
    n, m = A.shape
    per = adj.index.to_period("M")
    W = np.zeros((n, m + 1))
    cur = np.zeros(m + 1)
    cur[m] = 1.0
    wu = np.zeros(m)                 # 맞추지 않은 보유 비중(표류)
    hist: list = []
    for i in range(n):
        day_ret = None
        if i > 0 and wu.sum() > 0:
            r = rets[i]
            day_ret = float(wu @ r)
            g = wu * (1 + r)
            wu = g / g.sum() if g.sum() > 0 else wu
        if i > 0 and per[i] != per[i - 1]:
            sig = i - 1                          # 신호·변동성 모두 d-1 종가까지(hist 는 아직 i 일 수익을 담지 않음)
            scores = {}
            if sig >= LOOKBACK:
                for j in range(m):
                    a, b = A[sig - LOOKBACK, j], A[sig, j]
                    if np.isfinite(a) and np.isfinite(b) and a > 0:
                        scores[j] = b / a - 1.0
            wu = np.zeros(m)
            cur = np.zeros(m + 1)
            if len(scores) < MIN_VALID:
                cur[m] = 1.0
            else:
                order = sorted(scores, key=lambda j: (-scores[j], j))[:TOP]
                wu[order] = 1.0 / TOP
                expo = vt_exposure_from(hist) if vt else 1.0
                cur[:m] = wu * expo
                cur[m] = 1.0 - expo
        if day_ret is not None:
            hist.append(day_ret)
        W[i] = cur
    return pd.DataFrame(W, index=adj.index, columns=cols + [BIL])


def vt_exposure_from(daily: list, target: float = VT_TARGET, window: int = VT_WINDOW) -> float:
    """일별 수익 목록 → 변동성 맞춤 노출(126일 미만이면 1)."""
    if len(daily) < window:
        return 1.0
    vol = float(np.std(daily[-window:], ddof=1)) * math.sqrt(252)
    return min(target / vol, 1.0) if vol > 0 else 1.0


# =================================================================================================
# 대체 ETF 수익 구성 (미국 ETF 원화 총수익 − 연 차감)
# =================================================================================================

def build_proxy_px(close: pd.DataFrame, adj: pd.DataFrame, fx: pd.Series, tickers: list,
                   deductions: Optional[dict] = None, uniform: Optional[float] = None) -> pd.DataFrame:
    """대체 ETF 원화 지수 = 미국 ETF 원천징수 후 총수익 × 환율 × (1 − 연 차감)^(t/252). uniform 이 있으면 모든 대체에 같은 차감."""
    ref = loc.reference_krw_index(close[tickers], adj[tickers], fx)
    ded = {t: float(uniform) for t in tickers} if uniform is not None else dict(deductions or {})
    return loc.proxy_krw_index(ref, ded)


# =================================================================================================
# 판정 (순수 함수 — 테스트 대상)
# =================================================================================================

def ge_edge(a: float, b: float, edge: float = EDGE) -> bool:
    return bool(np.isfinite(a) and np.isfinite(b) and (a - b) >= edge - EDGE_TOL)


def decide(cov: float, guard: Optional[str], p: dict, o: dict, spy: dict) -> tuple[str, dict]:
    """p[(cap, period, tau)] / o[(cap, period)] / spy[(cap, period)] = 세후 청산 후 원화 연수익.
    RECOMMEND_REVIEW iff 3천만·1억 × (전체, 앞, 뒤 절반) × 연금세 (낮음, 높음) 에서 P ≥ SPY + 1.0%p 이고 P ≥ O + 1.0%p."""
    checks = {}
    for cap in CAPS:
        for per in JUDGED_PERIODS:
            for tau in TAUS:
                a = p.get((cap, per, tau), float("nan"))
                checks[f"{cap // 1_000_000}m_{per}_{tau}_vs_spy"] = ge_edge(a, spy.get((cap, per), float("nan")))
                checks[f"{cap // 1_000_000}m_{per}_{tau}_vs_O"] = ge_edge(a, o.get((cap, per), float("nan")))
    if cov < COVERAGE_MIN:
        return "NOT_EVALUABLE_COVERAGE", checks
    if guard:
        return "NOT_EVALUABLE", checks
    return ("RECOMMEND_REVIEW" if all(checks.values()) else "NO_CHANGE"), checks


def bisect_break_even(f: Callable[[float], float], lo: float = 0.0, hi: float = BE_HI, iters: int = BE_ITERS) -> dict:
    """f(drag) = P − SPY 연수익 차이(드래그가 클수록 작아진다고 가정). f 가 0 이 되는 연 드래그를 찾는다."""
    if not f(lo) > 0:
        return {"status": "never_beats", "value": None}
    if f(hi) > 0:
        return {"status": "above_range", "value": None, "hi": hi}
    a, b = lo, hi
    for _ in range(iters):
        mid = (a + b) / 2
        if f(mid) > 0:
            a = mid
        else:
            b = mid
    return {"status": "found", "value": (a + b) / 2}


# =================================================================================================
# 시뮬레이션 래퍼
# =================================================================================================

def period_days(index: pd.DatetimeIndex, periods: dict, name: str) -> pd.DatetimeIndex:
    a, b = periods[name]
    d = index[index >= pd.Timestamp(a)]
    return d[d <= pd.Timestamp(b)] if b else d


def trim(r: dict) -> dict:
    t = r["totals"]
    keep = {k: t[k] for k in ("overseas_cg_tax_krw", "overseas_fees_krw", "fx_cost_krw", "domestic_fees_krw", "domestic_tax_krw",
                              "pension_value_krw", "pension_principal_krw", "pension_withdrawal_tax_krw")}
    return {"cagr": r["cagr_after"], "final_krw": r["final_krw"], "years": r["years"], "mdd": r["mdd"],
            "start": r["start"], "end": r["end"], "totals": keep, "n_moves": len(r["migrations"])}


def one_sim(w: pd.DataFrame, close, adj, fx, proxy_px, scheme: str, cap: float, proxied: set, reserve: float) -> dict:
    return loc.simulate(w, close, adj, fx, proxy_px, scheme, cap, proxied=proxied, reserve_share=reserve)


def spy_weights(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({SPY: 1.0}, index=index)


# =================================================================================================
# 자료
# =================================================================================================

def _smoke_data():
    idx = pd.bdate_range("2007-01-01", "2014-12-31")
    rng = np.random.default_rng(7)
    names = SECTORS_11 + [SPY, BIL]
    close, adj = {}, {}
    for k, t in enumerate(names):
        r = rng.normal(0.0003 + 0.00005 * (k % 4), 0.020, len(idx))
        c = 50 * np.exp(np.cumsum(r))
        dy = np.where(np.arange(len(idx)) % 63 == 62, 0.005, 0.0)
        close[t], adj[t] = c, c * np.cumprod(1 + dy)
    close, adj = pd.DataFrame(close, index=idx), pd.DataFrame(adj, index=idx)
    close[BIL] = adj[BIL] = 90 + np.arange(len(idx)) * 0.002
    ref_us = loc.reference_krw_index(close, adj, pd.Series(1.0, index=idx))
    for t in ("XLC", "XLRE"):                # 상장 전 결측 경로
        close.loc[idx < "2009-01-01", t] = np.nan
        adj.loc[idx < "2009-01-01", t] = np.nan
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.005, len(idx)))), index=idx)
    krx = {}
    kidx = idx[idx >= "2011-01-01"]
    for t in SECTORS_9 + [BIL]:
        m = alrun.MAPPING[t]
        if not m["krx"]:
            continue
        base = (ref_us[t] * fx).reindex(kidx).shift(1).dropna()
        krx[m["krx"]] = base * np.exp(np.cumsum(rng.normal(-0.003 / 252, 0.002, len(base))))
    return {"close": close, "adj": adj, "fx": fx, "krx": krx, "source": "synthetic"}


def _real_data():
    from core import tax_fx as tx
    from core.market_data import get_multiple_price_history

    us = SECTORS_11 + [SPY, BIL]
    h = get_multiple_price_history(us, start="2006-01-01", end=None, interval="1d")
    close = pd.DataFrame({t: h[t]["Close"] for t in us if t in h and not h[t].empty}).sort_index()
    adj = pd.DataFrame({t: h[t]["Adj Close"] for t in us if t in h and not h[t].empty}).sort_index()
    days = close[SPY].dropna().index
    close, adj = close.reindex(days), adj.reindex(days)
    krx_t = [alrun.MAPPING[t]["krx"] for t in SECTORS_9 + [BIL] if alrun.MAPPING[t]["krx"]]
    hk = get_multiple_price_history(krx_t, start="2010-01-01", end=None, interval="1d") or {}
    krx = {}
    for t in krx_t:
        df = hk.get(t)
        if df is not None and not df.empty:
            krx[t] = df["Adj Close" if "Adj Close" in df else "Close"].dropna()
    return {"close": close, "adj": adj, "fx": tx.usdkrw_series(), "krx": krx, "source": "yfinance+fred(DEXKOUS)"}


# =================================================================================================
# 체크포인트
# =================================================================================================

def _atomic_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_ckpt(path: Path, fp: dict):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        return obj["payload"] if obj.get("fingerprint") == fp else None
    except Exception:  # noqa: BLE001 — 깨진 체크포인트는 다시 계산
        return None


def _safe(key: str) -> str:
    return key.replace("|", "_").replace(".", "p")


# =================================================================================================
# 본 계산
# =================================================================================================

def compute(stage, smoke: bool) -> dict:
    data = stage("data", lambda: _smoke_data() if smoke else _real_data())
    close, adj, fx, krx = data["close"], data["adj"], data["fx"], data["krx"]
    periods = SMOKE_PERIODS if smoke else REAL_PERIODS
    cols9 = [t for t in SECTORS_9 + [BIL] if t in close.columns]
    rows, proxied_all, ded = alrun.stage1(close[cols9 + [SPY]].ffill(), adj[cols9 + [SPY]].ffill(), fx, krx)
    rows = {t: r for t, r in rows.items() if t in cols9}
    proxied = {t for t in proxied_all if t in cols9}
    reserve = sum(1 for t in SECTORS_9 if t not in proxied) / len(SECTORS_9)
    px_cols = sorted(proxied)
    cfill, afill = close.ffill(), adj.ffill()
    proxy_px = build_proxy_px(cfill, afill, fx, px_cols, deductions=ded)

    W = {(m, s): sector_weights(adj, SECTORS_9 if m == "9" else SECTORS_11, vt) for m in ("9", "11") for s, vt in STRATS.items()}
    sims, sens, keep, cov = {}, {}, {}, {}

    def window_w(strat, menu, per):
        w = W[(menu, strat)]
        return w.loc[period_days(w.index, periods, per)]

    for strat in STRATS:
        cov[strat] = loc.coverage(window_w(strat, "9", "full"), proxied)
        for cap in CAPS:
            for per in periods:
                for menu, scheme in MAIN_COMBOS:
                    key = f"main|{strat}|{menu}|{scheme}|{cap}|{per}"
                    ww = window_w(strat, menu, per)

                    def run(ww=ww, scheme=scheme, cap=cap, menu=menu, per=per):
                        r = one_sim(ww, close, adj, fx, proxy_px, scheme, cap,
                                    proxied if menu == "9" else set(), reserve if menu == "9" else 0.0)
                        return {"r": trim(r), "v": r["values_krw"] if (cap == CAPS[0] and per == "full") else None}
                    got = stage(key, run)
                    sims[key] = got["r"]
                    if got["v"] is not None:
                        keep[key] = got["v"]
                key = f"main|{strat}|spy|L0|{cap}|{per}"
                idx = period_days(adj.index, periods, per)

                def run_spy(idx=idx, cap=cap, per=per):
                    r = one_sim(spy_weights(idx), close, adj, fx, proxy_px, "L0", cap, set(), 0.0)
                    return {"r": trim(r), "v": None}
                sims[key] = stage(key, run_spy)["r"]

    def p_cagr(strat, drag, cap, per):
        key = f"sens|{strat}|{drag:.5f}|{cap}|{per}"
        ww = window_w(strat, "9", per)

        def run():
            ppx = build_proxy_px(cfill, afill, fx, px_cols, uniform=drag)
            return trim(one_sim(ww, close, adj, fx, ppx, "L1", cap, proxied, reserve))["cagr"]
        return stage(key, run)

    for strat in STRATS:
        for d in SENS_DRAGS:
            for cap in CAPS:
                for per in JUDGED_PERIODS:
                    sens[f"{strat}|{d:.2f}|{cap}|{per}"] = p_cagr(strat, d, cap, per)

    be = {}
    for strat in STRATS:
        spy_full = sims[f"main|{strat}|spy|L0|{CAPS[0]}|full"]["cagr"]["low"]
        for tau in TAUS:
            be[f"{strat}|{tau}"] = bisect_break_even(
                lambda d, strat=strat, tau=tau, spy_full=spy_full: p_cagr(strat, d, CAPS[0], "full")[tau] - spy_full)

    verdicts, details = {}, {}
    for strat in STRATS:
        p, o, spy = {}, {}, {}
        for cap in CAPS:
            for per in JUDGED_PERIODS:
                pr = sims[f"main|{strat}|9|L1|{cap}|{per}"]["cagr"]
                for tau in TAUS:
                    p[(cap, per, tau)] = pr[tau]
                o[(cap, per)] = sims[f"main|{strat}|9|L0|{cap}|{per}"]["cagr"]["low"]
                spy[(cap, per)] = sims[f"main|{strat}|spy|L0|{cap}|{per}"]["cagr"]["low"]
        vp, vo = keep[f"main|{strat}|9|L1|{CAPS[0]}|full"], keep[f"main|{strat}|9|L0|{CAPS[0]}|full"]
        guard = noop_guard((vp.pct_change() - vo.pct_change()).fillna(0.0).to_numpy())
        verdict, checks = decide(cov[strat], guard, p, o, spy)
        verdicts[strat] = verdict
        details[strat] = {"checks": checks, "passed": f"{sum(checks.values())}/{len(checks)}", "coverage": cov[strat], "noop_guard": guard}

    from core import tax_fx as tx
    t0 = tx.simulate(window_w("SC2", "9", "full"), cfill, afill, fx, tx.AccountConfig(initial_krw=CAPS[0]))
    yrs = sims[f"main|SC2|9|L0|{CAPS[0]}|full"]["years"]
    engine_check = {"tax_fx_cagr_after_liquidation": (t0["final_after_liquidation_krw"] / CAPS[0]) ** (1 / yrs) - 1,
                    "location_O_cagr_after": sims[f"main|SC2|9|L0|{CAPS[0]}|full"]["cagr"]["low"],
                    "note": "location 엔진은 청산 매도 수수료·환전 스프레드·미납 세금까지 빼므로 조금 낮을 수 있다"}
    turn = {}
    for (m, s), w in W.items():
        ww = w.loc[period_days(w.index, periods, "full")]
        turn[f"{s}|{m}"] = float(ww.diff().abs().sum(axis=1).sum() / 2 / max((len(ww) - 1) / 252, 1e-9))
    span = {k: [str(period_days(adj.index, periods, k)[0].date()), str(period_days(adj.index, periods, k)[-1].date())] for k in periods}
    return {"stage1": rows, "proxied": sorted(proxied), "cash_proxy": BIL in proxied, "reserve_share": reserve, "coverage": cov,
            "periods": span, "sims": sims, "sens": sens, "break_even": be, "verdicts": verdicts, "details": details,
            "engine_check": engine_check, "one_way_turnover_per_year": turn, "data_source": data["source"]}


# =================================================================================================
# 보고
# =================================================================================================

def _pct(v, nd=2):
    return "—" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v * 100:.{nd}f}%"


def _cell(sim, taus=("low", "high", "lump")):
    return " / ".join(_pct(sim["cagr"][t]) for t in taus)


def render(res: dict, smoke: bool) -> str:
    per = res["periods"]
    L = [f"# 연금저축 섹터 v1 ({RULES_VERSION}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "**이것은 세금 자문이 아니라 모형이다.** 연금저축 쪽 수익은 **과거 KRX 가격이 아니라 모형(미국 섹터 ETF 의 원화 총수익 − 연 차감)** 이다 — "
         "대체 ETF 대부분은 2023년 이후에야 상장됐고 이 구간 대부분에는 존재하지 않았다. 세법 가정은 SPEC.md(‘확인 필요’ 표시 포함).", "",
         "검정력: 통계 관문이 없는 측정 연구라 power_report 를 쓰지 않는다. 판정은 세후 원화 연수익 차이의 기계 계산이다.", "",
         f"기간(판정) {per['full'][0]} ~ {per['full'][1]} · 절반 {per['H1'][0]}~{per['H1'][1]} / {per['H2'][0]}~{per['H2'][1]} · "
         f"이후 구간 {per['post'][0]}~{per['post'][1]} 은 보고만 · 자료 {res['data_source']}", "",
         "메뉴: 연금 판 = XLC XLE XLF XLI XLK XLP XLU XLV XLY(9개; XLB·XLRE 제외라 해외 11개 메뉴와 신호가 조금 다르다). "
         "공정 비교를 위해 해외 계좌 판(O)도 같은 9개 메뉴로 돌렸고, 원래 11개 메뉴의 O 는 보고만.", "",
         "## 판정 (사전 등록)", "", "| 전략 | 판정 | 통과한 조건 | 대체 비율 |", "|---|---|---|---|"]
    for s, v in res["verdicts"].items():
        d = res["details"][s]
        L.append(f"| {s} | **{v}** | {d['passed']} | {d['coverage']:.0%} |")
    L += ["", "규칙: 3천만·1억 × (전체·앞 절반·뒤 절반) × 연금 인출세(3.3%·5.5%) 모두에서 P 가 SPY(해외 계좌 영구 보유)보다 세후 연수익 +1.0%p 이상이고 "
          "같은 전략의 O 보다도 +1.0%p 이상이면 RECOMMEND_REVIEW, 아니면 NO_CHANGE. 대체 비율 80% 미만 NOT_EVALUABLE_COVERAGE, 기준선과 매일 같으면 NOT_EVALUABLE. "
          "통계 관문은 없다(측정 연구). RECOMMEND_REVIEW 도 사람 검토 대기이며 엔진·계좌에 자동 반영하지 않는다.", ""]
    for s in STRATS:
        L += [f"## {s} — 세후·청산 후 원화 연수익 (연금 인출세 낮음 3.3% / 높음 5.5% / 일시금 16.5% 스트레스)", "",
              "| 방식 | 3천만 전체 | 3천만 앞 | 3천만 뒤 | 3천만 이후 | 1억 전체 | 1억 앞 | 1억 뒤 | 1억 이후 |", "|---|---|---|---|---|---|---|---|---|"]
        for (m, sc), lab in COMBO_LABEL.items():
            cells = []
            for cap in CAPS:
                for p in ("full", "H1", "H2", "post"):
                    sim = res["sims"][f"main|{s}|{m}|{sc}|{cap}|{p}"]
                    cells.append(_cell(sim) if sc == "L1" else _cell(sim, ("low", "high")) if sc == "L2" else _pct(sim["cagr"]["low"]))
            L.append(f"| {lab} | " + " | ".join(cells) + " |")
        cells = [_pct(res["sims"][f"main|{s}|spy|L0|{cap}|{p}"]["cagr"]["low"]) for cap in CAPS for p in ("full", "H1", "H2", "post")]
        L += ["| SPY 해외 계좌 영구 보유 | " + " | ".join(cells) + " |", ""]
        t = res["sims"][f"main|{s}|9|L1|{CAPS[0]}|full"]["totals"]
        o = res["sims"][f"main|{s}|9|L0|{CAPS[0]}|full"]["totals"]
        L += [f"세금·비용(3천만 전체, 원): O 양도세 {o['overseas_cg_tax_krw']:,.0f} · 수수료 {o['overseas_fees_krw']:,.0f} · 환전 {o['fx_cost_krw']:,.0f} / "
              f"P 해외 잔여분 양도세 {t['overseas_cg_tax_krw']:,.0f} · 국내 수수료 {t['domestic_fees_krw']:,.0f} · "
              f"연금 인출세(낮음) {t['pension_withdrawal_tax_krw']['low']:,.0f}. 편도 회전율(연, 9 섹터) {res['one_way_turnover_per_year'][s + '|9']:.0%}.", ""]
    L += ["## 차감(드래그) 민감도 — P 의 세후 연수익(낮음/높음 인출세), 모든 대체에 같은 연 차감 (보고만)", "",
          "| 전략 | 연 차감 | 3천만 전체 | 3천만 앞 | 3천만 뒤 | 1억 전체 | SPY(3천만 전체) |", "|---|---|---|---|---|---|---|"]
    for s in STRATS:
        spy = res["sims"][f"main|{s}|spy|L0|{CAPS[0]}|full"]["cagr"]["low"]
        for d in SENS_DRAGS:
            cells = []
            for c, p in ((CAPS[0], "full"), (CAPS[0], "H1"), (CAPS[0], "H2"), (CAPS[1], "full")):
                g = res["sens"][f"{s}|{d:.2f}|{c}|{p}"]
                cells.append(f"{_pct(g['low'])} / {_pct(g['high'])}")
            L.append(f"| {s} | {d:.0%} | " + " | ".join(cells) + f" | {_pct(spy)} |")
    L += ["", "손익분기 차감(3천만 전체에서 P 가 SPY 를 겨우 이기는 균일 연 차감; 이분법 9회라 약 ±0.1%p):", ""]
    for k, v in res["break_even"].items():
        txt = {"never_beats": "0% 차감에서도 SPY 를 못 이김", "above_range": f"{v.get('hi', BE_HI):.0%} 차감에서도 이김"}.get(v["status"], _pct(v["value"]))
        L.append(f"- {k.replace('|', ' / 인출세 ')}: {txt}")
    L += ["", "## 대체 ETF 표 (account-location-v1 표·차감 규칙 재사용)", "", "| 미국 | KRX 대체 | 상태 | 겹친 기간 | 월 추적오차 | 측정 연 차이 | 적용 연 차감 |",
          "|---|---|---|---|---|---|---|"]
    for t, r in res["stage1"].items():
        if "tracking" not in r:
            continue
        st, dd = r["tracking"], r.get("deduction") or {}
        span = f"{st.get('start', '—')}~{st.get('end', '')} ({st.get('n_days', 0)}일)" if st.get("n_days") else "—"
        L.append(f"| {t} | {r['name']} {r['krx'] or ''} | {r['status_used']} | {span} | {_pct(st.get('te_monthly_ann'))} | "
                 f"{_pct(st.get('measured_drag'))} | {_pct(dd.get('deduction'))} {('(' + dd['source'] + ')') if dd else ''} |")
    L += ["", f"연금 안에서 대체 가능: {', '.join(res['proxied'])}. 연금 안 현금 대용: "
          + ("TIGER 미국달러단기채권액티브(329750) 대체(같은 차감 규칙)" if res["cash_proxy"] else "대체 없음 → 계좌 안 원화 현금 0%")
          + f". 해외 유보 몫 {res['reserve_share']:.0%}. 차감 규칙: {FIXED_RESID_NOTE}.", "",
          f"엔진 대조(O, SC2, 9 섹터, 3천만 전체): core/tax_fx {_pct(res['engine_check']['tax_fx_cagr_after_liquidation'])} vs 이 엔진 "
          f"{_pct(res['engine_check']['location_O_cagr_after'])}.", "",
          "## 읽을 때 주의 (모형의 한계)", "",
          "- 연금저축 곡선은 **모형**이다: 미국 섹터 ETF USD 수익 × 환율 − 차감. 실제 KRX 가격이 아니다. 차감이 낮게 잡혔다면 연금 판이 유리하게 나온다 — 민감도 표를 보라.",
          "- 연금 납입 한도(연 1,800만 원 합산, 확인 필요)가 있어 3천만 원을 첫 해에 모두 넣을 수 없다. 넘치는 돈은 해외 계좌에 남고 이듬해 1월에 옮긴다(옮길 때 팔면 그 차익에 양도세).",
          "- 연금은 55세 이후 연금 수령 요건을 지켜야 3.3~5.5%. 연 1,500만 원 초과 수령은 종합과세 또는 16.5% 선택, 중도 인출은 16.5%(일시금 스트레스 참고). 원금이 묶이는 기간이 길다.",
          "- 국내 섹터 ETF 는 거래대금이 작아 호가 차이가 가정(편도 0.065%)보다 클 수 있다. 월 1회 2종목 교체의 실제 비용은 더 높을 수 있다.",
          "- 2025년 이후 연금 계좌 안 해외 원천세 처리 변경(공제·환급)은 모형에 넣지 않았다(미국 원천징수 15% 가 매몰되는 보수적 가정). 세액공제도 넣지 않았다(보수적).",
          "- 2026년 세법을 소급 적용한 가상 비교이며, 기존 연구에서 이미 본 구간이다. 이 보고는 계좌·엔진·주문 경로를 바꾸지 않는다."]
    return "\n".join(L) + "\n"


def build_result(res: dict, smoke: bool) -> dict:
    out = {"judge_version": RULES_VERSION, "kind": "measurement (통계 관문 없음)", "smoke": smoke,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "power": None, "power_note": "통계 관문이 없는 측정 연구 — power_report 미사용(판정 설계 규칙 1 해당 없음)",
           "verdicts": res["verdicts"], **{k: v for k, v in res.items() if k != "verdicts"}}
    if len(json.dumps(out, ensure_ascii=False, default=str).encode("utf-8")) > 190_000:   # 200KB 제한
        out["stage1"] = {k: {"status_used": v.get("status_used")} for k, v in out["stage1"].items()}
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-steps-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 단계 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    steps = {"new": 0}

    def stage(name: str, fn):
        path = ck / f"{_safe(name)}.pkl"
        got = _load_ckpt(path, fp)
        if got is None:
            if a.max_steps_per_run and steps["new"] >= a.max_steps_per_run:
                raise _Stop()
            if deadline is not None and time.time() > deadline - 90:
                raise _Stop()
            got = fn()
            _atomic_pickle(path, {"fingerprint": fp, "payload": got})
            steps["new"] += 1
        return got

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        res = compute(stage, a.smoke)
    except _Stop:
        print("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서", flush=True)
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    result = build_result(res, a.smoke)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
