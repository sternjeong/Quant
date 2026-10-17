"""앞으로 토너먼트 v3 (2026-10-16 사전 등록, 사용자 요청) — 과거 구간에서 사전 등록 시험을 통과한 후보들의 도입 판단을 '아직 오지 않은 데이터'로 하기 위한 세 번째 전진 원장.

왜: spy-champion-v1(P1·P4)·sat-stagger-v1(G3)·sat-buffer-v1(K6_H6)·signal-swap-v1(KRS)·sector-concentrate-v1(SC2) 등은 이미 본
과거 데이터로 시험했다(docs/RESEARCH_JOBS.md '판정 설계 규칙' 3). v1·v2 는 후보·판정이 고정됐으므로 바꾸지 않고 여기서 따로 기록한다.

시작(START): 고정 날짜가 아니다. 배포 뒤 이 모듈의 record() 가 처음 불린 시각을 data/forward_tournament_v3/armed.json 에 남기고(뉴욕 날짜),
그 날짜 이상(그리고 등록일 REGISTERED 이상)인 첫 '완료된' 미국 거래일이 첫 기록일 = START 다. 원장의 첫 줄 날짜가 곧 START.

후보(고정 — 바꾸려면 새 id 로 다시 등록). 비중은 기록일(마지막 완료 거래일) 종가까지의 자료로 정하고 다음 거래일 수익부터 적용한다.
  B0  SPY 그냥 보유.
  B1  현 챔피언: 라이브 코어 85% + 새틀라이트(S-SEED-000) 15%. 라이브 방식(tax_fx.champion_weights 와 같음) — 코어 목표 비중이
      바뀌는 날(월 첫 거래일에 신호가 바뀔 때)이나 새틀라이트를 다시 고르는 날에만 전체를 85/15·목표 비중으로 맞추고, 그 밖의 날은 표류.
  P1  SPY 85% + 새틀라이트 15%. 슬리브 비율은 첫 기록일과 매년 첫 기록일(1월 첫 거래일)에만 목표로 되돌린다. 새틀라이트 재선정일에는
      새틀라이트 슬리브의 표류한 크기 안에서만 새 종목을 균등으로 나눈다.
  P4  SPY 50% + 새틀라이트 30% + 라이브 코어 20%. P1 과 같은 1월 리셋. 코어 목표가 바뀌는 날은 코어 슬리브 안에서만 다시 나눈다.
  P1ST SPY 85% + 새틀라이트 15% 를 5%씩 세 하위 슬리브로(재선정 달 1·7월 / 3·9월 / 5·11월), 각 하위 슬리브는 S-SEED-000 에
      K6 순위 버퍼(보유 종목이 추세 활성이고 순위 6 안이면 유지, 빈자리만 상위 종목으로 — sat-buffer-v1 과 같은 규칙). 1월 리셋은 P1 과 같고,
      하위 슬리브는 자기 재선정일에만 자기 크기 안에서 다시 나누며 그 사이에는 그대로 들고 있는다(다른 하위 슬리브는 건드리지 않음).
  KRS 상대강도 코어 85% + 새틀라이트 15%. 코어 = 라이브 코어와 같고 자격만 '252거래일 수익 > 같은 기간 SPY 수익'(못 넘으면 그 슬롯은 BIL,
      core_lab abs_filter="spy"). 라이브 방식(B1 과 같음).
  SC2 Select Sector SPDR 11개(XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY) 중 252거래일 총수익 상위 2, 균등, 월 1회(그달 첫 거래일 결정,
      신호는 그 전 거래일 종가까지), 언제나 100% 투자(신호가 있는 섹터가 4개 미만이면 SPY — sector-concentrate-v1 과 같음). 그 사이 표류.
  SC2VT20 (2026-10-17 사용자 추가, 기록 전) SC2 와 같은 선정에 변동성 맞춤(mom-volscale-v1 I2/VT20/none): 노출 = min(0.20 / 실현 변동성, 1.0),
      실현 변동성 = 결정일 전 거래일까지 126거래일의 '맞추지 않은 SC2' 일별 수익 표준편차 × √252(원장에 기록된 SC2 비중의 수익, 결정일 당일
      수익은 넣지 않음). 126일이 쌓이기 전에는 노출 1.0. 남는 몫은 BIL, 노출은 월 리밸런싱 때만 바꾼다. 시장 필터 없음.
  라이브 코어 = core_lab 기본(12개월 가격 모멘텀 상위 4·SPY 200일선·남는 몫 BIL), 유니버스는 등록 당시 라이브 16자산(CORE_UNIVERSE_V3) 고정.

새틀라이트 일정(정확히): 새틀라이트 상태는 넷 — SAT(1·7월, 버퍼 없음; B1·P1·P4·KRS 가 함께 씀), ST_A(1·7월)·ST_B(3·9월)·ST_C(5·11월, K6 버퍼).
  모두 첫 기록일(START)에 처음 고른다(버퍼 상태도 이때는 보유가 없어 그냥 상위 3). 그 뒤 다시 고르는 날 = 직전 선정일이 속한 달 '다음'의
  재선정 달 1일 이후 첫 기록일. 예: START 가 2026-10 이면 SAT·ST_A 는 2027-01·2027-07…, ST_B 는 2027-03·2027-09…, ST_C 는 2026-11·2027-05….
  선정은 v2 와 같은 방식 — 새틀라이트 R&D 의 동결 신호 코드(해시 고정)와 라이브 엔진과 같은 후보 풀(그날 기준 섹터 균등 시총 상위 40),
  기록일 종가까지의 가격, 상위 3 균등(못 채운 칸은 그 슬리브의 현금). 선정이 실패하면 그 상태만 직전 보유를 그대로 두고(첫 선정이면 현금)
  errors 에 남긴 뒤 다음 기록일에 다시 고른다.
기록: 매일 밤 forward_tournament_record 잡(00:39 KST)이 v1·v2 기록 뒤 이 모듈의 record() 를 부른다(각자 따로 try — 서로 영향 없음).
  원장 data/forward_tournament_v3/ledger.jsonl 에 주식 거래일마다 한 줄(같은 날짜는 다시 쓰지 않음). 아직 끝나지 않은 미국 정규장 봉은 쓰지 않는다.
  기록하는 비중은 '실제로 들고 있을 비중'이다 — 매매가 없는 날은 직전 비중이 배당 포함 수익에 따라 표류한 값.
평가: 기록된 비중을 다음 거래일 배당 포함 수익에 곱한다. 기록이 빠진 날은 직전 비중이 표류한 것으로 본다. 새 기록 비중으로 옮겨 가는 만큼
  (표류한 비중과의 차이) 편도 비용 — ETF 3bp, 개별 종목 8bp(v2 와 같은 값).
판정 forward-tournament/v3 (2026-10-16 고정, 첫 기록 뒤 252거래일 전에는 판정하지 않는다 — 경과·중간 순위만, 중간 순위는 '판정 아님'):
  후보(P1·P4·P1ST·KRS·SC2·SC2VT20) PASS = 연환산 수익 ≥ B0 연환산 수익 + 1.0%p 이고 최대낙폭이 B0 보다 3%p 넘게 나쁘지 않음.
  B1 대비 연환산 수익 차이와 일별 초과의 정보비율도 함께 보고한다(판정에 쓰지 않음). 후보가 B0 와 매일 같으면 NOT_EVALUABLE.
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

from core import forward_tournament_v2 as ft2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "forward_tournament_v3"
LEDGER = DATA_DIR / "ledger.jsonl"
STATUS = DATA_DIR / "status.json"   # 매일 기록 뒤 계산한 경과(관제 센터·주간 점검이 네트워크 없이 읽는다)
ARMED_NAME = "armed.json"           # 배포 뒤 첫 기록 시도 시각(START 기준) — 원장과 같은 폴더
JUDGE_VERSION = "forward-tournament/v3"
REGISTERED = date(2026, 10, 16)     # 사전 등록일 — 이보다 이른 거래일은 기록하지 않는다
MIN_DAYS = 252
# --- 판정 기준 (forward-tournament/v3, 2026-10-16 고정) ---
RETURN_MARGIN = 0.010               # 연환산 수익 ≥ B0 + 1.0%p
MDD_TOLERANCE = 0.03                # 최대낙폭이 B0 보다 3%p 넘게 나쁘지 않음
COST_BPS = 3.0                      # ETF 편도
STOCK_COST_BPS = 8.0                # 개별 종목 편도
SAT_TOP_K = 3
BUFFER_K = 6
SC2_TOP = 2
SC2_LOOKBACK = 252
VT_TARGET = 0.20
VT_WINDOW = 126
SC2_MIN_VALID = 2 * SC2_TOP         # 신호가 있는 섹터가 이보다 적으면 SPY 100%
SPY, BIL = ft2.SPY, ft2.BIL
SAT_SEED = "S-SEED-000"
# 등록 당시(2026-10-16) 라이브 코어 유니버스 — 이후 라이브가 바뀌어도 v3 는 이것을 쓴다
CORE_UNIVERSE_V3 = ("XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU",
                    "TLT", "IEF", "GLD", "EFA", "HYG")
# sector-concentrate-v1 ETF_SECTORS 순서(동점일 때 앞선 것)
SECTORS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLRE", "XLC")
ETFS = frozenset(CORE_UNIVERSE_V3) | frozenset(SECTORS) | {SPY, BIL}

# 새틀라이트 상태: 재선정 달, 순위 버퍼(None = 버퍼 없이 상위 3)
SAT_STATES: dict[str, dict[str, Any]] = {
    "SAT": {"months": (1, 7), "buffer": None},
    "ST_A": {"months": (1, 7), "buffer": BUFFER_K},
    "ST_B": {"months": (3, 9), "buffer": BUFFER_K},
    "ST_C": {"months": (5, 11), "buffer": BUFFER_K},
}
# 슬리브 → 안쪽 비중의 출처: spy / core(라이브 코어) / krs(상대강도 코어) / sec(SC2) / 새틀라이트 상태 이름
CANDIDATES: dict[str, dict[str, Any]] = {
    "B0": {"label": "SPY 그냥 보유", "mode": "january", "sleeves": {"spy": 1.0}},
    "B1": {"label": "현 챔피언(라이브 코어 85% + 새틀라이트 15%)", "mode": "live", "sleeves": {"core": 0.85, "SAT": 0.15}},
    "P1": {"label": "SPY 85% + 새틀라이트 15%(1월 리셋)", "mode": "january", "sleeves": {"spy": 0.85, "SAT": 0.15}},
    "P4": {"label": "SPY 50% + 새틀라이트 30% + 코어 20%(1월 리셋)", "mode": "january",
           "sleeves": {"spy": 0.50, "SAT": 0.30, "core": 0.20}},
    "P1ST": {"label": "SPY 85% + 새틀라이트 5%×3 엇갈린 재선정·K6 버퍼(1월 리셋)", "mode": "january",
             "sleeves": {"spy": 0.85, "ST_A": 0.05, "ST_B": 0.05, "ST_C": 0.05}},
    "KRS": {"label": "상대강도 코어(SPY 를 이긴 자산만) 85% + 새틀라이트 15%", "mode": "live", "sleeves": {"krs": 0.85, "SAT": 0.15}},
    "SC2": {"label": "섹터 SPDR 12개월 상위 2(월 1회, 100% 투자)", "mode": "january", "sleeves": {"sec": 1.0}},
    "SC2VT20": {"label": "SC2 + 변동성 맞춤(목표 20%, 노출 상한 1, 남는 몫 BIL)", "mode": "january", "sleeves": {"secvt": 1.0}},
}
BASELINES = ("B0", "B1")
JUDGED = ("P1", "P4", "P1ST", "KRS", "SC2", "SC2VT20")
CASH_KEY = "_cash"

PriceFn = Callable[[list[str]], dict[str, pd.DataFrame]]
PoolFn = Callable[[str, date], list[str]]


# ---------------------------------------------------------------- 시작(armed)
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
    """첫 기록 시도 시각을 남긴다(이미 있으면 그대로). START = 이 뉴욕 날짜 이상인 첫 완료 거래일."""
    got = load_armed(path)
    if got.get("start_not_before"):
        return got
    floor = max(_ny_date(now), REGISTERED)
    got = {"armed_at": now.isoformat(timespec="seconds"), "start_not_before": floor.isoformat(), "judge_version": JUDGE_VERSION}
    p = Path(path).parent / ARMED_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
    return got


# ---------------------------------------------------------------- 목표 비중
def core_targets(price: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    """(라이브 코어, KRS 코어)의 오늘(마지막 날) 목표 비중 — 신호는 가격, 남는 몫 BIL."""
    from core import core_lab as cl

    cols = [t for t in CORE_UNIVERSE_V3 if t in price.columns]
    extra = price[[c for c in (SPY, BIL) if c in price.columns]]
    base = cl.CoreConfig(cash="bil", universe=CORE_UNIVERSE_V3)
    out = []
    for cfg in (base, cl.with_changes(base, abs_filter="spy")):
        w = cl.build_weights(price[cols], extra, cfg).iloc[-1]
        out.append({t: float(v) for t, v in w.items() if v > 1e-9})
    return out[0], out[1]


def sc2_target(total: pd.DataFrame) -> dict[str, Any]:
    """SC2: 마지막 날이 속한 달의 결정(그달 첫 거래일, 신호 = 그 전 거래일까지 252거래일 총수익) — 상위 2 균등 또는 SPY."""
    idx = total.index
    per = idx.to_period("M")
    p = next(i for i in range(len(idx)) if per[i] == per[-1])   # 이 달 첫 거래일(결정일)
    sig = p - 1                                                  # 신호 = 그 전 거래일 종가
    month = str(per[-1])
    scores: dict[str, float] = {}
    if sig >= SC2_LOOKBACK:
        for t in SECTORS:
            if t not in total.columns:
                continue
            a, b = total[t].iloc[sig - SC2_LOOKBACK], total[t].iloc[sig]
            if pd.notna(a) and pd.notna(b) and a > 0:
                v = float(b / a - 1)
                if math.isfinite(v):
                    scores[t] = v
    if len(scores) < SC2_MIN_VALID:
        return {"month": month, "picks": [], "weights": {SPY: 1.0}, "signal_date": str(idx[sig].date()) if sig >= 0 else None}
    order = sorted(scores, key=lambda t: (-scores[t], SECTORS.index(t)))[:SC2_TOP]
    return {"month": month, "picks": order, "weights": {t: 1.0 / SC2_TOP for t in order},
            "signal_date": str(idx[sig].date()), "scores": {t: round(v, 6) for t, v in scores.items()}}


def vol_exposure(daily: list[float]) -> tuple[float, Optional[float]]:
    """(노출, 실현 변동성). daily = 결정일 전까지의 맞추지 않은 SC2 일별 수익(오래된 것부터). 126개 미만이면 노출 1."""
    if len(daily) < VT_WINDOW:
        return 1.0, None
    x = pd.Series(daily[-VT_WINDOW:], dtype=float)
    vol = float(x.std(ddof=1)) * math.sqrt(252)
    return (min(VT_TARGET / vol, 1.0) if vol > 0 else 1.0), vol


def vt_inner(sc2_weights: dict[str, float], exposure: float) -> dict[str, float]:
    out = {t: w * exposure for t, w in sc2_weights.items()}
    if exposure < 1.0:
        out[BIL] = out.get(BIL, 0.0) + (1.0 - exposure)
    return out


def sc2_daily(prev_w: Optional[dict], gap: pd.DataFrame) -> list[list]:
    """직전 기록의 SC2 비중(표류)으로 gap 각 날의 맞추지 않은 SC2 수익 — [[날짜, 수익], …]."""
    if not prev_w:
        return []
    out, w = [], dict(prev_w)
    for t, row in gap.iterrows():
        r = {k: _rr(row.to_dict(), k) for k in w}
        out.append([str(t.date()), sum(v * r[k] for k, v in w.items())])
        w = ft2.drift(w, r)
    return out


# ---------------------------------------------------------------- 새틀라이트
def next_due(rebalanced: str, months: tuple[int, ...]) -> date:
    """직전 선정일이 속한 달 '다음'의 재선정 달 1일."""
    d = date.fromisoformat(rebalanced)
    y, m = d.year, d.month
    for _ in range(12):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        if m in months:
            return date(y, m, 1)
    raise ValueError(f"재선정 달 없음: {months}")


def sat_due(state: Optional[dict], months: tuple[int, ...], day: date) -> bool:
    if not state or not state.get("rebalanced"):
        return True
    return day >= next_due(state["rebalanced"], months)


def _key(t: str, s: float) -> tuple:
    return (-float(s), t)


def select_with_buffer(held: list[str], pool_scores: dict, held_scores: dict, K: Optional[int],
                       top_n: int = SAT_TOP_K) -> tuple[list[str], list[str]]:
    """(새 보유, 유지한 종목) — sat-buffer-v1 과 같은 규칙. K=None 이면 버퍼 없이 상위 top_n.
    보유 종목 h 는 그날 점수가 있고(추세 활성·가격 있음) 순위(1 + 그날 풀 후보 중 h 보다 앞서는 수) ≤ K 이면 유지."""
    order = [t for t, _ in sorted(((t, float(s)) for t, s in pool_scores.items() if s is not None and math.isfinite(float(s))),
                                  key=lambda kv: _key(*kv))]
    if K is None:
        return order[:top_n], []
    kept = []
    for t in held:
        s = held_scores.get(t)
        if s is None or not math.isfinite(float(s)):
            continue
        k = _key(t, float(s))
        rank = 1 + sum(1 for c, v in pool_scores.items()
                       if c != t and v is not None and math.isfinite(float(v)) and _key(c, v) < k)
        if rank <= K:
            kept.append(t)
    kept = sorted(kept, key=lambda t: _key(t, held_scores[t]))[:top_n]
    picks = list(kept)
    for t in order:
        if len(picks) >= top_n:
            break
        if t not in picks:
            picks.append(t)
    return picks, kept


def sat_scores(day: pd.Timestamp, extra: list[str], *, pool_fn: PoolFn, sat_price_fn: Callable) -> dict:
    """그날 풀(라이브와 같은 live40)의 S-SEED-000 점수(추세 활성·기록일 종가 있음)와 풀 밖 보유 종목(extra)의 점수."""
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(ft2.SEEDS_DIR / SAT_SEED)
    if sl.sha(code) != ft2.SIGNAL_SHA[SAT_SEED]:
        raise RuntimeError(f"{SAT_SEED} 신호 코드가 등록 당시와 다름 — 기록 중단")
    signal = sl.load_signal(code)
    members = list(pool_fn("live40", day.date()))
    names = list(dict.fromkeys(members + [t for t in extra if t not in members]))
    hist = sat_price_fn(names, day.date())
    data = sl.LabData(trading_days=pd.DatetimeIndex([day]), ohlcv={t: df for t, df in hist.items()},
                      closes=pd.DataFrame(index=[day]))
    prices = sl._signal_prices(data, names, day, day)
    eligible = {t for t, df in prices.items() if len(df) and pd.Timestamp(df.index[-1]).normalize() == day
                and pd.notna(df["Close"].iloc[-1])}
    asof = pd.Timestamp(day.date() - timedelta(days=1))
    raw = sl._call_signal(signal, spec, data, {t: prices[t] for t in eligible}, asof, spec["signal"]["params_grid"][0]) or {}
    scores = {}
    for t, v in raw.items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if t in eligible and math.isfinite(f):
            scores[t] = f
    mset = set(members)
    return {"pool": {t: v for t, v in scores.items() if t in mset}, "all": scores,
            "pool_size": len(members), "eligible": len(eligible & mset), "signal_sha": ft2.SIGNAL_SHA[SAT_SEED]}


# ---------------------------------------------------------------- 슬리브 장부
def _rr(r: dict, t: str) -> float:
    if t == CASH_KEY:
        return 0.0
    v = r.get(t)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def drift_book(book: dict[str, dict[str, float]], rets: pd.DataFrame) -> dict[str, dict[str, float]]:
    """장부(슬리브 → {종목: 전체 대비 비중, _cash: 현금}) 를 여러 날 수익으로 표류. 합은 1 로 유지."""
    book = {s: dict(h) for s, h in book.items()}
    for _, row in rets.iterrows():
        r = row.to_dict()
        growth = sum(v * (1.0 + _rr(r, t)) for h in book.values() for t, v in h.items())
        if growth <= 0:
            return {s: {t: 0.0 for t in h} for s, h in book.items()}
        book = {s: {t: v * (1.0 + _rr(r, t)) / growth for t, v in h.items()} for s, h in book.items()}
    return book


def _fill(size: float, inner: dict[str, float]) -> dict[str, float]:
    out = {t: size * float(w) for t, w in inner.items() if w > 1e-12}
    cash = size - sum(out.values())
    if cash > 1e-12:
        out[CASH_KEY] = cash
    return out


def book_weights(book: dict[str, dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in book.values():
        for t, v in h.items():
            if t != CASH_KEY and v > 1e-12:
                out[t] = out.get(t, 0.0) + v
    return out


def _same(a: Optional[dict], b: Optional[dict], tol: float = 1e-9) -> bool:
    if a is None or b is None:
        return False
    return all(abs(float(a.get(t, 0.0)) - float(b.get(t, 0.0))) <= tol for t in set(a) | set(b))


def step_book(cid: str, prev_book: Optional[dict], gap: pd.DataFrame, inner: dict[str, dict[str, float]],
              changed: set[str], new_year: bool) -> tuple[dict, list[str]]:
    """후보 하나의 오늘 장부와 매매 사유.
    live: 어느 슬리브든 안쪽 목표가 바뀌면 전체를 목표 비율·목표 비중으로. 그 밖에는 표류.
    january: 첫 기록·해가 바뀐 첫 기록일에만 전체를 목표 비율로, 그 밖에는 바뀐 슬리브만 표류한 크기 안에서 다시 나눈다."""
    c = CANDIDATES[cid]
    targets = c["sleeves"]
    if prev_book is None or set(prev_book) != set(targets):
        return {s: _fill(w, inner[s]) for s, w in targets.items()}, ["start"]
    book = drift_book(prev_book, gap)
    hit = [s for s in targets if s in changed]
    if c["mode"] == "live":
        if hit:
            return {s: _fill(w, inner[s]) for s, w in targets.items()}, ["rebalance:" + ",".join(hit)]
        return book, []
    if new_year:
        return {s: _fill(w, inner[s]) for s, w in targets.items()}, ["january"] + [f"sleeve:{s}" for s in hit]
    for s in hit:
        book[s] = _fill(sum(book[s].values()), inner[s])
    return book, [f"sleeve:{s}" for s in hit]


# ---------------------------------------------------------------- 원장
def load_ledger(path: Optional[Path] = None) -> list[dict]:
    return ft2.load_ledger(Path(path or LEDGER))


def record(*, path: Optional[Path] = None, price_fn: Optional[PriceFn] = None, pool_fn: Optional[PoolFn] = None,
           sat_price_fn: Optional[Callable] = None, now: Optional[datetime] = None) -> dict:
    """마지막으로 끝난 주식 거래일의 후보별 비중을 한 줄 추가. 같은 날짜는 다시 쓰지 않는다.
    새틀라이트 선정이 실패하면 그 상태만 직전 보유를 두고(첫 선정이면 현금) errors 에 남긴다 — 다음 기록일에 다시 고른다."""
    now = now or datetime.now(timezone.utc)
    p = Path(path or LEDGER)
    armed = _arm(p, now)
    floor = date.fromisoformat(armed["start_not_before"])
    rows = load_ledger(p)
    prev = rows[-1] if rows else None
    held = sorted({t for h in ((prev or {}).get("books") or {}).values() for s in h.values() for t in s if t != CASH_KEY})
    base = list(dict.fromkeys(list(CORE_UNIVERSE_V3) + list(SECTORS) + [SPY, BIL]))
    tickers = list(dict.fromkeys(base + held))
    hist = (price_fn or ft2._default_price_fn)(tickers)
    price, total = ft2._frames(hist, tickers)
    days = ft2._completed(price.index, now)
    if not len(days):
        return {"recorded": False, "date": None, "reason": "완료된 거래일 없음"}
    day = days[-1]
    dstr = str(day.date())
    if not rows and day.date() < floor:
        return {"recorded": False, "date": dstr, "reason": f"시작 전({floor} 이후 첫 완료 거래일부터)"}
    if any(r.get("date") == dstr for r in rows):
        return {"recorded": False, "date": dstr, "reason": "이미 기록됨"}
    if prev and prev.get("date", "") > dstr:
        return {"recorded": False, "date": dstr, "reason": f"원장 마지막({prev['date']})보다 이른 날짜"}
    price, total = price.loc[:day], total.loc[:day]
    rets = total.pct_change(fill_method=None)
    gap = rets.loc[rets.index > pd.Timestamp(prev["date"])] if prev else rets.iloc[0:0]

    core, krs = core_targets(price)
    sc2 = sc2_target(total)
    pc = (prev or {}).get("components") or {}
    changed: set[str] = set()
    if not _same(core, pc.get("core")):
        changed.add("core")
    if not _same(krs, pc.get("krs")):
        changed.add("krs")
    if (pc.get("sc2") or {}).get("month") != sc2["month"]:
        changed.add("sec")

    satellite: dict[str, dict] = {}
    errors: dict[str, str] = {}
    prev_sat = (prev or {}).get("satellite") or {}
    due = [k for k, cfg in SAT_STATES.items() if sat_due(prev_sat.get(k), cfg["months"], day.date())]
    scores = None
    if due:
        extra = sorted({t for k in due if SAT_STATES[k]["buffer"] for t in (prev_sat.get(k) or {}).get("picks") or []})
        try:
            scores = sat_scores(day, extra, pool_fn=pool_fn or ft2._default_pool_fn,
                                sat_price_fn=sat_price_fn or ft2._default_sat_price_fn)
        except Exception as exc:  # noqa: BLE001 - 다른 후보 기록은 계속
            msg = f"{type(exc).__name__}: {exc}"
            for k in due:
                errors[k] = msg
    for k, cfg in SAT_STATES.items():
        st = dict(prev_sat.get(k) or {})
        if k in due and scores is not None:
            heldk = list(st.get("picks") or [])
            picks, kept = select_with_buffer(heldk, scores["pool"], {t: scores["all"].get(t) for t in heldk}, cfg["buffer"])
            st = {"picks": picks, "kept": kept, "rebalanced": dstr, "pool_size": scores["pool_size"],
                  "eligible": scores["eligible"], "signal_sha": scores["signal_sha"]}
            changed.add(k)
        satellite[k] = st

    sc2_rets = sc2_daily(((prev or {}).get("weights") or {}).get("SC2"), gap)
    hist_d = [x for r in rows for x in (r.get("sc2_rets") or [])] + sc2_rets
    pvt = pc.get("sc2vt") or {}
    if "sec" in changed or "exposure" not in pvt:
        expo, vol = vol_exposure([v for d_, v in hist_d if d_ < dstr])   # 결정일 당일 수익은 넣지 않음
        sc2vt = {"month": sc2["month"], "exposure": expo, "vol": vol, "n": len([1 for d_, _ in hist_d if d_ < dstr])}
    else:
        sc2vt = dict(pvt)
    if "sec" in changed:
        changed.add("secvt")
    inner: dict[str, dict[str, float]] = {"spy": {SPY: 1.0}, "core": core, "krs": krs, "sec": sc2["weights"],
                                          "secvt": vt_inner(sc2["weights"], sc2vt["exposure"])}
    for k in SAT_STATES:
        inner[k] = {t: 1.0 / SAT_TOP_K for t in (satellite[k].get("picks") or [])}
    new_year = prev is not None and pd.Timestamp(prev["date"]).year != day.year
    books, weights, trades = {}, {}, {}
    prev_books = (prev or {}).get("books") or {}
    for cid in CANDIDATES:
        b, why = step_book(cid, prev_books.get(cid), gap, inner, changed, new_year)
        books[cid] = b
        weights[cid] = book_weights(b)
        if why:
            trades[cid] = why

    row = {"date": dstr, "recorded_at": now.isoformat(timespec="seconds"), "judge_version": JUDGE_VERSION,
           "start": rows[0]["date"] if rows else dstr, "weights": weights, "books": books, "trades": trades,
           "components": {"core": core, "krs": krs, "sc2": sc2, "sc2vt": sc2vt}, "satellite": satellite,
           "sc2_rets": sc2_rets}
    if errors:
        row["errors"] = errors
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"recorded": True, "date": dstr, "errors": errors}


# ---------------------------------------------------------------- 평가
def _bps(t: str) -> float:
    return (COST_BPS if t in ETFS else STOCK_COST_BPS) / 1e4


def series_from_ledger(rows: list[dict], cid: str, returns: pd.DataFrame) -> pd.Series:
    """기록일 d 의 비중을 d 다음 거래일 수익부터 적용. 기록이 없는 날은 표류. 새 기록으로 옮기는 만큼 비용(종목별 편도 bp)."""
    recs = sorted(((pd.Timestamp(r["date"]), r["weights"][cid]) for r in rows if cid in (r.get("weights") or {})),
                  key=lambda x: x[0])
    if not recs:
        return pd.Series(dtype=float)
    first, last = recs[0][0], recs[-1][0]
    after_last = returns.index[returns.index > last][:1]
    idx = returns.index[(returns.index > first) & ((returns.index <= last) | returns.index.isin(after_last))]
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
            cost = sum(abs(target.get(n, 0.0) - held.get(n, 0.0)) * _bps(n) for n in names)
            held = dict(target)
        r = returns.loc[t]
        rr = {n: (float(r[n]) if n in r.index and pd.notna(r[n]) else 0.0) for n in held}
        out.append(sum(v * rr[n] for n, v in held.items()) - cost)
        held = ft2.drift(held, rr)
    return pd.Series(out, index=idx, dtype=float)


def judge(c: dict, b0: dict) -> bool:
    """PASS: 연환산 수익 ≥ B0 + 1.0%p 이고 최대낙폭이 B0 보다 3%p 넘게 나쁘지 않음."""
    return (c["cagr"] >= b0["cagr"] + RETURN_MARGIN - 1e-12 and c["mdd"] >= b0["mdd"] - MDD_TOLERANCE - 1e-12)


def evaluate(rows: list[dict], returns: pd.DataFrame) -> dict[str, Any]:
    from core import research_power as rp

    rows = sorted(rows, key=lambda r: r["date"])
    series = {cid: series_from_ledger(rows, cid, returns) for cid in CANDIDATES}
    n = len(series["B0"])
    power = rp.power_report(MIN_DAYS / 252, len(JUDGED))
    out: dict[str, Any] = {"judge_version": JUDGE_VERSION, "days": n, "min_days": MIN_DAYS,
                           "start": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
                           "rule": f"PASS = 연환산 수익 ≥ B0 + {RETURN_MARGIN * 100:.1f}%p · 최대낙폭이 B0 보다 {MDD_TOLERANCE * 100:.0f}%p 넘게 나쁘지 않음",
                           "power_line": rp.power_line(power), "candidates": {}}
    stats: dict[str, dict] = {}
    for cid, s in series.items():
        st: dict[str, Any] = {"label": CANDIDATES[cid]["label"], "days": len(s)}
        if len(s):
            st.update({"cumulative": float((1 + s).prod() - 1), "cagr": ft2._cagr(s), "mdd": ft2._mdd(s)})
        stats[cid] = st
    b0, b1 = stats["B0"], stats["B1"]
    for cid in CANDIDATES:
        st = stats[cid]
        s = series[cid]
        if cid != "B0" and len(s) and b0.get("days"):
            st["cagr_vs_B0"] = st["cagr"] - b0["cagr"]
            st["mdd_vs_B0"] = st["mdd"] - b0["mdd"]
        if cid != "B1" and len(s) and b1.get("days"):
            common = s.index.intersection(series["B1"].index)
            act = s.reindex(common) - series["B1"].reindex(common)
            st["cagr_vs_B1"] = st["cagr"] - b1["cagr"]
            st["ir_vs_B1"] = ft2._ir(act)
        if cid in BASELINES:
            st["verdict"] = "기준"
        elif not st.get("days"):
            st["verdict"] = "기록 없음"
        elif n < MIN_DAYS:
            st["verdict"] = f"판정 전 ({n}/{MIN_DAYS}거래일)"
        elif rp.noop_guard((s - series["B0"].reindex(s.index).fillna(0.0)).tolist()):
            st["verdict"] = "NOT_EVALUABLE"
        else:
            st["verdict"] = "PASS" if judge(st, b0) else "FAIL"
        out["candidates"][cid] = st
    # 중간 순위(판정 아님): 연환산 수익 순
    keys = [c for c in CANDIDATES if out["candidates"][c].get("days")]
    out["rank"] = sorted(keys, key=lambda c: -out["candidates"][c].get("cagr", float("-inf")))
    out["rank_note"] = "판정 아님"
    return out


def evaluate_live(path: Optional[Path] = None, price_fn: Optional[PriceFn] = None) -> dict[str, Any]:
    rows = load_ledger(path)
    if not rows:
        return {"judge_version": JUDGE_VERSION, "days": 0, "min_days": MIN_DAYS, "candidates": {}, "records": 0}
    out = evaluate(rows, ft2.ledger_returns(rows, price_fn))
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
