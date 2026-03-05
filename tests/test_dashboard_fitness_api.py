import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

try:
    from fastapi.testclient import TestClient
    from app.api import app
    import app.api as api_module

    FASTAPI_AVAILABLE = True
except Exception:  # noqa: BLE001
    FASTAPI_AVAILABLE = False
    TestClient = None
    app = None
    api_module = None


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed in this environment")
class DashboardFitnessApiTests(unittest.TestCase):
    AUTH_ENV = {
        "DASHBOARD_AUTH_ENABLED": "1",
        "DASHBOARD_ACCESS_TOKEN": "secret-token",
    }

    def _auth_headers(self) -> dict[str, str]:
        return {"x-jarvis-token": "secret-token"}

    def test_dashboard_fitness_workouts_smoke(self):
        rows = [
            (
                3,
                "Подтягивания + отжимания",
                "pull,bodyweight",
                "турник",
                3,
                1800,
                "3 круга",
                -100123,
                111,
                "",
                "2026-03-05T11:00:00",
            )
        ]
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api.fitness_list_workouts", return_value=(rows, 1)),
        ):
            client = TestClient(app)
            response = client.get(
                "/dashboard/fitness/workouts",
                params={"user_id": 118100880},
                headers=self._auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("count"), 1)
        self.assertEqual(payload["items"][0]["id"], 3)
        self.assertIn("tags", payload["items"][0])
        self.assertIn("equipment", payload["items"][0])

    def test_dashboard_fitness_session_smoke(self):
        workout_row = (
            7,
            "Ноги + корпус",
            "legs,core",
            "гантели",
            3,
            2100,
            "техника и контроль",
            -100123,
            222,
            "",
            "2026-03-05T11:00:00",
        )
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api.fitness_get_workout", return_value=workout_row),
            patch("app.api.fitness_add_session") as add_session,
            patch("app.api.fitness_get_recent_rpe", return_value=[7, 7, 6]),
            patch("app.api.fitness_upsert_progress") as upsert_progress,
        ):
            client = TestClient(app)
            response = client.post(
                "/dashboard/fitness/session",
                headers=self._auth_headers(),
                json={
                    "user_id": 118100880,
                    "workout_id": 7,
                    "rpe": 7,
                    "comment": "рабочая сессия",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("workout_id"), 7)
        self.assertIn("next_hint", payload)
        self.assertIn("activity", payload)
        add_session.assert_called_once()
        upsert_progress.assert_called_once()

    def test_dashboard_fitness_videos_smoke(self):
        fake_items = [
            {
                "name": "wim-hof.mp4",
                "title": "Wim Hof",
                "size_mb": 123.4,
                "modified_at": "2026-03-05T11:30:00",
                "stream_url": "/dashboard/fitness/video?name=wim-hof.mp4",
            }
        ]
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._list_fitness_videos", return_value=fake_items),
        ):
            client = TestClient(app)
            response = client.get(
                "/dashboard/fitness/videos",
                params={"user_id": 118100880},
                headers=self._auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("count"), 1)
        self.assertEqual(payload["items"][0]["name"], "wim-hof.mp4")

    def test_dashboard_fitness_video_stream_smoke(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"\x00\x00\x00\x18ftypmp42")
            tmp_path = Path(tmp.name)
        try:
            with (
                patch.dict(os.environ, self.AUTH_ENV, clear=False),
                patch("app.api._resolve_video_file", return_value=tmp_path),
                patch("app.api._video_media_type", return_value="video/mp4"),
            ):
                client = TestClient(app)
                response = client.get(
                    "/dashboard/fitness/video",
                    params={"name": "demo.mp4"},
                    headers=self._auth_headers(),
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers.get("content-type"), "video/mp4")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def test_list_fitness_videos_ai_title_cached(self):
        temp_dir = Path("ops") / "_test_fit_video_titles"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            video_path = temp_dir / "Guided Wim Hof Method Breathing.mp4"
            video_path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            cache_store: dict[str, str] = {}

            def fake_get_cache(key: str):
                if key in cache_store:
                    return (cache_store[key], "2026-03-05T12:00:00")
                return None

            def fake_set_cache(key: str, value: str, _updated_at: str):
                cache_store[key] = value

            llm_mock = AsyncMock(return_value='["Дыхание Вим Хоф"]')

            with (
                patch.object(api_module, "_FITNESS_VIDEO_DIR", temp_dir),
                patch("app.api._dashboard_ai_enabled", return_value=True),
                patch("app.api._settings", return_value=SimpleNamespace(llm_enhancer_timeout_seconds=2.0)),
                patch("app.api.build_prompt", return_value="prompt"),
                patch("app.api.call_ollama", new=llm_mock),
                patch("app.api.get_cache_value", side_effect=fake_get_cache),
                patch("app.api.set_cache_value", side_effect=fake_set_cache),
            ):
                first = api_module._list_fitness_videos(limit=5)
                second = api_module._list_fitness_videos(limit=5)

            self.assertTrue(first)
            self.assertEqual(first[0]["title"], "Дыхание Вим Хоф")
            self.assertEqual(second[0]["title"], "Дыхание Вим Хоф")
            self.assertEqual(llm_mock.await_count, 1)
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def test_training_panel_contains_timer_suggestions(self):
        workout_row = (
            11,
            "Интервалы: берпи + отжимания",
            "hiit,bodyweight",
            "коврик",
            4,
            1800,
            "табата 20/10",
            -100123,
            10,
            "",
            "2026-03-05T11:00:00",
        )
        with (
            patch("app.api.pick_workout_of_day", return_value=workout_row),
            patch("app.api.fitness_list_workouts", return_value=([workout_row], 1)),
            patch("app.api.fitness_get_latest_session_for_user", return_value=None),
            patch("app.api.fitness_get_progress", return_value=None),
            patch("app.api.fitness_stats_recent", return_value=(0, 0)),
            patch("app.api.program_summary", return_value="test"),
        ):
            panel = api_module._training_panel(user_id=118100880)

        self.assertIn("suggested_timers", panel)
        self.assertTrue(isinstance(panel.get("suggested_timers"), list))
        self.assertGreaterEqual(len(panel.get("suggested_timers")), 1)
        self.assertTrue(isinstance(panel.get("workouts"), list))
        self.assertIn("suggested_timers", panel["workouts"][0])
