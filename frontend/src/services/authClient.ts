import { supabase } from './supabaseClient';

/**
 * The single place the storefront reads its identity from.
 *
 * `VITE_AUTH_MODE` selects between two implementations:
 *
 *  - `supabase` (default — production): the real Supabase client. Customers
 *    live in Supabase Auth and Django only verifies those JWTs, exactly as
 *    before this module existed.
 *  - `django` (local development): the local Django server's own
 *    `/api/auth/*` endpoints, which read and write the SQLite `auth_user`
 *    table. Sign-up and sign-in then work with nothing running but
 *    `python manage.py runserver` — no Docker, no Supabase project, and no
 *    writes to any production auth store.
 *
 * The Django implementation deliberately mirrors the slice of the Supabase
 * client API that the app actually calls, so `AuthContext`, `apiClient` and
 * the rest can stay agnostic about which one is in play.
 */

export type AuthMode = 'supabase' | 'django';

export type AuthChangeEvent =
  | 'INITIAL_SESSION'
  | 'SIGNED_IN'
  | 'SIGNED_OUT'
  | 'USER_UPDATED'
  | 'PASSWORD_RECOVERY';

export interface AuthUser {
  id: string;
  email: string;
  aud?: string;
  role?: string;
  user_metadata?: Record<string, string | undefined>;
  app_metadata?: Record<string, string>;
  identities?: Array<{ provider?: string; identity_data?: Record<string, unknown> }>;
  created_at?: string | null;
}

export interface AuthSession {
  access_token: string;
  token_type?: string;
  expires_at?: number;
  user: AuthUser;
}

export interface AuthError {
  message: string;
}

interface AuthResult {
  data: { session: AuthSession | null; user: AuthUser | null };
  error: AuthError | null;
}

export interface AuthClient {
  getSession(): Promise<{ data: { session: AuthSession | null }; error: AuthError | null }>;
  getUser(): Promise<{ data: { user: AuthUser | null }; error: AuthError | null }>;
  onAuthStateChange(
    callback: (event: AuthChangeEvent, session: AuthSession | null) => void
  ): { data: { subscription: { unsubscribe(): void } } };
  signInWithPassword(credentials: { email: string; password: string }): Promise<AuthResult>;
  signUp(credentials: {
    email: string;
    password: string;
    options?: { data?: Record<string, string>; emailRedirectTo?: string };
  }): Promise<AuthResult>;
  signOut(): Promise<{ data: Record<string, never>; error: AuthError | null }>;
  refreshSession(): Promise<AuthResult>;
  updateUser(attributes: { password?: string }): Promise<{ data: { user: AuthUser | null }; error: AuthError | null }>;
  resetPasswordForEmail(
    email: string,
    options?: { redirectTo?: string }
  ): Promise<{ data: Record<string, never>; error: AuthError | null }>;
  signInWithOAuth(parameters: {
    provider: string;
    options?: { redirectTo?: string };
  }): Promise<{ data: Record<string, never>; error: AuthError | null }>;
}

const configuredMode = (import.meta.env.VITE_AUTH_MODE || 'supabase').toLowerCase();
export const authMode: AuthMode = configuredMode === 'django' ? 'django' : 'supabase';

// Auth always belongs to the Django backend: catalog data may be served by the
// Express dev server, but accounts live in Django's database in both modes.
const AUTH_BASE_URL = (
  import.meta.env.VITE_DJANGO_API_BASE_URL ||
  import.meta.env.VITE_API_BASE_URL ||
  'http://127.0.0.1:8000'
).replace(/\/$/, '');

const SESSION_STORAGE_KEY = 'modeza_local_auth_session';

type AuthListener = (event: AuthChangeEvent, session: AuthSession | null) => void;

