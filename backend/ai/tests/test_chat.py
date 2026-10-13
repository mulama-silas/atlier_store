"""API tests for ``POST /api/ai/chat/`` (Gemini mocked).

The only live boundary this isolates is the turn engine: ``run_message``
(shared with the assistant app) drives ``assistant.services.gemini.run_turn``,
which is patched here — nothing touches Google.
"""
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from assistant.models import AssistantConversation, AssistantMessage
from assistant.services.gemini import (GeminiFailed, GeminiUnavailable,
                                       TurnResult)
from assistant.services import tools as tools_module
from assistant.services.tools import ToolContext
from orders.models import Order

User = get_user_model()


def make_user(username, **kwargs):
    password = kwargs.pop('password', 'pw')
    email = kwargs.pop('email', f'{username}@example.com')
    return User.objects.create_user(username=username, email=email,
                                    password=password, **kwargs)


def make_turn(text='Hello! How can I help?', interaction_id='int-1',
              status='completed'):
    """Iterator shaped like ``gemini.run_turn``'s output for one round."""
    def gen():
        if text:
            half = max(1, len(text) // 2)
            yield ('delta', text[:half])
            yield ('delta', text[half:])
        yield ('result', TurnResult(
            text=text, interaction_id=interaction_id, usage={},
            status=status, rounds=1))
    return gen()


def failing_turn(error):
    def gen():
        raise error
        yield  # pragma: no cover
    return gen()


class ChatApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()
        self.alice = make_user('alice')
        self.bob = make_user('bob')

    def _post_json(self, body):
        return self.client.post('/api/ai/chat/', body, format='json')

    def _post_stream(self, body):
        body = dict(body, stream=True)
        return self.client.post('/api/ai/chat/', body, format='json')

    # -- validation --------------------------------------------------------

    def test_json_success(self):
        with patch('assistant.services.gemini.run_turn',
                   return_value=make_turn(
                       'Yes, we have the black dress in medium — KES 2,450.')):
            response = self._post_json(
                {'message': 'Do you have a black dress in medium?',
                 'stream': False})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertIn('medium', payload['message'])
        self.assertTrue(payload['conversation_id'])
        uuid.UUID(payload['conversation_id'])

    def test_json_success_with_camel_case_conversation_id(self):
        conversation = AssistantConversation.objects.create()
        with patch('assistant.services.gemini.run_turn',
                   return_value=make_turn('Sure.')):
            response = self._post_json(
                {'message': 'hi', 'conversationId': str(conversation.pk),
                 'stream': False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['conversation_id'],
                         str(conversation.pk))

    def test_stream_success_uses_sse(self):
        with patch('assistant.services.gemini.run_turn',
                   return_value=make_turn('Hello there!')):
            response = self._post_stream({'message': 'Hello'})
            body = b''.join(response.streaming_content).decode()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        self.assertIn('event: delta', body)
        self.assertIn('event: done', body)
        self.assertEqual(self._delta_text(body), 'Hello there!')

    def _delta_text(self, body):
        chunks = []
        for event in body.split('\n\n'):
            if event.startswith('event: delta'):
                for line in event.splitlines():
                    if line.startswith('data: '):
                        chunks.append(json.loads(line[len('data: '):])['text'])
        return ''.join(chunks)

    def test_stream_error_event(self):
        with patch('assistant.services.gemini.run_turn',
                   return_value=failing_turn(
                       GeminiFailed('down', code='timeout', retryable=True))):
            response = self._post_stream({'message': 'Hello'})
            body = b''.join(response.streaming_content).decode()
        self.assertEqual(response.status_code, 200)  # SSE carries the error
        self.assertIn('event: error', body)

    def test_empty_message_rejected(self):
        response = self._post_json({'message': '   ', 'stream': False})
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error_code'], 'VALIDATION_ERROR')
        self.assertTrue(payload['message'])

    def test_missing_message_rejected(self):
        response = self._post_json({'stream': False})
        self.assertEqual(response.status_code, 400)

    def test_oversized_message_rejected(self):
        response = self._post_json({'message': 'x' * 2001, 'stream': False})
        self.assertEqual(response.status_code, 400)

    def test_bad_conversation_id_rejected(self):
        response = self._post_json({'message': 'hi', 'stream': False,
                                    'conversation_id': 'not-a-uuid'})
        self.assertEqual(response.status_code, 400)

    def test_customer_id_in_body_is_never_trusted(self):
        # A caller claiming to be another customer (or passing a foreign
        # thread id) must never attach to that thread.
        foreign = AssistantConversation.objects.create(user=self.alice)
        with patch('assistant.services.gemini.run_turn',
                   return_value=make_turn('Ok.')):
            response = self._post_json(
                {'message': 'hi', 'stream': False,
                 'customer_id': str(self.bob.pk),
                 'conversation_id': str(foreign.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()['conversation_id'],
                            str(foreign.pk))
        foreign.refresh_from_db()
        self.assertEqual(foreign.message_count, 0,
                         'A guest must not write into a customer thread')

    # -- conversation handling ---------------------------------------------

    def test_guest_resumes_conversation_by_uuid(self):
        conversation = AssistantConversation.objects.create(session_key='')
        with patch('assistant.services.gemini.run_turn',
                   return_value=make_turn('Hello back.')):
            response = self._post_json(
                {'message': 'Hello', 'stream': False,
                 'conversation_id': str(conversation.pk)})
        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.message_count, 2)
        self.assertEqual(
            conversation.messages.filter(role=AssistantMessage.Role.ASSISTANT)
            .count(), 1)

    def test_authenticated_conversation_bound_to_user(self):
        self.client.force_authenticate(self.alice)
        conversation = AssistantConversation.objects.create(user=self.alice)
        with patch('assistant.services.gemini.run_turn',
                   return_value=make_turn('Account safe.')):
            response = self._post_json(
                {'message': 'hi', 'stream': False,
                 'conversation_id': str(conversation.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['conversation_id'],
                         str(conversation.pk))
        conversation.refresh_from_db()
        self.assertEqual(conversation.user_id, self.alice.pk)

    def test_cannot_write_into_another_users_thread(self):
        self.client.force_authenticate(self.bob)
        foreign = AssistantConversation.objects.create(user=self.alice)
        with patch('assistant.services.gemini.run_turn',
                   return_value=make_turn('New thread.')):
            response = self._post_json(
                {'message': 'hi', 'stream': False,
                 'conversation_id': str(foreign.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()['conversation_id'],
                            str(foreign.pk))
        foreign.refresh_from_db()
        self.assertEqual(foreign.message_count, 0,
                         'Bob must not have written into Alice\u2019s thread')

    # -- Gemini failures ---------------------------------------------------

    def test_timeout_returns_502_json(self):
        with patch('assistant.services.gemini.run_turn',
                   return_value=failing_turn(
                       GeminiFailed('Gemini request failed (timeout)',
                                    code='timeout', retryable=True))):
            response = self._post_json({'message': 'hello', 'stream': False})
        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error_code'], 'TIMEOUT')

    def test_not_configured_returns_502_json(self):
        with patch('assistant.services.gemini.run_turn',
                   return_value=failing_turn(GeminiUnavailable())):
            response = self._post_json({'message': 'hello', 'stream': False})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error_code'],
                         'GEMINI_NOT_CONFIGURED')

    def test_rate_limit_returns_429(self):
        with patch('assistant.services.gemini.run_turn',
                   return_value=make_turn('ok')):
            statuses = []
            for _ in range(16):
                response = self._post_json(
                    {'message': 'ok', 'stream': False})
                statuses.append(response.status_code)
        self.assertEqual(statuses[:15], [200] * 15)
        self.assertEqual(statuses[15], 429)
        cache.clear()

    # -- authorization (customer isolation) --------------------------------

    def test_order_status_refuses_another_customers_order(self):
        order = Order.objects.create(
            order_number='MDZ-2026-000777', user=self.alice,
            subtotal_minor=550000, total_minor=658000,
            customer={'fullName': 'Alice'}, status='shipped',
            payment_status='paid')
        result = tools_module.execute(
            'get_order_status',
            {'order_number': 'MDZ-2026-000777'},
            ToolContext(user=self.bob))
        self.assertEqual(result.payload['error']['code'], 'not_authorized')

    def test_order_listing_never_leaks_another_customers_orders(self):
        Order.objects.create(
            order_number='MDZ-2026-000778', user=self.alice,
            subtotal_minor=1000, total_minor=1000,
            customer={'fullName': 'Alice'}, status='processing',
            payment_status='paid')
        result = tools_module.execute(
            'get_customer_orders', {}, ToolContext(user=self.bob))
        blob = __import__('json').dumps(result.payload)
        self.assertNotIn('000778', blob)
        self.assertNotIn('Alice', blob)
        self.assertEqual(result.payload.get('count', 0), 0)

    def test_guest_without_cart_identity_cannot_read_orders(self):
        result = tools_module.execute(
            'get_customer_orders', {}, ToolContext())
        self.assertEqual(result.payload['error']['code'], 'auth_required')