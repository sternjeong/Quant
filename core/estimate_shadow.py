"""애널리스트 추정치 매일 기록(shadow) — 우리 손으로 쌓는 시점 기준(point-in-time) 추정치 이력 (2026-11-10, 사용자 요청
"연구도 실적 추정치 변화 등으로 확장해서 이어서 진행").

왜: 추정치 변화(리비전)는 가격 밖의 정보지만 과거 이력(IBES 등)은 무료로 구할 수 없다. 그래서 지금부터 매일 yfinance 가 보여 주는
'현재' 추정치를 기록 시각과 함께 남긴다. 6~12개월 쌓이면 미리 보기가 전혀 없는 진짜 표본 밖(out-of-sample) 자료가 되고, 그때 새 id 로
사전 등록 연구를 한다(docs/ESTIMATE_SHADOW_SPEC.md). 이 모듈로는 아무것도 매매하지 않는다 — 주문 경로와 연결되어 있지 않고 LLM 도 쓰지 않는다.

기록(종목마다 하루 한 번, 덮어쓰지 않음):
  - eps_trend: 분기·연도별(0q, +1q, 0y, +1y) EPS 컨센서스 현재 값과 7/30/60/90일 전 값
  - eps_revisions: 최근 7/30일 상향·하향 애널리스트 수
  - earnings_estimate / revenue_estimate: 평균·최저·최고·애널리스트 수·1년 전 실적·성장률
  - period_end_dates: 0q/+1q/0y/+1y 가 가리키는 회계 기간 끝(가능할 때만 — yfinance 내부 값이라 없을 수 있음)
  - recommendations_summary: 강력매수~강력매도 의견 수(이번 달·지난 몇 달)
  - price_targets: 목표주가 현재·최고·최저·평균·중앙값
저장: data/estimate_shadow/estimates.sqlite 의 snapshots 표. (record_date[KST], ticker, kind) 가 유일 — 같은 날 다시 돌면 이미 있는 줄은
건너뛴다(INSERT OR IGNORE). 과거 줄을 고치거나 지우는 코드는 없다(append-only). 실행마다 runs 표에 요약 한 줄.
대상: 오늘 기준 S&P 500 구성종목(data/sp500_historical_constituents.csv 의 최신 행, 최대 MAX_TICKERS). 시간 상한 MAX_SECONDS 를 넘으면
멈추고, 시작 위치를 날짜마다 돌려서 늘 같은 종목이 빠지지 않게 한다.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "estimate_shadow" / "estimates.sqlite"
SCHEMA_VERSION = "estimate-shadow/v1"
KST = timezone(timedelta(hours=9))
MAX_TICKERS = 520
MAX_SECONDS = 12 * 60
PAUSE_SECONDS = 0.15
ABORT_AFTER_FIRST_FAILURES = 25   # 처음부터 연속으로 이만큼 실패하면(차단·네트워크 끊김) 그날은 멈춘다
KINDS = ("eps_trend", "eps_revisions", "earnings_estimate", "revenue_estimate", "period_end_dates",
         "recommendations_summary", "price_targets")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    source TEXT NOT NULL,
    UNIQUE (record_date, ticker, kind)
);
CREATE INDEX IF NOT EXISTS ix_snapshots_ticker ON snapshots (ticker, kind, record_date);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    summary TEXT NOT NULL
);
"""


# ---------------------------------------------------------------- 저장소
def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=30)
    con.executescript(_SCHEMA)
    return con


def _clean(x: Any) -> Any:
    """JSON 으로 저장할 값: numpy/pandas → 파이썬, NaN/inf → None."""
    if x is None or isinstance(x, (str, bool)):
        return x
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if hasattr(x, "item") and not hasattr(x, "__len__"):
        try:
            x = x.item()
        except (TypeError, ValueError):
            pass
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return int(x)
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if hasattr(x, "isoformat"):
        return x.isoformat()
    try:
        f = float(x)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return str(x)


def frame_records(df) -> Optional[list[dict]]:
    """yfinance DataFrame(행 = period 등) → [{'period': ..., 열: 값}] — 비었으면 None."""
    if df is None:
        return None
    if isinstance(df, dict):
        return [_clean(df)] if df else None
    if getattr(df, "empty", True):
        return None
    d = df.reset_index()
    return [_clean(r) for r in d.to_dict("records")]


