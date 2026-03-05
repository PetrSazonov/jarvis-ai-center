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
class APIAuthBaselineTests(unittest.TestCase):
    def test_today_requires_auth_when_token_configured(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "1",
                "DASHBOARD_ACCESS_TOKEN": "secret-token",
            },
            clear=False,
        ):
            client = TestClient(app)
            response = client.get("/today", params={"user_id": 1})
        self.assertEqual(response.status_code, 401)

    def test_today_authorized_with_header_token(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "1",
                "DASHBOARD_ACCESS_TOKEN": "secret-token",
            },
            clear=False,
        ):
            with patch("app.api.handle_command", return_value={"day_mode": "workday"}) as mocked:
                client = TestClient(app)
                response = client.get(
                    "/today",
                    params={"user_id": 1},
                    headers={"x-jarvis-token": "secret-token"},
                )
        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once()

    def test_dashboard_allows_token_query_and_sets_cookie(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "1",
                "DASHBOARD_ACCESS_TOKEN": "secret-token",
            },
            clear=False,
        ):
            client = TestClient(app)
            response = client.get("/dashboard", params={"token": "secret-token"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("set-cookie", {k.lower(): v for k, v in response.headers.items()})

    def test_untrusted_client_blocked_even_with_valid_token(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "1",
                "DASHBOARD_ACCESS_TOKEN": "secret-token",
                "DASHBOARD_ALLOW_PUBLIC": "0",
            },
            clear=False,
        ):
            with patch("app.api._is_trusted_client", return_value=False):
                client = TestClient(app)
                response = client.get(
                    "/today",
                    params={"user_id": 1},
                    headers={"x-jarvis-token": "secret-token"},
                )
        self.assertEqual(response.status_code, 403)

    def test_dashboard_blocked_for_untrusted_client(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "1",
                "DASHBOARD_ACCESS_TOKEN": "secret-token",
                "DASHBOARD_ALLOW_PUBLIC": "0",
            },
            clear=False,
        ):
            with patch("app.api._is_trusted_client", return_value=False):
                client = TestClient(app)
                response = client.get("/dashboard", params={"token": "secret-token"})
        self.assertEqual(response.status_code, 403)

    def test_debug_events_not_exposed_for_remote_by_default(self):
        def fake_handle(_user_id, _command, _payload=None, return_events=False):
            if return_events:
                return {"result": {"items": []}, "events": [{"name": "tasks.listed"}]}
            return {"items": []}

        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "1",
                "DASHBOARD_ACCESS_TOKEN": "secret-token",
                "API_DEBUG_EVENTS": "1",
                "API_DEBUG_EVENTS_REMOTE": "0",
            },
            clear=False,
        ):
            with patch("app.api.handle_command", side_effect=fake_handle) as mocked:
                client = TestClient(app)
                response = client.get(
                    "/tasks",
                    params={"user_id": 1, "debug": 1},
                    headers={"x-jarvis-token": "secret-token"},
                )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("events", payload)
        mocked.assert_called_once_with(1, "tasks:list", {"limit": 20}, return_events=False)

    def test_debug_events_can_be_enabled_for_remote_explicitly(self):
        def fake_handle(_user_id, _command, _payload=None, return_events=False):
            if return_events:
                return {"result": {"items": []}, "events": [{"name": "tasks.listed"}]}
            return {"items": []}

        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "1",
                "DASHBOARD_ACCESS_TOKEN": "secret-token",
                "API_DEBUG_EVENTS": "1",
                "API_DEBUG_EVENTS_REMOTE": "1",
            },
            clear=False,
        ):
            with patch("app.api.handle_command", side_effect=fake_handle) as mocked:
                client = TestClient(app)
                response = client.get(
                    "/tasks",
                    params={"user_id": 1, "debug": 1},
                    headers={"x-jarvis-token": "secret-token"},
                )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("events", payload)
        mocked.assert_called_once_with(1, "tasks:list", {"limit": 20}, return_events=True)

    def test_ops_services_reports_hardened_security_state(self):
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_AUTH_ENABLED": "1",
                "DASHBOARD_ACCESS_TOKEN": "secret-token",
                "DASHBOARD_ALLOW_PUBLIC": "0",
                "API_DEBUG_EVENTS": "0",
                "API_DEBUG_EVENTS_REMOTE": "0",
            },
            clear=False,
        ):
            client = TestClient(app)
            response = client.get("/ops/services", headers={"x-jarvis-token": "secret-token"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        security = payload.get("security", {})
        self.assertEqual(security.get("auth_required"), True)
        self.assertEqual(security.get("public_access_allowed"), False)
        self.assertEqual(security.get("debug_events_remote"), False)
        self.assertEqual(security.get("status"), "ok")


if __name__ == "__main__":
    unittest.main()
