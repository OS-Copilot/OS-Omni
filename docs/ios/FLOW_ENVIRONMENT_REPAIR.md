# Flow host helper repair

The committed macOS Framework top-level ObjectBox file contains the text `Versions/Current/ObjectBox`, rather than a symlink. Its real Mach-O binary remains present at `Versions/A/ObjectBox`. The helper now binds directly to that versioned binary. No app state or evaluation requirement changes. Native loading and a real audit simulator database summary passed.

Use pinned Flutter 3.41.9 (Dart 3.11.5); the newer 3.47.7 conflicts with the committed material icon dependency. Asset provenance and hashes are recorded in the environment manifest.
