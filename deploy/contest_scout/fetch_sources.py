"""대회 목록 미리 받기 — Claude 실행 전에 run_scout.sh 가 주 1회 부른다(표준 라이브러리만 쓴다, 2026-11-12 사용자 승인).

Devpost 목록 화면과 aichallenge4all 메인 화면은 대회 카드를 JSON 주소에서 받아 그린다. 페이지 HTML 에는 목록이 없어서
Claude 가 페이지를 열어도 대회가 0개로 보였다(2026-11-12 첫 실행). 그래서 그 JSON 을 한 번씩 받아
SCOUT_DIR/sources/*.json 으로 줄여 쓰고, Claude 는 이 파일을 먼저 읽은 뒤 유망한 대회만 상세 페이지를 연다.
둘 다 문서화된 공개 API 가 아니라 깨질 수 있다 — 한 곳이 실패하면 그 파일만 빼고 계속한다(Claude 는 웹 검색으로 보완).
User-Agent 는 이 도구임을 그대로 밝힌다.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

UA = "QuantHub-ContestScout/1.0 (weekly personal contest digest)"
DEVPOST = "https://devpost.com/api/hackathons?status[]=open&per_page=40&page={page}"
AC4A = "https://aichallenge4all.or.kr/api/{name}"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def devpost() -> list[dict]:
    out, page = [], 1
    while page <= 5:
        data = _get(DEVPOST.format(page=page))
        for h in data.get("hackathons") or []:
            out.append({
                "title": h.get("title"), "url": h.get("url"), "organizer": h.get("organization_name"),
                "location": (h.get("displayed_location") or {}).get("location"),
                "submission_period": h.get("submission_period_dates"), "time_left": h.get("time_left_to_submission"),
                "prize": re.sub(r"<[^>]+>", "", h.get("prize_amount") or ""), "registrations": h.get("registrations_count"),
                "themes": [t.get("name") for t in h.get("themes") or []], "invite_only": h.get("invite_only"),
            })
        meta = data.get("meta") or {}
        if page * int(meta.get("per_page") or 40) >= int(meta.get("total_count") or 0):
            break
        page += 1
    return out


def aichallenge4all() -> dict:
    cards = _get(AC4A.format(name="competitions-cards"))
    home = _get(AC4A.format(name="home-competitions"))
    tracks = [{k: c.get(k) for k in ("name", "description", "target", "displayStatus", "detailUrl", "isOnline")}
              for c in cards.get("competitions") or []]
    extra = [{k: c.get(k) for k in ("name", "org", "href", "status")} for c in home.get("posterExtra") or []]
    return {"tracks": tracks, "partner_contests": extra}


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/srv/contests/.scout") / "sources"
    out_dir.mkdir(exist_ok=True)
    for name, fn in (("devpost", devpost), ("aichallenge4all", aichallenge4all)):
        try:
            data = fn()
            (out_dir / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
            count = len(data) if isinstance(data, list) else sum(map(len, data.values()))
            print(f"sources/{name}.json: {count}건")
        except Exception as exc:  # noqa: BLE001 — 한 곳 실패가 탐색 전체를 막지 않게
            (out_dir / f"{name}.json").unlink(missing_ok=True)
            print(f"sources/{name}.json: 실패 {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
