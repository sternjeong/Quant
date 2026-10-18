"""검증 연구 contrib-reval-sector-v1 (2026-10-17 사전 등록): 처음 목돈 + 매달 적립으로 굴리면 섹터 모멘텀 전략이 세후로 SPY 를 이기나.

사용자 목표(2026-10-17): 처음 1,000만 원 + 매달 15만 원을 넣으며 이 엔진을 끝없이 굴리고, 한국 세금 뒤 장기적으로 SPY 를 이기고 싶다.
지금까지 SC2·SC2VT20·SPY 섞기 연구는 '한 시작일·목돈 한 번'으로만 쟀다. 여기서는 2000-01 부터 매달 시작하는 10년(판정)·5년(보고) 구간을
core/rolling_eval 로 모두 굴려, 같은 돈을 같은 날 SPY 에 넣었을 때보다 청산 후 더 많이 남는 비율과 IRR 차이를 본다.

전략(목표 비중 표는 한 번 만들고 구간마다 잘라 쓴다 — 섞기는 시작일마다 다시 만든다):
  SPY      기준(그냥 보유, 적립금도 SPY 로).
  SC2      Select Sector SPDR 상위 2(252거래일 총수익, 전 거래일 종가 신호), 균등, 월 1회, 100% 투자 — core/forward_tournament_v3.py 정의.
  SC2VT20  SC2 + 변동성 맞춤 20%(직전 126일 '맞추지 않은 SC2' 과거 가격 재구성 변동성), 남는 몫 BIL(상장 전 0% 달러 현금).
  BL30/50  SPY 70/50 + SC2VT20 30/50, 시작일과 1월에만 소매 크기를 되돌림(spy-sector-blend-v1 PART E 코드 그대로).
판정(시나리오 B, 10년 구간, 구간 끝 ≤ 2024-09-30): 전략마다 CONTRIB_BEATS_SPY ⇔ 이긴 구간 비율 ≥ 70% · IRR 차이 중앙값 ≥ +0.5%p ·
  IRR 차이 10분위 ≥ −1.5%p · 시간가중 MDD 중앙값이 SPY 보다 5%p 넘게 나쁘지 않음. 아니면 classify_fail(FAIL / FAIL_UNDERPOWERED).
규칙 전체는 SPEC.md(한국어)와 아래 상수에 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 다시 등록한다. 엔진은 바뀌지 않는다.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import forward_tournament_v3 as ft3  # noqa: E402
from core import research_power as rp  # noqa: E402
from core import rolling_eval as re_  # noqa: E402
from core import tax_fx as tx  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ssb = _load("_crs_spy_sector_blend_v1", "research/jobs/spy-sector-blend-v1/run.py")

JOB_ID = "contrib-reval-sector-v1"
RULES_VERSION = "contrib-reval-sector-v1/2026-10-17"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
STRATEGIES = ("SC2", "SC2VT20", "BL30", "BL50")
BLEND_W = {"BL30": 0.30, "BL50": 0.50}
N_TRIALS = 4
POWER_YEARS = 24.7
SCENARIOS = {                       # 처음 금액, 매달 적립(원)
    "B": (10_000_000, 150_000),     # 판정
    "A": (10_000_000, 0),
    "C": (3_000_000, 150_000),
    "B10": (100_000_000, 1_500_000),
}
SCENARIO_ORDER = ("B", "A", "C", "B10")
PRIMARY_SCENARIO = "B"
POLICY = "underweight_first"
HORIZONS = (10, 5)
PRIMARY_HORIZON = 10
STEP = "M"
FIRST_START = "2000-01-01"           # 2000-01 첫 거래일부터 매달 시작
JUDGED_END = "2024-09-30"            # 구간 끝이 이 날 이하면 판정 대상, 뒤면 보고만
FULL_SPAN = ("2000-01-03", "2024-09-30")   # 관측 IR·무효 실행 가드·회전율(시나리오 B 한 계좌)

WIN_SHARE_MIN = 0.70
MEDIAN_IRR_MARGIN = 0.005
P10_IRR_FLOOR = -0.015
MDD_TW_TOL = 0.05
EPS = 1e-12

PASS = "CONTRIB_BEATS_SPY"
FAIL, NOT_EVALUABLE = "FAIL", "NOT_EVALUABLE"

SPY, BIL = ft3.SPY, ft3.BIL
ETF_TICKERS = ssb.ETF_TICKERS
DEADLINE_MARGIN = 90.0
SIZE_LIMIT = 190_000                 # results.json 바이트 상한(넘으면 구간별 계열을 뺀다)


def smoke_params() -> dict:
    """스모크(합성 자료): 같은 구조의 짧은 구간 — 2년(주)·1년, 해마다 시작, 판정 끝 2016-06-30."""
    return {"horizons": (2, 1), "primary_horizon": 2, "step": "A", "first_start": "2012-01-01", "last_start": "2016-12-31",
            "judged_end": "2016-06-30", "full_span": ("2012-01-03", "2016-06-30")}


def real_params() -> dict:
    return {"horizons": HORIZONS, "primary_horizon": PRIMARY_HORIZON, "step": STEP, "first_start": FIRST_START,
            "last_start": None, "judged_end": JUDGED_END, "full_span": FULL_SPAN}


class _Stop(Exception):
    """시간 예산 끝·새 계산 수 상한·SIGTERM — 캐시는 이미 저장돼 있다."""


# =================================================================================================
# 목표 비중 표
# =================================================================================================

def decisions_unscaled(decisions: list[dict]) -> list[dict]:
    """SC2(노출 1.0, 100% 투자): 같은 결정에서 변동성 맞춤만 뺀다."""
    return [dict(d, exposure=1.0) for d in decisions]


def first_decision_on_or_after(prep: dict, decisions: list[dict], day: str) -> str:
    idx = prep["adj"].index
    for d in decisions:
        if idx[d["i"]] >= pd.Timestamp(day):
            return d["date"]
    raise ValueError(f"{day} 이후 결정일이 없음")


def sc2_frame(prep: dict, decisions: list[dict], start: str, end: Optional[str] = None) -> pd.DataFrame:
    """SC2 목표 비중(ft3.sc2_target 그대로, 노출 1.0). 소매 100% 라 시작일과 무관하다 — 한 번 만들고 잘라 쓴다."""
    return ssb.build_etf_weights(prep, decisions_unscaled(decisions), 1.0, start, end)[0]


def sc2vt_frame(prep: dict, decisions: list[dict], start: str, end: Optional[str] = None) -> pd.DataFrame:
    """SC2VT20 목표 비중(spy-sector-blend-v1 PART E 의 w=100% 와 같음). 시작일과 무관하다."""
    return ssb.build_etf_weights(prep, decisions, 1.0, start, end)[0]


def blend_frame(prep: dict, decisions: list[dict], w: float, start: str, end: Optional[str] = None) -> pd.DataFrame:
    """SPY (1−w) + SC2VT20 w, 시작일·1월에만 되돌림 — 시작일에 따라 첫 1월 전까지 비중이 달라 구간마다 다시 만든다."""
    return ssb.build_etf_weights(prep, decisions, w, start, end)[0]


def turnover_per_year(weights: pd.DataFrame, rets: pd.DataFrame) -> float:
    """편도 회전율(연): 목표가 바뀌는 날 Σ|목표 − 표류한 보유| / 2 의 연평균(세전·비용 없음, 첫 매수 제외)."""
    W = weights.to_numpy(dtype=float)
    R = rets.reindex(index=weights.index, columns=weights.columns).fillna(0.0).to_numpy(dtype=float)
    ch = (weights.diff().abs().sum(axis=1) > 1e-9).to_numpy()
    h = W[0].copy()
    cash = 1.0 - h.sum()
    tot_turn = 0.0
    for i in range(1, len(W)):
        g = h * (1 + R[i])
        tot = g.sum() + cash
        h, cash = g / tot, cash / tot
        if ch[i]:
            tot_turn += float(np.abs(W[i] - h).sum()) / 2.0
            h = W[i].copy()
            cash = 1.0 - h.sum()
    years = (weights.index[-1] - weights.index[0]).days / 365.25
    return tot_turn / years if years > 0 else float("nan")


# =================================================================================================
# 구간
# =================================================================================================

def make_windows(days, horizon: float, params: dict) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    return re_.rolling_windows(days, horizon, step=params["step"], first_start=params["first_start"],
                               last_start=params["last_start"])


def split_rows(rows: list[dict], judged_end: str) -> tuple[list[dict], list[dict]]:
    """구간 끝 ≤ judged_end 면 판정, 아니면 보고만."""
    lim = pd.Timestamp(judged_end)
    judged = [r for r in rows if pd.Timestamp(r["end"]) <= lim]
    return judged, [r for r in rows if pd.Timestamp(r["end"]) > lim]


def account(scenario: str) -> tx.AccountConfig:
    init, monthly = SCENARIOS[scenario]
    return tx.AccountConfig(initial_krw=float(init), monthly_contribution_krw=float(monthly), contribution_policy=POLICY)


# =================================================================================================
# 판정 (결과를 보기 전에 고정)
# =================================================================================================

def _ok(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def contrib_checks(s: dict) -> Optional[dict[str, Optional[bool]]]:
    """s = rolling_eval.summarize(판정 구간). 구간이 없으면 None."""
    if not s or not s.get("n_windows"):
        return None
    mdd_gap = (s["median_strategy_mdd_tw"] - s["median_benchmark_mdd_tw"]) \
        if _ok(s.get("median_strategy_mdd_tw")) and _ok(s.get("median_benchmark_mdd_tw")) else None
    return {
        "win_share": (s["share_terminal_win"] >= WIN_SHARE_MIN - EPS) if _ok(s.get("share_terminal_win")) else None,
        "median_irr": (s["median_diff_irr"] >= MEDIAN_IRR_MARGIN - EPS) if _ok(s.get("median_diff_irr")) else None,
        "p10_irr": (s["p10_diff_irr"] >= P10_IRR_FLOOR - EPS) if _ok(s.get("p10_diff_irr")) else None,
        "mdd_tw": (mdd_gap >= -MDD_TW_TOL - EPS) if mdd_gap is not None else None,
    }


def contrib_verdict(checks: Optional[dict], noop: Optional[str], observed_ir, power: dict) -> str:
    if checks is None or noop:
        return NOT_EVALUABLE
    if all(v is True for v in checks.values()):
        return PASS
    return rp.classify_fail(observed_ir, power)


def information_ratio(a: np.ndarray, b: np.ndarray, ppy: float = 252.0) -> float:
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    if len(d) < 2:
        return float("nan")
    sd = float(np.std(d, ddof=1))
    return float(np.mean(d) / sd * math.sqrt(ppy)) if sd > 0 else float("nan")


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


def _load_ckpt(path: Path, fp):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        return obj["payload"] if obj.get("fingerprint") == fp else None
    except Exception:  # noqa: BLE001 — 깨진 체크포인트는 다시 계산
        return None


# =================================================================================================
# 계산
# =================================================================================================

def full_span_sim(prep: dict, frames: dict, decisions: list[dict], span: tuple[str, str]) -> dict:
    """시나리오 B 한 계좌로 판정 전체 기간을 굴린다 — 관측 IR(시간가중 일별 수익, 전략 − SPY)·무효 실행 가드·회전율·세금·수수료."""
    a, b = span
    start = first_decision_on_or_after(prep, decisions, a)
    cfg = account(PRIMARY_SCENARIO)
    out: dict[str, Any] = {}
    for name in ("SPY",) + STRATEGIES:
        if name == "SPY":
            idx = prep["adj"].loc[pd.Timestamp(start): pd.Timestamp(b)].index
            w = tx.buy_and_hold_weights(idx, SPY)
        elif name in BLEND_W:
            w = blend_frame(prep, decisions, BLEND_W[name], start, b)
        else:
            w = frames[name].loc[pd.Timestamp(start): pd.Timestamp(b)]
        w = w.loc[:, w.abs().sum() > 0]
        s = tx.simulate(w, prep["tax_close"], prep["tax_adj"], prep["fx"], cfg)
        twr = s["twr_index"]
        out[name] = {"first": str(w.index[0].date()), "last": str(w.index[-1].date()),
                     "irr_after_liquidation": float(s["irr_after_liquidation"]), "irr_pre_cost": float(s["irr_pre_cost"]),
                     "terminal_after_liquidation_krw": float(s["terminal_after_liquidation_krw"]),
                     "total_contributed_krw": float(s["total_contributed_krw"]),
                     "capital_gains_tax_krw": float(s["totals"]["capital_gains_tax_krw"]),
                     "fees_krw": float(s["totals"]["fees_krw"]), "fx_cost_krw": float(s["totals"]["fx_cost_krw"]),
                     "unpaid_tax_if_sold_now_krw": float(s["unpaid_tax_if_sold_now_krw"]),
                     "mdd_tw": re_.max_drawdown(twr), "mdd_mw": re_.max_drawdown(s["values_krw"]),
                     "turnover_one_way_per_year": 0.0 if name == "SPY" else turnover_per_year(w, prep["rets"]),
                     "twr_daily": twr.pct_change().fillna(0.0).to_numpy(dtype=float)[1:]}
    return out


def strategy_builder(name: str, prep: dict, decisions: list[dict], frames: dict):
    if name in BLEND_W:
        w = BLEND_W[name]
        return lambda s, e: blend_frame(prep, decisions, w, str(pd.Timestamp(s).date()), str(pd.Timestamp(e).date()))
    return frames[name]


def cell_summary(rows: list[dict], horizon: float, judged_end: str) -> dict:
    judged, reported = split_rows(rows, judged_end)
    out = {}
    for key, rr in (("judged", judged), ("reported", reported)):
        s = re_.summarize(rr, horizon) if rr else {"n_windows": 0, "share_terminal_win": None}
        if rr:
            def med(f):
                return float(np.nanmedian([f(r) for r in rr]))
            s.update({
                "median_strategy_tax_krw": med(lambda r: r["strategy"]["capital_gains_tax_krw"]),
                "median_benchmark_tax_krw": med(lambda r: r["benchmark"]["capital_gains_tax_krw"]),
                "median_strategy_unpaid_tax_krw": med(lambda r: r["strategy"]["unpaid_tax_if_sold_now_krw"]),
                "median_benchmark_unpaid_tax_krw": med(lambda r: r["benchmark"]["unpaid_tax_if_sold_now_krw"]),
                "median_strategy_terminal_krw": med(lambda r: r["strategy"]["terminal_krw"]),
                "median_benchmark_terminal_krw": med(lambda r: r["benchmark"]["terminal_krw"]),
                "median_total_contributed_krw": med(lambda r: r["strategy"]["total_contributed_krw"]),
                "median_strategy_mdd_mw": med(lambda r: r["strategy"]["mdd_mw"]),
                "median_benchmark_mdd_mw": med(lambda r: r["benchmark"]["mdd_mw"]),
                "first_start": rr[0]["start"], "last_start": rr[-1]["start"], "last_end": rr[-1]["end"],
            })
        out[key] = s
    return out


def judge_cells(cells: dict, full: dict, power: dict, params: dict) -> dict:
    """모든 (시나리오, 구간 길이, 전략) 칸에 같은 규칙을 적용한다. 판정은 B·10년만, 나머지는 같은 규칙의 보고."""
    spy_d = full["SPY"]["twr_daily"]
    obs, noop = {}, {}
    for name in STRATEGIES:
        d = full[name]["twr_daily"]
        n = min(len(d), len(spy_d))
        obs[name] = information_ratio(d[-n:], spy_d[-n:])
        noop[name] = rp.noop_guard((d[-n:] - spy_d[-n:]).tolist())
    out = {}
    for key, c in cells.items():
        name = key.split("|")[2]
        ch = contrib_checks(c["judged"])
        out[key] = {"checks": ch, "verdict": contrib_verdict(ch, noop[name], obs[name], power)}
    return {"cells": out, "observed_ir": obs, "noop": noop}


def cell_key(scen: str, hz, name: str) -> str:
    return f"{scen}|{hz:g}y|{name}"


def contributions_table(judged: dict, cells: dict, hz) -> list[dict]:
    rows = []
    for name in STRATEGIES:
        a, b = cell_key("A", hz, name), cell_key("B", hz, name)
        va, vb = judged["cells"][a]["verdict"], judged["cells"][b]["verdict"]
        rows.append({"strategy": name, "A_verdict": va, "B_verdict": vb, "changed": (va == PASS) != (vb == PASS),
                     "A_share_win": cells[a]["judged"].get("share_terminal_win"),
                     "B_share_win": cells[b]["judged"].get("share_terminal_win"),
                     "A_median_diff_irr": cells[a]["judged"].get("median_diff_irr"),
                     "B_median_diff_irr": cells[b]["judged"].get("median_diff_irr")})
    return rows


def smoke_coverage(cells: dict, decisions: list[dict], full: dict, judged: dict, params: dict) -> dict[str, bool]:
    hz0 = params["primary_horizon"]
    return {
        "all_cells": len(cells) == len(SCENARIOS) * len(params["horizons"]) * len(STRATEGIES),
        "judged_and_reported": all(c["judged"]["n_windows"] > 0 and c["reported"]["n_windows"] > 0 for c in cells.values()),
        "judged_end_bound": all(pd.Timestamp(c["judged"]["last_end"]) <= pd.Timestamp(params["judged_end"]) for c in cells.values()),
        "contributions_counted": cells[cell_key("B", hz0, "SC2")]["judged"]["median_total_contributed_krw"]
        > cells[cell_key("A", hz0, "SC2")]["judged"]["median_total_contributed_krw"],
        "sc2vt_scales": any(d["exposure"] < 0.999 for d in decisions),
        "tax_paid_somewhere": any(c["judged"].get("median_strategy_tax_krw", 0) > 0 for c in cells.values()),
        "turnover": all(full[n]["turnover_one_way_per_year"] > 0 for n in STRATEGIES),
        "verdicts_valid": all(v["verdict"] in (PASS, FAIL, "FAIL_UNDERPOWERED", NOT_EVALUABLE) for v in judged["cells"].values()),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-new-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 시뮬레이션 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    params = smoke_params() if a.smoke else real_params()
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    power = rp.power_report(POWER_YEARS, N_TRIALS)          # 결과를 보기 전에(기간·시도 수만)
    dl_epoch = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None
    t_start = time.time()
    budget = {"left": a.max_new_per_run or None}
    bench: dict[str, dict] = {}

    def log(s: str) -> None:
        print(s, flush=True)

    def mono_deadline() -> Optional[float]:
        if dl_epoch is None:
            return None
        return time.monotonic() + (dl_epoch - time.time() - DEADLINE_MARGIN)

    def check_time() -> None:
        if dl_epoch is not None and time.time() > dl_epoch - DEADLINE_MARGIN:
            raise _Stop()

    def stage(name: str, fn):
        path = ck / f"{name}.pkl"
        got = _load_ckpt(path, fp)
        if got is None:
            check_time()
            got = fn()
            _atomic_pickle(path, {"fingerprint": fp, "payload": got})
            log(f"단계 저장: {name}")
        return got

    def save_bench() -> None:
        for scen, d in bench.items():
            _atomic_pickle(ck / f"bench_{scen}.pkl", {"fingerprint": {**fp, "scenario": scen}, "payload": d})

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        inp = stage("etf_inputs", lambda: ssb.synthetic_etf() if a.smoke else ssb.load_etf_real())
        prep = ssb.etf_prepare(inp)
        decisions = stage("decisions", lambda: ssb.sleeve_decisions(prep))
        start0 = first_decision_on_or_after(prep, decisions, params["first_start"])
        frames = {"SC2": sc2_frame(prep, decisions, start0), "SC2VT20": sc2vt_frame(prep, decisions, start0)}
        full = stage("full_span", lambda: full_span_sim(prep, frames, decisions, params["full_span"]))
        days = prep["adj"].loc[pd.Timestamp(start0):].index
        panels = {"close": prep["tax_close"], "adj": prep["tax_adj"], "fx": prep["fx"]}
        rows_by_cell: dict[str, list] = {}
        for scen in SCENARIO_ORDER:
            bench[scen] = _load_ckpt(ck / f"bench_{scen}.pkl", {**fp, "scenario": scen}) or {}
            cfg = account(scen)
            for hz in params["horizons"]:
                wins = make_windows(days, hz, params)
                for name in STRATEGIES:
                    key = cell_key(scen, hz, name)
                    left = budget["left"]
                    res = re_.evaluate_windows(strategy_builder(name, prep, decisions, frames), panels, wins, cfg,
                                               cache_path=ck / f"cells/{key.replace('|', '_')}.pkl",
                                               benchmark_cache=bench[scen], fingerprint={**fp, "cell": key},
                                               max_new=left, deadline=mono_deadline())
                    save_bench()
                    if left is not None:
                        budget["left"] = max(0, left - res["new_sims"])
                    log(f"{key}: {res['done']}/{len(wins)} 구간 (새 시뮬레이션 {res['new_sims']})")
                    if not res["complete"]:
                        raise _Stop()
                    rows_by_cell[key] = res["rows"]
        cells = {k: cell_summary(v, float(k.split("|")[1][:-1]), params["judged_end"]) for k, v in rows_by_cell.items()}
        judged = judge_cells(cells, full, power, params)
        result = build_result(cells, judged, full, rows_by_cell, decisions, power, params, a.smoke, inp)
        if a.smoke:
            cov = smoke_coverage(cells, decisions, full, judged, params)
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        save_bench()
        log(f"시간 예산·계산 상한 끝 — 캐시 저장됨, 다음 회차에 이어서 ({time.time() - t_start:.0f}초)")
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    text =json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text.encode("utf-8")) > SIZE_LIMIT:
        result.pop("primary_window_series", None)
        result["note_size"] = "results.json 크기 상한 때문에 구간별 계열을 뺐다"
        text = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
    (out / "results.json").write_text(text, encoding="utf-8")
    (out / "REPORT.md").write_text(render(result), encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    log(f"완료 ({time.time() - t_start:.0f}초)")
    return 0


# =================================================================================================
# 결과
# =================================================================================================

def _r(x, nd=4):
    if isinstance(x, float):
        return round(x, nd) if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, nd) for v in x]
    return x


def _ck_str(ch: Optional[dict]) -> str:
    if not ch:
        return "-"
    return ", ".join(f"{k}={'Y' if v else ('N' if v is False else '-')}" for k, v in ch.items())


def build_result(cells, judged, full, rows_by_cell, decisions, power, params, smoke: bool, inp: dict) -> dict:
    hz0 = params["primary_horizon"]
    main_keys = {n: cell_key(PRIMARY_SCENARIO, hz0, n) for n in STRATEGIES}
    verdicts: dict[str, Any] = {}
    for n, k in main_keys.items():
        v = judged["cells"][k]["verdict"]
        verdicts[n] = f"SMOKE_ONLY({v})" if smoke else v
    n_pass = sum(judged["cells"][k]["verdict"] == PASS for k in main_keys.values())
    verdicts["passed"] = f"{n_pass}/{len(STRATEGIES)}"
    verdicts["scenario"] = f"B: {SCENARIOS['B'][0]:,} KRW + {SCENARIOS['B'][1]:,}/month, {hz0:g}y windows"
    verdicts["A_same_rule"] = ", ".join(f"{n}={judged['cells'][cell_key('A', hz0, n)]['verdict']}" for n in STRATEGIES)
    verdicts["checks"] = "; ".join(f"{n}: {_ck_str(judged['cells'][k]['checks'])}" for n, k in main_keys.items())
    series_rows = rows_by_cell[main_keys[STRATEGIES[0]]]
    jr, _ = split_rows(series_rows, params["judged_end"])
    series = {"starts": [r["start"] for r in jr],
              "spy_irr": [r["benchmark"]["irr"] for r in jr]}
    for n, k in main_keys.items():
        jj, _ = split_rows(rows_by_cell[k], params["judged_end"])
        series[f"{n}_diff_irr"] = [r["diff_irr"] for r in jj]
    fullc = {k: {kk: vv for kk, vv in v.items() if kk != "twr_daily"} for k, v in full.items()}
    recent = [{k: d[k] for k in ("date", "picks", "exposure", "vol")} for d in decisions[-3:]]
    return _r({
        "judge_version": RULES_VERSION, "smoke": smoke, "source": inp.get("source"), "missing": inp.get("missing", []),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdicts": verdicts, "power": power,
        "rule": {"strategies": {"SPY": "buy and hold (benchmark, same contributions)",
                                "SC2": "Select Sector SPDR top-2 by 252-day total return from prior close, equal weight, monthly, 100% invested (core/forward_tournament_v3.sc2_target)",
                                "SC2VT20": "SC2 with vol target 20% on backfilled unscaled-SC2 prior 126 days, cap 1.0, remainder BIL (0% USD cash before BIL)",
                                "BL30": "SPY 70% + SC2VT20 30%, reset at start and each January (spy-sector-blend-v1 PART E)",
                                "BL50": "SPY 50% + SC2VT20 50%, reset at start and each January"},
                 "scenarios": {k: {"initial_krw": v[0], "monthly_krw": v[1]} for k, v in SCENARIOS.items()},
                 "primary": {"scenario": PRIMARY_SCENARIO, "horizon_years": hz0}, "policy": POLICY,
                 "account": "tax_fx.AccountConfig defaults (Kakao fee 0.1%, FX 95% discount, average cost, dividends reinvested, 22% tax, 2.5M allowance)",
                 "windows": {"horizons": list(params["horizons"]), "step": params["step"], "first_start": params["first_start"],
                             "judged_end": params["judged_end"]},
                 "thresholds": {"win_share_min": WIN_SHARE_MIN, "median_irr_margin": MEDIAN_IRR_MARGIN,
                                "p10_irr_floor": P10_IRR_FLOOR, "mdd_tw_tol": MDD_TW_TOL},
                 "n_trials": N_TRIALS, "full_span": list(params["full_span"])},
        "cells": {k: {**c, **judged["cells"][k]} for k, c in cells.items()},
        "observed_ir_full_span": judged["observed_ir"], "noop": judged["noop"],
        "full_span_B": fullc,
        "contributions_change": contributions_table(judged, cells, hz0),
        "primary_window_series": series,
        "recent_sleeve_decisions": recent,
    })


# =================================================================================================
# 보고서
# =================================================================================================

def _p(x, signed=False, nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x * 100:+.{nd}f}%" if signed else f"{x * 100:.{nd}f}%"


def _man(x):
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x / 10000:,.0f}만 원"


def _yn(v):
    return "—" if v is None else ("통과" if v else "미달")


NAMES = {"SPY": "SPY 그냥 보유", "SC2": "SC2 섹터 상위 2", "SC2VT20": "SC2 + 변동성 맞춤 20%",
         "BL30": "SPY 70% + SC2VT20 30%", "BL50": "SPY 50% + SC2VT20 50%"}
SCEN_NAMES = {"B": "B 1,000만 원 + 월 15만 원 (판정)", "A": "A 1,000만 원, 적립 없음", "C": "C 300만 원 + 월 15만 원",
              "B10": "B10 1억 원 + 월 150만 원 (보고만)"}


def render(r: dict) -> str:
    v, rule = r["verdicts"], r["rule"]
    smoke = r["smoke"]
    hz0 = rule["primary"]["horizon_years"]
    hzs = rule["windows"]["horizons"]
    je = rule["windows"]["judged_end"]
    L = [f"# 적립식 세후 재평가 — 섹터 모멘텀 대 SPY v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if smoke else ''}", "",
         "처음 목돈에 매달 적립금을 더해 오래 굴릴 때, 섹터 모멘텀 전략(SC2·SC2VT20)이나 SPY 와 섞은 것이 한국 세금을 낸 뒤 SPY 보다 "
         "많이 남기는지 본다. 한 시작일만 보지 않고, 2000년 1월부터 매달 시작하는 여러 구간을 모두 굴렸다. "
         "SPY 도 같은 날 같은 돈을 받는다.", "",
         f"**판정 (시나리오 B, {hz0:g}년 구간): 통과 {v['passed']}** — " +
         " · ".join(f"{n} **{v[n]}**" for n in STRATEGIES), "",
         "통과(CONTRIB_BEATS_SPY)는 '전진 원장에 올릴 후보'일 뿐 채택이 아니다. 엔진(챔피언 전략)은 바뀌지 않았다.", "",
         rp.power_line(r["power"]) + f" (판정 기간 {r['power']['years']}년·시도 {r['power']['n_trials']})", "",
         "## 판정 규칙 (결과를 보기 전에 고정)", "",
         f"- 시나리오 B(1,000만 원 + 매달 15만 원, 다음 달부터 매달 첫 거래일), {hz0:g}년 구간, 매달 첫 거래일 시작, 구간 끝이 {je} 이하인 것만 판정.",
         "- 계좌: tax_fx 카카오 기본값(수수료 0.1%, 환전 우대 95%, 이동평균 취득가, 배당 재투자, 양도세 22%·공제 250만 원). "
         "적립금은 목표보다 모자란 종목부터 산다(underweight_first). 끝에 모두 판다고 보고 미납 세금을 뺀 금액으로 비교.",
         f"- 전략마다 모두 만족하면 CONTRIB_BEATS_SPY: ① SPY 보다 많이 남은 구간 비율 ≥ {WIN_SHARE_MIN:.0%} "
         f"② IRR 차이 중앙값 ≥ +{MEDIAN_IRR_MARGIN * 100:.1f}%p ③ IRR 차이 10분위 ≥ {P10_IRR_FLOOR * 100:.1f}%p "
         f"④ 시간가중 최대낙폭 중앙값이 SPY 보다 {MDD_TW_TOL * 100:.0f}%p 넘게 나쁘지 않음.",
         "- 탈락은 classify_fail 로 FAIL / FAIL_UNDERPOWERED(관측 IR 은 같은 기간 한 계좌의 시간가중 일별 수익 차이), "
         "SPY 와 매일 같으면 NOT_EVALUABLE. 시나리오 A·C·B10 과 5년 구간은 같은 규칙을 적용해 보고만 한다.", ""]
    # ---- 판정표
    L += [f"## 판정 — 시나리오 B, {hz0:g}년", "",
          "| 전략 | 이긴 구간 비율 | IRR 차이 중앙값 | IRR 차이 10분위 | 시간가중 MDD 중앙값 (SPY) | ① | ② | ③ | ④ | 판정 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for n in STRATEGIES:
        c = r["cells"][cell_key("B", hz0, n)]
        s, ch = c["judged"], c.get("checks") or {}
        L.append(f"| {NAMES[n]} | {_p(s.get('share_terminal_win'), nd=0)} ({s.get('n_windows')}구간) | {_p(s.get('median_diff_irr'), True, 2)}p | "
                 f"{_p(s.get('p10_diff_irr'), True, 2)}p | {_p(s.get('median_strategy_mdd_tw'))} ({_p(s.get('median_benchmark_mdd_tw'))}) | "
                 f"{_yn(ch.get('win_share'))} | {_yn(ch.get('median_irr'))} | {_yn(ch.get('p10_irr'))} | {_yn(ch.get('mdd_tw'))} | **{c['verdict']}** |")
    c0 = r["cells"][cell_key("B", hz0, STRATEGIES[0])]["judged"]
    if c0.get("n_windows"):
        L += ["", f"주의 — 구간이 크게 겹친다: {c0['n_windows']}개 구간이지만 {c0['span_years']:.1f}년 안에 겹치지 않는 {hz0:g}년 구간은 "
              f"약 {c0['effective_independent_windows']:.1f}개뿐이다. 이긴 비율은 독립 시행 {c0['n_windows']}번만큼 확실하지 않다."]
    L += ["", "관측 IR(판정 기간 한 계좌, 시나리오 B, 시간가중 일별 수익 − SPY): " +
          ", ".join(f"{n} {r['observed_ir_full_span'].get(n) if r['observed_ir_full_span'].get(n) is not None else '—'}" for n in STRATEGIES), ""]
    # ---- 적립이 결론을 바꿨나
    L += ["## 적립이 결론을 바꿨나? (A 적립 없음 대 B 적립, 같은 규칙)", "",
          "| 전략 | A 판정 | A 이긴 비율 / IRR 차이 중앙값 | B 판정 | B 이긴 비율 / IRR 차이 중앙값 | 결론 바뀜 |", "|---|---|---|---|---|---|"]
    for row in r["contributions_change"]:
        L.append(f"| {NAMES[row['strategy']]} | {row['A_verdict']} | {_p(row['A_share_win'], nd=0)} / {_p(row['A_median_diff_irr'], True, 2)}p | "
                 f"{row['B_verdict']} | {_p(row['B_share_win'], nd=0)} / {_p(row['B_median_diff_irr'], True, 2)}p | {'예' if row['changed'] else '아니오'} |")
    # ---- 모든 시나리오
    L += ["", "## 모든 시나리오·구간 길이 (같은 규칙, B·10년 외에는 보고만)", ""]
    for hz in hzs:
        for part, label in (("judged", f"구간 끝 ≤ {je}"), ("reported", f"구간 끝 > {je} (보고만)")):
            L += [f"### {hz:g}년 구간 — {label}", "",
                  "| 시나리오 | 전략 | 구간 수 | 이긴 비율 | IRR 중앙값 (SPY) | IRR 차이 중앙값 / 10분위 / 최악 | 남은 돈 중앙값 (SPY) | 넣은 돈 | 낸 양도세 중앙값 (SPY) | 같은 규칙 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for scen in SCENARIO_ORDER:
                for n in STRATEGIES:
                    c = r["cells"][cell_key(scen, hz, n)]
                    s = c[part]
                    if not s.get("n_windows"):
                        L.append(f"| {scen} | {n} | 0 | — | — | — | — | — | — | — |")
                        continue
                    worst = (s.get("worst_window") or {}).get("diff_irr")
                    ch = contrib_checks(s)
                    rule_v = "충족" if ch and all(x is True for x in ch.values()) else "미충족"
                    if part == "judged":
                        rule_v = c["verdict"]
                    L.append(f"| {scen} | {n} | {s['n_windows']} | {_p(s.get('share_terminal_win'), nd=0)} | "
                             f"{_p(s.get('median_strategy_irr'))} ({_p(s.get('median_benchmark_irr'))}) | "
                             f"{_p(s.get('median_diff_irr'), True, 2)}p / {_p(s.get('p10_diff_irr'), True, 2)}p / {_p(worst, True, 2)}p | "
                             f"{_man(s.get('median_strategy_terminal_krw'))} ({_man(s.get('median_benchmark_terminal_krw'))}) | "
                             f"{_man(s.get('median_total_contributed_krw'))} | "
                             f"{_man(s.get('median_strategy_tax_krw'))} ({_man(s.get('median_benchmark_tax_krw'))}) | {rule_v} |")
            L.append("")
    L += ["시나리오: " + " · ".join(SCEN_NAMES.values()) + ".", "",
          "낸 양도세 = 구간 안에서 실제로 낸 세금(끝에 청산할 때 내는 미납 세금은 남은 돈에서 이미 뺐다). "
          "SPY 그냥 보유는 팔지 않아 세금이 끝까지 미뤄진다 — 적립식에서도 같은 이점이 있다.", ""]
    # ---- 한 계좌 전체 기간
    fs = r["full_span_B"]
    L += [f"## 판정 기간 한 계좌 (시나리오 B, {rule['full_span'][0]} ~ {rule['full_span'][1]}) — 회전율·비용", "",
          "| 전략 | IRR(청산 후) | 세전 IRR | 시간가중 MDD | 낸 양도세 | 수수료 | 환전 비용 | 편도 회전율(연) |", "|---|---|---|---|---|---|---|---|"]
    for n in ("SPY",) + STRATEGIES:
        x = fs[n]
        L.append(f"| {NAMES[n]} | {_p(x['irr_after_liquidation'], nd=2)} | {_p(x['irr_pre_cost'], nd=2)} | {_p(x['mdd_tw'])} | "
                 f"{_man(x['capital_gains_tax_krw'])} | {_man(x['fees_krw'])} | {_man(x['fx_cost_krw'])} | {_p(x['turnover_one_way_per_year'], nd=0)} |")
    L += ["", "## 주의", "",
          "- 구간이 서로 크게 겹친다. 매달 시작하는 구간 수가 많아도 실제로 독립적인 10년은 2~3개뿐이라 '이긴 비율'은 생각보다 덜 확실하다.",
          "- 섹터 ETF 메뉴(미국 Select Sector SPDR)와 SPY 기준은 미국 시장이 지난 25년 강했다는 사후 지식이 일부 섞인 선택이다. "
          "XLRE·XLC 는 252거래일 신호가 생긴 뒤에만 후보가 된다.",
          "- 2000~2024 ETF 자료는 이미 여러 연구(sector-concentrate-v1·spy-sector-blend-v1 등)가 본 구간이다. 2024-10 이후 끝나는 구간은 보고만 한다.",
          "- 섹터 전략·섞기는 매월 첫 거래일이 리밸런싱 날이라 적립금이 그날 목표 비중대로 들어간다. "
          "'모자란 종목부터 사기(underweight_first)'가 따로 작동하는 것은 SPY 그냥 보유뿐이다.",
          "- BIL 상장(2007-05) 전에는 SC2VT20 의 남는 몫을 이자 없는 달러 현금으로 두었다(소매에 불리한 근사).",
          "- 세금은 tax_fx 추정이며 신고용이 아니다. 배당 종합과세(2,000만 원 초과)는 넣지 않았다.",
          "- 통과는 '전진 원장 후보'까지만 뜻한다. 엔진은 바뀌지 않았다. 엔진 반영은 사용자 확인 뒤 별도 작업이다. 투자 조언이 아니다."]
    if smoke:
        L += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
