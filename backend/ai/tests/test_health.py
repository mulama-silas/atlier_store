"""API tests for ``GET /api/ai/health/`` (Gemini mocked)."""
from types import SimpleNamespace as ns
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ai.gemini_service import (
    AIAuthenticationError, AIConfigurationError, AIModelError,
    AIProviderUnavailableError, AITimeoutError, GeminiService)


@override_settings(GEMINI_API_KEY='test-key',
                   GEMINI_MODEL='gemini-3.5-flash-lite',
                   GEMINI_HEALTH_CACHE_SECONDS=60)
class HealthViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        cache.clear()

    def _stub_create(self, *errors):
        """Patch GeminiService._create to raise ``errors`` in order."""
        return patch.object(GeminiService, '_create', side_effect=list(errors))

    def _ok(self):
        return ns(output_text='MODEZA_AI_OK', steps=[])

    def test_healthy_response_shape(self):
        with self._stub_create(self._ok()):
            response = self.client.get('/api/ai/health/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['status'], 'healthy')
        self.assertEqual(payload['provider'], 'google_gemini')
        self.assertEqual(payload['model'], 'gemini-3.5-flash-lite')
        self.assertEqual(payload['response'], 'MODEZA_AI_OK')
        self.assertIn('latency_ms', payload)

    def test_health_without_trailing_slash(self):
        with self._stub_create(self._ok()):
            response = self.client.get('/api/ai/health')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

    def test_authentication_failure_shape(self):
        with self._stub_create(
                AIAuthenticationError('API key not valid.'),
                AIAuthenticationError('API key not valid.')):
            response = self.client.get('/api/ai/health/')
        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['status'], 'unhealthy')
        self.assertEqual(payload['error_code'], 'AUTHENTICATION_ERROR')
        self.assertTrue(payload['message'])
        body = response.content.decode()
        self.assertNotIn('test-key', body)
        self.assertNotIn('Traceback', body)

    def test_configuration_failure_when_key_missing(self):
        with patch.object(GeminiService, '_create') as create:
            with override_settings(GEMINI_API_KEY=''):
                response = self.client.get('/api/ai/health/')
            create.assert_not_called()
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error_code'], 'CONFIGURATION_ERROR')

    def test_invalid_model_failure(self):
        with patch.object(GeminiService, '_create',
                          side_effect=[AIModelError('gemini-nope not found')]):
            response = self.client.get('/api/ai/health/')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error_code'], 'MODEL_NOT_FOUND')

    def test_provider_unavailable_shape(self):
        with self._stub_create(
                AIProviderUnavailableError('overloaded'),
                AIProviderUnavailableError('overloaded')):
            response = self.client.get('/api/ai/health/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error_code'], 'PROVIDER_UNAVAILABLE')

    def test_timeout_shape(self):
        with self._stub_create(AITimeoutError('timed out'),
                               AITimeoutError('timed out')):
            response = self.client.get('/api/ai/health/')
        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertEqual(payload['error_code'], 'AI_TIMEOUT')
        self.assertEqual(payload['message'],
                         'The AI assistant is temporarily unavailable. '
                         'Please try again.')

    def test_cache_short_ciruits_repeat_probes(self):
        with patch.object(GeminiService, '_create',
                          return_value=self._ok()) as create:
            self.client.get('/api/ai/health/')
            self.client.get('/api/ai/health/')
            self.assertEqual(create.call_count, 1)

    def test_failure_is_not_cached(self):
        with patch.object(GeminiService, '_create',
                          side_effect=[AIConfigurationError('no key')]):
            response = self.client.get('/api/ai/health/')
        self.assertEqual(response.status_code, 503)
        # A later success is not masked by a cached failure.
        with patch.object(GeminiService, '_create',
                          return_value=self._ok()) as create:
            response = self.client.get('/api/ai/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(create.call_count, 1)