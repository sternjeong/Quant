"""검증 연구 mom-proxy-v1 (2026-10-16 사전 등록): 생존편향 없는 '대형주 모멘텀 승자' 대리 지표로 새틀라이트를 본다.

사용자 요청(2026-10-16): 수익 최대화. WRDS/CRSP 는 쓸 수 없다. 새틀라이트(S-SEED-000: 시총 상위 40 대형주 중 12개월 승자 3개, 6개월 보유)가
수익 엔진으로 보이지만 근거가 2017~2024 에 몰려 있고 가격 자료에 상장폐지 종목이 없다. Ken French 의 규모 × 과거 수익(12-2)
포트폴리오(CRSP 기반, 상장폐지 포함, 1926-11~)를 '대형주 모멘텀 승자를 들고 가기'의 생존편향 없는 대리 지표로 쓴다.

PART 1(진단, 판정 아님): 2010-01 ~ 2024-09 에서 라이브 새틀라이트 슬리브(세전 USD) vs BIG HiPRIOR · ME5×PRIOR5 보정 비교,
    그리고 BIG HiPRIOR vs 시장 1927-07 ~ 2025 장기 통계.
PART 2(판정): 시장 (1−w) + BIG HiPRIOR 슬리브 w(연 1% 끌림 차감), w ∈ {15, 30, 50, 70, 100}%, 매년 첫 거래일 목표로 재조정(편도 10bp).
    선택 1927-07-01 ~ 1966-12-31 에서만 고르고, 확인 1967-01-01 ~ 2007-12-31 에서 판정. 2008 ~ 은 보고만.

규칙 전체는 SPEC.md(한국어)와 아래 상수에 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 다시 등록한다. 엔진 반영은 사용자 확인 뒤 별도 작업.
평일 달력(to_weekdays)·CAPM(NW6)·연 재조정(blend_returns)은 core-longrun-v1/lab.py 를 그대로 import 해서 쓴다.
라이브 새틀라이트 일정은 satellite-value-v1 의 _incumbent·_pool_wrapper 와 core.satellite_lab.run_variant 로 같은 방식으로 만든다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import pickle
import signal as _signal
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402

_spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research/jobs/core-longrun-v1/lab.py")
lab = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "Rule"):
    _spec.loader.exec_module(lab)

JOB_ID = "mom-proxy-v1"
RULES_VERSION = "mom-proxy-v1/2026-10-16"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
DATASET_6, DATASET_25 = "mom6_daily", "mom25_daily"      # core.french_factors.DATASETS 의 키
FILE_6 = "6_Portfolios_ME_Prior_12_2_Daily_CSV.zip"
FILE_25 = "25_Portfolios_ME_Prior_12_2_Daily_CSV.zip"
COL_BIG_HI = "BIG HiPRIOR"          # 6개 파일: 대형(NYSE 중앙값 위) × 과거 수익 상위 30%
COL_ME5_P5 = "BIG HiPRIOR"          # 25개 파일: ME5 PRIOR5 열 이름(가장 큰 규모 5분위 × 과거 수익 상위 5분위)
SLEEVES = {"BIGHI": "6개 중 BIG HiPRIOR(판정)", "ME5P5": "25개 중 ME5×PRIOR5(보고만)"}
JUDGED_SLEEVE = "BIGHI"

DRAG = 0.01                         # 슬리브 연 끌림(재구성 비용 근사) — 판정
DRAG_SENS = (0.0, 0.02)             # 민감도(보고만)
TRADING_DAYS = 252
W_CELLS = (0.15, 0.30, 0.50, 0.70, 1.00)
CELLS = tuple(f"w{int(round(w * 100))}" for w in W_CELLS)
N_TRIALS = 5
COST_BPS = 10.0                     # 연 재조정 회전율 × 편도 10bp
WINDOWS = {"sel": ("1927-07-01", "1966-12-31"), "conf": ("1967-01-01", "2007-12-31"), "post": ("2008-01-01", None)}
CONF_SUBS = (("1967-01-01", "1986-12-31"), ("1987-01-01", "2007-12-31"))
POWER_YEARS = 41.0
ROLL_DAYS = 252                     # 최악 롤링 12개월 = 252행
WORST12_SLACK = 0.05                # B: 최악 12개월 ≥ 시장 최악 − 5%p
CAGR_MARGIN = 0.01                  # 확인: CAGR ≥ 시장 + 1.0%p
ALPHA_T_MIN = 2.0                   # CAPM 알파 NW(6, 월별) t
TIE_EPS = 1e-9

# PART 1
CAL_WINDOWS = {"full": ("2010-01-01", "2024-09-30"), "h1": ("2010-01-01", "2017-05-31"), "h2": ("2017-06-01", "2024-09-30")}
LONGRUN = ("1927-07-01", "2025-12-31")
SAT_START = "2010-01-01"
SAT_DATA_START, SAT_DATA_END = "2009-12-01", "2024-10-31"

PASS, FAIL, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "NOT_EVALUABLE"
NO_ELIGIBLE = "NO_ELIGIBLE_CELL"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 자료
# =================================================================================================

def normalize(ff3: pd.DataFrame, p6: pd.DataFrame, p25: pd.DataFrame) -> dict[str, Any]:
    """세 표의 공통 날짜 → 평일 달력(주말 수익은 다음 평일에 복리) → 시작 뒤 드문 결측은 0(개수 기록)."""
    idx = ff3.index.intersection(p6.index).intersection(p25.index).sort_values()
    raw = pd.DataFrame({"rf": ff3["RF"], "mkt": ff3["Mkt-RF"] + ff3["RF"],
                        "BIGHI": p6[COL_BIG_HI], "ME5P5": p25[COL_ME5_P5]}).reindex(idx).astype(float)
    wk = lab.to_weekdays(raw)
    started = wk.notna().cummax()
    gaps = {c: int((started[c] & wk[c].isna()).sum()) for c in wk.columns}
    wk = lab.clean_industry(wk)
    return {"rf": wk["rf"], "mkt": wk["mkt"], "BIGHI": wk["BIGHI"], "ME5P5": wk["ME5P5"], "gaps_filled_zero": gaps,
            "start": str(wk.index[0].date()), "end": str(wk.index[-1].date()), "weekend_rows_raw": int((idx.dayofweek >= 5).sum())}


def load_french_real() -> dict[str, Any]:
    from core import french_factors as ff

    ff3, p6, p25 = ff.load("ff3_daily"), ff.load(DATASET_6), ff.load(DATASET_25)
    if ff3 is None or p6 is None or p25 is None:
        raise RuntimeError("Ken French 일별 FF3 / 규모×과거수익 6·25개 자료를 받지 못함")
    for df, f in ((p6, FILE_6), (p25, FILE_25)):
        if COL_BIG_HI not in df.columns:
            raise RuntimeError(f"{f} 에 '{COL_BIG_HI}' 열이 없음: {list(df.columns)}")
    out = normalize(ff3, p6, p25)
    out["source"] = f"Ken French data library ({FILE_6}, {FILE_25}, F-F_Research_Data_Factors_daily; value-weighted; weekday calendar)"
    return out


def _french_text(df: pd.DataFrame, title: str) -> str:
    """합성 표를 French CSV 모양(설명 → ',열' 머리줄 → YYYYMMDD 행 → 빈 줄 → 두 번째 표)으로 — 실제 파서를 지나게."""
    lines = [f"This file was created by synthetic smoke ({title}).", "", "  Average Value Weighted Returns -- Daily",
             "," + ",".join(df.columns)]
    for d, row in zip(df.index, df.to_numpy() * 100.0):
        lines.append(d.strftime("%Y%m%d") + "," + ",".join(f"{x:.4f}" for x in row))
    lines += ["", "  Average Equal Weighted Returns -- Daily", "," + ",".join(df.columns), df.index[0].strftime("%Y%m%d") + ",9,9", ""]
    return "\n".join(lines)


def synthetic_french(seed: int = 3, start: str = "1926-11-03", end: str = "2026-08-31") -> dict[str, Any]:
    """스모크용 가짜 French 표(네트워크·캐시 없음). 1952-06 이전 토요일 행, 시작 뒤 결측 하루, 폭락 구간을 넣는다."""
    from core import french_factors as ff

    sats = pd.date_range(start, "1952-05-31", freq="W-SAT")
    idx = pd.bdate_range(start, end).union(sats)
    n = len(idx)
    rng = np.random.default_rng(seed)
    drift = np.full(n, 0.0003)
    for a, b, d in (("1929-09-01", "1932-06-30", -0.0025), ("1973-01-01", "1974-10-31", -0.002),
                    ("1987-10-01", "1987-10-30", -0.012), ("2008-09-01", "2009-03-09", -0.005)):
        drift[(idx >= a) & (idx <= b)] = d
    rf = np.full(n, 0.00012)
    mkt_ex = drift + rng.normal(0, 0.009, n)
    ff3 = pd.DataFrame({"Mkt-RF": mkt_ex, "SMB": rng.normal(0, 0.004, n), "HML": rng.normal(0, 0.004, n), "RF": rf}, index=idx)
    cols6 = ["SMALL LoPRIOR", "ME1 PRIOR2", "SMALL HiPRIOR", "BIG LoPRIOR", "ME2 PRIOR2", "BIG HiPRIOR"]
    cols25 = [f"ME{i} PRIOR{j}" for i in range(1, 6) for j in range(1, 6)]
    cols25 = ["SMALL LoPRIOR" if c == "ME1 PRIOR1" else "SMALL HiPRIOR" if c == "ME1 PRIOR5" else
              "BIG LoPRIOR" if c == "ME5 PRIOR1" else "BIG HiPRIOR" if c == "ME5 PRIOR5" else c for c in cols25]

    def panel(cols, s, hi_alpha):
        r = np.random.default_rng(s)
        base = rf[:, None] + mkt_ex[:, None] * np.linspace(0.8, 1.3, len(cols)) + r.normal(0, 0.006, (n, len(cols)))
        df = pd.DataFrame(base, index=idx, columns=cols)
        # 승자 열은 시장보다 조금 덜 흔들리고 조금 더 벌게 — 스모크가 '고른 칸 → 확인 판정' 경로까지 지나가게
        df["BIG HiPRIOR"] = rf + 0.85 * mkt_ex + hi_alpha + r.normal(0, 0.003, n)
        return df
    p6, p25 = panel(cols6, seed + 1, 0.00012), panel(cols25, seed + 2, 0.00018)
    p6.iloc[n // 2, cols6.index("BIG HiPRIOR")] = -99.99 / 100.0   # 결측 표기 → 파서가 NaN → 0 으로
    parsed = [ff.parse_french_csv(_french_text(df, t)) for df, t in ((ff3, "ff3"), (p6, "6"), (p25, "25"))]
    out = normalize(*parsed)
    out["source"] = "synthetic (smoke)"
    return out


def build_satellite_real(log) -> dict[str, Any]:
    """라이브 새틀라이트(S-SEED-000, champion40 풀) 세전 USD 일별 수익 — satellite-value-v1 / sat-frontier-v1 과 같은 일정."""
    from core import satellite_lab as sl

    sv = _sv()
    pool = sv._pool_wrapper(sl.default_pool_provider(), date.fromisoformat(SAT_START))
    data = sl.build_data({"champion40"}, start=SAT_DATA_START, end=SAT_DATA_END, pool_provider=pool, log=log)
    out = satellite_from_data(data, sv)
    try:
        from core import champion_strategy as cs
        out["meta"] = {"strategy_version": cs.CHAMPION_STRATEGY_VERSION, "judge_version": sl.JUDGE_VERSION,
                       "pool_cache_tag": sl.POOL_CACHE_TAG, "live_satellite_weight": cs.SATELLITE_WEIGHT}
    except Exception:  # noqa: BLE001
        out["meta"] = {}
    return out


def build_satellite_smoke(log) -> dict[str, Any]:  # noqa: ARG001
    """합성 가격(네트워크 없음) 위에서 같은 경로(run_variant)로 만든 가짜 슬리브. 실데이터가 아니다."""
    from core import satellite_lab as sl

    sv = _sv()
    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=SAT_DATA_END, seed=11)
    pool = sv._pool_wrapper(poolp, date.fromisoformat(SAT_START))
    data = sl.build_data({"champion40"}, start=SAT_DATA_START, end=SAT_DATA_END, pool_provider=pool, price_provider=pp)
    out = satellite_from_data(data, sv)
    out["meta"] = {"synthetic": True}
    return out


def satellite_from_data(data, sv) -> dict[str, Any]:
    from core import satellite_lab as sl

    spec, signal, params = sv._incumbent()
    sp = json.loads(json.dumps(spec))
    sp["pool"] = {"type": "champion40"}
    gross = sl.run_variant(sp, params, signal, data, bps=0.0)
    net = sl.run_variant(sp, params, signal, data)
    return {"gross": _naive(gross["returns"]), "net": _naive(net["returns"]),
            "schedule": [{"date": d, "picks": list(p)} for d, p in gross["schedule"]]}


def _naive(s: pd.Series) -> pd.Series:
    s = s.astype(float).copy()
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep="first")].sort_index()


_SV = None


def _sv():
    global _SV
    if _SV is None:
        spec = importlib.util.spec_from_file_location("satellite_value_v1_for_momproxy", PROJECT_ROOT / "research/jobs/satellite-value-v1/run.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SV = mod
    return _SV


# =================================================================================================
# 순수 함수 (tests/test_mom_proxy.py)
# =================================================================================================

def apply_drag(r: pd.Series, drag: float) -> pd.Series:
    """일별 (1+r)(1 − drag/252) − 1 — 연 drag 만큼 깎는다(평일 달력 252행 = 1년)."""
    return (1.0 + r) * (1.0 - drag / TRADING_DAYS) - 1.0


def window(s: pd.Series, a: str, b: Optional[str]) -> pd.Series:
    return s.loc[pd.Timestamp(a): (pd.Timestamp(b) if b else None)]


def blend(sleeve: pd.Series, mkt: pd.Series, w: float, bps: float = COST_BPS) -> pd.Series:
    """시장 (1−w) + 슬리브 w. 구간 첫날 목표로 시작(새 계좌), 매년 첫 거래일 종가에 목표로 재조정(회전율 × 편도 bp), 그 사이 표류."""
    return lab.blend_returns(sleeve, mkt, w, bps)


def values(r: pd.Series) -> pd.Series:
    return (1.0 + r).cumprod()


def max_drawdown(r: pd.Series) -> float:
    """시작 값 1 을 첫 행 앞에 둔 최대 낙폭(음수)."""
    v = np.r_[1.0, values(r).to_numpy(dtype=float)]
    return float((v / np.maximum.accumulate(v) - 1.0).min())


def worst_rolling(r: pd.Series, n: int = ROLL_DAYS) -> Optional[float]:
    """연속 n 행(252 = 12개월) 수익의 최솟값. 시작 값 1 을 첫 행 앞에 둔다. n 행이 안 되면 None."""
    v = np.r_[1.0, values(r).to_numpy(dtype=float)]
    if len(v) < n + 1:
        return None
    return float((v[n:] / v[:-n] - 1.0).min())


def cagr(r: pd.Series) -> float:
    return lab.cagr(r) if len(r) > 1 else float("nan")


def _ok(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(float(x))


def stable(m: dict, mk: dict) -> tuple[bool, bool]:
    """(A, B): A = MDD 가 시장보다 나쁘지 않음, B = 최악 252행 수익 ≥ 시장 최악 − 5%p. 비교에 수치 허용 오차 TIE_EPS(1e-9)."""
    a = _ok(m["mdd"]) and _ok(mk["mdd"]) and m["mdd"] >= mk["mdd"] - TIE_EPS
    b = _ok(m["worst12"]) and _ok(mk["worst12"]) and m["worst12"] >= mk["worst12"] - WORST12_SLACK - TIE_EPS
    return bool(a), bool(b)


def cell_w(cell: str) -> float:
    return int(cell[1:]) / 100.0


def select_cell(sel_metrics: dict, mkt_sel: dict) -> Optional[str]:
    """선택 구간 지표만 받는다: {칸: {cagr, mdd, worst12}}. A·B 를 만족하는 칸 중 CAGR 최대(동률 → 낮은 w). 없으면 None."""
    ok = [c for c, m in sel_metrics.items() if all(stable(m, mkt_sel)) and _ok(m["cagr"])]
    if not ok:
        return None
    best = max(sel_metrics[c]["cagr"] for c in ok)
    tied = [c for c in ok if sel_metrics[c]["cagr"] >= best - TIE_EPS]
    return min(tied, key=cell_w)


def conf_checks(m: dict, mk: dict, subs: list[dict], capm: dict) -> dict[str, Optional[bool]]:
    """확인 구간 관문. 값이 없으면 None."""
    a, b = stable(m, mk)
    return {
        "cagr_ge_mkt_plus_1pp": (m["cagr"] >= mk["cagr"] + CAGR_MARGIN) if _ok(m["cagr"]) and _ok(mk["cagr"]) else None,
        "A_mdd": a,
        "B_worst12": b,
        "beat_1967_1986": (subs[0]["cagr"] > subs[0]["market_cagr"]) if len(subs) > 0 and _ok(subs[0]["cagr"]) and _ok(subs[0]["market_cagr"]) else None,
        "beat_1987_2007": (subs[1]["cagr"] > subs[1]["market_cagr"]) if len(subs) > 1 and _ok(subs[1]["cagr"]) and _ok(subs[1]["market_cagr"]) else None,
        "alpha_t_ge_2": (capm["alpha_t_nw6"] >= ALPHA_T_MIN) if _ok(capm.get("alpha_t_nw6")) else None,
    }


def decide(checks: dict, noop: Optional[str], observed_ir: Optional[float], power: dict) -> tuple[str, list[str]]:
    """모든 관문 True → PASS. 무효 실행·값 없음 → NOT_EVALUABLE. 그 밖 → classify_fail(FAIL / FAIL_UNDERPOWERED)."""
    if noop:
        return NOT_EVALUABLE, ["noop"]
    if any(v is None for v in checks.values()):
        return NOT_EVALUABLE, [k for k, v in checks.items() if v is None]
    miss = [k for k, v in checks.items() if v is not True]
    if not miss:
        return PASS, []
    return rp.classify_fail(observed_ir, power), miss


def align_to_calendar(r: pd.Series, cal: pd.DatetimeIndex) -> pd.Series:
    """일별 수익 r 을 다른 달력(cal)으로 옮긴다: 누적 지수를 cal 날짜에 앞값으로 채워 다시 수익으로.
    cal 에 없는 r 의 날 수익은 다음 cal 날에 복리로 합쳐진다(누적 수익 보존). 결과는 r 의 첫날 ~ 마지막 날 안의 cal 날짜."""
    s = r.dropna().sort_index()
    if s.empty:
        return pd.Series(dtype=float)
    cal_in = cal[(cal >= s.index[0]) & (cal <= s.index[-1])]
    lv = values(s)
    lv_c = lv.reindex(lv.index.union(cal_in)).ffill().reindex(cal_in)
    out = lv_c / lv_c.shift(1) - 1.0
    if len(out):
        out.iloc[0] = lv_c.iloc[0] - 1.0
    return out


def monthly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def pair_stats(a: pd.Series, b: pd.Series) -> dict[str, Any]:
    """같은 날짜의 두 일별 수익: 연복리·차이·일별/월별 상관·추적오차(일별 차이 표준편차 × √252)·IR."""
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
    if len(df) < 3:
        return {"days": len(df)}
    d = df["a"] - df["b"]
    sd = float(d.std(ddof=1))
    ma, mb = monthly(df["a"]), monthly(df["b"])
    ca, cb = cagr(df["a"]), cagr(df["b"])
    return {"days": len(df), "start": str(df.index[0].date()), "end": str(df.index[-1].date()),
            "cagr_a": ca, "cagr_b": cb, "cagr_diff": ca - cb,
            "corr_daily": float(df["a"].corr(df["b"])), "corr_monthly": float(ma.corr(mb)) if len(ma) > 2 else None,
            "tracking_error": sd * math.sqrt(TRADING_DAYS),
            "ir": float(d.mean()) / sd * math.sqrt(TRADING_DAYS) if sd > 0 else None,
            "vol_a": float(df["a"].std(ddof=1)) * math.sqrt(TRADING_DAYS), "vol_b": float(df["b"].std(ddof=1)) * math.sqrt(TRADING_DAYS)}


def yearly(series: dict[str, pd.Series]) -> list[dict[str, Any]]:
    """{이름: 일별 수익} → 연도별 복리 수익 행(공통 날짜만)."""
    df = pd.concat({k: v for k, v in series.items()}, axis=1, join="inner").dropna()
    g = (1 + df).groupby(df.index.year).prod() - 1
    return [{"year": int(y), **{k: float(g.at[y, k]) for k in df.columns}} for y in g.index]


# =================================================================================================
# 계산 단계
# =================================================================================================

def series_metrics(r: pd.Series, mkt_full: pd.Series, rf: pd.Series) -> dict[str, Any]:
    cp = lab.capm(r, mkt_full, rf) if len(r) > 30 else {}
    return {"cagr": cagr(r), "mdd": max_drawdown(r), "worst12": worst_rolling(r),
            "vol": float(r.std(ddof=1)) * math.sqrt(TRADING_DAYS) if len(r) > 2 else None,
            "sharpe_monthly": lab.sharpe_monthly(r, rf) if len(r) > 60 else None,
            "capm": cp, "start": str(r.index[0].date()) if len(r) else None, "end": str(r.index[-1].date()) if len(r) else None}


def frontier(sleeve_raw: pd.Series, mkt: pd.Series, rf: pd.Series, drag: float, power: dict) -> dict[str, Any]:
    """칸 × 구간 지표, 선택(선택 구간만), 확인 판정. 각 구간은 새 계좌."""
    sleeve = apply_drag(sleeve_raw, drag)
    out: dict[str, Any] = {"drag": drag, "metrics": {}, "market": {}, "stability": {}, "conf_checks": {}, "conf_subperiods": {}}
    conf_series: dict[str, pd.Series] = {}
    for wname, (a, b) in WINDOWS.items():
        m = window(mkt, a, b)
        if len(m) < 2:
            continue
        mk = series_metrics(m, mkt, rf)
        out["market"][wname] = mk
        sl = window(sleeve, a, b)
        for cell in CELLS:
            r = blend(sl, m, cell_w(cell))
            met = series_metrics(r, mkt, rf)
            out["metrics"].setdefault(cell, {})[wname] = met
            out["stability"].setdefault(wname, {})[cell] = dict(zip(("A", "B"), stable(met, mk)))
            if wname == "conf":
                conf_series[cell] = r
    sel = {c: out["metrics"][c]["sel"] for c in CELLS if "sel" in out["metrics"].get(c, {})}
    chosen = select_cell(sel, out["market"]["sel"]) if "sel" in out["market"] else None
    if "conf" in out["market"]:
        m_conf = window(mkt, *WINDOWS["conf"])
        for cell in CELLS:
            r = conf_series[cell]
            subs = [{"start": a, "end": b, "cagr": cagr(window(r, a, b)), "market_cagr": cagr(window(m_conf, a, b))} for a, b in CONF_SUBS]
            out["conf_subperiods"][cell] = subs
            out["conf_checks"][cell] = conf_checks(out["metrics"][cell]["conf"], out["market"]["conf"], subs,
                                                   out["metrics"][cell]["conf"]["capm"])
    out["chosen"] = chosen
    if chosen is None:
        out["verdict"], out["failed_conditions"], out["noop"] = NO_ELIGIBLE, [], None
    elif "conf" not in out["market"]:
        out["verdict"], out["failed_conditions"], out["noop"] = NOT_EVALUABLE, ["no_conf_window"], None
    else:
        r = conf_series[chosen]
        noop = rp.noop_guard((r - window(mkt, *WINDOWS["conf"]).reindex(r.index)).tolist())
        ir = out["metrics"][chosen]["conf"]["capm"].get("appraisal_ir")
        out["verdict"], out["failed_conditions"] = decide(out["conf_checks"][chosen], noop, ir, power)
        out["noop"] = noop
        out["observed_appraisal_ir"] = ir
    return out


def frontier_stage(fr: dict, power: dict) -> dict[str, Any]:
    out = {}
    for sleeve in SLEEVES:
        for d in (DRAG,) + DRAG_SENS:
            out[f"{sleeve}|{d:.2f}"] = frontier(fr[sleeve], fr["mkt"], fr["rf"], d, power)
    return out


def part1_stage(fr: dict, sat: dict) -> dict[str, Any]:
    cal = fr["mkt"].index
    sat_g, sat_n = align_to_calendar(sat["gross"], cal), align_to_calendar(sat["net"], cal)
    sat_days = pd.DatetimeIndex(sat["gross"].dropna().index)
    span = cal[(cal >= sat_days.min()) & (cal <= sat_days.max())] if len(sat_days) else cal[:0]
    align = {"sat_days": int(len(sat_days)), "french_days_in_span": int(len(span)),
             "sat_days_not_in_french": int(len(sat_days.difference(cal))),
             "french_days_not_in_sat": int(len(span.difference(sat_days))),
             "sat_first": str(sat_days.min().date()) if len(sat_days) else None,
             "sat_last": str(sat_days.max().date()) if len(sat_days) else None}
    refs = {"BIGHI": fr["BIGHI"], "ME5P5": fr["ME5P5"], "MKT": fr["mkt"]}
    cmp: dict[str, Any] = {}
    for wname, (a, b) in CAL_WINDOWS.items():
        g, n = window(sat_g, a, b), window(sat_n, a, b)
        cmp[wname] = {f"gross_vs_{k}": pair_stats(g, window(v, a, b)) for k, v in refs.items()}
        cmp[wname]["net_vs_BIGHI"] = pair_stats(n, window(fr["BIGHI"], a, b))
        cmp[wname]["BIGHI_vs_MKT"] = pair_stats(window(fr["BIGHI"], a, b).reindex(g.index), window(fr["mkt"], a, b).reindex(g.index))
    a, b = CAL_WINDOWS["full"]
    yt = yearly({"sat_gross": window(sat_g, a, b), "sat_net": window(sat_n, a, b), "BIGHI": window(fr["BIGHI"], a, b),
                 "ME5P5": window(fr["ME5P5"], a, b), "MKT": window(fr["mkt"], a, b)})
    la, lb = LONGRUN
    lr = {}
    for k in ("BIGHI", "ME5P5"):
        for d in (0.0, DRAG):
            s = window(apply_drag(fr[k], d), la, lb)
            lr[f"{k}|{d:.2f}"] = series_metrics(s, fr["mkt"], fr["rf"])
    lr["MKT"] = series_metrics(window(fr["mkt"], la, lb), fr["mkt"], fr["rf"])
    decades = []
    for y0 in range(1927, 2026, 10):
        a0, b0 = (f"{y0}-07-01" if y0 == 1927 else f"{y0}-01-01"), f"{min(y0 + 9, 2025)}-12-31"
        decades.append({"start": a0, "end": b0, "BIGHI": cagr(window(fr["BIGHI"], a0, b0)), "ME5P5": cagr(window(fr["ME5P5"], a0, b0)),
                        "MKT": cagr(window(fr["mkt"], a0, b0))})
    return {"alignment": align, "compare": cmp, "yearly": yt, "longrun": lr, "longrun_window": list(LONGRUN), "decades": decades,
            "schedule": sat.get("schedule", []), "meta": sat.get("meta", {})}


# =================================================================================================
# 체크포인트
# =================================================================================================

def _atomic_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _load_ckpt(path: Path, fp: dict):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)  # 이 스크립트가 쓴 파일만 읽는다
        return obj["payload"] if obj.get("fingerprint") == fp else None
    except Exception:  # noqa: BLE001 — 깨진 체크포인트는 다시 계산
        return None


# =================================================================================================
# 결과·보고
# =================================================================================================

def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return round(v, 6) if math.isfinite(v) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


def build_result(fr: dict, fro: dict, p1: dict, power: dict, smoke: bool) -> dict:
    j = fro[f"{JUDGED_SLEEVE}|{DRAG:.2f}"]
    verdicts = {"chosen_cell": j["chosen"] or NO_ELIGIBLE, "verdict": j["verdict"]}
    if smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    report_only = {k: {"chosen": v["chosen"] or NO_ELIGIBLE, "verdict_if_judged": v["verdict"]} for k, v in fro.items()
                   if k != f"{JUDGED_SLEEVE}|{DRAG:.2f}"}
    res = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": fr.get("source"), "data_span": [fr.get("start"), fr.get("end")], "gaps_filled_zero": fr.get("gaps_filled_zero"),
        "weekend_rows_merged": fr.get("weekend_rows_raw"),
        "rules": {"files": [FILE_6, FILE_25], "judged_sleeve": f"{FILE_6}:{COL_BIG_HI}", "report_sleeve": f"{FILE_25}:{COL_ME5_P5} (ME5 PRIOR5)",
                  "drag": DRAG, "drag_sensitivity": list(DRAG_SENS), "cells": list(CELLS), "w": list(W_CELLS), "cost_bps": COST_BPS,
                  "windows": WINDOWS, "conf_subperiods": CONF_SUBS, "roll_days": ROLL_DAYS, "worst12_slack": WORST12_SLACK,
                  "cagr_margin": CAGR_MARGIN, "alpha_t_min": ALPHA_T_MIN, "n_trials": N_TRIALS, "power_years": POWER_YEARS,
                  "post_2008": "report only", "pretax": True},
        "verdicts": verdicts,
        "judged": j,
        "report_only_frontiers": report_only,
        "frontiers": fro,
        "power": power, "power_line": rp.power_line(power),
        "part1": p1,
    }
    return _clean(res)


def _p(x, nd=1, signed=False) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _pp(x, nd=2) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x * 100:+.{nd}f}%p"


def _f(x, nd=2) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x:.{nd}f}"


def _yn(v) -> str:
    return "—" if v is None else ("✓" if v else "✗")


def _frontier_table(fr: dict, wname: str) -> list[str]:
    L = ["| 칸 | CAGR | 시장 대비 | MDD | 최악 12개월 | 샤프(월) | 알파 / t | A/B |", "|---|---|---|---|---|---|---|---|"]
    mk = fr["market"].get(wname)
    if not mk:
        return ["(구간 자료 없음)"]
    for c in CELLS:
        m = fr["metrics"][c][wname]
        st = fr["stability"][wname][c]
        cp = m.get("capm") or {}
        L.append(f"| {c} | {_p(m['cagr'], 2)} | {_pp(m['cagr'] - mk['cagr'] if _ok(m['cagr']) and _ok(mk['cagr']) else None)} | "
                 f"{_p(m['mdd'])} | {_p(m['worst12'])} | {_f(m.get('sharpe_monthly'))} | {_p(cp.get('alpha_annual'), 2, True)} / {_f(cp.get('alpha_t_nw6'))} | "
                 f"{_yn(st['A'])}/{_yn(st['B'])} |")
    L.append(f"| 시장 | {_p(mk['cagr'], 2)} | — | {_p(mk['mdd'])} | {_p(mk['worst12'])} | {_f(mk.get('sharpe_monthly'))} | — | — |")
    return L


def render(r: dict) -> str:
    sm = " (스모크 — 합성 데이터, 실측 아님)" if r["smoke"] else ""
    j = r["judged"]
    v = r["verdicts"]
    L = [f"# 대형주 모멘텀 대리 지표(Ken French, 생존편향 없음) — 새틀라이트 보정 + 시장/모멘텀 비중 고르기{sm}", "",
         f"자료: {r['source']} · {r['data_span'][0]} ~ {r['data_span'][1]} · 세전(USD) · 규칙 {r['rules_version']}", "",
         "## 판정 (PART 2)", "",
         f"- 고른 칸(선택 구간 1927-07 ~ 1966 에서만): **{v['chosen_cell']}**",
         f"- 확인 구간(1967 ~ 2007) 판정: **{v['verdict']}**" + (f" — 미충족: {', '.join(j['failed_conditions'])}" if j.get("failed_conditions") else ""),
         f"- {r['power_line']}" + (f" 관측 평가비율 IR {_f(j.get('observed_appraisal_ir'))}." if j.get("observed_appraisal_ir") is not None else ""),
         f"- 무효 실행 가드: {j.get('noop') or '통과(고른 칸이 시장과 다름)' if j.get('chosen') else '해당 없음'}",
         "",
         "### 무엇을 쟀나",
         "",
         "- **Ken French 모멘텀 포트폴리오**: CRSP 전 종목(상장폐지 포함)을 규모(시가총액, NYSE 기준점)와 과거 수익(파일 설명: −250 ~ −21거래일, 흔히 12-2)으로 나눈 "
         "시가총액 가중 포트폴리오다. 'BIG HiPRIOR' = 규모 중앙값 위 대형주 중 과거 수익 상위 30% (수백 종목). 파일 설명상 **매일 다시 구성**하며 매매 비용은 없다. "
         "그대로 살 수 있는 상품이 아니므로, 재구성 비용 근사로 슬리브 수익에서 **연 1%를 빼고(판정)** 0%·2% 는 민감도로만 본다.",
         "- 포트폴리오 = 시장(Mkt-RF + RF) (1 − w) + 모멘텀 슬리브 w, w ∈ {15, 30, 50, 70, 100}%. 각 구간은 새 계좌(첫날 목표 비중), 매년 첫 거래일 종가에 목표로 "
         "되돌림(재조정 회전율 × 편도 10bp). 시도 수 5.",
         "- 고르기(선택 구간만): (A) 최대 낙폭이 시장보다 나쁘지 않음, (B) 최악 252거래일 수익 ≥ 시장 최악 − 5%p 를 모두 만족하는 칸 중 CAGR 최대(동률 → 낮은 w). "
         "없으면 NO_ELIGIBLE_CELL.",
         "- 통과(PASS_FORWARD_CANDIDATE) = 고른 칸이 확인 구간에서 CAGR ≥ 시장 + 1.0%p, A, B, 1967~1986·1987~2007 둘 다 시장보다 높은 CAGR, "
         "월별 CAPM 알파 Newey-West(6) t ≥ 2.0 을 **모두** 만족. 탈락은 classify_fail 로 FAIL / FAIL_UNDERPOWERED.", ""]
    for wname, title in (("sel", "선택 구간 1927-07-01 ~ 1966-12-31"), ("conf", "확인 구간 1967-01-01 ~ 2007-12-31"),
                         ("post", "2008-01-01 ~ 자료 끝 (보고만 — sat-frontier-v1 의 ETF 시대 숫자와 비교용)")):
        L += [f"## 모든 칸 — {title} (BIG HiPRIOR, 연 1% 끌림)", ""] + _frontier_table(j, wname) + [""]
    if j.get("conf_checks"):
        L += ["## 확인 구간 관문(모든 칸, 판정은 고른 칸만)", "",
              "| 칸 | CAGR ≥ 시장+1%p | A | B | 1967~86 이김 | 1987~2007 이김 | 알파 t ≥ 2 | 1967~86 (시장) | 1987~2007 (시장) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for c in CELLS:
            ch, sb = j["conf_checks"][c], j["conf_subperiods"][c]
            L.append(f"| {c} | {_yn(ch['cagr_ge_mkt_plus_1pp'])} | {_yn(ch['A_mdd'])} | {_yn(ch['B_worst12'])} | {_yn(ch['beat_1967_1986'])} | "
                     f"{_yn(ch['beat_1987_2007'])} | {_yn(ch['alpha_t_ge_2'])} | {_p(sb[0]['cagr'])} ({_p(sb[0]['market_cagr'])}) | "
                     f"{_p(sb[1]['cagr'])} ({_p(sb[1]['market_cagr'])}) |")
        L.append("")
    L += ["## 민감도·25개 판 (보고만 — 판정 아님)", "",
          "| 슬리브 | 끌림 | 고른 칸 | (판정했다면) | " + " | ".join(f"{c} 확인 CAGR" for c in CELLS) + " | 시장 확인 | " +
          " | ".join(f"{c} 2008~" for c in CELLS) + " |",
          "|---|---|---|---|" + "---|" * (2 * len(CELLS) + 1)]
    for k, fr in r["frontiers"].items():
        sleeve, d = k.split("|")
        conf = [_p(fr["metrics"][c].get("conf", {}).get("cagr"), 2) for c in CELLS]
        post = [_p(fr["metrics"][c].get("post", {}).get("cagr"), 2) for c in CELLS]
        L.append(f"| {SLEEVES[sleeve]} | {float(d) * 100:.0f}% | {fr['chosen'] or NO_ELIGIBLE} | {fr['verdict']} | " + " | ".join(conf) +
                 f" | {_p(fr['market'].get('conf', {}).get('cagr'), 2)} | " + " | ".join(post) + " |")
    p1 = r["part1"]
    al = p1["alignment"]
    L += ["", "## PART 1 — 우리 새틀라이트 자료 보정(진단, 판정 아님)", "",
          "라이브 새틀라이트(S-SEED-000: 그 시점 champion40 풀, 돈치안 20일 추세 활성 중 252일 모멘텀 상위 3, 균등, 1·7월 재선정)의 **세전 USD 일별 수익**"
          "(비용 0 = gross, 라이브 편도 비용 반영 = net)을 French BIG HiPRIOR · ME5×PRIOR5 와 같은 날짜(French 달력으로 옮김, 누적 수익 보존)에서 비교한다.",
          f"- 날짜 맞춤: 새틀라이트 {al['sat_days']}일({al['sat_first']} ~ {al['sat_last']}), 그 사이 French 거래일 {al['french_days_in_span']}일, "
          f"새틀라이트에만 있는 날 {al['sat_days_not_in_french']}일(다음 French 날에 복리로 합침), French 에만 있는 날 {al['french_days_not_in_sat']}일.", "",
          "| 구간 | 비교 | 새틀라이트 CAGR | 비교 대상 CAGR | 차이 | 일별 상관 | 월별 상관 | 추적오차 | IR |", "|---|---|---|---|---|---|---|---|---|"]
    names = {"gross_vs_BIGHI": "gross vs BIG HiPRIOR", "gross_vs_ME5P5": "gross vs ME5×PRIOR5", "gross_vs_MKT": "gross vs 시장",
             "net_vs_BIGHI": "net vs BIG HiPRIOR", "BIGHI_vs_MKT": "(BIG HiPRIOR vs 시장)"}
    for wname, rows in p1["compare"].items():
        a, b = CAL_WINDOWS[wname]
        for k, s in rows.items():
            if "cagr_a" not in s:
                continue
            L.append(f"| {a} ~ {b} | {names.get(k, k)} | {_p(s['cagr_a'], 2)} | {_p(s['cagr_b'], 2)} | {_pp(s['cagr_diff'])} | {_f(s['corr_daily'])} | "
                     f"{_f(s.get('corr_monthly'))} | {_p(s['tracking_error'])} | {_f(s.get('ir'))} |")
    L += ["", "**해석 안내**: 새틀라이트 − BIG HiPRIOR 차이는 (1) 우리 가격 자료의 생존편향(상장폐지 종목이 후보에서 빠짐 → 새틀라이트를 좋게 보이게 함)과 "
          "(2) 진짜 선택 차이(40개 중 3개 집중·6개월 보유·추세 필터 vs 수백 종목 시가총액 가중·매일 재구성)가 **섞인 값**이다. 깨끗한 편향 추정이 아니다. "
          "차이가 크게 +이면 '편향 + 집중의 이득'의 상한 쪽 이야기이고, 0 근처나 −이면 우리 백테스트의 새틀라이트 우위 대부분이 넓은 대형 모멘텀으로 설명된다는 쪽이다. "
          "상관·추적오차가 낮으면 French 대리 지표가 우리 슬리브를 잘 대표하지 못한다는 뜻이므로 PART 2 결과를 우리 새틀라이트에 옮길 때 그만큼 조심해야 한다.", "",
          "### 연도별 (세전 USD, 2024 는 1~9월)", "",
          "| 연도 | 새틀라이트 gross | net | BIG HiPRIOR | ME5×PRIOR5 | 시장 | gross − BIG HiPRIOR |", "|---|---|---|---|---|---|---|"]
    for y in p1["yearly"]:
        L.append(f"| {y['year']} | {_p(y['sat_gross'])} | {_p(y['sat_net'])} | {_p(y['BIGHI'])} | {_p(y['ME5P5'])} | {_p(y['MKT'])} | "
                 f"{_pp(y['sat_gross'] - y['BIGHI'], 1)} |")
    lr = p1["longrun"]
    L += ["", f"### 장기 통계 {p1['longrun_window'][0]} ~ {p1['longrun_window'][1]} (보고만)", "",
          "| 시리즈 | CAGR | 변동성 | MDD | 최악 12개월 | 샤프(월) | 베타 | 알파 / t |", "|---|---|---|---|---|---|---|---|"]
    lrn = {"BIGHI|0.00": "BIG HiPRIOR (끌림 0)", "BIGHI|0.01": "BIG HiPRIOR (연 1% 끌림)", "ME5P5|0.00": "ME5×PRIOR5 (끌림 0)",
           "ME5P5|0.01": "ME5×PRIOR5 (연 1% 끌림)", "MKT": "시장"}
    for k, m in lr.items():
        cp = m.get("capm") or {}
        L.append(f"| {lrn.get(k, k)} | {_p(m['cagr'], 2)} | {_p(m.get('vol'))} | {_p(m['mdd'])} | {_p(m['worst12'])} | {_f(m.get('sharpe_monthly'))} | "
                 f"{_f(cp.get('beta_daily'))} | {_p(cp.get('alpha_annual'), 2, True)} / {_f(cp.get('alpha_t_nw6'))} |")
    L += ["", "| 10년 | BIG HiPRIOR | ME5×PRIOR5 | 시장 |", "|---|---|---|---|"]
    for d in p1["decades"]:
        L.append(f"| {d['start'][:4]}~{d['end'][:4]} | {_p(d['BIGHI'])} | {_p(d['ME5P5'])} | {_p(d['MKT'])} |")
    L += ["", "## 한계·주의(꼭 읽기)", "",
          "- French 포트폴리오는 그대로 살 수 없다(수백 종목, 매일 재구성, 비용 없음). 연 1% 끌림은 근사일 뿐 실제 비용을 재지 않는다 — 0%·2% 민감도를 함께 볼 것.",
          "- 우리 새틀라이트(상위 3개 집중, 6개월 보유, 추세 필터)와 BIG HiPRIOR(넓은 대형 승자)는 다른 포트폴리오다. PART 2 PASS 는 '넓은 대형 모멘텀 기울기'에 대한 근거이지 "
          "S-SEED-000 자체의 검증이 아니다.",
          "- 세전 USD. 한국 세금(해외주식 양도세 22%·250만 원 공제, 배당 원천징수 15%)과 환율은 모형에 넣지 않았다. 재조정이 연 1회라 실현 이익이 생기는 만큼 세후 차이는 줄어든다.",
          "- 2008 ~ 은 보고만(판정 아님). 1967 ~ 2007 은 이 저장소의 다른 연구(core-longrun-v1·sector-concentrate-v1 등)가 이미 본 장기 구간이지만, 이 포트폴리오(규모×모멘텀)로는 처음이다.",
          "- PASS 는 '전진 원장에 올릴 후보'까지만 뜻한다. 엔진(챔피언 전략)은 바뀌지 않았다. 반영은 사용자 확인 뒤 별도 작업이다.",
          "- 과거 결과이며 앞으로의 수익을 뜻하지 않는다.", ""]
    return "\n".join(L)


def smoke_coverage(res: dict, fr: dict) -> dict:
    fro = res["frontiers"]
    j = res["judged"]
    p1 = res["part1"]
    return {
        "all_frontiers": len(fro) == len(SLEEVES) * (1 + len(DRAG_SENS)),
        "all_cells_windows": all(set(j["metrics"][c]) == set(WINDOWS) for c in CELLS),
        "weekday_calendar": bool((fr["mkt"].index.dayofweek < 5).all()) and (res["weekend_rows_merged"] or 0) > 0,
        "gap_filled": (res["gaps_filled_zero"] or {}).get("BIGHI", 0) >= 1,
        "drag_lowers_cagr": all(fro["BIGHI|0.02"]["metrics"][c]["conf"]["cagr"] < fro["BIGHI|0.00"]["metrics"][c]["conf"]["cagr"] for c in CELLS),
        "verdict_label": j["verdict"] in (PASS, FAIL, "FAIL_UNDERPOWERED", NOT_EVALUABLE),
        "chosen_path": j["chosen"] in CELLS and set(j["conf_checks"]) == set(CELLS),
        "part1_windows": all("cagr_a" in p1["compare"][w]["gross_vs_BIGHI"] for w in CAL_WINDOWS),
        "part1_yearly": len(p1["yearly"]) >= 14,
        "longrun": "BIGHI|0.01" in p1["longrun"],
    }


# =================================================================================================
# 실행
# =================================================================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-steps-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 단계 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    power = rp.power_report(POWER_YEARS, N_TRIALS)  # 결과를 보기 전에(구간·시도 수만)
    steps = {"new": 0}

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time(margin: float = 90.0) -> None:
        if deadline is not None and time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    def stage(name: str, fn):
        path = ck / f"{name}.pkl"
        got = _load_ckpt(path, fp)
        if got is None:
            if a.max_steps_per_run and steps["new"] >= a.max_steps_per_run:
                raise _Stop()
            check_time()
            got = fn()
            _atomic_pickle(path, {"fingerprint": fp, "payload": got})
            steps["new"] += 1
            log(f"단계 저장: {name}")
        return got

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        fr = stage("french", lambda: synthetic_french() if a.smoke else load_french_real())
        sat = stage("satellite", lambda: build_satellite_smoke(log) if a.smoke else build_satellite_real(log))
        fro = stage("frontier", lambda: frontier_stage(fr, power))
        p1 = stage("part1", lambda: part1_stage(fr, sat))
        result = build_result(fr, fro, p1, power, a.smoke)
        if a.smoke:
            cov = smoke_coverage(result, fr)
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(result), encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
