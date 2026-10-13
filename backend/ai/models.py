"""Model alignment for the modeza AI endpoints.

The ``ai`` app shares the conversation schema owned by the ``assistant`` app
(single source of truth for conversations, messages, tool calls and
insights). No tables are created here — re-exports keep the ai codebase able
to use the same models without a second migration.
"""
from assistant.models import (AssistantConversation, AssistantInsight,
                              AssistantMessage, AssistantToolCall)

__all__ = [
    'AssistantConversation',
    'AssistantInsight',
    'AssistantMessage',
    'AssistantToolCall',
]