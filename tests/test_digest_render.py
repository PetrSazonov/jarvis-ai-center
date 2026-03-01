import unittest
from dataclasses import replace
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

from core.settings import Settings
from services.digest_service import build_digest_render


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


class DigestRenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_morning_mode_has_morning_header(self):
        settings = _settings()
        with (
            patch(
                "services.digest_service.fetch_prices",
                new=AsyncMock(
                    return_value={
                        "bitcoin": {"usd": 68000.0, "usd_24h_change": -0.4},
                        "ethereum": {"usd": 1975.0, "usd_24h_change": 1.6},
                    }
                ),
            ),
            patch(
                "services.digest_service.fetch_usd_eur_to_rub",
                new=AsyncMock(
                    return_value={
                        "usd_rub": 76.5,
                        "usd_rub_24h_change": -0.5,
                        "eur_rub": 91.0,
                        "eur_rub_24h_change": -0.4,
                    }
                ),
            ),
            patch(
                "services.digest_service.fetch_fuel95_moscow_data",
                new=AsyncMock(return_value={"price_rub": 68.66, "change_24h_pct": 0.2}),
            ),
            patch(
                "services.digest_service.fetch_weather_summary",
                new=AsyncMock(return_value="Погода в Москве: -1.0C, ощущается как -4.0C, пасмурно"),
            ),
            patch(
                "services.digest_service.fetch_topic_links",
                new=AsyncMock(
                    return_value=[
                        {"topic": "ии", "title": "Новая модель вышла", "url": "https://example.com/1", "published_ts": "1772241600"},
                        {"topic": "крипта", "title": "Рынок растет", "url": "https://example.com/2", "published_ts": "1772238000"},
                    ]
                ),
            ),
            patch("services.digest_service.fetch_interesting_fact", new=AsyncMock(return_value="Факт для теста")),
            patch("services.digest_service.now_dt", return_value=datetime(2026, 2, 23, 7, 0, 0)),
        ):
            render = await build_digest_render(settings, morning_mode=True)

        self.assertIn("Доброе утро", render.compact.text)
        self.assertIn("Задание дня:", render.compact.text)

    async def test_non_morning_mode_uses_neutral_header(self):
        settings = _settings()
        with (
            patch(
                "services.digest_service.fetch_prices",
                new=AsyncMock(
                    return_value={
                        "bitcoin": {"usd": 68000.0, "usd_24h_change": -0.4},
                        "ethereum": {"usd": 1975.0, "usd_24h_change": 1.6},
                    }
                ),
            ),
            patch(
                "services.digest_service.fetch_usd_eur_to_rub",
                new=AsyncMock(
                    return_value={
                        "usd_rub": 76.5,
                        "usd_rub_24h_change": -0.5,
                        "eur_rub": 91.0,
                        "eur_rub_24h_change": -0.4,
                    }
                ),
            ),
            patch(
                "services.digest_service.fetch_fuel95_moscow_data",
                new=AsyncMock(return_value={"price_rub": 68.66, "change_24h_pct": 0.2}),
            ),
            patch(
                "services.digest_service.fetch_weather_summary",
                new=AsyncMock(return_value="Погода в Москве: -1.0C, ощущается как -4.0C, пасмурно"),
            ),
            patch(
                "services.digest_service.fetch_topic_links",
                new=AsyncMock(
                    return_value=[
                        {"topic": "ии", "title": "Новая модель вышла", "url": "https://example.com/1", "published_ts": "1772241600"},
                        {"topic": "крипта", "title": "Рынок растет", "url": "https://example.com/2", "published_ts": "1772238000"},
                    ]
                ),
            ),
            patch("services.digest_service.fetch_interesting_fact", new=AsyncMock(return_value="Факт для теста")),
            patch("services.digest_service.now_dt", return_value=datetime(2026, 2, 23, 16, 0, 0)),
        ):
            render = await build_digest_render(settings, morning_mode=False)

        self.assertIn("Сегодня твой", render.compact.text)
        self.assertNotIn("Доброе утро", render.compact.text)

    async def test_digest_contains_news_freshness_line_when_timestamp_available(self):
        settings = replace(_settings(), default_lang="en")
        with (
            patch(
                "services.digest_service.fetch_prices",
                new=AsyncMock(
                    return_value={
                        "bitcoin": {"usd": 68000.0, "usd_24h_change": -0.4},
                        "ethereum": {"usd": 1975.0, "usd_24h_change": 1.6},
                    }
                ),
            ),
            patch(
                "services.digest_service.fetch_usd_eur_to_rub",
                new=AsyncMock(
                    return_value={
                        "usd_rub": 76.5,
                        "usd_rub_24h_change": -0.5,
                        "eur_rub": 91.0,
                        "eur_rub_24h_change": -0.4,
                    }
                ),
            ),
            patch(
                "services.digest_service.fetch_fuel95_moscow_data",
                new=AsyncMock(return_value={"price_rub": 68.66, "change_24h_pct": 0.2}),
            ),
            patch(
                "services.digest_service.fetch_weather_summary",
                new=AsyncMock(return_value="Weather in Moscow: -1.0C, feels -4.0C, overcast"),
            ),
            patch(
                "services.digest_service.fetch_topic_links",
                new=AsyncMock(
                    return_value=[
                        {"topic": "ai", "title": "Model update released", "url": "https://example.com/1", "published_ts": "1772241600"},
                        {"topic": "crypto", "title": "Market update", "url": "https://example.com/2", "published_ts": "1772238000"},
                    ]
                ),
            ),
            patch("services.digest_service.fetch_interesting_fact", new=AsyncMock(return_value="Fact")),
            patch("services.digest_service.now_dt", return_value=datetime(2026, 2, 23, 16, 0, 0)),
        ):
            render = await build_digest_render(settings, morning_mode=False)

        self.assertIn("News updated:", render.compact.text)


if __name__ == "__main__":
    unittest.main()
