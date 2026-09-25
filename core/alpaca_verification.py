"""Alpaca paper API 가정 검증을 사람 손 없이 돌리는 오케스트레이터 (2026-09-24).

배경: 사용자는 폰으로만 작업하고 VM 에 직접 접속해 검증 스크립트를 돌리기 어렵다. Alpaca paper 키는 VM
/opt/quant/.env 에만 있고 지금까지 실제 API 호출은 0회였다. 이 모듈은 읽기 전용 검증 5개를 순서대로 돌리고
PASS/FAIL/UNEXPECTED 를 JSON(data/verification/alpaca_YYYYMMDD_HHMM.json)으로 남긴다.

  1) idempotency_read_only : scripts/verify_alpaca_paper_idempotency.py 의 기본(읽기 전용) 모드 — write=False 고정
  2) corporate_actions     : scripts/verify_alpaca_corporate_actions.py 의 알려진 사례(AAPL 분할·배당) 대조
  3) price_crosscheck      : scripts/verify_price_crosscheck.py 의 최근 구간 대조 + AAPL 분할 조정 여부
  4) account_schema        : core.account_sync.sync_paper_account(persist=False) — 계좌/포지션 스키마

불변 조건:
- 주문을 내는 --write 경로는 이 모듈이 절대 호출하지 않는다(verify(..., write=False) 고정, 주문 URL 미사용).
- 키(ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET)는 환경변수에서만 읽고, 저장·출력·텔레그램 문자열에서
  값을 지운다(_redact). 키가 없으면 예외 없이 status='no_credentials'.
- 읽기 전용 PASS 는 멱등성(중복 POST 422, 조회, 취소)을 검증한 것이 아니다 — 결과에 verified_scope 로 명시한다.
"""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = PROJECT_ROOT / "data" / "verification"
FILE_PREFIX = "alpaca_"
NOTICE_STATE_FILE = ".last_notice.json"

KEY_ENV, SECRET_ENV = "ALPACA_PAPER_API_KEY", "ALPACA_PAPER_API_SECRET"
PASS_MAX_AGE_DAYS = 7
NOTICE_REPEAT_DAYS = 3  # 같은 실패 내용은 이 기간 안에는 다시 알리지 않는다(매일 밤 같은 알림 방지)

CHECK_LABELS = {
    "idempotency_read_only": "멱등성(읽기 전용)",
    "corporate_actions": "기업행동 API",
    "price_crosscheck": "가격 교차검증",
    "account_schema": "계좌 스키마",
    "market_meta_news": "자산·캘린더·뉴스",
}
VERIFIED_SCOPE = (
    "읽기 전용 범위만 검증했다: 연결·인증·계정 필드·미존재 ID 404 등. 중복 POST 422, 주문 후 조회, 취소 의미는 "
    "미검증(--write 는 사람이 명시적으로 실행해야 하며 이 자동 경로는 절대 실행하지 않는다)."
)


# --------------------------------------------------------------------------------------------
# 키 / 마스킹
# --------------------------------------------------------------------------------------------

def credentials_present() -> bool:
    """키가 둘 다 있는지만 알려준다 — 값은 반환하지 않는다."""
    return bool(os.getenv(KEY_ENV)) and bool(os.getenv(SECRET_ENV))


def _redact(text: str) -> str:
    """안전망: 키 값이 문자열에 섞여 들어갔으면 지운다."""
    for name in (KEY_ENV, SECRET_ENV):
        value = os.getenv(name)
        if value and len(value) >= 4:
            text = text.replace(value, "<redacted>")
    return text


def _scrub(obj: Any) -> Any:
    """JSON 직렬화 가능한 구조를 통째로 마스킹한다."""
    return json.loads(_redact(json.dumps(obj, ensure_ascii=False, default=str)))


# --------------------------------------------------------------------------------------------
# 개별 검증 (각각 {"verdict", "summary", "failing", "detail"} 반환)
# --------------------------------------------------------------------------------------------

_SCRIPT_CACHE: dict[str, Any] = {}


def _load_script(name: str):
    if name not in _SCRIPT_CACHE:
        path = PROJECT_ROOT / "scripts" / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"_verif_{name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SCRIPT_CACHE[name] = module
    return _SCRIPT_CACHE[name]


def _result(verdict: str, summary: str, failing: Optional[list[str]] = None, detail: Any = None) -> dict:
    return {"verdict": verdict, "summary": summary, "failing": failing or [], "detail": detail}


