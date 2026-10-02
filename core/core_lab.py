"""코어 R&D (2026-10-02) — 챔피언 코어(17자산 모멘텀 로테이션) 선정 방식의 변형을 한 번에 하나씩 바꿔 현 코어와 비교한다.

현 코어(C00)는 champion_strategy._build_core_weights + _compute_portfolio_returns 와 **같은 체결 모델**로 다시 만든다
(월 첫 거래일, 전날 종가 신호, 목표 비중 일정 유지·다음 날 체결, 편도 CORE_COST_BPS_PER_SIDE). 재현은 테스트가 확인한다.

바꿔 볼 수 있는 것(CoreConfig): 놀고 있는 현금을 단기국채(BIL)로, 4분할 시차 리밸런싱, 여러 기간 모멘텀 혼합, 현금보다 나을 때만
사기(듀얼 모멘텀), 상관 높은 자산 겹치지 않기, 순위 완충, 종목 수, 변동성 반비례 비중, 자산별 추세 필터, 신용 스트레스 필터(HYG/IEF).

판정(core-judge/v1)은 research/jobs/core-rnd-v1/run.py 에 고정돼 있고 이 모듈의 judge() 가 계산한다(결과를 보기 전에 고정).
주문 경로와 연결되어 있지 않다. 통과해도 챔피언에 자동 반영되지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Optional

import numpy as np
import pandas as pd

from core.champion_strategy import (
    CORE_COST_BPS_PER_SIDE,
    CORE_MOMENTUM_LOOKBACK_DAYS,
    CORE_SIZING_MAX_WEIGHT,
    CORE_SIZING_VOL_LOOKBACK_DAYS,
    CORE_TOP_N,
    CORE_UNIVERSE,
    MARKET_FILTER_EXPOSURE_CUT,
    MARKET_FILTER_SMA_WINDOW,
    MARKET_FILTER_TICKER,
)

CASH_ETF = "BIL"          # 1~3개월 미국 단기국채 ETF(2007-05 상장). 그 전에는 현금 수익 0
CREDIT_PAIR = ("HYG", "IEF")  # 하이일드/중기국채 가격비 — 신용 스트레스 대리지표(FRED 하이일드 스프레드는 최근 3년만 제공)
TRADING_DAYS = 252
JUDGE_VERSION = "core-judge/v1"

# --- 판정 기준 (core-judge/v1, 2026-10-02 고정) -------------------------------------------------------
HOLDOUT_YEARS = 2
G1_DSR = 0.95          # IS 일별 초과수익(변형 − 현 코어)의 Deflated Sharpe, 시도 수 = 등록된 변형 수
G3_MIN_SUBPERIODS = 2  # IS 를 3등분해 초과수익이 양수인 구간 수
G5_MDD_TOLERANCE = 0.05
DEFAULT_ACTIVE_SR_ANNUAL_SD = 0.5


@dataclass(frozen=True)
class CoreConfig:
    lookbacks: tuple[int, ...] = (CORE_MOMENTUM_LOOKBACK_DAYS,)  # 2개 이상이면 기간별 순위의 평균으로 줄 세운다
    abs_filter: str = "zero"        # zero: 12개월 수익률 > 0 / bil: 12개월 수익률 > 같은 기간 BIL 수익률
    top_n: int = CORE_TOP_N
    buffer_n: Optional[int] = None  # 보유 중인 자산은 순위가 이 안이면 계속 보유
    corr_cap: Optional[float] = None  # 이미 고른 자산과 상관이 이보다 높으면 건너뜀
    corr_window: int = 126
    weighting: str = "equal"        # equal(슬롯당 1/top_n) / inverse_vol
    market_filter: str = "spy200"   # spy200 / none / asset_sma / credit
    filter_window: int = MARKET_FILTER_SMA_WINDOW  # asset_sma·credit 의 이동평균 길이(거래일)
    cash: str = "zero"              # zero / bil
    tranches: int = 1               # 4 면 월 1·2·3·4주차에 하나씩 리밸런싱하는 4개 묶음의 평균
    signal_basis: str = "price"     # price: 가격(Close, 현 엔진) / total: 배당·분배금 포함 총수익(Adj Close)으로 순위·필터 계산


def _first_trading_day_mask(index: pd.DatetimeIndex, offset_days: int = 0) -> pd.Series:
    """달마다 (1일 + offset_days) 이후 첫 거래일."""
    s = pd.Series(index, index=index)
    target = s.apply(lambda d: d.replace(day=1) + pd.Timedelta(days=offset_days))
    eligible = s >= target
    period = pd.Series(index.to_period("M"), index=index)
    first = eligible & ~(eligible.groupby(period).cumsum() > 1)
    return first


def _rank_score(closes: pd.DataFrame, lookbacks: tuple[int, ...]) -> pd.DataFrame:
    """기간이 하나면 원시 모멘텀, 여럿이면 기간별 백분위 순위의 평균(클수록 좋음)."""
    if len(lookbacks) == 1:
        return closes.pct_change(lookbacks[0], fill_method=None)
    ranks = [closes.pct_change(lb, fill_method=None).rank(axis=1, pct=True) for lb in lookbacks]
    total = sum(r.fillna(0) for r in ranks)
    valid = sum(r.notna().astype(int) for r in ranks)
    out = total / len(lookbacks)
    return out.where(valid == len(lookbacks))


def _inverse_vol(window: pd.DataFrame) -> dict[str, float]:
    from core.position_sizing import portfolio_volatility_target_weights

    rets = window.pct_change(fill_method=None).dropna()
    if len(rets) < CORE_SIZING_VOL_LOOKBACK_DAYS:
        return {}
    return portfolio_volatility_target_weights(rets, max_weight=CORE_SIZING_MAX_WEIGHT)


def _tranche_weights(closes: pd.DataFrame, extra: pd.DataFrame, cfg: CoreConfig, offset_days: int) -> pd.DataFrame:
    assets = [c for c in closes.columns if c in CORE_UNIVERSE]
    score = _rank_score(closes[assets], cfg.lookbacks)
    mom12 = closes[assets].pct_change(CORE_MOMENTUM_LOOKBACK_DAYS, fill_method=None)
    bil12 = extra[CASH_ETF].pct_change(CORE_MOMENTUM_LOOKBACK_DAYS, fill_method=None) if CASH_ETF in extra else None
    spy = extra.get(MARKET_FILTER_TICKER)
    spy_sma = spy.rolling(MARKET_FILTER_SMA_WINDOW, min_periods=MARKET_FILTER_SMA_WINDOW).mean() if spy is not None else None
    asset_sma = closes[assets].rolling(cfg.filter_window, min_periods=cfg.filter_window).mean()
    credit = None
    if cfg.market_filter == "credit" and all(t in extra for t in CREDIT_PAIR):
        ratio = extra[CREDIT_PAIR[0]] / extra[CREDIT_PAIR[1]]
        credit = (ratio, ratio.rolling(cfg.filter_window, min_periods=cfg.filter_window).mean())
    rets = closes[assets].pct_change(fill_method=None)
    is_rebal = _first_trading_day_mask(closes.index, offset_days)

    cols = assets + ([CASH_ETF] if cfg.cash == "bil" else [])
    out = np.zeros((len(closes.index), len(cols)))
    last = np.zeros(len(cols))
    held: list[str] = []
    for i, dt in enumerate(closes.index):
        if is_rebal.iloc[i] and i > 0:
            sd = closes.index[i - 1]
            sc, m12 = score.loc[sd], mom12.loc[sd]
            hurdle = 0.0
            if cfg.abs_filter == "bil" and bil12 is not None and pd.notna(bil12.get(sd)):
                hurdle = float(bil12.loc[sd])
            eligible = [t for t in assets if pd.notna(sc.get(t)) and pd.notna(m12.get(t)) and m12[t] > hurdle]
            ranked = sorted(eligible, key=lambda t: (-sc[t], t))
            picks: list[str] = []
            if cfg.buffer_n:
                keep = [t for t in held if t in ranked[: cfg.buffer_n]]
                picks = sorted(keep, key=lambda t: ranked.index(t))[: cfg.top_n]
            corr = None
            if cfg.corr_cap is not None:
                corr = rets.loc[:sd].tail(cfg.corr_window).corr()
            for t in ranked:
                if len(picks) >= cfg.top_n:
                    break
                if t in picks:
                    continue
                if corr is not None and any(pd.notna(corr.at[t, p]) and corr.at[t, p] > cfg.corr_cap for p in picks):
                    continue
                picks.append(t)
            w = {t: 1.0 / cfg.top_n for t in picks}
            if cfg.weighting == "inverse_vol" and len(picks) >= 2:
                iv = _inverse_vol(closes[picks].loc[:sd].tail(CORE_SIZING_VOL_LOOKBACK_DAYS + 1))
                if iv:
                    scale = len(picks) / cfg.top_n
                    w = {t: iv.get(t, 0.0) * scale for t in picks}
            if cfg.market_filter == "spy200" and spy_sma is not None and pd.notna(spy_sma.get(sd)) and spy.loc[sd] < spy_sma.loc[sd]:
                w = {t: x * MARKET_FILTER_EXPOSURE_CUT for t, x in w.items()}
            elif cfg.market_filter == "asset_sma":
                w = {t: (0.0 if pd.notna(asset_sma.at[sd, t]) and closes.at[sd, t] < asset_sma.at[sd, t] else x) for t, x in w.items()}
            elif cfg.market_filter == "credit" and credit is not None:
                r, sma = credit
                if pd.notna(sma.get(sd)) and r.loc[sd] < sma.loc[sd]:
                    w = {t: x * MARKET_FILTER_EXPOSURE_CUT for t, x in w.items()}
            row = np.array([w.get(c, 0.0) for c in cols])
            if cfg.cash == "bil" and pd.notna(extra[CASH_ETF].get(sd)):
                row[cols.index(CASH_ETF)] = max(0.0, 1.0 - row.sum())
            last = row
            held = [t for t in picks if w.get(t, 0.0) > 0]
        out[i] = last
    return pd.DataFrame(out, index=closes.index, columns=cols)


def build_weights(closes: pd.DataFrame, extra: pd.DataFrame, cfg: CoreConfig) -> pd.DataFrame:
    """일별 목표 비중(리밸런싱일부터 다음 리밸런싱일까지 유지). tranches>1 이면 시차 묶음들의 평균."""
    offsets = [0] if cfg.tranches == 1 else [7 * k for k in range(cfg.tranches)]
    parts = [_tranche_weights(closes, extra, cfg, off) for off in offsets]
    w = sum(parts) / len(parts)
    return w


def portfolio_returns(closes: pd.DataFrame, extra: pd.DataFrame, weights: pd.DataFrame,
                      bps: float = CORE_COST_BPS_PER_SIDE) -> pd.Series:
    """champion_strategy._compute_portfolio_returns 와 같은 체결 모델(다음 날 체결, 회전율 × 편도 bp)."""
    prices = pd.concat([closes, extra], axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()][weights.columns]
    daily = prices.pct_change(fill_method=None).fillna(0.0)
    executed = weights.shift(1).fillna(0.0)
    gross = (daily * executed).sum(axis=1)
    turnover = (executed - executed.shift(1).fillna(0.0)).abs().sum(axis=1)
    return gross - turnover * (bps / 10000.0)


def run(closes: pd.DataFrame, extra: pd.DataFrame, cfg: CoreConfig, start: str,
        total: Optional[tuple[pd.DataFrame, pd.DataFrame]] = None) -> pd.Series:
    """비중은 전체 이력으로 계산하고, 수익은 start 부터 잘라서 계산한다(run_core_backtest 와 같은 순서 —
    시작일 수익 0, 둘째 날 첫 매수 비용).

    closes/extra 는 가격(Close). total=(closes, extra) 를 주면(배당·분배금 포함 Adj Close) 수익은 총수익으로 재고,
    cfg.signal_basis == "total" 이면 순위·필터도 총수익으로 계산한다. total 이 없으면 현 엔진처럼 가격 기준.
    """
    sig = total if (total is not None and cfg.signal_basis == "total") else (closes, extra)
    w = build_weights(sig[0], sig[1], cfg)
    rc, re = total if total is not None else (closes, extra)
    keep = rc.index >= pd.Timestamp(start)
    return portfolio_returns(rc[keep], re[keep], w.reindex(rc.index).fillna(0.0)[keep])


# =================================================================================================
# 통계·심판
# =================================================================================================

def stats(r: pd.Series) -> dict[str, Any]:
    r = r.dropna()
    n = len(r)
    if n < 2:
        return {"n_days": n}
    mean, sd = float(r.mean()), float(r.std(ddof=1))
    eq = (1 + r).cumprod()
    z = (r - mean) / sd if sd > 0 else r * 0
    sr = mean / sd if sd > 0 else 0.0
    return {"n_days": n, "sharpe_daily": sr, "sharpe_annual": sr * math.sqrt(TRADING_DAYS),
            "cagr": float(eq.iloc[-1] ** (TRADING_DAYS / n) - 1), "ann_vol": sd * math.sqrt(TRADING_DAYS),
            "max_drawdown": float((eq / eq.cummax() - 1).min()), "skew": float((z ** 3).mean()),
            "kurtosis": float((z ** 4).mean()), "total_return": float(eq.iloc[-1] - 1)}


def holdout_split(index: pd.DatetimeIndex) -> pd.Timestamp:
    return index[-1] - pd.DateOffset(years=HOLDOUT_YEARS)


def _r(d: dict, n: int = 4) -> dict:
    return {k: (round(v, n) if isinstance(v, float) else v) for k, v in d.items()}


def judge(variant: dict[str, pd.Series], incumbent: pd.Series, neighbors: list[pd.Series], *,
          n_trials: int, all_active_daily_srs: list[float]) -> dict:
    """core-judge/v1. variant: {"returns": Series}. 모든 관문을 넘어야 PASS(= 사람 검토 대기)."""
    from core.hypothesis_judge import deflated_sharpe

    r = variant["returns"]
    both = pd.concat([r.rename("v"), incumbent.rename("b")], axis=1).fillna(0.0)
    active = both["v"] - both["b"]
    split = holdout_split(both.index)
    is_mask = both.index < split
    a_is, a_oos = stats(active[is_mask]), stats(active[~is_mask])
    v_is, v_oos = stats(both["v"][is_mask]), stats(both["v"][~is_mask])
    b_is, b_oos = stats(both["b"][is_mask]), stats(both["b"][~is_mask])
    reasons: list[str] = []
    gates: dict[str, dict] = {}

    # 분산은 고정 가정(연 0.5)을 쓴다 — 관측 분산을 쓰면 극단값 하나(예: 현금→BIL 처럼 작지만 매우 꾸준한 초과수익)가
    # 다른 모든 변형의 기준을 올린다(합성 데이터 스모크에서 발견, 실제 데이터 결과를 보기 전 2026-10-02 수정).
    # all_active_daily_srs 는 보고용으로만 받는다.
    variance = (DEFAULT_ACTIVE_SR_ANNUAL_SD / math.sqrt(TRADING_DAYS)) ** 2
    dsr = deflated_sharpe(a_is.get("sharpe_daily", 0.0), a_is.get("n_days", 0), a_is.get("skew", 0.0),
                          a_is.get("kurtosis", 3.0), max(n_trials, 1), variance)
    g1 = dsr["dsr"] >= G1_DSR
    gates["G1_improves_corrected"] = {"pass": g1, "dsr": round(dsr["dsr"], 4), "threshold": G1_DSR, "n_trials": n_trials,
                                      "active_sharpe_annual": round(a_is.get("sharpe_annual", 0.0), 3),
                                      "active_ann_return": round(float(active[is_mask].mean() * TRADING_DAYS), 5)}
    if not g1:
        reasons.append(f"G1 IS 초과수익 DSR {dsr['dsr']:.2f} < {G1_DSR} (시도 {n_trials})")

    g2 = v_oos.get("sharpe_annual", 0.0) >= b_oos.get("sharpe_annual", 0.0)
    gates["G2_holdout"] = {"pass": g2, "split": split.date().isoformat(), "oos_sharpe": round(v_oos.get("sharpe_annual", 0.0), 3),
                           "incumbent_oos_sharpe": round(b_oos.get("sharpe_annual", 0.0), 3)}
    if not g2:
        reasons.append(f"G2 떼어 둔 2년 샤프 {v_oos.get('sharpe_annual', 0.0):.2f} < 현 코어 {b_oos.get('sharpe_annual', 0.0):.2f}")

    is_idx = both.index[is_mask]
    thirds = np.array_split(np.arange(len(is_idx)), 3)
    sub = [float(active[is_mask].iloc[t].sum()) for t in thirds if len(t)]
    g3 = sum(1 for x in sub if x > 0) >= G3_MIN_SUBPERIODS
    gates["G3_subperiods"] = {"pass": g3, "active_sum_by_third": [round(x, 4) for x in sub],
                              "periods": [f"{is_idx[t[0]].date()}~{is_idx[t[-1]].date()}" for t in thirds if len(t)]}
    if not g3:
        reasons.append(f"G3 IS 3구간 중 초과수익 양수 {sum(1 for x in sub if x > 0)}개 < {G3_MIN_SUBPERIODS}")

    nb = []
    for n_r in neighbors:
        nb_both = pd.concat([n_r.rename("v"), incumbent.rename("b")], axis=1).fillna(0.0)
        nb_act = (nb_both["v"] - nb_both["b"])[nb_both.index < split]
        nb.append(round(stats(nb_act).get("sharpe_annual", 0.0), 3))
    g4 = all(x > 0 for x in nb) if nb else True
    gates["G4_neighbors"] = {"pass": g4, "neighbor_active_sharpe": nb, "note": None if nb else "이웃 설정 없음 — 생략"}
    if not g4:
        reasons.append(f"G4 이웃 설정 초과 샤프 {nb}")

    g5 = v_is.get("max_drawdown", 0.0) >= b_is.get("max_drawdown", 0.0) - G5_MDD_TOLERANCE
    gates["G5_drawdown"] = {"pass": g5, "is_mdd": round(v_is.get("max_drawdown", 0.0), 3),
                            "incumbent_is_mdd": round(b_is.get("max_drawdown", 0.0), 3)}
    if not g5:
        reasons.append(f"G5 IS 최대낙폭 {v_is.get('max_drawdown', 0.0):.1%} (현 코어 {b_is.get('max_drawdown', 0.0):.1%})")

    full_v, full_b = stats(both["v"]), stats(both["b"])
    return {"judge_version": JUDGE_VERSION, "verdict": "PASS" if not reasons else "FAIL", "reasons": reasons, "gates": gates,
            "stats": {"is": _r(v_is), "oos": _r(v_oos), "full": _r(full_v)},
            "incumbent": {"is": _r(b_is), "oos": _r(b_oos), "full": _r(full_b)}}


def config_dict(cfg: CoreConfig) -> dict:
    d = asdict(cfg)
    d["lookbacks"] = list(cfg.lookbacks)
    return d


def with_changes(cfg: CoreConfig, **kw) -> CoreConfig:
    if "lookbacks" in kw:
        kw["lookbacks"] = tuple(kw["lookbacks"])
    return replace(cfg, **kw)
