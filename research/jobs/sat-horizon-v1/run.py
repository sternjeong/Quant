"""검증 연구 sat-horizon-v1 (2026-11-15 사전 등록): 보유 기간마다, S&P 500 보다 7%p 이상 더 오를 새틀라이트 5종목을 가장 잘 고르는 규칙은?

사용자 목표(2026-11-15): "새틀라이트 종목을 최적으로 찾는 규칙 — 시장을 이기는 alpha 로. 안정성은 조금 버려도 수익 극대화,
도박은 아님. S&P 500 대비 최소 7% 이상 수익을 특정 기간 안에 올리는 종목. 기간 n 개를 정해 기간마다 맞는 선정 방법을 연구."

기간(사전 고정): 1·3·6·12개월(21·63·126·252거래일).
후보 규칙(이론 근거가 있는 것만, 결과를 보기 전에 고정 — 새 규칙을 더하려면 새 id):
    MOM12_1   12-1 모멘텀: px[r−22]/px[r−253] − 1 (Jegadeesh·Titman 1993)
    MOM6      6개월 모멘텀: px[r−1]/px[r−127] − 1
    HIGH52    52주 신고가 근접: px[r−1] / 최근 252일 최고 종가 (George·Hwang 2004)
    BREAKOUT  지금 챔피언 규칙의 종가판: 직전 종가가 그 전 20일 최고 종가를 넘은 종목 중 63일 수익 순(돌파 종목이 5개 미만이면 63일 수익 순으로 채움)
    VOLADJ    변동성 조정 모멘텀: MOM12_1 / 최근 252일 일수익 표준편차
    COMBO     MOM12_1 순위와 HIGH52 순위의 평균
    REV1M     단기 반전: 직전 21일 수익이 가장 낮은 종목(1개월 기간에 맞는 반대 가설)
    LOTTERY   (보고만, 도박 기준선) 최근 21일 최대 일수익이 가장 큰 종목(Bali·Cakici·Whitelaw 2011)
매달 첫 거래일 r 에, 그날 S&P 500 편입(fja05680 시점 기준) · r−1·r−253·r 가격이 있는 종목 중 점수 상위 5개를 r 종가에 같은 비중으로 사고
H 거래일 뒤 종가에 판다(그 사이 가격이 끊기면 마지막 가격). 결과 E = 5종목 평균 수익 − SPY 수익(같은 기간).
무작위 기준선: 같은 날 같은 후보에서 무작위 5종목(500회, 씨앗 고정)의 P(E ≥ 7%p)·평균.

판정(결과를 보기 전에 고정, 기간마다 하나씩, 판정 4개):
  1) 고르기 — 선택 구간(형성 2002-01 ~ 2012-12)에서 판정 규칙 7개 중 'E 중앙값 > 0'(도박이 아님)을 만족하는 것 가운데 평균 E 최대.
     만족하는 규칙이 없으면 그 기간은 NO_ELIGIBLE_RULE.
  2) 확인 — 확인 구간(형성 2013-01 ~, H 끝 ≤ 2024-09-30)에서 고른 규칙이
     (a) 평균 E ≥ +7%p (사용자 목표)
     (b) P(E ≥ 7%p) − 무작위 P(E ≥ 7%p) 의 평균 > 0, 이동 블록 부트스트랩(블록 max(12, H개월)달, 2,000회) 단측 p < 0.0125(0.05/4 기간)
     (c) E 중앙값 > 0 그리고 E > 0 인 달 비율 ≥ 50%(도박이 아님)
     (d) 생존편향 스트레스: 연 2%(기간 비례)를 깎아도 평균 E ≥ +7%p
     를 모두 만족하면 TARGET_MET. (b)(c)만 만족하면 SKILL_BELOW_TARGET(무작위보다 잘 고르지만 +7%p 에는 못 미침).
     나머지는 FAIL(관측 IR 이 최소 검출 효과보다 작으면 FAIL_UNDERPOWERED).
  2024-10 이후는 보고만. 통과는 '전진 원장 후보'일 뿐 엔진은 바뀌지 않는다(사용자 확인 뒤 별도 작업).
한계: 무료 가격(Yahoo 캐시)에 상장폐지 종목이 대개 없다 → 위험한 종목을 고르는 규칙에 유리한 생존편향(스트레스 (d)로 일부만 보정).
배당은 조정 종가에 들어 있고, 세금·수수료는 넣지 않았다(5종목 교체 비용은 보고).
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
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


ES = _load("earnings_surprise_v1", HERE.parent / "earnings-surprise-v1" / "run.py")  # 시점 기준 S&P 500 편입·가격 공급자
L = ES.L
from core import research_power as rp  # noqa: E402

JOB_ID = "sat-horizon-v1"
RULES_VERSION = "sat-horizon-v1/2026-11-15"
SEED = 20261116
PRICE_START = "2000-01-01"
FORM_START = pd.Timestamp("2002-01-01")
SELECT_END = pd.Timestamp("2012-12-31")     # 선택 구간: 형성일 ≤ 이 날
CONFIRM_START = pd.Timestamp("2013-01-01")
JUDGE_END = pd.Timestamp("2024-09-30")      # 확인 구간: 보유 끝 ≤ 이 날
HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
TOP_N = 5
TARGET = 0.07
JUDGED = ("MOM12_1", "MOM6", "HIGH52", "BREAKOUT", "VOLADJ", "COMBO", "REV1M")
REPORTED = ("LOTTERY",)
RULES = JUDGED + REPORTED
N_RANDOM = 500
BOOT = 2000
ALPHA = 0.05 / len(HORIZONS)
SURV_DRAG = 0.02                           # 연 2%
HIT0_MIN = 0.5
LOOKBACK = 253
MIN_NAMES = 50
PRICE_CHUNK = 50

RULE_NOTE = {
    "MOM12_1": "12-1 모멘텀(px[r−22]/px[r−253])",
    "MOM6": "6개월 모멘텀(px[r−1]/px[r−127])",
    "HIGH52": "52주 신고가 근접(px[r−1]/252일 최고)",
    "BREAKOUT": "20일 돌파 + 63일 수익 순(지금 챔피언 규칙의 종가판, 후보 풀만 다름)",
    "VOLADJ": "변동성 조정 12-1 모멘텀",
    "COMBO": "12-1 모멘텀 순위 + 52주 신고가 순위 평균",
    "REV1M": "단기 반전(직전 21일 최약)",
    "LOTTERY": "도박 기준선: 최근 21일 최대 일수익 최대(보고만)",
}


# =================================================================================================
# 1. 가격
# =================================================================================================

def load_prices_real(R, tickers: list[str]) -> pd.DataFrame:
    """SPY 달력 × 종목 조정 종가. earnings-surprise-v1 과 같은 공급자, 시작만 2000 년."""
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


# =================================================================================================
# 2. 점수와 고르기
# =================================================================================================

def formation_rows(days: pd.DatetimeIndex) -> list[int]:
    s = pd.Series(np.arange(len(days)), index=days)
    first = s.groupby([days.year, days.month]).min().to_numpy()
    return [int(r) for r in first if r >= LOOKBACK and days[r] >= FORM_START]


def scores(px: np.ndarray, r: int, cols: np.ndarray) -> dict[str, np.ndarray]:
    """후보 열(cols)의 규칙별 점수(클수록 먼저 고름). px 는 날짜×종목 가격(NaN 가능)."""
    p1, p22, p127, p253 = px[r - 1, cols], px[r - 22, cols], px[r - 127, cols], px[r - 253, cols]
    win = px[r - 252:r, cols]
    with np.errstate(divide="ignore", invalid="ignore"):
        hi = np.nanmax(win, axis=0)
        mom12 = p22 / p253 - 1
        mom6 = p1 / p127 - 1
        high52 = p1 / hi
        dret = win[1:] / win[:-1] - 1
        vol = np.nanstd(dret, axis=0)
        voladj = mom12 / vol
        ret21 = p1 / p22 - 1
        maxret = np.nanmax(px[r - 21:r, cols][1:] / px[r - 21:r, cols][:-1] - 1, axis=0)
        prior20 = np.nanmax(px[r - 21:r - 1, cols], axis=0)
        brk = p1 > prior20
        mom63 = p1 / px[r - 64, cols] - 1
    breakout = np.where(brk, 1e6 + np.nan_to_num(mom63, nan=-1e6), np.nan_to_num(mom63, nan=-1e9))
    rank = lambda a: pd.Series(a).rank(method="average", na_option="keep").to_numpy()  # noqa: E731
    combo = (rank(mom12) + rank(high52)) / 2
    return {"MOM12_1": mom12, "MOM6": mom6, "HIGH52": high52, "BREAKOUT": breakout, "VOLADJ": voladj, "COMBO": combo,
            "REV1M": -ret21, "LOTTERY": maxret}


def top_n(score: np.ndarray, n: int = TOP_N) -> np.ndarray:
    """유한한 점수 중 상위 n 개의 위치(동점은 앞 열 먼저). 유한한 것이 n 개 미만이면 빈 배열."""
    ok = np.flatnonzero(np.isfinite(score))
    if len(ok) < n:
        return np.array([], dtype=int)
    order = ok[np.lexsort((ok, -score[ok]))]
    return order[:n]


def fwd_returns(px: np.ndarray, r: int, h: int, cols: np.ndarray) -> np.ndarray:
    """r 종가 → r+h 종가 수익. 그 사이 가격이 끊기면 r+h 이전 마지막 가격."""
    end = min(r + h, px.shape[0] - 1)
    seg = px[r:end + 1, cols]
    last = pd.DataFrame(seg).ffill().to_numpy()[-1]
    return last / px[r, cols] - 1


def build_table(px: np.ndarray, days: pd.DatetimeIndex, tickers: list[str], members_at: Callable[[date], frozenset],
                spy_col: int, check: Callable[[], None] = lambda: None) -> dict[str, pd.DataFrame]:
    """{H: DataFrame(index=형성일, 열: <규칙>(E), rand_hit7, rand_mean, n_names, picks_<규칙>)}."""
    col_of = {t: i for i, t in enumerate(tickers)}
    rng = np.random.default_rng(SEED)
    rows = {h: [] for h in HORIZONS}
    for r in formation_rows(days):
        check()
        mem = members_at(days[r].date())
        cols = np.array(sorted(col_of[t] for t in mem if t in col_of and col_of[t] != spy_col), dtype=int)
        if len(cols) == 0:
            continue
        ok = np.isfinite(px[r - 1, cols]) & np.isfinite(px[r - 253, cols]) & np.isfinite(px[r, cols])
        cols = cols[ok]
        if len(cols) < MIN_NAMES:
            continue
        sc = scores(px, r, cols)
        picks = {k: top_n(v) for k, v in sc.items()}
        for name, h in HORIZONS.items():
            if r + h >= px.shape[0]:
                continue
            fr = fwd_returns(px, r, h, cols)
            spy = px[r + h, spy_col] / px[r, spy_col] - 1
            if not np.isfinite(spy):
                continue
            ex = fr - spy
            valid = np.isfinite(ex)
            row = {"date": days[r], "end": days[r + h], "n_names": int(valid.sum()), "spy": float(spy)}
            for k, idx in picks.items():
                row[k] = float(np.nanmean(ex[idx])) if len(idx) else np.nan
                row[f"hit_stock_{k}"] = float(np.nanmean(ex[idx] >= TARGET)) if len(idx) else np.nan
                row[f"picks_{k}"] = ",".join(tickers[cols[i]] for i in idx)
            pool = np.flatnonzero(valid)
            if len(pool) >= TOP_N:
                pick = np.argpartition(rng.random((N_RANDOM, len(pool))), TOP_N, axis=1)[:, :TOP_N]  # 행마다 겹치지 않는 5개
                draws = ex[pool][pick].mean(axis=1)
                row["rand_hit7"] = float(np.mean(draws >= TARGET))
                row["rand_mean"] = float(np.mean(draws))
                row["univ_mean"] = float(np.mean(ex[pool]))
                row["univ_hit7_stock"] = float(np.mean(ex[pool] >= TARGET))
            rows[name].append(row)
    return {h: pd.DataFrame(v).set_index("date") if v else pd.DataFrame() for h, v in rows.items()}


# =================================================================================================
# 3. 판정
# =================================================================================================

def block_boot_p(d: np.ndarray, block: int, seed: int, n: int = BOOT) -> float:
    """평균 > 0 단측 p(이동 블록, 중심화)."""
    d = d[np.isfinite(d)]
    if len(d) < max(2 * block, 12):
        return float("nan")
    rng = np.random.default_rng(seed)
    obs = d.mean()
    c = d - obs
    nb = int(np.ceil(len(d) / block))
    starts_max = len(d) - block
    sims = np.empty(n)
    for i in range(n):
        st = rng.integers(0, starts_max + 1, nb)
        sims[i] = np.concatenate([c[s:s + block] for s in st])[:len(d)].mean()
    return float((np.sum(sims >= obs) + 1) / (n + 1))


def summarize(t: pd.DataFrame, rule: str) -> dict[str, Any]:
    e = t[rule].dropna()
    if e.empty:
        return {"n": 0}
    return {"n": int(len(e)), "mean": float(e.mean()), "median": float(e.median()), "hit7": float((e >= TARGET).mean()),
            "hit0": float((e > 0).mean()), "p10": float(e.quantile(0.1)), "p90": float(e.quantile(0.9)),
            "rand_hit7": float(t.loc[e.index, "rand_hit7"].mean()), "rand_mean": float(t.loc[e.index, "rand_mean"].mean()),
            "stock_hit7": float(t.loc[e.index, f"hit_stock_{rule}"].mean()),
            "univ_stock_hit7": float(t.loc[e.index, "univ_hit7_stock"].mean())}


def split(t: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"select": t[t.index <= SELECT_END],
            "confirm": t[(t.index >= CONFIRM_START) & (t["end"] <= JUDGE_END)],
            "post": t[t["end"] > JUDGE_END]}


def judge_horizon(name: str, t: pd.DataFrame, power: dict) -> dict[str, Any]:
    h = HORIZONS[name]
    parts = split(t)
    table = {p: {k: summarize(df, k) for k in RULES} for p, df in parts.items() if not df.empty}
    sel = table.get("select", {})
    eligible = [k for k in JUDGED if sel.get(k, {}).get("n") and sel[k]["median"] > 0]
    out: dict[str, Any] = {"horizon_days": h, "table": table, "eligible_in_selection": eligible}
    if not eligible:
        out["verdict"] = "NO_ELIGIBLE_RULE"
        return out
    chosen = max(eligible, key=lambda k: (sel[k]["mean"], -JUDGED.index(k)))
    out["chosen"] = chosen
    conf = parts["confirm"]
    if conf.empty or conf[chosen].dropna().size < 24:
        out["verdict"] = "NOT_EVALUABLE"
        out["reason"] = "확인 구간 형성 달 24 미만"
        return out
    c = table["confirm"][chosen]
    d = ((conf[chosen] >= TARGET).astype(float) - conf["rand_hit7"]).to_numpy()
    block = max(12, h // 21)
    p = block_boot_p(d, block, SEED + h)
    years = h / 252
    stressed = c["mean"] - SURV_DRAG * years
    active = (conf[chosen] - conf["rand_mean"]).to_numpy()
    ir = float(np.mean(active) / np.std(active) * np.sqrt(252 / h)) if np.std(active) > 0 else None
    checks = {"a_mean_ge_target": c["mean"] >= TARGET,
              "b_hit7_beats_random": bool(np.isfinite(p) and np.mean(d) > 0 and p < ALPHA),
              "c_not_gambling": c["median"] > 0 and c["hit0"] >= HIT0_MIN,
              "d_survivorship_stress": stressed >= TARGET}
    if all(checks.values()):
        verdict = "TARGET_MET"
    elif checks["b_hit7_beats_random"] and checks["c_not_gambling"]:
        verdict = "SKILL_BELOW_TARGET"
    else:
        verdict = rp.classify_fail(ir, power)
    noop = rp.noop_guard(active.tolist())
    if noop:
        verdict, out["reason"] = "NOT_EVALUABLE", noop
    out.update({"verdict": verdict, "checks": checks, "hit7_minus_random_mean": float(np.mean(d)), "p_one_sided": p,
                "block_months": block, "stressed_mean": stressed, "observed_ir_vs_random": ir,
                "latest_picks": {"date": str(t.index[-1].date()), "tickers": t[f"picks_{chosen}"].iloc[-1]},
                "turnover_avg": turnover(t, chosen)})
    return out


def turnover(t: pd.DataFrame, rule: str) -> float:
    """연속 형성 사이 5종목 중 바뀐 비율의 평균(보고)."""
    sets = [set(x.split(",")) for x in t[f"picks_{rule}"].fillna("") if x]
    ch = [1 - len(a & b) / TOP_N for a, b in zip(sets, sets[1:])]
    return float(np.mean(ch)) if ch else float("nan")


# =================================================================================================
# 4. 스모크 자료
# =================================================================================================

def synthetic_inputs(seed: int = 3) -> dict[str, Any]:
    """모멘텀이 이어지는 가짜 시장(판정 경로 확인용). 150종목, 2000~2025."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2000-01-03", "2025-06-30")
    n = 150
    drift = np.zeros((len(days), n))
    regime = rng.normal(0, 0.0012, n)
    for i in range(len(days)):
        if i % 126 == 0:
            regime = 0.7 * regime + rng.normal(0, 0.0008, n)
        drift[i] = regime
    rets = drift + rng.normal(0, 0.015, (len(days), n))
    px = 50 * np.exp(np.cumsum(rets, axis=0))
    spy = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(days))))
    tickers = [f"T{i:03d}" for i in range(n)]
    closes = pd.DataFrame(px, index=days, columns=tickers)
    closes["SPY"] = spy
    closes.iloc[:300, 7] = np.nan  # 늦게 상장
    members = frozenset(tickers)
    return {"closes": closes, "members_at": lambda d: members, "tickers": tickers}


