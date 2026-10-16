import React, { useState, useEffect, useRef } from "react";
import { useStore } from "../context/StoreContext";
import { ProductCard } from "../components/ProductCard";
import { CategorySlug, Product } from "../types";
import { ShopOccasion } from "../router/RouterContext";
import { useRouter } from "../router/RouterContext";
import {
  Search,
  SlidersHorizontal,
  ChevronLeft,
  X,
  Package,
  Filter,
  ChevronRight,
  Sparkles,
  ArrowRight,
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
  const headerTitle = selectedSale
    ? "The Sale Edit"
    : selectedOccasion
      ? OCCASION_TITLES[selectedOccasion]
      : selectedCollection === "best-sellers"
        ? "Best Sellers"
        : selectedCollection === "new-arrivals"
          ? "New Arrivals"
          : selectedCategory === "all"
            ? "All Products"
            : storeCategories.find((c) => c.slug === selectedCategory)?.name ||
              "The Collection";

  const headerDescription = selectedSale
    ? "Focused reductions on select pieces from the permanent collection, while they last."
    : storeCategories.find((c) => c.slug === selectedCategory)?.description ||
      (selectedCategory === "all"
        ? "Browse the complete MODEZA collection and find your next favorite."
        : "Tailored from organic fibers with meticulous attention to line, drape, and enduring tactility.");

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
    <div className="mx-auto w-full max-w-7xl space-y-6 px-4 pb-20 pt-6 sm:px-6 sm:pt-8 lg:px-8 2xl:max-w-[88rem]">
      <header className="space-y-4 border-b border-[#E8E5DF] pb-5">
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs text-[#827E77]">
          <Button type="button" variant="ghost" size="sm" onClick={() => navigate("/")} className="-ml-3 h-8 px-3 text-xs text-[#63605A]">Home</Button>
          <ChevronRight className="h-3 w-3" aria-hidden="true" />
          <span className="text-[#181716]">Shop</span>
          {selectedCategory !== "all" && <><ChevronRight className="h-3 w-3" aria-hidden="true" /><span className="max-w-40 truncate capitalize text-[#181716] sm:max-w-none">{selectedCategory}</span></>}
        </nav>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">MODEZA collection</p>
            <h1 className="mt-1 font-serif text-3xl font-normal tracking-tight text-[#181716] sm:text-4xl">{headerTitle}</h1>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-[#63605A]">{headerDescription}</p>
          </div>
          <div className="shrink-0 text-sm text-[#63605A]">{resultTotal} {resultTotal === 1 ? "product" : "products"}</div>
        </div>
      </header>

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
        <div className="mt-3 grid grid-cols-2 gap-2 border-t border-[#F3F1ED] pt-3 sm:grid-cols-4 lg:hidden">
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

      <div className="grid items-start gap-7 lg:grid-cols-[14rem_minmax(0,1fr)] xl:gap-9">
        <aside className="hidden lg:block" aria-label="Product filters">
          <Card
            className="sticky top-24 h-[calc(100dvh-7rem)] space-y-6 overflow-y-auto overscroll-contain rounded-xl border-[#E8E5DF] bg-white p-4 shadow-sm"
            role="region"
            tabIndex={0}
            aria-label="Scrollable product filters"
          >
            <section aria-labelledby="desktop-categories-heading">
              <h2 id="desktop-categories-heading" className="mb-2 text-sm font-semibold text-[#181716]">Categories</h2>
              <div className="space-y-1">
                <button type="button" onClick={() => { setSelectedCategory("all"); setPage(1); }} aria-pressed={selectedCategory === "all"} className={`w-full rounded-lg px-2.5 py-2 text-left text-xs transition-colors ${selectedCategory === "all" ? "bg-[#F1F0EE] font-semibold text-[#181716]" : "text-[#63605A] hover:bg-[#FAF9F6]"}`}>All products</button>
                {shopCategories.map((category) => <button key={category.slug} type="button" onClick={() => { setSelectedCategory(category.slug); setPage(1); }} aria-pressed={selectedCategory === category.slug} className={`w-full rounded-lg px-2.5 py-2 text-left text-xs transition-colors ${selectedCategory === category.slug ? "bg-[#F1F0EE] font-semibold text-[#181716]" : "text-[#63605A] hover:bg-[#FAF9F6]"}`}>{category.name}</button>)}
              </div>
            </section>
            <section className="border-t border-[#EEEAE3] pt-5" aria-labelledby="desktop-price-heading">
              <h2 id="desktop-price-heading" className="mb-3 text-sm font-semibold text-[#181716]">Price range</h2>
              <div className="grid grid-cols-2 gap-2">
                <Input id="filter-min-price-desktop" type="number" min="0" step="1" placeholder="Min KSh" aria-label="Minimum price in Kenyan shillings" value={minPrice} onChange={(event) => setMinPrice(event.target.value)} className="h-9 min-w-0 bg-[#FAF9F6] px-2 text-xs" />
                <Input id="filter-max-price-desktop" type="number" min="0" step="1" placeholder="Max KSh" aria-label="Maximum price in Kenyan shillings" value={maxPrice} onChange={(event) => setMaxPrice(event.target.value)} className="h-9 min-w-0 bg-[#FAF9F6] px-2 text-xs" />
              </div>
            </section>
            <section className="space-y-3 border-t border-[#EEEAE3] pt-5" aria-label="More filters">
              <label htmlFor="in-stock-sidebar" className="flex cursor-pointer items-center gap-2 text-xs text-[#3F4741]">
                <Checkbox id="in-stock-sidebar" checked={onlyInStock} onCheckedChange={(checked) => setOnlyInStock(checked === true)} />In stock only
              </label>
              <SortSelect id="filter-size-sidebar" value={selectedSize} onChange={(event) => setSelectedSize(event.target.value)} options={[{ value: "", label: "All sizes" }, ...facets.sizes.map((size) => ({ value: size, label: size }))]} aria-label="Filter by size" className="h-9 bg-[#FAF9F6] py-0 text-xs" />
              <SortSelect id="filter-color-sidebar" value={selectedColor} onChange={(event) => setSelectedColor(event.target.value)} options={[{ value: "", label: "All colors" }, ...facets.colors.map((color) => ({ value: color, label: color }))]} aria-label="Filter by color" className="h-9 bg-[#FAF9F6] py-0 text-xs" />
            </section>
            {hasActiveFilters && <Button type="button" variant="ghost" size="sm" fullWidth onClick={clearFilters} className="text-[#9E332B] hover:bg-[#FDF2F2]">Clear all filters</Button>}
          </Card>
        </aside>
        <div
          className="min-w-0 space-y-6 lg:h-[calc(100dvh-13rem)] lg:overflow-y-auto lg:overscroll-contain lg:pr-2"
          role="region"
          tabIndex={0}
          aria-label="Scrollable product results"
        >
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
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <label htmlFor="sort-results" className="shrink-0 text-xs text-[#63605A]">Sort by</label>
          <SortSelect
            id="sort-results"
            value={isNewArrivalsView ? "newest" : sortBy}
            onChange={(event) => setSortBy(event.target.value as SortOption)}
            options={SORT_OPTIONS}
            aria-label="Sort products"
            disabled={isNewArrivalsView}
            className="h-10 min-w-0 flex-1 bg-white py-0 text-xs sm:w-52 sm:flex-none"
          />
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
          className="grid min-w-0 grid-cols-2 gap-x-3 gap-y-6 sm:gap-x-5 sm:gap-y-8 lg:grid-cols-3 2xl:grid-cols-4"
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
      </div>
    </div>
  );
};
