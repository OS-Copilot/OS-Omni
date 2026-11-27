# Android platform

Android support for OS-Omni follows the shared execution/task/result protocol. The v1 tasks are in
`tasks/v1/android/`; the emulator image, host services and the cold-reset runner are described in
[docs/android/HANDOVER.md](../../docs/android/HANDOVER.md).

## Architecture

- The host runner talks to the Android emulator or device over ADB (unlike the HTTP guest runtime
  used on Windows, Linux and macOS).
- The ADB controller provides screenshots, the UI hierarchy, taps, swipes, text input and key events.
- The host reuses the shared LLM, prompt, runner, initializer and evaluator protocol. v1 executions
  use `action_mode: code_adapter` and `observation_mode: screenshot_only`.

## Prerequisites

- Android SDK with `adb` and `emulator`, and the `system-images;android-33;google_apis;x86_64` image.
- The Android V3 AVD registered as `AndroidWorldAvd` (see the handover document).
- Python 3.12.
- Host services: the OpenDriver replacement backend on `127.0.0.1:4321` and GreenMail on
  `127.0.0.1:8081`. `python local_eval/start_services.py` starts both (JDK 25 required for GreenMail).
  The emulator reaches the host at `10.0.2.2`.

## Configuration

`configs/android.yaml`:

```yaml
adb_device: emulator-5582
avd_name: AndroidWorldAvd
auto_launch_emulator: true
emulator_boot_timeout: 300
emulator_reset_between_tasks: true
emulator_snapshot_name: os_omni_clean
```

Environment overrides: `HELLOWORLD_ANDROID_ADB_DEVICE`, `HELLOWORLD_ANDROID_AVD_NAME`,
`HELLOWORLD_ANDROID_EMULATOR_RESET_BETWEEN_TASKS`, `HELLOWORLD_ANDROID_EMULATOR_SNAPSHOT_NAME`.

Model ids and their credential variables are defined in `configs/models.yaml`; edit `models:` in the
execution YAML to choose one.

## Running

Validate the execution without running tasks:

```bash
python scripts/run_benchmark.py --execution executions/v1/android.yaml
```

Run all 48 tasks:

```bash
python -m platforms.android.cli --execution executions/v1/android.yaml
```

Run one task with a cold reset of the AVD and the host services started automatically:

```bash
python local_eval/run_one.py --task tasks/v1/android/<task>.yaml --preflight   # initializer + untouched-state check
python local_eval/run_one.py --task tasks/v1/android/<task>.yaml               # model run
```

Other helpers: `scripts/run_android_task_trials.py` (repeat one task),
`scripts/run_android_all_initializers.py` and `scripts/check_android_init_incomplete.py` (initializer
checks over an execution), `scripts/setup_android_benchmark_env.py` (environment checks), and
`scripts/bootstrap_android_comm_state.py` / `scripts/bootstrap_android_comm_apps.py` (reusable K-9 /
Delta Chat app-data templates under the untracked `assets/android_comm_state/`).

## Long runs

- Keep the host awake; sleep or hibernation interrupts Python, ADB, GreenMail and the emulator.
- If `httpx` fails through a proxy (`PROVIDER_REQUEST_FAILED`), clear `HTTP(S)_PROXY`/`ALL_PROXY` and
  set `NO_PROXY=*` in the shell that runs the benchmark.

## Results

```
results/<model>/android/<execution_name>_<timestamp>/
  <task_id>/
    result.json
    trajectory.jsonl
    screenshots/
```
