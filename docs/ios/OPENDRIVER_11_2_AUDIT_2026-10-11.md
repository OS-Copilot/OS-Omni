# OpenDriver 11-2 audit and retest

## Attempt 001 disposition

Attempt 001 ran on the sole iOS 26.5 simulator with `deepseek_flash`, reasoning effort `none`, and a 180-step cap. The initializer passed. DeepSeek made 24 steps, added Visa ending 1111, but did not complete the requested ride, refunds, or support tickets. The trace shows taps outside visible controls and a rejected import attempt. The model did not create any ride, refund, or support-ticket records.

The result is excluded from the score because evaluation had two independent defects:

1. The final-default check counted defaults belonging to every user in the shared database. The task is scoped to `usr_rider_primary`; unrelated rider and driver defaults must not invalidate the rider’s PayPal default.
2. The task asks for the exact support text `Card charged`, but the evaluator expected `I need help with my ride.Card charged`, an unrequested prefix. The app’s form has that prefix as initial text, so the user instruction requires replacing it.

The evaluator now scopes payment methods, rides, refunds, and active rides to the primary rider/current session where appropriate, and checks the exact requested ticket text. The seeded-history target checks accept the persisted `pickupAddress` and `destinationAddress` fields.

## Validation

- iOS 26.5 simulator: one booted device, 440×956 logical and 1320×2868 physical pixels.
- Appium and OpenDriver backend reachable; initializer passed on the same device.
- Revised initial evaluation returned FAIL, as required; both seeded refund targets passed.
- Unit tests include the correct full reference state (PASS), an incorrect support message (FAIL), another rider’s default payment (does not invalidate), and two defaults on the target rider (FAIL).
- The excluded attempt’s newly added Visa card was removed and the seeded Visa 4242 default restored before retest. No task ride/refund/ticket state from attempt 001 was present.

Attempt 001 remains archived as excluded evidence and is not a model score. Attempt 002 is the only score-bearing attempt unless it too is excluded by audit.

## Attempt 002 audit

The repaired environment and evaluator were rechecked on the same simulator. Initial evaluation was FAIL with both seeded refund targets passing. The screenshot shows the signed-in rider on Account with Wallet expanded and the seeded Visa 4242 correctly marked Default. The formal run then initialized successfully and issued one DeepSeek request. The response contained reflection prose but no Python action block; the executor reported `missing_python_code_block`, and no action ran. The final screenshot and native backend state confirm that no card, ride, refund, or ticket was added. The corrected evaluator reported the expected unfinished-task checks as FAIL.

The request audit records `reasoning.effort=none` and zero reasoning items. Attempt 002 is retained but superseded after a final audit found the same account-scoping requirement for support tickets; that correction cannot turn the untouched state into a pass.

## Attempt 003 audit

Attempt 003 ran under the final evaluator and completed 41 steps. It correctly added Visa 1111 and restored PayPal as the default. It also submitted two Fare review refunds, but the database shows they target `ride_three_month_home_to_work` and `ride_three_month_work_to_home`; the second required target, `ride_three_month_lost_item`, has no request. The screenshots and database agree: the model selected the wrong history rides. The requested Green ride was never created, and neither support ticket was created. The no-active-ride check passes because there is no ride from this attempt to cancel.

The route target verifier passes on the seeded database and rejects a wrong address. A complete independently constructed reference state passes the full evaluator; wrong refund routes and wrong ticket text fail. Other users’ defaults and tickets are excluded from rider-scoped checks. No Appium action was lost or misreported, and the final screenshot shows the account page. The remaining failures are model navigation/task-completion failures, not app or verifier failures. Attempt 003 is the score-bearing `A_MODEL_FAILURE`; attempts 001 and 002 are retained but excluded due to earlier evaluator revisions.

Evidence bundle: [attempts 001–003 and audit artifacts](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/ios.opendriver.11-2.final.tar.gz).
