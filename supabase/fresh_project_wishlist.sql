-- MODEZA: signed-in customer wishlist for the storefront Data API.
-- Run after fresh_project_profiles.sql in a new Supabase project.

create table if not exists public.wishlist_items (
  user_id uuid not null references auth.users(id) on delete cascade,
  product_id text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, product_id)
);

create index if not exists wishlist_items_user_created_idx
  on public.wishlist_items(user_id, created_at desc);

alter table public.wishlist_items enable row level security;

drop policy if exists "Customers can read their own wishlist"
  on public.wishlist_items;
create policy "Customers can read their own wishlist"
  on public.wishlist_items for select
  using (auth.uid() = user_id);

drop policy if exists "Customers can add to their own wishlist"
  on public.wishlist_items;
create policy "Customers can add to their own wishlist"
  on public.wishlist_items for insert
  with check (auth.uid() = user_id);

drop policy if exists "Customers can update their own wishlist"
  on public.wishlist_items;
create policy "Customers can update their own wishlist"
  on public.wishlist_items for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "Customers can remove from their own wishlist"
  on public.wishlist_items;
create policy "Customers can remove from their own wishlist"
  on public.wishlist_items for delete
  using (auth.uid() = user_id);

-- Upsert uses INSERT + UPDATE; other operations are used by WishlistContext.
grant select, insert, update, delete on public.wishlist_items to authenticated;
grant all privileges on public.wishlist_items to service_role;
