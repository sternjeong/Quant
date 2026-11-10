"""검증 연구 earnings-surprise-v1 (2026-11-10 사전 등록): 실적 발표 뒤 표류(PEAD) — 무료 시점 기준 SEC 실적으로 SPY 를 이기나.

가격만 쓰는 신호 약 40개가 SPY(세후)를 확실히 이기지 못해, 새 정보(실적)로 넘어간다. 애널리스트 추정치 이력은 무료로 구할 수 없어
'놀람'을 계절 랜덤워크 기대치로 잰다(SUE).

자료(미리 보기 없음):
  - SEC EDGAR XBRL companyfacts: 분기 희석 EPS(us-gaap EarningsPerShareDiluted, 그 기간에 희석 값이 없으면 Basic), 단위 USD/shares,
    10-Q/10-K(정정 포함). 각 숫자의 `filed`(공시일)가 시점 기준 — 신호는 공시일 '다음 거래일'부터 쓸 수 있다.
  - 4분기: 10-K 연간 EPS − 같은 회계연도 안의 분기 3개(10-K 공시일까지 알려진 값). 3개가 다 없으면 그 4분기는 건너뛴다.
    분기 3개의 공시 뒤 액면분할이 끼면 값이 섞이므로, 같은 10-K 가 전년 연간 EPS 를 처음 값과 10% 넘게 다르게 재작성했거나
    |4분기| > 1.5 × max(|연간|, |분기|) 이면 버린다(분할 오염 방지). 회사가 3개월
    4분기 값을 직접 적었으면 그것을 쓴다.
  - 분기 E 의 사건일 = E 기간 값이 처음 공시된 날 F(F − E ≤ 100일인 것만 — 첫 XBRL 공시의 과거 비교 숫자는 사건이 아님).
    F 시점의 다른 분기 값 = F 까지 공시된 것 중 가장 늦게 공시된 값(정정·분할 재작성 반영).
  - SUE = (EPS_E − EPS_{E−4분기}) / (직전 8개 계절 차이 EPS_{E−j} − EPS_{E−j−4}, j=1..8 의 표본 표준편차), 차이 6개 이상 필요.
  - 가격: core.market_data 캐시(배당 포함 조정 종가). 종목: fja05680 S&P 500 시점 기준 구성종목(그날 편입된 종목만 후보).
    티커 → CIK 는 SEC 의 '현재' 목록이라 상장폐지·이름 바뀐 회사는 대개 실적·가격이 없다(생존 편향 — REPORT 에 명시).

검정(결과를 보기 전에 고정):
  매달 첫 거래일 r 에, 다음 거래일 u 가 [r−60, r−1] 거래일 안에 드는 사건(종목별 가장 최근)으로 SUE 상위 10%·하위 10% 를 만든다
  (그날 S&P 500 편입·r 일 가격 있음, 후보 50종목 이상인 달만). r 일 종가 매수, 1/3/6개월(21/63/126 거래일) 뒤 종가까지 단순 수익.
  비교: 같은 날 편입 종목 전체 동일가중(유니버스), SPY.
  판정 구간: 3개월 수익의 끝이 2024-09-30 이하인 달(2024-10 이후는 20개 넘는 연구가 이미 봤으므로 보고만 — RESEARCH_JOBS 판정 설계 규칙 3).
  PEAD_ALIVE ⇔ ① 판정 구간을 첫·끝 형성일의 가운데 날로 나눈 두 절반 모두에서 '상위 10% − 유니버스' 3개월 수익 평균 > 0 이고
               이동 블록 부트스트랩(12개월 블록, 2,000회) 단측 p < 0.05
             ② 팔지 않는 적립: 매달 첫 거래일 10만 원을 그달 상위 10% 종목에 똑같이 나눠 사고(수수료 0.1% + 환전 0.05%, 환율 1,300 고정,
               끝에 모두 판다고 보고 양도세 22% × (이익 − 250만 원)) 5년 구간(매달 시작, 끝 ≤ 2024-09-30)마다 SPY 적립과 비교해
               이긴(청산 세후 최종액이 큰) 구간 비율 ≥ 60% 이고 IRR 차이 중앙값 ≥ +0.5%p.
  그 밖은 FAIL(관측 IR 이 최소 검출 효과보다 작으면 FAIL_UNDERPOWERED), 자료 부족이면 NOT_EVALUABLE.
  보고만: 새틀라이트 변형(SPY 85% + 상위 10% 15%), 하위 10%, 1·6개월, 2024-10 이후.
엔진은 바뀌지 않는다(사용자 확인 뒤 별도 작업).
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from bisect import bisect_right
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dca-dip-deploy-v1"))
sys.path.insert(0, str(HERE.parents[2]))
import lab as L  # noqa: E402

from core import research_power as rp  # noqa: E402
from core import rolling_eval as re_  # noqa: E402

JOB_ID = "earnings-surprise-v1"
RULES_VERSION = "earnings-surprise-v1/2026-11-10"
PROJECT_ROOT = HERE.parents[2]
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "earnings_surprise" / "eps"
CACHE_DAYS = 60
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
CONCEPTS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")
UNIT = "USD/shares"
FORMS = ("10-Q", "10-K")
QUARTER_DAYS = (80, 100)
YEAR_DAYS = (330, 380)
MAX_FILE_LAG_DAYS = 100
MATCH_TOL_DAYS = 15
N_DIFFS, MIN_DIFFS = 8, 6
Q4_GUARD = 1.5

UNIVERSE_START = "2009-01-01"
PRICE_START = "2008-01-01"
LOOKBACK = 60
HORIZONS = {"1m": 21, "3m": 63, "6m": 126}
MAIN_H = "3m"
DECILE = 0.10
MIN_NAMES = 50
JUDGE_END = pd.Timestamp("2024-09-30")
BOOT = 2000
BLOCK_M = 12
ALPHA = 0.05
MONTHLY_KRW = 100_000.0
WIN_YEARS = 5
WIN_SHARE_MIN = 0.60
MED_IRR_MIN = 0.005
SAT_W = 0.15
FEE = L.FEE + L.FX_SPREAD
MIN_JUDGE_MONTHS = 48
MIN_WINDOWS = 12
SEED = 20261110
PRICE_CHUNK = 50


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


# =================================================================================================
# 1. SEC companyfacts → 분기 EPS (시점 기준)
# =================================================================================================

def compact_eps(raw: dict) -> dict[str, list]:
    """companyfacts JSON → {"diluted": [[start, end, val, filed, form]...], "basic": [...]} (USD/shares, 10-Q/10-K 계열)."""
    gaap = (raw.get("facts") or {}).get("us-gaap") or {}
    out = {}
    for key, concept in zip(("diluted", "basic"), CONCEPTS):
        rows, seen = [], set()
        for f in ((gaap.get(concept) or {}).get("units") or {}).get(UNIT) or []:
            form = str(f.get("form", ""))
            if not form.startswith(FORMS) or not f.get("start") or not f.get("end") or not f.get("filed"):
                continue
            try:
                val = float(f["val"])
            except (KeyError, TypeError, ValueError):
                continue
            k = (f["start"], f["end"], f["filed"])
            if k in seen or not math.isfinite(val):
                continue
            seen.add(k)
            rows.append([f["start"], f["end"], val, f["filed"], form])
        out[key] = sorted(rows, key=lambda r: (r[1], r[3]))
    return out


def merged_rows(rec: dict) -> list:
    """희석 값을 쓰고, 희석 값이 하나도 없는 기간(start, end)만 Basic 으로 채운다."""
    dil = rec.get("diluted") or []
    have = {(r[0], r[1]) for r in dil}
    return list(dil) + [r for r in (rec.get("basic") or []) if (r[0], r[1]) not in have]


def _restated_prior_year(annuals: list, e_a: date, f_a: date) -> bool:
    """같은 10-K 가 전년 연간 EPS 를 처음 공시 값과 10% 넘게 다르게 다시 적었으면(액면분할·주식배당 재작성) True.
    그해 1~3분기 값은 재작성 전 기준일 수 있어 4분기를 빼서 만들지 않는다."""
    prior = [a for a in annuals if abs((a[1] - (e_a - timedelta(days=365))).days) <= 10]
    same = [a[2] for a in prior if a[3] == f_a]
    earlier = sorted((a for a in prior if a[3] < f_a), key=lambda a: a[3])
    if not same or not earlier:
        return False
    orig = earlier[0][2]
    return abs(orig) > 1e-9 and abs(same[0] / orig - 1.0) > 0.10


def quarter_rows(rec: dict) -> tuple[list, dict]:
    """[(end, val, filed, form)] 분기 값(직접 + 10-K 에서 유도한 4분기), 진단 수."""
    rows = merged_rows(rec)
    quarters, annuals = [], []
    for start, end, val, filed, form in rows:
        s, e, f = _d(start), _d(end), _d(filed)
        days = (e - s).days
        if QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
            quarters.append((e, val, f, form, s))
        elif YEAR_DAYS[0] <= days <= YEAR_DAYS[1]:
            annuals.append((s, e, val, f, form))
    out = [(e, v, f, form) for e, v, f, form, _ in quarters]
    diag = {"q4_derived": 0, "q4_direct": 0, "q4_missing_quarters": 0, "q4_split_guard": 0}
    for s_a, e_a, v_a, f_a, form in annuals:
        if f_a < e_a:
            continue
        direct = [q for q in quarters if abs((q[0] - e_a).days) <= 7 and q[2] <= f_a]
        if direct:
            diag["q4_direct"] += 1
            continue
        inside: dict[date, tuple] = {}
        for e, v, f, _, s in quarters:
            if f <= f_a and s >= s_a - timedelta(days=7) and e <= e_a - timedelta(days=45):
                if e not in inside or inside[e][1] <= f:
                    inside[e] = (v, f)
        if len(inside) != 3:
            diag["q4_missing_quarters"] += 1
            continue
        qv = [v for v, _ in inside.values()]
        q4 = v_a - sum(qv)
        if _restated_prior_year(annuals, e_a, f_a) or abs(q4) > Q4_GUARD * max(abs(v_a), max(abs(x) for x in qv)):
            diag["q4_split_guard"] += 1
            continue
        diag["q4_derived"] += 1
        out.append((e_a, q4, f_a, form + "-Q4"))
    return sorted(out, key=lambda r: (r[0], r[2])), diag


class _Book:
    """분기 값 조회: 기간 끝(±MATCH_TOL_DAYS) 과 기준일까지 공시된 것 중 가장 늦은 값."""

    def __init__(self, rows: list):
        by: dict[date, list] = {}
        for e, v, f, _ in rows:
            by.setdefault(e, []).append((f, v))
        self.ends = sorted(by)
        self.ord = [e.toordinal() for e in self.ends]
        self.by = {e: sorted(x, key=lambda t: t[0]) for e, x in by.items()}

    def known(self, target: date, asof: date) -> Optional[float]:
        t = target.toordinal()
        lo, hi = bisect_right(self.ord, t - MATCH_TOL_DAYS - 1), bisect_right(self.ord, t + MATCH_TOL_DAYS)
        best = None
        for e in self.ends[lo:hi]:
            for f, v in self.by[e]:
                if f > asof:
                    break
                if best is None or f >= best[0]:
                    best = (f, v)
        return None if best is None else best[1]


@lru_cache(maxsize=None)
def _minus_q(e: date, k: int) -> date:
    return (pd.Timestamp(e) - pd.DateOffset(months=3 * k)).date()


def sue_events(ticker: str, rec: dict) -> tuple[list[dict], dict]:
    """한 회사 → [{ticker, end, filed, sue, eps, eps_lag4}]. 시점 기준: 모든 값은 사건일 F 까지 공시된 것."""
    rows, diag = quarter_rows(rec)
    book = _Book(rows)
    first: dict[date, date] = {}
    for e, _, f, _ in rows:
        if e not in first or f < first[e]:
            first[e] = f
    events = []
    diag.update({"periods": len(first), "late_first_filing": 0, "short_history": 0, "zero_std": 0})
    for e, f in sorted(first.items()):
        lag = (f - e).days
        if lag < 0 or lag > MAX_FILE_LAG_DAYS:
            diag["late_first_filing"] += 1
            continue
        v = {k: book.known(_minus_q(e, k), f) for k in range(0, N_DIFFS + 5)}
        if v[0] is None or v[4] is None:
            diag["short_history"] += 1
            continue
        diffs = [v[j] - v[j + 4] for j in range(1, N_DIFFS + 1) if v[j] is not None and v[j + 4] is not None]
        if len(diffs) < MIN_DIFFS:
            diag["short_history"] += 1
            continue
        sd = float(np.std(diffs, ddof=1))
        if not math.isfinite(sd) or sd <= 1e-9:
            diag["zero_std"] += 1
            continue
        events.append({"ticker": ticker, "end": e.isoformat(), "filed": f.isoformat(),
                       "sue": (v[0] - v[4]) / sd, "eps": v[0], "eps_lag4": v[4]})
    return events, diag


# =================================================================================================
# 2. 받기(재개 가능) — SEC · 가격
# =================================================================================================

def _atomic_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".e.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def fetch_eps(R, tickers: list[str], client, cache_dir: Path, now: Callable[[], datetime]) -> dict[str, dict]:
    """티커별 작은 EPS 기록(캐시 재사용, CACHE_DAYS 지나면 다시 받음). 시간이 다 되면 Stop(받은 것은 캐시에 남음).
    SEC 가 403 으로 막으면 전체를 멈춘다(모든 종목을 '없음'으로 만들지 않게)."""
    from core.filing_changes import EdgarBlocked, EdgarFetchError

    out, stats = {}, {"cached": 0, "fetched": 0, "missing": 0, "transient": 0}
    for i, t in enumerate(tickers):
        path = cache_dir / f"{t.upper().replace('/', '-')}.json"
        rec = None
        if path.exists():
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
                if now() - datetime.fromisoformat(rec["fetched_at"]) > timedelta(days=CACHE_DAYS):
                    rec = None
            except (OSError, ValueError, KeyError):
                rec = None
        if rec is not None:
            stats["cached"] += 1
        else:
            R.check_time()
            stamp = now().isoformat(timespec="seconds")
            try:
                cik = client.resolve_cik(t)
                raw = json.loads(client._get(COMPANYFACTS_URL.format(cik=cik)))
                rec = {"ticker": t, "cik": cik, "fetched_at": stamp, **compact_eps(raw)}
                del raw
                stats["fetched"] += 1
            except EdgarBlocked:
                raise
            except EdgarFetchError as exc:
                if getattr(exc, "kind", "") in ("ticker_not_found",) or getattr(exc, "status", None) == 404:
                    rec = {"ticker": t, "fetched_at": stamp, "missing": getattr(exc, "kind", "") or "http_404"}
                else:
                    stats["transient"] += 1
                    out[t] = {"ticker": t, "missing": "transient"}
                    continue
            except ValueError:
                rec = {"ticker": t, "fetched_at": stamp, "missing": "bad_json"}
            _atomic_json(path, rec)
        if rec.get("missing"):
            stats["missing"] += 1
        out[t] = rec
        if i % 100 == 0:
            R.log(f"SEC 실적 {i}/{len(tickers)} {stats}")
    R.log(f"SEC 실적 끝 {stats}")
    return {"records": out, "stats": stats}


def load_prices_real(R, tickers: list[str]) -> pd.DataFrame:
    """SPY 달력 × 종목 조정 종가(결측 NaN). 조각마다 단계 저장."""
    from core.candidate_ledger import default_price_provider as provider

    end = (date.today() + timedelta(days=1)).isoformat()

    def one(t):
        try:
            df = provider(t, PRICE_START, end)
        except Exception:  # noqa: BLE001
            return None
        if df is None or df.empty or "Close" not in df:
            return None
        col = df["Adj Close"] if "Adj Close" in df.columns and df["Adj Close"].notna().any() else df["Close"]
        s = pd.to_numeric(col, errors="coerce").astype("float32")
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
        return s[~s.index.duplicated(keep="last")].sort_index()

    spy = R.stage("price_spy", lambda: one("SPY"))
    if spy is None or spy.empty:
        raise RuntimeError("SPY 가격(거래일 달력)을 읽지 못함")
    days = spy.index
    cols = {"SPY": spy}
    for k in range(0, len(tickers), PRICE_CHUNK):
        part = tickers[k:k + PRICE_CHUNK]

        def chunk(part=part):
            got = {}
            for t in part:
                s = one(t)
                if s is not None and s.notna().sum() > 20:
                    got[t] = s.reindex(days)
            return got

        cols.update(R.stage(f"prices_{k // PRICE_CHUNK:03d}", chunk))
    return pd.DataFrame(cols, index=days)


def sp500_members() -> tuple[Callable[[date], frozenset], list[str]]:
    from core import hypothesis_engine as he

    dates, members = he._sp500_rows()
    lo = max(bisect_right(dates, _d(UNIVERSE_START)) - 1, 0)
    everyone = sorted(set().union(*members[lo:]))

    def at(d: date) -> frozenset:
        i = bisect_right(dates, d) - 1
        return members[i] if i >= 0 else frozenset()

    return at, everyone


# =================================================================================================
# 3. 매달 상위·하위 10% 와 앞으로 수익
# =================================================================================================

class Panel:
    """사건 표 + 가격 행렬 + 시점 기준 편입. form(r) = 그달 형성 결과(캐시)."""

    def __init__(self, events: pd.DataFrame, closes: pd.DataFrame, members_at: Callable[[date], frozenset]):
        self.days = closes.index
        self.cols = list(closes.columns)
        self.col = {t: i for i, t in enumerate(self.cols)}
        raw = closes.to_numpy(dtype=float)
        started = np.isfinite(raw)
        self.raw = raw
        # 상장폐지 등으로 가격이 끝나면 마지막 값을 유지(보유 가치 동결) — 계좌 계산용
        self.px = pd.DataFrame(raw, index=self.days).ffill().to_numpy()
        self.px[~np.maximum.accumulate(started, axis=0)] = np.nan
        ev = events[events["ticker"].isin(self.col)].copy()
        ev["u"] = self.days.searchsorted(pd.to_datetime(ev["filed"]).to_numpy(), side="right")
        self.ev = ev.sort_values(["u", "filed"]).reset_index(drop=True)
        self.ev_u = self.ev["u"].to_numpy()
        self.members_at = members_at
        self._cache: dict[int, dict] = {}

    def form(self, r: int) -> dict:
        if r in self._cache:
            return self._cache[r]
        out = {"top": [], "bottom": [], "universe": [], "n_eligible": 0, "ok": False}
        if r >= 1:
            mem = self.members_at(self.days[r - 1].date())
            uni = [self.col[t] for t in mem if t in self.col and t != "SPY" and np.isfinite(self.raw[r, self.col[t]])]
            lo, hi = np.searchsorted(self.ev_u, r - LOOKBACK, "left"), np.searchsorted(self.ev_u, r - 1, "right")
            latest: dict[str, float] = {}
            for t, s in zip(self.ev["ticker"].to_numpy()[lo:hi], self.ev["sue"].to_numpy()[lo:hi]):
                latest[t] = float(s)          # 정렬 순서상 뒤가 더 최근
            uni_set = set(uni)
            elig = [(s, self.col[t]) for t, s in latest.items() if t in mem and self.col[t] in uni_set]
            out["universe"], out["n_eligible"] = uni, len(elig)
            if len(elig) >= MIN_NAMES:
                elig.sort(key=lambda x: (x[0], x[1]))
                k = max(1, int(math.ceil(len(elig) * DECILE)))
                out["bottom"] = [c for _, c in elig[:k]]
                out["top"] = [c for _, c in elig[-k:]]
                out["ok"] = True
        self._cache[r] = out
        return out

    def fwd(self, cols: list[int], r: int, h: int) -> float:
        e = r + h
        if e >= len(self.days) or not cols:
            return float("nan")
        a, b = self.px[r, cols], self.px[e, cols]
        ok = np.isfinite(a) & np.isfinite(b) & (a > 0)
        return float(np.mean(b[ok] / a[ok] - 1.0)) if ok.any() else float("nan")


def month_rows(days: pd.DatetimeIndex) -> np.ndarray:
    return np.flatnonzero(L.lab.month_first_mask(days))


def monthly_table(P: Panel) -> pd.DataFrame:
    spy = P.col["SPY"]
    recs = []
    for r in month_rows(P.days):
        f = P.form(int(r))
        if not f["ok"]:
            continue
        rec = {"date": P.days[r], "row": int(r), "n_eligible": f["n_eligible"], "n_top": len(f["top"]), "n_universe": len(f["universe"])}
        for name, h in HORIZONS.items():
            rec[f"top_{name}"] = P.fwd(f["top"], int(r), h)
            rec[f"bottom_{name}"] = P.fwd(f["bottom"], int(r), h)
            rec[f"univ_{name}"] = P.fwd(f["universe"], int(r), h)
            rec[f"spy_{name}"] = P.fwd([spy], int(r), h)
            e = int(r) + h
            rec[f"end_{name}"] = P.days[e] if e < len(P.days) else pd.NaT
        recs.append(rec)
    if not recs:
        return pd.DataFrame()
    return pd.DataFrame(recs).set_index("date")


def mb_pvalue(x: np.ndarray, block: int, n_boot: int, rng) -> tuple[float, float]:
    """평균 > 0 단측 p: 중심화한 표본의 이동 블록 부트스트랩 평균이 관측 평균 이상인 비율(edge-decay-v1 과 같은 방식)."""
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2 * block:
        return (float(x.mean()) if n else float("nan")), float("nan")
    obs = float(x.mean())
    xc = x - obs
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, (n_boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]
    return obs, float(np.mean(xc[idx].mean(axis=1) >= obs))


def event_test(tab: pd.DataFrame, smoke: bool) -> dict:
    rng = np.random.default_rng(SEED)
    boot = 200 if smoke else BOOT
    judge = tab[tab[f"end_{MAIN_H}"].notna() & (tab[f"end_{MAIN_H}"] <= JUDGE_END)]
    post = tab[tab.index > JUDGE_END]
    out: dict[str, Any] = {"n_months_judge": int(len(judge)), "n_months_post_report": int(len(post))}
    if len(judge) < 2:
        out["halves"] = []
        return out
    mid = judge.index[0] + (judge.index[-1] - judge.index[0]) / 2
    out["split_date"] = str(mid.date())
    out["judge_first"], out["judge_last"] = str(judge.index[0].date()), str(judge.index[-1].date())
    halves = []
    for name, part in (("H1", judge[judge.index < mid]), ("H2", judge[judge.index >= mid])):
        x = (part[f"top_{MAIN_H}"] - part[f"univ_{MAIN_H}"]).to_numpy(dtype=float)
        m, p = mb_pvalue(x, BLOCK_M, boot, rng)
        halves.append({"half": name, "first": str(part.index[0].date()) if len(part) else None,
                       "last": str(part.index[-1].date()) if len(part) else None, "n": int(np.isfinite(x).sum()),
                       "mean_top_minus_univ": m, "p_one_sided": p,
                       "pass": bool(np.isfinite(m) and m > 0 and np.isfinite(p) and p < ALPHA)})
    out["halves"] = halves
    stats = {}
    for name in HORIZONS:
        for part_name, part in (("judge", judge), ("post2024_10_report", post)):
            if not len(part):
                continue
            d = {}
            for leg in ("top", "bottom", "univ", "spy"):
                d[f"mean_{leg}"] = float(np.nanmean(part[f"{leg}_{name}"]))
            d["mean_top_minus_univ"] = float(np.nanmean(part[f"top_{name}"] - part[f"univ_{name}"]))
            d["mean_top_minus_spy"] = float(np.nanmean(part[f"top_{name}"] - part[f"spy_{name}"]))
            d["mean_top_minus_bottom"] = float(np.nanmean(part[f"top_{name}"] - part[f"bottom_{name}"]))
            d["hit_top_vs_univ"] = float(np.nanmean((part[f"top_{name}"] > part[f"univ_{name}"]).to_numpy(dtype=float)))
            stats[f"{part_name}_{name}"] = d
    out["by_horizon"] = stats
    x = (judge[f"top_{MAIN_H}"] - judge[f"univ_{MAIN_H}"]).to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    out["observed_ir"] = float(x.mean() / x.std(ddof=1) * math.sqrt(12 / 3)) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")
    out["noop"] = rp.noop_guard(list(x))
    out["mean_n_eligible"] = float(judge["n_eligible"].mean())
    out["mean_n_top"] = float(judge["n_top"].mean())
    return out


# =================================================================================================
# 4. 팔지 않는 적립 계좌 (lab.weighted_window)
# =================================================================================================

def account_test(P: Panel, first_form: pd.Timestamp, smoke: bool) -> dict:
    days = P.days
    cg = np.ones(len(days))
    spy = P.col["SPY"]
    fallback = {"TOP": 0, "SAT": 0}

    def w_top(r):
        f = P.form(r)
        if not f["ok"]:
            fallback["TOP"] += 1
            return [(spy, 1.0)]
        return [(c, 1.0 / len(f["top"])) for c in f["top"]]

    def w_sat(r):
        f = P.form(r)
        if not f["ok"]:
            fallback["SAT"] += 1
            return [(spy, 1.0)]
        return [(spy, 1.0 - SAT_W)] + [(c, SAT_W / len(f["top"])) for c in f["top"]]

    def w_spy(r):
        return [(spy, 1.0)]

    # weighted_window 은 열 0 을 시장으로 본다(가격 결측 대체). SPY 를 0 열로 둔 보기.
    order = [spy] + [i for i in range(len(P.cols)) if i != spy]
    px = P.px[:, order]
    remap = {c: j for j, c in enumerate(order)}

    def wrap(fn):
        return lambda r: [(remap[c], w) for c, w in fn(r)]

    wins = re_.rolling_windows(days, WIN_YEARS, step="M", first_start=first_form)
    if smoke:
        wins = wins[::6]
    sets = {"judge": [w for w in wins if w[1] <= JUDGE_END], "post2024_10_report": [w for w in wins if w[1] > JUDGE_END]}
    out: dict[str, Any] = {"n_windows": {k: len(v) for k, v in sets.items()}}
    for set_name, ws in sets.items():
        rows = {"TOP": [], "SAT": []}
        for s, e in ws:
            base = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, wrap(w_spy), fee=FEE)
            for arm, fn in (("TOP", w_top), ("SAT", w_sat)):
                a = L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, wrap(fn), fee=FEE)
                rows[arm].append({"start": str(s.date()), "end": str(e.date()), "strategy_irr": a["irr"], "base_irr": base["irr"],
                                  "strategy_terminal": a["terminal"], "base_terminal": base["terminal"],
                                  "strategy_mdd": a["mdd"], "base_mdd": base["mdd"]})
        for arm in rows:
            summ = L.summarize_pairs(rows[arm])
            if summ.get("n_windows"):
                summ["pass"] = bool(summ["share_win"] >= WIN_SHARE_MIN and summ["median_diff_irr"] >= MED_IRR_MIN)
            out[f"{set_name}_{arm}"] = summ
    out["spy_fallback_months"] = dict(fallback)
    return out


# =================================================================================================
# 5. 합성 자료(스모크 — 네트워크 없음, 모든 코드 경로)
# =================================================================================================

class FakeClient:
    """EdgarClient 대역: resolve_cik/_get 만. 가짜 companyfacts JSON 을 돌려준다."""

    def __init__(self, raws: dict[str, dict]):
        self.raws = raws
        self.calls = 0

    def resolve_cik(self, t):
        from core.filing_changes import EdgarFetchError

        if t not in self.raws:
            raise EdgarFetchError("ticker not found", kind="ticker_not_found")
        return str(abs(hash(t)) % 10 ** 10).zfill(10)

    def _get(self, url):
        self.calls += 1
        cik = url.rsplit("CIK", 1)[1].split(".")[0]
        for t, raw in self.raws.items():
            if str(abs(hash(t)) % 10 ** 10).zfill(10) == cik:
                return json.dumps(raw).encode()
        raise ValueError("unknown cik")


def synthetic_raw(i: int, rng) -> dict:
    """회사 i 의 가짜 companyfacts: 2006~2021 분기(12월 결산), 10-Q 1~3분기 + 10-K 연간(전년 비교 포함), 공시일은 흩어 둠.
    일부는 4분기 직접 · Basic 만 · 해 중간 2:1 분할(재작성) · 정정 · 첫 공시가 늦은 과거 비교 숫자."""
    facts = []
    level = 1.0 + 0.1 * i
    basic_only = i % 11 == 3
    direct_q4 = i % 7 == 2
    split_at = (2015, 3) if i % 13 == 5 else None      # 2015년 3분기부터 분할 후 기준

    def post_split(y, q):
        return split_at is not None and (y, q) >= split_at

    q_vals = {}
    for y in range(2006, 2022):
        level *= 1.0 + rng.normal(0.04, 0.05)
        for q in range(1, 5):
            q_vals[(y, q)] = level / 4 * (1 + 0.1 * (q - 2.5) / 2) + rng.normal(0, 0.04 * level)
    q_end = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    q_start = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    first_year = 2009 if i % 19 == 6 else 2006          # 이 회사는 2009 년에 처음 XBRL 을 내며 과거를 비교 숫자로만 보여 줌
    for (y, q), v in q_vals.items():
        s, e = date(y, *q_start[q]), date(y, *q_end[q])
        lag = int(rng.integers(25, 45)) if q < 4 else int(rng.integers(45, 75))
        filed = e + timedelta(days=lag)
        if y < first_year:
            filed = date(first_year, 5, 1)
        shown = v / 2 if post_split(y, q) else v
        if q < 4 or direct_q4:
            facts.append({"start": s.isoformat(), "end": e.isoformat(), "val": round(shown, 4), "filed": filed.isoformat(),
                          "form": "10-Q" if q < 4 else "10-K"})
            nxt = (y + 1, q)
            facts.append({"start": s.isoformat(), "end": e.isoformat(), "val": round(v / 2 if post_split(*nxt) else v, 4),
                          "filed": (filed + timedelta(days=364)).isoformat(), "form": "10-Q" if q < 4 else "10-K"})
        if q == 4:
            div_now = 2 if post_split(y, 4) else 1
            ann = sum(q_vals[(y, k)] for k in range(1, 5)) / div_now
            facts.append({"start": date(y, 1, 1).isoformat(), "end": e.isoformat(), "val": round(ann, 4),
                          "filed": filed.isoformat(), "form": "10-K"})
            if y > 2006:   # 같은 10-K 의 전년 연간(분할이면 재작성)
                prev = sum(q_vals[(y - 1, k)] for k in range(1, 5)) / div_now
                facts.append({"start": date(y - 1, 1, 1).isoformat(), "end": date(y - 1, 12, 31).isoformat(), "val": round(prev, 4),
                              "filed": filed.isoformat(), "form": "10-K"})
    if i % 17 == 4:   # 정정 공시(같은 기간, 더 늦은 공시일)
        f0 = facts[40]
        facts.append({**f0, "val": f0["val"] + 0.05, "filed": (_d(f0["filed"]) + timedelta(days=20)).isoformat(), "form": "10-Q/A"})
    concept = "EarningsPerShareBasic" if basic_only else "EarningsPerShareDiluted"
    facts.append({"start": "2010-01-01", "end": "2010-03-31", "val": 1.0, "filed": "2010-05-01", "form": "8-K"})   # 버려져야 함
    return {"facts": {"us-gaap": {concept: {"units": {UNIT: facts, "USD": [{"val": 5}]}}}}}


def synthetic_inputs(R) -> dict:
    rng = np.random.default_rng(7)
    tickers = [f"T{i:02d}" for i in range(70)]
    raws = {t: synthetic_raw(i, rng) for i, t in enumerate(tickers) if i != 69}   # T69: SEC 에 없음
    client = FakeClient(raws)
    cache = R.ck / "smoke_cache"
    fixed_now = lambda: datetime(2022, 1, 15, tzinfo=timezone.utc)  # noqa: E731
    got = fetch_eps(R, tickers, client, cache, fixed_now)
    calls_first = client.calls
    again = fetch_eps(R, tickers, client, cache, fixed_now)          # 두 번째는 모두 캐시
    assert client.calls == calls_first, "캐시가 재사용되지 않음"
    assert again["stats"]["cached"] == len(tickers), again["stats"]
    days = pd.bdate_range("2006-01-02", "2021-12-31")

    def members_at(d: date) -> frozenset:
        base = set(tickers[:60])
        if d >= date(2014, 1, 1):
            base |= set(tickers[60:])
        if d >= date(2018, 6, 1):
            base -= {"T05"}
        return frozenset(base)

    return {"records": got["records"], "stats": got["stats"], "days": days, "tickers": tickers, "members_at": members_at,
            "source": "synthetic (smoke)"}


def synthetic_closes(days: pd.DatetimeIndex, tickers: list[str], events: pd.DataFrame) -> pd.DataFrame:
    """SPY + 종목 가격. 공시 다음 60거래일 동안 SUE 에 비례한 표류를 넣는다(코드 경로 확인용, 결과 의미 없음)."""
    rng = np.random.default_rng(11)
    n = len(days)
    mkt = rng.normal(0.0003, 0.01, n)
    cols = {"SPY": 100 * np.cumprod(1 + mkt)}
    for i, t in enumerate(tickers):
        r = mkt * (0.8 + 0.4 * rng.random()) + rng.normal(0.0001, 0.015, n)
        ev = events[events["ticker"] == t]
        for f, s in zip(ev["filed"], ev["sue"]):
            u = days.searchsorted(pd.Timestamp(f), side="right")
            r[u:u + 60] += 0.0002 * float(np.clip(s, -5, 5))
        p = 50 * np.cumprod(1 + r)
        if t == "T07":
            p[days >= pd.Timestamp("2016-03-01")] = np.nan       # 상장폐지 흉내
        if t == "T61":
            p[days < pd.Timestamp("2012-01-03")] = np.nan        # 늦게 상장
        cols[t] = p
    return pd.DataFrame(cols, index=days)


# =================================================================================================
# 6. 본문
# =================================================================================================

def build_events(records: dict[str, dict]) -> tuple[pd.DataFrame, dict]:
    allev, diag_sum = [], {}
    n_with = 0
    for t, rec in sorted(records.items()):
        if not rec or rec.get("missing"):
            continue
        ev, diag = sue_events(t, rec)
        if ev:
            n_with += 1
        allev.extend(ev)
        for k, v in diag.items():
            diag_sum[k] = diag_sum.get(k, 0) + v
    diag_sum["tickers_with_events"] = n_with
    df = pd.DataFrame(allev, columns=["ticker", "end", "filed", "sue", "eps", "eps_lag4"])
    return df, diag_sum


def body(R):
    if R.smoke:
        inp = synthetic_inputs(R)          # 가볍고, members_at 함수는 저장(pickle)할 수 없어 단계로 두지 않는다
        members_at, tickers = inp["members_at"], inp["tickers"]
        records, sec_stats, source = inp["records"], inp["stats"], inp["source"]
    else:
        members_at, tickers = sp500_members()
        R.log(f"S&P 500 시점 기준 구성종목 합집합 {len(tickers)}종목 ({UNIVERSE_START}~)")
        from core.filing_changes import EdgarClient

        client = EdgarClient(record_first_seen=False)
        got = fetch_eps(R, tickers, client, CACHE_DIR, lambda: datetime.now(timezone.utc))
        records, sec_stats = got["records"], got["stats"]
        source = "SEC EDGAR XBRL companyfacts (EPS diluted→basic, filed date) + core.market_data adjusted close + fja05680 S&P 500 PIT membership"
    events, diag = R.stage("events", lambda: build_events(records))
    R.log(f"SUE 사건 {len(events)}건, 종목 {diag.get('tickers_with_events')}개")
    if R.smoke:
        closes = R.stage("closes", lambda: synthetic_closes(inp["days"], tickers, events))
    else:
        closes = load_prices_real(R, [t for t in tickers if t != "SPY"])
    P = Panel(events, closes, members_at)
    tab = R.stage("monthly", lambda: monthly_table(P))
    if tab.empty:
        raise RuntimeError("형성 가능한 달이 없음(사건·가격 부족)")
    first_form = tab.index[0]
    ev_res = R.stage("event_test", lambda: event_test(tab, R.smoke))
    acc = R.stage("account", lambda: account_test(P, first_form, R.smoke))
    judge_years = max((min(tab.index[-1], JUDGE_END) - first_form).days / 365.25, 0.0)
    power = rp.power_report(judge_years, 1)

    halves = ev_res.get("halves") or []
    acc_top = acc.get("judge_TOP", {})
    evaluable = (ev_res["n_months_judge"] >= MIN_JUDGE_MONTHS and len(halves) == 2 and all(h["n"] >= 2 * BLOCK_M for h in halves)
                 and acc["n_windows"]["judge"] >= MIN_WINDOWS and ev_res.get("noop") is None)
    event_pass = bool(halves) and all(h["pass"] for h in halves)
    acc_pass = bool(acc_top.get("pass"))
    if not evaluable:
        main = "NOT_EVALUABLE"
    elif event_pass and acc_pass:
        main = "PEAD_ALIVE"
    else:
        main = rp.classify_fail(ev_res.get("observed_ir"), power)
    verdicts = {"PEAD": main,
                "event_H1": "PASS" if halves and halves[0]["pass"] else "FAIL",
                "event_H2": "PASS" if len(halves) > 1 and halves[1]["pass"] else "FAIL",
                "account_top_vs_spy": "PASS" if acc_pass else "FAIL",
                "satellite_85_15_report": "PASS(보고)" if acc.get("judge_SAT", {}).get("pass") else "FAIL(보고)"}
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    result = L.rnd({
        "judge_version": RULES_VERSION, "smoke": R.smoke, "source": source, "verdicts": verdicts,
        "power": power, "power_line": rp.power_line(power),
        "coverage": {"tickers_universe": len(tickers), "sec": sec_stats, "events": int(len(events)),
                     "event_first": str(events["filed"].min()) if len(events) else None,
                     "event_last": str(events["filed"].max()) if len(events) else None,
                     "tickers_with_price": int(closes.notna().any().sum()) - 1, "diag": diag,
                     "months_formed": int(len(tab)), "first_formation": str(first_form.date()), "last_formation": str(tab.index[-1].date())},
        "event_test": ev_res, "account": acc,
        "rule": {"lookback_trading_days": LOOKBACK, "horizons": HORIZONS, "decile": DECILE, "min_names": MIN_NAMES,
                 "judge_end": str(JUDGE_END.date()), "boot": BOOT, "block_months": BLOCK_M, "alpha": ALPHA,
                 "monthly_krw": MONTHLY_KRW, "window_years": WIN_YEARS, "win_share_min": WIN_SHARE_MIN, "median_irr_min": MED_IRR_MIN,
                 "satellite_weight": SAT_W, "fee_per_buy": L.FEE, "fx_spread_per_buy": L.FX_SPREAD, "fx": L.FX, "cgt": L.CGT,
                 "allowance_krw": L.ALLOWANCE, "max_file_lag_days": MAX_FILE_LAG_DAYS, "sue_diffs": N_DIFFS, "min_diffs": MIN_DIFFS,
                 "q4_guard": Q4_GUARD},
    })
    if R.smoke:
        assert len(events) > 500, "합성 사건이 너무 적음"
        assert diag["q4_derived"] > 0 and diag["q4_direct"] > 0 and diag["q4_split_guard"] > 0 and diag["late_first_filing"] > 0, diag
        assert len(halves) == 2 and acc["n_windows"]["judge"] > 0 and acc_top.get("n_windows"), "검정 경로가 비었음"
        assert sec_stats["missing"] >= 1, "SEC 없음 경로가 안 돌았음"
    return result, render(result)


# =================================================================================================
# 7. 보고서
# =================================================================================================

def render(r: dict) -> str:
    P = L.pct
    v, cov, ev, acc = r["verdicts"], r["coverage"], r["event_test"], r["account"]
    out = [f"# 실적 발표 뒤 표류(PEAD) — 무료 SEC 실적으로 SPY 를 이기나 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "분기 EPS 가 1년 전 같은 분기보다 '평소보다 얼마나 크게' 좋아졌는지(SUE)로 매달 상위 10% 종목을 고르고, "
           "그 종목들이 그 뒤 몇 달 동안 시장보다 더 오르는지, 그리고 매달 10만 원씩 사서 팔지 않으면 SPY 적립보다 나은지 본다.", "",
           f"**종합 판정: {v['PEAD']}** — 표류 검정 앞 절반 {v['event_H1']} · 뒤 절반 {v['event_H2']} · 적립 계좌(상위 10% vs SPY) {v['account_top_vs_spy']} · "
           f"새틀라이트 85/15 {v['satellite_85_15_report']}", "",
           "통과해도 엔진에 자동 반영되지 않는다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", "",
           "- 실적: SEC EDGAR XBRL 의 분기 희석 EPS(없으면 기본 EPS). 숫자마다 붙은 공시일의 **다음 거래일**부터만 신호로 쓴다. "
           "4분기는 10-K 연간 EPS − 1~3분기(공시일까지 알려진 값)로 만들고, 셋 중 하나라도 없으면 건너뛴다(액면분할이 끼어 값이 이상하면 버림).",
           f"- 놀람(SUE) = (이번 분기 EPS − 1년 전 같은 분기 EPS) ÷ 직전 8개 '1년 전 대비 차이'의 표준편차(6개 이상 필요). 처음 공시가 분기 끝 뒤 {MAX_FILE_LAG_DAYS}일을 넘으면 사건으로 치지 않는다.",
           f"- 매달 첫 거래일에, 지난 {LOOKBACK}거래일 안에 쓸 수 있게 된 사건으로 그날 S&P 500 편입 종목의 SUE 순위를 매겨 상위·하위 10% 를 만든다(후보 {MIN_NAMES}종목 이상인 달만). 그날 종가에 산다고 본다.",
           f"- 표류 검정: '상위 10% − 편입 종목 전체 동일가중'의 3개월 수익. 판정 구간(3개월 끝 ≤ {r['rule']['judge_end']})을 가운데 날로 둘로 나눠 **두 절반 모두** 평균 > 0, "
           f"{BLOCK_M}개월 이동 블록 부트스트랩 단측 p < {ALPHA}.",
           f"- 적립 계좌: 매달 10만 원을 상위 10% 에 똑같이 나눠 사고 팔지 않는다(매수마다 수수료 0.1% + 환전 0.05%, 환율 1,300원 고정, 끝에 양도세 22% × (이익 − 250만 원)). "
           f"5년 구간(매달 시작)마다 같은 돈을 SPY 에 넣은 경우와 비교해 이긴 구간 ≥ {WIN_SHARE_MIN:.0%}, 연수익(IRR) 차이 중앙값 ≥ +{MED_IRR_MIN * 100:.1f}%p.",
           "- 둘 다 통과해야 PEAD_ALIVE. 2024-10 이후는 이미 여러 연구가 본 구간이라 보고만 한다. 새틀라이트(SPY 85% + 상위 10% 15%)도 보고만.",
           "", "- " + r["power_line"], "",
           "## 자료 범위", "",
           f"- 종목 {cov['tickers_universe']}개(2009 년 이후 한 번이라도 S&P 500 에 든 종목) 중 가격 있음 {cov['tickers_with_price']}개, SUE 사건이 있는 종목 {cov['diag'].get('tickers_with_events')}개, 사건 {cov['events']:,}건 "
           f"({cov['event_first']} ~ {cov['event_last']}).",
           f"- SEC 받기: {cov['sec']}. 4분기 직접 {cov['diag'].get('q4_direct', 0)} · 유도 {cov['diag'].get('q4_derived', 0)} · 분기 부족으로 건너뜀 {cov['diag'].get('q4_missing_quarters', 0)} · 분할 의심으로 버림 {cov['diag'].get('q4_split_guard', 0)}.",
           f"- 형성한 달 {cov['months_formed']}개({cov['first_formation']} ~ {cov['last_formation']}), 판정 구간 {ev.get('n_months_judge')}개월, 평균 후보 {ev.get('mean_n_eligible', 0):.0f}종목 · 상위 10% {ev.get('mean_n_top', 0):.0f}종목.", "",
           "## 표류 검정 (상위 10% − 편입 종목 동일가중, 3개월)", "",
           "| 절반 | 기간 | 달 수 | 평균 초과 | 단측 p | 통과 |", "|---|---|---|---|---|---|"]
    for h in ev.get("halves", []):
        out.append(f"| {h['half']} | {h['first']} ~ {h['last']} | {h['n']} | {P(h['mean_top_minus_univ'], True, 2)} | {h['p_one_sided'] if h['p_one_sided'] is not None else '—'} | {'예' if h['pass'] else '아니오'} |")
    out += ["", "## 기간별 평균 수익 (보고)", "",
            "| 구간·기간 | 상위 10% | 하위 10% | 편입 전체 | SPY | 상위 − 전체 | 상위 − SPY | 상위 − 하위 | 상위가 전체를 이긴 달 |", "|---|---|---|---|---|---|---|---|---|"]
    for k, d in (ev.get("by_horizon") or {}).items():
        label = k.replace("judge_", "판정 ").replace("post2024_10_report_", "2024-10 이후(보고) ")
        out.append(f"| {label} | {P(d['mean_top'], True, 2)} | {P(d['mean_bottom'], True, 2)} | {P(d['mean_univ'], True, 2)} | {P(d['mean_spy'], True, 2)} | "
                   f"{P(d['mean_top_minus_univ'], True, 2)} | {P(d['mean_top_minus_spy'], True, 2)} | {P(d['mean_top_minus_bottom'], True, 2)} | {P(d['hit_top_vs_univ'])} |")
    out += ["", "## 팔지 않는 적립 계좌 (매달 10만 원, 5년 구간, 청산 세후)", "",
            "| 구간 | 방식 | 구간 수 | SPY 를 이긴 비율 | IRR 차이 중앙값 | 10%~90% | 방식 IRR 중앙값 | SPY IRR 중앙값 | 통과 |", "|---|---|---|---|---|---|---|---|---|"]
    for set_name, label in (("judge", "판정"), ("post2024_10_report", "2024-10 이후 끝(보고)")):
        for arm, alabel in (("TOP", "상위 10% 100%"), ("SAT", "SPY 85% + 상위 10% 15%(보고)")):
            s = acc.get(f"{set_name}_{arm}") or {}
            if not s.get("n_windows"):
                out.append(f"| {label} | {alabel} | 0 | — | — | — | — | — | — |")
                continue
            out.append(f"| {label} | {alabel} | {s['n_windows']} | {P(s['share_win'])} | {P(s['median_diff_irr'], True, 2)} | "
                       f"{P(s['p10_diff_irr'], True, 1)} ~ {P(s['p90_diff_irr'], True, 1)} | {P(s['median_strategy_irr'], False, 2)} | {P(s['median_base_irr'], False, 2)} | "
                       f"{'예' if s.get('pass') else '아니오'} |")
    fb = acc.get("spy_fallback_months", {})
    out += ["", f"후보가 {MIN_NAMES}종목 미만이라 그달 돈을 SPY 에 넣은 횟수(모든 구간 합): 상위 10% {fb.get('TOP', 0)} · 새틀라이트 {fb.get('SAT', 0)}.", "",
            "## 주의", "",
            "- **생존 편향**: 구성종목은 그 시점 S&P 500 이지만, SEC 티커 목록과 가격 캐시가 '현재' 기준이라 상장폐지·인수·이름 바뀐 회사는 대개 빠진다. "
            "빠진 회사는 나쁜 결말이 많으므로 결과가 실제보다 좋게 나올 수 있다. 가격이 중간에 끊긴 종목은 마지막 가격으로 보유 가치를 동결했다.",
            "- 신호일은 10-Q/10-K **공시일 다음 거래일**이다. 실제 실적 발표(보도자료)는 보통 이보다 며칠~몇 주 빠르므로, 발표 직후의 가장 큰 반응은 이 검정에 들어가지 않는다(보수적).",
            "- 애널리스트 추정치가 아니라 '1년 전 같은 분기'를 기대치로 쓴 놀람이다. 추정치 기반 놀람은 무료 과거 자료가 없어 시험하지 못했다(앞으로 쌓는 추정치 기록은 core/estimate_shadow.py).",
            "- EPS 는 주식 수 변화 때문에 4분기 유도 값이 정확히 더해지지 않는다. 분할 전후 값이 섞이면 버렸지만 모두 걸러졌다고 보장하지 못한다.",
            "- 매달 상위 10% 는 50종목 안팎이라 실제 계좌로 따라 하려면 매수 건수가 많다. 비용은 매수마다 0.15% 로 넣었다. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
