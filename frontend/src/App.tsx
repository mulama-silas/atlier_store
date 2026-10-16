import React, { lazy, Suspense, useState } from "react";
import { RouterProvider, useRouter } from "./router/RouterContext";
import { StoreProvider } from "./context/StoreContext";
import { OrdersProvider } from "./context/OrdersContext";
import { CartProvider } from "./context/CartContext";
import { AuthProvider } from "./context/AuthContext";
import { Navbar } from "./components/Navbar";
import { Footer } from "./components/Footer";
const CartDrawer = lazy(() => import("./components/CartDrawer").then((component) => ({ default: component.CartDrawer })));
const SearchModal = lazy(() => import("./components/SearchModal").then((component) => ({ default: component.SearchModal })));
const QuickViewModal = lazy(() => import("./components/QuickViewModal").then((component) => ({ default: component.QuickViewModal })));
const HomePage = lazy(() => import("./pages/HomePage").then((page) => ({ default: page.HomePage })));
const ShopPage = lazy(() => import("./pages/ShopPage").then((page) => ({ default: page.ShopPage })));
const ProductDetailPage = lazy(() => import("./pages/ProductDetailPage").then((page) => ({ default: page.ProductDetailPage })));
const CartPage = lazy(() => import("./pages/CartPage").then((page) => ({ default: page.CartPage })));
const CheckoutPage = lazy(() => import("./pages/CheckoutPage").then((page) => ({ default: page.CheckoutPage })));
const OrderSuccessPage = lazy(() => import("./pages/OrderSuccessPage").then((page) => ({ default: page.OrderSuccessPage })));
const OrderTrackingPage = lazy(() => import("./pages/OrderTrackingPage").then((page) => ({ default: page.OrderTrackingPage })));
const CustomerOrderDetailPage = lazy(() => import("./pages/CustomerOrderDetailPage").then((page) => ({ default: page.CustomerOrderDetailPage })));
const AccountPage = lazy(() => import("./pages/AccountPage").then((page) => ({ default: page.AccountPage })));
const ProfileCompletionPage = lazy(() => import("./pages/ProfileCompletionPage").then((page) => ({ default: page.ProfileCompletionPage })));
const AboutPage = lazy(() => import("./pages/AboutPage").then((page) => ({ default: page.AboutPage })));
const ContactPage = lazy(() => import("./pages/ContactPage").then((page) => ({ default: page.ContactPage })));
const WishlistPage = lazy(() => import("./pages/WishlistPage").then((page) => ({ default: page.WishlistPage })));
const RecentlyViewedPage = lazy(() => import("./pages/RecentlyViewedPage").then((page) => ({ default: page.RecentlyViewedPage })));
const LegalPage = lazy(() => import("./pages/LegalPage").then((page) => ({ default: page.LegalPage })));
import { WishlistProvider } from "./context/WishlistContext";
import { NotificationsProvider } from "./context/NotificationsContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
const AssistantWidget = lazy(() => import("./components/assistant/AssistantWidget").then((component) => ({ default: component.AssistantWidget })));
import { WhatsAppButton } from "./components/WhatsAppButton";
import { Product } from "./types";
import { Layers } from "lucide-react";

