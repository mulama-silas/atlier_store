import React, { useState } from 'react';
import { ArrowRight, LoaderCircle, ShoppingBag, Trash2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useCart } from '../context/CartContext';
import { useRouter } from '../router/RouterContext';
import { setPostAuthDestination } from '../utils/postAuthRedirect';
import {
  FREE_SHIPPING_THRESHOLD,
  formatPrice,
} from '../utils/currency';
import {
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Progress,
  ScrollArea,
} from './modeza';
import { Price } from './ui/Price';
import { ProductImage } from './ui/ProductImage';
import { QuantitySelector } from './ui/QuantitySelector';

export const CartDrawer: React.FC = () => {
  const {
    cart,
    isCartDrawerOpen,
    closeCartDrawer,
    updateQuantity,
    removeFromCart,
    subtotal,
    discountAmount,
    appliedPromo,
    estimatedShipping,
    estimatedTotal,
    cartCount,
    isLoading,
  } = useCart();
  const { navigate } = useRouter();
  const { user, isLoading: isAuthLoading } = useAuth();
  const [pendingItemId, setPendingItemId] = useState<string | null>(null);

  const goToCheckout = () => {
    if (isAuthLoading || isLoading) return;
    closeCartDrawer();
    if (!user) {
      setPostAuthDestination('/checkout');
      navigate('/account');
      return;
    }
    navigate('/checkout');
  };

  const handleQuantityChange = async (itemId: string, quantity: number) => {
    if (isLoading || pendingItemId) return;
    setPendingItemId(itemId);
    try {
      await updateQuantity(itemId, quantity);
    } finally {
      setPendingItemId(null);
    }
  };

  const handleRemove = async (itemId: string) => {
    if (isLoading || pendingItemId) return;
    setPendingItemId(itemId);
    try {
      await removeFromCart(itemId);
    } finally {
      setPendingItemId(null);
    }
  };

  const progressPercent = FREE_SHIPPING_THRESHOLD > 0
    ? Math.min(100, Math.round((subtotal / FREE_SHIPPING_THRESHOLD) * 100))
    : 100;
  const amountRemaining = Math.max(0, FREE_SHIPPING_THRESHOLD - subtotal);

  return (
    <Dialog
      open={isCartDrawerOpen}
      onOpenChange={(open) => {
        if (!open) closeCartDrawer();
      }}
    >
      {isCartDrawerOpen && (
        <DialogContent className="left-auto right-0 top-0 flex h-dvh max-h-dvh w-full max-w-full translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-y-0 border-r-0 p-0 shadow-2xl data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right sm:max-w-md lg:max-w-md">
          <div className="flex items-center justify-between border-b border-[#E8E5DF] bg-white px-5 py-4 pr-16 sm:px-6">
            <div className="flex items-center gap-2.5">
              <ShoppingBag className="h-5 w-5 text-[#181716]" strokeWidth={1.5} aria-hidden="true" />
              <DialogTitle className="font-serif text-lg font-medium text-[#181716]">
                Cart ({cartCount})
              </DialogTitle>
            </div>
          </div>
          <DialogDescription className="sr-only">
            Review the pieces in your bag, update quantities, and continue to checkout.
          </DialogDescription>

          <div className="border-b border-[#E8E5DF] bg-[#FAF9F6] px-5 py-3.5 text-xs sm:px-6">
            <div aria-live="polite" aria-atomic="true">
              {amountRemaining > 0 ? (
                <p className="mb-2 text-[#63605A]">
                  Add <span className="font-semibold text-[#181716]">{formatPrice(amountRemaining)}</span> more to qualify for{' '}
                  <span className="font-semibold text-[#181716]">complimentary express shipping</span>.
                </p>
              ) : (
                <p className="mb-2 flex items-center gap-1.5 font-medium text-[#2E5A44]">
                  <span aria-hidden="true">✓</span> Complimentary express shipping unlocked.
                </p>
              )}
              {isLoading && cart.length > 0 && (
                <p className="mb-2 flex items-center gap-1.5 font-medium text-[#A2574F]" role="status">
                  <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  Updating your bag…
                </p>
              )}
            </div>
            <Progress
              value={progressPercent}
              aria-label="Progress toward complimentary express shipping"
              aria-valuetext={`${progressPercent}% of complimentary shipping threshold reached`}
              className={`h-1.5 ${amountRemaining > 0 ? '' : '[&>div]:bg-[#2E5A44]'}`}
            />
          </div>

          <ScrollArea className="min-h-0 flex-1">
            <div
              className="min-h-full space-y-4 px-5 py-4 sm:px-6"
              aria-busy={isLoading}
            >
              {cart.length === 0 ? (
                isLoading ? (
                  <div className="flex min-h-[22rem] flex-col items-center justify-center gap-4 p-6 text-center" role="status">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#F3F1ED] text-[#A2574F]">
                      <LoaderCircle className="h-7 w-7 animate-spin" strokeWidth={1.5} aria-hidden="true" />
                    </div>
                    <div>
                      <h3 className="font-serif text-xl text-[#181716]">Syncing your bag</h3>
                      <p className="mt-1 text-xs text-[#63605A]">Checking the latest availability and pricing.</p>
                    </div>
                  </div>
                ) : (
                  <div className="flex min-h-[22rem] flex-col items-center justify-center gap-4 p-6 text-center">
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#F3F1ED] text-[#A2574F]">
                      <ShoppingBag className="h-7 w-7" strokeWidth={1.5} aria-hidden="true" />
                    </div>
                    <div>
                      <h3 className="font-serif text-xl text-[#181716]">Your cart is empty</h3>
                      <p className="mx-auto mt-1 max-w-xs text-xs leading-relaxed text-[#63605A]">
                        Explore our seasonal capsule of elevated apparel and curated accessories.
                      </p>
                    </div>
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      fullWidth
                      onClick={() => {
                        closeCartDrawer();
                        navigate('/shop');
                      }}
                    >
                      Browse The Collection
                    </Button>
                  </div>
                )
              ) : (
                cart.map((item) => {
                  const isPending = pendingItemId === item.id;
                  return (
                    <Card
                      key={item.id}
                      className="flex gap-3 rounded-xl p-3 shadow-none transition-shadow hover:shadow-sm sm:gap-4"
                    >
                      <div className="h-24 w-20 shrink-0 overflow-hidden rounded-lg bg-[#F4ECE9]">
                        <ProductImage
                          src={item.image}
                          alt={item.name}
                          className="h-full w-full"
                        />
                      </div>

                      <div className="flex flex-1 flex-col justify-between py-0.5">
                        <div>
                          <div className="flex items-start justify-between gap-2">
                            <h4 className="line-clamp-1 font-serif text-sm font-medium text-[#181716]">
                              {item.name}
                            </h4>
                            <button
                              type="button"
                              onClick={() => void handleRemove(item.id)}
                              disabled={isLoading || pendingItemId !== null}
                              className="rounded-md p-1 text-[#A29E96] transition-colors hover:bg-[#FDF2F2] hover:text-[#9E332B] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] disabled:cursor-not-allowed disabled:opacity-40"
                              aria-label={`Remove ${item.name} from cart`}
                            >
                              {isPending ? (
                                <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                              ) : (
                                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                              )}
                            </button>
                          </div>
                          <p className="mt-1 text-[11px] uppercase tracking-wider text-[#827E77]">
                            {item.color} &bull; Size {item.size}
                          </p>
                        </div>

                        <div className="mt-2 flex items-center justify-between gap-2 border-t border-[#F3F1ED] pt-2">
                          <QuantitySelector
                            quantity={item.quantity}
                            max={item.maxStock}
                            size="sm"
                            disabled={isLoading || pendingItemId !== null}
                            onChange={(quantity) => void handleQuantityChange(item.id, quantity)}
                          />
                          <Price amount={item.price * item.quantity} size="sm" />
                        </div>
                      </div>
                    </Card>
                  );
                })
              )}
            </div>
          </ScrollArea>

          {cart.length > 0 && (
            <div className="space-y-4 border-t border-[#E8E5DF] bg-white px-5 py-5 sm:px-6">
              <div className="space-y-1.5 text-xs text-[#63605A]" aria-live="polite">
                <div className="flex justify-between gap-4">
                  <span>Subtotal</span>
                  <span className="font-medium text-[#181716]">{formatPrice(subtotal)}</span>
                </div>
                {appliedPromo && (
                  <div className="flex justify-between gap-4 text-[#2E5A44]">
                    <span>{appliedPromo.code ? `Coupon (${appliedPromo.code})` : appliedPromo.description}</span>
                    <span className="font-medium">-{formatPrice(discountAmount)}</span>
                  </div>
                )}
                <div className="flex justify-between gap-4">
                  <span>Estimated Shipping</span>
                  <span className="font-medium text-[#181716]">
                    {estimatedShipping === 0 ? 'Complimentary' : formatPrice(estimatedShipping)}
                  </span>
                </div>
                <div className="flex justify-between gap-4 border-t border-[#F3F1ED] pt-2 text-sm font-semibold text-[#181716]">
                  <span>Estimated Total</span>
                  <span>{formatPrice(estimatedTotal)}</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 pt-1">
                <Button
                  type="button"
                  variant="outline"
                  fullWidth
                  disabled={isLoading}
                  onClick={() => {
                    closeCartDrawer();
                    navigate('/cart');
                  }}
                >
                  View Cart
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  fullWidth
                  disabled={isLoading}
                  isLoading={isAuthLoading || isLoading}
                  onClick={goToCheckout}
                >
                  Checkout
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      )}
    </Dialog>
  );
};
