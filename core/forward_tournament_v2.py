"""앞으로 토너먼트 v2 (2026-10-10 사전 등록, 사용자 승인) — 채택 판단을 '아직 오지 않은 데이터'로 하기 위한 두 번째 전진 원장.

왜: 2024-10 이후 떼어 둔 구간은 20개 넘는 연구가 이미 봤다(docs/RESEARCH_JOBS.md '판정 설계 규칙' 3). v1(core/forward_tournament.py)은
2026-10-05 에 후보·판정을 고정했으므로 바꾸지 않고, 그 뒤 나온 후보(위험조정 블렌드·거장 우선 새틀라이트)는 여기서 따로 기록한다.

후보(고정 — 바꾸려면 새 id 로 다시 등록):
  B0 SPY 그냥 보유 · B1 현 코어(core_lab 기본·BIL 현금, 등록 당시 라이브 코어 16자산 — DBC 는 2026-10-08 라이브에서 빠짐)
  C1 SPY 50% + ERC 코어 50%(주 후보, 비율은 synthesis-rnd-v2 와 같이 미리 고정)
  C2 SPY 30% + ERC 코어 70%(synthesis-rnd-v1 의 사후 관찰 최고 — 참고용)
     ERC 코어 = B1 과 같은 선정, 비중만 위험 균등 기여(core_lab weighting="erc"). 코어 안쪽 비중은 v1 처럼 매일 다시 계산한다.
     두 소매(SPY·ERC 코어)의 비율은 매년 첫 기록일(첫 거래일)에만 목표 비율로 되돌리고, 그 사이에는 기록된 비중 × 수익으로 표류시킨다.
  S0 현 새틀라이트 규칙(S-SEED-000) — 라이브 엔진과 같은 후보 풀(그날 기준 섹터 균등 시총 상위 40, champion_strategy._pick_satellite_at_date)
  S1 거장 보유 우선(S-SEED-019) — 그 시점 S&P500 전체(sp500_pit)
     첫 기록일과 그 뒤 6개월마다 상위 3종목을 동일가중으로 고르고, 그 사이에는 고른 종목을 그대로 들고 있는다(매일 다시 고르지 않음,
     비중은 수익에 따라 표류). 신호는 새틀라이트 R&D 의 동결된 신호 코드(해시 고정)·풀 코드로 기록일 종가까지의 가격만 보고,
     거장 13F 는 기록일 전날까지 공시된 것만 본다.
기록: 매일 밤 forward_tournament_record 잡(00:39 KST)이 v1 기록 직후 이 모듈의 record() 를 부른다. 원장 data/forward_tournament_v2/ledger.jsonl
  에 주식 거래일마다 한 줄(같은 날짜는 다시 쓰지 않음). 아직 끝나지 않은 미국 정규장의 봉은 쓰지 않는다(마지막 완료 거래일 기준).
평가: 기록된 비중을 다음 거래일 배당 포함 수익에 곱한다. 기록이 빠진 날은 직전 비중이 수익에 따라 표류한 것으로 본다.
  새 기록 비중으로 옮겨 가는 만큼(표류한 비중과의 차이) 편도 비용 — ETF 3bp, 새틀라이트 개별 종목 8bp.
판정 forward-tournament/v2 (첫 기록 뒤 252거래일 전에는 판정하지 않는다 — 순위·경과만):
  블렌드 C1·C2 — PASS = 샤프(BIL 초과) > B0 샤프 이고 최대낙폭이 B0 보다 5%p 이상 얕고 연환산 수익/|최대낙폭| 이 B0·B1 둘 다보다 큼.
  새틀라이트 S1 — PASS = S0 대비 일별 초과의 연환산 정보비율 ≥ 0.5 이고 누적 초과 > 0 이고 최대낙폭이 S0 보다 5%p 넘게 나쁘지 않음.
  후보가 기준과 매일 똑같으면 FAIL 대신 NOT_EVALUABLE(core/research_power.noop_guard).
  PASS 도 '사람이 도입을 검토할 후보'일 뿐이다. 주문·배분 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "forward_tournament_v2"
LEDGER = DATA_DIR / "ledger.jsonl"
STATUS = DATA_DIR / "status.json"   # 매일 기록 뒤 계산한 경과(관제 센터가 네트워크 없이 읽는다)
JUDGE_VERSION = "forward-tournament/v2"
START = date(2026, 10, 12)          # 첫 기록일 = 이 날짜 이후 첫 주식 거래일
MIN_DAYS = 252
# --- 판정 기준 (forward-tournament/v2, 2026-10-10 고정) ---
BLEND_MDD_MARGIN = 0.05             # 블렌드 최대낙폭이 B0 보다 5%p 이상 얕아야
SAT_IR_THRESHOLD = 0.5
SAT_MDD_TOLERANCE = 0.05
COST_BPS = 3.0                      # ETF 편도(코어 CORE_COST_BPS_PER_SIDE 와 같은 값으로 고정)
SAT_COST_BPS = 8.0                  # 새틀라이트 개별 종목 편도(SATELLITE_COST_BPS_PER_SIDE 와 같은 값으로 고정)
SAT_TOP_K = 3
SAT_HOLD_MONTHS = 6
SPY, BIL = "SPY", "BIL"
# 등록 당시(2026-10-10) 라이브 코어 유니버스 — 이후 라이브가 바뀌어도 v2 는 이것을 쓴다
CORE_UNIVERSE_V2 = ("XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU",
                    "TLT", "IEF", "GLD", "EFA", "HYG")
SEEDS_DIR = PROJECT_ROOT / "research" / "satellite_lab" / "seeds"
SIGNAL_SHA = {  # 새틀라이트 R&D 등록부에 동결된 신호 코드 해시 — 다르면 기록하지 않는다
    "S-SEED-000": "de04d12ae636dfcb71987bdfdaccf445fec9ef6ba4980635d3b21d372eeb42f3",
    "S-SEED-019": "4457d95fa02be43699b8809fa47e88576ba80bf7380aa3e64bfc309c014d525a",
}

CANDIDATES: dict[str, dict[str, Any]] = {
    "B0": {"label": "SPY 그냥 보유", "kind": "fixed", "weights": {SPY: 1.0}},
    "B1": {"label": "현 코어", "kind": "core", "config": {}},
    "C1": {"label": "SPY 50% + ERC 코어 50%(주 후보)", "kind": "blend", "spy": 0.50},
    "C2": {"label": "SPY 30% + ERC 코어 70%(사후 관찰 최고(synthesis-rnd-v1), 참고)", "kind": "blend", "spy": 0.30},
    "S0": {"label": "현 새틀라이트 규칙(S-SEED-000)", "kind": "satellite", "seed": "S-SEED-000", "pool": "live40"},
    "S1": {"label": "거장 보유 우선·S&P500 전체(S-SEED-019)", "kind": "satellite", "seed": "S-SEED-019", "pool": "sp500_pit"},
}
BLENDS = ("C1", "C2")
SATELLITES = ("S0", "S1")

PriceFn = Callable[[list[str]], dict[str, pd.DataFrame]]
PoolFn = Callable[[str, date], list[str]]


# ---------------------------------------------------------------- 가격
def _default_price_fn(tickers: list[str]) -> dict[str, pd.DataFrame]:
    from core.market_data import get_multiple_price_history

    return get_multiple_price_history(sorted(set(tickers)), start="2023-01-01", end=None, interval="1d")


def _frames(hist: dict[str, pd.DataFrame], tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(가격 Close, 배당 포함 Adj Close — 없으면 Close). 열은 이력이 있는 종목만."""
    price, total = {}, {}
    for t in tickers:
        df = hist.get(t)
        if df is None or df.empty or "Close" not in df:
            continue
        idx = pd.DatetimeIndex(df.index).tz_localize(None).normalize() if getattr(df.index, "tz", None) else pd.DatetimeIndex(df.index).normalize()
        c = pd.Series(df["Close"].to_numpy(dtype=float), index=idx)
        a = df["Adj Close"] if "Adj Close" in df and df["Adj Close"].notna().any() else df["Close"]
        price[t] = c[~c.index.duplicated(keep="last")]
        ta = pd.Series(a.to_numpy(dtype=float), index=idx)
        total[t] = ta[~ta.index.duplicated(keep="last")]
    return pd.DataFrame(price).sort_index(), pd.DataFrame(total).sort_index()


