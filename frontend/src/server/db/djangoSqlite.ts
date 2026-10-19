import fs from 'node:fs';
import path from 'node:path';
import { config } from '../config';
import { DatabaseSnapshot, db } from './database';
import {
  CategoryEntity,
  OrderEntity,
  OrderItemEntity,
  OrderStatus,
  PaymentMethod,
  PaymentStatus,
  ProductEntity,
  ProductStatus,
  ProductVariantEntity,
  ReservationStatus,
  ShippingAddressEntity,
  StockReservationEntity,
} from './types';

/**
 * Development-only bridge between the Django backend database (backend/db.sqlite3)
 * and the storefront API's in-memory data store.
 *
 * When NODE_ENV=development the catalog (categories, products, variants) plus the
 * order history and stock reservations are hydrated straight from the SQLite file
 * that the Django admin writes to, so local storefront data matches what was
 * created in the admin.
 *
 * The file is opened READ-ONLY and only in development: production builds
 * (Render/Vercel) never touch this module's work, so deployments keep using
 * their existing behaviour. Writes made through the storefront API stay in
 * memory for the lifetime of the dev server.
 */

type SqliteRow = Record<string, unknown>;

interface SqliteStatement {
  all(...params: unknown[]): SqliteRow[];
}

interface SqliteDatabase {
  prepare(sql: string): SqliteStatement;
  close(): void;
}

interface SqliteModule {
  DatabaseSync: new (
    filePath: string,
    options?: { readOnly?: boolean }
  ) => SqliteDatabase;
}

const PRODUCT_STATUSES: ProductStatus[] = ['DRAFT', 'ACTIVE', 'ARCHIVED'];
const ORDER_STATUSES: OrderStatus[] = [
  'pending',
  'confirmed',
  'processing',
  'shipped',
  'delivered',
  'received',
  'cancelled',
];
const PAYMENT_STATUSES: PaymentStatus[] = ['pending', 'paid', 'failed', 'refunded'];
const PAYMENT_METHODS: PaymentMethod[] = ['mpesa', 'card', 'cash_on_delivery', 'pay_on_delivery'];
const RESERVATION_STATUSES: ReservationStatus[] = ['active', 'committed', 'released', 'expired'];

/** SQLite hydration only runs while NODE_ENV is explicitly "development". */
export function isDjangoSqliteDevMode(): boolean {
  return config.NODE_ENV === 'development';
}

/** Locates backend/db.sqlite3 (or the path supplied via DJANGO_SQLITE_PATH). */
function resolveDatabasePath(): string | null {
  if (config.DJANGO_SQLITE_PATH) {
    const configured = path.resolve(process.cwd(), config.DJANGO_SQLITE_PATH);
    if (!fs.existsSync(configured)) {
      console.warn(
        `[dev-sqlite] DJANGO_SQLITE_PATH points to ${configured}, which does not exist. ` +
          'Falling back to the built-in seed catalog.'
      );
      return null;
    }
    return configured;
  }

  // Works whether the dev server is started from the repo root or from frontend/.
  const candidates = [
    path.resolve(process.cwd(), '../backend/db.sqlite3'),
    path.resolve(process.cwd(), 'backend/db.sqlite3'),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? null;
}

function getSqliteModule(): SqliteModule | undefined {
  const getBuiltinModule = (
    process as typeof process & {
      getBuiltinModule?: (id: string) => unknown;
    }
  ).getBuiltinModule;
  if (typeof getBuiltinModule !== 'function') return undefined;
  return getBuiltinModule('node:sqlite') as SqliteModule | undefined;
}

// --- Row helpers -----------------------------------------------------------

function asText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return '';
  return String(value);
}

