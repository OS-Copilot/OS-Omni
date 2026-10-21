# iOS Maily Mail-Environment Audit (read-only, no code changes)

- Scope: this document only. File created at `docs/ios/MAIL_ENVIRONMENT_AUDIT.md`. No other source reverted or edited.
- Method: static reads of current `tasks/v1/ios/maily_*.yaml`, imported `evaluators/ios/maily_*.py` + helpers, actual 48-task main (`tasks/v1/ios/*.yaml` + `executions/v1/ios.yaml`), GreenMail/initializer helpers. No model/API calls, no GUI, no simulators, no pushes, no DS output.
- Live formal Contacts on desktop was not operated.
- Root-provided facts taken as given (not re-verified by operating services): GreenMail `2.1.14` official verified JAR, OpenJDK 21, `SMTP 127.0.0.1:3025`, `IMAP 3143`, API `8081` now healthy; services were not in VM. Root fixed runner init to write UTC `args.json.created_at` before task init and evaluator context to include `run_dir` + trajectory path. Those files were read, not edited.

## 1. Task inventory: 3 live + 1 orphaned evaluator

- Actual task main is 48 files: `ls tasks/v1/ios/*.yaml | wc -l` = 48; `executions/v1/ios.yaml` lists 48 entries.
- Only three Maily yamls exist:
  - `tasks/v1/ios/maily_instruction_3_1.yaml` (`ios.maily.instruction_3_1`)
  - `tasks/v1/ios/maily_instruction_3_2.yaml` (`ios.maily.instruction_3_2`)
  - `tasks/v1/ios/maily_instruction_3_3.yaml` (`ios.maily.instruction_3_3`)
- `executions/v1/ios.yaml` lines 16–18 list exactly those three. There is **no** `tasks/v1/ios/maily_instruction_3_4.yaml` and no execution entry for it.
- But `evaluators/ios/maily_instruction_3_4.py` (`ios.maily.instruction_3_4`, `MailyInstruction34StateEvaluator`) exists and is a full fourth Maily semantic. It is currently unrunnable through the 48-task main. Audit covers all four semantics; do not treat the orphan as deleted.
- Legacy-only reading is insufficient: each yaml carries `metadata.cua_tasks_review.source_instruction` (76 Chinese UI steps) plus a rewritten English `instruction`, plus `evaluation.params` (`api_base_url`, `expected_ruleset_sha256`, windows/profiles). The English instruction + evaluator `CHECKPOINT_SPECS`/`MESSAGE_SPECS` are authoritative for seeding, not the step prose alone.
- Current initializers for all three live tasks are the launch-only `evaluators.cua_review.initializers.ios.maily_open_app:MailyOpenAppInitializer` (bundle `de.enough.maily`, snapshot `osomni-opendriver-ios-source-fixed-promax`, `wait_ms 800`). Source: `evaluators/cua_review/initializers/ios/maily_open_app.py`. They write no mail data. So every seed account/folder/message must come from a separate reproducible seeding layer (see §5).

## 2. Required initial state per Maily semantic (source-linked)

Common sender account: all four evaluators require `From == alex.rivera@example.test` on every durable output (`SENDER` / `SENDER_EMAIL`). This is the Maily account that must be configured before seeding. `3_4` additionally requires its display name to be `Incident Desk` (see account row below).

### Table 1 — seeds that must pre-exist (folders, subjects, provenance)

