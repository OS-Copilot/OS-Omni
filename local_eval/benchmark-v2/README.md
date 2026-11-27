# Author photo benchmark v2

The benchmark author authorized rebuilding missing assets and updating evaluation on 2026-10-09. This revision updates Cooking/Guitar only; the other46task definitions and valid runs are retained.

* Generated assets: assets/indoor-cooking-v2.jpg and assets/outdoor-cooking-v2.jpg (built-in image_gen), deterministic960x1280 conversion. Prompt, source copy and hash in assets/provenance.json.
* Source edits/calibration are authored fixtures, not recovery of the lost source snapshot. Original source JPEGs retained in local_eval/photo-originals.
* Calibration patches use RGB190/40/40,40/190/40,40/40/190 to avoid saturated-channel clipping. Exact task parameter recipes are unchanged.
* Correct references are exported by the original APK on the real Android emulator with host GPU, after explicitly verifying each slider value in nativeUI. Independent repeated correct exports must have identical medians.
* Evaluator requires original export size/dimensions/count/baseline/final-editor checks, new per-channel calibration tolerance1 and whole-image MAE<=2 to bind the correct source photo and rendered output. These are image-output requirements; they do not assert exact equality of every internal slider if two settings yield an indistinguishable render.
* Positive/negative validation covers repeat exports, untouched input, wrong exposure, wrong source, duplicate source and pre-existing export exclusion. See validation.json.
* Probe runs are author/reference work only; they never replace a DeepSeek trajectory or model result.
* Old Cooking/Guitar attempts remain excluded under the old definition. Fresh DS runs use this version. They may be combined with the retained46results as a revised-suite score, with version differences disclosed.

Reference generation: python -m local_eval.rebuild_photo_references
Freeze/validate: python -m local_eval.finalize_photo_v2
Actual cold preflight and DS execution: local_eval/run_queue.py --groups openphoto (completed unaffected tasks skip).
