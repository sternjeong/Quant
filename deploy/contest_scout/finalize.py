"""대회 탐색 결과 확정 — Claude 가 쓴 draft.json 을 검사해 latest.json·history/<날짜>.json 으로 옮긴다.

run_scout.sh 가 tmux 안의 Claude 실행이 끝난 뒤 ubuntu 계정으로 부른다(표준 라이브러리만 쓴다).
형식이 틀리면 기존 latest.json 을 건드리지 않고 종료 코드 1 로 사유를 출력한다.
화면(hub/contest_scout_page.py)은 latest.json·status.json 만 읽는다.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
TIERS = ("auto", "light")
MAX_PER_TIER = 10
TEXT_FIELDS = ("title", "url", "organizer", "platform", "deadline", "deadline_note", "prize",
               "what_to_do", "why", "eligibility", "human_work")


def _clean(value, limit: int = 400) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize(draft: dict) -> dict:
    """draft → 저장 형식. 잘못된 항목은 버리고, 쓸 만한 항목이 하나도 없으면 ValueError."""
    if not isinstance(draft, dict) or not isinstance(draft.get("items"), list):
        raise ValueError("draft.json 에 items 목록이 없습니다")
    items, seen = [], set()
    for raw in draft["items"]:
        if not isinstance(raw, dict):
            continue
        item = {k: _clean(raw.get(k)) for k in TEXT_FIELDS}
        item["tier"] = _clean(raw.get("tier")).lower()
        if item["tier"] not in TIERS or not item["title"] or not item["url"].startswith(("http://", "https://")):
            continue
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        try:
            item["effort_hours"] = max(0, min(int(float(raw.get("effort_hours") or 0)), 999))
        except (TypeError, ValueError):
            item["effort_hours"] = 0
        item["tags"] = [_clean(t, 30) for t in (raw.get("tags") or []) if _clean(t, 30)][:6]
        items.append(item)
    for tier in TIERS:
        extra = [i for i in items if i["tier"] == tier][MAX_PER_TIER:]
        items = [i for i in items if i not in extra]
    if not items:
        raise ValueError("조건에 맞는 항목이 하나도 없습니다(tier/title/url 확인)")
    skipped = [{"title": _clean(s.get("title"), 120), "reason": _clean(s.get("reason"), 200)}
               for s in (draft.get("skipped") or []) if isinstance(s, dict) and s.get("title")][:15]
    sources = [_clean(s, 200) for s in (draft.get("sources_checked") or [])][:30]
    return {"items": items, "skipped": skipped, "sources_checked": sources, "notes": _clean(draft.get("notes"), 600)}


def mark_new(result: dict, previous: dict | None) -> dict:
    old = {i.get("url") for i in (previous or {}).get("items", []) if isinstance(i, dict)}
    for item in result["items"]:
        item["new"] = bool(previous) and item["url"] not in old
    return result


def _write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def finalize(scout_dir: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(KST)
    draft = json.loads((scout_dir / "draft.json").read_text(encoding="utf-8"))
    latest_path = scout_dir / "latest.json"
    try:
        previous = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    result = mark_new(normalize(draft), previous)
    result["generated_at"] = now.isoformat(timespec="seconds")
    (scout_dir / "history").mkdir(exist_ok=True)
    _write_atomic(scout_dir / "history" / f"{now:%Y-%m-%d}.json", result)
    _write_atomic(latest_path, result)
    (scout_dir / "draft.json").unlink()
    return result


def main() -> int:
    scout_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/srv/contests/.scout")
    try:
        result = finalize(scout_dir)
    except (OSError, ValueError) as exc:
        print(f"finalize 실패: {exc}")
        return 1
    counts = {t: sum(1 for i in result["items"] if i["tier"] == t) for t in TIERS}
    print(f"finalize 완료: auto {counts['auto']} · light {counts['light']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
