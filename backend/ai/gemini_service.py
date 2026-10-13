"""Dedicated Google Gemini service for the Modeza AI endpoints.

This module is the ONLY place in the ``ai`` app that touches the Google Gen
AI SDK. It owns:

* lazy, cached ``genai.Client`` construction from Django settings (the API
  key never leaves the backend and never appears in a response),
* configuration validation (``GEMINI_API_KEY`` + ``GEMINI_MODEL`` present),
* a typed error taxonomy that maps SDK / network failures to public error
  codes (``CONFIGURATION_ERROR``, ``AUTHENTICATION_ERROR``,
  ``MODEL_NOT_FOUND``, ``AI_TIMEOUT``, ``RATE_LIMITED``, ``QUOTA_EXCEEDED``,
  ``PROVIDER_UNAVAILABLE``, ``NETWORK_ERROR``, ``CONTENT_BLOCKED`` ...),
* bounded retries for transient failures only — configuration, auth and
  model errors are never retried,
* a real connectivity probe for ``GET /api/ai/health/``,
* normalized chat turns delegating to the shared assistant turn engine
  (``assistant.services.conversation``) so persistence, authorization and the
  function-calling loop have one source of truth.

Views never import ``google.genai`` and never see raw SDK exceptions.
Diagnostics go to the ``modeza.assistant`` logger with the request id; the
public API only receives customer-safe codes and messages.
"""
import logging
import random
import time
from dataclasses import dataclass
from typing import Iterator, Optional

from django.conf import settings

logger = logging.getLogger('modeza.assistant')

FRIENDLY_UNAVAILABLE = (
    'The AI assistant is temporarily unavailable. Please try again.')
FRIENDLY_CAPACITY = (
    "Modeza's assistant has reached today's capacity. Please try again a bit later.")


# ---------------------------------------------------------------------------
# Error taxonomy
# ---------------------------------------------------------------------------

class AIError(Exception):
    """Base class for assistant-facing Gemini failures."""

    error_code = 'AI_ERROR'
    http_status = 502
    customer_message = FRIENDLY_UNAVAILABLE

    def __init__(self, message=''):
        super().__init__(message or self.error_code)


class AIConfigurationError(AIError):
    """GEMINI_API_KEY / GEMINI_MODEL missing or client init failed."""
    error_code = 'CONFIGURATION_ERROR'
    http_status = 503


class AIAuthenticationError(AIError):
    """401/403 — key rejected by Google."""
    error_code = 'AUTHENTICATION_ERROR'
    http_status = 502


class AIModelError(AIError):
    """404 — the configured model does not exist / is not enabled."""
    error_code = 'MODEL_NOT_FOUND'
    http_status = 502


class AIContentBlockedError(AIError):
    """Safety/policy blocked the response."""
    error_code = 'CONTENT_BLOCKED'
    http_status = 502
    customer_message = ('Sorry, I could not put that answer together. '
                        'Could you rephrase your question?')


class AIRateLimitError(AIError):
    """HTTP 429 — a temporary rate limit (retryable in seconds)."""
    error_code = 'RATE_LIMITED'
    http_status = 429
    customer_message = FRIENDLY_UNAVAILABLE


class AIQuotaExceededError(AIRateLimitError):
    """Daily (requests-per-day) quota exhausted — retrying cannot succeed."""
    error_code = 'QUOTA_EXCEEDED'
    customer_message = FRIENDLY_CAPACITY


class AITimeoutError(AIError):
    """The Gemini call exceeded the configured timeout."""
    error_code = 'AI_TIMEOUT'
    http_status = 502
    customer_message = FRIENDLY_UNAVAILABLE


class AINetworkError(AIError):
    """Connection-level failure reaching the Gemini API."""
    error_code = 'NETWORK_ERROR'
    http_status = 502


class AIProviderUnavailableError(AIError):
    """HTTP 5xx from Gemini."""
    error_code = 'PROVIDER_UNAVAILABLE'
    http_status = 503


class AIUnexpectedError(AIError):
    """Anything the classifier could not map."""
    error_code = 'UNEXPECTED_ERROR'


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _contains(text, *tokens):
    lowered = (text or '').lower()
    return any(token in lowered for token in tokens)


def _is_per_day_rate_limit(text):
    """A requests-per-day (RPD) quota — retrying now cannot succeed."""
    return _contains(text, 'per day', 'daily', ' rpd')


def classify_error(exc):
    """Map an SDK/network exception to the closest :class:`AIError`.

    The Google SDK raises typed errors carrying a numeric HTTP ``code`` and a
    message; httpx raises timeout/connection errors. Never raises.
    """
    code = getattr(exc, 'code', None)
    message = str(getattr(exc, 'message', '') or exc)
    name = type(exc).__name__

    if isinstance(code, int):
        if code == 400:
            if _contains(message, 'blocked', 'permitted', 'safety',
                         'prohibited'):
                return AIContentBlockedError(message)
            return AIUnexpectedError(message)
        if code in (401, 403):
            return AIAuthenticationError(message)
        if code == 404:
            return AIModelError(message)
        if code == 429:
            if _is_per_day_rate_limit(message):
                return AIQuotaExceededError(message)
            return AIRateLimitError(message)
        if 500 <= code < 600:
            return AIProviderUnavailableError(message)
        return AIUnexpectedError(message)

    low = name.lower() + ' ' + (message or '').lower()
    if 'timeout' in low or 'timed out' in low:
        return AITimeoutError(message)
    if 'connection' in low or 'connect error' in low or 'connreset' in low:
        return AINetworkError(message)
    if _contains(message, 'blocked', 'permitted', 'safety', 'prohibited'):
        return AIContentBlockedError(message)
    return AIUnexpectedError(message)


