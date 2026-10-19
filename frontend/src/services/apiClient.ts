import {
  ProductDTO,
  CategoryDTO,
  CartDTO,
  CartMergeResponse,
  OrderDTO,
  PaymentIntentDTO,
  PromotionPricingDTO,
  AvailablePromotionDTO,
  PromotionAnnouncementDTO,
  ReceiptDTO,
  PaginatedProductsResponse,
  CustomerAddressDTO,
  CustomerProfileDTO,
  ProductReviewDTO,
} from '../types/api';
import { CustomerNotification } from '../types';
import { supabase } from './supabaseClient';
import { setLastRequestId } from '../lib/requestId';

const CART_STORAGE_KEY = 'modeza_server_cart_id';
// Default to the Django backend for local development. The frontend is expected to
// read real catalog data from the database unless a different API origin is configured.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export function getOrCreateCartId(): string {
  if (typeof window === 'undefined') return 'cart_ssr';
  let cartId = localStorage.getItem(CART_STORAGE_KEY);
  if (!cartId) {
    const token = new Uint8Array(24);
    window.crypto.getRandomValues(token);
    cartId = `cart_${Array.from(token, byte => byte.toString(16).padStart(2, '0')).join('')}`;
    localStorage.setItem(CART_STORAGE_KEY, cartId);
  } 
  return cartId;
}

export function saveCartId(cartId: string): void {
  if (typeof window !== 'undefined' && cartId) {
    localStorage.setItem(CART_STORAGE_KEY, cartId);
  }
}

export function resetCartId(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(CART_STORAGE_KEY);
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}, includeAuth = true, requireAuth = false, retryUnauthorized = true): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');

  let cartId = getOrCreateCartId();

  if (includeAuth) {
    const session = (await supabase?.auth.getSession())?.data.session;
    if (session?.access_token) {
      headers.set('Authorization', `Bearer ${session.access_token}`);
    } else {
      // A signed-in user's cart key (u:<user id>) cannot be used by a guest.
      // Clear stale account keys before making public cart/pricing requests,
      // such as after a session expires or a sign-out event was missed.
      if (cartId.startsWith('u:')) {
        resetCartId();
        cartId = getOrCreateCartId();
      }
      if (requireAuth) {
        const error = new Error('Authentication is required for this request.') as Error & { code?: string; status?: number };
        error.code = 'AUTH_REQUIRED';
        error.status = 401;
        throw error;
      }
    }
  }

  headers.set('x-cart-id', cartId);

  const requestOptions = {
    ...options,
    headers,
    credentials: 'include' as const,
  };
  let res = await fetch(`${API_BASE_URL}${endpoint}`, requestOptions);

  // Supabase access tokens are short-lived. Refresh once before surfacing a 401.
  if (res.status === 401 && retryUnauthorized && includeAuth && requireAuth && supabase && headers.has('Authorization')) {
    const { data } = await supabase.auth.refreshSession();
    const refreshedToken = data.session?.access_token;
    if (refreshedToken) {
      headers.set('Authorization', `Bearer ${refreshedToken}`);
      res = await fetch(`${API_BASE_URL}${endpoint}`, requestOptions);
    }
  }

  // Capture the backend request ID for error correlation and audit reports.
  const requestId = res.headers.get('x-request-id');
  if (requestId) setLastRequestId(requestId);

  // Track returned cart header if any
  const returnedCartId = res.headers.get('x-cart-id');
  if (returnedCartId) {
    saveCartId(returnedCartId);
  }

  if (!res.ok) {
    let errorJson: { error?: { code?: string; message?: string; details?: unknown } } = {};
    try {
      errorJson = await res.json();
    } catch {
      // ignore
    }
    const errorObj = errorJson?.error;
    const message = errorObj?.message || `API request failed with status ${res.status}.`;
    const code = errorObj?.code || (res.status === 404 ? 'NOT_FOUND' : 'UNKNOWN_ERROR');
    const error = new Error(message) as Error & { code?: string; details?: unknown; status?: number; requestId?: string };
    error.code = code;
    error.details = errorObj?.details;
    error.status = res.status;
    if (errorJson && 'request_id' in errorJson) {
      setLastRequestId(errorJson.request_id as string);
      error.requestId = errorJson.request_id as string;
    }
    throw error;
  }

  if (res.status === 204) return undefined as T;

  return res.json() as Promise<T>;
}

