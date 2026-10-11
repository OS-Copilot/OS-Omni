# Contacts Semantic Audit (Independent, Instruction-Only)

Scope: semantic audit of iOS Contacts acceptance against explicit task
instructions. No GUI, no model requests, no pushes, no model
logs/results/screenshots inspected.

Inspected sources ONLY:

- `tasks/v1/ios/contacts_add_contact_card.yaml`
- `tasks/v1/ios/contacts_reconcile_multi_field_directory.yaml`
- `evaluators/ios/contacts_state.py` (ContactsStateEvaluator)
- `platforms/ios/contacts_store.py` (IOSContactsStore comparator)

All line citations below refer to those files as read at audit time.
No other task variant, oracle YAML, initializer, log, screenshot, or
result file was used as evidence.

Method: for each acceptance field/constraint, ask whether it follows
from the explicit instruction text alone. Seeded initial state in the
`init:` block of the same YAML is treated as background fact, not as
instruction. A constraint that needs an unstated assumption is flagged
as a hidden requirement (over-constraining) or overpermissiveness
(under-constraining), even if it looks practically reasonable. No
change is recommended merely to increase PASS.

---

## 1. Instruction semantics (explicit text only)

### 1.1 `contacts_add_contact_card.yaml`

Instruction (`contacts_add_contact_card.yaml:3-5`):

> In Contacts, create a new contact for Bench Courier. Set the company
> to Bench Logistics, the phone number to 555-010-2486, and the email
> address to courier@bench-example.test.

Explicit content:

- Action: create one new contact.
- Display/referential name: "Bench Courier".
- Company: "Bench Logistics".
- Phone: one value "555-010-2486".
- Email: one value "courier@bench-example.test".

NOT explicit:

- How "Bench Courier" splits into iOS `First` vs `Last` structural
  fields.
- Whether Company maps to anything other than the Contacts
  Organization field (in practice it must, but the instruction only
  says "company").
- Phone/email/note cardinality caps, label types, case/whitespace
  rules, or digit-formatting rules.
- The starting contents of the address book (that lives in
  `init:`, `contacts_add_contact_card.yaml:6-12`: purge all, seed
  empty — background fact, not instruction).

### 1.2 `contacts_reconcile_multi_field_directory.yaml`

Instruction (`contacts_reconcile_multi_field_directory.yaml:3-11`):

> Clean up the seeded contacts list. Update Bench Logistics so its
> company becomes Bench Logistics Desk, its phone numbers are
> 555-010-4400 and 555-010-4401, its email address is
> logistics@bench-example.test, and its note is Use loading dock
> entrance. Update Bench Catering Lead so its phone number becomes
> 555-010-4510 and its email address becomes
> catering-lead@bench-example.test. Delete the outdated contact Bench
> Venue Old. Then create a new contact named Bench Security with company
> North Gate Team, phone numbers 555-010-4620 and 555-010-4621, email
> security@bench-example.test, and note Badge desk closes at 21:00.
> Leave Bench Office unchanged.

Explicit content per referent:

- Bench Logistics: company := "Bench Logistics Desk"; phones :=
  {"555-010-4400","555-010-4401"}; email :=
  "logistics@bench-example.test"; note := "Use loading dock entrance."
- Bench Catering Lead: phone := "555-010-4510"; email :=
  "catering-lead@bench-example.test". Company and note are NOT
  mentioned for this referent.
- Bench Venue Old: delete.
- Bench Security (new): name "Bench Security"; company "North Gate
  Team"; phones {"555-010-4620","555-010-4621"}; email
  "security@bench-example.test"; note "Badge desk closes at 21:00."
- Bench Office: "unchanged" relative to seed.

Seed background facts (`contacts_reconcile_multi_field_directory.yaml:17-40`):
four seeded contacts (Logistics / Catering Lead / Venue Old / Office)
with the organizations/phones/emails/notes listed there. These facts
are needed to resolve "unchanged" and "becomes", but they are not
instruction text.

NOT explicit:

- First/Last splits for any of "Bench Logistics", "Bench Catering
  Lead", "Bench Venue Old", "Bench Security", "Bench Office".
- Whether "are" / "becomes" for phones/emails means exact-set
  replacement vs. must-contain (natural reading is replacement; see
  §5).
- Whether unmentioned fields of an "Update X so its Y becomes ..."
  record must be preserved (e.g. Catering Lead company/note) or are
  free.
- Uniqueness/display-vs-structure rules, formatting/normalization
  rules, or a total-count cap stated in words (count follows only by
  arithmetic over seed + instruction).

---

## 2. Evaluator and comparator mechanics (cited)

