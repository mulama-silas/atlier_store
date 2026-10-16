import React, { useState } from 'react';
import { useCart } from '../context/CartContext';
import { useStore } from '../context/StoreContext';
import { useAuth } from '../context/AuthContext';
import { useRouter } from '../router/RouterContext';
import { setPostAuthDestination } from '../utils/postAuthRedirect';
import { QuantitySelector } from '../components/ui/QuantitySelector';
import { Price } from '../components/ui/Price';
import { ProductImage } from '../components/ui/ProductImage';
import { Badge } from '../components/modeza/Badge';
import { Button } from '../components/modeza/Button';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '../components/modeza/Card';
import { Input } from '../components/modeza/Input';
import { Progress } from '../components/modeza/Progress';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Lock,
  ShieldCheck,
  ShoppingBag,
  Tag,
  Trash2,
  Truck,
  X,
} from 'lucide-react';
import { formatPrice, FREE_SHIPPING_THRESHOLD } from '../utils/currency';
import { motion } from 'motion/react';

export const CartPage: React.FC = () => {
  const {
    cart,
    isLoading,
    updateQuantity,
    removeFromCart,
    clearCart,
    subtotal,
    cartCount,
    discountAmount,
    appliedPromo,
    applyPromoCode,
    removePromoCode,
    estimatedShipping,
    estimatedTax,
    estimatedTotal,
  } = useCart();
  const { navigate } = useRouter();
  const { user, isLoading: isAuthLoading } = useAuth();
  const { getProductById } = useStore();
  const [promoCodeInput, setPromoCodeInput] = useState('');
  const [promoMsg, setPromoMsg] = useState<{ text: string; isError: boolean } | null>(null);
  const [orderNote, setOrderNote] = useState('');

  const goToProduct = (productId: string) => {
    const product = getProductById(productId);
    navigate(product ? `/product/${product.slug}` : '/shop');
  };

  const goToCheckout = () => {
    if (isAuthLoading) return;
    if (!user) {
      setPostAuthDestination('/checkout');
      navigate('/account');
      return;
    }
    navigate('/checkout');
  };

  const handleApplyPromo = async (e: React.FormEvent) => {
    e.preventDefault();
    setPromoMsg(null);
    if (!promoCodeInput.trim()) return;

    const result = await applyPromoCode(promoCodeInput.trim());
    if (result.success) {
      setPromoMsg({ text: result.message, isError: false });
      setPromoCodeInput('');
    } else {
      setPromoMsg({ text: result.message, isError: true });
    }
  };

  const handleRemovePromo = async () => {
    await removePromoCode();
    setPromoMsg(null);
  };

  const isFreeShipping = subtotal >= FREE_SHIPPING_THRESHOLD;
  const progressPercent = Math.min(100, Math.max(0, (subtotal / FREE_SHIPPING_THRESHOLD) * 100));
  const remainingForFreeShipping = Math.max(0, FREE_SHIPPING_THRESHOLD - subtotal);
  const checkoutDisabled = isLoading || isAuthLoading;

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 pb-28 sm:px-6 sm:py-12 lg:px-8 lg:pb-0 2xl:max-w-[88rem]">
      <header className="border-b border-[#E8E5DF] pb-6">
        <nav className="mb-3 flex items-center gap-2 text-xs text-[#827E77]" aria-label="Breadcrumb">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="rounded transition-colors hover:text-[#181716] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
          >
            Home
          </button>
          <span aria-hidden="true">/</span>
          <span className="font-medium text-[#181716]" aria-current="page">
            Cart
          </span>
        </nav>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">
              Your selection
            </p>
            <h1 className="font-serif text-3xl font-normal tracking-tight text-[#181716] sm:text-4xl">
              Your cart
            </h1>
          </div>
          <Badge variant="outline" size="lg" className="gap-2">
            <ShoppingBag className="h-3.5 w-3.5" aria-hidden="true" />
            <span>
              {cartCount} {cartCount === 1 ? 'piece' : 'pieces'}
            </span>
          </Badge>
        </div>
      </header>

      {isLoading && cart.length === 0 ? (
        <Card className="mx-auto max-w-2xl border-[#E8E5DF] p-8 text-center shadow-sm sm:p-12" aria-busy="true">
          <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full border border-[#E8E5DF] bg-[#FAF9F6] text-[#A2574F]">
            <ShoppingBag className="h-7 w-7 animate-pulse" strokeWidth={1.5} aria-hidden="true" />
          </div>
          <p className="mb-2 font-serif text-2xl text-[#181716]">Updating your selection</p>
          <p className="mx-auto mb-6 max-w-md text-sm leading-relaxed text-[#63605A]">
            We are syncing your bag with the latest availability and pricing.
          </p>
          <Progress value={55} className="mx-auto max-w-xs" aria-label="Loading your cart" />
        </Card>
      ) : cart.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        >
          <Card className="mx-auto max-w-2xl border-[#E8E5DF] p-8 text-center shadow-sm sm:p-12">
            <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full border border-[#E8E5DF] bg-[#FAF9F6] text-[#A2574F]">
              <ShoppingBag className="h-7 w-7" strokeWidth={1.5} aria-hidden="true" />
            </div>
            <Badge variant="default" size="sm" className="mb-4">Nothing here yet</Badge>
            <h2 className="mb-2 font-serif text-2xl text-[#181716]">Your cart is empty</h2>
            <p className="mx-auto mb-6 max-w-md text-sm leading-relaxed text-[#63605A]">
              Take your time browsing our trans-seasonal collection of organic silk, tailoring, and artisanal accessories.
            </p>
            <Button type="button" variant="primary" size="lg" onClick={() => navigate('/shop')} className="gap-2">
              <span>Discover the collection</span>
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </Card>
        </motion.div>
      ) : (
        <>
          <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-12 lg:gap-10">
            <section className="space-y-4 lg:col-span-8" aria-labelledby="cart-items-heading">
              <Card className="overflow-hidden border-[#E8E5DF] bg-[#FAF9F6] shadow-sm">
                <CardHeader className="flex-row items-center justify-between gap-4 p-5">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#E8E5DF] bg-white text-[#A2574F]">
                      <Truck className="h-4.5 w-4.5" strokeWidth={1.5} aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-[#181716]">
                        {isFreeShipping ? 'Complimentary delivery unlocked' : `${formatPrice(remainingForFreeShipping)} away from complimentary delivery`}
                      </p>
                      <p className="mt-0.5 text-xs text-[#827E77]">
                        {isFreeShipping ? 'Your order qualifies for complimentary delivery.' : `Complimentary delivery starts at ${formatPrice(FREE_SHIPPING_THRESHOLD)}.`}
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isLoading}
                    isLoading={isLoading}
                    onClick={() => void clearCart()}
                    className="shrink-0 gap-1.5 text-[#827E77] hover:text-[#9E332B]"
                    aria-label="Clear all items from cart"
                  >
                    {!isLoading && <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />}
                    {!isLoading && <span>Clear cart</span>}
                  </Button>
                </CardHeader>
                <CardContent className="px-5 pb-5 pt-0 sm:px-6 sm:pb-6">
                  <Progress value={progressPercent} className="h-1.5" aria-label="Progress toward complimentary delivery" />
                  <div className="mt-2 flex items-center justify-between gap-3 text-[10px] text-[#827E77]">
                    <span>{isFreeShipping ? 'Delivery benefit applied' : 'Free delivery threshold'}</span>
                    <span className="font-semibold text-[#63605A]">{isFreeShipping ? 'Complete' : `${Math.round(progressPercent)}%`}</span>
                  </div>
                </CardContent>
              </Card>

              <Card className="overflow-hidden" aria-labelledby="cart-items-heading">
                <CardHeader className="flex-row items-center justify-between gap-3 p-5 sm:p-6">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#A2574F]">Your edit</p>
                    <CardTitle id="cart-items-heading" className="mt-1 text-lg">Selected pieces</CardTitle>
                  </div>
                  <Badge variant="secondary" size="sm">{cartCount} total</Badge>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="divide-y divide-[#F3F1ED]">
                    {cart.map((item) => (
                      <motion.div
                        key={item.id}
                        layout
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                        className="group flex flex-col gap-4 p-4 transition-colors hover:bg-[#FAF9F6] sm:flex-row sm:items-center sm:justify-between sm:p-5"
                      >
                        <div className="flex min-w-0 flex-1 items-start gap-4 sm:items-center">
                          <button
                            type="button"
                            onClick={() => goToProduct(item.productId)}
                            className="h-24 w-20 shrink-0 overflow-hidden rounded-xl bg-[#F4ECE9] shadow-sm transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
                            aria-label={`View ${item.name}`}
                          >
                            <ProductImage
                              src={item.image}
                              alt={item.name}
                              className="h-full w-full"
                              imgClassName="transition-transform duration-300 group-hover:scale-105"
                            />
                          </button>
                          <div className="min-w-0 space-y-1.5">
                            <h3 className="min-w-0 truncate font-serif text-base font-medium text-[#181716]">
                              <button
                                type="button"
                                onClick={() => goToProduct(item.productId)}
                                className="text-left transition-colors hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
                              >
                                {item.name}
                              </button>
                            </h3>
                            <p className="text-xs uppercase tracking-wider text-[#827E77]">
                              {item.color} <span aria-hidden="true">•</span> Size {item.size}
                            </p>
                            <div className="pt-1 sm:hidden">
                              <Price amount={item.price} size="sm" />
                            </div>
                          </div>
                        </div>

                        <div className="flex w-full items-center justify-between gap-4 border-t border-[#F3F1ED] pt-3 sm:w-auto sm:justify-end sm:border-t-0 sm:pt-0">
                          <QuantitySelector
                            quantity={item.quantity}
                            max={item.maxStock}
                            size="sm"
                            disabled={isLoading}
                            onChange={(quantity) => void updateQuantity(item.id, quantity)}
                          />
                          <div className="min-w-[90px] text-right">
                            <Price amount={item.price * item.quantity} size="md" />
                            {item.quantity > 1 && (
                              <p className="mt-0.5 text-[10px] text-[#827E77]">{formatPrice(item.price)} each</p>
                            )}
                          </div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            disabled={isLoading}
                            onClick={() => void removeFromCart(item.id)}
                            className="h-8 w-8 shrink-0 text-[#A29E96] hover:bg-[#FDF2F2] hover:text-[#9E332B]"
                            title="Remove piece"
                            aria-label={`Remove ${item.name}`}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <div className="flex flex-col items-start gap-4 pt-2 sm:flex-row sm:items-center sm:justify-between">
                <Button type="button" variant="ghost" size="sm" onClick={() => navigate('/shop')} className="gap-2 px-0 text-[#181716] hover:bg-transparent hover:text-[#A2574F]">
                  <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>Continue shopping</span>
                </Button>
                <div className="w-full sm:max-w-sm">
                  <Input
                    id="order-note"
                    name="order-note"
                    label="Order note (optional)"
                    placeholder="MODEZA packaging / gift note instructions..."
                    value={orderNote}
                    onChange={(event) => setOrderNote(event.target.value)}
                    className="text-xs"
                  />
                </div>
              </div>
            </section>

            <aside className="space-y-4 lg:col-span-4 lg:sticky lg:top-24" aria-labelledby="cart-summary-heading">
              <Card className="relative overflow-hidden rounded-3xl shadow-xl">
                <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-transparent via-[#A2574F]/25 to-transparent" />
                <CardHeader className="flex-row items-start justify-between gap-3 p-5 pb-5 sm:p-7 sm:pb-6">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#F7ECEA] text-[#A2574F]">
                      <Lock className="h-4 w-4" aria-hidden="true" />
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#A2574F]">Almost there</p>
                      <CardTitle id="cart-summary-heading" className="mt-1 text-lg">Order summary</CardTitle>
                    </div>
                  </div>
                  <Badge variant="success" size="sm" className="gap-1">
                    <ShieldCheck className="h-3 w-3" aria-hidden="true" />
                    Secure
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-6 p-5 pt-0 sm:p-7 sm:pt-0">
                  <form onSubmit={handleApplyPromo} className="space-y-3" aria-label="Promotional voucher">
                    <Input
                      id="promo-code"
                      name="promo-code"
                      label="Promo code"
                      placeholder="e.g. MODEZA10, KARIBU500"
                      value={promoCodeInput}
                      onChange={(event) => setPromoCodeInput(event.target.value)}
                      icon={<Tag className="h-3.5 w-3.5" aria-hidden="true" />}
                      autoComplete="off"
                      spellCheck={false}
                      className="pl-10 text-xs uppercase"
                    />
                    <Button type="submit" variant="secondary" size="sm" disabled={!promoCodeInput.trim()} className="w-full sm:w-auto">
                      Apply code
                    </Button>
                    {promoMsg && (
                      <Badge
                        variant={promoMsg.isError ? 'destructive' : 'success'}
                        size="sm"
                        role={promoMsg.isError ? 'alert' : 'status'}
                        className="w-full justify-start gap-1.5 normal-case tracking-normal"
                      >
                        {promoMsg.isError ? <X className="h-3.5 w-3.5" aria-hidden="true" /> : <Check className="h-3.5 w-3.5" aria-hidden="true" />}
                        <span className="truncate">{promoMsg.text}</span>
                      </Badge>
                    )}
                    {appliedPromo && !promoMsg && (
                      <div className="flex items-center justify-between gap-2 rounded-xl bg-[#E8EFEA] px-3 py-2 text-xs font-medium text-[#2E5A44]">
                        <Badge variant="success" size="sm" className="gap-1.5">
                          <Tag className="h-3 w-3" aria-hidden="true" />
                          {appliedPromo.code || appliedPromo.description} applied
                        </Badge>
                        {appliedPromo.code && <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={handleRemovePromo}
                          className="h-6 w-6 shrink-0 text-[#9E332B] hover:bg-[#FDF2F2]"
                          aria-label={`Remove promo code ${appliedPromo.code}`}
                        >
                          <X className="h-3.5 w-3.5" aria-hidden="true" />
                        </Button>}
                      </div>
                    )}
                  </form>

                  <dl className="space-y-3 border-t border-[#F3F1ED] pt-4 text-xs text-[#63605A]">
                    <div className="flex items-center justify-between gap-4">
                      <dt>Cart subtotal</dt>
                      <dd className="font-medium text-[#181716]">{formatPrice(subtotal)}</dd>
                    </div>
                    {appliedPromo && (
                      <div className="flex items-center justify-between gap-4 text-[#2E5A44]">
                        <dt>{appliedPromo.code ? `Coupon (${appliedPromo.code})` : appliedPromo.description}</dt>
                        <dd className="font-medium">-{formatPrice(discountAmount)}</dd>
                      </div>
                    )}
                    <div className="flex items-center justify-between gap-4">
                      <dt>Estimated shipping</dt>
                      <dd className="font-medium text-[#181716]">
                        {estimatedShipping === 0 ? 'Complimentary' : formatPrice(estimatedShipping)}
                      </dd>
                    </div>
                    <div className="flex items-center justify-between gap-4">
                      <dt>Estimated VAT (16%)</dt>
                      <dd className="font-medium text-[#181716]">{formatPrice(estimatedTax)}</dd>
                    </div>
                    <div className="mt-3 flex items-baseline justify-between gap-4 border-t border-[#F3F1ED] pt-3 text-base font-medium text-[#181716]">
                      <dt className="font-serif">Estimated total</dt>
                      <dd className="font-serif text-xl">{formatPrice(estimatedTotal)}</dd>
                    </div>
                  </dl>
                </CardContent>
                <CardFooter className="block space-y-3 border-t border-[#F3F1ED] p-5 pt-5 sm:p-7 sm:pt-5">
                  <Button
                    type="button"
                    variant="primary"
                    size="lg"
                    fullWidth
                    disabled={checkoutDisabled}
                    isLoading={isAuthLoading}
                    onClick={goToCheckout}
                    className="gap-2"
                    aria-busy={isAuthLoading || isLoading}
                  >
                    {!isAuthLoading && <span>Proceed to checkout</span>}
                    {!isAuthLoading && <ArrowRight className="h-4 w-4" aria-hidden="true" />}
                  </Button>
                  <div className="flex items-center justify-center gap-2 pt-1 text-[11px] text-[#827E77]">
                    <ShieldCheck className="h-3.5 w-3.5 text-[#A2574F]" aria-hidden="true" />
                    <span>256-bit SSL encrypted transaction</span>
                  </div>
                </CardFooter>
              </Card>
            </aside>
          </div>

          <div className="fixed inset-x-0 bottom-0 z-[300] border-t border-[#E8E5DF] bg-white/95 px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3 shadow-[0_-4px_20px_rgb(24_23_22/0.06)] backdrop-blur lg:hidden" role="region" aria-label="Mobile order total">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0 shrink-0">
                <p className="text-[10px] uppercase tracking-wider text-[#827E77]">Estimated total</p>
                <p className="font-serif text-lg leading-tight text-[#181716]">{formatPrice(estimatedTotal)}</p>
              </div>
              <Button
                type="button"
                variant="primary"
                disabled={checkoutDisabled}
                isLoading={isAuthLoading}
                onClick={goToCheckout}
                className="min-w-0 flex-1 gap-1.5 text-xs"
                aria-busy={isAuthLoading || isLoading}
              >
                {!isAuthLoading && <span>Proceed to checkout</span>}
                {!isAuthLoading && <ArrowRight className="h-4 w-4 shrink-0" aria-hidden="true" />}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
