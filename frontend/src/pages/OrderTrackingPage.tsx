import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock,
  MapPin,
  PackageCheck,
  Search,
  ShieldCheck,
  Truck,
  XCircle,
} from 'lucide-react';
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
  CardHeader,
  CardTitle,
  Input,
  Progress,
} from '../components/modeza';
import { useOrders } from '../context/OrdersContext';
import { useRouter } from '../router/RouterContext';
import { ProductImage } from '../components/ui/ProductImage';
import { api } from '../services/apiClient';
import { formatPrice } from '../utils/currency';
import { mapServerOrder } from '../utils/orderMapper';
import { canCancel, canMarkReceived, ORDER_STATUS_META } from '../utils/orderStatus';
import { Order, OrderStatus, PaymentStatus } from '../types';

export interface OrderTrackingPageProps {
  orderNumber?: string;
}

type OrderAction = 'cancel' | 'receive';

interface PendingOrderAction {
  type: OrderAction;
  orderNumber: string;
}

function StatusBadge({ status }: { status: OrderStatus }) {
  switch (status) {
    case 'confirmed':
      return (
        <Badge variant="success" size="sm" className="gap-1.5">
          <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
          Confirmed
        </Badge>
      );
    case 'processing':
      return (
        <Badge variant="secondary" size="sm" className="gap-1.5">
          <PackageCheck className="h-3 w-3" aria-hidden="true" />
          MODEZA Preparation
        </Badge>
      );
    case 'shipped':
      return (
        <Badge variant="default" size="sm" className="gap-1.5 border-[#D8B1A5] bg-[#F4ECE9] text-[#83443D]">
          <Truck className="h-3 w-3" aria-hidden="true" />
          In transit
        </Badge>
      );
    case 'delivered':
      return (
        <Badge variant="success" size="sm" className="gap-1.5">
          <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
          Delivered
        </Badge>
      );
    case 'received':
      return (
        <Badge variant="success" size="sm" className="gap-1.5">
          <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
          Received
        </Badge>
      );
    case 'cancelled':
      return (
        <Badge variant="destructive" size="sm" className="gap-1.5">
          <XCircle className="h-3 w-3" aria-hidden="true" />
          Cancelled &amp; Restocked
        </Badge>
      );
    default:
      return (
        <Badge variant="default" size="sm" className="gap-1.5">
          <Clock className="h-3 w-3" aria-hidden="true" />
          Pending
        </Badge>
      );
  }
}

function PaymentStatusBadge({ status }: { status: PaymentStatus }) {
  const variant = status === 'paid'
    ? 'success'
    : status === 'failed'
      ? 'destructive'
      : status === 'refunded'
        ? 'secondary'
        : 'warning';

  return <Badge variant={variant} size="sm">Payment {status}</Badge>;
}

