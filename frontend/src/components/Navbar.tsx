import React, { useState } from "react";
import {
  ArrowRight,
  Bell,
  CheckCheck,
  ChevronDown,
  Heart,
  LoaderCircle,
  LogOut,
  Menu,
  Search,
  ShoppingBag,
  Sparkles,
  User,
  X,
} from "lucide-react";
import { motion } from "motion/react";
import { CategorySlug } from "../types";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { useNotifications } from "../context/NotificationsContext";
import { useStore } from "../context/StoreContext";
import { useWishlist } from "../context/WishlistContext";
import { useRouter, AppRoute } from "../router/RouterContext";
import { CollapsibleGroup } from "./CollapsibleGroup";
import {
  Badge,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Popover,
  PopoverContent,
  PopoverTrigger,
  ScrollArea,
} from "./modeza";

const backendBaseUrl = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");
const modezaLogoUrl = `${backendBaseUrl}/static/images/logo.png`;

export interface NavbarProps {
  onOpenSearch?: () => void;
}

interface NavigationItem {
  label: string;
  path: string;
  slug?: CategorySlug;
}

export const Navbar: React.FC<NavbarProps> = ({ onOpenSearch }) => {
  const { navigate, route } = useRouter();
  const { cartCount } = useCart();
  const { wishlistCount } = useWishlist();
  const { categories: storeCategories } = useStore();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isCategoriesOpen, setIsCategoriesOpen] = useState(false);

  const categories: NavigationItem[] = storeCategories.map((category) => ({
    label: category.name,
    slug: category.slug as CategorySlug,
    path: category.slug === "all" ? "/shop" : `/shop/${category.slug}`,
  }));
  const productCategories = categories.filter(
    (category) => category.slug !== "all",
  );
  const currentCategory =
    route.path === "/shop" ? route.category || "all" : undefined;
  const isHomeActive = route.path === "/";
  const isNewArrivalsActive =
    route.path === "/shop" && route.collection === "new-arrivals";
  const isSaleActive = route.path === "/shop" && route.sale === true;
  const isCollectionsActive =
    route.path === "/shop" &&
    !route.category &&
    !route.collection &&
    !route.occasion &&
    !route.query &&
    !route.sale;

  const navigateFromShopMenu = (path: string) => {
    navigate(path);
    setIsCategoriesOpen(false);
  };

  const navigateAndCloseMobile = (path: string) => {
    navigate(path);
    setIsMobileMenuOpen(false);
  };

  return (
    <header className="sticky top-0 z-40">
      <AnnouncementBar />

      <motion.div
        initial={{ y: -100, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="glass relative border-b border-[#E8E5DF]/60"
      >
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="relative flex h-16 items-center justify-between sm:h-20">
            <LeftNavigation
              isMobileMenuOpen={isMobileMenuOpen}
              onToggleMobileMenu={() => setIsMobileMenuOpen((open) => !open)}
              isCategoriesOpen={isCategoriesOpen}
              onCategoriesOpenChange={setIsCategoriesOpen}
              currentCategory={currentCategory}
              isHomeActive={isHomeActive}
              isNewArrivalsActive={isNewArrivalsActive}
              isCollectionsActive={isCollectionsActive}
              isSaleActive={isSaleActive}
              onNavigate={navigate}
              categories={productCategories}
              onNavigateFromShop={navigateFromShopMenu}
            />

            <CenterLogo onNavigate={navigate} />

            <RightActions
              onNavigate={navigate}
              onOpenSearch={onOpenSearch}
              cartCount={cartCount}
              wishlistCount={wishlistCount}
            />
          </div>
        </div>
      </motion.div>

      <Dialog open={isMobileMenuOpen} onOpenChange={setIsMobileMenuOpen}>
        <MobileMenu
          isOpen={isMobileMenuOpen}
          onClose={() => setIsMobileMenuOpen(false)}
          onNavigate={navigateAndCloseMobile}
          categories={categories}
          productCategories={productCategories}
          currentCategory={currentCategory}
          route={route}
          cartCount={cartCount}
          wishlistCount={wishlistCount}
        />
      </Dialog>
    </header>
  );
};

const AnnouncementBar: React.FC = () => (
  <div className="relative overflow-hidden bg-[#181716] px-4 py-2">
    <div
      className="absolute inset-0 bg-gradient-to-r from-[#181716] via-[#A2574F]/25 to-[#181716]"
      aria-hidden="true"
    />
    <p className="relative text-center text-[9px] font-medium uppercase tracking-[0.18em] text-[#FAF9F6] sm:text-[10px] sm:tracking-[0.2em]">
      <Sparkles
        className="mr-1.5 inline-block h-3 w-3 text-[#E6C8CD]"
        aria-hidden="true"
      />
      Free shipping on orders over KES 5,000
      <Sparkles
        className="ml-1.5 inline-block h-3 w-3 text-[#E6C8CD]"
        aria-hidden="true"
      />
    </p>
  </div>
);

interface LeftNavigationProps {
  isMobileMenuOpen: boolean;
  onToggleMobileMenu: () => void;
  isCategoriesOpen: boolean;
  onCategoriesOpenChange: (open: boolean) => void;
  currentCategory?: string;
  isHomeActive: boolean;
  isNewArrivalsActive: boolean;
  isCollectionsActive: boolean;
  isSaleActive: boolean;
  onNavigate: (path: string) => void;
  categories: NavigationItem[];
  onNavigateFromShop: (path: string) => void;
}

const LeftNavigation: React.FC<LeftNavigationProps> = ({
  isMobileMenuOpen,
  onToggleMobileMenu,
  isCategoriesOpen,
  onCategoriesOpenChange,
  currentCategory,
  isHomeActive,
  isNewArrivalsActive,
  isCollectionsActive,
  isSaleActive,
  onNavigate,
  categories,
  onNavigateFromShop,
}) => (
  <div className="flex shrink-0 items-center gap-4 sm:gap-6 lg:pl-[188px]">
    <button
      type="button"
      onClick={onToggleMobileMenu}
      className="flex items-center gap-2 rounded-full p-2 text-[#181716] transition-colors hover:bg-[#F3F1ED] hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 lg:hidden"
      aria-label={isMobileMenuOpen ? "Close menu" : "Open menu"}
      aria-expanded={isMobileMenuOpen}
    >
      {isMobileMenuOpen ? (
        <X className="h-5 w-5" aria-hidden="true" />
      ) : (
        <Menu className="h-5 w-5" aria-hidden="true" />
      )}
    </button>

    <nav
      className="hidden items-center gap-7 lg:flex xl:gap-8"
      aria-label="Primary navigation"
    >
      <NavButton label="Home" onClick={() => onNavigate("/")} />
      <NavButton
        label="New Arrivals"
        onClick={() => onNavigate("/shop?collection=new-arrivals")}
      />

      <Popover open={isCategoriesOpen} onOpenChange={onCategoriesOpenChange}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className={`flex items-center gap-1.5 rounded-full px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 ${
              currentCategory
                ? "bg-[#F4ECE9] text-[#A2574F]"
                : "text-[#63605A] hover:bg-[#F3F1ED] hover:text-[#181716]"
            }`}
            aria-label="Shop categories"
          >
            Categories
            <ChevronDown
              className={`h-3.5 w-3.5 transition-transform duration-200 ${isCategoriesOpen ? "rotate-180" : ""}`}
              aria-hidden="true"
            />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          sideOffset={10}
          className="w-[min(90vw,36rem)] rounded-2xl border border-[#E8E5DF] bg-white p-5 shadow-2xl sm:p-6"
        >
          <ShopDropdown
            categories={categories}
            onNavigate={onNavigateFromShop}
          />
        </PopoverContent>
      </Popover>

      <NavButton label="Collections" onClick={() => onNavigate("/shop")} />
      <NavButton label="Sale" onClick={() => onNavigate("/shop?sale=true")} />
      <NavButton label="Contact Us" onClick={() => onNavigate("/contact")} />
    </nav>
  </div>
);

const NavButton: React.FC<{ label: string; onClick: () => void }> = ({
  label,
  onClick,
}) => (
  <button
    type="button"
    onClick={onClick}
    className="relative py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#63605A] transition-colors after:absolute after:bottom-0 after:left-1/2 after:h-[2px] after:w-0 after:bg-[#A2574F] after:transition-all after:duration-200 hover:text-[#181716] hover:after:left-0 hover:after:w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-4"
  >
    {label}
  </button>
);

const ShopDropdown: React.FC<{
  categories: NavigationItem[];
  onNavigate: (path: string) => void;
}> = ({ categories, onNavigate }) => (
  <div>
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-3 sm:gap-6">
      <DropdownColumn title="Shop">
        <DropdownLink
          label="All Products"
          onClick={() => onNavigate("/shop")}
          icon={<Sparkles className="h-3.5 w-3.5" />}
        />
        <DropdownLink
          label="Best Sellers"
          onClick={() => onNavigate("/shop?collection=best-sellers")}
        />
        <DropdownLink
          label="New Arrivals"
          onClick={() => onNavigate("/shop?collection=new-arrivals")}
        />
      </DropdownColumn>

      <DropdownColumn title="Shop by Category">
        <DropdownLink
          label="All Products"
          onClick={() => onNavigate("/shop")}
        />
        {categories.map((category) => (
          <DropdownLink
            key={category.slug}
            label={category.label}
            onClick={() => onNavigate(category.path)}
          />
        ))}
      </DropdownColumn>

      <DropdownColumn title="Shop by Occasion">
        <DropdownLink
          label="Everyday"
          onClick={() => onNavigate("/shop?occasion=everyday")}
        />
        <DropdownLink
          label="Evening"
          onClick={() => onNavigate("/shop?occasion=evening")}
        />
        <DropdownLink
          label="Special Occasions"
          onClick={() => onNavigate("/shop?occasion=special-occasions")}
        />
      </DropdownColumn>
    </div>

    <div className="mt-6 border-t border-[#E8E5DF] pt-4">
      <button
        type="button"
        onClick={() => onNavigate("/shop?collection=new-arrivals")}
        className="group flex w-full items-center justify-between rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-3 py-2.5 transition-colors hover:bg-[#F4ECE9] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
      >
        <span className="text-xs font-medium text-[#181716]">
          Explore New Collection
        </span>
        <ArrowRight
          className="h-4 w-4 text-[#A2574F] transition-transform group-hover:translate-x-1"
          aria-hidden="true"
        />
      </button>
    </div>
  </div>
);

const DropdownColumn: React.FC<{
  title: string;
  children: React.ReactNode;
}> = ({ title, children }) => (
  <div>
    <p className="px-2 pb-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#827E77]">
      {title}
    </p>
    <div className="space-y-1">{children}</div>
  </div>
);

interface DropdownLinkProps {
  label: string;
  onClick: () => void;
  icon?: React.ReactNode;
}

const DropdownLink: React.FC<DropdownLinkProps> = ({
  label,
  onClick,
  icon,
}) => (
  <button
    type="button"
    onClick={onClick}
    className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-xs text-[#63605A] transition-colors hover:bg-[#FAF9F6] hover:text-[#181716] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
  >
    {icon}
    {label}
  </button>
);

const CenterLogo: React.FC<{ onNavigate: (path: string) => void }> = ({
  onNavigate,
}) => (
  <div className="absolute left-1/2 w-[124px] -translate-x-1/2 text-center sm:w-[170px] lg:left-0 lg:w-[170px] lg:translate-x-0">
    <button
      type="button"
      onClick={() => onNavigate("/")}
      className="group block rounded-sm text-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-4"
      aria-label="MODEZA Home"
    >
      <img
        src={modezaLogoUrl}
        alt="MODEZA Haute Prêt-à-Porter"
        className="mx-auto h-9 w-auto max-w-full object-contain transition-opacity group-hover:opacity-75 sm:h-12"
      />
    </button>
  </div>
);

const RightActions: React.FC<{
  onNavigate: (path: string) => void;
  onOpenSearch?: () => void;
  cartCount: number;
  wishlistCount: number;
}> = ({ onNavigate, onOpenSearch, cartCount, wishlistCount }) => {
  const { notifications, unreadCount, markAsRead, markAllAsRead } =
    useNotifications();
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [isMarkingAll, setIsMarkingAll] = useState(false);

  return (
    <div className="relative flex shrink-0 items-center gap-1.5 border-l border-[#E8E5DF] pl-3 sm:gap-2 sm:pl-4 lg:gap-3 lg:pl-5">
      <button
        type="button"
        onClick={() => onNavigate("/about")}
        className="hidden rounded-full px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#63605A] transition-colors hover:bg-[#F3F1ED] hover:text-[#181716] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] lg:block"
      >
        About
      </button>

      <IconButton
        onClick={onOpenSearch}
        ariaLabel="Search catalog"
        title="Search collection"
      >
        <Search className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
      </IconButton>

      <div className="relative">
        <Popover
          open={isNotificationsOpen}
          onOpenChange={setIsNotificationsOpen}
        >
          <PopoverTrigger asChild>
            <button
              type="button"
              className="relative rounded-full p-2.5 text-[#181716] transition-colors hover:bg-[#F3F1ED] hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
              aria-label={`Notifications, ${unreadCount} unread`}
              title="Notifications"
            >
              <Bell className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
              {unreadCount > 0 && (
                <Badge
                  variant="danger"
                  className="absolute -right-1 -top-1 h-4 min-w-4 justify-center px-1 text-[9px]"
                >
                  {unreadCount > 9 ? "9+" : unreadCount}
                </Badge>
              )}
            </button>
          </PopoverTrigger>
          <PopoverContent
            align="end"
            sideOffset={10}
            className="w-[min(90vw,22rem)] rounded-2xl border border-[#E8E5DF] bg-white p-3 shadow-2xl"
          >
            <div className="mb-2 flex items-center justify-between gap-3 border-b border-[#E8E5DF] px-2 pb-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">
                  Notifications
                </span>
                {unreadCount > 0 && (
                  <Badge variant="warning" size="sm">
                    {unreadCount} unread
                  </Badge>
                )}
              </div>
              {unreadCount > 0 && (
                <button
                  type="button"
                  disabled={isMarkingAll}
                  onClick={() => {
                    if (isMarkingAll) return;
                    setIsMarkingAll(true);
                    void markAllAsRead().finally(() => setIsMarkingAll(false));
                  }}
                  className="inline-flex shrink-0 items-center gap-1 rounded-sm text-[10px] font-semibold uppercase tracking-[0.12em] text-[#A2574F] transition-colors hover:text-[#181716] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] disabled:cursor-wait disabled:opacity-50"
                >
                  {isMarkingAll ? (
                    <LoaderCircle
                      className="h-3 w-3 animate-spin"
                      aria-hidden="true"
                    />
                  ) : (
                    <CheckCheck className="h-3 w-3" aria-hidden="true" />
                  )}
                  {isMarkingAll ? "Saving" : "Mark all read"}
                </button>
              )}
            </div>

            <ScrollArea className="h-72">
              <div className="space-y-2 pr-2">
                {notifications.length === 0 ? (
                  <div className="px-2 py-6 text-center text-sm text-[#63605A]">
                    No notifications yet.
                  </div>
                ) : (
                  notifications.slice(0, 6).map((notification) => (
                    <button
                      key={notification.id}
                      type="button"
                      onClick={() => {
                        if (notification.link) {
                          onNavigate(notification.link);
                        }
                        void markAsRead(notification.id);
                        setIsNotificationsOpen(false);
                      }}
                      className={`w-full rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] ${
                        notification.isRead
                          ? "border-[#E8E5DF] bg-[#FAF9F6] hover:border-[#D8D3CB]"
                          : "border-[#E7D8B3] bg-[#FFFDF8] hover:border-[#D8C99E]"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-[10px] uppercase tracking-[0.14em] text-[#827E77]">
                            {notification.category}
                          </div>
                          <div className="mt-1 text-sm font-medium text-[#181716]">
                            {notification.title}
                          </div>
                        </div>
                        {!notification.isRead && (
                          <span
                            className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-[#A2574F]"
                            aria-label="Unread"
                          />
                        )}
                      </div>
                      <p className="mt-2 text-xs leading-5 text-[#63605A]">
                        {notification.message}
                      </p>
                    </button>
                  ))
                )}
              </div>
            </ScrollArea>

            {notifications.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  onNavigate("/account/notifications");
                  setIsNotificationsOpen(false);
                }}
                className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl border border-[#E8E5DF] py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#A2574F] transition-colors hover:bg-[#FAF9F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
              >
                <Bell className="h-3.5 w-3.5" aria-hidden="true" />
                View all notifications
              </button>
            )}
          </PopoverContent>
        </Popover>
      </div>

      <IconButton
        onClick={() => onNavigate("/account")}
        ariaLabel="Customer account"
        title="Customer account"
      >
        <User className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
      </IconButton>

      <div className="hidden sm:flex">
        <IconButton
          onClick={() => onNavigate("/wishlist")}
          ariaLabel={`Wishlist with ${wishlistCount} saved items`}
          title="Wishlist"
        >
          <span className="relative block">
            <Heart className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
            {wishlistCount > 0 && (
              <Badge className="absolute -right-2.5 -top-2.5 h-4 min-w-4 justify-center px-1 text-[9px]">
                {wishlistCount > 99 ? "99+" : wishlistCount}
              </Badge>
            )}
          </span>
        </IconButton>
      </div>

      <button
        type="button"
        onClick={() => onNavigate("/cart")}
        className="relative flex items-center gap-2 rounded-full p-2.5 text-[#181716] transition-colors hover:bg-[#F3F1ED] hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
        aria-label={`View shopping cart with ${cartCount} items`}
        title="View Cart"
      >
        <ShoppingBag className="h-5 w-5" strokeWidth={1.5} aria-hidden="true" />
        <span className="hidden text-[10px] font-semibold uppercase tracking-[0.16em] sm:inline">
          Cart ({cartCount})
        </span>
        {cartCount > 0 && (
          <Badge className="absolute -right-0.5 -top-0.5 h-4 min-w-4 justify-center px-1 text-[9px]">
            {cartCount}
          </Badge>
        )}
      </button>
    </div>
  );
};

const IconButton: React.FC<{
  onClick?: () => void;
  ariaLabel: string;
  title: string;
  children: React.ReactNode;
}> = ({ onClick, ariaLabel, title, children }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={!onClick}
    className="rounded-full p-2.5 text-[#181716] transition-colors hover:bg-[#F3F1ED] hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40"
    aria-label={ariaLabel}
    title={title}
  >
    {children}
  </button>
);

const MobileMenu: React.FC<{
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (path: string) => void;
  categories: NavigationItem[];
  productCategories: NavigationItem[];
  currentCategory?: string;
  route: AppRoute;
  cartCount: number;
  wishlistCount: number;
}> = ({
  isOpen,
  onClose,
  onNavigate,
  categories,
  productCategories,
  currentCategory,
  route,
  cartCount,
  wishlistCount,
}) => {
  const { user, signOut } = useAuth();
  if (!isOpen) return null;

  const shopRoute = route.path === "/shop" ? route : undefined;
  const browseActive =
    route.path === "/" || route.path === "/about" || Boolean(shopRoute?.sale);
  const categoriesActive = Boolean(shopRoute?.category);
  const shopActive = Boolean(
    shopRoute && !shopRoute.category && !shopRoute.occasion && !shopRoute.sale,
  );
  const occasionActive = Boolean(shopRoute?.occasion);
  const isPlainShop = Boolean(
    shopRoute &&
    !shopRoute.category &&
    !shopRoute.occasion &&
    !shopRoute.collection &&
    !shopRoute.query &&
    !shopRoute.sale,
  );

  return (
    <DialogContent className="left-auto right-0 top-0 flex h-dvh max-h-dvh w-[min(90vw,24rem)] max-w-[calc(100%-1rem)] translate-x-0 translate-y-0 flex-col overflow-hidden rounded-l-3xl rounded-r-none border-y-0 border-r-0 p-0 shadow-2xl lg:hidden">
      <div className="flex items-center justify-between border-b border-[#E8E5DF] px-6 py-5 pr-16">
        <div>
          <p className="text-[10px] uppercase tracking-[0.2em] text-[#827E77]">
            MODEZA
          </p>
          <DialogTitle className="mt-1 font-serif text-2xl font-normal text-[#181716]">
            Menu
          </DialogTitle>
        </div>
      </div>
      <DialogDescription className="sr-only">
        Browse the boutique, manage your account, and review your wishlist and
        cart.
      </DialogDescription>

      <div className="flex-1 overflow-y-auto overscroll-contain px-6 py-7">
        <CollapsibleGroup
          title="Browse"
          defaultOpen={browseActive}
          active={browseActive}
          className="mb-6"
        >
          <MobileLink
            label="Home"
            isActive={route.path === "/"}
            onClick={() => onNavigate("/")}
          />
          <MobileLink
            label="About"
            isActive={route.path === "/about"}
            onClick={() => onNavigate("/about")}
          />
          <MobileLink
            label="Contact Us"
            isActive={route.path === "/contact"}
            onClick={() => onNavigate("/contact")}
          />
          <MobileLink
            label="New Arrivals"
            isActive={shopRoute?.collection === "new-arrivals"}
            onClick={() => onNavigate("/shop?collection=new-arrivals")}
          />
          <MobileLink
            label="Sale"
            isActive={Boolean(shopRoute?.sale)}
            onClick={() => onNavigate("/shop?sale=true")}
          />
        </CollapsibleGroup>

        <CollapsibleGroup
          title="Categories"
          defaultOpen={categoriesActive}
          active={categoriesActive}
          className="mb-6"
        >
          {productCategories.map((category) => (
            <MobileLink
              key={category.slug}
              label={category.label}
              onClick={() => onNavigate(category.path)}
              isActive={currentCategory === category.slug}
            />
          ))}
        </CollapsibleGroup>

        <CollapsibleGroup
          title="Shop"
          defaultOpen={shopActive}
          active={shopActive}
          className="mb-6"
        >
          <MobileLink
            label="All Products"
            isActive={isPlainShop}
            onClick={() => onNavigate("/shop")}
          />
          <MobileLink
            label="Best Sellers"
            isActive={shopRoute?.collection === "best-sellers"}
            onClick={() => onNavigate("/shop?collection=best-sellers")}
          />
          <MobileLink
            label="New Arrivals"
            isActive={shopRoute?.collection === "new-arrivals"}
            onClick={() => onNavigate("/shop?collection=new-arrivals")}
          />
        </CollapsibleGroup>

        <CollapsibleGroup
          title="Shop by Occasion"
          defaultOpen={occasionActive}
          active={occasionActive}
          className="mb-6"
        >
          <MobileLink
            label="Everyday"
            isActive={shopRoute?.occasion === "everyday"}
            onClick={() => onNavigate("/shop?occasion=everyday")}
          />
          <MobileLink
            label="Evening"
            isActive={shopRoute?.occasion === "evening"}
            onClick={() => onNavigate("/shop?occasion=evening")}
          />
          <MobileLink
            label="Special Occasions"
            isActive={shopRoute?.occasion === "special-occasions"}
            onClick={() => onNavigate("/shop?occasion=special-occasions")}
          />
        </CollapsibleGroup>

        <div className="mt-8 space-y-2 border-t border-[#E8E5DF] pt-6">
          <MobileLink
            label="My Account"
            isActive={route.path.startsWith("/account")}
            onClick={() => onNavigate("/account")}
          />
          {user && (
            <button
              type="button"
              onClick={() => {
                void signOut();
                onClose();
              }}
              className="flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm text-[#9E332B] transition-colors hover:bg-[#FDF2F2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Sign Out
            </button>
          )}
          <MobileLink
            label={`Wishlist (${wishlistCount})`}
            isActive={route.path === "/wishlist"}
            onClick={() => onNavigate("/wishlist")}
          />
          <MobileLink
            label="Track Order"
            isActive={route.path === "/track"}
            onClick={() => onNavigate("/track")}
          />
          <MobileLink
            label={`Cart (${cartCount})`}
            isActive={route.path === "/cart"}
            onClick={() => onNavigate("/cart")}
          />
        </div>

        <div className="mt-8 border-t border-[#E8E5DF] pt-6">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#827E77]">
            {categories.length} collection{categories.length === 1 ? "" : "s"}{" "}
            available
          </p>
        </div>
      </div>
    </DialogContent>
  );
};

const MobileLink: React.FC<{
  label: string;
  onClick: () => void;
  isActive?: boolean;
}> = ({ label, onClick, isActive = false }) => (
  <button
    type="button"
    onClick={onClick}
    className={`w-full rounded-xl px-4 py-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] ${
      isActive
        ? "bg-[#A2574F] font-medium text-[#FAF9F6] shadow-sm"
        : "text-[#63605A] hover:bg-[#F4ECE9] hover:text-[#181716]"
    }`}
    aria-current={isActive ? "page" : undefined}
  >
    {label}
  </button>
);

export default Navbar;
