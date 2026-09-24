"""core/tuning_ledger.py (ENG-04) 순수 함수 테스트 + tune_strategy_for_group 장부 통합."""

import copy
import math
from types import SimpleNamespace

import pytest

import core.strategy_tuning as st_mod
from core import tuning_ledger as tl


def test_ledger_counts_and_dict():
    led = tl.SearchLedger()
    led.record_search(10, 6)
    led.record_search(4, 4)
    led.record_retry()
    led.record_test_view(3)
    d = led.to_dict()
    assert d["candidates_generated"] == 14 and d["rejected"] == 4 and d["scored"] == 10
    assert d["backbones_searched"] == 2 and d["structural_retries"] == 1
    assert d["test_views"] == 3 and d["n_trials"] == 10


def _pts(pairs):
    return [{"rank": r, "train_score": 0, "test_score": t} for r, t in pairs]


def test_rank_instability_stable_when_test_follows_train():
    r = tl.compute_rank_instability(_pts([(1, 5.0), (2, 3.0), (3, 1.0), (4, -2.0)]))
    assert r["spearman"] == 1.0 and r["instability"] == 0.0
    assert r["top1_changed"] is False and r["is_unstable"] is False


def test_rank_instability_separate_from_top1_change():
    # 1위는 유지되지만 나머지 순서는 완전히 뒤집힘 -> top1 안 바뀌어도 불안정 신호 (is_overfit과 분리)
    r = tl.compute_rank_instability(_pts([(1, 9.0), (2, 1.0), (3, 2.0), (4, 3.0), (5, 4.0)]))
    assert r["top1_changed"] is False
    assert r["spearman"] < 0.3 and r["is_unstable"] is True


def test_rank_instability_top1_changed_but_ranking_mostly_stable():
    r = tl.compute_rank_instability(_pts([(1, 4.9), (2, 5.0), (3, 3.0), (4, 2.0), (5, 1.0)]))
    assert r["top1_changed"] is True
    assert r["spearman"] > 0.8 and r["is_unstable"] is False


def test_rank_instability_insufficient_points():
    r = tl.compute_rank_instability(_pts([(1, 1.0), (2, None), (3, 2.0)]))
    assert r["n_valid"] == 2 and r["spearman"] is None and r["is_unstable"] is None


def test_rank_instability_handles_ties_without_crash():
    r = tl.compute_rank_instability(_pts([(1, 1.0), (2, 1.0), (3, 1.0)]))
    assert r["spearman"] is None


def _cfg(a, b):
    return {"entry": {"period": a, "level": b}, "name": "x"}


def test_neighbor_stability_plateau_is_stable():
    trail = [
        {"config": _cfg(14, 30), "score": 2.0},
        {"config": _cfg(12, 30), "score": 1.9},
        {"config": _cfg(16, 30), "score": 1.8},
        {"config": _cfg(20, 40), "score": 0.1},  # 두 파라미터 달라 이웃 아님
    ]
    r = tl.check_neighbor_stability(trail)
    assert r["n_neighbors"] == 2 and r["is_stable"] is True and r["retention"] > 0.9


def test_neighbor_stability_sharp_peak_is_unstable():
    trail = [
        {"config": _cfg(14, 30), "score": 3.0},
        {"config": _cfg(12, 30), "score": 0.3},
        {"config": _cfg(14, 25), "score": 0.2},
    ]
    r = tl.check_neighbor_stability(trail)
    assert r["is_stable"] is False


def test_neighbor_stability_undeterminable_and_empty():
    assert tl.check_neighbor_stability([])["is_stable"] is None
    r = tl.check_neighbor_stability([{"config": _cfg(14, 30), "score": 1.0}, {"config": _cfg(12, 30), "score": 1.0}])
    assert r["n_neighbors"] == 1 and r["is_stable"] is None


def test_neighbor_stability_nonpositive_best():
    trail = [
        {"config": _cfg(14, 30), "score": -0.5},
        {"config": _cfg(12, 30), "score": -1.5},
        {"config": _cfg(16, 30), "score": -1.0},
    ]
    r = tl.check_neighbor_stability(trail)
    assert r["retention"] is None and r["is_stable"] is False


