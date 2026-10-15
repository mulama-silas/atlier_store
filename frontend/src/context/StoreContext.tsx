import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { Product, ProductVariant, Category, CategorySlug, DiscountCode, InventoryLog, CartItem } from '../types';
import { PROMOTIONAL_CODES } from '../data/promotions';
import { api } from '../services/apiClient';
import { AvailablePromotionDTO, PromotionAnnouncementDTO } from '../types/api';
import { mapProductDtoToDomain } from '../utils/productMapper';

const INVENTORY_LOGS_KEY = 'modeza_inventory_logs_v1';
const ALL_CATEGORY: Category = {
  id: 'all',
  name: 'All Pieces',
  slug: 'all',
  description: 'The complete seasonal wardrobe edit.',
};

const DUMMYJSON_ENABLED = import.meta.env.VITE_USE_DUMMYJSON === 'true';
const DUMMYJSON_BASE_URL = (import.meta.env.VITE_DUMMYJSON_URL || 'https://dummyjson.com').replace(/\/$/, '');

function makeSlug(text: string): string {
  return text.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function normalizeCategorySlug(category: string): CategorySlug {
  const key = category.toLowerCase();
  if (key.includes('dress')) return 'dresses';
  if (key.includes('shirt') || key.includes('top') || key.includes('t-shirt') || key.includes('knit') || key.includes('blouse')) return 'tops';
  if (key.includes('trouser') || key.includes('pant') || key.includes('skirt') || key.includes('jean') || key.includes('bottom')) return 'bottoms';
  if (key.includes('coat') || key.includes('jacket') || key.includes('outer')) return 'outerwear';
  if (key.includes('shoe') || key.includes('heel') || key.includes('sandal')) return 'shoes';
  if (key.includes('watch') || key.includes('bag') || key.includes('accessory') || key.includes('fragrance') || key.includes('beauty') || key.includes('skin') || key.includes('perfume')) return 'accessories';
  if (key.includes('men')) return 'men';
  if (key.includes('women')) return 'women';
  return 'all';
}

async function loadCatalogFromDummyJson(): Promise<{ products: Product[]; categories: Category[] }> {
  const [productsResponse, categoriesResponse] = await Promise.all([
    fetch(`${DUMMYJSON_BASE_URL}/products?limit=100`),
    fetch(`${DUMMYJSON_BASE_URL}/products/categories`),
  ]);

  const productsPayload = await productsResponse.json();
  const categoryPayload = await categoriesResponse.json();

  const rawProducts = Array.isArray(productsPayload?.products) ? productsPayload.products : [];
  const rawCategories = Array.isArray(categoryPayload) ? categoryPayload : [];

  const products = rawProducts.map((item: any): Product => {
    const categorySlug = normalizeCategorySlug(item.category || 'accessories');
    const categoryId = `dummy-${makeSlug(item.category || 'accessories')}`;
    const images = Array.isArray(item.images) && item.images.length > 0
      ? item.images
      : ['https://images.unsplash.com/photo-1551232864-3f9e0f24eb67?q=80&w=1000&auto=format&fit=crop'];

    return {
      id: String(item.id),
      name: item.title || item.name || 'Dummy Product',
      slug: makeSlug(item.title || item.name || `product-${item.id}`),
      tagline: item.description || '',
      description: item.description || '',
      details: [
        item.brand || 'DummyJSON',
        item.description || '',
        `${item.stock ?? 0} units available`,
        item.category || 'Marketplace',
      ],
      price: Number(item.price || 0),
      compareAtPrice: Number((item.price || 0) * 1.2),
      categoryId,
      categorySlug,
      images,
      status: 'active',
      isFeatured: Boolean(item.isFeatured),
      isNewArrival: Boolean(item.isNewArrival),
      isBestSeller: Boolean(item.isBestSeller),
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      variants: [
        {
          id: `dummy-variant-${item.id}`,
          productId: String(item.id),
          size: 'One Size' as any,
          color: item.category || 'Neutral',
          sku: `DUMMY-${item.id}`,
          price: Number(item.price || 0),
          stockQuantity: Number(item.stock || 0),
        },
      ],
    };
  });

  const categories = [ALL_CATEGORY, ...rawCategories.map((entry: any): Category => {
    const name = typeof entry === 'string' ? entry : entry?.name || entry?.slug || 'Category';
    const slug = typeof entry === 'string' ? entry : entry?.slug || makeSlug(name);
    return {
      id: `dummy-${slug}`,
      name: name.charAt(0).toUpperCase() + name.slice(1),
      slug: normalizeCategorySlug(slug) as CategorySlug,
      description: `Test category sourced from dummyjson: ${name}`,
    };
  })];

  return { products, categories };
}

export interface StockValidationResult {
  available: boolean;
  currentStock: number;
  message?: string;
}

export interface PromoValidationResult {
  valid: boolean;
  discount: DiscountCode | null;
  discountAmount: number;
  message: string;
}

export interface StoreContextType {
  products: Product[];
  categories: Category[];
  promotions: DiscountCode[];
  availablePromotions: AvailablePromotionDTO[];
  promotionAnnouncements: PromotionAnnouncementDTO[];
  refreshPromotions: () => Promise<void>;
  inventoryLogs: InventoryLog[];
  totalCatalogStock: number;
  refreshCatalog: () => Promise<void>;
  getProductBySlug: (slug: string) => Product | undefined;
  getProductById: (id: string) => Product | undefined;
  getVariant: (productId: string, variantId: string) => ProductVariant | undefined;
  checkStock: (productId: string, variantId: string, requestedQty: number) => StockValidationResult;
  checkBatchStock: (items: CartItem[]) => { available: boolean; errors: string[] };
  deductInventoryForOrder: (
    items: { productId: string; variantId: string; quantity: number; sku?: string }[],
    orderNumber: string
  ) => boolean;
  restockInventoryForOrder: (
    items: { productId: string; variantId: string; quantity: number; sku?: string }[],
    orderNumber: string
  ) => void;
  updateVariantStock: (productId: string, variantId: string, newStock: number) => void;
  validatePromoCode: (code: string, subtotal: number) => PromoValidationResult;
  resetCatalogToDefault: () => void;
}

const StoreContext = createContext<StoreContextType | undefined>(undefined);

export const StoreProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([ALL_CATEGORY]);
  const [availablePromotions, setAvailablePromotions] = useState<AvailablePromotionDTO[]>([]);
  const [promotionAnnouncements, setPromotionAnnouncements] = useState<PromotionAnnouncementDTO[]>([]);
  const refreshInFlight = useRef(false);

  // Server-driven promotion discovery (badges/banners). Best-effort: the
  // shop works without it; Django remains the authority at checkout.
  const refreshPromotions = useCallback(async () => {
    try {
      const result = await api.getAvailablePromotions();
      setAvailablePromotions(result.available ?? []);
      setPromotionAnnouncements(result.announcements ?? []);
    } catch {
      // offline / backend unreachable — keep the previous list
    }
  }, []);

  const loadCatalogFromApi = useCallback(async () => {
    if (refreshInFlight.current) return;
    refreshInFlight.current = true;

    try {
      if (DUMMYJSON_ENABLED) {
        const dummyCatalog = await loadCatalogFromDummyJson();
        setProducts(dummyCatalog.products);
        setCategories(dummyCatalog.categories);
        refreshInFlight.current = false;
        return;
      }

      const [productsResponse, categoriesResponse] = await Promise.all([
        api.getProducts({ limit: 100 }),
        api.getCategories(),
      ]);

      const mappedProducts = productsResponse.data.map(mapProductDtoToDomain);
      const mappedCategories = categoriesResponse.length > 0
        ? [ALL_CATEGORY, ...categoriesResponse.map((cat) => ({
            id: cat.id,
            name: cat.name,
            slug: cat.slug as CategorySlug,
            description: cat.description || '',
          }))]
        : [ALL_CATEGORY];

      setProducts(mappedProducts);
      setCategories(mappedCategories);
    } catch (error) {
      console.warn('[StoreContext] Failed to load catalog from Django API.', error);
      setProducts([]);
      setCategories((currentCategories) =>
        currentCategories.length > 0 ? currentCategories : [ALL_CATEGORY]
      );
    } finally {
      refreshInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void loadCatalogFromApi();
    void refreshPromotions();
    const promotionsInterval = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void refreshPromotions();
      }
    }, 30000);

    const refreshOnFocus = () => {
      if (document.visibilityState === 'visible') {
        void loadCatalogFromApi();
      }
    };
    const refreshInterval = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void loadCatalogFromApi();
      }
    }, 5000);

    document.addEventListener('visibilitychange', refreshOnFocus);
    window.addEventListener('focus', refreshOnFocus);

    return () => {
      window.clearInterval(promotionsInterval);
      window.clearInterval(refreshInterval);
      document.removeEventListener('visibilitychange', refreshOnFocus);
      window.removeEventListener('focus', refreshOnFocus);
    };
  }, [loadCatalogFromApi, refreshPromotions]);

  const [inventoryLogs, setInventoryLogs] = useState<InventoryLog[]>(() => {
    try {
      const saved = localStorage.getItem(INVENTORY_LOGS_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {
      // fallback
    }
    return [];
  });

  // Persist logs when modified
  useEffect(() => {
    try {
      localStorage.setItem(INVENTORY_LOGS_KEY, JSON.stringify(inventoryLogs));
    } catch {
      // ignore
    }
  }, [inventoryLogs]);

  // Total stock calculated across all product variants
  const totalCatalogStock = products.reduce(
    (acc, p) => acc + p.variants.reduce((vAcc, v) => vAcc + v.stockQuantity, 0),
    0
  );

  const getProductBySlug = useCallback(
    (slug: string): Product | undefined => {
      return products.find((p) => p.slug === slug);
    },
    [products]
  );

  const getProductById = useCallback(
    (id: string): Product | undefined => {
      return products.find((p) => p.id === id);
    },
    [products]
  );

  const getVariant = useCallback(
    (productId: string, variantId: string): ProductVariant | undefined => {
      const prod = products.find((p) => p.id === productId);
      return prod?.variants.find((v) => v.id === variantId);
    },
    [products]
  );

  const checkStock = useCallback(
    (productId: string, variantId: string, requestedQty: number): StockValidationResult => {
      const prod = products.find((p) => p.id === productId);
      if (!prod) {
        return { available: false, currentStock: 0, message: 'Piece not found in collection.' };
      }
      const variant = prod.variants.find((v) => v.id === variantId);
      if (!variant) {
        return { available: false, currentStock: 0, message: 'Variant not found.' };
      }

      if (variant.stockQuantity <= 0) {
        return {
          available: false,
          currentStock: 0,
          message: `${prod.name} (${variant.size}) is currently sold out.`,
        };
      }

      if (requestedQty > variant.stockQuantity) {
        return {
          available: false,
          currentStock: variant.stockQuantity,
          message: `Only ${variant.stockQuantity} piece(s) available in size ${variant.size}.`,
        };
      }

      return { available: true, currentStock: variant.stockQuantity };
    },
    [products]
  );

  const checkBatchStock = useCallback(
    (items: CartItem[]): { available: boolean; errors: string[] } => {
      const errors: string[] = [];
      for (const item of items) {
        const result = checkStock(item.productId, item.variantId, item.quantity);
        if (!result.available) {
          errors.push(result.message || `${item.name} (${item.size}) stock exceeded.`);
        }
      }
      return { available: errors.length === 0, errors };
    },
    [checkStock]
  );

  const deductInventoryForOrder = useCallback(
    (
      items: { productId: string; variantId: string; quantity: number; sku?: string }[],
      orderNumber: string
    ): boolean => {
      const newLogs: InventoryLog[] = [];
      let updatedProducts = [...products];

      for (const item of items) {
        const pIndex = updatedProducts.findIndex((p) => p.id === item.productId);
        if (pIndex === -1) continue;

        const targetProduct = updatedProducts[pIndex];
        const vIndex = targetProduct.variants.findIndex((v) => v.id === item.variantId);
        if (vIndex === -1) continue;

        const targetVariant = targetProduct.variants[vIndex];
        const prevStock = targetVariant.stockQuantity;
        const newStock = Math.max(0, prevStock - item.quantity);

        // Record audit transaction
        newLogs.push({
          id: `log-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
          productId: item.productId,
          variantId: item.variantId,
          sku: targetVariant.sku || item.sku || 'SKU-UNKNOWN',
          type: 'sale',
          quantityDelta: -item.quantity,
          previousStock: prevStock,
          newStock: newStock,
          referenceId: orderNumber,
          timestamp: new Date().toISOString(),
        });

        // Clone variant and product
        const updatedVariants = [...targetProduct.variants];
        updatedVariants[vIndex] = {
          ...targetVariant,
          stockQuantity: newStock,
        };

        updatedProducts[pIndex] = {
          ...targetProduct,
          variants: updatedVariants,
          updatedAt: new Date().toISOString(),
        };
      }

      setProducts(updatedProducts);
      setInventoryLogs((prev) => [...newLogs, ...prev]);
      return true;
    },
    [products]
  );

  const restockInventoryForOrder = useCallback(
    (
      items: { productId: string; variantId: string; quantity: number; sku?: string }[],
      orderNumber: string
    ): void => {
      const newLogs: InventoryLog[] = [];
      let updatedProducts = [...products];

      for (const item of items) {
        const pIndex = updatedProducts.findIndex((p) => p.id === item.productId);
        if (pIndex === -1) continue;

        const targetProduct = updatedProducts[pIndex];
        const vIndex = targetProduct.variants.findIndex((v) => v.id === item.variantId);
        if (vIndex === -1) continue;

        const targetVariant = targetProduct.variants[vIndex];
        const prevStock = targetVariant.stockQuantity;
        const newStock = prevStock + item.quantity;

        newLogs.push({
          id: `log-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
          productId: item.productId,
          variantId: item.variantId,
          sku: targetVariant.sku,
          type: 'cancellation',
          quantityDelta: item.quantity,
          previousStock: prevStock,
          newStock: newStock,
          referenceId: orderNumber,
          timestamp: new Date().toISOString(),
        });

        const updatedVariants = [...targetProduct.variants];
        updatedVariants[vIndex] = {
          ...targetVariant,
          stockQuantity: newStock,
        };

        updatedProducts[pIndex] = {
          ...targetProduct,
          variants: updatedVariants,
          updatedAt: new Date().toISOString(),
        };
      }

      setProducts(updatedProducts);
      setInventoryLogs((prev) => [...newLogs, ...prev]);
    },
    [products]
  );

  const updateVariantStock = useCallback(
    (productId: string, variantId: string, newStock: number) => {
      setProducts((prevProducts) =>
        prevProducts.map((prod) => {
          if (prod.id !== productId) return prod;
          return {
            ...prod,
            variants: prod.variants.map((v) =>
              v.id === variantId ? { ...v, stockQuantity: Math.max(0, newStock) } : v
            ),
            updatedAt: new Date().toISOString(),
          };
        })
      );
    },
    []
  );

  const validatePromoCode = useCallback(
    (code: string, subtotal: number): PromoValidationResult => {
      const cleanCode = code.trim().toUpperCase();
      if (!cleanCode) {
        return { valid: false, discount: null, discountAmount: 0, message: 'Please enter a coupon code.' };
      }

      const match = PROMOTIONAL_CODES.find((p) => p.code.toUpperCase() === cleanCode && p.isActive);
      if (!match) {
        return { valid: false, discount: null, discountAmount: 0, message: 'Voucher code is invalid or expired.' };
      }

      if (match.minOrderAmount && subtotal < match.minOrderAmount) {
        return {
          valid: false,
          discount: null,
          discountAmount: 0,
          message: `This coupon requires a minimum bag value of KSh ${match.minOrderAmount.toLocaleString()}.`,
        };
      }

      let calculatedDiscount = 0;
      if (match.type === 'percentage') {
        calculatedDiscount = (subtotal * match.value) / 100;
        if (match.maxDiscount && calculatedDiscount > match.maxDiscount) {
          calculatedDiscount = match.maxDiscount;
        }
      } else {
        calculatedDiscount = match.value;
      }

      calculatedDiscount = Math.min(subtotal, Math.round(calculatedDiscount));

      return {
        valid: true,
        discount: match,
        discountAmount: calculatedDiscount,
        message: `${match.description} applied.`,
      };
    },
    []
  );

  const resetCatalogToDefault = useCallback(() => {
    setProducts([]);
    setCategories([ALL_CATEGORY]);
    setInventoryLogs([]);
    try {
      localStorage.removeItem(INVENTORY_LOGS_KEY);
    } catch {
      // ignore
    }
    void loadCatalogFromApi();
  }, [loadCatalogFromApi]);

  return (
    <StoreContext.Provider
      value={{
        products,
        categories,
        refreshCatalog: loadCatalogFromApi,
        promotions: PROMOTIONAL_CODES,
        availablePromotions,
        promotionAnnouncements,
        refreshPromotions,
        inventoryLogs,
        totalCatalogStock,
        getProductBySlug,
        getProductById,
        getVariant,
        checkStock,
        checkBatchStock,
        deductInventoryForOrder,
        restockInventoryForOrder,
        updateVariantStock,
        validatePromoCode,
        resetCatalogToDefault,
      }}
    >
      {children}
    </StoreContext.Provider>
  );
};

export const useStore = (): StoreContextType => {
  const context = useContext(StoreContext);
  if (!context) {
    throw new Error('useStore must be used within a StoreProvider');
  }
  return context;
};