# ---------------------------------------------------------------- 받기 (yfinance)
def _period_end_dates(t) -> Optional[list[dict]]:
    """0q/+1q/0y/+1y 의 회계 기간 끝. yfinance 공개 API 에 없어 내부 값(_analysis._earnings_trend)을 조심스럽게 읽는다."""
    try:
        items = getattr(getattr(t, "_analysis", None), "_earnings_trend", None) or []
        out = [{"period": str(i.get("period")), "endDate": i.get("endDate")} for i in items if isinstance(i, dict) and i.get("period")]
        return out or None
    except Exception:  # noqa: BLE001
        return None


def fetch_yfinance(ticker: str, ticker_factory: Optional[Callable[[str], Any]] = None) -> dict[str, Any]:
    """종목 하나의 추정치 묶음 {kind: payload 또는 None}. 항목별 실패는 그 항목만 None(오류 이름은 '_errors')."""
    if ticker_factory is None:
        import yfinance as yf

        ticker_factory = yf.Ticker
    t = ticker_factory(ticker)
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for kind, attr in (("eps_trend", "eps_trend"), ("eps_revisions", "eps_revisions"),
                       ("earnings_estimate", "earnings_estimate"), ("revenue_estimate", "revenue_estimate"),
                       ("recommendations_summary", "recommendations_summary"), ("price_targets", "analyst_price_targets")):
        try:
            out[kind] = frame_records(getattr(t, attr))
        except Exception as exc:  # noqa: BLE001 - 종목·항목별 실패 격리
            out[kind] = None
            errors[kind] = type(exc).__name__
        if kind == "revenue_estimate":
            out["period_end_dates"] = _period_end_dates(t)
    if errors:
        out["_errors"] = errors
    return out


# ---------------------------------------------------------------- 대상 종목
def default_tickers(as_of: Optional[date] = None, limit: int = MAX_TICKERS) -> list[str]:
    """오늘 기준 S&P 500 구성종목(yfinance 표기). 파일이 없거나 비면 빈 목록."""
    from core.point_in_time_universe import get_constituents_as_of

    d = as_of or datetime.now(KST).date()
    try:
        tickers = get_constituents_as_of(d.isoformat())
    except Exception:  # noqa: BLE001
        return []
    return sorted(set(tickers))[:limit]


def rotate(tickers: list[str], day: date) -> list[str]:
    """날짜마다 시작 위치를 돌린다(시간 상한에 걸려도 늘 같은 종목이 빠지지 않게)."""
    if not tickers:
        return []
    k = day.toordinal() % len(tickers)
    return tickers[k:] + tickers[:k]


