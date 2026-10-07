# CUA Tasks Review import

This task pack is restored from the reviewed run artifacts in
`Hengyuhan/CUA-Tasks-Review`. OS-Omni Live v1 selects 212 of its tasks within a
balanced 300-task release; see the [v1 guide](../tasks/v1/README.md).

The generated TaskSpec files live directly in the per-platform task folders:
`tasks/v1/android/`, `tasks/v1/ios/`, `tasks/v1/linux/`, `tasks/v1/macos/`, and
`tasks/v1/windows/`, plus `tasks/v1/web/` for browser tasks that run on the
Linux VM (`platform: linux`). The original source artifacts contain 303 tasks: 297 exact task
snapshots, one repaired partial snapshot, four records restored from
structured flat arguments, and one record reconstructed from its instruction
and recorded init/evaluation metadata.

Each generated `instruction` is an English, model-facing work request. It opens
with the overall deliverable and describes what each completed artifact should
contain, how the artifacts relate, and what final state should remain. The task
briefs preserve exact values and necessary dependencies without narrating UI
navigation or presenting a numbered tutorial. The reviewed briefs and their
source digests are stored in
`tasks/v1/cua_tasks_review_instructions.json`; the original instruction digest is
also retained in
`metadata.cua_tasks_review.source_instruction_sha256` for provenance.

Bundled evaluator source is restored into task-specific modules directly under
the corresponding `evaluators/<platform>/` folder. Task-specific module names
avoid silently combining historical evaluator files that used the same import
path but had different implementations.

When the checkout contains the curated `benchmark/` release, each task's
`args.json` and evaluator are taken from `benchmark/tasks/<app>/<Platform>/<task>/`
instead of the raw run artifact, because the release updated evaluation
parameters (ruleset digests, bundle ids, profile roots) together with the
evaluators. The family bases, state readers and runtime helpers those
evaluators import are mirrored under `evaluators/cua_review/` with their imports
rewritten, so the release's top-level `core`/`evaluators`/`platforms` names never
shadow OS-Omni's. `evaluators/cua_review/core/evaluation.py` is hand-written: it
puts the release's evaluator helpers on top of OS-Omni's `BaseEvaluator` and
`EvalResult`, which the platform runners require. Per-task evaluators the
release generates from a table but did not upload are restored by rerunning its
`benchmark/tools/write_*_evaluators.py` on a scratch copy; shipped files always
take precedence. `metadata.cua_tasks_review.release_path` records which tasks
came from the release.

Many reviewed evaluators bind themselves to the task they were written for:
they compare `task_id`, their original evaluator id, and the digest of the
source instruction. The importer therefore keeps the source digests in
`evaluation.params`, stores the source instruction in
`metadata.cua_tasks_review.source_instruction`, and rebinds
`expected_evaluator_source_sha256` / `expected_checkpoint_specs_sha256` to the
evaluator file it writes. Every platform runner adds these fields to the
evaluator context through `core/evaluation/context.py`, and the iOS runner adds
the run-bound simulator `udid` to the params. `checks/` scripts that an
evaluator loads next to itself are copied along with it. Defects in release
modules are fixed through `RELEASE_SOURCE_PATCHES` in the importer, which fails
the import if a patch no longer applies.

Initializers OS-Omni does not ship are taken from the release the same way:
the importer vendors the release module below `evaluators/cua_review/`, points
`init.initializer_id` at the vendored class, and records the release id in
`metadata.cua_tasks_review.original_initializer_id`. Release initializers do
not subclass OS-Omni's `BaseInitializer`; `core.init.load_initializer` wraps
any class under `evaluators.cua_review.` in the hand-written
`evaluators/cua_review/core/init_binding.py` adapter. The adapter converts the
release result into an `InitResult`, passes the iOS simulator `udid` bound to
the controller, and presents the OS-Omni controller through the release
controller API: script results also carry `stdout`/`stderr`, observations are
mappings, and `foreground_package`, `start_app`, and `is_alive` are derived from
`get_current_activity`, `execute_adb`, and `health` when the controller has
them. The release Android base rejected every installed app because it looked
for `package:<package>` in `pm path` output; `RELEASE_SOURCE_PATCHES` fixes it.

`tasks/v1/cua_tasks_review_manifest.json` is the reviewed-subset inventory. Its
`unresolved` field records initializers, evaluators, internal imports, or task
assets that were not present in either OS-Omni or the reviewed artifact pack.
An entry is `implementation_ready` only when those code and asset references
are locally resolvable; VM snapshots and applications are still external
runtime prerequisites.

Regenerate only the reviewed tasks selected by `tasks/v1/manifest.json` from a
local artifact checkout with:

```bash
python tools/import_cua_tasks_review.py /path/to/CUA-Tasks-Review --release v1
```

The English brief map can be regenerated against an OpenAI-compatible local
model endpoint with `tools/generate_cua_tasks_review_instructions.py`. Audit
and correction helpers are available in `tools/audit_cua_tasks_review_briefs.py`
and `tools/refine_cua_tasks_review_briefs.py`. These tools operate on the subset
covered by the supplied instruction map. Regeneration preserves the release
selection and does not restore excluded tasks.
