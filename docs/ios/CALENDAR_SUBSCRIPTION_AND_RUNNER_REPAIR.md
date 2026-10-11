# Calendar subscription isolation and child import repair

The imported iOS 26.5 environment contains an active Subscribed Calendars store. For `ios.calendar.update_and_create_followup`, Calendar asynchronously restored 122 US Holidays entries after the initializer seeded three task events. Deleting the subscription calendar row was insufficient: the system recreated it. This contaminated attempt 001, which is excluded from model scores.

The task initializer now explicitly disables only the subscribed-calendar store before purging and seeding events. Both exact-count Calendar tasks now opt into this isolation; other tasks retain their existing initialization. The evaluator remains unchanged: exactly four requested events, exact fields, and unchanged unrelated events are required. A real simulator preflight produced three seed events and correctly failed evaluation. Independent references passed for correct completion and failed with an extra event or a changed description on the preserved Pharmacy event.

Attempt 002 failed before initialization or any model request. An inherited relative `PYTHONPATH=.` caused the direct CLI subprocess to import the platform-local `core` package instead of repository `core.artifacts`. The runner now prepends the absolute repository root and discards relative inherited path entries. A safe CLI probe reproduced the original import failure and reached the expected nonexistent-task error after removing the relative path. This attempt is also excluded.

Regression validation: 79 tests and 5 subtests passed across Calendar semantics, subscribed-store isolation, child path handling, and the author queue. Real iOS 26.5 final preflight: initializer PASS; initial evaluator FAIL; exactly three events. Evidence and excluded attempts are published in the author evaluation release; manifests carry SHA256 digests. These fixes do not relax evaluation or convert excluded attempts into successes.

Evidence release: https://github.com/BaoZhuhan/os-omni/releases/tag/author-eval-2026-10-11

Excluded artifacts:
- `ios.calendar.update_and_create_followup.environment-excluded.attempt_001.tar.gz`, SHA256 `f5832f9064c6a572f5b92b2de6208a17357b15fe5dd5a0167f8733d8818aa913`.
- `ios.calendar.update_and_create_followup.environment-excluded.attempt_002.tar.gz`, SHA256 `eab1a57a4c4e74be099aabc9c82ed3653095254c0cad503be68940965bbdcc2b`.

Reset policy: dispose of audit simulators after checks, retain the imported source baseline, and use one fresh formal clone at a time. Only DeepSeek performs formal task actions.

## Cross-task audit correction

A full-database reinspection of `ios.calendar.finalize_schedule_with_two_followups` attempt 002 found 125 events (three unchanged task drafts and 122 holiday subscription events), including its WAL state. The earlier audit had inspected task rows without checking the global count. Its published model-failure classification is superseded by an environment exclusion; it is removed from valid model scores and requires repair/retest. The original artifact remains immutable for provenance. The replacement artifact is `ios.calendar.finalize_schedule_with_two_followups.subscription-excluded.attempt_002.tar.gz`, SHA256 `61fd675856ff05ac8e91821bb81223df0922b116bec9fbbb3e941a204264355d`.

The child import repair needed an additional CLI bootstrap fix: when the root was already present later in `sys.path`, conditional insertion left the platform-local `core` first. The CLI now always promotes the root. A real subprocess regression reaches the expected nonexistent-task error, before constructing a controller or model. Update task attempt 003 is excluded for this pre-model error; artifact SHA256 `c7e292d83bcbe2583f8c9bc7f84c26295ea83874d5c3f48fd705c7cb21e20e39`.

After the cross-task audit, the finalize task received the same subscription-store isolation. Its real iOS preflight passed with exactly three seeds and initial evaluator FAIL. Independent native references passed for correct four-event completion and failed for an extra event, changed preserved-event description, and wrong time. The portable checker is `scripts/author_calendar_reference_check.py`; run with `--task finalize --udid <disposable-audit-simulator> --output <new-output-directory>`. It restores initial seeds after checks and must never operate on a formal run simulator.

## Attempt directory identity

When historical manual runs existed but the queue counter was zero, the queue reused `attempt_001` as a parent directory. Timestamped run directories stayed distinct, but parent-level bookkeeping could become ambiguous. Allocation now takes the maximum of the recorded counter and all occupied numeric attempt paths, then creates a new directory exclusively. Regression checks include stale counters, occupied files, unrelated names, and the complete queue suite: 54 tests and 5 subtests passed. Current finalize retest preserves its original timestamped evidence; after completion it is relocated to the distinct logical third attempt with an explicit mapping. This bookkeeping correction does not change task semantics, runtime actions, or evaluation.
