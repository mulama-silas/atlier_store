-- ============================================================================
-- MODEZA boutique — Supabase analytics replica
-- ============================================================================
-- Run ONCE in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query).
--
-- PURPOSE
--   A read-only analytics copy of the Django system of record, plus a nightly
--   catalogue snapshot history. This is NOT a disaster-recovery target: the
--   Django app cannot be repointed at this schema.
--
-- WHY A SEPARATE SCHEMA
--   Supabase's PostgREST only exposes schemas listed in the `db-schemas`
--   setting (default: `public`). Because `replica` is NOT in that list, the
--   anonymous key baked into the public Vite bundle cannot read it at all.
--   RLS is enabled on every table with NO policies, so `anon` and
--   `authenticated` are denied even if someone later adds `replica` to
--   `db-schemas` by mistake. Only `service_role` / direct superuser writes.
--
-- WRITES COME FROM
--   `python manage.py sync_replica`, over a direct Postgres connection
--   (SUPABASE_DB_URL) -- not PostgREST, which cannot reach this schema.
--
-- SAFE TO RE-RUN: every object is `if not exists` / `create or replace`.
-- ============================================================================

create schema if not exists replica;

-- ---------------------------------------------------------------------------
-- Current state: catalogue
-- ---------------------------------------------------------------------------

