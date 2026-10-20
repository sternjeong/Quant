import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

PATH = Path(__file__).resolve().parents[1]/'research/jobs/sso-policy-factorial-v1/run.py'
spec = importlib.util.spec_from_file_location('sso_policy_test', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def panel():
    idx = pd.bdate_range('2007-01-01',periods=1050)
    rng = np.random.default_rng(19)
    spy = 100*np.cumprod(1+rng.normal(.0005,.01,len(idx)))
    return pd.DataFrame({'SPY':spy,'SSO':100*(spy/100)**2,'BIL':100.},index=idx)


def test_future_and_same_day_prices_do_not_change_signal():
    p=panel()
    a,b=m.signals(p,p)
    d=p.index[700]
    changed=p.copy()
    changed.loc[d:,'SPY']*=2
    x,y=m.signals(changed,changed)
    pd.testing.assert_series_equal(a.loc[:d],x.loc[:d])
    pd.testing.assert_series_equal(b.loc[:d],y.loc[:d])


def test_monthly_budget_bounds_and_weights():
    p=panel()
    state,budget=m.signals(p,p)
    assert budget.between(.05,.30).all()
    flags=m.u.lb_first_month(p.index)
    assert (budget.diff().fillna(0).loc[~flags]==0).all()
    w=m.frames(p,p,p.index[300],p.index[-1])
    for name,frame in w.items():
        assert (frame>=0).all().all()
        assert np.allclose(frame.sum(axis=1),1,atol=1e-7)
    idx=w['FLOOR15'].index
    off=~state.reindex(idx)
    assert (w['FLOOR15'].loc[off,'SSO']==0).all()
    assert (w['FLOOR15'].loc[off,'BIL']==0).all()
    assert np.allclose(w['FLOOR15'].loc[off,'SPY'],1)


def test_incumbent_matches_previous_implementation():
    p=panel()
    idx=p.index[300:]
    state,_=m.signals(p,p)
    lb=m.u.module('sso_test_incumbent','research/jobs/lev-base-v1/run.py')
    asset=pd.DataFrame({'SSO':state.reindex(idx).astype(float),'BIL':1-state.reindex(idx).astype(float)},index=idx)
    expected=lb.SC.sleeve_weights(idx,p.reindex(idx),[
        ('spy',.85,pd.DataFrame({'SPY':1.},index=idx)),('lev',.15,asset)])[0]
    pd.testing.assert_frame_equal(m.frames(p,p,idx[0],idx[-1])['INCUMBENT'],expected)


def test_holm_step_down():
    assert m.holm({'a':.01,'b':.03,'c':.04}) == pytest.approx({'a':.03,'b':.06,'c':.06})


def test_noop_cannot_pass_even_good_account_metrics():
    names=m.NAMES
    row={n:{'irr':.2 if n in m.CANDIDATES else .1} for n in names}
    full={n:{'mdd':-.1,'worst252':-.1} for n in names}
    support={n:{'active_ir':.5} for n in m.CANDIDATES}
    actual=m.assess([row]*3,full,row,support,{n:0 for n in m.CANDIDATES},
                    m.rp.power_report(15,3),{n:[0]*20 for n in m.CANDIDATES},False)
    assert all(v['verdict']=='NOT_EVALUABLE' for v in actual.values())
