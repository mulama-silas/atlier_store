"""Turn orchestration: persistence, streaming events, audit, insights.

``run_message`` is a generator the HTTP layer consumes — no threads, no
queues. Event protocol (SSE ``event:`` names):

    meta     {conversationId, userMessageId}
    tool     {name, status, durationMs}          (repeatable)
    delta    {text}                              (repeatable)
    products {products: [...]}                   (at most once, before done)
    action   {type, slug, ...}                   (repeatable, before done)
    done     {messageId, latencyMs, usage, ...}  (terminal, success)
    error    {code, message}                     (terminal, friendly only)

Raw Gemini errors never reach the customer: they become ``error`` events
with the friendly copy from ``constants`` while the details are logged and
audited.
"""
import logging
import re
import time

from django.db import transaction
from django.utils import timezone

from audit.services import AuditLogService

from ..constants import (FRIENDLY_BLOCKED, FRIENDLY_ERROR,
                         MAX_HISTORY_MESSAGES, MAX_MESSAGE_LENGTH,
                         SYSTEM_PROMPT, UNANSWERED_MARKER)
from ..models import (AssistantConversation, AssistantInsight,
                      AssistantMessage, AssistantToolCall)
from . import gemini, tools as tools_module
from .gemini import GeminiError

logger = logging.getLogger('modeza.assistant')

MAX_PRODUCT_CARDS = 6
MAX_ACTIONS = 3

_PRODUCT_REQUEST_RE = re.compile(
    r'\b(?:need|want|looking\s+for|find|show\s+me|recommend|'
    r'do\s+you\s+have|have\s+you\s+got|do\s+you\s+sell|'
    r'is\s+there|are\s+there|can\s+i\s+get|could\s+i\s+get|'
    r'could\s+you\s+find|i[\'’]d\s+like|would\s+like|'
    r'carry|stock|available|shopping\s+for|search\s+for|buy)\b',
    re.IGNORECASE,
)
_NON_PRODUCT_REQUEST_RE = re.compile(
    r'\b(?:order|delivery|shipment|tracking|refund|return|payment|receipt)\b',
    re.IGNORECASE,
)
_PRODUCT_QUERY_FILLER = {
    'a', 'an', 'and', 'any', 'are', 'available', 'buy', 'can', 'carry', 'do',
    'find', 'for', 'get', 'got', 'have', 'i', 'in', 'is', 'looking', 'me', 'need',
    'of', 'please', 'recommend', 'search', 'sell', 'show', 'some', 'stock',
    'help', 'the', 'there', 'to', 'want', 'would', 'could', 'like', 'you',
    'under', 'below', 'less',
    'than', 'up', 'at', 'most', 'over', 'above', 'more', 'least', 'price',
    'kes', 'size', 'color', 'colour',
}
_PRODUCT_COLOURS = {
    'beige', 'black', 'blue', 'brown', 'cream', 'gold', 'green', 'grey',
    'gray', 'ivory', 'navy', 'orange', 'pink', 'purple', 'red', 'silver',
    'tan', 'white', 'yellow',
}

_TOOL_RECORD_STATUS = {
    'ok': AssistantToolCall.Status.OK,
    'error': AssistantToolCall.Status.ERROR,
    'timeout': AssistantToolCall.Status.TIMEOUT,
}

_WHITESPACE_RE = re.compile(r'\s+')


# ---------------------------------------------------------------------------
# Conversation lookup / history
# ---------------------------------------------------------------------------

def get_or_create_conversation(*, user=None, session_key='', conversation_id=None):
    """Return the conversation for this customer, creating it if needed.

    * Signed-in customers are bound to their user id (strong ownership).
    * Guests resume a conversation by presenting its UUID (possession of the
      random UUID is the capability); a guest id never hands over a
      user-bound conversation.
    * A guest conversation is claimed by the first signed-in customer who
      uses it.
    """
    authenticated = bool(user is not None and getattr(user, 'is_authenticated', False))

    if conversation_id:
        conversation = AssistantConversation.objects.filter(
            pk=conversation_id).first()
        if conversation is not None:
            foreign_guest_thread = bool(
                conversation.session_key and session_key
                and conversation.session_key != session_key)
            if authenticated:
                if conversation.user_id == user.pk:
                    return conversation, False
                if conversation.user_id is None and not foreign_guest_thread:
                    # The guest signed in: attach their thread to the account.
                    conversation.user = user
                    conversation.session_key = ''
                    conversation.save(update_fields=['user', 'session_key',
                                                     'updated_at'])
                    return conversation, False
            elif conversation.user_id is None and not foreign_guest_thread:
                if session_key and not conversation.session_key:
                    conversation.session_key = session_key
                    conversation.save(update_fields=['session_key',
                                                     'updated_at'])
                elif (session_key and conversation.session_key
                        and conversation.session_key != session_key):
                    pass  # unreachable: covered by foreign_guest_thread
                return conversation, False

    conversation = AssistantConversation.objects.create(
        user=user if authenticated else None,
        session_key='' if authenticated else (session_key or ''),
    )
    return conversation, True


