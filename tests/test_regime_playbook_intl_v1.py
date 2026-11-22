"""regime-playbook-intl-v1 — 얼린 규칙이 v3 와 같은지, 지역 평가·합동 검정, 스모크 전 경로(네트워크 없음)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("regime_playbook_intl_v1", ROOT / "research" / "jobs" / "regime-playbook-intl-v1" / "run.py")
pi = importlib.util.module_from_spec(spec)
sys.modules["regime_playbook_intl_v1"] = pi
spec.loader.exec_module(pi)


def test_frozen_rules_match_v3():
    v3 = pi._v3()
    for name, cfg in pi.VARIANTS.items():
        assert cfg["picks"] == v3.picks_for(v3.VARIANTS[name])
        assert sum(cfg["static"].values()) == pytest.approx(1.0)


def test_region_eval_and_pooled_test():
    regions = {k: pi.eval_region(pi.synthetic_region(5 + i)) for i, k in enumerate(pi.JUDGED_REGIONS)}
    t, p, n = pi.pooled_test(regions, "Q_CRISIS_CASH")
    assert n > 300 and p is not None and 0 <= p <= 1
    r = next(iter(regions.values()))
    assert r["start"] >= pi.EVAL_START and set(r["variants"]) == set(pi.VARIANTS)


def test_smoke_end_to_end(tmp_path):
    assert pi.main(["--smoke", "--out", str(tmp_path / "o"), "--checkpoint", str(tmp_path / "c")]) == 0
    res = json.loads((tmp_path / "o" / "results.json").read_text(encoding="utf-8"))
    assert set(res["verdicts"]) == set(pi.VARIANTS) and set(res["judged"]) == set(pi.JUDGED_REGIONS)
    assert all(v in {"HOLDS_ABROAD", "FAIL"} for v in res["verdicts"].values())
