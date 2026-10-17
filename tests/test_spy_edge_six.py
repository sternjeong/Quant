import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location('spy_edge_six', Path(__file__).resolve().parents[1] / 'research/jobs/spy-edge-six-v1/run.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

@pytest.fixture(scope='module')
def data():
    return m.load_data(True)

@pytest.mark.parametrize('family,param', [(f,v) for f,vs in m.CELLS.items() for v in vs])
def test_future_prices_do_not_change_past_weights(data, family, param):
    adj = data['adj'].iloc[:900].copy()
    cut = adj.index[650]
    base = m.make_weights(adj, family, param)
    adj.loc[cut:] *= np.linspace(1, 5, len(adj.loc[cut:]))[:,None]
    changed = m.make_weights(adj, family, param)
    pd.testing.assert_frame_equal(base.loc[:cut], changed.loc[:cut])
    assert (base.sum(axis=1) <= 1 + 1e-12).all()
    assert (base >= 0).all().all()


def test_gap_is_not_constant_rank_gap(data):
    w = m.make_weights(data['adj'], 'gap', .10)
    counts = (w[m.SECTORS] > 0).sum(axis=1)
    assert {1, 2}.issubset(set(counts))


def test_unavailable_prices_rejected(data):
    d = {**data, 'adj': data['adj'].copy()}
    days = d['adj'].loc['2014-01-02':].index[:3]
    d['adj'].loc[days, 'XLB'] = np.nan
    with pytest.raises(ValueError, match='isolated/nonpositive'):
        m.validate_data(d)


def test_common_inception_and_single_shared_gap_are_handled(data):
    d = {**data, 'close': data['close'].copy(), 'adj': data['adj'].copy()}
    before = d['adj'].index[0]
    for ticker in ('XLB', 'XLE', 'XLF'):
        d['adj'].loc[before, ticker] = np.nan
        d['close'].loc[before, ticker] = np.nan
    # A synchronized provider quote outage removes that date for all assets.
    outage = d['adj'].index[400]
    for ticker in ('XLB', 'XLE', 'XLF'):
        d['adj'].loc[outage, ticker] = np.nan
        d['close'].loc[outage, ticker] = np.nan
    cov = m.validate_data(d)
    assert cov['common_start'] == str(d['adj'].index[0].date())
    assert cov['incomplete_dates_dropped'] == 1
    assert outage not in d['adj'].index and outage not in d['close'].index


def test_same_candidates_are_not_evaluable():
    r = pd.Series([0.01, -.02, .03])
    x = {'returns': r, 'metrics': {}}
    assert m.decide(x, x, x, [], (0,0), {})['verdict'] == 'NOT_EVALUABLE'


def test_bootstrap_direction():
    assert m.bootstrap_p(np.full(500, .001), 100) < .02
    assert m.bootstrap_p(np.full(500, -.001), 100) == 1.
