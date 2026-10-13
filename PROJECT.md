# MODEZA Boutique — Project Documentation

Full-stack fashion e-commerce store targeting the **Kenyan market** (currency: **KES**, payments via **M-Pesa**).

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Directory Structure](#directory-structure)
- [Features](#features)
- [Frontend](#frontend)
- [Backend (Django)](#backend-django)
- [Promotions & Discounts Engine](#promotions--discounts-engine)
- [AI Shopping Assistant](#ai-shopping-assistant)
- [API Endpoints](#api-endpoints)
- [Database & Auth](#database--auth)
- [Payments (M-Pesa)](#payments-mpesa)
- [Environment Variables](#environment-variables)
- [Local Development](#local-development)
- [Deployment](#deployment)
- [Observability & Security](#observability--security)
- [Documentation Index](#documentation-index)

---

## Architecture

```
Browser ──▶ Vercel (Vite SPA, /assets)
             │ VITE_API_BASE_URL ──▶ Render (Django /api/*)
             │ VITE_SUPABASE_URL ──▶ Supabase (auth, account data)
             └ MPesa callback ────▶ Render /api/payments/mpesa/callback
```

| Layer | Service | Role |
|---|---|---|
| Frontend | **Vercel** | React SPA served as static assets |
| Backend API | **Render** (Docker) | Django REST Framework, `/api/*` |
| Auth + DB | **Supabase** | Auth (JWT) + PostgreSQL |
| Payments | **M-Pesa Daraja API** | STK Push; `PAYMENT_SANDBOX` completes intents in-process |
| Email | **Resend** (HTTPS API, port 443) | Outbound mail; SMTP is blocked on Render's free plan |

---

## Tech Stack

### Frontend
- **React 19** + **TypeScript** SPA
- **Vite 6** build tool
- **Tailwind CSS 4** (`@tailwindcss/vite` plugin) — warm boutique palette (`#FAF9F6` bg, `#181716` text)
- **motion** (Framer Motion successor) for page transitions
- **lucide-react** icons
- **@supabase/supabase-js** for auth
- **zod** for schema validation
- Custom hash-aware router (no React Router)
- React Context for state (no Redux/Zustand)
- Express/TypeScript API prototype bundled with the frontend (`src/server/`)

### Backend
- **Django 6** + **Django REST Framework**
- **PyJWT** for Supabase JWT verification
- **reportlab** for PDF receipts
- **openpyxl** for Excel product imports
- **gunicorn** + **whitenoise** for serving
- **psycopg2-binary** / **dj-database-url** for Postgres

### Infrastructure
- Docker (Python 3.12-slim) for backend
- `render.yaml` Blueprint for Render deployment
- `vercel.json` for SPA routing on Vercel
- k6 for load testing

---

## Directory Structure

```
boutique-fashion-store/
├── README.md                      # Deployment runbook
├── PROJECT.md                     # This file
├── .env.example                   # Master env template
├── render.yaml                    # Render Blueprint
├── questionnaire-answers.md       # Feature-state audit
├── load-test-info.md              # k6 load-testing guide & API contracts
├── supabase/                      # setup.sql, cleanup.sql
├── backend/                       # Django project
│   ├── manage.py, Dockerfile, requirements.txt, .env.example
│   ├── botique_backend/           # settings, urls, middleware, logging
│   ├── accounts/                  # Supabase JWT auth, /api/auth/me
│   ├── catalog/                   # products, categories, variants
│   ├── cart/                      # guest carts (x-cart-id header)
│   ├── orders/                    # checkout, order lifecycle
│   ├── payments/                  # M-Pesa create-intent/confirm/webhook
│   ├── inventory/                 # stock + reservations ledger
│   ├── receipts/                  # PDF/email receipts
│   ├── emails/                    # central outbound mailer (EmailLog + retries)
│   ├── audit/                     # audit log + /api/audit/events
│   ├── access_control/            # roles: customer/staff/admin
│   ├── admin_ui/                  # server-rendered admin dashboard
│   ├── admin_api/                 # staff REST endpoints
│   ├── store/                     # /api/health/
│   ├── ai/                        # Gemini assistant (/api/ai/health, /api/ai/chat)
│   └── docs/                      # LOGGING.md, ADMIN_VARIANTS.md, CELERY.md, AI_ASSISTANT.md
└── frontend/                      # React + Vite storefront
    ├── package.json, server.ts, vite.config.ts, vercel.json
    ├── src/
    │   ├── pages/                 # storefront + account pages
    │   ├── components/            # ui/, orders/, variant/, account/
    │   ├── context/               # Store, Auth, Cart, Orders, Wishlist…
    │   ├── router/                # custom RouterContext
    │   ├── services/              # apiClient, supabaseClient
    │   ├── server/                # Express API prototype (routes/, db/)
    │   └── types/, lib/, data/, utils/
    ├── supabase/migrations/       # schema, wishlist, RLS policies
    └── dist/                      # build output
```

---

## Features

### Storefront pages
| Page | Route | Notes |
|---|---|---|
| Home | `/` | Landing |
| Shop | `/shop` | Category, collection, occasion, filter, sort, search, sale |
| Product Detail | `/product/:slug` | Variant/color pickers, quick view |
| Cart | `/cart` | Drawer + page, localStorage persistence |
| Checkout | `/checkout` | M-Pesa payment flow |
| Order Success | `/order/success` | Confirmation |
| Order Tracking | `/track` | Status + progress |
| Wishlist | `/wishlist` | Saved items |
| Recently Viewed | `/recently-viewed` | History |
| About / Legal | `/about`, legal pages | Privacy, terms, shipping, returns, cookies |
| Account | `/account/*` | Overview, Orders, Notifications, Profile, Addresses, Security |

### Core components
- Navbar, Footer, CartDrawer, SearchModal, QuickViewModal
- ProductCard, ProductGrid, ErrorBoundary
- Order widgets: OrderStatusPill, OrderProgress, OrderItemThumb
- Variant pickers: VariantSelector, ColorSwatches
- UI kit (`components/ui/`): Button, Input, Select, Modal, Badge, Toast, Price, QuantitySelector, Loading/Error/EmptyState

### Admin dashboard (server-rendered, `admin_ui/`)
- Staff login, KPIs, dashboard
- Product / category / variant management (size-matrix bulk creation, SKU generation)
- Stock adjustments, Excel product import
- Order detail, customer detail, notifications center
- Activity / Error / Security / System-Health centers, request trace
- CSV / JSON exports

---

## Frontend

### Scripts (`frontend/package.json`)

| Script | Command | Purpose |
|---|---|---|
| `npm run dev` | `tsx server.ts` | Dev server (Express + Vite middleware) on port 3000 |
| `npm run build` | `vite build && esbuild server.ts …` | Production bundle → `dist/` |
| `npm start` | `node dist/server.cjs` | Serve production build |
| `npm run preview` | `vite preview` | Preview built SPA |
| `npm run lint` | `tsc --noEmit` | Typecheck |
| `npm run test:api` | `tsx src/server/tests/run-tests.ts` | API integration tests |

### State management
React Contexts: `Store`, `Auth`, `Orders`, `Wishlist`, `Cart`, `Notifications`. Guest cart ID persists in `localStorage` under `modeza_server_cart_id`.

### Routing
Custom hash-aware `RouterContext` — no React Router dependency.

### Express API prototype
`frontend/src/server/` contains a local Express/TypeScript API (routes, services, schemas, middleware, db) that mirrors the Django `/api` contract for local development and testing. The Django backend is the source of truth in production.

> **Note:** `@google/genai` is declared in `package.json` but not referenced anywhere in `src/`.

---

## Backend (Django)

### Apps

| App | Responsibility |
|---|---|
| `catalog` | Products, categories, variants |
| `cart` | Guest carts via `x-cart-id` header (+ persisted `coupon_code`) |
| `orders` | Checkout, order lifecycle (server-side promo totals, snapshot) |
| `payments` | M-Pesa create-intent / confirm / webhook / callback |
| `promotions` | Promotion rules, coupon validation, pricing engine, redemptions |
| `inventory` | Stock levels + reservations ledger |
| `accounts` | Supabase JWT auth, `/api/auth/me` |
| `receipts` | PDF/email receipts (reportlab; includes promotion lines) |
| `audit` | Audit log, client `/api/audit/events` |
| `access_control` | Roles: customer / staff / admin (+ `promotions.*` permissions) |
| `admin_ui` | Custom server-rendered dashboard (incl. Promotions pages) |
| `admin_api` | Staff REST endpoints (products, inventory, notifications, maintenance) |
| `assistant` | AI shopping assistant: Gemini chat, tools, SSE streaming, analytics |
| `store` | `/api/health/` health check |

---

## Promotions & Discounts Engine

Django (`promotions/`) is the single source of truth for eligibility,
discount math, coupon validation, usage limits, redemption and order totals.
The React storefront only requests, displays and submits promotion data.

### Promotion types
| Type | Behaviour |
|---|---|
| `percentage` | % off eligible subtotal, optional `maximum_discount` cap |
| `fixed` | Fixed KES off eligible subtotal, never below zero |
| `free_shipping` | Removes the shipping charge (most visible on express) |
| `buy_x_get_y` | Cheapest `reward_quantity` units free per qualifying group |
| `buy_x_get_pct` | `reward_discount_percent` off the cheapest reward units |
| Automatic | `is_automatic=true` promos apply without a coupon code |

### Calculation rules
- Money in minor units (KES cents); percentages are `Decimal(0–100)`.
- Targeting: whole store, products, variants, categories, sale-only, new-only.
- Customer scope: `all` / `new` (0 prior orders; guests count as new) /
  `existing` / `specific` (allow-list). Verified server-side.
- Coupon codes are case-insensitive, whitespace-normalized, unique across
  non-disabled/expired promotions.
- Tax (16%) applies to `subtotal − discount`; shipping follows the existing
  `orders.services` rules, then free-shipping promos zero it.
- Usage limits count immutable `PromotionRedemption` rows (voided on order
  cancel); `select_for_update()` serializes concurrent redemptions.

### Stacking & priority (deterministic)
1. Collect eligible promotions. 2. Sort by `(-priority, name, pk)`.
3. If any eligible promo is non-stackable, only the top-priority one applies
   (coupon promos win exact ties when a coupon was supplied).
4. Otherwise all eligible stackable promos apply, capped at the subtotal.

### Redemption rules
- `POST /api/promotions/apply` persists `Cart.coupon_code`; checkout
  (`POST /api/orders` with `couponCode`) re-resolves everything server-side.
- Orders freeze `discount_minor`, `shipping_discount_minor`, `coupon_code`
  and a `promotion_snapshot` so history survives later promo edits.
- `PaymentIntent.amount_minor` always equals the server-side order total.

### API endpoints
```
POST   /api/promotions/apply          # {code, shippingMethod?}
POST   /api/promotions/remove         # {}
GET    /api/promotions/available      # pricing + public discovery badges
GET    /api/admin/promotions          # list + status counts
POST   /api/admin/promotions          # create
GET    /api/admin/promotions/<id>     # detail
PATCH  /api/admin/promotions/<id>     # update
DELETE /api/admin/promotions/<id>     # delete
POST   /api/admin/promotions/<id>/activate|deactivate|duplicate
GET    /api/admin/promotions/<id>/analytics
POST   /api/admin/promotions/<id>/preview   # {exampleCart} -> {discount, final}
```
Dashboard pages: `/admin/dashboard/promotions/`, `.../new/`,
`.../<id>/edit/`, `.../<id>/activate|deactivate|duplicate/`.

### Admin workflow
Promotions page → Add Promotion (Basic → Discount → Eligibility → Coupon &
customers → Schedule & limits → Behavior) → preview via API → activate.
Usage analytics per promotion: redemptions, revenue, discount given, AOV.

### Audit / RBAC / notifications
- Audit: `promotion_created/updated/activated/deactivated/deleted/`
  `code_changed/redeemed/redemption_failed/usage_limit_reached`.
- Permissions: `promotions.view/create/update/delete` (+ `promotion_manager` role).
- Customer in-app notes on redemption/coupon issue; promo emails use the
  central `emails` mailer (`promotion_announcement`, `promotion_ending_soon`,
  `coupon_issued`) and require explicit consent; `EMAIL_ENABLED=false` still
  only records rows.

---

## AI Shopping Assistant

A production-ready shopping assistant: **React widget → Django → Google Gemini**
(Gemini is called **only** server-side). `GEMINI_API_KEY` lives in `backend/.env`
(or the Render secret of the same name), is read by Django settings, and never
appears in an API response — there is deliberately no `VITE_GEMINI_*` variable.

### Flow
1. `frontend/src/components/assistant/AssistantWidget.tsx` POSTs to
   `/api/assistant/chat` (Supabase JWT + `x-cart-id` headers) and reads the SSE
   reply with `fetch` + `ReadableStream` (`frontend/src/services/assistantClient.ts`).
2. `assistant/conversation.py` persists the turn (resumable per-customer /
   per-guest-session conversations) and builds the system prompt
   (`assistant/constants.py`).
3. `assistant/services/gemini.py` calls the Gemini **Interactions API** via the
   `google-genai` SDK with streaming, retries with backoff, and a round limit
   (`ASSISTANT_MAX_TOOL_ROUNDS`; the final round forces a plain-text answer).
4. Tools run against the real database — the same catalog, promotions, orders
   and policy data the storefront uses.
5. Tool calls, messages and insights are stored for auditing + admin analytics.

### Tools (10)
| Tool | Backed by / notes |
|---|---|
| `search_products`, `compare_products`, `check_variant_availability` | `catalog`; stock exposed only as `available` / `lowStock`, never exact quantities |
| `get_active_promotions` | `promotions`; coupon codes hidden (badge + `AVAILABLE_AT_CHECKOUT`, mirrors `/api/promotions/available`) |
| `validate_promotion_code` | server-side eligibility check without redeeming |
| `get_order_status`, `get_customer_orders` | `orders`; ownership = signed-in user match **or** caller's `x-cart-id`; only `order_number` is exposed, internal UUIDs never leave the server |
| `get_store_policy` | shipping, returns, payments, sizing, contact (port of `LegalPage`) |
| `prepare_add_to_cart` | returns an action payload; the widget performs the actual add through the normal cart API |
| `create_support_request` | escalates to support; PIN/password-like strings redacted before persistence (`actions.py`) |

### Streaming protocol (SSE)
```
meta{conversationId,userMessageId}
  → tool{name,status,durationMs}*
  → delta{text}*
  → products{...}*
  → action*
  → done{messageId,conversationId,latencyMs,usage,unanswered,toolCount}
  | error{code,message}
```
`"stream": false` returns the same events as a single JSON response.

### Safety & limits
- Rate limits **15/min anonymous (IP)** and **30/min signed-in**
  (`THROTTLE_ASSISTANT_ANON_RATE` / `THROTTLE_ASSISTANT_USER_RATE`);
  `LOAD_TEST_MODE` raises them like the other scopes.
- `[[UNANSWERED]]` marker → the reply is flagged for human follow-up instead
  of fabricating an answer (`unanswered` in `done` + `AssistantInsight`).
- Transient Gemini failures retried with backoff (`GEMINI_MAX_RETRIES`,
  `GEMINI_RETRY_BACKOFF_SECONDS`); per-request timeout `GEMINI_TIMEOUT_SECONDS`.
- Conversations kept `ASSISTANT_RETENTION_DAYS` (default 90) — purge with
  `python manage.py purge_assistant_conversations --older-than 90 [--dry-run]`.
- Audit actions: `assistant_conversation_started`, `assistant_message_sent`,
  `assistant_tool_called`, `assistant_tool_failed`, `assistant_product_recommended`,
  `assistant_order_lookup`, `assistant_escalated`, `assistant_error`.

### Admin analytics
Dashboard → Analytics → **Assistant** (`/admin/dashboard/assistant/`, gated on
`reports.view`): message volume, tool usage, unanswered rate, top unanswered
questions.

### Widget
Floating launcher on every storefront page: welcome message + suggested
questions, streaming replies, product cards → `/product/<slug>`, "Add to bag"
chips (existing cart flow), live tool indicator, error + retry, conversation
history restored for returning visitors, `Trash2` starts a fresh conversation.

---

## API Endpoints

### Public / storefront
```
GET    /api/products/                  # list (filter/sort/search)
GET    /api/products/<slug|uuid>/      # detail
GET    /api/categories/
GET    /api/cart                       # get cart (x-cart-id; includes discount/promotion)
POST   /api/cart/items                 # add item
POST   /api/promotions/apply           # apply coupon {code}
POST   /api/promotions/remove          # remove coupon
GET    /api/promotions/available       # pricing + discovery badges
POST   /api/orders                     # checkout (accepts couponCode; server re-prices)
POST   /api/payments/create-intent     # start payment (amount = server total)
POST   /api/payments/confirm           # confirm payment
POST   /api/payments/webhook           # provider webhook
POST   /api/payments/mpesa/callback    # M-Pesa callback
GET    /api/auth/me                    # current user (JWT)
POST   /api/audit/events               # client audit events
POST   /api/assistant/chat             # AI assistant (SSE stream; stream:false for JSON)
GET    /api/assistant/history?conversationId=…   # persisted messages
GET    /api/assistant/suggestions      # welcome text + suggested questions
GET    /api/health/                    # health check
```

### Admin / staff
```
/api/admin/*                           # staff REST endpoints
```

### Throttling (DRF)
| Scope | Limit |
|---|---|
| Anonymous | 60/min |
| Authenticated | 120/min |
| Orders | 20/min |
| Payments | 10/min |
| Assistant (anonymous) | 15/min (`assistant_anon`) |
| Assistant (authenticated) | 30/min (`assistant_user`) |

`LOAD_TEST_MODE` raises limits for load testing.

---

## Database & Auth

### Database
- **Dev default:** SQLite (`backend/db.sqlite3`)
- **Production:** Postgres via `DATABASE_URL` (Supabase or Render-managed)
- SQL migrations live in `supabase/` and `frontend/supabase/migrations/` (profiles, categories, products, variants, carts, orders, payments, reservations, audit logs, wishlist, RLS policies)

### Auth flow
1. User signs up/in via **Supabase Auth** (email + password, email verification) on the client.
2. Client sends the Supabase JWT to Django.
3. Django verifies the token via `SUPABASE_JWT_SECRET` / `ISSUER` / `AUDIENCE` and lazily creates a mapped local user.
4. Django sessions are also used for local/admin auth.

**Roles:** `customer`, `staff`, `admin` (managed by `access_control`).

---

## Payments (M-Pesa)

- **Provider:** Safaricom **Daraja API** (sandbox supported via `MPESA_ENV`)
- **Flow:** Checkout → `/api/payments/create-intent` → STK Push → user authorizes → `/api/payments/mpesa/callback` → order confirmed
- Card payment scaffolding exists but M-Pesa is the primary method
- Callback secured with `MPESA_CALLBACK_SECRET` / `PAYMENT_WEBHOOK_SECRET`
- **No STK push exists yet.** With `PAYMENT_SANDBOX=true` (the default, and the
  value `render.yaml` ships) `create_intent` completes the intent in-process
  with an `SBX-…` reference, so the order reaches `PAID` and the admin
  Approve button — which is gated on `payment_status == PAID` — appears. The
  storefront polls the intent as before and reports the outcome. Set it to
  `false` only once a real STK push is wired up, otherwise orders would sit at
  `pending` forever and could never be approved.

---

## Environment Variables

Three templates exist: root `.env.example` (master), `backend/.env.example`, `frontend/.env.example`.

### Django
| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Secret key |
| `DJANGO_DEBUG` | Debug flag |
| `DJANGO_ALLOWED_HOSTS` | Allowed hosts |
| `DATABASE_URL` | Postgres connection string |
| `FRONTEND_ORIGIN` | CORS origin |
| `STORE_*` | Store branding |

### Email
| Variable | Purpose |
|---|---|
| `EMAIL_ENABLED` | **Master kill switch.** `false` (the Render default) deactivates delivery: rows are still recorded, nothing is sent, nothing reaches `SENT`. |
| `RESEND_API_KEY` | Switches to the HTTPS API transport (port 443). Required for real delivery — the free plan blocks SMTP. Only consulted when `EMAIL_ENABLED=true`. |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | SMTP transport; only consulted when `RESEND_API_KEY` is empty |
| `EMAIL_TIMEOUT` | Seconds a transport may block (default `10`) |
| `EMAIL_DELIVERY_MODE` | `inline` \| `deferred` \| `worker` — `deferred` leaves rows for the sweeper |
| `EMAIL_SWEEP_TOKEN` | Guards `POST /api/admin/emails/sweep`; unset disables the endpoint (404) |
| `DEFAULT_FROM_EMAIL` / `SERVER_EMAIL` | Customer mail / admin alerts |

### Supabase
| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_JWT_SECRET` | JWT verification |
| `SUPABASE_JWT_ISSUER` / `SUPABASE_JWT_AUDIENCE` | JWT claims |
| `SUPABASE_SERVICE_ROLE_KEY` | **Server-only**, never expose to client |
| `SUPABASE_STORAGE_BUCKET` | Media storage |

### Payments
| Variable | Purpose |
|---|---|
| `PAYMENT_WEBHOOK_SECRET` | Webhook signature |
| `MPESA_CALLBACK_SECRET` | Callback verification |
| `MPESA_ENV` | `sandbox` / `production` |
| `PAYMENT_SANDBOX` | Mock gateway: completes the intent in-process so orders reach `PAID` |
| `MPESA_CONSUMER_KEY` / `MPESA_CONSUMER_SECRET` | API credentials |
| `MPESA_SHORTCODE` / `MPESA_PASSKEY` | Till number credentials |
| `MPESA_CALLBACK_URL` | Public callback URL |

### Assistant (Gemini)
| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | **Server-only** Google AI Studio key; used exclusively by `backend/assistant` |
| `GEMINI_MODEL` | Model id (default `gemini-3.5-flash-lite`; must support the Interactions API) |
| `GEMINI_TIMEOUT_SECONDS` / `GEMINI_MAX_RETRIES` / `GEMINI_RETRY_BACKOFF_SECONDS` | Per-call timeout and retry budget |
| `ASSISTANT_MAX_TOOL_ROUNDS` | Max tool round-trips per message (default `4`) |
| `ASSISTANT_RETENTION_DAYS` | Conversation retention for the purge command (default `90`) |
| `THROTTLE_ASSISTANT_ANON_RATE` / `THROTTLE_ASSISTANT_USER_RATE` | Assistant rate limits (default `15/minute` / `30/minute`) |

### Observability
| Variable | Purpose |
|---|---|
| `LOG_LEVEL` / `LOG_FORMAT` | Logging (`json` \| `text`) |
| `AUDIT_LOG_RETENTION_DAYS` | Audit retention |
| `USE_X_FORWARDED_FOR` | Trust proxy headers |
| `LOAD_TEST_MODE` | Raise throttle limits |

### Frontend (`VITE_*` baked at build)
| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Django API base URL |
| `VITE_ADMIN_URL` | Admin dashboard URL |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | Supabase client |

> ⚠️ **Do not commit real secrets.** `frontend/.env.local` and `backend/.env` may contain live credentials — keep them out of version control.

---

## Local Development

### Backend (port 8000)
```bash
cd backend
python -m venv ../.venv
# Windows: ..\.venv\Scripts\activate    macOS/Linux: source ../.venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in Supabase / payment keys
python manage.py migrate
python manage.py runserver      # http://127.0.0.1:8000
```

### Frontend (port 3000)
```bash
cd frontend
npm install
cp .env.example .env.local      # set VITE_API_BASE_URL=http://127.0.0.1:8000
npm run dev                     # http://localhost:3000
```

### Verify
```bash
cd frontend
npm run lint        # typecheck
npm run test:api    # API integration tests
```

---

## Deployment

### Backend → Render
- Defined in `render.yaml` (Render Blueprint)
- `backend/Dockerfile`: Python 3.12-slim; runs `migrate --noinput` + `gunicorn` on start; `collectstatic` baked in
- Create a superuser via `ensure_superuser`
- Health check: `/api/health/`

### Frontend → Vercel
- `vercel.json` forces Vite build, output `dist`, rewrites all non-`/api` routes to `index.html`
- Set `VITE_*` env vars in Vercel project settings **before build**

### Post-deploy checklist
1. Verify `/api/health/` returns OK
2. Confirm CORS: `FRONTEND_ORIGIN` matches the Vercel domain
3. Set `MPESA_CALLBACK_URL` to the public Render URL
4. Create admin superuser
5. Smoke-test checkout in M-Pesa sandbox

---

## Observability & Security

- **Structured logging:** `LOG_FORMAT=json|text`, levels via `LOG_LEVEL`
- **Request correlation:** `X-Request-ID` on every request
- **Audit trail:** `AuditLogService` with canonical event constants; queryable via `/api/audit/events` and admin Activity center
- **Admin notifications:** stock, errors, security events
- **Throttling:** DRF per-scope rate limits (see [API Endpoints](#api-endpoints))
- **RBAC:** customer / staff / admin roles via `access_control`
- **RLS:** Supabase row-level security policies in SQL migrations
- **Secure cookies:** configurable via env flags behind `X-Forwarded-Proto`

---

## Documentation Index

| File | Contents |
|---|---|
| `README.md` | Deployment runbook (Render, Vercel, post-deploy) |
| `PROJECT.md` | This file — full project documentation |
| `questionnaire-answers.md` | Feature-state audit (auth, products, orders, payments, security, gaps) |
| `load-test-info.md` | k6 load-testing guide + API contracts |
| `backend/docs/LOGGING.md` | Logging / audit / notification spec |
| `backend/docs/ADMIN_VARIANTS.md` | Product variant admin feature spec |
| `backend/docs/CELERY.md` | Background imports & email subsystem runbook |
| `backend/docs/AI_ASSISTANT.md` | Gemini assistant runbook (env, endpoints, troubleshooting) |
| `frontend/README.md` | Frontend local-run instructions |
| `.env.example` | Master environment variable template |
