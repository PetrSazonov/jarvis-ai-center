import os
import tempfile
import unittest
from datetime import datetime

import db


class ProductivityExtensionsDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="prodext_", suffix=".db")
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

    def test_rule_lifecycle(self):
        now = datetime.now().isoformat(timespec="seconds")
        rid = db.automation_rule_add(
            user_id=101,
            condition_expr="energy<5",
            action_expr="tasks=1",
            created_at=now,
        )
        self.assertGreater(rid, 0)
        rows = db.automation_rule_list(user_id=101, enabled_only=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], rid)
        self.assertTrue(rows[0][3])

        ok = db.automation_rule_set_enabled(
            user_id=101,
            rule_id=rid,
            enabled=False,
            updated_at=now,
        )
        self.assertTrue(ok)
        active = db.automation_rule_list(user_id=101, enabled_only=True)
        self.assertEqual(active, [])

        self.assertTrue(db.automation_rule_delete(user_id=101, rule_id=rid))
        self.assertEqual(db.automation_rule_list(user_id=101), [])

    def test_finance_alert_and_reflection(self):
        now = datetime.now().isoformat(timespec="seconds")
        aid = db.finance_alert_add(
            user_id=202,
            metric="btc",
            operator="<=",
            threshold=65000.0,
            due_days=None,
            created_at=now,
        )
        self.assertGreater(aid, 0)
        rows = db.finance_alert_list(user_id=202, enabled_only=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "btc")

        db.reflection_upsert(
            user_id=202,
            reflection_date="2026-03-01",
            done_text="закрыл 2 задачи",
            drain_text="много чатов",
            remove_text="лишние созвоны",
            tomorrow_rule="90 минут без мессенджеров",
            created_at=now,
            updated_at=now,
        )
        today = db.reflection_get(user_id=202, reflection_date="2026-03-01")
        self.assertIsNotNone(today)
        self.assertEqual(today[3], "90 минут без мессенджеров")
        latest = db.reflection_latest(user_id=202)
        self.assertIsNotNone(latest)
        self.assertEqual(latest[0], "2026-03-01")

        self.assertTrue(db.finance_alert_delete(user_id=202, alert_id=aid))

    def test_memory_timeline_and_profile_flags(self):
        now = datetime.now().isoformat(timespec="seconds")
        db.memory_set(user_id=303, key="city", value="Moscow", updated_at=now)
        db.memory_mark_verified(user_id=303, key="city", verified=True, updated_at=now)
        db.memory_delete(user_id=303, key="city")
        timeline = db.memory_timeline_list(user_id=303, limit=10)
        self.assertGreaterEqual(len(timeline), 2)

        db.user_settings_set_energy_autopilot(user_id=303, enabled=False, updated_at=now)
        db.user_settings_set_cognitive_profile(user_id=303, enabled=False, updated_at=now)
        db.user_settings_set_crisis(
            user_id=303,
            crisis_until="2026-03-02T10:00:00",
            crisis_reason="deadline",
            updated_at=now,
        )
        profile = db.user_settings_get_full(303)
        self.assertFalse(profile["energy_autopilot"])
        self.assertFalse(profile["cognitive_profile"])
        self.assertEqual(profile["crisis_reason"], "deadline")

    def test_decision_journal_lifecycle(self):
        now = datetime.now().isoformat(timespec="seconds")
        did = db.decision_log_add(
            user_id=404,
            decision_text="Запустить новый модуль",
            hypothesis="Увеличит вовлеченность",
            expected_outcome="+20% активностей",
            decision_date="2026-03-01",
            review_after_date="2026-03-15",
            created_at=now,
        )
        self.assertGreater(did, 0)
        rows = db.decision_log_list(user_id=404, only_open=True, limit=10)
        self.assertEqual(len(rows), 1)
        due = db.decision_log_due_reviews(user_id=404, as_of_date="2026-03-16")
        self.assertEqual(len(due), 1)
        ok = db.decision_log_set_outcome(
            user_id=404,
            decision_id=did,
            actual_outcome="Дало +10%",
            score=7,
            updated_at=now,
        )
        self.assertTrue(ok)
        rows = db.decision_log_list(user_id=404, only_open=True, limit=10)
        self.assertEqual(len(rows), 0)


if __name__ == "__main__":
    unittest.main()
