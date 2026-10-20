# New Supabase project setup

This repository uses Supabase for customer sign-in and public product-image
storage. Django/Postgres is the commerce system of record. The older
`setup.sql` creates a second, direct-to-Supabase commerce schema and should not
be run for the current Django-backed app.

## SQL Editor steps

Run these scripts in order in the new project's SQL Editor:

1. `supabase/fresh_project_profiles.sql` — creates the minimal `public.profiles`
   table and its row-level policies.
2. `frontend/supabase/migrations/202610130001_profiles_hardening.sql` — creates
   the Auth signup trigger and prevents customers from changing their role.
3. `supabase/fresh_project_wishlist.sql` — creates the signed-in customer
   wishlist table used by the storefront Data API.
4. `supabase/replica_schema.sql` — optional; run only if you intend to use the
   Django analytics/backup replica. It creates the private `replica` schema.

Do **not** run `supabase/setup.sql` or the older
`frontend/supabase/migrations/202609070001_initial_commerce_schema.sql` and
`202609090002_wishlist_items.sql` / `202609150003_rls_and_security_fixes.sql`
for this current setup. Those scripts define the former Supabase-direct
commerce implementation; products, carts, and orders now live in Django's
database instead.

## Dashboard configuration

- In **Storage**, create a public bucket named `product-images`. Django writes
  product images there and returns public CDN URLs.
- In **Authentication → URL Configuration**, set the production storefront URL
  and allowed redirect URLs (include the account completion and password
  recovery routes used by the storefront).
- Enable Google as an Auth provider only if you intend to offer Google sign-in;
  add that provider's credentials in Supabase Auth settings.

## Connect the app

- Set Render `DATABASE_URL` to the new project's Postgres connection string.
  The backend Docker start command automatically runs
  `python manage.py migrate --noinput`, which creates Django's tables.
- Update Render's `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and JWT
  verification settings to the new project. Update Vercel's
  `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` too. Use the new project's
  current signing-key/JWKS configuration and issuer shown by Supabase; do not
  copy old project secrets.
- If enabling the replica, set Render `SUPABASE_DB_URL` to the new project's
  direct Postgres URI. It is the replica writer connection; `DATABASE_URL`
  remains the Django primary database connection.

## Data API table access

Supabase grants for the legacy `public` schema are declared beside table
creation in `frontend/supabase/migrations/` and mirrored in `supabase/setup.sql`.
The storefront's `wishlist_items` Data API access is limited to signed-in users
and scoped by RLS. The legacy commerce scripts explicitly grant public catalogue
reads; order, payment, and audit tables stay private to customer API roles.
Django's tables are accessed over the direct Postgres connection and are not
exposed through the Data API. Keep future grants table-specific in the migration
that creates each table; avoid broad schema-wide grants.

After Render redeploys, create the Django admin with
`python manage.py ensure_superuser` (or the project's configured startup flow).
Supabase Auth customer accounts are separate and must sign up again in the new
project.
