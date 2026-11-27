# Maily App Repair Investigation (iOS)

- Date: 2026-10-11 (UTC).
- Scope: source provenance/version verification, rebuild feasibility, account
  endpoint config schema, and a source-level repair proposal for the account
  editor `Signature` failure. No simulator/VM/Appium/model/GreenMail
  operation, no account changes, no secrets/`.env`/keychain reads, no
  commits/push.
- Ownership: all new work lives in `execution/shared/maily-source-checkout`
  and this file. No other repository paths were modified. The two upstream
  checkouts below are uncommitted working-tree edits for Root review.
- Collaboration rules from `execution/source/AGENTS.md` and
  `execution/shared/upstream-apps/AGENTS.md` were read and followed.

## 1. Official source provenance (verified, not assumed)

The public upstream `Enough-Software/maily` hypothesis was verified through
official GitHub API metadata (not fork lore):

- Canonical repo: `Enough-Software/maily`, default branch `main`, not a fork,
  not archived.
- Clone URL: `https://github.com/Enough-Software/maily.git`.
- License: GNU General Public License v3.0 (`GPL-3.0`), confirmed both via the
  API record and the `LICENSE` file in the checkout.
- Pinned revision in `execution/shared/maily-source-checkout/maily`:
  `c05a128edb51102817e56f09eadc72ed077dccb6`
  (`chore: modernize`, 2026-05-03; parent `10b8fcb chore: upgrade
  dependencies`).
- iOS bundle identifier in source matches the installed app:
  `de.enough.maily` in `ios/Runner.xcodeproj/project.pbxproj`.
- Source `pubspec.yaml` version `1.0.0+96` matches the installed bundle
  metadata exactly (see section 2).

The account editor and `Signature` widget live in the sibling library, also
verified via official metadata (`Enough-Software/enough_mail_app`, `GPL-3.0`,
default branch `main`):

- Pinned revision in
  `execution/shared/maily-source-checkout/enough_mail_app`:
  `fc92b2ccb31647cf0835df02ebb56c4b2ce86c68`
  (`chore: use git-based dependencies`, 2026-04-26) — the newest upstream
  commit predating the pinned Maily revision, i.e. contemporary with the
  `ios-v3.1` bundle. (Upstream `main` has since moved on, e.g. `88ebee8`
  2026-06-10; do not rebuild against floating `main`.)
- Total checkout size is ~12 MB (3.7 MB `maily` + 8.4 MB `enough_mail_app`
  working trees), well within the ~12 GB free-disk budget.

## 2. Installed App version (records only, no device operation)

From `execution/records/ios-app-versions.json` and
`execution/records/ios-installed-apps.plist` (read-only):

- `de.enough.maily`: `CFBundleDisplayName` Maily,
  `CFBundleShortVersionString` `1.0.0`, `CFBundleVersion` `96`,
  `ApplicationType` User. This is the official `ios-v3.1` bundle and matches
  the pinned source `1.0.0+96`.

## 3. Observed failures (Root-owned GUI evidence, quoted)

- Stale-endpoint failure: the manage-accounts audit records
  `SocketException: Failed host lookup: 'hanqideMacBook-pro.local' (OS Error:
  nodename nor servname provided, or not known, errno = 8)` for the fixture
  account (`maily-account-gui-inspect-repaired.log`). Classification recorded
  in `maily-gui-root-cause.json`: historical machine hostname baked into the
  snapshot account, absent on this host. This is an environment/fixture issue,
  not a model failure; evaluators must not be adapted to it.
- Account editor failure: `records/ios-preflight/maily-account-details-audit`
  (`inspect_20261011_020243_641.png`, `observation.json`) shows the Edit
  Account screen rendering through Account name / Your name / `Signature`,
  then a full-width red error box reading
  `Instance of 'CircularDependencyError'` (`See also:
  https://docs.flutter.dev/testing/errors`) exactly where `SignatureWidget`
  should render. The accessibility tree ends at the `Signature` label (node
  `n14`), consistent with the signature subtree failing to build.

## 4. Diagnosis: provider-graph cycle through the signature fallback

Code references are to the pinned `enough_mail_app` revision `fc92b2c`:

- `lib/src/screens/account_edit_screen.dart:160` embeds
  `SignatureWidget(account: account)` under the `Signature` title.
