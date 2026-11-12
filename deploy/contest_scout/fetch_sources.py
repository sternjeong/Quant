"""대회 목록 미리 받기 — Claude 실행 전에 run_scout.sh 가 주 1회 부른다(표준 라이브러리만 쓴다, 2026-11-12 사용자 승인).

Devpost 목록 화면과 aichallenge4all 메인 화면은 대회 카드를 JSON 주소에서 받아 그린다. 페이지 HTML 에는 목록이 없어서
Claude 가 페이지를 열어도 대회가 0개로 보였다(2026-11-12 첫 실행). 그래서 그 JSON 을 한 번씩 받아
SCOUT_DIR/sources/*.json 으로 줄여 쓰고, Claude 는 이 파일을 먼저 읽은 뒤 유망한 대회만 상세 페이지를 연다.
2026-11-12 사용자 요청으로 곳을 늘렸다: HackerEarth·Unstop·Zindi·Devfolio(사이트가 쓰는 JSON),
Wevity 웹/모바일/IT·DrivenData(목록이 HTML 에 있음 — 대회 링크만 추린다). 사이트가 막으면(403 등) 우회하지 않고 건너뛴다.
대부분 문서화된 공개 API 가 아니라 깨질 수 있다 — 한 곳이 실패하면 그 파일만 빼고 계속한다(Claude 는 웹 검색으로 보완).
User-Agent 는 이 도구임을 그대로 밝힌다.
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

UA = "QuantHub-ContestScout/1.0 (weekly personal contest digest)"
DEVPOST = "https://devpost.com/api/hackathons?status[]=open&per_page=40&page={page}"
AC4A = "https://aichallenge4all.or.kr/api/{name}"
HACKEREARTH = "https://www.hackerearth.com/chrome-extension/events/"
UNSTOP = "https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons&page={page}&per_page=30&oppstatus=open"
ZINDI = "https://api.zindi.africa/v1/competitions?page=0&per_page=60&kind=competition&active=1"
DEVFOLIO = "https://api.devfolio.co/api/hackathons?filter=application_open&page=1"
WEVITY = "https://www.wevity.com/?c=find&s=1&gub=1&cidx=20&gp={page}"
DRIVENDATA = "https://www.drivendata.org/competitions/"


def _fetch(url: str, accept: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def _get(url: str) -> dict:
    return json.loads(_fetch(url, "application/json"))


def _links(page: str, base: str, href_re: str) -> list[dict]:
    """HTML 에서 href 가 href_re 에 맞는 링크의 (글자, 주소)만 추린다. 같은 주소는 한 번."""
    out, seen = [], set()
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, flags=re.S):
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inner)).split())
        href = html.unescape(href)
        if not re.search(href_re, href) or len(text) < 5:
            continue
        url = href if href.startswith("http") else base + href
        if url not in seen:
            seen.add(url)
            out.append({"title": text[:150], "url": url})
    return out


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


def hackerearth() -> list[dict]:
    keep = ("title", "url", "status", "challenge_type", "date", "end_date", "end_time", "end_tz", "college", "description")
    return [{k: e.get(k) for k in keep} for e in _get(HACKEREARTH).get("response") or []]


def unstop() -> list[dict]:
    """인도 대학 대상이 많아 온라인·접수 중인 것만 남긴다."""
    out = []
    for page in (1, 2, 3, 4):
        rows = (_get(UNSTOP.format(page=page)).get("data") or {}).get("data") or []
        for o in rows:
            if o.get("region") != "online" or not o.get("regn_open"):
                continue
            out.append({"title": o.get("title"), "url": "https://unstop.com/" + str(o.get("public_url") or ""),
                        "organizer": (o.get("organisation") or {}).get("name"), "end_date": o.get("end_date"),
                        "paid": o.get("isPaid"), "registrations": o.get("registerCount"),
                        "prizes": [p.get("cash") or p.get("rank") for p in o.get("prizes") or []][:5]})
        if len(rows) < 30:
            break
    return out


def zindi() -> list[dict]:
    keep = ("title", "reward", "end_time", "entries_close_at", "is_beginner_friendly", "kind", "participations_count")
    return [{**{k: c.get(k) for k in keep}, "organizer": c.get("organization"),
             "url": f"https://zindi.africa/competitions/{c.get('id')}"}
            for c in _get(ZINDI).get("data") or [] if c.get("open") and not c.get("secret_code_required")]


def devfolio() -> list[dict]:
    return [{"title": h.get("name"), "url": f"https://{h.get('slug')}.devfolio.co/", "tagline": h.get("tagline"),
             "starts_at": h.get("starts_at"), "ends_at": h.get("ends_at"), "country": h.get("country")}
            for h in _get(DEVFOLIO).get("result") or [] if h.get("is_online")]


def wevity() -> list[dict]:
    """국내 공모전 모음 '웹/모바일/IT' 분야 1~2쪽. 제목·주소만 있고 마감 등은 Claude 가 상세 페이지에서 확인한다."""
    out = []
    for page in (1, 2):
        out += _links(_fetch(WEVITY.format(page=page), "text/html"), "https://www.wevity.com/", r"ix=\d+")
    return out


def drivendata() -> list[dict]:
    return _links(_fetch(DRIVENDATA, "text/html"), "https://www.drivendata.org", r"^/competitions/\d+/")


SOURCES = (("devpost", devpost), ("aichallenge4all", aichallenge4all),
           ("hackerearth", hackerearth), ("unstop", unstop), ("zindi", zindi), ("devfolio", devfolio),
           ("wevity", wevity), ("drivendata", drivendata))


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/srv/contests/.scout") / "sources"
    out_dir.mkdir(exist_ok=True)
    for name, fn in SOURCES:
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