function createDjangoAuthClient(baseUrl: string): AuthClient {
  const listeners = new Set<AuthListener>();

  const emit = (event: AuthChangeEvent, session: AuthSession | null) => {
    listeners.forEach((listener) => {
      try {
        listener(event, session);
      } catch {
        // A misbehaving listener must never break an auth transition.
      }
    });
  };

  const readStoredSession = (): AuthSession | null => {
    if (typeof window === 'undefined') return null;
    try {
      const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
      if (!raw) return null;
      const session = JSON.parse(raw) as AuthSession;
      if (!session?.access_token || !session.user?.id) return null;
      if (session.expires_at && session.expires_at * 1000 <= Date.now()) {
        window.localStorage.removeItem(SESSION_STORAGE_KEY);
        return null;
      }
      return session;
    } catch {
      return null;
    }
  };

  const storeSession = (session: AuthSession | null) => {
    if (typeof window === 'undefined') return;
    if (session) {
      window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
    } else {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    }
  };

  const unreachable = (): AuthError => ({
    message:
      `Could not reach the local Django API at ${baseUrl}. ` +
      'Start it with `python manage.py runserver` from the backend/ folder, ' +
      'then try again.',
  });

  const call = async <T>(
    path: string,
    options: { method?: string; body?: unknown; token?: string } = {}
  ): Promise<{ data: T | null; error: AuthError | null; unauthorized?: boolean }> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (options.token) headers.Authorization = `Bearer ${options.token}`;

    let response: Response;
    try {
      response = await fetch(`${baseUrl}${path}`, {
        method: options.method || 'POST',
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch {
      return { data: null, error: unreachable() };
    }

    if (response.status === 401 || response.status === 403) {
      let message = 'Your session has expired. Please sign in again.';
      try {
        const payload = await response.json();
        message = payload?.error?.message || message;
      } catch {
        // Non-JSON body; keep the generic message.
      }
      return { data: null, error: { message }, unauthorized: true };
    }

    if (!response.ok) {
      let message = `Request failed with status ${response.status}.`;
      try {
        const payload = await response.json();
        message = payload?.error?.message || payload?.detail || message;
      } catch {
        // Non-JSON body; keep the status-derived message.
      }
      return { data: null, error: { message } };
    }

    if (response.status === 204) return { data: null as T, error: null };
    try {
      return { data: (await response.json()) as T, error: null };
    } catch {
      return { data: null as T, error: null };
    }
  };

  const toResult = (payload: { access_token?: string; token_type?: string; user?: AuthUser; expires_at?: number } | null): AuthSession | null => {
    if (!payload?.access_token || !payload.user) return null;
    return {
      access_token: payload.access_token,
      token_type: payload.token_type,
      expires_at: payload.expires_at,
      user: payload.user,
    };
  };

  return {
    async getSession() {
      return { data: { session: readStoredSession() }, error: null };
    },

    async getUser() {
      return { data: { user: readStoredSession()?.user ?? null }, error: null };
    },

    onAuthStateChange(callback) {
      listeners.add(callback);
      // Supabase reports the restored session once on subscription, so mirror
      // that here or components waiting for an event would never settle.
      callback('INITIAL_SESSION', readStoredSession());
      return {
        data: {
          subscription: {
            unsubscribe: () => {
              listeners.delete(callback);
            },
          },
        },
      };
    },

    async signInWithPassword({ email, password }) {
      const { data, error } = await call<{ access_token?: string; user?: AuthUser; expires_at?: number }>(
        '/api/auth/login',
        { body: { email, password } }
      );
      if (error) return { data: { session: null, user: null }, error };

      const session = toResult(data);
      if (!session) {
        return { data: { session: null, user: null }, error: { message: 'Sign-in returned an unexpected response.' } };
      }
      storeSession(session);
      emit('SIGNED_IN', session);
      return { data: { session, user: session.user }, error: null };
    },

    async signUp({ email, password, options }) {
      const { data, error } = await call<{ access_token?: string; user?: AuthUser; expires_at?: number }>(
        '/api/auth/register',
        {
          body: {
            email,
            password,
            fullName: options?.data?.full_name || '',
            phone: options?.data?.phone || '',
          },
        }
      );
      if (error) return { data: { session: null, user: null }, error };

      const session = toResult(data);
      if (!session) {
        return { data: { session: null, user: null }, error: { message: 'Sign-up returned an unexpected response.' } };
      }
      storeSession(session);
      emit('SIGNED_IN', session);
      return { data: { session, user: session.user }, error: null };
    },

    async signOut() {
      const session = readStoredSession();
      storeSession(null);
      // Best effort: the token is stateless, so a server that cannot be
      // reached must still count as signed out in this tab. Fire and forget —
      // sign-out must not wait on the network.
      if (session) {
        void call('/api/auth/logout', { token: session.access_token });
      }
      emit('SIGNED_OUT', null);
      return { data: {} as Record<string, never>, error: null };
    },

    async refreshSession() {
      // Local tokens are long-lived and stateless: there is no refresh
      // exchange, so an unexpired session is simply handed back.
      const session = readStoredSession();
      return { data: { session, user: session?.user ?? null }, error: null };
    },

    async updateUser({ password }) {
      const session = readStoredSession();
      if (!session) {
        return { data: { user: null }, error: { message: 'You must be signed in to change your password.' } };
      }
      if (!password) {
        return { data: { user: session.user }, error: null };
      }

      const { data, error } = await call<{ user?: AuthUser }>('/api/auth/password', {
        method: 'POST',
        body: { password },
        token: session.access_token,
      });
      if (error) return { data: { user: null }, error };

      const user = data?.user ?? session.user;
      const next: AuthSession = { ...session, user };
      storeSession(next);
      emit('USER_UPDATED', next);
      return { data: { user }, error: null };
    },

    async resetPasswordForEmail() {
      return {
        data: {} as Record<string, never>,
        error: {
          message:
            'Password reset emails are not available in local development. ' +
            'Create a new account, or ask an administrator to reset your password.',
        },
      };
    },

    async signInWithOAuth() {
      return {
        data: {} as Record<string, never>,
        error: {
          message:
            'Google sign-in is not available in local development. ' +
            'Use your email and password instead.',
        },
      };
    },
  };
}

const djangoAuthClient = authMode === 'django' ? createDjangoAuthClient(AUTH_BASE_URL) : null;

export const authClient: AuthClient | null =
  authMode === 'django'
    ? djangoAuthClient
    : supabase
      ? (supabase.auth as unknown as AuthClient)
      : null;
