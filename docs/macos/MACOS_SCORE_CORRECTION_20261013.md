# macOS benchmark score correction — 2026-10-13

The macOS progress ledger previously counted two native PASS results as FAIL. That administrative override was incorrect. A native PASS remains a PASS, so the corrected progress total is **2 PASS, 46 FAIL, 48 distinct tasks**. The other 46 task classifications are unchanged.

| Task | Native result | Initializer | Evaluator | Steps | Corrected status |
| --- | --- | --- | --- | ---: | --- |
| `macos.textedit.config_rewrite` | PASS | PASS | PASS | 3 | PASS |
| `macos.wireshark.conversations_triage` | PASS | PASS | PASS | 21 | PASS |

The immutable local result records are retained in `execution/records/macos-author-results-20261012/macos/`. Their SHA-256 digests and relative paths are recorded in [`../records/macos-score-correction-20261013.json`](../../records/macos-score-correction-20261013.json). The correction supersedes the stale task-level FAIL labels and aggregate in that archive's `TASKS.csv` and `DELIVERY_README.md`; it does not rewrite the underlying run evidence or change any other task.
