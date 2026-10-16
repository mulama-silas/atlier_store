# MODEZA M-Pesa Daraja setup

## Current implementation

The React/Vite storefront is static on Vercel. It sends checkout requests to the Django REST API on Render; Django uses PostgreSQL and the existing `Order`, `PaymentIntent`, and `PaymentEvent` records. Supabase Auth supplies customer identity. Daraja keys and all OAuth/STK requests stay in Django. The callback is `POST /api/payments/mpesa/callback` on the public Render backend.

The amount and order total come from the server-created order and its catalog/cart calculation. The callback is matched against both Daraja request IDs; successful callback data is checked against the stored amount and receipt, then confirmed by a server-to-server STK query before an order can be marked paid. Duplicate callbacks are ignored. Customer confirmation requests cannot settle an intent. A callback whose verification is temporarily unavailable stays pending and can be reconciled by a later callback; do not manually mark that order paid.

## Default deployed demo mode

The Render blueprint defaults to `MPESA_ENVIRONMENT=sandbox` and `MPESA_PAYMENT_MODE=simulation`. The customer can place an order successfully without a registered business, shortcode, Daraja credentials, or a phone prompt. No payment is sent or collected; the order remains unpaid and no official payment receipt is created. The success page identifies the checkout as a demo.

Set `MPESA_PAYMENT_MODE=daraja` when you are ready to test the retained Daraja STK Push integration. Simulation is rejected when `MPESA_ENVIRONMENT=production`.

## Sandbox account and credentials

