"""Frozen 2x2 ETF policy experiment; real calculations only through the VM runner."""
from __future__ import annotations
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import pickle
import signal
import sys
import time
import numpy as np
import pandas as pd
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research.return_upgrade import runner as u
from core import research_power as rp, rolling_eval as re_, tax_fx as tx

ID = 'sso-policy-factorial-v1'
VERSION = '2026-10-20/1'
CANDIDATES = ('FLOOR15', 'VOL30', 'VOL_FLOOR')
NAMES = ('SPY', 'INCUMBENT', 'MONTHLY15') + CANDIDATES


def signals(close, adj):
    lb = u.module('sso_policy_lev', 'research/jobs/lev-base-v1/run.py')
    state = lb.buffered_state(close['SPY'])
    vol = adj['SPY'].pct_change(fill_method=None).rolling(63, min_periods=63).std().shift(1)*np.sqrt(252)
    # Inverse variance, capped; never fill with future observations.
    budget = (.15*(.15/vol)**2).clip(.05, .30).fillna(.15)
    first = u.lb_first_month(close.index)
    budget = budget.where(first).ffill()
    return state, budget


def frames(close, adj, start, end):
    state, budget = signals(close, adj)
    idx = close.loc[start:end].index
    state, budget = state.reindex(idx), budget.reindex(idx)
    lb = u.module('sso_policy_frames', 'research/jobs/lev-base-v1/run.py')
    asset = pd.DataFrame({'SSO':state.astype(float), 'BIL':1-state.astype(float)}, index=idx)
    result = {'SPY':tx.buy_and_hold_weights(idx, 'SPY')}
    result['INCUMBENT'] = lb.SC.sleeve_weights(idx, adj.reindex(idx), [
        ('spy', .85, pd.DataFrame({'SPY':1.0}, index=idx)), ('lev', .15, asset)])[0]
    for name in ('MONTHLY15',) + CANDIDATES:
        level = budget if name in ('VOL30', 'VOL_FLOOR') else pd.Series(.15, index=idx)
        sso = level.where(state, 0.)
        bil = pd.Series(0., index=idx) if name in ('FLOOR15', 'VOL_FLOOR') else pd.Series(.15, index=idx).where(~state, 0.)
        target = pd.DataFrame({'SPY':1-sso-bil, 'SSO':sso, 'BIL':bil}, index=idx)
        target.attrs['marks'] = pd.Series(u.lb_first_month(idx), index=idx)
        result[name] = lb.SC.sleeve_weights(idx, adj.reindex(idx), [('portfolio',1.,target)])[0]
    return result


def holm(pvals):
    order = sorted(pvals, key=pvals.get)
    out, last = {}, 0.
    for i, name in enumerate(order):
        last = max(last, min(1., (len(order)-i)*pvals[name]))
        out[name] = last
    return out


def assess(rows, full, stress, support, adjusted, power, active, smoke):
    out = {}
    for name in CANDIDATES:
        gaps = np.array([r[name]['irr']-r['SPY']['irr'] for r in rows])
        old = np.array([r[name]['irr']-r['INCUMBENT']['irr'] for r in rows])
        monthly = np.array([r[name]['irr']-r['MONTHLY15']['irr'] for r in rows])
        checks = {
            'win70': bool(np.mean(gaps>0)>=.70), 'median_spy_plus1pp': bool(np.median(gaps)>=.01),
            'p10_ge_minus1_5pp': bool(np.percentile(gaps,10)>=-.015),
            'median_incumbent_plus0_3pp': bool(np.median(old)>=.003),
            'median_monthly_control_positive': bool(np.median(monthly)>0),
            'mdd_within5pp': full[name]['mdd']>=full['SPY']['mdd']-.05,
            'mdd_ge_minus40pct': full[name]['mdd']>=-.40,
            'worst252_within5pp': full[name]['worst252']>=full['SPY']['worst252']-.05,
            'stress_beats_both': stress[name]['irr']>max(stress['SPY']['irr'],stress['INCUMBENT']['irr']),
            'holm_p_le_0_10': adjusted[name]<=.10,
        }
        verdict = ('SMOKE_ONLY' if smoke else 'NOT_EVALUABLE' if rp.noop_guard(active[name]) else
                   'PASS_FORWARD_CANDIDATE' if all(checks.values()) else
                   rp.classify_fail(support[name]['active_ir'], power))
        out[name] = {'verdict':verdict, 'checks':checks, 'win_share':float(np.mean(gaps>0)),
                     'median_spy_gap':float(np.median(gaps)), 'p10_spy_gap':float(np.percentile(gaps,10)),
                     'median_incumbent_gap':float(np.median(old)), 'median_monthly_gap':float(np.median(monthly)),
                     'statistical_support_vs_incumbent':support[name], 'holm_p':adjusted[name]}
    return out