def test_expected_max_sharpe_grows_with_trials():
    assert tl.expected_max_sharpe(1, 0.01) == 0.0
    assert tl.expected_max_sharpe(100, 0.01) > tl.expected_max_sharpe(10, 0.01) > 0


def test_dsr_penalizes_more_trials():
    few = tl.deflated_sharpe_ratio(0.08, 5, 0.0004, 500)
    many = tl.deflated_sharpe_ratio(0.08, 500, 0.0004, 500)
    assert many["dsr"] < few["dsr"]
    assert 0 <= many["dsr"] <= 1


def test_dsr_single_trial_reduces_to_probabilistic_sharpe():
    r = tl.deflated_sharpe_ratio(0.1, 1, 0.0, 400)
    assert r["dsr"] > 0.95 and r["is_significant"] is True


def test_dsr_invalid_inputs():
    assert tl.deflated_sharpe_ratio(0.1, 10, 0.01, 1)["dsr"] is None


def test_deflate_trail_sharpe_needs_two():
    assert tl.deflate_trail_sharpe([{"mean_sharpe": 1.0}], 1, 500)["dsr"] is None
    r = tl.deflate_trail_sharpe([{"mean_sharpe": 1.5}, {"mean_sharpe": 0.5}, {"mean_sharpe": 0.4}], 30, 750)
    assert r["dsr"] is not None and r["n_trials"] == 30


def test_overfitting_diagnostics_wraps_curve_without_changing_it():
    curve = {"points": _pts([(3, 1.0), (2, 2.0), (1, 3.0)]), "is_overfit": False}
    before = copy.deepcopy(curve)
    d = st_mod.compute_overfitting_diagnostics(curve)
    assert curve == before
    assert d["top1_changed"] is False and d["rank_instability"]["spearman"] == 1.0


def test_tune_strategy_for_group_adds_ledger_fields(monkeypatch):
    base = {"entry": {"period": 14}}
    trail = [
        {"config": {"entry": {"period": 14}}, "score": 2.0, "mean_sharpe": 2.0},
        {"config": {"entry": {"period": 12}}, "score": 1.5, "mean_sharpe": 1.5},
        {"config": {"entry": {"period": 16}}, "score": 1.4, "mean_sharpe": 1.4},
    ]
    monkeypatch.setattr(st_mod, "build_param_grid", lambda cfg, style, intensity: [{}] * 5)
    monkeypatch.setattr(st_mod, "_select_best_group_config_walkforward",
                        lambda t, c, f, m=None: (trail[0]["config"], copy.deepcopy(trail)))
    monkeypatch.setattr(st_mod, "_split_into_folds", lambda *a, **k: [("2020-01-01", "2020-06-01")])
    metrics = {"cumulative_return": 20.0, "cagr": 20.0, "trade_count": 10, "sharpe": 1.0}
    comp = {"strategy": SimpleNamespace(metrics=metrics),
            "buy_and_hold_ticker": SimpleNamespace(metrics={"cumulative_return": 5.0, "cagr": 5.0}),
            "buy_and_hold_benchmark": SimpleNamespace(metrics={"cumulative_return": 5.0, "cagr": 5.0})}
    monkeypatch.setattr(st_mod, "compare_with_benchmarks", lambda *a, **k: comp)
    monkeypatch.setattr(st_mod, "run_backtest", lambda *a, **k: SimpleNamespace(metrics=metrics))
    monkeypatch.setattr(st_mod, "diagnose_strategy_health", lambda cfg: [])
    monkeypatch.setattr(st_mod, "_compute_tuning_significance", lambda *a, **k: {})

    res = st_mod.tune_strategy_for_group(["AAA"], base, "성장주", "2015-01-01", "2021-12-31")
    assert res["search_ledger"]["candidates_generated"] == 5
    assert res["search_ledger"]["scored"] == 3 and res["search_ledger"]["rejected"] == 2
    assert res["search_ledger"]["test_views"] == 1 and res["search_ledger"]["structural_retries"] == 0
    assert res["neighbor_stability"]["n_neighbors"] == 2
    assert res["multiple_testing"]["n_trials"] == 3
    # 기존 필드 유지
    assert "tuning_trail" in res and "group_config" in res
