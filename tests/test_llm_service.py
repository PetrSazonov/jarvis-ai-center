import unittest
from datetime import date

from core.settings import Settings
from services.llm_service import build_prompt


class PromptTests(unittest.TestCase):
    def test_build_prompt_trims_history(self):
        settings = Settings(
            bot_token="x",
            coingecko_vs="usd",
            price_currencies=("usd", "eur", "rub"),
            ollama_api_url="http://localhost",
            ollama_model="test",
            ollama_timeout_seconds=60.0,
            max_history_messages=2,
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

        history = [
            {"role": "user", "content": "old1"},
            {"role": "assistant", "content": "old2"},
            {"role": "user", "content": "new1"},
        ]

        prompt = build_prompt(history=history, user_message="hello", settings=settings)
        self.assertNotIn("old1", prompt)
        self.assertIn("Assistant: old2", prompt)
        self.assertIn("User: new1", prompt)
        self.assertIn("User: hello", prompt)

    def test_build_prompt_includes_mode_policy(self):
        settings = Settings(
            bot_token="x",
            coingecko_vs="usd",
            price_currencies=("usd", "eur", "rub"),
            ollama_api_url="http://localhost",
            ollama_model="test",
            ollama_timeout_seconds=60.0,
            max_history_messages=2,
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
        prompt = build_prompt(history=[], user_message="hello", settings=settings, mode="precise")
        self.assertIn("precise mode", prompt)

    def test_build_prompt_includes_advisor_safety_policy(self):
        settings = Settings(
            bot_token="x",
            coingecko_vs="usd",
            price_currencies=("usd", "eur", "rub"),
            ollama_api_url="http://localhost",
            ollama_model="test",
            ollama_timeout_seconds=60.0,
            max_history_messages=2,
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
        prompt = build_prompt(history=[], user_message="hello", settings=settings, profile="advisor")
        self.assertIn("never invent facts", prompt)

    def test_build_prompt_uses_rewriter_template(self):
        settings = Settings(
            bot_token="x",
            coingecko_vs="usd",
            price_currencies=("usd", "eur", "rub"),
            ollama_api_url="http://localhost",
            ollama_model="test",
            ollama_timeout_seconds=60.0,
            max_history_messages=2,
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
        prompt = build_prompt(history=[], user_message="hello", settings=settings, profile="rewriter")
        self.assertIn("improve readability", prompt)


if __name__ == "__main__":
    unittest.main()
