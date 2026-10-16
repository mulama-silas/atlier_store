import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { Order, OrderStatus, CreateOrderInput, OrderTimelineEvent } from '../types';
import { useStore } from './StoreContext';
import { useAuth } from './AuthContext';
import { api } from '../services/apiClient';
import { mapServerOrder } from '../utils/orderMapper';
import { canMarkReceived } from '../utils/orderStatus';

const ORDERS_STORAGE_BASE_KEY = 'modeza_orders_v4_kes';
const GUEST_KEY = `${ORDERS_STORAGE_BASE_KEY}:guest`;

function ordersKeyFor(userId?: string | null): string {
  return userId ? `${ORDERS_STORAGE_BASE_KEY}:${userId}` : GUEST_KEY;
}

function readStoredOrders(key: string): Order[] {
  try {
    const saved = localStorage.getItem(key);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) return parsed as Order[];
    }
  } catch {
    // ignore corrupt cache — fresh users start with 0 orders
  }
  return [];
}

/** One-time wipe of the legacy global key so old demo orders never leak. */
function wipeLegacyGlobalOrders(): void {
  try {
    localStorage.removeItem(ORDERS_STORAGE_BASE_KEY);
  } catch {
    // ignore
  }
}

export interface OrdersContextType {
  orders: Order[];
  createOrder: (input: CreateOrderInput) => Promise<{ success: boolean; order?: Order; error?: string }>;
  getOrder: (orderNumberOrId: string) => Order | undefined;
  updateOrderStatus: (orderNumber: string, status: OrderStatus) => void;
  cancelOrder: (orderNumber: string) => Promise<{ success: boolean; order?: Order; message: string }>;
  receiveOrder: (orderNumber: string) => Promise<{ success: boolean; order?: Order; message: string }>;
  requestOrderReturn: (orderNumber: string, reason?: string) => Promise<{ success: boolean; order?: Order; message: string }>;
  searchOrders: (query: string) => Order[];
  resetOrdersToDefault: () => void;
}

const OrdersContext = createContext<OrdersContextType | undefined>(undefined);

