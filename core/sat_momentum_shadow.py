"""모멘텀 새틀라이트 앞으로 기록(shadow) — 2026-11-19 사전 등록, 배분·주문에 반영하지 않는다.

배경: 새틀라이트 목표 연구 6개(sat-horizon-v1·v2, sat-industry-horizon-v1, insider-form4-v1, news-drift-v1, lazy-prices-v1)가
모두 'S&P 500 대비 +7%p' 기준을 넘지 못했다. 가장 꾸준했던 것은 12개월 보유 모멘텀(종목 MOM6 상위 5, 업종 RS12 1위)으로
세전 약 +3~6%p 였지만, 이 후보는 결과를 본 뒤 고른 것이고 1996~2026 주가 자료는 이미 다 봤다. 사용자 결정(2026-11-19):
목표를 +5%p 로 낮추고, 남은 정직한 검증인 '지금부터 앞으로'로 확인한다.

규칙(고정, sat-mom-forward/v1):
  - 후보: 형성일 기준 S&P 500 구성종목(data/sp500_historical_constituents.csv 최신 행), SPY 제외.
  - 형성: 매달 첫 기록일(그달 처음으로 완성된 미국 거래일 D)에 D 종가까지의 조정 종가로 점수를 매겨 상위 5종목(동점은 티커순).
      MOM6(본 판정)   = 종가[D] / 종가[D−126] − 1
      MOM12_1(참고)   = 종가[D−21] / 종가[D−252] − 1
  - 보유: D 다음 거래일 종가에 동일가중 매수, 그로부터 252거래일 뒤 종가까지 그대로 보유(달마다 새 묶음이 겹쳐 쌓임).
    중간에 가격이 끊긴 종목(상장폐지 등)은 끊기기 전 마지막 가격으로 본다.
  - 비용: 매수·매도 편도 8bp 씩 차감. 세금·배당 세금 미반영(조정 종가라 배당은 재투자된 것으로 본다).
  - 원장 data/sat_momentum_shadow/cohorts.jsonl 에 그달 선정 종목을 한 줄 남긴다. 줄은 고치지 않고, 평가는 기록된 종목만 쓴다.
    수익은 나중에 가격으로 계산한다(종목은 미리 고정되므로 결과를 보고 고를 여지가 없다).
판정(결과를 보기 전에 고정):
  - 대상: 2026-11 ~ 2027-10 에 형성된 12개 묶음(JUDGED_MONTHS). 12개 중 10개 이상이 기록되고 기록된 묶음이 모두 252거래일을
    채운 뒤(약 2028-11)에만 판정한다. 그 전에는 '판정 전'과 중간 경과(미완료 묶음은 현재가 평가)만 보고한다.
  - 묶음 초과수익 = 묶음 수익(비용 차감) − 같은 기간 SPY 조정 수익.
  - PASS = MOM6 묶음 초과수익 평균 ≥ +5%p 이고 중앙값 > 0(한두 종목의 대박에 기대지 않음). 아니면 FAIL.
  - MOM12_1 은 같은 방식으로 계산해 보여 주기만 한다(판정 대상 아님 — 다중검정을 피하려고 본 판정은 하나만).
  - PASS 도 '새틀라이트 규칙 교체를 사람이 검토할 후보'일 뿐이다. 겹치는 12개월 묶음 12개는 독립 관측이 2개 남짓이라 검정력이
    낮다 — 이 기록은 증명이 아니라 '과거에 보인 것이 앞으로도 대략 나오는가'의 현실 점검이다.
한계: 구성종목 파일이 최신이 아니면(갱신이 밀리면) 새로 편입된 종목이 후보에서 빠진다. 무료 가격 소스 기준.
"""

from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEDGER = PROJECT_ROOT / "data" / "sat_momentum_shadow" / "cohorts.jsonl"
JUDGE_VERSION = "sat-mom-forward/v1"
REGISTERED = date(2026, 11, 19)
FORWARD_START = date(2026, 11, 19)  # 이 날 이후 완성된 거래일부터 묶음을 만든다
ARMS = {"MOM6": "6개월 모멘텀 상위 5", "MOM12_1": "12-1 모멘텀 상위 5(참고)"}
PRIMARY = "MOM6"
TOP_N = 5
HOLD_DAYS = 252
LOOKBACK = 253          # MOM12_1 에 필요한 거래일 수(D−252 ~ D)
TARGET = 0.05
COST_BPS = 8.0
MIN_NAMES = 300         # 점수를 낼 수 있는 후보가 이보다 적으면 그날은 기록하지 않고 다음 날 다시 시도
JUDGED_MONTHS = tuple(f"{y}-{m:02d}" for y, m in [(2026, 11), (2026, 12)] + [(2027, k) for k in range(1, 11)])
MIN_JUDGED = 10
PRICE_HISTORY_DAYS = 400
ET = ZoneInfo("America/New_York")
US_CLOSE_SETTLED = (16, 15)

