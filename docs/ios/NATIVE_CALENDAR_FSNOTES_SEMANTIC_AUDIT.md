# Native Calendar + FSNotes — Instruction-Only Blind Semantic Audit

Scope: two Calendar tasks (`calendar_finalize_schedule_with_two_followups.yaml`,
`calendar_update_and_create_followup.yaml`) and two FSNotes tasks
(`fsnotes_archive_note_and_create_followup.yaml`, `fsnotes_move_rename_and_update_note.yaml`),
plus their actual evaluator / store / initializer modules. Blind: no model outputs read.
No GUI/device/VM/services operated. No source or task edits. No commit/push.

Sources read (only):

- `tasks/v1/ios/calendar_finalize_schedule_with_two_followups.yaml`
- `tasks/v1/ios/calendar_update_and_create_followup.yaml`
- `tasks/v1/ios/fsnotes_archive_note_and_create_followup.yaml`
- `tasks/v1/ios/fsnotes_move_rename_and_update_note.yaml`
- `evaluators/ios/calendar_event_state.py`
- `evaluators/ios/fsnotes_state.py`
- `initializers/ios/calendar_seed_open_app.py`
- `initializers/ios/fsnotes_seed_open_app.py`
- `platforms/ios/calendar_store.py`
- `platforms/ios/fsnotes_store.py`

Deliberately NOT read: formal/model outputs, evidence/screenshots, `.env`/keychain,
records under `execution/records/`.

## Verdict summary

No task is ungradeable. No false-initial-PASS. Baselines are reconstructible
(`purge_all_*` + explicit seeds). Two REAL defects need author action; the rest are
hypothetical risks or business clarifications.

- REAL defect R1 (Calendar, both tasks): strict instruction vs lenient comparator on
  extra events. Instruction says e.g. "Leave Bench Commute unchanged" / "Leave the other
  existing events unchanged", but `CalendarEventStateEvaluator` + `IOSCalendarStore`
  accept arbitrary extra events and extra description/location content. No total-count
  guard, no forbid-extra-summaries guard.
- REAL defect R2 (Calendar, both tasks + portability): timezone silently host-dependent.
  Neither task passes `timezone`; initializer and evaluator both fall back to
  `default_timezone_name()` (host local zone or `Asia/Shanghai`); the store writes that
  zone into `start_tz`/`end_tz` and anchors `day_offset` to the host date. The visible
  instruction never names a zone. On a fresh arbitrary-host simulator whose UI zone
  differs from the host zone, wall-clock times and day boundaries can shift. Detail and
  portability repairs in §4.
- Everything else below is hypothetical risk or needs a business answer, NOT a defect:
  F1–F8. Do not weaken comparators to "fix" them.

## 1. Calendar — instruction completeness

Both instructions fully state title, wall-clock interval, location, day (today / tomorrow /
day-after), which seed to delete/rename, and which seed to leave alone. Strict accepted
requirements visible to the agent are complete for a same-zone run.

Gaps (ambiguity, not defect):

- "today / tomorrow / day after tomorrow" is anchored to the device day, but the checker
  anchors `day_offset` to the host day (`_base_date()` = `datetime.now(self.tzinfo).date()`).
  Same-zone + same-date runs agree; a midnight crossover between init and eval, or a
  host/simulator date skew, moves the boundary. Hypothetical risk; author fix is to name
  the anchor ("device-local calendar day at evaluation time") only if flakiness is observed.
- Deletion vs rename mechanics are unspecified (delete via UI vs edit-then-delete 앨IAS).
  Checker only requires: old summary absent (exact summary match), new summary present with
  exact date/start/end and normalized location. Any UI path achieving that state passes.
  Correct — do not overspecify.
- "Leave X unchanged" for Calendar means: same summary, same day, same HH:MM–HH:MM, same
  location. It does NOT explicitly forbid extra new events with unrelated summaries, but a
  strict business reading would. That is R1, not agent ambiguity.

## 2. Calendar — business bounds / extra-content acceptance (R1, real defect)

Source evidence:

- `calendar_event_state.py` polls `store.list_events(wanted_summaries)` where
  `wanted_summaries = absent + present summaries`. Unrelated summaries are never queried.
