"""매매 실행 R&D (2026-10-02) — "얼마에 사고 얼마에 팔아야 하나"를 시험한다.

챔피언 전략은 리밸런싱 날 종가에 사고판다(백테스트 기준). 이 모듈은 그 실제 매매 하나하나에 다른 실행 방법
(다음 날 시가, 지정가, 나눠 사기, 눌림목, 익절)을 적용했을 때 기준(그날 종가)보다 얼마나 유리했는지 잰다.
종목 선택은 바꾸지 않는다 — 같은 종목을 '언제·얼마에' 사고파는지만 바꾼다.

측정(배당 포함 조정 가격): 매수 개선 = 기준가/체결가 − 1, 매도 개선 = 체결가/기준가 − 1. 기다리는 동안 그 돈은 현금(수익 0).
일봉만 있으므로 지정가 체결은 근사다: 그날 시가가 지정가보다 유리하면 시가에, 아니면 저가(매도는 고가)가 지정가에 닿았을 때
지정가에 체결된 것으로 본다(호가 대기열·부분 체결은 모름). 기한 안에 안 채워지면 마지막 날 종가로 매매한다.
판정 exec-judge/v1 은 research/jobs/exec-rnd-v1/run.py 에 고정. 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Optional

import numpy as np
import pandas as pd

JUDGE_VERSION = "exec-judge/v1"
HOLDOUT_YEARS = 2
FAMILY_ALPHA = 0.05  # 모든 칸(규칙×슬리브×방향)을 함께 시험하는 것을 감안한 단측 본페로니
_N = NormalDist()

# 규칙: (이름, 설명). 매수·매도에 대칭으로 쓴다.
RULES: dict[str, str] = {
    "next_open": "다음 날 시가",
    "limit1_5d": "지정가 1% 유리하게, 5거래일 안에 안 되면 5일째 종가",
    "limit2_5d": "지정가 2% 유리하게, 5거래일 안에 안 되면 5일째 종가",
    "limit3_10d": "지정가 3% 유리하게, 10거래일 안에 안 되면 10일째 종가",
    "split3": "3번 나눠서(당일·5일 뒤·10일 뒤 종가)",
    "pullback": "매수는 종가가 5일 평균 아래로 내려온 날, 매도는 위로 올라온 날(최대 10일)",
}
TAKE_PROFITS = {"tp20": 0.20, "tp40": 0.40}  # 새틀라이트 보유 중 익절(그 뒤 다음 리밸런싱까지 현금)
MAX_WAIT = 10


def adjusted(df: pd.DataFrame) -> pd.Series:
    """원 가격 → 배당 포함 조정 가격 환산 배수(Adj Close/Close). 없으면 1."""
    if "Adj Close" in df.columns and df["Adj Close"].notna().any():
        return (df["Adj Close"] / df["Close"]).ffill().fillna(1.0)
    return pd.Series(1.0, index=df.index)


def execute(df: pd.DataFrame, i: int, side: str, rule: str) -> Optional[float]:
    """i(리밸런싱 날 행 번호) 기준으로 규칙을 적용한 체결가(조정 가격). 데이터가 모자라면 None."""
    if i + MAX_WAIT >= len(df):
        return None
    o, h, lo, c = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    f = adjusted(df).to_numpy(dtype=float)
    buy = side == "buy"

    def at(j: int, px: float) -> float:
        return px * f[j]

    if rule == "next_open":
        return at(i + 1, o[i + 1])
    if rule.startswith("limit"):
        pct = {"limit1_5d": 0.01, "limit2_5d": 0.02, "limit3_10d": 0.03}[rule]
        days = 5 if rule.endswith("5d") else 10
        lim = c[i] * (1 - pct if buy else 1 + pct)
        for j in range(i + 1, i + days + 1):
            if buy and o[j] <= lim:
                return at(j, o[j])
            if not buy and o[j] >= lim:
                return at(j, o[j])
            if buy and lo[j] <= lim:
                return at(j, lim)
            if not buy and h[j] >= lim:
                return at(j, lim)
        return at(i + days, c[i + days])
    if rule == "split3":
        return float(np.mean([at(i, c[i]), at(i + 5, c[i + 5]), at(i + 10, c[i + 10])]))
    if rule == "pullback":
        sma5 = pd.Series(c).rolling(5, min_periods=5).mean().to_numpy()
        for j in range(i + 1, i + MAX_WAIT + 1):
            if not math.isnan(sma5[j]) and ((buy and c[j] < sma5[j]) or (not buy and c[j] > sma5[j])):
                return at(j, c[j])
        return at(i + MAX_WAIT, c[i + MAX_WAIT])
    raise ValueError(rule)


def improvement(df: pd.DataFrame, d: pd.Timestamp, side: str, rule: str) -> Optional[float]:
    if d not in df.index:
        return None
    i = df.index.get_loc(d)
    px = execute(df, i, side, rule)
    if px is None or not math.isfinite(px) or px <= 0:
        return None
    base = float(df["Close"].iloc[i] * adjusted(df).iloc[i])
    return base / px - 1 if side == "buy" else px / base - 1


def take_profit_improvement(df: pd.DataFrame, d: pd.Timestamp, end: pd.Timestamp, tp: float) -> Optional[float]:
    """보유 구간 [d, end] 에서 종가가 진입가×(1+tp) 이상이 된 날 팔고 현금 — 끝까지 들고 간 것 대비 가치 비율 − 1."""
    if d not in df.index:
        return None
    adj = (df["Close"] * adjusted(df)).loc[d:end].ffill()
    if len(adj) < 2:
        return None
    rel = (adj / adj.iloc[0]).to_numpy()
    hit = np.nonzero(rel[1:] >= 1 + tp)[0]
    exit_val = rel[hit[0] + 1] if len(hit) else rel[-1]
    return float(exit_val / rel[-1] - 1)


# ---------------------------------------------------------------- 매매 목록
def core_trades(weights: pd.DataFrame, scale: float, skip: tuple[str, ...] = ("BIL",)) -> list[dict]:
    """코어 목표 비중 변화 → 매매(리밸런싱 날 종가 기준). 비중은 포트폴리오 전체 기준(scale = 코어 비중)."""
    out = []
    diff = weights.diff().fillna(weights)
    for d, row in diff.iterrows():
        for t, dw in row.items():
            if t in skip or abs(dw) < 1e-9:
                continue
            out.append({"date": d, "ticker": t, "side": "buy" if dw > 0 else "sell", "w": abs(float(dw)) * scale, "sleeve": "core"})
    return out


def satellite_trades(schedule: list[tuple[str, list[str]]], scale: float) -> list[dict]:
    """새틀라이트 재선정 → 새로 담는 종목 매수, 빠지는 종목 매도(이어서 보유하는 종목은 매매 없음으로 본다)."""
    out, prev = [], []
    for i, (d, picks) in enumerate(schedule):
        d = pd.Timestamp(d)
        nxt = pd.Timestamp(schedule[i + 1][0]) if i + 1 < len(schedule) else None
        for t in picks:
            if t not in prev:
                out.append({"date": d, "ticker": t, "side": "buy", "w": scale / max(len(picks), 1), "sleeve": "satellite", "end": nxt})
        for t in prev:
            if t not in picks:
                out.append({"date": d, "ticker": t, "side": "sell", "w": scale / max(len(prev), 1), "sleeve": "satellite"})
        prev = list(picks)
    return out


# ---------------------------------------------------------------- 판정
def _cell_stats(rows: pd.DataFrame, split: pd.Timestamp) -> dict[str, Any]:
    """rows: date, w, imp. 리밸런싱 날짜를 한 단위로 묶어(같은 날 매매는 서로 독립이 아님) 가중 평균 개선을 본다."""
    rows = rows.dropna(subset=["imp"])
    if rows.empty:
        return {"n_trades": 0}
    by_date = rows.groupby("date").apply(lambda g: float(np.average(g["imp"], weights=g["w"])), include_groups=False)
    is_part, oos = by_date[by_date.index < split], by_date[by_date.index >= split]
    n = len(is_part)
    mean = float(is_part.mean()) if n else float("nan")
    sd = float(is_part.std(ddof=1)) if n > 1 else float("nan")
    t = mean / (sd / math.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    thirds = [float(x.mean()) for x in np.array_split(is_part, 3) if len(x)] if n >= 3 else []
    years = max((rows["date"].max() - rows["date"].min()).days / 365.25, 1e-9)
    return {"n_trades": int(len(rows)), "n_dates_is": n, "mean_is_bps": mean * 1e4, "t_is": t,
            "mean_oos_bps": float(oos.mean()) * 1e4 if len(oos) else None, "n_dates_oos": int(len(oos)),
            "thirds_bps": [x * 1e4 for x in thirds],
            "portfolio_bps_per_year": float((rows["w"] * rows["imp"]).sum()) / years * 1e4,
            "hit_rate": float((rows["imp"] > 0).mean())}


def judge(cells: dict[str, pd.DataFrame], split: pd.Timestamp) -> dict[str, Any]:
    """칸마다: IS 개선 평균 > 0, 날짜 단위 t ≥ 본페로니 임계값, 떼어 둔 2년 평균 > 0, IS 3구간 중 2구간 이상 > 0."""
    n_tests = max(len(cells), 1)
    t_crit = _N.inv_cdf(1 - FAMILY_ALPHA / n_tests)
    out = {}
    for key, rows in cells.items():
        s = _cell_stats(rows, split)
        reasons = []
        if not s.get("n_trades"):
            out[key] = {**s, "verdict": "FAIL", "reasons": ["매매 없음"]}
            continue
        if not (s["mean_is_bps"] > 0 and s["t_is"] >= t_crit):
            reasons.append(f"IS 평균 {s['mean_is_bps']:.1f}bp, t {s['t_is']:.2f} < {t_crit:.2f}")
        if s["mean_oos_bps"] is None or s["mean_oos_bps"] <= 0:
            reasons.append(f"떼어 둔 2년 평균 {s['mean_oos_bps'] if s['mean_oos_bps'] is None else round(s['mean_oos_bps'], 1)}bp ≤ 0")
        if sum(1 for x in s["thirds_bps"] if x > 0) < 2:
            reasons.append(f"IS 3구간 중 개선 {sum(1 for x in s['thirds_bps'] if x > 0)}개 < 2")
        out[key] = {**{k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()},
                    "verdict": "PASS" if not reasons else "FAIL", "reasons": reasons}
    return {"judge_version": JUDGE_VERSION, "n_tests": n_tests, "t_crit": round(t_crit, 3), "cells": out}