def build_replay_input(conversation, new_text):
    """Full server-side history (used when the Gemini chain id went stale)."""
    messages = list(
        conversation.messages.filter(kind=AssistantMessage.Kind.REPLY)
        .order_by('-created_at')[:MAX_HISTORY_MESSAGES])
    steps = []
    for message in reversed(messages):
        if not message.content:
            continue
        step_type = ('user_input' if message.role == AssistantMessage.Role.USER
                     else 'model_output')
        steps.append({'type': step_type,
                      'content': [{'type': 'text', 'text': message.content}]})
    steps.append({'type': 'user_input',
                  'content': [{'type': 'text', 'text': new_text}]})
    return steps


# ---------------------------------------------------------------------------
# Unanswered-marker tail buffer
# ---------------------------------------------------------------------------

class MarkerFilter:
    """Holds back a streamed tail that could be the start of
    ``[[UNANSWERED]]`` so the marker is never shown to the customer."""

    def __init__(self, marker=UNANSWERED_MARKER):
        self.marker = marker
        self._buf = ''
        self.found = False

    def feed(self, chunk):
        if not chunk:
            return ''
        self._buf += chunk
        if self.marker and self.marker in self._buf:
            self.found = True
            self._buf = self._buf.replace(self.marker, '')
        for size in range(min(len(self.marker) - 1, len(self._buf)), 0, -1):
            if self._buf.endswith(self.marker[:size]):
                safe, self._buf = self._buf[:-size], self._buf[-size:]
                return safe
        safe, self._buf = self._buf, ''
        return safe

    def flush(self):
        if not self._buf:
            return ''
        held, self._buf = self._buf, ''
        if self.marker and (held == self.marker or
                            (len(held) < len(self.marker) and
                             self.marker.startswith(held))):
            # The model stopped mid-marker: treat it as an unanswered flag.
            self.found = True
            return ''
        return held


# ---------------------------------------------------------------------------
# Insights (aggregated, admin analytics)
# ---------------------------------------------------------------------------

def record_insight(kind, text, limit=500):
    text = _WHITESPACE_RE.sub(' ', (text or '')).strip()[:limit]
    if not text:
        return
    normalized = text.lower()
    try:
        with transaction.atomic():
            insight, created = AssistantInsight.objects.get_or_create(
                kind=kind, normalized=normalized, defaults={'text': text})
            if not created:
                AssistantInsight.objects.filter(pk=insight.pk).update(
                    count=insight.count + 1, last_seen=timezone.now())
    except Exception:  # noqa: BLE001 - analytics must never break a reply
        logger.warning('assistant: failed to record insight', exc_info=True)


# ---------------------------------------------------------------------------
# Tool-event handling
# ---------------------------------------------------------------------------

def _result_summary(execution):
    payload = execution.payload
    if execution.status != 'ok':
        return {'error': execution.error_code or 'tool_error'}
    if not isinstance(payload, dict):
        return {}
    summary = {}
    for key in ('total', 'count', 'valid', 'ok'):
        if key in payload and payload[key] is not None:
            summary[key] = payload[key]
    return summary