- `ContactsStateEvaluator.evaluate` delegates the whole decision to
  `store.assert_state(params)` in a poll loop
  (`evaluators/ios/contacts_state.py:39`, `:46-60`). It adds no
  semantics of its own; all matching semantics live in
  `platforms/ios/contacts_store.py`.
- `assert_state` (`contacts_store.py:283-320`): every
  `present_contacts` spec must match ≥1 record (`:294-296`); every
  `absent_contacts` spec must match 0 records (`:298-300`);
  `exact_count`, when present, must equal total row count
  (`:302-303`). Empty `phones`/`emails`/`note`/`organization` in a
  spec impose no check on that field (see §3).
- `contact_matches_spec` (`contacts_store.py:322-346`):
  - `first_name`, `last_name`, `organization`, `note` are checked only
    when the spec side is non-empty, with case-insensitive,
    whitespace-collapsed comparison (`:324-331`, normalizer `:348-350`).
  - Phones/emails are SUBSET checks: normalized expected set must be a
    subset of normalized observed set (`:333-341`). Empty expected set
    passes vacuously.
  - Phone normalization strips to digits (`:356-360`); email
    normalization is strip + casefold (`:352-354`).
  - `full_name` redundant check (`:343-345`): normalized
    `record.full_name` must equal normalized `spec.full_name` whenever
    the spec's derived full name is non-empty. `full_name` derives as
    `"First Last"` or fallback to organization (`:29-31`, `:45-48`).
- Name coercion (`_coerce_name_parts`, `contacts_store.py:461-481`):
  `first_name`/`last_name` keys win when either is present; otherwise a
  `full_name`/`name` string is split on the FIRST space. A single token
  becomes `(token, "")`.
- Text coercion preserves case in storage (`_normalize_text`,
  `contacts_store.py:520-521`) but comparison folds case.

---

## 3. Field-by-field conformance

### 3.1 add_contact_card — acceptance (`contacts_add_contact_card.yaml:16-22`)

- **Name `first Bench / last Courier` (`:18-19`)** — HIDDEN REQUIREMENT.
  Display "Bench Courier" is explicit; the 1+1 split is not. Any split
  rendering that display meets the words; only one split passes. §4.
- **Organization "Bench Logistics" from "company" (`:20`)** — FOLLOWS
  (§3.3). Company has no other Contacts target than Organization.
- **Phone `555-010-2486` (`:21`)** — FOLLOWS as must-contain. Exact-set
  reading not enforced (subset, §5).
- **Email `courier@bench-example.test` (`:22`)** — FOLLOWS as
  must-contain. Exact-set not enforced (§5).
- **`exact_count: 1` (`:16`)** — FOLLOWS GIVEN SEED (purge + empty seed,
  `:9-11`) plus "create a new contact". Not instruction-explicit alone.
  No note constraint is stated, so any note passes — silent but faithful.

### 3.2 reconcile — present_contacts (`contacts_reconcile_multi_field_directory.yaml:45-68`)

- Logistics (`:46-51`): organization/phones/email/note each name the
  exact instructed values — FOLLOWS. Name split (`first Bench /
  last Logistics`) is the same hidden-split issue as §4. Phone/email
  enforced as subset, not exact set — overpermissive (§5).
- Catering Lead (`:52-56`): phones/emails name the instructed new
  values — FOLLOWS as must-contain. `organization: "Bench Catering"`
  (`:54`) is NOT in the instruction for this referent. The instruction
  says only phone + email "becomes"; it never states the company, nor
  "leave the rest unchanged" for this record (that phrase appears only
  for Bench Office). Requiring the old company value to persist is a
  HIDDEN REQUIREMENT: a plausible instruction-faithful reading leaves
  that field unconstrained, and a repair must come from instruction
  clarification ("leave company unchanged"), not silent evaluator
  retention. Conversely the evaluator imposes NO note constraint here
  (spec note empty → `contacts_store.py:330` vacuous): an agent-added
  note on Catering Lead passes. That is overpermissive relative to a
  strict "only these fields change" reading, but instruction-faithful
  under the literal text (note is unmentioned) — must NOT be "fixed"
  by adding a note ban without instruction basis.
- Security (`:57-62`): all five asserted fields name instructed values
  — FOLLOWS modulo the name-split hidden requirement (`first Bench /
  last Security`, §4) and subset/exact-set gap for phones (§5).
- Office (`:63-68`): full record pinned to seed values. Instruction
  "Leave Bench Office unchanged" + seed values (`:34-39`) jointly
  entail this — FOLLOWS. This is the only record where a preservation
  requirement is instruction-explicit.

