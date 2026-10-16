import React, { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Check,
  CreditCard,
  Download,
  ExternalLink,
  MapPin,
  Package,
  RotateCcw,
  Truck,
  X,
} from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "../components/modeza";
import { useOrders } from "../context/OrdersContext";
import { useRouter } from "../router/RouterContext";
import { ProductImage } from "../components/ui/ProductImage";
import { api } from "../services/apiClient";
import { Order, OrderStatus } from "../types";
import { ReceiptDTO } from "../types/api";
import { formatPrice } from "../utils/currency";
import {
  formatOrderDate,
  mapServerOrder,
} from "../utils/orderMapper";
import {
  canCancel,
  canMarkReceived,
  canRequestRefund,
} from "../utils/orderStatus";

interface CustomerOrderDetailPageProps {
  orderNumber?: string;
}

type OrderAction = "received" | "cancel" | "refund";

function getStatusBadge(status: OrderStatus) {
  switch (status) {
    case "shipped":
      return {
        label: "In Transit",
        bg: "bg-emerald-50 text-emerald-700 border-emerald-200",
      };
    case "processing":
      return {
        label: "Processing",
        bg: "bg-sky-50 text-sky-700 border-sky-200",
      };
    case "delivered":
      return {
        label: "Delivered",
        bg: "bg-emerald-100 text-emerald-800 border-emerald-300",
      };
    case "cancelled":
      return {
        label: "Cancelled",
        bg: "bg-rose-50 text-rose-700 border-rose-200",
      };
    case "pending":
    default:
      return {
        label: "Order Placed",
        bg: "bg-gray-100 text-gray-700 border-gray-200",
      };
  }
}

function getTimelineRank(status: OrderStatus): number {
  switch (status) {
    case "pending":
    case "confirmed":
      return 1;
    case "processing":
      return 2;
    case "shipped":
      return 3;
    case "delivered":
      return 4;
    case "cancelled":
      return 0;
    default:
      return 1;
  }
}

function getPaymentMethodDisplay(method?: string) {
  const m = (method || "card").toLowerCase();
  if (m === "card") {
    return {
      type: "card",
      label: "Visa ending in 4321",
      badge: "VISA",
    };
  }
  if (m === "mpesa") {
    return {
      type: "mpesa",
      label: "M-Pesa payment",
      badge: "M-PESA",
    };
  }
  return {
    type: "cash",
    label: "Pay on Delivery",
    badge: "COD",
  };
}

