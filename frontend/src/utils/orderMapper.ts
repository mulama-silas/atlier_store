import { Order, OrderStatus, ShippingAddress } from '../types';
import { OrderDTO } from '../types/api';

/**
 * Maps a server OrderDTO onto the domain Order used by the orders UI.
 * Source of truth for every server-backed order surface so mapping stays DRY.
 *
 * The timeline comes straight from the authoritative backend audit trail
 * (real events only). When a mock/local API omits it, fall back to a single
 * truthful "Placed" event rather than inventing milestones.
 */
export function mapServerOrder(serverOrder: OrderDTO): Order {
  const nameParts = (serverOrder.customer.fullName || '').split(' ').filter(Boolean);

  const customer: ShippingAddress = {
    firstName: nameParts[0] || serverOrder.customer.fullName || '',
    lastName: nameParts.slice(1).join(' ') || '',
    email: serverOrder.customer.email,
    phone: serverOrder.customer.phone,
    addressLine1: serverOrder.customer.addressLine1,
    addressLine2: serverOrder.customer.addressLine2 || '',
    city: serverOrder.customer.city,
    stateOrProvince: serverOrder.customer.county,
    postalCode: serverOrder.customer.postalCode || '',
    country: 'Kenya',
  };

  const timeline = Array.isArray(serverOrder.timeline) && serverOrder.timeline.length > 0
    ? serverOrder.timeline.map((event) => ({
        status: event.status,
        title: event.title,
        description: event.description,
        timestamp: event.timestamp,
        completed: event.completed,
      }))
    : [{
        status: 'confirmed' as OrderStatus,
        title: 'Order Placed',
        description: 'Order registered in the modeza order ledger.',
        timestamp: serverOrder.createdAt,
        completed: true,
      }];

  return {
    id: serverOrder.id,
    orderNumber: serverOrder.orderNumber,
    customer,
    items: serverOrder.items.map((item) => ({
      id: item.id,
      productId: item.productId,
      variantId: item.variantId,
      productName: item.productName,
      variantDetails: `${item.variantSize || ''} ${item.variantColor || ''}`.trim(),
      sku: item.variantSku,
      unitPrice: item.unitPrice,
      quantity: item.quantity,
      subtotal: item.lineTotal,
      image: item.imageUrl || '',
    })),
    subtotal: serverOrder.subtotal,
    discount: serverOrder.promotion
      ? {
          code: serverOrder.promotion.code,
          type: (serverOrder.promotion.type === 'fixed' ? 'fixed' : 'percentage') as 'percentage' | 'fixed',
          amount: serverOrder.discount ?? serverOrder.promotion.discount ?? 0,
          description: serverOrder.promotion.name,
        }
      : serverOrder.discount
        ? { code: '', type: 'fixed' as const, amount: serverOrder.discount, description: 'Promotion discount' }
        : undefined,
    shippingMethod: serverOrder.shippingMethod,
    shippingCost: serverOrder.shippingCost,
    tax: serverOrder.tax,
    total: serverOrder.total,
    status: serverOrder.status,
    paymentStatus: serverOrder.paymentStatus,
    paymentMethod: serverOrder.paymentMethod,
    notes: serverOrder.customer.deliveryInstructions,
    timeline,
    createdAt: serverOrder.createdAt,
    updatedAt: serverOrder.updatedAt,
  };
}

/** Total units across an order's items (quantity-aware). */
export function totalQuantity(order: { items: { quantity: number }[] }): number {
  return order.items.reduce((sum, item) => sum + item.quantity, 0);
}

/** Timestamp for the order's current status, with a sensible placed-date fallback. */
export function getOrderStatusTimestamp(order: Order): string {
  const event = order.timeline.find((entry) => entry.status === order.status);
  if (event?.timestamp) return event.timestamp;
  if (order.status === 'delivered' || order.status === 'received' || order.status === 'cancelled') {
    return order.updatedAt || order.createdAt;
  }
  return order.createdAt;
}

/** Compact day-month label used in order item rows, e.g. 28-08. */
export function formatShortOrderDate(iso: string | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const parts = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: '2-digit' }).formatToParts(date);
  const day = parts.find((part) => part.type === 'day')?.value;
  const month = parts.find((part) => part.type === 'month')?.value;
  return day && month ? `${day}-${month}` : '';
}

/** Locale-aware date formatting used across the orders experience. */
export function formatOrderDate(iso: string | undefined, opts?: Intl.DateTimeFormatOptions): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString('en-KE', opts);
}
