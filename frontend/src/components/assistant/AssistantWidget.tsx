import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  AlertCircle,
  Loader2,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { useCart } from '../../context/CartContext';
import { useNotifications } from '../../context/NotificationsContext';
import { useRouter } from '../../router/RouterContext';
import { api } from '../../services/apiClient';
import {
  AssistantAction,
  AssistantApiError,
  AssistantDone,
  AssistantHistoryMessage,
  AssistantProduct,
  AssistantToolInfo,
  clearStoredConversationId,
  fetchAssistantHistory,
  fetchAssistantSuggestions,
  getStoredConversationId,
  storeConversationId,
  streamAssistantMessage,
} from '../../services/assistantClient';
import { Price } from '../ui/Price';

interface WidgetMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  products: AssistantProduct[];
  action: AssistantAction | null;
  streaming: boolean;
  error: string | null;
  unanswered: boolean;
}

let messageSeq = 0;
const nextId = () => `msg_${Date.now()}_${(messageSeq += 1)}`;

function mapHistory(messages: AssistantHistoryMessage[]): WidgetMessage[] {
  return messages.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    products: [],
    action: m.actions?.[0] || null,
    streaming: false,
    error: null,
    unanswered: m.unanswered,
  }));
}

const INLINE_MARKDOWN_TOKEN = /\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)/g;