### 3.3 Vocabulary mapping: "company" → `organization`

Both tasks say "company"; acceptance uses `organization`. iOS
AddressBook exposes Company via the `Organization` column, which the
store reads/writes (`contacts_store.py:117`, `:211`). The mapping is
the only reasonable structural target, so it FOLLOWS. The audit notes
the wording gap only so a future instruction can say "company
(Organization field)" if literalism is desired; no evaluator repair is
needed.

### 3.4 reconcile — absent_contacts (`contacts_reconcile_multi_field_directory.yaml:69-83`)

- `{first Bench, last Venue Old}` with no phone/email (`:70-71`):
  instruction "Delete the outdated contact Bench Venue Old" — FOLLOWS,
  modulo the same name-split caveat. Because the spec carries no
  phone/email/note/organization, ANY record with that name matches
  (`contacts_store.py:324-345` all vacuous except names) and fails the
  run. That correctly models deletion of the named card.
- `{Bench Logistics + old phone 555-010-4000}` (`:72-74`) and `{Bench
  Logistics + old email dock-old@...}` (`:75-77`): instruction replaces
  both channels with new values — FOLLOWS as staleness guards. Partial
  specs are the right shape: they fail only a record that still carries
  the stale value under that name.
- `{Bench Catering Lead + old phone}` (`:78-80`) and `{... + old
  email}` (`:81-83`): same — FOLLOWS for the same reason.
- Gaps (overpermissiveness, instruction-faithful): no absent guard for
  the old Logistics company ("Bench Logistics Old"), the old Logistics
  note ("Old dock instructions."), or the old Catering company if it
  were changed. An agent that keeps the old company/note AND adds the
  new values still fails the present check (present requires the new
  company/note), so the company/note gap is harmless in practice. The
  phone/email absent guards are single-value specs, so a record keeping
  a stale value under a renamed contact would escape — but renaming
  itself already fails the present check. No repair recommended: the
  gaps do not admit an instruction-violating PASS on their own.

### 3.5 `exact_count: 4` (reconcile, `:44`)

Not stated in instruction words. Follows arithmetically from seed
count (4) − deleted (Venue Old, 1) + created (Security, 1) = 4. FOLLOWS
GIVEN SEED. It correctly rejects extra surviving cards and duplicate
creation. It does not cure intra-record superset permissiveness (§5).

---

## 4. Name representation vs. structural fields (no unstated intent assumed)

This is the audit's central finding.

Instructions refer to contacts by DISPLAY-style names: "Bench
Courier", "Bench Logistics", "Bench Catering Lead", "Bench Venue Old",
"Bench Security", "Bench Office". They never use the words First,
Last, Given, Family, full_name, or display name, and never state a
token split. iOS AddressBook, however, stores `First` and `Last`
structurally (`contacts_store.py:209-211`, read back at `:115-116`).

Acceptance pins a single split for every referent, e.g.
`first_name: "Bench", last_name: "Courier"`
(`contacts_add_contact_card.yaml:18-19`) and `first_name: "Bench",
last_name: "Catering Lead"`
(`contacts_reconcile_multi_field_directory.yaml:52-53`).

Why this over-constrains:

1. "Bench Courier" admits multiple structural realizations that all
   display as "Bench Courier": `(First=Bench, Last=Courier)`; a
   single-field realization is impossible in this schema but
   `(First="Bench Courier", Last="")` is a distinct DB state the
   instruction does not rule out in words; the comparator itself
   anticipates such states via its `full_name` fallback
   (`contacts_store.py:29-31`) and single-token coercion
   (`:478-479`).
