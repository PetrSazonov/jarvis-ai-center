import os
import tempfile
import unittest
from datetime import datetime

import db


class UserSettingsDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="usersettings_", suffix=".db")
        os.close(fd)
        self._tmp_path = path
        db.DATABASE_NAME = self._tmp_path
        db.init_db()

    def tearDown(self) -> None:
        db.DATABASE_NAME = self._orig_db_name
        try:
            os.remove(self._tmp_path)
        except OSError:
            pass

    def test_defaults(self):
        mode, show_conf = db.user_settings_get(123)
        self.assertEqual(mode, "normal")
        self.assertFalse(show_conf)

    def test_set_mode(self):
        now = datetime.now().isoformat(timespec="seconds")
        db.user_settings_set_mode(user_id=5, mode="precise", updated_at=now)
        mode, show_conf = db.user_settings_get(5)
        self.assertEqual(mode, "precise")
        self.assertFalse(show_conf)

    def test_set_confidence(self):
        now = datetime.now().isoformat(timespec="seconds")
        db.user_settings_set_confidence(user_id=5, show_confidence=True, updated_at=now)
        mode, show_conf = db.user_settings_get(5)
        self.assertEqual(mode, "normal")
        self.assertTrue(show_conf)

    def test_extended_profile_settings(self):
        now = datetime.now().isoformat(timespec="seconds")
        db.user_settings_set_lang(user_id=7, lang="en", updated_at=now)
        db.user_settings_set_timezone(user_id=7, timezone_name="UTC", updated_at=now)
        db.user_settings_set_weather_city(user_id=7, weather_city="London", updated_at=now)
        db.user_settings_set_digest_format(user_id=7, digest_format="expanded", updated_at=now)
        db.user_settings_set_quiet_hours(user_id=7, quiet_start="23:00", quiet_end="07:00", updated_at=now)
        db.user_settings_set_response_profile(
            user_id=7,
            response_style="direct",
            response_density="short",
            updated_at=now,
        )
        db.user_settings_set_day_mode(user_id=7, day_mode="travel", updated_at=now)

        profile = db.user_settings_get_full(7)
        self.assertEqual(profile["lang"], "en")
        self.assertEqual(profile["timezone_name"], "UTC")
        self.assertEqual(profile["weather_city"], "London")
        self.assertEqual(profile["digest_format"], "expanded")
        self.assertEqual(profile["quiet_start"], "23:00")
        self.assertEqual(profile["quiet_end"], "07:00")
        self.assertEqual(profile["response_style"], "direct")
        self.assertEqual(profile["response_density"], "short")
        self.assertEqual(profile["day_mode"], "travel")


if __name__ == "__main__":
    unittest.main()
