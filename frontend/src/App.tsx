import React, { useState } from "react";
import { RouterProvider, useRouter } from "./router/RouterContext";
import { StoreProvider } from "./context/StoreContext";
import { OrdersProvider } from "./context/OrdersContext";
import { CartProvider } from "./context/CartContext";
import { AuthProvider } from "./context/AuthContext";
import { Navbar } from "./components/Navbar";
import { Footer } from "./components/Footer";
import { CartDrawer } from "./components/CartDrawer";
import { SearchModal } from "./components/SearchModal";
import { QuickViewModal } from "./components/QuickViewModal";
import { HomePage } from "./pages/HomePage";
import { ShopPage } from "./pages/ShopPage";
import { ProductDetailPage } from "./pages/ProductDetailPage";
import { CartPage } from "./pages/CartPage";
import { CheckoutPage } from "./pages/CheckoutPage";
import { OrderSuccessPage } from "./pages/OrderSuccessPage";
import { OrderTrackingPage } from "./pages/OrderTrackingPage";
import { CustomerOrderDetailPage } from "./pages/CustomerOrderDetailPage";
import { AccountPage } from "./pages/AccountPage";
import { ProfileCompletionPage } from "./pages/ProfileCompletionPage";
import { AboutPage } from "./pages/AboutPage";
import { ContactPage } from "./pages/ContactPage";
import { WishlistPage } from "./pages/WishlistPage";
import { RecentlyViewedPage } from "./pages/RecentlyViewedPage";
import { LegalPage } from "./pages/LegalPage";
import { WishlistProvider } from "./context/WishlistContext";
import { NotificationsProvider } from "./context/NotificationsContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AssistantWidget } from "./components/assistant/AssistantWidget";
import { WhatsAppButton } from "./components/WhatsAppButton";
import { Product } from "./types";
import { Layers } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

function AppContent() {
  const { route, navigate, currentPath } = useRouter();
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [quickViewProduct, setQuickViewProduct] = useState<Product | null>(
    null,
  );

  const handleQuickView = (product: Product) => {
    setQuickViewProduct(product);
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#FAF9F6] text-[#181716] font-sans antialiased selection:bg-[#F4ECE9] selection:text-[#181716]">
      {/* Main Navbar */}
      <Navbar onOpenSearch={() => setIsSearchOpen(true)} />

      {/* Active Page View Rendering */}
      <main className="flex-grow">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={currentPath}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
          >
            {route.path === "/" && <HomePage onQuickView={handleQuickView} />}
            {route.path === "/shop" && (
              <ShopPage
                initialCategory={route.category || "all"}
                initialCollection={route.collection}
                initialOccasion={route.occasion}
                initialQuery={route.query}
                initialSale={route.sale}
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
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Overlays & Drawers */}
      <CartDrawer />
      <SearchModal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
      />
      <QuickViewModal
        product={quickViewProduct}
        isOpen={!!quickViewProduct}
        onClose={() => setQuickViewProduct(null)}
      />

      {/* AI shopping assistant (server-side Gemini via Django) */}
      <AssistantWidget />
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
