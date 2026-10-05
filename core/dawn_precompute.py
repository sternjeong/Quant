"""새벽 미리 계산 (2026-10-05) — 화면에서 버튼을 눌러 기다리던 계산을 기본 설정으로 매일 새벽에 미리 돌려 둔다.

사용자 요청(2026-10-05): "내가 당일 눌러서 확인할 수 있는거 미리 새벽 시간에 일단 돌려놔주라 그러면 빠르게 내가
확인할 수 있잖아." — 자동 잡 dawn_precompute(매일 06:40 KST)가 run_all() 을 부른다.

단계는 순서대로 돌고, 하나가 실패해도 나머지는 계속한다(실패는 요약에 남기고 텔레그램 1건).
  1. prices             가격 최신화 — 코어 17자산·BIL·SPY·TLT·^VIX 와 지금 추천·보유 중인 종목의 최근 봉을 장 마감 뒤
                        값으로 다시 받는다. 밤 00:10 신호 잡 같은 야간 잡은 미국 장중(한국 자정 = 미 동부 오전)에 돌아
                        마지막 봉이 장중 값으로 저장될 수 있고, 명시적 end 로 읽는 백테스트는 그 봉을 다시 받지 않으므로
                        여기서 먼저 고친다(core.market_data.get_price_history, cache_ttl=0).
  2. performance        '챔피언 성과' A. 백테스트 기본 기간(최근 5년) — core.champion_performance 캐시. 화면이 이미 자동으로
                        읽는 곳이라 화면을 고치지 않아도 바로 보인다. 오래된 기본 기간 캐시는 정리한다(화면이 캐시 목록을
                        매번 전부 읽기 때문).
  3. satellite_pit      '챔피언 전략' 2. 새틀라이트 '📌 point-in-time 새틀라이트 계산'(균등가중) — 이 모듈 캐시.
  4. champion_backtest  '챔피언 전략' 3. 백테스트 기본(오늘 - 3년 ~ 오늘, 새틀라이트 15%, 균등가중, 칼라 헤지 없음) — 이 모듈 캐시.
  5. satellite_scan     '챔피언 전략' 2. 새틀라이트 '🔍 새틀라이트 후보 스캔'(S&P500 전체 순차 조회, 참고용 근사) — 이 모듈 캐시.
                        네트워크를 가장 많이 쓰고 느려 맨 뒤에 둔다.

기준일(as_of)은 한국 날짜다. 06:40 KST 는 서버(UTC) 날짜로 아직 전날이라 date.today() 를 쓰면, 가격 조회의 end 가
배타적이어서 막 끝난 미국 장 봉이 빠진다. 한국 날짜를 end 로 주면 그 봉이 들어가고, 09:00 KST 이후 화면 기본값
(서버의 date.today())과도 같은 날짜가 된다.

계산 함수는 화면 버튼이 부르는 것과 같은 함수다(새 전략 로직 없음). 주문 경로를 import 하지 않는다.
화면은 load_latest() 로 가장 최근 결과(최대 MAX_AGE_DAYS 일)를 읽어 바로 보여 주고, 버튼은 그대로 있어 다른 설정이나
지금 데이터로 다시 계산할 수 있다. 실행 기록: data/cache/dawn_precompute_status.json(최근 HISTORY_KEEP 회).
무거운 모듈(champion_strategy 등)은 함수 안에서 import 한다 — 화면·테스트가 이 모듈을 가볍게 읽을 수 있게.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
STATUS_FILE = "dawn_precompute_status.json"
PREFIX = "dawn_"
SCHEMA_VERSION = 1  # 저장 형식이 바뀌면 올린다(옛 파일은 자동으로 무시된다)
KST = ZoneInfo("Asia/Seoul")
JOB_ID = "dawn_precompute"

DEFAULT_SIZING = "equal"  # 화면 '종목 간 비중 배분 방식' 기본값(균등가중, 검증됨)
BACKTEST_YEARS = 3  # 챔피언 전략 '3. 백테스트' 시작일 기본값 = 오늘 - 3년
KEEP_PER_KIND = 7  # 종류마다 남길 파일 수
MAX_AGE_DAYS = 7  # 화면이 자동으로 보여 줄 최대 나이(일)
HISTORY_KEEP = 14  # 실행 기록 보관 회수
PERF_KEEP_DAYS = 14  # 챔피언 성과 '기본 기간' 캐시를 남길 기간(일)

KIND_SATELLITE_PIT = "satellite_pit"
KIND_SATELLITE_SCAN = "satellite_scan"
KIND_CHAMPION_BACKTEST = "champion_backtest"
KINDS = (KIND_SATELLITE_PIT, KIND_SATELLITE_SCAN, KIND_CHAMPION_BACKTEST)

STATUS_OK, STATUS_PARTIAL, STATUS_SKIPPED = "ok", "partial", "skipped"

StepFn = Callable[[date, Optional[Path]], str]


# ============================================================================================
# 날짜·시각
# ============================================================================================

def kst_today(now: Optional[datetime] = None) -> date:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(KST).date()


def schedule_label() -> str:
    """잡 시각 'HH:MM'(KST) — core.job_schedule 에서 읽어 화면·설명 문구가 낡지 않게 한다."""
    try:
        from core.job_schedule import SCHEDULED_JOBS_BY_ID

        cron = SCHEDULED_JOBS_BY_ID[JOB_ID].cron
        return f"{int(cron['hour']):02d}:{int(cron['minute']):02d}"
    except Exception:  # noqa: BLE001 - 문구용이라 실패해도 기본값
        return "06:40"


def default_backtest_start(today: date, years: int = BACKTEST_YEARS) -> date:
    """챔피언 전략 '3. 백테스트' 시작일 기본값(오늘 - years 년). 2월 29일이면 28일로(화면이 같은 함수를 쓴다)."""
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================================================
# JSON 저장 형식 — DataFrame·Series 를 표식이 붙은 dict 로 바꿨다가 되돌린다
# ============================================================================================

def _encode(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        out = {
            "columns": [str(c) for c in obj.columns],
            "records": [[_encode(v) for v in row] for row in obj.itertuples(index=False, name=None)],
        }
        if not isinstance(obj.index, pd.RangeIndex):  # 날짜 인덱스(자산곡선 등)를 잃지 않게
            is_dt = isinstance(obj.index, pd.DatetimeIndex)
            out["datetime_index"] = is_dt
            out["index"] = [i.isoformat() if is_dt else _encode(i) for i in obj.index]
        return {"__df__": out}
    if isinstance(obj, pd.Series):
        is_dt = isinstance(obj.index, pd.DatetimeIndex)
        return {"__series__": {
            "name": None if obj.name is None else str(obj.name),
            "datetime_index": is_dt,
            "index": [i.isoformat() if is_dt else _encode(i) for i in obj.index],
            "values": [_encode(v) for v in obj.to_numpy()],
        }}
    if isinstance(obj, dict):
        return {str(k): _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_encode(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if isinstance(obj, np.datetime64):
        return pd.Timestamp(obj).isoformat()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    return obj


def _decode(obj: Any) -> Any:
    if isinstance(obj, dict):
        if set(obj) == {"__df__"}:
            d = obj["__df__"]
            df = pd.DataFrame(d["records"], columns=d["columns"])
            if "index" in d:
                df.index = pd.to_datetime(d["index"]) if d.get("datetime_index") else d["index"]
            return df
        if set(obj) == {"__series__"}:
            s = obj["__series__"]
            index = pd.to_datetime(s["index"]) if s.get("datetime_index") else s["index"]
            try:
                return pd.Series([np.nan if v is None else v for v in s["values"]], index=index,
                                 name=s.get("name"), dtype="float64")
            except (TypeError, ValueError):  # 숫자가 아닌 시리즈는 그대로
                return pd.Series(s["values"], index=index, name=s.get("name"), dtype=object)
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ============================================================================================
# 화면용 결과 캐시 (data/cache/dawn_<종류>_<기준일>_<해시>.json)
# ============================================================================================

def _strategy_version() -> str:
    from core import champion_strategy as cs

    return cs.CHAMPION_STRATEGY_VERSION


def result_params(kind: str, as_of: date, sizing_method: str = DEFAULT_SIZING, **extra: Any) -> dict:
    params = {"kind": kind, "as_of": as_of.isoformat(), "sizing_method": sizing_method,
              "strategy_version": _strategy_version(), "schema": SCHEMA_VERSION}
    params.update({k: _encode(v) for k, v in extra.items()})
    return params


def _result_path(params: dict, cache_dir: Optional[Path] = None) -> Path:
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
    return Path(cache_dir or CACHE_DIR) / f"{PREFIX}{params['kind']}_{params['as_of']}_{digest}.json"


def _kind_files(kind: str, cache_dir: Optional[Path] = None) -> list[Path]:
    """이 종류의 파일 — 이름(기준일 포함) 내림차순 = 최근 것부터."""
    return sorted(Path(cache_dir or CACHE_DIR).glob(f"{PREFIX}{kind}_*.json"), reverse=True)


def save_result(kind: str, params: dict, result: dict, *, cache_dir: Optional[Path] = None) -> Path:
    path = _result_path(params, cache_dir)
    _atomic_write_json(path, {"kind": kind, "params": params, "as_of": params["as_of"],
                              "computed_at": _now_iso(), "result": _encode(result)})
    for old in _kind_files(kind, cache_dir)[KEEP_PER_KIND:]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def load_latest(kind: str, *, sizing_method: str = DEFAULT_SIZING, today: Optional[date] = None,
                max_age_days: int = MAX_AGE_DAYS, cache_dir: Optional[Path] = None) -> Optional[dict]:
    """화면이 바로 보여 줄 가장 최근 결과. 없거나(다른 사이징·다른 전략 버전·max_age_days 보다 오래됨) 깨졌으면 None.

    반환: {"as_of", "computed_at", "params", "result"(DataFrame·Series 복원), "is_today", "age_days"}.
    is_today 는 한국 날짜 기준 — 오늘 새벽 계산이 아직 없거나 실패했으면 False(화면이 그렇게 적는다).
    계산·네트워크 없음(파일 읽기만).
    """
    today = today or kst_today()
    version = _strategy_version()
    for path in _kind_files(kind, cache_dir):
        env = _read_json(path)
        if not env:
            continue
        params = env.get("params") or {}
        if (params.get("schema") != SCHEMA_VERSION or params.get("strategy_version") != version
                or params.get("sizing_method") != sizing_method or params.get("kind") != kind):
            continue
        try:
            as_of = date.fromisoformat(str(env.get("as_of")))
        except ValueError:
            continue
        age = (today - as_of).days
        if age > max_age_days:
            continue
        try:
            result = _decode(env.get("result") or {})
        except Exception:  # noqa: BLE001 - 형식이 깨진 파일은 없는 것으로
            continue
        return {"as_of": as_of.isoformat(), "computed_at": env.get("computed_at"), "params": params,
                "result": result, "is_today": age <= 0, "age_days": max(age, 0)}
    return None


def loaded_caption(entry: dict, what: str = "") -> str:
    """화면에 붙이는 한 줄 — 언제 누가 계산한 결과인지 밝힌다."""
    when = str(entry.get("computed_at") or "?")[:16].replace("T", " ")
    text = (f"🌅 새벽 자동 계산 결과(매일 {schedule_label()} KST, 자동 잡 {JOB_ID}) · 기준일 {entry.get('as_of')} · "
            f"계산 {when} UTC")
    if what:
        text += f" · {what}"
    if not entry.get("is_today"):
        text += f" — 오늘 새벽 계산이 아직 없거나 실패해 {entry.get('age_days')}일 전 결과입니다"
    return text + ". 지금 데이터나 다른 설정으로 보려면 버튼을 누르세요."


# ============================================================================================
# 단계
# ============================================================================================

def refresh_tickers() -> list[str]:
    """마지막 봉을 다시 받을 종목: 코어 17자산·BIL·SPY·TLT·^VIX + 지금 보유(야간 신호 상태)·추천(마지막 재추천) 종목."""
    from core import champion_performance as cp
    from core import champion_strategy as cs

    tickers = list(cs.CORE_UNIVERSE) + [cs.CORE_CASH_ETF, cs.MARKET_FILTER_TICKER, cp.BOND_TICKER, cs.VIX_TICKER]
    try:
        holdings = cs.get_current_holdings() or {}
        tickers += list(holdings.get("tickers") or [])
    except Exception:  # noqa: BLE001 - 보유 상태가 없거나 깨져도 기본 목록은 받는다
        pass
    try:
        from core import champion_recommendation as cr

        sat = (cr.load_latest_cached() or {}).get("satellite") or {}
        tickers += list((sat.get("today") or {}).get("picks") or [])
        tickers += list((sat.get("if_bought_at_last_rebal") or {}).get("picks") or [])
    except Exception:  # noqa: BLE001
        pass
    out: list[str] = []
    for t in tickers:
        if t and t not in out:
            out.append(t)
    return out


def step_prices(as_of: date, cache_dir: Optional[Path] = None) -> str:
    from core import market_data as md

    tickers = refresh_tickers()
    start = (as_of - timedelta(days=30)).isoformat()
    bad: list[str] = []
    last: list[date] = []
    for t in tickers:
        try:
            df = md.get_price_history(t, start=start, end=None, interval="1d", use_cache=True, cache_ttl=0)
        except Exception:  # noqa: BLE001 - 종목 하나 실패는 세기만 한다
            df = None
        if df is None or df.empty:
            bad.append(t)
        else:
            last.append(pd.Timestamp(df.index.max()).date())
    if not tickers or len(bad) > len(tickers) // 2:
        raise RuntimeError(f"가격을 받지 못한 종목이 너무 많음 {len(bad)}/{len(tickers)}: {', '.join(bad[:8])}")
    text = f"{len(tickers) - len(bad)}/{len(tickers)}종목 최근 봉 갱신(마지막 봉 {max(last).isoformat()})"
    return text + (f", 실패 {', '.join(bad[:5])}" if bad else "")


def prune_performance_caches(as_of: date, keep_days: int = PERF_KEEP_DAYS) -> int:
    """챔피언 성과 캐시 중 '기본 기간(최근 5년)'이고 종료일이 keep_days 보다 오래된 것만 지운다.

    화면(load_latest_cached)은 캐시 파일을 매번 전부 읽으므로 매일 하나씩 쌓이면 점점 느려진다. 사용자가 직접 고른
    기간(최근 3년·직접 지정)의 결과는 지우지 않는다.
    """
    from core import champion_performance as cp

    cutoff = (as_of - timedelta(days=keep_days)).isoformat()
    removed = 0
    for row in cp.list_cached():
        p = row.get("params") or {}
        end = str(p.get("end") or "")
        try:
            is_default = p.get("start") == cp.default_start(date.fromisoformat(end))
        except ValueError:
            continue
        if is_default and end < cutoff:
            try:
                Path(row["path"]).unlink()
                removed += 1
            except OSError:
                pass
    return removed


def step_performance(as_of: date, cache_dir: Optional[Path] = None) -> str:
    from core import champion_performance as cp
    from core import champion_strategy as cs

    start = cp.default_start(as_of)
    res = cp.compute_backtest_performance(start, as_of.isoformat(), satellite_weight=cs.SATELLITE_WEIGHT)
    pruned = prune_performance_caches(as_of)
    s = res.get("summary") or {}
    text = f"{start}~{s.get('end')} 거래 {s.get('n_trades')}건"
    if res.get("from_cache"):
        text += "(이미 계산돼 있어 그대로 둠)"
    return text + (f", 오래된 기본 기간 캐시 {pruned}개 정리" if pruned else "")


def step_satellite_pit(as_of: date, cache_dir: Optional[Path] = None) -> str:
    from core import champion_strategy as cs

    res = cs.compute_satellite_recommendation_point_in_time(as_of_date=as_of.isoformat(), sizing_method=DEFAULT_SIZING)
    save_result(KIND_SATELLITE_PIT, result_params(KIND_SATELLITE_PIT, as_of), res, cache_dir=cache_dir)
    return f"직전 리밸런싱일 {res.get('rebal_date')} · 선정 {', '.join(res.get('selected') or []) or '없음'}"


def _trim_backtest(bt: dict) -> dict:
    """run_champion_backtest 결과에서 화면 '3. 백테스트'가 쓰는 것만 남긴다(코어 일별 비중표는 크고 화면이 안 씀)."""
    core = bt.get("core") or {}
    sat = bt.get("satellite") or {}
    return {
        "start": bt.get("start"), "end": bt.get("end"),
        "satellite_weight_applied": bt.get("satellite_weight_applied"),
        "metrics": bt.get("metrics"), "equity_net": bt.get("equity_net"), "ret_net": bt.get("ret_net"),
        "core": {k: core.get(k) for k in ("start", "end", "metrics", "ret_net", "equity_net")},
        "satellite": {k: sat.get(k) for k in ("start", "end", "metrics", "ret_net", "equity_net", "rebal_log",
                                              "tickers_ever_held")},
    }


def step_champion_backtest(as_of: date, cache_dir: Optional[Path] = None) -> str:
    from core import champion_strategy as cs
    from core import market_data as md

    start = default_backtest_start(as_of).isoformat()
    end = as_of.isoformat()
    bt = cs.run_champion_backtest(start, end, satellite_weight=cs.SATELLITE_WEIGHT,
                                  satellite_sizing_method=DEFAULT_SIZING)
    trimmed = _trim_backtest(bt)
    # 화면은 결과를 그릴 때 SPY 비교선을 가격 캐시에서 읽는다 — 미리 계산한 결과를 열 때는 그 조회도 하지 않게 함께 저장한다.
    try:
        spy = md.get_price_history("SPY", start=bt["start"], end=bt["end"])
        trimmed["spy_equity"] = (spy["Close"] / spy["Close"].iloc[0] * 100.0) if spy is not None and not spy.empty else None
    except Exception:  # noqa: BLE001 - 비교선이 없어도 결과는 저장
        trimmed["spy_equity"] = None
    params = result_params(KIND_CHAMPION_BACKTEST, as_of, start=start, end=end,
                           satellite_weight=round(float(cs.SATELLITE_WEIGHT), 4), collar=False)
    save_result(KIND_CHAMPION_BACKTEST, params, trimmed, cache_dir=cache_dir)
    n_rebal = len((bt.get("satellite") or {}).get("rebal_log") or [])
    return f"{start}~{end} · 새틀라이트 반기 선정 {n_rebal}회"


def step_satellite_scan(as_of: date, cache_dir: Optional[Path] = None) -> str:
    from core import champion_strategy as cs

    res = cs.compute_satellite_recommendation(sizing_method=DEFAULT_SIZING)
    save_result(KIND_SATELLITE_SCAN, result_params(KIND_SATELLITE_SCAN, as_of), res, cache_dir=cache_dir)
    cands = res.get("candidates")
    n_cands = len(cands) if cands is not None else 0
    return f"{res.get('scanned_count')}종목 스캔 · 돌파 후보 {n_cands}개 · 선정 {', '.join(res.get('selected') or []) or '없음'}"


STEPS: tuple[tuple[str, str, StepFn], ...] = (
    ("prices", "가격 최신화", step_prices),
    ("performance", "챔피언 성과 — 최근 5년 백테스트", step_performance),
    ("satellite_pit", "챔피언 전략 — point-in-time 새틀라이트", step_satellite_pit),
    ("champion_backtest", "챔피언 전략 — 3. 백테스트(최근 3년)", step_champion_backtest),
    ("satellite_scan", "챔피언 전략 — 새틀라이트 후보 스캔(S&P500)", step_satellite_scan),
)


# ============================================================================================
# 실행·기록·알림
# ============================================================================================

def _status_path(cache_dir: Optional[Path] = None) -> Path:
    return Path(cache_dir or CACHE_DIR) / STATUS_FILE


def load_status(cache_dir: Optional[Path] = None) -> dict:
    return _read_json(_status_path(cache_dir)) or {}


def record_status(summary: dict, cache_dir: Optional[Path] = None) -> None:
    st = load_status(cache_dir)
    hist = list(st.get("history") or [])
    hist.append({k: summary.get(k) for k in ("as_of", "status", "finished_at", "seconds", "failed", "reason")})
    _atomic_write_json(_status_path(cache_dir), {"latest": summary, "history": hist[-HISTORY_KEEP:]})


def run_all(as_of: Optional[date] = None, *, steps: Optional[tuple] = None,
            notify: Optional[Callable[[str], Any]] = None, cache_dir: Optional[Path] = None) -> dict:
    """모든 단계를 순서대로 돌린다. 한 단계의 예외는 그 단계만 실패로 남기고 다음 단계로 간다.

    실패가 있을 때만 notify(텔레그램)로 짧은 요약 1건을 보낸다(모두 정상이면 조용히). 결과 요약을 돌려주고 기록한다.
    """
    as_of = as_of or kst_today()
    t_all = time.monotonic()
    rows = []
    for key, label, fn in (steps or STEPS):
        t0 = time.monotonic()
        try:
            detail = fn(as_of, cache_dir)
            status = STATUS_OK
        except Exception as exc:  # noqa: BLE001 - 한 단계 실패가 나머지를 막지 않게
            detail = f"{type(exc).__name__}: {exc}"
            status = "error"
        row = {"key": key, "label": label, "status": status, "detail": str(detail)[:300],
               "seconds": round(time.monotonic() - t0, 1)}
        rows.append(row)
        print(f"  - [{key}] {status} {row['seconds']}s {row['detail']}")
    failed = [r["key"] for r in rows if r["status"] != STATUS_OK]
    summary = {
        "as_of": as_of.isoformat(), "finished_at": _now_iso(), "seconds": round(time.monotonic() - t_all, 1),
        "status": STATUS_PARTIAL if failed else STATUS_OK, "failed": failed, "reason": None, "steps": rows,
        "notified": False,
    }
    if failed and notify is not None:
        try:
            summary["notified"] = bool(notify(failure_message(summary)))
        except Exception as exc:  # noqa: BLE001 - 알림 실패가 기록을 막지 않게
            print(f"  - 새벽 미리 계산 실패 알림 전송 실패(무시): {type(exc).__name__}: {exc}")
    try:
        record_status(summary, cache_dir)
    except OSError as exc:
        print(f"  - 새벽 미리 계산 기록 저장 실패(무시): {exc}")
    return summary


def record_skip(reason: str, as_of: Optional[date] = None, cache_dir: Optional[Path] = None) -> dict:
    """VM 여유가 없어 이번 회차를 통째로 건너뛴 경우의 기록."""
    summary = {"as_of": (as_of or kst_today()).isoformat(), "finished_at": _now_iso(), "seconds": 0.0,
               "status": STATUS_SKIPPED, "failed": [], "reason": reason, "steps": []}
    try:
        record_status(summary, cache_dir)
    except OSError as exc:
        print(f"  - 새벽 미리 계산 기록 저장 실패(무시): {exc}")
    return summary


def failure_message(summary: dict) -> str:
    rows = summary.get("steps") or []
    bad = [r for r in rows if r.get("status") != STATUS_OK]
    lines = [f"⚠️ [새벽 미리 계산] {len(rows)}개 중 {len(bad)}개 실패 (기준일 {summary.get('as_of')})"]
    lines += [f"- {r['label']}: {str(r['detail'])[:160]}" for r in bad]
    lines.append("나머지는 저장됐습니다. 실패한 계산은 화면 버튼으로 직접 돌릴 수 있습니다(주문 없음). "
                 f"원하지 않으면 '/processes off {JOB_ID}'.")
    return "\n".join(lines)[:1500]


def skip_message(reason: str) -> str:
    return (f"⚠️ [새벽 미리 계산] 오늘은 건너뜀 — {reason}. 화면 버튼으로 직접 계산할 수 있습니다(주문 없음). "
            f"원하지 않으면 '/processes off {JOB_ID}'.")