async function downloadBlob(endpoint: string, requireAuth = true): Promise<Blob> {
  const cartId = getOrCreateCartId();
  const headers = new Headers();
  headers.set('x-cart-id', cartId);

  if (requireAuth) {
    const session = (await supabase?.auth.getSession())?.data.session;
    if (session?.access_token) {
      headers.set('Authorization', `Bearer ${session.access_token}`);
    } else {
      const error = new Error('Authentication is required for this request.') as Error & { code?: string; status?: number };
      error.code = 'AUTH_REQUIRED';
      error.status = 401;
      throw error;
    }
  }

  const res = await fetch(`${API_BASE_URL}${endpoint}`, { headers, credentials: 'include' as const });
  const requestId = res.headers.get('x-request-id');
  if (requestId) setLastRequestId(requestId);

  if (!res.ok) {
    let errorJson: { error?: { code?: string; message?: string; details?: unknown } } = {};
    try {
      errorJson = await res.json();
    } catch {
      // ignore
    }
    const errorObj = errorJson?.error;
    const message = errorObj?.message || `Download failed with status ${res.status}.`;
    const code = errorObj?.code || 'UNKNOWN_ERROR';
    const error = new Error(message) as Error & { code?: string; details?: unknown; status?: number };
    error.code = code;
    error.status = res.status;
    throw error;
  }

  return res.blob();
}