def _handle_tool(state, execution, context):
    """Persist/audit one tool execution; return the public tool event."""
    payload = execution.payload if isinstance(execution.payload, dict) else {}
    record = {
        'tool_name': execution.name,
        'arguments': dict(execution.arguments or {}),
        'result_summary': _result_summary(execution),
        'status': _TOOL_RECORD_STATUS.get(execution.status,
                                          AssistantToolCall.Status.ERROR),
        'error_code': execution.error_code or '',
        'duration_ms': execution.duration_ms or 0,
    }
    state['tools'].append(record)

    AuditLogService.log(
        'assistant_tool_called',
        object_type='assistant_tool',
        metadata={'name': execution.name, 'status': execution.status,
                  'durationMs': execution.duration_ms},
        description=f'Assistant tool {execution.name} executed.')
    if execution.status != 'ok':
        AuditLogService.log(
            'assistant_tool_failed',
            object_type='assistant_tool',
            metadata={'name': execution.name, 'status': execution.status,
                      'errorCode': execution.error_code},
            description=f'Assistant tool {execution.name} failed.')

    args = execution.arguments or {}

    if execution.name in ('search_products', 'compare_products'):
        products = [p for p in payload.get('products', [])
                    if isinstance(p, dict) and p.get('slug')]
        for product in products[:MAX_PRODUCT_CARDS]:
            if product['slug'] not in state['product_slugs']:
                state['product_slugs'].append(product['slug'])
                state['products'].append(product)
        if execution.name == 'search_products':
            if payload.get('total') == 0:
                record_insight(
                    AssistantInsight.Kind.ZERO_RESULT,
                    ' '.join(str(args.get(k, '')) for k in
                             ('query', 'colour', 'category', 'occasion')).strip()
                    or 'no keywords')
            elif products:
                AuditLogService.log(
                    'assistant_product_recommended',
                    object_type='product',
                    metadata={'count': len(products),
                              'slugs': state['product_slugs'][:10]},
                    description='Assistant recommended products to a customer.')

    if execution.name in ('get_order_status', 'get_customer_orders'):
        AuditLogService.log(
            'assistant_order_lookup',
            object_type='order',
            metadata={'orderNumber': str(args.get('order_number', ''))[:40],
                      'found': 'error' not in payload,
                      'errorCode': (payload.get('error') or {}).get('code', '')},
            description='Assistant looked up an order for a customer.')

    if execution.name == 'create_support_request' and payload.get('ok'):
        record_insight(AssistantInsight.Kind.ESCALATION,
                       str(args.get('message', ''))[:300])
        AuditLogService.log(
            'assistant_escalated',
            object_type='assistant_conversation',
            object_id=str(state['conversation_id']),
            metadata={'orderNumber': str(args.get('order_number', ''))[:40]},
            description='Assistant escalated an issue to support staff.')

    action = payload.get('action')
    if execution.name == 'prepare_add_to_cart' and isinstance(action, dict):
        if len(state['actions']) < MAX_ACTIONS:
            state['actions'].append(action)

    return {'name': execution.name, 'status': execution.status,
            'durationMs': execution.duration_ms or 0}


def _catalog_search_for_message(text):
    """Extract supported live-catalog filters from a shopping query."""
    if (_NON_PRODUCT_REQUEST_RE.search(text)
            or not _PRODUCT_REQUEST_RE.search(text)):
        return None
    normalized = re.sub(r"\bmen['’]s\b", 'men', text, flags=re.IGNORECASE)
    normalized = re.sub(r"\bwomen['’]s\b", 'women', normalized,
                        flags=re.IGNORECASE)
    normalized = re.sub(r'\bmens\b', 'men', normalized, flags=re.IGNORECASE)
    normalized = re.sub(r'\bwomens\b', 'women', normalized,
                        flags=re.IGNORECASE)

    filters = {'limit': MAX_PRODUCT_CARDS}
    price_patterns = (
        (r'\b(?:under|below|less\s+than|up\s+to|at\s+most)\s+(?:kes\s*)?([\d,]+)',
         'max_price_kes'),
        (r'\b(?:over|above|more\s+than|at\s+least)\s+(?:kes\s*)?([\d,]+)',
         'min_price_kes'),
    )
    for pattern, key in price_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            filters[key] = int(match.group(1).replace(',', ''))
            normalized = normalized[:match.start()] + normalized[match.end():]

    size_match = re.search(
        r'\bsize\s+(extra\s+small|extra\s+large|xxs|xs|small|medium|'
        r'large|s|m|l|xl|xxl|\d{1,2})\b',
        normalized, flags=re.IGNORECASE)
    if size_match:
        size = size_match.group(1).lower()
        filters['size'] = {
            'extra small': 'XS', 'small': 'S', 'medium': 'M',
            'large': 'L', 'extra large': 'XL',
        }.get(size, size.upper())
        normalized = normalized[:size_match.start()] + normalized[size_match.end():]

    terms = re.findall(r'[a-z0-9]+', normalized.lower())
    for term in terms:
        if term in _PRODUCT_COLOURS:
            filters['colour'] = term
            terms.remove(term)
            break
    query = ' '.join(term for term in terms
                     if term not in _PRODUCT_QUERY_FILLER)
    if not query and len(filters) == 1:
        return None
    if query:
        filters['query'] = query
    return query or text.strip(), filters


