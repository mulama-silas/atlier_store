# CELERY.md — Background Imports & the Email Subsystem

Two kinds of work do not belong inside an HTTP request:

* **bulk product imports** — thousands of spreadsheet rows, image writes and
  stock mutations, capped at two hours;
* **outbound email** — an HTTPS round trip per message, with a retry ladder.

Both now run through Celery. This document is the operational runbook: what
the switches do, how to run it locally, what Render needs, and how to recover
after a restart.

---

## The switches

Everything is governed by environment variables read in
`botique_backend/settings.py`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `REDIS_URL` | *(empty)* | Broker. Render injects it automatically when a Redis resource is linked. |
| `CELERY_WORKER_ENABLED` | `true` **iff** `REDIS_URL` is set | The single switch for imports (and email, when `EMAIL_DELIVERY_MODE` is unset). `false` → the browser-driven `/process` import loop. `true` → handed to a worker. |
| `CELERY_TASK_ALWAYS_EAGER` | `true` unless a worker is enabled **and** reachable | Safety net: if `.delay()` is ever called with no worker able to drain the broker, the task runs inline instead of being stranded. |
| `EMAIL_ENABLED` | code default `true`, but **`false` in `backend/.env` *and* in the Render blueprint** | Master kill switch. `false` → `queue_email` still writes its row, but `_dispatch`, `deliver_email_log`, `requeue_email_log`, `retry_email_log` and `sweep_pending_emails` are all no-ops: no transport is touched and no row reaches `SENT`. The test runner ignores the env value and pins `true`, so the disabled path is only ever exercised through `override_settings`. |
| `EMAIL_DELIVERY_MODE` | *(empty)* → infer from `CELERY_WORKER_ENABLED` | How a queued message reaches its transport. `inline` = synchronously right after the DB commit. `deferred` = left `QUEUED` for the sweeper, so the request does no mail I/O. `worker` = `send_email_log.delay()`. |
| `EMAIL_BACKEND` | inferred from `RESEND_API_KEY` / `EMAIL_HOST` | The transport itself — see "The transport" below. |
| `EMAIL_TIMEOUT` | `10` | Seconds a transport may block before it is abandoned. |

Under the test runner (`manage.py test`) the Celery triple is forced to
`memory://` / `EAGER` / `WORKER_ENABLED=False`, `EMAIL_BACKEND` is forced to
the locmem backend so `django.core.mail.outbox` is available to every test,
and no test can open a socket. `EMAIL_DELIVERY_MODE` stays `inline` under
tests, which is why `captureOnCommitCallbacks(execute=True)` is enough to
observe a delivery.

> **Render must ship `CELERY_WORKER_ENABLED: "false"` explicitly.** Leaving it
> unset on a service that *does* have `REDIS_URL` would default it to `true`
> and route work to a worker that does not exist.

> **The mailer ships deactivated — everywhere.** `render.yaml` and the local
> `backend/.env` both set `EMAIL_ENABLED: "false"` because no sending domain
> has been verified yet. Everything about
> the subsystem — queueing, idempotency, the `/admin/dashboard/emails/`
> pages, audit rows — stays in place and keeps recording; only the hand-off
> to a transport is suppressed, and a message is never marked `SENT` for mail
> nobody attempted. The admin page shows a banner to that effect, and the
> Resend/bulk-resend buttons say so instead of pretending they worked.

### The transport

Only consulted when `EMAIL_ENABLED` is `true`.

Resolution order, first match wins (`settings.py`):

1. **`RESEND_API_KEY`** → `emails.backends.ResendEmailBackend`, `POST
   https://api.resend.com/emails` over port 443.
2. **`EMAIL_HOST`** → Django's SMTP backend.
3. neither → the console backend, which prints mail to the log.

> **Render's free plan blocks outbound SMTP on ports 25, 465 and 587**
> (changelog, 2025-09-16). A configured `EMAIL_HOST` therefore fails there
> with `OSError: [Errno 101] Network is unreachable`, and because Django's
> SMTP backend is used without a timeout by default that failure can block
> `POST /api/orders` long enough to leave checkout spinning. Port 443 is not
> blocked, which is why mail leaves through the HTTPS API instead — and why
> `EMAIL_TIMEOUT` exists even there.

---

## Queues

`CELERY_TASK_ROUTES` in `settings.py`:

| Queue | Consumes | Tasks |
| --- | --- | --- |
| `imports` | `catalog.tasks.*` | `enqueue_import_job`, `process_import_job` |
| `email` | `emails.tasks.*` | `send_email_log` |
| `default` | everything else, including the smoke test | `botique_backend.ping` |

A single worker process consumes all three:

```bash
celery -A botique_backend worker --loglevel=info --queues=default,imports,email --concurrency=2
```

### Task catalogue

