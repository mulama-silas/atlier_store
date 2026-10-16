import React, { useState, useEffect, useRef } from 'react';
import { useStore } from '../context/StoreContext';
import { Product } from '../types';
import { useRouter } from '../router/RouterContext';
import { useCart } from '../context/CartContext';
import { Price } from '../components/ui/Price';
import { Button } from '../components/modeza/Button';
import { Badge } from '../components/modeza/Badge';
import { Card } from '../components/modeza/Card';
import { QuantitySelector } from '../components/ui/QuantitySelector';
import { ProductCard } from '../components/ProductCard';
import { VariantSelector } from '../components/variant/VariantSelector';
import { formatPrice } from '../utils/currency';
import { addRecentlyViewedProduct } from '../utils/recentlyViewed';
import {
  ShieldCheck,
  Truck,
  RotateCcw,
  ChevronDown,
  Check,
  Sparkles,
  AlertCircle,
  Share2,
  Heart,
  Package,
  Star,
  Bell,
} from 'lucide-react';
import { useWishlist } from '../context/WishlistContext';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/apiClient';
import { ProductReviewDTO } from '../types/api';
import { mapProductDtoToDomain } from '../utils/productMapper';
import { ProductImage } from '../components/ui/ProductImage';
import { motion } from 'motion/react';
import { audit } from '../lib/logger';
import {
  getAllOptionGroups,
  getPriceSummary,
  getVariantFlow,
  getVisibleOptionGroups,
  isVariantPurchasable,
  optionValueEquals,
  parseVariantSelections,
  selectionsToQuery,
  LOW_STOCK_THRESHOLD,
  VariantSelections,
} from '../utils/variants';

export interface ProductDetailPageProps {
  slug: string;
  onQuickView: (product: Product) => void;
}

type LocalFeedback = {
  tone: 'success' | 'error';
  message: string;
};

/**
 * Reconcile a previously-selected set of options against fresh product data.
 * Options that no longer exist structurally are dropped so the page never
 * holds an invalid selection; stock-based changes simply re-disable options.
 */
function reconcileSelections(product: Product, prev: VariantSelections): VariantSelections {
  const groups = getAllOptionGroups(product);
  const next: VariantSelections = {};
  for (const group of groups) {
    const selection = prev[group.key];
    if (selection && group.options.some((option) => optionValueEquals(option.value, selection))) {
      next[group.key] = selection;
    }
  }
  return next;
}