# ---------------------------------------------------------------- 기록
def record(*, tickers: Optional[Iterable[str]] = None, path: Optional[Path] = None,
           fetch: Optional[Callable[[str], dict]] = None, now: Optional[Callable[[], datetime]] = None,
           max_seconds: float = MAX_SECONDS, pause: float = PAUSE_SECONDS,
           clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """오늘(KST) 추정치를 기록한다. 이미 있는 (날짜, 종목, 항목)은 건너뛴다(덮어쓰지 않음). 요약 dict 를 돌려준다."""
    now = now or (lambda: datetime.now(timezone.utc))
    fetch = fetch or fetch_yfinance
    started = now()
    day = started.astimezone(KST).date()
    names = rotate(list(tickers) if tickers is not None else default_tickers(day), day)
    t0 = clock()
    summary: dict[str, Any] = {"schema": SCHEMA_VERSION, "record_date": day.isoformat(), "n_tickers": len(names), "n_ok": 0,
                               "n_empty": 0, "n_failed": 0, "n_already": 0, "inserted": 0, "timed_out": False, "aborted": False,
                               "errors": {}}
    try:
        import yfinance as _yf  # noqa: F401

        summary["source_version"] = getattr(_yf, "__version__", "?")
    except Exception:  # noqa: BLE001
        summary["source_version"] = "?"
    source = f"yfinance {summary['source_version']}"
    with closing(connect(path)) as con:
        have = {r[0] for r in con.execute("SELECT DISTINCT ticker FROM snapshots WHERE record_date = ?", (day.isoformat(),))}
        streak = 0
        for i, tk in enumerate(names):
            if clock() - t0 > max_seconds:
                summary["timed_out"] = True
                summary["n_skipped_time"] = len(names) - i
                break
            if tk in have:
                summary["n_already"] += 1
                continue
            try:
                got = fetch(tk)
            except Exception as exc:  # noqa: BLE001 - 종목별 실패 격리
                summary["n_failed"] += 1
                name = type(exc).__name__
                summary["errors"][name] = summary["errors"].get(name, 0) + 1
                streak += 1
                if summary["n_ok"] == 0 and summary["n_empty"] == 0 and streak >= ABORT_AFTER_FIRST_FAILURES:
                    summary["aborted"] = True
                    break
                continue
            streak = 0
            stamp = now().isoformat(timespec="seconds")
            rows = [(day.isoformat(), stamp, tk, k, json.dumps(got[k], ensure_ascii=False, separators=(",", ":")), source)
                    for k in KINDS if got.get(k)]
            if got.get("_errors"):
                for name in got["_errors"].values():
                    summary["errors"][name] = summary["errors"].get(name, 0) + 1
            if not rows:
                summary["n_empty"] += 1
                continue
            cur = con.executemany("INSERT OR IGNORE INTO snapshots (record_date, recorded_at, ticker, kind, payload, source) "
                                  "VALUES (?, ?, ?, ?, ?, ?)", rows)
            con.commit()
            summary["inserted"] += max(cur.rowcount, 0)
            summary["n_ok"] += 1
            if pause > 0 and i + 1 < len(names):
                sleep(pause)
        summary["seconds"] = round(clock() - t0, 1)
        summary["ok"] = bool(not summary["aborted"] and (summary["n_ok"] > 0 or summary["n_already"] > 0 or not names))
        con.execute("INSERT INTO runs (record_date, started_at, finished_at, summary) VALUES (?, ?, ?, ?)",
                    (day.isoformat(), started.isoformat(timespec="seconds"), now().isoformat(timespec="seconds"),
                     json.dumps(summary, ensure_ascii=False)))
        con.commit()
    return summary


def format_summary(s: dict) -> str:
    return (f"{s.get('record_date')} 대상 {s.get('n_tickers')} · 기록 {s.get('n_ok')} · 이미 있음 {s.get('n_already')} · "
            f"빈 응답 {s.get('n_empty')} · 실패 {s.get('n_failed')} · 줄 {s.get('inserted')} · {s.get('seconds')}초"
            + (" · 시간 상한으로 멈춤" if s.get("timed_out") else "") + (" · 연속 실패로 중단" if s.get("aborted") else ""))


# ---------------------------------------------------------------- 읽기 (나중 연구용)
def load_history(ticker: str, kind: Optional[str] = None, path: Optional[Path] = None) -> list[dict]:
    """한 종목의 기록(날짜 순). 각 줄 = {record_date, recorded_at, kind, payload}."""
    p = Path(path or DB_PATH)
    if not p.exists():
        return []
    with closing(sqlite3.connect(str(p), timeout=30)) as con:
        q = "SELECT record_date, recorded_at, kind, payload FROM snapshots WHERE ticker = ?"
        args: list[Any] = [ticker]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        q += " ORDER BY record_date, kind"
        return [{"record_date": a, "recorded_at": b, "kind": k, "payload": json.loads(p_)} for a, b, k, p_ in con.execute(q, args)]


def coverage(path: Optional[Path] = None) -> dict[str, Any]:
    """쌓인 정도: 기록한 날 수, 첫·마지막 날, 종목 수, 줄 수, 마지막 실행 요약."""
    p = Path(path or DB_PATH)
    if not p.exists():
        return {"days": 0, "tickers": 0, "rows": 0}
    with closing(sqlite3.connect(str(p), timeout=30)) as con:
        days, first, last, tickers, rows = con.execute(
            "SELECT COUNT(DISTINCT record_date), MIN(record_date), MAX(record_date), COUNT(DISTINCT ticker), COUNT(*) FROM snapshots").fetchone()
        run = con.execute("SELECT summary FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return {"days": days or 0, "first": first, "last": last, "tickers": tickers or 0, "rows": rows or 0,
            "last_run": json.loads(run[0]) if run else None}
