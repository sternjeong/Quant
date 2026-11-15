"""검증 연구 insider-form4-v1 (2026-11-15 사전 등록): 임원·이사의 장내 매수(SEC Form 4)를 따라 사면 SPY 를 이기나.

가격만 쓰는 신호 약 40개, 실적 놀람(earnings-surprise-v1)·애널리스트·13F 가 모두 SPY 를 확실히 이기지 못했다. 내부자 매매는
'가격 밖 정보' 가운데 **무료이고 공시 시각이 찍힌 과거 이력이 온전한** 드문 자료다(SEC Insider Transactions Data Sets, 2006~).

참고한 선행 연구·공개 도구(아이디어만 — 코드는 가져오지 않았다):
  - Cohen·Malloy·Pomorski(2012, JF) 'Decoding Inside Information': 같은 달에 해마다 사고파는 '일상형(routine)' 내부자의 매매는
    정보가 없고, 그렇지 않은 '기회형(opportunistic)' 내부자의 매매에 예측력이 있다. 분류는 직전 3개 달력연도 이력만 쓴다.
  - Alldredge·Blank(2019) 등 '여러 내부자가 함께 사는(cluster) 매수' — openinsider 의 cluster buys 화면이 같은 생각이다.
  - 10b5-1(미리 짜 둔 매매 계획) 매수는 정보가 없다 — 2023 년부터 SUBMISSION 의 AFF10B5ONE 으로 표시된다(그 전은 표시 없음).

자료(미리 보기 없음):
  - SEC 분기 ZIP(…/insider-transactions-data-sets/{YYYY}q{Q}_form345.zip)의 SUBMISSION·REPORTINGOWNER·NONDERIV_TRANS.
    시점 기준은 FILING_DATE — 신호는 공시일 '다음 거래일'부터 쓴다. 종목은 공시 당시 ISSUERTRADINGSYMBOL(옛 티커 그대로).
  - 내부자 = 보고자 관계에 Director 또는 Officer 가 있는 사람(10% 주주만인 펀드는 뺀다). 한 공시에 여럿이면 첫 임원·이사.
  - 자격 매수 = 비파생 거래 코드 P(장내 매수)·취득(A)·금액(주식 수 × 가격) ≥ 1만 달러·10b5-1 표시 없음.
  - 일상형/기회형(CMP): 매수 거래일이 Y 년 m 월일 때, 그 사람이 Y−1·Y−2·Y−3 해 모두 m 월에 거래(P 또는 S)했으면 일상형,
    세 해 모두 어떤 달이든 거래했지만 일상형이 아니면 기회형, 이력이 모자라면 미분류. 이력은 우리 종목들의 공시만 본다(한계 — REPORT 명시).
  - 가격·종목: earnings-surprise-v1 과 같다(core.market_data 조정 종가, fja05680 S&P 500 시점 기준 구성종목, 2009~).

검정(결과를 보기 전에 고정):
  매달 첫 거래일 r 에, 다음 거래일이 [r−60, r−1] 거래일 안에 드는 자격 매수로 종목 집합을 만든다(그날 S&P 500 편입·r 일 가격 있음).
    C_CLUSTER = 서로 다른 내부자 2명 이상이 산 종목 · O_OPP = 기회형 내부자 1명 이상이 산 종목 (판정 2개)
    A_ANY = 내부자 1명 이상이 산 종목 (보고만)
  형성은 2009-01 부터(기회형 분류에 2006~2008 이력이 필요 — 세 팔 모두 같은 날부터). 종목이 3개 미만인 달은 형성하지 않는다(적립 계좌는 그달 SPY). r 일 종가 매수, 1/3/6개월 단순 수익, 동일가중.
  INSIDER_ALIVE(팔마다) ⇔ ① 판정 구간(3개월 끝 ≤ 2024-09-30)을 가운데 날로 나눈 두 절반 모두 '집합 − 편입 종목 전체 동일가중'
    3개월 수익 평균 > 0 이고 이동 블록 부트스트랩(12개월, 2,000회) 단측 p < 0.025(판정 2개 → 0.05/2)
    ② 팔지 않는 적립: 매달 10만 원을 그달 집합에 똑같이 나눠 사고(0.15%, 끝에 양도세 22% × (이익 − 250만 원)) 5년 구간마다
       SPY 적립과 비교해 이긴 비율 ≥ 60% 이고 IRR 차이 중앙값 ≥ +0.5%p.
  그 밖은 FAIL(관측 IR 이 최소 검출 효과보다 작으면 FAIL_UNDERPOWERED), 판정 달 48 개·5년 구간 12 개 미만이면 NOT_EVALUABLE.
  보고만: A_ANY, 새틀라이트(SPY 85% + 집합 15%), 1·6개월, 2024-10 이후.
엔진은 바뀌지 않는다(사용자 확인 뒤 별도 작업).
"""

