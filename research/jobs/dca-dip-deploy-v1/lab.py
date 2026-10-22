"""팔지 않는 적립 계좌(buy-only) 공용 실험실 — dca-dip-deploy-v1·dca-asset-pick-v1 이 함께 쓴다 (2026-10-22 사전 등록).

계좌 모델(결과를 보기 전에 고정):
  - 적립금은 매달 첫 거래일에 들어온다(구간 첫날 = 첫 적립). 처음 목돈이 있으면 첫날 바로 산다(모든 팔 같음).
  - 절대 팔지 않는다. 산 단위는 구간 끝까지 보유. 기다리는 돈은 현금(무위험 이자, 이자소득세 15.4% 뺌).
  - 구간 끝에 모두 판다고 보고 양도세 22% × max(0, 평가 이익 − 250만 원)을 뺀다(원화, 환율 1,300 원/달러 고정 근사).
  - 매수 수수료 0.1%(+ 긴 역사 자료는 환전 0.05%). 배당 원천징수는 넣지 않았다(총수익 지수 그대로 — 주의 사항).
  - 신호는 d 일 종가로 계산하고 d+1 일 종가에 산다(미리 보기 없음).
구간 계산은 벡터화: 각 적립 i 의 최종 금액 = c_i × 현금 성장(t_i→d_i) × 자산 성장(d_i→T). d_i ≥ T 면 현금 그대로.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import rolling_eval as re_  # noqa: E402
from core import tax_fx as tx  # noqa: E402


def _load_mod(name: str, rel: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lab = _load_mod("core_longrun_lab", "research/jobs/core-longrun-v1/lab.py")

FX = 1300.0
FEE = 0.001
FX_SPREAD = 0.0005
CGT = 0.22
ALLOWANCE = 2_500_000.0
INTEREST_TAX = 0.154
BIG_VALUE = "BIG HiBM"

# 창 집합(긴 역사): 선택(끝 ≤ 1966), 확인(시작 ≥ 1967·끝 ≤ 2007), 2008+(끝 ≥ 2008, 보고만)
SEL_FIRST_START, SEL_END_CUTOFF = "1927-07-01", "1966-12-31"
CONF_FIRST_START, CONF_END_CUTOFF = "1967-01-01", "2007-12-31"
POST_FIRST_END = "2008-01-01"


# =================================================================================================
# 자료
# =================================================================================================

def load_long_real() -> dict[str, Any]:
    """Ken French 일별: 시장 총수익(Mkt-RF+RF)·RF·12 산업(VW)·대형 가치(25 규모×BM 의 BIG HiBM). 평일 달력."""
    from core import french_factors as ff

    ff3, i12, p25 = ff.load("ff3_daily"), ff.load("ind12_daily"), ff.load("ports25_daily")
    if ff3 is None or i12 is None or p25 is None or BIG_VALUE not in p25:
        raise RuntimeError("Ken French 일별 FF3 / 12 산업 / 25 규모×BM 자료를 받지 못함")
    out = lab._normalize(ff3["RF"], ff3["Mkt-RF"] + ff3["RF"], i12, None)
    idx = out["rf"].index
    bv = lab.to_weekdays(p25[BIG_VALUE].astype(float).to_frame("BV"))
    out["bv"] = lab.clean_industry(bv).reindex(idx)["BV"]
    out["source"] = "Ken French data library (daily, weekday calendar; FF3 market, 12 industries VW, 25 size×BM BIG HiBM VW)"
    return out


def load_long_synthetic(seed: int = 7) -> dict[str, Any]:
    d = lab.synthetic_data(seed=seed)
    idx = d["rf"].index
    rng = np.random.default_rng(seed + 3)
    bv = d["mkt"] * 1.05 + rng.normal(0.00005, 0.004, len(idx))
    return {"rf": d["rf"], "mkt": d["mkt"], "ind12": d["ind12"], "bv": pd.Series(bv, index=idx), "source": "synthetic (smoke)"}


def level(r: pd.Series) -> pd.Series:
    """일별 수익 → 가격 수준(시작 전 결측 유지)."""
    started = r.notna().cummax()
    return (1 + r.fillna(0.0)).cumprod().where(started)


# =================================================================================================
# 구간
# =================================================================================================

def window_sets(days: pd.DatetimeIndex, horizon: float, smoke: bool) -> dict[str, list]:
    step = 72 if smoke else 1   # 스모크만 6년마다 시작
    wins = re_.rolling_windows(days, horizon, step="M", first_start=SEL_FIRST_START)
    wins = wins[::step]
    sel = [w for w in wins if w[1] <= pd.Timestamp(SEL_END_CUTOFF)]
    conf = [w for w in wins if w[0] >= pd.Timestamp(CONF_FIRST_START) and w[1] <= pd.Timestamp(CONF_END_CUTOFF)]
    post = [w for w in wins if w[1] >= pd.Timestamp(POST_FIRST_END) and w[0] >= pd.Timestamp(CONF_FIRST_START)]
    return {"selection": sel, "confirmation": conf, "post2008": post}


def contribution_rows(days: pd.DatetimeIndex, s: pd.Timestamp, e: pd.Timestamp) -> np.ndarray:
    """구간 [s, e] 안의 적립 행: 첫날 + 이후 매달 첫 거래일."""
    i0, i1 = days.searchsorted(s), days.searchsorted(e, side="right") - 1
    m = lab.month_first_mask(days[i0:i1 + 1])
    m[0] = True
    return i0 + np.flatnonzero(m)


# =================================================================================================
# 계좌
# =================================================================================================

def liquidation_value(value_krw: float, cost_krw: float) -> float:
    gain = value_krw - cost_krw
    return value_krw - CGT * max(0.0, gain - ALLOWANCE)


def xirr_monthly(amounts: np.ndarray, rows: np.ndarray, end_row: int, terminal: float, days: pd.DatetimeIndex) -> float:
    flows = [(days[r], -float(a)) for r, a in zip(rows, amounts) if a > 0] + [(days[end_row], float(terminal))]
    try:
        v = tx.xirr(flows)
        return float(v) if v is not None and math.isfinite(v) else float("nan")
    except Exception:  # noqa: BLE001
        return float("nan")


def account_mdd(value_path: np.ndarray) -> float:
    """돈 가중 계좌 가치의 최대 낙폭(적립 유입 포함 — 같은 유입이라 팔끼리 비교용)."""
    v = np.asarray(value_path, dtype=float)
    if len(v) < 2:
        return 0.0
    peak = np.maximum.accumulate(v)
    return float(np.min(v / np.where(peak > 0, peak, 1.0) - 1.0))


def simulate_buy_only(px: np.ndarray, cash_growth: np.ndarray, rows: np.ndarray, amounts: np.ndarray,
                      deploy: np.ndarray, asset: np.ndarray, end_row: int, start_row: int,
                      fee: float = FEE + FX_SPREAD, want_path: bool = True) -> dict[str, float]:
    """px: (일, 자산) 가격 수준(배당 포함). cash_growth: 현금 누적 성장 지수(세후 이자).
    적립 i: 금액 amounts[i](원), 들어온 행 rows[i], 산 행 deploy[i](> end_row 면 끝까지 현금), 자산 열 asset[i].
    반환: terminal_pre(청산 전 평가), terminal(청산 세후), cost, invested_share, mdd."""
    dep = np.minimum(deploy, end_row + 1)
    bought = dep <= end_row
    a_idx = np.where(bought, asset, 0)
    dep_c = np.minimum(dep, end_row)
    # 현금 기간 성장(들어온 날 → 산 날 또는 끝)
    cash_mult = cash_growth[dep_c] / cash_growth[rows]
    usd_spent = amounts * cash_mult / FX
    units = np.where(bought, usd_spent * (1 - fee) / px[dep_c, a_idx], 0.0)
    cost_krw = float(np.sum(np.where(bought, amounts * cash_mult, 0.0)))
    end_px = px[end_row]
    eq_val = float(np.sum(units * end_px[a_idx])) * FX
    cash_left = float(np.sum(np.where(bought, 0.0, amounts * cash_growth[end_row] / cash_growth[rows])))
    pre = eq_val + cash_left
    term = liquidation_value(eq_val, cost_krw) + cash_left
    out = {"terminal_pre": pre, "terminal": term, "cost": cost_krw, "contributed": float(np.sum(amounts)),
           "invested_share": float(np.sum(amounts[bought]) / max(np.sum(amounts), 1e-9)),
           "mean_wait_days": float(np.mean(np.where(bought, dep_c - rows, end_row - rows)))}
    if want_path:
        n = end_row - start_row + 1
        u_add = np.zeros((n, px.shape[1]))
        np.add.at(u_add, (dep_c[bought] - start_row, a_idx[bought]), units[bought])
        held = np.cumsum(u_add, axis=0)
        eq_path = np.einsum("ij,ij->i", held, np.nan_to_num(px[start_row:end_row + 1])) * FX
        c_in = np.zeros(n)
        np.add.at(c_in, rows - start_row, amounts / cash_growth[rows])
        c_out = np.zeros(n)
        np.add.at(c_out, dep_c[bought] - start_row, (amounts[bought] / cash_growth[rows[bought]]))
        cash_path = np.cumsum(c_in - c_out) * cash_growth[start_row:end_row + 1]
        out["mdd"] = account_mdd(eq_path + cash_path)
    return out


# =================================================================================================
# 신호 (d 일 종가까지의 자료만)
# =================================================================================================

def drawdown(p: pd.Series) -> pd.Series:
    return p / p.cummax() - 1.0


def weekly_close(p: pd.Series) -> pd.Series:
    p = p.dropna()
    last = p.groupby(p.index.to_period("W-FRI")).apply(lambda s: s.index[-1])
    return p.loc[pd.DatetimeIndex(last.values)]


def wilder_rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    return (100 - 100 / (1 + up / dn)).where(dn > 0, 100.0).where(up.notna())


def weekly_to_daily(w: pd.Series, days: pd.DatetimeIndex) -> pd.Series:
    """주 마지막 거래일 값 → 그 주 마지막 날부터 다음 주 마지막 날 전까지(그날 종가에서 확정된 값)."""
    return w.reindex(days).ffill()


def next_true_row(flag: np.ndarray) -> np.ndarray:
    """각 행 r 에서 r 이후(r 포함) 처음 flag 가 True 인 행. 없으면 len."""
    n = len(flag)
    out = np.full(n + 1, n, dtype=np.int64)
    for r in range(n - 1, -1, -1):
        out[r] = r if flag[r] else out[r + 1]
    return out[:n]


def trailing_return(p: pd.Series, rows: int) -> pd.Series:
    return p / p.shift(rows) - 1.0


def fin(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def summarize_pairs(rows: list[dict]) -> dict[str, Any]:
    """rows: [{start,end,strategy_irr,base_irr,strategy_terminal,base_terminal,strategy_mdd,base_mdd}]."""
    if not rows:
        return {"n_windows": 0}
    d = np.array([r["strategy_irr"] - r["base_irr"] for r in rows], dtype=float)
    win = np.array([r["strategy_terminal"] > r["base_terminal"] for r in rows])
    ratio = np.array([r["strategy_terminal"] / r["base_terminal"] for r in rows], dtype=float)
    out = {"n_windows": len(rows), "share_win": float(win.mean()),
           "median_diff_irr": float(np.nanmedian(d)), "mean_diff_irr": float(np.nanmean(d)),
           "p10_diff_irr": float(np.nanpercentile(d, 10)), "p90_diff_irr": float(np.nanpercentile(d, 90)),
           "median_terminal_ratio": float(np.nanmedian(ratio)), "min_terminal_ratio": float(np.nanmin(ratio)),
           "median_strategy_irr": float(np.nanmedian([r["strategy_irr"] for r in rows])),
           "median_base_irr": float(np.nanmedian([r["base_irr"] for r in rows])),
           "first_start": rows[0]["start"], "last_end": rows[-1]["end"]}
    mm = [(r.get("strategy_mdd"), r.get("base_mdd")) for r in rows]
    if all(fin(a) and fin(b) for a, b in mm):
        out["median_strategy_mdd"] = float(np.median([a for a, _ in mm]))
        out["median_base_mdd"] = float(np.median([b for _, b in mm]))
    extra = [r.get("invested_share") for r in rows if fin(r.get("invested_share"))]
    if extra:
        out["median_invested_share"] = float(np.median(extra))
    return out
