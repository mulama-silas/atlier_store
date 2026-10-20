-- ============================================================================
-- MODEZA boutique — Supabase setup SQL
-- ============================================================================
-- Run this file ONCE in a NEW Supabase project:
--   Dashboard -> SQL Editor -> New query -> paste -> Run
--
-- It is a concatenation (in order) of the three committed migrations:
--   1. initial_commerce_schema      (tables, indexes, base RLS)
--   2. wishlist_items
--   3. rls_and_security_fixes       (missing policies + public reads)
--
-- Best used against an empty database; do not re-run wholesale on a project
-- that already has these objects (the plain `create table` statements are not
-- `if not exists`). For applying only missing pieces later, run the sections
-- that apply (their policies use the same names, so re-running those specific
-- statements is also safe/ignored).
-- ============================================================================

-- ============================================================================
-- SECTION 1 — Initial commerce schema
-- frontend/supabase/migrations/202609070001_initial_commerce_schema.sql
-- ============================================================================

create extension if not exists pgcrypto;

create type public.product_status as enum ('DRAFT', 'ACTIVE', 'ARCHIVED');
create type public.order_status as enum ('pending_payment', 'paid', 'processing', 'shipped', 'delivered', 'cancelled', 'return_requested', 'refunded');
create type public.payment_status as enum ('pending', 'paid', 'failed', 'refunded');
create type public.payment_method as enum ('mpesa', 'card');
create type public.reservation_status as enum ('active', 'committed', 'released', 'expired');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  first_name text,
  last_name text,
  phone text,
  role text not null default 'customer' check (role in ('customer', 'staff', 'admin')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.categories (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  description text,
  image_url text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.products (
  id uuid primary key default gen_random_uuid(),
  category_id uuid not null references public.categories(id),
  name text not null,
  slug text not null unique,
  description text not null,
  tagline text,
  details jsonb not null default '[]'::jsonb,
  price_minor integer not null check (price_minor >= 0),
  compare_at_price_minor integer check (compare_at_price_minor is null or compare_at_price_minor > price_minor),
  image_url text,
  images jsonb not null default '[]'::jsonb,
  status public.product_status not null default 'DRAFT',
  is_featured boolean not null default false,
  is_new_arrival boolean not null default false,
  is_best_seller boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.product_variants (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete cascade,
  sku text not null unique,
  size text,
  color text,
  color_hex text,
  price_minor integer check (price_minor is null or price_minor >= 0),
  stock_quantity integer not null default 0 check (stock_quantity >= 0),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.carts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete set null,
  guest_token_hash text unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.cart_items (
  id uuid primary key default gen_random_uuid(),
  cart_id uuid not null references public.carts(id) on delete cascade,
  product_id uuid not null references public.products(id),
  variant_id uuid not null references public.product_variants(id),
  quantity integer not null check (quantity > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (cart_id, variant_id)
);

create table public.orders (
  id uuid primary key default gen_random_uuid(),
  order_number text not null unique,
  cart_id uuid references public.carts(id),
  user_id uuid references auth.users(id) on delete set null,
  customer jsonb not null,
  subtotal_minor integer not null check (subtotal_minor >= 0),
  shipping_cost_minor integer not null check (shipping_cost_minor >= 0),
  tax_minor integer not null check (tax_minor >= 0),
  total_minor integer not null check (total_minor >= 0),
  shipping_method text not null check (shipping_method in ('standard', 'express')),
  payment_method public.payment_method not null default 'mpesa',
  status public.order_status not null default 'pending_payment',
  payment_status public.payment_status not null default 'pending',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  product_id uuid not null references public.products(id),
  variant_id uuid not null references public.product_variants(id),
  product_name text not null,
  variant_sku text not null,
  variant_size text,
  variant_color text,
  image_url text,
  unit_price_minor integer not null check (unit_price_minor >= 0),
  quantity integer not null check (quantity > 0),
  line_total_minor integer not null check (line_total_minor >= 0)
);

create table public.stock_reservations (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  variant_id uuid not null references public.product_variants(id),
  quantity integer not null check (quantity > 0),
  status public.reservation_status not null default 'active',
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.payment_intents (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id),
  provider text not null default 'mpesa',
  provider_reference text unique,
  amount_minor integer not null check (amount_minor >= 0),
  currency text not null default 'KES',
  method public.payment_method not null,
  status text not null default 'pending' check (status in ('pending', 'succeeded', 'failed', 'cancelled')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.payment_events (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  event_id text not null unique,
  event_type text not null,
  payload jsonb not null,
  processed_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid references auth.users(id) on delete set null,
  action text not null,
  entity_type text not null,
  entity_id text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index products_status_category_idx on public.products(status, category_id);
create index product_variants_product_idx on public.product_variants(product_id);
create index carts_user_idx on public.carts(user_id);
create index orders_user_created_idx on public.orders(user_id, created_at desc);
create index orders_status_created_idx on public.orders(status, created_at desc);
create index reservations_expiry_idx on public.stock_reservations(status, expires_at);
create index audit_logs_entity_idx on public.audit_logs(entity_type, entity_id, created_at desc);

alter table public.profiles enable row level security;
alter table public.carts enable row level security;
alter table public.orders enable row level security;
alter table public.order_items enable row level security;
alter table public.audit_logs enable row level security;

create policy "Customers can read their own profile"
  on public.profiles for select using (auth.uid() = id);
create policy "Customers can update their own profile"
  on public.profiles for update using (auth.uid() = id);
create policy "Customers can read their own orders"
  on public.orders for select using (auth.uid() = user_id);
create policy "Customers can read their own order items"
  on public.order_items for select using (
    exists (select 1 from public.orders o where o.id = order_id and o.user_id = auth.uid())
  );


-- ============================================================================
-- SECTION 2 — Wishlist items
-- frontend/supabase/migrations/202609090002_wishlist_items.sql
-- ============================================================================

create table public.wishlist_items (
  user_id uuid not null references auth.users(id) on delete cascade,
  product_id text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, product_id)
);

create index wishlist_items_user_created_idx
  on public.wishlist_items(user_id, created_at desc);

alter table public.wishlist_items enable row level security;

create policy "Customers can read their own wishlist"
  on public.wishlist_items for select
  using (auth.uid() = user_id);

create policy "Customers can add to their own wishlist"
  on public.wishlist_items for insert
  with check (auth.uid() = user_id);

create policy "Customers can remove from their own wishlist"
  on public.wishlist_items for delete
  using (auth.uid() = user_id);


-- ============================================================================
-- SECTION 3 — RLS and security fixes
-- frontend/supabase/migrations/202609150003_rls_and_security_fixes.sql
-- ============================================================================
-- Adds missing RLS policies for tables that had RLS enabled but no policies
-- (which blocked all access), plus an INSERT policy for profiles so signups
-- can create their profile row, and public read access for the catalogue.

-- Carts — customers own their carts via user_id
create policy "Customers can read their own carts"
  on public.carts for select
  using (auth.uid() = user_id);

create policy "Customers can insert their own carts"
  on public.carts for insert
  with check (auth.uid() = user_id);

create policy "Customers can update their own carts"
  on public.carts for update
  using (auth.uid() = user_id);

-- Cart items — customers own their cart items via cart FK
alter table public.cart_items enable row level security;

create policy "Customers can read their own cart items"
  on public.cart_items for select
  using (
    exists (
      select 1 from public.carts c
      where c.id = cart_id and c.user_id = auth.uid()
    )
  );

create policy "Customers can insert their own cart items"
  on public.cart_items for insert
  with check (
    exists (
      select 1 from public.carts c
      where c.id = cart_id and c.user_id = auth.uid()
    )
  );

create policy "Customers can update their own cart items"
  on public.cart_items for update
  using (
    exists (
      select 1 from public.carts c
      where c.id = cart_id and c.user_id = auth.uid()
    )
  );

create policy "Customers can delete their own cart items"
  on public.cart_items for delete
  using (
    exists (
      select 1 from public.carts c
      where c.id = cart_id and c.user_id = auth.uid()
    )
  );

-- Profiles — INSERT policy for new user signup
create policy "Customers can insert their own profile"
  on public.profiles for insert
  with check (auth.uid() = id);

-- Stock reservations — staff-only via service key (RLS on, no anon access)
alter table public.stock_reservations enable row level security;

-- Payment intents — staff-only via service key (RLS on, no anon access)
alter table public.payment_intents enable row level security;

-- Payment events — staff-only via service key (RLS on, no anon access)
alter table public.payment_events enable row level security;

-- Products & categories — public read access
alter table public.products enable row level security;
alter table public.categories enable row level security;
alter table public.product_variants enable row level security;

create policy "Anyone can read active categories"
  on public.categories for select
  using (is_active = true);

create policy "Anyone can read active products"
  on public.products for select
  using (status = 'ACTIVE'::public.product_status);

create policy "Anyone can read active product variants"
  on public.product_variants for select
  using (is_active = true);


-- ============================================================================
-- SECTION 4 — Explicit Data API grants for newly created public tables
-- ============================================================================
-- Grants enable table operations; RLS policies above still scope customer rows.
-- Sensitive commerce/payment tables remain inaccessible to anon/authenticated.

grant select on public.categories, public.products, public.product_variants
  to anon, authenticated;
grant select on public.profiles to authenticated;
grant update (first_name, last_name, phone) on public.profiles to authenticated;
grant select, insert, update on public.carts to authenticated;
grant select, insert, update, delete on public.cart_items to authenticated;
grant select on public.orders, public.order_items to authenticated;
grant select, insert, update, delete on public.wishlist_items to authenticated;

grant all privileges on table
  public.profiles,
  public.categories,
  public.products,
  public.product_variants,
  public.carts,
  public.cart_items,
  public.orders,
  public.order_items,
  public.stock_reservations,
  public.payment_intents,
  public.payment_events,
  public.audit_logs,
  public.wishlist_items
to service_role;