1. Create or sign in to an account at the [Safaricom Daraja Developer Portal](https://developer.safaricom.co.ke/account/signup).
2. Create a sandbox app and add the M-PESA Express (STK Push) product.
3. From the app's keys page, copy the sandbox Consumer Key and Consumer Secret. Get the sandbox shortcode and passkey from the Daraja test credentials/simulator for that app. Never put these values in Vite variables, source control, support tickets, or customer-visible logs. Safaricom documents the STK product and sandbox simulator in its [M-PESA Express guide](https://developer.safaricom.co.ke/apis/MpesaExpressSimulate).
4. Set the values below on the **Django backend**, first in `backend/.env` for local development, then in the Render service environment for a deployed sandbox. Keep secrets in the ignored `backend/.env` for local development; use the Render service environment for deployment.

```dotenv
MPESA_ENVIRONMENT=sandbox
MPESA_PAYMENT_MODE=daraja
MPESA_CONSUMER_KEY=...
MPESA_CONSUMER_SECRET=...
MPESA_SHORTCODE=...
MPESA_PASSKEY=...
MPESA_TRANSACTION_TYPE=CustomerPayBillOnline
MPESA_CALLBACK_URL=https://<your-render-service>.onrender.com/api/payments/mpesa/callback
```

`MPESA_ENVIRONMENT` accepts `sandbox` or `production`. Set `MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline` for a Till, or `CustomerPayBillOnline` for a PayBill. `MPESA_CALLBACK_URL` must be the full public HTTPS address of the deployed callback endpoint. The endpoint is asynchronous; a local `localhost` URL is not reachable by Safaricom. For local development, expose the Django listener through a trusted HTTPS tunnel (such as ngrok or LocalTunnel) and set the tunnel URL as the callback. Keep the tunnel alive for the whole test.

## Vercel and Render settings

1. The Render blueprint defaults to simulation, so no Daraja credentials are needed for demo checkout. To test STK Push, set `MPESA_PAYMENT_MODE=daraja` and add the Daraja `MPESA_*` secrets in the Render dashboard. Do not set these as `VITE_*` values.
2. In **Vercel → Project → Settings → Environment Variables**, set only the storefront's public values: `VITE_API_BASE_URL=https://<your-render-service>.onrender.com`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and any existing public storefront settings. No Daraja credential belongs in Vercel's frontend build environment.
3. Confirm the callback URL uses the exact deployed Render hostname and path. Deploy/restart the backend after changing variables. Verify `GET https://<backend>/api/health/` and that the public URL accepts POST requests (a malformed request should be rejected safely).
4. Run the payment migration during the normal backend deploy: `python manage.py migrate`. The existing container start command already runs migrations.

The backend has a scoped DRF payments throttle (`THROTTLE_PAYMENTS_RATE`, default `10/minute`). Keep `DJANGO_DEBUG=false`, HTTPS enforcement, and the existing CORS allowlist enabled in production. Callbacks do not rely on a query-string secret because Daraja does not sign the callback; a callback alone cannot settle an order. The backend checks it with Daraja's authenticated STK query API.

## Sandbox test flow

1. Start with sandbox credentials and a deployed HTTPS callback (or an HTTPS tunnel for local work). Keep the callback path publicly reachable for the duration of the request.
2. Add an in-stock product, choose M-Pesa at checkout, and enter a Kenyan M-Pesa number in `07…`, `01…`, `2547…`, or `2541…` form.
3. Confirm that the page shows the order total and that the phone receives the sandbox prompt. Complete or cancel it in the simulator/test flow.
4. Keep the checkout page open. The storefront polls its own backend for status. A successful screen is shown only after the callback and the backend's Daraja STK query verify success. A callback outage leaves the order pending.
5. Check the order and payment intent in Django admin/audit logs. Confirm unsuccessful attempts remain unpaid and repeated submissions reuse the active pending attempt.

Automated tests use mocked Daraja calls and never make transactions. The sandbox OAuth check passed, but an STK request/callback has not been tested end to end.

## Before production

1. Obtain Safaricom approval and production M-PESA Express access for the business PayBill/Till and API user. Sandbox credentials and shortcode must not be reused.
2. Obtain the production Consumer Key, Consumer Secret, shortcode, and passkey through the approved Daraja go-live process. Safaricom describes go-live requirements in the [M-PESA Express documentation](https://developer.safaricom.co.ke/apis/MpesaExpressSimulate) and [Daraja FAQ](https://developer.safaricom.co.ke/faqs).
3. Set `MPESA_ENVIRONMENT=production` and `MPESA_PAYMENT_MODE=daraja`, then replace the shortcode, passkey, and keys in Render's protected environment settings. Keep the same public HTTPS callback route unless the backend host changes.
4. Verify using a Safaricom-approved low-value live test with the business owner. Check the Daraja dashboard, callback, STK query, order, receipt, inventory, and customer confirmation before enabling normal traffic.
5. Monitor callback delivery and pending payment reconciliation. Add an operational reconciliation job/manual runbook before depending on callbacks as the only recovery path.

## Troubleshooting

- **Missing configuration / integration not configured:** set all five credentials/config values and the callback URL on Render; restart the service. The API fails closed and never fakes a successful payment.
- **Invalid access token:** check the environment matches the credentials, and copy the Consumer Key/Secret exactly. The backend obtains a fresh OAuth token for each request.
- **STK request rejected:** check the environment's shortcode/passkey pair, M-PESA Express product access, supported Kenyan phone format, and integer KES amount. Read the sanitized API error and request ID in backend logs; secrets and full phone numbers are not logged.
- **No phone prompt:** confirm the sandbox simulator and app are configured for M-PESA Express and that the entered phone is eligible for the sandbox flow.
- **Prompt completed but order remains pending:** check Render logs for the callback verification diagnostic, then verify the callback hostname/path is public HTTPS and the backend can reach Daraja's STK query endpoint. Do not confirm payment from the browser or manually edit the order status.
- **Vercel request fails:** check `VITE_API_BASE_URL`, Render availability, and backend `FRONTEND_ORIGIN` CORS settings. Daraja credentials do not belong in Vercel.
- **Render request timeout:** STK initiation and callback verification use bounded HTTP timeouts. The callback remains asynchronous; do not wait for customer PIN entry inside the checkout HTTP request.

## Operational notes and current limits

- Render hosts the payment callback, not Vercel. Vercel serves the SPA and rewrites client-side routes only.
- Pending intent retries reuse the same active attempt to avoid duplicate prompts. A failed attempt can be retried against the same order. Review late callbacks for an already-failed attempt operationally; current transition logic does not revive failed intents.
- Successful callback settlement verifies request IDs, callback amount and receipt, and Daraja's STK query result. If Daraja's query endpoint is unavailable, the order stays pending.
- Amounts are sent as whole KES shillings. The backend uses the authoritative order amount; the client cannot submit an amount.
- No real or sandbox Daraja request has been made from this repository during preparation. Production payments require approved credentials and end-to-end verification.
