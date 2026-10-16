import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowRight,
  BadgeCheck,
  Check,
  CheckCircle2,
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
    <div className="min-h-screen bg-[#F3F7F2] pb-14">
      <header className="bg-[#EAF4E9] px-4 py-9 text-center sm:py-12">
        <div className="mx-auto flex max-w-3xl flex-col items-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#D8EED9] text-[#2E7D4F] shadow-sm ring-8 ring-white/60">
            <BadgeCheck className="h-9 w-9" strokeWidth={1.6} aria-hidden="true" />
          </div>
          <p className="mt-6 text-[10px] font-semibold uppercase tracking-[0.22em] text-[#52715A]">MODEZA · Order care</p>
          <h1 className="mt-2 font-serif text-3xl font-medium leading-tight text-[#1D2920] sm:text-5xl">Thank you for your order, {resolvedOrder?.customer.firstName || 'there'}!</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-[#58675B] sm:text-base">Your order has been received and we’re getting it ready for you.</p>
          {simulatedPayment && <p className="mt-4 rounded-xl border border-[#D9C79F] bg-[#FFF9E9] px-4 py-3 text-xs leading-5 text-[#725B2F]" role="status">Demo checkout: no M-PESA request was sent and no payment was collected.</p>}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pt-6 sm:px-6 sm:pt-9 lg:px-8">
        {orderLoading && resolvedOrder && <p className="mb-4 text-xs text-[#827E77]" role="status" aria-live="polite">Refreshing your order details…</p>}
        {orderLoading && !resolvedOrder ? (
          <Card className="mx-auto max-w-3xl p-8 text-center" role="status" aria-live="polite">
            <p className="font-serif text-xl text-[#181716]">Gathering your order details</p>
            <Progress className="mx-auto mt-5 h-1.5 max-w-xs" aria-label="Loading order details" />
          </Card>
        ) : resolvedOrder ? (
          <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(20rem,0.85fr)]">
            <Card className="border-[#E3E8E1] bg-white p-5 shadow-sm sm:p-7" aria-busy={receiptLoading}>
              <div className="flex items-start gap-4 sm:gap-5">
                <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-[#E6F4E8] text-[#2F965F] sm:h-16 sm:w-16"><Check className="h-8 w-8" strokeWidth={2.5} aria-hidden="true" /></div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-serif text-2xl text-[#1D2920] sm:text-3xl">{resolvedOrder.status === 'cancelled' ? 'Order update' : 'Order placed successfully!'}</h2>
                    <StatusBadge status={resolvedOrder.status} />
                  </div>
                  <p className="mt-2 text-sm leading-6 text-[#647067]">{resolvedOrder.status === 'cancelled' ? 'This order has been cancelled. You can review the details below.' : 'We’ve received your order and are getting it ready to ship.'}</p>
                  <div className="mt-4 grid gap-1 text-sm text-[#59645C] sm:grid-cols-2 sm:gap-3">
                    <p><span className="text-[#879188]">Order ID:</span> <span className="font-semibold text-[#26352A]">#{resolvedOrder.orderNumber}</span></p>
                    <p><span className="text-[#879188]">Placed:</span> <span className="font-medium text-[#26352A]">{formatDate(resolvedOrder.createdAt)}</span></p>
                  </div>
                  <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-[#EDF7ED] px-3 py-1.5 text-xs text-[#41674B]"><Truck className="h-3.5 w-3.5" aria-hidden="true" />Estimated delivery: <strong>{resolvedOrder.shippingMethod === 'express' ? '2 business days' : '3–5 business days'}</strong></div>
                </div>
              </div>

              <section className="mt-7 border-t border-[#E9EDE8] pt-6" aria-labelledby="success-progress-heading">
                <div className="flex items-center justify-between gap-3"><h3 id="success-progress-heading" className="text-xs font-semibold uppercase tracking-[0.14em] text-[#536257]">Order progress</h3><span className="text-[11px] text-[#849087]">{progressValue}%</span></div>
                <Progress value={progressValue} className="mt-3 h-1.5 bg-[#E7EAE7]" aria-label="Order progress" aria-valuetext={`${progressValue}% complete`} />
                <ol className="mt-4 grid grid-cols-4 gap-1.5 sm:gap-3">
                  {PROGRESS_STEPS.map((step, index) => {
                    const reached = resolvedOrder.status !== 'cancelled' && ORDER_STATUS_META[resolvedOrder.status].rank >= ORDER_STATUS_META[step.status].rank;
                    return <li key={step.status} className="flex flex-col items-center gap-2 text-center sm:flex-row sm:items-center sm:text-left"><span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] ${reached ? 'bg-[#3CA66B] text-white' : 'bg-[#E6E9E6] text-[#89918B]'}`}>{reached ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : index + 1}</span><span className={`text-[10px] leading-4 sm:text-xs ${reached ? 'font-semibold text-[#405348]' : 'text-[#89918B]'}`}>{step.label}</span></li>;
                  })}
                </ol>
              </section>

              <div className="mt-6 flex flex-col gap-2.5 sm:flex-row sm:flex-wrap">
                <Button type="button" variant="primary" size="lg" onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)} className="gap-2 bg-[#3566C5] hover:bg-[#2957B0]"><Eye className="h-4 w-4" aria-hidden="true" />Track your order</Button>
                {receiptLoading ? <Button type="button" variant="outline" size="lg" isLoading disabled>Checking receipt</Button> : receipt ? (
                  <Button type="button" variant="outline" size="lg" isLoading={downloading} onClick={() => void handleDownloadReceipt()} className="gap-2"><Download className="h-4 w-4" aria-hidden="true" />{downloading ? 'Downloading' : 'Download receipt'}</Button>
                ) : <Button type="button" variant="outline" size="lg" disabled className="gap-2 text-[#89918B]"><Download className="h-4 w-4" aria-hidden="true" />Receipt unavailable</Button>}
                <Button type="button" variant="outline" size="lg" onClick={() => navigate('/shop')} className="gap-2 border-[#AEBDB0] bg-white text-[#385B43]">Continue shopping<ArrowRight className="h-4 w-4" aria-hidden="true" /></Button>
              </div>
              {receiptError && <p role="alert" className="mt-3 text-xs leading-5 text-[#9B1C1C]">{receiptError}</p>}
            </Card>

            <aside className="space-y-5">
              <Card className="border-[#E3E8E1] bg-white p-5 shadow-sm sm:p-6">
                <div className="flex items-center justify-between gap-3 border-b border-[#E9EDE8] pb-4"><h2 className="font-serif text-2xl text-[#1D2920]">Order summary</h2><span className="text-xs text-[#778279]">{resolvedOrder.items.reduce((sum, item) => sum + item.quantity, 0)} items</span></div>
                <ul className="divide-y divide-[#EEF0ED]">
                  {resolvedOrder.items.map((item) => <li key={item.id} className="flex items-center gap-3 py-3.5">
                    <ProductImage src={item.image} alt={item.productName} className="h-14 w-14 shrink-0 rounded-lg bg-[#F4ECE9] sm:h-16 sm:w-16" />
                    <div className="min-w-0 flex-1"><p className="line-clamp-2 text-sm font-semibold leading-5 text-[#29332B]">{item.productName}</p><p className="mt-0.5 text-[11px] text-[#818A82]">{item.variantDetails || 'One of a kind'}</p><p className="mt-1 text-xs text-[#606B62]">Qty: {item.quantity}</p></div>
                    <span className="shrink-0 text-sm font-medium text-[#29332B]">{formatPrice(item.subtotal)}</span>
                  </li>)}
                </ul>
                <div className="space-y-2 border-t border-[#E9EDE8] pt-4 text-sm">
                  <div className="flex justify-between gap-3 text-[#6F7A71]"><span>Subtotal</span><span>{formatPrice(resolvedOrder.subtotal)}</span></div>
                  {resolvedOrder.discount && resolvedOrder.discount.amount > 0 && <div className="flex justify-between gap-3 text-[#3D8055]"><span>Discount</span><span>-{formatPrice(resolvedOrder.discount.amount)}</span></div>}
                  <div className="flex justify-between gap-3 text-[#6F7A71]"><span>Shipping</span><span>{resolvedOrder.shippingCost > 0 ? formatPrice(resolvedOrder.shippingCost) : 'Free'}</span></div>
                  {resolvedOrder.tax > 0 && <div className="flex justify-between gap-3 text-[#6F7A71]"><span>Tax</span><span>{formatPrice(resolvedOrder.tax)}</span></div>}
                  <div className="flex items-baseline justify-between gap-3 border-t border-[#E9EDE8] pt-3 font-semibold text-[#26352A]"><span>Total</span><span className="font-serif text-2xl">{formatPrice(resolvedOrder.total)}</span></div>
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs text-[#748076]"><span>{paymentMethodLabel(resolvedOrder.paymentMethod)}</span><PaymentStatusBadge status={resolvedOrder.paymentStatus} /></div>
                </div>
              </Card>

              <Card className="border-[#E3E8E1] bg-white p-5 shadow-sm sm:p-6">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#718075]">Shipping to</p>
                <p className="mt-1 text-sm font-medium text-[#29372D]">{resolvedOrder.customer.firstName} {resolvedOrder.customer.lastName}</p>
                <address className="mt-1 text-xs not-italic leading-5 text-[#6F7A71]">{resolvedOrder.customer.addressLine1}{resolvedOrder.customer.addressLine2 ? `, ${resolvedOrder.customer.addressLine2}` : ''}<br />{[resolvedOrder.customer.city, resolvedOrder.customer.stateOrProvince, resolvedOrder.customer.postalCode, resolvedOrder.customer.country].filter(Boolean).join(', ')}</address>
                <p className="mt-2 flex items-center gap-1.5 text-xs text-[#738075]"><Mail className="h-3.5 w-3.5" aria-hidden="true" />{resolvedOrder.customer.email}</p>
              </Card>

              <Card className="border-[#E3E8E1] bg-white p-5 shadow-sm sm:p-6">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#718075]">Receipt</p>
                <p className="mt-1 text-sm leading-5 text-[#58665C]">{simulatedPayment ? 'A receipt will be available after a real payment is collected.' : receipt ? `Receipt ${receipt.receiptNumber} is ready to download.` : 'Your official receipt is available once payment is confirmed.'}</p>
              </Card>
            </aside>
          </div>
        ) : (
          <Card className="mx-auto max-w-2xl border-[#E3E8E1] bg-white p-7 text-center shadow-sm sm:p-10">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#E6F4E8] text-[#2F965F]"><PackageCheck className="h-7 w-7" aria-hidden="true" /></div>
            <CardTitle className="mt-5 font-serif text-3xl">Your order is safe with us.</CardTitle>
            <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-[#6F7A71]">We’re still connecting the order details. Keep your reference to check its status, or continue shopping.</p>
            <p className="mt-4 font-mono text-sm text-[#405348]">{refCode || 'Awaiting reference'}</p>
            <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
              <Button type="button" variant="primary" onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)} className="gap-2"><Eye className="h-4 w-4" aria-hidden="true" />Track your order</Button>
              <Button type="button" variant="outline" onClick={() => navigate('/shop')} className="gap-2">Continue shopping<ArrowRight className="h-4 w-4" aria-hidden="true" /></Button>
            </div>
          </Card>
        )}
      </main>
    </div>
  );
};