function asNumber(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function asBool(value: unknown): boolean {
  return value === 1 || value === true || value === '1' || value === 'true';
}

function optionalText(value: unknown): string | undefined {
  const text = asText(value).trim();
  return text ? text : undefined;
}

/**
 * Django (USE_TZ=True) stores UTC timestamps in SQLite as
 * "YYYY-MM-DD HH:MM:SS[.ffffff]"; append the missing timezone marker.
 */
function parseDjangoDate(value: unknown, fallback: Date = new Date(0)): Date {
  if (value instanceof Date) return value;
  const raw = asText(value).trim();
  if (!raw) return fallback;
  const normalized = /^\d{4}-\d{2}-\d{2} /.test(raw) ? `${raw.replace(' ', 'T')}Z` : raw;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? fallback : parsed;
}

function parseJsonArray(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => asText(item).trim()).filter(Boolean);
  }
  const raw = asText(value).trim();
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map((item) => asText(item).trim()).filter(Boolean);
  } catch {
    return [];
  }
}

function parseJsonObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  const raw = asText(value).trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/** Resolves Django's relative /media/... paths against the backend origin. */
function resolveMediaUrl(value: unknown): string | undefined {
  const raw = asText(value).trim();
  if (!raw) return undefined;
  if (/^(https?:|data:)/i.test(raw)) return raw;
  const base = config.DJANGO_BASE_URL.replace(/\/+$/, '');
  return raw.startsWith('/') ? `${base}${raw}` : `${base}/${raw}`;
}

function toProductStatus(value: unknown, isActive: boolean): ProductStatus {
  const candidate = asText(value).trim().toUpperCase() as ProductStatus;
  const status = PRODUCT_STATUSES.includes(candidate) ? candidate : 'DRAFT';
  return !isActive && status === 'ACTIVE' ? 'ARCHIVED' : status;
}

function toOrderStatus(value: unknown): OrderStatus {
  const candidate = asText(value).trim().toLowerCase() as OrderStatus;
  return ORDER_STATUSES.includes(candidate) ? candidate : 'pending';
}

function toPaymentStatus(value: unknown): PaymentStatus {
  const candidate = asText(value).trim().toLowerCase() as PaymentStatus;
  return PAYMENT_STATUSES.includes(candidate) ? candidate : 'pending';
}

function toPaymentMethod(value: unknown): PaymentMethod {
  const candidate = asText(value).trim().toLowerCase() as PaymentMethod;
  return PAYMENT_METHODS.includes(candidate) ? candidate : 'mpesa';
}

function toReservationStatus(value: unknown): ReservationStatus {
  const candidate = asText(value).trim().toLowerCase() as ReservationStatus;
  return RESERVATION_STATUSES.includes(candidate) ? candidate : 'active';
}

function query(conn: SqliteDatabase, sql: string): SqliteRow[] {
  return conn.prepare(sql).all();
}

// --- Mapping ---------------------------------------------------------------

interface ProductSeedRow extends SqliteRow {
  sku?: unknown;
  size?: unknown;
  color?: unknown;
  stock_quantity?: unknown;
}

function mapCategories(conn: SqliteDatabase): CategoryEntity[] {
  const categories: CategoryEntity[] = [];
  const seenIds = new Set<string>();
  const seenSlugs = new Set<string>();

  for (const row of query(conn, `
    SELECT id, name, slug, description, image_url, is_active, created_at, updated_at
    FROM catalog_category
  `)) {
    const id = asText(row.id);
    const slug = asText(row.slug);
    if (!id || !slug || seenIds.has(id) || seenSlugs.has(slug)) continue;

    seenIds.add(id);
    seenSlugs.add(slug);
    categories.push({
      id,
      name: asText(row.name) || slug,
      slug,
      description: optionalText(row.description),
      imageUrl: resolveMediaUrl(row.image_url),
      isActive: asBool(row.is_active),
      createdAt: parseDjangoDate(row.created_at),
      updatedAt: parseDjangoDate(row.updated_at),
    });
  }

  return categories;
}