export const OrdersProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { restockInventoryForOrder } = useStore();
  const { user } = useAuth();
  const userId = user?.id ?? null;

  // Fresh signups start with 0 orders. State is intentionally empty on first
  // render so no previous user's cache can flash before scoping resolves.
  const [orders, setOrders] = useState<Order[]>([]);
  const activeKeyRef = useRef<string>(ordersKeyFor(userId));
  const previousUserIdRef = useRef<string | null | undefined>(undefined);

  // One-time wipe of the legacy global key (pre-per-user cache).
  useEffect(() => {
    wipeLegacyGlobalOrders();
  }, []);

  // Switch the active per-user cache whenever auth changes. Guest caches are
  // discarded on sign-in (wiped, never migrated) so a new signup sees 0 orders.
  useEffect(() => {
    const prev = previousUserIdRef.current;
    const next = userId;
    const nextKey = ordersKeyFor(next);
    activeKeyRef.current = nextKey;

    if (prev === undefined) {
      // Initial load: hydrate this account's cache only.
      previousUserIdRef.current = next;
      setOrders(readStoredOrders(nextKey));
      return;
    }
    if (prev !== next) {
      if (!next && prev) {
        // Signed out: wipe in-memory so the next session never sees it.
        // Also discard the anonymous guest cache.
        try {
          localStorage.removeItem(GUEST_KEY);
        } catch {
          // ignore
        }
        previousUserIdRef.current = next;
        activeKeyRef.current = GUEST_KEY;
        setOrders([]);
        return;
      }
      if (next && !prev) {
        // Guest -> signed-in: discard guest cache, never migrate it.
        try {
          localStorage.removeItem(GUEST_KEY);
        } catch {
          // ignore
        }
        previousUserIdRef.current = next;
        setOrders(readStoredOrders(nextKey));
        return;
      }
      // Account switch (A -> B): isolate caches.
      previousUserIdRef.current = next;
      setOrders(readStoredOrders(nextKey));
    }
  }, [userId]);

  // Persist only to the active per-user key.
  useEffect(() => {
    try {
      localStorage.setItem(activeKeyRef.current, JSON.stringify(orders));
    } catch {
      // ignore
    }
  }, [orders]);

  const getOrder = useCallback(
    (orderNumberOrId: string): Order | undefined => {
      const query = orderNumberOrId.trim().toUpperCase();
      return orders.find(
        (o) => o.orderNumber.toUpperCase() === query || o.id.toUpperCase() === query
      );
    },
    [orders]
  );

  const createOrder = useCallback(
    async (input: CreateOrderInput): Promise<{ success: boolean; order?: Order; error?: string }> => {
      if (!input.items || input.items.length === 0) {
        return { success: false, error: 'Your cart is empty.' };
      }

      const normalizePhone = (phone: string): string => {
        return phone
          .replace(/[^\d\s\+\-\(\)\./#*]/g, '')
          .slice(0, 25);
      };

      // Try authoritative backend order placement via /api/orders
      try {
        const serverOrder = await api.createOrder({
          customer: {
            fullName: `${input.customer.firstName} ${input.customer.lastName}`.trim(),
            email: input.customer.email,
            phone: normalizePhone(input.customer.phone),
            addressLine1: input.customer.addressLine1,
            addressLine2: input.customer.addressLine2,
            city: input.customer.city,
            county: input.customer.stateOrProvince || 'Nairobi',
            postalCode: input.customer.postalCode,
            deliveryInstructions: input.notes,
          },
          shippingMethod: input.shippingMethod,
          paymentMethod: input.paymentMethod || 'mpesa',
          notes: input.notes,
          // Forward the checkout coupon: Django revalidates eligibility and
          // computes the discount server-side (never trusts this value).
          couponCode: input.discountCode,
        });

        const now = new Date().toISOString();
        // Timeline comes from the authoritative backend audit trail.
        const mappedOrder: Order = {
          ...mapServerOrder(serverOrder),
          notes: input.notes,
          updatedAt: now,
        };

        setOrders((prev) => [mappedOrder, ...prev]);
        return { success: true, order: mappedOrder };
      } catch (backendErr: unknown) {
        const errorObj = backendErr as Error & { code?: string; details?: unknown };

        // The backend responded with an application error (e.g. VALIDATION_ERROR
        // for stock conflicts, NOT_FOUND, RATE_LIMITED). Surface the authoritative
        // message instead of fabricating a local order.
        if (errorObj.code) {
          let message = errorObj.message || 'Could not place the order.';
          if (errorObj.code === 'VALIDATION_ERROR' && errorObj.details) {
            const details = errorObj.details as Record<string, unknown>;
            if (typeof details.stock === 'string') {
              message = details.stock;
            } else if (typeof details.couponCode === 'string') {
              message = details.couponCode;
            }
          }
          return { success: false, error: message };
        }

        return {
          success: false,
          error: 'We could not reach the store to place your order. Your bag is saved; check your connection and try again.',
        };
      }
    },
    []
  );

  const updateOrderStatus = useCallback(
    (orderNumber: string, status: OrderStatus) => {
      setOrders((prev) =>
        prev.map((o) => {
          if (o.orderNumber.toUpperCase() !== orderNumber.toUpperCase()) return o;

          const now = new Date().toISOString();
          const updatedTimeline = o.timeline.map((step) => {
            if (step.status === status) {
              return { ...step, completed: true, timestamp: now };
            }
            return step;
          });

          return {
            ...o,
            status,
            timeline: updatedTimeline,
            updatedAt: now,
          };
        })
      );
    },
    []
  );

  const cancelOrder = useCallback(
    async (orderNumber: string): Promise<{ success: boolean; order?: Order; message: string }> => {
      const order = orders.find((o) => o.orderNumber.toUpperCase() === orderNumber.toUpperCase());
      if (!order) {
        return { success: false, message: 'Order not found.' };
      }
      if (order.status === 'cancelled') {
        return { success: false, message: 'Order is already cancelled.' };
      }
      if (order.status === 'shipped' || order.status === 'delivered') {
        return {
          success: false,
          message: 'Order has already dispatched and cannot be cancelled automatically. Contact support.',
        };
      }

      const applyCancelled = (cancelled: Order) => {
        setOrders((prev) =>
          prev.map((o) =>
            o.orderNumber.toUpperCase() === cancelled.orderNumber.toUpperCase() ? cancelled : o
          )
        );
      };

      try {
        // Authoritative server cancellation releases reserved modeza stock.
        const serverOrder = await api.cancelOrder(order.orderNumber);
        applyCancelled(mapServerOrder(serverOrder));
        return { success: true, order: mapServerOrder(serverOrder), message: `Order ${orderNumber} has been cancelled and restocked.` };
      } catch (err: unknown) {
        const errorObj = err as Error & { code?: string };
        // The backend refused the cancellation (e.g. too late to cancel). Surface its message.
        if (errorObj.code && errorObj.code !== 'NOT_FOUND') {
          return {
            success: false,
            message: errorObj.message || 'MODEZA could not cancel this order.',
          };
        }

        // Server has no record of this order (offline/local preview) — fall back to a
        // local cancellation that restocks the local inventory ledger.
        restockInventoryForOrder(
          order.items.map((i) => ({
            productId: i.productId,
            variantId: i.variantId,
            quantity: i.quantity,
            sku: i.sku,
          })),
          order.orderNumber
        );
        const now = new Date().toISOString();
        const updated: Order = {
          ...order,
          status: 'cancelled',
          paymentStatus: 'refunded',
          updatedAt: now,
          timeline: [
            ...order.timeline,
            {
              status: 'cancelled',
              title: 'Order Cancelled (Offline)',
              description: 'Cancellation recorded locally while offline; it will sync with modeza services when back online.',
              timestamp: now,
              completed: true,
            },
          ],
        };
        applyCancelled(updated);
        return { success: true, order: updated, message: `Order ${orderNumber} has been cancelled and restocked.` };
      }
    },
    [orders, restockInventoryForOrder]
  );

  const receiveOrder = useCallback(
    async (orderNumber: string): Promise<{ success: boolean; order?: Order; message: string }> => {
      const order = orders.find((o) => o.orderNumber.toUpperCase() === orderNumber.toUpperCase());
      if (!order) {
        return { success: false, message: 'Order not found.' };
      }
      if (order.status === 'received') {
        return { success: false, message: 'Order is already marked as received.' };
      }
      if (!canMarkReceived(order.status, order.paymentMethod)) {
        return { success: false, message: 'Only confirmed, delivered or pay-on-delivery orders can be marked as received.' };
      }

      const applyReceived = (updated: Order) => {
        setOrders((prev) =>
          prev.map((o) =>
            o.orderNumber.toUpperCase() === updated.orderNumber.toUpperCase() ? updated : o
          )
        );
      };

      try {
        // Authoritative server confirmation (settles cash/pay-on-delivery balances).
        // The backend timeline carries the real order_received event.
        const serverOrder = await api.receiveOrder(order.orderNumber);
        const mapped = mapServerOrder(serverOrder);
        applyReceived(mapped);
        return { success: true, order: mapped, message: `Order ${orderNumber} has been marked as received.` };
      } catch (err: unknown) {
        const errorObj = err as Error & { code?: string };
        if (errorObj.code && errorObj.code !== 'NOT_FOUND') {
          return {
            success: false,
            message: errorObj.message || 'The order could not be marked as received.',
          };
        }

        const now = new Date().toISOString();
        // For cash/pay-on-delivery orders the balance is settled on confirmation
        // of receipt. Prepaid orders (M-Pesa / card) keep their payment status.
        const isDeliveryPayment =
          order.paymentMethod !== 'mpesa' && order.paymentMethod !== 'card';
        const updated: Order = {
          ...order,
          status: 'received',
          paymentStatus: isDeliveryPayment ? 'paid' : order.paymentStatus,
          updatedAt: now,
          timeline: [
            ...order.timeline,
            {
              status: 'received',
              title: 'Order Received (Offline)',
              description: 'Receipt confirmed locally while offline; it will sync with modeza services when back online.',
              timestamp: now,
              completed: true,
            },
          ],
        };
        applyReceived(updated);
        return { success: true, order: updated, message: `Order ${orderNumber} has been marked as received.` };
      }
    },
    [orders]
  );

  const searchOrders = useCallback(
    (query: string): Order[] => {
      const q = query.trim().toLowerCase();
      if (!q) return orders;
      return orders.filter(
        (o) =>
          o.orderNumber.toLowerCase().includes(q) ||
          o.customer.email.toLowerCase().includes(q) ||
          `${o.customer.firstName} ${o.customer.lastName}`.toLowerCase().includes(q) ||
          o.customer.phone.toLowerCase().includes(q)
      );
    },
    [orders]
  );

  const requestOrderReturn = useCallback(
    async (orderNumber: string, reason = ''): Promise<{ success: boolean; order?: Order; message: string }> => {
      const order = orders.find((o) => o.orderNumber.toUpperCase() === orderNumber.toUpperCase());
      if (!order) {
        return { success: false, message: 'Order not found.' };
      }
      if (order.paymentStatus === 'refunded') {
        return { success: false, message: 'A refund is already recorded for this order.' };
      }
      if (order.status !== 'received' && order.status !== 'delivered') {
        return { success: false, message: 'Only received or delivered orders can request a refund.' };
      }

      try {
        // Authoritative request is recorded in the backend audit trail and
        // notifies staff; payment reversal stays a staff action.
        const serverOrder = await api.requestOrderReturn(order.orderNumber, reason);
        const mapped = mapServerOrder(serverOrder);
        setOrders((prev) =>
          prev.map((o) =>
            o.orderNumber.toUpperCase() === mapped.orderNumber.toUpperCase() ? mapped : o
          )
        );
        return { success: true, order: mapped, message: 'Your return/refund request has been submitted.' };
      } catch (err: unknown) {
        const errorObj = err as Error & { code?: string };
        return {
          success: false,
          message: errorObj.message || 'The refund request could not be submitted.',
        };
      }
    },
    [orders]
  );

  const resetOrdersToDefault = useCallback(() => {
    // Wipe all local order caches (legacy global + guest + active user).
    setOrders([]);
    try {
      localStorage.removeItem(ORDERS_STORAGE_BASE_KEY);
      localStorage.removeItem(GUEST_KEY);
      localStorage.removeItem(activeKeyRef.current);
      const doomed: string[] = [];
      for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i);
        if (key && key.startsWith(`${ORDERS_STORAGE_BASE_KEY}:`)) doomed.push(key);
      }
      doomed.forEach((key) => localStorage.removeItem(key));
    } catch {
      // ignore
    }
  }, []);

  return (
    <OrdersContext.Provider
      value={{
        orders,
        createOrder,
        getOrder,
        updateOrderStatus,
        cancelOrder,
        receiveOrder,
        requestOrderReturn,
        searchOrders,
        resetOrdersToDefault,
      }}
    >
      {children}
    </OrdersContext.Provider>
  );
};

export const useOrders = (): OrdersContextType => {
  const context = useContext(OrdersContext);
  if (!context) {
    throw new Error('useOrders must be used within an OrdersProvider');
  }
  return context;
};
