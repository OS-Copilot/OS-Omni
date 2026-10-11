# Local GreenMail admin evidence (read-only, terminal)

Admin-only terminal evidence for locally isolated GreenMail 2.1.14 tasks,
captured before the next initializer purge. This document is the integration
contract; the helper is `core.evidence.local_mail`. No runner is implemented
here by design.

## Scope and prohibitions

- Read-only HTTP GET against the official installed schema
  `GreenMail GET /greenmail-openapi.yml` (GreenMail 2.1.14), restricted to
  `GET /api/user/{emailOrId}/messages/{folderName}` (carries `mimeMessage`).
- Never call `GET /api/user` (exposes passwords), never POST/DELETE
  (`/api/service/reset`, `/api/mail/purge`, user create/delete).
- Base URL must be explicit loopback only: `http://127.0.0.1[:port]` or
  `http://localhost[:port]`. Non-local hosts, credentials in URL, and
  non-HTTP schemes are rejected with `ValueError` before any I/O.
- Only explicit fake `.test` users/folders from task params. No user
  enumeration, no guessing.
- No GUI/device/VM operation, no GreenMail reset, no `.env`/keychain reads.
- Errors are recorded in `manifest["errors"]` and never affect PASS/FAIL.
- Output goes only to the dedicated admin evidence directory
  `<model_output_dir>/local_mail_evidence/` (raw JSON, raw `.eml`, and
  `manifest.json`), never into the model prompt.
- Omitted from all artifacts: request/response headers, passwords, API keys,
  tokens.
- No commits/push from this change (helper + tests + this doc only).

## Source task/eval parameter discovery (no guessing)

Maily 3.x (`ios.maily.instruction_3_1/3_2/3_3`, task files
`tasks/v1/ios/maily_instruction_3_*.yaml`):

1. Read the task file's `evaluation.params` via
   `discover_task_eval_params(task_file)` → gives `api_base_url`
   (default `http://127.0.0.1:8081` in
   `evaluators/ios/maily_instruction_3_1.py`), `timeout_seconds`,
   `poll_interval_seconds`.
2. Read the matching evaluator's `CHECKPOINT_SPECS[*]["mailbox"]` and pass
   them to `discover_maily_targets(specs)` → explicit
   `benchsender@example.test`, `benchrecv@example.test`, `planbox@mail.test`
   with folder `INBOX` (the evaluator's `_fetch_mailbox_messages` default).
   Any non-`.test` mailbox raises instead of being queried.

DeltaChat 4.x (`ios.deltachat.*_saved_messages_4_*`, task files
`tasks/v1/ios/deltachat_*_4_*.yaml`): evaluation is bound-`dc.db`-first
(`minimum_message_id`, `baseline_max_timestamp`, `sent_state`), not GreenMail.
Only add a GreenMail target here if a future DeltaChat evaluator declares an
explicit `api_base_url` plus explicit `.test` users in its task params; the
helper takes those explicit targets as-is and still refuses to enumerate.

## Parent integration

The iOS parent runner calls the task-bound helper
in the parent process at exactly this point:

1. Model child process has stopped (success, failure, or crash; terminal
   output already preserved).
2. **Then** — if `OS_OMNI_CAPTURE_LOCAL_MAIL=1` — call
   `maybe_capture_local_mail_evidence(base_url=<explicit task api_base_url>,
   targets=<explicit .test targets>, output_dir=<run model_output_dir>)`.
3. **Then** run existing cleanup / next-task initializer (which purges mail).

The helper writes `<model_output_dir>/local_mail_evidence/`:

- `<user>__<folder>.json` — bounded raw mailbox JSON (truncated flag when the
  `max_response_bytes` cap, default 32 MiB, is hit).
- `<user>__<folder>__uid-<uid>.eml` — bounded raw MIME per message
  (`max_mime_bytes` cap, default 8 MiB, per-file truncation flagged).
- `manifest.json` — `{evidence_kind, for_decision_system:false,
  greenmail_schema, greenmail_version:"2.1.14",
  endpoint:"GET /api/user/{emailOrId}/messages/{folderName}",
  captured_at_utc, base_url_host, targets, mailbox_message_counts,
  files:[{path, sha256, size, truncated, uid?, messageId?, subject?,
  contentType?}], errors:[{target, reason}]}`.

Bounds: at most `max_targets` (default 16) targets per call; HTTP timeout
default 5 s. Verification: `pytest tests/test_local_mail_evidence.py` from
the repository root (fully mocked, no live server). A live read-only check
against existing fake GreenMail, if ever needed, is a plain GET of one known
`.test` mailbox URL and must never print bodies or credentials.

Live GreenMail 2.1.14 smoke validation captured seven untouched inbound seed messages and an empty recipient mailbox, with all nine artifact hashes verified. Bounds cover image MIME payloads (32 MiB per mailbox, 8 MiB per message); larger evidence is explicitly marked truncated. Maily 3.2 declares recipients using the recipient key, while 3.1/3.3 use mailbox; task-bound tests cover all three actual contracts.
