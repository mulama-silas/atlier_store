import React, { useState, useEffect, useRef } from "react";
import { useStore } from "../context/StoreContext";
import { ProductCard } from "../components/ProductCard";
import { CategorySlug, Product } from "../types";
import { ShopOccasion } from "../router/RouterContext";
import { useRouter } from "../router/RouterContext";
import {
  Search,
  SlidersHorizontal,
  ArrowUpDown,
  ChevronLeft,
  X,
  Package,
  Filter,
  ChevronRight,
  Sparkles,
  ArrowRight,
  MoveRight,
} from "lucide-react";
import { Button } from "../components/modeza/Button";
import { Input, Select as SortSelect } from "../components/modeza/Input";
import { Badge } from "../components/modeza/Badge";
import { Card } from "../components/modeza/Card";
import { Checkbox } from "../components/modeza/Checkbox";
import { motion, AnimatePresence } from "motion/react";
import { audit } from "../lib/logger";
import { api } from "../services/apiClient";
import { mapProductDtoToDomain } from "../utils/productMapper";

export interface ShopPageProps {
  initialCategory?: CategorySlug;
  initialCollection?: "best-sellers" | "new-arrivals";
  initialOccasion?: ShopOccasion;
  initialQuery?: string;
  initialSale?: boolean;
  initialMinPrice?: string;
  initialMaxPrice?: string;
  initialSize?: string;
  initialColor?: string;
  initialInStock?: boolean;
  initialSort?: string;
  initialPage?: number;
  onQuickView: (product: Product) => void;
}

