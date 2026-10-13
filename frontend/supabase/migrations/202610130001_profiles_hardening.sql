-- ============================================================================
-- MODEZA boutique — profiles: auto-population + privilege hardening
-- ============================================================================
-- Run ONCE in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query).
-- Safe to re-run: `create or replace` / `on conflict` throughout.
--
-- THE PROBLEM
--   public.profiles has columns for first_name / last_name / phone / role, and
--   202609150003 added an INSERT policy "so signups can create their profile
--   row". But no code anywhere calls it: not the storefront, not Django, and
--   there was no signup trigger. A permission with no caller is not a feature.
--   Every customer who signed up has an auth.users row and NO profiles row.
--
--   Separately, the UPDATE policy scoped by row (`auth.uid() = id`) but not by
--   column, so a signed-in customer could set role='admin' on their own row.
--   Harmless today only because accounts/authentication.py reads the role from
--   app_metadata (service-role writable) rather than this column.
--
-- WHAT THIS DOES
--   1. handle_new_user trigger  -> a profile row is created for every signup,
--      whichever path created it (password, OAuth, magic link, phone OTP, a
--      dashboard insert, a future mobile app).
--   2. Column-level grants      -> closes the role escalation. RLS is row-level
--      and CANNOT restrict columns, so this needs REVOKE/GRANT.
--   3. A one-off backfill       -> the trigger only fires for future signups.
--
--   Run step 3 separately (it is commented at the bottom) after step 1, so a
--   brand-new user is never double-inserted.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 1. Trigger
-- ---------------------------------------------------------------------------
-- SECURITY DEFINER because the INSERT runs as the function owner rather than
-- the (unprivileged) role that inserted into auth.users. search_path is pinned
-- to public so the function body cannot be redirected via search_path.
--
-- full_name is the key the storefront already sends and that Django already
-- reads (accounts/authentication.py, sync_local_name), so both agree.
-- role is seeded from raw_app_meta_data -- service-role controlled -- and never
-- from anything the user supplied.

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, first_name, last_name, phone, role)
  values (
    new.id,
    nullif(split_part(coalesce(new.raw_user_meta_data->>'full_name', ''), ' ', 1), ''),
    nullif(regexp_replace(coalesce(new.raw_user_meta_data->>'full_name', ''), '^\S+\s*', ''), ''),
    new.phone,
    coalesce(new.raw_app_meta_data->>'role', 'customer')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();


-- ---------------------------------------------------------------------------
-- 2. Column-level grants -- close the role escalation
-- ---------------------------------------------------------------------------
-- The existing UPDATE policy (using auth.uid() = id) still decides WHICH row a
-- customer may touch. These grants decide WHICH COLUMNS they may change, which
-- a policy cannot express. After this, `update profiles set role = 'admin'`
-- fails with a permission error regardless of policy.
--
-- Staff promotion continues to work through app_metadata, which only the
-- service role can write. Nothing needs UPDATE on role.

revoke update on public.profiles from authenticated;
grant update (first_name, last_name, phone) on public.profiles to authenticated;

-- Defensive: confirm the column-level privilege actually took.
do $$
declare
  has_role_update boolean;
begin
  select has_column_privilege(
           'authenticated', 'public.profiles', 'role', 'UPDATE')
    into has_role_update;

  if has_role_update then
    raise exception
      'authenticated still holds UPDATE on profiles.role -- aborting so this is '
      'reviewed rather than silently left open.';
  end if;
end $$;


-- ---------------------------------------------------------------------------
-- 3. One-off backfill of EXISTING users
-- ---------------------------------------------------------------------------
-- Uncomment and run AFTER step 1. `on conflict do nothing` preserves any rows
-- created by hand in the dashboard.
--
-- insert into public.profiles (id, first_name, last_name, phone, role)
-- select id,
--   nullif(split_part(coalesce(raw_user_meta_data->>'full_name',''), ' ', 1), ''),
--   nullif(regexp_replace(coalesce(raw_user_meta_data->>'full_name',''), '^\S+\s*', ''), ''),
--   phone,
--   coalesce(raw_app_meta_data->>'role', 'customer')
-- from auth.users
-- on conflict (id) do nothing;


-- ---------------------------------------------------------------------------
-- VERIFY
-- ---------------------------------------------------------------------------
-- Every user has a profile:
--   select count(*) from auth.users u
--   where not exists (select 1 from public.profiles p where p.id = u.id);
--   -- expect 0
--
-- The escalation is closed (run as the ANON/authenticated context, or just
-- confirm the guard above did not raise):
--   select has_column_privilege(
--     'authenticated', 'public.profiles', 'role', 'UPDATE');
--   -- expect false
--
-- Note: profiles.role reflects signup-time app_metadata. If a user's role is
-- changed later via app_metadata this column goes stale -- nothing reads it for
-- authorization, so it is cosmetic. The replica joins profiles for identity
-- only; role never leaves app_metadata.
-- ---------------------------------------------------------------------------