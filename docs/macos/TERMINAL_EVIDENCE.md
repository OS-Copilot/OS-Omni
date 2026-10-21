# macOS Terminal / Final-State Evidence Capture

Opt-in, administrative post-run evidence collection for the macOS benchmark
runner (`platforms/macos/host/runners/benchmark.py`), analogous to the iOS
final-state capture (`OS_OMNI_CAPTURE_IOS_FINAL_STATE`).

> Status: implemented with unit/mock coverage. **Actual live-VM validation is
> pending** — the capture path has not yet been exercised against a real
> booted macOS guest.

## Enablement

Disabled by default. Opt in per benchmark invocation:

```bash
OS_OMNI_CAPTURE_MACOS_FINAL_STATE=1 <benchmark command>
```

Any other value (including unset) disables capture completely: no guest
calls are made and no `final_state/` directory is created.

## When it runs

After the per-run child process has **stopped** (success, failure, or
crash/exception) and **before** ephemeral-clone cleanup, so the clone's
guest state still exists. Ordering per run:

1. Child process stops; its terminal output stays in the runner log.
2. Final-state capture runs (guest is still up).
3. Clone cleanup runs.

Capture failure is recorded in the manifest/runner log and **never alters
the run verdict**: `success` / `return_code` pass through untouched, and a
crashed child still raises after capture + cleanup.

## What is collected

All collection is read-only through the supported, authenticated guest APIs
(`VMRuntimeController`: `/health`, `/version`, `/device_info`,
`/screenshot`, `/setup/execute`, `/run_python`, `/file`). The auth token is
never logged and never stored in the manifest or archive.

- **Final screenshot** (`final_screenshot.jpg`) via `GET /screenshot`.
- **Health / version / device info** via `/health`, `/version`,
  `/device_info`, sanitized to JSON-safe structures.
- **Task-bound files**: absolute guest paths taken only from the task
  YAML's `evaluation.params` / `init.params` (`*_path`, `*_file`,
  `*_dir`, `*_folder`, `path`, `open_file`, `db_path`) and restricted to
  `/Users/bench/Downloads`, `/Users/bench/Documents`,
  `/Users/bench/Desktop`, `/tmp`, `/private/tmp`.
- **Task-bound native stores only**: Photos `Photos.sqlite`,
  Thunderbird `calendar-data/local.sqlite` (via a fixed, static discovery
  probe capped at 4 profiles), Contacts `AddressBook-v22.abcddb`, and the
  Reminders store — each **only** when the task id / evaluator id / explicit
  `db_path` binds it to the task. SQLite `-wal` / `-shm` / `-journal`
  sidecars are fetched alongside their DB; Photos originals are never
  collected.

## What is never collected

- Keychains, secrets, credentials, `.env`, SSH keys, caches, cookies, and
  symlinks are excluded by name, component, and `lstat` checks; exclusions
  are recorded as `skipped` entries.
- No recursive home/archive of the VM: paths outside the allowlist
  (including `/Users/bench` itself, `~/.ssh`, `/etc`) are rejected with
  `path-not-allowed` **before any guest call**.
- Guest paths travel as subprocess **argv** (`/setup/execute` list form) or
  as `/file` / `/run_python` parameters; they are never interpolated into
  shell strings or probe code. The stat and Thunderbird-discovery probes are
  fixed strings.
- Binary payloads are hashed (SHA256), never embedded as base64 and never
  written to logs.

## Bounds

- Per file: 32 MiB (`MACOS_FINAL_STATE_MAX_FILE_BYTES`).
- Total: 128 MiB (`MACOS_FINAL_STATE_MAX_TOTAL_BYTES`).
- File count: 32 (`MACOS_FINAL_STATE_MAX_FILES`).
- Oversized/over-budget files are recorded as `skipped`
  (`file-size-exceeded`, `total-budget-exceeded`, `file-count-exceeded`),
  never silently dropped.

## Output layout

Under the run's model output directory:

```text
final_state/
  final_screenshot.jpg
  final_state.tar.gz   # staged task_files/... + native/... members
  manifest.json        # per-file SHA256/sizes, archive SHA256, skipped, errors
```

The manifest is tagged administrative-only:

```json
{
  "evidence_kind": "administrative-final-state",
  "for_decision_system": false
}
```

**Guest administrative collection is separate tagged evidence and is never
passed to the decision/scoring system.** Task semantics and scores are
untouched; the run record only gains a `final_state` pointer to the
manifest.

## Tests

`tests/test_macos_terminal_evidence.py` (fully mocked, no VM/GUI/network):

- Disabled flag and missing runtime URL make zero guest calls.
- Capture runs before cleanup; failed-child terminal output is preserved.
- Crashed child still captures, then cleans up, then re-raises.
- Capture errors keep PASS/FAIL verdicts.
- Credential/cache/symlink exclusion and allowlist rejection without guest
  calls; shell-special filenames travel as argv only.
- Per-file/count limits, per-file and archive SHA256, missing-state
  (`missing`) and WAL/SHM reporting.
- Token absence from manifest and runner log.