- `lib/src/widgets/signature.dart:26-29` initializes state with
  `account?.getSignatureHtml(ref.text.localeName) ?? ref.read(
  settingsProvider.notifier).getSignatureHtmlGlobal()`.
- `lib/src/settings/provider.dart:64-65,80-81` (pre-fix)
  `getSignatureHtmlGlobal()` / `getSignaturePlainGlobal()` fell back to
  `'<p>---<br/>${ref.text.signature}</p>'` / `'\n---\n${ref.text.signature}'`,
  where `Ref.text` (`lib/src/localization/extension.dart:27-30`) is
  `read(currentAppLocalizationProvider)`.
- `lib/src/localization/provider.dart:15-17`
  `CurrentAppLocalization.build()` does
  `ref.watch(settingsProvider.select((settings) => settings.languageTag))`.

So the settings notifier reads the localization provider, which watches the
settings provider — a settings→localization→settings dependency loop on the
exact path the account editor exercises whenever neither the account nor the
global signature is set (the fixture state). Maily's own override
(`maily/lib/settings/provider.dart`, `CustomSettingsNotifier`) duplicated the
same `ref.text.signature` reads, carrying the defect into the app target.
The precise runtime interleaving needs a Root-coordinated reproduction, but
the notifier→provider read is the only provider-graph interaction in the
failing subtree, and removing it is safe regardless.

## 5. Repair implemented in the owned checkout (uncommitted, for review)

- `enough_mail_app/lib/src/settings/provider.dart`: the two global fallbacks
  are now pure functions of `state`. The default signature word is resolved
  via `lookupAppLocalizations(PlatformDispatcher.instance.locale).signature`
  with an `AppLocalizationsEn` fallback on `FlutterError` — same localized
  defaults (`en`: `Sent with Maily`, `de`: `Mit Maily gesendet`), zero
  provider interaction. The now-unused `localization/extension.dart` import
  was removed.
- `maily/lib/settings/provider.dart`: removed the two `ref.text`-based
  overrides; `CustomSettingsNotifier` inherits the fixed base. The class
  remains as the customization hook, with a comment warning against
  reintroducing provider reads.
- Regression test (new):
  `enough_mail_app/test/settings/signature_fallback_test.dart` follows the
  repo's `flutter_test` conventions. It overrides
  `currentAppLocalizationProvider` with a throwing factory, so the pre-fix
  implementation fails and the fixed one passes; plus a verbatim-explicit-
  signature case. Authored but NOT run: executing `flutter test`/`pub get`
  counts as a build and is reserved for Root coordination (toolchain present:
  `execution/ios/toolchain/flutter-compatible/flutter`, Flutter 3.41.9).

## 6. Portable account endpoint config schema (non-secret, field names only)

Accounts persist via `AccountStorage` (`lib/src/account/storage.dart`):
JSON list under key `accts` in `FlutterSecureStorage` (iOS keychain; the
code wipes it on first run after reinstall, lines 22-29 — no keychain read
was performed here). Each entry is a `RealAccount`
(`lib/src/account/model.dart`) wrapping an `enough_mail` `MailAccount` under
the `mailAccount` key, with attributes `signatureHtml`, `signaturePlain`,
`excludeUnified`, `bccMyself`, `enableLogging`, plus `aliases`. Server
endpoints live at `mailAccount.incoming.serverConfig` /
`mailAccount.outgoing.serverConfig`, each carrying `hostname`, port, and
socket type (confirmed via `lib/src/extensions/extensions.dart:94-96`, which
reads `...incoming/outgoing.serverConfig.hostname`). Porting the fixture
account therefore means rewriting those two endpoint records (or clearing
the `accts` key and re-adding the account against a reachable host) — a
data/fixture operation owned by Root, not a code change.

## 7. Rebuild feasibility with Flutter 3.41.9

- SDK compatibility: YES on paper. Pinned source requires
  `flutter >=3.41.7` / `dart >=3.11.5 <5.0.0`; the available toolchain
  reports Flutter 3.41.9 / Dart 3.11.5 (`flutter-compatible-version.json`).
