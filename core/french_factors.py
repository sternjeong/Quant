"""Ken French 데이터 라이브러리 — 두 번째 시험대(무료, 1926~, CRSP 기반이라 생존편향 없음).

두 가지 용도:
1. 팩터 노출 회귀(factor_exposure): 가설의 일별 수익을 시장·규모·가치·수익성·투자(FF5)+모멘텀에 회귀해
   "새 전략인가, 알려진 팩터의 재포장인가"를 본다. 심판(core.hypothesis_judge)은 이 결과를 보고만 하고
   통과/탈락에는 쓰지 않는다(경고만). 우리 가설은 롱온리라 시장 베타가 크게 잡히는 것이 정상이다.
2. 공개 전후 감쇠표(decay_table): 고전 팩터를 원 논문 공개 연도로 나눠 월평균·Newey-West t·샤프를 비교한다.
   scripts/french_factor_report.py 가 research/factor_decay.md 로 써서 Scout·Writer 에이전트가 읽는다.

데이터 형식: zip 안의 CSV 하나. 설명문 → ",열1,열2" 머리줄 → YYYYMMDD(일별) 또는 YYYYMM(월별) 행 → 빈 줄(월별
파일은 뒤에 연간 표가 이어지지만 첫 표만 읽는다). 값은 퍼센트, 결측은 -99.99/-999.
캐시는 data/cache/french_<이름>.csv(커밋하지 않음), MAX_AGE_DAYS 가 지나면 다시 받고, 받기에 실패하면 낡은 캐시를 쓴다.
"""

from __future__ import annotations

import io
import math
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
DATASETS = {
    "ff5_daily": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "mom_daily": "F-F_Momentum_Factor_daily_CSV.zip",
    "ff3_monthly": "F-F_Research_Data_Factors_CSV.zip",
    "mom_monthly": "F-F_Momentum_Factor_CSV.zip",
    "strev_monthly": "F-F_ST_Reversal_Factor_CSV.zip",
    "ltrev_monthly": "F-F_LT_Reversal_Factor_CSV.zip",
}
MAX_AGE_DAYS = 7
DAILY_FACTORS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
MIN_OVERLAP_DAYS = 252
NW_LAGS_DAILY = 5
NW_LAGS_MONTHLY = 6
# 팩터 → (원 논문, 공개 연도). 공개 연도 말까지를 '공개 전'으로 본다.
PUBLICATIONS = {
    "SMB": ("Banz 1981 (규모)", 1981),
    "LT_Rev": ("De Bondt & Thaler 1985 (장기 반전)", 1985),
    "ST_Rev": ("Jegadeesh 1990 (단기 반전)", 1990),
    "HML": ("Fama & French 1992 (가치)", 1992),
    "Mom": ("Jegadeesh & Titman 1993 (모멘텀)", 1993),
}

Fetcher = Callable[[str], bytes]


def parse_french_csv(text: str) -> pd.DataFrame:
    """첫 번째 표를 소수 수익률(퍼센트/100) DataFrame 으로. 인덱스는 날짜(월별은 그 달 말일)."""
    rows, cols = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if cols is None:
            if line.startswith(","):
                cols = [c.strip() for c in line.split(",")[1:]]
            continue
        if not line:
            if rows:
                break
            continue
        cells = [c.strip() for c in line.split(",")]
        if not cells[0].isdigit() or len(cells[0]) not in (6, 8):
            if rows:
                break
            continue
        rows.append(cells[: len(cols) + 1])
    if cols is None or not rows:
        raise ValueError("French CSV 에서 표를 찾지 못함")
    keys = [r[0] for r in rows]
    idx = (pd.to_datetime(keys, format="%Y%m%d") if len(keys[0]) == 8
           else pd.to_datetime(keys, format="%Y%m") + pd.offsets.MonthEnd(0))
    df = pd.DataFrame([[float(x) for x in r[1:]] for r in rows], index=idx, columns=cols)
    df = df.mask(df <= -99.99)
    return df / 100.0


