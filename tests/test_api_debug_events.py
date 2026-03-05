import os
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from app.api import app

    FASTAPI_AVAILABLE = True
except Exception:  # noqa: BLE001
    FASTAPI_AVAILABLE = False
    TestClient = None
    app = None


@unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi is not installed in this environment")
class APIDebugEventsTests(unittest.TestCase):
    def test_debug_events_enabled_returns_events(self):
        with patch.dict(os.environ, {"API_DEBUG_EVENTS": "1"}, clear=False):
            with patch(
                "app.api.handle_command",
                return_value={"result": {"items": []}, "events": [{"name": "tasks.listed"}]},
            ) as mocked:
                client = TestClient(app)
                response = client.get("/tasks", params={"user_id": 1, "debug": 1})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("events", payload)
        mocked.assert_called_once_with(1, "tasks:list", {"limit": 20}, return_events=True)

    def test_debug_events_disabled_ignores_debug_flag(self):
        with patch.dict(os.environ, {"API_DEBUG_EVENTS": "0"}, clear=False):
            with patch("app.api.handle_command", return_value={"items": []}) as mocked:
                client = TestClient(app)
                response = client.get("/tasks", params={"user_id": 1, "debug": 1})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("events", payload)
        mocked.assert_called_once_with(1, "tasks:list", {"limit": 20}, return_events=False)

    def test_post_tasks_debug_enabled_passes_return_events(self):
        with patch.dict(os.environ, {"API_DEBUG_EVENTS": "1"}, clear=False):
            with patch(
                "app.api.handle_command",
                return_value={"result": {"id": 9}, "events": [{"name": "tasks.added"}]},
            ) as mocked:
                client = TestClient(app)
                response = client.post("/tasks?debug=1", json={"user_id": 5, "text": "MIT"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("events", payload)
        args, kwargs = mocked.call_args
        self.assertEqual(args[0], 5)
        self.assertEqual(args[1], "tasks:add")
        self.assertIn("created_at", args[2])
        self.assertEqual(args[2]["text"], "MIT")
        self.assertTrue(kwargs.get("return_events"))


if __name__ == "__main__":
    unittest.main()
