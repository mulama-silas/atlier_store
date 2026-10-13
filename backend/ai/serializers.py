"""Request validation for the /api/ai/ endpoints."""
from django.conf import settings
from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    """Validate ``POST /api/ai/chat/`` bodies.

    Accepts ``message`` (required, non-empty, bounded) and a conversation id
    supplied as ``conversation_id`` or the legacy camelCase ``conversationId``.
    """

    message = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=getattr(settings, 'AI_MAX_MESSAGE_LENGTH', 2000),
        error_messages={
            'required': 'Please type a message.',
            'blank': 'Please type a message.',
            'max_length': 'Your message is too long. Please shorten it.',
        },
    )
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    conversationId = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs['_conversation_id'] = (
            attrs.get('conversation_id') or attrs.get('conversationId'))
        return attrs