| Task | Seed subjects that must be in the sender-visible store before step 1 | Seed identity the verifier binds | Folders / files / photos the seed step assumes |
|---|---|---|---|
| 3_1 (`maily_instruction_3_1.yaml` + `maily_instruction_3_1.py`) | `AlphaReply0708`, `AlphaFwd0708`, `AlphaRead0708`, `AlphaBulkA`, `AlphaShare0708`, `AlphaBulkB`, `AlphaTrash0708` (7 seeds; 3 composes have no seed) | `source_message_id_fragment` per checkpoint, e.g. `baseline-23-alphareply0708-alex.rivera@example.test@example.test`, `baseline-24-alphafwd0708-…`, `baseline-22-alpharead0708-…`, `baseline-26-alphabulka-…`, `baseline-28-alphashare0708-…`, `baseline-27-alphabulkb-…`, `baseline-25-alphatrash0708-…`; bound via `In-Reply-To` / `References` / quoted original | FSNotes folder with `Sprint Review Draft.md`; photo grid containing uniformed-person-holding-gun thumbnail (top-middle, `source_asset IMG_0080.JPG`) |
| 3_2 (`maily_instruction_3_2.yaml` + `maily_instruction_3_2.py`) | `RouteFwd0708`, `RouteBulkA`, `RouteReply0708`, `RouteBulkB`, `RouteShare0708`, `RouteRead0708`, `RouteTrash0708` (7 seeds; 2 composes have no seed) | `source_reference` + quoted `Seed body for <Subject>.`, e.g. `baseline-1-routefwd0708`, `baseline-4-routebulka`, `baseline-3-routereply0708`, `baseline-5-routebulkb`, `baseline-7-routeshare0708`, `baseline-2-routeread0708`, `baseline-6-routetrash0708` | FSNotes folder with `Shipping Notes.md`; clown photo (row 1 col 1: white face, red nose, green hair); blue-electric-guitar close-up (row 4 col 1) |
| 3_3 (`maily_instruction_3_3.yaml` + `maily_instruction_3_3.py`) | `FieldRead0708`, `FieldFwd0708`, `FieldReply0708`, `FieldShare0708`, `FieldTrash0708` (5 seeds; 4 composes have no seed) | Exact `source_message_id`, e.g. `<baseline-15-fieldread0708-alex.rivera@example.test@example.test>`, `<baseline-18-fieldfwd0708-…>`, `<baseline-17-fieldreply0708-…>`, `<baseline-21-fieldshare0708-…>`, `<baseline-16-fieldtrash0708-…>`; `_check_seed_messages` requires these exact IDs in `alex.rivera@example.test` mailbox; per-message `In-Reply-To`/`References` must equal the normalized ID and body must contain the source subject | FSNotes list with `Team Contacts.md`; airport-entrance group selfie; two-people-holding-orange-boxes; multiple-people-cooking-around-table |
| 3_4 (`maily_instruction_3_4.py` only; no yaml) | `OpsReply0708`, `OpsFwd0708`, `OpsRead0708`, `OpsBulkA`, `OpsShare0708`, `OpsBulkB`, `OpsTrash0708` (7 seeds; 3 composes have no seed) | `source_message_id_fragment`, e.g. `baseline-8-opsreply0708-…`, `baseline-9-opsfwd0708-…`, `baseline-12-opsread0708-…`, `baseline-10-opsbulka-…`, `baseline-14-opsshare0708-…`, `baseline-11-opsbulkb-…`, `baseline-13-opstrash0708-…` (note: trash fragment in code reads `baseline-13-opstrash0708`, missing `p` — preserve exactly) | FSNotes file `Mobile Gates Gates.markdown`; clown photo; young-man photo |

Mailbox seeding target: GreenMail user `alex.rivera@example.test` (all seeds), because `3_3._check_seed_messages` reads `mailboxes[SENDER_EMAIL]` and all reply/forward provenance ultimately resolves against that mailbox. Recipient mailboxes (`benchsender`, `benchrecv`, `planbox`, `field3`, `rein`, `rain`, `benchchat`, `ops4`) are outputs, not seeds — they must exist as GreenMail users so delivery succeeds, but start empty each run (purge then seed).

### Table 2 — durable outputs the verifier requires (exact subjects/bodies/attachments)

3_1 — 10 outputs, order `[7,15,23,28,37,45,54,63,68,76]`, `MAILBOX = to`, `FROM = alex.rivera@example.test`:

| # | Expected `To` | Expected `Subject` | Authored body | Attachment |
|---|---|---|---|---|
| 1 | `benchsender@example.test` | `Re: AlphaReply0708` | `Gate one is open.` | none |
| 2 | `benchrecv@example.test` | `Alpha gate opened` | `Review has begun` | none |
| 3 | `planbox@mail.test` | `Fwd: AlphaFwd0708` | empty | `Sprint Review Draft.md`, `application/octet-stream`, sha256 `a0869ffd…` (see §3) |
| 4 | `benchsender@example.test` | `Re: AlphaRead0708` | `Crew is ready now` | none |
| 5 | `planbox@mail.test` | `Fwd: AlphaBulkA . batch-1` | `Batch A is kept` | none |
| 6 | `benchrecv@example.test` | `Alpha gate midway` | `Two checks passed` | none |
| 7 | `benchsender@example.test` | `Re: AlphaShare0708` | `Share is approved.` | photo `image/jpeg`, filename ignored, sha256 `97d5ae…`, `source_asset IMG_0080.JPG` |
| 8 | `planbox@mail.test` | `Fwd: AlphaBulkB . batch-b` | `Batch B is kept.` | none |
| 9 | `benchsender@example.test` | `Re: AlphaTrash0708` | `Purge is deferred.` | none |
| 10 | `planbox@mail.test` | `Alpha record index` | `Proofs are filed` | none |

3_2 — 9 outputs, durable steps `[8,17,26,34,43,51,60,67,76]`, strictly increasing MIME `Date`:

| # | `To` | `Subject` | Body rule | Attachment |
|---|---|---|---|---|
| 1 | `field3@mail.test` | `Fwd: RouteFwd0708` | no body-text requirement (`body None`; must still carry quoted `Seed body for RouteFwd0708.`) | `Shipping Notes.md`, sha256 `36e924…` |
| 2 | `field3@mail.test` | `Fwd: RouteBulkA · follow up` | starts with `Batch A moved on.` | none |
| 3 | `benchsender@example.test` | `Re: RouteReply0708` | starts with `Crew took the leg.` | clown photo, filename ignored, sha256 `b62370…` |
| 4 | `rein@mail.test` | `Route relay midway` | starts with `Three legs cllosed.` (sic, double-l) | none |
| 5 | `field3@mail.test` | `Fwd: RouteBulkB · check tomorrow` | starts with `Batch B moved on.` | none |
| 6 | `rain@mail.test` | `Route depot note` | starts with `Depot is stocked.` | none |
| 7 | `field3@mail.test` | `Fwd: RouteShare0708 · share-pack` | starts with `Share pack passed.` | none |
| 8 | `benchsender@example.test` | `Re: RouteRead0708 · read-log` | starts with `Log was reviewed.` | none |
| 9 | `field3@mail.test` | `Fwd: RouteTrash0708` | no body-text requirement | guitar photo, filename ignored, sha256 `3a3fda…` |

3_3 — 9 outputs, durable steps `[8,16,25,33,42,50,58,67,76]`, `body_mode` matters (`exact` vs `prefix` vs `contains`):

| # | `To` | `Subject` | Body mode + text | Attachment |
|---|---|---|---|---|
| 1 | `benchsender@example.test` | `Re: FieldRead0708` | prefix `Scan log was read.` | file `Team Contacts.md`, `application/octet-stream`, sha256 `8015c5…` |
| 2 | `ops4@mail.test` | `Field crew roster` | exact `Crew list is set.` | none |
| 3 | `benchchat@example.test` | `Fwd: FieldFwd0708` | contains `Seed body for FieldFwd0708.` | photo `image/jpeg` label `机场入口多人自拍`, sha256 `b7eba2…` |
| 4 | `ops4@mail.test` | `Field water note` | exact `Wells are marked.` | none |
| 5 | `benchsender@example.test` | `Re: FieldReply0708` | prefix `Depths check out.` | photo label `两人手持橙色箱子`, sha256 `8b1c7c…` |
| 6 | `ops4@mail.test` | `Field soil note` | exact `Soil set is filed.` | none |
| 7 | `ops4@mail.test` | `Field safety brief` | exact `Rules were issued.` | none |
| 8 | `benchsender@example.test` | `Re: FieldShare0708` | prefix `Share was granted.` | photo label `多人围桌烹饪`, sha256 `a61cd4…` |
| 9 | `benchchat@example.test` | `Fwd: FieldTrash0708 . retain` (wire; instruction suffix ` · retain`, Maily build-96 serializes middle dot as ASCII dot) | prefix `Keep this record.` | none |

3_4 — 10 mail outputs + 1 account checkpoint, 76 steps, durable mail steps `[11,19,27,32,40,49,57,62,71,76]`, account steps `[1,5]`:

| Checkpoint | `To` / target | `Subject` / name | Body | Attachment |
|---|---|---|---|---|
| account | `accts` record email `alex.rivera@example.test` | name `Incident Desk` | — | — |
| 1 | `benchsender@example.test` | `Re: OpsReply0708` | `Fix is deployed.` | none |
| 2 | `benchrecv@example.test` | `Ops incident log` | `Timeline is filed.` | none |
| 3 | `rain@mail.test` | `Fwd: OpsFwd0708` | empty | `Mobile Gates Gates.markdown`, `application/octet-stream`, sha256 `7d1cef…` |
| 4 | `benchsender@example.test` | `Re: OpsRead0708` | `Alert was triaged.` | none |
| 5 | `benchrecv@example.test` | `Ops root cause` | `Cause was found.` | none |
| 6 | `benchsender@example.test` | `Re: OpsBulkA` | `Backlog A cleared.` | clown photo sha256 `c70ca0…` |
| 7 | `benchrecv@example.test` | `Ops watch handoff` | `Desk takes over.` | none |
| 8 | `benchsender@example.test` | `Re: OpsShare0708` | `Access restored.` | none |
| 9 | `rain@mail.test` | `Fwd: OpsBulkB` | empty | young-man photo sha256 `61b82f…` |
| 10 | `benchsender@example.test` | `Re: OpsTrash0708` | `Do not purge yet.` | none |

Thread rules preserved: replies/forwards must carry `In-Reply-To`/`References`/quoted-original binding to the exact seed; composes must carry no thread headers and no quoted-original masquerade. Unique-match-required (exactly one fully valid match per checkpoint), same-mailbox UID strictly increasing, global parsed-Date strictly increasing.

## 3. Hardcoded old hashes incompatible with naive reconstruction

Every file/photo attachment hash below is enforced byte-for-byte (`attachment SHA-256 mismatch` / `missing attachment`). Rebuilding with same filename but different bytes fails. Do not "relax" these without task-semantic grounds.

| Task | Constant in evaluator | Filename / kind | Content-Type enforced | Full SHA-256 |
|---|---|---|---|---|
| 3_1 | `FILE_SHA256` | `Sprint Review Draft.md` | `application/octet-stream` | `a0869ffd08ca7775b3e0125272e89ae2559ecae652e413e24e319e921b52c891` |
| 3_1 | `PHOTO_SHA256` (`source_asset IMG_0080.JPG`) | photo, filename ignored | `image/jpeg` | `97d5ae0cb9f81db777d09af3240980ba588d7a551902e1662bef1d54bb5522fd` |
| 3_2 | `SHIPPING_NOTES_SHA256` | `Shipping Notes.md` | (via `_attachment_summaries`; filename+hash) | `36e924648e96f5608e189c92d30f19b2780438730b44b5d975d96fffa8c35b60` |
| 3_2 | `CLOWN_PHOTO_SHA256` | photo, filename ignored | image part | `b6237067e7ca26eb618ca8f8d4cb7b09bb931ac8c2e5cdf2928146bbd9c5ad91` |
| 3_2 | `GUITAR_PHOTO_SHA256` | photo, filename ignored | image part | `3a3fda010a1c08174c0866c1135194eabcbdd38fc4278f451186af72f90043d1` |
| 3_3 | `TEAM_CONTACTS_SHA256` | `Team Contacts.md` | `application/octet-stream` | `8015c51c4036b70ac1231b0bc6f38d43231039eac3ea7bfc6a0ccc9bec52565e` |
| 3_3 | `AIRPORT_SELFIE_SHA256` | airport-selfie photo | `image/jpeg` | `b7eba2f33fb661b273a5a7b311fe220efd925dddd4536e2175332e3d06d04faf` |
| 3_3 | `ORANGE_BOXES_SHA256` | orange-boxes photo | `image/jpeg` | `8b1c7cf4f3639b62f811cddcfce0471b8d2ae240dd14ddeae0a8fc647bf23815` |
| 3_3 | `TABLE_COOKING_SHA256` | table-cooking photo | `image/jpeg` | `a61cd4fbf7687f24fe4024cf3459c838267fe33cce6bb95106148f0e8c8ec963` |
| 3_4 | `FILE_SHA256` | `Mobile Gates Gates.markdown` | `application/octet-stream` | `7d1cef45a68f9ff199d6c78429f5973a8644082ad82e73c9c59c9b7ab8f1dc05` |
| 3_4 | `CLOWN_PHOTO_SHA256` | clown photo | `image/jpeg` | `c70ca0ab1b961103079b3ef5fcc520804d2ede1d0660a39d029d375ae0d9760a` |
| 3_4 | `YOUNG_MAN_PHOTO_SHA256` | young-man photo | `image/jpeg` | `61b82f396615c18bb517fbb6572a9f805a09ad4c252c51147e5127469ca5650a` |