from __future__ import annotations

import csv
import importlib.util
import io
import math
import sys
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ES = _load("earnings_surprise_v1", HERE.parent / "earnings-surprise-v1" / "run.py")  # 종목·가격·검정 틀을 그대로 쓴다
L = ES.L
from core import research_power as rp  # noqa: E402

JOB_ID = "insider-form4-v1"
RULES_VERSION = "insider-form4-v1/2026-11-15"
ZIP_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{y}q{q}_form345.zip"
FIRST_QUARTER = (2006, 1)
MIN_BUY_USD = 10_000.0
LOOKBACK = 60
MIN_NAMES = 3
FORM_START = pd.Timestamp("2009-01-01")   # 기회형 분류에 직전 3년(2006~2008) 이력이 필요 — 모든 팔이 같은 날부터 형성
ROUTINE_YEARS = 3
ALPHA = 0.025                      # 판정 2개 → 0.05 / 2
JUDGED = ("C_CLUSTER", "O_OPP")
REPORTED = ("A_ANY",)
ARMS = (*JUDGED, *REPORTED)
ARM_NOTE = {"C_CLUSTER": "서로 다른 임원·이사 2명 이상이 최근 60거래일 안에 장내 매수",
            "O_OPP": "기회형(CMP) 임원·이사 1명 이상이 최근 60거래일 안에 장내 매수",
            "A_ANY": "임원·이사 1명 이상이 최근 60거래일 안에 장내 매수(보고만)"}

SUB_COLS = ("ACCESSION_NUMBER", "FILING_DATE", "ISSUERTRADINGSYMBOL")
OWN_COLS = ("ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP")
NDT_COLS = ("ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD")
ROW_COLS = ["ticker", "filed", "trans", "owner", "code", "usd", "plan"]


# =================================================================================================
# 1. SEC 분기 ZIP → 작은 거래 표
# =================================================================================================

def quarters(last: tuple[int, int]) -> list[tuple[int, int]]:
    y, q = FIRST_QUARTER
    out = []
    while (y, q) <= last:
        out.append((y, q))
        y, q = (y, q + 1) if q < 4 else (y + 1, 1)
    return out


def last_published_quarter(today: date) -> tuple[int, int]:
    """분기 자료는 분기가 끝난 뒤 올라온다 — 직전 분기까지만 받는다."""
    q = (today.month - 1) // 3 + 1
    return (today.year, q - 1) if q > 1 else (today.year - 1, 4)