type SortOption = "featured" | "price-asc" | "price-desc" | "newest";

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
  initialMinPrice,
  initialMaxPrice,
  initialSize,
  initialColor,
  initialInStock,
  initialSort,
  initialPage = 1,
  onQuickView,
}) => {
  const { navigate, replace } = useRouter();
  const {
    categories: storeCategories,
    availablePromotions,
  } = useStore();
  const [filteredProducts, setFilteredProducts] = useState<Product[]>([]);
  const [resultTotal, setResultTotal] = useState(0);
  const [resultTotalPages, setResultTotalPages] = useState(1);
  const [page, setPage] = useState(Math.max(1, initialPage));
  const [isLoadingProducts, setIsLoadingProducts] = useState(true);
  const [loadMoreError, setLoadMoreError] = useState("");
  const [facets, setFacets] = useState<{ sizes: string[]; colors: string[] }>({ sizes: [], colors: [] });
  const catalogRequestId = useRef(0);
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
  const [onlyInStock, setOnlyInStock] = useState(Boolean(initialInStock));
  const [sortBy, setSortBy] = useState<SortOption>((initialSort as SortOption) || "featured");
  const [minPrice, setMinPrice] = useState(initialMinPrice || "");
  const [maxPrice, setMaxPrice] = useState(initialMaxPrice || "");
  const [selectedSize, setSelectedSize] = useState(initialSize || "");
  const [selectedColor, setSelectedColor] = useState(initialColor || "");
  const [showFilters, setShowFilters] = useState(false);
  const isNewArrivalsView = selectedCollection === "new-arrivals";
  const catalogFiltersKey = JSON.stringify([
    selectedCategory, searchQuery.trim(), sortBy, selectedCollection, selectedOccasion,
    selectedSale, minPrice, maxPrice, selectedSize, selectedColor, onlyInStock,
  ]);
  const previousCatalogFiltersKey = useRef(catalogFiltersKey);

  useEffect(() => {
    setSelectedCategory(initialCategory);
    setSelectedCollection(initialCollection);
    setSelectedOccasion(initialOccasion);
    setSelectedSale(Boolean(initialSale));
    setSearchQuery(initialQuery || "");
    setOnlyInStock(Boolean(initialInStock));
    setSortBy((initialSort as SortOption) || "featured");
    setMinPrice(initialMinPrice || "");
    setMaxPrice(initialMaxPrice || "");
    setSelectedSize(initialSize || "");
    setSelectedColor(initialColor || "");
    setPage(Math.max(1, initialPage));
  }, [
    initialCategory,
    initialCollection,
    initialOccasion,
    initialQuery,
    initialSale,
    initialMinPrice,
    initialMaxPrice,
    initialSize,
    initialColor,
    initialInStock,
    initialSort,
    initialPage,
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

  useEffect(() => {
    const query = new URLSearchParams();
    if (selectedCollection) query.set("collection", selectedCollection);
    if (selectedOccasion) query.set("occasion", selectedOccasion);
    if (searchQuery.trim()) query.set("q", searchQuery.trim());
    if (selectedSale) query.set("sale", "true");
    if (minPrice) query.set("minPrice", minPrice);
    if (maxPrice) query.set("maxPrice", maxPrice);
    if (selectedSize) query.set("size", selectedSize);
    if (selectedColor) query.set("color", selectedColor);
    if (onlyInStock) query.set("inStock", "true");
    if (sortBy !== "featured") query.set("sort", sortBy);
    if (page > 1) query.set("page", String(page));
    const path = selectedCategory === "all" ? "/shop" : `/shop/${selectedCategory}`;
    const queryString = query.toString();
    replace(queryString ? `${path}?${queryString}` : path);
  }, [replace, selectedCategory, selectedCollection, selectedOccasion, searchQuery, selectedSale,
    minPrice, maxPrice, selectedSize, selectedColor, onlyInStock, sortBy, page]);

  useEffect(() => {
    if (previousCatalogFiltersKey.current !== catalogFiltersKey) {
      previousCatalogFiltersKey.current = catalogFiltersKey;
      if (page !== 1) {
        setPage(1);
        return;
      }
    }
    const requestId = ++catalogRequestId.current;
    const timer = window.setTimeout(async () => {
      setIsLoadingProducts(true);
      setLoadMoreError("");
      try {
        const response = await api.getProducts({
          page, limit: 12, category: selectedCategory, search: searchQuery.trim(),
          sort: isNewArrivalsView ? "newest" : sortBy, collection: selectedCollection,
          occasion: selectedOccasion, sale: selectedSale, minPrice, maxPrice,
          size: selectedSize, color: selectedColor, inStock: onlyInStock,
        });
        if (catalogRequestId.current !== requestId) return;
        setFilteredProducts(response.data.map(mapProductDtoToDomain));
        setResultTotal(response.pagination.total);
        setResultTotalPages(Math.max(1, response.pagination.totalPages));
        if (page > response.pagination.totalPages && response.pagination.totalPages > 0) {
          setPage(response.pagination.totalPages);
        }
        if (response.facets) setFacets(response.facets);
      } catch {
        if (catalogRequestId.current === requestId) {
          setFilteredProducts([]);
          setResultTotal(0);
          setLoadMoreError("We couldn't load the collection. Check your connection and try again.");
        }
      } finally {
        if (catalogRequestId.current === requestId) setIsLoadingProducts(false);
      }
    }, searchQuery.trim() ? 250 : 0);
    return () => window.clearTimeout(timer);
  }, [selectedCategory, searchQuery, sortBy, selectedCollection, selectedOccasion,
    selectedSale, minPrice, maxPrice, selectedSize, selectedColor, onlyInStock, isNewArrivalsView,
    page, catalogFiltersKey]);

  const displayedProducts = filteredProducts;
  const activeFilterCount = [
    Boolean(searchQuery), onlyInStock, selectedCategory !== "all",
    Boolean(selectedCollection), Boolean(selectedOccasion), selectedSale,
    Boolean(minPrice), Boolean(maxPrice), Boolean(selectedSize), Boolean(selectedColor),
  ].filter(Boolean).length;
  const hasActiveFilters = activeFilterCount > 0;
  const activeSortLabel = isNewArrivalsView
    ? "Newest First"
    : (SORT_OPTIONS.find((option) => option.value === sortBy)?.label ?? "Featured First");

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
    setMinPrice("");
    setMaxPrice("");
    setSelectedSize("");
    setSelectedColor("");
    setPage(1);
  };

  const navigateToPage = (targetPage: number) => {
    const safePage = Math.max(1, Math.min(targetPage, resultTotalPages));
    if (safePage === page || isLoadingProducts) return;
    setLoadMoreError("");
    setPage(safePage);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const paginationPages = Array.from({ length: resultTotalPages }, (_, index) => index + 1)
    .filter((pageNumber) => pageNumber === 1 || pageNumber === resultTotalPages || Math.abs(pageNumber - page) <= 1);
  const shopCategories = storeCategories.filter((category) => category.slug !== "all");

  return (
    <div className="mx-auto w-full max-w-7xl space-y-8 px-4 pb-20 pt-6 sm:px-6 sm:pt-10 lg:px-8 2xl:max-w-[88rem]">
      <Card className="relative overflow-hidden rounded-[2rem] border-white/10 bg-[#181716] p-0 text-[#FAF9F6] shadow-xl hover:shadow-xl">
        <img
          src="https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?q=80&w=2200&auto=format&fit=crop"
          alt=""
          aria-hidden="true"
          className="absolute inset-0 z-0 h-full w-full object-cover object-center"
          referrerPolicy="no-referrer"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 z-0 bg-[#181716]/75"
        ></div>

        <div className="relative z-10 px-5 py-7 sm:px-8 sm:py-9 lg:px-12 lg:py-11">
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
                  {resultTotal}
                </span>
                <span className="text-xs uppercase tracking-wider text-white/50">
                  {resultTotal === 1 ? "Piece" : "Pieces"}
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

      {!hasActiveFilters && shopCategories.length > 0 && (
        <section aria-labelledby="shop-categories-title" className="space-y-4 sm:space-y-5">
          <div className="flex items-end justify-between gap-4">
            <div>
              <span className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">Find your next favorite</span>
              <h2 id="shop-categories-title" className="mt-1.5 font-serif text-2xl font-normal text-[#181716] sm:text-3xl">Shop by category</h2>
            </div>
            <span className="hidden pb-1 text-xs text-[#827E77] sm:block">Thoughtful pieces, made to be worn often</span>
          </div>
          <div className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:mx-0 sm:grid sm:snap-none sm:grid-cols-2 sm:gap-4 sm:overflow-visible sm:px-0 md:grid-cols-4">
            {shopCategories.map((category, index) => (
              <button
                key={category.slug}
                type="button"
                onClick={() => { setSelectedCategory(category.slug); setPage(1); }}
                className={`group relative flex min-h-28 w-[72vw] max-w-64 shrink-0 snap-start flex-col justify-between overflow-hidden rounded-2xl border p-4 text-left transition-all hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 sm:min-h-32 sm:w-full sm:max-w-none ${index % 3 === 1 ? "border-[#E6D8D2] bg-[#F7ECEA]" : index % 3 === 2 ? "border-[#DCE4DB] bg-[#F0F3EE]" : "border-[#E8E5DF] bg-white"}`}
                aria-pressed={selectedCategory === category.slug}
              >
                <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#A2574F]">0{index + 1}</span>
                <span className="flex items-end justify-between gap-2">
                  <span>
                    <span className="block font-serif text-xl text-[#181716] sm:text-2xl">{category.name}</span>
                    <span className="mt-1 block line-clamp-1 text-[11px] text-[#827E77]">{category.description}</span>
                  </span>
                  <span className="mb-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full border border-[#D8D3CB] text-[#63605A] transition-all group-hover:border-[#A2574F] group-hover:bg-[#A2574F] group-hover:text-white">
                    <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </span>
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      <Card className="sticky top-3 z-30 rounded-2xl border-[#E8E5DF] bg-white/95 p-3 shadow-md backdrop-blur-xl sm:p-4">
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
        <div className="mt-3 grid grid-cols-2 gap-2 border-t border-[#F3F1ED] pt-3 sm:grid-cols-4 lg:grid-cols-6">
          <Input id="filter-min-price" type="number" min="0" step="1" placeholder="Min KSh" aria-label="Minimum price in Kenyan shillings" value={minPrice} onChange={(event) => setMinPrice(event.target.value)} className="h-10 bg-[#FAF9F6] text-xs" />
          <Input id="filter-max-price" type="number" min="0" step="1" placeholder="Max KSh" aria-label="Maximum price in Kenyan shillings" value={maxPrice} onChange={(event) => setMaxPrice(event.target.value)} className="h-10 bg-[#FAF9F6] text-xs" />
          <SortSelect id="filter-size" value={selectedSize} onChange={(event) => setSelectedSize(event.target.value)} options={[{ value: "", label: "All sizes" }, ...facets.sizes.map((size) => ({ value: size, label: size }))]} aria-label="Filter by size" className="h-10 bg-[#FAF9F6] py-0 text-xs" />
          <SortSelect id="filter-color" value={selectedColor} onChange={(event) => setSelectedColor(event.target.value)} options={[{ value: "", label: "All colors" }, ...facets.colors.map((color) => ({ value: color, label: color }))]} aria-label="Filter by color" className="h-10 bg-[#FAF9F6] py-0 text-xs" />
          <p className="col-span-2 self-center text-[11px] text-[#827E77] sm:col-span-4 lg:col-span-2">Filters apply across the full collection and remain in this link.</p>
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
                  {resultTotal}{" "}
                  {resultTotal === 1 ? "piece" : "pieces"} match
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
            {headerTitle}
          </h2>
          <p className="mt-1.5 text-xs text-[#827E77]">Showing {displayedProducts.length} of {resultTotal} pieces</p>
        </div>
        <div className="flex items-center justify-between gap-2 self-start sm:self-auto">
          <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">
            Order
          </span>
          <Badge variant="default" size="lg">
            {activeSortLabel}
          </Badge>
          <span className="hidden items-center gap-1 text-[10px] text-[#827E77] sm:flex lg:hidden">Swipe for more <MoveRight className="h-3 w-3" aria-hidden="true" /></span>
        </div>
      </div>

      {isLoadingProducts && displayedProducts.length === 0 ? (
        <Card className="p-12 text-center text-sm text-[#827E77]" role="status">Loading the collection...</Card>
      ) : displayedProducts.length === 0 ? (
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
          className="-mx-4 grid grid-flow-col auto-rows-fr gap-3 overflow-x-auto snap-x snap-mandatory px-4 pb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:mx-0 sm:grid-flow-row sm:auto-cols-auto sm:grid-cols-2 sm:gap-x-6 sm:gap-y-10 sm:overflow-visible sm:px-0 sm:pb-0 sm:snap-none lg:grid-cols-3 lg:gap-x-7 lg:gap-y-12 xl:grid-cols-4"
          style={{ gridAutoColumns: "minmax(0, 42vw)" }}
        >
          {displayedProducts.map((product, index) => (
            <motion.div
              key={product.id}
              className="min-w-0 snap-start"
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

      {displayedProducts.length > 0 && !isLoadingProducts && (
        <div className="flex items-center justify-center gap-2 border-t border-[#E8E5DF] pt-5 text-center text-[10px] font-medium uppercase tracking-[0.16em] text-[#827E77] sm:hidden" aria-hidden="true">
          <span className="h-px w-8 bg-[#D8D3CB]" />
          Swipe to discover more
          <MoveRight className="h-3 w-3 text-[#A2574F]" />
          <span className="h-px w-8 bg-[#D8D3CB]" />
        </div>
      )}

      {resultTotalPages > 1 && displayedProducts.length > 0 && (
        <nav aria-label="Product pages" aria-busy={isLoadingProducts} className="pt-3">
          <div className="mx-auto flex max-w-4xl flex-col items-center justify-between gap-5 rounded-2xl border border-[#E8E5DF] bg-white px-5 py-5 shadow-sm sm:flex-row sm:px-7">
            <p className="text-xs tracking-wide text-[#827E77]" aria-live="polite">
              Showing <span className="font-semibold text-[#181716]">{(page - 1) * 12 + 1}–{Math.min(page * 12, resultTotal)}</span> of {resultTotal} pieces
            </p>
            <div className="flex items-center gap-1.5" role="group" aria-label="Choose product page">
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label="Previous page"
                onClick={() => navigateToPage(page - 1)}
                disabled={page <= 1 || isLoadingProducts}
                className="h-10 w-10 px-0"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </Button>
              {paginationPages.map((pageNumber, index) => {
                const previousPage = paginationPages[index - 1];
                return (
                  <React.Fragment key={pageNumber}>
                    {previousPage && pageNumber - previousPage > 1 && (
                      <span className="px-1 text-sm text-[#827E77]" aria-hidden="true">…</span>
                    )}
                    <Button
                      type="button"
                      variant={pageNumber === page ? "primary" : "outline"}
                      size="sm"
                      aria-label={`Page ${pageNumber}`}
                      aria-current={pageNumber === page ? "page" : undefined}
                      onClick={() => navigateToPage(pageNumber)}
                      disabled={isLoadingProducts}
                      className={`h-10 min-w-10 px-3 ${pageNumber === page ? "bg-[#A2574F] text-white hover:bg-[#8E4942]" : "border-transparent text-[#63605A] hover:border-[#E8E5DF]"}`}
                    >
                      {pageNumber}
                    </Button>
                  </React.Fragment>
                );
              })}
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label="Next page"
                onClick={() => navigateToPage(page + 1)}
                disabled={page >= resultTotalPages || isLoadingProducts}
                className="h-10 w-10 px-0"
              >
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </div>
          {loadMoreError && <p className="mt-3 text-center text-sm text-[#9E332B]" role="alert">{loadMoreError}</p>}
        </nav>
      )}
    </div>
  );
};
