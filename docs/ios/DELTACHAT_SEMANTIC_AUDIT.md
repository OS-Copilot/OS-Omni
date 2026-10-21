# DeltaChat iOS semantic audit (independent, read-only)

Scope: the four task specs in `tasks/v1/ios/deltachat*.yaml` checked against
the deterministic reference specs in the matching
`evaluators/ios/deltachat*.py` evaluators. No task or evaluator file was
changed (out of ownership for this phase); no GUI, device, model, credential,
historical-simulator, or prior model-output asset was inspected. Source-message
contents are unknown, so each source message is counted as exactly one logical
line (the same single-line assumption every evaluator's `_resolve_line_spec`
makes: unknown source resolves to `None`, never to extra lines). The
inaccessible stable source simulator is not a blocker: every claim below is
decided by the YAML instruction text plus the evaluator source.

## Findings

### F1 — 4_4 handoff: 7 vs 8 lines, reversed Nora pair, 17 vs 18 vs 19 lines

Task instruction (`tasks/v1/ios/deltachat_route_handoff_saved_messages_4_4.yaml:5`)
says the initial note version is exactly seven lines in this order:
`# Handoff log`, `Route handoff`, Mei content, `Owner Mei`, Nora content,
`Receiver Nora`, `Status offered`.
The evaluator's `V1_LINE_SPEC`
(`evaluators/ios/deltachat_route_handoff_saved_messages_4_4.py:58-67`) has
eight entries: it prepends a `Handoff Log 0728` filename/title line and it
places `Receiver Nora` *before* the Nora source instead of after it. The
historical GUI trace in the same YAML (steps 23–27,
`deltachat_route_handoff_saved_messages_4_4.yaml:102-108`) types
`Receiver Nora` (step 24) before pasting the Nora message (step 27), so the
trace agrees with the evaluator and disagrees with the instruction on that
pair. An instruction-faithful note therefore fails the evaluator, and an
evaluator-faithful note violates the instruction: a genuine wrong-negative
either way.

The final version compounds the error. The instruction
(`deltachat_route_handoff_saved_messages_4_4.yaml:7`) appends eleven lines and
then claims the total is exactly 17, but 7 + 11 = 18, not 17. The evaluator's
`V2_LINE_SPEC` (`deltachat_route_handoff_saved_messages_4_4.py:68-80`) is
`V1_LINE_SPEC` (8) plus the same eleven appended entries, i.e. 19 lines, and
the YAML's own verifier rules restate 8/19
(`deltachat_route_handoff_saved_messages_4_4.yaml:50-55`), contradicting the
instruction's 7/17 one page above it.

### F2 — 4_3 launch checklist: note agrees at 18, Saved Messages says 2 vs 3

The eighteen content lines agree: the instruction enumerates 18 items
(`tasks/v1/ios/deltachat_launch_checklist_saved_messages_4_3.yaml:4-15`) and
`V1_LINE_SPEC` (6) + 12 appended entries = 18
(`evaluators/ios/deltachat_launch_checklist_saved_messages_4_3.py:56-77`).
This evaluator strips the app-managed `TITLE` prefix before comparing
(`deltachat_launch_checklist_saved_messages_4_3.py:740-748`), so its count is
directly comparable to the instruction — the correct pattern the other three
evaluators do not follow (see F4).

The Saved Messages count disagrees. The instruction's final state demands
"exactly two new items in chronological order: the note attachment and the
forwarded Bob Ops message"
(`deltachat_launch_checklist_saved_messages_4_3.yaml:13-15`), but the trace in
the same file performs two attachment sends (steps 25 and 73) plus the forward
(step 79), and the evaluator requires exactly those three outputs in
`v1 < v2 < forward` order
(`evaluators/ios/deltachat_launch_checklist_saved_messages_4_3.py:535-565`;
YAML verifier rules restate three at
`deltachat_launch_checklist_saved_messages_4_3.yaml:54-56`). An
instruction-faithful run that shares the note only once can never satisfy the
evaluator's three-output check.

### F3 — 4_2 route approval: title merged into line 1

The instruction's first note is thirteen content lines starting with
`# Route gate`
(`tasks/v1/ios/deltachat_route_approval_saved_messages_4_2.yaml:7`), and the
second note is two lines starting with `# Route follow-up`
(`deltachat_route_approval_saved_messages_4_2.yaml:9`). The evaluator's specs
instead merge the note title into the first line with no line feed:
`Route Gate 0728# Route gate` (13 entries total) and
`Route Followup 28# Route follow-up` (2 entries total)
(`evaluators/ios/deltachat_route_approval_saved_messages_4_2.py:73-91`), while
its `_logical_lines` performs no title stripping
(`deltachat_route_approval_saved_messages_4_2.py:1122-1127`). The literal
`Route Gate 0728# Route gate` appears in neither the instruction's thirteen
lines nor any plausible file rendering of them, so exact-byte equality
(`deltachat_route_approval_saved_messages_4_2.py:660-690`) is unreachable from
the instruction as written. Source order (Mei, Alice, Bob, Nora) is consistent
between instruction, trace, and evaluator — the one ordering in this family
with no dispute.

