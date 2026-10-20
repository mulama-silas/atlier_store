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

-- The storefront uses supabase-js upsert/insert/delete for signed-in users.
-- Upsert requires UPDATE as well as INSERT; RLS still scopes rows to auth.uid().
grant select, insert, update, delete on public.wishlist_items to authenticated;
grant all privileges on public.wishlist_items to service_role;
