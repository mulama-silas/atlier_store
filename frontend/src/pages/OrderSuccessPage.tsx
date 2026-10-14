import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  Download,
  Eye,
  Mail,
  MapPin,
  PackageCheck,
  Printer,
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
  const [receiptUnavailable, setReceiptUnavailable] = useState(false);
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

  const handleOpenReceipt = useCallback(async () => {
    if (!receipt) return;
    const receiptWindow = window.open('', '_blank');
    if (!receiptWindow) {
      setReceiptError('Please allow pop-ups to open the receipt.');
      return;
    }
    setDownloading(true);
    setReceiptError('');
    try {
      const blob = await api.downloadReceipt(receipt.receiptNumber);
      const url = URL.createObjectURL(blob);
      receiptWindow.location.href = url;
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      receiptWindow.close();
      setReceiptError(err instanceof Error ? err.message : 'The receipt could not be opened.');
    } finally {
      setDownloading(false);
    }
  }, [receipt]);

  useEffect(() => {
    if (!order || order.paymentStatus !== 'paid') {
      setReceipt(null);
      setReceiptUnavailable(false);
      setReceiptError('');
      setReceiptLoading(false);
      return;
    }

    let cancelled = false;
    setReceipt(null);
    setReceiptUnavailable(false);
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
          setReceiptUnavailable(true);
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
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-12 text-center sm:px-6 sm:py-16 lg:px-8">
      <header className="mx-auto max-w-2xl space-y-4">
        <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full border border-[#C8D8CA] bg-[#F2F6F2] text-[#2E5A44] shadow-sm">
          <CheckCircle2 className="h-10 w-10 stroke-[1.5]" aria-hidden="true" />
        </div>
        <Badge variant="outline" size="lg">Order confirmation · {refCode || 'Pending reference'}</Badge>
        <h1 className="font-serif text-3xl font-normal tracking-tight text-[#181716] sm:text-5xl">
          Thank you. Your order is in.
        </h1>
        <p className="mx-auto max-w-xl text-sm leading-7 text-[#63605A]">
          Your confirmation is recorded. We will send email and SMS updates as each MODEZA milestone is completed.
        </p>
      </header>

      <Card className="mx-auto max-w-3xl overflow-hidden p-0 text-left shadow-sm" aria-busy={orderLoading || receiptLoading}>
        <CardHeader className="border-b border-[#F3F1ED] p-5 sm:p-7">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">Reference code</p>
              <p className="mt-1 break-all font-mono text-sm font-medium text-[#181716] sm:text-base">{refCode || 'Awaiting order reference'}</p>
            </div>
            <div className="text-left sm:text-right">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">Current status</p>
              <div className="mt-1"><StatusBadge status={resolvedOrder?.status} /></div>
            </div>
          </div>
          {orderLoading && resolvedOrder && (
            <p className="mt-3 text-xs text-[#827E77]" role="status" aria-live="polite">
              Refreshing the latest order status…
            </p>
          )}
        </CardHeader>

        <CardContent className="space-y-6 p-5 pt-5 sm:p-7 sm:pt-7">
          {orderLoading && !resolvedOrder ? (
            <div className="rounded-2xl border border-dashed border-[#E8E5DF] bg-[#FAF9F6] p-6 text-center" role="status" aria-live="polite">
              <p className="text-sm font-medium text-[#181716]">Finding your order details…</p>
              <Progress className="mx-auto mt-5 h-1.5 max-w-xs" aria-label="Loading order details" />
            </div>
          ) : resolvedOrder ? (
            <>
              <section aria-labelledby="success-progress-heading">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#A2574F]">Next steps</p>
                    <h2 id="success-progress-heading" className="mt-1 text-sm font-semibold text-[#181716]">Order progress</h2>
                  </div>
                  <span className="text-xs text-[#827E77]">{progressValue}% complete</span>
                </div>
                <Progress
                  value={progressValue}
                  className="mt-4 h-2"
                  aria-label="Order progress"
                  aria-valuetext={`${progressValue}% complete`}
                />
                <ol className="mt-3 grid grid-cols-4 gap-2 text-center">
                  {PROGRESS_STEPS.map((step) => {
                    const reached = resolvedOrder.status !== 'cancelled' && ORDER_STATUS_META[resolvedOrder.status].rank >= ORDER_STATUS_META[step.status].rank;
                    return (
                      <li key={step.status} className={`text-[10px] font-semibold uppercase tracking-[0.1em] ${reached ? 'text-[#181716]' : 'text-[#A29E96]'}`}>
                        {step.label}
                      </li>
                    );
                  })}
                </ol>
              </section>

              <section aria-labelledby="success-items-heading" className="border-t border-[#F3F1ED] pt-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h2 id="success-items-heading" className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">
                    Reserved MODEZA pieces
                  </h2>
                  <Badge variant="outline" size="sm">
                    {resolvedOrder.items.reduce((sum, item) => sum + item.quantity, 0)} total
                  </Badge>
                </div>
                <ul className="mt-3 divide-y divide-[#F3F1ED]">
                  {resolvedOrder.items.map((item) => (
                    <li key={item.id} className="flex items-center justify-between gap-4 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <ProductImage src={item.image} alt={item.productName} className="h-12 w-10 shrink-0 rounded-lg" />
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-[#181716]">{item.productName}</p>
                          <p className="text-xs text-[#827E77]">{item.variantDetails || '—'}</p>
                        </div>
                      </div>
                      <span className="shrink-0 text-sm font-medium text-[#181716]">{formatPrice(item.subtotal)}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex items-center justify-between border-t border-[#F3F1ED] pt-4 text-sm">
                  <span className="text-[#63605A]">Total settled</span>
                  <span className="font-serif text-lg font-semibold text-[#181716]">{formatPrice(resolvedOrder.total)}</span>
                </div>
              </section>

              <section className="grid gap-4 border-t border-[#F3F1ED] pt-5 sm:grid-cols-3" aria-label="Payment and delivery summary">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#827E77]">Payment</p>
                  <p className="mt-1 text-xs text-[#181716]">{paymentMethodLabel(resolvedOrder.paymentMethod)}</p>
                  <div className="mt-2"><PaymentStatusBadge status={resolvedOrder.paymentStatus} /></div>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#827E77]">Estimated dispatch</p>
                  <p className="mt-1 text-xs leading-5 text-[#181716]">{dispatchCopy}</p>
                </div>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#827E77]">Destination</p>
                  <p className="mt-1 flex items-center gap-1 text-xs text-[#181716]">
                    <MapPin className="h-3 w-3 shrink-0 text-[#A2574F]" aria-hidden="true" />
                    <span className="truncate">{resolvedOrder.customer.city}, {resolvedOrder.customer.country}</span>
                  </p>
                </div>
              </section>

              <div className="flex items-start gap-3 rounded-2xl border border-[#E8E5DF] bg-[#FAF9F6] p-4 text-left text-xs leading-5 text-[#63605A]">
                <Mail className="mt-0.5 h-4 w-4 shrink-0 text-[#A2574F]" aria-hidden="true" />
                <p>
                  We will notify {resolvedOrder.customer.email} when preparation and courier collection are confirmed.
                </p>
              </div>
            </>
          ) : (
            <div className="rounded-2xl border border-[#E8E5DF] bg-[#FAF9F6] p-5 text-left">
              <CardTitle className="text-lg">Order reference received</CardTitle>
              <CardDescription className="mt-2 text-sm">
                We are still connecting your confirmation. You can use the reference above to track the order or return to the collection.
              </CardDescription>
            </div>
          )}
        </CardContent>
      </Card>

      <section className="mx-auto max-w-2xl space-y-5" aria-label="Order actions">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Button
            type="button"
            variant="primary"
            size="lg"
            onClick={() => navigate(`/track?order=${encodeURIComponent(refCode)}`)}
            className="w-full gap-2"
          >
            <Eye className="h-4 w-4" aria-hidden="true" />
            Live order tracking
          </Button>
          <Button type="button" variant="outline" size="lg" onClick={() => navigate('/shop')} className="w-full gap-2">
            Continue exploring
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>

        <Card className="p-5 shadow-sm sm:p-6">
          <div className="flex items-center gap-3 text-center">
            <span className="h-px flex-1 bg-[#E8E5DF]" aria-hidden="true" />
            <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#827E77]">Official receipt</span>
            <span className="h-px flex-1 bg-[#E8E5DF]" aria-hidden="true" />
          </div>
          <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {receiptLoading ? (
              <Button type="button" variant="outline" size="lg" isLoading disabled className="w-full">
                Checking receipt
              </Button>
            ) : receipt ? (
              <Button
                type="button"
                variant="outline"
                size="lg"
                isLoading={downloading}
                onClick={() => void handleDownloadReceipt()}
                className="w-full gap-2"
              >
                <Download className="h-3.5 w-3.5" aria-hidden="true" />
                {downloading ? 'Downloading' : 'Download receipt (PDF)'}
              </Button>
            ) : (
              <Button type="button" variant="outline" size="lg" disabled className="w-full gap-2">
                <Download className="h-3.5 w-3.5" aria-hidden="true" />
                Receipt unavailable
              </Button>
            )}

            <Button
              type="button"
              variant="outline"
              size="lg"
              onClick={() => {
                if (receipt) {
                  void handleOpenReceipt();
                } else if (receiptUnavailable) {
                  window.print();
                }
              }}
              disabled={downloading || receiptLoading || (!receipt && !receiptUnavailable)}
              className="w-full gap-2"
            >
              <Printer className="h-3.5 w-3.5" aria-hidden="true" />
              Print receipt
            </Button>
          </div>
        </Card>
      </section>

      {orderNumber && resolvedOrder && (
        <p className="text-xs text-[#827E77]">Confirmation received on {formatDate(resolvedOrder.createdAt)}.</p>
      )}

      {receiptError && (
        <p role="alert" className="text-xs leading-5 text-[#9B1C1C]">{receiptError}</p>
      )}
    </div>
  );
};
