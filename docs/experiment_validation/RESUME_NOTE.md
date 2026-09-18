# Resume — Day 1 remains blocked

2026-09-18 UTC, `/opt/quant`. Perform only remaining Day 1 work. Do not advance
the supervisor state or write its completion token while these issues remain.
No service, broker credential, production strategy, or root progress file was
modified. No daily HTML report was committed and no Telegram message was sent.

## Existing work and ambiguities preserved

The root `PROGRESS.md`, `deploy/codex_telegram/runner.py` (pre-existing mode
change), `docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md`, and
`docs/reports/README.md` had uncommitted changes on arrival. Their content hashes
and permissions still match `initial_workspace.json`. Other untracked research
and runtime directories were left in place. The current protocol's operational
amendments are not in the reference commit, so the actual working-file snapshot
is explicitly stored and hashed rather than misrepresented as that commit.

Progress-path ambiguity is resolved by the protocol and supervisor code:
`deploy/experiment_supervisor.py:98` scans **this directory's `PROGRESS.md`**.
The root's large, already modified `PROGRESS.md` was read and preserved.
`.experiment-control/state.json` was read; the supervisor owns its updates.

## Next steps, in order

1. Verify the existing evidence without downloading or rerunning backtests:

   ```bash
   cd /opt/quant
   .venv/bin/python docs/experiment_validation/check_snapshot.py
   .venv/bin/python -m pytest -q docs/experiment_validation/test_snapshot.py
   .venv/bin/python docs/experiment_validation/check_snapshot.py --require-complete
   ```

   Expected: integrity PASS, 6 tests pass, final command exits 2 (blocked).
   Compare the lock checksum with the independent value in this directory's
   `PROGRESS.md`. Do not replace a lock merely to accept changed data.

2. Read `spec.json` and `day1_findings.md`, then search authoritative records for
   **B1**: S5 tickers/horizon/allocation, the intended S6 algorithm, month/SMA
   conventions and baseline rebalance rules. Existing live and historical
   Champion methods disagree; selecting one is not a mechanical conversion of
   the protocol. Do not invent a parameter or run performance comparisons to
   decide. If no prior specification exists, owner clarification is required.

3. Resolve **B2** without changing candidates or gates: the 17-ETF common panel
   includes XLRE (first price 2015-10-08), and the only authorized proxy is
   XLC→VOX. This cannot supply the fixed first OOS window with 12-month warmup.
   Locate an already authorized resolution; otherwise retain the block for the
   owner's explicit decision. No additional proxy is authorized by this note.

4. Resolve **B3**: establish and document S6's valid point-in-time input coverage
   and provenance, including the information actually available on signal dates.
   The copied membership table's upstream retrieval time is unknown, and its
   last event date is 2026-06-30. Current sectors, future-share fallback, silent
   delisted-stock omission and extrapolated current memberships cannot qualify.
   Freeze the required input panel only after B1 has identified the intended
   algorithm. Keep raw identifiers and publication/effective timestamps.

5. Preserve this blocked-state snapshot. When the above are resolved, create an
   explicitly named revision with complete candidate/execution definitions and
   all required data hashes. Distinguish the inspected reference-code SHA from
   the final implementation SHA. Test it, then record completion only if every
   Day 1 condition passes. The current checker is an evidence checker, not a
   certificate of backtest or point-in-time correctness.

Do not rerun `capture_day1.py`: it deliberately refuses to overwrite existing
data and its original 19 downloads already succeeded. No deterministic
backtest has run in this task. No Day 2/3/4 artifacts exist.

## Publication

Only this new directory is to be committed through a separate worktree on
`research/day1-validation-20260918`, then pushed to that same remote branch.
This preserves the dirty main worktree and avoids the main-branch automatic
deployment path. Do not merge or push main, restart services, stage unrelated
research/runtime files, or use force push. The publication result is appended
to this directory's progress record after the push.
