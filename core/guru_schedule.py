"""거장 포트폴리오 자동 추적 배치 (모듈 D 스케줄링 계층).

배경(2026-09-24): core/guru_tracker.py 의 sync_guru_holdings() 는 Streamlit 페이지의
"🔄 동기화" 버튼에서 거장 1명씩 수동으로만 호출됐다. 사용자가 버튼을 눌러야만 최신화되는
구조라, 앱을 안 열면 데이터가 무한정 낡는다. 이 모듈은 그 함수를 "전체 거장 배치"로 감싸
스케줄러(scheduler/run_scheduler.py 의 guru_holdings_sync 잡)가 매일 돌리게 한다.

주기 설계 (소스마다 갱신 주기가 근본적으로 다르다):

    * 13F 거장(버핏/버리/애크먼/드러켄밀러/테퍼/클라만/커스텀 추가분)
      13F-HR 은 **분기 공시**다 — 분기말 후 45일 이내에 한 번 제출되고, 그 사이에는 어떤
      새 정보도 나오지 않는다(2월/5월/8월/11월 중순에 몰린다). 따라서 매일 infoTable.xml 을
      내려받아 다시 파싱하는 건 SEC 대역폭과 yfinance 티커 역추적 호출을 통째로 낭비하는
      짓이다. 여기서는 두 단계로 거른다:
        1) 마지막 확인 이후 THIRTEEN_F_CHECK_INTERVAL_DAYS 일이 지나지 않았으면 네트워크
           요청 자체를 안 한다("interval" 스킵).
        2) 지났으면 data.sec.gov submissions JSON 한 번만 읽어 최신 13F accession 을 저장된
           값과 비교한다. 같으면 새 공시가 없다는 뜻이므로 파싱하지 않는다("no_new_filing").
      13F 는 이미 최대 45일 지연된 데이터라 탐지가 며칠 늦는 건 실질적 손실이 아니다.

    * 캐시 우드(ARK, source="ark_daily")
      ARK 운용사는 보유내역 CSV 를 **매 거래일** 새로 공개한다. 여기에 위의 간격 게이트를
      걸면 추적 정밀도(이 소스를 13F 대신 쓰는 유일한 이유)를 잃는다. 그래서 ARK 는
      매 실행마다 무조건 갱신한다. CSV 한 번 받는 비용이라 SEC 부하와도 무관하다.

SEC rate limit: data.sec.gov 는 초당 10회를 넘기면 차단한다. 이 배치는 안전하게
초당 5회 이하(거장 사이 SEC_REQUEST_INTERVAL 초 대기)로만 호출하며, User-Agent 는
core.guru_tracker._sec_headers() 의 기존 관례(SEC_EDGAR_USER_AGENT 환경변수)를 그대로
재사용한다 — 그 값은 로그/알림/상태파일 어디에도 기록하지 않는다.

멱등성: 실제 저장은 guru_tracker.sync_guru_holdings() 가 하고, 그 함수는 해당 거장의
기존 GuruHolding 행을 전부 delete 한 뒤 새로 채워 넣는 "최신 스냅샷" 방식이다. 즉 같은
공시를 몇 번 다시 파싱해도 중복 행이 쌓이지 않는다(tests/test_guru_tracker.py 의
test_sync_guru_holdings_replaces_previous_snapshot 가 이미 이 성질을 고정하고 있다).
이 모듈은 그 위에 "불필요한 재파싱을 애초에 하지 않는" 층만 더한다.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SYNC_STATE_PATH = PROJECT_ROOT / "data" / "cache" / "guru_sync_state.json"

# 13F 는 분기 공시라 매일 확인할 이유가 없다. 3일마다 accession 만 확인하면 새 공시를
# 최대 3일 안에 잡으면서 SEC 요청 수는 1/3로 줄어든다(45일 지연 데이터라 3일은 무의미한 지연).
THIRTEEN_F_CHECK_INTERVAL_DAYS = 3

# SEC 초당 5회 이하 유지를 위한 거장 간 최소 간격(초).
SEC_REQUEST_INTERVAL = 0.25

JOB_ID = "guru_holdings_sync"


# ---------------------------------------------------------------------------
# 상태 파일 (core/champion_strategy.py 의 *_STATE_CACHE_PATH 관례와 동일한 JSON 캐시)
# ---------------------------------------------------------------------------


def _load_state() -> dict:
    try:
        with open(SYNC_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    try:
        SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SYNC_STATE_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        tmp.replace(SYNC_STATE_PATH)
    except OSError:
        pass  # 상태 저장 실패는 다음 실행에서 "간격 지남"으로 판단돼 재시도될 뿐이라 치명적이지 않다.


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 변동 감지 (신규 편입 / 전량 청산)
# ---------------------------------------------------------------------------


def _holding_keys(holdings: list[dict]) -> set[str]:
    """비교 키: 티커가 있으면 티커, 없으면 원문 종목명(티커 역추적 실패분도 놓치지 않게)."""
    keys = set()
    for h in holdings:
        key = (h.get("ticker") or "").strip().upper() or (h.get("issuer_name") or "").strip().upper()
        if key:
            keys.add(key)
    return keys


def _format_change_message(guru_name: str, filing_date: Optional[str], added: list[str], removed: list[str]) -> str:
    lines = [f"🧠 거장 포트폴리오 변동: {guru_name}" + (f" (공시일 {filing_date})" if filing_date else "")]
    if added:
        lines.append(f"신규 편입 {len(added)}건: {', '.join(added[:10])}" + (" 외" if len(added) > 10 else ""))
    if removed:
        lines.append(f"전량 청산 {len(removed)}건: {', '.join(removed[:10])}" + (" 외" if len(removed) > 10 else ""))
    lines.append("※ 13F 는 최대 45일 지연 공시입니다. 참고용 정보이며 매매 신호가 아닙니다.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 배치 동기화
# ---------------------------------------------------------------------------


def sync_all_gurus(
    force: bool = False,
    now: Optional[datetime] = None,
    notify_fn: Optional[Callable[[str], object]] = None,
    notify: bool = True,
    sleep_fn: Callable[[float], object] = time.sleep,
) -> dict:
    """추적 중인 전체 거장을 한 번에 동기화한다. **한 명이 실패해도 나머지는 계속 진행한다.**

    Args:
        force: True면 13F 간격/accession 게이트를 무시하고 전원 재파싱한다(수동 강제 새로고침용).
        now: 기준 시각(테스트 주입용). None이면 현재 UTC.
        notify_fn: 텔레그램 전송 함수(테스트 주입용). None이면 core.telegram_notify.send_message.
        notify: False면 변동 알림을 보내지 않는다(변동 감지 자체는 결과 dict 에 남는다).
        sleep_fn: rate limit 대기 함수(테스트 주입용).

    Returns:
        {"as_of", "n_total", "n_synced", "n_skipped", "n_failed", "n_notified", "results": [...]}
        results 각 항목: {"guru_name", "source", "status": "synced"|"skipped"|"failed",
                          "reason", "filing_date", "holding_count", "added", "removed"}
    """
    from core.guru_tracker import (
        _find_latest_13f_filing,
        get_all_gurus,
        get_guru_holdings,
        sync_guru_holdings,
    )

    if notify_fn is None and notify:
        try:
            from core.telegram_notify import send_message as notify_fn
        except Exception:  # noqa: BLE001 - 알림 모듈이 없어도 동기화 자체는 돌아야 한다.
            notify_fn = None

    now = now or datetime.now(timezone.utc)
    state = _load_state()
    guru_state: dict = state.get("gurus") if isinstance(state.get("gurus"), dict) else {}

    gurus = get_all_gurus()
    results: list[dict] = []
    n_notified = 0

    for index, (guru_name, info) in enumerate(gurus.items()):
        source = info.get("source") or "13F"
        prev = guru_state.get(guru_name) if isinstance(guru_state.get(guru_name), dict) else {}
        entry: dict = {
            "guru_name": guru_name,
            "source": source,
            "status": "skipped",
            "reason": None,
            "filing_date": prev.get("filing_date"),
            "holding_count": prev.get("holding_count"),
            "added": [],
            "removed": [],
        }

        latest: Optional[dict] = None
        try:
            if index:
                sleep_fn(SEC_REQUEST_INTERVAL)  # SEC 초당 5회 이하 유지

            if source != "ark_daily" and not force:
                # 1단계: 마지막 확인 이후 간격이 안 지났으면 네트워크도 타지 않는다.
                last_checked = _parse_iso(prev.get("last_checked_at"))
                if last_checked and now - last_checked < timedelta(days=THIRTEEN_F_CHECK_INTERVAL_DAYS):
                    entry["reason"] = (
                        f"13F 분기 공시 — 마지막 확인 이후 {THIRTEEN_F_CHECK_INTERVAL_DAYS}일 미경과"
                    )
                    results.append(entry)
                    continue

                # 2단계: submissions JSON 1회로 최신 accession 만 비교 (infoTable 파싱 안 함).
                latest = _find_latest_13f_filing(info["cik"])
                prev_state = dict(prev)
                prev_state["last_checked_at"] = now.isoformat()
                guru_state[guru_name] = prev_state

                if latest is None:
                    entry["reason"] = "SEC 에 13F-HR 공시가 없음"
                    results.append(entry)
                    continue

                if prev.get("accession") == latest["accession"]:
                    entry["reason"] = f"새 13F 공시 없음 (최신 공시일 {latest.get('filing_date')})"
                    entry["filing_date"] = latest.get("filing_date")
                    results.append(entry)
                    continue

            before_keys = _holding_keys(get_guru_holdings(guru_name))
            result = sync_guru_holdings(guru_name)
            after = get_guru_holdings(guru_name)
            after_keys = _holding_keys(after)

            added = sorted(after_keys - before_keys)
            removed = sorted(before_keys - after_keys)

            entry.update(
                {
                    "status": "synced",
                    "reason": "ARK 일별 CSV 갱신" if source == "ark_daily" else "새 13F 공시 반영",
                    "filing_date": result.get("filing_date"),
                    "holding_count": result.get("holding_count"),
                    "added": added,
                    "removed": removed,
                }
            )

            new_state = dict(guru_state.get(guru_name) or {})
            new_state.update(
                {
                    "last_checked_at": now.isoformat(),
                    "last_synced_at": now.isoformat(),
                    "filing_date": result.get("filing_date"),
                    "holding_count": result.get("holding_count"),
                }
            )
            if source != "ark_daily":
                # force=True 경로에서는 accession 을 따로 조회하지 않았으므로(불필요한 SEC 요청
                # 회피) 그때는 한 번 확인해 다음 실행이 다시 파싱하지 않도록 저장해 둔다.
                if latest is None:
                    try:
                        sleep_fn(SEC_REQUEST_INTERVAL)
                        latest = _find_latest_13f_filing(info["cik"])
                    except Exception:  # noqa: BLE001 - accession 저장 실패는 다음 실행 재파싱일 뿐.
                        latest = None
                if latest and latest.get("accession"):
                    new_state["accession"] = latest["accession"]
            guru_state[guru_name] = new_state

            # 최초 동기화(이전 스냅샷 없음)는 전 종목이 "신규"로 보이므로 알리지 않는다 — 소음 방지.
            if notify and notify_fn is not None and before_keys and (added or removed):
                try:
                    notify_fn(_format_change_message(guru_name, result.get("filing_date"), added, removed))
                    n_notified += 1
                except Exception as exc:  # noqa: BLE001 - 알림 실패가 동기화 결과를 망치지 않게.
                    entry["notify_error"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - 한 거장의 실패가 나머지를 막으면 안 된다.
            entry["status"] = "failed"
            entry["reason"] = f"{type(exc).__name__}: {exc}"

        results.append(entry)

    state["gurus"] = guru_state
    state["last_run_at"] = now.isoformat()
    _save_state(state)

    return {
        "as_of": now.isoformat(),
        "n_total": len(results),
        "n_synced": sum(1 for r in results if r["status"] == "synced"),
        "n_skipped": sum(1 for r in results if r["status"] == "skipped"),
        "n_failed": sum(1 for r in results if r["status"] == "failed"),
        "n_notified": n_notified,
        "results": results,
    }


def summarize_sync(result: dict) -> str:
    """스케줄러 로그 한 줄 요약."""
    failed = [r["guru_name"] for r in result.get("results", []) if r["status"] == "failed"]
    line = (
        f"거장 {result.get('n_total', 0)}명 중 갱신 {result.get('n_synced', 0)}명, "
        f"스킵 {result.get('n_skipped', 0)}명, 실패 {result.get('n_failed', 0)}명"
    )
    if failed:
        line += f" (실패: {', '.join(failed[:3])})"
    return line


# ---------------------------------------------------------------------------
# UI 용 조회 (app/pages/4_거장_포트폴리오.py)
# ---------------------------------------------------------------------------


def get_auto_sync_status(now: Optional[datetime] = None) -> dict:
    """"마지막 자동 동기화 시각 / 다음 예정 시각"을 페이지에 보여주기 위한 조회 함수.

    Returns:
        {"last_run_at": datetime|None, "next_run_at": datetime|None, "enabled": bool,
         "gurus": {guru_name: {"last_synced_at": datetime|None, "filing_date": str|None}}}
        (시각은 모두 Asia/Seoul tz-aware)
    """
    from zoneinfo import ZoneInfo

    kst = ZoneInfo("Asia/Seoul")
    now = now or datetime.now(timezone.utc)

    state = _load_state()
    guru_state = state.get("gurus") if isinstance(state.get("gurus"), dict) else {}

    last_run = _parse_iso(state.get("last_run_at"))

    next_run = None
    try:
        from apscheduler.triggers.cron import CronTrigger

        from core.job_schedule import SCHEDULED_JOBS_BY_ID

        job = SCHEDULED_JOBS_BY_ID.get(JOB_ID)
        if job is not None:
            next_run = CronTrigger(**job.cron).get_next_fire_time(None, now.astimezone(kst))
    except Exception:  # noqa: BLE001 - 다음 예정 시각은 부가정보라 실패해도 화면을 막지 않는다.
        next_run = None

    enabled = True
    try:
        from core.process_registry import is_enabled

        enabled = is_enabled(JOB_ID)
    except Exception:  # noqa: BLE001
        enabled = True

    gurus = {}
    for name, entry in guru_state.items():
        if not isinstance(entry, dict):
            continue
        synced = _parse_iso(entry.get("last_synced_at"))
        gurus[name] = {
            "last_synced_at": synced.astimezone(kst) if synced else None,
            "filing_date": entry.get("filing_date"),
        }

    return {
        "last_run_at": last_run.astimezone(kst) if last_run else None,
        "next_run_at": next_run.astimezone(kst) if next_run else None,
        "enabled": enabled,
        "gurus": gurus,
    }
