# OpenDriver 11-1 audit — 2026-10-11

## Outcome

Attempt 1 is a valid, confirmed model failure. DeepSeek received the OpenDriver home screen and the task instruction, then returned only a prose reflection. The iOS action adapter requires either a fenced Python action or a documented special action; it correctly reported `missing_python_code_block`. No action was executed, and the durable task state remained unchanged. The API request audit records `reasoning.effort=none`, zero reasoning items, and one completed model response.

The final screenshot confirms that the app stayed on the authenticated rider home screen. The evaluator reported both seeded refund targets accurately and retained FAIL for the missing rides, refunds, and support ticket. No App, initializer, simulator, or executor defect explains this model outcome.

## Verifier correction

The seed database stores historical ride addresses in `pickupAddress` and `destinationAddress`; both OpenDriver 11-1 and 11-2 evaluators had attempted to read `pickup` and `destination`. The evaluator specs still use the concise check names, while `FIELD_ALIASES` now maps them to the stored schema. The reported evidence also reads the mapped fields, so a passing check exposes the actual address values.

Independent checks show that the exact seeded route records pass and that changing a destination causes the corresponding target check to fail. A complete synthetic 11-1 reference state passes; a wrong refund reason fails. The unmodified live seed state remains FAIL on all uncompleted task requirements after the address checks pass. The old attempt is preserved as evidence; it is scored as a model failure because the response format error came from the model, not the adapter.

## Reproduction

- Simulator: one booted iOS 26.5 simulator, logical 440×956 points at 3× scale.
- OpenDriver was logged in before the formal run, matching the task's declared prerequisite. The session contained no task-created rides, refunds, or tickets.
- Initializer: PASS; initial evaluation: FAIL as expected.
- Formal attempt: `deepseek_flash`, `reasoning_effort=none`, screenshot-only observations, 180-step cap; one model step.
- Tests: `PYTHONPATH=. .venv/bin/pytest -q tests/test_ios_opendriver_11_1_refund_target_fields.py`.
- Evidence is retained in the `ios.opendriver.11-1.model-fail.attempt001.tar.gz` GitHub Release asset; its manifest contains hashes for the request audit, trajectory, screenshots, evaluator output, and final state.