function renderInlineMarkdown(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let tokenIndex = 0;
  for (const match of text.matchAll(INLINE_MARKDOWN_TOKEN)) {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(text.slice(cursor, start));
    const key = `${keyPrefix}-${tokenIndex++}`;
    if ((token.startsWith('**') && token.endsWith('**')) || (token.startsWith('__') && token.endsWith('__'))) {
      nodes.push(<strong key={key} className="font-semibold">{token.slice(2, -2)}</strong>);
    } else if ((token.startsWith('*') && token.endsWith('*')) || (token.startsWith('_') && token.endsWith('_'))) {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith('`')) {
      nodes.push(<code key={key} className="rounded bg-[#F4F2EE] px-1 py-0.5 font-mono text-[0.9em]">{token.slice(1, -1)}</code>);
    } else {
      const link = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      nodes.push(link
        ? <a key={key} href={link[2]} target="_blank" rel="noopener noreferrer" className="font-medium text-[#4A5D4E] underline underline-offset-2">{link[1]}</a>
        : token);
    }
    cursor = start + token.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function AssistantMessageContent({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    if (!lines[index].trim()) {
      index += 1;
      continue;
    }

    const heading = lines[index].match(/^\s*(#{1,3})\s+(.+)$/);
    if (heading) {
      blocks.push(<h4 key={`heading-${index}`} className="text-sm font-semibold leading-snug">{renderInlineMarkdown(heading[2], `heading-${index}`)}</h4>);
      index += 1;
      continue;
    }

    const listMatch = lines[index].match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
    if (listMatch) {
      const ordered = /^\s*\d+\./.test(lines[index]);
      const items: React.ReactNode[] = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*(?:[-*]|\d+\.)\s+(.+)$/);
        if (!item || /^\s*\d+\./.test(lines[index]) !== ordered) break;
        items.push(<li key={`item-${index}`}>{renderInlineMarkdown(item[1], `item-${index}`)}</li>);
        index += 1;
      }
      const ListTag = ordered ? 'ol' : 'ul';
      blocks.push(<ListTag key={`list-${index}`} className={`my-1 space-y-1 pl-5 ${ordered ? 'list-decimal' : 'list-disc'}`}>{items}</ListTag>);
      continue;
    }

    const start = index;
    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim()) {
      if (paragraph.length && (/^\s*#{1,3}\s+/.test(lines[index]) || /^\s*(?:[-*]|\d+\.)\s+/.test(lines[index]))) break;
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p key={`paragraph-${start}`} className="whitespace-pre-wrap break-words">
        {paragraph.map((line, lineIndex) => (
          <React.Fragment key={`line-${start}-${lineIndex}`}>
            {lineIndex > 0 && <br />}
            {renderInlineMarkdown(line, `paragraph-${start}-${lineIndex}`)}
          </React.Fragment>
        ))}
      </p>,
    );
  }

  return <div className="space-y-2 break-words">{blocks}</div>;
}

export const AssistantWidget: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<WidgetMessage[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [welcome, setWelcome] = useState(
    'Hi! I can help you find pieces, check orders, and answer questions about shipping or returns.',
  );
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeTools, setActiveTools] = useState<AssistantToolInfo[]>([]);
  const [conversationId, setConversationId] = useState(getStoredConversationId());
  const [historyLoaded, setHistoryLoaded] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const { refreshCart, openCartDrawer } = useCart();
  const { notify } = useNotifications();
  const { navigate } = useRouter();

  useEffect(() => {
    let cancelled = false;
    fetchAssistantSuggestions()
      .then((data) => {
        if (cancelled) return;
        if (data.welcome) setWelcome(data.welcome);
        if (data.suggestions?.length) setSuggestions(data.suggestions);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isOpen || historyLoaded) return;
    let cancelled = false;
    const storedId = getStoredConversationId();
    if (storedId) {
      fetchAssistantHistory(storedId)
        .then((history) => {
          if (cancelled) return;
          if (history.length) setMessages(mapHistory(history));
          else clearStoredConversationId();
        })
        .catch(() => clearStoredConversationId())
        .finally(() => !cancelled && setHistoryLoaded(true));
    } else {
      setHistoryLoaded(true);
    }
    return () => {
      cancelled = true;
    };
  }, [isOpen, historyLoaded]);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, activeTools, isOpen]);

  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  const updateMessage = useCallback((id: string, patch: Partial<WidgetMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }, []);

  const appendMessage = useCallback((message: WidgetMessage) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  const send = useCallback(
    async (rawText: string) => {
      const text = rawText.trim();
      if (!text || isStreaming) return;

      setInput('');
      const userMessage: WidgetMessage = {
        id: nextId(),
        role: 'user',
        content: text,
        products: [],
        action: null,
        streaming: false,
        error: null,
        unanswered: false,
      };
      const replyId = nextId();
      appendMessage(userMessage);
      appendMessage({
        id: replyId,
        role: 'assistant',
        content: '',
        products: [],
        action: null,
        streaming: true,
        error: null,
        unanswered: false,
      });

      setIsStreaming(true);
      setActiveTools([]);
      const controller = new AbortController();
      abortRef.current = controller;

      const mutate = (patch: Partial<WidgetMessage>) => updateMessage(replyId, patch);

      try {
        const done: AssistantDone | null = await streamAssistantMessage({
          message: text,
          conversationId: getStoredConversationId() || undefined,
          signal: controller.signal,
          handlers: {
            onMeta: (meta) => {
              if (meta.conversationId) {
                storeConversationId(meta.conversationId);
                setConversationId(meta.conversationId);
              }
            },
            onTool: (tool) => {
              setActiveTools((prev) => [...prev, tool]);
              setTimeout(() => {
                setActiveTools((prev) => prev.filter((t) => t !== tool));
              }, 1500);
            },
            onDelta: (delta) => {
              setMessages((prev) =>
                prev.map((m) => (m.id === replyId ? { ...m, content: m.content + delta } : m)),
              );
            },
            onProducts: (products) => mutate({ products }),
            onAction: (action) => mutate({ action }),
            onError: (error) => {
              mutate({ error: error.message || 'The assistant hit a snag.' });
            },
          },
        });
        mutate({ streaming: false, unanswered: done?.unanswered ?? false });
        if (done?.conversationId) {
          storeConversationId(done.conversationId);
          setConversationId(done.conversationId);
        }
      } catch (error) {
        const message =
          error instanceof AssistantApiError
            ? error.message
            : 'Unable to reach the assistant. Check your connection and try again.';
        mutate({ streaming: false, error: message });
      } finally {
        setIsStreaming(false);
        setActiveTools([]);
        abortRef.current = null;
      }
    },
    [appendMessage, isStreaming, updateMessage],
  );

  const retryLast = useCallback(() => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    if (!lastUser) return;
    setMessages((prev) => {
      const index = prev.findIndex((m) => m.id === lastUser.id);
      return index === -1 ? prev : prev.slice(0, index);
    });
    void send(lastUser.content);
  }, [messages, send]);

  const handleAddToCart = useCallback(
    async (action: AssistantAction) => {
      if (!action.variantId) {
        notify({ type: 'info', title: 'Open the product page', description: 'Choose your size there to add this piece to your bag.' });
        return;
      }
      try {
        await api.addCartItem(action.variantId, action.quantity || 1);
        await refreshCart();
        notify({ type: 'success', title: 'Added to bag', description: `${action.name} · ${action.size}` });
        openCartDrawer();
      } catch (error) {
        notify({
          type: 'error',
          title: 'Could not add to bag',
          description: error instanceof Error ? error.message : 'This size may have just sold out.',
        });
      }
    },
    [notify, openCartDrawer, refreshCart],
  );

  const resetConversation = useCallback(() => {
    abortRef.current?.abort();
    clearStoredConversationId();
    setConversationId('');
    setMessages([]);
    setHistoryLoaded(true);
    setActiveTools([]);
    setIsStreaming(false);
  }, []);

  const canSend = input.trim().length > 0 && !isStreaming;
  const showSuggestions = messages.length === 0 && suggestions.length > 0;

  return (
    <>
      {/* Launcher */}
      <motion.button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={isOpen ? 'Close shopping assistant' : 'Open shopping assistant'}
        aria-expanded={isOpen}
        className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-[#181716] text-[#FAF9F6] shadow-lg transition-transform hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F] focus-visible:ring-offset-2"
        whileTap={{ scale: 0.94 }}
      >
        {isOpen ? <X size={22} /> : <Sparkles size={22} />}
      </motion.button>

      {/* Panel */}
      <AnimatePresence>
        {isOpen && (
          <motion.aside
            key="assistant-panel"
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            role="dialog"
            aria-label="Modeza shopping assistant"
            className="fixed bottom-24 right-4 left-4 z-50 flex h-[min(600px,75vh)] flex-col overflow-hidden rounded-2xl border border-[#E8E5DF] bg-[#FAF9F6] shadow-2xl sm:left-auto sm:right-6 sm:w-[400px]"
          >
            {/* Header */}
            <div className="flex items-center justify-between border-b border-[#E8E5DF] bg-white px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#181716] text-[#FAF9F6]">
                  <Sparkles size={15} />
                </span>
                <div>
                  <p className="text-sm font-semibold leading-tight">Modeza Assistant</p>
                  <p className="text-xs text-[#827E77]">Styling, orders &amp; store help</p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={resetConversation}
                  aria-label="Start a new conversation"
                  className="rounded-full p-2 text-[#827E77] transition-colors hover:bg-[#F4ECE9] hover:text-[#181716]"
                >
                  <Trash2 size={15} />
                </button>
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  aria-label="Close assistant"
                  className="rounded-full p-2 text-[#827E77] transition-colors hover:bg-[#F4ECE9] hover:text-[#181716]"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Messages */}
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
              {messages.length === 0 && (
                <div className="space-y-3">
                  <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-[#E8E5DF] bg-white px-4 py-3 text-sm leading-relaxed text-[#181716]">
                    {welcome}
                  </div>
                  {showSuggestions && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {suggestions.map((suggestion) => (
                        <button
                          key={suggestion}
                          type="button"
                          onClick={() => void send(suggestion)}
                          className="rounded-full border border-[#E8E5DF] bg-white px-3 py-1.5 text-xs text-[#181716] transition-colors hover:border-[#A2574F] hover:text-[#A2574F]"
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex flex-col ${message.role === 'user' ? 'items-end' : 'items-start'}`}
                >
                  <div
                    className={
                      message.role === 'user'
                        ? 'max-w-[85%] rounded-2xl rounded-tr-sm bg-[#181716] px-4 py-2.5 text-sm leading-relaxed text-[#FAF9F6]'
                        : 'max-w-[92%] space-y-2 rounded-2xl rounded-tl-sm border border-[#E8E5DF] bg-white px-4 py-3 text-sm leading-relaxed text-[#181716]'
                    }
                  >
                    {message.content && (message.role === 'assistant'
                      ? <AssistantMessageContent content={message.content} />
                      : <p className="whitespace-pre-wrap break-words">{message.content}</p>)}

                    {message.streaming && !message.content && !message.error && (
                      <span className="inline-flex items-center gap-1.5 text-[#827E77]">
                        <Loader2 size={13} className="animate-spin" />
                        <span className="text-xs">Thinking…</span>
                      </span>
                    )}

                    {message.error && (
                      <div className="flex items-start gap-2 text-[#A2574F]">
                        <AlertCircle size={15} className="mt-0.5 shrink-0" />
                        <p className="text-xs">{message.error}</p>
                      </div>
                    )}

                    {message.products.length > 0 && (
                      <div className="grid grid-cols-2 gap-2 pt-1">
                        {message.products.map((product) => (
                          <button
                            key={product.slug}
                            type="button"
                            onClick={() => {
                              navigate(`/product/${product.slug}`);
                              setIsOpen(false);
                            }}
                            className="group rounded-lg border border-[#E8E5DF] bg-[#FAF9F6] p-2 text-left transition-colors hover:border-[#A2574F]"
                          >
                            <span className="mb-1.5 block h-20 overflow-hidden rounded-md bg-[#F4ECE9]">
                              {product.image && (
                                <img
                                  src={product.image}
                                  alt={product.name}
                                  loading="lazy"
                                  className="h-full w-full object-cover transition-transform group-hover:scale-105"
                                />
                              )}
                            </span>
                            <span className="block truncate text-xs font-medium">{product.name}</span>
                            <Price
                              amount={product.price}
                              {...(product.compareAtPrice ? { compareAtAmount: product.compareAtPrice } : {})}
                              size="xs"
                            />
                            {product.lowStock && (
                              <span className="mt-0.5 block text-[10px] uppercase tracking-wide text-[#A2574F]">
                                Almost gone
                              </span>
                            )}
                          </button>
                        ))}
                      </div>
                    )}

                    {message.action && (
                      <button
                        type="button"
                        onClick={() => void handleAddToCart(message.action as AssistantAction)}
                        className="inline-flex items-center gap-1.5 rounded-full bg-[#181716] px-3.5 py-2 text-xs font-medium text-[#FAF9F6] transition-colors hover:bg-[#A2574F]"
                      >
                        <Plus size={13} />
                        Add to bag · {message.action.size}
                      </button>
                    )}

                    {message.unanswered && !message.streaming && (
                      <p className="text-[11px] text-[#827E77]">
                        Not fully answered — our team will follow up by email.
                      </p>
                    )}
                  </div>

                  {message.error && message.role === 'assistant' && !message.streaming && (
                    <button
                      type="button"
                      onClick={retryLast}
                      className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-[#A2574F] hover:underline"
                    >
                      <RefreshCw size={12} />
                      Retry
                    </button>
                  )}
                </div>
              ))}

              {activeTools.map((tool, index) => (
                <div
                  key={`${tool.name}_${index}`}
                  className="inline-flex items-center gap-1.5 rounded-full border border-[#E8E5DF] bg-white px-3 py-1.5 text-[11px] text-[#827E77]"
                >
                  <Loader2 size={11} className="animate-spin" />
                  {tool.name.replace(/_/g, ' ')}…
                </div>
              ))}
            </div>

            {/* Composer */}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void send(input);
              }}
              className="border-t border-[#E8E5DF] bg-white px-3 py-3"
            >
              <div className="flex items-end gap-2">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      if (canSend) void send(input);
                    }
                  }}
                  rows={1}
                  maxLength={1000}
                  placeholder="Ask about fit, orders, shipping…"
                  aria-label="Message the assistant"
                  className="max-h-28 min-h-[40px] flex-1 resize-none rounded-xl border border-[#E8E5DF] bg-[#FAF9F6] px-3 py-2.5 text-sm text-[#181716] placeholder:text-[#827E77] focus:border-[#A2574F] focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={!canSend}
                  aria-label="Send message"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#181716] text-[#FAF9F6] transition-colors hover:bg-[#A2574F] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {isStreaming ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                </button>
              </div>
              <p className="mt-1.5 px-1 text-[10px] text-[#827E77]">
                AI assistant · replies are generated from modeza&apos;s catalog and store policies.
              </p>
            </form>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
};
