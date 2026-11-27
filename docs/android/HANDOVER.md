# Android environment for v1

The 48 v1 Android tasks live in `tasks/v1/android/` and run against the author-rebuilt
**Android V3** emulator image plus two host services. This page lists what each part is
and where it comes from.

## Directory contract

| Location relative to repository root | Purpose |
|---|---|
| `platforms/android`, `initializers/android`, `evaluators/android`, `evaluators/cua_review/*/android` | Android runner, initializers and graders |
| `tasks/v1/android`, `executions/v1/android.yaml` | v1 task definitions and execution config |
| `local_eval/run_one.py`, `local_eval/run_queue.py`, `local_eval/cold_reset.py` | Cold-reset single-task runner and a sequential queue over `tasks/v1/android` |
| `local_eval/start_services.py`, `local_eval/opendriver_backend.py` | Host services: the OpenDriver replacement backend on `127.0.0.1:4321` (state in `local_eval/opendriver-backend-state.json`) and GreenMail 2.1.8 on `127.0.0.1:8081` |
| `local_eval/opendriver_dart` | OpenDriver Dart source recovered from the installed APK; the backend's API contract was recovered from it |
| `local_eval/benchmark-v2` | OpenPhoto Cooking/Guitar generated inputs and device reference exports used by the v1 OpenPhoto tasks |
| `assets/android/openphoto` | Base photos for the v1 OpenPhoto calibrated-export tasks |
| `local_eval/apks`, `local_eval/app_assets`, `.tools/greenmail` | Not in Git: patched OpenFood/OpenNavigation APKs, extracted app assets and the GreenMail jar, restored from the GitHub Release (below) |
| `local_eval/vm-original-disks` | Not in Git: the v2 AVD baseline disks used by `cold_reset.py` (checksums in `docs/android/external-vm-assets.json`) |

## Emulator image

The V3 image is on Hugging Face: [Cloudriver/OS-Omni-VM PR #7](https://huggingface.co/datasets/Cloudriver/OS-Omni-VM/discussions/7)
(`refs/pr/7`, directory `android_V3`, file `android_V3.zip`, uploaded commit
`2991c2ed0aa03d4a79d9c3253689361bb0032968`). Size 8,693,023,008 bytes, SHA256
`746eb8f40998866d85a8a595358c26fb8d5c930ee964b6dc475b124c03d9fa90`; see
`android-v3-manifest.json` and `hf-remote-assets-verified.json`.

V3 starts from the AndroidWorldAvd v2 disks (`vm/` holds the v2 README, package manifest, checksum
and `config.ini`), installs the OpenFood/OpenNavigation event-provenance APKs and the generated
Cooking inputs, and contains no task state. SDK system image:
`system-images;android-33;google_apis;x86_64`. `scripts/build_android_v3.py` records how it was
built; `scripts/install_android_v3.py` ships inside the archive and registers the extracted AVD.

## Restore and run (validated host: Windows x86_64)

1. Install Python 3.12, Android SDK platform-tools/emulator and the system image above, plus JDK 25.
   OpenPhoto and the OpenDriver document-arrival task need host GPU support.
2. Restore the host assets: `python scripts/restore_android_delivery.py` downloads the GitHub Release
   `android-handover-20261009` (checksums in `docs/android/release-manifest.json`), joins it and
   extracts it into the repository. The archive also carries the historical run evidence and older
   copies of tracked files, so afterwards restore the tracked files it overwrote
   (`git checkout -- local_eval docs/android`) and ignore the extra untracked files. Allow about
   60 GB of free space.
3. Create a Python 3.12 virtual environment and install `docs/android/requirements-observed.txt`
   (the repository-wide dependencies are in `pyproject.toml`).
4. Set `ANDROID_SDK_ROOT`, and `JAVA_EXE` or put JDK 25 `java` on PATH (see `environment.example`).
   With the v2 baseline disks in `local_eval/vm-original-disks`, `python scripts/setup_android_delivery.py`
   registers them as `AndroidWorldAvd`; it refuses to overwrite an existing AVD.
5. Set the model credentials for the model you evaluate (`configs/models.yaml`).
6. Check a task without a model: `python local_eval/run_one.py --task tasks/v1/android/<task>.yaml --preflight`
   (cold reset, services, initializer PASS and untouched-state evaluator FAIL are expected). Omit
   `--preflight` for a model run (`deepseek_flash`, at most 180 steps), or run all 48 tasks with
   `python local_eval/run_queue.py`. The runner starts the OpenDriver backend and GreenMail when they
   are not already up and uses emulator `emulator-5582`.

With the services running (`python local_eval/start_services.py`) and an emulator booted from V3,
the generic runner also works: `python -m platforms.android.cli --execution executions/v1/android.yaml`.

These launch scripts were exercised on Windows; Linux hosts need the usual path and emulator
adjustments. Credentials, SDKs, virtual environments and caches are not part of the repository.