def _live_catalog_reply(query, payload):
    products = payload.get('products') or []
    if not products:
        return (f'I checked the current catalog but could not find an in-stock '
                f'match for “{query}”. Try another style, category, colour, '
                'or search term.')

    lines = [f'Here are current in-stock matches for “{query}”:']
    for product in products[:4]:
        price = product.get('price')
        try:
            formatted_price = f"KES {float(price):,.0f}"
        except (TypeError, ValueError):
            formatted_price = 'Price shown on the product page'
        details = []
        if product.get('colours'):
            details.append('colours: ' + ', '.join(product['colours']))
        if product.get('sizes'):
            details.append('sizes: ' + ', '.join(product['sizes']))
        suffix = f" ({'; '.join(details)})" if details else ''
        lines.append(f"- **{product.get('name', 'Product')}** — {formatted_price}{suffix}")
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persist_turn(conversation, state, started):
    """Write the assistant message + tool rows once, at the end of a turn."""
    if state['saved']:
        return None
    state['saved'] = True
    latency_ms = int((time.monotonic() - started) * 1000)
    error = state.get('error')
    message = AssistantMessage.objects.create(
        conversation=conversation,
        role=AssistantMessage.Role.ASSISTANT,
        kind=(AssistantMessage.Kind.ERROR if error
              else AssistantMessage.Kind.REPLY),
        content=(error['message'] if error else state['text'].strip()),
        product_refs=list(state['product_slugs']),
        actions=[a for a in state['actions']],
        unanswered=state['unanswered'],
        latency_ms=latency_ms,
        usage=dict(state['usage']),
    )
    for record in state['tools']:
        try:
            AssistantToolCall.objects.create(
                conversation=conversation, message=message, **record)
        except Exception:  # noqa: BLE001 - analytics rows are best-effort
            logger.warning('assistant: failed to store tool call',
                           exc_info=True)
    if state.get('clear_interaction_id'):
        conversation.last_interaction_id = ''
    elif state.get('interaction_id'):
        conversation.last_interaction_id = state['interaction_id']
    conversation.message_count += 1
    conversation.save(update_fields=['last_interaction_id', 'message_count',
                                     'updated_at'])

    AuditLogService.log(
        'assistant_message_sent',
        object_type='assistant_conversation',
        object_id=str(conversation.pk),
        result='failure' if error else 'success',
        metadata={'conversationId': str(conversation.pk),
                  'messageId': str(message.pk),
                  'latencyMs': latency_ms,
                  'stream': bool(state['stream']),
                  'tools': [t['tool_name'] for t in state['tools']],
                  'toolErrors': [t['tool_name'] for t in state['tools']
                                 if t['status'] != AssistantToolCall.Status.OK],
                  'unanswered': state['unanswered'],
                  'productCount': len(state['products']),
                  'hasAction': bool(state['actions']),
                  'errorCode': (error or {}).get('code', '')},
        description=('Assistant failed to answer a customer message.'
                     if error else
                     'Assistant answered a customer message.'))
    return message


# ---------------------------------------------------------------------------
# The turn
# ---------------------------------------------------------------------------

