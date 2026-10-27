import { authClient } from '../services/authClient';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const AUDIT_EVENTS = [
  'signup',
  'login',
  'logout',
  'login_failed',
  'registration_failed',
  'password_reset',
  'password_updated',
  'profile_updated',
  'product_viewed',
  'category_viewed',
  'search_performed',
  'checkout_started',
  'checkout_failed',
  'payment_failed',
  'payment_timeout',
  'refund_requested',
  'wishlist_item_added',
  'wishlist_item_removed',
  'wishlist_cleared',
  'review_submitted',
  'support_message_submitted',
  'security_event',
] as const;

export type AuditClientEvent = (typeof AUDIT_EVENTS)[number];

const REDACTED = '[REDACTED]';
const MAX_STRING_LENGTH = 1000;

const SENSITIVE_PARTS = [
  'password',
  'passwd',
  'token',
  'authorization',
  'secret',
  'api_key',
  'apikey',
  'card',
  'cvv',
  'cvc',
  'pin',
  'otp',
  'ssn',
  'session',
  'phone',
  'email',
];

export function sanitizeAuditValue(value: unknown, key = ''): unknown {
  if (value === null || value === undefined) return value;
  if (typeof value === 'string') {
    const normalized = key.toLowerCase();
    if (SENSITIVE_PARTS.some((part) => normalized.includes(part))) return REDACTED;
    return value.length > MAX_STRING_LENGTH ? value.slice(0, MAX_STRING_LENGTH) : value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeAuditValue(item, key));
  }
  if (typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>)) {
      out[childKey] = sanitizeAuditValue(childValue, childKey);
    }
    return out;
  }
  return value;
}

export async function audit(
  event: AuditClientEvent,
  description?: string,
  context?: Record<string, unknown>,
  data?: Record<string, unknown>
): Promise<void> {
  if (typeof window === 'undefined') return;
  if (!authClient) return;

  try {
    const session = (await authClient.getSession())?.data?.session;
    if (!session?.access_token) return;

    await fetch(`${API_BASE_URL}/api/audit/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        event,
        description,
        context: sanitizeAuditValue(context ?? {}),
        data: sanitizeAuditValue(data ?? {}),
      }),
      keepalive: true,
    });
  } catch {
    // Fire-and-forget: an audit report must never disrupt the storefront.
  }
}