"""Six preregistered ETF research families. Full calculation belongs to VM runner."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
import pickle
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core import research_power as rp
from core import tax_fx as tx

spec = importlib.util.spec_from_file_location('edge_sector_source', ROOT / 'research/jobs/sector-concentrate-v1/run.py')
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)
# Fixed original nine sector ETFs: no hindsight addition of XLC/XLRE.
SECTORS = sc.ETF_SECTORS[:9]
CELLS = {'beta': (126, 252), 'skip': (21, 42), 'smooth': (126, 252),
         'correlation': (0.65, 0.80), 'gap': (0.10, 0.20), 'agreement': (63, 126)}
PERIODS = {'early': ('2000-01-01', '2011-12-31'),
           'judge': ('2012-01-01', '2024-09-30'),
           'half1': ('2012-01-01', '2017-12-31'),
           'half2': ('2018-01-01', '2024-09-30'),
           'recent': ('2024-10-01', '2026-10-15')}
N_TRIALS = 12


def load_data(smoke):
    if smoke:
        d = sc.synthetic_etf(19)
        return {k: (v[SECTORS + ['SPY']] if k in ('adj', 'close') else v) for k, v in d.items()}
    from core.market_data import get_multiple_price_history
    raw = get_multiple_price_history(SECTORS + ['SPY'], start='1998-12-01', end='2026-10-16', interval='1d') or {}
    frames = {}
    for kind, name in [('close', 'Close'), ('adj', 'Adj Close')]:
        items = {}
        for ticker in SECTORS + ['SPY']:
            df = raw.get(ticker)
            if df is None or name not in df:
                raise ValueError(f'missing required {name}: {ticker}; no raw-close substitute')
            s = df[name].copy()
            s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
            items[ticker] = s[~s.index.duplicated(keep='last')]
        frames[kind] = pd.DataFrame(items).reindex(items['SPY'].dropna().index).loc[:'2026-10-15']
    frames['fx'] = tx.usdkrw_series()
    frames['source'] = 'actual ETF Close/Adj Close; tax_fx USDKRW; original 9 sector menu'
    return frames


def validate_data(d):
    for key in ('close', 'adj'):
        f = d[key]
        if not f.index.is_monotonic_increasing or not f.index.is_unique:
            raise ValueError('unordered or duplicate dates')
        active = f.loc['1999-01-01':]
        if active.isna().any().any() or (active <= 0).any().any():
            raise ValueError(f'{key}: missing/nonpositive active prices; do not fill future prices')
    if d['adj'].index.min() > pd.Timestamp('1999-01-05') or d['adj'].index.max() < pd.Timestamp('2024-09-30'):
        raise ValueError('insufficient history for fixed windows')
    fx = d['fx'].sort_index().reindex(d['adj'].index, method='ffill')
    if fx.loc['2000-01-01':].isna().any() or (fx.dropna() <= 0).any():
        raise ValueError('missing FX; no backward filling')
    d['fx'] = fx


def make_weights(adj, family='control', param=0):
    """Month first close trades using only previous close and earlier information."""
    r = adj.pct_change(fill_method=None)
    p = adj[SECTORS]
    score = p / p.shift(252) - 1
    if family == 'beta':
        beta = r[SECTORS].rolling(252).cov(r.SPY) / r.SPY.rolling(252).var().to_numpy()[:, None]
        score = r[SECTORS].rolling(param).sum().sub(beta.mul(r.SPY.rolling(param).sum(), axis=0))
    elif family == 'skip':
        score = p.shift(param) / p.shift(252) - 1
    elif family == 'smooth':
        logs = np.log(p).diff()
        efficiency = logs.rolling(param).sum() / logs.abs().rolling(param).sum()
        score = score.rank(axis=1, pct=True) * .5 + efficiency.rank(axis=1, pct=True) * .5
    short = p / p.shift(int(param) if family == 'agreement' else 126) - 1
    idx = adj.index
    rows, last, event = [], np.zeros(len(SECTORS) + 1), 0
    for i, dt in enumerate(idx):
        decision = i > 0 and (dt.year, dt.month) != (idx[i-1].year, idx[i-1].month)
        if decision:
            row = score.iloc[i-1].dropna().sort_values(ascending=False, kind='stable')
            if len(row) >= 4:
                picks = list(row.index[:2])
                if family == 'gap' and row.iloc[0] - row.iloc[1] > param:
                    picks = picks[:1]
                elif family == 'agreement':
                    srow = short.iloc[i-1].dropna().sort_values(ascending=False, kind='stable')
                    if len(srow) and srow.index[0] == picks[0]:
                        picks = picks[:1]
                elif family == 'correlation':
                    past = r[SECTORS].iloc[i-126:i]
                    eligible = [x for x in row.index[1:4] if past[picks[0]].corr(past[x]) <= param]
                    if eligible:
                        picks[1] = eligible[0]
                history = r[picks].iloc[max(0, i-126):i]
                vol = history.mean(axis=1).std(ddof=1) * np.sqrt(252)
                exposure = min(1., .20 / vol) if len(history) == 126 and np.isfinite(vol) and vol > 0 else 0.
                last = np.zeros(len(SECTORS) + 1)
                for t in picks:
                    last[SECTORS.index(t)] = exposure / len(picks)
                # tax_fx only trades when target changes. Tiny alternating cash reserve forces monthly reset.
                event += 1
                last *= 1 - (event % 2) * 1e-7
        rows.append(last.copy())
    return pd.DataFrame(rows, index=idx, columns=SECTORS + ['SPY'])


def simulate(d, weights, bounds, fee):
    w = weights.loc[bounds[0]:bounds[1]]
    if len(w) < 200:
        raise ValueError('insufficient window')
    cfg = tx.AccountConfig(fee_rate=fee)
    sim = tx.simulate(w, d['close'], d['adj'], d['fx'], cfg)
    v = sim['values_krw'].copy()
    v.iloc[-1] = sim['final_after_liquidation_krw']
    ret = v.pct_change()
    ret.iloc[0] = v.iloc[0] / cfg.initial_krw - 1
    years = (v.index[-1] - v.index[0]).days / 365.25
    metrics = {'cagr': float((v.iloc[-1] / cfg.initial_krw) ** (1/years) - 1),
               'mdd': float((v / v.cummax().clip(lower=cfg.initial_krw) - 1).min()),
               'worst252': float(v.pct_change(252).min()) if len(v) > 252 else None,
               'years': years, 'totals': sim['totals']}
    return {'metrics': metrics, 'returns': ret}


def bootstrap_p(active, n=6000):
    """Centered circular paired 63-day block bootstrap, one-sided positive mean."""
    x = np.asarray(active, dtype=float)
    rng = np.random.default_rng(20261016)
    observed = x.mean()
    z = x - observed
    exceed = 0
    for _ in range(n):
        starts = rng.integers(0, len(x), size=int(np.ceil(len(x)/63)))
        sample = z[((starts[:, None] + np.arange(63)) % len(x)).ravel()[:len(x)]]
        exceed += sample.mean() >= observed
    return float((1 + exceed) / (n + 1))


def decide(candidate, spy, control, halves, stress, power, smoke=False):
    active = candidate['returns'] - spy['returns']
    control_active = candidate['returns'] - control['returns']
    if rp.noop_guard(active) or rp.noop_guard(control_active):
        return {'verdict': 'NOT_EVALUABLE', 'reason': 'daily identity to SPY or control'}
    ir = float(active.mean()/active.std(ddof=1)*np.sqrt(252)) if active.std() > 0 else 0.
    c, b, q = [v['metrics'] for v in (candidate, spy, control)]
    p = bootstrap_p(active, 100 if smoke else 6000)
    checks = {'spy_plus_1pp': c['cagr'] >= b['cagr']+.01,
              'control_plus_half_pp': c['cagr'] >= q['cagr']+.005,
              'mdd_slack_3pp': c['mdd'] >= b['mdd']-.03,
              'worst252_slack_5pp': c['worst252'] is not None and b['worst252'] is not None and c['worst252'] >= b['worst252']-.05,
              'both_halves': all(cg > bg for cg, bg in halves),
              'cost_stress_positive': stress[0] > stress[1],
              'family_bonferroni': p <= .05/N_TRIALS}
    passed = all(checks.values())
    verdict = 'PASS_FORWARD_CANDIDATE' if passed else rp.classify_fail(ir, power)
    return {'verdict': 'SMOKE_ONLY' if smoke else verdict, 'checks': checks, 'active_ir': ir,
            'p_raw': p, 'p_adjusted': min(1., p*N_TRIALS)}


def atomic_pickle(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_bytes(pickle.dumps(value))
    temp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--checkpoint', type=Path, required=True)
    ap.add_argument('--smoke', action='store_true')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    a.checkpoint.mkdir(parents=True, exist_ok=True)
    power = rp.power_report(12.75, N_TRIALS)  # computed before loading outcomes
    key = hashlib.sha256(Path(__file__).read_bytes()).hexdigest() + str(a.smoke)
    cp = a.checkpoint / 'state.pkl'
    state = pickle.loads(cp.read_bytes()) if cp.exists() else {}
    if state.get('key') != key:
        state = {'key': key, 'stages': {}}
    def stage(name, fn):
        if name not in state['stages']:
            deadline = float(os.environ.get('RESEARCH_JOB_DEADLINE_EPOCH', 'inf'))
            if time.time() > deadline - 60:
                raise TimeoutError
            state['stages'][name] = fn()
            atomic_pickle(cp, state)
        return state['stages'][name]
    try:
        d = stage('data', lambda: load_data(a.smoke))
        validate_data(d)
        candidates = [(f'{f}_{v}', f, v) for f, vals in CELLS.items() for v in vals]
        methods = [('SPY', 'SPY', 0), ('control', 'control', 0)] + candidates
        all_results = {}
        for name, family, param in methods:
            w = stage('weights_'+name, lambda family=family, param=param:
                      tx.buy_and_hold_weights(d['adj'].index) if family == 'SPY' else make_weights(d['adj'], family, param))
            for period, bounds in PERIODS.items():
                fees = (.001, .0025) if period == 'judge' else (.001,)
                for fee in fees:
                    k = f'{name}|{period}|{fee}'
                    all_results[k] = stage(k, lambda w=w, bounds=bounds, fee=fee: simulate(d, w, bounds, fee))
        def get(name, period='judge', fee=.001):
            return all_results[f'{name}|{period}|{fee}']
        judgments = {}
        for name, _, _ in candidates:
            judgments[name] = stage('decision_'+name, lambda name=name: decide(
                get(name), get('SPY'), get('control'),
                [(get(name, p)['metrics']['cagr'], get('SPY', p)['metrics']['cagr']) for p in ('half1', 'half2')],
                (get(name, fee=.0025)['metrics']['cagr'], get('SPY', fee=.0025)['metrics']['cagr']), power, a.smoke))
    except TimeoutError:
        return 3
    result = {'id': 'spy-edge-six-v1', 'smoke': a.smoke, 'power': power,
              'verdicts': {k: v['verdict'] for k, v in judgments.items()}, 'judgments': judgments,
              'metrics': {k: v['metrics'] for k, v in all_results.items()},
              'source': d['source'], 'code_hash': key,
              'data_hash': hashlib.sha256(pd.util.hash_pandas_object(d['adj']).values.tobytes()).hexdigest(),
              'limits': ['Retrospective reused periods, not independent OOS.',
                         'Tax and dividend reconstruction approximations; no legal verification.',
                         'USD cash earns zero; current ETF data may contain historical revisions.',
                         'Bonferroni covers these 12 cells only, not all prior research.',
                         'No engine or frozen forward ledger changes.']}
    (a.out/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    lines = ['# SPY 초과수익 신규 가설 6종', '', rp.power_line(power), '',
             '합성 스모크 — 성과 판정 아님' if a.smoke else '반복 사용한 과거 ETF 자료의 후보 선별. 독립 표본외 검증 아님.', '',
             '| 후보 | 판정 | 세후 CAGR | SPY 차이 | 대조군 차이 | MDD | 보정 p |', '|---|---|---|---|---|---|---|']
    for name, _, _ in candidates:
        m = get(name)['metrics']
        j = judgments[name]
        lines.append(f"| {name} | {j['verdict']} | {m['cagr']:.2%} | {m['cagr']-get('SPY')['metrics']['cagr']:+.2%} | {m['cagr']-get('control')['metrics']['cagr']:+.2%} | {m['mdd']:.2%} | {j.get('p_adjusted', '—')} |")
    lines += ['', '통과는 전진 검토 후보 의미. 세금·배당 복원 근사, 무이자 달러 현금, 월 1회 다음 종가 체결.',
              '모든 구간·비용 스트레스·탈락 조건은 results.json에 기록. 2024-10 이후는 참고만.',
              '기존 연구까지 포함한 선택 편향은 12칸 보정으로 제거되지 않음.']
    (a.out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
