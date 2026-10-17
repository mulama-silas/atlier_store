"""Assistant HTTP surface.

* ``POST /api/assistant/chat``   — streaming SSE reply (default) or JSON.
* ``GET  /api/assistant/history`` — messages of one conversation (owner only).
* ``GET  /api/assistant/suggestions`` — welcome copy + quick questions.

All endpoints are throttled with :class:`AssistantRateThrottle`. The Gemini
key is never touched here — only the conversation services are.
"""
import json
import uuid

from django.http import StreamingHttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .constants import (MAX_MESSAGE_LENGTH, SUGGESTED_QUESTIONS,
                        WELCOME_MESSAGE)
from .models import AssistantConversation
from .services.conversation import get_or_create_conversation, run_message
from .services.tools import ToolContext
from .throttling import AssistantRateThrottle


def _parse_uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return ''

def _session_ident(request):
    """Opaque guest identity: Django session key, else the cart id header."""
    session_key = ''
    try:
        session_key = request.session.session_key or ''
    except Exception:  # noqa: BLE001 - sessions are optional
        session_key = ''
    return session_key or (request.headers.get('x-cart-id') or '')

def _tool_context(request):
    user = request.user if getattr(request.user, 'is_authenticated', False) else None
    return ToolContext(
        user=user,
        cart_key=request.headers.get('x-cart-id') or '',
        ip_address=request.META.get('REMOTE_ADDR', ''),
    )


def _wants_json(request, body):
    if str(request.query_params.get('format', '')).lower() in ('json', 'text'):
        return True
    if body.get('stream') is False:
        return True
    accept = request.headers.get('Accept', '')
    if accept and 'text/event-stream' not in accept and 'application/json' in accept:
        return True
    return False


def _sse(events):
    """Render ``(event, data)`` tuples as Server-Sent Events."""
    for event, data in events:
        yield f'event: {event}\n'
        yield f'data: {json.dumps(data, separators=(",", ":"))}\n\n'


def _collect(events):
    """Consume a whole turn into one JSON payload (non-streaming mode)."""
    payload = {'reply': '', 'conversationId': '', 'messageId': '',
               'latencyMs': 0, 'usage': {}, 'unanswered': False,
               'tools': [], 'products': [], 'actions': [], 'error': None}
    for event, data in events:
        if event == 'meta':
            payload['conversationId'] = data.get('conversationId', '')
        elif event == 'delta':
            payload['reply'] += data.get('text', '')
        elif event == 'tool':
            payload['tools'].append(data)
        elif event == 'products':
            payload['products'] = data.get('products', [])
        elif event == 'action':
            payload['actions'].append(data)
        elif event == 'done':
            payload.update({k: data[k] for k in
                            ('messageId', 'conversationId', 'latencyMs', 'usage',
                             'unanswered') if k in data})
            payload['toolCount'] = data.get('toolCount', len(payload['tools']))
        elif event == 'error':
            payload['error'] = data
    return payload


def _conversation_for(request, body=None):
    body = body or {}
    conversation_id = _parse_uuid(
        body.get('conversationId') or request.query_params.get('conversationId'))
    user = request.user if getattr(request.user, 'is_authenticated', False) else None
    return get_or_create_conversation(
        user=user, session_key=_session_ident(request),
        conversation_id=conversation_id)


class ChatView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AssistantRateThrottle]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        text = str(body.get('message') or body.get('text') or '')
        conversation, _created = _conversation_for(request, body)
        context = _tool_context(request)
        stream = not _wants_json(request, body)
        events = run_message(conversation, text, context, stream=stream)

        if stream:
            response = StreamingHttpResponse(
                _sse(events), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache, no-transform'
            response['X-Accel-Buffering'] = 'no'
            return response

        payload = _collect(events)
        if payload['error']:
            code = payload['error'].get('code', 'upstream_error')
            if code == 'empty_message':
                status = 400
            elif code == 'rate_limited':
                status = 429
            else:
                status = 502
            return Response({'error': {
                'code': code.upper(),
                'message': payload['error'].get('message', ''),
                'details': {}},
                'conversationId': payload['conversationId']}, status=status)
        return Response(payload)


class HistoryView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AssistantRateThrottle]

    def get(self, request):
        conversation_id = _parse_uuid(
            request.query_params.get('conversationId') or '')
        if not conversation_id:
            return Response({'error': {'code': 'VALIDATION_ERROR',
                                       'message': 'conversationId is required.',
                                       'details': {}}}, status=400)
        conversation = AssistantConversation.objects.filter(
            pk=conversation_id).first()
        if conversation is None:
            return Response({'error': {'code': 'NOT_FOUND',
                                       'message': 'Conversation not found.',
                                       'details': {}}}, status=404)
        if not _owns(request, conversation):
            return Response({'error': {'code': 'FORBIDDEN',
                                       'message': 'You cannot read this conversation.',
                                       'details': {}}}, status=403)
        messages = conversation.messages.order_by('created_at')[:100]
        return Response({
            'conversationId': str(conversation.pk),
            'messages': [_serialize_message(m) for m in messages],
        })


class SuggestionsView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AssistantRateThrottle]

    def get(self, request):
        return Response({'welcome': WELCOME_MESSAGE,
                         'suggestions': SUGGESTED_QUESTIONS})


def _owns(request, conversation):
    user = request.user
    if conversation.user_id is not None:
        return bool(user and getattr(user, 'is_authenticated', False)
                    and user.pk == conversation.user_id)
    return True  # guests hold the unguessable conversation UUID


def _serialize_message(message):
    return {
        'id': str(message.pk),
        'role': message.role,
        'kind': message.kind,
        'content': message.content,
        'productRefs': message.product_refs,
        'actions': message.actions,
        'unanswered': message.unanswered,
        'createdAt': message.created_at.isoformat(),
    }
