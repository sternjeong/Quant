"""앞으로 토너먼트 (2026-10-05 사전 등록, 사용자 요청) — 과거 데이터 과적합에서 벗어나기 위해, 아깝게 떨어진 후보들을
현 코어와 나란히 '앞으로' 가상 운용하며 매일 기록하고 미리 정한 규칙으로 판정한다. 배분에 반영하지 않는다.

왜: 같은 과거 데이터(특히 떼어 둔 최근 2년)를 수십 번 판정에 썼다. 남은 정직한 시험대는 아직 오지 않은 데이터뿐이다.

후보(고정 — 바꾸려면 새 토너먼트로 다시 등록):
  T0 현 코어(기준선) · T1 비트코인 18번째 자산(info-rnd-v1 B1) · T2 9개월 모멘텀 5종목(sprint F2 앞 구간 1위)
  T3 3~12개월 혼합·상관 0.8 제한·6위 완충(sprint F2 3위, 최근 2년도 양호) · T4 4분할 시차 리밸런싱(core-rnd-v2 C02)
  T5 코어 + 코인 추세 5%(info-rnd-v1 B2; 코어 80/85 + BTC·ETH EMA100 위 보유 5/85 — 코어 100% 기준으로 환산)
  B1 SPY 그냥 보유 · B2 60/40(SPY 60 + IEF 40, 매일 같은 비중으로 보는 근사 — 비용 없음)
기록: 매일 밤(00:39 KST) 그날 종가까지의 데이터로 각 후보의 목표 비중을 계산해 원장(data/forward_tournament/ledger.jsonl)에 한 줄.
평가: 기록된 비중을 다음 거래일부터 배당 포함 수익에 곱한다(나중에 다시 계산하지 않음). 비중이 바뀐 만큼 편도 3bp(코인 8bp).
판정 forward-tournament/v1: 첫 기록 뒤 252거래일 전에는 판정하지 않는다(순위·경과만). 252거래일 이후 후보마다
  PASS = T0 대비 일별 초과수익의 연환산 정보비율 ≥ 0.5 이고 누적 초과 > 0 이고 최대낙폭이 T0 보다 5%p 넘게 나쁘지 않음.
  PASS 도 '사람이 도입을 검토할 후보'일 뿐이다. 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER = PROJECT_ROOT / "data" / "forward_tournament" / "ledger.jsonl"
JUDGE_VERSION = "forward-tournament/v1"
START = date(2026, 10, 6)
MIN_DAYS = 252
IR_THRESHOLD = 0.5
MDD_TOLERANCE = 0.05
COST_BPS = 3.0
CRYPTO_COST_BPS = 8.0
CRYPTO = ("BTC-USD", "ETH-USD")

CANDIDATES: dict[str, dict[str, Any]] = {
    "T0": {"label": "현 코어(기준선)", "kind": "core", "config": {}},
    "T1": {"label": "비트코인 18번째 자산", "kind": "core", "config": {"extra_assets": ["BTC-USD"]}},
    "T2": {"label": "9개월 모멘텀 5종목", "kind": "core", "config": {"lookbacks": [189], "top_n": 5}},
    "T3": {"label": "3~12개월 혼합·상관 제한·순위 완충", "kind": "core",
           "config": {"lookbacks": [63, 126, 189, 252], "corr_cap": 0.8, "buffer_n": 6}},
    "T4": {"label": "4분할 시차 리밸런싱", "kind": "core", "config": {"tranches": 4}},
    "T5": {"label": "코어 + 코인 추세 5%", "kind": "core_crypto", "config": {}},
    "B1": {"label": "SPY 그냥 보유", "kind": "fixed", "weights": {"SPY": 1.0}},
    "B2": {"label": "60/40 (SPY·IEF)", "kind": "fixed", "weights": {"SPY": 0.6, "IEF": 0.4}},
}


# ---------------------------------------------------------------- 목표 비중 계산
def load_prices(price_fn: Optional[Callable] = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(주식 거래일 기준 가격 closes, 배당 포함 total, 코인 가격 crypto). 코인은 주식 거래일에 맞춰 직전 값."""
    from core import champion_strategy as cs

    tickers = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    if price_fn is None:
        from core.market_data import get_multiple_price_history

        hist = get_multiple_price_history(tickers + list(CRYPTO), start="2023-01-01", end=None, interval="1d")
    else:
        hist = price_fn(tickers + list(CRYPTO))
    stock = [t for t in tickers if t in hist and not hist[t].empty]
    price = cs._closes_from_histories(hist, stock)
    total = cs._closes_from_histories(hist, stock, field=cs.CORE_PRICE_FIELD)
    days = price.index
    crypto = pd.DataFrame({t: hist[t]["Close"].reindex(days.union(hist[t].index)).ffill().reindex(days)
                           for t in CRYPTO if t in hist and not hist[t].empty})
    return price, total, crypto


