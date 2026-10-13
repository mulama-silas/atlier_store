"""Backend tests for the AI shopping assistant.

Gemini is never called: ``assistant.services.gemini._get_client`` is patched
with a fake Interactions API that replays scripted rounds (plain and SSE).
"""
import json
from datetime import timedelta
from types import SimpleNamespace as ns
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, APIClient

from admin_ui.models import AdminNotification
from audit.models import AuditLog
from catalog.models import Category, Product, ProductVariant
from orders.models import Order
from promotions.models import Promotion

from .analytics import assistant_analytics
from .models import (AssistantConversation, AssistantInsight,
                     AssistantMessage, AssistantToolCall)
from .services import tools as tools_module
from .services.conversation import (MarkerFilter, get_or_create_conversation,
                                    record_insight, run_message)
from .services.gemini import (_classify, _stream_error_detail,
                              _stream_error_retryable)
from .services.tools import ToolContext, sanitize_arguments
from .throttling import AssistantRateThrottle

User = get_user_model()


def make_user(username, **kwargs):
    password = kwargs.pop('password', 'pw')
    email = kwargs.pop('email', f'{username}@example.com')
    return User.objects.create_user(username=username, email=email,
                                    password=password, **kwargs)


# ---------------------------------------------------------------------------
# Fake Gemini
# ---------------------------------------------------------------------------

class FakeAPIError(Exception):
    def __init__(self, code=500, message='upstream boom'):
        super().__init__(message)
        self.code = code


def make_interaction(text='', calls=None, interaction_id='int-1'):
    steps = []
    for index, (name, arguments) in enumerate(calls or []):
        steps.append(ns(type='function_call', name=name,
                        id=f'call-{index}', arguments=arguments))
    if text:
        steps.append(ns(type='model_output',
                        content=[ns(type='text', text=text)]))
    return ns(id=interaction_id, status='completed', steps=steps,
              output_text=text, usage=None)


