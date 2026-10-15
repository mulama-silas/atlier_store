# MODEZA Boutique — Commerce Storefront

Full-stack fashion boutique: **Django** REST API + admin (deployed to **Render**)
backed by **Postgres**, and a **React/Vite** storefront (deployed to **Vercel** as a
static SPA). Supabase provides membership/auth + database for your external IDs.

```
Browser ──▶ Vercel (Vite SPA, /assets)
              │  VITE_API_BASE_URL ──▶ Render (Django /api/*)
              │  VITE_SUPABASE_URL ──▶ Supabase (auth, account data)
              └  MPesa callback ─────▶ Render /api/payments/mpesa/callback
```

## Local development

**Backend (Django, port 8000)**
```bash
cd backend
python -m venv ../.venv
# activate venv, then:
pip install -r requirements.txt
cp .env.example .env          # fill in Supabase / payment keys
python manage.py migrate
python manage.py runserver    # http://127.0.0.1:8000
```

**Frontend (Vite + Express dev server, port 3000)**
```bash
cd frontend
npm install
cp .env.example .env.local    # VITE_API_BASE_URL=http://127.0.0.1:8000, VITE_ADMIN_URL=...
npm run dev                   # http://localhost:3000
npm run lint && npm run build # typecheck + production build
npm run test:api              # bundled API integration tests
```

## Deploy the backend to Render

1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, select the repo (or *New → Web Service → Docker*,
   root directory `backend`). A `render.yaml` blueprint is included and deploys the
   `backend/Dockerfile` automatically.
3. Set environment variables in the dashboard (see `.env.example`):
   - `DJANGO_SECRET_KEY`, `DATABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_JWT_ISSUER`,
     `PAYMENT_WEBHOOK_SECRET`, `MPESA_CALLBACK_SECRET`, MPesa Daraja creds, `MPESA_CALLBACK_URL`.
   - `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS=<app.onrender.com>`,
     `DJANGO_SECURE_SSL_REDIRECT=True`, `FRONTEND_ORIGIN=<vercel-url>`.
   - Observability: `LOG_FORMAT=json`, `LOG_LEVEL=INFO`,
     `AUDIT_LOG_RETENTION_DAYS=365`, `USE_X_FORWARDED_FOR=True`, and an optional
     `THROTTLE_AUDIT_RATE` for the client audit-event endpoint.
   - Background work: `CELERY_WORKER_ENABLED=false` (the free plan cannot run a
      worker, so bulk imports run inline in the web process) and
      `EMAIL_DELIVERY_MODE=deferred` (email does **not** run inline — see below).
      Link a managed **Redis** resource to get `REDIS_URL` injected — see
      `backend/docs/CELERY.md` for how to switch the worker on later.
   - Outbound email: **currently deactivated** — `EMAIL_ENABLED=false` (the
      blueprint default). The mailer is still installed and still records
      every message in `/admin/dashboard/emails/`, but nothing is sent and
      nothing reaches `SENT`. It is off because there is no custom domain yet
      for Resend to verify. To switch it on: register a domain, verify it at
      resend.com, set `RESEND_API_KEY` + `EMAIL_ENABLED=true`, and point
      `DEFAULT_FROM_EMAIL` / `SERVER_EMAIL` at that domain. Remember
      Render's free plan blocks outbound SMTP (ports 25/465/587), so mail
      leaves through the Resend HTTPS API on port 443.
   - Add a managed **Postgres** database and paste its connection string into `DATABASE_URL`.
4. Migrations now run automatically on every container start (`python manage.py migrate
   --noinput` in the Dockerfile), so the schema is applied as soon as the first deploy
   boots. To apply them manually (e.g. for a one-off):

   ```bash
   DATABASE_URL="postgres://..." python manage.py migrate
   ```