- Rebuild blockers (do not attempt without Root coordination):
  1. `maily/pubspec.yaml dependency_overrides` force 14 sibling
     `../enough_*` path checkouts (`enough_mail_app`, `enough_mail`,
     `enough_mail_flutter`, `enough_mail_html`, `enough_icalendar`,
     `enough_mail_icalendar`, `enough_giphy`, `enough_giphy_flutter`,
     `enough_icalendar_export`, `enough_media`, `enough_html_editor`,
     `enough_text_editor`, `enough_ascii_art`, `enough_platform_widgets`);
     only the first is present in the owned checkout, and `pubspec.lock` is
     path-based, so a fresh resolve is not reproducible until all siblings
     are pinned alongside.
  2. iOS signing for `de.enough.maily` and device/simulator provisioning are
     unresolved and Root-owned.
  3. No `flutter pub get / build / test` was executed in this pass.

## 8. Independent fix options (no evaluator adaptation)

1. (Recommended) Accept the section-5 source repair, then Root coordinates
   `flutter test` (new regression test plus existing `test/model`,
   `test/util`) and a signed rebuild with all 14 sibling deps pinned.
2. Fixture-only relief, no rebuild: re-point the stale
   `hanqideMacBook-pro.local` endpoints to a reachable host (or clear the
   `accts` keychain entry and re-add the account) through the Root-owned
   account/server GUI flow. This fixes connectivity but NOT the
   `CircularDependencyError`.
3. Out of scope / rejected: changing benchmark tasks or evaluators to
   tolerate either failure as a model limitation.

## 9. Exact revision/license record

- `maily`: `c05a128edb51102817e56f09eadc72ed077dccb6`, GPL-3.0,
  `https://github.com/Enough-Software/maily.git`.
- `enough_mail_app` (diagnosed/repaired library):
  `fc92b2ccb31647cf0835df02ebb56c4b2ce86c68`, GPL-3.0,
  `https://github.com/Enough-Software/enough_mail_app.git`.
- Working-tree deltas (uncommitted): `maily`: `M lib/settings/provider.dart`;
  `enough_mail_app`: `M lib/src/settings/provider.dart`,
  `?? test/settings/signature_fallback_test.dart`.

---

# Continuation pass (2026-10-11, UTC) — Root-authorized simulator rebuild

Scope of this pass (per Root): resolve the 14 sibling path dependencies from
pinned official sources, run the signature regression FAIL pre-fix / PASS
post-fix (fixing both provider fallbacks including the Maily override), add a
benchmark-only compile-time endpoint override for fake `.test` accounts, and
rebuild the iOS simulator app unsigned (`--simulator --no-codesign`). No
device/Appium operation, no app installs, no `.env`/keychain/credential reads,
no passwords printed, no commits/push. Ownership unchanged: this file plus the
entire `execution/shared/maily-source-checkout` subtree; no other repo paths
modified. Machine-level notes: `flutter config --enable-swift-package-manager`
was set for the Powers user config (additive, reversible; required by an
SPM-only transitive plugin, see section 13) and the `cocoapods` gem (1.17.0)
was installed from `rubygems.org` after the preconfigured mirror failed TLS.

## 10. Sibling dependency provenance (all 14 resolved, pinned, licensed)

Each sibling below is a full git checkout in
`execution/shared/maily-source-checkout/<name>`, cloned from the official
`https://github.com/Enough-Software/<name>.git` (all 13 verified to exist via
`git ls-remote`; `maily`/`enough_mail_app` pins predate this pass). Pin rule:
newest upstream commit predating the Maily source date (2026-05-03) whose
`pubspec.yaml` version equals the version recorded in the committed
`maily/pubspec.lock`. Every pin matches its locked version exactly:

| repo | pinned SHA | date | pubspec version | license |
|---|---|---|---|---|
| maily | `c05a128edb51102817e56f09eadc72ed077dccb6` | 2026-05-03 | 1.0.0+96 | GPL-3.0 |
| enough_mail_app | `fc92b2ccb31647cf0835df02ebb56c4b2ce86c68` | 2026-04-26 | 1.0.0+96 | GPL-3.0 |
| enough_mail | `2f73b36f85237af450ee6d54d6aae8fa77eeb1ba` | 2026-05-01 | 2.2.3 | MPL-2.0 |
| enough_mail_flutter | `f56f8bb473f51aa39ce7f03354c019665431f9c1` | 2026-05-01 | 2.1.2 | MPL-2.0 |
| enough_mail_html | `2a8378a96eda94c87b9f06ccb27cad1574bf2c85` | 2026-05-01 | 2.0.2 | MPL-2.0 |
| enough_icalendar | `a312a173bc251138a41cab371e5c51db6f34ae40` | 2026-05-01 | 0.17.0 | MPL-2.0 |
| enough_mail_icalendar | `73f8e195f00bdb069934b6601e240bf0182a6e22` | 2025-08-19 | 0.2.2 | MPL-2.0 |
| enough_giphy | `31c50fb54976c70463ca793c9c57982d88751967` | 2023-09-04 | 0.2.1 | MPL-2.0 |
| enough_giphy_flutter | `b6b04b811e6c6addf6d91cf738c77b900c72d46f` | 2026-05-01 | 0.4.2 | MPL-2.0 |
| enough_icalendar_export | `30f75d6051d89a667a8b916f76490f43ba644397` | 2026-05-01 | 0.4.0 | MPL-2.0 |
| enough_media | `7c0d2ee3bcf79440f4118d4bd511ea93591c4cb8` | 2026-04-26 | 3.0.0 | MPL-2.0 |
| enough_html_editor | `f6daabdb00ec7d7a00fe03449ed48d7ebd86a1c3` | 2026-05-01 | 0.0.6 | MPL-2.0 |
| enough_text_editor | `bc7eb7d29d3e254f3487e1f70745f2e5e5e69b7f` | 2026-04-26 | 0.1.1 | MPL-2.0 |
| enough_ascii_art | `fdf1de527586e77ff80bb54ec60ca0828556ae73` | 2026-04-26 | 1.1.2 | MPL-2.0 |
| enough_platform_widgets | `38f080f758da42dd9e66d49adbba02aa28d9ff7c` | 2026-04-26 | 1.1.2 | MIT |

(Licenses read from each checkout's `LICENSE` file: GPL-3.0 for the two app
repos, MPL-2.0 for the `enough_*` libraries, MIT for
`enough_platform_widgets`.) Total checkout size ~481 MB including build
outputs; disk stayed above 8 GB free throughout.

Three real resolution defects were found and fixed (all in owned files):

1. `enough_mail_app/pubspec.yaml`: the 12 git-based `dependency_overrides`
   were indented at column 0, so YAML parses them as unknown top-level keys
   and pub silently resolved stale pub.dev releases (e.g. `enough_mail`
   2.1.7, which lacks `MailClient.eventStream` and breaks compilation). Fixed
   by indenting them under `dependency_overrides:` and pinning each with
   `ref:` to the table above (plus the same `ref:` on the direct
   `enough_text_editor` git dependency). Intent matches the pin commit
   `fc92b2c` ("chore: use git-based dependencies").
