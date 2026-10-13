# LOGGING.md — Logging, Audit Trail & Request Correlation

Modeza ships centralized, structured logging across the Django backend with a
shared audit trail, per-request correlation IDs, sanitization, and a
server-rendered Activity Logs page in the Django admin UI.

## Loggers

| Logger            | Emits                                                        |
| ----------------- | ------------------------------------------------------------ |
| `modeza.http`     | One `http_request` envelope per API request (no bodies)      |
| `modeza`          | Request-level INFO lines from the existing API middleware    |
| `audit`           | Audit write warnings and coercion notices                    |
| `django.request`  | Django request errors (ERROR level)                          |
| `django.server`   | Runserver request lines                                      |
| `django.db.backends` | SQL queries when `LOG_LEVEL=DEBUG`                        |
| `payments`, `orders`, `catalog`, `inventory`, `accounts`, `admin_api`, `admin_ui` | App namespace loggers |

All loggers propagate to a single console handler. Two formats exist and are
selected with `LOG_FORMAT`:

* `text` (default, human-readable): `level logger message … request_id=… user_id=… ip=…`
* `json` (production): the same envelope as JSON, one object per line with
  `request_id`, `request_user_id` and `request_ip` fields.

`RequestContextFilter` injects `request_id`, `request_user_id` and `request_ip`,
and `JsonFormatter` serializes dict messages into flat JSON.

## Request correlation

`RequestContextMiddleware` (right after `SecurityMiddleware`) assigns every
request a fresh ID:

* Incoming `X-Request-ID` is honored only when it matches `^[A-Za-z0-9_-]{8,64}$`.
* Otherwise a `req_<32 hex chars>` ID is generated.
* The ID is echoed back on the `X-Request-ID` response header and attached to
  every structured log line and audit record written during the request.