Consequence: equivalent reconstruction must either recover the exact original bytes (preferred) or mint new bytes and update the corresponding evaluator constant + `expected_ruleset_sha256` in the yaml together (ruleset digest covers the hash). The second path changes the benchmark contract and needs explicit task-owner approval; it is not a silent fix. See §6 provenance/hash approach.

## 4. Authoritative original-source fixtures available (read-only, no re-upload dependency)

- GreenMail artifact (root, verified): `../shared/greenmail/greenmail-standalone-2.1.14.jar` + `.sha256` (`0381392f…`), `../records/greenmail-artifact.json` (`version 2.1.14`, maven source URL, size 10976828). Prefer this JAR over `scripts/start_greenmail.sh` defaults (which pin container `greenmail/standalone:2.1.8` and a `GREENMAIL_USERS` list that omits all Maily mailboxes below).
- Mail seed identities: authoritative only in the four evaluators (§2 Table 1: exact `Message-ID`/fragments + `Seed body for <Subject>.` convention in 3_2/3_3). No committed `.eml` fixtures for Maily seeds were found; `grep` for the four FSNotes filenames across `local_eval/ tools/ scripts/ platforms/` returns no hits. Do not rely on missing history/user re-upload.
- FSNotes mechanism (authoritative): `platforms/ios/fsnotes_store.py` (`FSNotesStore`, bundle `co.fluder.mobile.FSNotes-iOS`) is the sanctioned read/write path for FSNotes note files. File *contents* for the four names above are not in repo — they are the missing assets to reconstruct per §6.
- Photo mechanism: `local_eval/photo-originals/` holds only openphotoedit originals (`portrait_*`, `landscape_*`); `local_eval/benchmark-v2/assets/` holds only cooking rebuild inputs + `provenance.json`; `local_eval/photo_baseline.py` documents a reconstruction pattern (RGB-strip calibration inputs, never export pixels). None of these is the Maily photo original. Maily photo bytes (uniformed-gun `IMG_0080.JPG`, clown ×2 distinct hashes, guitar, airport selfie, orange boxes, table cooking, young man) have no authoritative original in repo/workspace. They must be reconstructed with provenance (§6), not borrowed from openphotoedit originals.
- Helpers that already exist and should be reused, not forked:
  - `initializers/ios/greenmail_open_app.py` (`_ensure_greenmail_ready` GET `/api/service/readiness`, `_purge_greenmail` POST `/api/mail/purge`).
  - `initializers/ios/greenmail_seed_open_app.py` (`seed_messages` via SMTP, `purge_greenmail`, `seed_after_launch`, foreground handling).
  - `initializers/ios/greenmail_local_state.py` (`purge_maily_local_state` clears `flutter.nextUidsInfo` + caches/snapshots while preserving configured accounts; `purge_deltachat_local_state` separate).
  - Generic child evaluators `evaluators/ios/maily_send_email.py`, `maily_forward_specific_email.py`, `maily_delete_specific_email.py`, `maily_multi_step_workflow.py` are *not* used by the four instruction_3_* tasks; they are separate simpler tasks. Do not conflate their loose body/subject matching with the strict instruction_3_* rulesets.
- Prior audit format precedent: `docs/ios/SOURCE_AUDIT.md` (48-task table, symbol import check, asset-dependency column) and `docs/ios/DELTACHAT_SEMANTIC_AUDIT.md`. This file follows the same source-linked-table style for Maily.
- Runner ordering fix (read-only reference, not edited): `core/artifacts/run_args.py::write_run_args_snapshot` writes UTC `created_at` into `args.json`; `core/platform_shared/benchmark_runner.py::resolve_run_artifact_paths` exposes `run_dir` + `trajectory_path` into evaluator context. 3_2/3_3/3_4 causal windows depend on these; the fix is already in tree.

