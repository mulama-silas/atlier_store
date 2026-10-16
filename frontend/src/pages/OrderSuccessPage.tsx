import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowRight,
  BadgeCheck,
  Check,
  CheckCircle2,
  Download,
  Eye,
  Heart,
  Mail,
  MapPin,
  PackageCheck,
  Truck,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  CardTitle,
  Progress,
} from '../components/modeza';
import { useOrders } from '../context/OrdersContext';
import { useRouter } from '../router/RouterContext';
import { ProductImage } from '../components/ui/ProductImage';
import { api } from '../services/apiClient';
import { formatPrice } from '../utils/currency';
import { formatShortOrderDate, getOrderStatusTimestamp, mapServerOrder } from '../utils/orderMapper';
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
  const progressValue = resolvedOrder ? getProgressValue(resolvedOrder) : 0;
  return (
    <div className="min-h-screen bg-[#F5F2EC] pb-16">
      <header className="relative isolate overflow-hidden bg-[#263A30] text-white">
        <div className="pointer-events-none absolute -right-24 -top-40 h-[30rem] w-[30rem] rounded-full border border-white/10" aria-hidden="true" />
        <div className="pointer-events-none absolute -right-8 -top-24 h-[22rem] w-[22rem] rounded-full border border-white/10" aria-hidden="true" />
        <div className="relative mx-auto max-w-6xl px-4 pb-12 pt-10 sm:px-6 sm:pb-16 sm:pt-14 lg:px-8">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.24em] text-[#C9D7C9]">
            <span className="h-px w-8 bg-[#C9D7C9]/70" /> MODEZA · Order care
          </div>
          <div className="mt-10 grid items-end gap-8 md:grid-cols-[1fr_auto]">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-[#D9E6D9]/25 bg-white/10 px-3 py-1.5 text-xs text-[#F0F4EF]">
                <BadgeCheck className="h-4 w-4 text-[#CFE1D1]" aria-hidden="true" />
                {simulatedPayment ? 'Demo order created' : 'Your order is confirmed'}
              </div>
              <h1 className="mt-5 font-serif text-4xl font-normal leading-[1.08] tracking-tight sm:text-6xl lg:text-7xl">
                A beautiful choice.<br /><span className="text-[#D7C6A3]">Well on its way.</span>
              </h1>
              <p className="mt-5 max-w-xl text-sm leading-7 text-white/70 sm:text-base">
                Thank you for making MODEZA part of your story. We’ve saved your order and will share each update as it moves toward you.
              </p>
              {simulatedPayment && (
                <p className="mt-5 max-w-xl border-l-2 border-[#D7C6A3] bg-white/5 px-4 py-3 text-xs leading-5 text-[#F4EBD9]" role="status">
                  Demo checkout: no M-PESA request was sent and no payment was collected.
                </p>
              )}
            </div>
            <div className="w-full border-t border-white/15 pt-5 md:w-56 md:border-l md:border-t-0 md:pb-1 md:pl-6 md:pt-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-white/55">Order reference</p>
              <p className="mt-2 break-all font-mono text-sm font-medium text-white">{refCode || 'Awaiting reference'}</p>
              {resolvedOrder && <p className="mt-2 text-xs text-white/55">Placed {formatDate(resolvedOrder.createdAt)}</p>}
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pt-7 sm:px-6 sm:pt-9 lg:px-8">
        {orderLoading && resolvedOrder && (
          <p className="mb-5 text-xs text-[#827E77]" role="status" aria-live="polite">Refreshing your order details…</p>
        )}

        {orderLoading && !resolvedOrder ? (
          <Card className="mx-auto max-w-3xl p-8 text-center" role="status" aria-live="polite">
            <p className="font-serif text-xl text-[#181716]">Gathering your order details</p>
            <Progress className="mx-auto mt-5 h-1.5 max-w-xs" aria-label="Loading order details" />
          </Card>
        ) : resolvedOrder ? (
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(18rem,0.78fr)]">
            <div className="space-y-5">
              <Card className="overflow-hidden border-[#E7E1D6] bg-[#FBFAF7] p-5 shadow-[0_12px_40px_-28px_rgba(38,58,48,0.3)] sm:p-7">
                <div className="flex flex-wrap items-end justify-between gap-4">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">The next steps</p>
                    <h2 className="mt-1 font-serif text-2xl text-[#181716]">Your order journey</h2>
                  </div>
                  <div className="text-right">
                    <StatusBadge status={resolvedOrder.status} />
                    <p className="mt-2 text-[11px] text-[#827E77]">{progressValue}% complete</p>
                  </div>
                </div>
                <Progress value={progressValue} className="mt-5 h-1.5 bg-[#EAE6DE]" aria-label="Order progress" aria-valuetext={`${progressValue}% complete`} />
                <ol className="mt-6 grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4">
                  {PROGRESS_STEPS.map((step, index) => {
                    const reached = resolvedOrder.status !== 'cancelled' && ORDER_STATUS_META[resolvedOrder.status].rank >= ORDER_STATUS_META[step.status].rank;
                    return (
                      <li key={step.status} className="flex items-start gap-2.5">
                        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs ${reached ? 'bg-[#263A30] text-white' : 'border border-[#DED8CD] bg-white text-[#A29E96]'}`}>
                          {reached ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : index + 1}
                        </span>
                        <span className={`pt-1 text-xs leading-4 ${reached ? 'font-medium text-[#181716]' : 'text-[#827E77]'}`}>{step.label}</span>
                      </li>
                    );
                  })}
                </ol>
              </Card>

              <Card className="border-[#E7E1D6] bg-white p-5 shadow-sm sm:p-7">
                <div className="flex items-end justify-between gap-4 border-b border-[#EEEAE3] pb-4">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">Chosen for you</p>
                    <h2 className="mt-1 font-serif text-2xl text-[#181716]">Your MODEZA pieces</h2>
                  </div>
                  <span className="text-xs text-[#827E77]">
                    {resolvedOrder.items.reduce((sum, item) => sum + item.quantity, 0)} {resolvedOrder.items.reduce((sum, item) => sum + item.quantity, 0) === 1 ? 'piece' : 'pieces'}
                  </span>
                </div>
                <ul className="divide-y divide-[#EEEAE3]">
                  {resolvedOrder.items.map((item) => (
                    <li key={item.id} className="flex items-center gap-4 py-4 sm:gap-5 sm:py-5">
                      <ProductImage src={item.image} alt={item.productName} className="h-24 w-24 shrink-0 rounded-md bg-[#F4ECE9] sm:h-28 sm:w-28" />
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-2 font-serif text-lg leading-snug text-[#181716] sm:text-xl">{item.productName}</p>
                        <p className="mt-1 text-sm text-[#63605A]">Order {resolvedOrder.orderNumber}</p>
                        <p className="mt-1 text-xs text-[#827E77]">{item.variantDetails || 'One of a kind'} · Qty {item.quantity}</p>
                        <div className="mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                          <StatusBadge status={resolvedOrder.status} />
                          <span className="text-sm font-semibold text-[#181716]">On {formatShortOrderDate(getOrderStatusTimestamp(resolvedOrder)) || 'date pending'}</span>
                        </div>
                      </div>
                      <span className="shrink-0 self-start pt-1 text-sm font-medium text-[#181716]">{formatPrice(item.subtotal)}</span>
                    </li>
                  ))}
                </ul>
              </Card>

              <section className="grid gap-4 sm:grid-cols-2" aria-label="Delivery details">
                <Card className="border-[#E7E1D6] bg-[#ECEFE9] p-5 shadow-none sm:p-6">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-[#355641]"><Truck className="h-4 w-4" aria-hidden="true" /></div>
                  <p className="mt-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#6B766D]">Delivery estimate</p>
                  <p className="mt-1 font-serif text-xl text-[#263A30]">{resolvedOrder.shippingMethod === 'express' ? '2 business days' : '3–5 business days'}</p>
                  <p className="mt-2 flex items-center gap-1.5 text-xs text-[#636B64]"><MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />{resolvedOrder.customer.city}, {resolvedOrder.customer.country}</p>
                  <p className="mt-1 text-[11px] text-[#777E77]">{resolvedOrder.shippingMethod === 'express' ? 'Express courier' : 'Standard delivery'}</p>
                </Card>
                <Card className="border-[#E7E1D6] bg-white p-5 shadow-none sm:p-6">
                  <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#F7F1E7] text-[#A2574F]"><Mail className="h-4 w-4" aria-hidden="true" /></div>
                  <p className="mt-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">Order updates</p>
                  <p className="mt-1 break-words text-sm font-medium text-[#181716]">{resolvedOrder.customer.email}</p>
                  <p className="mt-2 text-xs leading-5 text-[#827E77]">We’ll let you know when your order is prepared and on its way.</p>
                </Card>
              </section>
            </div>

            <aside className="space-y-5 lg:sticky lg:top-6">
              <Card className="overflow-hidden border-[#263A30] bg-[#263A30] p-0 text-white shadow-lg">
                <div className="p-5 sm:p-6">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#C7D3C8]">Order summary</p>
                  <div className="mt-5 flex items-center justify-between gap-3 border-b border-white/15 pb-4 text-xs text-white/65">
                    <span>Items</span><span>{resolvedOrder.items.reduce((sum, item) => sum + item.quantity, 0)} pieces</span>
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-3 border-b border-white/15 pb-4 text-xs text-white/65">
                    <span>Payment method</span><span className="text-right text-white">{paymentMethodLabel(resolvedOrder.paymentMethod)}</span>
                  </div>
                  <div className="mt-5 flex items-end justify-between gap-3">
                    <span className="text-sm text-white/75">Total</span>
                    <span className="font-serif text-3xl text-[#E4D6B8]">{formatPrice(resolvedOrder.total)}</span>
                  </div>
                  <div className="mt-4"><PaymentStatusBadge status={resolvedOrder.paymentStatus} /></div>
                </div>
                <div className="border-t border-white/15 bg-white/5 px-5 py-4 sm:px-6">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#C7D3C8]">Official receipt</p>
                  <p className="mt-1 text-xs leading-5 text-white/65">
                    {simulatedPayment
                      ? 'A receipt will be available after a real payment is collected.'
                      : receipt ? `Receipt ${receipt.receiptNumber} is ready to download.` : 'Your official receipt is available once payment is confirmed.'}
                  </p>
                  {receiptLoading ? (
                    <Button type="button" variant="outline" size="lg" isLoading disabled className="mt-4 w-full">Checking receipt</Button>
                  ) : receipt ? (
                    <Button type="button" variant="outline" size="lg" isLoading={downloading} onClick={() => void handleDownloadReceipt()} className="mt-4 w-full gap-2 border-white/30 bg-white text-[#263A30] hover:bg-[#F4F1E9]">
                      <Download className="h-4 w-4" aria-hidden="true" />{downloading ? 'Downloading' : 'Download receipt'}
                    </Button>
                  ) : (
                    <Button type="button" variant="outline" size="lg" disabled className="mt-4 w-full gap-2 border-white/20 text-white/50">
                      <Download className="h-4 w-4" aria-hidden="true" />Receipt unavailable
                    </Button>
                  )}
                </div>
              </Card>

              <section className="space-y-3" aria-label="Order actions">
                <Button type="button" variant="primary" size="lg" onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)} className="w-full gap-2">
                  <Eye className="h-4 w-4" aria-hidden="true" />Track your order
                </Button>
                <Button type="button" variant="outline" size="lg" onClick={() => navigate('/shop')} className="w-full gap-2 border-[#D8D1C5] bg-white">
                  Continue exploring<ArrowRight className="h-4 w-4" aria-hidden="true" />
                </Button>
              </section>
              <p className="flex items-center justify-center gap-2 text-center text-[11px] text-[#827E77]"><Heart className="h-3.5 w-3.5 text-[#A2574F]" aria-hidden="true" />Thoughtfully chosen. Carefully prepared.</p>
            </aside>
          </div>
        ) : (
          <Card className="mx-auto max-w-2xl border-[#E7E1D6] bg-white p-7 text-center shadow-sm sm:p-10">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#E8EFEA] text-[#2E5A44]"><PackageCheck className="h-7 w-7" aria-hidden="true" /></div>
            <CardTitle className="mt-5 font-serif text-3xl">Your order is safe with us.</CardTitle>
            <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-[#827E77]">We’re still connecting the order details. Keep your reference to check its status, or continue exploring the collection.</p>
            <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
              <Button type="button" variant="primary" onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)} className="gap-2"><Eye className="h-4 w-4" aria-hidden="true" />Track your order</Button>
              <Button type="button" variant="outline" onClick={() => navigate('/shop')} className="gap-2">Continue exploring<ArrowRight className="h-4 w-4" aria-hidden="true" /></Button>
            </div>
          </Card>
        )}

        {receiptError && <p role="alert" className="mx-auto mt-5 max-w-2xl text-center text-xs leading-5 text-[#9B1C1C]">{receiptError}</p>}
      </main>
    </div>
  );
};
