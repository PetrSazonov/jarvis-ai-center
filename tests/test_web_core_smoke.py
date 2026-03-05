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
class WebCoreSmokeTests(unittest.TestCase):
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

    def test_dashboard_data_smoke(self):
        handle_side_effect = [
            {"date": "2026-03-04", "day_mode": "workday", "energy": 7, "next_actions": ["/todo", "/focus"]},
            {"items": [{"id": 1, "text": "MIT", "created_at": "2026-03-04T10:00:00"}]},
            {"items": [{"id": 3, "name": "ChatGPT", "next_date": "2026-03-20"}]},
        ]
        p_settings, p_weather, p_news, p_market, p_training, p_trend, p_signals = self._base_dashboard_patches()
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
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
            response = client.get(
                "/dashboard/data",
                params={"user_id": 118100880, "ai": 0},
                headers=self._auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("meta", {}).get("schema"), "dashboard.v2")
        self.assertIn("sections", payload)
        self.assertIn("today", payload["sections"])
        self.assertIn("tasks", payload["sections"])
        self.assertIn("assistant", payload["sections"])
        self.assertIn("ai_pack", payload["sections"])

    def test_gemma_endpoints_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._assistant_message", new=AsyncMock(return_value={"answer": "ok", "quick_actions": [], "status": "ok"})),
            patch("app.api._assistant_action", new=AsyncMock(return_value={"ok": True, "message": "done", "quick_actions": [], "status": "ok"})),
            patch("app.api._chat_history_load", return_value=[{"role": "assistant", "content": "hi"}]),
        ):
            client = TestClient(app)
            msg = client.post(
                "/gemma/message",
                headers=self._auth_headers(),
                json={"user_id": 1, "message": "hello", "mode": "normal", "chat_mode": "full"},
            )
            act = client.post(
                "/gemma/action",
                headers=self._auth_headers(),
                json={"user_id": 1, "action": "focus_start", "mode": "normal"},
            )
            history = client.get(
                "/gemma/history",
                headers=self._auth_headers(),
                params={"user_id": 1, "limit": 20},
            )

        self.assertEqual(msg.status_code, 200)
        self.assertEqual(act.status_code, 200)
        self.assertEqual(history.status_code, 200)
        self.assertIn("answer", msg.json())
        self.assertIn("message", act.json())
        self.assertIn("items", history.json())

    def test_codex_endpoints_smoke(self):
        with patch.dict(os.environ, self.AUTH_ENV, clear=False):
            client = TestClient(app)
            with patch("app.api._codex_bridge_enabled", return_value=False):
                run_response = client.post(
                    "/codex/run",
                    headers=self._auth_headers(),
                    json={"user_id": 1, "prompt": "task"},
                )
            with (
                patch("app.api._codex_read_status", return_value={"run_id": "r1", "status": "done"}),
                patch("app.api._codex_read_log_delta", return_value=(["line"], 1)),
                patch("app.api._codex_read_last_message", return_value="final"),
            ):
                status_response = client.get(
                    "/codex/run/r1",
                    headers=self._auth_headers(),
                    params={"cursor": 0, "limit": 20},
                )
            with patch("app.api._codex_history", return_value=[{"run_id": "r1", "status": "done"}]):
                history_response = client.get("/codex/history", headers=self._auth_headers())

        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(run_response.json().get("status"), "disabled")
        self.assertEqual(status_response.status_code, 200)
        self.assertIn("status", status_response.json())
        self.assertIn("lines", status_response.json())
        self.assertEqual(history_response.status_code, 200)
        self.assertIn("runs", history_response.json())

    def test_ops_services_smoke(self):
        with patch.dict(os.environ, self.AUTH_ENV, clear=False):
            client = TestClient(app)
            response = client.get("/ops/services", headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("status", payload)
        self.assertIn("checked_at", payload)
        self.assertIn("api", payload)
        self.assertIn("ollama", payload)
        self.assertIn("codex_bridge", payload)
        self.assertIn("security", payload)

    def test_signals_endpoint_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
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
        ):
            client = TestClient(app)
            response = client.get("/signals", params={"user_id": 1, "limit": 5}, headers=self._auth_headers())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("meta", payload)
        self.assertIn("signals", payload)
        self.assertEqual(payload["signals"].get("status"), "ok")

    def test_subs_create_endpoint_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._handle", return_value={"id": 77}),
        ):
            client = TestClient(app)
            response = client.post(
                "/subs",
                headers=self._auth_headers(),
                json={
                    "user_id": 1,
                    "name": "ChatGPT Pro",
                    "next_date": "2026-03-20",
                    "period": "monthly",
                    "amount": 20,
                    "currency": "USD",
                    "autopay": True,
                    "remind_days": 5,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("id"), 77)

    def test_task_done_endpoint_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._handle", return_value={"ok": True}),
        ):
            client = TestClient(app)
            response = client.post(
                "/tasks/12/done",
                headers=self._auth_headers(),
                json={"user_id": 1},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(bool(payload.get("ok")))

    def test_task_update_endpoint_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._handle", return_value={"ok": True}),
        ):
            client = TestClient(app)
            response = client.patch(
                "/tasks/15",
                headers=self._auth_headers(),
                json={"user_id": 1, "due_date": "2026-03-08", "remind_at": None, "remind_telegram": True},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(bool(payload.get("ok")))

    def test_task_update_endpoint_text_only_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._handle", return_value={"ok": True}) as mocked_handle,
        ):
            client = TestClient(app)
            response = client.patch(
                "/tasks/15",
                headers=self._auth_headers(),
                json={"user_id": 1, "text": "Обновить панель задач"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(bool(payload.get("ok")))
        mocked_handle.assert_called_once()
        args, kwargs = mocked_handle.call_args
        self.assertEqual(args[0], 1)
        self.assertEqual(args[1], "tasks:update")
        self.assertEqual(args[2]["task_id"], 15)
        self.assertEqual(args[2]["text"], "Обновить панель задач")

    def test_task_update_endpoint_with_notes_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._handle", return_value={"ok": True}) as mocked_handle,
        ):
            client = TestClient(app)
            response = client.patch(
                "/tasks/21",
                headers=self._auth_headers(),
                json={"user_id": 1, "text": "Переписать виджет", "notes": "Сначала шапка, потом кнопки"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(bool(payload.get("ok")))
        mocked_handle.assert_called_once()
        args, kwargs = mocked_handle.call_args
        self.assertEqual(args[1], "tasks:update")
        self.assertEqual(args[2]["task_id"], 21)
        self.assertEqual(args[2]["text"], "Переписать виджет")
        self.assertEqual(args[2]["notes"], "Сначала шапка, потом кнопки")

    def test_task_create_endpoint_with_notes_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._handle", return_value={"id": 55}) as mocked_handle,
        ):
            client = TestClient(app)
            response = client.post(
                "/tasks",
                headers=self._auth_headers(),
                json={
                    "user_id": 1,
                    "text": "Подготовить недельный план",
                    "notes": "Собрать цели и проверить хвосты",
                    "due_date": "2026-03-08",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(int(payload.get("id", 0)), 55)
        mocked_handle.assert_called_once()
        args, kwargs = mocked_handle.call_args
        self.assertEqual(args[1], "tasks:add")
        self.assertEqual(args[2]["text"], "Подготовить недельный план")
        self.assertEqual(args[2]["notes"], "Собрать цели и проверить хвосты")

    def test_task_delete_endpoint_smoke(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._handle", return_value={"ok": True}),
        ):
            client = TestClient(app)
            response = client.delete(
                "/tasks/15",
                headers=self._auth_headers(),
                params={"user_id": 1},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(bool(payload.get("ok")))

    def test_layout_state_smoke_from_dashboard_html(self):
        with patch.dict(os.environ, self.AUTH_ENV, clear=False):
            client = TestClient(app)
            response = client.get("/dashboard", params={"token": "secret-token"})

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("DECK_STATE_KEY", html)
        self.assertIn("loadDeckState()", html)
        self.assertIn("saveLayoutChanges()", html)
        self.assertIn("resetLayoutForPreset", html)
        self.assertIn("layoutModeBtn", html)
        self.assertIn("layoutSaveBtn", html)
        self.assertIn("layoutResetBtn", html)
        self.assertIn("tasksCompactToggle", html)
        self.assertIn("setTasksCompactMode", html)
        self.assertIn("tasksSortSelect", html)
        self.assertIn("setTasksSortMode", html)
        self.assertIn("sortTasksForView", html)
        self.assertIn("thing-edit-due", html)
        self.assertIn("things-done-stats", html)
        self.assertIn("doneStatsSummary", html)
        self.assertIn("things-done-filter", html)
        self.assertIn("bindDoneFilters", html)
        self.assertIn("worldClockBlock", html)
        self.assertIn("worldClockAddBtn", html)
        self.assertIn("worldClockResetBtn", html)
        self.assertIn("bindCardToolActions()", html)
        self.assertIn("togglePanelPicker(false)", html)
        self.assertIn("opsBlock", html)
        self.assertIn("opsPanelRefreshBtn", html)
        self.assertIn("opsPanelOllamaBtn", html)
        self.assertIn("opsPanelApiReloadBtn", html)


if __name__ == "__main__":
    unittest.main()
