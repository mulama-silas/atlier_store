import React, { useState, useMemo, useEffect } from "react";
import { useStore } from "../context/StoreContext";
import { ProductCard } from "../components/ProductCard";
import { CategorySlug, Product } from "../types";
import { ShopOccasion } from "../router/RouterContext";
import { useRouter } from "../router/RouterContext";
import {
  Search,
  SlidersHorizontal,
  ArrowUpDown,
  X,
  Package,
  Filter,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { Button } from "../components/modeza/Button";
import { Input, Select as SortSelect } from "../components/modeza/Input";
import { Badge } from "../components/modeza/Badge";
import { Card } from "../components/modeza/Card";
import { Checkbox } from "../components/modeza/Checkbox";
import { Progress } from "../components/modeza/Progress";
import { motion, AnimatePresence } from "motion/react";
import { audit } from "../lib/logger";

export interface ShopPageProps {
  initialCategory?: CategorySlug;
  initialCollection?: "best-sellers" | "new-arrivals";
  initialOccasion?: ShopOccasion;
  initialQuery?: string;
  initialSale?: boolean;
  onQuickView: (product: Product) => void;
}

type SortOption = "featured" | "price-asc" | "price-desc" | "newest";

const OCCASION_CATEGORIES: Record<ShopOccasion, CategorySlug[]> = {
  everyday: ["women", "men", "tops", "bottoms", "shoes"],
  evening: ["dresses", "outerwear"],
  "special-occasions": ["dresses", "accessories", "outerwear"],
};

const OCCASION_TITLES: Record<ShopOccasion, string> = {
  everyday: "The Everyday Edit",
  evening: "Evening & Occasion",
  "special-occasions": "Special Occasions",
};

const SORT_OPTIONS: Array<{ value: SortOption; label: string }> = [
  { value: "featured", label: "Featured First" },
  { value: "newest", label: "New Arrivals" },
  { value: "price-asc", label: "Price: Low to High" },
  { value: "price-desc", label: "Price: High to Low" },
];

export const ShopPage: React.FC<ShopPageProps> = ({
  initialCategory = "all",
  initialCollection,
  initialOccasion,
  initialQuery,
  initialSale,
  onQuickView,
}) => {
  const { navigate } = useRouter();
  const {
    products,
    categories: storeCategories,
    availablePromotions,
  } = useStore();
  const [selectedCategory, setSelectedCategory] =
    useState<CategorySlug>(initialCategory);
  const [selectedCollection, setSelectedCollection] =
    useState(initialCollection);
  const [selectedOccasion, setSelectedOccasion] = useState<
    ShopOccasion | undefined
  >(initialOccasion);
  const [selectedSale, setSelectedSale] = useState<boolean>(
    Boolean(initialSale),
  );
  const [searchQuery, setSearchQuery] = useState(initialQuery || "");
  const [onlyInStock, setOnlyInStock] = useState(false);
  const [sortBy, setSortBy] = useState<SortOption>("featured");
  const [itemsToShow, setItemsToShow] = useState(6);
  const [showFilters, setShowFilters] = useState(false);
  const isNewArrivalsView = selectedCollection === "new-arrivals";

  useEffect(() => {
    setSelectedCategory(initialCategory);
    setSelectedCollection(initialCollection);
    setSelectedOccasion(initialOccasion);
    setSelectedSale(Boolean(initialSale));
    setSearchQuery(initialQuery || "");
    setOnlyInStock(false);
    setSortBy("featured");
    setItemsToShow(6);
  }, [
    initialCategory,
    initialCollection,
    initialOccasion,
    initialQuery,
    initialSale,
  ]);

  useEffect(() => {
    if (initialQuery) {
      void audit(
        "search_performed",
        "Storefront search performed.",
        {},
        { query: initialQuery },
      );
    }
    if (initialCategory && initialCategory !== "all") {
      void audit(
        "category_viewed",
        "Viewed category.",
        {},
        { category: initialCategory },
      );
    }
  }, [initialCategory, initialQuery]);

  const filteredProducts = useMemo(() => {
    const hasMarkedNewArrivals = products.some(
      (product) => product.isNewArrival,
    );
    let list = products.filter((product) => {
      const matchesCategory =
        selectedCategory === "all" || product.categorySlug === selectedCategory;
      const matchesCollection =
        selectedCollection === "best-sellers"
          ? product.isBestSeller
          : selectedCollection === "new-arrivals"
            ? !hasMarkedNewArrivals || product.isNewArrival
            : true;
      const matchesOccasion = !selectedOccasion
        ? true
        : OCCASION_CATEGORIES[selectedOccasion].includes(product.categorySlug);
      const matchesSale = !selectedSale || product.compareAtPrice !== undefined;
      const search = searchQuery.trim().toLowerCase();
      const matchesSearch =
        !search ||
        [product.name, product.tagline, product.description].some(
          (value) => value?.toLowerCase().includes(search) ?? false,
        );
      return (
        matchesCategory &&
        matchesCollection &&
        matchesOccasion &&
        matchesSale &&
        matchesSearch
      );
    });

    list = [...list].sort((a, b) => {
      if (isNewArrivalsView) return b.createdAt.localeCompare(a.createdAt);
      if (sortBy === "price-asc") return a.price - b.price;
      if (sortBy === "price-desc") return b.price - a.price;
      if (sortBy === "newest") return b.createdAt.localeCompare(a.createdAt);
      return (
        Number(b.isFeatured) - Number(a.isFeatured) ||
        b.createdAt.localeCompare(a.createdAt)
      );
    });

    if (onlyInStock) {
      list = list.filter((p) => {
        const totalStock = p.variants.reduce(
          (sum, v) => sum + v.stockQuantity,
          0,
        );
        return totalStock > 0;
      });
    }
    if (isNewArrivalsView) list = list.slice(0, 5);
    return list;
  }, [
    products,
    selectedCategory,
    selectedCollection,
    selectedOccasion,
    selectedSale,
    searchQuery,
    sortBy,
    onlyInStock,
  ]);

  const isAllProductsView =
    selectedCategory === "all" &&
    !selectedCollection &&
    !selectedOccasion &&
    !selectedSale &&
    !searchQuery &&
    !onlyInStock;
  const displayedProducts = isAllProductsView
    ? filteredProducts
    : filteredProducts.slice(0, itemsToShow);
  const hasMore = !isAllProductsView && itemsToShow < filteredProducts.length;
  const activeFilterCount = [
    Boolean(searchQuery),
    onlyInStock,
    selectedCategory !== "all",
    Boolean(selectedCollection),
    Boolean(selectedOccasion),
    selectedSale,
  ].filter(Boolean).length;
  const hasActiveFilters = activeFilterCount > 0;
  const activeSortLabel = isNewArrivalsView
    ? "Newest First"
    : (SORT_OPTIONS.find((option) => option.value === sortBy)?.label ??
      "Featured First");
  const visibleProgress =
    filteredProducts.length > 0
      ? Math.min(
          100,
          Math.round(
            (displayedProducts.length / filteredProducts.length) * 100,
          ),
        )
      : 0;

  const headerTitle = selectedSale
    ? "The Sale Edit"
    : selectedOccasion
      ? OCCASION_TITLES[selectedOccasion]
      : selectedCollection === "best-sellers"
        ? "Best Sellers"
        : selectedCollection === "new-arrivals"
          ? "New Arrivals"
          : selectedCategory === "all"
            ? "The Complete Wardrobe"
            : storeCategories.find((c) => c.slug === selectedCategory)?.name ||
              "The Collection";

  const headerDescription = selectedSale
    ? "Focused reductions on select pieces from the permanent collection, while they last."
    : storeCategories.find((c) => c.slug === selectedCategory)?.description ||
      "Tailored from organic fibers with meticulous attention to line, drape, and enduring tactility.";

  const clearFilters = () => {
    setSearchQuery("");
    setOnlyInStock(false);
    setSelectedCategory("all");
    setSelectedCollection(undefined);
    setSelectedOccasion(undefined);
    setSelectedSale(false);
    setSortBy("featured");
    setItemsToShow(6);
  };

  return (
    <div className="mx-auto w-full max-w-7xl space-y-8 px-4 pb-20 pt-6 sm:px-6 sm:pt-10 lg:px-8 2xl:max-w-[88rem]">
      <Card className="relative overflow-hidden rounded-[2rem] border-white/10 bg-[#181716] p-0 text-[#FAF9F6] shadow-xl hover:shadow-xl">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 overflow-hidden"
        >
          <div className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-[#A2574F]/25 blur-3xl" />
          <div className="absolute -bottom-32 left-1/3 h-72 w-72 rounded-full bg-[#993A8B]/15 blur-3xl" />
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#E68057]/60 to-transparent" />
        </div>

        <div className="relative px-5 py-7 sm:px-8 sm:py-9 lg:px-12 lg:py-11">
          <nav
            aria-label="Breadcrumb"
            className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/45"
          >
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => navigate("/")}
              className="-ml-3 h-8 px-3 text-[10px] text-white/55 hover:bg-white/10 hover:text-white focus-visible:ring-offset-[#181716]"
            >
              Home
            </Button>
            <ChevronRight className="h-3 w-3" aria-hidden="true" />
            <span className="text-white/80">Shop</span>
            {selectedCategory !== "all" && (
              <>
                <ChevronRight className="h-3 w-3" aria-hidden="true" />
                <span className="max-w-40 truncate text-white/80 capitalize sm:max-w-none">
                  {selectedCategory}
                </span>
              </>
            )}
          </nav>

          <div className="mt-8 grid items-end gap-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:gap-12">
            <div className="max-w-3xl">
              <Badge variant="new" size="lg" className="mb-5 gap-1.5">
                <Sparkles className="h-3 w-3" aria-hidden="true" />
                MODEZA Collection
              </Badge>
              <h1 className="font-serif text-4xl font-normal leading-[1.08] tracking-tight text-balance sm:text-5xl lg:text-6xl">
                {headerTitle}
              </h1>
              <p className="mt-5 max-w-2xl text-sm leading-relaxed text-white/65 text-pretty sm:text-base">
                {headerDescription}
              </p>

              {(selectedCategory !== "all" ||
                selectedOccasion ||
                selectedSale) && (
                <div className="mt-6 flex flex-wrap items-center gap-2">
                  <span className="mr-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-white/40">
                    Refining
                  </span>
                  {selectedCategory !== "all" && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setSelectedCategory("all")}
                      className="h-8 border border-white/15 px-3 text-[10px] text-white/80 hover:border-white/30 hover:bg-white/10 hover:text-white"
                    >
                      <X className="h-3 w-3" aria-hidden="true" />
                      Clear Category
                    </Button>
                  )}
                  {selectedOccasion && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setSelectedOccasion(undefined)}
                      className="h-8 border border-white/15 px-3 text-[10px] text-white/80 hover:border-white/30 hover:bg-white/10 hover:text-white"
                    >
                      <X className="h-3 w-3" aria-hidden="true" />
                      Clear Occasion
                    </Button>
                  )}
                  {selectedSale && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setSelectedSale(false)}
                      className="h-8 border border-white/15 px-3 text-[10px] text-white/80 hover:border-white/30 hover:bg-white/10 hover:text-white"
                    >
                      <X className="h-3 w-3" aria-hidden="true" />
                      Clear Sale
                    </Button>
                  )}
                </div>
              )}
            </div>

            <div className="min-w-52 rounded-2xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur-sm">
              <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-white/45">
                Collection result
              </span>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-serif text-4xl font-normal text-white sm:text-5xl">
                  {filteredProducts.length}
                </span>
                <span className="text-xs uppercase tracking-wider text-white/50">
                  {filteredProducts.length === 1 ? "Piece" : "Pieces"}
                </span>
              </div>
              <p className="mt-3 text-xs text-white/45">
                Showing {displayedProducts.length} in the current view
              </p>
            </div>
          </div>
        </div>
      </Card>

      {availablePromotions.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-2xl border border-[#A2574F]/20 bg-[#F7ECEA] px-4 py-3"
          role="status"
          aria-label="Current promotions"
        >
          <Sparkles className="h-4 w-4 text-[#A2574F]" aria-hidden="true" />
          <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">
            Current offers
          </span>
          {availablePromotions.slice(0, 4).map((promo) => (
            <Badge
              key={promo.name}
              variant="warning"
              size="sm"
              title={promo.name}
            >
              {promo.badge} · {promo.name}
            </Badge>
          ))}
        </div>
      )}

      <Card className="sticky top-3 z-30 bg-white/95 p-3 shadow-lg backdrop-blur-xl sm:p-4">
        <div className="grid gap-3 lg:grid-cols-[minmax(18rem,1fr)_auto] lg:items-center">
          <div className="relative">
            <Input
              id="shop-search"
              type="text"
              placeholder="Search the collection..."
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              icon={<Search className="h-4 w-4" aria-hidden="true" />}
              aria-label="Search products"
              className="h-11 bg-[#FAF9F6] py-0 pl-10 pr-11 text-sm"
            />
            {searchQuery && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setSearchQuery("")}
                aria-label="Clear product search"
                className="absolute right-1.5 top-1/2 h-8 w-8 -translate-y-1/2 text-[#827E77] hover:bg-[#F3F1ED] hover:text-[#181716]"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
            )}
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-2 lg:justify-end">
            <div className="hidden items-center gap-2 lg:flex">
              <label
                htmlFor="in-stock-desktop"
                className="flex h-10 cursor-pointer select-none items-center gap-2.5 rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-3.5 text-xs font-medium text-[#63605A] transition-colors hover:border-[#D8D3CB]"
              >
                <Checkbox
                  id="in-stock-desktop"
                  checked={onlyInStock}
                  onCheckedChange={(checked) =>
                    setOnlyInStock(checked === true)
                  }
                  className="h-[18px] w-[18px] rounded-full"
                />
                <span>In stock only</span>
              </label>

              {!isNewArrivalsView && (
                <div className="relative w-52">
                  <ArrowUpDown
                    className="pointer-events-none absolute left-3.5 top-1/2 z-10 h-3.5 w-3.5 -translate-y-1/2 text-[#827E77]"
                    aria-hidden="true"
                  />
                  <SortSelect
                    id="sort-desktop"
                    value={sortBy}
                    onChange={(event) =>
                      setSortBy(event.target.value as SortOption)
                    }
                    options={SORT_OPTIONS}
                    aria-label="Sort products"
                    className="h-10 bg-[#FAF9F6] py-0 pl-10 text-xs font-semibold"
                  />
                </div>
              )}
            </div>

            <Button
              type="button"
              variant={showFilters ? "primary" : "outline"}
              size="md"
              onClick={() => setShowFilters(!showFilters)}
              aria-expanded={showFilters}
              aria-controls="mobile-filter-drawer"
              aria-label={
                activeFilterCount > 0
                  ? `Filters, ${activeFilterCount} active`
                  : "Filters"
              }
              className="flex-1 sm:flex-none lg:hidden"
            >
              <Filter className="h-3.5 w-3.5" aria-hidden="true" />
              Filters
              {activeFilterCount > 0 && (
                <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-[#A2574F] px-1.5 text-[10px] text-white lg:bg-[#181716]">
                  {activeFilterCount}
                </span>
              )}
            </Button>

            {hasActiveFilters && (
              <Button
                type="button"
                variant="ghost"
                size="md"
                onClick={clearFilters}
                className="text-[#9E332B] hover:bg-[#FDF2F2] hover:text-[#9E332B]"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
                Clear All
              </Button>
            )}
          </div>
        </div>
      </Card>

      <AnimatePresence>
        {showFilters && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setShowFilters(false)}
            className="fixed inset-0 z-[500] bg-[#181716]/50 backdrop-blur-sm lg:hidden"
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showFilters && (
          <motion.aside
            id="mobile-filter-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="Product filters"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 320 }}
            className="fixed inset-x-0 bottom-0 z-[600] max-h-[88dvh] overflow-y-auto rounded-t-3xl border-t border-[#E8E5DF] bg-white p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-2xl sm:p-6 sm:max-h-[80dvh] lg:hidden"
          >
            <div className="mx-auto mb-6 h-1 w-12 rounded-full bg-[#D8D3CB]" />

            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">
                  Refine selection
                </span>
                <p className="mt-1.5 text-sm text-[#63605A]">
                  {filteredProducts.length}{" "}
                  {filteredProducts.length === 1 ? "piece" : "pieces"} match
                  your view
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setShowFilters(false)}
                aria-label="Close filters"
                className="shrink-0 text-[#827E77] hover:bg-[#F3F1ED] hover:text-[#181716]"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>

            <div className="space-y-3">
              <label
                htmlFor="in-stock-mobile"
                className="flex cursor-pointer select-none items-center gap-3 rounded-2xl border border-[#E8E5DF] bg-[#FAF9F6] p-4 transition-colors hover:border-[#D8D3CB]"
              >
                <Checkbox
                  id="in-stock-mobile"
                  checked={onlyInStock}
                  onCheckedChange={(checked) =>
                    setOnlyInStock(checked === true)
                  }
                  className="h-5 w-5 rounded-full"
                />
                <span>
                  <span className="block text-sm font-semibold text-[#181716]">
                    In stock only
                  </span>
                  <span className="mt-0.5 block text-xs text-[#827E77]">
                    Hide unavailable pieces
                  </span>
                </span>
              </label>

              {!isNewArrivalsView && (
                <SortSelect
                  id="sort-mobile"
                  label="Sort pieces"
                  value={sortBy}
                  onChange={(event) =>
                    setSortBy(event.target.value as SortOption)
                  }
                  options={SORT_OPTIONS}
                  className="h-12 bg-[#FAF9F6] py-0"
                />
              )}
            </div>

            {hasActiveFilters && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                fullWidth
                onClick={clearFilters}
                className="mt-3 text-[#9E332B] hover:bg-[#FDF2F2] hover:text-[#9E332B]"
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
                Clear All Filters
              </Button>
            )}

            <Button
              type="button"
              variant="primary"
              size="lg"
              fullWidth
              onClick={() => setShowFilters(false)}
              className="mt-5"
            >
              <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
              Apply Filters
            </Button>
          </motion.aside>
        )}
      </AnimatePresence>

      <div className="flex flex-col gap-3 border-b border-[#E8E5DF] pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
            Curated selection
          </span>
          <h2 className="mt-2 font-serif text-2xl font-normal text-[#181716] sm:text-3xl">
            {filteredProducts.length}{" "}
            {filteredProducts.length === 1 ? "piece" : "pieces"} in view
          </h2>
        </div>
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">
            Order
          </span>
          <Badge variant="default" size="lg">
            {activeSortLabel}
          </Badge>
        </div>
      </div>

      {displayedProducts.length === 0 ? (
        <Card className="overflow-hidden">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="px-6 py-16 text-center sm:px-12 sm:py-20"
          >
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-[#E8E5DF] bg-[#FAF9F6] text-[#A2574F]">
              <Package className="h-7 w-7 stroke-[1.5]" aria-hidden="true" />
            </div>
            <Badge variant="outline" className="mt-5">
              No matches
            </Badge>
            <h3 className="mt-4 font-serif text-2xl font-normal text-[#181716]">
              No pieces match your criteria
            </h3>
            <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-[#63605A]">
              Try resetting your active search or removing the in-stock filter
              to reveal more of the collection.
            </p>
            <Button
              type="button"
              variant="outline"
              size="md"
              onClick={clearFilters}
              className="mt-7"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
              Clear All Filters
            </Button>
          </motion.div>
        </Card>
      ) : (
        <section
          aria-label="Shop products"
          className="grid grid-cols-1 gap-x-5 gap-y-10 sm:grid-cols-2 sm:gap-x-6 sm:gap-y-12 lg:grid-cols-3 lg:gap-x-7 xl:grid-cols-4"
        >
          {displayedProducts.map((product, index) => (
            <motion.div
              key={product.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                duration: 0.4,
                delay: (index % 6) * 0.06,
                ease: [0.16, 1, 0.3, 1],
              }}
            >
              <ProductCard
                product={product}
                onQuickView={onQuickView}
                onClick={() => navigate(`/product/${product.slug}`)}
              />
            </motion.div>
          ))}
        </section>
      )}

      {hasMore && (
        <div className="pt-4">
          <div className="mx-auto max-w-2xl rounded-2xl border border-[#E8E5DF] bg-white px-5 py-6 text-center shadow-sm sm:px-8">
            <div className="flex items-center justify-between gap-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#827E77]">
              <span>
                Viewing {displayedProducts.length} of {filteredProducts.length}
              </span>
              <span className="text-[#A2574F]">{visibleProgress}%</span>
            </div>
            <Progress
              value={visibleProgress}
              aria-label="Products viewed"
              aria-valuetext={`${displayedProducts.length} of ${filteredProducts.length} products viewed`}
              className="mt-3 h-1.5"
            />
            <Button
              type="button"
              variant="outline"
              size="lg"
              onClick={() => setItemsToShow((prev) => prev + 6)}
              className="mt-5 w-full px-8 hover-lift-sm sm:w-auto"
            >
              Load Additional Pieces ({filteredProducts.length - itemsToShow}{" "}
              remaining)
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