def _completed(index: pd.DatetimeIndex, now: datetime) -> pd.DatetimeIndex:
    """아직 끝나지 않은 미국 정규장 봉(뉴욕 날짜 = 마지막 날짜, 16:15 전)은 뺀다."""
    from zoneinfo import ZoneInfo

    ny = now.astimezone(ZoneInfo("America/New_York"))
    if len(index) and index[-1].date() >= ny.date() and (ny.hour, ny.minute) < (16, 15):
        return index[index.date < ny.date()]
    return index


# ---------------------------------------------------------------- 비중 계산
def drift(w: dict[str, float], r: dict[str, float]) -> dict[str, float]:
    """하루 수익 r 뒤의 비중(합이 1 보다 작으면 나머지는 수익 0 현금). 수익 결측은 0."""
    def rr(t: str) -> float:
        v = r.get(t)
        return float(v) if v is not None and math.isfinite(float(v)) else 0.0

    growth = 1.0 + sum(v * rr(t) for t, v in w.items())
    if growth <= 0:
        return {t: 0.0 for t in w}
    return {t: v * (1.0 + rr(t)) / growth for t, v in w.items()}


def _drift_path(w: dict[str, float], rets: pd.DataFrame) -> tuple[dict[str, float], float]:
    """여러 날 표류 → (마지막 비중, 그 기간 포트폴리오 성장 배수)."""
    g = 1.0
    for _, row in rets.iterrows():
        r = row.to_dict()
        g *= 1.0 + sum(v * (float(r[t]) if t in r and pd.notna(r[t]) else 0.0) for t, v in w.items())
        w = drift(w, r)
    return w, g


