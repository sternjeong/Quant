"""여러 시작일 × 월 적립으로 전략과 SPY 를 세후로 비교 (2026-10-17, 사용자 요청).

왜: 사용자는 처음 목돈(기본 시나리오 1,000만 원) + 매달 적립(15만 원)으로 이 엔진을 끝없이 굴리고, 세후로 SPY 를 이기고 싶다.
지금까지 연구는 한 시작일에 목돈 한 번만 넣고 쟀다. 시작일 운과 적립 효과를 빼고 보려면, 많은 시작일(매달 첫 거래일)에서
같은 기간(예: 10년)을 굴려 '몇 번 중 몇 번 SPY 보다 많이 남았나'를 본다.

구성:
  rolling_windows   — 매달(또는 분기·해마다) 첫 거래일에 시작해 horizon_years 뒤 마지막 거래일에 끝나는 구간들(데이터 안에서 끝나는 것만).
  evaluate_windows  — 구간마다 core/tax_fx.simulate 로 전략과 기준(SPY 그냥 보유)을 같은 계좌 설정·같은 적립금·같은 적립 정책으로 굴린다.
                      캐시(dict·파일)로 이어 하기: 시간 예산이 끝나면 complete=False 로 돌아오고, 호출한 연구는 종료 코드 3 으로 멈췄다가
                      다음 실행에서 이어 한다.
  summarize         — 1차 통계: 전략의 청산 후 최종 금액이 기준보다 큰 구간의 비율. IRR 차이의 중앙값·평균·10/90 분위, 최악 구간.
                      구간이 서로 크게 겹치므로 '겹치지 않는 구간 수 = 전체 기간 / 구간 길이'를 함께 낸다.
  index_sim         — 프렌치 지수처럼 긴 수익률 표용 가벼운 세전 시뮬레이터(적립금 = 처음 금액 대비 비율).
                      approx_tax=True 면 sector-concentrate-v1 과 같은 '근사' 한국 세금(1달러 = 1,300원 고정, 공제 250만 원, 22%, 이월 없음).

낙폭 두 가지:
  mdd_mw (돈 기준) — 계좌 평가액(적립금 포함) 자체의 최대 낙폭. 사용자가 계좌에서 보는 숫자. 적립금이 쌓이면 나중 낙폭이 작아 보인다.
  mdd_tw (시간가중) — 그날 수익 = 오늘 평가액 / (전날 평가액 + 오늘 넣은 돈) − 1 을 이어 붙인 지수의 최대 낙폭. 전략 자체의 낙폭.

속도(VM 기준, 2026-10-17 측정): tax_fx.simulate 는 하루 × 종목 파이썬 반복이라 10년(약 2,500 거래일) 구간 하나에
  SPY 그냥 보유 약 0.2초, 종목 3~10개를 매달 바꾸는 전략 약 0.4~1.5초. 10년 구간 매달 시작 × 25년 데이터 ≈ 180구간 → 전략 하나
  수 분. 목표 비중은 전체 기간에 한 번 계산한 표를 넘기면 구간마다 잘라 쓴다(다시 계산하지 않는다). 결과는 구간마다 숫자 몇 개만
  남기므로 메모리는 작다(시뮬레이션 일별 출력은 버린다).
주문 경로와 연결되어 있지 않다. 세금은 추정이다.
"""

from __future__ import annotations

import math
import os
import pickle
import time
from pathlib import Path
from typing import Any, Callable, Optional, Union

import numpy as np
import pandas as pd

from core import tax_fx as tx

APPROX_FX = 1300.0           # sector-concentrate-v1 과 같은 고정 환율(근사)
APPROX_INITIAL_KRW = 10_000_000  # 근사 세금용 기본 처음 금액(사용자 기본 시나리오)
APPROX_LABEL = ("APPROXIMATE Korean tax: core/tax_fx.simulate on index levels (close = adj, no dividends), "
                "fixed 1,300 KRW/USD, 2.5M KRW allowance, 22%, no loss carry-forward, fee = cost_bps, no FX spread")

_STEP_MONTHS = {"M": 1, "Q": 3, "A": 12, "Y": 12}


