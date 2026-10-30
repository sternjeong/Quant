"""현 챔피언과 SPY의 같은 계좌 경로에서 구·신 청산 공식 차이를 잰다."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import rolling_eval as rolling  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JOB_ID = "liquidation-accounting-impact-v1"
DECISION_END = pd.Timestamp("2024-09-30")
_STOP = False


def _on_stop(_sig, _frame):
    global _STOP
    _STOP = True


def _source():
    path = ROOT / "research/jobs/champion-aftertax-v1/run.py"
    spec = importlib.util.spec_from_file_location("champion_aftertax_source_for_impact", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fingerprint(frames: tuple) -> str:
    digest = hashlib.sha256(JOB_ID.encode())
    for path in (Path(__file__), ROOT / "core/tax_fx.py", ROOT / "research/jobs/champion-aftertax-v1/run.py"):
        digest.update(path.read_bytes())
    for frame in frames:
        data = frame.to_frame() if isinstance(frame, pd.Series) else frame
        digest.update(str(tuple(data.columns)).encode())
        digest.update(pd.util.hash_pandas_object(data, index=True).to_numpy().tobytes())
    return digest.hexdigest()


def _atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _legacy_terminal(result: dict, end_year: int) -> float:
    current_realized = next((row["realized_gain_krw"] for row in result["years"] if row["year"] == end_year), 0.0)
    gross_unreal = result["liquidation_sale_gain_krw"] + result["liquidation_trade_fees_krw"]
    old_tax = max(0.0, current_realized + gross_unreal - tx.ANNUAL_DEDUCTION_KRW) * tx.TAX_RATE
    return result["final_krw"] - old_tax


def _measure(weights: pd.DataFrame, close: pd.DataFrame, adj: pd.DataFrame, fx: pd.Series,
             start: pd.Timestamp, end: pd.Timestamp) -> dict:
    cfg = tx.AccountConfig(initial_krw=10_000_000, monthly_contribution_krw=150_000,
                           contribution_policy="underweight_first")
    window = weights.loc[start:end]
    sim = tx.simulate(window, close, adj, fx, cfg)
    old = _legacy_terminal(sim, end.year)
    flows = [(window.index[0], -cfg.initial_krw)]
    flows += [(day, -float(amount)) for day, amount in sim["contributions_krw"].items() if amount > 0]
    legacy_irr = tx.xirr(flows + [(window.index[-1], old)])
    if not all(math.isfinite(float(value)) for value in (
        old, sim["final_after_liquidation_krw"], sim["unpaid_prior_year_tax_krw"],
        sim["liquidation_trade_fees_krw"], sim["liquidation_fx_cost_krw"],
    )):
        raise ValueError(f"{start.date()}~{end.date()} 청산 금액 또는 비용이 유한하지 않습니다")
    return {"old_terminal_krw": old, "corrected_terminal_krw": sim["final_after_liquidation_krw"],
            "old_irr": _finite_or_none(legacy_irr),
            "corrected_irr": _finite_or_none(sim["irr_after_liquidation"]),
            "unpaid_prior_year_tax_krw": sim["unpaid_prior_year_tax_krw"],
            "exit_fee_krw": sim["liquidation_trade_fees_krw"],
            "exit_fx_krw": sim["liquidation_fx_cost_krw"]}


def _finite_or_none(value: float) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def _finite_median(values: list[float | None]) -> float | None:
    good = [v for v in values if v is not None and math.isfinite(v)]
    return float(np.median(good)) if good else None


def _gap(a: float | None, b: float | None) -> float | None:
    return a - b if a is not None and b is not None else None


def _fmt_pct(value: float | None) -> str:
    return f"{value:.3%}" if value is not None else "계산 불가"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    out, checkpoint = Path(args.out), Path(args.checkpoint) / "progress.json"
    out.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, _on_stop)

    source = _source()
    champ, _core, close, adj, fx, _log, _bt = source._smoke() if args.smoke else source._real()
    if not args.smoke:
        champ, close, adj, fx = (frame.loc[:DECISION_END] for frame in (champ, close, adj, fx))
    spy = tx.buy_and_hold_weights(champ.index)
    horizon, limit = (2, pd.Timestamp("2013-12-31")) if args.smoke else (5, DECISION_END)
    windows = [(start, end) for start, end in rolling.rolling_windows(champ.index, horizon, step=1,
                                                                        first_start="2010-01-01") if end <= limit]
    if not windows:
        raise ValueError("측정 가능한 구간이 없습니다")
    fingerprint = _fingerprint((champ, close, adj, fx))
    rows = []
    if checkpoint.is_file():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if saved.get("fingerprint") != fingerprint or saved.get("smoke") != args.smoke:
            raise ValueError("체크포인트 입력 지문 불일치 — 새 revision 또는 --fresh 필요")
        rows = saved["rows"]
    deadline = float(os.environ.get("RESEARCH_JOB_DEADLINE_EPOCH") or "inf")
    for index in range(len(rows), len(windows)):
        if _STOP or time.time() + 45 >= deadline:
            _atomic_json(checkpoint, {"fingerprint": fingerprint, "smoke": args.smoke, "rows": rows})
            return 3
        start, end = windows[index]
        a = _measure(champ, close, adj, fx, start, end)
        b = _measure(spy, close, adj, fx, start, end)
        rows.append({"start": str(start.date()), "end": str(end.date()), "champion": a, "spy": b,
                     "old_gap_irr": _gap(a["old_irr"], b["old_irr"]),
                     "corrected_gap_irr": _gap(a["corrected_irr"], b["corrected_irr"])})
        _atomic_json(checkpoint, {"fingerprint": fingerprint, "smoke": args.smoke, "rows": rows})

    old_gaps = [r["old_gap_irr"] for r in rows]
    new_gaps = [r["corrected_gap_irr"] for r in rows]
    paired = [(a, b) for a, b in zip(old_gaps, new_gaps) if a is not None and b is not None]
    changed = sum((a > 0) != (b > 0) for a, b in paired)
    summary = {"windows": len(rows), "old_gap_irr_median": _finite_median(old_gaps),
               "corrected_gap_irr_median": _finite_median(new_gaps), "gap_sign_changed_windows": changed,
               "comparable_irr_windows": len(paired),
               "irr_unavailable_windows": len(rows) - len(paired),
               "champion_terminal_delta_median_krw": _finite_median([r["champion"]["corrected_terminal_krw"] - r["champion"]["old_terminal_krw"] for r in rows]),
               "spy_terminal_delta_median_krw": _finite_median([r["spy"]["corrected_terminal_krw"] - r["spy"]["old_terminal_krw"] for r in rows])}
    result = {"id": JOB_ID, "smoke": args.smoke, "generated_at": datetime.now(timezone.utc).isoformat(),
              "verdicts": {"accounting_impact": "SMOKE_ONLY(MEASUREMENT_ONLY)" if args.smoke else "MEASUREMENT_ONLY"},
              "input_fingerprint": fingerprint, "rules": {"horizon_years": horizon, "step_months": 1,
              "decision_end": str(limit.date()), "account": "10m KRW + 150k/month, default tax_fx fees/tax"},
              "summary": summary, "rows": rows}
    _atomic_json(out / "results.json", result)
    report = ["# 청산 회계 수정 영향 측정" + (" — 합성 스모크" if args.smoke else ""), "",
              "판정: MEASUREMENT_ONLY. 같은 시뮬레이션에서 구·신 최종 청산 공식만 비교했다.", "",
              f"측정 창 {len(rows)}개; 5년 월별 시작(스모크만 2년), 종료일 상한 {limit.date()}.",
              f"현 챔피언−SPY IRR 중앙 차이: 과거 공식 {_fmt_pct(summary['old_gap_irr_median'])}, 수정 공식 {_fmt_pct(summary['corrected_gap_irr_median'])}.",
              f"IRR 비교 가능 {len(paired)}개·계산 불가 {len(rows) - len(paired)}개(수익률 해가 계산기 범위를 벗어나거나 현금흐름이 부적격).",
              f"비교 가능 창 중 우위 부호가 바뀐 창 {changed}개. 챔피언 청산액 수정 중앙 {summary['champion_terminal_delta_median_krw']:,.0f}원, SPY {summary['spy_terminal_delta_median_krw']:,.0f}원.", "",
              "창별 수치와 입력 지문은 results.json. 기존 연구의 원 판정은 변경하지 않았다.",
              "현재 S&P500 풀 생존편향과 원 연구 실행 당시 입력 차이 가능성이 있다. 독립 표본외·실계좌 세금 검증이 아니다."]
    (out / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