| Task | Queue | Time limit | Notes |
| --- | --- | --- | --- |
| `catalog.tasks.process_import_job` | `imports` | **2 h** (task-level override of `CELERY_TASK_TIME_LIMIT`) | Drives `BulkImportExecutionService.process_chunk` in a loop; cooperative stop at product-group boundaries when the job is cancelled. Retries 3× at 30 s / 2 m / 10 m. |
| `emails.tasks.send_email_log` | `email` | 600 s | One delivery attempt; re-dispatches itself with a `countdown` for the next rung of the ladder. |
| `botique_backend.ping` | `default` | — | Smoke test: `celery -A botique_backend call botique_backend.ping`. |

---

## Delivery guarantees

**Imports.** `process_import_job` is idempotent. It re-reads the job row, and
returns immediately if the job is already `COMPLETED`, `FAILED` or
`CANCELLED`. Rows that were already imported are skipped by the `next_index`
cursor, so a redelivered task cannot double-create a product. The completion
or failure email is keyed on the job (`bulk_import_completed:import:<pk>`),
so a second delivery cannot email the operator twice.

**Email.** `EmailLog` (Postgres) owns retry state, not Celery. Render's free
Redis key value is in-memory, so a restart can lose the queued *message*; the
log survives and `requeue_stuck_emails` re-derives the work from it.

* `queue_email` de-duplicates on `idempotency_key` — a duplicated webhook,
  callback or re-entrant service call resolves to the same row and sends once.
* Delivery claims the row with an atomic
  `QUEUED/RETRYING -> SENDING` update, so a duplicate broker message, a
  worker-crash redelivery and an admin retry can never send concurrently.
* Everything is dispatched on `transaction.on_commit`, so a rolled-back order
  never produces an email and a worker never reads uncommitted state.

### Retry ladders

**Email** — `emails/constants.py`, 5 attempts total, ±20 % jitter:

| Attempt | Delay before next |
| --- | --- |
| 1 | 30 s |
| 2 | 2 m |
| 3 | 10 m |
| 4 | 30 m |
| 5 | `FAILED` |

Failure classification is authoritative on the transport's own verdict: an
exception may declare itself permanent or temporary (the HTTPS API backend
does — HTTP `401`/`403`/`400`/`422` mean the key, the sending domain or the
payload is wrong, so retrying for 40 minutes only burns the attempts). Next
comes the SMTP status code: `4xx` → temporary (retry), `5xx` → permanent
(stop now). Known permanent exception types (`BadHeaderError`,
`ValidationError`, …) win after that; anything else is treated as temporary
because the ladder is bounded anyway. Only **terminal** failures raise a
staff notification — one bell entry per failed message, not one per attempt.

**Imports** — 3 attempts at 30 s / 2 m / 10 m, then the job is marked
`FAILED` and the operator is emailed once.

---

## Local development

Three modes, all exercised by the test suite:

```bash
# 1. No Redis, no worker — the default. Everything runs inline.
python manage.py runserver

# 2. Real worker. Start Redis, then:
REDIS_URL=redis://localhost:6379/0 CELERY_WORKER_ENABLED=true python manage.py runserver
celery -A botique_backend worker --loglevel=info --queues=default,imports,email

# 3. Tests — forced eager, forced locmem mailbox.
python manage.py test emails
python manage.py test catalog

# 4. Deferred delivery, without a cron: queue only, then flush by hand.
EMAIL_DELIVERY_MODE=deferred python manage.py runserver
python manage.py requeue_stuck_emails --dry-run
python manage.py requeue_stuck_emails
```

Sanity check the broker/worker link:

```bash
celery -A botique_backend call botique_backend.ping
# -> {'ok': True, 'pong': 'pong'}
```

---

## Render

### Shipped configuration (web only)

`render.yaml` runs a single Docker web service with:

```yaml
- key: CELERY_WORKER_ENABLED
  value: "false"
- key: EMAIL_DELIVERY_MODE
  value: "deferred"
- key: EMAIL_TIMEOUT
  value: "10"
```

There is no worker, so bulk imports run in the request that confirms them
(driving the same `process_chunk` loop, with the progress page polling as
before). Email does not: `deferred` means a web request **never opens a
socket for mail**. `POST /api/orders` commits the order and the `EmailLog`
row and returns immediately.

### Delivering deferred mail

`EmailLog` rows sit in `QUEUED` until something delivers them. That
something is a management command, invoked either by hand or by an external
cron hitting the sweeper endpoint. While `EMAIL_ENABLED=false` nothing
delivers them at all and the sweeper reports all zeros — which is the
correct answer, not a failure:

```bash
python manage.py requeue_stuck_emails            # one pass
python manage.py requeue_stuck_emails --dry-run  # list without sending
```

```
POST https://<your-backend>.onrender.com/api/admin/emails/sweep
x-sweep-token: $EMAIL_SWEEP_TOKEN
```

Optional query parameters: `olderThan` (default `45`) and `limit` (default
`10`).

The endpoint carries no Django or Supabase authentication — a cron has no
session — so it requires `EMAIL_SWEEP_TOKEN` and **returns 404 when that
variable is unset**, i.e. an unconfigured deployment does not advertise a
POST route at all. Rejections are audit-logged as `security_event`.

