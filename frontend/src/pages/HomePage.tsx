import React from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Feather,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Truck,
} from "lucide-react";
import { motion } from "motion/react";
import { useStore } from "../context/StoreContext";
import { ProductCard } from "../components/ProductCard";
import { Button } from "../components/modeza/Button";
import { useRouter } from "../router/RouterContext";
import { Product } from "../types";

export interface HomePageProps {
  onQuickView: (product: Product) => void;
}

export const HomePage: React.FC<HomePageProps> = ({ onQuickView }) => {
  const { navigate } = useRouter();
  const { products, categories } = useStore();
  const markedArrivals = products.filter((product) => product.isNewArrival);
  const newArrivals = (
    markedArrivals.length > 0
      ? markedArrivals
      : [...products].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  ).slice(0, 4);
  const markedBestSellers = products.filter((product) => product.isBestSeller);
  const bestSellers = (
    markedBestSellers.length > 0 ? markedBestSellers : products
  ).slice(0, 4);
  const shopCategories = categories.filter(
    (category) => category.slug !== "all",
  );

  return (
    <div className="bg-[#FAF9F6] pb-16 sm:pb-20">
      <section
        aria-labelledby="home-title"
        className="relative isolate overflow-hidden bg-[#181716] text-white"
      >
        <img
          src="https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?q=80&w=2200&auto=format&fit=crop"
          alt="A MODEZA-inspired look in fluid, natural fabric"
          className="absolute inset-0 -z-20 h-full w-full object-cover object-[center_38%]"
          referrerPolicy="no-referrer"
          fetchPriority="high"
        />
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-[#181716]/45"
        />
        <div className="mx-auto flex min-h-[78svh] max-w-7xl flex-col justify-between px-5 py-7 sm:px-8 sm:py-9 lg:px-12">
          <div className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-white/80">
            <span className="flex h-7 w-7 items-center justify-center rounded-full border border-white/45">
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
            Autumn / Winter 2026
          </div>

          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.65, ease: [0.16, 1, 0.3, 1] }}
            className="max-w-3xl py-12 sm:py-16"
          >
            <p className="mb-4 text-[10px] font-semibold uppercase tracking-[0.24em] text-[#F2C1A7]">
              The art of getting dressed
            </p>
            <h1
              id="home-title"
              className="font-serif text-5xl font-normal leading-[1.02] text-balance sm:text-6xl lg:text-7xl"
            >
              MODEZA
            </h1>
            <p className="mt-5 max-w-xl text-sm leading-7 text-white/85 sm:text-base sm:leading-8">
              A considered wardrobe of fluid tailoring, natural fibers, and
              pieces made to move with you.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-3">
              <Button
                variant="modeza-sandstone"
                size="lg"
                onClick={() => navigate("/shop")}
                className="gap-2"
              >
                Explore the collection
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="lg"
                onClick={() => navigate("/shop?collection=new-arrivals")}
                className="gap-2 border border-white/50 text-white hover:border-white hover:bg-white/10"
              >
                New arrivals
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </motion.div>

          <a
            href="#new-arrivals"
            className="flex items-center justify-between gap-4 border-t border-white/35 pt-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/75 transition-colors hover:text-white"
          >
            <span>Discover the collection</span>
            <ArrowDown className="h-4 w-4" aria-hidden="true" />
          </a>
        </div>
      </section>

      <section
        aria-label="Store services"
        className="border-b border-[#E8E5DF] bg-white"
      >
        <div className="mx-auto grid max-w-7xl grid-cols-1 divide-y divide-[#E8E5DF] px-5 sm:grid-cols-3 sm:divide-x sm:divide-y-0 sm:px-8 lg:px-12">
          <ServiceNote
            icon={<Truck className="h-4 w-4" />}
            label="Delivery across Kenya"
          />
          <ServiceNote
            icon={<RotateCcw className="h-4 w-4" />}
            label="30-day returns"
          />
          <ServiceNote
            icon={<ShieldCheck className="h-4 w-4" />}
            label="Secure checkout"
          />
        </div>
      </section>

      <section
        id="new-arrivals"
        aria-labelledby="arrivals-title"
        className="scroll-mt-24 mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12 lg:py-24"
      >
        <SectionHeading
          eyebrow="Just landed"
          title="New arrivals"
          actionLabel="Shop all new arrivals"
          onAction={() => navigate("/shop?collection=new-arrivals")}
        />
        {newArrivals.length > 0 ? (
          <ProductGrid
            products={newArrivals}
            onQuickView={onQuickView}
            onProductClick={(product) => navigate(`/product/${product.slug}`)}
          />
        ) : (
          <p className="border-y border-[#E8E5DF] py-8 text-sm text-[#63605A]">
            New pieces are on their way. Explore the full collection in the
            meantime.
          </p>
        )}
      </section>

      <section
        aria-labelledby="materials-title"
        className="overflow-hidden border-y border-[#E8E5DF] bg-[#F4ECE9]"
      >
        <div className="mx-auto grid max-w-7xl lg:grid-cols-2">
          <div className="flex flex-col justify-center px-5 py-14 sm:px-8 sm:py-16 lg:px-12 lg:py-20">
            <p className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
              <Feather className="h-4 w-4" aria-hidden="true" />
              Materials, considered
            </p>
            <h2
              id="materials-title"
              className="mt-5 max-w-lg font-serif text-3xl font-normal leading-tight sm:text-4xl lg:text-5xl"
            >
              Beautiful cloth changes how a piece feels.
            </h2>
            <p className="mt-5 max-w-xl text-sm leading-7 text-[#63605A] sm:text-base sm:leading-8">
              Traceable silk, responsible wool, and Mongolian cashmere bring
              softness, structure, and ease to the MODEZA wardrobe. Each
              material is chosen for the way it wears, not just the way it
              looks.
            </p>
            <Button
              variant="outline"
              size="md"
              onClick={() => navigate("/about#sustainability")}
              className="mt-7 w-fit gap-2"
            >
              Our approach to materials
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
          <div className="relative min-h-[320px] overflow-hidden bg-[#D8D3CB] sm:min-h-[420px] lg:min-h-[560px]">
            <img
              src="https://images.unsplash.com/photo-1558618666-fcd25c85cd64?q=80&w=1600&auto=format&fit=crop"
              alt="The texture and drape of natural textiles"
              className="absolute inset-0 h-full w-full object-cover"
              referrerPolicy="no-referrer"
              loading="lazy"
            />
            <span className="absolute bottom-5 left-5 bg-white/90 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#181716]">
              Natural fibers, considered design
            </span>
          </div>
        </div>
      </section>

      {shopCategories.length > 0 && (
        <section
          aria-labelledby="categories-title"
          className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12 lg:py-24"
        >
          <SectionHeading
            eyebrow="Find your form"
            title="Shop by category"
            actionLabel="Explore all pieces"
            onAction={() => navigate("/shop")}
          />
          <div className="grid gap-x-8 sm:grid-cols-2 lg:grid-cols-4">
            {shopCategories.slice(0, 8).map((category, index) => (
              <button
                key={category.id}
                type="button"
                onClick={() => navigate(`/shop/${category.slug}`)}
                className="group flex min-h-24 items-center justify-between gap-4 border-t border-[#D8D3CB] py-5 text-left transition-colors hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
              >
                <span className="flex min-w-0 items-baseline gap-3">
                  <span className="text-[10px] font-medium text-[#A29E96]">
                    0{index + 1}
                  </span>
                  <span className="truncate font-serif text-xl sm:text-2xl">
                    {category.name}
                  </span>
                </span>
                <ArrowUpRight
                  className="h-4 w-4 shrink-0 text-[#A2574F] transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </button>
            ))}
          </div>
        </section>
      )}

      <section
        aria-labelledby="bestsellers-title"
        className="border-y border-[#E8E5DF] bg-white"
      >
        <div className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12 lg:py-24">
          <SectionHeading
            eyebrow="Worn on repeat"
            title="Most-loved pieces"
            actionLabel="Browse best sellers"
            onAction={() => navigate("/shop?collection=best-sellers")}
          />
          {bestSellers.length > 0 ? (
            <ProductGrid
              products={bestSellers}
              onQuickView={onQuickView}
              onProductClick={(product) => navigate(`/product/${product.slug}`)}
            />
          ) : (
            <p className="border-y border-[#E8E5DF] py-8 text-sm text-[#63605A]">
              Explore the collection to find your next favorite piece.
            </p>
          )}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12">
        <div className="flex flex-col gap-6 border-b border-[#D8D3CB] pb-8 sm:flex-row sm:items-end sm:justify-between">
          <div className="max-w-2xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
              The MODEZA story
            </p>
            <h2 className="mt-4 font-serif text-3xl font-normal leading-tight sm:text-4xl">
              Made for your wardrobe, not just the moment.
            </h2>
          </div>
          <Button
            variant="ghost"
            size="md"
            onClick={() => navigate("/about")}
            className="w-fit gap-2 px-0"
          >
            Meet MODEZA
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
      </section>
    </div>
  );
};