- `event_matches_spec()` (`calendar_store.py`): summary exact; date/start/end exact;
  location checked ONLY if spec non-empty (normalized compare); description checked ONLY
  if spec non-empty. Extra description text on a matched event is accepted.
- There is no `event_count` / `total_count` parameter and no "absent unless listed" rule.

Consequences:

- Correct reference: update Briefing→Final (16:40–17:25, Cedar Room), delete Hold, create
  the two follow-ups, leave Commute byte-identical → PASS.
- Wrong reference that still PASSES today: do all of the above AND create an extra event
  "Bench Outreach Spam 23:00–23:30" AND append junk to the Final description via any
  description field the UI exposes → still PASS, because the extra summary is never listed
  and description is unchecked when the spec leaves it empty. The instruction's "leave
  unchanged / delete X / create exactly two" business intent is stricter than the checker.

Minimal semantics-preserving author fixes (pick one; do NOT loosen time/location matching):

1. Clarify business intent in the instruction (preferred, no code change): append
   "Do not create any other events and do not change anything else." This makes the
   strict reading visible without touching the comparator.
2. OR harden the comparator without changing accepted correct behavior: add an explicit
   total-count or closed-world option (e.g. `exact_event_count` / `forbid_extra_summaries`)
   to the Calendar evaluator and set it in these two tasks. This rejects the wrong
   reference above while every correct reference still passes.

## 3. Calendar — title / location / persistence / unchanged guards / seeds

- Title: `event_matches_spec` requires exact `record.summary == spec.summary` (case- and
  punctuation-sensitive; only location/description get whitespace-normalized compare).
  Instruction titles are exact quoted strings — consistent. Hypothetical risk only: an agent
  that trims/adds punctuation or changes case fails, which is intended strictness.
- Location: normalized (`_normalize_text`) compare, only when spec non-empty. All four
  present-events in both tasks specify a location, so all are checked. Extra whitespace
  differences are forgiven — reasonable, not a defect.
- Persistence: seeding writes `CalendarItem` + `Location` + `OccurrenceCache` +
  `CalendarItemChanges` rows directly in `Calendar.sqlitedb`; evaluation snapshots the DB
  files and reads the same tables. A file-level PASS therefore means durable state, not
  transient UI. Whether the Calendar UI visibly refreshes to the same state must be
  GUI-validated by Root (see §6).
- Unchanged guards: task 1 pins `Bench Commute` present-exact; task 2 pins `Bench Pharmacy
  Run` + `Bench Evening Walk` present-exact. Absent lists pin the renamed/deleted originals.
  Because init sets `purge_all_events: true`, "the other existing events" is exactly those
  pinned seeds — bounded, no false PASS. Initial state FAILS both tasks (seeds lack the
  Final/Updated/Debrief summaries and still contain the to-be-removed summaries), so no
  false-initial-PASS. Verified by spec comparison, not by execution.
- Baseline reconstruction: `purge_all_events: true` + explicit `seed_events` with
  day offsets, HH:MM, locations makes baselines reproducible on any fresh simulator DB
  that contains at least one `store_id = 1` calendar (`_resolve_event_calendar_id`
  fallback). Author note: `purge_all_events` is destructive by design — fine for benchmark
  simulators, must never run against a personal device.

## 4. Calendar — date/time/timezone portability (R2, real defect)

Trigger condition stated in the request IS present in these tasks: task values carry an
effective TZ (written into the DB) while the visible instruction never mentions it, and
local-region initialization does not force the simulator UI into the same zone.

Source evidence (all in `calendar_store.py` unless noted):

- `default_timezone_name()`: returns host local zone key, else `"Asia/Shanghai"`.
- Initializer (`calendar_seed_open_app.py`): `timezone_name = params.get("timezone") or
  default_timezone_name()` — neither Calendar task sets `timezone`, so host zone wins.
- Evaluator (`calendar_event_state.py`): identical fallback — host zone wins.
- Seeding: `_event_timestamp()` / `_local_midnight_timestamp()` interpret the YAML HH:MM
  as wall-clock in `self.tzinfo` (host zone); `INSERT INTO CalendarItem` stores
  `start_tz`/`end_tz = self.timezone_name`.
