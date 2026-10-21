# Evaluation records

BaoZhuhan/os-omni is the primary home for the source, result indexes and
downloadable evidence. Large trajectories, screenshots and videos live in
GitHub Releases; compact, reviewable run indexes live here.

| Collection | Contents | Evidence |
| --- | --- | --- |
| Android DeepSeek no thinking | Original rebuilt author benchmark | [android-handover-20261009](https://github.com/BaoZhuhan/os-omni/releases/tag/android-handover-20261009) |
| Windows DeepSeek no thinking | Original 48-task run and audit trail | [windows-handover-20261013](https://github.com/BaoZhuhan/os-omni/releases/tag/windows-handover-20261013) |
| macOS/iOS DeepSeek no thinking | Original author validation and closeout records | [author-eval-2026-10-11](https://github.com/BaoZhuhan/os-omni/releases/tag/author-eval-2026-10-11) |
| macOS author archive | Additional existing archive, draft at integration time | [macos-author-records-20261013](https://github.com/BaoZhuhan/os-omni/releases/tag/macos-author-records-20261013) |
| Android DeepSeek Flash high | 48 final valid runs: 20 PASS, 28 FAIL | [consolidated-evidence-20261021](https://github.com/BaoZhuhan/os-omni/releases/tag/consolidated-evidence-20261021) |
| GPT-5.5 and Kimi-K3 | 211 retained HF runs, automatic scores and raw model metadata | Same consolidated release |

See [the consolidated run index](consolidated-20261021/runs.json) and
[CSV scores](consolidated-20261021/results.csv). The release manifest lists
independent ZIP shards and their SHA-256 checksums. Each ZIP contains a member
manifest; extract every shard for a model/platform into the same directory.
Runs can span numbered archives. Preserve the `hf/` and `android/` directories.

The [DeepSeek no-thinking inventory](deepseek-no-thinking-v1.csv)
indexes the current 300 benchmark tasks, including blank untested entries and
the author's final iOS FAIL reconciliations. The retired Cross-VM placeholders
are replaced by blank entries for Touchstone's 12 Cross-device tasks; no scores
are inherited. Existing per-platform source ledgers
and Releases remain authoritative provenance for those historical runs.

After downloading the release manifest and all assets, verify them with:

```sh
python scripts/verify_consolidated_release.py /path/to/downloads --members
```

## Score conventions

- `PASS` and `FAIL` are scored results. `ERROR` and untested runs have a blank
  `result`; `raw_status` preserves the source status.
- Unspecified GPT/Kimi reasoning is grouped under `high`, following the author's
  instruction. Explicit `low` and `no thinking` remain separate. Raw settings
  are retained in `source_reasoning`.
- HF scores use the top-level model `result.json.status`. A later human/reference
  `verifier_result.json` does not override the model run.
- Only tasks retained in the original 300-task inventory are imported into the
  score index. 91 dataset-only tasks previously abandoned by the author are
  excluded. Platform labels follow that inventory; Web runs may report `linux`
  in their original runtime metadata.
- Android high is labelled `deepseek-flash-1017(high)` for reporting; actual
  request model `deepseek-flash` and reasoning effort `high` are recorded.
  Its V3 environment differs from the original no-thinking run; differences
  in scores cannot be attributed solely to reasoning mode.

The consolidated collection contains 259 run records: 64 PASS, 179 FAIL and
16 untested/ERROR. This does not include the existing no-thinking releases.
Credentials and the uploader's workspace paths are removed from published text
artifacts; image/video content and raw result metadata are otherwise retained.