def core_targets(price: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    """(B1 현 코어, ERC 코어)의 오늘(마지막 날) 목표 비중. 신호는 가격, 남는 몫 BIL — v1 T0 와 같은 계산."""
    from core import core_lab as cl

    cols = [t for t in CORE_UNIVERSE_V2 if t in price.columns]
    extra = price[[c for c in (SPY, BIL) if c in price.columns]]
    base = cl.CoreConfig(cash="bil", universe=CORE_UNIVERSE_V2)
    out = []
    for cfg in (base, cl.with_changes(base, weighting="erc")):
        w = cl.build_weights(price[cols], extra, cfg).iloc[-1]
        out.append({t: float(v) for t, v in w.items() if v > 1e-9})
    return out[0], out[1]


def _default_pool_fn(pool: str, d: date) -> list[str]:
    from core import satellite_lab as sl
    from core.champion_strategy import CORE_UNIVERSE, MARKET_FILTER_TICKER

    if pool == "live40":  # 라이브 엔진(_pick_satellite_at_date)과 같은 호출
        from core.strategy_tuning import sample_universe

        df = sample_universe(n=sl.CHAMPION_POOL_N, as_of_date=d.isoformat(), use_point_in_time_market_cap=True, use_cache=True)
        exclude = set(CORE_UNIVERSE) | {MARKET_FILTER_TICKER}
        return [t for t in df["ticker"].tolist() if t not in exclude]
    return sl.default_pool_provider()(pool, d)


def _default_sat_price_fn(tickers: list[str], day: date) -> dict[str, pd.DataFrame]:
    from core import hypothesis_engine as he
    from core import satellite_lab as sl

    return he.load_prices(sorted(set(tickers)), day - timedelta(days=sl.LOOKBACK_CALENDAR_DAYS + 30), day)


def pick_satellite(cid: str, day: pd.Timestamp, *, pool_fn: PoolFn, sat_price_fn: Callable, guru_store: Any = None) -> dict:
    """새틀라이트 R&D 의 동결 신호·풀 코드로 기록일(day) 종가 기준 상위 SAT_TOP_K 종목."""
    from core import satellite_lab as sl

    c = CANDIDATES[cid]
    spec, code = sl.read_variant_dir(SEEDS_DIR / c["seed"])
    if sl.sha(code) != SIGNAL_SHA[c["seed"]]:
        raise RuntimeError(f"{c['seed']} 신호 코드가 등록 당시와 다름 — 기록 중단")
    signal = sl.load_signal(code)
    members = list(pool_fn(c["pool"], day.date()))
    hist = sat_price_fn(members, day.date())
    data = sl.LabData(trading_days=pd.DatetimeIndex([day]), ohlcv={t: df for t, df in hist.items()},
                      closes=pd.DataFrame(index=[day]))
    if "guru13f" in (spec.get("data") or []):
        data.guru = guru_store if guru_store is not None else _default_guru_store()
    prices = sl._signal_prices(data, members, day, day)
    eligible = {t for t, df in prices.items() if len(df) and pd.Timestamp(df.index[-1]).normalize() == day
                and pd.notna(df["Close"].iloc[-1])}
    # 가격은 기록일 종가까지, 신호의 as_of·거장 공시는 기록일 전날까지(그날 공시는 쓰지 않는다)
    asof = pd.Timestamp(day.date() - timedelta(days=1))
    scores = sl._call_signal(signal, spec, data, {t: prices[t] for t in eligible}, asof, spec["signal"]["params_grid"][0])
    picks = sl.pick_top(scores, SAT_TOP_K, eligible)
    return {"picks": picks, "pool_size": len(members), "eligible": len(eligible), "signal_sha": SIGNAL_SHA[c["seed"]]}


def _default_guru_store():
    import time

    from core import guru_history as gh

    store = gh.Store(fetch=True)
    store.prefetch(deadline=time.time() + 300)
    return store


def _sat_due(prev_sat: Optional[dict], day: pd.Timestamp) -> bool:
    if not prev_sat or not prev_sat.get("rebalanced"):
        return True
    return day >= pd.Timestamp(prev_sat["rebalanced"]) + pd.DateOffset(months=SAT_HOLD_MONTHS)


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


def record(*, path: Optional[Path] = None, price_fn: Optional[PriceFn] = None, pool_fn: Optional[PoolFn] = None,
           sat_price_fn: Optional[Callable] = None, guru_store: Any = None, now: Optional[datetime] = None) -> dict:
    """마지막으로 끝난 주식 거래일의 후보별 비중을 한 줄 추가. 같은 날짜는 다시 쓰지 않는다.

    새틀라이트 종목 선정이 실패하면 그 후보만 직전 보유를 표류시키고(첫 선정이면 빠짐) errors 에 남긴다 — 다음 기록일에 다시 고른다.
    """
    now = now or datetime.now(timezone.utc)
    rows = load_ledger(path)
    prev = rows[-1] if rows else None
    held = sorted({t for cid in SATELLITES for t in ((prev or {}).get("weights", {}).get(cid) or {})})
    core_tickers = list(CORE_UNIVERSE_V2) + [SPY, BIL]
    hist = (price_fn or _default_price_fn)(core_tickers + held)
    price, total = _frames(hist, core_tickers + held)
    days = _completed(price.index, now)
    if not len(days):
        return {"recorded": False, "date": None, "reason": "완료된 거래일 없음"}
    day = days[-1]
    dstr = str(day.date())
    if day.date() < START:
        return {"recorded": False, "date": dstr, "reason": f"시작 전({START} 이후 첫 거래일부터)"}
    if any(r.get("date") == dstr for r in rows):
        return {"recorded": False, "date": dstr, "reason": "이미 기록됨"}
    if prev and prev.get("date", "") > dstr:
        return {"recorded": False, "date": dstr, "reason": f"원장 마지막({prev['date']})보다 이른 날짜"}
    price, total = price.loc[:day], total.loc[:day]
    rets = total.pct_change(fill_method=None)
    gap = rets.loc[rets.index > pd.Timestamp(prev["date"])] if prev else rets.iloc[0:0]

    b1, erc = core_targets(price)
    weights: dict[str, dict[str, float]] = {"B0": {SPY: 1.0}, "B1": b1}
    sleeves: dict[str, float] = {}
    new_year = prev is None or pd.Timestamp(prev["date"]).year != day.year
    for cid in BLENDS:
        target = CANDIDATES[cid]["spy"]
        s_prev = ((prev or {}).get("sleeves") or {}).get(cid)
        erc_prev = ((prev or {}).get("components") or {}).get("ERC")
        if new_year or s_prev is None or erc_prev is None:
            s = target                                   # 첫 기록·매년 첫 거래일에만 목표 비율로
        else:
            _, g_core = _drift_path(dict(erc_prev), gap)
            _, g_spy = _drift_path({SPY: 1.0}, gap)
            s = s_prev * g_spy / (s_prev * g_spy + (1 - s_prev) * g_core)
        sleeves[cid] = s
        w = {t: (1 - s) * v for t, v in erc.items()}
        w[SPY] = w.get(SPY, 0.0) + s
        weights[cid] = w

    satellite: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for cid in SATELLITES:
        prev_sat = ((prev or {}).get("satellite") or {}).get(cid)
        prev_w = ((prev or {}).get("weights") or {}).get(cid)
        if _sat_due(prev_sat if prev_w is not None else None, day):
            try:
                info = pick_satellite(cid, day, pool_fn=pool_fn or _default_pool_fn,
                                      sat_price_fn=sat_price_fn or _default_sat_price_fn, guru_store=guru_store)
                weights[cid] = {t: 1.0 / SAT_TOP_K for t in info["picks"]}   # 못 채운 칸은 현금
                satellite[cid] = {"picks": info["picks"], "rebalanced": dstr, "pool_size": info["pool_size"],
                                  "eligible": info["eligible"], "signal_sha": info["signal_sha"]}
                continue
            except Exception as exc:  # noqa: BLE001 - 다른 후보 기록은 계속
                errors[cid] = f"{type(exc).__name__}: {exc}"
        if prev_w is not None:
            w, _ = _drift_path(dict(prev_w), gap)
            weights[cid] = {t: v for t, v in w.items()}
            satellite[cid] = dict(prev_sat or {})

    row = {"date": dstr, "recorded_at": now.isoformat(timespec="seconds"), "judge_version": JUDGE_VERSION,
           "weights": weights, "sleeves": sleeves, "components": {"ERC": erc}, "satellite": satellite}
    if errors:
        row["errors"] = errors
    p = Path(path or LEDGER)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"recorded": True, "date": dstr, "errors": errors}


