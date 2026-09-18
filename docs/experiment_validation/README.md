# Day 1 evidence — blocked before final registration

2026-09-18 UTC. Scope: research and documentation for Day 1 only.
`spec.json` and `candidates.yaml` faithfully preserve the six protocol candidates,
three baselines and selection gates, but are explicitly **drafts**, not an executable
or completed registration. Do not run Day 2 or later work yet.

The working protocol has pre-existing, uncommitted operational amendments. Its
exact bytes are saved in `source/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md`; the
strategy/gate text is not modified. The inspected code SHA is
`ba408756b47e53c170a168db63e53a45d979baf6`. That SHA identifies existing reference
code, not a certified implementation of this new protocol.

## Saved evidence

- `candidates.yaml`: JSON-compatible YAML 1.2, containing exactly S1–S6. No YAML
  dependency is required; JSON syntax is intentional.
- `spec.json`: explicit protocol constraints, unchanged gate text, unresolved
  choices and three blocking issues.
- `manifest.json`: download arguments, source, UTC query times, timezone, package
  versions, row ranges, missing-value counts and compressed/uncompressed hashes.
- `data/`: 19 separate Yahoo Finance ETF OHLCV snapshots plus their metadata;
  a compressed, byte-preserving copy of the local historical membership table.
- `source/`: exact source files inspected, separate from the running application.
- `day1_findings.md`: preregistration issues and source evidence. This is not the
  Day 2 full data audit or the Day 4 S6 audit.
- `snapshot_lock.json`: SHA-256 inventory for immutable evidence. Its checksum is
  recorded in `PROGRESS.md` as an independent reference.
- `day1_validation.json`, `validation_tests.log`: saved verification results.
- `RESUME_NOTE.md`: bounded next steps and commands.

New ETF queries ran from 09:45:17 to 09:45:27 UTC on 2026-09-18, requesting
2006-01-01 through the exclusive end 2026-09-18. All 19 requests succeeded;
the last returned session is 2026-09-17. Provider Open, Close and Adj Close are
preserved separately with no fills or synthetic prices. The query start is a
capture bound, not an agreed backtest start. Further warmup may be required by
the eventual specification. No returns or candidate rankings were computed.

The local membership table was copied, not downloaded anew. Its original
upstream retrieval time is unknown and is explicitly null in the manifest.
Neither a Git commit date nor today's copy time is presented as that retrieval
time. Its checksum provides identity, not proof of point-in-time correctness.

## Verification and resume

From `/opt/quant`:

```bash
.venv/bin/python docs/experiment_validation/check_snapshot.py
.venv/bin/python -m pytest -q docs/experiment_validation/test_snapshot.py
.venv/bin/python docs/experiment_validation/check_snapshot.py --require-complete
```

The first command must report evidence integrity PASS; the last must exit **2**
while the registration is blocked. Passing integrity tests does not pass Day 1.
The checker never writes completion markers. Do not quote the supervisor's
completion-token syntax in this directory's progress file while blocked: the
supervisor scans that file with a regular expression rather than interpreting
negation or Markdown context.

Do not rerun `capture_day1.py` on this snapshot. It refuses to replace existing
data. Resolve the recorded issues from authoritative preregistration evidence
first; retain this evidence and use a separately named revision if needed.
Do not edit the six candidates, proxy authorization or selection gates to make
the experiment pass. Review publication/resume notes before further changes.

The lock excludes the progress/resume notes and validation outputs, which are
appendable records. It does not claim future hashes have already been checked.
Every later authorized run must verify the pinned inventory before using data.
