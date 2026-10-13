"""Rate limiting for /api/ai/* endpoints.

Shares the assistant's per-user/per-IP budget — both surfaces spend the same
Gemini quota, so one budget avoids a second silent drain.
"""
from assistant.throttling import AssistantRateThrottle


class AIRateThrottle(AssistantRateThrottle):
    """Throttle for the ai endpoints (assistant_anon / assistant_user)."""