"""검증 연구 news-drift-v1 (2026-11-15 사전 등록): 크게 움직인 종목 — 뉴스가 많았으면 이어 가고, 조용했으면 되돌아오나.

가격만 쓰는 신호·실적·애널리스트·13F 가 모두 SPY 를 확실히 이기지 못했다. 뉴스는 Alpaca 뉴스 API(Benzinga, 2015~)로 과거 기사를
게시 시각과 함께 받을 수 있음을 2026-11-15 VM 에서 확인했다(2016·2020·2024 조회 모두 created_at 포함 응답).

참고한 선행 연구(아이디어만 — 코드는 가져오지 않았다):
  - Chan(2003, JFE) 'Stock price reaction to news and no-news': 한 달 크게 오른·내린 종목 중 **헤드라인이 있던 종목은 같은 방향으로
    표류**하고, **헤드라인 없이 움직인 종목은 되돌아온다**(특히 내린 종목). 감성 분석이 필요 없는 설계라 무료 자료로 정직하게 잴 수 있다.
  - Tetlock(2007)·FinBERT(ProsusAI) 같은 감성 점수는 쓰지 않는다 — 단어 사전·모델 선택이 자유도가 되어 결과를 본 뒤 고르기 쉽다.

S&P 500 대형주는 거의 매달 기사가 있어 '뉴스 있음/없음' 이분법이 서지 않는다. 그래서 그달 극단 종목들 안에서 **기사 수가 중앙값보다
많은가**로 나눈다(사전 등록).

자료(미리 보기 없음):
  - 종목·가격: earnings-surprise-v1 과 같다(fja05680 S&P 500 시점 기준 구성종목, core.market_data 조정 종가).
  - 기사 수: Alpaca /v1beta1/news, 종목 1개씩, 형성 달 창 [days[r−22] 21:00 UTC, days[r−1] 21:00 UTC)(미 동부 장 마감 무렵)에
    created_at 이 드는 기사. 4쪽(200건)에서 자른다(순위만 쓰므로 위쪽 자름은 동률로 처리된다).

검정(결과를 보기 전에 고정):
  매달 첫 거래일 r(2015-02 부터)에, 그날 편입·r−22·r 일 가격이 있는 종목의 직전 21거래일 수익(px[r−1]/px[r−22]−1)으로
  상위 10%(승자)·하위 10%(패자)를 뽑는다. 두 무리를 합친 기사 수 중앙값 m 으로 나눈다.
    W_NEWS = 승자 중 기사 수 > m  (뉴스와 함께 오름 → 이어 오르나)       ← 판정
    L_QUIET = 패자 중 기사 수 ≤ m (조용히 내림 → 되돌아오나)               ← 판정
    W_QUIET · L_NEWS · W_ALL · L_ALL (보고만)
  무리가 5종목 미만인 달은 형성하지 않는다(적립 계좌는 그달 SPY). r 일 종가 매수, 동일가중.
  NEWS_EDGE(팔마다) ⇔ ① 판정 구간(1개월 끝 ≤ 2024-09-30)을 가운데 날로 나눈 두 절반 모두 '무리 − 편입 종목 동일가중'
    **1개월** 수익 평균 > 0, 이동 블록 부트스트랩(12개월, 2,000회) 단측 p < 0.025(판정 2개)
    ② 팔지 않는 적립(매달 10만 원, 5년 구간): SPY 적립 대비 이긴 비율 ≥ 60% & IRR 차이 중앙값 ≥ +0.5%p.
  그 밖은 FAIL(관측 IR 이 최소 검출 효과보다 작으면 FAIL_UNDERPOWERED), 판정 달 48·구간 12 미만이면 NOT_EVALUABLE.
엔진은 바뀌지 않는다(사용자 확인 뒤 별도 작업).
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

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

JOB_ID = "news-drift-v1"
RULES_VERSION = "news-drift-v1/2026-11-15"
FORM_START = pd.Timestamp("2015-02-01")
RET_DAYS = 21
DECILE = 0.10
MIN_NAMES = 5
MAX_PAGES = 4
PAGE_LIMIT = 50
CLOSE_UTC_HOUR = 21
ALPHA = 0.025
MAIN_H = "1m"
JUDGED = ("W_NEWS", "L_QUIET")
REPORTED = ("W_QUIET", "L_NEWS", "W_ALL", "L_ALL")
ARMS = (*JUDGED, *REPORTED)
ARM_NOTE = {"W_NEWS": "승자(직전 21거래일 상위 10%) 중 기사 수가 극단 무리 중앙값보다 많음",
            "L_QUIET": "패자(하위 10%) 중 기사 수가 중앙값 이하",
            "W_QUIET": "승자 중 기사 수 중앙값 이하(보고)", "L_NEWS": "패자 중 기사 수 중앙값 초과(보고)",
            "W_ALL": "승자 전부(보고)", "L_ALL": "패자 전부(보고)"}


# =================================================================================================
# 1. 극단 종목 + 기사 수
# =================================================================================================

def extremes(px: np.ndarray, days: pd.DatetimeIndex, cols: list[str], members_at, r: int) -> tuple[list[str], list[str]]:
    if r < RET_DAYS + 1 or days[r] < FORM_START:
        return [], []
    mem = members_at(days[r - 1].date())
    a, b, c = px[r - RET_DAYS - 1], px[r - 1], px[r]
    rows = []
    for j, t in enumerate(cols):
        if t == "SPY" or t not in mem:
            continue
        if np.isfinite(a[j]) and np.isfinite(b[j]) and np.isfinite(c[j]) and a[j] > 0:
            rows.append((b[j] / a[j] - 1.0, t))
    if len(rows) < 2 * MIN_NAMES / DECILE:
        return [], []
    rows.sort()
    k = max(1, int(math.ceil(len(rows) * DECILE)))
    return [t for _, t in rows[-k:]], [t for _, t in rows[:k]]


def window(days: pd.DatetimeIndex, r: int) -> tuple[str, str]:
    s = days[r - RET_DAYS - 1] + pd.Timedelta(hours=CLOSE_UTC_HOUR)
    e = days[r - 1] + pd.Timedelta(hours=CLOSE_UTC_HOUR)
    return s.strftime("%Y-%m-%dT%H:%M:%SZ"), e.strftime("%Y-%m-%dT%H:%M:%SZ")


def count_news(get: Callable[[str], Any], ticker: str, start: str, end: str) -> int:
    seen: set = set()
    token = None
    for _ in range(MAX_PAGES):
        params = {"symbols": ticker, "start": start, "end": end, "limit": PAGE_LIMIT, "sort": "asc"}
        if token:
            params["page_token"] = token
        payload = get("/v1beta1/news?" + urlencode(params))
        for a in payload.get("news") or []:
            if a.get("created_at") and start <= a["created_at"] < end:
                seen.add(a.get("id"))
        token = payload.get("next_page_token")
        if not token:
            break
    return len(seen)


def alpaca_get() -> Callable[[str], Any]:
    import requests

    from core import alpaca_news

    def get(path: str):
        for attempt in range(6):
            try:
                return alpaca_news._data_get_json(path)
            except requests.HTTPError as exc:
                code = getattr(exc.response, "status_code", None)
                if code == 429 or (code and code >= 500):
                    time.sleep(min(60, 5 * 2 ** attempt))
                    continue
                raise
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(min(60, 5 * 2 ** attempt))
        raise RuntimeError("Alpaca 뉴스 요청이 계속 실패함(429/5xx/연결)")
    return get


def month_counts(R, closes: pd.DataFrame, members_at, get) -> dict[str, dict]:
    days, cols = closes.index, list(closes.columns)
    px = closes.to_numpy(dtype=float)
    out: dict[str, dict] = {}
    for r in ES.month_rows(days):
        r = int(r)
        win, lose = extremes(px, days, cols, members_at, r)
        if not win:
            continue

        def one(r=r, win=win, lose=lose):
            s, e = window(days, r)
            return {"win": win, "lose": lose, "counts": {t: count_news(get, t, s, e) for t in sorted(set(win) | set(lose))}}

        out[str(days[r].date())] = R.stage(f"news_{days[r]:%Y%m}", one)
    return out


def split(m: dict) -> dict[str, list[str]]:
    c = m["counts"]
    med = float(np.median([c[t] for t in (*m["win"], *m["lose"])]))
    return {"W_NEWS": [t for t in m["win"] if c[t] > med], "W_QUIET": [t for t in m["win"] if c[t] <= med],
            "L_NEWS": [t for t in m["lose"] if c[t] > med], "L_QUIET": [t for t in m["lose"] if c[t] <= med],
            "W_ALL": list(m["win"]), "L_ALL": list(m["lose"]), "median": med}


class NewsPanel(ES.Panel):
    """earnings-surprise-v1 의 Panel 에 형성 규칙만 바꿔 끼운다(가격·편입·앞으로 수익·적립 계산은 그대로)."""

    def __init__(self, closes: pd.DataFrame, members_at, months: dict[str, dict], arm: str):
        super().__init__(pd.DataFrame({"ticker": [], "filed": pd.to_datetime([])}), closes, members_at)
        self.arm = arm
        self.sets = {k: split(v) for k, v in months.items()}

    def form(self, r: int) -> dict:
        if r in self._cache:
            return self._cache[r]
        out = {"top": [], "bottom": [], "universe": [], "n_eligible": 0, "ok": False}
        sets = self.sets.get(str(self.days[r].date()))
        if sets is not None:
            mem = self.members_at(self.days[r - 1].date())
            out["universe"] = [self.col[t] for t in mem if t in self.col and t != "SPY" and np.isfinite(self.raw[r, self.col[t]])]
            sel = sorted(self.col[t] for t in sets[self.arm] if t in self.col)
            out["n_eligible"] = len(sel)
            if len(sel) >= MIN_NAMES:
                out["top"], out["ok"] = sel, True
        self._cache[r] = out
        return out


# =================================================================================================
# 2. 합성 자료(스모크 — 네트워크 없음)
# =================================================================================================

def synthetic_inputs() -> dict:
    rng = np.random.default_rng(9)
    tickers = [f"T{i:02d}" for i in range(120)]
    days = pd.bdate_range("2013-01-02", "2022-12-30")
    mkt = rng.normal(0.0003, 0.01, len(days))
    cols = {"SPY": 100 * np.cumprod(1 + mkt)}
    for t in tickers:
        cols[t] = 50 * np.cumprod(1 + mkt * (0.8 + 0.4 * rng.random()) + rng.normal(0.0001, 0.02, len(days)))
    closes = pd.DataFrame(cols, index=days)
    closes.loc[closes.index >= "2018-03-01", "T07"] = np.nan

    def members_at(d: date) -> frozenset:
        return frozenset(tickers[:110] if d < date(2017, 1, 1) else tickers[10:])

    return {"closes": closes, "members_at": members_at, "tickers": tickers}


class FakeNews:
    """기사 수 = 종목·달 해시로 정한 0~120 건, 50건씩 쪽 나눔(next_page_token)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, path: str):
        from urllib.parse import parse_qs, urlparse

        self.calls += 1
        q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
        n = int(hashlib.sha256(f"{q['symbols']}{q['start'][:7]}".encode()).hexdigest(), 16) % 121
        page = int(q.get("page_token", "0"))
        lo, hi = page * PAGE_LIMIT, min(n, (page + 1) * PAGE_LIMIT)
        start = pd.Timestamp(q["start"])
        news = [{"id": f"{q['symbols']}-{q['start']}-{i}", "created_at": (start + pd.Timedelta(hours=1 + i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "headline": "h", "symbols": [q["symbols"]]} for i in range(lo, hi)]
        return {"news": news, "next_page_token": str(page + 1) if hi < n else None}


# =================================================================================================
# 3. 본문
# =================================================================================================

def judge_arm(R, closes, members_at, months, arm: str, power: dict) -> dict:
    P = NewsPanel(closes, members_at, months, arm)
    tab = ES.monthly_table(P)
    if tab.empty:
        return {"verdict": "NOT_EVALUABLE", "reason": "형성 가능한 달 없음", "months_formed": 0}
    old = ES.MAIN_H
    try:
        ES.MAIN_H = MAIN_H                       # 주 지표를 1개월로(매달 다시 짜는 설계와 맞춘다)
        ev = ES.event_test(tab, R.smoke)
    finally:
        ES.MAIN_H = old
    for h in ev.get("halves") or []:
        h["pass"] = bool(np.isfinite(h["mean_top_minus_univ"]) and h["mean_top_minus_univ"] > 0
                         and np.isfinite(h["p_one_sided"]) and h["p_one_sided"] < ALPHA)
    judge = tab[tab[f"end_{MAIN_H}"].notna() & (tab[f"end_{MAIN_H}"] <= ES.JUDGE_END)]
    x = (judge[f"top_{MAIN_H}"] - judge[f"univ_{MAIN_H}"]).to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    ev["observed_ir"] = float(x.mean() / x.std(ddof=1) * math.sqrt(12)) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")
    acc = ES.account_test(P, tab.index[0], R.smoke)
    halves = ev.get("halves") or []
    evaluable = (ev["n_months_judge"] >= ES.MIN_JUDGE_MONTHS and len(halves) == 2 and all(h["n"] >= 2 * ES.BLOCK_M for h in halves)
                 and acc["n_windows"]["judge"] >= ES.MIN_WINDOWS and ev.get("noop") is None)
    event_pass = bool(halves) and all(h["pass"] for h in halves)
    acc_pass = bool(acc.get("judge_TOP", {}).get("pass"))
    if not evaluable:
        verdict = "NOT_EVALUABLE"
    elif event_pass and acc_pass:
        verdict = "NEWS_EDGE"
    else:
        verdict = rp.classify_fail(ev.get("observed_ir"), power)
    return {"verdict": verdict, "event_pass": event_pass, "account_pass": acc_pass, "months_formed": int(len(tab)),
            "first_formation": str(tab.index[0].date()), "mean_names": float(tab["n_top"].mean()), "event_test": ev, "account": acc}


def body(R):
    if R.smoke:
        inp = synthetic_inputs()
        closes, members_at, tickers = inp["closes"], inp["members_at"], inp["tickers"]
        get = FakeNews()
        source = "synthetic (smoke)"
    else:
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
        except ImportError:
            pass
        from core import account_sync

        if not account_sync.credentials_available():
            raise RuntimeError("Alpaca 키가 환경에 없음(값은 출력하지 않음)")
        members_at, tickers = ES.sp500_members()
        closes = ES.load_prices_real(R, [t for t in tickers if t != "SPY"])
        get = alpaca_get()
        source = "Alpaca news API (Benzinga, created_at) + core.market_data adjusted close + fja05680 S&P 500 PIT membership"
    months = month_counts(R, closes, members_at, get)
    if not months:
        raise RuntimeError("형성 가능한 달이 없음")
    if R.smoke:
        calls = get.calls
        again = month_counts(R, closes, members_at, get)
        assert get.calls == calls and again.keys() == months.keys(), "기사 수 단계가 재사용되지 않음"
        assert any(max(m["counts"].values()) > PAGE_LIMIT for m in months.values()), "쪽 넘김 경로가 확인되지 않음"
    meds = [split(m)["median"] for m in months.values()]
    first = pd.Timestamp(min(months))
    power = rp.power_report(max((ES.JUDGE_END - first).days / 365.25, 0.0), len(JUDGED))
    arms = {arm: R.stage(f"arm_{arm}", lambda arm=arm: judge_arm(R, closes, members_at, months, arm, power)) for arm in ARMS}
    verdicts = {arm: arms[arm]["verdict"] for arm in JUDGED}
    verdicts.update({f"{arm}_report": arms[arm]["verdict"] for arm in REPORTED})
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    result = L.rnd({
        "id": JOB_ID, "judge_version": RULES_VERSION, "smoke": R.smoke, "source": source, "verdicts": verdicts,
        "power": power, "power_line": rp.power_line(power),
        "coverage": {"tickers_universe": len(tickers), "months": len(months), "first_month": min(months), "last_month": max(months),
                     "median_of_monthly_median_articles": float(np.median(meds)),
                     "zero_article_share": float(np.mean([v == 0 for m in months.values() for v in m["counts"].values()]))},
        "arms": arms,
        "rule": {"ret_days": RET_DAYS, "decile": DECILE, "min_names": MIN_NAMES, "max_pages": MAX_PAGES, "main_horizon": MAIN_H,
                 "judge_end": str(ES.JUDGE_END.date()), "boot": ES.BOOT, "block_months": ES.BLOCK_M, "alpha": ALPHA,
                 "win_years": ES.WIN_YEARS, "win_share_min": ES.WIN_SHARE_MIN, "median_irr_min": ES.MED_IRR_MIN}})
    return result, render(result)


def render(r: dict) -> str:
    v, P, cov = r["verdicts"], L.pct, r["coverage"]
    out = [f"# 크게 움직인 종목 — 뉴스와 함께면 이어 가고, 조용하면 되돌아오나 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "**판정:** " + " · ".join(f"{a} **{v[a]}**" for a in JUDGED) + " · (보고) " + " · ".join(f"{a} {v[a + '_report']}" for a in REPORTED), "",
           "통과는 '전진 원장 후보'일 뿐 엔진 채택이 아니다. 엔진은 바뀌지 않았다.", "", "## 규칙 (결과를 보기 전에 고정)", ""]
    out += [f"- {a}: {ARM_NOTE[a]}" for a in ARMS]
    out += [f"- NEWS_EDGE ⇔ 두 절반 모두 '무리 − 편입 종목 동일가중' {r['rule']['main_horizon']} 평균 > 0 & 부트스트랩 단측 p < {r['rule']['alpha']} "
            f"& 적립 5년 구간 이긴 비율 ≥ {r['rule']['win_share_min']:.0%} & IRR 차이 중앙값 ≥ +{r['rule']['median_irr_min'] * 100:.1f}%p.",
            f"- 검정력: {r['power_line']}", "", "## 자료", "", f"- {r['source']}",
            f"- 형성 달 {cov['months']}개({cov['first_month']} ~ {cov['last_month']}), 극단 무리 기사 수 중앙값(달별 중앙값의 중앙) {cov['median_of_monthly_median_articles']:.0f}건, "
            f"기사 0건 비율 {P(cov['zero_article_share'], nd=0)}", ""]
    for a in ARMS:
        x = r["arms"][a]
        out += [f"## {a}{' (보고만)' if a in REPORTED else ''} — {x['verdict']}", ""]
        if not x.get("months_formed"):
            out += [f"형성 가능한 달 없음({x.get('reason', '')})", ""]
            continue
        ev, acc = x["event_test"], x["account"]
        out.append(f"형성한 달 {x['months_formed']}개(첫 달 {x['first_formation']}), 달마다 평균 {x['mean_names']:.1f}종목, 판정 달 {ev['n_months_judge']}개 · 관측 IR {ev.get('observed_ir')}")
        out += ["", f"| 절반 | 기간 | 달 | {r['rule']['main_horizon']} '무리 − 편입 전체' 평균 | 단측 p | 통과 |", "|---|---|---|---|---|---|"]
        for h in ev.get("halves") or []:
            out.append(f"| {h['half']} | {h['first']} ~ {h['last']} | {h['n']} | {P(h['mean_top_minus_univ'], True, 2)} | {h['p_one_sided']} | {'예' if h['pass'] else '아니오'} |")
        out += ["", "| 구간 | 무리 평균 | 편입 전체 | SPY | 무리 − 편입 전체 | 무리 − SPY | 이긴 달 비율 |", "|---|---|---|---|---|---|---|"]
        for k, d in ev.get("by_horizon", {}).items():
            out.append(f"| {k} | {P(d['mean_top'], nd=2)} | {P(d['mean_univ'], nd=2)} | {P(d['mean_spy'], nd=2)} | {P(d['mean_top_minus_univ'], True, 2)} | "
                       f"{P(d['mean_top_minus_spy'], True, 2)} | {P(d['hit_top_vs_univ'], nd=0)} |")
        out += ["", "| 적립(매달 10만 원, 5년) | 구간 | 이긴 비율 | IRR 차이 중앙 | 통과 |", "|---|---|---|---|---|"]
        for k in ("judge_TOP", "judge_SAT", "post2024_10_report_TOP", "post2024_10_report_SAT"):
            s = acc.get(k) or {}
            if s.get("n_windows"):
                out.append(f"| {k} | {s['n_windows']} | {P(s['share_win'], nd=0)} | {P(s['median_diff_irr'], True, 2)}p | {'예' if s.get('pass') else '아니오'} |")
        out.append("")
    out += ["## 주의", "",
            "- 기사 수는 Alpaca(Benzinga) 기준이다. 매체 하나의 보도량이라 Chan(2003)의 다우존스 헤드라인과 다르다. 기사 수 많음 ≠ 중요한 뉴스.",
            "- 종목 가격은 Yahoo 캐시라 상장폐지 종목은 대개 가격이 없다(생존 편향). 2015~2024 는 한 시대뿐이다.",
            "- 적립 계좌는 매달 새 돈 10만 원으로 그달 무리만 사고 팔지 않는다(earnings-surprise-v1 과 같다). 1개월 검정은 매달 갈아타는 포트폴리오라 실제로 따라 하면 회전 비용·세금이 더 든다. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
