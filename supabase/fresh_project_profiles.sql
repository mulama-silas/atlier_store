-- MODEZA: minimum public schema needed alongside Supabase Auth.
-- Run this in the NEW project's Supabase SQL Editor before
-- frontend/supabase/migrations/202610130001_profiles_hardening.sql.
--
-- The Django commerce database is created by `python manage.py migrate`.
-- This file deliberately does not create the old direct-Supabase commerce
-- tables from setup.sql.

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  first_name text,
  last_name text,
  phone text,
  role text not null default 'customer'
    check (role in ('customer', 'staff', 'admin')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- The Data API role can read its own profile and update contact fields only.
-- Auth creates profile rows through the SECURITY DEFINER signup trigger.
grant select on public.profiles to authenticated;
grant update (first_name, last_name, phone) on public.profiles to authenticated;

drop policy if exists "Customers can read their own profile"
  on public.profiles;
create policy "Customers can read their own profile"
  on public.profiles for select using (auth.uid() = id);

drop policy if exists "Customers can update their own profile"
  on public.profiles;
create policy "Customers can update their own profile"
  on public.profiles for update using (auth.uid() = id);

drop policy if exists "Customers can insert their own profile"
  on public.profiles;
create policy "Customers can insert their own profile"
  on public.profiles for insert with check (auth.uid() = id);
