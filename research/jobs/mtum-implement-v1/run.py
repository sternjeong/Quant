"""Pre-registered investability check: French big-winner sleeve -> MTUM ETF."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core import market_data  # noqa: E402
from core import research_power as rp  # noqa: E402
from core import rolling_eval as re_  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "mtum-implement-v1"
VERSION = "mtum-implement-v1/2026-10-19"
SPY, MTUM = "SPY", "MTUM"
W_MOM = 0.50
INITIAL_KRW, MONTHLY_KRW = 10_000_000, 150_000
HORIZON_YEARS = 5
STEP = "M"
JUDGED_END = pd.Timestamp("2024-09-30")
WIN_SHARE_MIN, MEDIAN_IRR_MIN, P10_IRR_MIN, MDD_TOL = 0.70, 0.005, -0.015, 0.05
BOOT_N, BOOT_BLOCK, BOOT_SEED, BOOT_FLOOR = 2000, 126, 20261019, -0.005
POWER_YEARS, N_TRIALS = 10.45, 1
EPS = 1e-12


def smoke_prices(seed: int = 10) -> dict:
    idx = pd.bdate_range("2013-01-02", periods=3300)
    rng = np.random.default_rng(seed)
    market = rng.normal(0.00035, 0.009, len(idx))
    mom = market + rng.normal(0.00008, 0.007, len(idx))
    adj = pd.DataFrame({SPY: 100 * np.cumprod(1 + market), MTUM: 80 * np.cumprod(1 + mom)}, index=idx)
    close = adj * pd.DataFrame({SPY: 0.995, MTUM: 0.997}, index=idx)
    return {"close": close, "adj": adj, "fx": pd.Series(1300.0, index=idx), "source": "synthetic (smoke)"}


def load_real() -> dict:
    history = market_data.get_multiple_price_history([SPY, MTUM], start="2013-04-18", end=None, interval="1d") or {}
    close, adj = {}, {}
    for ticker in (SPY, MTUM):
        frame = history.get(ticker)
        if frame is None or frame.empty or "Close" not in frame:
            raise RuntimeError(f"{ticker} 가격 이력을 받지 못함")
        for dest, col in ((close, "Close"), (adj, "Adj Close" if "Adj Close" in frame and frame["Adj Close"].notna().any() else "Close")):
            series = frame[col].dropna().copy()
            series.index = pd.DatetimeIndex(series.index).tz_localize(None).normalize()
            dest[ticker] = series[~series.index.duplicated(keep="last")]
    calendar = close[SPY].index
    close_df = pd.DataFrame(close).reindex(calendar)
    adj_df = pd.DataFrame(adj).reindex(calendar)
    # Do not backfill pre-inception observations. Only short isolated quote gaps can be carried.
    close_df, adj_df = close_df.ffill(limit=3), adj_df.ffill(limit=3)
    common = adj_df.dropna(subset=[SPY, MTUM])
    if len(common) < 252 * 6:
        raise RuntimeError(f"SPY/MTUM 공통 자료가 너무 짧음: {len(common)} 거래일")
    first = adj_df[MTUM].first_valid_index()
    if first is None:
        raise RuntimeError("MTUM 거래 자료가 없음")
    live = slice(first, None)
    if close_df.loc[live, [SPY, MTUM]].isna().any().any() or adj_df.loc[live, [SPY, MTUM]].isna().any().any():
        raise RuntimeError("평가 구간의 가격 공백이 3거래일보다 김")
    if (close_df.loc[live, [SPY, MTUM]] <= 0).any().any() or (adj_df.loc[live, [SPY, MTUM]] <= 0).any().any():
        raise RuntimeError("평가 구간에 0 이하 가격이 있음")
    fx = tx.usdkrw_series().copy()
    fx.index = pd.DatetimeIndex(fx.index).tz_localize(None).normalize()
    fx = fx[~fx.index.duplicated(keep="last")].sort_index()
    fx_aligned = fx.reindex(calendar).ffill(limit=3)
    first_eval_i = min(int(adj_df.index.get_loc(first)) + 252, len(calendar) - 1)
    judged_days = calendar[(calendar >= calendar[first_eval_i]) & (calendar <= JUDGED_END)]
    if not len(judged_days) or fx_aligned.reindex(judged_days).isna().any():
        raise RuntimeError("워밍업 이후 판정기간의 환율 자료가 부족하거나 3거래일 초과 공백이 있음")
    return {"close": close_df, "adj": adj_df, "fx": fx_aligned,
            "source": "yfinance Close/Adj Close (SPY, MTUM), USDKRW via tax_fx.usdkrw_series()"}


def evaluation_start(data: dict) -> pd.Timestamp:
    first = data["adj"][MTUM].first_valid_index()
    i = data["adj"].index.get_loc(first)
    if isinstance(i, slice):
        i = i.start
    j = int(i) + 252
    if j >= len(data["adj"].index):
        raise RuntimeError("MTUM 252거래일 워밍업 뒤 평가 자료가 없음")
    return data["adj"].index[j]


def windows(data: dict, smoke: bool) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    start = evaluation_start(data)
    days = data["adj"].index[data["adj"][SPY].notna() & data["adj"][MTUM].notna()]
    if smoke:
        # Tiny synthetic run: shorter windows, with the same monthly rolling machinery.
        return re_.rolling_windows(days, 2, step="Q", first_start=days[600], last_start=days[-600])
    return [w for w in re_.rolling_windows(days, HORIZON_YEARS, step=STEP, first_start=start)
            if w[1] <= JUDGED_END]


def strategy_weights(start: pd.Timestamp, end: pd.Timestamp, data: dict) -> pd.DataFrame:
    idx = data["adj"].index[(data["adj"].index >= start) & (data["adj"].index <= end)]
    if len(idx) < 2:
        raise ValueError(f"평가 구간 데이터 부족: {start}~{end}")
    values = np.full((len(idx), 2), (W_MOM, W_MOM), dtype=float)
    # tax_fx detects trades from target-weight changes. Alternate a negligible cash buffer to
    # encode each January rebalance while preserving the preregistered 50/50 target.
    toggle = False
    years = idx.year.to_numpy()
    for i in range(1, len(idx)):
        if years[i] != years[i - 1]:
            toggle = not toggle
            values[i:, :] = (W_MOM - (1e-8 if toggle else 0.0), W_MOM)
    return pd.DataFrame(values, index=idx, columns=[SPY, MTUM])


def bootstrap_cagr_diff(candidate: np.ndarray, benchmark: np.ndarray) -> dict:
    a, b = np.asarray(candidate, float), np.asarray(benchmark, float)
    if len(a) != len(b) or len(a) < BOOT_BLOCK:
        return {"low90": None, "median": None, "high90": None, "n": 0}
    rng = np.random.default_rng(BOOT_SEED)
    n, n_blocks = len(a), math.ceil(len(a) / BOOT_BLOCK)
    starts = rng.integers(0, n, size=(BOOT_N, n_blocks))
    ix = ((starts[:, :, None] + np.arange(BOOT_BLOCK)[None, None, :]) % n).reshape(BOOT_N, -1)[:, :n]
    ra, rb = a[ix], b[ix]
    ann_a = np.exp(np.log1p(ra).sum(axis=1) * (252.0 / n)) - 1
    ann_b = np.exp(np.log1p(rb).sum(axis=1) * (252.0 / n)) - 1
    q = np.quantile(ann_a - ann_b, [0.05, 0.5, 0.95])
    return {"low90": float(q[0]), "median": float(q[1]), "high90": float(q[2]), "n": BOOT_N,
            "block_days": BOOT_BLOCK, "seed": BOOT_SEED}


def observed_ir(data: dict, start: pd.Timestamp, end: pd.Timestamp, cfg: tx.AccountConfig) -> float:
    idx = data["adj"].index[(data["adj"].index >= start) & (data["adj"].index <= end)]
    w = strategy_weights(idx[0], idx[-1], data)
    b = tx.buy_and_hold_weights(idx, SPY)
    s = tx.simulate(w, data["close"], data["adj"], data["fx"], cfg)
    m = tx.simulate(b, data["close"], data["adj"], data["fx"], cfg)
    rs = s["twr_index"].pct_change().fillna(0).to_numpy()
    rm = m["twr_index"].pct_change().fillna(0).to_numpy()
    d = rs - rm
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else 0.0
    return float(np.mean(d) / sd * math.sqrt(252)) if sd > 0 else 0.0


def judgment(summary: dict, boot: dict, obs_ir: float, power: dict) -> tuple[str, dict]:
    mdd_gap = summary["median_strategy_mdd_tw"] - summary["median_benchmark_mdd_tw"]
    checks = {
        "win_share_ge_70pct": summary["share_terminal_win"] >= WIN_SHARE_MIN - EPS,
        "median_irr_diff_ge_0.5pp": summary["median_diff_irr"] >= MEDIAN_IRR_MIN - EPS,
        "p10_irr_diff_ge_minus_1.5pp": summary["p10_diff_irr"] >= P10_IRR_MIN - EPS,
        "median_mdd_within_5pp": mdd_gap >= -MDD_TOL - EPS,
        "paired_bootstrap_low90_gt_minus_0.5pp": boot.get("low90") is not None and boot["low90"] > BOOT_FLOOR,
    }
    verdict = "PASS_FORWARD_CANDIDATE" if all(checks.values()) else rp.classify_fail(obs_ir, power)
    return verdict, checks


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    data = smoke_prices() if args.smoke else load_real()
    start = evaluation_start(data)
    all_days = data["adj"].index[data["adj"][SPY].notna() & data["adj"][MTUM].notna()]
    if args.smoke:
        ws = windows(data, True)
        horizon, judged_end = 2, all_days[-1]
        start = ws[0][0]
    else:
        ws = windows(data, False)
        horizon, judged_end = HORIZON_YEARS, JUDGED_END
    if not ws:
        raise RuntimeError("판정 가능한 rolling window가 없음")
    cfg = tx.AccountConfig(initial_krw=float(INITIAL_KRW), monthly_contribution_krw=float(MONTHLY_KRW), contribution_policy="underweight_first")
    cp = args.checkpoint
    cp.mkdir(parents=True, exist_ok=True)
    fp = f"{VERSION}|{data['adj'].index[0]}|{data['adj'].index[-1]}|{len(ws)}|{args.smoke}"
    cache_path, bench_path = cp / "candidate.pkl", cp / "benchmark.pkl"
    import pickle
    def load_cache(p):
        try:
            obj = pickle.loads(p.read_bytes())
            return obj.get("entries", {}) if obj.get("fingerprint") == fp else {}
        except Exception:
            return {}
    candidate_cache, benchmark_cache = load_cache(cache_path), load_cache(bench_path)
    def save_cache(p, entries):
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps({"fingerprint": fp, "entries": entries}, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(p)
    deadline_epoch = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH", time.time() + 3600))
    deadline_mono = time.monotonic() + max(0.0, deadline_epoch - time.time() - 90.0)
    result = re_.evaluate_windows(lambda a, b: strategy_weights(a, b, data),
                                 {"close": data["close"], "adj": data["adj"], "fx": data["fx"]}, ws, cfg,
                                 cache=candidate_cache, benchmark_cache=benchmark_cache,
                                 cache_path=cache_path, fingerprint=fp,
                                 max_new=None, deadline=deadline_mono)
    save_cache(bench_path, benchmark_cache)
    if not result["complete"]:
        return 3
    # Keep a safe margin for the two full-period simulations and output writes.
    if time.time() >= deadline_epoch - 120.0:
        return 3
    summary = re_.summarize(result, horizon_years=horizon)
    eval_start = ws[0][0]
    eval_end = ws[-1][1]
    idx = data["adj"].index[(data["adj"].index >= eval_start) & (data["adj"].index <= eval_end)]
    cw = strategy_weights(idx[0], idx[-1], data)
    bw = tx.buy_and_hold_weights(idx, SPY)
    sim_c = tx.simulate(cw, data["close"], data["adj"], data["fx"], cfg)
    sim_b = tx.simulate(bw, data["close"], data["adj"], data["fx"], cfg)
    rc = sim_c["twr_index"].pct_change().fillna(0).to_numpy()
    rb = sim_b["twr_index"].pct_change().fillna(0).to_numpy()
    boot = bootstrap_cagr_diff(rc, rb)
    diff = rc - rb
    sd = float(np.std(diff, ddof=1)) if len(diff) > 1 else 0.0
    obs_ir = float(np.mean(diff) / sd * math.sqrt(252)) if sd > 0 else 0.0
    noop = rp.noop_guard(diff.tolist())
    years = (eval_end - eval_start).days / 365.25
    power = rp.power_report(years, N_TRIALS) if not args.smoke else rp.power_report(max(years, 2), N_TRIALS)
    verdict, checks = judgment(summary, boot, obs_ir, power)
    if noop and not args.smoke:
        verdict = "NOT_EVALUABLE"
    result_json = {
        "id": JOB_ID, "version": VERSION, "smoke": args.smoke,
        "verdicts": {"spy_50_mtum_50": "SMOKE_ONLY" if args.smoke else verdict},
        "judgments": {"spy_50_mtum_50": {"verdict": "SMOKE_ONLY" if args.smoke else verdict,
            "checks": checks, "observed_ir": obs_ir, "noop_guard": noop, "p_raw_not_applicable": None}},
        "summary": summary, "bootstrap": boot, "power": power,
        "period": {"start": str(eval_start.date()), "end": str(eval_end.date()), "judged_end": str(judged_end.date()),
                   "horizon_years": horizon, "windows": len(ws), "source": data["source"]},
        "full_period": {"candidate_terminal_after_liquidation_krw": sim_c["terminal_after_liquidation_krw"],
                        "spy_terminal_after_liquidation_krw": sim_b["terminal_after_liquidation_krw"],
                        "candidate_irr_after_liquidation": sim_c["irr_after_liquidation"],
                        "spy_irr_after_liquidation": sim_b["irr_after_liquidation"],
                        "candidate_mdd_twr": float((sim_c["twr_index"] / sim_c["twr_index"].cummax() - 1).min()),
                        "spy_mdd_twr": float((sim_b["twr_index"] / sim_b["twr_index"].cummax() - 1).min()),
                        "candidate_totals": sim_c["totals"], "spy_totals": sim_b["totals"]},
        "limits": ["MTUM history is short; 5-year windows overlap heavily.",
                   "One fixed ETF candidate; no correction for previous research families.",
                   "Adjusted prices and Korean taxes are approximations; not tax advice.",
                   "A pass is forward-ledger review only; no engine or champion change."]}
    if args.smoke:
        result_json["verdicts"] = {"spy_50_mtum_50": "SMOKE_ONLY"}
    atomic_json(args.out / "results.json", result_json)
    lines = ["# 대형주 모멘텀 실제 ETF 이전 — SPY+MTUM 50/50", "",
             f"판정: **{result_json['verdicts']['spy_50_mtum_50']}**", "",
             "이 결과는 기존 French 대형주 승자 포트폴리오 50% 혼합을 실제 MTUM ETF로 옮긴 단일 고정 비교다. 통과해도 채택이 아니라 전진 검토 후보이며 엔진은 바뀌지 않는다.", "",
             f"- 기간: {eval_start.date()} ~ {eval_end.date()}, {len(ws)}개의 월별 시작 5년 창(스모크는 합성 2년 창)",
             f"- 승률 {summary['share_terminal_win']:.1%}; 세후 IRR 차이 중앙값 {summary['median_diff_irr']*100:+.2f}%p, 10분위 {summary['p10_diff_irr']*100:+.2f}%p",
             f"- 시간가중 MDD 중앙값 후보 {summary['median_strategy_mdd_tw']*100:.2f}% / SPY {summary['median_benchmark_mdd_tw']*100:.2f}%",
             f"- paired 126일 block bootstrap 90% CAGR 차이: [{boot['low90']*100:.2f}, {boot['high90']*100:.2f}]%p; 관측 IR {obs_ir:.3f}",
             f"- 판정 관문: `{json.dumps(checks, ensure_ascii=False)}`", "",
             f"- 검정력 사전 계산: {rp.power_line(power)}", "",
             f"- 겹침 주의: {summary['overlap_caveat']}", "",
             "세금·배당 및 가격 조정은 근사다. 매매 엔진·챔피언·전진 원장은 변경하지 않았다."]
    (args.out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
