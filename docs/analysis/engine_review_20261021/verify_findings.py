"""Offline audit probes, not strategy experiments. No network or production writes.

Run with the project venv and --repo /opt/quant to inspect the deployed code.
Outputs JSON to stdout; all prices below are synthetic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.repo))

import pandas as pd
from core import tax_fx as tx
from core import forward_tournament_v2 as f2
from core import forward_tournament_v3 as f3
from core import research_power as rp
from core.position_sizing import portfolio_volatility_target_weights

out = {'repo_commit': subprocess.check_output(
    ['git', '-C', str(args.repo), 'rev-parse', 'HEAD'], text=True).strip()}
out['source_hashes'] = {
    name: hashlib.sha256((args.repo / name).read_bytes()).hexdigest()
    for name in ('core/tax_fx.py', 'core/forward_tournament_v2.py',
                 'core/forward_tournament_v3.py', 'core/research_power.py',
                 'research/return_upgrade/runner.py')
}

# A gain realized in December is still payable when the account ends in January.
# This uses the engine's own tax assumptions, not an independent legal opinion.
days = pd.to_datetime(['2023-12-01', '2023-12-20', '2024-01-02'])
close = pd.DataFrame({'A': [100., 200., 200.]}, index=days)
w = pd.DataFrame({'A': [1., 0., 0.]}, index=days)
fx = pd.Series(1000., index=days)
cfg = tx.AccountConfig(initial_krw=30_000_000, fee_rate=0., fx_spread=0.)
s = tx.simulate(w, close, close, fx, cfg)
expected_tax = (30_000_000 - tx.ANNUAL_DEDUCTION_KRW) * tx.TAX_RATE
out['prior_year_unpaid_tax'] = {
    'reported_terminal': s['final_after_liquidation_krw'],
    'expected_terminal_under_same_tax_model': 60_000_000 - expected_tax,
    'missing_liability': expected_tax,
    'reported_unpaid_tax': s['unpaid_tax_if_sold_now_krw'],
    'reproduced': abs(s['final_after_liquidation_krw'] - 60_000_000) < 1e-6,
}

# With no tax, full liquidation must still pay the sale fee and exit FX spread.
days = pd.to_datetime(['2024-01-02', '2024-01-03'])
close = pd.DataFrame({'A': [100., 100.]}, index=days)
w = pd.DataFrame({'A': [1., 1.]}, index=days)
fx = pd.Series(1000., index=days)
cfg = tx.AccountConfig(initial_krw=30_000_000, fee_rate=.001,
                       fx_spread=.0005, apply_tax=False)
s = tx.simulate(w, close, close, fx, cfg)
expected_terminal = s['final_krw'] * (1 - cfg.fee_rate) * (1 - cfg.fx_spread)
out['terminal_sale_costs'] = {
    'reported_mark_to_market': s['final_krw'],
    'reported_liquidated': s['final_after_liquidation_krw'],
    'expected_liquidated_with_sale_and_fx': expected_terminal,
    'missing_cost': s['final_after_liquidation_krw'] - expected_terminal,
    'reproduced': s['final_after_liquidation_krw'] == s['final_krw'],
}

# Evaluation has no completed-bar filter, although record() has one.
days = pd.to_datetime(['2026-10-19', '2026-10-20'])
rows = [{'date': '2026-10-19', 'weights': {'B0': {'SPY': 1.}}}]
def prices(tickers):
    return {t: pd.DataFrame({'Close': [100., 90.], 'Adj Close': [100., 90.]},
                            index=days) for t in tickers}
returns = f2.ledger_returns(rows, prices)
series = f3.series_from_ledger(rows, 'B0', returns)
out['evaluation_accepts_uncompleted_bar'] = {
    'assumed_now_utc': '2026-10-20T15:40:00+00:00',
    'completed_dates_at_assumed_now': [str(d.date()) for d in f2._completed(
        days, pd.Timestamp('2026-10-20T15:40:00Z').to_pydatetime())],
    'evaluated_dates': [str(d.date()) for d in series.index],
    'reproduced': pd.Timestamp('2026-10-20') in series.index,
}

# The initial NAV=1 must be included when computing the first drawdown.
out['initial_drawdown_omitted'] = {
    'daily_returns': [-.10], 'reported_mdd': f2._mdd(pd.Series([-.10])),
    'expected_mdd': -.10,
    'reproduced': f2._mdd(pd.Series([-.10])) == 0.,
}
missing = pd.DataFrame({'SPY': [0., float('nan')]}, index=days)
got = f3.series_from_ledger(rows, 'B0', missing)
out['held_missing_return_becomes_zero'] = {
    'reported_return_including_entry_cost': float(got.iloc[0]),
    'reproduced': abs(float(got.iloc[0]) + .0003) < 1e-10,
}

# A cap followed by renormalization does not enforce the declared cap.
vol_returns = pd.DataFrame({'A': [-.001, .001] * 20,
                            'B': [-.01, .01] * 20,
                            'C': [-.02, .02] * 20})
cap_weights = portfolio_volatility_target_weights(vol_returns, max_weight=.4)
out['inverse_vol_cap_violated'] = {
    'declared_cap': .4, 'weights': cap_weights,
    'reproduced': max(cap_weights.values()) > .4,
}
threshold = rp.mde_ir(14.66, 6)
out['mde_label_means_50pct_power_threshold'] = {
    'reported_mde_ir': threshold,
    'power_at_reported_mde': rp.power(threshold, 14.66, 6),
    'interpretation': 'Not an MDE defined at 80% or 90% target power.',
}

# Aggregate the already produced p-values, as specified by the six-job design.
ids = ['sleeve-local-execution-v1', 'sso-contrib-confirm-v1',
       'stagger-sso-combine-v1', 'stock-residual-momentum-v1',
       'earnings-confirm-momentum-v1', 'momentum-rebound-switch-v1']
pv = {}
for name in ids:
    result = json.loads((args.repo / 'research/results' / name / 'results.json').read_text())
    p = result.get('statistical_support', {}).get('one_sided_p')
    pv[name] = float(p) if p is not None else 1.
ordered = sorted(pv, key=pv.get)
adjusted, running = {}, 0.
for i, name in enumerate(ordered):
    running = max(running, min(1., (len(ordered) - i) * pv[name]))
    adjusted[name] = running
out['six_job_holm_existing_results'] = {
    'raw_p': pv, 'holm_p': adjusted, 'alpha': .05,
    'passes': [name for name, p in adjusted.items() if p <= .05],
    'scope': 'Daily TWR mean only; no strategy rerun and no original verdict change.',
}
print(json.dumps(out, ensure_ascii=False, indent=2))
