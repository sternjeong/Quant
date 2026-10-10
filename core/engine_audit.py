"""주간 엔진 점검 (2026-10-05) — 모든 주식 엔진·연구 에이전트가 제대로 굴러가는지 한 번에 확인하고 텔레그램으로 보고한다.

사용자 요청: "주에 한 번씩 모든 주식 엔진이 잘 굴러가는지 검사하는 로직". 2026-10-05 에 사람이 손으로 한 점검(서비스·자동 잡·
연구 실행기·새틀라이트 R&D·야간 에이전트·아침 재추천·데이터 신선도·배포 동기화)을 그대로 코드로 옮겼다.
그날 손 점검에서 찾은 '배포 테스트가 실서비스 상태를 오염'시킨 것 같은 이상(설계 횟수가 상한을 넘은 에이전트 기록)도 잡는다.

읽기 전용이다 — 어떤 상태도 고치지 않고, 주문 경로와 연결되어 있지 않다. 항목마다 ok / warn / fail 과 한 줄 설명을 돌려주며,
한 항목의 점검이 예외로 실패해도 그 항목만 fail 로 남기고 나머지는 계속한다.
결과: data/engine_audit/latest.json (+ 날짜별 사본), 텔레그램 1건.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "engine_audit"
KST = ZoneInfo("Asia/Seoul")
SERVICES = ("quant-scheduler", "quant-hub", "quant-streamlit", "codex-telegram")
OK, WARN, FAIL = "ok", "warn", "fail"
ICON = {OK: "✅", WARN: "⚠️", FAIL: "❌"}

Check = dict[str, Any]


def _c(name: str, status: str, detail: str) -> Check:
    return {"name": name, "status": status, "detail": detail}


def _age_days(iso: Optional[str], now: datetime) -> Optional[float]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 86400


# ---------------------------------------------------------------- 점검 항목
def check_services(run: Callable = subprocess.run) -> Check:
    if not shutil.which("systemctl"):
        return _c("서비스", WARN, "systemctl 없음 — 확인 불가")
    bad = []
    for s in SERVICES:
        try:
            out = run(["systemctl", "is-active", s], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception as exc:  # noqa: BLE001
            out = type(exc).__name__
        if out != "active":
            bad.append(f"{s}={out or '?'}")
    return _c("서비스", FAIL if bad else OK, ("멈춤: " + ", ".join(bad)) if bad else f"{len(SERVICES)}개 모두 실행 중")


def check_scheduled_jobs(now: datetime) -> Check:
    from core.job_health import compute_job_health, describe_problem

    h = compute_job_health(now.astimezone(timezone.utc))
    probs = h.get("problems") or []
    if not probs:
        n = len(h.get("jobs") or [])
        return _c("자동 잡", OK, f"등록 잡 {n}개 모두 제때 실행(또는 꺼짐·대기)")
    lines = "; ".join(describe_problem(p) for p in probs[:5])
    failed = any(p.get("state") in ("error", "missed") for p in probs)
    return _c("자동 잡", FAIL if failed else WARN, f"{len(probs)}건 — {lines}")


def check_backup(now: datetime) -> Check:
    from core.backup_status import describe_backup, load_backup_status

    d = describe_backup(load_backup_status(), now.timestamp())
    level = {"ok": OK, "warn": WARN}.get(d.get("level"), FAIL)
    return _c("백업", level, " · ".join(d.get("lines") or [])[:300])


def check_deploy_sync(run: Callable = subprocess.run, root: Path = PROJECT_ROOT) -> Check:
    """작업트리 HEAD 가 마지막으로 받아온 origin/main 과 같은가(네트워크 조회 없이 로컬 참조만)."""
    try:
        head = run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
        origin = run(["git", "-C", str(root), "rev-parse", "origin/main"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return _c("배포 동기화", WARN, f"git 확인 불가({type(exc).__name__})")
    if not head or not origin:
        return _c("배포 동기화", WARN, "git 참조를 읽지 못함")
    if head == origin:
        return _c("배포 동기화", OK, f"main 과 같음({head[:7]})")
    return _c("배포 동기화", WARN, f"실행 중 코드 {head[:7]} ≠ 받아온 main {origin[:7]} — 배포 대기 또는 테스트 관문 실패 확인")


def check_research_runner(now: datetime, state_path: Optional[Path] = None) -> Check:
    p = state_path or PROJECT_ROOT / "data" / "research_jobs" / "state.json"
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _c("연구 실행기", WARN, "상태 파일 없음 — 아직 한 번도 안 돌았거나 경로 문제")
    tick_age = _age_days((st.get("runner") or {}).get("last_tick_at"), now)
    jobs = st.get("jobs") or {}
    bad = [j for j, e in jobs.items() if e.get("status") in ("failed", "invalid")]
    stuck = [j for j, e in jobs.items() if e.get("status") == "in_progress" and (_age_days(e.get("last_started_at"), now) or 0) > 7]
    done = sum(1 for e in jobs.values() if e.get("status") == "done")
    if tick_age is None or tick_age > 1.5:
        return _c("연구 실행기", FAIL, f"마지막 회차 {('없음' if tick_age is None else f'{tick_age:.1f}일 전')} — 하루 두 번 이상 깨어나야 정상")
    if bad:
        return _c("연구 실행기", FAIL, f"실패·정의 오류 작업: {', '.join(bad)}")
    if stuck:
        return _c("연구 실행기", WARN, f"7일 넘게 진행 중: {', '.join(stuck)}")
    return _c("연구 실행기", OK, f"마지막 회차 {tick_age * 24:.0f}시간 전 · 완료 {done} · 대기·진행 {len(jobs) - done - len(bad)}")


def check_satellite_lab(now: datetime, state_dir: Optional[Path] = None, variants_dir: Optional[Path] = None) -> Check:
    from core import satellite_lab as sl

    reg = sl.load_registry(state_dir)
    if not reg.get("variants"):
        return _c("새틀라이트 R&D", WARN, "등록부가 비어 있음 — 아직 첫 계산 전")
    issues, notes = [], []
    if reg.get("incumbent") is None:
        issues.append("현 규칙 기준선 없음")
    errors = [v["id"] for v in reg["variants"].values() if v.get("status") == sl.STATUS_ERROR]
    if errors:
        issues.append(f"계산 오류 {', '.join(errors)}")
    # 준비됐는데 2일 넘게 동결·심판되지 않은 에이전트 아이디어 / 상한을 넘은 설계 횟수(상태 오염 탐지)
    from core.agent_batch import SAT_MAX_ROUNDS

    vdir = Path(variants_dir or sl.VARIANTS_DIR)
    waiting, polluted, abandoned = [], [], []
    for d in sorted(p for p in vdir.glob("S-*") if p.is_dir()):
        st = sl.agent_state(d.name, state_dir)
        if st.get("rounds", 0) > SAT_MAX_ROUNDS:
            polluted.append(f"{d.name}(설계 {st['rounds']}회)")
        if st.get("abandoned"):
            abandoned.append(d.name)
        if d.name not in reg["variants"] and sl.agent_ready(d, state_dir) and (_age_days(st.get("ready_at"), now) or 0) > 2:
            waiting.append(d.name)
    if polluted:
        issues.append(f"설계 횟수가 상한({SAT_MAX_ROUNDS})을 넘은 기록 {', '.join(polluted)} — 테스트·수동 조작 오염 의심")
    if waiting:
        issues.append(f"준비됐지만 2일 넘게 판정 안 된 아이디어 {', '.join(waiting)}")
    week_ago = (now - timedelta(days=7)).isoformat()
    judged_week = [v["id"] for v in reg["variants"].values() if ((v.get("result") or {}).get("judged_at") or "") >= week_ago]
    passed = [v["id"] for v in reg["variants"].values() if v.get("status") == sl.STATUS_PASS]
    notes.append(f"이번 주 판정 {len(judged_week)} · 누적 시도 {reg.get('cumulative_trials', 0)} · 통과(검토 대기) {len(passed)}")
    if abandoned:
        notes.append(f"폐기된 에이전트 아이디어 {len(abandoned)}")
    return _c("새틀라이트 R&D", WARN if issues else OK, "; ".join(issues + notes))


def check_agent_batch(now: datetime, usage_path: Optional[Path] = None) -> Check:
    from core import agent_budget as budget

    rows = budget.read_usage(usage_path)
    week = [r for r in rows if (_age_days(r.get("at"), now) or 99) <= 7]
    if not week:
        return _c("야간 AI 에이전트", FAIL, "지난 7일 실행 0건 — 03:00 배치가 안 돌고 있음")
    nights = {str(r["at"])[:10] for r in week}
    fails = [r for r in week if not r.get("ok")]
    limited = sum(1 for r in week if r.get("limited"))
    timeouts = sum(1 for r in week if r.get("timed_out"))
    roles: dict[str, int] = {}
    for r in week:
        roles[r["role"]] = roles.get(r["role"], 0) + 1
    cost = sum(float(r.get("cost_usd") or 0) for r in week)
    level = OK
    notes = [f"{len(nights)}일 밤 실행 {len(week)}건 {roles}", f"사용량 환산 ${cost:.1f}/{budget.WEEKLY_CAP_USD:.0f}"]
    if len(nights) < 5:
        level = WARN
        notes.insert(0, f"7일 중 {len(nights)}일만 실행")
    if week and len(fails) / len(week) > 0.3:
        level = WARN
        notes.insert(0, f"실패 {len(fails)}/{len(week)}건(" + ", ".join(sorted({r['role'] for r in fails})) + ")")
    if limited:
        level = WARN
        notes.insert(0, f"사용량 한도 걸림 {limited}회")
    if timeouts:
        notes.append(f"시간 초과 {timeouts}회")
    if not roles.get("sat_designer"):
        level = WARN
        notes.insert(0, "새틀라이트 아이디어 설계(sat_designer) 0회")
    return _c("야간 AI 에이전트", level, " · ".join(notes))


def check_daily_recommendation(now: datetime, cache_dir: Optional[Path] = None) -> Check:
    from core import champion_recommendation as cr

    rows = cr.list_cached(cache_dir)
    dates = {str((r.get("params") or {}).get("as_of")) for r in rows}
    today = now.astimezone(timezone.utc).date()  # 잡은 서버 UTC 날짜로 as_of 를 정한다(09:01 KST = 00:01 UTC)
    expected = [(today - timedelta(days=i)).isoformat() for i in range(7)]
    if now.astimezone(KST).hour < 10:
        expected = expected[1:] + [(today - timedelta(days=7)).isoformat()]  # 오늘 09:01 실행 전이면 오늘은 빼고 7일
    if not dates:
        return _c("아침 자동 재추천", FAIL, "현재 전략 버전의 재추천 결과가 하나도 없음")
    first = min(dates)  # 전략 버전이 바뀌면 옛 결과는 목록에서 빠지므로, 새 버전의 첫 결과 이후만 센다
    expected = [d for d in expected if d >= first]
    missing = [d for d in expected if d not in dates]
    if len(missing) >= 3:
        return _c("아침 자동 재추천", FAIL, f"지난 7일 중 {len(missing)}일 결과 없음: {', '.join(sorted(missing))}")
    if missing:
        return _c("아침 자동 재추천", WARN, f"빠진 날 {', '.join(sorted(missing))}")
    return _c("아침 자동 재추천", OK, "지난 7일 매일 계산됨")


def check_dawn_precompute(now: datetime, cache_dir: Optional[Path] = None) -> Check:
    """새벽 미리 계산(06:40 KST, core/dawn_precompute.py)이 지난 7일 매일 돌았고 실패한 단계가 없는지 — 실행 기록만 읽는다."""
    from core import dawn_precompute as dp

    hist = dp.load_status(cache_dir).get("history") or []
    if not hist:
        return _c("새벽 미리 계산", WARN, f"실행 기록 없음 — 매일 {dp.schedule_label()} KST 잡이 아직 안 돌았거나 꺼짐")
    k = now.astimezone(KST)
    expected = [(k.date() - timedelta(days=i)).isoformat() for i in range(7)]
    if (k.hour, k.minute) < (7, 30):  # 오늘 회차가 끝나기 전이면 오늘은 빼고 7일
        expected = expected[1:] + [(k.date() - timedelta(days=7)).isoformat()]
    first = min(str(h.get("as_of")) for h in hist)  # 잡이 생긴 뒤부터만 센다
    expected = [d for d in expected if d >= first]
    ran = {str(h.get("as_of")) for h in hist if h.get("status") in (dp.STATUS_OK, dp.STATUS_PARTIAL)}
    missing = sorted(d for d in expected if d not in ran)
    week = [h for h in hist if str(h.get("as_of")) in set(expected)]
    failed = sorted({f for h in week for f in (h.get("failed") or [])})
    skipped = sum(1 for h in week if h.get("status") == dp.STATUS_SKIPPED)
    if len(missing) >= 3:
        return _c("새벽 미리 계산", FAIL, f"지난 7일 중 {len(missing)}일 결과 없음: {', '.join(missing)}")
    issues = []
    if missing:
        issues.append(f"빠진 날 {', '.join(missing)}" + (f"(VM 여유 없어 건너뜀 {skipped}회)" if skipped else ""))
    if failed:
        issues.append(f"실패한 단계 {', '.join(failed)}")
    last = hist[-1]
    note = f"최근 {last.get('as_of')} {float(last.get('seconds') or 0) / 60:.0f}분"
    return _c("새벽 미리 계산", WARN if issues else OK, "; ".join(issues + [note]) if issues else f"지난 7일 매일 계산됨 · {note}")


def check_signal_and_prices(now: datetime) -> Check:
    from core import champion_strategy as cs
    from core import market_data as md

    issues = []
    holdings = cs.get_current_holdings()
    sig_age = None
    if holdings and holdings.get("as_of"):
        sig_age = (now.date() - date.fromisoformat(str(holdings["as_of"]))).days
        if sig_age > 4:
            issues.append(f"야간 신호 {sig_age}일 전({holdings['as_of']})")
    else:
        issues.append("야간 신호 상태 없음")
    stale = []
    for t in ("SPY", "XLK", "BIL"):
        try:
            df = md._load_store(md._store_path(t, "1d"))
            last = df.index.max().date() if len(df) else None
        except Exception:  # noqa: BLE001
            last = None
        if last is None or (now.date() - last).days > 5:
            stale.append(f"{t}({last or '없음'})")
    if stale:
        issues.append("가격 캐시 오래됨 " + ", ".join(stale))
    return _c("신호·가격 데이터", WARN if issues else OK,
              "; ".join(issues) if issues else f"야간 신호 {sig_age}일 전 · SPY·XLK·BIL 가격 최신")


def check_geo_shadow(now: datetime) -> Check:
    from core import geo_shadow as gs

    k = now.astimezone(KST).date()
    month = gs.target_month(k)
    rows = gs.load_ledger()
    if month and k.day >= gs.DUE_FROM_DAY + 2 and not gs.has_month(month):
        return _c("AI 국제정세 의견", WARN, f"{month} 의견이 아직 없음(25일 이후 받아야 함)")
    latest = max((r["month"] for r in rows), default=None)
    return _c("AI 국제정세 의견", OK, f"기록 {len(rows)}개월 · 최근 {latest or '없음'} · 판정은 24개월 뒤")


def check_crypto_shadow(now: datetime) -> Check:
    from core import crypto_shadow as cx

    rows = cx.load_ledger()
    if now.date() >= cx.FORWARD_START and not rows:
        return _c("코인 추세 기록", WARN, "기록이 하나도 없음 — 00:37 기록 잡 확인")
    last = max((r["date"] for r in rows), default=None)
    if last and (now.date() - date.fromisoformat(last)).days > 4:
        return _c("코인 추세 기록", WARN, f"마지막 기록 {last} — 4일 넘게 멈춤")
    try:
        ev = cx.evaluate_live()
        cum = ev.get("cumulative_active")
        prog = f" · 현 챔피언 대비 누적 {cum * 100:+.2f}%p" if cum is not None else ""
        return _c("코인 추세 기록", OK, f"{len(rows)}일 기록 · {ev['verdict']}{prog}")
    except Exception as exc:  # noqa: BLE001 - 경과 계산 실패는 기록 자체와 구분
        return _c("코인 추세 기록", OK, f"{len(rows)}일 기록(경과 계산 실패: {type(exc).__name__})")


def check_forward_tournament(now: datetime) -> Check:
    from core import forward_tournament as ft

    rows = ft.load_ledger()
    if now.date() >= ft.START and not rows:
        return _c("앞으로 토너먼트", WARN, "기록이 하나도 없음 — 00:39 기록 잡 확인")
    last = max((r["date"] for r in rows), default=None)
    if last and (now.date() - date.fromisoformat(last)).days > 4:
        return _c("앞으로 토너먼트", WARN, f"마지막 기록 {last} — 4일 넘게 멈춤")
    try:
        ev = ft.evaluate_live()
        cands = ev.get("candidates") or {}
        best = max((c for k, c in cands.items() if k != "T0" and c.get("days")),
                   key=lambda c: c.get("excess_vs_T0", 0), default=None)
        lead = f" · T0 대비 선두 {best['label']} {best['excess_vs_T0'] * 100:+.2f}%p" if best else ""
        return _c("앞으로 토너먼트", OK, f"{len(rows)}일 기록 · {ev.get('days', 0)}/{ft.MIN_DAYS}거래일{lead}")
    except Exception as exc:  # noqa: BLE001 - 경과 계산 실패는 기록 자체와 구분
        return _c("앞으로 토너먼트", OK, f"{len(rows)}일 기록(경과 계산 실패: {type(exc).__name__})")


def check_forward_tournament_v2(now: datetime) -> Check:
    """v2 는 매일 기록 뒤 계산해 둔 status.json 만 읽는다(네트워크 없음)."""
    from core import forward_tournament_v2 as ft2

    name = "앞으로 토너먼트 v2"
    rows = ft2.load_ledger()
    # 첫 기록일은 START 이후 첫 거래일 다음 밤 — 며칠 여유를 둔다
    if (now.date() - ft2.START).days > 4 and not rows:
        return _c(name, WARN, "기록이 하나도 없음 — 00:39 기록 잡(v1 다음) 확인")
    if not rows:
        return _c(name, OK, f"기록 대기({ft2.START} 이후 첫 거래일부터)")
    last = rows[-1].get("date")
    if last and (now.date() - date.fromisoformat(last)).days > 4:
        return _c(name, WARN, f"마지막 기록 {last} — 4일 넘게 멈춤")
    errs = rows[-1].get("errors") or {}
    st = ft2.load_status()
    rank = " > ".join(st.get("rank_core") or [])
    msg = f"{len(rows)}일 기록 · {st.get('days', 0)}/{ft2.MIN_DAYS}거래일" + (f" · 중간 순위 {rank}" if rank else "")
    if errs:
        return _c(name, WARN, msg + f" · 최근 기록 오류 {', '.join(errs)}")
    return _c(name, OK, msg)


def check_disk(root: str = "/") -> Check:
    u = shutil.disk_usage(root)
    free_gb = u.free / 1024 ** 3
    pct = u.used / u.total * 100
    level = FAIL if free_gb < 2 else WARN if free_gb < 5 else OK
    return _c("디스크", level, f"여유 {free_gb:.1f}GB(사용 {pct:.0f}%)")


CHECKS: tuple[tuple[str, Callable[[datetime], Check]], ...] = (
    ("서비스", lambda now: check_services()),
    ("자동 잡", check_scheduled_jobs),
    ("백업", check_backup),
    ("배포 동기화", lambda now: check_deploy_sync()),
    ("연구 실행기", check_research_runner),
    ("새틀라이트 R&D", check_satellite_lab),
    ("야간 AI 에이전트", check_agent_batch),
    ("아침 자동 재추천", check_daily_recommendation),
    ("새벽 미리 계산", check_dawn_precompute),
    ("신호·가격 데이터", check_signal_and_prices),
    ("AI 국제정세 의견", check_geo_shadow),
    ("코인 추세 기록", check_crypto_shadow),
    ("앞으로 토너먼트", check_forward_tournament),
    ("앞으로 토너먼트 v2", check_forward_tournament_v2),
    ("디스크", lambda now: check_disk()),
)


# ---------------------------------------------------------------- 실행·보고
def run_audit(now: Optional[datetime] = None, checks=CHECKS) -> dict:
    now = now or datetime.now(timezone.utc)
    results = []
    for name, fn in checks:
        try:
            results.append(fn(now))
        except Exception as exc:  # noqa: BLE001 - 점검 하나가 깨져도 나머지는 계속
            results.append(_c(name, FAIL, f"점검 자체가 실패: {type(exc).__name__}: {str(exc)[:150]}"))
    counts = {s: sum(1 for r in results if r["status"] == s) for s in (OK, WARN, FAIL)}
    overall = FAIL if counts[FAIL] else WARN if counts[WARN] else OK
    return {"at": now.isoformat(timespec="seconds"), "overall": overall, "counts": counts, "checks": results}


def format_message(report: dict) -> str:
    c = report["counts"]
    head = {OK: "모두 정상", WARN: "확인할 것 있음", FAIL: "문제 있음"}[report["overall"]]
    lines = [f"{ICON[report['overall']]} [주간 엔진 점검] {head} — 정상 {c[OK]} · 주의 {c[WARN]} · 문제 {c[FAIL]}"]
    for r in sorted(report["checks"], key=lambda r: {FAIL: 0, WARN: 1, OK: 2}[r["status"]]):
        lines.append(f"{ICON[r['status']]} {r['name']}: {r['detail']}")
    lines.append("읽기 전용 점검입니다. 자세한 기록: data/engine_audit/latest.json")
    return "\n".join(lines)[:3500]


def save(report: dict, out_dir: Optional[Path] = None) -> Path:
    d = Path(out_dir or OUT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    (d / f"{report['at'][:10]}.json").write_text(text, encoding="utf-8")
    tmp = d / "latest.json.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, d / "latest.json")
    return d / "latest.json"


def run_and_notify(notify: Optional[Callable[[str], Any]] = None, now: Optional[datetime] = None) -> dict:
    report = run_audit(now)
    save(report)
    if notify:
        notify(format_message(report))
    return report
