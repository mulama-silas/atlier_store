# MODEZA Boutique Frontend

This directory contains the React/Vite customer storefront for the MODEZA fashion store.

## Run locally

From the `frontend` directory:

```bash
npm install
npm run dev
```

The development server runs at `http://127.0.0.1:3000`.

## Environment

Copy `.env.example` to `.env.local` and configure the browser Supabase values when customer accounts are enabled:

```env
VITE_SUPABASE_URL="https://your-project.supabase.co"
VITE_SUPABASE_ANON_KEY="your-anon-key"
VITE_API_BASE_URL="http://127.0.0.1:8000"
VITE_DEFAULT_WHATSAPP_NUMBER="+254768873844"
```

Set `VITE_DEFAULT_WHATSAPP_NUMBER` in Vercel's environment variables for the
frontend deployment. Vite embeds `VITE_` variables at build time, so redeploy
after changing it. Use the international number format, for example
`+2547XXXXXXXX`.

Server-side Supabase and M-Pesa variables are retained for the current local API prototype. The future Django backend should own those integrations in the separate `backend` project.

The frontend expects the backend to expose the existing `/api` contract, including `/api/products`, `/api/categories`, `/api/cart`, `/api/orders`, and `/api/payments`. `VITE_API_BASE_URL` should contain only the backend origin, without the `/api` suffix. The Django backend must allow the frontend origin through CORS and accept the `Authorization: Bearer <supabase-access-token>` header for authenticated requests.

## Project boundary

- `src/`: React pages, components, contexts, and client services
- `public/`: static assets
- `supabase/`: current database migration prototype
- `package.json`: frontend scripts and dependencies

The repository root is reserved for the future Django backend alongside this `frontend` directory.
