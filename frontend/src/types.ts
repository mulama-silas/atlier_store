/**
 * Core Domain & UI Types for the Boutique E-Commerce Platform
 */

export type CategorySlug = 'all' | 'women' | 'men' | 'dresses' | 'tops' | 'bottoms' | 'outerwear' | 'shoes' | 'accessories';

export interface Category {
  id: string;
  name: string;
  slug: CategorySlug;
  description: string;
}

export type VariantSize = 'XS' | 'S' | 'M' | 'L' | 'XL' | 'One Size';

export interface ProductVariant {
  id: string;
  productId: string;
  size: VariantSize;
  color: string;
  colorHex?: string;
  sku: string;
  price: number;
  stockQuantity: number;
  isActive?: boolean;
  isAvailable?: boolean;
}

export interface Product {
  id: string;
  name: string;
  slug: string;
  tagline?: string;
  description: string;
  details: string[];
  price: number;
  compareAtPrice?: number;
  categoryId: string;
  categorySlug: CategorySlug;
  images: string[];
  status: 'active' | 'draft' | 'archived';
  isFeatured?: boolean;
  isNewArrival?: boolean;
  isBestSeller?: boolean;
  createdAt: string;
  updatedAt: string;
  variants: ProductVariant[];
  material?: string;
  careInstructions?: string;
  fitNotes?: string;
  modelSize?: string;
  garmentMeasurements?: Record<string, string | number>;
  averageRating?: number | null;
  reviewCount?: number;
}

export interface CartItem {
  id: string; // Composite key: `${productId}-${variantId}`
  productId: string;
  variantId: string;
  name: string;
  size: VariantSize;
  color: string;
  price: number;
  quantity: number;
  image: string;
  maxStock: number;
}

export interface ShippingAddress {
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  addressLine1: string;
  addressLine2?: string;
  city: string;
  stateOrProvince: string;
  postalCode: string;
  country: string;
}

export type OrderStatus = 'pending' | 'confirmed' | 'processing' | 'shipped' | 'delivered' | 'received' | 'cancelled';
export type PaymentStatus = 'pending' | 'paid' | 'failed' | 'refunded';

export interface OrderItem {
  id: string;
  productId: string;
  variantId: string;
  productName: string;
  variantDetails: string;
  sku: string;
  unitPrice: number;
  quantity: number;
  subtotal: number;
  image: string;
}

export interface OrderTimelineEvent {
  status: OrderStatus;
  title: string;
  description: string;
  timestamp: string;
  completed: boolean;
}

export interface OrderDiscount {
  code: string;
  type: 'percentage' | 'fixed';
  amount: number;
  description: string;
}

export interface Order {
  id: string;
  orderNumber: string;
  customer: ShippingAddress;
  items: OrderItem[];
  subtotal: number;
  discount?: OrderDiscount;
  shippingMethod: 'standard' | 'express';
  shippingCost: number;
  tax: number;
  total: number;
  status: OrderStatus;
  paymentStatus: PaymentStatus;
  paymentMethod?: PaymentMethod;
  notes?: string;
  timeline: OrderTimelineEvent[];
  createdAt: string;
  updatedAt: string;
}

export type PaymentMethod = 'mpesa' | 'card' | 'cash_on_delivery' | 'pay_on_delivery';

export interface CreateOrderInput {
  customer: ShippingAddress;
  items: CartItem[];
  shippingMethod: 'standard' | 'express';
  paymentMethod?: PaymentMethod;
  discountCode?: string;
  notes?: string;
}

export interface DiscountCode {
  code: string;
  description: string;
  type: 'percentage' | 'fixed';
  value: number; // e.g. 10 for 10% or 500 for KSh 500
  minOrderAmount?: number;
  maxDiscount?: number;
  expiresAt?: string;
  isActive: boolean;
}

export interface InventoryLog {
  id: string;
  productId: string;
  variantId: string;
  sku: string;
  type: 'sale' | 'restock' | 'adjustment' | 'cancellation';
  quantityDelta: number;
  previousStock: number;
  newStock: number;
  referenceId: string; // e.g. order number or admin action
  timestamp: string;
}

// UI State & Feedback types
export type ToastType = 'success' | 'info' | 'error';

export interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  description?: string;
}

export interface CustomerNotification {
  id: string;
  category: 'order' | 'payment' | 'delivery' | 'account' | 'promotion' | 'system';
  title: string;
  message: string;
  link?: string;
  isRead: boolean;
  /** True once this notification has been surfaced to the user as a popup/toast */
  presented?: boolean;
  createdAt: string;
}
