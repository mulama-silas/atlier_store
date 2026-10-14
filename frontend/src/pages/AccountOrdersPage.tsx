import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowRight, Check, Package, RefreshCw, Search, ShoppingBag, Truck, X } from 'lucide-react';
import { useOrders } from '../context/OrdersContext';
import { useStore } from '../context/StoreContext';
import { useRouter } from '../router/RouterContext';
import { AccountPageHeader } from '../components/account/AccountPageHeader';
import { Button } from '../components/modeza/Button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../components/modeza/AlertDialog';
import { Badge } from '../components/modeza/Badge';
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '../components/modeza/Card';
import { Input } from '../components/modeza/Input';
import { Progress } from '../components/modeza/Progress';
import { Tabs, TabsList, TabsTrigger } from '../components/modeza/Tabs';
import { OrderProgress } from '../components/orders/OrderProgress';
import { OrderItemThumb } from '../components/orders/OrderItemThumb';
import { api } from '../services/apiClient';
import { Order, OrderItem } from '../types';
import { formatPrice } from '../utils/currency';
import {
  formatOrderDate,
  mapServerOrder,
  totalQuantity,
} from '../utils/orderMapper';
import {
  isActiveOrder,
  isTrackable,
  canMarkReceived,
  ORDER_STATUS_META,
  STATUS_FILTER_GROUPS,
} from '../utils/orderStatus';

type StatusBadgeVariant = 'default' | 'new' | 'success' | 'destructive';

const getStatusBadgeVariant = (status: Order['status']): StatusBadgeVariant => {
  if (status === 'cancelled') return 'destructive';
  if (status === 'delivered' || status === 'received') return 'success';
  if (status === 'pending') return 'default';
  return 'new';
};

interface OrderCardProps {
  order: Order;
  onMarkReceived: (order: Order) => void;
  isMarkingReceived: boolean;
}

