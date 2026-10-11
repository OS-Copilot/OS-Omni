# opendriver API

Base URL defaults to:

```text
http://127.0.0.1:4320
```

Responses:

```json
{ "success": true, "data": {}, "message": "OK" }
```

Errors:

```json
{ "success": false, "error": { "code": "ERROR_CODE", "message": "..." } }
```

Use:

```text
Authorization: Bearer <token>
```

## Auth

- `GET /config/bootstrap` returns supported service cities, popular pickup/dropoff locations, local currency metadata, seeded account password, and app metadata.

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

## Users

- `GET /users/me`
- `PATCH /users/me`
- `GET /users/:id` is limited to the current user or admins.

## Rider

- `POST /rides/estimate`
- `POST /rides/request`
- `GET /rides/active`
- `GET /rides/history`
- `GET /rides/scheduled`
- `GET /rides/:id`
- `GET /rides/:id/messages`
- `POST /rides/:id/messages`
- `POST /rides/:id/cancel`
- `POST /rides/:id/confirm-boarding`
- `POST /rides/:id/rating`
- `GET /rider/saved-places`
- `POST /rider/saved-places`
- `DELETE /rider/saved-places/:id`
- `GET /rider/coupons`

## Driver

- `GET /driver/profile`
- `POST /driver/profile`
- `PATCH /driver/profile`
- `GET /driver/documents`
- `POST /driver/documents`
- `PATCH /driver/status`
- `PATCH /driver/location`
- `POST /driver/incoming-ride`
- `GET /driver/incoming-rides`
- `GET /driver/active-ride`
- `GET /driver/earnings`
- `GET /driver/history`
- `GET /driver/payouts`
- `POST /driver/payouts`
- `POST /driver/rides/:id/accept`
- `POST /driver/rides/:id/reject`
- `PATCH /driver/rides/:id/status`

## Admin

- `GET /admin/overview`
- `GET /admin/users`
- `GET /admin/drivers`
- `PATCH /admin/drivers/:id/approve`
- `PATCH /admin/drivers/:id/reject`
- `PATCH /admin/drivers/:id/suspend`
- `PATCH /admin/drivers/:id/unsuspend`
- `PATCH /admin/drivers/:id/documents/:documentId`
- `GET /admin/rides`
- `PATCH /admin/rides/:id/status`
- `GET /admin/payments`
- `GET /admin/refunds`
- `PATCH /admin/refunds/:id`
- `GET /admin/payouts`
- `PATCH /admin/payouts/:id`
- `GET /admin/support-tickets`
- `PATCH /admin/support-tickets/:id`

## Payments

- `GET /payments/methods`
- `POST /payments/methods`
- `PATCH /payments/methods/:id/default`
- `DELETE /payments/methods/:id`
- `GET /payments/history`
- `GET /payments/refunds`
- `POST /payments/refunds`
- `GET /invoices`
- `POST /invoices`
- `GET /payments/receipt/:rideId`

Payment authorization and capture are handled inside ride request and completion.

Ride estimates, receipts, and payment records include `currencyCode`, `currencySymbol`, and `currencyDecimals` so clients can display local market pricing.

## Support

- `POST /support/tickets`
- `GET /support/tickets`
- `GET /support/tickets/:id`
- `POST /support/tickets/:id/replies`

## Notifications

- `GET /notifications`
- `PATCH /notifications/:id/read`

## Maps

- `GET /map/tiles/:z/:x/:y.png`

Map tiles are proxied and cached by the local backend so GUI-agent tests can use a stable app URL while still allowing public tile-provider fallback in local mode.

## Development

- `POST /dev/reset`