### F4 — 4_1 mobile brief: same title-merge pattern, orders otherwise sound

Both note specs merge title and heading (`Mobile Brief 0728# Mobile brief`,
`Mobile Risks 0728# Mobile risks`, 7 entries each;
`evaluators/ios/deltachat_mobile_qa_brief_saved_messages_4_1.py:64-81`) with
no title stripping in `_logical_lines`
(`deltachat_mobile_qa_brief_saved_messages_4_1.py:1015-1024`), while the
instruction treats the title as the note's name and `# Mobile brief` /
`# Mobile risks` as the first content lines
(`tasks/v1/ios/deltachat_mobile_qa_brief_saved_messages_4_1.yaml:7`). Same
unreachable-first-line defect as F3. The four-output Saved Messages order
(status, first attachment, second attachment, two-line archive) is consistent
between instruction
(`deltachat_mobile_qa_brief_saved_messages_4_1.yaml:9`) and evaluator
(`deltachat_mobile_qa_brief_saved_messages_4_1.py:754-775`), and per-note
source assignment (Nora/Alice to note one, Bob/Mei to note two) matches on
both sides.

### F5 — provenance/reference rules that punish valid business state

Several checks constrain *how* the state was produced rather than *what* it
contains, so a byte-correct final state built by any other valid route fails:

- Cross-app creation/edit/share chronology (`..._4_1.py:777-789`,
  `..._4_2.py:817-849`) requires interleavings such as note birth < summary
  send < note final mtime < share. A semantically identical state written in a
  different order (e.g. both notes fully authored before any send) is rejected
  although every file byte and message is correct.
- Strictly distinct message ids *and* timestamps for business order
  (`..._4_4.py:663-687`, `..._4_3.py:535-565`) rejects states where two
  outputs share a timestamp, which the instruction never forbids.
- Application version and boot-session freshness binding
  (`..._4_2.py:31-36,382-390,405-409`) ties PASS to one app build pair and to
  the current boot session, i.e. to the historical harness rather than to the
  delivered content.

These rules go beyond the "final business evidence / data source priority"
contract stated in each YAML's own `verifier_rules` (durable db/file/blob
state only, trajectory and recordings forbidden). Minimal repair keeps the
byte/provenance/order invariants on content and narrows or drops the
timestamp-interleaving, distinct-timestamp, and version/boot gates to
non-blocking diagnostics.

## Proposed canonical correct references

Placeholders stand for one complete unknown baseline message each (single
logical line). `TITLE` handling is the open choice noted per task.

- 4_4 v1 (trace/evaluator-aligned, 8 lines): `Handoff Log 0728`,
  `# Handoff log`, `Route handoff`, 〈Mei〉, `Owner Mei`, `Receiver Nora`,
  〈Nora〉, `Status offered`. Instruction-literal v1 (7 lines) swaps the last
  pair: 〈Nora〉 before `Receiver Nora`. Repair options: (a) keep evaluator,
  fix instruction to 8 lines in evaluator order; (b) keep instruction, fix
  evaluator order and drop the title entry. Either way fix 17 to 18 (7+11) or
  19 (8+11) consistently.
- 4_4 v2 (trace/evaluator-aligned, 19 lines): v1 plus `Design packet`,
  〈Alice〉, `Sender Alice`, `Ops receipt`, 〈Bob〉, `Receiver Bob`,
  `Closure logged`, `Monitor Bob`, `Escalation Mei`, `Status accepted`,
  `Archive local`.
- 4_3 final (agreed, 18 lines): `# Launch gate`, `Readiness draft`, 〈Bob〉,
  `Build 166`, `Owner Bob`, `Ops green`, `Cutover route`, 〈Mei〉,
  `Window 1740`, `Mobile verifier`, 〈Nora〉, `Gate ship ready`,
  `Decision proceed`, `Support Nora`, `Evidence linked`, `Risk no Sev1`,
  `Monitor active`, `Status ready`; readiness v1 is the first 6. Saved
  Messages must be exactly three outputs: v1 attachment, v2 attachment, Bob
  forward — repair the instruction's "exactly two".
- 4_2 first note (13 content lines): `# Route gate`, `Status pending`,
  `Decision evidence`, 〈Mei〉, `Design condition`, 〈Alice〉,
  `Ops condition`, 〈Bob〉, `Release verifier`, 〈Nora〉, `Decision approve`,
  `Owner Mei`, `Condition green`; second note (2 lines): `# Route follow-up`,
  `Approved by Mei`. Repair: define title handling once (adopt the 4_3
  strip-title convention) and replace the merged `Title# Heading` literals.
