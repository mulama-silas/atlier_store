"""Opt-in LIVE tests against the real Google Gemini API.

Skipped unless BOTH ``RUN_GEMINI_INTEGRATION=1`` and ``GEMINI_API_KEY`` are
present in the environment. Never runs as part of the default test suite.

Run with:

    $env:RUN_GEMINI_INTEGRATION=1; $env:GEMINI_API_KEY='…'
    python manage.py test ai.tests.test_integration
"""
import os

from django.test import SimpleTestCase, override_settings

from ai.gemini_service import GeminiService, _extract_text

_INTEGRATION = os.getenv('RUN_GEMINI_INTEGRATION') == '1'
_KEY = os.getenv('GEMINI_API_KEY', '')


@override_settings(GEMINI_API_KEY=_KEY)
class LiveGeminiIntegrationTests(SimpleTestCase):
    def setUp(self):
        if not (_INTEGRATION and _KEY):
            self.skipTest(
                'Integration tests need RUN_GEMINI_INTEGRATION=1 and '
                'GEMINI_API_KEY (real Gemini call).')

    def test_health_round_trip(self):
        report = GeminiService().health_check()
        self.assertTrue(report.ok)
        self.assertEqual(report.text, 'MODEZA_AI_OK')

    def test_model_accepts_modeza_prompt(self):
        service = GeminiService()
        interaction = service._create(
            model=service.model,
            system_instruction=(
                'You are the Modeza Boutique shopping assistant. '
                'Keep replies concise.'),
            input='Reply with exactly: MODEZA_AI_OK',
            stream=False)
        text = _extract_text(interaction)
        self.assertIn('MODEZA_AI_OK', text)