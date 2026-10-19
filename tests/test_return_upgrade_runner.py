"""Tests for the return-upgrade registration and the account trade restriction."""
from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from core import tax_fx as tx
from research.return_upgrade import runner as r


def test_six_registered_jobs_share_preregistered_ids():
    for job_id in r.IDS:
        p = Path('research/jobs') / job_id
        meta = json.loads((p / 'job.json').read_text())
        assert meta['id'] == job_id
        assert meta['entrypoint'] == f'research/jobs/{job_id}/run.py'
        assert {'results.json', 'REPORT.md'} <= set(meta['outputs'])


def test_restricted_rebalance_leaves_unselected_stock_untouched():
    idx = pd.bdate_range('2022-01-03', periods=8)
    prices = pd.DataFrame({'A':100.0, 'B':100.0}, index=idx)
    prices.loc[idx[4]:,'B'] = 200.0
    weights = pd.DataFrame({'A':.5,'B':.5}, index=idx)
    weights.loc[idx[5]:] = [.8,.2]
    allowed = pd.DataFrame(False,index=idx,columns=weights.columns)
    allowed.iloc[0] = True
    allowed.loc[idx[5],'A'] = True
    cfg = tx.AccountConfig(initial_krw=1_000_000,fee_rate=.001,fx_spread=0,
                           apply_tax=False,apply_dividend_tax=False)
    fx = pd.Series(1000.0,index=idx)
    baseline = tx.simulate(weights,prices,prices,fx,cfg)
    local = tx.simulate(weights,prices,prices,fx,cfg,trade_allowed=allowed)
    assert local['totals']['fees_krw'] < baseline['totals']['fees_krw']
    assert local['terminal_after_liquidation_krw'] > baseline['terminal_after_liquidation_krw']
    with pytest.raises(ValueError):
        tx.simulate(weights,prices,prices,fx,cfg,trade_allowed=allowed.drop(columns='B'))


def test_no_trade_restriction_matches_all_allowed():
    idx = pd.bdate_range('2022-01-03',periods=12)
    prices = pd.DataFrame({'A':100+np.arange(12),'B':100+np.arange(12)[::-1]},index=idx)
    w = pd.DataFrame({'A':.5,'B':.5},index=idx)
    w.loc[idx[6]:] = [.7,.3]
    cfg=tx.AccountConfig(initial_krw=1_000_000,monthly_contribution_krw=100_000)
    fx=pd.Series(1000.0,index=idx)
    old=tx.simulate(w,prices,prices,fx,cfg)
    new=tx.simulate(w,prices,prices,fx,cfg,trade_allowed=pd.DataFrame(True,index=idx,columns=w.columns))
    assert new['terminal_after_liquidation_krw'] == pytest.approx(old['terminal_after_liquidation_krw'])