# ---------------------------------------------------------------- 평가
def _cost_bps(cid: str) -> float:
    return SAT_COST_BPS if CANDIDATES[cid]["kind"] == "satellite" else COST_BPS


def series_from_ledger(rows: list[dict], cid: str, returns: pd.DataFrame) -> pd.Series:
    """기록일 d 의 비중을 d 다음 거래일 수익부터 적용. 기록이 없는 날은 표류. 새 기록으로 옮기는 만큼 비용."""
    recs = sorted(((pd.Timestamp(r["date"]), r["weights"][cid]) for r in rows if cid in (r.get("weights") or {})),
                  key=lambda x: x[0])
    if not recs:
        return pd.Series(dtype=float)
    first, last = recs[0][0], recs[-1][0]
    after_last = returns.index[returns.index > last][:1]
    idx = returns.index[(returns.index > first) & ((returns.index <= last) | returns.index.isin(after_last))]
    bps = _cost_bps(cid) / 1e4
    held: dict[str, float] = {}
    k = 0
    out = []
    for t in idx:
        target = None
        while k < len(recs) and recs[k][0] < t:
            target = recs[k][1]
            k += 1
        cost = 0.0
        if target is not None:
            names = set(target) | set(held)
            cost = sum(abs(target.get(n, 0.0) - held.get(n, 0.0)) for n in names) * bps
            held = dict(target)
        r = returns.loc[t]
        rr = {n: (float(r[n]) if n in r.index and pd.notna(r[n]) else 0.0) for n in held}
        out.append(sum(v * rr[n] for n, v in held.items()) - cost)
        held = drift(held, rr)
    return pd.Series(out, index=idx, dtype=float)


