import os
import tempfile
import unittest
from datetime import date, datetime

import db


class CheckinDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="checkin_", suffix=".db")
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

    def test_upsert_and_get(self):
        today = date.today().isoformat()
        now = datetime.now().isoformat(timespec="seconds")
        db.daily_checkin_upsert(
            user_id=42,
            check_date=today,
            done_text="Сделал 3 задачи",
            carry_text="Перенести одну",
            energy=7,
            created_at=now,
            updated_at=now,
        )
        row = db.daily_checkin_get(user_id=42, check_date=today)
        self.assertIsNotNone(row)
        self.assertEqual(str(row[0]), "Сделал 3 задачи")
        self.assertEqual(str(row[1]), "Перенести одну")
        self.assertEqual(int(row[2]), 7)

    def test_upsert_updates_existing(self):
        today = date.today().isoformat()
        now = datetime.now().isoformat(timespec="seconds")
        db.daily_checkin_upsert(
            user_id=7,
            check_date=today,
            done_text="v1",
            carry_text="c1",
            energy=5,
            created_at=now,
            updated_at=now,
        )
        db.daily_checkin_upsert(
            user_id=7,
            check_date=today,
            done_text="v2",
            carry_text="c2",
            energy=8,
            created_at=now,
            updated_at=now,
        )
        row = db.daily_checkin_get(user_id=7, check_date=today)
        self.assertIsNotNone(row)
        self.assertEqual(str(row[0]), "v2")
        self.assertEqual(str(row[1]), "c2")
        self.assertEqual(int(row[2]), 8)


if __name__ == "__main__":
    unittest.main()