export const api = {
  // Authenticated customer profile (Django is authoritative for name/phone).
  async getProfile(): Promise<CustomerProfileDTO> {
    return request<CustomerProfileDTO>('/api/auth/me', {}, true, true);
  },

  async updateProfile(payload: { fullName: string; phone: string }): Promise<CustomerProfileDTO> {
    return request<CustomerProfileDTO>('/api/auth/me', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }, true, true);
  },

  // Products
  async getProducts(params: {
    page?: number;
    limit?: number;
    category?: string;
    search?: string;
    sort?: string;
    collection?: string;
    occasion?: string;
    sale?: boolean;
    minPrice?: string;
    maxPrice?: string;
    size?: string;
    color?: string;
    inStock?: boolean;
  } = {}): Promise<PaginatedProductsResponse> {
    const query = new URLSearchParams();
    if (params.page) query.set('page', String(params.page));
    if (params.limit) query.set('limit', String(params.limit));
    if (params.category && params.category !== 'all') query.set('category', params.category);
    if (params.search) query.set('search', params.search);
    if (params.sort) query.set('sort', params.sort);
    if (params.collection) query.set('collection', params.collection);
    if (params.occasion) query.set('occasion', params.occasion);
    if (params.sale) query.set('sale', 'true');
    if (params.minPrice) query.set('minPrice', params.minPrice);
    if (params.maxPrice) query.set('maxPrice', params.maxPrice);
    if (params.size) query.set('size', params.size);
    if (params.color) query.set('color', params.color);
    if (params.inStock) query.set('inStock', 'true');

    return request<PaginatedProductsResponse>(`/api/products/?${query.toString()}`, {}, false);
  },

  async getProduct(idOrSlug: string): Promise<ProductDTO> {
    return request<ProductDTO>(`/api/products/${encodeURIComponent(idOrSlug)}/`, {}, false);
  },

  async getProductReviews(idOrSlug: string): Promise<{ results: ProductReviewDTO[] }> {
    return request<{ results: ProductReviewDTO[] }>(`/api/products/${encodeURIComponent(idOrSlug)}/reviews/`, {}, false);
  },

  async submitProductReview(idOrSlug: string, payload: { rating: number; title: string; body: string }): Promise<{ id: string; message: string }> {
    return request<{ id: string; message: string }>(`/api/products/${encodeURIComponent(idOrSlug)}/reviews/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }, true, true);
  },

  async getAddresses(): Promise<CustomerAddressDTO[]> {
    return request<CustomerAddressDTO[]>('/api/addresses', {}, true, true);
  },

  async createAddress(payload: Omit<CustomerAddressDTO, 'id'>): Promise<CustomerAddressDTO> {
    return request<CustomerAddressDTO>('/api/addresses', {
      method: 'POST',
      body: JSON.stringify(payload),
    }, true, true);
  },

  async updateAddress(id: string, payload: Partial<Omit<CustomerAddressDTO, 'id'>>): Promise<CustomerAddressDTO> {
    return request<CustomerAddressDTO>(`/api/addresses/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }, true, true);
  },

  async deleteAddress(id: string): Promise<void> {
    await request<void>(`/api/addresses/${encodeURIComponent(id)}`, { method: 'DELETE' }, true, true);
  },

  // Categories
  async getCategories(): Promise<CategoryDTO[]> {
    return request<CategoryDTO[]>('/api/categories/', {}, false);
  },

  async getCategory(slug: string): Promise<{ category: CategoryDTO; products: ProductDTO[] }> {
    return request<{ category: CategoryDTO; products: ProductDTO[] }>(`/api/categories/${encodeURIComponent(slug)}/`, {}, false);
  },

  // Cart
  async getCart(): Promise<CartDTO> {
    return request<CartDTO>('/api/cart');
  },

  async addCartItem(variantId: string, quantity: number): Promise<CartDTO> {
    return request<CartDTO>('/api/cart/items', {
      method: 'POST',
      body: JSON.stringify({ variantId, quantity }),
    });
  },

  async updateCartItem(itemId: string, quantity: number): Promise<CartDTO> {
    return request<CartDTO>(`/api/cart/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ quantity }),
    });
  },

  async removeCartItem(itemId: string): Promise<CartDTO> {
    return request<CartDTO>(`/api/cart/items/${encodeURIComponent(itemId)}`, {
      method: 'DELETE',
    });
  },

  async clearCart(): Promise<CartDTO> {
    return request<CartDTO>('/api/cart', {
      method: 'DELETE',
    });
  },

  async mergeCart(): Promise<CartMergeResponse> {
    return request<CartMergeResponse>('/api/cart/merge', {
      method: 'POST',
    }, true, true);
  },

  // Promotions (Django is the single source of truth for rules + math)
  async applyPromoCode(code: string, shippingMethod = 'standard'): Promise<PromotionPricingDTO> {
    return request<PromotionPricingDTO>('/api/promotions/apply', {
      method: 'POST',
      body: JSON.stringify({ code, shippingMethod }),
    });
  },

  async removePromoCode(shippingMethod = 'standard'): Promise<PromotionPricingDTO> {
    return request<PromotionPricingDTO>('/api/promotions/remove', {
      method: 'POST',
      body: JSON.stringify({ shippingMethod }),
    });
  },

  async getAvailablePromotions(shippingMethod = 'standard'): Promise<{
    pricing: PromotionPricingDTO | null;
    available: AvailablePromotionDTO[];
    announcements: PromotionAnnouncementDTO[];
  }> {
    return request<{
      pricing: PromotionPricingDTO | null;
      available: AvailablePromotionDTO[];
      announcements: PromotionAnnouncementDTO[];
    }>(`/api/promotions/available?shippingMethod=${encodeURIComponent(shippingMethod)}`);
  },

  async cancelOrder(orderNumber: string): Promise<OrderDTO> {
    return request<OrderDTO>(`/api/orders/${encodeURIComponent(orderNumber)}/cancel`, {
      method: 'POST',
    }, true, true);
  },

  async receiveOrder(orderNumber: string): Promise<OrderDTO> {
    return request<OrderDTO>(`/api/orders/${encodeURIComponent(orderNumber)}/mark-received-paid`, {
      method: 'POST',
    }, true, true);
  },

  async requestOrderReturn(orderNumber: string, reason = ''): Promise<OrderDTO> {
    return request<OrderDTO>(`/api/orders/${encodeURIComponent(orderNumber)}/return`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }, true, true);
  },

  // Orders
  async createOrder(payload: {
    customer: {
      fullName: string;
      email: string;
      phone: string;
      addressLine1: string;
      addressLine2?: string;
      city: string;
      county: string;
      postalCode?: string;
      deliveryInstructions?: string;
    };
    shippingMethod?: 'standard' | 'express';
    paymentMethod?: 'mpesa' | 'card' | 'cash_on_delivery' | 'pay_on_delivery';
    notes?: string;
    couponCode?: string;
    discountCode?: string;
  }): Promise<OrderDTO> {
    return request<OrderDTO>('/api/orders', {
      method: 'POST',
      body: JSON.stringify(payload),
    }, true, true);
  },

  async getOrder(orderNumber: string): Promise<OrderDTO> {
    return request<OrderDTO>(`/api/orders/${encodeURIComponent(orderNumber)}`, {}, true, true);
  },

  async getOrders(): Promise<{ count: number; results: OrderDTO[] }> {
    return request<{ count: number; results: OrderDTO[] }>('/api/orders', {}, true, true);
  },

  // Receipts
  async getOrderReceipt(orderNumber: string): Promise<ReceiptDTO> {
    return request<ReceiptDTO>(`/api/orders/${encodeURIComponent(orderNumber)}/receipt`, {}, true, true);
  },

  async downloadReceipt(receiptNumber: string): Promise<Blob> {
    return downloadBlob(
      `/api/receipts/${encodeURIComponent(receiptNumber)}/download`,
      true,
    );
  },

  // Payments
  async createPaymentIntent(
    orderNumber: string,
    method: 'mpesa' | 'card' = 'mpesa',
    phoneNumber?: string
  ): Promise<PaymentIntentDTO> {
    return request<PaymentIntentDTO>('/api/payments/create-intent', {
      method: 'POST',
      body: JSON.stringify({ orderNumber, method, phoneNumber }),
    }, true, false);
  },

  async confirmPayment(
    orderNumber: string,
    paymentIntentId: string,
    gatewayReference?: string
  ): Promise<OrderDTO> {
    return request<OrderDTO>('/api/payments/confirm', {
      method: 'POST',
      body: JSON.stringify({ orderNumber, paymentIntentId, gatewayReference }),
    }, true, true);
  },

  async getPaymentStatus(orderNumber: string, paymentIntentId: string): Promise<{ status: 'pending' | 'succeeded' | 'simulated' | 'failed'; simulated?: boolean; failureMessage?: string }> {
    const query = new URLSearchParams({ orderNumber, paymentIntentId });
    return request(`/api/payments/status?${query.toString()}`, {}, true, false);
  },

  // Admin
  async getNotifications(limit = 20): Promise<{ count: number; unread_count: number; results: CustomerNotification[] }> {
    return request<{ count: number; unread_count: number; results: CustomerNotification[] }>(`/api/notifications${limit ? `?limit=${limit}` : ''}`, {}, true, true, false);
  },

  async markNotificationRead(notificationId: string): Promise<{ ok: boolean; unread_count?: number }> {
    return request<{ ok: boolean; unread_count?: number }>(`/api/notifications/${encodeURIComponent(notificationId)}/read/`, {
      method: 'POST',
    }, true, true);
  },

  async markNotificationsPresented(notificationIds: string[]): Promise<{ ok: boolean; presented: string[] }> {
    return request<{ ok: boolean; presented: string[] }>('/api/notifications/presented/', {
      method: 'POST',
      body: JSON.stringify({ ids: notificationIds }),
    }, true, true);
  },

  async markAllNotificationsRead(): Promise<{ ok: boolean; unread_count: number; updated: number }> {
    return request<{ ok: boolean; unread_count: number; updated: number }>('/api/notifications/read-all/', {
      method: 'POST',
    }, true, true);
  },

  async getAdminAccess(): Promise<{ status: string; role: string }> {
    return request<{ status: string; role: string }>('/api/admin/access');
  },

  async adjustInventory(variantId: string, delta: number, reason: string): Promise<{ variantId: string; stockQuantity: number }> {
    return request<{ variantId: string; stockQuantity: number }>(`/api/admin/inventory/${encodeURIComponent(variantId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ delta, reason }),
    });
  },

  async subscribeBackInStock(variantId: string, email: string): Promise<{
    ok: boolean; alreadySubscribed?: boolean; message?: string;
  }> {
    return request<{ ok: boolean; alreadySubscribed?: boolean; message?: string }>('/api/back-in-stock', {
      method: 'POST',
      body: JSON.stringify({ variantId, email }),
    });
  },
};
