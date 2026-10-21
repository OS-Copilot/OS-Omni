# Touchstone source integration

BaoZhuhan/os-omni is the primary repository. This integration is pinned to
Touchstone-AI-Lab/OS-Omni `d6732999bb12cb06802e8956fdf1a91a5593e767`.

## Where the content lives

| Content | Location |
| --- | --- |
| Linux/Web task and runtime updates | `tasks/v1/{linux,web}`, `platforms/linux`, `initializers/linux`, `evaluators` |
| 12 authoritative single-screen cross-device tasks | `tasks/v1/cross_device`, `executions/v1/cross_device*.yaml` |
| Current 300-task benchmark | `tasks/v1/manifest.json` |
| Supporting stages retained by Touchstone | `tasks/v1/cross_vm/stages` |
| File-by-file provenance and conflict decisions | [manifest.json](manifest.json) |
| Exact upstream files, historical tasks and all five branch histories | `touchstone-all-branches.bundle` in the [consolidated release](https://github.com/BaoZhuhan/os-omni/releases/tag/consolidated-evidence-20261021) |
| Model results and evidence | [records](../../records/README.md) |

Windows, Android, iOS and macOS use the primary repository's versions. Linux,
Web and Cross-device use Touchstone's versions, including its removals of
obsolete tasks and execution configurations. The retired Cross-VM workflows
are removed from the active tree rather than offered as an alternative task
track. [authority-correction.json](authority-correction.json) lists the removals.
Upstream versions
of those files are retained in the source bundle rather than silently replacing
the validated primary implementations. The upstream branch histories also
preserve older tasks that Touchstone intentionally retired from its main tree.

The bundle is self-contained and does not require the Touchstone repository to
remain available. Verify its checksum against `SHA256SUMS.txt`, then use:

```sh
git clone --mirror touchstone-all-branches.bundle touchstone-history.git
git --git-dir=touchstone-history.git show refs/remotes/touchstone/main:README.md
```

## Task-version distinction

No committed model-run `result.json`, `trajectory.jsonl` or `results.csv`
collection was found in the five source branches, and the source repository had
no GitHub Releases at the integration date. This import does not invent scores
for Linux/Web or cross-device tasks. Available Linux/Web GPT/Kimi evidence is
imported separately from the pinned HF dataset; cross-device scores remain
untested until actual runs are available.

The current 300-task manifest follows Touchstone's selection: 288
single-platform tasks and 12 Cross-device tasks. These 12 replace the original
Cross-VM workflows; they are not additional tasks. Do not transfer historical
Cross-VM scores to the replacement IDs. [tasks/catalog.json](../../tasks/catalog.json)
records the platform authority and task revision. Older definitions remain in
Git history only; the supporting stages retained by Touchstone are not active
Cross-VM workflows and do not count as extra tasks.

The archived upstream manifest describes upstream files at its pinned commit;
it is provenance, not a claim that upstream iOS/macOS/Windows definitions were
substituted into the primary benchmark. Physical VM images and externally
installed prerequisites remain external runtime dependencies.
