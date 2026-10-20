export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export interface PaginationMeta {
  page: number;
  limit: number;
  total: number;
  totalPages: number;
}

export interface CategoryDTO {
  id: string;
  name: string;
  slug: string;
  description?: string;
  imageUrl?: string;
  isActive: boolean;
}

export interface ProductVariantDTO {
  id: string;
  sku: string;
  size?: string;
  color?: string;
  colorHex?: string;
  price: number; // In major currency units (e.g. 24500)
  stockQuantity: number;
  isAvailable: boolean;
  isActive: boolean;
}

export interface ProductDTO {
  id: string;
  name: string;
  slug: string;
  tagline?: string;
  description: string;
  details?: string[];
  price: number; // In major currency units
  compareAtPrice?: number;
  category: {
    id: string;
    name: string;
    slug: string;
  };
  imageUrl?: string;
  images: string[];
  status: 'DRAFT' | 'ACTIVE' | 'ARCHIVED';
  isFeatured?: boolean;
  isNewArrival?: boolean;
  isBestSeller?: boolean;
  averageRating?: number | null;
  reviewCount?: number;
  variants: ProductVariantDTO[];
  createdAt: string;
  updatedAt: string;
}

export interface PaginatedProductsResponse {
  data: ProductDTO[];
  pagination: PaginationMeta;
}

export interface CartItemDTO {
  id: string;
  productId: string;
  variantId: string;
  product: {
    id: string;
    name: string;
    slug: string;
    image?: string;
    imageUrl?: string;
    images?: string[];
  };
  variant: {
    id: string;
    sku: string;
    size?: string;
    color?: string;
    stockQuantity: number;
  };
  quantity: number;
  unitPrice: number; // Major units (e.g. 24500)
  lineTotal: number; // Major units (unitPrice * quantity)
}

export interface CartDTO {
  id: string;
  items: CartItemDTO[];
  subtotal: number; // Major units (sum of lineTotal)
  itemCount: number; // Sum of quantities
  currency: string;
}

export interface OrderItemDTO {
  id: string;
  productId: string;
  variantId: string;
  productName: string;
  variantSku: string;
  variantSize?: string;
  variantColor?: string;
  imageUrl?: string;
  unitPrice: number;
  quantity: number;
  lineTotal: number;
}

export type PaymentMethod = 'mpesa' | 'card' | 'cash_on_delivery' | 'pay_on_delivery';

export interface OrderDTO {
  id: string;
  orderNumber: string;
  cartId: string;
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
  items: OrderItemDTO[];
  subtotal: number;
  shippingCost: number;
  tax: number;
  total: number;
  shippingMethod: 'standard' | 'express';
  paymentMethod: PaymentMethod;
  status: 'pending' | 'confirmed' | 'processing' | 'shipped' | 'delivered' | 'received' | 'cancelled';
  paymentStatus: 'pending' | 'paid' | 'failed' | 'refunded';
  paymentIntentId?: string;
  currency: string;
  createdAt: string;
  updatedAt: string;
}

export interface PaymentIntentDTO {
  id: string;
  orderNumber: string;
  amount: number;
  currency: string;
  method: 'mpesa' | 'card';
  status: 'pending' | 'succeeded' | 'failed';
  clientSecret: string;
  gatewayReference?: string;
}

