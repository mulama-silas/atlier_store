import React from 'react';
import {
  ArrowRight,
  Bell,
  CheckCircle2,
  Heart,
  Package,
  PackageCheck,
  Sparkles,
  UserRound,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useOrders } from '../context/OrdersContext';
import { useWishlist } from '../context/WishlistContext';
import { useNotifications } from '../context/NotificationsContext';
import { useRouter } from '../router/RouterContext';
import { OrderStatusPill } from '../components/orders/OrderStatusPill';
import { OrderItemThumb } from '../components/orders/OrderItemThumb';
import { Badge } from '../components/modeza/Badge';
import { Button } from '../components/modeza/Button';
import { formatPrice } from '../utils/currency';
import { formatOrderDate } from '../utils/orderMapper';
import { isActiveOrder } from '../utils/orderStatus';

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

interface StatCardProps {
  label: string;
  value: number;
  note: string;
  href: string;
  icon: React.ReactNode;
  tone: string;
}

const StatCard: React.FC<StatCardProps> = ({ label, value, note, href, icon, tone }) => {
  const { navigate } = useRouter();

  return (
    <button
      type="button"
      onClick={() => navigate(href)}
      className="group flex min-h-[152px] flex-col rounded-[22px] border border-[#EAE4DC] bg-white p-5 text-left shadow-[0_8px_24px_rgba(43,34,28,0.035)] transition-all duration-300 hover:-translate-y-1 hover:border-[#D8C7BE] hover:shadow-[0_16px_32px_rgba(43,34,28,0.08)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
    >
      <span className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-[0.19em] text-[#81766D]">{label}</span>
        <span className={`flex h-10 w-10 items-center justify-center rounded-full ${tone}`} aria-hidden="true">{icon}</span>
      </span>
      <span className="mt-5 font-serif text-[2.65rem] leading-none tracking-tight text-[#211D1A]">{value}</span>
      <span className="mt-auto flex items-center justify-between gap-2 pt-3 text-xs text-[#81766D]">
        {note}
        <ArrowRight className="h-4 w-4 text-[#A2574F] transition-transform group-hover:translate-x-1" aria-hidden="true" />
      </span>
    </button>
  );
};

export const AccountOverviewPage: React.FC = () => {
  const { navigate } = useRouter();
  const { user, profile, profileLoading, profileError, refreshProfile } = useAuth();
  const { orders } = useOrders();
  const { wishlistCount } = useWishlist();
  const { notifications, unreadCount, markAsRead } = useNotifications();

  const firstName = (profile?.fullName || user?.user_metadata?.full_name || '').trim().split(/\s+/)[0];
  const email = profile?.email || user?.email || '';
  const initials = firstName ? firstName.slice(0, 1).toUpperCase() : (email.slice(0, 1).toUpperCase() || 'M');
  const recentOrders = [...orders]
    .sort((a, b) => +new Date(b.createdAt) - +new Date(a.createdAt))
    .slice(0, 3);
  const recentNotifications = notifications.slice(0, 3);
  const activeOrders = orders.filter((order) => isActiveOrder(order.status)).length;
  const receivedOrders = orders.filter((order) => order.status === 'received').length;
  const profileComplete = Boolean(profile?.isComplete);
  const profileProgress = profileLoading ? 0 : [profile?.fullName, profile?.phone].filter(Boolean).length * 50;

  return (
    <section className="w-full space-y-6 sm:space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.24em] text-[#A2574F]">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" /> Your MODEZA space
          </p>
          <h1 className="font-serif text-3xl tracking-tight text-[#211D1A] sm:text-[2.65rem]">
            {firstName ? `${greeting()}, ${firstName}` : `${greeting()}, welcome back`}
          </h1>
          <p className="mt-2 text-sm leading-6 text-[#746B64]">Your wardrobe, orders and account details, all in one place.</p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/account/profile')}
          className="hidden items-center gap-3 rounded-full border border-[#EAE4DC] bg-white py-1.5 pl-1.5 pr-4 shadow-xs transition hover:border-[#D8C7BE] sm:flex"
          aria-label="View personal information"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[#EDE2DA] font-serif text-lg text-[#754B40]">{initials}</span>
          <span className="text-left">
            <span className="block max-w-[180px] truncate text-xs font-semibold text-[#211D1A]">{firstName || 'MODEZA member'}</span>
            <span className="block max-w-[180px] truncate text-[11px] text-[#81766D]">{email || 'Personal account'}</span>
          </span>
        </button>
      </header>

      <div className="relative isolate overflow-hidden rounded-[28px] bg-[#29211D] shadow-[0_20px_55px_rgba(45,31,25,0.16)]">
        <div
          className="absolute inset-0 -z-10 bg-cover bg-[center_38%] opacity-70"
          style={{ backgroundImage: "url('https://images.unsplash.com/photo-1515372039744-b8f02a3ae446?q=80&w=1800&auto=format&fit=crop')" }}
          aria-hidden="true"
        />
        <div className="absolute inset-0 -z-10 bg-gradient-to-r from-[#201916]/95 via-[#2A211D]/78 to-[#2A211D]/15" aria-hidden="true" />
        <div className="grid min-h-[300px] items-end gap-8 p-6 sm:min-h-[330px] sm:p-9 lg:grid-cols-[1fr_280px] lg:items-center lg:p-11">
          <div className="max-w-xl self-center text-white">
            <Badge variant="outline" size="sm" className="border-white/35 bg-white/10 text-white backdrop-blur-sm">
              <Sparkles className="mr-1.5 h-3 w-3" aria-hidden="true" /> Your member edit
            </Badge>
            <h2 className="mt-5 max-w-lg font-serif text-3xl leading-[1.08] tracking-tight sm:text-4xl lg:text-[3.2rem]">
              A little more room for what you love.
            </h2>
            <p className="mt-3 max-w-md text-sm leading-6 text-white/75">
              Keep your favourite pieces close, follow every delivery and make your next visit feel effortless.
            </p>
            <Button type="button" size="md" onClick={() => navigate('/shop')} className="mt-6 gap-2 bg-[#F3E4D8] text-[#30231E] hover:bg-white">
              Explore the collection <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>

          <div className="rounded-[22px] border border-white/20 bg-[#201916]/65 p-5 text-white shadow-lg backdrop-blur-md sm:p-6">
            <div className="flex items-center justify-between gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-[#F0C6B8]" aria-hidden="true">
                {profileComplete ? <CheckCircle2 className="h-5 w-5" /> : <UserRound className="h-5 w-5" />}
              </span>
              <Badge variant="outline" size="sm" className="border-white/25 text-white/85">
                {profileComplete ? 'Profile ready' : profileError ? 'Status unavailable' : 'Member details'}
              </Badge>
            </div>
            <p className="mt-5 font-serif text-xl">{profileComplete ? 'All set for checkout' : 'Make it yours'}</p>
            <p className="mt-1.5 text-xs leading-5 text-white/65">
              {profileError
                ? 'We could not check your saved details.'
                : profileComplete
                  ? 'Your contact details are saved for a smoother checkout.'
                  : 'Add your name and phone to make checkout quicker.'}
            </p>
            <div className="mt-5 flex items-center gap-3">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/15" role="progressbar" aria-valuenow={profileProgress} aria-valuemin={0} aria-valuemax={100} aria-label="Profile completion">
                <div className="h-full rounded-full bg-[#E3AC96] transition-all" style={{ width: `${profileProgress}%` }} />
              </div>
              <span className="text-[10px] font-medium tabular-nums text-white/70">{profileLoading ? '…' : `${profileProgress}%`}</span>
            </div>
            <button
              type="button"
              onClick={() => profileError ? void refreshProfile() : navigate(profileComplete ? '/account/profile' : '/account/complete-profile')}
              className="mt-5 inline-flex items-center gap-2 text-xs font-semibold text-[#F0C6B8] transition hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            >
              {profileError ? 'Try again' : profileComplete ? 'View personal details' : 'Complete your profile'}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
        <StatCard label="In motion" value={activeOrders} note="Orders on their way" href="/account/orders" icon={<Package className="h-[18px] w-[18px] text-[#8A5D4C]" />} tone="bg-[#F4EAE3]" />
        <StatCard label="Delivered" value={receivedOrders} note="Pieces in your hands" href="/account/orders" icon={<PackageCheck className="h-[18px] w-[18px] text-[#55715A]" />} tone="bg-[#E9F0E8]" />
        <StatCard label="Saved pieces" value={wishlistCount} note="Your considered edit" href="/wishlist" icon={<Heart className="h-[18px] w-[18px] text-[#A2574F]" />} tone="bg-[#F7E9E9]" />
        <StatCard label="Updates" value={unreadCount} note={unreadCount ? 'Waiting to be read' : 'You’re all caught up'} href="/account/notifications" icon={<Bell className="h-[18px] w-[18px] text-[#78618B]" />} tone="bg-[#F0EBF4]" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(280px,0.8fr)]">
        <section className="overflow-hidden rounded-[24px] border border-[#EAE4DC] bg-white shadow-[0_8px_24px_rgba(43,34,28,0.035)]" aria-labelledby="recent-orders-heading">
          <div className="flex items-end justify-between gap-4 border-b border-[#F0ECE7] px-5 py-5 sm:px-6">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">Your purchases</p>
              <h2 id="recent-orders-heading" className="mt-1 font-serif text-2xl text-[#211D1A]">Recent orders</h2>
            </div>
            <button type="button" onClick={() => navigate('/account/orders')} className="group inline-flex items-center gap-1.5 pb-1 text-xs font-semibold text-[#8C5047] hover:text-[#211D1A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]">
              All orders <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </button>
          </div>

          {recentOrders.length === 0 ? (
            <div className="flex min-h-[265px] flex-col items-center justify-center px-6 py-10 text-center">
              <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#F5EEE8] text-[#9A6858]" aria-hidden="true"><Package className="h-6 w-6" /></span>
              <h3 className="mt-4 font-serif text-xl text-[#211D1A]">Your story starts here</h3>
              <p className="mt-1.5 max-w-xs text-sm leading-6 text-[#81766D]">Once you place an order, we’ll keep its details and delivery updates here.</p>
              <Button type="button" size="sm" onClick={() => navigate('/shop')} className="mt-5 gap-2">Find your next favourite <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Button>
            </div>
          ) : (
            <ul className="divide-y divide-[#F0ECE7]">
              {recentOrders.map((order) => {
                const thumb = order.items[0];
                return (
                  <li key={order.id}>
                    <button
                      type="button"
                      onClick={() => navigate(`/account/orders/${encodeURIComponent(order.orderNumber)}`)}
                      aria-label={`View order ${order.orderNumber}`}
                      className="group flex w-full items-center gap-3 px-4 py-4 text-left transition-colors hover:bg-[#FCFAF8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F] sm:gap-4 sm:px-6"
                    >
                      {thumb ? <OrderItemThumb item={thumb} className="h-[68px] w-[56px] shrink-0 rounded-xl" /> : <span className="flex h-[68px] w-[56px] shrink-0 items-center justify-center rounded-xl bg-[#F5EEE8] text-[#9A6858]"><Package className="h-5 w-5" /></span>}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium text-[#211D1A]">{thumb?.productName || 'MODEZA order'}</span>
                        <span className="mt-1 block truncate font-mono text-[10px] text-[#91867D]">{order.orderNumber}</span>
                        <span className="mt-1 block text-[11px] text-[#81766D]">{formatOrderDate(order.createdAt, { day: 'numeric', month: 'short', year: 'numeric' }) || 'Date unavailable'}</span>
                      </span>
                      <span className="hidden sm:block"><OrderStatusPill status={order.status} /></span>
                      <span className="shrink-0 text-right">
                        <span className="block font-serif text-base text-[#211D1A]">{formatPrice(order.total)}</span>
                        <span className="mt-1 block text-[10px] text-[#91867D] sm:hidden">{order.status}</span>
                      </span>
                      <ArrowRight className="h-4 w-4 shrink-0 text-[#B3A79D] transition-transform group-hover:translate-x-0.5 group-hover:text-[#A2574F]" aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="overflow-hidden rounded-[24px] border border-[#EAE4DC] bg-[#F8F4EF]" aria-labelledby="latest-notifications-heading">
          <div className="flex items-end justify-between gap-3 border-b border-[#EAE4DC] px-5 py-5 sm:px-6">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-[#A2574F]">A note for you</p>
              <div className="mt-1 flex items-center gap-2">
                <h2 id="latest-notifications-heading" className="font-serif text-2xl text-[#211D1A]">Latest updates</h2>
                {unreadCount > 0 && <Badge variant="new" size="sm">{unreadCount}</Badge>}
              </div>
            </div>
            <button type="button" onClick={() => navigate('/account/notifications')} className="group inline-flex items-center gap-1 text-xs font-semibold text-[#8C5047] hover:text-[#211D1A] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]">
              See all <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </button>
          </div>

          {recentNotifications.length === 0 ? (
            <div className="flex min-h-[265px] flex-col items-center justify-center px-6 py-10 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white text-[#9A6858] shadow-xs" aria-hidden="true"><Bell className="h-5 w-5" /></span>
              <h3 className="mt-4 font-serif text-xl text-[#211D1A]">Nothing new, for now</h3>
              <p className="mt-1.5 max-w-[240px] text-sm leading-6 text-[#81766D]">Order milestones and account notes will appear here.</p>
            </div>
          ) : (
            <ul className="divide-y divide-[#EAE4DC]">
              {recentNotifications.map((notification) => (
                <li key={notification.id}>
                  <button
                    type="button"
                    onClick={() => {
                      if (!notification.isRead) void markAsRead(notification.id);
                      if (notification.link) navigate(notification.link);
                    }}
                    className="group flex w-full items-start gap-3 px-5 py-4 text-left transition-colors hover:bg-white/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#A2574F] sm:px-6"
                  >
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${notification.isRead ? 'bg-[#D8CEC5]' : 'bg-[#A2574F]'}`} aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-[#302822]">{notification.title}</span>
                        <span className="shrink-0 text-[10px] text-[#9A8F86]">{notification.createdAt ? formatOrderDate(notification.createdAt, { day: 'numeric', month: 'short' }) : ''}</span>
                      </span>
                      <span className="mt-1 block line-clamp-2 text-xs leading-5 text-[#786E66]">{notification.message}</span>
                    </span>
                    <ArrowRight className="mt-1 h-3.5 w-3.5 shrink-0 text-[#B3A79D] opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </section>
  );
};
