import React, { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Check,
  CreditCard,
  Download,
  MapPin,
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
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Progress,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/modeza";
import { useOrders } from "../context/OrdersContext";
import { useRouter } from "../router/RouterContext";
import { OrderItemThumb } from "../components/orders/OrderItemThumb";
import { OrderProgress } from "../components/orders/OrderProgress";
import { api } from "../services/apiClient";
import { Order, OrderStatus, PaymentStatus } from "../types";
import { ReceiptDTO } from "../types/api";
import { formatPrice } from "../utils/currency";
import {
  formatOrderDate,
  mapServerOrder,
  totalQuantity,
} from "../utils/orderMapper";
import {
  canCancel,
  canMarkReceived,
  canRequestRefund,
  isActiveOrder,
  isTrackable,
  ORDER_STATUS_META,
} from "../utils/orderStatus";

interface CustomerOrderDetailPageProps {
  orderNumber?: string;
}

type OrderAction = "received" | "cancel" | "refund";

const paymentStatusLabels: Record<PaymentStatus, string> = {
  pending: "Pending",
  paid: "Paid",
  failed: "Failed",
  refunded: "Refunded",
};

function paymentMethodLabel(method?: string): string {
  switch ((method || "mpesa").toLowerCase()) {
    case "card":
      return "Card";
    case "cash_on_delivery":
      return "Pay on Delivery";
    case "pay_on_delivery":
      return "Pay on Delivery";
    case "mpesa":
    default:
      return "M-Pesa";
  }
}

function getStatusBadgeVariant(
  status: OrderStatus,
): "success" | "warning" | "destructive" | "default" | "secondary" {
  switch (status) {
    case "cancelled":
      return "destructive";
    case "pending":
      return "warning";
    case "shipped":
      return "default";
    case "processing":
      return "secondary";
    default:
      return "success";
  }
}

function StatusBadge({ status }: { status: OrderStatus }) {
  return (
    <Badge
      variant={getStatusBadgeVariant(status)}
      size="sm"
      className="gap-1.5"
    >
      <span className="sr-only">Order status: </span>
      {ORDER_STATUS_META[status].label}
    </Badge>
  );
}

function PaymentStatusBadge({ status }: { status: PaymentStatus }) {
  const variant =
    status === "paid"
      ? "success"
      : status === "failed"
        ? "destructive"
        : status === "refunded"
          ? "secondary"
          : "warning";

  return (
    <Badge variant={variant} size="sm">
      {paymentStatusLabels[status]}
    </Badge>
  );
}

function getProgressValue(order: Order): number {
  if (order.status === "cancelled") return 100;
  const rank = Math.max(0, ORDER_STATUS_META[order.status].rank);
  return Math.round((rank / 4) * 100);
}

export const CustomerOrderDetailPage: React.FC<
  CustomerOrderDetailPageProps
> = ({ orderNumber: propOrderNumber }) => {
  const { navigate } = useRouter();
  const { getOrder, receiveOrder, cancelOrder, requestOrderReturn } =
    useOrders();
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

  const completionTimestamp = useCallback(
    (status: "delivered" | "received" | "cancelled") => {
      if (!order) return "";
      const timelineTimestamp = order.timeline.find(
        (event) => event.status === status,
      )?.timestamp;
      return (
        timelineTimestamp || (status === "cancelled" ? order.updatedAt : "")
      );
    },
    [order],
  );

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

  const handleRetry = useCallback(() => {
    if (!propOrderNumber) return;
    setLoading(true);
    setError("");
    api
      .getOrder(propOrderNumber)
      .then((serverOrder) => {
        setOrder(mapServerOrder(serverOrder));
        setError("");
      })
      .catch(() => {
        setOrder(null);
        setError("No order could be found for this reference.");
      })
      .finally(() => setLoading(false));
  }, [propOrderNumber]);

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
    // The receipt is downloadable only after an admin confirms the order.
    // It stays available through every later fulfilment state.
    const receiptVisible =
      order && order.status !== "pending" && order.status !== "cancelled";
    if (!receiptVisible) {
      setReceipt(null);
      setReceiptError(
        order && order.status === "pending"
          ? "The official receipt will be available once an admin confirms your order."
          : "",
      );
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
        setReceiptError("The official receipt is not available yet.");
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
          setReceiptError(
            "The official receipt is not available yet. Please try again shortly.",
          );
          return;
        }
        if (
          receiptApiError.status === 403 &&
          receiptApiError.code === "RECEIPT_NOT_READY"
        ) {
          setReceiptError(
            "The official receipt will be available once an admin confirms your order.",
          );
          return;
        }
        setReceiptError(
          receiptApiError.message ||
            "The official receipt could not be checked.",
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
        <Card className="mx-auto max-w-xl border-[#E8E5DF] p-8 text-center shadow-sm sm:p-12">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F]">
            <X className="h-6 w-6" aria-hidden="true" />
          </div>
          <CardTitle className="mt-5 text-2xl">
            Missing order reference
          </CardTitle>
          <CardDescription className="mx-auto mt-3 max-w-sm text-sm leading-6">
            We could not identify the order you are looking for.
          </CardDescription>
          <Button
            type="button"
            variant="primary"
            size="md"
            onClick={() => navigate("/account/orders")}
            className="mt-7"
          >
            Back to orders
          </Button>
        </Card>
      </div>
    );
  }

  const showErrorPanel = !loading && !order;
  const progressValue = order ? getProgressValue(order) : 0;
  const deliveryTimestamp = order
    ? completionTimestamp("delivered") || completionTimestamp("received")
    : "";
  const cancellationTimestamp = order ? completionTimestamp("cancelled") : "";
  const actionIsCancellation = pendingAction === "cancel";
  const actionIsRefund = pendingAction === "refund";

  return (
    <main className="mx-auto w-full max-w-7xl px-4 pb-16 pt-5 sm:px-6 sm:pb-20 sm:pt-8 lg:px-8">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => navigate("/account/orders")}
        className="-ml-3 gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#63605A] hover:text-[#181716]"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Back to orders
      </Button>

      {loading && !order && (
        <Card
          className="mt-8 border-[#E8E5DF] p-8 text-center shadow-sm sm:p-12"
          aria-busy="true"
        >
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F]">
            <Truck className="h-6 w-6 animate-pulse" aria-hidden="true" />
          </div>
          <p
            className="mt-5 text-sm font-medium text-[#181716]"
            role="status"
            aria-live="polite"
          >
            Loading your order…
          </p>
          <Progress
            className="mx-auto mt-5 h-1.5 max-w-xs"
            aria-label="Loading order"
          />
        </Card>
      )}

      {showErrorPanel && (
        <Card
          className="mx-auto mt-10 max-w-xl border-[#E8E5DF] p-8 text-center shadow-sm sm:p-12"
          role="alert"
        >
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#FDF2F2] text-[#9E332B]">
            <X className="h-6 w-6" aria-hidden="true" />
          </div>
          <CardTitle className="mt-5 text-2xl">Something went wrong</CardTitle>
          <CardDescription className="mx-auto mt-3 max-w-sm text-sm leading-6">
            {error || "We could not load this order right now."}
          </CardDescription>
          <Button
            type="button"
            variant="primary"
            size="md"
            onClick={handleRetry}
            className="mt-7"
          >
            Try again
          </Button>
        </Card>
      )}

      {order && (
        <div className="mt-6 space-y-7" aria-busy={loading || receiptLoading}>
          {loading && (
            <p
              className="flex items-center gap-2 text-xs text-[#827E77]"
              role="status"
              aria-live="polite"
            >
              <span
                className="h-2 w-2 animate-pulse rounded-full bg-[#A2574F]"
                aria-hidden="true"
              />
              Refreshing the latest order status…
            </p>
          )}

          <header className="flex flex-col gap-5 border-b border-[#D8D3CB] pb-6 sm:flex-row sm:items-end sm:justify-between">
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-[#A2574F]">
                Order details
              </p>
              <h1 className="mt-2 break-all font-serif text-3xl font-normal leading-tight text-[#181716] sm:text-4xl">
                {order.orderNumber}
              </h1>
              <p className="mt-2 text-sm text-[#63605A]">
                Placed{" "}
                {formatOrderDate(order.createdAt, {
                  day: "numeric",
                  month: "long",
                  year: "numeric",
                })}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
              <div className="flex items-center gap-2 rounded-lg border border-[#E8E5DF] bg-white px-3 py-2">
                <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-[#827E77]">
                  Status
                </span>
                <StatusBadge status={order.status} />
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-[#E8E5DF] bg-white px-3 py-2">
                <CreditCard
                  className="h-3.5 w-3.5 text-[#A2574F]"
                  aria-hidden="true"
                />
                <span className="text-xs font-medium text-[#181716]">
                  {paymentMethodLabel(order.paymentMethod)}
                </span>
                <PaymentStatusBadge status={order.paymentStatus} />
              </div>
            </div>
          </header>

          <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1.6fr)_minmax(18rem,0.8fr)] lg:gap-12">
            <div className="min-w-0 space-y-7">
              {order.status === "cancelled" ? (
                <Card className="border-[#F8B4B4] bg-[#FDF2F2] p-5 shadow-none sm:p-6">
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-[#9E332B]">
                      <X className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div>
                      <p className="text-sm font-medium text-[#181716]">
                        This order was cancelled
                      </p>
                      {cancellationTimestamp && (
                        <p className="mt-1 text-xs text-[#63605A]">
                          Recorded on{" "}
                          {formatOrderDate(cancellationTimestamp, {
                            day: "numeric",
                            month: "long",
                            year: "numeric",
                          })}
                          .
                        </p>
                      )}
                      <p className="mt-2 text-xs leading-5 text-[#63605A]">
                        Reserved MODEZA stock has been returned to available
                        inventory.
                      </p>
                    </div>
                  </div>
                </Card>
              ) : order.status === "delivered" ||
                order.status === "received" ? (
                <Card className="border-[#C8D8CA] bg-[#F2F6F2] p-5 shadow-none sm:p-6">
                  <div className="flex items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-[#2E5A44] shadow-xs">
                      <Check className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <div>
                      <p className="text-sm font-medium text-[#181716]">
                        {order.status === "delivered"
                          ? "Delivered"
                          : "Order received"}
                        {deliveryTimestamp && (
                          <span>
                            {" "}
                            on{" "}
                            {formatOrderDate(deliveryTimestamp, {
                              day: "numeric",
                              month: "long",
                              year: "numeric",
                            })}
                          </span>
                        )}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-[#63605A]">
                        Thank you for shopping with the modeza.
                      </p>
                    </div>
                  </div>
                </Card>
              ) : isActiveOrder(order.status) ? (
                <Card className="border-[#E8E5DF] p-5 shadow-sm sm:p-6">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">
                        Order status
                      </p>
                      <h2 className="mt-1 text-sm font-semibold text-[#181716]">
                        Your journey so far
                      </h2>
                    </div>
                    {isTrackable(order.status) && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          navigate(
                            `/track?order=${encodeURIComponent(order.orderNumber)}`,
                          )
                        }
                        className="gap-1.5"
                      >
                        <Truck className="h-3.5 w-3.5" aria-hidden="true" />
                        Track order
                      </Button>
                    )}
                  </div>
                  <Progress
                    value={progressValue}
                    className="mt-5 h-2"
                    aria-label="Order lifecycle progress"
                    aria-valuetext={`${progressValue}% complete`}
                  />
                  <OrderProgress order={order} className="mt-6" />
                </Card>
              ) : null}

              {order.status === "shipped" && (
                <Card className="flex items-start gap-3.5 bg-[#FAF9F6] p-5 shadow-none sm:p-6">
                  <Truck
                    className="mt-0.5 h-5 w-5 shrink-0 text-[#181716]"
                    aria-hidden="true"
                  />
                  <div>
                    <p className="text-sm font-medium text-[#181716]">
                      Your order is on its way
                    </p>
                    <p className="mt-1 text-xs leading-5 text-[#63605A]">
                      Your pieces have been dispatched. You will receive SMS and
                      email updates as they travel to you.
                    </p>
                  </div>
                </Card>
              )}

              <Tabs defaultValue="items" className="w-full">
                <TabsList
                  className="h-11 w-full justify-start overflow-x-auto rounded-lg bg-[#F3F1ED] p-1"
                  aria-label="Order details"
                >
                  <TabsTrigger value="items">
                    Pieces ({totalQuantity(order)})
                  </TabsTrigger>
                  <TabsTrigger value="delivery">Delivery</TabsTrigger>
                </TabsList>
                <TabsContent value="items">
                  <Card
                    className="overflow-hidden p-0 shadow-sm"
                    aria-labelledby="order-items-heading"
                  >
                    <CardHeader className="border-b border-[#F3F1ED] p-5 sm:p-6">
                      <CardTitle id="order-items-heading" className="text-lg">
                        Reserved pieces
                      </CardTitle>
                      <CardDescription className="text-xs">
                        The items currently recorded on this order.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="p-0">
                      <ul className="divide-y divide-[#F3F1ED]">
                        {order.items.map((item) => (
                          <li
                            key={item.id}
                            className="flex flex-wrap items-center gap-4 p-4 sm:gap-5 sm:p-5"
                          >
                            <OrderItemThumb
                              item={item}
                              className="h-20 w-16 shrink-0 rounded-lg border border-[#E8E5DF] shadow-xs sm:h-24 sm:w-20"
                            />
                            <div className="min-w-[7.5rem] flex-1">
                              <h3 className="font-serif text-sm text-[#181716] sm:text-base">
                                {item.productName}
                              </h3>
                              <p className="mt-1 text-xs text-[#63605A]">
                                {item.variantDetails || "—"}
                              </p>
                              <p className="mt-1 text-xs text-[#827E77]">
                                Qty {item.quantity} ×{" "}
                                {formatPrice(item.unitPrice)}
                              </p>
                            </div>
                            <div className="shrink-0 font-serif text-sm text-[#181716] sm:text-base">
                              {formatPrice(item.subtotal)}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                </TabsContent>
                <TabsContent value="delivery">
                  <Card
                    className="p-5 shadow-sm sm:p-6"
                    aria-labelledby="order-delivery-heading"
                  >
                    <CardHeader className="p-0">
                      <div className="flex items-center gap-2">
                        <MapPin
                          className="h-4 w-4 text-[#A2574F]"
                          aria-hidden="true"
                        />
                        <CardTitle
                          id="order-delivery-heading"
                          className="text-lg"
                        >
                          Delivery address
                        </CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent className="p-0">
                      <address className="mt-5 text-sm not-italic leading-6 text-[#63605A]">
                        <p className="font-medium text-[#181716]">
                          {order.customer.firstName} {order.customer.lastName}
                        </p>
                        <p>
                          {order.customer.addressLine1}
                          {order.customer.addressLine2
                            ? `, ${order.customer.addressLine2}`
                            : ""}
                        </p>
                        <p>
                          {order.customer.city}
                          {order.customer.stateOrProvince
                            ? `, ${order.customer.stateOrProvince}`
                            : ""}
                          {order.customer.postalCode
                            ? ` ${order.customer.postalCode}`
                            : ""}
                        </p>
                        <p>{order.customer.country}</p>
                      </address>
                      <p className="mt-5 border-t border-[#F3F1ED] pt-4 text-xs text-[#827E77]">
                        Courier:{" "}
                        {order.shippingMethod === "express"
                          ? "Carbon-neutral priority air"
                          : "Standard land"}
                      </p>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </div>

            <aside
              className="space-y-5 lg:sticky lg:top-28"
              aria-label="Order totals and actions"
            >
              <Card
                className="p-0 shadow-sm"
                aria-labelledby="order-summary-heading"
              >
                <CardHeader className="border-b border-[#F3F1ED] p-5 sm:p-6">
                  <CardTitle id="order-summary-heading" className="text-lg">
                    Order summary
                  </CardTitle>
                </CardHeader>
                <CardContent className="p-5 pt-5 sm:p-6 sm:pt-6">
                  <dl className="space-y-3 text-xs text-[#63605A]">
                    <div className="flex items-center justify-between gap-4">
                      <dt>Subtotal</dt>
                      <dd className="font-medium text-[#181716]">
                        {formatPrice(order.subtotal)}
                      </dd>
                    </div>
                    {order.discount && (
                      <div className="flex items-center justify-between gap-4 text-[#2E5A44]">
                        <dt>Privilege ({order.discount.code})</dt>
                        <dd className="font-medium">
                          -{formatPrice(order.discount.amount)}
                        </dd>
                      </div>
                    )}
                    <div className="flex items-center justify-between gap-4">
                      <dt>Delivery</dt>
                      <dd className="font-medium text-[#181716]">
                        {order.shippingCost === 0
                          ? "Complimentary"
                          : formatPrice(order.shippingCost)}
                      </dd>
                    </div>
                    <div className="flex items-center justify-between gap-4">
                      <dt>VAT</dt>
                      <dd className="font-medium text-[#181716]">
                        {formatPrice(order.tax)}
                      </dd>
                    </div>
                    <div className="flex items-center justify-between gap-4 border-t border-[#F3F1ED] pt-3">
                      <dt className="text-sm font-medium text-[#181716]">
                        Total
                      </dt>
                      <dd className="font-serif text-xl text-[#181716]">
                        {formatPrice(order.total)}
                      </dd>
                    </div>
                  </dl>
                </CardContent>
              </Card>

              <Card
                className="p-0 shadow-sm"
                aria-labelledby="order-payment-heading"
              >
                <CardHeader className="border-b border-[#F3F1ED] p-5 sm:p-6">
                  <div className="flex items-center gap-2">
                    <CreditCard
                      className="h-4 w-4 text-[#A2574F]"
                      aria-hidden="true"
                    />
                    <CardTitle id="order-payment-heading" className="text-lg">
                      Payment
                    </CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="p-5 pt-5 sm:p-6 sm:pt-6">
                  <dl className="space-y-3 text-xs text-[#63605A]">
                    <div className="flex items-center justify-between gap-4">
                      <dt>Method</dt>
                      <dd className="font-medium capitalize text-[#181716]">
                        {paymentMethodLabel(order.paymentMethod)}
                      </dd>
                    </div>
                    <div className="flex items-center justify-between gap-4">
                      <dt>Status</dt>
                      <dd>
                        <PaymentStatusBadge status={order.paymentStatus} />
                      </dd>
                    </div>
                  </dl>
                </CardContent>
              </Card>

              <Card
                className="space-y-2.5 bg-[#FAF9F6] p-5 shadow-none hover:shadow-sm sm:p-6"
                aria-labelledby="order-actions-heading"
              >
                <CardHeader className="p-0">
                  <CardTitle id="order-actions-heading" className="text-lg">
                    Need to make a change?
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Available actions depend on this order's current status.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-2.5 p-0">
                  {isTrackable(order.status) && (
                    <Button
                      type="button"
                      variant="primary"
                      size="md"
                      onClick={() =>
                        navigate(
                          `/track?order=${encodeURIComponent(order.orderNumber)}`,
                        )
                      }
                      className="w-full gap-2"
                    >
                      <Truck className="h-4 w-4" aria-hidden="true" />
                      Track order
                    </Button>
                  )}
                  {canMarkReceived(order.status, order.paymentMethod) && (
                    <Button
                      type="button"
                      variant="secondary"
                      size="md"
                      onClick={() => setPendingAction("received")}
                      className="w-full"
                    >
                      Mark as received
                    </Button>
                  )}
                  {canCancel(order.status) && (
                    <Button
                      type="button"
                      variant="outline"
                      size="md"
                      onClick={() => setPendingAction("cancel")}
                      className="w-full border-[#F8B4B4] text-[#9E332B] hover:border-[#9E332B] hover:bg-[#FDF2F2] hover:text-[#9E332B]"
                    >
                      Cancel order
                    </Button>
                  )}
                  {canRequestRefund(order.status) &&
                    order.paymentStatus === "paid" && (
                      <Button
                        type="button"
                        variant="outline"
                        size="md"
                        onClick={() => setPendingAction("refund")}
                        className="w-full"
                      >
                        <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                        Request refund
                      </Button>
                    )}
                  {order.paymentStatus === "refunded" && (
                    <div className="flex items-center justify-center rounded-full border border-[#E8E5DF] bg-white px-3 py-2 text-xs uppercase tracking-wider text-[#827E77]">
                      Refunded
                    </div>
                  )}
                  {receiptLoading ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="md"
                      isLoading
                      disabled
                      className="w-full gap-2"
                    >
                      <Download className="h-3.5 w-3.5" aria-hidden="true" />
                      Checking receipt
                    </Button>
                  ) : receipt ? (
                    <Button
                      type="button"
                      variant="primary"
                      size="md"
                      isLoading={downloading}
                      onClick={() => void handleDownloadReceipt()}
                      className="w-full gap-2"
                    >
                      <Download className="h-3.5 w-3.5" aria-hidden="true" />
                      Download receipt (PDF)
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      size="md"
                      disabled
                      className="w-full gap-2"
                    >
                      <Download className="h-3.5 w-3.5" aria-hidden="true" />
                      Receipt unavailable
                    </Button>
                  )}
                </CardContent>
              </Card>

              {receiptError && (
                <div
                  role="alert"
                  className="rounded-2xl border border-[#F8B4B4] bg-[#FDF2F2] p-4 text-xs leading-5 text-[#9B1C1C]"
                >
                  {receiptError}
                </div>
              )}
              {error && (
                <div
                  role="alert"
                  className="rounded-2xl border border-[#F8B4B4] bg-[#FDF2F2] p-4 text-xs leading-5 text-[#9B1C1C]"
                >
                  {error}
                </div>
              )}
            </aside>
          </div>
        </div>
      )}

      <AlertDialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open && !actionLoading) setPendingAction(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {actionIsCancellation
                ? "Cancel this order?"
                : actionIsRefund
                  ? "Request a refund?"
                  : "Confirm order receipt"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {actionIsCancellation
                ? `Cancelling ${order?.orderNumber} will return the reserved MODEZA stock.`
                : actionIsRefund
                  ? `A staff member will review the refund request for ${order?.orderNumber}.`
                  : `Confirm that you have received ${order?.orderNumber}.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={actionLoading}>
              Keep order
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={actionLoading}
              aria-busy={actionLoading}
              className={
                actionIsCancellation
                  ? "bg-[#9E332B] hover:bg-[#8B2A24]"
                  : undefined
              }
              onClick={() => void handleConfirmAction()}
            >
              {actionLoading
                ? "Updating…"
                : actionIsCancellation
                  ? "Cancel order"
                  : actionIsRefund
                    ? "Submit request"
                    : "Confirm receipt"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
};
