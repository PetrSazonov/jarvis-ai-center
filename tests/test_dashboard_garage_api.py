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
class DashboardGarageApiTests(unittest.TestCase):
    AUTH_ENV = {
        "DASHBOARD_AUTH_ENABLED": "1",
        "DASHBOARD_ACCESS_TOKEN": "secret-token",
    }

    def _auth_headers(self) -> dict[str, str]:
        return {"x-jarvis-token": "secret-token"}

    def test_dashboard_garage_smoke(self):
        fake_panel = {
            "assets": [
                {
                    "id": 1,
                    "title": "Mitsubishi Outlander 3G",
                    "kind": "car",
                    "mileage_km": 120000,
                    "insurance_until": "2026-12-01",
                    "docs": [{"label": "Manual", "url": "https://example.com"}],
                }
            ],
            "alerts": [],
            "summary": "1 ТС",
            "updated_at": "2026-03-05T10:00:00",
        }
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api._garage_panel", return_value=fake_panel),
        ):
            client = TestClient(app)
            response = client.get(
                "/dashboard/garage",
                params={"user_id": 118100880},
                headers=self._auth_headers(),
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("assets", payload)
        self.assertEqual(len(payload["assets"]), 1)

    def test_dashboard_garage_update_smoke(self):
        fake_panel = {"assets": [], "alerts": [], "summary": "ok", "updated_at": "2026-03-05T10:00:00"}
        with (
            patch.dict(os.environ, self.AUTH_ENV, clear=False),
            patch("app.api.garage_update_asset", return_value=True) as p_update,
            patch("app.api._garage_panel", return_value=fake_panel),
        ):
            client = TestClient(app)
            response = client.patch(
                "/dashboard/garage/assets/1",
                headers=self._auth_headers(),
                json={
                    "user_id": 118100880,
                    "mileage_km": 120500,
                    "insurance_until": "2026-12-10",
                    "maintenance_due_date": "2026-05-01",
                },
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("asset_id"), 1)
        self.assertIn("garage", payload)
        p_update.assert_called_once()


if __name__ == "__main__":
    unittest.main()

