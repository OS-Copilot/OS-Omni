# opendriver Backend

Local Node.js API for the Flutter cross-platform opendriver app.

## Run

```bash
cd shared/backend
npm start
```

Default URL:

```text
http://127.0.0.1:4320
```

## Seeded Accounts

All seeded accounts use:

```text
Password123!
```

- Rider: `rider@example.com`
- Approved driver: `driver@example.com`
- Pending driver: `pending-driver@example.com`
- Admin: `admin@example.com`

## Storage

The API stores local data in:

```text
shared/backend/data/opendriver-db.json
```

Reset seed data:

```bash
npm run seed
```