**Render Cron jobs are a paid service type** ($1/month minimum), so the
recommended scheduler is a free external one — cron-job.org, UptimeRobot or
similar — configured as:

| Field | Value |
| --- | --- |
| URL | `https://<your-backend>.onrender.com/api/admin/emails/sweep` |
| Method | `POST` |
| Header | `x-sweep-token: <EMAIL_SWEEP_TOKEN>` |
| Schedule | every minute |

> **Order of operations.** Set `RESEND_API_KEY` and confirm a message
> actually delivers *before* relying on `deferred`, and create the cron
> before flipping `EMAIL_DELIVERY_MODE` to `deferred`. Between the two, rows
> simply accumulate and are flushed the moment the cron lands.

The admin **Resend** button and `requeue_stuck_emails` always attempt
delivery inline regardless of mode — they are explicit operator actions and
the person clicking them wants the result now.

### Enabling the worker

Render's free tier rejects `type: worker` with `plan: free`, so the worker
block ships **commented out** at the bottom of `render.yaml`. To turn it on:

1. Upgrade to a paid plan — a worker costs the price of one Starter instance.
2. Uncomment the `type: worker` block in `render.yaml`.
3. Set `CELERY_WORKER_ENABLED: "true"` on the **web** service as well, so it
   starts publishing to Redis instead of running inline.
4. Point the worker's `REDIS_URL` at the same Redis resource the web service
   uses (`fromService: type: redis`), and copy across the remaining env vars —
   the worker imports Django models, templates and settings.

Both services must share one `REDIS_URL`; two different brokers means the web
service queues work nobody consumes.

### Required env vars

| Name | Where | Notes |
| --- | --- | --- |
| `REDIS_URL` | injected by Render when Redis is linked | Do **not** declare it manually in `render.yaml`. |
| `CELERY_WORKER_ENABLED` | web service | `"false"` while there is no worker. |
| `CELERY_VISIBILITY_TIMEOUT` | both, optional | Default `7500` s. Must exceed the 2 h import limit or Redis redelivers a running job to a second worker. |
| `CELERY_TASK_TIME_LIMIT` | worker, optional | Default `3600` s — the *fallback* limit. `process_import_job` overrides it to 2 h and `send_email_log` to 600 s. |
| `EMAIL_ENABLED` | web service | `"false"` in the shipped blueprint — the kill switch. |
| `RESEND_API_KEY` | web service | **Required for mail on Render.** `sync: false` in `render.yaml`; unset means SMTP, which the free plan blocks. |
| `EMAIL_SWEEP_TOKEN` | web service | **Required for mail when `EMAIL_DELIVERY_MODE=deferred`.** `sync: false`; unset disables the sweeper endpoint (404). |
| `EMAIL_DELIVERY_MODE` | web service | `"deferred"` in the shipped blueprint. |
| `EMAIL_TIMEOUT` | web service | `"10"` — bounds every transport attempt. |
| `SERVER_EMAIL` | web service | Where admin alerts (failed imports, critical errors) land. Defaults to `DEFAULT_FROM_EMAIL`. |
| `STORE_EMAIL` | web service | `hello@modeza.co.ke` — the single ops inbox every admin email type is addressed to. |

---

## Recovering after a restart

Render's free Redis is in-memory. A restart drops queued messages; the
database rows survive. Two management commands rebuild the work:

```bash
# Bulk imports that were mid-flight when the process died.
python manage.py requeue_stuck_imports --dry-run
python manage.py requeue_stuck_imports --older-than 600

# Emails stuck in QUEUED (or RETRYING whose next_retry_at has passed).
python manage.py requeue_stuck_emails --dry-run
python manage.py requeue_stuck_emails --older-than 45
```

`--dry-run` lists what would be requeued without dispatching anything.
`--older-than` is in seconds and only considers rows that have been waiting at
least that long, so a restart does not fight in-flight work.

Neither command is needed when a worker is healthy — it is a **post-restart**
ritual for the free-tier setup. In deferred mode the same code path is what
the sweeper endpoint runs on every cron tick.

---

## Limitations / next phase

* **No worker on the free plan.** Long imports occupy a web worker for their
  duration; on a single-instance free service that can block other requests.
  Moving the import loop onto a paid worker is the single biggest win.
* **Retries are scheduled by the external cron, not by beat.** The ladder is
  driven by a `countdown` message in worker mode and otherwise by the next
  sweep of `requeue_stuck_emails`. Delete the cron and retries stop with it,
  leaving rows in `RETRYING` indefinitely — which is exactly the state the
  production incident started from.
* **No fan-out for admin alerts.** Every admin email type goes to the single
  `STORE_EMAIL` inbox; the in-app `notify_staff` channel is what fans out to
  individual staff accounts.
* **`EmailLog.attachments` stores storage keys, not base64.** A log whose
  attachment file has been pruned from storage sends without it (the failure
  is logged, not fatal).
* **No dead-letter queue.** Terminal failures are visible on
  `/admin/dashboard/emails/?status=failed` and as a staff notification;
  re-sending is an explicit staff action.
