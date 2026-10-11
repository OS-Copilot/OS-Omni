# Safari first-run onboarding in benchmark setup

On a clean iOS 26.5 simulator, Safari can display a first-run “Start Page” sheet when the app is opened. The previous benchmark initializer dismissed system alerts but did not recognize this sheet, then terminated Safari. A formal agent would therefore start with an unrelated onboarding overlay covering the browser.

`SafariPrepareOpenAppInitializer` now checks Safari's accessibility tree after launch. It closes the accessible `close` button only when the `Start Page` heading is also present, records whether it dismissed the sheet, and returns an initialization error if the sheet remains open or has no matching close button. When the sheet is absent, the initializer leaves Safari's interface untouched.

The repair is covered by tests for dismissal, no-op behavior, and failure when dismissal does not work. On the single iOS 26.5 simulator, a fresh preflight reported `dismissed_start_page_onboarding: true`; a follow-up launch showed the normal Safari Start Page with no onboarding sheet. The task-specific evaluator still returned the expected initial `FAIL` because the requested tabs, folder, and bookmarks had not been created. No formal model run occurred before this fix.