* Client IP comes from `REMOTE_ADDR` (or the first `X-Forwarded-For` entry when
  `USE_X_FORWARDED_FOR=True`, required behind Render's proxy).
* `/static/` and `/media/` requests are skipped entirely.

## Audit trail

All audit records are written through `audit.services.AuditLogService.log(...)`
and never raise. The service auto-derives actor, request ID, IP, user agent and
path from the active request; writes are deferred via `transaction.on_commit`
inside real atomic blocks so records from rolled-back operations never
survive.

Canonical events live in `audit/constants.py` and cover the full customer and
staff journey — account lifecycle (`signup`, `customer_registered`,
`registration_failed`, `login`, `login_failed`, `logout`, `password_reset`,
`password_updated`, `profile_updated`), catalog browsing (`product_viewed`,
`category_viewed`, `search_performed`), cart (`cart_item_added`,
`cart_item_updated`, `cart_item_removed`, `cart_cleared`, `cart_add_failed`,
`cart_update_failed`), orders (`checkout_started`, `checkout_failed`,
`order_created`, `order_creation_failed`, `order_details_viewed`,
`order_confirmed`, `order_cancelled`, `order_received`), payments
(`payment_initiated`, `payment_success`, `payment_failed`,
`payment_initiation_failed`, `payment_timeout`, `payment_reversed`, `refund`,
`refund_requested`, `refund_completed`), wishlist/review/support
(`wishlist_item_added/removed/cleared`, `review_submitted`,
`support_message_submitted`), generic CRUD (`create`, `update`, `delete`,
`file_upload`, `file_delete`, `status_change`), inventory
(`inventory_low_stock`) and security/system (`security_event`,
`permission_denied`, `access_denied`, `rate_limit_exceeded`, `server_error`,
`unexpected_server_error`). Each action also carries a default category and
severity (`CATEGORY_BY_ACTION` / `SEVERITY_BY_ACTION`). Unknown actions are
coerced to `security_event` with a warning.

### Client-side events

The browser storefront authenticates against Supabase entirely client-side, so
events like signup/login/checkout are reported by the frontend to
`POST /api/audit/events` (`audit/views.py`). The endpoint:

* requires a valid Supabase JWT (`IsAuthenticated`),
* throttles to `THROTTLE_AUDIT_RATE` (default `60/minute`),
* only accepts the whitelisted event subset in
  `constants.CLIENT_EVENT_WHITELIST`, coercing everything else to
  `security_event`,
* sanitizes all payload data before persistence,
* raises an admin notification for the client-only events in
  `admin_ui.services.CLIENT_NOTIFY_ALLOW` (`signup`, `registration_failed`), and
* responds `202 {received: true, action, request_id}`.

Backend-authoritative failures (checkout/payment) are deliberately excluded from
`CLIENT_NOTIFY_ALLOW`: the API already audits `order_creation_failed` /
`payment_failed` and would otherwise notify twice.

Frontend reporting lives in `frontend/src/lib/logger.ts` (fire-and-forget,
sensitive keys redacted) and is wired into `AuthContext` (signup/login/logout,
`registration_failed`, `profile_updated`), `CheckoutPage`
(`checkout_started`, `checkout_failed`, `payment_failed`), `WishlistContext`
(wishlist events), `ProductDetailPage` (`product_viewed`), `ShopPage`
(`search_performed`, `category_viewed`), the API client (`x-request-id`
capture) and `ErrorBoundary`.

### Security events

Invalid payment-webhook signatures (`payments/views.py`) and unauthorized
M-Pesa callbacks are logged as `security_event` with `severity=critical` before
the request is rejected. These writes happen outside the transaction that the
business logic runs in, so they always persist.

## Error handling

`botique_backend/exceptions.py` wraps every API error in a safe envelope —
`{"error": {code, message, details}, "request_id"}` (plus a generic message for
unhandled exceptions, never a traceback) — and audits the failure with the
matching canonical action before responding:

| Trigger | Action |
| ------- | ------ |
| 401 | `login_failed` |
| 403 | `permission_denied` |
| 429 | `rate_limit_exceeded` (skipped for `/api/audit/*` to avoid self-throttle noise) |
| 400 on `/api/orders` | `order_creation_failed` |
| 4xx on `payments/create-intent` | `payment_initiation_failed` |
| 4xx on `payments/confirm` | `payment_failed` |
| 4xx on `cart/items` | `cart_update_failed` (PATCH) / `cart_add_failed` (POST) |
| 500 | `unexpected_server_error` |

Every one of these failures also raises an admin notification through
`AdminNotificationService.notify_for_audit`, linked to its audit row. Clients
use the `request_id` to report correlated issues.

## Admin notifications

`admin_ui/services.py` owns `AdminNotificationService`, the single writer of
admin notifications. It follows a log-first, notify-second contract:

* the `AuditLog` row is always written first (the authoritative record),
* the notification links back to it (`audit_log` FK plus denormalised
  `event_type`, `severity`, `actor`, `resource_type`, `resource_id` and
  `request_id`),
* writes are deferred with `transaction.on_commit` inside atomic blocks so a
  rolled-back operation never leaves orphan notifications,
* the method **never raises** — failures are logged on `admin_ui.notify` and
  swallowed, and
* duplicates are prevented per `(recipient, event_key)`.

Which actions notify is centralised in `AUTO_NOTIFY` (order/payment/refund/
cart-failure, account, security and system events). High-frequency browse
events (`product_viewed`, `search_performed`, `cart_item_added`,
`wishlist_*`) intentionally stay audit-only. Notifications are delivered in the
admin UI by the existing 15-second poll on `base_admin.html`, which now
re-renders the dropdown live from the unread JSON endpoint; no Channels/Redis is
involved.

DRF endpoints (staff-only) mirror the server-rendered pages:

| Route | Purpose |
| ----- | ------- |
| `GET /api/admin/notifications/` | paginated list with `unread_count` |
| `GET /api/admin/notifications/unread/` | recent unread (bell poll) |
| `PATCH /api/admin/notifications/<id>/read/` | mark one read (sets `read_at`) |
| `POST /api/admin/notifications/read-all/` | mark all read (sets `read_at`) |


## Admin Activity & Logs center

The Django admin UI exposes a staff-only Activity & Logs center built on the
same read pipeline as the audit trail (`admin_ui/audit_ui.py`). All pages are
server-rendered, gated by `StaffRequiredMixin` (anonymous → `/admin/dashboard/login/`,
authenticated non-staff → 403 Access Denied page), and read directly from the
`AuditLog` table — no extra data is stored.

| Route | Page |
| ----- | ---- |
| `/admin/dashboard/activity/` | Overview: summary cards, timeline/table views, filters (event, category, result, severity, actor, free text, date range), sorting and CSV/JSON export |
| `/admin/dashboard/activity/errors/` | Error Center: failed requests, server errors and high/critical severity events |
| `/admin/dashboard/activity/request/<request_id>/` | Request Trace: chronological audit chain for one `req_<hex>` correlation ID |
| `/admin/dashboard/security/` | Security Center: logins, failed logins, permission denials, password resets and `security_event`s |
| `/admin/dashboard/system-health/` | System Health: live read-only checks (DB, API, auth config, storage, payments) that honestly report `Unknown`/`Configured` instead of inventing numbers |
| `/admin/dashboard/customers/<int:customer_id>/` | Customer profile with that account's audit activity and order history |
| `/admin/dashboard/notifications/` | Notification center: filter by category, severity and read status; severity badges and per-item read state |

Order and product detail pages also render an "activity" card of events for the
record. The dashboard itself is limited to KPI cards plus a sales line graph;
audit activity lives in `/admin/dashboard/activity/` (and the error summary in
`/admin/dashboard/activity/errors/`).
`/admin/dashboard/audit-logs/` remains as a legacy alias of the overview.

Event metadata is sanitized server-side before display; the client drawer
additionally redacts any key matching
`password|passwd|token|secret|authoriz|bearer|api[-_]?key|cookie|jwt|credential`.

Exports reuse the exact server-side filter pipeline shown on screen (CSV or
JSON, capped at 10 000 rows, `format=csv|json`); any other format returns 400.

## Housekeeping

`python manage.py cleanup_audit_logs --days 365` deletes audit rows older than
the retention window (`AUDIT_LOG_RETENTION_DAYS`, default 365). Use
`--dry-run` to preview deletions. Run it on a schedule (e.g. a Render cron /
cron job) to keep the `audit_auditlog` table bounded.

## Environment

| Variable                  | Default             | Purpose                                        |
| ------------------------- | ------------------- | ---------------------------------------------- |
| `LOG_LEVEL`               | `INFO`              | Minimum structured log level                   |
| `LOG_FORMAT`              | `text`              | `text` or `json` console output                |
| `AUDIT_LOG_RETENTION_DAYS` | `365`              | AuditLog cleanup retention window              |
| `THROTTLE_AUDIT_RATE`     | `60/minute`         | Client audit event POST throttle               |
| `USE_X_FORWARDED_FOR`     | `False`             | Trust `X-Forwarded-For` for client IP          |