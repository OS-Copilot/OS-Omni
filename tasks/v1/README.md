# OS-Omni Live — v1

This is the first release of OS-Omni Live. Each release wave contains 300
benchmark tasks. Use `v1` when reporting results from this task set.

## Inventory and counting

[`manifest.json`](manifest.json) is the authoritative list of the 300 benchmark
tasks: six single-platform tracks of 48 tasks each — Android, iOS, Linux
desktop, macOS, Windows, and Web — plus 12 single-screen cross-device
workflows. Web tasks run in a browser on the Linux VM, so their TaskSpec
`platform` is `linux`. A cross-device task's platform is the desktop that shows
the phone: `linux` for the six Linux + Android tasks and `windows` for the six
Windows + Android tasks. The manifest records the track (`track_counts`)
separately from the runtime platform (`platform_counts`).

* `<track>/*.yaml`: the 288 single-platform tasks, one folder per track.
* `cross_device/*.yaml`: the 12 single-screen cross-device tasks (6 Linux +
  Android, 6 Windows + Android).
* `cross_vm/stages/`: the per-VM stage definitions of the retired cross-VM
  workflows, which the cross-device tasks were converted from. They are listed
  under `supporting.cross_vm_stages` and do not count as tasks.
* `oracle/` subdirectories: oracle companions for retained tasks.
* `<platform>/files/`: local fixtures needed by retained tasks.

## Cross-device tasks

Each cross-device task runs on one screen and makes a round trip. The Linux or
Windows desktop shows a companion Android phone in a scrcpy window. The agent:

1. edits or builds a file in Markor on the phone;
2. moves it to the desktop itself (for example through the synced clipboard);
3. builds the deliverable in LibreOffice;
4. sends results computed on the desktop back to the phone. Depending on the
   task, these are a Markor note, items in the Tasks app, events in the Calendar
   app, or the exported file dropped onto the phone window.

The result is decided by:

* the phone's source file, return note, Tasks items and Calendar events
  (exactly the expected ones and no others);
* the copies on the phone, which must match the desktop files;
* the desktop copy and the document.

Any agent action that invokes or types `adb` or `scrcpy` fails the task. The
Linux + Android tasks replace the Android → Windows cross-VM workflows and keep
their Markor sources and LibreOffice targets. The Windows + Android tasks replace
the Windows → Linux workflows: the Notepad stage moves to Markor on the phone and
the LibreOffice stage to the Windows desktop, with the same checks. The retired
workflows are listed under `retired`, and their stage files remain under
`cross_vm/stages/` as provenance. Environment setup:
[`docs/linux_android_companion.md`](../../docs/linux_android_companion.md) and
[`docs/windows_android_companion.md`](../../docs/windows_android_companion.md).

| Screen + device | Workflow | Desktop app | Deliverables | Back on the phone | Human steps (phone + desktop, excluding the transfer and return) |
|---|---|---|---|---|---|
| Linux + Android | `budget_review` | Calc | six-sheet review workbook | Markor control note; 4 Tasks items | 96 + 232 = 328 |
| Linux + Android | `conference_schedule` | Writer | three room tables, speaker index, derived totals, PDF export | PDF onto the phone; 2 Calendar events | 88 + 132 = 220 |
| Linux + Android | `inspection_report` | Writer | prioritized failure table, item and unit rollups, PDF export | PDF onto the phone; 5 Tasks items | 102 + 108 = 210 |
| Linux + Android | `launch_review_minutes` | Writer | minutes with seven summary tables | DOCX onto the phone; 3 Calendar events | 148 + 258 = 406 |
| Linux + Android | `regional_review_deck` | Impress | twelve slides with variance, status, follow-ups, summary | Markor follow-up note; 3 Tasks items | 51 + 124 = 175 |
| Linux + Android | `reorder_plan` | Calc | three sheets with priorities, supplier rollups, INDEX/MATCH summary, CSV export | CSV onto the phone; 2 Tasks items | 81 + 136 = 217 |
| Windows + Android | `budget_review` | Calc | variance review with IF formulas and totals | Markor follow-up note; 5 Tasks items | 96 + 57 = 153 |
| Windows + Android | `contract_renewals` | Writer | renewal table with computed notice dates, owner and month rollups | 5 Calendar events | 60 + 159 = 219 |
| Windows + Android | `incident_postmortem` | Writer | summary figures, timeline, per-service and follow-up tables | DOCX onto the phone; 3 Tasks items | 80 + 138 = 218 |
| Windows + Android | `launch_review_minutes` | Writer | minutes plus owner matrix and archive manifest | owner matrix CSV onto the phone; 2 Tasks items | 92 + 74 = 166 |
| Windows + Android | `payables_ledger` | Calc | three sheets with tax, size buckets, vendor and category rollups, CSV export | CSV onto the phone; 6 Tasks items | 26 + 127 = 153 |
| Windows + Android | `shift_coverage` | Calc | three sheets with per-shift coverage gaps and summary, CSV export | Markor gap note; 3 Calendar events | 41 + 122 = 163 |

The step limit is the sum of the two source stages' limits plus 100 for the
return (300 or 450), and at least 1.5 times the human step count, rounded up to
50 (500 for Linux `budget_review`, 650 for Linux `launch_review_minutes`). The
phone runs the Android V3 image. Each task is validated three ways:

* a negative check (initializer only) fails;
* the deliverables without the return part fail;
* a positive reference passes. It does the phone edit and the clipboard
  transfer through the real GUI, and the documents come from the stage
  oracles. For `budget_review` and `conference_schedule` the return part (Markor
  note, Tasks items, Calendar events) is also done through the real GUI; the
  other tasks apply it at state level in the format the apps' GUIs store. The
  Windows + Android references write the phone file and the Desktop copy at
  state level, build the document with the Linux stage oracle's Python on
  Windows, and apply the return at state level.

## Cross-VM stages

The twelve cross-VM workflows of earlier drafts (six Android → Windows, six
Windows → Linux) ran a stage on one VM, copied a file through the host, and
finished on another VM. All twelve were replaced by the single-screen
cross-device tasks above and are listed under `retired`. Their stage files and
per-stage oracles stay under `cross_vm/stages/` because the cross-device tasks
were generated from them (`metadata.source_stages`). The v1 stages record their
human step estimate in `metadata.human_steps`; one step is one deliberate GUI
action: a click or menu pick, a shortcut, or typing one cell, line, or field.

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

To make room for the cross-platform workflows, two tasks were retired from each
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
python scripts/run_linux_qemu_batch.py --execution executions/v1/cross_device_linux_android.yaml ...  # with a companion phone
python scripts/run_linux_qemu_batch.py --platform windows --execution executions/v1/cross_device_windows_android.yaml ...
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