function getProgressValue(order: Order): number {
  if (order.status === 'cancelled') return 0;
  const rank = Math.max(0, ORDER_STATUS_META[order.status].rank);
  return Math.round((rank / 4) * 100);
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return 'Time unavailable';
  return date.toLocaleString('en-KE', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

export const OrderTrackingPage: React.FC<OrderTrackingPageProps> = ({ orderNumber: propOrderNum }) => {
  const { getOrder, cancelOrder, receiveOrder } = useOrders();
  const { navigate } = useRouter();
  const [searchQuery, setSearchQuery] = useState(propOrderNum || '');
  const [activeOrder, setActiveOrder] = useState<Order | null>(() => (propOrderNum ? getOrder(propOrderNum) || null : null));
  const [isSearchFormOpen, setIsSearchFormOpen] = useState(
    () => !propOrderNum || !getOrder(propOrderNum),
  );
  const [errorMsg, setErrorMsg] = useState('');
  const [actionSuccessMsg, setActionSuccessMsg] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingOrderAction | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    if (propOrderNum) {
      setSearchQuery(propOrderNum);
      const found = getOrder(propOrderNum);
      if (found) {
        setActiveOrder(found);
        setErrorMsg('');
        setIsSearchFormOpen(false);
      } else {
        setActiveOrder(null);
        setIsSearchFormOpen(true);
      }
    }
  }, [propOrderNum, getOrder]);

  const handleSearch = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMsg('');
    setActionSuccessMsg('');

    const cleanQuery = searchQuery.trim();
    const found = getOrder(cleanQuery);
    if (found) {
      setActiveOrder(found);
      setIsSearchFormOpen(false);
      return;
    }

    setIsSearching(true);
    try {
      const serverOrder = await api.getOrder(cleanQuery);
      setActiveOrder(mapServerOrder(serverOrder));
      setIsSearchFormOpen(false);
    } catch {
      setActiveOrder(null);
      setErrorMsg(`No record found for order "${searchQuery}". Please check reference code or contact concierge.`);
    } finally {
      setIsSearching(false);
    }
  };

  const handleConfirmAction = async () => {
    if (!pendingAction) return;

    setActionLoading(true);
    setActionSuccessMsg('');
    setErrorMsg('');

    try {
      const result = pendingAction.type === 'cancel'
        ? await cancelOrder(pendingAction.orderNumber)
        : await receiveOrder(pendingAction.orderNumber);

      if (result.success && result.order) {
        setActionSuccessMsg(result.message);
        setActiveOrder(result.order);
      } else {
        setErrorMsg(result.message);
      }
    } catch {
      setErrorMsg('The order could not be updated right now. Please try again.');
    } finally {
      setActionLoading(false);
      setPendingAction(null);
    }
  };

  const progressValue = activeOrder ? getProgressValue(activeOrder) : 0;
  const completedSteps = activeOrder?.timeline.filter((step) => step.completed).length || 0;
  const totalSteps = activeOrder?.timeline.length || 0;
  const pendingActionIsCancellation = pendingAction?.type === 'cancel';

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6 sm:py-10 lg:px-8">
      {activeOrder ? (
        <header className="space-y-5">
          <button
            type="button"
            onClick={() => navigate(`/account/orders/${encodeURIComponent(activeOrder.orderNumber)}`)}
            className="inline-flex items-center gap-2 text-xs font-medium text-[#63605A] transition-colors hover:text-[#A2574F]"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to order details
          </button>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="min-w-0">
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">
                Client services · Order tracking
              </p>
              <h1 className="mt-2 font-serif text-3xl font-normal tracking-tight text-[#181716] sm:text-4xl">
                Track your order
              </h1>
              <p className="mt-2 break-all font-mono text-xs text-[#63605A]">
                Order ID: {activeOrder.orderNumber}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
              <StatusBadge status={activeOrder.status} />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setIsSearchFormOpen((open) => !open)}
              >
                {isSearchFormOpen ? 'Close order search' : 'Track another order'}
              </Button>
              {canCancel(activeOrder.status) && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={actionLoading}
                  onClick={() => setPendingAction({ type: 'cancel', orderNumber: activeOrder.orderNumber })}
                  className="border-[#F8B4B4] text-[#9B1C1C] hover:border-[#9B1C1C] hover:bg-[#FDF2F2] hover:text-[#9B1C1C]"
                >
                  Cancel &amp; restock
                </Button>
              )}
              {canMarkReceived(activeOrder.status, activeOrder.paymentMethod) && (
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  disabled={actionLoading}
                  onClick={() => setPendingAction({ type: 'receive', orderNumber: activeOrder.orderNumber })}
                >
                  Mark as received
                </Button>
              )}
            </div>
          </div>
        </header>
      ) : (
        <header className="mx-auto max-w-2xl text-center">
          <Badge variant="outline" size="lg" className="mb-4">Client Services · Order Tracking</Badge>
          <h1 className="font-serif text-3xl font-normal tracking-tight text-[#181716] sm:text-5xl">
            Track your MODEZA order
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-sm leading-7 text-[#63605A]">
            Follow each real milestone from confirmation through dispatch, with the latest status from your order ledger.
          </p>
        </header>
      )}

      {(!activeOrder || isSearchFormOpen) && (
      <Card className={`mx-auto p-0 shadow-sm sm:p-0 ${activeOrder ? 'max-w-none' : 'max-w-3xl'}`}>
        <CardHeader className="border-b border-[#F3F1ED] p-5 sm:p-6">
          <CardTitle className="text-xl">{activeOrder ? 'Track another order' : 'Find an order'}</CardTitle>
          <p className="text-xs leading-5 text-[#63605A]">
            Enter the reference code from your confirmation to view live status and delivery details.
          </p>
        </CardHeader>
        <CardContent className="p-5 pt-5 sm:p-6 sm:pt-6">
          <form onSubmit={handleSearch} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <Input
                id="tracking-reference"
                label="Order reference"
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="e.g. AT-KES12AB34CDEF"
                autoComplete="off"
                icon={<Search className="h-4 w-4" aria-hidden="true" />}
                className="h-12 uppercase tracking-wider placeholder:normal-case placeholder:tracking-normal"
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              isLoading={isSearching}
              className="w-full sm:w-auto"
            >
              Locate order
            </Button>
          </form>
          <p className="mt-3 text-[11px] leading-5 text-[#827E77]">
            Only orders placed through the boutique can be tracked.
          </p>
        </CardContent>
      </Card>
      )}

      {errorMsg && (
        <div
          role="alert"
          className="mx-auto flex max-w-3xl items-start gap-3 rounded-2xl border border-[#F8B4B4] bg-[#FDF2F2] p-4 text-sm leading-6 text-[#9B1C1C]"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{errorMsg}</span>
        </div>
      )}

      {actionSuccessMsg && (
        <div
          role="status"
          aria-live="polite"
          className="mx-auto flex max-w-3xl items-start gap-3 rounded-2xl border border-[#B7EB8F] bg-[#EDF7ED] p-4 text-sm leading-6 text-[#1E4620]"
        >
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{actionSuccessMsg}</span>
        </div>
      )}

      {activeOrder && (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(18rem,0.85fr)]">
          <div className="min-w-0 space-y-5">
            <Card className="overflow-hidden p-0 shadow-sm">
              <div className="border-b border-[#F3F1ED] p-5 sm:p-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">
                      Shipment activity
                    </p>
                    <h2 className="mt-1 font-serif text-xl text-[#181716]">
                      Tracking history
                    </h2>
                  </div>
                  <p className="text-right text-xs text-[#827E77]">
                    Placed{" "}
                    {new Date(activeOrder.createdAt).toLocaleDateString('en-KE', { dateStyle: 'medium' })}
                  </p>
                </div>
                <div className="mt-5 flex items-center gap-3">
                  <Progress
                    value={progressValue}
                    aria-label="Order journey progress"
                    aria-valuetext={`${progressValue}% complete`}
                    className="h-2"
                  />
                  <span className="shrink-0 text-xs font-semibold text-[#A2574F]">
                    {progressValue}%
                  </span>
                </div>
                <p className="mt-2 text-xs text-[#827E77]">
                  {completedSteps} of {totalSteps} recorded milestones complete
                </p>
              </div>

              <div className="p-5 sm:p-6">
                <h3 id="tracking-timeline-heading" className="text-xs font-semibold uppercase tracking-[0.16em] text-[#827E77]">
                  MODEZA order timeline
                </h3>
                {totalSteps > 0 ? (
                  <ol className="mt-5">
                    {activeOrder.timeline.map((step, index) => (
                      <li
                        key={`${step.status}-${step.timestamp}-${index}`}
                        className="relative pb-7 pl-9 last:pb-0"
                        aria-current={step.status === activeOrder.status ? 'step' : undefined}
                      >
                        {index < totalSteps - 1 && (
                          <span
                            aria-hidden="true"
                            className="absolute bottom-0 left-[0.4375rem] top-5 w-px bg-[#E8E5DF]"
                          />
                        )}
                        <span
                          className={`absolute left-0 top-0 flex h-5 w-5 items-center justify-center rounded-full ring-4 ring-white ${
                            step.completed
                              ? 'bg-[#A2574F] text-white'
                              : 'border border-[#D8D3CB] bg-[#FAF9F6] text-[#A29E96]'
                          }`}
                          aria-hidden="true"
                        >
                          {step.completed
                            ? <CheckCircle2 className="h-3.5 w-3.5" />
                            : <Clock className="h-3 w-3" />}
                        </span>
                        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                          <div className="min-w-0">
                            <h4 className="text-sm font-semibold text-[#181716]">{step.title}</h4>
                            <p className="mt-1 text-xs leading-5 text-[#63605A]">{step.description}</p>
                          </div>
                          {step.timestamp && (
                            <time dateTime={step.timestamp} className="shrink-0 text-[10px] leading-5 text-[#827E77] sm:text-right">
                              {formatTimestamp(step.timestamp)}
                            </time>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="mt-4 rounded-xl border border-dashed border-[#E8E5DF] p-5 text-sm text-[#63605A]">
                    No timeline events have been recorded for this order yet.
                  </p>
                )}
              </div>
            </Card>

            <Card className="p-5 shadow-sm sm:p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#A2574F]">
                    In your parcel
                  </p>
                  <h2 className="mt-1 font-serif text-xl text-[#181716]">Order items</h2>
                </div>
                <Badge variant="outline" size="sm">
                  {activeOrder.items.reduce((sum, item) => sum + item.quantity, 0)} pieces
                </Badge>
              </div>
              <ul className="mt-4 divide-y divide-[#F3F1ED]">
                {activeOrder.items.map((item) => (
                  <li key={item.id} className="flex flex-wrap items-center justify-between gap-4 py-4 last:pb-0">
                    <div className="flex min-w-0 flex-1 items-center gap-4">
                      <ProductImage src={item.image} alt={item.productName} className="h-20 w-16 shrink-0 rounded-xl" />
                      <div className="min-w-0">
                        <h3 className="break-words font-serif text-sm text-[#181716]">{item.productName}</h3>
                        <p className="mt-1 text-xs text-[#827E77]">{item.variantDetails || '—'}</p>
                        <p className="mt-1 text-xs text-[#63605A]">
                          Qty {item.quantity} × {formatPrice(item.unitPrice)}
                        </p>
                      </div>
                    </div>
                    <span className="shrink-0 text-sm font-medium text-[#181716]">{formatPrice(item.subtotal)}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <aside className="min-w-0 space-y-5" aria-label="Delivery and order details">
            <Card className="p-5 shadow-sm sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#A2574F]">
                    Delivery overview
                  </p>
                  <h2 className="mt-1 font-serif text-xl text-[#181716]">Shipment status</h2>
                </div>
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F]">
                  <Truck className="h-5 w-5" aria-hidden="true" />
                </span>
              </div>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
                <StatusBadge status={activeOrder.status} />
                <PaymentStatusBadge status={activeOrder.paymentStatus} />
              </div>
              <div className="mt-5">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="font-medium text-[#181716]">Order progress</span>
                  <span className="font-semibold text-[#A2574F]">{progressValue}%</span>
                </div>
                <Progress
                  value={progressValue}
                  aria-label="Order progress"
                  aria-valuetext={`${progressValue}% complete`}
                  className="mt-2 h-2"
                />
              </div>
              <dl className="mt-5 space-y-3 border-t border-[#F3F1ED] pt-4 text-xs">
                <div className="flex items-start justify-between gap-4">
                  <dt className="text-[#827E77]">Delivery method</dt>
                  <dd className="text-right font-medium text-[#181716]">
                    {activeOrder.shippingMethod === 'express' ? 'Express delivery' : 'Standard delivery'}
                  </dd>
                </div>
                <div>
                  <dt className="text-[#827E77]">Delivery estimate</dt>
                  <dd className="mt-1 leading-5 text-[#63605A]">
                    {activeOrder.status === 'delivered' || activeOrder.status === 'received'
                      ? `Order delivered · ${formatTimestamp(activeOrder.timeline.find((step) => step.status === 'delivered')?.timestamp || activeOrder.updatedAt)}`
                      : 'A delivery date will appear here once it is confirmed.'}
                  </dd>
                </div>
              </dl>
            </Card>

            <Card className="p-5 shadow-sm sm:p-6">
              <div className="flex items-center gap-2">
                <MapPin className="h-4 w-4 text-[#A2574F]" aria-hidden="true" />
                <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-[#181716]">
                  Delivery address
                </h2>
              </div>
              <address className="mt-4 text-sm not-italic leading-6 text-[#63605A]">
                <p className="font-medium text-[#181716]">
                  {activeOrder.customer.firstName} {activeOrder.customer.lastName}
                </p>
                <p>
                  {activeOrder.customer.addressLine1}
                  {activeOrder.customer.addressLine2 ? `, ${activeOrder.customer.addressLine2}` : ''}
                </p>
                <p>
                  {activeOrder.customer.city}
                  {activeOrder.customer.stateOrProvince ? `, ${activeOrder.customer.stateOrProvince}` : ''}
                  {activeOrder.customer.postalCode ? ` ${activeOrder.customer.postalCode}` : ''}
                </p>
                <p>{activeOrder.customer.country}</p>
              </address>
              <p className="mt-4 border-t border-[#F3F1ED] pt-3 text-xs text-[#827E77]">
                {activeOrder.shippingMethod === 'express' ? 'Express' : 'Standard'} shipping
                {activeOrder.shippingCost === 0 ? ' · Complimentary' : ` · ${formatPrice(activeOrder.shippingCost)}`}
              </p>
            </Card>

            <Card className="p-5 shadow-sm sm:p-6">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-[#A2574F]" aria-hidden="true" />
                <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-[#181716]">
                  Order summary
                </h2>
              </div>
              <dl className="mt-4 space-y-2.5 text-xs text-[#63605A]">
                <div className="flex items-center justify-between gap-4">
                  <dt>Subtotal</dt>
                  <dd className="font-medium text-[#181716]">{formatPrice(activeOrder.subtotal)}</dd>
                </div>
                {activeOrder.discount && (
                  <div className="flex items-center justify-between gap-4 text-[#2E5A44]">
                    <dt className="min-w-0 break-words">
                      Promotion{activeOrder.discount.code ? ` (${activeOrder.discount.code})` : ''}
                    </dt>
                    <dd className="shrink-0 font-medium">-{formatPrice(activeOrder.discount.amount)}</dd>
                  </div>
                )}
                <div className="flex items-center justify-between gap-4">
                  <dt>VAT</dt>
                  <dd className="font-medium text-[#181716]">{formatPrice(activeOrder.tax)}</dd>
                </div>
                <div className="flex items-center justify-between gap-4 border-t border-[#E8E5DF] pt-3 font-serif text-base font-semibold text-[#181716]">
                  <dt>Total</dt>
                  <dd>{formatPrice(activeOrder.total)}</dd>
                </div>
              </dl>
            </Card>

            <Card className="bg-[#FAF9F6] p-5 shadow-none sm:p-6">
              <h2 className="font-serif text-lg text-[#181716]">Need a hand?</h2>
              <p className="mt-2 text-xs leading-5 text-[#63605A]">
                Our concierge can help with questions about this order or its delivery.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => navigate('/contact')}
                className="mt-4 w-full"
              >
                Contact the concierge
              </Button>
            </Card>
          </aside>
        </div>
      )}

      <div className="flex justify-center pt-2">
        <Button type="button" variant="outline" size="md" onClick={() => navigate('/shop')} className="gap-2">
          Return to collection
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </div>

      <AlertDialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open && !actionLoading) setPendingAction(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingActionIsCancellation ? 'Cancel this order?' : 'Confirm receipt'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingActionIsCancellation
                ? `Cancelling ${pendingAction?.orderNumber} will return the reserved MODEZA stock.`
                : `Confirm that you have received ${pendingAction?.orderNumber}.`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={actionLoading}>Keep order</AlertDialogCancel>
            <AlertDialogAction
              disabled={actionLoading}
              aria-busy={actionLoading}
              className={pendingActionIsCancellation ? 'bg-[#9E332B] hover:bg-[#8B2A24]' : undefined}
              onClick={() => void handleConfirmAction()}
            >
              {actionLoading ? 'Updating…' : pendingActionIsCancellation ? 'Cancel order' : 'Confirm receipt'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
