# iOS OpenShop Home Task Audit and Initializer Repair (2026-10-12)

Task: `ios.openshop.home_four_item_cart_checkout_368575`

## Root cause and repair

The first two formal attempts are excluded. `OpenShopSeedOpenAppInitializer` built its store with the helper's default key `openshop.localState.v1`, while this task and the packaged OpenShop app use `openshop.localState.v3`. The initializer reported success after writing an unused key; the app stayed on the sign-in page, and the evaluator correctly observed an unauthenticated state with no account record. Attempt 001 ended with an evaluator `ERROR` before any model step. Attempt 002 ran 41 steps against the invalid logged-out baseline and is contaminated regardless of its task actions.

The repair passes the task's configured local-storage key into `OpenShopStore.from_simulator`, creates the account-scoped `users` state expected by the current app, and includes the account ID in the session. The task now bootstraps WebKit storage before resetting it. The initializer rereads the persisted state after launch and fails initialization if the requested session or account data did not survive. Both the v1 task and its legacy `tasks/ios` mirror use the corrected initializer configuration.

Targeted tests passed: `11 passed` across the OpenShop store/origin and Trip Gear verifier suites. A real preflight on the single iOS 26.5 simulator then showed the logged-in OpenShop home page at 440x956 logical / 1320x2868 physical resolution. The post-launch session and account state were verified, the cart was empty, account binding and final-cart checks passed, and the incomplete task correctly failed the order/review checkpoints.

## Corrected formal attempt 003

DeepSeek used `reasoning.effort=none`; all 13 received responses had zero reasoning items. Initialization passed and the first bedding product was added to the cart. The model then misidentified the product-page navigation, issued taps at coordinates outside the logical screen or on the product image, and remained on the first product page. It finally attempted to import Selenium helper modules; the iOS adapter rejected imports before execution. The runner completed the task with a normal evaluator FAIL after 13 steps.

The final read-only state contains one bedding item in the cart and no orders or reviews. The evaluator reports the missing two orders, both reviews, and their timeline. Screenshots and WDA/Appium action results confirm the page did not navigate; no click, keyboard, screenshot, or state-capture failure was found. Attempt 003 is a confirmed model failure. Attempts 001 and 002 remain preserved in the evidence bundle but are excluded from scoring.

Evidence archive: [attempts 001-003 and initializer preflight audit](https://github.com/BaoZhuhan/os-omni/releases/download/author-eval-2026-10-11/ios.openshop.home_four_item_cart_checkout_368575.audit-attempts001-003.tar.gz) (SHA-256 `7952f39a21336923924a79c2682b7d26eef49603ae7179f5dbfa25117de775a8`).