def _mdd(s: pd.Series) -> float:
    if s.empty:
        return 0.0
    eq = (1 + s).cumprod()
    return float(min((eq / eq.cummax() - 1).min(), 0.0))


def _sharpe(s: pd.Series, rf: Optional[pd.Series]) -> Optional[float]:
    x = s - (rf.reindex(s.index).fillna(0.0) if rf is not None else 0.0)
    sd = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    return float(x.mean() / sd * math.sqrt(252)) if sd > 0 else None


def _cagr(s: pd.Series) -> float:
    if s.empty:
        return 0.0
    growth = float((1 + s).prod())
    return growth ** (252 / len(s)) - 1 if growth > 0 else -1.0


def _ir(act: pd.Series) -> Optional[float]:
    sd = float(act.std(ddof=1)) if len(act) > 1 else 0.0
    return float(act.mean() / sd * math.sqrt(252)) if sd > 0 else None


def judge_blend(c: dict, b0: dict, b1: dict) -> bool:
    """블렌드 PASS: 샤프 > B0 · MDD 가 B0 보다 5%p 이상 얕음 · 수익/|MDD| > B0·B1."""
    def gt(a, b):
        return a is not None and (b is None or a > b)
    return (gt(c.get("sharpe"), b0.get("sharpe")) and c["mdd"] >= b0["mdd"] + BLEND_MDD_MARGIN - 1e-12
            and c.get("return_per_mdd") is not None and gt(c["return_per_mdd"], b0.get("return_per_mdd"))
            and gt(c["return_per_mdd"], b1.get("return_per_mdd")))