5. Health check `GET /api/health/` should answer 200. Static admin assets are served by
   WhiteNoise (already `collectstatic`'d in the image).

## Admin login after deploy

The deployed admin (`https://<backend>.onrender.com/admin/dashboard/login/`, plus the
Django admin at `/admin/`) reads from the **production** database, not your local
`db.sqlite3`. A superuser created locally will never appear there.

1. Open the Render dashboard → your `boutique-backend` service → **Shell**.
2. Create the admin user against the production DB — either interactively:

   ```bash
   python manage.py createsuperuser
   ```

   or non-interactively from env vars set in the Render dashboard
   (`DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`):

   ```bash
   python manage.py ensure_superuser   # command is idempotent; re-runs also reset the password
   ```

   (You can also run either command locally with `DATABASE_URL` set to the production
   connection string — just never rely on the local SQLite admin users for production.)
3. Sign in at `https://<backend>.onrender.com/admin/dashboard/login/`.

Tests/customers explained: customers authenticate entirely through **Supabase Auth**
(`auth.users`), so a working sign-up always lives in the Supabase dashboard under
*Authentication → Users* for project `ngpzjddvkgopfmghjqnv`. Django only creates a
matching `auth_user` (username `supabase_<uuid>`) the first time that customer calls an
authenticated API endpoint (`GET /api/auth/me`), which is also where the admin
"Customers" page gets its rows.

## Deploy the frontend to Vercel

1. In Vercel: **Import Project →** repo, framework preset **Vite**, root `frontend`.
2. `vercel.json` (already present) forces `vite build`, output `dist`, and rewrites
   client-side routes to `index.html`.
3. Set project environment variables (`VITE_*` are baked into the bundle at build time):
   - `VITE_API_BASE_URL=https://<backend>.onrender.com`
   - `VITE_ADMIN_URL=https://<backend>.onrender.com/admin/dashboard/`
   - `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (public keys only).
4. Add the Vercel URL to the backend's `FRONTEND_ORIGIN` (CORS) and `DJANGO_ALLOWED_HOSTS`.

## Post-deploy checklist

- [ ] `GET https://<backend>/api/health/` returns 200.
- [ ] Superuser created via the Render Shell (`python manage.py ensure_superuser`) and
      `https://<backend>/admin/dashboard/login/` accepts it.
- [ ] `https://<frontend>/#/` serves the SPA and deep links (e.g. `/product/…`) refresh correctly.
- [ ] Guest adds to cart → signs in → checkout prefill shows account data.
- [ ] `https://<backend>/admin/dashboard/audit-logs/` lists orders, payments,
      logins and security events; `POST https://<backend>/api/audit/events`
      returns 202 for storefront events.
- [ ] Prepaid checkout remains pending until a verified M-Pesa provider flow is
      integrated. `PAYMENT_SANDBOX=true` is for local development only;
      production (`DEBUG=false`) rejects that setting. Render sets it to false.
- [ ] CORS: frontend origin is in `FRONTEND_ORIGIN`; cookie-flags work over HTTPS.
- [ ] `https://<backend>/admin/dashboard/emails/` loads and a test order produces a
      row there. Delivery is off (`EMAIL_ENABLED=false`), so rows stay `QUEUED`
      and the page carries the deactivation banner — that is the expected state
      until a sending domain exists.
- [ ] Sweeper endpoint answers `POST https://<backend>/api/admin/emails/sweep`
      with `x-sweep-token` and returns 401 when the token is wrong.
- [ ] (If the replica is enabled) `/admin/dashboard/replica/` loads, the first
      `manage.py sync_replica` reconciles, and the anon key cannot read
      `replica.*` from the Supabase SQL editor.

## Background work (bulk imports & email)

Bulk product imports and outbound email are driven by Celery, but the
deployment ships **without a worker**: `render.yaml` sets
`CELERY_WORKER_ENABLED=false`, so imports run inline in the web process with
byte-for-byte the same retry, idempotency and audit behaviour. Local
development needs no Redis either — `python manage.py runserver` is enough.

Email is **currently deactivated** (`EMAIL_ENABLED=false`). Nothing touches a
transport: checkout still writes an `EmailLog` row, so the admin email page
shows exactly what would have gone out, but no row ever reaches `SENT` and no
retry loop runs. Set `EMAIL_ENABLED=true` to re-arm it, which also requires
`EMAIL_DELIVERY_MODE=deferred` — a mode in which a web request never opens a
socket for mail and rows are delivered by `POST /api/admin/emails/sweep`,
guarded by `EMAIL_SWEEP_TOKEN` and called once a minute by a **free external
cron** (cron-job.org — Render's own cron jobs are a paid service type).

After a restart on the free plan (its Redis is in-memory) rebuild any lost work:

```bash
python manage.py requeue_stuck_imports --dry-run
python manage.py requeue_stuck_emails   --dry-run
```

Full runbook — switches, queues, retry ladders, the sweeper endpoint, and how
to enable the worker on a paid plan — is in `backend/docs/CELERY.md`.

## Admin recovery (no Render Shell on free)

The free plan has no shell, so `createsuperuser` cannot be run by hand. The
Dockerfile therefore runs `ensure_superuser --noinput` on **every container
start**, alongside `migrate`:

```
python manage.py migrate --noinput && (echo y | python manage.py ensure_superuser --noinput || true) && gunicorn ...
```

Set `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` in Render (all three
are already declared in `render.yaml`). The command is idempotent and re-promotes
the account on every boot, so a lost superuser is recoverable by redeploying.

## Resetting demo data

A one-shot cleanup for the moment before real customers arrive, when every order,
payment and receipt is test-generated.

Gated on `ENABLE_DATA_RESET`. While it is off - the default, and what
`render.yaml` ships - the page answers **404**, the nav link is hidden, and
`manage.py reset_demo_data` refuses to run. Handover to a client is therefore a
config change, not a code deletion.

```bash
ENABLE_DATA_RESET=true python manage.py reset_demo_data --dry-run   # preview
ENABLE_DATA_RESET=true python manage.py reset_demo_data --force     # execute
```

Or from the admin: set the variable, redeploy, then use
`/admin/dashboard/reset-data/`. That page shows a **live per-table count** of
what will be deleted and what will be kept, before offering the confirming POST,
which additionally requires the superuser and typing `WIPE`.

**Kept:** `auth_user` (admin + staff), `auth_permission`, `auth_group`,
`access_control.Permission` / `Role`, `django_content_type`,
`django_migrations`, `django_session`.

**Deletion order matters.** `PaymentIntent->order`,
`PromotionRedemption->promotion`/`->order`, `StockReservation->variant`,
`InventoryTransaction->variant` and `Product->category` all use
`on_delete=PROTECT`, so a naive cascade raises `ProtectedError` partway through.
Children are deleted first, inside a single transaction, so a failure rolls back
and leaves the database untouched.

> Do **not** use `manage.py flush` for this. It truncates every table including
> `auth_user`, which would delete the admin accounts this reset exists to
> preserve.

Wipe **before** the first replica sync, so the initial backfill and the snapshot
history start clean.

This does not touch Supabase: `auth.users` still holds the test signups (and
Django recreates their shadow rows on next login), and the `product-images`
bucket still holds the files. Both need a manual pass before handover.

## Backup to Supabase (analytics replica)

Supabase holds a **read-only analytics copy** of the Django database, plus a
mirror of the product-image bucket. It is **not** a disaster-recovery target —
Django cannot be repointed at it.

Because the project is on the **Free plan, Supabase takes no automatic backups
at all** (Pro/Team/Enterprise get daily backups automatically), so this job
*is* the backup. RPO equals the cron interval.

### One-time setup

1. **Schema** — Supabase → SQL Editor → run `supabase/replica_schema.sql`.
   Creates the `replica` schema. It is deliberately **not** added to
   `db-schemas`, so the anon key in the public storefront bundle cannot read it;
   every table also has RLS enabled with no policies.
2. **Destination bucket** — Storage → New bucket →
   `product-images-backup`, set to **private**. A backup copy that is publicly
   served is not a backup.
   ⚠️ Mirroring doubles bucket usage; check Storage → Usage against your quota
   first. If it does not fit, point the mirror at external S3 instead —
   `replica/services/storage_mirror.py` is the only file that changes.
3. **Profiles hardening** (optional, unrelated to backups) — run
   `frontend/supabase/migrations/202610130001_profiles_hardening.sql`, then the
   commented backfill at the bottom. Creates a `profiles` row for every signup
   and closes a `role` escalation (RLS cannot restrict columns; that needs
   `REVOKE`/`GRANT`).
4. **Backend secrets** (Render → Settings → Environment), then redeploy:
   - `SUPABASE_DB_URL` — the *direct Postgres* URI from Supabase → Project
     Settings → Database. Not the PostgREST URL.
   - `REPLICA_SYNC_TOKEN` — long random string.
   - `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` — the only admin
     recovery path on the free plan (see *Admin recovery* above).

### Running it

```bash
python manage.py sync_replica --status                  # read-only
python manage.py sync_replica --triggered-by first      # first full backfill
python manage.py sync_replica --skip-storage            # relational only
python manage.py sync_replica --storage-limit 5         # trial the mirror
```

The first run backfills everything at once — it is a full refresh, not an
incremental sync. Admin status page: `/admin/dashboard/replica/`
(`replica.view` to view, `replica.sync` to run).

### Scheduling it

The page is the control panel; the cron is the alarm clock. Neither replaces
the other - a button nobody presses is not a backup policy, and a silent cron
failure goes unnoticed for weeks.

Create a free job at **cron-job.org** hitting:

```
POST https://<backend>/api/admin/replica/sync?skipStorage=true
x-replica-token: <REPLICA_SYNC_TOKEN>
```

Run it nightly; add `skipStorage=true` if images change rarely, and drop the
flag on a schedule of its own when they do. While `REPLICA_SYNC_TOKEN` is unset
the endpoint answers **404** rather than existing unauthenticated. If a run is
already in progress it answers **409** with `skipped: true` - that is expected
when a tick lands during a manual run, not a failure.

### Concurrency and long runs

Two things protect a sync from itself:

- **Advisory lock** - `pg_try_advisory_lock` on the working connection, released
  when it closes. A second sync is refused rather than interleaved with the
  first. This is what stops the dangerous case where the admin button times out,
  the operator retries, and a second full sync starts alongside the first.
- **`REPLICA_SYNC_MODE`** - `inline` runs the sync inside the button's request;
  `deferred` only queues a run and returns immediately, leaving the cron to do
  the work. `deferred` is the safe choice on a free instance, where a long sync
  can outrun the proxy timeout. `render.yaml` ships `deferred`.

Each table commits in its own transaction, so a failure rolls that table back
rather than leaving it half-written, and Django/Supabase row counts are
reconciled - a mismatch fails the run loudly.

### What it replicates

Catalogue, variants, orders, order items, payment intents, inventory
transactions and reservations, promotions and redemptions, receipts, plus a
derived `replica.customers` aggregate. Skipped: `auth_user` (password hashes —
customer identity joins from `public.profiles` instead), sessions, migrations,
assistant conversations, email logs.

`replica.orders.customer` carries shipping name/phone/address. That PII is
unavoidable for sales reporting and needs a retention decision.

Each run also appends to `replica.catalogue_snapshots`, giving
*"what did the catalogue look like on date X?"*:

```sql
select entity_id, payload from replica.catalogue_snapshots
where entity = 'product' and snapshot_date = '2026-10-01';
```

Writes are **upsert, never truncate** (truncating would destroy that history),
each table commits in its own transaction so a failure rolls back rather than
leaving a half-empty replica, and Django/Supabase row counts are reconciled -
a mismatch fails the run loudly.

## Observability (logging & audit)

Every request carries a `X-Request-ID` (echoed in responses) that is attached to
structured log lines and audit records. `AuditLogService` centralizes audit writes
with sanitization, an admin **Activity Logs** page at `/admin/dashboard/audit-logs/`,
and `python manage.py cleanup_audit_logs --days N` for retention. The browser reports
storefront events (signup/login/checkout/…) to the throttled, authenticated
`POST /api/audit/events` endpoint. See `backend/docs/LOGGING.md` for the full details.