# =================================================================================================
# 5. 본문
# =================================================================================================

def body(R):
    if R.smoke:
        inp = synthetic_inputs()
        closes, members_at, tickers = inp["closes"], inp["members_at"], inp["tickers"]
        source = "synthetic (smoke)"
    else:
        members_at, tickers = ES.sp500_members()
        closes = load_prices_real(R, [t for t in tickers if t != "SPY"])
        source = "core.market_data 조정 종가(Yahoo 캐시) + fja05680 S&P 500 시점 기준 구성종목"
    cols = list(closes.columns)
    px = closes.to_numpy(dtype=float)
    days = closes.index
    tables = R.stage("tables", lambda: build_table(px, days, cols, members_at, cols.index("SPY"), R.check_time))
    if all(t.empty for t in tables.values()):
        raise RuntimeError("형성 가능한 달이 없음")
    conf_years = max((JUDGE_END - CONFIRM_START).days / 365.25, 0.0)
    power = rp.power_report(conf_years, len(HORIZONS))
    res = {h: judge_horizon(h, tables[h], power) for h in HORIZONS}
    verdicts = {h: res[h]["verdict"] + (f"({res[h]['chosen']})" if res[h].get("chosen") else "") for h in HORIZONS}
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    first = min(t.index.min() for t in tables.values() if not t.empty)
    result = L.rnd({
        "id": JOB_ID, "judge_version": RULES_VERSION, "smoke": R.smoke, "source": source, "verdicts": verdicts,
        "power": power, "power_line": rp.power_line(power),
        "coverage": {"tickers_with_prices": len(cols) - 1, "tickers_universe": len(tickers), "first_formation": str(first.date()),
                     "months": {h: int(len(t)) for h, t in tables.items()},
                     "median_names": {h: float(t["n_names"].median()) for h, t in tables.items() if not t.empty}},
        "horizons": res,
        "rule": {"top_n": TOP_N, "target": TARGET, "judged": list(JUDGED), "reported": list(REPORTED), "select_end": str(SELECT_END.date()),
                 "confirm_start": str(CONFIRM_START.date()), "judge_end": str(JUDGE_END.date()), "alpha": ALPHA, "boot": BOOT,
                 "n_random": N_RANDOM, "survivorship_drag": SURV_DRAG, "hit0_min": HIT0_MIN, "seed": SEED}})
    return result, render(result)


