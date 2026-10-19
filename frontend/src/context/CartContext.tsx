import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { CartItem, Product, ProductVariant, VariantSize, ToastType } from '../types';
import { useAuth } from './AuthContext';
import { FREE_SHIPPING_THRESHOLD, STANDARD_SHIPPING_COST, VAT_RATE } from '../utils/currency';
import { api, resetCartId } from '../services/apiClient';
import { CartDTO } from '../types/api';
import { SimpleToast } from '../components/ui/Toast';

interface AppliedPromo {
  code: string;
  discountAmount: number;
  description: string;
}

interface CartContextType {
  cart: CartItem[];
  addToCart: (product: Product, variant: ProductVariant, quantity: number) => Promise<{ success: boolean; message?: string }>;
  updateQuantity: (cartItemId: string, newQuantity: number) => Promise<void>;
  removeFromCart: (cartItemId: string) => Promise<void>;
  clearCart: () => Promise<void>;
  refreshCart: () => Promise<void>;
  isLoading: boolean;
  cartCount: number;
  subtotal: number;
  discountAmount: number;
  shippingDiscountAmount: number;
  appliedPromo: AppliedPromo | null;
  applyPromoCode: (code: string, shippingMethod?: 'standard' | 'express') => Promise<{ success: boolean; message: string }>;
  removePromoCode: (shippingMethod?: 'standard' | 'express') => Promise<void>;
  refreshPromotionPricing: (shippingMethod?: 'standard' | 'express') => Promise<void>;
  estimatedShipping: number;
  estimatedTax: number;
  estimatedTotal: number;
  isCartDrawerOpen: boolean;
  openCartDrawer: () => void;
  closeCartDrawer: () => void;
}

const CartContext = createContext<CartContextType | undefined>(undefined);

/**
 * The backend wraps validation failures in {"error": {"code", "message", "details"}}
 * where `details` carries field-level reasons (e.g. {'quantity': 'Only N items are
 * available.'}, {'variantId': 'Variant is not available.'}) while the top-level
 * message stays generic ("Request validation failed."). Surface the field-level
 * reason to the customer instead of the generic envelope message.
 */
function friendlyCartError(error: Error & { code?: string; details?: Record<string, string> }): string {
  const details = error?.details;
  if (details && typeof details === 'object') {
    const values = Object.values(details).filter((v): v is string => typeof v === 'string');
    const first = values[0];
    if (first) return first;
  }
  if (error?.code === 'CART_ITEM_UNAVAILABLE' || error?.code === 'VARIANT_NOT_AVAILABLE') {
    return 'This piece is no longer available on the modeza boutique.';
  }
  return error?.message || 'Unable to add item to bag.';
}

function mapCartDtoToItems(dto: CartDTO): CartItem[] {
  return dto.items.map((item) => ({
    id: item.id,
    productId: item.productId,
    variantId: item.variantId,
    name: item.product.name,
    size: (item.variant.size || 'One Size') as VariantSize,
    color: item.variant.color || '',
    price: item.unitPrice,
    quantity: item.quantity,
    image: item.product.image || item.product.imageUrl || item.product.images?.[0] || '',
    maxStock: item.variant.stockQuantity,
  }));
}