function mapProducts(
  conn: SqliteDatabase,
  categoryIds: Set<string>
): { products: ProductEntity[]; rowsById: Map<string, ProductSeedRow> } {
  const products: ProductEntity[] = [];
  const rowsById = new Map<string, ProductSeedRow>();
  const seenIds = new Set<string>();
  const seenSlugs = new Set<string>();

  for (const row of query(conn, `
    SELECT id, category_id, name, slug, tagline, description, details, price_minor,
           compare_at_price_minor, images, status, is_featured, is_new_arrival,
           is_best_seller, sku, size, color, stock_quantity, is_active,
           created_at, updated_at
    FROM catalog_product
  `) as ProductSeedRow[]) {
    const id = asText(row.id);
    const slug = asText(row.slug);
    const categoryId = asText(row.category_id);
    if (!id || !slug || !categoryId || seenIds.has(id) || seenSlugs.has(slug)) continue;
    if (!categoryIds.has(categoryId)) {
      console.warn(`[dev-sqlite] Skipping product '${slug}': category ${categoryId} is missing.`);
      continue;
    }

    const priceMinor = Math.max(0, Math.round(asNumber(row.price_minor)));
    let compareAtPriceMinor: number | undefined;
    if (row.compare_at_price_minor !== null && row.compare_at_price_minor !== undefined) {
      const compareAt = Math.round(asNumber(row.compare_at_price_minor, -1));
      // The store enforces compare-at > price, so drop values that would violate it.
      if (compareAt > priceMinor) compareAtPriceMinor = compareAt;
    }

    const images = parseJsonArray(row.images)
      .map((image) => resolveMediaUrl(image))
      .filter((image): image is string => Boolean(image));

    seenIds.add(id);
    seenSlugs.add(slug);
    rowsById.set(id, row);
    products.push({
      id,
      name: asText(row.name) || slug,
      slug,
      description: asText(row.description),
      tagline: optionalText(row.tagline),
      details: parseJsonArray(row.details),
      priceMinor,
      compareAtPriceMinor,
      categoryId,
      imageUrl: images[0],
      images,
      status: toProductStatus(row.status, asBool(row.is_active)),
      isFeatured: asBool(row.is_featured),
      isNewArrival: asBool(row.is_new_arrival),
      isBestSeller: asBool(row.is_best_seller),
      createdAt: parseDjangoDate(row.created_at),
      updatedAt: parseDjangoDate(row.updated_at),
    });
  }

  return { products, rowsById };
}

function mapVariants(
  conn: SqliteDatabase,
  products: ProductEntity[],
  productRows: Map<string, ProductSeedRow>
): { variants: ProductVariantEntity[]; synthesized: number } {
  const variants: ProductVariantEntity[] = [];
  const productById = new Map(products.map((product) => [product.id, product]));
  const seenIds = new Set<string>();
  const seenSkus = new Set<string>();
  const coveredProducts = new Set<string>();

  for (const row of query(conn, `
    SELECT id, product_id, sku, size, color, color_hex, price_minor,
           stock_quantity, is_active
    FROM catalog_productvariant
  `)) {
    const id = asText(row.id);
    const productId = asText(row.product_id);
    const sku = asText(row.sku);
    const product = productById.get(productId);
    if (!id || !sku || !product || seenIds.has(id) || seenSkus.has(sku)) continue;

    seenIds.add(id);
    seenSkus.add(sku);
    coveredProducts.add(productId);

    let priceMinor: number | undefined;
    if (row.price_minor !== null && row.price_minor !== undefined) {
      const price = Math.round(asNumber(row.price_minor, -1));
      if (price >= 0) priceMinor = price;
    }

    variants.push({
      id,
      productId,
      sku,
      size: optionalText(row.size),
      color: optionalText(row.color),
      colorHex: optionalText(row.color_hex),
      priceMinor,
      stockQuantity: Math.max(0, Math.round(asNumber(row.stock_quantity))),
      isActive: asBool(row.is_active),
      createdAt: product.createdAt,
      updatedAt: product.updatedAt,
    });
  }

  // Products without any variant row still need one so the storefront can price
  // and sell them; synthesise it from the legacy product-level size/stock fields.
  let synthesized = 0;
  for (const product of products) {
    if (coveredProducts.has(product.id)) continue;

    const source = productRows.get(product.id);
    const sku = optionalText(source?.sku) ?? `${product.id}-default`;
    const uniqueSku = seenSkus.has(sku) ? `${product.id}-default` : sku;
    if (seenSkus.has(uniqueSku)) continue;

    seenSkus.add(uniqueSku);
    synthesized += 1;
    variants.push({
      id: `${product.id}__default`,
      productId: product.id,
      sku: uniqueSku,
      size: optionalText(source?.size),
      color: optionalText(source?.color),
      stockQuantity: Math.max(0, Math.round(asNumber(source?.stock_quantity))),
      isActive: true,
      createdAt: product.createdAt,
      updatedAt: product.updatedAt,
    });
  }

  return { variants, synthesized };
}

