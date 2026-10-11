# Android author rebuilt benchmark delivery

This is the Android handover inside the **cross-platform OS-Omni repository**. Other platforms' original source and tasks remain in their original directories. Do not interpret the Android reconstruction as a replacement for the whole benchmark.

## Directory contract

| Location relative to repository root | Ownership / purpose |
|---|---|
| `platforms/android`, `initializers/android`, `evaluators/android` | Shared Android implementation and original graders |
| `tasks/v1/android` | Original released task definitions |
| `local_eval` | **Android only** reconstruction implementation; retained name is an import and path compatibility contract |
| `local_eval/tasks` | Runnable reconstructed 48-task suite |
| `local_eval/apks`, `app_assets`, `opendriver_dart` | Supplied original/patched APKs, extracted assets, repair source and provenance |
| `local_eval/benchmark-v2` | Author generated Cooking photos, four independent GUI references, verifier validation, legacy scores |
| `local_eval/photo-originals`, `delta-media`, `deltachat-baseline-db` | GitHub-delivered input photos, media and DB fixtures |
| `local_eval/vm-original-disks` | VM baseline disks: local copies retained, excluded from GitHub; author-rebuilt V3 is uploaded and remotely verified through HF PR #7 |
| `local_eval/runs/<task_id>/<timestamp>` | Run evidence including screenshots, trajectory, end state, initializer, grader, logs |
| `docs/android/final-valid-runs.json` | Authoritative selection of the **last valid run for each of 48 tasks**; follow the exact report path, including schema-corrected reports, rather than selecting by newest timestamp or assuming every report is named result.json |
| `local_eval/monitor-audits`, `FAILURE-AUDIT.md`, `failure-audit.json`, `repair-log.json` | Repair history and evidence; older attempts remain for audit |
| `docs/android/release-manifest.json` | Every delivered artifact's path, byte size and SHA256, release part hashes |
| `.tools/greenmail` | Delivered GreenMail 2.1.8 service binary |

**Storage policy:** App assets and evaluation evidence go to GitHub; the virtual machine goes to HF in the author-authorized `android_V3` revision. The VM is intentionally absent from the GitHub bundle. Its separate checksum inventory is `docs/android/external-vm-assets.json`; destination is `Cloudriver/OS-Omni-VM`, path `android_V3`; upload and remote verification are complete. Do not treat this intentional external dependency as a lost asset.

Large App/evidence artifacts are delivered through the GitHub Release `android-handover-20261009`, as ordered parts of a single ZIP. Check `docs/android/delivery-validation.json`: **pending** means the background upload is still running; **complete_remote_verified** means all server SHA256 digests match. `scripts/restore_android_delivery.py` joins, extracts, and verifies them into the exact paths above. Git contains source, task definitions, photos/references and 353 final run evidence files (including trajectories, logs and exact selected verdicts) so they can be reviewed directly. The release additionally preserves 5,499 final-run PNGs, historical attempts and all repair/audit assets. Allow at least 60 GB free space for downloads, joined ZIP, extraction and the running AVD if subsequently installed. The VM has a separate HF-pending manifest; the GitHub bundle contains no VM baseline disks.

## Final experiment

`restart_20261008_162853`: **48 valid tasks, 7 PASS, 41 model FAIL (14.58%)**. No current environment exclusions. DS Flash reasoning effort `none`, maximum 180 steps with smaller original limits preserved. Two photo tasks use author rebuilt photo v2; 46 valid tasks retain reconstruction v1. See `local_eval/FINAL-REPORT.md` and `FINAL-SCORE.json`. Photo v2 includes generated replacement photos, revised deterministic image references and whole-image checks; it does not claim recovery of the lost historical photographs. Retained legacy results are not part of the current score.

The repairs were validated against the encountered problems, including positive/negative verifier checks and actual emulator preflight. This is not a claim that all future app behavior or every other platform has been tested.

## Restore and run (validated host: Windows x86_64)

