"""모듈 D: 거장 포트폴리오 추종 (SEC EDGAR 13F 파싱 + ARK 일별 보유내역).

핵심 흐름:
    1. TRACKED_GURUS 에 정의된 기본 거장(+ data/custom_gurus.json 에 등록한 커스텀 거장)의
       CIK 로 SEC EDGAR 에서 최신 13F-HR 공시를 찾아 infoTable.xml 을 파싱한다.
    2. 13F infoTable 에는 티커가 없고 종목명(nameOfIssuer)/CUSIP 만 있으므로,
       yfinance 검색으로 티커를 역추적하고 결과를 파일 캐시에 저장해 재요청을 줄인다.
    3. 캐시 우드(ARK)는 13F(분기 지연) 대신 ARK 운용사가 매일 공개하는 CSV(티커 포함)를
       바로 사용해 더 정밀하게 추적한다.
    4. 파싱 결과는 core.models.GuruHolding 테이블에 "최신 스냅샷"으로 저장한다
       (재동기화 시 해당 거장의 기존 행을 지우고 새로 채워 넣는 방식 — 분기별 변동 이력
       누적은 스펙 범위 밖이라 생략, 필요해지면 filing_date 기준으로 append 하도록 바꾸면 됨).
    5. get_common_holdings() 로 여러 거장이 공통으로 보유한 종목(교집합)을 계산한다.

app/pages/4_거장_포트폴리오.py (Streamlit UI) 에서 이 모듈의 함수를 그대로 사용한다.
"""

from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests

from core.db import get_session
from core.models import GuruHolding

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TICKER_CACHE_FILE = CACHE_DIR / "issuer_ticker_cache.json"
CUSTOM_GURU_FILE = PROJECT_ROOT / "data" / "custom_gurus.json"

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/index.json"
SEC_FILING_FILE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{filename}"

SEC_13F_NS = {"n": "http://www.sec.gov/edgar/document/thirteenf/informationtable"}

REQUEST_TIMEOUT = 20

# SEC EDGAR 는 User-Agent에 연락처(이름/이메일)가 없으면 요청을 차단한다.
DEFAULT_UA = "QuantApp research contact@example.com"


def _sec_headers() -> dict:
    ua = os.getenv("SEC_EDGAR_USER_AGENT") or DEFAULT_UA
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


# ---------------------------------------------------------------------------
# 기본 추적 거장 리스트 (SPEC 확정 목록)
# ---------------------------------------------------------------------------

TRACKED_GURUS: dict[str, dict] = {
    "워런 버핏": {"cik": "0001067983", "fund_name": "Berkshire Hathaway", "source": "13F"},
    "마이클 버리": {"cik": "0001649339", "fund_name": "Scion Asset Management", "source": "13F"},
    "빌 애크먼": {"cik": "0001336528", "fund_name": "Pershing Square Capital Management", "source": "13F"},
    "캐시 우드": {"cik": "0001697748", "fund_name": "ARK Investment Management", "source": "ark_daily"},
    "스탠리 드러켄밀러": {"cik": "0001536411", "fund_name": "Duquesne Family Office", "source": "13F"},
    "데이비드 테퍼": {"cik": "0001656456", "fund_name": "Appaloosa LP", "source": "13F"},
    "세스 클라만": {"cik": "0001061768", "fund_name": "Baupost Group", "source": "13F"},
}

# 캐시 우드/ARK 는 13F 대신 매일 공개되는 펀드별 CSV로 추적 (더 정밀)
ARK_FUND_CSV_NAMES: dict[str, list[str]] = {
    "ARKK": ["ARK_INNOVATION_ETF_ARKK_HOLDINGS"],
    "ARKW": ["ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS"],
    "ARKG": ["ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS"],
    "ARKF": ["ARK_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS"],
    "ARKQ": [
        "ARK_AUTONOMOUS_TECH._&_ROBOTICS_ETF_ARKQ_HOLDINGS",
        "ARK_AUTONOMOUS_TECHNOLOGY_&_ROBOTICS_ETF_ARKQ_HOLDINGS",
    ],
    "ARKX": ["ARK_SPACE_EXPLORATION_&_INNOVATION_ETF_ARKX_HOLDINGS"],
}
ARK_CSV_BASE_URL = "https://assets.ark-funds.com/fund-documents/funds-etf-csv/{name}.csv"


@dataclass
class HoldingRow:
    ticker: Optional[str]
    name: str
    shares: Optional[float]
    value: Optional[float]
    weight_pct: Optional[float]


# ---------------------------------------------------------------------------
# 커스텀 거장 관리 ("추후 관심 있는 다른 펀드매니저 자유롭게 추가 가능")
# ---------------------------------------------------------------------------


