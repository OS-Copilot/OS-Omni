# Provenance — vendored openDriver backend

Source: `execution/shared/upstream-apps` (private execution mirror of the
Apache-2.0 upstream app collection).

Upstream pin (verified with `git rev-parse HEAD` inside
`execution/shared/upstream-apps`):

```text
0af1ba9d87577fcf5b994e99ff163f3155e7d309
```

License: Apache License, Version 2.0. The full upstream text is copied
verbatim as [LICENSE.upstream](./LICENSE.upstream) (tail carries
`Copyright 2024 XLANG NLP Lab`). No per-file license headers exist in the
backend sources, so the root LICENSE governs. License confirmed **before**
copying.

## What was vendored (byte-identical, sha256 verified)

From `Apps/openDriver/shared/backend/`:

- `src/server.js`
- `src/domain.js`
- `src/database/store.js`
- `src/database/seed.js`
- `package.json`, `package-lock.json`
- `README.md`, `.env.example`
- `test/domain.test.js`

From `Apps/openDriver/shared/docs/`:

- `API.md` → `shared-docs/API.md`

Layout here mirrors the upstream relative layout (`backend/...`,
`shared-docs/...`) so requires and docs stay valid.

## Deliberately excluded

- `node_modules/` — reinstallable via `npm ci` from the vendored lockfile.
- `data/opendriver-db.json` (167 KB seed snapshot) — regenerable; `store.js`
  calls `resetDb()` when the file is missing or `schemaVersion < 16`.
- `data/road-graphs/`, `data/route-cache/` (together ~19 MB), tile-cache,
  search-index — runtime caches; the server falls back to offline/online
  routing when they are absent.
- `public/` (37 MB Flutter web build incl. canvaskit) — optional static
  hosting only; `serveStaticFile` returns false when files are absent and all
  `/api`-style JSON routes work without it.
- `desktop_shell/`, `opendriver_*` platform shells, `scripts/`,
  `shared/flutter_app/` — runtimes/shells, not needed for backend
  reproducibility.
- Any `.env` with values — only `.env.example` (defaults, no secrets) is
  vendored.

## Credential scan

Scanned the vendored tree for private keys, cloud/API token shapes, and
password/secret assignments. No hits. The only credential-like string is the
publicly documented seed password (`Password123!`, exported as
`sharedPassword` in `seed.js` and listed in the backend README) shared by all
seeded test accounts — not a live secret.

The added backend/.gitignore excludes generated databases, dependency installs and local environment configuration. All required backend source is present in this directory, so reproducing it does not require access to the original private mirror.