def check_idempotency_read_only() -> dict:
    mod = _load_script("verify_alpaca_paper_idempotency")
    key, secret = os.getenv(KEY_ENV, ""), os.getenv(SECRET_ENV, "")
    report = mod.verify(mod.PaperApi(key, secret), key, secret, write=False)  # write=False 고정 — 주문 없음
    bad = [s for s in report["steps"] if s["verdict"] not in ("PASS", "SKIPPED")]
    failing = [f"{s['id']}: {s.get('note') or s['verdict']} (응답 {s.get('actual_status')}, 기대 {s.get('expected')})" for s in bad]
    steps = [{"id": s["id"], "verdict": s["verdict"], "actual_status": s["actual_status"], "note": s.get("note", "")}
             for s in report["steps"]]
    return _result(report["overall"], f"{report['summary']}", failing,
                   {"steps": steps, "unmapped_statuses": report.get("unmapped_statuses"),
                    "mode": report.get("mode"), "idempotency_verified": bool(report.get("idempotency_verified"))})


def check_corporate_actions() -> dict:
    mod = _load_script("verify_alpaca_corporate_actions")
    client = mod.AlpacaCorporateActionsClient.from_env()
    results = [mod._check_case(client, dict(case), use_cache=False) for case in mod.CASES]
    verdicts = {r["verdict"] for r in results}
    overall = "UNEXPECTED" if "UNEXPECTED" in verdicts else "FAIL" if "FAIL" in verdicts else "PASS"
    failing = []
    for r in results:
        if r["verdict"] != "PASS":
            reason = "; ".join(r.get("problems") or r.get("notes") or [r["verdict"]])
            failing.append(f"{r['case']}: {reason}")
    return _result(overall, f"{len(results)}개 사례", failing, {"results": results})


def check_price_crosscheck() -> dict:
    mod = _load_script("verify_price_crosscheck")
    recent = mod.step_recent(list(mod.DEFAULT_SYMBOLS), 30, False)
    split = mod.step_aapl_split(False)
    failing: list[str] = []
    verdict = "PASS"
    if recent["summary"].get(mod.VERDICT_UNAVAILABLE, 0) > 0:
        verdict = "UNEXPECTED"
        failing.append("recent: 일부 심볼 조회 불가(unavailable) — 구독 등급/피드 한계일 수 있음")
    sv = split.get("verdict")
    if sv == "alpaca_unadjusted":
        verdict = "FAIL"
        failing.append("aapl_split: Alpaca 종가가 분할 미조정(raw) — 조정 가정(DEFAULT_ADJUSTMENT) 위반")
    elif sv != "alpaca_split_adjusted":
        if verdict == "PASS":
            verdict = "UNEXPECTED"
        failing.append(f"aapl_split: 판정 {sv} — {split.get('note', '')}")
    return _result(verdict, f"recent={recent['summary']}, aapl_split={sv}", failing,
                   {"recent": recent, "aapl_split": split})


def check_account_schema() -> dict:
    from core.account_sync import sync_paper_account

    res = sync_paper_account(persist=False)
    if res.get("skipped"):
        return _result("UNEXPECTED", "건너뜀", [f"account: {res.get('reason')}"])
    if not res.get("ok"):
        return _result("UNEXPECTED", "조회 실패", [f"account: {res.get('reason')}"], {"errors": res.get("errors")})
    if res.get("errors"):
        return _result("UNEXPECTED", "부분 오류", [f"account: {e}" for e in res["errors"][:5]], {"errors": res["errors"]})
    return _result("PASS", "계좌/포지션 스키마 파싱 성공")


def check_market_meta_news() -> dict:
    """자산 거래가능·휴장 캘린더·과거 뉴스 스키마(core.alpaca_market_meta, core.alpaca_news)."""
    from core import alpaca_market_meta as meta, alpaca_news

    failing = []
    rep = meta.check_tradability(["AAPL", "ZZZZNOPE"])
    if rep["AAPL"]["verdict"] != meta.TRADABLE:
        failing.append(f"assets: AAPL={rep['AAPL']['verdict']}")
    if rep["ZZZZNOPE"]["verdict"] != meta.NOT_FOUND:
        failing.append(f"assets: ZZZZNOPE={rep['ZZZZNOPE']['verdict']} (기대 not_found)")
    days = meta.fetch_trading_days("2025-11-24", "2025-11-30")
    if any(d["date"] == "2025-11-27" for d in days) or not any(d["date"] == "2025-11-28" and d["early_close"] for d in days):
        failing.append("calendar: 2025 추수감사절 휴장/다음날 조기폐장이 가정과 다름")
    news = alpaca_news.fetch_news(["AAPL"], "2020-03-01", "2020-03-03")
    if not news:
        failing.append("news: 2020-03 과거 기사 0건")
    if failing:
        return _result("UNEXPECTED", "가정과 다름", failing, {"calendar": days, "n_news": len(news)})
    return _result("PASS", f"자산·캘린더·뉴스 스키마 일치 (과거 기사 {len(news)}건)")


