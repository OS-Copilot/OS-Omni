# Author photo benchmark v2

The benchmark author authorized rebuilding missing assets and updating evaluation on 2026-10-09. This revision updates the Cooking/Guitar OpenPhoto tasks only.

* Generated assets: assets/indoor-cooking-v2.jpg and assets/outdoor-cooking-v2.jpg (built-in image_gen), deterministic960x1280 conversion. Prompt, source copy and hash in assets/provenance.json.
* Source edits/calibration are authored fixtures, not recovery of the lost source snapshot.
* Calibration patches use RGB190/40/40,40/190/40,40/40/190 to avoid saturated-channel clipping. Exact task parameter recipes are unchanged.
* Correct references are exported by the original APK on the real Android emulator with host GPU, after explicitly verifying each slider value in nativeUI. Independent repeated correct exports must have identical medians.
* Evaluator requires original export size/dimensions/count/baseline/final-editor checks, new per-channel calibration tolerance1 and whole-image MAE<=2 to bind the correct source photo and rendered output. These are image-output requirements; they do not assert exact equality of every internal slider if two settings yield an indistinguishable render.
* Positive/negative validation covers repeat exports, untouched input, wrong exposure, wrong source, duplicate source and pre-existing export exclusion. See validation.json.
* Probe runs are author/reference work only; they never replace a model trajectory or result.
* `references/<profile_id>/` holds each profile's input, the correct and repeated device exports, the negative exports and the slider settings; the v1 tasks (`tasks/v1/android/openphoto_*_dual_calibrated_export_20260804.yaml`) cite them as `reference_source`, and `tests/test_android_openphoto_calibrated_inputs.py` checks the fixtures against them.
