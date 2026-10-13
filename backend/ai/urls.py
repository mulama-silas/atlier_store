from django.urls import path

from .views import AIChatView, AIHealthView

# Both slash variants are registered: the documented contract is with a
# trailing slash (/api/ai/health/, /api/ai/chat/) while the React client
# (mirroring /api/assistant/*) calls without one. APPEND_SLASH would turn a
# POST into a 301/GET, so both must resolve to the same views directly.
urlpatterns = [
    path('ai/health/', AIHealthView.as_view(), name='ai-health'),
    path('ai/health', AIHealthView.as_view(), name='ai-health-noslash'),
    path('ai/chat/', AIChatView.as_view(), name='ai-chat'),
    path('ai/chat', AIChatView.as_view(), name='ai-chat-noslash'),
]