import React from "react";
import { ArrowDown, ArrowRight, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useAuth } from "../context/AuthContext";
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
  const { user, isLoading: isAuthLoading } = useAuth();
  const { products } = useStore();
  const markedBestSellers = products.filter((product) => product.isBestSeller);
  const featuredPieces = (
    markedBestSellers.length > 0 ? markedBestSellers : products
  ).slice(0, 4);

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
        <div className="mx-auto flex min-h-[68svh] max-w-7xl flex-col justify-between px-5 py-7 sm:px-8 sm:py-9 lg:px-12">
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
              {!isAuthLoading && (user ? (
                <>
                  <Button
                    variant="modeza-sandstone"
                    size="lg"
                    onClick={() => navigate("/shop")}
                    className="gap-2"
                  >
                    Explore Collection
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="lg"
                    onClick={() => document.getElementById("featured-pieces")?.scrollIntoView({ behavior: "smooth" })}
                    className="gap-2 border border-white/50 text-white hover:border-white hover:bg-white/10"
                  >
                    Featured Pieces
                    <ArrowDown className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </>
              ) : (
                <Button
                  variant="modeza-sandstone"
                  size="lg"
                  onClick={() => navigate("/account")}
                  className="gap-2"
                >
                  Get Started
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              ))}
            </div>
          </motion.div>

          <a
            href="#featured-pieces"
            className="flex items-center justify-between gap-4 border-t border-white/35 pt-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/75 transition-colors hover:text-white"
          >
            <span>Discover the collection</span>
            <ArrowDown className="h-4 w-4" aria-hidden="true" />
          </a>
        </div>
      </section>

      <section
        id="featured-pieces"
        aria-labelledby="featured-title"
        className="scroll-mt-24 mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12 lg:py-24"
      >
        <SectionHeading
          id="featured-title"
          eyebrow="Selected for you"
          title="Featured Pieces"
          actionLabel="Explore the collection"
          onAction={() => navigate("/shop")}
        />
        {featuredPieces.length > 0 ? (
          <ProductGrid
            products={featuredPieces}
            onQuickView={onQuickView}
            onProductClick={(product) => navigate(`/product/${product.slug}`)}
          />
        ) : (
          <p className="border-y border-[#E8E5DF] py-8 text-sm text-[#63605A]">
            New pieces are on their way. Explore the full collection in the meantime.
          </p>
        )}
      </section>

      <section aria-labelledby="story-title" className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12">
        <div className="flex flex-col gap-6 border-b border-[#D8D3CB] pb-8 sm:flex-row sm:items-end sm:justify-between">
          <div className="max-w-2xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
              The MODEZA story
            </p>
            <h2 id="story-title" className="mt-4 font-serif text-3xl font-normal leading-tight sm:text-4xl">
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
  id: string;
  eyebrow: string;
  title: string;
  actionLabel: string;
  onAction: () => void;
}> = ({ id, eyebrow, title, actionLabel, onAction }) => (
  <div className="mb-8 flex flex-col gap-4 border-b border-[#D8D3CB] pb-5 sm:mb-10 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
        {eyebrow}
      </p>
      <h2
        id={id}
        className="mt-3 font-serif text-3xl font-normal leading-tight sm:text-4xl"
      >
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