const OrderCard: React.FC<OrderCardProps> = ({ order, onMarkReceived, isMarkingReceived }) => {
  const { navigate } = useRouter();
  const { getProductById } = useStore();

  const totalItems = totalQuantity(order);
  const items = order.items;
  const visibleItems = items.slice(0, 4);
  const hiddenCount = items.length - visibleItems.length;
  const isActive = isActiveOrder(order.status);
  const statusMeta = ORDER_STATUS_META[order.status];

  const formatPlaced = () =>
    formatOrderDate(order.createdAt, { day: 'numeric', month: 'long', year: 'numeric' });

  const completionTimestamp = useMemo(() => {
    if (order.status === 'delivered' || order.status === 'received') {
      const timelineTimestamp = order.timeline.find(
        (event) => event.status === 'delivered' || event.status === 'received'
      )?.timestamp;
      return timelineTimestamp || order.updatedAt;
    }
    if (order.status === 'cancelled') {
      const timelineTimestamp = order.timeline.find((event) => event.status === 'cancelled')?.timestamp;
      return timelineTimestamp || order.updatedAt;
    }
    return '';
  }, [order]);

  const openDetails = () => navigate(`/account/orders/${encodeURIComponent(order.orderNumber)}`);
  const openTrack = () => navigate(`/track?order=${encodeURIComponent(order.orderNumber)}`);

  const openProduct = (item: OrderItem) => {
    const product = item.productId ? getProductById(item.productId) : undefined;
    if (product) {
      navigate(`/product/${product.slug}`);
    } else {
      openDetails();
    }
  };

  return (
    <article aria-label={`Order ${order.orderNumber}`}>
      <Card className="overflow-hidden border-[#E8E5DF] shadow-xs">
        <CardHeader className="block border-b border-[#F3F1ED] p-5 sm:p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2.5">
                <CardTitle className="font-mono text-sm font-semibold tracking-tight text-[#181716] sm:text-base">
                  <a
                    href={`/account/orders/${encodeURIComponent(order.orderNumber)}`}
                    onClick={(event) => {
                      event.preventDefault();
                      openDetails();
                    }}
                    className="rounded-sm transition-colors hover:text-[#A2574F] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
                    aria-label={`View order ${order.orderNumber}`}
                  >
                    {order.orderNumber}
                  </a>
                </CardTitle>
                <Badge variant={getStatusBadgeVariant(order.status)} size="sm" className="gap-1.5">
                  <span className={`h-1.5 w-1.5 rounded-full ${statusMeta.dotClass}`} aria-hidden="true" />
                  {statusMeta.label}
                </Badge>
              </div>
              <p className="mt-2 text-xs text-[#827E77]">Placed {formatPlaced()}</p>
            </div>
            <div className="flex items-end justify-between gap-4 sm:block sm:text-right">
              <div className="font-serif text-xl leading-none text-[#181716] sm:text-2xl">
                {formatPrice(order.total)}
              </div>
              <p className="mt-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#827E77]">
                {totalItems} {totalItems === 1 ? 'item' : 'items'}
              </p>
            </div>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          <div className="px-5 py-5 sm:px-6">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#827E77]">Items in this order</p>
              <span className="text-[10px] uppercase tracking-[0.14em] text-[#A29E96]">{items.length} {items.length === 1 ? 'piece' : 'pieces'}</span>
            </div>
            {visibleItems.length > 0 ? (
              <div className="flex items-center gap-2.5 overflow-x-auto pb-1 no-scrollbar sm:gap-3" aria-label="Products in this order">
                {visibleItems.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => openProduct(item)}
                    aria-label={`View ${item.productName}`}
                    title={item.productName}
                    className="h-16 w-14 shrink-0 overflow-hidden rounded-lg border border-[#E8E5DF] bg-[#F4ECE9] shadow-xs transition-transform duration-300 hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 sm:h-20 sm:w-[4.5rem] image-zoom"
                  >
                    <OrderItemThumb item={item} className="h-full w-full" />
                  </button>
                ))}
                {hiddenCount > 0 && (
                  <button
                    type="button"
                    onClick={openDetails}
                    aria-label={`${hiddenCount} more ${hiddenCount === 1 ? 'item' : 'items'}`}
                    className="flex h-16 w-14 shrink-0 flex-col items-center justify-center rounded-lg border border-[#E8E5DF] bg-[#FAF9F6] text-[#181716] transition-colors hover:bg-[#F4ECE9] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2 sm:h-20 sm:w-[4.5rem]"
                  >
                    <span className="font-serif text-lg leading-none">+{hiddenCount}</span>
                    <span className="mt-1 text-[8px] font-semibold uppercase tracking-[0.14em] text-[#827E77]">more</span>
                  </button>
                )}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-[#D8D3CB] bg-[#FAF9F6] px-4 py-5 text-center text-sm text-[#63605A]">
                No product details are available for this order.
              </div>
            )}
          </div>

          <div className="border-t border-[#F3F1ED]">
            {order.status === 'cancelled' ? (
              <div className="mx-5 my-5 flex items-start gap-2.5 rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-4 py-3 sm:mx-6">
                <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#827E77]" aria-hidden="true" />
                <p className="text-xs leading-relaxed text-[#63605A]">
                  Order cancelled
                  {completionTimestamp ? (
                    <span>
                      {' '}on{' '}
                      {formatOrderDate(completionTimestamp, { day: 'numeric', month: 'long', year: 'numeric' })}
                    </span>
                  ) : null}
                  .
                </p>
              </div>
            ) : order.status === 'delivered' || order.status === 'received' ? (
              <div className="flex items-center gap-2 px-5 py-5 sm:px-6">
                <Check className="h-3.5 w-3.5 shrink-0 text-[#2E5A44]" aria-hidden="true" />
                <p className="text-xs font-medium text-[#2E5A44]">
                  {statusMeta.label}
                  {completionTimestamp ? (
                    <span>
                      {' '}on{' '}
                      {formatOrderDate(completionTimestamp, { day: 'numeric', month: 'long', year: 'numeric' })}
                    </span>
                  ) : null}
                </p>
              </div>
            ) : isActive ? (
              <div className="px-5 py-5 sm:px-6">
                <OrderProgress order={order} />
              </div>
            ) : null}
          </div>
        </CardContent>

        <CardFooter className="flex-col gap-2.5 border-t border-[#F3F1ED] p-5 sm:flex-row sm:items-center sm:justify-end sm:p-6">
          {canMarkReceived(order.status, order.paymentMethod) && (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={isMarkingReceived}
              onClick={() => onMarkReceived(order)}
              className="w-full gap-1.5 sm:w-auto"
            >
              {isMarkingReceived ? 'Updating…' : 'Mark as received'}
            </Button>
          )}
          {isTrackable(order.status) && (
            <Button type="button" variant="modeza-outline" size="sm" onClick={openTrack} className="w-full gap-1.5 sm:w-auto">
              <Truck className="h-3.5 w-3.5" aria-hidden="true" />
              Track Order
            </Button>
          )}
          <Button type="button" variant="primary" size="sm" onClick={openDetails} className="w-full gap-1.5 sm:w-auto">
            View Order
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </CardFooter>
      </Card>
      <span className="sr-only">
        {statusMeta.label} order, {totalItems} {totalItems === 1 ? 'item' : 'items'}, total {formatPrice(order.total)}.
      </span>
    </article>
  );
};