DEFAULT_CHECKS: dict[str, Callable[[], dict]] = {
    "idempotency_read_only": check_idempotency_read_only,
    "corporate_actions": check_corporate_actions,
    "price_crosscheck": check_price_crosscheck,
    "account_schema": check_account_schema,
    "market_meta_news": check_market_meta_news,
}


# --------------------------------------------------------------------------------------------
# 실행 / 저장 / 로드
# --------------------------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_alpaca_verification(out_dir: Optional[Path | str] = None, *, checks: Optional[dict[str, Callable[[], dict]]] = None,
                            now: Optional[datetime] = None) -> dict:
    """읽기 전용 검증 5개를 순서대로 실행하고 결과를 JSON 으로 저장해 dict 로 돌려준다(예외를 던지지 않는다).

    키가 없으면 status='no_credentials' (저장 안 함). checks 는 테스트용 주입점이다."""
    now = now or _now()
    if not credentials_present():
        return {"status": "no_credentials", "overall": None, "generated_at": now.isoformat(timespec="seconds"),
                "checks": {}, "write_phase_executed": False,
                "message": f"{KEY_ENV} / {SECRET_ENV} 환경변수가 없어 검증을 건너뜀 (값은 기록하지 않는다)"}
    results: dict[str, dict] = {}
    for name, fn in (checks or DEFAULT_CHECKS).items():
        try:
            res = fn()
            if res.get("verdict") not in ("PASS", "FAIL", "UNEXPECTED"):
                res = _result("UNEXPECTED", "알 수 없는 판정 값", [f"{name}: verdict={res.get('verdict')!r}"])
        except Exception as exc:  # noqa: BLE001 - 한 검증의 예외가 나머지를 막지 않게 한다
            res = _result("UNEXPECTED", "검증 실행 중 예외", [f"{name}: {type(exc).__name__}: {exc}"])
        results[name] = res
    verdicts = {r["verdict"] for r in results.values()}
    overall = "FAIL" if "FAIL" in verdicts else "UNEXPECTED" if "UNEXPECTED" in verdicts else "PASS"
    report = {
        "status": "completed", "overall": overall, "generated_at": now.isoformat(timespec="seconds"),
        "checks": results, "write_phase_executed": False, "verified_scope": VERIFIED_SCOPE,
    }
    report = _scrub(report)
    directory = Path(out_dir) if out_dir else VERIFICATION_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{FILE_PREFIX}{now.strftime('%Y%m%d_%H%M')}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["path"] = str(path)
    except OSError as exc:
        report["save_error"] = f"{type(exc).__name__}"
    return report


def _result_files(out_dir: Optional[Path | str]) -> list[Path]:
    directory = Path(out_dir) if out_dir else VERIFICATION_DIR
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"{FILE_PREFIX}*.json"), reverse=True)


