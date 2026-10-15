import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowRight,
  Check,
  CheckCircle2,
  Clock3,
  Download,
  Eye,
  Mail,
  MapPin,
  PackageCheck,
  Truck,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Progress,
} from '../components/modeza';
import { useOrders } from '../context/OrdersContext';
import { useRouter } from '../router/RouterContext';
import { ProductImage } from '../components/ui/ProductImage';
import { api } from '../services/apiClient';
import { formatPrice } from '../utils/currency';
import { mapServerOrder } from '../utils/orderMapper';
import { ORDER_STATUS_META, PROGRESS_STEPS } from '../utils/orderStatus';
import { Order, OrderStatus, PaymentStatus } from '../types';
import { ReceiptDTO } from '../types/api';

export interface OrderSuccessPageProps {
  orderNumber?: string;
}

function StatusBadge({ status }: { status?: OrderStatus }) {
  if (!status) {
    return (
      <Badge variant="secondary" size="sm" className="gap-1.5">
        <PackageCheck className="h-3 w-3" aria-hidden="true" />
        Preparing in MODEZA
      </Badge>
    );
  }

  const variant = status === 'cancelled'
    ? 'destructive'
    : status === 'pending'
      ? 'warning'
      : status === 'shipped'
        ? 'default'
        : 'success';

  return (
    <Badge variant={variant} size="sm" className="gap-1.5">
      <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
      {ORDER_STATUS_META[status].label}
    </Badge>
  );
}

function PaymentStatusBadge({ status }: { status?: PaymentStatus }) {
  const label = status || 'pending';
  const variant = label === 'paid'
    ? 'success'
    : label === 'failed'
      ? 'destructive'
      : label === 'refunded'
        ? 'secondary'
        : 'warning';

  return <Badge variant={variant} size="sm">Payment {label}</Badge>;
}

function paymentMethodLabel(method?: string): string {
  switch ((method || 'mpesa').toLowerCase()) {
    case 'card':
      return 'Card';
    case 'cash_on_delivery':
      return 'Pay on Delivery';
    case 'pay_on_delivery':
      return 'Pay on Delivery';
    case 'mpesa':
    default:
      return 'M-Pesa';
  }
}

function getProgressValue(order: Order): number {
  if (order.status === 'cancelled') return 100;
  const rank = Math.max(0, ORDER_STATUS_META[order.status].rank);
  return Math.round((rank / 4) * 100);
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date unavailable';
  return date.toLocaleDateString('en-KE', { dateStyle: 'long' });
}