PriceFn = Callable[[str, str, str], pd.DataFrame]


def _default_prices(ticker: str, start: str, end: str) -> pd.DataFrame:
    from core.candidate_ledger import default_price_provider

    return default_price_provider(ticker, start, end)


def _default_members(d: date) -> list[str]:
    from core.point_in_time_universe import get_constituents_as_of

    return get_constituents_as_of(d.isoformat())


def _close(df: Optional[pd.DataFrame]) -> Optional[pd.Series]:
    """조정 종가(없으면 종가), tz 없는 날짜 인덱스."""
    if df is None or df.empty or "Close" not in df:
        return None
    col = df["Adj Close"] if "Adj Close" in df.columns and df["Adj Close"].notna().any() else df["Close"]
    s = pd.to_numeric(col, errors="coerce").dropna()
    idx = pd.DatetimeIndex(s.index)
    s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def latest_settled_day(spy: pd.Series, now: datetime) -> Optional[date]:
    """완성된(미 동부 16:15 이후) 최신 거래일."""
    now_et = now.astimezone(ET)
    cut = now_et.date() if (now_et.hour, now_et.minute) >= US_CLOSE_SETTLED else now_et.date() - timedelta(days=1)
    s = spy.loc[:pd.Timestamp(cut)]
    return s.index.max().date() if not s.empty else None


def scores(closes: pd.DataFrame) -> dict[str, pd.Series]:
    """closes: 날짜×종목 조정 종가, 마지막 행이 형성일 D. 규칙별 점수(클수록 먼저). 계산 못 하는 종목은 빠진다."""
    if len(closes) < LOOKBACK:
        return {k: pd.Series(dtype=float) for k in ARMS}
    last = closes.iloc[-1]
    mom6 = last / closes.iloc[-127] - 1
    mom12 = closes.iloc[-22] / closes.iloc[-253] - 1
    alive = last.notna()
    return {"MOM6": mom6[alive].dropna(), "MOM12_1": mom12[alive].dropna()}


def pick(score: pd.Series, n: int = TOP_N) -> list[str]:
    df = pd.DataFrame({"t": score.index, "s": score.values})
    return list(df.sort_values(["s", "t"], ascending=[False, True])["t"][:n])


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


def record(*, path: Optional[Path] = None, price_fn: PriceFn = _default_prices,
           members_fn: Callable[[date], Iterable[str]] = _default_members, now: Optional[datetime] = None) -> dict:
    """그달 묶음이 아직 없으면 오늘(최신 완성 거래일) 형성해 한 줄 추가. 있으면 아무것도 하지 않는다(수정 불가)."""
    now = now or datetime.now(timezone.utc)
    end = (now.date() + timedelta(days=2)).isoformat()
    spy = _close(price_fn("SPY", (now.date() - timedelta(days=PRICE_HISTORY_DAYS)).isoformat(), end))
    if spy is None or spy.empty:
        return {"recorded": False, "reason": "SPY 가격 없음"}
    day = latest_settled_day(spy, now)
    if day is None or day < FORWARD_START:
        return {"recorded": False, "reason": f"기록 시작({FORWARD_START}) 전", "date": day and day.isoformat()}
    month = day.strftime("%Y-%m")
    rows = load_ledger(path)
    if any(r.get("month") == month for r in rows):
        return {"recorded": False, "reason": "이번 달 묶음 이미 기록됨", "month": month}
    days = spy.loc[:pd.Timestamp(day)].index
    start = (day - timedelta(days=PRICE_HISTORY_DAYS)).isoformat()
    members = sorted(set(members_fn(day)) - {"SPY"})
    cols, failed = {}, 0
    for t in members:
        try:
            s = _close(price_fn(t, start, end))
        except Exception:  # noqa: BLE001 — 한 종목 실패가 묶음을 막지 않는다(실패 수는 남긴다)
            s = None
        if s is None:
            failed += 1
            continue
        cols[t] = s.reindex(days)
    sc = scores(pd.DataFrame(cols, index=days).iloc[-LOOKBACK:])
    n_scored = len(sc[PRIMARY])
    if n_scored < MIN_NAMES:
        return {"recorded": False, "reason": f"점수 낸 후보 {n_scored}개 < {MIN_NAMES} — 내일 다시", "month": month}
    arms = {}
    for k in ARMS:
        picks = pick(sc[k])
        arms[k] = {"picks": picks, "scores": {t: round(float(sc[k][t]), 6) for t in picks}, "n_scored": len(sc[k])}
    row = {"month": month, "formed_on": day.isoformat(), "recorded_at": now.isoformat(timespec="seconds"),
           "judge_version": JUDGE_VERSION, "n_members": len(members), "n_price_failed": failed, "arms": arms}
    p = Path(path or LEDGER)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"recorded": True, "month": month, "formed_on": day.isoformat(),
            "picks": {k: v["picks"] for k, v in row["arms"].items()}}


