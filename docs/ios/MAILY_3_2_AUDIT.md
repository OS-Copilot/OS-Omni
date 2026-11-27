# Maily 3_2 formal-run audit (2026-10-12)

Task: `ios.maily.instruction_3_2` (nine ordered email actions).

## Formal result

- Status: **confirmed DeepSeek model failure**; attempt 001, one model step, 180-step cap (original task cap 240).
- Model: `deepseek_flash`; Responses API audit recorded `reasoning.effort=none`, zero reasoning items/tokens.
- Initializer: PASS. It reset only the isolated local GreenMail fake mailboxes, seeded exactly seven required Route messages, verified no missing/duplicate seeds, and opened Maily on the existing iOS simulator.
- Initial state: strict evaluator FAIL, as required for an incomplete task. Screenshot captured at 440×956 logical / 1320×2868 physical pixels; foreground app was `de.enough.maily`.
- DeepSeek's first response contained `import time`. The iOS adapter rejected it before executing any Appium operation (`outside_appium_framework: imports are not available in iOS Appium code mode`). The trace confirms the environment did not receive a click or other task action. The task remained incomplete and the read-only evaluator correctly returned FAIL.

## Classification and action

This is an A-class model failure. The app, seeder, API connectivity, screenshot, coordinate dimensions, and initial negative evaluator check all passed. The action failure is directly evidenced by the model response, executor rejection, unchanged screenshot, and final evaluator details. No evaluator or task requirement was changed, and no retest is warranted under the audit rule: the requested action was clearly rejected by the model's prohibited import before execution.

An earlier preflight without `MAILY_BENCH_SENDER_PASSWORD` was an initializer setup error and is excluded; it is not a formal attempt. The successful preflight and formal run both used the same already-booted simulator; no second simulator was started.

## Reproduction

Start the local GreenMail 2.1.14 service on the configured host and ports, make the historical Maily hostname resolve to the host, set `MAILY_BENCH_SENDER_PASSWORD` for the local fake account, then run the iOS queue for this task with `--ios-direct-udid` set to the existing simulator. The task YAML contains the exact seed/API configuration. Formal trace bundle and preflight screenshots are attached to GitHub release `author-eval-2026-10-11` as `ios-maily-3_2-attempt001-audit-20261012.tar.gz`.