## 5. Reproducible seeding + initializer proposal (preserves task meaning)

Goals: (a) every run starts from identical seeds; (b) launch-only initializer stays launch-only; (c) no verifier business rule is weakened.

1. GreenMail process: run the verified `../shared/greenmail/greenmail-standalone-2.1.14.jar` under OpenJDK 21 with SMTP `3025` / IMAP `3143` / API `8081` (root's healthy mapping). Update `scripts/start_greenmail.sh` defaults only if the container path is kept: bump image to a 2.1.14-equivalent and extend `GREENMAIL_USERS` to include every Maily mailbox: `alex.rivera@example.test`, `benchsender@example.test`, `benchrecv@example.test`, `planbox@mail.test`, `field3@mail.test`, `rein@mail.test`, `rain@mail.test`, `benchchat@example.test`, `ops4@mail.test` (all with a documented bench password). Without this, delivery to `planbox`/`ops4`/`field3` fails regardless of agent behavior.
2. Per-run reset (reproducible, order matters):
   - `GET /api/service/readiness` must return `Service running`.
   - `POST /api/mail/purge` (existing helper) to empty all mailboxes.
   - Purge Maily local state via `purge_maily_local_state` (clears `flutter.nextUidsInfo`, snapshots, caches; preserves accounts). Do not delete the `accts` keychain record.
3. Seed via SMTP + IMAP-visible REST (not UI):
   - Send each §2 Table 1 seed from a bench sender to `alex.rivera@example.test` over SMTP `127.0.0.1:3025` with exact `Subject`, exact `Message-ID` (the `<baseline-…>` values), a `Seed body for <Subject>.` text line (required by 3_2/3_3 quoted-body checks), and a stable `Date` well before the run window. IMAP `3143` is the Maily client's read path; REST `8081` (`GET /api/user/{mailbox}/messages/INBOX`) is the verifier's read path — seed through SMTP so both agree.
   - Seed counts: 7 (3_1) / 7 (3_2) / 5 (3_3) / 7 (3_4). For the live 48-task main only 3_1+3_2+3_3 seeds are needed per run; 3_4 seeds are needed once its yaml is restored.
4. FSNotes + photo-grid seeding (outside GreenMail):
   - Write the four FSNotes files via `FSNotesStore` into bundle `co.fluder.mobile.FSNotes-iOS` `Documents` (visible as `FSNotes` folder in the Maily file picker): `Sprint Review Draft.md`, `Shipping Notes.md`, `Team Contacts.md`, `Mobile Gates Gates.markdown`, each with the exact bytes matching §3 hashes (recovered or re-minted per §6).
   - Populate the iOS photo library with the 8 required JPEGs (exact bytes matching §3) so the Maily photo picker grid positions/descriptions resolve. Grid-position prose (e.g. "row 1 col 1") is descriptive; the hash is normative.
5. Maily account configuration (initializer change, minimal):
   - Keep `MailyOpenAppInitializer` launch-only. Add a separate opt-in seeding initializer (e.g. extending `GreenMailSeedOpenAppInitializer` with `seed_messages` for the per-task seed set + `account_email=alex.rivera@example.test`) OR document that the baseline simulator snapshot already contains the configured `alex.rivera@example.test` IMAP account pointing at `127.0.0.1:3025/3143` and that `greenmail_local_state` preservation is what keeps it. Either way, the task yamls' `initial_state_note` ("baseline data from stable source; initializer only launches") becomes true by construction instead of by assumption.
   - 3_4 only: the agent itself must rename the account to `Incident Desk` in steps 1–5 (keychain `accts`, verified via `SecItemCopyMatching` in the running app's entitlement context, `modified_after_current_boot && modified_before_first_delivery`). Seeding must *not* pre-rename; otherwise the rename-before-send proof is unachievable. Document this ordering explicitly in the restored 3_4 yaml.
6. Verification after seeding (read-only): `GET` each seed mailbox and assert the §2 seed subjects + Message-IDs exist exactly once before the agent starts. Never use GUI observation, trajectory, or old run dirs as seed proof.

## 6. Missing-asset reconstruction: provenance + hash approach

Missing: 4 FSNotes file bytes + 8 photo JPEG bytes (12 distinct hashes; the two clown hashes differ, so they are distinct assets). No history re-upload.

- Step 1 — exhaust read-only sources first: simulator baseline snapshots (`snapshot_name osomni-opendriver-ios-source-fixed-promax`), `../ios/legacy-device-*`, `../records/*`, `image-cache/`, `local_eval/benchmark-v2/references/`. Record negative results; do not fabricate a "found" claim.
- Step 2 — if unrecoverable, re-mint minimal assets that preserve task meaning:
  - Markdown files: UTF-8 text whose content is functionally neutral (e.g. one heading + one line identifying the task) — the verifier checks only filename + bytes + content-type, not prose semantics, so any stable bytes preserve meaning as long as evaluator + yaml hashes are updated together.
  - Photos: real JPEGs matching the prose descriptions (uniformed person holding gun; clown white-face/red-nose/green-hair; blue electric guitar close-up; airport-entrance group selfie; two people holding orange boxes; people cooking around table; young man). Content semantics (which photo the agent must pick) must remain distinguishable; exact pixels need not match the lost originals.
- Step 3 — provenance record (commit alongside the bytes, e.g. `local_eval/maily-assets/provenance.json`): for each asset: `{task, role, filename_or_label, source: "reconstructed", description_basis, creation_tool, created_at_utc, sha256, byte_size, content_type}`. Follow the `photo_baseline.py`/`benchmark-v2/assets/provenance.json` pattern: inputs are documented, outputs are hashed, limitations stated.
- Step 4 — contract update is atomic: new bytes → recompute the affected `*_SHA256` constant(s) in the corresponding `evaluators/ios/maily_instruction_3_*.py` → recompute `RULESET_SHA256` (it is derived, no manual edit needed beyond the constant) → update `expected_ruleset_sha256` in the matching `tasks/v1/ios/maily_*.yaml` → restore `maily_instruction_3_4.yaml` + execution entry if 3_4 assets are minted. Partial updates (bytes without hash, or hash without yaml digest) break the ruleset binding check by design.
- Explicit non-goal: do not "normalize" hashes away (e.g. compare filenames only) and do not widen body/subject matching to accommodate wrong bytes. Those weaken conclusions without task-semantic grounds (§7).

## 7. Read-only verifier business conditions vs historical causal/windows/device/process constraints

Business conditions (must keep — they encode the task):

- Exact `from`/`to`/`subject`/`user-authored-plain-text`, exact attachment filename (files) + content-type + SHA-256, reply/forward seed binding, compose-has-no-thread-headers, unique-match, global Date order + per-mailbox UID order, 76-step exact-once coverage. Sources: `RULESET_SPEC`/`CHECKPOINT_SPECS`/`MESSAGE_SPECS` in each evaluator + `verifier_rules` in each yaml.
- 3_3 body modes (`exact` for composes, `prefix` for replies, `contains` for the FieldFwd forward) and 3_2 body-prefix rule are business conditions, not tolerances.
- 3_3 wire normalization (` · retain` → ` . retain`, build 96) and 3_2 subject normalization (middle-dot may persist as ASCII period) are business conditions documenting real Maily transport behavior. Seeding/proposal must preserve them, not "fix" subjects to the instruction glyph.
- 3_4 account-name checkpoint (`Incident Desk`, `accts`, rename after boot and before first delivery) is a business condition.

Historical/causal/device/process constraints (do not silently carry into the GreenMail rebuild; re-derive or drop with stated grounds):

| Constraint in current code | Where | Verdict for GreenMail rebuild |
|---|---|---|
| `manual_window_start/end 2026-08-01T16:43:40+08:00 …` | `maily_instruction_3_2.yaml` params | Historical manual-recording window. Automatic runs resolve the window from `run_dir/args.json.created_at` (see `_resolve_causal_window`). Do not bake the August wall-clock window into seeds; seeds must predate `created_at`, outputs must fall inside the run window. |
| `expected_ios_device_profile iphone17-3 / iphone17-2`, `source_simulator_name …promax`, `udid` required + `simctl get_app_container` / `simctl list --json` binding, `lastBootedAt` session lower bound | 3_2/3_3/3_4 evaluators + yaml metadata | Device/process binding for the simulator era. In a GreenMail-on-host rebuild there is no `simctl` UDID; the equivalent causal lower bound is the root-fixed `args.json.created_at` (UTC, written before task init) and the evaluator-context `run_dir`/`trajectory_path`. Any proposal that keeps a UDID gate must state which runner provides it; otherwise replace with the `created_at` bound explicitly, not silently. |
| `evaluation_cutoff = now(utc)` at eval start; `booted_at < date <= cutoff` | 3_3 | Process constraint (prevents future-dated mail). Keep the shape (outputs must be within the run), but anchor `booted_at` to `created_at` when no simulator boot time exists. |
| Maily app-data health (`nextUidsInfo`, preferences `not_first_run`, container metadata) | 3_3 `_read_app_health` | Simulator-process constraint. If Maily runs against GreenMail on host without the iOS container, this check cannot pass as written — flag as needing a documented adapter, not a quiet deletion. |
| `SecItemCopyMatching` account read via LLDB in app entitlement context | 3_4 | Device/process constraint tied to the running iOS app. Same treatment: keep the rename-before-send business rule; adapt the read transport explicitly if the harness changes. |
| `expected_ruleset_sha256` per yaml | all three yamls | Anti-drift binding, not history. Keep. Any asset or constant change must update it (see §6 Step 4). |

No weakening without task-semantic grounds: the table above names the only constraints eligible for re-anchoring (they reference a simulator/clock that the GreenMail rebuild does not have). Everything in the business-conditions list stays byte-exact. In particular, do not drop attachment hashes, thread-binding, unique-match, ordering, or step-coverage to make reconstruction easier — those are the task.

## Addendum A — corrections (2026-10-11, Maily baseline seeder delivery)

Earlier sections above are preserved as written; the following corrections supersede the points they name. Nothing else in this file was reverted or edited.

1. Photos "unavailable" claim is FALSE and retracted. §4 ("Maily photo bytes … have no authoritative original") and §6 Step 1 (exhaust-then-re-mint) predate recovery: root has found ALL 8 JPEGs in the official pinned simulator DCIM matching the current evaluators. Record: `../records/mail-recovered-photo-manifest.json`; copies: `../ios/recovered-assets/mail-photos`. (Paths are root-provided and were not independently opened here; hash acceptance against the evaluator constants in `evaluators/ios/maily_instruction_3_[123].py` is enforced by `scripts/prepare_maily_assets.py`.) Reconstruction of photos is therefore a fallback only, not the plan.
2. Proposals to drop or re-anchor UDID/container health checks are RETRACTED. GreenMail runs on the host (SMTP 3025 / IMAP 3143 / REST 8081), but Maily REMAINS ON iOS: the `udid`-bound container checks (`simctl get_app_container`, app-data health, `lastBootedAt` session bound) remain applicable and must be kept. The §7 table rows suggesting a `created_at`-only replacement apply only to a hypothetical host-run Maily that is not being built.
3. FSNotes files: before any re-minting, first seek the 4 original md hashes from the official app containers (`Sprint Review Draft.md`, `Shipping Notes.md`, `Team Contacts.md`, `Mobile Gates Gates.markdown`); root handles the actual filesystem extraction. `scripts/prepare_maily_assets.py extract --source <caller-selected-tree>` performs only hash-verified matching against a caller-provided tree and never requires private directories.
4. Scope is three live tasks only (`maily_instruction_3_1/3_2/3_3`). No fourth task is added: `3_4` rows in the tables above document the orphaned evaluator and are seek-only references. `initializers/ios/greenmail_seed_open_app.py` and `initializers/ios/greenmail_local_state.py` are reused as-is (readiness/purge/local-state purge); the new per-task seeder is `initializers/ios/maily_benchmark_seed.py`, assets in `scripts/prepare_maily_assets.py`, coverage in `tests/test_maily_benchmark_seed.py`, guide in `docs/ios/MAIL_SEEDING.md`. Task YAML wiring is left to root after review.
