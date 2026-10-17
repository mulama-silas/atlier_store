import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CreditCard,
  Download,
  Eye,
  MapPin,
  Package,
} from 'lucide-react';
import { Button } from '../components/modeza';
import { useOrders } from '../context/OrdersContext';
import { useRouter } from '../router/RouterContext';
import { OrderItemRows } from '../components/orders/OrderItemRows';
import { api } from '../services/apiClient';
import { formatPrice } from '../utils/currency';
import { mapServerOrder } from '../utils/orderMapper';
import { Order, OrderStatus } from '../types';
import { ReceiptDTO } from '../types/api';

export interface OrderSuccessPageProps {
  orderNumber?: string;
}

const TIMELINE_STEPS = [
  { id: 'placed', label: 'Order Placed', rank: 1 },
  { id: 'processing', label: 'Processing', rank: 2 },
  { id: 'shipped', label: 'Shipped', rank: 3 },
  { id: 'delivery', label: 'Out for Delivery', rank: 4 },
];

function getTimelineRank(status: OrderStatus): number {
  switch (status) {
    case 'pending':
    case 'confirmed':
      return 1;
    case 'processing':
      return 2;
    case 'shipped':
      return 3;
    case 'delivered':
      return 4;
    case 'cancelled':
      return 0;
    default:
      return 1;
  }
}

function getPaymentMethodDisplay(method?: string) {
  const m = (method || 'card').toLowerCase();
  if (m === 'card') {
    return {
      type: 'card',
      label: 'Card payment',
      badge: 'CARD',
    };
  }
  if (m === 'mpesa') {
    return {
      type: 'mpesa',
      label: 'M-Pesa payment',
      badge: 'M-PESA',
    };
  }
  return {
    type: 'cash',
    label: 'Pay on Delivery',
    badge: 'COD',
  };
}

