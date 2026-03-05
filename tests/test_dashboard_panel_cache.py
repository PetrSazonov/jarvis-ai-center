import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app.api as api


class DashboardPanelCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_weather_panel_uses_cache_after_first_load(self):
        with (
            patch("app.api._cache_get_json", side_effect=[None, {"city": "Moscow", "summary": "clear", "clothing": "jacket"}]),
            patch("app.api._cache_set_json") as cache_set,
            patch("app.api.fetch_weather_summary", new=AsyncMock(return_value="clear")) as fetch_mock,
        ):
            first = await api._load_weather_panel("Moscow", "ru")
            second = await api._load_weather_panel("Moscow", "ru")

        self.assertEqual(str(first.get("summary")), "clear")
        self.assertEqual(str(second.get("summary")), "clear")
        self.assertEqual(fetch_mock.await_count, 1)
        self.assertGreaterEqual(cache_set.call_count, 1)

    async def test_market_panel_uses_cache_after_first_load(self):
        with (
            patch("app.api._settings", return_value=SimpleNamespace(coingecko_vs="usd")),
            patch("app.api._cache_get_json", side_effect=[None, {"highlights": ["BTC"], "vs": "USD"}]),
            patch("app.api._cache_set_json") as cache_set,
            patch(
                "app.api.fetch_prices",
                new=AsyncMock(
                    return_value={
                        "bitcoin": {"usd": 70000.0, "usd_24h_change": 1.0},
                        "ethereum": {"usd": 3200.0, "usd_24h_change": -0.5},
                    }
                ),
            ) as prices_mock,
            patch(
                "app.api.fetch_usd_eur_to_rub",
                new=AsyncMock(return_value={"usd_rub": 90.0, "usd_rub_24h_change": 0.2, "eur_rub": 98.0, "eur_rub_24h_change": 0.1}),
            ) as fx_mock,
            patch("app.api.fetch_fuel95_moscow_data", new=AsyncMock(return_value={})) as fuel_mock,
        ):
            first = await api._load_market_panel()
            second = await api._load_market_panel()

        self.assertIn("highlights", first)
        self.assertIn("highlights", second)
        self.assertEqual(prices_mock.await_count, 1)
        self.assertEqual(fx_mock.await_count, 1)
        self.assertEqual(fuel_mock.await_count, 1)
        self.assertGreaterEqual(cache_set.call_count, 1)

    async def test_news_panel_returns_cached_payload_without_fetch(self):
        cached_payload = {
            "items": [],
            "hype": [],
            "profile": {"interests": ["ии"], "hidden_topics": [], "hidden_sources": [], "explain": True},
            "catalog": {"topics": [], "sources": []},
            "noise": {"raw_count": 0, "shown_count": 0, "filtered_topic": 0, "filtered_source": 0, "filtered_interest": 0},
        }
        with (
            patch("app.api._cache_get_json", return_value=cached_payload),
            patch("app.api.fetch_topic_links", new=AsyncMock(return_value=[])) as links_mock,
        ):
            panel = await api._load_news_panel(profile=None, ai_enabled=False)

        self.assertIsInstance(panel, dict)
        self.assertIn("items", panel)
        self.assertEqual(links_mock.await_count, 0)

    async def test_signals_panel_returns_cached_payload_without_fetch(self):
        cached_payload = {
            "enabled": True,
            "status": "ok",
            "count": 1,
            "items": [{"id": "x"}],
            "sources": {
                "imap": {"enabled": False, "status": "off", "count": 0, "error": ""},
                "local_files": {"enabled": True, "status": "ok", "count": 1, "error": ""},
            },
        }
        with (
            patch("app.api._cache_get_json", return_value=cached_payload),
            patch("app.api.fetch_ingest_signals", new=AsyncMock(return_value={})) as ingest_mock,
        ):
            panel = await api._load_signals_panel(limit=20)

        self.assertEqual(panel.get("status"), "ok")
        self.assertEqual(ingest_mock.await_count, 0)


if __name__ == "__main__":
    unittest.main()
