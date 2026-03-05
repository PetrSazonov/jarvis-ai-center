import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    from fastapi.testclient import TestClient
    from app.api import app

    FASTAPI_AVAILABLE = True
except Exception:  # noqa: BLE001
    FASTAPI_AVAILABLE = False
    TestClient = None
    app = None


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed in this environment")
class DashboardContractTests(unittest.TestCase):
    def _base_patches(self):
        return (
            patch(
                "app.api._settings",
                return_value=SimpleNamespace(weather_city="Moscow", default_lang="ru", ollama_model="gemma3:27b"),
            ),
            patch(
                "app.api._load_weather_panel",
                new=AsyncMock(return_value={"city": "Moscow", "summary": "clear", "clothing": "light jacket"}),
            ),
            patch(
                "app.api._load_news_panel",
                new=AsyncMock(return_value={"items": [{"title": "News", "url": "https://example.com"}], "hype": []}),
            ),
            patch(
                "app.api._load_market_panel",
                new=AsyncMock(return_value={"highlights": ["BTC 70000 (+1.0%)"]}),
            ),
            patch(
                "app.api._training_panel",
                return_value={"today_plan": None, "latest_session": None, "progressive_hint": "keep form"},
            ),
            patch(
                "app.api._trend_panel",
                return_value={"summary": "stable rhythm", "open_now": 2},
            ),
            patch(
                "app.api._load_signals_panel",
                new=AsyncMock(
                    return_value={
                        "enabled": True,
                        "status": "ok",
                        "count": 1,
                        "items": [{"id": "file:daily.md", "source": "local_file", "title": "Daily note"}],
                        "sources": {
                            "imap": {"enabled": False, "status": "off", "count": 0, "error": ""},
                            "local_files": {"enabled": True, "status": "ok", "count": 1, "error": ""},
                        },
                    }
                ),
            ),
        )

    def test_dashboard_data_has_uniform_sections_and_freshness(self):
        handle_side_effect = [
            {"date": "2026-03-04", "day_mode": "workday", "energy": 7, "next_actions": ["/todo", "/focus"]},
            {"items": [{"id": 1, "text": "MIT", "created_at": "2026-03-04T10:00:00"}]},
            {"items": [{"id": 3, "name": "ChatGPT", "next_date": "2026-03-20"}]},
        ]

        p_settings, p_weather, p_news, p_market, p_training, p_trend, p_signals = self._base_patches()
        with (
            p_settings,
            p_weather,
            p_news,
            p_market,
            p_training,
            p_trend,
            p_signals,
            patch("app.api._handle", side_effect=handle_side_effect),
        ):
            client = TestClient(app)
            response = client.get("/dashboard/data", params={"user_id": 118100880, "ai": 0})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("meta", payload)
        self.assertEqual(payload["meta"].get("schema"), "dashboard.v2")
        self.assertIn("sections", payload)

        expected_sections = (
            "today",
            "tasks",
            "subs",
            "market",
            "weather",
            "news",
            "training",
            "trend",
            "signals",
            "stats",
            "calendar",
            "ai",
            "ai_pack",
            "assistant",
            "events",
        )
        for key in expected_sections:
            self.assertIn(key, payload["sections"])
            section = payload["sections"][key]
            self.assertIn("data", section)
            self.assertIn("freshness", section)
            freshness = section["freshness"]
            self.assertIn("as_of", freshness)
            self.assertIn("label", freshness)
            self.assertIn("state", freshness)
            self.assertIn("age_sec", freshness)
            self.assertIn("stale_after_sec", freshness)

        for key in ("today", "tasks", "subs", "market", "weather", "news", "training", "trend", "signals", "stats", "calendar", "ai", "ai_pack", "assistant", "events"):
            self.assertIn(key, payload)

    def test_dashboard_data_puts_debug_events_into_events_section(self):
        handle_side_effect = [
            {
                "result": {"date": "2026-03-04", "day_mode": "workday", "energy": 6, "next_actions": ["/todo"]},
                "events": [{"name": "today.loaded", "ts": "2026-03-04T10:00:00", "payload": {"user_id": 1}}],
            },
            {
                "result": {"items": []},
                "events": [{"name": "tasks.listed", "ts": "2026-03-04T10:00:01", "payload": {"count": 0}}],
            },
            {
                "result": {"items": []},
                "events": [{"name": "subs.listed", "ts": "2026-03-04T10:00:02", "payload": {"count": 0}}],
            },
        ]

        p_settings, p_weather, p_news, p_market, p_training, p_trend, p_signals = self._base_patches()
        with (
            patch.dict(os.environ, {"API_DEBUG_EVENTS": "1", "API_DEBUG_EVENTS_REMOTE": "1"}, clear=False),
            p_settings,
            p_weather,
            p_news,
            p_market,
            p_training,
            p_trend,
            p_signals,
            patch("app.api._handle", side_effect=handle_side_effect),
        ):
            client = TestClient(app)
            response = client.get("/dashboard/data", params={"user_id": 118100880, "debug": 1, "ai": 0})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        events = payload["sections"]["events"]["data"]
        self.assertEqual(len(events), 3)
        self.assertEqual(payload["events"], events)
        event_names = {event.get("name") for event in events}
        self.assertIn("today.loaded", event_names)
        self.assertIn("tasks.listed", event_names)
        self.assertIn("subs.listed", event_names)


if __name__ == "__main__":
    unittest.main()
