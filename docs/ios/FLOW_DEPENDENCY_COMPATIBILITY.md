# Flow benchmark dependency compatibility

The iOS Flow benchmark helper failed to initialize under Flutter 3.47.7 / Dart 3.13.5 because the locked `material_symbols_icons` 4.2906.0 package extends Dart's `IconData` outside its library, while `IconData` is now final. The initializer therefore returned an error before any model request.

The helper now resolves `material_symbols_icons` 4.2960.0 (still within the declared `^4.2906.0` constraint). No task text, seed semantics, executor behavior, or evaluator requirement changed. The updated lockfile was checked with the real benchmark seed runner, which produced JSON and persisted the three seeded accounts and opening transactions. A live iOS 26.5 preflight then passed initialization and correctly failed the unfinished task. An independent terminal-state reference passed for the exact $18.40 expense and failed for $18.41.

The failed pre-fix attempt is preserved and excluded from model scoring; only a subsequent run with captured wire-level reasoning settings can produce a valid model result.
