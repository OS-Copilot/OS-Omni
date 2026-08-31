# OS-Omni

OS-Omni is a cross-platform GUI benchmark and runtime stack for agent evaluation.

The repository is organized around platform-specific benchmark runners, task
definitions, evaluators, and runtime integrations:

* `core/`: shared LLM, prompt, spec, and runtime abstractions.
* `platforms/`: Android, iOS, Linux, macOS, and Windows runtime code.
* `tasks/`: benchmark task definitions and task assets.
* `evaluators/`: task-specific evaluation logic.
* `initializers/`: task setup and environment seeding logic.
* `executions/`: runnable benchmark execution configs.
* `scripts/`: project maintenance and benchmark helper scripts.
* `workbench/`: local benchmark inspection UI.

Install dependencies from `pyproject.toml` or use the platform-specific setup
notes under `platforms/`.

## Virtual Machine Images

Preconfigured virtual machine images for OS-Omni are available on Hugging Face:

https://huggingface.co/datasets/Cloudriver/OS-Omni-VM/tree/main
