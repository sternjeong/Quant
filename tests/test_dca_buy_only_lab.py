"""dca-dip-deploy-v1/lab.py 의 팔지 않는 적립 계좌 산수 확인(손으로 계산한 값과 비교)."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_dca_lab_test", ROOT / "research/jobs/dca-dip-deploy-v1/lab.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


def test_buy_now_vs_wait_by_hand():
    px = np.array([[10.0], [20.0], [40.0], [40.0]])
    cg = np.array([1.0, 1.0, 1.1, 1.1])           # 현금 이자 10% (2행에서)
    rows = np.array([0, 1])
    amounts = np.array([1300.0, 1300.0])          # 각 1달러
    fee = 0.0
    now = L.simulate_buy_only(px, cg, rows, amounts, rows.copy(), np.zeros(2, dtype=int), 3, 0, fee=fee)
    # 0행에 1달러 → 0.1 단위, 1행 1달러 → 0.05 단위, 끝 40 → 6 달러 = 7,800 원
    assert abs(now["terminal_pre"] - 7800.0) < 1e-6
    wait = L.simulate_buy_only(px, cg, rows, amounts, np.array([2, 9]), np.zeros(2, dtype=int), 3, 0, fee=fee)
    # 첫 돈: 2행까지 현금 1.1배 → 1.1 달러로 40 에 → 끝 1.1 달러 = 1,430 원. 둘째 돈은 끝까지 현금 1300×1.1/1.0 = 1,430 원
    assert abs(wait["terminal_pre"] - 2860.0) < 1e-6
    assert abs(wait["invested_share"] - 0.5) < 1e-12
    assert wait["mdd"] <= 0.0 and now["mdd"] <= 0.0


def test_liquidation_tax_uses_allowance():
    assert L.liquidation_value(10_000_000, 9_000_000) == 10_000_000
    assert abs(L.liquidation_value(20_000_000, 10_000_000) - (20_000_000 - 0.22 * 7_500_000)) < 1e-6


def test_next_true_row_and_contribution_rows():
    assert list(L.next_true_row(np.array([False, True, False, False, True]))) == [1, 1, 4, 4, 4]
    assert list(L.next_true_row(np.array([False, False]))) == [2, 2]
    days = pd.bdate_range("2020-01-01", "2020-03-31")
    rows = L.contribution_rows(days, days[0], days[-1])
    assert [str(days[r].date()) for r in rows] == ["2020-01-01", "2020-02-03", "2020-03-02"]