def run(out, checkpoint, smoke=False):
    # Reuse only actual ETF acquisition and synthetic smoke generation, not legacy verdicts.
    if smoke:
        panels = u.make_prep(u.IDS[1], True)['panels']
        # make_prep retains a long synthetic warm-up panel.
        close, adj, fx = panels['close'], panels['adj'], panels['fx']
    else:
        close, adj = u.real_sso_panel()
        # Preserve SPY history before BIL inception for the crisis signal warm-up.
        history = u.md.get_multiple_price_history(['SPY'], start='2005-01-01', end=None, interval='1d')['SPY'].copy()
        history.index = pd.DatetimeIndex(history.index).tz_localize(None).normalize()
        extended = history.index.union(close.index).sort_values()
        close, adj = close.reindex(extended), adj.reindex(extended)
        close['SPY'] = close['SPY'].combine_first(history['Close'])
        adj['SPY'] = adj['SPY'].combine_first(history['Adj Close'])
        fx = tx.usdkrw_series()
    cols = ['SPY','SSO','BIL']
    close, adj = close[cols].loc[:u.DECISION_END], adj[cols].loc[:u.DECISION_END]
    fx = fx.reindex(close.index).ffill(limit=3)
    idx = close.loc['2010-01-01':].index
    for panel in (close.loc[idx], adj.loc[idx]):
        if not np.isfinite(panel.to_numpy()).all() or (panel<=0).any().any():
            raise ValueError('ETF quote missing/nonpositive')
    if not np.isfinite(fx.loc[idx]).all() or (fx.loc[idx]<=0).any():
        raise ValueError('FX missing/nonpositive')
    windows = re_.rolling_windows(idx, 2 if smoke else 5, step='Q' if smoke else 'M')
    if smoke:
        windows = windows[:3]
    if not windows:
        raise ValueError('insufficient history')
    # Legacy incumbent carries its sleeve drift across 5-year window starts.
    # Build once on the full decision calendar, then slice each account exactly
    # as the previous sso-contrib-confirm-v1 job did.
    all_weights = frames(close,adj,idx[0],idx[-1])
    # Power is frozen before simulations. Historical data have already been explored.
    power = rp.power_report((idx[-1]-idx[0]).days/365.25, len(CANDIDATES))
    digest = hashlib.sha256(f'{VERSION}|{smoke}|{windows}'.encode())
    for x in (close, adj, fx):
        digest.update(pd.util.hash_pandas_object(x,index=True).to_numpy().tobytes())
    fp = digest.hexdigest()
    checkpoint.mkdir(parents=True,exist_ok=True)
    cp = checkpoint/'accounts.pkl'
    saved = pickle.loads(cp.read_bytes()) if cp.exists() else {}
    cache = saved.get('accounts',{}) if saved.get('fingerprint')==fp else {}
    limit = float(os.environ.get('RESEARCH_JOB_DEADLINE_EPOCH') or time.time()+10800)-60

    def account(a,b,cost=0):
        key = f'{a}|{b}|{cost}'
        if key in cache:
            return cache[key]
        if time.time()>limit:
            raise u.StopRequested()
        w = ({n:frame.loc[a:b] for n,frame in all_weights.items()}
             if a >= idx[0] else frames(close,adj,a,b))
        cfg = replace(u.CFG,fee_rate=u.CFG.fee_rate+cost)
        result = {}
        for name in NAMES:
            s = tx.simulate(w[name],close,adj,fx,cfg)
            result[name] = {'stats':u.ret_stats(s),'twr_index':s['twr_index']}
        cache[key] = result
        u.atomic(cp,{'fingerprint':fp,'accounts':cache})
        return result

    rows = []
    for a,b in windows:
        result = account(a,b)
        rows.append({'start':str(a.date()),'end':str(b.date()), **{n:r['stats'] for n,r in result.items()}})
    a,b = idx[0],idx[-1]
    full_sims = account(a,b)
    full = {n:r['stats'] for n,r in full_sims.items()}
    stress = {n:r['stats'] for n,r in account(a,b,.0025).items()}
    support = {n:u.active_bootstrap(full_sims[n],full_sims['INCUMBENT']) for n in CANDIDATES}
    for val in support.values():
        val['comparison'] = 'candidate minus INCUMBENT daily after-cost TWR; not IRR significance'
    adjusted = holm({n:support[n]['one_sided_p'] for n in CANDIDATES})
    returns = {n:full_sims[n]['twr_index'].pct_change().fillna(0) for n in NAMES}
    active = {n:returns[n]-returns['INCUMBENT'] for n in CANDIDATES}
    verdicts = assess(rows,full,stress,support,adjusted,power,active,smoke)
    diagnostics = {}
    for label,start,end in [('crisis','2007-06-01','2009-12-31'),('early','2010-01-01','2016-12-31'),('late','2017-01-01','2024-09-30')]:
        di = close.loc[start:end].index
        if len(di)>252 and fx.loc[di].notna().all():
            diagnostics[label] = {n:r['stats'] for n,r in account(di[0],di[-1]).items()}
    interaction = returns['VOL_FLOOR']-returns['VOL30']-returns['FLOOR15']+returns['MONTHLY15']
    result = {'id':ID,'version':VERSION,'smoke':smoke,'verdicts':{n:v['verdict'] for n,v in verdicts.items()},
              'power':power,'candidates':verdicts,'full_account':full,'cost_stress':stress,
              'diagnostics':diagnostics,'rolling_windows':rows,'input_fingerprint':fp,
              'factorial_interaction_daily_mean_annual':float(interaction.mean()*252),
              'effective_independent_5y_windows':(b-a).days/365.25/5,
              'limitations':['reused historical data, not independent OOS','overlapping windows are not independent',
                             'Holm covers only these 3 hypotheses, not all past research','tax_fx tax/dividend approximation',
                             'daily TWR p-value is not after-liquidation IRR p-value','SSO daily leverage, actual prices only']}
    report = f'# {ID}\n\n'+rp.power_line(power)+'\n\n'
    report += '| 후보 | 판정 | SPY 대비 중앙 IRR | 기존 대비 중앙 IRR | Holm p |\n|---|---|---|---|---|\n'
    for n,v in verdicts.items():
        report += f'| {n} | {v["verdict"]} | {v["median_spy_gap"]:+.2%}p | {v["median_incumbent_gap"]:+.2%}p | {v["holm_p"]:.3f} |\n'
    report += '\n수익 차이는 연 %p. 기존=실제 SSO15 필터 전략. 월간15 대조군으로 재조정 효과를 분리한다.\n'
    report += '\n반복 사용 과거의 후보 선별이며 채택이 아니다. 중첩 창을 독립 표본으로 세지 않는다. 2024-10 이후는 사용하지 않는다.\n'
    report += '\n금융위기·앞/뒤 시대 진단, 모든 계좌, 탈락 관문은 results.json에 기록한다. 통계는 기존 대비 일별 TWR 평균 검정이며 세후 IRR 검정이 아니다.\n'
    u.write_outputs(out,result,report)
    return 0


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--smoke',action='store_true')
    args=p.parse_args()
    def stop(*_):
        raise u.StopRequested()
    signal.signal(signal.SIGTERM,stop)
    try:
        return run(args.out,args.checkpoint,args.smoke)
    except u.StopRequested:
        return 3

if __name__=='__main__':
    raise SystemExit(main())
