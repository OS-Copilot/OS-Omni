# OS-Omni Live — v1

This is the first release of OS-Omni Live. Each release wave contains 300
benchmark tasks. Use `v1` when reporting results from this task set.

## Inventory and counting

[`manifest.json`](manifest.json) is the authoritative list of the 300 benchmark
tasks: six single-platform tracks of 48 tasks each — Android, iOS, Linux
desktop, macOS, Windows, and Web — plus 12 cross-platform workflows: 6
single-screen cross-device tasks and 6 cross-VM workflows. Web tasks run in a
browser on the Linux VM, so their TaskSpec `platform` is `linux`. The
cross-device tasks run on the Linux desktop, so their platform is also `linux`.
The manifest records the track (`track_counts`) separately from the runtime
platform (`platform_counts`).

* `<track>/*.yaml`: the 288 single-platform tasks, one folder per track.
* `cross_device/*.yaml`: the 6 single-screen cross-device tasks (Linux + Android).
* `cross_vm/*.yaml`: the 6 cross-VM workflows (Windows → Linux).
* `cross_vm/stages/`: the per-VM stage definitions the workflows run. They are
  listed under `supporting.cross_vm_stages` and do not count as tasks.
* `oracle/` subdirectories: oracle companions for retained tasks.
* `<platform>/files/`: local fixtures needed by retained tasks.

## Cross-device tasks

Each cross-device task runs on one screen. The Linux desktop shows a companion
Android phone in a scrcpy window. The agent edits a file on the phone, moves it
to the desktop itself (for example through the synced clipboard), and finishes
the deliverable in LibreOffice. The result is decided by the phone's file, the
desktop copy, and the document. Any agent action that invokes or types `adb`
or `scrcpy` fails the task. The six tasks replace the Android → Windows
cross-VM workflows and keep their Markor sources and LibreOffice targets; the
retired workflows are listed under `retired`, and their stage files remain under
`cross_vm/stages/` as provenance. Environment setup:
[`docs/linux_android_companion.md`](../../docs/linux_android_companion.md).

| Screen + device | Workflow | Desktop app | Deliverables | Human steps (phone + desktop, excluding the transfer) |
|---|---|---|---|---|
| Linux + Android | `budget_review` | Calc | six-sheet review workbook | 96 + 232 = 328 |
| Linux + Android | `conference_schedule` | Writer | three room tables, speaker index, derived totals, PDF export | 88 + 132 = 220 |
| Linux + Android | `inspection_report` | Writer | prioritized failure table, item and unit rollups, PDF export | 102 + 108 = 210 |
| Linux + Android | `launch_review_minutes` | Writer | minutes with seven summary tables | 148 + 258 = 406 |
| Linux + Android | `regional_review_deck` | Impress | twelve slides with variance, status, follow-ups, summary | 51 + 124 = 175 |
| Linux + Android | `reorder_plan` | Calc | three sheets with priorities, supplier rollups, INDEX/MATCH summary, CSV export | 81 + 136 = 217 |

The step limit is the sum of the two source stages' limits (200 or 350). The
phone stages run on the Android V3 image. Their positive references do the
phone edit and the clipboard transfer through the real GUI, and the documents
come from the stage oracles.

## Cross-VM workflows

Each workflow runs a source stage on one VM, copies one file from it to the
target VM through the host, then runs the target stage. Only the target stage's
evaluator decides the result; a failed source stage fails the workflow.

| Route | Workflow | Target app | Target deliverables | Human steps (source + target) |
|---|---|---|---|---|
| Windows → Linux | `budget_review` | Calc | variance review with IF formulas and totals | 96 + 57 = 153 |
| Windows → Linux | `contract_renewals` | Writer | renewal table with computed notice dates, owner and month rollups | 60 + 159 = 219 |
| Windows → Linux | `incident_postmortem` | Writer | summary figures, timeline, per-service and follow-up tables | 80 + 138 = 218 |
| Windows → Linux | `launch_review_minutes` | Writer | minutes plus owner matrix and archive manifest | 92 + 74 = 166 |
| Windows → Linux | `payables_ledger` | Calc | three sheets with tax, size buckets, vendor and category rollups, CSV export | 26 + 127 = 153 |
| Windows → Linux | `shift_coverage` | Calc | three sheets with per-shift coverage gaps and summary, CSV export | 41 + 122 = 163 |