def judge_satellite(s1: dict, s0: dict) -> bool:
    """S1 PASS: S0 대비 정보비율 ≥ 0.5 · 누적 초과 > 0 · MDD 가 S0 보다 5%p 넘게 나쁘지 않음."""
    ir = s1.get("ir_vs_S0")
    return (ir is not None and ir >= SAT_IR_THRESHOLD and s1.get("excess_vs_S0", 0.0) > 0
            and s1["mdd"] >= s0["mdd"] - SAT_MDD_TOLERANCE - 1e-12)


def evaluate(rows: list[dict], returns: pd.DataFrame) -> dict[str, Any]:
    from core.research_power import noop_guard

    rows = sorted((r for r in rows if r.get("date", "") >= START.isoformat()), key=lambda r: r["date"])
    series = {cid: series_from_ledger(rows, cid, returns) for cid in CANDIDATES}
    rf = returns[BIL] if BIL in returns.columns else None
    n = len(series["B0"])
    n_sat = len(series["S0"])
    out: dict[str, Any] = {"judge_version": JUDGE_VERSION, "days": n, "sat_days": n_sat, "min_days": MIN_DAYS,
                           "start": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
                           "candidates": {}}
    stats: dict[str, dict] = {}
    for cid, s in series.items():
        st: dict[str, Any] = {"label": CANDIDATES[cid]["label"], "days": len(s)}
        if len(s):
            mdd = _mdd(s)
            cagr = _cagr(s)
            st.update({"cumulative": float((1 + s).prod() - 1), "cagr": cagr, "mdd": mdd, "sharpe": _sharpe(s, rf),
                       "return_per_mdd": cagr / abs(mdd) if mdd < 0 else None})
        stats[cid] = st
    s0 = series["S0"]
    if len(series["S1"]) and len(s0):
        common = series["S1"].index.intersection(s0.index)
        act = series["S1"].reindex(common) - s0.reindex(common)
        stats["S1"]["excess_vs_S0"] = float((1 + act).prod() - 1)
        stats["S1"]["ir_vs_S0"] = _ir(act)
        stats["S1"]["_act"] = act
    for cid in CANDIDATES:
        st = stats[cid]
        kind = CANDIDATES[cid]["kind"]
        if cid in ("B0", "B1", "S0"):
            st["verdict"] = "기준"
        elif not st.get("days"):
            st["verdict"] = "기록 없음"
        elif kind == "blend":
            if n < MIN_DAYS:
                st["verdict"] = f"판정 전 ({n}/{MIN_DAYS}거래일)"
            elif noop_guard((series[cid] - series["B0"].reindex(series[cid].index).fillna(0.0)).tolist()):
                st["verdict"] = "NOT_EVALUABLE"
            else:
                st["verdict"] = "PASS" if (stats["B0"].get("days") and stats["B1"].get("days")
                                           and judge_blend(st, stats["B0"], stats["B1"])) else "FAIL"
        else:  # S1
            act = st.pop("_act", None)
            if n_sat < MIN_DAYS:
                st["verdict"] = f"판정 전 ({n_sat}/{MIN_DAYS}거래일)"
            elif act is None or noop_guard(act.tolist()):
                st["verdict"] = "NOT_EVALUABLE"
            else:
                st["verdict"] = "PASS" if judge_satellite(st, stats["S0"]) else "FAIL"
        st.pop("_act", None)
        out["candidates"][cid] = st
    # 중간 순위(판정 아님): 블렌드·기준선은 수익/|MDD|, 새틀라이트는 누적 수익
    rank_keys = [c for c in ("B0", "B1", "C1", "C2") if out["candidates"][c].get("days")]
    out["rank_core"] = sorted(rank_keys, key=lambda c: -(out["candidates"][c].get("return_per_mdd") or float("-inf")))
    sat_keys = [c for c in SATELLITES if out["candidates"][c].get("days")]
    out["rank_satellite"] = sorted(sat_keys, key=lambda c: -out["candidates"][c].get("cumulative", 0.0))
    return out