- 4_1 note one (7 content lines): `# Mobile brief`, 〈Nora〉,
  `Scope build 166`, `Owner Alice`, `Design decision`, 〈Alice〉,
  `Gate mobile ready`; note two: `# Mobile risks`, 〈Bob〉, `Risk no Sev1`,
  `Ops green`, `Route decision`, 〈Mei〉, `Gate ship ready`. Same title repair
  as 4_2.

## Ambiguities

- Whether an FSNotes title is a file-content line at all differs per
  evaluator (4_3 strips it, 4_4 keeps it as its own line, 4_1/4_2 fuse it with
  the heading). The specs alone do not disclose the on-disk rendering, so the
  canonical choice above follows the majority-trace reading; confirm against
  one real FSNotes file before repairing.
- Whether a historical source message could itself contain a newline is
  unknowable from the supplied specs (content unknown); all counts assume one
  line per source, matching every evaluator's resolver.
- For the 4_4 Nora pair, instruction order and trace order genuinely conflict;
  the audit recommends the trace order only because the evaluator and all 75
  GUI steps agree on it, not because the instruction is ambiguous.

## Versioning

Each task YAML binds to its evaluator by `expected_ruleset_sha256`, the hash
of the evaluator's `RULESET_SPEC`. Any spec repair — even a one-line order
swap — changes that digest, so repairs must ship as new ruleset versions
(e.g. `schema_version` 2.0 → 2.1 with a recorded supersedes link), updating
the YAML's `expected_ruleset_sha256`, `instruction_sha256`, and affected
`verifier_rules` text together. The original ruleset identity (task id +
digest + this audit) must be preserved in history so past results stay
interpretable; never edit a line spec in place while keeping the old digest.

## Tests

`tests/test_ios_deltachat_semantics.py` pins every claim above as pure,
device-free checks: line-spec lengths parsed from the evaluator sources,
instruction-vs-evaluator order comparisons with opaque single-line source
placeholders, Saved Messages count contradictions, title-handling divergence,
and a wrong-negative demonstration (instruction-faithful 4_4 v1 ≠ evaluator
v1). The tests assert the mismatches exist; when the repair lands, the
affected pins must be updated to the new canonical references and ruleset
digests together.

## Repair record (ruleset 2.0 → 2.1, 2026-10-10)

Authorization: benchmark author authorized evaluation semantic repair.
Instructions ruled authoritative over historical trace/oracle throughout;
no GUI, model, credential, or push was used. Full digest history lives in
`docs/ios/DELTACHAT_RULESET_REVISIONS.json`; the paragraphs below summarize
what changed and what remains open for root live validation.

- F1 (4_4): evaluator V1 is now the 7 instruction-ordered content lines
  (`# Handoff log` first; Nora source before `Receiver Nora`), V2 appends
  the same 11 lines (18 total). The filename title is not content and is
  not stripped — strict bytes, root GUI-validates. Instruction and verifier
  rules corrected 17 → 18 and 8/19 → 7/18. The trace's reversed Nora pair
  is retained as provenance and explicitly overruled.
- F2 (4_3): instruction now requires exactly three new items — readiness
  v1 attachment, final v2 attachment, forwarded Bob message, in
  v1 < v2 < forward order. No stated operation was deleted.
- F3 (4_2) / F4 (4_1): line specs are the stated content lines only
  (13/2 and 7/7); each evaluator has an explicit normalizer for its two
  app-managed creation-title prefixes, consistent with the 4_3 pattern —
  any other prefix is strict wrong content and still FAILs.
- F5: distinct-timestamp strictness relaxed to non-decreasing order
  (distinctness kept as a diagnostic) on all four tasks; 4_2 app-version /
  simulator / boot gates and 4_1 + 4_2 cross-app chronologies are now
  non-blocking diagnostics. Post-baseline freshness, source provenance,
  exact order/newlines/bytes, distinct revisions, byte-identical finals,
  and the required forward remain acceptance conditions.
- `tests/test_ios_deltachat_semantics.py` now asserts the corrected
  expectations (not the old mismatches): canonical 7/18, 6/18 + forward,
  13/2, 7/7 pins; isolated fixture PASS on canonical refs; FAIL on empty
  init baseline, wrong source, wrong order, missing line, and wrong
  attachment bytes; YAML↔evaluator digest binding.

Unresolved assumptions for root live validation:

1. Each unknown source message is assumed to occupy exactly one logical
   line (every evaluator's resolver behavior). If a real baseline message
   contains a newline, line counts shift and the canonical refs need a
   device-proven update.
2. FSNotes on-disk title rendering was not observed on a device here. 4_3
   keeps its proven strip convention; 4_2/4_1 normalize only the two
   explicit title prefixes each; 4_4 strips nothing. Confirm against one
   real FSNotes file during live validation.
3. Legacy copies at `tasks/ios/deltachat*.yaml` (outside this repair's
   ownership) still pin the superseded 2.0 digests and the old
   instructions; they will fail binding against the repaired evaluators
   until they are re-imported.
4. No live-device (DS) run exists yet — no claim in this record refers to
   DS output. Acceptance still requires the root GUI-validated run.