export const ProductDetailPage: React.FC<ProductDetailPageProps> = ({ slug, onQuickView }) => {
  const { navigate } = useRouter();
  const { addToCart } = useCart();
  const { isWishlisted, toggleWishlist } = useWishlist();
  const { user } = useAuth();
  const { getProductBySlug, products, refreshCatalog } = useStore();

  const catalogProduct = getProductBySlug(slug);
  const [fetchedProduct, setFetchedProduct] = useState<Product | null>(null);
  const [isFetchingProduct, setIsFetchingProduct] = useState(false);
  const product = catalogProduct || fetchedProduct || undefined;

  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const [selections, setSelections] = useState<VariantSelections>({});
  const [quantity, setQuantity] = useState(1);
  const [addFeedback, setAddFeedback] = useState<LocalFeedback | null>(null);
  const [shareFeedback, setShareFeedback] = useState<LocalFeedback | null>(null);
  const [isAddingToCart, setIsAddingToCart] = useState(false);
  const [stockError, setStockError] = useState<string | null>(null);
  const [openAccordion, setOpenAccordion] = useState<string | null>('composition');
  const [notifyEmail, setNotifyEmail] = useState('');
  const [notifyState, setNotifyState] = useState<'idle' | 'saving' | 'done' | 'error'>('idle');
  const [notifyMessage, setNotifyMessage] = useState('');
  const [reviews, setReviews] = useState<ProductReviewDTO[]>([]);
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewTitle, setReviewTitle] = useState('');
  const [reviewBody, setReviewBody] = useState('');
  const [reviewMessage, setReviewMessage] = useState('');
  const [reviewError, setReviewError] = useState('');
  const [isLoadingReviews, setIsLoadingReviews] = useState(true);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);
  const addToCartInFlight = useRef(false);
  const addToCartRequestId = useRef(0);

  const hasAnyVariants = (product?.variants?.length ?? 0) > 0;
  const priceSummary = product ? getPriceSummary(product) : null;
  const visibleGroups = product ? getVisibleOptionGroups(product) : [];
  const flow = product ? getVariantFlow(product, selections) : { requiresSelection: false, variant: undefined };
  const resolvedVariant = flow.variant;
  const stillSelecting = flow.requiresSelection;
  const resolvedVariantPurchasable = isVariantPurchasable(resolvedVariant);

  // Restore deep-linked selections from the URL once, when the slug loads.
  useEffect(() => {
    if (catalogProduct) {
      setFetchedProduct(null);
      setIsFetchingProduct(false);
      return;
    }
    let active = true;
    setIsFetchingProduct(true);
    void api.getProduct(slug).then((dto) => {
      if (active) setFetchedProduct(mapProductDtoToDomain(dto));
    }).catch(() => {
      if (active) setFetchedProduct(null);
    }).finally(() => {
      if (active) setIsFetchingProduct(false);
    });
    return () => { active = false; };
  }, [slug, catalogProduct?.id]);

  useEffect(() => {
    if (product) {
      setSelections(parseVariantSelections(product, window.location.search));
    }
    setQuantity(1);
    setStockError(null);
    setAddFeedback(null);
    setShareFeedback(null);
    addToCartRequestId.current += 1;
    addToCartInFlight.current = false;
    setIsAddingToCart(false);
  }, [slug, product?.id]);

  // Reconcile selections whenever refreshed product data arrives so the page
  // never holds options that no longer exist (e.g. variant removed by admin).
  useEffect(() => {
    if (product) {
      setSelections((prev) => reconcileSelections(product, prev));
    }
  }, [product]);

  // Record this piece in the visitor's recently-viewed trail and audit the view.
  useEffect(() => {
    if (product?.id) {
      addRecentlyViewedProduct(product.id);
      void audit('product_viewed', 'Viewed product detail.', {}, { slug, productId: product.id });
    }
  }, [product?.id]);

  useEffect(() => {
    let active = true;
    setIsLoadingReviews(true);
    void api.getProductReviews(slug).then((result) => {
      if (active) setReviews(result.results);
    }).catch(() => {
      if (active) setReviews([]);
    }).finally(() => {
      if (active) setIsLoadingReviews(false);
    });
    return () => { active = false; };
  }, [slug]);

  useEffect(() => {
    if (!addFeedback) return;
    const timer = window.setTimeout(() => setAddFeedback(null), 4000);
    return () => window.clearTimeout(timer);
  }, [addFeedback]);

  useEffect(() => {
    if (!shareFeedback) return;
    const timer = window.setTimeout(() => setShareFeedback(null), 3000);
    return () => window.clearTimeout(timer);
  }, [shareFeedback]);

  useEffect(() => {
    return () => {
      addToCartRequestId.current += 1;
      addToCartInFlight.current = false;
    };
  }, []);

  const handleVariantChange = (next: VariantSelections) => {
    setSelections(next);
    setQuantity(1);
    setStockError(null);
    setAddFeedback(null);
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', `${window.location.pathname}${selectionsToQuery(next)}`);
    }
  };

  const handleAddToCart = async () => {
    if (addToCartInFlight.current) return;
    if (!product || !resolvedVariant || !resolvedVariantPurchasable) return;
    if (quantity > resolvedVariant.stockQuantity) {
      setStockError(`Only ${resolvedVariant.stockQuantity} piece${resolvedVariant.stockQuantity === 1 ? '' : 's'} available.`);
      return;
    }
    const requestId = addToCartRequestId.current + 1;
    addToCartRequestId.current = requestId;
    addToCartInFlight.current = true;
    setIsAddingToCart(true);
    setStockError(null);
    setAddFeedback(null);
    try {
      const result = await addToCart(product, resolvedVariant, quantity);
      if (addToCartRequestId.current !== requestId) return;
      if (result.success) {
        setAddFeedback({
          tone: 'success',
          message: 'Added to cart! View in drawer or cart page.',
        });
      } else {
        setStockError(result.message || 'Unable to add piece to bag.');
        void refreshCatalog();
      }
    } catch (err: unknown) {
      if (addToCartRequestId.current === requestId) {
        const message = err instanceof Error && err.message
          ? err.message
          : 'Unable to add piece to bag.';
        setStockError(message);
        void refreshCatalog();
      }
    } finally {
      if (addToCartRequestId.current === requestId) {
        addToCartInFlight.current = false;
        setIsAddingToCart(false);
      }
    }
  };

  const handleShare = async () => {
    if (typeof window === 'undefined' || typeof navigator === 'undefined') return;
    const url = window.location.href;
    if (!navigator.clipboard?.writeText) {
      setShareFeedback({
        tone: 'error',
        message: 'Copy the product link from your address bar to share this piece.',
      });
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      setShareFeedback({ tone: 'success', message: 'Product link copied to clipboard.' });
    } catch {
      setShareFeedback({
        tone: 'error',
        message: 'Could not copy the link. Copy it from your address bar to share this piece.',
      });
    }
  };

  const handleNotifyMe = async () => {
    if (!resolvedVariant) return;
    const email = notifyEmail.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setNotifyState('error');
      setNotifyMessage('Enter a valid email address.');
      return;
    }
    setNotifyState('saving');
    setNotifyMessage('');
    try {
      const result = await api.subscribeBackInStock(resolvedVariant.id, email);
      setNotifyState('done');
      setNotifyMessage(
        result.alreadySubscribed
          ? 'You are already on the list — we will notify you when it is back.'
          : (result.message || 'We will notify you when this item is back in stock.')
      );
    } catch (err: unknown) {
      const errorObj = err as Error & { code?: string };
      setNotifyState('error');
      setNotifyMessage(errorObj.message || 'The request could not be saved. Please try again.');
    }
  };

  const handleSubmitReview = async (event: React.FormEvent) => {
    event.preventDefault();
    setReviewError('');
    setReviewMessage('');
    setIsSubmittingReview(true);
    try {
      const result = await api.submitProductReview(slug, {
        rating: reviewRating,
        title: reviewTitle.trim(),
        body: reviewBody.trim(),
      });
      setReviewMessage(result.message);
      setReviewTitle('');
      setReviewBody('');
    } catch (error: unknown) {
      setReviewError(error instanceof Error ? error.message : 'Your review could not be submitted.');
    } finally {
      setIsSubmittingReview(false);
    }
  };

  if (!product) {
    return (
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-20">
        <Card className="mx-auto max-w-2xl rounded-3xl p-8 text-center shadow-sm sm:p-12">
          <h1 className="font-serif text-3xl text-[#181716]">
            {isFetchingProduct || products.length === 0 ? 'Loading this piece...' : 'Piece no longer available'}
          </h1>
          <p className="mx-auto mt-4 max-w-lg text-sm leading-relaxed text-[#63605A]">
            {isFetchingProduct || products.length === 0
              ? 'We are refreshing the collection from the modeza catalogue.'
              : 'This product may have been archived or removed, but the rest of the collection is still available.'}
          </p>
          <Button variant="primary" size="md" className="mt-7" onClick={() => navigate('/shop')}>
            Return to collection
          </Button>
        </Card>
      </div>
    );
  }

  const saved = isWishlisted(product.id);

  const renderAvailability = () => {
    if (!hasAnyVariants) {
      return { tone: 'error', icon: AlertCircle, text: 'Currently unavailable online' };
    }
    if (stillSelecting) {
      return {
        tone: 'idle',
        icon: null,
        text:
          visibleGroups.length === 1
            ? `Choose ${visibleGroups[0].label.toLowerCase()} to check availability`
            : 'Choose your options to check availability',
      };
    }
    if (!resolvedVariantPurchasable) {
      return { tone: 'error', icon: AlertCircle, text: 'Out of stock' };
    }
    if (resolvedVariant && resolvedVariant.stockQuantity <= LOW_STOCK_THRESHOLD) {
      return {
        tone: 'low',
        icon: Sparkles,
        text: `Small-batch rarity: Only ${resolvedVariant.stockQuantity} pieces remaining`,
      };
    }
    return { tone: 'success', icon: Check, text: 'In Stock • Ready for MODEZA Dispatch' };
  };

  const availability = renderAvailability();

  const renderPrice = () => {
    if (resolvedVariant) {
      return (
        <Price
          amount={resolvedVariant.price}
          compareAtAmount={product.compareAtPrice}
          size="xl"
        />
      );
    }
    const from = priceSummary && !priceSummary.same;
    return (
      <div className="inline-flex items-baseline gap-1.5">
        {from && <span className="text-sm text-[#827E77] font-normal">From</span>}
        <Price amount={priceSummary ? priceSummary.min : product.price} size="xl" />
      </div>
    );
  };

  const cta = (() => {
    if (!hasAnyVariants || (!stillSelecting && !resolvedVariant) || !resolvedVariantPurchasable) {
      return { label: 'Sold Out', disabled: true };
    }
    if (stillSelecting) {
      return {
        label: visibleGroups.length === 1 ? `Select ${visibleGroups[0].label}` : 'Select Options',
        disabled: true,
      };
    }
    return {
      label: `Add to Cart • ${formatPrice((resolvedVariant?.price || 0) * quantity)}`,
      disabled: false,
    };
  })();

  const addButtonDisabled = cta.disabled || isAddingToCart;
  const addButtonLabel = isAddingToCart ? 'Adding…' : cta.label;

  const isLowStockForBadge = !!resolvedVariantPurchasable && !!resolvedVariant && resolvedVariant.stockQuantity <= LOW_STOCK_THRESHOLD;

  // Related products from same category or featured
  const relatedProducts = products.filter(
    (p) => p.id !== product.id && (p.categorySlug === product.categorySlug || p.isFeatured)
  ).slice(0, 3);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12 space-y-16 pb-28 lg:pb-0 2xl:max-w-[88rem]">
      {/* 1. BREADCRUMBS */}
      <nav className="text-xs text-[#827E77] flex items-center gap-2 flex-wrap" aria-label="Breadcrumb">
        <button onClick={() => navigate('/')} className="hover:text-[#181716] transition-colors">
          Home
        </button>
        <span>/</span>
        <button onClick={() => navigate('/shop')} className="hover:text-[#181716] transition-colors">
          Shop
        </button>
        <span>/</span>
        <button
          onClick={() => navigate(`/shop/${product.categorySlug}`)}
          className="hover:text-[#181716] transition-colors capitalize"
        >
          {product.categorySlug}
        </button>
        <span>/</span>
        <span className="text-[#181716] font-medium truncate max-w-xs">{product.name}</span>
      </nav>

      {/* 2. MAIN PRODUCT OVERVIEW (GALLERY + PURCHASE SPEC) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-14 items-start">
        {/* Gallery Visuals (Col 7) */}
        <div className="lg:col-span-7 space-y-4">
          {/* Main Visual Large Frame */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
            className="aspect-[3/4] w-full rounded-3xl overflow-hidden bg-[#F4ECE9] border border-[#E8E5DF] relative group shadow-xl hover:shadow-2xl transition-all"
          >
            <ProductImage
              src={product.images[activeImageIndex] || product.images[0]}
              alt={`${product.name} view ${activeImageIndex + 1}`}
              className="h-full w-full"
              imgClassName="transition-transform duration-700 ease-out group-hover:scale-105"
            />

            {/* Wishlist overlay button */}
            <button
              type="button"
              onClick={() => toggleWishlist(product.id)}
              className="absolute right-4 top-4 z-10 rounded-full bg-white/95 p-3 text-[#181716] shadow-md transition-all hover:bg-[#A2574F] hover:text-white hover:shadow-lg active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
              aria-label={`${saved ? 'Remove' : 'Add'} ${product.name} ${saved ? 'from' : 'to'} wishlist`}
              title={saved ? 'Remove from wishlist' : 'Add to wishlist'}
            >
              <Heart className={`h-5 w-5 ${saved ? 'fill-current text-[#9E332B]' : ''}`} />
            </button>

            {/* Sale badge */}
            {product.compareAtPrice && product.compareAtPrice > product.price && (
              <Badge
                variant="default"
                className="absolute left-4 top-4 border-0 bg-[#E68057] text-[#181716] shadow-md hover:bg-[#E68057]"
              >
                <Sparkles className="w-3 h-3" />
                Archive Sale
              </Badge>
            )}

            {/* Bottom gradient overlay for image caption */}
            <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-[#181716]/40 to-transparent p-4 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none">
              <p className="text-[10px] text-[#FAF9F6] uppercase tracking-widest">
                View {activeImageIndex + 1} of {product.images.length} &bull; {product.name}
              </p>
            </div>
          </motion.div>

          {/* Thumbnail Strip */}
          {product.images.length > 1 && (
            <div className="flex items-center gap-3 overflow-x-auto pb-2" role="tablist" aria-label="Product images">
              {product.images.map((img, idx) => (
                <button
                  key={idx}
                  type="button"
                  role="tab"
                  aria-selected={activeImageIndex === idx}
                  onClick={() => setActiveImageIndex(idx)}
                  className={`relative w-20 h-24 rounded-xl overflow-hidden border-2 transition-all shrink-0 bg-[#F4ECE9] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] ${
                    activeImageIndex === idx
                      ? 'border-[#A2574F] shadow-md scale-102'
                      : 'border-transparent opacity-65 hover:opacity-100 hover:border-[#D8D3CB]'
                  }`}
                >
                  <ProductImage
                    src={img}
                    alt={`${product.name} thumb ${idx + 1}`}
                    className="h-full w-full"
                  />
                  {activeImageIndex === idx && (
                    <span className="absolute inset-0 ring-2 ring-inset ring-white/30 pointer-events-none" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Product Purchase Column (Col 5) */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
          className="lg:col-span-5 lg:sticky lg:top-24"
        >
          <Card className="space-y-6 overflow-hidden rounded-3xl border-[#E8E5DF] p-5 shadow-xl sm:p-7">
            <div className="space-y-3 border-b border-[#E8E5DF] pb-6">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs uppercase tracking-widest font-semibold text-[#A2574F]">
                  {product.categorySlug}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => void handleShare()}
                  className="text-[#827E77] hover:text-[#181716]"
                  title="Share piece"
                  aria-label="Copy product link"
                >
                  <Share2 className="w-4 h-4" />
                </Button>
              </div>
            </div>

            {shareFeedback && (
              <motion.p
                key={shareFeedback.message}
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                className={`mt-3 flex items-center gap-2 rounded-xl border px-3 py-2.5 text-xs ${
                  shareFeedback.tone === 'success'
                    ? 'border-[#C8D8CA] bg-[#E8EFEA] text-[#2E5A44]'
                    : 'border-[#F8B4B4] bg-[#FDF2F2] text-[#9E332B]'
                }`}
                role="status"
                aria-live="polite"
              >
                {shareFeedback.tone === 'success' ? (
                  <Check className="w-3.5 h-3.5 shrink-0" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                )}
                {shareFeedback.message}
              </motion.p>
            )}

            <div className="flex items-center gap-2 flex-wrap">
              {product.isNewArrival && <Badge variant="new" size="sm">New Arrival</Badge>}
              {product.isBestSeller && <Badge variant="outline" size="sm"><Star className="w-2.5 h-2.5 fill-current" /> Best Seller</Badge>}
              {isLowStockForBadge && <Badge variant="lowStock" size="sm">Low Stock</Badge>}
            </div>

            <h1 className="font-serif text-2xl sm:text-3xl lg:text-4xl text-[#181716] font-normal leading-snug text-balance">
              {product.name}
            </h1>

            <a href="#product-reviews" className="inline-flex items-center gap-2 text-xs text-[#63605A] hover:text-[#A2574F]">
              <Star className="h-3.5 w-3.5 fill-[#C6A77A] text-[#C6A77A]" aria-hidden="true" />
              {product.averageRating ? `${product.averageRating.toFixed(1)} / 5` : 'No ratings yet'}
              <span>({product.reviewCount || 0} verified reviews)</span>
            </a>

            <p className="text-xs text-[#63605A] italic text-pretty">{product.tagline}</p>

            <div className="pt-2 flex items-baseline gap-3 flex-wrap">
              {renderPrice()}
            </div>

            {resolvedVariant && priceSummary && !priceSummary.same && (
              <p className="text-[11px] text-[#827E77]">
                Prices vary by selection &mdash; pieces start from {formatPrice(priceSummary.min)}
              </p>
            )}
          </div>

          {/* Variant Selection */}
          <div className="space-y-5">
            {visibleGroups.length > 0 && (
              <VariantSelector
                product={product}
                selections={selections}
                onChange={handleVariantChange}
                size="lg"
              />
            )}

            {/* Availability status */}
            <div>
              {availability.icon ? (
                <p
                  className={`text-xs flex items-center gap-1.5 font-medium rounded-lg px-3 py-2.5 ${
                    availability.tone === 'success'
                      ? 'text-[#2E5A44] bg-[#E8EFEA] border border-[#C8D8CA]'
                      : availability.tone === 'low'
                        ? 'text-[#8A6024] bg-[#FFF8F0] border border-[#ECD9BD]'
                        : 'text-[#9E332B] bg-[#FDF2F2] border border-[#F8B4B4]'
                  }`}
                >
                  <availability.icon className="w-3.5 h-3.5" />
                  <span>{availability.text}</span>
                </p>
              ) : (
                <p className="text-xs text-[#827E77] bg-[#FAF9F6] border border-dashed border-[#E8E5DF] rounded-lg px-3 py-2.5">
                  {availability.text}
                </p>
              )}
            </div>
          </div>

          {/* Quantity & Add to Cart Controls */}
          <div className="pt-1 space-y-3">
            <div className="flex items-center gap-3">
              <QuantitySelector
                quantity={quantity}
                max={resolvedVariant?.stockQuantity || 1}
                onChange={setQuantity}
                disabled={addButtonDisabled}
                size="md"
              />
              <Button
                variant="primary"
                size="lg"
                disabled={addButtonDisabled}
                isLoading={isAddingToCart}
                onClick={handleAddToCart}
                aria-label={addButtonLabel}
                className="flex-1 text-sm tracking-wider uppercase shadow-md hover:shadow-lg"
              >
                {addButtonLabel}
              </Button>
            </div>

            {cta.disabled && resolvedVariant && !resolvedVariantPurchasable && !stillSelecting && (
              <Card className="space-y-3 rounded-2xl border-[#E8E5DF] bg-[#FAF9F6] p-4 shadow-none">
                <p className="text-xs text-[#63605A] flex items-center gap-2">
                  <Bell className="w-4 h-4 shrink-0" />
                  Sold out — leave your email and we will notify you when it is back.
                </p>
                {notifyState === 'done' ? (
                  <p className="text-xs text-[#2E5A44] bg-[#E8EFEA] border border-[#2E5A44]/20 rounded-lg px-3 py-2.5" role="status">
                    <Check className="inline w-4 h-4 mr-1.5" />
                    {notifyMessage}
                  </p>
                ) : (
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input
                      type="email"
                      value={notifyEmail}
                      onChange={(e) => { setNotifyEmail(e.target.value); setNotifyState('idle'); }}
                      placeholder="you@example.com"
                      aria-label="Email for back-in-stock notification"
                      className="flex-1 rounded-lg border border-[#E8E5DF] bg-white px-3 py-2 text-sm text-[#181716] outline-none focus:border-[#181716]"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="md"
                      onClick={() => void handleNotifyMe()}
                      disabled={notifyState === 'saving'}
                      className="text-xs uppercase tracking-wider"
                    >
                      {notifyState === 'saving' ? 'Notifying…' : 'Notify Me'}
                    </Button>
                  </div>
                )}
                {notifyState === 'error' && (
                  <p className="text-xs text-[#9B1C1C] flex items-center gap-1.5" role="alert">
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    {notifyMessage}
                  </p>
                )}
              </Card>
            )}

            {addFeedback && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex items-center justify-between gap-3 rounded-2xl border p-3.5 text-xs ${
                  addFeedback.tone === 'success'
                    ? 'border-[#C8D8CA] bg-[#E8EFEA] text-[#2E5A44]'
                    : 'border-[#F8B4B4] bg-[#FDF2F2] text-[#9E332B]'
                }`}
                role="status"
                aria-live="polite"
              >
                <span className="flex items-center gap-2">
                  {addFeedback.tone === 'success' ? (
                    <Check className="w-4 h-4 shrink-0" />
                  ) : (
                    <AlertCircle className="w-4 h-4 shrink-0" />
                  )}
                  {addFeedback.message}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => navigate('/cart')}
                  className="shrink-0 px-2 text-xs underline"
                >
                  Go to Cart
                </Button>
              </motion.div>
            )}

            {stockError && (
              <div className="p-3.5 bg-[#FDF2F2] border border-[#F8B4B4] rounded-xl text-xs text-[#9B1C1C] flex items-center gap-2" role="alert">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{stockError}</span>
              </div>
            )}
          </div>

          {/* Value Assurance Badges */}
          <div className="grid grid-cols-3 gap-3 py-4 border-y border-[#E8E5DF] text-[11px] text-[#63605A]">
            <div className="flex flex-col items-center text-center gap-1.5 p-2 rounded-xl hover:bg-[#FAF9F6] transition-colors">
              <Truck className="w-4.5 h-4.5 text-[#A2574F]" strokeWidth={1.5} />
              <span className="text-center text-pretty">Complimentary over KSh 15k</span>
            </div>
            <div className="flex flex-col items-center text-center gap-1.5 p-2 rounded-xl hover:bg-[#FAF9F6] transition-colors">
              <RotateCcw className="w-4.5 h-4.5 text-[#A2574F]" strokeWidth={1.5} />
              <span className="text-center text-pretty">30-Day European Returns</span>
            </div>
            <div className="flex flex-col items-center text-center gap-1.5 p-2 rounded-xl hover:bg-[#FAF9F6] transition-colors">
              <ShieldCheck className="w-4.5 h-4.5 text-[#A2574F]" strokeWidth={1.5} />
              <span className="text-center text-pretty">Artisan Studio Certified</span>
            </div>
          </div>

          {/* Accordion Sections for Detailed Info */}
          <div className="space-y-2.5 text-xs">
            {/* 1. Composition & Craftsmanship */}
            <div className="border border-[#E8E5DF] rounded-xl overflow-hidden bg-[#FFFFFF] shadow-sm hover:shadow-md transition-shadow">
              <button
                type="button"
                onClick={() =>
                  setOpenAccordion(openAccordion === 'composition' ? null : 'composition')
                }
                className="w-full px-5 py-4 text-left font-medium text-[#181716] flex justify-between items-center hover:bg-[#FAF9F6] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F]"
                aria-expanded={openAccordion === 'composition'}
              >
                <span className="text-sm">Composition & Care</span>
                <ChevronDown
                  className={`w-4 h-4 text-[#827E77] transition-transform duration-300 ${
                    openAccordion === 'composition' ? 'rotate-180' : ''
                  }`}
                />
              </button>
              {openAccordion === 'composition' && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                  className="p-5 pt-0 space-y-3 text-[#63605A] border-t border-[#F3F1ED]"
                >
                  <p className="mt-3 text-xs leading-relaxed text-pretty">{product.description}</p>
                  {product.material && <p className="text-xs leading-relaxed"><strong className="text-[#181716]">Material:</strong> {product.material}</p>}
                  {product.careInstructions && <p className="text-xs leading-relaxed"><strong className="text-[#181716]">Care:</strong> {product.careInstructions}</p>}
                  <ul className="list-disc pl-5 space-y-1.5 pt-1">
                    {product.details.map((detail, idx) => (
                      <li key={idx}>{detail}</li>
                    ))}
                  </ul>
                </motion.div>
              )}
            </div>

            {/* 2. Sizing & Fit Guide */}
            <div className="border border-[#E8E5DF] rounded-xl overflow-hidden bg-[#FFFFFF] shadow-sm hover:shadow-md transition-shadow">
              <button
                type="button"
                onClick={() => setOpenAccordion(openAccordion === 'sizing' ? null : 'sizing')}
                className="w-full px-5 py-4 text-left font-medium text-[#181716] flex justify-between items-center hover:bg-[#FAF9F6] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F]"
                aria-expanded={openAccordion === 'sizing'}
              >
                <span className="text-sm">Sizing & Fit Recommendations</span>
                <ChevronDown
                  className={`w-4 h-4 text-[#827E77] transition-transform duration-300 ${
                    openAccordion === 'sizing' ? 'rotate-180' : ''
                  }`}
                />
              </button>
              {openAccordion === 'sizing' && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                  className="p-5 pt-0 space-y-4 text-[#63605A] border-t border-[#F3F1ED]"
                >
                  {product.fitNotes && <p className="mt-3 text-xs leading-relaxed text-pretty">{product.fitNotes}</p>}
                  {product.modelSize && <p className="text-xs leading-relaxed"><strong className="text-[#181716]">Model wears:</strong> {product.modelSize}</p>}
                  {Object.keys(product.garmentMeasurements || {}).length > 0 ? (
                    <dl className="grid grid-cols-2 gap-2 pt-1 sm:grid-cols-3">
                      {Object.entries(product.garmentMeasurements || {}).map(([measurement, value]) => (
                        <div key={measurement} className="rounded-lg border border-[#E8E5DF] bg-[#FAF9F6] p-3">
                          <dt className="text-[10px] uppercase tracking-wider text-[#827E77]">{measurement}</dt>
                          <dd className="mt-1 text-sm font-medium text-[#181716]">{value}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p className="mt-3 text-xs leading-relaxed text-[#827E77]">Detailed garment measurements are not available yet. Contact us for fit guidance.</p>
                  )}
                </motion.div>
              )}
            </div>

            {/* 3. Shipping & Returns */}
            <div className="border border-[#E8E5DF] rounded-xl overflow-hidden bg-[#FFFFFF] shadow-sm hover:shadow-md transition-shadow">
              <button
                type="button"
                onClick={() => setOpenAccordion(openAccordion === 'shipping' ? null : 'shipping')}
                className="w-full px-5 py-4 text-left font-medium text-[#181716] flex justify-between items-center hover:bg-[#FAF9F6] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F]"
                aria-expanded={openAccordion === 'shipping'}
              >
                <span className="text-sm flex items-center gap-2">
                  <Package className="w-4 h-4 text-[#A2574F]" />
                  Complimentary Delivery & Returns
                </span>
                <ChevronDown
                  className={`w-4 h-4 text-[#827E77] transition-transform duration-300 ${
                    openAccordion === 'shipping' ? 'rotate-180' : ''
                  }`}
                />
              </button>
              {openAccordion === 'shipping' && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                  className="p-5 pt-0 space-y-2 text-[#63605A] border-t border-[#F3F1ED]"
                >
                  <p className="mt-3 text-xs leading-relaxed text-pretty">
                    Orders are packaged in recyclable modeza boxes with cotton dustbags. Standard
                    delivery takes 2-4 business days. Returns are accepted within 30 days of receipt in
                    original unworn condition.
                  </p>
                </motion.div>
              )}
            </div>
          </div>
          </Card>
        </motion.div>
      </div>

      {/* Mobile sticky purchase bar (lg:hidden) */}
      <motion.div
        initial={{ y: 80 }}
        animate={{ y: 0 }}
        transition={{ delay: 0.3, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        className="fixed inset-x-0 bottom-0 z-[300] border-t border-[#E8E5DF] bg-white/95 px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur shadow-[0_-4px_20px_rgb(24_23_22/0.06)] lg:hidden"
      >
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] uppercase tracking-wider text-[#827E77]">Total</p>
            {resolvedVariant ? (
              <Price amount={resolvedVariant.price * quantity} size="md" />
            ) : (
              <div className="inline-flex items-baseline gap-1">
                {priceSummary && !priceSummary.same && (
                  <span className="text-[10px] text-[#827E77]">From</span>
                )}
                <Price amount={priceSummary ? priceSummary.min : product.price} size="md" />
              </div>
            )}
          </div>
          <QuantitySelector
            quantity={quantity}
            max={resolvedVariant?.stockQuantity || 1}
            onChange={setQuantity}
            disabled={addButtonDisabled}
            size="sm"
          />
          <Button
            variant="primary"
            size="md"
            disabled={addButtonDisabled}
            isLoading={isAddingToCart}
            onClick={handleAddToCart}
            className="shrink-0 text-xs uppercase tracking-wider max-w-[9.5rem]"
            aria-label={addButtonLabel}
          >
            {addButtonLabel.replace(/ •.*/, '')}
          </Button>
        </div>
      </motion.div>

      <section id="product-reviews" className="mx-auto w-full max-w-7xl scroll-mt-24 px-4 pt-12 sm:px-6 lg:px-8" aria-labelledby="reviews-heading">
        <div className="grid gap-8 border-t border-[#E8E5DF] pt-10 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.8fr)]">
          <div>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">Customer notes</p>
                <h2 id="reviews-heading" className="mt-2 font-serif text-3xl text-[#181716]">Verified reviews</h2>
              </div>
              <p className="inline-flex items-center gap-2 text-sm text-[#63605A]">
                <Star className="h-4 w-4 fill-[#C6A77A] text-[#C6A77A]" aria-hidden="true" />
                {product.averageRating ? `${product.averageRating.toFixed(1)} / 5` : 'No rating yet'}
                <span>({product.reviewCount || 0})</span>
              </p>
            </div>
            {isLoadingReviews ? (
              <p className="mt-6 text-sm text-[#827E77]" role="status">Loading customer reviews...</p>
            ) : reviews.length ? (
              <div className="mt-6 space-y-4">
                {reviews.map((review) => (
                  <article key={review.id} className="rounded-2xl border border-[#E8E5DF] bg-white p-5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="font-medium text-[#181716]">{review.title}</h3>
                      <span className="text-xs text-[#63605A]">{review.rating} / 5</span>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-[#63605A]">{review.body}</p>
                    <p className="mt-4 text-[11px] text-[#827E77]">{review.displayName} · Verified purchase · {new Date(review.createdAt).toLocaleDateString()}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="mt-6 rounded-2xl border border-dashed border-[#D8D3CB] bg-white p-5 text-sm text-[#63605A]">No approved reviews yet. Purchased this item? Once your order is delivered, you can share your experience.</p>
            )}
          </div>

          <Card className="h-fit rounded-2xl border-[#E8E5DF] p-5 shadow-sm sm:p-6">
            <h3 className="font-serif text-xl text-[#181716]">Share your experience</h3>
            <p className="mt-2 text-xs leading-5 text-[#63605A]">Reviews are accepted from customers with a delivered order and checked before publication.</p>
            {user ? (
              <form onSubmit={(event) => void handleSubmitReview(event)} className="mt-5 space-y-4">
                <fieldset>
                  <legend className="text-xs font-semibold text-[#181716]">Your rating</legend>
                  <div className="mt-2 flex gap-1" role="radiogroup" aria-label="Rating from one to five stars">
                    {[1, 2, 3, 4, 5].map((rating) => (
                      <button key={rating} type="button" role="radio" aria-checked={reviewRating === rating} aria-label={`${rating} star${rating === 1 ? '' : 's'}`} onClick={() => setReviewRating(rating)} className="rounded p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]">
                        <Star className={`h-5 w-5 ${rating <= reviewRating ? 'fill-[#C6A77A] text-[#C6A77A]' : 'text-[#D8D3CB]'}`} />
                      </button>
                    ))}
                  </div>
                </fieldset>
                <label className="block text-xs font-semibold text-[#181716]">Review title
                  <input required maxLength={120} value={reviewTitle} onChange={(event) => setReviewTitle(event.target.value)} className="mt-1.5 w-full rounded-xl border border-[#E8E5DF] px-3.5 py-2.5 text-sm font-normal focus:border-[#A2574F] focus:outline-none" />
                </label>
                <label className="block text-xs font-semibold text-[#181716]">Your review
                  <textarea required maxLength={2000} rows={4} value={reviewBody} onChange={(event) => setReviewBody(event.target.value)} className="mt-1.5 w-full resize-y rounded-xl border border-[#E8E5DF] px-3.5 py-2.5 text-sm font-normal focus:border-[#A2574F] focus:outline-none" />
                </label>
                {reviewError && <p role="alert" className="text-xs text-[#9E332B]">{reviewError}</p>}
                {reviewMessage && <p role="status" className="text-xs text-[#2E5A44]">{reviewMessage}</p>}
                <Button type="submit" variant="primary" size="md" disabled={isSubmittingReview} isLoading={isSubmittingReview}>Submit review</Button>
              </form>
            ) : (
              <Button type="button" variant="outline" size="md" className="mt-5" onClick={() => navigate('/account')}>Sign in to review</Button>
            )}
          </Card>
        </div>
      </section>

      {/* 3. RELATED PRODUCTS ("You May Also Appreciate") */}
      {relatedProducts.length > 0 && (
        <section className="pt-12 border-t border-[#E8E5DF]">
          <div className="flex items-center justify-between mb-8">
            <div>
              <span className="text-xs uppercase tracking-widest text-[#827E77] font-semibold block mb-1.5 flex items-center gap-2">
                <span className="w-8 h-px bg-[#A2574F]" />
                Wardrobe Styling
              </span>
              <h3 className="font-serif text-2xl sm:text-3xl text-[#181716] text-balance">
                Complete The Look
              </h3>
            </div>
            <Button variant="outline" size="sm" onClick={() => navigate('/shop')}>
              Explore Catalog
            </Button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 sm:gap-8">
            {relatedProducts.map((p, index) => (
              <motion.div
                key={p.id}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-50px' }}
                transition={{ duration: 0.4, delay: index * 0.08, ease: [0.16, 1, 0.3, 1] }}
              >
                <ProductCard
                  product={p}
                  onQuickView={onQuickView}
                  onClick={() => navigate(`/product/${p.slug}`)}
                />
              </motion.div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};
