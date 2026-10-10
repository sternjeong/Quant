"""검증 satellite-value-v1 (2026-10-10 사전 등록): 새틀라이트 15% 는 정직한 후보 풀에서도 'SPY 15%'보다 나은가.

계기: champion-aftertax-v1 은 코어 85% + 새틀라이트 15% 세후 11.13%, 코어만 9.30%(2010~2026, 3,000만 원)를 쟀다.
그러나 그 새틀라이트 선정은 2026-10-08 이전 champion40 풀(그 시점 시총 근사가 2015 말 이전 분할을 두 번 세어 2014 AAPL 6배 등
과대 → 나중에 분할한 승자 쪽으로 기울고, FB→META 등 이름 바뀐 종목이 빠짐)을 썼고, 작업 문서 스스로 생존편향을 한계로 적었다.
이 연구는 고친 풀(champion40 pit2, sat-judge/v3)로 같은 세후 원화 계좌 시뮬레이션(core/tax_fx.py)을 다시 돌려,
새틀라이트 15% 를 SPY 15% 로 바꿔 그냥 들고 있는 것보다 나은지 판정한다. 엔진 변경은 사용자 확인 뒤 별도 작업이다.

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
변형(모두 같은 tax_fx.simulate, 같은 코어 일별 목표 비중, 같은 시작일 = 첫 반기 선정일):
  A  코어 85% + 새틀라이트 15% — 라이브 규칙(_pick_satellite_at_date: 돈치안 20일 추세 활성 중 12개월 모멘텀 상위 3, 균등, 반기 1·7월)
     을 라이브가 쓰는 champion40 풀(sample_universe(n=40, 그 시점 편입·그 시점 시총) = 랩 champion40 pit2)에서. 새틀라이트 R&D 랩의
     S-SEED-000(tests/test_satellite_lab.py 가 챔피언 선정과 같음을 확인)으로 일정을 만든다.
  A2 같은 규칙, sp500_pit 풀(그 시점 S&P500 편입 전체) — 보고용.
  B  코어 85% + SPY 15%. SPY 목표 비중은 항상 15%. 슬리브 규약은 A 와 같다: tax_fx.simulate 는 전체 목표 비중이 바뀌는 날(코어 신호 변경일,
     A 는 반기 선정일 포함)에만 매매하고 그날 모든 종목(15% 슬리브 포함)을 목표로 맞춘다. 그 사이는 가격대로 표류. 양도세 납부 현금이
     모자라면 모든 보유를 비중대로 판다(A 와 같음). 그 밖에는 SPY 를 팔지 않는다.
  C  SPY 100% 그냥 보유(참고).  D  코어만(참고).
계좌: core/tax_fx.AccountConfig 기본(카카오페이증권 — 수수료 0.1%, 달러 보유·환전 스프레드 0.05%, 양도세 250만 원 공제 후 22%,
  이동평균 취득가, 배당 원천징수 15% 즉시 재투자), 초기 3,000만 원(판정). 1억 원은 보고만.
지표: 세후 연수익 = 원화 평가액(낸 세금 반영, 미실현 세금 제외) 기준 연복리. 구간 연수익은 구간 시작 평가액(첫 구간은 초기 원금) 대비.
판정 구간: 시작일 ~ 2024-09-30(2024-10 이후는 20개 넘는 연구가 이미 본 구간이라 보고만). 두 절반 = 판정 구간을 달력 날짜 가운데에서 나눔.
판정(A − B, 3,000만 원):
  KEEP_SATELLITE      판정 구간 차이 ≥ +0.3%p, 두 절반 모두 > 0, 6개월(126거래일) 블록 부트스트랩 1,000회 90% 구간 하한 > −0.5%p
  SIMPLIFY_CANDIDATE  판정 구간 차이 < 0
  INCONCLUSIVE        그 밖
  NOT_EVALUABLE       A 와 B 의 일별 수익이 매일 같음(noop_guard) 또는 수치가 유한하지 않음
부트스트랩: A·B 일별 세후 수익을 짝지은 채 순환 이동 블록(126거래일)으로 재표집, 각 표본의 연수익 차이, 시드 20261010, 백분위 5·95.
검정력: power_report(판정 구간 연수, 시도 1) 과 A−B 일별 차이의 연 IR. KEEP 이 아니면 classify_fail 로 검정력 부족 여부를 함께 적는다.

한계: 상장폐지 종목은 가격 소스에 없어 후보에서 빠짐(생존편향 잔존 — A 를 실제보다 좋게 만들 수 있음), 일봉 종가 체결,
금융소득 종합과세 미반영, champion40 의 과거 시총은 근사, 랩 풀은 1/1·7/1 기준이고 라이브는 그 달 첫 거래일 기준.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import signal as _signal
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import research_power as rp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "satellite-value-v1"
RULES_VERSION = "satellite-value-v1/2026-10-10"
START = "2010-01-01"
SAT_WEIGHT = 0.15
DECISION_END = "2024-09-30"       # 이 날까지(포함)가 판정 구간. 2024-10-01 부터는 보고만
MIN_FULL_DIFF = 0.003             # +0.3%p
CI_LOW_FLOOR = -0.005             # −0.5%p
N_BOOT = 1000
BLOCK_DAYS = 126                  # 약 6개월
BOOT_SEED = 20261010
CI_PCT = (5.0, 95.0)              # 90% 구간
VARIANTS = ("A", "A2", "B", "C", "D")
SETUPS = {"base_30m": {}, "base_100m": {"initial_krw": 100_000_000}}
DECISION_SETUP = "base_30m"
PAIRS = (("A", "B"), ("A2", "B"), ("A", "D"), ("B", "D"), ("A", "C"))
OLD_JOB = "champion-aftertax-v1"
NAMES = {"A": "코어 85% + 새틀라이트 15%(champion40 pit2, 라이브 풀)", "A2": "코어 85% + 새틀라이트 15%(sp500_pit 풀)",
         "B": "코어 85% + SPY 15%", "C": "SPY 100% 그냥 보유", "D": "코어만"}

KEEP, SIMPLIFY, INCONCLUSIVE, NOT_EVALUABLE = "KEEP_SATELLITE", "SIMPLIFY_CANDIDATE", "INCONCLUSIVE", "NOT_EVALUABLE"


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


# =================================================================================================
# 판정·통계 (순수 함수 — tests/test_satellite_value_research.py)
# =================================================================================================

def decide(full_diff: float, h1_diff: float, h2_diff: float, ci_low: float, noop_reason: Optional[str] = None) -> str:
    """사전 등록 판정. 입력은 A − B 세후 연수익 차이(소수, 0.003 = 0.3%p)."""
    if noop_reason:
        return NOT_EVALUABLE
    vals = (full_diff, h1_diff, h2_diff, ci_low)
    if any(v is None or not math.isfinite(float(v)) for v in vals):
        return NOT_EVALUABLE
    if full_diff >= MIN_FULL_DIFF and h1_diff > 0 and h2_diff > 0 and ci_low > CI_LOW_FLOOR:
        return KEEP
    if full_diff < 0:
        return SIMPLIFY
    return INCONCLUSIVE


def ann_from_returns(r: np.ndarray, ppy: float) -> np.ndarray:
    """일별 수익(…×n) → 연복리(마지막 축). ppy = 1년당 관측 수."""
    n = r.shape[-1]
    return np.exp(np.log1p(r).sum(axis=-1) * (ppy / n)) - 1.0


def block_bootstrap_diff(ra: np.ndarray, rb: np.ndarray, ppy: float, *, n_boot: int = N_BOOT,
                         block: int = BLOCK_DAYS, seed: int = BOOT_SEED) -> np.ndarray:
    """짝지은 일별 수익을 순환 이동 블록으로 재표집해 '연수익(A) − 연수익(B)' 분포를 돌려준다(결정론, 시드 고정)."""
    ra, rb = np.asarray(ra, dtype=float), np.asarray(rb, dtype=float)
    n = len(ra)
    if n == 0 or len(rb) != n:
        raise ValueError("두 수익 계열의 길이가 같고 0 보다 커야 합니다")
    block = max(1, min(int(block), n))
    n_blocks = -(-n // block)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(n_boot, -1)[:, :n]
    return ann_from_returns(ra[idx], ppy) - ann_from_returns(rb[idx], ppy)


def seg_ann(values: pd.Series, initial: float, t0: Optional[pd.Timestamp], t1: pd.Timestamp) -> float:
    """구간 연복리. t0=None 이면 시작일·초기 원금 기준(= tax_fx 의 cagr_after 와 같은 정의)."""
    base, d0 = (initial, values.index[0]) if t0 is None else (float(values.loc[t0]), t0)
    years = (t1 - d0).days / 365.25
    v1 = float(values.loc[t1])
    if years <= 0 or base <= 0 or v1 <= 0:
        return float("nan")
    return (v1 / base) ** (1 / years) - 1


def window_returns(values: pd.Series, initial: float, t1: pd.Timestamp) -> pd.Series:
    """시작일 ~ t1 의 일별 세후 수익. 첫날은 초기 원금 대비(매수 비용 포함) — 곱하면 values[t1]/initial."""
    v = values.loc[:t1]
    prev = v.shift(1)
    prev.iloc[0] = initial
    return v / prev - 1.0


def segments(index: pd.DatetimeIndex) -> dict:
    """판정 구간·두 절반·2024-10 이후·전체의 (t0, t1). t0=None 은 시작일·초기 원금 기준."""
    first, last = index[0], index[-1]
    dec = index[index <= pd.Timestamp(DECISION_END)]
    if len(dec) < 2:
        raise ValueError("판정 구간 데이터가 부족합니다")
    dec_end = dec[-1]
    mid = first + (dec_end - first) / 2
    h1_end = index[index <= mid][-1]
    out = {"decision": (None, dec_end), "h1": (None, h1_end), "h2": (h1_end, dec_end), "whole": (None, last)}
    if last > dec_end:
        out["post_2024_10"] = (dec_end, last)
    return out


def build_weights(core_w: pd.DataFrame, logs: dict) -> dict[str, pd.DataFrame]:
    """다섯 변형의 일별 목표 비중(같은 날짜 축 — A 의 첫 선정일부터)."""
    a = tx.champion_weights(core_w, logs["A"], SAT_WEIGHT)
    idx = a.index
    a2 = tx.champion_weights(core_w, logs["A2"], SAT_WEIGHT).reindex(idx).fillna(0.0)
    spy_log = [{"date": r["date"], "weights": {"SPY": 1.0}} for r in logs["A"]]
    b = tx.champion_weights(core_w, spy_log, SAT_WEIGHT).reindex(idx).fillna(0.0)
    return {"A": a, "A2": a2, "B": b, "C": tx.buy_and_hold_weights(idx), "D": core_w.reindex(idx).fillna(0.0)}


def schedule_to_log(schedule: list) -> list[dict]:
    """랩 일정 [(날짜, 종목들)] → champion_weights 용 반기 기록(균등가중, 빈 선정 = 새틀라이트 현금)."""
    return [{"date": str(pd.Timestamp(d).date()), "weights": ({t: 1.0 / len(p) for t in p} if p else {})}
            for d, p in schedule]


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


def _load_ckpt(path: Path, fingerprint: dict):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)  # 이 스크립트가 쓴 파일만 읽는다
    except Exception:  # noqa: BLE001
        return None
    return obj["payload"] if obj.get("fingerprint") == fingerprint else None


# =================================================================================================
# 입력
# =================================================================================================

def _incumbent():
    from core import satellite_lab as sl

    spec, code = sl.read_variant_dir(sl.SEEDS_DIR / sl.INCUMBENT_ID)
    return spec, sl.load_signal(code), dict(spec["signal"]["params_grid"][0])


def _schedules(data) -> dict:
    from core import satellite_lab as sl

    spec, signal, params = _incumbent()
    logs = {}
    for key, pool in (("A", "champion40"), ("A2", "sp500_pit")):
        sp = json.loads(json.dumps(spec))
        sp["pool"] = {"type": pool}
        logs[key] = schedule_to_log(sl.run_variant(sp, params, signal, data)["schedule"])
    return logs


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


def _panel(frames: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    close, adj = {}, {}
    for t, df in frames.items():
        if df is None or df.empty or "Close" not in df:
            continue
        df = _norm(df)
        close[t] = df["Close"]
        adj[t] = df["Adj Close"] if "Adj Close" in df.columns and df["Adj Close"].notna().any() else df["Close"]
    return pd.DataFrame(close), pd.DataFrame(adj)


def _pool_wrapper(base, start_d: date):
    # build_data 를 시작일 한 달 전부터 읽어(첫 반기 선정일 2010-01 의 '전날'이 있게) 그 전 달의 풀은 비운다.
    return lambda pt, d: [] if d < start_d else base(pt, d)


def _real_inputs(log) -> dict:
    from core import champion_strategy as cs
    from core import satellite_lab as sl
    from core.market_data import get_multiple_price_history

    log("코어 백테스트(일별 목표 비중)")
    core_w = cs.run_core_backtest(START)["weights"]
    pool = _pool_wrapper(sl.default_pool_provider(), date.fromisoformat(START))
    data = sl.build_data({"champion40", "sp500_pit"}, start="2009-12-01", pool_provider=pool, log=log)
    log("새틀라이트 일정(A: champion40, A2: sp500_pit)")
    logs = _schedules(data)
    picks = sorted({t for lg in logs.values() for r in lg for t in r["weights"]})
    others = sorted((set(core_w.columns) | {"SPY"}) - set(picks))
    hist = get_multiple_price_history(others, start="2009-06-01", end=None, interval="1d")
    frames = {t: hist.get(t) for t in others}
    frames.update({t: data.ohlcv.get(t) for t in picks})
    close, adj = _panel(frames)
    fx = tx.usdkrw_series()
    return {"core_w": core_w, "logs": logs, "close": close, "adj": adj, "fx": fx,
            "meta": {"live_satellite_weight": cs.SATELLITE_WEIGHT, "live_pool_n": cs.SATELLITE_BACKTEST_POOL_N,
                     "live_top_k": cs.SATELLITE_BACKTEST_TOP_K, "strategy_version": cs.CHAMPION_STRATEGY_VERSION,
                     "judge_version": sl.JUDGE_VERSION, "pool_cache_tag": sl.POOL_CACHE_TAG,
                     "core_universe": list(core_w.columns)}}


def _smoke_inputs(log) -> dict:
    """합성 데이터(네트워크 없음). 실데이터가 아니다."""
    from core import satellite_lab as sl

    end = "2026-06-30"
    pp, poolp = sl.synthetic_providers(n_tickers=50, start="2008-01-01", end=end, seed=7)
    pool = _pool_wrapper(poolp, date.fromisoformat(START))
    data = sl.build_data({"champion40", "sp500_pit"}, start="2009-12-01", end=end, pool_provider=pool, price_provider=pp)
    logs = _schedules(data)
    idx = data.trading_days[data.trading_days >= pd.Timestamp(START)]
    rng = np.random.default_rng(5)
    frames = {t: data.ohlcv[t] for r in [x for lg in logs.values() for x in lg] for t in r["weights"]}
    frames["SPY"] = pp("SPY", "2008-01-01", end)
    full = pd.bdate_range("2008-01-01", end)
    for t in ("C1", "C2"):
        c = 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(full))))
        frames[t] = pd.DataFrame({"Close": c, "Adj Close": c * np.exp(np.linspace(0, 0.3, len(full)))}, index=full)
    core_w = pd.DataFrame(0.0, index=idx, columns=["C1", "C2"])
    core_w.loc[core_w.index.month % 2 == 0, "C1"] = 1.0
    core_w.loc[core_w.index.month % 2 == 1, "C2"] = 1.0
    core_w.loc[core_w.index.month == 3, "C2"] = 0.5   # 시장 필터처럼 일부 현금
    close, adj = _panel(frames)
    fx = pd.Series(1100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(full)))), index=full)
    return {"core_w": core_w, "logs": logs, "close": close, "adj": adj, "fx": fx,
            "meta": {"live_satellite_weight": SAT_WEIGHT, "synthetic": True}}


# =================================================================================================
# 분석
# =================================================================================================

def _pair_stats(va: pd.Series, vb: pd.Series, initial: float, segs: dict, *, with_boot: bool = True) -> dict:
    out = {f"{k}_diff": seg_ann(va, initial, t0, t1) - seg_ann(vb, initial, t0, t1) for k, (t0, t1) in segs.items()}
    dec_end = segs["decision"][1]
    ra, rb = window_returns(va, initial, dec_end), window_returns(vb, initial, dec_end)
    years = (dec_end - va.index[0]).days / 365.25
    ppy = len(ra) / years
    d = (ra - rb).to_numpy()
    sd = float(np.std(d, ddof=1)) if len(d) > 1 else float("nan")
    out["daily_diff_ir"] = float(np.mean(d) / sd * math.sqrt(ppy)) if sd and math.isfinite(sd) and sd > 0 else float("nan")
    out["noop_reason"] = rp.noop_guard(d)
    out["decision_years"] = years
    out["periods_per_year"] = ppy
    if with_boot:
        boot = block_bootstrap_diff(ra.to_numpy(), rb.to_numpy(), ppy)
        lo, hi = np.percentile(boot, CI_PCT)
        out.update({"boot_ci90_low": float(lo), "boot_ci90_high": float(hi), "boot_median": float(np.median(boot)),
                    "boot_share_positive": float(np.mean(boot > 0))})
    return out


def _old_comparison(new30: dict) -> dict:
    path = PROJECT_ROOT / "research" / "results" / OLD_JOB / "results.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        m = old["metrics"]["base_30m"]
    except (OSError, ValueError, KeyError):
        return {"available": False}
    o = {"champion": m["champion"]["cagr_after"], "core_only": m["core_only"]["cagr_after"], "spy": m["spy"]["cagr_after"]}
    n = {"champion": new30["A"]["cagr_after"], "core_only": new30["D"]["cagr_after"], "spy": new30["C"]["cagr_after"]}
    old_inc, new_inc = o["champion"] - o["core_only"], n["champion"] - n["core_only"]
    return {"available": True, "old_period": f"{old.get('start')} ~ {old.get('end')}", "old_after_tax": o, "new_after_tax_whole": n,
            "old_satellite_increment": old_inc, "new_satellite_increment": new_inc,
            "bias_estimate_increment": old_inc - new_inc,
            "note": "옛 결과는 2026-10-06 계산(분할 이중 계산이 있던 champion40 풀, 코어에 DBC 포함). 코어도 그 뒤 바뀌었으므로 "
                    "새틀라이트 편향 크기는 '새틀라이트 증분(챔피언 − 코어만)'의 차이로 본다. 끝 날짜도 다르다."}


def _pct(x, signed: bool = False) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x:+.2%}" if signed else f"{x:.2%}"


def _pp(x) -> str:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x):
        return "—"
    return f"{x * 100:+.2f}%p"


def analyze(sims: dict, inputs: dict, smoke: bool) -> tuple[dict, str]:
    idx = sims[DECISION_SETUP]["A"]["values"].index
    segs = segments(idx)
    seg_dates = {k: [str(t0.date()) if t0 is not None else str(idx[0].date()), str(t1.date())] for k, (t0, t1) in segs.items()}
    metrics, pairs = {}, {}
    for sname, cfg_over in SETUPS.items():
        initial = tx.AccountConfig(**cfg_over).initial_krw
        metrics[sname] = {}
        for v in VARIANTS:
            s = sims[sname][v]
            vals = s["values"]
            metrics[sname][v] = {**{k: s[k] for k in ("cagr_pre", "cagr_after", "mdd_after", "final_krw",
                                                      "final_after_liquidation_krw", "totals")},
                                 "segments_after_tax": {k: seg_ann(vals, initial, t0, t1) for k, (t0, t1) in segs.items()}}
        pairs[sname] = {f"{a}-{b}": _pair_stats(sims[sname][a]["values"], sims[sname][b]["values"], initial, segs,
                                                with_boot=(sname == DECISION_SETUP))
                        for a, b in PAIRS}
    ab = pairs[DECISION_SETUP]["A-B"]
    verdict = decide(ab["decision_diff"], ab["h1_diff"], ab["h2_diff"], ab.get("boot_ci90_low", float("nan")), ab["noop_reason"])
    power = rp.power_report(ab["decision_years"], 1)
    power_class = None if verdict in (KEEP, NOT_EVALUABLE) else rp.classify_fail(ab["daily_diff_ir"], power)
    if smoke:
        verdict_out = {"satellite_vs_spy15": f"SMOKE_ONLY({verdict})"}
    else:
        verdict_out = {"satellite_vs_spy15": verdict}
    old_cmp = _old_comparison({v: metrics[DECISION_SETUP][v] for v in VARIANTS})
    logs = inputs["logs"]
    used = set().union(*(set(w.columns[(w.abs().sum() > 0)]) for w in build_weights(inputs["core_w"], logs).values()))
    missing = sorted(t for t in used if t not in inputs["close"].columns or inputs["close"][t].dropna().empty)
    result = {
        "kind": "pre-registered verdict", "id": JOB_ID, "rules_version": RULES_VERSION, "smoke": smoke,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": str(idx[0].date()), "end": str(idx[-1].date()), "segments": seg_dates,
        "rules": {"decision_setup": DECISION_SETUP, "decision_end": DECISION_END, "min_full_diff": MIN_FULL_DIFF,
                  "halves_positive": True, "ci_low_floor": CI_LOW_FLOOR, "n_boot": N_BOOT, "block_days": BLOCK_DAYS,
                  "boot_seed": BOOT_SEED, "ci_percentiles": list(CI_PCT), "satellite_weight": SAT_WEIGHT,
                  "post_2024_10": "report only"},
        "variants": NAMES, "live_pool": "champion40 (sample_universe n=40, point-in-time constituents + point-in-time market cap, "
                                        "pit2 fix 2026-10-08) — core.champion_strategy._pick_satellite_at_date, "
                                        "used by compute_satellite_recommendation_point_in_time (paper_auto_trade, champion_recommendation)",
        "sleeve_convention": "목표 비중이 바뀌는 날에만 매매하고 그날 모든 종목을 목표로 맞춘다(A·B 동일). B 의 SPY 목표는 항상 15%.",
        "metrics": metrics, "pairs": pairs, "power": power, "power_line": rp.power_line(power), "power_class": power_class,
        "noop_guard": ab["noop_reason"], "verdict_raw": verdict, "verdicts": verdict_out,
        "old_comparison": old_cmp, "inputs_meta": inputs.get("meta", {}), "missing_prices": missing,
        "satellite_schedule": {k: [{"date": r["date"], "picks": sorted(r["weights"])} for r in lg] for k, lg in logs.items()},
    }
    return result, _report(result)


def _report(r: dict) -> str:
    m, pr = r["metrics"][DECISION_SETUP], r["pairs"][DECISION_SETUP]
    ab = pr["A-B"]
    sg = r["segments"]
    L = [f"# 새틀라이트 15% 는 SPY 15% 보다 나은가 — 정직한 후보 풀, 세후 원화{' (스모크 — 합성 데이터)' if r['smoke'] else ''}", "",
         f"판정: **{r['verdicts']['satellite_vs_spy15']}** (A − B, 3,000만 원, 판정 구간 {sg['decision'][0]} ~ {sg['decision'][1]})", "",
         f"- 판정 구간 차이 {_pp(ab['decision_diff'])} (기준 ≥ +0.30%p) · 앞 절반 {_pp(ab['h1_diff'])} · 뒤 절반 {_pp(ab['h2_diff'])} (기준: 둘 다 > 0)",
         f"- 6개월 블록 부트스트랩 {N_BOOT}회 90% 구간 {_pp(ab.get('boot_ci90_low'))} ~ {_pp(ab.get('boot_ci90_high'))} (하한 기준 > −0.50%p), "
         f"차이 > 0 비율 {ab.get('boot_share_positive', float('nan')):.0%}",
         f"- {r['power_line']} 관측 A−B 일별 차이 연 IR {ab['daily_diff_ir']:.2f}."
         + (f" 검정력 분류: {r['power_class']}." if r["power_class"] else ""),
         f"- 무효 실행 가드: {r['noop_guard'] or '통과(A 와 B 가 다름)'}",
         "- 2024-10 이후는 판정에 쓰지 않는다(보고만).", "",
         "## 세후 연수익(3,000만 원)", "",
         "| 변형 | 판정 구간 | 앞 절반 | 뒤 절반 | 2024-10~ (보고) | 전체 | 원화 MDD(전체) | 양도세(백만) |", "|---|---|---|---|---|---|---|---|"]
    for v in VARIANTS:
        s = m[v]["segments_after_tax"]
        L.append(f"| {v} {NAMES[v]} | {_pct(s['decision'])} | {_pct(s['h1'])} | {_pct(s['h2'])} | {_pct(s.get('post_2024_10'))} | "
                 f"{_pct(s['whole'])} | {m[v]['mdd_after']:.1%} | {m[v]['totals']['capital_gains_tax_krw'] / 1e6:.1f} |")
    L += ["", "## 차이(세후 연수익, %p)", "",
          "| 비교 | 판정 구간 | 앞 절반 | 뒤 절반 | 부트스트랩 90% | 연 IR | 2024-10~ (보고) | 전체 |", "|---|---|---|---|---|---|---|---|"]
    for k, p in pr.items():
        L.append(f"| {k} | {_pp(p['decision_diff'])} | {_pp(p['h1_diff'])} | {_pp(p['h2_diff'])} | "
                 f"{_pp(p.get('boot_ci90_low'))} ~ {_pp(p.get('boot_ci90_high'))} | {p['daily_diff_ir']:.2f} | "
                 f"{_pp(p.get('post_2024_10_diff'))} | {_pp(p['whole_diff'])} |")
    L += ["", "A−B 만 판정에 쓴다. A2−B(sp500_pit 풀)·A−D·B−D·A−C 는 보고용이다.", ""]
    m1 = r["metrics"]["base_100m"]
    p1 = r["pairs"]["base_100m"]["A-B"]
    L += ["## 초기 1억 원(보고만)", "",
          "세후 연수익(판정 구간 / 전체): " + ", ".join(f"{v} {_pct(m1[v]['segments_after_tax']['decision'])} / {_pct(m1[v]['cagr_after'])}"
                                              for v in VARIANTS) + f". A−B 판정 구간 {_pp(p1['decision_diff'])}.", ""]
    oc = r["old_comparison"]
    if oc.get("available"):
        o, n = oc["old_after_tax"], oc["new_after_tax_whole"]
        L += ["## 옛 숫자(champion-aftertax-v1)와 비교 — 편향 크기", "",
              f"| | 옛({oc['old_period']}) | 이번(전체 {r['start']} ~ {r['end']}) |", "|---|---|---|",
              f"| 코어 85% + 새틀라이트 15% | {_pct(o['champion'])} | {_pct(n['champion'])} |",
              f"| 코어만 | {_pct(o['core_only'])} | {_pct(n['core_only'])} |",
              f"| SPY 그냥 보유 | {_pct(o['spy'])} | {_pct(n['spy'])} |",
              f"| 새틀라이트 증분(챔피언 − 코어만) | {_pp(oc['old_satellite_increment'])} | {_pp(oc['new_satellite_increment'])} |", "",
              f"편향 추정(옛 증분 − 새 증분): {_pp(oc['bias_estimate_increment'])} — +면 옛 결과가 새틀라이트 몫을 그만큼 부풀렸다는 뜻(코어 변경·기간 차이가 일부 섞임). {oc['note']}", ""]
    L += ["## 규약", "",
          f"- 라이브 풀: {r['live_pool']}.",
          f"- 슬리브: {r['sleeve_convention']} 양도세 납부 현금이 모자라면 모든 보유를 비중대로 판다(A·B 동일).",
          "- 계좌: 카카오페이증권 가정(수수료 0.1%, 달러 보유·환전 스프레드 0.05%, 양도세 250만 원 공제 후 22%, 이동평균, 배당 원천징수 15% 재투자).",
          f"- 가격 없는 보유 종목: {', '.join(r['missing_prices']) or '없음'}.", "",
          "## 한계", "",
          "- 상장폐지 종목은 가격 소스에 없어 후보에서 빠진다(생존편향 잔존 — 새틀라이트를 실제보다 좋게 만들 수 있다).",
          "- 일봉 종가 체결(슬리피지 없음), 금융소득 종합과세(연 2,000만 원 초과) 미반영, champion40 과거 시총은 근사.",
          "- 랩 풀은 1/1·7/1 기준, 라이브는 그 달 첫 거래일 기준(편입 명단이 그 사이 바뀌면 다를 수 있다).",
          "- 새틀라이트 비중(15% vs 25·35·50%)은 별도 연구 sleeve-weight-v1 이 다룬다. 이 연구는 15% 의 쓰임새만 본다.",
          "- 과거 결과이며 앞으로의 수익을 뜻하지 않는다. 엔진 반영은 사용자 확인 뒤 별도 작업이다."]
    return "\n".join(L) + "\n"


# =================================================================================================
# 실행
# =================================================================================================

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--max-sims-per-run", type=int, default=0, help="재개 확인용: 이번 실행에서 새로 할 시뮬레이션 수 상한(0=없음)")
    a = p.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None

    def log(s: str) -> None:
        print(s, flush=True)

    def check_time(margin: float = 90.0) -> None:
        if deadline is not None and time.time() > deadline - margin:
            raise _Stop()

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old_handler = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        inputs = _load_ckpt(ck / "inputs.pkl", fp)
        if inputs is None:
            inputs = _smoke_inputs(log) if a.smoke else _real_inputs(log)
            _atomic_pickle(ck / "inputs.pkl", {"fingerprint": fp, "payload": inputs})
            log("입력 체크포인트 저장")
        weights = build_weights(inputs["core_w"], inputs["logs"])
        sims: dict = {}
        new = 0
        for sname, over in SETUPS.items():
            cfg = tx.AccountConfig(**over)
            for v in VARIANTS:
                path = ck / f"sim_{sname}_{v}.pkl"
                got = _load_ckpt(path, fp)
                if got is None:
                    if a.max_sims_per_run and new >= a.max_sims_per_run:
                        raise _Stop()
                    check_time()
                    log(f"시뮬레이션 {sname} {v}")
                    s = tx.simulate(weights[v], inputs["close"], inputs["adj"], inputs["fx"], cfg)
                    got = {k: s[k] for k in ("cagr_pre", "cagr_after", "mdd_after", "final_krw", "final_after_liquidation_krw", "totals")}
                    got["values"] = s["values_krw"]
                    _atomic_pickle(path, {"fingerprint": fp, "payload": got})
                    new += 1
                sims.setdefault(sname, {})[v] = got
        result, report = analyze(sims, inputs, a.smoke)
    except _Stop:
        log("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서")
        return 3
    finally:
        if old_handler is not None:
            _signal.signal(_signal.SIGTERM, old_handler)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report, encoding="utf-8")
    log(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