def target_weights(price: pd.DataFrame, crypto: pd.DataFrame) -> dict[str, dict[str, float]]:
    """오늘(마지막 날) 후보별 목표 비중. 코어 엔진(core_lab)과 같은 계산 — 신호는 가격, 남는 몫 BIL."""
    from core import champion_strategy as cs
    from core import core_lab as cl

    core_cols = [t for t in cs.CORE_UNIVERSE if t in price.columns]
    extra = price[[c for c in (cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF) if c in price.columns]]
    out: dict[str, dict[str, float]] = {}
    for cid, c in CANDIDATES.items():
        if c["kind"] == "fixed":
            out[cid] = dict(c["weights"])
            continue
        closes = price[core_cols]
        cfg_over = dict(c["config"])
        if "extra_assets" in cfg_over:
            closes = closes.copy()
            for t in cfg_over["extra_assets"]:
                if t in crypto.columns:
                    closes[t] = crypto[t]
            cfg_over["extra_assets"] = tuple(cfg_over["extra_assets"])
        cfg = cl.with_changes(cl.CoreConfig(cash="bil"), **cfg_over)
        w = cl.build_weights(closes, extra, cfg).iloc[-1]
        wd = {t: float(v) for t, v in w.items() if v > 1e-9}
        if c["kind"] == "core_crypto":
            scale = 0.80 / 0.85
            wd = {t: v * scale for t, v in wd.items()}
            sleeve = 0.05 / 0.85
            on = [t for t in CRYPTO if t in crypto.columns and _above_ema(crypto[t])]
            for t in on:
                wd[t] = wd.get(t, 0.0) + sleeve / len(CRYPTO)
            wd[cs.CORE_CASH_ETF] = wd.get(cs.CORE_CASH_ETF, 0.0) + sleeve * (len(CRYPTO) - len(on)) / len(CRYPTO)
        out[cid] = wd
    return out


def _above_ema(c: pd.Series, span: int = 100) -> bool:
    c = c.dropna()
    if len(c) < span:
        return False
    return bool(c.iloc[-1] > c.ewm(span=span, adjust=False).mean().iloc[-1])


# ---------------------------------------------------------------- 원장
def load_ledger(path: Optional[Path] = None) -> list[dict]:
    p = Path(path or LEDGER)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def record(*, path: Optional[Path] = None, price_fn: Optional[Callable] = None, now: Optional[datetime] = None) -> dict:
    """오늘(마지막 주식 거래일)의 후보별 목표 비중을 한 줄 추가. 같은 날짜는 다시 쓰지 않는다."""
    price, _total, crypto = load_prices(price_fn)
    day = str(price.index[-1].date())
    rows = load_ledger(path)
    if any(r.get("date") == day for r in rows):
        return {"recorded": False, "date": day, "reason": "이미 기록됨"}
    weights = target_weights(price, crypto)
    row = {"date": day, "recorded_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
           "judge_version": JUDGE_VERSION, "weights": weights}
    p = Path(path or LEDGER)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"recorded": True, "date": day}


