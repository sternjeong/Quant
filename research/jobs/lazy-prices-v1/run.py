"""검증 연구 lazy-prices-v1 (2026-11-15 사전 등록): 10-K 를 작년과 거의 똑같이 낸 회사가 많이 고친 회사·시장보다 낫나.

참고한 선행 연구(아이디어만 — 코드는 가져오지 않았다):
  - Cohen·Malloy·Nguyen(2020, JF) 'Lazy Prices': 10-K/10-Q 문장을 전년과 많이 바꾼 회사(changers)는 이후 수익이 나쁘고,
    거의 안 바꾼 회사(non-changers)가 낫다. 투자자가 긴 공시의 '바뀐 곳'을 늦게 알아챈다는 해석. 주 척도는 단어 빈도 코사인 유사도.
  - 우리 core.filing_changes(공시 변화 거부권 shadow)는 같은 생각을 문장 단위로 앞으로만 쌓는데, 스펙 스스로 최소 표본까지
    8~40년이라 적었다. 이 연구는 과거 10-K 전체(2007~)로 같은 질문을 지금 잰다.

자료(미리 보기 없음):
  - SEC EDGAR submissions(정정본 10-K/A 제외)의 10-K 주 문서. 같은 회사의 바로 앞 10-K(공시 간격 300~450일)와 비교한다.
    시점 기준은 filingDate — 신호는 공시일 '다음 거래일'부터. 문서는 받아서 바로 단어 빈도로 줄이고 원문은 저장하지 않는다.
  - 유사도(주): 소문자 알파벳 단어(2글자 이상, 숫자 제외) 빈도 벡터의 코사인. (보고) 단어 집합 Jaccard.
  - 종목·가격: earnings-surprise-v1 과 같다(fja05680 S&P 500 시점 기준 구성종목 2009~, core.market_data 조정 종가).
    티커 → CIK 는 SEC '현재' 목록이라 상장폐지·이름 바뀐 회사는 대개 빠진다(생존 편향 — REPORT 명시).

검정(결과를 보기 전에 고정):
  매달 첫 거래일 r(2009-01 부터)에, 다음 거래일이 [r−252, r−1] 거래일 안에 드는 10-K 유사도(종목별 가장 최근)로
  그날 편입·r 일 가격 있는 종목을 줄 세운다(50종목 이상인 달만).
    NONCHANGERS = 유사도 상위 20% (판정 1개)        CHANGERS = 하위 20% (보고)
  r 일 종가 매수, 1/3/6개월 단순 수익, 동일가중. 비교: 같은 날 편입 종목 전체 동일가중, SPY.
  LAZY_ALIVE ⇔ ① 판정 구간(3개월 끝 ≤ 2024-09-30)을 가운데 날로 나눈 두 절반 모두 'NONCHANGERS − 편입 전체' 3개월 평균 > 0,
    이동 블록 부트스트랩(12개월, 2,000회) 단측 p < 0.05
    ② 팔지 않는 적립(매달 10만 원, 5년 구간): SPY 적립 대비 이긴 비율 ≥ 60% & IRR 차이 중앙값 ≥ +0.5%p.
  그 밖은 FAIL(관측 IR 이 최소 검출 효과보다 작으면 FAIL_UNDERPOWERED), 판정 달 48·구간 12 미만이면 NOT_EVALUABLE.
  보고만: CHANGERS, NONCHANGERS − CHANGERS, 새틀라이트(SPY 85 + 15), Jaccard, 1·6개월, 2024-10 이후.
엔진은 바뀌지 않는다(사용자 확인 뒤 별도 작업).
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Optional

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

JOB_ID = "lazy-prices-v1"
RULES_VERSION = "lazy-prices-v1/2026-11-15"
FIRST_FILED = "2007-01-01"
GAP_DAYS = (300, 450)
LOOKBACK = 252
QUANTILE = 0.20
MIN_NAMES = 50
FORM_START = pd.Timestamp("2009-01-01")
CHUNK = 25
RETRIES = 2
WORD_RE = re.compile(r"[a-z]{2,}")


# =================================================================================================
# 1. 문서 → 단어 빈도 → 유사도
# =================================================================================================

def word_counts(raw: str) -> Counter:
    from core.filing_changes import text_from_document

    return Counter(WORD_RE.findall(text_from_document(raw).lower()))


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return float("nan")
    small, big = (a, b) if len(a) < len(b) else (b, a)
    dot = sum(v * big.get(k, 0) for k, v in small.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb)


def jaccard(a: Counter, b: Counter) -> float:
    if not a or not b:
        return float("nan")
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb)


def ticker_events(client, ticker: str) -> list[dict]:
    """한 회사의 10-K 를 오래된 순으로 받아 바로 앞 10-K 와의 유사도 사건 목록을 만든다(원문은 메모리에서 버린다)."""
    recs = [r for r in client.list_filings(ticker=ticker, forms=("10-K",), include_older=True)
            if r.filing_date >= FIRST_FILED and not r.is_amendment]
    recs.sort(key=lambda r: (r.filing_date, r.accession))
    out, prev, prev_date = [], None, None
    for r in recs:
        raw = client._get(r.document_url)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        wc = word_counts(text)
        del raw, text
        d = date.fromisoformat(r.filing_date)
        if prev is not None and GAP_DAYS[0] <= (d - prev_date).days <= GAP_DAYS[1] and len(wc) > 200 and len(prev) > 200:
            out.append({"ticker": ticker, "filed": r.filing_date, "sim": cosine(prev, wc), "jac": jaccard(prev, wc),
                        "n_words": int(sum(wc.values()))})
        prev, prev_date = wc, d
    return out


def fetch_events(R, client, tickers: list[str]) -> tuple[pd.DataFrame, dict]:
    from core.filing_changes import EdgarBlocked, EdgarFetchError

    rows: list[dict] = []
    stats = {"tickers": len(tickers), "with_events": 0, "missing": 0, "failed": 0}
    for k in range(0, len(tickers), CHUNK):
        part = tickers[k:k + CHUNK]

        def chunk(part=part):
            got, miss, fail = {}, [], []
            for t in part:
                R.check_time()
                for attempt in range(RETRIES + 1):
                    try:
                        got[t] = ticker_events(client, t)
                        break
                    except EdgarBlocked:
                        raise
                    except EdgarFetchError as exc:
                        if getattr(exc, "kind", "") == "ticker_not_found" or getattr(exc, "status", None) == 404:
                            miss.append(t)
                            break
                        if attempt == RETRIES:
                            fail.append(t)
            return {"got": got, "missing": miss, "failed": fail}

        res = R.stage(f"sec_{k // CHUNK:03d}", chunk)
        for evs in res["got"].values():
            rows.extend(evs)
            stats["with_events"] += bool(evs)
        stats["missing"] += len(res["missing"])
        stats["failed"] += len(res["failed"])
        R.log(f"10-K 유사도 {min(k + CHUNK, len(tickers))}/{len(tickers)} {stats}")
    df = pd.DataFrame(rows, columns=["ticker", "filed", "sim", "jac", "n_words"])
    stats["events"] = int(len(df))
    return df, stats


class LazyPanel(ES.Panel):
    """earnings-surprise-v1 의 Panel 에 형성 규칙만 바꿔 끼운다: 최근 252거래일 안 가장 최근 10-K 유사도 5분위."""

    def __init__(self, events: pd.DataFrame, closes: pd.DataFrame, members_at, score: str = "sim"):
        super().__init__(events, closes, members_at)
        self.score = self.ev[score].to_numpy(dtype=float)
        self.tick = self.ev["ticker"].to_numpy()

    def form(self, r: int) -> dict:
        if r in self._cache:
            return self._cache[r]
        out = {"top": [], "bottom": [], "universe": [], "n_eligible": 0, "ok": False}
        if r >= 1 and self.days[r] >= FORM_START:
            mem = self.members_at(self.days[r - 1].date())
            uni = [self.col[t] for t in mem if t in self.col and t != "SPY" and np.isfinite(self.raw[r, self.col[t]])]
            lo, hi = np.searchsorted(self.ev_u, r - LOOKBACK, "left"), np.searchsorted(self.ev_u, r - 1, "right")
            latest: dict[str, float] = {}
            for t, s in zip(self.tick[lo:hi], self.score[lo:hi]):
                if np.isfinite(s):
                    latest[t] = float(s)          # 정렬 순서상 뒤가 더 최근
            uni_set = set(uni)
            elig = sorted((s, self.col[t]) for t, s in latest.items() if t in mem and self.col[t] in uni_set)
            out["universe"], out["n_eligible"] = uni, len(elig)
            if len(elig) >= MIN_NAMES:
                k = max(1, int(math.ceil(len(elig) * QUANTILE)))
                out["bottom"] = [c for _, c in elig[:k]]      # 많이 고친 회사(changers)
                out["top"] = [c for _, c in elig[-k:]]        # 거의 안 고친 회사(non-changers)
                out["ok"] = True
        self._cache[r] = out
        return out


# =================================================================================================
# 2. 합성 자료(스모크 — 네트워크 없음)
# =================================================================================================

class FakeClient:
    """list_filings·_get 만. 회사마다 해마다 10-K 를 내고, 일부는 문장을 많이 바꾼다."""

    def __init__(self, tickers: list[str], seed: int = 3):
        from core.filing_changes import FilingRecord

        rng = np.random.default_rng(seed)
        vocab = np.array([f"w{chr(97 + i % 26)}{chr(97 + (i // 26) % 26)}{chr(97 + (i // 676) % 26)}" for i in range(3000)])
        self.docs, self.recs, self.calls = {}, {}, 0
        for i, t in enumerate(tickers):
            if t == "T69":
                continue                                           # SEC 에 없는 종목
            base = rng.integers(0, len(vocab), 1500)
            recs = []
            for y in range(2007, 2022):
                change = 0.05 if i % 3 else 0.5                    # 셋 중 하나는 많이 고친다
                idx = rng.choice(len(base), int(len(base) * change), replace=False)
                base[idx] = rng.integers(0, len(vocab), len(idx))
                acc = f"0000{i:04d}{y}"
                url_doc = f"d{i}_{y}.htm"
                rec = FilingRecord(cik=str(i).zfill(10), accession=acc, form="10-K", filing_date=f"{y}-02-{10 + i % 15:02d}",
                                   acceptance_datetime=None, report_date=None, primary_document=url_doc, ticker=t)
                recs.append(rec)
                self.docs[rec.document_url] = ("<html><body><p>" + " ".join(vocab[base]) + " 2019 12,345</p></body></html>").encode()
                if y == 2012 and i % 7 == 0:                       # 정정본은 빠져야 한다
                    recs.append(FilingRecord(cik=rec.cik, accession=acc + "A", form="10-K/A", filing_date=f"{y}-05-01",
                                             acceptance_datetime=None, report_date=None, primary_document="a.htm", ticker=t))
            self.recs[t] = recs

    def list_filings(self, *, ticker, forms, include_older):
        from core.filing_changes import EdgarFetchError

        if ticker not in self.recs:
            raise EdgarFetchError("ticker not found", kind="ticker_not_found")
        return [r for r in self.recs[ticker] if r.form in set(forms) | {f + "/A" for f in forms}][::-1]

    def _get(self, url):
        self.calls += 1
        return self.docs[url]


def synthetic_inputs() -> dict:
    tickers = [f"T{i:02d}" for i in range(70)]
    days = pd.bdate_range("2006-01-02", "2021-12-31")

    def members_at(d: date) -> frozenset:
        base = set(tickers[:60])
        if d >= date(2014, 1, 1):
            base |= set(tickers[60:])
        return frozenset(base)

    return {"client": FakeClient(tickers), "tickers": tickers, "days": days, "members_at": members_at}


def synthetic_closes(days: pd.DatetimeIndex, tickers: list[str], events: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    mkt = rng.normal(0.0003, 0.01, len(days))
    cols = {"SPY": 100 * np.cumprod(1 + mkt)}
    for t in tickers:
        r = mkt * (0.8 + 0.4 * rng.random()) + rng.normal(0.0001, 0.015, len(days))
        for f, s in zip(events.loc[events["ticker"] == t, "filed"], events.loc[events["ticker"] == t, "sim"]):
            u = days.searchsorted(pd.Timestamp(f), side="right")
            r[u:u + 120] += 0.0002 * (s - 0.8)
        cols[t] = 50 * np.cumprod(1 + r)
    return pd.DataFrame(cols, index=days)


# =================================================================================================
# 3. 본문
# =================================================================================================

def judge(R, events, closes, members_at, score: str, power: dict) -> dict:
    P = LazyPanel(events, closes, members_at, score)
    tab = ES.monthly_table(P)
    if tab.empty:
        return {"verdict": "NOT_EVALUABLE", "reason": "형성 가능한 달 없음", "months_formed": 0}
    ev = ES.event_test(tab, R.smoke)
    acc = ES.account_test(P, tab.index[0], R.smoke)
    halves = ev.get("halves") or []
    evaluable = (ev["n_months_judge"] >= ES.MIN_JUDGE_MONTHS and len(halves) == 2 and all(h["n"] >= 2 * ES.BLOCK_M for h in halves)
                 and acc["n_windows"]["judge"] >= ES.MIN_WINDOWS and ev.get("noop") is None)
    event_pass = bool(halves) and all(h["pass"] for h in halves)
    acc_pass = bool(acc.get("judge_TOP", {}).get("pass"))
    if not evaluable:
        verdict = "NOT_EVALUABLE"
    elif event_pass and acc_pass:
        verdict = "LAZY_ALIVE"
    else:
        verdict = rp.classify_fail(ev.get("observed_ir"), power)
    return {"verdict": verdict, "event_pass": event_pass, "account_pass": acc_pass, "months_formed": int(len(tab)),
            "first_formation": str(tab.index[0].date()), "mean_names": float(tab["n_top"].mean()),
            "mean_eligible": float(tab["n_eligible"].mean()), "event_test": ev, "account": acc}


def body(R):
    if R.smoke:
        inp = synthetic_inputs()
        members_at, tickers, client = inp["members_at"], inp["tickers"], inp["client"]
        source = "synthetic (smoke)"
    else:
        from core.filing_changes import EdgarClient

        members_at, tickers = ES.sp500_members()
        client = EdgarClient(record_first_seen=False, timeout=120.0)
        source = "SEC EDGAR 10-K primary documents (filingDate) + core.market_data adjusted close + fja05680 S&P 500 PIT membership"
    events, sec_stats = fetch_events(R, client, [t for t in tickers if t != "SPY"])
    R.log(f"10-K 유사도 사건 {len(events)}건 {sec_stats}")
    if events.empty:
        raise RuntimeError("10-K 유사도 사건이 없음")
    if R.smoke:
        assert sec_stats["missing"] == 1, sec_stats
        low = events.groupby(events["ticker"].str[1:].astype(int) % 3 == 0)["sim"].median()
        assert low[True] < low[False], "많이 고친 회사의 유사도가 낮게 나오지 않음"
        closes = R.stage("closes", lambda: synthetic_closes(inp["days"], tickers, events))
    else:
        closes = ES.load_prices_real(R, [t for t in tickers if t != "SPY"])
    power = rp.power_report(max((ES.JUDGE_END - FORM_START).days / 365.25, 0.0), 1)
    main = R.stage("judge_sim", lambda: judge(R, events, closes, members_at, "sim", power))
    jac = R.stage("judge_jaccard_report", lambda: judge(R, events, closes, members_at, "jac", power))
    halves = main.get("event_test", {}).get("halves") or []
    verdicts = {"LAZY_PRICES": main["verdict"],
                "event_H1": "PASS" if halves and halves[0]["pass"] else "FAIL",
                "event_H2": "PASS" if len(halves) > 1 and halves[1]["pass"] else "FAIL",
                "account_nonchangers_vs_spy": "PASS" if main.get("account_pass") else "FAIL",
                "satellite_85_15_report": "PASS(보고)" if main.get("account", {}).get("judge_SAT", {}).get("pass") else "FAIL(보고)",
                "jaccard_report": jac["verdict"]}
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    sims = events["sim"].to_numpy(dtype=float)
    result = L.rnd({
        "id": JOB_ID, "judge_version": RULES_VERSION, "smoke": R.smoke, "source": source, "verdicts": verdicts,
        "power": power, "power_line": rp.power_line(power),
        "coverage": {**sec_stats, "event_first": str(events["filed"].min()), "event_last": str(events["filed"].max()),
                     "sim_quantiles": {q: float(np.nanquantile(sims, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
                     "median_words": float(events["n_words"].median()),
                     "tickers_with_price": int(closes.notna().any().sum()) - 1},
        "main": main, "jaccard_report": jac,
        "rule": {"lookback_trading_days": LOOKBACK, "quantile": QUANTILE, "min_names": MIN_NAMES, "gap_days": GAP_DAYS,
                 "horizons": ES.HORIZONS, "main_horizon": ES.MAIN_H, "judge_end": str(ES.JUDGE_END.date()), "boot": ES.BOOT,
                 "block_months": ES.BLOCK_M, "alpha": ES.ALPHA, "win_years": ES.WIN_YEARS, "win_share_min": ES.WIN_SHARE_MIN,
                 "median_irr_min": ES.MED_IRR_MIN}})
    return result, render(result)


def _arm_lines(x: dict, P) -> list[str]:
    if not x.get("months_formed"):
        return [f"형성 가능한 달 없음({x.get('reason', '')})", ""]
    ev, acc = x["event_test"], x["account"]
    out = [f"형성한 달 {x['months_formed']}개(첫 달 {x['first_formation']}), 달마다 줄 세운 종목 평균 {x['mean_eligible']:.0f}개 · 5분위 {x['mean_names']:.0f}종목 · "
           f"판정 달 {ev['n_months_judge']}개 · 관측 IR {ev.get('observed_ir')}",
           "", "| 절반 | 기간 | 달 | 3개월 'NONCHANGERS − 편입 전체' 평균 | 단측 p | 통과 |", "|---|---|---|---|---|---|"]
    for h in ev.get("halves") or []:
        out.append(f"| {h['half']} | {h['first']} ~ {h['last']} | {h['n']} | {P(h['mean_top_minus_univ'], True, 2)} | {h['p_one_sided']} | {'예' if h['pass'] else '아니오'} |")
    out += ["", "| 구간 | NONCHANGERS | CHANGERS | 편입 전체 | SPY | NON − 편입 | NON − CHANGERS | 이긴 달 비율 |", "|---|---|---|---|---|---|---|---|"]
    for k, d in ev.get("by_horizon", {}).items():
        out.append(f"| {k} | {P(d['mean_top'], nd=2)} | {P(d['mean_bottom'], nd=2)} | {P(d['mean_univ'], nd=2)} | {P(d['mean_spy'], nd=2)} | "
                   f"{P(d['mean_top_minus_univ'], True, 2)} | {P(d['mean_top_minus_bottom'], True, 2)} | {P(d['hit_top_vs_univ'], nd=0)} |")
    out += ["", "| 적립(매달 10만 원, 5년) | 구간 | 이긴 비율 | IRR 차이 중앙 | 통과 |", "|---|---|---|---|---|"]
    for k in ("judge_TOP", "judge_SAT", "post2024_10_report_TOP", "post2024_10_report_SAT"):
        s = acc.get(k) or {}
        if s.get("n_windows"):
            out.append(f"| {k} | {s['n_windows']} | {P(s['share_win'], nd=0)} | {P(s['median_diff_irr'], True, 2)}p | {'예' if s.get('pass') else '아니오'} |")
    return out + [""]


def render(r: dict) -> str:
    v, P, cov = r["verdicts"], L.pct, r["coverage"]
    out = [f"# 10-K 를 작년과 똑같이 낸 회사가 나은가 — Lazy Prices ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           f"**판정: {v['LAZY_PRICES']}** — " + " · ".join(f"{k} {val}" for k, val in v.items() if k != "LAZY_PRICES"), "",
           "통과는 '전진 원장 후보'일 뿐 엔진 채택이 아니다. 엔진은 바뀌지 않았다.", "", "## 규칙 (결과를 보기 전에 고정)", "",
           "- 유사도 = 같은 회사 바로 앞 10-K(300~450일 전)와의 단어 빈도 코사인(소문자 알파벳 2글자 이상, 숫자 제외). 정정본 제외. 신호는 공시일 다음 거래일부터.",
           f"- 매달 첫 거래일, 최근 {r['rule']['lookback_trading_days']}거래일 안 가장 최근 유사도로 편입 종목을 줄 세워 상위 {r['rule']['quantile']:.0%}(NONCHANGERS, 판정)·하위(CHANGERS, 보고). {r['rule']['min_names']}종목 미만인 달은 형성하지 않는다.",
           f"- LAZY_ALIVE ⇔ 두 절반 모두 3개월 'NONCHANGERS − 편입 동일가중' 평균 > 0 & 부트스트랩 단측 p < {r['rule']['alpha']} "
           f"& 적립 5년 구간 이긴 비율 ≥ {r['rule']['win_share_min']:.0%} & IRR 차이 중앙값 ≥ +{r['rule']['median_irr_min'] * 100:.1f}%p.",
           f"- 검정력: {r['power_line']}", "", "## 자료", "", f"- {r['source']}",
           f"- 종목 {cov['tickers']}개 중 사건 있음 {cov['with_events']}개, SEC 에 없음 {cov['missing']}개, 실패 {cov['failed']}개 · 사건 {cov['events']:,}건 "
           f"({cov['event_first']} ~ {cov['event_last']}) · 가격 있는 종목 {cov['tickers_with_price']}개",
           "- 유사도 분포(10·25·50·75·90%): " + " · ".join(f"{q:.2f}" for q in cov["sim_quantiles"].values()) + f" · 10-K 단어 수 중앙 {cov['median_words']:,.0f}", "",
           f"## 주 척도(코사인) — {r['main']['verdict']}", ""]
    out += _arm_lines(r["main"], P)
    out += [f"## 보고: 단어 집합 Jaccard — {r['jaccard_report']['verdict']}", ""]
    out += _arm_lines(r["jaccard_report"], P)
    out += ["## 주의", "",
            "- 티커 → CIK 는 SEC '현재' 목록이라 상장폐지·이름 바뀐 회사는 대개 빠진다(생존 편향). 가격도 Yahoo 캐시라 같은 한계가 있다.",
            "- 원 논문은 10-Q 도 쓰고 전체 미국 주식(소형주 포함)을 봤다. 여기는 10-K·S&P 500 대형주뿐이라 효과가 작을 수 있다.",
            "- 10-K 는 2~3월에 몰려 있어 달마다 신호가 고르게 새로 나오지 않는다(최근 252거래일 안 값을 쓴다). 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
