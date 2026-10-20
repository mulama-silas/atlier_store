# Boutique E-Commerce — Load Test Information

## 1. Frontend
What is your frontend URL?

Answer: `http://127.0.0.1:3000`

## 2. Django Backend
What is your Django backend URL?

Answer: `http://127.0.0.1:8000`

## 3. Products API
What URL returns your products?

Answer: `GET /api/products/`

## 4. Product Details
What URL is used to get one product?

Answer: `GET /api/products/<slug-or-uuid>/`

Example: `GET /api/products/luna-silk-dress/`

## 5. Search
What URL/endpoint searches products?

Answer: `GET /api/products/?search=dress`

The repository implementation reads the `search` query parameter in the product list view and filters product names, descriptions, and taglines.

## 6. Cart
What endpoint adds an item to the cart?

Answer: `POST /api/cart/items`

The frontend client sends a JSON payload like `{ "variantId": "<uuid>", "quantity": 1 }` to that route.

## 7. View Cart
What endpoint gets the current cart?

Answer: `GET /api/cart`

The cart id is carried by the `x-cart-id` header, and the response includes the `x-cart-id` header back to the client.

## 8. Authentication
Does a customer need to log in before using the cart/checkout?

Answer: `No login required`

This project exposes cart endpoints with `authentication_classes = []` and `permission_classes = []` in the cart views, and checkout/order creation accepts an anonymous request.

## 9. Login API
If login is required, what is the login endpoint?

Answer: `Not required for cart/checkout; no explicit login endpoint is wired in the Django API.`

The installed auth stack supports `SessionAuthentication` and a custom Supabase JWT authentication class in the settings file. The frontend also pulls a Supabase access token from Supabase session data and attaches it as a Bearer token when available.

## 10. Checkout
What is your checkout endpoint?

Answer: `POST /api/orders`

Exact request body shape that the backend order service consumes is:

```json
{
  "customer": {
    "fullName": "Ada Lovelace",
    "email": "ada@example.com",
    "phone": "0712345678",
    "addressLine1": "1 Market Street",
    "addressLine2": "",
    "city": "Nairobi",
    "county": "Nairobi",
    "postalCode": "00100",
    "deliveryInstructions": ""
  },
  "shippingMethod": "standard",
  "paymentMethod": "mpesa",
  "notes": ""
}
```

The order creation view reads this payload in the `create_order()` service and writes it into the `Order` model using the `customer`, `shipping_method`, and `payment_method` fields. The request also requires the `x-cart-id` header to identify the cart that owns the order.

## 11. Payment
Which payment system do you use?

Answer: `M-Pesa`

The order model defaults to `payment_method = 'mpesa'`, and the payment route set includes `payments/create-intent`, `payments/confirm`, `payments/webhook`, and `payments/mpesa/callback`.

## 12. Payment Testing
Do you have a sandbox/test mode?

Answer: `Yes`

The repository contains M-Pesa callback and webhook secret values and a local development metadata mode (`mode: 'local-development'`) in the payment creation service.

## 13. Database
Which database does Django use?

Answer: `SQLite`

The settings file configures Django’s database engine as `django.db.backends.sqlite3` using the local `db.sqlite3` file.

## 14. Product IDs
Give me 3–5 example product IDs or slugs.

Answer:

`e3c84a62-f0ce-4967-bb1c-f3c26b3efef5`, `4212ad99-eb63-4bd2-aeb8-a721ab0dddb2`, `7f1a8f82-2e04-4c3d-93e3-73131686b735`, `2f6c7c37-6061-47d9-b8ff-88ca9376f9e7`, `aa70a06e-0885-4c1c-bdc3-5ce91527917c`

or, using the slugs visible in the database:

`luna-silk-dress`, `luna-silk-slip-dress`, `silk-midi-wrap-dress-tt`, `test-product`, `urban-cartoon-street-style`

## 15. Test Environment
Where will you run the test?

Answer: `My local computer`

## 16. Main Goal
What do you want to prove?

Answer: `All of the above`

The repository is designed for browsing, product carting, and reaching checkout/order creation, with payment intent and M-Pesa callback support configured.

## 17. Extra
Anything else about your application that I should know?

Answer:

This app uses a Django REST API routed under `/api/` and a Vite/Express React storefront mounted locally at `http://127.0.0.1:3000`. It supports product browsing with category and search filters, cart persistence via the `x-cart-id` header, and order creation through `POST /api/orders` with a payload shaped like:

```json
{
  "customer": {
    "fullName": "Ada Lovelace",
    "email": "ada@example.com",
    "phone": "0712345678",
    "addressLine1": "1 Market Street",
    "city": "Nairobi",
    "county": "Nairobi"
  },
  "shippingMethod": "standard",
  "paymentMethod": "mpesa",
  "notes": ""
}
```

Payment confirmation is done through `POST /api/payments/create-intent` and `POST /api/payments/confirm`. Authentication is mostly optional for the storefront cart and order flow, but the backend also supports Supabase JWT authentication in the DRF settings.

---

## 18. Load Testing Configuration

### Background

The backend uses Django REST Framework's built-in throttling (AnonRateThrottle, UserRateThrottle, ScopedRateThrottle) with production defaults:

| Scope    | Production Rate |
|----------|-----------------|
| anon     | 60/minute       |
| user     | 120/minute      |
| orders   | 20/minute       |
| payments | 10/minute       |
| admin    | 60/minute       |

In production, these limits protect against abuse. During load testing, all k6 virtual users share one IP address (`127.0.0.1`), so the per-IP limits are exhausted almost immediately, causing HTTP 429 responses.