def run_message(conversation, text, context, *, stream=True):
    """Run one customer message; yields ``(event, data)`` tuples."""
    started = time.monotonic()
    user_text = (text or '').strip()[:MAX_MESSAGE_LENGTH]
    if not user_text:
        yield ('error', {'code': 'empty_message',
                         'message': 'Please type a message.'})
        return

    user_message = AssistantMessage.objects.create(
        conversation=conversation, role=AssistantMessage.Role.USER,
        content=user_text)
    conversation.message_count += 1
    conversation.save(update_fields=['message_count', 'updated_at'])
    if conversation.message_count == 1:
        AuditLogService.log(
            'assistant_conversation_started',
            object_type='assistant_conversation',
            object_id=str(conversation.pk),
            metadata={'conversationId': str(conversation.pk)},
            description='Customer started an assistant conversation.')

    state = {
        'text': '', 'tools': [], 'products': [], 'product_slugs': [],
        'actions': [], 'usage': {}, 'interaction_id': '',
        'unanswered': False, 'stream': stream, 'saved': False,
        'conversation_id': str(conversation.pk), 'error': None,
    }
    marker = MarkerFilter()

    yield ('meta', {'conversationId': str(conversation.pk),
                    'userMessageId': str(user_message.pk)})

    def _execute(name, arguments):
        return tools_module.execute(name, arguments, context)

    catalog_search = _catalog_search_for_message(user_text)
    if catalog_search:
        catalog_query, catalog_arguments = catalog_search
        # Shopping/availability replies must use the live catalog, even when
        # this conversation previously told the customer that an item was absent.
        state['clear_interaction_id'] = True
        try:
            execution = tools_module.execute(
                'search_products',
                catalog_arguments,
                context,
            )
            yield ('tool', _handle_tool(state, execution, context))
            if execution.status != 'ok':
                state['error'] = {
                    'code': 'catalog_unavailable',
                    'message': 'I could not check the catalog right now. Please try again shortly.',
                }
            else:
                state['text'] = _live_catalog_reply(
                    catalog_query, execution.payload or {})
                yield ('delta', {'text': state['text']})
                if state['products']:
                    yield ('products', {
                        'products': state['products'][:MAX_PRODUCT_CARDS]})
        except Exception:
            logger.exception('assistant: live catalog search failed')
            state['error'] = {
                'code': 'catalog_unavailable',
                'message': 'I could not check the catalog right now. Please try again shortly.',
            }
        finally:
            message = _persist_turn(conversation, state, started)

        if state['error']:
            yield ('error', state['error'])
            return
        yield ('done', {
            'messageId': str(message.pk) if message else '',
            'conversationId': str(conversation.pk),
            'latencyMs': int((time.monotonic() - started) * 1000),
            'usage': {},
            'unanswered': False,
            'toolCount': len(state['tools']),
        })
        return

    try:
        for event, data in gemini.run_turn(
                system_instruction=SYSTEM_PROMPT,
                payload=user_text,
                tools=tools_module.TOOL_SCHEMAS,
                previous_interaction_id=conversation.last_interaction_id,
                replay_input=build_replay_input(conversation, user_text),
                stream=stream,
                execute_tool=_execute):
            if event == 'delta':
                safe = marker.feed(data)
                if safe:
                    state['text'] += safe
                    yield ('delta', {'text': safe})
            elif event == 'tool':
                yield ('tool', _handle_tool(state, data, context))
            elif event == 'result':
                if not stream and data.text:
                    # Non-streaming turns have no deltas: collect the whole
                    # reply here (tail-buffered so the marker never shows).
                    safe = marker.feed(data.text)
                    if safe:
                        state['text'] += safe
                leftover = marker.flush()
                if leftover:
                    state['text'] += leftover
                    yield ('delta', {'text': leftover})
                state['interaction_id'] = data.interaction_id or ''
                state['usage'] = data.usage or {}
                if data.status in ('blocked', 'failed') or not state['text'].strip():
                    state['error'] = {'code': 'blocked',
                                      'message': FRIENDLY_BLOCKED}
                else:
                    if marker.found:
                        state['unanswered'] = True
                        record_insight(AssistantInsight.Kind.UNANSWERED,
                                       user_text)
                    if not stream and state['text']:
                        # Non-streaming turns have no deltas: emit the reply
                        # as one delta so JSON consumers share the protocol.
                        yield ('delta', {'text': state['text']})

        if state['error'] is None:
            if state['products']:
                yield ('products', {'products': state['products'][:MAX_PRODUCT_CARDS]})
            for action in state['actions']:
                yield ('action', action)

    except GeminiError as exc:
        logger.warning('assistant: turn failed (code=%s): %s', exc.code, exc)
        state['error'] = {'code': exc.code, 'message': exc.friendly}
        if exc.code not in ('stale_interaction',):
            record_insight(AssistantInsight.Kind.GEMINI_ERROR, exc.code)
        AuditLogService.log(
            'assistant_error',
            object_type='assistant_conversation',
            object_id=str(conversation.pk),
            result='failure',
            metadata={'conversationId': str(conversation.pk),
                      'errorCode': exc.code, 'retryable': bool(exc.retryable)},
            description='Assistant failed to reach the language model.')
    except Exception as exc:  # noqa: BLE001 - a chat turn must never 500
        logger.exception('assistant: unexpected turn failure')
        state['error'] = {'code': 'internal_error', 'message': FRIENDLY_ERROR}
        AuditLogService.log(
            'assistant_error',
            object_type='assistant_conversation',
            object_id=str(conversation.pk),
            result='failure',
            metadata={'conversationId': str(conversation.pk),
                      'errorCode': 'internal_error'},
            description='Assistant hit an unexpected internal error.')
    finally:
        # Runs on success, failure AND client disconnect (GeneratorExit), so
        # a half-streamed reply is still persisted for the audit trail.
        message = _persist_turn(conversation, state, started)

    latency_ms = int((time.monotonic() - started) * 1000)

    if state['error']:
        yield ('error', {'code': state['error']['code'],
                         'message': state['error']['message']})
        return

    yield ('done', {
        'messageId': str(message.pk) if message else '',
        'conversationId': str(conversation.pk),
        'latencyMs': latency_ms,
        'usage': state['usage'],
        'unanswered': state['unanswered'],
        'toolCount': len(state['tools']),
    })