create table if not exists replica.categories (
  id uuid primary key,
  name text,
  slug text,
  description text,
  image_url text,
  is_active boolean,
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists replica.products (
  id uuid primary key,
  category_id uuid,
  name text,
  slug text,
  tagline text,
  description text,
  details jsonb,
  price_minor integer,
  compare_at_price_minor integer,
  images jsonb,
  status text,
  is_featured boolean,
  is_new_arrival boolean,
  is_best_seller boolean,
  -- Product-level convenience fields (catalog.Product carries these directly,
  -- separate from ProductVariant which is the real source for stock).
  sku text,
  product_code text,
  stock_quantity integer,
  created_at timestamptz,
  updated_at timestamptz
);
create index if not exists products_category_idx on replica.products (category_id);

create table if not exists replica.product_variants (
  id uuid primary key,
  product_id uuid,
  sku text,
  size text,
  color text,
  color_hex text,
  price_minor integer,
  stock_quantity integer,
  is_active boolean
  -- catalog.ProductVariant deliberately has no created_at/updated_at.
);
create index if not exists product_variants_product_idx
  on replica.product_variants (product_id);

-- ---------------------------------------------------------------------------
-- Append-only ledgers. These ARE their own history -- replicate every row.
-- ---------------------------------------------------------------------------

create table if not exists replica.orders (
  id uuid primary key,
  order_number text,
  -- FK to Django's auth_user. Identity resolves via public.profiles, which is
  -- why no user record is duplicated here. Set null when the user was deleted.
  user_id uuid,
  -- PII (shipping name / phone / address). Unavoidable for sales reporting.
  -- See the plan's section 6 -- retention is an open owner decision.
  customer jsonb,
  notes text,
  subtotal_minor integer,
  discount_minor integer,
  shipping_cost_minor integer,
  shipping_discount_minor integer,
  tax_minor integer,
  total_minor integer,
  coupon_code text,
  promotion_snapshot jsonb,
  shipping_method text,
  payment_method text,
  status text,
  payment_status text,
  currency text,
  created_at timestamptz,
  updated_at timestamptz
);
create index if not exists orders_user_created_idx
  on replica.orders (user_id, created_at desc);
create index if not exists orders_status_created_idx
  on replica.orders (status, created_at desc);

create table if not exists replica.order_items (
  id uuid primary key,
  order_id uuid,
  product_id uuid,
  variant_id uuid,
  product_name text,
  variant_sku text,
  variant_size text,
  variant_color text,
  image_url text,
  unit_price_minor integer,
  quantity integer,
  line_total_minor integer
);
create index if not exists order_items_order_idx on replica.order_items (order_id);

create table if not exists replica.payment_intents (
  id text primary key,
  order_id uuid,
  amount_minor integer,
  currency text,
  method text,
  status text,
  gateway_reference text,
  metadata jsonb,
  created_at timestamptz,
  updated_at timestamptz
  -- payments.PaymentIntent.client_secret is deliberately NOT replicated: it
  -- is a live payment-confirmation secret and analytics never needs it.
);
create index if not exists payment_intents_order_idx
  on replica.payment_intents (order_id);

create table if not exists replica.inventory_transactions (
  id uuid primary key,
  variant_id uuid,
  quantity_delta integer,
  previous_quantity integer,
  new_quantity integer,
  reason text,
  order_id uuid,
  actor_id uuid,
  created_at timestamptz
);
create index if not exists inventory_transactions_variant_idx
  on replica.inventory_transactions (variant_id, created_at desc);

create table if not exists replica.stock_reservations (
  id uuid primary key,
  order_id uuid,
  variant_id uuid,
  quantity integer,
  status text,
  expires_at timestamptz,
  created_at timestamptz,
  released_at timestamptz
);
create index if not exists stock_reservations_status_expiry_idx
  on replica.stock_reservations (status, expires_at);

create table if not exists replica.promotions (
  id uuid primary key,
  name text,
  description text,
  promotion_type text,
  status text,
  discount_percent numeric,
  discount_amount_minor integer,
  maximum_discount_minor integer,
  minimum_order_value_minor integer,
  minimum_quantity integer,
  qualifying_quantity integer,
  reward_quantity integer,
  reward_discount_percent numeric,
  coupon_code text,
  is_automatic boolean,
  starts_at timestamptz,
  ends_at timestamptz,
  usage_limit integer,
  usage_limit_per_customer integer,
  priority integer,
  stackable boolean,
  customer_scope text,
  created_at timestamptz,
  updated_at timestamptz
);

create table if not exists replica.promotion_redemptions (
  id uuid primary key,
  promotion_id uuid,
  order_id uuid,
  user_id uuid,
  coupon_code text,
  discount_minor integer,
  shipping_discount_minor integer,
  voided boolean,
  redeemed_at timestamptz
);
create index if not exists promotion_redemptions_promo_idx
  on replica.promotion_redemptions (promotion_id, redeemed_at desc);

create table if not exists replica.receipts (
  id uuid primary key,
  order_id uuid,
  receipt_number text,
  status text,
  snapshot jsonb,
  pdf_url text,
  amount_minor integer,
  currency text,
  gateway_reference text,
  generated_at timestamptz,
  created_at timestamptz,
  updated_at timestamptz
);

-- ---------------------------------------------------------------------------
-- Sanitized audit events. Direct PII (email, IP, user agent, descriptions)
-- is intentionally not copied; metadata is sanitized again during sync.
-- ---------------------------------------------------------------------------

create table if not exists replica.audit_logs (
  id uuid primary key,
  actor_id uuid,
  actor_role text,
  action text,
  category text,
  object_type text,
  object_id text,
  metadata jsonb,
  result text,
  severity text,
  request_id text,
  path text,
  status_code integer,
  created_at timestamptz
);
create index if not exists audit_logs_actor_created_idx
  on replica.audit_logs (actor_id, created_at desc);
create index if not exists audit_logs_action_created_idx
  on replica.audit_logs (action, created_at desc);

-- ---------------------------------------------------------------------------
-- Derived customer metrics.
-- Identity (name / phone) comes from public.profiles via user_id -- it is NOT
-- duplicated here, which keeps a second copy of customer PII out of the
-- replica. Only aggregate numbers live here.
-- ---------------------------------------------------------------------------

create table if not exists replica.customers (
  user_id uuid primary key,
  first_order_at timestamptz,
  last_order_at timestamptz,
  order_count integer,
  -- Sum of total_minor over non-cancelled orders.
  total_spent_minor bigint
);

-- ---------------------------------------------------------------------------
-- HISTORY: nightly catalogue snapshots.
--
-- Stored as jsonb on purpose: the payload survives Django model changes, so
-- adding a field to catalog.Product needs no migration here.
-- ---------------------------------------------------------------------------

create table if not exists replica.catalogue_snapshots (
  id bigint generated always as identity primary key,
  entity text not null check (entity in ('product', 'variant', 'category')),
  entity_id uuid not null,
  snapshot_date date not null,
  payload jsonb not null,
  synced_at timestamptz not null default now(),
  -- Makes a second run on the same day idempotent rather than duplicating.
  unique (entity, entity_id, snapshot_date)
);
create index if not exists catalogue_snapshots_lookup_idx
  on replica.catalogue_snapshots (entity, entity_id, snapshot_date desc);

-- ---------------------------------------------------------------------------
-- Run log: powers the admin status page (staleness, outcome, per-table counts).
-- ---------------------------------------------------------------------------

create table if not exists replica.sync_runs (
  id bigint generated always as identity primary key,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  -- 'requested' is a deferred-mode run waiting for the cron to pick it up.
  status text not null default 'running'
    check (status in ('requested', 'running', 'success', 'failure')),
  triggered_by text not null
    check (triggered_by in ('cron', 'manual', 'first')),
  table_counts jsonb not null default '{}'::jsonb,
  storage jsonb not null default '{}'::jsonb,
  error text
);
create index if not exists sync_runs_recent_idx on replica.sync_runs (started_at desc);

-- A project that already ran this file has the older CHECK that forbids
-- 'requested' (deferred mode). Widen it so re-running is enough to upgrade.
do $$
declare
  allows_requested boolean;
begin
  select exists (
    select 1
    from pg_constraint c
    join pg_class t on t.oid = c.conrelid
    where t.relname = 'sync_runs'
      and c.contype = 'c'
      and pg_get_constraintdef(c.oid) like '%requested%'
  ) into allows_requested;

  if not allows_requested then
    alter table replica.sync_runs
      drop constraint if exists sync_runs_status_check;
    alter table replica.sync_runs
      add constraint sync_runs_status_check
      check (status in ('requested', 'running', 'success', 'failure'));
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- Locking: deny-by-default. No policies are created on purpose, so `anon` and
-- `authenticated` have no access even if `replica` is ever added to
-- `db-schemas`. Writes arrive over a direct superuser/service-role connection,
-- which bypasses RLS.
-- ---------------------------------------------------------------------------

do $$
declare
  t text;
begin
  foreach t in array array[
    'categories', 'products', 'product_variants', 'orders', 'order_items',
    'payment_intents', 'inventory_transactions', 'stock_reservations',
    'promotions', 'promotion_redemptions', 'receipts', 'audit_logs', 'customers',
    'catalogue_snapshots', 'sync_runs'
  ]
  loop
    execute format('alter table replica.%I enable row level security', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- Verify after running:
--
--   -- as the anon key, both MUST fail:
--   select * from replica.products;
--   select * from replica.orders;
--
--   -- after a successful `manage.py sync_replica`, as superuser:
--   select entity, snapshot_date, count(*)
--   from replica.catalogue_snapshots group by 1, 2 order by 2 desc;
-- ---------------------------------------------------------------------------