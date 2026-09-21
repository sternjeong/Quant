#!/usr/bin/env python3
"""스케줄러/앱과 독립적으로 매일 아침 한 번 도는 워치독 — 밤사이 작업과 백업이 정말 돌았는지 확인하고 문제만 텔레그램으로 알린다.

왜 따로 있나: 오늘의 브리핑(core/daily_briefing.py)도 스케줄러 안에서 도는 잡이라, 스케줄러가 죽으면 브리핑도 같이 안 온다 —
"브리핑이 안 왔다"를 스스로 알릴 수 없다. 이 스크립트는 systemd 타이머가 앱과 무관하게 실행하고(stdlib만 사용, venv 불필요),
sqlite/파일만 읽는다. 문제가 없으면 조용히 끝난다(알림 없음). 사용자가 폰으로만 운영하므로 "조용한 실패"를 막는 마지막 그물이다.

확인하는 것:
  1. 스케줄러 잡 실행 이력(scheduler_job_runs)에 최근 26시간 안의 기록이 있는가 — 기록이 있던 적이 있는데 26시간째 없으면
     스케줄러가 멈춘 것. (이력 추적이 시작되기 전이면 판정하지 않는다)
  2. 최근 26시간에 error/missed 로 기록된 잡이 있는가.
  3. 최신 daily_briefing_*.html 이 26시간 안에 만들어졌는가.
  4. 백업 상태(core.backup_status와 같은 기준): 36시간 넘게 성공 없음 / 실패 / 비공개 원격 push 3일 넘게 실패 /
     백업 검증 실패. (원격 미설정은 알리지 않는다 — 브리핑에 표시됨)
  5. 재부팅 필요 표시(/var/run/reboot-required, 보통 커널 보안 업데이트)가 14일 넘게 방치됐는가 — 자동으로 재부팅하지는
     않는다(부팅 실패 시 사람이 콘솔에서 복구해야 하므로). 사람이 잊지 않게 알리기만 한다.

주 1회(한국시간 일요일)는 문제가 없어도 "생존 신호" 요약을 한 통 보낸다 — 워치독/텔레그램 자체가 죽으면 "이상 없음"과
"알림이 안 옴"을 구분할 수 없기 때문이다. 일요일에 요약이 안 오면 그것이 이상 신호다.

사용법: python3 deploy/watchdog.py [--dry-run]     (문제가 있으면 종료 코드 1)
환경변수: QUANT_APP_DIR(기본 /opt/quant), QUANT_BACKUP_STATUS_PATH
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

DEFAULT_APP_DIR = "/opt/quant"
WINDOW_HOURS = 26  # 하루 한 번 도는 잡 + 여유
REBOOT_NAG_DAYS = 14
REBOOT_REQUIRED_PATH = Path(os.environ.get("QUANT_REBOOT_REQUIRED_PATH", "/var/run/reboot-required"))
KST = timezone(timedelta(hours=9))

APP_DIR = Path(os.environ.get("QUANT_APP_DIR", DEFAULT_APP_DIR))
# core/backup_status.py는 stdlib만 쓰므로 venv 없이 가져올 수 있다(임계값을 한 곳에서만 관리하려고 공유).
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def check_job_history(db_path: Path, now: datetime) -> list[str]:
    if not db_path.is_file():
        return [f"DB 파일이 없음: {db_path}"]
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        return [f"DB를 열 수 없음: {exc}"]
    try:
        try:
            total = conn.execute("SELECT COUNT(*) FROM scheduler_job_runs").fetchone()[0]
        except sqlite3.Error:
            return []  # 이력 테이블이 아직 없음(스케줄러가 새 코드로 한 번도 안 뜸) — 판정 불가
        if total == 0:
            return []  # 추적 시작 전 — 아직 판정할 기록이 없다
        cutoff = (now - timedelta(hours=WINDOW_HOURS)).replace(tzinfo=None).isoformat(sep=" ")
        recent = conn.execute("SELECT COUNT(*) FROM scheduler_job_runs WHERE recorded_at >= ?", (cutoff,)).fetchone()[0]
        problems = []
        if recent == 0:
            problems.append(f"스케줄러가 최근 {WINDOW_HOURS}시간 동안 어떤 작업도 기록하지 않음 — 스케줄러가 멈췄을 수 있음")
            return problems
        rows = conn.execute(
            "SELECT job_id, status, COUNT(*) FROM scheduler_job_runs WHERE recorded_at >= ? AND status IN ('error','failed','missed') "
            "GROUP BY job_id, status ORDER BY job_id", (cutoff,)
        ).fetchall()
        for job_id, status, count in rows:
            problems.append(f"작업 {job_id}: 최근 {WINDOW_HOURS}시간 중 {'실행 놓침' if status == 'missed' else '오류'} {count}회")
        return problems
    finally:
        conn.close()


def check_briefing(report_dir: Path, now_epoch: float) -> list[str]:
    files = sorted(report_dir.glob("daily_briefing_*.html"), key=lambda p: p.stat().st_mtime) if report_dir.is_dir() else []
    if not files:
        return []  # 브리핑이 한 번도 안 만들어진 환경(개발/신규) — 판정하지 않는다
    age_hours = (now_epoch - files[-1].stat().st_mtime) / 3600
    if age_hours > WINDOW_HOURS:
        return [f"오늘의 브리핑이 {age_hours:.0f}시간째 만들어지지 않음(마지막: {files[-1].name})"]
    return []


def check_backup(now_epoch: float) -> list[str]:
    from core.backup_status import describe_backup, load_backup_status

    status = load_backup_status()
    if status is None:
        return []  # 백업 미설치 환경
    result = describe_backup(status, now_epoch)
    return [f"백업: {line}" for line in result["lines"]] if result["level"] == "bad" else []


def check_reboot_required(now_epoch: float) -> list[str]:
    try:
        marked_at = REBOOT_REQUIRED_PATH.stat().st_mtime
    except OSError:
        return []  # 재부팅 필요 표시 없음
    age_days = (now_epoch - marked_at) / 86400
    if age_days < REBOOT_NAG_DAYS:
        return []
    return [f"재부팅이 필요한 상태가 {age_days:.0f}일째 방치됨(보통 커널 보안 업데이트) — 콘솔에 접근할 수 있을 때 재부팅하세요"]


def weekly_summary(app_dir: Path, now: datetime) -> str:
    """주 1회 생존 신호 — 문제 없이 돌고 있다는 사실과 핵심 수치 몇 개."""
    lines = ["[워치독] 주간 생존 신호 — 이상 없음"]
    db = app_dir / "data" / "quant.db"
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        try:
            cutoff = (now - timedelta(days=7)).replace(tzinfo=None).isoformat(sep=" ")
            total, oks = conn.execute(
                "SELECT COUNT(*), SUM(status='ok') FROM scheduler_job_runs WHERE recorded_at >= ?", (cutoff,)).fetchone()
            lines.append(f"- 최근 7일 스케줄러 작업 기록 {total or 0}건 (정상 {oks or 0}건)")
        finally:
            conn.close()
    except sqlite3.Error:
        lines.append("- 스케줄러 작업 기록: 조회 불가")
    try:
        from core.backup_status import describe_backup, load_backup_status

        result = describe_backup(load_backup_status(), now.timestamp())
        lines.append(f"- 백업: {result['lines'][0]}" + (" / 비공개 원격 미설정" if result["level"] == "warn" else ""))
    except Exception:  # noqa: BLE001
        pass
    lines.append("(이 메시지가 일요일에 오지 않으면 워치독/텔레그램 자체를 확인하세요)")
    return "\n".join(lines)


def default_alert(message: str) -> None:
    script = Path(__file__).resolve().parent / "send_telegram_alert.sh"
    if not script.is_file():
        print("send_telegram_alert.sh 가 없어 알림을 보내지 못함", file=sys.stderr)
        return
    result = subprocess.run(["bash", str(script), message], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"텔레그램 알림 전송 실패: {result.stderr.strip()[:200]}", file=sys.stderr)


def run_watchdog(
    app_dir: Path,
    *,
    dry_run: bool = False,
    alert: Callable[[str], None] = default_alert,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> list[str]:
    current = now()
    problems: list[str] = []
    problems += check_job_history(app_dir / "data" / "quant.db", current)
    problems += check_briefing(app_dir / "data" / "cache" / "champion_reports", current.timestamp())
    problems += check_backup(current.timestamp())
    problems += check_reboot_required(current.timestamp())
    if not dry_run:
        if problems:
            alert("[워치독] 밤사이 확인이 필요합니다\n" + "\n".join(f"- {p}" for p in problems)
                  + "\n\n(원인 확인: 허브 → 스케줄러, 또는 VM에서 journalctl -u quant-scheduler)")
        elif current.astimezone(KST).weekday() == 6:  # 일요일 — 문제가 없을 때만 생존 신호(문제가 있으면 위 알림이 이미 감)
            alert(weekly_summary(app_dir, current))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="알림을 보내지 않고 결과만 출력")
    args = parser.parse_args(argv)
    problems = run_watchdog(APP_DIR, dry_run=args.dry_run)
    if problems:
        print("문제 발견:\n" + "\n".join(f"- {p}" for p in problems))
        return 1
    print("이상 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
