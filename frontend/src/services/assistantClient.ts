import { authClient } from './authClient';
import { getOrCreateCartId } from './apiClient';

// The assistant is served by Django. Gemini is NEVER called from here — the
// API key lives only in backend/.env (see backend/assistant).
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const CONVERSATION_STORAGE_KEY = 'modeza_assistant_conversation_id';

export interface AssistantProduct {
  name: string;
  slug: string;
  price: number;
  compareAtPrice: number | null;
  category: string;
  colours: string[];
  sizes: string[];
  available: boolean;
  lowStock: boolean;
  badges: string[];
  image: string;
  tagline: string;
}

export interface AssistantAction {
  type: 'add_to_cart';
  slug: string;
  name: string;
  price: number;
  quantity: number;
  size: string;
  colour: string;
  variantSku: string;
  variantId: string;
  lowStock: boolean;
}

export interface AssistantToolInfo {
  name: string;
  status: 'ok' | 'error' | 'timeout';
  durationMs: number;
}

export interface AssistantDone {
  messageId: string;
  conversationId: string;
  latencyMs: number;
  usage: Record<string, number>;
  unanswered: boolean;
  toolCount: number;
}

export interface AssistantStreamHandlers {
  onMeta?: (data: { conversationId: string; userMessageId: string }) => void;
  onTool?: (data: AssistantToolInfo) => void;
  onDelta?: (text: string) => void;
  onProducts?: (products: AssistantProduct[]) => void;
  onAction?: (action: AssistantAction) => void;
  onError?: (error: { code: string; message: string }) => void;
}

export class AssistantApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = 'unknown_error', status = 0) {
    super(message);
    this.name = 'AssistantApiError';
    this.code = code;
    this.status = status;
  }
}

export function getStoredConversationId(): string {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(CONVERSATION_STORAGE_KEY) || '';
}

export function storeConversationId(conversationId: string): void {
  if (typeof window === 'undefined' || !conversationId) return;
  localStorage.setItem(CONVERSATION_STORAGE_KEY, conversationId);
}

export function clearStoredConversationId(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(CONVERSATION_STORAGE_KEY);
}

async function authHeaders(): Promise<Headers> {
  const headers = new Headers();
  headers.set('Content-Type', 'application/json');
  headers.set('x-cart-id', getOrCreateCartId());
  try {
    const session = (await authClient?.getSession())?.data.session;
    if (session?.access_token) {
      headers.set('Authorization', `Bearer ${session.access_token}`);
    }
  } catch {
    // Guest chat works without a session token.
  }
  return headers;
}

export interface AssistantSuggestions {
  welcome: string;
  suggestions: string[];
}

export async function fetchAssistantSuggestions(): Promise<AssistantSuggestions> {
  const response = await fetch(`${API_BASE_URL}/api/assistant/suggestions`, {
    headers: await authHeaders(),
    credentials: 'include',
  });
  if (!response.ok) {
    return { welcome: 'Hi! How can I help you shop today?', suggestions: [] };
  }
  return (await response.json()) as AssistantSuggestions;
}

export interface AssistantHistoryMessage {
  id: string;
  role: 'user' | 'assistant';
  kind: 'reply' | 'error';
  content: string;
  productRefs: string[];
  actions: AssistantAction[];
  unanswered: boolean;
  createdAt: string;
}

export async function fetchAssistantHistory(
  conversationId: string,
): Promise<AssistantHistoryMessage[]> {
  if (!conversationId) return [];
  const response = await fetch(
    `${API_BASE_URL}/api/assistant/history?conversationId=${encodeURIComponent(conversationId)}`,
    { headers: await authHeaders(), credentials: 'include' },
  );
  if (!response.ok) {
    clearStoredConversationId();
    return [];
  }
  const payload = (await response.json()) as { messages: AssistantHistoryMessage[] };
  return payload.messages || [];
}

/**
 * POST one message to an SSE chat endpoint and consume the reply incrementally.
 * Resolves with the turn's metadata; rejects with AssistantApiError on
 * transport/HTTP failures. Stream `error` events resolve normally after
 * calling onError (the reply itself failed, the request did not).
 */