def _fetch(filename: str) -> bytes:
    req = urllib.request.Request(BASE_URL + filename, headers={"User-Agent": "Mozilla/5.0 (quant research)"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 — 고정된 https 주소
        return resp.read()


def _unzip_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        return z.read(name).decode("latin-1")


def load(name: str, *, fetch: Optional[Fetcher] = None, max_age_days: float = MAX_AGE_DAYS) -> Optional[pd.DataFrame]:
    """데이터셋 하나. 캐시가 신선하면 캐시, 아니면 받아서 캐시. 받기 실패 시 낡은 캐시, 그것도 없으면 None."""
    path = CACHE_DIR / f"french_{name}.csv"
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400
    if not fresh:
        try:
            df = parse_french_csv(_unzip_text((fetch or _fetch)(DATASETS[name])))
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(path)
            return df
        except Exception:  # noqa: BLE001 — 네트워크·형식 오류는 낡은 캐시로 대신한다
            pass
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    return None


def daily_factors(fetch: Optional[Fetcher] = None) -> Optional[pd.DataFrame]:
    """FF5 일별 + 모멘텀 일별(Mkt-RF, SMB, HML, RMW, CMA, Mom, RF). 하나라도 없으면 None."""
    ff5, mom = load("ff5_daily", fetch=fetch), load("mom_daily", fetch=fetch)
    if ff5 is None or mom is None:
        return None
    return ff5.join(mom[["Mom"]], how="inner").dropna()


def monthly_factors(fetch: Optional[Fetcher] = None) -> Optional[pd.DataFrame]:
    """FF3 월별 + 모멘텀·단기반전·장기반전 월별. 하나라도 없으면 None."""
    parts = [load(n, fetch=fetch) for n in ("ff3_monthly", "mom_monthly", "strev_monthly", "ltrev_monthly")]
    if any(p is None for p in parts):
        return None
    out = parts[0]
    for p in parts[1:]:
        out = out.join(p, how="outer")
    return out


def ols_nw(y: np.ndarray, x: np.ndarray, lags: int) -> dict[str, Any]:
    """절편 포함 OLS 와 Newey-West(Bartlett) 표준오차. x 는 (n, k) 설명변수(절편 제외)."""
    n = len(y)
    X = np.column_stack([np.ones(n), x]) if x.size else np.ones((n, 1))
    xtx_inv = np.linalg.pinv(X.T @ X)  # 열이 겹치거나 0 이어도 멈추지 않게
    beta = xtx_inv @ X.T @ y
    e = y - X @ beta
    xe = X * e[:, None]
    s = xe.T @ xe
    for lag in range(1, min(lags, n - 1) + 1):
        w = 1 - lag / (lags + 1)
        g = xe[lag:].T @ xe[:-lag]
        s += w * (g + g.T)
    cov = xtx_inv @ s @ xtx_inv
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    t = np.divide(beta, se, out=np.zeros_like(beta), where=se > 0)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float((e ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    return {"coef": beta, "t": t, "r2": r2, "n": n}


def factor_exposure(strat: pd.Series, factors: Optional[pd.DataFrame]) -> Optional[dict[str, Any]]:
    """일별 순수익을 FF5+모멘텀에 회귀. 겹치는 날이 MIN_OVERLAP_DAYS 미만이면 None."""
    if factors is None or strat is None:
        return None
    s = strat.copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    df = pd.concat([s.rename("s"), factors], axis=1, join="inner").dropna()
    if len(df) < MIN_OVERLAP_DAYS:
        return None
    y = (df["s"] - df["RF"]).to_numpy()
    fit = ols_nw(y, df[DAILY_FACTORS].to_numpy(), NW_LAGS_DAILY)
    return {"n_days": fit["n"], "start": df.index[0].date().isoformat(), "end": df.index[-1].date().isoformat(),
            "alpha_annual": float(fit["coef"][0]) * 252, "alpha_t": float(fit["t"][0]), "r2": fit["r2"],
            "loadings": {f: {"beta": float(fit["coef"][i + 1]), "t": float(fit["t"][i + 1])}
                         for i, f in enumerate(DAILY_FACTORS)}}


def _period_stats(r: pd.Series) -> dict[str, Any]:
    r = r.dropna()
    if len(r) < 24:
        return {"months": len(r)}
    fit = ols_nw(r.to_numpy(), np.empty((len(r), 0)), NW_LAGS_MONTHLY)
    sd = float(r.std(ddof=1))
    return {"months": len(r), "start": r.index[0].strftime("%Y-%m"), "end": r.index[-1].strftime("%Y-%m"),
            "mean_pct": float(r.mean()) * 100, "t": float(fit["t"][0]),
            "sharpe_annual": float(r.mean()) / sd * math.sqrt(12) if sd > 0 else 0.0}


def decay_table(monthly: pd.DataFrame) -> list[dict[str, Any]]:
    """팩터별 공개 전/후 월평균(%)·NW t·연샤프와 공개 후/전 평균 비율."""
    out = []
    for f, (paper, year) in PUBLICATIONS.items():
        if f not in monthly:
            continue
        r = monthly[f]
        pre, post = _period_stats(r.loc[: f"{year}-12-31"]), _period_stats(r.loc[f"{year + 1}-01-01":])
        ratio = (post["mean_pct"] / pre["mean_pct"]
                 if "mean_pct" in pre and "mean_pct" in post and pre["mean_pct"] != 0 else None)
        out.append({"factor": f, "paper": paper, "year": year, "pre": pre, "post": post, "post_to_pre": ratio})
    return out


def render_decay_markdown(rows: list[dict[str, Any]], generated: str, data_end: str) -> str:
    def cell(p: dict) -> str:
        if "mean_pct" not in p:
            return f"표본 부족({p.get('months', 0)}개월)"
        return f"{p['mean_pct']:+.2f}% (t={p['t']:.2f}, 샤프 {p['sharpe_annual']:.2f}, {p['start']}~{p['end']})"

    lines = [f"# 고전 팩터 공개 전후 감쇠 (Ken French 월별 데이터, 자료 끝 {data_end}, 생성 {generated})", "",
             "scripts/french_factor_report.py 가 생성한다. 롱숏 팩터 월수익(비용 전)이며 우리 계약은 롱온리라 그대로 구현할 수 없다.",
             "공개 후 평균이 공개 전의 절반 아래면 그 방향의 가설은 비용·과밀을 먼저 반박해야 한다. t 는 Newey-West(6).", "",
             "| 팩터 | 원 논문 | 공개 전 월평균 | 공개 후 월평균 | 후/전 |", "|---|---|---|---|---|"]
    for x in rows:
        ratio = f"{x['post_to_pre']:.0%}" if x["post_to_pre"] is not None else "—"
        lines.append(f"| {x['factor']} | {x['paper']} | {cell(x['pre'])} | {cell(x['post'])} | {ratio} |")
    return "\n".join(lines) + "\n"
