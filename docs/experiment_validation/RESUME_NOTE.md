# Resume — Day 1 remains blocked

2026-09-18 UTC, `/opt/quant`. Perform only remaining Day 1 work. Do not advance
the supervisor state or write its completion token while these issues remain.
No service, broker credential, production strategy, or root progress file was
modified. No daily HTML report was committed and no Telegram message was sent.

## Existing work and ambiguities preserved

The root `PROGRESS.md`, `deploy/codex_telegram/runner.py` (pre-existing mode
change), `docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md`, and
`docs/reports/README.md` had uncommitted changes on arrival. Their content hashes
and permissions matched `initial_workspace.json` at the pre-publication check.
The final observation below records subsequent concurrent changes. Other untracked research
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

Publication succeeded: evidence commit `38a15e61dfe95c3b02aab539732dcc20b63252fc`
is on `origin/research/day1-validation-20260918`. The main working tree remains
on its original branch with these artifacts present as an untracked directory.
Do not assume the artifacts are absent because main has not merged the research
branch. The isolated worktree is `/tmp/quant-day1-validation-20260918`.

## Concurrent workspace change observed at final check

At 2026-09-18T09:52:43+00:00, main had advanced from
`ba408756b47e53c170a168db63e53a45d979baf6` to
`17bad161b019eba3a62bd526f840394dea9ab340`, with separate commits
`814ec7f` (supervision/reporting), `e598206` (state initialization), and
`17bad16` (help text). The runner content SHA changed from
`43b94cbf9c15497605367a6f76eecd989017260b6bbeaef3f131bcf8b1894b28` to
`588df4f3fc5fc31762f654e90cc1ab39dec25d3a0bcc257e40dcd66b3848681d`,
and permissions from 0750 to 0664. Protocol bytes stayed unchanged, but its
permissions changed from 0644 to 0664 and it is now committed on main.
Root PROGRESS.md and reports README bytes/permissions still matched.

This task did not write those files or make those commits. No reset, restore,
merge or service operation was attempted. Exact observations are saved in
`workspace_final_observation.json`; the earlier preservation check is a prior
checkpoint, not a statement that other workers cannot change shared files.
Re-read current git status/log before resuming. The evidence code SHA remains
the original inspected SHA; do not relabel it with the newer main HEAD.


## 2026-09-18 14:15 UTC — 이번 재개 결과가 이전 재개 지침보다 우선

Day 1은 B1/B2/B3로 계속 보류 중이다. 완료 표식은 없다.
새 근거가 생겼는지 먼저 확인하고, 같은 데이터 재수집/백테스트를 반복하지 않는다.
상세 다음 단계와 실행 명령:
`docs/experiment_validation/day1_review_20260918T141530Z/RESUME_NOTE.md`.
이 경로는 저장소 루트 기준이다. 이번 결과/해시는 같은 디렉터리의 `review.md`,
`reference_probe.json`, `result_hashes.json`에 있다.

기존 `/tmp/quant-day1-validation-20260918`는 실제 디렉터리가 사라졌고 git 등록만
남아 있다. 삭제하거나 강제 수정하지 않았다. 새 게시 worktree는
`/tmp/quant-day1-review-20260918`, 새 연구 브랜치는
`research/day1-review-20260918`이다. 실제 게시 SHA/상태는 이번 디렉터리의
`publication.json`을 확인한다. 그 파일이 없으면 게시가 완료됐다고 가정하지 않는다.

루트 PROGRESS.md의 기존 미커밋 연구, docs/reports/README.md, 앞선 미완료
`day1_resume_20260918T135512Z/`, 고정된 55개 증거는 덮어쓰지 않았다.
진행/재개 파일은 기존 본문 뒤에 이번 내용만 추가했다. 연구 브랜치의 루트
진행 기록에는 이번 추가분만 반영하고 별도 미커밋 연구 항목은 포함하지 않는다.
main push·서비스 조작·실계좌 주문·인증정보 변경·일일 HTML 커밋은 수행하지 않는다.
