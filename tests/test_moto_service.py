import unittest
from datetime import date

from core.settings import Settings
from services.moto_service import moto_season_countdown_line, next_moto_season_date


class MotoServiceTests(unittest.TestCase):
    def _settings(self) -> Settings:
        return Settings(
            bot_token="x",
            coingecko_vs="usd",
            price_currencies=("usd",),
            ollama_api_url="http://localhost",
            ollama_model="test",
            ollama_timeout_seconds=60.0,
            max_history_messages=10,
            system_prompt="system",
            default_lang="ru",
            enable_crypto_watcher=False,
            log_level="INFO",
            timezone_name=None,
            weather_city="Moscow",
            home_address=None,
            work_address=None,
            enable_auto_digest=True,
            digest_times=("07:00",),
            digest_chat_id=1,
            birth_date=date(1984, 12, 15),
            moto_season_start_mmdd=(4, 15),
            fuel95_source_url="https://example.com/fuel95",
            fuel95_moscow_rub=62.5,
            feedback_min_chars=280,
            style_mode="neutral",
        )

    def test_before_season(self):
        s = self._settings()
        self.assertEqual(next_moto_season_date(date(2026, 2, 10), s), date(2026, 4, 15))

    def test_after_season_rolls_next_year(self):
        s = self._settings()
        self.assertEqual(next_moto_season_date(date(2026, 10, 1), s), date(2027, 4, 15))

    def test_countdown_line(self):
        s = self._settings()
        line = moto_season_countdown_line(s, today=date(2026, 4, 10))
        self.assertIn("2026", line)
        self.assertIn("5", line)


if __name__ == "__main__":
    unittest.main()
