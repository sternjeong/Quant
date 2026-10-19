"""Six fixed return-improvement research jobs. Historical results are screening only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import pickle
import signal
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core import market_data as md, research_power as rp, rolling_eval as re_, tax_fx as tx

IDS = (
    'sleeve-local-execution-v1', 'sso-contrib-confirm-v1', 'stagger-sso-combine-v1',
    'stock-residual-momentum-v1', 'earnings-confirm-momentum-v1', 'momentum-rebound-switch-v1',
)
VERSION = '2026-10-19/1'
DECISION_END = pd.Timestamp('2024-09-30')
START = pd.Timestamp('2010-01-01')
CFG = tx.AccountConfig(initial_krw=10_000_000, monthly_contribution_krw=150_000,
                       contribution_policy='underweight_first')
STOCK_PREREG = {
    IDS[3]: {'signal': '36-month rolling OLS intercept+FF3; rank prior 12-to-2 month residual mean / residual sd',
             'control': 'price momentum on identical PIT universe', 'control_median_irr_gap_min': .005,
             'min_history_months': 36, 'n_positions': 3, 'satellite_weight': .15},
    IDS[4]: {'signal': '(quarter EPS - year-earlier same-quarter EPS) / sd(previous 8 YoY EPS changes); published before signal date',
             'control': 'price momentum on identical PIT universe', 'control_median_irr_gap_min': .005,
             'price_rank_pool': 10, 'n_positions': 3, 'satellite_weight': .15},
}


class StopRequested(Exception):
    pass


def module(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    spec.loader.exec_module(obj)
    return obj


def atomic(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL))
    tmp.replace(path)


def write_outputs(out: Path, result: dict, report: str):
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / 'results.json.tmp'
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding='utf-8')
    tmp.replace(out / 'results.json')
    tmp = out / 'REPORT.md.tmp'
    tmp.write_text(report, encoding='utf-8')
    tmp.replace(out / 'REPORT.md')


def audit_pit(job_id: str, smoke: bool) -> tuple[dict, str]:
    """Fail closed: an incomplete survivor-free data package cannot certify stock signals."""
    base = ROOT / 'data/research_inputs/crsp_sp500'
    needed = {'daily.csv': {'permno', 'date', 'prc', 'ret', 'vol', 'shrout'},
              'names.csv': {'permno', 'namedt', 'nameendt', 'siccd', 'exchcd', 'shrcd'},
              'delists.csv': {'permno', 'date', 'dlret', 'dlstcd'},
              'sp500.csv': {'permno', 'start', 'ending'}}
    if job_id == IDS[3]:
        needed['ff3_monthly.csv'] = {'date', 'mktrf', 'smb', 'hml', 'rf'}
    else:
        needed['eps_pit.csv'] = {'permno', 'accepted_at', 'fiscal_period_end', 'eps_split_adjusted'}
    issues = []
    for name, fields in needed.items():
        path = base / name
        if not path.is_file():
            issues.append(f'{name}: 없음')
            continue
        try:
            header = set(pd.read_csv(path, nrows=0).columns.str.lower())
        except (OSError, ValueError, pd.errors.EmptyDataError) as exc:
            issues.append(f'{name}: 헤더를 읽을 수 없음 ({type(exc).__name__})')
            continue
        missing = fields - header
        if missing:
            issues.append(f'{name}: 열 부족 {sorted(missing)}')
    # A complete data bundle needs an independently reviewed PIT/delist loader before any return verdict.
    if not issues:
        issues.append('시점별 구성종목·상장폐지·공시 접수시각을 결합하는 검증 로더 미등록')
    verdict = 'SMOKE_ONLY(NOT_EVALUABLE_DATA)' if smoke else 'NOT_EVALUABLE_DATA'
    result = {'id': job_id, 'version': VERSION, 'smoke': smoke, 'verdicts': {'primary': verdict},
              'missing_inputs': issues, 'power': rp.power_report(14.7, 6),
              'preregistered_signal': STOCK_PREREG[job_id],
              'status': 'data and point-in-time eligibility audit; no performance calculation'}
    report = f'# {job_id}\n\n판정: **{verdict}**. 수익률 계산은 하지 않았다.\n\n' + '\n'.join(f'- {x}' for x in issues) + '\n'
    return result, report


def synthetic_prices(index, spy_close, spy_adj, bil_close, bil_adj):
    r = spy_adj.pct_change().fillna(0.0)
    br = bil_adj.pct_change().fillna(0.0)
    # Smoke only: gives a realistic-shaped 2x path, never used for a real verdict.
    sso = 100 * (1 + (2 * r - br - .009 / 252).clip(lower=-.95)).cumprod()
    return pd.DataFrame({'SPY': spy_close, 'BIL': bil_close, 'SSO': sso}, index=index), pd.DataFrame(
        {'SPY': spy_adj, 'BIL': bil_adj, 'SSO': sso}, index=index)


def real_sso_panel():
    hist = md.get_multiple_price_history(['SPY', 'BIL', 'SSO'], start='2005-01-01', end=None, interval='1d')
    raw, adj = {}, {}
    for t in ('SPY', 'BIL', 'SSO'):
        h = hist.get(t)
        if h is None or h.empty or 'Close' not in h or 'Adj Close' not in h:
            raise RuntimeError(f'{t} 실제 가격/조정가가 없음')
        raw[t] = h['Close']
        adj[t] = h['Adj Close']
    c, a = pd.DataFrame(raw).sort_index(), pd.DataFrame(adj).sort_index()
    c.index = pd.DatetimeIndex(c.index).tz_localize(None).normalize()
    a.index = pd.DatetimeIndex(a.index).tz_localize(None).normalize()
    first = max(c[t].first_valid_index() for t in c)
    c, a = c.loc[first:].ffill(limit=3), a.loc[first:].ffill(limit=3)
    if c.loc[:DECISION_END].isna().any().any() or a.loc[:DECISION_END].isna().any().any():
        raise RuntimeError('SSO/SPY/BIL 평가 구간 가격 공백')
    return c, a


def p1st_data(smoke):
    c = module('return_upgrade_contrib', 'research/jobs/contrib-reval-champion-v1/run.py')
    base = c._smoke_base(print) if smoke else c._real_base(print)
    return c, base


def make_prep(job_id, smoke):
    mode = IDS.index(job_id)
    c = base = None
    if mode in (0, 2, 5):
        c, base = p1st_data(smoke)
        close, adj, fx = base['close'].copy(), base['adj'].copy(), base['fx'].copy()
        calendar = base['frames']['P1ST'].index
        p1st = base['frames']['P1ST'].reindex(calendar).ffill().fillna(0.0)
    else:
        p1st = None
        if smoke:
            idx = pd.bdate_range('2006-01-03', '2026-06-30')
            rng = np.random.default_rng(20261019)
            sr = rng.normal(.0004, .01, len(idx))
            br = np.full(len(idx), .00008)
            spy = 100 * np.cumprod(1 + sr)
            bil = 100 * np.cumprod(1 + br)
            close, adj = synthetic_prices(idx, pd.Series(spy, idx), pd.Series(spy, idx), pd.Series(bil, idx), pd.Series(bil, idx))
            fx = pd.Series(1300.0, idx)
        else:
            close, adj = real_sso_panel()
            fx = tx.usdkrw_series()
        calendar = close.index
    if mode in (1, 2):
        state_source = close['SPY'].dropna()
        if mode == 2:
            if smoke:
                spy, bil = close['SPY'], close['BIL'] if 'BIL' in close else pd.Series(100.0, calendar)
                sc, sa = synthetic_prices(calendar, spy, adj['SPY'], bil, adj['BIL'] if 'BIL' in adj else bil)
            else:
                sc, sa = real_sso_panel()
                state_source = sc['SPY'].dropna()
            close = close.join(sc[['BIL', 'SSO']], how='left', rsuffix='_duplicate')
            adj = adj.join(sa[['BIL', 'SSO']], how='left', rsuffix='_duplicate')
            for t in ('BIL', 'SSO'):
                if t + '_duplicate' in close:
                    close[t] = close[t + '_duplicate']; close = close.drop(columns=t + '_duplicate')
                    adj[t] = adj[t + '_duplicate']; adj = adj.drop(columns=t + '_duplicate')
        lb = module('return_upgrade_lev', 'research/jobs/lev-base-v1/run.py')
        state = lb.buffered_state(state_source)
        if mode == 1:
            calendar = calendar[calendar >= pd.Timestamp('2010-01-01')]
        else:
            calendar = calendar.intersection(close['SSO'].dropna().index)
        calendar = calendar[calendar <= DECISION_END] if not smoke else calendar
        state = state.reindex(calendar).ffill().fillna(False)
        asset = pd.DataFrame({'SSO': state.astype(float), 'BIL': 1.0-state.astype(float)}, index=calendar)
        if mode == 1:
            w, _ = lb.SC.sleeve_weights(calendar, adj.reindex(calendar), [
                ('spy', .85, pd.DataFrame({'SPY':1.0}, index=calendar)), ('lev', .15, asset)])
            controls = {'SPY': tx.buy_and_hold_weights(calendar, 'SPY')}
            # Synthetic comparison is diagnostic and uses the same signal.
            sr = adj['SPY'].reindex(calendar).pct_change().fillna(0.0)
            br = adj['BIL'].reindex(calendar).pct_change().fillna(0.0)
            synth = 100 * (1 + (2*sr-br-(.019/252)).clip(lower=-.95)).cumprod()
            close['SYN2'], adj['SYN2'] = synth, synth
            asset_s = asset.rename(columns={'SSO':'SYN2'})
            controls['SYNTH'] = lb.SC.sleeve_weights(calendar, adj.reindex(calendar), [
                ('spy', .85, pd.DataFrame({'SPY':1.0}, index=calendar)), ('lev', .15, asset_s)])[0]
            controls['NO_FILTER'] = lb.SC.sleeve_weights(calendar, adj.reindex(calendar), [
                ('spy', .85, pd.DataFrame({'SPY':1.0}, index=calendar)),
                ('lev', .15, pd.DataFrame({'SSO':1.0}, index=calendar))])[0]
        else:
            sat = p1st.reindex(calendar).fillna(0.0)
            # Use the incumbent P1ST satellite total; retain its current stock target vector.
            sat_part = sat.drop(columns='SPY', errors='ignore')
            sat_total = sat_part.sum(axis=1).replace(0, np.nan)
            sat_inner = sat_part.div(sat_total, axis=0).fillna(0.0)
            marks = pd.Series(False, index=calendar)
            for key in ('ST_A','ST_B','ST_C'):
                rows = (base.get('schedules') or {}).get(key, [])
                for row in rows:
                    d = pd.Timestamp(row['date'])
                    if d in marks.index:
                        marks.at[d] = True
            sat_inner.attrs['marks'] = marks
            w, _ = lb.SC.sleeve_weights(calendar, adj.reindex(calendar), [
                ('spy', .75, pd.DataFrame({'SPY':1.0}, index=calendar)), ('lev', .10, asset),
                ('sat', .15, sat_inner)])
            lev_only, _ = lb.SC.sleeve_weights(calendar, adj.reindex(calendar), [
                ('spy', .90, pd.DataFrame({'SPY':1.0}, index=calendar)), ('lev', .10, asset)])
            controls = {'SPY': tx.buy_and_hold_weights(calendar, 'SPY'), 'P1ST': sat, 'LEV10': lev_only}
    elif mode == 0:
        calendar = calendar[calendar <= DECISION_END] if not smoke else calendar
        w = p1st.reindex(calendar).ffill()
        controls = {'SPY': tx.buy_and_hold_weights(calendar, 'SPY'), 'P1ST': w}
    elif mode == 5:
        calendar = calendar[calendar <= DECISION_END] if not smoke else calendar
        baseline = p1st.reindex(calendar).ffill()
        close_spy = close['SPY'].reindex(calendar)
        high = close_spy.rolling(252, min_periods=252).max().shift(1)
        dd = close_spy.shift(1)/high - 1
        recent_panic = (dd <= -.20).rolling(63, min_periods=1).max().fillna(0) > 0
        rebound = close_spy.shift(1)/close_spy.shift(21)-1 > .05
        active = np.zeros(len(calendar), dtype=bool)
        triggers = []
        until = -1
        for i, day in enumerate(calendar):
            if i <= until:
                active[i] = True
            elif bool(recent_panic.iloc[i]) and bool(rebound.iloc[i]):
                until = min(i+62, len(calendar)-1)
                active[i:until+1] = True
                triggers.append(str(day.date()))
        w = baseline.copy()
        w.loc[active, :] = 0.0
        w.loc[active, 'SPY'] = 1.0
        controls = {'SPY':tx.buy_and_hold_weights(calendar, 'SPY'), 'P1ST':baseline}
    if w.empty or len(calendar) < 500:
        raise RuntimeError('공통 가격 구간 부족')
    close = close.reindex(calendar).ffill(limit=3)
    adj = adj.reindex(calendar).ffill(limit=3)
    fx = fx.reindex(calendar).ffill(limit=3)
    if fx.loc[calendar[calendar <= DECISION_END]].isna().any():
        raise RuntimeError('판정 구간 환율 공백')
    used = set(w.columns) | set().union(*(set(x.columns) for x in controls.values()))
    if close.reindex(columns=list(used)).loc[calendar[calendar <= DECISION_END]].isna().any().any():
        raise RuntimeError('판정 구간 종목 가격 공백')
    return {'weights':w, 'controls':controls, 'panels':{'close':close, 'adj':adj, 'fx':fx},
            'calendar':calendar, 'schedules':base.get('schedules') if base else None,
            'triggers':triggers if mode == 5 else [], 'mode':mode}


def local_trade_mask(prep, start, end):
    w = prep['weights'].loc[start:end]
    mask = pd.DataFrame(False, index=w.index, columns=w.columns)
    mask.iloc[0] = True
    sched = prep['schedules'] or {}
    months = {'ST_A': (1,7), 'ST_B':(3,9), 'ST_C':(5,11)}
    for k, m in months.items():
        rows = sched.get(k) or []
        prev = set()
        for row in rows:
            day = pd.Timestamp(row['date'])
            picks = set(row['picks'])
            if day in mask.index and day != mask.index[0]:
                for t in prev | picks:
                    if t in mask.columns:
                        mask.at[day,t] = True
            prev = picks
    jan = mask.index[(mask.index.month == 1) & pd.Series(lb_first_month(mask.index), index=mask.index).to_numpy()]
    mask.loc[jan,:] = True
    return mask


def lb_first_month(index):
    months = index.to_period('M')
    return np.r_[True, months[1:] != months[:-1]]


def sim(prep, name, start, end, cost_extra=0):
    w = prep['weights'] if name == 'CAND' else prep['controls'][name]
    w = w.loc[start:end]
    cfg = replace(CFG, fee_rate=CFG.fee_rate+cost_extra)
    mask = local_trade_mask(prep, start, end) if prep['mode'] == 0 and name == 'CAND' else None
    panels = prep['panels']
    return tx.simulate(w, panels['close'], panels['adj'], panels['fx'], cfg=cfg, trade_allowed=mask)


def ret_stats(s):
    twr = s['twr_index']
    years = (twr.index[-1]-twr.index[0]).days/365.25
    return {'irr':float(s['irr_after_liquidation']), 'terminal_krw':float(s['terminal_after_liquidation_krw']),
            'twr_cagr':float(twr.iloc[-1]**(1/years)-1) if years>0 else None,
            'mdd':re_.max_drawdown(twr),
            'worst252':float((s['twr_index']/s['twr_index'].shift(252)-1).min()) if len(s['twr_index'])>252 else None,
            'fees_krw':float(s['totals']['fees_krw']), 'tax_krw':float(s['totals']['capital_gains_tax_krw'])}


def active_bootstrap(candidate, benchmark):
    """Paired circular 126-session blocks; one-sided centered null for active mean."""
    a = candidate['twr_index'].pct_change().fillna(0).to_numpy(dtype=float)
    b = benchmark['twr_index'].pct_change().fillna(0).to_numpy(dtype=float)
    active = a-b
    n = len(active)
    if n < 126:
        return {'active_ir':None, 'one_sided_p':None, 'ci90_mean_annual':None}
    sd = float(active.std(ddof=1))
    observed = float(active.mean())
    rng = np.random.default_rng(20261019)
    blocks = int(math.ceil(n/126))
    starts = rng.integers(0,n,size=(1000,blocks))
    ix = ((starts[:,:,None] + np.arange(126)[None,None,:]) % n).reshape(1000,-1)[:,:n]
    means = active[ix].mean(axis=1)
    centered = means-observed
    p = (1+int((centered >= observed).sum()))/1001
    return {'active_ir':observed/sd*math.sqrt(252) if sd>0 else 0.0,
            'one_sided_p':p, 'ci90_mean_annual':(np.quantile(means,[.05,.95])*252).tolist(),
            'block_days':126, 'replicates':1000, 'seed':20261019,
            'comparison':'candidate minus SPY cashflow-adjusted daily TWR; p tests mean active return, not after-tax IRR'}


def judge(job_id, rows, full, stress, prep, smoke):
    primary = np.array([r['CAND']['irr']-r['SPY']['irr'] for r in rows])
    checks = {'win_share':float(np.mean(primary>0)) >= .70,
              'median_irr_plus_1pp':float(np.median(primary)) >= .01,
              'p10_irr_ge_minus_1_5pp':float(np.percentile(primary,10)) >= -.015,
              'full_mdd_within_5pp':full['CAND']['mdd'] >= full['SPY']['mdd']-.05,
              'full_worst252_within_5pp':(full['CAND']['worst252'] is not None and
                                           full['CAND']['worst252'] >= full['SPY']['worst252']-.05),
              'absolute_mdd_within_40pct':full['CAND']['mdd'] >= -.40,
              'cost_stress_positive':stress['CAND']['irr'] > stress['SPY']['irr']}
    if job_id == IDS[0]:
        plus = np.array([r['CAND']['irr']-r['P1ST']['irr'] for r in rows])
        checks['p1st_median_plus_0_3pp'] = float(np.median(plus)) >= .003
        checks['fee_reduction_20pct'] = full['CAND']['fees_krw'] <= .8*full['P1ST']['fees_krw']
    elif job_id == IDS[2]:
        for key in ('P1ST','LEV10'):
            plus = np.array([r['CAND']['irr']-r[key]['irr'] for r in rows])
            checks[f'{key}_median_plus_0_3pp'] = float(np.median(plus)) >= .003
    elif job_id == IDS[5]:
        plus = np.array([r['CAND']['irr']-r['P1ST']['irr'] for r in rows])
        checks['p1st_median_plus_0_3pp'] = float(np.median(plus)) >= .003
        checks['three_events'] = len(prep['triggers']) >= 3
    if smoke:
        verdict = 'SMOKE_ONLY'
    elif rp.noop_guard(primary):
        verdict = 'NOT_EVALUABLE'
    elif job_id == IDS[5] and not checks['three_events']:
        verdict = 'NOT_EVALUABLE_EVENTS'
    else:
        verdict = 'PASS_FORWARD_CANDIDATE' if all(checks.values()) else 'FAIL'
    return verdict, checks


def run(job_id, out:Path, checkpoint:Path, smoke=False):
    if job_id in (IDS[3],IDS[4]):
        result, report = audit_pit(job_id, smoke)
        write_outputs(out, result, report)
        return 0
    prep = make_prep(job_id, smoke)
    days = prep['calendar']
    judged = days[days <= DECISION_END]
    eval_days = judged[judged >= START]
    if job_id in (IDS[1],IDS[2]):
        first = prep['panels']['adj']['SSO'].first_valid_index()
        eval_days = eval_days[eval_days >= first]
    horizon = 2 if smoke else 5
    step = 'Q' if smoke else 'M'
    windows = [w for w in re_.rolling_windows(eval_days, horizon, step=step) if w[1] <= (days[-1] if smoke else DECISION_END)]
    if smoke:
        windows = windows[:3]
    if not windows:
        result = {'id':job_id,'version':VERSION,'verdicts':{'primary':'NOT_EVALUABLE_DATA'},
                  'reason':'5년 평가창 없음','power':None}
        write_outputs(out, result, f'# {job_id}\n\nNOT_EVALUABLE_DATA: 평가창 없음.\n')
        return 0
    checkpoint.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(f'{job_id}|{VERSION}|{smoke}|{windows[0]}|{windows[-1]}'.encode())
    for frame in (prep['weights'], prep['panels']['close'], prep['panels']['adj'], prep['panels']['fx']):
        digest.update(repr(getattr(frame,'columns',None)).encode())
        digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
    fp = digest.hexdigest()
    cp = checkpoint / 'rows.pkl'
    state = pickle.loads(cp.read_bytes()) if cp.exists() else {}
    rows = state.get('rows', []) if state.get('fingerprint') == fp else []
    limit = float(os.environ.get('RESEARCH_JOB_DEADLINE_EPOCH') or time.time()+3600)-60
    names = ['CAND'] + list(prep['controls'])
    for i in range(len(rows),len(windows)):
        if time.time() > limit:
            return 3
        a,b = windows[i]
        row = {'start':str(a.date()),'end':str(b.date())}
        for name in names:
            row[name] = ret_stats(sim(prep,name,a,b))
        rows.append(row)
        atomic(cp, {'fingerprint':fp,'rows':rows})
    a,b = windows[0][0], windows[-1][1]
    full_sims = {name:sim(prep,name,a,b) for name in names}
    full = {name:ret_stats(s) for name,s in full_sims.items()}
    stress = {name:ret_stats(sim(prep,name,a,b,.0025)) for name in ('CAND','SPY')}
    verdict, checks = judge(job_id,rows,full,stress,prep,smoke)
    diffs = [r['CAND']['irr']-r['SPY']['irr'] for r in rows]
    power = rp.power_report((b-a).days/365.25,6)
    nonoverlap = [r for r in rows if (pd.Timestamp(r['start']).year-2010)%5 == 0 and pd.Timestamp(r['start']).month == 1]
    result = {'id':job_id,'version':VERSION,'smoke':smoke,'verdicts':{'primary':verdict},'checks':checks,
              'metrics':{'windows':len(rows),'effective_independent_windows':(b-a).days/365.25/horizon,
                         'win_share':float(np.mean(np.array(diffs)>0)), 'median_irr_gap':float(np.median(diffs)),
                         'p10_irr_gap':float(np.percentile(diffs,10)),
                         'nonoverlap_5y':[{k:r[k] for k in ('start','end')} | {'irr_gap':r['CAND']['irr']-r['SPY']['irr']}
                                          for r in nonoverlap]},
              'full_account':full,'cost_stress':stress,'events':prep['triggers'],'power':power,
              'statistical_support':active_bootstrap(full_sims['CAND'],full_sims['SPY']),
              'limitations':['historical reuse; no independent holdout','overlapping rolling windows',
                             'P1ST equity universe may exclude delisted stocks']}
    report = f'# {job_id}\n\n판정 **{verdict}**. {len(rows)}개 중첩 평가창(비중첩 환산 {result["metrics"]["effective_independent_windows"]:.1f}개).\n\n'
    report += f'SPY 대비 IRR 차이 중앙 {np.median(diffs)*100:+.2f}%p, 10분위 {np.percentile(diffs,10)*100:+.2f}%p, 승리 {np.mean(np.array(diffs)>0):.1%}.\n\n'
    report += '| 관문 | 통과 |\n|---|---|\n' + ''.join(f'| {k} | {v} |\n' for k,v in checks.items())
    support = result['statistical_support']
    report += (f'\n활성 일수익 블록 부트스트랩: IR {support["active_ir"]}, 단측 p {support["one_sided_p"]}; '
               '여섯 작업의 Holm 보정은 전체 결과를 모은 뒤에만 계산한다. 이 값은 세후 IRR 유의확률이 아니다.\n\n')
    report += (rp.power_line(power) + '\n\n중첩 구간은 독립 표본이 아니며 2010~2024 이력은 반복 사용됐다. '
               'P1ST가 포함된 작업은 상장폐지 종목 누락 가능성이 있다. '
               '2024-10 이후는 판정에 사용하지 않았다. 엔진 반영은 별도 결정이다.\n')
    write_outputs(out,result,report)
    return 0


def main(job_id, argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--checkpoint',required=True,type=Path)
    p.add_argument('--smoke',action='store_true')
    args=p.parse_args(argv)
    old = signal.getsignal(signal.SIGTERM)
    def stop(signum, frame):  # noqa: ARG001
        raise StopRequested()
    signal.signal(signal.SIGTERM, stop)
    try:
        return run(job_id,args.out,args.checkpoint,args.smoke)
    except StopRequested:
        return 3
    finally:
        signal.signal(signal.SIGTERM, old)
