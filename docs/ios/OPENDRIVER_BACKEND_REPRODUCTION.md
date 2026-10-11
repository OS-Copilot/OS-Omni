# openDriver backend reproduction (portable, private-free)

Reproduce the openDriver backend API from the vendored source. Task and evaluator business logic is unchanged. Simulator UI connectivity and evaluator binding still require separate platform preflight.

Vendored source: `services/opendriver_backend/`
(see `PROVENANCE.md` there; Apache-2.0, upstream pin
`0af1ba9d87577fcf5b994e99ff163f3155e7d309`).

## 1. Canonical entry point and baseline

- Entry: `backend/src/server.js` (plain `node http`, sole runtime dependency
  `jpeg-js`). Start with `npm start` / `node src/server.js` from `backend/`.
- Default bind: `http://127.0.0.1:4320` (`HOST`/`PORT` environment variables). Choose a free port; an independent audit should use a distinct port such as `4331`.
- Upstream Electron launcher (`apps/opendriver/server.js`) only spawns this
  same backend and serves `public/`; it is **not** vendored and not needed.
- `GET /health` → `{status:"ok"}`; `GET /config/bootstrap` → service cities,
  locations, ride tiers.

## 2. Seed / reset APIs (canonical)

| API | Effect (from actual code) |
|---|---|
| `POST /dev/reset` | `store.resetDb()` → regenerates DB from `seed.js`, returns `{reset:true, meta}` |
| `npm run seed` | `node -e "require('./src/database/store').resetDb()"` |
| First start with no DB | `loadDb()` calls `resetDb()` when file missing **or** `meta.schemaVersion < 16` |

Seed identity: `createSeedData()` in `backend/src/database/seed.js`,
`meta.schemaVersion = 16`, 20 service cities, 140+ locations, seeded accounts
(`rider@example.com`, `driver@example.com`, `pending-driver@example.com`,
`admin@example.com`) sharing the documented seed password.

## 3. Persistence (DB locations)

- `store.js`: `DATA_DIR = <backend>/data`, `DB_PATH = <backend>/data/opendriver-db.json`.
- `DATA_DIR` is **hardcoded relative to the source file** (no env override),
  so a scratch DB means running a **temp copy** of `backend/` (see §6), never
  the live tree.
- Runtime caches under `data/` (`tile-cache/`, `road-graphs/`, `route-cache/`,
  `search-index/`) are optional: absent caches fall back to offline/online
  routing; none are vendored.

## 4. iOS surface the evaluators actually read

- Bundle: `com.killt.opendriver`; document: `opendriver-db.json`
  (`evaluators/cua_review/platforms/ios/opendriver_store.py`:
  `DEFAULT_BUNDLE_ID`, `DB_FILENAME`, `DB_RELATIVE_DIRS`).
- Evaluators read the **durable backend document read-only** (collections
  `users`, `sessions`, `rides`, `driverProfiles`, `payouts`, `supportTickets`,
  plus `payments`/`refunds`/`notifications`); intermediate pages and filenames
  are not acceptance evidence (task `verifier_rules`).
- Auth: `POST /auth/login` → `Authorization: Bearer <token>`.
- Endpoints exercised by the four iOS tasks (`tasks/v1/ios/opendriver_*.yaml`
  + `evaluators/ios/opendriver_*.py`, full list in `shared-docs/API.md`):
  `/auth/login`, `/rides/estimate`, `/rides/request`, `/rides/:id/cancel`,
  `/rides/active`, `/rides/history`, `/rides/:id`, `/payments/methods` (+
  `/:id/default`), `/payments/refunds`, `/support/tickets` (+
  `/:id/replies`), `/driver/profile`, `/driver/documents`, `/driver/status`,
  `/driver/payouts`, `/driver/incoming-ride(s)`,
  `/driver/rides/:id/accept|reject`.

## 5. Baseline: fresh seed FAILs (no answers seeded)

Against a fresh `POST /dev/reset`, every iOS openDriver evaluator fails —
this is the correct starting point, not a bug:

- `opendriver_11-1`: needs two **current-session** cancelled Green rides
  (PayPal/Stanford→Meta MPK 23; Visa→Downtown Palo Alto), two `Fare review`
  / `requested` refunds on `ride_three_month_home_to_work` and
  `ride_three_month_school_mall`, and an open `Blue umbrella` ticket with a
  `Rear seat` reply. Seed has: history rides without those refunds (seeded
  refund reason is `Fare adjustment after support review`, status `approved`),
  only old cancelled `standard`/`xl`/`plus` rides, no open umbrella ticket
  (seeded tickets are `closed`/`resolved`).
- `opendriver_11-2`, `opendriver_driver_payout_trip_support_profile`, and
  `opendriver_driver_requests_insurance_support_payout` likewise require
  post-seed writes (Visa-1111 card + PayPal default flip, payout `95.00`
  `Moring payout` / `135` `Weekend transfer`, profile `NY-DL-100492` Tesla
  Model Y, documents `DL-2026-2048` / `INS-2026-4096`, open support messages,
  post-seed reject/accept evidence, driver logout) — none present at seed.

## 6. Preflight / runtime config

Preflight (portable host):

1. `node --version` runs (any maintained Node 18+; sole dep `jpeg-js`).
2. `npm ci` (or `npm install`) inside a **scratch copy** of `backend/`.
3. Chosen port free and **not** 4320, e.g. `PORT=4331`; `HOST=127.0.0.1`.
4. Reachable loopback; outbound network optional (`OPENDRIVER_ONLINE_MAPS`,
   `OPENDRIVER_ONLINE_ROUTES` degrade gracefully offline).

Minimal scratch run (never touches live `:4320` or the vendored tree):

```bash
audit_backend=$(mktemp -d)
cp -R services/opendriver_backend/backend/. "$audit_backend/"
cd "$audit_backend" && npm ci --no-audit --no-fund
PORT=4331 HOST=127.0.0.1 node src/server.js &
curl -s http://127.0.0.1:4331/health
curl -s -X POST http://127.0.0.1:4331/dev/reset
kill %1
```

Runtime env (defaults in `src/server.js`, overridable):

```text
PORT=4331  HOST=127.0.0.1
AUTO_DISPATCH=true (false disables timers)
OPENDRIVER_ONLINE_MAPS=true  OPENDRIVER_ONLINE_ROUTES=true
OPENDRIVER_MAP_STYLE=osmde-retina
```

## 7. Terminal-store needs (what an iOS run leaves behind)

A completed task leaves only the mutated `opendriver-db.json` (plus optional
caches): new/updated `rides` (cancelled Green bindings), `refunds`
(`Fare review`/`requested`), `supportTickets` (+ replies), `paymentMethods`
(default flips), `driverProfiles`/`documents`/`payouts`, and cleared driver
`sessions` on logout. Evaluators assert on these fields; GUI navigation
itself leaves no other artifact the verdicts read.
