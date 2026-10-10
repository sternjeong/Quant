import math

from core import research_power as rp


def test_mde_matches_hand_calculation():
    assert math.isclose(rp.mde_ir(16.7, 1), 0.40, abs_tol=0.01)
    assert math.isclose(rp.mde_ir(16.7, 13), 0.82, abs_tol=0.01)
    assert rp.mde_ir(95, 13) < rp.mde_ir(16.7, 13)
    assert rp.mde_ir(0, 1) == float("inf")


def test_power_is_monotone_and_low_for_realistic_effects():
    assert rp.power(0.3, 16.7, 13) < 0.05
    assert rp.power(0.3, 95, 1) > rp.power(0.3, 16.7, 1)
    assert rp.power(2.0, 16.7, 1) > 0.99


def test_power_report_and_classification():
    rep = rp.power_report(16.7, 13)
    assert rep["n_trials"] == 13 and "0.30" in rep["power_at"]
    assert "통과에 필요한 연 IR" in rp.power_line(rep)
    assert rp.classify_fail(0.3, rep) == "FAIL_UNDERPOWERED"
    assert rp.classify_fail(1.0, rep) == "FAIL"
    assert rp.classify_fail(-0.1, rep) == "FAIL"
    assert rp.classify_fail(None, rep) == "FAIL"


def test_noop_guard():
    assert rp.noop_guard([0.0, 0.0, 0.0]) is not None
    assert rp.noop_guard([]) is not None
    assert rp.noop_guard([0.0, 1e-4]) is None