# ---------------------------------------------------------------- 평가
def _series_from_ledger(rows: list[dict], cid: str, returns: pd.DataFrame) -> pd.Series:
    """기록된 비중(날짜 d 종가 결정)을 d 다음 거래일 수익부터 적용. 비중 변화만큼 비용."""
    recs = [(pd.Timestamp(r["date"]), r["weights"].get(cid) or {}) for r in rows if cid in (r.get("weights") or {})]
    if not recs:
        return pd.Series(dtype=float)
    first, last = recs[0][0], recs[-1][0]
    after_last = returns.index[returns.index > last][:1]
    idx = returns.index[(returns.index > first) & ((returns.index <= last) | returns.index.isin(after_last))]
    cols = sorted({t for _, w in recs for t in w})
    wdf = pd.DataFrame([{t: w.get(t, 0.0) for t in cols} for _, w in recs], index=[d for d, _ in recs])
    held = wdf.reindex(wdf.index.union(idx)).ffill().shift(1).reindex(idx).fillna(0.0)
    r = returns.reindex(index=idx, columns=cols).fillna(0.0)
    diff = held.diff()
    if len(diff):
        diff.iloc[0] = held.iloc[0]
    cost = sum(diff[t].abs() * (CRYPTO_COST_BPS if t in CRYPTO else COST_BPS) / 1e4 for t in cols)
    return (held * r).sum(axis=1) - cost


def evaluate(rows: list[dict], returns: pd.DataFrame) -> dict[str, Any]:
    rows = sorted((r for r in rows if r.get("date", "") >= START.isoformat()), key=lambda r: r["date"])
    series = {cid: _series_from_ledger(rows, cid, returns) for cid in CANDIDATES}
    base = series.get("T0", pd.Series(dtype=float))
    n = len(base)
    out: dict[str, Any] = {"judge_version": JUDGE_VERSION, "days": n, "start": rows[0]["date"] if rows else None, "candidates": {}}

    def mdd(s: pd.Series) -> float:
        if s.empty:
            return 0.0
        eq = (1 + s).cumprod()
        return float((eq / eq.cummax() - 1).min())

    for cid, s in series.items():
        if s.empty:
            out["candidates"][cid] = {"label": CANDIDATES[cid]["label"], "days": 0}
            continue
        cum = float((1 + s).prod() - 1)
        act = (s - base.reindex(s.index).fillna(0.0)) if cid != "T0" else s * 0
        sd = float(act.std(ddof=1)) if len(act) > 1 else 0.0
        ir = float(act.mean() / sd * math.sqrt(252)) if sd > 0 else None
        row = {"label": CANDIDATES[cid]["label"], "days": len(s), "cumulative": cum, "mdd": mdd(s),
               "excess_vs_T0": float((1 + act).prod() - 1) if cid != "T0" else 0.0, "ir_vs_T0": ir}
        if cid == "T0":
            row["verdict"] = "기준선"
        elif n < MIN_DAYS:
            row["verdict"] = f"판정 전 ({n}/{MIN_DAYS}거래일)"
        else:
            ok = ir is not None and ir >= IR_THRESHOLD and row["excess_vs_T0"] > 0 and row["mdd"] >= mdd(base) - MDD_TOLERANCE
            row["verdict"] = "PASS" if ok else "FAIL"
        out["candidates"][cid] = row
    return out


def evaluate_live(path: Optional[Path] = None) -> dict[str, Any]:
    rows = load_ledger(path)
    if not rows:
        return {"judge_version": JUDGE_VERSION, "days": 0, "candidates": {}, "records": 0}
    price, total, crypto = load_prices()
    rets = total.pct_change(fill_method=None)
    for t in crypto.columns:
        rets[t] = crypto[t].pct_change(fill_method=None)
    out = evaluate(rows, rets)
    out["records"] = len(rows)
    return out
