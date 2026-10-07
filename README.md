# OS-Omni Live

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
| Cross-VM | 12 |
| **Total** | **300** |

Selection prioritizes the recently added Open-series applications, including
OpenBank, OpenShop, OpenTrip, OpenNote, and OpenTwitter. Other reviewed tasks
and earlier tasks fill the remaining slots. v1 includes 181 Open-series tasks.

The 12 cross-VM workflows each run a stage on one VM, move a file through the
host, and finish on another VM: six Android-to-Windows and six Windows-to-Linux
workflows, all at hard difficulty. Their stage definitions and oracle companions are supporting files
and do not count as additional benchmark tasks.

Task definitions and required local assets live under `tasks/v1/`. The
[release guide](tasks/v1/README.md) explains the layout and selection rules.
Execution configs covering each platform are in [`executions/v1/`](executions/v1/).
Tasks outside v1 have been removed from the working tree; earlier versions
remain available in Git history.

The task release does not bundle runtime prerequisites such as VM snapshots,
installed applications, or model credentials. Every task's initializer and
evaluator resolve locally; the reviewed import records its provenance in its
[manifest](tasks/v1/cua_tasks_review_manifest.json).

To run the Linux set on a server with a local vision model, see the
[headless QEMU guide](docs/linux_headless.md).

## Repository layout

The repository is organized around platform-specific benchmark runners, task
definitions, evaluators, and runtime integrations:

* `core/`: shared LLM, prompt, spec, and runtime abstractions.
* `platforms/`: Android, iOS, Linux, macOS, and Windows runtime code.
* `tasks/v1/`: the first 300-task release, supporting tasks, and task assets.
* `evaluators/`: task-specific evaluation logic.
* `initializers/`: task setup and environment seeding logic.
* `executions/`: benchmark execution configs referencing retained tasks.
* `scripts/`: project maintenance and benchmark helper scripts.
* `workbench/`: local benchmark inspection UI.

Install dependencies from `pyproject.toml` or use the platform-specific setup
notes under `platforms/`.

## Virtual Machine Images

Preconfigured virtual machine images for OS-Omni are available on Hugging Face:

https://huggingface.co/datasets/Cloudriver/OS-Omni-VM/tree/main
