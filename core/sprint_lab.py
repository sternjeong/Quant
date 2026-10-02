"""2주 R&D 스프린트 (2026-10-02 ~ 2026-10-16) — 넓은 탐색 + 과적합 방지 장치.

사용자 지시: "여러 가설을 스스로 세워 2주 동안 매일 돌려 최적값을 찾아라" + "코어도 언제 팔아야 할지 정량화".
계속 많이 시도하면 우연히 좋아 보이는 조합이 반드시 나오므로, 탐색은 넓게 하되 선택은 엄격하게 한다:
  1) 앞 구간(IS, 마지막 2년 전까지)에서만 최선을 고른다.
  2) 시도 수를 반영한 Deflated Sharpe(DSR) — 'N 번 무작위로 시도했을 때 기대되는 최대치'를 넘어야 한다.
  3) CSCV 로 과적합 확률(PBO, Bailey·Borwein·López de Prado·Zhu 2016)을 잰다 — IS 최선이 다른 구간에서 중앙값 아래로 떨어지는 비율.
  4) 떼어 둔 마지막 2년은 탐색이 끝난 뒤 승자 하나에 대해 한 번만 본다.

가족:
  F1 새틀라이트 선정(신호·종목 수·보유기간·손절·풀)   — core.satellite_lab 시뮬레이터
  F2 코어 선정(기간·종목 수·필터·상관 제한·순위 완충)   — core.core_lab
  F3 코어 보유 중 매도(트레일링스탑·이동평균 이탈·모멘텀 음전환·순위 이탈·주간 SPY 점검) — 이 모듈 apply_core_exits
  F4 사고파는 가격(지정가·분할·눌림목·익절)            — core.execution_lab 매매 목록
판정 sprint-judge/v1 은 research/jobs/sprint-2w/run.py 에 고정. 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

JUDGE_VERSION = "sprint-judge/v1"
DSR_MIN = 0.95
PBO_MAX = 0.25
CSCV_BLOCKS = 8
TRADING_DAYS = 252


# =================================================================================================
# 과적합 측정
# =================================================================================================

def sharpe_cols(m: np.ndarray) -> np.ndarray:
    mu = np.nanmean(m, axis=0)
    sd = np.nanstd(m, axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, mu / sd, 0.0)


def cscv_pbo(m: np.ndarray, blocks: int = CSCV_BLOCKS) -> Optional[dict]:
    """m: 행=시간(일 또는 리밸런싱 날짜), 열=설정. IS 절반 블록에서 최선이 나머지 절반에서 중앙값 아래인 비율."""
    t, n = m.shape
    if n < 2 or t < blocks * 5:
        return None
    parts = np.array_split(np.arange(t), blocks)
    logits = []
    for combo in itertools.combinations(range(blocks), blocks // 2):
        is_idx = np.concatenate([parts[k] for k in combo])
        oos_idx = np.concatenate([parts[k] for k in range(blocks) if k not in combo])
        best = int(np.argmax(sharpe_cols(m[is_idx])))
        oos = sharpe_cols(m[oos_idx])
        rank = (np.sum(oos < oos[best]) + 0.5 * (np.sum(oos == oos[best]) - 1)) / (n - 1)  # 0~1, 높을수록 좋음
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1 - rank)))
    lg = np.array(logits)
    return {"pbo": float(np.mean(lg <= 0)), "n_splits": len(lg), "median_logit": float(np.median(lg))}


def deflated(sr_daily: float, n_days: int, skew: float, kurt: float, n_trials: int, srs_daily: list[float]) -> dict:
    """hypothesis_judge.deflated_sharpe 를 쓰되, 시도 간 분산은 이 가족에서 실제로 시도한 설정들의 샤프 분산."""
    from statistics import pvariance

    from core.hypothesis_judge import deflated_sharpe

    var = pvariance(srs_daily) if len(srs_daily) >= 2 else (0.5 / math.sqrt(TRADING_DAYS)) ** 2
    return deflated_sharpe(sr_daily, n_days, skew, kurt, max(n_trials, 1), var)


def moments(r: np.ndarray) -> dict:
    r = r[~np.isnan(r)]
    if len(r) < 3:
        return {"n": len(r), "sr": 0.0, "skew": 0.0, "kurt": 3.0}
    mu, sd = r.mean(), r.std(ddof=1)
    z = (r - mu) / sd if sd > 0 else r * 0
    return {"n": len(r), "sr": float(mu / sd) if sd > 0 else 0.0, "skew": float((z ** 3).mean()), "kurt": float((z ** 4).mean())}


def finalize_returns_family(names: list[str], mat: np.ndarray, index: pd.DatetimeIndex, split: pd.Timestamp,
                            incumbent: str, *, periods_per_year: int = TRADING_DAYS) -> dict:
    """F1~F3: mat = 일별 수익(행=날짜, 열=설정). 선택은 IS, 떼어 둔 구간은 승자·현 규칙에 한 번."""
    is_mask = np.asarray(index < split)
    inc = names.index(incumbent)
    is_m = mat[is_mask]
    srs = sharpe_cols(is_m)
    order = np.argsort(-srs)
    win = int(order[0])
    active = is_m[:, win] - is_m[:, inc]
    mo = moments(active)
    act_srs = list(sharpe_cols(is_m - is_m[:, [inc]]))
    dsr = deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], len(names), [x for i, x in enumerate(act_srs) if i != inc])
    pbo = cscv_pbo(is_m)
    oos = mat[~is_mask]

    def ann(col: np.ndarray, part: np.ndarray) -> dict:
        c = part[:, col] if part.ndim == 2 else part
        c = c[~np.isnan(c)]
        if len(c) < 2:
            return {}
        eq = np.cumprod(1 + c)
        return {"sharpe": float(c.mean() / c.std(ddof=1) * math.sqrt(periods_per_year)) if c.std(ddof=1) > 0 else 0.0,
                "cagr": float(eq[-1] ** (periods_per_year / len(c)) - 1), "mdd": float((eq / np.maximum.accumulate(eq) - 1).min())}

    win_oos, inc_oos = ann(win, oos), ann(inc, oos)
    reasons = []
    if win == inc:
        reasons.append("앞 구간 최선이 현 규칙 자신")
    if dsr["dsr"] < DSR_MIN:
        reasons.append(f"DSR {dsr['dsr']:.2f} < {DSR_MIN} (시도 {len(names)})")
    if pbo is None or pbo["pbo"] > PBO_MAX:
        reasons.append(f"과적합 확률 PBO {('—' if pbo is None else f'{pbo['pbo']:.0%}')} > {PBO_MAX:.0%}")
    if not win_oos or not inc_oos or win_oos["sharpe"] <= inc_oos["sharpe"]:
        reasons.append(f"떼어 둔 2년 샤프 {win_oos.get('sharpe', float('nan')):.2f} ≤ 현 규칙 {inc_oos.get('sharpe', float('nan')):.2f}")
    top = []
    for i in order[:10]:
        top.append({"config": names[i], "is": ann(int(i), is_m), "oos": ann(int(i), oos)})
    inc_rank = int(np.where(order == inc)[0][0]) + 1
    return {"judge_version": JUDGE_VERSION, "n_configs": len(names), "winner": names[win], "incumbent": incumbent,
            "incumbent_is_rank": inc_rank, "winner_is": ann(win, is_m), "incumbent_is": ann(inc, is_m),
            "winner_oos": win_oos, "incumbent_oos": inc_oos, "dsr": round(dsr["dsr"], 4), "pbo": pbo,
            "verdict": "CANDIDATE" if not reasons else "KEEP_CURRENT", "reasons": reasons, "top10": top}


def finalize_execution_family(cells: dict[str, pd.DataFrame], split: pd.Timestamp) -> dict:
    """F4: cells[(슬리브|방향)] = 행=리밸런싱 날짜, 열=규칙(기준 'base' 포함, 값=그날 가중 평균 개선). 칸마다 승자 하나."""
    out = {}
    for key, df in cells.items():
        df = df.sort_index()
        names = list(df.columns)
        mat = df.to_numpy(dtype=float)
        is_mask = np.asarray(df.index < split)
        is_m = np.nan_to_num(mat[is_mask])
        means = is_m.mean(axis=0)
        win = int(np.argmax(means))
        mo = moments(is_m[:, win])
        # 개선량 자체가 '현 규칙 대비 초과'이므로 그 평균/표준편차를 샤프처럼 본다(기준 열 base 는 0).
        dsr = deflated(mo["sr"], mo["n"], mo["skew"], mo["kurt"], len(names), list(sharpe_cols(is_m)))
        pbo = cscv_pbo(is_m)
        oos = np.nan_to_num(mat[~is_mask])
        win_oos = float(oos[:, win].mean()) if len(oos) else None
        reasons = []
        if names[win] == "base":
            reasons.append("앞 구간 최선이 지금 방식(리밸런싱 날 종가)")
        if dsr["dsr"] < DSR_MIN:
            reasons.append(f"DSR {dsr['dsr']:.2f} < {DSR_MIN} (시도 {len(names)})")
        if pbo is None or pbo["pbo"] > PBO_MAX:
            reasons.append(f"과적합 확률 PBO {('—' if pbo is None else f'{pbo['pbo']:.0%}')} > {PBO_MAX:.0%}")
        if win_oos is None or win_oos <= 0:
            reasons.append(f"떼어 둔 2년 평균 개선 {('—' if win_oos is None else f'{win_oos * 1e4:+.1f}bp')} ≤ 0")
        order = np.argsort(-means)
        out[key] = {"n_rules": len(names), "n_dates_is": int(is_mask.sum()), "winner": names[win],
                    "winner_is_bps": float(means[win] * 1e4), "winner_oos_bps": None if win_oos is None else win_oos * 1e4,
                    "dsr": round(dsr["dsr"], 4), "pbo": pbo, "verdict": "CANDIDATE" if not reasons else "KEEP_CURRENT",
                    "reasons": reasons,
                    "top10": [{"rule": names[i], "is_bps": float(means[i] * 1e4),
                               "oos_bps": float(oos[:, i].mean() * 1e4) if len(oos) else None} for i in order[:10]]}
    return out


# =================================================================================================
# F1 새틀라이트 선정 — 파라미터 신호(순수 함수, satellite_lab.score 계약과 같음)
# =================================================================================================

def _trend_active(close: pd.Series, window: int, stop: float) -> bool:
    v = close.to_numpy(dtype=float)
    roll = close.shift(1).rolling(window, min_periods=window).max().to_numpy()
    in_pos, peak = False, 0.0
    for i in range(len(v)):
        c = v[i]
        if in_pos:
            peak = max(peak, c)
            if c <= peak * (1 - stop):
                in_pos = False
        elif not np.isnan(roll[i]) and c > roll[i]:
            in_pos, peak = True, c
    return in_pos


def _mom(c: pd.Series, lb: int, skip: int = 0) -> float:
    if len(c) < lb + 2:
        return float("nan")
    return float(c.iloc[-1 - skip] / c.iloc[-1 - lb] - 1)


def make_signal(kind: str, p: dict) -> Callable:
    def score(prices: dict, as_of, params) -> dict:
        out = {}
        moms = {}
        for t, df in prices.items():
            c = df["Close"].dropna()
            if len(c) < 80:
                continue
            if kind == "trend_mom":
                if len(c) < p["donchian"] + 60 or not _trend_active(c, p["donchian"], p["stop"]):
                    continue
                m = _mom(c, p["lb"]) if len(c) >= p["lb"] + 5 else float(c.iloc[-1] / c.iloc[0] - 1)
                if math.isfinite(m):
                    out[t] = m
            elif kind == "mom":
                m = _mom(c, p["lb"], p["skip"])
                if math.isfinite(m):
                    out[t] = m
            elif kind == "high52":
                if len(c) >= p["w"]:
                    out[t] = float(c.iloc[-1] / c.iloc[-p["w"]:].max())
            elif kind == "voladj":
                m = _mom(c, p["lb"])
                if len(c) > p["vol"] + 1 and math.isfinite(m):
                    vol = float(np.std(np.diff(np.log(c.iloc[-p["vol"] - 1:].to_numpy())), ddof=1))
                    if vol > 0:
                        out[t] = m / vol
            elif kind == "fip":
                m = _mom(c, p["lb"])
                if math.isfinite(m) and m > 0:
                    d = np.diff(c.iloc[-p["lb"] - 1:].to_numpy())
                    moms[t] = (m, float((d > 0).mean() - (d < 0).mean()))
            elif kind == "lowvol_trend":
                if len(c) >= max(80, p["vol"] + 2) and _trend_active(c, 20, 0.15):
                    vol = float(np.std(np.diff(np.log(c.iloc[-p["vol"] - 1:].to_numpy())), ddof=1))
                    if vol > 0:
                        out[t] = -vol
            elif kind == "mom_high":
                m = _mom(c, 252)
                if math.isfinite(m) and len(c) >= 252:
                    moms[t] = (m, float(c.iloc[-1] / c.iloc[-252:].max()))
        if kind == "fip" and moms:
            cut = float(np.median([v[0] for v in moms.values()]))
            out = {t: v[1] for t, v in moms.items() if v[0] >= cut}
        if kind == "mom_high" and moms:
            s = pd.DataFrame(moms, index=["m", "h"]).T.rank(pct=True)
            out = (s["m"] + s["h"]).to_dict()
        return out
    return score


def satellite_signal_grid() -> list[tuple[str, str, dict]]:
    """(이름, 종류, 파라미터). 첫 줄이 현 규칙 신호."""
    g = [("trend_mom(d20,s0.15,lb252)", "trend_mom", {"donchian": 20, "stop": 0.15, "lb": 252})]
    for d, s, lb in itertools.product((10, 20, 55), (0.10, 0.15, 0.25), (126, 252)):
        name = f"trend_mom(d{d},s{s},lb{lb})"
        if name != g[0][0]:
            g.append((name, "trend_mom", {"donchian": d, "stop": s, "lb": lb}))
    g += [(f"mom(lb{lb},skip{sk})", "mom", {"lb": lb, "skip": sk}) for lb, sk in itertools.product((63, 126, 252), (0, 21))]
    g += [(f"high52(w{w})", "high52", {"w": w}) for w in (126, 252)]
    g += [(f"voladj(lb{lb},v{v})", "voladj", {"lb": lb, "vol": v}) for lb, v in itertools.product((126, 252), (63, 126))]
    g += [(f"fip(lb{lb})", "fip", {"lb": lb}) for lb in (126, 252)]
    g += [(f"lowvol_trend(v{v})", "lowvol_trend", {"vol": v}) for v in (21, 63, 126)]
    g += [("mom_high", "mom_high", {})]
    return g


def satellite_configs() -> list[dict]:
    out = []
    for name, kind, p in satellite_signal_grid():
        for k, h, ex in itertools.product((3, 5, 8), (1, 3, 6), ("none", 0.15, 0.25)):
            out.append({"signal": name, "kind": kind, "p": p, "pool": "champion40", "top_k": k, "hold": h, "exit": ex})
        for k in (3, 5):
            out.append({"signal": name, "kind": kind, "p": p, "pool": "sp500_pit", "top_k": k, "hold": 6, "exit": "none"})
    return out


def satellite_config_name(c: dict) -> str:
    ex = "none" if c["exit"] == "none" else f"ts{c['exit']}"
    return f"{c['signal']}|{c['pool']}|k{c['top_k']}|h{c['hold']}|{ex}"


SATELLITE_INCUMBENT = "trend_mom(d20,s0.15,lb252)|champion40|k3|h6|none"


def run_satellite_config(c: dict, data) -> pd.Series:
    from core import satellite_lab as sl

    spec = {"pool": {"type": c["pool"]}, "portfolio": {"top_k": c["top_k"], "hold_months": c["hold"]},
            "exit": {"type": "none"} if c["exit"] == "none" else {"type": "trailing_stop", "stop_pct": c["exit"]}}
    return sl.run_variant(spec, {}, make_signal(c["kind"], c["p"]), data)["returns"]


# =================================================================================================
# F2 코어 선정
# =================================================================================================

def core_configs() -> list[tuple[str, Any]]:
    from core import core_lab as cl

    out = []
    lbs = {"12m": (252,), "9m": (189,), "6m": (126,), "mix3-12": (63, 126, 189, 252), "mix6-12": (126, 252)}
    filters = {"spy200": {"market_filter": "spy200"}, "none": {"market_filter": "none"},
               "asset10m": {"market_filter": "asset_sma", "filter_window": 210}}
    for (ln, lb), n, (fn, f), cc, bf in itertools.product(lbs.items(), (3, 4, 5), filters.items(), (None, 0.8), (None, 6)):
        cfg = cl.CoreConfig(lookbacks=lb, top_n=n, corr_cap=cc, buffer_n=bf, cash="bil", **f)
        out.append((f"{ln}|top{n}|{fn}|corr{cc or '-'}|buf{bf or '-'}", cfg))
    return out


CORE_INCUMBENT = "12m|top4|spy200|corr-|buf-"


# =================================================================================================
# F3 코어 보유 중 매도 규칙
# =================================================================================================

def core_exit_rules() -> list[tuple[str, dict]]:
    r = [("none", {"kind": "none"})]
    for pct, fq in itertools.product((0.05, 0.08, 0.10, 0.15, 0.20), ("daily", "weekly")):
        r.append((f"trail{int(pct * 100)}%|{fq}", {"kind": "trail", "p": pct, "freq": fq}))
    for n, fq in itertools.product((20, 50, 100, 200), ("daily", "weekly")):
        r.append((f"below_sma{n}|{fq}", {"kind": "sma", "n": n, "freq": fq}))
    r.append(("mom12_negative|weekly", {"kind": "mom_neg", "freq": "weekly"}))
    r.append(("rank_out_of_top8|weekly", {"kind": "rank", "k": 8, "freq": "weekly"}))
    r.append(("spy_below_200|weekly", {"kind": "spy", "freq": "weekly"}))
    return r


def apply_core_exits(weights: pd.DataFrame, closes: pd.DataFrame, spy: pd.Series, rule: dict,
                     cash: str = "BIL") -> pd.DataFrame:
    """월간 목표 비중에 '보유 중 매도'를 덧씌운다. 판단은 전날 종가(j−1), 반영은 j 행(그날 종가 체결 — 엔진 관례).
    판 몫은 다음 리밸런싱까지 cash(단기국채)에. 다시 사는 것은 다음 월간 리밸런싱에서만."""
    if rule["kind"] == "none":
        return weights
    w = weights.copy()
    idx = w.index
    risky = [c for c in w.columns if c != cash]
    change = w.diff().abs().sum(axis=1) > 1e-12
    change.iloc[0] = True
    starts = list(np.nonzero(change.to_numpy())[0]) + [len(idx)]
    week = pd.Series(idx.to_period("W"), index=idx)
    first_of_week = (week != week.shift(1)).to_numpy()
    c = closes.reindex(idx).ffill()
    sma = c.rolling(rule.get("n", 20), min_periods=rule.get("n", 20)).mean() if rule["kind"] == "sma" else None
    mom = c.pct_change(252, fill_method=None) if rule["kind"] in ("mom_neg", "rank") else None
    rank = mom[risky].rank(axis=1, ascending=False) if rule["kind"] == "rank" else None
    spy_c = spy.reindex(idx).ffill()
    spy_sma = spy_c.rolling(200, min_periods=200).mean()
    arr = w.to_numpy(copy=True)
    col = {t: i for i, t in enumerate(w.columns)}
    ci = col.get(cash)
    for s, e in zip(starts[:-1], starts[1:]):
        held = [t for t in risky if arr[s, col[t]] > 0]
        peak = {t: c[t].iloc[max(s - 1, 0)] for t in held}
        cut_done = False
        for j in range(s + 1, e):
            check = rule["freq"] == "daily" or first_of_week[j]
            for t in list(held):
                prev = c[t].iloc[j - 1]
                if pd.isna(prev):
                    continue
                peak[t] = max(peak[t], prev)
                if not check:
                    continue
                k = rule["kind"]
                hit = ((k == "trail" and prev <= peak[t] * (1 - rule["p"]))
                       or (k == "sma" and pd.notna(sma[t].iloc[j - 1]) and prev < sma[t].iloc[j - 1])
                       or (k == "mom_neg" and pd.notna(mom[t].iloc[j - 1]) and mom[t].iloc[j - 1] < 0)
                       or (k == "rank" and pd.notna(rank[t].iloc[j - 1]) and rank[t].iloc[j - 1] > rule["k"]))
                if hit:
                    wt = arr[j, col[t]]
                    arr[j:e, col[t]] = 0.0
                    if ci is not None:
                        arr[j:e, ci] += wt
                    held.remove(t)
            if rule["kind"] == "spy" and check and not cut_done and pd.notna(spy_sma.iloc[j - 1]) and spy_c.iloc[j - 1] < spy_sma.iloc[j - 1]:
                # 월간 리밸런싱 때 이미 200일선 아래라 절반으로 줄였으면(신호일 s−1) 또 줄이지 않는다
                already_cut = s > 0 and pd.notna(spy_sma.iloc[s - 1]) and spy_c.iloc[s - 1] < spy_sma.iloc[s - 1]
                if not already_cut:
                    for t in risky:
                        wt = arr[j, col[t]] * 0.5
                        arr[j:e, col[t]] -= wt
                        if ci is not None:
                            arr[j:e, ci] += wt
                cut_done = True
    return pd.DataFrame(arr, index=idx, columns=w.columns)


# =================================================================================================
# F4 사고파는 가격 — 파라미터 실행 규칙
# =================================================================================================

def execution_rules() -> list[tuple[str, dict]]:
    r = [("base", {"kind": "base"}), ("next_open", {"kind": "next_open"})]
    r += [(f"limit{p}%|{d}d", {"kind": "limit", "pct": p / 100, "days": d})
          for p, d in itertools.product((0.5, 1, 2, 3, 5), (1, 3, 5, 10))]
    r += [(f"split{n}x{g}d", {"kind": "split", "n": n, "gap": g}) for n, g in itertools.product((2, 3, 5), (1, 3, 5))]
    r += [(f"pullback_sma{s}|{w}d", {"kind": "pullback", "sma": s, "wait": w}) for s, w in itertools.product((3, 5, 10, 20), (5, 10, 20))]
    return r


MAX_LOOKAHEAD = 25


def execute_param(df: pd.DataFrame, i: int, side: str, rule: dict, f: np.ndarray) -> Optional[float]:
    """i 행(리밸런싱 날) 기준 체결가(조정 가격). 데이터가 모자라면 None."""
    if i + MAX_LOOKAHEAD >= len(df):
        return None
    o, h, lo, c = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close"))
    buy = side == "buy"
    k = rule["kind"]
    if k == "base":
        return c[i] * f[i]
    if k == "next_open":
        return o[i + 1] * f[i + 1]
    if k == "limit":
        lim = c[i] * (1 - rule["pct"] if buy else 1 + rule["pct"])
        for j in range(i + 1, i + rule["days"] + 1):
            if (buy and o[j] <= lim) or (not buy and o[j] >= lim):
                return o[j] * f[j]
            if (buy and lo[j] <= lim) or (not buy and h[j] >= lim):
                return lim * f[j]
        j = i + rule["days"]
        return c[j] * f[j]
    if k == "split":
        js = [i + rule["gap"] * m for m in range(rule["n"])]
        return float(np.mean([c[j] * f[j] for j in js]))
    if k == "pullback":
        sma = pd.Series(c).rolling(rule["sma"], min_periods=rule["sma"]).mean().to_numpy()
        for j in range(i + 1, i + rule["wait"] + 1):
            if not math.isnan(sma[j]) and ((buy and c[j] < sma[j]) or (not buy and c[j] > sma[j])):
                return c[j] * f[j]
        j = i + rule["wait"]
        return c[j] * f[j]
    raise ValueError(k)


TAKE_PROFIT_LEVELS = (0.10, 0.20, 0.30, 0.50, 0.75, 1.00)
