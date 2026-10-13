"""Google Gemini driver for the Modeza assistant (Interactions API).

This module is the ONLY place that touches the Google Gen AI SDK. It owns:

* lazy client construction (``GEMINI_API_KEY`` stays server-side),
* the function-calling loop: create interaction → execute Modeza tools →
  send function results back → repeat until the model answers,
* streaming (``stream=True``) with incremental ``step.delta`` text events,
* retries with exponential backoff for transient failures (timeout, 429,
  5xx) and classification of everything else.

Nothing here knows about Django models or HTTP — callers hand in a system
instruction, a payload and an ``execute_tool`` callable, and consume a
generator of ``(event, data)`` tuples:

    ('delta',  'text chunk')                     # streamed reply text
    ('tool',   ToolExecution)                    # one executed tool call
    ('result', TurnResult)                       # always the last event

Raw SDK exceptions never escape: they become :class:`GeminiFailed` /
:class:`GeminiUnavailable` with a customer-safe message; details are logged
on the ``modeza.assistant`` logger with the request id.
"""
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

from django.conf import settings

logger = logging.getLogger('modeza.assistant')

MAX_TOOL_ROUNDS = 4

# Customer-safe fallbacks. Raw Gemini errors are never shown.
FRIENDLY_ERROR = ("Sorry, I'm having trouble right now. "
                  "Please try again in a moment.")
# Distinct copy for quota exhaustion so it reads as capacity, not breakage.
FRIENDLY_CAPACITY = ("Modeza's assistant has reached today's capacity. "
                     "Please try again a bit later.")


class GeminiError(Exception):
    """Base class for assistant-facing Gemini failures."""

    def __init__(self, message='', *, code='gemini_error',
                 friendly=FRIENDLY_ERROR, retryable=False):
        super().__init__(message or code)
        self.code = code
        self.friendly = friendly
        self.retryable = retryable


class GeminiUnavailable(GeminiError):
    """No API key / SDK not configured — the assistant is off, not broken."""

    def __init__(self, message='GEMINI_API_KEY is not configured'):
        super().__init__(message, code='gemini_not_configured',
                         friendly=FRIENDLY_ERROR, retryable=False)


class GeminiFailed(GeminiError):
    """Retries exhausted (or a non-retryable API failure)."""


class GeminiStaleChain(GeminiError):
    """The stored ``previous_interaction_id`` is no longer valid — the caller
    should retry once with replayed history instead."""

    def __init__(self, message='stale previous_interaction_id'):
        super().__init__(message, code='stale_interaction',
                         retryable=False)


@dataclass
class ToolCall:
    name: str
    arguments: dict
    call_id: str


@dataclass
class ToolExecution:
    """One executed tool call, yielded as a ``('tool', ...)`` event and
    persisted by the conversation layer as ``AssistantToolCall``."""

    name: str
    arguments: dict = field(default_factory=dict)
    payload: Any = None
    status: str = 'ok'          # ok | error | timeout
    error_code: str = ''
    duration_ms: int = 0
    call_id: str = ''


@dataclass
class TurnResult:
    text: str = ''
    interaction_id: str = ''
    usage: dict = field(default_factory=dict)
    status: str = 'completed'   # completed | blocked | tool_limit | failed
    rounds: int = 0


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_client = None
_client_key = None


def _get_client():
    """Return a cached ``google.genai.Client`` built from Django settings.

    Tests monkeypatch this function; nothing else in the codebase may create
    a client, so the API key never leaves the backend.
    """
    global _client, _client_key
    api_key = getattr(settings, 'GEMINI_API_KEY', '') or ''
    if not api_key:
        raise GeminiUnavailable('GEMINI_API_KEY is not configured')
    if _client is None or _client_key != api_key:
        from google import genai
        _client = genai.Client(api_key=api_key)
        _client_key = api_key
    return _client


def reset_client():
    """Drop the cached client (used when settings change, e.g. tests)."""
    global _client, _client_key
    _client = None
    _client_key = None


# ---------------------------------------------------------------------------
# Error classification / retries
# ---------------------------------------------------------------------------

def _is_rate_limit(text):
    return ('rate_limit' in text or 'rate limit' in text
            or 'resource_exhausted' in text or 'resource exhausted' in text)


def _is_daily_rate_limit(text):
    """A requests-per-day (RPD) quota — retrying now cannot succeed."""
    lowered = text.lower()
    return 'per day' in lowered or 'daily' in lowered or ' rpd' in lowered


