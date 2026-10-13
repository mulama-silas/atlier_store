"""Modeza AI HTTP surface (``/api/ai/*``).

* ``GET  /api/ai/health/`` — real Gemini connectivity probe (public but
  throttled and briefly cached).
* ``POST /api/ai/chat/`` — one customer turn. Defaults to Server-Sent Events
  (``stream: true``) with the same event names the React widget parses; set
  ``stream: false`` (or ``Accept: application/json``) for the JSON contract:
  ``{"success": true, "message": ..., "conversation_id": ...}``.

Gemini is only ever reached through :class:`ai.gemini_service.GeminiService`;
views never import ``google.genai``. Customer identity comes exclusively from
``request.user`` — a ``customer_id`` in the body is never trusted.
"""
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import StreamingHttpResponse
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.context import current_request_context
from assistant.services.conversation import get_or_create_conversation
from assistant.services.tools import ToolContext
from assistant.views import _session_ident, _wants_json

from .gemini_service import GeminiService
from .serializers import ChatRequestSerializer
from .throttling import AIRateThrottle

logger = logging.getLogger('modeza.assistant')

HEALTH_CACHE_KEY = 'modeza:ai:health'

_ERROR_HTTP_STATUS = {
    'empty_message': 400,
    'rate_limited': 429,
    'quota_exceeded': 429,
}


def _sse(events):
    """Render ``(event, data)`` tuples as Server-Sent Events."""
    for event, data in events:
        yield f'event: {event}\n'
        yield f'data: {json.dumps(data, separators=(",", ":"))}\n\n'


def _collect_json(events):
    """Consume a turn into the JSON (non-streaming) response contract."""
    conversation_id = ''
    reply_parts = []
    done = {}
    error = None
    for event, data in events:
        if event == 'meta':
            conversation_id = data.get('conversationId', '') or conversation_id
        elif event == 'delta':
            reply_parts.append(data.get('text', ''))
        elif event == 'done':
            done = data
        elif event == 'error':
            error = data

    if error:
        code = str(error.get('code', 'upstream_error'))
        status = _ERROR_HTTP_STATUS.get(code, 502)
        return Response({
            'success': False,
            'error_code': code.upper(),
            'message': error.get('message', ''),
            'conversation_id': conversation_id,
        }, status=status)

    return Response({
        'success': True,
        'message': ''.join(reply_parts).strip(),
        'conversation_id': (conversation_id
                            or done.get('conversationId', '')),
        'latency_ms': done.get('latencyMs', 0),
        'usage': done.get('usage', {}),
        'unanswered': done.get('unanswered', False),
    })


def _first_error(errors):
    """Pick the first human-readable serializer error message."""
    for field, details in errors.items():
        if isinstance(details, list) and details:
            return str(details[0])
        if isinstance(details, dict):
            return _first_error(details)
    return 'Invalid request.'


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class AIHealthView(APIView):
    """``GET /api/ai/health/`` — proves Django→google-genai→Gemini round-trip.

    The result is cached for ``GEMINI_HEALTH_CACHE_SECONDS`` because each
    probe spends real Gemini quota. Never exposes the API key or internals.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AIRateThrottle]

    def get(self, request):
        cached = cache.get(HEALTH_CACHE_KEY)
        if cached:
            return Response(cached)

        service = GeminiService()
        report = service.health_check()

        if report.ok:
            payload = {
                'success': True,
                'status': 'healthy',
                'provider': 'google_gemini',
                'model': report.model,
                'response': report.text,
                'latency_ms': report.latency_ms,
            }
            cache.set(
                HEALTH_CACHE_KEY, payload,
                timeout=int(getattr(settings, 'GEMINI_HEALTH_CACHE_SECONDS', 60)
                            or 60))
            return Response(payload)

        error = report.error or AI_UNEXPECTED
        return Response({
            'success': False,
            'status': 'unhealthy',
            'provider': 'google_gemini',
            'model': report.model,
            'error_code': error.error_code,
            'message': error.customer_message,
        }, status=error.http_status)


# Sentinel: health_check only returns None error when ok is True, so this is
# never visible; kept for type safety.
class _UnreachableError:
    error_code = 'UNEXPECTED_ERROR'
    http_status = 503
    customer_message = 'Health check failed.'


AI_UNEXPECTED = _UnreachableError()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class AIChatView(APIView):
    """``POST /api/ai/chat/`` — one customer turn (SSE or JSON).

    * ``message`` must be present, non-empty and short enough.
    * ``conversation_id`` / ``conversationId`` resumes an existing thread.
    * ``stream: true`` (default) returns Server-Sent Events; otherwise the
      JSON response object is returned.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AIRateThrottle]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        serializer = ChatRequestSerializer(data=body)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'VALIDATION_ERROR',
                'message': _first_error(serializer.errors),
            }, status=400)

        text = serializer.validated_data['message']
        conversation_id = serializer.validated_data.get('_conversation_id')
        user = (request.user
                if getattr(request.user, 'is_authenticated', False) else None)

        conversation, _created = get_or_create_conversation(
            user=user,
            session_key=_session_ident(request),
            conversation_id=conversation_id,
        )

        context = ToolContext(
            user=user,
            cart_key=request.headers.get('x-cart-id') or '',
            request_id=(current_request_context().get('request_id') or ''),
            ip_address=request.META.get('REMOTE_ADDR', ''),
        )

        stream = not _wants_json(request, body)
        service = GeminiService()
        events = service.run_chat(conversation, text, context, stream=stream)

        if stream:
            response = StreamingHttpResponse(
                _sse(events), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache, no-transform'
            response['X-Accel-Buffering'] = 'no'
            return response

        return _collect_json(events)