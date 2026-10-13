"""Prompts for the Modeza AI endpoints.

The Modeza system prompt lives in ``assistant.constants`` (single source of
truth) and is loaded here for the ai surface. The health probe is a tiny,
deterministic probe used only by ``GET /api/ai/health/``.
"""
from assistant.constants import SYSTEM_PROMPT  # noqa: F401 - re-exported

HEALTH_PROBE_SYSTEM_INSTRUCTION = (
    'You are a connectivity probe for the Modeza Boutique AI assistant. '
    'Reply with exactly: MODEZA_AI_OK'
)

HEALTH_PROBE_INPUT = 'Reply with exactly: MODEZA_AI_OK'

EXPECTED_HEALTH_RESPONSE = 'MODEZA_AI_OK'

__all__ = [
    'SYSTEM_PROMPT',
    'HEALTH_PROBE_SYSTEM_INSTRUCTION',
    'HEALTH_PROBE_INPUT',
    'EXPECTED_HEALTH_RESPONSE',
]