export const OrderSuccessPage: React.FC<OrderSuccessPageProps> = ({ orderNumber }) => {
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
  }, [order]);

  const resolvedOrder = order;
  const refCode = resolvedOrder ? resolvedOrder.orderNumber : (orderNumber || '');
  const progressValue = resolvedOrder ? getProgressValue(resolvedOrder) : 0;
  const dispatchCopy = resolvedOrder?.shippingMethod === 'express'
    ? '2 business days · Express Courier'
    : '3–5 business days · Standard Land';

  return (
    <div className="bg-[#FAF9F6] pb-16">
      <header className="relative isolate overflow-hidden bg-[#263A30] px-4 py-12 text-white sm:px-6 sm:py-16 lg:px-8">
        <div className="pointer-events-none absolute -right-24 -top-32 h-80 w-80 rounded-full border border-white/10 sm:h-[28rem] sm:w-[28rem]" aria-hidden="true" />
        <div className="pointer-events-none absolute -right-8 -top-16 h-64 w-64 rounded-full border border-white/10 sm:h-80 sm:w-80" aria-hidden="true" />
        <div className="relative mx-auto max-w-6xl">
          <div className="flex flex-col items-center text-center">
            <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-full border border-white/20 bg-white/10 text-[#DCE8DC]">
              <Check className="h-7 w-7 stroke-[1.5]" aria-hidden="true" />
            </div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[#C9D7C9]">Order placed successfully</p>
            <h1 className="mt-3 max-w-2xl font-serif text-4xl font-normal leading-tight tracking-tight sm:text-6xl">
              A little something lovely is on its way.
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-7 text-white/70 sm:text-base">
              Thank you for choosing MODEZA. Your order is confirmed, and we’ll keep you updated at every step.
            </p>
            <div className="mt-7 inline-flex max-w-full items-center gap-2 rounded-full border border-white/15 bg-white/10 px-4 py-2 text-xs text-white/90">
              <span className="text-white/60">Order reference</span>
              <span className="break-all font-mono font-medium">{refCode || 'Awaiting reference'}</span>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pt-8 sm:px-6 sm:pt-10 lg:px-8">
        {orderLoading && resolvedOrder && (
          <p className="mb-5 text-center text-xs text-[#827E77]" role="status" aria-live="polite">
            Refreshing the latest order status…
          </p>
        )}

        {orderLoading && !resolvedOrder ? (
          <Card className="mx-auto max-w-3xl p-6 text-center" role="status" aria-live="polite">
            <p className="text-sm font-medium text-[#181716]">Finding your order details…</p>
            <Progress className="mx-auto mt-5 h-1.5 max-w-xs" aria-label="Loading order details" />
          </Card>
        ) : resolvedOrder ? (
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(18rem,0.85fr)]">
            <Card className="overflow-hidden p-0 shadow-sm" aria-busy={receiptLoading}>
              <CardHeader className="border-b border-[#F3F1ED] bg-white p-5 sm:p-7">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">Your order</p>
                    <CardTitle className="mt-1 text-2xl">The details</CardTitle>
                    {orderNumber && (
                      <p className="mt-1 text-xs text-[#827E77]">Placed {formatDate(resolvedOrder.createdAt)}</p>
                    )}
                  </div>
                  <StatusBadge status={resolvedOrder.status} />
                </div>
              </CardHeader>
              <CardContent className="p-5 pt-5 sm:p-7 sm:pt-6">
                <section aria-labelledby="success-items-heading">
                  <div className="flex items-center justify-between gap-3">
                    <h2 id="success-items-heading" className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">
                      Your MODEZA pieces
                    </h2>
                    <span className="text-xs text-[#827E77]">
                      {resolvedOrder.items.reduce((sum, item) => sum + item.quantity, 0)} items
                    </span>
                  </div>
                  <ul className="mt-3 divide-y divide-[#F3F1ED]">
                    {resolvedOrder.items.map((item) => (
                      <li key={item.id} className="flex items-center justify-between gap-4 py-4">
                        <div className="flex min-w-0 items-center gap-4">
                          <ProductImage src={item.image} alt={item.productName} className="h-[4.5rem] w-16 shrink-0 rounded-xl bg-[#F4ECE9]" />
                          <div className="min-w-0">
                            <p className="font-serif text-base text-[#181716]">{item.productName}</p>
                            <p className="mt-1 text-xs leading-5 text-[#827E77]">{item.variantDetails || 'One of a kind'}</p>
                            <p className="mt-1 text-xs text-[#827E77]">Qty {item.quantity}</p>
                          </div>
                        </div>
                        <span className="shrink-0 text-sm font-medium text-[#181716]">{formatPrice(item.subtotal)}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-2 flex items-end justify-between border-t border-[#E8E5DF] pt-5">
                    <div>
                      <p className="text-sm font-medium text-[#181716]">Order total</p>
                      <p className="mt-1 text-xs text-[#827E77]">{paymentMethodLabel(resolvedOrder.paymentMethod)}</p>
                    </div>
                    <span className="font-serif text-2xl font-semibold text-[#181716]">{formatPrice(resolvedOrder.total)}</span>
                  </div>
                </section>

                <section className="mt-7 grid gap-4 border-t border-[#F3F1ED] pt-6 sm:grid-cols-2" aria-label="Payment and delivery details">
                  <div className="rounded-xl bg-[#FAF9F6] p-4">
                    <div className="flex items-center gap-2 text-[#A2574F]">
                      <Truck className="h-4 w-4" aria-hidden="true" />
                      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#827E77]">Delivery estimate</p>
                    </div>
                    <p className="mt-2 text-sm font-medium text-[#181716]">{dispatchCopy}</p>
                    <p className="mt-1 flex items-center gap-1 text-xs text-[#827E77]">
                      <MapPin className="h-3 w-3 shrink-0" aria-hidden="true" />
                      <span className="truncate">{resolvedOrder.customer.city}, {resolvedOrder.customer.country}</span>
                    </p>
                  </div>
                  <div className="rounded-xl bg-[#FAF9F6] p-4">
                    <div className="flex items-center gap-2 text-[#A2574F]">
                      <Mail className="h-4 w-4" aria-hidden="true" />
                      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#827E77]">We’ll keep you posted</p>
                    </div>
                    <p className="mt-2 break-words text-sm font-medium text-[#181716]">{resolvedOrder.customer.email}</p>
                    <p className="mt-1 text-xs leading-5 text-[#827E77]">Updates when your order is prepared and dispatched.</p>
                  </div>
                </section>
              </CardContent>
            </Card>

            <aside className="space-y-5">
              <Card className="p-5 shadow-sm sm:p-6">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#A2574F]">Good things take a little time</p>
                    <h2 className="mt-1 font-serif text-xl text-[#181716]">Your order journey</h2>
                  </div>
                  <Clock3 className="mt-1 h-5 w-5 shrink-0 text-[#A2574F]" aria-hidden="true" />
                </div>
                <div className="mt-5 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs text-[#827E77]">Current status</p>
                    <div className="mt-1"><StatusBadge status={resolvedOrder.status} /></div>
                  </div>
                  <span className="text-xs font-medium text-[#827E77]">{progressValue}%</span>
                </div>
                <Progress
                  value={progressValue}
                  className="mt-4 h-2"
                  aria-label="Order progress"
                  aria-valuetext={`${progressValue}% complete`}
                />
                <ol className="mt-4 space-y-3">
                  {PROGRESS_STEPS.map((step) => {
                    const reached = resolvedOrder.status !== 'cancelled' && ORDER_STATUS_META[resolvedOrder.status].rank >= ORDER_STATUS_META[step.status].rank;
                    return (
                      <li key={step.status} className="flex items-center gap-3">
                        <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${reached ? 'bg-[#E8EFEA] text-[#2E5A44]' : 'bg-[#F3F1ED] text-[#A29E96]'}`}>
                          {reached ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                        </span>
                        <span className={`text-xs ${reached ? 'font-medium text-[#181716]' : 'text-[#827E77]'}`}>{step.label}</span>
                      </li>
                    );
                  })}
                </ol>
              </Card>

              <Card className="p-5 shadow-sm sm:p-6">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">Payment</p>
                    <p className="mt-1 text-sm font-medium text-[#181716]">{paymentMethodLabel(resolvedOrder.paymentMethod)}</p>
                  </div>
                  <PaymentStatusBadge status={resolvedOrder.paymentStatus} />
                </div>
                <div className="mt-5 border-t border-[#F3F1ED] pt-4">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">Official receipt</p>
                  <p className="mt-1 text-xs leading-5 text-[#827E77]">
                    {receipt ? `Receipt ${receipt.receiptNumber} is ready to download.` : 'Your official receipt is available once payment is confirmed.'}
                  </p>
                  {receiptLoading ? (
                    <Button type="button" variant="outline" size="lg" isLoading disabled className="mt-4 w-full">
                      Checking receipt
                    </Button>
                  ) : receipt ? (
                    <Button
                      type="button"
                      variant="outline"
                      size="lg"
                      isLoading={downloading}
                      onClick={() => void handleDownloadReceipt()}
                      className="mt-4 w-full gap-2"
                    >
                      <Download className="h-4 w-4" aria-hidden="true" />
                      {downloading ? 'Downloading' : 'Download receipt'}
                    </Button>
                  ) : (
                    <Button type="button" variant="outline" size="lg" disabled className="mt-4 w-full gap-2">
                      <Download className="h-4 w-4" aria-hidden="true" />
                      Receipt unavailable
                    </Button>
                  )}
                </div>
              </Card>

              <section className="space-y-3" aria-label="Order actions">
                <Button
                  type="button"
                  variant="primary"
                  size="lg"
                  onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)}
                  className="w-full gap-2"
                >
                  <Eye className="h-4 w-4" aria-hidden="true" />
                  Track your order
                </Button>
                <Button type="button" variant="outline" size="lg" onClick={() => navigate('/shop')} className="w-full gap-2">
                  Continue exploring
                  <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              </section>
            </aside>
          </div>
        ) : (
          <Card className="mx-auto max-w-2xl p-6 text-center shadow-sm sm:p-8">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[#E8EFEA] text-[#2E5A44]">
              <PackageCheck className="h-6 w-6" aria-hidden="true" />
            </div>
            <CardTitle className="mt-4 text-2xl">Your order reference is safe with us.</CardTitle>
            <CardDescription className="mx-auto mt-2 max-w-md leading-6">
              We’re still connecting your order details. Use your reference to check its status, or continue exploring the collection.
            </CardDescription>
            <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
              <Button type="button" variant="primary" onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)} className="gap-2">
                <Eye className="h-4 w-4" aria-hidden="true" />
                Track your order
              </Button>
              <Button type="button" variant="outline" onClick={() => navigate('/shop')} className="gap-2">
                Continue exploring
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </Card>
        )}

        {receiptError && (
          <p role="alert" className="mx-auto mt-5 max-w-2xl text-center text-xs leading-5 text-[#9B1C1C]">{receiptError}</p>
        )}
      </main>
    </div>
  );
};
