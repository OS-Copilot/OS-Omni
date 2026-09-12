# CUA Tasks Review import

This task pack is restored from the reviewed run artifacts in
`Hengyuhan/CUA-Tasks-Review`.

The generated TaskSpec files live directly in the per-platform task folders:
`tasks/android/`, `tasks/ios/`, `tasks/linux/`, `tasks/macos/`, and
`tasks/windows/`. The source artifacts contain 303 tasks: 297 exact task
snapshots, one repaired partial snapshot, four records restored from
structured flat arguments, and one record reconstructed from its instruction
and recorded init/evaluation metadata.

Each generated `instruction` is an English, model-facing work request. It opens
with the overall deliverable and describes what each completed artifact should
contain, how the artifacts relate, and what final state should remain. The task
briefs preserve exact values and necessary dependencies without narrating UI
navigation or presenting a numbered tutorial. The reviewed briefs and their
source digests are stored in
`tasks/cua_tasks_review_instructions.json`; the original instruction digest is
also retained in
`metadata.cua_tasks_review.source_instruction_sha256` for provenance.

Bundled evaluator source is restored into task-specific modules directly under
the corresponding `evaluators/<platform>/` folder. Task-specific module names
avoid silently combining historical evaluator files that used the same import
path but had different implementations.

`tasks/cua_tasks_review_manifest.json` is the machine-readable inventory. Its
`unresolved` field records initializers, evaluators, internal imports, or task
assets that were not present in either OS-Omni or the reviewed artifact pack.
An entry is `implementation_ready` only when those code and asset references
are locally resolvable; VM snapshots and applications are still external
runtime prerequisites.

Regenerate the pack from a local artifact checkout with:

```bash
python tools/import_cua_tasks_review.py /path/to/CUA-Tasks-Review
```

The English brief map can be regenerated against an OpenAI-compatible local
model endpoint with `tools/generate_cua_tasks_review_instructions.py`. Audit
and correction helpers are available in `tools/audit_cua_tasks_review_briefs.py`
and `tools/refine_cua_tasks_review_briefs.py`.
