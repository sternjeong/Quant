"""청산 회계 영향 연구의 구 공식 재현과 새 ID 계약."""

import importlib.util
import math
from pathlib import Path

import pandas as pd
import pytest

from core import tax_fx as tx
from core.research_jobs import Config, load_job_definitions

ROOT = Path(__file__).resolve().parents[1]


def _job():
    spec = importlib.util.spec_from_file_location(
        "liquidation_accounting_impact_v1", ROOT / "research/jobs/liquidation-accounting-impact-v1/run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_job_is_registered_and_old_formula_omits_prior_year_liability():
    valid, invalid = load_job_definitions(Config.for_root(ROOT))
    assert "liquidation-accounting-impact-v1" in valid, invalid.get("liquidation-accounting-impact-v1")
    idx = pd.DatetimeIndex(["2025-01-02", "2025-12-31", "2026-01-02"])
    close = pd.DataFrame({"A": [100.0, 200.0, 200.0]}, index=idx)
    weights = pd.DataFrame({"A": [1.0, 0.0, 0.0]}, index=idx)
    result = tx.simulate(weights, close, close, pd.Series(1000.0, index=idx),
                         tx.AccountConfig(initial_krw=10_000_000, fee_rate=0, fx_spread=0))
    old = _job()._legacy_terminal(result, 2026)
    assert old == pytest.approx(result["final_krw"])
    assert old - result["final_after_liquidation_krw"] == pytest.approx(1_650_000)


def test_undefined_irr_is_explicit_and_does_not_break_checkpoint(tmp_path):
    job = _job()
    assert job._finite_or_none(math.nan) is None
    assert job._gap(None, 0.1) is None
    assert job._finite_median([None, 0.1, 0.3]) == pytest.approx(0.2)
    path = tmp_path / "progress.json"
    job._atomic_json(path, {"rows": [{"old_gap_irr": job._gap(None, 0.1)}]})
    assert '"old_gap_irr": null' in path.read_text()
