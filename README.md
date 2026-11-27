# OS-Omni Live

**OS-Omni: Benchmarking Generalist Computer-Using Agents on Long-Horizon Workflows Across Platforms**

[Project Page](https://os-copilot.github.io/OS-Omni-Home/) | [Paper (arXiv)](https://arxiv.org/pdf/2611.34232) | [Hugging Face Paper Page](https://huggingface.co/papers/2611.34232) | [Discord](https://discord.gg/fADJQaMTRb)

OS-Omni is a **live cross-platform GUI benchmark** and runtime stack for agent
evaluation. We release tasks in versioned waves of **300 tasks each**, starting
with **v1**. Future waves will be published as v2, v3, and so on. Report the
release version alongside evaluation results so comparisons use the same tasks.

## First release: v1

The [v1 task inventory](tasks/v1/manifest.json) contains **300 benchmark tasks**:

| Track | Tasks |
| --- | ---: |
| Android | 48 |
| iOS | 48 |
| Linux desktop | 48 |
| macOS | 48 |
| Windows | 48 |
| Web (browser on the Linux VM) | 48 |
| Cross-device (single screen) | 12 |
| **Total** | **300** |

Selection prioritizes the recently added Open-series applications, including
OpenBank, OpenShop, OpenTrip, OpenNote, and OpenTwitter. Other reviewed tasks
and earlier tasks fill the remaining slots. v1 includes 180 Open-series tasks.

The 12 cross-device workflows each run on one screen: the Linux or Windows
desktop shows a companion Android phone in a scrcpy window, and the agent works
on both, moves the file between them, and returns results to the phone. There
are six Linux + Android and six Windows + Android workflows, all at hard
difficulty. They replace the earlier cross-VM workflows, whose stage
definitions remain as supporting files and do not count as additional
benchmark tasks.

Task definitions and required local assets live under `tasks/v1/`. The
[release guide](tasks/v1/README.md) explains the layout and selection rules.
Execution configs covering each platform are in [`executions/v1/`](executions/v1/).
Tasks outside v1 have been removed from the working tree; earlier versions
remain available in Git history.

The task release does not bundle runtime prerequisites such as VM snapshots,
installed applications, or model credentials. Every task's initializer and
evaluator resolve locally; the reviewed import records its provenance in its
[manifest](tasks/v1/cua_tasks_review_manifest.json).

## Running v1

Each platform has its own runner; see the [repository guide](docs/REPOSITORY.md)
for setup documents.

| Track | Entry point |
| --- | --- |
| Linux desktop, Web | `scripts/run_linux_qemu_batch.py --execution executions/v1/{linux,web}.yaml` ([headless QEMU guide](docs/linux_headless.md)) |
| Cross-device | `scripts/run_linux_qemu_batch.py` with `executions/v1/cross_device_linux_android.yaml` or `--platform windows` and `executions/v1/cross_device_windows_android.yaml` ([Linux + Android](docs/linux_android_companion.md), [Windows + Android](docs/windows_android_companion.md)) |
| Windows | `python -m platforms.windows.cli --execution executions/v1/windows.yaml`, or `scripts/run_linux_qemu_batch.py --platform windows` on QEMU ([platform notes](platforms/windows/README.md)) |
| macOS | `python -m platforms.macos.host.cli --execution executions/v1/macos.yaml` ([platform notes](platforms/macos/README.md)) |
| iOS | `python -m platforms.ios.cli --execution executions/v1/ios.yaml` ([platform notes](platforms/ios/README.md)) |
| Android | `python -m platforms.android.cli --execution executions/v1/android.yaml`, or `local_eval/run_one.py` for a cold-reset single task ([Android setup](docs/android/HANDOVER.md)) |

## Results

* [`task_results.csv`](task_results.csv): per-task PASS/FAIL for every
  evaluated model.
* [`platform_summary.csv`](platform_summary.csv): per-platform totals.
* [`scan.csv`](scan.csv): the evaluator/instruction alignment scan of the v1
  tasks.

## Repository layout

The repository is organized around platform-specific benchmark runners, task
definitions, evaluators, and runtime integrations:

* `core/`: shared LLM, prompt, spec, and runtime abstractions.
* `platforms/`: Android, iOS, Linux, macOS, and Windows runtime code.
* `tasks/v1/`: the first 300-task release, supporting tasks, and task assets.
* `evaluators/`: task-specific evaluation logic.
* `initializers/`: task setup and environment seeding logic.
* `executions/v1/`: benchmark execution configs for the v1 tasks.
* `scripts/`, `tools/`: benchmark runners, environment setup, and maintenance
  helpers for the v1 task maps and re-scoring.
* `apps/`, `services/`, `assets/`: app sources, the OpenDriver backend, and
  fixtures used by v1 tasks.
* `local_eval/`: the Android host runner, cold reset, and local OpenDriver /
  GreenMail services.
* `workbench/`: local benchmark inspection UI.

Install dependencies from `pyproject.toml` or use the platform-specific setup
notes under `platforms/`.

## Virtual Machine Images

Preconfigured virtual machine images for OS-Omni are available on Hugging Face:

https://huggingface.co/datasets/Cloudriver/OS-Omni-VM/tree/main
