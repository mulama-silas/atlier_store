"""Unit tests for :mod:`ai.gemini_service` (Gemini SDK fully mocked).

Run with a real API key by setting ``RUN_GEMINI_INTEGRATION=1`` (a separate,
opt-in integration test in ``test_integration.py``) — the unit suite here
never touches the network.
"""
from types import SimpleNamespace as ns
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ai.gemini_service import (
    AIAuthenticationError, AIConfigurationError, AIContentBlockedError,
    AIModelError, AINetworkError, AIProviderUnavailableError,
    AIQuotaExceededError, AIRateLimitError, AITimeoutError,
    AIUnexpectedError, GeminiService, _extract_text, classify_error)


class FakeAPIError(Exception):
    """Looks like the google-genai SDK errors (numeric ``code`` + text)."""

    def __init__(self, code, message='upstream boom'):
        super().__init__(message)
        self.code = code
        self.message = message


class _FakeTimeout(Exception):
    """Errs ONLY by class name (like httpx/timeout variants)."""


class _FakeConnectionError(Exception):
    pass


def _service(api_key='k', model='gemini-3.5-flash-lite', max_retries=0,
             backoff=0.0, timeout=5.0):
    return GeminiService(api_key=api_key, model=model, timeout=timeout,
                         max_retries=max_retries, backoff=backoff)


class ConfigTests(SimpleTestCase):
    def test_missing_api_key_raises_on_client_access(self):
        service = GeminiService(api_key='', model='gemini-3.5-flash-lite')
        with self.assertRaises(AIConfigurationError) as ctx:
            service.client
        self.assertEqual(ctx.exception.error_code, 'CONFIGURATION_ERROR')
        self.assertEqual(ctx.exception.http_status, 503)

    def test_configured_service_builds_client_lazily(self):
        service = _service()
        with patch('google.genai.Client', return_value=ns()) as m:
            self.assertIs(service.client, m.return_value)
            service.reset_client()
            service.client
            self.assertEqual(m.call_count, 2)

    def test_empty_model_reported_as_config(self):
        report = _service(model='').health_check()
        self.assertFalse(report.ok)
        self.assertIsInstance(report.error, AIConfigurationError)
        self.assertEqual(report.error.error_code, 'CONFIGURATION_ERROR')


class HealthCheckTests(SimpleTestCase):
    def _stub(self, interaction):
        fake = ns(interactions=ns(create=lambda **kw: interaction))
        service = _service()
        service._client = fake
        return service

    def _raise(self, error):
        def boom(**kw):
            raise error
        fake = ns(interactions=ns(create=boom))
        service = _service()
        service._client = fake
        return service

    def test_success(self):
        interaction = ns(output_text='MODEZA_AI_OK', steps=[])
        report = self._stub(interaction).health_check()
        self.assertTrue(report.ok)
        self.assertEqual(report.model, 'gemini-3.5-flash-lite')
        self.assertEqual(report.text, 'MODEZA_AI_OK')
        self.assertGreaterEqual(report.latency_ms, 0)
        self.assertIsNone(report.error)

    def test_probe_uses_configuration(self):
        service = _service(model='gemini-3.5-flash-lite')
        captured = {}
        def create(**kw):
            captured.update(kw)
            return ns(output_text='MODEZA_AI_OK', steps=[])
        service._client = ns(interactions=ns(create=create))
        service.health_check()
        self.assertEqual(captured['model'], 'gemini-3.5-flash-lite')
        self.assertFalse(captured['stream'])
        self.assertIn('MODEZA_AI_OK', captured['input'])

    def test_authentication_error(self):
        report = self._raise(FakeAPIError(401, 'API key not valid.')).health_check()
        self.assertFalse(report.ok)
        self.assertIsInstance(report.error, AIAuthenticationError)
        self.assertEqual(report.error.error_code, 'AUTHENTICATION_ERROR')
        self.assertEqual(report.error.http_status, 502)

    def test_invalid_model(self):
        report = self._raise(FakeAPIError(404, 'models/gemini-nope not found.')).health_check()
        self.assertFalse(report.ok)
        self.assertIsInstance(report.error, AIModelError)
        self.assertEqual(report.error.error_code, 'MODEL_NOT_FOUND')

    def test_missing_key_beats_unreachable_model(self):
        report = GeminiService(api_key='', model='gemini-nope').health_check()
        self.assertFalse(report.ok)
        self.assertEqual(report.error.error_code, 'CONFIGURATION_ERROR')

    def test_timeout_error(self):
        report = self._raise(_FakeTimeout('timed out')).health_check()
        self.assertIsInstance(report.error, AITimeoutError)
        self.assertEqual(report.error.error_code, 'AI_TIMEOUT')

    def test_network_error(self):
        report = self._raise(_FakeConnectionError('Connection reset')).health_check()
        self.assertIsInstance(report.error, AINetworkError)
        self.assertEqual(report.error.error_code, 'NETWORK_ERROR')

    def test_provider_unavailable(self):
        report = self._raise(FakeAPIError(503, 'overloaded')).health_check()
        self.assertIsInstance(report.error, AIProviderUnavailableError)
        self.assertEqual(report.error.error_code, 'PROVIDER_UNAVAILABLE')
        self.assertEqual(report.error.http_status, 503)

    def test_daily_quota_exceeded(self):
        report = self._raise(FakeAPIError(
            429, 'Quota exceeded. Limit 100 requests per day.')).health_check()
        self.assertIsInstance(report.error, AIQuotaExceededError)
        self.assertEqual(report.error.error_code, 'QUOTA_EXCEEDED')

    def test_minute_rate_limit(self):
        report = self._raise(FakeAPIError(429, 'resource exhausted')).health_check()
        self.assertIsInstance(report.error, AIRateLimitError)
        self.assertEqual(report.error.error_code, 'RATE_LIMITED')