def _classify(exc):
    """Map an SDK/network exception to ``(code, retryable)``."""
    code = getattr(exc, 'code', None)
    name = type(exc).__name__
    text = str(exc).lower()

    if isinstance(code, int) and 400 <= code < 500:
        if 'previous_interaction_id' in text:
            return 'stale_interaction', False
        if code == 429:
            # Minute-level limits recover in seconds; daily ones do not.
            return 'rate_limited', not _is_daily_rate_limit(text)
        if code == 401 or code == 403:
            return 'auth_error', False
        return 'client_error', False
    if isinstance(code, int) and 500 <= code < 600:
        return 'server_error', True
    if 'timeout' in name.lower() or 'timed out' in text or 'timeout' in text:
        return 'timeout', True
    if 'connection' in name.lower() or 'connect' in text:
        return 'connection_error', True
    return 'unknown_error', False


def _create_interaction(client, *, stream, **kwargs):
    """One API call with retry/backoff for transient failures.

    ``stream`` must reach the SDK body — that is what makes
    ``interactions.create`` return an SSE stream instead of a completed
    interaction.
    """
    kwargs['stream'] = bool(stream)
    max_retries = int(getattr(settings, 'GEMINI_MAX_RETRIES', 2) or 0)
    backoff = float(getattr(settings, 'GEMINI_RETRY_BACKOFF_SECONDS', 0.5) or 0)
    attempt = 0
    while True:
        try:
            return client.interactions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - SDK raises many shapes
            code, retryable = _classify(exc)
            if code == 'stale_interaction':
                logger.info('assistant: stale interaction chain (%s)', type(exc).__name__)
                raise GeminiStaleChain(str(exc)) from exc
            logger.warning(
                'assistant: gemini call failed (attempt=%s code=%s '
                'retryable=%s type=%s): %s',
                attempt, code, retryable, type(exc).__name__,
                str(exc)[:300])
            if retryable and attempt < max_retries:
                attempt += 1
                if backoff:
                    time.sleep(min(backoff * (2 ** (attempt - 1)), 8)
                               + random.uniform(0, 0.25))
                continue
            raise GeminiFailed(
                f'Gemini request failed ({code})', code=code,
                retryable=retryable,
                friendly=(FRIENDLY_CAPACITY if code == 'rate_limited'
                          else FRIENDLY_ERROR)) from exc


def _usage_dict(usage):
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {k: v for k, v in usage.items() if not k.endswith('_by_modality')}
    try:
        data = usage.model_dump(exclude_none=True)
    except Exception:  # noqa: BLE001 - usage is best-effort metadata
        return {}
    return {k: v for k, v in data.items() if not k.endswith('_by_modality')}


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _merge_call_arguments(call):
    """Prefer the streamed raw JSON arguments; fall back to the step dict."""
    raw = call.get('raw') or ''
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, TypeError):
            pass
    args = call.get('args')
    return args if isinstance(args, dict) else {}


def _parse_interaction(interaction):
    text_parts, calls = [], []
    steps = getattr(interaction, 'steps', None) or []
    for step in steps:
        step_type = getattr(step, 'type', None)
        if step_type == 'function_call':
            calls.append(ToolCall(
                name=getattr(step, 'name', '') or '',
                arguments=_merge_call_arguments({
                    'args': getattr(step, 'arguments', None) or {},
                    'raw': '',
                }),
                call_id=getattr(step, 'id', '') or '',
            ))
        elif step_type == 'model_output':
            for content in (getattr(step, 'content', None) or []):
                if getattr(content, 'type', None) == 'text':
                    text_parts.append(getattr(content, 'text', '') or '')
    text = ''.join(text_parts)
    if not text:
        text = getattr(interaction, 'output_text', '') or ''
    return (
        text,
        calls,
        getattr(interaction, 'id', '') or '',
        _usage_dict(getattr(interaction, 'usage', None)),
        getattr(interaction, 'status', 'completed') or 'completed',
    )


def _stream_error_detail(event):
    """Extract ``(code, message)`` from a Gemini SSE ``error`` event.

    The SDK's ``ErrorEvent`` carries the failure in ``event.error`` (a
    ``{code, message}`` object); ``event.message`` does not exist — reading it
    used to make every stream failure log the useless "stream error".
    """
    error = getattr(event, 'error', None)
    code = str(getattr(error, 'code', '') or '')
    message = str(getattr(error, 'message', '') or '')
    if not message:  # tolerate alternate/older event shapes
        message = str(getattr(event, 'message', '') or '')
    return code, message


_PERMANENT_STREAM_TOKENS = (
    'permission', 'denied', 'forbidden', 'unauthenticated', 'unauthorized',
    'api key', 'invalid', 'not found', 'prohibited', 'blocked',
)


def _stream_error_retryable(code, message):
    """Classify a stream ``error`` event.

    Daily (RPD) rate limits and clearly permanent errors never retry;
    everything else — including an empty/unknown mid-stream failure (e.g. a
    network blip between Render and Google) — defaults to retryable, which is
    exactly the case a second attempt fixes. Retries in ``run_turn`` only run
    before any text was emitted, so a retry can never duplicate a reply.
    """
    text = f'{code} {message}'.lower()
    if _is_rate_limit(text) and _is_daily_rate_limit(text):
        return False
    return not any(token in text for token in _PERMANENT_STREAM_TOKENS)


