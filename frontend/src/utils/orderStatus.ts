import { OrderStatus } from '../types';

/**
 * Centralised order-status metadata shared by every orders surface.
 * Keeps status presentation (labels, dot colour, accessibility) consistent.
 */
export interface OrderStatusMeta {
  label: string;
  /** Tailwind classes for the status dot. */
  dotClass: string;
  /** Tailwind classes for the status label text. */
  pillTextClass: string;
  /** Lifecycle rank for the progress tracker. -1 = terminal/non-lifecycle. */
  rank: number;
}

export const ORDER_STATUS_META: Record<OrderStatus, OrderStatusMeta> = {
  pending: {
    label: 'Pending',
    dotClass: 'bg-[#A29E96]',
    pillTextClass: 'text-[#63605A]',
    rank: 0,
  },
  confirmed: {
    label: 'Confirmed',
    dotClass: 'bg-[#A2574F]',
    pillTextClass: 'text-[#83443D]',
    rank: 1,
  },
  processing: {
    label: 'Processing',
    dotClass: 'bg-[#A2574F]',
    pillTextClass: 'text-[#83443D]',
    rank: 2,
  },
  shipped: {
    label: 'Shipped',
    dotClass: 'bg-[#181716]',
    pillTextClass: 'text-[#181716]',
    rank: 3,
  },
  delivered: {
    label: 'Delivered',
    dotClass: 'bg-[#2E5A44]',
    pillTextClass: 'text-[#2E5A44]',
    rank: 4,
  },
  received: {
    label: 'Received',
    dotClass: 'bg-[#2E5A44]',
    pillTextClass: 'text-[#2E5A44]',
    rank: 4,
  },
  cancelled: {
    label: 'Cancelled',
    dotClass: 'bg-[#A29E96]',
    pillTextClass: 'text-[#827E77]',
    rank: -1,
  },
};

/**
 * Status filter groups shown on the My Orders page. Delivered and Received
 * share a single tab so counts never collide for the same customer-facing state.
 */
export const STATUS_FILTER_GROUPS: { key: string; label: string; statuses: OrderStatus[] }[] = [
  { key: 'pending', label: 'Pending', statuses: ['pending'] },
  { key: 'confirmed', label: 'Confirmed', statuses: ['confirmed'] },
  { key: 'processing', label: 'Processing', statuses: ['processing'] },
  { key: 'shipped', label: 'Shipped', statuses: ['shipped'] },
  { key: 'delivered', label: 'Delivered', statuses: ['delivered', 'received'] },
  { key: 'cancelled', label: 'Cancelled', statuses: ['cancelled'] },
];

/** Standard lifecycle steps shown in the order progress tracker. */
export const PROGRESS_STEPS: { status: OrderStatus; label: string }[] = [
  { status: 'confirmed', label: 'Ordered' },
  { status: 'processing', label: 'Processing' },
  { status: 'shipped', label: 'Shipped' },
  { status: 'delivered', label: 'Delivered' },
];

/** Statuses that are still travelling through the delivery lifecycle. */
export function isActiveOrder(status: OrderStatus): boolean {
  return status !== 'cancelled' && status !== 'delivered' && status !== 'received';
}

/** Statuses where a "Track order" action makes sense. */
export function isTrackable(status: OrderStatus): boolean {
  return status === 'confirmed' || status === 'processing' || status === 'shipped';
}

/** Statuses the backend allows a customer to cancel (pending or confirmed). */
export function canCancel(status: OrderStatus): boolean {
  return status === 'pending' || status === 'confirmed';
}

/** Statuses where a customer can confirm receipt / settle (backend mark-received-paid). */
export function canMarkReceived(status: OrderStatus, paymentMethod?: string): boolean {
  const method = paymentMethod?.toLowerCase();
  const isDeliveryPayment = method === 'pay_on_delivery' || method === 'cash_on_delivery';
  return isDeliveryPayment && (
    status === 'pending' || status === 'confirmed' || status === 'delivered'
  );
}

/** Statuses where a customer can request a return/refund (backend request_refund). */
export function canRequestRefund(status: OrderStatus): boolean {
  return status === 'received' || status === 'delivered';
}