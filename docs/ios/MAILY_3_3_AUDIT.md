# Maily 3_3 formal-run audit (2026-10-12)

Task: `ios.maily.instruction_3_3` (nine ordered outgoing messages).

## Attempt 001: excluded, not scored

- DeepSeek `deepseek_flash`, reasoning effort `none`, completed 94 of the 180 allowed steps.
- Initializer PASS; five exact Field source messages seeded and verified; Maily was foregrounded on the existing simulator and its data container was healthy.
- The original evaluator had a confirmed environment-binding defect: it compared the simulator's editable display name with the stale string `iphone17-2`. The task ran on the benchmark author's requested long-lived simulator, whose actual device type is `com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max` and whose display name is `OS-Omni iOS v3`. The evaluator therefore returned `bound_maily_runtime: FAIL` independently of task completion. Attempt 001 is excluded from benchmark scoring.
- The evaluator also captured durable outcomes: `Field crew roster` and `Field water note` passed; the `FieldFwd0708` forward was missing its required attachment; the other six requested target messages were absent. Its result is retained as evidence only, not counted as a model score.
- The real action trace shows the model's repeated selectors and taps did execute on the app. Several nonexistent labels returned Appium `NoSuchElementException`; coordinate taps later succeeded. No independent evidence indicates the app or executor blocked the task. This partial model behavior does not override the environment exclusion.

## Repair and validation

The runtime gate now checks that the exact bound simulator is available, Booted, and has the configured Apple `deviceTypeIdentifier`. It no longer treats a user-editable display name as hardware identity. The task retains its nine original business requirements and strict MIME/attachment/order checks. The revised ruleset digest is `c6f515324e3f92ff8dd0576f4539d838225b192ae41f22bad36b7e4850fc6024`.

Independent reference tests synthesize all nine correct MIME outcomes and verify that every business and order check passes. A negative reference with altered attachment bytes is rejected by the SHA-256 check. Runtime tests accept the renamed correct device and reject a wrong device type or a non-Booted simulator. Attempt 001 will be preserved remotely; only this task is retested against the revised evaluation.

## Evidence

Full attempt and preflight traces, screenshots, terminal state archive, request audit, and evaluator details are attached to the GitHub release `author-eval-2026-10-11` as `ios-maily-3_3-attempt001-excluded-audit-20261012.tar.gz`.

## Attempt 002: confirmed DeepSeek model failure under the revised evaluator

- Device-type binding passed on the designated simulator; the initializer passed and the exact five source messages were visible in the real initial Inbox screenshot.
- The model stopped after 14 of 180 steps. Screenshots and the Appium trace show it opened the correct FieldRead0708 message, then tapped the font-size toolbar while trying to enter the reply. It repeatedly tapped the quoted-message area, where `switch_to.active_element.send_keys` failed because no text input element was focused. It then invoked unsupported `mobile: type` and ended with an import the adapter rejected before execution.
- The read-only evaluator found zero current-session target emails for all nine requested message checkpoints, and order failed because no sequence existed. The corrected runtime binding passed. The Maily sync-cursor health flag remained false because no message was sent; the actual initial screenshot and exact seed check show the app Inbox was available. That flag did not drive the failure: every required business output was independently absent.
- This is a valid A-class model failure. There is no app/executor defect in the recorded action path: unsuccessful taps hit the wrong control or the quoted message; unsupported commands/imports were rejected as specified. No task or business check was loosened. Attempt 002 is the scored result; attempt 001 stays excluded.

The complete attempt 002 bundle and repaired preflight are attached to the same GitHub release as `ios-maily-3_3-attempt002-model-fail-20261012.tar.gz`.
