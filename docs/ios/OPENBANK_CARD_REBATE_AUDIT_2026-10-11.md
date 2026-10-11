# OpenBank iOS card-rebate task audit (2026-10-11)

Task: `ios.openbank.card_rebate_dispute_183183` (v1, 240 original steps; queue cap 180).

## Result

Attempt 003 is a valid confirmed model failure. The iOS 26.5 preflight established the signed-in Jordan Lee account, the unfinished task returned FAIL, and the evaluator used the current-run event boundary (`baseline_max_event_seq=11`). DeepSeek Flash was configured with `reasoning.effort=none`. Its first action attempted `import time`; the iOS code adapter rejected the request before execution. No dispute, recipients, transfers, or settings were changed, and the exact-state evaluator correctly returned FAIL.

Attempts 001 and 002 are preserved but excluded from scoring. Attempt 001's actual first screenshot showed the sign-in form although the task contract requires Jordan's signed-in home. Attempt 002 ran on the correct signed-in screen, but the evaluator filtered all October 11 events through a hard-coded August 3 wall-clock window. The iOS run path also dropped initializer metadata, despite this evaluator supporting `initialization.metadata.baseline_max_event_seq`. Attempt 002's trajectory also shows unsuccessful navigation and a prohibited import, but the stale evaluator boundary makes that result unsuitable for a model score.

## Repair and validation

The OpenBank initializer now prepares the documented signed-in session without altering business data and captures the maximum persisted event sequence before the task. The iOS runner and real-device preflight now pass initializer metadata to the evaluator, so tasks with run-local causal boundaries can distinguish task events from prior app events. The evaluator's exact business checks and required event sequence were not relaxed.

Validation on the existing iOS 26.5 simulator: initializer PASS; visible account home; unfinished evaluator FAIL; automatic event boundary starts after sequence 11. A completed reference state with the specified dispute, recipients, transfers, and settings passes; changing Mira's account number still fails. Focused regression tests pass (8 tests including session preparation, current-run boundary selection, positive exact reference, and negative wrong-recipient check).

## Evidence

The complete raw attempts, screenshots, DeepSeek request audits, evaluator details, final-state archive, author audits, and direct-simulator preflights are published in the [audit evidence archive](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/ios.openbank.card_rebate_dispute_183183.audit-20261011.tar.gz) with its [file manifest](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/ios.openbank.card_rebate_dispute_183183.audit-20261011.manifest.json). The archive contains 80 files and its verified SHA-256 is `5381a23eb497c0a815e5c110d6d08a1fe90131e98b48f7d545c09877c8b7ef0d`. The manifest SHA-256 is `501c7f0e83d9be9be2c1fd37425b5f515ad16e739665c442c1faa913b88ceb91`.