- Reading: `_apple_timestamp_to_local()` converts Apple-epoch seconds back into
  `self.tzinfo` (host zone) and formats `%H:%M` + date. Matching compares those host-zone
  projections against the YAML.
- The initializer never sets the simulator's system timezone; it only terminates/opens the
  app, dismisses alerts, and taps List/Today. Nothing aligns the UI zone with the host zone.

Why this breaks portability: init and eval agree with each other (both host zone), so CI on
one machine is self-consistent; but the agent acts through the simulator UI, which renders
in the simulator's zone. If host = Asia/Shanghai and simulator = America/Los_Angeles, a
seeded "16:40" (Shanghai wall-clock) displays as 01:40 same-day in the UI; "today /
tomorrow" day boundaries also shift by up to ±1. An agent that faithfully reproduces the
UI-displayed times then FAILS the host-zone checker, and an agent that obeys the literal
instruction HH:MM in the UI zone also FAILS. The instruction gives the agent no way to know
which zone the checker means. This is a real defect whenever hosts and simulators span
zones; single-zone labs will never see it (hypothetical there).

Exact portability repairs that preserve the original time intent (author picks one):

- Option A (recommended, minimal): pin and disclose. Add `timezone: Asia/Shanghai` (or the
  lab's canonical zone) to BOTH `init.params` and `evaluation.params` in the two Calendar
  tasks, document that the harness must set the simulator system timezone to the same zone
  (or add that step to the initializer), and append one sentence to each instruction:
  "All times are <Zone> wall-clock." Correct behavior is unchanged for same-zone runs;
  cross-zone runs become deterministic. Original intent (the HH:MM wall-clock on the stated
  day) is preserved exactly.
- Option B: evaluate instants, not wall-clock. Keep the instruction zone-agnostic but store
  an explicit absolute expectation (UTC instant per event) and compare instants within a
  stated tolerance. Heavier change; only if the business requirement is "same moment" rather
  than "same wall-clock."
- What NOT to do: silently widen time matching (±hours) or drop day checks to "make
  cross-zone pass." That weakens the comparator and adapts the task to infrastructure drift.

## 5. FSNotes — findings

Both instructions fully state: folders to create, which note moves where, rename target,
exact appended section/lines, new-note folder + exact lines, and "leave the other notes
unchanged." The checkers enforce: `note_count` (4), `folder_count` (1 or 3),
`present_folders`, per-note `path` + `content_contains` (moved/edited notes) or
`exact_content` (new + untouched notes), and `absent_notes` by path AND title. No
false-initial-PASS (seeds are 3 notes / 0 folders without the appended sections).

Real leniencies vs strict instruction (business clarifications, NOT defects unless the
business requires strictness):

- B1 — moved-note append position and exclusivity unchecked. `content_contains` requires
  each fragment to appear anywhere (`fragment in note.content`), in any order, with any
  extra text. Correct reference (original body + blank line + exact trailing section)
  passes; wrong reference (section prepended at top, or original body + section + extra
  junk paragraph) also passes. If "append at the end" and "nothing else added" are business
  requirements, the author must either state the tolerance in the instruction ("the section
  must be present; position and extra text are not graded") or add an `exact_content` /
  `ends_with` assertion for the moved notes. Do not "fix" by weakening the new-note
  `exact_content` checks.
- B2 — "lines exactly" for new notes tolerates a leading title line. `_content_matches_exact`
  strips trailing newlines, normalizes `\r\n`, and — when the file has >1 line — accepts an
  extra first line whose normalized title matches the note title, comparing the remainder.
  This models FSNotes auto-title behavior and is pragmatic. But the instruction says "with
  these two/four lines exactly" with no mention of a title line. If an agent writes exactly
  the lines, it passes; if the app prepends `# Title`, it also passes. Author clarification
  (one sentence: "an app-added first-line title matching the note name is acceptable") makes
  visible instruction match the checker. Hypothetical risk only — do not remove the tolerance
  to "strengthen" the task, since that would start failing app-faithful behavior.
- B3 — extension interchangeability. `_relative_path_matches` treats any two
  markdown-compatible extensions (`.md`, `.markdown`, `.txt` excluded from the compatible
  set only for the no-suffix default rule) as matching when both sides carry an extension,
  and stem compare is casefolded/whitespace-normalized. So "Bench Follow-up Log.markdown"
  satisfies "named Bench Follow-up Log." The instruction never names `.md`. If `.md`
  specifically is required, the author must write "named Bench Follow-up Log.md" and add an
  `extension: .md` assertion; otherwise the current tolerance is the disclosed business rule.
- B4 — "in the root" / "in Meeting Prep" folder targeting IS enforced (`parent` must match
  after normalization), and `absent_notes` by both path and title catches move-by-copy
  leftovers and rename misses (title match uses stem + first-line + stripped-heading
  candidates). Good — no fix needed.
- B5 — `note_count`/`folder_count` close the world that Calendar leaves open: extra notes or
  folders fail FSNotes. Trash is excluded from both counts; unsupported suffixes are invisible
  to the checker (an agent hiding content in `*.pdf` would neither pass nor be counted —
  GUI validation should confirm the app shows only the expected notes).
- Baseline/persistence: `purge_all_notes: true` + explicit `notes:` paths/contents +
  `clear_saved_state` make baselines reconstructible. Seeding/eval operate on files under
  the simulator container, polled until timeout — durable state. Whether the FSNotes UI
  (folders list, note list, editor) reflects the files without relaunch is a Root
  GUI-validation item.

## 6. Checks Root should actually GUI-validate (not inferrable from source)

1. Calendar List/Today landing: after init, does the app actually land in List view on
   Today on a fresh simulator (the `_ensure_month_list_mode` + `_tap_today_if_available`
   path is best-effort and silently no-ops when buttons are missing)?
2. Calendar editability/visibility: can an agent, using only the simulator UI, edit title /
   time / location of a seeded event, delete one event, and create events on tomorrow and
   the day after (date picker day arithmetic across month boundaries)?
3. Calendar zone render: with the simulator in its default zone, do seeded times display as
   the instruction's HH:MM? If not, apply repair Option A and re-validate.
4. FSNotes folder/note affordances: create folder, move note into folder, rename note,
   append text at end of note, create note in a specific folder vs root — all reachable and
   persisted without force-quit?
5. FSNotes title behavior: does saving a new note prepend a `# Title` first line (justifying
   the B2 tolerance), and does the untouched-note `exact_content` survive an app relaunch?
6. FSNotes root-vs-folder creation: does "new note in Meeting Prep" land in that folder's
   path (not root with a tag), matching the parent-path assertion?

## 7. Minimal author diffs (semantics-preserving; apply only if business agrees)

- Calendar tasks: add `timezone: Asia/Shanghai` under BOTH `init.params` and
  `evaluation.params`; append to instruction: "All times are Asia/Shanghai wall-clock."
  Plus either the no-extra-events sentence (no code) or a closed-world count in the
  evaluator (code + task params).
- FSNotes tasks: optionally add one sentence covering B1–B3 tolerances
  ("The required section must appear in the moved note; its position and additional text
  are not graded. The file extension may be any Markdown extension. An app-added first-line
  title matching the note name is acceptable.") — or, if the business is strict, replace
  `content_contains` with exact/ends-with assertions for the moved notes and add
  `extension: .md`. Either direction keeps correct references passing; pick the one that
  matches the real product requirement.

Audit performed under the stated boundaries; no task answers were sent anywhere.

## Author review before formal runs

The original instruction does not explicitly forbid unrelated new events. The exact-four condition is therefore a disclosed author clarification that strengthens the revised task, rather than an unstated original requirement. Equality on the unchanged seeded descriptions follows the existing unchanged constraint. Host IANA timezone resolution addresses the real portability defect; simulator display alignment still requires actual GUI validation. No Calendar model outputs existed during this review.

## Author review of FSNotes append semantics before model runs

The original tasks explicitly require an exact section or line at the end. Accepting a reversed or prepended section violates that existing instruction; the proposed position-tolerance alternative is rejected. Independent native-file references reproduced the original substring matcher accepting this wrong completion, before any FSNotes model output existed. The opt-in `content_ends_with` revision retains the original task wording and all other checks. Both tasks pass independently correct references and fail wrong-position references. GUI validation and revised initializer prechecks remain required before formal runs. See `FSNOTES_RULESET_REVISIONS.json`; revised scores must disclose the correction.