const OrdersLoadingState: React.FC = () => (
  <div className="space-y-4" role="status" aria-live="polite" aria-label="Loading your orders">
    <Card className="border-[#E8E5DF] p-5 sm:p-6" aria-busy="true">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="font-serif text-lg text-[#181716]">Loading your orders</p>
          <p className="mt-1 text-xs text-[#827E77]">Syncing your order history with MODEZA.</p>
        </div>
        <Badge variant="outline" size="sm">Please wait</Badge>
      </div>
      <Progress value={65} className="mt-5 h-1.5" aria-label="Loading your orders" />
    </Card>
    {Array.from({ length: 3 }).map((_, index) => (
      <Card key={index} className="border-[#E8E5DF] p-5 sm:p-6" aria-hidden="true">
        <div className="animate-pulse">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-2.5">
              <div className="skeleton h-4 w-40" />
              <div className="skeleton h-3 w-32" />
            </div>
            <div className="space-y-2.5">
              <div className="skeleton ml-auto h-5 w-24" />
              <div className="skeleton ml-auto h-3 w-16" />
            </div>
          </div>
          <div className="mt-5 flex items-center gap-2.5">
            {Array.from({ length: 4 }).map((__, thumb) => (
              <div key={thumb} className="skeleton h-16 w-14 sm:h-20 sm:w-[4.5rem]" />
            ))}
          </div>
        </div>
      </Card>
    ))}
    <span className="sr-only">Loading your orders</span>
  </div>
);

