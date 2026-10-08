"""검증 연구 dip-rnd-v1: 초대형 우량주(빅테크 등)를 '많이 눌렸을 때 줍기' — 단독으로 챔피언을 이기나, 챔피언에 더하면 나아지나. (사전 등록, 2026-10-08)

동기(사용자 관찰): 챔피언 성과 화면을 보면 구글 같은 빅테크를 눌렸을 때 사기만 해도 챔피언을 이길 것 같다.
위험: '지금 보니 승자'인 종목을 고르면 사후편향으로 거의 무엇이든 좋아 보인다. 그래서 후보는 **그 시점** 시가총액 상위만 쓴다
(2010 년이면 XOM·GE·WMT 도 들어가고, 이후 무너진 대형주도 남는다). 사후편향 크기는 판정과 무관한 진단(D1)으로 따로 보여 준다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
데이터 3분할: 개발(2010-08 ~ 2019-12) / 검증(2020-01 ~ 떼어 둔 구간 직전) / 떼어 둔 마지막 2년(최종 판정에서 한 번만).
풀(그 시점 S&P500 편입 종목 중 그 시점 시총 근사 = 발행주식수 이력 × 종가, 반기 1·7월 갱신, 코어 자산 제외):
  mega10 = 시총 상위 10, mega20 = 상위 20, megatech10 = 정보기술·커뮤니케이션·경기소비재 섹터 안 상위 10(섹터는 현재 GICS 분류).
  한 회사 한 칸: 2종 주식(GOOG/GOOGL 등)은 대표 하나만. 이름이 바뀐 종목은 지금 이름으로 가격을 읽는다(FB→META 등) —
  가격 소스에 옛 이름(FB) 이력이 없어 2013~2022 Facebook 이 빠지는 문제를 사전 점검에서 발견해 결과를 보기 전에 고정(2026-10-08).
  시총은 pit_cap()(이 스크립트)으로 계산한다: core.point_in_time_market_cap 은 발행주식수 이력(2015 말부터)보다 이른 날짜에
  2015 값에 그 날짜 이후 모든 분할 배수를 곱해, 이력 시작 전 분할(AAPL 2014 7:1, GOOGL 2014)을 두 번 센다
  (2014-01 AAPL 3.1조 달러 ≈ 실제의 6배, GOOGL 2배). 여기서는 이력 시작 전이면 '이력 시작일 이후' 분할만 곱한다(사전 점검에서 발견·고정).
눌림 규칙(종목마다, 그날 종가로 결정·다음 날부터 보유):
  dd = 종가 / 직전 252 거래일 최고 종가 − 1. 진입: dd ≤ −X (X ∈ 10·15·20·30%).
  필터 F: none | winner3y(진입일 종가 > 756 거래일 전 종가 — 눌렸어도 3년 전보다는 높은 '장기 승자'만).
  청산 E: recover(dd ≥ −2%, 거의 전고점 회복) | hold126(진입 후 126 거래일) | recover_or_252(회복 또는 252 거래일 중 먼저).
  청산 뒤에는 dd > −X 로 한 번 올라온 뒤에야 다시 진입할 수 있다(시간 청산 직후 같은 눌림에 바로 재진입 금지).
  보유 칸 K ∈ {3, 5}: 눌린 종목이 K 개 이하면 각 1/K, 더 많으면 동일가중. 풀에서 빠진 종목은 그날 판다.
  남는 돈 I ∈ {bil(단기국채), spy(SPY 보유)}.
R1 = 풀 3 × X 4 × F 2 × E 3 × K 2 × I 2 = 288개.
R2 한계 돌파: R1 중 검증 구간 샤프가 같은 풀 '그냥 동일가중 보유'보다 높은 것 개발 샤프 상위 최대 8개(없으면 개발 상위 5개)
  × 7변형: 진입 국면 게이트 3(시장 강세장일 때만·약세장일 때만·VIX>20 일 때만 새로 진입), X ±5%p, K 절반·두 배.
R3 결합: R1+R2 중 개발 샤프 > 0 인 것에서 검증 샤프 상위 3개 × 3결합
  (새틀라이트 대신 15% = 코어 85 + 눌림 15 / 코어 70 + 새틀라이트 15 + 눌림 15 / 코어 55 + 새틀라이트 15 + 눌림 30).
판정 dip-judge/v1 (tech-judge/v1 과 같은 관문, 가족: 단독=R1+R2, 결합=R3, 비교 대상은 둘 다 현 챔피언 = 코어 85 + 새틀라이트 15):
  1) 승자 = 개발+검증(IS) 샤프 최고 2) 승자의 챔피언 대비 초과의 DSR ≥ 0.95 — 시도 수 = 이 연구 전체(R1+R2+R3)
  3) CSCV PBO ≤ 25% 4) 떼어 둔 2년 샤프 > 챔피언
  5) (단독 가족만) 타이밍 관문: 승자 IS 샤프 > 같은 풀 그냥 동일가중 보유 IS 샤프 — '눌림을 기다린 것'이 '그냥 들고 있기'보다 나아야 한다.
  모두 만족 = CANDIDATE(사람 검토), 아니면 KEEP_CURRENT. 샤프·DSR·PBO 는 단기국채(BIL) 대비 초과수익으로 계산.
진단(판정과 무관, 보고용): D1 사후편향 — 오늘 시총 상위 10 을 전 기간 풀로 쓴 같은 규칙·그냥 보유(실제로는 불가능한 전략),
  연도별 수익(승자·챔피언·SPY·풀 보유), 국면별 초과, 그 시점 풀 구성.
비용 편도 8bp. 한계: 일봉, 상장폐지 결측(생존편향 일부 남음), 세금·환전 미반영, 시총은 근사, 섹터는 현재 분류.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import champion_strategy as cs  # noqa: E402
from core import core_lab as cl  # noqa: E402
from core import satellite_lab as sl  # noqa: E402
from core import sprint_lab as sp  # noqa: E402
from core import technical_lab as tl  # noqa: E402

JOB_ID = "dip-rnd-v1"
JUDGE_VERSION = "dip-judge/v1"
POOLS = ("mega10", "mega20", "megatech10")
POOL_N = {"mega10": 10, "mega20": 20, "megatech10": 10}
TECH_SECTORS = {"Information Technology", "Communication Services", "Consumer Discretionary"}
DIPS = (0.10, 0.15, 0.20, 0.30)
FILTERS = ("none", "winner3y")
EXITS = ("recover", "hold126", "recover_or_252")
KS = (3, 5)
IDLES = ("bil", "spy")
RECOVER_DD = -0.02
HINDSIGHT = "hindsight10"
# 구성종목 CSV 의 옛 이름 → 가격 소스(yfinance)의 지금 이름. 시총 상위에 들 만한 것 위주.
ALIASES = {"FB": "META", "ANTM": "ELV", "FISV": "FI", "ABC": "COR", "WLTW": "WTW", "PKI": "RVTY", "FLT": "CPAY",
           "COG": "CTRA", "RE": "EG", "HFC": "DINO"}
# 같은 회사의 다른 주식 종류 → 대표(대표가 같이 편입돼 있으면 이쪽을 뺀다).
DUAL_CLASS = {"GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA", "UA": "UAA", "DISCK": "DISCA", "DISCB": "DISCA",
              "BF-A": "BF-B", "LEN-B": "LEN", "HEI-A": "HEI", "BRK-A": "BRK-B"}
COMMON = "2010-08-01"
EXIT_IN_PROGRESS = 3


def log(m):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {m}", flush=True)


def deadline() -> float:
    raw = os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH")
    return (float(raw) if raw else time.time() + 3 * 3600) - 120


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def p(self, key: str) -> Path:
        return self.root / (key.replace("/", "_").replace("|", "__").replace(":", "_").replace(".", "p") + ".npy")

    def has(self, key):
        return self.p(key).exists()

    def save(self, key, arr):
        tmp = self.p(key).with_suffix(".tmp.npy")
        np.save(tmp, np.asarray(arr, dtype=np.float32))
        os.replace(tmp, self.p(key))

    def load(self, key):
        return np.load(self.p(key)).astype(float)

    def json(self, name, obj=None):
        f = self.root / f"{name}.json"
        if obj is None:
            return json.loads(f.read_text()) if f.exists() else None
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str))
        os.replace(tmp, f)


# ---------------------------------------------------------------- 풀(그 시점 시총 상위)
def make_pool_provider(cache: Path):
    """mega10/mega20/megatech10 은 반기 기준일의 그 시점 시총 순위, champion40·sp500_pit 는 새틀라이트 연구실과 같은 풀."""
    from core import hypothesis_engine as he

    base = sl.default_pool_provider()
    cache.mkdir(parents=True, exist_ok=True)
    memo: dict = {}
    exclude = set(cs.CORE_UNIVERSE) | {cs.MARKET_FILTER_TICKER}

    def sectors() -> dict:
        if "sectors" not in memo:
            from core import screener

            u = screener.get_universe(use_cache=True)
            memo["sectors"] = {he.price_symbol(str(s)): sec for s, sec in zip(u["Symbol"], u["Sector"])}
        return memo["sectors"]

    def ranked(anchor: date) -> list[list]:
        path = cache / f"rank_{anchor.isoformat()}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        from bisect import bisect_right

        dates, members = he._sp500_rows()
        i = bisect_right(dates, anchor) - 1
        names = {ALIASES.get(he.price_symbol(t), he.price_symbol(t)) for t in (members[i] if i >= 0 else ())}
        tickers = sorted(t for t in names - exclude if not (t in DUAL_CLASS and DUAL_CLASS[t] in names))
        caps = pit_caps(tickers, anchor)
        sec = sectors()
        rows = sorted(([t, float(c), sec.get(t, "Unknown")] for t, c in caps.items() if c), key=lambda r: -r[1])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows), encoding="utf-8")
        os.replace(tmp, path)
        return rows

    def provider(pool_type: str, d: date) -> list[str]:
        if pool_type in ("champion40", "sp500_pit"):
            return base(pool_type, d)
        if pool_type == HINDSIGHT:  # 진단 D1 전용: 오늘 기준 상위 10 을 과거 전체에 그대로(불가능한 전략)
            return [r[0] for r in ranked(sl._anchor(date.today()))[:10]]
        rows = ranked(sl._anchor(d))
        if pool_type == "megatech10":
            rows = [r for r in rows if r[2] in TECH_SECTORS]
        return [r[0] for r in rows[:POOL_N[pool_type]]]

    return provider


def pit_cap(ticker: str, anchor: date):
    """그 시점 시총 근사 = 그 시점 발행주식수(분할 보정) × 그 시점 종가(분할 조정 가격). 계산 불가면 None."""
    from core import point_in_time_market_cap as pit
    from core.market_data import get_price_history

    sh = pit.get_shares_outstanding_history(ticker)
    if sh.empty:
        return None
    ts = pd.Timestamp(anchor)
    prior = sh[sh.index <= ts]
    if prior.empty:  # 이력 시작 전: 시작일 값을 쓰고 시작일 이후 분할만 곱한다(그 전 분할은 이미 그 값에 반영됨)
        shares = float(sh.iloc[0]) * pit._cumulative_split_factor_after(ticker, sh.index[0])
    else:
        shares = float(prior.iloc[-1]) * pit._cumulative_split_factor_after(ticker, ts)
    px = get_price_history(ticker, start=(ts - pd.DateOffset(days=10)).date().isoformat(),
                           end=(ts + pd.DateOffset(days=1)).date().isoformat(), interval="1d")
    if px is None or px.empty or "Close" not in px.columns:
        return None
    px = px[px.index <= ts]
    return float(px["Close"].iloc[-1]) * shares if not px.empty else None


def pit_caps(tickers: list[str], anchor: date) -> dict:
    from concurrent.futures import ThreadPoolExecutor

    def one(t):
        try:
            return pit_cap(t, anchor)
        except Exception:  # noqa: BLE001 - 계산 불가 종목은 후보에서 빠진다
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        return dict(zip(tickers, ex.map(one, tickers)))


# ---------------------------------------------------------------- 눌림 포지션
def dip_position(close: pd.Series, x: float, filt: str, exit_: str, entry_gate: pd.Series | None = None) -> pd.Series:
    """사전 등록 규칙의 0/1 목표 포지션(그날 종가 기준). 상태 기계: 진입 → 청산 → dd > −X 로 재무장 → 다시 진입 가능."""
    c = close.astype(float)
    hi = c.rolling(252, min_periods=126).max()
    dd = (c / hi - 1.0).to_numpy()
    entry = dd <= -x
    if filt == "winner3y":
        entry &= (c > c.shift(756)).to_numpy()
    if entry_gate is not None:
        entry &= entry_gate.reindex(c.index).fillna(False).to_numpy(dtype=bool)
    max_hold = {"recover": None, "hold126": 126, "recover_or_252": 252}[exit_]
    use_recover = exit_ in ("recover", "recover_or_252")
    out = np.zeros(len(c))
    inside, armed, held = False, True, 0
    for i in range(len(c)):
        if np.isnan(dd[i]):
            continue
        if inside:
            held += 1
            if (use_recover and dd[i] >= RECOVER_DD) or (max_hold and held >= max_hold):
                inside, armed = False, dd[i] > -x
            else:
                out[i] = 1.0
                continue
        if not armed and dd[i] > -x:
            armed = True
        if armed and entry[i]:
            inside, armed, held = True, False, 0
            out[i] = 1.0
    return pd.Series(out, index=c.index)


def positions(data, x, filt, exit_, days, tickers, gate=None) -> pd.DataFrame:
    cols = {}
    for t in tickers:
        df = data.ohlcv.get(t)
        if df is None or len(df) < 130:
            continue
        cols[t] = dip_position(df["Close"], x, filt, exit_, gate).reindex(days).ffill().fillna(0.0)
    return pd.DataFrame(cols, index=days).fillna(0.0)


def cfg_key(rnd, pt, x, filt, exit_, k, idle, extra=""):
    return f"{rnd}|{pt}|x{int(round(x * 100))}|{filt}|{exit_}|k{k}|{idle}" + (f"|{extra}" if extra else "")


def parse_key(key):
    p = key.split("|")
    return {"pool": p[1], "x": int(p[2][1:]) / 100, "filt": p[3], "exit": p[4], "k": int(p[5][1:]), "idle": p[6]}


# ---------------------------------------------------------------- 데이터·기준선
def load_all(smoke: bool, ck: Path):
    pool_types = set(POOLS) | {"champion40", HINDSIGHT}
    if smoke:
        pp, base = sl.synthetic_providers(n_tickers=30, start="2006-01-01", end="2016-12-30")
        names = sorted(base("sp500_pit", None))

        def poolp(pt, d):
            return {"mega10": names[:10], "mega20": names[:20], "megatech10": names[5:15],
                    HINDSIGHT: names[-10:]}.get(pt) or base(pt, d)

        data = sl.build_data(pool_types, start="2008-01-01", end="2016-12-30", pool_provider=poolp, price_provider=pp)
        for df in data.ohlcv.values():
            df["Adj Close"] = df["Close"]
        idx = data.trading_days
        spy = pp("SPY", "2006-01-01", "2017-01-01")["Close"]
        vix = pd.Series(18 + 6 * np.sin(np.arange(len(idx)) / 40.0), index=idx)
        bil = pd.Series(0.0001, index=idx)
        core = pd.Series(np.random.default_rng(1).normal(0.0003, 0.008, len(idx)), index=idx)
        return data, spy, spy, vix, bil, core
    data = sl.build_data(pool_types, start="2008-01-01", pool_provider=make_pool_provider(ck / "pools"), log=log)
    from core.market_data import get_price_history

    s = get_price_history("SPY", start="2007-01-01", interval="1d")
    spy, spy_total = s["Close"], (s["Adj Close"] if "Adj Close" in s else s["Close"])
    vix = get_price_history("^VIX", start="2007-01-01", interval="1d")["Close"]
    b = get_price_history("BIL", start="2007-01-01", interval="1d")
    bil = (b["Adj Close"] if "Adj Close" in b else b["Close"]).pct_change(fill_method=None)
    price, total = _load_core()
    core = cl.run(price[0], price[1], cl.CoreConfig(cash="bil"), "2008-01-01", total=total)
    return data, spy, spy_total, vix, bil, core


def _load_core():
    tickers = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    from core.market_data import get_multiple_price_history

    hist = get_multiple_price_history(tickers, start="2006-01-01", end=None, interval="1d")
    names = [t for t in tickers if t in hist and not hist[t].empty]
    price = cs._closes_from_histories(hist, names)
    total = cs._closes_from_histories(hist, names, field=cs.CORE_PRICE_FIELD)
    core = [t for t in cs.CORE_UNIVERSE if t in names]
    ex = [t for t in (cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF) if t in names]
    return (price[core], price[ex]), (total[core], total[ex])


def satellite_positions(data, days, tickers) -> pd.DataFrame:
    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    sched = sl.run_variant(spec, spec["signal"]["params_grid"][0], sl.load_signal(code), data)["schedule"]
    pos = pd.DataFrame(0.0, index=days, columns=tickers)
    for i, (d, picks) in enumerate(sched):
        d0 = pd.Timestamp(d)
        d1 = pd.Timestamp(sched[i + 1][0]) if i + 1 < len(sched) else days[-1] + pd.Timedelta(days=1)
        rows = (days >= d0) & (days < d1)
        for t in picks:
            if t in pos.columns:
                pos.loc[rows, t] = 1.0
    return pos


# ---------------------------------------------------------------- 실행
def main(argv=None) -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--out", required=True)
    a.add_argument("--checkpoint", required=True)
    a.add_argument("--smoke", action="store_true")
    args = a.parse_args(argv)
    out, ck = Path(args.out), Path(args.checkpoint)
    st = Store(ck / "series")
    out.mkdir(parents=True, exist_ok=True)
    dl = deadline()
    data, spy, spy_total, vix, bil, core_r = load_all(args.smoke, ck)
    days = data.trading_days[data.trading_days >= pd.Timestamp("2011-01-03" if args.smoke else COMMON)]
    split = days[-1] - pd.DateOffset(years=2)
    train_end = pd.Timestamp("2014-01-01") if args.smoke else tl.TRAIN_END
    tickers = sorted(data.ohlcv)
    rets = tl.adj_returns(data, days, tickers)
    cash = bil.reindex(days).fillna(0.0)
    spy_r = spy_total.reindex(days).ffill().pct_change(fill_method=None).fillna(0.0)
    idle_ret = {"bil": cash, "spy": spy_r}
    members = {pt: tl.membership(data, pt, days) for pt in POOLS + (HINDSIGHT,)}
    reg = tl.regimes(spy, vix, days)
    core_r = core_r.reindex(days).fillna(0.0)

    # 이하 모든 수익은 단기국채(BIL) 대비 초과수익
    all_member = pd.DataFrame(True, index=days, columns=tickers)
    sat_r = tl.sleeve_returns(satellite_positions(data, days, tickers), all_member, rets, 3, cash) - cash
    core_x = core_r - cash
    champion = 0.85 * core_x + 0.15 * sat_r
    ones = pd.DataFrame(1.0, index=days, columns=tickers)
    bh = {pt: tl.sleeve_returns(ones, members[pt], rets, 1, cash) - cash for pt in POOLS + (HINDSIGHT,)}
    spy_x = spy_r - cash

    is_mask = days < split
    tr_mask = days < train_end
    va_mask = (days >= train_end) & is_mask

    def sh(r, mask):
        return tl.stats(pd.Series(r, index=days)[mask]).get("sharpe", float("nan"))

    def run_cfg(key, pt, x, filt, exit_, k, idle, gate=None, pos_cache={}):  # noqa: B006 - 최근 하나만 재사용
        pk = (x, filt, exit_, None if gate is None else gate.name)
        if pos_cache.get("key") != pk:
            pos_cache.clear()
            pos_cache.update(key=pk, pos=positions(data, x, filt, exit_, days, tickers, gate))
        r = tl.sleeve_returns(pos_cache["pos"], members[pt], rets, k, idle_ret[idle]) - cash
        st.save(key, r.to_numpy())

    # ---- R1 ----
    r1 = []
    for x in DIPS:
        for filt in FILTERS:
            for exit_ in EXITS:
                for pt in POOLS:
                    for k in KS:
                        for idle in IDLES:
                            key = cfg_key("R1", pt, x, filt, exit_, k, idle)
                            r1.append(key)
                            if st.has(key):
                                continue
                            if time.time() > dl:
                                log("시간 예산 소진(R1) — 다음 창에 이어서")
                                return EXIT_IN_PROGRESS
                            run_cfg(key, pt, x, filt, exit_, k, idle)
    log(f"R1 완료 {len(r1)}개")

    # ---- R2 (사전 등록 규칙으로 후보 선택) ----
    r1_stats = {k: (sh(st.load(k), tr_mask), sh(st.load(k), va_mask)) for k in r1}
    bh_va = {pt: sh(bh[pt].to_numpy(), va_mask) for pt in POOLS}
    ranked = sorted(r1, key=lambda k: -np.nan_to_num(r1_stats[k][0], nan=-9))
    passed = [k for k in ranked if r1_stats[k][1] > bh_va[parse_key(k)["pool"]]]
    cands = passed[:8] if passed else ranked[:5]
    st.json("r2_candidates", {"candidates": cands, "rule": "검증 구간에서 풀 그냥 보유를 이긴 개발 상위 8" if passed else "통과 없음 → 개발 상위 5"})
    gates = {}
    for gname, col in (("gate_bull", "bull"), ("gate_bear", "bear"), ("gate_high_vol", "high_vol")):
        g = reg[col] if col in reg else pd.Series(False, index=days)
        gates[gname] = g.rename(gname)
    r2 = []
    for base in cands:
        c = parse_key(base)
        variants = {**{g: dict(gate=gates[g]) for g in gates},
                    "x_minus5": dict(x=max(0.05, round(c["x"] - 0.05, 2))), "x_plus5": dict(x=round(c["x"] + 0.05, 2)),
                    "k_half": dict(k=max(1, c["k"] // 2)), "k_double": dict(k=c["k"] * 2)}
        for vn, ov in variants.items():
            vkey = base.replace("R1|", "R2|", 1) + f"|{vn}"
            r2.append(vkey)
            if st.has(vkey):
                continue
            if time.time() > dl:
                log("시간 예산 소진(R2) — 다음 창에 이어서")
                return EXIT_IN_PROGRESS
            run_cfg(vkey, c["pool"], ov.get("x", c["x"]), c["filt"], c["exit"], ov.get("k", c["k"]), c["idle"], ov.get("gate"))
    log(f"R2 완료 {len(r2)}개")

    # ---- R3 결합 ----
    pool_keys = [k for k in r1 + r2 if sh(st.load(k), tr_mask) > 0]
    top3 = sorted(pool_keys, key=lambda k: -np.nan_to_num(sh(st.load(k), va_mask), nan=-9))[:3]
    r3 = {}
    for key in top3:
        dip = pd.Series(st.load(key), index=days)
        r3[f"R3|replace_sat|{key}"] = 0.85 * core_x + 0.15 * dip
        r3[f"R3|add15|{key}"] = 0.70 * core_x + 0.15 * sat_r + 0.15 * dip
        r3[f"R3|add30|{key}"] = 0.55 * core_x + 0.15 * sat_r + 0.30 * dip
    log(f"R3 완료 {len(r3)}개")

    # ---- 판정 ----
    n_total = len(r1) + len(r2) + len(r3)
    standalone = {k: st.load(k) for k in r1 + r2}
    bench_name = "현 챔피언(코어 85 + 새틀라이트 15)"
    fam_s = judge_family(standalone, champion.to_numpy(), days, split, n_total, bench_name)
    if fam_s["winner"] != "__bench__":
        wpool = parse_key(fam_s["winner"])["pool"]
        w_is = sh(standalone[fam_s["winner"]], is_mask)
        b_is = sh(bh[wpool].to_numpy(), is_mask)
        fam_s["timing_gate"] = {"winner_is_sharpe": w_is, "pool_buyhold_is_sharpe": b_is, "pool": wpool}
        if not w_is > b_is:
            fam_s["reasons"].append(f"타이밍 관문: 눌림 매수 IS 샤프 {w_is:.2f} ≤ 같은 풀({wpool}) 그냥 보유 {b_is:.2f}")
            fam_s["verdict"] = "KEEP_CURRENT"
    fam_c = judge_family({k: v.to_numpy() for k, v in r3.items()}, champion.to_numpy(), days, split, n_total, bench_name)

    # ---- 진단(판정과 무관) ----
    def full(r) -> dict:
        """연수익·낙폭은 총수익(BIL 더함), 샤프는 판정과 같은 초과수익 기준."""
        x = pd.Series(r, index=days)
        out = {}
        for part, m in (("is", is_mask), ("oos", ~is_mask)):
            s = tl.stats(x[m] + cash[m])
            s["sharpe"] = tl.stats(x[m]).get("sharpe")
            out[part] = s
        return out

    def yearly(r) -> dict:
        r = pd.Series(r, index=days) + cash
        return {str(y): float((1 + g).prod() - 1) for y, g in r.groupby(r.index.year)}

    lines = {"현 챔피언": champion, "SPY": spy_x, **{f"그냥 보유 {pt}": bh[pt] for pt in POOLS}}
    for fam in (fam_s, fam_c):
        if fam["winner"] != "__bench__":
            lines[f"승자 {fam['winner']}"] = pd.Series(standalone.get(fam["winner"], r3.get(fam["winner"])), index=days)
    # D1 사후편향: 단독 승자(없으면 R1 개발 1위)의 규칙을 '오늘 상위 10' 풀에 그대로
    ref = fam_s["winner"] if fam_s["winner"] != "__bench__" else ranked[0]
    rc = parse_key(ref)
    hind = tl.sleeve_returns(positions(data, rc["x"], rc["filt"], rc["exit"], days, tickers), members[HINDSIGHT], rets,
                             rc["k"], idle_ret[rc["idle"]]) - cash
    hindsight = {"rule": ref, "pool_today_top10": data.pool(HINDSIGHT, days[-1]),
                 "rule_on_today_top10": full(hind), "buyhold_today_top10": full(bh[HINDSIGHT]),
                 "rule_on_pit_pool": full(standalone[ref]), "buyhold_pit_pool": full(bh[rc["pool"]])}
    pool_hist = {}
    for d in sl.rebalance_dates(days, 1):
        if d.month in (1, 7):
            pool_hist[str(d.date())] = {pt: data.pool(pt, d) for pt in POOLS}
    diag_top = []
    for k in sorted(standalone, key=lambda k: -np.nan_to_num(sh(standalone[k], is_mask), nan=-9))[:15]:
        r = pd.Series(standalone[k], index=days)
        diag_top.append({"config": k, "train": sh(standalone[k], tr_mask), "val": sh(standalone[k], va_mask),
                         "corr_champion": float(r[is_mask].corr(champion[is_mask])),
                         "regimes_vs_champion": tl.regime_table(r[is_mask], champion[is_mask], reg[is_mask])})
    payload = {"id": JOB_ID, "judge_version": JUDGE_VERSION, "smoke": args.smoke,
               "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "split": str(split.date()), "train_end": str(train_end.date()), "n_trials_total": n_total,
               "counts": {"R1": len(r1), "R2": len(r2), "R3": len(r3)},
               "r2_candidates": st.json("r2_candidates"), "r3_sleeves": top3,
               "verdicts": {"standalone": fam_s["verdict"], "synergy": fam_c["verdict"]},
               "families": {"standalone": fam_s, "synergy": fam_c},
               "benchmarks": {name: full(r) for name, r in lines.items()},
               "yearly": {name: yearly(r) for name, r in lines.items()},
               "diagnostics": {"hindsight": hindsight, "top15": diag_top, "pools": pool_hist}}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(payload), encoding="utf-8")
    log(f"판정 {payload['verdicts']}")
    return 0


def judge_family(configs: dict[str, np.ndarray], bench: np.ndarray, days, split, n_total: int, bench_name: str) -> dict:
    """tech-judge/v1 과 같은 관문(승자 IS 샤프 최고 → DSR(이 연구 전체 시도 수) → PBO → 떼어 둔 2년)."""
    names = ["__bench__"] + list(configs)
    mat = np.column_stack([bench] + [configs[k] for k in configs])
    res = sp.finalize_returns_family(names, mat, days, split, "__bench__")
    is_mask = np.asarray(days < split)
    win = names.index(res["winner"])
    active = mat[is_mask, win] - mat[is_mask, 0]
    mo = sp.moments(active)
    act_srs = list(sp.sharpe_cols(mat[is_mask] - mat[is_mask][:, [0]]))[1:]
    dsr = sp.deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], n_total, act_srs)
    res.update(dsr=round(dsr["dsr"], 4), n_trials_total=n_total, benchmark=bench_name, judge_version=JUDGE_VERSION)
    reasons = [r for r in res["reasons"] if not r.startswith("DSR")]
    if res["winner"] == "__bench__":
        reasons = ["앞 구간 최선이 비교 대상(챔피언) 자신"] + reasons
    if dsr["dsr"] < sp.DSR_MIN:
        reasons.append(f"DSR {dsr['dsr']:.2f} < {sp.DSR_MIN} (이 연구 전체 시도 {n_total})")
    res["reasons"] = list(dict.fromkeys(reasons))
    res["verdict"] = "CANDIDATE" if not res["reasons"] else "KEEP_CURRENT"
    return res


def describe(key: str) -> str:
    if key == "__bench__":
        return "현 챔피언"
    if key.startswith("R3|"):
        mode, rest = key.split("|", 2)[1:]
        return {"replace_sat": "코어 85 + 눌림 15", "add15": "코어 70 + 새틀 15 + 눌림 15",
                "add30": "코어 55 + 새틀 15 + 눌림 30"}[mode] + " ← " + describe(rest)
    c = parse_key(key)
    extra = key.split("|")[7] if key.count("|") >= 7 else ""
    return (f"{c['pool']} · 전고점 −{c['x']:.0%} 매수 · {'3년 승자만' if c['filt'] == 'winner3y' else '필터 없음'} · "
            f"{ {'recover': '회복 시 매도', 'hold126': '6개월 보유', 'recover_or_252': '회복 또는 1년'}[c['exit']]} · "
            f"{c['k']}칸 · 남는 돈 {c['idle'].upper()}" + (f" · {extra}" if extra else ""))


def report(p: dict) -> str:
    def num(x, d=2):
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"

    def pct(x):
        return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.0%}"

    L = ["# 초대형 우량주 눌림 매수 R&D v1 (dip-judge/v1)", "",
         f"생성 {p['generated_at']} · 개발 ~{p['train_end']} · 검증 ~{p['split']} · 그 뒤 2년 떼어 둠 · 전체 시도 {p['n_trials_total']}개 "
         f"(R1 {p['counts']['R1']}, R2 {p['counts']['R2']}, R3 {p['counts']['R3']})" + (" · **스모크(합성 데이터) — 실제 결과 아님**" if p["smoke"] else ""), "",
         "후보는 **그 시점** 시가총액 상위만 씁니다(지금 승자를 과거에 넣으면 무엇이든 좋아 보이므로). 샤프·DSR·PBO 는 단기국채 대비 초과수익 기준, "
         "아래 연수익·낙폭은 총수익입니다. CANDIDATE 도 엔진에 자동 반영되지 않습니다.", ""]
    L += ["## 한눈에 — 개발+검증 구간 / 떼어 둔 2년", "", "| | 연수익(앞) | 최대낙폭(앞) | 샤프(앞) | 연수익(떼어 둔 2년) | 샤프(떼어 둔 2년) |", "|---|---|---|---|---|---|"]
    for name, b in p["benchmarks"].items():
        label = ("승자 " + describe(name[3:])) if name.startswith("승자 ") else name
        L.append(f"| {label} | {pct(b['is'].get('cagr'))} | {pct(b['is'].get('mdd'))} | {num(b['is'].get('sharpe'))} | "
                 f"{pct(b['oos'].get('cagr'))} | {num(b['oos'].get('sharpe'))} |")
    L.append("")
    for fam, label in (("standalone", "단독(R1+R2) — 눌림 매수만으로 챔피언을 이기나"), ("synergy", "결합(R3) — 챔피언에 더하면 나아지나")):
        r = p["families"][fam]
        L += [f"## {label}", "", f"- 판정 **{r['verdict']}** · 앞 구간 최선: {describe(r['winner'])}",
              f"- 앞 구간 샤프 승자 {num(r['winner_is'].get('sharpe'))} vs 챔피언 {num(r['incumbent_is'].get('sharpe'))} · "
              f"DSR {num(r['dsr'])} · 과적합 확률 PBO {pct((r['pbo'] or {}).get('pbo'))} · 떼어 둔 2년 샤프 승자 {num(r['winner_oos'].get('sharpe'))} vs {num(r['incumbent_oos'].get('sharpe'))}"]
        if r.get("timing_gate"):
            t = r["timing_gate"]
            L.append(f"- 타이밍 관문: 눌림 매수 {num(t['winner_is_sharpe'])} vs 같은 풀 그냥 보유 {num(t['pool_buyhold_is_sharpe'])}")
        L += [f"- 사유: {'; '.join(r['reasons']) or '—'}", "", "| 앞 구간 상위 | 샤프(앞) | 연수익(앞) | 최대낙폭(앞) | 샤프(떼어 둔 2년) |", "|---|---|---|---|---|"]
        for t in r["top10"]:
            L.append(f"| {describe(t['config'])} | {num(t['is'].get('sharpe'))} | {pct(t['is'].get('cagr'))} | {pct(t['is'].get('mdd'))} | {num(t['oos'].get('sharpe'))} |")
        L.append("")
    h = p["diagnostics"]["hindsight"]
    L += ["## 진단 D1 — 사후편향은 얼마나 큰가 (판정과 무관)", "",
          f"같은 규칙({describe(h['rule'])})을 오늘 시총 상위 10({', '.join(h['pool_today_top10'])})에 과거 전체로 적용하면 — 실제로는 과거에 알 수 없던 목록입니다.", "",
          "| | 연수익(앞) | 샤프(앞) | 연수익(떼어 둔 2년) |", "|---|---|---|---|"]
    for lab, key in (("규칙 · 그 시점 상위(정직한 시험)", "rule_on_pit_pool"), ("그냥 보유 · 그 시점 상위", "buyhold_pit_pool"),
                     ("규칙 · 오늘 상위 10(사후편향)", "rule_on_today_top10"), ("그냥 보유 · 오늘 상위 10(사후편향)", "buyhold_today_top10")):
        b = h[key]
        L.append(f"| {lab} | {pct(b['is'].get('cagr'))} | {num(b['is'].get('sharpe'))} | {pct(b['oos'].get('cagr'))} |")
    years = sorted({y for v in p["yearly"].values() for y in v})
    L += ["", "## 연도별 총수익", "", "| | " + " | ".join(years) + " |", "|---|" + "---|" * len(years)]
    for name, v in p["yearly"].items():
        label = "승자(" + ("단독" if "R3|" not in name else "결합") + ")" if name.startswith("승자 ") else name
        L.append(f"| {label} | " + " | ".join(pct(v.get(y)) for y in years) + " |")
    pools = p["diagnostics"]["pools"]
    if pools:
        L += ["", "## 그 시점 mega10 구성(1월 기준)", ""]
        for d, v in pools.items():
            if d[5:7] == "01":
                L.append(f"- {d[:4]}: {', '.join(v.get('mega10') or [])}")
    L += ["", "판정 기준(사전 등록): 앞 구간 샤프 최고 승자가 챔피언 대비 DSR ≥ 0.95(이 연구 전체 시도 수), PBO ≤ 25%, 떼어 둔 2년 샤프 > 챔피언, "
          "단독은 같은 풀 그냥 보유보다 IS 샤프가 높을 것. 한계: 상장폐지 결측, 세금·환전 미반영, 시총은 발행주식수 × 종가 근사, 섹터는 현재 분류."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
