# Maily 3_1 formal-run audit (2026-10-12)

Task: `ios.maily.instruction_3_1` (ten ordered replies, forwards, and new emails).

## Attempt 002: confirmed DeepSeek model failure

- Model: `deepseek_flash`; reasoning effort `none`, zero reasoning items; original 240-step cap preserved by the task but execution was capped at 180.
- Initializer PASS. It seeded and verified exactly seven Alpha source messages. The initial incomplete-task evaluator returned FAIL as expected. No target messages had been produced.
- DeepSeek's first response tried to `import time`. The iOS code adapter rejected the response before executing any Appium action (`outside_appium_framework: imports are not available in iOS Appium code mode`). The screenshot/trajectory shows the actual Inbox state and no click occurred.
- The final evaluator returned FAIL for all ten requested durable messages, global delivery-date order, and per-mailbox UID order. This matches the unchanged mailbox state. The action failure is directly recorded by the executor, not inferred from DeepSeek's explanation.

Classification: A-class model failure. No task requirement or evaluator rule was changed, and no retest is needed because the only action was rejected before execution and the initial state was correct.

## Attempt 001: excluded environment run

The earlier run used the old OpenApp-only initializer and the historical Maily hostname was not resolving; Maily displayed a connection failure. It is retained in the evidence bundle and excluded from model scoring. The fixed local GreenMail service, hostname alias, and task-specific seeder were used for attempt 002.

## Evidence

Full screenshots, trajectory, executor and request audit, terminal archive, both attempts, and the verified seeded preflight are attached to GitHub release `author-eval-2026-10-11` as `ios-maily-3_1-attempt002-audit-20261012.tar.gz`.