export const AccountOrdersPage: React.FC = () => {
  const { navigate } = useRouter();
  const { orders, receiveOrder } = useOrders();

  const [hydratedOrders, setHydratedOrders] = useState<Order[] | null>(null);
  const [syncStatus, setSyncStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [filterKey, setFilterKey] = useState<string>('all');
  const [query, setQuery] = useState('');
  const [pendingReceiptOrder, setPendingReceiptOrder] = useState<Order | null>(null);
  const [isMarkingReceived, setIsMarkingReceived] = useState(false);
  const [receiptError, setReceiptError] = useState('');
  const [receiptSuccess, setReceiptSuccess] = useState('');

  const loadServerOrders = useCallback(async () => {
    setSyncStatus('loading');
    try {
      const response = await api.getOrders();
      setHydratedOrders(response.results.map(mapServerOrder));
      setSyncStatus('done');
    } catch {
      setSyncStatus('error');
    }
  }, []);

  useEffect(() => {
    void loadServerOrders();
  }, [loadServerOrders]);

  const mergedOrders = useMemo<Order[]>(() => {
    // Server is authoritative. Local context holds only this account's
    // per-user cache + offline orders, so prefer the server copy on conflict.
    const seen = new Set<string>();
    const merged: Order[] = [];
    for (const order of [...(hydratedOrders ?? []), ...orders]) {
      const key = order.orderNumber.toUpperCase();
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(order);
    }
    return merged;
  }, [orders, hydratedOrders]);

  const filterTabs = useMemo<{ key: string; label: string; count: number }[]>(() => {
    const statusTabs = STATUS_FILTER_GROUPS.map((group) => ({
      key: group.key,
      label: group.label,
      count: mergedOrders.filter((order) => group.statuses.includes(order.status)).length,
    })).filter((tab) => tab.count > 0);
    return [{ key: 'all', label: 'All', count: mergedOrders.length }, ...statusTabs];
  }, [mergedOrders]);

  const visibleOrders = useMemo(() => {
    let list = mergedOrders;
    if (filterKey !== 'all') {
      const group = STATUS_FILTER_GROUPS.find((entry) => entry.key === filterKey);
      if (group) list = list.filter((order) => group.statuses.includes(order.status));
    }
    const trimmed = query.trim().toLowerCase();
    if (trimmed) {
      list = list.filter(
        (order) =>
          order.orderNumber.toLowerCase().includes(trimmed) ||
          order.items.some((item) => item.productName.toLowerCase().includes(trimmed))
      );
    }
    return [...list].sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt));
  }, [mergedOrders, filterKey, query]);

  const isLoading = syncStatus === 'loading' && mergedOrders.length === 0;
  const showError = syncStatus === 'error' && mergedOrders.length === 0;
  const hasNoOrders = mergedOrders.length === 0 && !showError;

  const clearFilters = () => {
    setQuery('');
    setFilterKey('all');
  };

  const handleConfirmReceipt = async () => {
    if (!pendingReceiptOrder) return;

    setIsMarkingReceived(true);
    setReceiptError('');
    setReceiptSuccess('');
    try {
      const result = await receiveOrder(pendingReceiptOrder.orderNumber);
      if (!result.success || !result.order) {
        setReceiptError(result.message);
        return;
      }

      const receivedOrder = result.order;
      setHydratedOrders((current) =>
        current?.map((order) =>
          order.orderNumber.toUpperCase() === receivedOrder.orderNumber.toUpperCase()
            ? receivedOrder
            : order
        ) ?? null
      );
      setReceiptSuccess(result.message);
    } catch {
      setReceiptError('The order could not be updated right now. Please try again.');
    } finally {
      setIsMarkingReceived(false);
      setPendingReceiptOrder(null);
    }
  };

  return (
    <section className="w-full space-y-7 sm:space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <AccountPageHeader
          eyebrow="Account"
          title="My Orders"
          description="Track your purchases and view your order history."
        />
        <Badge variant="outline" size="lg" className="w-fit gap-2">
          <Package className="h-3.5 w-3.5" aria-hidden="true" />
          {mergedOrders.length} {mergedOrders.length === 1 ? 'order' : 'orders'}
        </Badge>
      </div>

      {receiptError && (
        <div role="alert" className="rounded-xl border border-[#F8B4B4] bg-[#FDF2F2] px-4 py-3 text-sm text-[#9B1C1C]">
          {receiptError}
        </div>
      )}
      {receiptSuccess && (
        <div role="status" className="rounded-xl border border-[#C5D9CB] bg-[#F2F8F4] px-4 py-3 text-sm text-[#2E5A44]">
          {receiptSuccess}
        </div>
      )}

      <div className="space-y-4">
        <Tabs value={filterKey} onValueChange={setFilterKey} className="w-full">
          <TabsList aria-label="Filter orders by status" className="no-scrollbar flex w-full max-w-full justify-start gap-1 overflow-x-auto rounded-full bg-[#F4ECE9] p-1 sm:w-auto">
            {filterTabs.map((tab) => (
              <TabsTrigger key={tab.key} value={tab.key} className="shrink-0 gap-2 text-[11px] tracking-[0.12em]">
                {tab.label}
                <span className="text-[10px] opacity-70">{tab.count}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="relative">
          <Input
            id="orders-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search orders..."
            aria-label="Search orders by order number or product name"
            icon={<Search className="h-4 w-4" aria-hidden="true" />}
            className="h-11 rounded-full bg-white pl-10 pr-11 text-sm"
          />
          {query && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setQuery('')}
              aria-label="Clear search"
              className="absolute right-1.5 top-1/2 h-8 w-8 -translate-y-1/2 text-[#827E77] hover:bg-[#F3F1ED] hover:text-[#181716]"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          )}
        </div>

        {syncStatus === 'loading' && mergedOrders.length > 0 && (
          <div className="flex flex-col gap-2 rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <p className="text-[11px] text-[#827E77]" role="status">Refreshing orders from the modeza…</p>
            <Progress value={70} className="h-1.5 w-full sm:w-32" aria-label="Refreshing your orders" />
          </div>
        )}
      </div>

      <div className="space-y-5">
        {isLoading ? (
          <OrdersLoadingState />
        ) : showError ? (
          <Card className="mx-auto max-w-xl border-[#E8E5DF] p-8 text-center sm:p-12" role="alert">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#FDF2F2] text-[#9E332B]">
              <AlertTriangle className="h-6 w-6" strokeWidth={1.5} aria-hidden="true" />
            </div>
            <Badge variant="destructive" size="sm" className="mt-5">Connection issue</Badge>
            <h2 className="mt-4 font-serif text-2xl text-[#181716]">Something went wrong</h2>
            <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-[#63605A]">We couldn't load your orders right now.</p>
            <Button type="button" variant="outline" size="md" onClick={() => void loadServerOrders()} className="mt-6 gap-2">
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Try Again
            </Button>
          </Card>
        ) : hasNoOrders ? (
          <Card className="mx-auto max-w-xl border-[#E8E5DF] p-8 text-center sm:p-12">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-[#E8E5DF] bg-[#F4ECE9] text-[#A2574F]">
              <ShoppingBag className="h-7 w-7" strokeWidth={1.5} aria-hidden="true" />
            </div>
            <Badge variant="outline" size="sm" className="mt-5">Waiting for your first order</Badge>
            <h2 className="mt-4 font-serif text-2xl text-[#181716]">No orders yet</h2>
            <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-[#63605A]">Your next favorite piece is waiting for you.</p>
            <Button type="button" variant="primary" size="md" onClick={() => navigate('/shop')} className="mt-7 gap-2">
              Start Shopping
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </Card>
        ) : visibleOrders.length === 0 ? (
          <Card className="border-[#E8E5DF] p-8 text-center sm:p-12">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#F4ECE9] text-[#A2574F]">
              <Search className="h-6 w-6" strokeWidth={1.5} aria-hidden="true" />
            </div>
            <Badge variant="outline" size="sm" className="mt-5">No matches</Badge>
            <h2 className="mt-4 font-serif text-2xl text-[#181716]">No matching orders</h2>
            <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-[#63605A]">Try a different search or filter to find what you're looking for.</p>
            <Button type="button" variant="outline" size="sm" onClick={clearFilters} className="mt-6 gap-2">
              <X className="h-3.5 w-3.5" aria-hidden="true" />
              Clear search and filters
            </Button>
          </Card>
        ) : (
          <>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="font-serif text-2xl text-[#181716]">Order history</h2>
              <Badge variant="default" size="sm">{visibleOrders.length} {visibleOrders.length === 1 ? 'result' : 'results'}</Badge>
            </div>
            <div className="space-y-5">
              {visibleOrders.map((order) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  onMarkReceived={(selectedOrder) => {
                    setReceiptError('');
                    setReceiptSuccess('');
                    setPendingReceiptOrder(selectedOrder);
                  }}
                  isMarkingReceived={
                    isMarkingReceived &&
                    pendingReceiptOrder?.orderNumber === order.orderNumber
                  }
                />
              ))}
            </div>
          </>
        )}
      </div>

      <AlertDialog
        open={pendingReceiptOrder !== null}
        onOpenChange={(open) => {
          if (!open && !isMarkingReceived) setPendingReceiptOrder(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm order receipt</AlertDialogTitle>
            <AlertDialogDescription>
              Confirm that you have received {pendingReceiptOrder?.orderNumber}. This will also mark the pay-on-delivery payment as paid.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isMarkingReceived}>Keep order</AlertDialogCancel>
            <AlertDialogAction
              disabled={isMarkingReceived}
              aria-busy={isMarkingReceived}
              onClick={() => void handleConfirmReceipt()}
            >
              {isMarkingReceived ? 'Updating…' : 'Confirm receipt'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
};
