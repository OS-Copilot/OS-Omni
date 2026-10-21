# iOS benchmark closeout (updated 2026-10-17)

The final task-level classification covers all 48 iOS tasks: **5 PASS / 43 FAIL / 0 skipped**. This supersedes the 2026-10-12 closeout of 5 PASS, 39 FAIL and four unscored skips.

| Outcome | Count |
| --- | ---: |
| PASS | 5 |
| FAIL with native scored result | 40 |
| Author-adjudicated FAIL | 3 |
| Unscored / skipped | 0 |
| Total | 48 |

On 2026-10-17 the benchmark author explicitly directed these previously skipped tasks to be classified FAIL:

- `ios.openbank.lena_marco_dispute_security_086132`
- `ios.opennote.forum_outfit_three_notes_194503`
- `ios.openshop.beauty_office_checkout_review_807073`

These are task-level author adjudications. They do not create new native evaluator results or rewrite the original attempt evidence. The ledger preserves the previous skip classifications and historical evaluator fields; `valid_result` remains false for these three, while the author-adjudicated task verdict is valid.

`ios.flow.rework_budget_with_transfer_and_income` was subsequently retested on 2026-10-14: initializer PASS, native result FAIL and evaluator FAIL after 17 steps. The [saved result](../../local_eval/runs/ios.flow.rework_budget_with_transfer_and_income/20261014_013127/result.json) supersedes its earlier initializer-timeout skip. This retest records `deepseek_chat` / `deepseek-chat`, rather than the earlier `deepseek_flash` model label.

The [task-by-task ledger](../../records/ios-completion-status-20261012.json) distinguishes native results from author adjudications and retains original evidence links. Historical attempt exclusions remain preserved.

The iOS v3.2 repair overlay is submitted to [Hugging Face PR #8](https://huggingface.co/datasets/Cloudriver/OS-Omni-VM/discussions/8). The PR is open and **not merged**. A merge attempt was rejected with HTTP 403 because the authenticated account cannot merge into the dataset main branch. Its README and manifest were read from `refs/pr/8`; the remote LFS SHA-256 and a fresh download of the 68,128,024-byte app ZIP match `1f6c0b23bbcbbbcd42f674e5b9135f2046a09e396152b97eb7af95a5def06b3e`. The overlay is based on the current v3.1 image and includes the fixed OpenPhotoEdit simulator app; evaluator, initializer, task, and test source is already in GitHub. It is an app overlay, not a rebuilt full VM image. The status JSON records the PR, base revision, and payload hash.

## Evidence supplements

Two archives were uploaded to the existing [author-eval-2026-10-11 GitHub release](https://github.com/BaoZhuhan/os-omni/releases/tag/author-eval-2026-10-11) to cover the valid latest attempts that were missing from its original asset set:

- [Seven iOS attempts](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/os-omni-ios-final-valid-runs-supplement-20261012.tar.gz), SHA-256 `985c95ebdb91d347a5584e0fe58cd1683ab9b864d06740a9389ceda7b0b69ab4`.
- [Two FSNotes attempts](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/os-omni-ios-fsnotes-valid-runs-supplement-20261012.tar.gz), SHA-256 `a82326f0bc93f432e707141eb205b7f9aad179d1a8331097822094b46a9fa325`.

The machine-readable task list links every scored result to its evidence asset and archive member where applicable. Release asset metadata was checked after upload. The supplemental archives were scanned for API-token patterns before publication; no matches were found.