const SectionHeading: React.FC<{
  eyebrow: string;
  title: string;
  actionLabel: string;
  onAction: () => void;
}> = ({ eyebrow, title, actionLabel, onAction }) => (
  <div className="mb-8 flex flex-col gap-4 border-b border-[#D8D3CB] pb-5 sm:mb-10 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
        {eyebrow}
      </p>
      <h2 className="mt-3 font-serif text-3xl font-normal leading-tight sm:text-4xl">
        {title}
      </h2>
    </div>
    <Button
      variant="ghost"
      size="sm"
      onClick={onAction}
      className="w-fit gap-1.5 px-0 text-[10px] uppercase tracking-[0.14em]"
    >
      {actionLabel}
      <ArrowRight className="h-4 w-4" aria-hidden="true" />
    </Button>
  </div>
);

const ProductGrid: React.FC<{
  products: Product[];
  onQuickView: (product: Product) => void;
  onProductClick: (product: Product) => void;
}> = ({ products, onQuickView, onProductClick }) => (
  <div className="grid grid-cols-1 justify-items-center gap-x-6 gap-y-10 sm:grid-cols-2 sm:gap-y-12 lg:grid-cols-4">
    {products.map((product, index) => (
      <motion.div
        key={product.id}
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-40px" }}
        transition={{
          duration: 0.4,
          delay: index * 0.06,
          ease: [0.16, 1, 0.3, 1],
        }}
        className="w-full"
      >
        <ProductCard
          product={product}
          onQuickView={onQuickView}
          onClick={() => onProductClick(product)}
        />
      </motion.div>
    ))}
  </div>
);

const ServiceNote: React.FC<{ icon: React.ReactNode; label: string }> = ({
  icon,
  label,
}) => (
  <div className="flex items-center gap-3 py-4 text-xs font-medium text-[#63605A] sm:justify-center sm:py-5">
    <span className="text-[#A2574F]">{icon}</span>
    {label}
  </div>
);