2. `maily` ↔ `enough_mail_app` riverpod conflict: `maily@c05a128` demands
   `hooks_riverpod ^3.3.1` / `riverpod_annotation ^4.0.2` while the pinned
   library requires `^2.6.1` — unresolvable as committed (verified: no
   `enough_mail_app` commit exists between `fc92b2c` and the Maily date, so
   the committed `maily/pubspec.lock` riverpod-3 closure is irreproducible
   from committed sources). Fixed by aligning `maily` down to the `2.6.1`
   stack (the library uses `StateProvider` at 4 sites and 19
   generator-2.x `.g.dart` files, so moving the app down touches 2 generated
   files vs 19+4 the other way), regenerating `maily`'s two `.g.dart` files
   with `riverpod_generator` 2.4.0, and removing the unused
   `freezed`/`hive_ce_generator` dev deps (no annotations under
   `maily/lib`/`test`; they require analyzer ^9 vs riverpod_lint 2.x's ^7).

## 11. Signature regression: FAIL pre-fix, PASS post-fix

With the pinned git resolution in place, the pre-fix code (repair stashed)
fails exactly on the diagnosed path — `SettingsNotifier`
→ `AppLocalizationRef.text` → `currentAppLocalizationProvider` (2 failing
cases, verbatim case passing). The previously authored (never-run) fix had
two compile errors, now corrected: `AppLocalizationsEn()` has no `const`
constructor, and `PlatformDispatcher` needs `import 'dart:ui'`. Post-fix
(`git stash pop` + fixes): `test/settings/signature_fallback_test.dart`
3/3 PASS; together with `test/util` + `test/model/async_mime_source_test`
51/51 PASS. `flutter analyze` reports no errors in any created/edited file
(3 remaining info lints on the new override lines are inherent to the
required `bool.fromEnvironment` mechanism; see section 12).
Pre-existing, unrelated: `test/model/multiple_message_source_test.dart` does
not compile (`TestScaffoldMessengerService` misses
`ScaffoldMessengerService.statusBarState`) — left untouched for Root triage;
it is test-only and not shipped in the app.

## 12. Benchmark-only compile-time endpoint override

`enough_mail_app/lib/src/mail/service.dart` (`EmailService`, new static
members; wired into `createMailClient`, i.e. before every
`MailClient.connect`): opt-in `bool.fromEnvironment('OS_OMNI_LOCAL_MAIL',
defaultValue: false)`. When compiled with
`--dart-define=OS_OMNI_LOCAL_MAIL=true`, accounts whose email domain sits
under the reserved `.test` TLD (benchmark fixture addresses are
`...@example.test`, confirmed from task/evaluator sources) are routed to
`127.0.0.1` IMAP `3143` / SMTP `3025`, `SocketType.plain`, rebuilt with the
real `ServerConfig`/`MailServerConfig`/`MailAccount.copyWith` profile types,
preserving server type, authentication and username type. Defaults unchanged
(flag off returns the stored account identical), non-`.test` accounts never
rewritten, transport-only — no business/task-completion logic touched.
Durable test `enough_mail_app/test/mail/local_transport_override_test.dart`
passes in both modes (default 2/2; `--dart-define=OS_OMNI_LOCAL_MAIL=true`
2/2), and a throwaway probe confirmed the flag reads `false`/`true`
respectively (probe deleted afterwards). No credentials read or printed;
fixtures use synthetic `PlainAuthentication('fixture', 'fixture')`.

## 13. Simulator build (unsigned, arm64)

- Command (from `execution/shared/maily-source-checkout/maily`):
  `execution/ios/toolchain/flutter-compatible/flutter/bin/flutter build ios
  --simulator --no-codesign` (exit 0; Xcode build 487 s). No `--dart-define`
  passed, so the artifact keeps stock endpoints; the loopback variant rebuilds
  with `--dart-define=OS_OMNI_LOCAL_MAIL=true` appended.
- Toolchain: Flutter 3.41.9 / Dart 3.11.5 (compatible toolchain), Xcode 27.0
  (27A266a), CocoaPods 1.17.0, macOS arm64.
- Artifact: `maily/build/ios/iphonesimulator/Runner.app` (210 MB).
  `lipo -info`: non-fat arm64. `Info.plist`: `de.enough.maily`, `Maily`,
  `1.0.0`, `96` — same bundle/version as the installed `ios-v3.1` bundle.
  SHA-256: Runner binary
  `d32ae0b0abf2ac262263e4b60a33103d6fa2d5e9123238383ff80e851210dd6c`,
  `Info.plist`
  `990c71ca8ded20c2d5253c34f82059b15191327a0521fddee4d025b3fff861a3`.
- Real build issues fixed (all in owned files except the noted user-config
  flag): (a) `add_2_calendar_plus` 1.0.0 (transitive via pinned
  `enough_icalendar_export` 0.4.0) is SPM-only, which hard-fails CocoaPods
  builds — enabled Swift Package Manager support (source-only package, no
  remote deps); (b) `flutter_tools` 3.41.9 passes Xcode's multi-arch
  `ARCHS="arm64 x86_64"` into `lipo -verify_arch`, which accepts exactly one
  arch — constrained the Runner target to `ARCHS = arm64` in all three
  target configs (exactly the requested simulator arm64 slice; device builds
  were already arm64); (c) Xcode 27 minimum deployment target 15.0 —
  Runner `IPHONEOS_DEPLOYMENT_TARGET` 13.0→15.0 (×3), `ios/Podfile`
  `platform :ios, '13.0'`→`'15.0'`, plus a `post_install` floor clamping
  every pod target to ≥15.0 (several transitive podspecs declare 9.0–13.0;
  no pod sources modified).

## 14. Final deltas and handoff

- `maily` (vs `c05a128`): `M lib/settings/provider.dart` (prior pass),
  `M lib/account/provider.g.dart`, `M lib/settings/ui/provider.g.dart`
  (regenerated, gen-2 style), `M pubspec.yaml`, `M pubspec.lock`,
  `M ios/Runner.xcodeproj/project.pbxproj` (ARCHS + deployment target),
  `M ios/Podfile`, `M ios/Runner.xcscheme` + `M ios/Flutter/AppFrameworkInfo.plist`
  + `M macos/Flutter/GeneratedPluginRegistrant.swift` (tool-generated),
  `?? ios/.../swiftpm/` (tool-generated SPM wiring).
- `enough_mail_app` (vs `fc92b2c`): `M lib/src/settings/provider.dart`
  (signature fix + 2 compile corrections), `M lib/src/mail/service.dart`
  (transport override), `M pubspec.yaml` (override indentation + ref pins),
  `?? test/settings/signature_fallback_test.dart`,
  `?? test/mail/local_transport_override_test.dart`.
- Sibling checkouts: pristine at their pins (detached HEAD, no deltas).
- Handoff: artifact and provenance above are ready for Root's actual
  GUI/Inbox verification (positive/negative) before anything is formalized;
  nothing committed, pushed, installed, or run on device.

## 15. Loopback variant rebuild (`OS_OMNI_LOCAL_MAIL=true`, 2026-10-11 UTC)

Exclusive rebuild pass per Root: no source edits, no GUI/Appium/device
operation, no `git stash`/`reset`/`checkout`. Only the build was executed
and this section appended.

- Exact command (from `execution/shared/maily-source-checkout/maily`,
  pinned Flutter 3.41.9):
  `/Users/zhuhan/Documents/Research/OS-Omni[ArXiv]/execution/ios/toolchain/flutter-compatible/flutter/bin/flutter
  build ios --simulator --no-codesign
  --dart-define=OS_OMNI_LOCAL_MAIL=true`
- Exit status: 0 (`Xcode build done. 83.7s`,
  `Built build/ios/iphonesimulator/Runner.app`).
- Artifact: `maily/build/ios/iphonesimulator/Runner.app` (210 MB).
  `lipo -info`: non-fat arm64. `Info.plist`: `de.enough.maily`, `Maily`,
  `1.0.0`, `96` — same bundle/version as the installed `ios-v3.1` bundle.
- SHA-256: Runner binary
  `d32ae0b0abf2ac262263e4b60a33103d6fa2d5e9123238383ff80e851210dd6c`
  (identical to the section-13 stock build — expected, since Runner is the
  native launcher and the Dart payload ships in App.framework),
  `Info.plist`
  `cb5f401237889f19283bee175c2de441f623adfce9f8c55bca04281cbce0a361`,
  `App.framework/App`
  `cce5808a2ee2270a28875c950506c56e957b345d27898d2e54463fb684806c12`,
  `App.framework/flutter_assets/kernel_blob.bin`
  `7c55e2704657f3809b06b11790bf2d9751860f6038d2abf824bc7ad7e77143af`
  (the file carrying the compiled Dart code, hence the flag).
- Local-mail flag presence: the tool-regenerated
  `maily/ios/Flutter/Generated.xcconfig` and
  `maily/ios/Flutter/flutter_export_environment.sh` both list
  `DART_DEFINES=T1NfT01OSV9MT0NBTF9NQUlMPXRydWU=,...`, whose first entry
  base64-decodes to exactly `OS_OMNI_LOCAL_MAIL=true`. The
  `OS_OMNI_LOCAL_MAIL` symbol — including the
  `bool.fromEnvironment('OS_OMNI_LOCAL_MAIL', defaultValue: false)`
  reference behind `EmailService.useLocalTestMail` (section 12) — is present
  in the shipped `kernel_blob.bin`. `bool.fromEnvironment` is const-folded
  at compile time, so the `true` value is baked into that constant; the
  read-back mechanism itself was verified by the section-12 throwaway probe
  (`false` default / `true` opted-in).
