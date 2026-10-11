"""CRSP 백엔드 (2026-10-11) — S&P500 구성종목 일별 자료로 새틀라이트 선정 연구를 1963년부터 돌린다.

입력 계약(사용자가 WRDS 에서 내려받아 data/research_inputs/crsp_sp500/ 에 둔다. SPEC.md 와 같은 내용):
  daily.csv    permno,date,prc,ret,vol,shrout      (crsp.dsf — 열 이름은 소문자 그대로)
  names.csv    permno,namedt,nameendt,siccd,exchcd,shrcd   (crsp.dsenames)
  delists.csv  permno,date,dlret,dlstcd            (crsp.dsedelist, dlret 가 있는 행 + 없는 행 모두)
  sp500.csv    permno,start,ending                 (crsp.dsp500list — 구성종목 기간)

규칙(고정):
  * 시가총액 = |prc| × shrout × 1000, 리밸런싱일의 '전 거래일' 종가·주식수 (분할 문제 없음).
  * 총수익 지수 = 누적곱(1 + ret). 신호(돈치안 20일·252일 모멘텀)와 수익을 모두 이 지수로 잰다(분할·배당 조정; ETF 시대 연구는 신호를
    가격으로 잰다는 차이가 있다). 상장폐지 수익률 dlret 은 폐지일(또는 그 이전 마지막 기록일)의 수익에 (1+ret)(1+dlret)−1 로 합친다.
  * 결측·특수 코드: ret 이 숫자가 아니거나 −1 미만(CRSP −44/−55/−66/−77/−88/−99 코드)이면 그날 수익 0. dlret 은 −1~+1 범위일 때만 유효
    (delisted-precursors-v1 과 같은 관례); −55/−66/−88/−99 나 비어 있으면 적용하지 않는다(상장폐지 손실을 과소평가할 수 있음 — 보고서에 건수 표시).
  * 구성종목: sp500.csv 의 start ≤ 전 거래일 ≤ ending(비어 있으면 현재까지).
  * 섹터 = 그 시점 siccd(names.csv 에서 namedt ≤ 전 거래일인 마지막 행)를 Fama-French 12 산업으로 바꾼 것(Ken French Siccodes12 정의, 아래 표).
    siccd 가 없거나 0 이면 Other.
메모리: 25M 행 CSV 를 청크로 읽어 sp500.csv 에 한 번이라도 나온 종목만 남기고(date ≥ 자료 시작), 종목×날짜 총수익 지수 배열로 바꾼다.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
CRSP_DIR = ROOT / "data" / "research_inputs" / "crsp_sp500"
FILES = {
    "daily.csv": ["permno", "date", "prc", "ret", "vol", "shrout"],
    "names.csv": ["permno", "namedt", "nameendt", "siccd", "exchcd", "shrcd"],
    "delists.csv": ["permno", "date", "dlret", "dlstcd"],
    "sp500.csv": ["permno", "start", "ending"],
}
DATA_START = "1961-01-01"   # 1963-07 첫 선정 전에 730달력일 신호 창·252거래일 상관 창이 있도록
FAR_FUTURE = pd.Timestamp("2262-01-01")

EXTRACTION_SPEC = """\
WRDS(CRSP) 에서 아래 4개 CSV 를 내려받아 data/research_inputs/crsp_sp500/ 에 둔다 (헤더 한 줄, UTF-8, 열 이름 소문자 그대로, 날짜는 YYYY-MM-DD 또는 YYYYMMDD).
1) daily.csv   crsp.dsf (일별 주식 파일)   열: permno,date,prc,ret,vol,shrout
   필터: permno ∈ crsp.dsp500list 에 한 번이라도 나온 permno, date ≥ 1961-01-01(가능하면 2025 말까지). prc 부호(매수·매도 호가 평균은 음수)는 그대로 둔다.
