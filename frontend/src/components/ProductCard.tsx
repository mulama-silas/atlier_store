import React, { useEffect, useId, useRef, useState } from "react";
import { ArrowRight, Check, Eye, Heart, ShoppingBag } from "lucide-react";
import { Product } from "../types";
import { useCart } from "../context/CartContext";
import { useStore } from "../context/StoreContext";
import { useWishlist } from "../context/WishlistContext";
import {
  getAllOptionGroups,
  getColorSwatches,
  getPriceSummary,
  getVisibleOptionGroups,
  isVariantPurchasable,
} from "../utils/variants";
import { Badge, Button, Card } from "./modeza";
import { Price } from "./ui/Price";
import { ProductImage } from "./ui/ProductImage";
import { ColorSwatches } from "./variant/ColorSwatches";

export interface ProductCardProps {
  product: Product;
  onQuickView?: (product: Product) => void;
  onClick?: (product: Product) => void;
  variant?: "default" | "compact" | "featured";
}

export const ProductCard: React.FC<ProductCardProps> = ({
  product,
  onQuickView,
  onClick,
  variant = "default",
}) => {
  const productHeadingId = useId();
  const [isHovered, setIsHovered] = useState(false);
  const [isAdded, setIsAdded] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const addedTimerRef = useRef<number | null>(null);
  const { isWishlisted, toggleWishlist } = useWishlist();
  const { addToCart, isLoading } = useCart();
  const { availablePromotions } = useStore();
  const saved = isWishlisted(product.id);

  useEffect(() => {
    if (addedTimerRef.current !== null) {
      window.clearTimeout(addedTimerRef.current);
      addedTimerRef.current = null;
    }
    setIsAdded(false);
    setIsAdding(false);
    setAddError(null);
  }, [product.id]);

  useEffect(
    () => () => {
      if (addedTimerRef.current !== null) {
        window.clearTimeout(addedTimerRef.current);
      }
    },
    [],
  );

  const hasVariants = (product.variants?.length ?? 0) > 0;
  const totalStock = (product.variants ?? []).reduce(
    (total, item) => total + item.stockQuantity,
    0,
  );
  const visibleOptionGroups = hasVariants
    ? getVisibleOptionGroups(product)
    : [];
  const hasOptionsToSelect = visibleOptionGroups.length > 0;
  const isSoldOut = totalStock <= 0;
  const isLowStock = !isSoldOut && totalStock <= 4;
  // Server-driven promotion badge (Django /api/promotions/available metadata).
  const promoBadge =
    availablePromotions.length > 0 ? availablePromotions[0].badge : "";
  const showPromoBadge =
    Boolean(promoBadge) &&
    !isSoldOut &&
    (Boolean(
      product.compareAtPrice && product.compareAtPrice > product.price,
    ) ||
      product.isNewArrival);
  const hasMultipleImages = product.images.length > 1;
  const selectedVariant = hasVariants
    ? product.variants.find((item) => isVariantPurchasable(item)) ||
      product.variants[0]
    : undefined;
  const priceSummary = getPriceSummary(product);
  const swatches = getColorSwatches(product);
  const colorCount = swatches.length;
  const optionGroups = getAllOptionGroups(product);
  const sizeCount =
    optionGroups.find((group) => group.key === "size")?.options.length ?? 0;
  const sizeSummary = sizeCount > 1 ? `${sizeCount} sizes` : null;
  const variantSummary =
    optionGroups
      .filter((group) => group.key !== "size" && group.options.length > 1)
      .map((group) => {
        const label =
          group.key === "color" ? "colour" : group.label.toLowerCase();
        return `${group.options.length} ${label}s`;
      })
      .join(" · ") || null;
  const isActionLoading = isAdding || isLoading;

  const handleAddToCart = async () => {
    if (
      isActionLoading ||
      !selectedVariant ||
      !isVariantPurchasable(selectedVariant)
    )
      return;

    setAddError(null);
    setIsAdding(true);
    try {
      const result = await addToCart(product, selectedVariant, 1);
      if (result.success) {
        setIsAdded(true);
        if (addedTimerRef.current !== null) {
          window.clearTimeout(addedTimerRef.current);
        }
        addedTimerRef.current = window.setTimeout(() => {
          setIsAdded(false);
          addedTimerRef.current = null;
        }, 1600);
      } else {
        setAddError(result.message || "Unable to add this piece to your bag.");
      }
    } finally {
      setIsAdding(false);
    }
  };

  const handleViewOptions = () => {
    onClick?.(product);
  };

  const primaryActionDisabled = hasOptionsToSelect
    ? isActionLoading
    : isSoldOut || isActionLoading;
  const primaryActionLabel = hasOptionsToSelect
    ? "View Options"
    : isSoldOut
      ? "Sold Out"
      : isAdded
        ? "Added to Cart"
        : "Add to Cart";
  const primaryActionAriaLabel = hasOptionsToSelect
    ? `View options for ${product.name}`
    : isSoldOut
      ? `${product.name} is sold out`
      : isActionLoading
        ? `Adding ${product.name} to cart`
        : isAdded
          ? `${product.name} added to cart`
          : `Add ${product.name} to cart`;
  const imageAspectRatio = "aspect-[4/5]";
  const cardClassName = [
    "group relative mx-auto flex h-full w-full max-w-[280px] flex-col rounded-2xl border border-transparent bg-transparent shadow-none transition-[border-color,box-shadow] duration-300 hover:border-[#E8E5DF] hover:shadow-sm",
    variant === "featured" ? "p-1" : "",
    onClick ? "cursor-pointer" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const renderPriceLine = () => (
    <div className="flex flex-wrap items-baseline gap-1.5">
      {!priceSummary.same && (
        <span className="text-[11px] font-normal text-[#827E77]">From</span>
      )}
      <Price
        amount={priceSummary.min}
        compareAtAmount={product.compareAtPrice}
        size="sm"
      />
    </div>
  );

  const renderCategoryMeta = () => (
    <div className="flex min-h-[14px] items-center justify-between gap-2 text-[10px] font-medium uppercase tracking-widest text-[#827E77]">
      <span className="truncate">{product.categorySlug}</span>
      {sizeSummary && (
        <span className="shrink-0 normal-case tracking-normal">
          {sizeSummary}
        </span>
      )}
    </div>
  );

  const renderVariantMeta = () => {
    if (!variantSummary && colorCount < 2) return null;

    return (
      <div
        className="pointer-events-auto space-y-2"
        onClick={onClick ? () => onClick(product) : undefined}
      >
        {variantSummary && (
          <p className="flex items-center gap-1.5 text-[11px] text-[#827E77]">
            {variantSummary}
          </p>
        )}
        {colorCount >= 2 && (
          <ColorSwatches options={swatches} size="sm" compact />
        )}
      </div>
    );
  };

  const renderCardOverlay = () => {
    if (!onClick) return null;

    return (
      <button
        type="button"
        className="absolute inset-0 z-0 rounded-2xl focus-visible:z-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F]"
        onClick={() => onClick(product)}
        aria-label={`View ${product.name}${hasOptionsToSelect ? " and choose options" : ""}`}
      />
    );
  };

  if (variant === "compact") {
    return (
      <Card
        role="article"
        aria-labelledby={productHeadingId}
        className={cardClassName}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {renderCardOverlay()}

        <div className="pointer-events-none relative z-10 flex w-full flex-1 flex-col">
          <div className="relative mb-2.5 w-full overflow-hidden rounded-2xl bg-[#F4ECE9]">
            <div className="aspect-[4/5]">
              <ProductImage
                src={
                  isHovered && hasMultipleImages
                    ? product.images[1]
                    : product.images[0]
                }
                alt={product.name}
                className="h-full w-full"
                imgClassName="transition-transform duration-500 ease-out group-hover:scale-105"
              />
            </div>
            <button
              type="button"
              onClick={() => toggleWishlist(product.id)}
              className="pointer-events-auto absolute right-2 top-2 z-30 rounded-full bg-white/95 p-2 text-[#181716] shadow-sm transition-colors hover:bg-[#181716] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
              aria-label={`${saved ? "Remove" : "Add"} ${product.name} ${saved ? "from" : "to"} wishlist`}
              aria-pressed={saved}
              title={saved ? "Remove from wishlist" : "Add to wishlist"}
            >
              <Heart
                className={`h-3.5 w-3.5 ${saved ? "fill-current text-[#9E332B]" : ""}`}
                aria-hidden="true"
              />
            </button>
          </div>

          <div className="flex flex-grow flex-col space-y-1">
            {renderCategoryMeta()}
            <h3
              id={productHeadingId}
              className="line-clamp-1 font-serif text-sm text-[#181716] transition-colors group-hover:text-[#A2574F]"
            >
              {product.name}
            </h3>
            {renderPriceLine()}
            {renderVariantMeta()}
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card
      role="article"
      aria-labelledby={productHeadingId}
      className={cardClassName}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {renderCardOverlay()}

      <div className="pointer-events-none relative z-10 flex w-full flex-1 flex-col">
        <div className="image-zoom relative mb-3.5 w-full overflow-hidden rounded-2xl bg-[#F4ECE9]">
          <div className={imageAspectRatio}>
            <ProductImage
              src={
                isHovered && hasMultipleImages
                  ? product.images[1]
                  : product.images[0]
              }
              alt={product.name}
              className="h-full w-full"
              imgClassName="transition-transform duration-500 ease-out"
            />
          </div>

          <div className="pointer-events-none absolute left-3 top-3 z-20 flex flex-col items-start gap-1.5">
            {isSoldOut ? (
              <Badge variant="secondary" size="sm">
                Sold Out
              </Badge>
            ) : showPromoBadge ? (
              <Badge variant="warning" size="sm">
                {promoBadge}
              </Badge>
            ) : product.compareAtPrice &&
              product.compareAtPrice > product.price ? (
              <Badge variant="warning" size="sm">
                Sale
              </Badge>
            ) : product.isNewArrival ? (
              <Badge variant="new" size="sm">
                New
              </Badge>
            ) : null}
            {isLowStock && (
              <Badge variant="lowStock" size="sm">
                Low Stock
              </Badge>
            )}
            {product.isBestSeller && !isSoldOut && (
              <Badge variant="outline" size="sm">
                Best Seller
              </Badge>
            )}
          </div>

          <button
            type="button"
            onClick={() => toggleWishlist(product.id)}
            className="pointer-events-auto absolute right-3 top-3 z-30 rounded-full bg-white/95 p-2.5 text-[#181716] shadow-sm transition-all duration-200 hover:bg-[#A2574F] hover:text-white hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
            aria-label={`${saved ? "Remove" : "Add"} ${product.name} ${saved ? "from" : "to"} wishlist`}
            aria-pressed={saved}
            title={saved ? "Remove from wishlist" : "Add to wishlist"}
          >
            <Heart
              className={`h-4 w-4 ${saved ? "fill-current text-[#9E332B]" : ""}`}
              aria-hidden="true"
            />
          </button>

          {onQuickView && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => onQuickView(product)}
              className="pointer-events-auto absolute bottom-3 left-3 right-auto z-20 h-7 border border-white/80 bg-white/95 px-2.5 text-[10px] opacity-100 shadow-sm backdrop-blur-sm hover:bg-white hover:shadow-md lg:translate-y-2 lg:opacity-0 lg:transition-all lg:duration-300 lg:group-hover:translate-y-0 lg:group-hover:opacity-100 lg:group-focus-within:translate-y-0 lg:group-focus-within:opacity-100"
              aria-label={`Quick view ${product.name}`}
              aria-haspopup="dialog"
            >
              <Eye className="h-3.5 w-3.5" aria-hidden="true" />
              Quick View
            </Button>
          )}
        </div>

        <div className="flex flex-1 flex-col space-y-2">
          {renderCategoryMeta()}

          <h3
            id={productHeadingId}
            className="line-clamp-1 font-serif text-base text-[#181716] transition-colors group-hover:text-[#A2574F]"
          >
            {product.name}
          </h3>

          <p className="min-h-[16px] line-clamp-1 text-[11px] italic text-[#63605A]">
            {product.tagline || " "}
          </p>

          <div className="min-h-[24px] pt-1">{renderPriceLine()}</div>
          <div className="min-h-[44px]">
            {hasVariants && renderVariantMeta()}
          </div>

          <Button
            type="button"
            variant="outline"
            fullWidth
            onClick={hasOptionsToSelect ? handleViewOptions : handleAddToCart}
            disabled={primaryActionDisabled}
            isLoading={isActionLoading && !hasOptionsToSelect}
            aria-busy={isActionLoading}
            aria-label={primaryActionAriaLabel}
            className="pointer-events-auto mt-2 h-10 shrink-0 rounded-lg disabled:border-[#D8D3CB] disabled:text-[#A29E96]"
          >
            {hasOptionsToSelect ? (
              <span className="inline-flex items-center justify-center gap-1.5">
                {primaryActionLabel}
                <ArrowRight className="h-3 w-3" aria-hidden="true" />
              </span>
            ) : isAdded ? (
              <span
                className="inline-flex items-center justify-center gap-1.5"
                role="status"
                aria-live="polite"
              >
                <Check className="h-3.5 w-3.5" aria-hidden="true" />
                {primaryActionLabel}
              </span>
            ) : (
              <span className="inline-flex items-center justify-center gap-1.5">
                <ShoppingBag className="h-3.5 w-3.5" aria-hidden="true" />
                {primaryActionLabel}
              </span>
            )}
          </Button>
          {addError && (
            <p
              className="pointer-events-auto mt-1 text-[11px] leading-relaxed text-[#9B1C1C]"
              role="alert"
            >
              {addError}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
};
