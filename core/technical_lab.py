"""차트 매매 규칙(유튜브 대본 출신) R&D (2026-10-02) — 단독 성과, 한계, 챔피언(코어+새틀라이트)과의 시너지.

사용자 지시: 볼린저 하단 반전·스퀴즈, RSI 과매도, 캔들 패턴, 이평 돌파, 1:2:6 분할매수 같은 규칙을 같은 종목 풀·같은 비용·같은 판정으로
돌리고, 현재 새틀라이트·코어와 결합했을 때 언제 시너지가 나는지 가설을 세워 연구·기각·한계 돌파까지 하라.

규칙은 core/indicators.py 의 지표 함수(전략 스튜디오가 유튜브 대본을 해석할 때 쓰는 것)를 그대로 쓴다.
포지션 엔진(벡터화): 종목마다 그날 종가까지로 목표 포지션(0~1)을 정하고 다음 날부터 수익을 받는다(엔진 관례 shift(1)).
포트폴리오 = 활성 포지션 / max(활성 합, K) — K개 슬롯 동일가중, 남는 몫은 단기국채(BIL) 총수익. 비용 편도 8bp × 비중 변화.
후보 풀은 새틀라이트 R&D 와 같은 point-in-time 풀(월별 편입 기준). 수익은 배당 포함 조정 가격(Adj Close).

연구 순서와 판정은 research/jobs/tech-rnd-v1/run.py 에 고정(결과를 보기 전). 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from core import indicators as ind

COST_BPS = 8.0
TRAIN_END = pd.Timestamp("2020-01-01")   # 개발 구간 끝(라운드 사이 판단은 검증 구간 2020-01 ~ 떼어 둔 구간 직전)
TRADING_DAYS = 252


# =================================================================================================
# 규칙 — (이름, 종류, 파라미터). 각 규칙은 OHLCV DataFrame → 목표 포지션 Series(0~1)
# =================================================================================================

def _state(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """진입 이벤트가 나면 1, 청산 이벤트가 나면 0 을 유지(같은 날이면 청산 우선)."""
    ev = pd.Series(np.where(exit_.fillna(False), 0.0, np.where(entry.fillna(False), 1.0, np.nan)), index=entry.index)
    return ev.ffill().fillna(0.0)


def _hold(entry: pd.Series, days: int) -> pd.Series:
    return entry.fillna(False).astype(float).rolling(days, min_periods=1).max()


def rule_position(df: pd.DataFrame, kind: str, p: dict) -> pd.Series:
    c = df["Close"]
    if kind == "rsi":
        rsi = ind.compute_rsi(df, p["n"])
        ex = (c > c.rolling(5).mean()) if p["exit"] == "sma5" else (rsi > 50)
        return _state(rsi < p["lo"], ex)
    if kind == "bb_reversal":
        bb = ind.compute_bollinger(df, 20, p["k"])
        entry = (c.shift(1) < bb["lower"].shift(1)) & (c > bb["lower"])
        ex = c > (bb["mid"] if p["exit"] == "mid" else bb["upper"])
        return _state(entry, ex)
    if kind == "bb_squeeze":
        bbw = ind.compute_bbw(df, 20, 2.0)
        low = bbw <= bbw.rolling(126, min_periods=60).quantile(p["q"])
        bb = ind.compute_bollinger(df, 20, 2.0)
        entry = low.shift(1).rolling(10, min_periods=1).max().astype(bool) & (c > bb["upper"])
        return _state(entry, c < bb["mid"])
    if kind == "candle":
        pat = ind.compute_engulfing(df)["bullish"] if p["pattern"] == "engulfing" else ind.compute_pin_bar(df)["bullish"]
        entry = pat & (c < c.rolling(20).mean())  # 하락 뒤 반전 캔들(대본들의 공통 조건)
        return _hold(entry, p["hold"])
    if kind == "ma_trend":
        if p["mode"] == "golden":
            fast, slow = c.rolling(50).mean(), c.rolling(200).mean()
            return (fast > slow).astype(float).where(slow.notna(), 0.0)
        sma = c.rolling(p["n"]).mean()
        return (c > sma).astype(float).where(sma.notna(), 0.0)
    if kind == "turtle":
        hi = c.shift(1).rolling(p["entry"]).max()
        lo = c.shift(1).rolling(p["exit"]).min()
        return _state(c > hi, c < lo)
    if kind == "volume_breakout":
        vr = df["Volume"] / df["Volume"].rolling(20).mean()
        entry = (vr > p["mult"]) & (c > c.shift(1)) & (c >= c.rolling(20).max())
        return _hold(entry, p["hold"])
    if kind == "staged_126":
        # 후지모토 1:2:6 — 밴드 하단 2.0/2.5/3.0σ 를 차례로 깨면 10%→30%→90%, 중심선 위로 오면 전량 청산
        mid = c.rolling(20).mean()
        sd = c.rolling(20).std()
        tier = pd.Series(0.0, index=c.index)
        for k, lvl in ((2.0, 0.1), (2.5, 0.3), (3.0, 0.9)):
            tier = tier.where(~(c < mid - k * sd), lvl)
        exit_ev = (c > mid).fillna(False)
        episode = exit_ev.cumsum()
        level = tier.groupby(episode).cummax()
        return level.where(~exit_ev, 0.0).fillna(0.0) * (1.0 / 0.9 if p.get("full") else 1.0)
    raise ValueError(kind)


def rule_grid() -> list[tuple[str, str, dict]]:
    g: list[tuple[str, str, dict]] = []
    for n, lo, ex in itertools.product((2, 14), (10, 20, 30), ("sma5", "rsi50")):
        g.append((f"rsi{n}<{lo},exit_{ex}", "rsi", {"n": n, "lo": lo, "exit": ex}))
    for k, ex in itertools.product((2.0, 2.5), ("mid", "upper")):
        g.append((f"bb_rev{k},exit_{ex}", "bb_reversal", {"k": k, "exit": ex}))
    for q in (0.1, 0.2):
        g.append((f"bb_squeeze_q{q}", "bb_squeeze", {"q": q}))
    for pat, h in itertools.product(("engulfing", "pinbar"), (5, 10, 20)):
        g.append((f"{pat}_after_dip,hold{h}", "candle", {"pattern": pat, "hold": h}))
    g.append(("golden_cross50/200", "ma_trend", {"mode": "golden"}))
    for n in (50, 100, 200):
        g.append((f"above_sma{n}", "ma_trend", {"mode": "above", "n": n}))
    for e, x in ((20, 10), (55, 20)):
        g.append((f"turtle{e}/{x}", "turtle", {"entry": e, "exit": x}))
    for m, h in ((2.0, 10), (3.0, 10)):
        g.append((f"volume{m}x_breakout,hold{h}", "volume_breakout", {"mult": m, "hold": h}))
    g.append(("staged_1:2:6", "staged_126", {}))
    g.append(("staged_1:2:6_full", "staged_126", {"full": True}))
    return g


# =================================================================================================
# 위치 행렬 → 포트폴리오 수익
# =================================================================================================

def membership(data, pool_type: str, days: pd.DatetimeIndex) -> pd.DataFrame:
    """월초마다 그 시점 풀 편입 여부(행=날짜, 열=종목, bool)."""
    from core import satellite_lab as sl

    tickers = sorted(data.ohlcv)
    m = pd.DataFrame(np.nan, index=days, columns=tickers)
    for d in sl.rebalance_dates(days, 1):
        members = set(data.pool(pool_type, d))
        m.loc[d] = [1.0 if t in members else 0.0 for t in tickers]
    return m.ffill().fillna(0.0).astype(bool)


def positions_matrix(data, kind: str, p: dict, days: pd.DatetimeIndex, tickers: list[str]) -> pd.DataFrame:
    cols = {}
    for t in tickers:
        df = data.ohlcv.get(t)
        if df is None or len(df) < 60 or not {"Open", "High", "Low", "Close", "Volume"} <= set(df.columns):
            continue
        try:
            pos = rule_position(df, kind, p)
        except Exception:  # noqa: BLE001 - 데이터 이상 종목은 건너뛴다
            continue
        cols[t] = pos.reindex(days).ffill().fillna(0.0)
    return pd.DataFrame(cols, index=days).fillna(0.0)


def adj_returns(data, days: pd.DatetimeIndex, tickers: list[str]) -> pd.DataFrame:
    out = {}
    for t in tickers:
        df = data.ohlcv.get(t)
        if df is None:
            continue
        px = df["Adj Close"] if "Adj Close" in df.columns and df["Adj Close"].notna().any() else df["Close"]
        out[t] = px.reindex(days).ffill().pct_change(fill_method=None)
    return pd.DataFrame(out, index=days).fillna(0.0)


def sleeve_returns(pos: pd.DataFrame, member: pd.DataFrame, rets: pd.DataFrame, k: int,
                   cash_ret: Optional[pd.Series] = None, bps: float = COST_BPS,
                   gate: Optional[pd.Series] = None) -> pd.Series:
    """목표 포지션(그날 종가 결정) → 다음 날부터 수익. gate(날짜 bool)가 False 인 날은 신규·보유 모두 0."""
    cols = [c for c in pos.columns if c in member.columns and c in rets.columns]
    p = pos[cols] * member[cols].astype(float)
    if gate is not None:
        p = p.mul(gate.reindex(p.index).fillna(False).astype(float), axis=0)
    tot = p.sum(axis=1)
    w = p.div(np.maximum(tot, k), axis=0)
    cash_w = 1.0 - w.sum(axis=1)
    ex = w.shift(1).fillna(0.0)
    gross = (ex * rets[cols]).sum(axis=1)
    if cash_ret is not None:
        gross = gross + cash_w.shift(1).fillna(0.0) * cash_ret.reindex(w.index).fillna(0.0)
    turnover = (ex - ex.shift(1).fillna(0.0)).abs().sum(axis=1)
    return gross - turnover * bps / 1e4


def turnover_reduce(pos: pd.DataFrame, mode: str) -> pd.DataFrame:
    """한계 돌파 장치: 최소 5일 보유(진입하면 5일은 유지) / 주 1회만 결정(주 첫 거래일 값을 그 주 내내)."""
    if mode == "min_hold5":
        return pos.rolling(5, min_periods=1).max().where(pos.cummax() > 0, 0.0)
    if mode == "weekly":
        wk = pd.Series(pos.index.to_period("W"), index=pos.index)
        first = (wk != wk.shift(1)).to_numpy()
        return pos.where(pd.Series(first, index=pos.index), np.nan).ffill().fillna(0.0)
    raise ValueError(mode)


# =================================================================================================
# 국면(시너지 분석·국면 게이트)
# =================================================================================================

def regimes(spy: pd.Series, vix: Optional[pd.Series], days: pd.DatetimeIndex) -> pd.DataFrame:
    """그날 종가로 판단한 국면(다음 날 수익에 쓰도록 호출부가 shift). bull=SPY>200일선 & 6개월 상승, bear=SPY<200일선, 나머지 sideways."""
    s = spy.reindex(days).ffill()
    sma = s.rolling(200, min_periods=200).mean()
    r6 = s.pct_change(126, fill_method=None)
    above = s > sma
    out = pd.DataFrame(index=days)
    out["bull"] = above & (r6 > 0)
    out["bear"] = (~above) & sma.notna()
    out["sideways"] = ~(out["bull"] | out["bear"])
    if vix is not None:
        v = vix.reindex(days).ffill()
        out["high_vol"] = v > 20
        out["low_vol"] = v <= 20
    return out


def stats(r: pd.Series) -> dict[str, float]:
    r = r.dropna()
    if len(r) < 20:
        return {"n": len(r)}
    sd = r.std(ddof=1)
    eq = (1 + r).cumprod()
    return {"n": len(r), "sharpe": float(r.mean() / sd * math.sqrt(TRADING_DAYS)) if sd > 0 else 0.0,
            "cagr": float(eq.iloc[-1] ** (TRADING_DAYS / len(r)) - 1), "mdd": float((eq / eq.cummax() - 1).min()),
            "vol": float(sd * math.sqrt(TRADING_DAYS))}


def regime_table(r: pd.Series, bench: pd.Series, reg: pd.DataFrame) -> dict[str, dict]:
    """국면별 연 초과수익(규칙 − 비교 대상)과 상관. 국면은 전날 종가 기준."""
    lagged = reg.shift(1).fillna(False).astype(bool)
    out = {}
    for name in lagged.columns:
        m = lagged[name]
        if m.sum() < 60:
            continue
        a, b = r[m], bench.reindex(r.index)[m]
        out[name] = {"days": int(m.sum()), "excess_ann": float((a - b).mean() * TRADING_DAYS),
                     "corr": float(a.corr(b)) if a.std() > 0 and b.std() > 0 else None,
                     "sharpe": stats(a).get("sharpe")}
    return out


def breakeven_bps(pos: pd.DataFrame, member: pd.DataFrame, rets: pd.DataFrame, k: int, cash_ret: Optional[pd.Series]) -> Optional[float]:
    """수익이 0 이 되는 편도 비용(bp) — 회전율 큰 단기 규칙의 한계 측정."""
    gross = sleeve_returns(pos, member, rets, k, cash_ret, bps=0.0)
    cols = [c for c in pos.columns if c in member.columns and c in rets.columns]
    p = pos[cols] * member[cols].astype(float)
    w = p.div(np.maximum(p.sum(axis=1), k), axis=0).shift(1).fillna(0.0)
    turn = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).sum()
    total = gross.sum()
    if turn <= 0:
        return None
    return float(total / turn * 1e4)
