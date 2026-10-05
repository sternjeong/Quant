"""코인 추세 슬리브 앞으로 기록(shadow) — 2026-10-05 사전 등록, 배분에는 반영하지 않는다.

배경: info-rnd-v1(research/results/info-rnd-v1)에서 'BTC+ETH 를 100일 지수이동평균 위일 때만 보유하는 5% 슬리브(코어에서 떼어 옴)'가
앞 구간(샤프 0.96 vs 현 챔피언 0.67)과 떼어 둔 최근 2년(1.12 vs 1.04) 모두 현 규칙보다 나았지만, 사전 등록상 앞 구간 1위만 판정 대상이라
정식 판정을 받지 못했다. 최근 2년은 이미 봤으므로 남은 정직한 검증은 '지금부터 앞으로'뿐이다.

규칙(고정, crypto-forward/v1):
  - 대상 BTC-USD, ETH-USD. 각 코인은 그날 종가가 100일 지수이동평균(EMA, span=100) 위면 보유, 아니면 그 몫은 단기국채(BIL).
  - 그날 종가로 정하고 다음 거래일부터 수익(엔진 관례). 두 코인에 반씩. 슬리브 = 포트폴리오의 5%, 코어 85% 에서 떼어 온다(코어 80%).
  - 비용 편도 8bp(보유 상태가 바뀔 때).
  - 매일 밤 그날의 보유 상태를 기록한다(data/crypto_shadow/ledger.jsonl). 평가는 기록된 상태만 쓴다 — 나중에 다시 계산하지 않는다.
판정(결과를 보기 전에 고정): 기록 시작(FORWARD_START) 뒤 252거래일(약 12개월)이 쌓이기 전에는 판정하지 않는다(중간 경과만 보고).
  PASS = 현 챔피언 대비 일별 초과수익(0.05 × (슬리브 − 코어))의 연환산 정보비율 ≥ 0.5 이고 누적 초과 > 0.
  PASS 도 '5% 슬리브 도입을 사람이 검토할 후보'일 뿐이다. 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER = PROJECT_ROOT / "data" / "crypto_shadow" / "ledger.jsonl"
JUDGE_VERSION = "crypto-forward/v1"
FORWARD_START = date(2026, 10, 6)
ASSETS = ("BTC-USD", "ETH-USD")
EMA_SPAN = 100
SLEEVE_WEIGHT = 0.05
COST_BPS = 8.0
MIN_DAYS = 252
IR_THRESHOLD = 0.5

PriceFn = Callable[[str], pd.DataFrame]


def _default_prices(ticker: str) -> pd.DataFrame:
    from core.market_data import get_price_history

    return get_price_history(ticker, start="2025-01-01", interval="1d", use_cache=True)


def signal_state(prices: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """가장 최근 종가 기준 각 코인의 보유 여부(종가 > EMA100)."""
    out: dict[str, Any] = {}
    for t in ASSETS:
        df = prices.get(t)
        if df is None or df.empty or len(df) < EMA_SPAN:
            out[t] = {"on": None, "reason": "가격 이력 부족"}
            continue
        c = df["Close"].dropna()
        ema = c.ewm(span=EMA_SPAN, adjust=False).mean()
        out[t] = {"date": str(c.index[-1].date()), "close": float(c.iloc[-1]), "ema100": float(ema.iloc[-1]),
                  "on": bool(c.iloc[-1] > ema.iloc[-1])}
    return out


def load_ledger(path: Optional[Path] = None) -> list[dict]:
    p = Path(path or LEDGER)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def record(*, path: Optional[Path] = None, price_fn: PriceFn = _default_prices, now: Optional[datetime] = None) -> dict:
    """오늘(가장 최근 종가 날짜)의 보유 상태를 한 줄 추가. 같은 날짜가 이미 있으면 그대로 둔다(수정 불가)."""
    now = now or datetime.now(timezone.utc)
    state = signal_state({t: price_fn(t) for t in ASSETS})
    day = max((v.get("date") for v in state.values() if v.get("date")), default=None)
    if day is None:
        return {"recorded": False, "reason": "가격 없음", "state": state}
    rows = load_ledger(path)
    if any(r.get("date") == day for r in rows):
        return {"recorded": False, "reason": "이미 기록됨", "date": day, "state": state}
    row = {"date": day, "recorded_at": now.isoformat(timespec="seconds"), "judge_version": JUDGE_VERSION,
           "assets": {t: {"on": v.get("on"), "close": v.get("close"), "ema100": v.get("ema100")} for t, v in state.items()}}
    p = Path(path or LEDGER)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"recorded": True, "date": day, "state": state}


def evaluate(rows: list[dict], coin_returns: pd.DataFrame, core_returns: pd.Series, cash_returns: pd.Series) -> dict:
    """기록된 상태로 앞으로의 성과를 잰다. coin_returns: 날짜×코인 배당 없는 일간 수익, core_returns: 현 코어 일간 수익(총수익).

    날짜 d 의 기록은 d 종가 기준 결정 → d 다음 거래일 수익에 적용.
    """
    rows = sorted((r for r in rows if r.get("date") and r["date"] >= FORWARD_START.isoformat()), key=lambda r: r["date"])
    if not rows:
        return {"judge_version": JUDGE_VERSION, "days": 0, "verdict": f"판정 전 (0/{MIN_DAYS}거래일)"}
    first, last = pd.Timestamp(rows[0]["date"]), pd.Timestamp(rows[-1]["date"])
    after_last = core_returns.index[core_returns.index > last][:1]  # 마지막 기록의 결정이 적용되는 다음 거래일까지만
    idx = core_returns.index[(core_returns.index > first) & ((core_returns.index <= last) | core_returns.index.isin(after_last))]
    state = pd.DataFrame([{t: float(bool((r["assets"].get(t) or {}).get("on"))) for t in ASSETS} for r in rows],
                         index=pd.to_datetime([r["date"] for r in rows]))
    held = state.reindex(state.index.union(idx)).ffill().shift(1).reindex(idx).fillna(0.0) / len(ASSETS)
    cr = coin_returns.reindex(idx).fillna(0.0)
    cash = cash_returns.reindex(idx).fillna(0.0)
    diff = held.diff()
    if len(diff):
        diff.iloc[0] = held.iloc[0]  # 첫날 진입도 비용
    turn = diff.abs().sum(axis=1)
    sleeve = (held * cr[list(ASSETS)]).sum(axis=1) + (1 - held.sum(axis=1)) * cash - turn * COST_BPS / 1e4
    active = SLEEVE_WEIGHT * (sleeve - core_returns.reindex(idx).fillna(0.0))
    n = len(active)
    cum = float((1 + active).prod() - 1) if n else 0.0
    sd = float(active.std(ddof=1)) if n > 1 else 0.0
    ir = float(active.mean() / sd * math.sqrt(252)) if sd > 0 else None
    out = {"judge_version": JUDGE_VERSION, "days": n, "start": rows[0]["date"], "cumulative_active": cum, "ir": ir,
           "sleeve_cumulative": float((1 + sleeve).prod() - 1) if n else 0.0,
           "current_on": {t: (rows[-1]["assets"].get(t) or {}).get("on") for t in ASSETS}}
    if n < MIN_DAYS:
        out["verdict"] = f"판정 전 ({n}/{MIN_DAYS}거래일)"
    else:
        out["verdict"] = "PASS" if (ir is not None and ir >= IR_THRESHOLD and cum > 0) else "FAIL"
    return out


def evaluate_live(path: Optional[Path] = None) -> dict:
    """VM 데이터로 지금까지의 경과를 계산(주간 엔진 점검·화면용)."""
    from core import champion_strategy as cs
    from core.market_data import get_price_history

    rows = load_ledger(path)
    if not rows:
        return {"judge_version": JUDGE_VERSION, "days": 0, "verdict": f"판정 전 (0/{MIN_DAYS}거래일)", "records": 0}
    core = cs.run_core_backtest(FORWARD_START.isoformat())["ret_net"]
    coins = pd.DataFrame({t: get_price_history(t, start="2026-06-01", interval="1d")["Close"] for t in ASSETS})
    coins = coins.reindex(coins.index.union(core.index)).ffill().reindex(core.index).pct_change(fill_method=None)
    b = get_price_history("BIL", start="2026-06-01", interval="1d")
    cash = (b["Adj Close"] if "Adj Close" in b else b["Close"]).pct_change(fill_method=None)
    out = evaluate(rows, coins, core, cash)
    out["records"] = len(rows)
    return out