def render(r: dict) -> str:
    P = L.pct
    v = r["verdicts"]
    out = [f"# 새틀라이트 5종목 — 기간별로 S&P 500 을 7%p 넘게 이기는 고르기 규칙 ({r['judge_version']})"
           + (" — 스모크(가짜 데이터)" if r["smoke"] else ""), "",
           "**판정:** " + " · ".join(f"{h} **{v[h]}**" for h in HORIZONS), "",
           "통과는 '전진 원장 후보'일 뿐 엔진 채택이 아니다. 엔진은 바뀌지 않았다.", "", "## 규칙 (결과를 보기 전에 고정)", ""]
    out += [f"- {k}: {RULE_NOTE[k]}" for k in RULES]
    out += [f"- 매달 첫 거래일, 시점 기준 S&P 500 편입 종목 중 상위 {r['rule']['top_n']}개 같은 비중, 기간 끝 종가에 매도. E = 5종목 평균 − SPY.",
            f"- 고르기: 선택 구간(형성 ~{r['rule']['select_end']})에서 E 중앙값 > 0 인 판정 규칙 중 평균 E 최대.",
            f"- TARGET_MET = 확인 구간(형성 {r['rule']['confirm_start']}~, 끝 ≤ {r['rule']['judge_end']}) (a) 평균 E ≥ +7%p (b) P(E≥7%p) 가 무작위 5종목보다 높음, "
            f"블록 부트스트랩 단측 p < {r['rule']['alpha']:.4f} (c) E 중앙값 > 0, E>0 비율 ≥ 50% (d) 연 2% 생존편향 차감 후에도 평균 E ≥ +7%p. "
            "(b)(c)만이면 SKILL_BELOW_TARGET.", f"- {r['power_line']}", "", "## 자료", "", f"- {r['source']}",
            f"- 첫 형성 {r['coverage']['first_formation']}, 기간별 형성 달 {r['coverage']['months']}, 후보 수 중앙값 {r['coverage'].get('median_names')}", ""]
    for h, x in r["horizons"].items():
        out += [f"## {h} ({x['horizon_days']}거래일) — {x['verdict']}" + (f" · 고른 규칙 {x['chosen']}" if x.get("chosen") else ""), ""]
        if x.get("checks"):
            ck = x["checks"]
            out.append(f"관문: (a) {'통과' if ck['a_mean_ge_target'] else '미달'} · (b) {'통과' if ck['b_hit7_beats_random'] else '미달'}"
                       f"(차이 {P(x['hit7_minus_random_mean'], True, 1)}p, p={x['p_one_sided']}) · (c) {'통과' if ck['c_not_gambling'] else '미달'}"
                       f" · (d) {'통과' if ck['d_survivorship_stress'] else '미달'}(차감 후 평균 {P(x['stressed_mean'], True, 1)}) · 무작위 대비 관측 IR {x['observed_ir_vs_random']}")
            out.append(f"최근 고른 종목({x['latest_picks']['date']}): {x['latest_picks']['tickers']} · 평균 교체율 {P(x['turnover_avg'], nd=0)}")
        if x.get("reason"):
            out.append(f"사유: {x['reason']}")
        for part, label in (("select", "선택 구간"), ("confirm", "확인 구간"), ("post", "2024-10 이후(보고)")):
            tb = x["table"].get(part)
            if not tb:
                continue
            out += ["", f"**{label}**", "", "| 규칙 | 달 | 평균 E | 중앙 E | P(E≥7%p) | 무작위 P | E>0 | 하위 10% | 상위 10% | 종목별 P(≥7%p) |",
                    "|---|---|---|---|---|---|---|---|---|---|"]
            for k in RULES:
                s = tb.get(k) or {}
                if not s.get("n"):
                    continue
                star = " ★" if k == x.get("chosen") else ""
                out.append(f"| {k}{star} | {s['n']} | {P(s['mean'], True, 1)} | {P(s['median'], True, 1)} | {P(s['hit7'], nd=0)} | {P(s['rand_hit7'], nd=0)} | "
                           f"{P(s['hit0'], nd=0)} | {P(s['p10'], True, 1)} | {P(s['p90'], True, 1)} | {P(s['stock_hit7'], nd=0)} (전체 {P(s['univ_stock_hit7'], nd=0)}) |")
        out.append("")
    out += ["## 주의", "",
            "- 상장폐지 종목은 무료 가격에 대개 없어 생존편향이 있다. 위험한 종목을 고르는 규칙일수록 실제보다 좋아 보인다((d)는 일부 보정).",
            "- 세금·수수료 미반영. 매달 새로 고르는 '형성' 단위 결과라, 기간이 겹치는 달들은 독립이 아니다(블록 부트스트랩으로 반영).",
            "- 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