def _parse_dates(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")
    rest = d.isna() & s.notna()
    if rest.any():
        d[rest] = pd.to_datetime(s[rest], errors="coerce")
    return d.dt.normalize()


def _table(zf: zipfile.ZipFile, name: str, cols: tuple[str, ...], optional: tuple[str, ...] = ()) -> pd.DataFrame:
    member = next((n for n in zf.namelist() if n.rsplit("/", 1)[-1].upper() == f"{name}.TSV"), None)
    if member is None:
        raise RuntimeError(f"{name}.tsv 가 ZIP 에 없음: {zf.namelist()[:10]}")
    with zf.open(member) as f:
        head = f.readline().decode("utf-8", "replace").rstrip("\r\n").split("\t")
    missing = [c for c in cols if c not in head]
    if missing:
        raise RuntimeError(f"{name}.tsv 에 열 {missing} 없음(있는 열: {head[:30]}) — SEC 자료 형식 확인 필요")
    use = [c for c in (*cols, *optional) if c in head]
    with zf.open(member) as f:
        return pd.read_csv(f, sep="\t", dtype=str, usecols=use, quoting=csv.QUOTE_NONE, on_bad_lines="skip",
                           encoding="utf-8", encoding_errors="replace")


def parse_quarter_zip(raw: bytes, universe: set[str], norm: Callable[[str], str]) -> pd.DataFrame:
    """분기 ZIP → 우리 종목·임원/이사·코드 P/S 거래만 담은 작은 표(ROW_COLS)."""
    zf = zipfile.ZipFile(io.BytesIO(raw))
    sub = _table(zf, "SUBMISSION", SUB_COLS, ("AFF10B5ONE",))
    sub["ticker"] = sub["ISSUERTRADINGSYMBOL"].fillna("").str.strip().str.upper().map(lambda t: norm(t) if t else "")
    sub = sub[sub["ticker"].isin(universe)]
    if sub.empty:
        return pd.DataFrame(columns=ROW_COLS)
    own = _table(zf, "REPORTINGOWNER", OWN_COLS)
    rel = own["RPTOWNER_RELATIONSHIP"].fillna("").str.lower()
    own = own[rel.str.contains("director") | rel.str.contains("officer")]
    own = own.drop_duplicates("ACCESSION_NUMBER", keep="first")
    ndt = _table(zf, "NONDERIV_TRANS", NDT_COLS)
    ndt = ndt[ndt["TRANS_CODE"].isin(["P", "S"])]
    df = ndt.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER")
    if df.empty:
        return pd.DataFrame(columns=ROW_COLS)
    shares = pd.to_numeric(df["TRANS_SHARES"], errors="coerce")
    price = pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce")
    plan = df["AFF10B5ONE"].fillna("").str.strip().str.lower().isin(["1", "true", "y", "yes"]) if "AFF10B5ONE" in df else False
    out = pd.DataFrame({"ticker": df["ticker"], "filed": _parse_dates(df["FILING_DATE"]), "trans": _parse_dates(df["TRANS_DATE"]),
                        "owner": pd.to_numeric(df["RPTOWNERCIK"], errors="coerce"), "code": df["TRANS_CODE"],
                        "usd": (shares * price).astype(float), "plan": plan, "ad": df["TRANS_ACQUIRED_DISP_CD"].fillna("")})
    out = out[out["filed"].notna() & out["trans"].notna() & out["owner"].notna()]
    out = out[(out["code"] == "S") | (out["ad"] == "A")]
    out["owner"] = out["owner"].astype("int64")
    return out[ROW_COLS].reset_index(drop=True)


def fetch_rows(R, client, universe: set[str], norm, last: tuple[int, int]) -> tuple[pd.DataFrame, dict]:
    from core.filing_changes import EdgarFetchError

    parts, stats = [], {"quarters": 0, "missing": [], "rows": 0}
    for y, q in quarters(last):
        def one(y=y, q=q):
            try:
                raw = client._get(ZIP_URL.format(y=y, q=q))
            except EdgarFetchError as exc:
                if getattr(exc, "status", None) == 404:
                    return None
                raise
            return parse_quarter_zip(raw, universe, norm)

        df = R.stage(f"sec_{y}q{q}", one)
        if df is None:
            stats["missing"].append(f"{y}q{q}")
            continue
        stats["quarters"] += 1
        parts.append(df)
    rows = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=ROW_COLS)
    stats["rows"] = int(len(rows))
    return rows, stats


# =================================================================================================
# 2. 자격 매수 + 일상형/기회형
# =================================================================================================

def classify(rows: pd.DataFrame) -> pd.DataFrame:
    """자격 매수 사건표: ticker, filed, owner, kind(routine/opportunistic/unclassified). CMP 규칙(직전 3개 달력연도)."""
    if rows.empty:
        return pd.DataFrame(columns=["ticker", "filed", "owner", "kind", "usd"])
    tr = rows.drop_duplicates(["owner", "ticker", "trans", "code", "usd"])
    years = tr.groupby("owner")["trans"].apply(lambda s: set(s.dt.year))
    ym = tr.groupby("owner")["trans"].apply(lambda s: set(zip(s.dt.year, s.dt.month)))
    buys = rows[(rows["code"] == "P") & (rows["usd"] >= MIN_BUY_USD) & (~rows["plan"].astype(bool))].copy()
    kinds = []
    for o, t in zip(buys["owner"].to_numpy(), buys["trans"]):
        y, m = t.year, t.month
        prior = [y - k for k in range(1, ROUTINE_YEARS + 1)]
        if all(p in years.get(o, ()) for p in prior):
            kinds.append("routine" if all((p, m) in ym.get(o, ()) for p in prior) else "opportunistic")
        else:
            kinds.append("unclassified")
    buys["kind"] = kinds
    return buys[["ticker", "filed", "owner", "kind", "usd"]].sort_values(["filed", "ticker"]).reset_index(drop=True)