def _read(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data["path"] = str(path)
    return data


def _age_days(generated_at: str, now: datetime) -> Optional[float]:
    try:
        ts = datetime.fromisoformat(generated_at)
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 86400


def load_latest_verification(out_dir: Optional[Path | str] = None) -> Optional[dict]:
    """가장 최근 결과 파일(깨진 파일은 건너뜀). 없으면 None."""
    for path in _result_files(out_dir):
        data = _read(path)
        if data is not None:
            return data
    return None


def find_recent_pass(out_dir: Optional[Path | str] = None, *, max_age_days: float = PASS_MAX_AGE_DAYS,
                     now: Optional[datetime] = None) -> Optional[dict]:
    """최근 max_age_days 안의 전체 PASS 결과(가장 최근 것). 없으면 None."""
    now = now or _now()
    for path in _result_files(out_dir):
        data = _read(path)
        if not data or data.get("overall") != "PASS":
            continue
        age = _age_days(data.get("generated_at", ""), now)
        if age is not None and age <= max_age_days:
            return data
    return None


def summarize_latest_verification(out_dir: Optional[Path | str] = None, now: Optional[datetime] = None) -> dict:
    """마지막 결과와 경과 일수, 전체 판정."""
    now = now or _now()
    latest = load_latest_verification(out_dir)
    if latest is None:
        return {"has_result": False, "generated_at": None, "age_days": None, "overall": None, "failing": [], "path": None}
    failing = [line for c in (latest.get("checks") or {}).values() for line in c.get("failing", [])]
    age = _age_days(latest.get("generated_at", ""), now)
    return {"has_result": True, "generated_at": latest.get("generated_at"),
            "age_days": None if age is None else round(age, 2), "overall": latest.get("overall"),
            "failing": failing, "path": latest.get("path")}


def verification_status_for_ui(out_dir: Optional[Path | str] = None, now: Optional[datetime] = None) -> dict:
    """화면용 상태 dict: {label, level('ok'|'warn'|'error'|'unknown'), last_run_at, age_days, overall, stale, failing}.

    ok = 7일 이내 PASS, warn = PASS 지만 7일 넘음 또는 UNEXPECTED, error = FAIL, unknown = 결과 없음.
    UI 는 이 함수만 호출하면 된다(파일 읽기만 하며 네트워크·주문 없음)."""
    s = summarize_latest_verification(out_dir, now)
    if not s["has_result"]:
        return {"label": "Alpaca paper 검증: 아직 실행 전(자동 실행 대기)", "level": "unknown", "last_run_at": None,
                "age_days": None, "overall": None, "stale": True, "failing": []}
    stale = s["age_days"] is None or s["age_days"] > PASS_MAX_AGE_DAYS
    overall = s["overall"]
    level = "error" if overall == "FAIL" else "ok" if overall == "PASS" and not stale else "warn"
    age_text = "?" if s["age_days"] is None else f"{s['age_days']:.1f}일 전"
    label = f"Alpaca paper 검증(읽기 전용): {overall} · {age_text}" + (" · 오래됨" if stale else "")
    return {"label": label, "level": level, "last_run_at": s["generated_at"], "age_days": s["age_days"],
            "overall": overall, "stale": stale, "failing": s["failing"][:5]}


# --------------------------------------------------------------------------------------------
# 텔레그램 요약 / 부트스트랩
# --------------------------------------------------------------------------------------------

def format_telegram_summary(result: dict) -> str:
    """결과 요약 1건. 실패한 검증마다 어떤 단계의 어떤 가정이 틀렸는지 한 줄씩. 키 값은 절대 넣지 않는다."""
    if result.get("status") == "no_credentials":
        text = f"[Alpaca paper 검증] 키가 없어 건너뜀 — VM /opt/quant/.env 에 {KEY_ENV}/{SECRET_ENV} 를 넣으면 자동 실행됩니다."
        return _redact(text)
    checks = result.get("checks") or {}
    n_pass = sum(1 for c in checks.values() if c.get("verdict") == "PASS")
    lines = [f"[Alpaca paper 검증] 전체 {result.get('overall')} ({n_pass}/{len(checks)} PASS)"]
    for name, c in checks.items():
        for line in c.get("failing", [])[:3]:
            lines.append(f"- {CHECK_LABELS.get(name, name)} [{c.get('verdict')}] {line}"[:220])
    lines.append("범위: 읽기 전용. 중복 POST 422·주문 후 조회·취소는 미검증(주문 검증은 사람이 --write 로).")
    return _redact("\n".join(lines))


def _fingerprint(result: dict) -> str:
    checks = result.get("checks") or {}
    return json.dumps([result.get("status"), result.get("overall"),
                       sorted((n, tuple(c.get("failing", []))) for n, c in checks.items())], ensure_ascii=False)


def _should_notify(directory: Path, result: dict, now: datetime) -> bool:
    """PASS 는 항상 알린다. 같은 실패/키 없음은 NOTICE_REPEAT_DAYS 안에 반복 알리지 않는다."""
    if result.get("overall") == "PASS":
        return True
    try:
        state = json.loads((directory / NOTICE_STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    age = _age_days(state.get("at", ""), now)
    return not (state.get("fingerprint") == _fingerprint(result) and age is not None and age < NOTICE_REPEAT_DAYS)


def _remember_notice(directory: Path, result: dict, now: datetime) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / NOTICE_STATE_FILE).write_text(
            json.dumps({"at": now.isoformat(timespec="seconds"), "fingerprint": _fingerprint(result)}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def run_bootstrap_if_needed(out_dir: Optional[Path | str] = None, *, now: Optional[datetime] = None,
                            runner: Optional[Callable[..., dict]] = None,
                            notify: Optional[Callable[[str], bool]] = None) -> dict:
    """최근 7일 안에 전체 PASS 가 없을 때만 검증을 돌리고 텔레그램 요약 1건을 보낸다(자가 치유).

    이미 PASS 가 있으면 조용히 건너뛴다(action='skipped_recent_pass'). 반환: {"action", "overall", "notified", "path"}."""
    now = now or _now()
    directory = Path(out_dir) if out_dir else VERIFICATION_DIR
    if find_recent_pass(directory, now=now) is not None:
        return {"action": "skipped_recent_pass", "overall": "PASS", "notified": False, "path": None}
    result = (runner or run_alpaca_verification)(directory, now=now)
    if notify is None:
        from core import telegram_notify

        notify = telegram_notify.send_message
    notified = False
    if _should_notify(directory, result, now):
        notified = bool(notify(format_telegram_summary(result)))
        if notified:
            _remember_notice(directory, result, now)
    return {"action": "ran", "status": result.get("status"), "overall": result.get("overall"), "notified": notified,
            "path": result.get("path")}