All six cross-VM workflows are hard and need at least 100 human steps end to end; every
target stage added for v1 needs at least 100 on its own. Each stage records its
estimate in `metadata.human_steps`, and the stages added for v1 (plus the two
original Linux targets) also list a `human_steps_breakdown`. One step is one
deliberate GUI action: a click or menu pick, a shortcut, or typing one cell,
line, or field. The v1 additions raise the stage step limit to 150 for source
stages and 200 for target stages. `budget_review` and `launch_review_minutes`
come from the original catalog, and their source stages copy a long file
exactly. The other four are new in v1, and their Windows stages filter,
de-duplicate, sort, or correct a file in Notepad (the cross-device phone stages
rebuild a CSV in Markor from a reference note and apply its corrections).
Every cross-VM workflow has a composite oracle under `cross_vm/oracle/` and
per-stage oracles under `cross_vm/stages/*/oracle/`.

## Selection

Each single-platform track takes tasks from the reviewed CUA-Tasks-Review
import first and fills the remainder from earlier OS-Omni tasks:

| Track | Reviewed import | Earlier tasks |
|---|---:|---:|
| Android | 48 | 0 |
| iOS | 34 | 14 |
| Linux desktop | 10 | 38 |
| macOS | 33 | 15 |
| Web | 48 | 0 |
| Windows | 39 | 9 |

Web covers the Open-series web applications; Linux desktop covers native
applications (Blender, Thunderbird, Delta Chat, LibreOffice, GIMP, Marble,
Wireshark, Zotero, and others). Tasks on the Linux VM must have an importable
initializer. iOS, macOS, and Windows fills come from the previous v1 selection;
Linux desktop fills come from the original Linux catalog, excluding duplicates
of reviewed tasks and tasks without a resolvable evaluator or initializer.

Within a track, tasks are drawn round-robin across applications for coverage.
Ties favor implementation-ready tasks, tasks already reviewed for v1, more
recent tasks, oracle companions and hard difficulty, then task ID. Retired
tasks and their unused assets remain recoverable from Git history.

To make room for the cross-VM workflows, two tasks were retired from each
single-platform track; the manifest lists them under `retired`. A track retires
tasks without a resolvable initializer first. Linux desktop has none, so it
retires tasks whose declared oracle companion is missing; Web has no dependency
gaps and retires by coverage only. Among the candidates, tasks come from the
application with the most tasks in the track (the Open-series photo-edit
variants count as one application), preferring non-Open-series applications on
ties, then non-hard tasks without an oracle companion.

## Execution and provenance

Use the platform entrypoints documented under [`platforms/`](../../platforms/)
with the corresponding [`executions/v1/`](../../executions/v1/) config. For example:

```bash
python -m platforms.android.cli --execution executions/v1/android.yaml
python -m platforms.linux.cli --execution executions/v1/web.yaml
python -m platforms.cross_vm.cli --execution executions/v1/cross_vm.yaml
python -m platforms.linux.cli --execution executions/v1/cross_device.yaml  # with a companion phone
```

Set up the required applications, VM snapshots, and model credentials first.
The reviewed subset contains 212 tasks. Its
[`cua_tasks_review_manifest.json`](cua_tasks_review_manifest.json) records source
provenance and any missing initializers, evaluators, imports, or assets. All
212 reviewed tasks currently have every recorded local code and asset
reference resolved; 130 of them use release initializers vendored from the
artifact pack (see [the import notes](../../docs/cua_tasks_review.md)). This is
a static dependency check, not a VM execution result.
English briefs and their source digests are preserved in
[`cua_tasks_review_instructions.json`](cua_tasks_review_instructions.json).