class RetryTests(SimpleTestCase):
    def test_transient_failure_retries_then_succeeds(self):
        calls = []
        def create(**kw):
            calls.append(kw)
            if len(calls) == 1:
                raise FakeAPIError(429, 'resource exhausted')
            return ns(output_text='MODEZA_AI_OK', steps=[])
        service = _service(max_retries=2, backoff=0.0)
        service._client = ns(interactions=ns(create=create))
        report = service.health_check()
        self.assertTrue(report.ok)
        self.assertEqual(len(calls), 2)

    def test_transient_retries_exhausted(self):
        def create(**kw):
            raise FakeAPIError(500, 'server exploded')
        service = _service(max_retries=1, backoff=0.0)
        service._client = ns(interactions=ns(create=create))
        report = service.health_check()
        self.assertIsInstance(report.error, AIProviderUnavailableError)
        self.assertFalse(report.ok)

    def test_permanent_auth_error_never_retried(self):
        calls = []
        def create(**kw):
            calls.append(kw)
            raise FakeAPIError(401, 'invalid key')
        service = _service(max_retries=3, backoff=0.0)
        service._client = ns(interactions=ns(create=create))
        report = service.health_check()
        self.assertIsInstance(report.error, AIAuthenticationError)
        self.assertEqual(len(calls), 1)

    def test_permanent_model_error_never_retried(self):
        calls = []
        def create(**kw):
            calls.append(kw)
            raise FakeAPIError(404, 'model not found')
        service = _service(max_retries=3, backoff=0.0)
        service._client = ns(interactions=ns(create=create))
        report = service.health_check()
        self.assertIsInstance(report.error, AIModelError)
        self.assertEqual(len(calls), 1)


class ClassifyTests(SimpleTestCase):
    def test_numeric_status_mapping(self):
        cases = [
            (400, AIUnexpectedError),
            (401, AIAuthenticationError),
            (403, AIAuthenticationError),
            (404, AIModelError),
            (429, AIRateLimitError),
            (429, AIQuotaExceededError),  # daily text flips it below
            (500, AIProviderUnavailableError),
            (502, AIProviderUnavailableError),
            (599, AIProviderUnavailableError),
        ]
        for code, expected in cases:
            message = ('Quota exceeded. 100 requests per day.' if code == 429
                       else 'whatever')
            error = classify_error(FakeAPIError(code, message))
            self.assertIsInstance(error, expected, f'code={code}')

    def test_daily_quota_flips_to_quota(self):
        error = classify_error(
            FakeAPIError(429, 'Rate limit exceeded: 20 requests per day'))
        self.assertIsInstance(error, AIQuotaExceededError)
        self.assertEqual(error.error_code, 'QUOTA_EXCEEDED')

    def test_timeout_by_name_without_code(self):
        self.assertIsInstance(classify_error(_FakeTimeout('x')), AITimeoutError)

    def test_connection_by_name(self):
        self.assertIsInstance(classify_error(_FakeConnectionError('x')),
                              AINetworkError)

    def test_blocked_content(self):
        error = classify_error(FakeAPIError(400, 'Response was blocked.'))
        self.assertIsInstance(error, AIContentBlockedError)

    def test_exception_without_code_maps_to_unexpected(self):
        error = classify_error(ValueError('mystery'))
        self.assertIsInstance(error, AIUnexpectedError)

    def test_extract_text_prefers_steps(self):
        interaction = ns(
            steps=[ns(type='function_call', name='f', arguments={}),
                   ns(type='model_output', content=[
                       ns(type='text', text='Hello '),
                       ns(type='text', text='world')])],
            output_text='stale')
        self.assertEqual(_extract_text(interaction), 'Hello world')

    def test_extract_text_falls_back_to_output_text(self):
        self.assertEqual(_extract_text(ns(steps=[], output_text='MODEZA_AI_OK')),
                         'MODEZA_AI_OK')