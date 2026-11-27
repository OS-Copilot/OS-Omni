# macOS task repairs and disposition

## OpenPhotoEdit tasks (2026-10-12)

The four imported OpenPhotoEdit tasks referenced RGB calibration fixtures and
edited-output hashes that were absent from the workspace. Those references
cannot be reproduced from the installed app bundle alone. The source scenes
were regenerated with the built-in ImageGen tool; the exact prompts, raw image
hashes, derived fixture hashes, dimensions, and calibration patches are in
`tasks/v1/macos/assets/openphotoedit/PhotoFixtures/CalibrationManifest.json`.

To retain runnable, independently judgeable OpenPhotoEdit coverage, the four
tasks now ask DeepSeek to identify each named replacement photo and export a
no-edit PNG copy. Evaluation compares each export with an independently decoded
source-pixel PNG reference, including dimensions, RGB calibration region, and
whole-image pixels. `tests/test_macos_openphotoedit_export_evaluator.py` proves
that correct exports pass while swapped sources and missing exports fail. These
revised results must be reported as `openphotoedit-export-only-v1`; they are not
scores for the superseded filter-edit tasks.

## Photos task skip (2026-10-12)

`macos.photos.favorite_receipts_hard` is excluded from the formal model queue.
On the active macOS VM, the Photos first-run library chooser cannot create the
expected `~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`.
The initializer can generate the ten source fixtures and launch Photos, but the
app reports that the library could not be opened; the evaluator therefore
returns ERROR before a model action. A native “Create New…” attempt also failed
to produce the expected database. This is an app/environment blocker, not a
DeepSeek failure. Its initializer/evaluator error JSON and screenshots remain
under `execution/records/macos-author-preflight-full-20261012/`.

The other 47 tasks have fresh initialization-pass and initial-evaluator-fail
evidence. The Photos task is recorded as `SKIPPED_BY_AUTHOR` and is excluded
from the 47-task queue. No model score is assigned to it.