def _load_custom_gurus() -> dict[str, dict]:
    if not CUSTOM_GURU_FILE.exists():
        return {}
    try:
        return json.loads(CUSTOM_GURU_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_custom_gurus(data: dict[str, dict]) -> None:
    CUSTOM_GURU_FILE.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_GURU_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_custom_guru(guru_name: str, cik: str, fund_name: str) -> None:
    """CIK 번호를 직접 입력해 임의의 펀드매니저를 추적 목록에 추가한다 (13F 기반)."""
    guru_name = (guru_name or "").strip()
    cik_digits = re.sub(r"\D", "", cik or "")
    if not guru_name or not cik_digits:
        raise ValueError("거장 이름과 CIK 번호를 모두 입력해주세요.")
    cik = cik_digits.zfill(10)
    if guru_name in TRACKED_GURUS:
        raise ValueError(f"'{guru_name}'은(는) 이미 기본 추적 목록에 있습니다.")

    custom = _load_custom_gurus()
    custom[guru_name] = {"cik": cik, "fund_name": fund_name or guru_name, "source": "13F"}
    _save_custom_gurus(custom)


def remove_custom_guru(guru_name: str) -> None:
    custom = _load_custom_gurus()
    if guru_name in custom:
        del custom[guru_name]
        _save_custom_gurus(custom)


def get_all_gurus() -> dict[str, dict]:
    """기본 추적 목록 + 커스텀 추가 목록을 합쳐서 반환한다."""
    merged = dict(TRACKED_GURUS)
    merged.update(_load_custom_gurus())
    return merged


def is_custom_guru(guru_name: str) -> bool:
    return guru_name in _load_custom_gurus()


# ---------------------------------------------------------------------------
# 종목명(issuer name) -> 티커 역추적 (파일 캐시)
# ---------------------------------------------------------------------------


def _load_ticker_cache() -> dict[str, Optional[str]]:
    if not TICKER_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(TICKER_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_ticker_cache(cache: dict[str, Optional[str]]) -> None:
    try:
        TICKER_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # 캐시 저장 실패는 무시


def _normalize_issuer_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().upper())


# 13F 종목명은 검색엔진이 알아듣기 힘든 축약어를 자주 쓴다. 흔한 축약어를 풀어써서
# 재시도하면 매칭률이 크게 올라간다 (예: "OCCIDENTAL PETE CORP" -> "OCCIDENTAL PETROLEUM CORP").
_ABBREVIATION_MAP = {
    "PETE": "PETROLEUM",
    "FINL": "FINANCIAL",
    "LTD": "LIMITED",
    "INTL": "INTERNATIONAL",
    "GRP": "GROUP",
    "HLDGS": "HOLDINGS",
    "HLDG": "HOLDING",
    "TECHS": "TECHNOLOGIES",
    "IND": "INDUSTRIES",
    "MTG": "MORTGAGE",
    "BK": "BANK",
}
# 국가/채권 표기 등 검색을 방해하는 토큰은 제거하고 재시도한다.
_STRIP_TOKENS = {"SWITZ", "MTN", "BE", "DEB", "NOTE", "NOTES", "BOND", "COM", "NEW"}
_CORP_SUFFIX_TOKENS = {"CORP", "CO", "INC", "LTD", "LIMITED", "PLC", "SA", "AG", "COMPANY", "INCORPORATED"}
_US_EXCHANGES = {"NMS", "NYQ", "NGM", "ASE", "NCM", "PCX", "BATS"}


def _expand_abbreviations(name: str) -> str:
    words = name.split(" ")
    return " ".join(_ABBREVIATION_MAP.get(w, w) for w in words)


def _strip_noise_tokens(name: str) -> str:
    words = [w for w in name.split(" ") if w not in _STRIP_TOKENS]
    return " ".join(words)


def _candidate_queries(issuer_name: str) -> list[str]:
    """검색 성공률을 높이기 위해 원문 -> 축약어 확장 -> 잡음 제거 -> 핵심 단어만, 순으로 시도할 후보들."""
    original = _normalize_issuer_name(issuer_name)
    if "BANK AMERICA" in original:
        original = original.replace("BANK AMERICA", "BANK OF AMERICA")

    candidates = [original]

    expanded = _expand_abbreviations(original)
    if expanded not in candidates:
        candidates.append(expanded)

    stripped = _strip_noise_tokens(expanded)
    if stripped not in candidates:
        candidates.append(stripped)

    core_words = [w for w in stripped.split(" ") if w not in _CORP_SUFFIX_TOKENS]
    if core_words:
        core = " ".join(core_words)
        if core not in candidates:
            candidates.append(core)

    return [c for c in candidates if c]


def resolve_ticker(issuer_name: str) -> Optional[str]:
    """13F의 nameOfIssuer(종목명)로 미국 상장 티커를 추정한다.

    yfinance 검색 결과를 파일 캐시(data/cache/issuer_ticker_cache.json)에 저장해
    같은 종목명을 여러 거장/여러 번 조회해도 네트워크 요청은 한 번만 하도록 한다.
    13F 특유의 축약 표기(PETE, FINL, LTD 등) 때문에 원문 그대로는 검색이 잘 안 맞는 경우가
    많아, 축약어를 풀어쓰거나 잡음 토큰(국가명/채권 표기 등)을 제거한 버전으로도 재시도한다.
    그래도 못 찾으면(주로 우선주/워런트/회사채 등) ticker=None 으로 저장하고 종목명만 표시한다.
    """
    key = _normalize_issuer_name(issuer_name)
    if not key:
        return None

    cache = _load_ticker_cache()
    if key in cache:
        return cache[key]

    ticker = None
    try:
        import yfinance as yf

        for query in _candidate_queries(issuer_name):
            search = yf.Search(query, max_results=5)
            candidates = [
                q
                for q in (search.quotes or [])
                if q.get("quoteType") == "EQUITY" and q.get("exchange") in _US_EXCHANGES
            ]
            if candidates:
                ticker = candidates[0].get("symbol")
                break
    except Exception:
        ticker = None

    cache[key] = ticker
    _save_ticker_cache(cache)
    return ticker


# ---------------------------------------------------------------------------
# SEC EDGAR 13F 조회/파싱
# ---------------------------------------------------------------------------


def _find_latest_13f_filing(cik: str) -> Optional[dict]:
    """가장 최근 13F-HR(또는 /A) 공시의 accession number/파일일자를 찾는다."""
    url = SEC_SUBMISSIONS_URL.format(cik=cik)
    resp = requests.get(url, headers=_sec_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])

    for form, accession, filing_date in zip(forms, accessions, dates):
        if form.startswith("13F-HR"):  # 13F-HR / 13F-HR/A (13F-NT 는 보유내역 없는 통지서라 제외)
            return {"accession": accession, "filing_date": filing_date, "cik": cik}
    return None