async function postChatStream(
  url: string,
  options: {
    message: string;
    conversationId?: string;
    signal?: AbortSignal;
    handlers: AssistantStreamHandlers;
  },
): Promise<AssistantDone | null> {
  const { message, conversationId, signal, handlers } = options;
  const response = await fetch(url, {
    method: 'POST',
    headers: await authHeaders(),
    credentials: 'include',
    signal,
    body: JSON.stringify({
      message,
      stream: true,
      conversationId: conversationId || undefined,
    }),
  });

  if (!response.ok) {
    let code = 'request_failed';
    let errorMessage = 'The assistant is unavailable right now.';
    try {
      const payload = await response.json();
      code = payload?.error?.code || code;
      errorMessage = payload?.error?.message || errorMessage;
    } catch {
      // Non-JSON error body (e.g. HTML error page) — keep the fallback.
    }
    throw new AssistantApiError(errorMessage, code, response.status);
  }

  if (!response.body) {
    throw new AssistantApiError('Streaming is not supported by this browser.',
      'no_stream', 0);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let done: AssistantDone | null = null;
  let finished = false;

  const dispatch = (eventName: string, data: unknown) => {
    switch (eventName) {
      case 'meta':
        handlers.onMeta?.(data as { conversationId: string; userMessageId: string });
        break;
      case 'tool':
        handlers.onTool?.(data as AssistantToolInfo);
        break;
      case 'delta':
        handlers.onDelta?.((data as { text: string }).text || '');
        break;
      case 'products':
        handlers.onProducts?.((data as { products: AssistantProduct[] }).products || []);
        break;
      case 'action':
        handlers.onAction?.(data as AssistantAction);
        break;
      case 'done':
        done = data as AssistantDone;
        finished = true;
        break;
      case 'error':
        handlers.onError?.(data as { code: string; message: string });
        finished = true;
        break;
      default:
        break;
    }
  };

  const processBlock = (block: string) => {
    let eventName = 'message';
    let dataLine = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) eventName = line.slice(7).trim();
      else if (line.startsWith('data: ')) dataLine = line.slice(6);
    }
    if (!dataLine) return;
    try {
      dispatch(eventName, JSON.parse(dataLine));
    } catch {
      // Ignore malformed frames rather than breaking the stream.
    }
  };

  while (!finished) {
    const { value, done: readerDone } = await reader.read();
    if (readerDone) break;
    buffer += decoder.decode(value, { stream: true });
    let separator = buffer.indexOf('\n\n');
    while (separator !== -1) {
      processBlock(buffer.slice(0, separator));
      buffer = buffer.slice(separator + 2);
      if (finished) break;
      separator = buffer.indexOf('\n\n');
    }
  }

  return done;
}

/** Stream a chat turn through the current ``/api/assistant/chat`` endpoint. */
export async function streamAssistantMessage(options: {
  message: string;
  conversationId?: string;
  signal?: AbortSignal;
  handlers: AssistantStreamHandlers;
}): Promise<AssistantDone | null> {
  return postChatStream(`${API_BASE_URL}/api/assistant/chat`, options);
}

/** Stream a chat turn through the new ``/api/ai/chat`` endpoint. */
export async function streamAIMessage(options: {
  message: string;
  conversationId?: string;
  signal?: AbortSignal;
  handlers: AssistantStreamHandlers;
}): Promise<AssistantDone | null> {
  return postChatStream(`${API_BASE_URL}/api/ai/chat`, options);
}

export interface AIHealthReport {
  success: boolean;
  status: string;
  provider: string;
  model: string;
  response: string;
  latencyMs: number;
  updatedAt?: string | null;
  error?: { code: string; message: string } | null;
}

/**
 * Probe ``GET /api/ai/health/`` (public, throttled). Returns `null` if the
 * endpoint or payload is unavailable; never throws.
 */
export async function fetchAIHealth(signal?: AbortSignal): Promise<AIHealthReport | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/ai/health/`, {
      headers: await authHeaders(),
      credentials: 'include',
      signal,
    });
    if (!response.ok) return null;
    return (await response.json()) as AIHealthReport;
  } catch {
    return null;
  }
}