2. Three-token names make the assumption visible. "Bench Catering
   Lead" is pinned as `(Bench | Catering Lead)`. `(Bench Catering |
   Lead)` displays identically in the Contacts list ("Bench Catering
   Lead") and satisfies every instruction word, yet the comparator
   rejects it: `contact_matches_spec` requires BOTH structural parts
   (`:324-327`) AND the joined full name (`:343-345`), so a different
   split fails twice over. The instruction never authorizes that
   rejection.
3. The `full_name` check (`:343-345`) is redundant when First/Last
   already match (join of equal parts is equal), so it adds no
   display-name leniency — it only re-punishes an alternative split.
   Case/whitespace folding (`:348-350`) is the sole leniency, and it
   does not span splits.

Therefore: every `first_name`/`last_name` pair in both YAMLs is a
HIDDEN REQUIREMENT as written. Each is one valid rendering of the
instructed name, not the instructed name itself.

What preserves meaning: INSTRUCTION CLARIFICATION, not silent
evaluator loosening. Options that preserve meaning:

- (a) Instruction states the split explicitly, e.g. "create a contact
  with first name Bench and last name Courier". Then the current
  acceptance follows exactly.
- (b) Instruction states display semantics, e.g. "contact displaying
  as Bench Courier (any First/Last split rendering that display is
  acceptable)". Then the evaluator must be repaired to match on
  normalized `full_name` display rather than structural parts for
  these tasks.

Either (a) or (b) preserves meaning because the current instruction
underdetermines the split; picking one unilaterally in the evaluator
invents intent. Recommending (b) merely to raise PASS would violate
the audit rule — it is recommended here only because the instruction
as written does not contain the split, so the evaluator currently
checks something the instruction never said. If the benchmark intends
structural precision, (a) is the correct fix and the evaluator stays
as is.

Canonical references (instruction-only, no evaluator consulted):

- CORRECT (task 1): any card whose Contacts display reads "Bench
  Courier" with company Bench Logistics, containing phone digits
  5550102486 and email courier@bench-example.test. Canonical narrow
  example: First=Bench, Last=Courier. Equally instruction-correct but
  currently rejected: First="Bench Courier", Last="" (same display,
  degenerate split) — which is exactly why clarification is needed.
- CORRECT (reconcile Security): display "Bench Security", company
  North Gate Team, both security phones, security email, badge-desk
  note. Canonical: First=Bench, Last=Security.
- INCORRECT (genuinely wrong under any reading): display "Courier
  Bench" (token order swapped); display "Bench" alone (missing token);
  "Bench Courier Extra" (added token); company "Bench Logistics Desk"
  on the add-card task (wrong company string); phone digits
  5550102487 (off-by-one); email courier@bench-example.example
  (wrong domain).

---

## 5. Hidden requirements and overpermissiveness inventory

Hidden requirements (evaluator checks more than the instruction states):

- H1. First/Last token splits for all six names (add-card `:18-19`;
  reconcile `:46-47`, `:52-53`, `:57-58`, `:63-64`, `:70-71`). Needs
  instruction clarification per §4. Do NOT repair by silently
  accepting any split unless the instruction is clarified to display
  semantics.
- H2. Catering Lead `organization: "Bench Catering"` must persist
  (reconcile `:54`). Instruction never mentions this record's company.
  Preserving meaning requires instruction clarification ("leave its
  company unchanged") — an evaluator-only retention rule invents a
  preservation duty the text states only for Bench Office. Do not add
  further preservation checks (e.g. note-absence) without the same
  instruction basis.

Overpermissiveness (evaluator admits instruction-violating states):

- O1. Superset phones/emails PASS. Comparator uses subset
  (`contacts_store.py:333-341`), but both instructions use exact-set
  language: "its phone numbers are 555-010-4400 and 555-010-4401"
  (reconcile `:4-6`); "phone numbers 555-010-4620 and 555-010-4621"
  (`:9-10`); singular "the phone number" / "the email address"
  (add-card `:4-5`). A card with all required values PLUS an extra
  phone/email still matches. Repair is EVALUATOR-side (exact-set
  comparison for these specs) and preserves meaning because the
  instruction's "are" already states replacement. This is not
  PASS-chasing: it closes a genuinely wrong PASS.
- O2. Extra note on add-card and on Catering Lead passes (spec note
  empty → `contacts_store.py:330` vacuous). Instruction is silent on
  notes there, so this is instruction-faithful permissiveness — NO
  repair recommended. Banning notes would invent a requirement.
- O3. Formatting/case leniency passes: phones compare digit-only
  (`:356-360`, so "5550102486", "(555) 010-2486" all match);
  emails/text compare case-insensitively (`:348-354`). Instructions
  state canonical forms but no formatting rule. This leniency is
  benign and standard; no repair recommended, noted only so future
  instructions can pin formatting if they mean it.
- O4. Duplicate-content cards are caught only by `exact_count`. Two
  identical "Bench Courier" cards each match the present spec
  (`:294-296` existential), and only `exact_count: 1` fails the run.
  Correct as paired; neither check alone suffices. No repair needed.

Not issues:

- Redundant `full_name` check (`:343-345`) adds no false PASS/FAIL
  beyond H1.
- `absent_contacts` partial-spec shape (§3.4) is correct staleness
  logic, not overpermissiveness.
- Poll/timeout params (`timeout_seconds`, `poll_interval_seconds`)
  affect timing only, not semantics.

---

## 6. Truth table (instruction-grounded, evaluator-independent)

Correct = meets every instruction word under display-name reading
(any First/Last split rendering the stated display is accepted).
Wrong = violates at least one word. (†) = current evaluator
disagrees; the dagger rows are the findings, not reasons to redefine
correctness.

### Names

- **A1 canonical correct** — display "Bench Courier", Bench/Courier
  split. Verdict: CORRECT.
- **A2 same display, degenerate split** — First "Bench Courier",
  Last empty. Verdict: CORRECT († FAILs). Proves H1.
- **A6 swapped display** — "Courier Bench". Verdict: WRONG.
- **B8 three-token re-split** — "Bench Catering Lead" as Bench
  Catering / Lead. Verdict: CORRECT († FAILs). Proves H1.
- **Missing/extra token** — "Bench" alone or "Bench Courier Extra".
  Verdict: WRONG.

### Company

- **A1 company "Bench Logistics"** — Verdict: CORRECT.
- **A3 company "Bench Logistics Desk" on add-card** — Verdict: WRONG.
- **B2 Catering company changed to "Other Co"** — Verdict: CORRECT
  under literal text († FAILs). Proves H2; needs instruction words.

### Phones

- **A1 single required phone only** — Verdict: CORRECT.
- **A4 required phone plus extra line** — Verdict: WRONG († PASSes).
  Proves O1 subset gap.
- **B3 Logistics triple set 4400/4401/extra** — Verdict: WRONG
  († PASSes). Same gap.
- **B7 old 4000 kept alongside 4400/4401** — Verdict: WRONG. Absent
  stale-value guard correctly fails it.

### Emails

- **A1 single required email only** — Verdict: CORRECT.
- **A5 required email plus extra address** — Verdict: WRONG († PASSes).
  Proves O1.
- **B4 Security email plus extra address** — Verdict: WRONG († PASSes).
  Same gap.
- **Wrong domain / off-by-one digit** — Verdict: WRONG under any reading.

### Extra contacts and notes

- **A7 duplicate A1 cards, count 2** — Verdict: WRONG. Only
  `exact_count` catches it; correct as paired checks.
- **B6 Venue Old still present** — Verdict: WRONG. Absent-name guard
  correctly fails it.
- **B5 Logistics keeps old dock note** — Verdict: WRONG. Present-note
  check correctly fails it.
- **B9 Office phone changed** — Verdict: WRONG. "Unchanged" plus seed
  violated.
- **A8 / B10 arbitrary extra note where silent** — Verdict: CORRECT.
  Do not ban; instruction is silent.

---

## 7. Recommendations (meaning-preserving only)

1. Clarify name semantics in BOTH instructions (instruction-side fix
   for H1): either pin structural splits ("first name Bench, last
   name Courier", "... last name Catering Lead", etc.) to keep current
   acceptance, or state display semantics ("contact displaying as ...;
   any First/Last split rendering that display is acceptable") and
   then repair the comparator call for these tasks to match normalized
   display name. Do not relax the evaluator without the instruction
   change — that would trade one invented intent for another.
2. Clarify Catering Lead preservation (instruction-side fix for H2):
   add "leave its company and note unchanged" if that is intended;
   then the current `organization: "Bench Catering"` acceptance
   follows. If instead the company is free, remove that acceptance
   line. Either direction preserves meaning once written; the current
   text underdetermines it.
3. Repair phone/email comparison to exact-set for specs that state a
   replacement set (evaluator-side fix for O1): fail a present match
   when normalized observed phones/emails exceed the stated set for
   Logistics, Security, add-card, and the updated Catering Lead
   channels. This enforces what "are"/"becomes"/"the" already say.
4. Make NO change for O2/O3 (notes silence, formatting leniency):
   adding constraints there would invent requirements to chase
   strictness, which this audit forbids.
5. Optionally name the Company→Organization mapping in instructions
   ("company (Organization field)") to remove the last vocabulary
   inference, though the current mapping is already the only
   reasonable reading.

---

## 8. Verdict

- add_contact_card: company/phone/email values and `exact_count: 1`
  (given seed) follow the instruction; the First/Last split does not —
  it is a hidden requirement. Subset phone/email matching is
  overpermissive against the instruction's exact-set language.
- reconcile: Logistics update, Venue Old deletion, Security creation,
  Office preservation, stale phone/email absent guards, and
  `exact_count: 4` (given seed) follow the instruction; Catering Lead
  company persistence and every First/Last split do not — both are
  hidden requirements as written. Superset phones/emails are
  overpermissive for the same exact-set reason.
- Required fixes are §7.1 (instruction names), §7.2 (instruction
  Catering preservation), §7.3 (evaluator exact-set). No other change
  preserves meaning; in particular, no constraint should be added
  merely to alter PASS rates.