def ledger_returns(rows: list[dict], price_fn: Optional[PriceFn] = None) -> pd.DataFrame:
    tickers = sorted({t for r in rows for w in (r.get("weights") or {}).values() for t in w} | {SPY, BIL})
    hist = (price_fn or _default_price_fn)(tickers)
    _, total = _frames(hist, tickers)
    return total.pct_change(fill_method=None)


def evaluate_live(path: Optional[Path] = None, price_fn: Optional[PriceFn] = None) -> dict[str, Any]:
    rows = load_ledger(path)
    if not rows:
        return {"judge_version": JUDGE_VERSION, "days": 0, "sat_days": 0, "min_days": MIN_DAYS, "candidates": {}, "records": 0}
    out = evaluate(rows, ledger_returns(rows, price_fn))
    out["records"] = len(rows)
    return out


def refresh_status(path: Optional[Path] = None, status_path: Optional[Path] = None,
                   price_fn: Optional[PriceFn] = None, now: Optional[datetime] = None) -> dict:
    """경과를 계산해 status.json 에 원자적으로 쓴다(관제 센터·주간 점검이 네트워크 없이 읽음)."""
    ev = evaluate_live(path, price_fn)
    rows = load_ledger(path)
    ev["updated_at"] = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    ev["last_errors"] = (rows[-1].get("errors") if rows else None) or {}
    p = Path(status_path or STATUS)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".status.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, default=float)
    os.replace(tmp, p)
    return ev


def load_status(status_path: Optional[Path] = None) -> dict:
    p = Path(status_path or STATUS)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