def stream_events(text='', calls=None, interaction_id='int-1', events=None):
    if events is not None:
        yield from events
        return
    yield ns(event_type='interaction.created',
             interaction=ns(id=interaction_id))
    for index, (name, arguments) in enumerate(calls or []):
        yield ns(event_type='step.start',
                 step=ns(type='function_call', name=name,
                         id=f'call-{index}', arguments={}))
        yield ns(event_type='step.delta',
                 delta=ns(type='arguments_delta',
                          arguments=json.dumps(arguments)))
        yield ns(event_type='step.stop')
    if text:
        half = max(1, len(text) // 2)
        for chunk in (text[:half], text[half:]):
            yield ns(event_type='step.start',
                     step=ns(type='model_output', content=[]))
            yield ns(event_type='step.delta',
                     delta=ns(type='text', text=chunk))
        yield ns(event_type='step.stop')
    yield ns(event_type='interaction.completed',
             interaction=ns(id=interaction_id, status='completed',
                            usage=None))


def error_stream_event(code='', message=''):
    """An SSE ``error`` event shaped exactly like the SDK's ErrorEvent."""
    return ns(event_type='error', error=ns(code=code, message=message))


def stream_before_error(text='partial', code='', message=''):
    """Events that stream some text and then fail (error not retried)."""
    half = max(1, len(text) // 2)
    return [
        ns(event_type='interaction.created', interaction=ns(id='int-partial')),
        ns(event_type='step.start', step=ns(type='model_output', content=[])),
        ns(event_type='step.delta', delta=ns(type='text', text=text[:half])),
        ns(event_type='step.delta', delta=ns(type='text', text=text[half:])),
        error_stream_event(code=code, message=message),
    ]


class FakeInteractions:
    """Replays scripted rounds; each spec is a dict or an Exception."""

    def __init__(self, specs):
        self.specs = list(specs)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.specs:
            raise AssertionError('unexpected extra Gemini call')
        spec = self.specs.pop(0)
        if isinstance(spec, Exception):
            raise spec
        if kwargs.get('stream'):
            return stream_events(text=spec.get('text', ''),
                                 calls=spec.get('calls'),
                                 interaction_id=spec.get('id', 'int-1'),
                                 events=spec.get('events'))
        return make_interaction(text=spec.get('text', ''),
                                calls=spec.get('calls'),
                                interaction_id=spec.get('id', 'int-1'))


class FakeClient:
    def __init__(self, specs):
        self.interactions = FakeInteractions(specs)


def patch_gemini(specs):
    """Patch the SDK client factory with a scripted fake.

    Yields the :class:`FakeClient` so tests can assert on recorded calls
    (``client.interactions.calls``).
    """
    return _GeminiScript(specs)


class _GeminiScript:
    def __init__(self, specs):
        self.client = FakeClient(specs)
        self.patcher = None

    def __enter__(self):
        self.patcher = patch('assistant.services.gemini._get_client',
                             return_value=self.client)
        self.patcher.start()
        return self.client

    def __exit__(self, *exc_info):
        self.patcher.stop()
        return False


# ---------------------------------------------------------------------------
# Chat API
# ---------------------------------------------------------------------------

class AssistantChatApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.category = Category.objects.create(name='Dresses',
                                                slug='dresses')
        self.product = Product.objects.create(
            category=self.category, name='Luna Slip Dress',
            slug='luna-slip-dress', description='A bias-cut slip dress.',
            price_minor=550000, status=Product.Status.ACTIVE)
        ProductVariant.objects.create(product=self.product, sku='LUNA-M',
                                      size='M', color='black',
                                      stock_quantity=4)

    def _post(self, specs, message='find me a dress', **extra):
        with patch_gemini(specs) as fake:
            body = {'message': message, 'stream': False}
            body.update(extra)
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post('/api/assistant/chat', body,
                                            format='json')
        return response, fake

    def test_json_turn_persists_both_messages(self):
        response, fake = self._post(
            [{'text': 'The Luna Slip Dress is KES 5,500.', 'id': 'int-9'}],
            message='what costs money?')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('Luna Slip Dress', payload['reply'])
        self.assertEqual(payload['unanswered'], False)
        self.assertTrue(payload['messageId'])
        self.assertEqual(AssistantMessage.objects.filter(
            role='user').count(), 1)
        assistant = AssistantMessage.objects.get(role='assistant')
        self.assertEqual(assistant.kind, AssistantMessage.Kind.REPLY)
        self.assertIn('Luna Slip Dress', assistant.content)
        conversation = AssistantConversation.objects.get()
        self.assertEqual(conversation.last_interaction_id, 'int-9')
        self.assertEqual(conversation.message_count, 2)
        self.assertTrue(AuditLog.objects.filter(
            action='assistant_message_sent').exists())

    def test_second_turn_chains_previous_interaction_id(self):
        first, first_fake = self._post([{'text': 'Hello!', 'id': 'int-1'}])
        conversation_id = first.json()['conversationId']

        second, second_fake = self._post(
            [{'text': 'Anything else?', 'id': 'int-2'}],
            message='and dresses?', conversationId=conversation_id)

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['conversationId'], conversation_id)
        self.assertEqual(AssistantConversation.objects.count(), 1)
        self.assertNotIn('previous_interaction_id',
                         first_fake.interactions.calls[0])
        self.assertEqual(
            second_fake.interactions.calls[0].get('previous_interaction_id'),
            'int-1')

    def test_stale_chain_falls_back_to_server_side_replay(self):
        conversation, _ = get_or_create_conversation()
        AssistantMessage.objects.create(conversation=conversation,
                                        role='user', content='old question')
        conversation.last_interaction_id = 'int-gone'
        conversation.save(update_fields=['last_interaction_id'])

        specs = [FakeAPIError(400, 'previous_interaction_id is invalid'),
                 {'text': 'Recovered.', 'id': 'int-new'}]
        with patch_gemini(specs) as fake:
            events = list(run_message(conversation, 'new question',
                                      ToolContext(), stream=False))

        done = [d for e, d in events if e == 'done']
        self.assertEqual(len(done), 1)
        calls = fake.interactions.calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].get('previous_interaction_id'), 'int-gone')
        self.assertNotIn('previous_interaction_id', calls[1])
        replayed = calls[1]['input']
        self.assertIsInstance(replayed, list)
        self.assertEqual(replayed[0]['type'], 'user_input')
        self.assertEqual(replayed[-1]['content'][0]['text'], 'new question')

    def test_tool_loop_returns_product_cards_and_tool_rows(self):
        specs = [
            {'calls': [('search_products', {'query': 'dress', 'limit': 5})],
             'id': 'int-3'},
            {'text': 'The Luna Slip Dress is KES 5,500.', 'id': 'int-4'},
        ]
        response, _ = self._post(specs, message='show me dresses')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['products']), 1)
        self.assertEqual(payload['products'][0]['slug'], 'luna-slip-dress')
        self.assertEqual(payload['products'][0]['price'], 5500.0)
        self.assertEqual([t['name'] for t in payload['tools']],
                         ['search_products'])
        self.assertEqual(payload['tools'][0]['status'], 'ok')
        tool = AssistantToolCall.objects.get()
        self.assertEqual(tool.tool_name, 'search_products')
        self.assertEqual(tool.status, AssistantToolCall.Status.OK)
        self.assertTrue(AuditLog.objects.filter(
            action='assistant_tool_called').exists())
        self.assertTrue(AuditLog.objects.filter(
            action='assistant_product_recommended').exists())
        assistant = AssistantMessage.objects.get(role='assistant')
        self.assertEqual(assistant.product_refs, ['luna-slip-dress'])

    def test_sse_streams_protocol_events(self):
        specs = [{'text': 'Hello from Modeza!', 'id': 'int-5'}]
        with patch_gemini(specs):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    '/api/assistant/chat', {'message': 'hi'}, format='json')
            body = b''.join(response.streaming_content).decode()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        self.assertIn('text/event-stream', response['Content-Type'])
        self.assertIn('event: meta', body)
        self.assertIn('event: delta', body)
        self.assertIn('event: done', body)
        self.assertNotIn('event: error', body)
        texts = [json.loads(line[6:])['text'] for line in body.split('\n')
                 if line.startswith('data: ') and '"text"' in line]
        self.assertEqual(''.join(texts), 'Hello from Modeza!')

    def test_sse_never_leaks_unanswered_marker(self):
        specs = [{'text': 'No idea. [[UNANSWERED]]', 'id': 'int-6'}]
        with patch_gemini(specs):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post('/api/assistant/chat',
                                            {'message': 'obscure question'},
                                            format='json')
            body = b''.join(response.streaming_content).decode()
        self.assertNotIn('[[UNANSWERED]]', body)
        message = AssistantMessage.objects.get(role='assistant')
        self.assertTrue(message.unanswered)
        self.assertNotIn('[[UNANSWERED]]', message.content)
        self.assertTrue(AssistantInsight.objects.filter(
            kind=AssistantInsight.Kind.UNANSWERED).exists())

    def test_gemini_failure_returns_friendly_error(self):
        specs = [FakeAPIError(503, 'service unavailable')] * 3
        with self.settings(GEMINI_MAX_RETRIES=2,
                           GEMINI_RETRY_BACKOFF_SECONDS=0):
            response, _ = self._post(specs, message='hello')

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertIn('trouble', payload['error']['message'])
        self.assertNotIn('503', payload['error']['message'])
        message = AssistantMessage.objects.get(role='assistant')
        self.assertEqual(message.kind, AssistantMessage.Kind.ERROR)
        self.assertTrue(AuditLog.objects.filter(
            action='assistant_error').exists())
        self.assertTrue(AssistantInsight.objects.filter(
            kind=AssistantInsight.Kind.GEMINI_ERROR).exists())

    def test_stream_error_before_text_is_retried_and_recovers(self):
        """A transient mid-stream failure with no text yet gets one retry."""
        specs = [
            {'events': [error_stream_event(
                code='UNAVAILABLE', message='upstream hiccup')]},
            {'text': 'Recovered!', 'id': 'int-7'},
        ]
        with patch_gemini(specs) as fake:
            with self.settings(GEMINI_RETRY_BACKOFF_SECONDS=0):
                with self.assertLogs('modeza.assistant', level='WARNING') as logs:
                    with self.captureOnCommitCallbacks(execute=True):
                        response = self.client.post(
                            '/api/assistant/chat', {'message': 'hi'},
                            format='json')
                        body = b''.join(
                            response.streaming_content).decode()

        self.assertIn('event: done', body)
        texts = [json.loads(line[6:])['text'] for line in body.split('\n')
                 if line.startswith('data: ') and '"text"' in line]
        self.assertEqual(''.join(texts), 'Recovered!')
        self.assertNotIn('event: error', body)
        self.assertEqual(len(fake.interactions.calls), 2)
        self.assertTrue(any('upstream hiccup' in line for line in logs.output))

    def test_stream_error_after_text_is_not_retried(self):
        """Once text has streamed, a failure surfaces instead of duplicating."""
        specs = [{'events': stream_before_error(
            'Half a reply', code='', message='connection reset')}]
        with patch_gemini(specs) as fake:
            with self.settings(GEMINI_RETRY_BACKOFF_SECONDS=0):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(
                        '/api/assistant/chat', {'message': 'hi'}, format='json')
                    body = b''.join(response.streaming_content).decode()

        self.assertEqual(len(fake.interactions.calls), 1)
        self.assertIn('event: error', body)
        error_line = next(line for line in body.split('\n')
                          if line.startswith('data: ') and '"code"' in line)
        payload = json.loads(error_line[6:])
        self.assertIn('trouble', payload['message'])
        self.assertNotIn('connection reset', payload['message'])

    def test_permanent_stream_error_fails_without_retry(self):
        specs = [{'events': [error_stream_event(
            code='PERMISSION_DENIED', message='API key not valid')]}]
        with patch_gemini(specs) as fake:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    '/api/assistant/chat', {'message': 'hi'}, format='json')
                body = b''.join(response.streaming_content).decode()

        self.assertEqual(len(fake.interactions.calls), 1)
        self.assertIn('event: error', body)
        message = AssistantMessage.objects.get(role='assistant')
        self.assertEqual(message.kind, AssistantMessage.Kind.ERROR)
        self.assertTrue(AuditLog.objects.filter(
            action='assistant_error').exists())

    def test_daily_rate_limit_returns_429_with_capacity_message(self):
        """JSON mode: per-day quota → 429, no retries, capacity copy."""
        daily = ('Rate limit exceeded for model gemini-3.5-flash-lite '
                 '(limit: 1500 requests per day on Free Tier).')
        with self.settings(GEMINI_MAX_RETRIES=2,
                           GEMINI_RETRY_BACKOFF_SECONDS=0):
            response, fake = self._post([FakeAPIError(429, daily)],
                                        message='hello')

        self.assertEqual(response.status_code, 429)
        payload = response.json()
        self.assertEqual(payload['error']['code'], 'RATE_LIMITED')
        self.assertIn("capacity", payload['error']['message'])
        self.assertNotIn('per day', payload['error']['message'])
        self.assertEqual(len(fake.interactions.calls), 1)

    def test_minute_rate_limit_still_retries_then_fails(self):
        """Minute-level 429s are transient: retries happen, then capacity
        copy is shown (they share the rate_limited code)."""
        minute = 'Rate limit exceeded: 20 requests per minute'
        with self.settings(GEMINI_MAX_RETRIES=2,
                           GEMINI_RETRY_BACKOFF_SECONDS=0):
            response, fake = self._post([FakeAPIError(429, minute)] * 3,
                                        message='hello')

        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(fake.interactions.calls), 3)
        self.assertIn('capacity', response.json()['error']['message'])

    def test_daily_rate_limit_stream_error_is_not_retried(self):
        """SSE mode: the exact production failure — one call, rate_limited
        code, capacity copy in the error event."""
        specs = [{'events': [error_stream_event(
            code='rate_limit_exceeded',
            message='Rate limit exceeded for model gemini-3.5-flash-lite '
                    '(limit: 1500 requests per day on Free Tier).')]}]
        with patch_gemini(specs) as fake:
            with self.settings(GEMINI_RETRY_BACKOFF_SECONDS=0):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(
                        '/api/assistant/chat', {'message': 'hi'},
                        format='json')
                    body = b''.join(response.streaming_content).decode()

        self.assertEqual(len(fake.interactions.calls), 1)
        self.assertIn('event: error', body)
        error_line = next(line for line in body.split('\n')
                          if line.startswith('data: ') and '"code"' in line)
        payload = json.loads(error_line[6:])
        self.assertEqual(payload['code'], 'rate_limited')
        self.assertIn('capacity', payload['message'])
        self.assertNotIn('per day', payload['message'])

    def test_support_escalation_is_audited_during_a_chat_turn(self):
        specs = [
            {'calls': [('create_support_request',
                        {'message': 'the checkout button is broken'})],
             'id': 'int-7'},
            {'text': 'Support has been notified.', 'id': 'int-8'},
        ]
        response, _ = self._post(specs, message='I need support')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(
            action='assistant_escalated').exists())

    def test_empty_message_rejected(self):
        response = self.client.post('/api/assistant/chat',
                                    {'message': '   ', 'stream': False},
                                    format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'EMPTY_MESSAGE')

    def test_rate_limit_returns_429_envelope(self):
        specs = [{'text': 'ok', 'id': f'int-{i}'} for i in range(16)]
        with patch_gemini(specs):
            statuses = []
            for _ in range(16):
                response = self.client.post(
                    '/api/assistant/chat', {'message': 'hi', 'stream': False},
                    format='json')
                statuses.append(response.status_code)
        self.assertEqual(statuses[:15], [200] * 15)
        self.assertEqual(statuses[15], 429)
        cache.clear()

    def test_throttle_scope_follows_authentication(self):
        from django.contrib.auth.models import AnonymousUser

        request = APIRequestFactory().get('/api/assistant/chat')
        request.user = AnonymousUser()
        throttle = AssistantRateThrottle()
        throttle.allow_request(request, None)
        self.assertEqual(throttle.scope, 'assistant_anon')

        user = make_user('scope', email='scope@example.com')
        request2 = APIRequestFactory().get('/api/assistant/chat')
        request2.user = user
        throttle2 = AssistantRateThrottle()
        throttle2.allow_request(request2, None)
        self.assertEqual(throttle2.scope, 'assistant_user')
        cache.clear()


