# iOS OpenBank Lena/Marco task — author-directed skip

Task: `ios.openbank.lena_marco_dispute_security_086132`. Preflight passed on the single existing iOS 26.5 simulator: initializer PASS, logged in as Jordan, initial evaluation FAIL, baseline event sequence 11, with valid 440×956 logical / 1320×2868 physical dimensions.

The formal run used `deepseek_flash`, `reasoning.effort=none`, and a 180-step cap. The operator stopped it after 42 completed trajectory steps under the user's instruction to skip slow tasks and continue elsewhere. The trace shows repeated navigation mistakes and text-selection-menu loops. There is no final evaluator result, so this attempt is **unscored** and is not a model failure. The partial native state confirms that the two recipient records were saved, but the required transfers were not; the event sequence reached 13 from baseline 11. Restore the OpenBank baseline before any future OpenBank task on this simulator.

The complete partial trajectory, screenshots, request audit, native state archive, and preflight are retained in the evidence release:

- [Partial-skip evidence archive](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/ios.openbank.lena_marco_dispute_security_086132.partial-skip-20261011.tar.gz) — SHA-256 `32bb1d44c3182afcef4cec6a997e5e7738a597b2be495f69fcd4489dfb159ad7`.
- [Archive manifest](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/ios.openbank.lena_marco_dispute_security_086132.partial-skip-20261011.tar.gz.manifest.json) — SHA-256 `9886c9cb0c035bd2e3d6826f6813f0f154e6bdd9524e17e9fe95571463ccd699`.
