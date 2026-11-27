# Repository guide

| Need | Location |
| --- | --- |
| Current 300-task benchmark | `tasks/v1/manifest.json` |
| Task definitions and local assets | `tasks/v1/<track>/` |
| Reviewed-import provenance and English briefs | `tasks/v1/cua_tasks_review_manifest.json`, `tasks/v1/cua_tasks_review_instructions.json`, [import notes](cua_tasks_review.md) |
| Execution configurations | `executions/v1/` |
| Shared model/runtime code | `core/`, `configs/` |
| Platform integrations | `platforms/<platform>/` |
| Environment setup and grading | `initializers/`, `evaluators/` |
| Linux and Web setup | [linux_headless.md](linux_headless.md) |
| Cross-device setup | [Linux + Android](linux_android_companion.md), [Windows + Android](windows_android_companion.md) |
| Windows setup | [platform notes](../platforms/windows/README.md), [Qwen3.8-max reproduction](windows/qwen38-max-reproduction.md), [OpenTrip baseline](windows/task-application-compatibility.md) |
| macOS setup | [platform notes](../platforms/macos/README.md), [terminal evidence capture](macos/TERMINAL_EVIDENCE.md) |
| iOS setup | [platform notes](../platforms/ios/README.md), [Maily seeding](ios/MAIL_SEEDING.md), [OpenDriver backend](ios/OPENDRIVER_BACKEND_REPRODUCTION.md), [Flow helper](ios/FLOW_ENVIRONMENT_REPAIR.md), [local mail evidence](author_eval/LOCAL_MAIL_EVIDENCE.md) |
| Android setup | [Android V3 image and host services](android/HANDOVER.md), [platform notes](../platforms/android/README.md) |
| Harness protocol | [protocol/](protocol/) |
| Results | `task_results.csv`, `platform_summary.csv`, `scan.csv` |

The 12 single-screen Cross-device tasks replaced the retired Cross-VM
workflows within the 300-task benchmark. Only the supporting stages they were
generated from remain under `tasks/v1/cross_vm/`.

Tasks, execution configurations, run evidence and audit reports outside v1 were
removed from the working tree; they remain available in Git history. VM images
are published separately on Hugging Face and are runtime prerequisites.
