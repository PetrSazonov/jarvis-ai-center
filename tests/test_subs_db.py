import os
import tempfile
import unittest
from datetime import datetime

import db


class SubsDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="subs_", suffix=".db")
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

    def test_add_list_delete(self):
        now = datetime.now().isoformat(timespec="seconds")
        sub_id = db.subs_add(
            user_id=1,
            name="Netflix",
            next_date="2026-03-15",
            period="monthly",
            created_at=now,
        )
        rows = db.subs_list(user_id=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0][0]), sub_id)
        self.assertEqual(str(rows[0][1]), "Netflix")
        self.assertTrue(db.subs_delete(user_id=1, sub_id=sub_id))
        self.assertEqual(db.subs_list(user_id=1), [])

    def test_detailed_subscription_fields(self):
        now = "2026-03-05T10:00:00"
        sub_id = db.subs_add(
            user_id=7,
            name="ChatGPT Pro",
            next_date="2026-03-20",
            period="monthly",
            created_at=now,
            amount=20.0,
            currency="USD",
            note="work assistant",
            category="AI",
            autopay=True,
            remind_days=5,
        )
        rows = db.subs_list_detailed(user_id=7)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(int(row[0]), sub_id)
        self.assertEqual(str(row[1]), "ChatGPT Pro")
        self.assertEqual(float(row[4]), 20.0)
        self.assertEqual(str(row[5]), "USD")
        self.assertEqual(str(row[6]), "work assistant")
        self.assertEqual(str(row[7]), "AI")
        self.assertEqual(int(row[8]), 1)
        self.assertEqual(int(row[9]), 5)


if __name__ == "__main__":
    unittest.main()