2) names.csv   crsp.dsenames               열: permno,namedt,nameendt,siccd,exchcd,shrcd
   필터: 위와 같은 permno 전체(이름 구간 모두; nameendt 가 열려 있으면 비워도 된다).
3) delists.csv crsp.dsedelist              열: permno,date,dlret,dlstcd
   필터: 위와 같은 permno 전체(dlret 가 비어 있거나 −55/−66/−88/−99 인 행도 포함. date = dlstdt).
4) sp500.csv   crsp.dsp500list             열: permno,start,ending
   전체(구성종목 기간. ending 이 비어 있으면 아직 편입 중).
"""

# --- Fama-French 12 산업 (Ken French Siccodes12, 공개 정의) ---------------------------------------
FF12_NAMES = ("NoDur", "Durbl", "Manuf", "Enrgy", "Chems", "BusEq", "Telcm", "Utils", "Shops", "Hlth", "Money", "Other")
_FF12_RANGES: dict[str, list[tuple[int, int]]] = {
    "NoDur": [(100, 999), (2000, 2399), (2700, 2749), (2770, 2799), (3100, 3199), (3940, 3989)],
    "Durbl": [(2500, 2519), (2590, 2599), (3630, 3659), (3710, 3711), (3714, 3714), (3716, 3716), (3750, 3751), (3792, 3792),
              (3900, 3939), (3990, 3999)],
    "Manuf": [(2520, 2589), (2600, 2699), (2750, 2769), (3000, 3099), (3200, 3569), (3580, 3629), (3700, 3709), (3712, 3713),
              (3715, 3715), (3717, 3749), (3752, 3791), (3793, 3799), (3860, 3899)],
    "Enrgy": [(1200, 1399), (2900, 2999)],
    "Chems": [(2800, 2829), (2840, 2899)],
    "BusEq": [(3570, 3579), (3660, 3692), (3694, 3699), (3810, 3829), (7370, 7379)],
    "Telcm": [(4800, 4899)],
    "Utils": [(4900, 4949)],
    "Shops": [(5000, 5999), (7200, 7299), (7600, 7699)],
    "Hlth": [(2830, 2839), (3693, 3693), (3840, 3859), (8000, 8099)],
    "Money": [(6000, 6999)],
}


def ff12_from_sic(sic) -> str:
    """4자리 SIC → FF12 산업 이름. 없음/0/범위 밖은 Other."""
    try:
        s = int(float(sic))
    except (TypeError, ValueError):
        return "Other"
    if s <= 0:
        return "Other"
    for name, ranges in _FF12_RANGES.items():
        for lo, hi in ranges:
            if lo <= s <= hi:
                return name
    return "Other"


# =================================================================================================
# 입력 점검
# =================================================================================================

def input_problems(directory: Optional[Path] = None) -> list[str]:
    """없는 파일·빠진 열 목록(비어 있으면 사용 가능)."""
    d = Path(directory or CRSP_DIR)
    out = []
    for fname, cols in FILES.items():
        p = d / fname
        if not p.exists():
            out.append(f"{fname} 없음")
            continue
        try:
            head = pd.read_csv(p, nrows=0)
        except Exception as exc:  # noqa: BLE001
            out.append(f"{fname} 을 읽지 못함({type(exc).__name__})")
            continue
        miss = [c for c in cols if c not in head.columns]
        if miss:
            out.append(f"{fname} 에 열 없음: {', '.join(miss)}")
    return out


def parse_dates(s: pd.Series) -> pd.Series:
    """YYYY-MM-DD 문자열 또는 YYYYMMDD 정수/문자열."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    txt = s.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    nn = txt.dropna()
    if len(nn) and nn.str.fullmatch(r"\d{8}").all():
        return pd.to_datetime(txt, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(txt, errors="coerce")


def clean_ret(s: pd.Series) -> tuple[np.ndarray, int]:
    """수익률 → (유효한 값, 무효 건수). 숫자가 아니거나 −1 미만(특수 코드)이거나 결측이면 0 수익으로 보고 건수에 센다."""
    r = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
    bad = ~np.isfinite(r) | (r < -1.0)
    r = np.where(bad, 0.0, r)
    return np.maximum(r, -0.9999), int(bad.sum())


def valid_dlret(x) -> bool:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and -1.0 <= v <= 1.0


# =================================================================================================
# 읽기
# =================================================================================================

def read_sp500(directory: Path) -> pd.DataFrame:
    sp = pd.read_csv(directory / "sp500.csv")
    sp["permno"] = pd.to_numeric(sp["permno"], errors="coerce")
    sp = sp.dropna(subset=["permno"]).copy()
    sp["permno"] = sp["permno"].astype(int)
    sp["start"] = parse_dates(sp["start"])
    sp["ending"] = parse_dates(sp["ending"]).fillna(FAR_FUTURE)
    return sp.dropna(subset=["start"]).reset_index(drop=True)


def members_asof(sp: pd.DataFrame, asof: pd.Timestamp) -> set[int]:
    m = sp[(sp["start"] <= asof) & (sp["ending"] >= asof)]
    return set(int(x) for x in m["permno"])


def read_names(directory: Path) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    nm = pd.read_csv(directory / "names.csv")
    nm["permno"] = pd.to_numeric(nm["permno"], errors="coerce")
    nm = nm.dropna(subset=["permno"]).copy()
    nm["permno"] = nm["permno"].astype(int)
    nm["namedt"] = parse_dates(nm["namedt"])
    nm = nm.dropna(subset=["namedt"]).sort_values(["permno", "namedt"])
    out = {}
    for p, g in nm.groupby("permno", sort=False):
        out[int(p)] = (g["namedt"].to_numpy(dtype="datetime64[ns]"), g["siccd"].to_numpy())
    return out


def sic_asof(names: dict, permno: int, asof: pd.Timestamp):
    """asof 에 유효한(namedt ≤ asof 인 마지막) siccd. 이름 이력이 asof 보다 늦게 시작하면 첫 행(가장 이른 값)을 쓴다."""
    ent = names.get(int(permno))
    if ent is None:
        return None
    dts, sics = ent
    i = int(np.searchsorted(dts, np.datetime64(asof), side="right")) - 1
    return sics[max(i, 0)]


def read_delists(directory: Path) -> tuple[pd.DataFrame, dict]:
    dl = pd.read_csv(directory / "delists.csv")
    dl["permno"] = pd.to_numeric(dl["permno"], errors="coerce")
    dl = dl.dropna(subset=["permno"]).copy()
    dl["permno"] = dl["permno"].astype(int)
    dl["date"] = parse_dates(dl["date"])
    dl["dlret"] = pd.to_numeric(dl["dlret"], errors="coerce")
    ok = dl["dlret"].between(-1.0, 1.0, inclusive="both") & dl["date"].notna()
    perf = pd.to_numeric(dl["dlstcd"], errors="coerce").fillna(0) >= 500
    info = {"rows": int(len(dl)), "valid_dlret": int(ok.sum()),
            "invalid_or_missing_dlret": int((~ok).sum()),
            "performance_delist_without_valid_dlret": int((perf & ~ok).sum()),
            "code_counts": {str(c): int((dl["dlret"] == c).sum()) for c in (-55.0, -66.0, -88.0, -99.0)}}
    return dl[ok].sort_values("date").drop_duplicates("permno", keep="last"), info


def read_daily_members(directory: Path, permnos: set[int], start: str, end: Optional[str] = None,
                       chunk: int = 2_000_000, log: Callable[[str], None] = lambda s: None) -> tuple[pd.DataFrame, dict]:
    """daily.csv 를 청크로 읽어 permnos 만, date ≥ start 만 남긴다. 열: permno(int32), date, ret(원본 숫자), cap(= |prc|×shrout×1000)."""
    parts, rows_in, rows_out = [], 0, 0
    t0, t1 = pd.Timestamp(start), (pd.Timestamp(end) if end else None)
    for ch in pd.read_csv(directory / "daily.csv", usecols=["permno", "date", "prc", "ret", "shrout"], chunksize=chunk,
                          dtype={"permno": "float64", "date": "string", "prc": "float64", "shrout": "float64"}):
        rows_in += len(ch)
        ch = ch[ch["permno"].isin(permnos)]
        if ch.empty:
            continue
        ch = ch.assign(date=parse_dates(ch["date"]))
        ch = ch[(ch["date"] >= t0) & ch["date"].notna()]
        if t1 is not None:
            ch = ch[ch["date"] <= t1]
        if ch.empty:
            continue
        cap = ch["prc"].abs() * ch["shrout"] * 1000.0
        cap = cap.where(cap > 0)
        parts.append(pd.DataFrame({"permno": ch["permno"].astype("int32").to_numpy(), "date": ch["date"].to_numpy(),
                                   "ret_raw": ch["ret"].to_numpy(), "cap": cap.to_numpy(dtype="float32")}))
        rows_out += len(ch)
        if rows_in % (10 * chunk) < chunk:
            log(f"daily.csv {rows_in:,}행 읽음, 사용 {rows_out:,}")
    if not parts:
        return pd.DataFrame(columns=["permno", "date", "ret_raw", "cap"]), {"rows_in": rows_in, "rows_used": 0}
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values(["permno", "date"], kind="mergesort").drop_duplicates(["permno", "date"], keep="last").reset_index(drop=True)
    return df, {"rows_in": rows_in, "rows_used": int(len(df))}


# =================================================================================================
# 총수익 지수·시가총액·구성종목
# =================================================================================================

def total_return_index(df: pd.DataFrame, delists: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """(permno, date 정렬된) 행마다 총수익 지수. 종목 첫 행 = 1 + 첫 수익. 상장폐지 수익은 마지막 기록일(≤ 폐지일)에 합친다."""
    r_raw = pd.Series(df["ret_raw"])
    ret, bad = clean_ret(r_raw)
    ret = ret.copy()
    perm = df["permno"].to_numpy()
    dates = df["date"].to_numpy(dtype="datetime64[ns]")
    n_dl = 0
    if len(delists) and len(df):
        bounds = np.flatnonzero(np.r_[True, perm[1:] != perm[:-1], True])
        seg = {int(perm[bounds[k]]): (bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1)}
        for row in delists.itertuples(index=False):
            se = seg.get(int(row.permno))
            if se is None:
                continue
            a, b = se
            j = a + int(np.searchsorted(dates[a:b], np.datetime64(row.date), side="right")) - 1
            if j < a:
                continue
            ret[j] = max((1.0 + ret[j]) * (1.0 + float(row.dlret)) - 1.0, -0.9999)
            n_dl += 1
    lr = pd.Series(np.log1p(ret))
    tr = np.exp(lr.groupby(perm).cumsum().to_numpy())
    return tr, {"ret_invalid_or_missing": bad, "delist_returns_applied": n_dl}


def build_bundle(directory: Path, *, start: str, data_start: str = DATA_START, end: Optional[str] = None,
                 log: Callable[[str], None] = lambda s: None, chunk: int = 2_000_000):
    """CRSP → (sl.LabData, 부가 정보). 부가 정보: caps({리밸런싱일 ISO: {티커: 시총}}), sector_dated, meta."""
    from core import satellite_lab as sl

    sp = read_sp500(directory)
    ever = set(int(x) for x in sp["permno"])
    names = read_names(directory)
    delists, dl_info = read_delists(directory)
    log(f"구성종목 기록 {len(sp)}건, 종목 {len(ever)}개")
    df, rd_info = read_daily_members(directory, ever, data_start, end, chunk=chunk, log=log)
    if df.empty:
        raise RuntimeError("daily.csv 에서 구성종목 행을 찾지 못함")
    tr, tr_info = total_return_index(df, delists)
    days = pd.DatetimeIndex(np.sort(df["date"].unique()))
    di = days.searchsorted(pd.DatetimeIndex(df["date"]))
    perm = df["permno"].to_numpy()
    uniq = np.unique(perm)
    pi = np.searchsorted(uniq, perm)
    arr = np.full((len(days), len(uniq)), np.nan)
    arr[di, pi] = tr
    tickers = [str(int(p)) for p in uniq]
    closes = pd.DataFrame(arr, index=days, columns=tickers, copy=False)
    # 종목별 데이터프레임(신호용 Close)
    ohlcv = {}
    bounds = np.flatnonzero(np.r_[True, perm[1:] != perm[:-1], True])
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        ohlcv[str(int(perm[a]))] = pd.DataFrame({"Close": tr[a:b]}, index=days[di[a:b]])
    # 시가총액·섹터·구성종목 (리밸런싱일 전 거래일 기준)
    monthly = [d for d in pd.Series(days, index=days).groupby(days.to_period("M")).min() if d >= pd.Timestamp(start)]
    cap_by_day: dict[int, dict[str, float]] = {}
    need_prev = {int(days.searchsorted(d)) - 1 for d in monthly}
    capcol = df["cap"].to_numpy()
    sel = np.flatnonzero(np.isin(di, list(need_prev)) & np.isfinite(capcol))
    for idx in sel:
        cap_by_day.setdefault(int(di[idx]), {})[str(int(perm[idx]))] = float(capcol[idx])
    caps, sector_dated, pools = {}, {}, {}
    with_sic = set()
    for d in monthly:
        prev_i = int(days.searchsorted(d)) - 1
        if prev_i < 0:
            continue
        cutoff = days[prev_i]
        mem = members_asof(sp, cutoff)
        row = {t: c for t, c in cap_by_day.get(prev_i, {}).items() if int(t) in mem}
        key = d.date().isoformat()
        caps[key] = row
        sec = {}
        for t in row:
            sic = sic_asof(names, int(t), cutoff)
            if sic is not None:
                with_sic.add(t)
            sec[t] = ff12_from_sic(sic)
        sector_dated[key] = sec
        pools[d.date()] = sorted(str(int(p)) for p in mem if str(int(p)) in closes.columns)

    def pool_provider(pool_type: str, d) -> list[str]:
        members = pools.get(d, [])
        if pool_type == "sp500_pit":
            return members
        row = caps.get(d.isoformat(), {})
        ranked = sorted((t for t in members if t in row), key=lambda t: (-row[t], t))
        return ranked[:40]

    data = sl.LabData(trading_days=days, ohlcv=ohlcv, closes=closes, pool_provider=pool_provider)
    meta = {"backend": "crsp", "n_permnos": len(uniq), "first_day": str(days[0].date()), "last_day": str(days[-1].date()),
            "rows_in": rd_info["rows_in"], "rows_used": rd_info["rows_used"], "delists": dl_info, **tr_info,
            "n_sector_tickers": len(with_sic)}
    return data, {"caps": caps, "sector_dated": sector_dated, "meta": meta, "monthly": monthly}



# =================================================================================================
# 업종 코어 (industry_core): core-longrun-v1 의 복제 규칙이 들고 있는 FF12 산업
# =================================================================================================

def industry_core_held(monthly: list[pd.Timestamp], ind12: pd.DataFrame, mkt: pd.Series, core_lab) -> dict[str, list[str]]:
    """리밸런싱일 d 에 코어(252거래일 모멘텀 상위 4 양수, 200일 시장 필터)가 비중을 둔 FF12 산업. 신호는 d 전 거래일 종가까지(core_lab 규칙)."""
    w = core_lab.target_weights(ind12, mkt, core_lab.Rule())
    out = {}
    for d in monthly:
        sub = w.loc[:d]
        if sub.empty:
            out[d.date().isoformat()] = []
            continue
        row = sub.iloc[-1]
        out[d.date().isoformat()] = sorted(c for c in row.index if float(row[c]) > 1e-9)
    return out


def load_core_longrun_lab():
    import importlib.util
    import sys

    path = ROOT / "research" / "jobs" / "core-longrun-v1" / "lab.py"
    spec = importlib.util.spec_from_file_location("core_longrun_lab", path)
    mod = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(spec))
    if not hasattr(mod, "Rule"):
        spec.loader.exec_module(mod)
    return mod


# =================================================================================================
# 스모크용 합성 CRSP 파일
# =================================================================================================

_REP_SIC = {"NoDur": 2000, "Durbl": 3711, "Manuf": 3310, "Enrgy": 1311, "Chems": 2821, "BusEq": 3571, "Telcm": 4813,
            "Utils": 4911, "Shops": 5411, "Hlth": 2834, "Money": 6021, "Other": 7000}


def write_synthetic(directory: Path, *, seed: int = 5, start: str = "1961-01-02", end: str = "2010-12-31", per_industry: int = 4) -> dict:
    """작은 CRSP 형식 파일 4개를 만든다(네트워크 없음). 산업 요인 + 개별 잡음, 일부 종목 상장폐지(유효·무효 dlret), 이름(SIC) 변경, 편입/편출."""
    directory.mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range(start, end)
    n = len(days)
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0002, 0.006, n)
    daily, names, dls, sp = [], [], [], []
    permno = 10000
    for si, ind in enumerate(FF12_NAMES):
        fac = rng.normal(0.0002, 0.009, n)
        for k in range(per_industry):
            permno += 1
            r = 0.8 * market + rng.uniform(0.6, 1.4) * fac + rng.normal(0.0, rng.uniform(0.005, 0.014), n)
            first = 0 if k < per_industry - 1 else min(int(np.searchsorted(days, pd.Timestamp("1975-01-02"))), n // 2)
            last = n - 1
            if k == 0 and si % 3 == 0:  # 일부는 상장폐지
                last = min(int(np.searchsorted(days, pd.Timestamp("1998-06-30")) + si * 100), n - 50)
                dls.append((permno, days[last], -0.5 if si % 2 == 0 else -55.0, 500 if si % 2 == 0 else 574))
            idx = np.arange(first, last + 1)
            price = 30 * np.exp(np.cumsum(r[idx] - r[idx][0]))
            price = price * (1 + 0.0 * idx)
            shares = float(np.exp(rng.uniform(np.log(2e4), np.log(2e6))))  # 천 주
            rr = r[idx].copy()
            rr[::997] = np.nan                                                 # 드문 결측
            daily.append(pd.DataFrame({"permno": permno, "date": days[idx].strftime("%Y-%m-%d"), "prc": -price if k == 1 else price,
                                       "ret": rr, "vol": 1e5, "shrout": shares}))
            sic = _REP_SIC[ind]
            if k == 2:   # 중간에 업종 변경: 2000-01-01 부터 BusEq 로
                names.append((permno, "1961-01-01", "1999-12-31", sic, 1, 11))
                names.append((permno, "2000-01-01", "", 3571, 1, 11))
            else:
                names.append((permno, "1961-01-01", "", sic, 1, 11))
            sp.append((permno, days[first].strftime("%Y-%m-%d"), "" if last == n - 1 else days[last].strftime("%Y-%m-%d")))
    pd.concat(daily).to_csv(directory / "daily.csv", index=False)
    pd.DataFrame(names, columns=FILES["names.csv"]).to_csv(directory / "names.csv", index=False)
    pd.DataFrame(dls, columns=FILES["delists.csv"]).to_csv(directory / "delists.csv", index=False)
    pd.DataFrame(sp, columns=FILES["sp500.csv"]).to_csv(directory / "sp500.csv", index=False)
    return {"days": n, "permnos": permno - 10000}
