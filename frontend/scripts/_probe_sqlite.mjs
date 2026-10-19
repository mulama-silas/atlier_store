import { DatabaseSync } from 'node:sqlite';

const db = new DatabaseSync('../backend/db.sqlite3', { readOnly: true });

const dump = (label, sql) => {
  console.log('\n=== ' + label + ' ===');
  const rows = db.prepare(sql).all();
  for (const r of rows) console.log(JSON.stringify(r));
};

dump('category', 'SELECT * FROM catalog_category LIMIT 3');
dump('product', 'SELECT id, category_id, name, slug, tagline, details, price_minor, compare_at_price_minor, images, status, is_featured, is_new_arrival, is_best_seller, sku, size, color, stock_quantity, is_active, created_at, updated_at FROM catalog_product');
dump('variant', 'SELECT * FROM catalog_productvariant');
dump('order', 'SELECT id, order_number, cart_id, user_id, customer, subtotal_minor, shipping_cost_minor, tax_minor, total_minor, shipping_method, payment_method, status, payment_status, payment_intent_id, created_at, updated_at FROM orders_order LIMIT 3');
dump('orderitem', 'SELECT * FROM orders_orderitem LIMIT 3');
dump('reservation_status', 'SELECT DISTINCT status FROM inventory_stockreservation');
dump('reservation', 'SELECT * FROM inventory_stockreservation LIMIT 3');
dump('productimage', 'SELECT * FROM catalog_productimage LIMIT 3');