def _fetch_infotable_filename(cik: str, accession_nodash: str) -> Optional[str]:
    """공시 인덱스에서 실제 holdings XML 파일명을 찾는다 (파일명이 filer마다 다를 수 있음).

    보통 "infotable.xml" 같은 이름을 쓰지만, 제출 대행사에 따라 "53405.xml"처럼
    의미 없는 숫자 파일명을 쓰는 경우도 있다(예: 버크셔 해서웨이). 그런 경우를 대비해
    이름에 "infotable"이 없으면, primary_doc.xml/인덱스 파일이 아닌 첫 번째 .xml 파일로 대체한다.
    """
    cik_int = int(cik)
    url = SEC_FILING_INDEX_URL.format(cik_int=cik_int, accession_nodash=accession_nodash)
    resp = requests.get(url, headers=_sec_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    items = resp.json().get("directory", {}).get("item", [])

    xml_names = [item.get("name", "") for item in items if item.get("name", "").lower().endswith(".xml")]

    for name in xml_names:
        if "infotable" in name.lower() or "info_table" in name.lower():
            return name

    fallback = [n for n in xml_names if n.lower() != "primary_doc.xml"]
    if fallback:
        return fallback[0]
    return None


def _parse_infotable_xml(xml_bytes: bytes) -> list[HoldingRow]:
    """13F infoTable XML을 파싱해 종목명/CUSIP 기준으로 합산한 보유 리스트를 반환한다."""
    root = ET.fromstring(xml_bytes)
    aggregated: dict[str, dict] = {}

    for entry in root.findall("n:infoTable", SEC_13F_NS):
        name = (entry.findtext("n:nameOfIssuer", default="", namespaces=SEC_13F_NS) or "").strip()
        value_raw = entry.findtext("n:value", default="0", namespaces=SEC_13F_NS)
        shares_raw = entry.findtext("n:shrsOrPrnAmt/n:sshPrnamt", default="0", namespaces=SEC_13F_NS)

        try:
            value = float(value_raw) * 1000  # 13F 의 value 단위는 "천 달러"
        except (TypeError, ValueError):
            value = 0.0
        try:
            shares = float(shares_raw)
        except (TypeError, ValueError):
            shares = 0.0

        if not name:
            continue

        agg = aggregated.setdefault(name, {"shares": 0.0, "value": 0.0})
        agg["shares"] += shares
        agg["value"] += value

    total_value = sum(a["value"] for a in aggregated.values()) or 1.0

    rows = []
    for name, agg in aggregated.items():
        rows.append(
            HoldingRow(
                ticker=None,  # 이후 resolve_ticker() 로 채움
                name=name,
                shares=agg["shares"],
                value=agg["value"],
                weight_pct=round(agg["value"] / total_value * 100, 4),
            )
        )
    rows.sort(key=lambda r: r.value or 0, reverse=True)
    return rows


def fetch_latest_13f_holdings(cik: str, resolve_tickers: bool = True) -> tuple[list[HoldingRow], Optional[str]]:
    """CIK 기준 최신 13F 보유 종목을 조회한다.

    Returns:
        (보유종목 리스트, 공시일 "YYYY-MM-DD" 또는 None)
    """
    filing = _find_latest_13f_filing(cik)
    if filing is None:
        return [], None

    accession_nodash = filing["accession"].replace("-", "")
    filename = _fetch_infotable_filename(cik, accession_nodash)
    if filename is None:
        return [], filing["filing_date"]

    cik_int = int(cik)
    file_url = SEC_FILING_FILE_URL.format(cik_int=cik_int, accession_nodash=accession_nodash, filename=filename)
    resp = requests.get(file_url, headers=_sec_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    rows = _parse_infotable_xml(resp.content)

    if resolve_tickers:
        for row in rows:
            row.ticker = resolve_ticker(row.name)
            time.sleep(0.05)  # yfinance 과호출 방지용 짧은 딜레이

    return rows, filing["filing_date"]


# ---------------------------------------------------------------------------
# ARK 일별 보유내역 (캐시 우드)
# ---------------------------------------------------------------------------


def fetch_ark_fund_holdings(fund_ticker: str) -> tuple[list[HoldingRow], Optional[str]]:
    """ARK 펀드(예: ARKK)의 최신 일별 보유내역 CSV를 가져온다. 티커가 CSV에 포함되어 있어 조회가 필요 없다."""
    fund_ticker = fund_ticker.upper()
    candidate_names = ARK_FUND_CSV_NAMES.get(fund_ticker)
    if not candidate_names:
        raise ValueError(f"지원하지 않는 ARK 펀드입니다: {fund_ticker}")

    last_error: Optional[Exception] = None
    for name in candidate_names:
        url = ARK_CSV_BASE_URL.format(name=name)
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            last_error = e
            continue

        import io

        import pandas as pd

        try:
            df = pd.read_csv(io.StringIO(resp.text), thousands=",")
        except Exception as e:  # noqa: BLE001
            last_error = e
            continue

        if "fund" not in df.columns:
            continue
        df = df[df["fund"] == fund_ticker].copy()
        if df.empty:
            continue

        df["market value ($)"] = (
            df["market value ($)"].astype(str).str.replace(r"[$,]", "", regex=True).astype(float)
        )
        df["weight (%)"] = df["weight (%)"].astype(str).str.replace("%", "", regex=False).astype(float)

        filing_date = None
        if not df["date"].empty:
            try:
                filing_date = datetime.strptime(str(df["date"].iloc[0]), "%m/%d/%Y").strftime("%Y-%m-%d")
            except Exception:
                filing_date = None

        rows = [
            HoldingRow(
                ticker=(str(r["ticker"]).strip() or None) if pd.notna(r["ticker"]) else None,
                name=str(r["company"]),
                shares=float(r["shares"]) if pd.notna(r["shares"]) else None,
                value=float(r["market value ($)"]) if pd.notna(r["market value ($)"]) else None,
                weight_pct=float(r["weight (%)"]) if pd.notna(r["weight (%)"]) else None,
            )
            for _, r in df.iterrows()
        ]
        rows.sort(key=lambda r: r.weight_pct or 0, reverse=True)
        return rows, filing_date

    raise RuntimeError(f"ARK {fund_ticker} 보유내역 CSV를 가져오지 못했습니다: {last_error}")


ARK_DEFAULT_FUND = "ARKK"  # 캐시 우드 = ARK Investment Management, 대표 펀드는 ARKK(ARK Innovation ETF)


# ---------------------------------------------------------------------------
# DB 동기화 / 조회
# ---------------------------------------------------------------------------


def sync_guru_holdings(guru_name: str, ark_fund: str = ARK_DEFAULT_FUND) -> dict:
    """지정한 거장의 최신 보유 종목을 조회해 GuruHolding 테이블에 최신 스냅샷으로 저장한다.

    기존에 저장돼 있던 해당 거장의 행은 지우고 새로 채워 넣는다(=최신 분기/일자 스냅샷만 유지).

    Returns:
        {"guru_name", "fund_name", "filing_date", "holding_count", "resolved_ticker_count"}
    """
    gurus = get_all_gurus()
    info = gurus.get(guru_name)
    if info is None:
        raise ValueError(f"추적 목록에 없는 거장입니다: {guru_name}")

    if info.get("source") == "ark_daily":
        rows, filing_date = fetch_ark_fund_holdings(ark_fund)
        fund_name = f"{info['fund_name']} ({ark_fund})"
    else:
        rows, filing_date = fetch_latest_13f_holdings(info["cik"])
        fund_name = info["fund_name"]

    filing_date_obj: Optional[date] = None
    if filing_date:
        try:
            filing_date_obj = datetime.strptime(filing_date, "%Y-%m-%d").date()
        except ValueError:
            filing_date_obj = None

    resolved = sum(1 for r in rows if r.ticker)

    with get_session() as session:
        session.query(GuruHolding).filter(GuruHolding.guru_name == guru_name).delete()
        for row in rows:
            session.add(
                GuruHolding(
                    guru_name=guru_name,
                    fund_name=fund_name,
                    ticker=row.ticker,  # 티커 역추적 실패 시 None (issuer_name 으로 원문 종목명은 항상 보존)
                    issuer_name=row.name,
                    shares=row.shares,
                    weight_pct=row.weight_pct,
                    filing_date=filing_date_obj,
                )
            )

    return {
        "guru_name": guru_name,
        "fund_name": fund_name,
        "filing_date": filing_date,
        "holding_count": len(rows),
        "resolved_ticker_count": resolved,
    }


def get_synced_guru_names() -> list[str]:
    """DB에 한 번이라도 동기화된 거장 이름 목록 (최신순 아님, 이름순)."""
    with get_session() as session:
        names = session.query(GuruHolding.guru_name).distinct().order_by(GuruHolding.guru_name).all()
        return [n[0] for n in names]


def get_guru_holdings(guru_name: str) -> list[dict]:
    """특정 거장의 저장된 보유 종목을 비중 내림차순으로 반환한다."""
    with get_session() as session:
        rows = (
            session.query(GuruHolding)
            .filter(GuruHolding.guru_name == guru_name)
            .order_by(GuruHolding.weight_pct.desc().nullslast())
            .all()
        )
        return [
            {
                "ticker": r.ticker,
                "issuer_name": r.issuer_name,
                "fund_name": r.fund_name,
                "shares": r.shares,
                "weight_pct": r.weight_pct,
                "filing_date": r.filing_date,
            }
            for r in rows
        ]


def get_last_sync_info() -> dict[str, Optional[str]]:
    """거장별 마지막 동기화(공시) 날짜. {guru_name: "YYYY-MM-DD" | None}."""
    with get_session() as session:
        # SQLite는 PostgreSQL의 DISTINCT ON을 지원하지 않으므로 파이썬에서 거장별 최신 filing_date를 집계한다.
        latest: dict[str, Optional[date]] = {}
        for name, filing_date in session.query(GuruHolding.guru_name, GuruHolding.filing_date).all():
            if name not in latest or (filing_date and (latest[name] is None or filing_date > latest[name])):
                latest[name] = filing_date
        return {name: (d.isoformat() if d else None) for name, d in latest.items()}


def get_common_holdings(guru_names: list[str]) -> list[dict]:
    """여러 거장이 공통으로 보유한 종목(교집합)을 비중 합산 기준으로 정렬해 반환한다.

    티커가 확인되지 않은 종목(값이 종목명 임시 표기인 경우)은 교집합 계산에서 제외한다.
    """
    if len(guru_names) < 2:
        return []

    by_ticker: dict[str, dict] = {}
    with get_session() as session:
        rows = (
            session.query(GuruHolding)
            .filter(GuruHolding.guru_name.in_(guru_names))
            .all()
        )
        for r in rows:
            if not r.ticker:
                continue
            entry = by_ticker.setdefault(r.ticker, {"ticker": r.ticker, "gurus": {}, "total_weight": 0.0})
            entry["gurus"][r.guru_name] = r.weight_pct
            entry["total_weight"] += r.weight_pct or 0.0

    common = [e for e in by_ticker.values() if len(e["gurus"]) == len(set(guru_names))]
    common.sort(key=lambda e: e["total_weight"], reverse=True)
    for e in common:
        e["guru_count"] = len(e["gurus"])
    return common