def _consume_stream(stream):
    """Walk SSE events; yields ``('delta', text)`` as text arrives and a
    final ``('final', (text, calls, interaction_id, usage, status))``."""
    text_parts, call_buffers = [], []
    interaction_id, usage, status = '', {}, 'completed'
    current = None

    def flush():
        nonlocal current
        if current is not None:
            call_buffers.append(current)
            current = None

    for event in stream:
        event_type = getattr(event, 'event_type', None)
        if event_type == 'interaction.created':
            interaction = getattr(event, 'interaction', None)
            interaction_id = getattr(interaction, 'id', '') or interaction_id
        elif event_type == 'step.start':
            step = getattr(event, 'step', None)
            step_type = getattr(step, 'type', None)
            if step_type == 'function_call':
                flush()
                current = {
                    'id': getattr(step, 'id', '') or '',
                    'name': getattr(step, 'name', '') or '',
                    'args': getattr(step, 'arguments', None) or {},
                    'raw': '',
                }
            else:
                flush()
        elif event_type == 'step.delta':
            delta = getattr(event, 'delta', None)
            delta_type = getattr(delta, 'type', None)
            if delta_type == 'text':
                chunk = getattr(delta, 'text', '') or ''
                if chunk:
                    text_parts.append(chunk)
                    yield ('delta', chunk)
            elif delta_type == 'arguments_delta' and current is not None:
                current['raw'] += getattr(delta, 'arguments', '') or ''
        elif event_type == 'step.stop':
            flush()
        elif event_type == 'interaction.completed':
            interaction = getattr(event, 'interaction', None)
            interaction_id = getattr(interaction, 'id', '') or interaction_id
            usage = _usage_dict(getattr(interaction, 'usage', None))
            status = getattr(interaction, 'status', 'completed') or 'completed'
        elif event_type == 'error':
            code, message = _stream_error_detail(event)
            text = f'{code} {message}'.lower()
            retryable = _stream_error_retryable(code, message)
            try:
                dump = event.model_dump(mode='json', exclude_none=True)
            except Exception:  # noqa: BLE001 - log whatever shape we got
                dump = repr(event)
            logger.warning(
                'assistant: gemini stream error event (retryable=%s '
                'code=%s message=%s): %s',
                retryable, code or 'unknown', message or '<empty>',
                str(dump)[:500])
            rate_limited = _is_rate_limit(text)
            raise GeminiFailed(
                f'Gemini stream error: [{code or "unknown"}] '
                f'{message or "no detail"}',
                code='rate_limited' if rate_limited else 'stream_error',
                retryable=retryable,
                friendly=(FRIENDLY_CAPACITY if rate_limited
                          else FRIENDLY_ERROR))
        # 'interaction.status_update' and unknown events are ignored.

    flush()
    calls = [
        ToolCall(name=c['name'], arguments=_merge_call_arguments(c),
                 call_id=c['id'])
        for c in call_buffers if c.get('name')
    ]
    yield ('final', (''.join(text_parts), calls, interaction_id, usage,
                     status))