_TRANSIENT_CODES = {AIRateLimitError, AITimeoutError, AINetworkError,
                    AIProviderUnavailableError}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

@dataclass
class HealthReport:
    ok: bool
    model: str
    latency_ms: int
    text: str = ''
    error: Optional[AIError] = None


class GeminiService:
    """Server-side Gemini access for the ai endpoints.

    Construct with settings values by default; pass explicit values for
    tests. Instances are cheap; the underlying SDK client is cached per key.
    """

    def __init__(self, *, api_key=None, model=None, timeout=None,
                 max_retries=None, backoff=None):
        self.api_key = (api_key if api_key is not None
                        else getattr(settings, 'GEMINI_API_KEY', '') or '')
        self.model = (model if model is not None
                      else getattr(settings, 'GEMINI_MODEL', '') or '')
        self.timeout = float(timeout if timeout is not None
                             else getattr(settings,
                                          'GEMINI_TIMEOUT_SECONDS', 30) or 30)
        self.max_retries = int(max_retries if max_retries is not None
                               else getattr(settings,
                                            'GEMINI_MAX_RETRIES', 2) or 0)
        self.backoff = float(backoff if backoff is not None
                             else getattr(settings,
                                          'GEMINI_RETRY_BACKOFF_SECONDS',
                                          0.5) or 0.5)
        self._client = None

    # -- client ------------------------------------------------------------

    @property
    def client(self):
        """Cached ``google.genai.Client``; raises :class:`AIConfigurationError`
        when the API key is missing."""
        if self._client is None:
            if not self.api_key:
                raise AIConfigurationError('GEMINI_API_KEY is not configured.')
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as exc:  # noqa: BLE001 - client init is env-shaped
                logger.warning('ai: gemini client init failed: %s',
                               type(exc).__name__)
                raise AIConfigurationError(
                    'Gemini client could not be initialized.') from exc
        return self._client

    def reset_client(self):
        self._client = None

    # -- low-level call ----------------------------------------------------

    def _create(self, **kwargs):
        """One ``interactions.create`` call with bounded retry/backoff.

        Retries only transient failures (timeout / network / minute-level 429
        / 5xx). Configuration, auth and model errors are raised immediately.
        """
        kwargs.setdefault('timeout', self.timeout)
        attempt = 0
        while True:
            try:
                return self.client.interactions.create(**kwargs)
            except AIError:
                raise
            except Exception as exc:  # noqa: BLE001 - SDK raises many shapes
                error = classify_error(exc)
                logger.warning(
                    'ai: gemini call failed (attempt=%s code=%s type=%s): %s',
                    attempt, error.error_code, type(exc).__name__,
                    str(exc)[:300])
                transient = type(error) in _TRANSIENT_CODES
                if transient and attempt < self.max_retries:
                    attempt += 1
                    if self.backoff:
                        time.sleep(
                            min(self.backoff * (2 ** (attempt - 1)), 8)
                            + random.uniform(0, 0.25))
                    continue
                raise error

    # -- connectivity probe -------------------------------------------------

    def health_check(self) -> HealthReport:
        """Real Gemini connectivity test for ``GET /api/ai/health/``."""
        started = time.monotonic()
        report_error = None
        text = ''
        try:
            model = self.model or ''
            if not model:
                raise AIConfigurationError('GEMINI_MODEL is not configured.')
            self.client  # noqa: B018 - validates the API key first
            interaction = self._create(
                model=model,
                system_instruction=(
                    'You are a connectivity probe for the Modeza Boutique '
                    'AI assistant. Reply with exactly: MODEZA_AI_OK'),
                input='Reply with exactly: MODEZA_AI_OK',
                stream=False)
            text = _extract_text(interaction) or ''
        except AIError as exc:
            logger.warning('ai: health check failed (code=%s): %s',
                           exc.error_code, exc)
            report_error = exc
        return HealthReport(
            ok=bool(report_error is None and text.strip() == 'MODEZA_AI_OK'),
            model=self.model or '',
            text=text.strip(),
            latency_ms=int((time.monotonic() - started) * 1000),
            error=report_error)

    # -- chat --------------------------------------------------------------

    def run_chat(self, conversation, text, context, *, stream=True):
        """Run one customer turn using the shared assistant engine.

        Delegates to ``assistant.services.conversation.run_message`` (the one
        place that owns persistence, tool authorization, SSE events and
        Gemini failure mapping). Returns the same ``(event, data)`` iterator
        the assistant surface produces.
        """
        from assistant.services.conversation import run_message
        return run_message(conversation, text, context, stream=stream)


def _extract_text(interaction):
    """Pull plain text from a completed (non-stream) interaction."""
    parts = []
    for step in getattr(interaction, 'steps', None) or []:
        if getattr(step, 'type', None) == 'model_output':
            for content in getattr(step, 'content', None) or []:
                if getattr(content, 'type', None) == 'text':
                    parts.append(getattr(content, 'text', '') or '')
    return ''.join(parts) or getattr(interaction, 'output_text', '') or ''