# ---------------------------------------------------------------------------
# History access
# ---------------------------------------------------------------------------

class AssistantHistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner = make_user('owner')
        self.stranger = make_user('stranger')
        self.conversation = AssistantConversation.objects.create(
            user=self.owner)
        AssistantMessage.objects.create(conversation=self.conversation,
                                        role='user', content='hello')

    def test_owner_can_read_history(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            '/api/assistant/history',
            {'conversationId': str(self.conversation.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['messages']), 1)

    def test_stranger_cannot_read_history(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            '/api/assistant/history',
            {'conversationId': str(self.conversation.pk)})
        self.assertEqual(response.status_code, 403)

    def test_guest_conversation_can_be_resumed_by_id(self):
        guest, _ = get_or_create_conversation(session_key='cart-abc')
        resumed, created = get_or_create_conversation(
            session_key='cart-abc', conversation_id=str(guest.pk))
        self.assertFalse(created)
        self.assertEqual(resumed.pk, guest.pk)

    def test_guest_conversation_is_not_handed_to_signed_in_stranger(self):
        guest, _ = get_or_create_conversation(session_key='cart-abc')
        resumed, created = get_or_create_conversation(
            user=self.stranger, session_key='their-own-session',
            conversation_id=str(guest.pk))
        self.assertTrue(created)
        self.assertNotEqual(resumed.pk, guest.pk)

    def test_guest_conversation_is_claimed_by_owner(self):
        guest, _ = get_or_create_conversation(session_key='cart-abc')
        resumed, created = get_or_create_conversation(
            user=self.owner, conversation_id=str(guest.pk))
        self.assertFalse(created)
        resumed.refresh_from_db()
        self.assertEqual(resumed.user_id, self.owner.pk)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class ProductToolTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category = Category.objects.create(name='Dresses',
                                                slug='dresses')
        self.dress = Product.objects.create(
            category=self.category, name='Luna Slip Dress',
            slug='luna-slip-dress', description='Bias-cut slip dress.',
            price_minor=550000, status=Product.Status.ACTIVE)
        ProductVariant.objects.create(product=self.dress, sku='LUNA-M',
                                      size='M', color='black',
                                      stock_quantity=4)
        self.gown = Product.objects.create(
            category=self.category, name='Aurora Gown', slug='aurora-gown',
            description='A gown for weddings.', price_minor=1200000,
            status=Product.Status.ACTIVE)
        ProductVariant.objects.create(product=self.gown, sku='AUR-S',
                                      size='S', color='ivory',
                                      stock_quantity=0)
        self.context = ToolContext()

    def test_search_filters_colour_and_stock(self):
        result = tools_module.execute(
            'search_products', {'colour': 'black', 'in_stock': True},
            self.context)
        self.assertEqual(result.status, 'ok')
        self.assertEqual([p['slug'] for p in result.payload['products']],
                         ['luna-slip-dress'])

    def test_search_by_budget(self):
        result = tools_module.execute(
            'search_products', {'max_price_kes': 6000}, self.context)
        self.assertEqual(result.payload['total'], 1)
        self.assertEqual(result.payload['products'][0]['slug'],
                         'luna-slip-dress')

    def test_search_never_returns_exact_stock(self):
        result = tools_module.execute('search_products', {}, self.context)
        blob = json.dumps(result.payload)
        self.assertNotIn('stock_quantity', blob)
        product = result.payload['products'][0]
        self.assertNotIn('stock', json.dumps(product))
        self.assertIn('available', product)
        self.assertIn('lowStock', product)

    def test_search_zero_results(self):
        result = tools_module.execute(
            'search_products', {'query': 'spacesuit'}, self.context)
        self.assertEqual(result.payload['total'], 0)
        self.assertEqual(result.payload['products'], [])

    def test_variant_availability(self):
        result = tools_module.execute(
            'check_variant_availability',
            {'product': 'luna-slip-dress', 'size': 'M', 'colour': 'black'},
            self.context)
        self.assertEqual(result.payload['matches'][0]['available'], True)

    def test_variant_availability_wrong_size(self):
        result = tools_module.execute(
            'check_variant_availability',
            {'product': 'luna-slip-dress', 'size': 'XL'}, self.context)
        self.assertEqual(result.payload['matches'], [])
        self.assertIn('message', result.payload)

    def test_compare_products(self):
        result = tools_module.execute(
            'compare_products',
            {'slugs': ['luna-slip-dress', 'aurora-gown']}, self.context)
        self.assertEqual(len(result.payload['products']), 2)
        self.assertEqual(result.payload['products'][1]['available'], False)

    def test_unknown_tool_is_an_error_execution(self):
        result = tools_module.execute('drop_database', {}, self.context)
        self.assertEqual(result.status, 'error')
        self.assertEqual(result.error_code, 'unknown_tool')

    def test_sanitize_arguments_truncates_and_drops_junk(self):
        clean = sanitize_arguments({
            'query': 'x' * 1000,
            'limit': 99999999999,
            'in_stock': True,
            'nested': {'a': 1},
            'slugs': ['ok', 3, 'also-ok'],
        })
        self.assertEqual(len(clean['query']), 300)
        self.assertNotIn('nested', clean)
        self.assertEqual(clean['slugs'], ['ok', 'also-ok'])
        self.assertEqual(clean['in_stock'], True)


class PolicyToolTests(TestCase):
    def setUp(self):
        self.context = ToolContext()

    def test_shipping_policy(self):
        result = tools_module.execute('get_store_policy',
                                      {'topic': 'shipping'}, self.context)
        self.assertEqual(result.payload['topic'], 'shipping')
        self.assertIn('KES 15,000', json.dumps(result.payload))

    def test_alias_mapping(self):
        result = tools_module.execute('get_store_policy',
                                      {'topic': 'refund'}, self.context)
        self.assertEqual(result.payload['topic'], 'returns')

    def test_unknown_topic_is_reported(self):
        result = tools_module.execute('get_store_policy',
                                      {'topic': 'astrology'}, self.context)
        self.assertIn('error', result.payload)


class PromotionToolTests(TestCase):
    def setUp(self):
        cache.clear()
        self.context = ToolContext()
        self.coupon = Promotion.objects.create(
            name='Welcome 10', promotion_type='percentage',
            status=Promotion.Status.ACTIVE, discount_percent=10,
            coupon_code='WELCOME10', coupon_code_normalized='WELCOME10',
            is_automatic=False)
        self.auto = Promotion.objects.create(
            name='Free delivery over 15k', promotion_type='free_shipping',
            status=Promotion.Status.ACTIVE, is_automatic=True)

    def test_active_promotions_never_reveal_coupon_codes(self):
        result = tools_module.execute('get_active_promotions', {},
                                      self.context)
        blob = json.dumps(result.payload)
        self.assertNotIn('WELCOME10', blob)
        self.assertIn('AVAILABLE_AT_CHECKOUT', blob)
        names = [p['name'] for p in result.payload['promotions']]
        self.assertIn('Free delivery over 15k', names)
        self.assertIn('Welcome 10',
                      [c['name'] for c in result.payload['couponOffers']])

    def test_validate_code_reports_validity_without_code(self):
        result = tools_module.execute('validate_promotion_code',
                                      {'code': 'welcome10'}, self.context)
        self.assertTrue(result.payload['valid'])
        self.assertEqual(result.payload['code'], 'AVAILABLE_AT_CHECKOUT')
        self.assertNotIn('WELCOME10', json.dumps(result.payload))

    def test_validate_unknown_code(self):
        result = tools_module.execute('validate_promotion_code',
                                      {'code': 'NOPE'}, self.context)
        self.assertFalse(result.payload['valid'])
        self.assertEqual(result.payload['reason'], 'unknown_code')

    def test_validate_expired_code(self):
        self.coupon.ends_at = timezone.now() - timedelta(days=1)
        self.coupon.save(update_fields=['ends_at'])
        result = tools_module.execute('validate_promotion_code',
                                      {'code': 'WELCOME10'}, self.context)
        self.assertFalse(result.payload['valid'])
        self.assertEqual(result.payload['reason'], 'expired')


class OrderToolTests(TestCase):
    def setUp(self):
        cache.clear()
        self.context_owner = None
        self.alice = make_user('alice')
        self.bob = make_user('bob')
        self.order = Order.objects.create(
            order_number='MDZ-2026-000042', user=self.alice,
            subtotal_minor=550000, total_minor=658000,
            customer={'fullName': 'Alice'}, status='shipped',
            payment_status='paid')

    def test_owner_sees_own_order(self):
        context = ToolContext(user=self.alice)
        result = tools_module.execute(
            'get_order_status', {'order_number': 'MDZ-2026-000042'}, context)
        self.assertEqual(result.payload['status'], 'shipped')
        self.assertNotIn('error', result.payload)

    def test_other_customer_is_denied(self):
        context = ToolContext(user=self.bob)
        result = tools_module.execute(
            'get_order_status', {'order_number': 'MDZ-2026-000042'}, context)
        self.assertEqual(result.payload['error']['code'], 'not_authorized')

    def test_guest_without_cart_key_is_denied(self):
        result = tools_module.execute(
            'get_order_status', {'order_number': 'MDZ-2026-000042'},
            ToolContext())
        self.assertEqual(result.payload['error']['code'], 'not_authorized')

    def test_unknown_order_is_not_found(self):
        context = ToolContext(user=self.alice)
        result = tools_module.execute(
            'get_order_status', {'order_number': 'MDZ-2026-999999'}, context)
        self.assertEqual(result.payload['error']['code'], 'not_found')

    def test_list_orders_requires_identity(self):
        result = tools_module.execute('get_customer_orders', {},
                                      ToolContext())
        self.assertEqual(result.payload['error']['code'], 'auth_required')

    def test_list_orders_returns_own(self):
        context = ToolContext(user=self.alice)
        result = tools_module.execute('get_customer_orders', {}, context)
        self.assertEqual(result.payload['count'], 1)
        self.assertEqual(result.payload['orders'][0]['orderNumber'],
                         'MDZ-2026-000042')
        blob = json.dumps(result.payload)
        self.assertNotIn(str(self.order.pk), blob)


class ActionToolTests(TestCase):
    def setUp(self):
        cache.clear()
        self.context = ToolContext()
        self.staff = make_user('staff', is_staff=True)
        category = Category.objects.create(name='Dresses', slug='dresses')
        self.product = Product.objects.create(
            category=category, name='Luna Slip Dress',
            slug='luna-slip-dress', description='Slip dress.',
            price_minor=550000, status=Product.Status.ACTIVE)
        self.variant = ProductVariant.objects.create(
            product=self.product, sku='LUNA-M', size='M', color='black',
            stock_quantity=2)

    def test_prepare_add_to_cart_validates_and_prepares(self):
        result = tools_module.execute(
            'prepare_add_to_cart',
            {'product': 'luna-slip-dress', 'size': 'M', 'quantity': 1},
            self.context)
        action = result.payload['action']
        self.assertEqual(action['type'], 'add_to_cart')
        self.assertEqual(action['slug'], 'luna-slip-dress')
        self.assertEqual(action['variantSku'], 'LUNA-M')
        self.assertEqual(action['quantity'], 1)

    def test_prepare_add_to_cart_reports_out_of_stock(self):
        self.variant.stock_quantity = 0
        self.variant.save(update_fields=['stock_quantity'])
        result = tools_module.execute(
            'prepare_add_to_cart',
            {'product': 'luna-slip-dress', 'size': 'M'}, self.context)
        self.assertEqual(result.payload['error']['code'], 'out_of_stock')
        self.assertNotIn('action', result.payload)

    def test_prepare_add_to_cart_quantity_clamped(self):
        result = tools_module.execute(
            'prepare_add_to_cart',
            {'product': 'luna-slip-dress', 'quantity': 99}, self.context)
        self.assertEqual(result.payload['action']['quantity'], 10)

    def test_support_request_notifies_staff_and_redacts_pin(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = tools_module.execute(
                'create_support_request',
                {'message': 'my mpesa pin is 123456 and order is stuck'},
                self.context)
        self.assertTrue(result.payload['ok'])
        notification = AdminNotification.objects.filter(
            title='Assistant: customer needs support').get()
        self.assertNotIn('123456', notification.message)
        self.assertIn('order is stuck', notification.message)

    def test_support_request_requires_message(self):
        result = tools_module.execute('create_support_request',
                                      {'message': '  '}, self.context)
        self.assertIn('error', result.payload)


# ---------------------------------------------------------------------------
# Conversation internals
# ---------------------------------------------------------------------------

class MarkerFilterTests(TestCase):
    def test_marker_split_across_chunks_is_never_emitted(self):
        marker = MarkerFilter()
        out = marker.feed('Sorry, no idea. [[UNAN')
        out += marker.feed('SWERED]] and more')
        self.assertNotIn('[[', out)
        self.assertTrue(marker.found)
        self.assertIn('and more', marker.flush() or 'and more')

    def test_plain_text_passes_through(self):
        marker = MarkerFilter()
        self.assertEqual(marker.feed('Hello there'), 'Hello there')
        self.assertEqual(marker.flush(), '')
        self.assertFalse(marker.found)

    def test_partial_tail_on_flush_counts_as_unanswered(self):
        marker = MarkerFilter()
        marker.feed('I could not find that [[U')
        self.assertEqual(marker.flush(), '')
        self.assertTrue(marker.found)


class ClassifyTests(TestCase):
    def test_stale_chain_detected_from_400(self):
        code, retryable = _classify(FakeAPIError(
            400, 'invalid previous_interaction_id supplied'))
        self.assertEqual(code, 'stale_interaction')
        self.assertFalse(retryable)

    def test_5xx_and_timeouts_are_retryable(self):
        self.assertEqual(_classify(FakeAPIError(503))[1], True)
        self.assertEqual(_classify(TimeoutError('timed out'))[1], True)
        self.assertEqual(_classify(FakeAPIError(401))[1], False)


class StreamErrorDetailTests(TestCase):
    def test_detail_is_read_from_the_error_payload(self):
        event = error_stream_event(
            code='https://googleapis.com/UNAVAILABLE',
            message='The service is currently unavailable.')
        self.assertEqual(
            _stream_error_detail(event),
            ('https://googleapis.com/UNAVAILABLE',
             'The service is currently unavailable.'))

    def test_missing_payload_falls_back_without_crashing(self):
        code, message = _stream_error_detail(ns(event_type='error'))
        self.assertEqual(code, '')
        self.assertIn(message, ('', 'stream error'))

    def test_empty_error_is_retryable(self):
        self.assertTrue(_stream_error_retryable('', ''))

    def test_unavailable_is_retryable(self):
        self.assertTrue(_stream_error_retryable(
            'https://googleapis.com/UNAVAILABLE', 'try again later'))

    def test_permission_error_is_not_retryable(self):
        self.assertFalse(_stream_error_retryable(
            'PERMISSION_DENIED', 'API key not valid for this API'))

    def test_invalid_argument_is_not_retryable(self):
        self.assertFalse(_stream_error_retryable(
            'INVALID_ARGUMENT', 'invalid model'))

    def test_daily_rate_limit_is_not_retryable(self):
        self.assertFalse(_stream_error_retryable(
            'rate_limit_exceeded',
            'Rate limit exceeded for model gemini-3.5-flash-lite '
            '(limit: 1500 requests per day on Free Tier).'))

    def test_minute_rate_limit_is_retryable(self):
        self.assertTrue(_stream_error_retryable(
            'rate_limit_exceeded',
            'Rate limit exceeded: 30 requests per minute, retry in 12s.'))

    def test_daily_rate_limit_is_not_retryable_at_call_time(self):
        code, retryable = _classify(FakeAPIError(
            429, 'Rate limit exceeded: 20 requests per day on Free Tier'))
        self.assertEqual(code, 'rate_limited')
        self.assertFalse(retryable)

    def test_minute_rate_limit_is_retryable_at_call_time(self):
        code, retryable = _classify(FakeAPIError(
            429, 'Rate limit exceeded: 20 requests per minute'))
        self.assertEqual(code, 'rate_limited')
        self.assertTrue(retryable)


class InsightTests(TestCase):
    def test_insight_counts_are_aggregated(self):
        record_insight(AssistantInsight.Kind.UNANSWERED, 'How do I wash silk?')
        record_insight(AssistantInsight.Kind.UNANSWERED, 'how do   I wash silk?')
        insight = AssistantInsight.objects.get(
            kind=AssistantInsight.Kind.UNANSWERED)
        self.assertEqual(insight.count, 2)


# ---------------------------------------------------------------------------
# Admin analytics + retention
# ---------------------------------------------------------------------------

class AnalyticsAndRetentionTests(TestCase):
    def setUp(self):
        cache.clear()
        conversation = AssistantConversation.objects.create()
        user_msg = AssistantMessage.objects.create(
            conversation=conversation, role='user', content='a question')
        AssistantMessage.objects.create(
            conversation=conversation, role='assistant',
            content='an answer', latency_ms=400)
        AssistantToolCall.objects.create(
            conversation=conversation, tool_name='search_products',
            duration_ms=12)
        record_insight(AssistantInsight.Kind.UNANSWERED, 'obscure ask')
        self.conversation = conversation

    def test_analytics_aggregates(self):
        data = assistant_analytics(days=30)
        self.assertEqual(data['totals']['questions'], 1)
        self.assertEqual(data['totals']['replies'], 1)
        self.assertEqual(data['totals']['toolCalls'], 1)
        self.assertEqual(data['totals']['unanswered'], 0)
        self.assertEqual(data['toolUsage'][0]['name'], 'search_products')
        self.assertEqual(len(data['daily']), 30)

    def test_purge_command_respects_retention(self):
        old = AssistantConversation.objects.create()
        AssistantMessage.objects.create(conversation=old, role='user',
                                        content='ancient')
        type(old).objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - timedelta(days=120))

        call_command('purge_assistant_conversations', '--dry-run')
        self.assertEqual(AssistantConversation.objects.count(), 2)

        call_command('purge_assistant_conversations')
        self.assertFalse(AssistantConversation.objects.filter(
            pk=old.pk).exists())
        self.assertTrue(AssistantConversation.objects.filter(
            pk=self.conversation.pk).exists())


class SuggestionsTests(TestCase):
    def test_suggestions_endpoint(self):
        cache.clear()
        response = APIClient().get('/api/assistant/suggestions')
        self.assertEqual(response.status_code, 200)
        self.assertIn('suggestions', response.json())
        self.assertIn('welcome', response.json())
        cache.clear()
