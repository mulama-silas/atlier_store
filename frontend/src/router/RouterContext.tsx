import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import { CategorySlug } from "../types";

export type ShopOccasion = "everyday" | "evening" | "special-occasions";

export type AppRoute =
  | { path: "/" }
  | {
      path: "/shop";
      category?: CategorySlug;
      collection?: "best-sellers" | "new-arrivals";
      occasion?: ShopOccasion;
      query?: string;
      sale?: boolean;
      minPrice?: string;
      maxPrice?: string;
      size?: string;
      color?: string;
      inStock?: boolean;
      sort?: string;
      page?: number;
    }
  | { path: "/product/:slug"; slug: string }
  | { path: "/cart" }
  | { path: "/checkout" }
  | { path: "/order/success"; orderNumber?: string }
  | { path: "/track"; orderNumber?: string }
  | { path: "/account" }
  | { path: "/account/orders" }
  | { path: "/account/orders/:orderNumber"; orderNumber: string }
  | { path: "/account/notifications" }
  | { path: "/account/profile" }
  | { path: "/account/addresses" }
  | { path: "/account/security" }
  | { path: "/account/complete-profile" }
  | { path: "/about" }
  | { path: "/contact" }
  | { path: "/wishlist" }
  | { path: "/recently-viewed" }
  | { path: "/privacy" }
  | { path: "/terms" }
  | { path: "/shipping" }
  | { path: "/returns" }
  | { path: "/cookies" }
  | { path: "/not-found" };

interface RouterContextType {
  currentPath: string;
  navigate: (path: string) => void;
  replace: (path: string) => void;
  route: AppRoute;
}

const RouterContext = createContext<RouterContextType | undefined>(undefined);

function parseShopRoute(cleanPath: string, searchString: string): AppRoute {
  const params = new URLSearchParams(searchString);
  const category = cleanPath.startsWith('/shop/')
    ? cleanPath.slice('/shop/'.length) as CategorySlug
    : undefined;
  const collection = params.get('collection');
  const occasion = params.get('occasion');
  const requestedSort = params.get('sort');
  const sort = requestedSort === 'featured' || requestedSort === 'newest' || requestedSort === 'price-asc' || requestedSort === 'price-desc'
    ? requestedSort
    : undefined;
  return {
    path: '/shop',
    category,
    collection: collection === 'best-sellers' || collection === 'new-arrivals' ? collection : undefined,
    occasion: occasion === 'everyday' || occasion === 'evening' || occasion === 'special-occasions' ? occasion : undefined,
    query: params.get('q') || undefined,
    sale: params.get('sale') === 'true',
    minPrice: params.get('minPrice') || undefined,
    maxPrice: params.get('maxPrice') || undefined,
    size: params.get('size') || undefined,
    color: params.get('color') || undefined,
    inStock: params.get('inStock') === 'true',
    sort,
    page: Math.max(1, Number.parseInt(params.get('page') || '1', 10) || 1),
  };
}

function parsePathToRoute(path: string): AppRoute {
  const cleanPath = path.split("?")[0].split("#")[0] || "/";
  const searchString = path.includes("?")
    ? path.slice(path.indexOf("?"))
    : typeof window !== "undefined"
      ? window.location.search
      : "";

  if (cleanPath === "/" || cleanPath === "") {
    return { path: "/" };
  }

  if (cleanPath === "/shop") {
    return parseShopRoute(cleanPath, searchString);
  }

  if (cleanPath.startsWith("/shop/")) {
    return parseShopRoute(cleanPath, searchString);
  }

  if (cleanPath.startsWith("/product/")) {
    const slug = cleanPath.replace("/product/", "");
    return { path: "/product/:slug", slug };
  }

  if (cleanPath === "/cart") {
    return { path: "/cart" };
  }

  if (cleanPath === "/account") {
    return { path: "/account" };
  }

  if (cleanPath.startsWith("/account/orders/")) {
    const orderNumber = cleanPath.replace("/account/orders/", "");
    return { path: "/account/orders/:orderNumber", orderNumber };
  }

  if (cleanPath === "/account/orders") {
    return { path: "/account/orders" };
  }

  if (cleanPath === "/account/notifications") {
    return { path: "/account/notifications" };
  }

  if (cleanPath === "/account/profile") {
    return { path: "/account/profile" };
  }

  if (cleanPath === "/account/addresses") {
    return { path: "/account/addresses" };
  }

  if (cleanPath === "/account/security") {
    return { path: "/account/security" };
  }

  if (cleanPath === "/account/complete-profile") {
    return { path: "/account/complete-profile" };
  }

  if (cleanPath === "/about") {
    return { path: "/about" };
  }

  if (cleanPath === "/contact") {
    return { path: "/contact" };
  }

  if (cleanPath === "/wishlist") {
    return { path: "/wishlist" };
  }

  if (cleanPath === "/recently-viewed") {
    return { path: "/recently-viewed" };
  }

  if (
    cleanPath === "/privacy" ||
    cleanPath === "/terms" ||
    cleanPath === "/shipping" ||
    cleanPath === "/returns" ||
    cleanPath === "/cookies"
  ) {
    return {
      path: cleanPath as
        | "/privacy"
        | "/terms"
        | "/shipping"
        | "/returns"
        | "/cookies",
    };
  }

  if (cleanPath === "/checkout") {
    return { path: "/checkout" };
  }

  if (cleanPath.startsWith("/order/success")) {
    const params = new URLSearchParams(searchString);
    const orderNumber = params.get("order") || undefined;
    return { path: "/order/success", orderNumber };
  }

  if (cleanPath.startsWith("/track")) {
    const params = new URLSearchParams(searchString);
    const orderNumber = params.get("order") || undefined;
    return { path: "/track", orderNumber };
  }

  return { path: "/not-found" };
}

export const RouterProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [currentPath, setCurrentPath] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return window.location.pathname || "/";
    }
    return "/";
  });

  const [route, setRoute] = useState<AppRoute>(() =>
    parsePathToRoute(currentPath),
  );

  const navigate = useCallback((newPath: string) => {
    if (typeof window !== "undefined") {
      window.history.pushState({}, "", newPath);
      setCurrentPath(newPath);
      setRoute(parsePathToRoute(newPath));
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, []);

  const replace = useCallback((newPath: string) => {
    if (typeof window !== "undefined") {
      window.history.replaceState({}, "", newPath);
      setCurrentPath(newPath.split("?")[0]);
      setRoute(parsePathToRoute(newPath));
    }
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const path = window.location.pathname || "/";
      setCurrentPath(path);
      setRoute(parsePathToRoute(path));
      window.scrollTo({ top: 0 });
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  return (
    <RouterContext.Provider value={{ currentPath, navigate, replace, route }}>
      {children}
    </RouterContext.Provider>
  );
};

export const useRouter = (): RouterContextType => {
  const context = useContext(RouterContext);
  if (!context) {
      throw new Error("useRouter must be used within a RouterProvider");
  }
  return context;
};
