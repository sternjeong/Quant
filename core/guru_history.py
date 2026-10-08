"""거장 13F 보유 이력(공시일 기준) — 새틀라이트 R&D 가 '그때 알 수 있던' 거장 포트폴리오를 쓰게 한다 (2026-10-08).

사용자 요청(2026-10-08): "거장들의 포트폴리오를 잘 참고해서 내 포트폴리오의 새틀라이트를 구성하든 아니면 챔피언 전략을 잘 짤 수
있지 않을까? 이것도 연구 R&D 주제로 올려줘". core/guru_tracker.py 는 최신 스냅샷만 저장하므로, 여기서 분기별 13F 이력을 모은다.

거장: guru_tracker.TRACKED_GURUS 전부(캐시 우드도 13F 로 — ARK 일별 CSV 는 과거 이력이 없다).
출처: SEC EDGAR submissions(13F-HR 목록, 정정본 제외) → 각 공시의 infoTable XML(종목명·CUSIP·평가액). XML 13F 는 2013년 2분기부터라
그 전에는 데이터가 없다(연구 신호는 '모름' — 현 규칙대로).
티커: 13F 에는 티커가 없어 종목명을 SEC 회사 목록(company_tickers.json) 이름과 정규화해 맞춘다(맞춘 비율을 기록).
시점 규칙: view 는 기준일까지 '공시된' 13F 만 쓴다(분기 말 + 최대 45일 지연이 그대로 반영됨).
저장: data/satellite_lab/guru13f/<CIK>.json (공시마다 상위 보유만이 아니라 전부, 종목당 평가액·비중). 주문 경로와 무관.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = PROJECT_ROOT / "data" / "satellite_lab" / "guru13f"
REFRESH_DAYS = 7
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/index.json"
FILE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{name}"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
NS = {"n": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}
_NOISE = {"INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "PLC", "SA", "AG", "NV", "LP", "LLC",
          "HOLDINGS", "HLDGS", "HLDG", "GROUP", "GRP", "THE", "COM", "NEW", "DEL", "CL", "CLASS", "A", "B", "C", "SHS", "ORD", "ADR",
          "SPONSORED", "SPON", "COMMON", "STOCK", "STK", "OF", "AND"}
_ABBR = {"PETE": "PETROLEUM", "FINL": "FINANCIAL", "INTL": "INTERNATIONAL", "TECHS": "TECHNOLOGIES", "TECHNOLOGY": "TECHNOLOGIES",
         "IND": "INDUSTRIES", "INDS": "INDUSTRIES", "MTG": "MORTGAGE", "BK": "BANK", "AMER": "AMERICA", "SVCS": "SERVICES",
         "SYS": "SYSTEMS", "COMMUNICATIONS": "COMMUNICATION", "COMM": "COMMUNICATION", "HOLDING": "", "PHARMACEUTICALS": "PHARMACEUTICAL",
         "LABS": "LABORATORIES", "MFG": "MANUFACTURING", "ENTMT": "ENTERTAINMENT", "SOLUTIONS": "SOLUTION", "BANCORPORATION": "BANCORP"}


def norm_name(name: str) -> str:
    s = re.sub(r"[^A-Z0-9 ]", " ", str(name).upper().replace("&", " AND "))
    toks = [_ABBR.get(t, t) for t in s.split()]
    return " ".join(t for t in toks if t and t not in _NOISE)


def parse_infotable(xml_bytes: bytes) -> list[dict]:
    """13F infoTable XML → [{name, cusip, value}] (같은 CUSIP 합산, 옵션(putCall)은 제외)."""
    root = ET.fromstring(xml_bytes)
    agg: dict[str, dict] = {}
    for e in root.findall("n:infoTable", NS) or root.findall("infoTable"):
        g = (lambda tag: e.findtext(f"n:{tag}", default="", namespaces=NS) or e.findtext(tag, default=""))
        if (g("putCall") or "").strip():
            continue
        cusip = (g("cusip") or "").strip().upper()
        name = (g("nameOfIssuer") or "").strip()
        try:
            value = float(g("value") or 0)
        except ValueError:
            value = 0.0
        if not cusip and not name:
            continue
        a = agg.setdefault(cusip or name, {"name": name, "cusip": cusip, "value": 0.0})
        a["value"] += value
    return list(agg.values())


def view_from_filings(per_guru: dict[str, list[dict]], ticker: str, asof: date) -> dict[str, Any]:
    """per_guru: {거장: [{filed, period, holdings: [{ticker, weight}]}...]} → 기준일에 알 수 있던 그 종목의 거장 보유 상태."""
    n_holders = n_new = n_top5 = 0
    max_w = 0.0
    seen_any = False
    for guru, filings in per_guru.items():
        known = [f for f in filings if date.fromisoformat(f["filed"]) <= asof]
        if not known:
            continue
        seen_any = True
        known.sort(key=lambda f: (f["period"], f["filed"]))
        last = known[-1]
        prev = known[-2] if len(known) > 1 else None
        hold = {h["ticker"]: h["weight"] for h in last["holdings"] if h.get("ticker")}
        if ticker in hold:
            n_holders += 1
            max_w = max(max_w, hold[ticker])
            top5 = sorted(hold.values(), reverse=True)[:5]
            if hold[ticker] >= (top5[-1] if top5 else 1.0):
                n_top5 += 1
            if prev is not None and ticker not in {h["ticker"] for h in prev["holdings"] if h.get("ticker")}:
                n_new += 1
    if not seen_any:
        return {}
    return {"n_holders": n_holders, "n_new": n_new, "n_top5": n_top5, "max_weight": max_w}


class Store:
    """거장별 13F 이력. fetch=False 면 디스크에 있는 것만."""

    def __init__(self, store_dir: Optional[Path] = None, *, fetch: bool = True, client=None,
                 gurus: Optional[dict] = None, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.dir = Path(store_dir or STORE_DIR)
        self.fetch = fetch
        self._client = client
        self._now = now
        self._gurus = gurus
        self._data: Optional[dict[str, list[dict]]] = None

    def gurus(self) -> dict[str, str]:
        if self._gurus is not None:
            return self._gurus
        from core.guru_tracker import TRACKED_GURUS

        return {name: g["cik"] for name, g in TRACKED_GURUS.items() if g.get("cik")}

    def _c(self):
        if self._client is None:
            from core.filing_changes import EdgarClient

            self._client = EdgarClient(record_first_seen=False)
        return self._client

    def _name_map(self) -> dict[str, str]:
        raw = json.loads(self._c()._get(TICKERS_URL))
        rows = raw.values() if isinstance(raw, dict) else raw
        out: dict[str, str] = {}
        for r in rows:
            key = norm_name(r.get("title", ""))
            if key and key not in out:
                out[key] = str(r.get("ticker", "")).upper().replace(".", "-")
        # 관제 센터 '거장 포트폴리오'가 yfinance 로 이미 풀어 둔 종목명 → 티커 캐시도 쓴다(있으면)
        try:
            from core.guru_tracker import TICKER_CACHE_FILE

            for raw_name, t in json.loads(Path(TICKER_CACHE_FILE).read_text(encoding="utf-8")).items():
                if t:
                    out.setdefault(norm_name(raw_name), str(t).upper().replace(".", "-"))
        except (OSError, ValueError, ImportError):
            pass
        return out

    def _path(self, cik: str) -> Path:
        return self.dir / f"{cik}.json"

    def _fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        try:
            got = datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["fetched_at"])
        except (OSError, ValueError, KeyError):
            return False
        return self._now() - got <= timedelta(days=REFRESH_DAYS)

    def _download(self, cik: str, names: dict[str, str]) -> dict:
        c = self._c()
        meta = json.loads(c._get(SUBMISSIONS_URL.format(cik=cik)))
        blocks = [(meta.get("filings") or {}).get("recent") or {}]
        for f in (meta.get("filings") or {}).get("files") or []:
            name = str(f.get("name", ""))
            if name.startswith("CIK") and name.endswith(".json"):
                blocks.append(json.loads(c._get(SUBMISSIONS_FILE_URL.format(name=name))))
        old = {}
        p = self._path(cik)
        if p.exists():
            try:
                old = {f["accession"]: f for f in json.loads(p.read_text(encoding="utf-8")).get("filings", [])}
            except (OSError, ValueError):
                old = {}
        filings, matched, total, w_matched, w_total = [], 0, 0, 0.0, 0.0
        for cols in blocks:
            forms, accs, fdates = cols.get("form") or [], cols.get("accessionNumber") or [], cols.get("filingDate") or []
            periods = cols.get("reportDate") or [""] * len(forms)
            for i, form in enumerate(forms):
                if form != "13F-HR":
                    continue
                acc = accs[i]
                if acc in old:
                    filings.append(old[acc])
                    continue
                nodash = acc.replace("-", "")
                try:
                    items = json.loads(c._get(INDEX_URL.format(cik_int=int(cik), acc=nodash))).get("directory", {}).get("item", [])
                    xmls = [it.get("name", "") for it in items if it.get("name", "").lower().endswith(".xml")]
                    pick = next((n for n in xmls if "info" in n.lower()), None) or next((n for n in xmls if n.lower() != "primary_doc.xml"), None)
                    if not pick:
                        continue
                    rows = parse_infotable(c._get(FILE_URL.format(cik_int=int(cik), acc=nodash, name=pick)))
                except Exception:  # noqa: BLE001 - 2013 이전 텍스트 13F 등
                    continue
                tot = sum(r["value"] for r in rows) or 1.0
                hold = []
                for r in rows:
                    t = names.get(norm_name(r["name"]))
                    total += 1
                    matched += int(bool(t))
                    w_total += r["value"] / tot
                    w_matched += (r["value"] / tot) if t else 0.0
                    hold.append({"name": r["name"], "cusip": r["cusip"], "ticker": t, "weight": r["value"] / tot})
                filings.append({"accession": acc, "filed": fdates[i], "period": periods[i] or fdates[i], "holdings": hold})
        return {"cik": cik, "fetched_at": self._now().isoformat(timespec="seconds"), "filings": filings,
                "match_rate_new": (matched / total) if total else None,
                "match_weight_new": (w_matched / w_total) if w_total else None}

    def _write(self, cik: str, rec: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".g.")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, separators=(",", ":"))
        os.replace(tmp, self._path(cik))

    def prefetch(self, deadline: Optional[float] = None, log: Callable[[str], Any] = lambda s: None) -> dict:
        names = None
        done = left = 0
        for guru, cik in self.gurus().items():
            if deadline is not None and time.time() > deadline:
                left += 1
                continue
            if self.fetch and not self._fresh(self._path(cik)):
                names = names or self._name_map()
                self._write(cik, self._download(cik, names))
                log(f"13F {guru} 받음")
            done += 1
        self._data = None
        return {"done": done, "left": left, "complete": left == 0}

    def load(self) -> dict[str, list[dict]]:
        if self._data is None:
            out = {}
            for guru, cik in self.gurus().items():
                p = self._path(cik)
                if p.exists():
                    try:
                        out[guru] = json.loads(p.read_text(encoding="utf-8")).get("filings", [])
                    except (OSError, ValueError):
                        continue
            self._data = out
        return self._data

    def view(self, ticker: str, asof: date) -> dict:
        return view_from_filings(self.load(), ticker, asof)


class SyntheticStore(Store):
    """검사·스모크용 가짜 거장 보유(티커·날짜로 정해지는 결정론 값)."""

    def __init__(self):
        super().__init__(store_dir=Path(tempfile.gettempdir()) / "synthetic_guru13f", fetch=False, gurus={})

    def view(self, ticker: str, asof: date) -> dict:
        h = sum(ord(c) for c in ticker) + asof.year * 4 + (asof.month - 1) // 3
        return {"n_holders": h % 3, "n_new": int(h % 7 == 0), "n_top5": int(h % 5 == 0), "max_weight": (h % 20) / 100.0}