function mapCustomer(value: unknown): ShippingAddressEntity {
  const parsed = parseJsonObject(value);
  const text = (key: string): string => asText(parsed[key]).trim();
  const optional = (key: string): string | undefined => optionalText(parsed[key]);

  return {
    fullName: text('fullName') || 'Customer',
    email: text('email'),
    phone: text('phone'),
    addressLine1: text('addressLine1'),
    addressLine2: optional('addressLine2'),
    city: text('city'),
    county: text('county'),
    postalCode: optional('postalCode'),
    deliveryInstructions: optional('deliveryInstructions'),
  };
}

function mapOrders(conn: SqliteDatabase): {
  orders: OrderEntity[];
  orderItems: number;
} {
  const orderRows = query(conn, `
    SELECT id, order_number, cart_id, customer, subtotal_minor, shipping_cost_minor,
           tax_minor, total_minor, shipping_method, payment_method, status,
           payment_status, payment_intent_id, created_at, updated_at
    FROM orders_order
  `);
  const itemRows = query(conn, `
    SELECT id, order_id, product_id, variant_id, product_name, variant_sku,
           variant_size, variant_color, image_url, unit_price_minor, quantity,
           line_total_minor
    FROM orders_orderitem
  `);

  const itemsByOrder = new Map<string, OrderItemEntity[]>();
  let itemCount = 0;
  for (const row of itemRows) {
    const orderId = asText(row.order_id);
    if (!orderId) continue;

    itemCount += 1;
    const items = itemsByOrder.get(orderId) ?? [];
    items.push({
      id: asText(row.id) || `item-${itemCount}`,
      orderId,
      productId: asText(row.product_id),
      variantId: asText(row.variant_id),
      productName: asText(row.product_name),
      variantSku: asText(row.variant_sku),
      variantSize: optionalText(row.variant_size),
      variantColor: optionalText(row.variant_color),
      imageUrl: resolveMediaUrl(row.image_url),
      unitPriceMinor: Math.round(asNumber(row.unit_price_minor)),
      quantity: Math.max(1, Math.round(asNumber(row.quantity, 1))),
      lineTotalMinor: Math.round(asNumber(row.line_total_minor)),
    });
    itemsByOrder.set(orderId, items);
  }

  const orders: OrderEntity[] = [];
  const seenIds = new Set<string>();
  const seenNumbers = new Set<string>();

  for (const row of orderRows) {
    const id = asText(row.id);
    const orderNumber = asText(row.order_number) || id;
    if (!id || seenIds.has(id) || seenNumbers.has(orderNumber)) continue;

    seenIds.add(id);
    seenNumbers.add(orderNumber);
    orders.push({
      id,
      orderNumber,
      cartId: optionalText(row.cart_id) ?? `django-order-${id}`,
      customer: mapCustomer(row.customer),
      items: itemsByOrder.get(id) ?? [],
      subtotalMinor: Math.round(asNumber(row.subtotal_minor)),
      shippingCostMinor: Math.round(asNumber(row.shipping_cost_minor)),
      taxMinor: Math.round(asNumber(row.tax_minor)),
      totalMinor: Math.round(asNumber(row.total_minor)),
      shippingMethod: asText(row.shipping_method).trim().toLowerCase() === 'express'
        ? 'express'
        : 'standard',
      paymentMethod: toPaymentMethod(row.payment_method),
      status: toOrderStatus(row.status),
      paymentStatus: toPaymentStatus(row.payment_status),
      paymentIntentId: optionalText(row.payment_intent_id),
      createdAt: parseDjangoDate(row.created_at),
      updatedAt: parseDjangoDate(row.updated_at),
    });
  }

  return { orders, orderItems: itemCount };
}

