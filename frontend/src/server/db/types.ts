/**
 * Server Database Entity Definitions
 * Relational model representation for boutique e-commerce MVP
 */

export type ProductStatus = 'DRAFT' | 'ACTIVE' | 'ARCHIVED';

export interface CategoryEntity {
  id: string;
  name: string;
  slug: string;
  description?: string;
  imageUrl?: string;
  isActive: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface ProductEntity {
  id: string;
  name: string;
  slug: string;
  description: string;
  tagline?: string;
  details?: string[];
  priceMinor: number; // Stored in minor currency units (e.g. KES cents or exact integer unit)
  compareAtPriceMinor?: number;
  categoryId: string;
  imageUrl?: string;
  images: string[];
  status: ProductStatus;
  isFeatured?: boolean;
  isNewArrival?: boolean;
  isBestSeller?: boolean;
  averageRating?: number | null;
  reviewCount?: number;
  createdAt: Date;
  updatedAt: Date;
}

export interface ProductVariantEntity {
  id: string;
  productId: string;
  sku: string;
  size?: string;
  color?: string;
  colorHex?: string;
  priceMinor?: number; // Overrides product base price if present
  stockQuantity: number;
  isActive: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface CartEntity {
  id: string;
  userId?: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface CartItemEntity {
  id: string;
  cartId: string;
  productId: string;
  variantId: string;
  quantity: number;
  createdAt: Date;
  updatedAt: Date;
}

export interface ShippingAddressEntity {
  fullName: string;
  email: string;
  phone: string;
  addressLine1: string;
  addressLine2?: string;
  city: string;
  county: string;
  postalCode?: string;
  deliveryInstructions?: string;
}

export interface OrderItemEntity {
  id: string;
  orderId: string;
  productId: string;
  variantId: string;
  productName: string;
  variantSku: string;
  variantSize?: string;
  variantColor?: string;
  imageUrl?: string;
  unitPriceMinor: number;
  quantity: number;
  lineTotalMinor: number;
}

export type OrderStatus = 'pending' | 'confirmed' | 'processing' | 'shipped' | 'delivered' | 'received' | 'cancelled';
export type PaymentStatus = 'pending' | 'paid' | 'failed' | 'refunded';

export type PaymentMethod = 'mpesa' | 'card' | 'cash_on_delivery' | 'pay_on_delivery';

export interface OrderEntity {
  id: string;
  orderNumber: string;
  cartId: string;
  customer: ShippingAddressEntity;
  items: OrderItemEntity[];
  subtotalMinor: number;
  shippingCostMinor: number;
  taxMinor: number;
  totalMinor: number;
  shippingMethod: 'standard' | 'express';
  paymentMethod: PaymentMethod;
  status: OrderStatus;
  paymentStatus: PaymentStatus;
  paymentIntentId?: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface PaymentIntentEntity {
  id: string;
  orderId: string;
  orderNumber: string;
  amountMinor: number;
  currency: string;
  method: 'mpesa' | 'card';
  status: 'pending' | 'succeeded' | 'failed';
  clientSecret: string;
  gatewayReference?: string;
  metadata?: Record<string, unknown>;
  createdAt: Date;
  updatedAt: Date;
}

export type ReservationStatus = 'active' | 'committed' | 'released' | 'expired';

export interface StockReservationEntity {
  id: string;
  orderId: string;
  variantId: string;
  quantity: number;
  status: ReservationStatus;
  expiresAt: Date;
  createdAt: Date;
  updatedAt: Date;
}

