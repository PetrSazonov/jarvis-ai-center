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
class DashboardNewsNoiseTests(unittest.TestCase):
    AUTH_ENV = {
        "DASHBOARD_AUTH_ENABLED": "1",
        "DASHBOARD_ACCESS_TOKEN": "secret-token",
    }

    def _auth_headers(self) -> dict[str, str]:
        return {"x-jarvis-token": "secret-token"}

    def _base_dashboard_patches(self):
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
                "app.api._load_market_panel",
                new=AsyncMock(return_value={"highlights": ["BTC 70000 (+1.0%)"]}),
            ),
            patch(
                "app.api._training_panel",
                return_value={"today_plan": None, "latest_session": None, "progressive_hint": "keep form"},
            ),
            patch(
                "app.api._trend_panel",
                return_value={"summary": "stable", "open_now": 2},
            ),
            patch(
                "app.api._load_signals_panel",
                new=AsyncMock(
                    return_value={
                        "enabled": False,
                        "status": "off",
                        "count": 0,
                        "items": [],
                        "sources": {
                            "imap": {"enabled": False, "status": "off", "count": 0, "error": ""},
                            "local_files": {"enabled": False, "status": "off", "count": 0, "error": ""},
                        },
                    }
                ),
            ),
        )

    def test_news_profile_roundtrip(self):
        user_id = 99887766
        with patch.dict(os.environ, self.AUTH_ENV, clear=False):
            client = TestClient(app)
            before = client.get(
                "/dashboard/news/profile",
                params={"user_id": user_id},
                headers=self._auth_headers(),
            )
            self.assertEqual(before.status_code, 200)
            self.assertIn("profile", before.json())

            save_payload = {
                "user_id": user_id,
                "interests": ["ии", "крипта"],
                "hidden_topics": ["спорт"],
                "hidden_sources": ["vc.ru", "www.cnews.ru"],
                "explain": False,
            }
            saved = client.post(
                "/dashboard/news/profile",
                headers=self._auth_headers(),
                json=save_payload,
            )
            self.assertEqual(saved.status_code, 200)
            profile = saved.json().get("profile", {})
            self.assertEqual(profile.get("interests"), ["ии", "крипта"])
            self.assertEqual(profile.get("hidden_topics"), ["спорт"])
            self.assertEqual(profile.get("hidden_sources"), ["vc.ru", "cnews.ru"])
            self.assertFalse(profile.get("explain", True))

    def test_dashboard_news_respects_noise_profile_and_has_why(self):
        user_id = 77665544
        feed_items = [
            {"topic": "ии", "title": "Новый AI релиз", "url": "https://vc.ru/ai/1", "published_ts": "1731000000"},
            {"topic": "ии", "title": "ML в проде", "url": "https://cnews.ru/news/2", "published_ts": "1731003600"},
            {"topic": "спорт", "title": "UFC карточка", "url": "https://sport.ru/3", "published_ts": "1731007200"},
        ]
        handle_side_effect = [
            {"date": "2026-03-04", "day_mode": "workday", "energy": 7, "next_actions": ["/todo", "/focus"]},
            {"items": [{"id": 1, "text": "MIT", "created_at": "2026-03-04T10:00:00"}]},
            {"items": []},
        ]
        p_settings, p_weather, p_market, p_training, p_trend, p_signals = self._base_dashboard_patches()
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api.fetch_topic_links", new=AsyncMock(return_value=feed_items)),
            p_settings,
            p_weather,
            p_market,
            p_training,
            p_trend,
            p_signals,
            patch("app.api._handle", side_effect=handle_side_effect),
        ):
            client = TestClient(app)
            saved = client.post(
                "/dashboard/news/profile",
                headers=self._auth_headers(),
                json={
                    "user_id": user_id,
                    "interests": ["ии"],
                    "hidden_topics": [],
                    "hidden_sources": ["vc.ru"],
                    "explain": True,
                },
            )
            self.assertEqual(saved.status_code, 200)

            response = client.get(
                "/dashboard/data",
                params={"user_id": user_id, "ai": 0},
                headers=self._auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        news = payload.get("news", {})
        items = news.get("items", [])
        self.assertTrue(items)
        for item in items:
            self.assertEqual(item.get("topic"), "ии")
            self.assertIn("why", item)
            self.assertTrue(str(item.get("source") or "").strip())
            self.assertNotEqual(item.get("source"), "vc.ru")


if __name__ == "__main__":
    unittest.main()
