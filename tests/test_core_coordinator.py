import unittest
from unittest.mock import patch

from core.coordinator import handle_command


class CoordinatorTests(unittest.TestCase):
    def test_today_routes_to_day_os(self):
        with patch("core.coordinator.day_os.get_today", return_value={"ok": True}) as mocked:
            result = handle_command(118100880, "today")
        mocked.assert_called_once_with(user_id=118100880)
        self.assertEqual(result, {"ok": True})

    def test_tasks_list_routes_to_tasks(self):
        with patch("core.coordinator.tasks.list_tasks", return_value=[{"id": 1, "text": "a", "created_at": "x"}]) as mocked:
            result = handle_command(1, "tasks:list", {"limit": 10})
        mocked.assert_called_once_with(user_id=1, limit=10)
        self.assertIn("items", result)

    def test_tasks_add_routes_to_tasks(self):
        with patch("core.coordinator.tasks.add_task", return_value=42) as mocked:
            result = handle_command(5, "tasks:add", {"text": "MIT"})
        mocked.assert_called_once()
        self.assertEqual(result, {"id": 42})

    def test_subs_list_routes_to_subs(self):
        with patch("core.coordinator.subs.list_subs", return_value=[{"id": 1}]) as mocked:
            result = handle_command(9, "subs:list")
        mocked.assert_called_once_with(user_id=9)
        self.assertEqual(result, {"items": [{"id": 1}]})

    def test_unknown_command_raises(self):
        with self.assertRaises(ValueError):
            handle_command(1, "unknown")

    def test_tasks_update_text_routes_to_tasks(self):
        with patch("core.coordinator.tasks.update_task", return_value=True) as mocked:
            result = handle_command(7, "tasks:update", {"task_id": 9, "text": "Новый текст"})
        mocked.assert_called_once_with(
            user_id=7,
            todo_id=9,
            text="Новый текст",
            has_text=True,
            notes=None,
            has_notes=False,
            due_date=None,
            has_due_date=False,
            remind_at=None,
            has_remind_at=False,
            remind_telegram=None,
            has_remind_telegram=False,
        )
        self.assertEqual(result, {"ok": True})


if __name__ == "__main__":
    unittest.main()
