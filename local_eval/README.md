# Android host runner

The name `local_eval` is kept for import and path compatibility. It holds the host side of the
v1 Android setup described in [docs/android/HANDOVER.md](../docs/android/HANDOVER.md):

* `run_one.py`: run one task (`--task tasks/v1/android/<task>.yaml`) after a cold reset of the
  emulator from the baseline disks; `--preflight` runs only the initializer and the untouched-state
  evaluator. Evidence is written to `local_eval/runs/<task_id>/<timestamp>/` (ignored by Git).
* `run_queue.py`: run every task in `tasks/v1/android` in order, resuming from
  `local_eval/queue/status.json`. Environment errors are recorded separately from model failures.
* `cold_reset.py`: restore the AVD disks before each task; snapshot restores were unstable.
* `start_services.py`: start the OpenDriver backend (`127.0.0.1:4321`) and GreenMail
  (`127.0.0.1:8081`) when they are not already running.
* `opendriver_backend.py`, `driver_map.py`: local replacement for the OpenDriver backend, recovered
  from the Dart sources in `opendriver_dart/`. Mutations persist to `opendriver-backend-state.json`.
* `benchmark-v2/`: generated OpenPhoto Cooking inputs and the device reference exports used by the
  v1 OpenPhoto tasks.

The patched APKs (`apks/`), extracted app assets (`app_assets/`) and VM baseline disks
(`vm-original-disks/`) are not in Git; see the handover document for how to restore them.