export const CustomerOrderDetailPage: React.FC<CustomerOrderDetailPageProps> = ({
  orderNumber: propOrderNumber,
}) => {
  const { navigate } = useRouter();
  const { getOrder, receiveOrder, cancelOrder, requestOrderReturn } = useOrders();
  const [order, setOrder] = useState<Order | null>(() => {
    if (!propOrderNumber) return null;
    return getOrder(propOrderNumber) || null;
  });
  const [receipt, setReceipt] = useState<ReceiptDTO | null>(null);
  const [receiptLoading, setReceiptLoading] = useState(false);
  const [receiptError, setReceiptError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingAction, setPendingAction] = useState<OrderAction | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    const orderNum = propOrderNumber || "";
    if (!orderNum) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    const local = getOrder(orderNum);
    if (local) setOrder(local);

    setLoading(true);
    api
      .getOrder(orderNum)
      .then((serverOrder) => {
        if (cancelled) return;
        setOrder(mapServerOrder(serverOrder));
        setError("");
      })
      .catch(() => {
        if (cancelled) return;
        setOrder(null);
        setError("No order could be found for this reference.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [propOrderNumber, getOrder]);

  const handleConfirmAction = useCallback(async () => {
    if (!order || !pendingAction) return;

    setActionLoading(true);
    setError("");

    try {
      const result =
        pendingAction === "received"
          ? await receiveOrder(order.orderNumber)
          : pendingAction === "cancel"
            ? await cancelOrder(order.orderNumber)
            : await requestOrderReturn(order.orderNumber, "");

      if (result.success && result.order) {
        setOrder(result.order);
        setError("");
      } else {
        setError(result.message);
      }
    } catch {
      setError("The order could not be updated right now. Please try again.");
    } finally {
      setActionLoading(false);
      setPendingAction(null);
    }
  }, [cancelOrder, order, pendingAction, receiveOrder, requestOrderReturn]);

  const handleDownloadReceipt = useCallback(async () => {
    if (!receipt) return;
    setDownloading(true);
    setReceiptError("");
    try {
      const blob = await api.downloadReceipt(receipt.receiptNumber);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${receipt.receiptNumber}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setReceiptError(
        err instanceof Error
          ? err.message
          : "The receipt could not be downloaded.",
      );
    } finally {
      setDownloading(false);
    }
  }, [receipt]);

  useEffect(() => {
    const receiptVisible =
      order && order.status !== "pending" && order.status !== "cancelled";
    if (!receiptVisible) {
      setReceipt(null);
      setReceiptError("");
      setReceiptLoading(false);
      return;
    }

    let cancelled = false;
    setReceipt(null);
    setReceiptError("");
    setReceiptLoading(true);
    api
      .getOrderReceipt(order.orderNumber)
      .then((data) => {
        if (cancelled) return;
        if (data.status === "generated") {
          setReceipt(data);
          return;
        }
        setReceiptError("The official invoice is not available yet.");
      })
      .catch((err) => {
        if (cancelled) return;
        const receiptApiError = err as Error & {
          code?: string;
          status?: number;
        };
        if (
          receiptApiError.status === 404 &&
          receiptApiError.code === "RECEIPT_NOT_FOUND"
        ) {
          setReceiptError("The official invoice is being generated.");
          return;
        }
        setReceiptError(
          receiptApiError.message || "The official invoice could not be checked.",
        );
      })
      .finally(() => {
        if (!cancelled) setReceiptLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [order]);

  if (!propOrderNumber) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-xl rounded-2xl border border-gray-150 bg-white p-8 text-center shadow-sm sm:p-12">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-red-50 text-red-600">
            <X className="h-6 w-6" aria-hidden="true" />
          </div>
          <h2 className="mt-5 text-2xl font-bold text-gray-900">
            Missing Order Reference
          </h2>
          <p className="mx-auto mt-3 max-w-sm text-sm text-gray-500">
            We could not identify the order you are looking for.
          </p>
          <Button
            type="button"
            onClick={() => navigate("/account/orders")}
            className="mt-7 rounded-xl bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-blue-700"
          >
            Back to Orders
          </Button>
        </div>
      </div>
    );
  }

  const currentRank = order ? getTimelineRank(order.status) : 1;
  const statusBadge = order ? getStatusBadge(order.status) : null;
  const paymentInfo = getPaymentMethodDisplay(order?.paymentMethod);

  const placedDateStr = order
    ? formatOrderDate(order.createdAt, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "numeric",
      })
    : "Oct 14, 2:30 PM";

  const placedDateHeader = order
    ? formatOrderDate(order.createdAt, {
        month: "long",
        day: "numeric",
        year: "numeric",
      })
    : "October 14, 2026";

  const processingDateStr = order?.updatedAt
    ? formatOrderDate(order.updatedAt, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "numeric",
      })
    : "Oct 15, 9:00 AM";

  const trackingNumber = order
    ? `TRK-${order.orderNumber.replace(/[^0-9A-Z]/gi, "").slice(-8).toUpperCase() || "884920482"}`
    : "TRK-884920482";

  return (
    <div className="min-h-screen bg-[#FDFDFE] text-[#1E2024] antialiased">
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-10 lg:px-8">
        <button
          type="button"
          onClick={() => navigate("/account/orders")}
          className="group mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-900 transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5 transition-transform group-hover:-translate-x-0.5" />
          <span>Back to Orders</span>
        </button>

        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between sm:mb-8">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-gray-900 sm:text-3xl">
              Order Details
            </h1>
            <p className="mt-1 text-xs text-gray-500 sm:text-sm">
              Order ID: <strong className="font-semibold text-gray-900">#{order?.orderNumber || propOrderNumber}</strong> &bull; Placed on {placedDateHeader}
            </p>
          </div>

          {statusBadge && (
            <div className="flex items-center gap-2">
              <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${statusBadge.bg}`}>
                {statusBadge.label}
              </span>
              {order?.status === "shipped" && (
                <>
                  <span className="text-xs text-gray-400">or</span>
                  <span className="inline-flex items-center rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
                    Processing
                  </span>
                </>
              )}
            </div>
          )}
        </div>

        {loading && !order && (
          <div className="rounded-2xl border border-gray-150 bg-white p-12 text-center shadow-sm">
            <Package className="mx-auto h-8 w-8 animate-pulse text-blue-600" />
            <p className="mt-4 text-sm text-gray-600">Loading order details...</p>
          </div>
        )}

        {error && !order && (
          <div className="rounded-2xl border border-gray-150 bg-white p-10 text-center shadow-sm">
            <X className="mx-auto h-8 w-8 text-rose-500" />
            <p className="mt-3 text-sm text-gray-700">{error}</p>
            <Button
              type="button"
              onClick={() => navigate("/account/orders")}
              className="mt-5 rounded-xl bg-blue-600 px-5 py-2 text-xs font-semibold text-white"
            >
              Back to Orders
            </Button>
          </div>
        )}

        {order && (
          <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-12 lg:gap-8">
            <div className="space-y-6 lg:col-span-7">
              <div className="overflow-hidden rounded-2xl border border-gray-150 bg-white p-5 shadow-[0_2px_14px_rgba(0,0,0,0.04)] sm:p-7">
                <div className="flex items-center justify-between pb-6 border-b border-gray-100">
                  <h2 className="text-base font-bold text-gray-900 sm:text-lg">
                    Shipment Progress
                  </h2>
                  <Button
                    type="button"
                    onClick={() => navigate(`/track?order=${encodeURIComponent(order.orderNumber)}`)}
                    className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 transition-all"
                  >
                    Track Order
                  </Button>
                </div>

                <div className="mt-6 relative pl-1">
                  <div className="relative flex items-start gap-4 pb-8">
                    <div
                      className={`absolute left-3.5 top-7 bottom-0 w-0.5 ${
                        currentRank >= 2 ? "bg-emerald-500" : "bg-gray-200"
                      }`}
                    />
                    <div className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white shadow-sm">
                      <Check className="h-4 w-4 stroke-[3]" />
                    </div>
                    <div className="min-w-0 flex-1 pt-0.5">
                      <p className="text-sm font-bold text-gray-900">Order Placed</p>
                      <p className="mt-0.5 text-xs text-gray-500">{placedDateStr}</p>
                    </div>
                  </div>

                  <div className="relative flex items-start gap-4 pb-8">
                    <div
                      className={`absolute left-3.5 top-7 bottom-0 w-0.5 ${
                        currentRank >= 3 ? "bg-emerald-500" : "bg-gray-200"
                      }`}
                    />
                    <div
                      className={`relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs transition-colors ${
                        currentRank >= 2
                          ? "bg-emerald-500 text-white shadow-sm"
                          : "border-2 border-gray-200 bg-white text-transparent"
                      }`}
                    >
                      {currentRank >= 2 ? <Check className="h-4 w-4 stroke-[3]" /> : null}
                    </div>
                    <div className="min-w-0 flex-1 pt-0.5 flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <p className={`text-sm ${currentRank >= 2 ? "font-bold text-gray-900" : "font-medium text-gray-400"}`}>
                          Processing
                        </p>
                        {currentRank >= 2 && (
                          <p className="mt-0.5 text-xs text-gray-500">{processingDateStr}</p>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="relative flex items-start gap-4 pb-8">
                    <div
                      className={`absolute left-3.5 top-7 bottom-0 w-0.5 ${
                        currentRank >= 4 ? "bg-emerald-500" : "bg-gray-200"
                      }`}
                    />
                    <div
                      className={`relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs transition-colors ${
                        currentRank >= 3
                          ? "bg-emerald-500 text-white shadow-sm"
                          : "border-2 border-gray-200 bg-white text-transparent"
                      }`}
                    >
                      {currentRank >= 3 ? <Check className="h-4 w-4 stroke-[3]" /> : null}
                    </div>
                    <div className="min-w-0 flex-1 pt-0.5 flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-1 sm:gap-4">
                      <div>
                        <p className={`text-sm ${currentRank >= 3 ? "font-bold text-gray-900" : "font-medium text-gray-400"}`}>
                          Shipped
                        </p>
                        {currentRank >= 3 && (
                          <p className="mt-0.5 text-xs text-gray-500">{processingDateStr}</p>
                        )}
                      </div>

                      <div className="text-xs sm:text-right text-gray-500">
                        <p>
                          Carrier:{" "}
                          <button
                            type="button"
                            onClick={() => navigate(`/track?order=${encodeURIComponent(order.orderNumber)}`)}
                            className="inline-flex items-center gap-0.5 font-medium text-blue-600 hover:underline"
                          >
                            Link <ExternalLink className="h-2.5 w-2.5" />
                          </button>
                        </p>
                        <p className="mt-0.5">
                          Tracking number:{" "}
                          <button
                            type="button"
                            onClick={() => navigate(`/track?order=${encodeURIComponent(order.orderNumber)}`)}
                            className="font-medium text-blue-600 underline underline-offset-2 hover:text-blue-700"
                          >
                            {trackingNumber}
                          </button>
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="relative flex items-start gap-4">
                    <div
                      className={`relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs transition-colors ${
                        currentRank >= 4
                          ? "bg-emerald-500 text-white shadow-sm"
                          : "border-2 border-gray-200 bg-white text-transparent"
                      }`}
                    >
                      {currentRank >= 4 ? <Check className="h-4 w-4 stroke-[3]" /> : null}
                    </div>
                    <div className="min-w-0 flex-1 pt-0.5 flex flex-wrap items-baseline justify-between gap-2">
                      <p className={`text-sm ${currentRank >= 4 ? "font-bold text-gray-900" : "font-medium text-gray-400"}`}>
                        Out for Delivery
                      </p>
                      <span className="text-xs text-gray-400 italic">
                        {currentRank >= 4 ? "Completed" : "in progress"}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="overflow-hidden rounded-2xl border border-gray-150 bg-white shadow-[0_2px_14px_rgba(0,0,0,0.04)]">
                <div className="grid grid-cols-1 sm:grid-cols-2">
                  <div className="p-5 sm:p-6">
                    <h2 className="text-sm font-bold text-gray-900 sm:text-base">
                      Delivery Address
                    </h2>
                    <p className="mt-2 text-sm font-bold text-gray-900">
                      {order.customer.firstName} {order.customer.lastName}
                    </p>
                    <p className="mt-1 text-xs text-gray-600 leading-relaxed">
                      {order.customer.addressLine1}
                      {order.customer.addressLine2 ? `, ${order.customer.addressLine2}` : ""}
                    </p>
                    <p className="text-xs text-gray-500">
                      {[order.customer.city, order.customer.stateOrProvince, order.customer.postalCode]
                        .filter(Boolean)
                        .join(", ")}
                    </p>
                    <p className="mt-1 text-xs text-gray-400">{order.customer.country}</p>
                  </div>

                  <div className="relative h-32 w-full bg-[#EBF3ED] sm:h-auto overflow-hidden border-t sm:border-t-0 sm:border-l border-gray-100">
                    <svg
                      className="absolute inset-0 h-full w-full object-cover opacity-75"
                      viewBox="0 0 240 120"
                      preserveAspectRatio="none"
                    >
                      <rect width="240" height="120" fill="#E8F1EC" />
                      <path d="M 0,40 Q 60,20 120,45 T 240,30 L 240,0 L 0,0 Z" fill="#DCECE3" />
                      <path d="M 40,120 Q 90,80 180,95 T 240,80 L 240,120 Z" fill="#E0EDE5" />

                      <path d="M 170,0 Q 185,40 220,55 T 240,120 L 240,0 Z" fill="#D5E8F5" />
                      <path d="M 0,85 Q 40,75 50,120 Z" fill="#D5E8F5" />

                      <path d="M 0,60 L 240,55" stroke="#FFFFFF" strokeWidth="4" />
                      <path d="M 80,0 L 85,120" stroke="#FFFFFF" strokeWidth="4" />
                      <path d="M 150,0 L 140,120" stroke="#FFFFFF" strokeWidth="3" />
                      <path d="M 0,25 L 170,25" stroke="#FFFFFF" strokeWidth="2.5" />
                      <path d="M 30,95 L 240,90" stroke="#FFFFFF" strokeWidth="3" />
                    </svg>

                    <div className="absolute inset-0 flex items-center justify-center">
                      <div className="relative flex flex-col items-center">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-blue-600 text-white shadow-md">
                          <div className="h-2.5 w-2.5 rounded-full bg-white" />
                        </div>
                        <div className="-mt-1 h-2 w-2 rotate-45 bg-blue-600" />
                        <div className="mt-0.5 h-1.5 w-4 rounded-full bg-black/15 blur-[1px]" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="overflow-hidden rounded-2xl border border-gray-150 bg-white p-5 shadow-[0_2px_14px_rgba(0,0,0,0.04)] sm:p-6">
                <h2 className="text-sm font-bold text-gray-900 sm:text-base">
                  Payment Information
                </h2>

                <div className="mt-3 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                  <div>
                    <p className="text-xs font-semibold text-gray-700">Billing Address</p>
                    <p className="mt-1 text-xs text-gray-600 leading-relaxed">
                      {order.customer.addressLine1}
                      {order.customer.addressLine2 ? `, ${order.customer.addressLine2}` : ""}
                    </p>
                    <p className="text-xs text-gray-500">
                      {[order.customer.city, order.customer.stateOrProvince, order.customer.postalCode]
                        .filter(Boolean)
                        .join(", ")}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 pt-1 sm:pt-0">
                    <span className="inline-flex items-center justify-center rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-700">
                      {paymentInfo.badge}
                    </span>
                    <span className="text-xs font-medium text-gray-700">
                      {paymentInfo.label}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="lg:col-span-5">
              <div className="overflow-hidden rounded-2xl border border-gray-150 bg-white p-5 shadow-[0_2px_14px_rgba(0,0,0,0.04)] sm:p-7">
                <h2 className="text-base font-bold text-gray-900 sm:text-lg">
                  Items Ordered
                </h2>

                <div className="mt-4 divide-y divide-gray-100">
                  {order.items.map((item) => (
                    <div key={item.id} className="flex items-center gap-3.5 py-3.5">
                      <div className="h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-gray-50 border border-gray-100 p-1 flex items-center justify-center">
                        <ProductImage
                          src={item.image}
                          alt={item.productName}
                          className="h-full w-full object-contain"
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h3 className="truncate text-sm font-semibold text-gray-900">
                          {item.productName}
                        </h3>
                        {item.variantDetails && (
                          <p className="mt-0.5 text-xs text-gray-400">
                            Size: {item.variantDetails}
                          </p>
                        )}
                        <p className="mt-0.5 text-xs text-gray-500">
                          Qty: {item.quantity}
                        </p>
                      </div>
                      <div className="text-right">
                        <span className="text-sm font-semibold text-gray-900">
                          {formatPrice(item.subtotal)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-4 space-y-2 border-t border-gray-100 pt-4 text-xs sm:text-sm text-gray-600">
                  <div className="flex justify-between">
                    <span>Subtotal</span>
                    <span className="font-medium text-gray-900">{formatPrice(order.subtotal)}</span>
                  </div>
                  {order.discount && order.discount.amount > 0 && (
                    <div className="flex justify-between text-emerald-600">
                      <span>Discount</span>
                      <span>-{formatPrice(order.discount.amount)}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span>Shipping</span>
                    <span className="font-medium text-gray-900">
                      {order.shippingCost > 0 ? formatPrice(order.shippingCost) : "$0.00"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Tax</span>
                    <span className="font-medium text-gray-900">
                      {order.tax > 0 ? formatPrice(order.tax) : "$0.00"}
                    </span>
                  </div>

                  <div className="flex items-baseline justify-between border-t border-gray-100 pt-3.5">
                    <span className="text-sm font-bold text-gray-900 sm:text-base">Total:</span>
                    <span className="text-lg font-bold text-gray-900 sm:text-xl">
                      {formatPrice(order.total)}
                    </span>
                  </div>
                </div>

                <div className="mt-6 space-y-3">
                  <Button
                    type="button"
                    onClick={() => navigate(`/track?order=${encodeURIComponent(order.orderNumber)}`)}
                    className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 active:scale-[0.99] transition-all"
                  >
                    Track Shipment
                  </Button>

                  {receiptLoading ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled
                      className="w-full rounded-xl border-gray-200 py-2.5 text-sm font-medium text-gray-500 gap-2"
                    >
                      <Download className="h-4 w-4" />
                      Checking Invoice...
                    </Button>
                  ) : receipt ? (
                    <Button
                      type="button"
                      variant="outline"
                      isLoading={downloading}
                      onClick={() => void handleDownloadReceipt()}
                      className="w-full rounded-xl border-gray-200 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 gap-2"
                    >
                      <Download className="h-4 w-4 text-gray-500" />
                      {downloading ? "Downloading..." : "Download Invoice"}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => void handleDownloadReceipt()}
                      className="w-full rounded-xl border-gray-200 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 gap-2"
                    >
                      <Download className="h-4 w-4 text-gray-500" />
                      Download Invoice
                    </Button>
                  )}

                  <div className="pt-2 text-center">
                    {canCancel(order.status) ? (
                      <button
                        type="button"
                        onClick={() => setPendingAction("cancel")}
                        className="text-xs font-medium text-gray-500 hover:text-rose-600 hover:underline"
                      >
                        Cancel Order or Need Help?
                      </button>
                    ) : canRequestRefund(order.status) ? (
                      <button
                        type="button"
                        onClick={() => setPendingAction("refund")}
                        className="text-xs font-medium text-gray-500 hover:text-blue-600 hover:underline"
                      >
                        Request Return / Refund or Need Help?
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => navigate("/contact")}
                        className="text-xs font-medium text-gray-500 hover:text-blue-600 hover:underline"
                      >
                        Cancel Order or Need Help?
                      </button>
                    )}
                  </div>

                  {receiptError && (
                    <p className="mt-2 text-center text-xs text-gray-500">
                      {receiptError}
                    </p>
                  )}
                  {error && (
                    <p className="mt-2 text-center text-xs text-rose-600">
                      {error}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      <AlertDialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open && !actionLoading) setPendingAction(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingAction === "cancel"
                ? "Cancel this order?"
                : "Request a return / refund?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingAction === "cancel"
                ? "This will cancel your order and release reserved items back to the store inventory."
                : "Our care team will review your refund request and follow up promptly."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={actionLoading}>Nevermind</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void handleConfirmAction()}
              disabled={actionLoading}
              className={
                pendingAction === "cancel"
                  ? "bg-rose-600 hover:bg-rose-700 text-white"
                  : "bg-blue-600 hover:bg-blue-700 text-white"
              }
            >
              {actionLoading ? "Processing..." : "Confirm"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
