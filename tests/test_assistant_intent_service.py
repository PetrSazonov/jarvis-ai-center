import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from core.settings import Settings
from services.assistant_intent_service import (
    INTENT_CHAT,
    INTENT_PRICE,
    INTENT_ROUTE,
    INTENT_WEATHER,
    detect_assistant_intent,
)


def _settings() -> Settings:
    return Settings(
        bot_token="x",
        coingecko_vs="usd",
        price_currencies=("usd", "eur", "rub"),
        ollama_api_url="http://localhost",
        ollama_model="test",
        ollama_timeout_seconds=60.0,
        max_history_messages=24,
        system_prompt="system",
        default_lang="ru",
        enable_crypto_watcher=False,
        log_level="INFO",
        timezone_name=None,
        weather_city="Moscow",
        home_address=None,
        work_address=None,
        enable_auto_digest=True,
        digest_times=("07:00", "14:00", "21:00"),
        digest_chat_id=1,
        birth_date=date(1984, 12, 15),
        moto_season_start_mmdd=(4, 15),
        fuel95_source_url="https://example.com/fuel95",
        fuel95_moscow_rub=62.5,
        feedback_min_chars=280,
        style_mode="neutral",
    )


class AssistantIntentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_heuristic_weather(self):
        decision = await detect_assistant_intent(
            text="какая погода в москве сегодня?",
            settings=_settings(),
            mode="normal",
            lang="ru",
        )
        self.assertEqual(decision.intent, INTENT_WEATHER)
        self.assertGreaterEqual(decision.confidence, 0.8)

    async def test_heuristic_route_requires_clarification(self):
        decision = await detect_assistant_intent(
            text="построй маршрут",
            settings=_settings(),
            mode="normal",
            lang="ru",
        )
        self.assertEqual(decision.intent, INTENT_ROUTE)
        self.assertTrue(decision.need_clarification)
        self.assertIn("дом", decision.clarifying_question.lower() or "дом")

    async def test_llm_json_external_intent_parsed(self):
        with patch(
            "services.assistant_intent_service.call_ollama",
            new=AsyncMock(
                return_value='{"intent":"price","confidence":0.88,"need_clarification":false,"clarifying_question":"","args":{}}'
            ),
        ):
            decision = await detect_assistant_intent(
                text="сделай сводку",
                settings=_settings(),
                mode="fast",
                lang="ru",
            )
        self.assertEqual(decision.intent, INTENT_PRICE)
        self.assertGreaterEqual(decision.confidence, 0.8)

    async def test_llm_json_invalid_payload_falls_back(self):
        with patch(
            "services.assistant_intent_service.call_ollama",
            new=AsyncMock(return_value='{"intent":"price","need_clarification":false,"clarifying_question":"","args":{}}'),
        ):
            decision = await detect_assistant_intent(
                text="help me maybe",
                settings=_settings(),
                mode="normal",
                lang="en",
            )
        self.assertEqual(decision.intent, INTENT_CHAT)
        self.assertGreaterEqual(decision.confidence, 0.5)


if __name__ == "__main__":
    unittest.main()

