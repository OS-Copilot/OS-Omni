# Contacts Multi-Field Directory — Instruction-Only Semantic Audit (Note Final Period)

**Scope.** Independent instruction-only audit. Sources read ONLY:

- `tasks/v1/ios/contacts_reconcile_multi_field_directory.yaml`
- `platforms/ios/contacts_store.py`
- `evaluators/ios/contacts_state.py`

No formal/audit outputs, screenshots, logs, results, environment, or model/device/service state were inspected. No source/task code was modified. No failure evidence was supplied; nothing in this note adapts any standard to any failure or aims to improve model scores.

**Verdict: AMBIGUITY EXISTS — conservative author-side instruction repair recommended; verifier must NOT be relaxed.**

## 1. Strict expected strings (evaluator contract)

Task YAML `evaluation.params.present_contacts` states, exactly:

- Bench Logistics note: `"Use loading dock entrance."` — YAML line 53, **with final `.`**.
- Bench Security note: `"Badge desk closes at 21:00."` — YAML line 68, **with final `.`**.
- Bench Office note: `"Keep this record unchanged."` — YAML line 76, **with final `.`**.

## 2. Instruction narrative (unquoted — the defect)

Task YAML `instruction` states, in running prose without quotation marks or other delimiters:

- Logistics (lines 4–6): `... its note is Use loading dock entrance.`
- Security (lines 10–12): `... and note Badge desk closes at 21:00.`

In each case a single trailing `.` serves double duty: it is simultaneously (a) plausibly part of the required note value and (b) the ordinary sentence-final period of the instruction sentence itself. Nothing in the narrative — no quotes, code span, capitalisation cue, or "including the trailing period / with period" gloss — disambiguates reading (a) from reading (b).

A careful author and a careful agent can therefore both reasonably produce:

- (a) `Use loading dock entrance.` / `Badge desk closes at 21:00.` (period included), or
- (b) `Use loading dock entrance` / `Badge desk closes at 21:00` (period excluded as mere sentence punctuation).

The instruction as written does not select between them. That is a genuine semantic ambiguity, not a readability nit.

## 3. Comparator strictness (why the ambiguity is load-bearing)

`platforms/ios/contacts_store.py`:

- `contact_matches_spec`, lines 339–340: `if spec.note and cls._normalize_text(record.note) != cls._normalize_text(spec.note): return False`.
- `_normalize_text`, lines 365–367: `" ".join(str(value or "").strip().casefold().split())` — case-folds and collapses whitespace but **preserves punctuation**.

So the trailing `.` is significant. `Use loading dock entrance` does NOT match `Use loading dock entrance.` under the shipped comparator, and likewise for the Security note. Reading (b) above therefore fails the shipped verifier while reading (a) passes. The instruction leaves open exactly the distinction the verifier enforces.

`evaluators/ios/contacts_state.py` adds no note-level tolerance of its own; it delegates to `store.assert_state(params)` (lines 39, 46–60) and reports pass/fail. There is no fuzzy/period-insensitive path to absorb the ambiguity.

## 4. Office unchanged constraint — exact, no issue

Instruction line 13: `Leave the contact with first name Bench and last name Office unchanged.`

This states no literal replacement value, so there is no trailing-punctuation duality. Its meaning (do not edit Bench Office; seed note `"Keep this record unchanged."` at YAML line 41 must still match expected line 76) is exact and must remain exact. The repair below does not touch it.

## 5. Conservative author repair (instruction clarification only)

Principle: quote the **existing** strict expected strings in the instruction; change no comparator, business requirement, phone/email exactness, count, absence guard, or expected value.

Proposed instruction edit (author to apply; not applied by this audit):

- Logistics: `... and its note is "Use loading dock entrance."` — quoting the existing YAML line 53 string verbatim, period inside the quotes.
- Security: `... and note "Badge desk closes at 21:00."` — quoting the existing YAML line 68 string verbatim, period inside the quotes.
- Leave every other clause byte-identical, including line 8 (`leaving its company unchanged as Bench Catering.`, which names a value without terminal punctuation collision only because the sentence continues) and line 13 (Office unchanged).

Why this form:

- It preserves all comparator/business requirements: expected notes, `exact_phones`/`exact_emails`, `exact_count: 4`, absent-contact stale-value guards, and seed values are untouched.
- Quotation is the minimal disambiguator: the period is visibly inside the literal, so no "including the period" meta-gloss is needed and no new normative wording is introduced.
- It does not move the task goalposts: the required on-device strings before and after the repair are identical to the current evaluator strings.

Alternatives rejected:

- **Verifier relaxation** (strip trailing periods, period-insensitive note compare): rejected — see §6.
- **Rewording values to avoid terminal periods**: rejected — gratuitously changes business data and invalidates the existing strict strings.
- **Leaving unquoted with a parenthetical "(including the final period)"**: acceptable but wordier than quoting; quoting is preferred as self-demonstrating.

## 6. Why clarify the instruction rather than relax the verifier

1. **Intent preservation.** The seeded data already treats notes as complete sentences ending in `.` (`"Old dock instructions."`, `"Keep this record unchanged."`, YAML lines 25, 41). The expected notes continue that convention. Relaxing the comparator to ignore a trailing period would bless a second, unintended data shape (sentence fragment) as correct and weaken the note check for all current and future tasks sharing `contact_matches_spec`.
2. **Least privilege.** Instruction text is the ambiguous layer; the store comparator (case/whitespace-normalised, punctuation-exact) is deliberate shared infrastructure. Fix the layer that is wrong.
3. **No score-driven standard-shifting.** No failure evidence was supplied and none was consulted. This repair is justified purely by the text-level ambiguity (§2–§3), so it is independent of any agent outcome and cannot be read as adapting the standard to failures.
4. **Versions/disclosure.** Any author edit to the instruction is a task-text change: it should bump/record the task revision and disclose the before/after instruction diff in the task changelog, while explicitly stating the evaluator/store are unchanged. Consumers of prior revisions must be able to tell which wording an attempt ran against.
5. **Fresh formal runs required.** After the repair, the task must be re-run through the normal formal pipeline from scratch. This audit performed no execution and asserts no outcome; only a fresh formal run on the revised wording can confirm the clarified instruction and the unchanged verifier agree end to end.

## 7. Independent valid-reference vs wrong-text truth table

"Valid reference" = the existing strict evaluator strings, quoted independently of the instruction prose. "Wrong-text" = the period-dropped readings a reasonable reader could produce under reading (b). Comparator model: `IOSContactsStore.contact_matches_spec` note equality (case/whitespace-insensitive, punctuation-exact).

| # | Contact.field | Entered (device) text | Reference (existing strict expected) | Verifier outcome under shipped comparator | Instruction-ambiguity reading |
|---|---|---|---|---|---|
| V1 | Logistics.note | `Use loading dock entrance.` | `Use loading dock entrance.` | PASS | Reading (a): period is content |
| W1 | Logistics.note | `Use loading dock entrance` (no final period) | `Use loading dock entrance.` | FAIL | Reading (b): period was sentence punctuation |
| V2 | Security.note | `Badge desk closes at 21:00.` | `Badge desk closes at 21:00.` | PASS | Reading (a): period is content |
| W2 | Security.note | `Badge desk closes at 21:00` (no final period) | `Badge desk closes at 21:00.` | FAIL | Reading (b): period was sentence punctuation |
| V3 | Office.note (unchanged) | `Keep this record unchanged.` | `Keep this record unchanged.` | PASS | Exact; no ambiguity |
| W3 | Office.note (edited) | Any edit, including period drop/add | `Keep this record unchanged.` | FAIL | Violates unchanged constraint |

Notes on the table:

- V1/V2 are the only instruction-compliant passing values; W1/W2 are instruction-plausible but verifier-failing, which is precisely the hazard.
- Case/whitespace variants of V1/V2 (e.g. extra spaces) still pass per `_normalize_text`; any punctuation variant (missing/added/doubled period) fails. The repair does not alter this.
- V3/W3 confirm the Office constraint is unaffected by the ambiguity and needs no repair.

## 8. Bottom line

Unquoted instruction narrative does **not** disambiguate the final period in the edited Logistics and new Security note values against the strict, period-including evaluator strings; a period-dropped entry is a reasonable reading of the current instruction and a certain failure under the shipped comparator. Recommend the conservative author repair in §5 (quote the two existing strict note strings verbatim in the instruction), with version/disclosure bookkeeping and fresh formal runs per §6. Office unchanged constraint: no issue, keep exact.
