"""앞으로 토너먼트 v4 (2026-11-12 사전 등록, 사용자 요청) — '시장 + 2배 다리 20%' 후보를 실제 원화 적립 계좌로 앞으로 기록하는 원장.

왜: engine-candidate-v1(실제 SSO·정밀 세금 3/3 통과), sleeve-mechanism-v1(200일선은 장기적으로 낙폭 보험), frontier-lev-rebal-v1(끝없이
굴리면 되돌림 필수 — 공제 한도 안 되돌림 통과)은 모두 이미 본 과거 자료다. v1~v3 는 '비중'만 기록해 적립·세금·공제를 담지 못하므로,
여기서는 같은 돈을 넣는 가상 원화 계좌 넷을 매일 한 걸음씩 굴려 그날의 보유·원가·세금을 그대로 남긴다(과거를 다시 계산하지 않는다).

시작(START): v3 와 같다 — 배포 뒤 record() 가 처음 불린 뉴욕 날짜(data/forward_tournament_v4/armed.json) 이상이고 REGISTERED 이상인
첫 완료 미국 거래일. 그날 1,000만 원 + 15만 원을 넣고, 그 뒤 매달 첫 기록 거래일에 15만 원을 넣는다.

계좌(고정 — 바꾸려면 새 id 로 다시 등록):
  B0    SPY 만 산다(기준).
  L20A  SPY 80 + SSO 20. 적립금은 목표보다 모자란 쪽부터 산다(팔지 않음). 매년 12월 첫 기록 거래일에, SSO 가 20% 를 넘는 만큼을
        '그해 남은 양도세 공제(250만 원)' 안에서만 팔아 SPY 를 산다(추가 세금 0, frontier-lev-rebal-v1 A4_ALLOW).
  L20Y  SPY 80 + SSO 20. 적립은 L20A 와 같고, 매년 1월 첫 기록 거래일에 전체를 80/20 으로 되돌린다(세금 냄, engine-candidate-v1 SSO20Y).
  L20F  SPY 80 + 다리 20, 다리 = SSO 또는 BIL. 매달 첫 기록 거래일에 전 거래일 SPY 종가가 200일 평균 × 1.02 위면 SSO, × 0.98 아래면 BIL,
        그 사이면 그대로(START 에도 같은 규칙으로 정한다). 바뀌면 다리 전체를 팔아 바꿔 산다(세금 냄, engine-candidate-v1 SSO20F).
        적립은 모자란 쪽부터.
가격: 배당 포함 가격(Adj Close, 없으면 Close)으로 산다·판다 — 배당 원천징수 15% 는 넣지 않았다(모든 계좌 같은 방향의 근사).
환율: core.tax_fx.usdkrw_series()(FRED DEXKOUS → yfinance KRW=X), 그날 이전 마지막 값.
비용: 사고팔 때마다 0.15%(수수료 0.1% + 환전 0.05%). 취득원가는 원화 이동평균. 양도세 22% × max(0, 그해 실현이익 − 250만 원)을
  판 즉시 현금에서 뺀다(실제 납부는 다음 해 5월 — 보수적 근사). 현금은 이자 없음.
평가: 매일 '오늘 모두 판다면' 세후 금액(청산 세후), 적립 흐름의 IRR(XIRR), 흐름을 뺀 시간가중 수익의 최대낙폭.
판정 forward-tournament/v4 (2026-11-12 고정, 첫 기록 뒤 252거래일 전에는 판정하지 않는다 — 경과만):
  후보(L20A·L20Y·L20F) PASS = 청산 세후 IRR ≥ B0 + 0.5%p 이고 시간가중 최대낙폭이 B0 보다 10%p 넘게 나쁘지 않음.
  1년 앞으로 자료는 검정력이 매우 낮다 — PASS 도 '사람이 도입을 검토할 근거 하나'일 뿐이며 주문·배분 경로와 연결되어 있지 않다.
기록: 매일 밤 forward_tournament_record 잡(00:39 KST)이 v1~v3 뒤에 record() 와 refresh_status() 를 부른다. 원장
  data/forward_tournament_v4/ledger.jsonl 에 처리한 거래일마다 한 줄(빠진 날이 있으면 그 날들을 차례로 처리, 같은 날짜는 다시 쓰지 않음).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

from core import forward_tournament_v2 as ft2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "forward_tournament_v4"
LEDGER = DATA_DIR / "ledger.jsonl"
STATUS = DATA_DIR / "status.json"
ARMED_NAME = "armed.json"
JUDGE_VERSION = "forward-tournament/v4"
REGISTERED = date(2026, 11, 12)
MIN_DAYS = 252
IRR_MARGIN = 0.005
MDD_TOLERANCE = 0.10

LUMP_KRW = 10_000_000.0
MONTHLY_KRW = 150_000.0
TARGET_W = 0.20
COST = 0.0015
CGT = 0.22
ALLOWANCE = 2_500_000.0
SMA_WIN, BAND_UP, BAND_DN = 200, 1.02, 0.98
SPY, SSO, BIL = "SPY", "SSO", "BIL"
TICKERS = (SPY, SSO, BIL)
BASELINE = "B0"
JUDGED = ("L20A", "L20Y", "L20F")
ARMS = (BASELINE,) + JUDGED
LABELS = {"B0": "SPY 만", "L20A": "SPY 80 + SSO 20, 12월 공제 한도 안 되돌림", "L20Y": "SPY 80 + SSO 20, 매년 1월 되돌림",
          "L20F": "SPY 80 + SSO/BIL 20 (200일선)"}

PriceFn = Callable[[list], dict]
FxFn = Callable[[], pd.Series]


# ---------------------------------------------------------------- 시작
def _ny_date(now: datetime) -> date:
    from zoneinfo import ZoneInfo

    return now.astimezone(ZoneInfo("America/New_York")).date()


def load_armed(path: Optional[Path] = None) -> dict:
    p = Path(path or LEDGER).parent / ARMED_NAME
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _arm(path: Path, now: datetime) -> dict:
    got = load_armed(path)
    if got.get("start_not_before"):
        return got
    floor = max(_ny_date(now), REGISTERED)
    got = {"armed_at": now.isoformat(timespec="seconds"), "start_not_before": floor.isoformat(), "judge_version": JUDGE_VERSION}
    p = Path(path).parent / ARMED_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
    return got


def load_ledger(path: Optional[Path] = None) -> list[dict]:
    return ft2.load_ledger(Path(path or LEDGER))


# ---------------------------------------------------------------- 계좌 한 걸음
def new_account() -> dict:
    return {"units": {}, "basis": {}, "cash": 0.0, "year": None, "year_gain": 0.0, "tax_paid": 0.0,
            "contributed": 0.0, "flows": [], "n_sells": 0, "leg": SSO}


def _value(acct: dict, t: str, px: dict, fx: float) -> float:
    return float(acct["units"].get(t, 0.0)) * px[t] * fx


def total_value(acct: dict, px: dict, fx: float) -> float:
    return sum(_value(acct, t, px, fx) for t in acct["units"]) + acct["cash"]


def buy(acct: dict, t: str, krw: float, px: dict, fx: float) -> None:
    krw = min(krw, acct["cash"])
    if krw <= 0:
        return
    acct["units"][t] = acct["units"].get(t, 0.0) + krw * (1 - COST) / (px[t] * fx)
    acct["basis"][t] = acct["basis"].get(t, 0.0) + krw
    acct["cash"] -= krw


def sell(acct: dict, t: str, krw_value: float, px: dict, fx: float) -> float:
    """평가액 krw_value 만큼 판다 → 실현이익. 판 즉시 그해 누적 기준 추가 세금을 현금에서 뺀다."""
    val = _value(acct, t, px, fx)
    krw_value = max(0.0, min(krw_value, val))
    if krw_value <= 0 or val <= 0:
        return 0.0
    frac = krw_value / val
    basis_out = acct["basis"].get(t, 0.0) * frac
    gain = krw_value * (1 - COST) - basis_out
    before = CGT * max(0.0, acct["year_gain"] - ALLOWANCE)
    acct["year_gain"] += gain
    tax = CGT * max(0.0, acct["year_gain"] - ALLOWANCE) - before
    acct["units"][t] *= (1 - frac)
    acct["basis"][t] -= basis_out
    acct["cash"] += krw_value * (1 - COST) - tax
    acct["tax_paid"] += tax
    acct["n_sells"] += 1
    return gain


def allowance_room_value(acct: dict, t: str, px: dict, fx: float) -> float:
    """그해 남은 공제 안에서 실현이익이 딱 차도록 팔 수 있는 평가액(이익이 없으면 0)."""
    val = _value(acct, t, px, fx)
    if val <= 0:
        return 0.0
    rate = 1.0 - acct["basis"].get(t, 0.0) / (val * (1 - COST)) if val > 0 else 0.0
    room = max(0.0, ALLOWANCE - acct["year_gain"])
    return room / ((1 - COST) * rate) if rate > 1e-9 else 0.0


def liquidation(acct: dict, px: dict, fx: float) -> float:
    gain = sum(_value(acct, t, px, fx) * (1 - COST) - acct["basis"].get(t, 0.0) for t in acct["units"])
    gross = sum(_value(acct, t, px, fx) for t in acct["units"])
    tax = CGT * max(0.0, acct["year_gain"] + gain - ALLOWANCE) - CGT * max(0.0, acct["year_gain"] - ALLOWANCE)
    return gross * (1 - COST) - max(0.0, tax) + acct["cash"]


def band_state(spy_level: pd.Series, day: pd.Timestamp, prev_on: bool) -> bool:
    """전 거래일 종가와 그날까지의 200일 평균으로 다리 상태(True = SSO)."""
    hist = spy_level.loc[:day].iloc[:-1]
    if len(hist) < SMA_WIN:
        return prev_on
    c, s = float(hist.iloc[-1]), float(hist.iloc[-SMA_WIN:].mean())
    if c > BAND_UP * s:
        return True
    if c < BAND_DN * s:
        return False
    return prev_on


def step(arm: str, acct: dict, day: pd.Timestamp, px: dict, fx: float, *, first: bool, new_month: bool,
         spy_level: pd.Series) -> list[str]:
    """한 거래일. 순서: 해 바뀜 → (L20F 다리 점검) → 적립 → 정책 매도/매수. 반환: 그날 일어난 일."""
    ev = []
    if acct["year"] != day.year:
        acct["year"], acct["year_gain"] = day.year, 0.0
    if arm == "L20F" and (first or new_month):
        on = band_state(spy_level, day, acct["leg"] == SSO if not first else True)
        want = SSO if on else BIL
        if want != acct["leg"]:
            v = _value(acct, acct["leg"], px, fx)
            if v > 0:
                sell(acct, acct["leg"], v, px, fx)
                buy(acct, want, v * (1 - COST), px, fx)
                ev.append(f"다리 {acct['leg']}→{want}")
            acct["leg"] = want
    if first or new_month:
        amt = MONTHLY_KRW + (LUMP_KRW if first else 0.0)
        acct["cash"] += amt
        acct["contributed"] += amt
        acct["flows"].append([str(day.date()), amt])
        if arm == BASELINE:
            buy(acct, SPY, acct["cash"], px, fx)
        else:
            leg = acct["leg"] if arm == "L20F" else SSO
            tot = total_value(acct, px, fx)
            to_leg = TARGET_W * acct["cash"] if first else min(acct["cash"], max(0.0, TARGET_W * tot - _value(acct, leg, px, fx)))
            buy(acct, leg, to_leg, px, fx)
            buy(acct, SPY, acct["cash"], px, fx)
        ev.append(f"적립 {amt:,.0f}원")
    if arm in ("L20A", "L20Y") and new_month and not first:
        tot = total_value(acct, px, fx)
        over = _value(acct, SSO, px, fx) - TARGET_W * tot
        if arm == "L20A" and day.month == 12 and over > 0:
            g = min(over, allowance_room_value(acct, SSO, px, fx))
            if g > 0:
                cash0 = acct["cash"]
                sell(acct, SSO, g, px, fx)
                buy(acct, SPY, acct["cash"] - cash0, px, fx)
                ev.append(f"공제 안 되돌림 {g:,.0f}원")
        elif arm == "L20Y" and day.month == 1 and abs(over) > 1.0:
            src, dst = (SSO, SPY) if over > 0 else (SPY, SSO)
            cash0 = acct["cash"]
            sell(acct, src, abs(over), px, fx)
            buy(acct, dst, acct["cash"] - cash0, px, fx)
            ev.append(f"연초 되돌림 {src}→{dst} {abs(over):,.0f}원")
    return ev


def snapshot(acct: dict, px: dict, fx: float) -> dict:
    v = total_value(acct, px, fx)
    w = {t: _value(acct, t, px, fx) / v for t in acct["units"] if v > 0 and acct["units"].get(t, 0) > 0}
    return {"value_krw": v, "liq_krw": liquidation(acct, px, fx), "weights": w}


# ---------------------------------------------------------------- 기록
def _default_fx_fn() -> pd.Series:
    from core import tax_fx as tx

    return tx.usdkrw_series()


def _fx_on(fx: pd.Series, day: pd.Timestamp) -> Optional[float]:
    s = fx.loc[:day].dropna()
    return float(s.iloc[-1]) if len(s) else None


def record(*, path: Optional[Path] = None, price_fn: Optional[PriceFn] = None, fx_fn: Optional[FxFn] = None,
           now: Optional[datetime] = None) -> dict:
    """원장 마지막 날 다음부터 마지막 완료 거래일까지 차례로 처리해 한 줄씩 추가."""
    now = now or datetime.now(timezone.utc)
    p = Path(path or LEDGER)
    armed = _arm(p, now)
    floor = date.fromisoformat(armed["start_not_before"])
    rows = load_ledger(p)
    hist = (price_fn or ft2._default_price_fn)(list(TICKERS))
    _price, total = ft2._frames(hist, list(TICKERS))
    missing = [t for t in TICKERS if t not in total]
    if missing:
        return {"recorded": False, "date": None, "reason": f"가격 없음: {missing}"}
    total = total[list(TICKERS)].dropna()
    days = ft2._completed(total.index, now)
    fx = (fx_fn or _default_fx_fn)()
    fx.index = pd.DatetimeIndex(fx.index).tz_localize(None) if getattr(fx.index, "tz", None) else pd.DatetimeIndex(fx.index)
    prev = rows[-1] if rows else None
    last = pd.Timestamp(prev["date"]) if prev else None
    todo = [d for d in days if (d > last if last is not None else d.date() >= floor)]
    if not todo:
        return {"recorded": False, "date": str(days[-1].date()) if len(days) else None,
                "reason": "이미 기록됨" if prev else f"시작 전({floor} 이후 첫 완료 거래일부터)"}
    accts = {a: json.loads(json.dumps((prev or {}).get("accounts", {}).get(a) or new_account())) for a in ARMS}
    spy_level = total[SPY]
    written = []
    with open(p, "a", encoding="utf-8") as f:
        for day in todo:
            rate = _fx_on(fx, day)
            if rate is None:
                break
            px = {t: float(total.at[day, t]) for t in TICKERS}
            first = prev is None and not written
            prev_day = pd.Timestamp(prev["date"]) if prev else None
            if written:
                prev_day = pd.Timestamp(written[-1])
            new_month = first or (prev_day is not None and (prev_day.year, prev_day.month) != (day.year, day.month))
            events = {a: step(a, accts[a], day, px, rate, first=first, new_month=new_month, spy_level=spy_level) for a in ARMS}
            line = {"date": str(day.date()), "fx": rate, "prices": px, "events": {a: e for a, e in events.items() if e},
                    "snap": {a: snapshot(accts[a], px, rate) for a in ARMS}, "accounts": accts, "judge_version": JUDGE_VERSION}
            f.write(json.dumps(line, ensure_ascii=False, default=float) + "\n")
            written.append(str(day.date()))
    if not written:
        return {"recorded": False, "date": str(todo[0].date()), "reason": "환율 없음"}
    return {"recorded": True, "date": written[-1], "days": len(written), "reason": f"{len(written)}일 처리"}


# ---------------------------------------------------------------- 평가
def _xirr(flows: list, end: str, terminal: float) -> Optional[float]:
    from core import tax_fx as tx

    cf = [(pd.Timestamp(d), -float(a)) for d, a in flows] + [(pd.Timestamp(end), float(terminal))]
    try:
        v = tx.xirr(cf)
        return float(v) if v is not None and math.isfinite(v) else None
    except Exception:  # noqa: BLE001
        return None


def twr_series(rows: list[dict], arm: str) -> pd.Series:
    """흐름(적립)을 뺀 일별 수익: (오늘 평가 − 오늘 넣은 돈) / 어제 평가 − 1."""
    out, prev_v = {}, None
    for r in rows:
        v = r["snap"][arm]["value_krw"]
        inflow = sum(a for d, a in r["accounts"][arm]["flows"] if d == r["date"])
        if prev_v:
            out[pd.Timestamp(r["date"])] = (v - inflow) / prev_v - 1
        prev_v = v
    return pd.Series(out, dtype=float)


def evaluate(rows: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {"judge_version": JUDGE_VERSION, "days": len(rows), "min_days": MIN_DAYS, "candidates": {}}
    if not rows:
        return out
    last = rows[-1]
    out.update({"start": rows[0]["date"], "last": last["date"]})
    for a in ARMS:
        acct, snap = last["accounts"][a], last["snap"][a]
        tw = twr_series(rows, a)
        out["candidates"][a] = {"label": LABELS[a], "value_krw": snap["value_krw"], "liq_krw": snap["liq_krw"],
                                "contributed": acct["contributed"], "tax_paid": acct["tax_paid"], "n_sells": acct["n_sells"],
                                "weights": snap["weights"], "irr": _xirr(acct["flows"], last["date"], snap["liq_krw"]) if len(rows) > 20 else None,
                                "twr_cum": float((1 + tw).prod() - 1) if len(tw) else 0.0, "mdd": ft2._mdd(tw)}
    b = out["candidates"][BASELINE]
    ready = len(rows) >= MIN_DAYS
    for a in JUDGED:
        c = out["candidates"][a]
        c["liq_vs_b0_krw"] = c["liq_krw"] - b["liq_krw"]
        c["mdd_gap"] = c["mdd"] - b["mdd"]
        if c["irr"] is not None and b["irr"] is not None:
            c["irr_gap"] = c["irr"] - b["irr"]
        if ready:
            ok = c.get("irr_gap") is not None and c["irr_gap"] >= IRR_MARGIN and c["mdd_gap"] >= -MDD_TOLERANCE
            c["verdict"] = "PASS" if ok else "FAIL"
    out["verdict"] = "JUDGED" if ready else "IN_PROGRESS"
    return out


def refresh_status(path: Optional[Path] = None, status_path: Optional[Path] = None, now: Optional[datetime] = None) -> dict:
    rows = load_ledger(path)
    ev = evaluate(rows)
    ev["records"] = len(rows)
    ev["updated_at"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    p = Path(status_path or STATUS)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".status.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, default=float)
    os.replace(tmp, p)
    return ev


def load_status(status_path: Optional[Path] = None) -> dict:
    try:
        return json.loads(Path(status_path or STATUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    print(json.dumps(record(), ensure_ascii=False))
    print(json.dumps(refresh_status(), ensure_ascii=False, default=float)[:2000])