def _function_result_step(execution):
    """Build the ``function_result`` input step for a tool execution."""
    if execution.status == 'ok':
        result = execution.payload
        is_error = False
    else:
        result = {'error': {'code': execution.error_code or 'tool_failed',
                            'message': 'The tool could not complete.'}}
        is_error = True
    try:
        text = json.dumps(result, default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        text = '{}'
    return {
        'type': 'function_result',
        'name': execution.name,
        'call_id': execution.call_id,
        'is_error': is_error,
        'result': [{'type': 'text', 'text': text}],
    }


# ---------------------------------------------------------------------------
# The turn loop
# ---------------------------------------------------------------------------

def run_turn(*, system_instruction: str, payload, tools=None,
             previous_interaction_id: Optional[str] = None,
             replay_input=None, stream: bool = False,
             execute_tool: Optional[Callable] = None) -> Iterator[tuple]:
    """Run one customer turn, executing tools until the model answers.

    ``payload`` is the new user message (str) or the ``function_result``
    steps built by a previous round. ``replay_input`` is a full server-side
    history (list of steps) used only when the stored chain id went stale.
    """
    client = _get_client()
    model = getattr(settings, 'GEMINI_MODEL', '') or 'gemini-3.5-flash-lite'
    timeout = float(getattr(settings, 'GEMINI_TIMEOUT_SECONDS', 30) or 30)
    max_retries = int(getattr(settings, 'GEMINI_MAX_RETRIES', 2) or 0)
    backoff = float(getattr(settings, 'GEMINI_RETRY_BACKOFF_SECONDS', 0.5) or 0)
    max_tool_rounds = int(
        getattr(settings, 'ASSISTANT_MAX_TOOL_ROUNDS', MAX_TOOL_ROUNDS))

    # Stateful chaining when we have a valid previous interaction id; otherwise
    # fall back to server-side history replay (built by the caller).
    chain_id = previous_interaction_id or ''
    if chain_id:
        current_input = payload
    else:
        current_input = replay_input if replay_input else payload
    used_replay = bool(not chain_id and replay_input)
    text_parts: list[str] = []
    last_interaction_id = ''
    last_usage: dict = {}
    last_status = 'completed'
    rounds = 0

    for round_index in range(max_tool_rounds + 1):
        rounds = round_index + 1
        # Final round: no tools, so the model must produce the answer.
        round_tools = tools if round_index < max_tool_rounds else []
        kwargs = {
            'model': model,
            'system_instruction': system_instruction,
            'input': current_input,
            'stream': bool(stream),
            'timeout': timeout,
        }
        if round_tools:
            kwargs['tools'] = round_tools
        if chain_id:
            kwargs['previous_interaction_id'] = chain_id

        try:
            created = _create_interaction(client, **kwargs)
        except GeminiStaleChain:
            if not replay_input or used_replay:
                raise
            used_replay = True
            chain_id = ''
            kwargs.pop('previous_interaction_id', None)
            if isinstance(current_input, list) and current_input is not replay_input:
                kwargs['input'] = list(replay_input) + current_input
            else:
                kwargs['input'] = replay_input
            created = _create_interaction(client, **kwargs)

        if stream:
            attempt = 0
            while True:
                final = None
                emitted_before = len(text_parts)
                try:
                    for kind, data in _consume_stream(created):
                        if kind == 'delta':
                            text_parts.append(data)
                            yield ('delta', data)
                        else:
                            final = data
                    break
                except GeminiFailed as exc:
                    # Retry only transient stream errors that arrive before
                    # this round emitted any text (retrying after a delta
                    # would duplicate what the customer already sees).
                    if (not exc.retryable
                            or len(text_parts) != emitted_before
                            or attempt >= max_retries):
                        raise
                    attempt += 1
                    logger.warning(
                        'assistant: retrying stream (attempt=%s code=%s): %s',
                        attempt, exc.code, exc)
                    if backoff:
                        time.sleep(min(backoff * (2 ** (attempt - 1)), 8)
                                   + random.uniform(0, 0.25))
                    created = _create_interaction(client, **kwargs)
            text, calls, interaction_id, usage, status = final
        else:
            text, calls, interaction_id, usage, status = _parse_interaction(created)

        if interaction_id:
            last_interaction_id = interaction_id
            chain_id = interaction_id  # fresh ids chain the tool rounds
        if usage:
            last_usage = usage
        last_status = status
        if text and not stream:
            text_parts.append(text)

        if not calls:
            joined = ''.join(text_parts)
            yield ('result', TurnResult(
                text=joined,
                interaction_id=last_interaction_id,
                usage=last_usage,
                status=('blocked' if not joined else (
                    'failed' if status in ('failed', 'cancelled') else 'completed')),
                rounds=rounds,
            ))
            return

        if execute_tool is None:
            yield ('result', TurnResult(
                text=''.join(text_parts),
                interaction_id=last_interaction_id,
                usage=last_usage,
                status='failed',
                rounds=rounds,
            ))
            return

        function_results = []
        for call in calls:
            started = time.monotonic()
            try:
                execution = execute_tool(call.name, call.arguments)
            except Exception as exc:  # noqa: BLE001 - tool bugs stay inside
                logger.warning('assistant: tool %s raised: %s', call.name, exc)
                execution = ToolExecution(
                    name=call.name, arguments=dict(call.arguments or {}),
                    payload=None, status='error', error_code='tool_crashed',
                    duration_ms=int((time.monotonic() - started) * 1000))
            if not isinstance(execution, ToolExecution):
                execution = ToolExecution(
                    name=call.name, arguments=dict(call.arguments or {}),
                    payload=execution, status='ok')
            execution.call_id = execution.call_id or call.call_id
            execution.duration_ms = execution.duration_ms or int(
                (time.monotonic() - started) * 1000)
            yield ('tool', execution)
            function_results.append(_function_result_step(execution))

        current_input = function_results

    # Should be unreachable (the final round passes tools=[]), but never let
    # the loop end without a result event.
    yield ('result', TurnResult(
        text=''.join(text_parts),
        interaction_id=last_interaction_id,
        usage=last_usage,
        status='tool_limit',
        rounds=rounds,
    ))