function AppContent() {
  const { route, navigate, currentPath } = useRouter();
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [hasInteracted, setHasInteracted] = useState(false);
  const [quickViewProduct, setQuickViewProduct] = useState<Product | null>(
    null,
  );

  const handleQuickView = (product: Product) => {
    setQuickViewProduct(product);
  };

  return (
    <div onPointerDownCapture={() => setHasInteracted(true)} onKeyDownCapture={() => setHasInteracted(true)} className="min-h-screen flex flex-col bg-[#FAF9F6] text-[#181716] font-sans antialiased selection:bg-[#F4ECE9] selection:text-[#181716]">
      {/* Main Navbar */}
      <Navbar onOpenSearch={() => setIsSearchOpen(true)} />

      {/* Active Page View Rendering */}
      <main className="flex-grow">
        <div key={currentPath} className="animate-route-in">
            <Suspense fallback={<div role="status" className="mx-auto max-w-7xl px-5 py-20 text-center text-sm text-[#827E77]">Loading this page...</div>}>
            {route.path === "/" && <HomePage onQuickView={handleQuickView} />}
            {route.path === "/not-found" && (
              <section className="mx-auto max-w-3xl px-5 py-24 text-center sm:py-32">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#A2574F]">404 - Page not found</p>
                <h1 className="mt-4 font-serif text-4xl text-[#181716]">This page isn't here</h1>
                <p className="mx-auto mt-4 max-w-md text-sm leading-7 text-[#63605A]">The link may be outdated, or the page may have moved.</p>
                <button type="button" onClick={() => navigate("/")} className="mt-7 rounded-full bg-[#A2574F] px-6 py-3 text-sm font-medium text-white transition hover:bg-[#87453F]">Return to the home page</button>
              </section>
            )}
            {route.path === "/shop" && (
              <ShopPage
                initialCategory={route.category || "all"}
                initialCollection={route.collection}
                initialOccasion={route.occasion}
                initialQuery={route.query}
                initialSale={route.sale}
                initialMinPrice={route.minPrice}
                initialMaxPrice={route.maxPrice}
                initialSize={route.size}
                initialColor={route.color}
                initialInStock={route.inStock}
                initialSort={route.sort}
                onQuickView={handleQuickView}
              />
            )}
            {route.path === "/product/:slug" && (
              <ProductDetailPage
                slug={route.slug}
                onQuickView={handleQuickView}
              />
            )}
            {route.path === "/cart" && <CartPage />}
            {route.path === "/account/orders/:orderNumber" && (
              <CustomerOrderDetailPage orderNumber={route.orderNumber} />
            )}
            {route.path === "/account/complete-profile" && (
              <ProfileCompletionPage />
            )}
            {route.path !== "/account/orders/:orderNumber" &&
              (route.path === "/account" ||
                route.path.startsWith("/account/")) && <AccountPage />}
            {route.path === "/about" && <AboutPage />}
            {route.path === "/contact" && <ContactPage />}
            {route.path === "/checkout" && <CheckoutPage />}
            {route.path === "/order/success" && (
              <OrderSuccessPage orderNumber={route.orderNumber} />
            )}
            {route.path === "/track" && (
              <OrderTrackingPage orderNumber={route.orderNumber} />
            )}
            {route.path === "/wishlist" && <WishlistPage />}
            {route.path === "/recently-viewed" && <RecentlyViewedPage />}
            {(route.path === "/privacy" ||
              route.path === "/terms" ||
              route.path === "/shipping" ||
              route.path === "/returns" ||
              route.path === "/cookies") && (
              <LegalPage
                slug={
                  route.path.slice(1) as
                    | "privacy"
                    | "terms"
                    | "shipping"
                    | "returns"
                    | "cookies"
                }
              />
            )}
            </Suspense>
        </div>
      </main>

      {/* Overlays & Drawers */}
      {hasInteracted && (
        <Suspense fallback={null}>
          <CartDrawer />
          {isSearchOpen && <SearchModal isOpen onClose={() => setIsSearchOpen(false)} />}
          {quickViewProduct && <QuickViewModal product={quickViewProduct} isOpen onClose={() => setQuickViewProduct(null)} />}
        </Suspense>
      )}

      {/* AI shopping assistant (server-side Gemini via Django) */}
      {hasInteracted && <Suspense fallback={null}><AssistantWidget /></Suspense>}
      <WhatsAppButton />

      {/* Global Boutique Footer */}
      <Footer />
    </div>
  );
}

export default function App() {
  return (
    <RouterProvider>
      <StoreProvider>
        <AuthProvider>
          <OrdersProvider>
            <WishlistProvider>
              <CartProvider>
                <NotificationsProvider>
                  <ErrorBoundary>
                    <AppContent />
                  </ErrorBoundary>
                </NotificationsProvider>
              </CartProvider>
            </WishlistProvider>
          </OrdersProvider>
        </AuthProvider>
      </StoreProvider>
    </RouterProvider>
  );
}
