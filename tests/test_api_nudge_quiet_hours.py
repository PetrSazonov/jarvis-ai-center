import unittest
from unittest.mock import patch

try:
    from app.api import _in_quiet_hours, _pick_gemma_nudge

    API_AVAILABLE = True
except Exception:  # noqa: BLE001
    API_AVAILABLE = False
    _in_quiet_hours = None
    _pick_gemma_nudge = None


@unittest.skipUnless(API_AVAILABLE, "api module is not available in this environment")
class ApiNudgeQuietHoursTests(unittest.TestCase):
    def test_in_quiet_hours_overnight_window(self):
        with patch("app.api.user_settings_get_full", return_value={"quiet_start": "23:00", "quiet_end": "07:00"}):
            from datetime import datetime

            self.assertTrue(_in_quiet_hours(1, datetime.fromisoformat("2026-03-05T23:30:00")))
            self.assertTrue(_in_quiet_hours(1, datetime.fromisoformat("2026-03-06T06:45:00")))
            self.assertFalse(_in_quiet_hours(1, datetime.fromisoformat("2026-03-06T12:00:00")))

    def test_pick_nudge_returns_none_in_quiet_hours(self):
        with (
            patch("app.api._gemma_nudge_state_load", return_value={"cursor": 0, "last_sent_at": ""}),
            patch("app.api.user_settings_get_full", return_value={"quiet_start": "00:00", "quiet_end": "23:59"}),
            patch("app.api._build_gemma_nudge_candidates", return_value=[{"kind": "signal", "message": "x"}]),
        ):
            payload, wait_sec = _pick_gemma_nudge(1, force=False)
        self.assertIsNone(payload)
        self.assertGreaterEqual(int(wait_sec), 60)


if __name__ == "__main__":
    unittest.main()