# ------------------------------------------------------------------------------------------------- 구간
def rolling_windows(trading_days, horizon_years: float, step: Union[str, int] = "M",
                    first_start=None, last_start=None) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(시작, 끝) 목록. 시작 = 달의 첫 거래일(데이터 첫날은 그달 4일 안이면 첫 거래일로 친다), step 개월마다.
    끝 = 시작 + horizon_years(개월 단위로 반올림) 이하의 마지막 거래일. 끝 목표일이 데이터 마지막 날보다 뒤면 넣지 않는다."""
    days = pd.DatetimeIndex(pd.to_datetime(trading_days)).sort_values().unique()
    if len(days) < 2:
        return []
    k = _STEP_MONTHS[step] if isinstance(step, str) else int(step)
    months = int(round(float(horizon_years) * 12))
    if months <= 0 or k <= 0:
        raise ValueError("horizon_years 와 step 은 양수여야 합니다.")
    firsts = days[tx.contribution_days(days)]
    if days[0].day <= 4:
        firsts = firsts.insert(0, days[0])
    if first_start is not None:
        firsts = firsts[firsts >= pd.Timestamp(first_start)]
    if last_start is not None:
        firsts = firsts[firsts <= pd.Timestamp(last_start)]
    out, anchor = [], None
    for s in firsts:
        m = s.year * 12 + s.month
        if anchor is not None and (m - anchor) % k:
            continue
        anchor = m if anchor is None else anchor
        target = s + pd.DateOffset(months=months)
        if target > days[-1]:
            break
        end = days[days <= target][-1]
        if end > s:
            out.append((s, end))
    return out


# ------------------------------------------------------------------------------------------------- 지표
def max_drawdown(s: pd.Series) -> float:
    s = pd.Series(s, dtype=float)
    return float((s / s.cummax() - 1).min()) if len(s) else float("nan")


def _summ(sim: dict) -> dict[str, float]:
    return {"terminal_krw": float(sim["terminal_after_liquidation_krw"]),
            "irr": float(sim["irr_after_liquidation"]),
            "irr_pre": float(sim["irr_pre_cost"]),
            "mdd_mw": max_drawdown(sim["values_krw"]),
            "mdd_tw": max_drawdown(sim["twr_index"]),
            "total_contributed_krw": float(sim["total_contributed_krw"]),
            "capital_gains_tax_krw": float(sim["totals"]["capital_gains_tax_krw"]),
            "unpaid_tax_if_sold_now_krw": float(sim["unpaid_tax_if_sold_now_krw"])}


def _key(kind: str, start, end) -> str:
    return f"{kind}|{pd.Timestamp(start).date()}|{pd.Timestamp(end).date()}"


def _load_cache(path: Optional[Path], fingerprint) -> dict:
    if path is None or not Path(path).exists():
        return {}
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        if obj.get("fingerprint") == fingerprint:
            return dict(obj.get("entries") or {})
    except Exception:  # noqa: BLE001 — 깨진 캐시는 버리고 새로 계산
        pass
    return {}


def _save_cache(path: Path, fingerprint, entries: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump({"fingerprint": fingerprint, "entries": entries}, f)
    os.replace(tmp, path)


def evaluate_windows(build_weights: Union[pd.DataFrame, Callable[[pd.Timestamp, pd.Timestamp], pd.DataFrame]],
                     panels: dict, windows: list, cfg_factory: Union[tx.AccountConfig, Callable[..., tx.AccountConfig]],
                     benchmark_weights_fn: Optional[Callable[[pd.DatetimeIndex], pd.DataFrame]] = None, *,
                     cache: Optional[dict] = None, cache_path: Optional[Union[str, Path]] = None,
                     benchmark_cache: Optional[dict] = None, fingerprint: Any = None,
                     max_new: Optional[int] = None, deadline: Optional[float] = None,
                     log: Optional[Callable[[str], None]] = None) -> dict[str, Any]:
    """구간마다 전략·기준을 tax_fx.simulate 로 굴린다.
    build_weights: 전체 기간 목표 비중 표(구간마다 .loc[시작:끝] 으로 자른다 — 첫 행이 첫 매수) 또는 (시작, 끝) → 표 함수.
    panels: {"close", "adj", "fx"} (tax_fx.simulate 와 같은 뜻). cfg_factory: AccountConfig 또는 (시작, 끝) → AccountConfig.
      전략과 기준이 같은 설정(같은 처음 금액·적립금·적립 정책)을 쓴다.
    benchmark_weights_fn: 거래일 → 기준 목표 비중(기본 SPY 그냥 보유). 기준은 전략 구간과 같은 거래일로 굴린다(적립일이 같다).
    cache: 결과를 담을 dict(호출자가 들고 있다가 다시 넘기면 이어 한다). cache_path: 파일 캐시(pickle, 새 계산마다 원자적 저장,
      fingerprint 가 다르면 버린다). benchmark_cache: 기준 결과를 여러 전략이 함께 쓰려면 같은 dict 를 넘긴다(없으면 cache 에 넣는다).
    max_new / deadline(time.monotonic() 값): 새 시뮬레이션 수·시간 한도 — 넘으면 멈추고 complete=False.
    반환: {"rows": [구간별 결과(계산된 것만, windows 순서)], "complete", "done", "pending", "new_sims"}.
    구간별 결과: start, end, years, strategy{...}, benchmark{...}, diff_terminal_krw, terminal_ratio, diff_irr, win."""
    bench_fn = benchmark_weights_fn or (lambda idx: tx.buy_and_hold_weights(idx, "SPY"))
    path = Path(cache_path) if cache_path is not None else None
    entries = cache if cache is not None else {}
    if path is not None:
        for k, v in _load_cache(path, fingerprint).items():
            entries.setdefault(k, v)
    bcache = benchmark_cache if benchmark_cache is not None else entries
    new, rows, stopped = 0, [], False

    def weights_for(s, e) -> pd.DataFrame:
        if isinstance(build_weights, pd.DataFrame):
            return build_weights.loc[pd.Timestamp(s): pd.Timestamp(e)]
        return build_weights(pd.Timestamp(s), pd.Timestamp(e))

    def cfg_for(s, e) -> tx.AccountConfig:
        return cfg_factory if isinstance(cfg_factory, tx.AccountConfig) else cfg_factory(pd.Timestamp(s), pd.Timestamp(e))

    def budget_left() -> bool:
        if max_new is not None and new >= max_new:
            return False
        return deadline is None or time.monotonic() < deadline

    for s, e in windows:
        ks, kb = _key("S", s, e), _key("B", s, e)
        need = [k for k, c in ((ks, entries), (kb, bcache)) if k not in c]
        if need and not budget_left():
            stopped = True
            break
        w = None
        if ks not in entries or kb not in bcache:
            w = weights_for(s, e)
            w = w.loc[:, w.abs().sum() > 0] if len(w.columns) else w
            cfg = cfg_for(s, e)
        if ks not in entries:
            entries[ks] = _summ(tx.simulate(w, panels["close"], panels["adj"], panels["fx"], cfg))
            new += 1
            if path is not None:
                _save_cache(path, fingerprint, entries)
        if kb not in bcache:
            bench_w = bench_fn(w.index)
            bcache[kb] = _summ(tx.simulate(bench_w, panels["close"], panels["adj"], panels["fx"], cfg))
            new += 1
            if path is not None and bcache is entries:
                _save_cache(path, fingerprint, entries)
        st, bm = entries[ks], bcache[kb]
        rows.append({"start": str(pd.Timestamp(s).date()), "end": str(pd.Timestamp(e).date()),
                     "years": (pd.Timestamp(e) - pd.Timestamp(s)).days / 365.25,
                     "strategy": st, "benchmark": bm,
                     "diff_terminal_krw": st["terminal_krw"] - bm["terminal_krw"],
                     "terminal_ratio": st["terminal_krw"] / bm["terminal_krw"] if bm["terminal_krw"] > 0 else float("nan"),
                     "diff_irr": st["irr"] - bm["irr"],
                     "win": bool(st["terminal_krw"] > bm["terminal_krw"])})
        if log and w is not None:
            log(f"구간 {rows[-1]['start']}~{rows[-1]['end']} IRR 차이 {rows[-1]['diff_irr']:+.4f}")
    done = len(rows)
    return {"rows": rows, "complete": not stopped and done == len(windows), "done": done,
            "pending": len(windows) - done, "new_sims": new}


def summarize(results: Union[dict, list], horizon_years: Optional[float] = None) -> dict[str, Any]:
    """1차 통계 share_terminal_win(전략 최종 금액 > 기준 최종 금액인 구간 비율) 과 IRR 차이 분포.
    구간이 겹치므로 독립 표본이 아니다 — effective_independent_windows = 전체 기간 / 구간 길이 를 함께 본다."""
    rows = results["rows"] if isinstance(results, dict) else list(results)
    n = len(rows)
    if n == 0:
        return {"n_windows": 0, "share_terminal_win": None}
    d = np.array([r["diff_irr"] for r in rows], dtype=float)
    ratio = np.array([r["terminal_ratio"] for r in rows], dtype=float)
    hz = float(horizon_years) if horizon_years else float(np.mean([r["years"] for r in rows]))
    span = (pd.Timestamp(max(r["end"] for r in rows)) - pd.Timestamp(min(r["start"] for r in rows))).days / 365.25
    worst = rows[int(np.nanargmin(d))]
    best = rows[int(np.nanargmax(d))]

    def pick(r):
        return {"start": r["start"], "end": r["end"], "diff_irr": r["diff_irr"], "terminal_ratio": r["terminal_ratio"],
                "strategy_irr": r["strategy"]["irr"], "benchmark_irr": r["benchmark"]["irr"]}

    eff = span / hz if hz > 0 else float("nan")
    return {
        "n_windows": n,
        "share_terminal_win": float(np.mean([r["win"] for r in rows])),
        "median_diff_irr": float(np.nanmedian(d)), "mean_diff_irr": float(np.nanmean(d)),
        "p10_diff_irr": float(np.nanpercentile(d, 10)), "p90_diff_irr": float(np.nanpercentile(d, 90)),
        "median_terminal_ratio": float(np.nanmedian(ratio)), "min_terminal_ratio": float(np.nanmin(ratio)),
        "median_strategy_irr": float(np.nanmedian([r["strategy"]["irr"] for r in rows])),
        "median_benchmark_irr": float(np.nanmedian([r["benchmark"]["irr"] for r in rows])),
        "median_strategy_mdd_tw": float(np.nanmedian([r["strategy"]["mdd_tw"] for r in rows])),
        "median_benchmark_mdd_tw": float(np.nanmedian([r["benchmark"]["mdd_tw"] for r in rows])),
        "worst_window": pick(worst), "best_window": pick(best),
        "horizon_years": hz, "span_years": span, "effective_independent_windows": eff,
        "overlap_caveat": (f"{n} windows overlap heavily; only about {eff:.1f} non-overlapping {hz:g}-year windows fit in "
                           f"{span:.1f} years, so the win share is far less certain than {n} independent trials would suggest."),
    }


# ------------------------------------------------------------------------------------------------- 지수 시뮬레이터
def _as_weight_frame(weights, index: pd.DatetimeIndex, columns) -> pd.DataFrame:
    if isinstance(weights, pd.DataFrame):
        return weights.reindex(index=index, columns=columns).ffill().fillna(0.0)
    s = pd.Series(weights, dtype=float).reindex(columns).fillna(0.0)
    return pd.DataFrame(np.tile(s.to_numpy(), (len(index), 1)), index=index, columns=columns)


def index_sim(returns_by_asset: pd.DataFrame, weights, contributions_ratio_per_month: float = 0.0, *,
              policy: str = "underweight_first", initial: float = 1.0, cost_bps: float = 0.0,
              approx_tax: bool = False, tax_initial_krw: float = APPROX_INITIAL_KRW,
              fx_const: float = APPROX_FX) -> dict[str, Any]:
    """긴 지수 수익률 표(날짜 × 자산, 단순 수익률)용 가벼운 세전 시뮬레이터.
    weights: 같은 날짜의 목표 비중 표(목표가 바뀌는 날 그날 종가에 맞춘다 — 그날 수익은 전날 보유로) 또는 고정 비중(dict/Series:
      첫날 사고 그 뒤로는 적립금으로만 맞춘다). 첫날은 항상 목표대로 산다.
    적립금 = contributions_ratio_per_month × initial, 시작일 다음 달부터 매달 첫 행에(tax_fx 와 같은 규칙·같은 정책).
    cost_bps: 리밸런싱 매매대금·적립 매수액에 편도로 뗀다.
    approx_tax=True: 같은 비중을 core/tax_fx.simulate 로 '근사' 한국 세금과 함께 굴린 결과를 approx_tax 에 넣는다
      (지수 수준을 가격으로, 1달러 = 1,300원 고정, 공제 250만 원·22%·이월 없음, 처음 tax_initial_krw 원 + 매달 비율 × 그 금액).
      공제가 원화 금액이라 결과는 금액 규모에 따라 달라진다. 근사일 뿐이다(APPROX_LABEL)."""
    r = returns_by_asset.astype(float)
    idx, cols = r.index, list(r.columns)
    W = _as_weight_frame(weights, idx, cols)
    change = (W.diff().abs().sum(axis=1) > 1e-9).to_numpy()
    change[0] = True
    Wv, R = W.to_numpy(dtype=float), r.fillna(0.0).to_numpy(dtype=float)
    cday = tx.contribution_days(idx)
    c_amt = float(contributions_ratio_per_month) * float(initial)
    flows = np.where(cday, c_amt, 0.0) if c_amt > 0 else np.zeros(len(idx))
    fee = float(cost_bps) / 10000.0
    h, cash = np.zeros(len(cols)), float(initial)
    vals = np.empty(len(idx))
    for i in range(len(idx)):
        if i > 0:
            h = h * (1 + R[i])
        if flows[i] > 0:
            cash += flows[i]
            if not change[i]:
                a = tx.allocate_contribution(policy, Wv[i], h, h.sum() + cash, cash, flows[i])
                h = h + a * (1 - fee)
                cash -= a.sum()
        if change[i]:
            tot = h.sum() + cash
            turnover = np.abs(Wv[i] * tot - h).sum()
            tot -= fee * turnover
            h = Wv[i] * tot
            cash = tot - h.sum()
        vals[i] = h.sum() + cash
    values = pd.Series(vals, index=idx)
    fl = pd.Series(flows, index=idx)
    cf = [(idx[0], -float(initial))] + [(d, -float(a)) for d, a in fl[fl > 0].items()] + [(idx[-1], float(vals[-1]))]
    twr = tx._twr(values, fl)
    out = {"values": values, "contributions": fl, "cumulative_contributed": float(initial) + fl.cumsum(),
           "total_contributed": float(initial + fl.sum()), "terminal": float(vals[-1]),
           "irr": tx.xirr(cf), "twr_index": twr, "mdd_mw": max_drawdown(values), "mdd_tw": max_drawdown(twr),
           "approx_tax": None}
    if approx_tax:
        out["approx_tax"] = approx_tax_sim(r, W, contributions_ratio_per_month, policy=policy, cost_bps=cost_bps,
                                           initial_krw=tax_initial_krw, fx_const=fx_const)
    return out


def approx_tax_sim(returns_by_asset: pd.DataFrame, weights: pd.DataFrame, contributions_ratio_per_month: float = 0.0, *,
                   policy: str = "underweight_first", cost_bps: float = 0.0, initial_krw: float = APPROX_INITIAL_KRW,
                   fx_const: float = APPROX_FX) -> dict[str, Any]:
    """index_sim(approx_tax=True) 의 근사 세금 부분(sector-concentrate-v1 tax_inputs/tax_drag 와 같은 근사 + 적립금).
    세금 없이(apply_tax=False) 같은 계좌도 굴려 세금 차이를 낸다. 금액은 원화, *_ratio 는 처음 금액 대비."""
    lev = (1 + returns_by_asset.fillna(0.0).astype(float)).cumprod()
    fx = pd.Series(float(fx_const), index=lev.index)
    w = weights.reindex(index=lev.index, columns=lev.columns).fillna(0.0)
    res = {"label": APPROX_LABEL, "initial_krw": float(initial_krw),
           "monthly_contribution_krw": float(contributions_ratio_per_month) * float(initial_krw)}
    for key, apply in (("no_tax", False), ("tax", True)):
        cfg = tx.AccountConfig(initial_krw=float(initial_krw), fee_rate=float(cost_bps) / 10000.0, fx_spread=0.0,
                               apply_tax=apply, apply_dividend_tax=False,
                               monthly_contribution_krw=res["monthly_contribution_krw"], contribution_policy=policy)
        s = tx.simulate(w, lev, lev, fx, cfg)
        res[key] = {"terminal_after_liquidation_krw": s["terminal_after_liquidation_krw"],
                    "terminal_ratio": s["terminal_after_liquidation_krw"] / float(initial_krw),
                    "irr_after_liquidation": s["irr_after_liquidation"],
                    "capital_gains_tax_krw": s["totals"]["capital_gains_tax_krw"],
                    "unpaid_tax_if_sold_now_krw": s["unpaid_tax_if_sold_now_krw"]}
        res["total_contributed_krw"] = s["total_contributed_krw"]
    a, b = res["tax"]["irr_after_liquidation"], res["no_tax"]["irr_after_liquidation"]
    res["irr_tax_drag"] = b - a if math.isfinite(a) and math.isfinite(b) else float("nan")
    return res
