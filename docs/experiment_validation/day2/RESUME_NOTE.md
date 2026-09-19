# Next automatic supervisor: Day 3 only

Day 2 passed. Read ../data_audit.md, ../day2_resolutions.md, validation.json and the two progress files. Preserve all original Day 1 hashes and the Day 1 resolution overlay. The old check_snapshot.py still reports the original BLOCKED status; it does not consume later owner resolutions.

1. Verify input/result hashes from result_hashes.json (paths relative to docs/experiment_validation) and audit_results.json. Do not re-download VNQ or recapture Day 1.
2. Use data_contract.py for strict price and next-open guards. Run the 27 relevant tests only if needed after implementation changes.
3. Complete only Day 3: baseline and S1–S5 full-period after-cost backtests, 5/10/25bp, baseline_metrics.csv. Implement actual next-session Open fills and drift/cash/fees; never reuse the legacy shifted close returns.
4. Main sample starts 2018-06-19 before warmup; long proxy panel starts 2007-04-11 before warmup because of HYG. Keep all fixed OOS windows and show unassessable warmup intervals; do not invent 2007 performance. XLC uses VOX throughout proxy sample; XLRE uses VNQ before 2015-10-08 and actual XLRE thereafter. Charge both legs of held proxy conversion.
5. Preserve/report XLRE zero-volume rows and reject executions on them. Never backfill, delete assets, shorten lookback, or change candidate/gates to resolve a problem. Resolve unspecified implementation details BEFORE performance runs with checkpoint → written basis → immediate Telegram notify.
6. Day 4 still must obtain/verify actual S6 PIT availability, sectors, share units and delisted prices. Current-sector or future-share fallbacks remain prohibited. Day 6 must audit real order logs.

Publication uses a separate research/day2-data-audit-20260919 branch, preserving dirty main. See publication.json for verified commit and remote SHA. Never commit runtime control files or daily HTML reports.
