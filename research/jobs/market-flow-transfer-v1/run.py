"""검증 연구 market-flow-transfer-v1 (2026-10-30 사전 등록): 기술이 크게 빠진 뒤 다른 산업이 시장보다 더 버나.

사용자 가설: 한 시장에서 빠진 돈이 다른 시장으로 들어간다. 2008 이후 ETF 표본은 화면 탐색에서 이미 봤으므로(보정 후 유의 0)
판정에 쓰지 않고, 아무도 보지 않은 Ken French 12 산업 일별 1926~2007 로 판정한다. 규칙 전체는 SPEC.md 와 아래 상수에 결과를
보기 전에 고정했다. 바꾸려면 새 id 로 다시 등록한다. 엔진·주문 규칙은 바꾸지 않는다.
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
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import market_flow as mf  # noqa: E402

_spec = importlib.util.spec_from_file_location("core_longrun_lab", PROJECT_ROOT / "research/jobs/core-longrun-v1/lab.py")
lab = sys.modules.setdefault("core_longrun_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "Rule"):
    _spec.loader.exec_module(lab)

JOB_ID = "market-flow-transfer-v1"
RULES_VERSION = "market-flow-transfer-v1/2026-10-30"

# --- 고정 상수 (사전 등록) ---------------------------------------------------------------------------
DATA_START, DATA_END = "1926-07-01", "2007-12-31"
SOURCE_REAL, SOURCE_SMOKE = "BusEq", "I05"
DEFENSIVE_REAL, DEFENSIVE_SMOKE = ("NoDur", "Utils", "Hlth"), ("I00", "I01", "I02")
TRIGGER_WINDOW, HORIZON, QUANTILE, MIN_HISTORY = 21, 21, 0.10, 504
N_TESTS = 12                      # 11 산업 + DEFENSIVE
ALPHA = 0.05 / N_TESTS            # Bonferroni
ECON_FLOOR = 0.30                 # (b) %p / 21행
SPLIT = pd.Timestamp("1967-01-01")
MIN_HALF_EPISODES = 10
MIN_EPISODES_SOURCE = 5
POWER_TARGET = 0.80
SENSITIVITY = (("63행 트리거·63행 효과·하위20%", 63, 63, 0.20), ("21행·21행·하위5%", 21, 21, 0.05),
               ("21행 트리거·63행 효과·하위10%", 21, 63, 0.10))
PASS, FAIL, UNDERPOWERED, NOT_EVALUABLE = "PASS_FORWARD_CANDIDATE", "FAIL", "FAIL_UNDERPOWERED", "NOT_EVALUABLE"

_N = NormalDist()


class _Stop(Exception):
    """시간 예산 끝 또는 SIGTERM — 체크포인트는 이미 저장돼 있다."""


def build_levels(data: dict, smoke: bool) -> tuple[pd.DataFrame, str]:
    """12 산업 + MKT + DEFENSIVE 의 누적 수준(1926-07 ~ 2007-12). 시작 전 결측은 그대로 둔다."""
    ret = data["ind12"].loc[DATA_START:DATA_END].copy()
    mkt = data["mkt"].reindex(ret.index)
    members = list(DEFENSIVE_SMOKE if smoke else DEFENSIVE_REAL)
    ret["DEFENSIVE"] = ret[members].mean(axis=1)
    ret["MKT"] = mkt
    levels = (1 + ret.fillna(0.0)).cumprod()
    return levels, (SOURCE_SMOKE if smoke else SOURCE_REAL)


def mde_mean_excess(sd: float, n: int) -> float | None:
    """80% 검정력으로 Bonferroni α 에서 잡을 수 있는 최소 평균 초과수익(%p)."""
    if not (n >= mf.MIN_EPISODES_FOR_STAT and sd and math.isfinite(sd) and sd > 0):
        return None
    return float((_N.inv_cdf(1 - ALPHA / 2) + _N.inv_cdf(POWER_TARGET)) * sd / math.sqrt(n))


def target_verdict(row: pd.Series, samples: pd.Series | None) -> dict[str, Any]:
    out: dict[str, Any] = {"episodes": int(row["episodes"]), "mean_excess": _num(row["mean_excess"]), "t_stat": _num(row["t_stat"]),
                           "p_value": _num(row["p_value"]), "hit_rate": _num(row["hit_rate"])}
    if samples is None or not math.isfinite(row["mean_excess"]):
        return {**out, "checks": {"a": None, "b": None, "c": None}, "mde": None, "verdict": FAIL, "half_before": None, "half_after": None}
    before, after = samples[samples.index < SPLIT], samples[samples.index >= SPLIT]
    sd = float(samples.std(ddof=1)) if len(samples) > 1 else float("nan")
    checks = {
        "a": bool(row["mean_excess"] > 0 and row["p_value"] < ALPHA),
        "b": bool(row["mean_excess"] >= ECON_FLOOR),
        "c": bool(len(before) >= MIN_HALF_EPISODES and len(after) >= MIN_HALF_EPISODES and before.mean() > 0 and after.mean() > 0),
    }
    return {**out, "checks": checks, "mde": _num(mde_mean_excess(sd, len(samples))),
            "half_before": {"n": int(len(before)), "mean": _num(before.mean()) if len(before) else None},
            "half_after": {"n": int(len(after)), "mean": _num(after.mean()) if len(after) else None},
            "verdict": PASS if all(checks.values()) else FAIL}


def _num(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, 4) if math.isfinite(x) else None


def run_primary(levels: pd.DataFrame, source: str) -> dict[str, Any]:
    res = mf.conditional_forward_excess(levels, source, benchmark="MKT", trigger_window=TRIGGER_WINDOW, horizon=HORIZON,
                                        quantile=QUANTILE, min_history=MIN_HISTORY)
    episodes = len(res.attrs.get("episode_dates", [])) if not res.empty else 0
    if res.empty or episodes < MIN_EPISODES_SOURCE:
        return {"verdict": NOT_EVALUABLE, "source_episodes": episodes, "targets": {}, "reason": f"{source} 에피소드 {episodes}건 < {MIN_EPISODES_SOURCE}"}
    samples = res.attrs.get("samples", {})
    targets = {r["ticker"]: target_verdict(r, samples.get(r["ticker"])) for _, r in res.iterrows()}
    passed = [t for t, v in targets.items() if v["verdict"] == PASS]
    mdes = [v["mde"] for v in targets.values() if v["mde"] is not None]
    median_mde = float(np.median(mdes)) if mdes else None
    if passed:
        verdict = PASS
    elif median_mde is not None and median_mde > ECON_FLOOR:
        verdict = UNDERPOWERED
    else:
        verdict = FAIL
    return {"verdict": verdict, "source_episodes": episodes, "n_tests": int(res.attrs.get("n_tests", len(res))),
            "passed": passed, "median_mde": _num(median_mde), "bonferroni_significant": int(res["significant_bonferroni"].sum()),
            "raw_significant": int(res["significant_raw"].sum()), "targets": targets}


def run_sensitivity(levels: pd.DataFrame, source: str) -> list[dict[str, Any]]:
    rows = []
    for name, trig, hor, q in SENSITIVITY:
        r = mf.conditional_forward_excess(levels, source, benchmark="MKT", trigger_window=trig, horizon=hor, quantile=q, min_history=MIN_HISTORY)
        if r.empty:
            rows.append({"spec": name, "episodes": 0, "bonferroni_significant": 0, "raw_significant": 0, "max_mean_excess": None})
            continue
        rows.append({"spec": name, "episodes": len(r.attrs.get("episode_dates", [])), "bonferroni_significant": int(r["significant_bonferroni"].sum()),
                     "raw_significant": int(r["significant_raw"].sum()), "max_mean_excess": _num(r["mean_excess"].max())})
    return rows


def run_etf_report(smoke: bool) -> dict[str, Any]:
    """2008 이후 ETF 34개: 화면과 같은 검정. 이미 본 표본이라 판정에 쓰지 않는다. 실패해도 판정은 영향 없음."""
    if smoke:
        return {"skipped": "smoke"}
    try:
        from datetime import date, timedelta

        start = (date.today() - timedelta(days=mf.LONG_LOOKBACK_DAYS)).isoformat()
        close, _, missing = mf.load_universe(start=start)
        r = mf.conditional_forward_excess(close, "XLK", trigger_window=TRIGGER_WINDOW, horizon=HORIZON, quantile=QUANTILE)
        if r.empty:
            return {"error": "표본 부족"}
        return {"source": "XLK", "episodes": len(r.attrs.get("episode_dates", [])), "n_tests": int(r.attrs.get("n_tests", len(r))),
                "bonferroni_significant": int(r["significant_bonferroni"].sum()), "raw_significant": int(r["significant_raw"].sum()),
                "missing": missing, "note": "이미 본 표본(화면 탐색) — 판정에 쓰지 않음"}
    except Exception as exc:  # noqa: BLE001 — 보고 블록의 실패가 판정을 막지 않는다
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def _atomic_pickle(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump(obj, f)
    tmp.replace(path)


def _load_ckpt(path: Path, fp: dict):
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            blob = pickle.load(f)
        return blob["payload"] if blob.get("fingerprint") == fp else None
    except Exception:  # noqa: BLE001
        return None


def build_result(primary: dict, sens: list, etf: dict, smoke: bool, source: str) -> dict:
    verdicts = {"overall": f"SMOKE_ONLY({primary['verdict']})" if smoke else primary["verdict"]}
    for t, v in primary.get("targets", {}).items():
        verdicts[t] = f"SMOKE_ONLY({v['verdict']})" if smoke else v["verdict"]
    return {"judge_version": RULES_VERSION, "smoke": smoke, "source": source,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "verdicts": verdicts,
            "rule": {"source": SOURCE_REAL, "trigger_window": TRIGGER_WINDOW, "horizon": HORIZON, "quantile": QUANTILE, "min_history": MIN_HISTORY,
                     "n_tests": N_TESTS, "alpha_bonferroni": round(ALPHA, 6), "econ_floor_pp": ECON_FLOOR, "split": str(SPLIT.date()),
                     "min_half_episodes": MIN_HALF_EPISODES, "data": f"{DATA_START}~{DATA_END}"},
            "primary": primary, "sensitivity_report_only": sens, "etf_report_only": etf}


def render(res: dict) -> str:
    p = res["primary"]
    lines = [f"# 시장 자금 이동 v1 ({res['judge_version']})", "",
             f"판정 **{res['verdicts']['overall']}** · 자료 {res['rule']['data']} · {res['source']}", "",
             f"질문: BusEq 가 직전 {TRIGGER_WINDOW}행 수익률 하위 {int(QUANTILE*100)}%(확장 분포)로 빠진 뒤 {HORIZON}행 동안 다른 산업이 시장보다 평소보다 더 벌었나. "
             f"독립 에피소드 {p.get('source_episodes')}건, 검정 {N_TESTS}개, Bonferroni α={res['rule']['alpha_bonferroni']}.", ""]
    if p.get("targets"):
        lines += ["| 대상 | 판정 | 에피소드 | 평균 초과(%p) | t | p | 이긴 비율(%) | 1967 전 평균(n) | 1967 후 평균(n) | MDE(%p) |", "|---|---|---:|---:|---:|---:|---:|---|---|---:|"]
        for t, v in sorted(p["targets"].items(), key=lambda kv: -(kv[1]["mean_excess"] or -99)):
            b, a = v.get("half_before") or {}, v.get("half_after") or {}
            lines.append(f"| {t} | **{v['verdict']}** | {v['episodes']} | {v['mean_excess']} | {v['t_stat']} | {v['p_value']} | {v['hit_rate']} | "
                         f"{b.get('mean')} ({b.get('n')}) | {a.get('mean')} ({a.get('n')}) | {v['mde']} |")
        lines += ["", f"보정 후 유의 {p.get('bonferroni_significant')}개 · 보정 전 유의 {p.get('raw_significant')}개(우연 기대 ≈ {0.05*N_TESTS:.1f}) · 중앙값 MDE {p.get('median_mde')}%p (경제적 하한 {ECON_FLOOR}%p)."]
    else:
        lines.append(p.get("reason", "평가 불가"))
    lines += ["", "통과(PASS_FORWARD_CANDIDATE) = 모두: (a) 평균 > 0 이고 p < 0.05/12, (b) 평균 ≥ 0.30%p, (c) 1967 전·후 각각 10건 이상이고 둘 다 평균 > 0. "
              "FAIL_UNDERPOWERED = PASS 없음 + 중앙값 MDE > 0.30%p(효과가 있어도 못 잡는 표본).", "", "## 보고만 (판정 아님)", "",
              "| 민감도 사양 | 에피소드 | 보정 후 유의 | 보정 전 유의 | 최대 평균 초과(%p) |", "|---|---:|---:|---:|---:|"]
    for s in res["sensitivity_report_only"]:
        lines.append(f"| {s['spec']} | {s['episodes']} | {s['bonferroni_significant']} | {s['raw_significant']} | {s['max_mean_excess']} |")
    etf = res["etf_report_only"]
    lines += ["", f"2008 이후 ETF(이미 본 표본): {json.dumps(etf, ensure_ascii=False)}", "",
              "한계: 산업 총수익이라 ETF 와 직접 비교가 안 되고, BusEq 는 현대적 '기술'과 다르다. 채권·원자재·해외는 이 자료에 없다. 세금·비용 미포함(신호 존재 시험). "
              "PASS 도 전진 원장에 올릴 후보일 뿐 엔진·주문 규칙을 바꾸지 않는다."]
    return "\n".join(lines) + "\n"


def smoke_coverage(res: dict) -> dict[str, bool]:
    p = res["primary"]
    return {"primary_has_targets": bool(p.get("targets")), "episodes_enough": p.get("source_episodes", 0) >= MIN_EPISODES_SOURCE,
            "sensitivity_ran": len(res["sensitivity_report_only"]) == len(SENSITIVITY),
            "halves_computed": any(v.get("half_before") for v in p.get("targets", {}).values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    out, ck = Path(a.out), Path(a.checkpoint)
    out.mkdir(parents=True, exist_ok=True)
    ck.mkdir(parents=True, exist_ok=True)
    fp = {"rules": RULES_VERSION, "smoke": bool(a.smoke)}
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or 0) or None

    def on_term(signum, frame):  # noqa: ARG001
        raise _Stop()

    old = _signal.signal(_signal.SIGTERM, on_term) if hasattr(_signal, "SIGTERM") else None
    try:
        if deadline is not None and time.time() > deadline - 90:
            raise _Stop()
        data = _load_ckpt(ck / "french.pkl", fp)
        if data is None:
            data = lab.synthetic_data() if a.smoke else lab.load_real()
            _atomic_pickle(ck / "french.pkl", {"fingerprint": fp, "payload": data})
        levels, source = build_levels(data, a.smoke)
        primary = run_primary(levels, source)
        sens = run_sensitivity(levels, source)
        etf = run_etf_report(a.smoke)
        result = build_result(primary, sens, etf, a.smoke, data["source"])
        if a.smoke:
            cov = smoke_coverage(result)
            result["smoke_coverage"] = cov
            bad = [k for k, v in cov.items() if not v]
            if bad:
                raise RuntimeError(f"스모크가 다음 상태를 지나지 않음: {bad}")
    except _Stop:
        print("시간 예산 끝 — 체크포인트 저장됨, 다음 회차에 이어서", flush=True)
        return 3
    finally:
        if old is not None:
            _signal.signal(_signal.SIGTERM, old)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(render(result), encoding="utf-8")
    print(json.dumps(result["verdicts"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
