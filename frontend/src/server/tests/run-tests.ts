import { createExpressApp } from '../app';
import { db } from '../db/database';
import { AddressInfo } from 'net';
import { hasPrivilegedAppRole } from '../middleware/auth.middleware';

interface TestResult {
  suite: string;
  name: string;
  passed: boolean;
  error?: string;
}

const results: TestResult[] = [];

function assert(condition: boolean, message: string) {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

async function run() {
  console.log('🧪 Starting Backend API Automated Test Suite...\n');
  const app = createExpressApp();

  const server = app.listen(0);
  const port = (server.address() as AddressInfo).port;
  const baseUrl = `http://127.0.0.1:${port}`;

  async function test(suite: string, name: string, fn: () => Promise<void>) {
    // Reset database before each test
    db.seed();
    try {
      await fn();
      results.push({ suite, name, passed: true });
      console.log(`  ✓ [${suite}] ${name}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      results.push({ suite, name, passed: false, error: msg });
      console.error(`  ✗ [${suite}] ${name}`);
      console.error(`    -> ${msg}`);
    }
  }

  try {
    // ==========================================
    // 1. PRODUCT TESTS
    // ==========================================
    await test('Products', 'GET /api/products returns publicly active products with pagination', async () => {
      const res = await fetch(`${baseUrl}/api/products?page=1&limit=10`);
      assert(res.status === 200, `Expected 200, got ${res.status}`);
      const json = await res.json();
      assert(Array.isArray(json.data), 'Expected json.data array');
      assert(json.pagination.page === 1, 'Expected page 1');
      assert(json.data.length > 0, 'Expected products to be returned');
      // Verify inactive/draft products are NOT returned in public list
      const draft = json.data.find((p: { status: string }) => p.status === 'DRAFT');
      const archived = json.data.find((p: { status: string }) => p.status === 'ARCHIVED');
      assert(!draft, 'Draft product should not be publicly returned');
      assert(!archived, 'Archived product should not be publicly returned');
    });

    await test('Products', 'GET /api/products supports category filtering and sort whitelist', async () => {
      const res = await fetch(`${baseUrl}/api/products?category=dresses&sort=price_asc`);
      assert(res.status === 200, `Expected 200, got ${res.status}`);
      const json = await res.json();
      assert(json.data.length >= 1, 'Expected at least 1 dress');
      assert(json.data[0].category.slug === 'dresses', 'Expected category dresses');
    });

    await test('Products', 'GET /api/products rejects invalid sort parameter', async () => {
      const res = await fetch(`${baseUrl}/api/products?sort=malicious_column`);
      assert(res.status === 400, `Expected 400, got ${res.status}`);
      const json = await res.json();
      assert(json.error.code === 'VALIDATION_ERROR', 'Expected VALIDATION_ERROR');
    });

    await test('Products', 'GET /api/products/:id returns single active product and 404 for missing', async () => {
      const resFound = await fetch(`${baseUrl}/api/products/prod-1`);
      assert(resFound.status === 200, `Expected 200, got ${resFound.status}`);
      const prod = await resFound.json();
      assert(prod.id === 'prod-1', 'Expected prod-1');
      assert(Array.isArray(prod.variants), 'Expected variants array');
      assert(prod.price === 24500, 'Expected major currency price 24500');

      const resMissing = await fetch(`${baseUrl}/api/products/non-existent-id`);
      assert(resMissing.status === 404, `Expected 404, got ${resMissing.status}`);
    });

    await test('Products', 'Public cannot access draft or archived product via /api/products/:id', async () => {
      const resDraft = await fetch(`${baseUrl}/api/products/prod-draft-sample`);
      assert(resDraft.status === 404, `Expected 404 for draft product, got ${resDraft.status}`);

      const resArchived = await fetch(`${baseUrl}/api/products/prod-archived-sample`);
      assert(resArchived.status === 404, `Expected 404 for archived product, got ${resArchived.status}`);
    });

    // ==========================================
    // 2. CATEGORY TESTS
    // ==========================================
    await test('Categories', 'GET /api/categories returns active categories only', async () => {
      const res = await fetch(`${baseUrl}/api/categories`);
      assert(res.status === 200, `Expected 200, got ${res.status}`);
      const json = await res.json();
      assert(Array.isArray(json), 'Expected category array');
      const inactive = json.find((c: { isActive: boolean }) => !c.isActive);
      assert(!inactive, 'Inactive category must not appear in public categories');
    });

    await test('Categories', 'GET /api/categories/:slug returns category and its active products', async () => {
      const res = await fetch(`${baseUrl}/api/categories/dresses`);
      assert(res.status === 200, `Expected 200, got ${res.status}`);
      const json = await res.json();
      assert(json.category.slug === 'dresses', 'Expected dresses slug');
      assert(Array.isArray(json.products), 'Expected products list');

      const resInvalid = await fetch(`${baseUrl}/api/categories/non-existent-category`);
      assert(resInvalid.status === 404, `Expected 404, got ${resInvalid.status}`);
    });

    // ==========================================
    // 3. PRICING & INVENTORY TESTS
    // ==========================================
    await test('Pricing', 'Authoritative price respects variant overrides vs product base price', async () => {
      // prod-2 has base price 48500
      // v-2-s has no override -> price 48500
      // v-2-m has variant price 51000 override
      const prodRes = await fetch(`${baseUrl}/api/products/prod-2`);
      const prod = await prodRes.json();
      const variantS = prod.variants.find((v: { id: string }) => v.id === 'v-2-s');
      const variantM = prod.variants.find((v: { id: string }) => v.id === 'v-2-m');
      assert(variantS.price === 48500, `Expected 48500 for variant S, got ${variantS.price}`);
      assert(variantM.price === 51000, `Expected 51000 for variant M, got ${variantM.price}`);
    });

    // ==========================================
    // 4. CART TESTS
    // ==========================================
    await test('Cart', 'Initial cart is empty and returns server-calculated zero subtotal', async () => {
      const res = await fetch(`${baseUrl}/api/cart`, {
        headers: { 'x-cart-id': 'test-cart-session-1' },
      });
      assert(res.status === 200, `Expected 200, got ${res.status}`);
      const cart = await res.json();
      assert(cart.items.length === 0, 'Cart should start empty');
      assert(cart.subtotal === 0, 'Subtotal should be 0');
      assert(cart.itemCount === 0, 'Item count should be 0');
    });

    await test('Cart', 'POST /api/cart/items adds item, ignores client pricing, computes authoritative subtotal', async () => {
      const res = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-cart-id': 'test-cart-session-2',
        },
        body: JSON.stringify({
          variantId: 'v-1-s', // 24,500.00 KES
          quantity: 2,
          // Attempted client price manipulation: must be ignored by server!
          price: 1.0,
          subtotal: 2.0,
        }),
      });

      assert(res.status === 201, `Expected 201, got ${res.status}`);
      const cart = await res.json();
      assert(cart.items.length === 1, 'Expected 1 item in cart');
      assert(cart.items[0].quantity === 2, 'Expected quantity 2');
      assert(cart.items[0].unitPrice === 24500, `Expected unitPrice 24500, got ${cart.items[0].unitPrice}`);
      assert(cart.items[0].lineTotal === 49000, `Expected lineTotal 49000, got ${cart.items[0].lineTotal}`);
      assert(cart.subtotal === 49000, `Expected subtotal 49000, got ${cart.subtotal}`);
      assert(cart.itemCount === 2, 'Expected itemCount 2');
    });

    await test('Cart', 'POST /api/cart/items adding same variant increments existing cart item quantity', async () => {
      const headers = {
        'Content-Type': 'application/json',
        'x-cart-id': 'test-cart-session-3',
      };

      await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 1 }),
      });

      const resSecond = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 2 }),
      });

      assert(resSecond.status === 201, `Expected 201, got ${resSecond.status}`);
      const cart = await resSecond.json();
      assert(cart.items.length === 1, 'Expected single combined line item');
      assert(cart.items[0].quantity === 3, 'Expected quantity 3');
      assert(cart.subtotal === 73500, `Expected subtotal 73500, got ${cart.subtotal}`);
    });

    await test('Cart', 'POST /api/cart/items rejects invalid variant and inactive variant', async () => {
      const headers = { 'Content-Type': 'application/json', 'x-cart-id': 'test-cart-session-4' };

      // Missing variant
      const resMissing = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'non-existent-var', quantity: 1 }),
      });
      assert(resMissing.status === 404, `Expected 404, got ${resMissing.status}`);

      // Inactive variant
      const resInactive = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-inactive', quantity: 1 }),
      });
      assert(resInactive.status === 400, `Expected 400, got ${resInactive.status}`);
      const jsonInactive = await resInactive.json();
      assert(jsonInactive.error.code === 'VARIANT_UNAVAILABLE', 'Expected VARIANT_UNAVAILABLE');
    });

    await test('Cart', 'POST /api/cart/items rejects quantity exceeding available stock with 409 Conflict', async () => {
      const headers = { 'Content-Type': 'application/json', 'x-cart-id': 'test-cart-session-5' };
      // v-1-s has stockQuantity = 8; requesting 12 exceeds stock
      const resExceeded = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 12 }),
      });

      assert(resExceeded.status === 409, `Expected 409 Conflict, got ${resExceeded.status}`);
      const json = await resExceeded.json();
      assert(json.error.code === 'INSUFFICIENT_STOCK', `Expected INSUFFICIENT_STOCK, got ${json.error.code}`);
    });

    await test('Cart', 'Validation: Rejects negative, zero, or non-integer quantities with 400 Bad Request', async () => {
      const headers = { 'Content-Type': 'application/json', 'x-cart-id': 'test-cart-session-6' };

      const resZero = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 0 }),
      });
      assert(resZero.status === 400, `Expected 400 for zero quantity, got ${resZero.status}`);

      const resNeg = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: -5 }),
      });
      assert(resNeg.status === 400, `Expected 400 for negative quantity, got ${resNeg.status}`);

      const resFloat = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 1.5 }),
      });
      assert(resFloat.status === 400, `Expected 400 for float quantity, got ${resFloat.status}`);
    });

    await test('Cart', 'PATCH /api/cart/items/:itemId updates quantity and recalculates totals', async () => {
      const headers = { 'Content-Type': 'application/json', 'x-cart-id': 'test-cart-session-7' };

      const addRes = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 1 }),
      });
      const cart = await addRes.json();
      const itemId = cart.items[0].id;

      const patchRes = await fetch(`${baseUrl}/api/cart/items/${itemId}`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ quantity: 4 }),
      });

      assert(patchRes.status === 200, `Expected 200, got ${patchRes.status}`);
      const updatedCart = await patchRes.json();
      assert(updatedCart.items[0].quantity === 4, 'Expected quantity 4');
      assert(updatedCart.subtotal === 98000, `Expected subtotal 98000 (24500 * 4), got ${updatedCart.subtotal}`);
    });

    await test('Cart', 'DELETE /api/cart/items/:itemId removes item and recalculates totals', async () => {
      const headers = { 'Content-Type': 'application/json', 'x-cart-id': 'test-cart-session-8' };

      const addRes = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 2 }),
      });
      const cart = await addRes.json();
      const itemId = cart.items[0].id;

      const deleteRes = await fetch(`${baseUrl}/api/cart/items/${itemId}`, {
        method: 'DELETE',
        headers,
      });

      assert(deleteRes.status === 200, `Expected 200, got ${deleteRes.status}`);
      const updatedCart = await deleteRes.json();
      assert(updatedCart.items.length === 0, 'Expected cart to be empty');
      assert(updatedCart.subtotal === 0, 'Expected subtotal 0');
    });

    // ==========================================
    // 5. SECURITY & AUTHORIZATION TESTS
    // ==========================================
    await test('Security', 'Cart ownership enforcement: User A cannot modify or delete User B cart item', async () => {
      // User A adds an item
      const addRes = await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-cart-id': 'user-a-cart-session',
        },
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 1 }),
      });
      const cartA = await addRes.json();
      const itemAId = cartA.items[0].id;

      // User B attempts to tamper with User A's item
      const tamperPatchRes = await fetch(`${baseUrl}/api/cart/items/${itemAId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'x-cart-id': 'user-b-cart-session', // Different cart session!
        },
        body: JSON.stringify({ quantity: 5 }),
      });
      assert(tamperPatchRes.status === 404, `Expected 404 Not Found for unauthorized cart modification, got ${tamperPatchRes.status}`);

      const tamperDeleteRes = await fetch(`${baseUrl}/api/cart/items/${itemAId}`, {
        method: 'DELETE',
        headers: {
          'x-cart-id': 'user-b-cart-session',
        },
      });
      assert(tamperDeleteRes.status === 404, `Expected 404 Not Found for unauthorized cart deletion, got ${tamperDeleteRes.status}`);
    });

    await test('Security', 'Admin authorization reads privileged roles only from trusted app metadata', async () => {
      assert(!hasPrivilegedAppRole(undefined), 'A role in user-editable metadata must not grant admin access');
      assert(!hasPrivilegedAppRole(null), 'Missing app metadata must not grant admin access');
      assert(!hasPrivilegedAppRole({ role: 'customer' }), 'Customer app metadata must not grant admin access');
      assert(hasPrivilegedAppRole({ role: 'staff' }), 'Trusted staff role should be accepted');
      assert(hasPrivilegedAppRole({ role: 'admin' }), 'Trusted admin role should be accepted');
    });

    await test('Security', 'Admin operations reject unauthenticated or invalid bearer tokens with 401 Unauthorized', async () => {
      const resNoAuth = await fetch(`${baseUrl}/api/admin/products`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: 'Unauthorized Cape',
          slug: 'unauthorized-cape',
          description: 'Hacker created item',
          price: 100,
          categoryId: 'cat-outerwear',
        }),
      });
      assert(resNoAuth.status === 401, `Expected 401, got ${resNoAuth.status}`);

      const resBadToken = await fetch(`${baseUrl}/api/admin/products`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer wrong-secret-token',
        },
        body: JSON.stringify({
          name: 'Unauthorized Cape',
          slug: 'unauthorized-cape',
          description: 'Hacker created item',
          price: 100,
          categoryId: 'cat-outerwear',
        }),
      });
      assert(resBadToken.status === 401, `Expected 401, got ${resBadToken.status}`);
    });

    await test('Security', 'Admin can create product when authorized with valid Bearer token', async () => {
      const previousToken = process.env.ADMIN_API_TOKEN;
      const testToken = `test-admin-token-${Date.now()}-${Math.random()}`;
      process.env.ADMIN_API_TOKEN = testToken;
      try {
        const res = await fetch(`${baseUrl}/api/admin/products`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${testToken}`,
          },
          body: JSON.stringify({
            name: 'The Organic Linen Oversized Shirt',
            slug: 'the-organic-linen-oversized-shirt',
            description: 'Breathable 100% Normandy flax linen tailored with dropped shoulder silhouette.',
            price: 16500,
            categoryId: 'cat-tops',
            status: 'ACTIVE',
          }),
        });

        assert(res.status === 201, `Expected 201, got ${res.status}`);
        const created = await res.json();
        assert(created.name === 'The Organic Linen Oversized Shirt', 'Expected correct product name');
        assert(created.price === 16500, 'Expected correct price');
      } finally {
        if (previousToken === undefined) delete process.env.ADMIN_API_TOKEN;
        else process.env.ADMIN_API_TOKEN = previousToken;
      }
    });

    // ==========================================
    // 6. ORDER CREATION & INVENTORY DECREMENT TESTS
    // ==========================================
    await test('Orders', 'POST /api/orders rejects order if cart is empty', async () => {
      const res = await fetch(`${baseUrl}/api/orders`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-cart-id': 'empty-cart-order-test',
        },
        body: JSON.stringify({
          customer: {
            fullName: 'Amina Kimani',
            email: 'amina.kimani@example.com',
            phone: '+254712345678',
            addressLine1: 'Riverside Drive, Penthouse 4B',
            city: 'Nairobi',
            county: 'Nairobi',
          },
          shippingMethod: 'standard',
          paymentMethod: 'mpesa',
        }),
      });

      assert(res.status === 400, `Expected 400, got ${res.status}`);
      const json = await res.json();
      assert(json.error.code === 'EMPTY_CART', 'Expected EMPTY_CART code');
    });

    await test('Orders', 'POST /api/orders creates order, decrements stock atomically, and clears cart', async () => {
      const cartHeaders = {
        'Content-Type': 'application/json',
        'x-cart-id': 'active-order-test-cart',
      };

      // 1. Add 2 units of v-1-s (stock starts at 8)
      await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 2 }),
      });

      // 2. Place Order
      const orderRes = await fetch(`${baseUrl}/api/orders`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({
          customer: {
            fullName: 'Zainab Noor',
            email: 'zainab.noor@modeza.co.ke',
            phone: '+254722998877',
            addressLine1: 'Karen Blixen Lane, Villa 12',
            city: 'Nairobi',
            county: 'Nairobi',
          },
          shippingMethod: 'standard',
          paymentMethod: 'mpesa',
        }),
      });

      assert(orderRes.status === 201, `Expected 201, got ${orderRes.status}`);
      const order = await orderRes.json();
      assert(order.orderNumber.startsWith('ATL-'), 'Expected ATL- order number prefix');
      assert(order.items.length === 1, 'Expected 1 line item');
      assert(order.items[0].quantity === 2, 'Expected quantity 2');
      assert(order.subtotal === 49000, `Expected subtotal 49000, got ${order.subtotal}`);
      assert(order.shippingCost === 0, 'Expected free shipping since subtotal >= 30,000 KES');
      assert(order.total === 49000, `Expected total 49000, got ${order.total}`);
      assert(order.status === 'pending', 'Expected initial status pending');

      // 3. Verify stock was decremented in database (8 - 2 = 6)
      const prodRes = await fetch(`${baseUrl}/api/products/prod-1`);
      const prod = await prodRes.json();
      const variant = prod.variants.find((v: { id: string }) => v.id === 'v-1-s');
      assert(variant.stockQuantity === 6, `Expected variant stock 6, got ${variant.stockQuantity}`);

      // 4. Verify cart was cleared
      const cartRes = await fetch(`${baseUrl}/api/cart`, { headers: cartHeaders });
      const cart = await cartRes.json();
      assert(cart.items.length === 0, 'Cart should be cleared after order');
    });

    await test('Orders', 'GET /api/orders/:orderNumber retrieves authoritative order details', async () => {
      const cartHeaders = {
        'Content-Type': 'application/json',
        'x-cart-id': 'fetch-order-test-cart',
      };

      await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({ variantId: 'v-1-xs', quantity: 1 }),
      });

      const createRes = await fetch(`${baseUrl}/api/orders`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({
          customer: {
            fullName: 'Lian Mwangi',
            email: 'lian.mwangi@example.com',
            phone: '+254700112233',
            addressLine1: '14 Riverside, Suite 100',
            city: 'Nairobi',
            county: 'Nairobi',
          },
          shippingMethod: 'express',
          paymentMethod: 'card',
        }),
      });
      const createdOrder = await createRes.json();

      const getRes = await fetch(`${baseUrl}/api/orders/${createdOrder.orderNumber}`);
      assert(getRes.status === 200, `Expected 200, got ${getRes.status}`);
      const retrieved = await getRes.json();
      assert(retrieved.orderNumber === createdOrder.orderNumber, 'Order numbers should match');
      assert(retrieved.shippingMethod === 'express', 'Expected express shipping');
      assert(retrieved.shippingCost === 1200, 'Expected express shipping cost 1200');
    });

    await test('Orders', 'POST /api/orders/:orderNumber/cancel restocks variant inventory', async () => {
      const cartHeaders = {
        'Content-Type': 'application/json',
        'x-cart-id': 'cancel-order-test-cart',
      };

      // v-1-s stock is 8
      await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({ variantId: 'v-1-s', quantity: 3 }),
      });

      const createRes = await fetch(`${baseUrl}/api/orders`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({
          customer: {
            fullName: 'Tariq Al-Mansoor',
            email: 'tariq@example.com',
            phone: '+254799887766',
            addressLine1: 'Loresho Ridge, Gate 5',
            city: 'Nairobi',
            county: 'Nairobi',
          },
        }),
      });
      const createdOrder = await createRes.json();

      // Cancel order
      const cancelRes = await fetch(`${baseUrl}/api/orders/${createdOrder.orderNumber}/cancel`, {
        method: 'POST',
      });
      assert(cancelRes.status === 200, `Expected 200, got ${cancelRes.status}`);
      const cancelled = await cancelRes.json();
      assert(cancelled.status === 'cancelled', 'Expected cancelled status');

      // Verify stock was restored to 8
      const prodRes = await fetch(`${baseUrl}/api/products/prod-1`);
      const prod = await prodRes.json();
      const variant = prod.variants.find((v: { id: string }) => v.id === 'v-1-s');
      assert(variant.stockQuantity === 8, `Expected variant stock restored to 8, got ${variant.stockQuantity}`);
    });

    // ==========================================
    // 7. PAYMENT GATEWAY & WEBHOOK INTEGRATION TESTS
    // ==========================================
    await test('Payments', 'POST /api/payments/create-intent generates authoritative intent', async () => {
      const cartHeaders = { 'Content-Type': 'application/json', 'x-cart-id': 'pay-intent-cart' };
      await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({ variantId: 'v-1-xs', quantity: 1 }),
      });

      const orderRes = await fetch(`${baseUrl}/api/orders`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({
          customer: {
            fullName: 'Elena Rostova',
            email: 'elena@modeza.co.ke',
            phone: '+254711223344',
            addressLine1: 'Gigiri Crescent 42',
            city: 'Nairobi',
            county: 'Nairobi',
          },
        }),
      });
      const order = await orderRes.json();

      const intentRes = await fetch(`${baseUrl}/api/payments/create-intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          orderNumber: order.orderNumber,
          method: 'mpesa',
          phoneNumber: '+254711223344',
        }),
      });

      assert(intentRes.status === 201, `Expected 201, got ${intentRes.status}`);
      const intent = await intentRes.json();
      assert(intent.orderNumber === order.orderNumber, 'Expected matching orderNumber');
      assert(intent.amount === order.total, `Expected intent amount ${order.total}, got ${intent.amount}`);
      assert(intent.clientSecret.startsWith('cs_'), 'Expected clientSecret');
    });

    await test('Payments', 'POST /api/payments/confirm updates payment and order status to paid', async () => {
      const cartHeaders = { 'Content-Type': 'application/json', 'x-cart-id': 'pay-confirm-cart' };
      await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({ variantId: 'v-1-xs', quantity: 1 }),
      });

      const orderRes = await fetch(`${baseUrl}/api/orders`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({
          customer: {
            fullName: 'Elena Rostova',
            email: 'elena@modeza.co.ke',
            phone: '+254711223344',
            addressLine1: 'Gigiri Crescent 42',
            city: 'Nairobi',
            county: 'Nairobi',
          },
        }),
      });
      const order = await orderRes.json();

      const intentRes = await fetch(`${baseUrl}/api/payments/create-intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          orderNumber: order.orderNumber,
          method: 'card',
        }),
      });
      const intent = await intentRes.json();

      const confirmRes = await fetch(`${baseUrl}/api/payments/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          orderNumber: order.orderNumber,
          paymentIntentId: intent.id,
          gatewayReference: 'STRIPE-CHG-998811',
        }),
      });

      assert(confirmRes.status === 200, `Expected 200, got ${confirmRes.status}`);
      const paidOrder = await confirmRes.json();
      assert(paidOrder.paymentStatus === 'paid', 'Expected paymentStatus paid');
      assert(paidOrder.status === 'confirmed', 'Expected order status confirmed');
    });

    await test('Payments', 'POST /api/payments/webhook enforces signature and updates order status', async () => {
      const cartHeaders = { 'Content-Type': 'application/json', 'x-cart-id': 'pay-webhook-cart' };
      await fetch(`${baseUrl}/api/cart/items`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({ variantId: 'v-1-xs', quantity: 1 }),
      });

      const orderRes = await fetch(`${baseUrl}/api/orders`, {
        method: 'POST',
        headers: cartHeaders,
        body: JSON.stringify({
          customer: {
            fullName: 'Kofi Mensah',
            email: 'kofi@example.com',
            phone: '+254700998877',
            addressLine1: 'Muthaiga Park, Villa 8',
            city: 'Nairobi',
            county: 'Nairobi',
          },
        }),
      });
      const order = await orderRes.json();

      // 1. Invalid signature should be rejected with 401
      const invalidWebhookRes = await fetch(`${baseUrl}/api/payments/webhook`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-webhook-signature': 'forged-signature',
        },
        body: JSON.stringify({
          event: 'mpesa.stk_callback.success',
          data: {
            orderNumber: order.orderNumber,
            transactionId: 'MPESA-QRT77881',
          },
        }),
      });
      assert(invalidWebhookRes.status === 401, `Expected 401 for invalid signature, got ${invalidWebhookRes.status}`);

      // 2. Valid signature succeeds and marks order as paid
      const validWebhookRes = await fetch(`${baseUrl}/api/payments/webhook`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-webhook-signature': 'modeza_webhook_secret_2026',
        },
        body: JSON.stringify({
          event: 'mpesa.stk_callback.success',
          data: {
            orderNumber: order.orderNumber,
            transactionId: 'MPESA-QRT77881',
          },
        }),
      });

      assert(validWebhookRes.status === 200, `Expected 200, got ${validWebhookRes.status}`);
      const webhookResponse = await validWebhookRes.json();
      assert(webhookResponse.status === 'order_marked_paid', 'Expected order_marked_paid status');

      // Verify order is now marked paid
      const updatedOrderRes = await fetch(`${baseUrl}/api/orders/${order.orderNumber}`);
      const updatedOrder = await updatedOrderRes.json();
      assert(updatedOrder.paymentStatus === 'paid', 'Expected paymentStatus paid');
      assert(updatedOrder.status === 'confirmed', 'Expected status confirmed');
    });
  } finally {
    server.close();
  }

  // Summary
  const passedCount = results.filter((r) => r.passed).length;
  const failedCount = results.filter((r) => !r.passed).length;

  console.log('\n========================================');
  console.log(`Test Execution Summary:`);
  console.log(`  Total:  ${results.length}`);
  console.log(`  Passed: ${passedCount}`);
  console.log(`  Failed: ${failedCount}`);
  console.log('========================================\n');

  if (failedCount > 0) {
    process.exit(1);
  }
}

run().catch((err) => {
  console.error('Fatal test runner failure:', err);
  process.exit(1);
});
