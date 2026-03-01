import os
import tempfile
import unittest
from datetime import datetime

import db


class AssistantMemoryDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="memory_", suffix=".db")
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

    def test_memory_lifecycle(self):
        now = datetime.now().isoformat(timespec="seconds")
        db.memory_set(user_id=10, key="city", value="РњРѕСЃРєРІР°", updated_at=now)
        self.assertEqual(db.memory_get(user_id=10, key="city"), "РњРѕСЃРєРІР°")

        rows = db.memory_list(user_id=10, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "city")
        self.assertEqual(rows[0][1], "РњРѕСЃРєРІР°")

        context = db.memory_build_context(user_id=10, limit=10)
        self.assertIn("User profile memory:", context)
        self.assertIn("- city: РњРѕСЃРєРІР°", context)

        self.assertTrue(db.memory_delete(user_id=10, key="city"))
        self.assertIsNone(db.memory_get(user_id=10, key="city"))

    def test_memory_verification(self):
        now = datetime.now().isoformat(timespec="seconds")
        db.memory_set(
            user_id=11,
            key="home",
            value="Moscow",
            updated_at=now,
            is_verified=False,
            confidence=0.4,
        )
        rows = db.memory_list_detailed(user_id=11, limit=5)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0][2])
        self.assertAlmostEqual(rows[0][3], 0.4, places=2)

        ok = db.memory_mark_verified(user_id=11, key="home", verified=True, updated_at=now)
        self.assertTrue(ok)
        rows = db.memory_list_detailed(user_id=11, limit=5)
        self.assertTrue(rows[0][2])


if __name__ == "__main__":
    unittest.main()
