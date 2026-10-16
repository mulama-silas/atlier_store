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
  price: number;
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
  price: number;
  compareAtPrice?: number;
  category: { id: string; name: string; slug: string };
  images: string[];
  status: 'DRAFT' | 'ACTIVE' | 'ARCHIVED';
  isFeatured?: boolean;
  isNewArrival?: boolean;
  isBestSeller?: boolean;
  variants: ProductVariantDTO[];
  material?: string;
  careInstructions?: string;
  fitNotes?: string;
  modelSize?: string;
  garmentMeasurements?: Record<string, string | number>;
  averageRating?: number | null;
  reviewCount?: number;
  createdAt: string;
  updatedAt: string;
}

export interface PaginatedProductsResponse {
  data: ProductDTO[];
  pagination: PaginationMeta;
  facets?: { sizes: string[]; colors: string[] };
}

export interface CustomerAddressDTO {
  id: string;
  label: string;
  firstName: string;
  lastName: string;
  phone: string;
  addressLine1: string;
  addressLine2: string;
  county: string;
  subcounty: string;
  city: string;
  postalCode: string;
  country: string;
  isDefault: boolean;
}

export interface ProductReviewDTO {
  id: string;
  rating: number;
  title: string;
  body: string;
  displayName: string;
  isVerified: boolean;
  createdAt: string;
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
  variant: { id: string; sku: string; size?: string; color?: string; stockQuantity: number };
  quantity: number;
  unitPrice: number;
  lineTotal: number;
}

export interface CartPromotionDTO {
  code: string;
  name: string;
  discount: number;
  type: string;
}

export interface AppliedPromotionDTO {
  code: string;
  name: string;
  type: string;
  discount: number;
  shippingDiscount?: number;
}

export interface CartDTO {
  id: string;
  items: CartItemDTO[];
  subtotal: number;
  itemCount: number;
  currency: string;
  discount?: number;
  shippingDiscount?: number;
  tax?: number;
  total?: number;
  promotion?: CartPromotionDTO | null;
  appliedPromotions?: AppliedPromotionDTO[];
}

export interface PromotionPricingDTO {
  subtotal: number;
  eligibleSubtotal: number;
  discount: number;
  shipping: number;
  shippingDiscount: number;
  tax: number;
  total: number;
  currency: string;
  promotion: CartPromotionDTO | null;
  appliedPromotions: AppliedPromotionDTO[];
}

export interface AvailablePromotionDTO {
  name: string;
  type: string;
  code: string;
  badge: string;
  automatic: boolean;
}

export interface PromotionAnnouncementDTO {
  id: string;
  name: string;
  description: string;
  badge: string;
  code: string;
  endsAt: string | null;
}

export interface CartMergeSummaryItem {
  variantId: string;
  productName?: string;
  reason: 'unavailable' | 'out_of_stock' | 'clamped';
}

export interface CartMergeSummary {
  merged: number;
  clamped: number;
  skipped: number;
  skippedItems: CartMergeSummaryItem[];
}

export interface CartMergeResponse extends CartDTO {
  mergeSummary: CartMergeSummary;
}

export interface CartMergeResponse extends CartDTO {
  mergeSummary: CartMergeSummary;
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

export type OrderDTOStatus = 'pending' | 'confirmed' | 'processing' | 'shipped' | 'delivered' | 'received' | 'cancelled';

export interface OrderTimelineItemDTO {
  status: OrderDTOStatus;
  title: string;
  description: string;
  timestamp: string;
  completed: boolean;
}

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
  discount?: number;
  shippingCost: number;
  shippingDiscount?: number;
  promotion?: CartPromotionDTO | null;
  tax: number;
  total: number;
  shippingMethod: 'standard' | 'express';
  paymentMethod: 'mpesa' | 'card' | 'cash_on_delivery' | 'pay_on_delivery';
  status: OrderDTOStatus;
  paymentStatus: 'pending' | 'paid' | 'failed' | 'refunded';
  paymentIntentId?: string;
  currency: string;
  createdAt: string;
  updatedAt: string;
  timeline: OrderTimelineItemDTO[];
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

export interface ReceiptDTO {
  id: string;
  receiptNumber: string;
  orderNumber: string;
  status: 'generated' | 'failed';
  currency: string;
  amount: number;
  issueDate?: string;
  gatewayReference?: string;
  checkoutRequestId?: string;
  emailSentAt?: string;
  downloadPath: string;
  createdAt: string;
}
