# OpenTrip iOS serial-run seed audit (2026-10-12)

## Finding and repair

OpenTrip keeps bookings in WebKit localStorage. The iOS task initializers previously launched the app without restoring task state. Reusing one simulator therefore carried dynamic bookings from one task into the next. Grand Axis attempt 001 began with two unrelated dynamic bookings (one NR2269 flight and one Seabreeze hotel), so that attempt is excluded from model scoring.

The OpenTrip tasks in the current iOS manifest all define the same four-booking seed. A shared initializer utility now reconstructs that state from the installed app's `public/seed-data.js`, terminates the app before writing SQLite, confirms the exact canonical state hash and booking order, launches and settles the app, and reads the state again to ensure startup did not rewrite it. A failed `simctl` process query now stops initialization instead of being mistaken for a stopped app.

The independent seed source SHA-256 is `6b1836923d6ad21aa0e977c03e3f0ba77ce531582488b75b8acb0a2cf43ebcba`. The evaluator's canonical baseline SHA-256 is `f2e6ce37e0fa96ec73fba0be4a339bb3047e8552f688b50158e5f94924e9ff04`; the four expected IDs are `OT-SEED-FLIGHT-1`, `OT-SEED-HOTEL-1`, `OT-SEED-FLIGHT-2`, and `OT-SEED-HOTEL-2` in that order.

## Formal checks and model results

Both initializers now used by the current manifest (the grand-axis initializer and the shared instruction initializer) passed preflight on the single bound iOS 26.5 simulator. The parkline-specific initializer was also repaired and passed its own preflight. Each preflight produced an initial evaluator FAIL with the clean-baseline checks passing. Focused automated checks passed: `tests/test_opentrip_seed_initializer.py`, `tests/test_opentwitter_seed_initializer.py`, `tests/test_ios_appium_builtin_contract.py`, and `tests/test_cua_review_evaluator_binding.py` (15 tests after the shared helper repair).

- `ios.opentrip.sc2306_grand_axis_booking_284952`: attempt 001 excluded for contaminated start state. Attempt 002 began with the exact clean baseline and failed after 9 DeepSeek requests without creating a flight or hotel booking. The screenshots show the search results count appeared; the model failed to navigate to/select a result, attempted text selection, and submitted a prohibited import. Classified as confirmed model FAIL. Reasoning effort was `none`, with zero reasoning items.
- `ios.opentrip.review_flight_hotel_reschedule_234497`: started from a clean, verified baseline. DeepSeek's first action included `import time`, which the transmitted iOS code-mode restrictions prohibit. The executor rejected the action and the task remained unchanged. Classified as confirmed model FAIL. Reasoning effort was `none`, with zero reasoning items.
- `ios.opentrip.sanya_parkline_review_mj2158_638214`: the task-specific initializer was repaired and its clean-baseline preflight passed. DeepSeek reached the intended flight and selected the 15 kg baggage option, then stalled on checkout navigation and submitted a prohibited import. No requested booking or review persisted; classified as confirmed model FAIL. Reasoning effort was `none`, with zero reasoning items.

The task implementation does not reduce or waive the requested booking/review requirements. No evaluator checks were loosened.

## Reproduction

From `execution/source`, run the focused tests above with the repository virtual environment. On a booted iOS simulator with the OpenTrip app installed, run `scripts/author_ios_preflight.py` for each task ID and a unique output directory. The preflight must report initializer PASS, `settled_state_verified: true`, `baseline_clean_exact: true`, and initial evaluator FAIL before queueing DeepSeek. The shared simulator is reused serially; no simulator clone or additional simulator is created.

The full attempt traces, screenshots, verifier outputs, initial/final state snapshots, and preflight evidence are archived in the [OpenTrip serial-run evidence bundle](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/opentrip-serial-attempts-20261012.tar.gz); the adjacent manifest records its SHA-256 and source commit.
