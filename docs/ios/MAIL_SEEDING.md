# Maily baseline seeding guide (three live tasks)

Per-task reproducible seeder for `ios.maily.instruction_3_1`,
`ios.maily.instruction_3_2`, `ios.maily.instruction_3_3`. New code:

- `initializers/ios/maily_benchmark_seed.py` — seed specs + `MailyBenchmarkSeedInitializer`.
- `scripts/prepare_maily_assets.py` — FSNotes/photo asset resolver with hash verification.
- `tests/test_maily_benchmark_seed.py` — isolated mocked coverage (28 tests, all mock HTTP; no live server).

Task YAML wiring is left to root after review; this document specifies the
intended wiring and the safety rules around it.

## 1. What is seeded (and what is never seeded)

Only initial inbound messages: the mails the agent must find in the
sender-visible store before step 1. Every seed is delivered to the sender
mailbox `alex.rivera@example.test`; reply-source seeds carry their original
sender (the reply checkpoint mailbox from `TARGET_SPECS`, e.g.
`benchsender@example.test`) as `From`, so the app's Reply is addressed to the
graded mailbox. Each seed carries the original evaluator identity as its
`Message-ID` plus a `Seed body for <Subject>.` text line (the quoted-body
convention the 3_2/3_3 verifiers require).

| Task | Seeds (subject → Message-ID) |
|---|---|
| 3_1 (7) | AlphaReply0708 → `<baseline-23-…>`, AlphaFwd0708 → `<baseline-24-…>`, AlphaRead0708 → `<baseline-22-…>`, AlphaBulkA → `<baseline-26-…>`, AlphaShare0708 → `<baseline-28-…>`, AlphaBulkB → `<baseline-27-…>`, AlphaTrash0708 → `<baseline-25-…>` (full fragments in `SEED_SPECS`) |
| 3_2 (7) | RouteFwd0708 / RouteBulkA / RouteReply0708 / RouteBulkB / RouteShare0708 / RouteRead0708 / RouteTrash0708; IDs minted as `<baseline-N-<slug>-alex.rivera@example.test@example.test>` (see §4) |
| 3_3 (5) | FieldRead0708 → `<baseline-15-…>`, FieldFwd0708 → `<baseline-18-…>`, FieldReply0708 → `<baseline-17-…>`, FieldShare0708 → `<baseline-21-…>`, FieldTrash0708 → `<baseline-16-…>` |

NEVER seeded: the agents' final sent (target completion) messages — the 10/9/9
`Re:`/`Fwd:`/compose outputs in `TARGET_SPECS`. They start nonexistent each
run; the original evaluators verify them. Tests assert the seed and target
subject sets are disjoint and every reply/forward target links to a seed.

Seed `Date` values use the stable `SEED_BASE_DATE` (2026-07-08 08:00 UTC plus
per-seed minute offsets), so seeds always predate any run window anchored at
`args.json.created_at`, and per-mailbox UID order is deterministic.

## 2. Intended initializer wiring (for root review)

Per task YAML `init.params` (values illustrative; secrets via environment):

```yaml
init:
  initializer_id: initializers.ios.maily_benchmark_seed:MailyBenchmarkSeedInitializer
  params:
    task_id: ios.maily.instruction_3_1   # one of the three live ids
    sender_password_env: MAILY_SEED_PASSWORD
    greenmail_reset_confirmed: true      # set ONLY by the root initializer/CLI
    api_base_url: http://127.0.0.1:8081
    smtp_host: 127.0.0.1
    smtp_port: 3025
```

Run order per task: readiness GET → `POST /api/mail/purge` →
`purge_maily_local_state` (delegated, preserves configured accounts) →
user provisioning (`GET /api/user` then `POST /api/user` for missing
sender + that task's recipients only; existing users preserved;
recipient INBOXes verified empty) → SMTP seed of that task's inbound
set → read-only REST verification (each seed subject + Message-ID
exactly once) → foreground Maily on iOS.

