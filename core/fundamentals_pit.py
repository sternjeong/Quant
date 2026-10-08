"""시점 기준(point-in-time) 재무·실적 발표 데이터 — 새틀라이트 R&D 가 가격 밖의 정보를 쓰게 한다 (2026-10-08, 사용자 "이대로 진행").

새틀라이트 R&D 의 가격만 쓰는 아이디어 11개가 모두 탈락해(2026-10-08 기준), 재무·실적 정보를 넣는다.
출처: SEC EDGAR (무료, 공시일이 붙어 있음)
  - XBRL companyfacts: 매출·매출총이익·매출원가·영업이익·순이익·총자산 — 각 숫자의 공시일(filed)
  - submissions: 업종 코드(SIC), 실적 발표 8-K(Item 2.02) 날짜
원본은 크므로(회사당 수 MB) 필요한 항목만 뽑아 data/satellite_lab/fundamentals/<티커>.json 에 작게 저장한다(30일 지나면 다시 받음).
시점 규칙: view(티커, 기준일)은 기준일까지 '공시된' 숫자만 쓴다(같은 기간을 나중에 고친 공시는 기준일 전에 나온 것만).
한계: 티커 → CIK 는 SEC 의 현재 목록이라 상장폐지·티커 변경 회사는 대개 데이터가 없다(신호는 '모름'으로 다뤄 제외하지 않는다).
주문 경로와 연결되어 있지 않다. LLM 을 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = PROJECT_ROOT / "data" / "satellite_lab" / "fundamentals"
REFRESH_DAYS = 30
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SUBMISSIONS_FILE_URL = "https://data.sec.gov/submissions/{name}"
CONCEPTS = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"),
    "gross_profit": ("GrossProfit",),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"),
    "assets": ("Assets",),
}
QUARTER_DAYS = (80, 100)
YEAR_DAYS = (330, 380)
MAX_QUARTER_AGE_DAYS = 200   # 기준일보다 이만큼 넘게 지난 분기 값은 '모름'(공시가 끊긴 항목을 최신처럼 쓰지 않게)
MAX_ANNUAL_AGE_DAYS = 550


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


# ---------------------------------------------------------------- 원본 → 작은 기록
def compact_companyfacts(raw: dict) -> dict:
    """companyfacts JSON → {항목: [[start|None, end, val, filed, form], ...]} (USD 만, 10-K/10-Q 계열만)."""
    gaap = (raw.get("facts") or {}).get("us-gaap") or {}
    out: dict[str, list] = {}
    for key, names in CONCEPTS.items():
        rows = []
        for name in names:
            for unit, facts in ((gaap.get(name) or {}).get("units") or {}).items():
                if unit != "USD":
                    continue
                for f in facts:
                    form = str(f.get("form", ""))
                    if not form.startswith(("10-K", "10-Q", "20-F", "40-F")) or "end" not in f or "filed" not in f:
                        continue
                    rows.append([f.get("start"), f["end"], float(f["val"]), f["filed"], form])
        # 같은 (start, end, filed) 는 개념 이름 순서상 앞의 것만
        seen, uniq = set(), []
        for r in rows:
            k = (r[0], r[1], r[3])
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        out[key] = sorted(uniq, key=lambda r: (r[1], r[3]))
    return out


def compact_submissions(meta: dict, older_blocks: Iterable[dict] = ()) -> dict:
    """submissions → {sic, earnings_dates: [YYYY-MM-DD, ...]} (실적 발표 = 8-K 중 Item 2.02)."""
    dates = set()
    for cols in [((meta.get("filings") or {}).get("recent") or {}), *older_blocks]:
        forms, fdates, items = cols.get("form") or [], cols.get("filingDate") or [], cols.get("items") or []
        for i, form in enumerate(forms):
            it = items[i] if i < len(items) else ""
            if str(form).startswith("8-K") and "2.02" in str(it or "") and i < len(fdates):
                dates.add(fdates[i])
    try:
        sic = int(meta.get("sic") or 0) or None
    except (TypeError, ValueError):
        sic = None
    return {"sic": sic, "earnings_dates": sorted(dates)}


# ---------------------------------------------------------------- 시점 기준 계산
def _known(rows: list, asof: date, duration: Optional[tuple[int, int]]) -> dict[tuple, list]:
    """기준일까지 공시된 것만, 기간별로 가장 늦게(기준일 전) 공시된 값."""
    best: dict[tuple, list] = {}
    for r in rows:
        start, end, val, filed, form = r
        if _d(filed) > asof:
            continue
        if duration is None:
            if start is not None:
                continue
        else:
            if start is None:
                continue
            days = (_d(end) - _d(start)).days
            if not (duration[0] <= days <= duration[1]):
                continue
        k = (start, end)
        if k not in best or best[k][3] <= filed:
            best[k] = r
    return best


def _fresh(d: dict[tuple, list], asof: date, max_age: int) -> dict[tuple, list]:
    return {k: r for k, r in d.items() if (asof - _d(k[1])).days <= max_age}


def _yoy(q: dict[tuple, list]) -> list[tuple[str, float]]:
    """분기 값의 전년 같은 분기 대비 성장률, 최근 분기부터(가장 최근 분기가 기준일에서 너무 오래됐으면 빈 목록)."""
    by_end = {k[1]: r[2] for k, r in q.items()}
    ends = sorted(by_end, reverse=True)
    out = []
    for e in ends:
        target = _d(e) - timedelta(days=365)
        prior = [x for x in by_end if abs((_d(x) - target).days) <= 20]
        if prior and by_end[prior[0]] and by_end[prior[0]] > 0:
            out.append((e, by_end[e] / by_end[prior[0]] - 1.0))
    return out


def view_from_record(rec: dict, asof: date) -> dict[str, Any]:
    """한 회사 기록 → 기준일에 알 수 있던 지표. 모르면 None."""
    facts = rec.get("facts") or {}
    out: dict[str, Any] = {"sic": rec.get("sic"), "gp_assets": None, "rev_yoy": None, "rev_yoy_prev": None,
                           "ni_yoy": None, "last_earnings": None}
    annual_gp = _fresh(_known(facts.get("gross_profit", []), asof, YEAR_DAYS), asof, MAX_ANNUAL_AGE_DAYS)
    annual_rev = _fresh(_known(facts.get("revenue", []), asof, YEAR_DAYS), asof, MAX_ANNUAL_AGE_DAYS)
    annual_cost = _fresh(_known(facts.get("cost_of_revenue", []), asof, YEAR_DAYS), asof, MAX_ANNUAL_AGE_DAYS)
    assets = _known(facts.get("assets", []), asof, None)
    if annual_gp or (annual_rev and annual_cost):
        if annual_gp:
            k = max(annual_gp, key=lambda k: k[1])
            gp, end = annual_gp[k][2], k[1]
        else:
            common = sorted(set(k[1] for k in annual_rev) & set(k[1] for k in annual_cost))
            if common:
                end = common[-1]
                gp = next(r[2] for kk, r in annual_rev.items() if kk[1] == end) - next(r[2] for kk, r in annual_cost.items() if kk[1] == end)
            else:
                end = None
        if end:
            a = [r[2] for k, r in assets.items() if abs((_d(k[1]) - _d(end)).days) <= 5]
            if a and a[0] > 0:
                out["gp_assets"] = gp / a[0]
    rev_q = [x for x in _yoy(_known(facts.get("revenue", []), asof, QUARTER_DAYS))]
    rev_q = rev_q if rev_q and (asof - _d(rev_q[0][0])).days <= MAX_QUARTER_AGE_DAYS else []
    if rev_q:
        out["rev_yoy"] = rev_q[0][1]
        out["rev_yoy_prev"] = rev_q[1][1] if len(rev_q) > 1 else None
    ni_q = _yoy(_known(facts.get("net_income", []), asof, QUARTER_DAYS))
    ni_q = ni_q if ni_q and (asof - _d(ni_q[0][0])).days <= MAX_QUARTER_AGE_DAYS else []
    if ni_q:
        out["ni_yoy"] = ni_q[0][1]
    past = [d for d in rec.get("earnings_dates", []) if _d(d) <= asof]
    out["last_earnings"] = past[-1] if past else None
    return out


# ---------------------------------------------------------------- 저장소
class Store:
    """티커별 작은 기록을 디스크에 두고, 없거나 낡으면 SEC 에서 받는다. fetch=False 면 디스크에 있는 것만 쓴다."""

    def __init__(self, store_dir: Optional[Path] = None, *, fetch: bool = True, client=None,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.dir = Path(store_dir or STORE_DIR)
        self.fetch = fetch
        self._client = client
        self._now = now
        self._mem: dict[str, Optional[dict]] = {}

    def _path(self, ticker: str) -> Path:
        return self.dir / f"{ticker.upper().replace('/', '-')}.json"

    def _client_or_make(self):
        if self._client is None:
            from core.filing_changes import EdgarClient

            self._client = EdgarClient(record_first_seen=False)
        return self._client

    def _load_disk(self, ticker: str) -> Optional[dict]:
        p = self._path(ticker)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _stale(self, rec: Optional[dict]) -> bool:
        if not rec:
            return True
        try:
            got = datetime.fromisoformat(rec["fetched_at"])
        except (KeyError, ValueError):
            return True
        return self._now() - got > timedelta(days=REFRESH_DAYS)

    def ensure(self, ticker: str) -> Optional[dict]:
        """기록을 돌려준다(필요하면 받음). 받을 수 없는 티커는 {"missing": 사유} 를 저장해 30일 동안 다시 묻지 않는다."""
        if ticker in self._mem:
            return self._mem[ticker]
        rec = self._load_disk(ticker)
        if self.fetch and self._stale(rec):
            rec = self._download(ticker)
            self._write(ticker, rec)
        self._mem[ticker] = rec
        return rec

    def _download(self, ticker: str) -> dict:
        now = self._now().isoformat(timespec="seconds")
        c = self._client_or_make()
        try:
            cik = c.resolve_cik(ticker)
        except Exception as exc:  # noqa: BLE001 - 상장폐지·티커 변경 등
            return {"ticker": ticker, "fetched_at": now, "missing": f"cik: {type(exc).__name__}"}
        rec: dict[str, Any] = {"ticker": ticker, "cik": cik, "fetched_at": now}
        try:
            rec["facts"] = compact_companyfacts(json.loads(c._get(COMPANYFACTS_URL.format(cik=cik))))
        except Exception as exc:  # noqa: BLE001
            rec["facts"] = {}
            rec["facts_error"] = type(exc).__name__
        try:
            meta = json.loads(c._get(SUBMISSIONS_URL.format(cik=cik)))
            older = []
            for f in (meta.get("filings") or {}).get("files") or []:
                name = str(f.get("name", ""))
                if name.startswith("CIK") and name.endswith(".json"):
                    older.append(json.loads(c._get(SUBMISSIONS_FILE_URL.format(name=name))))
            rec.update(compact_submissions(meta, older))
        except Exception as exc:  # noqa: BLE001
            rec.setdefault("sic", None)
            rec.setdefault("earnings_dates", [])
            rec["submissions_error"] = type(exc).__name__
        return rec

    def _write(self, ticker: str, rec: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".f.")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, separators=(",", ":"))
        os.replace(tmp, self._path(ticker))

    def prefetch(self, tickers: Iterable[str], deadline: Optional[float] = None,
                 log: Callable[[str], Any] = lambda s: None) -> dict:
        """여러 티커를 미리 받는다. deadline(유닉스 초)을 넘으면 멈추고 다음에 이어 받는다(이미 받은 것은 디스크에 남음)."""
        done = left = 0
        tickers = sorted(set(tickers))
        for i, t in enumerate(tickers):
            if deadline is not None and time.time() > deadline:
                left = len(tickers) - i
                break
            self.ensure(t)
            done += 1
            if i % 50 == 0:
                log(f"재무 데이터 {i}/{len(tickers)}")
        return {"done": done, "left": left, "complete": left == 0}

    def view(self, ticker: str, asof: date) -> Optional[dict]:
        rec = self.ensure(ticker) if self.fetch else (self._mem.get(ticker) or self._load_disk(ticker))
        if not rec or rec.get("missing"):
            return None
        return view_from_record(rec, asof)


class Context:
    """신호에 넘기는 4번째 인자. 리밸런싱 기준일(전날)까지 공시된 것만 보여 준다."""

    def __init__(self, store: Store, asof):
        self._store = store
        self.asof = asof.date() if hasattr(asof, "date") else asof

    def fundamentals(self, ticker: str) -> Optional[dict]:
        return self._store.view(ticker, self.asof)


class SyntheticStore(Store):
    """검사·스모크용 가짜 재무(티커 이름으로 정해지는 결정론 값). 실데이터가 아니다."""

    def __init__(self):
        super().__init__(store_dir=Path(tempfile.gettempdir()) / "synthetic_fundamentals", fetch=False)

    def view(self, ticker: str, asof: date) -> Optional[dict]:
        h = sum(ord(c) for c in ticker)
        q = (asof.year * 4 + (asof.month - 1) // 3)
        return {"sic": 1000 * (h % 9 + 1), "gp_assets": (h % 50) / 100.0, "rev_yoy": ((h * q) % 41 - 15) / 100.0,
                "rev_yoy_prev": ((h * (q - 1)) % 41 - 15) / 100.0, "ni_yoy": ((h + q) % 31 - 10) / 100.0,
                "last_earnings": (asof - timedelta(days=(h % 60) + 5)).isoformat()}