class InsiderPanel(ES.Panel):
    """earnings-surprise-v1 의 Panel 에 형성 규칙만 바꿔 끼운다(가격·편입·앞으로 수익·적립 계산은 그대로)."""

    def __init__(self, events: pd.DataFrame, closes: pd.DataFrame, members_at, arm: str):
        super().__init__(events, closes, members_at)
        self.arm = arm
        self._owner = self.ev["owner"].to_numpy()
        self._kind = self.ev["kind"].to_numpy()
        self._tick = self.ev["ticker"].to_numpy()

    def form(self, r: int) -> dict:
        if r in self._cache:
            return self._cache[r]
        out = {"top": [], "bottom": [], "universe": [], "n_eligible": 0, "ok": False}
        if r >= 1 and self.days[r] >= FORM_START:
            mem = self.members_at(self.days[r - 1].date())
            uni = [self.col[t] for t in mem if t in self.col and t != "SPY" and np.isfinite(self.raw[r, self.col[t]])]
            lo, hi = np.searchsorted(self.ev_u, r - LOOKBACK, "left"), np.searchsorted(self.ev_u, r - 1, "right")
            buyers: dict[str, set] = {}
            opp: set[str] = set()
            for t, o, k in zip(self._tick[lo:hi], self._owner[lo:hi], self._kind[lo:hi]):
                buyers.setdefault(t, set()).add(int(o))
                if k == "opportunistic":
                    opp.add(t)
            if self.arm == "C_CLUSTER":
                pick = {t for t, s in buyers.items() if len(s) >= 2}
            elif self.arm == "O_OPP":
                pick = opp
            else:
                pick = set(buyers)
            uni_set = set(uni)
            sel = sorted(self.col[t] for t in pick if t in mem and self.col[t] in uni_set)
            out["universe"], out["n_eligible"] = uni, len(sel)
            if len(sel) >= MIN_NAMES:
                out["top"], out["ok"] = sel, True
        self._cache[r] = out
        return out


# =================================================================================================
# 3. 합성 자료(스모크 — 네트워크 없음, ZIP 파싱부터 모든 코드 경로)
# =================================================================================================

