import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { CustomerNotification, ToastMessage } from '../types';
import { ToastContainer } from '../components/ui/Toast';
import { useAuth } from './AuthContext';
import { api } from '../services/apiClient';
import { authClient } from '../services/authClient';

interface NotificationsContextValue {
  notifications: CustomerNotification[];
  unreadCount: number;
  refreshNotifications: () => Promise<void>;
  markAsRead: (notificationId: string) => Promise<void>;
  markAllAsRead: () => Promise<void>;
  notify: (toast: Omit<ToastMessage, 'id'>) => void;
}

const NotificationsContext = createContext<NotificationsContextValue | undefined>(undefined);

export const NotificationsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  const [notifications, setNotifications] = useState<CustomerNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const pollingDisabledRef = useRef(false);
  const refreshInFlightRef = useRef(false);

  const refreshNotifications = useCallback(async () => {
    if (!user || pollingDisabledRef.current || refreshInFlightRef.current) {
      setNotifications([]);
      setUnreadCount(0);
      return;
    }

    refreshInFlightRef.current = true;
    try {
      const session = (await authClient?.getSession())?.data.session;
      if (!session?.access_token) {
        setNotifications([]);
        setUnreadCount(0);
        return;
      }

      const response = await api.getNotifications();
      setNotifications(response.results || []);
      setUnreadCount(typeof response.unread_count === 'number' ? response.unread_count : (response.results || []).filter((item) => !item.isRead).length);
    } catch (error) {
      setNotifications([]);
      setUnreadCount(0);
      if ((error as { status?: number }).status === 401) {
        pollingDisabledRef.current = true;
      }
    } finally {
      refreshInFlightRef.current = false;
    }
  }, [user]);

  useEffect(() => {
    if (!user) {
      setNotifications([]);
      setUnreadCount(0);
      setToasts([]);
      pollingDisabledRef.current = false;
      return;
    }

    void refreshNotifications();
    const timer = window.setInterval(() => {
      void refreshNotifications();
    }, 15000);

    return () => window.clearInterval(timer);
  }, [refreshNotifications, user]);

  // Unread status is independent from popup presentation. Only a notification
  // that is (a) unread AND (b) not yet presented server-side is surfaced once.
  // The server atomically claims `presented_at` via a compare-and-set, so a
  // refresh, page remount or a later poll can never replay the same ID and
  // unread counts remain accurate until the user actually reads.
  const surfaceNewNotifications = useCallback(async () => {
    if (!user) return;
    const candidates = notifications.filter((item) => !item.isRead && !item.presented);
    if (candidates.length === 0) return;

    let presentedIds: string[] = [];
    try {
      const result = await api.markNotificationsPresented(candidates.map((item) => item.id));
      presentedIds = result?.presented ?? [];
    } catch {
      // Claim failed (network). Nothing was surfaced and no state changed, so
      // the next poll simply re-attempts the claim.
      return;
    }
    if (presentedIds.length === 0) return;

    setNotifications((current) => current.map((item) =>
      presentedIds.includes(item.id) ? { ...item, presented: true } : item
    ));

    const newlyPresented = candidates
      .filter((item) => presentedIds.includes(item.id))
      .slice(0, 3);
    if (newlyPresented.length === 0) return;

    setToasts((current) => {
      const nextToasts: ToastMessage[] = newlyPresented.map((item) => ({
        id: item.id,
        type: item.category === 'payment' ? 'success' : 'info',
        title: item.title,
        description: item.message,
      }));
      return [...nextToasts, ...current].slice(0, 4);
    });
  }, [notifications, user]);

  useEffect(() => {
    void surfaceNewNotifications();
  }, [surfaceNewNotifications]);

  const dismissToast = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback((toast: Omit<ToastMessage, 'id'>) => {
    const id = typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `toast_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    setToasts((current) => [{ id, ...toast }, ...current].slice(0, 4));
  }, []);

  useEffect(() => {
    if (toasts.length === 0) return undefined;

    const timers = toasts.map((toast) => window.setTimeout(() => dismissToast(toast.id), 5000));
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [dismissToast, toasts]);

  const markAsRead = useCallback(async (notificationId: string) => {
    try {
      const result = await api.markNotificationRead(notificationId);
      setNotifications((current) => current.map((item) => item.id === notificationId ? { ...item, isRead: true } : item));
      if (typeof result.unread_count === 'number') {
        setUnreadCount(result.unread_count);
      } else {
        setUnreadCount((current) => Math.max(current - 1, 0));
      }
    } catch {
      // ignore failed read-state updates for now
    }
  }, []);

  const markAllAsRead = useCallback(async () => {
    try {
      await api.markAllNotificationsRead();
    } catch {
      // keep local state in sync even if the request fails
    }
    setNotifications((current) => current.map((item) => ({ ...item, isRead: true })));
    setUnreadCount(0);
    setToasts([]);
  }, []);

  return (
    <NotificationsContext.Provider value={{
      notifications,
      unreadCount,
      refreshNotifications,
      markAsRead,
      markAllAsRead,
      notify,
    }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} onMarkAllRead={markAllAsRead} />
    </NotificationsContext.Provider>
  );
};

export const useNotifications = (): NotificationsContextValue => {
  const context = useContext(NotificationsContext);
  if (!context) {
    throw new Error('useNotifications must be used within a NotificationsProvider');
  }
  return context;
};