function mapReservations(
  conn: SqliteDatabase,
  orderIds: Set<string>,
  variantIds: Set<string>
): StockReservationEntity[] {
  const reservations: StockReservationEntity[] = [];
  const seenIds = new Set<string>();

  for (const row of query(conn, `
    SELECT id, order_id, variant_id, quantity, status, expires_at,
           created_at, released_at
    FROM inventory_stockreservation
  `)) {
    const id = asText(row.id);
    const orderId = asText(row.order_id);
    const variantId = asText(row.variant_id);
    const quantity = Math.round(asNumber(row.quantity));
    if (!id || seenIds.has(id) || quantity <= 0) continue;
    if (!orderIds.has(orderId) || !variantIds.has(variantId)) continue;

    seenIds.add(id);
    const createdAt = parseDjangoDate(row.created_at);
    const releasedAt = optionalText(row.released_at);
    reservations.push({
      id,
      orderId,
      variantId,
      quantity,
      status: toReservationStatus(row.status),
      expiresAt: parseDjangoDate(row.expires_at, createdAt),
      createdAt,
      updatedAt: releasedAt ? parseDjangoDate(releasedAt) : createdAt,
    });
  }

  return reservations;
}

interface DjangoSnapshot {
  snapshot: DatabaseSnapshot;
  synthesizedVariants: number;
  orderItems: number;
}

function buildSnapshot(conn: SqliteDatabase): DjangoSnapshot {
  const categories = mapCategories(conn);
  const { products, rowsById: productRows } = mapProducts(
    conn,
    new Set(categories.map((category) => category.id))
  );
  const { variants, synthesized } = mapVariants(conn, products, productRows);
  const { orders, orderItems } = mapOrders(conn);
  const reservations = mapReservations(
    conn,
    new Set(orders.map((order) => order.id)),
    new Set(variants.map((variant) => variant.id))
  );

  return {
    snapshot: {
      categories,
      products,
      variants,
      carts: [],
      cartItems: [],
      orders,
      paymentIntents: [],
      reservations,
    },
    synthesizedVariants: synthesized,
    orderItems,
  };
}

/**
 * Replaces the in-memory store with the contents of the Django SQLite database.
 * Returns true when data was loaded, false when the app should keep the seed data.
 */
export function hydrateFromDjangoSqlite(): boolean {
  if (!isDjangoSqliteDevMode()) return false;

  const databasePath = resolveDatabasePath();
  if (!databasePath) {
    console.info('[dev-sqlite] No Django SQLite database found — serving the built-in seed catalog.');
    return false;
  }

  const sqlite = getSqliteModule();
  if (!sqlite || typeof sqlite.DatabaseSync !== 'function') {
    console.warn(
      '[dev-sqlite] node:sqlite is unavailable (Node.js 22.5+ required) — serving the built-in seed catalog.'
    );
    return false;
  }

  let conn: SqliteDatabase | undefined;
  try {
    conn = new sqlite.DatabaseSync(databasePath, { readOnly: true });
    const { snapshot, synthesizedVariants, orderItems } = buildSnapshot(conn);

    if (snapshot.categories.length === 0 && snapshot.products.length === 0) {
      console.info(
        `[dev-sqlite] ${databasePath} has no catalog rows yet — serving the built-in seed catalog.`
      );
      return false;
    }

    db.restoreSnapshot(snapshot);
    console.info(
      `[dev-sqlite] Loaded ${snapshot.categories.length} categories, ` +
        `${snapshot.products.length} products, ${snapshot.variants.length} variants ` +
        `(${synthesizedVariants} synthesised), ${snapshot.orders.length} orders ` +
        `(${orderItems} line items) and ${snapshot.reservations.length} reservations ` +
        `from ${databasePath} ` +
        '(read-only; storefront writes stay in memory).'
    );
    return true;
  } catch (err) {
    console.warn(
      '[dev-sqlite] Could not read the Django SQLite database — serving the built-in seed catalog.',
      err instanceof Error ? err.message : err
    );
    try {
      db.seed();
    } catch {
      // RelationalDatabase.seed() only fails on corrupt seed data; keep going.
    }
    return false;
  } finally {
    try {
      conn?.close();
    } catch {
      // Closing an already-closed handle is not actionable.
    }
  }
}
