# Repository guide

| Need | Location |
| --- | --- |
| Current 300-task benchmark | `tasks/v1/manifest.json` |
| Track authority and task revision | `tasks/catalog.json` |
| Task definitions and local assets | `tasks/v1/<platform>/` |
| Shared model/runtime code | `core/`, `configs/` |
| Platform integrations | `platforms/<platform>/` |
| Environment setup and grading | `initializers/`, `evaluators/` |
| Execution configurations | `executions/v1/` |
| Linux and Web setup | [linux_headless.md](linux_headless.md) |
| Cross-device setup | [Linux + Android](linux_android_companion.md), [Windows + Android](windows_android_companion.md) |
| Result indexes and downloadable evidence | [records](../records/README.md) |
| Touchstone source/conflict provenance | [integrations/touchstone](../integrations/touchstone/README.md) |

Source and small result indexes belong in Git. Large experimental evidence
belongs in Releases with checksums. VM images are published separately on
Hugging Face and are runtime prerequisites, not benchmark evidence.

Windows, Android, iOS and macOS follow BaoZhuhan/os-omni. Linux, Web and
Cross-device follow Touchstone-AI-Lab/OS-Omni. The 12 Touchstone Cross-device
tasks replace the retired Cross-VM workflows within the 300-task benchmark.
Only the supporting stages retained by Touchstone remain under `cross_vm/`.

Use `executions/v1/` for the supported versioned tasks. Older files directly
under platform-specific execution folders are historical author configurations;
they can reference tasks retired before v1 and are not current run entrypoints.

The original per-platform handover and closeout documents remain available at
their existing paths so older links continue to resolve. The Touchstone source
bundle stores all branches locally within this repository's Release; the source
repository is not needed to recover those versions.
