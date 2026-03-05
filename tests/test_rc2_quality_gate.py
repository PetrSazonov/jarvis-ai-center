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
class RC2QualityGateTests(unittest.TestCase):
    AUTH_ENV = {
        "DASHBOARD_AUTH_ENABLED": "1",
        "DASHBOARD_ACCESS_TOKEN": "secret-token",
    }

    def _auth_headers(self) -> dict[str, str]:
        return {"x-jarvis-token": "secret-token"}

    def test_ingest_smoke_signals_endpoint(self):
        signals_payload = {
            "enabled": True,
            "status": "ok",
            "count": 2,
            "items": [
                {"id": "imap:100", "source": "imap", "title": "IMAP note"},
                {"id": "file:daily.txt", "source": "local_file", "title": "Daily file"},
            ],
            "sources": {
                "imap": {"enabled": True, "status": "ok", "count": 1, "error": ""},
                "local_files": {"enabled": True, "status": "ok", "count": 1, "error": ""},
            },
        }
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._load_signals_panel", new=AsyncMock(return_value=signals_payload)),
        ):
            client = TestClient(app)
            response = client.get("/signals", params={"user_id": 118100880, "limit": 20}, headers=self._auth_headers())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("meta", {}).get("schema"), "signals.v1")
        self.assertEqual(payload.get("signals", {}).get("status"), "ok")
        self.assertEqual(payload.get("signals", {}).get("count"), 2)
        self.assertIn("sources", payload.get("signals", {}))

    def test_rag_smoke_gemma_blocks_without_sources(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._settings", return_value=SimpleNamespace(ollama_model="gemma3:27b", ollama_soft_timeout_seconds=25.0)),
            patch("app.api._handle", side_effect=[{"day_mode": "workday", "energy": 6}, {"items": []}]),
            patch("app.api._trend_panel", return_value={"summary": "stable"}),
            patch(
                "app.api.resolve_rag_for_query",
                new=AsyncMock(
                    return_value={
                        "personal": True,
                        "required": True,
                        "context": "",
                        "citations_block": "",
                        "block_message": "Не могу отвечать по личным данным без источников.",
                    }
                ),
            ),
            patch("app.api.call_ollama", new=AsyncMock(return_value="should_not_run")) as call_mock,
        ):
            client = TestClient(app)
            response = client.post(
                "/gemma/message",
                headers=self._auth_headers(),
                json={"user_id": 118100880, "message": "что у меня в заметках по тренировкам", "mode": "normal", "chat_mode": "full"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("без источников", str(payload.get("answer") or ""))
        self.assertTrue(isinstance(payload.get("quick_actions"), list))
        call_mock.assert_not_called()

    def test_ops_smoke_services_and_actions(self):
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch(
                "app.api._restart_ollama_service",
                return_value={"ok": True, "status": "restarting", "message": "restart requested"},
            ) as restart_mock,
            patch(
                "app.api._trigger_api_reload",
                return_value={"ok": True, "status": "triggered", "message": "reload requested"},
            ) as reload_mock,
        ):
            client = TestClient(app)
            services = client.get("/ops/services", headers=self._auth_headers())
            restart = client.post("/ops/ollama/restart", headers=self._auth_headers())
            reload = client.post("/ops/api/reload", headers=self._auth_headers())

        self.assertEqual(services.status_code, 200)
        services_payload = services.json()
        self.assertIn("status", services_payload)
        self.assertIn("api", services_payload)
        self.assertIn("ollama", services_payload)
        self.assertIn("security", services_payload)

        self.assertEqual(restart.status_code, 200)
        self.assertTrue(restart.json().get("ok"))
        restart_mock.assert_called_once()

        self.assertEqual(reload.status_code, 200)
        self.assertTrue(reload.json().get("ok"))
        reload_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