export const CartProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  const [cart, setCart] = useState<CartItem[]>([]);
  const [serverSubtotal, setServerSubtotal] = useState<number>(0);
  const [serverItemCount, setServerItemCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [appliedPromo, setAppliedPromo] = useState<AppliedPromo | null>(null);
  const [serverDiscount, setServerDiscount] = useState<number>(0);
  const [serverShippingDiscount, setServerShippingDiscount] = useState<number>(0);
  const [isCartDrawerOpen, setIsCartDrawerOpen] = useState(false);
  const [syncToast, setSyncToast] = useState<{ message: string; type: ToastType } | null>(null);
  const previousUser = useRef<{ id: string | undefined } | null | undefined>(undefined);

  const applyServerCart = useCallback((dto: CartDTO) => {
    setCart(mapCartDtoToItems(dto));
    setServerSubtotal(dto.subtotal);
    setServerItemCount(dto.itemCount);
    setServerShippingDiscount(dto.shippingDiscount ?? 0);
    // Django is the authority on promotion math: prefer server values.
    if (dto.promotion) {
      setServerDiscount(dto.discount ?? dto.promotion.discount ?? 0);
      setAppliedPromo({
        code: dto.promotion.code,
        discountAmount: dto.discount ?? dto.promotion.discount ?? 0,
        description: dto.promotion.name,
      });
    } else if ((dto.discount ?? 0) > 0) {
      setServerDiscount(dto.discount ?? 0);
      setAppliedPromo(null);
    } else {
      setServerDiscount(0);
      setServerShippingDiscount(0);
      setAppliedPromo(null);
    }
  }, []);

  // Synchronize cart with authoritative server state on load
  const refreshCart = useCallback(async () => {
    try {
      setIsLoading(true);
      const serverCart = await api.getCart();
      applyServerCart(serverCart);
    } catch (err) {
      console.warn('[CartContext] Failed to load server cart, using fallback:', err);
    } finally {
      setIsLoading(false);
    }
  }, [applyServerCart]);

  useEffect(() => {
    refreshCart();
  }, [refreshCart]);

  /**
   * On sign-in, fold any anonymous guest bag into the authenticated account
   * bag (server-authoritative). The response carries the canonical account
   * cart key in ``x-cart-id``, which the api client persists automatically so
   * subsequent requests reuse the same account cart. Stock risks surfaced by
   * the merge are reported to the customer instead of being silently dropped.
   */
  const mergeGuestCartWithAccount = useCallback(async () => {
    try {
      const result = await api.mergeCart();
      applyServerCart(result);
      const summary = result.mergeSummary;
      if (summary && (summary.merged > 0 || summary.clamped > 0 || summary.skipped > 0)) {
        const notes: string[] = [];
        if (summary.merged > 0) {
          notes.push(`${summary.merged} item${summary.merged === 1 ? '' : 's'} moved to your account bag.`);
        }
        if (summary.clamped > 0) {
          notes.push(`Quantity ${summary.clamped === 1 ? 'was' : 'were'} adjusted to available stock.`);
        }
        if (summary.skipped > 0) {
          notes.push(`${summary.skipped} item${summary.skipped === 1 ? ' was' : 's were'} removed — no longer available.`);
        }
        setSyncToast({ message: notes.join(' '), type: summary.skipped > 0 ? 'info' : 'success' });
      }
    } catch (err) {
      console.warn('[CartContext] Failed to merge guest cart with account:', err);
      // Account merge isn't critical to browsing; keep the authoritative list.
      await refreshCart();
    }
  }, []);

  useEffect(() => {
    if (previousUser.current === undefined) {
      previousUser.current = user;
      return;
    }
    const hadUser = Boolean(previousUser.current);
    const hasUser = Boolean(user);
    previousUser.current = user;

    if (hasUser && !hadUser) {
      void mergeGuestCartWithAccount();
    } else if (!hasUser && hadUser) {
      // Signed out: drop the account cart key so the next session starts with
      // a fresh anonymous bag and never leaks the previous user's cart.
      resetCartId();
      setCart([]);
      setServerSubtotal(0);
      setServerItemCount(0);
      setServerDiscount(0);
      setAppliedPromo(null);
    }
  }, [user, mergeGuestCartWithAccount]);

  const addToCart = async (
    product: Product,
    variant: ProductVariant,
    quantity: number
  ): Promise<{ success: boolean; message?: string }> => {
    try {
      setIsLoading(true);
      const updatedServerCart = await api.addCartItem(variant.id, quantity);
      applyServerCart(updatedServerCart);
      return { success: true };
    } catch (err: unknown) {
      const errorObj = err as Error & { code?: string; details?: Record<string, string> };
      return { success: false, message: friendlyCartError(errorObj) };
    } finally {
      setIsLoading(false);
    }
  };

  const updateQuantity = async (cartItemId: string, newQuantity: number): Promise<void> => {
    try {
      if (newQuantity <= 0) {
        await removeFromCart(cartItemId);
        return;
      }
      setIsLoading(true);
      const updatedServerCart = await api.updateCartItem(cartItemId, newQuantity);
      applyServerCart(updatedServerCart);
    } catch (err) {
      console.error('[CartContext] Update quantity failed:', err);
      // Re-fetch authoritative state to undo invalid optimistic values
      await refreshCart();
    } finally {
      setIsLoading(false);
    }
  };

  const removeFromCart = async (cartItemId: string): Promise<void> => {
    try {
      setIsLoading(true);
      const updatedServerCart = await api.removeCartItem(cartItemId);
      applyServerCart(updatedServerCart);
    } catch (err) {
      console.error('[CartContext] Remove item failed:', err);
      await refreshCart();
    } finally {
      setIsLoading(false);
    }
  };

  const clearCart = async (): Promise<void> => {
    try {
      setIsLoading(true);
      const cleared = await api.clearCart();
      applyServerCart(cleared);
      setServerDiscount(0);
      setServerShippingDiscount(0);
      setAppliedPromo(null);
    } catch (err) {
      console.error('[CartContext] Clear cart failed:', err);
      setCart([]);
      setServerDiscount(0);
      setServerShippingDiscount(0);
      setAppliedPromo(null);
    } finally {
      setIsLoading(false);
    }
  };

  const cartCount = cart.length;
  const subtotal = serverSubtotal || cart.reduce((total, item) => total + item.price * item.quantity, 0);

  const applyPromoCode = async (code: string, shippingMethod: 'standard' | 'express' = 'standard'): Promise<{ success: boolean; message: string }> => {
    const normalized = code.trim();
    if (!normalized) return { success: false, message: 'Please enter a coupon code.' };
    // Server-first: Django validates eligibility and computes the discount.
    try {
      const pricing = await api.applyPromoCode(normalized, shippingMethod);
      const promo = pricing.appliedPromotions.find((entry) => entry.code.toUpperCase() === normalized.toUpperCase())
        ?? pricing.promotion;
      if (promo) {
        setServerDiscount(pricing.discount);
        setServerShippingDiscount(pricing.shippingDiscount);
        setAppliedPromo({ code: promo.code || normalized, discountAmount: pricing.discount, description: promo.name });
        const saved = pricing.discount + pricing.shippingDiscount;
        const message = pricing.shippingDiscount > 0 && pricing.discount === 0
          ? `${promo.name} applied. Delivery is complimentary.`
          : `${promo.name} applied — you saved ${saved.toLocaleString()} KES.`;
        return { success: true, message };
      }
      return { success: false, message: 'This code did not apply to your bag.' };
    } catch (err) {
      const serverMessage = (err as Error)?.message || '';
      return { success: false, message: serverMessage || 'We could not verify this coupon. Please try again.' };
    }
  };

  const removePromoCode = async (shippingMethod: 'standard' | 'express' = 'standard') => {
    try {
      const pricing = await api.removePromoCode(shippingMethod);
      setServerDiscount(pricing.discount);
      setServerShippingDiscount(pricing.shippingDiscount);
      const promo = pricing.promotion ?? pricing.appliedPromotions[0] ?? null;
      setAppliedPromo(promo ? {
        code: promo.code,
        discountAmount: promo.discount ?? pricing.discount,
        description: promo.name,
      } : null);
    } catch {
      setServerDiscount(0);
      setServerShippingDiscount(0);
      setAppliedPromo(null);
    }
  };

  const refreshPromotionPricing = useCallback(async (shippingMethod: 'standard' | 'express' = 'standard') => {
    try {
      const result = await api.getAvailablePromotions(shippingMethod);
      const pricing = result.pricing;
      if (!pricing) return;
      setServerDiscount(pricing.discount);
      setServerShippingDiscount(pricing.shippingDiscount);
      const promo = pricing.appliedPromotions.find((entry) => entry.code) ?? pricing.promotion;
      setAppliedPromo(promo ? {
        code: promo.code,
        discountAmount: pricing.discount,
        description: promo.name,
      } : null);
    } catch {
      // Keep the last server quote visible if refreshing it fails.
    }
  }, []);

  const localDiscount = appliedPromo ? appliedPromo.discountAmount : 0;
  const discountAmount = serverDiscount > 0 ? serverDiscount : localDiscount;
  const baseEstimatedShipping = subtotal === 0 || subtotal >= FREE_SHIPPING_THRESHOLD
    ? 0
    : Math.round(subtotal * 0.2);
  const estimatedShipping = Math.max(0, baseEstimatedShipping - serverShippingDiscount);
  const taxableSubtotal = Math.max(0, subtotal - discountAmount);
  const estimatedTax = Math.round(taxableSubtotal * VAT_RATE);
  const estimatedTotal = taxableSubtotal + estimatedShipping + estimatedTax;

  return (
    <CartContext.Provider
      value={{
        cart,
        addToCart,
        updateQuantity,
        removeFromCart,
        clearCart,
        refreshCart,
        isLoading,
        cartCount,
        subtotal,
        discountAmount,
        shippingDiscountAmount: serverShippingDiscount,
        appliedPromo,
        applyPromoCode,
        removePromoCode,
        refreshPromotionPricing,
        estimatedShipping,
        estimatedTax,
        estimatedTotal,
        isCartDrawerOpen,
        openCartDrawer: () => setIsCartDrawerOpen(true),
        closeCartDrawer: () => setIsCartDrawerOpen(false),
      }}
    >
      {children}
      {syncToast && (
        <SimpleToast type={syncToast.type} message={syncToast.message} onClose={() => setSyncToast(null)} />
      )}
    </CartContext.Provider>
  );
};

export const useCart = (): CartContextType => {
  const context = useContext(CartContext);
  if (!context) {
    throw new Error('useCart must be used within a CartProvider');
  }
  return context;
};
