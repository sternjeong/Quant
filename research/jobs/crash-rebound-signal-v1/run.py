"""crash-rebound-signal-v1 — 급락 상태에서 바로 살까, 반등 신호를 기다렸다 살까. 규칙·판정은 SPEC.md (결과 보기 전 고정).

python research/jobs/crash-rebound-signal-v1/run.py --out OUT --checkpoint CK [--smoke]
계산은 수십 초라 체크포인트를 쓰지 않는다(계약상 인자만 받는다).
신호 계산 함수(state_frame·latest_state)는 scripts/crash_rebound_scan.py 가 그대로 가져다 쓴다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RULES_VERSION = "crash-rebound/v1"
JUDGE_VERSION = "rebound-judge/v1"

# --- 사전 등록 상수 (바꾸지 않는다) ------------------------------------------------------------------
ERAS = {"A": ("1927-07-01", "1966-12-31"), "B": ("1967-01-01", "2007-12-31")}
REPORT_ERA = ("2008-01-01", None)
HIGH_WIN = 252
MKT_CRASH, MKT_END = -0.15, -0.05
STK_CRASH, STK_END = -0.30, -0.10
DEEPER_STEP = 0.10
RSI_N, RSI_LO = 14, 30.0
MA_N = 20
VOL_N, VOL_FADE = 21, 0.75
FTD_MIN_DAYS, FTD_RET = 4, 0.015
NEWS_LAG, NEWS_FADE = 1, 0.80
PRIMARY_H = 250
HORIZONS = (60, 120, 250)
FWD = (20, 60, 120, 250)
SIGNALS = ("RSI_LT30", "RSI_X30", "MA20_RECLAIM", "DEEPER", "VOL_FADE", "FTD", "NEWS_FADE")
K = len(SIGNALS)
ALPHA = 0.05 / K
MIN_EP_ERA = 5
MIN_STOCKS = 8
BIGTECH = ("AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "NFLX", "ADBE", "ORCL", "INTC", "CSCO", "IBM", "QCOM")
NEWS_CSV = PROJECT_ROOT / "research" / "jobs" / "news-core-combo-v1" / "data" / "news_indices_monthly.csv"
LABELS = {
    "RSI_LT30": "RSI(14) 30 미만(과매도)",
    "RSI_X30": "RSI 가 30 위로 회복",
    "MA20_RECLAIM": "종가가 20일선을 위로 돌파",
    "DEEPER": "고점 대비 하락이 시작 기준보다 10%p 더 깊어짐",
    "VOL_FADE": "21일 변동성이 사건 최고치 대비 25% 이상 진정",
    "FTD": "추세 확인일(최저일 4일 뒤 이후 +1.5% 이상 상승일)",
    "NEWS_FADE": "뉴스 불확실성(EPU)이 사건 최고치 대비 20% 이상 진정",
}
ERA_NAMES = {"A": "시대 A 1927~1966 (판정)", "B": "시대 B 1967~2007 (판정)", "C": "시대 C 2008~ (보고만)"}


# ---------------------------------------------------------------- 지표·신호 (순수 함수, 과거 정보만)
def rsi_wilder(close: pd.Series, n: int = RSI_N) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rsi = 100 - 100 / (1 + up / dn)
    return rsi.where(dn > 0, 100.0).where(up.notna())


def load_news(path: Path = NEWS_CSV) -> Optional[pd.Series]:
    """월별 뉴스 기반 EPU(PeriodIndex). 파일이 없으면 None."""
    try:
        df = pd.read_csv(path)
    except OSError:
        return None
    s = pd.Series(df["epu_news"].astype(float).to_numpy(), index=pd.PeriodIndex(df["month"], freq="M"))
    return s.sort_index()


def news_daily(epu_m: Optional[pd.Series], index: pd.DatetimeIndex, lag: int = NEWS_LAG) -> pd.Series:
    """날짜 d(달 m) → EPU(m − lag). 공표 전 값은 쓰지 않는다."""
    if epu_m is None or len(epu_m) == 0:
        return pd.Series(np.nan, index=index)
    months = pd.DatetimeIndex(index).to_period("M") - lag
    return pd.Series(epu_m.reindex(months).to_numpy(dtype=float), index=index)


def state_frame(close: pd.Series, crash_th: float = MKT_CRASH, end_th: float = MKT_END,
                epu_m: Optional[pd.Series] = None) -> pd.DataFrame:
    """날짜별 급락 상태·사건 번호·지표·신호(bool). 모든 값은 그날 종가까지의 정보로만 정해진다."""
    c = close.astype(float).dropna()
    c = c[c > 0]
    ret = c.pct_change()
    high = c.rolling(HIGH_WIN, min_periods=HIGH_WIN).max()
    dd = c / high - 1
    rsi = rsi_wilder(c)
    ma = c.rolling(MA_N, min_periods=MA_N).mean()
    vol = ret.rolling(VOL_N, min_periods=VOL_N).std() * math.sqrt(252)
    news = news_daily(epu_m, c.index)
    C, R, DD, RS, MA, V, NW = (x.to_numpy(dtype=float) for x in (c, ret, dd, rsi, ma, vol, news))
    n = len(c)
    ep = np.full(n, -1, dtype=int)
    sig = {s: np.zeros(n, dtype=bool) for s in SIGNALS}
    days_low = np.full(n, -1, dtype=int)
    vol_peak = np.full(n, np.nan)
    news_peak = np.full(n, np.nan)
    in_ep, k = False, -1
    peak_v = peak_n = low = np.nan
    low_i = 0
    for i in range(n):
        if in_ep and DD[i] > end_th:
            in_ep = False
        if not in_ep and DD[i] <= crash_th:
            in_ep, k = True, k + 1
            peak_v, peak_n, low, low_i = np.nan, np.nan, C[i], i
        if not in_ep:
            continue
        ep[i] = k
        if np.isfinite(V[i]):
            peak_v = V[i] if not np.isfinite(peak_v) else max(peak_v, V[i])
        if np.isfinite(NW[i]):
            peak_n = NW[i] if not np.isfinite(peak_n) else max(peak_n, NW[i])
        if C[i] < low:
            low, low_i = C[i], i
        vol_peak[i], news_peak[i], days_low[i] = peak_v, peak_n, i - low_i
        prev = i - 1
        sig["RSI_LT30"][i] = RS[i] < RSI_LO
        sig["RSI_X30"][i] = prev >= 0 and RS[prev] < RSI_LO <= RS[i]
        sig["MA20_RECLAIM"][i] = prev >= 0 and C[prev] <= MA[prev] and C[i] > MA[i]
        sig["DEEPER"][i] = DD[i] <= crash_th - DEEPER_STEP
        sig["VOL_FADE"][i] = np.isfinite(peak_v) and V[i] <= VOL_FADE * peak_v
        sig["FTD"][i] = (i - low_i) >= FTD_MIN_DAYS and R[i] >= FTD_RET
        sig["NEWS_FADE"][i] = np.isfinite(peak_n) and NW[i] <= NEWS_FADE * peak_n
    out = pd.DataFrame({"close": C, "ret": R, "dd": DD, "rsi": RS, "ma20": MA, "vol21": V, "epu": NW,
                        "episode": ep, "vol_peak": vol_peak, "news_peak": news_peak, "days_since_low": days_low},
                       index=c.index)
    for s in SIGNALS:
        out[s] = sig[s]
    out.attrs.update(crash_th=crash_th, end_th=end_th)
    return out


def episodes(frame: pd.DataFrame) -> list[tuple[int, int, bool]]:
    """(시작 위치, 마지막 위치(포함), 아직 진행 중?) 목록."""
    e = frame["episode"].to_numpy()
    out = []
    for k in np.unique(e[e >= 0]):
        pos = np.flatnonzero(e == k)
        out.append((int(pos[0]), int(pos[-1]), bool(pos[-1] == len(e) - 1)))
    return out


# ---------------------------------------------------------------- 사건 단위 측정
def _cash(rf: np.ndarray, a: int, b: int) -> float:
    """a 일 종가 → b 일 종가 사이 현금 누적(b ≥ a)."""
    return float(np.prod(1 + rf[a + 1:b + 1])) if b > a else 1.0


def episode_outcome(frame: pd.DataFrame, rf: np.ndarray, ep: tuple[int, int, bool], h: int) -> Optional[dict]:
    """신호별 '기다리기 vs 바로 사기' 쌍 차이. T 가 자료 밖이면 None."""
    start, end, _ = ep
    c = frame["close"].to_numpy(dtype=float)
    entry, T = start + 1, start + 1 + h
    if T >= len(c):
        return None
    now_w = c[T] / c[entry]
    pain_now = float(np.min(c[entry:T + 1]) / c[entry] - 1)
    last = min(end, start + h - 1)
    res = {"start": str(frame.index[start].date()), "now": float(now_w), "pain_now": pain_now, "signals": {}}
    for s in SIGNALS:
        hits = np.flatnonzero(frame[s].to_numpy()[start:last + 1])
        if len(hits):
            ts = start + int(hits[0])
            buy = ts + 1
            wait_w = _cash(rf, entry, buy) * c[T] / c[buy]
            pain_w = float(np.min(c[buy:T + 1]) / c[buy] - 1)
            delay = int(ts - start)
        else:
            wait_w, pain_w, delay = _cash(rf, entry, T), 0.0, None
        res["signals"][s] = {"D": float(math.log(wait_w) - math.log(now_w)), "pain_diff": pain_w - pain_now,
                             "fired": delay is not None, "delay": delay}
    return res


def forward_stats(frame: pd.DataFrame, ep: tuple[int, int, bool]) -> dict:
    """서술용: 진입일·신호 첫날·사건 안 아무 날의 앞 수익, 사후 바닥 대비 신호 시점."""
    start, end, _ = ep
    c = frame["close"].to_numpy(dtype=float)
    n = len(c)

    def fwd(t: int, h: int) -> Optional[float]:
        b = t + 1
        return float(c[b + h] / c[b] - 1) if b + h < n else None

    trough = start + int(np.argmin(c[start:end + 1]))
    out: dict[str, Any] = {"entry": {h: fwd(start, h) for h in FWD}, "any": {}, "signal": {}, "trough_lag": {}}
    for h in FWD:
        vals = [v for v in (fwd(t, h) for t in range(start, end + 1)) if v is not None]
        out["any"][h] = float(np.mean(vals)) if vals else None
    for s in SIGNALS:
        hits = np.flatnonzero(frame[s].to_numpy()[start:end + 1])
        if len(hits):
            ts = start + int(hits[0])
            out["signal"][s] = {h: fwd(ts, h) for h in FWD}
            out["trough_lag"][s] = int(ts - trough)
        else:
            out["signal"][s] = None
            out["trough_lag"][s] = None
    return out


# ---------------------------------------------------------------- 통계
def t_sf(t: float, df: int) -> float:
    """스튜던트 t 분포 위꼬리 확률 P(T > t) — scipy 없이(VM venv) 밀도를 심프슨 적분한다."""
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    f = lambda u: c * (1 + u * u / df) ** (-(df + 1) / 2)  # noqa: E731
    a, b = 0.0, abs(t)
    n = 2000
    h = (b - a) / n
    area = (f(a) + f(b) + sum((4 if k % 2 else 2) * f(a + k * h) for k in range(1, n))) * h / 3
    upper = 0.5 - area
    return float(min(1.0, max(0.0, upper if t >= 0 else 1 - upper)))


def t_crit(alpha: float, df: int) -> float:
    """P(T > x) = alpha 인 x (이분법)."""
    lo, hi = 0.0, 200.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if t_sf(mid, df) > alpha else (lo, mid)
    return (lo + hi) / 2


def paired_stats(x: list[float]) -> dict:
    a = np.asarray([v for v in x if v is not None and math.isfinite(v)], dtype=float)
    n = len(a)
    out = {"n": n, "mean": float(a.mean()) if n else None, "median": float(np.median(a)) if n else None,
           "win": float((a > 0).mean()) if n else None, "sd": None, "t": None, "p": None, "effect": None,
           "needed_effect": None}
    if n >= 2:
        out["needed_effect"] = t_crit(ALPHA, n - 1) / math.sqrt(n)
    if n >= 3:
        sd = float(a.std(ddof=1))
        out["sd"] = sd
        if sd > 0:
            t = float(a.mean() / (sd / math.sqrt(n)))
            out.update(t=t, p=t_sf(t, n - 1), effect=float(a.mean() / sd))
    return out


def clustered_stats(by_stock: dict[str, list[float]]) -> dict:
    """종목 군집: 종목별 평균을 한 표본으로 본다."""
    means = [float(np.mean(v)) for v in by_stock.values() if v]
    out = paired_stats(means)
    out["n_stocks"] = len(means)
    out["n_episodes"] = int(sum(len(v) for v in by_stock.values()))
    return out


def _median(x: list[float]) -> Optional[float]:
    return float(np.median(x)) if x else None


# ---------------------------------------------------------------- 평가
def era_of(date: str) -> str:
    if date < ERAS["A"][0]:
        return "pre"
    if date <= ERAS["A"][1]:
        return "A"
    if date <= ERAS["B"][1]:
        return "B"
    return "C"


def market_block(frame: pd.DataFrame, rf: np.ndarray) -> dict:
    eps = episodes(frame)
    out: dict[str, Any] = {"episodes": [], "by_era": {}}
    outcomes = {h: [] for h in HORIZONS}
    fwds = []
    for ep in eps:
        st = str(frame.index[ep[0]].date())
        era = era_of(st)
        if era == "pre":
            continue
        trough = ep[0] + int(np.argmin(frame["close"].to_numpy()[ep[0]:ep[1] + 1]))
        out["episodes"].append({"start": st, "end": str(frame.index[ep[1]].date()), "open": ep[2], "era": era,
                                "trough": str(frame.index[trough].date()),
                                "max_dd": float(frame["dd"].iloc[ep[0]:ep[1] + 1].min())})
        for h in HORIZONS:
            o = episode_outcome(frame, rf, ep, h)
            if o is not None:
                outcomes[h].append((era, o))
        fwds.append((era, forward_stats(frame, ep)))
    for era in ("A", "B", "C"):
        blk: dict[str, Any] = {"n_episodes": sum(1 for e in out["episodes"] if e["era"] == era), "horizons": {}, "forward": {}}
        for h in HORIZONS:
            rows = [o for e, o in outcomes[h] if e == era]
            blk["horizons"][str(h)] = {
                "n": len(rows),
                "buy_now_mean": float(np.mean([math.log(o["now"]) for o in rows])) if rows else None,
                "pain_now_median": _median([o["pain_now"] for o in rows]),
                "signals": {s: {**paired_stats([o["signals"][s]["D"] for o in rows]),
                                "pain_diff_median": _median([o["signals"][s]["pain_diff"] for o in rows]),
                                "fired_share": float(np.mean([o["signals"][s]["fired"] for o in rows])) if rows else None,
                                "delay_median": _median([o["signals"][s]["delay"] for o in rows if o["signals"][s]["delay"] is not None])}
                            for s in SIGNALS}}
        blk["forward"] = _forward_summary([f for e, f in fwds if e == era])
        out["by_era"][era] = blk
    return out


def _forward_summary(fs: list[dict]) -> dict:
    def mean(vals):
        v = [x for x in vals if x is not None]
        return float(np.mean(v)) if v else None

    out = {"entry": {str(h): mean([f["entry"][h] for f in fs]) for h in FWD},
           "any_crash_day": {str(h): mean([f["any"][h] for f in fs]) for h in FWD}, "signals": {}}
    for s in SIGNALS:
        got = [f["signal"][s] for f in fs if f["signal"][s] is not None]
        lags = [f["trough_lag"][s] for f in fs if f["trough_lag"][s] is not None]
        out["signals"][s] = {"n": len(got), **{str(h): mean([g[h] for g in got]) for h in FWD},
                             "trough_lag_median": _median(lags),
                             "after_trough_share": float(np.mean([x >= 0 for x in lags])) if lags else None}
    return out


def bigtech_block(frames: dict[str, pd.DataFrame], rf_by: dict[str, np.ndarray]) -> dict:
    out: dict[str, Any] = {"per_stock": {}, "horizons": {}}
    for h in HORIZONS:
        by = {s: {} for s in SIGNALS}
        pains = {s: [] for s in SIGNALS}
        fired = {s: [] for s in SIGNALS}
        nows = []
        for tk, fr in frames.items():
            for ep in episodes(fr):
                o = episode_outcome(fr, rf_by[tk], ep, h)
                if o is None:
                    continue
                nows.append(math.log(o["now"]))
                for s in SIGNALS:
                    by[s].setdefault(tk, []).append(o["signals"][s]["D"])
                    pains[s].append(o["signals"][s]["pain_diff"])
                    fired[s].append(o["signals"][s]["fired"])
        out["horizons"][str(h)] = {"n": len(nows), "buy_now_mean": float(np.mean(nows)) if nows else None,
                                   "signals": {s: {**clustered_stats(by[s]), "pain_diff_median": _median(pains[s]),
                                                   "fired_share": float(np.mean(fired[s])) if fired[s] else None}
                                               for s in SIGNALS}}
    for tk, fr in frames.items():
        eps = episodes(fr)
        out["per_stock"][tk] = {"first": str(fr.index[0].date()), "n_episodes": len(eps),
                                "starts": [str(fr.index[e[0]].date()) for e in eps]}
    return out


def judge(mkt: dict, bt: dict) -> dict:
    h = str(PRIMARY_H)
    verdicts, detail, diag = {}, {}, {}
    for s in SIGNALS:
        gates, means, all_d_zero = {}, [], True
        for era in ERAS:
            st = mkt["by_era"][era]["horizons"][h]["signals"][s]
            means.append(st["mean"])
            all_d_zero &= (st["mean"] in (None, 0.0) and (st["sd"] in (None, 0.0)))
            gates[era] = {"count": st["n"] >= MIN_EP_ERA,
                          "positive": st["mean"] is not None and st["mean"] > 0 and st["p"] is not None and st["p"] < ALPHA,
                          "pain": st["pain_diff_median"] is not None and st["pain_diff_median"] >= 0}
        b = bt["horizons"][h]["signals"][s]
        means.append(b["mean"])
        all_d_zero &= (b["mean"] in (None, 0.0) and (b["sd"] in (None, 0.0)))
        gates["bigtech"] = {"count": b["n_stocks"] >= MIN_STOCKS,
                            "positive": b["mean"] is not None and b["mean"] > 0 and b["p"] is not None and b["p"] < ALPHA,
                            "pain": b["pain_diff_median"] is not None and b["pain_diff_median"] >= 0}
        fail_kind = None
        if not all(g["count"] for g in gates.values()) or all_d_zero:
            v = "NOT_EVALUABLE"
        elif all(all(g.values()) for g in gates.values()):
            v = "SIGNAL_HELPS"
        else:
            v = "FAIL"
            fail_kind = "FAIL_UNDERPOWERED" if all(m is not None and m > 0 for m in means) else "FAIL"
        verdicts[s] = v
        detail[s] = {"verdict": v, "fail_kind": fail_kind, "gates": gates, "mean_D": means}
        diag[s] = "DEFAULT_BUY_NOW" if all(m is not None and m < 0 for m in means) else "MIXED_OR_WAIT"
    return {"verdicts": verdicts, "detail": detail, "diagnostics": diag}


# ---------------------------------------------------------------- 현재 상태 (포착기와 공유)
def latest_state(frame: pd.DataFrame) -> dict:
    """마지막 날의 급락 상태와 신호. 사건 중이면 사건 시작 이후 각 신호가 처음 켜진 날도 준다."""
    if frame.empty:
        return {"available": False}
    last = frame.iloc[-1]
    i = len(frame) - 1
    k = int(last["episode"])
    d: dict[str, Any] = {"available": True, "date": str(frame.index[-1].date()), "close": float(last["close"]),
                         "dd": None if not np.isfinite(last["dd"]) else float(last["dd"]),
                         "rsi": None if not np.isfinite(last["rsi"]) else float(last["rsi"]),
                         "above_ma20": bool(last["close"] > last["ma20"]) if np.isfinite(last["ma20"]) else None,
                         "crash_th": frame.attrs.get("crash_th"), "in_crash": k >= 0, "signals_today": {}, "first_fired": {}}
    if k >= 0:
        pos = np.flatnonzero(frame["episode"].to_numpy() == k)
        st = int(pos[0])
        d.update(episode_start=str(frame.index[st].date()), days_in_episode=int(i - st),
                 days_since_low=int(last["days_since_low"]),
                 vol_ratio=None if not (np.isfinite(last["vol21"]) and np.isfinite(last["vol_peak"]) and last["vol_peak"] > 0)
                 else float(last["vol21"] / last["vol_peak"]),
                 news_ratio=None if not (np.isfinite(last["epu"]) and np.isfinite(last["news_peak"]) and last["news_peak"] > 0)
                 else float(last["epu"] / last["news_peak"]))
        for s in SIGNALS:
            d["signals_today"][s] = bool(last[s])
            hits = np.flatnonzero(frame[s].to_numpy()[st:])
            d["first_fired"][s] = str(frame.index[st + int(hits[0])].date()) if len(hits) else None
    return d


# ---------------------------------------------------------------- 자료
def _lab():
    spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research" / "jobs" / "core-longrun-v1" / "lab.py")
    mod = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(spec))
    if not hasattr(mod, "to_weekdays"):
        spec.loader.exec_module(mod)
    return mod


def load_market_real() -> tuple[pd.Series, pd.Series]:
    from core import french_factors as ff

    lab = _lab()
    ff3 = ff.load("ff3_daily")
    if ff3 is None:
        raise RuntimeError("Ken French 일별 FF3 자료를 받지 못함")
    rf = lab.to_weekdays(ff3["RF"].astype(float))
    mkt = lab.to_weekdays((ff3["Mkt-RF"] + ff3["RF"]).astype(float))
    idx = rf.index.intersection(mkt.index)
    return mkt.reindex(idx).dropna(), rf.reindex(idx).fillna(0.0)


def load_market_smoke() -> tuple[pd.Series, pd.Series]:
    lab = _lab()
    d = lab.synthetic_data()
    rf, mkt = lab.to_weekdays(d["rf"]), lab.to_weekdays(d["mkt"])
    idx = rf.index.intersection(mkt.index)
    return mkt.reindex(idx).dropna(), rf.reindex(idx).fillna(0.0)


def price_close(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s.astype(float).dropna()


def fetch_prices(tickers, start: str = "1962-01-01") -> dict[str, pd.Series]:
    from core.market_data import get_price_history

    out = {}
    for tk in tickers:
        s = price_close(get_price_history(tk, start=start, interval="1d"))
        if len(s) > HIGH_WIN + 10:
            out[tk] = s
    return out


def synthetic_prices(tickers=BIGTECH, seed: int = 11, start: str = "1995-01-02", end: str = "2026-11-20") -> dict[str, pd.Series]:
    """스모크·테스트용 가짜 종목 가격(네트워크 없음). 큰 급락·반등을 넣어 사건이 생기게 한다."""
    idx = pd.bdate_range(start, end)
    out = {}
    for j, tk in enumerate(tickers):
        r = np.random.default_rng(seed + j)
        drift = np.full(len(idx), 0.0006)
        for a, b, dr in (("2000-03-01", "2002-09-30", -0.003), ("2008-06-01", "2009-02-28", -0.005),
                         ("2015-08-01", "2016-02-15", -0.004), ("2022-01-01", "2022-10-31", -0.003),
                         ("2026-08-01", "2026-11-20", -0.004)):
            drift[(idx >= a) & (idx <= b)] = dr * (0.6 + 0.1 * (j % 7))
        ret = drift + r.normal(0, 0.022, len(idx))
        s = pd.Series(100 * np.cumprod(1 + ret), index=idx)
        out[tk] = s.iloc[(j % 4) * 400:]  # 상장 시기를 다르게
    return out


def rf_for(index: pd.DatetimeIndex, rf: Optional[pd.Series]) -> np.ndarray:
    if rf is None or rf.empty:
        return np.zeros(len(index))
    return rf.reindex(index.union(rf.index)).ffill().reindex(index).fillna(0.0).to_numpy(dtype=float)


# ---------------------------------------------------------------- 보고
def _pct(x: Optional[float], nd: int = 1) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def _p(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.4f}"


def current_lines(cur: dict) -> list[str]:
    lines = ["| 대상 | 날짜 | 고점 대비 | 급락 상태(기준) | RSI | 20일선 위 | 사건 시작 | 오늘 켜진 신호 | 사건 중 이미 켜졌던 신호(첫날) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, d in cur.items():
        if not d.get("available"):
            lines.append(f"| {name} | 자료 없음 | | | | | | | |")
            continue
        today = ", ".join(s for s, on in d["signals_today"].items() if on) or "—"
        fired = ", ".join(f"{s}({dt})" for s, dt in d["first_fired"].items() if dt) or "—"
        lines.append(f"| {name} | {d['date']} | {_pct(d['dd'])} | {'예' if d['in_crash'] else '아니오'} ({_pct(d['crash_th'], 0)}) | "
                     f"{'—' if d['rsi'] is None else f'{d['rsi']:.0f}'} | {'—' if d['above_ma20'] is None else ('예' if d['above_ma20'] else '아니오')} | "
                     f"{d.get('episode_start', '—')} | {today if d['in_crash'] else '—'} | {fired if d['in_crash'] else '—'} |")
    return lines


def report(res: dict, smoke: bool) -> str:
    j, mkt, bt = res["judge"], res["market"], res["bigtech"]
    h = str(PRIMARY_H)
    L = [f"# 급락장 반등 매수 신호 검증 (crash-rebound-signal-v1{' · 스모크(가짜 자료)' if smoke else ''})", "",
         "질문: 이미 급락 상태에 들어섰을 때, 그날 가진 현금을 **다음 날 바로 사는 것**과 **반등 신호가 켜질 때까지 기다렸다 사는 것** 중 "
         "무엇이 1년(250 거래일) 뒤 더 많이 남았나. 전 기간 시장 대비 우위가 아니라 '지금 같은 상황'에만 쓰는 조건부 질문이다. "
         "규칙·판정은 결과를 보기 전에 고정했다(SPEC.md).", "",
         "**판정:** " + " · ".join(f"{s} **{v}**" for s, v in j["verdicts"].items()), "",
         f"판정 기준({JUDGE_VERSION}): 시장 시대 A(1927~1966)·B(1967~2007) 각각 사건 ≥ {MIN_EP_ERA}, 그리고 빅테크(종목 군집, 종목 ≥ {MIN_STOCKS}) "
         f"세 곳 모두에서 쌍 차이 D = ln(기다리기) − ln(바로 사기) 평균 > 0, 단측 p < {ALPHA:.4f}(0.05/{K}), 고통(추가 최대 하락) 차이 중앙값 ≥ 0. "
         "2008 이후는 보고만. 통과도 엔진 반영이 아니다.", "",
         rp_line(res), ""]
    buy_now = [s for s, d in j["diagnostics"].items() if d == "DEFAULT_BUY_NOW"]
    L += ["## 한 줄 결론(정직한 기본값)", "",
          (f"세 곳 모두 '기다리면 손해'(D 평균 < 0)였던 신호: {', '.join(buy_now)}." if buy_now else "세 곳 모두 일관되게 손해인 신호는 없었다.")
          + " 통과(SIGNAL_HELPS) 신호가 없으면 기본값은 '급락 진입 때 정한 계획대로 산다(신호를 기다리지 않는다)'이다.", ""]
    for era in ("A", "B", "C"):
        blk = mkt["by_era"][era]
        hz = blk["horizons"][h]
        L += [f"## 시장 {ERA_NAMES[era]} — 사건 {blk['n_episodes']}개, 250일 평가 {hz['n']}개", "",
              f"바로 사기의 250일 로그 수익 평균 {_pct(hz['buy_now_mean'])}, 추가 최대 하락 중앙값 {_pct(hz['pain_now_median'])}.", "",
              "| 신호 | D 평균 / 중앙 | 기다림이 이긴 비율 | 단측 p | 효과(평균/sd) / 통과에 필요 | 고통 차이 중앙 | 켜진 비율 | 켜지기까지 중앙(일) | 60일 D 평균 | 120일 D 평균 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for s in SIGNALS:
            st = hz["signals"][s]
            s60, s120 = blk["horizons"]["60"]["signals"][s], blk["horizons"]["120"]["signals"][s]
            eff = "—" if st["effect"] is None else f"{st['effect']:.2f}"
            need = "—" if st["needed_effect"] is None else f"{st['needed_effect']:.2f}"
            L.append(f"| {s} | {_pct(st['mean'])} / {_pct(st['median'])} | {'—' if st['win'] is None else f'{st['win'] * 100:.0f}%'} | "
                     f"{_p(st['p'])} | {eff} / {need} | {_pct(st['pain_diff_median'])} | "
                     f"{'—' if st['fired_share'] is None else f'{st['fired_share'] * 100:.0f}%'} | "
                     f"{'—' if st['delay_median'] is None else f'{st['delay_median']:.0f}'} | {_pct(s60['mean'])} | {_pct(s120['mean'])} |")
        fw = blk["forward"]
        L += ["", "서술(판정 아님): 신호 첫날 다음 날 산 경우 앞 수익 vs 진입일·급락 상태 아무 날. '바닥 대비'는 사후 바닥(사건 안 최저일) 기준 "
              "신호가 켜진 날 차이(음수 = 바닥 전, 사후 정보).", "",
              "| 매수 시점 | 사건 수 | 20일 | 60일 | 120일 | 250일 | 바닥 대비(중앙, 일) | 바닥 뒤 비율 |", "|---|---|---|---|---|---|---|---|",
              f"| 진입일 | {blk['n_episodes']} | " + " | ".join(_pct(fw['entry'][str(x)]) for x in FWD) + " | | |",
              f"| 급락 상태 아무 날 | {blk['n_episodes']} | " + " | ".join(_pct(fw['any_crash_day'][str(x)]) for x in FWD) + " | | |"]
        for s in SIGNALS:
            f = fw["signals"][s]
            L.append(f"| {s} | {f['n']} | " + " | ".join(_pct(f[str(x)]) for x in FWD) +
                     f" | {'—' if f['trough_lag_median'] is None else f'{f['trough_lag_median']:+.0f}'} | "
                     f"{'—' if f['after_trough_share'] is None else f'{f['after_trough_share'] * 100:.0f}%'} |")
        L.append("")
    eps = [e for e in mkt["episodes"]]
    L += ["## 시장 급락 사건 목록", "", "| 시작 | 종료 | 시대 | 사후 바닥 | 최대 하락 |", "|---|---|---|---|---|"]
    L += [f"| {e['start']} | {e['end']}{' (진행 중)' if e['open'] else ''} | {e['era']} | {e['trough']} | {_pct(e['max_dd'])} |" for e in eps]
    hz = bt["horizons"][h]
    L += ["", f"## 빅테크 검증 — 250일 평가 사건 {hz['n']}개 (종목 기준 −30%, 종료 −10%)", "",
          "**생존 편향 주의:** 지금 대형 기술주 이름으로 고른 표본이다. INTC·IBM·CSCO 처럼 오래 회복 못 한 종목을 넣었지만 상장폐지된 옛 기술주는 없다. "
          "FTD 의 +1.5% 는 종목에도 같은 값이라 종목에서는 훨씬 자주 켜진다.", "",
          f"바로 사기의 250일 로그 수익 평균 {_pct(hz['buy_now_mean'])}.", "",
          "| 신호 | 종목 수 / 사건 수 | 종목 평균 D 의 평균 | 단측 p | 효과 / 필요 | 고통 차이 중앙 | 켜진 비율 |", "|---|---|---|---|---|---|---|"]
    for s in SIGNALS:
        st = hz["signals"][s]
        eff = "—" if st["effect"] is None else f"{st['effect']:.2f}"
        need = "—" if st["needed_effect"] is None else f"{st['needed_effect']:.2f}"
        L.append(f"| {s} | {st['n_stocks']} / {st['n_episodes']} | {_pct(st['mean'])} | {_p(st['p'])} | {eff} / {need} | "
                 f"{_pct(st['pain_diff_median'])} | {'—' if st['fired_share'] is None else f'{st['fired_share'] * 100:.0f}%'} |")
    L += ["", "| 종목 | 자료 시작 | 사건 수 | 사건 시작일 |", "|---|---|---|---|"]
    L += [f"| {tk} | {p['first']} | {p['n_episodes']} | {', '.join(p['starts'][:12])} |" for tk, p in bt["per_stock"].items()]
    L += ["", "## 현재 상태 (보고만, 판정과 무관)", "",
          "Ken French 시장 자료는 한두 달 늦게 갱신된다. SPY·빅테크는 yfinance 최신 종가(스모크는 가짜 자료). "
          "같은 계산을 `python scripts/crash_rebound_scan.py` 로 언제든 다시 볼 수 있다.", ""]
    L += current_lines(res["current"])
    L += ["", "## 읽는 법", "",
          "- D 가 양수면 신호를 기다렸다 산 쪽이 1년 뒤 더 많이 남았다는 뜻이다. 신호가 안 켜져 1년 내내 현금이었던 사건도 그대로 센다(기다림의 실제 비용).",
          "- 시장 사건은 시대당 10개 안팎이라 검정력이 낮다. FAIL 은 '효과 없음'의 증명이 아니다(FAIL_UNDERPOWERED 표시 참고).",
          "- 빅테크 사건은 2000~2002·2008·2022 에 몰려 서로 겹친다. 종목 군집으로 일부만 보정된다.",
          "- 세금·거래 비용은 넣지 않았다. 통과해도 엔진·아침 메시지 반영은 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


def rp_line(res: dict) -> str:
    from core import research_power as rp
    return rp.power_line(res["power"]) + " (위 IR 기준은 일별 활성 수익용 근사다. 이 연구의 실제 기준은 표의 '효과/필요' 열 — 사건 단위 t 임계값.)"


# ---------------------------------------------------------------- 실행
def run(smoke: bool) -> dict:
    from core import research_power as rp

    epu = load_news()
    mkt_r, rf = load_market_smoke() if smoke else load_market_real()
    wealth = (1 + mkt_r).cumprod()
    mframe = state_frame(wealth, MKT_CRASH, MKT_END, epu)
    mres = market_block(mframe, rf.reindex(mframe.index).fillna(0.0).to_numpy())
    if smoke:
        prices = synthetic_prices()
        spy = synthetic_prices(("SPY",), seed=99)
    else:
        prices = fetch_prices(BIGTECH)
        spy = fetch_prices(("SPY",), start="1993-01-01")
    frames = {tk: state_frame(s, STK_CRASH, STK_END, epu) for tk, s in prices.items()}
    rf_by = {tk: rf_for(fr.index, rf) for tk, fr in frames.items()}
    bres = bigtech_block(frames, rf_by)
    j = judge(mres, bres)
    years = (pd.Timestamp(ERAS["A"][1]) - pd.Timestamp(ERAS["A"][0])).days / 365.25
    current = {"미국 시장(Ken French)": latest_state(mframe)}
    for tk, s in spy.items():
        current[tk] = latest_state(state_frame(s, MKT_CRASH, MKT_END, epu))
    for tk, fr in frames.items():
        current[tk] = latest_state(fr)
    return {"rules": RULES_VERSION, "judge_version": JUDGE_VERSION, "smoke": smoke, "alpha": ALPHA, "k": K,
            "power": rp.power_report(years, K), "judge": j, "verdicts": j["verdicts"], "market": mres, "bigtech": bres,
            "current": current, "tickers_loaded": sorted(prices)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    Path(a.checkpoint).mkdir(parents=True, exist_ok=True)
    res = run(a.smoke)
    tmp = out / "results.json.tmp"
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(out / "results.json")
    (out / "REPORT.md").write_text(report(res, a.smoke), encoding="utf-8")
    print(json.dumps(res["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