def cohort_result(row: dict, arm: str, closes: dict[str, pd.Series], spy: pd.Series) -> Optional[dict]:
    """한 묶음의 수익. 진입 = 형성일 다음 거래일 종가, 청산 = 진입 뒤 252거래일 종가(아직이면 최신 종가로 중간 평가)."""
    after = spy.index[spy.index > pd.Timestamp(row["formed_on"])]
    if len(after) == 0:
        return None
    entry = after[0]
    complete = len(after) > HOLD_DAYS
    exit_ = after[HOLD_DAYS] if complete else after[-1]
    rets = []
    for t in row["arms"][arm]["picks"]:
        s = closes.get(t)
        seg = s.loc[entry:exit_] if s is not None else None
        if seg is None or seg.empty or seg.index[0] != entry:
            rets.append(None)
            continue
        rets.append(float(seg.iloc[-1] / seg.iloc[0] - 1))
    known = [r for r in rets if r is not None]
    if not known:
        return None
    port = sum(known) / len(known) - 2 * COST_BPS / 1e4
    bench = float(spy.loc[exit_] / spy.loc[entry] - 1)
    return {"month": row["month"], "entry": entry.date().isoformat(), "exit": exit_.date().isoformat(), "complete": complete,
            "days": int(min(len(after) - 1, HOLD_DAYS)), "return": port, "spy": bench, "excess": port - bench,
            "missing_prices": len(rets) - len(known)}


def evaluate(rows: list[dict], closes: dict[str, pd.Series], spy: pd.Series) -> dict:
    """기록된 묶음으로 규칙별 경과·판정. closes: 종목별 조정 종가, spy: SPY 조정 종가."""
    out: dict[str, Any] = {"judge_version": JUDGE_VERSION, "records": len(rows), "target": TARGET, "arms": {}}
    for arm in ARMS:
        res = [c for r in sorted(rows, key=lambda r: r["month"]) if (c := cohort_result(r, arm, closes, spy))]
        judged = [c for c in res if c["month"] in JUDGED_MONTHS]
        done = [c for c in judged if c["complete"]]
        ex = [c["excess"] for c in done]
        a: dict[str, Any] = {"label": ARMS[arm], "cohorts": res, "judged_recorded": len(judged), "judged_complete": len(done),
                             "mean_excess": statistics.fmean(ex) if ex else None,
                             "median_excess": statistics.median(ex) if ex else None,
                             "hit_rate_target": (sum(e >= TARGET for e in ex) / len(ex)) if ex else None}
        open_ = [c["excess"] for c in judged if not c["complete"]]
        a["interim_mean_excess_open"] = statistics.fmean(open_) if open_ else None
        all_months_passed = any(r["month"] > JUDGED_MONTHS[-1] for r in rows)
        ready = len(judged) >= MIN_JUDGED and len(done) == len(judged) and (len(judged) == len(JUDGED_MONTHS) or all_months_passed)
        if arm != PRIMARY:
            a["verdict"] = "참고(판정 대상 아님)"
        elif not ready:
            a["verdict"] = f"판정 전 (완료 {len(done)}/{len(JUDGED_MONTHS)}묶음)"
        else:
            a["verdict"] = "PASS" if (a["mean_excess"] >= TARGET and a["median_excess"] > 0) else "FAIL"
        out["arms"][arm] = a
    out["verdict"] = out["arms"][PRIMARY]["verdict"]
    return out


def evaluate_live(path: Optional[Path] = None, price_fn: PriceFn = _default_prices) -> dict:
    """VM 가격으로 지금까지의 경과(주간 엔진 점검·화면용)."""
    rows = load_ledger(path)
    if not rows:
        return {"judge_version": JUDGE_VERSION, "records": 0, "verdict": f"판정 전 (완료 0/{len(JUDGED_MONTHS)}묶음)", "arms": {}}
    start = min(r["formed_on"] for r in rows)
    end = (date.today() + timedelta(days=2)).isoformat()
    spy = _close(price_fn("SPY", start, end))
    tickers = {t for r in rows for a in r["arms"].values() for t in a["picks"]}
    closes = {t: s for t in tickers if (s := _close(price_fn(t, start, end))) is not None}
    return evaluate(rows, closes, spy)


def summary_line(ev: dict) -> str:
    """주간 점검·화면 한 줄: 기록 수, 판정, 본 판정 규칙의 경과."""
    a = (ev.get("arms") or {}).get(PRIMARY) or {}
    parts = [f"{ev.get('records', 0)}개월 기록", str(ev.get("verdict"))]
    if a.get("mean_excess") is not None:
        parts.append(f"완료 묶음 평균 초과 {a['mean_excess'] * 100:+.1f}%p")
    if a.get("interim_mean_excess_open") is not None:
        parts.append(f"진행 중 묶음 현재 평균 {a['interim_mean_excess_open'] * 100:+.1f}%p(판정 아님)")
    return " · ".join(parts)
