import React from 'react';
import { ArrowRight, Bell, CheckCheck, CheckCircle2, Heart, Package, PackageX, UserRound } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useOrders } from '../context/OrdersContext';
import { useWishlist } from '../context/WishlistContext';
import { useNotifications } from '../context/NotificationsContext';
import { useRouter } from '../router/RouterContext';
import { OrderStatusPill } from '../components/orders/OrderStatusPill';
import { OrderItemThumb } from '../components/orders/OrderItemThumb';
import { AccountPageHeader } from '../components/account/AccountPageHeader';
import { Badge } from '../components/modeza/Badge';
import { Button } from '../components/modeza/Button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/modeza/Card';
import { Progress } from '../components/modeza/Progress';
import { formatPrice } from '../utils/currency';
import { formatOrderDate } from '../utils/orderMapper';
import { isActiveOrder, ORDER_STATUS_META } from '../utils/orderStatus';

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good Morning';
  if (hour < 17) return 'Good Afternoon';
  return 'Good Evening';
}

interface StatCardProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  href: string;
  hint?: string;
}

const StatCard: React.FC<StatCardProps> = ({ label, value, icon, href, hint }) => {
  const { navigate } = useRouter();

  return (
    <Card className="h-full overflow-hidden p-0 shadow-xs transition-transform duration-300 hover:-translate-y-0.5 hover:shadow-md">
      <button
        type="button"
        onClick={() => navigate(href)}
        className="group flex h-full w-full flex-col p-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F] sm:p-5"
      >
        <div className="flex items-start justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase leading-4 tracking-[0.16em] text-[#827E77]">{label}</span>
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#FAF9F6] ring-1 ring-[#E8E5DF]">
            <span className="text-[#A2574F]">{icon}</span>
          </span>
        </div>
        <span className="mt-4 font-serif text-3xl leading-none text-[#181716] sm:text-4xl">
          {String(value).padStart(2, '0')}
        </span>
        <span className="mt-auto inline-flex items-center gap-1.5 pt-4 text-[10px] font-semibold uppercase tracking-[0.14em] text-[#A2574F] transition-colors group-hover:text-[#181716]">
          {hint ?? 'View'}
          <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
        </span>
      </button>
    </Card>
  );
};