def _fake_zip(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        def put(name, cols, recs):
            lines = ["\t".join(cols)] + ["\t".join(str(r.get(c, "")) for c in cols) for r in recs]
            zf.writestr(f"{name}.tsv", "\n".join(lines) + "\n")
        put("SUBMISSION", [*SUB_COLS, "DOCUMENT_TYPE", "AFF10B5ONE"], rows)
        put("REPORTINGOWNER", [*OWN_COLS, "RPTOWNERNAME"], rows)
        put("NONDERIV_TRANS", [*NDT_COLS, "SECURITY_TITLE"], rows)
    return buf.getvalue()


class FakeClient:
    def __init__(self, zips: dict[str, bytes]):
        self.zips, self.calls = zips, 0

    def _get(self, url):
        from core.filing_changes import EdgarFetchError

        self.calls += 1
        key = url.rsplit("/", 1)[-1].split("_")[0]
        if key not in self.zips:
            raise EdgarFetchError("HTTP 404", status=404, kind="http")
        return self.zips[key]


def synthetic_inputs() -> dict:
    rng = np.random.default_rng(5)
    tickers = [f"T{i:02d}" for i in range(70)]
    days = pd.bdate_range("2006-01-02", "2021-12-31")
    by_q: dict[str, list] = {}
    n = 0
    # 일상형: 해마다 3월에 사는 사람 / 기회형: 해마다 거래는 하지만 달이 바뀌는 사람 / 펀드(10% 주주): 빠져야 한다
    for i, t in enumerate(tickers):
        for k in range(3):
            owner = 1000 + 10 * i + k
            routine = k == 0
            rel = "TenPercentOwner" if k == 2 and i % 5 == 0 else ("Director" if k else "Officer")
            for y in range(2006, 2022):
                m = 3 if routine else int(rng.integers(1, 13))
                d = pd.Timestamp(y, m, int(rng.integers(1, 26)))
                code = "P" if rng.random() < 0.6 else "S"
                n += 1
                filed = d + pd.Timedelta(days=2)
                by_q.setdefault(f"{filed.year}q{(filed.month - 1) // 3 + 1}", []).append({
                    "ACCESSION_NUMBER": f"A{n}", "FILING_DATE": filed.strftime("%d-%b-%Y").upper(),
                    "ISSUERTRADINGSYMBOL": t.lower() if n % 7 == 0 else t, "DOCUMENT_TYPE": "4",
                    "AFF10B5ONE": "1" if n % 23 == 0 else "", "RPTOWNERCIK": owner, "RPTOWNER_RELATIONSHIP": rel,
                    "RPTOWNERNAME": f"P{owner}", "TRANS_DATE": d.strftime("%d-%b-%Y").upper(), "TRANS_CODE": code,
                    "TRANS_SHARES": int(rng.integers(500, 20000)), "TRANS_PRICEPERSHARE": round(float(rng.uniform(10, 200)), 2),
                    "TRANS_ACQUIRED_DISP_CD": "A" if code == "P" else "D", "SECURITY_TITLE": "Common"})
    zips = {k: _fake_zip(v) for k, v in by_q.items() if k != "2010q2"}   # 한 분기 404 흉내

    def members_at(d: date) -> frozenset:
        base = set(tickers[:60])
        if d >= date(2014, 1, 1):
            base |= set(tickers[60:])
        if d >= date(2018, 6, 1):
            base -= {"T05"}
        return frozenset(base)

    return {"client": FakeClient(zips), "tickers": tickers, "days": days, "members_at": members_at, "last": (2021, 4)}


def synthetic_closes(days: pd.DatetimeIndex, tickers: list[str], events: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    mkt = rng.normal(0.0003, 0.01, len(days))
    cols = {"SPY": 100 * np.cumprod(1 + mkt)}
    for t in tickers:
        r = mkt * (0.8 + 0.4 * rng.random()) + rng.normal(0.0001, 0.015, len(days))
        for f in events.loc[(events["ticker"] == t) & (events["kind"] == "opportunistic"), "filed"]:
            u = days.searchsorted(pd.Timestamp(f), side="right")
            r[u:u + 60] += 0.0003
        p = 50 * np.cumprod(1 + r)
        if t == "T07":
            p[days >= pd.Timestamp("2016-03-01")] = np.nan
        cols[t] = p
    return pd.DataFrame(cols, index=days)


# =================================================================================================
# 4. 본문
# =================================================================================================

def judge_arm(R, events, closes, members_at, arm: str, power: dict) -> dict:
    P = InsiderPanel(events, closes, members_at, arm)
    tab = ES.monthly_table(P)
    if tab.empty:
        return {"verdict": "NOT_EVALUABLE", "reason": "형성 가능한 달 없음", "months_formed": 0}
    ev = ES.event_test(tab, R.smoke)
    for h in ev.get("halves") or []:                  # 판정 2개 → 유의 수준 0.025 로 다시 판정
        h["pass"] = bool(np.isfinite(h["mean_top_minus_univ"]) and h["mean_top_minus_univ"] > 0
                         and np.isfinite(h["p_one_sided"]) and h["p_one_sided"] < ALPHA)
    acc = ES.account_test(P, tab.index[0], R.smoke)
    halves = ev.get("halves") or []
    evaluable = (ev["n_months_judge"] >= ES.MIN_JUDGE_MONTHS and len(halves) == 2 and all(h["n"] >= 2 * ES.BLOCK_M for h in halves)
                 and acc["n_windows"]["judge"] >= ES.MIN_WINDOWS and ev.get("noop") is None)
    event_pass = bool(halves) and all(h["pass"] for h in halves)
    acc_pass = bool(acc.get("judge_TOP", {}).get("pass"))
    if not evaluable:
        verdict = "NOT_EVALUABLE"
    elif event_pass and acc_pass:
        verdict = "INSIDER_ALIVE"
    else:
        verdict = rp.classify_fail(ev.get("observed_ir"), power)
    return {"verdict": verdict, "event_pass": event_pass, "account_pass": acc_pass, "months_formed": int(len(tab)),
            "first_formation": str(tab.index[0].date()), "mean_names": float(tab["n_top"].mean()),
            "event_test": ev, "account": acc}


def body(R):
    norm = (lambda t: t.replace(".", "-")) if R.smoke else None
    if R.smoke:
        inp = synthetic_inputs()
        members_at, tickers, client, last = inp["members_at"], inp["tickers"], inp["client"], inp["last"]
        source = "synthetic (smoke)"
    else:
        from core import hypothesis_engine as he
        from core.filing_changes import EdgarClient

        norm = he.price_symbol
        members_at, tickers = ES.sp500_members()
        client = EdgarClient(record_first_seen=False, timeout=300.0)
        last = last_published_quarter(date.today())
        source = ("SEC Insider Transactions Data Sets (Form 3/4/5, FILING_DATE) + core.market_data adjusted close + "
                  "fja05680 S&P 500 PIT membership")
    universe = set(tickers)
    rows, sec_stats = fetch_rows(R, client, universe, norm, last)
    R.log(f"SEC 내부자 거래 {sec_stats}")
    events = R.stage("events", lambda: classify(rows))
    kinds = events["kind"].value_counts().to_dict() if len(events) else {}
    R.log(f"자격 매수 {len(events)}건 {kinds}")
    if R.smoke:
        assert sec_stats["missing"] == ["2010q2"], sec_stats["missing"]
        assert kinds.get("routine", 0) > 0 and kinds.get("opportunistic", 0) > 0, kinds
        closes = R.stage("closes", lambda: synthetic_closes(inp["days"], tickers, events))
    else:
        closes = ES.load_prices_real(R, [t for t in tickers if t != "SPY"])
    if events.empty:
        raise RuntimeError("자격 매수 사건이 없음")
    first = max(pd.Timestamp(events["filed"].min()), FORM_START)
    judge_years = max((ES.JUDGE_END - first).days / 365.25, 0.0)
    power = rp.power_report(judge_years, len(JUDGED))
    arms = {arm: R.stage(f"arm_{arm}", lambda arm=arm: judge_arm(R, events, closes, members_at, arm, power)) for arm in ARMS}
    verdicts = {arm: arms[arm]["verdict"] for arm in JUDGED}
    verdicts.update({f"{arm}_report": arms[arm]["verdict"] for arm in REPORTED})
    for arm in ARMS:
        verdicts[f"{arm}_satellite_85_15_report"] = "PASS(보고)" if arms[arm].get("account", {}).get("judge_SAT", {}).get("pass") else "FAIL(보고)"
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    result = L.rnd({
        "id": JOB_ID, "judge_version": RULES_VERSION, "smoke": R.smoke, "source": source, "verdicts": verdicts,
        "power": power, "power_line": rp.power_line(power),
        "coverage": {"tickers_universe": len(tickers), "sec": sec_stats, "qualifying_buys": int(len(events)), "kinds": kinds,
                     "event_first": str(events["filed"].min().date()), "event_last": str(events["filed"].max().date()),
                     "tickers_with_buys": int(events["ticker"].nunique()),
                     "tickers_with_price": int(closes.notna().any().sum()) - 1},
        "arms": arms,
        "rule": {"lookback_trading_days": LOOKBACK, "min_names": MIN_NAMES, "min_buy_usd": MIN_BUY_USD, "routine_years": ROUTINE_YEARS,
                 "horizons": ES.HORIZONS, "main_horizon": ES.MAIN_H, "judge_end": str(ES.JUDGE_END.date()), "boot": ES.BOOT,
                 "block_months": ES.BLOCK_M, "alpha": ALPHA, "win_years": ES.WIN_YEARS, "win_share_min": ES.WIN_SHARE_MIN,
                 "median_irr_min": ES.MED_IRR_MIN, "monthly_krw": ES.MONTHLY_KRW}})
    return result, render(result)


def render(r: dict) -> str:
    v, P = r["verdicts"], L.pct
    cov = r["coverage"]
    out = [f"# 내부자 장내 매수(SEC Form 4)를 따라 사면 SPY 를 이기나 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "**판정:** " + " · ".join(f"{a} **{v[a]}**" for a in JUDGED) + f" · (보고) A_ANY {v['A_ANY_report']}", "",
           "통과는 '전진 원장 후보'일 뿐 엔진 채택이 아니다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", ""]
    out += [f"- {a}: {ARM_NOTE[a]}" for a in ARMS]
    out += ["- 내부자 = 임원·이사(10% 주주만인 펀드 제외). 자격 매수 = 장내 매수(P)·취득·1만 달러 이상·10b5-1 표시 없음. 신호는 공시일 다음 거래일부터.",
            "- 기회형/일상형(Cohen·Malloy·Pomorski 2012): 직전 3개 달력연도 모두 같은 달에 거래했으면 일상형, 세 해 모두 거래했지만 아니면 기회형.",
            f"- INSIDER_ALIVE ⇔ 두 절반 모두 '집합 − 편입 종목 동일가중' 3개월 평균 > 0 & 부트스트랩 단측 p < {r['rule']['alpha']} "
            f"& 적립 5년 구간 이긴 비율 ≥ {r['rule']['win_share_min']:.0%} & IRR 차이 중앙값 ≥ +{r['rule']['median_irr_min'] * 100:.1f}%p.",
            f"- 종목 {r['rule']['min_names']}개 미만인 달은 형성하지 않는다(적립은 SPY). 판정 구간 끝 {r['rule']['judge_end']}, 이후는 보고만.",
            f"- 검정력: {r['power_line']}", "",
            "## 자료", "",
            f"- {r['source']}",
            f"- 분기 {cov['sec']['quarters']}개(없음: {', '.join(cov['sec']['missing']) or '없음'}), 우리 종목 거래 {cov['sec']['rows']:,}건 → 자격 매수 "
            f"{cov['qualifying_buys']:,}건 {cov['kinds']} · 매수 있는 종목 {cov['tickers_with_buys']}개 · 가격 있는 종목 {cov['tickers_with_price']}개",
            f"- 사건 {cov['event_first']} ~ {cov['event_last']}", ""]
    for a in ARMS:
        x = r["arms"][a]
        out += [f"## {a}{' (보고만)' if a in REPORTED else ''} — {x['verdict']}", ""]
        if not x.get("months_formed"):
            out += [f"형성 가능한 달 없음({x.get('reason', '')})", ""]
            continue
        ev, acc = x["event_test"], x["account"]
        out.append(f"형성한 달 {x['months_formed']}개(첫 달 {x['first_formation']}), 달마다 평균 {x['mean_names']:.1f}종목, 판정 달 {ev['n_months_judge']}개 · 관측 IR {ev.get('observed_ir')}")
        out += ["", "| 절반 | 기간 | 달 | 3개월 '집합 − 편입 전체' 평균 | 단측 p | 통과 |", "|---|---|---|---|---|---|"]
        for h in ev.get("halves") or []:
            out.append(f"| {h['half']} | {h['first']} ~ {h['last']} | {h['n']} | {P(h['mean_top_minus_univ'], True, 2)} | {h['p_one_sided']} | {'예' if h['pass'] else '아니오'} |")
        bh = ev.get("by_horizon", {})
        out += ["", "| 구간 | 집합 평균 | 편입 전체 | SPY | 집합 − 편입 전체 | 집합 − SPY | 이긴 달 비율 |", "|---|---|---|---|---|---|---|"]
        for k, d in bh.items():
            out.append(f"| {k} | {P(d['mean_top'], nd=2)} | {P(d['mean_univ'], nd=2)} | {P(d['mean_spy'], nd=2)} | {P(d['mean_top_minus_univ'], True, 2)} | "
                       f"{P(d['mean_top_minus_spy'], True, 2)} | {P(d['hit_top_vs_univ'], nd=0)} |")
        out += ["", "| 적립(매달 10만 원, 5년) | 구간 | 이긴 비율 | IRR 차이 중앙 | 통과 |", "|---|---|---|---|---|"]
        for k in ("judge_TOP", "judge_SAT", "post2024_10_report_TOP", "post2024_10_report_SAT"):
            s = acc.get(k) or {}
            if s.get("n_windows"):
                out.append(f"| {k} | {s['n_windows']} | {P(s['share_win'], nd=0)} | {P(s['median_diff_irr'], True, 2)}p | {'예' if s.get('pass') else '아니오'} |")
        out.append("")
    out += ["## 주의", "",
            "- 종목 가격은 Yahoo 캐시라 상장폐지 종목은 대개 가격이 없다(생존 편향 — 매수 신호가 있던 망한 회사가 빠진다). 결과는 낙관 쪽으로 기운다.",
            "- 일상형/기회형 분류는 우리 종목(2009 년 이후 S&P 500)의 공시만 본다 — 다른 회사에서의 거래 이력은 빠진다.",
            "- 10b5-1 표시는 2023 년부터만 있다. 그 전의 계획 매수는 섞여 있다.",
            "- S&P 500 대형주는 내부자 매수가 드물고 정보가 적다는 것이 선행 연구의 일반적 결과다(효과는 소형주에서 크다). 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
