# Day 1 preregistration findings

Status: **BLOCKED**. No strategy or selection gate has been changed.

## B1 — incomplete executable specification

The protocol fixes S5 as positive absolute momentum followed by top-three
relative momentum across five asset-class ETFs, but does not enumerate those
five tickers, momentum horizon or allocation when fewer than three qualify.
S4's five tickers are explicit; applying them to S5 would be an inference.
Likewise the protocol does not resolve calendar-month versus trading-day
lookbacks, the SMA observation convention, or benchmark rebalance schedules.
These choices must be fixed before observing performance.

S6 fixes an 85% S1 core and 15% point-in-time Donchian satellite with semiannual
satellite rebalancing. Existing code offers materially different live and
historical satellite methods. The historical method uses a 40-stock pool,
three picks, a 20-close breakout, a 15% trailing stop, and a 252-session ranking;
the live method uses prior highs and five picks with a 63-session ranking.
They are evidence of prior implementations, not interchangeable specifications.
`spec.json` records historical defaults as **not adopted** pending authoritative
linkage to the preregistered S6. No parameter search was performed.

The existing Champion core also selects only positive momentum and applies a
SPY 200-session filter by default (`source/champion_strategy.py:342` and the
following filter). S1 in this protocol is raw relative momentum top four.
Using the old core unchanged would silently change the registered candidate.

## B2 — long-sample coverage conflict

The existing 17-ETF list includes XLRE. In the new provider response, its first
row is **2015-10-08**; XLC starts **2018-06-19**, and HYG **2007-04-11**.
Only XLC→VOX is an authorized proxy substitution. Even with that substitution,
the common raw panel cannot start before XLRE in 2015. A 12-month fully warmed
signal cannot be evaluated in the first fixed 2007–2015 OOS window on this panel.
This is relevant to the fixed multi-window selection gate, not a performance
finding. Data before requested 2006-01-01 were not sought.

No XLRE→IYR substitution, expanding universe, prelisting fill, shortened
lookback or relaxed gate was introduced. An already registered resolution must
be found, or the experiment owner must clarify the conflict before final freeze.

## B3 — point-in-time input coverage/provenance

The byte-preserved local S&P membership table has 2,718 rows spanning
1996-01-02 to 2026-06-30. Root `PROGRESS.md:2020` describes a local merger of an
older historical-components file and subsequent changes, but original upstream
revisions and query timestamps are not recorded. Do not extrapolate its final
row through September without verified membership-event coverage.

The snapshot lacks historical sector classifications, share publication times,
security identifiers for reused/delisted tickers, and complete delisted-price
inputs. These cannot be reconstructed by silently using current data. Existing
code has specific paths requiring exclusion or correction in a future validated
implementation:

- `source/strategy_tuning.py:89`: present-day sector mapping is used for past
  members, affecting sector quotas and hence satellite selection.
- `source/point_in_time_market_cap.py:130`: a request before share-history
  coverage takes the earliest **future** observation. Publication lag is also
  not verified by the existing approximation.
- `source/point_in_time_universe.py:106`: a query before membership-history
  coverage returns the earliest **future** row. Historical ticker suffixes are
  stripped, which also requires identifier review before using old securities.
- `source/champion_strategy.py:459`: short history can substitute an inception
  return for the stated 252-session momentum. This must not be silently inherited.

These are static evidence and data-source limitations, not a completed S6
backtest audit. No production code was changed and these functions were not
invoked for a strategy simulation.

## Close/open execution and leakage check

The saved execution contract requires signal information available by session
close and fills at the **next exchange session's Open**, with separate 5/10/25bp
one-way cost cases. Missing Open is an unresolved order, not permission to fill
at the previous close or invent a price.

`source/champion_strategy.py:360–364` multiplies shifted weights by close-to-close
returns. It does not read Open. The shift alone cannot establish next-open
execution, correct overnight exposure or drift-aware turnover. This existing
engine is therefore not accepted as the protocol's execution engine. No claim
is made that a next-open engine was implemented or tested during Day 1.

All downloaded price columns and exchange-zone offsets are kept separately.
Adjusted-close versus Open treatment, corporate actions, missing prices and
timestamp mapping still need the designated later audits after the registration
blockers have been resolved. No future-universe or same-close exception is added.