export const OrderSuccessPage: React.FC<OrderSuccessPageProps> = ({ orderNumber }) => {
  const simulatedPayment = new URLSearchParams(window.location.search).get('simulation') === '1';
  const { navigate } = useRouter();
  const { getOrder, orders } = useOrders();
  const [order, setOrder] = useState<Order | null>(() => {
    if (orderNumber) return getOrder(orderNumber) || null;
    return orders[0] || null;
  });
  const [receipt, setReceipt] = useState<ReceiptDTO | null>(null);
  const [receiptLoading, setReceiptLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [receiptError, setReceiptError] = useState('');
  const [orderLoading, setOrderLoading] = useState(Boolean(orderNumber));

  useEffect(() => {
    if (!orderNumber) {
      setOrderLoading(false);
      return;
    }

    let cancelled = false;
    const cachedOrder = getOrder(orderNumber);
    if (cachedOrder) setOrder(cachedOrder);
    setOrderLoading(true);

    api
      .getOrder(orderNumber)
      .then((serverOrder) => {
        if (!cancelled) setOrder(mapServerOrder(serverOrder));
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setOrderLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [orderNumber, getOrder]);

  const handleDownloadReceipt = useCallback(async () => {
    if (!receipt) return;
    setDownloading(true);
    setReceiptError('');
    try {
      const blob = await api.downloadReceipt(receipt.receiptNumber);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${receipt.receiptNumber}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setReceiptError(err instanceof Error ? err.message : 'The receipt could not be downloaded.');
    } finally {
      setDownloading(false);
    }
  }, [receipt]);

  useEffect(() => {
    if (simulatedPayment) {
      setReceipt(null);
      setReceiptError('');
      setReceiptLoading(false);
      return;
    }
    if (!order || order.paymentStatus !== 'paid') {
      setReceipt(null);
      setReceiptError('');
      setReceiptLoading(false);
      return;
    }

    let cancelled = false;
    setReceipt(null);
    setReceiptError('');
    setReceiptLoading(true);
    api
      .getOrderReceipt(order.orderNumber)
      .then((data) => {
        if (cancelled) return;
        if (data.status === 'generated') {
          setReceipt(data);
          return;
        }
        setReceiptError('The official receipt is not available yet.');
      })
      .catch((err) => {
        if (cancelled) return;
        const error = err as Error & { code?: string; status?: number };
        if (error.status === 404 && error.code === 'RECEIPT_NOT_FOUND') {
          setReceiptError('The official receipt is not available yet.');
          return;
        }
        setReceiptError(error.message || 'The official receipt could not be checked.');
      })
      .finally(() => {
        if (!cancelled) setReceiptLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [order, simulatedPayment]);

  const resolvedOrder = order;
  const refCode = resolvedOrder ? resolvedOrder.orderNumber : (orderNumber || '');
  const customerName = resolvedOrder?.customer?.firstName || 'there';
  const currentRank = resolvedOrder ? getTimelineRank(resolvedOrder.status) : 1;
  const paymentInfo = getPaymentMethodDisplay(resolvedOrder?.paymentMethod);
  const orderStatusLabel = resolvedOrder?.status === 'shipped'
    ? 'In transit'
    : resolvedOrder?.status
      ? `${resolvedOrder.status.charAt(0).toUpperCase()}${resolvedOrder.status.slice(1)}`
      : '';

  return (
    <div className="min-h-screen bg-[#FAF9F6] text-[#181716] antialiased">
      {/* Top Mobile Bar */}
      <div className="flex items-center justify-between border-b border-[#F3F1ED] bg-white px-4 py-3 sm:hidden">
        <button
          type="button"
          onClick={() => navigate('/shop')}
          className="flex h-9 w-9 items-center justify-center rounded-full text-[#3C3934] hover:bg-[#F3F1ED]"
          aria-label="Back to store"
        >
          <ArrowLeft className="h-5 w-5" />
        </button>
        <span className="text-sm font-semibold text-[#181716]">Order Status</span>
        <div className="w-9" />
      </div>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-12 lg:px-8">
        {/* Main Heading */}
        <div className="mb-6 flex min-w-0 items-start gap-2.5 sm:mb-8 sm:items-center sm:gap-3">
          <span className="mt-0.5 shrink-0 text-2xl sm:mt-0 sm:text-3xl" role="img" aria-label="Celebration">🎉</span>
          <h1 className="min-w-0 flex-1 break-words text-xl font-bold leading-tight tracking-tight text-[#181716] sm:text-3xl md:text-4xl">
            Thank you for your order, {customerName}!
          </h1>
        </div>

        {simulatedPayment && (
          <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-xs text-amber-800">
            Demo checkout simulation: No live payment was charged.
          </div>
        )}

        {resolvedOrder ? (
          <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-12 lg:gap-8">
            {/* Left Column: Confirmation + Timeline + Address + Actions */}
            <div className="space-y-6 lg:col-span-7">
              <div className="overflow-hidden rounded-2xl border border-[#E8E5DF] bg-white p-5 shadow-[0_2px_14px_rgba(0,0,0,0.04)] sm:p-7">
                {/* Badge + Header Section */}
                <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center sm:gap-6">
                  {/* Scalloped Green Celebration Badge with Checkmark & Confetti */}
                  <div className="relative flex h-20 w-20 shrink-0 items-center justify-center sm:h-24 sm:w-24">
                    {/* Festive SVG Confetti Sprinkles */}
                    <svg
                      className="absolute inset-0 h-full w-full pointer-events-none"
                      viewBox="0 0 100 100"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                    >
                      <circle cx="16" cy="24" r="2.5" fill="#EF4444" />
                      <circle cx="84" cy="22" r="2.5" fill="#3B82F6" />
                      <circle cx="18" cy="74" r="2.5" fill="#F59E0B" />
                      <circle cx="82" cy="78" r="2.5" fill="#10B981" />
                      
                      <rect x="28" y="12" width="2" height="5" rx="1" fill="#6366F1" transform="rotate(25 28 12)" />
                      <rect x="70" y="14" width="2" height="6" rx="1" fill="#EC4899" transform="rotate(-30 70 14)" />
                      <rect x="10" y="48" width="5" height="2" rx="1" fill="#10B981" transform="rotate(15 10 48)" />
                      <rect x="86" y="44" width="6" height="2" rx="1" fill="#F59E0B" transform="rotate(-20 86 44)" />
                      <rect x="26" y="84" width="2" height="5" rx="1" fill="#3B82F6" transform="rotate(-40 26 84)" />
                      <rect x="74" y="86" width="2" height="5" rx="1" fill="#8B5CF6" transform="rotate(35 74 86)" />
                    </svg>

                    {/* Scalloped Stamp Badge */}
                    <div className="relative flex h-14 w-14 items-center justify-center rounded-full bg-[#2E5A44] text-white shadow-md shadow-emerald-500/20 sm:h-16 sm:w-16">
                      <svg
                        className="h-full w-full fill-current text-emerald-500"
                        viewBox="0 0 24 24"
                      >
                        <path d="M12 2l1.6 2.3 2.8-.4.7 2.7 2.6.9-.3 2.8 2.2 1.8-1.3 2.5 1.5 2.4-2.2 1.8.3 2.8-2.6.9-.7 2.7-2.8-.4L12 22l-1.6-2.3-2.8.4-.7-2.7-2.6-.9.3-2.8-2.2-1.8 1.3-2.5-1.5-2.4 2.2-1.8-.3-2.8 2.6-.9.7-2.7 2.8.4L12 2z" />
                      </svg>
                      <Check className="absolute h-7 w-7 stroke-[3.5] text-white sm:h-8 sm:w-8" />
                    </div>
                  </div>

                  {/* Order Confirmation Details */}
                  <div className="w-full min-w-0 text-center sm:flex-1 sm:text-left">
                    <h2 className="text-lg font-bold text-[#181716] sm:text-xl">
                      Order Placed Successfully!
                    </h2>
                    <p className="mt-1 text-xs text-[#827E77] sm:text-sm">
                      Your order has been received and we are getting it ready to ship.
                    </p>
                    <div className="mt-2.5 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-[#3C3934] sm:justify-start sm:text-sm">
                      <span className="break-all">Order ID: <strong className="font-semibold text-[#181716]">#{refCode}</strong></span>
                      <span className="hidden text-[#D8D3CB] sm:inline">&bull;</span>
                      <span className="break-words">Delivery estimate: <strong className="font-semibold text-[#181716]">To be confirmed as your order is prepared</strong></span>
                    </div>
                  </div>
                </div>

                {/* Stepper Progress Bar */}
                <div className="mt-8 border-t border-[#F3F1ED] pt-7">
                    <div className="relative mx-auto w-full max-w-lg">
                    {/* Connector Lines */}
                    <div className="absolute top-3 left-4 right-4 -z-0 h-0.5 bg-[#E8E5DF]">
                      <div
                        className="h-full bg-[#2E5A44] transition-all duration-300"
                        style={{
                          width: `${Math.min(100, Math.max(0, ((currentRank - 1) / (TIMELINE_STEPS.length - 1)) * 100))}%`,
                        }}
                      />
                    </div>

                    {/* Step Nodes */}
                    <div className="relative z-10 flex justify-between">
                      {TIMELINE_STEPS.map((step) => {
                        const isDone = currentRank > step.rank;
                        const isCurrent = currentRank === step.rank;
                        const isReached = isDone || isCurrent;

                        return (
                          <div key={step.id} className="flex w-1/4 min-w-0 flex-col items-center">
                            <div
                              className={`flex h-6 w-6 items-center justify-center rounded-full text-xs transition-colors duration-200 ${
                                isReached
                                  ? 'bg-[#2E5A44] text-white shadow-sm'
                                  : 'border-2 border-[#E8E5DF] bg-white text-transparent'
                              }`}
                            >
                              {isReached ? <Check className="h-3.5 w-3.5 stroke-[3]" /> : null}
                            </div>
                            <span
                              className={`mt-2 max-w-full break-words px-0.5 text-center text-[10px] font-medium leading-tight sm:text-xs ${
                                isReached ? 'font-semibold text-[#181716]' : 'text-[#A29E96]'
                              }`}
                            >
                              {step.label}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* Shipping To + Mini Map Card */}
                <div className="mt-7 overflow-hidden rounded-xl border border-[#F3F1ED] bg-[#F8FAFC]">
                  <div className="grid grid-cols-1 sm:grid-cols-2">
                    {/* Address details */}
                    <div className="min-w-0 p-4 sm:p-5">
                      <p className="text-[11px] font-semibold tracking-wider text-[#A29E96] uppercase">
                        Shipping to:
                      </p>
                      <p className="mt-1 text-sm font-bold text-[#181716]">
                        {resolvedOrder.customer.firstName} {resolvedOrder.customer.lastName}
                      </p>
                      <p className="mt-1 break-words text-xs leading-relaxed text-[#63605A]">
                        {resolvedOrder.customer.addressLine1}
                        {resolvedOrder.customer.addressLine2 ? `, ${resolvedOrder.customer.addressLine2}` : ''}
                      </p>
                      <p className="text-xs text-[#827E77]">
                        {[resolvedOrder.customer.city, resolvedOrder.customer.stateOrProvince, resolvedOrder.customer.postalCode]
                          .filter(Boolean)
                          .join(', ')}
                      </p>
                    </div>

                    {/* Stylized Illustrated Mini Map */}
                    <div className="relative h-28 w-full bg-[#EBF3ED] sm:h-auto overflow-hidden border-t sm:border-t-0 sm:border-l border-[#F3F1ED]">
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

                      {/* Map Pin */}
                      <div className="absolute inset-0 flex items-center justify-center">
                        <div className="relative flex flex-col items-center">
                          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#A2574F] text-white shadow-md">
                            <div className="h-2.5 w-2.5 rounded-full bg-white" />
                          </div>
                          <div className="-mt-1 h-2 w-2 rotate-45 bg-[#A2574F]" />
                          <div className="mt-0.5 h-1.5 w-4 rounded-full bg-black/15 blur-[1px]" />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Action Buttons Row */}
                <div className="mt-7 flex flex-col gap-3 sm:flex-row sm:items-center">
                  <Button
                    type="button"
                    onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)}
                    className="w-full flex-1 rounded-xl bg-[#A2574F] py-2.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#83443D] active:scale-[0.99]"
                  >
                    Track Your Order
                  </Button>

                  {receiptLoading ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled
                      className="w-full flex-1 rounded-xl border-[#E8E5DF] py-2.5 text-sm font-medium text-[#827E77]"
                    >
                      Checking Receipt...
                    </Button>
                  ) : receipt ? (
                    <Button
                      type="button"
                      variant="outline"
                      isLoading={downloading}
                      onClick={() => void handleDownloadReceipt()}
                      className="w-full flex-1 gap-2 rounded-xl border-[#E8E5DF] py-2.5 text-sm font-medium text-[#3C3934] hover:bg-[#FAF9F6] hover:text-[#181716]"
                    >
                      <Download className="h-4 w-4 text-[#827E77]" />
                      {downloading ? 'Downloading...' : 'Download Receipt'}
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="outline"
                      disabled
                      className="w-full flex-1 gap-2 rounded-xl border-[#E8E5DF] py-2.5 text-sm font-medium text-[#A29E96]"
                    >
                      <Download className="h-4 w-4 text-[#A29E96]" />
                      Download Receipt
                    </Button>
                  )}

                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => navigate('/shop')}
                    className="w-full flex-1 rounded-xl border-[#E8E5DF] py-2.5 text-sm font-medium text-[#3C3934] hover:bg-[#FAF9F6] hover:text-[#181716]"
                  >
                    Continue Shopping
                  </Button>
                </div>

                {receiptError && (
                  <p role="alert" className="mt-3 text-center text-xs text-red-600">
                    {receiptError}
                  </p>
                )}
              </div>
            </div>

            {/* Right Column: Order Summary Card */}
            <div className="lg:col-span-5">
              <div className="overflow-hidden rounded-2xl border border-[#E8E5DF] bg-white p-5 shadow-[0_2px_14px_rgba(0,0,0,0.04)] sm:p-7">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-base font-bold text-[#181716] sm:text-lg">
                    Order Items ({resolvedOrder.items.length})
                  </h2>
                  <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold ${resolvedOrder.status === 'delivered' || resolvedOrder.status === 'received' ? 'border-[#C5D9CB] bg-[#F2F8F4] text-[#2E5A44]' : resolvedOrder.status === 'cancelled' ? 'border-[#F8B4B4] bg-[#FDF2F2] text-[#9E332B]' : 'border-[#D8B1A5] bg-[#F4ECE9] text-[#83443D]'}`}>
                    {orderStatusLabel}
                  </span>
                </div>

                {/* Items List */}
                <div className="mt-4">
                  <OrderItemRows order={resolvedOrder} showTrackAction={false} />
                </div>

                {/* Pricing Breakdown */}
                <div className="mt-4 space-y-2 border-t border-[#F3F1ED] pt-4 text-xs sm:text-sm text-[#63605A]">
                  <div className="flex justify-between gap-3">
                    <span>Subtotal</span>
                    <span className="font-medium text-[#181716]">{formatPrice(resolvedOrder.subtotal)}</span>
                  </div>
                  {resolvedOrder.discount && resolvedOrder.discount.amount > 0 && (
                  <div className="flex justify-between gap-3 text-[#2E5A44]">
                      <span>Discount</span>
                      <span>-{formatPrice(resolvedOrder.discount.amount)}</span>
                    </div>
                  )}
                  <div className="flex justify-between gap-3">
                    <span>Shipping</span>
                    <span className="font-medium text-[#181716]">
                      {resolvedOrder.shippingCost > 0 ? formatPrice(resolvedOrder.shippingCost) : 'Free'}
                    </span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span>Tax</span>
                    <span className="font-medium text-[#181716]">
                      {formatPrice(resolvedOrder.tax)}
                    </span>
                  </div>

                  {/* Total Row */}
                  <div className="flex items-baseline justify-between gap-3 border-t border-[#F3F1ED] pt-3.5">
                    <span className="text-sm font-bold text-[#181716] sm:text-base">Total:</span>
                    <span className="text-lg font-bold text-[#181716] sm:text-xl">
                      {formatPrice(resolvedOrder.total)}
                    </span>
                  </div>

                  {/* Payment Method Badge */}
                  <div className="flex min-w-0 flex-wrap items-center gap-2 pt-2 text-xs text-[#827E77]">
                    <span className="inline-flex items-center justify-center rounded border border-[#E8E5DF] bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] font-bold text-[#83443D]">
                      {paymentInfo.badge}
                    </span>
                    <span>{paymentInfo.label}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Empty or Loading State */
          <div className="mx-auto max-w-lg rounded-2xl border border-[#E8E5DF] bg-white p-8 text-center shadow-sm">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#F2F8F4] text-[#2E5A44]">
              <Package className="h-7 w-7" />
            </div>
            <h2 className="mt-4 text-xl font-bold text-[#181716]">Your order is safe with us</h2>
            <p className="mt-2 text-xs text-[#827E77] leading-relaxed">
              We're loading your order details. Keep your reference number handy to track the delivery progress.
            </p>
            {refCode && (
              <p className="mt-3 font-mono text-sm font-semibold text-[#292622]">
                #{refCode}
              </p>
            )}
            <div className="mt-6 flex flex-col gap-2.5 sm:flex-row sm:justify-center">
              <Button
                type="button"
                onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)}
                className="rounded-xl bg-[#A2574F] py-2.5 text-sm font-semibold text-white hover:bg-[#83443D]"
              >
                Track Your Order
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate('/shop')}
                className="rounded-xl border-[#E8E5DF] py-2.5 text-sm font-medium text-[#3C3934] hover:bg-[#FAF9F6]"
              >
                Continue Shopping
              </Button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};