export const AccountOverviewPage: React.FC = () => {
  const { navigate } = useRouter();
  const { user, profile, profileLoading, profileError, refreshProfile } = useAuth();
  const { orders } = useOrders();
  const { wishlistCount } = useWishlist();
  const { notifications, unreadCount, markAsRead } = useNotifications();

  const firstName = (profile?.fullName || user?.user_metadata?.full_name || '').split(' ')[0];
  const recentOrders = [...orders]
    .sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt))
    .slice(0, 3);
  const recentNotifications = notifications.slice(0, 3);
  const activeOrders = orders.filter((order) => isActiveOrder(order.status)).length;
  const receivedOrders = orders.filter((order) => order.status === 'received').length;
  const cancelledOrders = orders.filter((order) => order.status === 'cancelled').length;
  const profileComplete = Boolean(profile?.isComplete);
  const profileProgress = profileLoading
    ? 0
    : [profile?.fullName, profile?.phone].filter(Boolean).length * 50;

  return (
    <section className="w-full space-y-8 sm:space-y-9">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <AccountPageHeader
          eyebrow={greeting()}
          title={firstName ? `Welcome back, ${firstName}` : 'Welcome back'}
          description="A glance at your MODEZA — orders, wishlist and the latest from your boutique."
        />
        <Badge variant="outline" size="sm" className="mt-1 gap-1.5">
          <UserRound className="h-3 w-3" aria-hidden="true" />
          Member dashboard
        </Badge>
      </div>

      <Card className={`overflow-hidden shadow-none ${profileComplete ? 'border-[#C8D8CA] bg-[#F8FBF8]' : profileError ? 'border-[#E8E5DF] bg-[#FAF9F6]' : 'border-[#E7D8B3] bg-[#FFFDF8]'}`}>
        <CardContent className="p-5 sm:p-6">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={profileComplete ? 'success' : profileError ? 'default' : 'warning'} size="sm" className="gap-1.5">
                  {profileComplete ? <CheckCircle2 className="h-3 w-3" aria-hidden="true" /> : <UserRound className="h-3 w-3" aria-hidden="true" />}
                  {profileComplete ? 'Profile ready' : profileError ? 'Profile unavailable' : 'Profile setup'}
                </Badge>
                <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#827E77]">{profileError ? 'Status unknown' : `${profileProgress}% complete`}</span>
              </div>
              <h2 className="mt-3 font-serif text-2xl tracking-tight text-[#181716] sm:text-3xl">
                {profileError ? 'Your saved profile could not be checked.' : profileComplete ? 'Your details are ready to shop.' : 'Make checkout feel like yours.'}
              </h2>
              <p className="mt-1.5 max-w-xl text-sm leading-6 text-[#63605A]">
                {profileError
                  ? 'Try loading your account details again to check whether setup is complete.'
                  : profileComplete
                  ? 'Your name and phone are saved for a faster, more personal MODEZA experience.'
                  : 'Add your name and phone number once, then keep your orders and delivery details together.'}
              </p>
            </div>
            <Button
              type="button"
              variant={profileComplete || profileError ? 'outline' : 'primary'}
              size="sm"
              onClick={() => profileError ? void refreshProfile() : navigate(profileComplete ? '/account/profile' : '/account/complete-profile')}
              className="w-full shrink-0 justify-center gap-2 sm:w-auto"
            >
              {profileError ? 'Retry' : profileComplete ? 'View profile' : 'Complete profile'}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          </div>
          <div className="mt-5 flex items-center gap-3">
            <Progress value={profileProgress} className="h-2" aria-label="Profile completion" />
            <span className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#827E77]">
              {profileError ? 'Check connection' : profileComplete ? 'Complete' : profileLoading ? 'Loading' : '2 steps'}
            </span>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-5">
        <StatCard
          label="Active Orders"
          value={activeOrders}
          icon={<Package className="h-4 w-4" />}
          href="/account/orders"
          hint="View orders"
        />
        <StatCard
          label="Received"
          value={receivedOrders}
          icon={<CheckCheck className="h-4 w-4" />}
          href="/account/orders"
          hint="View orders"
        />
        <StatCard
          label="Cancelled"
          value={cancelledOrders}
          icon={<PackageX className="h-4 w-4" />}
          href="/account/orders"
          hint="View orders"
        />
        <StatCard
          label="Wishlist"
          value={wishlistCount}
          icon={<Heart className="h-4 w-4" />}
          href="/wishlist"
          hint="Browse list"
        />
        <StatCard
          label="Notifications"
          value={unreadCount}
          icon={<Bell className="h-4 w-4" />}
          href="/account/notifications"
          hint={unreadCount > 0 ? `${unreadCount} unread` : 'No unread'}
        />
      </div>

      <Card className="overflow-hidden" aria-labelledby="recent-orders-heading">
        <CardHeader className="flex-row items-start justify-between gap-4 border-b border-[#F3F1ED] p-5 sm:p-6">
          <div className="min-w-0">
            <CardTitle id="recent-orders-heading" className="text-xl sm:text-2xl">Recent Orders</CardTitle>
            <CardDescription className="mt-1 text-xs">Your latest pieces, at a glance.</CardDescription>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => navigate('/account/orders')}
            className="shrink-0 gap-1.5 px-2 text-[10px] text-[#A2574F] hover:text-[#181716]"
          >
            View all
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </CardHeader>

        {recentOrders.length === 0 ? (
          <CardContent className="px-6 py-14 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[#FAF9F6] ring-1 ring-[#E8E5DF]">
              <Package className="h-5 w-5 text-[#A2574F]" aria-hidden="true" />
            </div>
            <p className="mt-4 font-serif text-xl text-[#181716]">No orders yet</p>
            <p className="mx-auto mt-1.5 max-w-xs text-sm leading-6 text-[#63605A]">
              Your next favorite piece is waiting for you.
            </p>
            <Button type="button" size="sm" onClick={() => navigate('/shop')} className="mt-5 gap-2">
              Start shopping
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
          </CardContent>
        ) : (
          <CardContent className="p-0">
            <ul className="divide-y divide-[#F3F1ED]">
              {recentOrders.map((order) => {
                const thumb = order.items[0];
                const statusLabel = ORDER_STATUS_META[order.status].label;
                return (
                  <li key={order.id}>
                    <button
                      type="button"
                      onClick={() => navigate(`/account/orders/${encodeURIComponent(order.orderNumber)}`)}
                      aria-label={`View order ${order.orderNumber}, ${statusLabel}`}
                      className="group flex w-full items-center gap-3 px-4 py-4 text-left transition-colors hover:bg-[#FAF9F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F] sm:gap-5 sm:px-6"
                    >
                      {thumb ? (
                        <OrderItemThumb item={thumb} className="h-14 w-12 shrink-0 rounded-lg border border-[#E8E5DF] shadow-xs sm:h-20 sm:w-[4.5rem]" />
                      ) : (
                        <span className="flex h-14 w-12 shrink-0 items-center justify-center rounded-lg border border-[#E8E5DF] bg-[#FAF9F6] text-[#A2574F] sm:h-20 sm:w-[4.5rem]" aria-hidden="true">
                          <Package className="h-5 w-5" />
                        </span>
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-mono text-sm font-semibold text-[#181716]">
                          {order.orderNumber}
                        </div>
                        <div className="mt-0.5 text-xs text-[#827E77]">
                          Placed {formatOrderDate(order.createdAt, { day: 'numeric', month: 'short', year: 'numeric' }) || '—'}
                        </div>
                        <Badge variant="default" size="sm" className="mt-2 sm:hidden">{statusLabel}</Badge>
                      </div>
                      <OrderStatusPill status={order.status} className="hidden sm:inline-flex" />
                      <span className="shrink-0 text-right font-serif text-sm text-[#181716] sm:text-base">
                        {formatPrice(order.total)}
                      </span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-[#A29E96] transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        )}
      </Card>

      <Card className="overflow-hidden" aria-labelledby="latest-notifications-heading">
        <CardHeader className="flex-row items-start justify-between gap-4 border-b border-[#F3F1ED] p-5 sm:p-6">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle id="latest-notifications-heading" className="text-xl sm:text-2xl">Latest Notifications</CardTitle>
              {unreadCount > 0 && <Badge variant="new" size="sm">{unreadCount} unread</Badge>}
            </div>
            <CardDescription className="mt-1 text-xs">Order and account updates from MODEZA.</CardDescription>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => navigate('/account/notifications')}
            className="shrink-0 gap-1.5 px-2 text-[10px] text-[#A2574F] hover:text-[#181716]"
          >
            View all
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </CardHeader>

        {recentNotifications.length === 0 ? (
          <CardContent className="px-6 py-14 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[#FAF9F6] ring-1 ring-[#E8E5DF]">
              <Bell className="h-5 w-5 text-[#A2574F]" aria-hidden="true" />
            </div>
            <p className="mt-4 font-serif text-xl text-[#181716]">You&apos;re all caught up</p>
            <p className="mx-auto mt-1.5 max-w-xs text-sm leading-6 text-[#63605A]">
              We&apos;ll let you know here the moment something happens.
            </p>
          </CardContent>
        ) : (
          <CardContent className="p-0">
            <ul className="divide-y divide-[#F3F1ED]">
              {recentNotifications.map((notification) => (
                <li key={notification.id}>
                  <button
                    type="button"
                    onClick={() => {
                      if (!notification.isRead) void markAsRead(notification.id);
                      if (notification.link) navigate(notification.link);
                    }}
                    aria-label={`${notification.title}${notification.isRead ? '' : ', unread'}`}
                    className={`flex w-full items-start gap-3 px-4 py-4 text-left transition-colors hover:bg-[#FAF9F6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F] sm:px-6 ${notification.isRead ? 'bg-white' : 'bg-[#FFFDF8]'}`}
                  >
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${notification.isRead ? 'bg-[#E8E5DF]' : 'bg-[#A2574F]'}`} aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#827E77]">{notification.category}</p>
                      <p className="mt-0.5 font-medium text-[#181716]">{notification.title}</p>
                      <p className="mt-1 line-clamp-2 text-sm leading-5 text-[#63605A]">{notification.message}</p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      {!notification.isRead && <Badge variant="new" size="sm" className="sm:hidden">New</Badge>}
                      <span className="text-[11px] text-[#A29E96]">
                        {notification.createdAt ? formatOrderDate(notification.createdAt, { day: 'numeric', month: 'short' }) : ''}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </CardContent>
        )}
      </Card>
    </section>
  );
};