Provisioning contract (GreenMail 2.1.14 live OpenAPI): `GET /api/user` lists users,
`POST /api/user` with JSON `{"email", "login", "password"}` creates one
(`login == email`). The seeder provisions the sender plus
`recipients_for(task_id)` from `TARGET_SPECS` — only the initially
selected task's recipients, never unrelated tasks' mailboxes — using the
caller-supplied fake-account password already resolved from
`sender_password` / `sender_password_env`. Passwords are never logged,
stored, or returned (results carry only address lists plus
`password_provided: bool`). Any provisioning failure (list/create/empty
check) aborts before SMTP and surfaces as `ERROR`. This fixes the
observed probe failure where the seeder passed SMTP (`PASS`) but the
initial evaluator errored (`ERROR GET benchrecv@example.test HTTP 400`)
because the recipient user did not exist.

## 3. Safety rules

- Host GreenMail reset ONLY when invoked by the root initializer/CLI **and**
  no competing formal mail task is running. The code gate is
  `greenmail_reset_confirmed=True`; without it the initializer fails before
  any network call. The reset purges the isolated local fake accounts only —
  no simulator, app-container, GUI, or process operations.
- Maily remains on iOS: UDID/container health checks stay applicable and are
  untouched by this change.
- Passwords are never logged, stored, or returned — including across
  provisioning: `POST /api/user` bodies carry the secret on the wire only;
  results carry only `{email, password_provided: bool}` plus the
  non-secret `provision_result` (`needed`/`created`/`preserved` address
  lists). No Maily preferences key names are assumed; all local-state
  handling is delegated to `greenmail_local_state`.
- Reused as-is, not forked: `greenmail_seed_open_app.py` (SMTP/purge
  patterns), `greenmail_open_app.py` (readiness/purge), `greenmail_local_state.py`
  (local purge). Only exact `Message-ID`/`Date` seed construction is new.

## 4. Assets: FSNotes + photos

`scripts/prepare_maily_assets.py` resolves the 3 live-task FSNotes files and
6 live-task photos against the byte-exact evaluator hashes. It reads ONLY the
caller-selected `--source` tree (official simulator archive / extracted
container chosen by the caller); actual filesystem extraction from official
app containers is handled by root. No private directories are required or
assumed. Orphaned 3_4 hashes are listed with `--include-orphan` as seek-only
references; they are never wired to a task. If an original cannot be
recovered, re-minting requires updating the evaluator constant AND the
yaml `expected_ruleset_sha256` together — never weakening the hash checks.

## 5. Remaining uncertainties (candid)

1. 3_2 exact original Message-IDs are not recorded in the evaluator (only
   `source_reference` substrings); seed IDs are convention-minted. Any ID
   containing the reference satisfies the verifier, but byte-identity with
   the historical baseline is unverified.
2. Reply-source seed `From` addresses are derived from the evaluators' reply
   checkpoint mailboxes (`TARGET_SPECS` `kind: "reply"`), while delivery stays
   in the agent mailbox; non-reply seeds remain self-addressed. No evaluator
   pins the seed `From` header directly, only the target reply's recipient.
3. The recovered-photo manifest and copies are root-provided and were not
   opened here; hash acceptance runs in `prepare_maily_assets.py` at
   extraction time.
4. FSNotes attachments for the three live tasks are resolved: root's
   exact-hash search of the official FSNotes container confirms all three
   live-task originals byte-exact (`Sprint Review Draft.md`, `Shipping
   Notes.md`, `Team Contacts.md`); no MD assets are missing for 3_1–3_3.
   Only the orphaned 3_4 row stays seek-only (no task wiring, no seeding).
5. GreenMail user provisioning is now owned by the seeder (this change);
   the pre-configured Maily IMAP account in the iOS snapshot stays a
   root-owned prerequisite outside this change. `ALL_TARGET_RECIPIENTS`
   remains as the cross-task inventory for root review; per-run
   provisioning uses only `recipients_for(task_id)`.
...[truncated 4057 chars]