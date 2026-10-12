"""leader-catch-v1 계산 (사전 등록 2026-10-12, 결과를 보기 전에 고정. 바꾸려면 새 id).

질문: 다음 주도 업종·종목을 '그 시점에 알 수 있던 정보'만으로 미리 알아볼 수 있었나. 승자를 미리 정해 두지 않고,
리더십이 계속 바뀐 장기 자료(Ken French 일별 12·49 산업, 규모×B/M 25개)에서 사전(ex-ante) 신호 8종 + 합성 1종을 비교한다.

규칙은 SPEC.md 에 한국어로 모두 적었다. 이 파일의 상수가 그 규칙의 코드 표현이다.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("core_longrun_lab", ROOT / "research/jobs/core-longrun-v1/lab.py")
core = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(_spec))
if not hasattr(core, "Rule"):
    _spec.loader.exec_module(core)

# --- 고정 상수 (사전 등록) -----------------------------------------------------------------------------
WARMUP_START = core.WARMUP_START
MAIN_START, MAIN_END = "1927-07-01", "2007-12-31"
SEL_START, SEL_END = "1927-07-01", "1966-12-31"      # 선택 반
CONF_START, CONF_END = "1967-01-01", "2007-12-31"    # 확인 반(판정)
POST_START = "2008-01-01"                              # 보고만
SUBPERIODS = (("1927-07-01", "1946-12-31"), ("1947-01-01", "1966-12-31"),
              ("1967-01-01", "1986-12-31"), ("1987-01-01", "2007-12-31"))
DECADES = (1920, 1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000)
ETF_START, ETF_END = "2010-01-01", "2024-09-30"

TOP_K = {"ind12": 3, "ind49": 5, "ports25": 5}
UNIVERSES = ("ind12", "ind49", "ports25")
MIN_VALID_FACTOR = 2          # 신호가 유한한 구성원이 2k 미만이면 그 달은 포지션 없음(RF)
COST_BPS = core.COST_BPS      # 편도 10bp
FILTER_CUT = core.FILTER_CUT  # 200일 시장 필터(보고용): 시장 < SMA200 이면 비중 × 0.5
SMA_WINDOW = 200

# 특징 창(자료의 행 수; 평일 달력으로 정리했으므로 252 ≈ 1년)
W_F1, SKIP_F1 = 231, 21       # 12-1: 252행 전 ~ 21행 전
W_F2 = 126
W_HIGH = 252
W_BREAK = 55
W_VOL = 63
W_REV = 21
W_RS = 252

SIGNALS = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "C")
MOMENTUM_LIKE = ("F1", "F2", "F3", "F4", "F5", "F6", "C")
CONTROLS = ("F7", "F8")
SIGNAL_NAMES = {
    "F1": "12-1개월 모멘텀", "F2": "6개월 모멘텀", "F3": "252일 고점 근접도", "F4": "추세 플래그(>SMA200) 후 F1 순위",
    "F5": "시장 대비 상대강도(12개월)", "F6": "55일 신고가 최근성", "F7": "저변동성(63일, 대조군)",
    "F8": "단기 반전(1개월, 대조군)", "C": "합성(F1·F3·F5 평균 순위)",
}
ETF_SIGNALS = ("F1", "F2", "F3", "F5", "C", "F7", "F8")
ETF_MENU = ["SPY", "IWM", "EFA", "EEM", "IWF", "IWD", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLC", "XLRE"]
ETF_K = 3

HIT_CHANCE = 1.0 / 3.0
HIT_QUANTILE = 2.0 / 3.0
BOOT_BLOCK, BOOT_DRAWS, BOOT_SEED = 12, 1000, 20261012
T_MIN = 2.0
SUB_MIN_POSITIVE = 3
ROBUST_MIN_UNIVERSES = 2
N_TRIALS = len(SIGNALS) * len(UNIVERSES)   # 27
NW_LAGS = 6
CONC_TOP = 3


# =================================================================================================
# 자료
# =================================================================================================

def load_real() -> dict[str, Any]:
    """French 일별 FF3(RF·Mkt-RF)·12 산업·49 산업·25 포트폴리오. 하나라도 못 받으면 예외(실행기가 실패로 세고 다시 시도)."""
    from core import french_factors as ff

    ff3 = ff.load("ff3_daily")
    raw = {"ind12": ff.load("ind12_daily"), "ind49": ff.load("ind49_daily"), "ports25": ff.load("ports25_daily")}
    if ff3 is None or any(v is None for v in raw.values()):
        raise RuntimeError("Ken French 일별 자료(FF3/12/49/25)를 받지 못함")
    return normalize(ff3["RF"], ff3["Mkt-RF"] + ff3["RF"], raw, "Ken French data library (daily, weekday calendar)")


def normalize(rf: pd.Series, mkt: pd.Series, panels: dict[str, pd.DataFrame], source: str) -> dict[str, Any]:
    """공통 날짜 → 평일 달력(주말 수익은 다음 평일에 복리, core-longrun-v1 과 같은 to_weekdays) → 시작 뒤 결측은 수익 0."""
    idx = rf.index
    for p in panels.values():
        idx = idx.intersection(p.index)
    idx = idx.sort_values()
    out: dict[str, Any] = {"rf": core.to_weekdays(rf.reindex(idx).astype(float)),
                           "mkt": core.to_weekdays(mkt.reindex(idx).astype(float)), "source": source}
    for k, p in panels.items():
        out[k] = core.clean_industry(core.to_weekdays(p.reindex(idx).astype(float)))
    return out


def synthetic_data(seed: int = 11) -> dict[str, Any]:
    """스모크용 가짜 자료(네트워크 없음). core-longrun-v1 의 합성 12/49 + 같은 달력의 25개(주기적으로 주도 산업이 바뀜)."""
    base = core.synthetic_data(seed=seed, n12=12, n49=20)
    idx = base["rf"].index
    n = len(idx)
    rng = np.random.default_rng(seed + 5)
    mk = base["mkt"].to_numpy() - base["rf"].to_numpy()
    blocks = np.arange(n) // 250
    trend = rng.normal(0, 0.0006, (blocks.max() + 1, 25))[blocks]
    betas = np.linspace(0.6, 1.4, 25)
    ret = 0.00012 + mk[:, None] * betas + trend + rng.normal(0, 0.007, (n, 25))
    out = dict(base)
    out["ports25"] = pd.DataFrame(ret, index=idx, columns=[f"P{j:02d}" for j in range(25)])
    out["source"] = "synthetic (smoke)"
    return out


def synthetic_etf(seed: int = 3) -> dict[str, Any]:
    idx = pd.bdate_range("2008-01-02", "2025-06-30")
    n = len(idx)
    rng = np.random.default_rng(seed)
    mk = rng.normal(0.0004, 0.011, n)
    blocks = np.arange(n) // 300
    trend = rng.normal(0, 0.0005, (blocks.max() + 1, len(ETF_MENU)))[blocks]
    ret = 0.00005 + mk[:, None] * np.linspace(0.7, 1.3, len(ETF_MENU)) + trend + rng.normal(0, 0.006, (n, len(ETF_MENU)))
    df = pd.DataFrame(ret, index=idx, columns=ETF_MENU)
    df.loc[df.index < "2018-07-01", "XLC"] = np.nan
    df.loc[df.index < "2015-11-01", "XLRE"] = np.nan
    df = core.clean_industry(df)
    return {"rets": df, "mkt": df["SPY"].copy(), "rf": pd.Series(0.00005, index=idx), "source": "synthetic ETF (smoke)"}


def load_etf_real() -> dict[str, Any]:
    """ETF 메뉴 일별 수익(조정 종가) + SPY 시장 + French RF. 가격을 못 받으면 예외."""
    from core import french_factors as ff
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history(ETF_MENU, start="2008-01-01", end=None, interval="1d")
    cols = {}
    for t in ETF_MENU:
        df = (h or {}).get(t)
        if df is None or df.empty:
            continue
        col = "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close"
        s = df[col].dropna()
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
        cols[t] = s[~s.index.duplicated(keep="last")]
    if "SPY" not in cols:
        raise RuntimeError("SPY 가격을 받지 못함")
    px = pd.DataFrame(cols).sort_index()
    days = px["SPY"].dropna().index
    px = px.reindex(days)
    rets = core.clean_industry(px.pct_change(fill_method=None).iloc[1:])
    ff3 = ff.load("ff3_daily")
    rf = ff3["RF"].reindex(rets.index).ffill().fillna(0.0) if ff3 is not None else pd.Series(0.0, index=rets.index)
    return {"rets": rets, "mkt": rets["SPY"].copy(), "rf": rf, "source": "yfinance adjusted close (ETF menu)",
            "missing": sorted(set(ETF_MENU) - set(cols))}


# =================================================================================================
# 특징 (모두 d 전 거래일 종가까지의 자료만)
# =================================================================================================

def levels(rets: pd.DataFrame) -> pd.DataFrame:
    started = rets.notna().cummax()
    return np.exp(np.log1p(rets).fillna(0.0).cumsum()).where(started)


def raw_scores(rets: pd.DataFrame, mkt: pd.Series) -> dict[str, pd.DataFrame]:
    """모든 행에 대한 특징 점수(클수록 좋음). F1~F8 만(합성 C 는 표본 추출 뒤 순위로). 각 행의 값은 그 행 이전 자료만 쓴다."""
    lr = np.log1p(rets)
    lev = levels(rets)
    mkt_lr = np.log1p(mkt.reindex(rets.index).fillna(0.0))
    f1 = np.expm1(lr.rolling(W_F1, min_periods=W_F1).sum().shift(SKIP_F1))
    f2 = np.expm1(lr.rolling(W_F2, min_periods=W_F2).sum())
    f3 = lev / lev.rolling(W_HIGH, min_periods=W_HIGH).max()
    sma = lev.rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    f4 = f1 + 1000.0 * (lev > sma).astype(float).where(sma.notna() & f1.notna())
    mk12 = np.expm1(mkt_lr.rolling(W_RS, min_periods=W_RS).sum())
    f5 = np.expm1(lr.rolling(W_RS, min_periods=W_RS).sum()).sub(mk12, axis=0)
    hi = lev.rolling(W_BREAK, min_periods=W_BREAK).max()
    flag = (lev >= hi) & hi.notna()
    pos = pd.DataFrame(np.where(flag.to_numpy(), np.arange(len(lev))[:, None], np.nan), index=lev.index, columns=lev.columns).ffill()
    f6 = (-(np.arange(len(lev))[:, None] - pos)).where(hi.notna())
    f7 = -rets.rolling(W_VOL, min_periods=W_VOL).std()
    f8 = -np.expm1(lr.rolling(W_REV, min_periods=W_REV).sum())
    return {"F1": f1, "F2": f2, "F3": f3, "F4": f4, "F5": f5, "F6": f6, "F7": f7, "F8": f8}


def month_first_positions(index: pd.DatetimeIndex) -> np.ndarray:
    """매월 첫 거래일의 행 위치(첫 행 제외 — 그 앞 종가가 없다)."""
    m = core.month_first_mask(index)
    pos = np.flatnonzero(m)
    return pos[pos >= 1]


class Context:
    """한 유니버스의 사전 계산: 월별 신호 행렬·다음 수익 행렬·일별 수익."""

    def __init__(self, rets: pd.DataFrame, mkt: pd.Series, rf: pd.Series, k: int, label: str = ""):
        self.label, self.k = label, k
        self.rets = rets.sort_index(axis=1)
        self.mkt = mkt.reindex(self.rets.index).fillna(0.0)
        self.rf = rf.reindex(self.rets.index).fillna(0.0)
        self.members = list(self.rets.columns)
        self.lev = levels(self.rets)
        self.ew = self.rets.mean(axis=1, skipna=True).fillna(0.0)
        idx = self.rets.index
        self.dec = month_first_positions(idx)            # 결정(=월 첫 거래일) 행
        self.sd = self.dec - 1                            # 신호 기준 행(전 거래일)
        self.dates = idx[self.dec]
        raw = raw_scores(self.rets, self.mkt)
        self.scores: dict[str, np.ndarray] = {k_: v.to_numpy()[self.sd] for k_, v in raw.items()}
        ranks = {n: pd.DataFrame(self.scores[n]).rank(axis=1, pct=True).to_numpy() for n in ("F1", "F3", "F5")}
        self.scores["C"] = (ranks["F1"] + ranks["F3"] + ranks["F5"]) / 3.0   # 셋 중 하나라도 NaN 이면 NaN
        lv = self.lev.to_numpy()
        m = len(self.dec)
        self.next1 = np.full((m, lv.shape[1]), np.nan)
        self.next12 = np.full((m, lv.shape[1]), np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.next1[:-1] = lv[self.dec[1:]] / lv[self.dec[:-1]] - 1.0
            if m > 12:
                self.next12[:-12] = lv[self.dec[12:]] / lv[self.dec[:-12]] - 1.0
        # 시장 필터(보고용): 결정 시점 시장 지수 < SMA200 이면 비중 × FILTER_CUT
        ml = (1 + self.mkt).cumprod()
        sma = ml.rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
        below = (ml < sma) & sma.notna()
        self.below = below.to_numpy()[self.sd]

    # --- 선택·비중 ----------------------------------------------------------------------------
    def picks(self, signal: str) -> np.ndarray:
        """월별 선택 마스크 (M × N, bool). 유효 구성원이 2k 미만이면 그 달은 비어 있음."""
        s = self.scores[signal]
        out = np.zeros(s.shape, dtype=bool)
        for i in range(s.shape[0]):
            fin = np.isfinite(s[i])
            if fin.sum() < MIN_VALID_FACTOR * self.k:
                continue
            order = np.argsort(-np.where(fin, s[i], -np.inf), kind="stable")[: self.k]
            out[i, order] = True
        return out

    def daily_weights(self, picks: np.ndarray, market_filter: bool = False) -> pd.DataFrame:
        n_rows, n_mem = len(self.rets), len(self.members)
        w = np.zeros((n_rows, n_mem))
        ends = list(self.dec[1:]) + [n_rows]
        for i, (a, b) in enumerate(zip(self.dec, ends)):
            row = picks[i].astype(float) / self.k
            if market_filter and self.below[i]:
                row = row * FILTER_CUT
            w[a:b] = row
        return pd.DataFrame(w, index=self.rets.index, columns=self.members)

    def strategy(self, signal: str, market_filter: bool = False, bps: float = COST_BPS) -> pd.Series:
        w = self.daily_weights(self.picks(signal), market_filter)
        return core.strategy_returns(self.rets, self.rf, w, bps)


# =================================================================================================
# 통계
# =================================================================================================

def hit_series(ctx: Context, signal: str, horizon: int = 1) -> np.ndarray:
    """월별 적중률: 선택된 구성원 중 같은 달 유효 구성원의 다음 수익 상위 3분위(엄격히 2/3 분위수 초과)에 든 비율. 포지션 없는 달은 NaN."""
    nxt = ctx.next1 if horizon == 1 else ctx.next12
    pk = ctx.picks(signal)
    s = ctx.scores[signal]
    out = np.full(len(s), np.nan)
    for i in range(len(s)):
        if not pk[i].any():
            continue
        elig = np.isfinite(s[i]) & np.isfinite(nxt[i])
        if elig.sum() < 3:
            continue
        cut = np.quantile(nxt[i][elig], HIT_QUANTILE)
        sel = pk[i] & elig
        if sel.any():
            out[i] = float((nxt[i][sel] > cut).mean())
    return out


def ic_series(ctx: Context, signal: str) -> np.ndarray:
    """월별 순위 IC: 신호와 다음 1개월 수익의 스피어만 상관(유효 구성원 5개 미만이면 NaN)."""
    s, nxt = ctx.scores[signal], ctx.next1
    out = np.full(len(s), np.nan)
    for i in range(len(s)):
        elig = np.isfinite(s[i]) & np.isfinite(nxt[i])
        if elig.sum() < 5:
            continue
        a = pd.Series(s[i][elig]).rank().to_numpy()
        b = pd.Series(nxt[i][elig]).rank().to_numpy()
        if a.std() == 0 or b.std() == 0:
            continue
        out[i] = float(np.corrcoef(a, b)[0, 1])
    return out


def block_bootstrap_ci(x: np.ndarray, block: int = BOOT_BLOCK, draws: int = BOOT_DRAWS, seed: int = BOOT_SEED,
                       alpha: float = 0.05) -> dict[str, Any]:
    """원형 블록 부트스트랩(블록 12개월)으로 평균의 양쪽 95% 구간. NaN 은 먼저 버린다. 같은 입력·시드면 항상 같은 결과."""
    v = np.asarray(x, float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < block * 2:
        return {"mean": float(v.mean()) if n else None, "lo": None, "hi": None, "n": int(n)}
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(n / block))
    starts = rng.integers(0, n, size=(draws, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    means = v[idx.reshape(draws, -1)[:, :n]].mean(axis=1)
    return {"mean": float(v.mean()), "lo": float(np.quantile(means, alpha / 2)), "hi": float(np.quantile(means, 1 - alpha / 2)), "n": int(n)}


def nw_mean_t(x: np.ndarray) -> dict[str, Any]:
    """평균과 Newey-West(6) t."""
    from core.french_factors import ols_nw

    v = np.asarray(x, float)
    v = v[np.isfinite(v)]
    if len(v) < 24:
        return {"mean": float(v.mean()) if len(v) else None, "t": None, "n": int(len(v))}
    fit = ols_nw(v, np.empty((len(v), 0)), NW_LAGS)
    return {"mean": float(fit["coef"][0]), "t": float(fit["t"][0]), "n": int(len(v))}


def in_window(dates: pd.DatetimeIndex, a: str, b: Optional[str]) -> np.ndarray:
    m = dates >= pd.Timestamp(a)
    if b:
        m &= dates <= pd.Timestamp(b)
    return np.asarray(m)


def _nan_capm() -> dict[str, float]:
    return {"alpha_annual": float("nan"), "alpha_t_nw6": float("nan"), "beta_monthly": float("nan"), "appraisal_ir": float("nan"), "months": 0}


def safe_capm(r: pd.Series, bench: pd.Series, rf: pd.Series, min_months: int = 24) -> dict[str, float]:
    if r.empty or core.monthly(r).shape[0] < min_months:
        return _nan_capm()
    return core.capm(r, bench, rf)


def port_stats(strat: pd.Series, ctx: Context, a: str, b: Optional[str]) -> dict[str, Any]:
    s = core.window(strat, a, b)
    if len(s) < 60:
        return {"days": int(len(s))}
    cm = safe_capm(s, ctx.mkt, ctx.rf)
    ce = safe_capm(s, ctx.ew, ctx.rf)
    return {"days": int(len(s)), "cagr": core.cagr(s), "sharpe": core.sharpe_monthly(s, ctx.rf), "mdd": core.mdd(s),
            "alpha_mkt": cm["alpha_annual"], "t_mkt": cm["alpha_t_nw6"], "beta": cm["beta_monthly"],
            "alpha_ew": ce["alpha_annual"], "t_ew": ce["alpha_t_nw6"], "ir_ew": ce["appraisal_ir"]}


def window_block(ctx: Context, signal: str, strat: pd.Series, hit1: np.ndarray, hit12: np.ndarray, ic: np.ndarray,
                 a: str, b: Optional[str]) -> dict[str, Any]:
    m = in_window(ctx.dates, a, b)
    return {"months": int(np.isfinite(hit1[m]).sum()), "hit1": block_bootstrap_ci(hit1[m]), "hit12": block_bootstrap_ci(hit12[m]),
            "ic": nw_mean_t(ic[m]), "port": port_stats(strat, ctx, a, b)}


def cell_pass(hit_lo: Optional[float], alpha: Optional[float], alpha_t: Optional[float], n_positive: Optional[int]) -> Optional[bool]:
    """LEADER_SIGNAL_CONFIRMED(한 유니버스에서): 확인 반 1개월 적중률 CI 하한 > 1/3 AND 알파 > 0 & NW t ≥ 2.0 AND 4개 하위 구간 중 알파 > 0 이 3개 이상.
    입력이 비어 있으면 None(평가 불가)."""
    vals = (hit_lo, alpha, alpha_t, n_positive)
    if any(v is None or (isinstance(v, float) and not math.isfinite(v)) for v in vals):
        return None
    return bool(hit_lo > HIT_CHANCE and alpha > 0 and alpha_t >= T_MIN and n_positive >= SUB_MIN_POSITIVE)


def signal_verdict(cell_flags: list[Optional[bool]]) -> str:
    """세 유니버스 판정 → ROBUST(2곳 이상 확인) / NOT_ROBUST / NOT_EVALUABLE(모두 평가 불가)."""
    if all(f is None for f in cell_flags):
        return "NOT_EVALUABLE"
    return "ROBUST" if sum(1 for f in cell_flags if f is True) >= ROBUST_MIN_UNIVERSES else "NOT_ROBUST"


def overall_verdict(sig_verdicts: dict[str, str]) -> str:
    """대조군(F7·F8) 중 하나라도 ROBUST 면 시험이 변별력이 없다(NOT_DISCRIMINATING). 아니면 모멘텀류 중 ROBUST 가 있나."""
    if any(sig_verdicts.get(c) == "ROBUST" for c in CONTROLS):
        return "NOT_DISCRIMINATING"
    if any(sig_verdicts.get(s) == "ROBUST" for s in MOMENTUM_LIKE):
        return "LEADER_SIGNAL_ROBUST"
    if all(v == "NOT_EVALUABLE" for v in sig_verdicts.values()):
        return "NOT_EVALUABLE"
    return "NO_ROBUST_LEADER_SIGNAL"


def evaluate_cell(ctx: Context, signal: str, power: dict, rp) -> dict[str, Any]:
    """한 유니버스 × 한 신호의 모든 측정과 판정."""
    strat = ctx.strategy(signal)
    strat_f = ctx.strategy(signal, market_filter=True)
    hit1, hit12, ic = hit_series(ctx, signal, 1), hit_series(ctx, signal, 12), ic_series(ctx, signal)
    wins = {"sel": (SEL_START, SEL_END), "conf": (CONF_START, CONF_END), "full": (MAIN_START, MAIN_END), "post2008": (POST_START, None)}
    windows = {k: window_block(ctx, signal, strat, hit1, hit12, ic, a, b) for k, (a, b) in wins.items()}
    filt = {k: port_stats(strat_f, ctx, a, b) for k, (a, b) in (("full", wins["full"]), ("post2008", wins["post2008"]))}
    subs = []
    for a, b in SUBPERIODS:
        p = port_stats(strat, ctx, a, b)
        subs.append({"start": a, "end": b, "alpha_ew": p.get("alpha_ew"), "t_ew": p.get("t_ew"),
                     "alpha_mkt": p.get("alpha_mkt"), "t_mkt": p.get("t_mkt")})
    n_pos = sum(1 for s_ in subs if s_.get("alpha_ew") is not None and math.isfinite(s_["alpha_ew"]) and s_["alpha_ew"] > 0)
    n_pos_mkt = sum(1 for s_ in subs if s_.get("alpha_mkt") is not None and math.isfinite(s_["alpha_mkt"]) and s_["alpha_mkt"] > 0)
    decades = []
    for d in DECADES:
        a = max(f"{d}-01-01", MAIN_START)
        b = min(f"{d + 9}-12-31", MAIN_END)
        m = in_window(ctx.dates, a, b)
        p = port_stats(strat, ctx, a, b)
        decades.append({"decade": d, "ic": nw_mean_t(ic[m])["mean"], "hit1": float(np.nanmean(hit1[m])) if np.isfinite(hit1[m]).any() else None,
                        "alpha_ew": p.get("alpha_ew"), "alpha_mkt": p.get("alpha_mkt")})
    conf = windows["conf"]
    full = windows["full"]["port"]
    active = (core.window(strat, MAIN_START, MAIN_END) - core.window(ctx.ew, MAIN_START, MAIN_END)).tolist()
    noop = rp.noop_guard(active)
    pass_parts = {"hit_lo_conf_1m": conf["hit1"]["lo"], "alpha_ew_conf": conf["port"].get("alpha_ew"),
                  "t_ew_conf": conf["port"].get("t_ew"), "n_positive_subperiods_ew": n_pos}
    flag = None if noop else cell_pass(pass_parts["hit_lo_conf_1m"], pass_parts["alpha_ew_conf"], pass_parts["t_ew_conf"], n_pos)
    verdict = "NOT_EVALUABLE" if flag is None else ("LEADER_SIGNAL_CONFIRMED" if flag else "NOT_CONFIRMED")
    res = {"signal": signal, "k": ctx.k, "windows": windows, "with_market_filter": filt, "subperiods": subs,
           "n_positive_subperiods_ew": n_pos, "n_positive_subperiods_mkt": n_pos_mkt, "decades": decades,
           "pass_parts": pass_parts, "noop_guard": noop, "verdict": verdict, "confirmed": flag}
    if verdict == "NOT_CONFIRMED":
        res["fail_kind"] = rp.classify_fail(full.get("ir_ew"), power)
    return res


# =================================================================================================
# 집중도 진단 (보고만)
# =================================================================================================

def spearman(a: np.ndarray, b: np.ndarray) -> float:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return float("nan")
    ra, rb = pd.Series(a[m]).rank().to_numpy(), pd.Series(b[m]).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def concentration_table(ctx: Context) -> list[dict[str, Any]]:
    """연도별: 그해 수익 상위 3개 구성원이 (양의 수익 합계에서) 차지한 몫, 상위 3 평균 − 전체 평균, 지난해 순위와의 상관(리더십 지속),
    지난해 상위 3과 겹친 수. 달력 연도 수익(전년 말 종가 → 그해 말 종가), 전년 말에 유효했던 구성원만. 자료가 12월에 끝나지 않으면 마지막 해는 뺀다."""
    lev = ctx.lev
    ye = lev.groupby(lev.index.year).last()
    last = lev.index[-1]
    if not (last.month == 12 and last.day >= 24):
        ye = ye.iloc[:-1]
    yr = (ye / ye.shift(1) - 1.0)
    rows = []
    prev = None
    for y in yr.index[1:]:
        v = yr.loc[y].to_numpy()
        fin = np.isfinite(v)
        if fin.sum() < 8:
            prev = None
            continue
        order = np.argsort(-np.where(fin, v, -np.inf), kind="stable")
        top = order[:CONC_TOP]
        pos = np.clip(v[fin], 0, None)
        share = float(np.clip(v[top], 0, None).sum() / pos.sum()) if pos.sum() > 0 else float("nan")
        row = {"year": int(y), "n": int(fin.sum()), "top3_share_pos": share, "top3_minus_mean": float(v[top].mean() - v[fin].mean()),
               "dispersion": float(v[fin].std(ddof=1)), "persistence": float("nan"), "top3_overlap": None}
        if prev is not None:
            row["persistence"] = spearman(prev["v"], v)
            row["top3_overlap"] = int(len(set(prev["top"].tolist()) & set(top.tolist())))
        prev = {"v": v, "top": top}
        rows.append(row)
    return rows


def concentration_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def agg(sel):
        r = [x for x in rows if sel(x["year"])]
        f = lambda k: float(np.nanmean([x[k] for x in r if x.get(k) is not None])) if r and any(
            x.get(k) is not None and np.isfinite(x[k]) for x in r) else None
        return {"years": len(r), "top3_share_pos": f("top3_share_pos"), "top3_minus_mean": f("top3_minus_mean"),
                "dispersion": f("dispersion"), "persistence": f("persistence"), "top3_overlap": f("top3_overlap")}
    return {"pre2008": agg(lambda y: y <= 2007), "post2008": agg(lambda y: y >= 2008)}


# =================================================================================================
# ETF 메뉴 (보조, 보고 + '지지' 표시만)
# =================================================================================================

def etf_supports(res: dict) -> bool:
    """SUPPORTING: 적중률 점추정 > 1/3 AND 평균 IC > 0 AND SPY 대비 알파 > 0 (구간이 짧아 유의성은 요구하지 않는다)."""
    h = res["hit1"]["mean"]
    ic = res["ic"]["mean"]
    al = res["port"].get("alpha_mkt")
    return bool(h is not None and ic is not None and al is not None and h > HIT_CHANCE and ic > 0 and al > 0)


def evaluate_etf(ctx: Context, signal: str) -> dict[str, Any]:
    strat = ctx.strategy(signal)
    hit1, hit12, ic = hit_series(ctx, signal, 1), hit_series(ctx, signal, 12), ic_series(ctx, signal)
    res = window_block(ctx, signal, strat, hit1, hit12, ic, ETF_START, ETF_END)
    res.update({"signal": signal, "k": ctx.k, "supporting": etf_supports(res),
                "control": signal in CONTROLS})
    return res