### Load-Test Mode

Set the `LOAD_TEST_MODE` environment variable to `true` before starting Django:

```powershell
$env:LOAD_TEST_MODE="true"
cd backend
python manage.py runserver 127.0.0.1:8000
```

This raises the throttle budgets to levels that tolerate a 500-VU k6 run. The throttle classes remain active (no feature is disabled), but the per-IP counters are large enough that a local multi-VU run is not throttled.

| Scope    | Load-Test Rate |
|----------|----------------|
| anon     | 100000/minute  |
| user     | 100000/minute  |
| orders   | 60000/minute   |
| payments | 30000/minute   |
| admin    | 60000/minute   |

Each rate can be overridden individually via environment variables:

```
LOAD_TEST_ANON_RATE=200000/minute
THROTTLE_ORDERS_RATE=100/minute   # always works, even in production mode
```

### To Run in Production Mode

Simply omit `LOAD_TEST_MODE`:

```powershell
cd backend
python manage.py runserver 127.0.0.1:8000
```

Or explicitly:

```powershell
$env:LOAD_TEST_MODE="false"
cd backend
python manage.py runserver 127.0.0.1:8000
```

### Running the k6 Test

The k6 script is located at `Desktop\load_test\boutique-500-users.js`.

**Quick smoke test (recommended before a full run):**

```powershell
& "C:\Program Files\k6\k6.exe" run -e VUS=1 -e DURATION=2m "C:\Users\LENOVO T460s\Desktop\load_test\boutique-500-users.js"
```

**Progressive tests (recommended sequence):**

```powershell
k6 run -e VUS=1   -e DURATION=1m   boutique-500-users.js
k6 run -e VUS=10  -e DURATION=2m   boutique-500-users.js
k6 run -e VUS=25  -e DURATION=2m   boutique-500-users.js
k6 run -e VUS=50  -e DURATION=2m   boutique-500-users.js
k6 run -e VUS=100 -e DURATION=5m   boutique-500-users.js
k6 run -e VUS=250 -e DURATION=10m  boutique-500-users.js
k6 run -e VUS=500                  boutique-500-users.js
```

**Key options:**

| Variable          | Default | Description                                       |
|-------------------|---------|---------------------------------------------------|
| `VUS`             | `500`   | Number of concurrent virtual users                |
| `DURATION`        | `15m30s`| Total test duration                               |
| `CHECKOUT_DRY_RUN`| `true`  | Skip order creation (safe by default)             |
| `INCLUDE_FRONTEND`| `false` | Include requests to `http://127.0.0.1:3000`       |
| `API`             | `http://127.0.0.1:8000` | Backend base URL                  |
|-------------------|---------|---------------------------------------------------|

### Current Database Inventory

Only 4 of 6 active products have variants; the test uses these for add-to-cart:

| Product Slug            | Variant UUID                             | Stock |
|-------------------------|------------------------------------------|-------|
| silk-midi-wrap-dress-tt | `9d7721b0-a960-4288-a08d-fd955a355c49` | 8     |
| test-product            | `4448c83f-9d12-4808-80ca-0fd168786ab1` | 75    |
| urban-cartoon-street-style | `3626daae-ac0c-46c0-94d7-fcb08af65664` | 86   |
| silk-midi-wrap-dress    | `d5598e1e-a490-4fa8-b8d7-fedfa5df53aa` | 13    |
| silk-midi-wrap-dress    | `9cf5a094-d48e-4665-94fd-7e3d7a964234` | 12    |
|-------------------|---------|---------------------------------------------------|

With `CHECKOUT_DRY_RUN=true` (default), stock is not reserved, so cart operations remain stable for the full test duration.

## 19. Promotion-heavy traffic (k6)

The promotions engine adds three storefront endpoints plus heavier cart
pricing (one extra promotion query per `GET /api/cart`). Extend the k6
script (`boutique-500-users.js`) with these scenarios; all share the
`x-cart-id` header flow and run under `LOAD_TEST_MODE=true` so the
`orders`-scoped throttle (coupon apply/remove) does not 429 the run:

| # | Scenario | Requests | What it proves |
|---|---|---|---|
| 1 | Browse with active promos | `GET /api/products/` + `GET /api/promotions/available` | discovery payload stays small; product list p95 unaffected |
| 2 | Cart pricing | `POST /api/cart/items` → `GET /api/cart` | `discount/promotion/appliedPromotions` computed per GET without N+1 |
| 3 | Coupon apply | `POST /api/promotions/apply {code}` (valid + invalid codes) | validation errors return 422 with stable `{error:{code,message}}` envelope |
| 4 | Checkout with promotion | `POST /api/orders {couponCode}` → `POST /api/payments/create-intent` | order total = subtotal − discount + shipping + tax; intent amount matches |
| 5 | Concurrent redemption | N VUs `POST /api/orders {couponCode}` against a `usage_limit=1` promo | exactly 1 order succeeds; rest get `USAGE_LIMIT_REACHED` (row-locked) |

Seed a coupon promo before the run (Django shell or admin API):

```python
from decimal import Decimal
from promotions.models import Promotion
Promotion.objects.create(name='Load Test 10%', promotion_type='percentage',
    status='active', discount_percent=Decimal('10'), coupon_code='LOAD10',
    priority=10, stackable=True)
```

Ramp with the same progressive sequence as §18 (`VUS=1/10/25/50/100/250/500`);
compare cart/checkout p95 against the no-promo baseline — the engine is
`select_related`/`prefetch_related`-backed and must not regress p95 by more
than ~10%.