1. Install Python 3.12, Android SDK platform-tools/emulator and `system-images;android-33;google_apis;x86_64`, plus JDK 25. Enable Windows hypervisor acceleration. OpenPhoto and the final Driver task require working host GPU support. Vendor runtimes are dependencies, not missing benchmark assets.
2. From repository root run `python scripts/restore_android_delivery.py`. A GitHub login may be needed if repository visibility is changed to private. Parts can also be downloaded with `gh release download android-handover-20261009 --repo BaoZhuhan/os-omni --dir .android-delivery-cache` before running the script.
3. Create a Python 3.12 virtual environment at `.runtime`, install the packages in `docs/android/requirements-observed.txt` using pip. Original cross-platform dependency specifications remain in `pyproject.toml`, `uv.lock` and requirements files. The observed list records the actual Android experiment environment.
4. Set `ANDROID_SDK_ROOT` to your SDK. Set `JAVA_EXE` or put JDK 25 `java` on PATH. Run `python scripts/setup_android_delivery.py` only after the VM baseline has been obtained through the separately supplied HF delivery, to register those pristine disks. It refuses to overwrite an existing `AndroidWorldAvd`. Original downloadable VM archive source and SHA256 are recorded in the manifest, as historical provenance. New HF publication is pending the author閳ユ獨 instructions; the GitHub restore does not fetch or supply VM disks.
5. Set `DEEPSEEK_API_KEY` to your credential and `DEEPSEEK_BASE_URL=https://api.deepseek.com` (the actual endpoint used for this experiment). See `docs/android/environment.example`; set variables in the shell rather than expecting this example file to load automatically. Neither credential nor an API service subscription is included. `OS_OMNI_SECRET_FILE` optionally points to an external JSON mapping of environment variables. Model ID/configuration lives in `configs/models.yaml` under `deepseek_flash`; the provider must actually expose that model and Responses protocol.
6. Run `.runtime/Scripts/python.exe local_eval/run_one.py --task local_eval/tasks/<task>.yaml --preflight`; expect initializer PASS and untouched baseline FAIL. Then omit `--preflight` for DS execution. The run automatically starts the supplied OpenDriver backend on port 4321 and GreenMail on 8081. Emulator device is `emulator-5582`, AVD is `AndroidWorldAvd`.
7. All delivered queue statuses are completed to preserve the finished experiment. For a new experiment, back up `local_eval/queue/status.json` and `experiment.json`, then start with a new empty status file. Run `local_eval/run_queue.py` only once; never manually operate the same emulator while the queue is running. `queue_companion.py` is an optional Windows companion. Keep existing final evidence immutable.

These reconstruction launch scripts were exercised on Windows. The overall repository remains cross-platform; Linux/macOS Android launch adaptation and all other platform suites are not silently certified by this Android delivery. The restore/verifier scripts use standard Python and portable repository-relative paths. Historical logs retain external host paths when needed as evidence; the old evaluation workspace prefix is normalized to `.` in exported text. Binary screenshots, verdicts and business parameters are unchanged. API credentials are redacted.

## What is intentionally external

Only user API credentials, vendor-installed SDK/JDK/Python virtual environments, caches, and process lock files are excluded. Benchmark input photos, DB/media fixtures, repaired APKs, backend, verifiers, all final valid trajectories/screenshots, and historical repair evidence are delivered through GitHub. VM baseline disks are kept locally for the separately requested HF publication; HF V3 upload and remote verification are complete. Nothing depends on the previous operator's Codex installation for a new run.

## Author rebuilt Android V3 delivery

Hugging Face supports dataset pull requests. The authorized upload uses [Cloudriver/OS-Omni-VM PR #7](https://huggingface.co/datasets/Cloudriver/OS-Omni-VM/discussions/7) (`refs/pr/7`), directory **android_V3**, image **android_V3.zip**. A PR URL alone does not mean the image is fully uploaded or merged. Check the V3 manifest and remote verification status before downloading.

V3 starts from clean historical v2 disks, installs Food/Navigation repairs, supplies generated Cooking inputs, and includes host initializers/verifiers and a portable AVD registration script. It excludes the final model task state. Task-specific reset and the host OpenDriver/GreenMail services are still required. SDK system image: `system-images;android-33;google_apis;x86_64`. VM binaries belong exclusively to HF; this Git repository holds code, provenance and evaluation evidence. The historical 7/48 score has not been remeasured using the newly baked V3 image.

V3 archive is locally complete and CRC/SHA256 verified: **8,693,023,008 bytes**, SHA256 `746eb8f40998866d85a8a595358c26fb8d5c930ee964b6dc475b124c03d9fa90`. HF upload is complete and remote LFS SHA256/size plus README, validation and manifest hashes have been verified. See `android-v3-manifest.json` and `external-vm-assets.json`.

Final HF verification: `hf-remote-assets-verified.json`. PR #7 status: **open**; this submission does not claim the V3 image is merged into main. Exact uploaded commit: `2991c2ed0aa03d4a79d9c3253689361bb0032968`.
